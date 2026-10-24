#!/usr/bin/env bash
# Probe what the Cursor CLI (cursor-agent) actually does with hooks and same-named skills.
# The vendor docs do not settle this, so the Cursor host layer is designed from what
# this measures, not from the docs. Each case runs in its own throwaway HOME and toy
# git repo; the only thing copied in is the login file (mode 600, shredded on exit).
#
# Cases (each runs cursor-agent once, except shadow, which runs it twice). All but
# interactive run headless (`cursor-agent -p`), where the server never asks the client to
# run stop, subagentStart or subagentStop; interactive measures a real TUI session:
#   plugin  a local plugin sp-probe whose hooks/hooks.json registers stop, preToolUse
#           (matcher Task), subagentStart, subagentStop and beforeShellExecution
#   user    the same five events in the throwaway ~/.cursor/hooks.json
#   both    both routes at once: lines per event show whether one event fires twice
#   claude  a Claude Code plugin with Stop and PreToolUse loggers, installed from a local
#           marketplace into the throwaway ~/.claude with the claude CLI (route
#           claude-plugin), plus the same two events in the throwaway
#           ~/.claude/settings.json (route claude-settings), which is the source the
#           vendor docs name for Claude hooks
#   shadow  a skill sp-shadow in four roots: a Cursor local plugin, the Claude plugin
#           cache (a real install of a plugin sp-shadow from marketplace sp-mkt),
#           ~/.claude/skills and ~/.agents/skills. Each copy answers with its own token.
#           Run 1 invokes /sp-shadow; run 2 asks for a listing of every sp-shadow skill.
#   interactive  both routes, as in case both, plus afterAgentResponse, in a TUI session:
#           `cursor-agent --trust --force` (no -p) inside tmux on a private socket. The
#           prompt is typed into the pane; the case ends when the bottom of the pane
#           shows no Working/Running status line and the pane has not changed for QUIET
#           seconds (or at --timeout).
#           The pane, history included, is saved as transcript-interactive.txt.
#           The plugin route also gets path-form hooks that log their working directory,
#           $0 and the CURSOR_*/CLAUDE_* environment (names that hold an email, token,
#           key, secret or auth are left out) with stdin: stop three times, as
#           ./hooks/rel-stop.sh (route plugin-rel), $CURSOR_PLUGIN_ROOT/hooks/env-stop.sh
#           (plugin-env) and "${CURSOR_PLUGIN_ROOT}/hooks/envq-stop.sh" (plugin-envq), and
#           preToolUse(Task) as ./hooks/rel-preToolUse.sh (plugin-rel). The toy repo holds
#           decoys at the same relative paths (route workspace-decoy), so a relative
#           command resolved against the workspace root shows up as a decoy line. The
#           plugin ships one custom agent, sp-probe-agent, and this case's own prompt asks
#           for a default subagent, a general-purpose one and sp-probe-agent by name, so
#           the preToolUse lines show what tool_input carries for each.
#
# The headless hook cases use one fixed prompt. Except for the interactive case's
# path-form hooks, every logger command is an absolute path, so a missing line means the
# route did not fire, not that a relative path failed to resolve.
# A logger appends {event, route, stdin} to <evidence>/events-<case>.jsonl and exits 0;
# the Cursor-route loggers for the two permission events print {"permission":"allow"}
# (the docs say invalid output blocks the action), the others print {} (Cursor) or
# nothing (Claude).
#
# Evidence written to --evidence (keep it outside any repo: it holds machine paths):
#   events-<case>.jsonl      one line per hook call
#   transcript-<case>.jsonl  the cursor-agent stream-json output (shadow: -invoke/-list)
#   transcript-interactive.txt  the captured tmux pane of the interactive case
#   shadow.txt               which copy answered /sp-shadow and which copies were listed
#   version.txt              host versions, probe date, per-case exit codes; each run
#                            appends its own block, so a one-case re-run keeps the rest
#
# Usage: cursor-probe.sh --credentials <cursor auth.json> --evidence <dir>
#                        [--cases plugin,user,both,claude,shadow,interactive]
#                        [--timeout <seconds>]
set -euo pipefail

