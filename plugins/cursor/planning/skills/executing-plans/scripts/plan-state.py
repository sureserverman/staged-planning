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


# What a caller sends, per operation. The JSON goes on stdin; the revision is the last
# receipt's (0 for init), and the id is new for each call.
PAYLOADS={'init':('{"plan": "<plan>", "source": "<the owner request, quoted>", "scope": "plan"}',0),
    'transition':('{"phase": "task", "stage": 1, "task": "1.1", "task_desc": "<title>"}',2),
    'finish':('{"evidence": "<the Completed line and its commit>"}',9)}


def example_for(operation):
    op=operation or 'transition'
    payload,revision=PAYLOADS.get(op,('<payload: references/execution-state-contract.md>',3))
    return ("echo '"+payload+"' | python3 <planning-plugin>/skills/executing-plans/scripts/"
            "plan-state.py "+op+" --repo <repo> --expected-revision "+str(revision)+
            " --operation-id <id>")


class ExampleParser(argparse.ArgumentParser):
    """An argument error ends with `example: <a call this parser accepts>`. `check`
    (namespace -> problem or None) holds the rules argparse cannot state, such as a flag
    another flag needs, so they fail here, with the example, before the script acts."""

    def __init__(self, *args, example=None, check=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.example = example
        self.check = check

    def parse_known_args(self, args=None, namespace=None):
        namespace, extras = super().parse_known_args(args, namespace)
        problem = self.check(namespace) if self.check else None
        if problem:
            self.error(problem)
        return namespace, extras

    def error(self, message):
        self.print_usage(sys.stderr)
        tail = f"example: {self.example}\n" if self.example else ""
        self.exit(2, f"{self.prog}: error: {message}\n{tail}")


def main():
    parser=ExampleParser(example=example_for(None))
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
            if args.expected_revision is None or not args.operation_id:
                print('example: '+example_for(args.operation),file=sys.stderr)
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
