// The plan pane: the whole executing plan — its master, its stages with their
// gates, every task with its status — and the agents this session has dispatched.
// Opened only by the person (/plan-view or the band's Plan button), never unasked.
// It draws planning.model.detail, which plan-progress.py --json parsed with the
// same regexes as the bar, and planning.agents.
//
// A plan's own pane, `planning-plan-<id>` (a band row's own Plan button), draws
// that plan instead: its header row built as the band builds its rows (rowSpans,
// the band's bar size for the pane's width, one name column), then — for a master
// — its in-flight sub-plans, then its stages and tasks from
// planning.model.details[id], with no current-task marker and no agents, which
// belong to the executing plan alone.

import { atom, read } from 'claude-code'
import type { On } from 'claude-code'

import type { AgentRecord, PlanDetail, PlanGroup, PlanModelState, PlanTask } from '../../types'
import { barCellsFor, layoutFor, rowSpans } from './band'
import type { Span } from './band'
import { PLAN_PANE, PLAN_PANE_TITLE, PLAN_PANES } from './pane-id'

// Declared in each file that reads them: the engine's scan lists a module's state
// reads from atoms written in the reading file itself.
const MODEL = atom({ plugin: 'planning', key: 'model' } as const, null as PlanModelState | null)
const AGENTS = atom({ plugin: 'planning', key: 'agents' } as const, [] as AgentRecord[])

// Controls (Cc: C0, DEL and C1, among them U+009B, a one-byte CSI), invisible
// format characters (Cf: bidi overrides, zero-width marks) and lone surrogates
// (Cs) — the classes plan_continue_classify.py's clean() drops.
const CONTROL = /[\p{Cc}\p{Cf}\p{Cs}]/gu

const GLYPH: Record<string, string> = { done: '✔', partial: '◐', open: '○' }

const OUTCOME: Record<string, string> = { running: '◌', done: '✔', failed: '✘', denied: '⊘' }

function plain(s: unknown): string {
  return typeof s === 'string' ? s.replace(CONTROL, '') : ''
}

function clip(text: string, width: number): string {
  const cells = [...text]
  if (cells.length <= width) return text
  return width <= 1 ? cells.slice(0, Math.max(0, width)).join('') : `${cells.slice(0, width - 1).join('')}…`
}

function counts(g: PlanGroup): string {
  return g.total > 0 ? ` ${g.done}/${g.total}` : ''
}

function taskLine(t: PlanTask, current: string | null): string {
  const mark = current !== null && t.id === current ? '▶' : ' '
  return `${mark} ${GLYPH[t.status ?? ''] ?? '·'} ${plain(t.id)} ${plain(t.title)}`
}

type Line = { text: string; bold?: boolean; dim?: boolean; colour?: string; spans?: Span[] }

// The stage and task lines of one plan's breakdown; `current` marks the task the
// executing plan is on (null draws no marker).
function stageLines(detail: PlanDetail | null, current: string | null): Line[] {
  const lines: Line[] = []
  // The model is the script's output: a breakdown that is not the shape it promises
  // costs its own lines, never the pane.
  const stages = Array.isArray(detail?.stages) ? detail.stages : []
  for (const stage of stages) {
    if (stage === null || typeof stage !== 'object') continue
    const tasks = Array.isArray(stage.tasks) ? stage.tasks : []
    const head = stage.number === null ? 'Tasks' : `Stage ${stage.number}${stage.name ? ` — ${plain(stage.name)}` : ''}`
    const gate = stage.gate_total > 0 ? `  gate ${stage.gate_checked}/${stage.gate_total}` : ''
    lines.push({ text: '' })
    lines.push({ text: `${head}${gate}`, bold: true })
    for (const t of tasks) if (t !== null && typeof t === 'object') lines.push({ text: taskLine(t, current), dim: t.status === 'done' })
  }
  return lines
}

// A plan's own pane: the plan whose `id` the pane's id carries. Its header and any
// sub-plan's are rowSpans() fitted to `width`, so it reads as the band does.
export function planLines(state: PlanModelState | null, id: string, width: number): Line[] {
  const groups = state?.model?.groups ?? []
  const at = groups.findIndex(g => g?.id === id)
  if (at < 0) return [{ text: 'This plan is no longer in flight.', dim: true }]
  const g = groups[at]!
  const palette = state?.model?.palette
  const cells = barCellsFor(width)
  // Its in-flight sub-plans: the depth-1 groups that follow a top-level plan. A
  // master is found by them too, so a pinned master (role `pinned`) lists them.
  const subs: PlanGroup[] = []
  if ((g.depth ?? 0) === 0) {
    for (const below of groups.slice(at + 1)) {
      if ((below?.depth ?? 0) === 0) break
      subs.push(below)
    }
  }
  // A listed sub-plan keeps its own markers (⊘ GATE BLOCKED); only the executing
  // plan's tail — its phase, task and any ↻N/M round — is left to that plan's own
  // pane (planning-plan).
  const listed = subs.map(sub => (sub.role === 'pinned' ? { ...sub, tail: '', tail_spans: [] } : sub))
  const header = { ...g, depth: 0 }
  const layout = layoutFor([header, ...listed].map(row => ({ g: row, width, stale: false })), cells)
  const row = (r: PlanGroup, mid = false): Line => ({ text: '', spans: rowSpans(r, width, false, '', palette, cells, layout, mid) })
  const lines: Line[] = [row(header)]
  if (state?.stale === true) lines.push({ text: '(stale: the last refresh failed)', dim: true })
  if (g.role === 'master' || subs.length > 0) {
    lines.push({ text: '' })
    lines.push({ text: subs.length > 0 ? 'Sub-plans in flight' : 'No sub-plan in flight', bold: true })
    listed.forEach((sub, i) => lines.push(row(sub, i < listed.length - 1)))
  }
  const detail = state?.model?.details?.[id] ?? null
  if (detail === null && subs.length === 0) {
    lines.push({ text: '' })
    lines.push({ text: 'Its stages and tasks could not be read.', dim: true })
  }
  lines.push(...stageLines(detail, null))
  return lines
}

