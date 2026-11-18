"""Tape slicing helpers (cached per-run slices from recorded JSONL)."""

from __future__ import annotations

import json
import pickle
import tempfile
from pathlib import Path

from . import constants as C
from .replay_consts import STRATEGY_V26, _DEFAULT_RUNS_DIR
from .runs import tape_segments


def cache_dir() -> Path:
    base = Path("scratch/replay_cache") if Path("scratch").exists() else Path(tempfile.gettempdir()) / "replay_cache"
    base.mkdir(parents=True, exist_ok=True)
    return base


def list_run_windows(run_dir: Path) -> list[dict]:
    """(slot, condition_id, winner, slug) for every window file in a run."""
    out = []
    wdir = run_dir / "windows"
    if not wdir.exists():
        return out
    for p in sorted(wdir.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        slug = d.get("event_slug") or p.stem
        try:
            slot = int(str(slug).rsplit("-", 1)[1])
        except (ValueError, IndexError):
            continue
        out.append({
            "slot": slot,
            "slug": slug,
            "condition_id": d.get("condition_id"),
            "winner": d.get("winner"),
        })
    return out

def load_prints_grouped(tape_dir: Path) -> dict[str, list[dict]]:
    """Prints grouped by market (condition id), oldest first per market."""
    grouped: dict[str, list[dict]] = {}
    # Flat ts-ordered log too: windows without a recorded condition_id (older
    # run format) join prints by time, majority market wins the slice.
    flat: list[dict] = []
    for path in tape_segments(tape_dir, "prints"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue  # tolerated: tape is append-only, last line may be partial
                    mkt = str(rec.get("market") or "")
                    if not mkt:
                        continue
                    try:
                        ts = float(rec.get("ts") or 0.0)
                    except (TypeError, ValueError):
                        continue
                    if ts <= 0:
                        continue
                    grouped.setdefault(mkt, []).append(rec)
                    flat.append(rec)
        except OSError:
            continue
    for recs in grouped.values():
        recs.sort(key=lambda r: float(r.get("ts") or 0.0))
    flat.sort(key=lambda r: float(r.get("ts") or 0.0))
    grouped[""] = flat  # scratch key: time-slice source for the fallback join
    return grouped

def build_slices(run_id: str, runs_root: Path | None = None) -> dict:
    """Per-window (book_events, prints) slices for one run, cached on disk.

    One streaming pass over the book segments: rows are assigned to a window
    by asset_id (each market's two tokens are learned from its prints) and
    clipped to [slot, slot+300]. Book segments are large (100+ MB), so this
    runs once per tape state and is pickled afterwards.
    """
    cdir = cache_dir()
    if runs_root is None:
        runs_root = _DEFAULT_RUNS_DIR
    run_dir = runs_root / run_id
    tape_dir = run_dir / "tape"
    manifest = {"windows": [], "prints": {}, "book": {}}
    windows = list_run_windows(run_dir)
    if not windows or not tape_dir.exists():
        return manifest

    prints_by_market = load_prints_grouped(tape_dir)
    flat = prints_by_market.pop("", [])
    import bisect as _bisect
    flat_ts = [float(r.get("ts") or 0.0) for r in flat]
    voted = 0
    for w in windows:
        if not w.get("condition_id"):
            # Older window format: no condition_id recorded. The window's own
            # recorder is the first to write into its time range, so the
            # majority market in [slot, slot+300] is this window's.
            lo = _bisect.bisect_left(flat_ts, float(w["slot"]))
            hi = _bisect.bisect_right(flat_ts, float(w["slot"]) + WINDOW_S)
            counts: dict[str, int] = {}
            for rec in flat[lo:hi]:
                mkt = str(rec.get("market") or "")
                if mkt:
                    counts[mkt] = counts.get(mkt, 0) + 1
            if counts:
                w["condition_id"] = max(counts, key=lambda m: counts[m])
                voted += 1
    # asset_id -> slot: each market's tokens are unique to it.
    asset_to_slot: dict[str, int] = {}
    for w in windows:
        for rec in prints_by_market.get(str(w["condition_id"] or ""), []):
            aid = str(rec.get("asset_id") or "")
            if aid and aid not in asset_to_slot:
                asset_to_slot[aid] = w["slot"]

    by_slot: dict[int, list] = {w["slot"]: [] for w in windows}
    slot_set = set(by_slot)
    for path in tape_segments(tape_dir, "book"):
        try:
            f = open(path, "r", encoding="utf-8")
        except OSError:
            continue
        with f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue  # partial last line while the live loop is writing
                aid = str(rec.get("asset_id") or "")
                slot = asset_to_slot.get(aid)
                if slot is None or slot not in slot_set:
                    continue
                try:
                    ts = float(rec.get("ts") or 0.0)
                except (TypeError, ValueError):
                    continue
                if ts < slot or ts > slot + WINDOW_S:
                    continue
                bids = rec.get("bids") or []
                asks = rec.get("asks") or []
                try:
                    bids = [[float(p), float(s)] for p, s in bids]
                    asks = [[float(p), float(s)] for p, s in asks]
                except (TypeError, ValueError):
                    continue
                by_slot[slot].append((ts, str(rec.get("outcome") or ""), bids, asks))
    for rows in by_slot.values():
        rows.sort(key=lambda r: r[0])

    manifest["windows"] = windows
    manifest["voted_markets"] = voted
    manifest["prints"] = {
        w["condition_id"]: [
            (float(r.get("ts") or 0.0), str(r.get("slug_outcome") or ""),
             float(r.get("price") or 0.0), float(r.get("size") or 0.0),
             str(r.get("side") or ""), str(r.get("asset_id") or ""))
            for r in prints_by_market.get(str(w["condition_id"] or ""), [])
            if w["slot"] <= float(r.get("ts") or 0.0) <= w["slot"] + WINDOW_S
        ]
        for w in windows
    }
    manifest["book"] = {str(s): rows for s, rows in by_slot.items()}
    # asset -> outcome fallback for prints missing slug_outcome
    outcome_by_asset: dict[str, str] = {}
    for w in windows:
        for rec in prints_by_market.get(str(w["condition_id"] or ""), []):
            aid, oc = str(rec.get("asset_id") or ""), str(rec.get("slug_outcome") or "")
            if aid and oc and aid not in outcome_by_asset:
                outcome_by_asset[aid] = oc
    manifest["asset_outcome"] = outcome_by_asset
    try:
        with open(cdir / f"{run_id}.pkl", "wb") as f:
            pickle.dump(manifest, f, protocol=5)
    except OSError:
        pass
    return manifest

def load_slices(run_id: str, runs_root: Path | None = None) -> dict:
    """Cached slices; rebuilt when the tape grew since the cache was written."""
    if runs_root is None:
        runs_root = _DEFAULT_RUNS_DIR
    cdir = cache_dir()
    run_dir = runs_root / run_id
    tape_dir = run_dir / "tape"
    cache_path = cdir / f"{run_id}.pkl"
    if cache_path.exists() and tape_dir.exists():
        try:
            newest = max(p.stat().st_mtime for p in list(tape_dir.glob("*.jsonl")))
            if cache_path.stat().st_mtime >= newest:
                with open(cache_path, "rb") as f:
                    data = pickle.load(f)
                # A window prune leaves the tape untouched, so the tape mtime alone
                # would serve slices for windows that no longer exist.
                if sum(1 for _ in (run_dir / "windows").glob("*.json")) == len(data["windows"]):
                    return data
        except Exception:
            pass
    return build_slices(run_id, runs_root)

def load_run_entry(run_id: str, runs_root: Path | None = None) -> tuple[str, dict]:
    """(strategy_id, entry) frozen in the run's own config snapshot."""
    if runs_root is None:
        runs_root = _DEFAULT_RUNS_DIR
    try:
        meta = json.loads((runs_root / run_id / "run_meta.json").read_text(encoding="utf-8"))
        snap = meta.get("configSnapshot", {}) or {}
        strat = (snap.get("strategy") or {}).get("id", STRATEGY_V26)
        entry = dict(snap.get("entry") or {})
        if entry:
            return str(strat), entry
    except Exception:
        pass
    reg = C.STRATEGY_SETUPS[STRATEGY_V26]
    return STRATEGY_V26, dict(reg["entry"])
