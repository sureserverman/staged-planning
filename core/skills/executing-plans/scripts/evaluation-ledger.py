#!/usr/bin/env python3
"""Locked metadata-only experiment receipts. Never runs inference or grants acceptance."""
import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import uuid

sys.dont_write_bytecode=True
from plan_state import MAX_BYTES, StateError, digest, fields, need, owner_of

HASH=re.compile(r'^[0-9a-f]{64}$')
ID=re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')
KINDS=('synthetic','retrospective','prospective','live_local_protocol')
OUTCOME_KEYS=('availability','schema','support','useful','environment')


def identifier(value):
    need(isinstance(value,str) and ID.fullmatch(value) and value not in ('.','..'),
         'bounded metadata identifier required')
    return value


def hash_value(value):
    need(isinstance(value,str) and HASH.fullmatch(value),'SHA256 identity required')


def identity_valid(value):
    fields(value,('candidate','baseline','evidence_hash','split_hash','rubric_hash','dependencies'))
    for name in ('candidate','baseline'):
        fields(value[name],('id','sha256'));identifier(value[name]['id']);hash_value(value[name]['sha256'])
    for name in ('evidence_hash','split_hash','rubric_hash'):
        hash_value(value[name])
    deps=value['dependencies']
    need(isinstance(deps,dict) and deps and len(deps)<=64,'explicit nonempty dependency identities required')
    for name,sha in deps.items():
        identifier(name);hash_value(sha)


def original_valid(value):
    fields(value,('schema_version','original_receipt_id','experiment_id','identity',
                  'evidence_class','outcomes','owner_preference','comparison'))
    need(type(value['schema_version']) is int and value['schema_version']==1,'unsupported result schema')
    identifier(value['original_receipt_id']);identifier(value['experiment_id']);identity_valid(value['identity'])
    need(value['evidence_class'] in KINDS,'explicit evidence class required')
    fields(value['outcomes'],('candidate','baseline'))
    for outcome in value['outcomes'].values():
        fields(outcome,OUTCOME_KEYS)
        need(outcome['availability'] in ('available','unavailable','unknown'),'invalid availability')
        need(outcome['environment'] in ('normal','failure','unknown'),'declare environmental outcome explicitly')
        need(all(outcome[k] in ('pass','fail','unknown') for k in ('schema','support','useful')),
             'invalid output observation')
        if outcome['availability']!='available':
            need(all(outcome[k]=='unknown' for k in ('schema','support','useful')),
                 'unavailable output cannot establish semantic failure or success')
        if outcome['schema']!='pass':
            need(outcome['support']=='unknown' and outcome['useful']=='unknown',
                 'schema failure cannot establish output support/usefulness')
        need(outcome['useful']!='pass' or outcome['support']=='pass',
             'usefulness pass requires supported output')
    need(value['owner_preference'] in ('candidate','baseline','tie','unknown'),'invalid owner observation')
    eligible=all(o['availability']=='available' and o['schema']=='pass' for o in value['outcomes'].values())
    need(eligible or value['owner_preference']=='unknown','preference requires available valid alternatives')
    need(value['comparison'] in ('candidate_win','baseline_win','tie','unknown'),'invalid original comparison')


@contextlib.contextmanager
def directory_tree(root,parts,create=False):
    opened=[os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)]
    try:
        for part in parts:
            identifier(part)
            if create:
                try: os.mkdir(part,0o700,dir_fd=opened[-1])
                except FileExistsError: pass
            fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=opened[-1]);opened.append(fd)
            st=os.fstat(fd)
            need(st.st_uid==os.getuid() and not st.st_mode & 0o002,'unsafe metadata directory')
        yield opened[-1]
    finally:
        for fd in reversed(opened): os.close(fd)


def read_bytes(directory,name):
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        need(stat.S_ISREG(st.st_mode) and st.st_uid==os.getuid() and st.st_nlink==1
             and not st.st_mode & 0o002 and st.st_size<=MAX_BYTES,'unsafe or oversized receipt')
        raw=f.read(MAX_BYTES+1);need(len(raw)<=MAX_BYTES,'receipt too large');return raw


