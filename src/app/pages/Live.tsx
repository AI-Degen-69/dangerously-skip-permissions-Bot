import { useMemo, useState } from 'react'
import { Activity, Play, Radio, ShieldAlert, Target, Zap } from 'lucide-react'

import { PolymarketLiveChart } from '../components/PolymarketEmbed'
import { eventMetrics, KIND_TONE, reasonLabel as label } from '../lib/labels'
import { Badge, Button, Card, EmptyState, PageHeader, Skeleton, useToast } from '../components/ui'
import {
  BOT_ORIGIN,
  useBotControl,
  useBotEvents,
  useBotSnapshot,
  useBotTrades,
  useSetKillSwitch,
  useResumeBot,
  useStartBot,
  useBotWsTicks,
  type WsStatus,
  type WsTick,
  type BotEvent,
  type BotSnapshot,
  type BotTrade,
  type MarketView,
  type PositionView,
} from '../lib/bot'
import { cx } from '../lib/cx'
import { relativeTime } from '../lib/format'

const money = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `${value < 0 ? '−' : ''}$${Math.abs(value).toFixed(2)}`
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
  const killSwitch = useSetKillSwitch()
  const control = useBotControl()
  const start = useStartBot()
  const wsTicks = useBotWsTicks()
  const toast = useToast()

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
  const startBot = () =>
    start.mutate(undefined, {
      onSuccess: (result) => toast(result.reason === 'already-running' ? 'Bot already running' : 'Paper bot started'),
      onError: (error: Error) => toast(error.message, 'danger'),
    })

  return (
    <div className="mx-auto max-w-[1200px] p-5 sm:p-8">
      <PageHeader
        title="Live bot"
        subtitle="What it sees right now, why it decides, and every fill it made."
        actions={
          <div className="flex flex-wrap items-center gap-2">
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
            {isViewOnly ? (
              <Badge tone="warning" dot>
                View only
              </Badge>
            ) : (
              <Button
                variant={stopped ? 'primary' : 'danger'}
                size="sm"
                disabled={!running}
                loading={killSwitch.isPending}
                onClick={() => killSwitch.mutate(!stopped)}
              >
                {stopped ? <Play /> : <ShieldAlert />}
                {stopped ? 'Resume entries' : 'Pause entries'}
              </Button>
            )}
            {!running && !isViewOnly && (
              <Button variant="primary" size="sm" loading={start.isPending} onClick={startBot}>
                <Play /> Start bot
              </Button>
            )}
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
                  No windows are being traded, so there is nothing streaming to show. Start it to resume one 5-minute
                  straddle window at a time.
                  {snapshot.data?.ageMs != null && (
                    <> Last heartbeat {relativeTime(Date.now() - snapshot.data.ageMs)}.</>
                  )}
                </p>
              </div>
            </div>
            <Button variant="primary" size="sm" loading={start.isPending} onClick={startBot}>
              <Play /> Start paper bot
            </Button>
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
            <StraddleDeskStrip data={data} ws={ws} />

            <PolymarketLiveChart markets={data.markets} positions={data.positions} ws={ws} />

            <div className="mt-3 grid gap-3 lg:grid-cols-3">
              <Card className="p-5 lg:col-span-2">
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

              <div className="flex flex-col gap-3">
                <Positions data={data} />
                <RiskPanel data={data} />
              </div>
            </div>

            <WssStreamTape ws={ws} ticks={ticks} />

            <Trades items={trades.data?.items ?? []} />
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

  return <span className="truncate text-[13px]">{label(event.reason)}</span>
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

function Positions({ data }: { data: BotSnapshot }) {
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-[14px] font-semibold">Open positions</h2>
        <Badge tone={data.positions.length > 0 ? 'accent' : 'neutral'}>{data.positions.length}</Badge>
      </div>
      {data.positions.length === 0 ? (
        <p className="mt-3 text-[13px] text-muted">Flat. The bot only holds a position when every entry gate passes.</p>
      ) : (
        <ul className="mt-2 divide-y divide-line">
          {data.positions.map((position) => (
            <PositionRow key={position.id} position={position} markets={data.markets} />
          ))}
        </ul>
      )}
    </Card>
  )
}

function PositionRow({ position, markets }: { position: PositionView; markets?: MarketView[] }) {
  const isResolving = Boolean(position.resolving ?? (position.secondsLeft <= 0))

  // Mid-window fallback: if window is still running, ensure mark and pnl are not hidden with a dash
  const market = markets?.find((m) => m.slug === position.slug)
  const quotes = market?.quotes?.[position.side]
  const quoteMark = quotes?.bid ?? quotes?.ask ?? null
  const fallbackMark = position.mark ?? quoteMark ?? (isResolving ? null : 0)
  const fallbackPnl =
    position.unrealizedPnlUsd ??
    (fallbackMark != null ? Number((fallbackMark * position.shares - position.costUsd).toFixed(2)) : (isResolving ? null : -position.costUsd))

  const mark = isResolving && position.mark == null ? null : fallbackMark
  const pnl = isResolving && position.unrealizedPnlUsd == null ? null : fallbackPnl
  const resolving = isResolving && pnl == null

  return (
    <li className="py-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge tone={position.side === 'Up' ? 'success' : 'danger'}>{position.side}</Badge>
          <span className="text-[12.5px] text-muted">{windowLabel(position.slug)}</span>
        </div>
        <span
          className={cx(
            'text-[13px] font-semibold tabular-nums',
            resolving || pnl == null ? 'text-faint' : pnl >= 0 ? 'text-success' : 'text-danger',
          )}
        >
          {resolving ? 'resolving…' : money(pnl)}
        </span>
      </div>
      <div className="mt-1.5 grid grid-cols-3 gap-2 text-[12px] text-muted">
        <span>
          {position.shares} @ {cents(position.entryPrice)}
        </span>
        <span>mark {mark == null ? '—' : cents(mark)}</span>
        <span className="text-right">{Math.max(0, Math.round(position.secondsLeft))}s left</span>
      </div>
      <div className="mt-1 flex items-center gap-2 text-[11.5px] text-faint">
        <span>p {position.modelProb.toFixed(3)}</span>
        <span>edge {(position.edge * 100).toFixed(1)}¢</span>
        {position.stalledSec !== null && <span className="text-warning">stalled {Math.round(position.stalledSec)}s</span>}
      </div>
    </li>
  )
}

function RiskPanel({ data }: { data: BotSnapshot }) {
  const { risk, limits } = data
  const resume = useResumeBot()
  const toast = useToast()
  const dayLoss = Math.max(0, risk.dayStartEquityUsd - data.equityUsd)
  const dayLimit = limits.dailyLossCapUsd != null ? limits.dailyLossCapUsd : (risk.dayStartEquityUsd * limits.dailyLossLimitPct) / 100
  const drawdown = Math.max(0, risk.highWaterEquityUsd - data.equityUsd)
  const drawdownLimit = (risk.highWaterEquityUsd * limits.maxDrawdownPct) / 100
  const cooldownLeft = Math.max(0, Math.round((risk.cooldownUntilMs - Date.now()) / 1000))

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-[14px] font-semibold">Risk limits</h2>
        <Zap className="size-4 text-faint" />
      </div>
      <ul className="mt-3 space-y-3">
        <Limit label="Trades today" value={`${risk.tradesToday} / ${limits.maxTradesPerDay}`} ratio={risk.tradesToday / limits.maxTradesPerDay} />
        <Limit
          label="Losses in a row"
          value={`${risk.consecutiveLosses} / ${limits.maxConsecutiveLosses}`}
          ratio={risk.consecutiveLosses / limits.maxConsecutiveLosses}
        />
        <Limit label="Daily loss" value={`${money(dayLoss)} of ${money(dayLimit)}`} ratio={dayLimit > 0 ? dayLoss / dayLimit : 0} />
        <Limit label="Drawdown" value={`${money(drawdown)} of ${money(drawdownLimit)}`} ratio={drawdownLimit > 0 ? drawdown / drawdownLimit : 0} />
      </ul>

      {risk.halted && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-tile bg-danger-soft p-2.5 text-[12.5px] text-danger">
          <span>Halted for the day: {label(risk.haltReason)}</span>
          <Button
            size="sm"
            variant="secondary"
            loading={resume.isPending}
            onClick={() =>
              resume.mutate(undefined, {
                onSuccess: () => toast('Risk halt cleared and entries resumed'),
                onError: (err: Error) => toast(err.message, 'danger'),
              })
            }
          >
            Clear halt & resume
          </Button>
        </div>
      )}
      {cooldownLeft > 0 && !risk.halted && (
        <p className="mt-3 rounded-tile bg-warning-soft px-2.5 py-2 text-[12.5px] text-warning">
          Cooling down after a loss — {cooldownLeft}s left
        </p>
      )}
      {data.newsBlocked && <p className="mt-3 rounded-tile bg-info-soft px-2.5 py-2 text-[12.5px] text-info">News blackout active</p>}
    </Card>
  )
}

