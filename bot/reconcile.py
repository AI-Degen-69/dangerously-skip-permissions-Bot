"""Reconcile via Data API v2 (public, no keys) — correct py-sdk usage.

Address requirement (docs/02): pass the account PROXY wallet, not the EOA.
Target: 0xc53375ff94e96100f2b30a4b5775db35218d69a9 (dangerously-skip-permissions).
"""

TARGET_PROXY = "0xc53375ff94e96100f2b30a4b5775db35218d69a9"

DATA_API = "https://data-api.polymarket.com/v2"


def target_urls(proxy: str = TARGET_PROXY) -> dict[str, str]:
    return {
        "positions": f"{DATA_API}/positions?user={proxy}",
        "activity": f"{DATA_API}/activity?user={proxy}&limit=20",
        "value": f"{DATA_API}/value?user={proxy}",
    }


def summarize_with_sdk(client, proxy: str = TARGET_PROXY) -> dict:
    """Uses PublicClient.list_positions / list_activity (paginated)."""
    pos = list(client.list_positions(user=proxy, page_size=20).iter_items())
    acts = list(client.list_activity(user=proxy, page_size=20).iter_items())
    return {"positions": len(pos), "recent_activity": len(acts)}


# --- paper fidelity job -------------------------------------------------
# Compares live paper_runs/*.json against the frozen CSV moments in
# bot.constants (45 median trades/market, 280/288 both-sides, M0-M4 shape).
# Same gate the plan requires before any live size.
def fidelity(runs_dir: str = "bot/paper_runs") -> dict:
    import json
    import statistics
    from pathlib import Path

    from . import constants as C

    runs = []
    for p in sorted(Path(runs_dir).glob("*.json")):
        try:
            runs.append(json.loads(p.read_text()))
        except Exception:
            continue
    settled = [r for r in runs if not r.get("pending")]
    ns = [r.get("trades", 0) for r in settled] or [0]
    both = sum(1 for r in settled
               if len({f.get("outcome") for f in r.get("fills", [])}) > 1)
    m_shape = [0, 0, 0, 0, 0]
    for r in settled:
        for f in r.get("fills", []):
            m = f.get("minute", 0)
            if 0 <= m <= 4:
                m_shape[m] += 1
    return {
        "windows": len(settled),
        "median_trades": statistics.median(ns),
        "mean_trades": round(statistics.mean(ns), 1),
        "both_sides": f"{both}/{len(settled)}" if settled else "0/0",
        "m_shape": m_shape,
        "target": {"windows": C.NUM_WINDOWS_24H,
                     "median": C.MEDIAN_TRADES_PER_WINDOW,
                     "mean": C.MEAN_TRADES_PER_WINDOW,
                     "both_sides": f"{int(C.NUM_WINDOWS_24H * C.BOTH_SIDES_RATE)}/{C.NUM_WINDOWS_24H}",
                     "m_shape": list(C.M_BUCKETS)},
    }


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(fidelity(), indent=2))
