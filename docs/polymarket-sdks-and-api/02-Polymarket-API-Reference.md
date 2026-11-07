### Polymarket API Reference & How to Use Them

Polymarket divides its programmatic infrastructure into distinct HTTP REST APIs and WebSocket streaming channels:

The repository overview is in [01-Polymarket-Repositories.md](./01-Polymarket-Repositories.md). The collected API links and documentation references are also available in [03-Polymarket-Resources-Links.md](./03-Polymarket-Resources-Links.md).

```
                       ┌─────────────────────────────────────────────────┐
                       │              Polymarket Core APIs               │
                       └───────────────────────┬─────────────────────────┘
                                               │
         ┌───────────────────┬─────────────────┼───────────────────┬───────────────────┐
         ▼                   ▼                 ▼                   ▼                   ▼
    Gamma API            CLOB API         Data API v2          Bridge API         PolyBolt WS
(Market Discovery)   (Order Execution)  (Public Data & PnL) (Cross-Chain Ops)   (Live Data Feeds)
```

---

#### 1. Gamma API (Market Discovery)

* **Base URL**: [`https://gamma-api.polymarket.com`](https://gamma-api.polymarket.com)

* **Auth**: Fully public (no API key required)

* **Purpose**: The primary API for searching, discovering, and querying metadata for markets, events, tags, series, comments, sports, and public user profiles.

* **How to Use**:

  * Send REST `GET` requests to discover active markets:

    * `GET /events`: List active events ranked by volume or liquidity.

    * `GET /markets`: Search and list specific market outcomes and metadata.

    * `GET /public-search`: Search markets, events, and user profiles.

---

#### 2. CLOB API (Central Limit Order Book)

* **Base URLs**: [`https://clob.polymarket.com`](https://clob.polymarket.com) / [`https://clob-v2.polymarket.com`](https://clob-v2.polymarket.com)

* **Auth**: Public endpoints are unauthenticated; trading operations require dual-layer (L1/L2) authentication.

* **Purpose**: Handles orderbook depth, order placement, order cancellations, midpoints, spreads, and execution history.

* **Key Endpoints & Usage**:

  * **Market Data**: `GET /book` (fetch orderbook), `GET /price`, `GET /midpoint`, `GET /spread`.

  * **Order Placement**: `POST /order` (single order) or `POST /orders` (batch orders). Requires EIP-712 order signatures.

  * **Order Cancellation**: `DELETE /order` (cancel single), `DELETE /orders` (cancel multiple), `DELETE /cancel-market-orders`, or `DELETE /cancel-all`.

  * **Disconnect Safety**: `POST /heartbeats` sends keep-alive pings to prevent open orders from standing if the client disconnects.

---

#### 3. Data API v2 (Public Analytics, Positions & PnL)

* **Base URL**: [`https://data-api.polymarket.com/v2`](https://data-api.polymarket.com/v2)

* **Auth**: Fully public (no API key or credentials required)

* **Migration Status**: Replaces Data API v1, which retires on November 2, 2026.

* **Conventions**: All endpoints wrap payloads inside `{ "data": ..., "pagination": ... }` envelopes and use cursor-based pagination (`next_cursor`) with `snake_case` fields.

* **References**: [OpenAPI contract](https://data-api.polymarket.com/v2/openapi.json) · [Interactive explorer](https://data-api.polymarket.com/v2/docs)

* **Key Endpoints & Usage**:

  * `GET /v2/positions`: Query open, closed, redeemable, or mergeable positions for a wallet or market.

    > **Address Requirement**: You **must pass the account proxy wallet address** (`proxy_wallet`), not the signing EOA key, to retrieve holdings.

  * `GET /v2/trades`: Global, market, or user trade execution feeds.

  * `GET /v2/activity`: On-chain action feed detailing trades, splits, merges, redemptions, rewards, and rebates.

  * `GET /v2/value`: Query portfolio mark-to-market valuations.

  * `GET /v2/holders`: Top outcome holders for a market.

  * `GET /v2/leaderboard`: Ranked trader PnL and volume leaderboards.

  * `GET /v2/prices-history`: Historical pricing series for an outcome token.

---

#### 4. Bridge API (Cross-Chain Deposits & Withdrawals)

* **Base URL**: [`https://bridge.polymarket.com`](https://bridge.polymarket.com)

* **Purpose**: Manages cross-chain deposits and withdrawals across EVM chains, Solana (SVM), and Bitcoin (BTC) as a proxy for the `fun.xyz` service.

* **Key Endpoints**: `GET /supported-assets`, `POST /deposit` (generates deposit addresses), `POST /quote`, and `POST /withdraw`.

---

#### 5. Streaming Channels (WebSockets & PolyBolt)

* **WSS Market & User Channels**: [`wss://ws-subscriptions.polymarket.com`](wss://ws-subscriptions.polymarket.com) / CLOB WS feeds for streaming orderbook updates (`subscribe_orderbook`), price shifts (`subscribe_prices`), midpoints (`subscribe_midpoints`), and authenticated user trade fills (`subscribe_orders`, `subscribe_trades`).

* **PolyBolt WebSocket Channel**: Hosted at `wss-live-v2.polymarket.com`, providing high-throughput real-time live data feeds.

* **Polymarket documentation**: [Documentation site](https://docs.polymarket.com) · [Machine-readable index (`llms.txt`)](https://docs.polymarket.com/llms.txt)

---

### Third-Party Data Intelligence & Backtesting Tools

* **[Codex API](https://graph.codex.io/graphql)**:

  * **Purpose**: A GraphQL data intelligence layer (`https://graph.codex.io/graphql`) that indexes Polymarket and Kalshi into a unified schema.

  * **Usage**: Used alongside Polymarket's native API to obtain OHLC odds history (1-minute to weekly bars), sub-day momentum/trending rankings (`filterPredictionEvents`), and live WebSocket trade streams (`onPredictionTradesCreated`).

* **PolyTest**:

  * **Purpose**: A specialized backtesting engine and historical data recorder that captures orderbook snapshots and price history for 5-minute Up/Down prediction markets.