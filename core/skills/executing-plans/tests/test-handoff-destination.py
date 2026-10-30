#!/usr/bin/env python3
"""Synthetic repositories and external records exercise destination selection."""
import importlib.util
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


_MODULE = None

def load():
    global _MODULE
    if _MODULE is not None:
        return _MODULE
    spec = importlib.util.spec_from_file_location('handoff_destination', SCRIPTS / 'handoff_destination.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _MODULE = module
    return module


class Destinations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='destination-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.a, self.b, self.c = [self.repo(n) for n in ('orchard', 'river', 'summit')]
        self.records = self.base / 'records store'
        self.records.mkdir()
        self.master = self.records / 'journey-master-plan.md'
        self.plans = [self.records / f'sub-{n}-plan.md' for n in (1, 2, 3)]
        for p, root in zip(self.plans, (self.a, self.b, self.c)):
            p.write_text(self.subplan(root))
        self.write_master()

    def repo(self, name):
        p = self.base / name
        subprocess.run(['git', '-c', 'init.templateDir=', 'init', '-q', '-b', 'feature', str(p)], check=True)
        subprocess.run(['git', '-C', str(p), '-c', 'user.name=Fixture', '-c',
                        'user.email=fixture@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'fixture'], check=True)
        return p

    def subplan(self, root=None, done=False):
        return ('# Project Plan: synthetic work\nMaster: ./journey-master-plan.md\n'
                + (f'Execution root: `{root}`\nExecution branch: `feature`\n' if root else '')
                + '## Stage 1: Work\n### Task 1.1: Work\n- **Status:** [' + ('x' if done else ' ') + ']\n'
                + '### Stage 1 Gate\n- [' + ('x' if done else ' ') + '] synthetic check\n'
                + ('**Completed:** 2026-01-01 — synthetic\n' if done else ''))

    def write_master(self, done=(1,), overrides=None):
        text = '# Master Plan: journey\n## Owner decisions\nnone\n## Sub-plans\n'
        for n, plan in enumerate(self.plans, 1):
            status = 'x' if n in done else ' '
            gate = (overrides or {}).get(n, status)
            text += (f'### Sub-plan {n}: Work {n}\n- **Status:** [{status}]\n'
                     f'- **Plan:** ./{plan.name}\n- **Depends on:** '
                     + ('none' if n == 1 else f'Sub-plan {n-1}')
                     + f'\n**Gate:**\n- [{gate}] integration\n')
            if n in done:
                plan.write_text(self.subplan((self.a, self.b, self.c)[n-1], done=True))
        self.master.write_text(text)

    def resolve(self, **kw):
        return load().resolve_destination(self.plans[0], self.a, 'Task 1.1', **kw)

    def refused(self, code, fn):
        with self.assertRaises(load().DestinationError) as ctx:
            fn()
        self.assertEqual(ctx.exception.code, code)

    def test_external_records_select_next_dependency_not_markdown_folder(self):
        d = self.resolve(boundary=True)
        self.assertEqual(d, {'root': str(self.b), 'branch': 'feature', 'plan': str(self.plans[1]),
                             'locator': 'Task 1.1', 'master_plan': str(self.master)})

    def test_within_subplan_retains_its_explicit_root(self):
        d = load().resolve_destination(self.plans[1], self.b, 'Task 1.1')
        self.assertEqual(d['root'], str(self.b))
        self.assertEqual(d['master_plan'], str(self.master))

    def test_legacy_same_root_only_when_no_explicit_metadata(self):
        self.plans[1].write_text(self.subplan())
        self.assertEqual(self.resolve(boundary=True)['root'], str(self.a))

    def test_explicit_incomplete_metadata_does_not_fall_back(self):
        self.plans[1].write_text(self.subplan(self.b).replace('Execution branch: `feature`\n', ''))
        self.refused('destination-metadata', lambda: self.resolve(boundary=True))

    def test_entry_metadata_agrees_with_subplan(self):
        t = self.master.read_text().replace(f'- **Plan:** ./{self.plans[1].name}',
            f'- **Plan:** ./{self.plans[1].name}\n- **Execution root:** `{self.c}`\n- **Execution branch:** `feature`')
        self.master.write_text(t)
        self.refused('destination-metadata', lambda: self.resolve(boundary=True))

    def test_pending_or_blocked_master_gate_cannot_be_skipped(self):
        for marker in (' ', '~'):
            self.write_master(overrides={1: marker})
            self.refused('pending-master-gate', lambda: self.resolve(boundary=True))

    def test_completed_entry_requires_completed_subplan(self):
        self.plans[0].write_text(self.subplan(self.a))
        self.refused('pending-subplan', lambda: self.resolve(boundary=True))

    def test_malformed_or_missing_task_status_cannot_hide_unfinished_work(self):
        good = self.plans[0].read_text()
        for marker in ('- **Status:** [!]', '- **Status:** done', '', '- **Status:** [x]\n- **Status:** [x]'):
            self.plans[0].write_text(good.replace('### Stage 1 Gate',
                '### Task 1.2: Hidden\n' + marker + '\n### Stage 1 Gate'))
            self.refused('pending-subplan', lambda: self.resolve(boundary=True))

    def test_invalid_gate_rows_and_empty_gates_are_not_green(self):
        good = self.plans[0].read_text()
        master_good = self.master.read_text()
        for marker in ('- [!] invalid', '- [] empty', '* [x] unsupported marker', '- unmarked criterion'):
            self.plans[0].write_text(good.replace('- [x] synthetic check', '- [x] synthetic check\n' + marker))
            self.refused('pending-subplan', lambda: self.resolve(boundary=True))
            self.plans[0].write_text(good)
            self.master.write_text(master_good.replace('- [x] integration', '- [x] integration\n' + marker))
            self.refused('pending-master-gate', lambda: self.resolve(boundary=True))
            self.master.write_text(master_good)
        self.plans[0].write_text(good.replace('- [x] synthetic check', ''))
        self.refused('pending-subplan', lambda: self.resolve(boundary=True))

    def test_fenced_completion_marker_cannot_close_current_subplan(self):
        p = self.plans[0]
        p.write_text(p.read_text().replace('**Completed:** 2026-01-01 — synthetic',
                                         '```text\n**Completed:** 2026-01-01 — synthetic\n```'))
        self.refused('pending-subplan', lambda: self.resolve(boundary=True))

    def test_ambiguous_entries_require_selection(self):
        self.master.write_text(self.master.read_text().replace('Sub-plan 2\n**Gate:**', 'Sub-plan 1\n**Gate:**'))
        self.refused('ambiguous-destination', lambda: self.resolve(boundary=True))
        self.assertEqual(self.resolve(boundary=True, selection=3)['root'], str(self.c))

    def test_selection_cannot_bypass_dependencies(self):
        self.refused('not-executable', lambda: self.resolve(boundary=True, selection=3))

    def test_master_origin_requires_completed_current_entry(self):
        resolve = lambda **kw: load().resolve_destination(self.master, self.a, 'Task 1.1', boundary=True, **kw)
        self.refused('current-subplan', lambda: resolve())
        self.refused('current-subplan', lambda: resolve(current_subplan=99))
        self.refused('pending-subplan', lambda: resolve(current_subplan=2))
        self.assertEqual(resolve(current_subplan=1)['root'], str(self.b))
        self.write_master(overrides={1: ' '})
        self.refused('pending-master-gate', lambda: resolve(current_subplan=1))

    def test_subplan_origin_cannot_claim_another_current_entry(self):
        self.refused('current-subplan', lambda: self.resolve(boundary=True, current_subplan=2))

    def test_no_executable_work_is_distinct_from_finished(self):
        self.master.write_text(self.master.read_text().replace('Sub-plan 1\n**Gate:**', 'Sub-plan 3\n**Gate:**'))
        self.refused('no-executable-work', lambda: self.resolve(boundary=True))
        self.write_master(done=(1, 2, 3))
        self.assertIsNone(self.resolve(boundary=True))

    def test_cancelled_failed_and_waiting_runs_are_refused(self):
        for disposition in ('cancelled', 'failed', 'waiting_external', 'awaiting_owner_decision'):
            self.refused('run-not-runnable', lambda: self.resolve(boundary=True, disposition=disposition))

    def test_removed_root_branch_mismatch_and_nested_folder(self):
        self.plans[1].write_text(self.subplan(self.base / 'removed'))
        self.refused('destination-unavailable', lambda: self.resolve(boundary=True))
        self.plans[1].write_text(self.subplan(self.b).replace('`feature`', '`other`'))
        self.refused('branch-mismatch', lambda: self.resolve(boundary=True))
        nested = self.b / 'nested'
        nested.mkdir()
        self.plans[1].write_text(self.subplan(nested))
        self.refused('destination-root', lambda: self.resolve(boundary=True))

    def test_existing_worktree_is_exact_destination(self):
        wt = self.base / 'river worktree'
        subprocess.run(['git', '-C', str(self.b), 'worktree', 'add', '-q', '-b', 'next', str(wt)], check=True)
        self.plans[1].write_text(self.subplan(wt).replace('`feature`', '`next`'))
        self.assertEqual(self.resolve(boundary=True)['root'], str(wt))

    def test_unknown_dependencies_duplicate_ids_and_backlink_refused(self):
        original = self.master.read_text()
        self.master.write_text(original.replace('Sub-plan 1\n**Gate:**', 'Sub-plan 99\n**Gate:**'))
        self.refused('master-metadata', lambda: self.resolve(boundary=True))
        self.master.write_text(original.replace('### Sub-plan 3:', '### Sub-plan 2:'))
        self.refused('master-metadata', lambda: self.resolve(boundary=True))
        self.master.write_text(original)
        self.plans[1].write_text(self.subplan(self.b).replace('journey-master-plan.md', 'other-master-plan.md'))
        self.refused('master-metadata', lambda: self.resolve(boundary=True))

    def test_refuses_unbounded_plan_and_stale_locator(self):
        self.refused('locator-mismatch', lambda: load().resolve_destination(self.plans[1], self.b, 'Task 9.9'))
        self.plans[1].write_bytes(b'x' * (8 * 1024 * 1024 + 1))
        self.refused('plan-unreadable', lambda: self.resolve(boundary=True))


class EnvelopeDestinations(unittest.TestCase):
    repo = Destinations.repo
    subplan = Destinations.subplan
    write_master = Destinations.write_master

    def setUp(self):
        Destinations.setUp(self)
        self.writer = SCRIPTS / 'handoff-envelope.py'
        self.hid = 'h-' + 'a' * 20
        self.checkpoint(self.plans[0], self.hid, self.b, self.plans[1])
        self.state(self.a, self.plans[0])
        self.hold(self.a, self.hid)

    def checkpoint(self, source_plan, hid, root, target_plan, branch='feature'):
        source_plan.write_text(source_plan.read_text() + (
            f'\n**RESUME HERE (2026-01-01):**\nhandoff_id: {hid}\n'
            f'cwd: {root}\nbranch: {branch}\nplan: {target_plan}\nnext: Task 1.1\n'))

    def state(self, root, plan, operation='init', payload=None, revision=0):
        payload = payload or {'plan': str(plan), 'source': 'Fixture owner authorized synthetic work',
                              'scope': 'Synthetic fixture only', 'stage': 1, 'task': '1.1'}
        p = subprocess.run([sys.executable, str(SCRIPTS / 'plan-state.py'), operation,
                            '--repo', str(root), '--expected-revision', str(revision),
                            '--operation-id', 'fixture-' + operation + '-' + str(revision)], input=json.dumps(payload),
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads((root / '.claude/plan-progress.json').read_text())

    def hold(self, root, hid, revision=1):
        return self.state(root, None, operation='set-blocker', revision=revision, payload={
            'disposition': 'handoff', 'prevented_operation': 'synthetic successor work',
            'evidence': 'synthetic measured stage gate', 'dependency': 'synthetic adoption',
            'remaining_work': ['synthetic next task'], 'reason': 'rule requested: synthetic rollover',
            'handoff_id': hid})

    def run_writer(self, cmd, root=None, source=None, plan=None, hid=None, caps='1,2',
                   sid='predecessor', more=(), expected=0, cwd=None):
        root = root or self.a
        args = [sys.executable, str(self.writer), cmd, '--root', str(root),
                '--handoff-id', hid or self.hid]
        if source:
            args += ['--handoff-root', str(source)]
        if plan:
            args += ['--plan', str(plan)]
        env = {k: v for k, v in os.environ.items() if not k.startswith('PLANNING_')}
        env['PLANNING_SUPERVISOR_ID_CMD'] = shlex.join([sys.executable, '-c', f'print({sid!r})'])
        if caps is not None:
            env['PLANNING_HANDOFF_VERSIONS'] = caps
        p = subprocess.run(args + list(more), cwd=str(cwd or root), env=env,
                           text=True, capture_output=True, timeout=20)
        self.assertEqual(p.returncode, expected, (args, p.stdout, p.stderr))
        return p

    def ready(self, **kw):
        return self.run_writer('ready', plan=self.plans[0],
            more=('--next', 'Task 1.1', '--sub-plan-boundary'), **kw)

    def envelope(self, suffix='ready', root=None, hid=None):
        return (root or self.a) / '.claude/handoffs' / f'{hid or self.hid}.{suffix}.json'

    def test_a_to_b_and_b_to_c_preserve_source_channel_and_independent_owners(self):
        source_state = json.loads((self.a / '.claude/plan-progress.json').read_text())
        self.ready()
        frozen = json.loads(self.envelope().read_text())
        self.assertEqual(frozen['version'], 2)
        self.assertEqual(frozen['source_root'], str(self.a))
        self.assertEqual(frozen['destination']['root'], str(self.b))
        self.assertEqual(frozen['predecessor_session_id'], 'predecessor')
        p = self.run_writer('plan', root=self.b, source=self.a, sid='successor')
        self.assertEqual(p.stdout.strip(), str(self.plans[1]))
        self.run_writer('verify', root=self.b, source=self.a, plan=self.plans[1])
        target_state = self.state(self.b, self.plans[1])
        self.assertNotEqual(source_state['run_id'], target_state['run_id'])
        self.assertEqual(target_state['owner']['root'], str(self.b))
        self.run_writer('accept', root=self.b, source=self.a, plan=self.plans[1], sid='successor')
        accepted = json.loads(self.envelope('accepted').read_text())
        self.assertEqual(accepted['destination'], frozen['destination'])
        self.assertEqual(accepted['source_root'], str(self.a))
        self.assertEqual(accepted['predecessor_session_id'], 'predecessor')
        self.assertEqual(accepted['managed_session_id'], 'successor')
        self.assertEqual(accepted['ready_sha256'], hashlib.sha256(json.dumps(
            frozen, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest())
        self.assertFalse((self.b / '.claude/handoffs').exists())
        self.assertEqual(json.loads((self.a / '.claude/plan-progress.json').read_text()), source_state)
        self.write_master(done=(1, 2))
        hid = 'h-' + 'b' * 20
        self.checkpoint(self.plans[1], hid, self.c, self.plans[2])
        self.hold(self.b, hid)
        self.run_writer('ready', root=self.b, plan=self.plans[1], hid=hid, sid='successor',
                        more=('--next', 'Task 1.1', '--sub-plan-boundary'))
        self.state(self.c, self.plans[2])
        self.run_writer('accept', root=self.c, source=self.b, plan=self.plans[2], hid=hid, sid='third')
        self.assertTrue(self.envelope('accepted', root=self.b, hid=hid).exists())

    def test_old_reader_capability_refuses_cross_root_without_ready(self):
        for caps in (None, '1'):
            self.ready(caps=caps, expected=3)
            self.assertFalse(self.envelope().exists())
        self.run_writer('ready', plan=self.plans[0], caps=None, expected=3)
        self.assertFalse(self.envelope().exists())

    def test_source_cwd_identity_and_state_must_agree(self):
        self.ready(cwd=self.c, expected=3)
        self.assertFalse(self.envelope().exists())
        self.state(self.a, self.plans[0], operation='set-blocker', revision=2, payload={
            'disposition': 'awaiting_owner_decision', 'prevented_operation': 'synthetic gate',
            'evidence': 'synthetic pending owner decision', 'dependency': 'fixture owner',
            'remaining_work': ['synthetic continuation']})
        self.ready(expected=3)
        self.assertFalse(self.envelope().exists())

    def test_ready_requires_recorded_hold_with_same_handoff_id(self):
        source = self.repo('runnable-source')
        self.state(source, self.plans[0])
        self.run_writer('ready', root=source, plan=self.plans[0], expected=3,
                        more=('--next', 'Task 1.1', '--sub-plan-boundary'))
        self.assertFalse(self.envelope(root=source).exists())
        self.hold(source, 'h-' + 'f' * 20)
        self.run_writer('ready', root=source, plan=self.plans[0], expected=3,
                        more=('--next', 'Task 1.1', '--sub-plan-boundary'))
        self.assertFalse(self.envelope(root=source).exists())

    def test_master_origin_ready_freezes_completed_current_entry(self):
        source = self.repo('master-source')
        self.checkpoint(self.master, self.hid, self.b, self.plans[1])
        self.state(source, self.master)
        self.hold(source, self.hid)
        self.run_writer('ready', root=source, plan=self.master, expected=3,
                        more=('--next', 'Task 1.1', '--sub-plan-boundary'))
        self.run_writer('ready', root=source, plan=self.master,
                        more=('--next', 'Task 1.1', '--sub-plan-boundary', '--current-subplan', '1'))
        body = json.loads(self.envelope(root=source).read_text())
        self.assertEqual(body['selection'], {'boundary': True, 'subplan': 2, 'current_subplan': 1})
        self.run_writer('verify', root=self.b, source=source, plan=self.plans[1])

    def test_wrong_cwd_branch_plan_or_id_cannot_adopt(self):
        self.ready()
        for kw, code in (({'cwd': self.c}, 'cwd-mismatch'),
                         ({'plan': self.plans[2]}, 'plan-mismatch'),
                         ({'hid': 'h-' + 'c' * 20}, 'no-ready')):
            p = self.run_writer('verify', root=self.b, source=self.a,
                                **({'plan': self.plans[1]} | kw), expected=3)
            self.assertEqual(p.stdout.strip(), code)
        subprocess.run(['git', '-C', str(self.b), 'checkout', '-q', '-b', 'wrong'], check=True)
        p = self.run_writer('verify', root=self.b, source=self.a, plan=self.plans[1], expected=3)
        self.assertEqual(p.stdout.strip(), 'branch-mismatch')
        self.assertFalse(self.envelope('accepted').exists())

    def test_restarted_ready_is_identical_and_cannot_retarget(self):
        self.ready()
        before = self.envelope().read_bytes()
        self.ready()
        self.assertEqual(self.envelope().read_bytes(), before)
        self.plans[1].write_text(self.subplan(self.c))
        self.ready(expected=3)
        self.assertEqual(self.envelope().read_bytes(), before)
        self.run_writer('verify', root=self.b, source=self.a, plan=self.plans[1], expected=3)

    def test_stale_checkpoint_and_frozen_payload_fail_closed(self):
        self.ready()
        original = self.plans[0].read_text()
        for needle, replacement in ((self.hid, 'h-'+'d'*20), ('next: Task 1.1', 'next: Task 9.9'),
                                    (f'plan: {self.plans[1]}', f'plan: {self.plans[2]}')):
            self.plans[0].write_text(original.replace(needle, replacement))
            self.run_writer('verify', root=self.b, source=self.a, plan=self.plans[1], expected=3)
        self.plans[0].write_text(original)
        body = json.loads(self.envelope().read_text())
        body['unrecognized'] = 'unsafe'
        self.envelope().write_text(json.dumps(body))
        self.run_writer('verify', root=self.b, source=self.a, plan=self.plans[1], expected=3)

    def test_accept_requires_destination_owner_and_never_reuses_another_run(self):
        self.ready()
        self.run_writer('accept', root=self.b, source=self.a, plan=self.plans[1], sid='successor', expected=3)
        self.assertFalse(self.envelope('accepted').exists())
        self.state(self.b, self.plans[2])
        before = (self.b / '.claude/plan-progress.json').read_bytes()
        self.run_writer('accept', root=self.b, source=self.a, plan=self.plans[1], sid='successor', expected=3)
        self.assertEqual((self.b / '.claude/plan-progress.json').read_bytes(), before)

    def test_one_outcome_and_correlated_failure_preserves_source(self):
        self.ready()
        self.run_writer('fail', root=self.b, source=self.a, plan=self.plans[1], sid='successor',
                        more=('--code', 'cwd-mismatch'))
        failed = json.loads(self.envelope('failed').read_text())
        self.assertEqual(failed['source_root'], str(self.a))
        self.assertEqual(failed['destination']['root'], str(self.b))
        self.state(self.b, self.plans[1])
        self.run_writer('accept', root=self.b, source=self.a, plan=self.plans[1], sid='successor', expected=1)
        self.assertFalse(self.envelope('accepted').exists())

    def test_predecessor_or_wrong_destination_cannot_claim_failure(self):
        self.ready()
        for kw in ({'root': self.a}, {'root': self.b, 'source': self.a, 'cwd': self.a, 'sid': 'successor'},
                   {'root': self.b, 'source': self.a}):
            self.run_writer('fail', plan=self.plans[1], more=('--code', 'cwd-mismatch'), expected=3, **kw)
            self.assertFalse(self.envelope('failed').exists())
            self.assertFalse((self.a / '.claude/handoffs' / ('.' + self.hid + '.claim')).exists())
        self.state(self.b, self.plans[1])
        self.run_writer('accept', root=self.b, source=self.a, plan=self.plans[1], sid='successor')

    def test_v2_same_root_legacy_plan_and_existing_worktree(self):
        local = self.records / 'local-plan.md'
        local.write_text(self.subplan().replace('Master: ./journey-master-plan.md\n', ''))
        self.checkpoint(local, self.hid, self.a, local)
        # Use another source root to avoid altering or replacing the fixture's owned run.
        local_root = self.repo('local')
        self.checkpoint(local, self.hid, local_root, local)
        self.state(local_root, local)
        self.hold(local_root, self.hid)
        self.run_writer('ready', root=local_root, plan=local, more=('--next', 'Task 1.1'))
        self.run_writer('verify', root=local_root, plan=local)
        self.state(local_root, local, operation='set-blocker', revision=2, payload={
            'disposition': 'working', 'prevented_operation': 'synthetic adopted task',
            'evidence': 'verified same-root handoff', 'dependency': 'handoff resolved',
            'remaining_work': ['synthetic task']})
        self.run_writer('accept', root=local_root, plan=local, sid='successor')
        accepted = json.loads(self.envelope('accepted', root=local_root).read_text())
        self.assertEqual(accepted['managed_session_id'], 'successor')
        wt = self.base / 'river worktree'
        subprocess.run(['git', '-C', str(self.b), 'worktree', 'add', '-q', '-b', 'next', str(wt)], check=True)
        self.plans[1].write_text(self.subplan(wt).replace('`feature`', '`next`'))
        self.checkpoint(self.plans[0], self.hid, wt, self.plans[1], branch='next')
        self.ready()
        self.run_writer('verify', root=wt, source=self.a, plan=self.plans[1])
        state = self.state(wt, self.plans[1])
        self.assertEqual(state['owner']['root'], str(wt))
        self.run_writer('accept', root=wt, source=self.a, plan=self.plans[1], sid='successor')

    def test_same_root_accept_requires_resumed_task_and_latest_recorded_handoff(self):
        for defect, code in (('still-held', 'run-not-runnable'),
                             ('wrong-task', 'state-ownership'), ('newer-handoff', 'id-mismatch')):
            with self.subTest(defect=defect):
                root = self.repo('same-root-' + defect)
                plan = self.records / (defect + '-plan.md')
                plan.write_text(self.subplan().replace('Master: ./journey-master-plan.md\n', ''))
                self.checkpoint(plan, self.hid, root, plan)
                self.state(root, plan)
                self.hold(root, self.hid)
                self.run_writer('ready', root=root, plan=plan, more=('--next', 'Task 1.1'))
                revision = 2
                if defect == 'newer-handoff':
                    self.hold(root, 'h-' + 'b' * 20, revision=revision)
                    revision += 1
                if defect != 'still-held':
                    self.state(root, plan, operation='set-blocker', revision=revision, payload={
                        'disposition': 'working', 'prevented_operation': 'synthetic task',
                        'evidence': 'synthetic verified handoff', 'dependency': 'synthetic adoption',
                        'remaining_work': ['synthetic task']})
                    revision += 1
                if defect == 'wrong-task':
                    self.state(root, plan, operation='transition', revision=revision,
                               payload={'phase': 'task', 'stage': 9, 'task': '9.9'})
                result = self.run_writer('accept', root=root, plan=plan, sid='successor', expected=3)
                self.assertEqual(result.stdout.strip(), code)
                self.assertFalse(self.envelope('accepted', root=root).exists())

    def test_cross_root_accept_still_requires_the_source_to_be_held(self):
        self.ready()
        self.state(self.b, self.plans[1])
        self.state(self.a, self.plans[0], operation='set-blocker', revision=2, payload={
            'disposition': 'working', 'prevented_operation': 'synthetic task',
            'evidence': 'synthetic source was resumed', 'dependency': 'synthetic task',
            'remaining_work': ['synthetic task']})
        result = self.run_writer('accept', root=self.b, source=self.a,
                                 plan=self.plans[1], sid='successor', expected=3)
        self.assertEqual(result.stdout.strip(), 'run-not-runnable')
        self.assertFalse(self.envelope('accepted').exists())

    def test_outsize_emission_is_refused_before_publishing(self):
        # A long legal plan path makes a v2 envelope exceed the channel read bound.
        deep = self.records
        for i in range(15):
            deep /= str(i) + 'x' * 170
        deep.mkdir(parents=True)
        distant = deep / 'next-plan.md'
        distant.write_text(self.subplan(self.b).replace('./journey-master-plan.md', str(self.master)))
        self.master.write_text(self.master.read_text().replace('./sub-2-plan.md', str(distant)))
        self.checkpoint(self.plans[0], self.hid, self.b, distant)
        self.ready(expected=3)
        self.assertFalse(self.envelope().exists())


if __name__ == '__main__':
    unittest.main()
