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
"""

from __future__ import annotations

import bisect
import json
import statistics
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
    book: list[dict] | None = None,
) -> dict[str, Any] | None:
    """Compare one closed window's fills with what the tape could have filled.

    Returns None when the tape holds no print for this window's own market
    inside it: silence is missing evidence, not proof that nothing traded.
    ``book`` is optional post-hoc only; None preserves the legacy static-queue
    path so all existing callers/tests stay backward compatible.
    """
    tape = _window_tape(prints, float(window_start_s), condition_id)
    if not tape:
        return None
    window_end = float(window_start_s) + C.WINDOW_S
    # This window's token ids: book rows carry asset_id but no market id, and
    # the next window's recorder starts ~10s before this one ends, so foreign
    # rows can fall inside this window's time range. Scope book rows to our
    # own tokens; rows that predate asset tagging stay unfiltered.
    _allowed_assets = {str(_p.get("asset_id") or "") for _p in tape} - {""}
    book_rows = _window_book(book, float(window_start_s), window_end, condition_id, _allowed_assets) if book else []
    verdicts = _attainability(fills, tape)
    # Dynamic per-fill realism (cancel credit + time-to-fill + taker slippage).
    dyn = _dynamic_realism(fills, tape, book_rows, float(window_start_s), window_end)
    if book_rows:
        # Cancel credit can only rescue phantom fills, never condemn a fill
        # the static queue already credits (backward-compatible upgrade).
        # Rescues share one SELL pool in _attainability order so the same
        # volume cannot fill two orders, and rescued rows are stamped so
        # detail.attainable and the window totals share one verdict.
        _pool: dict[int, float] = {}
        _order = sorted(range(len(fills)), key=lambda _oi: (-_num(fills[_oi].get("price")), fill_epoch_s(fills[_oi])))
        for _i in _order:
            if role_of(fills[_i]) == "TAKER" or not verdicts.get(_i):
                continue
            _sflow = _maker_flow_from(tape, fills[_i].get("outcome"), _num(fills[_i].get("price")), _maker_t0(fills[_i]), window_end)
            _spend(tape, _sflow, _queue_ahead(fills[_i]) + _num(fills[_i].get("shares")), _pool)
        for _i in _order:
            if role_of(fills[_i]) == "TAKER" or verdicts.get(_i):
                continue
            _shares = _num(fills[_i].get("shares"))
            if _shares <= 0:
                continue
            _ttf = (dyn.get(_i) or {}).get("timeToAttainableMs")
            if not isinstance(_ttf, (int, float)):
                continue
            _eff_end = (dyn.get(_i) or {}).get("effQueueEnd")
            if not isinstance(_eff_end, (int, float)) or isinstance(_eff_end, bool):
                _eff_end = _queue_ahead(fills[_i])
            _need = max(0.0, float(_eff_end)) + _shares
            _flow = _maker_flow_from(tape, fills[_i].get("outcome"), _num(fills[_i].get("price")), _maker_t0(fills[_i]), window_end)
            if _available(tape, _flow, _pool) + PRICE_EPS >= _need:
                verdicts[_i] = True
                fills[_i].setdefault("detail", {})["attainable"] = True
                _spend(tape, _flow, _need, _pool)

    maker = attainable = phantom = queue_known = 0
    assumed_shares = attainable_shares = 0.0
    attainable_cost = attainable_payout = 0.0
    # Band totals.
    verified_fills = verified_shares = 0.0
    verified_cost = verified_payout = 0.0
    paper_shares = paper_cost = paper_payout = 0.0
    attain_band_shares = attain_band_cost = attain_band_payout = 0.0
    time_to_fill: list[float] = []
    # Verified band: cumulative level-traded check (both sides, no queue).
    verified_map = _verified_map(fills, tape)
    for i, fill in enumerate(fills):
        shares = _num(fill.get("shares"))
        usd = _num(fill.get("usd"))
        payout = shares if winner and fill.get("outcome") == winner else 0.0
        assumed_shares += shares
        paper_shares += shares
        paper_cost += usd
        paper_payout += payout
        is_taker = role_of(fill) == "TAKER"
        if is_taker:
            # A taker fill takes the ask by definition, so the queue cannot
            # block it; only the maker fills can be phantom.
            slip = (dyn.get(i) or {}).get("takerSlipPerShare", 0.0)
            slipped_cost = usd + shares * slip
            attainable_shares += shares
            attainable_cost += slipped_cost
            attainable_payout += payout
            attain_band_shares += shares
            attain_band_cost += slipped_cost
            attain_band_payout += payout
            continue
        maker += 1
        if _queue_ahead_recorded(fill):
            queue_known += 1
        if verdicts.get(i):
            attainable += 1
            attainable_shares += shares
            attainable_cost += usd
            attainable_payout += payout
        else:
            phantom += 1
        # Bands: verified uses the weak level check; attainable uses the
        # (possibly dynamic) maker verdict; paper counts everything.
        if verified_map.get(i):
            verified_fills += 1
            verified_shares += shares
            verified_cost += usd
            verified_payout += payout
        if verdicts.get(i):
            attain_band_shares += shares
            attain_band_cost += usd
            attain_band_payout += payout
        ttf = (dyn.get(i) or {}).get("timeToAttainableMs")
        if verdicts.get(i) and isinstance(ttf, (int, float)):
            time_to_fill.append(float(ttf))

    phantom_rate = round(phantom / maker, 4) if maker else 0.0
    median_ttf = round(statistics.median(time_to_fill), 1) if time_to_fill else None
    by_minute = _by_minute(fills, verdicts, verified_map, dyn, float(window_start_s), winner)

    paper_net = paper_payout - paper_cost
    verified_net = verified_payout - verified_cost
    attain_net = attain_band_payout - attain_band_cost
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
        "bands": {
            "verified": {
                "fills": int(verified_fills),
                "shares": round(verified_shares, 2),
                "costUsd": round(verified_cost, 2),
                "payoutUsd": round(verified_payout, 2),
                "netUsd": round(verified_net, 2),
            },
            "attainable": {
                "fills": attainable + sum(1 for f in fills if role_of(f) == "TAKER"),
                "shares": round(attain_band_shares, 2),
                "costUsd": round(attain_band_cost, 2),
                "payoutUsd": round(attain_band_payout, 2),
                "netUsd": round(attain_net, 2),
            },
            "paper": {
                "fills": len(fills),
                "shares": round(paper_shares, 2),
                "costUsd": round(paper_cost, 2),
                "payoutUsd": round(paper_payout, 2),
                "netUsd": round(paper_net, 2),
            },
        },
        "phantomRate": phantom_rate,
        "medianTimeToAttainableMs": median_ttf,
        "byMinute": by_minute,
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


def _window_book(
    book: list[dict] | None, start: float, end: float, condition_id: str | None,
    allowed_assets: set[str] | None = None,
) -> list[dict]:
    if not book:
        return []
    rows = []
    for rec in book:
        try:
            ts = float(rec.get("ts") or 0.0)
        except (TypeError, ValueError):
            continue
        if ts < start or ts > end:
            continue
        rows.append(rec)
    # Book rows carry asset_id but no market id. When the window's own prints
    # name their tokens, drop rows from other markets (the next recorder
    # starts ~10s before this window ends). Rows that predate asset tagging
    # carry no asset_id and stay unfiltered.
    if allowed_assets and any(str(r.get("asset_id") or "") for r in rows):
        rows = [r for r in rows if str(r.get("asset_id") or "") in allowed_assets]
    # Keep only this window's market when condition_id is known; book rows
    # carry asset/outcome but not always market, so fall back to all rows.
    if condition_id:
        want = str(condition_id).strip()
        filt = [r for r in rows if str(r.get("market") or r.get("condition_id") or "") == want]
        if filt:
            return sorted(filt, key=lambda r: float(r.get("ts") or 0.0))
    rows.sort(key=lambda r: float(r.get("ts") or 0.0))
    return rows


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


def _verified_map(fills: list[dict], tape: list[dict]) -> dict[int, bool]:
    """Weak level check per fill: cumulative prints at/below limit >= shares."""
    out: dict[int, bool] = {}
    for i, fill in enumerate(fills):
        if role_of(fill) == "TAKER":
            out[i] = False
            continue
        shares = _num(fill.get("shares"))
        limit = _num(fill.get("price"))
        outcome = fill.get("outcome")
        cumm = sum(
            _num(p.get("size"))
            for p in tape
            if p.get("slug_outcome") == outcome and _num(p.get("price")) <= limit + PRICE_EPS
        )
        out[i] = shares > 0 and cumm + PRICE_EPS >= shares
    return out


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
            if str(p.get("slug_outcome") or "") != str(fill.get("outcome") or ""):
                continue
            if str(p.get("side") or "").upper() != "SELL":
                continue
            if _num(p.get("price")) > limit + PRICE_EPS:
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
                if abs(_num(payload.get("price")) - limit) <= 1e-6:
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
    """Positions in `tape` of taker SELL prints for `outcome` at/below `limit`.

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
        if str(print_row.get("slug_outcome") or "") != str(outcome or ""):
            continue
        if str(print_row.get("side") or "").upper() != "SELL":
            continue
        if _num(print_row.get("price")) > limit + PRICE_EPS:
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
