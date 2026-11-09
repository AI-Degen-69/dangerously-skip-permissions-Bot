export const LABELS: Record<string, string> = {
  // Window Timing & Planned Cutoffs
  'opening-buffer': 'Opening buffer (T+0..4s)',
  'opening-delay': 'Opening buffer (T+0..4s)',
  'too-late-in-window': 'Settlement cutoff (T−12s..0s)',
  'awaiting-resolution': 'Window ended — awaiting market resolution',

  // Entries & Snipes
  'straddle-open': 'Straddle opened — first touch',
  'hedge-pending': 'First leg filled — hedge pending',
  'hedge-leg': 'Hedge leg filled',
  'clip-fill': 'MSR-v2 ladder fill accumulated',
  'maker-dip-ladder': 'Maker dip ladder [7¢–50¢] (0% fee)',
  'hedge-equalizer': 'Lagging-leg share equalizer [75¢–95¢]',
  'working-fills': 'Active grid accumulation (M0–M3)',
  'm4-window': 'M4 late snipe & hedge window (T−60s..12s)',
  'lean-up': 'Microprice lean Up',
  'lean-down': 'Microprice lean Down',
  'straddle-balance': 'Straddle balance fill',
  'm4-snipe': 'M4 late snipe filled',
  'paper-fill': 'Paper fill',

  // Holds & Pacing
  'minute-quota-reached': 'Minute quota filled — pacing entries',
  'target-fills-reached': 'Target window fills reached',
  'spacing-guard': 'Spacing guard — orderbook replenishment',
  'window-observing': 'Observing window opening',

  // Done: Window Trading Finished
  'holding-to-resolution': 'Window trading done — holding to resolution',

  // Refusals: Conditions Refused
  'extreme-price-skip': 'Price outside active bands [7¢–50¢] / [75¢–95¢]',
  'pair-cost-cap': 'Refused — projected pair cost exceeds $0.99 cap',
  'share-lead-cap': 'Refused — share lead exceeds 90-share limit',
  'dust-quote': 'Dust quote refused (<1¢)',
  'no-liquidity': 'Quotes refused — no liquidity on this side',
  'spread-too-wide': 'Quote refused — spread too wide (>30¢)',

  // Settlement & Redemption
  'paper-resolve': 'Window settled to market outcome',
  'paper-redeem': 'Settled shares redeemed',
  won: 'Window won',
  lost: 'Window lost',
  'unresolved-fallback': 'Market resolved via fallback oracle',

  // Risk Limits & Safety Halts
  'kill-switch-engaged': 'Kill switch engaged — entries paused',
  'kill-switch-file-present': 'Kill switch active',
  'entries-resumed': 'Entries resumed',
  'window-trade-cap': 'Window trade cap reached (500)',
  'window-cost-cap': 'Window cost cap reached ($4,000)',
  'daily-loss-cap': 'Daily loss limit hit — halted',
  'daily-loss-limit': 'Daily loss limit hit — halted',
  'single-window-locked': 'Another window already active',
  'single-window-violation': 'Single-window conflict — window refused',
  'max-concurrent-positions': 'Another window already active',

  // System & Lifecycle
  'loop-started': 'Paper loop started',
  'loop-stopped': 'Paper loop stopped',
  'paper-reset': 'Paper state reset',
  'config-updated': 'Configuration updated',
  'window-failed': 'Window execution failed',
  'ws-connected': 'WebSocket connected',
  'ws-fallback-active': 'REST fallback active',

  // Legacy compatibility
  'thesis-intact': 'Straddle clip checkpoint',
  'clip-checkpoint': 'Straddle clip checkpoint',
}

export const KIND_TONE: Record<string, 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info'> = {
  entry: 'success',
  snipe: 'accent',
  done: 'accent',
  refuse: 'warning',
  hold: 'neutral',
  skip: 'warning',
  exit: 'info',
  settle: 'accent',
  blocked: 'warning',
  anchor: 'info',
  risk: 'danger',
  info: 'neutral',
  error: 'danger',
}

export const reasonLabel = (reason: string | null | undefined) =>
  !reason ? '—' : (LABELS[reason] ?? reason.replace(/[:-]/g, ' ').replace(/\s+/g, ' ').trim())

export type MetricUnit = 'ratio' | 'pct' | 'cents' | 'price' | 'sec' | 'usd' | 'count'

export interface MetricSpec {
  /** Detail key holding the measured value. */
  key: string
  /** Detail key holding the limit it was judged against. */
  threshold?: string
  op?: '<' | '>' | '>=' | '<='
  unit?: MetricUnit
  label?: string
}

/**
 * Which measured value and which limit each verdict is judged on.
 */
