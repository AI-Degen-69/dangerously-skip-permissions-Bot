import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Award,
  Ban,
  BarChart3,
  CalendarClock,
  CheckCircle2,
  Clock,
  Crown,
  FileText,
  Gauge,
  Gem,
  GitBranch,
  GitMerge,
  Info,
  Layers,
  LayoutDashboard,
  Medal,
  Percent,
  Receipt,
  RotateCcw,
  Scale,
  Shield,
  ShieldCheck,
  Sparkles,
  Target,
  TrendingUp,
  Trophy,
  Wallet,
  type LucideIcon,
} from 'lucide-react'
import { Link } from 'react-router'
import { useState, type ReactNode } from 'react'

import { PageHeader, useToast } from '../components/ui'
import { BotControlTile } from '../components/BotControlTile'
import { InteractivePnlChart } from '../components/InteractivePnlChart'
import { StatusDot, type StatusDotTone } from '../components/StatusDot'
import { BOT_ORIGIN, useBotControl, useBotPerf, useRedeemBot, useStrategySetups, mergeStrategySetups } from '../lib/bot'
import { STRATEGY_PRESETS } from '../botDefaults'
import type { BotPerf, PerfCell, PerfWindow, StrategySetup, WindowFidelity } from '../lib/bot'
import { computeKpiStats } from '../lib/kpiStats'
import { ACCOUNT_TIERS, useAccountTier, useIncludeRebates, windowRebate } from '../lib/rebates'
import type { AccountTier } from '../lib/rebates'
import { TIMEFRAMES, scopeWindows, timeframeStart } from '../lib/timeframes'
import { verifiedWindow } from '../lib/verified'
import { useStoredFlag } from '../lib/flags'
import { cx } from '../lib/cx'
import { money2 } from '../lib/format'
import { Badge as ShadcnBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

type BadgeTone = 'neutral' | 'accent' | 'info' | 'success' | 'warning' | 'danger'

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: 'border-border bg-muted/50 text-muted-foreground',
  accent: 'border-primary/30 bg-primary/10 text-primary',
  info: 'border-sky-500/30 bg-sky-500/10 text-sky-600 dark:text-sky-400',
  success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
  warning: 'border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400',
  danger: 'border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-400',
}

const BADGE_DOT_TONES: Record<BadgeTone, StatusDotTone> = {
  neutral: 'stopped',
  accent: 'stopped',
  info: 'stopped',
  success: 'live',
  warning: 'warning',
  danger: 'danger',
}

function Badge({
  tone = 'neutral',
  dot,
  live = false,
  className,
  children,
}: {
  tone?: BadgeTone
  dot?: boolean
  live?: boolean
  className?: string
  children: ReactNode
}) {
  return (
    <ShadcnBadge variant="outline" className={cn('gap-1.5', BADGE_TONES[tone], className)}>
      {dot && <StatusDot tone={BADGE_DOT_TONES[tone]} blink={live} size="xs" />}
      {children}
    </ShadcnBadge>
  )
}

function EmptyState({ icon, title, description }: { icon: ReactNode; title: string; description?: string }) {
  return (
    <Empty className="py-10">
      <EmptyHeader>
        <EmptyMedia variant="icon">{icon}</EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        {description && <EmptyDescription>{description}</EmptyDescription>}
      </EmptyHeader>
    </Empty>
  )
}

const usd = money2
const share = (value: number) => `${Math.round(value * 100)}%`
const windowTime = (ms: number) =>
  new Date(ms).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })

/**
 * The same slice judged by what a real resting bid could have got: a maker fill
 * only counts when taker selling at its limit outlasted the queue ahead of it.
 * Windows the auditor could not read carry no fidelity and drop out of both
 * sides, so the number never mixes judged and unjudged windows.
 */
function attainableOf(windows: PerfWindow[]) {
  const audited = windows.filter((window) => window.fidelity)
  const sum = (pick: (f: WindowFidelity) => number) =>
    audited.reduce((total, window) => total + (window.fidelity ? pick(window.fidelity) : 0), 0)
  return {
    windows: audited.length,
    // Pre-rebate, so it is directly comparable with the attainable net.
    paperNetUsd: audited.reduce((total, window) => total + (window.netUsd ?? 0), 0),
    netUsd: sum((f) => f.attainableNetUsd),
    makerFills: sum((f) => f.makerFills),
    attainableFills: sum((f) => f.attainableFills),
    phantomFills: sum((f) => f.phantomFills),
  }
}

const CELL_TONE: Record<PerfCell['status'], string> = {
  pass: 'text-success',
  warn: 'text-warning',
  fail: 'text-danger',
  stat: 'text-fg',
}

// Balanced 4x3 execution-health layout: activity & volume, fill breakdown &
// pairing, then coverage & execution quality. Unknown keys sink to the end.
const EXEC_HEALTH_ORDER = [
  'windows',
  'orders',
  'totalShares',
  'perWindow',
  'fillsUp',
  'fillsDown',
  'paired',
  'unpaired',
  'single',
  'bothSides',
  'attainable',
  'zeroPrice',
]
const EXEC_HEALTH_ICONS: Record<string, LucideIcon> = {
  windows: CalendarClock,
  orders: FileText,
  totalShares: Layers,
  perWindow: Gauge,
  fillsUp: ArrowUpRight,
  fillsDown: ArrowDownRight,
  paired: GitMerge,
  unpaired: GitBranch,
  single: AlertTriangle,
  bothSides: CheckCircle2,
  attainable: ShieldCheck,
  zeroPrice: Ban,
}

// One colour class per element: `text-fg` is emitted after `text-danger` in the
// stylesheet, so mixing them leaves the value white instead of red.
type Tone = 'success' | 'danger' | 'warning' | 'neutral'
const TONE_TEXT: Record<Tone, string> = {
  success: 'text-success',
  danger: 'text-danger',
  warning: 'text-warning',
  neutral: 'text-fg',
}

const drawdownTone = (pct: number): 'success' | 'warning' | 'danger' =>
  pct <= 15 ? 'success' : pct <= 30 ? 'warning' : 'danger'

