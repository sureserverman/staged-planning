import { expect, test } from 'claude-code/testing'

import type { PlanGroup } from '../../types'
import { rowSpans } from './band'
import { group, PALETTE, ran, seed, world } from './testing'

const SURFACES = ['terminal', 'desktop'] as const

const band = (bodyColumns: number, maxRows = 10, hasSurvey = false) => ({
  plugin: 'planning',
  component: 'AbovePrompt' as const,
  props: {
    hasSurvey,
    isWorking: false,
    maxRows,
    bodyColumns,
    scroll: { offset: 0, bodyRows: maxRows },
    view: {},
  },
})

const THREE: PlanGroup[] = [
  group({ name: 'master-plan', role: 'master', depth: 0, tail: '' }),
  group({ name: 'sub-plan-01', role: 'pinned', depth: 1 }),
  group({ name: 'another-plan-with-a-rather-long-name', role: 'other', depth: 0, tail: '' }),
]

function answering(groups: PlanGroup[]) {
  return () => ran(JSON.stringify({ groups, detail: null }))
}

// A row is one truncating Text: the drawn tree keeps no key on a Text, and the
// band's only other Text is the spacer before its button.
async function rowsOf(ui: { findAll: (q: { type: string }) => Promise<{ props: Record<string, unknown>; text: string }[]> }) {
  return (await ui.findAll({ type: 'Text' })).filter(t => t.props.wrap === 'truncate')
}

test('a 3-group model draws 3 rows on every surface', async ($, on) => {
  const w = world(on, answering(THREE))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(120), surface })
    const rows = await rowsOf(ui)
    expect(rows.length).toBe(3)
    expect(rows[0]!.text).toContain('master-plan')
    expect(rows[1]!.text).toContain('sub-plan-01')
    expect(rows[1]!.text).toContain('2/5')
    expect(rows[1]!.text).toContain('▶ T1.3')
    await ui.unmount()
  }
})

test('no row is wider than bodyColumns at 40, 80 and 200', async ($, on) => {
  const w = world(on, answering(THREE))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (const cols of [40, 80, 200]) {
      const ui = await $.ui.mount({ ...band(cols), surface })
      const rows = await rowsOf(ui)
      expect(rows.length).toBe(3)
      for (const row of rows) expect([...row.text].length).toBeLessThanOrEqual(cols)
      const button = await ui.find({ key: 'open-plan' })
      expect(button).toBeDefined()
      expect([...rows[0]!.text].length + '[ Plan ]'.length + 1).toBeLessThanOrEqual(cols)
      await ui.unmount()
    }
  }
})

test('an empty model passes through to what is beneath', async ($, on) => {
  const w = world(on, answering([]))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>beneath: engine band</Text>
  })
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(80), surface })
    expect(await ui.find({ type: 'Text', text: 'beneath:' })).toBeDefined()
    expect((await rowsOf(ui)).length).toBe(0)
    await ui.unmount()
  }
})

test('no model at all passes through', async ($, on) => {
  world(on)
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>beneath: engine band</Text>
  })
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(80), surface })
    expect(await ui.find({ type: 'Text', text: 'beneath:' })).toBeDefined()
    await ui.unmount()
  }
})

test('a survey holding the band passes through', async ($, on) => {
  const w = world(on, answering(THREE))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>beneath: survey</Text>
  })
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(80, 10, true), surface })
    expect(await ui.find({ type: 'Text', text: 'beneath:' })).toBeDefined()
    expect((await rowsOf(ui)).length).toBe(0)
    await ui.unmount()
  }
})

test('a 12-group model at maxRows 4 draws 4 rows', async ($, on) => {
  const twelve = Array.from({ length: 12 }, (_, i) => group({ name: `plan-${i}`, role: i === 0 ? 'pinned' : 'other' }))
  const w = world(on, answering(twelve))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(80, 4), surface })
    const rows = await rowsOf(ui)
    expect(rows.length).toBe(4)
    expect(rows[3]!.text).toContain('9 more')
    await ui.unmount()
  }
})

test('no drawn text carries an escape, even from a hostile name or tail', async ($, on) => {
  const hostile = [group({ name: 'evil\x1b[31mred', tail: '· \x1b]0;title\x07 S1/2' })]
  const w = world(on, answering(hostile))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(80), surface })
    const texts = await ui.findAll({ type: 'Text' })
    expect(texts.length).toBeGreaterThan(0)
    for (const t of texts) expect(/[\x00-\x1f\x7f]/.test(t.text)).toBe(false)
    await ui.unmount()
  }
})

test('a stale model is marked', async ($, on) => {
  let fail = false
  const w = world(on, () => {
    if (fail) throw new Error('timed out')
    return ran(JSON.stringify({ groups: [group()], detail: null }))
  })
  await seed($ as never, w.clock)
  fail = true
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(80), surface })
    const rows = await rowsOf(ui)
    expect(rows[0]!.text).toContain('stale')
    await ui.unmount()
  }
})

