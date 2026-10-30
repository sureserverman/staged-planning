"""Correlate a terminal workflow with its exact v2 supervisor request."""
import os
import re
from pathlib import Path

import handoff_destination as destination
import plan_state
from handoff_v2 import BASE, absolute, bounded, canonical

REQUEST_KEYS = {'protocol', 'version', 'managed_session_id', 'requested_at', 'request_id'}
FINISHED_KEYS = BASE | {'source_root', 'request_id', 'requested_at', 'outcome'}
UTC = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ')
ID = re.compile(r'h-[0-9a-f]{20}')


def schema(data, root):
    event = data.get('event')
    if event is None:
        return (set(data) == REQUEST_KEYS and isinstance(data.get('request_id'), str)
                and bool(ID.fullmatch(data['request_id'])) and timestamp(data.get('requested_at')))
    return (event == 'HANDOFF_FINISHED' and set(data) == FINISHED_KEYS
            and data['outcome'] == 'completed' and absolute(data['plan'])
            and data['source_root'] == os.path.realpath(root)
            and data['request_id'] == data['handoff_id']
            and timestamp(data['requested_at']) and timestamp(data['timestamp']))


def timestamp(value):
    return isinstance(value, str) and bool(UTC.fullmatch(value))


def workflow_done(plan):
    text = destination.read_plan(plan)
    destination.runnable(text)
    master = (plan if destination.PARSER.is_master_plan(text, plan)
              else destination.master_path(plan, text))
    if master is None:
        destination.require(destination.plan_done(text), 'workflow-incomplete')
        return plan
    if plan != master:
        destination.require(destination.plan_done(text), 'workflow-incomplete')
    mt = destination.read_plan(master)
    destination.runnable(mt)
    visible = '\n'.join(destination.visible_lines(mt))
    destination.require(destination.PARSER.COMPLETED_RE.search(visible)
                        and not destination.PARSER.contract_warnings(visible)
                        and destination.gates_done(visible, master=True), 'workflow-incomplete')
    register = destination.entries(master, mt)
    destination.require(plan == master or plan in [e['path'] for e in register.values()], 'master-metadata')
    for entry in register.values():
        st = destination.read_plan(entry['path'])
        destination.runnable(st)
        destination.require(entry['status'] == 'done' and entry['gates']
                            and destination.plan_done(st), 'workflow-incomplete')
        destination.require(destination.master_path(entry['path'], st) == master, 'master-metadata')
    return master


def finished(wire, root, plan, env):
    request = wire.read_handoff_file(root, wire.REQUEST)
    if request is None or request['version'] != 2 or set(request) != REQUEST_KEYS:
        print('no-request')
        return 0
    sid = wire.supervised_session_id(env, root)
    if sid is None or sid != request['managed_session_id']:
        print('no-request')
        return 0
    root, _ = destination.git_identity(os.path.realpath(root))
    plan = Path(plan).resolve()
    result = plan_state.result(Path(root), 'show', {})
    destination.require(result['status'] == 'ok', 'state-ownership')
    state = result['state']
    destination.require(Path(state['plan']).resolve() == plan, 'state-ownership')
    destination.require(state['disposition'] == 'complete' and state['phase'] == 'closeout',
                        'run-not-runnable')
    workflow_done(plan)
    data = wire.envelope('HANDOFF_FINISHED', request['request_id'], sid, str(plan))
    data.update(version=2, source_root=root, request_id=request['request_id'],
                requested_at=request['requested_at'], outcome='completed')
    name = f"{request['request_id']}.finished.json"
    previous = wire.read_handoff_file(root, name)
    if previous is not None:
        destination.require({k: v for k, v in previous.items() if k != 'timestamp'}
                            == {k: v for k, v in data.items() if k != 'timestamp'}, 'stale-finished')
    else:
        bounded(data, name, wire.MAX_READ_BYTES)
        destination.require(wire.write_handoff_file(root, name, canonical(data) + b'\n', exclusive=True),
                            'stale-finished')
    print(os.path.join(root, wire.CLAUDE_DIR, wire.HANDOFF_DIR, name))
    return 0
