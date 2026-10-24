import { expect, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import type { PlanGroup } from '../../types'
import { figuresOf, isoSeconds } from './context'
import { group, ran, seed, world } from './testing'
import type { Run } from './testing'

const SESSION = 'session-abc'
const USAGE = { window: 1_000_000, tokens: 250_000, percent: 25 }

// The --write-sidecar runs the mod made, with the JSON it handed over.
function writes(w: { runs: Run[] }) {
  return w.runs
    .filter(r => r.argv.includes('--write-sidecar'))
    .map(r => ({ argv: r.argv, init: r.init, body: JSON.parse(r.init?.stdin ?? 'null') }))
}

function engine(on: On, context: unknown = USAGE) {
  on('session.id', () => ({ value: SESSION }))
  on('session.usage', () => ({ value: { startedAt: 0, context, rateLimits: [] } }) as never)
  on('turn.complete', () => ({ text: '' }))
}

const turn = (over: Record<string, unknown> = {}) =>
  ({ answer: 'done', durationMs: 5, isAborted: false, turnId: 't1', reason: 'answer', ...over }) as never

function planned(groups: PlanGroup[]) {
  return () => ran(JSON.stringify({ groups, detail: null }))
}

async function setup($: unknown, on: On, groups: PlanGroup[], context?: unknown) {
  const w = world(on, planned(groups))
  engine(on, context)
  await seed($ as never, w.clock)
  return w
}

test('a pinned plan in task: the script is handed the engine figures and this session', async ($, on) => {
  const w = await setup($, on, [group({ phase: 'task' })])
  await $.turn.complete(turn())
  const runs = writes(w)
  expect(runs.length).toBe(1)
  const { argv, init, body } = runs[0]!
  expect(argv[0]).toBe('python3')
  expect(argv).toContain('-I')
  expect(argv.some(a => a.endsWith('skills/executing-plans/scripts/context-usage.py'))).toBe(true)
  expect(init?.cwd).toBe('/repo')
  expect(init?.timeoutMs).toBe(5000)
  expect(body.session_id).toBe(SESSION)
  expect(body.window).toBe(1_000_000)
  expect(body.tokens).toBe(250_000)
  expect(body.percent).toBe(25)
  expect(body.updated).toBe(isoSeconds(await w.clock.now()))
  expect(body.updated).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/)
  expect(Object.keys(body).sort()).toEqual(['percent', 'session_id', 'tokens', 'updated', 'window'])
  expect(w.seen.keys.context).toEqual(USAGE)
})

for (const phase of ['preflight', 'gate', 'TASK']) {
  test(`a pinned plan in ${phase}: written`, async ($, on) => {
    const w = await setup($, on, [group({ phase })])
    await $.turn.complete(turn())
    expect(writes(w).length).toBe(1)
  })
}

test('no plan in flight: nothing is written', async ($, on) => {
  const w = await setup($, on, [])
  await $.turn.complete(turn())
  expect(writes(w).length).toBe(0)
})

test('a pinned plan outside preflight, task and gate: nothing is written', async ($, on) => {
  const w = await setup($, on, [group({ phase: 'closeout' }), group({ name: 'other', role: 'other' })])
  await $.turn.complete(turn())
  expect(writes(w).length).toBe(0)
})

test('only another plan in task, none pinned: nothing is written', async ($, on) => {
  const w = await setup($, on, [group({ role: 'other', phase: 'task' })])
  await $.turn.complete(turn())
  expect(writes(w).length).toBe(0)
})

test('a stale pinned plan: nothing is written', async ($, on) => {
  const w = await setup($, on, [group({ phase: 'gate', stale_hours: 30 })])
  await $.turn.complete(turn())
  expect(writes(w).length).toBe(0)
})

test('a subagent turn: nothing is written, nothing stored', async ($, on) => {
  const w = await setup($, on, [group({ phase: 'task' })])
  await $.turn.complete(turn({ agentId: 'agent-1' }))
  expect(writes(w).length).toBe(0)
  expect('context' in w.seen.keys).toBe(false)
})

for (const context of [{ window: 0 }, {}, { window: 1.5 }, { window: '1000000' }]) {
  test(`no window from the engine (${JSON.stringify(context)}): nothing is written, no figures`, async ($, on) => {
    const w = await setup($, on, [group({ phase: 'task' })], context)
    await $.turn.complete(turn())
    expect(writes(w).length).toBe(0)
    expect(w.seen.keys.context).toBe(null)
  })
}

test('a write run that fails leaves the turn to end normally', async ($, on) => {
  let calls = 0
  const w = world(on, () => {
    calls += 1
    if (calls > 1) throw new Error('timed out')
    return ran(JSON.stringify({ groups: [group({ phase: 'task' })], detail: null }))
  })
  engine(on)
  await seed($ as never, w.clock)
  const done = await $.turn.complete(turn())
  expect(typeof done.text).toBe('string')
  expect(writes(w).length).toBe(1)
  expect(w.seen.keys.context).toEqual(USAGE)
})

// A run-to-completion stage is often one long turn: the sidecar must not wait
// for its end. The Bash call that runs context-usage.py gets a fresh one first.
test('a main-loop Bash call running context-usage.py writes the sidecar before it runs', async ($, on) => {
  const w = await setup($, on, [group({ phase: 'gate' })])
  const before = writes(w).length
  w.order.length = 0
  await $.tool.call({ tool: 'Bash', command: 'python3 /p/skills/executing-plans/scripts/context-usage.py --plan x' } as never)
  expect(writes(w).length).toBe(before + 1)
  expect(w.order.indexOf('run')).toBeLessThan(w.order.indexOf('tool'))
  expect(w.seen.keys.context).toEqual(USAGE)
})

test('other Bash calls, a subagent\'s context-usage.py, and no plan in flight write nothing', async ($, on) => {
  const w = await setup($, on, [group({ phase: 'task' })])
  const before = writes(w).length
  await $.tool.call({ tool: 'Bash', command: 'git status' } as never)
  await $.tool.call({ tool: 'Bash', command: 'python3 context-usage.py', agentId: 'a1' } as never)
  expect(writes(w).length).toBe(before)
})

test('context-usage.py with no plan in flight writes nothing', async ($, on) => {
  const w = await setup($, on, [group({ phase: 'closeout' })])
  await $.tool.call({ tool: 'Bash', command: 'python3 context-usage.py' } as never)
  expect(writes(w).length).toBe(0)
})

test('figuresOf keeps only whole, non-negative figures and caps percent at 100', () => {
  expect(figuresOf({ context: { window: 200_000, tokens: -1, percent: 140 } })).toEqual({
    window: 200_000,
    tokens: null,
    percent: 100,
  })
  expect(figuresOf({ context: { window: 200_000 } })).toEqual({ window: 200_000, tokens: null, percent: null })
  expect(figuresOf(null)).toBe(null)
  expect(figuresOf({ context: null })).toBe(null)
})