test('a long name is clipped before the counts: bar and done/total always show', async ($, on) => {
  const long = [group({ name: '2031-04-17 example-app Widget Cache Rewrite and Clean-Up', done: 3, total: 6 })]
  const w = world(on, answering(long))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (const cols of [40, 60]) {
      const ui = await $.ui.mount({ ...band(cols), surface })
      const row = (await rowsOf(ui))[0]!.text
      expect(row).toContain('3/6')
      expect(row).toContain('▐')
      await ui.unmount()
    }
  }
})

test('the stale marker survives a long tail', async ($, on) => {
  let fail = false
  const w = world(on, () => {
    if (fail) throw new Error('timed out')
    return ran(JSON.stringify({ groups: [group({ tail: `· S1/2 ▶ T1.3 ${'very long task description '.repeat(6)}` })], detail: null }))
  })
  await seed($ as never, w.clock)
  fail = true
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(60), surface })
    expect((await rowsOf(ui))[0]!.text).toContain('stale')
    await ui.unmount()
  }
})

test('maxRows 0 draws nothing of its own', async ($, on) => {
  const w = world(on, answering(THREE))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>beneath: engine band</Text>
  })
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(80, 0), surface })
    expect((await rowsOf(ui)).length).toBe(0)
    expect(await ui.find({ type: 'Text', text: 'beneath:' })).toBeDefined()
    await ui.unmount()
  }
})

test('the pinned plan stays visible when the rows run out', async ($, on) => {
  const many = Array.from({ length: 12 }, (_, i) =>
    group({ name: `plan-${i}`, role: i === 7 ? 'pinned' : 'other', depth: 0 }),
  )
  const w = world(on, answering(many))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (const maxRows of [1, 4]) {
      const ui = await $.ui.mount({ ...band(80, maxRows), surface })
      const rows = await rowsOf(ui)
      expect(rows.length).toBe(maxRows)
      expect(rows.some(r => r.text.includes('plan-7'))).toBe(true)
      await ui.unmount()
    }
  }
})

test('a pinned sub-plan keeps its master above it when rows run out', async ($, on) => {
  const groups = [
    group({ name: 'other-a', role: 'other', depth: 0 }),
    group({ name: 'other-b', role: 'other', depth: 0 }),
    group({ name: 'the-master', role: 'master', depth: 0 }),
    group({ name: 'sub-1', role: 'child', depth: 1 }),
    group({ name: 'sub-2', role: 'pinned', depth: 1 }),
  ]
  const w = world(on, answering(groups))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(80, 3), surface })
    const rows = (await rowsOf(ui)).map(r => r.text)
    expect(rows[0]).toContain('the-master')
    expect(rows[1]).toContain('sub-2')
    expect(rows[1]).toContain('└─ ')
    expect(rows[2]).toContain('more')
    await ui.unmount()
  }
})

test('below 24 columns the Plan button is dropped and the row keeps the width', async ($, on) => {
  const w = world(on, answering(THREE))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(20), surface })
    expect(await ui.find({ key: 'open-plan' })).toBe(undefined)
    for (const row of await rowsOf(ui)) expect([...row.text].length).toBeLessThanOrEqual(20)
    await ui.unmount()
  }
})

test('C1 controls (CSI U+009B) never reach a surface', async ($, on) => {
  const w = world(on, answering([group({ name: 'evil\u009b31mred', tail: '· \u0085next' })]))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(80), surface })
    for (const t of await ui.findAll({ type: 'Text' })) expect(/[\x00-\x1f\x7f-\x9f]/.test(t.text)).toBe(false)
    await ui.unmount()
  }
})

test('bidi, zero-width and lone surrogate characters never reach a surface', async ($, on) => {
  const w = world(on, answering([group({ name: 'evil\u202ereversed\u200b', tail: '· \u2066x\udc00y' })]))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(80), surface })
    const texts = await ui.findAll({ type: 'Text' })
    expect(texts.some(t => t.text.includes('evilreversed'))).toBe(true)
    for (const t of texts) expect(/[\p{Cc}\p{Cf}\p{Cs}]/u.test(t.text)).toBe(false)
    await ui.unmount()
  }
})

test('drawing the band runs no process', async ($, on) => {
  const w = world(on, answering(THREE))
  await seed($ as never, w.clock)
  const before = w.runs.length
  for (const surface of SURFACES) {
    for (const cols of [40, 120]) {
      const ui = await $.ui.mount({ ...band(cols), surface })
      await ui.unmount()
    }
  }
  expect(w.runs.length).toBe(before)
})

// The live window as a main-loop turn's end reports it: `engineUsage` answers
// beneath (registered before the test first calls $), `turnEnds` ends a turn, and
// the context hook stores the figures for the band (no state file on disk here,
// so no sidecar is written).
function engineUsage(on: Parameters<typeof world>[0], percent: number) {
  on('session.usage', () => ({ value: { startedAt: 0, context: { window: 1_000_000, tokens: 250_000, percent }, rateLimits: [] } }) as never)
  on('turn.complete', () => ({ text: '' }))
}

