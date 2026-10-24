"""Integrated protocol traces. Tests use actual CLIs in disposable repositories."""
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import os
import tempfile
import time
from pathlib import Path
import unittest

from workflow_state_cases import Strategy, Rounds, Storage, Case, SCRIPT

HERE=Path(__file__).resolve().parent
SCENARIOS={
    'active-two':'test_failure_interruption_recovery_and_next_green_task',
    'completed-two':'test_failure_interruption_recovery_and_next_green_task',
    'missing':'test_missing_idle_differs_from_missing_owned_snapshot',
    'corrupt':'test_corruption_scope_counter_reset_and_unresolved_wait_controls',
    'partial-write':'test_private_permissions_and_partial_temp_do_not_replace_snapshot',
    'interruption':'test_failure_interruption_recovery_and_next_green_task',
    'concurrent':'test_concurrent_compare_and_swap_allows_only_one_writer',
    'worktree':'test_worktrees_are_independent_and_branch_change_conflicts',
    'retry':'test_fresh_process_and_exact_idempotent_receipt',
    'extension':'test_actual_authorized_experiment_and_checkpoint',
    'no-go-repair':'test_actual_authorized_experiment_and_checkpoint',
    'premises':'test_early_disposable_artifact_and_missing_live_claim',
    'baseline':'test_actual_authorized_experiment_and_checkpoint',
    'environment':'test_actual_authorized_experiment_and_checkpoint',
    'strategy':'test_actual_authorized_experiment_and_checkpoint',
}
spec=importlib.util.spec_from_file_location('evaluation_cases',HERE/'test-evaluation-ledger.py')
evaluation=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluation)


class AuthorizedExperiment(evaluation.Ledger):
    begin=Rounds.begin
    verify=Rounds.verify
    review=Strategy.review

    def test_actual_authorized_experiment_and_checkpoint(self):
        self.init();self.gate()
        self.call('transition',{'phase':'gate','qualification':'no_go'})
        # Actual fixture input bytes, with explicitly synthetic quality claims.
        self.identity['candidate']['sha256']=hashlib.sha256(b'candidate-v1').hexdigest()
        self.identity['baseline']['sha256']=hashlib.sha256(b'baseline-v1').hexdigest()
        self.identity['dependencies']['config']=hashlib.sha256(b'fixture-config').hexdigest()
        self.run_cli('record',self.original(comparison='baseline_win'))
        unavailable={'availability':'unavailable','schema':'unknown','support':'unknown',
                     'useful':'unknown','environment':'failure'}
        baseline={'availability':'available','schema':'pass','support':'pass',
                  'useful':'unknown','environment':'normal'}
        self.run_cli('record',self.original('outage',comparison='unknown',outcomes={
            'candidate':unavailable,'baseline':baseline}))
        for _ in range(2):
            self.begin();self.verify('failed')
            self.call('complete-round',{'gate_id':'stage-1'})
        self.call('begin-round',{'gate_id':'stage-1'},status='budget_exhausted')
        self.call('strategy-review',{},status='strategy_review_due')
        assessment=self.call('strategy-review',self.review())['strategy_assessment']
        self.assertEqual(assessment['severity'],'advisory')
        self.assertEqual(self.state()['rounds']['completed'],2)
        self.call('transition',{'phase':'task','task':'authorized-diagnosis'})
        self.call('authorize',{'source':'fixture owner input: extend existing scope to three',
            'scope':'fixture','budget':3})
        self.begin();self.verify();self.call('complete-round',{'gate_id':'stage-1'})
        self.call('transition',{'phase':'task','task':'next-green-task'})
        state=self.state()
        self.assertEqual(state['task'],'next-green-task')
        self.assertEqual(state['qualification'],'no_go')
        self.assertEqual(state['rounds']['completed'],3)
        self.assertEqual(state['disposition'],'working')
        report=self.run_cli('summarize')
        self.assertEqual(report['original_results'],2)
        self.assertEqual(report['comparisons']['baseline_win'],1)
        self.assertEqual(report['metrics']['candidate']['availability']['eligible'],2)
        self.assertEqual(report['metrics']['candidate']['support']['failed'],0)
        payload={'from_experiment':'exp-a','original_receipt_id':'result-1','identity':self.identity}
        reuse=self.run_cli('check-reuse',payload,experiment='exp-b',status='reused')
        self.assertEqual(reuse['original_experiment'],'exp-a')
        for key in ('baseline','dependencies'):
            changed=copy.deepcopy(payload)
            if key=='baseline': changed['identity'][key]['sha256']='0'*64
            else: changed['identity'][key]['config']='0'*64
            self.run_cli('check-reuse',changed,experiment='exp-b',status='conflict')
        self.assertEqual(self.run_cli('summarize')['original_results'],2)


