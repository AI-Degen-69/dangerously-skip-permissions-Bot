// Assert-based self-check for the dashboard's scope + rebate math. No test
// framework is wired into this repo, so this runs on bun:
// `bun scripts/pnl-scope-check.ts`.
import assert from 'node:assert/strict'

import type { PerfWindow } from '../src/app/lib/bot'
import { computeKpiStats } from '../src/app/lib/kpiStats'
import { scopeWindows, timeframeStart, TIMEFRAMES } from '../src/app/lib/timeframes'

const MINUTE = 60_000
const NOW = 1_700_000_000_000

function win(startMs: number, netUsd: number, feesUsd = 0, makerFeeBaseUsd = 0): PerfWindow {
  return {
    slug: `w-${startMs}`,
    market: null,
    startMs,
    trades: 4,
    costUsd: 10,
    payoutUsd: 10 + netUsd,
    netUsd,
    winner: netUsd >= 0 ? 'Up' : 'Down',
    pending: false,
    redeemed: true,
    bothSides: true,
    upFills: 2,
    downFills: 2,
    zeroPriceFills: 0,
    mShape: [],
    feesUsd,
    makerFeeBaseUsd,
  }
}

// Two windows: one two hours old, one thirty minutes old.
const windows = [
  win(NOW - 120 * MINUTE, 5, 20, 100),
  win(NOW - 30 * MINUTE, -2, 10, 50),
]

// All-time view: nothing is dropped and the base stays at the starting capital.
const all = scopeWindows(windows, timeframeStart(TIMEFRAMES[5], NOW), 0.5, true, 1000)
assert.equal(all.windows.length, 2)
assert.equal(all.baseCapital, 1000)

// A one-hour view keeps the recent window and starts from the capital the
// account held when the hour began: 1000 + the older window's net (+ its rebate).
const hour = scopeWindows(windows, timeframeStart(TIMEFRAMES[0], NOW), 0.5, true, 1000)
assert.equal(hour.windows.length, 1)
assert.equal(hour.baseCapital, 1000 + 5 + (0.5 * 20 + 0.2 * 100))

// The rebate toggle reaches every stat: net, win rate and the capital curve.
const tierRate = 0.5
const withRebates = computeKpiStats(windows, 1000, undefined, tierRate, true)
const withoutRebates = computeKpiStats(windows, 1000, undefined, tierRate, false)
// Taker rebate 0.5 × 30 fees, maker rebate 0.2 × 150 matched fees.
assert.equal(withRebates.rebatesUsd, 45)
assert.equal(withRebates.netUsd, 3 + 45)
assert.equal(withoutRebates.netUsd, 3)
assert.equal(withoutRebates.netBeforeRebateUsd, 3)
assert.equal(withoutRebates.rebatesCounted, false)
assert.equal(withRebates.rebatesCounted, true)
// The rebate reaches the win rate too: the losing window earns 15 in rebates,
// so it closes positive and the win count moves.
assert.equal(withoutRebates.winsCount, 1)
assert.equal(withRebates.winsCount, 2)

// The scoped base and the scoped stats must agree on the capital left.
const scopedStats = computeKpiStats(
  hour.windows,
  hour.baseCapital,
  undefined,
  tierRate,
  true,
)
assert.equal(scopedStats.currentCapital, hour.baseCapital + scopedStats.netUsd)
assert.equal(scopedStats.netUsd, -2 + (0.5 * 10 + 0.2 * 50))

console.log('pnl scope ok')
