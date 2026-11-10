// Assert-based self-check for the chart projection math. No test framework is
// wired into this repo, so this runs on bun: `bun scripts/chart-math-check.ts`.
import assert from 'node:assert/strict'

import { axisLabels, projectX, projectY } from '../src/app/lib/chartMath'

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

// Axis labels: both endpoints always, interior marks only when they clear every
// label already placed. Losers keep their tick line, they just lose the text.
const axisMarks = [
  { x: 5, label: '0:04', title: 'gate at 4s' }, // hugs 0:00
  { x: 160, label: '1:00', title: 'minute 1' },
  { x: 170, label: '1:05', title: 'minute 1b' }, // collides with the 1:00 label
  { x: 320, label: '2:00', title: 'minute 2' },
  { x: 790, label: '4:56', title: 'cutoff' }, // hugs the 5:00 label
]
const axisOut = axisLabels(
  axisMarks,
  800,
  26,
  { label: '0:00', title: 'Window opens' },
  { label: '5:00', title: 'Window closes' },
)
assert.deepEqual(
  axisOut.map((label) => label.label),
  ['0:00', '1:00', '2:00', '5:00'],
  'endpoints kept, near-edge and colliding interior labels dropped',
)
assert.deepEqual(
  axisOut.map((label) => label.anchor),
  ['start', 'middle', 'middle', 'end'],
  'edge labels anchor inward',
)

console.log('chart math ok')