const turnEnds = ($: unknown) =>
  ($ as { turn: { complete: (i: never) => Promise<unknown> } }).turn.complete(
    { answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as never,
  )

test('the pinned row shows the context in use, and only the pinned row', async ($, on) => {
  const w = world(on, answering(THREE))
  engineUsage(on, 25)
  await seed($ as never, w.clock)
  await turnEnds($)
  for (const surface of ['terminal', 'desktop'] as const) {
    for (const cols of [60, 160]) {
      const ui = await $.ui.mount({ ...band(cols), surface })
      const rows = await rowsOf(ui)
      expect(rows[1]!.text).toContain('context 25%')
      expect(rows[1]!.text).toContain('2/5')
      expect(rows[0]!.text).not.toContain('context')
      expect(rows[2]!.text).not.toContain('context')
      for (const row of rows) expect([...row.text].length).toBeLessThanOrEqual(cols)
      // The context is reserved in the shared column, so the bars still line up.
      const bars = rows.map(r => columnOf(r.text, /▐/))
      expect(bars.every(c => c > 0 && c === bars[0])).toBe(true)
      await ui.unmount()
    }
  }
})

test('no context figure yet: the pinned row shows none', async ($, on) => {
  const w = world(on, answering([group()]))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(120), surface })
    expect((await rowsOf(ui))[0]!.text).not.toContain('context')
    await ui.unmount()
  }
})

test('the context figure gives way before the counts: done/total survives every width', async ($, on) => {
  const w = world(on, answering([group({ name: 'fixture-plan', done: 12, total: 34 })]))
  engineUsage(on, 25)
  await seed($ as never, w.clock)
  await turnEnds($)
  for (const surface of SURFACES) {
    let shown = 0
    for (let cols = 12; cols <= 80; cols += 1) {
      const ui = await $.ui.mount({ ...band(cols), surface })
      const row = (await rowsOf(ui))[0]!.text
      const width = cols >= 24 ? cols - 12 : cols
      expect([...row].length).toBeLessThanOrEqual(width)
      // '⚙ ' (2) + NAME_MIN (8) + ' ▐██████████▌' (13) + ' 12/34 (35%)' (12): the floor
      // below which a row is cut whole.
      if (width >= 35) expect(row).toContain('12/34')
      if (row.includes('context')) {
        expect(row).toContain('context 25%')
        expect(row).toContain('12/34')
        shown += 1
      }
      await ui.unmount()
    }
    expect(shown).toBeGreaterThan(0)
  }
})

// A drawn row: the truncating Text, and the nested Texts that carry its pieces.
// A drawn element's `props` is left out when it has none.
type Found = { props?: Record<string, unknown>; text: string; children: unknown[] }
function pieces(row: Found): { text: string; color?: unknown; dim?: unknown }[] {
  return (row.children as unknown[])
    .filter((c): c is Found => typeof c === 'object' && c !== null)
    .map(c => ({
      text: (c.children as unknown[]).filter(x => typeof x === 'string').join(''),
      color: c.props?.color,
      dim: c.props?.dimColor,
    }))
}

const COLOURED: PlanGroup[] = [
  group({ name: 'master-plan', role: 'master', depth: 0, tail: '⊘ GATE BLOCKED',
          tail_spans: [{ text: '⊘ GATE BLOCKED', color: PALETTE.red, dim: false }] }),
  group({ name: 'sub-plan-01', role: 'pinned', depth: 1, done: 2, total: 5, tail: '· S1/2 ▶ T1.3',
          tail_spans: [{ text: '·', color: null, dim: true }, { text: ' S1/2 ', color: null, dim: false },
                       { text: '▶ T1.3', color: PALETTE.green, dim: false }] }),
  group({ name: 'another-plan', role: 'other', depth: 0, tail: '', tail_spans: [] }),
]

function answeringPalette(groups: PlanGroup[]) {
  return () => ran(JSON.stringify({ groups, detail: null, palette: PALETTE }))
}

test('the bar fill is drawn in the palette green, the pinned name in cyan, the others dim', async ($, on) => {
  const w = world(on, answeringPalette(COLOURED))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(120), surface })
    const rows = await rowsOf(ui)
    expect(rows.length).toBe(3)
    for (const [i, row] of rows.entries()) {
      const p = pieces(row as Found)
      const fill = p.find(x => x.text.includes('█'))
      expect(fill?.color).toBe(PALETTE.green)
      const name = p.find(x => x.text.includes(COLOURED[i]!.name))
      if (COLOURED[i]!.role === 'pinned') {
        expect(name?.color).toBe(PALETTE.cyan)
      } else {
        expect(name?.color).toBe(undefined)
        expect(name?.dim).toBe(true)
      }
      expect(p.find(x => x.text.includes('⚙'))).toBeDefined()
    }
    await ui.unmount()
  }
})

test('a tail span keeps its colour, and the row reads (40%) for 2/5', async ($, on) => {
  const w = world(on, answeringPalette(COLOURED))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(120), surface })
    const rows = await rowsOf(ui)
    const blocked = pieces(rows[0] as Found).find(x => x.text.includes('⊘ GATE BLOCKED'))
    expect(blocked?.color).toBe('#db3630')
    expect(rows[1]!.text).toContain('2/5')
    expect(rows[1]!.text).toContain('(40%)')
    const pct = pieces(rows[1] as Found).find(x => x.text.includes('(40%)'))
    expect(pct?.dim).toBe(true)
    expect(rows[1]!.text).toContain('└─ ')
    await ui.unmount()
  }
})