class Premises(evaluation.Ledger):
    def test_early_disposable_artifact_and_missing_live_claim(self):
        self.init()
        application=self.repo/'application.py'
        application.write_text('import json\nfrom pathlib import Path\n'
            'config=json.loads(Path("config.json").read_text())\n'
            'print(json.dumps({"adoption":config["adoption"],"diagnosis":"available"}))\n')
        (self.repo/'config.json').write_text('{"adoption":"off"}')
        result=subprocess.run([sys.executable,str(application)],cwd=self.repo,
            capture_output=True,text=True,timeout=10,check=True)
        self.assertEqual(json.loads(result.stdout),{'adoption':'off','diagnosis':'available'})
        self.identity['candidate']['sha256']=hashlib.sha256(application.read_bytes()).hexdigest()
        self.identity['baseline']['sha256']=hashlib.sha256((self.repo/'config.json').read_bytes()).hexdigest()
        self.identity['evidence_hash']=hashlib.sha256(result.stdout.encode()).hexdigest()
        observation={'availability':'available','schema':'pass','support':'unknown',
                     'useful':'unknown','environment':'normal'}
        absent_observation={'availability':'unknown','schema':'unknown','support':'unknown',
                            'useful':'unknown','environment':'unknown'}
        data=self.original(evidence_class='live_local_protocol',identity=self.identity,
            outcomes={'candidate':observation,'baseline':absent_observation},comparison='unknown')
        self.run_cli('record',data)
        self.assertEqual(self.run_cli('summarize')['evidence_class'],'live_local_protocol')
        self.run_cli('record',self.original('false-live',evidence_class='live_ai_quality'),status='state_error')
        # Real missing artifact: the claim is blocked; runnable authorized work stays visible.
        absent=subprocess.run([sys.executable,str(self.repo/'requested-service.py')],
            capture_output=True,text=True,timeout=10)
        self.assertNotEqual(absent.returncode,0)
        self.call('transition',{'phase':'task','qualification':'blocked','task':'remaining-diagnosis'})
        self.assertEqual(self.state()['disposition'],'working')
        self.call('set-blocker',{'disposition':'waiting_external',
            'prevented_operation':'requested live claim','dependency':'requested service',
            'evidence':'original missing artifact process exit '+str(absent.returncode),'remaining_work':[]})
        self.call('transition',{'phase':'task'},status='conflict')

    def test_authored_premise_fields_and_source_goal_mechanism(self):
        root=HERE.parents[3]
        template=(root/'core/skills/planning-projects/references/plan-document-template.md').read_text()
        for field in ('Requirement origin','Early premise','Evidence claim','Remaining authorized work'):
            self.assertIn(field,template)
        self.assertIn('**(goal)**',template)
        text=(root/'core/skills/executing-plans/references/stage-gate.md').read_text()
        self.assertIn('whole artifact',text)
        self.assertIn('Step 3.0',text)
        self.assertIn('Commentary',text)


