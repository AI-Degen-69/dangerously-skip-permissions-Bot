import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { PositionView } from '../lib/bot'
import { pairCostTone } from '../lib/format'

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
      <span className="align-sub text-[10px] leading-none opacity-70">{third[2]}</span>
    </>
  )
}

export interface OpenPositionsStripProps {
  positions: PositionView[]
  /** Strategy's pair-cost cap (`entry.maxPairCost`); colors the center pill. */
  pairCostCap?: number
}

export function OpenPositionsStrip({ positions, pairCostCap = 0.985 }: OpenPositionsStripProps) {
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
      <div className="relative flex min-w-0 flex-1 items-center justify-between overflow-hidden rounded-2xl border border-border bg-card/90 px-3 py-2 shadow-2xs transition-all">
        {/* Outer Left: UP ↗ Badge — fixed width so separator aligns across rows */}
        <div className="flex w-[84px] shrink-0 items-center gap-1.5">
          <Badge
            variant="outline"
            className="border-emerald-500/30 bg-emerald-500/10 px-2 font-mono text-[11px] font-semibold tracking-wide text-emerald-600 dark:text-emerald-400"
          >
            UP ↗
          </Badge>
          <span className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">Held</span>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {/* Avg Cost — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline justify-end gap-1.5 pr-2">
              <span className="block text-[9px] font-medium tracking-wider text-muted-foreground uppercase">
                Avg Cost
              </span>
              <span className="font-mono text-[13px] font-semibold text-foreground tabular-nums">{cents(upAvg)}</span>
            </div>
          </div>
          {/* Separator — anchored at fixed position (matches LiveWindowStrip) */}
          <div className="h-7 w-px shrink-0 bg-border" />
          {/* PnL & Shares — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline justify-end gap-1.5 pr-2">
              <span
                className={cn(
                  'block font-mono text-[11px] font-medium tabular-nums',
                  upPnl == null
                    ? 'text-muted-foreground'
                    : upPnl >= 0
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : 'text-rose-600 dark:text-rose-400',
                )}
              >
                {money(upPnl)}
              </span>
              <div className="flex items-baseline justify-end gap-1">
                <span className="font-mono text-[19px] leading-none font-bold text-emerald-600 tabular-nums dark:text-emerald-400">
                  {upShares}
                </span>
                <span className="text-[10px] text-emerald-600/80 uppercase dark:text-emerald-400/80">sh</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* CENTER METRIC: INVENTORY PAIR COST (UP avg + DN avg) */}
      <div
        className="-my-0.5 flex w-16 shrink-0 items-center justify-center self-stretch rounded-xl border border-border bg-muted/60"
        title="UP avg cost + DN avg cost"
      >
        <span
          className={`font-mono text-lg leading-none font-extrabold tabular-nums ${pairCostTone(pairCost, pairCostCap)}`}
        >
          {money3(pairCost)}
        </span>
      </div>

      {/* DN SIDE (MIRRORED) */}
      <div className="relative flex min-w-0 flex-1 items-center justify-between overflow-hidden rounded-2xl border border-border bg-card/90 px-3 py-2 shadow-2xs transition-all">
        <div className="flex shrink-0 items-center gap-2">
          {/* PnL & Shares — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline gap-1.5 pl-2">
              <span
                className={cn(
                  'block font-mono text-[11px] font-medium tabular-nums',
                  downPnl == null
                    ? 'text-muted-foreground'
                    : downPnl >= 0
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : 'text-rose-600 dark:text-rose-400',
                )}
              >
                {money(downPnl)}
              </span>
              <div className="flex items-baseline gap-1">
                <span className="font-mono text-[19px] leading-none font-bold text-rose-600 tabular-nums dark:text-rose-400">
                  {downShares}
                </span>
                <span className="text-[10px] text-rose-600/80 uppercase dark:text-rose-400/80">sh</span>
              </div>
            </div>
          </div>
          {/* Separator — anchored at fixed position (matches LiveWindowStrip) */}
          <div className="h-7 w-px shrink-0 bg-border" />
          {/* Avg Cost — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline gap-1.5 pl-2">
              <span className="font-mono text-[13px] font-semibold text-foreground tabular-nums">
                {cents(downAvg)}
              </span>
              <span className="block text-[9px] font-medium tracking-wider text-muted-foreground uppercase">
                Avg Cost
              </span>
            </div>
          </div>
        </div>

        {/* Outer Right: DN ↘ Badge — fixed width so separator aligns across rows */}
        <div className="flex w-[84px] shrink-0 items-center justify-end gap-1.5">
          <span className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">Held</span>
          <Badge
            variant="outline"
            className="border-rose-500/30 bg-rose-500/10 px-2 font-mono text-[11px] font-semibold tracking-wide text-rose-600 dark:text-rose-400"
          >
            DN ↘
          </Badge>
        </div>
      </div>
    </div>
  )
}
