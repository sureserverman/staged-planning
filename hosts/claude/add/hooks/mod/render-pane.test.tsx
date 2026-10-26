import type { On } from 'claude-code'
import { expect, test } from 'claude-code/testing'

import type { PlanDetail, PlanGroup } from '../../types'
import { PLAN_PANE } from './pane-id'
import { group, ran, seed, world } from './testing'

const SURFACES = ['terminal', 'desktop'] as const

const DETAIL: PlanDetail = {
  plan: '/records/plans/2026-10-03-fixture-plan.md',
  name: 'fixture-plan',
  stages: [
    {
      number: 1,
      name: 'Input parser',
      gate_checked: 3,
      gate_total: 3,
      tasks: [
        { id: '1.1', title: 'tokenizer', status: 'done' },
        { id: '1.2', title: 'grammar', status: 'done' },
      ],
    },
    {
      number: 2,
      name: 'Report output',
      gate_checked: 0,
      gate_total: 2,
      tasks: [
        { id: '2.1', title: 'layout', status: 'done' },
        { id: '2.2', title: 'colours', status: 'partial' },
        { id: '2.3', title: 'export', status: 'open' },
      ],
    },
  ],
}

const GROUPS: PlanGroup[] = [
  group({ name: 'fixture-master', role: 'master', depth: 0, tail: '' }),
  group({ name: 'fixture-plan', role: 'pinned', depth: 1, done: 3, total: 5, stage: 2, task: '2.3', remediation_round: 1, remediation_budget: 2 }),
]

const pane = (bodyColumns = 100) => ({
  plugin: 'planning',
  component: 'Pane' as const,
  requestId: PLAN_PANE,
  props: {
    title: 'Plan',
    isFocused: false,
    bodyColumns,
    placement: 'dock' as const,
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
})

const band = {
  plugin: 'planning',
  component: 'AbovePrompt' as const,
  props: { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 100, scroll: { offset: 0, bodyRows: 10 }, view: {} },
}

function opens(on: On): string[] {
  const opened: string[] = []
  on('ui.open', (_$, e) => {
    opened.push(e.id)
    return { value: { isPlaced: true } } as never
  })
  return opened
}

const withPlan = () => ran(JSON.stringify({ groups: GROUPS, detail: DETAIL }))

async function shown(ui: { findAll: (q: { type: string }) => Promise<{ text: string }[]> }): Promise<string> {
  return (await ui.findAll({ type: 'Text' })).map(t => t.text).join('\n')
}

test('running plan-view opens the plan pane, on every surface', async ($, on) => {
  const opened = opens(on)
  world(on, withPlan)
  for (const surface of SURFACES) {
    const answer = await $.command.run({
      command: 'plan-view',
      args: '',
      origin: { kind: 'composer' },
      presentation: { isFullscreen: surface === 'terminal', columns: 160 },
    } as never)
    expect(opened.at(-1)).toBe(PLAN_PANE)
    expect(typeof (answer as { text?: unknown }).text).toBe('string')
  }
})

test('the pane draws the master, the plan, both stage headers with gates, and every task id', async ($, on) => {
  const w = world(on, withPlan)
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...pane(), surface })
    const text = await shown(ui)
    expect(text).toContain('fixture-master')
    expect(text).toContain('fixture-plan')
    expect(text).toContain('Stage 1')
    expect(text).toContain('Input parser')
    expect(text).toContain('3/3')
    expect(text).toContain('Stage 2')
    expect(text).toContain('0/2')
    for (const id of ['1.1', '1.2', '2.1', '2.2', '2.3']) expect(text).toContain(id)
    expect(text).toMatch(/▶[^\n]*2\.3/)
    expect(text).toContain('↻1/2')
    await ui.unmount()
  }
})

test("a running agent's description appears in the pane, listed before finished ones", async ($, on) => {
  const w = world(on, withPlan)
  await seed($ as never, w.clock)
  await $.tool.call({ tool: 'Agent', description: 'finished reviewer', prompt: 'p', subagent_type: 'planning:code-reviewer' } as never)
  for (const surface of SURFACES) {
    let during = ''
    w.hooks.onTool = async e => {
      if (e.tool !== 'Agent') return
      const ui = await $.ui.mount({ ...pane(), surface })
      during = await shown(ui)
      await ui.unmount()
    }
    await $.tool.call({ tool: 'Agent', description: `Task 2.3 dispatch on ${surface}`, prompt: 'p', subagent_type: 'general-purpose' } as never)
    w.hooks.onTool = undefined
    expect(during).toContain(`Task 2.3 dispatch on ${surface}`)
    expect(during.indexOf(`Task 2.3 dispatch on ${surface}`)).toBeLessThan(during.indexOf('finished reviewer'))
  }
})

