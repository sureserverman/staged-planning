"""Negotiated destination-aware handoffs; the envelope module owns channel I/O."""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import handoff_destination as destination
import plan_state

CAPABILITIES = 'PLANNING_HANDOFF_VERSIONS'
BASE = {'protocol', 'version', 'event', 'handoff_id', 'managed_session_id', 'timestamp', 'plan'}
ROUTING = {'source_root', 'source_plan', 'predecessor_session_id', 'destination', 'selection'}
DESTINATION = {'root', 'branch', 'plan', 'locator', 'master_plan'}
SELECTION = {'boundary', 'subplan', 'current_subplan'}
ERRORS = ('manual-continuation', 'destination-metadata', 'destination-unavailable', 'destination-root',
          'branch-mismatch', 'master-metadata', 'pending-master-gate', 'pending-subplan',
          'ambiguous-destination', 'not-executable', 'no-executable-work', 'run-not-runnable',
          'plan-unreadable', 'locator-mismatch', 'current-subplan', 'plan-metadata',
          'plan-mismatch', 'state-ownership', 'stale-destination', 'oversized-envelope',
          'session-mismatch')


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')


def fingerprint(data):
    return hashlib.sha256(canonical(data)).hexdigest()


def size_refusal(name, size, limit):
    return f"refused: {name} would be {size} bytes, over the reader's limit of {limit}"


def bounded(data, name, limit):
    """Refuse an envelope the reader would refuse; call it before anything is written."""
    size = len(canonical(data)) + 1
    if size > limit:
        print(size_refusal(name, size, limit), file=sys.stderr)
        raise destination.DestinationError('oversized-envelope')


def absolute(value):
    return isinstance(value, str) and os.path.isabs(value) and not any(ord(c) < 32 for c in value)


