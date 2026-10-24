#!/usr/bin/env python3
"""Fixture tests for scripts/check-portable.py.

The cases that matter are the ones proving the check REJECTS: a portability check that
only ever passes is indistinguishable from one that reads nothing. So every class is
planted in a throwaway tree and must go red, and the near-misses that must stay green
(this plugin's own ids, placeholders, a noreply address) are planted beside them.

Every fixture is built at run time from fragments, so this file itself holds no home
path, address or foreign id for the check to find.

Stdlib only.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "check-portable.py")

FAILURES = []

# Fragments, joined at run time.
HOME = "/" + "home" + "/someone/x"
MAC_HOME = "/" + "Users" + "/someone/x"
MOUNT = "/" + "mnt" + "/disk/notes"
ADDR = "a.b" + "@" + "c.io"
NOREPLY = "noreply" + "@" + "anthropic.com"
EXAMPLE = "you" + "@" + "example.com"
SSH = "git" + "@" + "github.com:owner/repo.git"
FOREIGN = "acme" + "-tools" + ":" + "lint" + "-helper"
OWN = "planning" + ":" + "code-reviewer"
BAD_ID = "DEC" + "-999"
GOOD_ID = "DEC" + "-SP-001"
PLAIN_ID = "DEC" + "-001"
BAD_TAGGED = "DEC" + "-SP-009"
PLACEHOLDER = "DEC" + "-NNN"
WORD = "va" + "ult"
OTHER_TAG = "DEC" + "-ZZ-009"


def check(ok, msg):
    print(f"  {'ok' if ok else 'FAIL'}: {msg}")
    if not ok:
        FAILURES.append(msg)


def run(root, *args):
    p = subprocess.run([sys.executable, SCRIPT, "--root", root, *args],
                       capture_output=True, text=True, cwd=root)
    return p.returncode, p.stdout, p.stderr


def tree(files):
    root = tempfile.mkdtemp(prefix="portable-")
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return root


def classes(stdout):
    return sorted({line.split(" ", 1)[0] for line in stdout.splitlines() if line.strip()})


def main():
    print("each class goes red on a planted line")
    planted = {
        "home-path": f"see {HOME}\n",
        "home-path ": f"see {MAC_HOME}\n",
        "home-path  ": f"notes live in {MOUNT}\n",
        "email": f"mail {ADDR}\n",
        "plugin-id": f"dispatch `{FOREIGN}` here\n",
        "plugin-id ": f"run /{FOREIGN} now\n",
        "plugin-id  ": f"| stack | {FOREIGN} |\n",
        "plugin-id   ": f'subagent_type: "{FOREIGN}"\n',
        "unregistered-id": f"Honors {BAD_ID}\n",
        "vault-word": f"plans live in the {WORD}\n",
    }
    for cls, line in planted.items():
        root = tree({"docs/decisions.md": f"## {GOOD_ID} — kept\n", "core/a.md": line})
        rc, out, _ = run(root, "core")
        check(rc == 1 and classes(out) == [cls.strip()],
              f"{cls.strip()!r} red on {line.strip()!r} (rc={rc}, got {classes(out)})")
        check(f"{cls.strip()} core/a.md:1" in out, f"{cls.strip()!r} reports <class> <path>:<line>")

    print("a tagged id is registered when its tag heads a register entry; a tag never covers a plain id")
    for line, want in ((f"cite {GOOD_ID}\n", 0), (f"cite {BAD_TAGGED}\n", 0), (f"cite {OTHER_TAG}\n", 1),
                       (f"cite {PLAIN_ID}\n", 1)):
        root = tree({"docs/decisions.md": f"## {GOOD_ID} — kept\n", "core/a.md": line})
        rc, out, _ = run(root, "core")
        check(rc == want, f"{line.strip()!r} with only {GOOD_ID} defined exits {want} (rc={rc}, {out!r})")

    print("near-misses stay green")
    root = tree({
        "docs/decisions.md": f"## {GOOD_ID} — kept\n",
        "core/a.md": (f"dispatch `{OWN}`\nmail {NOREPLY} or {EXAMPLE}\nclone {SSH}\n"
                      f"cite {PLACEHOLDER} or {GOOD_ID}\npath /home/<user>/x and ~/notes\n"
                      "url https://example.org:8080/x and node:path\n"),
    })
    rc, out, _ = run(root, "core")
    check(rc == 0 and out.strip() == "", f"near-misses produce no finding (rc={rc}, out={out!r})")

    print("the vault word is allowed only in the two config docs")
    root = tree({f"docs/{n}": f"a {WORD}\n" for n in ("configuration.md", "records-resolver.md")})
    rc, out, _ = run(root, "docs")
    check(rc == 0, f"configuration.md and records-resolver.md may say the word (rc={rc}, {out!r})")
    root = tree({"core/references/records-resolver.md": f"a {WORD}\n",
                 "core/references/other.md": f"a {WORD}\n"})
    rc, out, _ = run(root, "core")
    check(rc == 1 and out.splitlines() == ["vault-word core/references/other.md:1"],
          f"the shipped core/references/records-resolver.md may say it too, its neighbour "
          f"may not (rc={rc}, {out!r})")

    print("the types Claude Code writes under .claude-plugin/ are skipped; a plugin's own types/ is not")
    root = tree({"plugins/x/.claude-plugin/types/claude-code/index.d.ts": f"a {WORD}\n",
                 "plugins/x/types/own.md": f"a {WORD}\n"})
    rc, out, _ = run(root, "plugins")
    check(rc == 1 and out.splitlines() == ["vault-word plugins/x/types/own.md:1"],
          f"only the plugin's own types/ is scanned (rc={rc}, {out!r})")

    print("a file with NUL bytes, invalid UTF-8 or a UTF-16 BOM is scanned, not skipped")
    for name, data in (("nul.bin", b"x\x00\n" + HOME.encode()),
                       ("latin.md", b"x\xff\n" + HOME.encode()),
                       ("u16.md", ("x\n" + HOME).encode("utf-16"))):
        root = tree({})
        os.makedirs(os.path.join(root, "core"))
        with open(os.path.join(root, "core", name), "wb") as fh:
            fh.write(data)
        rc, out, err = run(root, "core")
        check(rc == 1 and out.splitlines() == [f"home-path core/{name}:2"],
              f"{name}: a home path is found (rc={rc}, {out!r}, {err!r})")

    print("a symlink is never followed; its link text is scanned as one line of its own path")
    root = tree({"outside/a.md": f"{HOME}\n", f"{WORD}/b.md": f"{HOME}\n", "core/ok.md": "clean\n"})
    os.symlink(HOME, os.path.join(root, "core", "link"))
    os.symlink(os.path.join("..", "outside", "a.md"), os.path.join(root, "core", "flink"))
    os.symlink(os.path.join("..", "outside"), os.path.join(root, "core", "dlink"))
    os.symlink(os.path.join("..", WORD), os.path.join(root, "core", "wlink"))
    rc, out, err = run(root, "core")
    check(rc == 1 and sorted(out.splitlines()) == ["home-path core/link:1", "vault-word core/wlink:1"],
          f"link text is the content; targets are not read (rc={rc}, {out!r}, {err!r})")

    print("--json counts per class")
    root = tree({"core/a.md": f"{HOME}\n{HOME}\n{ADDR}\n"})
    rc, out, _ = run(root, "--json", "core")
    data = json.loads(out)
    check(data["trees"] == ["core"] and data["counts"].get("home-path") == 2
          and data["counts"].get("email") == 1, f"--json shape and counts ({data})")

    print("ratchet")
    root = tree({"core/a.md": f"{HOME}\n{ADDR}\n"})
    base = os.path.join(root, "baseline.txt")
    rc, _, _ = run(root, "--write-baseline", base, "core")
    check(rc == 0 and os.path.exists(base), "--write-baseline writes the file")
    rc, out, _ = run(root, "--ratchet", base, "--exact", "core")
    check(rc == 0, f"unchanged tree passes --ratchet --exact (rc={rc}, {out!r})")
    with open(os.path.join(root, "core", "b.md"), "w", encoding="utf-8") as fh:
        fh.write(f"{HOME}\n")
    rc, out, _ = run(root, "--ratchet", base, "--exact", "core")
    check(rc == 1, f"one planted finding over the ceiling fails (rc={rc})")
    rc, _, _ = run(root, "--ratchet", base, "core")
    check(rc == 1, f"over the ceiling fails without --exact too (rc={rc})")
    os.remove(os.path.join(root, "core", "b.md"))
    with open(os.path.join(root, "core", "a.md"), "w", encoding="utf-8") as fh:
        fh.write(f"{HOME}\n")
    rc, out, _ = run(root, "--ratchet", base, "--exact", "core")
    check(rc == 1 and "STALE email core/a.md 0 < 1" in out, f"a fallen count is STALE and fails --exact (rc={rc}, {out!r})")
    rc, out, _ = run(root, "--ratchet", base, "core")
    check(rc == 0 and "STALE email core/a.md 0 < 1" in out, f"STALE alone passes without --exact (rc={rc}, {out!r})")
    os.makedirs(os.path.join(root, "docs"), exist_ok=True)
    rc, _, _ = run(root, "--ratchet", base, "core", "docs")
    check(rc == 2, f"a tree list different from the baseline's exits 2 (rc={rc})")

    print("bare is strict, and a stray baseline is refused")
    def every_tree(text):
        files = {f"{t}/x.md": "clean\n" for t in ("core", "hosts", "build", "scripts", "docs",
                                                   "plugins")}
        files["README.md"] = "clean\n"
        files["core/a.md"] = text
        return tree(files)
    root = every_tree("clean\n")
    rc, out, err = run(root)
    check(rc == 0, f"a clean tree passes the bare run (rc={rc}, {out!r}, {err!r})")
    root = every_tree(f"{HOME}\n")
    rc, out, _ = run(root)
    check(rc == 1 and "core/a.md" in out, f"one finding fails the bare run (rc={rc}, {out!r})")
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    rc, _, _ = run(root, "--write-baseline", os.path.join(root, "scripts", "portable-baseline.txt"),
                   "core", "hosts", "build", "scripts", "docs", "plugins", "README.md")
    rc, out, err = run(root)
    check(rc == 2 and "portable-baseline.txt" in err,
          f"a baseline file beside the bare run is refused, not obeyed (rc={rc}, {err!r})")

    print("--list prints findings only")
    root = tree({"core/a.md": f"{HOME}\n"})
    rc, out, _ = run(root, "--list", "core")
    check(out.splitlines() == ["home-path core/a.md:1"], f"--list output ({out!r})")

    new_cases()

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S)")
        return 1
    print("\nall check-portable cases passed")
    return 0


def counts_for(files, *trees):
    root = tree(files)
    rc, out, err = run(root, "--json", *(trees or ("core",)))
    try:
        return rc, json.loads(out)["counts"], err
    except ValueError:
        return rc, {}, err


def red_lines(cls, lines):
    for line in lines:
        root = tree({"docs/decisions.md": f"## {GOOD_ID} — kept\n", "core/a.md": line + "\n"})
        rc, out, _ = run(root, "--list", "core")
        check(classes(out) == [cls], f"{cls} red on {line!r} (got {out!r})")


def green_lines(lines):
    root = tree({"docs/decisions.md": f"## {GOOD_ID} — kept\n", "core/a.md": "\n".join(lines) + "\n"})
    rc, out, _ = run(root, "core")
    check(rc == 0 and out.strip() == "", f"near-misses stay green (rc={rc}, out={out!r})")


def new_cases():
    print("home-path: every machine-home and mount form, with or without a trailing slash")
    home_bare = "/" + "home" + "/someone"
    mac_bare = "/" + "Users" + "/someone"
    root_bare = "/" + "root"
    win_json = "C:" + "\\\\" + "Users" + "\\\\" + "someone"
    red_lines("home-path", [
        f"see {home_bare}", f'path "{home_bare}"', f"in {home_bare} today",
        f"see {mac_bare}", f'path "{mac_bare}"', f"in {mac_bare} today",
        f"as {root_bare}", f'cd "{root_bare}"', f"in {root_bare} today",
        "see /" + "var/home/someone", "see /" + "run/media/someone/disk",
        "see /" + "Volumes/disk", f'"dir": "{win_json}"',
        "see /" + "media/disk", "see /" + "mnt/disk",
    ])
    green_lines(["see ~/someone/notes", "see $HOME/notes", "see ${HOME}/notes", "src/root and /rootfs"])

    print("email: only the named service addresses and the reserved domains pass")
    at = "@"
    red_lines("email", [
        "git" + at + "corp.io", "noreply" + at + "corp.io", "user" + at + "localhost",
        "x" + at + "corp.internal", "1+handle" + at + "users.noreply.github.com",
        "_alice" + at + "gmail.com_", "alice" + at + "gmail.com_", "mail alice" + at + "gmail.com_ now",
    ])
    green_lines([
        "git" + at + "github.com:o/r.git", "git" + at + "gitlab.com:o/r", "git" + at + "bitbucket.org:o/r",
        "noreply" + at + "anthropic.com", "a" + at + "example.com", "a" + at + "mail.example.org",
        "a" + at + "example.net", "a" + at + "x.test", "a" + at + "x.example", "a" + at + "x.invalid",
        "a" + at + "x.localhost", "react" + at + "18.3.1", "uses: actions/checkout" + at + "v4",
    ])

    print("plugin-id: Skill()/Agent() calls and unquoted YAML keys")
    red_lines("plugin-id", [
        f"call Skill({FOREIGN}) now", f"call `Skill({FOREIGN})` now", f"call Agent({FOREIGN})",
        f"subagent_type: {FOREIGN}", f"agent: {FOREIGN}", f"  - agent: {FOREIGN}",
    ])
    green_lines([f"call Skill({OWN})", f"subagent_type: {OWN}", f"agent: {OWN}",
                 f"the {FOREIGN} agent in prose"])

    print("plugin-id: this plugin's install identity under another marketplace's name")
    ident = "planning" + at   # built at run time, so this file holds no foreign identity
    red_lines("plugin-id", [f'IDENTITY = "{ident}other-market"', f"add `{ident}other-market` here",
                            f"codex plugin add {ident}other-market --json"])
    green_lines([f"codex plugin add {ident}staged-planning", f"identity: {ident}example-ports",
                 f"an undeclared copy reads {ident}local",
                 "user.email=t" + at + "t", "`lib" + at + "version`", f"mail {ident}corp.example"])

    print("vault-word: the plural too")
    red_lines("vault-word", [f"the {WORD}s hold"])

    print("ip-address: a real host's address, not a documentation one")
    o = "."   # built at run time, so this file holds no address
    red_lines("ip-address", [f"ssh 10{o}1{o}2{o}3 now", f"host 192{o}168{o}1{o}20:22",
                             f"at 8{o}8{o}8{o}8.", f"(172{o}16{o}0{o}9)"])
    green_lines([f"see 192{o}0{o}2{o}10", f"see 198{o}51{o}100{o}7", f"see 203{o}0{o}113{o}5",
                 f"bind 127{o}0{o}0{o}1", f"version 0{o}44{o}0{o}0", f"mask 255{o}255{o}255{o}0",
                 f"v1{o}2{o}3", f"tag 1{o}2{o}3{o}4{o}5", f"not 300{o}1{o}1{o}1"])

    print("unregistered-id: long numbers and plain GDEC ids")
    red_lines("unregistered-id", ["cite BL" + "-1234", "cite DEC" + "-1000", "cite GDEC" + "-123",
                                  "cite GDEC" + "-ANDROID-001"])
    root = tree({"docs/backlog.md": "## BL" + "-SP-004 — open\n", "core/a.md": "cite BL" + "-SP-003\n"})
    rc, out, _ = run(root, "core")
    check(rc == 0, f"a closed id whose tag a backlog heading uses is registered (rc={rc}, {out!r})")

    print("occurrences are counted, not lines")
    rc, c, _ = counts_for({"core/a.md": f"{HOME} and {HOME}\n{ADDR} {ADDR}\nBL" + "-901 BL" + "-902\n"
                                        f"`{FOREIGN}` and `{FOREIGN}`\n{WORD} {WORD}\n"})
    check(c.get("home-path") == 2 and c.get("email") == 2 and c.get("unregistered-id") == 2
          and c.get("plugin-id") == 2 and c.get("vault-word") == 2, f"two per line count 2 ({c})")
    root = tree({"core/a.md": f"{HOME} and {HOME}\n"})
    rc, out, _ = run(root, "--list", "core")
    check(out.splitlines() == ["home-path core/a.md:1"] * 2, f"--list prints one line per occurrence ({out!r})")
    rc, out, _ = run(root, "--json", "core")
    data = json.loads(out)
    check(data.get("files", {}).get("core/a.md", {}).get("home-path") == 2, f"--json per-file counts ({data})")

    print("the ratchet keys per file")
    root = tree({"core/a.md": f"{HOME}\n", "core/b.md": f"{HOME}\n"})
    base = os.path.join(root, "baseline.txt")
    run(root, "--write-baseline", base, "core")
    with open(base, encoding="utf-8") as fh:
        text = fh.read()
    check("# trees: core" in text and "core/a.md" not in text
          and sum(1 for l in text.splitlines() if re.fullmatch(r"home-path sha256:[0-9a-f]{16} 1", l)) == 2,
          f"baseline lists <class> sha256:<path hash> <count>, never the path ({text!r})")
    root2 = tree({"core/alpha-widget/notes.md": f"{HOME}\n"})
    base2 = os.path.join(root2, "baseline.txt")
    run(root2, "--write-baseline", base2, "core")
    with open(base2, encoding="utf-8") as fh:
        check("alpha-widget" not in fh.read(), "a path naming a project never reaches the baseline")
    with open(os.path.join(root, "core", "a.md"), "w", encoding="utf-8") as fh:
        fh.write(f"{HOME}\n{HOME}\n")
    with open(os.path.join(root, "core", "b.md"), "w", encoding="utf-8") as fh:
        fh.write("clean\n")
    rc, out, _ = run(root, "--ratchet", base, "core")
    check(rc == 1 and "OVER home-path core/a.md 2 > 1" in out and "STALE home-path core/b.md 0 < 1" in out,
          f"a move between files is OVER in one and STALE in the other (rc={rc}, {out!r})")
    with open(os.path.join(root, "core", "a.md"), "w", encoding="utf-8") as fh:
        fh.write(f"{HOME}\n")
    with open(os.path.join(root, "core", "b.md"), "w", encoding="utf-8") as fh:
        fh.write(f"{HOME}\n")
    with open(os.path.join(root, "core", "c.md"), "w", encoding="utf-8") as fh:
        fh.write(f"{ADDR}\n")
    rc, out, _ = run(root, "--ratchet", base, "core")
    check(rc == 1 and "OVER email core/c.md 1 > 0" in out, f"a finding in an unlisted file is OVER (rc={rc}, {out!r})")

    print("bad input exits 2, never a traceback")
    root = tree({"core/a.md": "clean\n"})
    rc, _, err = run(root, "core", "nosuch")
    check(rc == 2 and "nosuch" in err, f"a named tree that does not exist exits 2 (rc={rc}, {err!r})")
    rc, _, err = run(root, "--ratchet", os.path.join(root, "missing.txt"), "core")
    check(rc == 2 and "Traceback" not in err, f"a missing baseline exits 2 (rc={rc}, {err!r})")
    for bad in ("# trees: core\nhome-path 3\n", "# trees: core\nhome-path core/a.md many\n",
                "home-path core/a.md 1\n", "# trees: core\nnosuch core/a.md 1\n"):
        with open(os.path.join(root, "bad.txt"), "w", encoding="utf-8") as fh:
            fh.write(bad)
        rc, _, err = run(root, "--ratchet", os.path.join(root, "bad.txt"), "core")
        check(rc == 2 and "Traceback" not in err, f"malformed baseline {bad!r} exits 2 (rc={rc}, {err!r})")

    print("nothing is skipped as binary; a dangling link is scanned; an unreadable file exits 2")
    root = tree({"core/a.md": "clean\n"})
    with open(os.path.join(root, "core", "blob.bin"), "wb") as fh:
        fh.write(b"\x00\x01")
    os.symlink("gone", os.path.join(root, "core", "dangling.md"))
    rc, _, err = run(root, "core")
    check(rc == 0 and "skipped" not in err, f"NUL bytes and a dangling link skip nothing (rc={rc}, {err!r})")
    if os.geteuid() != 0:
        root = tree({"core/a.md": "clean\n"})
        os.chmod(os.path.join(root, "core", "a.md"), 0)
        rc, _, err = run(root, "core")
        os.chmod(os.path.join(root, "core", "a.md"), 0o644)
        check(rc == 2 and "1 unreadable" in err, f"a mode-000 file exits 2 (rc={rc}, {err!r})")

    print("the tool and its own test hold no finding")
    repo = os.path.dirname(os.path.dirname(HERE))
    p = subprocess.run([sys.executable, SCRIPT, "--root", repo, "--list",
                        os.path.join("scripts", "check-portable.py"),
                        os.path.join("scripts", "tests", "test-check-portable.py")],
                       capture_output=True, text=True, cwd=repo)
    check(p.returncode == 0 and p.stdout == "", f"self-check is clean (rc={p.returncode}, {p.stdout!r})")


if __name__ == "__main__":
    sys.exit(main())
