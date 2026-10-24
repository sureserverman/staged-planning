#!/usr/bin/env bash
# Fixture suite for the clean-machine harness — run directly (repo convention):
#
#     bash scripts/tests/test-clean-machine-run.sh
#
# WHAT THIS SUITE IS REALLY GUARDING. clean-machine-run.sh is the one proof that the
# plugin works on a machine that has nothing else installed. Its verdict is only worth
# something if (a) it fails when records land anywhere but where --expect says, (b) it
# fails when anything outside the throwaway HOME and the toy repo changed, and (c) the
# login credentials it copies never outlive the run. Every case here drives the harness
# with a stub host binary (--exec), so no network or model call ever happens. The stub
# imitates `plugin marketplace add`, `plugin install` and a `-p` session that writes a
# plan; each variant writes the plan somewhere different or touches a watched dir.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
H="$HERE/../clean-machine-run.sh"
TT="$(mktemp -d)"
trap 'chmod -R u+w "$TT" 2>/dev/null; rm -rf "$TT"' EXIT
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok    $1"; }
bad() { fail=$((fail+1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && printf '        | %s\n' "${2:0:700}"
        [ "${SUITE_FAIL_FAST:-}" = 1 ] && exit 1; }

[ -f "$H" ] || { echo "FAIL: $H does not exist"; exit 1; }

# The fake login file. Its token must never reach the evidence, and no copy of it may
# remain under RUNTMP (the harness's mktemp root) after any run.
TOKEN="fake-cred-token-$$-$RANDOM"
CRED="$TT/secret/login.json"
mkdir -p "$TT/secret" "$TT/tmp" "$TT/watched" "$TT/seen" "$TT/mkt" "$TT/vault-src/notes"
printf '{"claudeAiOauth":{"accessToken":"%s"}}\n' "$TOKEN" > "$CRED"
RUNTMP="$(cd "$TT/tmp" && pwd -P)"   # physical: the harness reports physical paths
WATCH="$TT/watched"
SEEN="$TT/seen"
MKT="$TT/mkt"
printf 'seed\n' > "$TT/vault-src/notes/seed.md"
printf '{"k": 1}\n' > "$TT/home-file.json"
# A variable the harness's own environment carries; env -i must keep it from the session.
export CMR_SENTINEL=leaked-into-session
# The harness lists /tmp as well as the run root's parent; here a dir of the suite's own
# stands in for /tmp, so no run reads or writes the real one.
mkdir -p "$TT/systmp"
export CLEAN_MACHINE_SYS_TMP="$TT/systmp"

mkstub() {  # $1 = mode; see the list after this function
    local f="$TT/stub-$1"
    cat > "$f" <<'EOF'
#!/usr/bin/env bash
MODE=@MODE@; SEEN=@SEEN@; WATCH=@WATCH@; TT=@TT@
tok() { python3 -c 'import json,os;print(json.load(open(os.environ["CLAUDE_CONFIG_DIR"]+"/.credentials.json"))["claudeAiOauth"]["accessToken"])'; }
case "${1:-}" in
  --version) echo "9.9.9 (Stub Code)"; exit 0 ;;
  plugin)
    case "${2:-} ${3:-}" in
      "marketplace add")
        mkdir -p "$CLAUDE_CONFIG_DIR/plugins"
        printf '%s\n' "$4" >> "$CLAUDE_CONFIG_DIR/plugins/marketplaces.txt"
        printf '%s\n' "$4" > "$SEEN/mkt-path"; ls -A "$4" > "$SEEN/mkt-ls"
        echo "added marketplace from $4"; exit 0 ;;
      install\ *)
        if [ "$MODE" = installfail ]; then echo "install failed for $3" >&2; exit 1; fi
        touch "$CLAUDE_CONFIG_DIR/plugins/installed-$3"
        # The install's own copy of the plugin source holds plan-shaped .md files.
        mkdir -p "$CLAUDE_CONFIG_DIR/plugins/cache/$3/docs/plans"
        printf '# Light Plan: example\n' > "$CLAUDE_CONFIG_DIR/plugins/cache/$3/docs/plans/example-plan.md"
        [ "$MODE" = installwatch ] && printf 'oops\n' > "$WATCH/from-install.txt"
        echo "installed $3"; exit 0 ;;
    esac
    exit 3 ;;
  -p)
    printf '%s\n' "$HOME" > "$SEEN/session-home"
    printf '%s\n' "$PWD" > "$SEEN/session-cwd"
    printf '%s\n' "$@" > "$SEEN/session-args"
    env > "$SEEN/session-env"
    python3 -c 'import os,sys;print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' \
        "$CLAUDE_CONFIG_DIR/.credentials.json" > "$SEEN/cred-mode" 2>&1
    [ -f "$HOME/.config/stub/settings.json" ] && echo yes > "$SEEN/home-file" || echo no > "$SEEN/home-file"
    printf '{"type":"system","subtype":"init","cwd":"%s","home":"%s"}\n' "$PWD" "$HOME"
    skills="planning:brainstorming planning:planning-projects planning:executing-plans"
    [ "$MODE" = noskills ] && skills=""
    [ "$MODE" = reorder ] && skills="planning:brainstorming planning:executing-plans planning:planning-projects"
    n=0
    for s in $skills; do
      n=$((n+1))
      printf '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"toolu_s%s","name":"Skill","input":{"skill":"%s"}}]}}\n' "$n" "$s"
      # Each call is answered by its tool_result; skillerr answers every one with an error.
      case "$MODE.$n" in
        skillerr.1) r='"is_error":true,"content":"Launching skill: '"$s"'"' ;;
        skillerr.2) r='"content":"Unknown skill: '"$s"'"' ;;
        skillerr.3) r='"content":[{"type":"text","text":"Error: skill '"$s"' failed to load"}]' ;;
        *)          r='"content":"Launching skill: '"$s"'"' ;;
      esac
      [ "$MODE" = skillnores ] || \
        printf '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_s%s",%s}]}}\n' "$n" "$r"
    done
    case "$MODE" in
      elsewhere) d="$HOME/notes/plans" ;;
      testvault) d="$HOME/test-vault/plans" ;;
      *)         d="$PWD/docs/plans" ;;
    esac
    mkdir -p "$d"; printf '# Light Plan: fix add\n\n### Task 1.1: fix add\n' > "$d/2026-10-19-calc-plan.md"
    printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Write","input":{"file_path":"%s"}}]}}\n' "$d/2026-10-19-calc-plan.md"
    [ "$MODE" = watch ] && printf 'oops\n' > "$WATCH/leaked.txt"
    # Straight into the system temp dir (the harness's own temp root), not $TMPDIR.
    [ "$MODE" = tmpstray ] && printf 'oops\n' > "$TT/tmp/stray-in-temp.txt"
    # Straight into /tmp (the suite's stand-in) while the harness's TMPDIR is elsewhere.
    [ "$MODE" = systmpstray ] && printf 'oops\n' > "$TT/systmp/stray-in-sys-tmp.txt"
    case "$MODE" in
      testfail|usercust) ;;
      edittest) printf 'print("ok")\n' > tests/test_calc.py ;;
      *) printf 'def add(a, b):\n    return a + b\n' > calc.py ;;
    esac
    case "$MODE" in
      refresh) printf '{"type":"assistant","message":{"content":[{"type":"text","text":"%s"}]}}\n' "$(tok)"
               printf '{"claudeAiOauth":{"accessToken":"rotated-token-ZZZZZZZZ"}}\n' > "$CLAUDE_CONFIG_DIR/.credentials.json" ;;
      delete)  printf '{"type":"assistant","message":{"content":[{"type":"text","text":"%s"}]}}\n' "$(tok)"
               rm -f "$CLAUDE_CONFIG_DIR/.credentials.json" ;;
      partial) t="$(tok)"; printf '{"type":"assistant","message":{"content":[{"type":"text","text":"starts %s"}]}}\n' "${t:0:20}" ;;
      symlinkwatch) printf 'oops\n' > "$TT/watched-real/leaked.txt" ;;
      mtime)   printf 'changed\n' > "$WATCH/seed.txt"; touch -t 200001010000 "$WATCH/seed.txt" "$WATCH" ;;
      bg)      ( sleep 2; printf 'late\n' > "$WATCH/late.txt" ) >/dev/null 2>&1 &
               disown ;;
      pluginplan) mkdir -p "$HOME/.claude/plugins/cache/p"; printf '# Light Plan: p\n' > "$HOME/.claude/plugins/cache/p/z.md" ;;
      docsnote) mkdir -p "$HOME/notes"; printf 'intro\n\n# Design: d\n' > "$HOME/notes/d.md" ;;
      synced)  # Files a host syncs into a fresh HOME are not plans, whatever their dirs.
               mkdir -p "$HOME/.claude/skills/synced/x/docs" "$HOME/.claude/plugins/synced/y/docs/plans"
               printf '# docs\n' > "$HOME/.claude/skills/synced/x/docs/SKILL.md"
               printf '# A routine plan\n' > "$HOME/.claude/plugins/synced/y/docs/plans/routine-plan.md" ;;
      designonly) rm -f "$PWD/docs/plans/2026-10-19-calc-plan.md"
               printf '# Design: fix add\n' > "$PWD/docs/plans/2026-10-19-calc-design.md" ;;
      copyplan) mkdir -p "$(cat "$SEEN/mkt-path")/docs/plans"
               printf '# Master Plan: stray\n' > "$(cat "$SEEN/mkt-path")/docs/plans/stray.md" ;;
      bomplan) printf '\357\273\277# Light Plan: fix add\n' > "$PWD/docs/plans/2026-10-19-calc-plan.md" ;;
      pluginwrite) printf 'x\n' > "$(cat "$SEEN/mkt-path")/written-by-session.txt" ;;
      tokplan) t="$(tok)"; printf '# Light Plan: p\n' > "$PWD/docs/plans/$t-plan.md" ;;
      escape)  # The session ends only once the child has left its process group.
               python3 -c 'import os, sys, time