test('the bar has 20 cells at 120 columns and 10 at 80', async ($, on) => {
  const w = world(on, answeringPalette(COLOURED))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (const [cols, cells] of [[120, 20], [80, 10]] as const) {
      const ui = await $.ui.mount({ ...band(cols), surface })
      for (const row of await rowsOf(ui)) {
        const bar = /▐([█░]*)▌/.exec(row.text)
        expect(bar?.[1]?.length).toBe(cells)
      }
      await ui.unmount()
    }
  }
})

test('coloured rows fit bodyColumns at 40, 80 and 200, and carry no escape', async ($, on) => {
  const hostile = [...COLOURED, group({ name: 'evil\x1b[31mred', role: 'other', tail: 'x\x1b[2Jy',
                                         tail_spans: [{ text: 'x\x1b[2Jy', color: PALETTE.red, dim: false }] })]
  const w = world(on, answeringPalette(hostile))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (const cols of [40, 80, 200]) {
      const ui = await $.ui.mount({ ...band(cols), surface })
      const rows = await rowsOf(ui)
      expect(rows.length).toBe(4)
      for (const row of rows) expect([...row.text].length).toBeLessThanOrEqual(cols)
      for (const t of await ui.findAll({ type: 'Text' })) expect(/[\x00-\x1f\x7f-\x9f]/.test(t.text)).toBe(false)
      await ui.unmount()
    }
  }
})

test('an older script (no palette, no tail_spans) still draws every row, colours from the theme', async ($, on) => {
  const w = world(on, answering(THREE))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(120), surface })
    const rows = await rowsOf(ui)
    expect(rows.length).toBe(3)
    expect(rows[1]!.text).toContain('▶ T1.3')
    expect(pieces(rows[1] as Found).find(x => x.text.includes('█'))?.color).toBe('success')
    await ui.unmount()
  }
})

const FIVE: PlanGroup[] = [
  group({ name: 'a-master-with-a-name', role: 'master', depth: 0, done: 9, total: 10, tail: '', tail_spans: [] }),
  group({ name: 'sub-01', role: 'child', depth: 1, done: 1, total: 2, tail: '', tail_spans: [] }),
  group({ name: 'sub-02-the-executing-one', role: 'pinned', depth: 1, done: 12, total: 40 }),
  group({ name: 'x', role: 'other', depth: 0, done: 9, total: 10, tail: '⊘ GATE BLOCKED' }),
  group({ name: 'an-other-plan-whose-name-runs-on-and-on-past-the-cap', role: 'other', depth: 0, done: 1, total: 2 }),
]

// The column of the bar's `▐` and of the `(` opening the percentage, on every row.
const columnOf = (text: string, re: RegExp): number => {
  const m = re.exec(text)
  return m === null ? -1 : [...text.slice(0, m.index)].length
}

for (const [label, groups] of [['3 groups', COLOURED], ['5 groups', FIVE]] as const) test(`every plan row starts its bar and its percentage at one column: ${label}`, async ($, on) => {
  {
    const w = world(on, answeringPalette(groups))
    await seed($ as never, w.clock)
    for (const surface of SURFACES) {
      for (const cols of [60, 120, 200]) {
        const ui = await $.ui.mount({ ...band(cols), surface })
        const rows = await rowsOf(ui)
        expect(rows.length).toBe(groups.length)
        const bars = rows.map(r => columnOf(r.text, /▐/))
        const pcts = rows.map(r => columnOf(r.text, /\(\d+%\)/))
        expect(bars.every(c => c > 0 && c === bars[0])).toBe(true)
        expect(pcts.every(c => c > 0 && c === pcts[0])).toBe(true)
        for (const row of rows) expect([...row.text].length).toBeLessThanOrEqual(cols)
        await ui.unmount()
      }
    }
  }
})

const IDS = ['aaaa0001', 'bbbb0002', 'cccc0003']
const WITH_IDS: PlanGroup[] = COLOURED.map((g, i) => ({ ...g, id: IDS[i] }))

function opensPanes(on: Parameters<typeof world>[0]): { id: string; title?: string }[] {
  const opened: { id: string; title?: string }[] = []
  on('ui.open', (_$, e) => {
    opened.push({ id: e.id, title: (e as { title?: string }).title })
    return { value: { isPlaced: true } } as never
  })
  return opened
}

