#!/usr/bin/env python3
"""Which run plan-progress.py marks as current (the `pinned` row), and which it hides.

Every case builds its own repo, records home and records resolver, so it never reads
the machine's records home. The resolver answers the main checkout with the records
home and any other path with an empty home: the shape a linked worktree gets.
"""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
PROGRESS = HERE.parent / 'scripts' / 'plan-progress.py'
STATE = HERE.parent / 'scripts' / 'plan-state.py'
GIT_ID = ('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid')


def plan_text(statuses, completed=False):
    lines = ['# Plan: fixture', '', '## Stage 1: only', '']
    for n, mark in enumerate(statuses, 1):
        lines += [f'### Task 1.{n}: step {n}', f'- **Status:** [{mark}]', '']
    if completed:
        lines += ['**Completed:** 2026-11-12 — commits: fixture', '']
    return '\n'.join(lines)


class Pinning(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.repo = self.tmp / 'repo'
        self.repo.mkdir()
        self.git(self.repo, 'init', '-q', '--template=')
        (self.repo / '.gitignore').write_text('.claude/\n')
        self.git(self.repo, 'add', '.gitignore')
        self.git(self.repo, *GIT_ID, 'commit', '-qm', 'fixture')
        self.home = self.tmp / 'home'
        (self.home / 'plans').mkdir(parents=True)
        self.elsewhere = self.tmp / 'elsewhere'
        self.elsewhere.mkdir()
        resolver = self.tmp / 'resolver.sh'
        resolver.write_text('#!/bin/sh\n'
                            f'if [ "$2" = "{self.repo}" ]; then echo "{self.home}"; '
                            f'else echo "{self.elsewhere}"; fi\n')
        resolver.chmod(0o755)
        self.config = self.tmp / 'config.yaml'
        self.config.write_text(f'records_resolver: ["{resolver}"]\n')
        xdg = self.tmp / 'xdg'
        xdg.mkdir()
        self.env = {**os.environ, 'STAGED_PLANNING_CONFIG': str(self.config),
                    'XDG_CONFIG_HOME': str(xdg)}
        for k in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE'):
            self.env.pop(k, None)
        self.revs = {}

    def git(self, where, *args):
        return subprocess.run(['git', '-C', str(where), *args], capture_output=True,
                              text=True, check=True, env=getattr(self, 'env', None)).stdout

    def plan(self, name, statuses, completed=False):
        path = self.home / 'plans' / name
        path.write_text(plan_text(statuses, completed))
        return path

    def run_op(self, where, operation, payload):
        rev = self.revs.get(where, 0)
        p = subprocess.run([sys.executable, str(STATE), operation, '--repo', str(where),
                            '--expected-revision', str(rev), '--operation-id',
                            f'{operation}-{rev}'], input=json.dumps(payload),
                           capture_output=True, text=True, timeout=20, env=self.env)
        value = json.loads(p.stdout)
        self.assertEqual(value['status'], 'ok', (operation, value, p.stderr))
        self.revs[where] = value['revision']
        return value

    def owned_run(self, where, plan, phase='task', finish=False):
        self.run_op(where, 'init', {'plan': str(plan), 'scope': 'fixture',
                                    'source': 'owner: execute the fixture plan'})
        if phase == 'closeout':
            self.run_op(where, 'transition', {'phase': 'closeout'})
        else:
            self.run_op(where, 'transition', {'phase': 'task', 'stage': 1, 'task': '1.1',
                                              'task_desc': 'step 1'})
        if finish:
            self.run_op(where, 'finish', {'evidence': 'fixture close-out'})

    def legacy_state(self, where, plan, hours_ago=0, phase='task'):
        when = (datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(hours=hours_ago)).strftime('%Y-%m-%dT%H:%M:%SZ')
        (where / '.claude').mkdir(exist_ok=True)
        (where / '.claude' / 'plan-progress.json').write_text(json.dumps(
            {'plan': str(plan), 'phase': phase, 'stage': 1, 'task': '1.1',
             'task_desc': 'step 1', 'updated': when}))

    def worktree(self, name):
        path = self.tmp / name
        self.git(self.repo, 'worktree', 'add', '-q', '-b', name, str(path))
        return path

    def model(self, cwd=None):
        p = subprocess.run([sys.executable, str(PROGRESS), '--json'], cwd=cwd or self.repo,
                           capture_output=True, text=True, timeout=30, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def pinned(self, doc):
        return [g for g in doc['groups'] if g['role'] == 'pinned']

    # --- Task 1.2: a finished run stops pinning --------------------------------------

    def test_complete_run_with_completed_plan_draws_nothing(self):
        plan = self.plan('2026-11-01-done-plan.md', 'xx', completed=True)
        self.owned_run(self.repo, plan, phase='closeout', finish=True)
        self.assertEqual(self.model()['groups'], [])

    def test_legacy_state_naming_a_completed_plan_does_not_pin(self):
        plan = self.plan('2026-10-22-old-plan.md', 'xx', completed=True)
        self.legacy_state(self.repo, plan)
        doc = self.model()
        self.assertEqual(self.pinned(doc), [])
        self.assertEqual(doc['groups'], [])

    def test_closeout_phase_still_pins(self):
        plan = self.plan('2026-11-02-closing-plan.md', 'xx', completed=True)
        self.owned_run(self.repo, plan, phase='closeout')
        pinned = self.pinned(self.model())
        self.assertEqual(len(pinned), 1)
        self.assertIn('closing', pinned[0]['name'])

    def test_stale_closeout_leftover_over_a_completed_plan_does_not_pin(self):
        plan = self.plan('2026-10-22-left-plan.md', 'xx', completed=True)
        self.legacy_state(self.repo, plan, hours_ago=30, phase='closeout')
        self.assertEqual(self.model()['groups'], [])

    # --- Task 1.3: the run in another worktree is the current row ----------------------

    def test_own_finished_leftover_yields_to_the_live_run_elsewhere(self):
        old = self.plan('2026-10-22-old-plan.md', 'xx', completed=True)
        live = self.plan('2026-11-12-live-plan.md', 'x  ')
        self.legacy_state(self.repo, old)
        self.legacy_state(self.worktree('run'), live)
        doc = self.model()
        self.assertEqual([g['name'] for g in self.pinned(doc)], ['2026-11-12-live'])
        self.assertEqual(self.names(doc), ['2026-11-12-live'])

    def test_finished_run_elsewhere_does_not_compete(self):
        old = self.plan('2026-10-22-old-plan.md', 'xx', completed=True)
        live = self.plan('2026-11-12-live-plan.md', 'x  ')
        self.legacy_state(self.worktree('left'), old)
        self.legacy_state(self.worktree('run'), live)
        self.assertEqual([g['name'] for g in self.pinned(self.model())], ['2026-11-12-live'])

    def test_unreadable_state_elsewhere_does_not_compete(self):
        live = self.plan('2026-11-12-live-plan.md', 'x  ')
        bad = self.worktree('bad')
        (bad / '.claude').mkdir()
        (bad / '.claude' / 'plan-progress.json').write_text('{not json')
        self.legacy_state(self.worktree('run'), live)
        self.assertEqual([g['name'] for g in self.pinned(self.model())], ['2026-11-12-live'])

    def test_own_stale_run_yields_to_one_fresh_run_elsewhere(self):
        mine = self.plan('2026-11-10-mine-plan.md', 'x  ')
        theirs = self.plan('2026-11-11-theirs-plan.md', 'x  ')
        self.legacy_state(self.repo, mine, hours_ago=14)
        self.legacy_state(self.worktree('other'), theirs)
        doc = self.model()
        self.assertEqual([g['name'] for g in self.pinned(doc)], ['2026-11-11-theirs'])
        self.assertEqual(self.pinned(doc)[0]['stale_hours'], None)

    def test_own_stale_run_and_two_fresh_elsewhere_pin_none(self):
        mine = self.plan('2026-11-10-mine-plan.md', 'x  ')
        self.legacy_state(self.repo, mine, hours_ago=14)
        for n in ('a', 'b'):
            self.legacy_state(self.worktree(n), self.plan(f'2026-11-11-{n}-plan.md', 'x  '))
        doc = self.model()
        self.assertEqual(self.pinned(doc), [])
        self.assertIn('2026-11-10-mine', self.names(doc))

    def names(self, doc):
        return sorted(g['name'] for g in doc['groups'])

    def test_fresh_run_in_linked_worktree_is_pinned_from_main(self):
        plan = self.plan('2026-11-12-live-plan.md', 'x  ')
        wt = self.worktree('run')
        self.owned_run(wt, plan)
        pinned = self.pinned(self.model())
        self.assertEqual(len(pinned), 1)
        self.assertEqual(pinned[0]['name'], '2026-11-12-live')
        self.assertEqual((pinned[0]['phase'], pinned[0]['task']), ('task', '1.1'))

    def test_own_fresh_run_outranks_another_worktree(self):
        mine = self.plan('2026-11-10-mine-plan.md', 'x  ')
        theirs = self.plan('2026-11-11-theirs-plan.md', 'x  ')
        self.legacy_state(self.repo, mine)
        self.legacy_state(self.worktree('other'), theirs)
        doc = self.model()
        self.assertEqual([g['name'] for g in self.pinned(doc)], ['2026-11-10-mine'])
        self.assertIn('2026-11-11-theirs', self.names(doc))

    def test_two_fresh_runs_elsewhere_pin_none(self):
        a = self.plan('2026-11-10-a-plan.md', 'x  ')
        b = self.plan('2026-11-11-b-plan.md', 'x  ')
        self.legacy_state(self.worktree('wa'), a)
        self.legacy_state(self.worktree('wb'), b)
        doc = self.model()
        self.assertEqual(self.pinned(doc), [])
        self.assertEqual(self.names(doc), ['2026-11-10-a', '2026-11-11-b'])

    def test_stale_run_elsewhere_does_not_compete(self):
        theirs = self.plan('2026-11-11-theirs-plan.md', 'x  ')
        self.legacy_state(self.worktree('other'), theirs, hours_ago=13)
        self.assertEqual(self.pinned(self.model()), [])
        mine = self.plan('2026-11-10-mine-plan.md', 'x  ')
        self.legacy_state(self.repo, mine, hours_ago=14)
        pinned = self.pinned(self.model())
        self.assertEqual([g['name'] for g in pinned], ['2026-11-10-mine'])
        self.assertEqual(pinned[0]['stale_hours'], 14)

    def test_removed_worktree_holds_nothing(self):
        gone = self.plan('2026-11-10-gone-plan.md', 'x  ')
        live = self.plan('2026-11-11-live-plan.md', 'x  ')
        wt_gone = self.worktree('gone')
        self.legacy_state(wt_gone, gone)
        self.legacy_state(self.worktree('live'), live)
        subprocess.run(['rm', '-rf', str(wt_gone)], check=True)
        p = subprocess.run([sys.executable, str(PROGRESS)], cwd=self.repo, env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0)
        self.assertNotIn(str(wt_gone), p.stdout)
        doc = self.model()
        self.assertEqual([g['name'] for g in self.pinned(doc)], ['2026-11-11-live'])

    def test_unreadable_own_state_yields_to_the_run_elsewhere(self):
        live = self.plan('2026-11-11-live-plan.md', 'x  ')
        (self.repo / '.claude').mkdir()
        (self.repo / '.claude' / 'plan-progress.json').write_text('{"schema_version": 2}')
        self.legacy_state(self.worktree('live'), live)
        self.assertEqual([g['name'] for g in self.pinned(self.model())], ['2026-11-11-live'])

    # --- Task 1.4: a plan with every task done and no close-out says so ---------------

    def test_all_tasks_done_without_closeout_is_marked(self):
        self.plan('2026-11-08-finished-plan.md', 'xxx')
        self.plan('2026-11-09-half-plan.md', 'xx ')
        doc = self.model()
        tails = {g['name']: g['tail'] for g in doc['groups']}
        self.assertIn('◌ close-out pending', tails['2026-11-08-finished'])
        self.assertNotIn('close-out pending', tails['2026-11-09-half'])
        spans = [s for g in doc['groups'] if g['name'] == '2026-11-08-finished'
                 for s in g['tail_spans'] if 'close-out pending' in s['text']]
        self.assertTrue(spans and spans[0]['dim'], spans)
        text = subprocess.run([sys.executable, str(PROGRESS)], cwd=self.repo, env=self.env,
                              capture_output=True, text=True, timeout=30).stdout
        line = [l for l in text.splitlines() if '2026-11-08-finished' in l]
        self.assertTrue(line and '◌ close-out pending' in line[0], text)
        pinned_plan = self.plan('2026-11-10-pinned-plan.md', 'xxx')
        self.legacy_state(self.repo, pinned_plan)
        pinned = self.pinned(self.model())
        self.assertEqual([g['name'] for g in pinned], ['2026-11-10-pinned'])
        self.assertNotIn('close-out pending', pinned[0]['tail'])

    def test_git_that_cannot_list_worktrees_leaves_the_own_state_deciding(self):
        mine = self.plan('2026-11-10-mine-plan.md', 'x  ')
        theirs = self.plan('2026-11-11-theirs-plan.md', 'x  ')
        self.legacy_state(self.worktree('other'), theirs)
        self.legacy_state(self.repo, mine, hours_ago=15)
        fake = self.tmp / 'bin'
        fake.mkdir()
        (fake / 'git').write_text('#!/bin/sh\nexit 1\n')
        (fake / 'git').chmod(0o755)
        self.env['PATH'] = f"{fake}{os.pathsep}{self.env.get('PATH', '')}"
        pinned = self.pinned(self.model())
        self.assertEqual([g['name'] for g in pinned], ['2026-11-10-mine'])
        self.assertEqual(pinned[0]['stale_hours'], 15)

    def test_records_home_past_the_deadline_draws_no_bars(self):
        plan = self.plan('2026-11-12-live-plan.md', 'x  ')
        self.legacy_state(self.worktree('run'), plan)
        p = subprocess.run([sys.executable, str(PROGRESS)], cwd=self.repo, timeout=30,
                           env={**self.env, 'PLAN_PROGRESS_TEST_STALL_S': '10'},
                           capture_output=True, text=True)
        self.assertEqual((p.returncode, p.stdout), (0, ''))

    def test_in_tree_records_in_a_linked_worktree_stay_its_own(self):
        # No resolver: records are each checkout's own docs/, so a linked worktree's
        # plans come from its own tree, and its run's plan draws once.
        del self.env['STAGED_PLANNING_CONFIG']
        plans = self.repo / 'docs' / 'plans'
        plans.mkdir(parents=True)
        (plans / '2026-11-12-x-plan.md').write_text(plan_text('x  '))
        self.git(self.repo, 'add', 'docs')
        self.git(self.repo, *GIT_ID, 'commit', '-qm', 'plan')
        wt = self.worktree('run')
        (wt / 'docs' / 'plans' / '2026-11-12-x-plan.md').write_text(plan_text('xx '))
        self.legacy_state(wt, 'docs/plans/2026-11-12-x-plan.md')
        doc = self.model(cwd=wt)
        rows = [(g['role'], g['name'], g['done']) for g in doc['groups']]
        self.assertEqual(rows, [('pinned', '2026-11-12-x', 2)])

    def test_in_tree_run_elsewhere_draws_once_from_another_checkout(self):
        # No resolver: main's docs/plans holds its own copy of the plan the run in W
        # executes. That copy is the same plan, so it draws no second row.
        del self.env['STAGED_PLANNING_CONFIG']
        plans = self.repo / 'docs' / 'plans'
        plans.mkdir(parents=True)
        (plans / '2026-11-12-x-plan.md').write_text(plan_text('x  '))
        (plans / '2026-11-10-other-plan.md').write_text(plan_text('x  '))
        self.git(self.repo, 'add', 'docs')
        self.git(self.repo, *GIT_ID, 'commit', '-qm', 'plans')
        wt = self.worktree('run')
        (wt / 'docs' / 'plans' / '2026-11-12-x-plan.md').write_text(plan_text('xx '))
        self.legacy_state(wt, 'docs/plans/2026-11-12-x-plan.md')
        rows = [(g['role'], g['name'], g['done']) for g in self.model()['groups']]
        self.assertEqual(sorted(rows), [('other', '2026-11-10-other', 1),
                                        ('pinned', '2026-11-12-x', 2)])

    def test_a_resolver_that_times_out_is_asked_once_and_the_run_still_draws(self):
        # As in 2.0.0: a records home that does not answer costs the other rows, not the
        # run's own bar. Two calls of a timing-out resolver would pass the child's deadline.
        plan = self.plan('2026-11-12-live-plan.md', 'x  ')
        wt = self.worktree('run')
        self.legacy_state(wt, plan)
        calls = self.tmp / 'calls.log'
        slow = self.tmp / 'slow.sh'
        slow.write_text(f'#!/bin/sh\necho "$@" >> {calls}\nsleep 8\necho {self.home}\n')
        slow.chmod(0o755)
        self.config.write_text(f'records_resolver: ["{slow}"]\n')
        p = subprocess.run([sys.executable, str(PROGRESS)], cwd=wt, env=self.env, timeout=30,
                           input=json.dumps({'cwd': str(wt)}), capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertIn('2026-11-12-live', p.stdout)
        self.assertEqual(len(calls.read_text().splitlines()), 1)

    def test_linked_worktree_lists_the_main_worktree_plans(self):
        self.plan('2026-11-09-inflight-plan.md', 'x  ')
        wt = self.worktree('side')
        self.assertEqual(self.names(self.model(cwd=wt)), ['2026-11-09-inflight'])


if __name__ == '__main__':
    sys.exit(not unittest.main(verbosity=2, exit=False).result.wasSuccessful())