os.setpgid(0, 0); open(sys.argv[2], "w").close(); time.sleep(2); open(sys.argv[1], "w").write("late\n")' \
                   "$WATCH/late-pgrp.txt" "$SEEN/escaped" >/dev/null 2>&1 &
               disown
               for _ in $(seq 1 50); do [ -e "$SEEN/escaped" ] && break; sleep 0.1; done ;;
      usercust) d="$(python3 -c 'import site; print(site.getusersitepackages())')"; mkdir -p "$d"
                printf 'import os, sys\nsys.path.insert(0, os.getcwd())\nimport calc\ncalc.add = lambda a, b: a + b\n' > "$d/usercustomize.py" ;;
      meta)    printf '{"type":"assistant","message":{"content":[{"type":"text","text":"scopes inference-scope profile-scope, tier default_claude_max"}]}}\n' ;;
      keyedshort) printf '{"type":"assistant","message":{"content":[{"type":"text","text":"refresh is short-r8x"}]}}\n' ;;
    esac
    [ "$MODE" = leak ] && printf '{"type":"assistant","message":{"content":[{"type":"text","text":%s}]}}\n' \
        "$(python3 -c 'import json,sys; print(json.dumps(open(sys.argv[1]).read()))' "$CLAUDE_CONFIG_DIR/.credentials.json")"
    [ "$MODE" = sleep ] && { echo started > "$SEEN/session-started"; sleep 30; }
    printf '{"type":"result","subtype":"success","is_error":false}\n'
    exit 0 ;;
esac
exit 3
EOF
    sed -i.bak -e "s|@MODE@|$1|" -e "s|@SEEN@|$SEEN|" -e "s|@WATCH@|$WATCH|" -e "s|@TT@|$TT|" "$f" && rm -f "$f.bak"
    chmod +x "$f"
}
# docs: the good run. watch/elsewhere/testvault: where it writes. installfail, leak, sleep.
# noskills/reorder: the skills are not all used in order. testfail/edittest: the toy test
# is left failing or rewritten. refresh/delete/partial: the token is printed, then the copy
# changes or goes, or only a prefix is printed. symlinkwatch/mtime/bg/installwatch: writes
# the watch check could miss. pluginplan/docsnote: plans with a planning title in places a
# path rule would skip. synced: host-synced docs that are not plans. pluginwrite: the session
# writes into the plugin's own install dir.
# skillerr/skillnores: the Skill calls are answered by errors, or not answered. tokplan: a
# plan named after the token. escape: a child that leaves the session's process group.
# usercust: a usercustomize.py in the throwaway HOME fakes the toy fix. meta/keyedshort:
# the session prints credentials metadata, or a short value held under a token key.
# tmpstray: a file written straight into the system temp dir, outside every --watch dir.
# systmpstray: the same, into /tmp (the suite's stand-in) when TMPDIR points elsewhere.
for m in docs watch elsewhere testvault installfail leak sleep noskills reorder testfail edittest \
         refresh delete partial symlinkwatch mtime bg installwatch pluginplan docsnote synced pluginwrite designonly copyplan bomplan \
         skillerr skillnores tokplan escape usercust meta keyedshort tmpstray systmpstray; do mkstub "$m"; done
# Every run names one plugin: a run with none proves nothing about the plugin.
PL=(--plugin "$MKT" planning@staged-planning)

cat > "$TT/setup.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\${CLEAN_HOME-unset}" > "$SEEN/setup-home"
printf '%s\n' "\${CLEAN_TEST_VAULT-unset}" > "$SEEN/setup-vault"
printf '%s\n' "\${CLEAN_HOST-unset}" > "$SEEN/setup-host"
[ -f "\${CLEAN_TEST_VAULT-/nonexistent}/notes/seed.md" ] && echo yes > "$SEEN/setup-seed" || echo no > "$SEEN/setup-seed"
grep -q '^installed-' < <(ls "\$CLEAN_HOME/.claude/plugins" 2>/dev/null) && echo yes > "$SEEN/setup-after-install" || echo no > "$SEEN/setup-after-install"
EOF

# run_h <evidence-dir> <args...>: run the harness with mktemp rooted in RUNTMP, then
# check that no credentials copy survived. Sets rc and err.
run_h() {
    local ev="$1"; shift
    rm -f "$SEEN"/*
    TMPDIR="$RUNTMP" bash "$H" --credentials "${RUN_CRED:-$CRED}" --evidence "$ev" "$@" >"$TT/h.out" 2>"$TT/h.err"
    rc=$?
    err="$(cat "$TT/h.err")"
    local left; left="$(find "$RUNTMP" \( -name .credentials.json -o -name auth.json \) 2>/dev/null
        grep -rlF -e "$TOKEN" ${CTOKEN:+-e "$CTOKEN"} ${KTOKEN:+-e "$KTOKEN"} ${OTOKEN:+-e "$OTOKEN"} "$RUNTMP" 2>/dev/null)"
    if [ -z "$left" ]; then ok "no credentials copy remains after the run (rc=$rc)"
    else bad "a credentials copy survived the run" "$left"; fi
    if [ -d "$ev" ] && grep -rqF -e "$TOKEN" -e "$CRED" ${CTOKEN:+-e "$CTOKEN" -e "$CACCT" -e "$CCRED"} \
            ${KTOKEN:+-e "$KTOKEN" -e "$KCRED"} ${OTOKEN:+-e "$OTOKEN" -e "$OCRED"} "$ev" 2>/dev/null; then
        bad "the evidence carries the credentials or their path"
    fi
}
aj() {  # aj <evidence-dir> <python expr over a> — print the expression's value
    python3 -c 'import json,sys; a=json.load(open(sys.argv[1])); print(eval(sys.argv[2]))' "$1/asserts.json" "$2" 2>&1
}

# --- 1. The good run: plan lands in <toy>/docs, nothing outside changes -> exit 0.
EV="$TT/ev-docs"
run_h "$EV" --plugin "$MKT" planning@staged-planning --test-vault "$TT/vault-src" \
    --setup "$TT/setup.sh" --home-file .config/stub/settings.json="$TT/home-file.json" \
    --watch "$WATCH" --model stub-model --exec "$TT/stub-docs"
if [ $rc -eq 0 ]; then ok "the docs stub exits 0"; else bad "the docs stub must exit 0 (rc=$rc)" "$err"; fi
[ "$(aj "$EV" 'a["records_under"]')" = docs ] && ok "records_under is docs" \
    || bad "records_under must be docs" "$(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["outside_changes"]')" = "[]" ] && ok "outside_changes is empty" \
    || bad "outside_changes must be empty" "$(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["plan_files"]')" = "['<toy>/docs/plans/2026-10-19-calc-plan.md']" ] \
    && ok "plan_files names the plan by its <toy> label" || bad "plan_files is wrong" "$(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["skills_seen"]')" = "['planning:brainstorming', 'planning:planning-projects', 'planning:executing-plans']" ] \
    && ok "skills_seen lists the three skills in order" || bad "skills_seen is wrong" "$(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["exit"]')" = 0 ] && ok "exit records the session's exit" || bad "exit must be 0" "$(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["toy_test_exit"]')" = 0 ] && ok "toy_test_exit records the toy test passing after the session" \
    || bad "toy_test_exit must be 0" "$(aj "$EV" 'a')"
case "$(aj "$EV" 'a["host_version"]')" in *9.9.9*) ok "host_version comes from the host binary" ;;
    *) bad "host_version is wrong" "$(aj "$EV" 'a')" ;; esac
SH="$(cat "$SEEN/session-home" 2>/dev/null)"
case "$SH" in "$RUNTMP"/*) ok "the session's HOME is a throwaway dir under the temp root" ;;
    *) bad "the session HOME must be under the temp root" "$SH" ;; esac
[ "$(cat "$SEEN/setup-host" 2>/dev/null)" = claude ] && ok "--setup sees CLEAN_HOST, the --host of the run" \
    || bad "--setup must see CLEAN_HOST=claude" "$(cat "$SEEN/setup-host" 2>/dev/null)"
[ "$(cat "$SEEN/setup-home" 2>/dev/null)" = "$SH" ] && ok "--setup sees CLEAN_HOME equal to the throwaway HOME" \
    || bad "--setup must see CLEAN_HOME = the session HOME" "$(cat "$SEEN/setup-home" 2>/dev/null) vs $SH"
[ "$(cat "$SEEN/setup-vault" 2>/dev/null)" = "$SH/test-vault" ] \
    && ok "--setup sees CLEAN_TEST_VAULT = \$CLEAN_HOME/test-vault" \
    || bad "--setup must see CLEAN_TEST_VAULT" "$(cat "$SEEN/setup-vault" 2>/dev/null)"
[ "$(cat "$SEEN/setup-seed" 2>/dev/null)" = yes ] && ok "the test vault is copied before setup runs" \
    || bad "the test vault copy must exist when setup runs"
[ "$(cat "$SEEN/setup-after-install" 2>/dev/null)" = yes ] && ok "setup runs after the plugins are installed" \
    || bad "setup must run after plugin install"
[ "$(cat "$SEEN/cred-mode" 2>/dev/null)" = 0o600 ] && ok "the credentials copy is mode 600 in \$HOME/.claude" \
    || bad "the credentials copy must be mode 600" "$(cat "$SEEN/cred-mode" 2>/dev/null)"
[ "$(cat "$SEEN/home-file" 2>/dev/null)" = yes ] && ok "--home-file is placed under the throwaway HOME" \
    || bad "--home-file must be placed"
grep -q CMR_SENTINEL "$SEEN/session-env" 2>/dev/null && bad "the session inherits the caller's environment" \
    || ok "the session runs under env -i"
if grep -qF "$TOKEN" "$SEEN/session-env" "$SEEN/session-args" 2>/dev/null; then
    bad "the token reached the session's environment or arguments"
else ok "the token is in neither the session's environment nor its arguments"; fi
grep -qx "CLAUDE_CONFIG_DIR=$SH/.claude" "$SEEN/session-env" 2>/dev/null \
    && ok "CLAUDE_CONFIG_DIR points into the throwaway HOME" || bad "CLAUDE_CONFIG_DIR must be \$HOME/.claude"
case "$(cat "$SEEN/session-cwd" 2>/dev/null)" in "$RUNTMP"/*) ok "the session runs in the toy repo" ;;
    *) bad "the session cwd must be the toy repo" ;; esac
ARGS="$(cat "$SEEN/session-args" 2>/dev/null)"
for want in stream-json --verbose acceptEdits --model stub-model --allowedTools 'Bash(git *)' \
            'Bash(python3 *)' 'Bash(bash *)' planning:brainstorming planning:planning-projects planning:executing-plans \
            'not a broken baseline'; do
    grep -qF -- "$want" <<<"$ARGS" || bad "the session args lack '$want'" "$ARGS"
done
grep -qx 'Bash' <<<"$ARGS" && bad "Bash must not be allowed unrestricted"
ok "the session gets the fixed flags and the three-skill prompt"
if [ -f "$EV/transcript.jsonl" ] && grep -qF '<toy>' "$EV/transcript.jsonl" && grep -qF '<home>' "$EV/transcript.jsonl" \
   && ! grep -qF "$RUNTMP" "$EV/transcript.jsonl"; then ok "transcript.jsonl paths are rewritten to labels"
else bad "transcript paths must be rewritten to <toy>/<home>" "$(head -c 400 "$EV/transcript.jsonl" 2>/dev/null)"; fi
grep -rqF "$RUNTMP" "$EV" && bad "the evidence still carries a raw temp path" "$(grep -rlF "$RUNTMP" "$EV")" \
    || ok "no evidence file carries a raw temp path"
[ -z "$(ls -A "$RUNTMP")" ] && ok "the throwaway root is removed" || bad "the throwaway root must be removed" "$(ls -A "$RUNTMP")"

# --- 2. --setup without --test-vault: CLEAN_TEST_VAULT is unset.
run_h "$TT/ev-novault" "${PL[@]}" --setup "$TT/setup.sh" --watch "$WATCH" --exec "$TT/stub-docs"
[ "$(cat "$SEEN/setup-vault" 2>/dev/null)" = unset ] && ok "without --test-vault, CLEAN_TEST_VAULT is unset" \
    || bad "CLEAN_TEST_VAULT must be unset without --test-vault" "$(cat "$SEEN/setup-vault" 2>/dev/null)"
[ $rc -eq 0 ] || bad "a run with one plugin and no vault must still pass (rc=$rc)" "$err"

# --- 3. A host the harness does not know exits 2.
run_h "$TT/ev-badhost" "${PL[@]}" --host vscode --watch "$WATCH" --exec "$TT/stub-docs"
if [ $rc -eq 2 ] && grep -q -- '--host must be' <<<"$err"; then ok "an unknown --host exits 2"
else bad "an unknown --host must exit 2 naming the hosts (rc=$rc)" "$err"; fi

# --- 4. A session that writes into a watched dir fails.
EV="$TT/ev-watch"
run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-watch"
[ $rc -eq 1 ] && ok "the watch-writing stub exits 1" || bad "the watch-writing stub must exit 1 (rc=$rc)" "$err"
case "$(aj "$EV" 'a["outside_changes"]')" in *"<watch:1>/leaked.txt"*) ok "outside_changes names the watched write" ;;
    *) bad "outside_changes must name <watch:1>/leaked.txt" "$(aj "$EV" 'a')" ;; esac
rm -f "$WATCH/leaked.txt"

# --- 4b. A file written straight into the system temp dir is an outside change, though no
# --watch names the temp dir; and the session's own TMPDIR is inside the run's root.
EV="$TT/ev-tmpstray"
run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-tmpstray"
[ $rc -eq 1 ] && ok "the temp-writing stub exits 1" || bad "the temp-writing stub must exit 1 (rc=$rc)" "$err"
case "$(aj "$EV" 'a["outside_changes"]')" in *"stray-in-temp.txt"*) ok "outside_changes names the file created in the system temp dir" ;;
    *) bad "outside_changes must name the stray temp file" "$(aj "$EV" 'a')" ;; esac
case "$(sed -n 's/^TMPDIR=//p' "$SEEN/session-env" 2>/dev/null)" in "$RUNTMP"/clean-machine.*/tmp) ok "the session's TMPDIR is inside the run's own root" ;;
    *) bad "the session's TMPDIR must be <run root>/tmp" "$(grep '^TMPDIR=' "$SEEN/session-env" 2>/dev/null)" ;; esac
