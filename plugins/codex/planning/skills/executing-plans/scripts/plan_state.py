"""Owned, revisioned execution snapshots. Stdlib, Unix advisory locks.

Only cooperating writers are serialized. The integrity hash detects accidental
edits; filesystem owners can fabricate metadata and are not authenticated here.
"""
import contextlib
import datetime
import fcntl
import hashlib
import json
import math
import os
import re
from pathlib import Path
import stat
import subprocess
import uuid

VERSION = 2
MAX_BYTES = 8 * 1024 * 1024
# Admission threshold; the hard history bound is MAX_BYTES. Active completion
# and re-verification remain possible here, rather than stranding reserved work.
MAX_RECEIPTS = 256
EXITS = {'ok':0, 'no_active_plan':0, 'budget_exhausted':2, 'state_error':3,
         'conflict':4, 'strategy_review_due':5}
DISPOSITIONS = ('working', 'repairing', 'waiting_external', 'awaiting_owner_decision',
                'handoff', 'complete')
# The id handoff-envelope.py new-id mints; a handoff blocker may record it.
HANDOFF_ID = re.compile(r'h-[0-9a-f]{20}')
PHASES = ('preflight', 'task', 'gate', 'blocked', 'handoff', 'closeout')
# What a lost snapshot took with it and no recovery can bring back.
RECOVERY_MISSING = ['receipts', 'verifications', 'revision_continuity', 'unlisted_gate_accounts']
# While a recovered history is unresolved, every other operation is refused.
RECOVERY_ALLOWED = ('record-verification', 'strategy-review', 'set-blocker', 'authorize',
                    'resolve-recovery')


class StateError(Exception):
    def __init__(self, message, status='state_error'):
        super().__init__(message)
        self.status = status


