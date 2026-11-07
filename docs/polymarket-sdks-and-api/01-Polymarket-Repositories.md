### Overview of Polymarket Repositories

Polymarket provides several GitHub repositories containing client SDKs, smart contract architectures, and development tools.

For the API overview, see [02-Polymarket-API-Reference.md](./02-Polymarket-API-Reference.md). The collected repository links are also available in [03-Polymarket-Resources-Links.md](./03-Polymarket-Resources-Links.md).

---

#### 1. Official Unified SDKs (Recommended Layer)

* **[`Polymarket/ts-sdk`](https://github.com/Polymarket/ts-sdk) (`@polymarket/client`)**:

  * **Purpose**: The official TypeScript SDK monorepo for building applications on Polymarket. Managed as a `pnpm` workspace, it provides a unified interface across public market data, user trading, account management, and position handling.

  * **Structure**:

    * `packages/client`: Core TypeScript client library.

    * `packages/types`: Shared TypeScript type definitions.

    * `packages/bindings`: Internal generated API bindings.

    * `examples/scripts`: Runnable workflow scripts.

  * **How to Use**: Install via `npm` or `pnpm`. Developers can instantiate a client using `createPublicClient()` for synchronous public reads or async methods like `listPositions()` and `fetchPortfolioValue()`.

* **[`Polymarket/py-sdk`](https://github.com/Polymarket/py-sdk) (`polymarket-client`)**:

  * **Purpose**: The official Python SDK for Polymarket DeFi. It offers a coherent, workflow-oriented interface covering public data, authenticated trading, builder attribution, and position batching.

  * **How to Use**:

    * **Installation**: Run `uv add polymarket-client` or `pip install polymarket-client`.

    * **Execution**: Supports both synchronous (`PublicClient`) and asynchronous (`AsyncPublicClient`) clients. It also includes built-in methods for batch merging market or combo positions via `merge_multiple_positions()`.

* **[`Polymarket/rs-clob-client-v2`](https://github.com/Polymarket/rs-clob-client-v2) (`polymarket_client_sdk_v2`)**:

  * **Purpose**: An ergonomic, async-first Rust SDK for interacting with Polymarket services, primarily the Central Limit Order Book (CLOB).

  * **Features**: Features strongly typed request builders, zero-cost abstractions, compile-time type-level state machines for authentication, and Alloy signers.

  * **Modular Feature Flags**:

    * `clob`: Core order placement, market data, and auth.

    * `ws`: WebSocket client for orderbook, price, and user event streams.

    * `data`: Data API client for positions, trades, and analytics.

    * `gamma`: Market/event discovery and search.

    * `bridge`: Cross-chain deposit addresses.

    * `heartbeats`: Automated pinging to execute cancel-on-disconnect if the client drops connection.

  * **How to Use**: Add `polymarket_client_sdk_v2 = { version = "0.6", features = ["ws", "data"] }` to `Cargo.toml`. Authenticate using `Client::new()` with a `LocalSigner`, build orders via `.limit_order()` or `.market_order()`, sign them, and post via `client.post_order()`.

---

#### 2. Smart Contract Repositories

* **[`Polymarket/ctf-exchange-v2`](https://github.com/Polymarket/ctf-exchange-v2)**:

  * **Purpose**: The core smart contract system for trading Conditional Token Framework (CTF) assets on Polymarket.

  * **Architecture & Mechanics**:

    * Implements a **mixin composition pattern** (`CTFExchange` composed of `Auth`, `Trading`, `Hashing`, `AssetOperations`, `Fees`, `Signatures`).

    * **PMCT Collateral**: Trades in PolyMarket Collateral Token (`PMCT`), an ERC20 wrapper around USDC/USDCe via `CollateralOnramp` and `CollateralOfframp`.

    * **Order Execution**: Operator-driven `matchOrders()` supporting `COMPLEMENTARY` (p2p transfers), `MINT` (split collateral into outcome tokens), and `MERGE` (merge outcome tokens back into collateral).

    * **Signatures Supported**: EOA, `POLY_PROXY`, `POLY_GNOSIS_SAFE`, and `POLY_1271` smart contract signatures.

* **[`Polymarket/polymarket-v2-external`](https://github.com/Polymarket/polymarket-v2-external)**:

  * **Purpose**: Next-generation prediction market smart contract architecture built with Foundry and Solady.

  * **Architecture & Mechanics**:

    * Manages ERC1155 position tokens, collateral wrapping, modular oracle resolution (`OracleAggregator`, `OOReporterModule`, `ChainlinkReporterModule`, `EOAReporterModule`), order matching, and cross-chain bridging.

    * Uses **structured Position IDs** encoding module routing, condition identity, and outcome index directly into the token ID to eliminate storage lookups.

    * Key contracts include `PositionManager`, `Exchange`, `Router`, `AutoRedeemer`, `BinaryModule`, `NegRiskModule`, and `CombinatorialModule`.

---

#### 3. Deprecated SDKs (Legacy Layer)

> **Migration Warning**: These repositories explicitly advise developers to transition to the unified SDKs (`@polymarket/client` or `polymarket-client`).

* **[`Polymarket/clob-client-v2`](https://github.com/Polymarket/clob-client-v2)**: Legacy TypeScript client for the Polymarket CLOB. Used two-tier auth (L1 wallet signature via `createOrDeriveApiKey()` and L2 HMAC credentials) to submit `GTC`, `FOK`, or `FAK` limit and market orders.

* **[`Polymarket/builder-signing-sdk`](https://github.com/Polymarket/builder-signing-sdk)**: Legacy TypeScript SDK (`@polymarket/builder-signing-sdk`) used for generating authenticated request headers for builder attribution via `BuilderConfig`.

* **[`Polymarket/py-builder-relayer-client`](https://github.com/Polymarket/py-builder-relayer-client)**: Legacy Python client for interacting with Polymarket's relayer API infrastructure.

---
