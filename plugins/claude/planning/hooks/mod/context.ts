// The live context window, for the two readers that want it: context-usage.py,
// through the sidecar .claude/plan-context.json, and the band, through
// planning.context. context-usage.py otherwise knows the window only from its
// model table, and an unknown model there leaves its handoff verdict `unknown`.
//
// This file only carries the engine's figures across. The verdict stays the
// script's: the sidecar names the window, and the script still counts the
// tokens from the transcript and applies its own rules. The sidecar is written,
// while the pinned plan is in preflight, task or gate and never otherwise, at the
// end of each main-loop turn and just before a main-loop Bash call that runs
// context-usage.py: a run-to-completion stage is often one long turn, and the
// verdict at its gate must not find a sidecar older than its 15-minute limit.
//
// The write itself is context-usage.py's (--write-sidecar): it finds the root the
// way its reader does, and writes without following any link the repo planted
// (`.claude` opened O_NOFOLLOW, a fresh temporary, a rename over the name). This
// file only hands it the engine's figures and this session's id.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, On } from 'claude-code'

import type { ContextFigures, PlanModelState } from '../../types'
import { ACTIVE_PHASES } from './stage-note'

const MODEL = atom({ plugin: 'planning', key: 'model' } as const, null as PlanModelState | null)
const CONTEXT = atom({ plugin: 'planning', key: 'context' } as const, null as ContextFigures | null)

const SCRIPT = 'skills/executing-plans/scripts/context-usage.py'
const RUNS_CONTEXT_USAGE = /context-usage\.py/
const TIMEOUT_MS = 5000

const count = (v: unknown): number | null =>
  typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 ? v : null

// The engine's figures, held to what the readers accept: a window that is a
// positive whole number, else none at all.
export function figuresOf(usage: unknown): ContextFigures | null {
  const c = (usage as { context?: unknown } | null)?.context as Record<string, unknown> | undefined
  if (c === null || typeof c !== 'object') return null
  const window = count(c.window)
  if (window === null || window === 0) return null
  const percent = count(c.percent)
  return { window, tokens: count(c.tokens), percent: percent === null ? null : Math.min(percent, 100) }
}

// Whether the model shows a plan executing right now: the pinned plan, not stale,
// in a phase the executor writes while it works.
export function inFlight(state: PlanModelState | null): boolean {
  const pinned = state?.model?.groups?.find(g => g?.role === 'pinned')
  if (pinned === undefined || pinned.stale_hours != null) return false
  return ACTIVE_PHASES.includes(String(pinned.phase ?? '').toLowerCase())
}

// `2026-10-04T08:00:00Z`, the state file's own spelling of a time.
export const isoSeconds = (ms: number): string => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z')

async function writeSidecar($: EngineInterface, figures: ContextFigures): Promise<void> {
  const sidecar = {
    session_id: await $.session.id(),
    window: figures.window,
    tokens: figures.tokens,
    percent: figures.percent,
    updated: isoSeconds(await $.clock.now()),
  }
  await $.process.run(['python3', '-I', `${$.plugin.root}/${SCRIPT}`, '--write-sidecar'], {
    cwd: await $.session.cwd(),
    stdin: JSON.stringify(sidecar),
    timeoutMs: TIMEOUT_MS,
  })
}

// The engine's current figures into planning.context, and into the sidecar while a
// plan is in flight. Never throws.
async function capture($: EngineInterface): Promise<void> {
  try {
    const figures = figuresOf(await $.session.usage())
    await update($, CONTEXT, () => figures)
    if (figures !== null && inFlight(await read($, MODEL))) await writeSidecar($, figures)
  } catch {
    // no sidecar this time; context-usage.py falls back to its table
  }
}

export function registerContext(on: On): void {
  // Main loop only: a subagent's turn reports its own loop, not the session's
  // window.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId === undefined) await capture($)
    return result
  })

  // Before the tool runs, so the script it starts reads this moment's window.
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const command = (e as { command?: unknown }).command
    if (e.agentId === undefined && typeof command === 'string' && RUNS_CONTEXT_USAGE.test(command)) {
      await capture($)
    }
    return next(e)
  })
}
