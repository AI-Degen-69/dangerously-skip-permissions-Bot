import { Badge } from './ui'
import { cx } from '../lib/cx'
import type { PositionView } from '../lib/bot'

const money = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `${value < 0 ? '−' : ''}$${Math.abs(value).toFixed(2)}`
const cents = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `${Math.round(value * 100)}¢`

export interface OpenPositionsStripProps {
  positions: PositionView[]
}

export function OpenPositionsStrip({ positions }: OpenPositionsStripProps) {
  const upPos = positions.find((p) => p.side === 'Up')
  const downPos = positions.find((p) => p.side === 'Down')

  const upShares = Math.round(upPos?.shares ?? 0)
  const downShares = Math.round(downPos?.shares ?? 0)

  const upAvg = upPos?.entryPrice ?? null
  const downAvg = downPos?.entryPrice ?? null

  const upPnl = upPos?.unrealizedPnlUsd ?? null
  const downPnl = downPos?.unrealizedPnlUsd ?? null

  return (
    <div className="grid w-full grid-cols-2 gap-2 select-none">
      {/* UP SIDE */}
      <div className="relative flex items-stretch justify-between overflow-hidden rounded-xl border border-line bg-surface-1 py-2 px-3 transition-all">
        {/* Outer Left: UP ↗ Badge */}
        <div className="flex items-center gap-2">
          <Badge tone="success" className="px-2 py-0.5 text-[11px] font-semibold tracking-wide">
            UP ↗
          </Badge>
          <span className="text-[10px] font-medium tracking-wider uppercase text-faint">Held</span>
        </div>

        {/* Center: Position Avg Cost */}
        <div className="flex flex-1 flex-col items-center justify-center px-2">
          <span className="text-[9.5px] uppercase tracking-wider text-faint font-medium">Avg Cost</span>
          <span className="font-mono text-[13px] font-semibold tabular-nums text-fg">{cents(upAvg)}</span>
        </div>

        {/* Inner Right: Fixed Width (w-[160px]) Shares & PnL */}
        <div className="flex w-[160px] shrink-0 items-center justify-between border-l border-line pl-4">
          <span
            className={cx(
              'font-mono text-[12px] font-medium tabular-nums',
              upPnl == null ? 'text-faint' : upPnl >= 0 ? 'text-success' : 'text-danger',
            )}
          >
            {money(upPnl)}
          </span>
          <div className="flex items-baseline gap-1">
            <span className="font-mono text-[22px] font-bold leading-none tabular-nums text-emerald-400">
              {upShares}
            </span>
            <span className="text-[10px] uppercase text-emerald-500/80">sh</span>
          </div>
        </div>
      </div>

      {/* DN SIDE (MIRRORED) */}
      <div className="relative flex items-stretch justify-between overflow-hidden rounded-xl border border-line bg-surface-1 py-2 px-3 transition-all">
        {/* Inner Left: Fixed Width (w-[160px]) Shares & PnL */}
        <div className="flex w-[160px] shrink-0 items-center justify-between border-r border-line pr-4">
          <div className="flex items-baseline gap-1">
            <span className="font-mono text-[22px] font-bold leading-none tabular-nums text-rose-400">
              {downShares}
            </span>
            <span className="text-[10px] uppercase text-rose-500/80">sh</span>
          </div>
          <span
            className={cx(
              'font-mono text-[12px] font-medium tabular-nums',
              downPnl == null ? 'text-faint' : downPnl >= 0 ? 'text-success' : 'text-danger',
            )}
          >
            {money(downPnl)}
          </span>
        </div>

        {/* Center: Position Avg Cost */}
        <div className="flex flex-1 flex-col items-center justify-center px-2">
          <span className="text-[9.5px] uppercase tracking-wider text-faint font-medium">Avg Cost</span>
          <span className="font-mono text-[13px] font-semibold tabular-nums text-fg">{cents(downAvg)}</span>
        </div>

        {/* Outer Right: DN ↘ Badge */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-medium tracking-wider uppercase text-faint">Held</span>
          <Badge tone="danger" className="px-2 py-0.5 text-[11px] font-semibold tracking-wide">
            DN ↘
          </Badge>
        </div>
      </div>
    </div>
  )
}
