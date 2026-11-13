"""How the wallet actually trades: first-leg decay, second-leg pricing, ticket size.

Per market we keep the first BUY on each side (when, at what price, how big) plus
totals, then answer:
  * why the first leg lands at 0.80 or 0.06 instead of 0.50
  * whether the second leg is priced off a target pair cost or off the live book
  * whether tickets are fixed-share or fixed-notional
Fills only: the ledger shows what it filled, never what it quoted.
"""
import csv
import json
import statistics as st
from collections import Counter, defaultdict
from datetime import datetime, timezone

LEDGER = "scratch/trades_full_history.csv"
DUMPS = ("scratch/market_placement.jsonl", "scratch/market_placement2.jsonl")

win = {}
for p in DUMPS:
    for line in open(p, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if r.get("win"):
                win[r["slug"]] = r["win"]

mk = {}
tickets = defaultdict(list)      # price bucket -> [(shares, usd)]
price_mod = Counter()            # cents grid check
n_fill = Counter()


def m(slug):
    d = mk.get(slug)
    if d is None:
        d = mk[slug] = {"f": [None, None], "sh": [0.0, 0.0], "c": [0.0, 0.0], "n": 0}
    return d


for r in csv.DictReader(open(LEDGER, encoding="utf-8", newline="")):
    if r["Type"] != "TRADE" or r["Side"] != "BUY":
        continue
    slug = r["Market_Slug"]
    if not slug:
        continue
    try:
        px = float(r["Price"])
        sh = float(r["Shares"])
        usd = float(r["USD_Amount"]) if r["USD_Amount"] else px * sh
    except ValueError:
        continue
    i = 0 if r["Outcome"] == "Up" else 1
    d = m(slug)
    d["sh"][i] += sh
    d["c"][i] += usd
    d["n"] += 1
    t = int(datetime.fromisoformat(r["Timestamp_UTC"]).replace(tzinfo=timezone.utc).timestamp())
    if d["f"][i] is None or t < d["f"][i][0]:
        d["f"][i] = (t, px, sh)
    b = min(19, int(px * 20))
    tickets[b].append((sh, usd, px))
    price_mod[round((px % 0.05) * 100)] += 1
    n_fill[b] += 1

# ---------------------------------------------------------------- first leg
firsts = []
for slug, d in mk.items():
    a, b = d["f"]
    if a is None or b is None:
        continue
    if a[0] <= b[0]:
        p1, p2, i = a[1], b[1], 0
    else:
        p1, p2, i = b[1], a[1], 1
    firsts.append({"p1": p1, "p2": p2, "lag": abs(a[0] - b[0]), "side": i,
                   "first_ts": min(a[0], b[0]), "win": win.get(slug),
                   "cost": d["c"][0] + d["c"][1]})

print("markets with both sides bought:", len(firsts))


def med(v):
    return st.median(v) if v else float("nan")


def bucket(p):
    for hi, name in ((0.25, "<=0.25"), (0.45, "0.25-0.45"), (0.55, "0.45-0.55"),
                     (0.75, "0.55-0.75"), (1.01, ">0.75")):
        if p <= hi:
            return name
    return ">0.75"


ORDER = ["<=0.25", "0.25-0.45", "0.45-0.55", "0.55-0.75", ">0.75"]
by = defaultdict(list)
for r in firsts:
    by[bucket(r["p1"])].append(r)

print("\n1) WHY THE FIRST LEG LANDS FAR FROM 0.50")
print("%-10s %6s %8s %8s %9s %10s" % ("p1", "n", "p1", "p2", "sum", "first side won"))
for k in ORDER:
    sel = by[k]
    won = [r for r in sel if r["win"] and ((r["win"] == "Up") == (r["side"] == 0))]
    print("%-10s %6d %8.3f %8.3f %9.3f %9.1f%%" % (
        k, len(sel), med([r["p1"] for r in sel]), med([r["p2"] for r in sel]),
        med([r["p1"] + r["p2"] for r in sel]), 100.0 * len(won) / max(1, len(sel))))

print("\n2) THE SECOND LEG: target pair cost, or the live book?")
print("%-10s %6s %8s %9s %9s %9s" % ("p1", "n", "lag(s)", "p1+p2", "p25", "p75"))
for k in ORDER:
    sel = by[k]
    sums = sorted(r["p1"] + r["p2"] for r in sel)
    q = lambda x: sums[min(len(sums) - 1, int(x * len(sums)))]
    print("%-10s %6d %8.0f %9.3f %9.3f %9.3f" % (
        k, len(sel), med([r["lag"] for r in sel]), med(sums), q(0.25), q(0.75)))

print("\n   pair sum by how long the second leg waited")
print("%-10s %6s %9s %9s %9s" % ("lag", "n", "p1+p2", "p25", "p75"))
for name, lo, hi in (("0-1s", 0, 1), ("2-5s", 2, 5), ("6-15s", 6, 15), ("16-30s", 16, 30),
                     ("31-60s", 31, 60), ("61-120s", 61, 120), (">120s", 121, 10**9)):
    sel = [r for r in firsts if lo <= r["lag"] <= hi]
    sums = sorted(r["p1"] + r["p2"] for r in sel)
    q = lambda x: sums[min(len(sums) - 1, int(x * len(sums)))]
    print("%-10s %6d %9.3f %9.3f %9.3f" % (name, len(sel), med(sums), q(0.25), q(0.75)))

print("\n   spread of the pair sum (a target cost would be a spike)")
d = Counter(round((r["p1"] + r["p2"]) * 100) for r in firsts)
top = d.most_common(5)
print("   most common p1+p2 in cents:", top)
print("   sd of p1+p2: %.3f" % st.pstdev([r["p1"] + r["p2"] for r in firsts]))

print("\n3) SIZING: fixed shares or fixed notional?")
print("%-10s %8s %8s %8s %8s %8s %8s" % ("price", "fills", "medSh", "p25Sh", "p75Sh", "med$", "medPx"))
for b in range(20):
    t = tickets[b]
    if len(t) < 200:
        continue
    sh = sorted(x[0] for x in t)
    usd = sorted(x[1] for x in t)
    q = lambda v, x: v[min(len(v) - 1, int(x * len(v)))]
    print("%4.2f-%4.2f %8d %8.1f %8.1f %8.1f %8.2f %8.3f" % (
        b * 0.05, (b + 1) * 0.05, len(t), q(sh, .5), q(sh, .25), q(sh, .75), q(usd, .5), q(sorted(x[2] for x in t), .5)))

print("\n   fills per market: median %d  mean %.1f" % (
    int(med([d["n"] for d in mk.values()])), st.mean([d["n"] for d in mk.values()])))
print("   cents-grid check (price mod 0.05, in cents):", price_mod.most_common(6))