CREDS="" EVID="" CASES="plugin,user,both,claude,shadow,interactive" TMO=600 QUIET=8
while [ $# -gt 0 ]; do
  case "$1" in
    --credentials) CREDS="$2"; shift 2 ;;
    --evidence) EVID="$2"; shift 2 ;;
    --cases) CASES="$2"; shift 2 ;;
    --timeout) TMO="$2"; shift 2 ;;
    -h|--help) sed -n '2,58p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$CREDS" ] && [ -f "$CREDS" ] || { echo "--credentials <file> is required" >&2; exit 2; }
[ -n "$EVID" ] || { echo "--evidence <dir> is required" >&2; exit 2; }
for t in cursor-agent jq git shred; do
  command -v "$t" >/dev/null || { echo "missing tool: $t" >&2; exit 2; }
done
case ",$CASES," in *,claude,*|*,shadow,*|*,interactive,*)
  command -v claude >/dev/null || { echo "missing tool: claude (cases claude/shadow/interactive)" >&2; exit 2; } ;;
esac
case ",$CASES," in *,interactive,*)
  command -v tmux >/dev/null || { echo "missing tool: tmux (case interactive)" >&2; exit 2; } ;;
esac

mkdir -p "$EVID"
EVID=$(cd "$EVID" && pwd)
JQ=$(command -v jq)
ROOT=$(mktemp -d "${TMPDIR:-/tmp}/cursor-probe.XXXXXX")

TSOCK="cursor-probe-$$-${RANDOM}"   # the interactive case's private tmux server
TMUX_UP=0

cleanup() {
  [ "$TMUX_UP" = 1 ] && env -u TMUX tmux -L "$TSOCK" kill-server 2>/dev/null
  rm -f "${TMUX_TMPDIR:-/tmp}/tmux-$(id -u)/$TSOCK" 2>/dev/null
  find "$ROOT" -path '*/.config/cursor/auth.json' -type f -exec shred -u {} + 2>/dev/null || true
  # A session that just ended can still hold files under .cache for a moment.
  local i
  for i in 1 2 3 4 5; do
    rm -rf "$ROOT" 2>/dev/null && break
    sleep 1
  done
  [ -e "$ROOT" ] && echo "could not remove $ROOT" >&2
  return 0
}
trap cleanup EXIT
# A signal exits, so EXIT runs cleanup once and no later case starts with fresh credentials.
trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM

PROMPT='Use a subagent to list the files here, then run `ls` in the shell, then stop'
IPROMPT='In order: use a subagent to list the files here; use a general-purpose subagent to read README.md; use the sp-probe-agent subagent to count the .txt files; run `ls` in the shell; stop'
CURSOR_EVENTS="stop preToolUse subagentStart subagentStop beforeShellExecution"

# new_home <case>: a throwaway HOME holding only the login file, and a toy git repo.
new_home() {
  local h="$ROOT/$1/home" toy="$ROOT/$1/toy"
  mkdir -p "$h/.config/cursor" "$toy" "$ROOT/$1/bin"
  install -m 600 "$CREDS" "$h/.config/cursor/auth.json"
  git init -q --template= "$toy"
  printf 'probe toy repo\n' > "$toy/README.md"
  printf 'alpha\n' > "$toy/alpha.txt"
  printf 'beta\n' > "$toy/beta.txt"
  git -C "$toy" -c core.hooksPath=/dev/null -c user.name=probe -c user.email=probe@example.com \
    add -A
  git -C "$toy" -c core.hooksPath=/dev/null -c user.name=probe -c user.email=probe@example.com \
    commit -q -m 'toy'
}

# logger <case> <route> <event> <style>: write a logger script and print its path.
# style: allow (print {"permission":"allow"}), empty (print {}), none (print nothing).
logger() {
  local c="$1" r="$2" e="$3" style="$4" f="$ROOT/$1/bin/$2-$3.sh" out=""
  case "$style" in allow) out='{"permission":"allow"}' ;; empty) out='{}' ;; esac
  cat > "$f" <<EOF
