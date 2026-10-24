#!/usr/bin/env python3
"""Actual metadata-ledger CLI: identity, denominator and refusal controls."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

from workflow_state_cases import Case, SCRIPT

LEDGER=SCRIPT.parent/'evaluation-ledger.py'


class Ledger(Case):
    def setUp(self):
        super().setUp()
        self.originals=self.repo/'proof/fixture/originals';self.originals.mkdir(parents=True)
        self.identity={'candidate':{'id':'candidate','sha256':'a'*64},
            'baseline':{'id':'baseline','sha256':'b'*64},'evidence_hash':'c'*64,
            'split_hash':'d'*64,'rubric_hash':'e'*64,'dependencies':{'config':'f'*64}}

    def original(self, receipt='result-1',**extra):
        outcome={'availability':'available','schema':'pass','support':'pass',
                 'useful':'pass','environment':'normal'}
        value={'schema_version':1,'original_receipt_id':receipt,'experiment_id':'exp-a',
            'identity':copy.deepcopy(self.identity),'evidence_class':'synthetic',
            'outcomes':{'candidate':copy.deepcopy(outcome),'baseline':copy.deepcopy(outcome)},
            'owner_preference':'unknown','comparison':'tie',**extra}
        path=self.originals/(receipt+'.json');path.write_text(json.dumps(value))
        return {'original_receipt':str(path.relative_to(self.repo)),
                'original_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

    def run_cli(self,operation,data=None,experiment='exp-a',status='ok'):
        p=subprocess.run([sys.executable,str(LEDGER),operation,'--repo',str(self.repo),
            '--plan','fixture','--experiment',experiment],input=json.dumps(data or {}),
            capture_output=True,text=True,timeout=10)
        self.assertNotIn('Traceback',p.stderr)
        result=json.loads(p.stdout);self.assertEqual(result['status'],status,(p.returncode,result))
        self.assertEqual(p.returncode,{'ok':0,'reused':0,'state_error':3,'conflict':4}[status])
        return result

    def test_duplicate_original_does_not_create_a_fresh_experiment(self):
        data=self.original();self.run_cli('record',data);self.run_cli('record',data)
        summary=self.run_cli('summarize');self.assertEqual(summary['original_results'],1)
        self.assertEqual(summary['comparisons']['tie'],1)

    def test_reuse_retains_original_attribution_and_rejects_each_changed_identity(self):
        self.run_cli('record',self.original())
        payload={'from_experiment':'exp-a','original_receipt_id':'result-1','identity':self.identity}
        reused=self.run_cli('check-reuse',payload,experiment='exp-b',status='reused')
        self.assertEqual(reused['original_experiment'],'exp-a')
        for key in self.identity:
            changed=copy.deepcopy(payload)
            if key in ('candidate','baseline'):
                changed['identity'][key]['sha256']='0'*64
            elif key=='dependencies':
                changed['identity'][key]['config']='0'*64
            else:
                changed['identity'][key]='0'*64
            self.run_cli('check-reuse',changed,experiment='exp-b',status='conflict')

    def test_environment_schema_and_semantic_denominators_are_separate(self):
        self.run_cli('record',self.original())
        unavailable={'availability':'unavailable','schema':'unknown','support':'unknown',
                     'useful':'unknown','environment':'failure'}
        available={'availability':'available','schema':'pass','support':'fail',
                   'useful':'unknown','environment':'normal'}
        self.run_cli('record',self.original('result-2',outcomes={
            'candidate':unavailable,'baseline':available},comparison='unknown'))
        report=self.run_cli('summarize')
        candidate=report['metrics']['candidate']
        self.assertEqual(candidate['availability']['eligible'],2)
        self.assertEqual(candidate['availability']['failed'],1)
        self.assertEqual(candidate['schema']['eligible'],1)
        self.assertEqual(candidate['support']['failed'],0)
        self.assertEqual(report['metrics']['baseline']['support']['failed'],1)
        self.assertEqual(report['owner_preference']['unknown'],1)
        self.assertEqual(report['environments']['candidate']['failure'],1)

    def test_original_hash_unknown_fields_and_impossible_claim_are_refused(self):
        data=self.original();self.run_cli('record',{**data,'original_sha256':'0'*64},status='conflict')
        self.run_cli('record',self.original('extra',prompt='private payload'),status='state_error')
        path=self.originals/'extra.json';value=json.loads(path.read_text());value.pop('prompt')
        value['outcomes']['candidate']['availability']='unavailable';path.write_text(json.dumps(value))
        self.run_cli('record',{'original_receipt':str(path.relative_to(self.repo)),
            'original_sha256':hashlib.sha256(path.read_bytes()).hexdigest()},status='state_error')

    def test_failed_result_cannot_be_rewritten_and_new_baseline_needs_new_experiment(self):
        self.run_cli('record',self.original(comparison='baseline_win'))
        self.run_cli('record',self.original(comparison='candidate_win'),status='conflict')
        identity=copy.deepcopy(self.identity);identity['baseline']['sha256']='0'*64
        self.run_cli('record',self.original('result-2',identity=identity),status='conflict')
        report=self.run_cli('summarize');self.assertEqual(report['comparisons']['baseline_win'],1)

    def test_corrupt_and_symlink_ledgers_are_preserved_and_refused(self):
        self.run_cli('record',self.original());path=self.repo/'proof/fixture/evaluation/exp-a.jsonl'
        before=path.read_bytes();path.write_bytes(before+b'{partial')
        self.run_cli('summarize',status='state_error');self.assertEqual(path.read_bytes(),before+b'{partial')
        path.unlink();outside=self.repo/'outside';outside.write_text('original')
        path.symlink_to(outside)
        self.run_cli('record',self.original('result-2'),status='state_error')
        self.assertEqual(outside.read_text(),'original')

    def test_existing_target_identity_and_evidence_class_cannot_be_bypassed(self):
        self.run_cli('record',self.original())
        payload={'from_experiment':'exp-a','original_receipt_id':'result-1','identity':self.identity}
        for key in ('candidate','baseline','dependencies','evidence_class'):
            identity=copy.deepcopy(self.identity);kind='synthetic'
            if key in ('candidate','baseline'): identity[key]['sha256']='0'*64
            elif key=='dependencies': identity[key]['config']='0'*64
            else: kind='prospective'
            target='target-'+key
            data=self.original('target-result-'+key,experiment_id=target,identity=identity,evidence_class=kind)
            self.run_cli('record',data,experiment=target)
            self.run_cli('check-reuse',payload,experiment=target,status='conflict')
        path=self.repo/'proof/fixture/evaluation/target-baseline.jsonl';path.write_text('{partial')
        self.run_cli('check-reuse',payload,experiment='target-baseline',status='state_error')
        self.assertEqual(path.read_text(),'{partial')

    def test_concurrent_distinct_original_results_are_both_retained(self):
        command=[sys.executable,str(LEDGER),'record','--repo',str(self.repo),
                 '--plan','fixture','--experiment','exp-a']
        payloads=[self.original('concurrent-'+str(i)) for i in (1,2)]
        processes=[subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True) for _ in payloads]
        try:
            for process,payload in zip(processes,payloads):
                process.stdin.write(json.dumps(payload));process.stdin.close();process.stdin=None
            outcomes=[(process,process.communicate(timeout=10)) for process in processes]
            for process,(stdout,stderr) in outcomes:
                self.assertEqual(process.returncode,0,stderr)
                self.assertEqual(json.loads(stdout)['status'],'ok')
        finally:
            for process in processes:
                if process.poll() is None: process.kill();process.wait(timeout=5)
        self.assertEqual(self.run_cli('summarize')['original_results'],2)

    def test_concurrent_original_records_are_serialized(self):
        command=[sys.executable,str(LEDGER),'record','--repo',str(self.repo),
                 '--plan','fixture','--experiment','exp-a']
        processes=[subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True) for _ in (1,2)]
        data=json.dumps(self.original())
        for p in processes:
            p.stdin.write(data);p.stdin.close();p.stdin=None
        outcomes=[(p,p.communicate(timeout=10)) for p in processes]
        for p,(stdout,stderr) in outcomes:
            self.assertEqual(p.returncode,0,stderr);self.assertEqual(json.loads(stdout)['status'],'ok')
        self.assertEqual(self.run_cli('summarize')['original_results'],1)

    def raw_cli(self,operation,raw,experiment='exp-a'):
        p=subprocess.run([sys.executable,str(LEDGER),operation,'--repo',str(self.repo),
            '--plan','fixture','--experiment',experiment],input=raw,
            capture_output=True,text=True,timeout=20)
        self.assertNotIn('Traceback',p.stderr)
        self.assertEqual((p.returncode,json.loads(p.stdout)['status']),(3,'state_error'),p.stdout)

    def test_deep_nesting_is_a_state_error_not_a_traceback(self):
        deep='['*200000
        self.raw_cli('summarize',deep)
        path=self.originals/'deep.json';path.write_text(deep)
        self.raw_cli('record',json.dumps({'original_receipt':str(path.relative_to(self.repo)),
            'original_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}))
        self.run_cli('record',self.original())
        ledger=self.repo/'proof/fixture/evaluation/exp-a.jsonl';ledger.write_text(deep+'\n')
        self.raw_cli('summarize','{}')
        self.assertEqual(ledger.read_text(),deep+'\n')

    def test_ledger_leaves_only_its_committable_file(self):
        evaluation=self.repo/'proof/fixture/evaluation'
        self.run_cli('record',self.original())
        self.assertEqual(sorted(p.name for p in evaluation.iterdir()),['exp-a.jsonl'])
        stale=evaluation/'.evaluation-0123abcd';stale.write_text('{partial')
        self.run_cli('record',self.original('result-2'))
        self.assertEqual(sorted(p.name for p in evaluation.iterdir()),['exp-a.jsonl'])
        self.assertEqual(self.run_cli('summarize')['original_results'],2)

    def test_original_receipt_must_be_under_originals(self):
        elsewhere=self.repo/'proof/fixture/other';elsewhere.mkdir()
        data=self.original('moved');moved=elsewhere/'moved.json'
        (self.originals/'moved.json').rename(moved)
        self.run_cli('record',{'original_receipt':str(moved.relative_to(self.repo)),
            'original_sha256':data['original_sha256']},status='state_error')


if __name__=='__main__':
    unittest.main(verbosity=2)
