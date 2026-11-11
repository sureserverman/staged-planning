#!/usr/bin/env python3
"""The behaviour-rule eval cases are runnable, and their graders can fail.

evals/behaviour-rules/cases/ holds three synthetic `claude plugin eval` cases, one per
behaviour rule, each with a sabotage control: the same case with one added prompt line
telling the session to do the forbidden thing. A paid run is what measures a model; this
suite checks, offline, everything a paid run would otherwise find out the expensive way:

  shape       each case folder has a case.yaml with schema_version "1.1", its own name,
              a scaffold script, max_turns <= 200, timeout_seconds <= 3600, a prompt, and
              at least one grader of a known type
  scaffold    each scaffold.sh, run in an empty temp dir with the eval's small fixed
              environment, leaves a git repo on a branch other than main, a clean tree,
              and exactly one plan under docs/plans/ that core/lib/plan_parser.py parses
              (tasks with Status fields; stages and a gate, or a light heading and a gate)
  graders     every file a grader reads exists in the scaffolded workspace; the free
              graders (regex, tool_used) are evaluated here on the honest outcome and on
              the sabotaged one, and must pass the first and fail the second
  controls    a control's prompt is its twin's plus exactly one added line, and its
              scaffold, graders and run limits are byte-for-byte the twin's
  leak-check  no file under evals/ matches scripts/leak-check.py; its arguments are
              operator-specific, so they come from LEAK_CHECK_ARGS, and without it the
              check says it did not run and the rest still decides the result

stdlib only. YAML is read by a small parser for the subset these files use; a file that
steps outside that subset fails here rather than being half-read.
"""
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CASES = os.path.join(REPO, "evals", "behaviour-rules", "cases")
TWINS = ["gate-blocked", "run-to-completion", "dispatch-mandated"]
CONTROL = "-control"
GRADER_TYPES = {"regex", "tool_used", "tool_order", "file_exists", "llm", "baseline"}
MAX_TURNS, MAX_TIMEOUT = 200, 3600
MISSING_TOOL = "qzx-gatecheck"
FAILS = []


def check(ok, msg, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)
        if detail:
            print("     | " + str(detail)[-800:].replace("\n", "\n     | "))
    return ok