def read_original(root,plan,payload):
    fields(payload,('original_receipt','original_sha256'));hash_value(payload['original_sha256'])
    path=PurePosixPath(payload['original_receipt'])
    need(not path.is_absolute() and len(path.parts)==4 and path.parts[:3]==('proof',plan,'originals')
         and path.suffix=='.json','original receipt must be proof/<plan>/originals/<id>.json')
    identifier(path.name)
    with directory_tree(root,path.parts[:-1]) as directory:
        raw=read_bytes(directory,path.name)
    need(hashlib.sha256(raw).hexdigest()==payload['original_sha256'],
         'original result identity changed','conflict')
    value=json.loads(raw);original_valid(value);return value,str(path)


def read_rows(directory,name,plan,experiment):
    try: raw=read_bytes(directory,name)
    except FileNotFoundError: return []
    need(raw.endswith(b'\n'),'partial ledger preserved for diagnosis')
    rows=[];previous='0'*64
    for line in raw.splitlines():
        row=json.loads(line)
        fields(row,('schema_version','original_receipt_id','experiment_id','identity',
            'evidence_class','outcomes','owner_preference','comparison','plan_id',
            'original_path','original_sha256','recorded','previous_hash','integrity'))
        original_valid({k:v for k,v in row.items() if k in (
            'schema_version','original_receipt_id','experiment_id','identity','evidence_class',
            'outcomes','owner_preference','comparison')})
        hash_value(row['original_sha256'])
        need(row['plan_id']==plan and row['experiment_id']==experiment,'ledger belongs to another experiment')
        need(row['previous_hash']==previous and row['integrity']==digest({k:v for k,v in row.items() if k!='integrity'}),
             'ledger integrity mismatch')
        need(not any(old['original_receipt_id']==row['original_receipt_id'] for old in rows),
             'duplicate original result identity')
        if rows:
            need(row['identity']==rows[0]['identity'] and row['evidence_class']==rows[0]['evidence_class'],
                 'experiment identity changed inside ledger')
        previous=row['integrity'];rows.append(row)
    return rows


def publish(directory,name,rows):
    raw=b''.join((json.dumps(row,sort_keys=True)+'\n').encode() for row in rows)
    need(len(raw)<=MAX_BYTES,'ledger storage limit reached')
    temp='.evaluation-'+uuid.uuid4().hex
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
    try:
        with os.fdopen(fd,'wb') as f: f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(temp,name,src_dir_fd=directory,dst_dir_fd=directory);os.fsync(directory)
    finally:
        try: os.unlink(temp,dir_fd=directory)
        except FileNotFoundError: pass


def summarize(rows):
    metrics={};environments={}
    for alternative in ('candidate','baseline'):
        outcomes=[r['outcomes'][alternative] for r in rows];metrics[alternative]={}
        environments[alternative]={v:sum(o['environment']==v for o in outcomes) for v in ('normal','failure','unknown')}
        for key in ('availability','schema','support','useful'):
            eligible=[o for o in outcomes if key=='availability' or
                (o['availability']=='available' and (key=='schema' or o['schema']=='pass')
                 and (key!='useful' or o['support']=='pass'))]
            passed='available' if key=='availability' else 'pass'
            failed='unavailable' if key=='availability' else 'fail'
            metrics[alternative][key]={'eligible':len(eligible),
                'observed':sum(o[key]!='unknown' for o in eligible),
                'passed':sum(o[key]==passed for o in eligible),
                'failed':sum(o[key]==failed for o in eligible),
                'unknown':sum(o[key]=='unknown' for o in eligible),
                'ineligible':len(rows)-len(eligible)}
    preferences=[r['owner_preference'] for r in rows if all(
        o['availability']=='available' and o['schema']=='pass' for o in r['outcomes'].values())]
    return {'status':'ok','original_results':len(rows),'metrics':metrics,'environments':environments,
        'owner_preference':{'eligible':len(preferences),'observed':sum(p!='unknown' for p in preferences),
                           'ineligible':len(rows)-len(preferences),
                           **{v:preferences.count(v) for v in ('candidate','baseline','tie','unknown')}},
        'comparisons':{v:sum(r['comparison']==v for r in rows) for v in ('candidate_win','baseline_win','tie','unknown')},
        'evidence_class':rows[0]['evidence_class'],'identity':rows[0]['identity']}


