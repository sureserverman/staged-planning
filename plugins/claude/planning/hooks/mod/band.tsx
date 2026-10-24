// The progress band above the prompt: one row per plan group the model holds,
// sized to the band's own width, drawn in the status line's pieces and colours.
// It draws what plan-progress.py --json computed — the counts, `tail_spans` (the
// script's own text after its bar, split at its colour codes) and the `palette` —
// and never derives a phase, a marker or a marker's colour itself, so on those the
// band and the status line cannot disagree. The bar it builds itself, rounding as
// the status line rounds; it differs on purpose in three ways: 10 cells below
// WIDE_COLUMNS, a fill held to the bar when done > total, and its own (stale) mark
// for a refresh that failed.

import { atom, read } from 'claude-code'
import type { On } from 'claude-code'

import type { ContextFigures, PlanGroup, PlanModelState, PlanPalette } from '../../types'
import { PLAN_ID, PLAN_PANE, PLAN_PANE_TITLE, planPaneId } from './pane-id'

// Declared in each file that reads it: the engine's scan lists a module's state
// reads from atoms written in the reading file itself.
const MODEL = atom({ plugin: 'planning', key: 'model' } as const, null as PlanModelState | null)
const CONTEXT = atom({ plugin: 'planning', key: 'context' } as const, null as ContextFigures | null)

// The status line's 20-cell bar where the band is wide, half of it elsewhere.
const BAR_CELLS = 20
const BAR_CELLS_NARROW = 10
const WIDE_COLUMNS = 100
// The bar's cells for a surface `cols` wide: the band's rule, shared with the plan pane.
export const barCellsFor = (cols: number): number => (cols >= WIDE_COLUMNS ? BAR_CELLS : BAR_CELLS_NARROW)
// "[ Plan ]", the space before it, and the collapse control the engine draws at
// the band's right edge: kept off the text budget of every row with a button, so
// the buttons line up in one column.
const BUTTON_CELLS = 12
// Below this the button is not drawn at all; the row keeps the whole width.
const BUTTON_MIN_COLUMNS = 24
// A name is never clipped below this while the row has room for it.
const NAME_MIN = 8
// The status line's name column cap (plan-progress.py NAME_WIDTH): the tree glyph
// and the name, with `⚙ ` drawn beside them.
const NAME_WIDTH = 46
const HEAD = '⚙ '
// Controls (Cc: C0, DEL and C1, among them U+009B, a one-byte CSI), invisible
// format characters (Cf: bidi overrides, zero-width marks) and lone surrogates
// (Cs) — the classes plan_continue_classify.py's clean() drops.
const CONTROL = /[\p{Cc}\p{Cf}\p{Cs}]/gu

// The fill and the pinned name take the script's palette; an older script sends
// none, and the theme's own keys stand in.
const FALLBACK = { green: 'success', cyan: 'suggestion' }
// A span colour is the script's `#rrggbb` or nothing: no other string reaches a Text.
const HEX = /^#[0-9a-f]{6}$/i

// One piece of a row: its text and how it is drawn.
export type Span = { text: string; color?: string; dim?: boolean }

// The model is the script's output, and a plan name or a task description in it
// is text somebody else wrote: no control character reaches a surface.
function plain(s: unknown): string {
  return typeof s === 'string' ? s.replace(CONTROL, '') : ''
}

const cells = (text: string): number => [...text].length
const width_ = (spans: Span[]): number => spans.reduce((n, s) => n + cells(s.text), 0)

function clip(text: string, width: number): string {
  const chars = [...text]
  if (chars.length <= width) return text
  return width <= 1 ? chars.slice(0, Math.max(0, width)).join('') : `${chars.slice(0, width - 1).join('')}…`
}

// The pinned row's context figure, ` · context 25%`, from the live window the
// context hook stored; empty when the engine has not reported a percentage yet.
export function contextText(figures: ContextFigures | null): string {
  const percent = figures?.percent
  return typeof percent === 'number' && Number.isSafeInteger(percent) ? ` · context ${percent}%` : ''
}

