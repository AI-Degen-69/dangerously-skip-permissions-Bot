import { useId, useState, useRef, useMemo } from 'react'
import { Clock } from 'lucide-react'

import type { PerfWindow } from '../lib/bot'
import { cx } from '../lib/cx'
import { money2 } from '../lib/format'
import { Badge } from './ui'

const usd = money2

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
  const greenGradId = `green-grad-${chartId}`
  const redGradId = `red-grad-${chartId}`

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
      className={cx('relative select-none outline-none focus-visible:ring-1 focus-visible:ring-primary/50 rounded-lg', className)}
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

      {/* Floating Window Summary Tooltip */}
      {activePoint !== null && (
        <div
          className={cx(
            'pointer-events-none absolute z-30 w-72 rounded-tile border border-line-strong/80 bg-surface/95 p-3.5 shadow-pop backdrop-blur-md transition-all duration-100',
            activePctX > 62 ? '-translate-x-full mr-3' : 'translate-x-0 ml-3',
          )}
          style={{
            left: `${activePctX}%`,
            top: '12px',
          }}
        >
          {activePoint.isStart ? (
            <div>
              <div className="flex items-center justify-between border-b border-line pb-2">
                <span className="text-[12px] font-semibold text-fg">{baseLabel}</span>
                <Badge tone="neutral">Base</Badge>
              </div>
              <p className="mt-2 text-[20px] font-bold text-fg tabular-nums">{usd(startingCapital)}</p>
              <p className="mt-1 text-[11.5px] text-muted">
                Trading capital before the first window in this view, opened at {windowTime(activePoint.ts)}.
              </p>
            </div>
          ) : activePoint.window ? (
            <div>
              {/* Header: Window time + Winner */}
              <div className="flex items-center justify-between border-b border-line pb-2">
                <div className="flex items-center gap-1.5">
                  <Clock className="size-3.5 text-muted" />
                  <span className="font-mono text-[12px] font-semibold text-fg">
                    Window {windowTime(activePoint.window.startMs)}
                  </span>
                  <span className="text-[11px] text-faint">#{activePoint.index + 1}</span>
                </div>
                {activePoint.window.winner ? (
                  <Badge tone={activePoint.window.winner === 'Up' ? 'success' : 'danger'}>
                    {activePoint.window.winner}
                  </Badge>
                ) : (
                  <Badge tone="neutral">Pending</Badge>
                )}
              </div>

              {/* Window Net & Capital */}
              <div className="mt-2.5 flex items-baseline justify-between">
                <div>
                  <p className="text-[11px] uppercase tracking-wide text-faint">Window Net</p>
                  <p
                    className={cx(
                      'text-[18px] font-bold tabular-nums tracking-[-0.02em]',
                      activePoint.windowNet >= 0 ? 'text-success' : 'text-danger',
                    )}
                  >
                    {activePoint.windowNet >= 0 ? '+' : ''}
                    {usd(activePoint.windowNet)}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-[11px] uppercase tracking-wide text-faint">Total Capital</p>
                  <p className="text-[15px] font-semibold text-fg tabular-nums">{usd(activePoint.capital)}</p>
                </div>
              </div>

              {/* Cumulative Return vs Starting Capital */}
              <div className="mt-1 flex items-center justify-between text-[11.5px] text-muted">
                <span>Total Net:</span>
                <span
                  className={cx(
                    'font-medium tabular-nums',
                    activePoint.cumNet >= 0 ? 'text-success' : 'text-danger',
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
              <div className="mt-3 space-y-1.5 border-t border-line pt-2 text-[12px]">
                <div className="flex justify-between">
                  <span className="text-muted">Trades / Fills:</span>
                  <span className="font-medium tabular-nums text-fg">
                    {activePoint.window.trades} fills ({activePoint.window.upFills}↑ / {activePoint.window.downFills}↓)
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Staked → Payout:</span>
                  <span className="font-medium tabular-nums text-fg">
                    {usd(activePoint.window.costUsd)} → {usd(activePoint.window.payoutUsd)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Sides Covered:</span>
                  <span className="text-fg">
                    {activePoint.window.bothSides ? (
                      <span className="text-success font-medium">Both sides (pass)</span>
                    ) : (
                      <span className="text-warning font-medium">Single side</span>
                    )}
                  </span>
                </div>
                {activePoint.window.zeroPriceFills > 0 && (
                  <div className="flex justify-between text-danger">
                    <span>Zero-price fills:</span>
                    <span className="font-medium">{activePoint.window.zeroPriceFills}</span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-muted">Redemption:</span>
                  <span className="text-muted">
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
