import { expect, test } from 'claude-code/testing'

test('the module loads and session.start reaches the engine beneath it', async ($, on) => {
  let reached = 0
  on('session.start', (_$, e) => {
    reached += 1
    return { cwd: e.cwd }
  })
  const started = await $.session.start({ cwd: '/work', surface: null, isInteractive: false })
  expect(reached).toBe(1)
  expect(started.cwd).toBe('/work')
})
