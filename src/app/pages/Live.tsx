import { useMemo, useState } from 'react'
import { Activity, Radio } from 'lucide-react'
import { Link } from 'react-router'

import { PolymarketLiveChart } from '../components/PolymarketEmbed'
import { OrdersAndFillsTable } from '../components/OrdersAndFillsTable'
import { eventMetrics, KIND_TONE, reasonLabel as label } from '../lib/labels'
import { Badge, Card, EmptyState, PageHeader, Skeleton } from '../components/ui'
import {
  BOT_ORIGIN,
  useBotControl,
  useBotEvents,
  useBotSnapshot,
  useBotTrades,
  useBotWsTicks,
  useStrategySetups,
  mergeStrategySetups,
  type WsStatus,
  type StrategySetup,
  type WsTick,
  type BotEvent,
  type BotSnapshot,
  type OpenOrderView,
} from '../lib/bot'
import { STRATEGY_PRESETS } from '../botDefaults'
import { cx } from '../lib/cx'
import { relativeTime } from '../lib/format'

const cents = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `${Math.round(value * 100)}¢`
const clock = (ts: number | string) =>
  new Date(ts).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })

function windowLabel(slug: string): string {
  const parts = slug.split('-')
  const epoch = Number(parts[parts.length - 1])
  const interval = parts[parts.length - 2]
  return Number.isFinite(epoch) ? `${interval} ${clock(epoch * 1000)}` : slug
}

function MetricChip({ text, limit }: { text: string; limit?: string }) {
  return (
    <span className="flex items-baseline gap-1 rounded-[7px] bg-surface-2 px-1.5 py-0.5 tabular-nums">
      <span className="text-[11px] font-medium text-fg">{text}</span>
      {limit && <span className="text-[10.5px] text-faint">{limit}</span>}
    </span>
  )
}

