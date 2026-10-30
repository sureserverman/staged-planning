#!/usr/bin/env python3
"""The Codex build's handoff writer names its session through the neutral protocol.

No Codex override touches the handoff: the writer learns its session id by running
$PLANNING_SUPERVISOR_ID_CMD, as on every host. This builds the Codex output to a scratch
dir, points that variable at a stub supervisor that prints one fixed id, and runs the
built handoff-envelope.py `ready`:

  supervised    the envelope carries "protocol": "planning-handoff" and the stub's id
  unsupervised  with the variable unset, `ready` prints `unsupervised` and writes nothing
  same file     the built script is core's, byte for byte
"""
import filecmp
import glob
import hashlib
import importlib.util
import shlex
import unittest
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join("skills", "executing-plans", "scripts", "handoff-envelope.py")
SESSION = "stub-session-0001"
HANDOFF = "h-" + "0123456789abcdef0123"
FAILS = []


def check(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)


tmp = tempfile.mkdtemp(prefix="codex-handoff-stub-")
try:
    out = os.path.join(tmp, "out")
    subprocess.run([sys.executable, os.path.join(REPO, "build", "build.py"), "--host", "codex",
                    "--out", out], cwd=REPO, check=True, capture_output=True)
    built = os.path.join(out, SCRIPT)
    check(filecmp.cmp(built, os.path.join(REPO, "core", SCRIPT), shallow=False),
          "the Codex build ships core's handoff-envelope.py unchanged")
    stub = os.path.join(tmp, "supervisor-id")
    with open(stub, "w") as fh:
        fh.write("#!/bin/sh\necho %s\n" % SESSION)
    os.chmod(stub, 0o755)
    root = os.path.join(tmp, "project")
    os.makedirs(root)
    subprocess.run(["git", "init", "-q", "--template=", root], check=True)
    plan = os.path.join(root, "p-plan.md")
    with open(plan, "w") as fh:
        fh.write("# Project Plan: stub\n")

    def ready(env_cmd):
        env = {k: v for k, v in os.environ.items() if k != "PLANNING_SUPERVISOR_ID_CMD"}
        if env_cmd is not None:
            env["PLANNING_SUPERVISOR_ID_CMD"] = env_cmd
        return subprocess.run([sys.executable, built, "ready", "--root", root, "--handoff-id",
                               HANDOFF, "--plan", plan], cwd=root, env=env,
                              capture_output=True, text=True)

    r = ready(None)
    written = glob.glob(os.path.join(root, ".claude", "handoffs", "*"))
    check(r.returncode == 0 and "unsupervised" in r.stdout and not written,
          f"unset: `ready` writes nothing ({r.stdout.strip()!r}, {len(written)} file(s))")
    r = ready(stub)
    envelopes = [p for p in glob.glob(os.path.join(root, ".claude", "handoffs", "*.json"))
                 if HANDOFF in os.path.basename(p)]
    doc = {}
    if len(envelopes) == 1:
        with open(envelopes[0]) as fh:
            doc = json.load(fh)
    check(r.returncode == 0 and doc.get("protocol") == "planning-handoff"
          and doc.get("managed_session_id") == SESSION and doc.get("event") == "HANDOFF_READY",
          f"supervised: the ready envelope names the stub's session ({r.stderr.strip()[-160:]})")
    legacy_dir = Path(REPO) / 'core/skills/executing-plans/test-fixtures/handoff-v1'
    legacy = legacy_dir / 'envelope.py'
    provenance = json.loads((legacy_dir / 'provenance.json').read_text())
    check(hashlib.sha256(legacy.read_bytes()).hexdigest() == provenance['sha256'],
          'the frozen release 1.1.1 built v1 reader/writer retains its provenance')
    receipts = []
    for host in ('claude', 'codex'):
        host_out = Path(tmp) / host
        subprocess.run([sys.executable, str(Path(REPO) / 'build/build.py'), '--host', host,
                        '--out', str(host_out)], cwd=REPO, check=True, capture_output=True)
        scripts = host_out / 'skills/executing-plans/scripts'
        for helper in ('handoff-envelope.py', 'handoff_destination.py', 'handoff_v2.py',
                       'handoff_finished.py', 'plan_state.py'):
            check(filecmp.cmp(scripts / helper, Path(REPO) / 'core/skills/executing-plans/scripts' / helper,
                              shallow=False), f'{host}: built {helper} matches core')
        for suite in ('destination', 'finished'):
            spec = importlib.util.spec_from_file_location('built_' + host + '_' + suite,
                Path(REPO) / 'core/skills/executing-plans/tests' / ('test-handoff-' + suite + '.py'))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.SCRIPTS = scripts
            result = unittest.TextTestRunner(verbosity=0).run(unittest.defaultTestLoader.loadTestsFromModule(module))
            check(result.wasSuccessful(), f'{host}: actual built {suite} writer/adopter contracts ({result.testsRun} cases)')
        # Real old built writer -> new reader, then new v2 writer -> old reader refusal.
        spec = importlib.util.spec_from_file_location('matrix_fixture_' + host,
            Path(REPO) / 'core/skills/executing-plans/tests/test-handoff-destination.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.SCRIPTS = scripts
        fixture = module.EnvelopeDestinations()
        fixture.setUp()
        try:
            local = fixture.repo('legacy-local')
            plan = fixture.records / 'legacy-plan.md'
            plan.write_text(fixture.subplan().replace('Master: ./journey-master-plan.md\n', ''))
            fixture.checkpoint(plan, fixture.hid, local, plan)
            env = {k: v for k, v in os.environ.items() if not k.startswith('PLANNING_')}
            env['PLANNING_SUPERVISOR_ID_CMD'] = shlex.join([sys.executable, '-c', "print('legacy')"])
            args = ['--root', str(local), '--handoff-id', fixture.hid, '--plan', str(plan)]
            old = subprocess.run([sys.executable, str(legacy), 'ready'] + args, env=env, cwd=local,
                                  capture_output=True, text=True, timeout=20)
            check(old.returncode == 0, f'{host}: actual frozen v1 writer publishes same-root ready')
            fixture.run_writer('verify', root=local, plan=plan, caps=None)
            fixture.run_writer('accept', root=local, plan=plan, caps=None, sid='new-reader')
            check(fixture.envelope('accepted', root=local).exists(), f'{host}: new reader accepts old v1 ready')
            fixture.ready()
            old_check = subprocess.run([sys.executable, str(legacy), 'verify', '--root', str(fixture.a),
                '--handoff-id', fixture.hid, '--plan', str(fixture.plans[0])], env=env,
                cwd=fixture.a, capture_output=True, text=True, timeout=20)
            check(old_check.returncode == 3 and old_check.stdout.strip() == 'no-ready',
                  f'{host}: actual old v1 reader refuses the new v2 ready')
            fixture.ready(caps='1', expected=3)
            # New writer defaults to v1 when no capability is advertised.
            newer = fixture.repo('new-writer-v1')
            plan2 = fixture.records / 'new-writer-plan.md'
            plan2.write_text(fixture.subplan().replace('Master: ./journey-master-plan.md\n', ''))
            fixture.checkpoint(plan2, fixture.hid, newer, plan2)
            fixture.run_writer('ready', root=newer, plan=plan2, caps=None)
            old_check = subprocess.run([sys.executable, str(legacy), 'verify', '--root', str(newer),
                '--handoff-id', fixture.hid, '--plan', str(plan2)], env=env, cwd=newer,
                capture_output=True, text=True, timeout=20)
            check(old_check.returncode == 0, f'{host}: old reader accepts unadvertised new writer v1')
            receipts.append({'host':host, 'built_version':'1.1.1 plus destination source',
                             'writer_sha256':hashlib.sha256((scripts / 'handoff-envelope.py').read_bytes()).hexdigest(),
                             'legacy_sha256':provenance['sha256'],
                             'matrix':'old/new v1, new/new v2, old-reader v2 refusal, no-capability cross-root refusal',
                             'native':'not qualified'})
        finally:
            fixture.doCleanups()
    print('compatibility-receipts: ' + json.dumps(receipts, sort_keys=True))

finally:
    shutil.rmtree(tmp)

print(f"\n{'FAIL' if FAILS else 'OK'}: {len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
