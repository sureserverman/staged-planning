// The run-to-completion Stop check on Claude Code 2.1.288+: the mod's answer to
// classic.Stop, opt-in exactly like the command hook (PLAN_CONTINUE=1). Everything
// that decides is plan_continue_classify.py's — the same module the command hook
// imports: `--inputs` finds the repo root, reads .claude/plan-progress.json through
// the hardened reader (opened component by component with O_NOFOLLOW, FIFO-safe, owner, size),
// parses PLAN_CONTINUE_MAX and names the counter key; the classifier then decides.
// This file only carries the last assistant message (on the event, no transcript to
// tail) and the no-progress count, kept in $.state so a hot reload does not reset it.
//
// When the module answered, the event passes on marked planning_mod_handled: the
// user's own Stop hooks still run (answering without next would skip them all), and
// the command hook, seeing the mark, steps aside instead of deciding twice. When it
// did not answer — no last message on the event, a run refused, failed or garbled —
// the event passes on unmarked and the command hook decides from the transcript.
// Every failure allows: a Stop hook that fails closed traps the session.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, On } from 'claude-code'

import type { StopCounter } from '../../types'

const COUNTER = atom({ plugin: 'planning', key: 'stopCounter' } as const, null as StopCounter | null)

const CLASSIFIER = 'hooks/plan_continue_classify.py'
const CONTEXT_USAGE = 'skills/executing-plans/scripts/context-usage.py'
const TIMEOUT_MS = 5000
const MAX_TEXT_BYTES = 2048
const DEFAULT_MAX = 3
// Newlines stay (the reason's paragraphs); every other character of the hidden
// categories goes, as in plan_continue_classify.py's clean(): controls (Cc),
// invisible format characters (Cf: bidi, zero-width, soft hyphen, tags) and lone
// surrogates (Cs).
const HIDDEN = /(?!\n)[\p{Cc}\p{Cf}\p{Cs}]/gu
const COUNT_LOST =
  'plan-continue: the no-progress count could not be stored, so there is no loop guard; letting the turn end.'

type Decision = { decision: string; reason?: unknown; system_message?: unknown; notice?: unknown }

// What the module answered for one Stop, and the counter entry it is counted under
// (null when there was no state to count against).
type Verdict = { decision: Decision; counterKey: string | null; count: number }

// Model-bound or user-visible text from the classifier, held again on this side:
// control characters out, at most MAX_TEXT_BYTES of UTF-8, cut on a character.
export function bounded(text: unknown): string {
  const flat = (typeof text === 'string' ? text : '').replace(HIDDEN, '')
  const encoder = new TextEncoder()
  if (encoder.encode(flat).length <= MAX_TEXT_BYTES) return flat
  let out = ''
  let used = 0
  for (const ch of flat) {
    const size = encoder.encode(ch).length
    if (used + size > MAX_TEXT_BYTES - 3) break
    out += ch
    used += size
  }
  return `${out}…`
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

// The module's JSON answer, or null when it did not give one (refused, timed out,
// non-zero exit, unparseable output).
async function runPython($: EngineInterface, args: string[], input: unknown): Promise<Record<string, unknown> | null> {
  try {
    const ran = await $.process.run(['python3', '-I', `${$.plugin.root}/${CLASSIFIER}`, ...args], {
      stdin: JSON.stringify(input),
      timeoutMs: TIMEOUT_MS,
    })
    if (ran.exitCode !== 0) return null
    const parsed: unknown = JSON.parse(ran.stdout)
    return isObject(parsed) ? parsed : null
  } catch {
    return null
  }
}

// null: the module did not answer, so the command hook is left to decide.
async function decide($: EngineInterface, lastText: string): Promise<Verdict | null> {
  const cwd = await $.session.cwd()
  const max = (await $.env.get('PLAN_CONTINUE_MAX')) ?? null
  const got = await runPython($, ['--inputs'], { cwd, max })
  if (got === null) return null
  const { root, state, key } = got
  if (typeof root !== 'string' || root === '' || !isObject(state) || typeof key !== 'string') {
    return { decision: { decision: 'allow' }, counterKey: null, count: 0 }
  }

  // Keyed by root too, as the command hook's counter file is: two repos in one
  // session never share a count.
  const counterKey = JSON.stringify([root, key])
  const counter = await read($, COUNTER)
  const count = counter !== null && counter.key === counterKey ? counter.count : 0

  const result = await runPython($, [], {
    state,
    last_text: lastText,
    count,
    max: typeof got.max === 'number' && Number.isInteger(got.max) ? got.max : DEFAULT_MAX,
    context_usage_path: `${$.plugin.root}/${CONTEXT_USAGE}`,
    check_updated: true,
  })
  if (result === null || typeof result.decision !== 'string') return null
  return { decision: result as Decision, counterKey, count }
}

export function registerStop(on: On): void {
  on('classic.Stop', async ($, e, next) => {
    let optedIn = false
    try {
      optedIn = (await $.env.get('PLAN_CONTINUE')) === '1'
    } catch {
      optedIn = false
    }
    const lastText = e.last_assistant_message
    if (!optedIn || typeof lastText !== 'string' || lastText.trim() === '') return next(e)

    let verdict: Verdict | null = null
    try {
      verdict = await decide($, lastText)
    } catch {
      verdict = null
    }
    if (verdict === null) return next(e)

    // The hooks below are the user's: one that fails must not make this one throw.
    let below: Awaited<ReturnType<typeof next>>
    try {
      below = await next({ ...e, planning_mod_handled: true } as typeof e)
    } catch {
      return {}
    }
    if (!isObject(below)) return {}
    try {
      return await finish($, verdict, below)
    } catch {
      return below
    }
  })
}

async function finish(
  $: EngineInterface,
  verdict: Verdict,
  below: Record<string, unknown> & { block?: string },
): Promise<typeof below> {
  const { decision } = verdict
  const userBlocked = typeof below.block === 'string' && below.block !== ''

  // The command hook's systemMessage: one dim transcript line, never sent to the model.
  const note = typeof decision.system_message === 'string' ? decision.system_message : decision.notice
  if (typeof note === 'string' && note !== '') {
    try {
      $.ui.log(bounded(note))
    } catch {
      // a notice that cannot be shown changes no decision
    }
  }

  // Counted when the command hook counts — a block, or a guard release — except a
  // block a user's own Stop hook pre-empted: that continuation was not ours. A
  // count that cannot be stored leaves no loop guard, so that block is not sent.
  const counted = (decision.decision === 'block' && !userBlocked) || typeof decision.system_message === 'string'
  let stored = true
  if (counted && verdict.counterKey !== null) {
    const entry = { key: verdict.counterKey, count: verdict.count + 1 }
    try {
      await update($, COUNTER, () => entry)
    } catch {
      stored = false
    }
  }

  if (userBlocked) return below
  if (decision.decision !== 'block' || typeof decision.reason !== 'string') return below
  if (!stored) {
    try {
      $.ui.log(COUNT_LOST)
    } catch {
      // the allow stands without its notice
    }
    return below
  }
  const reason = bounded(decision.reason)
  return reason === '' ? below : { ...below, block: bounded(decision.reason) }
}