function Limit({ label: limitLabel, value, ratio }: { label: string; value: string; ratio: number }) {
  const clamped = Math.min(1, Math.max(0, Number.isFinite(ratio) ? ratio : 0))
  return (
    <li>
      <div className="flex items-center justify-between text-[12.5px]">
        <span className="text-muted">{limitLabel}</span>
        <span className="tabular-nums">{value}</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
        <div
          className={cx('h-full rounded-full', clamped >= 1 ? 'bg-danger' : clamped > 0.66 ? 'bg-warning' : 'bg-accent')}
          style={{ width: `${clamped * 100}%` }}
        />
      </div>
    </li>
  )
}

function parseTsMs(ts: number | string): number {
  const raw = typeof ts === 'string' ? Number(ts) || new Date(ts).getTime() : ts
  return Number.isFinite(raw) ? (raw < 1e11 ? raw * 1000 : raw) : Date.now()
}

function formatWindow(slug?: string, fallbackTs?: number | string): string {
  if (slug) {
    const parts = slug.split('-')
    const epoch = Number(parts[parts.length - 1])
    if (Number.isFinite(epoch) && epoch > 0) {
      const ms = epoch < 1e11 ? epoch * 1000 : epoch
      return new Date(ms).toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
      })
    }
  }
  if (fallbackTs != null) {
    const raw = typeof fallbackTs === 'string' ? Number(fallbackTs) || new Date(fallbackTs).getTime() : fallbackTs
    if (Number.isFinite(raw) && raw > 0) {
      const ms = raw < 1e11 ? raw * 1000 : raw
      return new Date(ms).toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
      })
    }
  }
  return '—'
}