#!/usr/bin/env bash
in=\$(cat)
if printf '%s' "\$in" | "$JQ" -e . >/dev/null 2>&1; then
  printf '%s' "\$in" | "$JQ" -c --arg e '$e' --arg r '$r' '{event:\$e,route:\$r,stdin:.}' >> '$EVID/events-$c.jsonl'
else
  "$JQ" -nc --arg e '$e' --arg r '$r' --arg s "\$in" '{event:\$e,route:\$r,stdin:\$s}' >> '$EVID/events-$c.jsonl'
fi
[ -n '$out' ] && printf '%s\n' '$out'
exit 0
EOF
  chmod 755 "$f"
  printf '%s' "$f"
}

# path_logger <case> <route> <event> <style> <file>: a logger at <file> that also records
# its working directory, $0 and the CURSOR_*/CLAUDE_* environment (no email, token, key,
# secret or auth names), so a hook reached by a relative or variable path shows where it ran.
path_logger() {
  local c="$1" r="$2" e="$3" style="$4" f="$5" out=""
  case "$style" in allow) out='{"permission":"allow"}' ;; empty) out='{}' ;; esac
  mkdir -p "${f%/*}"
  cat > "$f" <<EOF
#!/usr/bin/env bash
in=\$(cat)
envj=\$("$JQ" -nc 'env | with_entries(select((.key|test("^(CURSOR|CLAUDE)_")) and (.key|test("EMAIL|TOKEN|KEY|SECRET|AUTH")|not)))')
if printf '%s' "\$in" | "$JQ" -e . >/dev/null 2>&1; then
  printf '%s' "\$in" | "$JQ" -c --arg e '$e' --arg r '$r' --arg pwd "\$PWD" --arg a0 "\$0" --argjson env "\$envj" \
    '{event:\$e,route:\$r,pwd:\$pwd,argv0:\$a0,env:\$env,stdin:.}' >> '$EVID/events-$c.jsonl'
else
  "$JQ" -nc --arg e '$e' --arg r '$r' --arg pwd "\$PWD" --arg a0 "\$0" --argjson env "\$envj" --arg s "\$in" \
    '{event:\$e,route:\$r,pwd:\$pwd,argv0:\$a0,env:\$env,stdin:\$s}' >> '$EVID/events-$c.jsonl'
fi
[ -n '$out' ] && printf '%s\n' '$out'
exit 0
EOF
  chmod 755 "$f"
}

# path_hooks <case> <plugin dir>: add the path-form stop and preToolUse(Task) hooks to the
# plugin's hooks.json, their scripts under the plugin's hooks/, the decoys in the toy repo,
# and the custom agent sp-probe-agent.
path_hooks() {
  local c="$1" d="$2" toy="$ROOT/$1/toy" hj="$2/hooks/hooks.json"
  path_logger "$c" plugin-rel stop empty "$d/hooks/rel-stop.sh"
  path_logger "$c" plugin-env stop empty "$d/hooks/env-stop.sh"
  path_logger "$c" plugin-envq stop empty "$d/hooks/envq-stop.sh"
  path_logger "$c" plugin-rel preToolUse allow "$d/hooks/rel-preToolUse.sh"
  path_logger "$c" workspace-decoy stop empty "$toy/hooks/rel-stop.sh"
  path_logger "$c" workspace-decoy preToolUse allow "$toy/hooks/rel-preToolUse.sh"
  "$JQ" '.hooks.stop += [
      {type:"command",command:"./hooks/rel-stop.sh",timeout:10},
      {type:"command",command:"$CURSOR_PLUGIN_ROOT/hooks/env-stop.sh",timeout:10},
      {type:"command",command:"\"${CURSOR_PLUGIN_ROOT}/hooks/envq-stop.sh\"",timeout:10}]
    | .hooks.preToolUse += [
      {type:"command",command:"./hooks/rel-preToolUse.sh",matcher:"Task",timeout:10}]' \
    "$hj" > "$hj.new" && mv "$hj.new" "$hj"
  mkdir -p "$d/agents"
  cat > "$d/agents/sp-probe-agent.md" <<'EOF'