// Spans cut to `width` cells, the last kept one ending in … when anything was lost.
export function clipSpans(spans: Span[], width: number): Span[] {
  if (width_(spans) <= width) return spans
  const out: Span[] = []
  let room = Math.max(0, width)
  for (const s of spans) {
    if (room <= 0) break
    const chars = [...s.text]
    if (chars.length <= room) {
      out.push(s)
      room -= chars.length
    } else {
      out.push({ ...s, text: clip(s.text, room) })
      room = 0
    }
  }
  return out
}

// The group's tail as spans: the script's own `tail_spans`, each text made plain
// and each colour a `#rrggbb` or none; the plain `tail` when an older script sent
// no spans.
function tailSpans(g: PlanGroup): Span[] {
  if (!Array.isArray(g.tail_spans)) {
    const tail = plain(g.tail)
    return tail === '' ? [] : [{ text: tail }]
  }
  const out: Span[] = []
  for (const s of g.tail_spans) {
    const text = plain(s?.text)
    if (text === '') continue
    const color = typeof s.color === 'string' && HEX.test(s.color) ? s.color : undefined
    out.push({ text, color, dim: s.dim === true ? true : undefined })
  }
  return out
}

// The cells a group's coloured tail spans — its markers, `✘ blocked`, `⊘ GATE
// BLOCKED`, `↻N/M` — need whole: each with a space before it. Free text (a note,
// a task description, the stage position) carries no colour and is not counted.
function markCells(g: PlanGroup): number {
  return tailSpans(g).reduce((n, s) => (s.color === undefined ? n : n + 1 + cells(s.text)), 0)
}

// The tail fitted to `room` cells, its leading space included: whole when it fits;
// else every coloured marker kept whole and the free text around them cut, in
// order, to what is left. A marker never loses its space before it.
export function fitTail(tail: Span[], room: number): Span[] {
  if (1 + width_(tail) <= room) return [{ text: ' ' }, ...tail]
  const marks = tail.reduce((n, s) => (s.color === undefined ? n : n + 1 + cells(s.text)), 0)
  if (1 + marks > room) return clipSpans([{ text: ' ' }, ...tail], room)
  let budget = room - 1 - marks
  const out: Span[] = [{ text: ' ' }]
  for (const s of tail) {
    if (s.color !== undefined) {
      if (!/\s$/.test(out[out.length - 1]!.text)) out.push({ text: ' ' })
      out.push(s)
      continue
    }
    if (budget <= 0) continue
    const text = cells(s.text) <= budget ? s.text : budget >= 2 ? clip(s.text, budget) : ''
    budget = text === s.text ? budget - cells(text) : 0
    if (text !== '') out.push({ ...s, text })
  }
  return out
}

// One column for every row drawn: names padded to `nameColumn` cells (indent and
// `⚙ ` included), counts right-aligned to `countWidth`.
export type Layout = { nameColumn: number; countWidth: number }

// A count the script sent as a whole number, else none: no NaN reaches a Text.
const whole = (n: unknown): number | null => (typeof n === 'number' && Number.isSafeInteger(n) ? n : null)
const totalOf = (g: PlanGroup): number => Math.max(0, whole(g.total) ?? 0)
const doneOf = (g: PlanGroup): number => Math.min(Math.max(whole(g.done) ?? 0, 0), totalOf(g))

// `├─ ` for a sub-plan with another sub-plan drawn below it, `└─ ` for the last,
// as the status line draws its tree.
const indentOf = (g: PlanGroup, mid = false): string => ((g.depth ?? 0) > 0 ? (mid ? '├─ ' : '└─ ') : '')
const countOf = (g: PlanGroup): string => (totalOf(g) > 0 ? `${whole(g.done) ?? 0}/${totalOf(g)}` : '')
// Unclamped above 100, as the status line prints it: only the bar is held.
const pctOf = (g: PlanGroup): string =>
  totalOf(g) > 0 ? `(${Math.floor((Math.max(whole(g.done) ?? 0, 0) * 100) / totalOf(g))}%)` : ''

