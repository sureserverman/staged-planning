#!/usr/bin/env python3
"""Protocol corpus and subprocess acceptance. Run bare for all implemented groups."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
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


NO_DOCUMENT = ('show',)
TAKES_DOCUMENT = ('init', 'transition', 'begin-round', 'record-verification', 'complete-round',
                  'authorize', 'set-blocker', 'strategy-review', 'migrate', 'finish', 'recover',
                  'resolve-recovery')


def stdin_cases(Case):
    class Stdin(Case):
        """Only an operation with a document waits on stdin: a caller whose stdin is an open
        socket must not hang `show`. Every other operation still reads what it is sent, so a
        missing document is refused by the same checks as an empty one."""

        def git(self, *args):
            # The fixture repo Case.setUp creates: no template, so no hooks of this machine's.
            return super().git(*(('init', '-q', '--template=') if args == ('init', '-q') else args))

        def command(self, operation):
            self.seq += 1
            return [sys.executable, str(SCRIPT), operation, '--repo', str(self.repo),
                    '--expected-revision', str(self.rev), '--operation-id', 'stdin-'+str(self.seq)]

        def open_silent(self, operation):
            """Start the operation on a pipe whose write end stays open and unwritten."""
            read_end, write_end = os.pipe()
            self.open_ends.add(write_end)
            p = subprocess.Popen(self.command(operation), stdin=read_end, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
            os.close(read_end)
            self.addCleanup(p.stdout.close)
            self.addCleanup(p.stderr.close)
            # Cleanups run last first: kill the child, then reap it.
            self.addCleanup(p.wait)
            self.addCleanup(p.kill)
            return p, write_end

        def setUp(self):
            super().setUp()
            self.open_ends = set()
            self.addCleanup(lambda: [os.close(end) for end in self.open_ends])

        def silent(self, operation):
            p, _ = self.open_silent(operation)
            try:
                out, _ = p.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                self.fail(operation+' did not return within 2 s with stdin an open silent pipe')
            return p.returncode, json.loads(out)

        def sent(self, operation, data):
            p = subprocess.run(self.command(operation), input=data, capture_output=True,
                               text=True, timeout=10)
            self.assertNotIn('Traceback', p.stderr)
            return p.returncode, json.loads(p.stdout)

        def snapshot(self):
            return (self.repo/'.claude/plan-progress.json').read_bytes()

        def test_the_two_lists_are_every_operation(self):
            usage = subprocess.run([sys.executable, str(SCRIPT), '--help'], capture_output=True,
                                   text=True, check=True).stdout
            self.assertEqual(set(re.search(r'{([^}]+)}', usage).group(1).split(',')),
                             set(NO_DOCUMENT) | set(TAKES_DOCUMENT))

        def test_no_document_operation_returns_on_a_silent_pipe(self):
            for operation in NO_DOCUMENT:
                with self.subTest(operation=operation):
                    self.assertEqual(self.silent(operation), (0, {'status': 'no_active_plan'}))
            self.init()
            for operation in NO_DOCUMENT:
                with self.subTest(operation=operation):
                    code, value = self.silent(operation)
                    self.assertEqual((code, value['status'], value['state']['revision']), (0, 'ok', 1))

        def test_document_operation_reads_what_it_is_sent(self):
            # Unparseable input is refused before any operation runs, so only a read reports it.
            self.init(); before = self.snapshot()
            for operation in TAKES_DOCUMENT:
                with self.subTest(operation=operation):
                    self.assertEqual(self.sent(operation, '{not json'),
                                     (3, {'status': 'state_error', 'message': 'invalid JSON payload'}))
            self.assertEqual(self.snapshot(), before)

        def test_document_operation_without_one_is_refused(self):
            self.init(); self.gate(); before = self.snapshot()
            for operation in TAKES_DOCUMENT:
                with self.subTest(operation=operation):
                    code, value = self.sent(operation, '')
                    self.assertIn(value['status'], ('state_error', 'conflict'), value)
                    self.assertIn(operation, value['message'], value)
                    self.assertNotEqual(code, 0)
            self.assertEqual(self.snapshot(), before)

        def test_closed_or_blank_stdin_is_refused_naming_the_operation(self):
            self.init(); self.gate(); before = self.snapshot()
            for operation in TAKES_DOCUMENT:
                with self.subTest(operation=operation):
                    p = subprocess.run(self.command(operation), stdin=None, capture_output=True, text=True,
                                       timeout=10, preexec_fn=lambda: os.close(0))
                    self.assertNotIn('Traceback', p.stderr)
                    value = json.loads(p.stdout)
                    self.assertIn(operation, value['message'], value)
                    self.assertNotEqual(p.returncode, 0)
                    code, value = self.sent(operation, ' \n')
                    self.assertIn(operation, value['message'], value)
                    self.assertNotEqual(code, 0)
            self.assertEqual(self.snapshot(), before)

        def test_a_call_refused_whatever_its_document_does_not_wait_for_one(self):
            self.init()
            read_end, write_end = os.pipe()
            self.open_ends.add(write_end)
            p = subprocess.Popen([sys.executable, str(SCRIPT), 'transition', '--repo', str(self.repo)],
                                 stdin=read_end, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            os.close(read_end)
            out, _ = p.communicate(timeout=5)
            self.assertEqual(json.loads(out)['status'], 'state_error')
            self.git('checkout', '-q', '--detach')
            code, value = self.silent('transition')
            self.assertEqual(value['status'], 'state_error', value)
            self.assertIn('detached', value['message'])

        def test_stdin_that_cannot_be_read_is_refused_naming_the_operation(self):
            self.init(); self.gate(); before = self.snapshot()
            read_end, write_end = os.pipe()
            os.set_blocking(read_end, False)
            self.open_ends.add(write_end)
            for name, stdin in (('write-only', subprocess.DEVNULL), ('non-blocking', read_end)):
                for operation in TAKES_DOCUMENT:
                    with self.subTest(shape=name, operation=operation):
                        if name == 'write-only':
                            write_only = os.open(os.devnull, os.O_WRONLY)
                            self.addCleanup(os.close, write_only)
                            stdin = write_only
                        p = subprocess.run(self.command(operation), stdin=stdin, capture_output=True,
                                           text=True, timeout=10)
                        self.assertNotIn('Traceback', p.stderr)
                        self.assertIn(operation, json.loads(p.stdout)['message'])
                        self.assertNotEqual(p.returncode, 0)
            os.close(read_end)
            self.assertEqual(self.snapshot(), before)

        def test_corrupt_state_is_refused_before_stdin_is_read(self):
            self.init()
            for damaged in ('{corrupt', '[]', '42', '"x"', '{}', '{"plan":"x"}'):
                with self.subTest(snapshot=damaged):
                    (self.repo/'.claude/plan-progress.json').write_text(damaged)
                    code, value = self.silent('transition')
                    self.assertEqual(value['status'], 'state_error', value)
                    self.assertNotEqual(code, 0)

        def test_strategy_review_waits_for_its_document(self):
            # An empty payload is its read-only re-entry, so it must wait to see the payload.
            self.init(); before = self.snapshot()
            p, write_end = self.open_silent('strategy-review')
            time.sleep(0.5)
            self.assertIsNone(p.poll(), 'strategy-review returned before its document arrived')
            os.write(write_end, b'{}')
            os.close(write_end); self.open_ends.discard(write_end)
            out, _ = p.communicate(timeout=10)
            self.assertEqual((p.returncode, json.loads(out)['status']), (4, 'conflict'))
            self.assertEqual(self.snapshot(), before)
    return Stdin


def suite(group):
    if group == 'contract':
        return unittest.defaultTestLoader.loadTestsFromTestCase(Contract)
    # A missing behavioral implementation is never a green empty selection.
    from workflow_state_cases import Case, Storage, Rounds, ProjectionReaders, Dispositions, Strategy
    if group == 'storage':
        return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c)
                                  for c in (Storage, ProjectionReaders, stdin_cases(Case)))
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
