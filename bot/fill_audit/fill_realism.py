"""Fill attainability and realism engine (queues, depth, slippage)."""

from __future__ import annotations


import bisect
import statistics
from typing import Any

from .fill_roles import role_of
from .fill_util import PRICE_EPS, _num, _print_ts
from bot.tape_verifier import fill_epoch_s


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

def _dynamic_realism(
    fills: list[dict],
    tape: list[dict],
    book_rows: list[dict],
    window_start: float,
    window_end: float,
) -> dict[int, dict[str, Any]]:
    """Per-fill dynamic realism: effQueue cancel credit + taker slippage.

    Maker: walk merged (book, SELL-print) events from t0; depth drops grant
    cancel credit net of SELL prints at L since the last snapshot.
    Taker: resolve askSize(t0) and model 1-2c slippage into the band.
    No book -> legacy static values (backward compatible).
    """
    out: dict[int, dict[str, Any]] = {}
    # Index book rows by outcome for quick lookup.
    books_by_outcome: dict[str, list[dict]] = {}
    for rec in book_rows:
        oc = str(rec.get("outcome") or "")
        books_by_outcome.setdefault(oc, []).append(rec)
    for i, fill in enumerate(fills):
        detail = fill.get("detail") or {}
        t_fill = fill_epoch_s(fill)
        try:
            t0 = float(detail.get("placedAtMs", 0)) / 1000.0 if detail.get("placedAtMs") else t_fill
        except (TypeError, ValueError):
            t0 = t_fill
        if role_of(fill) == "TAKER":
            shares = _num(fill.get("shares"))
            ask = _taker_ask_size(fill, books_by_outcome.get(str(fill.get("outcome") or ""), []), t_fill)
            slip = _taker_slippage(shares, ask, fill, books_by_outcome.get(str(fill.get("outcome") or ""), []), t_fill)
            out[i] = {
                "takerAskSize": ask,
                "takerDepthOk": (ask is not None and ask + PRICE_EPS >= shares) if ask is not None else None,
                "takerSlipPerShare": slip,
            }
            continue
        # Maker dynamic effQueue.
        limit = _num(fill.get("price"))
        shares = _num(fill.get("shares"))
        init_q = _num(detail.get("queueAheadAtPlace")) if _queue_value_present(detail.get("queueAheadAtPlace")) else _queue_ahead(fill)
        if not book_rows:
            out[i] = {"effQueueStart": round(init_q, 2), "effQueueEnd": round(init_q, 2), "timeToAttainableMs": None}  # No book: timing unavailable, never 0.0 ms
            continue
        eff = max(0.0, init_q)
        prev = init_q
        sells_le = 0.0
        sells_at_L = 0.0
        ttf: float | None = None
        # Merge events after t0.
        events: list[tuple[float, str, Any]] = []
        for p in tape:
            try:
                pts = float(p.get("ts") or 0.0)
            except (TypeError, ValueError):
                continue
            if pts < t0 or pts > window_end:
                continue
            ok, _ = _is_maker_flow_print(p, fill.get("outcome"), limit)
            if not ok:
                continue
            events.append((pts, "print", p))
        for rec in books_by_outcome.get(str(fill.get("outcome") or ""), []):
            try:
                bts = float(rec.get("ts") or 0.0)
            except (TypeError, ValueError):
                continue
            if bts < t0 or bts > window_end:
                continue
            events.append((bts, "book", rec))
        events.sort(key=lambda e: e[0])
        for ts, kind, payload in events:
            if kind == "print":
                sz = _num(payload.get("size"))
                sells_le += sz
                _, at_level = _is_maker_flow_print(payload, fill.get("outcome"), limit)
                if at_level:
                    sells_at_L += sz
            else:
                cur = _book_size_at(payload, limit)
                if cur is None:
                    # Snapshot does not cover our limit: depth unknown, so
                    # grant no cancel credit here and keep the last known
                    # depth instead of treating it as emptied.
                    continue
                delta = cur - prev
                if delta < -PRICE_EPS:
                    cancel = max(0.0, (-delta) - sells_at_L)
                    eff = max(0.0, eff - cancel)
                # New bids sit behind us: never raise effQueue.
                prev = cur
                sells_at_L = 0.0
            if shares > 0 and sells_le + PRICE_EPS >= eff + shares and ttf is None:
                ttf = round((ts - t0) * 1000.0, 1)
        out[i] = {
            "effQueueStart": round(init_q, 2),
            "effQueueEnd": round(eff, 2),
            "timeToAttainableMs": ttf,
        }
    return out