test("pressing the band's Plan button opens the same pane id", async ($, on) => {
  const opened = opens(on)
  const w = world(on, withPlan)
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band, surface })
    await ui.press({ key: 'open-plan' })
    expect(opened.at(-1)).toBe(PLAN_PANE)
    await ui.unmount()
  }
})

test('with no model the pane says no plan is executing', async ($, on) => {
  world(on)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...pane(), surface })
    expect(await shown(ui)).toMatch(/no plan is executing/i)
    await ui.unmount()
  }
})

test('no pane line is wider than the pane', async ($, on) => {
  const w = world(on, withPlan)
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...pane(30), surface })
    for (const t of await ui.findAll({ type: 'Text' })) expect([...t.text].length).toBeLessThanOrEqual(30)
    await ui.unmount()
  }
})

test('an interactive start registers /plan-view; a -p start does not', async ($, on) => {
  world(on)
  const registered: string[] = []
  on('command.register', (_$, e) => {
    registered.push((e as { name: string }).name)
    return { value: undefined } as never
  })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
  expect(registered).toEqual([])
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  expect(registered).toEqual(['plan-view'])
})

test('the pane never opens unasked: a start, a refresh and a band draw open nothing', async ($, on) => {
  const opened = opens(on)
  const w = world(on, withPlan)
  on('command.register', () => ({ value: undefined }) as never)
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await w.clock.settle()
  await seed($ as never, w.clock)
  const ui = await $.ui.mount({ ...band, surface: 'terminal' })
  await ui.unmount()
  await w.clock.advance(30_000)
  expect(opened).toEqual([])
})

test('a remediation round already in the tail is not repeated on its own line', async ($, on) => {
  const gate = [group({ name: 'fixture-plan', role: 'pinned', phase: 'gate', task: null, remediation_round: 1, remediation_budget: 2, tail: '· S2/2 ◆ S2 gate ↻1/2' })]
  const w = world(on, () => ran(JSON.stringify({ groups: gate, detail: DETAIL })))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...pane(), surface })
    const text = await shown(ui)
    expect(text.split('↻1/2').length - 1).toBe(1)
    await ui.unmount()
  }
})

test('agents show their outcome: running first, then done, failed and denied', async ($, on) => {
  const w = world(on, withPlan)
  on('agent.list', () => ({ value: [{ id: 'bg1', description: 'bg', type: 'general-purpose', status: 'running' }] }) as never)
  await seed($ as never, w.clock)
  w.hooks.onTool = () => ({ deny: 'no' })
  await $.tool.call({ tool: 'Agent', description: 'refused one', prompt: 'p', subagent_type: 'x' } as never)
  w.hooks.onTool = () => ({ result: 'x', isError: true })
  await $.tool.call({ tool: 'Agent', description: 'broken one', prompt: 'p', subagent_type: 'x' } as never)
  w.hooks.onTool = () => ({ result: { status: 'async_launched', agentId: 'bg1', description: 'bg' } })
  await $.tool.call({ tool: 'Agent', description: 'background one', prompt: 'p', subagent_type: 'x' } as never)
  w.hooks.onTool = undefined
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...pane(), surface })
    const text = await shown(ui)
    expect(text).toMatch(/◌ background one/)
    expect(text).toMatch(/✘ broken one/)
    expect(text).toMatch(/⊘ refused one/)
    expect(text.indexOf('background one')).toBeLessThan(text.indexOf('broken one'))
    await ui.unmount()
  }
})

test("plan-view says so when the surface cannot place the pane", async ($, on) => {
  on('ui.open', () => ({ value: { isPlaced: false, reason: 'terminal is 80 columns; a pane needs 110' } }) as never)
  world(on, withPlan)
  const answer = (await $.command.run({
    command: 'plan-view',
    args: '',
    origin: { kind: 'composer' },
    presentation: { isFullscreen: false, columns: 80 },
  } as never)) as { text?: string }
  expect(answer.text).toContain('110')
})

