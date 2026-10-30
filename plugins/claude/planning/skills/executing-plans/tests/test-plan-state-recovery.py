#!/usr/bin/env python3
"""`recover` and `resolve-recovery`: a lost snapshot comes back blocked, its gaps named."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from workflow_state_cases import Case, SCRIPT

CONTRACT = HERE.parent / 'references/execution-state-contract.md'
PROGRESS = HERE.parent / 'scripts/plan-progress.py'
MISSING = ['receipts', 'verifications', 'revision_continuity', 'unlisted_gate_accounts']
GATE = {'id': 'stage-1', 'repair_revision': 'sha-1', 'checks': ['task-test', 'review']}


def cite(at, evidence=0):
    return {'evidence': evidence, 'at': at}


class Recovery(Case):
    def setUp(self):
        super().setUp()
        self.init()
        self.call('transition', {'phase': 'gate', 'gate': GATE})
        self.run_id = self.state()['run_id']
        self.snapshot = self.repo/'.claude/plan-progress.json'
        self.pointers = Path(self.git('rev-parse', '--absolute-git-dir'))/'plan-state-runs'
        self.pointer = next(self.pointers.iterdir())
        self.pointer_bytes = self.pointer.read_bytes()
        self.evidence = Path(self.temp.name)/'transcript.jsonl'
        self.evidence.write_text('{"receipt": "begin-round"}\n')
        self.older = self.snapshot.read_bytes()
        self.snapshot.unlink()
        self.rev = 0

    def payload(self, **changes):
        payload = {
            'run_id': self.run_id, 'plan': 'fixture-plan.md',
            'source': 'owner: build the recovery', 'scope': 'fixture',
            'gate': GATE, 'rounds': {'completed': 1, 'budget': 2, 'reserved': True},
            'round_evidence': [{'round': 1, 'verdict': 'failed', 'source': cite('line 40')}],
            'budget_source': cite('line 3'), 'gate_accounts': {},
            'reservation_source': cite('line 47'),
            'last_known': {'revision': 47, 'operation': 'begin-round', 'source': cite('line 47')},
            'known_operation_ids': ['old-begin-round'],
            'source_evidence': [{'path': str(self.evidence),
                                 'sha256': hashlib.sha256(self.evidence.read_bytes()).hexdigest()}],
            'stage': 3, 'task': '3.3', 'task_desc': 'the probe',
        }
        payload.update(changes)
        return payload

    def recover(self, **changes):
        return self.call('recover', self.payload(**changes), expected=0, op_id='recover-1')

    def refused(self, status, *args, **kwargs):
        self.call(*args, **kwargs, status=status)

    def assert_untouched(self):
        self.assertFalse(self.snapshot.exists())
        self.assertEqual(self.pointer.read_bytes(), self.pointer_bytes)
        self.assertTrue(self.evidence.exists())

    def blocker(self, disposition, **extra):
        return {'disposition': disposition, 'prevented_operation': 'x', 'evidence': 'y',
                'dependency': 'z', 'remaining_work': [], **extra}

    def resolve(self):
        return self.call('resolve-recovery', {'source': 'owner: reviewed the history',
                                              'scope': 'fixture', 'evidence': 'review note'})

    def test_a_lost_snapshot_comes_back_blocked_with_its_account_and_gaps(self):
        receipt = self.recover()
        self.assertEqual((receipt['run_id'], receipt['revision']), (self.run_id, 1))
        state = self.state()
        self.assertEqual(state['run_id'], self.run_id)
        self.assertEqual((state['disposition'], state['phase'], state['qualification']),
                         ('awaiting_owner_decision', 'blocked', 'blocked'))
        self.assertEqual((state['stage'], state['task'], state['gate']), (3, '3.3', GATE))
        rounds = state['rounds']
        self.assertEqual((rounds['completed'], rounds['budget'], rounds['active']['number']), (1, 2, 2))
        self.assertIsNone(rounds['active']['verification'])
        self.assertEqual(rounds['active']['recovery_source'], cite('line 47'))
        self.assertEqual((state['remediation_round'], state['remediation_budget']), (2, 2))
        self.assertEqual(list(state['receipts']), ['recover-1'])
        record = state['recovery']
        self.assertEqual(record['missing_history'], MISSING)
        self.assertEqual(record['last_known']['revision'], 47)
        self.assertEqual(record['round_evidence'][0]['verdict'], 'failed')
        self.assertEqual(record['source_evidence'], self.payload()['source_evidence'])
        self.assertIsNone(record['resolution'])
        self.assertEqual(self.pointer.read_bytes(), self.pointer_bytes)

    def test_bad_recoveries_refuse_and_leave_pointer_and_evidence_alone(self):
        good = self.payload()
        cases = {
            'another run': ('conflict', {'run_id': '00000000-0000-4000-8000-000000000000'}),
            'evidence changed': ('conflict', {'source_evidence': [
                {'path': str(self.evidence), 'sha256': '0'*64}]}),
            'no evidence': ('state_error', {'source_evidence': []}),
            'evidence missing on disk': ('state_error', {'source_evidence': [
                {'path': str(self.evidence)+'.gone', 'sha256': '0'*64}]}),
            'relative evidence path': ('state_error', {'source_evidence': [
                {'path': 'transcript.jsonl', 'sha256': good['source_evidence'][0]['sha256']}]}),
            'a spent round with no evidence': ('state_error', {'round_evidence': []}),
            'evidence for a round not spent': ('state_error', {'round_evidence': [
                good['round_evidence'][0], {'round': 2, 'verdict': 'passed', 'source': cite('s')}]}),
            'an invented verdict': ('state_error', {'round_evidence': [
                {'round': 1, 'verdict': 'green', 'source': cite('s')}]}),
            'reserved past the ceiling': ('state_error', {
                'rounds': {'completed': 2, 'budget': 2, 'reserved': True},
                'round_evidence': [{'round': n, 'verdict': 'failed', 'source': cite('s')} for n in (1, 2)]}),
            'a reservation with no source': ('state_error', {'reservation_source': cite(' ')}),
            'a claim citing no evidence': ('state_error', {'budget_source': cite('line 3', evidence=1)}),
            'a free-text source': ('state_error', {'budget_source': 'the owner said so'}),
            'no known operation ids': ('state_error', {'known_operation_ids': []}),
            'a count too large to spend': ('state_error', {
                'rounds': {'completed': 10**30, 'budget': 10**30, 'reserved': False},
                'round_evidence': []}),
            'a reservation source with no reservation': ('state_error', {
                'rounds': {'completed': 1, 'budget': 2, 'reserved': False}}),
            'a counter that is not a count': ('state_error', {
                'rounds': {'completed': True, 'budget': 2, 'reserved': True}}),
            'a caller-set field': ('state_error', {'revision': 48}),
            'a saved account for the current gate': ('state_error', {'gate_accounts': {
                'stage-1': {'completed': 1, 'budget': 2, 'source': cite('s')}}}),
            'a saved account past the ceiling': ('state_error', {'gate_accounts': {
                'stage-0': {'completed': 3, 'budget': 3, 'source': cite('s')}}}),
            'no last known point': ('state_error', {'last_known': {'revision': 0, 'operation': 'o', 'source': cite('s')}}),
        }
        for name, (status, change) in cases.items():
            with self.subTest(name):
                self.call('recover', self.payload(**change), expected=0, status=status)
                self.assert_untouched()
        for required in ('reservation_source', 'budget_source', 'gate_accounts'):
            incomplete = self.payload()
            del incomplete[required]
            self.call('recover', incomplete, expected=0, status='state_error')
        self.call('recover', self.payload(), expected=0, op_id='old-begin-round', status='conflict')
        self.call('recover', self.payload(), expected=47, status='conflict')
        self.assert_untouched()

    def test_a_snapshot_on_disk_is_never_replaced(self):
        self.snapshot.write_bytes(self.older)   # a stale backup of the same run
        self.call('recover', self.payload(), expected=0, status='conflict')
        self.assertEqual(self.snapshot.read_bytes(), self.older)
        self.call('recover', self.payload(), expected=json.loads(self.older)['revision'], status='conflict')
        self.assertEqual(self.snapshot.read_bytes(), self.older)
        self.snapshot.write_text('{corrupt')
        self.call('recover', self.payload(), expected=0, status='state_error')
        self.assertEqual(self.snapshot.read_text(), '{corrupt')
        self.assertEqual(self.pointer.read_bytes(), self.pointer_bytes)

    def test_no_pointer_means_nothing_to_recover(self):
        self.pointer.unlink()
        self.call('recover', self.payload(), expected=0, status='state_error')
        self.assertFalse(self.snapshot.exists())

    def test_a_pointer_that_is_not_an_object_refuses(self):
        (self.pointers/('0'*64+'.json')).write_text('[]')
        self.call('recover', self.payload(), expected=0, status='state_error')
        self.assert_untouched()

    def test_two_pointers_naming_the_run_are_ambiguous(self):
        (self.pointers/('0'*64+'.json')).write_bytes(self.pointer_bytes)
        self.call('recover', self.payload(), expected=0, status='state_error')
        self.assert_untouched()

    def test_another_branch_cannot_recover_the_run(self):
        self.git('checkout', '-qb', 'elsewhere')
        self.call('recover', self.payload(), expected=0, status='conflict')
        self.assert_untouched()

    def test_a_retry_returns_the_first_receipt_and_a_changed_payload_conflicts(self):
        first = self.recover()
        state = self.state()
        self.assertEqual(self.recover(), first)
        self.assertEqual(self.state(), state)
        self.call('recover', self.payload(task='other'), expected=0, op_id='recover-1', status='conflict')
        self.assertEqual(self.state(), state)

    def test_two_concurrent_recoveries_commit_once(self):
        wrapper = Path(self.temp.name)/'slow-writer.py'
        wrapper.write_text('import runpy, sys, time\n'
            'sys.path.insert(0, '+repr(str(SCRIPT.parent))+')\n'
            'import plan_state\n'
            'original = plan_state.replace_json\n'
            'def slow(*a, **k):\n'
            '    time.sleep(1.5)\n'
            '    return original(*a, **k)\n'
            'plan_state.replace_json = slow\n'
            'runpy.run_path('+repr(str(SCRIPT))+', run_name="__main__")\n')
        processes = [subprocess.Popen([sys.executable, str(wrapper), 'recover', '--repo', str(self.repo),
                     '--expected-revision', '0', '--operation-id', 'r'+str(i)], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(2)]
        raw = json.dumps(self.payload())
        statuses = sorted(json.loads(p.communicate(raw, timeout=20)[0])['status'] for p in processes)
        self.assertEqual(statuses, ['conflict', 'ok'])
        self.assertEqual(self.state()['revision'], 1)

    def test_unresolved_history_refuses_new_work_and_completion(self):
        self.recover()
        before = self.state()
        for operation, payload in (
                ('begin-round', {'gate_id': 'stage-1'}),
                ('complete-round', {'gate_id': 'stage-1'}),
                ('finish', {'evidence': 'done'}),
                ('transition', {'phase': 'task'}),
                ('set-blocker', self.blocker('working')),
                ('set-blocker', self.blocker('repairing')),
                ('authorize', {'source': 'owner', 'scope': 'fixture', 'budget': 3})):
            with self.subTest(operation=operation, payload=payload):
                self.call(operation, payload, status='conflict')
                self.assertEqual(self.state(), before)

    def test_unresolved_history_still_lets_a_run_verify_and_stop_cleanly(self):
        self.recover()
        self.call('record-verification', {'gate_id': 'stage-1', 'repair_revision': 'sha-1',
                  'evidence': 'fresh run', 'checks': {'task-test': 'passed', 'review': 'failed'}})
        self.call('authorize', {'source': 'owner: same ceiling', 'scope': 'fixture', 'budget': 2})
        self.call('set-blocker', self.blocker('handoff', reason='measured 50%'))
        state = self.state()
        self.assertEqual((state['disposition'], state['qualification']), ('handoff', 'blocked'))
        self.assertIsNone(state['recovery']['resolution'])

    def test_resolving_opens_the_reserved_round_and_grants_no_other(self):
        self.recover()
        self.call('resolve-recovery', {'source': 'owner', 'scope': 'another', 'evidence': 'e'}, status='conflict')
        self.call('resolve-recovery', {'source': ' ', 'scope': 'fixture', 'evidence': 'e'}, status='state_error')
        self.call('resolve-recovery', {'source': 'owner', 'scope': 'fixture'}, status='state_error')
        self.assertIsNone(self.state()['recovery']['resolution'])
        self.resolve()
        state = self.state()
        self.assertEqual(state['recovery']['resolution'],
                         {'source': 'owner: reviewed the history', 'evidence': 'review note'})
        self.assertEqual(state['disposition'], 'awaiting_owner_decision')
        self.assertEqual(state['qualification'], 'blocked')
        self.assertEqual(state['rounds']['budget'], 2)
        self.call('resolve-recovery', {'source': 'owner', 'scope': 'fixture', 'evidence': 'e'}, status='conflict')
        self.call('set-blocker', self.blocker('repairing'))
        self.call('begin-round', {'gate_id': 'stage-1'}, status='conflict')
        self.call('record-verification', {'gate_id': 'stage-1', 'repair_revision': 'sha-1',
                  'evidence': 'fresh run', 'checks': {'task-test': 'failed', 'review': 'passed'}})
        self.call('complete-round', {'gate_id': 'stage-1'})
        state = self.state()
        self.assertEqual((state['rounds']['completed'], state['rounds']['active']), (2, None))
        self.assertEqual(state['recovery']['round_evidence'][0]['verdict'], 'failed')
        self.assertEqual(state['recovery']['missing_history'], MISSING)
        self.call('begin-round', {'gate_id': 'stage-1'}, status='budget_exhausted')

    def test_an_operation_id_from_before_the_loss_cannot_run_again(self):
        self.recover()
        self.resolve()
        self.call('set-blocker', self.blocker('repairing'))
        self.call('record-verification', {'gate_id': 'stage-1', 'repair_revision': 'sha-1',
                  'evidence': 'fresh', 'checks': {'task-test': 'passed', 'review': 'passed'}})
        before = self.state()
        self.call('complete-round', {'gate_id': 'stage-1'}, op_id='old-begin-round', status='conflict')
        self.assertEqual(self.state(), before)

    def test_the_review_needs_its_own_source(self):
        self.recover()
        self.call('resolve-recovery', {'source': 'owner: build the recovery', 'scope': 'fixture',
                                       'evidence': 'e'}, status='conflict')
        self.assertIsNone(self.state()['recovery']['resolution'])

    def test_authorize_cannot_launder_the_recovering_source(self):
        self.recover()
        self.call('authorize', {'source': 'owner: later amendment', 'scope': 'fixture'})
        self.call('resolve-recovery', {'source': 'owner: build the recovery', 'scope': 'fixture',
                                       'evidence': 'e'}, status='conflict')
        self.assertIsNone(self.state()['recovery']['resolution'])
        self.call('resolve-recovery', {'source': 'owner: later amendment', 'scope': 'fixture',
                                       'evidence': 'e'})
        self.assertEqual(self.state()['recovery']['recovered_under'], 'owner: build the recovery')

    def test_a_listed_account_survives_and_an_unlisted_gate_is_named_as_a_gap(self):
        self.recover_with_account()
        self.resolve()
        self.call('set-blocker', self.blocker('working'), status='ok')

    def recover_with_account(self):
        self.call('recover', self.without_reservation(), expected=0, op_id='recover-1')
        state = self.state()
        self.assertEqual(state['gate_accounts']['stage-0'], {'completed': 2, 'budget': 2, 'active': None})
        self.assertEqual(state['recovery']['account_sources']['stage-0'], cite('line 9'))
        self.assertIn('unlisted_gate_accounts', state['recovery']['missing_history'])

    def without_reservation(self):
        payload = self.payload(rounds={'completed': 1, 'budget': 2, 'reserved': False},
                               gate_accounts={'stage-0': {'completed': 2, 'budget': 2, 'source': cite('line 9')}})
        del payload['reservation_source']
        return payload

    def test_resolve_needs_a_recovered_run(self):
        self.snapshot.write_bytes(self.older)
        self.rev = json.loads(self.older)['revision']
        self.call('resolve-recovery', {'source': 'owner', 'scope': 'fixture', 'evidence': 'e'}, status='conflict')

    def test_a_reader_refuses_a_record_that_contradicts_its_state(self):
        self.recover()
        good = json.loads(self.snapshot.read_text())
        sys.path.insert(0, str(SCRIPT.parent))
        import plan_state

        def forge(change):
            state = json.loads(json.dumps(good))
            change(state)
            state['integrity'] = plan_state.digest({k: v for k, v in state.items() if k != 'integrity'})
            self.snapshot.write_text(json.dumps(state))
            self.call('show', status='state_error')

        def runnable(state):
            state.update(disposition='repairing', phase='gate', blocker=None)

        def qualified(state):
            state['qualification'] = 'pass'

        def no_gaps(state):
            state['recovery']['missing_history'] = []

        def no_source(state):
            del state['recovery']['recovered_under']

        def extra(state):
            state['recovery']['extra'] = 1

        for change in (runnable, qualified, no_gaps, no_source, extra):
            with self.subTest(change.__name__):
                forge(change)
        tampered = json.loads(json.dumps(good))
        tampered['recovery']['last_known']['revision'] = 1
        self.snapshot.write_text(json.dumps(tampered))
        self.call('show', status='state_error')

    def test_the_budget_reader_refuses_until_the_history_is_resolved(self):
        self.recover()
        def check():
            return subprocess.run([sys.executable, str(PROGRESS), '--budget-check'], cwd=self.repo,
                                  capture_output=True, text=True, timeout=20)
        p = check()
        self.assertNotEqual(p.returncode, 0, p.stdout+p.stderr)
        self.assertIn('unresolved', p.stdout+p.stderr)
        self.resolve()
        self.assertEqual(check().returncode, 0)

    def test_the_contract_states_both_operations(self):
        contract = CONTRACT.read_text()
        for word in ('`recover`', '`resolve-recovery`', 'missing_history'):
            self.assertIn(word, contract)


if __name__ == '__main__':
    unittest.main()
