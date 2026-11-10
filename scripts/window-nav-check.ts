import assert from 'node:assert/strict'

import { buildWindows, resolveWindowIndex, slotOfSlug } from '../src/app/lib/windows'

const SLUG_A = 'btc-updown-5m-1794297300'
const SLUG_B = 'btc-updown-5m-1794297600'
const SLUG_C = 'btc-updown-5m-1794297900'

assert.equal(slotOfSlug(SLUG_B), 1794297600)
assert.equal(slotOfSlug('garbage'), null)
assert.equal(slotOfSlug(undefined), null)
assert.equal(slotOfSlug(''), null)

const windows = buildWindows([{ slug: SLUG_B }, { slug: SLUG_A }, {}], [SLUG_C, SLUG_B])
assert.deepEqual(
  windows.map((w) => w.slot),
  [1794297300, 1794297600, 1794297900],
  'oldest first, deduped, slug-less rows ignored',
)

assert.equal(resolveWindowIndex(windows, 1794297600, null), 1, 'defaults to the running window')
assert.equal(resolveWindowIndex(windows, 1794297600, 1794297300), 0, 'honours a picked window')
assert.equal(resolveWindowIndex(windows, 1794297600, 123), 1, 'a pick that aged out falls back to live')
assert.equal(resolveWindowIndex(windows, 42, null), 2, 'no live match falls back to the newest window')
assert.equal(resolveWindowIndex([], 42, null), -1, 'empty feed has no window')

console.log('window nav ok')