test('bidi, zero-width, lone surrogate and control characters never reach the pane', async ($, on) => {
  const hostile: PlanDetail = {
    ...DETAIL,
    name: 'evil‮reversed​',
    stages: DETAIL.stages.map(st => ({
      ...st,
      name: `${st.name ?? ''}⁦\x1b[31m`,
      tasks: st.tasks.map(t => ({ ...t, title: `${t.title}\udc00\u009b` })),
    })),
  }
  const w = world(on, () => ran(JSON.stringify({ groups: GROUPS, detail: hostile })))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...pane(100), surface })
    const texts = await ui.findAll({ type: 'Text' })
    expect(texts.length).toBeGreaterThan(3)
    for (const t of texts) expect(/[\p{Cc}\p{Cf}\p{Cs}]/u.test(t.text)).toBe(false)
    await ui.unmount()
  }
})

// ---- a pane per plan (planning-plan-<id>) ----

const MASTER_ID = 'aaaa0001'
const PINNED_ID = 'aaaa0002'
const OTHER_ID = 'aaaa0003'
const OTHER_DETAIL: PlanDetail = {
  plan: '/records/plans/2026-10-01-other-plan.md',
  name: 'other-plan',
  stages: [
    {
      number: 1,
      name: 'Other groundwork',
      gate_checked: 1,
      gate_total: 2,
      tasks: [
        { id: '9.1', title: 'other first', status: 'done' },
        { id: '9.2', title: 'other second', status: 'open' },
      ],
    },
  ],
}
const MASTER_DETAIL: PlanDetail = { plan: '/records/plans/2026-10-02-fixture-master-plan.md', name: 'fixture-master', stages: [] }
const THREE_GROUPS: PlanGroup[] = [
  group({ name: 'fixture-master', role: 'master', depth: 0, done: 1, total: 3, tail: '⊘ GATE BLOCKED',
          tail_spans: [{ text: '⊘ GATE BLOCKED', color: '#db3630', dim: false }], id: MASTER_ID }),
  { ...GROUPS[1]!, id: PINNED_ID },
  group({ name: 'other-plan', role: 'other', depth: 0, done: 1, total: 2, tail: '', tail_spans: [], id: OTHER_ID }),
]
const PALETTE = { green: '#008c2f', red: '#db3630', yellow: '#947006', cyan: '#168191', purple: '#a23efa' }
const withThree = () =>
  ran(JSON.stringify({
    groups: THREE_GROUPS,
    detail: DETAIL,
    details: { [MASTER_ID]: MASTER_DETAIL, [PINNED_ID]: DETAIL, [OTHER_ID]: OTHER_DETAIL },
    palette: PALETTE,
  }))
const paneFor = (id: string, bodyColumns = 100) => ({ ...pane(bodyColumns), requestId: `planning-plan-${id}` })
const PINNED_TASKS = ['1.1', '1.2', '2.1', '2.2', '2.3']

test("a plan's own pane draws its stages and tasks, none of the pinned plan's, no agents and no ▶", async ($, on) => {
  const w = world(on, withThree)
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneFor(OTHER_ID), surface })
    const text = await shown(ui)
    expect(text).toContain('other-plan')
    expect(text).toContain('1/2')
    expect(text).toContain('Stage 1 — Other groundwork')
    expect(text).toContain('9.1')
    expect(text).toContain('9.2')
    for (const id of PINNED_TASKS) expect(text.includes(` ${id} `)).toBe(false)
    expect(text).not.toContain('Agents')
    expect(text).not.toContain('▶')
    await ui.unmount()
  }
})

test("the master's pane draws its header in the band's colours and lists its in-flight sub-plans", async ($, on) => {
  const w = world(on, withThree)
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneFor(MASTER_ID), surface })
    const text = await shown(ui)
    expect(text).toContain('fixture-master')
    expect(text).toContain('fixture-plan')
    expect(text).not.toContain('other-plan')
    const coloured = (await ui.findAll({ type: 'Text' })).map(t => t.props.color)
    expect(coloured).toContain('#db3630')
    expect(coloured).toContain('#008c2f')
    expect(text).not.toContain('Agents')
    expect(text).not.toContain('▶')
    await ui.unmount()
  }
})

test('a pane for a plan no longer in the model says so', async ($, on) => {
  const w = world(on, withThree)
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneFor('ffffffff'), surface })
    expect(await shown(ui)).toContain('This plan is no longer in flight.')
    await ui.unmount()
  }
})

