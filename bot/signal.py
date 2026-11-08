"""Lean-signal interface. Executor stays dumb (lean=0) until alpha is proven.

lean in [-1, +1]: -1 = max Down lean, +1 = max Up lean, 0 = neutral straddle.
confidence in [0, 1]: 0 = no edge, 1 = full size tilt.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LeanSignal:
    lean: float  # [-1, +1]
    confidence: float  # [0, 1]
    source: str = "dumb"
    raw: float | None = None


class LeanSource(Protocol):
    name: str

    def lean_for_window(self, event_slug: str) -> LeanSignal: ...


class DumbLean:
    """Neutral straddle — plumbing testable with no alpha."""

    name = "dumb"

    def lean_for_window(self, event_slug: str) -> LeanSignal:
        return LeanSignal(lean=0.0, confidence=0.0, source="dumb")


class BookMicropriceLean:
    """First real candidate (operator-confirmed 2026-11-07).

    Placeholder: returns neutral until CLOB book wiring lands.
    CSV shows lean forms mid-window (first-side predicts final only 61%),
    so this must read live book microprice, not first-trade side.
    """

    name = "book-microprice"

    def lean_for_window(self, event_slug: str) -> LeanSignal:
        return LeanSignal(lean=0.0, confidence=0.0, source="book-microprice-stub")
