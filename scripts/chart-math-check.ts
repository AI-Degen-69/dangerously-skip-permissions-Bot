// Assert-based self-check for the chart projection math. No test framework is
// wired into this repo, so this runs on bun: `bun scripts/chart-math-check.ts`.
import assert from 'node:assert/strict'

import { projectX, projectY } from '../src/app/lib/chartMath'

const start = 1_700_000_000_000
const span = 300_000
const plotW = 800
const pad = 10
const floor = 180

// The next market is revealed 15s before it opens, so its samples can carry a
// timestamp before the window start. They clamp to the left edge instead of
// landing off-canvas.
assert.equal(projectX(start - 8_000, start, span, plotW), 0)
// A sample past the window end clamps to the right edge.
assert.equal(projectX(start + span + 5_000, start, span, plotW), plotW)
// A sample inside the window maps linearly.
assert.equal(projectX(start + span / 2, start, span, plotW), plotW / 2)
// A probability outside 0..1 stays inside the plot box.
assert.equal(projectY(0, pad, floor), floor)
assert.equal(projectY(1, pad, floor), pad)
for (const v of [1.4, -0.2]) {
  const y = projectY(v, pad, floor)
  assert.ok(y >= pad && y <= floor, `y for ${v} escaped the plot: ${y}`)
}

console.log('chart math ok')
