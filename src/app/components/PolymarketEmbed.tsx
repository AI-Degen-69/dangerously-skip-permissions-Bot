import { Activity, ArrowUpRight, Radio, TrendingDown, TrendingUp } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { useBotConfig, type BotConfigView, type Interval, type MarketView, type PositionView, type WsStatus } from '../lib/bot'
import { cx } from '../lib/cx'
import { reasonLabel } from '../lib/labels'
import { Badge, Card } from './ui'

export function getWsLatencyStatus(ws?: WsStatus | null) {
  if (!ws || ws.state === 'disconnected') {
    return {
      label: 'Disconnected',
      rawMs: null,
      tone: 'neutral' as const,
      badgeClass: 'bg-surface-2 text-muted',
      dotClass: 'bg-muted',
      colorClass: 'text-muted',
    }
  }
  if (ws.state === 'fallback_active' || ws.state === 'stale') {
    const ageMs = ws.age_ms ?? 3000
    return {
      label: `Stale (${(ageMs / 1000).toFixed(1)}s)`,
      rawMs: ageMs,
      tone: 'danger' as const,
      badgeClass: 'bg-danger-soft text-danger',
      dotClass: 'bg-danger',
      colorClass: 'text-danger',
    }
  }
  const ageMs = ws.age_ms
  // Green range: < 150ms
  if (ageMs == null || ageMs < 150) {
    return {
      label: ageMs == null ? '<40ms' : `${ageMs}ms`,
      rawMs: ageMs,
      tone: 'success' as const,
      badgeClass: 'bg-success-soft text-success',
      dotClass: 'bg-success',
      colorClass: 'text-success',
    }
  }
  // Yellow range: 150ms - 500ms
  if (ageMs <= 500) {
    return {
      label: `${ageMs}ms`,
      rawMs: ageMs,
      tone: 'warning' as const,
      badgeClass: 'bg-warning-soft text-warning',
      dotClass: 'bg-warning',
      colorClass: 'text-warning',
    }
  }
  // Red range: > 500ms
  return {
    label: `${ageMs}ms`,
    rawMs: ageMs,
    tone: 'danger' as const,
    badgeClass: 'bg-danger-soft text-danger',
    dotClass: 'bg-danger',
    colorClass: 'text-danger',
  }
}

// Polymarket's official embed only plots last-trade prints, so a market this
// quiet is stuck at its listing price forever. These panels keep the Polymarket
// credit but chart the live book instead: implied Up odds sampled every
// snapshot poll (2s) over the window, alongside the bot's own decision stats.

// Implied Up probability, normalized from asks (or either side alone).
function impliedUp(market: MarketView): number {
  const up = market.quotes.Up.ask ?? market.quotes.Up.bid
  const down = market.quotes.Down.ask ?? market.quotes.Down.bid
  if (up !== null && down !== null && up + down > 0) return up / (up + down)
  if (up !== null) return up
  if (down !== null) return 1 - down
  return 0.5
}

interface OddsPoint {
  t: number
  v: number // implied Up, 0..1
}

interface GateTick {
  atSec: number
  tone: string
  label: string
  title: string
}

const MAX_SAMPLES = 500
const MAX_CACHED_MARKETS = 20
const ODDS_SERIES_CACHE = new Map<string, OddsPoint[]>()

function pruneOddsCache(): void {
  while (ODDS_SERIES_CACHE.size > MAX_CACHED_MARKETS) {
    const oldest = ODDS_SERIES_CACHE.keys().next().value
    if (!oldest) break
    ODDS_SERIES_CACHE.delete(oldest)
  }
}

const useOddsSeries = (market: MarketView): OddsPoint[] => {
  // When the bot engine provides continuous server-side odds history, use it
  if (market.oddsHistory && market.oddsHistory.length > 0) {
    ODDS_SERIES_CACHE.set(market.slug, market.oddsHistory)
    pruneOddsCache()
    return market.oddsHistory
  }

  let points = ODDS_SERIES_CACHE.get(market.slug)
  if (!points) {
    points = []
    ODDS_SERIES_CACHE.set(market.slug, points)
    pruneOddsCache()
  }
  const now = Date.now()
  const v = impliedUp(market)

  if (points.length === 0) {
    // Only anchor at 0.5 if we are actually at the start of the window
    if (Math.abs(now - market.startMs) < 15_000) {
      points.push({ t: market.startMs, v: 0.5 })
    }
    points.push({ t: now, v })
  } else if (now - points[points.length - 1]!.t > 1_500) {
    points.push({ t: now, v })
  }
  if (points.length > MAX_SAMPLES) points.splice(0, points.length - MAX_SAMPLES)

  return points
}

