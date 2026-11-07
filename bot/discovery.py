"""Gamma discovery — correct py-sdk usage per docs/02 API reference.

Gamma is public, no auth. Event slug = btc-updown-5m-<epoch>.
Market detail lives on get_event(...).markets[0]: condition_id + outcomes
{yes: {label Up, token_id}, no: {label Down, token_id}}.
NOTE: get_market(slug) does NOT return token ids — use get_event.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from polymarket import PublicClient

WINDOW_S = 300


@dataclass(frozen=True)
class WindowSpec:
    event_slug: str
    condition_id: str
    up_token_id: str
    down_token_id: str
    question: str


def current_slot(now_ts: int | None = None) -> int:
    now = now_ts if now_ts is not None else int(datetime.now(timezone.utc).timestamp())
    return (now // WINDOW_S) * WINDOW_S


def get_window(client: PublicClient, event_slug: str) -> WindowSpec:
    ev = client.get_event(slug=event_slug)
    d = ev.model_dump()
    markets = d.get("markets") or []
    if not markets:
        raise ValueError(f"no markets for {event_slug}")
    m = markets[0]
    outs = m.get("outcomes") or {}
    up = (outs.get("yes") or {}).get("token_id")
    down = (outs.get("no") or {}).get("token_id")
    if not up or not down:
        raise ValueError(f"missing token_ids for {event_slug}: {outs.keys()}")
    return WindowSpec(
        event_slug=d.get("slug") or event_slug,
        condition_id=m.get("condition_id") or "",
        up_token_id=up,
        down_token_id=down,
        question=m.get("question") or "",
    )


def current_and_next(client: PublicClient | None = None) -> tuple[WindowSpec, WindowSpec]:
    c = client or PublicClient()
    slot = current_slot()
    return (
        get_window(c, f"btc-updown-5m-{slot}"),
        get_window(c, f"btc-updown-5m-{slot + WINDOW_S}"),
    )
