"""Wallet mechanics from any Polymarket activity ledger CSV.

One pass over the ledger answers four questions, printed as plain-text sections:

  1. FIRST LEG  does the first leg's price/time predict how the market ends?
  2. MECHANICS  why the first leg lands far from 0.50, whether the second leg is
                priced off a target pair cost or the live book, and whether
                tickets are fixed-share or fixed-notional
  3. LEVELS     how much goes on each price level, and is the clip one size?
  4. SEQUENCE   one side then the other, or both ladders at once?

Usage: python analyze_mechanics.py <ledger.csv>   (or set TRADES_CSV)
The same Markdown report is saved as `<csv-stem>_mechanics.md` under
`docs/leaderboard-traders/ledgers/<account>/analysis/` when the CSV sits under
`data/leaderboard/<account>/raw/`,
otherwise next to the CSV.

Fills only: the ledger shows what it filled, never what it quoted. P&L is the
cash the account actually moved: sells, redeems and merges in, buys out, with the
fee already inside USD_Amount. Market length comes from the slug
(...-5m-<epoch>, ...-15m-<epoch>, ...-1h-<epoch>), so every market length is
handled and markets without a parsable clock are counted, not guessed.
Rebates are excluded.

A market still holding shares when the file ends is skipped, so a window that
stops mid-market books nothing for it. Shares left in a market that has closed
are valued only when the outcome is known: a REDEEM row names the winner, which
pays $1/share, and the other side pays $0. Without a REDEEM the value is
unknown, so that market's P&L is reported as a $0..$1-per-share range and it is
left out of the rate columns. Every rate carries a Wilson 95% CI and its sample
size; every table states what it excluded.

The winning outcome comes from the REDEEM rows (the winning token redeems at
$1/share, the loser at $0). An account that sells out before resolution leaves no
REDEEM row, so those markets count toward P&L but not toward "first side won".

Sections 2-4 describe the buy ladder only: sells are priced into the P&L, not
into the level or sequence tables.
"""
from .measures import *
from .report import *
from scripts.leaderboard_traders.report_kit import analysis_target


import csv
import io
import os
import pathlib
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
csv.field_size_limit(10**9)
PATH = (
    next((a for a in sys.argv[1:] if a.lower().endswith(".csv")), None)
    or os.environ.get("TRADES_CSV")
)
if not PATH:
    sys.exit("usage: python -m scripts.leaderboard_traders.mechanics <ledger.csv>  (or set TRADES_CSV)")
REQUIRED_COLUMNS = (
    "Timestamp_UTC", "Type", "Market_Slug", "Outcome",
    "Side", "Price", "Shares", "USD_Amount",
)
if not os.path.isfile(PATH):
    sys.exit(
        f"Ledger not found: {PATH}\n"
        "Pass a ledger .csv path, set TRADES_CSV, or pull one first with "
        "save-trades-to-csv.py."
    )
with open(PATH, encoding="utf-8", newline="") as _header_file:
    _header = next(csv.reader(_header_file), [])
_missing = [c for c in REQUIRED_COLUMNS if c not in _header]
if _missing:
    sys.exit(f"{PATH} is not a ledger CSV; missing column(s): {', '.join(_missing)}")
def _report_failure(exc_type, exc, traceback):
    """One-line failure instead of a traceback for a bad ledger."""
    print(f"Cannot analyse {PATH}: {exc}", file=sys.stderr)
sys.excepthook = _report_failure
ORDER = ["<=0.25", "0.25-0.45", "0.45-0.55", "0.55-0.75", ">0.75"]
sys.stdout = _Indent(sys.stdout)
_STDOUT = sys.stdout
_REPORT = io.StringIO()
sys.stdout = Tee(_STDOUT, _REPORT)
mk = {}                                        # slug -> per-market state
levels = defaultdict(lambda: [0.0, 0.0, 0])    # (slug, px2) -> [shares, $, prints]
tickets = defaultdict(list)                    # price bucket -> [(shares, $, px)]
price_mod = Counter()                          # cents-grid check
win = {}                                       # slug -> winning outcome, from REDEEM
runs = []                                      # same-side run lengths
alts = []                                      # side-switch share per market
file_end = 0.0                                 # latest trade instant in the file
types = Counter()                              # row count per Type
bad_rows = 0                                   # rows with an unreadable number or timestamp
def m(slug):
    d = mk.get(slug)
    if d is None:
        d = mk[slug] = {
            "first": [None, None],   # (epoch, px, shares) of the first BUY per side
            "first_all": None,       # (epoch, px, outcome) of the first BUY overall
            "buy_sh": [0.0, 0.0], "buy_usd": [0.0, 0.0],
            "sell_sh": [0.0, 0.0], "sell_usd": [0.0, 0.0],
            "red_sh": [0.0, 0.0], "red_usd": [0.0, 0.0],
            "merge_sh": 0.0, "merge_usd": 0.0,
            "n": 0, "fee": 0.0,
            "fills": [],             # epoch*2 + side, for the sequence section
            "t_first": [None, None], "t_last": [None, None],
        }
    return d
