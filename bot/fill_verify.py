"""Window verification: audit_window and attainable-index entry points."""

from __future__ import annotations


import bisect
import statistics
from typing import Any

from . import constants as C
from .fill_realism import (
    _attainability,
    _available,
    _by_minute,
    _dynamic_realism,
    _maker_flow_from,
    _maker_t0,
    _queue_ahead,
    _queue_ahead_recorded,
    _spend,
)
from .fill_roles import role_of
from .fill_util import PRICE_EPS, _num, _print_ts
from .tape_verifier import fill_epoch_s


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
