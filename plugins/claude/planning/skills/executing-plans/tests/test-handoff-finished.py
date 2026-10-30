#!/usr/bin/env python3
"""Finished requests use the real CLI and independently owned disposable runs."""
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import plan_state


class Finished(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='finished-fixture-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        subprocess.run(['git', '-c', 'init.templateDir=', 'init', '-q', '-b', 'feature', str(self.root)], check=True)
        self.plan = self.root / 'work-plan.md'
        self.plan.write_text(self.single())
        self.hid = 'h-' + 'd' * 20
        self.channel = self.root / '.claude/handoffs'
        self.channel.mkdir(parents=True)
        self.request = {'protocol': 'planning-handoff', 'version': 2,
                        'managed_session_id': 'worker', 'requested_at': '2026-01-01T00:00:00Z',
                        'request_id': self.hid}
        self.write_request()
        self.revision = 0
        self.op('init', {'plan': str(self.plan), 'source': 'Fixture owner authorized work',
                         'scope': 'Synthetic fixture only'})
        self.op('finish', {'evidence': 'Synthetic close-out complete'})

    def single(self):
        return ('# Project Plan: synthetic\n## Stage 1: Work\n### Task 1.1: Work\n'
                '- **Status:** [x]\n### Stage 1 Gate\n- [x] synthetic check\n'
                '**Completed:** 2026-01-01 — synthetic\n')

    def op(self, name, payload):
        result = plan_state.execute(self.root, name, payload, self.revision, 'fixture-' + str(self.revision))
        self.revision = result['revision']

    def write_request(self):
        (self.channel / 'request.json').write_text(json.dumps(self.request))

    def run_cli(self, expected=0, sid='worker', root=None, plan=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith('PLANNING_')}
        env['PLANNING_SUPERVISOR_ID_CMD'] = shlex.join([sys.executable, '-c', f'print({sid!r})'])
        env['PLANNING_HANDOFF_VERSIONS'] = '1,2'
        result = subprocess.run([sys.executable, str(SCRIPTS / 'handoff-envelope.py'), 'finished',
                                 '--root', str(root or self.root), '--plan', str(plan or self.plan)],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def finished(self):
        return self.channel / f'{self.hid}.finished.json'

    def master(self, pending=False):
        sub = self.root / 'sub-plan.md'
        sub.write_text((self.single() if not pending else self.single().replace('[x]', '[ ]'))
                       .replace('# Project Plan: synthetic', f'# Project Plan: synthetic\nMaster: ./{self.plan.name}'))
        self.plan.write_text('# Master Plan: synthetic\n## Sub-plans\n### Sub-plan 1: Work\n'
                             '- **Status:** [' + (' ' if pending else 'x') + ']\n'
                             f'- **Plan:** ./{sub.name}\n- **Depends on:** none\n'
                             '**Gate:**\n- [x] integration\n**Completed:** 2026-01-01 — synthetic\n')
        return sub

    def test_finished_single_plan_correlates_exact_request_and_retains_terminal_state(self):
        before = (self.root / '.claude/plan-progress.json').read_bytes()
        self.run_cli()
        data = json.loads(self.finished().read_text())
        self.assertEqual(set(data), {'protocol', 'version', 'event', 'handoff_id', 'managed_session_id',
                                    'timestamp', 'plan', 'source_root', 'request_id', 'requested_at', 'outcome'})
        self.assertEqual(data['event'], 'HANDOFF_FINISHED')
        self.assertEqual(data['version'], 2)
        self.assertEqual(data['handoff_id'], self.hid)
        self.assertEqual(data['request_id'], self.hid)
        self.assertEqual(data['requested_at'], self.request['requested_at'])
        self.assertEqual(data['source_root'], str(self.root))
        self.assertEqual(data['plan'], str(self.plan))
        self.assertEqual(data['outcome'], 'completed')
        self.assertEqual(before, (self.root / '.claude/plan-progress.json').read_bytes())
        self.assertFalse(list(self.channel.glob('*.ready.json')))

    def test_finished_master_requires_all_subplans_and_master_closeout(self):
        self.master()
        self.run_cli()
        self.assertTrue(self.finished().exists())

    def test_unfinished_dependent_subplan_is_not_whole_master_success(self):
        self.master(pending=True)
        result = self.run_cli(expected=3)
        self.assertIn('workflow-incomplete', result.stdout)
        self.assertFalse(self.finished().exists())

    def test_subplan_with_next_executable_work_cannot_emit_completion(self):
        master = self.root / 'journey-master-plan.md'
        later = self.root / 'later-plan.md'
        later.write_text(self.single().replace('[x]', '[ ]'))
        self.plan.write_text(self.single().replace('# Project Plan: synthetic',
                              f'# Project Plan: synthetic\nMaster: ./{master.name}'))
        master.write_text('# Master Plan: journey\n## Sub-plans\n### Sub-plan 1: Work\n'
                          '- **Status:** [x]\n- **Plan:** ./work-plan.md\n- **Depends on:** none\n'
                          '**Gate:**\n- [x] integration\n### Sub-plan 2: Later\n'
                          '- **Status:** [ ]\n- **Plan:** ./later-plan.md\n- **Depends on:** Sub-plan 1\n'
                          '**Gate:**\n- [ ] integration\n')
        result = self.run_cli(expected=3)
        self.assertIn('workflow-incomplete', result.stdout)
        self.assertFalse(self.finished().exists())

    def test_missing_closeout_and_pending_or_malformed_gate_are_refused(self):
        for text in (self.single().replace('**Completed:** 2026-01-01 — synthetic\n', ''),
                     self.single().replace('- [x] synthetic check', '- [ ] synthetic check'),
                     self.single().replace('- [x] synthetic check', '- [~] synthetic check'),
                     self.single().replace('- [x] synthetic check', '- [x] synthetic check\n- [!] invalid'),
                     self.single().replace('- **Status:** [x]', '- **Status:** [ ]')):
            self.plan.write_text(text)
            self.run_cli(expected=3)
            self.assertFalse(self.finished().exists())

    def test_no_request_and_wrong_session_are_silent_noops(self):
        (self.channel / 'request.json').unlink()
        self.assertEqual(self.run_cli().stdout.strip(), 'no-request')
        self.write_request()
        self.assertEqual(self.run_cli(sid='other').stdout.strip(), 'no-request')
        self.assertFalse(self.finished().exists())

    def test_v1_request_is_not_reinterpreted_as_finished(self):
        self.request.update(version=1)
        self.request.pop('request_id')
        self.write_request()
        self.assertEqual(self.run_cli().stdout.strip(), 'no-request')
        self.assertFalse(self.finished().exists())

    def test_malformed_and_symlink_requests_are_not_consumed(self):
        for key, value in (('requested_at', 'invalid'), ('request_id', 'bad'), ('extra', True)):
            original = self.request.copy()
            self.request[key] = value
            self.write_request()
            self.assertEqual(self.run_cli().stdout.strip(), 'no-request')
            self.request = original
        self.write_request()
        (self.channel / 'request.json').rename(self.channel / 'elsewhere.json')
        (self.channel / 'request.json').symlink_to('elsewhere.json')
        self.assertEqual(self.run_cli().stdout.strip(), 'no-request')
        self.assertFalse(self.finished().exists())

    def test_replay_is_byte_identical_and_new_request_timestamp_cannot_replace_outcome(self):
        self.run_cli()
        original = self.finished().read_bytes()
        self.run_cli()
        self.assertEqual(original, self.finished().read_bytes())
        self.request['requested_at'] = '2026-01-02T00:00:00Z'
        self.write_request()
        self.run_cli(expected=3)
        self.assertEqual(original, self.finished().read_bytes())

    def test_cancelled_failed_or_blocked_plan_is_not_success(self):
        for marker in ('Status: cancelled', 'Status: failed', '**Abandoned:** 2026-01-01',
                       '**Blocked-accepted:** 2026-01-01 — synthetic'):
            self.plan.write_text(self.single().replace('## Stage', marker + '\n## Stage', 1))
            self.run_cli(expected=3)
            self.assertFalse(self.finished().exists())

    def test_nonterminal_owned_run_is_refused_without_mutation(self):
        other = self.root / 'other'
        other.mkdir()
        subprocess.run(['git', '-c', 'init.templateDir=', 'init', '-q', '-b', 'feature', str(other)], check=True)
        plan_state.execute(other, 'init', {'plan': str(self.plan), 'source': 'Fixture owner',
                                         'scope': 'Synthetic fixture'}, 0, 'init')
        (other / '.claude/handoffs').mkdir()
        (other / '.claude/handoffs/request.json').write_text(json.dumps(self.request))
        self.run_cli(expected=3, root=other)
        self.assertEqual(plan_state.execute(other, 'show', {})['state']['disposition'], 'working')
        self.assertFalse(list(other.glob('.claude/handoffs/*.finished.json')))

    def test_cancelled_owned_run_keeps_its_disposition_and_cancellation(self):
        other = self.root / 'cancelled'
        other.mkdir()
        subprocess.run(['git', '-c', 'init.templateDir=', 'init', '-q', '-b', 'feature', str(other)], check=True)
        plan_state.execute(other, 'init', {'plan': str(self.plan), 'source': 'Fixture owner',
                                         'scope': 'Synthetic fixture'}, 0, 'init')
        plan_state.execute(other, 'set-blocker', {
            'disposition': 'awaiting_owner_decision', 'prevented_operation': 'synthetic continuation',
            'evidence': 'fixture owner cancelled', 'dependency': 'fresh owner authorization',
            'remaining_work': [], 'cancelled': True, 'owner_source': 'Fixture owner: cancel'}, 1, 'cancel')
        (other / '.claude/handoffs').mkdir()
        (other / '.claude/handoffs/request.json').write_text(json.dumps(self.request))
        before = (other / '.claude/plan-progress.json').read_bytes()
        self.run_cli(expected=3, root=other)
        self.assertEqual(before, (other / '.claude/plan-progress.json').read_bytes())
        self.assertFalse(list(other.glob('.claude/handoffs/*.finished.json')))

    def test_corrupt_existing_outcome_is_not_replaced(self):
        self.finished().write_text('{broken')
        self.run_cli(expected=3)
        self.assertEqual(self.finished().read_text(), '{broken')

    def test_wrong_owned_plan_refused(self):
        other = self.root / 'other-plan.md'
        other.write_text(self.single())
        self.run_cli(expected=3, plan=other)
        self.assertFalse(self.finished().exists())

    def test_finished_schema_is_readable_and_v2_request_is_pending(self):
        spec = importlib.util.spec_from_file_location('wire', SCRIPTS / 'handoff-envelope.py')
        wire = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wire)
        env = {'PLANNING_SUPERVISOR_ID_CMD': shlex.join([sys.executable, '-c', "print('worker')"])}
        self.assertTrue(wire.request_pending(str(self.root), env))
        self.run_cli()
        self.assertEqual(wire.read_handoff_file(str(self.root), self.finished().name)['event'], 'HANDOFF_FINISHED')


if __name__ == '__main__':
    unittest.main()
