import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

const ROOT = '/repo'
const PROMISE = 'Stage 2 is green and committed — starting now with Task 2.1.'
const STATE = { plan: 'plans/x-plan.md', phase: 'task', stage: 2, task: '2.1', updated: '2000-01-01T00:00:00Z' }

type Classified = { decision: string; reason?: string; system_message?: string; notice?: string }
type Inputs = { root: string | null; state: unknown; key: string | null; max: number }
type ClassifyIn = { state: unknown; count: number; max: number; check_updated?: boolean }
type Fault = { deny: string } | { exitCode: number; stdout: string }
type Opts = {
  env?: Record<string, string>
  inputs?: (input: { cwd?: string; max?: unknown }) => Inputs | Fault
  classify?: (input: ClassifyIn) => Classified | Fault
  below?: () => { block?: string }
  stateDown?: boolean
}

const ran = (stdout: string, exitCode = 0) => ({
  value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})
const answer = (out: unknown) =>
  typeof out === 'object' && out !== null && 'deny' in out
    ? out
    : typeof out === 'object' && out !== null && 'exitCode' in out
      ? ran((out as { stdout: string }).stdout, (out as { exitCode: number }).exitCode)
      : ran(JSON.stringify(out))

const INPUTS: Inputs = { root: ROOT, state: STATE, key: 'task|2|2.1', max: 3 }

// The world beneath the mod for a Stop: the environment, the session's cwd, the
// two process runs (`--inputs`, then the classifier — answered here as the Python
// module would), the counter's state writes, and what the chain below receives.
function harness(on: On, o: Opts = {}) {
  const spawned: string[][] = []
  const below: Record<string, unknown>[] = []
  const notices: string[] = []
  const gathered: { cwd?: string; max?: unknown }[] = []
  const inputs: ClassifyIn[] = []
  mock.env(on, o.env ?? { PLAN_CONTINUE: '1' })
  on('session.cwd', () => ({ value: `${ROOT}/sub` }))
  on('process.run', (_$, e) => {
    spawned.push([...e.argv])
    const input = JSON.parse(e.init?.stdin ?? '{}')
    if (e.argv.includes('--inputs')) {
      gathered.push(input)
      return answer((o.inputs ?? (() => INPUTS))(input)) as never
    }
    inputs.push(input)
    return answer((o.classify ?? (() => ({ decision: 'block', reason: 'keep going' })))(input)) as never
  })
  on('state.set', (_$, e, next) => (o.stateDown ? ({ deny: 'state store down' } as never) : next(e)))
  on('ui.log', (_$, e) => {
    notices.push(String((e as { text?: unknown }).text))
    return { value: undefined } as never
  })
  on('classic.Stop', (_$, e) => {
    below.push(e as Record<string, unknown>)
    return o.below?.() ?? {}
  })
  return { spawned, below, notices, gathered, inputs }
}

// A rest parameter, not a default, so an explicit `undefined` message reaches the event.
const stop = ($: { classic: { Stop: (e: never) => Promise<{ block?: string }> } }, ...text: unknown[]) =>
  $.classic.Stop({ stop_hook_active: false, last_assistant_message: text.length > 0 ? text[0] : PROMISE } as never)

test('opt-in off: the event passes on untouched and nothing is spawned', async ($, on) => {
  const w = harness(on, { env: {} })
  const r = await stop($ as never)
  expect(r.block).toBe(undefined)
  expect(w.spawned.length).toBe(0)
  expect(w.below.length).toBe(1)
  expect(w.below[0]!.planning_mod_handled).toBe(undefined)
})

test('a promise in phase task blocks with the classifier reason, and the chain below still runs', async ($, on) => {
  const w = harness(on)
  const r = await stop($ as never)
  expect(r.block).toBe('keep going')
  expect(w.below.length).toBe(1)
  expect(w.below[0]!.planning_mod_handled).toBe(true)
  expect(w.gathered[0]!.cwd).toBe(`${ROOT}/sub`)
  expect(w.inputs[0]!.state).toEqual(STATE)
  expect(w.inputs[0]!.check_updated).toBe(true)
  expect(w.spawned.every(a => a.some(x => x.endsWith('plan_continue_classify.py')))).toBe(true)
})