function formatPriceCents(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const c = value * 100
  return c % 1 === 0 ? `${c}¢` : `${c.toFixed(1)}¢`
}

interface WhyInfo {
  label: string
  sub?: string
  tone: 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info'
  tip: string
}

function getTradeWhy(trade: BotTrade): WhyInfo {
  const reason = trade.reason || (trade.kind === 'settle' ? 'paper-resolve' : 'paper-fill')
  const detail = trade.detail as Record<string, unknown> | undefined
  const minute = detail?.minute as number | undefined
  const lean = detail?.lean as number | undefined
  const winner = detail?.winner as string | undefined

  switch (reason) {
    case 'straddle-open':
      return {
        label: 'Straddle Open',
        sub: 'T+13s first touch',
        tone: 'accent',
        tip: 'First touch opening leg executed ~13s into the window to establish straddle base.',
      }
    case 'hedge-leg':
      return {
        label: 'Hedge Leg',
        sub: '+15s opposite leg',
        tone: 'info',
        tip: 'Counter hedge leg filled 15s after open to balance direction exposure.',
      }
    case 'lean-up':
      return {
        label: 'Lean Up',
        sub: lean != null ? `lean ${lean > 0 ? `+${lean}` : lean}` : 'OB microprice tilt',
        tone: 'success',
        tip: 'Orderbook queue imbalance and depth microprice tilted odds heavily toward Up.',
      }
    case 'lean-down':
      return {
        label: 'Lean Down',
        sub: lean != null ? `lean ${lean > 0 ? `+${lean}` : lean}` : 'OB microprice tilt',
        tone: 'danger',
        tip: 'Orderbook queue imbalance and depth microprice tilted odds heavily toward Down.',
      }
    case 'm4-snipe':
      return {
        label: 'M4 Snipe',
        sub: 'extreme discount',
        tone: 'warning',
        tip: 'Late window (M4) snipe targeting extreme tail-end odds (<15¢ / >85¢).',
      }
    case 'straddle-balance':
      return {
        label: 'Straddle Balance',
        sub: minute != null ? `M${minute} cadence` : 'even allocation',
        tone: 'neutral',
        tip: 'Cadence rebalance fill preserving even straddle distribution across the 5m window.',
      }
    case 'awaiting-resolution':
      return {
        label: 'Awaiting Settlement',
        sub: 'window closed',
        tone: 'warning',
        tip: '5-minute window concluded; waiting for Polymarket oracle resolution.',
      }
    case 'won':
      return {
        label: 'Settled · Won',
        sub: winner ? `winner ${winner}` : undefined,
        tone: 'success',
        tip: `Window resolved in bot's favor (${winner ?? 'win'}).`,
      }
    case 'lost':
      return {
        label: 'Settled · Lost',
        sub: winner ? `winner ${winner}` : undefined,
        tone: 'danger',
        tip: `Window resolved against bot (${winner ?? 'loss'}).`,
      }
    case 'paper-resolve':
      return {
        label: winner ? `Winner: ${winner}` : 'Settled',
        sub: 'resolved',
        tone: winner === 'Up' ? 'success' : winner === 'Down' ? 'danger' : 'accent',
        tip: `Market outcome resolved to ${winner ?? 'official result'}.`,
      }
    default:
      if (minute === 0) {
        return {
          label: 'Straddle Leg',
          sub: 'M0 open',
          tone: 'accent',
          tip: 'Opening straddle execution.',
        }
      }
      if (minute === 4) {
        return {
          label: 'M4 Snipe',
          sub: 'late window',
          tone: 'warning',
          tip: 'Late-window tail execution.',
        }
      }
      if (minute != null) {
        return {
          label: 'Straddle Cadence',
          sub: `M${minute}`,
          tone: 'neutral',
          tip: `Fill executed during minute M${minute} cadence quota.`,
        }
      }
      return {
        label: label(trade.reason),
        sub: undefined,
        tone: 'neutral',
        tip: 'Recorded paper order execution.',
      }
  }
}

