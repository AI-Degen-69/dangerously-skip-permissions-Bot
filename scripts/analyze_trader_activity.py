"""Analyze Polymarket account trade ledgers (strategy & mechanics).

Usage:
    python scripts/analyze_trader_activity.py strategy <path/to/ledger.csv>
    python scripts/analyze_trader_activity.py mechanics <path/to/ledger.csv>
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python scripts/analyze_trader_activity.py [strategy|mechanics] [path/to/ledger.csv]")
        sys.exit(0)

    mode = sys.argv[1].lower()
    if mode in ("strategy", "strat"):
        from scripts.leaderboard_traders.strategy import main as strat_main
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        strat_main()
    elif mode in ("mechanics", "mech"):
        from scripts.leaderboard_traders.mechanics import main as mech_main
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        mech_main()
    elif mode.endswith(".csv"):
        from scripts.leaderboard_traders.strategy import main as strat_main
        strat_main()
    else:
        print(f"Unknown analysis mode: '{mode}'. Use 'strategy' or 'mechanics'.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
