#!/usr/bin/env python3
"""Protocol corpus and subprocess acceptance. Run bare for all implemented groups."""
import argparse
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'scripts' / 'plan-state.py'
GROUPS = ('contract', 'storage', 'rounds', 'dispositions', 'strategy')


class Contract(unittest.TestCase):
    def test_contract_and_corpus_cover_master_invariants(self):
        corpus = json.loads((HERE / 'fixtures/workflow-recovery/manifest.json').read_text())
        contract = (HERE.parent / 'references/execution-state-contract.md').read_text()
        self.assertEqual(set(corpus['invariants']), set(range(1, 12)))
        for operation in ('init', 'show', 'transition', 'begin-round', 'record-verification',
                          'complete-round', 'authorize', 'set-blocker', 'strategy-review',
                          'migrate', 'finish'):
            self.assertIn(operation, contract)
        required = {'active-two', 'completed-two', 'missing', 'corrupt', 'partial-write',
                    'interruption', 'concurrent', 'worktree', 'retry', 'extension',
                    'no-go-repair', 'premises', 'baseline', 'environment', 'strategy'}
        self.assertEqual(required, {case['id'] for case in corpus['cases']})
        for case in corpus['cases']:
            self.assertTrue(case['expected'])
            self.assertTrue(case['invariants'])
        handoff = json.loads((HERE.parent / 'scripts/workflow-recovery-manifest.json').read_text())
        self.assertEqual(handoff['schema_version'], 2)
        self.assertEqual(set(handoff['state_groups']), set(GROUPS))


HID = 'h-' + '0123456789abcdef0123'


def handoff_id_cases(Case):
    class HandoffId(Case):
        """A measured handoff records the id handoff-envelope.py minted; a supervisor
        reads it from the snapshot, so a malformed one, or one on any other blocker, is
        refused, and a handoff without one stays valid."""

        def handoff(self, status='ok', **extra):
            return self.call('set-blocker', {'disposition': 'handoff', 'prevented_operation': 'next stage',
                'evidence': 'context-usage.py verdict', 'dependency': 'fresh session',
                'remaining_work': [], 'reason': 'rule context: 60% > 50%', **extra}, status=status)

        def test_handoff_state_carries_handoff_id(self):
            self.init(); self.gate(); self.handoff(handoff_id=HID)
            shown = self.state()
            self.assertEqual((shown['phase'], shown['blocker']['handoff_id']), ('handoff', HID))

        def test_handoff_id_is_refused_malformed_or_off_handoff(self):
            self.init(); self.gate()
            self.handoff(handoff_id='h-123', status='state_error')
            self.call('set-blocker', {'disposition': 'waiting_external', 'prevented_operation': 'live claim',
                'dependency': 'fixture service', 'evidence': 'original missing fixture',
                'remaining_work': [], 'handoff_id': HID}, status='state_error')

        def test_handoff_without_id_stays_valid(self):
            self.init(); self.gate(); self.handoff()
            self.assertNotIn('handoff_id', self.state()['blocker'])

        def test_contract_names_the_field(self):
            contract = (HERE.parent / 'references/execution-state-contract.md').read_text()
            self.assertIn('handoff_id', contract)
    return HandoffId


def suite(group):
    if group == 'contract':
        return unittest.defaultTestLoader.loadTestsFromTestCase(Contract)
    # A missing behavioral implementation is never a green empty selection.
    from workflow_state_cases import Case, Storage, Rounds, ProjectionReaders, Dispositions, Strategy
    if group == 'storage':
        return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c)
                                  for c in (Storage, ProjectionReaders))
    if group == 'dispositions':
        return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c)
                                  for c in (Dispositions, handoff_id_cases(Case)))
    return unittest.defaultTestLoader.loadTestsFromTestCase(
        {'storage': Storage, 'rounds': Rounds, 'strategy': Strategy}[group])


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--group', choices=GROUPS)
    p.add_argument('--manifest', type=Path)
    args = p.parse_args()
    if args.manifest:
        supplied = json.loads(args.manifest.read_text())
        if supplied.get('schema_version') != 2:
            p.error('unsupported manifest')
    tests = unittest.TestSuite(suite(g) for g in ([args.group] if args.group else GROUPS))
    if tests.countTestCases() == 0:
        p.error('empty group')
    sys.exit(not unittest.TextTestRunner(verbosity=2).run(tests).wasSuccessful())