---
name: sp-probe-agent
description: Probe agent sp-probe-agent. Use it only when the user asks for sp-probe-agent by name. It counts what it is asked to count.
model: inherit
readonly: true
---
Count what you are asked to count. Reply with the number and the token SP-PROBE-AGENT.
EOF
}

# cursor_hooks_json <case> <route> [extra events]: the five events, plus any extra ones,
# in Cursor's hooks.json format.
cursor_hooks_json() {
  local c="$1" r="$2" e style p json='{"version":1,"hooks":{}}'
  for e in $CURSOR_EVENTS ${3:-}; do
    case "$e" in preToolUse|beforeShellExecution) style=allow ;; *) style=empty ;; esac
    p=$(logger "$c" "$r" "$e" "$style")
    if [ "$e" = preToolUse ]; then
      json=$(printf '%s' "$json" | "$JQ" -c --arg e "$e" --arg p "$p" \
        '.hooks[$e]=[{type:"command",command:$p,matcher:"Task",timeout:10}]')
    else
      json=$(printf '%s' "$json" | "$JQ" -c --arg e "$e" --arg p "$p" \
        '.hooks[$e]=[{type:"command",command:$p,timeout:10}]')
    fi
  done
  printf '%s' "$json" | "$JQ" .
}

cursor_plugin() {  # <home> <name>: an empty Cursor local plugin, path printed
  local d="$1/.cursor/plugins/local/$2"
  mkdir -p "$d/.cursor-plugin"
  "$JQ" -n --arg n "$2" '{name:$n,version:"0.0.1",description:"probe plugin"}' \
    > "$d/.cursor-plugin/plugin.json"
  printf '%s' "$d"
}

run_agent() {  # <case> <label> <prompt>: one cursor-agent turn in the case's toy repo
  local c="$1" label="$2" rc=0
  ( cd "$ROOT/$c/toy" && env -i PATH="$PATH" HOME="$ROOT/$c/home" \
      timeout "$TMO" cursor-agent -p --trust --force --output-format stream-json "$3" ) \
    > "$EVID/transcript-$label.jsonl" 2> "$ROOT/$c/stderr-$label.txt" || rc=$?
  echo "case $label: cursor-agent exit $rc" >> "$EVID/version.txt"
  if [ "$rc" -ne 0 ]; then sed 's/^/  stderr: /' "$ROOT/$c/stderr-$label.txt" | head -20 >> "$EVID/version.txt"; fi
}

tmx() { env -u TMUX tmux -L "$TSOCK" "$@"; }

# BUSY_RE: the TUI's busy status line: Working or Running at the start of a line, after
# at most a spinner glyph. Anchored, so a reply that says "Running ls next" is not busy.
BUSY_RE='^[[:space:]]*([^[:alnum:][:space:]]+[[:space:]]*)?(Working|Running)'

# wait_quiet <seconds> <min>: return once the pane's last ten non-blank lines (where the
# TUI shows its busy status) hold no busy status line, the pane has not changed for
# <seconds>, and at least <min> seconds have passed; 1 at --timeout.
wait_quiet() {
  local need="$1" min="$2" start now last="" cur still=0
  start=$(date +%s)
  while :; do
    now=$(date +%s)
    [ $((now - start)) -ge "$TMO" ] && return 1
    cur=$(tmx capture-pane -p -t probe 2>/dev/null) || return 1
    if [ "$cur" = "$last" ] && ! printf '%s\n' "$cur" | grep -v '^[[:space:]]*$' | tail -n 10 |
        grep -Eq "$BUSY_RE"; then
      still=$((still + 1))
    else
      still=0
    fi
    last="$cur"
    [ "$still" -ge "$need" ] && [ $((now - start)) -ge "$min" ] && return 0
    sleep 1
  done
}

