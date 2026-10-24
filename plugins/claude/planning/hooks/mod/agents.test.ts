import { expect, test } from 'claude-code/testing'

import type { AgentRecord } from '../../types'
import { world } from './testing'

const launched = (agentId: string) => ({ result: { status: 'async_launched', agentId, description: 'bg' } })

function agentList(on: Parameters<typeof world>[0], statuses: Record<string, string>) {
  on('agent.list', () => ({ value: Object.entries(statuses).map(([id, status]) => ({ id, description: id, type: 'general-purpose', status })) }) as never)
}

const agents = (w: ReturnType<typeof world>) => (w.seen.keys.agents ?? []) as AgentRecord[]

const dispatch = (description: string, subagent_type = 'general-purpose') =>
  ({ tool: 'Agent', description, prompt: `do ${description}`, subagent_type }) as never

test('two Agent calls record two entries, both done once they resolve', async ($, on) => {
  const w = world(on)
  await $.tool.call(dispatch('Task 1.1: tokenizer'))
  await $.tool.call(dispatch('Stage 1 review', 'planning:code-reviewer'))
  const list = agents(w)
  expect(list.length).toBe(2)
  expect(list.map(a => a.description)).toEqual(['Task 1.1: tokenizer', 'Stage 1 review'])
  expect(list[1]!.subagentType).toBe('planning:code-reviewer')
  expect(list.every(a => a.isDone)).toBe(true)
  expect(list.every(a => typeof a.startedAt === 'number')).toBe(true)
  expect(new Set(list.map(a => a.id)).size).toBe(2)
})

test('an Agent call is recorded as running before it resolves', async ($, on) => {
  const w = world(on)
  let during: AgentRecord[] = []
  w.hooks.onTool = () => {
    during = agents(w).map(a => ({ ...a }))
  }
  await $.tool.call(dispatch('slow one'))
  expect(during.length).toBe(1)
  expect(during[0]!.isDone).toBe(false)
  expect(agents(w)[0]!.isDone).toBe(true)
})

test('a Bash call records nothing', async ($, on) => {
  const w = world(on)
  await $.tool.call({ tool: 'Bash', command: 'ls' })
  expect(w.seen.keys.agents).toBe(undefined)
})

test('the 51st call evicts the oldest', async ($, on) => {
  const w = world(on)
  for (let i = 1; i <= 51; i += 1) await $.tool.call(dispatch(`agent ${i}`))
  const list = agents(w)
  expect(list.length).toBe(50)
  expect(list[0]!.description).toBe('agent 2')
  expect(list[49]!.description).toBe('agent 51')
})

test('a background launch stays running until the agent list says it finished', async ($, on) => {
  const w = world(on)
  const statuses: Record<string, string> = { ag1: 'running' }
  agentList(on, statuses)
  w.hooks.onTool = () => launched('ag1')
  await $.tool.call(dispatch('background task'))
  expect(agents(w)[0]!.isDone).toBe(false)
  expect(agents(w)[0]!.outcome).toBe('running')
  await w.clock.advance(5_000)
  expect(agents(w)[0]!.isDone).toBe(false)
  statuses.ag1 = 'completed'
  await w.clock.advance(5_000)
  expect(agents(w)[0]!.isDone).toBe(true)
  expect(agents(w)[0]!.outcome).toBe('done')
})

test('a background agent that fails or is killed is recorded as failed', async ($, on) => {
  const w = world(on)
  const statuses: Record<string, string> = { ag2: 'running', ag3: 'running' }
  agentList(on, statuses)
  w.hooks.onTool = () => launched('ag2')
  await $.tool.call(dispatch('will fail'))
  w.hooks.onTool = () => launched('ag3')
  await $.tool.call(dispatch('will be killed'))
  statuses.ag2 = 'failed'
  statuses.ag3 = 'killed'
  await w.clock.advance(5_000)
  expect(agents(w).map(a => a.outcome)).toEqual(['failed', 'failed'])
  expect(agents(w).every(a => a.isDone)).toBe(true)
})

test('a denied Agent call is recorded as denied, not done', async ($, on) => {
  const w = world(on)
  w.hooks.onTool = () => ({ deny: 'not allowed here' })
  await $.tool.call(dispatch('refused reviewer'))
  expect(agents(w)[0]!.outcome).toBe('denied')
  expect(agents(w)[0]!.isDone).toBe(true)
})

test('an Agent call that errors is recorded as failed', async ($, on) => {
  const w = world(on)
  w.hooks.onTool = () => ({ result: 'boom', isError: true })
  await $.tool.call(dispatch('broken'))
  expect(agents(w)[0]!.outcome).toBe('failed')
})

test('a foreground Agent call that returns is done', async ($, on) => {
  const w = world(on)
  await $.tool.call(dispatch('fg'))
  expect(agents(w)[0]!.outcome).toBe('done')
})

test('an Agent call whose tool throws is recorded as failed', async ($, on) => {
  const w = world(on)
  w.hooks.onTool = () => {
    throw new Error('tool crashed')
  }
  try {
    await $.tool.call(dispatch('crashing'))
  } catch {
    // the call itself may reject; the record is what is under test
  }
  expect(agents(w)[0]!.outcome).toBe('failed')
  expect(agents(w)[0]!.isDone).toBe(true)
})
