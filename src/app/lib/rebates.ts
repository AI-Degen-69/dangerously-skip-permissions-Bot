import { useCallback, useEffect, useState } from 'react'
import { useStoredFlag } from './flags'

/** Polymarket's parabolic taker fee per share: 0.07 · p · (1 − p). */
export const TAKER_FEE_COEFF = 0.07

/**
 * Share of collected taker fees paid back to makers (crypto markets: 20%).
 * Every maker fill is matched against a taker, so the pool one fill can claim
 * is the taker fee on the same price and size.
 */
export const MAKER_REBATE_SHARE = 0.2

export interface AccountTier {
  id: string
  name: string
  /** Trailing 30-day weighted volume that holds the tier. */
  volumeUsd: number
  /** Share of taker fees paid back at this tier. */
  rate: number
}

/** Polymarket's published taker-rebate ladder, cheapest first. */
export const ACCOUNT_TIERS: AccountTier[] = [
  { id: 'bronze', name: 'Bronze', volumeUsd: 2_000, rate: 0.03 },
  { id: 'silver', name: 'Silver', volumeUsd: 20_000, rate: 0.08 },
  { id: 'gold', name: 'Gold', volumeUsd: 200_000, rate: 0.18 },
  { id: 'platinum', name: 'Platinum', volumeUsd: 1_000_000, rate: 0.32 },
  { id: 'diamond', name: 'Diamond', volumeUsd: 4_000_000, rate: 0.44 },
  { id: 'obsidian', name: 'Obsidian', volumeUsd: 10_000_000, rate: 0.5 },
]

/** The wallet this bot is modelled on trades at Obsidian. */
export const DEFAULT_TIER_ID = 'obsidian'

const STORAGE_KEY = 'dsp.accountTier'
const TIER_EVENT = 'dsp:account-tier'

export function tierById(id: string | null | undefined): AccountTier {
  return ACCOUNT_TIERS.find((tier) => tier.id === id) ?? ACCOUNT_TIERS[ACCOUNT_TIERS.length - 1]
}

function readStoredTier(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? DEFAULT_TIER_ID
  } catch {
    return DEFAULT_TIER_ID
  }
}

/**
 * The selected account tier, shared by every page through localStorage so the
 * dashboard totals and the live orders table always agree.
 */
export function useAccountTier(): [AccountTier, (id: string) => void] {
  const [id, setId] = useState<string>(() =>
    typeof window === 'undefined' ? DEFAULT_TIER_ID : readStoredTier(),
  )

  useEffect(() => {
    const sync = () => setId(readStoredTier())
    const onPick = (event: Event) => setId(tierById((event as CustomEvent<string>).detail).id)
    window.addEventListener('storage', sync)
    window.addEventListener(TIER_EVENT, onPick)
    return () => {
      window.removeEventListener('storage', sync)
      window.removeEventListener(TIER_EVENT, onPick)
    }
  }, [])

  const pick = useCallback((next: string) => {
    const tier = tierById(next)
    setId(tier.id)
    try {
      window.localStorage.setItem(STORAGE_KEY, tier.id)
    } catch {
      // Private-mode storage failures must not block the selector.
    }
    window.dispatchEvent(new CustomEvent(TIER_EVENT, { detail: tier.id }))
  }, [])

  return [tierById(id), pick]
}

/**
 * Whether taker and maker rebates count towards the P&L. Shared by every page
 * through localStorage, so the dashboard totals, the chart and the orders table
 * always answer the same question.
 */
export function useIncludeRebates(): [boolean, (value: boolean) => void] {
  return useStoredFlag('includeRebates', true)
}

/**
 * Maker or taker for one fill, mirroring `_window_row` in bot/api.py so the
 * totals and the orders table can never disagree.
 *
 * A recorded role wins. Without one, a recorded fee decides — a charged fee means
 * the fill crossed — then the legacy reason text, and finally maker, which is
 * what the backend assumes for a fill it cannot classify.
 */
export function classifyFill(input: {
  role?: unknown
  reason?: string | null
  feeUsd?: unknown
}): 'maker' | 'taker' {
  const role = String(input.role ?? '').toLowerCase()
  if (role === 'maker' || role === 'taker') return role

  if (typeof input.feeUsd === 'number' && Number.isFinite(input.feeUsd)) {
    return input.feeUsd > 0 ? 'taker' : 'maker'
  }

  const reason = String(input.reason ?? '').toLowerCase()
  if (reason.includes('equalizer') || reason.includes('snipe')) return 'taker'
  if (reason.includes('maker')) return 'maker'
  return 'maker'
}

/** Fee per share at a price, in dollars. */
export function takerFeePerShare(price: number): number {
  const p = Math.min(1, Math.max(0, price))
  return TAKER_FEE_COEFF * p * (1 - p)
}

/**
 * Rebate earned on a settled window: the tier's share of the taker fees it paid,
 * plus the maker share of the fees its maker fills were matched against.
 */
export function windowRebate(
  window: { feesUsd?: number; makerFeeBaseUsd?: number },
  tierRate: number,
): number {
  return tierRate * (window.feesUsd ?? 0) + MAKER_REBATE_SHARE * (window.makerFeeBaseUsd ?? 0)
}

/** Taker fee actually charged on one order. Makers pay nothing. */
export function feeFor(
  price: number | null | undefined,
  shares: number | null | undefined,
  isMaker: boolean,
): number {
  if (isMaker || price == null || shares == null || price <= 0 || shares <= 0) return 0
  return shares * takerFeePerShare(price)
}

/**
 * Rebate earned on one order: a taker keeps `rate` of the fee it paid, a maker
 * claims `MAKER_REBATE_SHARE` of the fee its counterparty paid.
 */
export function rebateFor(
  price: number | null | undefined,
  shares: number | null | undefined,
  isMaker: boolean,
  tierRate: number,
  feeUsd?: number | null,
): number {
  if (isMaker) {
    if (price == null || shares == null || price <= 0 || shares <= 0) return 0
    return MAKER_REBATE_SHARE * shares * takerFeePerShare(price)
  }
  return tierRate * (feeUsd ?? feeFor(price, shares, false))
}
