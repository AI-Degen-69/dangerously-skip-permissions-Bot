"""Paper redeem batch job — hold-to-redeem without keys, no funding.

Scans settled windows (winner known, not pending) that have not been
redeemed yet, marks them redeemedAt across active run workspaces (and legacy
bot/paper_runs/ for backward compatibility), and can dump REDEEM rows in the
same CSV schema as docs/dangerously-skip-permissions/scripts/save-trades-to-csv.py
so the existing reconcile pattern keeps working.

Real on-chain redeem (AutoRedeemer / claim) needs live keys and stays out
of paper. Weekly cadence is acceptable — the target account leaves winners
unclaimed for weeks (see findings.md).

Usage:
  python bot/redeem.py --dry-run             # list what would be redeemed
  python bot/redeem.py                       # mark redeemed
  python bot/redeem.py --run-id <run_id>     # target a specific run workspace
  python bot/redeem.py --csv out.csv         # also append REDEEM rows to CSV
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.runs import RUNS_DIR as WORKSPACES_DIR, RunWorkspace, resolve_run_workspace

BOT_DIR = ROOT / "bot"
RUNS_DIR = BOT_DIR / "paper_runs"
EVENTS_PATH = BOT_DIR / "events.jsonl"

CSV_HEADER = [
    "Proxy_Wallet", "Timestamp_UTC", "Type", "Market", "Outcome",
    "Side", "Price", "Shares", "USD_Amount", "Condition_ID",
    "Token_ID", "Transaction_Hash", "Market_Slug", "Event_Slug"
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_target_workspace(run_id: str | None = None) -> RunWorkspace | None:
    if run_id == "legacy":
        return None
    return resolve_run_workspace(run_id)


def redeemable(run_id: str | None = None) -> list[tuple[Path, dict]]:
    """Return list of (path, window_dict) for settled unredeemed windows."""
    ws = get_target_workspace(run_id)
    candidates: list[tuple[Path, dict]] = []

    target_dir = ws.windows_dir if (ws and ws.windows_dir.exists()) else RUNS_DIR
    if not target_dir.exists():
        return candidates

    for p in sorted(target_dir.glob("*.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if r.get("winner") and not r.get("pending") and not r.get("redeemedAt"):
            candidates.append((p, r))
    return candidates


def log_event(kind: str, reason: str, slug: str, events_path: Path | None = None, **kw: Any) -> None:
    target = events_path or EVENTS_PATH
    rec = {
        "ts": utc_now_iso(),
        "kind": kind,
        "mode": "paper",
        "reason": reason,
        "slug": slug,
    }
    rec.update(kw)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def execute_redeem(
    run_id: str | None = None,
    dry_run: bool = False,
    csv_path: str | None = None,
) -> dict[str, Any]:
    """Execute redeem batch for the target run workspace and sync to legacy paths."""
    ws = get_target_workspace(run_id)
    events_file = ws.events_file if (ws and ws.root.exists()) else EVENTS_PATH

    due = redeemable(run_id)
    now = utc_now_iso()

    winning_due: list[tuple[Path, dict, float, float]] = []
    zero_due: list[tuple[Path, dict]] = []

    for p, r in due:
        wshares = sum(
            float(f.get("shares", 0.0))
            for f in r.get("fills", [])
            if f.get("outcome") == r.get("winner")
        )
        payout = r.get("payout_usd")
        if payout is None:
            payout = round(wshares, 2)
        else:
            payout = float(payout)

        if payout > 0:
            winning_due.append((p, r, wshares, payout))
        else:
            zero_due.append((p, r))

    total_payout = sum(item[3] for item in winning_due)
    details = [
        {
            "slug": r.get("event_slug", p.stem),
            "winner": r.get("winner"),
            "shares": round(wshares, 2),
            "payoutUsd": round(payout, 2),
        }
        for p, r, wshares, payout in winning_due
    ]

    result: dict[str, Any] = {
        "ok": True,
        "runId": ws.run_id if ws else None,
        "redeemedCount": len(winning_due),
        "zeroCleanCount": len(zero_due),
        "totalWindowsMarked": len(due),
        "payoutUsd": round(total_payout, 2),
        "redeemedAt": now,
        "dryRun": dry_run,
        "details": details,
    }

    if dry_run or not due:
        return result

    rows = []
    for p, r, wshares, payout in winning_due:
        r["redeemedAt"] = now
        data_str = json.dumps(r, indent=2)
        p.write_text(data_str, encoding="utf-8")

        # Sync to legacy directory if different
        if RUNS_DIR.exists() and p.parent.resolve() != RUNS_DIR.resolve():
            legacy_file = RUNS_DIR / p.name
            if legacy_file.exists():
                try:
                    legacy_file.write_text(data_str, encoding="utf-8")
                except Exception:
                    pass

        # Also sync to workspace windows if p was in legacy dir
        if ws and ws.windows_dir.exists() and p.parent.resolve() != ws.windows_dir.resolve():
            ws_file = ws.windows_dir / p.name
            if ws_file.exists():
                try:
                    ws_file.write_text(data_str, encoding="utf-8")
                except Exception:
                    pass

        log_event(
            "redeem",
            "paper-redeem",
            r.get("event_slug", p.stem),
            events_path=events_file,
            detail={"winner": r.get("winner"), "payout": payout, "shares": wshares},
        )
        if events_file.resolve() != EVENTS_PATH.resolve() and EVENTS_PATH.exists():
            log_event(
                "redeem",
                "paper-redeem",
                r.get("event_slug", p.stem),
                events_path=EVENTS_PATH,
                detail={"winner": r.get("winner"), "payout": payout, "shares": wshares},
            )

        rows.append([
            "paper",
            now,
            "REDEEM",
            r.get("market", ""),
            r.get("winner", ""),
            "",
            1.0,
            round(wshares, 6),
            payout,
            "",
            "",
            "",
            r.get("event_slug", p.stem),
            r.get("event_slug", p.stem),
        ])

    # Mark zero-payout settled windows clean as well
    for p, r in zero_due:
        r["redeemedAt"] = now
        data_str = json.dumps(r, indent=2)
        p.write_text(data_str, encoding="utf-8")
        if RUNS_DIR.exists() and p.parent.resolve() != RUNS_DIR.resolve():
            legacy_file = RUNS_DIR / p.name
            if legacy_file.exists():
                try:
                    legacy_file.write_text(data_str, encoding="utf-8")
                except Exception:
                    pass
        if ws and ws.windows_dir.exists() and p.parent.resolve() != ws.windows_dir.resolve():
            ws_file = ws.windows_dir / p.name
            if ws_file.exists():
                try:
                    ws_file.write_text(data_str, encoding="utf-8")
                except Exception:
                    pass

    if csv_path and rows:
        path = Path(csv_path)
        need_header = not path.exists() or path.stat().st_size == 0
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if need_header:
                w.writerow(CSV_HEADER)
            w.writerows(rows)

    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Paper redeem batch (no keys)")
    ap.add_argument("--dry-run", action="store_true", help="list what would be redeemed without mutating files")
    ap.add_argument("--run-id", default=None, help="target run ID (defaults to active run workspace)")
    ap.add_argument("--csv", default=None, help="append REDEEM rows to this CSV")
    args = ap.parse_args()

    res = execute_redeem(run_id=args.run_id, dry_run=args.dry_run, csv_path=args.csv)
    target_name = res.get("runId") or "legacy paper_runs"
    print(f"target workspace: {target_name}")
    print(f"redeemable winning windows: {res['redeemedCount']} (${res['payoutUsd']:.2f})")
    for d in res["details"]:
        print(f"  {d['slug']}: winner={d['winner']} shares={d['shares']:.2f} payout=${d['payoutUsd']:.2f}")

    if res["zeroCleanCount"] > 0:
        print(f"({res['zeroCleanCount']} settled zero-payout windows marked clean)")

    if args.dry_run:
        print("[dry-run] no files mutated")
        return 0

    if args.csv and res["redeemedCount"] > 0:
        print(f"appended {res['redeemedCount']} REDEEM rows -> {args.csv}")

    print(f"redeemed: {res['redeemedCount']} winning windows (${res['payoutUsd']:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
