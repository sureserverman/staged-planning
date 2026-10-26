// The planning mod's state contract: every `$.state` value the hooks module under
// ../hooks/mod/ reads or writes is declared here, and `claude plugin validate`
// holds the module's keys to it.

// One bar of the render model `plan-progress.py --json` prints; the script owns
// the shape, and a field it leaves out is absent rather than guessed here.
export type PlanGroup = {
  name: string
  plan?: string
  done: number
  total: number
  role: 'pinned' | 'other' | 'master' | 'child'
  depth?: number
  gate_blocked?: boolean
  stage?: number | null
  stage_count?: number | null
  task?: string | null
  phase?: string | null
  stale_hours?: number | null
  remediation_round?: number | null
  remediation_budget?: number | null
  blocked_note?: string | null
  status_lag?: number | null
  task_not_in_plan?: boolean | null
  stage_order?: boolean | null
  // What the text line shows after its bar, plain: drawn verbatim by the band.
  tail?: string
  // A short stable id for the plan (8 hex of the sha1 of its resolved path): the
  // key into PlanModel.details.
  id?: string
  // `tail` split at the line's own colour codes; the texts join to `tail`.
  tail_spans?: TailSpan[]
  [field: string]: unknown
}

// One piece of a group's tail: `color` a `#rrggbb` from the status line's
// escape codes, or null for the terminal's own; `dim` from its dim code.
export type TailSpan = { text: string; color: string | null; dim: boolean }

// The status line's five role colours as hex, read from the script's constants.
export type PlanPalette = { green: string; red: string; yellow: string; cyan: string; purple: string }

// `status` is the plan parser's own word for the marker: done, partial ([~]) or open.
export type PlanTask = { id: string; title: string; status: 'done' | 'partial' | 'open' | null }

// A light plan has no `## Stage` heading: its one stage carries number and name null.
export type PlanStage = {
  number: number | null
  name: string | null
  gate_checked: number
  gate_total: number
  tasks: PlanTask[]
}

// One entry of a master's register, in register order. `status` is the register's
// own Status word; `plan`, `id`, `done` and `total` are null when the plan its
// `Plan:` link names cannot be read.
export type PlanSubplan = {
  number: number | null
  title: string
  status: 'done' | 'partial' | 'open' | null
  plan: string | null
  name: string
  id: string | null
  done: number | null
  total: number | null
}

// `subplans` is present on a master's breakdown only, and absent from an older
// script's output.
export type PlanDetail = { plan: string; name?: string; stages: PlanStage[]; subplans?: PlanSubplan[]; [field: string]: unknown }

// `detail` is the pinned plan's breakdown; `details` every group's, keyed by its
// `id` (null where it could not be built; one entry per id, so two plans whose
// 8-hex ids collide share one). Both keys are absent from an older
// script's output.
export type PlanModel = {
  groups: PlanGroup[]
  detail: PlanDetail | null
  details?: Record<string, PlanDetail | null>
  palette?: PlanPalette
}

// The last model a refresh produced. `stale` is set when the latest refresh failed
// (timeout, non-zero exit, unparseable output) and the previous model was kept.
export type PlanModelState = { model: PlanModel | null; fetchedAt: number; stale: boolean }

// One Agent call this session made, for the plan pane's agents list. A background
// launch keeps `agentId` and stays `running` until $.agent.list() reports it ended.
export type AgentOutcome = 'running' | 'done' | 'failed' | 'denied'

export type AgentRecord = {
  id: string
  agentId?: string
  description: string
  subagentType: string
  startedAt: number
  isDone: boolean
  outcome: AgentOutcome
}

// The Stop check's no-progress count for one phase|stage|task.
export type StopCounter = { key: string; count: number }

// The live context window as $.session.usage() last reported it on a main-loop
// turn: `window` always a positive whole number; a figure the engine lacked is null.
export type ContextFigures = { window: number; tokens: number | null; percent: number | null }

declare module 'claude-code' {
  interface PluginState {
    planning: {
      model: PlanModelState | null
      agents: AgentRecord[]
      statuslineNoted: boolean
      stopCounter: StopCounter | null
      // JSON [plan, stage] pairs this session has had a stage-boundary note for.
      notedStages: string[]
      context: ContextFigures | null
    }
  }
}