export function Live() {
  const snapshot = useBotSnapshot()
  const events = useBotEvents()
  const trades = useBotTrades()
  const control = useBotControl()
  const wsTicks = useBotWsTicks()
  const setupsQuery = useStrategySetups()

  const isViewOnly = control.data?.isViewOnly ?? false
  const data = snapshot.data?.snapshot ?? null
  const ws = wsTicks.data?.status ?? data?.ws
  const ticks = wsTicks.data?.ticks ?? data?.recentTicks ?? []
  const online = Boolean(snapshot.data?.online && data && !isViewOnly)
  const stopped = data?.killSwitch ?? false
  const running = (control.data?.running ?? false) && !isViewOnly
  const [eventFilter, setEventFilter] = useState<'all' | 'entry' | 'snipe' | 'hold' | 'refuse' | 'done_settle'>('all')
  const rawEvents = events.data?.items ?? []
  const filteredEvents = useMemo(() => {
    if (eventFilter === 'all') return rawEvents
    if (eventFilter === 'done_settle') {
      return rawEvents.filter((e) => ['done', 'settle', 'redeem', 'risk', 'error'].includes(e.kind))
    }
    if (eventFilter === 'refuse') {
      return rawEvents.filter((e) => e.kind === 'refuse' || e.kind === 'skip')
    }
    return rawEvents.filter((e) => e.kind === eventFilter)
  }, [rawEvents, eventFilter])

  const counts = useMemo(
    () => ({
      all: rawEvents.length,
      entry: rawEvents.filter((e) => e.kind === 'entry').length,
      snipe: rawEvents.filter((e) => e.kind === 'snipe').length,
      hold: rawEvents.filter((e) => e.kind === 'hold').length,
      refuse: rawEvents.filter((e) => e.kind === 'refuse' || e.kind === 'skip').length,
      done_settle: rawEvents.filter((e) => ['done', 'settle', 'redeem', 'risk', 'error'].includes(e.kind)).length,
    }),
    [rawEvents],
  )

  const activeStrategyId = data?.strategy?.id ?? control.data?.strategy?.id ?? setupsQuery.data?.activeSetupId
  const setups = mergeStrategySetups(setupsQuery.data?.setups, STRATEGY_PRESETS as unknown as Record<string, StrategySetup>)
  const currentSetup = setups.find((s) => s.id === activeStrategyId) ?? setups[0]

  const strategySymbol = data?.strategy?.symbol ?? control.data?.strategy?.symbol ?? currentSetup?.symbol ?? '—'
  const strategyName = data?.strategy?.name ?? control.data?.strategy?.name ?? currentSetup?.name ?? '—'
  const strategySignature =
    data?.strategy?.signature ??
    control.data?.strategy?.signature ??
    currentSetup?.signature ??
    currentSetup?.description

  return (
    <div className="mx-auto max-w-[1200px] p-5 sm:p-8">
      <PageHeader
        title={`Live bot · ${strategySymbol}`}
        subtitle={strategySignature}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <span title={strategyName}>
              <Badge tone="accent" className="font-mono font-semibold">
                {strategySymbol} · Recovery Engine
              </Badge>
            </span>
            <Badge tone={snapshot.isError && !snapshot.data ? 'neutral' : running ? 'success' : 'neutral'} dot>
              {snapshot.isError && !snapshot.data ? 'No signal' : running ? 'Streaming' : 'Stopped'}
            </Badge>
            {ws && (
              <Badge
                tone={
                  ws.state === 'connected'
                    ? 'success'
                    : ws.state === 'stale'
                    ? 'warning'
                    : ws.state === 'fallback_active'
                    ? 'danger'
                    : 'neutral'
                }
                dot
              >
                {ws.state === 'connected'
                  ? `WSS Live (${ws.age_ms != null ? `${ws.age_ms}ms` : '<40ms'})`
                  : ws.state === 'stale'
                  ? `WSS Stale (${((ws.age_ms ?? 3000) / 1000).toFixed(1)}s)`
                  : ws.state === 'fallback_active'
                  ? 'REST Fallback'
                  : 'WSS Disconnected'}
              </Badge>
            )}
            <Badge tone={data?.mode === 'live' ? 'danger' : 'warning'}>{data?.mode === 'live' ? 'LIVE money' : 'Paper'}</Badge>
            {running && stopped && <Badge tone="warning">Entries paused</Badge>}
            {isViewOnly && (
              <Badge tone="warning" dot>
                View only
              </Badge>
            )}
            <Link to="/" className="text-[12.5px] font-medium text-muted hover:text-fg">
              Controls on Dashboard →
            </Link>
          </div>
        }
      />

      {snapshot.isLoading || control.isLoading ? (
        <Skeleton className="mt-6 h-[260px] rounded-card" />
      ) : snapshot.isError && !snapshot.data ? (
        <Card className="mt-6 p-6">
          <div className="flex items-start gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-card bg-warning-soft text-warning">
              <Activity className="size-5" />
            </span>
            <div>
              <h2 className="text-[15px] font-semibold">Bot API not reachable</h2>
              <p className="mt-1 text-[13.5px] text-muted">
                The request to {BOT_ORIGIN} failed. Start the API with <code>python bot/api.py</code>; this page fills in on its own once it answers.
              </p>
            </div>
          </div>
        </Card>
      ) : !running ? (
        <Card className="mt-6 p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              <span className="grid size-10 shrink-0 place-items-center rounded-card bg-warning-soft text-warning">
                <Activity className="size-5" />
              </span>
              <div>
                <h2 className="text-[15px] font-semibold">The loop is stopped</h2>
                <p className="mt-1 max-w-xl text-[13.5px] text-muted">
                  No windows are being traded, so there is nothing streaming to show. Start it from the Dashboard to resume one 5-minute
                  straddle window at a time.
                  {snapshot.data?.ageMs != null && (
                    <> Last heartbeat {relativeTime(Date.now() - snapshot.data.ageMs)}.</>
                  )}
                </p>
              </div>
            </div>
            <Link to="/" className="text-[12.5px] font-medium text-muted hover:text-fg">
              Start it from the Dashboard →
            </Link>
          </div>
        </Card>
      ) : !online ? (
        <Card className="mt-6 p-6">
          <div className="flex items-start gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-card bg-warning-soft text-warning">
              <Activity className="size-5" />
            </span>
            <div>
              <h2 className="text-[15px] font-semibold">Waiting for the first window</h2>
              <p className="mt-1 text-[13.5px] text-muted">
                The loop is running — this page fills in as soon as it opens the next window.
              </p>
            </div>
          </div>
        </Card>
      ) : (
        data && (
          <>
            <StraddleDeskStrip data={data} />

            <PolymarketLiveChart markets={data.markets} positions={data.positions} ws={ws} trades={trades.data?.items ?? []} />

            <RestingOrdersStrip orders={data.openOrders ?? []} />

            <OrdersAndFillsTable items={trades.data?.items ?? []} windowSlugs={data.markets.map((market) => market.slug)} />

            <div className="mt-3 grid gap-3 lg:grid-cols-3">
              <Card className="p-5 lg:col-span-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-[14px] font-semibold">Decision journal</h2>
                    <p className="text-[12.5px] text-muted">Every gate it passed or failed, newest first.</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {(
                      [
                        { id: 'all', label: 'All', count: counts.all },
                        { id: 'entry', label: 'Entries', count: counts.entry },
                        { id: 'snipe', label: 'Snipes', count: counts.snipe },
                        { id: 'hold', label: 'Holds', count: counts.hold },
                        { id: 'refuse', label: 'Refusals', count: counts.refuse },
                        { id: 'done_settle', label: 'Done & Settle', count: counts.done_settle },
                      ] as const
                    ).map((tab) => (
                      <button
                        key={tab.id}
                        type="button"
                        onClick={() => setEventFilter(tab.id)}
                        className={cx(
                          'rounded-md px-2 py-0.5 text-[11.5px] font-medium transition-colors',
                          eventFilter === tab.id
                            ? 'bg-surface-2 text-fg shadow-xs ring-1 ring-line'
                            : 'text-muted hover:bg-surface-2/50 hover:text-fg',
                        )}
                      >
                        {tab.label}
                        {tab.count > 0 && <span className="ml-1 text-[10px] opacity-70">({tab.count})</span>}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="scrollbar-thin mt-2 max-h-[440px] overflow-y-auto">
                  {filteredEvents.length > 0 ? (
                    <ul className="divide-y divide-line">
                      {[...filteredEvents].reverse().map((event, index) => (
                        <EventRow key={`${event.ts}-${index}`} event={event} />
                      ))}
                    </ul>
                  ) : events.isError ? (
                    <EmptyState
                      icon={<Activity />}
                      title="Bot API not reachable"
                      description={`The request failed. Start the API with \`python bot/api.py\`; this list refills as soon as the API at ${BOT_ORIGIN} answers.`}
                    />
                  ) : (
                    <EmptyState
                      icon={<Activity />}
                      title={eventFilter === 'all' ? 'No decisions logged yet' : `No ${eventFilter} events`}
                      description={
                        eventFilter === 'all'
                          ? 'Entries, clip fills, holds and skips appear here as the bot ticks.'
                          : 'Try selecting "All" to view all journal decisions.'
                      }
                    />
                  )}
                </div>
              </Card>
            </div>

            <WssStreamTape ws={ws} ticks={ticks} />
          </>
        )
      )}
    </div>
  )
}

function EventTitle({ event }: { event: BotEvent }) {
  const detail = event.detail
  const shares = detail?.shares != null ? `${Math.round(Number(detail.shares))}` : '30'
  const side = event.side ?? ''
  const price = typeof detail?.price === 'number' ? detail.price.toFixed(2) : null

  // 1. First touch: Decided Lean (<calculated lean value>): <shares amount> <SIDE> @ <0.XX>\share
  if (event.reason === 'straddle-open') {
    const rawVal = typeof detail?.rawLean === 'number' ? detail.rawLean : detail?.lean
    const leanNum = typeof rawVal === 'number' ? rawVal : typeof detail?.lean === 'number' ? detail.lean : 0
    const leanStr = leanNum > 0 ? `+${leanNum.toFixed(2)}` : leanNum.toFixed(2)
    const pxStr = price ? `@ ${price}\\share` : ''
    return (
      <span className="truncate text-[13px] font-medium text-fg">
        Decided Lean ({leanStr}): {shares} {side} {pxStr}
      </span>
    )
  }

  // 2. Second touch: Locked Hedge: <shares amount> <SIDE> @ <0.XX>\share  |  Pair Cost: <X.XX>
  // Above 1$ is red, <= 1$ is green
  if (event.reason === 'hedge-leg') {
    const pxStr = price ? `@ ${price}\\share` : ''
    const pairCost = typeof detail?.pairCost === 'number' ? detail.pairCost : null
    return (
      <span className="truncate text-[13px] font-medium text-fg">
        Locked Hedge: {shares} {side} {pxStr}
        {pairCost !== null && (
          <>
            {'  |  Pair Cost: '}
            <span
              className={cx(
                'font-semibold tabular-nums',
                pairCost > 1.0 ? 'text-danger' : 'text-success',
              )}
            >
              {pairCost.toFixed(2)}
            </span>
          </>
        )}
      </span>
    )
  }

  return <span className="truncate text-[13px]">{label(event.reason, event.detail)}</span>
}

function EventRow({ event }: { event: BotEvent }) {
  const metrics = eventMetrics(event.reason, event.detail)
  const displayKind = event.kind === 'skip' ? 'refuse' : event.kind

  return (
    <li className="flex items-start gap-3 py-2.5">
      <span className="mt-0.5 w-[58px] shrink-0 text-[11.5px] tabular-nums text-faint">{clock(event.ts)}</span>
      <Badge tone={KIND_TONE[displayKind] ?? 'neutral'} className="shrink-0 capitalize">
        {displayKind}
      </Badge>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px]">
          <EventTitle event={event} />
        </p>
        <p className="truncate text-[11.5px] text-faint">
          {event.slug ? windowLabel(event.slug) : 'bot'}
          {event.side ? (
            <>
              {' · '}
              <span className={event.side === 'Up' ? 'font-medium text-success' : 'font-medium text-danger'}>
                {event.side}
              </span>
            </>
          ) : ''}
        </p>
      </div>
      {metrics.length > 0 && (
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
          {metrics.map((metric) => (
            <MetricChip key={metric.text} text={metric.text} limit={metric.limit} />
          ))}
        </div>
      )}
    </li>
  )
}

function RestingOrdersStrip({ orders }: { orders: OpenOrderView[] }) {
  if (orders.length === 0) return null
  return (
    <Card className="mt-3 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-[14px] font-semibold">Resting orders</h2>
        <p className="text-[12px] text-muted">Not fills yet — each one needs a seller to hit it.</p>
      </div>
      <ul className="mt-1 divide-y divide-line">
        {orders.map((order) => (
          <li key={order.side} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2 text-[12.5px]">
            <Badge tone={order.side === 'Up' ? 'success' : 'danger'}>{order.side}</Badge>
            <span className="font-mono tabular-nums">
              {order.shares.toFixed(1)} sh @ {cents(order.price)}
            </span>
            <span className="text-muted">
              {order.queueAhead > 0 ? `${order.queueAhead.toFixed(0)} sh ahead` : 'front of queue'}
            </span>
            <span className="text-muted">resting {Math.max(0, Math.round((Date.now() - order.placedAtMs) / 1000))}s</span>
            <span className="ml-auto text-faint">
              M{order.minute} · {order.subReason}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function StraddleDeskStrip({ data }: { data: BotSnapshot }) {
  const activeMarket = data.markets[0]
  const positions = data.positions
  const upPos = positions.find((p) => p.side === 'Up')
  const downPos = positions.find((p) => p.side === 'Down')

  const upShares = upPos?.shares ?? 0
  const downShares = downPos?.shares ?? 0
  const upAvg = upPos?.entryPrice ?? null
  const downAvg = downPos?.entryPrice ?? null
  const isHedged = upShares > 0 && downShares > 0
  const hasHoldings = upShares > 0 || downShares > 0

  const pairedShares = Math.min(upShares, downShares)
  const unpairedShares = Math.abs(Math.round(upShares) - Math.round(downShares))
  const leadingSide = upShares > downShares ? 'Up' : downShares > upShares ? 'Down' : null

  let pairCost: number | null = null
  let isIndicative = false
  if (isHedged && upAvg != null && downAvg != null) {
    pairCost = upAvg + downAvg
  } else if (activeMarket?.quotes.Up.ask != null && activeMarket?.quotes.Down.ask != null) {
    pairCost = activeMarket.quotes.Up.ask + activeMarket.quotes.Down.ask
    isIndicative = true
  }

  const totalCost = (upPos?.costUsd ?? 0) + (downPos?.costUsd ?? 0)
  const effectiveCost = pairedShares > 0 ? totalCost / pairedShares : null
  const payIfUp = upShares * 1.0 - totalCost
  const payIfDown = downShares * 1.0 - totalCost
  const minFloor = hasHoldings ? Math.min(payIfUp, payIfDown) : 0
  const maxPayoff = hasHoldings ? Math.max(payIfUp, payIfDown) : 0
  const favoredSide = payIfUp >= payIfDown ? 'Up' : 'Down'

  return (
    <Card className="mt-3 p-4">
      <div className="grid grid-cols-2 gap-4 divide-y sm:divide-y-0 sm:divide-x divide-line lg:grid-cols-2">
        {/* Metric 1: Combined Pair Cost */}
        <div className="pt-2 sm:pt-0 sm:px-3 first:pl-0">
          <p className="text-[11px] font-medium uppercase tracking-wide text-faint">Combined Pair Cost</p>
          <div className="mt-1 flex items-baseline gap-2">
            <span
              className={cx(
                'text-[22px] font-semibold tracking-[-0.02em] tabular-nums',
                pairCost == null
                  ? 'text-faint'
                  : pairCost <= 1.0
                  ? 'text-success'
                  : 'text-danger',
              )}
            >
              {pairCost != null ? `${(pairCost * 100).toFixed(1)}¢` : '—'}
            </span>
            {pairCost != null && (
              <span className="text-[11.5px] text-muted">
                {isIndicative ? '/ book' : pairedShares > 0 ? `(${Math.round(pairedShares)} paired)` : '/ pair'}
              </span>
            )}
          </div>
          <p className="mt-0.5 text-[11.5px] text-muted">
            {pairCost == null ? (
              'Awaiting first fill'
            ) : unpairedShares === 0 && pairCost <= 1.0 ? (
              <span className="font-medium text-success">
                +{((1.0 - pairCost) * 100).toFixed(1)}¢ margin · 100% paired
              </span>
            ) : effectiveCost != null && effectiveCost > 1.0 ? (
              <span className="font-medium text-warning" title={`Total spent $${totalCost.toFixed(2)} across ${Math.round(pairedShares)} paired units`}>
                Eff: ${(effectiveCost).toFixed(2)}/guaranteed $1 ({unpairedShares} {leadingSide} unhedged)
              </span>
            ) : pairCost <= 1.0 ? (
              <span className="font-medium text-success">
                +{((1.0 - pairCost) * 100).toFixed(1)}¢ margin{isIndicative ? ' (book)' : ''}
              </span>
            ) : (
              <span className="font-medium text-danger">
                −{((pairCost - 1.0) * 100).toFixed(1)}¢ underwater{isIndicative ? ' (book)' : ''}
              </span>
            )}
          </p>
        </div>

        {/* Metric 2: Guaranteed Settlement Floor */}
        <div className="pt-2 sm:pt-0 sm:px-3 last:pr-0">
          <p className="text-[11px] font-medium uppercase tracking-wide text-faint">Settlement Payoff Floor</p>
          <div className="mt-1 flex items-baseline gap-2">
            <span
              className={cx(
                'text-[22px] font-semibold tracking-[-0.02em] tabular-nums',
                !hasHoldings ? 'text-faint' : minFloor >= 0 ? 'text-success' : 'text-danger',
              )}
            >
              {hasHoldings ? `${minFloor >= 0 ? '+' : '−'}$${Math.abs(minFloor).toFixed(2)}` : '—'}
            </span>
            {hasHoldings && (
              <span className="text-[11px] text-faint">
                {minFloor >= 0 ? 'locked floor' : 'min floor'}
              </span>
            )}
          </div>
          <p className="mt-0.5 text-[11.5px] text-muted">
            {hasHoldings ? (
              <>
                Max: <span className="font-medium text-fg">+${maxPayoff.toFixed(2)}</span> ({favoredSide} wins)
              </>
            ) : (
              'Redemption guarantee at expiry'
            )}
          </p>
        </div>
      </div>
    </Card>
  )
}

function WssStreamTape({ ws, ticks }: { ws?: WsStatus; ticks?: WsTick[] }) {
  return (
    <Card className="mt-3 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
        <div className="flex items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-card bg-accent-soft text-accent">
            <Radio className="size-4 animate-pulse" />
          </span>
          <div>
            <h2 className="text-[14px] font-semibold">Live WSS Orderbook Stream</h2>
            <p className="font-mono text-[11px] text-faint">wss://ws-subscriptions-clob.polymarket.com/ws/market</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <MetricChip text={`Ticks: ${ws?.tick_count ?? 0}`} />
          {ws?.reconnect_count ? <MetricChip text={`Reconnects: ${ws.reconnect_count}`} /> : null}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-card border border-line bg-surface-1 p-3.5">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-[13px] font-semibold text-success">
              <span className="size-2 rounded-full bg-success" /> Up Outcome Book
            </span>
            <span className="text-[11.5px] text-faint">
              depth: {ws?.up_book?.bid_depth ?? 0}b / {ws?.up_book?.ask_depth ?? 0}a
            </span>
          </div>
          <div className="mt-2.5 grid grid-cols-3 gap-2 text-center text-[12px]">
            <div className="rounded bg-surface-2 p-1.5">
              <div className="text-[10.5px] uppercase text-faint">Best Bid</div>
              <div className="font-semibold tabular-nums text-fg">{cents(ws?.up_book?.best_bid)}</div>
            </div>
            <div className="rounded bg-surface-2 p-1.5">
              <div className="text-[10.5px] uppercase text-faint">Midpoint</div>
              <div className="font-semibold tabular-nums text-accent">
                {ws?.up_book?.midpoint != null ? ws.up_book.midpoint.toFixed(3) : '—'}
              </div>
            </div>
            <div className="rounded bg-surface-2 p-1.5">
              <div className="text-[10.5px] uppercase text-faint">Best Ask</div>
              <div className="font-semibold tabular-nums text-fg">{cents(ws?.up_book?.best_ask)}</div>
            </div>
          </div>
        </div>

        <div className="rounded-card border border-line bg-surface-1 p-3.5">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-[13px] font-semibold text-danger">
              <span className="size-2 rounded-full bg-danger" /> Down Outcome Book
            </span>
            <span className="text-[11.5px] text-faint">
              depth: {ws?.down_book?.bid_depth ?? 0}b / {ws?.down_book?.ask_depth ?? 0}a
            </span>
          </div>
          <div className="mt-2.5 grid grid-cols-3 gap-2 text-center text-[12px]">
            <div className="rounded bg-surface-2 p-1.5">
              <div className="text-[10.5px] uppercase text-faint">Best Bid</div>
              <div className="font-semibold tabular-nums text-fg">{cents(ws?.down_book?.best_bid)}</div>
            </div>
            <div className="rounded bg-surface-2 p-1.5">
              <div className="text-[10.5px] uppercase text-faint">Midpoint</div>
              <div className="font-semibold tabular-nums text-accent">
                {ws?.down_book?.midpoint != null ? ws.down_book.midpoint.toFixed(3) : '—'}
              </div>
            </div>
            <div className="rounded bg-surface-2 p-1.5">
              <div className="text-[10.5px] uppercase text-faint">Best Ask</div>
              <div className="font-semibold tabular-nums text-fg">{cents(ws?.down_book?.best_ask)}</div>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between">
          <h3 className="text-[12.5px] font-semibold uppercase tracking-wider text-muted">Recent Stream Ticks</h3>
          <span className="text-[11.5px] text-faint">Millisecond precision tape</span>
        </div>

        {!ticks || ticks.length === 0 ? (
          <EmptyState icon={<Radio />} title="Awaiting ticks" description="Real-time orderbook events stream here as they land from WebSocket." />
        ) : (
          <div className="scrollbar-thin mt-2 max-h-[280px] overflow-y-auto">
            <table className="w-full text-left text-[12.5px]">
              <thead className="sticky top-0 border-b border-line bg-surface-1 text-[11px] uppercase tracking-wide text-faint">
                <tr>
                  <th className="py-1.5 font-medium">Timestamp</th>
                  <th className="py-1.5 font-medium">Event</th>
                  <th className="py-1.5 font-medium">Outcome</th>
                  <th className="py-1.5 font-medium">Side</th>
                  <th className="py-1.5 text-right font-medium">Price</th>
                  <th className="py-1.5 text-right font-medium">Size</th>
                  <th className="py-1.5 text-right font-medium">Midpoint</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {[...ticks].reverse().map((t, idx) => (
                  <tr key={`${t.ts}-${idx}`} className="transition-colors hover:bg-surface-2/50">
                    <td className="py-1.5 font-mono text-[11.5px] text-muted">{t.time_str || clock(t.ts * 1000)}</td>
                    <td className="py-1.5">
                      <span
                        className={cx(
                          'inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[10.5px] font-medium',
                          t.event_type === 'snapshot' ? 'bg-info-soft text-info' : 'bg-surface-2 text-fg',
                        )}
                      >
                        {t.event_type === 'snapshot' ? '📦 SNAP' : '⚡ TICK'}
                      </span>
                    </td>
                    <td className="py-1.5">
                      <Badge tone={t.outcome === 'Up' ? 'success' : 'danger'} className="px-1.5 py-0 text-[10.5px]">
                        {t.outcome}
                      </Badge>
                    </td>
                    <td className="py-1.5 text-[11.5px] font-medium">
                      {t.side ? (
                        <span className={t.side === 'BUY' ? 'text-success' : 'text-danger'}>{t.side}</span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="py-1.5 text-right font-mono tabular-nums">{t.price != null ? cents(t.price) : '—'}</td>
                    <td className="py-1.5 text-right font-mono tabular-nums text-muted">{t.size != null ? t.size.toFixed(1) : '—'}</td>
                    <td className="py-1.5 text-right font-mono tabular-nums text-accent">
                      {t.midpoint != null ? t.midpoint.toFixed(3) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Card>
  )
}
