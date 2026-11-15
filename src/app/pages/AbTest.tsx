import { useMemo, useState, type ReactNode } from 'react'
import {
  AlertCircle,
  Award,
  BarChart3,
  Check,
  Clock,
  Filter,
  FlaskConical,
  Layers,
  Play,
  RefreshCw,
  Scale,
  Sparkles,
  Square,
  Target,
  TrendingUp,
} from 'lucide-react'
import katex from 'katex'
import 'katex/dist/katex.min.css'

import {
  type AbTestDistributionStats,
  useAbTestData,
  useStartAbCandidate,
  useStopAbCandidate,
  useBotControl,
} from '../lib/bot'
import { MAKER_REBATE_SHARE, useAccountTier, useIncludeRebates } from '../lib/rebates'
import { PageHeader, useToast } from '../components/ui'
import { StatusDot, type StatusDotTone } from '../components/StatusDot'
import { cx } from '../lib/cx'
import { tweakCards } from '../strategyCopy'
import { Badge as ShadcnBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Spinner } from '@/components/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
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

const { abs, max, min, ceil, round } = globalThis.Math

const money = (val: number | null | undefined, digits = 2) =>
  val == null ? '—' : `${val < 0 ? '−' : val > 0 ? '+' : ''}$${abs(val).toFixed(digits)}`

const pct = (val: number | null | undefined) =>
  val == null ? '—' : `${(val * 100).toFixed(1)}%`

/** KaTeX-safe dollar formatting for inside String.raw tex: escaped \$ so $ never breaks math mode. */
const katexMoney = (val: number | null | undefined, digits = 2) =>
  val == null ? '\\text{--}' : `${val < 0 ? '-' : val > 0 ? '+' : ''}\\$${abs(val).toFixed(digits)}`

/** Rebate credit for one arm, same inputs as the dashboard (windowRebate summed). */
const armRebate = (
  s: { feesUsd?: number | null; makerFeeBaseUsd?: number | null } | null | undefined,
  rate: number,
  enabled: boolean,
) => (enabled ? (s?.feesUsd ?? 0) * rate + MAKER_REBATE_SHARE * (s?.makerFeeBaseUsd ?? 0) : 0)

/** Kill float noise: 36.980000000000004 → 36.98, 135 → 135. */
const trim2 = (val: number) => Number(val.toFixed(2))

/** One row of the compact parameter spec grid on a scorecard. */
interface SpecRow {
  key: string
  label: string
  value: string
}

/** Six decision-grade knobs read straight off the arm's live entry snapshot. */
function specRows(entry: Record<string, unknown> | undefined): SpecRow[] {
  const e = entry ?? {}
  const num = (v: unknown, fb: number) => {
    const n = Number(v)
    return Number.isFinite(n) ? n : fb
  }
  const clip = num(e.clipSharesDefault, 10)
  const maxClip = num(e.maxClipShares ?? e.maxShares, 45)
  const lead = num(e.maxShareLead, 15)
  const taker = e.takerDipEntryMax != null ? `${round(num(e.takerDipEntryMax, 0.36) * 100)}c` : '—'
  const tgt = num(e.targetPairCost ?? e.benchmarkPairCost, 0.965)
  const cap = num(e.maxPairCost, 0.985)
  const gapUsd = num(e.maxUnhedgedUsd, 0)
  const gapSh = num(e.maxUnhedgedShares ?? lead, lead)
  const rescue = num(e.rescuePairCostMax ?? e.lateRescueMaxPairCost, 0.995)
  return [
    { key: 'clips', label: 'Clips', value: `${clip} to ${maxClip} sh` },
    { key: 'lead', label: 'Lead Veto', value: `${lead} sh` },
    { key: 'taker', label: 'Taker Dip', value: taker },
    { key: 'pairCap', label: 'Pair Cap', value: `$${tgt.toFixed(3)} / $${cap.toFixed(3)}` },
    { key: 'gapCap', label: 'Gap Cap', value: gapUsd > 0 ? `$${gapUsd.toFixed(0)}` : `${gapSh} sh` },
    { key: 'rescue', label: 'Rescue', value: `$${rescue.toFixed(3)}` },
  ]
}

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

interface ScorecardProps {
  arm: AbTestDistributionStats | null | undefined
  label: string
  kicker: string
  tag: string
  nTag: string
  badge: React.ReactNode
  highlight: boolean
  rebates: { name: string; rate: number }
  includeRebates: boolean
  changed: Set<string>
}

