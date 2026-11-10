import assert from 'node:assert/strict'

import { buildWindows, resolveWindowIndex, slotOfSlug, slotOfTime, windowSlotOf } from '../src/app/lib/windows'

const SLUG_A = 'btc-updown-5m-1794297300'
const SLUG_B = 'btc-updown-5m-1794297600'
const SLUG_C = 'btc-updown-5m-1794297900'

assert.equal(slotOfSlug(SLUG_B), 1794297600)
assert.equal(slotOfSlug('garbage'), null)
assert.equal(slotOfSlug(undefined), null)
assert.equal(slotOfSlug(''), null)

// Timestamps bucket into their own 5m window, in seconds, ms or ISO form.
assert.equal(slotOfTime(1794297600), 1794297600)
assert.equal(slotOfTime(1794297600_000), 1794297600)
assert.equal(slotOfTime(1794297600_000 + 299_999), 1794297600)
assert.equal(slotOfTime(1794297600_000 + 300_000), 1794297900)
assert.equal(slotOfTime(new Date(1794297600_000).toISOString()), 1794297600)
assert.equal(slotOfTime('garbage'), null)
assert.equal(slotOfTime(undefined), null)

// A fill placed 8s before its market's slot belongs to the window that closed.
const earlyFill = { ts: 1794297592_000, slug: SLUG_B }
assert.equal(windowSlotOf(earlyFill), 1794297300, 'pre-open fill lands in the previous window')
assert.equal(windowSlotOf({ ts: 1794297605_000, slug: SLUG_B }), 1794297600, 'in-window fill stays put')
assert.equal(windowSlotOf({ slug: SLUG_B }), 1794297600, 'no timestamp falls back to the slug')
assert.equal(windowSlotOf({}), null)

const windows = buildWindows([{ slug: SLUG_B }, { slug: SLUG_A }, {}], [SLUG_C, SLUG_B])
assert.deepEqual(
  windows.map((w) => w.slot),
  [1794297300, 1794297600, 1794297900],
  'oldest first, deduped, slug-less rows ignored',
)

// A fill before its own market's slot keeps that earlier window navigable.
const earlyWindows = buildWindows([earlyFill], [SLUG_B])
assert.deepEqual(
  earlyWindows.map((w) => w.slot),
  [1794297300, 1794297600],
  'timestamp-only window added next to the slug window',
)
assert.equal(earlyWindows[0].slug, '', 'timestamp-only window carries no slug')
assert.equal(
  earlyWindows.filter((w) => windowSlotOf(earlyFill) === w.slot).length,
  1,
  'the pre-open fill is visible in exactly one window',
)

assert.equal(resolveWindowIndex(windows, 1794297600, null), 1, 'defaults to the running window')
assert.equal(resolveWindowIndex(windows, 1794297600, 1794297300), 0, 'honours a picked window')
assert.equal(resolveWindowIndex(windows, 1794297600, 123), 1, 'a pick that aged out falls back to live')
assert.equal(resolveWindowIndex(windows, 42, null), 2, 'no live match falls back to the newest window')
assert.equal(resolveWindowIndex([], 42, null), -1, 'empty feed has no window')

console.log('window nav ok')
