"""Resolve explicit execution metadata, never the directory holding a plan.

This helper reads metadata and Git identity without changing execution state.
The caller supplies the current root and whether a completed sub-plan boundary is
being crossed. Markdown is read through the shared format contract; execution
metadata has a deliberately small, single-line grammar.
"""
import importlib.util
import os
import re
import stat
import subprocess
from pathlib import Path

MAX_PLAN_BYTES = 8 * 1024 * 1024
# A locator for a caller asking only where the next sub-plan runs, never for publishing.
ANY_TASK = object()
_SPEC = importlib.util.spec_from_file_location(
    'handoff_plan_parser', Path(__file__).resolve().parents[3] / 'lib' / 'plan_parser.py')
PARSER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(PARSER)


class DestinationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise DestinationError(code)


def read_plan(path):
    """Bounded regular-file read; external records may use symlinked paths."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_PLAN_BYTES, 'plan-unreadable')
            chunks, size = [], 0
            while size <= MAX_PLAN_BYTES:
                chunk = os.read(fd, min(65536, MAX_PLAN_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            require(size <= MAX_PLAN_BYTES, 'plan-unreadable')
            return b''.join(chunks).decode('utf-8')
        finally:
            os.close(fd)
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, DestinationError):
            raise
        raise DestinationError('plan-unreadable') from exc


def visible_lines(text):
    """Ignore fenced examples; they cannot set routing metadata or gate state."""
    fence = None
    for line in text.splitlines():
        m = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            yield line


def header(text):
    lines = []
    for line in visible_lines(text):
        if line.startswith('## '):
            break
        lines.append(line)
    return '\n'.join(lines)


def value(raw):
    raw = raw.strip()
    if raw.startswith('`') and raw.endswith('`'):
        raw = raw[1:-1]
    require(bool(raw) and not any(ord(c) < 32 for c in raw), 'destination-metadata')
    return raw


def metadata(text, entry=False):
    pattern = (r'^- \*\*Execution (root|branch):\*\*\s*(.*)$' if entry
               else r'^Execution (root|branch):\s*(.*)$')
    result = {}
    for line in visible_lines(text):
        m = re.match(pattern, line)
        if m:
            require(m[1] not in result, 'destination-metadata')
            result[m[1]] = value(m[2])
    require(not result or set(result) == {'root', 'branch'}, 'destination-metadata')
    return result


def git_identity(root, branch=None):
    """Validate the exact existing Git root/worktree and its checked out branch."""
    try:
        root = Path(root)
        require(root.is_absolute() and root.is_dir(), 'destination-unavailable')
        root = root.resolve()
        p = subprocess.run(['git', '-C', str(root), 'rev-parse', '--show-toplevel'],
                           capture_output=True, text=True, timeout=10)
        require(p.returncode == 0, 'destination-unavailable')
        require(Path(p.stdout.strip()).resolve() == root, 'destination-root')
        p = subprocess.run(['git', '-C', str(root), 'branch', '--show-current'],
                           capture_output=True, text=True, timeout=10)
        actual = p.stdout.strip()
        require(p.returncode == 0 and bool(actual), 'branch-mismatch')
        require(branch is None or actual == branch, 'branch-mismatch')
        return str(root), actual
    except (OSError, subprocess.SubprocessError) as exc:
        raise DestinationError('destination-unavailable') from exc


def master_path(plan, text):
    links = PARSER.MASTER_BACKLINK_RE.findall(header(text))
    require(len(links) <= 1, 'master-metadata')
    if not links:
        return None
    target = PARSER.link_target(links[0])
    require(bool(target), 'master-metadata')
    return (Path(plan).parent / target).resolve()


def gates_done(text, master=False):
    active, groups = False, []
    for line in visible_lines(text):
        if master:
            if line.startswith('**Gate:**'):
                active = True
                groups.append([])
            elif line.startswith('#'):
                active = False
        elif line.startswith('#'):
            active = bool(PARSER.GATEHDR_RE.match(line))
            if active:
                groups.append([])
        if active and re.match(r'^\s*[-*]\s+', line):
            m = PARSER.GATE_ITEM_RE.match(line)
            if m is None:
                return False
            groups[-1].append(PARSER.gate_item_state(m[1]))
    return bool(groups) and all(g and all(s == 'done' for s in g) for g in groups)


def task_states(text):
    """Every task must have exactly one valid Status; omissions cannot mean done."""
    states, current = {}, None
    for line in visible_lines(text):
        if m := PARSER.TASK_RE.match(line):
            require(m[1] not in states, 'plan-metadata')
            current = m[1]
            states[current] = []
        elif line.startswith('#'):
            current = None
        elif PARSER.STATUS_LINE_RE.match(line):
            m = PARSER.STATUS_RE.match(line)
            require(current is not None and m is not None, 'plan-metadata')
            states[current].append(PARSER.status_state(m[1]))
    require(bool(states) and all(len(s) == 1 for s in states.values()), 'plan-metadata')
    return {task: s[0] for task, s in states.items()}


def plan_done(text):
    visible = '\n'.join(visible_lines(text))
    try:
        states = task_states(visible)
    except DestinationError:
        return False
    return (bool(PARSER.COMPLETED_RE.search(visible)) and not PARSER.contract_warnings(visible)
            and all(s == 'done' for s in states.values()) and gates_done(visible))


def runnable(text):
    require(not PARSER.ABANDONED_RE.search(text) and not PARSER.BLOCKED_ACCEPTED_RE.search(text)
            and not PARSER.plan_has_blocked_gate(text)
            and not re.search(r'^Status:\s*(?:cancelled|failed|blocked)\b', header(text), re.I | re.M),
            'run-not-runnable')


def entries(master, text):
    result, current = {}, None
    for line in visible_lines(text):
        match = PARSER.SUBPLAN_RE.match(line)
        if match:
            current = int(match[1])
            require(current not in result, 'master-metadata')
            result[current] = []
        elif line.startswith('## ') or (line.startswith('### ') and not match):
            current = None
        elif current is not None:
            result[current].append(line)
    require(bool(result), 'master-metadata')
    for n, lines in list(result.items()):
        block = '\n'.join(lines)
        links = PARSER.SUBPLAN_LINK_RE.findall(block)
        statuses = [m[1] for line in lines if (m := PARSER.STATUS_RE.match(line))]
        deps = re.findall(r'^- \*\*Depends on:\*\*\s*(.+)$', block, re.M)
        require(len(links) == len(statuses) == len(deps) == 1, 'master-metadata')
        link = PARSER.link_target(links[0])
        require(bool(link), 'master-metadata')
        dep_ids = set(int(x) for x in re.findall(r'Sub-plan\s+(\d+)', deps[0]))
        require(deps[0].strip() == 'none' or bool(dep_ids), 'master-metadata')
        require(n not in dep_ids and dep_ids <= result.keys(), 'master-metadata')
        result[n] = {'path': (master.parent / link).resolve(),
                     'status': PARSER.status_state(statuses[0]), 'deps': dep_ids,
                     'gates': gates_done(block, master=True), 'metadata': metadata(block, entry=True)}
    paths = [x['path'] for x in result.values()]
    require(len(set(paths)) == len(paths), 'master-metadata')
    return result


def locator_valid(text, locator):
    require(isinstance(locator, str) and bool(re.fullmatch(r'Task \d+\.\d+', locator)), 'locator-mismatch')
    require(task_states(text).get(locator.removeprefix('Task ')) in ('open', 'partial'), 'locator-mismatch')


def resolve_destination(plan, source_root, locator, *, boundary=False, selection=None,
                        current_subplan=None, disposition='working'):
    """Return {root, branch, plan, locator, master_plan}, or None if all entries closed.

    None is not proof of whole-master completion: the caller must also check the
    master's close-out. Missing/ambiguous/blocked work raises a named refusal.
    """
    require(disposition in ('working', 'repairing', 'handoff'), 'run-not-runnable')
    plan = Path(plan).resolve()
    text = read_plan(plan)
    runnable(text)
    master = plan if PARSER.is_master_plan(text, plan) else master_path(plan, text)
    entry_meta = {}
    if boundary:
        require(master is not None, 'master-metadata')
        mt = read_plan(master)
        runnable(mt)
        register = entries(master, mt)
        require(plan == master or plan in [e['path'] for e in register.values()], 'master-metadata')
        if plan == master:
            require(type(current_subplan) is int and current_subplan in register, 'current-subplan')
        else:
            inferred = next(n for n, e in register.items() if e['path'] == plan)
            require(current_subplan is None or current_subplan == inferred, 'current-subplan')
            current_subplan = inferred
        done = set()
        for n, entry in register.items():
            if entry['status'] == 'done':
                require(entry['gates'], 'pending-master-gate')
                require(plan_done(read_plan(entry['path'])), 'pending-subplan')
                done.add(n)
            require(entry['status'] != 'partial', 'run-not-runnable')
        require(current_subplan in done, 'pending-subplan')
        if len(done) == len(register):
            return None
        choices = [n for n, e in register.items() if n not in done and e['deps'] <= done]
        require(bool(choices), 'no-executable-work')
        if selection is None:
            require(len(choices) == 1, 'ambiguous-destination')
            selection = choices[0]
        require(type(selection) is int and selection in choices, 'not-executable')
        entry = register[selection]
        plan, entry_meta = entry['path'], entry['metadata']
        text = read_plan(plan)
        runnable(text)
        require(master_path(plan, text) == master, 'master-metadata')
    else:
        require(selection is None and current_subplan is None, 'not-executable')
    declared = metadata(header(text))
    require(not declared or not entry_meta or declared == entry_meta, 'destination-metadata')
    declared = declared or entry_meta
    root, branch = git_identity(declared.get('root', source_root), declared.get('branch'))
    if locator is not ANY_TASK:
        locator_valid(text, locator)
    return {'root': root, 'branch': branch, 'plan': str(plan), 'locator': locator,
            'master_plan': str(master) if master else None}


def other_root(plan, cwd, env):
    """(root, why): the next sub-plan's root when a v2 reader can carry the work there.

    root is None when the work stays here. why names a refusal when this could not be decided,
    for the caller to say out loud: the handoff or the next session meets the same refusal, and
    a measurement must never stop a run.
    """
    if '2' not in env.get('PLANNING_HANDOFF_VERSIONS', '1').split(','):
        return None, None
    try:
        p = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'],
                           capture_output=True, text=True, timeout=10)
        if p.returncode != 0:
            return None, 'destination-unavailable'
        here = str(Path(p.stdout.strip()).resolve())
        found = resolve_destination(plan, here, ANY_TASK, boundary=True)
    except DestinationError as exc:
        return None, str(exc)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return None, type(exc).__name__
    return (found['root'], None) if found and found['root'] != here else (None, None)