test('every non-pinned pane line fits the pane, and none carries a control character', async ($, on) => {
  const w = world(on, withThree)
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (const id of [MASTER_ID, OTHER_ID]) {
      for (const cols of [30, 100]) {
        const ui = await $.ui.mount({ ...paneFor(id, cols), surface })
        const rows = (await ui.findAll({ type: 'Text' })).filter(t => t.props.wrap === 'truncate')
        for (const r of rows) expect([...r.text].length).toBeLessThanOrEqual(cols)
        for (const r of rows) expect(/[\p{Cc}\p{Cf}\p{Cs}]/u.test(r.text)).toBe(false)
        await ui.unmount()
      }
    }
  }
})

test("pressing a row's own Plan button, then drawing that pane, shows that plan", async ($, on) => {
  const opened = opens(on)
  const w = world(on, withThree)
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const b = await $.ui.mount({ ...band, props: { ...band.props, bodyColumns: 120 }, surface })
    await b.press({ key: `open-plan:${OTHER_ID}` })
    expect(opened.at(-1)).toBe(`planning-plan-${OTHER_ID}`)
    await b.unmount()
    const ui = await $.ui.mount({ ...paneFor(OTHER_ID), surface })
    expect(await shown(ui)).toContain('9.2')
    await ui.unmount()
  }
})

test('plan-view still opens planning-plan, the pinned plan with its agents', async ($, on) => {
  const opened = opens(on)
  world(on, withThree)
  await $.command.run({ command: 'plan-view', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } } as never)
  expect(opened.at(-1)).toBe(PLAN_PANE)
})

// ---- a viewed plan beside the executing one ----

// The viewed plan shares a task id with the executing one, and an agent is
// recorded, so "no ▶" and "no Agents" can fail.
const SHARED_DETAIL: PlanDetail = {
  plan: '/records/plans/2026-10-01-other-plan.md',
  name: 'other-plan',
  stages: [{ number: 2, name: 'Shared ids', gate_checked: 0, gate_total: 1, tasks: [{ id: '2.3', title: 'same id as the pinned task', status: 'open' }] }],
}
const BLOCKED_SUB = group({ name: 'blocked-sub', role: 'child', depth: 1, done: 1, total: 2, id: 'aaaa0005',
  tail: '⊘ GATE BLOCKED', tail_spans: [{ text: '⊘ GATE BLOCKED', color: '#db3630', dim: false }] })
const PINNED_SUB = { ...THREE_GROUPS[1]!, tail_spans: [{ text: '· S2/2 ▶ T2.3', color: null, dim: false }] }
const MIXED: PlanGroup[] = [
  group({ name: 'quiet-master', role: 'master', depth: 0, done: 0, total: 2, tail: '', tail_spans: [], id: MASTER_ID }),
  PINNED_SUB,
  BLOCKED_SUB,
  { ...THREE_GROUPS[2]!, id: OTHER_ID },
]
const withMixed = (details: Record<string, PlanDetail | null>) => () =>
  ran(JSON.stringify({ groups: MIXED, detail: DETAIL, details, palette: PALETTE }))

test("a plan's own pane has no ▶ even on the executing task's id, and no Agents while agents ran", async ($, on) => {
  const w = world(on, withMixed({ [MASTER_ID]: MASTER_DETAIL, [PINNED_ID]: DETAIL, aaaa0005: null, [OTHER_ID]: SHARED_DETAIL }))
  await seed($ as never, w.clock)
  await $.tool.call({ tool: 'Agent', description: 'a recorded reviewer', prompt: 'p', subagent_type: 'planning:code-reviewer' } as never)
  for (const surface of SURFACES) {
    const executing = await $.ui.mount({ ...pane(), surface })
    expect(await shown(executing)).toContain('Agents')
    expect(await shown(executing)).toContain('▶')
    await executing.unmount()
    for (const id of [OTHER_ID, MASTER_ID]) {
      const ui = await $.ui.mount({ ...paneFor(id), surface })
      const text = await shown(ui)
      expect(text).not.toContain('Agents')
      expect(text).not.toContain('a recorded reviewer')
      expect(text.split('\n').some(l => l.startsWith('▶'))).toBe(false)
      if (id === OTHER_ID) expect(text).toContain('2.3 same id as the pinned task')
      await ui.unmount()
    }
  }
})

