import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'

import type { MarketView } from '../lib/bot'
import { projectX, projectY } from '../lib/chartMath'
import { mmss } from '../lib/format'
import { Badge } from './ui'

/** Sampled implied-Up odds over the window: { t: epoch ms, v: probability 0..1 }. */
export interface OddsPoint {
  t: number
  v: number // implied Up, 0..1
}

const CHART_MIN_H = 110
const CHART_MAX_H = 190
const Y_AXIS_GUTTER = 32
const PAD = 10
const AXIS_H = 13 // bottom band reserved for elapsed-time labels
const LABEL_GAP = 26 // px a tick label needs so it never collides with its neighbour
// Theme tokens: in the dark desk these resolve to the emerald/rose pair, and
// the light theme keeps the chart in step with the badges around it.
const UP_COLOR = 'var(--color-success)'
const DOWN_COLOR = 'var(--color-danger)'

/** A strategy-critical moment in the window, drawn as an x-axis tick on the chart. */
export interface AxisTick {
  atSec: number
  label: string
  title: string
  tone: 'info' | 'danger' | 'muted'
}

const TICK_STROKE: Record<AxisTick['tone'], string> = {
  info: 'var(--color-info)',
  danger: 'var(--color-danger)',
  muted: 'var(--color-line-strong)',
}

interface ChartPoint {
  t: number
  v: number
  x: number
  y: number
}

interface Geometry {
  coords: ChartPoint[]
  line: string
  area: string
  last: ChartPoint | undefined
  current: number
  isUp: boolean
  color: string
  parityY: number
  yFor: (v: number) => number
}

