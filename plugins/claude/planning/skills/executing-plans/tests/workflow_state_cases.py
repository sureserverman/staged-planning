"""Real CLI scenarios. Temporary git repositories isolate state and pointer writes."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent.parent/'scripts/plan-state.py'


class Case(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)/'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        (self.repo/'.gitignore').write_text('# ===== AI Tools =====\n.claude/\n# ===== AI / Design Plans =====\n')
        self.git('add', '.gitignore')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 'commit', '--allow-empty', '-qm', 'fixture')
        self.rev = 0
        self.seq = 0

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], capture_output=True,
                              text=True, check=True).stdout.strip()

    def call(self, operation, payload=None, expected=None, op_id=None, repo=None, status='ok'):
        self.seq += 1
        cmd = [sys.executable, str(SCRIPT), operation, '--repo', str(repo or self.repo)]
        if operation != 'show':
            cmd += ['--expected-revision', str(self.rev if expected is None else expected),
                    '--operation-id', op_id or 'op-'+str(self.seq)]
        p = subprocess.run(cmd, input=json.dumps(payload or {}), capture_output=True,
                           text=True, timeout=10)
        self.assertNotIn('Traceback', p.stderr)
        value = json.loads(p.stdout)
        self.assertEqual(value['status'], status, (p.returncode, value, p.stderr))
        self.assertEqual(p.returncode, {'ok':0, 'no_active_plan':0, 'state_error':3,
                                      'conflict':4, 'budget_exhausted':2,
                                      'strategy_review_due':5}[status])
        if status == 'ok' and operation != 'show':
            self.rev = value['revision']
        return value

    def init(self, **extra):
        return self.call('init', {'plan':'fixture-plan.md', 'scope':'fixture',
                                  'source':'owner: execute the fixture plan', **extra})

    def state(self):
        return self.call('show')['state']

    def gate(self, repair='sha-1'):
        return self.call('transition', {'phase':'gate', 'gate':{'id':'stage-1',
                         'repair_revision':repair, 'checks':['task-test','review']}})


class Storage(Case):
    def test_missing_idle_differs_from_missing_owned_snapshot(self):
        self.call('show', status='no_active_plan')
        self.init()
        (self.repo/'.claude/plan-progress.json').unlink()
        self.call('show', status='state_error')

    def test_fresh_process_and_exact_idempotent_receipt(self):
        data={'plan':'fixture-plan.md','scope':'fixture','source':'owner: execute'}
        first=self.call('init',data,op_id='retry-me')
        retry=self.call('init',data,expected=0,op_id='retry-me')
        self.assertEqual(first,retry)
        self.call('init',{**data,'plan':'other'},expected=0,op_id='retry-me',status='conflict')
        self.assertEqual(self.state()['revision'],1)

    def test_stale_revision_conflicts_without_writing(self):
        self.init()
        before=(self.repo/'.claude/plan-progress.json').read_bytes()
        self.call('transition',{'phase':'task'},expected=0,status='conflict')
        self.assertEqual(before,(self.repo/'.claude/plan-progress.json').read_bytes())

    def test_corrupt_snapshot_is_preserved(self):
        self.init()
        path=self.repo/'.claude/plan-progress.json';path.write_text('{partial')
        self.call('transition',{'phase':'task'},status='state_error')
        self.assertEqual(path.read_text(),'{partial')

    def test_manual_edit_and_unknown_schema_are_errors(self):
        self.init();path=self.repo/'.claude/plan-progress.json'
        state=json.loads(path.read_text());state['revision']=100;path.write_text(json.dumps(state))
        self.call('show',status='state_error')
        state['schema_version']=99;path.write_text(json.dumps(state))
        self.call('show',status='state_error')

    def test_symlink_directory_and_hardlink_snapshot_refused(self):
        target=Path(self.temp.name)/'outside';target.mkdir()
        (self.repo/'.claude').symlink_to(target, target_is_directory=True)
        self.call('init',{'plan':'x','scope':'fixture','source':'owner'},status='state_error')
        self.assertEqual(list(target.iterdir()),[])
        (self.repo/'.claude').unlink();self.init()
        os.link(self.repo/'.claude/plan-progress.json',target/'copy')
        self.call('transition',{'phase':'task'},status='state_error')

    def test_private_permissions_and_partial_temp_do_not_replace_snapshot(self):
        self.init();path=self.repo/'.claude/plan-progress.json'
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        (path.parent/'.plan-state-leftover').write_text('{partial')
        self.assertEqual(self.state()['revision'],1)

    def test_process_death_before_replace_preserves_old_snapshot_and_retry(self):
        self.init();path=self.repo/'.claude/plan-progress.json';before=path.read_bytes()
        wrapper=Path(self.temp.name)/'interrupted.py'
        wrapper.write_text('import os, runpy, sys\n'
            'sys.path.insert(0, '+repr(str(SCRIPT.parent))+')\n'
            'os.replace = lambda *a, **k: os._exit(9)\n'
            'runpy.run_path('+repr(str(SCRIPT))+', run_name="__main__")\n')
        p=subprocess.run([sys.executable,str(wrapper),'transition','--repo',str(self.repo),
            '--operation-id','interrupted','--expected-revision','1'],
            input='{"phase":"task"}',text=True,capture_output=True,timeout=10)
        self.assertEqual(p.returncode,9)
        self.assertEqual(before,path.read_bytes())
        self.call('transition',{'phase':'task'},op_id='interrupted')
        self.assertEqual(self.state()['revision'],2)

    def test_worktrees_are_independent_and_branch_change_conflicts(self):
        self.init();linked=Path(self.temp.name)/'linked'
        self.git('worktree','add','-qb','linked',str(linked))
        self.call('show',repo=linked,status='no_active_plan')
        other=self.call('init',{'plan':'linked','scope':'fixture','source':'owner'},
                        repo=linked,expected=0)
        original=self.call('show')['state']
        self.assertNotEqual(other['run_id'],original['run_id'])
        self.git('switch','-qc','different')
        self.call('transition',{'phase':'task'},expected=original['revision'],status='conflict')

    def test_unregistered_git_pointer_cannot_write_outside_its_repo(self):
        fake=Path(self.temp.name)/'fake';fake.mkdir()
        (fake/'.git').write_text('gitdir: '+str(self.repo/'.git')+'\n')
        self.call('init',{'plan':'fake','scope':'fixture','source':'owner'},repo=fake,
                  status='state_error')
        self.assertFalse((self.repo/'.git/plan-state-runs').exists())
        (fake/'.git').unlink();(fake/'.git').symlink_to(self.repo/'.git',target_is_directory=True)
        self.call('init',{'plan':'fake','scope':'fixture','source':'owner'},repo=fake,
                  status='state_error')

    def test_existing_public_lock_is_refused(self):
        self.init();lock=self.repo/'.claude/plan-state.lock';lock.chmod(0o666)
        self.call('transition',{'phase':'task'},status='state_error')

    def test_concurrent_compare_and_swap_allows_only_one_writer(self):
        self.init()
        # The overlap is forced, not hoped for: each writer sleeps after it has read the
        # snapshot and before it replaces it. Without the lock both read revision 1
        # inside that window and both commit; with it the second reads revision 2.
        wrapper=Path(self.temp.name)/'slow-writer.py'
        wrapper.write_text('import runpy, sys, time\n'
            'sys.path.insert(0, '+repr(str(SCRIPT.parent))+')\n'
            'import plan_state\n'
            'original = plan_state.replace_json\n'
            'def slow(*a, **k):\n'
            '    time.sleep(1.5)\n'
            '    return original(*a, **k)\n'
            'plan_state.replace_json = slow\n'
            'runpy.run_path('+repr(str(SCRIPT))+', run_name="__main__")\n')
        processes=[subprocess.Popen([sys.executable,str(wrapper),'transition','--repo',str(self.repo),
                    '--expected-revision','1','--operation-id',str(i)],stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for i in range(2)]
        for p in processes:
            p.stdin.write('{"phase":"task"}');p.stdin.close();p.stdin=None
        statuses=[json.loads(p.communicate(timeout=20)[0])['status'] for p in processes]
        self.assertEqual(sorted(statuses),['conflict','ok'])
        self.assertEqual(self.state()['revision'],2)

    def test_deep_nesting_is_a_state_error_not_a_traceback(self):
        deep='['*200000
        p=subprocess.run([sys.executable,str(SCRIPT),'init','--repo',str(self.repo),
            '--expected-revision','0','--operation-id','deep'],input=deep,
            capture_output=True,text=True,timeout=20)
        self.assertNotIn('Traceback',p.stderr)
        self.assertEqual((p.returncode,json.loads(p.stdout)['status']),(3,'state_error'))
        self.init()
        path=self.repo/'.claude/plan-progress.json';path.write_text(deep)
        self.call('show',status='state_error')
        self.call('transition',{'phase':'task'},status='state_error')
        self.assertEqual(path.read_text(),deep)

    def test_process_death_between_snapshot_and_pointer_recovers_on_retry(self):
        wrapper=Path(self.temp.name)/'interrupted-init.py'
        # Dies on the SECOND replace: init has written one of its two files.
        wrapper.write_text('import os, runpy, sys\n'
            'sys.path.insert(0, '+repr(str(SCRIPT.parent))+')\n'
            'real = os.replace\n'
            'calls = []\n'
            'def replace(*a, **k):\n'
            '    calls.append(a)\n'
            '    if len(calls) == 2:\n'
            '        os._exit(9)\n'
            '    return real(*a, **k)\n'
            'os.replace = replace\n'
            'runpy.run_path('+repr(str(SCRIPT))+', run_name="__main__")\n')
        data={'plan':'fixture-plan.md','scope':'fixture','source':'owner: execute'}
        p=subprocess.run([sys.executable,str(wrapper),'init','--repo',str(self.repo),
            '--operation-id','interrupted-init','--expected-revision','0'],
            input=json.dumps(data),text=True,capture_output=True,timeout=10)
        self.assertEqual(p.returncode,9,p.stderr)
        retry=self.call('init',data,expected=0,op_id='interrupted-init')
        self.assertEqual(retry['revision'],1)
        self.assertEqual(self.state()['run_id'],retry['run_id'])
        self.call('transition',{'phase':'task'})
        self.assertEqual(self.state()['revision'],2)

    def test_legacy_positive_counter_requires_evidenced_migration(self):
        directory=self.repo/'.claude';directory.mkdir()
        path=directory/'plan-progress.json'
        path.write_text(json.dumps({'plan':'x','phase':'task','remediation_round':2,
                                    'remediation_budget':2}))
        self.call('migrate',{'source':'owner','scope':'fixture'},status='state_error')
        self.call('migrate',{'source':'owner','scope':'fixture','legacy_evidence':{
                  'source':'original stage gate receipt','disposition':'active',
                  'gate':{'id':'stage-1','repair_revision':'sha-1','checks':['check']}}})
        self.assertEqual(self.state()['rounds']['completed'],1)
        self.assertIsNotNone(self.state()['rounds']['active'])

    def test_caller_cannot_set_counters_or_ownership(self):
        self.init()
        for field in ('revision','rounds','authorization','owner','receipts'):
            self.call('transition',{'phase':'task',field:{}},status='state_error')

    def test_missing_legacy_counter_cannot_fabricate_zero_work(self):
        (self.repo/'.claude').mkdir()
        path=self.repo/'.claude/plan-progress.json'
        path.write_text('{"plan":"x","phase":"gate"}')
        self.call('migrate',{'source':'owner','scope':'fixture'},status='state_error')
        self.call('migrate',{'source':'owner','scope':'fixture','legacy_evidence':{
            'source':'first gate receipt; no repair attempted','completed':0,
            'disposition':'completed'}},status='ok')
        self.assertEqual(self.state()['rounds']['completed'],0)

    def test_completed_migration_requires_original_exact_verification(self):
        (self.repo/'.claude').mkdir()
        path=self.repo/'.claude/plan-progress.json'
        path.write_text('{"plan":"x","phase":"gate","remediation_round":2}')
        evidence={'source':'gate receipt','disposition':'completed','gate':{
            'id':'stage-1','repair_revision':'sha-1','checks':['test']},'verification':{}}
        self.call('migrate',{'source':'owner','scope':'fixture','legacy_evidence':evidence},status='state_error')
        evidence['verification']={'gate_id':'stage-1','repair_revision':'sha-1',
                                 'evidence':'original test receipt','checks':{'test':'passed'}}
        self.call('migrate',{'source':'owner','scope':'fixture','legacy_evidence':evidence})
        self.assertEqual(self.state()['rounds']['completed'],2)

    def test_legacy_wait_or_handoff_cannot_migrate_into_working(self):
        directory=self.repo/'.claude';directory.mkdir()
        path=directory/'plan-progress.json'
        for phase in ('blocked','handoff'):
            value={'plan':'fixture-plan.md','phase':phase,'remediation_round':0}
            path.write_text(json.dumps(value));before=path.read_bytes()
            self.call('migrate',{'source':'owner fixture','scope':'fixture'},status='state_error')
            self.assertEqual(path.read_bytes(),before)
        blocker={'disposition':'handoff','prevented_operation':'next task',
            'evidence':'original handoff measurement','dependency':'fresh session',
            'remaining_work':['next task'],'reason':'original measured context boundary'}
        self.call('migrate',{'source':'owner fixture','scope':'fixture','legacy_blocker':blocker})
        self.assertEqual(self.state()['disposition'],'handoff')
        self.call('transition',{'phase':'task'},status='conflict')

    def test_structured_blocker_shape_is_validated_even_with_recomputed_integrity(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('state_contract_module',SCRIPT.parent/'plan_state.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.init();path=self.repo/'.claude/plan-progress.json'
        state=json.loads(path.read_text());state.update(disposition='waiting_external',phase='blocked',blocker=None)
        state['integrity']=module.digest({k:v for k,v in state.items() if k!='integrity'})
        path.write_text(json.dumps(state));before=path.read_bytes()
        self.call('show',status='state_error')
        self.call('transition',{'phase':'task'},status='state_error')
        self.assertEqual(path.read_bytes(),before)

    def test_finish_requires_no_active_work_and_preserves_receipts(self):
        self.init();self.call('finish',{'evidence':'gate and close-out complete'})
        state=self.state()
        self.assertEqual(state['disposition'],'complete')
        self.assertEqual(len(state['receipts']),2)
        self.call('transition',{'phase':'task'},status='conflict')


class Rounds(Case):
    def begin(self):
        self.call('begin-round',{'gate_id':'stage-1'})

    def verify(self, verdict='passed', **extra):
        self.call('record-verification',{'gate_id':'stage-1','repair_revision':'sha-1',
            'evidence':'test and review original receipts','checks':{'task-test':verdict,'review':verdict},**extra})

    def test_active_second_round_finishes_third_refused(self):
        self.init();self.gate()
        for n in (1,2):
            self.begin();self.verify()
            self.call('complete-round',{'gate_id':'stage-1'})
            self.assertEqual(self.state()['rounds']['completed'],n)
        self.call('begin-round',{'gate_id':'stage-1'},status='budget_exhausted')
        self.call('transition',{'phase':'task','task':'1.2'})
        self.assertEqual(self.state()['task'],'1.2')

    def test_missing_and_wrong_gate_verification_cannot_complete(self):
        self.init();self.gate();self.begin()
        self.call('complete-round',{'gate_id':'stage-1'},status='conflict')
        self.call('record-verification',{'gate_id':'other','repair_revision':'sha-1',
            'evidence':'receipt','checks':{'task-test':'passed','review':'passed'}},status='conflict')
        self.call('record-verification',{'gate_id':'stage-1','repair_revision':'sha-1',
            'evidence':'receipt','checks':{'task-test':'passed'}},status='state_error')

    def test_repair_revision_and_real_code_changes_invalidate_verification(self):
        self.init();self.gate();self.begin();self.verify()
        (self.repo/'code.py').write_text('print("changed")\n')
        self.call('complete-round',{'gate_id':'stage-1'},status='conflict')
        self.verify();self.gate('sha-2')
        self.call('complete-round',{'gate_id':'stage-1'},status='conflict')

    def test_untracked_file_hash_boundaries_cannot_alias_changed_code(self):
        self.init();self.gate();self.begin()
        a=self.repo/'a';a.write_text('b420c');a.chmod(0o644)
        self.verify()
        a.write_text('');b=self.repo/'b';b.write_text('c');b.chmod(0o644)
        self.call('complete-round',{'gate_id':'stage-1'},status='conflict')

    def test_tracked_clean_filter_cannot_hide_changed_repair_bytes(self):
        (self.repo/'.gitattributes').write_text('code.py filter=erase\n')
        self.git('config','filter.erase.clean','cat /dev/null')
        (self.repo/'code.py').write_text('print(1)\n')
        self.git('add','.gitattributes','code.py')
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                 'commit','-qm','filtered code')
        self.init();self.gate();self.begin();self.verify()
        (self.repo/'code.py').write_text('print(2)\n')
        self.assertEqual(self.git('diff','HEAD','--','code.py'),'')
        sentinel=self.repo/'.claude/filter-ran'
        self.git('config','filter.erase.clean','touch '+str(sentinel)+'; cat /dev/null')
        self.verify()
        self.assertFalse(sentinel.exists(),'verification must not execute clean filters')
        (self.repo/'code.py').write_text('print(3)\n')
        self.call('complete-round',{'gate_id':'stage-1'},status='conflict')
        self.assertFalse(sentinel.exists(),'completion must not execute clean filters')

    def test_dirty_submodule_bytes_invalidate_verification(self):
        source=Path(self.temp.name)/'library-source';source.mkdir()
        subprocess.run(['git','-C',str(source),'init','-q'],check=True)
        (source/'.gitignore').write_text('# ===== AI Tools =====\n.claude/\n# ===== AI / Design Plans =====\n')
        (source/'code.py').write_text('x=1\n')
        subprocess.run(['git','-C',str(source),'add','.'],check=True)
        subprocess.run(['git','-C',str(source),'-c','user.name=Fixture',
                        '-c','user.email=fixture@example.invalid','commit','-qm','library'],check=True)
        self.git('-c','protocol.file.allow=always','submodule','add','-q',str(source),'library')
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                 'commit','-qm','submodule')
        code=self.repo/'library/code.py';code.write_text('x=2\n')
        self.init();self.gate();self.begin();self.verify()
        before=self.git('diff','HEAD','--','library');code.write_text('x=3\n')
        self.assertEqual(before,self.git('diff','HEAD','--','library'))
        self.call('complete-round',{'gate_id':'stage-1'},status='conflict')
        shutil.rmtree(self.repo/'library')
        self.call('record-verification',{'gate_id':'stage-1','repair_revision':'sha-1',
            'evidence':'uninitialized checkout','checks':{'task-test':'passed','review':'passed'}},
            status='state_error')
        (self.repo/'library').mkdir()
        self.call('record-verification',{'gate_id':'stage-1','repair_revision':'sha-1',
            'evidence':'empty checkout','checks':{'task-test':'passed','review':'passed'}},
            status='state_error')

    def test_tracked_mode_deletion_and_symlink_targets_are_bound(self):
        path=self.repo/'code.py';path.write_text('code\n');path.chmod(0o644)
        self.git('add','code.py')
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                 'commit','-qm','tracked code')
        self.init();self.gate();self.begin();self.verify()
        path.chmod(0o755)
        self.call('complete-round',{'gate_id':'stage-1'},status='conflict')
        self.verify();path.unlink()
        self.call('complete-round',{'gate_id':'stage-1'},status='conflict')
        path.symlink_to('one');self.verify();path.unlink();path.symlink_to('two')
        self.call('complete-round',{'gate_id':'stage-1'},status='conflict')

    def test_failed_assessment_consumes_round_without_claiming_green(self):
        self.init();self.gate();self.begin();self.verify('failed')
        receipt=self.call('complete-round',{'gate_id':'stage-1'})
        self.assertEqual(receipt['verification_verdict'],'failed')
        self.assertEqual(self.state()['qualification'],'pending')

    def test_idempotent_completion_charges_once_and_new_completion_conflicts(self):
        self.init();self.gate();self.begin();self.verify()
        before=self.rev;first=self.call('complete-round',{'gate_id':'stage-1'},op_id='done')
        retry=self.call('complete-round',{'gate_id':'stage-1'},op_id='done',expected=before)
        self.assertEqual(first,retry)
        self.call('complete-round',{'gate_id':'stage-1'},status='conflict')
        self.assertEqual(self.state()['rounds']['completed'],1)

    def test_changed_gate_check_set_invalidates_old_verification(self):
        self.init();self.gate();self.begin();self.verify()
        self.call('transition',{'phase':'gate','gate':{'id':'stage-1',
                  'repair_revision':'sha-1','checks':['task-test','review','new-check']}})
        self.call('complete-round',{'gate_id':'stage-1'},status='conflict')

    def test_concurrent_begin_reserves_only_one_round(self):
        self.init();self.gate()
        cmd=[sys.executable,str(SCRIPT),'begin-round','--repo',str(self.repo),
             '--expected-revision',str(self.rev)]
        ps=[subprocess.Popen(cmd+['--operation-id','begin-'+str(i)],stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for i in (1,2)]
        for p in ps:
            p.stdin.write('{"gate_id":"stage-1"}');p.stdin.close();p.stdin=None
        values=[json.loads(p.communicate(timeout=10)[0]) for p in ps]
        self.assertEqual(sorted(v['status'] for v in values),['conflict','ok'])
        self.assertEqual(self.state()['rounds']['active']['number'],1)

    def test_switching_gates_preserves_each_account(self):
        self.init();self.gate();self.begin();self.verify()
        self.call('complete-round',{'gate_id':'stage-1'})
        self.call('transition',{'phase':'gate','gate':{'id':'stage-2','repair_revision':'sha-2','checks':['test']}})
        self.assertEqual(self.state()['rounds']['completed'],0)
        self.gate();self.assertEqual(self.state()['rounds']['completed'],1)

    def test_budget_wrapper_allows_finishing_active_round_and_reports_corruption(self):
        self.init();self.gate()
        for n in (1,2):
            self.begin()
            p=subprocess.run([sys.executable,str(SCRIPT.parent/'plan-progress.py'),'--budget-check'],
                cwd=self.repo,capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stderr)
            self.verify();self.call('complete-round',{'gate_id':'stage-1'})
        p=subprocess.run([sys.executable,str(SCRIPT.parent/'plan-progress.py'),'--budget-check'],
            cwd=self.repo,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,2,p.stderr)
        path=self.repo/'.claude/plan-progress.json'
        original=path.read_text();downgraded=json.loads(original)
        del downgraded['schema_version'];del downgraded['remediation_round']
        path.write_text(json.dumps(downgraded))
        p=subprocess.run([sys.executable,str(SCRIPT.parent/'plan-progress.py'),'--budget-check'],
            cwd=self.repo,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,3,p.stderr)
        self.assertIn('state_error',p.stderr)
        path.write_text(original)
        (self.repo/'.claude/plan-progress.json').write_text('{corrupt')
        p=subprocess.run([sys.executable,str(SCRIPT.parent/'plan-progress.py'),'--budget-check'],
            cwd=self.repo,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,3,p.stderr)

    def test_no_go_is_independent_of_active_repair(self):
        self.init();self.gate();self.begin()
        self.call('transition',{'phase':'task','qualification':'no_go'})
        self.verify();self.call('complete-round',{'gate_id':'stage-1'})
        self.assertEqual(self.state()['qualification'],'no_go')

    def test_receipt_soft_limit_cannot_strand_authorized_active_round(self):
        self.init();self.gate()
        for n in range(252):
            self.call('transition',{'phase':'task','task':str(n)})
        self.begin();self.verify()
        (self.repo/'code.py').write_text('changed after verification\n')
        self.verify()
        self.call('complete-round',{'gate_id':'stage-1'})
        self.call('begin-round',{'gate_id':'stage-1'},status='conflict')
        self.call('set-blocker',{'disposition':'awaiting_owner_decision',
            'prevented_operation':'new work','evidence':'owner cancellation at capacity',
            'dependency':'owner instruction','remaining_work':[],
            'cancelled':True,'owner_source':'owner: cancel fixture'})
        self.call('finish',{'evidence':'receipt capacity reached; bounded fixture closed'})


class ProjectionReaders(Case):
    def reader(self, name, *args, stdin=None):
        path=(SCRIPT.parent/name if name=='plan-progress.py' else
              SCRIPT.parents[3]/'hooks'/name)
        return subprocess.run([sys.executable,str(path),*args],cwd=self.repo,
            input=json.dumps(stdin or {}),capture_output=True,text=True,timeout=10)

    def test_a_detached_head_owns_no_run(self):
        # A checkout with no branch (a tag build, a rebase, a bisect) is idle when no run
        # exists here, never a state error; it cannot start one; and a run started on a
        # branch is a conflict from the detached checkout, not invisible.
        self.git('checkout','-q','--detach')
        self.call('show',status='no_active_plan')
        result=self.reader('plan-progress.py',stdin={'cwd':str(self.repo)})
        self.assertEqual((result.returncode,result.stderr),(0,''))
        refused=self.call('init',{'plan':'fixture-plan.md','scope':'fixture',
                                  'source':'owner: execute the fixture plan'},status='state_error')
        self.assertIn('detached HEAD',refused['message'])
        self.git('checkout','-q','-')
        self.init()
        self.git('checkout','-q','--detach')
        self.call('show',status='conflict')

    def test_structured_wait_handoff_and_qualification_are_visible(self):
        (self.repo/'fixture-plan.md').write_text('# Project Plan: Fixture\n## Stage 1: Work\n### Task 1.1: Repair\n- **Status:** [ ]\n')
        self.init();self.call('transition',{'phase':'task','qualification':'no_go'})
        self.call('set-blocker',{'disposition':'waiting_external','prevented_operation':'live claim',
            'evidence':'original unavailable endpoint','dependency':'fixture endpoint','remaining_work':[]})
        report=json.loads(self.reader('plan-progress.py','--json',stdin={'cwd':str(self.repo)}).stdout)
        group=report['groups'][0]
        self.assertIn('fixture endpoint',group['blocked_note'])
        self.assertIn('qualification no_go',group['tail'])
        self.call('set-blocker',{'disposition':'handoff','prevented_operation':'next task',
            'evidence':'original context receipt','dependency':'fresh session','remaining_work':['next task'],
            'reason':'measured context boundary'})
        report=json.loads(self.reader('plan-progress.py','--json',stdin={'cwd':str(self.repo)}).stdout)
        self.assertIn('measured context boundary',report['groups'][0]['tail'])

    def test_versioned_projection_and_unknown_schema_diagnostics(self):
        (self.repo/'fixture-plan.md').write_text('# Project Plan: Fixture\n## Stage 1: Work\n### Task 1.1: Repair\n- **Status:** [ ]\n')
        self.init();self.gate()
        result=self.reader('plan-progress.py','--json',stdin={'cwd':str(self.repo)})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['groups'][0]['phase'],'gate')
        path=self.repo/'.claude/plan-progress.json';state=json.loads(path.read_text())
        state['schema_version']=99;path.write_text(json.dumps(state));before=path.read_bytes()
        for args in (('--json',),(),('--stage-order-check',)):
            result=self.reader('plan-progress.py',*args,stdin={'cwd':str(self.repo)})
            self.assertIn('state_error',result.stderr,(args,result.stdout,result.stderr))
            if args==('--json',):
                output=json.loads(result.stdout)
                self.assertEqual(output['state_status'],'state_error')
                self.assertFalse(any(g['role']=='pinned' for g in output['groups']))
            if args==('--stage-order-check',):
                self.assertEqual(result.returncode,3)
        result=self.reader('plan_continue_classify.py','--inputs',stdin={'cwd':str(self.repo)})
        marker=json.loads(result.stdout)['state']
        self.assertEqual(marker['state_status'],'state_error')
        result=self.reader('plan_continue_classify.py',stdin={'state':marker,
                          'last_text':'Next is task 2.1.'})
        self.assertIn('state_error',result.stdout)
        self.assertNotEqual(json.loads(result.stdout).get('decision'),'block')
        self.assertEqual(before,path.read_bytes())

    def test_terminal_owned_state_releases_opted_in_proof_guard(self):
        self.init()
        self.call('finish', {'evidence':'fixture close-out complete'})
        snapshot=(self.repo/'.claude/plan-progress.json').read_bytes()
        hooks=SCRIPT.parents[3]/'hooks'
        (self.repo/'.git/hooks/reference-transaction').write_text(
            '#!/bin/sh\n# planning commit gate — installed by fixture\n')
        result=subprocess.run(['bash',str(hooks/'proof-guard.sh')],cwd=self.repo,
            input=json.dumps({'cwd':str(self.repo),'tool_input':{'command':'git config core.hooksPath fixture'}}),
            text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0)
        self.assertEqual(result.stdout,'',result.stdout)
        self.assertEqual((self.repo/'.claude/plan-progress.json').read_bytes(),snapshot)

    def test_terminal_owned_state_releases_ref_gate_and_dispatch_observer(self):
        plan=self.repo/'fixture-plan.md'
        plan.write_text('# Fixture plan\n### Task 1.1: Old task\n- **Status:** [x]\n- **Test:** `python3 test.py` — old claim (red if previous break)\n')
        self.init()
        hooks=SCRIPT.parents[3]/'hooks'
        observer=['bash',str(hooks/'dispatch-log.sh')]
        event=json.dumps({'hook_event_name':'PreToolUse','tool_name':'Agent',
            'tool_input':{'description':'fixture dispatch','subagent_type':'general-purpose'}})
        env={**os.environ,'CLAUDE_PROJECT_DIR':str(self.repo)}
        subprocess.run(observer,input=event,text=True,env=env,check=True,timeout=10)
        log=self.repo/'.claude/dispatch-log.jsonl';self.assertTrue(log.exists())
        before=log.read_bytes()
        self.call('finish',{'evidence':'fixture old plan complete'})
        subprocess.run(observer,input=event,text=True,env=env,check=True,timeout=10)
        self.assertEqual(log.read_bytes(),before)
        log.unlink()
        subprocess.run(observer,input=event,text=True,env=env,check=True,timeout=10)
        self.assertFalse(log.exists())
        subprocess.run([sys.executable,str(SCRIPT.parent/'proof-hooks-install.py'),
            '--install','--repo',str(self.repo)],capture_output=True,text=True,check=True,timeout=10)
        (self.repo/'next.txt').write_text('unrelated next plan work')
        self.git('add','next.txt')
        result=subprocess.run(['git','-C',str(self.repo),'-c','user.name=Fixture',
            '-c','user.email=fixture@example.invalid','commit','-qm','Task 1.1: next plan task'],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_owned_reader_uses_protocol_bound_above_legacy_read_limit(self):
        self.init(task_desc='fixture description '+('x'*300000))
        result=self.reader('plan_continue_classify.py','--inputs',stdin={'cwd':str(self.repo)})
        state=json.loads(result.stdout)['state']
        self.assertEqual(state['schema_version'],2)
        self.assertNotIn('state_status',state)

    def test_corrupt_and_missing_owned_projection_differ_from_idle(self):
        idle=self.reader('plan-progress.py','--json',stdin={'cwd':str(self.repo)})
        self.assertNotIn('state_error',idle.stderr)
        self.assertNotIn('state_status',json.loads(idle.stdout))
        self.init();path=self.repo/'.claude/plan-progress.json'
        downgraded=json.loads(path.read_text());del downgraded['schema_version']
        for broken in ('{partial','[]',json.dumps(downgraded),None):
            if broken is None:
                path.unlink()
            else:
                path.write_text(broken)
            result=self.reader('plan-progress.py','--json',stdin={'cwd':str(self.repo)})
            self.assertIn('state_error',result.stderr)
            self.assertEqual(json.loads(result.stdout)['state_status'],'state_error')
            result=self.reader('plan-progress.py','--stage-order-check')
            self.assertEqual(result.returncode,3)
            self.assertIn('state_error',result.stderr)
            marker=json.loads(self.reader('plan_continue_classify.py','--inputs',
                stdin={'cwd':str(self.repo)}).stdout)['state']
            self.assertEqual(marker['state_status'],'state_error')
            hook=SCRIPT.parents[3]/'hooks/plan-continue.sh'
            result=subprocess.run(['bash',str(hook)],cwd=self.repo,
                input=json.dumps({'cwd':str(self.repo)}),text=True,capture_output=True,timeout=10,
                env={**os.environ,'PLAN_CONTINUE':'1'})
            self.assertEqual(result.returncode,0)
            self.assertIn('state_error',result.stdout+result.stderr)
            hooks=SCRIPT.parents[3]/'hooks'
            # Exercise the actual opt-in proof adapters, with fixture metadata
            # only; no Git update or hook-removal command is executed.
            (self.repo/'.git/hooks/reference-transaction').write_text(
                '#!/bin/sh\n# planning commit gate — installed by fixture\n')
            result=subprocess.run(['bash',str(hooks/'proof-guard.sh')],cwd=self.repo,
                input=json.dumps({'cwd':str(self.repo),'tool_input':{
                    'command':'git config core.hooksPath fixture'}}),
                text=True,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0)
            self.assertIn('state_error',result.stderr)
            if broken is None:
                self.assertFalse(path.exists())
            else:
                self.assertEqual(path.read_text(),broken)
            self.assertNotIn('deny',result.stdout)
            result=subprocess.run(['bash',str(hooks/'git-ref-gate.sh'),'prepared'],
                cwd=self.repo,input='',text=True,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0)
            self.assertIn('state_error',result.stderr)


class Dispositions(Case):
    begin=Rounds.begin
    verify=Rounds.verify

    def block(self,disposition='waiting_external',status='ok',**extra):
        return self.call('set-blocker',{'disposition':disposition,
            'prevented_operation':'gate verification','evidence':'fixture service unavailable',
            'dependency':'fixture service','remaining_work':['inspect local fixture'],**extra},status=status)

    def test_owner_extension_survives_restart_and_cannot_reset_spent_work(self):
        self.init();self.gate()
        for _ in (1,2):
            self.begin();self.verify();self.call('complete-round',{'gate_id':'stage-1'})
        self.call('authorize',{'source':'owner message: extend fixture to 3',
                 'scope':'fixture','budget':3},op_id='owner-extension')
        self.assertEqual(self.state()['rounds']['completed'],2)
        self.assertEqual(self.state()['authorization']['source'],'owner message: extend fixture to 3')
        self.begin();self.verify();self.call('complete-round',{'gate_id':'stage-1'})
        self.call('begin-round',{'gate_id':'stage-1'},status='budget_exhausted')
        self.assertIn('authorization',self.state()['receipts']['owner-extension']['receipt'])

    def test_extension_requires_matching_scope_source_and_explicit_ceiling(self):
        self.init();self.gate();self.begin()
        self.call('authorize',{'source':'owner message','scope':'other','budget':3},status='conflict')
        self.call('authorize',{'source':'','scope':'fixture','budget':3},status='state_error')
        self.call('authorize',{'source':'owner message','scope':'fixture','budget':0},status='state_error')
        self.call('authorize',{'source':'owner message','scope':'fixture'})
        self.assertEqual(self.state()['rounds']['budget'],2)
        self.assertEqual(self.state()['rounds']['active']['number'],1)

    def test_no_go_continues_repair_and_prose_cannot_stop_structured_work(self):
        self.init();self.gate();self.begin()
        self.call('transition',{'phase':'task','qualification':'no_go'})
        p=subprocess.run([sys.executable,str(SCRIPT.parents[3]/'hooks/plan_continue_classify.py')],
            input=json.dumps({'state':self.state(),'last_text':'ACTION NEEDED: stop repair.'}),
            capture_output=True,text=True,timeout=10)
        self.assertEqual(json.loads(p.stdout)['decision'],'block')
        self.verify();self.call('complete-round',{'gate_id':'stage-1'})
        self.assertEqual(self.state()['qualification'],'no_go')

    def test_wait_blocks_new_work_but_permits_active_assessment_and_explicit_resume(self):
        self.init();self.gate();self.begin();self.block()
        self.assertEqual(self.state()['phase'],'blocked')
        self.call('transition',{'phase':'task'},status='conflict')
        self.verify();self.call('complete-round',{'gate_id':'stage-1'})
        self.assertEqual(self.state()['disposition'],'waiting_external')
        self.call('begin-round',{'gate_id':'stage-1'},status='conflict')
        self.block('working',evidence='dependency is now available')
        self.assertEqual(self.state()['phase'],'task');self.begin()

    def test_blocker_cancellation_and_measured_handoff_are_structured(self):
        self.init();self.gate()
        self.call('set-blocker',{'disposition':'waiting_external'},status='state_error')
        self.block('awaiting_owner_decision',owner_source='owner message: cancel fixture',
                   cancelled=True)
        self.assertTrue(self.state()['blocker']['cancelled'])
        self.call('begin-round',{'gate_id':'stage-1'},status='conflict')
        self.block('waiting_external',status='conflict')
        self.block('working',status='conflict')
        self.call('authorize',{'source':'owner message: resume fixture','scope':'fixture'})
        self.block('working')
        self.call('set-blocker',{'disposition':'handoff','prevented_operation':'next stage',
            'evidence':'context measurement','dependency':'fresh session','remaining_work':[],
            'reason':'context 60% > 50%'})
        self.assertEqual(self.state()['phase'],'handoff')
        self.call('begin-round',{'gate_id':'stage-1'},status='conflict')

    def test_scoped_ceiling_covers_saved_gate_accounts(self):
        self.init(budget=3);self.gate()
        for _ in range(2):
            self.call('begin-round',{'gate_id':'stage-1'})
            self.call('record-verification',{'gate_id':'stage-1','repair_revision':'sha-1',
                'evidence':'original verification','checks':{'task-test':'passed','review':'passed'}})
            self.call('complete-round',{'gate_id':'stage-1'})
        self.call('transition',{'phase':'gate','gate':{'id':'stage-2',
            'repair_revision':'sha-2','checks':['test']}})
        self.call('authorize',{'source':'owner: lower same scope','scope':'fixture','budget':1},
                  status='conflict')
        self.call('authorize',{'source':'owner: keep completed scope','scope':'fixture','budget':2})
        self.call('transition',{'phase':'gate','gate':{'id':'stage-1',
            'repair_revision':'sha-1','checks':['task-test','review']}})
        self.assertEqual(self.state()['rounds']['completed'],2)
        self.assertEqual(self.state()['rounds']['budget'],2)
        self.call('begin-round',{'gate_id':'stage-1'},status='budget_exhausted')

    def test_noop_metadata_writes_cannot_reset_stop_escape(self):
        self.init();self.call('transition',{'phase':'task'})
        transcript=self.repo/'transcript.jsonl'
        transcript.write_text(json.dumps({'type':'assistant','message':{'content':'Repair summary.'}})+'\n')
        session='noop-'+self.repo.parent.name
        sid=hashlib.sha1((session+'|'+str(self.repo)).encode()).hexdigest()[:16]
        counter=Path(tempfile.gettempdir())/('claude-plan-continue-'+sid+'.json')
        self.addCleanup(lambda:counter.unlink(missing_ok=True))
        for n in range(4):
            if n==1: self.call('transition',{'phase':'task'})
            if n==2: self.call('authorize',{'source':'owner: execute the fixture plan','scope':'fixture'})
            if n==3: self.block('working')
            result=subprocess.run(['bash',str(SCRIPT.parents[3]/'hooks/plan-continue.sh')],
                input=json.dumps({'cwd':str(self.repo),'session_id':session,'transcript_path':str(transcript)}),
                env={**os.environ,'PLAN_CONTINUE':'1'},cwd=self.repo,
                capture_output=True,text=True,timeout=10)
            data=json.loads(result.stdout)
            if n<3: self.assertEqual(data['decision'],'block')
            else: self.assertIn('systemMessage',data)

    def test_counter_key_tracks_checks_and_bytes_without_prose_or_revision_churn(self):
        import copy, importlib.util
        path=SCRIPT.parents[3]/'hooks/plan_continue_classify.py'
        spec=importlib.util.spec_from_file_location('counter_classifier',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.init();self.gate();self.call('begin-round',{'gate_id':'stage-1'})
        self.call('record-verification',{'gate_id':'stage-1','repair_revision':'sha-1',
            'evidence':'original','checks':{'task-test':'passed','review':'passed'}})
        state=self.state();key=module.counter_key(state);changed=copy.deepcopy(state)
        changed['revision']+=1;changed['gate']['repair_revision']='label-only'
        changed['rounds']['budget']+=1
        changed['rounds']['active']['verification']['evidence']='different receipt reference'
        self.assertEqual(module.counter_key(changed),key)
        for field in ('checks','worktree_digest'):
            changed=copy.deepcopy(state)
            changed['rounds']['active']['verification'][field]= {'task-test':'failed','review':'passed'} if field=='checks' else '0'*64
            self.assertNotEqual(module.counter_key(changed),key)

    def test_structured_wait_and_handoff_allow_stop_with_no_prose_inference(self):
        self.init();self.gate()
        self.block()
        p=subprocess.run([sys.executable,str(SCRIPT.parents[3]/'hooks/plan_continue_classify.py')],
            input=json.dumps({'state':self.state(),'last_text':'Next is task 2.2.'}),
            capture_output=True,text=True,timeout=10)
        self.assertEqual(json.loads(p.stdout)['decision'],'allow')

    def test_actual_stop_hook_uses_disposition_and_retains_escape_guard(self):
        self.init();self.gate()
        self.call('transition',{'phase':'closeout'})
        p=subprocess.run([sys.executable,str(SCRIPT.parents[3]/'hooks/plan_continue_classify.py')],
            input=json.dumps({'state':self.state(),'last_text':'Repair summary.'}),
            capture_output=True,text=True,timeout=10)
        self.assertEqual(json.loads(p.stdout)['decision'],'block')
        transcript=self.repo/'transcript.jsonl'
        transcript.write_text(json.dumps({'type':'assistant','message':{'content':'Repair summary.'}})+'\n')
        session='fixture-'+self.repo.parent.name
        sid=hashlib.sha1((session+'|'+str(self.repo)).encode()).hexdigest()[:16]
        counter=Path(tempfile.gettempdir())/('claude-plan-continue-'+sid+'.json')
        self.addCleanup(lambda:counter.unlink(missing_ok=True))
        for n in range(4):
            result=subprocess.run(['bash',str(SCRIPT.parents[3]/'hooks/plan-continue.sh')],
                input=json.dumps({'cwd':str(self.repo),'session_id':session,
                                  'transcript_path':str(transcript)}),
                env={**os.environ,'PLAN_CONTINUE':'1'},cwd=self.repo,
                capture_output=True,text=True,timeout=10)
            data=json.loads(result.stdout)
            self.assertEqual(result.returncode,0)
            if n<3:
                self.assertEqual(data['decision'],'block')
            else:
                self.assertIn('systemMessage',data)
        self.call('transition',{'phase':'task','task':'2.1'})
        result=subprocess.run(['bash',str(SCRIPT.parents[3]/'hooks/plan-continue.sh')],
            input=json.dumps({'cwd':str(self.repo),'session_id':session,
                              'transcript_path':str(transcript)}),
            env={**os.environ,'PLAN_CONTINUE':'1'},cwd=self.repo,
            capture_output=True,text=True,timeout=10)
        self.assertEqual(json.loads(result.stdout)['decision'],'block')
        self.block('awaiting_owner_decision',cancelled=True,owner_source='owner: cancel fixture')
        result=subprocess.run(['bash',str(SCRIPT.parents[3]/'hooks/plan-continue.sh')],
            input=json.dumps({'cwd':str(self.repo),'session_id':session,
                              'transcript_path':str(transcript)}),
            env={**os.environ,'PLAN_CONTINUE':'1'},cwd=self.repo,
            capture_output=True,text=True,timeout=10)
        self.assertEqual(result.stdout,'')


class Strategy(Case):
    begin=Rounds.begin
    verify=Rounds.verify
    def completed(self):
        self.init();self.gate()
        for _ in range(2):
            self.begin();self.verify('failed')
            self.call('complete-round',{'gate_id':'stage-1'})

    def review(self, **extra):
        observations=[{'round':n,'defect_families':['parser-exception'],
            'verified_gain':0,'false_rejections':None,'cost_ms':n*100,
            'evidence':'original fixture run '+str(n)} for n in (1,2)]
        return {'gate_id':'stage-1','checkpoint':{'after_completed':2,
            'source':'authored default two-round checkpoint'},'observations':observations,
            'assessment':'consider_redesign','alternatives':[
                {'kind':'repair','scope':'existing','evidence':'current implementation'},
                {'kind':'redesign','scope':'new','evidence':'architecture hypothesis'}],**extra}

    def test_checkpoint_never_grants_work_or_resets_account(self):
        self.completed();before=self.state()['rounds']
        receipt=self.call('strategy-review',self.review())
        self.assertTrue(receipt['strategy_assessment']['owner_decision_required'])
        self.assertEqual(self.state()['rounds'],before)
        self.call('begin-round',{'gate_id':'stage-1'},status='budget_exhausted')
        self.call('transition',{'phase':'task','task':'diagnosis'})
        self.assertEqual(self.state()['task'],'diagnosis')
        self.call('authorize',{'scope':'fixture','source':'owner: third round','budget':3})
        self.begin();self.verify();self.call('complete-round',{'gate_id':'stage-1'})
        self.assertEqual(self.state()['rounds']['completed'],3)

    def test_recorded_checkpoint_is_not_reported_due_again(self):
        self.completed();self.call('strategy-review',self.review())
        path=self.repo/'.claude/plan-progress.json';before=path.read_bytes()
        result=self.call('strategy-review',{})
        self.assertEqual(result['strategy_assessment']['severity'],'advisory')
        self.assertEqual(path.read_bytes(),before)

    def test_large_numeric_observations_report_state_error_without_traceback(self):
        self.completed()
        for field in ('cost_ms','verified_gain'):
            data=self.review();data['observations'][0][field]=10**400
            self.call('strategy-review',data,status='state_error')

    def test_boundary_reports_due_and_preserves_snapshot_until_recorded(self):
        self.completed();path=self.repo/'.claude/plan-progress.json';before=path.read_bytes()
        self.call('strategy-review',{},status='strategy_review_due')
        self.assertEqual(path.read_bytes(),before)
        self.call('strategy-review',self.review())
        self.assertEqual(self.state()['strategy']['assessment'],'consider_redesign')

    def test_missing_observations_are_advisory_unknown(self):
        self.completed();receipt=self.call('strategy-review',self.review(
            observations=[],assessment='unknown'))
        assessment=receipt['strategy_assessment']
        self.assertEqual(assessment['signal'],'unknown')
        self.assertEqual(assessment['severity'],'advisory')
        self.assertEqual(assessment['available_cost_ms'],[])

    def test_known_audit_and_benign_sequences_do_not_force_failure(self):
        self.completed();observations=self.review()['observations']
        receipt=self.call('strategy-review',self.review())
        self.assertEqual(receipt['strategy_assessment']['signal'],'review_suggested')
        observations[1].update(defect_families=['different-family'],verified_gain=2,cost_ms=50)
        receipt=self.call('strategy-review',self.review(observations=observations,
            assessment='continue_repair',alternatives=[{'kind':'diagnosis','scope':'existing',
                'evidence':'benign positive sequence'}]))
        self.assertEqual(receipt['strategy_assessment']['signal'],'no_advisory_trigger')
        self.assertFalse(receipt['strategy_assessment']['owner_decision_required'])

    def test_invalid_observations_and_unreached_checkpoint_are_refused(self):
        self.init();self.gate()
        self.call('strategy-review',self.review(),status='conflict')
        self.begin();self.verify();self.call('complete-round',{'gate_id':'stage-1'})
        self.begin();self.verify();self.call('complete-round',{'gate_id':'stage-1'})
        for observations in ([{'round':3}], [self.review()['observations'][0]]*2,
                [{**self.review()['observations'][0],'cost_ms':-1}],
                [{**self.review()['observations'][0],'verified_gain':True}]):
            self.call('strategy-review',self.review(observations=observations),status='state_error')
        self.call('strategy-review',{**self.review(),'reset_budget':True},status='state_error')