test("a master's pane keeps a sub-plan's own marker, drops only the executing plan's phase, and draws the tree", async ($, on) => {
  const w = world(on, withMixed({ [MASTER_ID]: MASTER_DETAIL, [PINNED_ID]: DETAIL, aaaa0005: null, [OTHER_ID]: SHARED_DETAIL }))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneFor(MASTER_ID, 120), surface })
    const rows = (await ui.findAll({ type: 'Text' })).filter(t => t.props.wrap === 'truncate').map(t => t.text)
    const blocked = rows.find(r => r.includes('blocked-sub'))
    const pinned = rows.find(r => r.includes('fixture-plan'))
    expect(blocked).toContain('⊘ GATE BLOCKED')
    expect(pinned).not.toContain('▶ T2.3')
    expect(pinned!.startsWith('├─ ')).toBe(true)
    expect(blocked!.startsWith('└─ ')).toBe(true)
    expect(rows.join('\n')).not.toContain('other-plan')
    await ui.unmount()
  }
})

test("a plan pane's header and sub-plan rows use the band's 20-cell bar and one name column when wide", async ($, on) => {
  const w = world(on, withMixed({ [MASTER_ID]: MASTER_DETAIL, [PINNED_ID]: DETAIL, aaaa0005: null, [OTHER_ID]: SHARED_DETAIL }))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (const [cols, cells] of [[120, 20], [80, 10]] as const) {
      const ui = await $.ui.mount({ ...paneFor(MASTER_ID, cols), surface })
      const bars = (await ui.findAll({ type: 'Text' })).filter(t => t.props.wrap === 'truncate' && t.text.includes('▐'))
      expect(bars.length).toBe(3)
      for (const b of bars) expect(/▐([█░]*)▌/.exec(b.text)?.[1]?.length).toBe(cells)
      const cols0 = bars.map(b => [...b.text.slice(0, b.text.indexOf('▐'))].length)
      expect(cols0.every(c => c === cols0[0])).toBe(true)
      await ui.unmount()
    }
  }
})

test("a pinned master's own pane still lists its sub-plans", async ($, on) => {
  const groups = [
    group({ name: 'pinned-master', role: 'pinned', depth: 0, done: 0, total: 2, id: MASTER_ID }),
    group({ name: 'its-sub', role: 'child', depth: 1, done: 1, total: 3, id: PINNED_ID }),
    group({ name: 'unrelated', role: 'other', depth: 0, id: OTHER_ID }),
  ]
  const w = world(on, () => ran(JSON.stringify({ groups, detail: MASTER_DETAIL, details: { [MASTER_ID]: MASTER_DETAIL }, palette: PALETTE })))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneFor(MASTER_ID), surface })
    const text = await shown(ui)
    expect(text).toContain('Sub-plans in flight')
    expect(text).toContain('its-sub')
    expect(text).not.toContain('unrelated')
    await ui.unmount()
  }
})

test("a plan whose breakdown could not be read says so, and a malformed breakdown throws nothing", async ($, on) => {
  const w = world(on, withMixed({ [MASTER_ID]: MASTER_DETAIL, [PINNED_ID]: DETAIL, aaaa0005: null,
                                  [OTHER_ID]: { plan: 'x', stages: [null, { number: 1, name: 'n', gate_checked: 0, gate_total: 0, tasks: 'bad' }] } as never }))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneFor('aaaa0005'), surface })
    expect(await shown(ui)).toContain('Its stages and tasks could not be read.')
    await ui.unmount()
    const bad = await $.ui.mount({ ...paneFor(OTHER_ID), surface })
    expect(await shown(bad)).toContain('other-plan')
    await bad.unmount()
  }
})

test("a sub-plan's own pane lists no siblings, and a master's pane never takes a later plan's sub-plans", async ($, on) => {
  const LATER_CHILD = group({ name: 'later-child', role: 'child', depth: 1, done: 0, total: 1, id: 'aaaa0006' })
  const groups = [...MIXED, LATER_CHILD]
  const w = world(on, () => ran(JSON.stringify({ groups, detail: DETAIL,
    details: { [MASTER_ID]: MASTER_DETAIL, [PINNED_ID]: DETAIL, aaaa0005: null, [OTHER_ID]: SHARED_DETAIL, aaaa0006: null }, palette: PALETTE })))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const sub = await $.ui.mount({ ...paneFor(PINNED_ID), surface })
    const subText = await shown(sub)
    expect(subText).not.toContain('Sub-plans in flight')
    expect(subText).not.toContain('blocked-sub')
    await sub.unmount()
    const master = await $.ui.mount({ ...paneFor(MASTER_ID), surface })
    const masterText = await shown(master)
    expect(masterText).toContain('blocked-sub')
    expect(masterText).not.toContain('later-child')
    await master.unmount()
  }
})

