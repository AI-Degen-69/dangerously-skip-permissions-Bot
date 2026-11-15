import { Clock } from 'lucide-react'
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { PerfWindow } from '../lib/bot'
import { money2 } from '../lib/format'

const usd = money2

type IndicatorId = 'trendline' | 'sma' | 'hwm' | 'band'

const INDICATORS_STORAGE_KEY = 'dsp.equityIndicators'
const INDICATORS_EVENT = 'dsp:equity-indicators'
const DEFAULT_INDICATORS: IndicatorId[] = ['trendline']

const INDICATOR_DEFS: Array<{
  id: IndicatorId
  label: string
  color: string
  description: string
}> = [
  { id: 'trendline', label: 'Trendline', color: '#f59e0b', description: 'OLS linear regression trendline' },
  { id: 'sma', label: 'Moving Avg', color: '#38bdf8', description: 'Rolling simple moving average' },
  { id: 'hwm', label: 'High-Water', color: '#a78bfa', description: 'Running peak high-water mark' },
  { id: 'band', label: '±1σ Band', color: '#38bdf8', description: '±1σ residual channel around trendline' },
]

const VALID_INDICATORS = new Set<string>(INDICATOR_DEFS.map((d) => d.id))

function readStoredIndicators(): IndicatorId[] {
  try {
    const raw = window.localStorage.getItem(INDICATORS_STORAGE_KEY)
    if (raw === null) return DEFAULT_INDICATORS
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return DEFAULT_INDICATORS
    return parsed.filter((item): item is IndicatorId => typeof item === 'string' && VALID_INDICATORS.has(item))
  } catch {
    return DEFAULT_INDICATORS
  }
}

/**
 * Persisted set of active equity curve overlays, synced across storage listeners.
 */
function useEquityIndicators(): [IndicatorId[], (id: IndicatorId) => void] {
  const [active, setActive] = useState<IndicatorId[]>(() =>
    typeof window === 'undefined' ? DEFAULT_INDICATORS : readStoredIndicators(),
  )

  useEffect(() => {
    const sync = () => setActive(readStoredIndicators())
    const onPick = (event: Event) => setActive((event as CustomEvent<IndicatorId[]>).detail)
    window.addEventListener('storage', sync)
    window.addEventListener(INDICATORS_EVENT, onPick)
    return () => {
      window.removeEventListener('storage', sync)
      window.removeEventListener(INDICATORS_EVENT, onPick)
    }
  }, [])

  const toggle = useCallback((id: IndicatorId) => {
    setActive((prev) => {
      const next = prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
      try {
        window.localStorage.setItem(INDICATORS_STORAGE_KEY, JSON.stringify(next))
      } catch {
        // Private-mode storage failures must not block toggling indicators.
      }
      window.dispatchEvent(new CustomEvent(INDICATORS_EVENT, { detail: next }))
      return next
    })
  }, [])

  return [active, toggle]
}

const windowTime = (ms: number) =>
  new Date(ms).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })

interface ChartPoint {
  index: number
  ts: number
  capital: number
  windowNet: number
  cumNet: number
  window: PerfWindow | null
  slug?: string
  isStart?: boolean
}

export interface InteractivePnlChartProps {
  windows: PerfWindow[]
  startingCapital: number
  hoveredSlug?: string | null
  onHoverWindow?: (window: PerfWindow | null) => void
  /** Baseline caption: the real starting capital, or the base of a scoped view. */
  baseLabel?: string
  className?: string
}

function computeNiceTicks(min: number, max: number, startingCapital: number, targetCount = 5): number[] {
  const span = Math.max(10, max - min)
  const rawStep = span / targetCount
  const power = Math.pow(10, Math.floor(Math.log10(rawStep)))
  const factor = rawStep / power
  let step = power
  if (factor > 5) step = 10 * power
  else if (factor > 2) step = 5 * power
  else if (factor > 1) step = 2 * power

  const tickMin = Math.floor(min / step) * step
  const tickMax = Math.ceil(max / step) * step
  const ticks: number[] = []

  for (let t = tickMin; t <= tickMax + step * 0.05; t += step) {
    const val = Math.round(t * 100) / 100
    if (val >= min - step * 0.5 && val <= max + step * 0.5) {
      ticks.push(val)
    }
  }

  if (!ticks.includes(startingCapital)) {
    ticks.push(startingCapital)
    ticks.sort((a, b) => a - b)
  }

  return ticks
}

