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


PROGRESS = HERE.parent / 'scripts' / 'plan-progress.py'
STAGE_PLAN = ('# Plan: fixture\n\n## Stage 1: first\n\n'
              + ''.join(f'### Task 1.{n}: step {n}\n- **Status:** [x]\n\n' for n in range(1, 5))
              + '## Stage 2: second\n\n### Task 2.1: next step\n- **Status:** [ ]\n')


def stage_open_cases(Case):
    class StageOpen(Case):
        """A stage opens with a transition naming no task. The bar must then
        show the stage alone, not the last stage's task."""

        def test_stage_open_clears_previous_task(self):
            plan = self.repo/'fixture-plan.md'
            plan.write_text(STAGE_PLAN)
            self.call('init', {'plan': str(plan), 'scope': 'fixture',
                               'source': 'owner: execute the fixture plan'})
            self.call('transition', {'phase': 'task', 'stage': 1, 'task': '1.4',
                                     'task_desc': 'step 4'})
            self.call('transition', {'phase': 'task', 'stage': 2})
            shown = self.state()
            self.assertEqual((shown['task'], shown['task_desc']), ('', ''))
            self.call('transition', {'phase': 'task', 'stage': 2, 'task': '2.1',
                                     'task_desc': 'next step'})
            self.assertEqual(self.state()['task'], '2.1')
            self.call('transition', {'phase': 'task', 'stage': 2})
            env = {**os.environ, 'STAGED_PLANNING_CONFIG': str(self.repo/'no-config.yaml')}
            out = subprocess.run([sys.executable, str(PROGRESS)], cwd=self.repo, env=env,
                                 capture_output=True, text=True, timeout=20).stdout
            self.assertIn('S2/2', out)
            self.assertNotIn('T1.4', out)
            self.assertNotIn('T2.1', out)

        def test_gate_transition_keeps_the_task(self):
            # The status-lag marker reads the task at the gate, where unticked markers matter.
            self.init()
            self.call('transition', {'phase': 'task', 'stage': 1, 'task': '1.4',
                                     'task_desc': 'step 4'})
            self.call('transition', {'phase': 'gate', 'stage': 1})
            shown = self.state()
            self.assertEqual((shown['task'], shown['task_desc']), ('1.4', 'step 4'))
    return StageOpen


FINISHED_PLAN = ('# Project Plan: Fixture\n\n## Stage 1: Work\n\n'
                 '### Task 1.1: Repair\n- **Status:** [x]\n')


