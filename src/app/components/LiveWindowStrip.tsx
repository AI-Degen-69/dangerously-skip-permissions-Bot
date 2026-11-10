import { Badge } from './ui'
import type { MarketView, WsStatus } from '../lib/bot'

const cents = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `${Math.round(value * 100)}¢`

export interface LiveWindowStripProps {
  markets: MarketView[]
  ws?: WsStatus
}

export function LiveWindowStrip({ markets, ws }: LiveWindowStripProps) {
  const activeMarket = markets[0]

  const upBid = ws?.up_book?.best_bid ?? activeMarket?.quotes?.Up?.bid ?? null
  const upAsk = ws?.up_book?.best_ask ?? activeMarket?.quotes?.Up?.ask ?? null

  const downBid = ws?.down_book?.best_bid ?? activeMarket?.quotes?.Down?.bid ?? null
  const downAsk = ws?.down_book?.best_ask ?? activeMarket?.quotes?.Down?.ask ?? null

  return (
    <div className="grid w-full grid-cols-2 gap-2 select-none">
      {/* UP SIDE */}
      <div className="relative flex items-stretch justify-between overflow-hidden rounded-xl border border-line bg-surface-1 py-2 px-3 transition-all">
        <div className="pointer-events-none absolute -left-10 top-0 h-full w-24 bg-emerald-500/5 blur-xl" />

        {/* Outer Left: UP ↗ Badge */}
        <div className="flex items-center gap-2">
          <Badge tone="success" className="px-2 py-0.5 text-[11px] font-semibold tracking-wide">
            UP ↗
          </Badge>
          <span className="text-[10px] font-medium tracking-wider uppercase text-faint">Live</span>
        </div>

        {/* Center: Ask */}
        <div className="flex flex-1 flex-col items-center justify-center px-2">
          <span className="text-[9.5px] uppercase tracking-wider text-faint font-medium">Ask</span>
          <span className="font-mono text-[13px] font-semibold tabular-nums text-fg">{cents(upAsk)}</span>
        </div>

        {/* Inner Right: Fixed Width Bid Slot */}
        <div className="flex w-[160px] shrink-0 items-center justify-between border-l border-line pl-4">
          <span className="text-[10px] uppercase tracking-wider text-emerald-400/80 font-medium">Bid</span>
          <span className="font-mono text-[22px] font-bold leading-none tabular-nums text-emerald-400">
            {cents(upBid)}
          </span>
        </div>
      </div>

      {/* DN SIDE (MIRRORED) */}
      <div className="relative flex items-stretch justify-between overflow-hidden rounded-xl border border-line bg-surface-1 py-2 px-3 transition-all">
        <div className="pointer-events-none absolute -right-10 top-0 h-full w-24 bg-rose-500/5 blur-xl" />

        {/* Inner Left: Fixed Width Bid Slot */}
        <div className="flex w-[160px] shrink-0 items-center justify-between border-r border-line pr-4">
          <span className="font-mono text-[22px] font-bold leading-none tabular-nums text-rose-400">
            {cents(downBid)}
          </span>
          <span className="text-[10px] uppercase tracking-wider text-rose-400/80 font-medium">Bid</span>
        </div>

        {/* Center: Ask */}
        <div className="flex flex-1 flex-col items-center justify-center px-2">
          <span className="text-[9.5px] uppercase tracking-wider text-faint font-medium">Ask</span>
          <span className="font-mono text-[13px] font-semibold tabular-nums text-fg">{cents(downAsk)}</span>
        </div>

        {/* Outer Right: DN ↘ Badge */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-medium tracking-wider uppercase text-faint">Live</span>
          <Badge tone="danger" className="px-2 py-0.5 text-[11px] font-semibold tracking-wide">
            DN ↘
          </Badge>
        </div>
      </div>
    </div>
  )
}
