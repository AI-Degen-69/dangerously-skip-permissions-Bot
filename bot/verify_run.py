"""Re-verify a run's windows against the tape prints recorded for them.

The live verifier only stamps the window it is trading, so a run that started
before the verifier existed keeps most of its fills unstamped forever. The
dashboard's "Verified Only" view then covers a slice of the tape instead of the
tape, and the two views cannot be compared. This tool re-checks every settled
window of a run against the prints the tape recorded inside that window and
writes the stamps back, so the view covers the whole run.

    python bot/verify_run.py --dry-run     # report only, change nothing
    python bot/verify_run.py               # re-stamp the active run
    python bot/verify_run.py --audit       # also stamp what could actually fill

A fill is confirmed by prints at or below its limit price inside its own
window, totalling at least the clip size - the same rule the live verifier
uses, with the window's own bounds instead of "everything up to now".

``--audit`` goes one step further and writes each window's ``fidelity``: the
same fills judged by sell-side flow against the queue that was resting ahead,
so the desk can show the paper net beside the net a real order could have got.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # allow `python bot/verify_run.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import constants as C
from bot.fill_audit import audit_window, load_prints
from bot.runs import resolve_run_workspace
from bot.tape_verifier import verify_fills


def window_epoch(slug: str | None) -> int:
    try:
        return int(str(slug).split("-")[-1])
    except (TypeError, ValueError):
        return 0


def status_of(fill: dict) -> str:
    return str((fill.get("detail") or {}).get("tapeStatus") or "none")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None, help="run to verify (default: the active run)")
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument("--audit", action="store_true", help="also stamp each window's attainable P&L")
    args = parser.parse_args()

    ws = resolve_run_workspace(args.run_id)
    if ws is None or not ws.windows_dir.exists():
        print("No run workspace found.")
        return 1

    tape_dir = ws.tape_dir if ws.tape_dir.exists() else None
    if tape_dir is None:
        print(f"No tape prints under {ws.tape_dir} - nothing to verify against.")
        return 1

    files = sorted(ws.windows_dir.glob("*.json"))
    # Loaded once: the auditor slices it per window, and the run holds ~200k
    # prints, so per-window reloads would dominate the backfill.
    prints = load_prints(tape_dir) if args.audit else None
    audited: list[dict] = []
    before = {"verified": 0, "partial": 0, "unverified": 0, "unverified-taker": 0, "none": 0}
    after = dict(before)
    changed_windows = 0
    skipped = 0

    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        fills = record.get("fills") or []
        if not fills:
            continue
        if record.get("pending") or not record.get("winner"):
            # The live loop owns an open window; it stamps it when it closes.
            skipped += 1
            continue

        epoch = window_epoch(record.get("event_slug"))
        if epoch <= 0:
            skipped += 1
            continue

        before_counts = {status_of(f) for f in fills}
        for f in fills:
            before[status_of(f)] = before.get(status_of(f), 0) + 1

        verify_fills(
            fills,
            tape_dir,
            window_start_s=float(epoch),
            window_end_s=float(epoch + C.WINDOW_S),
            force=True,
        )

        after_counts = {status_of(f) for f in fills}
        for f in fills:
            after[status_of(f)] = after.get(status_of(f), 0) + 1
        if before_counts != after_counts:
            changed_windows += 1

        if prints is not None:
            fidelity = audit_window(
                fills, prints, float(epoch), record.get("winner"), record.get("condition_id")
            )
            if fidelity is not None:
                record["fidelity"] = fidelity
                audited.append(fidelity)

        if not args.dry_run:
            path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    if not args.dry_run:
        ws.sync_to_paper_runs()

    total_before = sum(before.values())
    total_after = sum(after.values())
    print(f"run      : {ws.root.name}")
    print(f"tape     : {tape_dir}")
    print(f"windows  : {len(files)} ({skipped} left to the live loop)")
    print(f"changed  : {changed_windows} windows" + (" (dry run, nothing written)" if args.dry_run else ""))
    print("fills by status:")
    for status in ("verified", "partial", "unverified", "unverified-taker", "none"):
        b, a = before.get(status, 0), after.get(status, 0)
        print(f"  {status:16} {b:5} -> {a:5}")
    checked = total_after - after.get("none", 0)
    if checked:
        print(f"confirmed: {after.get('verified', 0)}/{checked} of the checked fills"
              f" ({100 * after.get('verified', 0) / checked:.1f}%)")
    if prints is not None:
        maker = sum(a["makerFills"] for a in audited)
        kept = sum(a["attainableFills"] for a in audited)
        net = sum(a["attainableNetUsd"] for a in audited)
        print(f"audited  : {len(audited)} windows, {kept}/{maker} maker fills could have filled"
              f" - attainable net ${net:+.2f}"
              + (" (dry run, nothing written)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