for r in csv.DictReader(open(PATH, encoding="utf-8", newline="")):
    slug = r["Market_Slug"]
    typ = r["Type"]
    types[typ or "(blank)"] += 1
    if typ in ("REDEEM", "MERGE"):
        if not slug:
            continue
        try:
            usd = float(r["USD_Amount"] or 0)
            sh = float(r["Shares"] or 0)
        except ValueError:
            bad_rows += 1
            continue
        d = m(slug)
        if typ == "REDEEM":
            i = 0 if r["Outcome"] == "Up" else 1
            d["red_sh"][i] += sh
            d["red_usd"][i] += usd
            if usd > 0:
                win[slug] = r["Outcome"]
        else:                      # MERGE: Shares is a pair count, paid $1 each
            d["merge_sh"] += sh
            d["merge_usd"] += usd
        continue
    if typ != "TRADE" or not slug or r["Side"] not in ("BUY", "SELL"):
        continue
    try:
        px = float(r["Price"])
        sh = float(r["Shares"])
        usd = float(r["USD_Amount"]) if r["USD_Amount"] else px * sh
        t = secs(r["Timestamp_UTC"])
    except ValueError:
        bad_rows += 1
        continue
    i = 0 if r["Outcome"] == "Up" else 1
    file_end = max(file_end, t)
    d = m(slug)
    d["fee"] += abs(usd - px * sh)  # recorded fee: inside USD on a buy, netted on a sell
    if r["Side"] == "SELL":
        d["sell_sh"][i] += sh
        d["sell_usd"][i] += usd
        continue
    d["buy_sh"][i] += sh
    d["buy_usd"][i] += usd
    d["n"] += 1
    if d["first"][i] is None or t < d["first"][i][0]:
        d["first"][i] = (t, px, sh)
    if d["first_all"] is None or t < d["first_all"][0]:
        d["first_all"] = (t, px, r["Outcome"])
    if d["t_first"][i] is None or t < d["t_first"][i]:
        d["t_first"][i] = t
    if d["t_last"][i] is None or t > d["t_last"][i]:
        d["t_last"][i] = t

    # Whole-second epochs; side breaks timestamp ties the same way a text sort does.
    d["fills"].append(int(t) * 2 + (0 if r["Outcome"] == "Down" else 1))
    b = min(19, int(px * 20))
    tickets[b].append((sh, usd, px))
    price_mod[round((px % 0.05) * 100)] += 1
    lv = levels[(slug, round(px, 2))]
    lv[0] += sh
    lv[1] += usd
    lv[2] += 1
for d in mk.values():
    if d["n"] < 4:
        continue
    sides = [f & 1 for f in sorted(d["fills"])]
    run = 1
    switches = 0
    for k in range(1, len(sides)):
        if sides[k] == sides[k - 1]:
            run += 1
        else:
            runs.append(run)
            run = 1
            switches += 1
    runs.append(run)
    alts.append(switches / (len(sides) - 1))
