// Shared fixtures for the mod's *.test.ts(x) files: the world beneath the mod.
// Not imported by register.tsx, so it never loads in a session.

import type { On } from 'claude-code'
import { mock } from 'claude-code/testing'
import type { MockClock } from 'claude-code/testing'

import type { PlanGroup, PlanModel, PlanModelState } from '../../types'

export type Run = { argv: string[]; init: { cwd?: string; stdin?: string; timeoutMs?: number } | undefined }

export const ran = (stdout: string, exitCode = 0) => ({
  value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})

export function group(over: Partial<PlanGroup> = {}): PlanGroup {
  return {
    name: 'fixture-plan',
    done: 2,
    total: 5,
    role: 'pinned',
    depth: 0,
    stage: 1,
    stage_count: 2,
    task: '1.3',
    phase: 'task',
    tail: '· S1/2 ▶ T1.3 wire the thing',
    ...over,
  }
}

// A session at /repo, a clock that moves only when the test moves it, a
// process.run answered by `answer`, the mod's state writes observed on their way
// down (the test's $ has no state noun; the last write is what a drawing reads),
// and a tool beneath that answers every call.
export function world(
  on: On,
  answer: () => unknown | Promise<unknown> = () => ran(JSON.stringify({ groups: [group()], detail: null })),
  stateDown: () => boolean = () => false,
) {
  const runs: Run[] = []
  const order: string[] = []
  const seen: { last: PlanModelState | null; keys: Record<string, unknown> } = { last: null, keys: {} }
  const clock: MockClock = mock.clock(on, { now: 1_000 })
  on('session.cwd', () => ({ value: '/repo' }))
  on('process.run', async (_$, e) => {
    runs.push({ argv: [...e.argv], init: e.init })
    order.push('run')
    return (await answer()) as never
  })
  on('state.set', (_$, e, next) => {
    if (stateDown()) return { deny: 'state store down' } as never
    if (e.plugin === 'planning') seen.keys[e.key] = e.value
    if (e.plugin === 'planning' && e.key === 'model') seen.last = e.value as PlanModelState
    return next(e)
  })
  // onTool runs inside the tool stand-in; what it returns (if anything) is the
  // tool's answer, else { result: 'ok' }.
  const hooks: { onTool?: (e: { tool: string }) => unknown } = {}
  on('tool.call', async (_$, e) => {
    order.push('tool')
    const answer = await hooks.onTool?.(e)
    return (answer ?? { result: 'ok' }) as never
  })
  return { runs, order, seen, clock, hooks }
}

// Puts `model` into planning.model the way a session does: a state-file write
// triggers a refresh whose script run answers with it.
export async function seed($: { tool: { call: (i: never) => Promise<unknown> } }, clock: MockClock): Promise<void> {
  await $.tool.call({ tool: 'Write', file_path: '.claude/plan-progress.json', content: '{}' } as never)
  await clock.settle()
}

export function modelOf(groups: PlanGroup[]): PlanModel {
  return { groups, detail: null }
}

// The status line's five role colours, as plan-progress.py --json reports them.
export const PALETTE = { green: '#008c2f', red: '#db3630', yellow: '#947006', cyan: '#168191', purple: '#a23efa' }
