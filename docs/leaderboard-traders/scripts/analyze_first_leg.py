"""Does the price/time of the FIRST leg predict how the market ends?

One pass over the ledger. Per market we keep the first BUY print (when, at what
price) and the full cost/shares per side; the winner comes from the per-market
dump. P&L is gross: winning shares x $1 minus what was paid.
"""
import csv
import json
import statistics as st

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


def m(slug):
    d = mk.get(slug)
    if d is None:
        d = mk[slug] = {"t": None, "px": None, "side": None, "sh": [0.0, 0.0],
                        "c": [0.0, 0.0], "fee": 0.0}
    return d


for r in csv.DictReader(open(LEDGER, encoding="utf-8", newline="")):
    if r["Type"] != "TRADE" or r["Side"] != "BUY":
        continue
    slug = r["Market_Slug"]
    if not slug or slug not in win:
        continue
    try:
        px = float(r["Price"])
        sh = float(r["Shares"])
        usd = float(r["USD_Amount"]) if r["USD_Amount"] else px * sh
    except ValueError:
        continue
    d = m(slug)
    i = 0 if r["Outcome"] == "Up" else 1
    d["sh"][i] += sh
    d["c"][i] += usd
    d["fee"] += 0.768 * 0.07 * px * (1.0 - px) * sh  # 76.8% of cash is taker
    t = r["Timestamp_UTC"]
    if d["t"] is None or t < d["t"]:
        d["t"], d["px"], d["side"] = t, px, r["Outcome"]

rows = []
for slug, d in mk.items():
    if d["px"] is None:
        continue
    try:
        slot = int(slug.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        continue
    from datetime import datetime, timezone

    epoch = int(datetime.fromisoformat(d["t"]).replace(tzinfo=timezone.utc).timestamp())
    off = epoch - slot
    if not -600 <= off <= 900:
        continue
    cost = d["c"][0] + d["c"][1]
    payout = d["sh"][0] if win[slug] == "Up" else d["sh"][1]
    rows.append({"px": d["px"], "off": off, "cost": cost, "pnl": payout - cost,
                 "fee": d["fee"], "net": payout - cost - d["fee"], "tick": d["side"]})

print("markets analysed:", len(rows), " total cost $%.0f" % sum(r["cost"] for r in rows))
print("gross pnl $%.0f  fees $%.0f  net $%.0f" % (
    sum(r["pnl"] for r in rows), sum(r["fee"] for r in rows), sum(r["net"] for r in rows)))


def show(label, sel):
    if not sel:
        print("%-26s %5s" % (label, "-"))
        return
    cost = sum(r["cost"] for r in sel)
    pnl = sum(r["pnl"] for r in sel)
    bps = [r["pnl"] / r["cost"] * 1e4 for r in sel if r["cost"] > 0]
    net = [r["net"] / r["cost"] * 1e4 for r in sel if r["cost"] > 0]
    winr = 100.0 * sum(1 for r in sel if r["net"] > 0) / len(sel)
    print("%-26s %6d %8.1f%% %9.0f %7.0f %7.0f %7.0f %7.0f" % (
        label, len(sel), winr, pnl, st.median(bps), pnl / cost * 1e4,
        st.median(net), sum(r["net"] for r in sel) / cost * 1e4))


HDR = "%-26s %6s %9s %9s %7s %7s %7s %7s" % (
    "bucket", "n", "net>0", "$pnl", "medBps", "bps", "netMed", "netBps")
price_b = [("<=0.25", lambda r: r["px"] <= 0.25), ("0.25-0.45", lambda r: 0.25 < r["px"] <= 0.45),
           ("0.45-0.55", lambda r: 0.45 < r["px"] < 0.55), ("0.55-0.75", lambda r: 0.55 <= r["px"] <= 0.75),
           (">0.75", lambda r: r["px"] > 0.75)]
off_b = [("0-15s", lambda r: r["off"] <= 15), ("16-30s", lambda r: 15 < r["off"] <= 30),
         ("31-60s", lambda r: 30 < r["off"] <= 60), ("61-120s", lambda r: 60 < r["off"] <= 120),
         (">120s", lambda r: r["off"] > 120)]

print("\nBY FIRST-LEG PRICE")
print(HDR)
show("all", rows)
for name, fn in price_b:
    show(name, [r for r in rows if fn(r)])

print("\nBY FIRST-LEG TIME (seconds after open)")
print(HDR)
for name, fn in off_b:
    show(name, [r for r in rows if fn(r)])

print("\nTHE TIGHT CASE: first leg >0.75, by time")
print(HDR)
for name, fn in off_b:
    show(name, [r for r in rows if r["px"] > 0.75 and fn(r)])

print("\nTHE LATE CASE: first leg after 60s, by price")
print(HDR)
for name, fn in price_b:
    show(name, [r for r in rows if r["off"] > 60 and fn(r)])
