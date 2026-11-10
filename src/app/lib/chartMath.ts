// Projection of the live probability series onto the chart canvas. Pure
// functions so the clamps can be locked by scripts/chart-math-check.ts — an
// out-of-range sample must never push the path outside the plot, because the
// SVG blur filter derives its surface from the path's bounding box.

/** Window timestamp to an x pixel inside the plot; out-of-range samples clamp to the edges. */
export const projectX = (t: number, startMs: number, span: number, plotW: number) =>
  Math.min(plotW, Math.max(0, ((t - startMs) / span) * plotW))

/** Probability (0..1) to a y pixel inside the plot box; out-of-range values clamp. */
export const projectY = (v: number, pad: number, floor: number) =>
  pad + (floor - pad) * (1 - Math.min(1, Math.max(0, v)))

export interface AxisLabel {
  x: number
  label: string
  title: string
  anchor: 'start' | 'middle' | 'end'
}

/**
 * Elapsed-time labels for the x-axis: both endpoints always, an interior mark
 * only when `gap` px separates it from every label already placed. Marks that
 * lose their label keep their line, so the moment stays visible.
 */
export function axisLabels(
  marks: { x: number; label: string; title: string }[],
  plotW: number,
  gap: number,
  start: { label: string; title: string },
  end: { label: string; title: string },
): AxisLabel[] {
  const labels: AxisLabel[] = [
    { x: 0, label: start.label, title: start.title, anchor: 'start' },
    { x: plotW, label: end.label, title: end.title, anchor: 'end' },
  ]
  for (const mark of marks) {
    if (labels.some((label) => Math.abs(label.x - mark.x) < gap)) continue
    labels.push({ x: mark.x, label: mark.label, title: mark.title, anchor: 'middle' })
  }
  return labels.sort((a, b) => a.x - b.x)
}
