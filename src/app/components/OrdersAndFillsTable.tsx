import { useMemo, useState } from 'react'
import { Badge, Card, EmptyState } from './ui'
import { cx } from '../lib/cx'
import type { BotTrade } from '../lib/bot'
import { classifyFill, rebateFor, takerFeePerShare, useAccountTier } from '../lib/rebates'
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
      // Rows belong to the window their timestamp falls in. Matching the market
      // slug alone leaked fills the bot placed in its pre-open pipeline (a few
      // seconds before the next window) into that next window's list.
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
    <Card className="mt-3 p-5">
      {/* Header Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-[14px] font-semibold">Orders & Fills</h2>
            <Badge tone="neutral">{filteredItems.length}</Badge>
          </div>
          <p className="text-[12px] text-muted">
            Execution logs with millisecond timestamps, Maker/Taker routing, fees and rebates at {tier.name} (
            {Math.round(tier.rate * 100)}%).
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Window Filter · running window by default, arrows step ±5m */}
          <div className="flex items-center gap-0.5 rounded-lg border border-line bg-surface-2 px-1 py-0.5 text-[11.5px]">
            <span aria-hidden className="pl-0.5 font-mono text-[10px] text-faint">
              −5
            </span>
            <button
              type="button"
              onClick={() => stepWindow(-1)}
              disabled={windowIndex <= 0}
              aria-label="Previous window"
              className="rounded px-1 font-semibold text-muted transition-colors hover:text-fg disabled:opacity-30"
            >
              «
            </button>
            <button
              type="button"
              onClick={() => setPickedSlot(null)}
              title={isLiveView ? 'Running window' : 'Back to the running window'}
              className="flex items-center gap-1.5 rounded px-1.5 py-0.5 font-mono tabular-nums text-fg transition-colors hover:bg-surface-1"
            >
              {activeWindow ? windowClock(activeWindow.slot) : '—'}
              <span aria-hidden className={cx('size-1.5 rounded-full', isLiveView ? 'animate-pulse bg-danger' : 'bg-line-strong')} />
              <span className="sr-only">{isLiveView ? 'Live window' : 'Closed window, click for the live one'}</span>
            </button>
            <button
              type="button"
              onClick={() => stepWindow(1)}
              disabled={windowIndex < 0 || windowIndex >= windows.length - 1}
              aria-label="Next window"
              className="rounded px-1 font-semibold text-muted transition-colors hover:text-fg disabled:opacity-30"
            >
              »
            </button>
            <span aria-hidden className="pr-0.5 font-mono text-[10px] text-faint">
              +5
            </span>
          </div>

          {/* Side Filter */}
          <div className="flex rounded-lg border border-line bg-surface-2 p-0.5 text-[11.5px]">
            {(['all', 'Up', 'Down'] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSideFilter(s)}
                className={cx(
                  'rounded-md px-2 py-0.5 font-medium transition-colors',
                  sideFilter === s ? 'bg-surface-1 text-fg shadow-xs' : 'text-muted hover:text-fg',
                )}
              >
                {s === 'all' ? 'All Sides' : s === 'Up' ? 'UP ↗' : 'DN ↘'}
              </button>
            ))}
          </div>

          {/* Type Filter */}
          <div className="flex rounded-lg border border-line bg-surface-2 p-0.5 text-[11.5px]">
            {(['all', 'maker', 'taker'] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTypeFilter(t)}
                className={cx(
                  'rounded-md px-2 py-0.5 font-medium transition-colors uppercase',
                  typeFilter === t ? 'bg-surface-1 text-fg shadow-xs' : 'text-muted hover:text-fg',
                )}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>

      {filteredItems.length === 0 ? (
        <EmptyState
          title="No matching executions"
          description="Fills and order executions will appear here in real-time."
        />
      ) : (
        <div className="scrollbar-thin mt-3 max-h-[480px] overflow-x-auto overflow-y-auto">
          <table className="w-full min-w-[780px] text-left text-[12.5px]">
            <thead className="sticky top-0 z-10 border-b border-line bg-surface-1/95 text-[11px] font-semibold uppercase tracking-wider text-faint backdrop-blur">
              <tr>
                <th className="py-2.5 px-3 font-medium">Time (ms)</th>
                <th className="py-2.5 px-3 font-medium">Side</th>
                <th className="py-2.5 px-3 font-medium">Type</th>
                <th className="py-2.5 px-3 text-right font-medium">Size</th>
                <th className="py-2.5 px-3 text-right font-medium">Price</th>
                <th className="py-2.5 px-3 text-right font-medium">Total Cost</th>
                <th className="py-2.5 px-3 text-right font-medium">Fee</th>
                <th className="py-2.5 px-3 text-right font-medium">Rebate</th>
                <th className="py-2.5 px-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
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
                // fall back to the 0.07 · p · (1 − p) formula.
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
                  feeUsd == null ? null : rebateFor(trade.price, trade.shares, !!isMaker, tier.rate, feeUsd)
                const tapeStatus = (detail?.tapeStatus as string | undefined) ?? undefined
                const statusLabel = isSettled
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
                const statusColor = isSettled
                  ? 'bg-accent'
                  : tapeStatus === 'verified'
                  ? 'bg-success'
                  : tapeStatus === 'partial'
                  ? 'bg-warning'
                  : tapeStatus === 'unverified'
                  ? 'bg-danger'
                  : tapeStatus === 'unverified-taker'
                  ? 'bg-faint'
                  : tapeStatus === 'pending'
                  ? 'bg-warning'
                  : 'bg-success'

                return (
                  <tr key={`${trade.ts}-${index}`} className="transition-colors hover:bg-surface-2/60">
                    {/* 1. Time with Milliseconds */}
                    <td className="py-2.5 px-3">
                      <div className="flex flex-col">
                        <span className="text-[12.5px] font-medium text-fg">{ago}</span>
                        <span className="font-mono text-[11px] text-faint tabular-nums tracking-tight">
                          {clockMs}
                        </span>
                      </div>
                    </td>

                    {/* 2. Side */}
                    <td className="py-2.5 px-3">
                      {side ? (
                        <Badge
                          tone={side === 'Up' ? 'success' : side === 'Down' ? 'danger' : 'neutral'}
                          className="px-2 py-0.5 text-[11px] font-semibold"
                        >
                          {side === 'Up' ? 'UP ↗' : 'DN ↘'}
                        </Badge>
                      ) : (
                        <span className="font-mono text-faint">—</span>
                      )}
                    </td>

                    {/* 3. Type (Maker / Taker) */}
                    <td className="py-2.5 px-3">
                      <span
                        className={cx(
                          'inline-flex items-center rounded-[6px] px-2 py-0.5 font-mono text-[10.5px] font-semibold uppercase tracking-wider',
                          orderType === 'MAKER'
                            ? 'bg-success-soft text-success border border-success/20'
                            : 'bg-accent-soft text-accent border border-accent/20',
                        )}
                      >
                        {orderType}
                      </span>
                    </td>

                    {/* 4. Size */}
                    <td className="py-2.5 px-3 text-right font-mono text-[12.5px] tabular-nums text-fg">
                      {trade.shares != null ? (
                        <>
                          <span>
                            {trade.shares.toLocaleString(undefined, {
                              minimumFractionDigits: trade.shares % 1 !== 0 ? 1 : 0,
                              maximumFractionDigits: 1,
                            })}
                          </span>
                          <span className="ml-1 text-[10.5px] text-faint">sh</span>
                        </>
                      ) : (
                        <span className="text-faint">—</span>
                      )}
                    </td>

                    {/* 5. Price */}
                    <td className="py-2.5 px-3 text-right font-mono text-[12.5px] font-medium tabular-nums text-fg">
                      {trade.price != null ? cents(trade.price) : <span className="text-faint">—</span>}
                    </td>

                    {/* 6. Total Cost */}
                    <td className="py-2.5 px-3 text-right font-mono text-[12.5px] font-semibold tabular-nums text-fg">
                      {cost != null ? money(cost) : <span className="font-normal text-faint">—</span>}
                    </td>

                    {/* 7. Fee */}
                    <td className="py-2.5 px-3 text-right font-mono text-[12.5px] tabular-nums">
                      {feeUsd == null ? (
                        <span className="text-faint">—</span>
                      ) : feeUsd > 0 ? (
                        <span className="font-medium text-danger">−{money(feeUsd)}</span>
                      ) : (
                        <span className="text-faint">$0.00</span>
                      )}
                    </td>

                    {/* 8. Rebate */}
                    <td className="py-2.5 px-3 text-right font-mono text-[12.5px] tabular-nums">
                      {rebateUsd == null ? (
                        <span className="text-faint">—</span>
                      ) : rebateUsd > 0 ? (
                        <span className="font-medium text-success">+{money(rebateUsd)}</span>
                      ) : (
                        <span className="text-faint">$0.00</span>
                      )}
                    </td>

                    {/* 9. Status */}
                    <td className="py-2.5 px-3">
                      <span className="inline-flex items-center gap-1.5 font-mono text-[11.5px] font-medium text-fg">
                        <span
                          className={cx(
                            'size-1.5 rounded-full',
                            statusColor,
                          )}
                        />
                        {statusLabel}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