interface ChartIndicators {
  trendStart: number
  trendEnd: number
  sigma: number
  sma: number[]
  hwm: number[]
}

/**
 * Computes OLS linear regression trendline, residual sigma channel,
 * rolling SMA, and running High-Water Mark over chart points.
 */
function computeIndicators(points: ChartPoint[], startingCapital: number): ChartIndicators {
  const n = points.length
  if (n === 0) {
    return { trendStart: startingCapital, trendEnd: startingCapital, sigma: 0, sma: [], hwm: [] }
  }

  let trendStart = points[0].capital
  let trendEnd = points[n - 1].capital
  let sigma = 0

  if (n >= 2) {
    const meanX = (n - 1) / 2
    const meanY = points.reduce((sum, pt) => sum + pt.capital, 0) / n
    let num = 0
    let den = 0
    for (let i = 0; i < n; i++) {
      const dx = i - meanX
      num += dx * (points[i].capital - meanY)
      den += dx * dx
    }
    const slope = den > 0 ? num / den : 0
    const intercept = meanY - slope * meanX
    trendStart = intercept
    trendEnd = intercept + slope * (n - 1)

    if (n > 2) {
      let ssRes = 0
      for (let i = 0; i < n; i++) {
        const residual = points[i].capital - (intercept + slope * i)
        ssRes += residual * residual
      }
      sigma = Math.sqrt(ssRes / (n - 2))
    }
  }

  const smaWin = Math.min(8, Math.max(3, Math.floor(n / 4)))
  const sma: number[] = []
  let rollingSum = 0
  for (let i = 0; i < n; i++) {
    rollingSum += points[i].capital
    if (i >= smaWin) rollingSum -= points[i - smaWin].capital
    const denom = Math.min(i + 1, smaWin)
    sma.push(rollingSum / denom)
  }

  const hwm: number[] = []
  let peak = startingCapital
  for (let i = 0; i < n; i++) {
    if (points[i].capital > peak) peak = points[i].capital
    hwm.push(peak)
  }

  return { trendStart, trendEnd, sigma, sma, hwm }
}

function IndicatorSwatch({ id, color, active }: { id: IndicatorId; color: string; active: boolean }) {
  if (id === 'band') {
    return (
      <span
        className={cn(
          'inline-block h-2 w-3 rounded-[2px] border-y border-dotted transition-opacity',
          !active && 'opacity-40',
        )}
        style={{ borderColor: color, backgroundColor: 'rgba(56, 189, 248, 0.16)' }}
        aria-hidden="true"
      />
    )
  }

  return (
    <span
      className={cn(
        'inline-block w-3 transition-opacity',
        id === 'sma' ? 'h-0.5 rounded-full' : 'h-0 border-t-2',
        id === 'trendline' && 'border-dashed',
        id === 'hwm' && 'border-dotted',
        !active && 'opacity-40',
      )}
      style={id === 'sma' ? { backgroundColor: color } : { borderColor: color }}
      aria-hidden="true"
    />
  )
}

