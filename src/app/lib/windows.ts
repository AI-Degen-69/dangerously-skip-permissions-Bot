// Window picker for the fills table: which 5m windows the feed knows about, and
// which one is being viewed. Pure so scripts/window-nav-check.ts can lock it.

/** Window length; Polymarket 5m markets start on these boundaries. */
export const WINDOW_SECONDS = 300

/** `btc-updown-5m-1794297600` → 1794297600 (epoch seconds); null when unparseable. */
export function slotOfSlug(slug: string | null | undefined): number | null {
  const epoch = Number(String(slug ?? '').split('-').pop())
  return Number.isFinite(epoch) && epoch > 0 ? epoch : null
}

/** Epoch seconds, epoch milliseconds or an ISO string → the window slot containing it. */
export function slotOfTime(ts: number | string | null | undefined): number | null {
  const raw = typeof ts === 'string' ? Number(ts) || Date.parse(ts) : ts
  if (raw == null || !Number.isFinite(raw) || raw <= 0) return null
  const ms = raw < 1e11 ? raw * 1000 : raw
  return Math.floor(ms / 1000 / WINDOW_SECONDS) * WINDOW_SECONDS
}

/**
 * The window a feed row belongs to. Its execution timestamp wins over the slug
 * it was recorded under: the bot tags fills placed by its pre-open pipeline
 * with the upcoming window, yet those fills happened before it opened.
 */
export function windowSlotOf(item: { ts?: number | string; slug?: string }): number | null {
  return slotOfTime(item.ts) ?? slotOfSlug(item.slug)
}

export interface WindowRef {
  slot: number
  slug: string
  /** Empty when the window is only known from a row's timestamp. */
}

/** Windows with a slug or at least one trade, oldest first. */
export function buildWindows(items: { ts?: number | string; slug?: string }[], windowSlugs: string[]): WindowRef[] {
  const bySlot = new Map<number, string>()
  const addSlug = (slug?: string) => {
    const slot = slotOfSlug(slug)
    if (slot != null && slug) bySlot.set(slot, slug)
  }
  for (const slug of windowSlugs) addSlug(slug)
  for (const item of items) addSlug(item.slug)
  // A fill can land just before its market's slot; keep that earlier window
  // navigable even when no slug names it.
  for (const item of items) {
    const slot = windowSlotOf(item)
    if (slot != null && !bySlot.has(slot)) bySlot.set(slot, '')
  }
  return [...bySlot.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([slot, slug]) => ({ slot, slug }))
}

/**
 * Which window to show: the picked one while it still exists, otherwise the
 * running window — or the newest known window when the live slot is missing.
 */
export function resolveWindowIndex(windows: WindowRef[], liveSlot: number | null, pickedSlot: number | null): number {
  if (pickedSlot != null) {
    const picked = windows.findIndex((w) => w.slot === pickedSlot)
    if (picked >= 0) return picked
  }
  const live = liveSlot == null ? -1 : windows.findIndex((w) => w.slot === liveSlot)
  return live >= 0 ? live : windows.length - 1
}
