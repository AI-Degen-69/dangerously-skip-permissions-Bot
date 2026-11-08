# Implementation Plan - Real-Time WebSocket Orderbook, Terminal Watcher & Dashboard Stream UI

Branch: i4/stream-live-orderbook-via-websocket | Issue: #4

## 1. Overview & Motivation
Currently, `bot/live_paper.py` couples trade pacing with market data retrieval by using a blocking `time.sleep()` of 5 to 6.5 seconds. During these intervals, the bot is completely blind to orderbook changes, price sweeps, and micro-moves. Furthermore, making 3 synchronous HTTP REST calls per cycle risks REST rate limits (HTTP 429).

This implementation introduces:
1. Real-time WebSocket streaming from Polymarket's public CLOB market feed (`wss://ws-subscriptions-clob.polymarket.com/ws/market`).
2. An in-memory, zero-latency, thread-safe orderbook.
3. Continuous connection health monitoring (staleness detection if >3s without ticks; auto-reconnect; automatic REST fallback if disconnected/stale).
4. A dedicated terminal watcher CLI (`python bot/ws.py --watch`) with millisecond timestamps and colorized tick feeds.
5. A live WebSocket stream panel and health indicator in the desk dashboard UI (`src/app/pages/Live.tsx`).

## 2. Grounded API Specifications (from NotebookLM & Repos)
* **WebSocket Endpoint**: `wss://ws-subscriptions-clob.polymarket.com/ws/market`
  *(Derived from `polymarket.environments.PRODUCTION.clob_market_ws_url` and official CLOB guides).*
* **Subscription Message Frame**:
  ```json
  {
    "type": "market",
    "assets_ids": ["<up_token_id>", "<down_token_id>"]
  }
  ```
* **Initial Snapshot Payload**:
  Array of objects containing:
  `market`, `asset_id`, `timestamp`, `hash`, `bids: [{"price": "...", "size": "..."}]`, `asks: [{"price": "...", "size": "..."}]`.
* **Incremental Delta Payload**:
  `{"market": "...", "price_changes": [{"asset_id": "...", "price": "...", "size": "...", "side": "BUY"|"SELL", "best_bid": "...", "best_ask": "..."}]}`
* **Keepalive / Ping**:
  Standard WebSocket PING/PONG control frames + text `"PING"` message keepalive.

## 3. Architecture & Interface Contracts

### 3.1 Data Structures (`bot/ws.py`)
```python
@dataclass
class TokenBook:
    asset_id: str
    outcome: str  # "Up" | "Down"
    bids: dict[float, float] = field(default_factory=dict)  # price -> size
    asks: dict[float, float] = field(default_factory=dict)  # price -> size
    best_bid: float | None = None
    best_ask: float | None = None
    midpoint: float | None = None
    last_update_ts: float = 0.0

@dataclass
class StreamTick:
    ts: float  # epoch seconds with ms precision
    time_str: str  # HH:MM:SS.mmm
    outcome: str  # "Up" | "Down"
    event_type: str  # "snapshot" | "price_change"
    side: str | None  # "BUY" | "SELL" | None
    price: float | None
    size: float | None
    best_bid: float | None
    best_ask: float | None
    midpoint: float | None

class ConnectionState(Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    STALE = "stale"
    DISCONNECTED = "disconnected"
    FALLBACK_ACTIVE = "fallback_active"

class LiveBookStreamer:
    def __init__(self, up_token_id: str, down_token_id: str, rest_fallback_client=None, buffer_size: int = 100): ...
    def start(self) -> None: ...  # Spawns background asyncio daemon thread
    def stop(self) -> None: ...
    def get_status(self) -> dict: ...  # state, age_ms, reconnect_count, tick_count
    def get_recent_ticks(self, limit: int = 50) -> list[dict]: ...
    def get_buy_price(self, token_id: str) -> float | None: ...
    def get_midpoint(self, token_id: str) -> float | None: ...
    def get_lean(self, up_id: str, down_id: str) -> LeanSignal: ...
```

### 3.2 Terminal Watcher Interface
Run via command line:
```bash
python bot/ws.py --watch              # watch active window
python bot/ws.py --watch --slot <ts>  # watch specific window
```
Output format:
```
[01:54:28.120] 🟢 CONNECTED (wss://ws-subscriptions-clob.polymarket.com/ws/market)
[01:54:28.250] 📦 SNAPSHOT Up   bid: 0.84 (2450 sh) | ask: 0.86 (1800 sh) | mid: 0.850
[01:54:28.252] 📦 SNAPSHOT Down bid: 0.13 (1200 sh) | ask: 0.15 (2100 sh) | mid: 0.140
[01:54:29.410] ⚡ TICK Up BUY 0.86 (size: 50.0) | mid: 0.855 | age: 12ms
[01:54:32.105] ⚠️ STALE: no ticks for 3200ms
[01:54:35.000] 🚨 DISCONNECTED: reconnecting in 2s... [FALLBACK TO REST ACTIVE]
```