export function InteractivePnlChart({
  windows,
  startingCapital,
  hoveredSlug,
  onHoverWindow,
  baseLabel = 'Starting capital',
  className,
}: InteractivePnlChartProps) {
  const chartId = useId()
  const [internalHoverIndex, setInternalHoverIndex] = useState<number | null>(null)
  const [activeIndicators, toggleIndicator] = useEquityIndicators()
  const containerRef = useRef<HTMLDivElement>(null)

  const settled = useMemo(() => windows.filter((w) => !w.pending), [windows])

  // Build cumulative data points: starting anchor point + each settled window
  const points = useMemo<ChartPoint[]>(() => {
    if (settled.length === 0) return []

    const pts: ChartPoint[] = []
    let cum = 0

    // Anchor point before trading started
    pts.push({
      index: -1,
      ts: settled[0].startMs,
      capital: startingCapital,
      windowNet: 0,
      cumNet: 0,
      window: null,
      slug: 'start',
      isStart: true,
    })

    settled.forEach((w, idx) => {
      cum += w.netUsd ?? 0
      pts.push({
        index: idx,
        ts: w.startMs,
        capital: Math.round((startingCapital + cum) * 100) / 100,
        windowNet: w.netUsd ?? 0,
        cumNet: Math.round(cum * 100) / 100,
        window: w,
        slug: w.slug,
      })
    })

    return pts
  }, [settled, startingCapital])

  // Sync external hoveredSlug if provided
  const activeIndex = useMemo(() => {
    if (internalHoverIndex !== null && internalHoverIndex < points.length) return internalHoverIndex
    if (hoveredSlug) {
      const idx = points.findIndex((p) => p.window?.slug === hoveredSlug)
      if (idx !== -1) return idx
    }
    return null
  }, [internalHoverIndex, hoveredSlug, points])

  const indicators = useMemo(
    () => computeIndicators(points, startingCapital),
    [points, startingCapital],
  )

  if (settled.length === 0 || points.length === 0) {
    return null
  }

  // SVG dimensions and padding
  const width = 820
  const height = 290
  const padLeft = 76
  const padRight = 32
  const padTop = 26
  const padBottom = 40

  const chartWidth = width - padLeft - padRight
  const chartHeight = height - padTop - padBottom

  // Value boundaries with padding headroom
  const capitalValues = points.map((p) => p.capital)
  const minVal = Math.min(startingCapital, ...capitalValues)
  const maxVal = Math.max(startingCapital, ...capitalValues)
  const valSpan = maxVal - minVal
  const margin = Math.max(12, valSpan * 0.12)
  const yMin = minVal - margin
  const yMax = maxVal + margin
  const totalYSpan = yMax - yMin || 1

  const yCoord = (val: number) => padTop + chartHeight * (1 - (val - yMin) / totalYSpan)
  const xCoord = (idx: number) => padLeft + (idx / Math.max(1, points.length - 1)) * chartWidth

  const baselineY = yCoord(startingCapital)

  // Construct line and area paths
  const linePoints = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xCoord(i).toFixed(2)} ${yCoord(p.capital).toFixed(2)}`).join(' ')
  const lastX = xCoord(points.length - 1).toFixed(2)
  const firstX = xCoord(0).toFixed(2)
  const areaPath = `${linePoints} L ${lastX} ${baselineY.toFixed(2)} L ${firstX} ${baselineY.toFixed(2)} Z`

  // Y-axis tick values
  const yTicks = computeNiceTicks(minVal, maxVal, startingCapital, 5)

  // X-axis evenly spaced time labels
  const numTimeLabels = Math.min(6, points.length)
  const timeLabelIndices = Array.from({ length: numTimeLabels }, (_, i) =>
    Math.round((i * (points.length - 1)) / Math.max(1, numTimeLabels - 1)),
  )

  // Where the calendar day turns over. The time labels alone cannot say which
  // day a point belongs to once the view spans midnight, so every new day gets
  // its own tick on the axis.
  const dayMarks = points
    .map((p, idx) => ({ idx, ts: p.ts }))
    .filter((p, idx) => idx > 0 && new Date(p.ts).toDateString() !== new Date(points[idx - 1].ts).toDateString())
    .map((p) => ({
      idx: p.idx,
      label: new Date(p.ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    }))

  const clipAboveId = `clip-above-${chartId}`
  const clipBelowId = `clip-below-${chartId}`
  const clipPlotId = `clip-plot-${chartId}`
  const greenGradId = `green-grad-${chartId}`
  const redGradId = `red-grad-${chartId}`

  const showTrendline = activeIndicators.includes('trendline') && points.length >= 2
  const showSma = activeIndicators.includes('sma') && points.length >= 2
  const showHwm = activeIndicators.includes('hwm') && points.length >= 2
  const showBand = activeIndicators.includes('band') && points.length >= 2 && indicators.sigma > 0

  const smaPath = showSma
    ? points
        .map((_, i) => `${i === 0 ? 'M' : 'L'} ${xCoord(i).toFixed(2)} ${yCoord(indicators.sma[i]).toFixed(2)}`)
        .join(' ')
    : ''
  const hwmPath = showHwm
    ? points
        .map((_, i) => `${i === 0 ? 'M' : 'L'} ${xCoord(i).toFixed(2)} ${yCoord(indicators.hwm[i]).toFixed(2)}`)
        .join(' ')
    : ''
  const trendX1 = xCoord(0)
  const trendX2 = xCoord(points.length - 1)
  const trendY1 = yCoord(indicators.trendStart)
  const trendY2 = yCoord(indicators.trendEnd)
  const bandAreaPath = showBand
    ? `M ${trendX1.toFixed(2)} ${yCoord(indicators.trendStart + indicators.sigma).toFixed(2)} L ${trendX2.toFixed(2)} ${yCoord(indicators.trendEnd + indicators.sigma).toFixed(2)} L ${trendX2.toFixed(2)} ${yCoord(indicators.trendEnd - indicators.sigma).toFixed(2)} L ${trendX1.toFixed(2)} ${yCoord(indicators.trendStart - indicators.sigma).toFixed(2)} Z`
    : ''
  const bandUpperY1 = yCoord(indicators.trendStart + indicators.sigma)
  const bandUpperY2 = yCoord(indicators.trendEnd + indicators.sigma)
  const bandLowerY1 = yCoord(indicators.trendStart - indicators.sigma)
  const bandLowerY2 = yCoord(indicators.trendEnd - indicators.sigma)

  const activePoint = activeIndex !== null ? points[activeIndex] : null

  // Pointer move handler to snap to closest window tick
  const handlePointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!containerRef.current) return
    const rect = e.currentTarget.getBoundingClientRect()
    const mouseX = e.clientX - rect.left
    const svgX = (mouseX / rect.width) * width

    // Find nearest point
    let closestIdx = 0
    let minDiff = Infinity
    points.forEach((_, idx) => {
      const diff = Math.abs(xCoord(idx) - svgX)
      if (diff < minDiff) {
        minDiff = diff
        closestIdx = idx
      }
    })

    setInternalHoverIndex(closestIdx)
    onHoverWindow?.(points[closestIdx].window)
  }

  const handlePointerLeave = () => {
    setInternalHoverIndex(null)
    onHoverWindow?.(null)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (points.length === 0) return
    if (e.target instanceof HTMLElement && e.target.closest('button')) return
    if (e.key === 'ArrowRight') {
      e.preventDefault()
      const next = activeIndex === null ? 0 : Math.min(points.length - 1, activeIndex + 1)
      setInternalHoverIndex(next)
      onHoverWindow?.(points[next]?.window ?? null)
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault()
      const prev = activeIndex === null ? 0 : Math.max(0, activeIndex - 1)
      setInternalHoverIndex(prev)
      onHoverWindow?.(points[prev]?.window ?? null)
    } else if (e.key === 'Escape') {
      setInternalHoverIndex(null)
      onHoverWindow?.(null)
    }
  }

  // Active point tooltip coordinates
  const activeX = activePoint !== null ? xCoord(activeIndex!) : 0
  const activeY = activePoint !== null ? yCoord(activePoint.capital) : 0
  const activePctX = (activeX / width) * 100

  return (
    <div
      ref={containerRef}
      className={cn(
        'relative rounded-xl outline-none select-none focus-visible:ring-2 focus-visible:ring-ring/50',
        className,
      )}
      tabIndex={0}
      role="region"
      aria-label="Interactive performance chart. Use left and right arrow keys to navigate windows."
      onKeyDown={handleKeyDown}
    >
      <span className="sr-only" aria-live="polite">
        {activePoint
          ? activePoint.isStart
            ? `${baseLabel}: ${usd(startingCapital)}`
            : `${activePoint.slug}: Capital ${usd(activePoint.capital)}, Total Return ${activePoint.cumNet >= 0 ? '+' : ''}${usd(activePoint.cumNet)}${startingCapital > 0 ? `, ${(((activePoint.capital - startingCapital) / startingCapital) * 100).toFixed(1)}%` : ''}`
          : ''}
      </span>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full overflow-visible"
        role="img"
        aria-label="Cumulative paper P&L and capital chart with starting capital baseline"
        onPointerMove={handlePointerMove}
        onPointerLeave={handlePointerLeave}
      >
        <defs>
          {/* Green gradient: from top curve to baseline */}
          <linearGradient id={greenGradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22c55e" stopOpacity="0.38" />
            <stop offset="85%" stopColor="#22c55e" stopOpacity="0.08" />
            <stop offset="100%" stopColor="#22c55e" stopOpacity="0.01" />
          </linearGradient>

          {/* Red gradient: from baseline down to bottom trough */}
          <linearGradient id={redGradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ef4444" stopOpacity="0.01" />
            <stop offset="15%" stopColor="#ef4444" stopOpacity="0.08" />
            <stop offset="100%" stopColor="#ef4444" stopOpacity="0.38" />
          </linearGradient>

          {/* Clip path above starting capital baseline (positive area) */}
          <clipPath id={clipAboveId}>
            <rect x={padLeft} y={0} width={chartWidth} height={Math.max(0, baselineY)} />
          </clipPath>

          {/* Clip path below starting capital baseline (negative area) */}
          <clipPath id={clipBelowId}>
            <rect x={padLeft} y={baselineY} width={chartWidth} height={Math.max(0, height - baselineY)} />
          </clipPath>

          {/* Clip path bounded to the chart plot area for indicator overlays */}
          <clipPath id={clipPlotId}>
            <rect x={padLeft} y={padTop} width={chartWidth} height={chartHeight} />
          </clipPath>
        </defs>

        {/* Y-Axis Gridlines and Labels */}
        {yTicks.map((tick) => {
          const y = yCoord(tick)
          const isBaseline = Math.abs(tick - startingCapital) < 0.01
          if (isBaseline) return null // Rendered separately below for prominence

          return (
            <g key={`y-grid-${tick}`}>
              <line
                x1={padLeft}
                x2={width - padRight}
                y1={y}
                y2={y}
                stroke="var(--color-line)"
                strokeDasharray="2 4"
                strokeWidth="1"
                opacity="0.6"
              />
              <text
                x={padLeft - 10}
                y={y + 3.5}
                textAnchor="end"
                fontSize="11"
                fill="var(--color-faint)"
                className="font-mono"
              >
                {usd(tick)}
              </text>
            </g>
          )
        })}

        {/* Shaded Area ABOVE starting capital (Green Gradient) */}
        <g clipPath={`url(#${clipAboveId})`}>
          <path d={areaPath} fill={`url(#${greenGradId})`} />
          <path
            d={linePoints}
            fill="none"
            stroke="#22c55e"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>

        {/* Shaded Area BELOW starting capital (Red Gradient) */}
        <g clipPath={`url(#${clipBelowId})`}>
          <path d={areaPath} fill={`url(#${redGradId})`} />
          <path
            d={linePoints}
            fill="none"
            stroke="#ef4444"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>

        {/* Dotted Horizontal Line Indicating Starting Capital */}
        <g className="cursor-pointer">
          <line
            x1={padLeft}
            x2={width - padRight}
            y1={baselineY}
            y2={baselineY}
            stroke="var(--color-line-strong)"
            strokeDasharray="4 4"
            strokeWidth="1.5"
          />
          {/* Starting Capital Y-Axis label */}
          <text
            x={padLeft - 10}
            y={baselineY + 3.5}
            textAnchor="end"
            fontSize="11"
            fontWeight="600"
            fill="var(--color-fg)"
            className="font-mono"
          >
            {usd(startingCapital)}
          </text>
          {/* Starting Capital Right Badge */}
          <text
            x={width - padRight}
            y={Math.max(12, baselineY - 6)}
            textAnchor="end"
            fontSize="10.5"
            fontWeight="500"
            fill="var(--color-muted)"
            className="font-mono"
          >
            {baseLabel} ({usd(startingCapital)})
          </text>
        </g>

        {/* Y-Axis border line */}
        <line
          x1={padLeft}
          x2={padLeft}
          y1={padTop}
          y2={height - padBottom}
          stroke="var(--color-line)"
          strokeWidth="1"
        />

        {/* X-Axis border line */}
        <line
          x1={padLeft}
          x2={width - padRight}
          y1={height - padBottom}
          y2={height - padBottom}
          stroke="var(--color-line)"
          strokeWidth="1"
        />

        {/* Day change ticks on the X-Axis */}
        {dayMarks.map((mark) => {
          const x = xCoord(mark.idx)
          return (
            <g key={`day-${mark.idx}`} className="pointer-events-none">
              <line
                x1={x}
                x2={x}
                y1={padTop}
                y2={height - padBottom}
                stroke="var(--color-line-strong)"
                strokeDasharray="3 3"
                strokeWidth="1"
                opacity="0.75"
              />
              <text
                x={Math.min(x + 4, width - padRight - 46)}
                y={padTop - 8}
                textAnchor="start"
                fontSize="10"
                fontWeight="600"
                fill="var(--color-muted)"
                className="font-mono"
              >
                {mark.label}
              </text>
            </g>
          )
        })}

        {/* Ticks for EVERY settled window along the X-Axis */}
        {points.map((p, idx) => {
          if (idx === 0) return null // Anchor start point
          const x = xCoord(idx)
          const isHovered = activeIndex === idx
          return (
            <line
              key={`x-tick-${p.slug ?? idx}`}
              x1={x}
              x2={x}
              y1={height - padBottom}
              y2={height - padBottom + (isHovered ? 6 : 3.5)}
              stroke={isHovered ? 'var(--color-fg)' : 'var(--color-line-strong)'}
              strokeWidth={isHovered ? 1.5 : 1}
            />
          )
        })}

        {/* X-Axis Time Labels at readable intervals */}
        {timeLabelIndices.map((idx) => {
          const p = points[idx]
          const x = xCoord(idx)
          const textAnchor = idx === 0 ? 'start' : idx === points.length - 1 ? 'end' : 'middle'
          return (
            <text
              key={`time-${idx}`}
              x={x}
              y={height - padBottom + 18}
              textAnchor={textAnchor}
              fontSize="11"
              fill="var(--color-faint)"
              className="font-mono"
            >
              {windowTime(p.ts)}
            </text>
          )
        })}

        {/* Optional Statistical & Technical Overlay Indicators */}
        <g clipPath={`url(#${clipPlotId})`} className="pointer-events-none">
          {showBand && (
            <g>
              <path d={bandAreaPath} fill="#38bdf8" fillOpacity="0.08" />
              <line
                x1={trendX1}
                x2={trendX2}
                y1={bandUpperY1}
                y2={bandUpperY2}
                stroke="#38bdf8"
                strokeWidth="1.25"
                strokeDasharray="2 3"
                opacity="0.55"
              />
              <line
                x1={trendX1}
                x2={trendX2}
                y1={bandLowerY1}
                y2={bandLowerY2}
                stroke="#38bdf8"
                strokeWidth="1.25"
                strokeDasharray="2 3"
                opacity="0.55"
              />
            </g>
          )}
          {showHwm && (
            <path
              d={hwmPath}
              fill="none"
              stroke="#a78bfa"
              strokeWidth="1.5"
              strokeDasharray="2 3"
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity="0.85"
            />
          )}
          {showSma && (
            <path
              d={smaPath}
              fill="none"
              stroke="#38bdf8"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity="0.9"
            />
          )}
          {showTrendline && (
            <line
              x1={trendX1}
              x2={trendX2}
              y1={trendY1}
              y2={trendY2}
              stroke="#f59e0b"
              strokeWidth="1.75"
              strokeDasharray="5 4"
              strokeLinecap="round"
              opacity="0.9"
            />
          )}
        </g>

        {/* Interactive Ticks on the curve for EVERY settled window */}
        {points.map((p, idx) => {
          if (idx === 0) return null // Anchor start point
          const x = xCoord(idx)
          const y = yCoord(p.capital)
          const isProfitable = p.windowNet >= 0
          const isHovered = activeIndex === idx
          const toneColor = isProfitable ? '#22c55e' : '#ef4444'

          return (
            <g key={`curve-tick-${p.slug ?? idx}`} className="cursor-pointer">
              {/* Outer halo when active */}
              {isHovered && (
                <circle cx={x} cy={y} r="9" fill={toneColor} opacity="0.22" className="animate-pulse" />
              )}
              {/* Point tick */}
              <circle
                cx={x}
                cy={y}
                r={isHovered ? 5 : 2.75}
                fill={isHovered ? toneColor : 'var(--color-surface)'}
                stroke={toneColor}
                strokeWidth={isHovered ? 2 : 1.5}
                className="transition-all duration-150"
              />
            </g>
          )
        })}

        {/* Active Crosshair Guidelines */}
        {activePoint !== null && (
          <g className="pointer-events-none">
            {/* Vertical crosshair line */}
            <line
              x1={activeX}
              x2={activeX}
              y1={padTop}
              y2={height - padBottom}
              stroke="var(--color-fg)"
              strokeDasharray="3 3"
              strokeWidth="1.2"
              opacity="0.4"
            />
            {/* Horizontal projection line to Y-axis */}
            <line
              x1={padLeft}
              x2={activeX}
              y1={activeY}
              y2={activeY}
              stroke="var(--color-fg)"
              strokeDasharray="3 3"
              strokeWidth="1.2"
              opacity="0.4"
            />
            {/* Y-axis indicator tag */}
            <rect
              x={padLeft - 66}
              y={activeY - 9}
              width="60"
              height="18"
              rx="3"
              fill="var(--color-fg)"
            />
            <text
              x={padLeft - 36}
              y={activeY + 3.5}
              textAnchor="middle"
              fontSize="10"
              fontWeight="600"
              fill="var(--color-bg)"
              className="font-mono"
            >
              {usd(activePoint.capital)}
            </text>
          </g>
        )}

        {/* Full-area pointer interaction overlay */}
        <rect
          x={padLeft}
          y={padTop}
          width={chartWidth}
          height={chartHeight}
          fill="transparent"
          className="cursor-crosshair"
        />
      </svg>

      {/* Bottom Indicator Toggle Bar */}
      <div
        className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-line/60 px-2 pt-2 text-[11.5px]"
        role="group"
        aria-label="Chart overlay indicators"
      >
        <span className="font-mono text-[10.5px] uppercase tracking-wider text-faint">Indicators:</span>
        <div className="flex flex-wrap items-center gap-y-1">
          {INDICATOR_DEFS.map((ind, idx) => {
            const active = activeIndicators.includes(ind.id)
            return (
              <div key={ind.id} className="inline-flex items-center">
                {idx > 0 && (
                  <span className="mx-1.5 select-none text-border" aria-hidden="true">
                    |
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => toggleIndicator(ind.id)}
                  aria-pressed={active}
                  title={`${ind.description} — click to ${active ? 'hide' : 'show'}`}
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[11.5px] font-medium transition-colors',
                    active
                      ? 'bg-surface-2 text-fg ring-1 ring-border'
                      : 'text-muted-foreground/75 hover:bg-surface-2/50 hover:text-fg',
                  )}
                >
                  <IndicatorSwatch id={ind.id} color={ind.color} active={active} />
                  <span>{ind.label}</span>
                </button>
              </div>
            )
          })}
        </div>
      </div>

      {/* Floating Window Summary Tooltip */}
      {activePoint !== null && (
        <div
          className={cn(
            'pointer-events-none absolute z-30 w-72 rounded-2xl border border-border bg-popover/95 p-3.5 text-popover-foreground shadow-lg backdrop-blur-md transition-all duration-100',
            activePctX > 62 ? 'mr-3 -translate-x-full' : 'ml-3 translate-x-0',
          )}
          style={{
            left: `${activePctX}%`,
            top: '12px',
          }}
        >
          {activePoint.isStart ? (
            <div>
              <div className="flex items-center justify-between border-b border-border pb-2">
                <span className="text-xs font-semibold text-foreground">{baseLabel}</span>
                <Badge variant="secondary">Base</Badge>
              </div>
              <p className="mt-2 font-mono text-xl font-bold text-foreground tabular-nums">{usd(startingCapital)}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Trading capital before the first window in this view, opened at {windowTime(activePoint.ts)}.
              </p>
            </div>
          ) : activePoint.window ? (
            <div>
              {/* Header: Window time + Winner */}
              <div className="flex items-center justify-between border-b border-border pb-2">
                <div className="flex items-center gap-1.5">
                  <Clock className="size-3.5 text-muted-foreground" />
                  <span className="font-mono text-xs font-semibold text-foreground">
                    Window {windowTime(activePoint.window.startMs)}
                  </span>
                  <span className="font-mono text-[11px] text-muted-foreground">#{activePoint.index + 1}</span>
                </div>
                {activePoint.window.winner ? (
                  <Badge
                    variant="outline"
                    className={
                      activePoint.window.winner === 'Up'
                        ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                        : 'border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-400'
                    }
                  >
                    {activePoint.window.winner}
                  </Badge>
                ) : (
                  <Badge variant="secondary">Pending</Badge>
                )}
              </div>

              {/* Window Net & Capital */}
              <div className="mt-2.5 flex items-baseline justify-between">
                <div>
                  <p className="text-[11px] tracking-wide text-muted-foreground uppercase">Window Net</p>
                  <p
                    className={cn(
                      'font-mono text-lg font-bold tracking-tight tabular-nums',
                      activePoint.windowNet >= 0
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : 'text-rose-600 dark:text-rose-400',
                    )}
                  >
                    {activePoint.windowNet >= 0 ? '+' : ''}
                    {usd(activePoint.windowNet)}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-[11px] tracking-wide text-muted-foreground uppercase">Total Capital</p>
                  <p className="font-mono text-[15px] font-semibold text-foreground tabular-nums">
                    {usd(activePoint.capital)}
                  </p>
                </div>
              </div>

              {/* Cumulative Return vs Starting Capital */}
              <div className="mt-1 flex items-center justify-between text-xs text-muted-foreground">
                <span>Total Net:</span>
                <span
                  className={cn(
                    'font-mono font-medium tabular-nums',
                    activePoint.cumNet >= 0
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : 'text-rose-600 dark:text-rose-400',
                  )}
                >
                  {activePoint.cumNet >= 0 ? '+' : ''}
                  {usd(activePoint.cumNet)}
                  {startingCapital > 0
                    ? ` (${(((activePoint.capital - startingCapital) / startingCapital) * 100).toFixed(1)}%)`
                    : ''}
                </span>
              </div>

              {/* Window Details Breakdown */}
              <div className="mt-3 flex flex-col gap-1.5 border-t border-border pt-2 text-xs">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Trades / Fills:</span>
                  <span className="font-mono font-medium text-foreground tabular-nums">
                    {activePoint.window.trades} fills ({activePoint.window.upFills}↑ / {activePoint.window.downFills}↓)
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Staked → Payout:</span>
                  <span className="font-mono font-medium text-foreground tabular-nums">
                    {usd(activePoint.window.costUsd)} → {usd(activePoint.window.payoutUsd)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Sides Covered:</span>
                  <span className="text-foreground">
                    {activePoint.window.bothSides ? (
                      <span className="font-medium text-emerald-600 dark:text-emerald-400">Both sides (pass)</span>
                    ) : (
                      <span className="font-medium text-amber-600 dark:text-amber-400">Single side</span>
                    )}
                  </span>
                </div>
                {activePoint.window.zeroPriceFills > 0 && (
                  <div className="flex justify-between text-rose-600 dark:text-rose-400">
                    <span>Zero-price fills:</span>
                    <span className="font-mono font-medium tabular-nums">{activePoint.window.zeroPriceFills}</span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Redemption:</span>
                  <span className="text-muted-foreground">
                    {activePoint.window.pending
                      ? 'Settling…'
                      : activePoint.window.redeemed
                        ? 'Claimed'
                        : 'Due to claim'}
                  </span>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}
