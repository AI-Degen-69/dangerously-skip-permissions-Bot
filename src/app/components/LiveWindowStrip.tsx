import { Badge } from '@/components/ui/badge'
import type { MarketView, WsStatus } from '../lib/bot'
import { pairCostTone } from '../lib/format'

const cents = (value: number | null | undefined) =>
  value === null || value === undefined ? '-' : `${Math.round(value * 100)}¢`

/** Mills-precision cents: the tenth-of-a-cent digit renders small and subscripted. */
const cents3 = (value: number | null | undefined) => {
  if (value === null || value === undefined) return <>-</>
  const c = Math.round(value * 1000)
  return (
    <>
      {Math.floor(c / 10)}
      <span className="align-sub text-[10px] leading-none opacity-70">{c % 10}</span>¢
    </>
  )
}

export interface LiveWindowStripProps {
  markets: MarketView[]
  ws?: WsStatus
  /** Strategy's pair-cost cap (`entry.maxPairCost`); colors the center pill. */
  pairCostCap?: number
}

export function LiveWindowStrip({ markets, ws, pairCostCap = 0.985 }: LiveWindowStripProps) {
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
      <div className="relative flex min-w-0 flex-1 items-center justify-between overflow-hidden rounded-2xl border border-border bg-card/90 px-3 py-2 shadow-2xs transition-all">
        <div className="pointer-events-none absolute -left-10 top-0 h-full w-24 bg-emerald-500/5 blur-xl" />

        {/* Outer Left: UP ↗ Badge — fixed width so separator aligns across rows */}
        <div className="flex w-[84px] shrink-0 items-center gap-1.5">
          <Badge
            variant="outline"
            className="border-emerald-500/30 bg-emerald-500/10 px-2 font-mono text-[11px] font-semibold tracking-wide text-emerald-600 dark:text-emerald-400"
          >
            UP ↗
          </Badge>
          <span className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">Live</span>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {/* Ask — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline justify-end gap-1.5 pr-2">
              <span className="block text-[9px] font-medium tracking-wider text-muted-foreground uppercase">Ask</span>
              <span className="font-mono text-[13px] font-semibold text-foreground tabular-nums">{cents(upAsk)}</span>
            </div>
          </div>
          {/* Separator — anchored at fixed position */}
          <div className="h-7 w-px shrink-0 bg-border" />
          {/* Bid — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline justify-end gap-1.5 pr-2">
              <span className="block text-[9px] font-medium tracking-wider text-emerald-600/80 uppercase dark:text-emerald-400/80">
                Bid
              </span>
              <span className="font-mono text-[19px] leading-none font-bold text-emerald-600 tabular-nums dark:text-emerald-400">
                {cents(upBid)}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* CENTER METRIC: LIVE PAIR BID (UP bid + DN bid) */}
      <div
        className="-my-0.5 flex w-16 shrink-0 items-center justify-center self-stretch rounded-xl border border-border bg-muted/60"
        title="UP bid + DN bid"
      >
        <span
          className={`font-mono text-xl leading-none font-extrabold tabular-nums ${pairCostTone(pairBid, pairCostCap)}`}
        >
          {cents3(pairBid)}
        </span>
      </div>

      {/* DN SIDE (MIRRORED) */}
      <div className="relative flex min-w-0 flex-1 items-center justify-between overflow-hidden rounded-2xl border border-border bg-card/90 px-3 py-2 shadow-2xs transition-all">
        <div className="pointer-events-none absolute -right-10 top-0 h-full w-24 bg-rose-500/5 blur-xl" />

        <div className="flex shrink-0 items-center gap-2">
          {/* Bid — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline gap-1.5 pl-2">
              <span className="font-mono text-[19px] leading-none font-bold text-rose-600 tabular-nums dark:text-rose-400">
                {cents(downBid)}
              </span>
              <span className="block text-[9px] font-medium tracking-wider text-rose-600/80 uppercase dark:text-rose-400/80">
                Bid
              </span>
            </div>
          </div>
          {/* Separator — anchored at fixed position */}
          <div className="h-7 w-px shrink-0 bg-border" />
          {/* Ask — fixed width column */}
          <div className={col}>
            <div className="flex items-baseline gap-1.5 pl-2">
              <span className="font-mono text-[13px] font-semibold text-foreground tabular-nums">
                {cents(downAsk)}
              </span>
              <span className="block text-[9px] font-medium tracking-wider text-muted-foreground uppercase">Ask</span>
            </div>
          </div>
        </div>

        {/* Outer Right: DN ↘ Badge — fixed width so separator aligns across rows */}
        <div className="flex w-[84px] shrink-0 items-center justify-end gap-1.5">
          <span className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">Live</span>
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
