#!/usr/bin/env python3
"""JSON protocol entry point. All user-state errors have explicit exits."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode=True
from plan_state import EXITS, MAX_BYTES, admissible, guarded, result

# Reading stdin blocks until it closes, so a caller's open socket would hang these.
NO_DOCUMENT=('show',)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=('init','show','transition','begin-round',
        'record-verification','complete-round','authorize','set-blocker','strategy-review','migrate','finish',
        'recover','resolve-recovery'))
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--expected-revision',type=int)
    parser.add_argument('--operation-id')
    args=parser.parse_args()
    takes_document=args.operation not in NO_DOCUMENT
    if takes_document:
        refusal=guarded(admissible,args.repo,args.operation,args.expected_revision,args.operation_id)
        if refusal['status']!='ok':
            print(json.dumps(refusal,sort_keys=True))
            return EXITS[refusal['status']]
    try:
        # A closed stdin has no file object at all: it is a caller sending no document.
        # A non-blocking stdin with nothing waiting reads as None: also no document.
        raw=(sys.stdin.buffer.read(MAX_BYTES+1) if takes_document and sys.stdin else b'') or b''
        if len(raw)>MAX_BYTES:
            raise ValueError('payload too large')
        payload=json.loads(raw.strip() or b'{}')
        output=result(args.repo,args.operation,payload,args.expected_revision,args.operation_id)
        if not raw.strip() and takes_document and output['status'] not in ('ok','no_active_plan'):
            output['message']=args.operation+' (empty document): '+output['message']
    except OSError:
        output={'status':'state_error','message':args.operation+': stdin cannot be read'}
    except (ValueError,UnicodeError,RecursionError):
        # RecursionError: a deeply nested payload is invalid input, not a crash.
        output={'status':'state_error','message':'invalid JSON payload'}
    print(json.dumps(output,sort_keys=True))
    return EXITS[output['status']]


if __name__=='__main__':
    sys.exit(main())
