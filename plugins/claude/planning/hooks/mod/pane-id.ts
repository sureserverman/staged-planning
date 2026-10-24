// The plan pane's id (letters, digits, _ and - only), shared by the band's Plan button and the /plan-view command.
export const PLAN_PANE = 'planning-plan'
export const PLAN_PANE_TITLE = 'Plan'

// A plan's own pane: `planning-plan-<id>`, the id the script's 8 hex. One RegExp
// matches the whole family, the pinned plan's pane included.
export const PLAN_ID = /^[0-9a-f]{8}$/
export const PLAN_PANES = /^planning-plan(-[0-9a-f]{8})?$/
export const planPaneId = (id: string): string => `${PLAN_PANE}-${id}`
