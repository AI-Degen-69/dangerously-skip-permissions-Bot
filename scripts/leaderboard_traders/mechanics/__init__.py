"""Wallet mechanics from a Polymarket fill ledger (paper-trading reverse engineering).

Thin shell: the program itself lives in flow.py (run via main(), which imports
it lazily so importing this package never executes an analysis), the helpers
live in measures.py (numbers) and report.py (printing).
"""
from .measures import (
    MIN_RATE_N,
    SLUG_RE,
    bucket,
    held,
    market_clock,
    med,
    money,
    pnl_range,
    rate,
    secs,
    wilson,
)
from .report import (
    HDR,
    SECTION_WIDTH,
    Tee,
    _Indent,
    _section,
    line,
    md_table,
    show,
    show_group,
)

REQUIRED_COLUMNS = (
    "Timestamp_UTC", "Type", "Market_Slug", "Outcome",
    "Side", "Price", "Shares", "USD_Amount",
)

__all__ = [
    "REQUIRED_COLUMNS",
    "HDR",
    "MIN_RATE_N",
    "SECTION_WIDTH",
    "SLUG_RE",
    "Tee",
    "_Indent",
    "_section",
    "bucket",
    "held",
    "line",
    "main",
    "market_clock",
    "md_table",
    "med",
    "money",
    "pnl_range",
    "rate",
    "secs",
    "show",
    "show_group",
    "wilson",
]


def main() -> None:
    """Run the wallet-mechanics analysis (importing flow executes it)."""
    from . import flow  # noqa: F401