with_fills = sum(1 for d in mk.values() if d["n"])
print("# Wallet mechanics - computed sections")
print(f"Ledger: {PATH}")
print(f"Markets with fills: {with_fills:,} | with a REDEEM: {len(win):,}")
print("Rows: %s" % ", ".join(f"{k} {v:,}" for k, v in types.most_common()))
with_clock = sum(1 for slug in mk if market_clock(slug)[0] is not None)
print(f"Slugs with a market clock: {with_clock:,} of {len(mk):,}")
rows = []
skipped = Counter()
for slug, d in mk.items():
    if d["first_all"] is None:
        continue
    slot, duration = market_clock(slug)
    if slot is None:
        skipped["no market clock in the slug"] += 1
        continue
    left = held(d)
    if (left[0] > 1e-6 or left[1] > 1e-6) and slot + duration > file_end:
        skipped["still open when the file ends"] += 1
        continue
    t, px, side = d["first_all"]
    off = t - slot
    if not -60 <= off <= duration + 60:
        skipped["first fill outside the market window"] += 1
        continue
    cash_in, cost, fee = money(d)
    w = win.get(slug)
    # Shares left over are only priced when the outcome is known; otherwise they
    # are a $0..$1-per-share range and the market stays out of the rate columns.
    value_low = value_high = 0.0
    if left[0] > 1e-6 or left[1] > 1e-6:
        if w:
            value_low = value_high = max(left[0] if w == "Up" else left[1], 0.0)
        else:
            value_high = max(left[0], left[1], 0.0)
    traded = cash_in - cost
    rows.append({"px": px, "off": off, "cost": cost, "fee": fee,
                 "net_low": traded + value_low, "net_high": traded + value_high,
                 "gross_low": traded + value_low + fee, "win": w,
                 "known": value_low == value_high, "tick": side})
known_rows = [r for r in rows if r["known"]]
unresolved = [r for r in rows if not r["known"]]
_section("1. FIRST LEG: does price/time predict the outcome?")
print("markets analysed:", len(rows), " total cost $%.0f" % sum(r["cost"] for r in rows))
print("resolved exactly: %d  unresolved: %d" % (len(known_rows), len(unresolved)))
print("gross pnl $%.0f  fees $%.0f  net $%.0f" % (
    sum(r["gross_low"] for r in known_rows), sum(r["fee"] for r in known_rows),
    sum(r["net_low"] for r in known_rows)))
if unresolved:
    print("unresolved pnl range $%.0f .. $%.0f  (not in net above)" % (
        sum(r["net_low"] for r in unresolved), sum(r["net_high"] for r in unresolved)))
print("outcome known from a REDEEM:", sum(1 for r in rows if r["win"]))
if skipped or bad_rows:
    print("excluded: %d still open, %d without a market clock, %d first fill "
          "outside the window, %d unreadable row(s)" % (
              skipped["still open when the file ends"],
              skipped["no market clock in the slug"],
              skipped["first fill outside the market window"], bad_rows))
price_b = [("<=0.25", lambda r: r["px"] <= 0.25), ("0.25-0.45", lambda r: 0.25 < r["px"] <= 0.45),
           ("0.45-0.55", lambda r: 0.45 < r["px"] < 0.55), ("0.55-0.75", lambda r: 0.55 <= r["px"] <= 0.75),
           (">0.75", lambda r: r["px"] > 0.75)]
off_b = [("0-15s", lambda r: r["off"] <= 15), ("16-30s", lambda r: 15 < r["off"] <= 30),
         ("31-60s", lambda r: 30 < r["off"] <= 60), ("61-120s", lambda r: 60 < r["off"] <= 120),
         (">120s", lambda r: r["off"] > 120)]
print("\nBY FIRST-LEG PRICE")
show_group([("all", rows)] + [(name, [r for r in rows if fn(r)]) for name, fn in price_b])
print("\nBY FIRST-LEG TIME (seconds after open)")
show_group([(name, [r for r in rows if fn(r)]) for name, fn in off_b])
print("\nTHE TIGHT CASE: first leg >0.75, by time")
show_group([(name, [r for r in rows if r["px"] > 0.75 and fn(r)]) for name, fn in off_b])
print("\nTHE LATE CASE: first leg after 60s, by price")
show_group([(name, [r for r in rows if r["off"] > 60 and fn(r)]) for name, fn in price_b])
firsts = []
for slug, d in mk.items():
    a, b = d["first"]
    if a is None or b is None:
        continue
    if a[0] <= b[0]:
        p1, p2, i = a[1], b[1], 0
    else:
        p1, p2, i = b[1], a[1], 1
    firsts.append({"p1": p1, "p2": p2, "lag": abs(a[0] - b[0]), "side": i,
                   "first_ts": min(a[0], b[0]), "win": win.get(slug)})
