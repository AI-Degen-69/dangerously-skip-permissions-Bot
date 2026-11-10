import { useMemo, useState } from 'react'
import {
  AlertCircle,
  BarChart3,
  FlaskConical,
  Play,
  RefreshCw,
  Scale,
  Sparkles,
  Square,
} from 'lucide-react'

import {
  useAbTestData,
  useStartAbCandidate,
  useStopAbCandidate,
  useBotControl,
} from '../lib/bot'
import { Badge, Button, Card, PageHeader, useToast } from '../components/ui'
import { cx } from '../lib/cx'
import { tweakCards } from '../strategyCopy'

const money = (val: number | null | undefined, digits = 2) =>
  val == null ? '—' : `${val < 0 ? '−' : val > 0 ? '+' : ''}$${Math.abs(val).toFixed(digits)}`

const pct = (val: number | null | undefined) =>
  val == null ? '—' : `${(val * 100).toFixed(1)}%`

const TEX: Record<string, string> = {
  '\\alpha': 'α', '\\beta': 'β', '\\mu': 'μ', '\\sigma': 'σ', '\\ge': '≥', '\\le': '≤',
  '\\geq': '≥', '\\leq': '≤', '\\ne': '≠', '\\to': '→', '\\cdot': '·', '\\times': '×',
}

/** Render a math-like token: Greek/TeX → Unicode, `x_{sub}`/`x_sub` → subscript, italic. */
function Var({ children }: { children: string }) {
  const src = children.replace(/\\[a-zA-Z]+/g, (m) => TEX[m] ?? m)
  const parts: React.ReactNode[] = []
  const re = /_(\{[^}]+\}|[A-Za-z0-9.]*[A-Za-z0-9])/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(src))) {
    if (m.index > last) parts.push(src.slice(last, m.index))
    parts.push(<sub key={m.index} className="text-[0.7em] not-italic">{m[1].replace(/^\{|\}$/g, '')}</sub>)
    last = m.index + m[0].length
  }
  if (last < src.length) parts.push(src.slice(last))
  return (
    <span className="mx-px whitespace-nowrap rounded-[4px] bg-accent/15 px-1 font-serif italic text-accent">
      {parts}
    </span>
  )
}

const TOKEN_RE = /(\$[^$]+\$|H[₀₁]|[μσαβ](?:_(?:\{[^}]+\}|[A-Za-z0-9.]*[A-Za-z0-9]))?|\b(?:N|t|p|d|df)\b(?=[\s,.:;)=<>≥≤-]|$))/g

/** Inline text with math: `$...$` is TeX-lite; known variables (H₀, μ, α, t, p, N…) are auto-highlighted. */
function Rich({ text }: { text: string }) {
  const out: React.ReactNode[] = []
  let last = 0
  let m: RegExpExecArray | null
  const re = new RegExp(TOKEN_RE.source, 'g')
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const tok = m[0]
    out.push(<Var key={m.index}>{tok.startsWith('$') ? tok.slice(1, -1) : tok}</Var>)
    last = m.index + tok.length
  }
  if (last < text.length) out.push(text.slice(last))
  return <>{out}</>
}

