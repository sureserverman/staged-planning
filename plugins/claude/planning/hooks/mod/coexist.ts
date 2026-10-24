// The band and the status-line bar show the same plans. When the user's status
// line still runs the chain that draws the bar, say once per session that
// /planning:statusline remove takes it out. Read only: the settings file is
// never written here (the installer owns that write).

import { atom, read, update } from 'claude-code'
import type { On } from 'claude-code'

// Session-scoped, so a hot reload does not repeat the toast.
const NOTED = atom({ plugin: 'planning', key: 'statuslineNoted' } as const, false)

const CHAIN = /statusline-chain\.sh/

export function registerCoexist(on: On): void {
  on('session.start', { isInteractive: true }, async ($, e, next) => {
    const started = await next(e)
    try {
      if (await read($, NOTED)) return started
      const settings = (await $.settings.read({ source: 'user' })) as { statusLine?: unknown }
      const line = settings?.statusLine
      const command =
        line !== null && typeof line === 'object' ? (line as { command?: unknown }).command : undefined
      if (typeof command === 'string' && CHAIN.test(command)) {
        await update($, NOTED, () => true)
        $.ui.toast(
          'The plan progress band now shows above the prompt; /planning:statusline remove takes the duplicate status-line bar out.',
          { timeoutMs: 8000 },
        )
      }
    } catch {
      // a missing or unreadable settings file is no reason to say anything
    }
    return started
  })
}