### 3.3 Desk API & Dashboard UI Interface
- `bot/api.py`: Exposes `ws` health object + recent ticks in `snapshot()` and a streaming `/api/bot/ws-ticks` endpoint.
- `src/app/pages/Live.tsx`: Renders:
  1. Connection status badge in header (`🟢 WSS Live (<40ms)` / `🟡 Stale (3.2s)` / `🔴 Disconnected - REST Fallback`).
  2. Live Stream Tape component displaying recent ticks with millisecond timestamps, outcome tags, prices, sizes, and midpoints.

## 4. Tasks & Implementation Steps

- [x] **Task 1: Core WebSocket Engine & Health Monitor (`bot/ws.py`)** `[Backend/Logic]` [Size: M]
  - Implement `TokenBook` with bid/ask tracking, best quote derivation, and midpoint calculation.
  - Implement `LiveBookStreamer` running a background daemon thread with `websockets.connect`.
  - Handle initial snapshot array and subsequent `price_changes` updates.
  - Implement connection state machine: `CONNECTING`, `CONNECTED`, `STALE` (>3s tick silence), `DISCONNECTED`, `FALLBACK_ACTIVE`.
  - Implement ring buffer of recent `StreamTick` objects (last 100 entries).
  - Handle PING keepalives and automatic reconnect with exponential backoff.
  - Expose thread-safe read helpers with transparent fallback to `PublicClient`.
  - *Verification*: `python -m unittest bot/tests/test_ws.py`.

- [x] **Task 2: Terminal Stream Watcher CLI (`bot/ws.py`)** `[CLI/Observability]` [Size: S]
  - Add CLI arguments: `--watch`, `--slot <epoch>`, `--limit <n>`.
  - Auto-discover current window's Up and Down token IDs via `bot.discovery`.
  - Print formatted, colorized real-time ticks with millisecond timestamps, side, price, size, and midpoint.
  - Print visual warnings on staleness (>3s) and disconnect/fallback events.
  - *Verification*: Run `python bot/ws.py --watch` in terminal and verify output stream.

- [x] **Task 3: Comprehensive Test Suite (`bot/tests/test_ws.py`)** `[Test]` [Size: S]
  - Unit test `TokenBook.apply_snapshot` with various depth levels.
  - Unit test `TokenBook.apply_price_change` (orderbook additions, updates, removals when size=0).
  - Unit test staleness detection and state transitions (`CONNECTED` -> `STALE` -> `FALLBACK_ACTIVE`).
  - Unit test `LiveBookStreamer` fallback to REST when disconnected.
  - Unit test thread-safety under concurrent readers and writers.
  - *Verification*: `python -m unittest bot.tests.test_ws` (all green).

- [x] **Task 4: Trading Loop & Desk API Integration (`bot/live_paper.py` + `bot/api.py`)** `[Backend/Integration]` [Size: M]
  - Update `bot/live_paper.py`: In `trade_window()`, start `LiveBookStreamer(up_id, down_id)`.
  - Update `microprice_lean()` and `live_buy_price()` to query the streamer first.
  - Ensure streamer is cleanly stopped when the 5-minute window closes.
  - Update `bot/api.py`: include `ws` connection health and recent ticks in `snapshot()`.
  - Keep `bot/tests/test_bot.py` mocks aligned so existing test suite continues passing.
  - *Verification*: `python -m unittest discover -s bot/tests`.

- [ ] **Task 5: Dashboard UI Live Stream Panel & Health Badge (`src/app/pages/Live.tsx` + `src/app/lib/bot.ts`)** `[Frontend/UI]` [Size: M]
  - Update `src/app/lib/bot.ts` with `WsStatus` types and hook queries.
  - Add connection status badge to `Live.tsx` page header:
    - `🟢 WSS Live` (active, low latency)
    - `🟡 WSS Stale` (warning, >3s gap)
    - `🔴 Disconnected` (danger, fallback active)
  - Add a "Live WSS Stream" panel in `Live.tsx` showing the tick tape table/feed with timestamps, outcome chips, prices, sizes, and spread/midpoint metrics.
  - *Verification*: Inspect UI via Vite dev server.

- [ ] **Task 6: End-to-End System Verification** `[Verification]` [Size: S]
  - Run terminal watcher: `python bot/ws.py --watch` to verify live console ticks.
  - Run paper trading window: `python bot/live_paper.py --once` with WSS enabled.
  - Verify live stream ticks render in dashboard UI simultaneously.
  - Confirm 0 REST calls made during streaming.
  - All unit tests passing (25 existing + new WSS tests).

## 5. Checkpoints
- **Checkpoint 1 (after Task 3)**: Core WSS engine and unit tests 100% green; terminal watcher verified live.
- **Checkpoint 2 (after Task 4)**: Trading engine and desk API integrated; existing 25 unit tests remain green.
- **Checkpoint 3 (after Task 5)**: Desk UI renders live WSS stream and health badges.
- **Checkpoint 4 (after Task 6)**: Full end-to-end verified across CLI, UI, and paper execution loop.