_section("2. MECHANICS: first-leg decay, second-leg pricing, sizing")
known_out = sum(1 for r in firsts if r["win"])
print("markets with both sides bought:", len(firsts),
      " (outcome known for %d, unknown for %d)" % (known_out, len(firsts) - known_out))
by = defaultdict(list)
for r in firsts:
    by[bucket(r["p1"])].append(r)
print("\n1) WHY THE FIRST LEG LANDS FAR FROM 0.50")
trows = []
for k in ORDER:
    sel = by[k]
    judged = [r for r in sel if r["win"]]
    won = sum(1 for r in judged if (r["win"] == "Up") == (r["side"] == 0))
    p1 = med([r["p1"] for r in sel])
    p2 = med([r["p2"] for r in sel])
    total = med([r["p1"] + r["p2"] for r in sel])
    trows.append((k, str(len(sel)), str(len(judged)), f"{p1:.3f}", f"{p2:.3f}",
                  f"{total:.3f}", rate(won, len(judged))))
md_table(("bucket", "n", "known", "p1", "p2", "sum", "first side won"), trows)
print("\n2) THE SECOND LEG: target pair cost, or the live book?")
trows = []
for k in ORDER:
    sel = by[k]
    sums = sorted(r["p1"] + r["p2"] for r in sel)
    q = lambda x: sums[min(len(sums) - 1, int(x * len(sums)))] if sums else float("nan")
    lag = med([r["lag"] for r in sel])
    trows.append((k, str(len(sel)), f"{lag:.0f}", f"{med(sums):.3f}",
                  f"{q(0.25):.3f}", f"{q(0.75):.3f}"))
md_table(("p1", "n", "lag(s)", "p1+p2", "p25", "p75"), trows)
print("\n   pair sum by how long the second leg waited")
trows = []
for name, lo, hi in (("0-1s", 0, 1), ("2-5s", 2, 5), ("6-15s", 6, 15), ("16-30s", 16, 30),
                     ("31-60s", 31, 60), ("61-120s", 61, 120), (">120s", 121, 10**9)):
    sel = [r for r in firsts if lo <= r["lag"] <= hi]
    sums = sorted(r["p1"] + r["p2"] for r in sel)
    q = lambda x: sums[min(len(sums) - 1, int(x * len(sums)))] if sums else float("nan")
    trows.append((name, str(len(sel)), f"{med(sums):.3f}", f"{q(0.25):.3f}", f"{q(0.75):.3f}"))
md_table(("lag", "n", "p1+p2", "p25", "p75"), trows)
print("\n   spread of the pair sum")
common = Counter(round((r["p1"] + r["p2"]) * 100) for r in firsts)
print("   most common p1+p2 in cents:", common.most_common(5))
if firsts:
    top_cent, top_n = common.most_common(1)[0]
    sums = sorted(r["p1"] + r["p2"] for r in firsts)
    q = lambda x: sums[min(len(sums) - 1, int(x * len(sums)))]
    print("   share at the single most common cent: %.1f%% (%.2f)"
          % (100.0 * top_n / len(firsts), top_cent / 100))
    print("   IQR of p1+p2: %.3f  sd: %.3f"
          % (q(0.75) - q(0.25),
             st.pstdev(sums) if len(sums) > 1 else 0.0))
print("\n3) SIZING: fixed shares or fixed notional?")
trows = []
omitted = 0
for b in range(20):
    t = tickets[b]
    if len(t) < 200:
        omitted += len(t)
        continue
    sh = sorted(x[0] for x in t)
    usd = sorted(x[1] for x in t)
    px = sorted(x[2] for x in t)
    q = lambda v, x: v[min(len(v) - 1, int(x * len(v)))]
    trows.append((f"{b * 0.05:.2f}-{(b + 1) * 0.05:.2f}", str(len(t)),
                  f"{q(sh, .5):.1f}", f"{q(sh, .25):.1f}", f"{q(sh, .75):.1f}",
                  f"{q(usd, .5):.2f}", f"{q(px, .5):.3f}"))
md_table(("price", "fills", "medSh", "p25Sh", "p75Sh", "med$", "medPx"), trows)
if omitted:
    print("   (%d fills in price buckets with <200 fills not shown)" % omitted)