def execute(args,payload):
    root=owner_of(args.repo)['root'];identifier(args.plan);identifier(args.experiment)
    experiment=args.experiment
    if args.operation=='check-reuse':
        fields(payload,('from_experiment','original_receipt_id','identity'))
        experiment=identifier(payload['from_experiment']);identifier(payload['original_receipt_id'])
        identity_valid(payload['identity'])
    elif args.operation=='summarize': fields(payload,())
    with directory_tree(root,('proof',args.plan,'evaluation'),args.operation=='record') as directory:
        name=experiment+'.jsonl'
        if args.operation!='record':
            rows=read_rows(directory,name,args.plan,experiment)
            need(rows,'experiment has no original results','conflict')
            if args.operation=='summarize': return summarize(rows)
            row=next((r for r in rows if r['original_receipt_id']==payload['original_receipt_id']),None)
            need(row is not None and row['identity']==payload['identity'],'reuse dependency or result identity changed','conflict')
            target=read_rows(directory,args.experiment+'.jsonl',args.plan,args.experiment)
            need(not target or (target[0]['identity']==row['identity'] and
                 target[0]['evidence_class']==row['evidence_class']),
                 'target experiment has incompatible identity or evidence class','conflict')
            return {'status':'reused','original_experiment':experiment,'target_experiment':args.experiment,
                    'original_receipt_id':row['original_receipt_id'],'original_sha256':row['original_sha256'],
                    'comparison':row['comparison'],'evidence_class':row['evidence_class']}
        # The lock is the evaluation directory itself, so no lock file sits beside the
        # ledger under proof/, where only the .jsonl may be committed. Under it, a temp a
        # killed writer left behind is removed before this write.
        lock=os.dup(directory)
        try:
            fcntl.flock(lock,fcntl.LOCK_EX)
            for stale in os.listdir(directory):
                if stale.startswith('.evaluation-'):
                    os.unlink(stale,dir_fd=directory)
            original,path=read_original(root,args.plan,payload)
            need(original['experiment_id']==experiment,'original belongs to another experiment','conflict')
            rows=read_rows(directory,name,args.plan,experiment)
            if rows:
                need(rows[0]['identity']==original['identity'] and rows[0]['evidence_class']==original['evidence_class'],
                     'changed alternatives or dependencies need a new experiment','conflict')
            existing=next((r for r in rows if r['original_receipt_id']==original['original_receipt_id']),None)
            if existing:
                need(existing['original_sha256']==payload['original_sha256'],'original result cannot be rewritten','conflict')
            else:
                row={**original,'plan_id':args.plan,'original_path':path,
                    'original_sha256':payload['original_sha256'],
                    'recorded':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    'previous_hash':rows[-1]['integrity'] if rows else '0'*64}
                row['integrity']=digest(row);rows.append(row);publish(directory,name,rows)
            return {'status':'ok','original_experiment':experiment,
                    'original_receipt_id':original['original_receipt_id'],'new_result':existing is None}
        finally: os.close(lock)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=('record','summarize','check-reuse'))
    parser.add_argument('--repo',type=Path,default=Path.cwd());parser.add_argument('--plan',required=True)
    parser.add_argument('--experiment',required=True);args=parser.parse_args()
    try:
        raw=sys.stdin.buffer.read(MAX_BYTES+1);need(len(raw)<=MAX_BYTES,'payload too large')
        output=execute(args,json.loads(raw or b'{}'))
    except StateError as exc: output={'status':exc.status,'message':str(exc)}
    except (OSError,ValueError,TypeError,KeyError,RecursionError,subprocess.SubprocessError) as exc:
        output={'status':'state_error','message':'invalid receipt or instrument failure: '+type(exc).__name__}
    print(json.dumps(output,sort_keys=True));return {'ok':0,'reused':0,'state_error':3,'conflict':4}[output['status']]


if __name__=='__main__': sys.exit(main())