test('with 3 plans, every plan row has its own Plan button opening its own pane', async ($, on) => {
  const opened = opensPanes(on)
  const w = world(on, answeringPalette(WITH_IDS))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(120), surface })
    const buttons = await ui.findAll({ type: 'Button' })
    expect(buttons.length).toBe(3)
    expect(new Set(buttons.map(b => b.key)).size).toBe(3)
    // Exactly these props and no other: no keyboard shortcut is bound to a band Button.
    for (const b of buttons) expect(Object.keys(b.props).filter(k => k !== 'key').sort()).toEqual(
      b.key === 'open-plan' ? ['label'] : ['dimColor', 'label'],
    )
    // the pinned row (sub-plan-01) keeps the plain pane; the others open their own
    await ui.press({ key: 'open-plan' })
    expect(opened.at(-1)?.id).toBe('planning-plan')
    for (const i of [0, 2]) {
      await ui.press({ key: `open-plan:${IDS[i]}` })
      expect(opened.at(-1)?.id).toBe(`planning-plan-${IDS[i]}`)
      expect(opened.at(-1)?.title).toBe(WITH_IDS[i]!.name)
    }
    const pinnedButton = buttons.find(b => b.key === 'open-plan')
    expect(pinnedButton?.props.dimColor).not.toBe(true)
    for (const b of buttons.filter(b => b.key !== 'open-plan')) expect(b.props.dimColor).toBe(true)
    await ui.unmount()
  }
})

test('a 1-plan model draws exactly one Plan button', async ($, on) => {
  const w = world(on, answeringPalette([{ ...WITH_IDS[1]!, depth: 0 }]))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(120), surface })
    const buttons = await ui.findAll({ type: 'Button' })
    expect(buttons.map(b => b.key)).toEqual(['open-plan'])
    await ui.unmount()
  }
})

// A plan in flight that no state file pins (its executor never wrote one): the
// executing-plan pane would say no plan is executing, so the lone button opens
// the row's own pane.
test('a lone plan nothing pins: its button opens that plan\'s own pane', async ($, on) => {
  const opened = opensPanes(on)
  const w = world(on, answeringPalette([{ ...WITH_IDS[2]! }]))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(120), surface })
    const buttons = await ui.findAll({ type: 'Button' })
    expect(buttons.map(b => b.key)).toEqual([`open-plan:${IDS[2]}`])
    await ui.press({ key: `open-plan:${IDS[2]}` })
    expect(opened.at(-1)?.id).toBe(`planning-plan-${IDS[2]}`)
    expect(opened.at(-1)?.title).toBe(WITH_IDS[2]!.name)
    await ui.unmount()
  }
})

test('a lone pinned plan\'s button still opens the executing-plan pane', async ($, on) => {
  const opened = opensPanes(on)
  const w = world(on, answeringPalette([{ ...WITH_IDS[1]!, depth: 0 }]))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(120), surface })
    await ui.press({ key: 'open-plan' })
    expect(opened.at(-1)?.id).toBe('planning-plan')
    await ui.unmount()
  }
})

test('a master\'s lone button opens the executing-plan pane while its sub-plan is pinned', async ($, on) => {
  const opened = opensPanes(on)
  const w = world(on, answeringPalette([{ ...WITH_IDS[0]! }, { ...WITH_IDS[1]!, id: undefined }]))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(120), surface })
    expect((await ui.findAll({ type: 'Button' })).map(b => b.key)).toEqual(['open-plan'])
    await ui.press({ key: 'open-plan' })
    expect(opened.at(-1)?.id).toBe('planning-plan')
    await ui.unmount()
  }
})

test('a lone plan nothing pins, without a valid id, keeps the plain button', async ($, on) => {
  const w = world(on, answeringPalette([group({ name: 'p', role: 'other', id: undefined })]))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(120), surface })
    expect((await ui.findAll({ type: 'Button' })).map(b => b.key)).toEqual(['open-plan'])
    await ui.unmount()
  }
})

test('12 plans at maxRows 4 draw 3 buttons and none on the "more" row', async ($, on) => {
  const twelve = Array.from({ length: 12 }, (_, i) =>
    group({ name: `plan-${i}`, role: i === 0 ? 'pinned' : 'other', id: `0000000${i.toString(16)}`.slice(-8) }),
  )
  const w = world(on, answeringPalette(twelve))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(80, 4), surface })
    const buttons = await ui.findAll({ type: 'Button' })
    expect(buttons.length).toBe(3)
    const rows = await rowsOf(ui)
    expect(rows[3]!.text).toContain('9 more')
    await ui.unmount()
  }
})

test('at 20 columns no row has a button; every row and its button fit bodyColumns', async ($, on) => {
  const w = world(on, answeringPalette(WITH_IDS))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const narrow = await $.ui.mount({ ...band(20), surface })
    expect((await narrow.findAll({ type: 'Button' })).length).toBe(0)
    await narrow.unmount()
    for (const cols of [40, 80, 200]) {
      const ui = await $.ui.mount({ ...band(cols), surface })
      for (const row of await rowsOf(ui)) {
        expect([...row.text].length + ' [ Plan ]'.length).toBeLessThanOrEqual(cols)
      }
      await ui.unmount()
    }
  }
})

// ---- Rounding, padding, ids and alignment at the edges ----

