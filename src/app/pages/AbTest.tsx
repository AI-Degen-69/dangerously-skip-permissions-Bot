import { useMemo, useState } from 'react'
import {
  AlertCircle,
  BarChart3,
  Check,
  FlaskConical,
  Play,
  RefreshCw,
  Scale,
  Sparkles,
  Square,
} from 'lucide-react'
import katex from 'katex'
import 'katex/dist/katex.min.css'

import {
  useAbTestData,
  useStartAbCandidate,
  useStopAbCandidate,
  useBotControl,
} from '../lib/bot'
import { MAKER_REBATE_SHARE, useAccountTier, useIncludeRebates } from '../lib/rebates'
import { Badge, Button, Card, PageHeader, useToast } from '../components/ui'
import { cx } from '../lib/cx'
import { tweakCards } from '../strategyCopy'

const { abs, max, min, ceil, round } = globalThis.Math

const money = (val: number | null | undefined, digits = 2) =>
  val == null ? '—' : `${val < 0 ? '−' : val > 0 ? '+' : ''}$${abs(val).toFixed(digits)}`

const pct = (val: number | null | undefined) =>
  val == null ? '—' : `${(val * 100).toFixed(1)}%`

/** Rebate credit for one arm, same inputs as the dashboard (windowRebate summed). */
const armRebate = (
  s: { feesUsd?: number | null; makerFeeBaseUsd?: number | null } | null | undefined,
  rate: number,
  enabled: boolean,
) => (enabled ? (s?.feesUsd ?? 0) * rate + MAKER_REBATE_SHARE * (s?.makerFeeBaseUsd ?? 0) : 0)

/** Kill float noise: 36.980000000000004 → 36.98, 135 → 135. */
const trim2 = (val: number) => Number(val.toFixed(2))

interface MathProps {
  tex: string
  className?: string
}