/** One arm of the A/B scorecard: spec grid, four KPIs, four diagnostics. */
function Scorecard({
  arm,
  label,
  kicker,
  tag,
  nTag,
  badge,
  highlight,
  rebates,
  includeRebates,
  changed,
}: ScorecardProps) {
  const [rulebook, setRulebook] = useState(false)
  const specs = specRows(arm?.entry)
  const hasSamples = (arm?.samples ?? 0) > 0
  const rebate = armRebate(arm, rebates.rate, includeRebates)
  const rebated = (arm?.netPnl ?? 0) + rebate
  const pairedPct = arm && arm.activeWindows > 0 ? (arm.pairedWindows / arm.activeWindows) * 100 : 0
  const subDollarPct = arm && arm.pairedWindows > 0 ? (arm.subDollarPairs / arm.pairedWindows) * 100 : 0

  return (
    <Card className={cx('grid grid-rows-subgrid row-span-5 gap-y-3 p-5', highlight && 'border-emerald-500/40 shadow-xs')}>
      <div className="contents">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span
              className={cx(
                'grid size-8 shrink-0 place-items-center rounded-xl',
                highlight ? 'bg-emerald-500/15 text-emerald-500' : 'bg-muted text-muted-foreground',
              )}
            >
              {highlight ? <FlaskConical className="size-4" /> : <Layers className="size-4" />}
            </span>
            <div className="min-w-0">
              <span
                className={cx(
                  'inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 font-mono text-[10px] font-bold',
                  highlight ? 'bg-emerald-500/15 text-emerald-600' : 'bg-surface-2 text-muted',
                )}
              >
                {kicker}
              </span>
              <h3 className="mt-0.5 truncate font-heading text-[15px] font-semibold text-foreground">{label}</h3>
            </div>
          </div>
          {badge}
        </div>

        {/* Compact 6-item parameter spec grid */}
        <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 rounded-tile border border-line bg-surface-2/40 p-2.5 sm:grid-cols-3">
          {specs.map((s) => (
            <div key={s.key} className="min-w-0">
              <span className="block text-[10px] uppercase tracking-wide text-faint">{s.label}</span>
              <span
                className={cx(
                  'block truncate font-mono text-[11.5px] font-semibold',
                  highlight && changed.has(s.key) ? 'text-emerald-600' : 'text-fg',
                )}
                title={s.value}
              >
                {s.value}
              </span>
            </div>
          ))}
        </div>

        {/* Full rulebook toggle */}
        <div>
          <button
            type="button"
            aria-expanded={rulebook}
            onClick={() => setRulebook((v) => !v)}
            className="font-mono text-[10.5px] font-semibold uppercase tracking-wider text-muted transition-colors hover:text-fg"
          >
            {rulebook ? '- Hide full rulebook' : '+ Full rulebook'}
          </button>
          {rulebook ? <p className="mt-1 text-[11.5px] leading-relaxed text-muted">{arm?.description}</p> : null}
        </div>

        {/* Standardized 4 KPI tiles */}
        <div className="grid grid-cols-2 gap-2.5 pt-1 sm:grid-cols-4">
          <div className="rounded-[8px] bg-surface-2/60 p-2.5">
            <span className="text-[11px] text-muted">
              Active Windows (<Math tex={String.raw`${nTag}`} className="text-[11px]" />)
            </span>
            <p className="mt-0.5 font-mono text-[15px] font-bold text-fg">
              {arm?.activeWindows ?? 0}
              <span className="text-[11px] text-faint"> / {arm?.observedWindows ?? 0}</span>
            </p>
          </div>
          <div className="rounded-[8px] bg-surface-2/60 p-2.5">
            <span className="text-[11px] text-muted">Mean Window PnL</span>
            <p
              className={cx(
                'mt-0.5 font-mono text-[15px] font-bold',
                !hasSamples ? 'text-muted' : (arm?.meanPnl ?? 0) < 0 ? 'text-danger' : 'text-success',
              )}
            >
              {hasSamples ? money(arm?.meanPnl, 4) : 'Pending'}
            </p>
            <p className="mt-0.5 font-mono text-[10.5px] text-faint">
              Median <Math tex={String.raw`P_{50} = ${katexMoney(arm?.medianPnl)}`} />
            </p>
          </div>
          <div className="rounded-[8px] bg-surface-2/60 p-2.5">
            <span className="text-[11px] text-muted">Win Rate</span>
            <p className="mt-0.5 font-mono text-[15px] font-bold text-fg">
              {hasSamples ? pct(arm?.winRate) : 'Pending'}
            </p>
            <p className="mt-0.5 font-mono text-[10.5px] text-faint">
              {arm?.wins ?? 0}W–{arm?.losses ?? 0}L
            </p>
          </div>
          <div className="rounded-[8px] bg-surface-2/60 p-2.5">
            <span className="text-[11px] text-muted">Total Net PnL</span>
            <p
              className={cx(
                'mt-0.5 font-mono text-[15px] font-bold',
                !hasSamples ? 'text-muted' : (arm?.netPnl ?? 0) < 0 ? 'text-danger' : 'text-success',
              )}
            >
              {hasSamples ? money(arm?.netPnl) : 'Pending'}
            </p>
            {hasSamples ? (
              <p
                className="mt-0.5 font-mono text-[10.5px] text-muted"
                title={`Rebates at ${rebates.name} tier${includeRebates ? '' : ' (excluded)'}`}
              >
                with rebates {money(rebated)}
              </p>
            ) : null}
          </div>
        </div>

        {/* Four diagnostic rows */}
        <div className="space-y-1.5 pt-1 text-[12px]">
          <div className="flex items-baseline justify-between gap-2 border-b border-line/60 pb-1">
            <span className="text-muted">Paired vs One-Sided PnL</span>
            <span className="truncate font-mono font-medium text-fg">
              <span className={(arm?.pairedPnl ?? 0) < 0 ? 'text-danger' : 'text-success'}>{money(arm?.pairedPnl)}</span>
              <span className="text-faint"> (<Math tex={String.raw`n = ${arm?.pairedWindows ?? 0}`} className="text-[11.5px]" />)</span>
              <span className="text-faint"> / </span>
              <span className={(arm?.oneSidedPnl ?? 0) < 0 ? 'text-danger' : 'text-success'}>{money(arm?.oneSidedPnl)}</span>
              <span className="text-faint"> (<Math tex={String.raw`n = ${arm?.oneSidedWindows ?? 0}`} className="text-[11.5px]" />)</span>
            </span>
          </div>
          <div className="flex items-baseline justify-between gap-2 border-b border-line/60 pb-1">
            <span className="text-muted">Pair Quality</span>
            <span className="truncate font-mono font-medium text-fg">
              {pct(pairedPct / 100)} paired · {pct(subDollarPct / 100)} sub-$1 · {arm?.meanPairCost ? `$${arm.meanPairCost.toFixed(4)}` : '—'}
            </span>
          </div>
          <div className="flex items-baseline justify-between gap-2 border-b border-line/60 pb-1">
            <span className="text-muted">
              Volatility &amp; IQR (<Math tex={String.raw`${tag}`} />)
            </span>
            <span className="truncate font-mono font-medium text-fg">
              <Math tex={String.raw`s = \$${(arm?.stdPnl ?? 0).toFixed(2)}`} /> ·{' '}
              <Math tex={String.raw`P_{25} = ${katexMoney(arm?.q25Pnl)}`} /> ·{' '}
              <Math tex={String.raw`P_{75} = ${katexMoney(arm?.q75Pnl)}`} />
            </span>
          </div>
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-muted">Worst / Best Window</span>
            <span className="truncate font-mono font-medium">
              <span className={(arm?.minPnl ?? 0) < 0 ? 'text-danger' : 'text-fg'}>{money(arm?.minPnl)}</span>
              <span className="text-faint"> / </span>
              <span className={(arm?.maxPnl ?? 0) > 0 ? 'text-success' : 'text-fg'}>{money(arm?.maxPnl)}</span>
            </span>
          </div>
        </div>
      </div>
    </Card>
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
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : 'Error starting candidate run'
      toast('Failed to Start Candidate' + ': ' + detail, 'danger')
    }
  }

  const handleStop = async () => {
    try {
      await stopCandidate.mutateAsync()
      toast('Candidate Run Stopped — Testing paused. Sample data is safely preserved.')
      refetch()
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : 'Error stopping candidate run'
      toast('Failed to Stop' + ': ' + detail, 'danger')
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
  const subB = cleanSub(candidate?.name ?? control.data?.strategy?.name, 'v1.2')
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
  // null = follow the data-driven default (Core when the tails run wider than +-20).
  const [domainMode, setDomainMode] = useState<'core' | 'full' | null>(null)
  const [showQuantiles, setShowQuantiles] = useState(false)

  const fullLo = histogram.length > 0 ? histogram[0].range[0] : 0
  const fullHi = histogram.length > 0 ? histogram[histogram.length - 1].range[1] : 1
  const isCore = domainMode === null ? fullLo < -20 || fullHi > 20 : domainMode === 'core'
  const domainBins = useMemo(
    () => (isCore ? histogram.filter((b) => b.range[1] > -15 && b.range[0] < 15) : histogram),
    [histogram, isCore],
  )
  // Windows sitting in the clipped tails, so Core never silently drops evidence.
  const clipped = useMemo(() => {
    if (!isCore) return { a: 0, b: 0, pctA: 0, pctB: 0 }
    const outside = (v: number) => v < -15 || v >= 15
    const aList = baseline?.pnlList ?? []
    const bList = candidate?.pnlList ?? []
    const a = aList.filter(outside).length
    const b = bList.filter(outside).length
    return {
      a,
      b,
      pctA: aList.length > 0 ? round((a / aList.length) * 100) : 0,
      pctB: bList.length > 0 ? round((b / bList.length) * 100) : 0,
    }
  }, [isCore, baseline, candidate])
  const maxBinCount = useMemo(() => {
    let m = 1
    for (const b of domainBins) {
      if (showA && b.baselineCount > m) m = b.baselineCount
      if (showB && b.candidateCount > m) m = b.candidateCount
    }
    return m
  }, [domainBins, showA, showB])
  const maxBinPct = useMemo(() => {
    let m = 1
    for (const b of domainBins) {
      if (showA && b.baselinePct > m) m = b.baselinePct
      if (showB && b.candidatePct > m) m = b.candidatePct
    }
    return m
  }, [domainBins, showA, showB])

  // Linear dollar x-axis over the full-range $1 bins: contiguous [k, k+1)
  // sticks, so a value maps proportionally between the first bin low and
  // the last bin high.
  const histLo = domainBins.length > 0 ? domainBins[0].range[0] : 0
  const histHi = domainBins.length > 0 ? domainBins[domainBins.length - 1].range[1] : 1
  const histSpan = max(1, histHi - histLo)
  const valueToXPct = (v: number): number => {
    if (domainBins.length === 0) return 0
    const frac = (v - histLo) / histSpan
    return min(100, max(0, frac * 100))
  }
  /** True when a reference value falls inside the visible domain. */
  const inDomain = (v: number) => v >= histLo && v <= histHi
  // Vertical grid ticks at regular dollar steps ($5, or $10 for wide ranges),
  // always marking $0.
  const xTicks = useMemo(() => {
    if (domainBins.length === 0) return [] as number[]
    const step = histSpan > 40 ? 10 : 5
    const ticks: number[] = []
    for (let t = ceil(histLo / step) * step; t <= histHi; t += step) ticks.push(t)
    if (!ticks.includes(0) && histLo <= 0 && histHi >= 0) ticks.push(0)
    return ticks.sort((a, b) => a - b)
  }, [domainBins, histLo, histHi, histSpan])
  // Centered high-visibility reference lines: mu_A (slate), mu_B (emerald),
  // mu_crit (RED). Zero is a subtle dotted line with no pill. Tiers stagger
  // only when adjacent labels sit within ~8% x-distance so they never touch.
  const refLines = useMemo(() => {
    type RefLine = { key: string; value: number; label: React.ReactNode; title: string; lineClass: string; labelClass: string; dashed: boolean; tier: number }
    const mains: Omit<RefLine, 'tier'>[] = []
    if (baseline != null && inDomain(baseline.meanPnl)) {
      mains.push({ key: 'muA', value: baseline.meanPnl, label: <Math tex={String.raw`\mu_A = ${katexMoney(baseline.meanPnl)}`} />, title: `μ_A $${baseline.meanPnl.toFixed(2)}`, lineClass: 'bg-slate-400', labelClass: 'text-muted ring-line', dashed: true })
    }
    if (candidate != null && (candidate.samples ?? 0) > 0 && inDomain(candidate.meanPnl)) {
      mains.push({ key: 'muB', value: candidate.meanPnl, label: <Math tex={String.raw`\mu_B = ${katexMoney(candidate.meanPnl)}`} />, title: `μ_B $${candidate.meanPnl.toFixed(2)}`, lineClass: 'bg-emerald-500', labelClass: 'text-emerald-600 ring-emerald-500/30', dashed: false })
    }
    if (stats?.muCritical != null && inDomain(stats.muCritical)) {
      mains.push({ key: 'mucrit', value: stats.muCritical, label: <Math tex={String.raw`\mu_{\text{crit}} = ${katexMoney(stats.muCritical)}`} />, title: `μ_crit $${stats.muCritical.toFixed(2)}`, lineClass: 'bg-danger', labelClass: 'text-danger ring-danger/40', dashed: false })
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
      if (baseline.q25Pnl != null) out.push({ key: 'q25A', value: baseline.q25Pnl, label: <Math tex={String.raw`P_{25,A}`} className="text-[10px]" />, title: `Baseline P25 $${baseline.q25Pnl.toFixed(2)}`, arm: 'A' })
      if (baseline.medianPnl != null) out.push({ key: 'p50A', value: baseline.medianPnl, label: <Math tex={String.raw`P_{50,A}`} className="text-[10px]" />, title: `Baseline P50 $${Number(baseline.medianPnl).toFixed(2)}`, arm: 'A' })
      if (baseline.q75Pnl != null) out.push({ key: 'q75A', value: baseline.q75Pnl, label: <Math tex={String.raw`P_{75,A}`} className="text-[10px]" />, title: `Baseline P75 $${baseline.q75Pnl.toFixed(2)}`, arm: 'A' })
      if (baseline.meanMinusStd != null) out.push({ key: 'm1A', value: baseline.meanMinusStd, label: <Math tex={String.raw`-1\sigma_A`} className="text-[10px]" />, title: `Baseline −1σ $${baseline.meanMinusStd.toFixed(2)}`, arm: 'A' })
      if (baseline.meanPlusStd != null) out.push({ key: 'p1A', value: baseline.meanPlusStd, label: <Math tex={String.raw`+1\sigma_A`} className="text-[10px]" />, title: `Baseline +1σ $${baseline.meanPlusStd.toFixed(2)}`, arm: 'A' })
    }
    if (candidate != null && (candidate.samples ?? 0) >= 3) {
      if (candidate.q25Pnl != null) out.push({ key: 'q25B', value: candidate.q25Pnl, label: <Math tex={String.raw`P_{25,B}`} className="text-[10px]" />, title: `Candidate P25 $${candidate.q25Pnl.toFixed(2)}`, arm: 'B' })
      if (candidate.medianPnl != null) out.push({ key: 'p50B', value: candidate.medianPnl, label: <Math tex={String.raw`P_{50,B}`} className="text-[10px]" />, title: `Candidate P50 $${Number(candidate.medianPnl).toFixed(2)}`, arm: 'B' })
      if (candidate.q75Pnl != null) out.push({ key: 'q75B', value: candidate.q75Pnl, label: <Math tex={String.raw`P_{75,B}`} className="text-[10px]" />, title: `Candidate P75 $${candidate.q75Pnl.toFixed(2)}`, arm: 'B' })
      if (candidate.meanMinusStd != null) out.push({ key: 'm1B', value: candidate.meanMinusStd, label: <Math tex={String.raw`-1\sigma_B`} className="text-[10px]" />, title: `Candidate −1σ $${candidate.meanMinusStd.toFixed(2)}`, arm: 'B' })
      if (candidate.meanPlusStd != null) out.push({ key: 'p1B', value: candidate.meanPlusStd, label: <Math tex={String.raw`+1\sigma_B`} className="text-[10px]" />, title: `Candidate +1σ $${candidate.meanPlusStd.toFixed(2)}`, arm: 'B' })
    }
    return out.filter((s) => inDomain(s.value))
  }, [baseline, candidate, histLo, histSpan])

  // Which of the six spec knobs differ between the two arms: B highlights them.
  const changedSpecs = useMemo(() => {
    const a = specRows(baseline?.entry)
    const b = specRows(candidate?.entry)
    const out = new Set<string>()
    for (const row of b) {
      const peer = a.find((r) => r.key === row.key)
      if (!peer || peer.value !== row.value) out.add(row.key)
    }
    return out
  }, [baseline, candidate])

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 p-5 pb-12 sm:p-8">
      <PageHeader
        icon={<FlaskConical className="size-5" />}
        title="A/B Hypothesis Lab"
        actions={
          <div className="flex items-center gap-2.5">
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
            >
              <RefreshCw data-icon="inline-start" className="size-3.5" />
              Refresh Data
            </Button>
            {isCandidateRunning ? (
              <Button
                variant="destructive"
                size="sm"
                onClick={handleStop}
                disabled={stopCandidate.isPending}
              >
                {stopCandidate.isPending ? (
                  <Spinner data-icon="inline-start" />
                ) : (
                  <Square data-icon="inline-start" className="size-3.5 fill-current" />
                )}
                Stop Candidate Run
              </Button>
            ) : (
              <Button
                variant="default"
                size="sm"
                onClick={handleStart}
                disabled={startCandidate.isPending}
                title="Start the candidate run under the wired strategy config"
              >
                {startCandidate.isPending ? (
                  <Spinner data-icon="inline-start" />
                ) : (
                  <Play data-icon="inline-start" className="size-3.5 fill-current" />
                )}
                Launch Candidate Run (B)
              </Button>
            )}
          </div>
        }
      />

      {/* Top Grid: Section 1 (Statistical Test Status) & Section 2 (Sample Size Progress) */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        {/* Section 1 — Statistical Test Status (Left 2×2 KPI Grid matching SVG layout) */}
        <Card className="flex flex-col justify-between gap-0 p-5 lg:col-span-7">
          <div>
            <div className="mb-3.5 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2.5">
                <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                  <FlaskConical className="size-4" />
                </span>
                <h2 className="font-heading text-[15px] font-semibold text-foreground">
                  Statistical Test Status
                </h2>
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
                  {stats.verdict.includes('(')
                    ? stats.verdict
                    : `${stats.verdict} (${candidateActive}/${targetN} active)`}
                </Badge>
              )}
            </div>

            {/* 4 Stat Tiles (2x2 Grid) */}
            {stats ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {/* Tile 1: Welch t-Statistic vs Critical */}
                <div className="flex flex-col justify-between rounded-tile border border-line bg-surface-2/60 p-3">
                  <span className="flex items-center gap-1.5 text-[11px] font-medium text-muted">
                    <Scale className="size-3 text-primary" />
                    Welch t-Statistic vs Critical
                  </span>
                  <div className="mt-1.5 flex items-baseline gap-2">
                    <span className="font-mono text-[18px] font-bold text-fg">
                      <Math tex={String.raw`t = ${stats.tStatistic.toFixed(2)}`} className="mr-0.5 text-[14px]" />
                    </span>
                    <span
                      className={cx(
                        'text-[13px] font-semibold',
                        stats.tCritical != null && stats.tStatistic >= stats.tCritical ? 'text-success' : 'text-danger',
                      )}
                    >
                      /{' '}
                      {stats.tCritical != null ? (
                        <Math tex={String.raw`t_{\text{crit}} = ${stats.tCritical.toFixed(2)}`} className="text-[12px]" />
                      ) : (
                        '—'
                      )}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-[10.5px] text-faint">
                    <Math tex={String.raw`\text{df} = ${stats.degreesOfFreedom.toFixed(1)}`} /> · one-tailed{' '}
                    <Math tex={String.raw`\alpha = ${stats.alpha}`} className="text-[10.5px]" />
                  </p>
                </div>

                {/* Tile 2: Observed p-value */}
                <div className="flex flex-col justify-between rounded-tile border border-line bg-surface-2/60 p-3">
                  <span className="flex items-center gap-1.5 text-[11px] font-medium text-muted">
                    <Target className="size-3 text-info" />
                    Observed p-value
                  </span>
                  <div className="mt-1.5 flex items-baseline gap-2">
                    <span className="font-mono text-[18px] font-bold text-fg">
                      <Math tex={String.raw`p = ${stats.pValue.toFixed(4)}`} className="mr-0.5 text-[14px]" />
                    </span>
                    <span className="text-[12px] text-muted">
                      (need <Math tex={String.raw`p \le 0.05`} className="text-[12px]" />)
                    </span>
                  </div>
                  <p className="mt-1 text-[10.5px] text-faint">
                    Cohen&apos;s <Math tex={String.raw`d = ${stats.cohenD.toFixed(3)}`} className="text-[10.5px]" /> (effect size)
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
                  <span className="flex items-center gap-1.5 text-[11px] font-medium text-muted">
                    <TrendingUp className="size-3 text-emerald-500" />
                    <span>
                      Candidate Mean (<Math tex={String.raw`\mu_B`} className="text-[11px]" />) vs Target
                    </span>
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
                        <Math tex={String.raw`\mu_{\text{crit}} = ${katexMoney(stats.muCritical)}`} className="text-[12px]" />
                      </span>
                    ) : (
                      <span className="font-mono text-[12px] text-faint">
                        pending <Math tex={String.raw`\mu_{\text{crit}}`} className="text-[11px]" />
                      </span>
                    )}
                  </div>
                  <p className="mt-1 font-mono text-[10.5px] text-faint">
                    Baseline <Math tex={String.raw`\mu_A = ${katexMoney(baseline?.meanPnl)}`} className="text-[10.5px]" /> / window
                  </p>
                </div>

                {/* Tile 4: Win Rate & Pair Quality */}
                <div className="flex flex-col justify-between rounded-tile border border-line bg-surface-2/60 p-3">
                  <span className="flex items-center gap-1.5 text-[11px] font-medium text-muted">
                    <Award className="size-3 text-amber-500" />
                    Win Rate &amp; Pair Quality
                  </span>
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
        </Card>

        {/* Section 2 — Sample Size Progress (Right Panel with 3 Visual Progress Bars) */}
        <Card className="flex flex-col justify-between gap-0 p-5 lg:col-span-5">
          <div>
            <div className="mb-3.5 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2.5">
                <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                  <Filter className="size-4" />
                </span>
                <h2 className="font-heading text-[15px] font-semibold text-foreground">
                  Sample Gates (B vs A)
                </h2>
              </div>
              <span className="font-mono text-[11px] text-faint">
                Power: 80% (<Math tex={String.raw`1 - \beta`} className="text-[11px]" />)
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
      <Card className="gap-0 p-5">
        <div className="mb-4 flex items-center gap-2.5">
          <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
            <Scale className="size-4" />
          </span>
          <h2 className="font-heading text-[15px] font-semibold text-foreground">
            Hypothesis &amp; Decision Boundary
          </h2>
        </div>

        <div className="grid gap-3.5 md:grid-cols-2">
          {/* H0 Card */}
          <div className="flex flex-col justify-between rounded-tile border border-danger/30 bg-surface-2/40 p-4">
            <div>
              <span className="inline-flex items-center gap-1.5 font-mono text-[11px] font-bold uppercase tracking-wider text-danger">
                <AlertCircle className="size-3.5" />
                <Math tex={String.raw`H_0`} className="text-[11px]" /> · STAY ON {baselineLabel.toUpperCase()}
              </span>
              <div className="mt-3">
                <Math
                  tex={String.raw`H_0: \mu_{${subB}} \le \mu_{${subA}} \;\text{or}\; \mu_{${subB}} \le 0`}
                  className="text-[16px] font-semibold text-fg sm:text-[17px]"
                />
              </div>
            </div>
            <p className="mt-3 text-[11.5px] leading-relaxed text-muted">
              Default state if <Math tex={String.raw`t < t_{\text{crit}}`} className="text-[11.5px]" /> or any sample gate is unmet.
            </p>
          </div>

          {/* H1 Card */}
          <div className="flex flex-col justify-between rounded-tile border border-success/30 bg-surface-2/40 p-4">
            <div>
              <span className="inline-flex items-center gap-1.5 font-mono text-[11px] font-bold uppercase tracking-wider text-success">
                <Sparkles className="size-3.5" />
                <Math tex={String.raw`H_1`} className="text-[11px]" /> · PROMOTE {candidateLabel.toUpperCase()} (ALL 3 REQUIRED)
              </span>
              <div className="mt-3">
                <Math
                  tex={String.raw`H_1: \mu_{${subB}} > \mu_{${subA}} \;\text{and}\; \mu_{${subB}} > 0`}
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
                  Active <Math tex={String.raw`N \ge ${targetN}`} className="text-[11px]" />
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
                  Paired <Math tex={String.raw`\ge ${targetPaired}`} className="text-[11px]" /> &amp; Sub-$1{' '}
                  <Math tex={String.raw`\ge ${targetSubDollar}`} className="text-[11px]" />
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
                  <Math tex={String.raw`t \ge t_{\text{crit}}`} className="text-[11px]" /> &amp;{' '}
                  <Math tex={String.raw`p \le 0.05`} className="text-[11px]" />
                </span>
              </span>
            </div>
          </div>
        </div>

        {/* The 3 Tested Tweaks Breakdown */}
        <div className="mt-4 border-t border-line pt-4">
          <p className="flex items-center gap-1.5 text-[12px] font-semibold text-foreground">
            <Sparkles className="size-3.5 text-primary" />
            Core Candidate Tweaks ({candidateLabel})
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
      <div className="grid gap-4 md:grid-cols-2 md:gap-y-3">
        <Scorecard
          arm={baseline}
          label={baselineLabel}
          kicker="STRATEGY A - BASELINE"
          tag="s_A"
          nTag="N_A"
          badge={<Badge tone="neutral">Reference Run</Badge>}
          highlight={false}
          rebates={tier}
          includeRebates={includeRebates}
          changed={changedSpecs}
        />
        <Scorecard
          arm={candidate}
          label={candidateLabel}
          kicker="STRATEGY B - CANDIDATE"
          tag="s_B"
          nTag="N_B"
          badge={
            <Badge tone={isCandidateRunning ? 'success' : 'neutral'} dot live={isCandidateRunning}>
              {isCandidateRunning ? 'Live Sampling' : 'Ready'}
            </Badge>
          }
          highlight
          rebates={tier}
          includeRebates={includeRebates}
          changed={changedSpecs}
        />
      </div>

      {/* 4. Comparative PnL Distribution Histogram */}
      <Card className="gap-0 p-5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2.5">
            <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
              <BarChart3 className="size-4" />
            </span>
            <h2 className="font-heading text-[15px] font-semibold text-foreground">PnL Distribution Histogram</h2>
          </div>

          <div className="flex items-center gap-4 text-[11.5px]">
            <button
              type="button"
              aria-pressed={showA}
              onClick={() => setShowA((v) => !v)}
              title={showA ? 'Click to hide Baseline A' : 'Click to show Baseline A'}
              className={cx('flex items-center gap-1.5 rounded-pill border border-line px-2.5 py-1 transition-all hover:bg-surface-2', !showA && 'opacity-45')}
            >
              <span className={cx('size-3 rounded-[3px] bg-slate-400/50', !showA && 'bg-transparent ring-1 ring-muted')} />
              <span className={cx('text-muted', !showA && 'line-through')}>Baseline A (<Math tex={String.raw`N = ${baseline?.samples ?? 0}`} />)</span>
            </button>
            <button
              type="button"
              aria-pressed={showB}
              onClick={() => setShowB((v) => !v)}
              title={showB ? 'Click to hide Candidate B' : 'Click to show Candidate B'}
              className={cx('flex items-center gap-1.5 rounded-pill border border-line px-2.5 py-1 transition-all hover:bg-surface-2', !showB && 'opacity-45')}
            >
              <span className={cx('size-3 rounded-[3px] bg-emerald-500', !showB && 'bg-transparent ring-1 ring-emerald-500')} />
              <span className={cx('font-medium text-fg', !showB && 'line-through')}>Candidate B (<Math tex={String.raw`N = ${candidate?.samples ?? 0}`} />)</span>
            </button>
            <button
              type="button"
              aria-pressed={live}
              onClick={() => setLive((v) => !v)}
              title={live ? 'Pause live updates (freezes the chart for inspection)' : 'Resume live updates (10s poll)'}
              className={cx('flex items-center gap-1.5 rounded-pill border border-line px-2.5 py-1 transition-all hover:bg-surface-2', !live && 'opacity-60')}
            >
              <StatusDot tone={live ? 'live' : 'stopped'} size="sm" />
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

        {/* Domain and quantile controls: keep the mean band legible. */}
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px]">
          <div className="flex items-center overflow-hidden rounded-pill border border-line" role="group" aria-label="Histogram domain">
            <button
              type="button"
              aria-pressed={isCore}
              onClick={() => setDomainMode('core')}
              title="Clip the axis to +-\$15 so the mean band fills the frame"
              className={cx('px-2.5 py-1 transition-all', isCore ? 'bg-accent/15 font-semibold text-fg' : 'text-muted hover:bg-surface-2')}
            >
              <Math tex={String.raw`\text{Core } (\pm\$15)`} className="text-[11px]" />
            </button>
            <button
              type="button"
              aria-pressed={!isCore}
              onClick={() => setDomainMode('full')}
              className={cx('px-2.5 py-1 transition-all', !isCore ? 'bg-accent/15 font-semibold text-fg' : 'text-muted hover:bg-surface-2')}
            >
              Full Range
            </button>
          </div>
          <button
            type="button"
            aria-pressed={showQuantiles}
            onClick={() => setShowQuantiles((v) => !v)}
            title="Overlay per-arm quartiles and +-1 sigma markers"
            className={cx(
              'rounded-pill border border-line px-2.5 py-1 transition-all hover:bg-surface-2',
              showQuantiles ? 'bg-accent/15 font-semibold text-fg' : 'text-muted',
            )}
          >
            Quantiles
          </button>
          {isCore && (clipped.a > 0 || clipped.b > 0) ? (
            <span className="font-mono text-[10.5px] text-faint">
              +{clipped.a + clipped.b} window{clipped.a + clipped.b === 1 ? '' : 's'} outside{' '}
              <Math tex={String.raw`\pm\$15`} className="text-[10.5px]" /> (A: {clipped.a} [{clipped.pctA}%] · B: {clipped.b} [{clipped.pctB}%])
            </span>
          ) : null}
        </div>

        {/* Histogram Visualization: cropped $1.00 stick bars on a linear dollar axis */}
        <div className="mt-6 space-y-2">
          <div className="relative h-64 border-b border-line pb-6 pt-16">
            {/* Horizontal grid lines at 25/50/75/100% of max height */}
            {[25, 50, 75, 100].map((t) => (
              <div
                key={t}
                className="pointer-events-none absolute inset-x-0"
                style={{ bottom: `calc(1.5rem + (100% - 5.5rem) * ${t / 100})` }}
              >
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
            {(showQuantiles ? spreadLines : []).map((s) => (
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
              {domainBins.map((bin) => {
                const hA = normalized ? (bin.baselinePct / maxBinPct) * 100 : (bin.baselineCount / maxBinCount) * 100
                const hB = normalized ? (bin.candidatePct / maxBinPct) * 100 : (bin.candidateCount / maxBinCount) * 100
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
                      <div className={cx('rounded-t-[2px] bg-slate-400/50', isCore ? 'w-2.5 max-w-[14px] sm:w-3' : 'w-[3px] max-w-[5px]', !showA && 'opacity-0')} style={{ height: showA && bin.baselineCount > 0 ? `${max(3, hA)}%` : '0%' }} />
                      {/* Candidate B emerald stick */}
                      <div className={cx('rounded-t-[2px] bg-emerald-500', isCore ? 'w-2.5 max-w-[14px] sm:w-3' : 'w-[3px] max-w-[5px]', !showB && 'opacity-0')} style={{ height: showB && bin.candidateCount > 0 ? `${max(3, hB)}%` : '0%' }} />
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
      <Card className="gap-0 p-5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
              <Clock className="size-4" />
            </span>
            <h2 className="font-heading text-[15px] font-semibold text-foreground">Recent Candidate Samples</h2>
          </div>
          <Badge tone="neutral">{candidate?.windows?.length ?? 0} windows</Badge>
        </div>

        {candidate?.windows && candidate.windows.length > 0 ? (
          <div className="mt-4 [&_[data-slot=table-container]]:max-h-[380px] [&_[data-slot=table-container]]:overflow-y-auto [&_[data-slot=table-container]]:scrollbar-thin">
            <Table className="text-left text-[12.5px]">
              <TableHeader className="sticky top-0 z-10 bg-card font-mono text-[11px] text-muted-foreground">
                <TableRow className="hover:bg-transparent">
                  <TableHead className="h-8 pb-2 text-muted-foreground">Window</TableHead>
                  <TableHead className="h-8 pb-2 text-muted-foreground">Winner</TableHead>
                  <TableHead className="h-8 pb-2 text-right text-muted-foreground">Shares (Up / Down)</TableHead>
                  <TableHead className="h-8 pb-2 text-right text-muted-foreground">Pair Cost</TableHead>
                  <TableHead className="h-8 pb-2 text-right text-muted-foreground">Total Cost</TableHead>
                  <TableHead className="h-8 pb-2 text-right text-muted-foreground">Payout</TableHead>
                  <TableHead className="h-8 pb-2 text-right text-muted-foreground">Net PnL</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody className="font-mono">
                {candidate.windows.slice().reverse().map((w) => (
                  <TableRow key={w.slug}>
                    <TableCell className="py-2.5 font-medium text-foreground">{w.slug}</TableCell>
                    <TableCell className="py-2.5">
                      <span className={w.winner === 'Up' ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}>
                        {w.winner ?? '—'}
                      </span>
                    </TableCell>
                    <TableCell className="py-2.5 text-right tabular-nums text-muted-foreground">
                      {trim2(w.upShares)} / {trim2(w.downShares)} {w.imbalance > 0 && <span className="text-amber-600 dark:text-amber-400">(!{trim2(w.imbalance)})</span>}
                    </TableCell>
                    <TableCell className="py-2.5 text-right font-medium tabular-nums">
                      <span className={w.pairCost && w.pairCost <= 0.995 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}>
                        {w.pairCost ? `$${w.pairCost.toFixed(4)}` : '—'}
                      </span>
                    </TableCell>
                    <TableCell className="py-2.5 text-right tabular-nums text-muted-foreground">${w.cost.toFixed(2)}</TableCell>
                    <TableCell className="py-2.5 text-right tabular-nums text-muted-foreground">${w.payout.toFixed(2)}</TableCell>
                    <TableCell className="py-2.5 text-right font-bold tabular-nums">
                      <span className={w.net > 0 ? 'text-emerald-600 dark:text-emerald-400' : w.net < 0 ? 'text-rose-600 dark:text-rose-400' : 'text-muted-foreground'}>
                        {money(w.net)}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <Empty className="mt-6 border border-dashed border-border py-10">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <FlaskConical />
              </EmptyMedia>
              <EmptyTitle>No candidate samples gathered yet</EmptyTitle>
              <EmptyDescription>
                Click &ldquo;Launch Candidate Run (B)&rdquo; above to start the live paper trading loop under the {candidateLabel} configuration.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
      </Card>
    </div>
  )
}
