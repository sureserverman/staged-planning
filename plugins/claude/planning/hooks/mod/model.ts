// The mod's data layer: the render model plan-progress.py --json prints, held in
// $.state so every drawing that reads it redraws when it changes.
//
// The script is the one implementation of discovery, counting and grouping; this
// file only decides WHEN to run it. A drawing never runs it: a render hook that
// spawned a process would put a plan scan (a stall on an unreachable mount) on
// the redraw path. Refreshes come from session.start, a poll, and plan-touching tool
// calls instead, each run detached from the hook that asked for it.

import { atom, update } from 'claude-code'
import type { EngineInterface, On } from 'claude-code'

import type { PlanModel, PlanModelState } from '../../types'
import { clean, NOTE_MAX, NOTED_KEEP, noteFor, noteMessage } from './stage-note'

export const MODEL = atom({ plugin: 'planning', key: 'model' } as const, null as PlanModelState | null)
const NOTED = atom({ plugin: 'planning', key: 'notedStages' } as const, [] as string[])

const SCRIPT = 'skills/executing-plans/scripts/plan-progress.py'
const TIMEOUT_MS = 5000
const POLL_MS = 30000

// A tool call that can have changed what the model shows: the state file the
// executor mirrors, or a plan file whose Status markers the counts come from. The
// Bash match is by mention, so a read (`cat x-plan.md`) refreshes too: a wasted
// scan, never wrong data, and it runs detached. A write it cannot see (a bare
// `plan-progress.json` after `cd .claude`, a plan without the -plan.md suffix) is
// picked up by the poll.
const PLAN_STATE = /(^|\/)\.claude\/plan-progress\.json$/
const PLAN_FILE = /-plan\.md$/
const MENTIONS = /\.claude\/plan-progress\.json|-plan\.md/

export function touchesPlanState(e: { tool: string; [k: string]: unknown }): boolean {
  const tool = String(e.tool)
  if (tool === 'Write' || tool === 'Edit' || tool === 'MultiEdit') {
    const path = typeof e.file_path === 'string' ? e.file_path : ''
    return PLAN_STATE.test(path) || PLAN_FILE.test(path)
  }
  if (tool === 'Bash') {
    return typeof e.command === 'string' && MENTIONS.test(e.command)
  }
  return false
}

function parseModel(stdout: string): PlanModel | null {
  try {
    const value = JSON.parse(stdout) as unknown
    if (value === null || typeof value !== 'object') return null
    const groups = (value as { groups?: unknown }).groups
    if (!Array.isArray(groups)) return null
    return value as PlanModel
  } catch {
    return null
  }
}

// One refresh at a time per module load: a trigger landing while one runs asks
// for exactly one more after it, never a pile of concurrent scans.
let running: Promise<void> | null = null
let again = false

// Never rejects: a refresh is a cache fill, and a fault in it must not surface as
// a failed tool call or an unhandled rejection in a timer.
export function refresh($: EngineInterface): Promise<void> {
  if (running !== null) {
    again = true
    return running
  }
  running = (async () => {
    do {
      again = false
      try {
        await refreshOnce($)
      } catch {
        // keep whatever the state holds; the next trigger tries again
      }
    } while (again)
  })().finally(() => {
    running = null
  })
  return running
}

// Detached from the triggering hook: a slow scan (an unreachable records mount, up
// to TIMEOUT_MS) must hold neither the first prompt nor a tool result. A clock timer
// is the documented home for work that outlives a dispatch.
function schedule($: EngineInterface): void {
  $.clock.after(0, () => void refresh($))
}

// $.clock timers end when the module reloads, and session.start does not fire
// again after a reload, so the poll is re-armed lazily by whichever hook runs
// first in each load. `polling` is a module variable on purpose: it resets with
// the timers it tracks.
let polling = false

function ensurePolling($: EngineInterface): void {
  if (polling) return
  polling = true
  $.clock.every(POLL_MS, () => void refresh($))
}

async function refreshOnce($: EngineInterface): Promise<void> {
  let model: PlanModel | null = null
  try {
    const cwd = await $.session.cwd()
    const ran = await $.process.run(['python3', `${$.plugin.root}/${SCRIPT}`, '--json'], {
      cwd,
      stdin: JSON.stringify({ cwd, workspace: { current_dir: cwd } }),
      timeoutMs: TIMEOUT_MS,
    })
    if (ran.exitCode === 0) model = parseModel(ran.stdout)
  } catch {
    model = null
  }
  const fetchedAt = await $.clock.now()
  await update($, MODEL, previous =>
    model !== null
      ? { model, fetchedAt, stale: false }
      : { model: previous?.model ?? null, fetchedAt: previous?.fetchedAt ?? fetchedAt, stale: true },
  )
  // Not awaited: an append that never settles must not hold `running`, which
  // would leave every later refresh queued behind it and the model frozen.
  if (model !== null) void noteStage($, model)
}

// The stage-boundary note (stage-note.ts builds it): once per (plan, stage) per
// session. Marked before the append, so a refused or failing append is not retried
// on every refresh. Never throws: the model is already stored.
async function noteStage($: EngineInterface, model: PlanModel): Promise<void> {
  try {
    const wanted = noteFor(model)
    if (wanted === null) return
    let isNew = false
    await update($, NOTED, previous => {
      const list = Array.isArray(previous) ? previous : []
      isNew = !list.includes(wanted.key)
      return isNew ? [...list, wanted.key].slice(-NOTED_KEEP) : list
    })
    if (!isNew) return
    let refused: string | null = null
    try {
      const stored = await $.session.append(noteMessage(clean(wanted.note, NOTE_MAX)))
      if (stored.deny !== undefined) refused = stored.deny
    } catch (err) {
      refused = err instanceof Error ? err.message : String(err)
    }
    if (refused !== null) $.ui.log(`planning: stage note not delivered (${clean(refused, 120)})`)
  } catch {
    // no note this time
  }
}

export function registerModel(on: On): void {
  // The module's one unmatched session.start (an event takes one hook per module
  // without a matcher); other parts hook it under a matcher.
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    ensurePolling($)
    schedule($)
    return started
  })

  on('turn.start', async ($, e, next) => {
    ensurePolling($)
    return next(e)
  })

  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    ensurePolling($)
    if (touchesPlanState(e)) schedule($)
    return result
  })
}