def finished_run_cases(Case):
    class FinishedRun(Case):
        """A finished run blocks nothing: `init` archives it and starts the next run, on
        its branch or another, and a reader on another branch sees no run. An unfinished
        run still refuses `init`, naming its plan and branch."""

        def finished(self):
            (self.repo/'fixture-plan.md').write_text(FINISHED_PLAN)
            self.init()
            old = self.state()['run_id']
            self.call('finish', {'evidence': 'fixture close-out complete'})
            return old

        def pointer(self):
            runs = list((self.repo/'.git/plan-state-runs').glob('*.json'))
            self.assertEqual(len(runs), 1)
            return json.loads(runs[0].read_text())

        def archived(self, run_id):
            path = self.repo/'.claude/plan-state-archive'/(run_id+'.json')
            self.assertTrue(path.is_file(), path)
            return json.loads(path.read_text())

        def readers(self):
            env = {**os.environ, 'STAGED_PLANNING_CONFIG': str(self.repo/'no-config.yaml')}
            out = []
            for args in (('--json',), ()):
                out.append(subprocess.run([sys.executable, str(PROGRESS), *args], cwd=self.repo,
                    env=env, input=json.dumps({'cwd': str(self.repo)}), capture_output=True,
                    text=True, timeout=20))
            classify = SCRIPT.parents[3]/'hooks'/'plan_continue_classify.py'
            out.append(subprocess.run([sys.executable, str(classify), '--inputs'], cwd=self.repo,
                input=json.dumps({'cwd': str(self.repo)}), capture_output=True, text=True,
                timeout=20))
            return out

        def test_init_after_finish_archives_on_the_same_branch(self):
            old = self.finished()
            self.rev = 0
            new = self.init()
            self.assertNotEqual(new['run_id'], old)
            self.assertEqual(self.archived(old)['disposition'], 'complete')
            shown = self.state()
            self.assertEqual((shown['run_id'], shown['revision'], shown['disposition']),
                             (new['run_id'], 1, 'working'))
            self.assertEqual(self.pointer()['run_id'], new['run_id'])

        def test_init_after_finish_archives_on_another_branch(self):
            old = self.finished()
            self.git('switch', '-qc', 'next-plan')
            self.call('show', status='no_active_plan')
            self.rev = 0
            new = self.init()
            self.assertNotEqual(self.archived(old)['owner']['branch'], 'next-plan')
            shown = self.state()
            self.assertEqual((shown['run_id'], shown['owner']['branch']), (new['run_id'], 'next-plan'))
            self.assertEqual(self.pointer()['owner']['branch'], 'next-plan')

        def test_init_retry_after_an_interrupted_archive(self):
            # Archived and the old pointer removed, but the new snapshot never written.
            old = self.finished()
            self.git('switch', '-qc', 'next-plan')
            for p in (self.repo/'.git/plan-state-runs').glob('*.json'):
                p.unlink()
            self.call('show', status='no_active_plan')
            self.rev = 0
            new = self.init()
            self.assertEqual(self.archived(old)['run_id'], old)
            self.assertEqual(self.pointer()['run_id'], new['run_id'])

        def test_init_over_an_unfinished_run_conflicts_naming_plan_and_branch(self):
            self.init()
            branch = self.git('symbolic-ref', '--short', 'HEAD')
            snapshot = (self.repo/'.claude/plan-progress.json').read_bytes()
            for expected in (0, self.rev):
                refused = self.call('init', {'plan': 'second-plan.md', 'scope': 'fixture',
                                    'source': 'owner'}, expected=expected, status='conflict')
                self.assertIn('fixture-plan.md', refused['message'])
                self.assertIn(branch, refused['message'])
            self.git('switch', '-qc', 'other')
            self.call('show', status='conflict')
            refused = self.call('init', {'plan': 'second-plan.md', 'scope': 'fixture',
                                'source': 'owner'}, expected=0, status='conflict')
            self.assertIn('fixture-plan.md', refused['message'])
            self.assertIn(branch, refused['message'])
            self.assertEqual((self.repo/'.claude/plan-progress.json').read_bytes(), snapshot)
            self.assertFalse((self.repo/'.claude/plan-state-archive').exists())

        def test_reader_on_another_branch_than_a_finished_run_shows_no_run(self):
            self.finished()
            self.git('switch', '-qc', 'next-plan')
            progress_json, progress_line, classify = self.readers()
            for result in (progress_json, progress_line, classify):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('state_error', result.stdout + result.stderr)
            self.assertNotIn('state_status', json.loads(progress_json.stdout))
            self.assertFalse(any(g.get('role') == 'pinned'
                                 for g in json.loads(progress_json.stdout)['groups']))
            # The hooks see it as the finished run it is, so they stand aside as they do
            # on its own branch; only the display shows no run.
            self.assertEqual(json.loads(classify.stdout)['state']['disposition'], 'complete')

        def test_hooks_stand_aside_for_a_finished_run_on_another_branch_or_detached(self):
            self.finished()
            subprocess.run([sys.executable, str(SCRIPT.parent/'proof-hooks-install.py'),
                '--install', '--repo', str(self.repo)], capture_output=True, text=True,
                check=True, timeout=20)
            for move in (('switch', '-qc', 'next-plan'), ('checkout', '-q', '--detach')):
                self.git(*move)
                self.call('show', status='no_active_plan')
                classify = self.readers()[2]
                self.assertEqual(json.loads(classify.stdout)['state']['disposition'], 'complete')
                (self.repo/'replay.txt').write_text(' '.join(move))
                self.git('add', 'replay.txt')
                result = subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=Fixture',
                    '-c', 'user.email=fixture@example.invalid', 'commit', '-qm',
                    'Stage 1 green'], capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, (move, result.stderr))

        def test_replayed_init_after_finish_returns_its_original_receipt(self):
            (self.repo/'fixture-plan.md').write_text(FINISHED_PLAN)
            data = {'plan': 'fixture-plan.md', 'scope': 'fixture', 'source': 'owner: execute'}
            first = self.call('init', data, op_id='first-init')
            self.call('finish', {'evidence': 'fixture close-out complete'})
            replay = self.call('init', data, expected=0, op_id='first-init')
            self.assertEqual(replay, first)
            self.assertEqual(self.state()['disposition'], 'complete')
            self.assertFalse((self.repo/'.claude/plan-state-archive').exists())
            self.call('init', {**data, 'plan': 'other'}, expected=0, op_id='first-init',
                      status='conflict')

        def test_contract_names_the_archive(self):
            contract = (HERE.parent/'references/execution-state-contract.md').read_text()
            self.assertIn('.claude/plan-state-archive/', contract)
    return FinishedRun


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
                                  for c in (Storage, ProjectionReaders, stdin_cases(Case),
                                            stage_open_cases(Case), finished_run_cases(Case)))
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
