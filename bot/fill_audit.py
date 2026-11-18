"""What the paper desk's maker fills could actually have got.

A maker fill is booked at the bid the moment the loop reads the book, so the
paper number assumes every resting order at the touch was first in line. A real
bid there sits behind whatever is already resting at that price, and only a
taker SELL can fill it. So a fill is attainable when taker SELL prints at or
below its limit, after it was booked, carry more size than the queue ahead of
it.

Prints record the taker side: a resting BUY is filled by a SELL print, never by
a BUY print. Getting that backwards inverts the whole result.

Where the queue is unknown (windows from before ``detail.queueAhead`` was
recorded) the fill is judged on sell size alone, which is an upper bound. Each
share sold fills one order, so the flow is spent across fills highest price then
oldest first. No prints at all in the window for its own market means the window
cannot be judged: ``audit_window`` returns None rather than declaring every fill
phantom.

Phase 1 realism (post-hoc only, no live-execution change):
- Maker ``effQueue`` with FIFO cancel credit from ``book`` snapshots
  (absolute levels per Polymarket docs MarketBookEvent: bids/asks arrays of
  [price, size]; price_change = absolute level size; last_trade_price side =
  taker side; tick_size_change = granularity only).
- New bids at our limit sit behind us (never raise effQueue). Depth drops
  grant cancel credit max(0, drop - SELL prints at L since last snap) so SELLs
  are never double-counted. A complementary BUY on the opposite token at 1-L
  can also consume depth without an own-token SELL print, so this stays in the
  attainable band, never the strict verified band.
- Taker realism: askSize at fill time + 1-2c slippage into the attainable band.

Shell: public names live here; pure logic lives in fill_util /
fill_roles / fill_realism / fill_verify.
"""

from .fill_realism import (
    _attainability,
    _available,
    _book_size_at,
    _by_minute,
    _dynamic_realism,
    _is_maker_flow_print,
    _maker_flow_from,
    _maker_t0,
    _minute_of,
    _queue_ahead,
    _queue_ahead_recorded,
    _queue_value_present,
    _sell_flow,
    _spend,
    _taker_ask_size,
    _taker_slippage,
)
from .fill_roles import load_prints, role_of
from .fill_util import PRICE_EPS, _num, _print_ts
from .fill_verify import (
    _own_market,
    _verified_map,
    _window_book,
    _window_tape,
    attainable_indexes,
    audit_window,
)

__all__ = [
    "PRICE_EPS",
    "_attainability",
    "_available",
    "_book_size_at",
    "_by_minute",
    "_dynamic_realism",
    "_is_maker_flow_print",
    "_maker_flow_from",
    "_maker_t0",
    "_minute_of",
    "_num",
    "_own_market",
    "_print_ts",
    "_queue_ahead",
    "_queue_ahead_recorded",
    "_queue_value_present",
    "_sell_flow",
    "_spend",
    "_taker_ask_size",
    "_taker_slippage",
    "_verified_map",
    "_window_book",
    "_window_tape",
    "attainable_indexes",
    "audit_window",
    "load_prints",
    "role_of",
]
