import { Receipt } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'
import type { BotTrade } from '../lib/bot'
import { classifyFill, rebateFor, takerFeePerShare, useAccountTier, useIncludeRebates } from '../lib/rebates'
import { buildWindows, resolveWindowIndex, slotOfSlug, windowSlotOf } from '../lib/windows'

const money = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `${value < 0 ? '−' : ''}$${Math.abs(value).toFixed(2)}`

const cents = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `${Math.round(value * 100)}¢`

const windowClock = (slot: number) =>
  new Date(slot * 1000).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })

function formatPreciseTime(ts: number | string): { ago: string; clockMs: string } {
  const raw = typeof ts === 'string' ? Number(ts) || new Date(ts).getTime() : ts
  const ms = Number.isFinite(raw) ? (raw < 1e11 ? raw * 1000 : raw) : Date.now()
  const d = new Date(ms)

  const diffSec = Math.max(0, Math.round((Date.now() - ms) / 1000))
  const ago =
    diffSec < 60
      ? `${diffSec}s ago`
      : diffSec < 3600
        ? `${Math.floor(diffSec / 60)}m ago`
        : `${Math.floor(diffSec / 3600)}h ago`

  const hours = String(d.getHours()).padStart(2, '0')
  const mins = String(d.getMinutes()).padStart(2, '0')
  const secs = String(d.getSeconds()).padStart(2, '0')
  const millis = String(d.getMilliseconds()).padStart(3, '0')

  return {
    ago,
    clockMs: `${hours}:${mins}:${secs}.${millis}`,
  }
}

export interface OrdersAndFillsProps {
  items: BotTrade[]
  /** Running window first, then the next one once it has been revealed. */
  windowSlugs?: string[]
}

