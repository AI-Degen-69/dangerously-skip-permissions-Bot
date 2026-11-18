"""Performance and execution-health view (straddle paper loop)."""

import math
import statistics
import time

from .views_common import _mean, _median, _num, _window_row


def build_perf(raw_runs, cfg, selected_run_id, config_snapshot, loop_pid, current_state, kill_switch, bankroll_default=1000.0, utc_now=""):
    """Performance and execution health for the straddle paper loop.

    Everything here is computed from run windows (data/runs/<run_id>/windows/*.json)
    with data/windows_mirror/*.json as fallback (no network), so the desk can
    answer two questions in one read: how much did the paper loop make, and is it
    executing the way the strategy intends — both legs covered, pair cost under
    its own cap, fills a real bid could have got.
    """
    from bot import constants as C

    raw_runs = sorted(raw_runs, key=lambda r: str(r.get("event_slug", "")))
    rows = [_window_row(r) for r in raw_runs]
    settled = [w for w in rows if not w["pending"]]
    pending = [w for w in rows if w["pending"]]

    cost = round(sum(w["costUsd"] for w in settled), 2)
    payout = round(sum(w["payoutUsd"] for w in settled), 2)
    net = round(payout - cost, 2)
    fills = sum(w["trades"] for w in settled)
    profitable = sum(1 for w in settled if (w["netUsd"] or 0) > 0)
    both = sum(1 for w in settled if w["bothSides"])
    zero_fills = sum(w["zeroPriceFills"] for w in settled)
    up_fills = sum(w["upFills"] for w in settled)
    down_fills = sum(w["downFills"] for w in settled)
    nets = [w["netUsd"] or 0.0 for w in settled]

    median_fills = _median([float(w["trades"]) for w in settled])
    mean_fills = _mean([float(w["trades"]) for w in settled])
    median_cost = _median([w["costUsd"] for w in settled])
    mean_cost = _mean([w["costUsd"] for w in settled])

    live_shape = [0, 0, 0, 0, 0]
    m_attainable = [0, 0, 0, 0, 0]
    m_phantom = [0, 0, 0, 0, 0]
    for w in settled:
        for i, n in enumerate(w["mShape"]):
            live_shape[i] += n
        for i in range(5):
            m_attainable[i] += w["mAttainable"][i]
            m_phantom[i] += w["mPhantom"][i]
    live_total = sum(live_shape) or 1
    live_share = [round(n / live_total, 4) for n in live_shape]

    # The queue audit judges only maker fills the tape could read at all.
    audited = [w["fidelity"] for w in settled if w.get("fidelity")]
    a_maker = sum(int(f.get("makerFills") or 0) for f in audited)
    a_attainable = sum(int(f.get("attainableFills") or 0) for f in audited)
    a_phantom = sum(int(f.get("phantomFills") or 0) for f in audited)
    fill_rate = round(a_attainable / a_maker, 4) if a_maker else None

    # Config decides the pair-cost bar: the strategy's own cap, not a tape mean.
    cfg = dict(config_snapshot) if isinstance(config_snapshot, dict) else dict(cfg or {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg_bankroll = cfg.get("bankrollUsd")
    bankroll = _num(cfg_bankroll, default=float(bankroll_default))
    entry_cfg = cfg.get("entry") if isinstance(cfg.get("entry"), dict) else {}
    pair_cap = _num(entry_cfg.get("maxPairCost"), default=0.985)

    both_rate = round(both / len(settled), 4) if settled else 0.0
    pair_costs = [w["pairCost"] for w in settled if w["pairCost"] is not None]
    median_pair_cost = _median(pair_costs)

    both_status = "stat" if not settled else ("pass" if both == len(settled) else ("warn" if both_rate >= 0.8 else "fail"))
    if not pair_costs:
        pair_status = "stat"
    elif median_pair_cost <= pair_cap:
        pair_status = "pass"
    else:
        pair_status = "warn" if median_pair_cost <= 1.0 else "fail"

    # The funnel the run actually walked: windows -> orders -> fills by side ->
    # paired positions -> the lone legs that never got a partner.
    counted_orders = [w for w in settled if w["ordersPosted"] is not None]
    orders_made = sum(int(w["ordersPosted"] or 0) for w in counted_orders)
    orders_cancelled = sum(int(w["ordersCancelled"] or 0) for w in counted_orders)

    def side_stats(outcome: str) -> dict:
        settled_slugs = {w["slug"] for w in settled}
        side_fills = [
            f
            for r in raw_runs
            if r.get("event_slug") in settled_slugs
            for f in (r.get("fills") or [])
            if f.get("outcome") == outcome
        ]
        shares = [_num(f.get("shares")) for f in side_fills]
        prices = [_num(f.get("price")) for f in side_fills if _num(f.get("price")) > 0]
        return {
            "count": len(side_fills),
            "shares": round(sum(shares), 2),
            "medianShares": _median(shares),
            "avgShares": _mean(shares),
            "medianPrice": _median(prices),
            "avgPrice": _mean(prices),
        }

    up_stats = side_stats("Up")
    down_stats = side_stats("Down")

    paired_windows = [w for w in settled if w["upShares"] > 0 and w["downShares"] > 0]
    paired_shares = [w["pairedShares"] for w in paired_windows]
    single_windows = [w for w in settled if w["singleSide"]]
    single_shares = [w["singleShares"] for w in single_windows]

    # Shares, not fills: a pair is made of the smaller side, so every share
    # above that minimum is a share nobody paired.
    up_shares_total = sum(w["upShares"] for w in settled)
    down_shares_total = sum(w["downShares"] for w in settled)
    total_shares = up_shares_total + down_shares_total
    net_side_diff = up_shares_total - down_shares_total
    unpaired_total = sum(abs(w["upShares"] - w["downShares"]) for w in settled)
    unpaired_in_two_sided = unpaired_total - sum(single_shares)

    # The card is a matrix, not a list of sentences: every number lives in a
    # cell next to the number it belongs with.
    def cell(key: str, label: str, value: str, sub: list[tuple[str, str]],
             status: str = "stat", tone: str | None = None, big: bool = False,
             span: int = 1) -> dict:
        return {
            "key": key,
            "label": label,
            "value": value,
            "status": status,
            "big": big,
            "span": span,
            "sub": [{"label": name, "value": text, "tone": tone} for name, text in sub],
        }

    def share_fmt(value: float) -> str:
        return f"{round(value, 1):g} sh"

    cells = [
        cell("windows", "Windows traded", f"{len(settled)}",
             [("Pending", f"{len(pending)}")]),
        cell("orders", "Orders made",
             f"{orders_made}" if counted_orders else "—",
             ([("Cancelled", f"{orders_cancelled}"),
               ("Windows counted", f"{len(counted_orders)} of {len(settled)}")] if counted_orders
              else [("Cancelled", "—"), ("Windows counted", f"0 of {len(settled)}")])),
        cell("totalShares", "Total shares filled", f"{total_shares:,.0f} sh",
             [("Up", f"{up_shares_total:,.0f}"), ("Down", f"{down_shares_total:,.0f}"),
              ("Fills", f"{up_stats['count'] + down_stats['count']:,}"),
              ("Side difference", f"{abs(net_side_diff):,.0f} sh")],
             big=True, span=2),
        cell("fillsUp", "Filled orders · Up", f"{up_stats['count']:,}",
             [("Median size", share_fmt(up_stats['medianShares'])),
              ("Median price", f"{up_stats['medianPrice'] * 100:.1f}¢"),
              ("Shares", f"{up_shares_total:,.0f}")]),
        cell("fillsDown", "Filled orders · Down", f"{down_stats['count']:,}",
             [("Median size", share_fmt(down_stats['medianShares'])),
              ("Median price", f"{down_stats['medianPrice'] * 100:.1f}¢"),
              ("Shares", f"{down_shares_total:,.0f}")]),
        cell("paired", "Paired orders", f"{len(paired_windows):,}",
             [("Paired shares", f"{sum(paired_shares):,.0f}"),
              ("Median / window", share_fmt(_median(paired_shares))),
              ("Lock-in", f"{median_pair_cost * 100:.1f}¢"),
              ("Your cap", f"{pair_cap * 100:.1f}¢")],
             status=pair_status, span=2),
        cell("unpaired", "Unpaired shares", f"{unpaired_total:,.0f} sh",
             [("Lone-leg positions", f"{sum(single_shares):,.0f}"),
              ("Inside two-sided windows", f"{unpaired_in_two_sided:,.0f}"),
              ("Net side difference", f"{abs(net_side_diff):,.0f} sh")]),
        cell("single", "Single-side positions", f"{len(single_windows):,}",
             [("Shares held", f"{sum(single_shares):,.0f}"),
              ("Median size", share_fmt(_median(single_shares))),
              ("Share of windows", f"{(len(single_windows) / len(settled) * 100) if settled else 0:.0f}%")],
             status="stat" if not single_windows else ("warn" if len(single_windows) <= len(settled) * 0.2 else "fail")),
        cell("bothSides", "Both sides covered", f"{both}/{len(settled)}" if settled else "0/0",
             [("Coverage", f"{(both_rate * 100):.0f}%")], status=both_status),
        cell("attainable", "Queue fill rate",
             f"{fill_rate * 100:.0f}%" if fill_rate is not None else "—",
             [("Audited maker fills", f"{a_maker:,}"),
              ("Could fill", f"{a_attainable:,}"),
              ("Never could", f"{a_phantom:,}")]),
        cell("zeroPrice", "Zero-price fills", f"{zero_fills}",
             [("Cost moved", "$0.00")], status="pass" if zero_fills == 0 else "fail"),
        cell("perWindow", "Per window", f"{median_fills:g} fills",
             [("Mean fills", f"{mean_fills:.1f}"),
              ("Median cost", f"${median_cost:,.2f}"),
              ("Mean cost", f"${mean_cost:,.2f}")]),
    ]

    redeem_due = [w for w in settled if w["winner"] and not w["redeemed"] and (w.get("payoutUsd") or 0) > 0]
    redeem_payout = round(sum(w["payoutUsd"] for w in redeem_due), 2)

    pid = loop_pid
    st = current_state
    age_ms = None
    if st and st.get("updatedAtMs"):
        age_ms = max(0, int(time.time() * 1000) - int(st["updatedAtMs"]))
    health = {
        "loopRunning": pid is not None,
        "pid": pid,
        "killSwitch": bool(kill_switch),
        "stateSlug": (st or {}).get("slug"),
        "stateFills": len((st or {}).get("fills") or []),
        "snapshotAgeSec": round(age_ms / 1000, 1) if age_ms is not None else None,
        "windowEndsInSec": max(0, round((int((st or {}).get("endMs") or 0) - time.time() * 1000) / 1000)) if st else None,
    }

    notes: list[dict] = []

    def note(tone: str, title: str, body: str) -> None:
        notes.append({"tone": tone, "title": title, "body": body})

    if not health["loopRunning"]:
        note("warning", "Loop is stopped",
             "No new windows are being taken. Start it from the header; the paper loop runs one window at a time.")
    if health["killSwitch"]:
        note("danger", "Kill switch engaged",
             "Entries stay paused between windows while data/kill exists. Resume from Live, or `rm data/kill`.")
    age_s = health["snapshotAgeSec"]
    if health["loopRunning"] and age_s is not None and age_s > 120:
        note("warning", f"Heartbeat is {age_s:.0f}s old",
             "The window may have died mid-fill. Restart the loop — do not delete state.json while it owns the window (assert_single_window).")
    if pending:
        note("info", f"{len(pending)} window{'s' if len(pending) != 1 else ''} still settling",
             "Payout is not final until the market resolves; these are excluded from net, cost and the health rows.")
    if redeem_due:
        note("warning", f"{len(redeem_due)} winning window{'s' if len(redeem_due) != 1 else ''} unredeemed (${redeem_payout:,.2f})",
             "Hold-to-redeem is the strategy: paper only books the win when claimed. Redeem via the Dashboard or run python bot/redeem.py.")
    if zero_fills:
        note("danger", f"{zero_fills} fills at $0.00",
             "No capital moved, but they still count toward every fill average. Fix the late dust path before trusting the queue audit.")
    if a_maker and a_phantom:
        phantom_rate = a_phantom / a_maker
        if phantom_rate > 0.25:
            note("warning", f"{phantom_rate * 100:.0f}% of audited maker fills were phantom",
                 f"The tape shows no selling behind the queue at {a_phantom} of {a_maker} audited limits, so the paper tape overstates what a real bid would have filled.")
    if settled and both < len(settled):
        note("warning", f"{len(settled) - both} single-sided window{'s' if len(settled) - both != 1 else ''}",
             "A missed hedge leg breaks the straddle: the first leg filled but the other outcome was never bought.")
    if fills and max(up_fills, down_fills) / fills > 0.75:
        lead = "Up" if up_fills >= down_fills else "Down"
        share = max(up_fills, down_fills) / fills
        note("warning", f"Fill mix is {share * 100:.0f}% {lead}",
             f"{up_fills} Up vs {down_fills} Down fills — the lean/alternation is not flipping sides the way the strategy expects.")
    if settled:
        roi = net / cost if cost else 0.0
        note("success" if net > 0 else "danger",
             f"Paper net {'+' if net >= 0 else '−'}${abs(net):,.2f} on ${cost:,.2f} staked",
             f"{profitable}/{len(settled)} windows profitable ({roi * 100:+.1f}% on cost). Winners pay $1/share at resolution; there are no sells.")

    severity = {"danger": 0, "warning": 1, "info": 2, "success": 3}
    notes.sort(key=lambda n: severity.get(n["tone"], 9))

    wins = [n for n in nets if n > 0]
    losses = [-n for n in nets if n < 0]
    wins_count = len(wins)
    losses_count = len(losses)
    gross_profit = round(sum(wins), 2)
    gross_loss = round(sum(losses), 2)
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
    avg_win = round(gross_profit / wins_count, 2) if wins_count > 0 else 0.0
    avg_loss = round(gross_loss / losses_count, 2) if losses_count > 0 else 0.0
    payoff_ratio = round(avg_win / avg_loss, 2) if avg_loss > 0 else (99.0 if avg_win > 0 else 0.0)
    win_rate = round(profitable / len(settled), 4) if settled else 0.0
    loss_rate = round(losses_count / len(settled), 4) if settled else 0.0
    expectancy_usd = round(net / len(settled), 2) if settled else 0.0
    expectancy_ratio = round((win_rate * payoff_ratio) - loss_rate, 2) if settled else 0.0
    be_win_rate = round(((wins_count + losses_count) / len(settled)) / (1.0 + payoff_ratio), 4) if (settled and wins_count > 0 and payoff_ratio > 0) else None
    edge_pct = round((win_rate - be_win_rate) * 100, 2) if (settled and be_win_rate is not None) else None

    annual_factor = math.sqrt(288 * 365)
    if len(nets) >= 2:
        mean_net = statistics.mean(nets)
        stdev_net = statistics.stdev(nets)
        sharpe_ratio = round((mean_net / stdev_net) * annual_factor, 2) if stdev_net > 0.0001 else 0.0
        downside = [min(0.0, n) for n in nets]
        downside_variance = sum(d**2 for d in downside) / len(nets)
        downside_std = math.sqrt(downside_variance)
        sortino_ratio = round((mean_net / downside_std) * annual_factor, 2) if downside_std > 0.0001 else (99.0 if mean_net > 0 else 0.0)
    else:
        sharpe_ratio = 0.0
        sortino_ratio = 0.0

    sorted_settled = sorted(settled, key=lambda w: w.get("startMs", 0))
    equity = bankroll
    peak = equity
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    for w in sorted_settled:
        n = w.get("netUsd") or 0.0
        equity += n
        if equity > peak:
            peak = equity
        dd = peak - equity
        dd_pct = dd / peak if peak > 0 else 0.0
        if dd > max_dd_usd:
            max_dd_usd = dd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
    current_dd_usd = round(max(0.0, peak - equity), 2)
    current_dd_pct = round(current_dd_usd / peak, 4) if peak > 0 else 0.0
    max_dd_usd = round(max_dd_usd, 2)
    max_dd_pct = round(max_dd_pct, 4)

    current_streak = 0
    max_win_streak = 0
    max_loss_streak = 0
    streak = 0
    for w in sorted_settled:
        n = w.get("netUsd") or 0.0
        if n > 0:
            streak = streak + 1 if streak > 0 else 1
            if streak > max_win_streak:
                max_win_streak = streak
        elif n < 0:
            streak = streak - 1 if streak < 0 else -1
            if abs(streak) > max_loss_streak:
                max_loss_streak = abs(streak)
        else:
            streak = 0
    current_streak = streak

    up_windows = [w for w in settled if w.get("winner") == "Up"]
    down_windows = [w for w in settled if w.get("winner") == "Down"]
    up_wins = sum(1 for w in up_windows if (w.get("netUsd") or 0) > 0)
    down_wins = sum(1 for w in down_windows if (w.get("netUsd") or 0) > 0)
    up_net = round(sum(w.get("netUsd") or 0.0 for w in up_windows), 2)
    down_net = round(sum(w.get("netUsd") or 0.0 for w in down_windows), 2)
    up_win_rate = round(up_wins / len(up_windows), 4) if up_windows else 0.0
    down_win_rate = round(down_wins / len(down_windows), 4) if down_windows else 0.0

    # Attainable view: the same windows judged by what a real resting bid could
    # have got behind the queue that was actually there. Windows the auditor
    # could not read (no prints) carry no fidelity and drop out, so this net
    # covers the audited windows while the headline covers every settled one.
    a_cost = round(sum(_num(f.get("attainableCostUsd")) for f in audited), 2)
    a_payout = round(sum(_num(f.get("attainablePayoutUsd")) for f in audited), 2)
    a_assumed = round(sum(_num(f.get("assumedShares")) for f in audited), 2)
    a_kept = round(sum(_num(f.get("attainableShares")) for f in audited), 2)
    attainable = {
        "windows": len(audited),
        "makerFills": a_maker,
        "attainableFills": a_attainable,
        "phantomFills": a_phantom,
        "queueKnownFills": sum(int(f.get("queueKnown") or 0) for f in audited),
        "costUsd": a_cost,
        "payoutUsd": a_payout,
        "netUsd": round(a_payout - a_cost, 2),
        "fillRate": round(a_attainable / a_maker, 4) if a_maker else 0.0,
        "shareRate": round(a_kept / a_assumed, 4) if a_assumed else 0.0,
    }

    strat = cfg.get("strategy", {})
    strat_id = strat.get("id", C.STRATEGY_ID)
    strat_sym = strat.get("symbol", C.STRATEGY_SYMBOL)
    strat_name = strat.get("name", C.STRATEGY_NAME)
    setup_info = C.STRATEGY_SETUPS.get(strat_id, {})
    strat_sig = setup_info.get("signature", C.STRATEGY_SIGNATURE)

    return {
        "strategy": {
            "id": strat_id,
            "symbol": strat_sym,
            "name": strat_name,
            "signature": strat_sig,
            "makerShareTarget": C.MAKER_SHARE_TARGET,
            "pairCostTarget": entry_cfg.get("targetPairCost", C.PAIR_COST_TARGET),
            "priceFloor": entry_cfg.get("minFillPrice", C.PRICE_FLOOR),
            "priceCeiling": entry_cfg.get("maxFillPrice", C.PRICE_CEILING),
            "cutoffSec": entry_cfg.get("stopBeforeCloseSec", C.HARD_CUTOFF_SBC),
        },
        "summary": {
            "bankrollUsd": bankroll,
            "settled": len(settled), "pending": len(pending), "fills": fills,
            "costUsd": cost, "payoutUsd": payout, "netUsd": net,
            "feesUsd": round(sum(w["feesUsd"] for w in settled), 4),
            "makerFeeBaseUsd": round(sum(w["makerFeeBaseUsd"] for w in settled), 4),
            "roi": round(net / cost, 4) if cost else 0.0,
            "profitable": profitable,
            "hitRate": round(profitable / len(settled), 4) if settled else 0.0,
            "bothSides": both, "bothSidesRate": both_rate,
            "medianFills": median_fills, "meanFills": mean_fills,
            "medianCostUsd": median_cost, "meanCostUsd": mean_cost,
            "bestUsd": round(max(nets), 2) if nets else 0.0,
            "worstUsd": round(min(nets), 2) if nets else 0.0,
            "zeroPriceFills": zero_fills,
            "upFills": up_fills, "downFills": down_fills,
            "upWins": up_wins,
            "downWins": down_wins,
            "winRate": win_rate,
            "lossRate": loss_rate,
            "winsCount": wins_count,
            "lossesCount": losses_count,
            "grossProfitUsd": gross_profit,
            "grossLossUsd": gross_loss,
            "profitFactor": profit_factor,
            "avgWinUsd": avg_win,
            "avgLossUsd": avg_loss,
            "payoffRatio": payoff_ratio,
            "expectancyUsd": expectancy_usd,
            "expectancyRatio": expectancy_ratio,
            "breakEvenWinRate": be_win_rate,
            "edgePct": edge_pct,
            "sharpeRatio": sharpe_ratio,
            "sortinoRatio": sortino_ratio,
            "maxDrawdownUsd": max_dd_usd,
            "maxDrawdownPct": max_dd_pct,
            "currentDrawdownUsd": current_dd_usd,
            "currentDrawdownPct": current_dd_pct,
            "currentStreak": current_streak,
            "maxWinStreak": max_win_streak,
            "maxLossStreak": max_loss_streak,
            "upWindows": len(up_windows),
            "downWindows": len(down_windows),
            "upNetUsd": up_net,
            "downNetUsd": down_net,
            "upWinRate": up_win_rate,
            "downWinRate": down_win_rate,
            "attainable": attainable,
        },
        "cells": cells,
        "mShape": {"live": live_shape, "liveShare": live_share,
                   "attainable": m_attainable, "phantom": m_phantom},
        "redeem": {"count": len(redeem_due), "payoutUsd": redeem_payout},
        "health": health,
        "notes": notes,
        "windows": rows,
        "generatedAt": utc_now,
    }
