// This session's Agent calls, for the plan pane: a plan's Dispatch: YES tasks, its
// reviewers and its evaluators all go out through the Agent tool. Every Agent call
// is listed, whatever it was for.
//
// When a call returns is not when its agent finishes: a background launch returns
// at once with `async_launched` and its agent's id. Such a record stays `running`
// until $.agent.list() reports that agent in another status, checked on a timer
// while any record is still running.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, On } from 'claude-code'

import type { AgentOutcome, AgentRecord } from '../../types'

const AGENTS = atom({ plugin: 'planning', key: 'agents' } as const, [] as AgentRecord[])

const KEEP = 50
const POLL_MS = 5000

const text = (v: unknown): string => (typeof v === 'string' ? v : '')

type Settled = { outcome: AgentOutcome; agentId?: string }

// What the Agent tool's answer says about the agent behind it.
function settledBy(answer: unknown): Settled {
  const a = (answer ?? {}) as { deny?: unknown; isError?: unknown; result?: unknown }
  if (typeof a.deny === 'string') return { outcome: 'denied' }
  if (a.isError === true) return { outcome: 'failed' }
  const r = (a.result ?? {}) as { status?: unknown; agentId?: unknown }
  if (r.status === 'async_launched' && typeof r.agentId === 'string') return { outcome: 'running', agentId: r.agentId }
  return { outcome: 'done' }
}

function finished(status: string): AgentOutcome | null {
  if (status === 'running' || status === 'pending') return null
  return status === 'completed' ? 'done' : 'failed'
}

async function sync($: EngineInterface): Promise<void> {
  const list = await read($, AGENTS)
  if (!list.some(a => a.outcome === 'running' && a.agentId !== undefined)) return
  const live = new Map((await $.agent.list()).map(info => [info.id, info.status]))
  await update($, AGENTS, records =>
    records.map(a => {
      if (a.outcome !== 'running' || a.agentId === undefined) return a
      const status = live.get(a.agentId)
      const outcome = status === undefined ? null : finished(status)
      return outcome === null ? a : { ...a, outcome, isDone: true }
    }),
  )
}

// Started once per module load, by the first background launch; timers end with a
// reload, and so does this flag.
let polling = false

function ensurePolling($: EngineInterface): void {
  if (polling) return
  polling = true
  $.clock.every(POLL_MS, () => {
    void sync($).catch(() => undefined)
  })
}

export function registerAgents(on: On): void {
  on('tool.call', { tool: 'Agent' }, async ($, e, next) => {
    const record: AgentRecord = {
      id: e.tool_use_id,
      description: text((e as { description?: unknown }).description),
      subagentType: text((e as { subagent_type?: unknown }).subagent_type) || 'general-purpose',
      startedAt: await $.clock.now(),
      isDone: false,
      outcome: 'running',
    }
    await update($, AGENTS, list => [...list, record].slice(-KEEP))
    let settled: Settled = { outcome: 'failed' }
    try {
      const answer = await next(e)
      settled = settledBy(answer)
      return answer
    } finally {
      await update($, AGENTS, list =>
        list.map(a =>
          a.id === record.id
            ? { ...a, ...settled, isDone: settled.outcome !== 'running' }
            : a,
        ),
      )
      if (settled.outcome === 'running') ensurePolling($)
    }
  })
}
