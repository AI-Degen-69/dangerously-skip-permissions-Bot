import { Activity, ArrowUpRight, Radio } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import { useBotConfig, type BotConfigView, type Interval, type MarketView, type PositionView, type WsStatus } from '../lib/bot'
import { cx } from '../lib/cx'
import { reasonLabel } from '../lib/labels'
import { Badge, Card } from './ui'
import { LiveWindowStrip } from './LiveWindowStrip'
import { OpenPositionsStrip } from './OpenPositionsStrip'

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

  // 2. Window Fills
  const fillsCount =
    Number(market.verdict?.detail?.fills) ||
    (positions.length > 0 ? (hasUp ? 1 : 0) + (hasDown ? 1 : 0) : 0)

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

  return (
    <Card aria-label={`Live odds for ${slug}`} className={cx('flex flex-col p-5', wide && 'lg:col-span-2')}>
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[11px] text-faint">
          <Radio className="size-3 text-danger" aria-hidden />
          Live odds · via Polymarket
        </p>
        <div className="flex items-center gap-2">
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

      <ProbabilityChart market={market} points={points} />

      <div className="mt-3 space-y-2">
        <LiveWindowStrip markets={[market]} ws={ws} />
        <OpenPositionsStrip positions={positions} />
      </div>

      <div className="mt-3 flex items-center justify-between text-[11px] text-faint">
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
          label="Window Fills"
          value={`${fillsCount} fills`}
          hint={elapsedSec >= 240 ? 'M4 snipe' : 'tape med: 45'}
        />
        <Field
          label="CLOB Spread & Depth"
          value={clobSpread != null ? `${(clobSpread * 100).toFixed(1)}¢` : '—'}
          hint={depthHint}
        />
      </dl>
    </Card>
  )
}

// Live probability trajectory: implied Up odds sampled across the window.
// The chart is measured so SVG units equal CSS pixels — strokes and markers
// stay crisp and undistorted at any card width.
const CHART_MIN_H = 110
const CHART_MAX_H = 190
const Y_AXIS_GUTTER = 32
const UP_COLOR = '#22c55e'
const DOWN_COLOR = '#f87171'

