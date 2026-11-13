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
"""

from __future__ import annotations

import bisect
import json
from pathlib import Path
from typing import Any

from bot import constants as C
from bot.runs import tape_segments
from bot.tape_verifier import fill_epoch_s


# Print prices and limits are both 3-decimal grid values, so a 1e-9 tolerance
# only absorbs float noise - it never lets a worse price through.
PRICE_EPS = 1e-9


def load_prints(tape_dir: Path) -> list[dict]:
    """Every print recorded for the run, oldest first."""
    prints: list[dict] = []
    for path in tape_segments(tape_dir, "prints"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        prints.append(json.loads(line))
                    except (json.JSONDecodeError, ValueError):
                        continue
        except OSError:
            continue
    prints.sort(key=_print_ts)
    return prints


def role_of(fill: dict) -> str:
    """MAKER or TAKER, with the same precedence the desk uses for fees.

    A recorded role wins, then a recorded fee, then the legacy reason text:
    equalizer and snipe fills were taker fills before roles were stamped.
    """
    detail = fill.get("detail") or {}
    role = str(detail.get("role") or "").upper()
    if role in ("MAKER", "TAKER"):
        return role
    fee = detail.get("feeUsd")
    if isinstance(fee, (int, float)) and not isinstance(fee, bool):
        return "TAKER" if fee > 0 else "MAKER"
    reason = str(fill.get("reason") or "").lower()
    return "TAKER" if ("equalizer" in reason or "snipe" in reason) else "MAKER"


def audit_window(
    fills: list[dict],
    prints: list[dict],
    window_start_s: float,
    winner: str | None,
    condition_id: str | None = None,
) -> dict[str, Any] | None:
    """Compare one closed window's fills with what the tape could have filled.

    Returns None when the tape holds no print for this window's own market
    inside it: silence is missing evidence, not proof that nothing traded.
    """
    tape = _window_tape(prints, float(window_start_s), condition_id)
    if not tape:
        return None
    verdicts = _attainability(fills, tape)

    maker = attainable = phantom = queue_known = 0
    assumed_shares = attainable_shares = 0.0
    attainable_cost = attainable_payout = 0.0
    for i, fill in enumerate(fills):
        shares = _num(fill.get("shares"))
        assumed_shares += shares
        payout = shares if winner and fill.get("outcome") == winner else 0.0
        if role_of(fill) == "TAKER":
            # A taker fill takes the ask by definition, so the queue cannot
            # block it; only the maker fills can be phantom.
            attainable_shares += shares
            attainable_cost += _num(fill.get("usd"))
            attainable_payout += payout
            continue
        maker += 1
        if _queue_ahead_recorded(fill):
            queue_known += 1
        if verdicts[i]:
            attainable += 1
            attainable_shares += shares
            attainable_cost += _num(fill.get("usd"))
            attainable_payout += payout
        else:
            phantom += 1

    return {
        "makerFills": maker,
        "attainableFills": attainable,
        "phantomFills": phantom,
        "queueKnown": queue_known,
        "assumedShares": round(assumed_shares, 2),
        "attainableShares": round(attainable_shares, 2),
        "attainableCostUsd": round(attainable_cost, 2),
        "attainablePayoutUsd": round(attainable_payout, 2),
        "attainableNetUsd": round(attainable_payout - attainable_cost, 2),
    }


def attainable_indexes(
    fills: list[dict],
    window_prints: list[dict],
    condition_id: str | None = None,
) -> dict[int, bool] | None:
    """Fill index -> could it have filled on the selling recorded so far.

    `window_prints` must already be bounded to this window. Winner-independent,
    so the live loop calls it while the window is still trading: a False there
    means "not yet" - later selling can still fill the order. None when the tape
    holds no print for this window's own market.
    """
    tape = _own_market(window_prints, condition_id)
    if not tape:
        return None
    return _attainability(fills, tape)


def _window_tape(prints: list[dict], start: float, condition_id: str | None) -> list[dict]:
    lo = bisect.bisect_left(prints, start, key=_print_ts)
    hi = bisect.bisect_right(prints, start + C.WINDOW_S, key=_print_ts)
    return _own_market(prints[lo:hi], condition_id)


def _attainability(fills: list[dict], tape: list[dict]) -> dict[int, bool]:
    """One print's size fills one order only, and the taker hits the most
    aggressive bid first: spend the flow highest price then oldest first."""
    verdicts: dict[int, bool] = {}
    taken: dict[int, float] = {}
    order = sorted(range(len(fills)), key=lambda i: (-_num(fills[i].get("price")), fill_epoch_s(fills[i])))
    for i in order:
        fill = fills[i]
        if role_of(fill) == "TAKER":
            verdicts[i] = True
            continue
        shares = _num(fill.get("shares"))
        ahead = _queue_ahead(fill)
        flow = _sell_flow(tape, fill, _num(fill.get("price")))
        ok = shares > 0 and _available(tape, flow, taken) - ahead >= shares - PRICE_EPS
        verdicts[i] = ok
        if ok:
            _spend(tape, flow, ahead + shares, taken)
    return verdicts


def _queue_ahead_recorded(fill: dict) -> bool:
    ahead = (fill.get("detail") or {}).get("queueAhead")
    return isinstance(ahead, (int, float)) and not isinstance(ahead, bool) and ahead >= 0


def _queue_ahead(fill: dict) -> float:
    ahead = (fill.get("detail") or {}).get("queueAhead")
    if isinstance(ahead, (int, float)) and not isinstance(ahead, bool) and ahead >= 0:
        return float(ahead)
    return 0.0


def _print_ts(print_row: dict) -> float:
    return _num(print_row.get("ts"))


def _own_market(tape: list[dict], condition_id: str | None) -> list[dict]:
    """This window's prints only.

    Windows record their condition id; older ones do not, and the window's own
    recorder is the first to write into its time range, so the earliest market
    in the slice is this window's. The next market's recorder starts 10s before
    this one ends, and its "Up"/"Down" SELLs must not read as flow here.
    """
    market = str(condition_id or "").strip()
    if not market:
        market = str(tape[0].get("market") or "") if tape else ""
    if not market:
        return tape
    return [p for p in tape if str(p.get("market") or "") == market]


def _sell_flow(tape: list[dict], fill: dict, price: float) -> list[int]:
    """Positions in `tape` of taker SELL prints at or below `price`, from the fill on."""
    outcome = fill.get("outcome")
    first = bisect.bisect_left(tape, fill_epoch_s(fill), key=_print_ts)
    flow: list[int] = []
    for i in range(first, len(tape)):
        print_row = tape[i]
        if print_row.get("slug_outcome") != outcome:
            continue
        if str(print_row.get("side") or "").upper() != "SELL":
            continue
        if _num(print_row.get("price")) > price + PRICE_EPS:
            continue
        flow.append(i)
    return flow


def _available(tape: list[dict], flow: list[int], taken: dict[int, float]) -> float:
    """Sell size in `flow` that no earlier fill has spent."""
    return sum(max(0.0, _num(tape[i].get("size")) - taken.get(i, 0.0)) for i in flow)


def _spend(tape: list[dict], flow: list[int], need: float, taken: dict[int, float]) -> None:
    """Spend `need` shares of the flow, oldest print first."""
    for i in flow:
        if need <= PRICE_EPS:
            return
        free = max(0.0, _num(tape[i].get("size")) - taken.get(i, 0.0))
        used = min(free, need)
        if used > 0.0:
            taken[i] = taken.get(i, 0.0) + used
            need -= used


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
