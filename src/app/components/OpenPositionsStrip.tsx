import { Badge } from './ui'
import { cx } from '../lib/cx'
import { pairCostTone } from '../lib/format'
import type { PositionView } from '../lib/bot'

const money = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `${value < 0 ? '−' : ''}$${Math.abs(value).toFixed(2)}`
const cents = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `${Math.round(value * 100)}¢`

/** Three-decimal money: the last digit renders small and subscripted. */
const money3 = (value: number | null | undefined) => {
  if (value === null || value === undefined) return <>—</>
  const [whole, third] = value.toFixed(3).split('.')
  return (
    <>
      {whole}.{third.slice(0, 2)}
      <span className="text-[10px] align-sub leading-none opacity-70">{third[2]}</span>
    </>
  )
}

export interface OpenPositionsStripProps {
  positions: PositionView[]
  /** Strategy's pair-cost cap (`entry.maxPairCost`); colors the center pill. */
  pairCostCap?: number
}

export function OpenPositionsStrip({ positions, pairCostCap = 0.99 }: OpenPositionsStripProps) {
  const upPos = positions.find((p) => p.side === 'Up')
  const downPos = positions.find((p) => p.side === 'Down')

  const upShares = Math.round(upPos?.shares ?? 0)
  const downShares = Math.round(downPos?.shares ?? 0)

  const upAvg = upPos?.entryPrice ?? null
  const downAvg = downPos?.entryPrice ?? null

  const upPnl = upPos?.unrealizedPnlUsd ?? null
  const downPnl = downPos?.unrealizedPnlUsd ?? null

  // Inventory pair cost: UP avg cost + DN avg cost (e.g. 52¢ + 48¢ = $1.00)
  const pairCost = upAvg != null && downAvg != null ? upAvg + downAvg : null

  // Fixed width for the label+value column so separator stays anchored (matches LiveWindowStrip)
  // Must accommodate: "-XXX.XX$ 999 sh" (widest possible in this row)
  const col = 'w-[112px] shrink-0'

  return (
    <div className="flex w-full items-center gap-2 select-none">
      {/* UP SIDE */}
      <div className="relative flex min-w-0 flex-1 items-center justify-between overflow-hidden rounded-xl border border-line bg-surface-1 px-3 py-2 transition-all">
        {/* Outer Left: UP ↗ Badge — fixed width so separator aligns across rows */}
        <div className="flex shrink-0 w-[84px] items-center gap-2">
          <Badge tone="success" className="px-2 py-0.5 text-[11px] font-semibold tracking-wide">
            UP ↗
          </Badge>
          <span className="text-[10px] font-medium tracking-wider uppercase text-faint">Held</span>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {/* Avg Cost — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline justify-end gap-1.5 pr-2">
              <span className="block text-[9px] font-medium tracking-wider uppercase text-faint">Avg Cost</span>
              <span className="font-mono text-[13px] font-semibold tabular-nums text-fg">{cents(upAvg)}</span>
            </div>
          </div>
          {/* Separator — anchored at fixed position (matches LiveWindowStrip) */}
          <div className="h-7 w-px bg-line shrink-0" />
          {/* PnL & Shares — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline justify-end gap-1.5 pr-2">
              <span
                className={cx(
                  'block font-mono text-[11px] font-medium tabular-nums',
                  upPnl == null ? 'text-faint' : upPnl >= 0 ? 'text-success' : 'text-danger',
                )}
              >
                {money(upPnl)}
              </span>
              <div className="flex items-baseline justify-end gap-1">
                <span className="font-mono text-[19px] font-bold leading-none tabular-nums text-emerald-400">
                  {upShares}
                </span>
                <span className="text-[10px] uppercase text-emerald-500/80">sh</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* CENTER METRIC: INVENTORY PAIR COST (UP avg + DN avg) */}
      <div
        className="flex w-16 shrink-0 -my-0.5 self-stretch items-center justify-center rounded-lg border border-line bg-surface-2"
        title="UP avg cost + DN avg cost"
      >
        <span
          className={`font-mono text-lg font-extrabold leading-none tabular-nums ${pairCostTone(pairCost, pairCostCap)}`}
        >
          {money3(pairCost)}
        </span>
      </div>

      {/* DN SIDE (MIRRORED) */}
      <div className="relative flex min-w-0 flex-1 items-center justify-between overflow-hidden rounded-xl border border-line bg-surface-1 px-3 py-2 transition-all">
        <div className="flex shrink-0 items-center gap-2">
          {/* PnL & Shares — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline gap-1.5 pl-2">
              <span
                className={cx(
                  'block font-mono text-[11px] font-medium tabular-nums',
                  downPnl == null ? 'text-faint' : downPnl >= 0 ? 'text-success' : 'text-danger',
                )}
              >
                {money(downPnl)}
              </span>
              <div className="flex items-baseline gap-1">
                <span className="font-mono text-[19px] font-bold leading-none tabular-nums text-rose-400">
                  {downShares}
                </span>
                <span className="text-[10px] uppercase text-rose-500/80">sh</span>
              </div>
            </div>
          </div>
          {/* Separator — anchored at fixed position (matches LiveWindowStrip) */}
          <div className="h-7 w-px bg-line shrink-0" />
          {/* Avg Cost — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline gap-1.5 pl-2">
              <span className="font-mono text-[13px] font-semibold tabular-nums text-fg">{cents(downAvg)}</span>
              <span className="block text-[9px] font-medium tracking-wider uppercase text-faint">Avg Cost</span>
            </div>
          </div>
        </div>

        {/* Outer Right: DN ↘ Badge — fixed width so separator aligns across rows */}
        <div className="flex shrink-0 w-[84px] items-center gap-2 justify-end">
          <span className="text-[10px] font-medium tracking-wider uppercase text-faint">Held</span>
          <Badge tone="danger" className="px-2 py-0.5 text-[11px] font-semibold tracking-wide">
            DN ↘
          </Badge>
        </div>
      </div>
    </div>
  )
}