test('the fill rounds half to even, as the status line does: 1/8 and 5/8 at 20 cells', async ($, on) => {
  const w = world(on, answeringPalette([
    group({ name: 'one-eighth', role: 'pinned', done: 1, total: 8, id: 'aaaa0001' }),
    group({ name: 'five-eighths', role: 'other', done: 5, total: 8, id: 'aaaa0002' }),
    group({ name: 'over', role: 'other', done: 9, total: 8, id: 'aaaa0003' }),
    group({ name: 'three-eighths', role: 'other', done: 3, total: 8, id: 'aaaa0004' }),
  ]))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(140), surface })
    const fills = (await rowsOf(ui)).map(r => /▐(█*)(░*)▌/.exec(r.text))
    // Python round(): 20*1/8 = 2.5 -> 2, 20*5/8 = 12.5 -> 12
    expect(fills[0]?.[1]?.length).toBe(2)
    expect(fills[1]?.[1]?.length).toBe(12)
    // done > total: the band never draws past its 20 cells, and says 112% as the status line does
    expect((fills[2]?.[1]?.length ?? 0) + (fills[2]?.[2]?.length ?? 0)).toBe(20)
    expect((await rowsOf(ui))[2]!.text).toContain('9/8 (112%)')
    // 20*3/8 = 7.5 -> 8: a tie with an odd quotient rounds up
    expect(fills[3]?.[1]?.length).toBe(8)
    await ui.unmount()
  }
})

test('every row with a button pads its text to one width, so the buttons line up', async ($, on) => {
  const w = world(on, answeringPalette(WITH_IDS))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (const cols of [60, 120, 200]) {
      const ui = await $.ui.mount({ ...band(cols), surface })
      const rows = await rowsOf(ui)
      expect(rows.length).toBe(3)
      for (const row of rows) expect([...row.text].length).toBe(cols - 12)
      await ui.unmount()
    }
  }
})

test('a pinned sub-plan stays drawn at maxRows 1 and 2, its master giving way', async ($, on) => {
  const groups = [
    group({ name: 'the-master', role: 'master', depth: 0 }),
    group({ name: 'the-sub', role: 'pinned', depth: 1 }),
    group({ name: 'an-other', role: 'other', depth: 0 }),
  ]
  const w = world(on, answeringPalette(groups))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (const maxRows of [1, 2]) {
      const ui = await $.ui.mount({ ...band(80, maxRows), surface })
      const rows = (await rowsOf(ui)).map(r => r.text)
      expect(rows.length).toBe(maxRows)
      expect(rows.some(r => r.includes('the-sub'))).toBe(true)
      await ui.unmount()
    }
  }
})

test('the stale marker and the counts survive every width the row floor allows', async ($, on) => {
  let fail = false
  const w = world(on, () => {
    if (fail) throw new Error('timed out')
    return ran(JSON.stringify({ groups: [group()], detail: null, palette: PALETTE }))
  })
  await seed($ as never, w.clock)
  fail = true
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (let cols = 12; cols <= 80; cols += 1) {
      const ui = await $.ui.mount({ ...band(cols), surface })
      const row = (await rowsOf(ui))[0]!.text
      const width = cols >= 24 ? cols - 12 : cols
      expect([...row].length).toBeLessThanOrEqual(width)
      // '⚙ ' (2) + NAME_MIN (8) + ' ▐██████████▌ 2/5' (17) + ' (stale)' (8): the pct gives way first.
      if (width >= 35) {
        expect(row).toContain('2/5')
        expect(row).toContain('(stale)')
      }
      await ui.unmount()
    }
  }
})

test('only a #rrggbb from the script, or a theme key, ever reaches a Text colour', async ($, on) => {
  const bad = { green: 'red', cyan: 7, red: '#12', yellow: '\x1b[31m', purple: null }
  const groups = [
    group({ name: 'p', role: 'pinned', tail: 'abcd', tail_spans: [
      { text: 'a', color: 'red', dim: false }, { text: 'b', color: '#12', dim: false },
      { text: 'c', color: '#db3630\n', dim: false }, { text: 'd', color: 42 as never, dim: 'yes' as never },
    ] }),
    group({ name: 'q', role: 'other' }),
  ]
  const w = world(on, () => ran(JSON.stringify({ groups, detail: null, palette: bad })))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(120), surface })
    const colours = (await ui.findAll({ type: 'Text' })).map(t => t.props.color).filter(c => c !== undefined)
    for (const c of colours) expect(c === 'success' || c === 'suggestion' || /^#[0-9a-f]{6}$/i.test(String(c))).toBe(true)
    const p = pieces((await rowsOf(ui))[0] as Found)
    expect(p.find(x => x.text.includes('█'))?.color).toBe('success')
    expect(p.find(x => x.text.includes('⚙'))?.color).toBe('suggestion')
    await ui.unmount()
  }
})

for (const [label, ids] of [
  ['one missing', ['aaaa0001', undefined]],
  ['9 hex', ['aaaa0001', 'aaaa00022']],
  ['uppercase', ['aaaa0001', 'AAAA0002']],
  ['a slash', ['aaaa0001', 'aaa/0002']],
  ['a duplicate', ['aaaa0001', 'aaaa0001']],
] as const) {
  test(`two plans with an id that is ${label}: one button, on row 0`, async ($, on) => {
    const groups = [group({ name: 'p', role: 'pinned', id: ids[0] }), group({ name: 'q', role: 'other', id: ids[1] })]
    const w = world(on, answeringPalette(groups))
    await seed($ as never, w.clock)
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ ...band(120), surface })
      expect((await ui.findAll({ type: 'Button' })).map(b => b.key)).toEqual(['open-plan'])
      await ui.unmount()
    }
  })
}

