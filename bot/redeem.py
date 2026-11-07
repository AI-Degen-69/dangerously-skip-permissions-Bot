"""Paper redeem batch job — hold-to-redeem without keys, no funding.

Scans bot/paper_runs/*.json for settled windows (winner known, not
pending) that have not been redeemed yet, marks them redeemedAt, and can
dump REDEEM rows in the same CSV schema as
docs/dangerously-skip-permissions/scripts/save-trades-to-csv.py so the
existing reconcile pattern keeps working.

Real on-chain redeem (AutoRedeemer / claim) needs live keys and stays out
of paper. Weekly cadence is acceptable — the target account leaves winners
unclaimed for weeks (see findings.md).

Usage:
  python bot/redeem.py --dry-run     # list what would be redeemed
  python bot/redeem.py               # mark redeemed
  python bot/redeem.py --csv out.csv # also append REDEEM rows to CSV
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RUNS_DIR = Path("bot/paper_runs")
EVENTS_PATH = Path("bot/events.jsonl")

CSV_HEADER = ["Proxy_Wallet", "Timestamp_UTC", "Type", "Market", "Outcome",
              "Side", "Price", "Shares", "USD_Amount", "Condition_ID",
              "Token_ID", "Transaction_Hash", "Market_Slug", "Event_Slug"]


def redeemable() -> list[dict]:
    out = []
    if not RUNS_DIR.exists():
        return out
    for p in sorted(RUNS_DIR.glob("*.json")):
        try:
            r = json.loads(p.read_text())
        except Exception:
            continue
        if r.get("winner") and not r.get("pending") and not r.get("redeemedAt"):
            out.append((p, r))
    return out


def log_event(kind: str, reason: str, slug: str, **kw) -> None:
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind,
           "mode": "paper", "reason": reason, "slug": slug}
    rec.update(kw)
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Paper redeem batch (no keys)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--csv", default=None, help="append REDEEM rows to this CSV")
    args = ap.parse_args()

    due = redeemable()
    print(f"redeemable windows: {len(due)}")
    for _, r in due:
        wshares = sum(f["shares"] for f in r.get("fills", [])
                      if f.get("outcome") == r.get("winner"))
        print(f"  {r.get('event_slug')}: winner={r.get('winner')} "
              f"shares={wshares:.2f} payout=${r.get('payout_usd', 0):.2f}")

    if args.dry_run:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for p, r in due:
        r["redeemedAt"] = now
        p.write_text(json.dumps(r, indent=2))
        log_event("redeem", "paper-redeem", r.get("event_slug", ""),
                  detail={"winner": r.get("winner"),
                          "payout": r.get("payout_usd")})
        wshares = sum(f["shares"] for f in r.get("fills", [])
                      if f.get("outcome") == r.get("winner"))
        rows.append(["paper", now, "REDEEM", r.get("market", ""),
                     r.get("winner", ""), "", 1.0,
                     round(wshares, 6), r.get("payout_usd", 0),
                     "", "", "", r.get("event_slug", ""),
                     r.get("event_slug", "")])

    if args.csv and rows:
        path = Path(args.csv)
        need_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="") as f:
            w = csv.writer(f)
            if need_header:
                w.writerow(CSV_HEADER)
            w.writerows(rows)
        print(f"appended {len(rows)} REDEEM rows -> {args.csv}")

    print(f"redeemed: {len(due)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