/** Clean KaTeX math renderer without regex shrinking or partial bolding. */
function Math({ tex, className }: MathProps) {
  const html = useMemo(() => {
    try {
      return katex.renderToString(tex, { throwOnError: false })
    } catch {
      return tex
    }
  }, [tex])

  return (
    <span
      className={cx('inline-flex items-baseline font-normal', className)}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

export function AbTest() {
  const [live, setLive] = useState(true)
  const { data, refetch } = useAbTestData(live)
  const [tier] = useAccountTier()
  const [includeRebates] = useIncludeRebates()
  const control = useBotControl(live)
  const startCandidate = useStartAbCandidate()
  const stopCandidate = useStopAbCandidate()
  const toast = useToast()

  const isCandidateRunning = Boolean(
    control.data?.running &&
    control.data?.activeRunId &&
    data?.candidate?.runId &&
    control.data.activeRunId === data.candidate.runId
  )
  const handleStart = async () => {
    try {
      await startCandidate.mutateAsync()
      toast('Candidate Run Started — A/B Test candidate engine is now active and gathering samples.')
      refetch()
    } catch (err: any) {
      toast('Failed to Start Candidate' + ': ' + (err?.message || 'Error starting candidate run'), 'danger')
    }
  }

  const handleStop = async () => {
    try {
      await stopCandidate.mutateAsync()
      toast('Candidate Run Stopped — Testing paused. Sample data is safely preserved.')
      refetch()
    } catch (err: any) {
      toast('Failed to Stop' + ': ' + (err?.message || 'Error stopping candidate run'), 'danger')
    }
  }

  const baseline = data?.baseline
  const candidate = data?.candidate
  const candidateLabel = candidate?.name ?? control.data?.strategy?.name ?? 'Candidate'
  const tw = tweakCards(candidate ?? null)
  const baselineLabel = baseline?.name ?? 'Baseline'
  const stats = data?.statistics
  const histogram = data?.histogram ?? []

  const cleanSub = (name: string | undefined, fallback: string): string => {
    if (!name) return fallback
    const m = name.match(/v\d+(\.\d+)*/i)
    if (m) return m[0].toLowerCase()
    return fallback
  }
  const subB = cleanSub(candidate?.name, 'v1.1')
  const subA = cleanSub(baseline?.name, 'v1.0')

  const candidateActive = candidate?.activeWindows ?? candidate?.samples ?? 0
  const baselineActive = baseline?.activeWindows ?? baseline?.samples ?? 0
  const targetN = stats?.targetSampleSize ?? 120
  const activePct = targetN > 0 ? (candidateActive / targetN) * 100 : 0

  const candidatePaired = candidate?.pairedWindows ?? 0
  const baselinePaired = baseline?.pairedWindows ?? 0
  const targetPaired = stats?.targetPaired ?? 60
  const pairedPct = targetPaired > 0 ? (candidatePaired / targetPaired) * 100 : 0

  const candidateSubDollar = candidate?.subDollarPairs ?? 0
  const baselineSubDollar = baseline?.subDollarPairs ?? 0
  const targetSubDollar = stats?.targetSubDollar ?? 35
  const subDollarPct = candidatePaired > 0 ? ((candidateSubDollar / candidatePaired) * 100).toFixed(0) : '0'
  const subDollarProgressPct = targetSubDollar > 0 ? (candidateSubDollar / targetSubDollar) * 100 : 0

  const isPassingMu = Boolean(
    stats?.muCritical != null &&
    candidate != null &&
    (candidate.samples ?? 0) > 0 &&
    candidate.meanPnl >= stats.muCritical
  )

  const gate1ActiveMet = candidateActive >= targetN
  const gate2PairsMet = candidatePaired >= targetPaired && candidateSubDollar >= targetSubDollar
  const gate3StatsMet = Boolean(
    stats &&
    stats.tCritical != null &&
    stats.tStatistic >= stats.tCritical &&
    stats.pValue <= stats.alpha
  )

  // Histogram view: normalized % of active windows (default) vs raw counts,
  // so unequal N_A vs N_B stay directly comparable.
  const [showA, setShowA] = useState(true)
  const [showB, setShowB] = useState(true)
  const [normalized, setNormalized] = useState(true)
  const maxBinCount = useMemo(() => {
    let m = 1
    for (const b of histogram) {
      if (showA && b.baselineCount > m) m = b.baselineCount
      if (showB && b.candidateCount > m) m = b.candidateCount
    }
    return m
  }, [histogram, showA, showB])
  const maxBinPct = useMemo(() => {
    let m = 1
    for (const b of histogram) {
      if (showA && b.baselinePct > m) m = b.baselinePct
      if (showB && b.candidatePct > m) m = b.candidatePct
    }
    return m
  }, [histogram, showA, showB])

  // Linear dollar x-axis over the full-range $1 bins: contiguous [k, k+1)
  // sticks, so a value maps proportionally between the first bin low and
  // the last bin high.
  const histLo = histogram.length > 0 ? histogram[0].range[0] : 0
  const histHi = histogram.length > 0 ? histogram[histogram.length - 1].range[1] : 1
  const histSpan = max(1, histHi - histLo)
  const valueToXPct = (v: number): number => {
    if (histogram.length === 0) return 0
    const frac = (v - histLo) / histSpan
    return min(100, max(0, frac * 100))
  }
  // Vertical grid ticks at regular dollar steps ($5, or $10 for wide ranges),
  // always marking $0.
  const xTicks = useMemo(() => {
    if (histogram.length === 0) return [] as number[]
    const step = histSpan > 40 ? 10 : 5
    const ticks: number[] = []
    for (let t = ceil(histLo / step) * step; t <= histHi; t += step) ticks.push(t)
    if (!ticks.includes(0) && histLo <= 0 && histHi >= 0) ticks.push(0)
    return ticks.sort((a, b) => a - b)
  }, [histogram, histLo, histHi, histSpan])
  // Centered high-visibility reference lines: mu_A (slate), mu_B (emerald),
  // mu_crit (RED). Zero is a subtle dotted line with no pill. Tiers stagger
  // only when adjacent labels sit within ~8% x-distance so they never touch.
  const refLines = useMemo(() => {
    type RefLine = { key: string; value: number; label: React.ReactNode; title: string; lineClass: string; labelClass: string; dashed: boolean; tier: number }
    const mains: Omit<RefLine, 'tier'>[] = []
    if (baseline != null) {
      mains.push({ key: 'muA', value: baseline.meanPnl, label: <><Math tex="\mu_A" /> ${baseline.meanPnl.toFixed(2)}</>, title: `μ_A $${baseline.meanPnl.toFixed(2)}`, lineClass: 'bg-slate-400', labelClass: 'text-muted ring-line', dashed: true })
    }
    if (candidate != null && (candidate.samples ?? 0) > 0) {
      mains.push({ key: 'muB', value: candidate.meanPnl, label: <><Math tex="\mu_B" /> ${candidate.meanPnl.toFixed(2)}</>, title: `μ_B $${candidate.meanPnl.toFixed(2)}`, lineClass: 'bg-emerald-500', labelClass: 'text-emerald-600 ring-emerald-500/30', dashed: false })
    }
    if (stats?.muCritical != null) {
      mains.push({ key: 'mucrit', value: stats.muCritical, label: <><Math tex="\mu_{\text{crit}}" /> ${stats.muCritical.toFixed(2)}</>, title: `μ_crit $${stats.muCritical.toFixed(2)}`, lineClass: 'bg-danger', labelClass: 'text-danger ring-danger/40', dashed: false })
    }
    const withX = mains.map((l) => ({ ...l, x: valueToXPct(l.value) })).sort((a, b) => a.x - b.x)
    let tier = 0
    let prevX: number | null = null
    return withX.map((l) => {
      if (prevX != null && abs(l.x - prevX) < 8) tier = min(2, tier + 1)
      else if (prevX != null && abs(l.x - prevX) >= 8 && tier > 0) tier = max(0, tier - 1)
      prevX = l.x
      return { ...l, tier }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseline, candidate, stats, histLo, histSpan])
  // Faint spread markers: quartiles P25/P50/P75 and ±1σ (~68%) per arm.
  const spreadLines = useMemo(() => {
    type Spread = { key: string; value: number; label: React.ReactNode; title: string; arm: 'A' | 'B' }
    const out: Spread[] = []
    if (baseline != null && (baseline.samples ?? 0) >= 3) {
      if (baseline.q25Pnl != null) out.push({ key: 'q25A', value: baseline.q25Pnl, label: <Math tex="P_{25,A}" className="text-[10px]" />, title: `Baseline P25 $${baseline.q25Pnl.toFixed(2)}`, arm: 'A' })
      if (baseline.medianPnl != null) out.push({ key: 'p50A', value: baseline.medianPnl, label: <Math tex="P_{50,A}" className="text-[10px]" />, title: `Baseline P50 $${Number(baseline.medianPnl).toFixed(2)}`, arm: 'A' })
      if (baseline.q75Pnl != null) out.push({ key: 'q75A', value: baseline.q75Pnl, label: <Math tex="P_{75,A}" className="text-[10px]" />, title: `Baseline P75 $${baseline.q75Pnl.toFixed(2)}`, arm: 'A' })
      if (baseline.meanMinusStd != null) out.push({ key: 'm1A', value: baseline.meanMinusStd, label: <Math tex="-1\sigma_A" className="text-[10px]" />, title: `Baseline −1σ $${baseline.meanMinusStd.toFixed(2)}`, arm: 'A' })
      if (baseline.meanPlusStd != null) out.push({ key: 'p1A', value: baseline.meanPlusStd, label: <Math tex="+1\sigma_A" className="text-[10px]" />, title: `Baseline +1σ $${baseline.meanPlusStd.toFixed(2)}`, arm: 'A' })
    }
    if (candidate != null && (candidate.samples ?? 0) >= 3) {
      if (candidate.q25Pnl != null) out.push({ key: 'q25B', value: candidate.q25Pnl, label: <Math tex="P_{25,B}" className="text-[10px]" />, title: `Candidate P25 $${candidate.q25Pnl.toFixed(2)}`, arm: 'B' })
      if (candidate.medianPnl != null) out.push({ key: 'p50B', value: candidate.medianPnl, label: <Math tex="P_{50,B}" className="text-[10px]" />, title: `Candidate P50 $${Number(candidate.medianPnl).toFixed(2)}`, arm: 'B' })
      if (candidate.q75Pnl != null) out.push({ key: 'q75B', value: candidate.q75Pnl, label: <Math tex="P_{75,B}" className="text-[10px]" />, title: `Candidate P75 $${candidate.q75Pnl.toFixed(2)}`, arm: 'B' })
      if (candidate.meanMinusStd != null) out.push({ key: 'm1B', value: candidate.meanMinusStd, label: <Math tex="-1\sigma_B" className="text-[10px]" />, title: `Candidate −1σ $${candidate.meanMinusStd.toFixed(2)}`, arm: 'B' })
      if (candidate.meanPlusStd != null) out.push({ key: 'p1B', value: candidate.meanPlusStd, label: <Math tex="+1\sigma_B" className="text-[10px]" />, title: `Candidate +1σ $${candidate.meanPlusStd.toFixed(2)}`, arm: 'B' })
    }
    return out
  }, [baseline, candidate])

  return (
    <div className="space-y-6 pb-12">
      <PageHeader
        title="A/B Hypothesis Lab & Statistical Gate"
        subtitle={`Rigorous empirical testing of ${baselineLabel} vs ${candidateLabel} at 95% confidence.`}
        actions={
          <div className="flex items-center gap-2.5">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => refetch()}
              className="gap-1.5"
            >
              <RefreshCw className="size-3.5" />
              Refresh Data
            </Button>
            {isCandidateRunning ? (
              <Button
                variant="danger"
                size="sm"
                onClick={handleStop}
                loading={stopCandidate.isPending}
                className="gap-1.5"
              >
                <Square className="size-3.5 fill-current" />
                Stop Candidate Run
              </Button>
            ) : (
              <Button
                variant="primary"
                size="sm"
                onClick={handleStart}
                loading={startCandidate.isPending}
                title="Start the candidate run under the wired strategy config"
              >
                <Play className="size-3.5 fill-current" />
                Launch Candidate Run (B)
              </Button>
            )}
          </div>
        }
      />

      {/* Top Grid: Section 1 (Statistical Test Status) & Section 2 (Sample Size Progress) */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        {/* Section 1 — Statistical Test Status (Left 2×2 KPI Grid matching SVG layout) */}
        <Card className="flex flex-col justify-between p-5 lg:col-span-7">
          <div>
            <div className="mb-3.5 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="flex size-7 items-center justify-center rounded-[8px] bg-accent/15 text-accent">
                  <FlaskConical className="size-4" />
                </span>
                <span className="font-mono text-[11px] font-bold uppercase tracking-wider text-muted">
                  Statistical Test Status
                </span>
              </div>
              {stats && (
                <Badge
                  tone={
                    stats.verdictTone === 'success'
                      ? 'success'
                      : stats.verdictTone === 'danger'
                        ? 'danger'
                        : stats.verdictTone === 'accent'
                          ? 'accent'
                          : 'neutral'
                  }
                  className="font-medium text-[11px]"
                >
                  {stats.verdict} ({candidateActive} / {targetN} active)
                </Badge>
              )}
            </div>

            {/* 4 Stat Tiles (2x2 Grid) */}
            {stats ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {/* Tile 1: Welch t-Statistic vs Critical */}
                <div className="flex flex-col justify-between rounded-tile border border-line bg-surface-2/60 p-3">
                  <span className="text-[11px] font-medium text-muted">Welch t-Statistic vs Critical</span>
                  <div className="mt-1.5 flex items-baseline gap-2">
                    <span className="font-mono text-[18px] font-bold text-fg">
                      <Math tex="t" className="mr-0.5 text-[14px]" /> = {stats.tStatistic.toFixed(2)}
                    </span>
                    <span
                      className={cx(
                        'text-[13px] font-semibold',
                        stats.tCritical != null && stats.tStatistic >= stats.tCritical ? 'text-success' : 'text-danger',
                      )}
                    >
                      / {stats.tCritical != null ? stats.tCritical.toFixed(2) : '—'}{' '}
                      <Math tex="t_{\text{crit}}" className="text-[12px]" />
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-[10.5px] text-faint">
                    df = {stats.degreesOfFreedom.toFixed(1)} · one-tailed{' '}
                    <Math tex={`\\alpha = ${stats.alpha}`} className="text-[10.5px]" />
                  </p>
                </div>

                {/* Tile 2: Observed p-value */}
                <div className="flex flex-col justify-between rounded-tile border border-line bg-surface-2/60 p-3">
                  <span className="text-[11px] font-medium text-muted">Observed p-value</span>
                  <div className="mt-1.5 flex items-baseline gap-2">
                    <span className="font-mono text-[18px] font-bold text-fg">
                      <Math tex="p" className="mr-0.5 text-[14px]" /> = {stats.pValue.toFixed(4)}
                    </span>
                    <span className="text-[12px] text-muted">
                      (need <Math tex="\le 0.05" className="text-[12px]" />)
                    </span>
                  </div>
                  <p className="mt-1 text-[10.5px] text-faint">
                    Cohen&apos;s d = {stats.cohenD.toFixed(3)} (effect size)
                  </p>
                </div>

                {/* Tile 3: Candidate Mean (μ_B) vs μ_crit */}
                <div
                  className={cx(
                    'flex flex-col justify-between rounded-tile border p-3',
                    stats.muCritical != null && (candidate?.samples ?? 0) > 0
                      ? isPassingMu
                        ? 'border-success/40 bg-surface-2/60'
                        : 'border-danger/40 bg-surface-2/60'
                      : 'border-line bg-surface-2/60',
                  )}
                >
                  <span className="text-[11px] font-medium text-muted">
                    Candidate Mean (<Math tex="\mu_B" className="text-[11px]" />) vs Target
                  </span>
                  <div className="mt-1.5 flex items-baseline gap-2">
                    <span
                      className={cx(
                        'font-mono text-[18px] font-bold',
                        (candidate?.samples ?? 0) === 0
                          ? 'text-muted'
                          : isPassingMu
                            ? 'text-success'
                            : 'text-danger',
                      )}
                    >
                      {(candidate?.samples ?? 0) > 0 ? money(candidate?.meanPnl) : 'Pending'}
                    </span>
                    <span className="text-[12px] text-muted">vs</span>
                    {stats.muCritical != null ? (
                      <span
                        className={cx(
                          'font-mono text-[13px] font-bold',
                          isPassingMu ? 'text-success' : 'text-danger',
                        )}
                      >
                        {money(stats.muCritical)} <Math tex="\mu_{\text{crit}}" className="text-[12px]" />
                      </span>
                    ) : (
                      <span className="font-mono text-[12px] text-faint">
                        pending <Math tex="\mu_{\text{crit}}" className="text-[11px]" />
                      </span>
                    )}
                  </div>
                  <p className="mt-1 font-mono text-[10.5px] text-faint">
                    Baseline <Math tex="\mu_A" className="text-[10.5px]" /> = {money(baseline?.meanPnl)} / window
                  </p>
                </div>

                {/* Tile 4: Win Rate & Pair Quality */}
                <div className="flex flex-col justify-between rounded-tile border border-line bg-surface-2/60 p-3">
                  <span className="text-[11px] font-medium text-muted">Win Rate & Pair Quality</span>
                  <div className="mt-1.5 flex items-baseline gap-2">
                    <span className="font-mono text-[18px] font-bold text-fg">
                      {(candidate?.samples ?? 0) > 0 ? pct(candidate?.winRate) : '—'}
                    </span>
                    <span className="font-mono text-[12px] text-muted">
                      ({candidate?.wins ?? 0}W / {candidate?.losses ?? 0}L)
                    </span>
                  </div>
                  <p
                    className={cx(
                      'mt-1 font-mono text-[10.5px]',
                      candidateSubDollar > 0 ? 'text-success' : 'text-faint',
                    )}
                  >
                    {subDollarPct}% sub-$1.00 pairs ({candidateSubDollar} / {candidatePaired})
                  </p>
                </div>
              </div>
            ) : (
              <div className="py-8 text-center text-[12px] text-muted">
                Statistical test metrics pending sample data...
              </div>
            )}
          </div>

          <p className="mt-3 text-[10.5px] leading-relaxed text-faint">
            Raw settled-window PnL before rebates — compare with dashboard &ldquo;Net before rebates&rdquo; tile.
          </p>
        </Card>

        {/* Section 2 — Sample Size Progress (Right Panel with 3 Visual Progress Bars) */}
        <Card className="flex flex-col justify-between p-5 lg:col-span-5">
          <div>
            <div className="mb-3.5 flex items-center justify-between gap-2">
              <span className="font-mono text-[11px] font-bold uppercase tracking-wider text-muted">
                Sample Gates (B vs Baseline A)
              </span>
              <span className="font-mono text-[11px] text-faint">
                Power: 80% (1 − <Math tex="\beta" className="text-[11px]" />)
              </span>
            </div>

            {/* 3 Clean Progress Bars */}
            <div className="space-y-3.5">
              {/* Bar 1: Active Windows (fills > 0) */}
              <div>
                <div className="mb-1 flex items-center justify-between text-[12px]">
                  <span className="font-medium text-fg">Active Windows</span>
                  <span className="font-mono text-[11px] text-muted">
                    <span className="font-semibold text-fg">B: {candidateActive}</span> / {targetN}
                    <span className="text-faint"> · </span>
                    <span>A: {baselineActive}</span>
                  </span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
                  <div
                    className={cx(
                      'h-full rounded-full transition-all duration-500',
                      activePct >= 100 ? 'bg-success' : 'bg-accent',
                    )}
                    style={{ width: `${min(100, activePct)}%` }}
                  />
                </div>
              </div>

              {/* Bar 2: Paired Windows */}
              <div>
                <div className="mb-1 flex items-center justify-between text-[12px]">
                  <span className="font-medium text-fg">Paired Windows</span>
                  <span className="font-mono text-[11px] text-muted">
                    <span className="font-semibold text-fg">B: {candidatePaired}</span> / {targetPaired}
                    <span className="text-faint"> · </span>
                    <span>A: {baselinePaired}</span>
                  </span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
                  <div
                    className={cx(
                      'h-full rounded-full transition-all duration-500',
                      pairedPct >= 100 ? 'bg-success' : 'bg-accent',
                    )}
                    style={{ width: `${min(100, pairedPct)}%` }}
                  />
                </div>
              </div>

              {/* Bar 3: Sub-$1.00 Pairs */}
              <div>
                <div className="mb-1 flex items-center justify-between text-[12px]">
                  <span className="font-medium text-fg">Sub-$1.00 Pairs</span>
                  <span className="font-mono text-[11px] text-muted">
                    <span className="font-semibold text-fg">B: {candidateSubDollar}</span> / {targetSubDollar}+
                    <span className="text-faint"> · </span>
                    <span>A: {baselineSubDollar}</span>
                  </span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
                  <div
                    className="h-full rounded-full bg-success transition-all duration-500"
                    style={{ width: `${min(100, subDollarProgressPct)}%` }}
                  />
                </div>
              </div>
            </div>

            {/* Compact 2-line summary strip */}
            <div className="mt-4 space-y-0.5 rounded-tile border border-line bg-surface-2/60 p-2.5 font-mono text-[10.5px] leading-relaxed">
              <div className="text-muted">
                Buckets: &lt;$0.96 ({candidate?.pairCostUnder096 ?? 0}) · $0.96–$1.00 ({candidate?.pairCost096to100 ?? 0}) · &gt;$1.00 ({candidate?.pairCostOver100 ?? 0})
              </div>
              <div className="text-faint">
                Observed: B {candidate?.observedWindows ?? 0} / A {baseline?.observedWindows ?? 0} · Merged: {(candidate?.pairsMerged ?? 0).toFixed(1)} pairs
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* Section 3 — Formal Scientific Hypothesis & Decision Boundary */}
      <Card className="p-5">
        <div className="mb-4 flex items-center gap-2">
          <Scale className="size-4 text-accent" />
          <h2 className="text-[15px] font-semibold text-fg">
            Formal Scientific Hypothesis &amp; Decision Boundary
          </h2>
        </div>

        <div className="grid gap-3.5 md:grid-cols-2">
          {/* H0 Card */}
          <div className="flex flex-col justify-between rounded-tile border border-danger/30 bg-surface-2/40 p-4">
            <div>
              <span className="inline-flex items-center gap-1.5 font-mono text-[11px] font-bold uppercase tracking-wider text-danger">
                <AlertCircle className="size-3.5" />
                <Math tex="H_0" className="text-[11px]" /> · STAY ON {baselineLabel.toUpperCase()}
              </span>
              <div className="mt-3">
                <Math
                  tex={`H_0: \\mu_{${subB}} \\le \\mu_{${subA}} \\;\\text{or}\\; \\mu_{${subB}} \\le 0`}
                  className="text-[16px] font-semibold text-fg sm:text-[17px]"
                />
              </div>
            </div>
            <p className="mt-3 text-[11.5px] leading-relaxed text-muted">
              Default state if <Math tex="t < t_{\\text{crit}}" className="text-[11.5px]" /> or any sample gate is unmet.
            </p>
          </div>

          {/* H1 Card */}
          <div className="flex flex-col justify-between rounded-tile border border-success/30 bg-surface-2/40 p-4">
            <div>
              <span className="inline-flex items-center gap-1.5 font-mono text-[11px] font-bold uppercase tracking-wider text-success">
                <Sparkles className="size-3.5" />
                <Math tex="H_1" className="text-[11px]" /> · PROMOTE {candidateLabel.toUpperCase()} (ALL 3 REQUIRED)
              </span>
              <div className="mt-3">
                <Math
                  tex={`H_1: \\mu_{${subB}} > \\mu_{${subA}} \\;\\text{and}\\; \\mu_{${subB}} > 0`}
                  className="text-[16px] font-semibold text-fg sm:text-[17px]"
                />
              </div>
            </div>

            {/* 3 Live Checkable Gate Pills */}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {/* Gate 1 */}
              <span
                className={cx(
                  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[11px] transition-colors',
                  gate1ActiveMet
                    ? 'border-success/40 bg-success/15 font-semibold text-success'
                    : 'border-line bg-surface/80 text-muted',
                )}
              >
                {gate1ActiveMet ? <Check className="size-3 text-success" /> : <span className="size-1.5 rounded-full bg-muted/60" />}
                <span>
                  Active <Math tex={`N \\ge ${targetN}`} className="text-[11px]" />
                </span>
              </span>

              {/* Gate 2 */}
              <span
                className={cx(
                  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[11px] transition-colors',
                  gate2PairsMet
                    ? 'border-success/40 bg-success/15 font-semibold text-success'
                    : 'border-line bg-surface/80 text-muted',
                )}
              >
                {gate2PairsMet ? <Check className="size-3 text-success" /> : <span className="size-1.5 rounded-full bg-muted/60" />}
                <span>
                  Paired <Math tex={`\\ge ${targetPaired}`} className="text-[11px]" /> &amp; Sub-$1{' '}
                  <Math tex={`\\ge ${targetSubDollar}`} className="text-[11px]" />
                </span>
              </span>

              {/* Gate 3 */}
              <span
                className={cx(
                  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[11px] transition-colors',
                  gate3StatsMet
                    ? 'border-success/40 bg-success/15 font-semibold text-success'
                    : 'border-line bg-surface/80 text-muted',
                )}
              >
                {gate3StatsMet ? <Check className="size-3 text-success" /> : <span className="size-1.5 rounded-full bg-muted/60" />}
                <span>
                  <Math tex="t \\ge t_{\\text{crit}}" className="text-[11px]" /> &amp;{' '}
                  <Math tex="p \\le 0.05" className="text-[11px]" />
                </span>
              </span>
            </div>
          </div>
        </div>

        {/* The 3 Tested Tweaks Breakdown */}
        <div className="mt-4 border-t border-line pt-4">
          <p className="text-[12px] font-bold uppercase tracking-wider text-muted">
            The 3 Core Improvements in Candidate Strategy B ({candidateLabel})
          </p>
          <div className="mt-2.5 grid gap-3 sm:grid-cols-3">
            <div className="rounded-[9px] border border-line bg-surface p-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10.5px] font-bold text-muted">Tweak 1 · Hard Gate</span>
                <Badge tone="success" className="text-[10px]">{tw[0].badge}</Badge>
              </div>
              <p className="mt-1 text-[12.5px] font-semibold text-fg">{tw[0].title}</p>
              <p className="mt-1 text-[11px] text-muted">{tw[0].body}</p>
            </div>

            <div className="rounded-[9px] border border-line bg-surface p-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10.5px] font-bold text-muted">Tweak 2 · Intake</span>
                <Badge tone="accent" className="text-[10px]">{tw[1].badge}</Badge>
              </div>
              <p className="mt-1 text-[12.5px] font-semibold text-fg">{tw[1].title}</p>
              <p className="mt-1 text-[11px] text-muted">{tw[1].body}</p>
            </div>

            <div className="rounded-[9px] border border-line bg-surface p-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10.5px] font-bold text-muted">Tweak 3 · Sweep</span>
                <Badge tone="info" className="text-[10px]">{tw[2].badge}</Badge>
              </div>
              <p className="mt-1 text-[12.5px] font-semibold text-fg">{tw[2].title}</p>
              <p className="mt-1 text-[11px] text-muted">{tw[2].body}</p>
            </div>
          </div>
        </div>
      </Card>

      {/* 3. Comparative Scorecard: Strategy A (Baseline) vs Strategy B (Candidate) */}
      {/* Subgrid: both cards span the same 3 parent rows (header / tiles / details),
          so each row takes the height of the taller card and both columns line up. */}
      <div className="grid gap-4 md:grid-cols-2 md:gap-y-3">
        {/* Baseline Card */}
        <Card className="grid grid-rows-subgrid row-span-3 gap-y-3 p-5">
          <div className="contents">
            <div className="flex items-start justify-between">
              <div>
                <span className="inline-flex items-center gap-1 rounded-[6px] bg-surface-2 px-2 py-0.5 font-mono text-[11px] font-bold text-muted">
                  STRATEGY A · BASELINE
                </span>
                <h3 className="mt-1 text-[16px] font-semibold text-fg">{baseline?.name ?? 'DSP v2.6 (Baseline)'}</h3>
                <p className="text-[12px] text-muted">{baseline?.description}</p>
              </div>
              <Badge tone="neutral">Reference Run</Badge>
            </div>

            <div className="grid grid-cols-2 gap-2.5 pt-2 sm:grid-cols-4">
              <div className="rounded-[8px] bg-surface-2/60 p-2.5">
                <span className="text-[11px] text-muted">Sample Windows</span>
                <p className="mt-0.5 font-mono text-[15px] font-bold text-fg">{baseline?.samples ?? 0}</p>
              </div>
              <div className="rounded-[8px] bg-surface-2/60 p-2.5">
                <span className="text-[11px] text-muted">Mean Window PnL</span>
                <p className={cx('mt-0.5 font-mono text-[15px] font-bold', (baseline?.meanPnl ?? 0) < 0 ? 'text-danger' : 'text-success')}>
                  {money(baseline?.meanPnl, 4)}
                </p>
              </div>
              <div className="rounded-[8px] bg-surface-2/60 p-2.5">
                <span className="text-[11px] text-muted">Win Rate</span>
                <p className="mt-0.5 font-mono text-[15px] font-bold text-fg">{pct(baseline?.winRate)}</p>
              </div>
              <div className="rounded-[8px] bg-surface-2/60 p-2.5">
                <span className="text-[11px] text-muted">Total Net PnL</span>
                <p className={cx('mt-0.5 font-mono text-[15px] font-bold', (baseline?.netPnl ?? 0) < 0 ? 'text-danger' : 'text-success')}>
                  {money(baseline?.netPnl)}
                </p>
                {baseline?.samples ? (
                  <p className="mt-0.5 font-mono text-[11px] text-muted" title={`Rebates at ${tier.name} tier${includeRebates ? '' : ' (excluded)'}`}>
                    with rebates {money(baseline.netPnl + armRebate(baseline, tier.rate, includeRebates))} · mean {money((baseline.netPnl + armRebate(baseline, tier.rate, includeRebates)) / baseline.samples, 4)}
                  </p>
                ) : null}
              </div>
            </div>

            <div className="space-y-1.5 pt-2 text-[12px]">
              <div className="flex justify-between border-b border-line/60 pb-1">
                <span className="text-muted">Mean Pair Cost</span>
                <span className="font-mono font-medium text-fg">{baseline?.meanPairCost ? `$${baseline.meanPairCost.toFixed(4)}` : '—'}</span>
              </div>
              <div className="flex justify-between border-b border-line/60 pb-1">
                <span className="text-muted">Standard Deviation (<Math tex="s_A" />)</span>
                <span className="font-mono font-medium text-fg">{baseline?.stdPnl ? `$${baseline.stdPnl.toFixed(4)}` : '—'}</span>
              </div>
              <div className="flex justify-between border-b border-line/60 pb-1">
                <span className="text-muted">Wins / Losses / Scratches</span>
                <span className="font-mono font-medium text-fg">
                  {baseline?.wins}W · {baseline?.losses}L · {baseline?.scratches}S
                </span>
              </div>
              <div className="flex justify-between pb-1">
                <span className="text-muted">100% Paired Rate</span>
                <span className="font-mono font-medium text-fg">{baseline?.zeroImbalancePct}%</span>
              </div>
            </div>
          </div>
        </Card>

        {/* Candidate Card */}
        <Card className="grid grid-rows-subgrid row-span-3 gap-y-3 border-accent/40 p-5 shadow-xs">
          <div className="contents">
            <div className="flex items-start justify-between">
              <div>
                <span className="inline-flex items-center gap-1 rounded-[6px] bg-accent/15 px-2 py-0.5 font-mono text-[11px] font-bold text-accent">
                  STRATEGY B · CANDIDATE
                </span>
                <h3 className="mt-1 text-[16px] font-semibold text-fg">{candidate?.name ?? 'Hydrogen v1.1'}</h3>
                <p className="text-[12px] text-muted">{candidate?.description}</p>
              </div>
              <Badge tone={isCandidateRunning ? 'success' : 'accent'}>
                {isCandidateRunning ? 'Live Sampling' : 'Ready'}
              </Badge>
            </div>

            <div className="grid grid-cols-2 gap-2.5 pt-2 sm:grid-cols-4">
              <div className="rounded-[8px] bg-surface-2/60 p-2.5">
                <span className="text-[11px] text-muted">Samples (<Math tex="N_B" />)</span>
                <p className="mt-0.5 font-mono text-[15px] font-bold text-fg">
                  {candidate?.samples ?? 0}
                  <span className="text-[11px] text-faint"> / {stats?.targetSampleSize}</span>
                </p>
              </div>
              <div className="rounded-[8px] bg-surface-2/60 p-2.5">
                <span className="text-[11px] text-muted">Mean Window PnL</span>
                <p className={cx('mt-0.5 font-mono text-[15px] font-bold', (candidate?.meanPnl ?? 0) < 0 ? 'text-danger' : (candidate?.samples ?? 0) > 0 ? 'text-success' : 'text-muted')}>
                  {candidate?.samples ? money(candidate.meanPnl, 4) : 'Pending'}
                </p>
              </div>
              <div className="rounded-[8px] bg-surface-2/60 p-2.5">
                <span className="text-[11px] text-muted">Win Rate</span>
                <p className="mt-0.5 font-mono text-[15px] font-bold text-fg">
                  {candidate?.samples ? pct(candidate.winRate) : 'Pending'}
                </p>
              </div>
              <div className="rounded-[8px] bg-surface-2/60 p-2.5">
                <span className="text-[11px] text-muted">Total Net PnL</span>
                <p className={cx('mt-0.5 font-mono text-[15px] font-bold', (candidate?.netPnl ?? 0) < 0 ? 'text-danger' : (candidate?.samples ?? 0) > 0 ? 'text-success' : 'text-muted')}>
                  {candidate?.samples ? money(candidate.netPnl) : 'Pending'}
                </p>
                {candidate?.samples ? (
                  <p className="mt-0.5 font-mono text-[11px] text-muted" title={`Rebates at ${tier.name} tier${includeRebates ? '' : ' (excluded)'}`}>
                    with rebates {money(candidate.netPnl + armRebate(candidate, tier.rate, includeRebates))} · mean {money((candidate.netPnl + armRebate(candidate, tier.rate, includeRebates)) / candidate.samples, 4)}
                  </p>
                ) : null}
              </div>
            </div>

            <div className="space-y-1.5 pt-2 text-[12px]">
              <div className="flex justify-between border-b border-line/60 pb-1">
                <span className="text-muted">Mean Pair Cost</span>
                <span className="font-mono font-medium text-fg">
                  {candidate?.samples && candidate.meanPairCost ? `$${candidate.meanPairCost.toFixed(4)}` : 'Pending'}
                </span>
              </div>
              <div className="flex justify-between border-b border-line/60 pb-1">
                <span className="text-muted">Standard Deviation (<Math tex="s_B" />)</span>
                <span className="font-mono font-medium text-fg">
                  {candidate?.samples && candidate.stdPnl ? `$${candidate.stdPnl.toFixed(4)}` : 'Pending'}
                </span>
              </div>
              <div className="flex justify-between border-b border-line/60 pb-1">
                <span className="text-muted">Wins / Losses / Scratches</span>
                <span className="font-mono font-medium text-fg">
                  {candidate?.samples ? `${candidate.wins}W · ${candidate.losses}L · ${candidate.scratches}S` : '0W · 0L · 0S'}
                </span>
              </div>
              <div className="flex justify-between pb-1">
                <span className="text-muted">100% Paired Rate</span>
                <span className="font-mono font-medium text-fg">
                  {candidate?.samples ? `${candidate.zeroImbalancePct}%` : 'Pending'}
                </span>
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* 4. Comparative PnL Distribution Histogram */}
      <Card className="p-5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <BarChart3 className="size-4 text-accent" />
              <h3 className="text-[15px] font-semibold text-fg">Comparative PnL Frequency Histogram</h3>
            </div>
            <p className="text-[12px] text-muted">
              Auto-updating distribution of active-window PnL (fills &gt; 0): Baseline Strategy A (Slate) vs Candidate Strategy B (Emerald).
            </p>
          </div>

          <div className="flex items-center gap-4 text-[11.5px]">
            <button
              type="button"
              aria-pressed={showA}
              onClick={() => setShowA((v) => !v)}
              title={showA ? 'Click to hide Baseline A' : 'Click to show Baseline A'}
              className={cx('flex items-center gap-1.5 rounded-pill border border-line px-2.5 py-1 transition-all hover:bg-surface-2', !showA && 'opacity-45')}
            >
              <span className={cx('size-3 rounded-[3px] bg-muted/50', !showA && 'bg-transparent ring-1 ring-muted')} />
              <span className={cx('text-muted', !showA && 'line-through')}>Baseline A (N={baseline?.samples ?? 0})</span>
            </button>
            <button
              type="button"
              aria-pressed={showB}
              onClick={() => setShowB((v) => !v)}
              title={showB ? 'Click to hide Candidate B' : 'Click to show Candidate B'}
              className={cx('flex items-center gap-1.5 rounded-pill border border-line px-2.5 py-1 transition-all hover:bg-surface-2', !showB && 'opacity-45')}
            >
              <span className={cx('size-3 rounded-[3px] bg-accent', !showB && 'bg-transparent ring-1 ring-accent')} />
              <span className={cx('font-medium text-fg', !showB && 'line-through')}>Candidate B (N={candidate?.samples ?? 0})</span>
            </button>
            <button
              type="button"
              aria-pressed={live}
              onClick={() => setLive((v) => !v)}
              title={live ? 'Pause live updates (freezes the chart for inspection)' : 'Resume live updates (10s poll)'}
              className={cx('flex items-center gap-1.5 rounded-pill border border-line px-2.5 py-1 transition-all hover:bg-surface-2', !live && 'opacity-60')}
            >
              <span className={cx('size-2 rounded-full', live ? 'bg-success' : 'bg-muted')} />
              <span className={cx(!live && 'line-through')}>{live ? 'Live' : 'Paused'}</span>
            </button>
            <div className="flex items-center overflow-hidden rounded-pill border border-line text-[11px]" role="group" aria-label="Histogram scale">
              <button
                type="button"
                aria-pressed={normalized}
                onClick={() => setNormalized(true)}
                className={cx('px-2.5 py-1 transition-all', normalized ? 'bg-accent/15 font-semibold text-fg' : 'text-muted hover:bg-surface-2')}
              >
                Normalized %
              </button>
              <button
                type="button"
                aria-pressed={!normalized}
                onClick={() => setNormalized(false)}
                className={cx('px-2.5 py-1 transition-all', !normalized ? 'bg-accent/15 font-semibold text-fg' : 'text-muted hover:bg-surface-2')}
              >
                Raw Count
              </button>
            </div>
          </div>
        </div>

        {/* Histogram Visualization: cropped $1.00 stick bars on a linear dollar axis */}
        <div className="mt-6 space-y-2">
          <div className="relative h-64 border-b border-line pb-6 pt-16">
            {/* Horizontal grid lines at 25/50/75/100% of max height */}
            {[25, 50, 75, 100].map((t) => (
              <div key={t} className="pointer-events-none absolute inset-x-0" style={{ bottom: `calc(1.5rem + ${t}% * 0.01 * (100% - 5.5rem))` }}>
                <div className="border-t border-dashed border-line/70" />
                <span className="absolute -top-2 left-0 font-mono text-[10px] text-faint">
                  {normalized ? `${(maxBinPct * (t / 100)).toFixed(1)}%` : `${round(maxBinCount * (t / 100))}`}
                </span>
              </div>
            ))}
            {/* Vertical grid lines at regular dollar ticks */}
            {xTicks.map((t) => (
              <div
                key={t}
                className="pointer-events-none absolute bottom-6 top-16 z-0"
                style={{ left: `${valueToXPct(t)}%` }}
              >
                <div className="absolute inset-y-0 w-px bg-line/50" />
              </div>
            ))}
            {/* Subtle grayed-out dotted zero line (no pill, no footer) */}
            {histLo <= 0 && histHi >= 0 && (
              <div
                className="pointer-events-none absolute bottom-6 top-16 z-10"
                style={{ left: `${valueToXPct(0)}%` }}
                title="$0.00"
              >
                <div className="h-full w-px border-l border-dotted border-muted/60" />
              </div>
            )}
            {/* Faint quartile / ±1σ spread markers (bottom labels, muted) */}
            {spreadLines.map((s) => (
              <div
                key={s.key}
                className="pointer-events-none absolute bottom-6 top-16 z-[5]"
                style={{ left: `${valueToXPct(s.value)}%` }}
                title={s.title}
              >
                <div className={`h-full w-px ${s.arm === 'B' ? 'bg-emerald-500/30' : 'bg-slate-400/30'} [background-image:linear-gradient(to_bottom,currentColor_40%,transparent_40%)] [background-size:1px_4px] bg-transparent`} />
                <div className="absolute inset-x-0 bottom-0 -translate-x-1/2 whitespace-nowrap text-center font-mono text-[10px] font-medium text-faint">
                  {s.label}
                </div>
              </div>
            ))}
            {/* $1.00 stick bars */}
            <div className="absolute inset-x-0 bottom-6 top-16 flex items-end gap-[1px]">
              {histogram.map((bin) => {
                const hA = normalized ? (bin.baselinePct / maxBinPct) * 100 : (bin.baselineCount / maxBinCount) * 100
                const hB = normalized ? (bin.candidatePct / maxBinPct) * 100 : (bin.candidateCount / maxBinCount) * 100
                const isPositive = bin.range[0] >= 0
                return (
                  <div
                    key={bin.label}
                    className="group relative flex h-full flex-1 flex-col justify-end rounded-t-sm transition-colors hover:bg-surface-2/40"
                    title={`${bin.label} — Base ${bin.baselineCount} (${bin.baselinePct}%) · Cand ${bin.candidateCount} (${bin.candidatePct}%)`}
                  >
                    {/* Tooltip on hover: exact $1 range, raw counts, percentages */}
                    <div className="pointer-events-none absolute -top-2 left-1/2 z-20 hidden -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-tile border border-line bg-surface px-2.5 py-1 text-[11px] shadow-sm group-hover:block">
                      <p className="font-semibold">{bin.label}</p>
                      <p className="text-muted">
                        Base: {bin.baselineCount} ({bin.baselinePct}%) · Cand: {bin.candidateCount} ({bin.candidatePct}%)
                      </p>
                    </div>
                    <div className="flex h-full items-end justify-center gap-[2px] px-px">
                      {/* Baseline A slate stick */}
                      <div className={cx('w-[3px] min-w-[3px] max-w-[4px] rounded-t-[1px] bg-muted/40', !showA && 'opacity-0')} style={{ height: showA && bin.baselineCount > 0 ? `${max(3, hA)}%` : '0%' }} />
                      {/* Candidate B emerald/accent stick */}
                      <div className={cx('w-[3px] min-w-[3px] max-w-[4px] rounded-t-[1px]', isPositive ? 'bg-success' : 'bg-accent', !showB && 'opacity-0')} style={{ height: showB && bin.candidateCount > 0 ? `${max(3, hB)}%` : '0%' }} />
                    </div>
                  </div>
                )
              })}
            </div>
            {/* Centered high-visibility mean / critical lines (line slices label dead-center) */}
            {refLines.map((line) => (
              <div
                key={line.key}
                className="pointer-events-none absolute inset-y-0 z-10"
                style={{ left: `${valueToXPct(line.value)}%` }}
                title={line.title}
              >
                <div
                  className="absolute inset-x-0 whitespace-nowrap text-center text-[12px] font-semibold"
                  style={{ top: `${line.tier * 22}px` }}
                >
                  <span className={`inline-block -translate-x-1/2 rounded bg-surface px-1.5 py-px shadow-xs ring-1 ${line.labelClass}`}>{line.label}</span>
                </div>
                <div className={`absolute bottom-6 top-16 w-px ${line.lineClass}${line.dashed ? ' [background-image:linear-gradient(to_bottom,currentColor_55%,transparent_45%)] [background-size:1px_6px] bg-transparent' : ''}`} />
              </div>
            ))}
          </div>
          {/* Clean dollar x-axis tick labels */}
          <div className="relative h-4 text-[10px] text-faint">
            {xTicks.map((t) => (
              <span
                key={t}
                className="absolute -translate-x-1/2 whitespace-nowrap font-mono"
                style={{ left: `${valueToXPct(t)}%` }}
              >
                {t === 0 ? '$0' : `${t > 0 ? '$' : '−$'}${abs(t)}`}
              </span>
            ))}
          </div>
        </div>
      </Card>

      {/* 5. Live Settled Window Stream (Recent Candidate Samples) */}
      <Card className="p-5">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-[15px] font-semibold text-fg">Recent Candidate Window Samples</h3>
            <p className="text-[12px] text-muted">
              Live sample stream recorded under Strategy B ({candidate?.windows?.length ?? 0} settled records shown).
            </p>
          </div>
          <Badge tone="neutral">Auto-updating (10s poll)</Badge>
        </div>

        {candidate?.windows && candidate.windows.length > 0 ? (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-[12.5px]">
              <thead>
                <tr className="border-b border-line font-mono text-[11px] text-faint">
                  <th className="pb-2">Window</th>
                  <th className="pb-2">Winner</th>
                  <th className="pb-2 text-right">Shares (Up / Down)</th>
                  <th className="pb-2 text-right">Pair Cost</th>
                  <th className="pb-2 text-right">Total Cost</th>
                  <th className="pb-2 text-right">Payout</th>
                  <th className="pb-2 text-right">Net PnL</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/40 font-mono">
                {candidate.windows.slice().reverse().map((w) => (
                  <tr key={w.slug} className="hover:bg-surface-2/30">
                    <td className="py-2.5 font-medium text-fg">{w.slug}</td>
                    <td className="py-2.5">
                      <span className={w.winner === 'Up' ? 'text-success' : 'text-danger'}>
                        {w.winner ?? '—'}
                      </span>
                    </td>
                    <td className="py-2.5 text-right text-muted">
                      {trim2(w.upShares)} / {trim2(w.downShares)} {w.imbalance > 0 && <span className="text-warning">(!{trim2(w.imbalance)})</span>}
                    </td>
                    <td className="py-2.5 text-right font-medium">
                      <span className={w.pairCost && w.pairCost <= 0.995 ? 'text-success' : 'text-danger'}>
                        {w.pairCost ? `$${w.pairCost.toFixed(4)}` : '—'}
                      </span>
                    </td>
                    <td className="py-2.5 text-right text-muted">${w.cost.toFixed(2)}</td>
                    <td className="py-2.5 text-right text-muted">${w.payout.toFixed(2)}</td>
                    <td className="py-2.5 text-right font-bold">
                      <span className={w.net > 0 ? 'text-success' : w.net < 0 ? 'text-danger' : 'text-muted'}>
                        {money(w.net)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="mt-6 flex flex-col items-center justify-center rounded-tile border border-dashed border-line py-10 text-center">
            <FlaskConical className="size-8 text-faint" />
            <p className="mt-2 text-[14px] font-medium text-fg">No candidate samples gathered yet</p>
            <p className="mt-1 text-[12px] text-muted">
              Click "Launch Candidate Run (B)" above to start the live paper trading loop under the Hydrogen v1.1 configuration.
            </p>
          </div>
        )}
      </Card>
    </div>
  )
}