test('buttons appear from 24 columns, not at 23', async ($, on) => {
  const w = world(on, answeringPalette(WITH_IDS))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (const [cols, n] of [[23, 0], [24, 3]] as const) {
      const ui = await $.ui.mount({ ...band(cols), surface })
      expect((await ui.findAll({ type: 'Button' })).length).toBe(n)
      await ui.unmount()
    }
  }
})

test('stale, context and buttons at once: the bars still line up and every row fits', async ($, on) => {
  let fail = false
  const w = world(on, () => {
    if (fail) throw new Error('timed out')
    return ran(JSON.stringify({ groups: WITH_IDS, detail: null, palette: PALETTE }))
  })
  engineUsage(on, 25)
  await seed($ as never, w.clock)
  await turnEnds($)
  fail = true
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (const cols of [100, 160]) {
      const ui = await $.ui.mount({ ...band(cols), surface })
      const rows = await rowsOf(ui)
      expect(rows[0]!.text).toContain('(stale)')
      expect(rows[1]!.text).toContain('context 25%')
      const bars = rows.map(r => columnOf(r.text, /▐/))
      expect(bars.every(c => c > 0 && c === bars[0])).toBe(true)
      for (const row of rows) expect([...row.text].length).toBeLessThanOrEqual(cols - 12)
      await ui.unmount()
    }
  }
})

test('a sub-plan with another sub-plan below it is drawn ├─, the last └─', async ($, on) => {
  const w = world(on, answeringPalette(FIVE))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(120), surface })
    const rows = (await rowsOf(ui)).map(r => r.text)
    expect(rows[1]!.startsWith('├─ ')).toBe(true)
    expect(rows[2]!.startsWith('└─ ')).toBe(true)
    await ui.unmount()
  }
})

test('the name column is the status line\'s: 46 cells of tree glyph and name, ⚙ beside them', async ($, on) => {
  const name = 'n'.repeat(60)
  const w = world(on, answeringPalette([group({ name, role: 'pinned', id: 'aaaa0001' }), group({ name: 'x', role: 'other', id: 'aaaa0002' })]))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(200), surface })
    const row = (await rowsOf(ui))[0]!.text
    // '⚙ ' + 46 cells of name (45 + …), then the bar
    expect(columnOf(row, /▐/)).toBe(2 + 46 + 1)
    await ui.unmount()
  }
})

test('a count that is not a whole number reads as 0, never NaN, null or 1.5', async ($, on) => {
  const odd = [
    group({ name: 'a', done: null as never, total: 5, id: 'aaaa0001' }),
    group({ name: 'b', role: 'other', done: 'a' as never, total: 5, id: 'aaaa0002' }),
    group({ name: 'c', role: 'other', done: 1.5, total: 5, id: 'aaaa0003' }),
    group({ name: 'd', role: 'other', done: 1, total: 'x' as never, id: 'aaaa0004' }),
  ]
  const w = world(on, answeringPalette(odd))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (const cols of [120, Number.NaN]) {
      const ui = await $.ui.mount({ ...band(cols), surface })
      for (const t of await ui.findAll({ type: 'Text' })) expect(/NaN|null|undefined|1\.5/.test(t.text)).toBe(false)
      if (cols === 120) {
        const rows = (await rowsOf(ui)).map(r => r.text)
        for (const r of rows.slice(0, 3)) {
          expect(r).toContain('0/5')
          expect(r).toContain('(0%)')
        }
        expect(rows[3]).not.toContain('▐')
      }
      await ui.unmount()
    }
  }
})

test('a stale first row with a long name: its mark is reserved in the shared column', async ($, on) => {
  const long = WITH_IDS.map(g => ({ ...g, name: `${g.name}-${'z'.repeat(50)}` }))
  let fail = false
  const w = world(on, () => {
    if (fail) throw new Error('timed out')
    return ran(JSON.stringify({ groups: long, detail: null, palette: PALETTE }))
  })
  await seed($ as never, w.clock)
  fail = true
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    for (const cols of [100, 120]) {
      const ui = await $.ui.mount({ ...band(cols), surface })
      const rows = await rowsOf(ui)
      expect(rows[0]!.text).toContain('(stale)')
      const bars = rows.map(r => columnOf(r.text, /▐/))
      expect(bars.every(c => c > 0 && c === bars[0])).toBe(true)
      await ui.unmount()
    }
  }
})

test('the fill rounds half to even at 10 cells too: 1/4 and 3/4', async ($, on) => {
  const w = world(on, answeringPalette([
    group({ name: 'q1', role: 'pinned', done: 1, total: 4, id: 'aaaa0001' }),
    group({ name: 'q3', role: 'other', done: 3, total: 4, id: 'aaaa0002' }),
  ]))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(80), surface })
    const fills = (await rowsOf(ui)).map(r => /▐(█*)░*▌/.exec(r.text)?.[1]?.length)
    expect(fills).toEqual([2, 8])
    await ui.unmount()
  }
})