class Complete(evaluation.Ledger):
    def call(self,*args,**kwargs):
        self.invocations=getattr(self,'invocations',0)+1
        return super().call(*args,**kwargs)

    def test_failure_interruption_recovery_and_next_green_task(self):
        started=time.monotonic();self.invocations=0
        initial=self.init();owner=self.state()['authorization']
        gate={'id':'stage-1','repair_revision':'fixture-code-v1','checks':['application','continuation']}
        self.call('transition',{'phase':'gate','gate':gate,'qualification':'no_go'})
        application=self.repo/'application.py'
        application.write_text('import json,sys\nfrom pathlib import Path\n'
            'value=json.loads(Path("config.json").read_text())\n'
            'print(json.dumps({"diagnosis":value.get("diagnosis"),"adoption":value["adoption"]}))\n'
            'sys.exit(0 if value.get("diagnosis")=="available" else 2)\n')
        config=self.repo/'config.json';config.write_text('{"adoption":"off"}')
        baseline_bytes=application.read_bytes()+config.read_bytes()
        def application_check():
            self.invocations+=1
            return subprocess.run([sys.executable,str(application)],cwd=self.repo,
                capture_output=True,text=True,timeout=10)
        def continuation_check():
            self.invocations+=1
            p=subprocess.run([sys.executable,str(SCRIPT.parents[3]/'hooks/plan_continue_classify.py')],
                input=json.dumps({'state':self.state(),'last_text':'Task assessment completed.'}),
                capture_output=True,text=True,timeout=10,check=True)
            self.assertEqual(json.loads(p.stdout)['decision'],'block')
        self.call('begin-round',{'gate_id':'stage-1'})
        failed=application_check();self.assertEqual(failed.returncode,2);continuation_check()
        self.call('record-verification',{'gate_id':'stage-1','repair_revision':'fixture-code-v1',
            'evidence':'original local application failure and actual Stop receipt',
            'checks':{'application':'failed','continuation':'passed'}})
        first=self.call('complete-round',{'gate_id':'stage-1'})
        self.assertEqual(first['verification_verdict'],'failed')
        self.call('begin-round',{'gate_id':'stage-1'})
        config.write_text('{"adoption":"off","diagnosis":"available"}')
        passed=application_check();self.assertEqual(passed.returncode,0)
        self.assertEqual(json.loads(passed.stdout)['adoption'],'off');continuation_check()
        self.call('complete-round',{'gate_id':'stage-1'},status='conflict')
        self.call('record-verification',{'gate_id':'wrong','repair_revision':'fixture-code-v1',
            'evidence':'wrong gate','checks':{'application':'passed','continuation':'passed'}},status='conflict')
        snapshot=self.repo/'.claude/plan-progress.json';before=snapshot.read_bytes()
        wrapper=Path(self.temp.name)/'interrupted-writer.py'
        wrapper.write_text('import os,runpy,sys\n'
            'sys.path.insert(0,'+repr(str(SCRIPT.parent))+')\n'
            'os.replace=lambda *args,**kwargs:os._exit(9)\n'
            'runpy.run_path('+repr(str(SCRIPT))+',run_name="__main__")\n')
        verification={'gate_id':'stage-1','repair_revision':'fixture-code-v1',
            'evidence':'original local application pass and actual Stop receipt',
            'checks':{'application':'passed','continuation':'passed'}}
        process=subprocess.Popen([sys.executable,str(wrapper),'record-verification','--repo',str(self.repo),
            '--expected-revision',str(self.rev),'--operation-id','interrupted-verification'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.invocations+=1
        try:
            stdout,stderr=process.communicate(json.dumps(verification),timeout=10)
        finally:
            if process.poll() is None:
                process.kill();process.wait(timeout=5)
        self.assertEqual(process.returncode,9,stderr);self.assertIsNotNone(process.poll())
        self.assertEqual(snapshot.read_bytes(),before)
        resumed=self.state()
        self.assertEqual(resumed['run_id'],initial['run_id'])
        self.assertEqual(resumed['authorization'],owner)
        self.assertEqual(resumed['rounds']['active']['number'],2)
        self.assertIsNone(resumed['rounds']['active']['verification'])
        self.call('record-verification',verification,op_id='interrupted-verification')
        receipt=self.call('complete-round',{'gate_id':'stage-1'},op_id='finish-round-two')
        self.assertEqual(receipt['verification_verdict'],'passed')
        retry=self.call('complete-round',{'gate_id':'stage-1'},op_id='finish-round-two',expected=0)
        self.assertEqual(retry,receipt)
        self.call('begin-round',{'gate_id':'stage-1'},status='budget_exhausted')
        self.call('transition',{'phase':'task','task':'next-green-task'})
        self.assertEqual(application_check().returncode,0)
        final=self.state()
        self.assertEqual(final['rounds']['completed'],2)
        self.assertEqual(final['qualification'],'no_go')
        self.assertEqual(final['task'],'next-green-task')
        self.assertEqual(final['authorization'],owner)
        self.assertFalse(any(r['receipt']['operation']=='authorize' for r in final['receipts'].values()))
        self.identity['candidate']['sha256']=hashlib.sha256(application.read_bytes()+config.read_bytes()).hexdigest()
        self.identity['baseline']['sha256']=hashlib.sha256(baseline_bytes).hexdigest()
        self.identity['evidence_hash']=hashlib.sha256(failed.stdout.encode()+passed.stdout.encode()).hexdigest()
        self.identity['dependencies']={'protocol':hashlib.sha256((SCRIPT.parent/'plan_state.py').read_bytes()).hexdigest()}
        observation={'availability':'available','schema':'pass','support':'unknown',
                     'useful':'unknown','environment':'normal'}
        self.run_cli('record',self.original(evidence_class='live_local_protocol',
            outcomes={'candidate':observation,'baseline':copy.deepcopy(observation)},comparison='unknown'))
        payload={'from_experiment':'exp-a','original_receipt_id':'result-1','identity':self.identity}
        for key in ('baseline','dependencies'):
            changed=copy.deepcopy(payload)
            if key=='baseline': changed['identity'][key]['sha256']='0'*64
            else: changed['identity'][key]['protocol']='0'*64
            self.run_cli('check-reuse',changed,experiment='exp-b',status='conflict')
        metrics={'evidence_class':'live_local_protocol','provider_calls':0,
            'elapsed_s':time.monotonic()-started,'state_application_and_classifier_invocations':self.invocations,
            'ledger_invocations':3,
            'owned_interrupted_process':process.pid,'interrupted_exit':process.returncode,
            'owner_amendments_before_next_task':0,'completed_rounds':2}
        print(json.dumps({'full_trace':metrics}),flush=True)

    def test_corruption_scope_counter_reset_and_unresolved_wait_controls(self):
        self.init();self.gate()
        self.call('authorize',{'source':'fixture owner initial source','scope':'different','budget':3},status='conflict')
        for key in ('rounds','remediation_round','authorization'):
            self.call('transition',{'phase':'task',key:0},status='state_error')
        self.call('set-blocker',{'disposition':'waiting_external','prevented_operation':'live claim',
            'dependency':'missing prerequisite','evidence':'original unavailable dependency','remaining_work':[]})
        self.call('transition',{'phase':'task'},status='conflict')
        self.call('begin-round',{'gate_id':'stage-1'},status='conflict')
        snapshot=self.repo/'.claude/plan-progress.json';snapshot.write_text('{partial')
        self.call('transition',{'phase':'task'},status='state_error')
        reader=SCRIPT.parents[3]/'hooks/plan_continue_classify.py'
        inputs=subprocess.run([sys.executable,str(reader),'--inputs'],input=json.dumps({'cwd':str(self.repo)}),
            capture_output=True,text=True,timeout=10,check=True)
        state=json.loads(inputs.stdout)['state'];self.assertEqual(state['state_status'],'state_error')
        decision=subprocess.run([sys.executable,str(reader)],input=json.dumps({'state':state,'last_text':'Next task'}),
            capture_output=True,text=True,timeout=10,check=True)
        self.assertEqual(json.loads(decision.stdout)['decision'],'allow')
        self.assertEqual(snapshot.read_text(),'{partial')


def run(group,manifest):
    if group=='authorized-experiment':
        suite=unittest.TestSuite([AuthorizedExperiment('test_actual_authorized_experiment_and_checkpoint')])
    elif group=='premises':
        suite=unittest.TestSuite([Premises(name) for name in
            ('test_early_disposable_artifact_and_missing_live_claim','test_authored_premise_fields_and_source_goal_mechanism')])
    elif group=='complete':
        corpus=HERE.parent/manifest['corpus']
        if not corpus.resolve().is_relative_to(HERE.parent):
            raise ValueError('corpus outside source deliverable')
        frozen=json.loads(corpus.read_text())
        identifiers=[case['id'] for case in frozen['cases']]
        if len(identifiers)!=len(set(identifiers)) or set(identifiers)!=set(SCENARIOS):
            raise ValueError('frozen scenario coverage is incomplete or duplicated')
        # Nameable coverage of every frozen scenario, through actual subprocesses.
        suite=unittest.TestSuite([Complete(name) for name in (
            'test_failure_interruption_recovery_and_next_green_task',
            'test_corruption_scope_counter_reset_and_unresolved_wait_controls')])
        suite.addTests(Storage(name) for name in (
            'test_worktrees_are_independent_and_branch_change_conflicts',
            'test_concurrent_compare_and_swap_allows_only_one_writer',
            'test_private_permissions_and_partial_temp_do_not_replace_snapshot',
            'test_missing_idle_differs_from_missing_owned_snapshot',
            'test_fresh_process_and_exact_idempotent_receipt',
            'test_completed_migration_requires_original_exact_verification',
            'test_legacy_wait_or_handoff_cannot_migrate_into_working',
            'test_finish_requires_no_active_work_and_preserves_receipts'))
        suite.addTest(AuthorizedExperiment('test_actual_authorized_experiment_and_checkpoint'))
        suite.addTest(Premises('test_early_disposable_artifact_and_missing_live_claim'))
        actual={test._testMethodName for test in suite}
        if not set(SCENARIOS.values())<=actual:
            raise ValueError('declared scenario has no executed behavioral test')
    else:
        raise ValueError('group deliverable not implemented: '+group)
    if suite.countTestCases()==0: raise ValueError('empty behavioral group')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful(): raise SystemExit(1)
