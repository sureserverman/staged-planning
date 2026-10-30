#!/usr/bin/env python3
"""JSON protocol entry point. All user-state errors have explicit exits."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode=True
from plan_state import EXITS, MAX_BYTES, result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=('init','show','transition','begin-round',
        'record-verification','complete-round','authorize','set-blocker','strategy-review','migrate','finish',
        'recover','resolve-recovery'))
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--expected-revision',type=int)
    parser.add_argument('--operation-id')
    args=parser.parse_args()
    try:
        raw=sys.stdin.buffer.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:
            raise ValueError('payload too large')
        payload=json.loads(raw or b'{}')
        output=result(args.repo,args.operation,payload,args.expected_revision,args.operation_id)
    except (ValueError,UnicodeError,RecursionError):
        # RecursionError: a deeply nested payload is invalid input, not a crash.
        output={'status':'state_error','message':'invalid JSON payload'}
    print(json.dumps(output,sort_keys=True))
    return EXITS[output['status']]


if __name__=='__main__':
    sys.exit(main())