def schema(data, root):
    """Strict v2 schema only; filesystem/plan validation belongs to verify()."""
    if data.get('event') not in ('HANDOFF_READY', 'HANDOFF_ACCEPTED', 'HANDOFF_FAILED'):
        return False
    expected = BASE | ROUTING
    if data['event'] != 'HANDOFF_READY':
        expected |= {'ready_sha256'}
    if data['event'] == 'HANDOFF_FAILED':
        expected |= {'failure_code'}
    if set(data) != expected:
        return False
    d, s = data['destination'], data['selection']
    if not (isinstance(d, dict) and set(d) == DESTINATION
            and isinstance(s, dict) and set(s) == SELECTION):
        return False
    if not all(absolute(data[k]) for k in ('source_root', 'source_plan', 'plan')):
        return False
    if (os.path.realpath(root) != data['source_root'] or not absolute(d['root']) or not absolute(d['plan'])
            or d['plan'] != data['plan'] or not (d['master_plan'] is None or absolute(d['master_plan']))):
        return False
    if (not isinstance(d['branch'], str) or not d['branch']
            or not isinstance(d['locator'], str) or not re.fullmatch(r'Task \d+\.\d+', d['locator'])
            or type(s['boundary']) is not bool
            or any(x is not None and (type(x) is not int or x < 1) for x in (s['subplan'], s['current_subplan']))
            or (not s['boundary'] and (s['subplan'] is not None or s['current_subplan'] is not None))):
        return False
    if not isinstance(data['predecessor_session_id'], str) or not re.fullmatch(
            r'[A-Za-z0-9_-]{1,128}', data['predecessor_session_id']):
        return False
    if data['event'] == 'HANDOFF_READY' and data['predecessor_session_id'] != data['managed_session_id']:
        return False
    if data['event'] != 'HANDOFF_READY' and (not isinstance(data['ready_sha256'], str)
            or not re.fullmatch(r'[0-9a-f]{64}', data['ready_sha256'])):
        return False
    return (isinstance(data.get('timestamp'), str)
            and bool(re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', data['timestamp']))
            and (data['event'] != 'HANDOFF_FAILED' or data['failure_code'] in ERRORS
                 or data['failure_code'] in ('id-mismatch', 'no-ready', 'cwd-mismatch', 'plan-missing')))


def owned(root, plan, *, adopting=False, locator=None, handoff_id=None):
    result = plan_state.result(Path(root), 'show', {})
    destination.require(result['status'] == 'ok', 'state-ownership')
    state = result['state']
    destination.require(Path(state['plan']).resolve() == Path(plan).resolve(), 'state-ownership')
    destination.require(state['disposition'] in (('working', 'repairing') if adopting else
                                                ('handoff',)), 'run-not-runnable')
    if adopting:
        destination.require(state['task'] == locator.removeprefix('Task '), 'state-ownership')
    else:
        destination.require(state['blocker'].get('handoff_id') == handoff_id, 'id-mismatch')
    return state


def resolve(source_plan, root, locator, selection, disposition='working'):
    return destination.resolve_destination(source_plan, root, locator,
        boundary=selection['boundary'], selection=selection['subplan'],
        current_subplan=selection['current_subplan'], disposition=disposition)


def checkpoint(wire, ready):
    text = wire.read_plan(ready['source_plan'])
    destination.require(text is not None, 'plan-missing')
    lines = wire.last_block(text)
    destination.require(lines is not None, 'id-mismatch')
    expected = {'handoff_id': ready['handoff_id'], 'cwd': ready['destination']['root'],
                'branch': ready['destination']['branch'], 'plan': ready['plan'],
                'next': ready['destination']['locator']}
    for key, expected_value in expected.items():
        values = [line[len(key)+1:].strip().strip('`') for line in lines if line.startswith(key + ':')]
        if key == 'next':
            values = [v.split(' — ', 1)[0] for v in values]
        code = {'handoff_id': 'id-mismatch', 'cwd': 'cwd-mismatch', 'branch': 'branch-mismatch',
                'plan': 'plan-mismatch', 'next': 'locator-mismatch'}[key]
        destination.require(values == [expected_value], code)


def verify(wire, root, source, handoff_id, plan, ready, *, adopting=False):
    destination.require(Path(plan).resolve() == Path(ready['plan']), 'plan-mismatch')
    destination.require(Path.cwd().resolve() == Path(root).resolve()
                        == Path(ready['destination']['root']), 'cwd-mismatch')
    destination.git_identity(root, ready['destination']['branch'])
    if adopting:
        # A same-root stage successor resumes the one owned run before accepting.
        # Its current state cannot still be handoff. Prove that the latest saved
        # handoff in that same run is this one; never relax cross-root ownership.
        destination.require(Path(source).resolve() == Path(root).resolve(), 'state-ownership')
        state = owned(source, ready['source_plan'], adopting=True,
                      locator=ready['destination']['locator'])
        holds = [row['receipt'] for row in state['receipts'].values()
                 if row['receipt'].get('operation') == 'set-blocker'
                 and row['receipt'].get('disposition') == 'handoff']
        latest = max(holds, key=lambda receipt: receipt['revision'], default={})
        destination.require((latest.get('blocker') or {}).get('handoff_id') == handoff_id,
                            'id-mismatch')
    else:
        state = owned(source, ready['source_plan'], handoff_id=handoff_id)
    current = resolve(ready['source_plan'], source, ready['destination']['locator'],
                      ready['selection'], state['disposition'])
    destination.require(current == ready['destination'], 'stale-destination')
    checkpoint(wire, ready)


def ready(wire, args, env, sid):
    root = os.path.realpath(args.root)
    destination.require(str(Path.cwd().resolve()) == root, 'cwd-mismatch')
    state = owned(root, args.plan, handoff_id=args.handoff_id)
    selection = {'boundary': args.sub_plan_boundary, 'subplan': args.subplan,
                 'current_subplan': args.current_subplan}
    d = resolve(args.plan, root, args.next, selection, state['disposition'])
    destination.require(d is not None, 'no-executable-work')
    versions = env.get(CAPABILITIES, '1').split(',')
    if '2' not in versions:
        destination.require(d['root'] == root and d['plan'] == str(Path(args.plan).resolve())
                            and '1' in versions, 'manual-continuation')
        return None
    if selection['boundary']:
        register = destination.entries(Path(d['master_plan']), destination.read_plan(d['master_plan']))
        selection['subplan'] = next(n for n, e in register.items() if str(e['path']) == d['plan'])
        if selection['current_subplan'] is None:
            selection['current_subplan'] = next(n for n, e in register.items()
                                                if e['path'] == Path(args.plan).resolve())
    data = wire.envelope('HANDOFF_READY', args.handoff_id, sid, d['plan'])
    data.update(version=2, source_root=root, source_plan=str(Path(args.plan).resolve()),
                predecessor_session_id=sid, destination=d, selection=selection)
    checkpoint(wire, data)
    path = f'{args.handoff_id}.ready.json'
    bounded(data, path, wire.MAX_READ_BYTES)
    largest_outcome = dict(data, event='HANDOFF_FAILED', managed_session_id='x' * 128,
                           ready_sha256='f' * 64, failure_code=max(ERRORS, key=len))
    bounded(largest_outcome, f'the largest outcome of {path}', wire.MAX_READ_BYTES)
    previous = wire.read_handoff_file(root, path)
    if previous is not None:
        same = {k: v for k, v in data.items() if k != 'timestamp'}
        destination.require({k: v for k, v in previous.items() if k != 'timestamp'} == same, 'stale-destination')
        return previous
    destination.require(wire.write_handoff_file(root, path, canonical(data) + b'\n', exclusive=True), 'stale-destination')
    return data


def outcome(wire, args, source, data, sid):
    destination.require(Path.cwd().resolve() == Path(args.root).resolve()
                        == Path(data['destination']['root']), 'cwd-mismatch')
    destination.require(sid != data['predecessor_session_id'], 'session-mismatch')
    if args.cmd == 'accept':
        verify(wire, args.root, source, args.handoff_id, args.plan, data,
               adopting=Path(source).resolve() == Path(args.root).resolve())
        owned(args.root, data['plan'], adopting=True, locator=data['destination']['locator'])
    result = dict(data)
    result.update(event=wire.EVENTS[args.cmd][0], managed_session_id=sid,
                  timestamp=wire.envelope('', '', '', None)['timestamp'], ready_sha256=fingerprint(data))
    if args.cmd == 'fail':
        result['failure_code'] = args.code
    bounded(result, f'{args.handoff_id}.{wire.EVENTS[args.cmd][1]}.json', wire.MAX_READ_BYTES)
    return result