// The bar's filled cells: round(cells * done / total) with ties to even, as
// Python's round() in plan-progress.py's bar() — in integers, so a tie is exact.
export function filledCells(done: number, total: number, barCells: number): number {
  if (total <= 0) return 0
  const n = barCells * done
  const q = Math.floor(n / total)
  const r2 = 2 * (n - q * total)
  return r2 > total || (r2 === total && q % 2 === 1) ? q + 1 : q
}

// The shared column for `rows`, each drawn in its own `width`: the widest indent +
// `⚙ ` + name, capped at NAME_WIDTH + `⚙ ` and at what the narrowest row leaves beside its
// bar and counts — so every `▐` and every `(pct%)` starts at one column. A row's
// coloured markers, then its `context`, are reserved too, each while the column
// still leaves every row its NAME_MIN: both outrank the names' extra width, in
// that order, as they do in rowSpans.
export function layoutFor(
  rows: { g: PlanGroup; width: number; stale: boolean; context?: string }[],
  barCells: number,
): Layout {
  const countWidth = Math.max(0, ...rows.map(r => cells(countOf(r.g))))
  const column = (withMarks: boolean, withContext: boolean): number => {
    let widest = 0
    let room = NAME_WIDTH + cells(HEAD)
    for (const { g, width, stale, context } of rows) {
      widest = Math.max(widest, cells(indentOf(g)) + cells(HEAD) + cells(plain(g.name)))
      const rest = totalOf(g) > 0 ? 1 + barCells + 2 + 1 + countWidth + 1 + cells(pctOf(g)) : 0
      const marks = withMarks && markCells(g) > 0 ? 1 + markCells(g) : 0
      const ctx = withContext ? cells(context ?? '') : 0
      room = Math.min(room, width - rest - (stale ? cells(' (stale)') : 0) - marks - ctx)
    }
    return Math.min(widest, room)
  }
  const keepsMin = (col: number): boolean =>
    rows.every(({ g }) => col - cells(indentOf(g)) - cells(HEAD) >= Math.min(cells(plain(g.name)), NAME_MIN))
  for (const [marks, ctx] of [[true, true], [true, false]] as const) {
    const col = column(marks, ctx)
    if (keepsMin(col)) return { nameColumn: col, countWidth }
  }
  return { nameColumn: column(false, false), countWidth }
}

