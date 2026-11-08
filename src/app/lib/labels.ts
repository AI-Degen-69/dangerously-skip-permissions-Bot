export const LABELS: Record<string, string> = {
  // Window Timing & Planned Cutoffs
  'opening-delay': 'Waiting opening delay (~T+13s)',
  'too-late-in-window': 'Planned entry cutoff (last 15s)',
  'awaiting-resolution': 'Window ended — awaiting market resolution',

  // Order Execution & Fills
  'straddle-open': 'Market opened — first touch',
  'hedge-leg': 'Hedge leg filled (+15s) — both sides held',
  'working-fills': 'Working fills (M1–M3)',
  'm4-snipe': 'M4 late snipe & fade',
  'thesis-intact': 'Accumulating fills on pace',
  'paper-fill': 'Paper fill executed',
  'paper-redeem': 'Paper redeem completed',

  // Market & Orderbook Gates (Skips)
  'no-liquidity': 'No quotes available on ask',
  'spread-too-wide': 'Spread too wide (> 30¢)',
  'dust-quote': 'Dust quote (< 1¢) — skipped',
  'early-extreme-skip': 'Extreme price (<15¢ / >85¢) — skipped until M4',
  'orderbook-pacing': 'Pacing fill — waiting orderbook replenishment',

  // Risk & Safeguards
  'kill-switch-engaged': 'Kill switch engaged — entries paused',
  'kill-switch-file-present': 'Kill switch engaged — entries paused',
  'daily-loss-limit': 'Daily loss limit hit ($500) — halted',
  'window-cost-cap': 'Window cost limit reached ($4,000)',
  'window-trade-cap': 'Window fill limit reached (500 trades)',
  'single-window-locked': 'Another window already active',
  'max-concurrent-positions': 'Another window already active',
  'window-failed': 'Window processing error',

  // Resolution & Outcomes
  won: 'Window won',
  lost: 'Window lost',
  'paper-resolve': 'Market resolved',
  'unresolved-fallback': 'Market resolved via fallback oracle',

  // System Runtime Status
  'loop-started': 'Paper loop started',
  'loop-stopped': 'Paper loop stopped',
  'paper-reset': 'Paper state reset',
  'config-updated': 'Configuration updated',
  'entries-resumed': 'Entries resumed',
}

export const KIND_TONE: Record<string, 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info'> = {
  entry: 'success',
  exit: 'info',
  settle: 'accent',
  hold: 'neutral',
  skip: 'neutral',
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
  op?: '<' | '>'
  unit?: MetricUnit
  label?: string
}

/**
 * Which measured value and which limit each verdict is judged on. The engine
 * writes both into the event detail, so the journal can show `0.038% < 0.05%`
 * instead of an unlabelled number.
 */
export const REASON_METRICS: Record<string, MetricSpec[]> = {
  'opening-delay': [{ key: 'elapsedSec', threshold: 'needsSec', op: '<', unit: 'sec' }],
  'too-late-in-window': [{ key: 'remainingSec', threshold: 'needsSec', op: '<', unit: 'sec' }],
  'spread-too-wide': [{ key: 'spreadCents', threshold: 'maxCents', op: '>', unit: 'cents' }],
  'dust-quote': [{ key: 'price', label: 'price', unit: 'price' }],
  'no-liquidity': [{ key: 'side', label: 'side' }],
  'straddle-open': [
    { key: 'price', label: 'price', unit: 'price' },
    { key: 'shares', label: 'shares' },
    { key: 'lean', label: 'lean', unit: 'ratio' },
  ],
  'hedge-leg': [
    { key: 'price', label: 'price', unit: 'price' },
    { key: 'shares', label: 'shares' },
  ],
  'working-fills': [{ key: 'fills', label: 'fills', unit: 'count' }],
  'thesis-intact': [
    { key: 'bid', label: 'bid', unit: 'price' },
    { key: 'fills', label: 'fills', unit: 'count' },
  ],
  'paper-resolve': [
    { key: 'net', label: 'net', unit: 'usd' },
    { key: 'fills', label: 'fills', unit: 'count' },
  ],
  // Journal rows that are not entry attempts: anchors and open-position holds.
  'anchor captured at window open': [
    { key: 'price', label: 'anchor', unit: 'usd' },
    { key: 'source', label: 'source' },
  ],
  'thesis-intact': [{ key: 'bid', label: 'bid', unit: 'price' }],
  'stalled-but-waiting': [
    { key: 'bid', label: 'bid', unit: 'price' },
    { key: 'stalledSec', label: 'stalled', unit: 'sec' },
  ],
  'accept-loss-at-resolution': [{ key: 'bid', label: 'bid', unit: 'price' }],
  'no-bid': [{ key: 'bid', label: 'bid', unit: 'price' }],
  'confirmed-mispricing': [
    { key: 'price', label: 'price', unit: 'price' },
    { key: 'modelProb', label: 'p', unit: 'ratio' },
    { key: 'edge', label: 'edge', unit: 'ratio' },
  ],
}

/** Rows without a paired limit still show what was measured, not empty boxes. */
const FALLBACK_METRICS: MetricSpec[] = [
  { key: 'modelProb', label: 'p', unit: 'ratio' },
  { key: 'edge', label: 'edge', unit: 'ratio' },
  { key: 'movePct', label: 'move', unit: 'pct' },
  { key: 'spreadCents', label: 'spread', unit: 'cents' },
  { key: 'anchorSource' },
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
      text = `${Number(value.toFixed(2))}¢`
      break
    case 'price':
      text = `${Math.round(value * 100)}¢`
      break
    case 'sec':
      text = `${Math.round(value)}s`
      break
    case 'usd':
      text = Number.isInteger(value) ? `$${value}` : `$${value.toFixed(2)}`
      break
    case 'count':
      text = `${Math.round(value)}`
      break
    default:
      text = Number.isInteger(value) ? String(value) : value.toFixed(3)
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
    if (out.length === 3) break
  }
  return out
}