export function OrdersAndFillsTable({ items, windowSlugs = [] }: OrdersAndFillsProps) {
  const [tier] = useAccountTier()
  const [includeRebates] = useIncludeRebates()
  const [typeFilter, setTypeFilter] = useState<'all' | 'maker' | 'taker'>('all')
  const [sideFilter, setSideFilter] = useState<'all' | 'Up' | 'Down'>('all')
  // null = follow the running window; a slot pins the view to that window.
  const [pickedSlot, setPickedSlot] = useState<number | null>(null)

  const windows = useMemo(() => buildWindows(items, windowSlugs), [items, windowSlugs])
  const liveSlot = slotOfSlug(windowSlugs[0])
  const windowIndex = resolveWindowIndex(windows, liveSlot, pickedSlot)
  const activeWindow = windows[windowIndex]
  const activeSlot = activeWindow?.slot ?? null
  const isLiveView = activeWindow != null && activeWindow.slot === liveSlot

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      // A settlement is not an execution: this table lists orders and fills.
      // The window result (winner, payout) is already in the decision journal.
      if (item.kind === 'settle') return false

      // Rows belong to the window of the market they traded. The bot opens the
      // next window's straddle seconds before that window opens, so those fills
      // land in the previous window's clock — the slug keeps them with the
      // window the chart and the positions count them in.
      if (activeSlot != null && windowSlotOf(item) !== activeSlot) return false

      const detail = item.detail as Record<string, unknown> | undefined
      const role = classifyFill({ role: detail?.role, reason: item.reason, feeUsd: detail?.feeUsd })

      if (typeFilter === 'maker' && role !== 'maker') return false
      if (typeFilter === 'taker' && role !== 'taker') return false

      const side = item.side ?? (detail?.winner as string | undefined)
      if (sideFilter !== 'all' && side !== sideFilter) return false

      return true
    })
  }, [items, typeFilter, sideFilter, activeSlot])

  const stepWindow = (delta: number) => {
    const next = windows[windowIndex + delta]
    if (next) setPickedSlot(next.slot)
  }

  return (
    <Card className="mt-3 pt-0">
      <CardHeader className="flex flex-wrap items-center justify-between gap-3 border-b border-border pt-5 pb-4">
        <div className="flex items-center gap-2.5">
          <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
            <Receipt className="size-4" aria-hidden="true" />
          </span>
          <CardTitle className="font-heading text-[15px] font-semibold">Orders &amp; Fills</CardTitle>
          <Badge variant="secondary" className="font-mono tabular-nums">
            {filteredItems.length}
          </Badge>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Window Filter · running window by default, arrows step ±5m */}
          <div className="flex items-center gap-0.5 rounded-xl border border-border bg-muted/50 px-1.5 py-0.5 text-xs">
            <span aria-hidden className="pl-0.5 font-mono text-[10px] text-muted-foreground">
              −5
            </span>
            <button
              type="button"
              onClick={() => stepWindow(-1)}
              disabled={windowIndex <= 0}
              aria-label="Previous window"
              className="rounded px-1 font-semibold text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30"
            >
              «
            </button>
            <button
              type="button"
              onClick={() => setPickedSlot(null)}
              title={isLiveView ? 'Running window' : 'Back to the running window'}
              className="flex items-center gap-1.5 rounded-lg px-1.5 py-0.5 font-mono text-foreground tabular-nums transition-colors hover:bg-card"
            >
              {activeWindow ? windowClock(activeWindow.slot) : '—'}
              <span
                aria-hidden
                className={cn(
                  'size-1.5 rounded-full',
                  isLiveView ? 'animate-pulse bg-rose-500' : 'bg-muted-foreground/50',
                )}
              />
              <span className="sr-only">{isLiveView ? 'Live window' : 'Closed window, click for the live one'}</span>
            </button>
            <button
              type="button"
              onClick={() => stepWindow(1)}
              disabled={windowIndex < 0 || windowIndex >= windows.length - 1}
              aria-label="Next window"
              className="rounded px-1 font-semibold text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30"
            >
              »
            </button>
            <span aria-hidden className="pr-0.5 font-mono text-[10px] text-muted-foreground">
              +5
            </span>
          </div>

          {/* Side Filter */}
          <div className="flex rounded-xl border border-border bg-muted/50 p-0.5 text-xs">
            {(['all', 'Up', 'Down'] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSideFilter(s)}
                className={cn(
                  'rounded-lg px-2 py-0.5 font-medium transition-colors',
                  sideFilter === s
                    ? 'bg-card text-foreground shadow-2xs'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {s === 'all' ? 'All Sides' : s === 'Up' ? 'UP ↗' : 'DN ↘'}
              </button>
            ))}
          </div>

          {/* Type Filter */}
          <div className="flex rounded-xl border border-border bg-muted/50 p-0.5 text-xs">
            {(['all', 'maker', 'taker'] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTypeFilter(t)}
                className={cn(
                  'rounded-lg px-2 py-0.5 font-medium uppercase transition-colors',
                  typeFilter === t
                    ? 'bg-card text-foreground shadow-2xs'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>

      <CardContent className="px-3">
        {filteredItems.length === 0 ? (
          <Empty className="py-10">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Receipt />
              </EmptyMedia>
              <EmptyTitle>No matching executions</EmptyTitle>
              <EmptyDescription>Fills and order executions will appear here in real-time.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="[&_[data-slot=table-container]]:scrollbar-thin [&_[data-slot=table-container]]:max-h-[480px] [&_[data-slot=table-container]]:overflow-y-auto">
            <Table className="min-w-[780px] text-xs">
              <TableHeader className="sticky top-0 z-10 bg-card/95 backdrop-blur [&_th]:h-9 [&_th]:text-[11px] [&_th]:font-semibold [&_th]:tracking-wider [&_th]:text-muted-foreground [&_th]:uppercase">
                <TableRow className="hover:bg-transparent">
                  <TableHead className="px-3">Time (ms)</TableHead>
                  <TableHead className="px-3">Side</TableHead>
                  <TableHead className="px-3">Type</TableHead>
                  <TableHead className="px-3 text-right">Size</TableHead>
                  <TableHead className="px-3 text-right">Price</TableHead>
                  <TableHead className="px-3 text-right">Fee</TableHead>
                  <TableHead className="px-3 text-right">Total Cost</TableHead>
                  <TableHead className="px-3 text-right">Rebate</TableHead>
                  <TableHead className="px-3">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[...filteredItems].reverse().map((trade, index) => {
                  const { ago, clockMs } = formatPreciseTime(trade.ts)
                  const detail = trade.detail as Record<string, unknown> | undefined
                  const side = trade.side ?? (detail?.winner as string | undefined)
                  const cost =
                    trade.usd ?? (trade.shares != null && trade.price != null ? trade.shares * trade.price : null)

                  const fillRole = classifyFill({
                    role: detail?.role,
                    reason: trade.reason,
                    feeUsd: detail?.feeUsd,
                  })
                  const isMaker = fillRole === 'maker'
                  const orderType = fillRole.toUpperCase()

                  const isSettled = trade.kind === 'settle'

                  // The run file records the fee it charged, and a stored zero is a
                  // real value (no fee on that fill). Only fills with no recorded fee
                  // fall back to the 0.05 · p · (1 − p) formula.
                  const detailFee = typeof detail?.feeUsd === 'number' ? detail.feeUsd : null
                  const feeUsd = isSettled
                    ? null
                    : detailFee !== null
                      ? detailFee
                      : isMaker
                        ? 0
                        : trade.price != null && trade.shares != null
                          ? trade.shares * takerFeePerShare(trade.price)
                          : null
                  const rebateUsd =
                    !includeRebates || feeUsd == null
                      ? null
                      : rebateFor(trade.price, trade.shares, !!isMaker, tier.rate, feeUsd, tier.makerRate)
                  const tapeStatus = (detail?.tapeStatus as string | undefined) ?? undefined
                  // Attainable is the stronger verdict: it is the only check that
                  // knows the queue ahead and the sell side. Live it only ever
                  // turns true (more selling can still arrive); the close pass and
                  // the resolution audit write both verdicts.
                  const attainable = detail?.attainable as boolean | undefined
                  const statusLabel = !isMaker
                    ? 'Taker'
                    : attainable === true
                      ? 'Attainable'
                      : attainable === false
                        ? 'Phantom'
                        : isSettled
                          ? 'Settled'
                          : tapeStatus === 'verified'
                            ? 'Verified'
                            : tapeStatus === 'partial'
                              ? 'Partial'
                              : tapeStatus === 'unverified'
                                ? 'Unverified'
                                : tapeStatus === 'unverified-taker'
                                  ? 'Taker'
                                  : tapeStatus === 'pending'
                                    ? 'Pending'
                                    : 'Filled'
                  const statusColor = !isMaker
                    ? 'bg-muted-foreground/50'
                    : attainable === true
                      ? 'bg-emerald-500'
                      : attainable === false
                        ? 'bg-rose-500'
                        : isSettled
                          ? 'bg-primary'
                          : tapeStatus === 'verified'
                            ? 'bg-emerald-500'
                            : tapeStatus === 'partial'
                              ? 'bg-amber-500'
                              : tapeStatus === 'unverified'
                                ? 'bg-rose-500'
                                : tapeStatus === 'unverified-taker'
                                  ? 'bg-muted-foreground/50'
                                  : tapeStatus === 'pending'
                                    ? 'bg-amber-500'
                                    : 'bg-emerald-500'

                  return (
                    <TableRow key={`${trade.ts}-${index}`}>
                      {/* 1. Time with Milliseconds */}
                      <TableCell className="px-3 py-2.5">
                        <div className="flex flex-col">
                          <span className="font-medium text-foreground">{ago}</span>
                          <span className="font-mono text-[11px] tracking-tight text-muted-foreground tabular-nums">
                            {clockMs}
                          </span>
                        </div>
                      </TableCell>

                      {/* 2. Side */}
                      <TableCell className="px-3 py-2.5">
                        {side ? (
                          <Badge
                            variant="outline"
                            className={cn(
                              'px-2 font-mono text-[11px] font-semibold',
                              side === 'Up'
                                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                                : side === 'Down'
                                  ? 'border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-400'
                                  : 'text-muted-foreground',
                            )}
                          >
                            {side === 'Up' ? 'UP ↗' : 'DN ↘'}
                          </Badge>
                        ) : (
                          <span className="font-mono text-muted-foreground">—</span>
                        )}
                      </TableCell>

                      {/* 3. Type (Maker / Taker) */}
                      <TableCell className="px-3 py-2.5">
                        <span
                          className={cn(
                            'inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-[10.5px] font-semibold tracking-wider uppercase',
                            orderType === 'MAKER'
                              ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                              : 'border-primary/25 bg-primary/10 text-primary',
                          )}
                        >
                          {orderType}
                        </span>
                      </TableCell>

                      {/* 4. Size */}
                      <TableCell className="px-3 py-2.5 text-right font-mono text-foreground tabular-nums">
                        {trade.shares != null ? (
                          <>
                            <span>
                              {trade.shares.toLocaleString(undefined, {
                                minimumFractionDigits: trade.shares % 1 !== 0 ? 1 : 0,
                                maximumFractionDigits: 1,
                              })}
                            </span>
                            <span className="ml-1 text-[10.5px] text-muted-foreground">sh</span>
                          </>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>

                      {/* 5. Price */}
                      <TableCell className="px-3 py-2.5 text-right font-mono font-medium text-foreground tabular-nums">
                        {trade.price != null ? (
                          cents(trade.price)
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>

                      {/* 6. Fee */}
                      <TableCell className="px-3 py-2.5 text-right font-mono tabular-nums">
                        {feeUsd == null ? (
                          <span className="text-muted-foreground">—</span>
                        ) : feeUsd > 0 ? (
                          <span className="font-medium text-rose-600 dark:text-rose-400">−{money(feeUsd)}</span>
                        ) : (
                          <span className="text-muted-foreground">$0.00</span>
                        )}
                      </TableCell>

                      {/* 7. Total Cost - the bot fill usd, which already carries the fee */}
                      <TableCell className="px-3 py-2.5 text-right font-mono font-semibold text-foreground tabular-nums">
                        {cost != null ? (
                          money(cost)
                        ) : (
                          <span className="font-normal text-muted-foreground">—</span>
                        )}
                      </TableCell>

                      {/* 8. Rebate */}
                      <TableCell className="px-3 py-2.5 text-right font-mono tabular-nums">
                        {rebateUsd == null ? (
                          <span className="text-muted-foreground">—</span>
                        ) : rebateUsd > 0 ? (
                          <span className="font-medium text-emerald-600 dark:text-emerald-400">+{money(rebateUsd)}</span>
                        ) : (
                          <span className="text-muted-foreground">$0.00</span>
                        )}
                      </TableCell>

                      {/* 9. Status */}
                      <TableCell className="px-3 py-2.5">
                        <span className="inline-flex items-center gap-1.5 font-mono text-[11.5px] font-medium text-foreground">
                          <span className={cn('size-1.5 rounded-full', statusColor)} />
                          {statusLabel}
                        </span>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
