import type { PerfWindow } from './bot'

/**
 * The same window recomputed from the fills the tape verifier confirmed, or
 * null when it has none: a window without a verified fill contributes nothing
 * to a verified-only P&L, so it drops out of the view entirely.
 */
export function verifiedWindow(window: PerfWindow): PerfWindow | null {
  const verified = window.verified
  if (!verified || verified.trades === 0) return null
  return {
    ...window,
    trades: verified.trades,
    costUsd: verified.costUsd,
    payoutUsd: verified.payoutUsd,
    netUsd: window.pending ? null : verified.netUsd,
    upFills: verified.upFills,
    downFills: verified.downFills,
    zeroPriceFills: verified.zeroPriceFills,
    feesUsd: verified.feesUsd,
    makerFeeBaseUsd: verified.makerFeeBaseUsd,
    bothSides: verified.upFills > 0 && verified.downFills > 0,
  }
}
