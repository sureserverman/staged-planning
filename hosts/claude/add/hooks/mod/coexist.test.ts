import type { On } from 'claude-code'
import { expect, test } from 'claude-code/testing'

import { world } from './testing'

const CHAIN = 'PLAN_STATUSLINE_BASE=~/.claude/statusline.sh bash "$(ls -d ~/.claude/plugins/cache/some-marketplace/planning/*/ | sort -V | tail -1)skills/executing-plans/scripts/statusline-chain.sh"'

function harness(on: On, settings: () => unknown) {
  world(on)
  const toasts: string[] = []
  on('ui.toast', (_$, e) => {
    toasts.push(String((e as { text?: unknown }).text))
    return { value: undefined } as never
  })
  on('settings.read', (_$, e) => {
    expect((e as { source?: string }).source).toBe('user')
    return settings() as never
  })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  return toasts
}

const start = { cwd: '/repo', surface: 'terminal', isInteractive: true } as const

test('settings naming statusline-chain.sh -> exactly one toast across two session.starts', async ($, on) => {
  const toasts = harness(on, () => ({ value: { statusLine: { type: 'command', command: CHAIN } } }))
  await $.session.start(start)
  await $.session.start(start)
  expect(toasts.length).toBe(1)
  expect(toasts[0]).toContain('/planning:statusline remove')
  expect(toasts[0]).toContain('band')
})

test('other status-line settings -> no toast', async ($, on) => {
  const toasts = harness(on, () => ({ value: { statusLine: { type: 'command', command: 'bash ~/.claude/statusline.sh' } } }))
  await $.session.start(start)
  expect(toasts.length).toBe(0)
})

test('no status line at all -> no toast', async ($, on) => {
  const toasts = harness(on, () => ({ value: {} }))
  await $.session.start(start)
  expect(toasts.length).toBe(0)
})

test('a missing or unparseable settings file -> no toast and no throw', async ($, on) => {
  const toasts = harness(on, () => ({ deny: 'ENOENT: no such file' }))
  await $.session.start(start)
  expect(toasts.length).toBe(0)
})

test('a malformed statusLine value -> no toast and no throw', async ($, on) => {
  const toasts = harness(on, () => ({ value: { statusLine: 42 } }))
  await $.session.start(start)
  expect(toasts.length).toBe(0)
})

test('a statusLine command that is not a string -> no toast, even when it names the chain', async ($, on) => {
  const toasts = harness(on, () => ({ value: { statusLine: { type: 'command', command: ['statusline-chain.sh'] } } }))
  await $.session.start(start)
  expect(toasts.length).toBe(0)
})
