#!/usr/bin/env python3
"""Integrated, subprocess-driven workflow groups; no empty group can pass."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
GROUPS = ('durable-round', 'authorized-experiment', 'premises', 'complete')


def run_group(group, manifest):
    if group == 'durable-round':
        for selection in ('storage', 'rounds'):
            subprocess.run([sys.executable, str(HERE/'test-plan-state.py'), '--group', selection],
                           check=True, timeout=300)
    else:
        # An unimplemented group fails loudly, never as an empty pass.
        from workflow_trace_cases import run
        run(group, manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--group', choices=GROUPS, default='complete')
    parser.add_argument('--manifest', type=Path,
                        default=HERE.parent/'scripts/workflow-recovery-manifest.json')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if manifest.get('schema_version') != 2 or set(manifest.get('trace_groups', [])) != set(GROUPS):
        parser.error('incomplete or unsupported manifest')
    run_group(args.group, manifest)
