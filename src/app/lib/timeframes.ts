import type { PerfWindow } from './bot'
import { windowRebate } from './rebates'

export interface Timeframe {
  id: string
  label: string
  /** Length of the trailing window in ms; null means since inception. */
  ms: number | null
}

/** The views the dashboard can be scoped to, shortest first. */
export const TIMEFRAMES: Timeframe[] = [
  { id: '1h', label: '1H', ms: 60 * 60 * 1000 },
  { id: '12h', label: '12H', ms: 12 * 60 * 60 * 1000 },
  { id: '1d', label: '1D', ms: 24 * 60 * 60 * 1000 },
  { id: '1w', label: '1W', ms: 7 * 24 * 60 * 60 * 1000 },
  { id: '1m', label: '1M', ms: 30 * 24 * 60 * 60 * 1000 },
  { id: 'all', label: 'All', ms: null },
]

/** Start of the trailing window, or -Infinity when the timeframe is all-time. */
export function timeframeStart(timeframe: Timeframe, now: number): number {
  return timeframe.ms == null ? -Infinity : now - timeframe.ms
}

export interface ScopedView {
  /** The settled windows inside the timeframe. */
  windows: PerfWindow[]
  /** Capital at the start of the timeframe, so the curve starts where the account was. */
  baseCapital: number
}

/**
 * Slice the settled windows down to a timeframe and work out the capital the
 * account held when that slice began. Rebate credit follows the toggle, so the
 * base and the slice always move together.
 */
export function scopeWindows(
  windows: PerfWindow[],
  cutoff: number,
  tierRate: number,
  includeRebates: boolean,
  startingCapital: number,
): ScopedView {
  const netOf = (w: PerfWindow) =>
    (w.netUsd ?? 0) + (includeRebates ? windowRebate(w, tierRate) : 0)
  const scoped = windows.filter((w) => w.startMs >= cutoff)
  const baseCapital =
    startingCapital +
    windows.filter((w) => w.startMs < cutoff).reduce((sum, w) => sum + netOf(w), 0)
  return { windows: scoped, baseCapital }
}