export function paneLines(state: PlanModelState | null, agents: AgentRecord[]): Line[] {
  const groups = state?.model?.groups ?? []
  const pinned = groups.find(g => g.role === 'pinned')
  const detail = state?.model?.detail ?? null
  if (pinned === undefined && detail === null) return [{ text: 'No plan is executing.', dim: true }]

  const lines: Line[] = []
  const master = groups.find(g => g.role === 'master' && (pinned?.depth ?? 0) > 0)
  if (master !== undefined) lines.push({ text: `${plain(master.name)}${counts(master)}`, colour: 'magenta', bold: true })
  if (pinned !== undefined) {
    const indent = master !== undefined ? '└ ' : ''
    const tail = plain(pinned.tail)
    lines.push({ text: `${indent}${plain(pinned.name)}${counts(pinned)}${tail ? ` ${tail}` : ''}`, colour: 'cyan', bold: true })
    // The tail already shows ↻N/M during a gate; outside one, a recorded round
    // gets its own line. Both numbers come from the script, never a default here.
    const round = pinned.remediation_round
    const budget = pinned.remediation_budget
    if (typeof round === 'number' && typeof budget === 'number' && !tail.includes('↻')) {
      lines.push({ text: `remediation ↻${round}/${budget}`, colour: 'yellow' })
    }
  }
  if (state?.stale === true) lines.push({ text: '(stale: the last refresh failed)', dim: true })

  const current = typeof pinned?.task === 'string' && pinned.phase === 'task' ? pinned.task : null
  lines.push(...stageLines(detail, current))

  if (agents.length > 0) {
    lines.push({ text: '' })
    lines.push({ text: 'Agents', bold: true })
    const running = agents.filter(a => a.outcome === 'running')
    const ended = agents.filter(a => a.outcome !== 'running').reverse()
    for (const a of [...running, ...ended]) {
      lines.push({
        text: `${OUTCOME[a.outcome] ?? '·'} ${plain(a.description)} · ${plain(a.subagentType)}`,
        dim: a.outcome === 'done',
        colour: a.outcome === 'failed' || a.outcome === 'denied' ? 'red' : undefined,
      })
    }
  }
  return lines
}

export function registerPane(on: On): void {
  // Only where a person can type it: a -p run has no use for a slash command.
  on('session.start', { isInteractive: true }, async ($, e, next) => {
    const started = await next(e)
    await $.command.register({
      name: 'plan-view',
      description: 'Show the executing plan, its stages and tasks, and dispatched agents in a pane',
    })
    return started
  })

  on('command.run', { command: 'plan-view' }, async $ => {
    const opened = await $.ui.open({ id: PLAN_PANE, title: PLAN_PANE_TITLE })
    if (opened.isPlaced === false) return { text: `The plan pane is open but waits to be placed: ${opened.reason}` }
    return { text: 'Plan pane opened.' }
  })

  // One hook for the family: `planning-plan` is the executing plan with its agents,
  // `planning-plan-<id>` that plan alone.
  on('ui.render', { component: 'Pane', requestId: PLAN_PANES }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const width = Math.max(1, Math.floor(e.props.bodyColumns))
    const id = String(e.requestId ?? '').slice(PLAN_PANE.length + 1)
    const state = await read($, MODEL)
    const lines = id === '' ? paneLines(state, await read($, AGENTS)) : planLines(state, id, width)
    return (
      <Box flexDirection="column">
        {lines.map((line, i) =>
          line.spans !== undefined ? (
            <Text key={`line-${i}`} wrap="truncate">
              {line.spans.map((s, j) => (
                <Text key={`span-${j}`} color={s.color} dimColor={s.dim}>
                  {s.text}
                </Text>
              ))}
            </Text>
          ) : (
            <Text key={`line-${i}`} bold={line.bold} dimColor={line.dim} color={line.colour} wrap="truncate">
              {clip(line.text, width) || ' '}
            </Text>
          ),
        )}
      </Box>
    )
  })
}