test('the same phase|stage|task blocked max times releases the next with a notice', async ($, on) => {
  const w = harness(on, {
    classify: ({ count, max }) =>
      count >= max ? { decision: 'allow', system_message: `released after ${count}` } : { decision: 'block', reason: 'go' },
  })
  for (let i = 0; i < 3; i += 1) expect((await stop($ as never)).block).toBe('go')
  const r = await stop($ as never)
  expect(r.block).toBe(undefined)
  expect(w.inputs.map(x => x.count)).toEqual([0, 1, 2, 3])
  expect(w.inputs[0]!.max).toBe(3)
  expect(w.notices).toEqual(['released after 3'])
})

test('the counter restarts when the key moves, or the same key is in another repo', async ($, on) => {
  const keys: Inputs[] = [
    INPUTS,
    INPUTS,
    { ...INPUTS, key: 'task|2|2.2' },
    { ...INPUTS, key: 'task|2|2.2' },
    { ...INPUTS, root: '/other', key: 'task|2|2.2' },
  ]
  let i = 0
  const w = harness(on, { inputs: () => keys[i++]! })
  for (let n = 0; n < keys.length; n += 1) await stop($ as never)
  expect(w.inputs.map(x => x.count)).toEqual([0, 1, 0, 1, 0])
})

test('PLAN_CONTINUE_MAX is handed to Python raw, and the max it parses is the one used', async ($, on) => {
  const w = harness(on, {
    env: { PLAN_CONTINUE: '1', PLAN_CONTINUE_MAX: '7abc' },
    inputs: () => ({ ...INPUTS, max: 3 }),
  })
  await stop($ as never)
  expect(w.gathered[0]!.max).toBe('7abc')
  expect(w.inputs[0]!.max).toBe(3)
})

test('an unset PLAN_CONTINUE_MAX is sent as null, never guessed here', async ($, on) => {
  const w = harness(on)
  await stop($ as never)
  expect(w.gathered[0]!.max).toBe(null)
})

for (const [label, gone] of [
  ['no root', { root: null, state: null, key: null, max: 3 }],
  ['a refused or escaping state file', { root: ROOT, state: null, key: null, max: 3 }],
] as const) {
  test(`${label} -> allow, no classifier run, handled`, async ($, on) => {
    const w = harness(on, { inputs: () => gone })
    const r = await stop($ as never)
    expect(r.block).toBe(undefined)
    expect(w.inputs.length).toBe(0)
    expect(w.below[0]!.planning_mod_handled).toBe(true)
  })
}

test('the --inputs run refused or timing out -> allow, and the command hook is left to decide', async ($, on) => {
  const w = harness(on, { inputs: () => ({ deny: 'timed out' }) })
  const r = await stop($ as never)
  expect(r.block).toBe(undefined)
  expect(w.inputs.length).toBe(0)
  expect(w.below[0]!.planning_mod_handled).toBe(undefined)
})

for (const [label, fault] of [
  ['refused', { deny: 'timed out' }],
  ['exiting non-zero', { exitCode: 1, stdout: '' }],
  ['unparseable', { exitCode: 0, stdout: 'not json' }],
] as const) {
  test(`the classifier ${label} -> allow, and the command hook is left to decide`, async ($, on) => {
    const w = harness(on, { classify: () => fault })
    const r = await stop($ as never)
    expect(r.block).toBe(undefined)
    expect(w.inputs.length).toBe(1)
    expect(w.below[0]!.planning_mod_handled).toBe(undefined)
  })
}

for (const text of ['', '   ', undefined, 5]) {
  test(`a last message of ${JSON.stringify(text) ?? 'undefined'}: nothing spawned, the command hook reads the transcript`, async ($, on) => {
    const w = harness(on)
    const r = await stop($ as never, text)
    expect(r.block).toBe(undefined)
    expect(w.spawned.length).toBe(0)
    expect(w.below[0]!.planning_mod_handled).toBe(undefined)
  })
}