def _queue_value_present(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0

def _book_size_at(rec: dict, limit: float) -> float | None:
    """Depth resting at exactly `limit`, or None when the snapshot is silent.

    Only the top-5 bid levels are recorded: a limit below them has unknown
    depth behind it, which must never read as zero (that would grant the
    whole recorded queue as cancel credit).
    """
    for rung in rec.get("bids") or []:
        try:
            p, s = float(rung[0]), float(rung[1])
        except (TypeError, ValueError, IndexError):
            continue
        if abs(p - limit) <= 1e-6:
            return max(0.0, s)
    return None

def _taker_ask_size(fill: dict, brows: list[dict], t_fill: float) -> float | None:
    detail = fill.get("detail") or {}
    v = detail.get("askSize")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
        return float(v)
    best: float | None = None
    best_ts = -1.0
    for rec in brows:
        try:
            ts = float(rec.get("ts") or 0.0)
        except (TypeError, ValueError):
            continue
        if ts > t_fill or ts < best_ts:
            continue
        asks = rec.get("asks") or []
        if not asks:
            continue
        try:
            sz = float(asks[0][1])
        except (TypeError, ValueError, IndexError):
            continue
        best, best_ts = sz, ts
    return best

def _taker_slippage(
    shares: float, ask: float | None, fill: dict, brows: list[dict], t_fill: float
) -> float:
    px = _num(fill.get("price"))
    # Prefer walking the asks rungs when a book snapshot is available.
    snap = None
    snap_ts = -1.0
    for rec in brows:
        try:
            ts = float(rec.get("ts") or 0.0)
        except (TypeError, ValueError):
            continue
        if ts > t_fill or ts < snap_ts:
            continue
        if not (rec.get("asks") or []):
            continue
        snap, snap_ts = rec, ts
    if snap is not None:
        try:
            need = shares
            cost = 0.0
            for rung in snap.get("asks") or []:
                p, s = float(rung[0]), float(rung[1])
                take = min(need, max(0.0, s))
                cost += take * p
                need -= take
                if need <= PRICE_EPS:
                    break
            if need > PRICE_EPS:
                return 0.02
            avg = cost / shares if shares > 0 else px
            return round(max(0.0, avg - px), 4)
        except (TypeError, ValueError, IndexError, ZeroDivisionError):
            pass
    if ask is None or ask <= 0 or shares <= 0:
        return 0.0
    if shares > ask + PRICE_EPS:
        return 0.02
    if shares > 0.5 * ask + PRICE_EPS:
        return 0.01
    return 0.0

def _by_minute(
    fills: list[dict],
    verdicts: dict[int, bool],
    verified_map: dict[int, bool],
    dyn: dict[int, dict[str, Any]],
    window_start: float,
    winner: str | None,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for m in range(5):
        key = f"M{m}"
        idx = [i for i, f in enumerate(fills) if _minute_of(f, window_start) == m and role_of(f) == "MAKER"]
        ttf = [float((dyn.get(i) or {}).get("timeToAttainableMs")) for i in idx if verdicts.get(i) and isinstance((dyn.get(i) or {}).get("timeToAttainableMs"), (int, float))]
        out[key] = {
            "verified": sum(1 for i in idx if verified_map.get(i)),
            "attainable": sum(1 for i in idx if verdicts.get(i)),
            "phantom": sum(1 for i in idx if not verdicts.get(i)),
            "medianTimeToAttainableMs": round(statistics.median(ttf), 1) if ttf else None,
        }
    return out

def _minute_of(fill: dict, window_start: float) -> int:
    ts = fill_epoch_s(fill)
    m = int((ts - window_start) // 60)
    return min(max(m, 0), 4)

def _queue_ahead_recorded(fill: dict) -> bool:
    ahead = (fill.get("detail") or {}).get("queueAhead")
    return isinstance(ahead, (int, float)) and not isinstance(ahead, bool) and ahead >= 0

def _queue_ahead(fill: dict) -> float:
    ahead = (fill.get("detail") or {}).get("queueAhead")
    if isinstance(ahead, (int, float)) and not isinstance(ahead, bool) and ahead >= 0:
        return float(ahead)
    return 0.0

def _is_maker_flow_print(print_row: dict, outcome: object, limit: float) -> tuple[bool, bool]:
    """Return (matches_flow, at_exact_limit) for direct SELL or complementary BUY prints.

    Direct match: SELL/ASK on ``outcome`` with price <= ``limit`` + PRICE_EPS.
    Complementary match: BUY/BID on the opposite binary outcome with
    price >= (1.0 - ``limit``) - PRICE_EPS.
    """
    target_oc = str(outcome or "")
    print_oc = str(print_row.get("slug_outcome") or "")
    side = str(print_row.get("side") or "").upper()
    px = _num(print_row.get("price"))
    if print_oc == target_oc:
        if side in ("SELL", "ASK", "SELLS") and px <= limit + PRICE_EPS:
            return True, abs(px - limit) <= 1e-6
        return False, False
    if (target_oc, print_oc) in (("Up", "Down"), ("Down", "Up")):
        comp_limit = 1.0 - limit
        if side in ("BUY", "BID", "BUYS") and px >= comp_limit - PRICE_EPS:
            return True, abs(px - comp_limit) <= 1e-6
    return False, False


def _sell_flow(tape: list[dict], fill: dict, price: float) -> list[int]:
    """Positions in `tape` of attainable maker flow (direct SELL or complementary BUY), from the fill on."""
    outcome = fill.get("outcome")
    first = bisect.bisect_left(tape, fill_epoch_s(fill), key=_print_ts)
    flow: list[int] = []
    for i in range(first, len(tape)):
        ok, _ = _is_maker_flow_print(tape[i], outcome, price)
        if ok:
            flow.append(i)
    return flow

def _maker_t0(fill: dict) -> float:
    """Placement time for a maker fill: placedAtMs when recorded, else fill time."""
    detail = fill.get("detail") or {}
    t_fill = fill_epoch_s(fill)
    try:
        t0 = float(detail.get("placedAtMs", 0)) / 1000.0 if detail.get("placedAtMs") else t_fill
    except (TypeError, ValueError):
        t0 = t_fill
    return t0

def _maker_flow_from(tape: list[dict], outcome: object, limit: float, t0: float, window_end: float) -> list[int]:
    """Positions in `tape` of attainable maker flow for `outcome` at `limit`.

    Same price/side/outcome gates as `_sell_flow`, but measured from placement
    time `t0` (not fill time) so cancel-credit rescues compete for the same
    volume the static check spends, oldest print first.
    """
    flow: list[int] = []
    for i, print_row in enumerate(tape):
        try:
            pts = float(print_row.get("ts") or 0.0)
        except (TypeError, ValueError):
            continue
        if pts < t0 or pts > window_end:
            continue
        ok, _ = _is_maker_flow_print(print_row, outcome, limit)
        if ok:
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