run_interactive() {  # <case> <prompt>: one TUI turn of <prompt> in tmux, the pane saved
  local c="$1" prompt="$2" w=quiet
  tmx -f /dev/null new-session -d -s probe -x 260 -y 60 -c "$ROOT/$c/toy" \
    env -i PATH="$PATH" HOME="$ROOT/$c/home" TERM=xterm-256color cursor-agent --trust --force
  TMUX_UP=1
  tmx set-option -t probe history-limit 20000 >/dev/null
  # Type only once the TUI has drawn its banner: keys sent earlier reach the terminal
  # before the TUI reads them, and the Enter is lost.
  local i n=0
  for i in $(seq 60); do
    tmx capture-pane -p -t probe 2>/dev/null | grep -q 'Cursor Agent' && break
    sleep 1
  done
  wait_quiet 3 3 || w=timeout-before-prompt
  tmx send-keys -t probe -l "$prompt"
  sleep 2
  # The prompt is submitted when it leaves the prompt bar (the line starting with an
  # arrow); press Enter until it does, at most three times.
  for i in 1 2 3; do
    tmx send-keys -t probe Enter
    n=$i
    sleep 5
    tmx capture-pane -p -t probe 2>/dev/null | grep -qF "→ $prompt" || break
  done
  echo "case $c: Enter pressed $n time(s)" >> "$EVID/version.txt"
  [ "$w" = quiet ] && { wait_quiet "$QUIET" 20 || w=timeout; }
  tmx capture-pane -p -J -S - -t probe > "$EVID/transcript-$c.txt" 2>/dev/null || true
  tmx kill-server 2>/dev/null || true
  TMUX_UP=0
  echo "case $c: tui session ended by $w" >> "$EVID/version.txt"
}

# claude_matcher_plugin <case> <home>: a Claude Code plugin installed from a local marketplace
# into the throwaway ~/.claude, logging Stop and three PreToolUse variants (routes
# claude-plugin, claude-plugin-agent-task, claude-plugin-bash).
claude_matcher_plugin() {
  local c="$1" h="$2" m p s0 p0 pt pb
  m="$ROOT/$c/mkt"; p="$m/sp-claude"
  mkdir -p "$m/.claude-plugin" "$p/.claude-plugin" "$p/hooks"
  "$JQ" -n '{name:"sp-mkt",owner:{name:"probe"},plugins:[{name:"sp-claude",source:"./sp-claude",version:"0.0.1",description:"probe"}]}' \
    > "$m/.claude-plugin/marketplace.json"
  "$JQ" -n '{name:"sp-claude",version:"0.0.1",description:"probe"}' > "$p/.claude-plugin/plugin.json"
  s0=$(logger "$c" claude-plugin Stop none); p0=$(logger "$c" claude-plugin PreToolUse none)
  pt=$(logger "$c" claude-plugin-agent-task PreToolUse none)
  pb=$(logger "$c" claude-plugin-bash PreToolUse none)
  "$JQ" -n --arg s "$s0" --arg p "$p0" --arg t "$pt" --arg b "$pb" \
    '{hooks:{Stop:[{hooks:[{type:"command",command:$s}]}],PreToolUse:[{hooks:[{type:"command",command:$p}]},{matcher:"Agent|Task",hooks:[{type:"command",command:$t}]},{matcher:"Bash",hooks:[{type:"command",command:$b}]}]}}' \
    > "$p/hooks/hooks.json"
  claude_cli "$h" plugin marketplace add "$m" > "$ROOT/$c/claude-install.txt" 2>&1
  claude_cli "$h" plugin install sp-claude@sp-mkt >> "$ROOT/$c/claude-install.txt" 2>&1
  find "$h/.claude/plugins" -path '*/hooks/hooks.json' 2>/dev/null | grep -q . \
    || { echo "claude plugin install left no cached hooks.json" >&2; exit 1; }
}

claude_cli() {  # <home> <args...>: the claude CLI confined to the throwaway HOME
  local h="$1"; shift
  env -i PATH="$PATH" HOME="$h" claude "$@"
}

skill_md() {  # <dir> <token>
  mkdir -p "$1"
  cat > "$1/SKILL.md" <<EOF
---
name: sp-shadow
description: Probe skill sp-shadow. When invoked, reply with this copy's token and nothing else.
---
Reply with exactly this token and nothing else: $2
EOF
}

