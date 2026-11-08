import { Activity, Clock, Play, Radio, ShieldAlert, Target, Zap } from 'lucide-react'

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
            <Card className="mt-3 flex flex-wrap items-center justify-between gap-4 p-4">
              <div>
                <p className="text-[11.5px] uppercase tracking-wide text-faint">BTC reference price</p>
                <p className="text-[24px] font-semibold tracking-[-0.02em] tabular-nums">
                  {data.feed.price === null ? '—' : data.feed.price.toFixed(2)}
                </p>
              </div>
              <div className="h-14 w-full max-w-[440px]">
                <Spark points={data.feed.history} />
              </div>
              <p className="text-[12px] text-faint">
                <Clock className="mr-1 inline size-3.5" />
                updated {data.feed.updatedAtMs ? clock(data.feed.updatedAtMs) : '—'}
              </p>
            </Card>

            <PolymarketLiveChart markets={data.markets} positions={data.positions} />

            <div className="mt-3 grid gap-3 lg:grid-cols-3">
              <Card className="p-5 lg:col-span-2">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-[14px] font-semibold">Decision journal</h2>
                    <p className="text-[12.5px] text-muted">Every gate it passed or failed, newest first.</p>
                  </div>
                  <Badge tone="neutral">{events.data?.items.length ?? 0} events</Badge>
                </div>
                <div className="scrollbar-thin mt-2 max-h-[440px] overflow-y-auto">
                  {events.data && events.data.items.length > 0 ? (
                    <ul className="divide-y divide-line">
                      {[...events.data.items].reverse().map((event, index) => (
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
                    <EmptyState icon={<Activity />} title="No decisions logged yet" description="Entries, exits, holds and skips appear here as the bot ticks." />
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

function EventRow({ event }: { event: BotEvent }) {
  const metrics = eventMetrics(event.reason, event.detail)

  return (
    <li className="flex items-start gap-3 py-2.5">
      <span className="mt-0.5 w-[58px] shrink-0 text-[11.5px] tabular-nums text-faint">{clock(event.ts)}</span>
      <Badge tone={KIND_TONE[event.kind] ?? 'neutral'} className="shrink-0 capitalize">
        {event.kind}
      </Badge>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px]">{label(event.reason)}</p>
        <p className="truncate text-[11.5px] text-faint">
          {event.slug ? windowLabel(event.slug) : 'bot'}
          {event.side ? ` · ${event.side}` : ''}
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
            <PositionRow key={position.id} position={position} />
          ))}
        </ul>
      )}
    </Card>
  )
}

function PositionRow({ position }: { position: PositionView }) {
  const pnl = position.unrealizedPnlUsd
  const resolving = pnl == null
  return (
    <li className="py-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge tone={position.side === 'Up' ? 'success' : 'danger'}>{position.side}</Badge>
          <span className="text-[12.5px] text-muted">{windowLabel(position.slug)}</span>
        </div>
        <span className={cx('text-[13px] font-semibold tabular-nums', resolving ? 'text-faint' : pnl! >= 0 ? 'text-success' : 'text-danger')}>
          {resolving ? 'resolving…' : money(pnl)}
        </span>
      </div>
      <div className="mt-1.5 grid grid-cols-3 gap-2 text-[12px] text-muted">
        <span>
          {position.shares} @ {cents(position.entryPrice)}
        </span>
        <span>mark {position.mark == null ? '—' : cents(position.mark)}</span>
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
  const dayLimit = (risk.dayStartEquityUsd * limits.dailyLossLimitPct) / 100
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

function Trades({ items }: { items: BotTrade[] }) {
  return (
    <Card className="mt-3 p-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[14px] font-semibold">Fills</h2>
          <p className="text-[12.5px] text-muted">Every entry, exit and settlement, newest first.</p>
        </div>
        <Badge tone="neutral">{items.length}</Badge>
      </div>

      {items.length === 0 ? (
        <EmptyState icon={<Target />} title="No fills yet" description="Fills land here as the paper loop works each window." />
      ) : (
        <div className="scrollbar-thin mt-3 overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-[13px]">
            <thead className="text-[11.5px] uppercase tracking-wide text-faint">
              <tr className="border-b border-line">
                <th className="py-2 font-medium">Time</th>
                <th className="py-2 font-medium">Event</th>
                <th className="py-2 font-medium">Window</th>
                <th className="py-2 font-medium">Side</th>
                <th className="py-2 text-right font-medium">Price</th>
                <th className="py-2 text-right font-medium">Shares</th>
                <th className="py-2 text-right font-medium">PnL</th>
                <th className="py-2 font-medium">Why</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {[...items].reverse().map((trade, index) => (
                <tr key={`${trade.ts}-${index}`}>
                  <td className="py-2.5 tabular-nums text-muted">{clock(trade.ts)}</td>
                  <td className="py-2.5">
                    <Badge tone={KIND_TONE[trade.kind] ?? 'neutral'} className="capitalize">
                      {trade.kind}
                    </Badge>
                  </td>
                  <td className="py-2.5 text-muted">{trade.slug ? windowLabel(trade.slug) : '—'}</td>
                  <td className="py-2.5">{trade.side ?? '—'}</td>
                  <td className="py-2.5 text-right tabular-nums">{cents(trade.price)}</td>
                  <td className="py-2.5 text-right tabular-nums">{trade.shares ?? '—'}</td>
                  <td
                    className={cx(
                      'py-2.5 text-right font-medium tabular-nums',
                      trade.pnlUsd == null ? 'text-faint' : trade.pnlUsd >= 0 ? 'text-success' : 'text-danger',
                    )}
                  >
                    {trade.pnlUsd == null ? '—' : money(trade.pnlUsd)}
                  </td>
                  <td className="py-2.5 text-muted">{label(trade.reason)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

function Spark({ points }: { points: { ts: number; value: number }[] }) {
  if (points.length < 2) {
    return <div className="grid h-full place-items-center text-[12px] text-faint">collecting price…</div>
  }
  const values = points.map((point) => point.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const width = 440
  const height = 56
  const path = points
    .map((point, index) => `${index === 0 ? 'M' : 'L'}${(index / (points.length - 1)) * width},${height - ((point.value - min) / span) * (height - 4) - 2}`)
    .join(' ')
  const up = values[values.length - 1] >= values[0]

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" preserveAspectRatio="none" aria-hidden>
      <path d={path} fill="none" stroke={up ? 'var(--color-success)' : 'var(--color-danger)'} strokeWidth="1.75" vectorEffect="non-scaling-stroke" />
    </svg>
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
