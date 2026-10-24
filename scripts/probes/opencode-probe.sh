#!/usr/bin/env bash
# Measures how OpenCode loads a host package, in throwaway HOMEs. Five cases:
#
#   a  skills      a skill dir named in the global config's `skills` array
#                  (<home>/sp/skills/sp-probe).
#   b  plugin-dir  a plugin file dropped in the global plugin dir
#                  (<home>/.config/opencode/plugins/sp-probe.ts), no config entry. Its
#                  `config` hook adds the subagent sp-probe-agent and the command
#                  sp-probe-cmd.
#   c  plugin-path the same plugin named by its local path in the config's `plugin` array.
#   d  co-visible  skills OpenCode may read from other tools' roots. Each root gets a skill
#                  of its own name (sp-vis-<root>) to show whether the root is read, and a
#                  copy of the same-named skill sp-shadow that answers with its own token
#                  to show which copy is served.
#   e  external    a skill that must read <home>/outside/token.txt from a workspace
#                  elsewhere. Run twice: e-default with default permissions, and
#                  e-allow with permission.external_directory allowing <home>/outside/**.
#
# What decides each result. Exit codes are logged and never trusted: a non-interactive
# `opencode run` can refuse a tool call and still exit 0.
#   - Listing: `opencode debug skill`, `opencode debug config` and `opencode agent list`,
#     which need no model call. They go to config.txt.
#   - Served: the token the probe file carries appears in that run's output.
#   - External directory: `allowed` only when the sentinel token from token.txt appears in
#     that run's output. The token is random per run and written nowhere but token.txt;
#     the run file carries only its sha256, so the token cannot reach the output by any
#     route but a read of the file. After the runs, the recorded verdicts are re-derived
#     from the run files and a mismatch exits 1.
#
# Every model prompt names its skill, agent or command: a host may not pick a skill from
# a natural-language request.
#
# Isolation. One throwaway HOME per case under mktemp. Only the --credentials file is
# copied into it (<home>/.local/share/opencode/auth.json, mode 600) and the copy is
# shredded on exit, then the HOME is removed. Each session runs under env -i with only
# PATH and HOME, from a git workspace inside the throwaway HOME, made with an empty
# template and no hooks. The --credentials file is only read. Evidence paths show the
# throwaway HOME as $HOME.
#
# Usage:
#   opencode-probe.sh --credentials <auth.json> --model <provider/model> --evidence <dir>
#                     [--case a|b|c|d|e]...
#       Runs the named cases (all five by default). Writes version.txt, config.txt and
#       run-<case>.txt to <dir>, prints the measured results as YAML on stdout, then
#       cross-checks them against the run files.
#   opencode-probe.sh --verify <host.yaml> --evidence <dir>
#       No model call. Re-derives the external-directory verdicts from run-e-*.txt and
#       exits 1 when host.yaml records one that the sentinel evidence does not show.
#
# Exit: 0 measured and consistent, 1 a recorded or derived verdict contradicts the
# evidence, 2 usage or harness error.
set -u

usage() { sed -n '2,/^set -u$/{/^set -u$/d;s/^# \{0,1\}//;p}' "$0"; }
die() { echo "opencode-probe: $*" >&2; exit 2; }

