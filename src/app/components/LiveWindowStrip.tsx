import { Badge } from './ui'
import { pairCostTone } from '../lib/format'
import type { MarketView, WsStatus } from '../lib/bot'

const cents = (value: number | null | undefined) =>
  value === null || value === undefined ? '-' : `${Math.round(value * 100)}¢`

const cents3 = (value: number | null | undefined) => {
  if (value === null || value === undefined) return '-'
  const c = Math.round(value * 1000)
  const whole = Math.floor(c / 10)
  const third = c % 10
  return `${whole}<span class="text-[10px] align-sub leading-none opacity-70">${third}</span>¢`
}

export interface LiveWindowStripProps {
  markets: MarketView[]
  ws?: WsStatus
  /** Strategy's pair-cost cap (`entry.maxPairCost`); colors the center pill. */
  pairCostCap?: number
}

export function LiveWindowStrip({ markets, ws, pairCostCap = 0.99 }: LiveWindowStripProps) {
  const activeMarket = markets[0]

  const upBid = ws?.up_book?.best_bid ?? activeMarket?.quotes?.Up?.bid ?? null
  const upAsk = ws?.up_book?.best_ask ?? activeMarket?.quotes?.Up?.ask ?? null

  const downBid = ws?.down_book?.best_bid ?? activeMarket?.quotes?.Down?.bid ?? null
  const downAsk = ws?.down_book?.best_ask ?? activeMarket?.quotes?.Down?.ask ?? null

  // Pair bid: UP bid + DN bid (e.g. 47¢ + 51¢ = 98¢)
  const pairBid = upBid != null && downBid != null ? upBid + downBid : null

  // Fixed width for the label+value column so separator stays anchored
  // Must accommodate: "-XXX.XX$ 999 sh" (widest possible in row 2)
  const col = 'w-[112px] shrink-0'

  return (
    <div className="flex w-full items-center gap-2 select-none">
      {/* UP SIDE */}
      <div className="relative flex min-w-0 flex-1 items-center justify-between overflow-hidden rounded-xl border border-line bg-surface-1 px-3 py-2 transition-all">
        <div className="pointer-events-none absolute -left-10 top-0 h-full w-24 bg-emerald-500/5 blur-xl" />

        {/* Outer Left: UP ↗ Badge — fixed width so separator aligns across rows */}
        <div className="flex shrink-0 w-[84px] items-center gap-2">
          <Badge tone="success" className="px-2 py-0.5 text-[11px] font-semibold tracking-wide">
            UP ↗
          </Badge>
          <span className="text-[10px] font-medium tracking-wider uppercase text-faint">Live</span>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {/* Ask — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline justify-end gap-1.5 pr-2">
              <span className="block text-[9px] font-medium tracking-wider uppercase text-faint">Ask</span>
              <span className="font-mono text-[13px] font-semibold tabular-nums text-fg">{cents(upAsk)}</span>
            </div>
          </div>
          {/* Separator — anchored at fixed position */}
          <div className="h-7 w-px bg-line shrink-0" />
          {/* Bid — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline justify-end gap-1.5 pr-2">
              <span className="block text-[9px] font-medium tracking-wider uppercase text-emerald-500/80">Bid</span>
              <span className="font-mono text-[19px] font-bold leading-none tabular-nums text-emerald-400">
                {cents(upBid)}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* CENTER METRIC: LIVE PAIR BID (UP bid + DN bid) */}
      <div
        className="flex w-16 shrink-0 -my-0.5 self-stretch items-center justify-center rounded-lg border border-line bg-surface-2"
        title="UP bid + DN bid"
      >
        <span
          className={`font-mono text-xl font-extrabold leading-none tabular-nums ${pairCostTone(pairBid, pairCostCap)}`}
          dangerouslySetInnerHTML={{ __html: cents3(pairBid) }}
        />
      </div>

      {/* DN SIDE (MIRRORED) */}
      <div className="relative flex min-w-0 flex-1 items-center justify-between overflow-hidden rounded-xl border border-line bg-surface-1 px-3 py-2 transition-all">
        <div className="pointer-events-none absolute -right-10 top-0 h-full w-24 bg-rose-500/5 blur-xl" />

        <div className="flex shrink-0 items-center gap-2">
          {/* Bid — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline gap-1.5 pl-2">
              <span className="font-mono text-[19px] font-bold leading-none tabular-nums text-rose-400">
                {cents(downBid)}
              </span>
              <span className="block text-[9px] font-medium tracking-wider uppercase text-rose-500/80">Bid</span>
            </div>
          </div>
          {/* Separator — anchored at fixed position */}
          <div className="h-7 w-px bg-line shrink-0" />
          {/* Ask — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline gap-1.5 pl-2">
              <span className="font-mono text-[13px] font-semibold tabular-nums text-fg">{cents(downAsk)}</span>
              <span className="block text-[9px] font-medium tracking-wider uppercase text-faint">Ask</span>
            </div>
          </div>
        </div>

        {/* Outer Right: DN ↘ Badge — fixed width so separator aligns across rows */}
        <div className="flex shrink-0 w-[84px] items-center gap-2 justify-end">
          <span className="text-[10px] font-medium tracking-wider uppercase text-faint">Live</span>
          <Badge tone="danger" className="px-2 py-0.5 text-[11px] font-semibold tracking-wide">
            DN ↘
          </Badge>
        </div>
      </div>
    </div>
  )
}