// One row as the status line draws it — `└─ ` for a sub-plan, `⚙ ` and the name
// (cyan when pinned, dim otherwise), `▐` + the green fill + the `░` track `▌`,
// `done/total`, a dim `(pct%)`, the tail's spans, the pinned row's context — fitted
// to `width` by priority: the indent, the counts and the stale marker are kept
// whole; the context figure is shown whole or not at all, and only while the name
// keeps NAME_MIN beside it; the name gives way next (down to NAME_MIN); the tail's
// free text gives way first, while its coloured markers are kept whole ahead of
// the context and the names' extra width (fitTail). Only a row too narrow for even
// that is clipped as a whole. The `(pct%)` gives way before that cut, so the
// counts and the stale mark outlast it. With a `layout` whose column leaves this
// row its NAME_MIN, the name is padded or clipped to that column instead.
export function rowSpans(
  g: PlanGroup,
  width: number,
  stale: boolean,
  context = '',
  palette: PlanPalette | undefined = undefined,
  barCells = BAR_CELLS_NARROW,
  layout: Layout | undefined = undefined,
  mid = false,
): Span[] {
  const green = typeof palette?.green === 'string' && HEX.test(palette.green) ? palette.green : FALLBACK.green
  const cyan = typeof palette?.cyan === 'string' && HEX.test(palette.cyan) ? palette.cyan : FALLBACK.cyan
  const glyph = indentOf(g, mid)
  const indent: Span[] = glyph === '' ? [] : [{ text: glyph, dim: true }]
  const mark: Span[] = stale ? [{ text: ' (stale)', dim: true }] : []
  const name = plain(g.name)
  const pinned = g.role === 'pinned'
  const head = HEAD
  const counts: Span[] = []
  if (totalOf(g) > 0) {
    const filled = filledCells(doneOf(g), totalOf(g), barCells)
    const count = countOf(g)
    const pad = layout === undefined ? 0 : Math.max(0, layout.countWidth - cells(count))
    counts.push(
      { text: ' ' },
      { text: '▐', dim: true },
      { text: '█'.repeat(filled), color: green },
      { text: `${'░'.repeat(barCells - filled)}▌`, dim: true },
      { text: ` ${' '.repeat(pad)}${count}` },
    )
    // The percentage, with its space, only where the row floor leaves room for it.
    const pct = ` ${pctOf(g)}`
    const floor = width_(indent) + cells(head) + Math.min(cells(name), NAME_MIN) + width_(counts) + width_(mark)
    if (floor + cells(pct) <= width) counts.push({ text: ' ' }, { text: pctOf(g), dim: true })
  }
  const fixed0 = width_(indent) + cells(head) + width_(counts) + width_(mark)
  const nameMin = Math.min(cells(name), NAME_MIN)
  // The coloured markers' cells, kept whole while the name keeps NAME_MIN beside them.
  const tail = tailSpans(g)
  const marks = markCells(g) > 0 ? 1 + markCells(g) : 0
  const reserve = fixed0 + nameMin + marks <= width ? marks : 0
  // The shared column, when it leaves this row its NAME_MIN and its markers; else the
  // row fits alone.
  const column = layout === undefined ? -1 : layout.nameColumn - width_(indent) - cells(head)
  const aligned = column >= nameMin && fixed0 + column + reserve <= width
  const minName = aligned ? column : nameMin
  const ctx = fixed0 + minName + reserve + cells(context) <= width ? context : ''
  const fixed = fixed0 + cells(ctx)
  const nameRoom = aligned ? column : Math.max(nameMin, width - fixed - reserve)
  const clipped = clip(name, nameRoom)
  const shownName = aligned ? clipped + ' '.repeat(Math.max(0, column - cells(clipped))) : clipped
  const tailRoom = width - fixed - cells(shownName)
  const shownTail = tail.length > 0 && tailRoom >= 3 ? fitTail(tail, tailRoom) : []
  const row: Span[] = [
    ...indent,
    pinned ? { text: `${head}${shownName}`, color: cyan } : { text: `${head}${shownName}`, dim: true },
    ...counts,
    ...mark,
    ...shownTail,
    ...(ctx === '' ? [] : [{ text: ctx }]),
  ]
  return clipSpans(row, width).filter(s => s.text !== '')
}

// At most `maxRows` rows, and the executing plan is always one of them: when the
// groups do not fit, the pinned group (with its master, when it is a sub-plan)
// comes first and the last row counts the rest. None when maxRows is below 1.
export function bandRows(groups: PlanGroup[], maxRows: number): (PlanGroup | number)[] {
  const limit = Math.floor(maxRows)
  if (!(limit >= 1)) return []
  if (groups.length <= limit) return groups
  const at = groups.findIndex(g => g.role === 'pinned')
  const keep: PlanGroup[] = []
  if (at >= 0) {
    const pinned = groups[at]!
    if ((pinned.depth ?? 0) > 0) {
      for (let i = at - 1; i >= 0; i -= 1) {
        if ((groups[i]!.depth ?? 0) === 0) {
          keep.push(groups[i]!)
          break
        }
      }
    }
    keep.push(pinned)
  }
  const room = limit === 1 ? 1 : limit - 1
  // The pinned plan outranks its master: with room for one of them, it is the one.
  if (keep.length > room) keep.splice(0, keep.length - room)
  const rest = groups.filter(g => !keep.includes(g))
  const shown = [...keep, ...rest].slice(0, room)
  return limit === 1 ? shown : [...shown, groups.length - shown.length]
}