test("a user Stop hook's block wins, and that turn is not counted as ours", async ($, on) => {
  let userBlocks = true
  const w = harness(on, { below: () => (userBlocks ? { block: 'user says no' } : {}) })
  expect((await stop($ as never)).block).toBe('user says no')
  userBlocks = false
  expect((await stop($ as never)).block).toBe('keep going')
  expect(w.inputs.map(x => x.count)).toEqual([0, 0])
})

test('a counter that cannot be stored allows, saying why: no loop guard, no block', async ($, on) => {
  const w = harness(on, { stateDown: true })
  expect((await stop($ as never)).block).toBe(undefined)
  expect(w.notices.some(n => n.includes('count'))).toBe(true)
})

test('a Stop hook below that throws never makes this hook throw', async ($, on) => {
  harness(on, {
    below: () => {
      throw new Error('user hook broke')
    },
  })
  const r = await stop($ as never)
  expect(r.block === undefined || typeof r.block === 'string').toBe(true)
})

test('a reason that is empty once bounded is no block', async ($, on) => {
  harness(on, { classify: () => ({ decision: 'block', reason: '\u0001\u200b\u202e' }) })
  expect((await stop($ as never)).block).toBe(undefined)
})

test('format and tag characters (soft hyphen, ALM, word joiner, tags) are stripped from a reason', async ($, on) => {
  harness(on, { classify: () => ({ decision: 'block', reason: 'a\u00adb\u061cc\u2060d\u{E0041}\u{E007F}e' }) })
  expect((await stop($ as never)).block).toBe('abcde')
})

test('a hostile 100 KB reason is cut to at most 2 KB with no control characters but newlines', async ($, on) => {
  const huge = `${'x'.repeat(50_000)}\u001b[31m\u0085\u009b2J\n${'y'.repeat(50_000)}`
  harness(on, { classify: () => ({ decision: 'block', reason: huge }) })
  const r = await stop($ as never)
  expect(typeof r.block).toBe('string')
  expect(new TextEncoder().encode(r.block!).length).toBeLessThanOrEqual(2048)
  expect(/[\x00-\x09\x0b-\x1f\x7f-\x9f]/.test(r.block!)).toBe(false)
})

test('C1 controls are stripped from a short reason too', async ($, on) => {
  harness(on, { classify: () => ({ decision: 'block', reason: 'a\u009b2Jb\u0085c\nd' }) })
  expect((await stop($ as never)).block).toBe('a2Jbc\nd')
})

test('bidi, zero-width and lone surrogate characters are stripped from a reason', async ($, on) => {
  harness(on, { classify: () => ({ decision: 'block', reason: 'a\u202eb\u200bc\u2066d\ud800e' }) })
  expect((await stop($ as never)).block).toBe('abcde')
})

test('a stale state is released with the notice and nothing is counted', async ($, on) => {
  const w = harness(on, { classify: () => ({ decision: 'allow', notice: 'plan-continue: 13.0h stale' }) })
  await stop($ as never)
  await stop($ as never)
  expect(w.notices).toEqual(['plan-continue: 13.0h stale', 'plan-continue: 13.0h stale'])
  expect(w.inputs.map(x => x.count)).toEqual([0, 0])
})

test('owned state errors from inputs reach the classifier and visible notice', async ($, on) => {
  const marker = { state_status: 'state_error', note: 'owned snapshot missing' }
  const w = harness(on, {
    inputs: () => ({ root: ROOT, state: marker, key: '||', max: 3 }),
    classify: () => ({ decision: 'allow', notice: 'plan-continue: state_error' }),
  })
  expect((await stop($ as never, 'Next is task 2.1.')).block).toBe(undefined)
  expect(w.inputs[0]!.state).toEqual(marker)
  expect(w.notices).toEqual(['plan-continue: state_error'])
})

test('a changed execution key resets the stored continuation counter', async ($, on) => {
  let completed = 1
  const w = harness(on, {
    inputs: () => ({ root: ROOT, state: { ...STATE, schema_version: 2, rounds: { completed } },
      key: `run|round-${completed}|task|2|2.1`, max: 3 }),
  })
  await stop($ as never)
  await stop($ as never)
  completed = 2
  await stop($ as never)
  expect(w.inputs.map(x => x.count)).toEqual([0, 1, 0])
})
