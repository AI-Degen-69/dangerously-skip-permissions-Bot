// Window picker for the fills table: which 5m windows the feed knows about, and
// which one is being viewed. Pure so scripts/window-nav-check.ts can lock it.

/** `btc-updown-5m-1794297600` → 1794297600 (epoch seconds); null when unparseable. */
export function slotOfSlug(slug: string | null | undefined): number | null {
  const epoch = Number(String(slug ?? '').split('-').pop())
  return Number.isFinite(epoch) && epoch > 0 ? epoch : null
}

export interface WindowRef {
  slot: number
  slug: string
}

/** Windows with a slug or at least one trade, oldest first. */
export function buildWindows(items: { slug?: string }[], windowSlugs: string[]): WindowRef[] {
  const bySlot = new Map<number, string>()
  for (const slug of windowSlugs) {
    const slot = slotOfSlug(slug)
    if (slot != null) bySlot.set(slot, slug)
  }
  for (const item of items) {
    const slot = slotOfSlug(item.slug)
    if (slot != null && item.slug) bySlot.set(slot, item.slug)
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
