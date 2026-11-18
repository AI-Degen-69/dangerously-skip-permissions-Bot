"""Unified CLI entry point for Polymarket leaderboard-trader tools.

Usage:
    python -m scripts.leaderboard_traders <command> [options]

Commands:
    fetch (pull)        Fetch Polymarket account trading activity into a CSV ledger
    strategy            Analyze a trade ledger for high-level strategy, timing, and fee patterns
    mechanics           Analyze a trade ledger for microsecond wallet mechanics, pricing, and sizing
    analyze <kind>      Alias to analyze 'strategy' or 'mechanics'
"""
import sys

USAGE = """Polymarket Leaderboard-Trader Reverse Engineering CLI

Usage:
  python -m scripts.leaderboard_traders <command> [options]

Commands:
  fetch (pull)      Fetch Polymarket account trading activity into CSV ledger
                    Options: -u/--user <wallet/handle>, -d/--date <YYYY-MM-DD|max>, --days <1|7>, -o <output>
  strategy          Analyze a trade ledger for strategy, timing, and fee rebate patterns
                    Usage: python -m scripts.leaderboard_traders strategy [path/to/ledger.csv]
  mechanics         Analyze a trade ledger for order mechanics, pricing, and ticket sizing
                    Usage: python -m scripts.leaderboard_traders mechanics [path/to/ledger.csv]
  analyze           Unified analyzer: 'strategy' or 'mechanics'
                    Usage: python -m scripts.leaderboard_traders analyze [strategy|mechanics] [ledger.csv]

Examples:
  # Fetch recent 7-day activity for a target wallet
  python -m scripts.leaderboard_traders fetch -u dangerously-skip-permissions

  # Fetch all historical activity backward until the account runs dry
  python -m scripts.leaderboard_traders fetch -u 0xc53375ff94e96100f2b30a4b5775db35218d69a9 -d max

  # Run strategy analysis on a trade ledger
  python -m scripts.leaderboard_traders strategy data/leaderboard/dangerously-skip-permissions/raw/trades.csv

  # Run mechanics analysis on a trade ledger
  python -m scripts.leaderboard_traders mechanics data/leaderboard/dangerously-skip-permissions/raw/trades.csv
"""


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(USAGE)
        sys.exit(0)

    command = sys.argv[1].lower()

    if command in ("fetch", "pull"):
        from .puller import main as puller_main
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        puller_main()

    elif command == "strategy":
        from .strategy import main as strategy_main
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        strategy_main()

    elif command == "mechanics":
        from .mechanics import main as mechanics_main
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        mechanics_main()

    elif command == "analyze":
        if len(sys.argv) < 3 or sys.argv[2] in ("-h", "--help"):
            print("Usage: python -m scripts.leaderboard_traders analyze [strategy|mechanics] [path/to/ledger.csv]")
            sys.exit(0)
        sub = sys.argv[2].lower()
        if sub in ("strategy", "strat"):
            from .strategy import main as strategy_main
            sys.argv = [sys.argv[0]] + sys.argv[3:]
            strategy_main()
        elif sub in ("mechanics", "mech"):
            from .mechanics import main as mechanics_main
            sys.argv = [sys.argv[0]] + sys.argv[3:]
            mechanics_main()
        else:
            print(f"Unknown analysis type: '{sub}'. Choose 'strategy' or 'mechanics'.", file=sys.stderr)
            sys.exit(1)

    else:
        print(f"Unknown command: '{command}'. Run with --help for available commands.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
