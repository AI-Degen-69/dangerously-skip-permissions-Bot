import {
  Activity,
  BarChart3,
  CheckCircle2,
  Info,
  Percent,
  Scale,
  Target,
  TrendingUp,
} from 'lucide-react'
import { Link } from 'react-router'
import { useId, useState } from 'react'

import { Badge, Button, Card, EmptyState, PageHeader, Skeleton, useToast } from '../components/ui'
import { BotControlTile } from '../components/BotControlTile'
import { InteractivePnlChart } from '../components/InteractivePnlChart'
import { BOT_ORIGIN, useBotControl, useBotPerf, useRedeemBot, useStrategySetups, mergeStrategySetups } from '../lib/bot'
import { STRATEGY_PRESETS } from '../botDefaults'
import type { BotPerf, PerfGate, PerfWindow, StrategySetup, WindowFidelity } from '../lib/bot'
import { computeKpiStats } from '../lib/kpiStats'
import { ACCOUNT_TIERS, useAccountTier, useIncludeRebates, windowRebate } from '../lib/rebates'
import type { AccountTier } from '../lib/rebates'
import { TIMEFRAMES, scopeWindows, timeframeStart } from '../lib/timeframes'
import { verifiedWindow } from '../lib/verified'
import { useStoredFlag } from '../lib/flags'
import { cx } from '../lib/cx'
import { money2, relativeTime } from '../lib/format'

const usd = money2
const share = (value: number) => `${Math.round(value * 100)}%`
const windowTime = (ms: number) =>
  new Date(ms).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })

function windowLabel(slug: string | null): string {
  if (!slug) return '—'
  const epoch = Number(slug.split('-').pop())
  return Number.isFinite(epoch) ? windowTime(epoch * 1000) : slug
}

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
    netUsd: sum((f) => f.attainableNetUsd),
    makerFills: sum((f) => f.makerFills),
    attainableFills: sum((f) => f.attainableFills),
    phantomFills: sum((f) => f.phantomFills),
  }
}