const priceCents = (value: number | null) => (value === null ? '-' : `${Math.round(value * 100)}¢`)
const clock = (ms: number) => new Date(ms).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
// Elapsed time into the window, e.g. 5:00 — "passed", not "remaining".
const mmss = (sec: number) => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, '0')}`

export function PolymarketLiveChart({
  markets,
  positions = [],
  ws,
}: {
  markets: MarketView[]
  positions?: PositionView[]
  ws?: WsStatus
}) {
  const { data: config } = useBotConfig()
  const lastMarkets = useRef<MarketView[]>([])
  useEffect(() => {
    if (markets.length > 0) {
      lastMarkets.current = markets
    } else {
      const now = Date.now()
      lastMarkets.current = lastMarkets.current.filter((m) => m.endMs > now)
    }
  }, [markets])
  const now = Date.now()
  const activeMarkets = markets.length > 0 ? markets : lastMarkets.current.filter((m) => m.endMs > now)

  return (
    <div className="mt-3 grid gap-3 lg:grid-cols-2">
      {activeMarkets.length === 0 ? (
        <Card className="p-5 lg:col-span-2">
          <WaitingBody />
        </Card>
      ) : (
        activeMarkets.map((market) => (
          <MarketChartPanel
            key={market.slug}
            market={market}
            positions={positions.filter((p) => p.slug === market.slug)}
            params={config?.config.intervalParams[market.interval] ?? null}
            wide={activeMarkets.length === 1}
            ws={ws}
          />
        ))
      )}
    </div>
  )
}

function MarketChartPanel({
  market,
  positions = [],
  params,
  wide = false,
  ws,
}: {
  market: MarketView
  positions?: PositionView[]
  params: BotConfigView['intervalParams'][Interval] | null
  wide?: boolean
  ws?: WsStatus
}) {
  const points = useOddsSeries(market)
  const total = Math.max(1, market.endMs - market.startMs)
  const intervalSec = total / 1000
  const hasUp = positions.some((p) => p.side === 'Up')
  const hasDown = positions.some((p) => p.side === 'Down')
  const position = positions[0]
  const progress = Math.min(1, Math.max(0, (total - market.secondsRemaining * 1000) / total))
  const elapsedSec = Math.max(0, intervalSec - market.secondsRemaining)
  // The bar is a calendar of the bot's regimes, independent of whether a trade
  // is available right now: observe (accent) → tradeable (green) → closed (red).
  const bands = params
    ? [
        {
          key: 'observe',
          from: 0,
          to: params.observationSeconds,
          tone: 'bg-accent',
          soft: 'bg-accent-soft',
        },
        {
          key: 'tradeable',
          from: params.observationSeconds,
          to: intervalSec - params.minRemainingSeconds,
          tone: 'bg-success',
          soft: 'bg-success-soft',
        },
        {
          key: 'closed',
          from: intervalSec - params.minRemainingSeconds,
          to: intervalSec,
          tone: 'bg-danger',
          soft: 'bg-danger-soft',
        },
      ]
        .map((band) => {
          const to = Math.max(band.from, Math.min(band.to, intervalSec))
          const filled = Math.min(1, Math.max(0, (elapsedSec - band.from) / Math.max(1, to - band.from)))
          return { ...band, width: ((to - band.from) / intervalSec) * 100, filled: filled * 100 }
        })
        .filter((band) => band.width > 0)
    : []
  // Ticks sit on the regime boundaries and minute bucket edges, labelled with elapsed time.
  const gateTicks = params
    ? [
        {
          atSec: params.observationSeconds,
          tone: 'bg-info',
          label: mmss(params.observationSeconds),
          title: `Observation window ends · direction must then hold ${params.minDirectionHoldSeconds}s`,
        },
        position && params.stallSeconds > 0
          ? {
              atSec: (position.entryAtMs - market.startMs) / 1000 + params.stallSeconds,
              tone: 'bg-danger',
              label: mmss((position.entryAtMs - market.startMs) / 1000 + params.stallSeconds),
              title: `Stall exit · ${params.stallSeconds}s without movement`,
            }
          : null,
        {
          atSec: intervalSec - params.minRemainingSeconds,
          tone: 'bg-danger',
          label: mmss(intervalSec - params.minRemainingSeconds),
          title: `No new entries · last ${params.minRemainingSeconds}s`,
        },
      ].filter((tick): tick is GateTick => tick !== null && tick.atSec > 0 && tick.atSec < intervalSec)
    : []
  const minuteStepSec = intervalSec > 600 ? 300 : 60
  const minuteTicks: GateTick[] = []
  for (let sec = minuteStepSec; sec < intervalSec; sec += minuteStepSec) {
    const m = Math.round(sec / 60)
    minuteTicks.push({
      atSec: sec,
      tone: 'bg-muted',
      label: mmss(sec),
      title: `Minute ${m} bucket · ${mmss(sec)}`,
    })
  }

  const ticks = [
    ...minuteTicks.filter((mTick) => !gateTicks.some((gTick) => Math.abs(gTick.atSec - mTick.atSec) < 8)),
    ...gateTicks,
  ].sort((a, b) => a.atSec - b.atSec)
  const verdictTone =
    market.verdict.action === 'enter'
      ? 'success'
      : market.verdict.action === 'snipe'
      ? 'accent'
      : market.verdict.action === 'blocked' || market.verdict.action === 'refuse'
      ? 'warning'
      : market.verdict.action === 'done'
      ? 'accent'
      : 'neutral'
  const slug = market.slug
  const eventUrl = `https://polymarket.com/event/${slug}?utm_medium=embed&utm_campaign=market&utm_content=spread-hunter`

  // 1. Microprice Lean
  let leanVal = market.lean
  let leanConf = 0.5
  if (leanVal == null) {
    const upMid =
      market.quotes.Up.ask != null && market.quotes.Up.bid != null
        ? (market.quotes.Up.ask + market.quotes.Up.bid) / 2
        : (market.quotes.Up.ask ?? market.quotes.Up.bid ?? 0.5)
    const downMid =
      market.quotes.Down.ask != null && market.quotes.Down.bid != null
        ? (market.quotes.Down.ask + market.quotes.Down.bid) / 2
        : (market.quotes.Down.ask ?? market.quotes.Down.bid ?? 0.5)
    const edge = (upMid - downMid) / 2.0
    const raw = edge * 4.0
    leanVal = Math.max(-1.0, Math.min(1.0, raw))
    const spreadDist = Math.abs(upMid + downMid - 1.0)
    leanConf = Math.max(0, Math.min(1.0, 1.0 - spreadDist * 5.0))
  }

  // 2. Cadence Fills
  const fillsCount =
    Number(market.verdict?.detail?.fills) ||
    (positions.length > 0 ? (hasUp ? 1 : 0) + (hasDown ? 1 : 0) : 0)
  const targetFills = 45

  // 3. CLOB Spread & Depth
  const upSpread =
    market.quotes.Up.ask != null && market.quotes.Up.bid != null
      ? market.quotes.Up.ask - market.quotes.Up.bid
      : null
  const downSpread =
    market.quotes.Down.ask != null && market.quotes.Down.bid != null
      ? market.quotes.Down.ask - market.quotes.Down.bid
      : null
  const clobSpread =
    upSpread != null && downSpread != null
      ? Math.min(upSpread, downSpread)
      : (upSpread ?? downSpread)

  const upDepth = ws?.up_book ? ws.up_book.bid_depth + ws.up_book.ask_depth : 0
  const downDepth = ws?.down_book ? ws.down_book.bid_depth + ws.down_book.ask_depth : 0
  const depthHint =
    upDepth > 0 || downDepth > 0
      ? `depth $${(upDepth / 1000).toFixed(1)}k / $${(downDepth / 1000).toFixed(1)}k`
      : 'best bid/ask'

  const wsLatency = getWsLatencyStatus(ws)

  return (
    <Card aria-label={`Live odds for ${slug}`} className={cx('flex flex-col p-5', wide && 'lg:col-span-2')}>
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[11px] text-faint">
          <Radio className="size-3 text-danger" aria-hidden />
          Live odds · via Polymarket
        </p>
        <div className="flex items-center gap-2">
          <span
            className={cx(
              'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-medium tabular-nums',
              wsLatency.badgeClass,
            )}
            title={`WebSocket latency: ${wsLatency.rawMs != null ? `${wsLatency.rawMs}ms` : '<40ms'}`}
          >
            <span className={cx('size-1.5 rounded-full', wsLatency.dotClass)} />
            WSS {wsLatency.label}
          </span>
          <a
            href={eventUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[11px] font-medium text-accent hover:underline"
            title="Open live market on Polymarket"
          >
            trade on Polymarket
            <ArrowUpRight className="size-3" aria-hidden />
          </a>
        </div>
      </div>
      <div className="mt-1 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-[13px] font-semibold">
            {market.interval} window
            <span className="text-[11.5px] font-normal text-faint">{clock(market.startMs)}</span>
            {hasUp && hasDown ? (
              <Badge tone="accent">holding UP & DOWN</Badge>
            ) : hasUp ? (
              <Badge tone="accent">holding Up (first leg)</Badge>
            ) : hasDown ? (
              <Badge tone="accent">holding Down (first leg)</Badge>
            ) : null}
          </h3>
          <p className="mt-0.5 truncate font-mono text-[10.5px] text-faint">{slug}</p>
        </div>
        <Badge tone={verdictTone} dot>
          {reasonLabel(market.verdict.reason)}
        </Badge>
      </div>

      <div className="mt-2 flex items-center justify-between text-[11px] text-faint">
        <span>{Math.round(progress * 100)}% elapsed</span>
        <span className="tabular-nums">{Math.max(0, Math.round(market.secondsRemaining))}s left</span>
      </div>
      <div className="relative mt-1 pb-3">
        <div className="flex h-1 overflow-hidden rounded-full bg-surface-2">
          {bands.length === 0 ? (
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-1000 ease-linear"
              style={{ width: `${Math.round(progress * 100)}%` }}
            />
          ) : (
            bands.map((band) => (
              <div key={band.key} className={cx('h-full', band.soft)} style={{ width: `${band.width}%` }}>
                <div
                  className={cx('h-full transition-[width] duration-1000 ease-linear', band.tone)}
                  style={{ width: `${band.filled}%` }}
                />
              </div>
            ))
          )}
        </div>
        {ticks.map((tick) => (
          // Clamped so an edge label cannot spill out of the card.
          <span
            key={`${tick.label}-${tick.atSec}`}
            title={tick.title}
            aria-label={tick.title}
            className="absolute top-0 -translate-x-1/2"
            style={{ left: `${Math.min(96, Math.max(4, (tick.atSec / intervalSec) * 100))}%` }}
          >
            <span className={cx('mx-auto -mt-[3px] block h-[10px] w-0.5 rounded-full', tick.tone)} />
            <span className="mt-0.5 block whitespace-nowrap text-[9px] tabular-nums tracking-wide text-faint">{tick.label}</span>
          </span>
        ))}
      </div>

      <dl className="mt-3 grid grid-cols-1 gap-x-4 gap-y-2.5 rounded-tile border border-line/50 bg-surface-2/30 p-3 sm:grid-cols-3">
        <Field
          label="Microprice Lean"
          value={
            leanVal == null || Math.abs(leanVal) < 0.02
              ? 'Neutral'
              : `${leanVal > 0 ? `+${leanVal.toFixed(2)}` : leanVal.toFixed(2)} ${leanVal > 0 ? 'Up' : 'Down'}`
          }
          hint={`${Math.round(leanConf * 100)}% conf · OB`}
        />
        <Field
          label="Cadence Fills"
          value={`${fillsCount} / ${targetFills} target`}
          hint={elapsedSec >= 240 ? 'M4 snipe' : 'M1–M3 clips'}
        />
        <Field
          label="CLOB Spread & Depth"
          value={clobSpread != null ? `${(clobSpread * 100).toFixed(1)}¢` : '—'}
          hint={depthHint}
        />
      </dl>

      <div className="mt-2.5 grid grid-cols-2 gap-2">
        {(['Up', 'Down'] as const).map((outcome) => {
          const leading = market.side === outcome
          const holding = positions.some((p) => p.side === outcome)
          return (
            <div
              key={outcome}
              className={cx(
                'rounded-tile border px-3 py-1.5',
                holding || leading ? 'border-accent/40 bg-accent-soft' : 'border-line bg-surface-2/50',
              )}
            >
              <p className="flex items-center gap-1.5 text-[11px] text-muted">
                {outcome === 'Up' ? <TrendingUp className="size-3.5" /> : <TrendingDown className="size-3.5" />}
                {outcome}
                {holding ? <span className="text-[10px] font-medium text-accent">held</span> : leading && <span className="text-[10px] text-faint">leading</span>}
              </p>
              <p className="mt-0.5 text-[12.5px] font-medium tabular-nums">
                {priceCents(market.quotes[outcome].bid)} / {priceCents(market.quotes[outcome].ask)}
              </p>
            </div>
          )
        })}
      </div>

      <OddsChart market={market} points={points} />
    </Card>
  )
}

