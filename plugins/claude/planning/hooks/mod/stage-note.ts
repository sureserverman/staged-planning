// The stage-boundary note: when a refresh of planning.model shows the pinned plan
// at a (plan, stage) this session has not been reminded about, while it is in
// preflight, task or gate, one short user-role row goes to the end of the
// conversation with the run-to-completion rules. It is appended, never put in a
// system-prompt section: changing the system prompt rewrites the whole cached
// prefix, the most expensive request of a long execution session.
//
// This file builds the note and decides whether a model calls for one; it holds
// no `$`. The append itself runs at the end of model.ts's refresh, because the
// engine never follows `$` across an import, and a write made from the refresh's
// timer never reaches a state.set hook of the plugin's own.
//
// Every field comes from .claude/plan-progress.json or the plan file, both
// repo-controlled and possibly hostile, and this text is model-bound: each field
// passes through clean() (the classifier's own rule: whitespace flattened, cut)
// before it is placed, quotes taken out so it cannot close the quotes around it,
// and the whole note through clean() again at NOTE_MAX. A state the script reports
// stale (stale_hours set) gets no note: a run left over from yesterday is not one
// to push on with.

import type { PlanDetail, PlanGroup, PlanModel } from '../../types'

export const NOTE_MAX = 600
export const NOTED_KEEP = 50
const FIELD_MAX = 80
// The phases the executor writes while it works; context.ts reads the same list.
export const ACTIVE_PHASES = ['preflight', 'task', 'gate']
// The hidden categories plan_continue_classify.py's clean() drops: controls (Cc),
// invisible format characters (Cf: bidi, zero-width, soft hyphen, tags) and lone
// surrogates (Cs). Whitespace among them becomes a space first.
const HIDDEN = /[\p{Cc}\p{Cf}\p{Cs}]/gu
const SPACE = /[\s\x85]+/g
const QUOTES = /["\u201c\u201d]/g
const KEY_MAX = 200

// plan_continue_classify.py's clean(), for text this side builds: whitespace runs
// flattened to one space (a newline lets planted text leave its sentence), the
// hidden categories dropped, and the result cut to `limit` UTF-16 units on a code
// point, marked with an ellipsis.
export function clean(value: unknown, limit: number): string {
  const raw = typeof value === 'string' ? value : value == null ? '' : String(value)
  const text = raw.replace(SPACE, ' ').replace(HIDDEN, '').replace(SPACE, ' ').trim()
  if (text.length <= limit) return text
  let out = ''
  for (const ch of text) {
    if (out.length + ch.length > limit - 1) break
    out += ch
  }
  return `${out}…`
}

// A field placed inside the note's quotes.
function field(value: unknown): string {
  return clean(typeof value === 'string' ? value.replace(QUOTES, '') : value, FIELD_MAX)
}

function stageOf(pinned: PlanGroup): number | null {
  return Number.isSafeInteger(pinned.stage) ? (pinned.stage as number) : null
}

export function stageNote(pinned: PlanGroup, detail: PlanDetail | null): string {
  const plan = field(pinned.name)
  const number = stageOf(pinned)
  const entry = number === null ? undefined : detail?.stages.find(s => s.number === number)
  const stageName = field(entry?.name)
  const where =
    number === null ? `plan "${plan}"` : `plan "${plan}", Stage ${number}${stageName === '' ? '' : ` ("${stageName}")`}`
  return clean(
    `[planning] Now executing ${where}. Run to completion: finish this stage and go straight on to the next; ` +
      'never end a turn on an announcement, the tool call that starts announced work goes in the same turn; ' +
      'stop only with an `ACTION NEEDED:` block, a documented Stop condition, or a `handoff` verdict from ' +
      'context-usage.py run after a gate.',
    NOTE_MAX,
  )
}

// The note a freshly refreshed model calls for, keyed by (plan, stage); null when
// there is no pinned plan or it is not in preflight, task or gate.
export function noteFor(model: PlanModel): { key: string; note: string } | null {
  if (!Array.isArray(model.groups)) return null
  const pinned = model.groups.find(g => g?.role === 'pinned')
  if (pinned === undefined) return null
  if (!ACTIVE_PHASES.includes(String(pinned.phase ?? '').toLowerCase())) return null
  if (pinned.stale_hours != null) return null
  const stage = stageOf(pinned)
  // Held to KEY_MAX: the plan path is repo-controlled, and the key is stored.
  const plan = clean(typeof pinned.plan === 'string' ? pinned.plan : pinned.name, KEY_MAX)
  return {
    key: JSON.stringify([plan, stage]),
    note: stageNote(pinned, model.detail ?? null),
  }
}

// The row the refresh appends: one user-role text block (the model reads it; a
// `system` row would be a notice it never sees), bounded once more here.
export function noteMessage(note: string): { message: { type: 'user'; content: { type: 'text'; text: string }[] } } {
  return { message: { type: 'user', content: [{ type: 'text', text: clean(note, NOTE_MAX) }] } }
}