export function Dashboard() {
  const perf = useBotPerf()
  const control = useBotControl()
  const redeem = useRedeemBot()
  const toast = useToast()
  const [hoveredSlug, setHoveredSlug] = useState<string | null>(null)
  const [tier, setTier] = useAccountTier()
  const [includeRebates, setIncludeRebates] = useIncludeRebates()
  const [verifiedOnly, setVerifiedOnly] = useStoredFlag('verifiedOnly', false)
  const [timeframeId, setTimeframeId] = useState<string>('all')

  const isViewOnly = control.data?.isViewOnly ?? false

  const data = perf.data
  const summary = data?.summary
  const health = data?.health
  const windows = data?.windows ?? []
  // Verified Only: every window carries the numbers its verified fills make,
  // and a window without a verified fill drops out of the view entirely.
  const effective = verifiedOnly
    ? windows.map(verifiedWindow).filter((window): window is PerfWindow => window !== null)
    : windows
  const settled = effective.filter((window) => !window.pending)
  const startingCapital = data?.summary?.bankrollUsd ?? 1000

  // The timeframe scopes the whole page: the KPI cards, the chart, the bars and
  // the window log all read the same slice, so they can never disagree.
  const timeframe = TIMEFRAMES.find((tf) => tf.id === timeframeId) ?? TIMEFRAMES[TIMEFRAMES.length - 1]
  const cutoff = timeframeStart(timeframe, Date.now())
  const scoped = scopeWindows(settled, cutoff, tier.rate, includeRebates, startingCapital)
  // Capital at the start of the slice, so the curve starts where the account was.
  const baseCapital = scoped.baseCapital
  // The window log shows the same slice, pending windows included.
  const scopedLog = effective.filter((window) => window.startMs >= cutoff)
  // The same slice as the tape recorded it, for the corroboration readout.
  const scopedTape = windows.filter((window) => window.startMs >= cutoff)

  // Credit the rebate per window so the chart, the bars and the window log agree
  // with the KPI cards above them.
  const withRebates = (window: PerfWindow): PerfWindow =>
    window.netUsd == null
      ? window
      : {
          ...window,
          netUsd: window.netUsd + (includeRebates ? windowRebate(window, tier.rate) : 0),
        }
  // The API summary covers the whole run, so it can only back an all-time view
  // of every fill.
  const stats = computeKpiStats(
    scoped.windows,
    baseCapital,
    timeframe.ms == null && !verifiedOnly ? summary : undefined,
    tier.rate,
    includeRebates,
  )
  const currentCapital = stats.currentCapital
  const attainable = attainableOf(scoped.windows)
  // Segment widths for the win/loss bar, so the tick labels above it land on
  // the slice they belong to.
  const winPct = Math.max(stats.winsCount > 0 ? 2 : 0, stats.winRate * 100)
  const scratchPct = stats.scratchCount > 0 ? (stats.scratchCount / (stats.settled || 1)) * 100 : 0
  const upFillPct = (stats.upFills / Math.max(1, stats.upFills + stats.downFills)) * 100
  const setupsQuery = useStrategySetups()
  const allSetups = mergeStrategySetups(setupsQuery.data?.setups, STRATEGY_PRESETS as unknown as Record<string, StrategySetup>)
  const activeId = data?.strategy?.id ?? control.data?.strategy?.id ?? setupsQuery.data?.activeSetupId
  const activeSetup = allSetups.find((s) => s.id === activeId) ?? allSetups[0]
  const strategySymbol = data?.strategy?.symbol ?? control.data?.strategy?.symbol ?? activeSetup?.symbol ?? '—'

  return (
    <div className="mx-auto max-w-[1200px] p-5 sm:p-8">
      <PageHeader
        icon={<LayoutDashboard className="size-5" />}
        title={`${control.data?.mode === 'live' ? 'Real desk' : 'Paper desk'} · ${strategySymbol}`}
      />

      <BotControlTile health={health} />

      {perf.isError && (
        <Card className="mt-4 gap-0 p-5">
          <div className="flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400">
              <Activity className="size-4.5" />
            </span>
            <div>
              <p className="text-[13.5px] font-medium">Bot API not reachable</p>
              <p className="mt-0.5 text-[12.5px] text-muted-foreground">
                Nothing answered at {BOT_ORIGIN}. Start it with <code className="font-mono">python bot/api.py</code>; this
                page refills on its own.
              </p>
            </div>
          </div>
        </Card>
      )}

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {!summary ? (
          Array.from({ length: 5 }).map((_, index) => <Skeleton key={index} className="h-[116px] rounded-3xl" />)
        ) : (
          <>
            <Stat
              label="Net P&amp;L"
              value={`${stats.netUsd >= 0 ? '+' : ''}${usd(stats.netUsd)}`}
              hint={
                <>
                  <span className={stats.capitalReturnPct >= 0 ? 'text-success' : 'text-danger'}>
                    {stats.capitalReturnPct >= 0 ? '+' : ''}
                    {stats.capitalReturnPct.toFixed(1)}% capital
                  </span>
                  {' · '}
                  <span className={stats.roiPct >= 0 ? 'text-success' : 'text-danger'}>{stats.roiPct.toFixed(1)}% ROI</span>
                </>
              }
              hintText={`${stats.capitalReturnPct >= 0 ? '+' : ''}${stats.capitalReturnPct.toFixed(1)}% capital · ${stats.roiPct.toFixed(1)}% ROI`}
              tone={stats.netUsd >= 0 ? 'success' : 'danger'}
              badge={
                <Badge tone={stats.netUsd >= 0 ? 'success' : 'danger'}>
                  {stats.netUsd >= 0 ? 'Profitable' : 'Loss'}
                </Badge>
              }
              tip={`Total realized paper profit/loss across settled windows${
                timeframe.ms == null ? '' : ` in the last ${timeframe.label}`
              } vs starting capital.${
                verifiedOnly
                  ? ' Verified fills only — the fills the tape corroborates against real prints. The fills the market never traded and the taker fills paper mode cannot check drop out, so read it as a lower bound.'
                  : ''
              }`}
              icon={<TrendingUp className="size-3.5" />}
            />
            <Stat
              label="Win Rate"
              value={`${(stats.winRate * 100).toFixed(1)}%`}
              hint={
                <>
                  <span className="text-success">{stats.winsCount}W</span>
                  {' – '}
                  <span className="text-danger">{stats.lossesCount}L</span>
                  {` (${stats.settled} settled)`}
                </>
              }
              hintText={`${stats.winsCount}W – ${stats.lossesCount}L (${stats.settled} settled)`}
              tone={stats.winRate >= 0.5 ? 'success' : 'danger'}
              badge={
                stats.edgePct !== null ? (
                  <Badge tone={stats.edgePct >= 0 ? 'success' : 'warning'}>
                    {stats.edgePct >= 0 ? `+${stats.edgePct.toFixed(1)}% edge` : `${stats.edgePct.toFixed(1)}% edge`}
                  </Badge>
                ) : (
                  <Badge tone="neutral">No edge data</Badge>
                )
              }
              tip="Percentage of settled windows closing positive. Edge reflects surplus over the break-even required win rate."
              icon={<Percent className="size-3.5" />}
            />
            <Stat
              label="Expectancy"
              value={`${stats.expectancyUsd >= 0 ? '+' : ''}${usd(stats.expectancyUsd)}`}
              unit="/ window"
              hint={
                <>
                  {`Avg Win `}
                  <span className="text-success">+{usd(Math.abs(stats.avgWinUsd))}</span>
                  {' · Loss '}
                  <span className="text-danger">-{usd(Math.abs(stats.avgLossUsd))}</span>
                </>
              }
              hintText={`Avg Win +${usd(Math.abs(stats.avgWinUsd))} · Loss -${usd(Math.abs(stats.avgLossUsd))}`}
              tone={stats.expectancyUsd >= 0 ? 'success' : 'danger'}
              badge={
                <Badge tone={stats.expectancyRatio >= 0 ? 'success' : 'danger'} className="font-mono text-[10.5px]">
                  {stats.expectancyRatio >= 0 ? '+' : ''}
                  {stats.expectancyRatio.toFixed(2)}R EV
                </Badge>
              }
              tip="Expected dollar and R-multiple gain per 5-minute window: (Win Rate × Avg Win) - (Loss Rate × Avg Loss)."
              icon={<Target className="size-3.5" />}
            />
            <Stat
              label="Profit Factor"
              value={stats.grossLossUsd === 0 && stats.grossProfitUsd > 0 ? '∞' : stats.profitFactor.toFixed(2)}
              hint={
                <>
                  {`Gross: `}
                  <span className="text-success">+{usd(Math.abs(stats.grossProfitUsd))}</span>
                  {' / '}
                  <span className="text-danger">-{usd(Math.abs(stats.grossLossUsd))}</span>
                </>
              }
              hintText={`Gross: +${usd(Math.abs(stats.grossProfitUsd))} / -${usd(Math.abs(stats.grossLossUsd))}`}
              tone={stats.profitFactor >= 1.5 ? 'success' : stats.profitFactor >= 1.0 ? 'warning' : 'danger'}
              badge={
                <Badge
                  tone={stats.payoffRatio >= 1 ? 'success' : stats.payoffRatio >= 0.5 ? 'warning' : 'danger'}
                  className="font-mono text-[10.5px]"
                >
                  Payoff {stats.lossesCount === 0 && stats.winsCount > 0 ? '∞' : `${stats.payoffRatio.toFixed(2)}x`}
                </Badge>
              }
              tip="Total profit from winning windows divided by total loss from losing windows. >1.0 means profitable, >1.5 is strong quant tier."
              icon={<Scale className="size-3.5" />}
            />
            <Stat
              label="Sharpe Ratio"
              value={stats.sharpeRatio.toFixed(2)}
              unit="Ann."
              hint={
                <>
                  {`Sortino: `}
                  <span
                    className={
                      stats.lossesCount === 0 && stats.settled > 0 && stats.netUsd > 0
                        ? 'text-success'
                        : stats.sortinoRatio >= 0
                          ? 'text-success'
                          : 'text-danger'
                    }
                  >
                    {stats.lossesCount === 0 && stats.settled > 0 && stats.netUsd > 0 ? '∞' : stats.sortinoRatio.toFixed(2)}
                  </span>
                  {' · Max DD: '}
                  <span className={TONE_TEXT[drawdownTone(stats.maxDrawdownPct)]}>-{stats.maxDrawdownPct.toFixed(1)}%</span>
                </>
              }
              hintText={`Sortino: ${stats.lossesCount === 0 && stats.settled > 0 && stats.netUsd > 0 ? '∞' : stats.sortinoRatio.toFixed(2)} · Max DD: -${stats.maxDrawdownPct.toFixed(1)}%`}
              tone={stats.sharpeRatio >= 1.0 ? 'success' : stats.sharpeRatio >= 0 ? 'neutral' : 'danger'}
              badge={
                <Badge tone={drawdownTone(stats.maxDrawdownPct)}>
                  DD {stats.maxDrawdownPct.toFixed(1)}%
                </Badge>
              }
              tip="Annualized risk-adjusted return ratio measuring return per unit of volatility over 105,120 5m-periods/year."
              icon={<Activity className="size-3.5" />}
            />
          </>
        )}
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <Card className="gap-0 p-5 lg:col-span-2">
          {summary && (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="tabular-nums text-[22px] font-semibold tracking-[-0.02em] text-fg">
                  {usd(currentCapital)}
                </span>
                <span
                  className={cx(
                    'tabular-nums text-[13.5px] font-semibold',
                    stats.netUsd >= 0 ? 'text-success' : 'text-danger',
                  )}
                >
                  {stats.netUsd >= 0 ? '+' : ''}
                  {usd(stats.netUsd)}
                  {baseCapital > 0
                    ? ` (${(((currentCapital - baseCapital) / baseCapital) * 100).toFixed(1)}%)`
                    : ''}
                </span>
                {timeframe.ms != null && (
                  <Badge tone="neutral" className="text-[11px]">
                    {timeframe.label}
                  </Badge>
                )}
                {!includeRebates && (
                  <Badge tone="warning" className="text-[11px]">
                    no rebates
                  </Badge>
                )}
                <span className="text-[11.5px] text-faint">
                  {stats.settled}w · {stats.winsCount}W
                </span>
              </div>

              <div className="ml-auto flex flex-wrap items-center gap-2.5">
                <CorroborationBadge
                  windows={scopedTape}
                  attainable={attainable}
                  totalScopedWindows={scoped.windows.length}
                  verifiedOnly={verifiedOnly}
                />
                <Toggle
                  label="Verified Only"
                  on={verifiedOnly}
                  onToggle={() => setVerifiedOnly(!verifiedOnly)}
                  title={
                    verifiedOnly
                      ? 'Counting only the fills the tape corroborates. Click to count every fill.'
                      : 'Counting every fill. Click to count only the fills the tape corroborates.'
                  }
                />
              </div>
            </div>
          )}

          {scoped.windows.length > 0 ? (
            <>
              <div className="mt-3 rounded-xl border border-line bg-surface-2/20 p-3">
                <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wider text-faint">
                    <TrendingUp className="size-3.5 text-primary" />
                    Equity curve
                  </span>
                  <TimeframePicker value={timeframeId} onChange={setTimeframeId} />
                </div>
                <InteractivePnlChart
                  windows={scoped.windows.map(withRebates)}
                  startingCapital={baseCapital}
                  baseLabel={timeframe.ms == null ? undefined : 'Base capital'}
                  hoveredSlug={hoveredSlug}
                  onHoverWindow={(w) => setHoveredSlug(w?.slug ?? null)}
                />
              </div>
              <div className="mt-3 rounded-xl border border-line bg-surface-2/20 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-muted">
                  <span className="flex items-center gap-1.5 font-medium text-fg">
                    <BarChart3 className="size-3.5 text-primary" />
                    Last {Math.min(scoped.windows.length, 24)} Windows
                  </span>
                  <span className="font-mono text-[11.5px] tabular-nums text-faint">
                    Best{' '}
                    <span className="text-success">
                      {stats.bestUsd > 0 ? `+${usd(stats.bestUsd)}` : usd(stats.bestUsd)}
                    </span>
                    {' · '}
                    Worst{' '}
                    <span className="text-danger">{usd(stats.worstUsd)}</span>
                    {' · '}
                    Average{' '}
                    <span className={stats.expectancyUsd >= 0 ? 'text-success' : 'text-danger'}>
                      {stats.expectancyUsd > 0 ? `+${usd(stats.expectancyUsd)}` : usd(stats.expectancyUsd)}
                    </span>
                  </span>
                </div>
                <WindowBars
                  windows={scoped.windows.slice(-24).map(withRebates)}
                  hoveredSlug={hoveredSlug}
                  onHoverSlug={setHoveredSlug}
                />
              </div>
            </>
          ) : (
            <div className="mt-3">
              <EmptyState
                icon={<Target />}
                title={settled.length > 0 ? 'No settled windows in this timeframe' : 'No settled windows yet'}
                description={
                  settled.length > 0
                    ? 'Widen the timeframe above to see older windows.'
                    : 'The first window settles about five minutes after the loop opens it. Everything here fills in on its own.'
                }
              />
            </div>
          )}
        </Card>

        <Card className="flex flex-col justify-between gap-0 p-5">
          <div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="grid size-8 place-items-center rounded-xl bg-primary/10 text-primary">
                  <BarChart3 className="size-4" />
                </span>
                <h2 className="font-heading text-[15px] font-semibold text-foreground">Performance Diagnostics</h2>
              </div>
              <Badge tone={stats.netUsd >= 0 ? 'success' : 'danger'} dot>
                {stats.settled}w settled
              </Badge>
            </div>

            {summary ? (
              <>
                {/* Win / Loss & Payoff Quality */}
                <div className="mt-3.5 rounded-tile border border-line bg-surface-2/30 p-3">
                  {/* Each result sits above its own slice of the bar, like ticks. */}
                  <div className="flex items-baseline gap-3 text-[12.5px]">
                    <div className="flex min-w-0 flex-1 items-baseline">
                      <span
                        className="tabular-nums font-semibold text-success"
                        style={{ width: `${winPct}%` }}
                        title={`${stats.winsCount} winning windows`}
                      >
                        {winPct >= 6 ? `${stats.winsCount}W` : ''}
                      </span>
                      {stats.scratchCount > 0 && (
                        <span
                          className="tabular-nums text-muted"
                          style={{ width: `${scratchPct}%` }}
                          title={`${stats.scratchCount} break-even windows`}
                        >
                          {scratchPct >= 6 ? `${stats.scratchCount}T` : ''}
                        </span>
                      )}
                      <span
                        className="flex-1 text-right tabular-nums font-semibold text-danger"
                        title={`${stats.lossesCount} losing windows`}
                      >
                        {stats.lossesCount}L
                      </span>
                    </div>
                    <span className="tabular-nums font-semibold text-fg">{(stats.winRate * 100).toFixed(1)}%</span>
                  </div>
                  <div className="mt-1 flex h-2 overflow-hidden rounded-full bg-surface-2">
                    <div
                      className="h-full bg-success transition-all duration-300"
                      style={{ width: `${winPct}%` }}
                      title={`${(stats.winRate * 100).toFixed(1)}% Wins (${stats.winsCount})`}
                    />
                    {stats.scratchCount > 0 && (
                      <div
                        className="h-full bg-line/80 transition-all duration-300"
                        style={{ width: `${scratchPct.toFixed(1)}%` }}
                        title={`${((stats.scratchCount / (stats.settled || 1)) * 100).toFixed(1)}% Break-even (${stats.scratchCount})`}
                      />
                    )}
                    <div
                      className="h-full flex-1 bg-danger transition-all duration-300"
                      title={`${(stats.lossRate * 100).toFixed(1)}% Losses (${stats.lossesCount})`}
                    />
                  </div>
                  <div className="mt-2.5 grid grid-cols-2 gap-2 border-t border-line/60 pt-2 text-[11.5px]">
                    <div>
                      <span className="text-faint">Payoff (Avg W/L): </span>
                      <span
                        className={cx(
                          'font-medium tabular-nums',
                          stats.payoffRatio >= 1 ? 'text-success' : stats.payoffRatio >= 0.5 ? 'text-warning' : 'text-danger',
                        )}
                      >
                        {stats.lossesCount === 0 && stats.winsCount > 0 ? '∞' : `${stats.payoffRatio.toFixed(2)}x`}
                      </span>
                    </div>
                    <div className="text-right">
                      <span className="text-faint">Break-Even Req: </span>
                      <span className="font-medium tabular-nums text-fg">
                        {stats.breakEvenWinRate !== null
                          ? `${(stats.breakEvenWinRate * 100).toFixed(1)}%`
                          : 'N/A'}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Risk & Volatility Profile */}
                <ul className="mt-3.5 space-y-2 text-[12.5px]">
                  <Row
                    label="Max Drawdown"
                    value={`-${usd(stats.maxDrawdownUsd)} (-${stats.maxDrawdownPct.toFixed(1)}%)`}
                    tone="danger"
                  />
                  <Row
                    label="Current Drawdown"
                    value={
                      stats.currentDrawdownUsd <= 0.01
                        ? 'At All-Time High'
                        : `-${usd(stats.currentDrawdownUsd)} (-${stats.currentDrawdownPct.toFixed(1)}%)`
                    }
                    tone={stats.currentDrawdownUsd <= 0.01 ? 'success' : 'danger'}
                  />
                  <Row
                    label="Sortino Ratio"
                    value={stats.lossesCount === 0 && stats.settled > 0 && stats.netUsd > 0 ? '∞' : stats.sortinoRatio.toFixed(2)}
                    tone={stats.sortinoRatio >= 1 ? 'success' : stats.sortinoRatio < 0 ? 'danger' : 'neutral'}
                  />
                  <Row
                    label="Best / Worst Window"
                    value={
                      <>
                        <span className="text-success">
                          {stats.bestUsd > 0 ? `+${usd(stats.bestUsd)}` : usd(stats.bestUsd)}
                        </span>
                        {' / '}
                        <span className="text-danger">
                          {stats.worstUsd > 0 ? `+${usd(stats.worstUsd)}` : usd(stats.worstUsd)}
                        </span>
                      </>
                    }
                  />
                  <Row
                    label="Streak (Current · Best · Worst)"
                    value={
                      <>
                        <span
                          className={cx(
                            stats.currentStreak > 0 ? 'text-success' : stats.currentStreak < 0 ? 'text-danger' : 'text-fg',
                          )}
                        >
                          {stats.currentStreak > 0
                            ? `+${stats.currentStreak}W`
                            : stats.currentStreak < 0
                              ? `${stats.currentStreak}L`
                              : '0'}
                        </span>
                        <span className="text-fg">
                          {' · '}+{stats.maxWinStreak}W / -{stats.maxLossStreak}L
                        </span>
                      </>
                    }
                  />
                </ul>

                {/* Directional Market Edge (Up vs Down) */}
                <div className="mt-3.5 border-t border-line pt-3">
                  <div className="flex items-center justify-between text-[12.5px]">
                    <span className="flex items-center gap-1.5 font-medium text-fg">
                      <TrendingUp className="size-3.5 text-primary" />
                      Directional Edge
                    </span>
                  </div>
                  <div className="mt-2 space-y-1.5 text-[12px]">
                    <div className="flex items-center justify-between">
                      <span className="inline-flex items-center gap-1.5 text-muted">
                        <span className="size-2 rounded-[2px] bg-success" />
                        Up Windows ({stats.upCount})
                      </span>
                      <span className="tabular-nums">
                        <span className="text-muted">
                          {stats.upWins}W ({(stats.upWinRate * 100).toFixed(0)}%) ·{' '}
                        </span>
                        <span className={cx('font-medium', stats.upNetUsd >= 0 ? 'text-success' : 'text-danger')}>
                          {stats.upNetUsd >= 0 ? '+' : ''}
                          {usd(stats.upNetUsd)}
                        </span>
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="inline-flex items-center gap-1.5 text-muted">
                        <span className="size-2 rounded-[2px] bg-danger" />
                        Down Windows ({stats.downCount})
                      </span>
                      <span className="tabular-nums">
                        <span className="text-muted">
                          {stats.downWins}W ({(stats.downWinRate * 100).toFixed(0)}%) ·{' '}
                        </span>
                        <span className={cx('font-medium', stats.downNetUsd >= 0 ? 'text-success' : 'text-danger')}>
                          {stats.downNetUsd >= 0 ? '+' : ''}
                          {usd(stats.downNetUsd)}
                        </span>
                      </span>
                    </div>
                  </div>

                  <div className="mt-2.5 flex items-baseline text-[12px]">
                    <span
                      className="tabular-nums font-semibold text-success"
                      style={{ width: `${upFillPct}%` }}
                      title={`${stats.upFills} Up fills`}
                    >
                      {upFillPct >= 10 ? `${stats.upFills} Up` : ''}
                    </span>
                    <span className="flex-1 text-right tabular-nums font-semibold text-danger">
                      {stats.downFills} Down
                    </span>
                  </div>
                  <div className="mt-1 flex h-1.5 overflow-hidden rounded-full bg-surface-2">
                    <div
                      className="h-full bg-success/80"
                      style={{ width: `${upFillPct}%` }}
                      title={`${share(upFillPct / 100)} Up`}
                    />
                    <div className="h-full flex-1 bg-danger/70" />
                  </div>
                </div>
              </>
            ) : (
              <Skeleton className="mt-4 h-[300px]" />
            )}
          </div>

          {/* Operational Settlement Notice */}
          {summary && (
            <div className="mt-4 pt-2">
              {(data?.redeem.count ?? 0) > 0 ? (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-tile border border-warning/30 bg-warning-soft/30 p-3 text-[11.5px]">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 font-medium text-warning-strong">
                      <span>
                        {data?.redeem.count} unredeemed {data?.redeem.count === 1 ? 'window' : 'windows'}
                      </span>
                      <span>•</span>
                      <span>{usd(data?.redeem.payoutUsd ?? 0)}</span>
                    </div>
                    <p className="mt-0.5 text-[11px] leading-tight text-muted">
                      Claim payouts into your run session records or run <code className="font-mono text-[10.5px]">python bot/redeem.py</code>.
                    </p>
                  </div>
                  {!isViewOnly && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={redeem.isPending}
                      onClick={() =>
                        redeem.mutate(undefined, {
                          onSuccess: (res) =>
                            toast(
                              res.redeemedCount > 0
                                ? `Redeemed ${res.redeemedCount} winning ${res.redeemedCount === 1 ? 'window' : 'windows'} (${usd(res.payoutUsd)})`
                                : 'All windows marked clean',
                            ),
                          onError: (err) =>
                            toast(err instanceof Error ? err.message : 'Failed to redeem'),
                        })
                      }
                    >
                      {redeem.isPending && <Spinner data-icon="inline-start" />}
                      Redeem all
                    </Button>
                  )}
                </div>
              ) : (
                <div className="flex items-center justify-between rounded-tile border border-line bg-surface-2/30 px-3 py-2 text-[11.5px] text-muted">
                  <span className="flex items-center gap-1.5">
                    <CheckCircle2 className="size-3.5 text-success" /> All settled payouts redeemed
                  </span>
                  <span className="font-mono text-[11px] text-faint">clean</span>
                </div>
              )}
            </div>
          )}
        </Card>
      </div>

      <TierBar tier={tier} onPick={setTier} />

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat
          label="Taker Fees"
          icon={<Receipt className="size-3.5" />}
          value={stats.feesUsd > 0 ? `−${usd(stats.feesUsd)}` : usd(0)}
          hint={
            verifiedOnly
              ? 'Taker fills excluded in verified view'
              : `${stats.costUsd > 0 ? ((stats.feesUsd / stats.costUsd) * 100).toFixed(1) : '0.0'}% of cost`
          }
          tone={stats.feesUsd > 0 ? 'danger' : 'neutral'}
          badge={verifiedOnly ? <Badge tone="neutral">maker only</Badge> : undefined}
          tip="Polymarket's parabolic taker fee, 0.07 · p · (1 − p) per share, already charged inside each taker fill's cost. Maker fills pay none."
        />
        <Stat
          label="Taker Rebate"
          icon={<RotateCcw className="size-3.5" />}
          value={`+${usd(stats.takerRebateUsd)}`}
          hint={`${Math.round(tier.rate * 100)}% of fees · ${tier.name}`}
          tone="success"
          badge={verifiedOnly ? <Badge tone="neutral">maker only</Badge> : includeRebates ? undefined : <Badge tone="neutral">excluded</Badge>}
          tip="Taker fees returned at the selected tier. Polymarket credits this daily at 00:00 UTC on the previous day's fees."
        />
        <Stat
          label="Maker Rebate"
          icon={<Sparkles className="size-3.5" />}
          value={`+${usd(stats.makerRebateUsd)}`}
          hint="20% of the fee each maker fill was matched against"
          tone="success"
          badge={includeRebates ? undefined : <Badge tone="neutral">excluded</Badge>}
          tip="Makers claim a fixed 20% share (crypto markets) of the taker fees collected on the fills they took the other side of. It does not depend on tier."
        />
        <Stat
          label="Net before rebates"
          icon={<Wallet className="size-3.5" />}
          value={`${stats.netBeforeRebateUsd >= 0 ? '+' : ''}${usd(stats.netBeforeRebateUsd)}`}
          hint={
            includeRebates
              ? `Rebates add ${usd(stats.rebatesUsd)}`
              : `Rebates excluded · ${usd(stats.rebatesUsd)} not counted`
          }
          tone={stats.netBeforeRebateUsd >= 0 ? 'success' : 'danger'}
          badge={
            <Toggle
              label="Rebates"
              on={includeRebates}
              onToggle={() => setIncludeRebates(!includeRebates)}
              title={
                includeRebates
                  ? 'Rebates are included in the P&L. Click to exclude them.'
                  : 'Rebates are excluded from the P&L. Click to include them.'
              }
            />
          }
          tip="What the strategy earned on price alone, fees charged and no rebate credited. The switch decides whether the rebate is credited on top of it."
        />
      </div>

      <Card className="mt-3 gap-0 p-5">
        <div className="flex items-center gap-2.5">
          <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
            <ShieldCheck className="size-4" />
          </span>
          <h2 className="font-heading text-[15px] font-semibold text-foreground">Execution Health</h2>
        </div>

        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {[...(data?.cells ?? [])]
            .sort((a, b) => {
              const ra = EXEC_HEALTH_ORDER.indexOf(a.key)
              const rb = EXEC_HEALTH_ORDER.indexOf(b.key)
              return (
                (ra === -1 ? EXEC_HEALTH_ORDER.length : ra) - (rb === -1 ? EXEC_HEALTH_ORDER.length : rb)
              )
            })
            .map((cell) => {
              const Icon = EXEC_HEALTH_ICONS[cell.key]
              return (
                <div key={cell.key} className="rounded-tile border border-line bg-surface-2/30 p-3">
                  <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-faint">
                    {Icon && <Icon className="size-3.5" />}
                    <span className="whitespace-nowrap">{cell.label}</span>
                  </p>
                  <p
                    className={cx(
                      'mt-0.5 text-[19px] font-semibold tabular-nums tracking-[-0.02em]',
                      CELL_TONE[cell.status] ?? 'text-fg',
                    )}
                  >
                    {cell.value}
                  </p>
                  <dl className="mt-1.5 space-y-0.5">
                    {cell.sub.map((item) => (
                      <div key={item.label} className="flex items-baseline justify-between gap-2 text-[11.5px]">
                        <dt className="truncate text-faint">{item.label}</dt>
                        <dd className={cx('shrink-0 font-medium tabular-nums', item.tone ?? 'text-fg')}>{item.value}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )
            })}
          {!data && <Skeleton className="col-span-2 my-4 h-[180px] lg:col-span-4" />}
        </div>

        {data && <ShapeChart mShape={data.mShape} />}
      </Card>

      <Card className="mt-3 gap-0 p-5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
              <CalendarClock className="size-4" />
            </span>
            <h2 className="font-heading text-[15px] font-semibold text-foreground">Window Log</h2>
          </div>
          <Link to="/live" className="text-[12.5px] font-medium text-muted-foreground hover:text-foreground">
            Live view →
          </Link>
        </div>

        {scopedLog.length === 0 ? (
          <EmptyState
            icon={<Target />}
            title={windows.length === 0 ? 'No windows traded yet' : 'No windows in this timeframe'}
            description={
              windows.length === 0
                ? 'Start the loop and the first row appears when it opens a window.'
                : 'Widen the timeframe above to see older windows.'
            }
          />
        ) : (
          <div className="mt-3 [&_[data-slot=table-container]]:max-h-[460px] [&_[data-slot=table-container]]:overflow-auto [&_[data-slot=table-container]]:scrollbar-thin">
            <Table className="min-w-[720px] text-left text-[13px]">
              <TableHeader className="sticky top-0 z-10 bg-card text-[11.5px] uppercase tracking-wide text-muted-foreground">
                <TableRow className="hover:bg-transparent">
                  <TableHead className="h-9 py-2 pr-3 font-medium text-muted-foreground">Window</TableHead>
                  <TableHead className="h-9 py-2 px-3 text-right font-medium text-muted-foreground">Fills</TableHead>
                  <TableHead className="h-9 py-2 px-3 font-medium text-muted-foreground">Sides</TableHead>
                  <TableHead className="h-9 py-2 px-3 text-right font-medium text-muted-foreground">Cost</TableHead>
                  <TableHead className="h-9 py-2 px-3 text-right font-medium text-muted-foreground">Payout</TableHead>
                  <TableHead className="h-9 py-2 px-3 text-right font-medium text-muted-foreground">Net</TableHead>
                  <TableHead className="h-9 py-2 px-3 font-medium text-muted-foreground">Winner</TableHead>
                  <TableHead className="h-9 py-2 pl-3 font-medium text-muted-foreground">Redeem</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[...scopedLog].reverse().map(withRebates).map((window) => (
                  <TableRow key={window.slug}>
                    <TableCell className="py-2.5 pr-3 font-mono tabular-nums text-muted-foreground">{windowTime(window.startMs)}</TableCell>
                    <TableCell className="py-2.5 px-3 text-right font-mono tabular-nums">
                      {window.trades}
                      {window.zeroPriceFills > 0 && (
                        <span className="ml-1 text-[11px] text-rose-600 dark:text-rose-400" title={`${window.zeroPriceFills} fills at $0.00`}>
                          ({window.zeroPriceFills} zero)
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="py-2.5 px-3">
                      <Badge tone={window.bothSides ? 'neutral' : 'warning'} className="capitalize">
                        {window.bothSides ? 'both' : 'single'}
                      </Badge>
                    </TableCell>
                    <TableCell className="py-2.5 px-3 text-right font-mono tabular-nums text-muted-foreground">{usd(window.costUsd)}</TableCell>
                    <TableCell className="py-2.5 px-3 text-right font-mono tabular-nums text-muted-foreground">{usd(window.payoutUsd)}</TableCell>
                    <TableCell
                      className={cx(
                        'py-2.5 px-3 text-right font-mono font-medium tabular-nums',
                        window.netUsd == null
                          ? 'text-muted-foreground'
                          : window.netUsd >= 0
                            ? 'text-emerald-600 dark:text-emerald-400'
                            : 'text-rose-600 dark:text-rose-400',
                      )}
                    >
                      {window.netUsd == null ? 'settling…' : usd(window.netUsd)}
                    </TableCell>
                    <TableCell className="py-2.5 px-3">
                      {window.winner ? (
                        <Badge tone={window.winner === 'Up' ? 'success' : 'danger'}>{window.winner}</Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="py-2.5 pl-3 text-muted-foreground">
                      {window.pending ? '—' : (window.payoutUsd ?? 0) <= 0 ? '—' : window.redeemed ? 'claimed' : 'due'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>

    </div>
  )
}

function Stat({
  label,
  value,
  unit,
  hint,
  hintText,
  badge,
  tip,
  tone,
  icon,
}: {
  label: string
  value: string
  unit?: string
  hint: React.ReactNode
  hintText?: string
  badge?: React.ReactNode
  tip?: string
  tone?: Tone
  icon?: React.ReactNode
}) {
  return (
    <Card className="group relative flex min-h-[116px] flex-col justify-between gap-2 p-3 transition-colors hover:border-border">
      <div className="flex flex-wrap items-center justify-between gap-x-1.5 gap-y-1">
        <div className="flex min-w-0 items-center gap-1 text-[12px] font-medium text-muted-foreground">
          {icon && <span className="shrink-0 text-muted-foreground/70 [&_svg]:size-3.5">{icon}</span>}
          <span className="truncate">{label}</span>
          {tip && (
            <Tooltip>
              <TooltipTrigger
                render={
                  <button
                    type="button"
                    aria-label={`About ${label}`}
                    className="inline-flex shrink-0 cursor-help text-muted-foreground/70 transition-colors hover:text-foreground focus-visible:text-foreground"
                  />
                }
              >
                <Info className="size-3" aria-hidden="true" />
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-left leading-relaxed">
                {tip}
              </TooltipContent>
            </Tooltip>
          )}
        </div>
        {badge && (
          <div className="shrink-0 [&_[data-slot=badge]]:h-5 [&_[data-slot=badge]]:px-1.5 [&_[data-slot=badge]]:text-[10px]">
            {badge}
          </div>
        )}
      </div>
      <div>
        <div className="flex items-baseline gap-1.5">
          <span
            className={cx(
              'text-[23px] font-semibold tracking-[-0.02em] tabular-nums',
              TONE_TEXT[tone ?? 'neutral'],
            )}
          >
            {value}
          </span>
          {unit && <span className="text-[12px] font-medium text-muted-foreground">{unit}</span>}
        </div>
        {typeof hint === 'string' ? (
          <p className="mt-0.5 truncate text-[11.5px] text-muted-foreground" title={hint}>
            {hint}
          </p>
        ) : (
          // The hint is composed markup, so the plain-text twin keeps the
          // full value reachable when the card truncates it.
          <div className="mt-0.5 truncate text-[11.5px] text-muted-foreground" title={hintText}>
            {hint}
          </div>
        )}
      </div>
    </Card>
  )
}

const TIER_META: Record<string, { icon: LucideIcon; color: string }> = {
  bronze: { icon: Medal, color: 'text-amber-600 dark:text-amber-500' },
  silver: { icon: Shield, color: 'text-slate-400 dark:text-slate-300' },
  gold: { icon: Trophy, color: 'text-yellow-500 dark:text-amber-400' },
  platinum: { icon: Crown, color: 'text-sky-400 dark:text-sky-300' },
  diamond: { icon: Gem, color: 'text-cyan-400 dark:text-cyan-300' },
  obsidian: { icon: Sparkles, color: 'text-violet-400 dark:text-violet-300' },
}

function TierBar({
  tier,
  onPick,
}: {
  tier: AccountTier
  onPick: (id: string) => void
}) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2.5 rounded-2xl border border-border bg-card px-3.5 py-2.5">
      <span className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        <Award className="size-3.5 text-primary" />
        Account tier
      </span>
      <div className="flex flex-wrap gap-0.5 rounded-lg border border-border bg-muted/50 p-0.5">
        {ACCOUNT_TIERS.map((option) => {
          const meta = TIER_META[option.id]
          const TierIcon = meta?.icon ?? Award
          return (
            <button
              key={option.id}
              type="button"
              onClick={() => onPick(option.id)}
              aria-pressed={tier.id === option.id}
              title={`${option.name} · ${Math.round(option.rate * 100)}% rebate · $${option.volumeUsd.toLocaleString('en-US')} 30-day weighted volume`}
              className={cx(
                'inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11.5px] font-medium transition-colors',
                tier.id === option.id ? 'bg-background text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              <TierIcon className={cx('size-3 shrink-0', meta?.color)} aria-hidden="true" />
              <span>
                {option.name}
                <span className="ml-1 font-mono text-[10.5px] text-muted-foreground/80">{Math.round(option.rate * 100)}%</span>
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function Toggle({
  label,
  on,
  onToggle,
  title,
}: {
  label: string
  on: boolean
  onToggle: () => void
  title: string
}) {
  return (
    <label
      title={title}
      className="inline-flex cursor-pointer items-center gap-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
    >
      <Switch size="sm" checked={on} onCheckedChange={() => onToggle()} />
      <span>{label}</span>
    </label>
  )
}

/**
 * Collapsed tape corroboration & queue-audit badge. Reveals the full tape
 * corroboration breakdown and attainable vs paper figures on hover.
 */
function CorroborationBadge({
  windows,
  attainable: attainableSummary,
  totalScopedWindows,
  verifiedOnly,
}: {
  windows: PerfWindow[]
  attainable?: {
    windows: number
    netUsd: number
    paperNetUsd: number
    makerFills: number
    attainableFills: number
  }
  totalScopedWindows?: number
  verifiedOnly?: boolean
}) {
  const maker = windows.reduce((sum, w) => sum + (w.makerFills ?? 0), 0)
  const taker = windows.reduce((sum, w) => sum + (w.takerFills ?? 0), 0)
  const corroborated = windows.reduce((sum, w) => sum + (w.verified?.trades ?? 0), 0)
  const uncorroboratedPayout = windows.reduce(
    (sum, w) => sum + Math.max(0, (w.payoutUsd ?? 0) - (w.verified?.payoutUsd ?? 0)),
    0,
  )
  // The queue check answers a narrower question than the tape check: not "did
  // this price trade" but "could our order have got filled while it did".
  const audited = windows.filter((w) => w.fidelity)
  const auditedMaker = audited.reduce((sum, w) => sum + (w.fidelity?.makerFills ?? 0), 0)
  const attainableCount = audited.reduce((sum, w) => sum + (w.fidelity?.attainableFills ?? 0), 0)
  const phantom = audited.reduce((sum, w) => sum + (w.fidelity?.phantomFills ?? 0), 0)
  if (maker === 0 && taker === 0) return null
  const pct = maker > 0 ? (100 * corroborated) / maker : 0
  const attainablePct = auditedMaker > 0 ? (100 * attainableCount) / auditedMaker : 0
  const n = (value: number) => value.toLocaleString('en-US')
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            className="inline-flex cursor-help items-center gap-1 rounded-md border border-line bg-surface-2/60 px-2 py-0.5 font-mono text-[11px] text-muted transition-colors hover:border-line-strong hover:text-fg"
          />
        }
      >
        <Info className="size-3 text-faint" aria-hidden="true" />
        <span>Tape {pct.toFixed(0)}%</span>
        {!verifiedOnly && attainableSummary && attainableSummary.windows > 0 && (
          <span
            className={cx(
              'ml-0.5 font-semibold',
              attainableSummary.netUsd >= 0 ? 'text-success' : 'text-danger',
            )}
          >
            · {attainableSummary.netUsd >= 0 ? '+' : ''}
            {usd(attainableSummary.netUsd)}
          </span>
        )}
      </TooltipTrigger>
      <TooltipContent
        side="bottom"
        align="end"
        className="max-w-xs flex-col items-start p-3 text-left text-[11.5px] leading-relaxed"
      >
        <div className="space-y-1.5">
          <p className="text-popover-foreground">
            The tape corroborates <span className="font-semibold text-popover-foreground">{n(corroborated)}</span> of{' '}
            <span className="font-semibold text-popover-foreground">{n(maker)}</span> maker fills ({pct.toFixed(1)}%).
          </p>
          {auditedMaker > 0 ? (
            <p className="text-muted-foreground">
              {n(attainableCount)} of {n(auditedMaker)} audited could actually fill ({attainablePct.toFixed(1)}%),{' '}
              {n(phantom)} never could.
            </p>
          ) : (
            maker - corroborated > 0 && (
              <p className="text-muted-foreground">{n(maker - corroborated)} never traded at their limit.</p>
            )
          )}
          {(taker > 0 || uncorroboratedPayout > 0) && (
            <p className="text-muted-foreground">
              {taker > 0 && <>{n(taker)} taker fills cannot be checked in paper mode</>}
              {taker > 0 && uncorroboratedPayout > 0 && ' · '}
              {uncorroboratedPayout > 0 && <>{usd(uncorroboratedPayout)} payout rests on the rest</>}
            </p>
          )}
          {!verifiedOnly && attainableSummary && attainableSummary.windows > 0 && (
            <p className="border-t border-border/60 pt-1.5 text-muted-foreground">
              Attainable net:{' '}
              <span className={cx('font-semibold', attainableSummary.netUsd >= 0 ? 'text-success' : 'text-danger')}>
                {attainableSummary.netUsd >= 0 ? '+' : ''}
                {usd(attainableSummary.netUsd)}
              </span>{' '}
              vs{' '}
              <span className={cx('font-semibold', attainableSummary.paperNetUsd >= 0 ? 'text-success' : 'text-danger')}>
                {attainableSummary.paperNetUsd >= 0 ? '+' : ''}
                {usd(attainableSummary.paperNetUsd)}
              </span>{' '}
              paper ({n(attainableSummary.windows)}/{n(totalScopedWindows ?? attainableSummary.windows)} windows,{' '}
              {n(attainableSummary.attainableFills)}/{n(attainableSummary.makerFills)} maker fills survive).
            </p>
          )}
        </div>
      </TooltipContent>
    </Tooltip>
  )
}

function TimeframePicker({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  return (
    <div
      className="flex flex-wrap gap-0.5 rounded-lg border border-line bg-surface-2 p-0.5"
      role="group"
      aria-label="Timeframe"
    >
      {TIMEFRAMES.map((option) => (
        <button
          key={option.id}
          type="button"
          onClick={() => onChange(option.id)}
          aria-pressed={value === option.id}
          title={option.ms == null ? 'Since inception' : `Last ${option.label}`}
          className={cx(
            'rounded-md px-2 py-1 text-[11.5px] font-medium transition-colors',
            value === option.id ? 'bg-surface text-fg shadow-xs' : 'text-muted hover:text-fg',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

function Row({ label, value, tone }: { label: string; value: React.ReactNode; tone?: 'success' | 'danger' | 'warning' | 'neutral' }) {
  return (
    <li className="flex items-center justify-between gap-3">
      <span className="text-muted">{label}</span>
      <span
        className={cx(
          'whitespace-nowrap font-medium tabular-nums',
          tone === 'success' && 'text-success',
          tone === 'danger' && 'text-danger',
          tone === 'warning' && 'text-warning',
          (tone === 'neutral' || !tone) && 'text-fg',
        )}
      >
        {value}
      </span>
    </li>
  )
}

function ShapeChart({ mShape }: { mShape: BotPerf['mShape'] }) {
  // An API server that predates the queue split must not blank the dashboard.
  const attainable = mShape.attainable ?? []
  const phantom = mShape.phantom ?? []
  const liveShare = mShape.liveShare ?? []
  const totals = attainable.map((n, index) => n + (phantom[index] ?? 0))
  const audited = totals.reduce((sum, n) => sum + n, 0)
  const attainableTotal = attainable.reduce((sum, n) => sum + n, 0)
  const max = Math.max(1, ...totals)
  // Where the queue hurts most, as a share of the fills audited in that minute.
  const worst = totals.length > 0
    ? totals
        .map((total, index) => ({ index, rate: total > 0 ? (phantom[index] ?? 0) / total : 0 }))
        .reduce((a, b) => (b.rate > a.rate ? b : a))
    : { index: -1, rate: 0 }
  return (
    <div className="mt-4 rounded-tile border border-line bg-surface-2/30 p-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[12.5px] font-medium">
          <Clock className="size-3.5 text-primary" />
          Fill cadence · minutes 0–4
        </p>
        <div className="flex items-center gap-3 text-[11px] text-faint">
          <span className="flex items-center gap-1">
            <span className="size-2 rounded-[2px] bg-accent" /> could fill
          </span>
          <span className="flex items-center gap-1">
            <span className="size-2 rounded-[2px] bg-danger" /> phantom
          </span>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-5 gap-3">
        {liveShare.map((live, index) => {
          const total = totals[index] ?? 0
          return (
            <div key={index} title={`M${index}: ${attainable[index] ?? 0} fillable · ${phantom[index] ?? 0} phantom`}>
              <div className="flex h-16 flex-col justify-end">
                {total > 0 ? (
                  <>
                    <div
                      className="rounded-t-[3px] bg-danger/70"
                      style={{ height: `${Math.max(2, ((phantom[index] ?? 0) / max) * 100)}%` }}
                    />
                    <div
                      className="bg-accent"
                      style={{ height: `${Math.max(2, ((attainable[index] ?? 0) / max) * 100)}%` }}
                    />
                  </>
                ) : (
                  <div className="rounded-t-[3px] bg-line-strong" style={{ height: '2%' }} />
                )}
              </div>
              <p className="mt-1 text-center text-[11px] text-faint">
                M{index} <span className="text-fg">{share(live)}</span> of fills
              </p>
            </div>
          )
        })}
      </div>
      <p className="mt-2 text-[11.5px] text-faint">
        {audited === 0
          ? 'No audited fills yet — the queue check runs once a window’s tape is read.'
          : `Bars show the ${audited} audited maker fills: ${attainableTotal} had selling behind the queue ahead, ${
              audited - attainableTotal
            } never could.${worst.rate > 0 ? ` M${worst.index} is the weakest minute (${share(worst.rate)} phantom).` : ''}`}
      </p>
    </div>
  )
}

const WINDOW_BAR_STEPS = [0.5, 1, 2, 2.5, 5, 10, 15, 20, 25, 50, 100, 200, 500]

function formatDollarTick(value: number): string {
  if (Math.abs(value) < 0.005) return '$0'
  const sign = value > 0 ? '+' : '−'
  const abs = Math.abs(value)
  const decimals = Number.isInteger(abs) ? 0 : 2
  return `${sign}$${abs.toFixed(decimals)}`
}

function WindowBars({
  windows,
  hoveredSlug,
  onHoverSlug,
}: {
  windows: PerfWindow[]
  hoveredSlug?: string | null
  onHoverSlug?: (slug: string | null) => void
}) {
  if (windows.length === 0) return null

  const width = 820
  const height = 176
  const padLeft = 76
  const padRight = 32
  const padTop = 14
  const padBottom = 30
  const chartWidth = width - padLeft - padRight
  const chartHeight = height - padTop - padBottom

  const maxAbs = Math.max(1, ...windows.map((window) => Math.abs(window.netUsd ?? 0)))
  const step = WINDOW_BAR_STEPS.find((candidate) => candidate * 2 >= maxAbs * 0.85) ?? Math.ceil(maxAbs / 2)
  const yBound = Math.max(step * 2, maxAbs * 1.08)
  const yTicks = [-2 * step, -step, 0, step, 2 * step]
  const yCoord = (val: number) => padTop + (chartHeight / 2) * (1 - val / yBound)
  const zeroY = yCoord(0)

  const count = windows.length
  const colW = chartWidth / count
  const barW = Math.min(22, Math.max(6, colW * 0.68))
  const labelStep = count <= 8 ? 1 : count <= 16 ? 2 : 3

  const hoveredIndex = hoveredSlug ? windows.findIndex((w) => w.slug === hoveredSlug) : -1
  const hoveredWindow = hoveredIndex >= 0 ? windows[hoveredIndex] : null

  return (
    <div className="relative mt-2 select-none" onMouseLeave={() => onHoverSlug?.(null)}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full overflow-visible"
        role="img"
        aria-label="Last 24 windows profit and loss bar chart with dollar and hour axes"
      >
        {/* Outer plot grid border */}
        <rect
          x={padLeft}
          y={padTop}
          width={chartWidth}
          height={chartHeight}
          fill="none"
          stroke="var(--color-line)"
          strokeWidth="1"
          opacity="0.7"
        />

        {/* Vertical column grid lines */}
        {windows.slice(1).map((window, idx) => {
          const x = padLeft + (idx + 1) * colW
          return (
            <line
              key={`v-grid-${window.slug}`}
              x1={x}
              x2={x}
              y1={padTop}
              y2={height - padBottom}
              stroke="var(--color-line)"
              strokeDasharray="2 4"
              strokeWidth="1"
              opacity="0.45"
            />
          )
        })}

        {/* Horizontal dollar gridlines & Y-axis ticks (including $0) */}
        {yTicks.map((tick) => {
          const y = yCoord(tick)
          const isZero = tick === 0
          return (
            <g key={`y-tick-${tick}`}>
              <line
                x1={padLeft}
                x2={width - padRight}
                y1={y}
                y2={y}
                stroke={isZero ? 'var(--color-line-strong)' : 'var(--color-line)'}
                strokeDasharray={isZero ? undefined : '2 4'}
                strokeWidth={isZero ? 1.25 : 1}
                opacity={isZero ? 0.95 : 0.6}
              />
              <line
                x1={padLeft - 4}
                x2={padLeft}
                y1={y}
                y2={y}
                stroke={isZero ? 'var(--color-fg)' : 'var(--color-line-strong)'}
                strokeWidth={isZero ? 1.25 : 1}
              />
              <text
                x={padLeft - 8}
                y={y + 3.5}
                textAnchor="end"
                fontSize="10.5"
                fontWeight={isZero ? '600' : '400'}
                fill={isZero ? 'var(--color-fg)' : 'var(--color-faint)'}
                className="font-mono"
              >
                {formatDollarTick(tick)}
              </text>
            </g>
          )
        })}

        {/* Bars, X-axis ticks, and hour labels */}
        {windows.map((window, index) => {
          const net = window.netUsd ?? 0
          const colX = padLeft + index * colW
          const centerX = colX + colW / 2
          const barTop = net >= 0 ? yCoord(net) : zeroY
          const barHeight = Math.max(2, Math.abs(yCoord(net) - zeroY))
          const isHovered = hoveredSlug === window.slug
          const isPositive = net >= 0
          const showLabel = index % labelStep === 0 || index === count - 1 || isHovered
          const timeText = windowTime(window.startMs)
          const title = `${timeText} · ${net >= 0 ? '+' : '−'}${usd(Math.abs(net))} · ${window.trades} fills · ${window.winner ?? 'pending'}`

          return (
            <g
              key={window.slug}
              className="cursor-pointer"
              onMouseEnter={() => onHoverSlug?.(window.slug)}
            >
              <title>{title}</title>

              {isHovered && (
                <rect
                  x={colX}
                  y={padTop}
                  width={colW}
                  height={chartHeight}
                  fill="var(--color-fg)"
                  opacity="0.06"
                />
              )}

              <rect
                x={centerX - barW / 2}
                y={barTop}
                width={barW}
                height={barHeight}
                rx={2}
                fill={isPositive ? '#22c55e' : '#ef4444'}
                opacity={hoveredWindow && !isHovered ? 0.55 : 0.88}
                stroke={isHovered ? 'var(--color-fg)' : 'none'}
                strokeWidth={isHovered ? 1.5 : 0}
              />

              {/* X-axis tick mark for every window */}
              <line
                x1={centerX}
                x2={centerX}
                y1={height - padBottom}
                y2={height - padBottom + (isHovered ? 6 : 3.5)}
                stroke={isHovered ? 'var(--color-fg)' : 'var(--color-line-strong)'}
                strokeWidth={isHovered ? 1.5 : 1}
              />

              {showLabel && (
                <text
                  x={centerX}
                  y={height - padBottom + 16}
                  textAnchor="middle"
                  fontSize="10"
                  fontWeight={isHovered ? '600' : '400'}
                  fill={isHovered ? 'var(--color-fg)' : 'var(--color-faint)'}
                  className="font-mono"
                >
                  {timeText}
                </text>
              )}

              {/* Full-column transparent hit target for responsive hover */}
              <rect x={colX} y={padTop} width={colW} height={chartHeight + 18} fill="transparent" />
            </g>
          )
        })}
      </svg>

      {hoveredWindow && (
        <div className="pointer-events-none absolute top-1.5 right-2 rounded-md border border-line bg-surface/95 px-2 py-0.5 font-mono text-[11px] text-fg shadow-xs">
          <span>{windowTime(hoveredWindow.startMs)}</span>
          <span className="mx-1.5 text-faint">·</span>
          <span className={cx('font-semibold', (hoveredWindow.netUsd ?? 0) >= 0 ? 'text-success' : 'text-danger')}>
            {(hoveredWindow.netUsd ?? 0) >= 0 ? '+' : ''}
            {usd(hoveredWindow.netUsd ?? 0)}
          </span>
          <span className="mx-1.5 text-faint">·</span>
          <span className="text-muted">{hoveredWindow.trades} fills</span>
        </div>
      )}
    </div>
  )
}