counts = [d["n"] for d in mk.values()]
print("\n   fills per market: median %d  mean %.1f" % (
    int(med(counts)) if counts else 0, st.mean(counts) if counts else 0.0))
print("   cents-grid check (price mod 0.05, in cents):", price_mod.most_common(6))
_section("3. LEVELS: clip size per (market, price) level")
LINE_HDR = ("scope", "n", "min", "p10", "p25", "p50", "p75", "p90", "max")
print("\nLEVEL (one price inside one market = one resting order)")
md_table(LINE_HDR, [line("shares per level", [lv[0] for lv in levels.values()]),
                    line("$ per level", [lv[1] for lv in levels.values()])])
print()
print("MARKET")
levels_per_market = defaultdict(int)
for (s, p) in levels:
    levels_per_market[s] += 1
md_table(LINE_HDR, [
    line("shares per market", [d["buy_sh"][0] + d["buy_sh"][1] for d in mk.values()]),
    line("$ per market", [d["buy_usd"][0] + d["buy_usd"][1] for d in mk.values()]),
    line("levels per market", list(levels_per_market.values())),
    line("total fills per market", [d["n"] for d in mk.values()]),
])
level_n = [lv[2] for lv in levels.values()]
multi = [n for n in level_n if n > 1]
if level_n:
    print("\nlevels hit by more than one print: %d of %d (%.1f%%)"
          % (len(multi), len(level_n), 100.0 * len(multi) / len(level_n)))
    print("prints per level: mean %.1f  p90 %d  max %d"
          % (st.mean(level_n), sorted(level_n)[int(.9 * len(level_n))], max(level_n)))
print("\nmedian level size by price band")
byprice = defaultdict(list)
for (s, p), lv in levels.items():
    byprice[min(19, int(p * 20))].append(lv[0])
trows = []
omitted = 0
for b in range(0, 20, 2):
    xs = byprice[b] + byprice.get(b + 1, [])
    if len(xs) <= 200:
        omitted += len(xs)
        continue
    trows.append((f"{b * 0.05:.2f}-{(b + 2) * 0.05:.2f}", str(len(xs)),
                  f"{st.median(xs):.1f}", f"{st.mean(xs):.1f}"))
md_table(("price", "n", "med sh", "mean sh"), trows)
if omitted:
    print("  (%d levels in price bands with <=200 levels not shown)" % omitted)
_section("4. SEQUENCE: one side then the other, or both ladders at once?")
n_markets = sum(1 for d in mk.values() if d["n"] >= 4)
small = sum(1 for d in mk.values() if 0 < d["n"] < 4)
overlap = 0
two_sided = 0
gaps = []
for d in mk.values():
    if d["n"] < 4:
        continue
    tu, td = d["t_first"]
    if tu is not None and td is not None:
        two_sided += 1
        if max(tu, td) <= min(d["t_last"][0], d["t_last"][1]):
            overlap += 1
        gaps.append(abs(tu - td))
print("markets with >=4 fills:", n_markets)
print("markets with 1-3 fills not analysed:", small)
print("two-sided among the analysed:", two_sided)
print("mean same-side run length: %.2f  (1.0 = perfect alternation, big = one side at a time)"
      % (st.mean(runs) if runs else 0.0))
print("median share of consecutive pairs that switch side: %.0f%%" % (100 * st.median(alts) if alts else 0.0))
print("both sides bought inside the same time span: %.1f%%"
      % (100.0 * overlap / two_sided if two_sided else 0.0))
gaps.sort()
if gaps:
    q = lambda x: gaps[min(len(gaps) - 1, int(x * len(gaps)))]
    print("\ngap between the two sides' FIRST fills (seconds):"
          "  p10 %.0f  p25 %.0f  p50 %.0f  p75 %.0f  p90 %.0f"
          % (q(.10), q(.25), q(.5), q(.75), q(.90)))
sys.stdout = _STDOUT
target = analysis_target(PATH, "_mechanics.md")
tmp = target.with_name(target.name + ".tmp")
try:
    tmp.write_text(_REPORT.getvalue(), encoding="utf-8")
    os.replace(tmp, target)
except BaseException:
    tmp.unlink(missing_ok=True)
    raise
print(f"\nWrote {target}")