export const REASON_METRICS: Record<string, MetricSpec[]> = {
  'opening-delay': [{ key: 'elapsedSec', threshold: 'needsSec', op: '<', unit: 'sec' }],
  'straddle-open': [
    { key: 'cost', label: 'cost', unit: 'usd' },
    { key: 'fills', label: 'fill #' },
  ],
  'hedge-pending': [
    { key: 'price', label: 'price', unit: 'price' },
    { key: 'shares', label: 'shares' },
  ],
  'hedge-leg': [
    { key: 'cost', label: 'cost', unit: 'usd' },
    { key: 'fills', label: 'fill #' },
  ],
  'working-fills': [{ key: 'fills', label: 'fills', unit: 'count' }],
  'clip-fill': [
    { key: 'role' },
    { key: 'price', label: 'price', unit: 'price' },
    { key: 'shares', label: 'shares' },
    { key: 'pairCost', label: 'pair', unit: 'usd' },
  ],
  'm4-snipe': [
    { key: 'minute' },
    { key: 'price', label: 'price', unit: 'price' },
    { key: 'shares', label: 'shares' },
    { key: 'fills', label: 'fill #' },
  ],
  'minute-quota-reached': [
    { key: 'minute' },
    { key: 'fills', label: 'fills', unit: 'count' },
    { key: 'waitSec', label: 'wait', unit: 'sec' },
  ],
  'target-fills-reached': [
    { key: 'fills', label: 'fills', unit: 'count' },
    { key: 'cost', label: 'cost', unit: 'usd' },
  ],
  'holding-to-resolution': [
    { key: 'fills', label: 'fills', unit: 'count' },
    { key: 'cost', label: 'cost', unit: 'usd' },
    { key: 'upShares', label: 'Up', unit: 'count' },
    { key: 'downShares', label: 'Down', unit: 'count' },
  ],
  'extreme-price-skip': [
    { key: 'minute' },
    { key: 'price', label: 'odds', unit: 'price' },
  ],
  'dust-quote': [
    { key: 'minute' },
    { key: 'price', label: 'quote', unit: 'cents' },
    { key: 'minFill', label: 'min', unit: 'price' },
  ],
  'no-liquidity': [{ key: 'side', label: 'side' }],
  'spread-too-wide': [{ key: 'spreadCents', threshold: 'maxCents', op: '>', unit: 'cents' }],
  'too-late-in-window': [{ key: 'remainingSec', threshold: 'needsSec', op: '<', unit: 'sec' }],
  'paper-resolve': [
    { key: 'winner', label: 'winner' },
    { key: 'net', label: 'net', unit: 'usd' },
    { key: 'payout', label: 'payout', unit: 'usd' },
    { key: 'fills', label: 'fills', unit: 'count' },
  ],
  'paper-redeem': [
    { key: 'winner', label: 'winner' },
    { key: 'payout', label: 'payout', unit: 'usd' },
  ],
  'daily-loss-cap': [
    { key: 'lossUsd', label: 'loss', threshold: 'capUsd', op: '>=', unit: 'usd' },
  ],
  'window-cost-cap': [
    { key: 'costUsd', label: 'cost', threshold: 'capUsd', op: '>=', unit: 'usd' },
  ],
  'window-trade-cap': [
    { key: 'fills', label: 'fills', threshold: 'cap', op: '>=', unit: 'count' },
  ],
  'loop-started': [{ key: 'pid', label: 'pid' }],
  'loop-stopped': [{ key: 'pid', label: 'pid' }],
  'paper-reset': [{ key: 'bankrollUsd', label: 'bankroll', unit: 'usd' }],
  'window-failed': [{ key: 'error', label: 'err' }],
  // Legacy / fallbacks
  'thesis-intact': [
    { key: 'bid', label: 'bid', unit: 'price' },
    { key: 'price', label: 'price', unit: 'price' },
    { key: 'fills', label: 'fills', unit: 'count' },
  ],
  'clip-checkpoint': [
    { key: 'price', label: 'price', unit: 'price' },
    { key: 'fills', label: 'fills', unit: 'count' },
  ],
}

/** Rows without a paired limit still show what was measured, not empty boxes. */
const FALLBACK_METRICS: MetricSpec[] = [
  { key: 'price', label: 'price', unit: 'price' },
  { key: 'shares', label: 'shares' },
  { key: 'lean', label: 'lean', unit: 'ratio' },
  { key: 'net', label: 'net', unit: 'usd' },
  { key: 'spreadCents', label: 'spread', unit: 'cents' },
]

function formatMetric(value: unknown, unit?: MetricUnit, label?: string): string | null {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'string') return label ? `${label} ${value}` : value
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  let text: string
  switch (unit) {
    case 'pct':
      text = `${Number(value.toFixed(4))}%`
      break
    case 'cents':
      text = `${Number(value.toFixed(1))}¢`
      break
    case 'price':
      text = `${Math.round(value * 100)}¢`
      break
    case 'sec':
      text = `${Math.round(value)}s`
      break
    case 'usd':
      text = value >= 0 ? `$${value.toFixed(2)}` : `-$${Math.abs(value).toFixed(2)}`
      break
    case 'count':
      text = `${Math.round(value)}`
      break
    case 'ratio':
      text = value > 0 ? `+${value.toFixed(2)}` : value.toFixed(2)
      break
    default:
      text = Number.isInteger(value) ? String(value) : value.toFixed(2)
  }
  return label ? `${label} ${text}` : text
}

/** Value + the limit it missed, for the decision journal row. */
export function eventMetrics(
  reason: string,
  detail: Record<string, unknown> | undefined,
): { text: string; limit?: string }[] {
  if (!detail) return []
  const out: { text: string; limit?: string }[] = []
  for (const spec of REASON_METRICS[reason] ?? FALLBACK_METRICS) {
    const text = formatMetric(detail[spec.key], spec.unit, spec.label)
    if (!text) continue
    const limit = spec.threshold ? formatMetric(detail[spec.threshold], spec.unit) : null
    out.push({ text, limit: limit && spec.op ? `${spec.op} ${limit}` : undefined })
    if (out.length === 4) break
  }
  return out
}
