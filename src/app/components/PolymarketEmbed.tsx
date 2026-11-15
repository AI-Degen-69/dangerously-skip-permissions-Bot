import { Activity, ArrowUpRight, Radio } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { cn } from '@/lib/utils'
import {
  useBotConfig,
  type BotConfigView,
  type BotTrade,
  type Interval,
  type MarketView,
  type PositionView,
  type WsStatus,
} from '../lib/bot'
import { mmss } from '../lib/format'
import { reasonLabel } from '../lib/labels'
import { LiveWindowStrip } from './LiveWindowStrip'
import { OpenPositionsStrip } from './OpenPositionsStrip'
import { ProbabilityChart, type AxisTick, type OddsPoint } from './ProbabilityChart'
import { StatusDot, type StatusDotTone } from './StatusDot'

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

// Tailwind only emits class names it can see as literals, so tones map explicitly.
const TICK_BG: Record<AxisTick['tone'], string> = {
  info: 'bg-info',
  danger: 'bg-danger',
  muted: 'bg-muted',
}

type VerdictTone = 'success' | 'accent' | 'warning' | 'neutral'

const VERDICT_BADGE: Record<VerdictTone, string> = {
  success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
  accent: 'border-primary/30 bg-primary/10 text-primary',
  warning: 'border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400',
  neutral: 'border-border bg-muted/60 text-muted-foreground',
}

const VERDICT_DOT_TONE: Record<VerdictTone, StatusDotTone> = {
  success: 'live',
  accent: 'stopped',
  warning: 'warning',
  neutral: 'stopped',
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

const clock = (ms: number) =>
  new Date(ms).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })

