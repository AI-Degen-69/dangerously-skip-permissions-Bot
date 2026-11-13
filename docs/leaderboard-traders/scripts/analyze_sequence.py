"""Does it trade one side then the other, or both ladders at once?

For each market: the order of fills, how often the side switches, how much the
two sides' buying overlaps, and how far apart the two sides' first fills land.
"""
import csv
import statistics as st
from collections import defaultdict
from datetime import datetime, timezone

LEDGER = "scratch/trades_full_history.csv"


def secs(iso):
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp()


seq = defaultdict(list)
for r in csv.DictReader(open(LEDGER, encoding="utf-8", newline="")):
    if r["Type"] != "TRADE" or r["Side"] != "BUY":
        continue
    s = r["Market_Slug"]
    if not s:
        continue
    seq[s].append((r["Timestamp_UTC"], r["Outcome"]))

runs, alt, n_markets, overlap = [], [], 0, 0
gaps = []
for s, fills in seq.items():
    fills.sort()
    sides = [f[1] for f in fills]
    if len(sides) < 4:
        continue
    n_markets += 1
    r_ = a_ = 0
    r_ = 1
    for i in range(1, len(sides)):
        if sides[i] == sides[i - 1]:
            r_ += 1
        else:
            runs.append(r_)
            r_ = 1
            a_ += 1
    runs.append(r_)
    alt.append(a_ / (len(sides) - 1))

    t_up = [f[0] for f in fills if f[1] == "Up"]
    t_dn = [f[0] for f in fills if f[1] == "Down"]
    if t_up and t_dn:
        if max(t_up[0], t_dn[0]) <= min(t_up[-1], t_dn[-1]):
            overlap += 1
        gaps.append(abs(secs(t_up[0]) - secs(t_dn[0])))

print("markets with >=4 fills:", n_markets)
print("mean same-side run length: %.2f  (1.0 = perfect alternation, big = one side at a time)"
      % st.mean(runs))
print("median share of consecutive pairs that switch side: %.0f%%" % (100 * st.median(alt)))
print("both sides bought inside the same time span: %.1f%%" % (100.0 * overlap / n_markets))

gaps.sort()
q = lambda x: gaps[min(len(gaps) - 1, int(x * len(gaps)))]
print("\ngap between the two sides' FIRST fills (seconds):"
      "  p10 %.0f  p25 %.0f  p50 %.0f  p75 %.0f  p90 %.0f"
      % (q(.10), q(.25), q(.5), q(.75), q(.90)))