/** Live probability trajectory: implied Up odds across the window, scrubbable by pointer or keyboard. */
export function ProbabilityChart({
  market,
  points,
  ticks = [],
}: {
  market: MarketView
  points: OddsPoint[]
  ticks?: AxisTick[]
}) {
  const [hoverT, setHoverT] = useState<number | null>(null)
  const [box, setBox] = useState({ w: 0, h: 0 })
  const surfaceRef = useRef<HTMLDivElement>(null)

  // Measure the surface so SVG units equal CSS pixels. ResizeObserver alone is
  // not enough: it stays silent in a background tab, so the width is also read
  // directly on mount and on window resize.
  const measure = useCallback(() => {
    const el = surfaceRef.current
    if (!el) return
    const w = Math.round(el.getBoundingClientRect().width)
    if (w <= 0) {
      setBox((prev) => (prev.w === 0 ? prev : { w: 0, h: 0 }))
      return
    }
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
  // Right gutter holds the y-axis labels; the plot uses the rest.
  const plotW = Math.max(40, box.w - Y_AXIS_GUTTER)
  // The plot stops above the axis band so the elapsed-time labels have their own row.
  const floorY = box.h - PAD - AXIS_H

  const geometry = useMemo<Geometry>(() => {
    // Samples collected before the window opened (the next market is revealed
    // 15s early) clamp to the plot edges instead of landing off-canvas.
    const xFor = (t: number) => projectX(t, market.startMs, span, plotW)
    const yFor = (v: number) => projectY(v, PAD, floorY)
    const coords = points.map((p) => ({ t: p.t, v: p.v, x: xFor(p.t), y: yFor(p.v) }))
    const line = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ')
    const last = coords[coords.length - 1]
    const parityY = yFor(0.5)
    const area = coords.length > 1 ? `${line} L${last!.x.toFixed(1)},${parityY} L${coords[0]!.x.toFixed(1)},${parityY} Z` : ''
    const current = last?.v ?? 0.5
    return {
      coords,
      line,
      area,
      last,
      current,
      isUp: current >= 0.5,
      color: current >= 0.5 ? UP_COLOR : DOWN_COLOR,
      parityY,
      yFor,
    }
    // `points` is mutated in place by the sampler, so its length and last
    // timestamp are the real change signals.
  }, [points, points.length, points[points.length - 1]?.t, box.w, box.h, floorY, plotW, span, market.startMs])

  const { coords, line, area, last, current, isUp, color, parityY, yFor } = geometry

  // Strategy-critical moments become x-axis ticks. Endpoints are always labelled
  // (0 → window end); interior labels are dropped when they would collide, but
  // their lines stay so the moment is still visible.
  const axis = useMemo(() => {
    const spanSec = span / 1000
    const xAt = (atSec: number) => projectX(market.startMs + atSec * 1000, market.startMs, span, plotW)
    const marks = ticks
      .filter((tick) => tick.atSec > 0 && tick.atSec < spanSec)
      .map((tick) => ({ ...tick, x: xAt(tick.atSec) }))
    const labels: { x: number; label: string; title: string; anchor: 'start' | 'middle' | 'end' }[] = [
      { x: 0, label: '0:00', title: 'Window opens', anchor: 'start' },
      { x: plotW, label: mmss(spanSec), title: 'Window closes', anchor: 'end' },
    ]
    for (const mark of marks) {
      if (mark.x < LABEL_GAP / 2 || mark.x > plotW - LABEL_GAP / 2) continue
      if (labels.some((l) => Math.abs(l.x - mark.x) < LABEL_GAP)) continue
      labels.push({ x: mark.x, label: mark.label, title: mark.title, anchor: 'middle' })
    }
    return { marks, labels }
  }, [ticks, plotW, span, market.startMs])

  const hovered = useMemo(() => {
    if (hoverT == null || coords.length === 0) return null
    let best = coords[0]!
    for (const c of coords) if (Math.abs(c.t - hoverT) < Math.abs(best.t - hoverT)) best = c
    return best
  }, [hoverT, coords])

  const handleMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const rect = surfaceRef.current?.getBoundingClientRect()
    if (!rect || rect.width === 0 || coords.length === 0) return
    const plotX = Math.min(plotW, Math.max(0, e.clientX - rect.left))
    setHoverT(market.startMs + (plotX / plotW) * span)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (coords.length === 0) return
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault()
      const idx = hovered ? coords.indexOf(hovered) : -1
      const next = e.key === 'ArrowRight' ? Math.min(coords.length - 1, idx + 1) : Math.max(0, idx - 1)
      setHoverT(coords[next]!.t)
    } else if (e.key === 'Escape') {
      setHoverT(null)
    }
  }

  // Tooltip stays inside the chart box at both edges.
  const tipLeft = hovered ? Math.min(Math.max(hovered.x, 52), Math.max(52, plotW - 20)) : 0
  const tipTop = hovered ? Math.min(Math.max(hovered.y - 10, 22), Math.max(22, box.h - 6)) : 0
  const elapsedSec = hovered ? Math.max(0, (hovered.t - market.startMs) / 1000) : 0

  return (
    <div className="relative mt-2.5 overflow-hidden rounded-tile border border-line bg-surface-2/30 p-3">
      <div className="relative flex items-center justify-between gap-2">
        <p className="text-[10px] font-medium uppercase tracking-wide text-faint">Live probability trajectory</p>
        <Badge tone={coords.length === 0 ? 'neutral' : isUp ? 'success' : 'danger'} className="font-mono text-[11px]">
          {coords.length === 0 ? '—' : `${isUp ? 'UP' : 'DN'} ${Math.round(current * 100)}¢`}
        </Badge>
      </div>

      <div
        ref={surfaceRef}
        className="relative mt-2 w-full select-none"
        style={{ height: box.h }}
        role="region"
        aria-label="Live probability trajectory. Use left and right arrow keys to step through the samples."
        tabIndex={0}
        onPointerMove={handleMove}
        onPointerLeave={() => setHoverT(null)}
        onKeyDown={handleKeyDown}
      >
        {box.w > 0 && (
          <svg
            viewBox={`0 0 ${box.w} ${box.h}`}
            className="h-full w-full"
            role="img"
            aria-label={
              coords.length === 0
                ? 'Live probability trajectory · no samples yet'
                : `Live probability trajectory · Up ${Math.round(current * 100)}¢`
            }
          >
            <defs>
              <linearGradient id={`prob-up-${market.slug}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" style={{ stopColor: UP_COLOR, stopOpacity: 0.34 }} />
                <stop offset="100%" style={{ stopColor: UP_COLOR, stopOpacity: 0.02 }} />
              </linearGradient>
              <linearGradient id={`prob-down-${market.slug}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" style={{ stopColor: DOWN_COLOR, stopOpacity: 0.02 }} />
                <stop offset="100%" style={{ stopColor: DOWN_COLOR, stopOpacity: 0.34 }} />
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
              <line
                key={v}
                x1={0}
                x2={plotW}
                y1={yFor(v)}
                y2={yFor(v)}
                stroke="var(--color-line)"
                strokeDasharray="2 4"
                strokeWidth={1}
              />
            ))}
            {/* 50¢ parity line */}
            <line x1={0} x2={plotW} y1={parityY} y2={parityY} stroke="var(--color-warning)" strokeDasharray="4 4" strokeWidth={1} />

            {/* Strategy-critical moments, drawn under the curve as x-axis ticks. */}
            {axis.marks.map((mark) => (
              <g key={`tick-${mark.atSec}`}>
                <title>{mark.title}</title>
                <line
                  x1={mark.x}
                  x2={mark.x}
                  y1={PAD}
                  y2={floorY}
                  stroke={TICK_STROKE[mark.tone]}
                  strokeWidth={1}
                  strokeDasharray="2 5"
                  opacity={0.5}
                />
                <line x1={mark.x} x2={mark.x} y1={floorY} y2={floorY + 3} stroke={TICK_STROKE[mark.tone]} strokeWidth={1.5} />
              </g>
            ))}
            {axis.labels.map((label) => (
              <text
                key={`axis-${label.label}-${label.x}`}
                x={label.x}
                y={floorY + 12}
                textAnchor={label.anchor}
                fontSize={9}
                fill="var(--color-faint)"
                className="font-mono"
              >
                <title>{label.title}</title>
                {label.label}
              </text>
            ))}

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
                  y1={PAD}
                  y2={floorY}
                  stroke="var(--color-fg)"
                  strokeDasharray="3 3"
                  strokeWidth={1}
                  opacity={0.45}
                />
                <circle cx={hovered.x} cy={hovered.y} r={5} fill={color} stroke="var(--color-surface)" strokeWidth={2} />
              </g>
            )}
          </svg>
        )}

        <span className="sr-only" aria-live="polite">
          {hovered ? `Up ${Math.round(hovered.v * 100)} cents at ${mmss(elapsedSec)} into the window` : ''}
        </span>

        {hovered && (
          <div
            className="pointer-events-none absolute z-20 -translate-x-1/2 -translate-y-full rounded border border-line bg-surface-2 px-2 py-1 font-mono text-[11px] text-fg shadow-pop"
            style={{ left: tipLeft, top: tipTop }}
          >
            {Math.round(hovered.v * 100)}¢
            <span className="ml-1 text-faint">{mmss(elapsedSec)}</span>
          </div>
        )}
      </div>
    </div>
  )
}