rm -f "$RUNTMP/stray-in-temp.txt"

# --- 4c. /tmp is listed too, though the harness's TMPDIR (the run root's parent) is not /tmp.
EV="$TT/ev-systmpstray"
run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-systmpstray"
[ $rc -eq 1 ] && ok "a write into /tmp under another TMPDIR exits 1" || bad "a write into /tmp under another TMPDIR must exit 1 (rc=$rc)" "$err"
case "$(aj "$EV" 'a["outside_changes"]')" in *"systmp/stray-in-sys-tmp.txt"*) ok "outside_changes names the file created in /tmp" ;;
    *) bad "outside_changes must name the file created in /tmp" "$(aj "$EV" 'a')" ;; esac
rm -f "$TT/systmp/stray-in-sys-tmp.txt"

# --- 4d. When /tmp is the run root's parent, it is listed once: one stray, one entry, and
# the run root itself is not reported.
EV="$TT/ev-tmpdedupe"
CLEAN_MACHINE_SYS_TMP="$RUNTMP" run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-tmpstray"
[ "$(aj "$EV" 'len(a["outside_changes"]), "stray-in-temp.txt" in a["outside_changes"][0]')" = "(1, True)" ] \
    && ok "a temp dir named twice is listed once" || bad "the deduped listing must report the stray once and nothing else" "$(aj "$EV" 'a')"
rm -f "$RUNTMP/stray-in-temp.txt"

# --- 4e. A find without GNU -printf (BSD, macOS) does not blind the check.
mkdir -p "$TT/bsdfind"
cat > "$TT/bsdfind/find" <<EOF
#!/usr/bin/env bash
for a in "\$@"; do [ "\$a" = -printf ] && { echo "find: -printf: unknown primary or operator" >&2; exit 1; }; done
exec $(command -v find) "\$@"
EOF
chmod +x "$TT/bsdfind/find"
EV="$TT/ev-bsdfind"
PATH="$TT/bsdfind:$PATH" run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-tmpstray"
case "$rc:$(aj "$EV" 'a["outside_changes"]')" in 1:*"stray-in-temp.txt"*) ok "the temp-dir check works without GNU find -printf" ;;
    *) bad "the temp-dir check must not depend on GNU find -printf (rc=$rc)" "$(aj "$EV" 'a')" ;; esac
rm -f "$RUNTMP/stray-in-temp.txt"

# --- 4f. A temp dir that cannot be listed fails the run instead of passing it silently.
EV="$TT/ev-tmpunlisted"
CLEAN_MACHINE_SYS_TMP="$TT/no-such-tmp" run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-docs"
case "$rc:$(aj "$EV" 'a.get("error", "")')" in 1:*"listing the temp dirs failed"*) ok "a failed temp-dir listing fails the run" ;;
    *) bad "a failed temp-dir listing must fail the run (rc=$rc)" "$(aj "$EV" 'a')" ;; esac

# --- 5. A plan written anywhere but the records home fails.
EV="$TT/ev-elsewhere"
run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-elsewhere"
[ $rc -eq 1 ] && ok "the plan-elsewhere stub exits 1" || bad "the plan-elsewhere stub must exit 1 (rc=$rc)" "$err"
[ "$(aj "$EV" 'a["records_under"]')" = elsewhere ] && ok "records_under is elsewhere" \
    || bad "records_under must be elsewhere" "$(aj "$EV" 'a')"

# --- 6. --expect test-vault passes when the plan lands in the test vault.
EV="$TT/ev-tv"
run_h "$EV" "${PL[@]}" --test-vault "$TT/vault-src" --expect test-vault --watch "$WATCH" --exec "$TT/stub-testvault"
[ $rc -eq 0 ] && ok "--expect test-vault passes on a test-vault plan" || bad "--expect test-vault must pass (rc=$rc)" "$err"
[ "$(aj "$EV" 'a["plan_files"]')" = "['<test-vault>/plans/2026-10-19-calc-plan.md']" ] \
    && ok "a test-vault plan is labelled <test-vault>" || bad "test-vault label is wrong" "$(aj "$EV" 'a')"
run_h "$TT/ev-tv2" "${PL[@]}" --test-vault "$TT/vault-src" --watch "$WATCH" --exec "$TT/stub-testvault"
[ $rc -eq 1 ] && ok "a test-vault plan fails the default --expect docs" || bad "default --expect docs must fail a test-vault plan (rc=$rc)"