test('a sub-plan row\'s tree glyph counts inside the 46-cell name column', async ($, on) => {
  const name = 'n'.repeat(60)
  const w = world(on, answeringPalette([
    group({ name: 'm', role: 'master', depth: 0, id: 'aaaa0001' }),
    group({ name, role: 'pinned', depth: 1, id: 'aaaa0002' }),
  ]))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(200), surface })
    const row = (await rowsOf(ui))[1]!.text
    // '└─ ' + '⚙ ' + 43 cells of name: the glyph and name fill 46, ⚙ beside them
    expect(row.startsWith(`└─ ⚙ ${'n'.repeat(42)}…`)).toBe(true)
    expect(columnOf(row, /▐/)).toBe(2 + 46 + 1)
    await ui.unmount()
  }
})

test('two rows claiming pinned share no button key', async ($, on) => {
  const w = world(on, answeringPalette([
    group({ name: 'p1', role: 'pinned', id: 'aaaa0001' }),
    group({ name: 'p2', role: 'pinned', id: 'aaaa0002' }),
  ]))
  await seed($ as never, w.clock)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...band(120), surface })
    const keys = (await ui.findAll({ type: 'Button' })).map(b => b.key)
    expect(new Set(keys).size).toBe(keys.length)
    await ui.unmount()
  }
})

// A crowded band: a blocked pinned plan with a long note, a plain plan, and a
// master whose two sub-plans are both gate-blocked.
const CROWDED: PlanGroup[] = [
  group({ name: '2031-05-02-invoice-export-redesign-follow', role: 'pinned', depth: 0, done: 4, total: 9, id: '1f2e3d4c',
          tail: '· S1/3 ✘ blocked Staging database restore is booked for next week',
          tail_spans: [{ text: '·', color: null, dim: true }, { text: ' S1/3 ', color: null, dim: false },
                       { text: '✘ blocked', color: '#db3630', dim: false }, { text: ' ', color: null, dim: false },
                       { text: 'Staging database restore is booked for next week', color: null, dim: true }] }),
  group({ name: 'docs-site-refresh', role: 'other', depth: 0, done: 2, total: 8, id: '5a6b7c8d', tail: '', tail_spans: [] }),
  group({ name: '2031-04-21-billing-ledger-migration-master', role: 'master', depth: 0, done: 0, total: 2, id: '9e0f1a2b', tail: '', tail_spans: [] }),
  group({ name: 'sub-01-schema-split', role: 'child', depth: 1, done: 4, total: 4, id: 'c3d4e5f6',
          tail: '⊘ GATE BLOCKED', tail_spans: [{ text: '⊘ GATE BLOCKED', color: '#db3630', dim: false }] }),
  group({ name: 'sub-02-backfill-old-invoices', role: 'child', depth: 1, done: 5, total: 5, id: '7b8c9d0e',
          tail: '⊘ GATE BLOCKED', tail_spans: [{ text: '⊘ GATE BLOCKED', color: '#db3630', dim: false }] }),
]

test('a coloured marker outlasts the free text, the context and the name column: whole and aligned from 70 columns', async ($, on) => {
  const w = world(on, answeringPalette(CROWDED))
  engineUsage(on, 25)
  await seed($ as never, w.clock)
  await turnEnds($)
  for (const surface of SURFACES) {
    for (const cols of [70, 76, 88, 100, 120, 160]) {
      const ui = await $.ui.mount({ ...band(cols), surface })
      const rows = await rowsOf(ui)
      expect(rows[0]!.text).toContain('✘ blocked')
      expect(rows[3]!.text).toContain('⊘ GATE BLOCKED')
      expect(rows[4]!.text).toContain('⊘ GATE BLOCKED')
      const red = pieces(rows[0] as Found).find(x => x.text.includes('✘ blocked'))
      expect(red?.color).toBe('#db3630')
      const bars = rows.map(r => columnOf(r.text, /▐/))
      expect(bars.every(c => c > 0 && c === bars[0])).toBe(true)
      for (const row of rows) expect([...row.text].length).toBeLessThanOrEqual(cols - 12)
      if (cols >= 160) expect(rows[0]!.text).toContain('context 25%')
      await ui.unmount()
    }
  }
})

test('a row fitted alone keeps its marker whole before the name\'s extra width', () => {
  const g = group({ name: 'a-plan-name-long-enough-to-take-the-whole-row-by-itself', role: 'other',
                    tail: 'note ⊘ GATE BLOCKED', tail_spans: [{ text: 'note ', color: null, dim: true },
                                                          { text: '⊘ GATE BLOCKED', color: '#db3630', dim: false }] })
  for (const width of [50, 60, 70]) {
    const text = rowSpans(g, width, false, '', PALETTE, 10).map(s => s.text).join('')
    expect(text).toContain('⊘ GATE BLOCKED')
    expect([...text].length).toBeLessThanOrEqual(width)
  }
})