CREDS="" MODEL="" EVIDENCE="" VERIFY="" CASES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --credentials) CREDS="${2:-}"; shift 2 ;;
    --model) MODEL="${2:-}"; shift 2 ;;
    --evidence) EVIDENCE="${2:-}"; shift 2 ;;
    --verify) VERIFY="${2:-}"; shift 2 ;;
    --case) CASES+=("${2:-}"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[ -n "$EVIDENCE" ] || die "--evidence is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"

# --- the sentinel cross-check -------------------------------------------------------
# Prints `<case> allowed|rejected` for each run-e-*.txt: allowed only when a token of the
# sentinel's shape appears in the run's output and its sha256 equals the one the run
# file's header recorded.
derive_external() {
  python3 -I - "$1" <<'PY'
import glob, hashlib, os, re, sys
ev = sys.argv[1]
for path in sorted(glob.glob(os.path.join(ev, "run-e-*.txt"))):
    case = os.path.basename(path)[len("run-"):-len(".txt")]
    text = open(path, encoding="utf-8", errors="replace").read()
    head, sep, body = text.partition("\n--- output ---\n")
    m = re.search(r"^sentinel_sha256: ([0-9a-f]{64})$", head, re.M)
    if not sep or not m:
        print(f"{case} malformed")
        continue
    hit = any(hashlib.sha256(t.encode()).hexdigest() == m.group(1)
              for t in set(re.findall(r"SP-SENTINEL-[0-9a-f]{32}", body)))
    print(f"{case} {'allowed' if hit else 'rejected'}")
PY
}

verify_recorded() {  # <host.yaml> <evidence>
  local derived; derived="$(derive_external "$2")"
  python3 -I - "$1" "$derived" <<'PY'
import sys
import yaml
rec = (yaml.safe_load(open(sys.argv[1])) or {}).get("external_directory") or {}
got = dict(line.split(" ", 1) for line in sys.argv[2].splitlines() if line.strip())
key = {"default": "e-default", "with_permission": "e-allow"}
bad = 0
for k, case in key.items():
    want = rec.get(k)
    have = got.get(case)
    if have is None or have == "malformed":
        print(f"MISMATCH external_directory.{k}: no usable run-{case}.txt evidence")
        bad = 1
    elif want != have:
        print(f"MISMATCH external_directory.{k}: recorded {want!r}, sentinel evidence shows {have!r}")
        bad = 1
    else:
        print(f"ok external_directory.{k}: {have} (sentinel evidence in run-{case}.txt)")
sys.exit(bad)
PY
}

if [ -n "$VERIFY" ]; then
  [ -f "$VERIFY" ] || die "no such file: $VERIFY"
  verify_recorded "$VERIFY" "$EVIDENCE"
  exit $?
fi

[ -n "$CREDS" ] && [ -s "$CREDS" ] || die "--credentials must name a non-empty file"
[ -n "$MODEL" ] || die "--model is required (provider/model)"
command -v opencode >/dev/null 2>&1 || die "opencode is not on PATH"
[ ${#CASES[@]} -gt 0 ] || CASES=(a b c d e)
for c in "${CASES[@]}"; do case "$c" in a|b|c|d|e) ;; *) die "unknown case: $c" ;; esac; done
mkdir -p "$EVIDENCE" || die "cannot create $EVIDENCE"
EVIDENCE="$(cd "$EVIDENCE" && pwd)"

HOMES=()
cleanup() {
  local h
  for h in "${HOMES[@]}"; do
    local cred="$h/.local/share/opencode/auth.json"
    if [ -f "$cred" ]; then shred -u "$cred" 2>/dev/null || rm -f "$cred"; fi
    rm -rf "$h"
  done
}
trap cleanup EXIT
trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM

new_home() {  # sets T: a throwaway HOME with only the login, and a git workspace
  T="$(mktemp -d)" || die "mktemp failed"
  HOMES+=("$T")
  mkdir -p "$T/.local/share/opencode" "$T/.config/opencode" "$T/work"
  ( umask 077; cp "$CREDS" "$T/.local/share/opencode/auth.json" ) || die "cannot copy credentials"
  chmod 600 "$T/.local/share/opencode/auth.json"
  git init -q --template= "$T/work" || die "git init failed"
  printf 'probe workspace\n' > "$T/work/README.md"
  git -C "$T/work" -c core.hooksPath=/dev/null add README.md
  git -C "$T/work" -c core.hooksPath=/dev/null -c user.name=probe \
    -c user.email=probe@example.invalid -c commit.gpgsign=false commit -q -m init \
    || die "git commit failed"
}

oc() {  # opencode under a clean env, in the workspace; output with the HOME masked
  ( cd "$T/work" && env -i PATH="$PATH" HOME="$T" timeout --kill-after=10 600 opencode "$@" ) 2>&1
}

mask() { sed "s#$T#\$HOME#g"; }

write_skill() {  # <dir> <name> <body>
  mkdir -p "$1/$2"
  printf -- '---\nname: %s\ndescription: Probe skill %s. Use only when a prompt names %s.\n---\n\n%s\n' \
    "$2" "$2" "$2" "$3" > "$1/$2/SKILL.md"
}

write_plugin() {  # <file> <case letter>
  local up; up="$(printf '%s' "$2" | tr a-z A-Z)"
  mkdir -p "$(dirname "$1")"
  cat > "$1" <<EOF
export const SpProbe = async () => ({
  config: async (cfg: any) => {
    cfg.agent = cfg.agent || {};
    cfg.agent["sp-probe-agent"] = {
      mode: "subagent",
      description: "Probe subagent. Use only when a prompt names sp-probe-agent.",
      prompt: "Whatever you are asked, reply with exactly: SP-AGENT-OK-$up",
    };
    cfg.command = cfg.command || {};
    cfg.command["sp-probe-cmd"] = {
      description: "Probe command",
      template: "Reply with exactly: SP-CMD-OK-$up",
    };
  },
});
EOF
}

listings() {  # <case>: the model-free listings, appended to config.txt
  {
    echo "===== case $1 ====="
    echo "--- opencode.json ---"; mask < "$T/.config/opencode/opencode.json"; echo
    echo "--- opencode debug config ---"; oc debug config | mask
    echo "--- opencode debug skill (name<TAB>location) ---"
    oc debug skill | python3 -I -c '
import json, sys
raw = sys.stdin.read()
try:
    for s in json.loads(raw[raw.index("["):]):
        print(s.get("name"), s.get("location"), sep="\t")
except Exception as e:
    print("unparsed:", e); print(raw)' | mask
    echo "--- opencode agent list (names) ---"; oc agent list | grep -E '^[A-Za-z0-9_-]+ \(' | mask
    echo
  } >> "$EVIDENCE/config.txt"
}

run_case() {  # <run id> <prompt> [extra opencode run args...]; run-<id>.txt, exit in RUN_RC
  local id="$1" prompt="$2"; shift 2
  local out="$EVIDENCE/run-$id.txt" raw rc
  raw="$(oc run -m "$MODEL" --format json "$@" ${prompt:+"$prompt"})"; rc=$?
  RUN_RC=$rc
  {
    echo "case: $id"
    echo "model: $MODEL"
    echo "args: $*"
    echo "prompt: $prompt"
    echo "exit: $rc (logged, not trusted)"
    [ -n "${SENTINEL_SHA:-}" ] && echo "sentinel_sha256: $SENTINEL_SHA"
    echo "--- output ---"
    printf '%s\n' "$raw" | mask
  } > "$out"
}

has() { grep -qF -- "$2" "$EVIDENCE/run-$1.txt"; }
section() { sed -n "/^===== case $1 =====\$/,/^===== case /p" "$EVIDENCE/config.txt"; }
listed() { section "$1" | awk -F'\t' -v n="$2" '$1==n{f=1} END{exit !f}'; }
cfg_has() { section "$1" | grep -qF -- "$2"; }

VH="$(mktemp -d)" || die "mktemp failed"; HOMES+=("$VH")   # --version gets a throwaway HOME too
env -i PATH="$PATH" HOME="$VH" opencode --version > "$EVIDENCE/version.txt" 2>&1 \
  || die "opencode --version failed"
{ echo "probe_date: $(date +%F)"; echo "model: $MODEL"; } >> "$EVIDENCE/version.txt"
: > "$EVIDENCE/config.txt"
declare -A R=()

for c in "${CASES[@]}"; do
  SENTINEL_SHA=""
  case "$c" in
  a)
    new_home
    write_skill "$T/sp/skills" sp-probe "Reply with exactly: SP-SKILL-OK-A"
    printf '{"$schema":"https://opencode.ai/config.json","skills":["%s/sp/skills"]}\n' "$T" \
      > "$T/.config/opencode/opencode.json"
    listings a
    run_case a "Use the skill tool to load the skill named sp-probe, then do exactly what it says."
    R[skills_listed]=$(listed a sp-probe && echo true || echo false)
    R[skills_served]=$(has a SP-SKILL-OK-A && echo true || echo false)
    ;;
  b|c)
    new_home
    up="$(printf '%s' "$c" | tr a-z A-Z)"
    if [ "$c" = b ]; then
      write_plugin "$T/.config/opencode/plugins/sp-probe.ts" b
      printf '{"$schema":"https://opencode.ai/config.json"}\n' > "$T/.config/opencode/opencode.json"
    else
      write_plugin "$T/sp/plugin/index.ts" c
      printf '{"$schema":"https://opencode.ai/config.json","plugin":["%s/sp/plugin/index.ts"]}\n' "$T" \
        > "$T/.config/opencode/opencode.json"
    fi
    listings "$c"
    { echo "--- opencode debug agent sp-probe-agent ---"; oc debug agent sp-probe-agent | head -40 | mask; echo; } \
      >> "$EVIDENCE/config.txt"
    run_case "$c-cmd" "" --command sp-probe-cmd
    run_case "$c-agent" "Use the task tool to run the subagent named sp-probe-agent with the prompt 'go', then reply with exactly what it returned."
    R[${c}_injected]=$(cfg_has "$c" '"sp-probe-agent"' && cfg_has "$c" '"sp-probe-cmd"' && echo true || echo false)
    R[${c}_cmd_served]=$(has "$c-cmd" "SP-CMD-OK-$up" && echo true || echo false)
    R[${c}_agent_served]=$(has "$c-agent" "SP-AGENT-OK-$up" && echo true || echo false)
    ;;
  d)
    new_home
    declare -A ROOT=(
      [opencode]="$T/.config/opencode/skills"
      [claude]="$T/.claude/skills"
      [agents]="$T/.agents/skills"
      [claudecache]="$T/.claude/plugins/cache/sp-mkt/sp-shadow/0.0.1/skills"
    )
    for r in "${!ROOT[@]}"; do
      write_skill "${ROOT[$r]}" "sp-vis-$r" "Reply with exactly: SP-VIS-$r-OK"
      write_skill "${ROOT[$r]}" sp-shadow "Reply with exactly: SP-SHADOW-$r-OK"
    done
    printf '{"$schema":"https://opencode.ai/config.json"}\n' > "$T/.config/opencode/opencode.json"
    listings d
    run_case d "First list the name of every skill available to you whose name starts with sp-. Then use the skill tool to load the skill named sp-shadow and reply with exactly what it says."
    for r in opencode claude agents claudecache; do
      R[vis_$r]=$(listed d "sp-vis-$r" && echo true || echo false)
      R[shadow_listed_$r]=$(section d | awk -F'\t' -v loc="\$HOME${ROOT[$r]#"$T"}/sp-shadow/SKILL.md" \
        '$1=="sp-shadow" && $2==loc{f=1} END{exit !f}' && echo true || echo false)
      R[shadow_served_$r]=$(has d "SP-SHADOW-$r-OK" && echo true || echo false)
    done
    ;;
  e)
    for mode in default allow; do
      new_home
      mkdir -p "$T/outside"
      tok="SP-SENTINEL-$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
      printf '%s\n' "$tok" > "$T/outside/token.txt"
      SENTINEL_SHA="$(printf '%s' "$tok" | sha256sum | cut -d' ' -f1)"
      write_skill "$T/sp/skills" sp-outside \
        "Read the file $T/outside/token.txt with the read tool and reply with its exact contents. If you cannot read it, say why."
      if [ "$mode" = default ]; then
        printf '{"$schema":"https://opencode.ai/config.json","skills":["%s/sp/skills"]}\n' "$T" \
          > "$T/.config/opencode/opencode.json"
      else
        printf '{"$schema":"https://opencode.ai/config.json","skills":["%s/sp/skills"],"permission":{"external_directory":{"%s/outside/**":"allow"}}}\n' \
          "$T" "$T" > "$T/.config/opencode/opencode.json"
      fi
      listings "e-$mode"
      run_case "e-$mode" "Use the skill tool to load the skill named sp-outside, then do exactly what it says."
      R[ext_$mode]=$(grep -qF -- "$tok" "$EVIDENCE/run-e-$mode.txt" && echo allowed || echo rejected)
      R[ext_${mode}_exit]=$RUN_RC
      unset tok
    done
    ;;
  esac