test('a master with no sub-plans and no breakdown says both', async ($, on) => {
  const groups = [group({ name: 'lone-master', role: 'master', depth: 0, id: MASTER_ID }), group({ name: 'x', role: 'pinned', depth: 0, id: PINNED_ID })]
  const w = world(on, () => ran(JSON.stringify({ groups, detail: DETAIL, details: { [MASTER_ID]: null, [PINNED_ID]: DETAIL }, palette: PALETTE })))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneFor(MASTER_ID), surface })
    const text = await shown(ui)
    expect(text).toContain('No sub-plan in flight')
    expect(text).toContain('Its stages and tasks could not be read.')
    await ui.unmount()
  }
})

// ---- every register entry, from the master's breakdown ----

// The master's register as plan-progress.py --json lists it: one finished entry
// discovery never chose, the executing one, an in-flight one with its own marker,
// one not started, and one whose plan link does not resolve.
const REGISTER = [
  { number: 1, title: 'done', status: 'done', plan: '/r/done-sub-plan.md', name: 'done-sub', id: 'aaaa0007', done: 4, total: 4 },
  { number: 2, title: 'pinned', status: 'open', plan: '/r/fixture-plan.md', name: 'fixture-plan', id: PINNED_ID, done: 3, total: 5 },
  { number: 3, title: 'blocked', status: 'open', plan: '/r/blocked-sub-plan.md', name: 'blocked-sub', id: 'aaaa0005', done: 1, total: 2 },
  { number: 4, title: 'waiting', status: 'open', plan: '/r/waiting-sub-plan.md', name: 'waiting-sub', id: 'aaaa0008', done: 0, total: 4 },
  { number: 5, title: 'lost one', status: 'open', plan: null, name: 'lost-sub', id: null, done: null, total: null },
] as const
const withRegister = (subplans: unknown = REGISTER) => () =>
  ran(JSON.stringify({
    groups: MIXED,
    detail: DETAIL,
    details: { [MASTER_ID]: { ...MASTER_DETAIL, subplans }, [PINNED_ID]: DETAIL, aaaa0005: null, [OTHER_ID]: SHARED_DETAIL },
    palette: PALETTE,
  }))
const ORDER = ['done-sub', 'fixture-plan', 'blocked-sub', 'waiting-sub', 'lost one']

async function rowsOf(ui: { findAll: (q: { type: string }) => Promise<{ text: string; props: { wrap?: string } }[]> }) {
  return (await ui.findAll({ type: 'Text' })).filter(t => t.props.wrap === 'truncate').map(t => t.text)
}

test("a master's own pane lists every register entry in order, each with its progress", async ($, on) => {
  const w = world(on, withRegister())
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneFor(MASTER_ID, 120), surface })
    const rows = await rowsOf(ui)
    expect(rows.join('\n')).toContain('Sub-plans 1/5 done')
    const at = ORDER.map(name => rows.findIndex(r => r.includes(name)))
    expect(at.every(i => i >= 0)).toBe(true)
    expect([...at].sort((a, b) => a - b)).toEqual(at)
    const row = (name: string) => rows[at[ORDER.indexOf(name)]!]!
    expect(row('done-sub')).toContain('4/4')
    expect(row('done-sub')).toContain('✔ done')
    expect(row('blocked-sub')).toContain('⊘ GATE BLOCKED')
    expect(row('fixture-plan')).toContain('3/5')
    expect(row('fixture-plan')).not.toContain('▶ T2.3')
    expect(row('waiting-sub')).toContain('0/4')
    expect(row('waiting-sub')).toContain('not started')
    expect(row('lost one')).toContain('plan not found')
    expect(row('lost one')).not.toContain('▐')
    expect(row('lost one').startsWith('└─ ')).toBe(true)
    expect(rows.join('\n')).not.toContain('Sub-plans in flight')
    await ui.unmount()
  }
})

