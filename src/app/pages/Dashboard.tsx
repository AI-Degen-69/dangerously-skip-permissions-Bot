import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  History,
  Info,
  Pause,
  Percent,
  Play,
  RotateCcw,
  Scale,
  Target,
  TrendingUp,
} from 'lucide-react'
import { Link } from 'react-router'
import { useId, useState } from 'react'

import { Badge, Button, Card, ConfirmDialog, EmptyState, PageHeader, Skeleton, useToast } from '../components/ui'
import { InteractivePnlChart } from '../components/InteractivePnlChart'
import {
  BOT_ORIGIN,
  useBotControl,
  useBotPerf,
  useBotRuns,
  useRedeemBot,
  useResetBot,
  useResumeRun,
  useSelectRun,
  useStartBot,
  useStopBot,
} from '../lib/bot'
import type { BotPerf, PerfGate, PerfNote, PerfWindow } from '../lib/bot'
import { computeKpiStats } from '../lib/kpiStats'
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

const NOTE_TONE: Record<PerfNote['tone'], string> = {
  danger: 'bg-danger-soft text-danger',
  warning: 'bg-warning-soft text-warning',
  info: 'bg-info-soft text-info',
  success: 'bg-success-soft text-success',
}

export function Dashboard() {
  const perf = useBotPerf()
  const control = useBotControl()
  const runsQuery = useBotRuns()
  const selectRun = useSelectRun()
  const start = useStartBot()
  const resumeRun = useResumeRun()
  const stop = useStopBot()
  const reset = useResetBot()
  const redeem = useRedeemBot()
  const toast = useToast()
  const [confirmReset, setConfirmReset] = useState(false)
  const [hoveredSlug, setHoveredSlug] = useState<string | null>(null)

  const isViewOnly = control.data?.isViewOnly ?? false
  const running = (control.data?.running ?? false) && !isViewOnly
  const selectedRunId = control.data?.selectedRunId ?? runsQuery.data?.selectedRunId ?? null
  const availableRuns = runsQuery.data?.runs ?? []

  const data = perf.data
  const summary = data?.summary
  const health = data?.health
  const notes = data?.notes ?? []
  const windows = data?.windows ?? []
  const settled = windows.filter((window) => !window.pending)
  const startingCapital = data?.summary?.bankrollUsd ?? 1000
  const stats = computeKpiStats(windows, startingCapital, summary)
  const currentCapital = stats.currentCapital
  const gateJudged = settled.length >= (data?.targets.windows ?? 288)
  const strategySymbol = data?.strategy?.symbol ?? control.data?.strategy?.symbol ?? '🎯 HAPCS-v1'
  const strategyName =
    data?.strategy?.name ??
    control.data?.strategy?.name ??
    'Hybrid Arbitrage Pairing & Certainty Sniping v1'
  const strategySignature =
    data?.strategy?.signature ??
    control.data?.strategy?.signature ??
    'Maker Dip Grid [7¢–50¢] (0% fee) · Dynamic Pairing Arbitrage · Resolution Certainty Snipe [up to 97.5¢] · Pair Cost Benchmark $0.965 (cap ≤$0.990)'

  return (
    <div className="mx-auto max-w-[1200px] p-5 sm:p-8">
      <PageHeader
        title={`Paper desk · ${strategySymbol}`}
        subtitle={`${strategyName} — BTC 5-minute windows, held to redeem.`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <span title={strategyName}>
              <Badge tone="accent" className="font-mono font-semibold">
                {strategySymbol} · Recovery Engine
              </Badge>
            </span>
            {availableRuns.length > 0 && (
              <div className="flex items-center gap-1.5 rounded-pill border border-subtle bg-subtle px-2.5 py-1 text-[12px]">
                <History className="size-3.5 text-muted" />
                <label htmlFor="dashboard-session" className="text-muted font-medium cursor-pointer">Session:</label>
                <select
                  id="dashboard-session"
                  aria-label="Paper trading session"
                  value={selectedRunId ?? ''}
                  onChange={(e) => {
                    const val = e.target.value || null
                    selectRun.mutate(val, {
                      onSuccess: (res) => {
                        toast(res.isViewOnly ? `Loaded past run (View-Only)` : 'Switched to live session')
                      },
                    })
                  }}
                  className="bg-transparent font-mono text-[11.5px] font-semibold text-fg outline-none cursor-pointer"
                >
                  <option value="">Live session</option>
                  {availableRuns.map((r) => (
                    <option key={r.runId} value={r.runId}>
                      {r.runId} ({r.windowsCount ?? 0}w{r.status ? ` - ${r.status}` : ''})
                    </option>
                  ))}
                </select>
              </div>
            )}

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

            {!isViewOnly ? (
              <>
                <Button
                  variant={running ? 'secondary' : 'primary'}
                  size="sm"
                  loading={start.isPending || stop.isPending}
                  onClick={() =>
                    running
                      ? stop.mutate(undefined, { onSuccess: () => toast('Bot stopped') })
                      : start.mutate(undefined, {
                          onSuccess: (result) =>
                            toast(result.reason === 'already-running' ? 'Bot already running' : 'Paper bot started'),
                        })
                  }
                >
                  {running ? <Pause /> : <Play />}
                  {running ? 'Stop bot' : 'Start bot'}
                </Button>
                <Button variant="ghost" size="icon-sm" aria-label="Reset bot" onClick={() => setConfirmReset(true)}>
                  <RotateCcw />
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="primary"
                  size="sm"
                  loading={resumeRun.isPending}
                  onClick={() =>
                    resumeRun.mutate(selectedRunId, {
                      onSuccess: (res) => toast(`Resumed run ${res.runId} on existing database`),
                      onError: (err) => toast(`Failed to resume: ${(err as Error).message}`),
                    })
                  }
                >
                  <Play />
                  Resume run
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() =>
                    selectRun.mutate(null, {
                      onSuccess: () => toast('Returned to live session'),
                    })
                  }
                >
                  Return to Live
                </Button>
              </>
            )}
          </div>
        }
      />

      <Card className="mt-4 border-accent/40 bg-accent-soft/20 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="grid size-8 shrink-0 place-items-center rounded-tile bg-accent text-white font-bold shadow-xs">
              ⚡
            </span>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[13.5px] font-semibold text-fg">{strategyName}</span>
                <Badge tone="info" className="font-mono text-[10.5px]">
                  Isolated Desk · {BOT_ORIGIN}
                </Badge>
              </div>
              <p className="mt-0.5 font-mono text-[11.5px] text-muted">{strategySignature}</p>
            </div>
          </div>
        </div>
      </Card>

      {isViewOnly && (
        <Card className="mt-4 border-warning/40 bg-warning-soft/30 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-start gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-tile bg-warning-soft text-warning">
                <History className="size-4.5" />
              </span>
              <div>
                <p className="text-[13.5px] font-semibold text-warning-strong">
                  Viewing Historical Run: <code className="font-mono">{selectedRunId}</code>
                </p>
                <p className="text-[12.5px] text-muted">
                  Inspecting past run telemetry and database. Click &ldquo;Resume run&rdquo; to restart the bot on this database and continue from where it stopped.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="primary"
                loading={resumeRun.isPending}
                onClick={() =>
                  resumeRun.mutate(selectedRunId, {
                    onSuccess: (res) => toast(`Resumed run ${res.runId} on existing database`),
                    onError: (err) => toast(`Failed to resume: ${(err as Error).message}`),
                  })
                }
              >
                <Play className="size-3.5" />
                Resume run
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  selectRun.mutate(null, {
                    onSuccess: () => toast('Returned to live session'),
                  })
                }
              >
                Back to Live Run
              </Button>
            </div>
          </div>
        </Card>
      )}

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

      {!running && !perf.isError && (
        <Card className="mt-4 flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-tile bg-warning-soft text-warning">
              <Activity className="size-4.5" />
            </span>
            <div>
              <p className="text-[13.5px] font-medium">The loop is not running</p>
              <p className="text-[12.5px] text-muted">
                No new windows are being taken.
                {health?.snapshotAgeSec != null && (
                  <> Last heartbeat {relativeTime(Date.now() - health.snapshotAgeSec * 1000)}.</>
                )}
              </p>
            </div>
          </div>
          <Button size="sm" loading={start.isPending} onClick={() => start.mutate(undefined, { onSuccess: () => toast('Paper bot started') })}>
            <Play /> Start paper bot
          </Button>
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

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {!summary ? (
          Array.from({ length: 5 }).map((_, index) => <Skeleton key={index} className="h-[116px] rounded-card" />)
        ) : (
          <>
            <Stat
              label="Net P&amp;L"
              value={`${stats.netUsd >= 0 ? '+' : ''}${usd(stats.netUsd)}`}
              hint={`${stats.capitalReturnPct >= 0 ? '+' : ''}${stats.capitalReturnPct.toFixed(1)}% capital · ${stats.roiPct.toFixed(1)}% ROI`}
              tone={stats.netUsd >= 0 ? 'success' : 'danger'}
              badge={
                <Badge tone={stats.netUsd >= 0 ? 'success' : 'danger'}>
                  {stats.netUsd >= 0 ? 'Profitable' : 'Loss'}
                </Badge>
              }
              tip="Total realized paper profit/loss across all settled windows vs starting capital."
              icon={<TrendingUp className="size-3.5" />}
            />
            <Stat
              label="Win Rate"
              value={`${(stats.winRate * 100).toFixed(1)}%`}
              hint={`${stats.winsCount}W – ${stats.lossesCount}L (${stats.settled} settled)`}
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
              hint={`Avg Win +${usd(stats.avgWinUsd)} · Loss -${usd(stats.avgLossUsd)}`}
              tone={stats.expectancyUsd >= 0 ? 'success' : 'danger'}
              badge={
                <Badge tone="neutral" className="font-mono text-[10.5px]">
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
              hint={`Gross: +${usd(stats.grossProfitUsd)} / -${usd(stats.grossLossUsd)}`}
              tone={stats.profitFactor >= 1.5 ? 'success' : stats.profitFactor >= 1.0 ? 'warning' : 'danger'}
              badge={
                <Badge tone="neutral" className="font-mono text-[10.5px]">
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
              hint={`Sortino: ${stats.lossesCount === 0 && stats.settled > 0 && stats.netUsd > 0 ? '∞' : stats.sortinoRatio.toFixed(2)} · Max DD: -${stats.maxDrawdownPct.toFixed(1)}%`}
              tone={stats.sharpeRatio >= 1.0 ? 'success' : stats.sharpeRatio >= 0 ? 'neutral' : 'danger'}
              badge={
                <Badge tone={stats.maxDrawdownPct <= 15 ? 'success' : stats.maxDrawdownPct <= 30 ? 'warning' : 'danger'}>
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
        <Card className="p-5 lg:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-[14px] font-semibold">Paper P&amp;L &amp; Capital</h2>
                <Badge tone="neutral" className="font-mono text-[11px]">
                  Base {usd(startingCapital)}
                </Badge>
                {stats.settled > 0 && (
                  <Badge tone={stats.expectancyUsd >= 0 ? 'success' : 'danger'} className="text-[11px]">
                    EV: {stats.expectancyUsd >= 0 ? '+' : ''}{usd(stats.expectancyUsd)}/window
                  </Badge>
                )}
                {stats.settled > 0 && (
                  <Badge tone="neutral" className="text-[11px]">
                    PF: {stats.grossLossUsd === 0 && stats.grossProfitUsd > 0 ? '∞' : stats.profitFactor.toFixed(2)}
                  </Badge>
                )}
              </div>
              <p className="text-[12.5px] text-muted">
                Cumulative capital &amp; net per settled window vs {usd(startingCapital)} starting capital; pending windows excluded.
              </p>
            </div>
            {summary && (
              <div className="text-right">
                <div className="flex items-baseline justify-end gap-2">
                  <span className="tabular-nums text-[22px] font-semibold tracking-[-0.02em] text-fg">
                    {usd(currentCapital)}
                  </span>
                  <span
                    className={cx(
                      'tabular-nums text-[13.5px] font-semibold',
                      summary.netUsd >= 0 ? 'text-success' : 'text-danger',
                    )}
                  >
                    {summary.netUsd >= 0 ? '+' : ''}{usd(summary.netUsd)}
                    {startingCapital > 0
                      ? ` (${(((currentCapital - startingCapital) / startingCapital) * 100).toFixed(1)}%)`
                      : ''}
                  </span>
                </div>
                <p className="text-[11.5px] text-faint">
                  {summary.settled} settled window{summary.settled === 1 ? '' : 's'} · {summary.profitable} profitable
                </p>
              </div>
            )}
          </div>

          {settled.length > 0 ? (
            <>
              <div className="mt-3">
                <InteractivePnlChart
                  windows={settled}
                  startingCapital={startingCapital}
                  hoveredSlug={hoveredSlug}
                  onHoverWindow={(w) => setHoveredSlug(w?.slug ?? null)}
                />
              </div>
              <div className="mt-4 border-t border-line pt-3">
                <div className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-muted">
                  <span>Last {Math.min(settled.length, 24)} windows</span>
                  <span className="text-faint">
                    best {usd(summary?.bestUsd ?? 0)} · worst {usd(summary?.worstUsd ?? 0)}
                  </span>
                </div>
                <WindowBars
                  windows={settled.slice(-24)}
                  hoveredSlug={hoveredSlug}
                  onHoverSlug={setHoveredSlug}
                />
              </div>
            </>
          ) : (
            <div className="mt-3">
              <EmptyState
                icon={<Target />}
                title="No settled windows yet"
                description="The first window settles about five minutes after the loop opens it. Everything here fills in on its own."
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

      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h2 className="text-[14px] font-semibold">Fidelity gate</h2>
              <p className="text-[12.5px] text-muted">
                How close the live paper tape is to the frozen 24h sample — 45 median fills, both sides, $316/$447 cost,
                M0–M4 shape.
              </p>
            </div>
            <Badge tone={gateJudged ? 'success' : 'neutral'}>
              {gateJudged ? 'judged' : `sample · ${settled.length}/288`}
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

          {data && <ShapeChart mShape={data.mShape} />}
        </Card>

        <Card className="flex flex-col p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-[14px] font-semibold">Things to note</h2>
            <Badge tone="neutral">{notes.length}</Badge>
          </div>
          <p className="text-[12.5px] text-muted">What the tape says about this run, worst first.</p>
          <ul className="scrollbar-thin mt-3 -mr-2 max-h-[430px] space-y-2.5 overflow-y-auto pr-2">
            {notes.map((note) => (
              <li key={note.title} className="rounded-tile border border-line bg-surface-2/40 p-3">
                <div className="flex items-start gap-2">
                  <span className={cx('mt-0.5 grid size-5 shrink-0 place-items-center rounded-[6px]', NOTE_TONE[note.tone])}>
                    {note.tone === 'danger' || note.tone === 'warning' ? (
                      <AlertTriangle className="size-3" />
                    ) : note.tone === 'success' ? (
                      <CheckCircle2 className="size-3" />
                    ) : (
                      <Info className="size-3" />
                    )}
                  </span>
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium leading-snug">{note.title}</p>
                    <p className="mt-1 text-[12px] leading-relaxed text-muted">{note.body}</p>
                  </div>
                </div>
              </li>
            ))}
            {!data && <Skeleton className="h-[220px]" />}
          </ul>
        </Card>
      </div>

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

        {windows.length === 0 ? (
          <EmptyState
            icon={<Target />}
            title="No windows traded yet"
            description="Start the loop and the first row appears when it opens a window."
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
                {[...windows].reverse().map((window) => (
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

      <ConfirmDialog
        open={confirmReset}
        onClose={() => setConfirmReset(false)}
        loading={reset.isPending}
        title="Reset the paper bot?"
        description="This wipes every paper window, fill and risk counter and restarts from the configured bankroll. It cannot be undone."
        confirmLabel="Reset to clean state"
        onConfirm={() =>
          reset.mutate(undefined, {
            onSuccess: (result) => {
              setConfirmReset(false)
              toast(`Bot reset to ${usd(result.bankrollUsd)} — window history wiped`)
            },
          })
        }
      />
    </div>
  )
}

function Stat({
  label,
  value,
  unit,
  hint,
  badge,
  tip,
  tone,
  icon,
}: {
  label: string
  value: string
  unit?: string
  hint: React.ReactNode
  badge?: React.ReactNode
  tip?: string
  tone?: 'success' | 'danger' | 'warning' | 'neutral'
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
              'text-[23px] font-semibold tracking-[-0.02em] tabular-nums text-fg',
              tone === 'success' && 'text-success',
              tone === 'danger' && 'text-danger',
              tone === 'warning' && 'text-warning',
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
          <div className="mt-0.5 truncate text-[11.5px] text-faint">{hint}</div>
        )}
      </div>
    </Card>
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

function ShapeChart({ mShape }: { mShape: BotPerf['mShape'] }) {
  const max = Math.max(0.05, ...mShape.liveShare, ...mShape.targetShare)
  return (
    <div className="mt-4 rounded-tile border border-line bg-surface-2/30 p-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[12.5px] font-medium">Fill cadence · minutes 0–4</p>
        <div className="flex items-center gap-3 text-[11px] text-faint">
          <span className="flex items-center gap-1">
            <span className="size-2 rounded-[2px] bg-accent" /> live
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
                title={`live ${share(live)} · ${mShape.live[index]} fills`}
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
        {mShape.distance > 0.2 ? 'Live is late-heavy: M4 carries far more fills than the tape.' : 'Shape is inside the band.'}
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