done

# --- results, as YAML --------------------------------------------------------------
v() { printf '%s' "${R[$1]:-unmeasured}"; }
echo "# measured by scripts/probes/opencode-probe.sh, opencode $(head -1 "$EVIDENCE/version.txt"), $(date +%F)"
echo "skills_config_path: {listed: $(v skills_listed), served: $(v skills_served)}"
for c in b c; do
  echo "plugin_case_$c: {config_hook_injected: $(v ${c}_injected), command_served: $(v ${c}_cmd_served), agent_served: $(v ${c}_agent_served)}"
done
echo "co_visible:"
for r in opencode claude agents claudecache; do
  echo "  $r: {own_name_listed: $(v vis_$r), shadow_listed: $(v shadow_listed_$r), shadow_served: $(v shadow_served_$r)}"
done
echo "external_directory: {default: $(v ext_default), with_permission: $(v ext_allow)}"
echo "external_directory_exit_codes: {default: $(v ext_default_exit), with_permission: $(v ext_allow_exit)}"

# --- cross-check: the verdicts above must be what the sentinel evidence shows ---------
status=0
if [ -n "${R[ext_default]:-}" ] || [ -n "${R[ext_allow]:-}" ]; then
  derived="$(derive_external "$EVIDENCE")"
  for pair in "default e-default" "allow e-allow"; do
    set -- $pair
    [ -n "${R[ext_$1]:-}" ] || continue
    have="$(printf '%s\n' "$derived" | awk -v c="$2" '$1==c{print $2}')"
    if [ "$have" != "${R[ext_$1]}" ]; then
      echo "MISMATCH external_directory $1: derived ${R[ext_$1]}, sentinel evidence shows ${have:-nothing}" >&2
      status=1
    fi
  done
fi
exit $status