test('plan-view lists every sub-plan of the executing master, the executing one with its task', async ($, on) => {
  const w = world(on, withRegister())
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...pane(120), surface })
    const rows = await rowsOf(ui)
    const text = rows.join('\n')
    expect(text).toContain('quiet-master')
    expect(text).toContain('Sub-plans 1/5 done')
    const at = ORDER.map(name => rows.findIndex(r => r.includes(name)))
    expect(at.every(i => i >= 0)).toBe(true)
    expect([...at].sort((a, b) => a - b)).toEqual(at)
    expect(rows[at[1]!]).toContain('▶ T2.3')
    expect(rows[at[0]!]).toContain('✔ done')
    expect(rows[at[3]!]).toContain('not started')
    expect(text.indexOf('lost one')).toBeLessThan(text.indexOf('Stage 1'))
    for (const id of PINNED_TASKS) expect(text).toContain(id)
    await ui.unmount()
  }
})

test('a master with an empty register says so in both panes', async ($, on) => {
  const w = world(on, withRegister([]))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (const p of [paneFor(MASTER_ID), pane()]) {
      const ui = await $.ui.mount({ ...p, surface })
      expect(await shown(ui)).toContain('No sub-plans in the register')
      if (p.requestId === PLAN_PANE) expect((await rowsOf(ui)).find(r => r.includes('fixture-plan'))).toContain('▶ T2.3')
      await ui.unmount()
    }
  }
})

test('register rows fit the pane and carry no control character from a hostile name', async ($, on) => {
  const hostile = REGISTER.map(s => ({ ...s, name: `${s.name}‮\x1b[31m\udc00` }))
  const w = world(on, withRegister(hostile))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (const cols of [30, 100]) {
      for (const p of [paneFor(MASTER_ID, cols), pane(cols)]) {
        const ui = await $.ui.mount({ ...p, surface })
        const rows = await rowsOf(ui)
        expect(rows.some(r => r.includes('waiting-sub') || r.includes('waiting'))).toBe(true)
        for (const r of rows) expect([...r].length).toBeLessThanOrEqual(cols)
        for (const r of rows) expect(/[\p{Cc}\p{Cf}\p{Cs}]/u.test(r)).toBe(false)
        await ui.unmount()
      }
    }
  }
})

test('an executing sub-plan its master register does not name is still drawn, with its task', async ($, on) => {
  const unnamed = REGISTER.filter(s => s.id !== PINNED_ID)
  const w = world(on, withRegister(unnamed))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const view = await $.ui.mount({ ...pane(120), surface })
    const rows = await rowsOf(view)
    const pinned = rows.find(r => r.includes('fixture-plan'))
    expect(pinned).toContain('▶ T2.3')
    expect(rows.indexOf(pinned!)).toBeGreaterThan(rows.findIndex(r => r.includes('lost one')))
    await view.unmount()
    const own = await $.ui.mount({ ...paneFor(MASTER_ID, 120), surface })
    expect((await rowsOf(own)).some(r => r.includes('fixture-plan'))).toBe(true)
    await own.unmount()
  }
})

test('an entry with no task done reads not started whatever its register status, short of done', async ($, on) => {
  const partial = [{ ...REGISTER[3], status: 'partial' }]
  const w = world(on, withRegister(partial))
  await seed($ as never, w.clock)
  const ui = await $.ui.mount({ ...paneFor(MASTER_ID, 120), surface: 'terminal' })
  expect((await rowsOf(ui)).find(r => r.includes('waiting-sub'))).toContain('not started')
  await ui.unmount()
})

test('a malformed register costs its own rows, never the pane', async ($, on) => {
  const shapes: unknown[] = [
    'not a list',
    { 0: REGISTER[0] },
    [null, 7, 'x', REGISTER[0]],
    [{ ...REGISTER[0], name: 5, title: null, status: 3, id: 9 }],
    [{ ...REGISTER[3], done: '2', total: 4.5 }],
    [{ ...REGISTER[3], name: '', title: 'titled' }],
  ]
  let current: unknown = shapes[0]
  const w = world(on, () => withRegister(current)())
  for (const subplans of shapes) {
    current = subplans
    await seed($ as never, w.clock)
    for (const p of [paneFor(MASTER_ID, 60), pane(60)]) {
      const ui = await $.ui.mount({ ...p, surface: 'terminal' })
      const rows = await rowsOf(ui)
      expect(rows.join('\n')).toContain('quiet-master')
      for (const r of rows) expect([...r].length).toBeLessThanOrEqual(60)
      if (subplans === shapes[5]) expect(rows.join('\n')).toContain('titled')
      await ui.unmount()
    }
  }
})
