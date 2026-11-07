"""288-window paper fidelity run — dumb straddle, no keys, no funding.

Simulates the executor state machine for 288 windows and prints the
fidelity diff vs CSV moments (45 median trades/market, both-sides rate,
M0-M4 shape). Optionally POSTs window summaries to the local Worker
/api/bot/import (same-origin dev server) for the dashboard.
"""

import json
import statistics
import sys
import urllib.request

sys.path.insert(0, ".")

from bot import constants as C
from bot.executor import plan_window
from bot.risk import RiskState
from bot.signal import DumbLean


def main(post: str | None = None) -> None:
    sig = DumbLean()
    plans = [plan_window(f"paper-5m-{i:03d}", sig.lean_for_window(f"w{i}"), RiskState()) for i in range(C.NUM_WINDOWS_24H)]
    ns = [len(p.fills) for p in plans]
    both = sum(1 for p in plans if len({f.outcome for f in p.fills}) > 1)
    print(f"paper windows={len(plans)} median={statistics.median(ns)} mean={round(statistics.mean(ns),1)} both-sides={both}/{len(plans)}")
    print(f"target  windows=288 median=45 mean=58.5 both-sides=280/288")
    if post:
        payload = json.dumps({"windows": [
            {"event_slug": p.event_slug, "market": p.event_slug, "trades": len(p.fills),
             "cost_usd": round(p.cost, 2), "payout_usd": 0, "net_usd": round(-p.cost, 2)}
            for p in plans
        ]}).encode()
        req = urllib.request.Request(post, data=payload, headers={"Content-Type": "application/json"})
        print(urllib.request.urlopen(req).read().decode()[:200])
        print(f"imported {len(plans)} paper windows -> {post}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