function TradeWhyCell({ trade }: { trade: BotTrade }) {
  const why = getTradeWhy(trade)
  return (
    <div className="flex items-center gap-1.5" title={why.tip}>
      <Badge tone={why.tone} className="px-2 py-0.5 text-[10.5px] font-semibold">
        {why.label}
      </Badge>
      {why.sub && <span className="max-w-[130px] truncate text-[11px] tabular-nums text-faint">{why.sub}</span>}
    </div>
  )
}

function Trades({ items }: { items: BotTrade[] }) {
  const upFills = items.filter((t) => t.side === 'Up' || t.detail?.winner === 'Up').length
  const downFills = items.filter((t) => t.side === 'Down' || t.detail?.winner === 'Down').length
  const totalSpent = items.reduce((acc, t) => acc + (t.usd ?? (t.shares && t.price ? t.shares * t.price : 0)), 0)

  return (
    <Card className="mt-3 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
        <div className="flex items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-card bg-[#f7931a]/15 text-[#f7931a] shadow-sm">
            <span className="text-[14px] font-bold leading-none">₿</span>
          </span>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-[14px] font-semibold">Fills & Executions</h2>
              <Badge tone="neutral">{items.length} fills</Badge>
            </div>
            <p className="text-[12px] text-muted">Real-time order execution stream across 5-minute straddle windows.</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {items.length > 0 && (
            <>
              <Badge tone="success" dot className="px-2 py-0.5 text-[11px]">
                {upFills} Up
              </Badge>
              <Badge tone="danger" dot className="px-2 py-0.5 text-[11px]">
                {downFills} Down
              </Badge>
              <MetricChip text={`Total: $${totalSpent.toFixed(2)}`} />
            </>
          )}
        </div>
      </div>

      {items.length === 0 ? (
        <EmptyState icon={<Target />} title="No fills yet" description="Fills land here as the paper loop works each window." />
      ) : (
        <div className="scrollbar-thin mt-3 max-h-[480px] overflow-x-auto overflow-y-auto">
          <table className="w-full min-w-[760px] text-left text-[12.5px]">
            <thead className="sticky top-0 z-10 border-b border-line bg-surface-1/95 text-[11px] font-semibold uppercase tracking-wider text-faint backdrop-blur">
              <tr>
                <th className="py-2.5 px-3 font-medium">Time</th>
                <th className="py-2.5 px-3 font-medium">Window</th>
                <th className="py-2.5 px-3 font-medium">Event</th>
                <th className="py-2.5 px-3 font-medium">Side</th>
                <th className="py-2.5 px-3 text-right font-medium">Size</th>
                <th className="py-2.5 px-3 text-right font-medium">Price</th>
                <th className="py-2.5 px-3 text-right font-medium">Total Cost</th>
                <th className="py-2.5 px-3 font-medium">
                  <span className="inline-flex items-center gap-1 cursor-help" title="Strategy decision rationale behind each execution or settlement">
                    Why (?)
                  </span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {[...items].reverse().map((trade, index) => {
                const tsMs = parseTsMs(trade.ts)
                const side = trade.side ?? (trade.detail?.winner as string | undefined)
                const cost = trade.usd ?? (trade.shares != null && trade.price != null ? trade.shares * trade.price : null)

                return (
                  <tr key={`${trade.ts}-${index}`} className="transition-colors hover:bg-surface-2/60">
                    {/* 1. Time: Xm ago, <timestamp> in smaller font */}
                    <td className="py-2.5 px-3">
                      <div className="flex flex-col">
                        <span className="text-[12.5px] font-medium text-fg">{relativeTime(tsMs)}</span>
                        <span className="font-mono text-[11px] text-faint">{clock(tsMs)}</span>
                      </div>
                    </td>

                    {/* 2. Window: HH:MM */}
                    <td className="py-2.5 px-3 font-mono text-[12.5px] font-medium text-fg">
                      {formatWindow(trade.slug, tsMs)}
                    </td>

                    {/* 3. Event: Buy / Settle / Exit */}
                    <td className="py-2.5 px-3">
                      <span
                        className={cx(
                          'inline-flex items-center rounded-[6px] px-2 py-0.5 font-mono text-[10.5px] font-semibold uppercase tracking-wider',
                          trade.kind === 'entry'
                            ? 'bg-success-soft text-success'
                            : trade.kind === 'settle'
                            ? 'bg-accent-soft text-accent'
                            : trade.kind === 'exit'
                            ? 'bg-info-soft text-info'
                            : 'bg-surface-2 text-fg',
                        )}
                      >
                        {trade.kind === 'entry' ? 'Buy' : trade.kind === 'settle' ? 'Settle' : trade.kind === 'exit' ? 'Sell' : trade.kind}
                      </span>
                    </td>

                    {/* 4. Side: same as WS "side" column (Up / Down colored label) */}
                    <td className="py-2.5 px-3">
                      {side ? (
                        <Badge
                          tone={side === 'Up' ? 'success' : side === 'Down' ? 'danger' : 'neutral'}
                          className="px-2 py-0.5 text-[11px] font-semibold"
                        >
                          {side}
                        </Badge>
                      ) : (
                        <span className="font-mono text-faint">—</span>
                      )}
                    </td>

                    {/* 5. Size */}
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

                    {/* 6. Price */}
                    <td className="py-2.5 px-3 text-right font-mono text-[12.5px] font-medium tabular-nums text-fg">
                      {trade.price != null ? formatPriceCents(trade.price) : <span className="text-faint">—</span>}
                    </td>

                    {/* 7. Total Cost */}
                    <td className="py-2.5 px-3 text-right font-mono text-[12.5px] font-semibold tabular-nums text-fg">
                      {cost != null ? money(cost) : <span className="font-normal text-faint">—</span>}
                    </td>

                    {/* 8. Why(?) */}
                    <td className="py-2.5 px-3">
                      <TradeWhyCell trade={trade} />
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

function StraddleDeskStrip({ data, ws }: { data: BotSnapshot; ws?: WsStatus }) {
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

  let pairCost: number | null = null
  let isIndicative = false
  if (isHedged && upAvg != null && downAvg != null) {
    pairCost = upAvg + downAvg
  } else if (activeMarket?.quotes.Up.ask != null && activeMarket?.quotes.Down.ask != null) {
    pairCost = activeMarket.quotes.Up.ask + activeMarket.quotes.Down.ask
    isIndicative = true
  }

  const totalCost = (upPos?.costUsd ?? 0) + (downPos?.costUsd ?? 0)
  const payIfUp = upShares * 1.0 - totalCost
  const payIfDown = downShares * 1.0 - totalCost
  const minFloor = hasHoldings ? Math.min(payIfUp, payIfDown) : 0
  const maxPayoff = hasHoldings ? Math.max(payIfUp, payIfDown) : 0
  const favoredSide = payIfUp >= payIfDown ? 'Up' : 'Down'
  const delta = Math.round(upShares) - Math.round(downShares)

  const fillsCount =
    Number(activeMarket?.verdict?.detail?.fills) ||
    (positions.length > 0 ? (upShares > 0 ? 1 : 0) + (downShares > 0 ? 1 : 0) : 0)
  const targetFills = 45
  const windowCap = 4000

  return (
    <Card className="mt-3 p-4">
      <div className="grid grid-cols-2 gap-4 divide-y sm:divide-y-0 sm:divide-x divide-line lg:grid-cols-4">
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
                {isIndicative ? '/ book' : '/ pair'}
              </span>
            )}
          </div>
          <p className="mt-0.5 text-[11.5px] text-muted">
            {pairCost == null ? (
              'Awaiting first fill'
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

        {/* Metric 2: Holdings & Net Bias */}
        <div className="pt-2 sm:pt-0 sm:px-3">
          <p className="text-[11px] font-medium uppercase tracking-wide text-faint">Holdings & Net Bias</p>
          <p className="mt-1 text-[22px] font-semibold tracking-[-0.02em] tabular-nums">
            {hasHoldings ? `${Math.round(upShares)} Up · ${Math.round(downShares)} Down` : '0 Up · 0 Down'}
          </p>
          <p className="mt-0.5 text-[11.5px] text-muted">
            {!hasHoldings ? (
              'Flat · No open inventory'
            ) : delta === 0 ? (
              <span className="font-medium text-success">Balanced 1:1 (Flat Delta)</span>
            ) : delta > 0 ? (
              <span className="font-medium text-accent">Net: +{delta} Up bias</span>
            ) : (
              <span className="font-medium text-warning">Net: +{Math.abs(delta)} Down bias</span>
            )}
          </p>
        </div>

        {/* Metric 3: Guaranteed Settlement Floor */}
        <div className="pt-2 sm:pt-0 sm:px-3">
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
            {hasHoldings && <span className="text-[11px] text-faint">min floor</span>}
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

        {/* Metric 4: Window Budget & Clips */}
        <div className="pt-2 sm:pt-0 sm:px-3 last:pr-0">
          <p className="text-[11px] font-medium uppercase tracking-wide text-faint">Window Budget & Clips</p>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-[22px] font-semibold tracking-[-0.02em] tabular-nums">
              ${totalCost.toFixed(2)}
            </span>
            <span className="text-[11.5px] text-faint">of ${windowCap.toLocaleString()}</span>
          </div>
          <div className="mt-1 flex items-center justify-between text-[11px] text-faint">
            <span className="tabular-nums">
              {fillsCount}/{targetFills} clips
            </span>
            {ws?.state === 'connected' && (
              <span className="tabular-nums opacity-80">
                WSS {ws.age_ms != null ? `${ws.age_ms}ms` : '<40ms'}
              </span>
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}


function WssStreamTape({ ws, ticks }: { ws?: WsStatus; ticks?: WsTick[] }) {
  const isConnected = ws?.state === 'connected'
  const isStale = ws?.state === 'stale'
  const isFallback = ws?.state === 'fallback_active'

  return (
    <Card className="mt-3 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
        <div className="flex items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-card bg-accent-soft text-accent">
            <Radio className="size-4 animate-pulse" />
          </span>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-[14px] font-semibold">Live WSS Orderbook Stream</h2>
              <Badge
                tone={isConnected ? 'success' : isStale ? 'warning' : isFallback ? 'danger' : 'neutral'}
                dot
              >
                {isConnected
                  ? 'Connected (<40ms)'
                  : isStale
                  ? 'Stale Feed (>3s)'
                  : isFallback
                  ? 'REST Fallback Active'
                  : 'Disconnected'}
              </Badge>
            </div>
            <p className="font-mono text-[11px] text-faint">wss://ws-subscriptions-clob.polymarket.com/ws/market</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {ws?.age_ms != null && <MetricChip text={`Tick Age: ${ws.age_ms}ms`} />}
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
