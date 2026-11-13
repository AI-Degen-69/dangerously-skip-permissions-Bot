"""How much does it put on each price level, and is the clip one size?

Groups fills by (market, price) to recover the size of the order at each level,
then looks at the spread of that size and of the whole-market budget.
"""
import csv
import statistics as st
from collections import defaultdict

LEDGER = "scratch/trades_full_history.csv"

level_sh = defaultdict(float)
level_n = defaultdict(int)
level_usd = defaultdict(float)
market_usd = defaultdict(float)
market_sh = defaultdict(float)
market_n = defaultdict(int)

for r in csv.DictReader(open(LEDGER, encoding="utf-8", newline="")):
    if r["Type"] != "TRADE" or r["Side"] != "BUY":
        continue
    st_ = r["Market_Slug"]
    if not st_:
        continue
    try:
        px = float(r["Price"])
        sh = float(r["Shares"])
        usd = float(r["USD_Amount"]) if r["USD_Amount"] else px * sh
    except ValueError:
        continue
    k = (st_, round(px, 2))
    level_sh[k] += sh
    level_usd[k] += usd
    level_n[k] += 1
    market_usd[st_] += usd
    market_sh[st_] += sh
    market_n[st_] += 1


def line(label, xs):
    xs = sorted(xs)
    q = lambda x: xs[min(len(xs) - 1, int(x * len(xs)))]
    print("%-26s %7d  min %8.2f p10 %8.2f p25 %8.2f p50 %8.2f p75 %8.2f p90 %8.2f max %9.2f" % (
        label, len(xs), xs[0], q(.10), q(.25), q(.5), q(.75), q(.90), xs[-1]))


print("LEVEL (one price inside one market = one resting order)")
line("shares per level", list(level_sh.values()))
line("$ per level", list(level_usd.values()))
print()
print("MARKET")
line("shares per market", list(market_sh.values()))
line("$ per market", list(market_usd.values()))
levels_per_market = defaultdict(int)
for (s, p) in level_sh:
    levels_per_market[s] += 1
line("levels per market", list(levels_per_market.values()))
line("total fills per market", list(market_n.values()))

# Is each level filled in one print, or built from many?
multi = [n for n in level_n.values() if n > 1]
print("\nlevels hit by more than one print: %d of %d (%.1f%%)"
      % (len(multi), len(level_n), 100.0 * len(multi) / len(level_n)))
print("prints per level: median %.1f  p90 %d  max %d"
      % (st.mean(list(level_n.values())), sorted(level_n.values())[int(.9 * len(level_n))], max(level_n.values())))

# Level size vs price: does it buy more shares higher up, or fewer?
print("\nmedian level size by price band")
byprice = defaultdict(list)
for (s, p), sh in level_sh.items():
    byprice[min(19, int(p * 20))].append(sh)
for b in range(0, 20, 2):
    xs = byprice[b] + byprice.get(b + 1, [])
    if len(xs) > 200:
        print("  %.2f-%.2f  n %7d  med %6.1f sh  mean %6.1f" % (
            b * 0.05, (b + 2) * 0.05, len(xs), st.median(xs), st.mean(xs)))