function OddsChart({ market, points }: { market: MarketView; points: OddsPoint[] }) {
  const W = 600
  const H = 110
  const PAD_TOP = 10
  const PAD_BOTTOM = 12
  const span = Math.max(1, market.endMs - market.startMs)
  const yFor = (v: number) => PAD_TOP + (H - PAD_TOP - PAD_BOTTOM) * (1 - v)
  const xFor = (t: number) => Math.min(W, Math.max(0, ((t - market.startMs) / span) * W))
  const coords = points.map((p) => [xFor(p.t), yFor(p.v)] as const)
  const line = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const last = coords[coords.length - 1]!
  // Area between the chart line and the price-to-beat midline, split green/red by side.
  const midY = yFor(0.5)
  const priceToBeat = market.anchor ? market.anchor.value.toFixed(2) : null
  const areaMid = `${line} L${last[0].toFixed(1)},${midY.toFixed(1)} L${coords[0]![0].toFixed(1)},${midY.toFixed(1)} Z`
  const current = points[points.length - 1]?.v ?? 0.5
  const oddsColor = current >= 0.5 ? 'var(--color-success)' : 'var(--color-danger)'
  const upPct = impliedUp(market) * 100

  return (
    <div
      className="mt-2.5 flex min-h-[130px] flex-1 flex-col"
      role="img"
      aria-label={`Implied Up odds ${upPct.toFixed(0)}% this window`}
    >
      <div className="flex items-center justify-between text-[11px] text-faint">
        <span>
          Implied Up · <span className="font-semibold tabular-nums text-fg">{upPct.toFixed(0)}%</span>
        </span>
        <span>
          Down <span className="font-semibold tabular-nums text-fg">{(100 - upPct).toFixed(0)}%</span>
        </span>
      </div>
      <div className="relative mt-1 flex-1">
      <svg viewBox={`0 0 ${W} ${H}`} className="absolute inset-0 h-full w-full" preserveAspectRatio="none" aria-hidden>
        <defs>
          {/* One fill, clipped to whichever side of the price-to-beat line it is on. */}
          <clipPath id={`ptb-above-${market.slug}`}>
            <rect x={0} y={0} width={W} height={midY} />
          </clipPath>
          <clipPath id={`ptb-below-${market.slug}`}>
            <rect x={0} y={midY} width={W} height={H - midY} />
          </clipPath>
        </defs>
        {[0.25, 0.75].map((t) => (
          <line
            key={t}
            x1={0}
            x2={W}
            y1={yFor(t)}
            y2={yFor(t)}
            stroke="var(--color-line)"
            strokeDasharray="2 4"
            strokeWidth={1}
          />
        ))}
        <line x1={0} x2={W} y1={midY} y2={midY} stroke="var(--color-warning)" strokeDasharray="2 4" strokeWidth={1} />
        <text x={2} y={midY - 3} fontSize={10} fill="var(--color-warning)">
          {priceToBeat ?? '50'}
        </text>
        {coords.length > 0 && (
          <>
            <path d={areaMid} fill="var(--color-success)" fillOpacity={0.16} clipPath={`url(#ptb-above-${market.slug})`} />
            <path d={areaMid} fill="var(--color-danger)" fillOpacity={0.16} clipPath={`url(#ptb-below-${market.slug})`} />
            <path d={line} fill="none" stroke={oddsColor} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
            <circle cx={last[0]} cy={last[1]} r={4} fill={oddsColor} stroke="var(--color-surface)" strokeWidth={2} />
          </>
        )}
      </svg>
      </div>
    </div>
  )
}

function Field({
  label,
  value,
  hint,
  valueClassName,
}: {
  label: string
  value: React.ReactNode
  hint?: React.ReactNode
  valueClassName?: string
}) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-[10px] font-medium uppercase tracking-wide text-faint">{label}</dt>
      <dd className={cx('mt-0.5 truncate text-[12.5px] font-semibold tabular-nums', valueClassName ?? 'text-fg')}>
        {value}
        {hint && <span className="ml-1.5 text-[10.5px] font-normal text-faint">{hint}</span>}
      </dd>
    </div>
  )
}

function WaitingBody() {
  return (
    <div className="grid h-[230px] place-items-center">
      <div className="flex flex-col items-center gap-2 text-center">
        <Activity className="size-6 animate-pulse text-faint" aria-hidden />
        <p className="text-[13px] font-medium text-muted">Next window opening…</p>
        <p className="max-w-[320px] text-[12px] text-faint">
          The bot reattaches on its own — this switches the moment the new 5m/15m market appears.
        </p>
      </div>
    </div>
  )
}