export function PolymarketLiveChart({
  markets,
  positions = [],
  ws,
  trades = [],
}: {
  markets: MarketView[]
  positions?: PositionView[]
  ws?: WsStatus
  /** Every fill in the run; each chart draws only its own window's. */
  trades?: BotTrade[]
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
        <Card className="gap-0 p-5 lg:col-span-2">
          <WaitingBody />
        </Card>
      ) : (
        activeMarkets.map((market) => (
          <MarketChartPanel
            key={market.slug}
            market={market}
            positions={positions.filter((p) => p.slug === market.slug)}
            params={config?.config.intervalParams[market.interval] ?? null}
            pairCostCap={config?.config.entry.maxPairCost}
            wide={activeMarkets.length === 1}
            ws={ws}
            trades={trades}
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
  pairCostCap,
  wide = false,
  ws,
  trades = [],
}: {
  market: MarketView
  positions?: PositionView[]
  params: BotConfigView['intervalParams'][Interval] | null
  pairCostCap?: number
  wide?: boolean
  ws?: WsStatus
  trades?: BotTrade[]
}) {
  const points = useOddsSeries(market)
  // Each fill becomes a marker at the moment and price it filled.
  const fills = trades
    .filter((t) => t.slug === market.slug && t.kind !== 'settle' && t.side && t.price != null)
    .map((t) => ({ side: t.side!, price: t.price!, atMs: Number(t.ts), shares: t.shares ?? 0 }))
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
  const gateCandidates: (AxisTick | null)[] = params
    ? [
        {
          atSec: params.observationSeconds,
          tone: 'info',
          label: mmss(params.observationSeconds),
          title: `Observation window ends · direction must then hold ${params.minDirectionHoldSeconds}s`,
        },
        position && params.stallSeconds > 0
          ? {
              atSec: (position.entryAtMs - market.startMs) / 1000 + params.stallSeconds,
              tone: 'danger',
              label: mmss((position.entryAtMs - market.startMs) / 1000 + params.stallSeconds),
              title: `Stall exit · ${params.stallSeconds}s without movement`,
            }
          : null,
        {
          atSec: intervalSec - params.minRemainingSeconds,
          tone: 'danger',
          label: mmss(intervalSec - params.minRemainingSeconds),
          title: `No new entries · last ${params.minRemainingSeconds}s`,
        },
      ]
    : []
  const gateTicks = gateCandidates.filter(
    (tick): tick is AxisTick => tick !== null && tick.atSec > 0 && tick.atSec < intervalSec,
  )
  const minuteStepSec = intervalSec > 600 ? 300 : 60
  const minuteTicks: AxisTick[] = []
  for (let sec = minuteStepSec; sec < intervalSec; sec += minuteStepSec) {
    const m = Math.round(sec / 60)
    minuteTicks.push({
      atSec: sec,
      tone: 'muted',
      label: mmss(sec),
      title: `Minute ${m} bucket · ${mmss(sec)}`,
    })
  }

  const ticks = [
    ...minuteTicks.filter((mTick) => !gateTicks.some((gTick) => Math.abs(gTick.atSec - mTick.atSec) < 8)),
    ...gateTicks,
  ].sort((a, b) => a.atSec - b.atSec)
  const verdictTone: VerdictTone =
    market.verdict.action === 'enter'
      ? 'success'
      : market.verdict.action === 'snipe' || market.verdict.action === 'done'
        ? 'accent'
        : market.verdict.action === 'blocked' || market.verdict.action === 'refuse'
          ? 'warning'
          : 'neutral'
  const slug = market.slug
  const eventUrl = `https://polymarket.com/event/${slug}?utm_medium=embed&utm_campaign=market&utm_content=spread-hunter`

  return (
    <Card aria-label={`Live odds for ${slug}`} className={cn('gap-0 p-5', wide && 'lg:col-span-2')}>
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Radio className="size-3 text-rose-500" aria-hidden />
          Live odds · via Polymarket
        </p>
        <div className="flex items-center gap-2">
          <a
            href={eventUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
            title="Open live market on Polymarket"
          >
            trade on Polymarket
            <ArrowUpRight className="size-3" aria-hidden />
          </a>
        </div>
      </div>

      <div className="mt-1 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            {market.interval} window
            <span className="font-mono text-xs font-normal text-muted-foreground tabular-nums">
              {clock(market.startMs)}
            </span>
            {hasUp && hasDown ? (
              <Badge variant="outline" className="border-primary/30 bg-primary/10 text-primary">
                holding UP &amp; DOWN
              </Badge>
            ) : hasUp ? (
              <Badge variant="outline" className="border-primary/30 bg-primary/10 text-primary">
                holding Up (first leg)
              </Badge>
            ) : hasDown ? (
              <Badge variant="outline" className="border-primary/30 bg-primary/10 text-primary">
                holding Down (first leg)
              </Badge>
            ) : null}
          </h3>
          <p className="mt-0.5 truncate font-mono text-[10.5px] text-muted-foreground">{slug}</p>
        </div>
        <Badge variant="outline" className={VERDICT_BADGE[verdictTone]}>
          <StatusDot tone={VERDICT_DOT_TONE[verdictTone]} blink={verdictTone === 'success'} size="xs" />
          {reasonLabel(market.verdict.reason)}
        </Badge>
      </div>

      <ProbabilityChart market={market} points={points} ticks={ticks} fills={fills} />

      <div className="mt-3 flex flex-col gap-2">
        <LiveWindowStrip markets={[market]} ws={ws} pairCostCap={pairCostCap} />
        <OpenPositionsStrip positions={positions} pairCostCap={pairCostCap} />
      </div>

      <div className="mt-3 flex items-center justify-between text-[11px] text-muted-foreground">
        <span className="tabular-nums">{Math.round(progress * 100)}% elapsed</span>
        <span className="font-mono tabular-nums">{Math.max(0, Math.round(market.secondsRemaining))}s left</span>
      </div>
      <div className="relative mt-1 pb-3">
        <div className="flex h-1 overflow-hidden rounded-full bg-muted">
          {bands.length === 0 ? (
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-1000 ease-linear"
              style={{ width: `${Math.round(progress * 100)}%` }}
            />
          ) : (
            bands.map((band) => (
              <div key={band.key} className={cn('h-full', band.soft)} style={{ width: `${band.width}%` }}>
                <div
                  className={cn('h-full transition-[width] duration-1000 ease-linear', band.tone)}
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
            <span className={cn('mx-auto -mt-[3px] block h-[10px] w-0.5 rounded-full', TICK_BG[tick.tone])} />
            <span className="mt-0.5 block font-mono text-[9px] tracking-wide whitespace-nowrap text-muted-foreground tabular-nums">
              {tick.label}
            </span>
          </span>
        ))}
      </div>
    </Card>
  )
}

function WaitingBody() {
  return (
    <Empty className="h-[230px] p-6">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Activity className="size-5 animate-pulse" aria-hidden />
        </EmptyMedia>
        <EmptyTitle>Next window opening…</EmptyTitle>
        <EmptyDescription>
          The bot reattaches on its own — this switches the moment the new 5m/15m market appears.
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}