export function AbTest() {
  const { data, refetch } = useAbTestData()
  const control = useBotControl()
  const startCandidate = useStartAbCandidate()
  const stopCandidate = useStopAbCandidate()
  const toast = useToast()
  const [selectedBin, setSelectedBin] = useState<string | null>(null)

  const isCandidateRunning = Boolean(
    control.data?.running &&
    ((control.data?.activeRunId && data?.candidate?.runId && control.data.activeRunId === data.candidate.runId) ||
     (control.data?.strategy?.id && (control.data.strategy.id.endsWith('v2.2') || control.data.strategy.id.endsWith('v2.3'))))
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
  const hypotheses = data?.hypotheses
  const histogram = data?.histogram ?? []

  // Maximum histogram count for scaling bar heights
  const [showA, setShowA] = useState(true)
  const [showB, setShowB] = useState(true)
  const maxBinCount = useMemo(() => {
    let m = 1
    for (const b of histogram) {
      if (showA && b.baselineCount > m) m = b.baselineCount
      if (showB && b.candidateCount > m) m = b.candidateCount
    }
    return m
  }, [histogram, showA, showB])

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
                className="gap-1.5 bg-accent text-white hover:bg-accent/90"
              >
                <Play className="size-3.5 fill-current" />
                Launch Candidate Run (B)
              </Button>
            )}
          </div>
        }
      />

      {/* 1. Executive Statistical Verdict Banner */}
      {stats && (
        <Card className="relative overflow-hidden border border-line bg-gradient-to-r from-surface to-surface-2 p-5 shadow-xs">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="flex size-7 items-center justify-center rounded-[8px] bg-accent/15 text-accent">
                  <FlaskConical className="size-4" />
                </span>
                <span className="font-mono text-[11px] font-bold uppercase tracking-wider text-muted">
                  Statistical Test Status
                </span>
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
                  className="font-medium"
                >
                  {stats.verdict}
                </Badge>
              </div>
              <p className="text-[14.5px] font-semibold text-fg">
                Welch's Two-Sample <Var>t</Var>-Test: <Var>{`t = ${stats.tStatistic.toFixed(3)}`}</Var> vs <Var>{`t_{crit} = ${stats.tCritical.toFixed(3)}`}</Var> (one-tailed, <Var>{`\\alpha = ${stats.alpha}`}</Var>)
              </p>
              <p className="text-[12.5px] text-muted">
                Observed <Var>p</Var>-value: <strong className="font-mono text-fg">{stats.pValue.toFixed(4)}</strong> · Degrees of freedom: <strong className="font-mono text-fg">{stats.degreesOfFreedom.toFixed(1)}</strong> · Cohen's <Var>d</Var>: <strong className="font-mono text-fg">{stats.cohenD.toFixed(3)}</strong>
              </p>
            </div>

            {/* Target Sample Size Progress Gauge */}
            <div className="min-w-[260px] rounded-tile border border-line-strong bg-surface/80 p-3.5">
              <div className="flex items-center justify-between text-[12px]">
                <span className="font-medium text-muted">Sample Size Progress</span>
                <span className="font-mono font-bold text-fg">
                  {candidate?.samples ?? 0} / {stats.targetSampleSize} windows
                </span>
              </div>
              <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full bg-accent transition-all duration-500"
                  style={{ width: `${candidate?.progressPct ?? 0}%` }}
                />
              </div>
              <div className="mt-1.5 flex items-center justify-between text-[11px] text-faint">
                <span>Power: 80% (1 − <Var>β</Var>)</span>
                <span>{candidate?.progressPct ?? 0}% collected</span>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* 2. Formal Hypothesis & Scientific Design Specification */}
      <Card className="p-5">
        <div className="mb-4 flex items-center gap-2">
          <Scale className="size-4 text-accent" />
          <h2 className="text-[15px] font-semibold text-fg">Formal Scientific Hypothesis & Decision Boundary</h2>
        </div>

        <div className="grid gap-3.5 md:grid-cols-2">
          <div className="rounded-tile border border-line bg-surface-2/40 p-4">
            <span className="inline-flex items-center gap-1.5 font-mono text-[11px] font-bold uppercase tracking-wider text-danger">
              <AlertCircle className="size-3.5" /> Null Hypothesis (<Var>H_0</Var>)
            </span>
            <p className="mt-1.5 text-[13px] font-medium leading-relaxed text-fg">
              <Rich text={hypotheses?.nullHypothesis ?? 'H₀: μ_v2.2 ≤ μ_v2.0 — Confidence-based sizing produces no positive statistical advantage.'} />
            </p>
            <p className="mt-1 text-[11.5px] leading-relaxed text-muted">
              Any observed difference in window PnL is attributed to random microstructure variance or market drift.
            </p>
          </div>

          <div className="rounded-tile border border-line bg-surface-2/40 p-4">
            <span className="inline-flex items-center gap-1.5 font-mono text-[11px] font-bold uppercase tracking-wider text-success">
              <Sparkles className="size-3.5" /> Alternative Hypothesis (<Var>H_1</Var>)
            </span>
            <p className="mt-1.5 text-[13px] font-medium leading-relaxed text-fg">
              <Rich text={hypotheses?.altHypothesis ?? 'H₁: μ_v2.2 > 0 and μ_v2.2 > μ_v2.0 — Confidence-based sizing generates a statistically significant positive expected return.'} />
            </p>
            <p className="mt-1 text-[11.5px] leading-relaxed text-muted">
              <Rich text="Reject $H_0$ if test statistic $t \ge 1.658$ ($p \le 0.05$) upon reaching target sample size $N = 113$ windows." />
            </p>
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
                <span className="font-mono text-[10.5px] font-bold text-accent">Tweak 1 · Hard Gate</span>
                <Badge tone="success" className="text-[10px]">{tw[0].badge}</Badge>
              </div>
              <p className="mt-1 text-[12.5px] font-semibold text-fg">{tw[0].title}</p>
              <p className="mt-1 text-[11px] text-muted">
                {tw[0].body}
              </p>
            </div>

            <div className="rounded-[9px] border border-line bg-surface p-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10.5px] font-bold text-accent">Tweak 2 · Intake</span>
                <Badge tone="accent" className="text-[10px]">{tw[1].badge}</Badge>
              </div>
              <p className="mt-1 text-[12.5px] font-semibold text-fg">{tw[1].title}</p>
              <p className="mt-1 text-[11px] text-muted">
                {tw[1].body}
              </p>
            </div>

            <div className="rounded-[9px] border border-line bg-surface p-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10.5px] font-bold text-accent">Tweak 3 · Sweep</span>
                <Badge tone="info" className="text-[10px]">{tw[2].badge}</Badge>
              </div>
              <p className="mt-1 text-[12.5px] font-semibold text-fg">{tw[2].title}</p>
              <p className="mt-1 text-[11px] text-muted">
                {tw[2].body}
              </p>
            </div>
          </div>
        </div>
      </Card>

      {/* 3. Comparative Scorecard: Strategy A (Baseline) vs Strategy B (Candidate) */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* Baseline Card */}
        <Card className="flex flex-col justify-between p-5">
          <div className="space-y-3">
            <div className="flex items-start justify-between">
              <div>
                <span className="inline-flex items-center gap-1 rounded-[6px] bg-surface-2 px-2 py-0.5 font-mono text-[11px] font-bold text-muted">
                  STRATEGY A · BASELINE
                </span>
                <h3 className="mt-1 text-[16px] font-semibold text-fg">{baseline?.name ?? 'DSP v2.0 (Baseline)'}</h3>
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
              </div>
            </div>

            <div className="space-y-1.5 pt-2 text-[12px]">
              <div className="flex justify-between border-b border-line/60 pb-1">
                <span className="text-muted">Mean Pair Cost</span>
                <span className="font-mono font-medium text-fg">{baseline?.meanPairCost ? `$${baseline.meanPairCost.toFixed(4)}` : '—'}</span>
              </div>
              <div className="flex justify-between border-b border-line/60 pb-1">
                <span className="text-muted">Standard Deviation (<Var>s_A</Var>)</span>
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
        <Card className="flex flex-col justify-between border-accent/40 p-5 shadow-xs">
          <div className="space-y-3">
            <div className="flex items-start justify-between">
              <div>
                <span className="inline-flex items-center gap-1 rounded-[6px] bg-accent/15 px-2 py-0.5 font-mono text-[11px] font-bold text-accent">
                  STRATEGY B · CANDIDATE
                </span>
                <h3 className="mt-1 text-[16px] font-semibold text-fg">{candidate?.name ?? 'DSP v2.2 (Confidence Sizing)'}</h3>
                <p className="text-[12px] text-muted">{candidate?.description}</p>
              </div>
              <Badge tone={isCandidateRunning ? 'success' : 'accent'}>
                {isCandidateRunning ? 'Live Sampling' : 'Ready'}
              </Badge>
            </div>

            <div className="grid grid-cols-2 gap-2.5 pt-2 sm:grid-cols-4">
              <div className="rounded-[8px] bg-surface-2/60 p-2.5">
                <span className="text-[11px] text-muted">Samples (<Var>N_B</Var>)</span>
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
                <span className="text-muted">Standard Deviation (<Var>s_B</Var>)</span>
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
              Auto-updating distribution: Baseline Strategy A (Slate) vs Candidate Strategy B (Emerald) across 5-minute window returns.
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
          </div>
        </div>

        {/* Histogram Visualization */}
        <div className="mt-6 space-y-2">
          <div className="flex h-52 items-end gap-2 border-b border-line pb-2 pt-4">
            {histogram.map((bin) => {
              const hA = (bin.baselineCount / maxBinCount) * 100
              const hB = (bin.candidateCount / maxBinCount) * 100
              const isSelected = selectedBin === bin.label
              const isPositive = bin.range[0] >= 0

              return (
                <div
                  key={bin.label}
                  className={cx(
                    'group relative flex h-full flex-1 cursor-pointer flex-col justify-end rounded-t-sm transition-colors hover:bg-surface-2/40',
                    isSelected && 'bg-surface-2/60',
                  )}
                  onClick={() => setSelectedBin(bin.label)}
                >
                  {/* Tooltip on hover */}
                  <div className="pointer-events-none absolute -top-12 left-1/2 z-20 hidden -translate-x-1/2 whitespace-nowrap rounded-tile border border-line bg-surface px-2.5 py-1 text-[11px] shadow-sm group-hover:block">
                    <p className="font-semibold">{bin.label}</p>
                    <p className="text-muted">
                      Base: {bin.baselineCount} ({bin.baselinePct}%) · Cand: {bin.candidateCount} ({bin.candidatePct}%)
                    </p>
                  </div>

                  <div className="flex h-full items-end justify-center gap-1 px-0.5">
                    {/* Baseline Bar */}
                    <div className={cx('w-1/2 rounded-t-[2px] bg-muted/40 transition-all duration-300', !showA && 'opacity-0')} style={{ height: showA && bin.baselineCount > 0 ? `${Math.max(4, hA)}%` : '0%' }} />
                    {/* Candidate Bar */}
                    <div className={cx('w-1/2 rounded-t-[2px] transition-all duration-300', isPositive ? 'bg-success' : 'bg-accent', !showB && 'opacity-0')} style={{ height: showB && bin.candidateCount > 0 ? `${Math.max(4, hB)}%` : '0%' }} />
                  </div>
                </div>
              )
            })}
          </div>

          {/* Histogram X-Axis Labels */}
          <div className="flex gap-2 text-[10px] text-faint">
            {histogram.map((bin) => (
              <div key={bin.label} className="flex-1 truncate text-center font-mono">
                {bin.label.replace('..', ' to ')}
              </div>
            ))}
          </div>
        </div>

        {/* Zero Boundary Marker */}
        <div className="mt-3 flex items-center justify-between text-[11.5px] text-faint">
          <span className="flex items-center gap-1 text-danger">
            ← Net Negative Windows (Loss Drag)
          </span>
          <span className="font-mono font-semibold text-fg">Critical Zero Cutoff ($0.00)</span>
          <span className="flex items-center gap-1 text-success">
            Net Positive Windows (Arb Profit) →
          </span>
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
          <Badge tone="neutral">Auto-updating (3s poll)</Badge>
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
                      {w.upShares} / {w.downShares} {w.imbalance > 0 && <span className="text-warning">(!{w.imbalance})</span>}
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
              Click "Launch Candidate Run (B)" above to start the live paper trading loop under the DSP v2.2 (Confidence Sizing) configuration.
            </p>
          </div>
        )}
      </Card>
    </div>
  )
}
