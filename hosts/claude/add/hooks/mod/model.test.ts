import { expect, test } from 'claude-code/testing'
import type { MockClock } from 'claude-code/testing'

import { group, ran, world } from './testing'

const FIXTURE = { groups: [group()], detail: null }
const GOOD = JSON.stringify(FIXTURE)

test('a refresh runs the script with --json, the session cwd, statusline stdin and a 5 s bound', async ($, on) => {
  const w = world(on)
  await $.tool.call({ tool: 'Write', file_path: '/repo/.claude/plan-progress.json', content: '{}' })
  await w.clock.settle()
  expect(w.runs.length).toBe(1)
  const run = w.runs[0]!
  expect(run.argv[0]).toBe('python3')
  expect(run.argv.some(a => a.endsWith('skills/executing-plans/scripts/plan-progress.py'))).toBe(true)
  expect(run.argv).toContain('--json')
  expect(run.init?.timeoutMs).toBe(5000)
  expect(run.init?.cwd).toBe('/repo')
  expect(JSON.parse(run.init?.stdin ?? '{}').cwd).toBe('/repo')
  expect(w.seen.last?.model?.groups[0]?.name).toBe('fixture-plan')
  expect(w.seen.last?.stale).toBe(false)
})

test('a write to the state file triggers exactly one refresh, after the tool ran', async ($, on) => {
  const w = world(on)
  await $.tool.call({ tool: 'Write', file_path: '.claude/plan-progress.json', content: '{}' })
  await w.clock.settle()
  expect(w.runs.length).toBe(1)
  expect(w.order).toEqual(['tool', 'run'])
})

test('an Edit or MultiEdit of a plan file and a Bash write of the state file each refresh', async ($, on) => {
  const w = world(on)
  await $.tool.call({ tool: 'Edit', file_path: '/records/plans/2026-10-03-x-plan.md', old_string: 'a', new_string: 'b' })
  await w.clock.settle()
  await $.tool.call({ tool: 'Bash', command: "printf '{}' > .claude/plan-progress.json" })
  await w.clock.settle()
  await $.tool.call({
    tool: 'MultiEdit',
    file_path: '/records/plans/2026-10-03-x-plan.md',
    edits: [{ old_string: 'a', new_string: 'b' }],
  } as never)
  await w.clock.settle()
  expect(w.runs.length).toBe(3)
})

test('a write to an unrelated file triggers no refresh', async ($, on) => {
  const w = world(on)
  await $.tool.call({ tool: 'Write', file_path: '/repo/src/main.rs', content: 'fn main() {}' })
  await $.tool.call({ tool: 'Write', file_path: '/repo/notes/plan.md', content: '# notes' })
  await $.tool.call({ tool: 'Bash', command: 'ls -la' })
  await w.clock.settle()
  expect(w.runs.length).toBe(0)
})

test('a timeout keeps the previous model and marks it stale', async ($, on) => {
  let fail = false
  const w = world(on, () => {
    if (fail) throw new Error('timed out')
    return ran(GOOD)
  })
  await $.tool.call({ tool: 'Write', file_path: '.claude/plan-progress.json', content: '{}' })
  await w.clock.settle()
  fail = true
  await $.tool.call({ tool: 'Write', file_path: '.claude/plan-progress.json', content: '{}' })
  await w.clock.settle()
  expect(w.seen.last?.model?.groups[0]?.name).toBe('fixture-plan')
  expect(w.seen.last?.stale).toBe(true)
})

test('unparseable output keeps the previous model and marks it stale', async ($, on) => {
  let out = GOOD
  const w = world(on, () => ran(out))
  await $.tool.call({ tool: 'Write', file_path: '.claude/plan-progress.json', content: '{}' })
  await w.clock.settle()
  out = 'Traceback (most recent call last):'
  await $.tool.call({ tool: 'Write', file_path: '.claude/plan-progress.json', content: '{}' })
  await w.clock.settle()
  expect(w.seen.last?.model?.groups.length).toBe(1)
  expect(w.seen.last?.stale).toBe(true)
})

test('a non-zero exit is a failed refresh even when stdout parses', async ($, on) => {
  let code = 0
  const changed = JSON.stringify({ ...FIXTURE, groups: [{ ...FIXTURE.groups[0], done: 4 }] })
  const w = world(on, () => ran(code === 0 ? GOOD : changed, code))
  await $.tool.call({ tool: 'Write', file_path: '.claude/plan-progress.json', content: '{}' })
  await w.clock.settle()
  code = 2
  await $.tool.call({ tool: 'Write', file_path: '.claude/plan-progress.json', content: '{}' })
  await w.clock.settle()
  expect(w.seen.last?.model?.groups[0]?.done).toBe(2)
  expect(w.seen.last?.stale).toBe(true)
})

test('a first refresh that fails stores no model, marked stale', async ($, on) => {
  const w = world(on, () => {
    throw new Error('python3: not found')
  })
  await $.tool.call({ tool: 'Write', file_path: '.claude/plan-progress.json', content: '{}' })
  await w.clock.settle()
  expect(w.seen.last?.model).toBe(null)
  expect(w.seen.last?.stale).toBe(true)
})

test('session.start refreshes once, and the poll refreshes again every 30 s', async ($, on) => {
  const w = world(on)
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
  await w.clock.settle()
  expect(w.runs.length).toBe(1)
  await w.clock.advance(30_000)
  expect(w.runs.length).toBe(2)
  await w.clock.advance(30_000)
  expect(w.runs.length).toBe(3)
})

test('the poll is armed by a tool call too, so it survives a load that missed session.start', async ($, on) => {
  const w = world(on)
  await $.tool.call({ tool: 'Bash', command: 'ls' })
  await w.clock.settle()
  expect(w.runs.length).toBe(0)
  await w.clock.advance(30_000)
  expect(w.runs.length).toBe(1)
})

test('triggers landing during a refresh coalesce into exactly one more', async ($, on) => {
  let clock: MockClock | undefined
  const w = world(on, async () => {
    await clock!.sleep(1_000)
    return ran(GOOD)
  })
  clock = w.clock
  for (let i = 0; i < 3; i += 1) {
    await $.tool.call({ tool: 'Write', file_path: '.claude/plan-progress.json', content: '{}' })
    await w.clock.settle()
  }
  expect(w.runs.length).toBe(1)
  await w.clock.advance(1_000)
  await w.clock.advance(1_000)
  expect(w.runs.length).toBe(2)
})

test('a fault inside a refresh never fails the tool call that triggered it', async ($, on) => {
  const w = world(on, () => ran(GOOD), () => true)
  const result = await $.tool.call({ tool: 'Write', file_path: '.claude/plan-progress.json', content: '{}' })
  await w.clock.settle()
  expect(result.deny).toBe(undefined)
  expect(w.runs.length).toBe(1)
})

test('a refresh that faults still runs the one queued behind it', async ($, on) => {
  let clock: MockClock | undefined
  let writes = 0
  const w = world(
    on,
    async () => {
      await clock!.sleep(1_000)
      return ran(GOOD)
    },
    () => (writes += 1) === 1,
  )
  clock = w.clock
  await $.tool.call({ tool: 'Write', file_path: '.claude/plan-progress.json', content: '{}' })
  await w.clock.settle()
  await $.tool.call({ tool: 'Write', file_path: '.claude/plan-progress.json', content: '{}' })
  await w.clock.settle()
  await w.clock.advance(1_000)
  await w.clock.advance(1_000)
  expect(w.runs.length).toBe(2)
  expect(w.seen.last?.stale).toBe(false)
})
