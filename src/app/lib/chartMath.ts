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