count_table() {  # <case>: "route event lines" for every logged pair
  local f="$EVID/events-$1.jsonl"
  [ -s "$f" ] || { echo "  (no hook lines)"; return; }
  "$JQ" -r '"\(.route) \(.event)"' "$f" | sort | uniq -c | sed 's/^/  /'
}

{
  echo "== run $(date -u +%FT%TZ) cases=$CASES"
  echo "probe_date: $(date +%F)"
  echo "cursor-agent: $(env -i PATH="$PATH" HOME="$ROOT" cursor-agent --version 2>&1)"
  command -v claude >/dev/null && echo "claude: $(env -i PATH="$PATH" HOME="$ROOT" claude --version 2>&1)"
  echo "prompt: $PROMPT"
  echo "interactive prompt: $IPROMPT"
} >> "$EVID/version.txt"

for c in $(printf '%s' "$CASES" | tr ',' ' '); do
  : > "$EVID/events-$c.jsonl"
  new_home "$c"
  H="$ROOT/$c/home"
  case "$c" in
    plugin)
      d=$(cursor_plugin "$H" sp-probe); mkdir -p "$d/hooks"
      cursor_hooks_json plugin plugin > "$d/hooks/hooks.json"
      run_agent "$c" "$c" "$PROMPT" ;;
    user)
      mkdir -p "$H/.cursor"
      cursor_hooks_json user user > "$H/.cursor/hooks.json"
      run_agent "$c" "$c" "$PROMPT" ;;
    both)
      d=$(cursor_plugin "$H" sp-probe); mkdir -p "$d/hooks"
      cursor_hooks_json both plugin > "$d/hooks/hooks.json"
      cursor_hooks_json both user > "$H/.cursor/hooks.json"
      run_agent "$c" "$c" "$PROMPT" ;;
    claude)
      m="$ROOT/$c/mkt"; p="$m/sp-claude"
      mkdir -p "$m/.claude-plugin" "$p/.claude-plugin" "$p/hooks"
      "$JQ" -n '{name:"sp-mkt",owner:{name:"probe"},plugins:[{name:"sp-claude",source:"./sp-claude",version:"0.0.1",description:"probe"}]}' \
        > "$m/.claude-plugin/marketplace.json"
      "$JQ" -n '{name:"sp-claude",version:"0.0.1",description:"probe"}' > "$p/.claude-plugin/plugin.json"
      ps=$(logger claude claude-plugin Stop none); pp=$(logger claude claude-plugin PreToolUse none)
      "$JQ" -n --arg s "$ps" --arg p "$pp" \
        '{hooks:{Stop:[{hooks:[{type:"command",command:$s}]}],PreToolUse:[{hooks:[{type:"command",command:$p}]}]}}' \
        > "$p/hooks/hooks.json"
      claude_cli "$H" plugin marketplace add "$m" > "$ROOT/$c/claude-install.txt" 2>&1
      claude_cli "$H" plugin install sp-claude@sp-mkt >> "$ROOT/$c/claude-install.txt" 2>&1
      sed 's/^/  claude install: /' "$ROOT/$c/claude-install.txt" >> "$EVID/version.txt"
      cached=$(find "$H/.claude/plugins" -path '*/hooks/hooks.json' 2>/dev/null | head -1)
      [ -n "$cached" ] || { echo "claude plugin install left no cached hooks.json" >&2; exit 1; }
      echo "  claude plugin cached at: ${cached#"$H"/}" >> "$EVID/version.txt"
      ss=$(logger claude claude-settings Stop none); sp=$(logger claude claude-settings PreToolUse none)
      st="$H/.claude/settings.json"
      [ -f "$st" ] || echo '{}' > "$st"
      "$JQ" --arg s "$ss" --arg p "$sp" \
        '.hooks={Stop:[{hooks:[{type:"command",command:$s}]}],PreToolUse:[{hooks:[{type:"command",command:$p}]}]}' \
        "$st" > "$st.new" && mv "$st.new" "$st"
      run_agent "$c" "$c" "$PROMPT" ;;
    shadow)
      m="$ROOT/$c/mkt"; p="$m/sp-shadow"
      mkdir -p "$m/.claude-plugin" "$p/.claude-plugin"
      "$JQ" -n '{name:"sp-mkt",owner:{name:"probe"},plugins:[{name:"sp-shadow",source:"./sp-shadow",version:"0.0.1",description:"probe"}]}' \
        > "$m/.claude-plugin/marketplace.json"
      "$JQ" -n '{name:"sp-shadow",version:"0.0.1",description:"probe"}' > "$p/.claude-plugin/plugin.json"
      skill_md "$p/skills/sp-shadow" SP-SHADOW-CLAUDE-CACHE
      claude_cli "$H" plugin marketplace add "$m" > "$ROOT/$c/claude-install.txt" 2>&1
      claude_cli "$H" plugin install sp-shadow@sp-mkt >> "$ROOT/$c/claude-install.txt" 2>&1
      sed 's/^/  claude install: /' "$ROOT/$c/claude-install.txt" >> "$EVID/version.txt"
      [ -f "$H/.claude/plugins/cache/sp-mkt/sp-shadow/0.0.1/skills/sp-shadow/SKILL.md" ] || {
        echo "claude plugin install did not land at plugins/cache/sp-mkt/sp-shadow/0.0.1" >&2; exit 1; }
      d=$(cursor_plugin "$H" sp-cursor)
      skill_md "$d/skills/sp-shadow" SP-SHADOW-CURSOR-PLUGIN
      skill_md "$H/.claude/skills/sp-shadow" SP-SHADOW-CLAUDE-SKILLS
      skill_md "$H/.agents/skills/sp-shadow" SP-SHADOW-AGENTS-SKILLS
      run_agent "$c" shadow-invoke '/sp-shadow'
      run_agent "$c" shadow-list 'Do not invoke any skill and do not read any files. From the skills you were given, list every skill named sp-shadow, one per line, each with the full path of its SKILL.md exactly as you were given it. If several share the name, list each one.'
      {
        echo "token -> root: SP-SHADOW-CURSOR-PLUGIN=cursor-plugin SP-SHADOW-CLAUDE-CACHE=claude-cache SP-SHADOW-CLAUDE-SKILLS=claude-skills SP-SHADOW-AGENTS-SKILLS=agents-skills"
        for r in invoke list; do
          t="$EVID/transcript-shadow-$r.jsonl"
          echo "== run $r: final result"
          "$JQ" -r 'select(.type=="result") | .result // empty' "$t" 2>/dev/null | sed 's/^/  /' || true
          echo "== run $r: tokens anywhere in the transcript"
          grep -o 'SP-SHADOW-[A-Z-]*' "$t" | sort | uniq -c | sed 's/^/  /' || true
          echo "== run $r: SKILL.md paths named in the transcript"
          grep -o '[^" ]*sp-shadow[^" ]*SKILL\.md' "$t" | sed "s#$ROOT/shadow/home#~#g" | sort | uniq -c | sed 's/^/  /' || true
        done
      } > "$EVID/shadow.txt" ;;
    interactive)
      d=$(cursor_plugin "$H" sp-probe); mkdir -p "$d/hooks"
      cursor_hooks_json "$c" plugin afterAgentResponse > "$d/hooks/hooks.json"
      cursor_hooks_json "$c" user afterAgentResponse > "$H/.cursor/hooks.json"
      # A Claude Code plugin beside them: its Stop, and PreToolUse with no matcher, with the
      # matcher a Claude planning plugin's dispatch logger uses, and with Bash, so the run
      # shows which Claude matchers Cursor's tool names satisfy, interactively.
      claude_matcher_plugin "$c" "$H"
      path_hooks "$c" "$d"
      run_interactive "$c" "$IPROMPT" ;;
    *) echo "unknown case: $c" >&2; exit 2 ;;
  esac
  echo "case $c: hook lines (route event count):" >> "$EVID/version.txt"
  count_table "$c" >> "$EVID/version.txt"
done

cat "$EVID/version.txt"
