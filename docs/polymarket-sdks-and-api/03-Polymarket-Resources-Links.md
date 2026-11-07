> Note

Companion guides: [01-Polymarket-Repositories.md](./01-Polymarket-Repositories.md) · [02-Polymarket-API-Reference.md](./02-Polymarket-API-Reference.md)

### Polymarket Repositories

#### Official Unified SDKs

* **`Polymarket/ts-sdk`**: Unified TypeScript SDK monorepo for building on Polymarket.
  * **Link**: `https://github.com/Polymarket/ts-sdk`
* **`Polymarket/py-sdk`**: Official Python SDK for Polymarket DeFi workflows.
  * **Link**: `https://github.com/Polymarket/py-sdk`
* **`Polymarket/rs-clob-client-v2`**: Ergonomic Rust SDK for the Central Limit Order Book (CLOB) and related services.
  * **Link**: `https://github.com/Polymarket/rs-clob-client-v2`

#### Smart Contracts

* **`Polymarket/ctf-exchange-v2`**: Core smart contract exchange system for Conditional Token Framework (CTF) assets.
  * **Link**: `https://github.com/Polymarket/ctf-exchange-v2`
* **`Polymarket/polymarket-v2-external`**: Next-generation prediction market smart contracts handling ERC1155 position tokens, oracles, and order matching.
  * **Link**: `https://github.com/Polymarket/polymarket-v2-external`

#### Legacy / Deprecated Repositories

* **`Polymarket/clob-client-v2`**: Legacy TypeScript client for the Polymarket CLOB.
  * **Link**: `https://github.com/Polymarket/clob-client-v2`
* **`Polymarket/builder-signing-sdk`**: Legacy TypeScript SDK for generating authenticated builder request headers.
  * **Link**: `https://github.com/Polymarket/builder-signing-sdk`
* **`Polymarket/py-builder-relayer-client`**: Legacy Python client for the Polymarket relayer API.
  * **Link**: `https://github.com/Polymarket/py-builder-relayer-client`

---

### Polymarket API References & Documentation Links

* **Gamma API** (Market Discovery & Metadata):
  * **Base URL**: `https://gamma-api.polymarket.com`
  * **Authentication**: None (Public)
  * **Key Uses**: `GET /events`, `GET /markets`, `GET /public-search`.
* **CLOB API** (Central Limit Order Book & Order Execution):
  * **Base URLs**: `https://clob.polymarket.com` / `https://clob-v2.polymarket.com`
  * **Authentication**: L1/L2 dual authentication for trading endpoints; public for orderbook reads
  * **Key Uses**: `GET /book`, `POST /order`, `DELETE /cancel-market-orders`, `POST /heartbeats`.
* **Data API v2** (Public Analytics, Positions & PnL):
  * **Base URL**: `https://data-api.polymarket.com/v2`
  * **Authentication**: None (Public)
  * **OpenAPI Contract**: `https://data-api.polymarket.com/v2/openapi.json`
  * **Interactive Explorer**: `https://data-api.polymarket.com/v2/docs`
  * **Key Uses**: `GET /v2/positions`, `GET /v2/trades`, `GET /v2/activity`, `GET /v2/value`, `GET /v2/leaderboard`.
* **Bridge API** (Cross-Chain Deposits & Withdrawals) :
  * **Base URL**: `https://bridge.polymarket.com`
  * **Key Uses**: `GET /supported-assets`, `POST /deposit`, `POST /withdraw`.
* **WebSockets & PolyBolt Channels** (Live Real-Time Data Streams):
  * **PolyBolt Live Data Stream**: `wss-live-v2.polymarket.com`
  * **Market / User Websocket Channels**: `wss://ws-subscriptions.polymarket.com`
* **Documentation & Machine / MCP Endpoints**:
  * **Documentation Index (`/llms.txt`)**: `https://docs.polymarket.com/llms.txt`
  * **Web MCP / Agent Integration**: Polymarket's Mintlify documentation site at `https://docs.polymarket.com` incorporates a native **`WEB_MCP`** integration for coding agents and LLMs.
