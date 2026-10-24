// The planning plugin's hooks module (Claude Code 2.1.288+). It is the Claude Code
// layer over the shared Python scripts under ../../skills/executing-plans/scripts/:
// it gathers inputs and draws, and never reimplements rendering, classification or
// a verdict. Hosts without mods keep using the scripts directly.

import type { Register } from 'claude-code'

import { registerAgents } from './agents'
import { registerBand } from './band'
import { registerCoexist } from './coexist'
import { registerContext } from './context'
import { registerModel } from './model'
import { registerPane } from './pane'
import { registerStop } from './stop'

export const register: Register = on => {
  registerModel(on)
  registerBand(on)
  registerAgents(on)
  registerPane(on)
  registerCoexist(on)
  registerStop(on)
  registerContext(on)
}