const GATE_TONE: Record<PerfGate['status'], 'success' | 'warning' | 'danger' | 'neutral'> = {
  pass: 'success',
  warn: 'warning',
  fail: 'danger',
  sample: 'neutral',
}
const GATE_LABEL: Record<PerfGate['status'], string> = {
  pass: 'pass',
  warn: 'watch',
  fail: 'off',
  sample: 'sample',
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
  const running = (control.data?.running ?? false) && !isViewOnly

  const data = perf.data
  const summary = data?.summary
  const health = data?.health
  const windows = data?.windows ?? []
  // Verified Only: every window carries the numbers its verified fills make,
  // and a window without a verified fill drops out of the view entirely.
  const effective = verifiedOnly
    ? windows.map(verifiedWindow).filter((window): window is PerfWindow => window !== null)
    : windows
  const allSettled = windows.filter((window) => !window.pending)
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
  // The gate judges the run as it was traded, not the verified subset.
  const gateJudged = allSettled.length >= (data?.targets.windows ?? 288)
  const setupsQuery = useStrategySetups()
  const allSetups = mergeStrategySetups(setupsQuery.data?.setups, STRATEGY_PRESETS as unknown as Record<string, StrategySetup>)
  const activeId = data?.strategy?.id ?? control.data?.strategy?.id ?? setupsQuery.data?.activeSetupId
  const activeSetup = allSetups.find((s) => s.id === activeId) ?? allSetups[0]
  const strategySymbol = data?.strategy?.symbol ?? control.data?.strategy?.symbol ?? activeSetup?.symbol ?? '—'
  const strategyName = data?.strategy?.name ?? control.data?.strategy?.name ?? activeSetup?.name ?? '—'

  return (
    <div className="mx-auto max-w-[1200px] p-5 sm:p-8">
      <PageHeader
        title={`Paper desk · ${strategySymbol}`}
        subtitle={control.data?.strategy?.signature ?? activeSetup?.signature ?? activeSetup?.description ?? strategyName}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <span title={strategyName}>
              <Badge tone="accent" className="font-mono font-semibold">
                {strategySymbol} · Recovery Engine
              </Badge>
            </span>

            {isViewOnly ? (
              <Badge tone="warning" dot>
                View only (past run)
              </Badge>
            ) : (
              <Badge tone={running ? 'success' : 'neutral'} dot>
                {running ? 'Running' : 'Stopped'}
              </Badge>
            )}
            <Badge tone="warning">Paper only</Badge>
          </div>
        }
      />

      <BotControlTile />

      {perf.isError && (
        <Card className="mt-4 p-5">
          <div className="flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-tile bg-warning-soft text-warning">
              <Activity className="size-4.5" />
            </span>
            <div>
              <p className="text-[13.5px] font-medium">Bot API not reachable</p>
              <p className="mt-0.5 text-[12.5px] text-muted">
                Nothing answered at {BOT_ORIGIN}. Start it with <code className="font-mono">python bot/api.py</code>; this
                page refills on its own.
              </p>
            </div>
          </div>
        </Card>
      )}

      <Card className="mt-3 grid gap-x-6 gap-y-2 px-4 py-3 sm:grid-cols-2 lg:grid-cols-4">
        <HealthItem
          label="Loop"
          value={running ? `running · pid ${control.data?.pid ?? '—'}` : 'stopped'}
          tone={running ? 'success' : 'warning'}
        />
        <HealthItem
          label="Heartbeat"
          value={
            health?.snapshotAgeSec == null
              ? 'no state'
              : health.snapshotAgeSec < 120
                ? `${Math.round(health.snapshotAgeSec)}s ago`
                : relativeTime(Date.now() - health.snapshotAgeSec * 1000)
          }
          tone={health?.snapshotAgeSec == null ? 'neutral' : health.snapshotAgeSec > 120 ? 'warning' : 'success'}
        />
        <HealthItem
          label="Window"
          value={health?.stateSlug ? `${windowLabel(health.stateSlug)} · ${health.stateFills} fills` : 'idle between windows'}
          tone="neutral"
        />
        <HealthItem
          label="Kill switch"
          value={health?.killSwitch ? 'engaged — entries paused' : 'clear'}
          tone={health?.killSwitch ? 'danger' : 'neutral'}
        />
      </Card>

      <TierBar tier={tier} onPick={setTier} rebatesUsd={stats.rebatesUsd} counted={includeRebates} />

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {!summary ? (
          Array.from({ length: 5 }).map((_, index) => <Skeleton key={index} className="h-[116px] rounded-card" />)
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

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat
          label="Taker Fees"
          value={stats.feesUsd > 0 ? `−${usd(stats.feesUsd)}` : usd(0)}
          hint={`${stats.costUsd > 0 ? ((stats.feesUsd / stats.costUsd) * 100).toFixed(1) : '0.0'}% of cost`}
          tone="danger"
          tip="Polymarket's parabolic taker fee, 0.07 · p · (1 − p) per share, already charged inside each taker fill's cost. Maker fills pay none."
        />
        <Stat
          label="Taker Rebate"
          value={`+${usd(stats.takerRebateUsd)}`}
          hint={`${Math.round(tier.rate * 100)}% of fees · ${tier.name}`}
          tone="success"
          badge={includeRebates ? undefined : <Badge tone="neutral">excluded</Badge>}
          tip="Taker fees returned at the selected tier. Polymarket credits this daily at 00:00 UTC on the previous day's fees."
        />
        <Stat
          label="Maker Rebate"
          value={`+${usd(stats.makerRebateUsd)}`}
          hint="20% of the fee each maker fill was matched against"
          tone="success"
          badge={includeRebates ? undefined : <Badge tone="neutral">excluded</Badge>}
          tip="Makers claim a fixed 20% share (crypto markets) of the taker fees collected on the fills they took the other side of. It does not depend on tier."
        />
        <Stat
          label="Net before rebates"
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

      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          {summary && (
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
                {stats.netUsd >= 0 ? '+' : ''}{usd(stats.netUsd)}
                {baseCapital > 0
                  ? ` (${(((currentCapital - baseCapital) / baseCapital) * 100).toFixed(1)}%)`
                  : ''}
              </span>
              {timeframe.ms != null && (
                <Badge tone="neutral" className="text-[11px]">
                  last {timeframe.label}
                </Badge>
              )}
              {!includeRebates && (
                <Badge tone="warning" className="text-[11px]">
                  rebates excluded
                </Badge>
              )}
              {!verifiedOnly && attainable.windows > 0 && (
                <span
                  className={cx(
                    'tabular-nums text-[12.5px] font-semibold',
                    attainable.netUsd >= 0 ? 'text-success' : 'text-danger',
                  )}
                  title={
                    'Net if every maker fill needed real taker selling at its limit, behind the queue resting at that price where it was recorded, before rebates. ' +
                    `${attainable.attainableFills.toLocaleString('en-US')} of ${attainable.makerFills.toLocaleString('en-US')} maker fills survive ` +
                    `across ${attainable.windows.toLocaleString('en-US')} of ${scoped.windows.length.toLocaleString('en-US')} settled windows.`
                  }
                >
                  <span className="mr-1 text-[11px] font-normal text-faint">attainable</span>
                  {attainable.netUsd >= 0 ? '+' : ''}
                  {usd(attainable.netUsd)}
                </span>
              )}
              <span className="text-[11.5px] text-faint">
                {stats.settled} settled window{stats.settled === 1 ? '' : 's'} · {stats.winsCount} profitable
              </span>
              <span className="ml-auto">
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
              </span>
            </div>
          )}
          <CorroborationNote windows={scopedTape} />

          {scoped.windows.length > 0 ? (
            <>
              <div className="mt-3">
                <InteractivePnlChart
                  windows={scoped.windows.map(withRebates)}
                  startingCapital={baseCapital}
                  baseLabel={timeframe.ms == null ? undefined : 'Base capital'}
                  hoveredSlug={hoveredSlug}
                  onHoverWindow={(w) => setHoveredSlug(w?.slug ?? null)}
                />
              </div>
              <div className="mt-4 border-t border-line pt-3">
                <div className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-muted">
                  <span>
                    Last {Math.min(scoped.windows.length, 24)} windows ·{' '}
                    <span className="text-faint">
                      best {usd(stats.bestUsd)} · worst {usd(stats.worstUsd)}
                    </span>
                  </span>
                  <TimeframePicker value={timeframeId} onChange={setTimeframeId} />
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

        <Card className="flex flex-col justify-between p-5">
          <div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="grid size-8 place-items-center rounded-tile bg-accent-soft text-accent">
                  <BarChart3 className="size-4" />
                </span>
                <div>
                  <h2 className="text-[14px] font-semibold">Performance Diagnostics</h2>
                  <p className="text-[12px] text-muted">Edge analysis &amp; risk profile</p>
                </div>
              </div>
              <Badge tone={stats.netUsd >= 0 ? 'success' : 'danger'} dot>
                {stats.settled}w settled
              </Badge>
            </div>

            {summary ? (
              <>
                {/* Win / Loss & Payoff Quality */}
                <div className="mt-3.5 rounded-tile border border-line bg-surface-2/30 p-3">
                  <div className="flex items-baseline justify-between text-[12.5px]">
                    <span className="font-medium text-fg">Win Rate Breakdown</span>
                    <span className="tabular-nums font-semibold text-fg">
                      {(stats.winRate * 100).toFixed(1)}%{' '}
                      <span className="text-[11px] font-normal text-muted">
                        ({stats.winsCount}W · {stats.lossesCount}L{stats.scratchCount > 0 ? ` · ${stats.scratchCount}T` : ''})
                      </span>
                    </span>
                  </div>
                  <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-surface-2">
                    <div
                      className="h-full bg-success transition-all duration-300"
                      style={{ width: `${Math.max(stats.winsCount > 0 ? 2 : 0, stats.winRate * 100)}%` }}
                      title={`${(stats.winRate * 100).toFixed(1)}% Wins (${stats.winsCount})`}
                    />
                    {stats.scratchCount > 0 && (
                      <div
                        className="h-full bg-line/80 transition-all duration-300"
                        style={{ width: `${((stats.scratchCount / (stats.settled || 1)) * 100).toFixed(1)}%` }}
                        title={`${((stats.scratchCount / (stats.settled || 1)) * 100).toFixed(1)}% Break-even (${stats.scratchCount})`}
                      />
                    )}
                    <div
                      className="h-full bg-danger transition-all duration-300"
                      style={{ width: `${Math.max(stats.lossesCount > 0 ? 2 : 0, stats.lossRate * 100)}%` }}
                      title={`${(stats.lossRate * 100).toFixed(1)}% Losses (${stats.lossesCount})`}
                    />
                  </div>
                  <div className="mt-2.5 grid grid-cols-2 gap-2 border-t border-line/60 pt-2 text-[11.5px]">
                    <div>
                      <span className="text-faint">Payoff (Avg W/L): </span>
                      <span className="font-medium tabular-nums text-fg">
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
                    tone={stats.currentDrawdownUsd <= 0.01 ? 'success' : undefined}
                  />
                  <Row
                    label="Sortino Ratio"
                    value={stats.lossesCount === 0 && stats.settled > 0 && stats.netUsd > 0 ? '∞' : stats.sortinoRatio.toFixed(2)}
                    tone={stats.sortinoRatio >= 1.5 ? 'success' : undefined}
                  />
                  <Row
                    label="Best / Worst Window"
                    value={`${stats.bestUsd > 0 ? `+${usd(stats.bestUsd)}` : usd(stats.bestUsd)} / ${stats.worstUsd > 0 ? `+${usd(stats.worstUsd)}` : usd(stats.worstUsd)}`}
                  />
                  <Row
                    label="Streak (Current · Best · Worst)"
                    value={`${stats.currentStreak > 0 ? `+${stats.currentStreak}W` : stats.currentStreak < 0 ? `${stats.currentStreak}L` : '0'} · +${stats.maxWinStreak}W / -${stats.maxLossStreak}L`}
                  />
                </ul>

                {/* Directional Market Edge (Up vs Down) */}
                <div className="mt-3.5 border-t border-line pt-3">
                  <div className="flex items-center justify-between text-[12.5px]">
                    <span className="font-medium text-fg">Directional Edge</span>
                    <span className="text-[11.5px] text-faint">Up vs Down resolution</span>
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

                  <div className="mt-2.5 flex items-center justify-between text-[12px]">
                    <span className="text-muted">Fill mix</span>
                    <span className="tabular-nums text-faint">
                      Up {stats.upFills} · Down {stats.downFills}
                    </span>
                  </div>
                  <div className="mt-1 flex h-1.5 overflow-hidden rounded-full bg-surface-2">
                    <div
                      className="h-full bg-success/80"
                      style={{
                        width: `${(stats.upFills / Math.max(1, stats.upFills + stats.downFills)) * 100}%`,
                      }}
                      title={`${share(stats.upFills / Math.max(1, stats.upFills + stats.downFills))} Up`}
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
                      variant="secondary"
                      loading={redeem.isPending}
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

      <Card className="mt-3 p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="text-[14px] font-semibold">Fidelity gate</h2>
            <p className="text-[12.5px] text-muted">
              How close the live paper tape is to the frozen 24h sample — 45 median fills, both sides, $316/$447 cost,
              M0–M4 shape.
              {verifiedOnly && (
                <span className="text-faint"> Judged on the whole run, not the verified subset.</span>
              )}
            </p>
          </div>
          <Badge tone={gateJudged ? 'success' : 'neutral'}>
            {gateJudged ? 'judged' : `sample · ${allSettled.length}/288`}
          </Badge>
        </div>

        <div className="mt-3 divide-y divide-line">
          {(data?.gate ?? []).map((row) => (
            <div key={row.key} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="text-[13px]">{row.label}</p>
                <p className="text-[11.5px] text-faint">{row.detail}</p>
              </div>
              <span className="tabular-nums text-[13px] font-medium">{row.value}</span>
              <span className="w-[92px] text-right text-[12px] text-faint">tape {row.target}</span>
              <Badge tone={GATE_TONE[row.status]} className="w-[74px] justify-center">
                {GATE_LABEL[row.status]}
              </Badge>
            </div>
          ))}
          {!data && <Skeleton className="my-4 h-[180px]" />}
        </div>

        {data && (
          <ShapeChart mShape={shapeOf(data.mShape, verifiedOnly)} liveLabel={verifiedOnly ? 'verified' : 'live'} />
        )}
      </Card>

      <Card className="mt-3 p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="text-[14px] font-semibold">Window log</h2>
            <p className="text-[12.5px] text-muted">
              One row per 5-minute window, newest first. Net is payout minus staked cost at resolution.
            </p>
          </div>
          <Link to="/live" className="text-[12.5px] text-muted hover:text-fg">
            Live view
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
          <div className="scrollbar-thin mt-3 max-h-[460px] overflow-auto">
            <table className="w-full min-w-[720px] text-left text-[13px]">
              <thead className="sticky top-0 bg-surface text-[11.5px] uppercase tracking-wide text-faint">
                <tr className="border-b border-line">
                  <th className="py-2 font-medium">Window</th>
                  <th className="py-2 text-right font-medium">Fills</th>
                  <th className="py-2 font-medium">Sides</th>
                  <th className="py-2 text-right font-medium">Cost</th>
                  <th className="py-2 text-right font-medium">Payout</th>
                  <th className="py-2 text-right font-medium">Net</th>
                  <th className="py-2 font-medium">Winner</th>
                  <th className="py-2 font-medium">Redeem</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {[...scopedLog].reverse().map(withRebates).map((window) => (
                  <tr key={window.slug}>
                    <td className="py-2.5 tabular-nums text-muted">{windowTime(window.startMs)}</td>
                    <td className="py-2.5 text-right tabular-nums">
                      {window.trades}
                      {window.zeroPriceFills > 0 && (
                        <span className="ml-1 text-[11px] text-danger" title={`${window.zeroPriceFills} fills at $0.00`}>
                          ({window.zeroPriceFills} zero)
                        </span>
                      )}
                    </td>
                    <td className="py-2.5">
                      <Badge tone={window.bothSides ? 'neutral' : 'warning'} className="capitalize">
                        {window.bothSides ? 'both' : 'single'}
                      </Badge>
                    </td>
                    <td className="py-2.5 text-right tabular-nums text-muted">{usd(window.costUsd)}</td>
                    <td className="py-2.5 text-right tabular-nums text-muted">{usd(window.payoutUsd)}</td>
                    <td
                      className={cx(
                        'py-2.5 text-right font-medium tabular-nums',
                        window.netUsd == null ? 'text-faint' : window.netUsd >= 0 ? 'text-success' : 'text-danger',
                      )}
                    >
                      {window.netUsd == null ? 'settling…' : usd(window.netUsd)}
                    </td>
                    <td className="py-2.5">
                      {window.winner ? (
                        <Badge tone={window.winner === 'Up' ? 'success' : 'danger'}>{window.winner}</Badge>
                      ) : (
                        <span className="text-faint">—</span>
                      )}
                    </td>
                    <td className="py-2.5 text-muted">
                      {window.pending ? '—' : (window.payoutUsd ?? 0) <= 0 ? '—' : window.redeemed ? 'claimed' : 'due'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
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
  const tipId = useId()
  return (
    <Card className="group relative flex h-[116px] flex-col justify-between p-3.5 transition-colors hover:border-line-strong">
      <div className="flex items-center justify-between gap-1.5">
        <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-muted">
          {icon && <span className="text-faint [&_svg]:size-3.5">{icon}</span>}
          <span>{label}</span>
          {tip && (
            <span className="group/tip relative inline-flex">
              <span
                tabIndex={0}
                aria-label={`About ${label}`}
                aria-describedby={tipId}
                className="cursor-help text-faint transition-colors hover:text-fg focus-visible:text-fg"
              >
                <Info className="size-3" aria-hidden="true" />
              </span>
              <span
                id={tipId}
                role="tooltip"
                className="pointer-events-none absolute bottom-full left-0 z-50 mb-1.5 hidden w-64 rounded-tile bg-fg px-2.5 py-2 text-[11.5px] font-normal normal-case leading-relaxed text-surface shadow-pop group-hover/tip:block group-focus-within/tip:block"
              >
                {tip}
              </span>
            </span>
          )}
        </div>
        {badge}
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
          {unit && <span className="text-[12px] font-medium text-muted">{unit}</span>}
        </div>
        {typeof hint === 'string' ? (
          <p className="mt-0.5 truncate text-[11.5px] text-faint" title={hint}>
            {hint}
          </p>
        ) : (
          // The hint is composed markup, so the plain-text twin keeps the
          // full value reachable when the card truncates it.
          <div className="mt-0.5 truncate text-[11.5px] text-faint" title={hintText}>
            {hint}
          </div>
        )}
      </div>
    </Card>
  )
}

function TierBar({
  tier,
  onPick,
  rebatesUsd,
  counted,
}: {
  tier: AccountTier
  onPick: (id: string) => void
  rebatesUsd: number
  counted: boolean
}) {
  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-card border border-line bg-surface-1 px-3.5 py-2.5">
      <div className="flex flex-wrap items-center gap-2.5">
        <span className="text-[11px] font-medium uppercase tracking-wide text-faint">Account tier</span>
        <div className="flex flex-wrap gap-0.5 rounded-lg border border-line bg-surface-2 p-0.5">
          {ACCOUNT_TIERS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => onPick(option.id)}
              aria-pressed={tier.id === option.id}
              title={`${option.name} · ${Math.round(option.rate * 100)}% rebate · $${option.volumeUsd.toLocaleString('en-US')} 30-day weighted volume`}
              className={cx(
                'rounded-md px-2 py-1 text-[11.5px] font-medium transition-colors',
                tier.id === option.id ? 'bg-surface-1 text-fg shadow-xs' : 'text-muted hover:text-fg',
              )}
            >
              {option.name}
              <span className="ml-1 font-mono text-[10.5px] text-faint">{Math.round(option.rate * 100)}%</span>
            </button>
          ))}
        </div>
      </div>
      <p className="text-[11.5px] text-faint">
        {counted
          ? `Rebates recompute net P&L, expectancy and profit factor · ${usd(rebatesUsd)} credited at ${tier.name}`
          : `Rebates excluded from the P&L, the stats and the chart · ${usd(rebatesUsd)} not counted`}
      </p>
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
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={onToggle}
      title={title}
      className="flex items-center gap-1.5 text-[11px] font-medium text-muted transition-colors hover:text-fg"
    >
      <span
        className={cx(
          'relative h-[11px] w-[20px] rounded-full transition-colors',
          on ? 'bg-success' : 'bg-line-strong',
        )}
      >
        <span
          className={cx(
            'absolute top-[2px] size-[7px] rounded-full bg-surface transition-all',
            on ? 'left-[11px]' : 'left-[2px]',
          )}
        />
      </span>
      {label}
    </button>
  )
}

/** The fill cadence over every fill, or over the verified ones only. */
function shapeOf(mShape: BotPerf['mShape'], verifiedOnly: boolean): BotPerf['mShape'] {
  if (!verifiedOnly || !mShape.verifiedShare) return mShape
  return {
    live: mShape.verifiedLive ?? mShape.live,
    target: mShape.target,
    liveShare: mShape.verifiedShare,
    targetShare: mShape.targetShare,
    distance: mShape.verifiedDistance ?? mShape.distance,
  }
}

/**
 * What the tape actually corroborates inside the view: the fills the real
 * prints back, the ones the market never traded, and the payout riding on
 * whatever is left over.
 */
function CorroborationNote({ windows }: { windows: PerfWindow[] }) {
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
  const attainable = audited.reduce((sum, w) => sum + (w.fidelity?.attainableFills ?? 0), 0)
  const phantom = audited.reduce((sum, w) => sum + (w.fidelity?.phantomFills ?? 0), 0)
  if (maker === 0 && taker === 0) return null
  const pct = maker > 0 ? (100 * corroborated) / maker : 0
  const attainablePct = auditedMaker > 0 ? (100 * attainable) / auditedMaker : 0
  const n = (value: number) => value.toLocaleString('en-US')
  return (
    <p className="mt-1.5 text-[11.5px] text-faint">
      The tape corroborates {n(corroborated)} of {n(maker)} maker fills ({pct.toFixed(1)}%)
      {auditedMaker > 0 ? (
        <>
          {' '}
          · {n(attainable)} of the {n(auditedMaker)} audited could actually fill (
          {attainablePct.toFixed(1)}%), {n(phantom)} never could
        </>
      ) : (
        maker - corroborated > 0 && <> · {n(maker - corroborated)} never traded at their limit</>
      )}
      {taker > 0 && <> · {n(taker)} taker fills cannot be checked in paper mode</>}
      {uncorroboratedPayout > 0 && <> · {usd(uncorroboratedPayout)} of payout rests on the rest</>}
    </p>
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

function HealthItem({ label, value, tone }: { label: string; value: string; tone: 'success' | 'warning' | 'danger' | 'neutral' }) {
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span className="text-[11px] uppercase tracking-wide text-faint">{label}</span>
      <span
        className={cx(
          'min-w-0 truncate text-[12.5px] font-medium',
          tone === 'success' && 'text-success',
          tone === 'warning' && 'text-warning',
          tone === 'danger' && 'text-danger',
          tone === 'neutral' && 'text-fg',
        )}
      >
        {value}
      </span>
    </div>
  )
}

function Row({ label, value, tone }: { label: string; value: string; tone?: 'success' | 'danger' }) {
  return (
    <li className="flex items-center justify-between">
      <span className="text-muted">{label}</span>
      <span className={cx('font-medium tabular-nums', tone === 'success' && 'text-success', tone === 'danger' && 'text-danger')}>
        {value}
      </span>
    </li>
  )
}

function ShapeChart({ mShape, liveLabel = 'live' }: { mShape: BotPerf['mShape']; liveLabel?: string }) {
  const max = Math.max(0.05, ...mShape.liveShare, ...mShape.targetShare)
  // Name the minute that drifts furthest from the tape instead of assuming it
  // is always M4 — the verified subset is M0-heavy, the full tape is not.
  const worst = mShape.liveShare
    .map((live, index) => ({ index, gap: live - mShape.targetShare[index] }))
    .reduce((a, b) => (Math.abs(b.gap) > Math.abs(a.gap) ? b : a))
  return (
    <div className="mt-4 rounded-tile border border-line bg-surface-2/30 p-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[12.5px] font-medium">Fill cadence · minutes 0–4</p>
        <div className="flex items-center gap-3 text-[11px] text-faint">
          <span className="flex items-center gap-1">
            <span className="size-2 rounded-[2px] bg-accent" /> {liveLabel}
          </span>
          <span className="flex items-center gap-1">
            <span className="size-2 rounded-[2px] bg-line-strong" /> tape
          </span>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-5 gap-3">
        {mShape.liveShare.map((live, index) => (
          <div key={index}>
            <div className="flex h-16 items-end justify-center gap-1.5">
              <div
                className="w-1/3 rounded-t-[3px] bg-accent"
                style={{ height: `${Math.max(2, (live / max) * 100)}%` }}
                title={`${liveLabel} ${share(live)} · ${mShape.live[index]} fills`}
              />
              <div
                className="w-1/3 rounded-t-[3px] bg-line-strong"
                style={{ height: `${Math.max(2, (mShape.targetShare[index] / max) * 100)}%` }}
                title={`tape ${share(mShape.targetShare[index])} · ${mShape.target[index]} fills`}
              />
            </div>
            <p className="mt-1 text-center text-[11px] text-faint">
              M{index} <span className="text-fg">{share(live)}</span> / {share(mShape.targetShare[index])}
            </p>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11.5px] text-faint">
        {(mShape.distance * 100).toFixed(1)}% total-variation distance from the tape.{' '}
        {mShape.distance > 0.2
          ? `M${worst.index} carries ${
              worst.gap > 0 ? 'more' : 'fewer'
            } fills than the tape (${share(mShape.liveShare[worst.index])} vs ${share(mShape.targetShare[worst.index])}).`
          : 'Shape is inside the band.'}
      </p>
    </div>
  )
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
  const maxAbs = Math.max(1, ...windows.map((window) => Math.abs(window.netUsd ?? 0)))
  return (
    <div
      className="relative mt-2 flex h-24 items-stretch gap-[3px]"
      onMouseLeave={() => onHoverSlug?.(null)}
    >
      <div className="pointer-events-none absolute inset-x-0 top-1/2 border-t border-line-strong" />
      {windows.map((window) => {
        const net = window.netUsd ?? 0
        const height = Math.max(3, (Math.abs(net) / maxAbs) * 48)
        const isHovered = hoveredSlug === window.slug
        return (
          <div
            key={window.slug}
            className="relative flex-1 cursor-pointer transition-transform hover:scale-y-105"
            onMouseEnter={() => onHoverSlug?.(window.slug)}
            title={`${windowTime(window.startMs)} · ${net >= 0 ? '+' : '−'}${usd(Math.abs(net))} · ${window.trades} fills · ${window.winner ?? 'pending'}`}
          >
            <div
              className={cx(
                'absolute inset-x-0 rounded-[2px] transition-all duration-150',
                net >= 0 ? 'bottom-1/2 bg-success/80' : 'top-1/2 bg-danger/80',
                isHovered && 'brightness-125 ring-2 ring-fg z-10',
              )}
              style={{ height: `${height}%` }}
            />
          </div>
        )
      })}
    </div>
  )
}