function ProbabilityChart({ market, points }: { market: MarketView; points: OddsPoint[] }) {
  const [hoverT, setHoverT] = useState<number | null>(null)
  const [box, setBox] = useState({ w: 640, h: 150 })
  const surfaceRef = useRef<HTMLDivElement>(null)

  // Measure the surface so SVG units equal CSS pixels. ResizeObserver alone is
  // not enough: it stays silent in a background tab, so the width is also read
  // directly on mount and on window resize.
  const measure = useCallback(() => {
    const el = surfaceRef.current
    if (!el) return
    const w = Math.round(el.getBoundingClientRect().width)
    if (w <= 0) return
    const h = Math.round(Math.min(CHART_MAX_H, Math.max(CHART_MIN_H, w / 4.5)))
    setBox((prev) => (prev.w === w && prev.h === h ? prev : { w, h }))
  }, [])

  useLayoutEffect(() => {
    measure()
    const el = surfaceRef.current
    if (!el) return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    window.addEventListener('resize', measure)
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [measure])
  const span = Math.max(1, market.endMs - market.startMs)
  const padTop = 10
  const padBottom = 10
  const floor = box.h - padBottom
  // Right gutter holds the y-axis labels; the plot uses the rest.
  const plotW = Math.max(40, box.w - Y_AXIS_GUTTER)
  const xFor = (t: number) => ((t - market.startMs) / span) * plotW
  const yFor = (v: number) => padTop + (floor - padTop) * (1 - v)

  const coords = points.map((p) => ({ t: p.t, v: p.v, x: xFor(p.t), y: yFor(p.v) }))
  const current = coords.length > 0 ? coords[coords.length - 1]!.v : 0.5
  const isUp = current >= 0.5
  const color = isUp ? UP_COLOR : DOWN_COLOR
  const parityY = yFor(0.5)
  const last = coords[coords.length - 1]

  const line = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ')
  // Area spans the curve down to the 50¢ baseline; the clip below splits it green/red by side.
  const area = coords.length > 1 ? `${line} L${last!.x.toFixed(1)},${parityY} L${coords[0]!.x.toFixed(1)},${parityY} Z` : ''

  let hovered: (typeof coords)[number] | null = null
  if (hoverT != null && coords.length > 0) {
    hovered = coords.reduce((best, c) => (Math.abs(c.t - hoverT) < Math.abs(best.t - hoverT) ? c : best))
  }

  const handleMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const rect = surfaceRef.current?.getBoundingClientRect()
    if (!rect || rect.width === 0 || coords.length === 0) return
    const plotX = Math.min(plotW, Math.max(0, e.clientX - rect.left))
    setHoverT(market.startMs + (plotX / plotW) * span)
  }

  // Tooltip stays inside the chart box at both edges.
  const tipLeft = hovered ? Math.min(Math.max(hovered.x, 52), Math.max(52, plotW - 20)) : 0
  const tipTop = hovered ? Math.min(Math.max(hovered.y - 10, 22), Math.max(22, box.h - 6)) : 0

  return (
    <div className="relative mt-2.5 overflow-hidden rounded-tile border border-line bg-surface-2/30 p-3">
      <div className="relative flex items-center justify-between gap-2">
        <p className="text-[10px] font-medium uppercase tracking-wide text-faint">Live probability trajectory</p>
        <Badge tone={isUp ? 'success' : 'danger'} className="font-mono text-[11px]">
          {isUp ? 'UP' : 'DN'} {Math.round(current * 100)}¢
        </Badge>
      </div>

      <div
        ref={surfaceRef}
        className="relative mt-2 w-full select-none"
        style={{ height: box.h }}
        onPointerMove={handleMove}
        onPointerLeave={() => setHoverT(null)}
      >
        <svg
          viewBox={`0 0 ${box.w} ${box.h}`}
          className="h-full w-full"
          role="img"
          aria-label={`Live probability trajectory · Up ${Math.round(current * 100)}¢`}
        >
          <defs>
            <linearGradient id={`prob-up-${market.slug}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={UP_COLOR} stopOpacity="0.34" />
              <stop offset="100%" stopColor={UP_COLOR} stopOpacity="0.02" />
            </linearGradient>
            <linearGradient id={`prob-down-${market.slug}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={DOWN_COLOR} stopOpacity="0.02" />
              <stop offset="100%" stopColor={DOWN_COLOR} stopOpacity="0.34" />
            </linearGradient>
            <filter id={`prob-glow-${market.slug}`} x="-10%" y="-40%" width="120%" height="180%">
              <feGaussianBlur stdDeviation="6" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <clipPath id={`prob-above-${market.slug}`}>
              <rect x={0} y={0} width={plotW} height={parityY} />
            </clipPath>
            <clipPath id={`prob-below-${market.slug}`}>
              <rect x={0} y={parityY} width={plotW} height={box.h - parityY} />
            </clipPath>
          </defs>

          {[0, 0.25, 0.75, 1].map((v) => (
            <line key={v} x1={0} x2={plotW} y1={yFor(v)} y2={yFor(v)} stroke="var(--color-line)" strokeDasharray="2 4" strokeWidth={1} />
          ))}
          {/* 50¢ parity line */}
          <line x1={0} x2={plotW} y1={parityY} y2={parityY} stroke="var(--color-warning)" strokeDasharray="4 4" strokeWidth={1} />

          {/* Y axis */}
          {[
            { v: 1, label: '100¢' },
            { v: 0.75, label: '75¢' },
            { v: 0.5, label: '50¢' },
            { v: 0.25, label: '25¢' },
            { v: 0, label: '0¢' },
          ].map((tick) => (
            <text
              key={tick.label}
              x={plotW + 6}
              y={yFor(tick.v) + 3.5}
              fontSize={9.5}
              fontWeight={tick.v === 0.5 ? 600 : 400}
              fill={tick.v === 0.5 ? 'var(--color-warning)' : 'var(--color-faint)'}
              className="font-mono"
            >
              {tick.label}
            </text>
          ))}

          {area && (
            <>
              <path d={area} fill={`url(#prob-up-${market.slug})`} clipPath={`url(#prob-above-${market.slug})`} />
              <path d={area} fill={`url(#prob-down-${market.slug})`} clipPath={`url(#prob-below-${market.slug})`} />
            </>
          )}
          {line && (
            <path
              d={line}
              fill="none"
              stroke={color}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              filter={`url(#prob-glow-${market.slug})`}
            />
          )}
          {last && (
            <g>
              {/* Blinking halo on the live edge of the curve. */}
              <circle cx={last.x} cy={last.y} r={7} fill={color} opacity={0.25} className="animate-pulse" />
              <circle cx={last.x} cy={last.y} r={3.5} fill={color} stroke="var(--color-surface)" strokeWidth={2} />
            </g>
          )}

          {hovered && (
            <g pointerEvents="none">
              <line
                x1={hovered.x}
                x2={hovered.x}
                y1={padTop}
                y2={floor}
                stroke="var(--color-fg)"
                strokeDasharray="3 3"
                strokeWidth={1}
                opacity={0.45}
              />
              <circle cx={hovered.x} cy={hovered.y} r={5} fill={color} stroke="var(--color-surface)" strokeWidth={2} />
            </g>
          )}
        </svg>

        {hovered && (
          <div
            className="pointer-events-none absolute z-20 -translate-x-1/2 -translate-y-full rounded border border-line bg-surface-2 px-2 py-1 font-mono text-[11px] text-fg shadow-pop"
            style={{ left: tipLeft, top: tipTop }}
          >
            {Math.round(hovered.v * 100)}¢
            <span className="ml-1 text-faint">{mmss((hovered.t - market.startMs) / 1000)}</span>
          </div>
        )}
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