# --- 7. Failure before the session: a plugin install fails.
EV="$TT/ev-installfail"
run_h "$EV" --plugin "$MKT" planning@staged-planning --watch "$WATCH" --exec "$TT/stub-installfail"
[ $rc -eq 1 ] && ok "a failed plugin install exits 1" || bad "a failed install must exit 1 (rc=$rc)" "$err"
[ -f "$EV/asserts.json" ] && ok "a failed install still writes asserts.json" || bad "asserts.json missing after install failure"
grep -qF "$MKT" "$EV"/* 2>/dev/null && bad "a plugin dir path leaked into the evidence" || ok "plugin dirs are labelled in the evidence"

# --- 8. Usage errors exit 2 and never start a run.
TMPDIR="$RUNTMP" bash "$H" --evidence "$TT/ev-x" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-docs" >/dev/null 2>&1
[ $? -eq 2 ] && ok "a missing --credentials exits 2" || bad "a missing --credentials must exit 2"
run_h "$HERE/../../.cmr-evidence-in-repo" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-docs"
[ $rc -eq 2 ] && ok "evidence inside the repo is refused (exit 2)" || bad "evidence inside the repo must exit 2 (rc=$rc)" "$err"
rmdir "$HERE/../../.cmr-evidence-in-repo" 2>/dev/null
run_h "$TT/ev-hf" "${PL[@]}" --home-file .claude/.credentials.json="$TT/home-file.json" --watch "$WATCH" --exec "$TT/stub-docs"
[ $rc -eq 2 ] && ok "--home-file cannot place a credentials file" || bad "--home-file onto the credentials path must exit 2 (rc=$rc)"
run_h "$TT/ev-hf2" "${PL[@]}" --home-file .claude//.credentials.json="$TT/home-file.json" --watch "$WATCH" --exec "$TT/stub-docs"
[ $rc -eq 2 ] && ok "a doubled slash cannot slip a credentials path past the guard" || bad "'.claude//.credentials.json' must exit 2 (rc=$rc)"
for trav in ../x ../../x a/../../x /abs; do
    run_h "$TT/ev-trav" "${PL[@]}" --home-file "$trav=$TT/home-file.json" --watch "$WATCH" --exec "$TT/stub-docs"
    [ $rc -eq 2 ] && ok "--home-file '$trav' is refused" || bad "--home-file '$trav' must exit 2 (rc=$rc)"
done
run_h "$TT/ev-nowatch" "${PL[@]}" --exec "$TT/stub-docs"
[ $rc -eq 2 ] && grep -q -- '--watch' <<<"$err" && ok "a run with no --watch is refused" \
    || bad "a run with no --watch must exit 2 naming --watch (rc=$rc)" "$err"
run_h "$TT/ev-badid" --plugin "$MKT" -planning --watch "$WATCH" --exec "$TT/stub-docs"
[ $rc -eq 2 ] && ok "a plugin id that is not <plugin>@<marketplace> is refused" || bad "a bad plugin id must exit 2 (rc=$rc)"

# --- 9. A relative --setup still runs (the harness cds into the throwaway HOME first).
( cd "$TT" && run_h "$TT/ev-relsetup" "${PL[@]}" --setup setup.sh --watch "$WATCH" --exec "$TT/stub-docs"
  [ $rc -eq 0 ] && [ "$(cat "$SEEN/setup-home" 2>/dev/null)" != "" ] && echo REL_OK > "$TT/rel.result" || echo "rc=$rc $err" > "$TT/rel.result" )
[ "$(cat "$TT/rel.result")" = REL_OK ] && ok "a relative --setup path is resolved before the cd" \
    || bad "a relative --setup must run" "$(cat "$TT/rel.result")"

# --- 10. A session that prints the credentials: the evidence is redacted and the run fails.
EV="$TT/ev-leak"
run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-leak"
[ $rc -eq 1 ] && ok "a session exposing the credentials fails the run" || bad "a credentials-exposing session must exit 1 (rc=$rc)" "$err"
grep -qF '<redacted>' "$EV/transcript.jsonl" 2>/dev/null && ok "the exposed token is redacted in the transcript" \
    || bad "the transcript must carry <redacted>"
case "$(aj "$EV" 'a.get("error","")')" in *credentials*) ok "asserts.json says the credentials were exposed" ;;
    *) bad "asserts.json must name the exposure" "$(aj "$EV" 'a')" ;; esac

# --- 11. TERM mid-session: the run ends promptly and no credentials copy remains.
rm -f "$SEEN"/*
TMPDIR="$RUNTMP" bash "$H" --credentials "$CRED" --evidence "$TT/ev-term" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-sleep" >/dev/null 2>&1 &
HPID=$!
for _ in $(seq 1 50); do [ -f "$SEEN/session-started" ] && break; sleep 0.1; done
start=$(date +%s); kill -TERM "$HPID"; wait "$HPID" 2>/dev/null; took=$(( $(date +%s) - start ))
[ "$took" -le 5 ] && ok "TERM ends the run promptly (${took}s)" || bad "TERM must end the run promptly (took ${took}s)"
[ -z "$(find "$RUNTMP" -name .credentials.json 2>/dev/null)" ] && ok "no credentials copy remains after TERM" \
    || bad "a credentials copy survived TERM" "$(find "$RUNTMP" -name .credentials.json)"
[ -z "$(ls -A "$RUNTMP")" ] && ok "no run leaves anything under the temp root" || bad "runs left files under the temp root" "$(ls -A "$RUNTMP")"

# --- 12. The verdict proves the workflow ran.
run_h "$TT/ev-noplugin" --watch "$WATCH" --exec "$TT/stub-docs"
[ $rc -eq 2 ] && grep -q -- '--plugin' <<<"$err" && ok "a run with no --plugin is refused" \
    || bad "a run with no --plugin must exit 2 naming --plugin (rc=$rc)" "$err"
for m in noskills reorder; do
    run_h "$TT/ev-$m" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-$m"
    [ $rc -eq 1 ] && ok "a plan written without the three skills in order fails ($m)" \
        || bad "a $m session must exit 1 (rc=$rc)" "$(aj "$TT/ev-$m" 'a')"
done
EV="$TT/ev-testfail"
run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-testfail"
[ $rc -eq 1 ] && ok "a session that leaves the toy test failing fails" || bad "a failing toy test must exit 1 (rc=$rc)" "$(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["toy_test_exit"]')" = 1 ] && ok "toy_test_exit records the failing test" \
    || bad "toy_test_exit must be 1" "$(aj "$EV" 'a')"
run_h "$TT/ev-edittest" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-edittest"
[ $rc -eq 1 ] && ok "a session that rewrites the toy test fails" || bad "a rewritten toy test must exit 1 (rc=$rc)" "$(aj "$TT/ev-edittest" 'a')"

# --- 13. A symlinked --watch dir is measured.
mkdir -p "$TT/watched-real"; ln -s "$TT/watched-real" "$TT/watchlink"
EV="$TT/ev-symlink"
run_h "$EV" "${PL[@]}" --watch "$TT/watchlink" --exec "$TT/stub-symlinkwatch"
[ $rc -eq 1 ] && ok "a write into a symlinked watch dir fails the run" || bad "a symlinked watch write must exit 1 (rc=$rc)" "$(aj "$EV" 'a')"
case "$(aj "$EV" 'a["outside_changes"]')" in *"<watch:1>/leaked.txt"*) ok "outside_changes names the write behind the symlink" ;;
    *) bad "outside_changes must name <watch:1>/leaked.txt" "$(aj "$EV" 'a')" ;; esac

# --- 14. Redaction uses the original credentials, and catches a long prefix.
for m in refresh delete partial; do
    EV="$TT/ev-$m"
    run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-$m"
    [ $rc -eq 1 ] && ok "a session that printed the token fails ($m)" || bad "a $m session must exit 1 (rc=$rc)" "$(aj "$EV" 'a')"
    if grep -rqF -e "${TOKEN:0:16}" "$EV"; then bad "the evidence carries part of the token ($m)"
    else ok "no 16-character piece of the token reaches the evidence ($m)"; fi
    case "$(aj "$EV" 'a.get("error","")')" in *credentials*) ok "asserts.json names the exposure ($m)" ;;
        *) bad "asserts.json must name the exposure ($m)" "$(aj "$EV" 'a')" ;; esac
done

# --- 15. Changes the watch check could miss.
printf 'seed\n' > "$WATCH/seed.txt"; touch -t 200001010000 "$WATCH/seed.txt"
EV="$TT/ev-mtime"
run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-mtime"
[ $rc -eq 1 ] && ok "an mtime-preserving write into a watch dir fails" || bad "a backdated write must exit 1 (rc=$rc)" "$(aj "$EV" 'a')"
case "$(aj "$EV" 'a["outside_changes"]')" in *"<watch:1>/seed.txt"*) ok "outside_changes names the backdated file" ;;
    *) bad "outside_changes must name <watch:1>/seed.txt" "$(aj "$EV" 'a')" ;; esac
rm -f "$WATCH/seed.txt"
printf '#!/usr/bin/env bash\nprintf "oops\\n" > "%s/from-setup.txt"\n' "$WATCH" > "$TT/setup-watch.sh"
run_h "$TT/ev-setupwatch" "${PL[@]}" --setup "$TT/setup-watch.sh" --watch "$WATCH" --exec "$TT/stub-docs"
[ $rc -eq 1 ] && ok "a --setup that writes into a watch dir fails" || bad "a watch write during --setup must exit 1 (rc=$rc)" "$(aj "$TT/ev-setupwatch" 'a')"
rm -f "$WATCH/from-setup.txt"
run_h "$TT/ev-installwatch" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-installwatch"
[ $rc -eq 1 ] && ok "a plugin install that writes into a watch dir fails" || bad "a watch write during install must exit 1 (rc=$rc)" "$(aj "$TT/ev-installwatch" 'a')"
rm -f "$WATCH/from-install.txt"
run_h "$TT/ev-bg" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-bg"
sleep 3
if [ -e "$WATCH/late.txt" ]; then bad "a background child of the session wrote after the check"
else ok "the session's process group is killed when the session ends"; fi
rm -f "$WATCH/late.txt"

# --- 16. Plans in places a path rule would skip.
for m in pluginplan docsnote; do
    EV="$TT/ev-$m"
    run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-$m"
    [ $rc -eq 1 ] && ok "a stray plan candidate fails the run ($m)" || bad "a $m session must exit 1 (rc=$rc)" "$(aj "$EV" 'a')"
    [ "$(aj "$EV" 'a["records_under"]')" = elsewhere ] && ok "records_under is elsewhere ($m)" \
        || bad "records_under must be elsewhere ($m)" "$(aj "$EV" 'a')"
done

# --- 16b. Host-synced docs are not plan candidates: the title decides, not the path.
EV="$TT/ev-synced"
run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-synced"
[ $rc -eq 0 ] && ok "host-synced docs leave the run green" || bad "a synced session must exit 0 (rc=$rc)" "$(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["plan_files"]')" = "['<toy>/docs/plans/2026-10-19-calc-plan.md']" ] \
    && ok "only the titled plan is a plan file (synced)" || bad "plan_files is wrong (synced)" "$(aj "$EV" 'a')"

EV="$TT/ev-designonly"
run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-designonly"
[ $rc -eq 1 ] && ok "a design with no plan fails the run" || bad "a designonly session must exit 1 (rc=$rc)" "$(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["records_under"]')" = none ] && ok "records_under is none with no plan title" \
    || bad "records_under must be none (designonly)" "$(aj "$EV" 'a')"

# --- 16c. A git marketplace installs from a copy of its committed tree, inside the run
# root, so an uncommitted file is not installed and a write into the install dir is the
# install's own, as with a real install into the plugin cache.
GMKT="$TT/gmkt"; mkdir -p "$GMKT"
( cd "$GMKT" && git init -q --template= && printf 'c\n' > committed.txt && git add committed.txt \
  && git -c user.name=t -c user.email=t@example.com commit -qm c --no-verify ) >/dev/null 2>&1 \
    || bad "making the git marketplace failed"
printf 'u\n' > "$GMKT/uncommitted.txt"
EV="$TT/ev-pluginwrite"
run_h "$EV" --plugin "$GMKT" planning@staged-planning --watch "$WATCH" --watch "$GMKT" --exec "$TT/stub-pluginwrite"
case "$(cat "$SEEN/mkt-path" 2>/dev/null)" in "$RUNTMP"/*) ok "the marketplace added is a copy under the run root" ;;
    *) bad "the marketplace must be a copy under the run root" "$(cat "$SEEN/mkt-path" 2>/dev/null)" ;; esac
[ "$(cat "$SEEN/mkt-ls" 2>/dev/null)" = committed.txt ] && ok "the copy holds the committed tree only" \
    || bad "the copy must hold committed.txt only" "$(cat "$SEEN/mkt-ls" 2>/dev/null)"
[ ! -e "$GMKT/written-by-session.txt" ] && ok "a session write into the install dir leaves the source alone" \
    || bad "the session wrote into the marketplace source"
[ $rc -eq 0 ] && ok "a write into the install's own dir is not an outside change" \
    || bad "a pluginwrite session must exit 0 (rc=$rc)" "$(aj "$EV" 'a')"
grep -qE 'committed tree \(git archive HEAD [0-9a-f]{12}, working tree dirty\)' "$EV/host.log" \
    && ok "host.log names the copy, its commit, and that the source had uncommitted files" \
    || bad "host.log must name the copy and its commit" "$(cat "$EV/host.log" 2>/dev/null)"
# A plan written into the install copy is still a plan, and it is not under <toy>/docs.
EV="$TT/ev-copyplan"
run_h "$EV" --plugin "$GMKT" planning@staged-planning --watch "$WATCH" --exec "$TT/stub-copyplan"
[ $rc -eq 1 ] && ok "a plan written into the plugin's install copy fails the run" \
    || bad "a copyplan session must exit 1 (rc=$rc)" "$(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["records_under"]')" = elsewhere ] && ok "records_under is elsewhere (copyplan)" \
    || bad "records_under must be elsewhere (copyplan)" "$(aj "$EV" 'a')"
# A byte-order mark before the title does not hide it.
EV="$TT/ev-bomplan"
run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-bomplan"
[ $rc -eq 0 ] && [ "$(aj "$EV" 'a["records_under"]')" = docs ] && ok "a title after a BOM is read" \
    || bad "a bomplan session must exit 0 with records under docs (rc=$rc)" "$(aj "$EV" 'a')"
# A git marketplace with no commit has no committed tree to install: the run stops.
EMKT="$TT/emkt"; mkdir -p "$EMKT"; git -C "$EMKT" init -q --template= >/dev/null 2>&1
EV="$TT/ev-emptymkt"
run_h "$EV" --plugin "$EMKT" planning@staged-planning --watch "$WATCH" --exec "$TT/stub-docs"
[ $rc -eq 1 ] && ok "a git marketplace with no commit stops the run" || bad "an empty git marketplace must exit 1 (rc=$rc)"
case "$(aj "$EV" 'a.get("error","")')" in *"committed tree failed"*) ok "asserts.json names the failed copy" ;;
    *) bad "asserts.json must name the failed copy" "$(aj "$EV" 'a')" ;; esac

# --- 17. A Skill call counts only when its tool_result came back without an error.
for m in skillerr skillnores; do
    EV="$TT/ev-$m"
    run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-$m"
    [ $rc -eq 1 ] && ok "Skill calls with no successful result fail the run ($m)" \
        || bad "a $m session must exit 1 (rc=$rc)" "$(aj "$EV" 'a')"
    [ "$(aj "$EV" 'a["skills_seen"]')" = "[]" ] && ok "skills_seen leaves out the unanswered or failed calls ($m)" \
        || bad "skills_seen must be empty ($m)" "$(aj "$EV" 'a')"
done

# --- 18. A credential in a file name is redacted from asserts.json and fails the run.
EV="$TT/ev-tokplan"
run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-tokplan"
[ $rc -eq 1 ] && ok "a plan named after the token fails the run" || bad "a tokplan session must exit 1 (rc=$rc)" "$(aj "$EV" 'a')"
grep -qF "${TOKEN:0:16}" "$EV/asserts.json" 2>/dev/null && bad "asserts.json carries the token from a file name" \
    || ok "asserts.json does not carry the token from a file name"
case "$(aj "$EV" 'a["plan_files"]')" in *"<redacted>"*) ok "plan_files shows the token as <redacted>" ;;
    *) bad "plan_files must redact the token" "$(aj "$EV" 'a')" ;; esac
case "$(aj "$EV" 'a.get("error","")')" in *credentials*) ok "asserts.json names the exposure (tokplan)" ;;
    *) bad "asserts.json must name the exposure (tokplan)" "$(aj "$EV" 'a')" ;; esac

# --- 19. A credentials file that is not JSON is still redacted.
RAWSEC="raw-cred-$$-$RANDOM-abcdefghij"
RAWCRED="$TT/secret/raw-login.txt"
printf 'user clean-machine\nsecret %s\n' "$RAWSEC" > "$RAWCRED"
EV="$TT/ev-rawleak"
RUN_CRED="$RAWCRED" run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-leak"
[ $rc -eq 1 ] && ok "a session echoing non-JSON credentials fails" || bad "a non-JSON leak must exit 1 (rc=$rc)" "$(aj "$EV" 'a')"
grep -rqF "$RAWSEC" "$EV" && bad "the evidence carries the non-JSON secret" || ok "the non-JSON secret is redacted"
case "$(aj "$EV" 'a.get("error","")')" in *credentials*) ok "asserts.json names the exposure (non-JSON)" ;;
    *) bad "asserts.json must name the exposure (non-JSON)" "$(aj "$EV" 'a')" ;; esac

# --- 20. Only real secrets are collected: echoed metadata passes, a keyed short value fails.
METACRED="$TT/secret/meta-login.json"
printf '{"claudeAiOauth":{"accessToken":"%s","refreshToken":"short-r8x","scopes":["inference-scope","profile-scope"],"subscriptionType":"max","rateLimitTier":"default_claude_max"}}\n' "$TOKEN" > "$METACRED"
RUN_CRED="$METACRED" run_h "$TT/ev-meta" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-meta"
[ $rc -eq 0 ] && ok "echoed scopes and tier do not fail the run" || bad "a meta session must exit 0 (rc=$rc)" "$(aj "$TT/ev-meta" 'a')"
RUN_CRED="$METACRED" run_h "$TT/ev-keyedshort" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-keyedshort"
[ $rc -eq 1 ] && ok "a short value under a token key is still a secret" || bad "a keyedshort session must exit 1 (rc=$rc)" "$(aj "$TT/ev-keyedshort" 'a')"
grep -rqF short-r8x "$TT/ev-keyedshort" && bad "the keyed short value reaches the evidence" || ok "the keyed short value is redacted"

# --- 21. A child that moves to its own process group is killed with the session.
run_h "$TT/ev-escape" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-escape"
[ -e "$SEEN/escaped" ] && ok "the escape stub's child left the session's process group" \
    || bad "the escape stub's child never left its process group"
sleep 3
if [ -e "$WATCH/late-pgrp.txt" ]; then bad "a child in its own process group wrote after the check"
else ok "every process in the session is killed when it ends"; fi
rm -f "$WATCH/late-pgrp.txt"

# --- 22. The toy test runs isolated: a usercustomize.py in the throwaway HOME cannot fake it.
EV="$TT/ev-usercust"
run_h "$EV" "${PL[@]}" --watch "$WATCH" --exec "$TT/stub-usercust"
[ $rc -eq 1 ] && ok "a usercustomize.py patching calc.add does not pass the run" \
    || bad "a usercust session must exit 1 (rc=$rc)" "$(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["toy_test_exit"]')" = 1 ] && ok "toy_test_exit records the unpatched failure" \
    || bad "toy_test_exit must be 1 (usercust)" "$(aj "$EV" 'a')"
[ -z "$(ls -A "$RUNTMP")" ] && ok "the new cases leave nothing under the temp root" || bad "runs left files under the temp root" "$(ls -A "$RUNTMP")"

# --- 23. The codex path. Codex's login is $CODEX_HOME/auth.json; its plugin command is
# `plugin add`; the session is `codex exec`, and a skill counts when the session's rollout
# shows it injected from the installed plugin cache. The stub's rollout also carries the
# account id, as a real one does, so copying the rollout whole would leak it.
CTOKEN="fake-codex-token-$$-$RANDOM"
CACCT="acct-$$-$RANDOM-0123456789abcdef"
CCRED="$TT/secret/auth.json"
CSTAMP="2026-10-23T19:00:00.123456Z"
printf '{"auth_mode":"chatgpt","tokens":{"access_token":"%s","account_id":"%s"},"last_refresh":"%s"}\n' \
    "$CTOKEN" "$CACCT" "$CSTAMP" > "$CCRED"
mkcodex() {  # $1 = mode: cdocs cfail cwatch cforeign cswapped cother cleak ctestvault csorted cmissing
    local f="$TT/codex-$1"
    cat > "$f" <<'EOF'
#!/usr/bin/env bash
MODE=@MODE@; SEEN=@SEEN@; WATCH=@WATCH@
case "${1:-}" in
  --version) echo "codex-cli 9.9.9-stub"; exit 0 ;;
  plugin)
    case "${2:-} ${3:-}" in
      "marketplace add") mkdir -p "$CODEX_HOME"; printf '%s\n' "$4" >> "$CODEX_HOME/markets.txt"; exit 0 ;;
      "add "*) if [ "${3:-}" = install ]; then exit 3; fi
               d="$CODEX_HOME/plugins/cache/${3#*@}/${3%@*}/1.0.0"
               for s in brainstorming planning-projects executing-plans; do
                 mkdir -p "$d/skills/$s"; printf '# %s\n' "$s" > "$d/skills/$s/SKILL.md"; done
               echo "added $3"; exit 0 ;;
    esac
    exit 3 ;;
  exec)
    printf '%s\n' "$HOME" > "$SEEN/session-home"; printf '%s\n' "$PWD" > "$SEEN/session-cwd"
    printf '%s\n' "$@" > "$SEEN/session-args"; env > "$SEEN/session-env"
    python3 -c 'import os,sys;print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$CODEX_HOME/auth.json" > "$SEEN/cred-mode" 2>&1
    acct="$(python3 -c 'import json,os;print(json.load(open(os.environ["CODEX_HOME"]+"/auth.json"))["tokens"]["account_id"])')"
    r="$CODEX_HOME/sessions/2026/10/23"; mkdir -p "$r"; R="$r/rollout-stub.jsonl"
    printf '{"type":"session_meta","payload":{"creator_account_id":"%s","cwd":"%s"}}\n' "$acct" "$PWD" > "$R"
    cache="$CODEX_HOME/plugins/cache/staged-planning/planning/1.0.0"
    [ "$MODE" = cforeign ] && cache="$CODEX_HOME/plugins/cache/../sessions/elsewhere"
    [ "$MODE" = cother ] && cache="$CODEX_HOME/plugins/cache/staged-planning/other-plugin/1.0.0"
    order="brainstorming planning-projects executing-plans"
    [ "$MODE" = csorted ] && order="brainstorming executing-plans planning-projects"
    [ "$MODE" = cmissing ] && order="brainstorming planning-projects"
    names="$order"
    [ "$MODE" = cswapped ] && names="planning-projects executing-plans brainstorming"
    set -- $names
    for s in $order; do
      n="$1"; shift
      python3 -c 'import json,sys; n,p=sys.argv[1:3]; print(json.dumps({"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"<skill>\n<name>"+n+"</name>\n<path>"+p+"</path>\nbody\n</skill>"}]}}))' \
        "planning:$n" "$cache/skills/$s/SKILL.md" >> "$R"
    done
    printf '{"type":"thread.started","thread_id":"t1"}\n'
    stamp="$(python3 -c 'import json,os;print(json.load(open(os.environ["CODEX_HOME"]+"/auth.json"))["last_refresh"])')"
    printf '{"type":"item.completed","item":{"type":"agent_message","text":"at %s"}}\n' "$stamp"
    if [ "$MODE" = cleak ]; then
      python3 -c 'import json,os;t=json.load(open(os.environ["CODEX_HOME"]+"/auth.json"))["tokens"]["access_token"];print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"token "+t}}))'
    fi
    if [ "$MODE" = cfail ]; then echo started > "$SEEN/session-started"; exit 7; fi
    case "$MODE" in ctestvault) d="$HOME/test-vault/plans" ;; *) d="$PWD/docs/plans" ;; esac
    mkdir -p "$d"; printf '# Light Plan: fix add\n' > "$d/2026-10-23-calc-plan.md"
    [ "$MODE" = cwatch ] && printf 'oops\n' > "$WATCH/codex-leaked.txt"
    printf 'def add(a, b):\n    return a + b\n' > calc.py
    printf '{"type":"turn.completed"}\n'
    exit 0 ;;
esac
exit 3
EOF
    sed -i.bak -e "s|@MODE@|$1|" -e "s|@SEEN@|$SEEN|" -e "s|@WATCH@|$WATCH|" "$f" && rm -f "$f.bak"
    chmod +x "$f"
}
for m in cdocs cfail cwatch cforeign cswapped cother cleak ctestvault csorted cmissing; do mkcodex "$m"; done
EV="$TT/ev-cdocs"
RUN_CRED="$CCRED" run_h "$EV" "${PL[@]}" --host codex --watch "$WATCH" --model stub-model --exec "$TT/codex-cdocs"
[ $rc -eq 0 ] && ok "the codex docs stub exits 0, its auth file's last_refresh in the output not taken for a secret" \
    || bad "the codex docs stub must exit 0 (rc=$rc)" "$err $(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["records_under"]')" = docs ] && ok "codex: records_under is docs" || bad "codex: records_under must be docs" "$(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["skills_seen"]')" = "['planning:brainstorming', 'planning:planning-projects', 'planning:executing-plans']" ] \
    && ok "codex: skills_seen comes from the rollout's injections from the cache" || bad "codex: skills_seen is wrong" "$(aj "$EV" 'a')"
case "$(aj "$EV" 'a["host_version"]')" in *9.9.9-stub*) ok "codex: host_version comes from codex --version" ;;
    *) bad "codex: host_version is wrong" "$(aj "$EV" 'a')" ;; esac
[ "$(cat "$SEEN/cred-mode" 2>/dev/null)" = 0o600 ] && ok "codex: the auth copy is mode 600 in \$CODEX_HOME" \
    || bad "codex: the auth copy must be mode 600" "$(cat "$SEEN/cred-mode" 2>/dev/null)"
SH="$(cat "$SEEN/session-home" 2>/dev/null)"
grep -qx "CODEX_HOME=$SH/.codex" "$SEEN/session-env" 2>/dev/null && ok "codex: CODEX_HOME is \$HOME/.codex in the throwaway HOME" \
    || bad "codex: CODEX_HOME must be \$HOME/.codex" "$(grep CODEX "$SEEN/session-env" 2>/dev/null)"
grep -q '^CLAUDE_CONFIG_DIR=' "$SEEN/session-env" 2>/dev/null && bad "codex: the session must not get CLAUDE_CONFIG_DIR" \
    || ok "codex: the session gets no Claude config dir"
ARGS="$(cat "$SEEN/session-args" 2>/dev/null)"
for want in exec --json workspace-write -C "$(cat "$SEEN/session-cwd" 2>/dev/null)" -m stub-model \
            '$planning:brainstorming' '$planning:planning-projects' '$planning:executing-plans'; do
    grep -qxF -- "$want" <<<"$ARGS" || grep -qF -- "$want" <<<"$ARGS" || bad "codex: the session args lack '$want'" "$ARGS"
done
grep -qx -- --dangerously-bypass-hook-trust <<<"$ARGS" && bad "codex: hooks must stay untrusted" || ok "codex: hook trust is never bypassed"
grep -qx -- --ephemeral <<<"$ARGS" && bad "codex: --ephemeral writes no rollout, so no skill could be seen" \
    || ok "codex: the session is not --ephemeral, so its rollout records the skills"
grep -qF 'skills=present' "$TT/h.out" && ok "codex: the verdict says the skills are present, not in order" \
    || bad "codex: the verdict must print skills=present" "$(cat "$TT/h.out")"
grep -qF -- "$CACCT" "$EV/transcript.jsonl" && bad "codex: the transcript carries the rollout's account id" \
    || ok "codex: the rollout is read for skills only, never copied whole"
grep -qF "$CTOKEN" "$EV/transcript.jsonl" "$EV/host.log" && bad "codex: the evidence carries the token" || ok "codex: no token in the evidence"
[ -z "$(ls -A "$RUNTMP")" ] && ok "codex: the throwaway root is removed" || bad "codex: the throwaway root must be removed" "$(ls -A "$RUNTMP")"

EV="$TT/ev-cfail"
RUN_CRED="$CCRED" run_h "$EV" "${PL[@]}" --host codex --watch "$WATCH" --exec "$TT/codex-cfail"
[ $rc -eq 1 ] && [ -f "$SEEN/session-started" ] && ok "codex: a session failing midway fails the run" \
    || bad "codex: a failing session must exit 1 after it started (rc=$rc)" "$err"
[ -z "$(ls -A "$RUNTMP")" ] && ok "codex: the trap removes the throwaway HOME, auth copy included, after a failure" \
    || bad "codex: a failed run left the throwaway root" "$(find "$RUNTMP" | head)"

EV="$TT/ev-cwatch"
RUN_CRED="$CCRED" run_h "$EV" "${PL[@]}" --host codex --watch "$WATCH" --exec "$TT/codex-cwatch"
[ $rc -eq 1 ] && grep -q 'codex-leaked.txt' <<<"$(aj "$EV" 'a["outside_changes"]')" \
    && ok "codex: a write outside the throwaway HOME lands in outside_changes" \
    || bad "codex: an outside write must fail the run and be listed (rc=$rc)" "$(aj "$EV" 'a')"
rm -f "$WATCH/codex-leaked.txt"

EV="$TT/ev-cforeign"
RUN_CRED="$CCRED" run_h "$EV" "${PL[@]}" --host codex --watch "$WATCH" --exec "$TT/codex-cforeign"
[ $rc -eq 1 ] && [ "$(aj "$EV" 'a["skills_seen"]')" = "[]" ] \
    && ok "codex: a skill injected from outside the plugin cache (via ..) does not count" \
    || bad "codex: foreign injections must not count (rc=$rc)" "$(aj "$EV" 'a')"
EV="$TT/ev-cswapped"
RUN_CRED="$CCRED" run_h "$EV" "${PL[@]}" --host codex --watch "$WATCH" --exec "$TT/codex-cswapped"
[ $rc -eq 1 ] && [ "$(aj "$EV" 'a["skills_seen"]')" = "[]" ] \
    && ok "codex: a skill name injected with another skill's SKILL.md does not count" \
    || bad "codex: a name must match its SKILL.md's folder (rc=$rc)" "$(aj "$EV" 'a')"
EV="$TT/ev-cother"
RUN_CRED="$CCRED" run_h "$EV" "${PL[@]}" --host codex --watch "$WATCH" --exec "$TT/codex-cother"
[ $rc -eq 1 ] && [ "$(aj "$EV" 'a["skills_seen"]')" = "[]" ] \
    && ok "codex: a planning: skill injected from another plugin's cache dir does not count" \
    || bad "codex: the plugin part of a name must match its cache dir (rc=$rc)" "$(aj "$EV" 'a')"
EV="$TT/ev-cleak"
RUN_CRED="$CCRED" run_h "$EV" "${PL[@]}" --host codex --watch "$WATCH" --exec "$TT/codex-cleak"
[ $rc -eq 1 ] && grep -q 'exposed the credentials' <<<"$(aj "$EV" 'a.get("error","")')" \
    && grep -qF '<redacted>' "$EV/transcript.jsonl" \
    && ok "codex: a session that prints the auth token fails and the token is redacted" \
    || bad "codex: a printed token must be redacted and fail the run (rc=$rc)" "$(aj "$EV" 'a')"

# Codex injects mentioned skills sorted by name: order is not judged there, presence is.
RUN_CRED="$CCRED" run_h "$TT/ev-csorted" "${PL[@]}" --host codex --watch "$WATCH" --exec "$TT/codex-csorted"
[ $rc -eq 0 ] && ok "codex: the three skills injected in name order pass" || bad "codex: name-ordered injections must pass (rc=$rc)" "$(aj "$TT/ev-csorted" 'a')"
RUN_CRED="$CCRED" run_h "$TT/ev-cmissing" "${PL[@]}" --host codex --watch "$WATCH" --exec "$TT/codex-cmissing"
[ $rc -eq 1 ] && ok "codex: a run missing one of the three skills fails" || bad "codex: a missing skill must fail (rc=$rc)" "$(aj "$TT/ev-cmissing" 'a')"

EV="$TT/ev-ctv"
RUN_CRED="$CCRED" run_h "$EV" "${PL[@]}" --host codex --test-vault "$TT/vault-src" --expect test-vault \
    --watch "$WATCH" --exec "$TT/codex-ctestvault"
[ $rc -eq 0 ] && [ "$(aj "$EV" 'a["records_under"]')" = test-vault ] && ok "codex: a plan in the test vault passes --expect test-vault" \
    || bad "codex: test-vault run must pass (rc=$rc)" "$(aj "$EV" 'a')"
grep -qxF -- "$(cat "$SEEN/session-cwd" 2>/dev/null)/.git" "$SEEN/session-args" 2>/dev/null \
    && ok "codex: the toy's .git is added as a writable dir, so the session can commit" \
    || bad "codex: --add-dir must name <toy>/.git" "$(cat "$SEEN/session-args" 2>/dev/null)"
grep -qxF -- "$(cat "$SEEN/session-home" 2>/dev/null)/test-vault" "$SEEN/session-args" 2>/dev/null && ok "codex: the test vault is added as a writable dir" \
    || bad "codex: --add-dir must name the test vault" "$(cat "$SEEN/session-args" 2>/dev/null)"
run_h "$TT/ev-chf" "${PL[@]}" --host codex --home-file .codex/auth.json="$TT/home-file.json" --watch "$WATCH" --exec "$TT/codex-cdocs"
[ $rc -eq 2 ] && ok "codex: --home-file cannot place the auth file" || bad "codex: --home-file .codex/auth.json must exit 2 (rc=$rc)" "$err"
run_h "$TT/ev-chf2" "${PL[@]}" --host codex --home-file .codex/./auth.json="$TT/home-file.json" --watch "$WATCH" --exec "$TT/codex-cdocs"
[ $rc -eq 2 ] && ok "codex: --home-file .codex/./auth.json cannot place it either" || bad "codex: a /./ path must not slip past the auth check (rc=$rc)" "$err"

# --- 24. The cursor path. Cursor's login is $HOME/.config/cursor/auth.json; a plugin is a
# dir under $HOME/.cursor/plugins/local/<id>; the session is `cursor-agent -p --trust
# --force --output-format stream-json`. A skill counts when the transcript shows a successful
# readToolCall of that skill's SKILL.md under the installed plugin dir.
KTOKEN="fake-cursor-token-$$-$RANDOM"
KCRED="$TT/secret/cursor-auth.json"
printf '{"accessToken":"%s","refreshToken":"%s-refresh"}\n' "$KTOKEN" "$KTOKEN" > "$KCRED"
KPLUG="$TT/cursor-plugin"
mkdir -p "$KPLUG/.cursor-plugin"; printf '{"name":"planning"}\n' > "$KPLUG/.cursor-plugin/plugin.json"
for s in brainstorming planning-projects executing-plans; do
    mkdir -p "$KPLUG/skills/$s"; printf -- '---\nname: %s\n---\nbody\n' "$s" > "$KPLUG/skills/$s/SKILL.md"
done
mkcursor() {  # $1 = mode: kdocs (the good run) kforeign (skills read from outside the plugin dir)
    local f="$TT/cursor-$1"
    cat > "$f" <<'EOF'
#!/usr/bin/env bash
MODE=@MODE@; SEEN=@SEEN@
case "${1:-}" in
  --version) echo "2026.10.16-stub"; exit 0 ;;
  -p)
    printf '%s\n' "$HOME" > "$SEEN/session-home"; printf '%s\n' "$PWD" > "$SEEN/session-cwd"
    printf '%s\n' "$@" > "$SEEN/session-args"; env > "$SEEN/session-env"
    python3 -c 'import os,sys;print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$HOME/.config/cursor/auth.json" > "$SEEN/cred-mode" 2>&1
    ls -A "$HOME/.cursor/plugins/local" > "$SEEN/local-ls" 2>&1
    [ -f "$HOME/.cursor/plugins/local/planning/.cursor-plugin/plugin.json" ] && echo yes > "$SEEN/plugin-placed" || echo no > "$SEEN/plugin-placed"
    printf '{"type":"system","subtype":"init","cwd":"%s"}\n' "$PWD"
    base="$HOME/.cursor/plugins/local/planning/skills"
    if [ "$MODE" = kforeign ]; then
      base="$HOME/.agents/skills"
      for s in brainstorming planning-projects executing-plans; do mkdir -p "$base/$s"; printf 'x\n' > "$base/$s/SKILL.md"; done
    fi
    n=0
    for s in brainstorming planning-projects executing-plans; do
      n=$((n+1)); p="$base/$s/SKILL.md"
      [ -f "$p" ] || continue
      printf '{"type":"tool_call","subtype":"started","call_id":"c%s","tool_call":{"readToolCall":{"args":{"path":"%s"}}}}\n' "$n" "$p"
      printf '{"type":"tool_call","subtype":"completed","call_id":"c%s","tool_call":{"readToolCall":{"args":{"path":"%s"},"result":{"success":{"path":"%s"}}}}}\n' "$n" "$p" "$p"
    done
    mkdir -p "$PWD/docs/plans"; printf '# Light Plan: fix add\n' > "$PWD/docs/plans/2026-10-24-calc-plan.md"
    printf 'def add(a, b):\n    return a + b\n' > calc.py
    printf '{"type":"result","subtype":"success","is_error":false}\n'
    exit 0 ;;
esac
exit 3
EOF
    sed -i.bak -e "s|@MODE@|$1|" -e "s|@SEEN@|$SEEN|" "$f" && rm -f "$f.bak"
    chmod +x "$f"
}
for m in kdocs kforeign; do mkcursor "$m"; done
EV="$TT/ev-kdocs"
RUN_CRED="$KCRED" run_h "$EV" --plugin "$KPLUG" planning --host cursor --watch "$WATCH" --model stub-model --exec "$TT/cursor-kdocs"
[ $rc -eq 0 ] && ok "cursor: the docs stub exits 0" || bad "cursor: the docs stub must exit 0 (rc=$rc)" "$err $(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["records_under"]')" = docs ] && ok "cursor: records_under is docs" || bad "cursor: records_under must be docs" "$(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["skills_seen"]')" = "['planning:brainstorming', 'planning:planning-projects', 'planning:executing-plans']" ] \
    && ok "cursor: skills_seen comes from the reads of the installed SKILL.md files" || bad "cursor: skills_seen is wrong" "$(aj "$EV" 'a')"
case "$(aj "$EV" 'a["host_version"]')" in *2026.10.16-stub*) ok "cursor: host_version comes from cursor-agent --version" ;;
    *) bad "cursor: host_version is wrong" "$(aj "$EV" 'a')" ;; esac
[ "$(cat "$SEEN/cred-mode" 2>/dev/null)" = 0o600 ] && ok "cursor: the auth copy is mode 600 at \$HOME/.config/cursor/auth.json" \
    || bad "cursor: the auth copy must be mode 600 at .config/cursor/auth.json" "$(cat "$SEEN/cred-mode" 2>/dev/null)"
[ "$(cat "$SEEN/plugin-placed" 2>/dev/null)" = yes ] && [ "$(cat "$SEEN/local-ls" 2>/dev/null)" = planning ] \
    && ok "cursor: --plugin <dir> planning is copied to \$HOME/.cursor/plugins/local/planning" \
    || bad "cursor: the plugin must sit at .cursor/plugins/local/planning" "$(cat "$SEEN/local-ls" 2>/dev/null)"
ARGS="$(cat "$SEEN/session-args" 2>/dev/null)"
for want in -p --trust --force --output-format stream-json --model stub-model 'brainstorming skill' 'planning-projects skill' 'executing-plans skill'; do
    grep -qF -- "$want" <<<"$ARGS" || bad "cursor: the session args lack '$want'" "$ARGS"
done
grep -q '^CLAUDE_CONFIG_DIR=' "$SEEN/session-env" 2>/dev/null && bad "cursor: the session must not get CLAUDE_CONFIG_DIR" \
    || ok "cursor: the session gets no Claude config dir"
grep -qF "$KTOKEN" "$SEEN/session-env" "$SEEN/session-args" 2>/dev/null && bad "cursor: the token reached the session's env or args" \
    || ok "cursor: the token is in neither the session's env nor its args"
[ -z "$(ls -A "$RUNTMP")" ] && ok "cursor: the throwaway root is removed" || bad "cursor: the throwaway root must be removed" "$(ls -A "$RUNTMP")"
EV="$TT/ev-kforeign"
RUN_CRED="$KCRED" run_h "$EV" --plugin "$KPLUG" planning --host cursor --watch "$WATCH" --exec "$TT/cursor-kforeign"
[ $rc -eq 1 ] && [ "$(aj "$EV" 'a["skills_seen"]')" = "[]" ] \
    && ok "cursor: a SKILL.md read from outside the installed plugin dir does not count" \
    || bad "cursor: foreign skill reads must not count (rc=$rc)" "$(aj "$EV" 'a')"
run_h "$TT/ev-khf" --plugin "$KPLUG" planning --host cursor --home-file .config/cursor/auth.json="$TT/home-file.json" --watch "$WATCH" --exec "$TT/cursor-kdocs"
[ $rc -eq 2 ] && ok "cursor: --home-file cannot place the auth file" || bad "cursor: --home-file .config/cursor/auth.json must exit 2 (rc=$rc)" "$err"
run_h "$TT/ev-kbadid" --plugin "$KPLUG" .. --host cursor --watch "$WATCH" --exec "$TT/cursor-kdocs"
[ $rc -eq 2 ] && ok "cursor: a plugin id of '..' is refused" || bad "cursor: --plugin <dir> .. must exit 2 (rc=$rc)" "$err"

# --- 25. The opencode path. OpenCode's login is $HOME/.local/share/opencode/auth.json; the
# session is `opencode run -m <model>`, one prompt per skill, each naming its skill. Its
# plugin install shape is not recorded yet, so --plugin exits 2 and these runs carry none.
# `opencode run` can refuse a write and still exit 0: records_under is read
# from disk, never from the exit code.
OTOKEN="fake-opencode-token-$$-$RANDOM"
OCRED="$TT/secret/opencode-auth.json"
printf '{"openai":{"type":"oauth","access":"%s","refresh":"%s-refresh","expires":1}}\n' "$OTOKEN" "$OTOKEN" > "$OCRED"
mkopencode() {  # $1 = mode: opre (a preamble, exit 0, no records) odocs (writes the plan) oforeign (skills served from outside the plugin copy) oerror (failed skill calls)
    local f="$TT/opencode-$1"
    cat > "$f" <<'EOF'
#!/usr/bin/env bash
MODE=@MODE@; SEEN=@SEEN@
case "${1:-}" in
  --version) echo "1.19.3-stub"; exit 0 ;;
  run)
    n=$(( $(cat "$SEEN/steps" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$SEEN/steps"
    printf '%s\n' "$HOME" > "$SEEN/session-home"; printf '%s\n' "$PWD" > "$SEEN/session-cwd"
    printf '%s\n' "$@" > "$SEEN/session-args-$n"; env > "$SEEN/session-env"
    python3 -c 'import os,sys;print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$HOME/.local/share/opencode/auth.json" > "$SEEN/cred-mode" 2>&1
    cp "$HOME/.config/opencode/opencode.json" "$SEEN/oc-config" 2>/dev/null || echo none > "$SEEN/oc-config"
    ( cd "$HOME" && find .local/share/opencode-plugins .config/opencode/commands -type f 2>/dev/null | sort ) > "$SEEN/oc-files"
    printf '{"type":"text","part":{"type":"text","text":"I need access to a directory outside the workspace."}}\n'
    sk=brainstorming; [ "$n" = 2 ] && sk=planning-projects; [ "$n" = 3 ] && sk=executing-plans
    dir="$HOME/.local/share/opencode-plugins/planning/skills/$sk"; st=completed
    [ "$MODE" = oforeign ] && { dir="$HOME/.agents/skills/$sk"; mkdir -p "$dir"; printf 'x\n' > "$dir/SKILL.md"; }
    [ "$MODE" = oerror ] && st=error
    if [ "$MODE" != opre ]; then
      printf '{"type":"tool_use","part":{"type":"tool","tool":"skill","state":{"status":"%s","input":{"name":"%s"},"metadata":{"name":"%s","dir":"%s"}}}}\n' "$st" "$sk" "$sk" "$dir"
    fi
    if [ "$MODE" != opre ] && [ "$n" = 2 ]; then
      mkdir -p "$PWD/docs/plans"; printf '# Light Plan: fix add\n' > "$PWD/docs/plans/2026-10-24-calc-plan.md"
    fi
    [ "$MODE" != opre ] && [ "$n" = 3 ] && printf 'def add(a, b):\n    return a + b\n' > calc.py
    exit 0 ;;
esac
exit 3
EOF
    sed -i.bak -e "s|@MODE@|$1|" -e "s|@SEEN@|$SEEN|" "$f" && rm -f "$f.bak"
    chmod +x "$f"
}
for m in opre odocs oforeign oerror; do mkopencode "$m"; done
RUN_CRED="$OCRED" run_h "$TT/ev-onomodel" --host opencode --watch "$WATCH" --exec "$TT/opencode-opre"
[ $rc -eq 2 ] && grep -q -- '--model' <<<"$err" && ok "opencode: a run without --model exits 2" \
    || bad "opencode: no --model must exit 2 naming --model (rc=$rc)" "$err"
# Two fixtures in the recorded install shape: a package (package.json with a main module),
# loaded by local path, and a skills-only plugin dir, whose skills/ joins skills.paths.
OCPKG="$TT/ocpkg"; OCDIR="$TT/ocdir"
mkdir -p "$OCPKG/src" "$OCPKG/skills/x" "$OCDIR/skills/y" "$OCDIR/commands"
for s in brainstorming planning-projects executing-plans; do
    mkdir -p "$OCPKG/skills/$s"; printf -- '---\nname: %s\n---\nbody\n' "$s" > "$OCPKG/skills/$s/SKILL.md"
done
printf '{"name": "stub-pkg", "main": "./src/index.ts"}\n' > "$OCPKG/package.json"
printf 'export default {};\n' > "$OCPKG/src/index.ts"
printf -- '---\nname: x\n---\n' > "$OCPKG/skills/x/SKILL.md"
printf -- '---\nname: y\n---\n' > "$OCDIR/skills/y/SKILL.md"
printf 'a command\n' > "$OCDIR/commands/vault-y.md"
OPL=(--plugin "$OCPKG" planning)
RUN_CRED="$OCRED" run_h "$TT/ev-onoplugin" --host opencode --model stub/model --watch "$WATCH" --exec "$TT/opencode-opre"
[ $rc -eq 2 ] && grep -q -- '--plugin' <<<"$err" && ok "opencode: a run with no --plugin exits 2" \
    || bad "opencode: a run with no --plugin must exit 2 (rc=$rc)" "$err"
rm -f "$SEEN/oc-config"
RUN_CRED="$OCRED" run_h "$TT/ev-oplugin" --host opencode --model stub/model "${OPL[@]}" --plugin "$OCDIR" vault-y --watch "$WATCH" --exec "$TT/opencode-opre"
SH="$(cat "$SEEN/session-home" 2>/dev/null)"
python3 - "$SEEN/oc-config" "$SH" <<'PY' && ok "opencode: a package loads by local path and a plugin dir joins skills.paths, both from copies in the HOME" \
    || bad "opencode: opencode.json is not in the recorded install shape" "$(cat "$SEEN/oc-config" 2>/dev/null)"
import json, sys
conf, home = json.load(open(sys.argv[1])), sys.argv[2]
root = home + "/.local/share/opencode-plugins/"
assert conf["plugin"] == [root + "planning/src/index.ts"], conf
assert conf["skills"]["paths"] == [root + "vault-y/skills"], conf
PY
grep -qx '.local/share/opencode-plugins/vault-y/skills/y/SKILL.md' "$SEEN/oc-files" \
    && grep -qx '.local/share/opencode-plugins/vault-y/commands/vault-y.md' "$SEEN/oc-files" \
    && ! grep -q '^.config/opencode/commands/' "$SEEN/oc-files" \
    && ok "opencode: a plugin dir is copied whole; its commands are left to its own installer" \
    || bad "opencode: the plugin dir copy or its commands are wrong" "$(cat "$SEEN/oc-files" 2>/dev/null)"
EV="$TT/ev-opre"
RUN_CRED="$OCRED" run_h "$EV" --host opencode --model stub/model "${OPL[@]}" --watch "$WATCH" --exec "$TT/opencode-opre"
[ "$(aj "$EV" 'a["records_under"]')" = none ] && ok "opencode: a session that exits 0 with no records reads records_under none" \
    || bad "opencode: records_under must be none when nothing was written" "$(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["exit"]')" = 0 ] && ok "opencode: asserts.json records the session's exit 0" || bad "opencode: exit must be 0" "$(aj "$EV" 'a')"
[ $rc -ne 0 ] && ok "opencode: the harness exits non-zero despite the session's exit 0 (rc=$rc)" \
    || bad "opencode: the harness must not trust the session's exit code" "$(cat "$TT/h.out")"
case "$(aj "$EV" 'a["host_version"]')" in *1.19.3-stub*) ok "opencode: host_version comes from opencode --version" ;;
    *) bad "opencode: host_version is wrong" "$(aj "$EV" 'a')" ;; esac
[ "$(cat "$SEEN/cred-mode" 2>/dev/null)" = 0o600 ] && ok "opencode: the auth copy is mode 600 at \$HOME/.local/share/opencode/auth.json" \
    || bad "opencode: the auth copy must be mode 600 at .local/share/opencode/auth.json" "$(cat "$SEEN/cred-mode" 2>/dev/null)"
EV="$TT/ev-odocs"
RUN_CRED="$OCRED" run_h "$EV" --host opencode --model stub/model "${OPL[@]}" --watch "$WATCH" --exec "$TT/opencode-odocs"
[ "$(cat "$SEEN/steps" 2>/dev/null)" = 3 ] && ok "opencode: the flow is three opencode run prompts" \
    || bad "opencode: the flow must be three prompts" "steps=$(cat "$SEEN/steps" 2>/dev/null)"
for n in 1 2 3; do
    A="$(cat "$SEEN/session-args-$n" 2>/dev/null)"
    sk=brainstorming; [ $n = 2 ] && sk=planning-projects; [ $n = 3 ] && sk=executing-plans
    for want in run -m stub/model "$sk skill"; do
        grep -qF -- "$want" <<<"$A" || bad "opencode: prompt $n lacks '$want'" "$A"
    done
    [ $n = 1 ] || grep -qx -- --continue <<<"$A" || bad "opencode: prompt $n must continue the session" "$A"
done
ok "opencode: each prompt names its own skill and the later ones continue the session"
[ "$(aj "$EV" 'a["records_under"]')" = docs ] && ok "opencode: a plan on disk reads records_under docs" \
    || bad "opencode: records_under must be docs when the plan is on disk" "$(aj "$EV" 'a')"
[ "$(aj "$EV" 'a["skills_seen"]')" = "['planning:brainstorming', 'planning:planning-projects', 'planning:executing-plans']" ] \
    && ok "opencode: skills_seen comes from the completed skill calls served from the installed copy" || bad "opencode: skills_seen is wrong" "$(aj "$EV" 'a')"
[ $rc -eq 0 ] && ok "opencode: the docs stub passes once its skills are seen" || bad "opencode: the docs stub must exit 0 (rc=$rc)" "$(cat "$TT/h.out") $(aj "$EV" 'a')"
for m in oforeign oerror; do
    EV="$TT/ev-$m"
    RUN_CRED="$OCRED" run_h "$EV" --host opencode --model stub/model "${OPL[@]}" --watch "$WATCH" --exec "$TT/opencode-$m"
    [ $rc -eq 1 ] && [ "$(aj "$EV" 'a["skills_seen"]')" = "[]" ] \
        && ok "opencode: a skill call that failed or was served from outside the plugin copy does not count ($m)" \
        || bad "opencode: skills_seen must be empty and the run must fail ($m, rc=$rc)" "$(aj "$EV" 'a')"
done
run_h "$TT/ev-ohf" --host opencode --model stub/model "${OPL[@]}" --home-file .local/share/opencode/auth.json="$TT/home-file.json" --watch "$WATCH" --exec "$TT/opencode-opre"
[ $rc -eq 2 ] && ok "opencode: --home-file cannot place the auth file" || bad "opencode: --home-file onto the auth path must exit 2 (rc=$rc)" "$err"
[ -z "$(ls -A "$RUNTMP")" ] && ok "cursor/opencode: no run leaves anything under the temp root" || bad "runs left files under the temp root" "$(ls -A "$RUNTMP")"

echo
echo "passed: $pass   failed: $fail"
[ "$fail" -eq 0 ]