export function registerBand(on: On): void {
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const state = await read($, MODEL)
    const context = contextText(await read($, CONTEXT))
    const groups = state?.model?.groups ?? []
    const rows = bandRows(groups, e.props.maxRows)
    if (rows.length === 0) return next(e)

    const { Box, Button, Text } = $.ui.resolve(e)
    const cols = Math.max(1, Math.floor(e.props.bodyColumns))
    const withButton = cols >= BUTTON_MIN_COLUMNS
    const barCells = barCellsFor(cols)
    const palette = state?.model?.palette
    // With two or more plan rows, each with the script's id, every plan row has its
    // own button; otherwise row 0 alone has one.
    const planRows = rows.filter((row): row is PlanGroup => typeof row !== 'number')
    const perRow =
      planRows.length >= 2 &&
      planRows.every(g => typeof g.id === 'string' && PLAN_ID.test(g.id)) &&
      new Set(planRows.map(g => g.id)).size === planRows.length &&
      planRows.filter(g => g.role === 'pinned').length <= 1
    // What the executing-plan pane reads (pane.tsx): with neither, it would say no
    // plan is executing, so the lone button opens its row's own pane instead.
    const noneExecuting = !groups.some(g => g.role === 'pinned') && (state?.model?.detail ?? null) === null
    const hasButton = (i: number): boolean =>
      withButton && typeof rows[i] !== 'number' && (perRow || i === 0)
    const widthOf = (i: number): number => (hasButton(i) ? cols - BUTTON_CELLS : cols)
    const staleAt = (i: number): boolean => i === 0 && state?.stale === true
    const layout = layoutFor(
      rows.flatMap((row, i) =>
        typeof row === 'number'
          ? []
          : [{ g: row, width: widthOf(i), stale: staleAt(i), context: row.role === 'pinned' ? context : '' }],
      ),
      barCells,
    )

    return (
      <Box flexDirection="column">
        {rows.map((row, i) => {
          if (typeof row === 'number') {
            return (
              <Text key="more" dimColor wrap="truncate">
                {clip(`… ${row} more`, cols)}
              </Text>
            )
          }
          const below = rows[i + 1]
          const mid = typeof below !== 'number' && below !== undefined && (below.depth ?? 0) > 0
          const spans = rowSpans(
            row,
            widthOf(i),
            staleAt(i),
            row.role === 'pinned' ? context : '',
            palette,
            barCells,
            layout,
            mid,
          )
          // A row with a button is padded to its width, so every button starts at
          // one column.
          const pad = hasButton(i) ? widthOf(i) - width_(spans) : 0
          const drawn = pad > 0 ? [...spans, { text: ' '.repeat(pad) }] : spans
          const line = (
            <Text key={`line-${i}`} wrap="truncate">
              {drawn.map((s, j) => (
                <Text key={`span-${j}`} color={s.color} dimColor={s.dim}>
                  {s.text}
                </Text>
              ))}
            </Text>
          )
          if (!hasButton(i)) return line
          // The pinned plan's button (and the lone button) opens the plan pane; any
          // other plan's opens that plan's own pane, titled with its name, as does a
          // lone button when nothing is executing. No keyboard shortcut:
          // a bare digit typed into an empty composer would press it.
          const own =
            row.role !== 'pinned' &&
            (perRow || (noneExecuting && typeof row.id === 'string' && PLAN_ID.test(row.id)))
          const name = clip(plain(row.name), NAME_WIDTH)
          return (
            <Box key={`row-${i}`} flexDirection="row">
              {line}
              <Text> </Text>
              <Button
                key={own ? `open-plan:${row.id}` : 'open-plan'}
                label="Plan"
                dimColor={own ? true : undefined}
                onPress={() =>
                  void $.ui.open(
                    own
                      ? { id: planPaneId(row.id as string), title: name === '' ? PLAN_PANE_TITLE : name }
                      : { id: PLAN_PANE, title: PLAN_PANE_TITLE },
                  )
                }
              />
            </Box>
          )
        })}
      </Box>
    )
  })
}
