"""Fetch Polymarket account trading activity into a CSV ledger.

Usage:
    python scripts/fetch_trader_activity.py -u <wallet_or_username> [options]

Examples:
    python scripts/fetch_trader_activity.py -u dangerously-skip-permissions
    python scripts/fetch_trader_activity.py -u 0xc53375ff94e96100f2b30a4b5775db35218d69a9 -d max
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.leaderboard_traders.puller import main

if __name__ == "__main__":
    main()