def need(condition, message, status='state_error'):
    if not condition:
        raise StateError(message, status)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True).encode()).hexdigest()


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def text_field(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 8192


def fields(payload, required, optional=()):
    need(isinstance(payload, dict), 'payload must be an object')
    need(set(required) <= set(payload) <= set(required) | set(optional),
         'missing or unknown payload fields')


def gate_valid(gate):
    need(isinstance(gate, dict) and set(gate) == {'id','repair_revision','checks'}, 'invalid gate')
    need(text_field(gate['id']) and text_field(gate['repair_revision']), 'gate identity required')
    checks = gate['checks']
    need(isinstance(checks,list) and checks and all(text_field(c) for c in checks)
         and len(checks) == len(set(checks)), 'nonempty unique declared checks required')


def verification_valid(gate, receipt):
    fields(receipt,('gate_id','repair_revision','evidence','checks'))
    need(receipt['gate_id']==gate['id'] and receipt['repair_revision']==gate['repair_revision'],
         'verification belongs to another gate or repair revision','conflict')
    need(text_field(receipt['evidence']) and isinstance(receipt['checks'],dict)
         and set(receipt['checks'])==set(gate['checks'])
         and all(v in ('passed','failed') for v in receipt['checks'].values()),
         'verification needs original evidence and exact declared check coverage')


def blocker_valid(state):
    disposition=state['disposition'];blocker=state['blocker'];phase=state['phase']
    if disposition in ('working','repairing'):
        need(blocker is None and phase not in ('blocked','handoff'),
             'runnable disposition contradicts blocker or phase')
        return
    if disposition=='complete':
        fields(blocker,('closeout_evidence',))
        need(text_field(blocker['closeout_evidence']) and phase=='closeout',
             'terminal state requires close-out evidence')
        return
    fields(blocker,('disposition','prevented_operation','evidence','dependency',
                    'remaining_work','cancel_authorization_id'),('owner_source','cancelled','reason','handoff_id'))
    need(blocker['disposition']==disposition and
         phase==('handoff' if disposition=='handoff' else 'blocked'),
         'blocker disposition or phase mismatch')
    need(all(text_field(blocker[k]) for k in ('prevented_operation','evidence','dependency')),
         'blocker metadata requires original evidence and dependency')
    remaining=blocker['remaining_work']
    need(isinstance(remaining,list) and len(remaining)<=64 and all(text_field(v) for v in remaining),
         'invalid remaining work')
    cancelled=blocker.get('cancelled',False)
    need(type(cancelled) is bool,'invalid cancellation flag')
    if cancelled:
        identity=blocker['cancel_authorization_id']
        need(disposition=='awaiting_owner_decision' and text_field(blocker.get('owner_source'))
             and isinstance(identity,str) and len(identity)==64 and
             all(c in '0123456789abcdef' for c in identity),'invalid cancellation authority')
    else:
        need(blocker['cancel_authorization_id'] is None,'unexpected cancellation authority')
    if disposition=='handoff':
        need(text_field(blocker.get('reason')),'handoff requires original measured reason')
    handoff_id_valid(disposition,blocker)


def handoff_id_valid(disposition,blocker):
    # Optional, so a snapshot written before the field existed stays valid.
    if 'handoff_id' in blocker:
        need(disposition=='handoff' and isinstance(blocker['handoff_id'],str)
             and HANDOFF_ID.fullmatch(blocker['handoff_id']) is not None,
             'handoff_id must be a minted id (h- and 20 hex) on a handoff')


def is_sha256(value):
    return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def citation_valid(citation,evidence_count):
    """A claim's source: where in which cited file. It ties the claim to a hashed file."""
    fields(citation,('evidence','at'))
    need(integer(citation['evidence']) and citation['evidence']<evidence_count
         and text_field(citation['at']),'a recovered claim must cite its source evidence')


def round_evidence_valid(rows,completed,evidence_count):
    # Length first: `completed` is caller input and may be any size.
    need(isinstance(rows,list) and len(rows)==completed
         and [r.get('round') if isinstance(r,dict) else None for r in rows]==list(range(1,completed+1)),
         'every spent round, and only those, needs evidence')
    for row in rows:
        fields(row,('round','verdict','source'))
        need(row['verdict'] in ('passed','failed','unknown'),'round evidence needs a verdict or unknown')
        citation_valid(row['source'],evidence_count)


def known_ids_valid(ids):
    need(isinstance(ids,list) and 1<=len(ids)<=MAX_RECEIPTS and all(text_field(v) for v in ids),
         'recovery must name the operation ids known to have run')


def recovery_valid(state):
    record=state['recovery']
    fields(record,('source_evidence','last_known','known_operation_ids','round_evidence',
                   'budget_source','reservation_source','account_sources','missing_history',
                   'recovered_under','resolution'))
    need(record['missing_history']==RECOVERY_MISSING,'recovery must name its missing history')
    need(text_field(record['recovered_under']),'recovery must keep the source it was made under')
    evidence=record['source_evidence']
    need(isinstance(evidence,list) and evidence,'recovery needs source evidence')
    for item in evidence:
        fields(item,('path','sha256'))
        need(text_field(item['path']) and is_sha256(item['sha256']),'invalid source evidence')
    last=record['last_known']
    fields(last,('revision','operation','source'))
    need(integer(last['revision'],1) and text_field(last['operation']),'invalid last known point')
    citation_valid(last['source'],len(evidence))
    known_ids_valid(record['known_operation_ids'])
    round_evidence_valid(record['round_evidence'],len(record['round_evidence']),len(evidence))
    citation_valid(record['budget_source'],len(evidence))
    if record['reservation_source'] is not None:
        citation_valid(record['reservation_source'],len(evidence))
    sources=record['account_sources']
    need(isinstance(sources,dict),'invalid saved account sources')
    for citation in sources.values():
        citation_valid(citation,len(evidence))
    resolution=record['resolution']
    if resolution is None:
        need(state['disposition'] in ('waiting_external','awaiting_owner_decision','handoff')
             and state['qualification']=='blocked','unresolved recovery must stay blocked')
    else:
        fields(resolution,('source','evidence'))
        need(text_field(resolution['source']) and text_field(resolution['evidence']),
             'invalid recovery resolution')


def validate(state):
    need(isinstance(state,dict) and state.get('schema_version') == VERSION, 'unsupported schema; migrate legacy explicitly')
    required={'schema_version','run_id','revision','owner','plan','phase','stage','task','task_desc',
              'updated','gate','rounds','gate_accounts','authorization','disposition',
              'qualification','blocker','strategy','receipts','integrity',
              'remediation_round','remediation_budget'}
    # `recovery` is optional, so a snapshot written before the field existed stays valid.
    need(set(state)-{'recovery'}==required, 'invalid snapshot fields')
    need(state['integrity']==digest({k:v for k,v in state.items() if k!='integrity'}), 'snapshot integrity mismatch')
    need(integer(state['revision'],1) and str(uuid.UUID(state['run_id']))==state['run_id'], 'invalid run/revision')
    need(isinstance(state['owner'],dict) and set(state['owner'])=={'root','common','git_dir','branch'}, 'invalid owner')
    need(all(text_field(v) for v in state['owner'].values()), 'owner identity required')
    need(text_field(state['plan']) and state['phase'] in PHASES and state['disposition'] in DISPOSITIONS, 'invalid projection')
    need(state['qualification'] in ('pending','pass','no_go','blocked'), 'invalid qualification')
    blocker_valid(state)
    if 'recovery' in state:
        recovery_valid(state)
    need(integer(state['stage']) and isinstance(state['task'],str) and isinstance(state['task_desc'],str), 'invalid task projection')
    stamp=datetime.datetime.fromisoformat(state['updated'].replace('Z','+00:00'))
    need(stamp.tzinfo is not None, 'UTC timestamp required')
    rounds=state['rounds']
    need(isinstance(rounds,dict) and set(rounds)=={'completed','budget','active'}, 'invalid round account')
    need(integer(rounds['completed']) and integer(rounds['budget'],1), 'invalid round counts')
    active=rounds['active']
    need(active is None or isinstance(active,dict), 'invalid active round')
    need(rounds['completed']+(active is not None)<=rounds['budget'], 'reserved work exceeds authority')
    need(state['remediation_round']==rounds['completed']+(active is not None)
         and state['remediation_budget']==rounds['budget'], 'projection disagrees with account')
    need(isinstance(state['receipts'],dict), 'invalid receipt history')
    need(isinstance(state['gate_accounts'],dict), 'invalid prior gate accounts')
    auth=state['authorization']
    need(isinstance(auth,dict) and set(auth)=={'source','scope','id'}, 'invalid authority')
    need(text_field(auth['source']) and text_field(auth['scope']) and auth['id']==digest({'source':auth['source'],'scope':auth['scope']}), 'authority identity mismatch')
    if state['strategy'] is not None:
        if isinstance(state['strategy'],dict) and set(state['strategy'])=={'migration_evidence'}:
            ev=state['strategy']['migration_evidence']
            need(isinstance(ev,dict) and text_field(ev.get('source')) and ev.get('disposition')=='completed',
                 'invalid original migration evidence')
            gate_valid(ev.get('gate'));verification_valid(ev['gate'],ev.get('verification'))
        else:
            strategy_valid(state['strategy'])
    if state['gate'] is not None:
        gate_valid(state['gate'])
    if active is not None:
        need(set(active) in ({'number','authorization_id','verification'},
                            {'number','authorization_id','verification','migration_source'},
                            {'number','authorization_id','verification','recovery_source'}), 'invalid active-round fields')
        need(state['gate'] is not None and active['number']==rounds['completed']+1
             and isinstance(active['authorization_id'],str) and len(active['authorization_id'])==64,
             'invalid active-round identity')
        if active['verification'] is not None:
            verification=active['verification']
            need(isinstance(verification,dict) and isinstance(verification.get('worktree_digest'),str)
                 and len(verification['worktree_digest'])==64, 'invalid repair fingerprint')
            verification_valid(state['gate'],{k:v for k,v in verification.items() if k!='worktree_digest'})
    for gate_id,account in state['gate_accounts'].items():
        need(text_field(gate_id) and isinstance(account,dict)
             and set(account)=={'completed','budget','active'} and account['active'] is None
             and integer(account['completed']) and integer(account['budget'],1)
             and account['completed']<=account['budget'], 'invalid saved gate account')
        need(account['completed']<=rounds['budget'] and account['budget']<=rounds['budget'],
             'saved gate account exceeds current scoped ceiling')
    for operation_id,row in state['receipts'].items():
        need(text_field(operation_id) and isinstance(row,dict) and set(row)=={'request','receipt'}
             and isinstance(row['request'],str) and len(row['request'])==64, 'invalid receipt record')
        receipt=row['receipt']
        need(isinstance(receipt,dict) and receipt.get('status')=='ok'
             and receipt.get('operation_id')==operation_id and receipt.get('run_id')==state['run_id']
             and integer(receipt.get('revision'),1) and receipt['revision']<=state['revision']
             and text_field(receipt.get('operation')), 'invalid receipt identity')
    return state


def owner_of(repo):
    def git(*args):
        p=subprocess.run(['git','-C',str(repo),*args],capture_output=True,text=True,timeout=10)
        need(p.returncode==0, 'git worktree identity unavailable')
        return p.stdout.strip()
    root=Path(git('rev-parse','--show-toplevel')).resolve()
    need(root.stat().st_uid==os.getuid() and not root.stat().st_mode & 0o002, 'unsafe repo root')
    marker=root/'.git'
    need(not marker.is_symlink(), 'symlink git marker refused')
    common=Path(git('rev-parse','--path-format=absolute','--git-common-dir'))
    git_dir=Path(git('rev-parse','--absolute-git-dir'))
    need(not common.is_symlink() and not git_dir.is_symlink(), 'symlink git directory refused')
    common=common.resolve();git_dir=git_dir.resolve()
    registered=git('worktree','list','--porcelain','-z').split('\0')
    need('worktree '+str(root) in registered, 'git pointer is not a registered worktree')
    if marker.is_file():
        need(git_dir.parent==common/'worktrees', 'unregistered git-directory pointer')
        backlink=git_dir/'gitdir'
        need(not backlink.is_symlink() and Path(backlink.read_text().strip())==marker,
             'linked worktree backlink mismatch')
    else:
        need(marker.is_dir() and git_dir==marker and common==git_dir, 'invalid main worktree marker')
    need(common.stat().st_uid==os.getuid() and not common.stat().st_mode & 0o002, 'unsafe common directory')
    # A detached HEAD (a tag build, a rebase, a bisect) has no branch, so it owns no run:
    # `symbolic-ref -q` exits 1 there, and any other failure is still an identity error.
    head=subprocess.run(['git','-C',str(repo),'symbolic-ref','-q','--short','HEAD'],
                        capture_output=True,text=True,timeout=10)
    need(head.returncode in (0,1), 'git worktree identity unavailable')
    return {'root':str(root),'common':str(common),'git_dir':str(git_dir),
            'branch':head.stdout.strip() if head.returncode==0 else None}


@contextlib.contextmanager
def own_directory(parent, name, create=False):
    parent_fd=os.open(parent,os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    fd=None
    try:
        if create:
            try:
                os.mkdir(name,mode=0o700,dir_fd=parent_fd)
            except FileExistsError:
                pass
        fd=os.open(name,os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,dir_fd=parent_fd)
        st=os.fstat(fd)
        need(st.st_uid==os.getuid() and not st.st_mode & 0o002, 'unsafe state directory')
        yield fd
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent_fd)


def read_json(directory, name):
    try:
        fd=os.open(name,os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,dir_fd=directory)
    except FileNotFoundError:
        return None
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        need(stat.S_ISREG(st.st_mode) and st.st_uid==os.getuid() and st.st_nlink==1
             and st.st_size<=MAX_BYTES and not st.st_mode & 0o002, 'unsafe snapshot or pointer')
        raw=f.read(MAX_BYTES+1)
        need(len(raw)<=MAX_BYTES, 'snapshot too large')
        return json.loads(raw)


def replace_json(directory,name,value):
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    need(len(raw)<=MAX_BYTES, 'snapshot exceeds size limit')
    temp='.plan-state-'+uuid.uuid4().hex
    fd=os.open(temp,os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,0o600,dir_fd=directory)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(temp,name,src_dir_fd=directory,dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temp,dir_fd=directory)
        except FileNotFoundError:
            pass


def pointer_name(owner):
    return hashlib.sha256(owner['git_dir'].encode()).hexdigest()+'.json'


def read_pointer(owner):
    try:
        with own_directory(owner['common'], 'plan-state-runs') as fd:
            value=read_json(fd,pointer_name(owner))
    except FileNotFoundError:
        return None
    if value is not None:
        need(isinstance(value,dict) and set(value)=={'owner','run_id'}, 'invalid pointer')
        need(value['owner']==owner, 'worktree or branch differs from run owner', 'conflict')
    return value


def publish_pointer(owner,run_id):
    with own_directory(owner['common'],'plan-state-runs',True) as fd:
        replace_json(fd,pointer_name(owner),{'owner':owner,'run_id':run_id})


def read_owned(owner, directory, legacy=False, lost_ok=False):
    """The validated owned snapshot, or None when idle. Init and migrate write the
    snapshot before the pointer, so an interruption between them leaves a valid snapshot
    with no pointer: that is accepted here, and the next mutation republishes the pointer
    (execute). A pointer with no snapshot is never left by an interruption; only `recover`,
    which exists for that loss, passes lost_ok."""
    pointer=read_pointer(owner)
    state=read_json(directory,'plan-progress.json')
    if state is None:
        need(pointer is None or lost_ok, 'owned active run has no snapshot')
        return None
    if legacy and isinstance(state,dict) and 'schema_version' not in state:
        need(pointer is None, 'legacy snapshot conflicts with v2 pointer')
        return state
    validate(state)
    need(state['owner']==owner, 'snapshot owned by another worktree or branch','conflict')
    need(pointer is None or pointer['run_id']==state['run_id'], 'run pointer mismatch')
    return state


def authority(payload):
    need(text_field(payload.get('source')) and text_field(payload.get('scope')), 'actual owner source and scope required')
    auth={'source':payload['source'],'scope':payload['scope']}
    return {**auth,'id':digest(auth)}


def new_state(owner,payload):
    budget=payload.get('budget',2)
    need(integer(budget,1) and text_field(payload.get('plan')), 'plan and positive budget required')
    return {'schema_version':VERSION,'run_id':str(uuid.uuid4()),'revision':0,'owner':owner,
            'plan':payload['plan'],'phase':'preflight','stage':payload.get('stage',0),
            'task':payload.get('task',''),'task_desc':payload.get('task_desc',''),
            'updated':'','gate':None,'rounds':{'completed':0,'budget':budget,'active':None},
            'gate_accounts':{},'authorization':authority(payload),'disposition':'working',
            'qualification':'pending','blocker':None,'strategy':None,'receipts':{},'integrity':''}


def transition(state,payload):
    need(state['disposition'] in ('working','repairing'),
         'resolve structured blocker before transitioning','conflict')
    fields(payload,('phase',),('stage','task','task_desc','gate','qualification'))
    need(payload['phase'] in ('preflight','task','gate','closeout'), 'use structured blocker for stopping')
    if 'gate' in payload:
        gate_valid(payload['gate'])
        old=state['gate'];new=payload['gate'];rounds=state['rounds']
        if old and old['id']!=new['id']:
            need(rounds['active'] is None, 'cannot switch an active gate','conflict')
            state['gate_accounts'][old['id']]=rounds
            state['rounds']=state['gate_accounts'].pop(new['id'],
                {'completed':0,'budget':rounds['budget'],'active':None})
        elif old and old!=new and rounds['active']:
            rounds['active']['verification']=None
        state['gate']=new
    state.update(payload)


def worktree_digest(owner):
    """Bind actual repair bytes without storing payloads or invoking filters.

    Proof receipts and execution metadata are excluded; the code they describe is
    bound. Ignored files are not inferred dependencies and need an explicit check.
    """
    root=Path(owner['root'])
    h=hashlib.sha256()
    def frame(value):
        h.update(len(value).to_bytes(8,'big'));h.update(value)
    def git(directory,*args):
        # Enumeration is raw index metadata. No diff, filters or fsmonitor command.
        p=subprocess.run(['git','-c','core.fsmonitor=false','-C',str(directory),*args],
                         capture_output=True,timeout=10)
        need(p.returncode==0,'cannot fingerprint repair worktree')
        need(len(p.stdout)<=MAX_BYTES,'repair inventory too large for local protocol')
        return p.stdout
    def visit(directory,prefix=b'',depth=0):
        need(depth<=16,'repair submodule nesting exceeds protocol bound')
        frame(prefix);frame(git(directory,'rev-parse','--verify','HEAD'))
        entries={}
        for entry in git(directory,'ls-files','--stage','-z').split(b'\0'):
            if not entry:
                continue
            metadata,name=entry.split(b'\t',1)
            mode,oid,stage=metadata.split()
            need(stage==b'0','unmerged repair index cannot be verified')
            entries[name]=(mode,metadata)
        for name in git(directory,'ls-files','--others','--exclude-standard','-z').split(b'\0'):
            if name:
                entries.setdefault(name,(b'',b'untracked'))
        for name,(mode,metadata) in sorted(entries.items()):
            full=prefix+name
            if full.split(b'/',1)[0] in (b'proof',b'.claude'):
                continue
            path=directory/os.fsdecode(name)
            need(path.parent.resolve().is_relative_to(root),'repair file parent escapes repository')
            frame(full);frame(metadata)
            try:
                st=path.lstat()
            except FileNotFoundError:
                need(mode!=b'160000','repair submodule is not initialized')
                frame(b'missing');continue
            if mode==b'160000':
                need(stat.S_ISDIR(st.st_mode) and not path.is_symlink(),
                     'repair submodule must be checked out without a symlink')
                # An uninitialized submodule must not resolve to the parent repo.
                need(git(path,'rev-parse','--show-toplevel').strip()==os.fsencode(str(path)),
                     'repair submodule is not initialized')
                frame(b'submodule');visit(path,full+b'/',depth+1)
            elif stat.S_ISLNK(st.st_mode):
                frame(b'symlink');frame(os.fsencode(os.readlink(path)))
            else:
                need(stat.S_ISREG(st.st_mode),'repair fingerprint accepts regular files only')
                fd=os.open(path,os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd,'rb') as f:
                    opened=os.fstat(f.fileno())
                    need(stat.S_ISREG(opened.st_mode),'repair file changed type while reading')
                    frame(b'regular');frame(str(stat.S_IMODE(opened.st_mode)).encode())
                    content=hashlib.sha256()
                    for chunk in iter(lambda:f.read(65536),b''):
                        content.update(chunk)
                    frame(content.digest())
    visit(root)
    return h.hexdigest()


def round_operation(state,operation,payload):
    gate=state['gate'];rounds=state['rounds']
    need(gate is not None,'declare gate before round operations','conflict')
    need(payload.get('gate_id')==gate['id'],'round belongs to another gate','conflict')
    if operation=='begin-round':
        fields(payload,('gate_id',))
        need(state['disposition'] in ('working','repairing'),'new round prevented by disposition','conflict')
        need(rounds['active'] is None,'one round already active','conflict')
        need(rounds['completed']<rounds['budget'],'new round exceeds recorded authority','budget_exhausted')
        rounds['active']={'number':rounds['completed']+1,
                         'authorization_id':state['authorization']['id'],'verification':None}
        state['disposition']='repairing'
    else:
        active=rounds['active']
        need(active is not None,'no active round to verify or complete','conflict')
        if operation=='record-verification':
            verification_valid(gate,payload)
            active['verification']={**payload,'worktree_digest':worktree_digest(state['owner'])}
        else:
            fields(payload,('gate_id',))
            receipt=active['verification']
            need(receipt is not None,'active round has no verification','conflict')
            need(receipt['worktree_digest']==worktree_digest(state['owner']),
                 'repair bytes changed after verification','conflict')
            verification_valid(gate,{k:v for k,v in receipt.items() if k!='worktree_digest'})
            rounds['completed']+=1;rounds['active']=None
            if state['disposition']=='repairing':
                state['disposition']='working'
            return {'verification_verdict':'passed' if all(v=='passed' for v in receipt['checks'].values())
                    else 'failed','verification':receipt}
    return {}


def authorize(state,payload):
    fields(payload,('source','scope'),('budget',))
    amendment=authority(payload)
    need(amendment['scope']==state['authorization']['scope'],
         'owner source applies to another scope','conflict')
    previous=state['authorization']
    ceiling=payload.get('budget',state['rounds']['budget'])
    need(integer(ceiling,1),'positive explicit authorization ceiling required')
    previous_budget=state['rounds']['budget']
    saved_budgets={gate:account['budget'] for gate,account in state['gate_accounts'].items()}
    accounts=[state['rounds'],*state['gate_accounts'].values()]
    reserved=max(account['completed']+(account['active'] is not None) for account in accounts)
    need(ceiling>=reserved,'ceiling cannot erase completed or active work','conflict')
    state['authorization']=amendment;state['rounds']['budget']=ceiling
    for account in state['gate_accounts'].values():
        account['budget']=ceiling
    return {'authorization':amendment,'previous_authorization':previous,'budget':ceiling,
            'previous_budget':previous_budget,'previous_saved_gate_budgets':saved_budgets}


def set_blocker(state,payload):
    fields(payload,('disposition','prevented_operation','evidence','dependency','remaining_work'),
           ('owner_source','cancelled','reason','handoff_id'))
    disposition=payload['disposition']
    need(disposition in DISPOSITIONS and disposition!='complete',
         'use finish with close-out evidence for completion')
    need(all(text_field(payload[k]) for k in ('prevented_operation','evidence','dependency')),
         'blocker needs prevented operation, original evidence and dependency')
    remaining=payload['remaining_work']
    need(isinstance(remaining,list) and len(remaining)<=64
         and all(text_field(v) for v in remaining),'remaining runnable work must be explicit')
    cancelled=payload.get('cancelled',False)
    need(type(cancelled) is bool,'cancellation must be an explicit boolean')
    old=state['blocker']
    need(not isinstance(old,dict) or not old.get('cancelled')
         or old.get('cancel_authorization_id')!=state['authorization']['id']
         or (cancelled and disposition=='awaiting_owner_decision'),
         'cancellation remains in force until fresh owner authorization','conflict')
    if cancelled:
        need(disposition=='awaiting_owner_decision' and text_field(payload.get('owner_source')),
             'cancellation needs actual owner source and decision disposition')
    if disposition=='handoff':
        need(text_field(payload.get('reason')),'handoff needs original measured reason and reference')
    handoff_id_valid(disposition,payload)
    if disposition in ('working','repairing'):
        need(disposition!='repairing' or state['rounds']['active'] is not None,
             'repairing disposition requires reserved work','conflict')
        state['blocker']=None;state['phase']='gate' if disposition=='repairing' else 'task'
    else:
        state['blocker']={**payload,'cancel_authorization_id':state['authorization']['id'] if cancelled else None}
        state['phase']='handoff' if disposition=='handoff' else 'blocked'
    state['disposition']=disposition
    return {'blocker':state['blocker'],'disposition':disposition}


def migrate(owner,legacy,payload):
    fields(payload,('source','scope'),('legacy_evidence','legacy_blocker'))
    need(isinstance(legacy,dict) and 'schema_version' not in legacy, 'only readable legacy state migrates')
    ev=payload.get('legacy_evidence')
    if 'remediation_round' not in legacy:
        need(isinstance(ev,dict) and text_field(ev.get('source')) and
             type(ev.get('completed')) is int and ev['completed']==0
             and ev.get('disposition')=='completed', 'missing legacy counter requires evidenced zero work')
        rnd=0
    else:
        rnd=legacy['remediation_round']
    budget=legacy.get('remediation_budget',2)
    need(integer(rnd) and integer(budget,1) and rnd<=budget, 'invalid legacy counter')
    state=new_state(owner,{'plan':legacy.get('plan'),'budget':budget,
                          'source':payload['source'],'scope':payload['scope']})
    if rnd:
        need(isinstance(ev,dict) and text_field(ev.get('source')) and
             ev.get('disposition') in ('active','completed'), 'ambiguous legacy round requires evidence')
        gate_valid(ev.get('gate'));state['gate']=ev['gate']
        state['rounds']['completed']=rnd-(ev['disposition']=='active')
        if ev['disposition']=='active':
            state['rounds']['active']={'number':rnd,'authorization_id':state['authorization']['id'],
                                      'verification':None,'migration_source':ev['source']}
        else:
            need(isinstance(ev.get('verification'),dict), 'completed legacy round requires original verification')
            verification_valid(state['gate'],ev['verification'])
            state['strategy']={'migration_evidence':ev}
    for key in ('phase','stage','task','task_desc'):
        if key in legacy:
            state[key]=legacy[key]
    if state['phase'] in ('blocked','handoff'):
        original_phase=state['phase'];blocker=payload.get('legacy_blocker')
        need(isinstance(blocker,dict),'legacy stop requires evidenced structured disposition')
        allowed=('handoff',) if original_phase=='handoff' else ('waiting_external','awaiting_owner_decision')
        need(blocker.get('disposition') in allowed,'legacy stop cannot migrate into runnable work')
        set_blocker(state,blocker)
    else:
        need('legacy_blocker' not in payload,'legacy blocker does not match stop phase')
    return state


def evidence_identity(item):
    """The caller's hash, checked against the file now, so a record cannot name evidence
    that is not there. It proves which bytes were cited, not that they are true."""
    fields(item,('path','sha256'))
    need(text_field(item['path']) and os.path.isabs(item['path']) and is_sha256(item['sha256']),
         'source evidence needs an absolute path and a sha256')
    fd=os.open(item['path'],os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        need(stat.S_ISREG(os.fstat(f.fileno()).st_mode),'source evidence must be a regular file')
        content=hashlib.sha256()
        for chunk in iter(lambda:f.read(65536),b''):
            content.update(chunk)
    need(content.hexdigest()==item['sha256'],'source evidence differs from its recorded hash','conflict')
    return {'path':item['path'],'sha256':item['sha256']}


def only_pointer_to(owner,run_id):
    with own_directory(owner['common'],'plan-state-runs') as fd:
        for name in os.listdir(fd):
            if name.endswith('.json') and name!=pointer_name(owner):
                other=read_json(fd,name)
                need(isinstance(other,dict) and other.get('run_id')!=run_id,
                     'another worktree also claims this run, or its pointer is invalid; recovery is ambiguous')


def recover(owner,pointer,state,payload,operation_id):
    """Rebuild a lost snapshot from evidence, keeping the run's identity and spent work.
    It starts blocked and names what it cannot know; it grants nothing."""
    need(state is None,'run has a snapshot; recovery never replaces one','conflict')
    need(pointer is not None,'no owned run to recover')
    fields(payload,('run_id','plan','source','scope','gate','rounds','round_evidence','last_known',
                    'known_operation_ids','source_evidence','budget_source','gate_accounts'),
           ('reservation_source','stage','task','task_desc','remaining_work'))
    need(payload['run_id']==pointer['run_id'],'recovery names another run','conflict')
    only_pointer_to(owner,pointer['run_id'])
    counts=payload['rounds']
    fields(counts,('completed','budget','reserved'))
    completed=counts['completed'];reserved=counts['reserved']
    need(integer(completed) and integer(counts['budget'],1) and type(reserved) is bool
         and completed+reserved<=counts['budget'],'recovered round counts required, within the ceiling')
    need(isinstance(payload['source_evidence'],list),'source evidence must be a list')
    count=len(payload['source_evidence'])
    round_evidence_valid(payload['round_evidence'],completed,count)
    citation_valid(payload['budget_source'],count)
    gate_valid(payload['gate'])
    known_ids_valid(payload['known_operation_ids'])
    need(operation_id not in payload['known_operation_ids'],'recovery reuses a pre-loss operation id','conflict')
    source=payload.get('reservation_source')
    need(reserved==('reservation_source' in payload),'a reserved round, and only one, needs its source')
    if reserved:
        citation_valid(source,count)
    sources=[evidence_identity(item) for item in payload['source_evidence']]
    state=new_state(owner,{k:payload[k] for k in ('plan','source','scope','stage','task','task_desc')
                           if k in payload}|{'budget':counts['budget']})
    state['run_id']=payload['run_id'];state['gate']=payload['gate']
    state['rounds']['completed']=completed
    if reserved:
        state['rounds']['active']={'number':completed+1,'authorization_id':state['authorization']['id'],
                                   'verification':None,'recovery_source':source}
    accounts=payload['gate_accounts']
    need(isinstance(accounts,dict) and payload['gate']['id'] not in accounts,
         'a saved account is for another gate')
    account_sources={}
    for gate_id,account in accounts.items():
        fields(account,('completed','budget','source'))
        citation_valid(account['source'],count)
        state['gate_accounts'][gate_id]={'completed':account['completed'],'budget':account['budget'],'active':None}
        account_sources[gate_id]=account['source']
    set_blocker(state,{'disposition':'awaiting_owner_decision',
                       'prevented_operation':'new rounds, round completion, finish and runnable work',
                       'evidence':'owned snapshot lost; this run was rebuilt from the recovery record',
                       'dependency':'owner review of the recovered history (resolve-recovery)',
                       'remaining_work':payload.get('remaining_work',[])})
    state['qualification']='blocked'
    state['recovery']={'source_evidence':sources,'last_known':payload['last_known'],
                       'known_operation_ids':payload['known_operation_ids'],
                       'round_evidence':payload['round_evidence'],'budget_source':payload['budget_source'],
                       'reservation_source':source,
                       'account_sources':account_sources,'missing_history':list(RECOVERY_MISSING),
                       'recovered_under':payload['source'],
                       'resolution':None}
    return state


def resolve_recovery(state,payload):
    fields(payload,('source','scope','evidence'))
    record=state.get('recovery')
    need(record is not None and record['resolution'] is None,'no unresolved recovery','conflict')
    need(authority(payload)['scope']==state['authorization']['scope'],
         'owner source applies to another scope','conflict')
    # Against the record, not the current authorization: `authorize` may have replaced that.
    need(payload['source']!=record['recovered_under'],
         'the review needs its own owner source, not the one the recovery cited','conflict')
    need(text_field(payload['evidence']),'resolving a recovery needs evidence of the review')
    record['resolution']={'source':payload['source'],'evidence':payload['evidence']}
    return {'resolution':record['resolution']}


def strategy_valid(payload):
    fields(payload,('gate_id','checkpoint','observations','assessment','alternatives'))
    need(text_field(payload['gate_id']),'strategy gate identity required')
    checkpoint=payload['checkpoint']
    fields(checkpoint,('after_completed','source'))
    need(integer(checkpoint['after_completed'],1) and text_field(checkpoint['source']),
         'authored checkpoint and source required')
    observations=payload['observations']
    need(isinstance(observations,list) and len(observations)<=256,'bounded observations required')
    rounds=set()
    for observation in observations:
        fields(observation,('round','defect_families','verified_gain','false_rejections','cost_ms','evidence'))
        number=observation['round'];families=observation['defect_families']
        need(integer(number,1) and number not in rounds,'unique observed round required')
        rounds.add(number)
        need(isinstance(families,list) and len(families)<=64 and
             all(text_field(family) for family in families) and len(families)==len(set(families)),
             'typed unique defect families required')
        need(text_field(observation['evidence']),'observation evidence required')
        for key in ('verified_gain','cost_ms'):
            value=observation[key]
            need(value is None or (type(value) in (int,float) and abs(value)<=10**15 and math.isfinite(value)
                 and (key!='cost_ms' or value>=0)), 'finite observation or null required')
        need(observation['false_rejections'] is None or integer(observation['false_rejections']),
             'false rejections must be measured count or null')
    need(payload['assessment'] in ('unknown','continue_repair','consider_redesign','owner_decision'),
         'explicit strategy assessment required')
    alternatives=payload['alternatives']
    need(isinstance(alternatives,list) and 1<=len(alternatives)<=16,'bounded alternatives required')
    for alternative in alternatives:
        fields(alternative,('kind','scope','evidence'))
        need(alternative['kind'] in ('repair','redesign','diagnosis') and
             alternative['scope'] in ('existing','new') and text_field(alternative['evidence']),
             'alternative kind, scope and evidence required')


def strategy_review(state,payload):
    if payload=={}:
        saved=state['strategy']
        if isinstance(saved,dict) and saved.get('gate_id')==state['gate']['id']:
            return strategy_review(state,saved)
        need(state['rounds']['completed']<2,'two-round checkpoint needs authored assessment',
             'strategy_review_due')
        raise StateError('default checkpoint has not been reached','conflict')
    strategy_valid(payload)
    need(state['gate'] is not None and payload['gate_id']==state['gate']['id'],
         'strategy belongs to another gate','conflict')
    completed=state['rounds']['completed']
    need(completed>=payload['checkpoint']['after_completed'],
         'authored checkpoint has not been reached','conflict')
    need(all(o['round']<=completed for o in payload['observations']),
         'observation refers to uncompleted work')
    observations=sorted(payload['observations'],key=lambda o:o['round'])
    families=[family for o in observations for family in o['defect_families']]
    gains=[o['verified_gain'] for o in observations]
    costs=[o['cost_ms'] for o in observations]
    # Simple suggestions, explicitly advisory. Missing values cannot fire a rule.
    repeated=any(families.count(family)>1 for family in set(families))
    no_gain=len(gains)>=2 and all(g is not None and g<=0 for g in gains)
    rising=len(costs)>=2 and all(c is not None for c in costs) and costs[-1]>costs[0]
    any_measurement=bool(families) or any(o[k] is not None for o in observations
                          for k in ('verified_gain','false_rejections','cost_ms'))
    assessment={'severity':'advisory','signal':
        'review_suggested' if repeated or no_gain or rising else
        'no_advisory_trigger' if any_measurement else 'unknown',
        'repeated_families':sorted(f for f in set(families) if families.count(f)>1),
        'no_verified_gain':no_gain,'rising_cost':rising,
        'available_cost_ms':[c for c in costs if c is not None],
        'owner_decision_required':payload['assessment']=='owner_decision' or
             any(a['scope']=='new' for a in payload['alternatives']),
        'corpus':'audit-and-benign-v1','calibration':'uncalibrated-advisory'}
    state['strategy']=payload
    return {'strategy_assessment':assessment}


def mutate(state,operation,payload):
    need(state['disposition']!='complete','terminal run cannot be mutated','conflict')
    record=state.get('recovery')
    if record is not None and record['resolution'] is None:
        need(operation in RECOVERY_ALLOWED,'recovered history is unresolved: '+operation+' refused','conflict')
        need(operation!='set-blocker' or payload.get('disposition') not in ('working','repairing'),
             'recovered history is unresolved: runnable work refused','conflict')
        need(operation!='authorize' or payload.get('budget',state['rounds']['budget'])<=state['rounds']['budget'],
             'recovered history is unresolved: no ceiling increase','conflict')
    if operation=='transition':
        transition(state,payload)
    elif operation in ('begin-round','record-verification','complete-round'):
        return round_operation(state,operation,payload)
    elif operation=='authorize':
        return authorize(state,payload)
    elif operation=='set-blocker':
        return set_blocker(state,payload)
    elif operation=='strategy-review':
        return strategy_review(state,payload)
    elif operation=='resolve-recovery':
        return resolve_recovery(state,payload)
    elif operation=='finish':
        fields(payload,('evidence',))
        need(text_field(payload['evidence']) and state['rounds']['active'] is None,
             'finish needs close-out evidence and no active round','conflict')
        state['disposition']='complete';state['phase']='closeout'
        state['blocker']={'closeout_evidence':payload['evidence']}
    else:
        raise StateError('operation not implemented: '+operation)
    return {}


def execute(repo,operation,payload,expected=None,operation_id=None):
    owner=owner_of(repo)
    need(operation=='show' or owner['branch'] is not None,
         'detached HEAD owns no run: switch to a branch first')
    if operation=='show':
        fields(payload,())
        try:
            with own_directory(owner['root'],'.claude') as directory:
                state=read_owned(owner,directory)
        except FileNotFoundError:
            need(read_pointer(owner) is None, 'owned run directory missing')
            state=None
        return {'status':'no_active_plan'} if state is None else {'status':'ok','state':state}
    need(integer(expected) and text_field(operation_id), 'expected revision and operation id required')
    with own_directory(owner['root'],'.claude',True) as directory:
        lock=os.open('plan-state.lock',os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                     0o600,dir_fd=directory)
        try:
            st=os.fstat(lock)
            need(stat.S_ISREG(st.st_mode) and st.st_uid==os.getuid() and st.st_nlink==1
                 and stat.S_IMODE(st.st_mode)==0o600,
                 'unsafe lock')
            fcntl.flock(lock,fcntl.LOCK_EX)
            state=read_owned(owner,directory,legacy=operation=='migrate',lost_ok=operation=='recover')
            if state and state.get('schema_version')==VERSION and read_pointer(owner) is None:
                # An init or migrate interrupted after its snapshot and before its pointer.
                publish_pointer(owner,state['run_id'])
            request=digest({'operation':operation,'payload':payload})
            if state and state.get('schema_version')==VERSION and operation_id in state['receipts']:
                old=state['receipts'][operation_id]
                need(old['request']==request,'operation id reused with changed payload','conflict')
                return old['receipt']
            if state and operation_id in state.get('recovery',{}).get('known_operation_ids',()):
                raise StateError('operation id ran before the snapshot was lost','conflict')
            revision=state.get('revision',0) if state else 0
            need(revision==expected,'expected revision is stale','conflict')
            if operation=='strategy-review' and payload=={}:
                need(state is not None,'no active plan to assess')
                return {'status':'ok','run_id':state['run_id'],'revision':revision,
                        **strategy_review(state,payload)}
            details={}
            if operation=='init':
                fields(payload,('plan','source','scope'),('budget','stage','task','task_desc'))
                need(state is None,'run already exists','conflict');state=new_state(owner,payload)
            elif operation=='migrate':
                state=migrate(owner,state,payload)
                details={'legacy_evidence':payload.get('legacy_evidence'),
                         'legacy_blocker':payload.get('legacy_blocker')}
            elif operation=='recover':
                state=recover(owner,read_pointer(owner),state,payload,operation_id)
            else:
                need(state is not None,'no active plan to mutate','state_error')
                completing_active=(state['rounds']['active'] is not None and
                                   operation in ('record-verification','complete-round'))
                need(len(state['receipts'])<MAX_RECEIPTS
                     or operation in ('finish','set-blocker','authorize','strategy-review','resolve-recovery')
                     or completing_active,
                     'receipt capacity reached; finish/archive before another run','conflict')
                details=mutate(state,operation,payload)
            state['revision']=revision+1
            state['updated']=datetime.datetime.now(datetime.timezone.utc).isoformat()
            rounds=state['rounds']
            state['remediation_round']=rounds['completed']+(rounds['active'] is not None)
            state['remediation_budget']=rounds['budget']
            receipt={'status':'ok','run_id':state['run_id'],'revision':state['revision'],
                     'operation_id':operation_id,'operation':operation,**details}
            state['receipts'][operation_id]={'request':request,'receipt':receipt}
            state['integrity']=digest({k:v for k,v in state.items() if k!='integrity'})
            validate(state)
            # Snapshot first, pointer second: an interruption between them leaves a valid
            # snapshot the next mutation repairs, never a pointer with nothing behind it.
            replace_json(directory,'plan-progress.json',state)
            if operation in ('init','migrate'):
                publish_pointer(owner,state['run_id'])
            return receipt
        finally:
            os.close(lock)


def result(repo,operation,payload,expected=None,operation_id=None):
    try:
        return execute(repo,operation,payload,expected,operation_id)
    except StateError as e:
        return {'status':e.status,'message':str(e)}
    except (OSError,ValueError,TypeError,KeyError,AttributeError,RecursionError,
            subprocess.SubprocessError) as e:
        # RecursionError: a deeply nested snapshot, pointer or payload is invalid state.
        return {'status':'state_error','message':'invalid state or instrument failure: '+type(e).__name__}


def budget_result(repo):
    outcome=result(repo,'show',{})
    if outcome['status']!='ok':
        return outcome
    state=outcome['state'];rounds=state['rounds']
    record=state.get('recovery')
    if record is not None and record['resolution'] is None:
        return {'status':'conflict','message':'recovered history is unresolved: no round may start or finish'}
    if rounds['active'] is not None:
        return {'status':'ok','message':'active authorized round may finish'}
    if rounds['completed']>=rounds['budget']:
        return {'status':'budget_exhausted','message':'new round requires evidenced owner extension'}
    return {'status':'ok','message':'begin-round is the authority to reserve new work'}