def load_parser():
    path = os.path.join(REPO, "core", "lib", "plan_parser.py")
    sys.dont_write_bytecode = True  # keep core/lib free of a __pycache__ this test made
    spec = importlib.util.spec_from_file_location("plan_parser", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PP = load_parser()


# --- a strict reader for the YAML subset the case files use --------------------------
# Block mappings (two-space indent), scalars (bare, "double", 'single', integers), flow
# lists of scalars, and `|` literal blocks. Anything else raises, naming the line.

class YamlSubsetError(ValueError):
    pass


def _scalar(raw, where):
    s = raw.strip()
    if s.startswith('"'):
        if not s.endswith('"') or len(s) < 2:
            raise YamlSubsetError(f"{where}: unterminated double-quoted scalar")
        body = s[1:-1]
        if re.search(r'(?<!\\)"', body):
            raise YamlSubsetError(f"{where}: stray quote in a double-quoted scalar")
        return re.sub(r'\\(["\\])', r"\1", body)
    if s.startswith("'"):
        if not s.endswith("'") or len(s) < 2:
            raise YamlSubsetError(f"{where}: unterminated single-quoted scalar")
        return s[1:-1].replace("''", "'")
    if s.startswith("["):
        if not s.endswith("]"):
            raise YamlSubsetError(f"{where}: unterminated flow list")
        inner = s[1:-1].strip()
        return [_scalar(x, where) for x in inner.split(",")] if inner else []
    if s[:1] in "{&*!|>%@`":
        raise YamlSubsetError(f"{where}: unsupported YAML construct {s[:1]!r}")
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if " #" in s:
        raise YamlSubsetError(f"{where}: trailing comment on a bare scalar")
    return s


def parse_yaml(text, label):
    lines = text.split("\n")
    root, stack = {}, [(-1, None)]
    stack[0] = (-1, root)
    i = 0
    while i < len(lines):
        line = lines[i]
        where = f"{label}:{i + 1}"
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise YamlSubsetError(f"{where}: tab indentation")
        indent = len(line) - len(line.lstrip(" "))
        m = re.match(r"^( *)([A-Za-z_][A-Za-z0-9_]*):(?: (.*))?$", line)
        if not m:
            raise YamlSubsetError(f"{where}: not a `key: value` line: {line!r}")
        key, val = m.group(2), (m.group(3) or "").rstrip()
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if key in parent:
            raise YamlSubsetError(f"{where}: duplicate key {key!r}")
        if val == "|":
            body, j = [], i + 1
            block_indent = None
            while j < len(lines):
                nxt = lines[j]
                if nxt.strip():
                    ni = len(nxt) - len(nxt.lstrip(" "))
                    if ni <= indent:
                        break
                    block_indent = ni if block_indent is None else block_indent
                    if ni < block_indent:
                        raise YamlSubsetError(f"{label}:{j + 1}: under-indented block line")
                    body.append(nxt[block_indent:])
                else:
                    body.append("")
                j += 1
            while body and body[-1] == "":
                body.pop()
            parent[key] = "\n".join(body) + "\n"
            i = j
            continue
        if val == "":
            child = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _scalar(val, where)
        i += 1
    return root


def split_frontmatter(text, label):
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        raise YamlSubsetError(f"{label}: no `---` frontmatter block")
    return parse_yaml(m.group(1), label), m.group(2)


def cross_check_yaml(text, parsed, label):
    """Where PyYAML happens to be installed, it must read the file the same way."""
    try:
        import yaml  # optional: the suite never needs it
    except ImportError:
        return
    check(yaml.safe_load(text) == parsed, f"{label}: PyYAML reads it the same way")


# --- reading one case ------------------------------------------------------------------

def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def load_case(name):
    d = os.path.join(CASES, name)
    case = {"dir": d, "graders": {}}
    if not check(os.path.isdir(d), f"{name}: case folder exists"):
        return None
    cy = os.path.join(d, "case.yaml")
    if not check(os.path.isfile(cy), f"{name}: case.yaml exists"):
        return None
    try:
        text = read(cy)
        case["yaml"] = parse_yaml(text, f"{name}/case.yaml")
    except YamlSubsetError as e:
        check(False, f"{name}: case.yaml is in the supported YAML subset", e)
        return None
    cross_check_yaml(text, case["yaml"], f"{name}/case.yaml")
    gdir = os.path.join(d, "graders")
    files = sorted(f for f in os.listdir(gdir) if f.endswith(".md")) if os.path.isdir(gdir) else []
    for f in files:
        gtext = read(os.path.join(gdir, f))
        try:
            fm, body = split_frontmatter(gtext, f"{name}/graders/{f}")
        except YamlSubsetError as e:
            check(False, f"{name}: grader {f} is in the supported YAML subset", e)
            continue
        fm_text = re.match(r"^---\n(.*?)\n---", gtext, re.S).group(1)
        cross_check_yaml(fm_text, fm, f"{name}/graders/{f}")
        case["graders"][f[:-3]] = (fm, body, gtext)
    return case


def check_shape(name, case):
    y = case["yaml"]
    check(y.get("schema_version") == "1.1", f'{name}: schema_version is "1.1"')
    check(y.get("name") == name, f"{name}: name matches the folder")
    ctx = y.get("context") or {}
    script = ctx.get("scaffold_script") if isinstance(ctx, dict) else None
    check(script == "scaffold.sh" and os.path.isfile(os.path.join(case["dir"], "scaffold.sh")),
          f"{name}: context.scaffold_script names the case's scaffold.sh")
    ex = y.get("execution") or {}
    mt, to = ex.get("max_turns"), ex.get("timeout_seconds")
    check(isinstance(mt, int) and 0 < mt <= MAX_TURNS, f"{name}: max_turns {mt} is 1..{MAX_TURNS}")
    check(isinstance(to, int) and 0 < to <= MAX_TIMEOUT,
          f"{name}: timeout_seconds {to} is 1..{MAX_TIMEOUT}")
    prompt = ex.get("prompt")
    check(isinstance(prompt, str) and prompt.strip() != "", f"{name}: execution.prompt is set")
    check(not os.path.exists(os.path.join(case["dir"], "prompt.md")),
          f"{name}: no prompt.md (the prompt lives in case.yaml alone)")
    check(len(case["graders"]) >= 1, f"{name}: at least one grader ({len(case['graders'])})")
    for g, (fm, body, _) in case["graders"].items():
        check(fm.get("type") in GRADER_TYPES, f"{name}: grader {g} has a known type ({fm.get('type')})")
        if fm.get("type") == "llm":
            check(bool(body.strip()) and "PASS" in body and "FAIL" in body,
                  f"{name}: llm grader {g} states PASS and FAIL conditions")


# --- scaffolds -------------------------------------------------------------------------

def git(ws, *args):
    return subprocess.run(["git", "-C", ws, *args], capture_output=True, text=True)


def run_scaffold(name, case, tmp):
    """Run scaffold.sh the way the eval does: an empty dir, a small fixed environment."""
    ws = os.path.join(tmp, name, "ws")
    home = os.path.join(tmp, name, "home")
    os.makedirs(ws)
    os.makedirs(home)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home, "TMPDIR": tmp,
           "TERM": "dumb", "LANG": "C", "GIT_CONFIG_NOSYSTEM": "1"}
    try:
        r = subprocess.run(["bash", os.path.join(case["dir"], "scaffold.sh")], cwd=ws, env=env,
                           capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        check(False, f"{name}: scaffold.sh finishes inside the eval's 120 s limit")
        return None
    if not check(r.returncode == 0, f"{name}: scaffold.sh exits 0", r.stdout + r.stderr):
        return None
    # Run where it does not belong (a folder that already holds a repo), it must refuse
    # rather than re-point that repo's HEAD.
    busy = os.path.join(tmp, name, "busy")
    os.makedirs(busy)
    git(busy, "init", "-q")
    head_before = read(os.path.join(busy, ".git", "HEAD"))
    rb = subprocess.run(["bash", os.path.join(case["dir"], "scaffold.sh")], cwd=busy, env=env,
                        capture_output=True, text=True, timeout=120)
    check(rb.returncode != 0 and read(os.path.join(busy, ".git", "HEAD")) == head_before
          and not os.path.exists(os.path.join(busy, "docs")),
          f"{name}: scaffold.sh refuses a non-empty folder and leaves it untouched", rb.stdout + rb.stderr)
    return ws


def check_scaffold(name, ws):
    """Returns (plan relpath, plan text) when the workspace holds one parseable plan."""
    inside = git(ws, "rev-parse", "--show-toplevel")
    if not check(inside.returncode == 0 and os.path.samefile(inside.stdout.strip(), ws),
                 f"{name}: the workspace is a git repo's top level", inside.stderr):
        return None
    branch = git(ws, "symbolic-ref", "--short", "HEAD").stdout.strip()
    check(branch not in ("", "main", "master"), f"{name}: on a branch other than main ({branch!r})")
    check(git(ws, "rev-parse", "--verify", "-q", "HEAD").returncode == 0,
          f"{name}: an initial commit exists")
    dirty = git(ws, "status", "--porcelain", "--untracked-files=all").stdout
    check(dirty == "", f"{name}: the scaffolded tree is committed and clean", dirty)
    pdir = os.path.join(ws, "docs", "plans")
    plans = sorted(f for f in os.listdir(pdir) if f.endswith("-plan.md")) if os.path.isdir(pdir) else []
    if not check(len(plans) == 1, f"{name}: exactly one plan under docs/plans/ ({plans})"):
        return None
    rel = f"docs/plans/{plans[0]}"
    text = read(os.path.join(ws, rel))
    lines = text.splitlines()
    tasks = [ln for ln in lines if PP.TASK_RE.match(ln)]
    statuses = [ln for ln in lines if PP.STATUS_RE.match(ln)]
    stages = [ln for ln in lines if PP.STAGE_RE.match(ln)]
    gates = [ln for ln in lines if PP.GATE_RE.match(ln)]
    check(len(tasks) >= 1, f"{name}: the plan parses to tasks ({len(tasks)})")
    check(len(statuses) == len(tasks), f"{name}: one Status field per task "
          f"({len(statuses)} for {len(tasks)})")
    check(all(PP.status_state(PP.STATUS_RE.match(s).group(1)) == "open" for s in statuses),
          f"{name}: every task starts open")
    check(len(stages) >= 1 and len(gates) == len(stages),
          f"{name}: stages and one gate each ({len(stages)} stages, {len(gates)} gates)")
    check(PP.contract_warnings(text, rel) == [], f"{name}: no plan-contract warnings",
          PP.contract_warnings(text, rel))
    check(PP.plan_terminal_state(text) == (False, None, None)
          and not PP.COMPLETED_RE.search(text) and not PP.plan_blocked(text)[0],
          f"{name}: the plan is open: not abandoned, completed or blocked")
    light = PP.is_light_plan(text, rel)
    if light:
        check(bool(PP.LIGHT_HEADING_RE.search(text)) and rel.endswith("-light-plan.md"),
              f"{name}: a light plan carries both the heading and the file name")
        check(len(stages) == 1 and 2 <= len(tasks) <= 5, f"{name}: a light plan is one stage of 2-5 tasks")
    else:
        for field in ("## Research Summary", "## Preflight"):
            check(field in text, f"{name}: a Standard plan has {field!r}")
        for field in ("**Goal:**", "**Depends on:**", "**Blocks:**", "**Risk:**", "**Rollback:**"):
            check(text.count(field) >= len(stages), f"{name}: every stage has {field}")
        for field in ("- **Dispatch:**", "- **Test:**", "- **Red-Green max cycles:**"):
            check(text.count(field) == len(tasks), f"{name}: every task has {field}")
    return rel, text, light


# --- the free graders, evaluated offline -----------------------------------------------
# regex and tool_used are computed from text, so this suite can run them on a simulated
# honest result and a simulated sabotaged one. llm graders need a judge; their PASS/FAIL
# wording is checked above and their verdicts are the pilot's to measure.

def js_flags(flags):
    out = 0
    for ch in flags or "":
        out |= {"m": re.M, "i": re.I, "s": re.S}.get(ch, 0)
        if ch not in "mis":
            raise ValueError(f"flag {ch!r} has no meaning here")
    return out


def regex_verdict(fm, text):
    hits = len(re.findall(fm["pattern"], text, js_flags(fm.get("flags"))))
    match = str(fm.get("match", "contains"))
    if match == "not_contains":
        return hits == 0
    if match.startswith("count:"):
        return hits == int(match.split(":", 1)[1])
    return hits >= 1


def tool_used_verdict(fm, calls):
    pat = fm.get("input_match")
    n = sum(1 for tool, inp in calls if tool == fm["tool"]
            and (pat is None or re.search(pat, json.dumps(inp, separators=(",", ":")))))
    lo, hi = int(fm.get("min", 1)), fm.get("max")
    return n >= lo and (hi is None or n <= int(hi))


def tick_status(text, task_ids):
    out, cur = [], None
    for ln in text.splitlines(keepends=True):
        tm = PP.TASK_RE.match(ln.rstrip("\n"))
        if tm:
            cur = tm.group(1)
        if cur in task_ids and PP.STATUS_RE.match(ln):
            ln = ln.replace("**Status:** [ ]", "**Status:** [x]", 1)
        out.append(ln)
    return "".join(out)


def set_gate_line(text, needle, mark):
    return "".join(ln.replace("- [ ]", f"- [{mark}]", 1) if needle in ln else ln
                   for ln in text.splitlines(keepends=True))


def tick_gates(text, stages):
    """Tick every open gate box under the `### Stage N Gate` headings for N in stages."""
    out, cur = [], None
    for ln in text.splitlines(keepends=True):
        if ln.startswith("###"):
            gm = PP.GATEHDR_RE.match(ln)
            cur = int(gm.group(1)) if gm else None
        elif cur in stages and PP.GATE_ITEM_RE.match(ln):
            ln = ln.replace("- [ ]", "- [x]", 1)
        out.append(ln)
    return "".join(out)


def task_ids(text):
    return [m.group(1) for m in (PP.TASK_RE.match(ln) for ln in text.splitlines()) if m]


def outcomes(family, text):
    """(honest, sabotaged) simulated results: plan file texts and Agent calls."""
    ids = task_ids(text)
    if family == "gate-blocked":
        done = tick_status(text, set(ids))
        return ({"plan": set_gate_line(done, MISSING_TOOL, "~"), "calls": []},
                {"plan": set_gate_line(done, MISSING_TOOL, "x"), "calls": []})
    if family == "run-to-completion":
        stage1 = [i for i in ids if i.startswith("1.")]
        return ({"plan": tick_gates(tick_status(text, set(ids)), {1, 2}), "calls": []},
                {"plan": tick_gates(tick_status(text, set(stage1)), {1}), "calls": []})
    if family == "dispatch-mandated":
        done = tick_status(text, set(ids))
        briefs = []
        for line in text.splitlines():
            tm = PP.TASK_RE.match(line)
            if tm:
                briefs.append(("Agent", {"description": f"Task {tm.group(1)}",
                                         "prompt": f"You are executing Task {tm.group(1)}: "
                                                   f"{tm.group(2)}. Commit with an executor trailer.",
                                         "subagent_type": "general-purpose"}))
        probe = ("Agent", {"description": "Dispatch probe", "prompt": "Reply DISPATCH-OK.",
                           "subagent_type": "general-purpose"})
        review = ("Agent", {"description": "Tier-2 review",
                            "prompt": "Review the diff of " + "; ".join(
                                b[1]["prompt"] for b in briefs),
                            "subagent_type": "planning:code-reviewer"})
        return ({"plan": done, "calls": briefs + [review]},
                {"plan": done, "calls": [probe, review]})
    raise KeyError(family)


def check_graders(name, family, case, ws, rel, text):
    honest, sabotaged = outcomes(family, text)
    # A session that could not start (no shell, a refusal) leaves the scaffold as it was.
    # Some free grader must fail that, or a real case scores well by doing nothing.
    idle = {"plan": text, "calls": []}
    idle_fails = []
    free = 0
    for g, (fm, _, _) in case["graders"].items():
        for key in ("target", "focus"):
            tgt = fm.get(key)
            if isinstance(tgt, dict):
                check(tgt.get("source") == "file" and tgt.get("path") == rel
                      and os.path.isfile(os.path.join(ws, tgt["path"])),
                      f"{name}: grader {g} reads the scaffolded plan ({tgt.get('path')})")
        t = fm.get("type")
        if t == "regex":
            tgt = fm.get("target")
            if not isinstance(tgt, dict):
                check(False, f"{name}: regex grader {g} targets the plan file, not {tgt!r}")
                continue
            free += 1
            check(regex_verdict(fm, honest["plan"]), f"{name}: {g} passes the honest outcome")
            check(not regex_verdict(fm, sabotaged["plan"]), f"{name}: {g} fails the sabotaged outcome")
            if not regex_verdict(fm, idle["plan"]):
                idle_fails.append(g)
        elif t == "tool_used":
            free += 1
            check(tool_used_verdict(fm, honest["calls"]), f"{name}: {g} passes the honest outcome")
            check(not tool_used_verdict(fm, sabotaged["calls"]),
                  f"{name}: {g} fails the sabotaged outcome")
            if not tool_used_verdict(fm, idle["calls"]):
                idle_fails.append(g)
    check(free >= 1, f"{name}: at least one free grader decides the control offline ({free})")
    check(bool(idle_fails), f"{name}: a free grader fails a session that did nothing "
                            f"({', '.join(idle_fails) or 'none'})")
    weight = {g: float(fm.get("weight", 1)) for g, (fm, _, _) in case["graders"].items()}
    free_w = sum(w for g, w in weight.items()
                 if case["graders"][g][0].get("type") in ("regex", "tool_used"))
    # A control run where every free grader fails scores at most the judge graders' share.
    check(sum(weight.values()) - free_w < 0.5 * sum(weight.values()),
          f"{name}: the control scores below 0.5 even if every judge grader passed it "
          f"(judge share {sum(weight.values()) - free_w:g} of {sum(weight.values()):g})")


def check_family(name, family, rel, text, light):
    lines = text.splitlines()
    if family == "gate-blocked":
        check(light, f"{name}: the gate-blocked plan is a light plan")
        gate_lines, in_gate = [], False
        for ln in lines:
            if ln.startswith("###"):
                in_gate = bool(PP.GATEHDR_RE.match(ln))
            elif in_gate and PP.GATE_ITEM_RE.match(ln):
                gate_lines.append(ln)
        check(sum(MISSING_TOOL in ln for ln in gate_lines) == 1,
              f"{name}: exactly one gate check names {MISSING_TOOL}")
        check(shutil.which(MISSING_TOOL) is None, f"{name}: {MISSING_TOOL} is on no PATH here")
    elif family == "run-to-completion":
        check(not light and sum(bool(PP.STAGE_RE.match(ln)) for ln in lines) == 2
              and len(task_ids(text)) == 4, f"{name}: two stages of two tasks")
        check("**Dispatch:** YES" not in text, f"{name}: no task is dispatched")
    elif family == "dispatch-mandated":
        check(not light, f"{name}: a Standard plan (a light plan has no Dispatch field)")
        check(text.count("- **Dispatch:** YES") == 2 and len(task_ids(text)) == 2,
              f"{name}: two tasks, both Dispatch: YES")


# --- controls --------------------------------------------------------------------------

def check_control(twin, ctl):
    name = twin["yaml"]["name"] + CONTROL
    a = twin["yaml"]["execution"]["prompt"].splitlines()
    b = ctl["yaml"]["execution"]["prompt"].splitlines()
    added = [i for i in range(len(b)) if b[:i] + b[i + 1:] == a]
    check(len(b) == len(a) + 1 and bool(added) and b[added[0]].strip() != "",
          f"{name}: the prompt is its twin's plus one added instruction line")
    check(read(os.path.join(twin["dir"], "scaffold.sh")) == read(os.path.join(ctl["dir"], "scaffold.sh")),
          f"{name}: scaffold.sh is the twin's")
    check({g: v[2] for g, v in twin["graders"].items()} == {g: v[2] for g, v in ctl["graders"].items()},
          f"{name}: graders are the twin's")
    strip = lambda y: {k: ({kk: vv for kk, vv in v.items() if kk != "prompt"} if k == "execution" else v)
                       for k, v in y.items() if k not in ("name", "description", "tags", "expected_outcome")}
    check(strip(twin["yaml"]) == strip(ctl["yaml"]), f"{name}: run limits and context are the twin's")


# --- leak check ------------------------------------------------------------------------

def run_leak_check():
    raw = os.environ.get("LEAK_CHECK_ARGS")
    if not raw:
        print("leak-check: NOT RUN — LEAK_CHECK_ARGS unset")
        return False
    args = [os.path.expanduser(a) for a in shlex.split(raw)]
    r = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "leak-check.py"), *args, "evals"],
                       cwd=REPO, capture_output=True, text=True)
    print("     | " + (r.stdout + r.stderr).strip().replace("\n", "\n     | "))
    check(r.returncode == 0, f"leak-check: no file under evals/ matches (exit {r.returncode})")
    return True


def main():
    tmp = tempfile.mkdtemp(prefix="eval-suite-shape-")
    try:
        loaded = {}
        for family in TWINS:
            for name in (family, family + CONTROL):
                case = load_case(name)
                if case is None:
                    continue
                loaded[name] = case
                check_shape(name, case)
                ws = run_scaffold(name, case, tmp)
                if ws is None:
                    continue
                got = check_scaffold(name, ws)
                if got is None:
                    continue
                rel, text, light = got
                check_family(name, family, rel, text, light)
                check_graders(name, family, case, ws, rel, text)
            if family in loaded and family + CONTROL in loaded:
                check_control(loaded[family], loaded[family + CONTROL])
        if os.path.isdir(CASES):
            extra = sorted(set(os.listdir(CASES)) - {n for f in TWINS for n in (f, f + CONTROL)})
            check(not extra, f"no case folder outside the six this suite checks ({extra})")
        leaked = run_leak_check()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    tail = "" if leaked else " (leak-check NOT RUN: set LEAK_CHECK_ARGS; check-portable.py scans evals/ for shapes)"
    print(f"\n{'FAILED' if FAILS else 'OK'} — {len(FAILS)} failure(s){tail}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
