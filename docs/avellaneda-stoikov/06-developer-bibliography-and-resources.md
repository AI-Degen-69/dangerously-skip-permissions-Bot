# Polymarket 5-Minute HFT Engine: Developer Bibliography & Resource Hub

This document serves as the master bibliography, repository index, and configuration reference for the automated trading bot. It provides the environment template tailored for an **external wallet (EOA / MetaMask)** using developer address `0xeE3B778A783510BC833384919F709e3d2fee1624`, followed by a categorized directory of all official repositories, API endpoints, smart contracts, data feeds, and academic papers required to build and operate the system.

---

## 1. Production Environment Template (External Wallet / EOA)

Configure this environment file in your project root (`.env`). It is pre-parameterized for direct EOA interaction (Signature Type `0`), pointing to Polygon Mainnet (Chain ID `137`).

```bash
# ==============================================================================
# POLYMARKET 5-MINUTE HFT BOT - ENVIRONMENT CONFIGURATION
# ==============================================================================
# Mode: Direct External Wallet (EOA / MetaMask)
# Developer Public Address: 0xeE3B778A783510BC833384919F709e3d2fee1624
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. WALLET & AUTHENTICATION (LAYER 1)
# ------------------------------------------------------------------------------
# Your public Ethereum/Polygon address (External Wallet EOA)
POLYMARKET_PUBLIC_ADDRESS="0xeE3B778A783510BC833384919F709e3d2fee1624"

# Private key of the external wallet (64-character hex string)
# Used by Alloy / Ethers-rs to generate EIP-712 order signatures
SIGNER_SECRET_KEY="0x_YOUR_EXTERNAL_WALLET_PRIVATE_KEY_HEX_HERE"

# Signature Type for polymarket_client_sdk_v2:
# 0 = EOA (Standard external wallet: MetaMask, Coinbase Wallet, Ledger)
# 1 = POLY_PROXY (Legacy Polymarket Proxy)
# 2 = POLY_GNOSIS_SAFE (Magic Link / Email onboarding)
# For this address, set strictly to 0:
POLYMARKET_SIGNATURE_TYPE=0

# In an EOA setup, your proxy address for Data API v2 queries is your EOA address
POLYMARKET_PROXY_ADDRESS="0xeE3B778A783510BC833384919F709e3d2fee1624"

# ------------------------------------------------------------------------------
# 2. CLOB API CREDENTIALS (LAYER 2)
# ------------------------------------------------------------------------------
# Derived via L1 wallet signature (client.derive_api_key() in rs-clob-client-v2)
CLOB_API_KEY="YOUR_CLOB_API_KEY_UUID"
CLOB_API_SECRET="YOUR_CLOB_API_SECRET_BASE64"
CLOB_API_PASSPHRASE="YOUR_CLOB_PASSPHRASE"

# ------------------------------------------------------------------------------
# 3. GASLESS RELAYER (ZERO POL REQUIRED FOR ON-CHAIN MERGES & APPROVALS)
# ------------------------------------------------------------------------------
# Enables 100% sponsored gas for mergePositions and ERC-20 allowances
GASLESS_RELAYER_ENABLED=true
POLYMARKET_RELAYER_URL="https://relayer-v2.polymarket.com/submit"
RELAYER_API_KEY="01a01551-4415-7a54-a382-f09ad02bf050"
RELAYER_API_KEY_ADDRESS="0x832cBcdece2724eA0174c9fbE8D584b75C872163"

# ------------------------------------------------------------------------------
# 4. NETWORK & SERVICE IDENTIFIERS
# ------------------------------------------------------------------------------
CHAIN_ID=137

# Dedicated Polygon Mainnet JSON-RPC node URL (e.g. Alchemy, Infura, QuickNode)
POLYGON_RPC_URL="YOUR_POLYGON_RPC_PROVIDER_ENDPOINT"

# Official Polymarket REST & WSS Service Hosts
CLOB_API_SERVICE="CLOB REST v2 Production Service"
DATA_API_SERVICE="Data API v2 Production Service"
GAMMA_API_SERVICE="Gamma API Metadata Service"
CLOB_WSS_SERVICE="CLOB WebSocket Subscription Service"
POLYBOLT_WSS_SERVICE="PolyBolt High-Throughput Stream Service"

# External Market Data Streams (BTC leading signals & settlement oracle)
BINANCE_WSS_STREAM="Binance BTC/USDT 100ms L2 Order Book Stream"
CHAINLINK_ORACLE_FEED="Chainlink 60-Second TWAP Data Stream"

# ------------------------------------------------------------------------------
# 5. ON-CHAIN CONTRACT ADDRESSES (POLYGON MAINNET)
# ------------------------------------------------------------------------------
# Polymarket CTF Exchange v2 Contract
CTF_EXCHANGE_CONTRACT="0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

# Conditional Token Framework (CTF) Contract (for mergePositions)
CTF_CONTRACT="0x4D97DCdE725A8964c18F938002996A407217E759"

# Collateral Token: Bridged USDC.e on Polygon (Standard CTF Collateral)
USDC_COLLATERAL_CONTRACT="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# ------------------------------------------------------------------------------
# 6. QUANTITATIVE MODEL PARAMETERS (AVELLANEDA-STOIKOV)
# ------------------------------------------------------------------------------
# CARA risk aversion parameter (gamma)
ENGINE_GAMMA=0.15

# Order arrival intensity parameter (kappa baseline fallback)
ENGINE_KAPPA_BASE=12.0

# Savitzky-Golay Denoising (Window length m=5, polynomial degree d=2)
ENGINE_SG_WINDOW=5
ENGINE_SG_DEGREE=2

# Maximum Notional Dollar Capital allowed in single unhedged leg (V_max)
MAX_NOTIONAL_PER_LEG_USD=50.0

# Base order size in contract shares
BASE_ORDER_SIZE_UNITS=100.0

# Hysteresis Threshold (epsilon) - Minimum price displacement to trigger cancel/replace
# Set to native tick size ($0.01) to protect FIFO queue priority
HYSTERESIS_TICK_EPSILON=0.01

# Sub-$1.00 Maximum Combined Bid Target (Locks in >= $0.01 risk-free arbitrage spread)
MAX_COMBINED_BID_TARGET=0.99

# ------------------------------------------------------------------------------
# 7. OPERATIONAL SAFETY & EXECUTION FLAGS
# ------------------------------------------------------------------------------
# Set to false to simulate fills without dispatching real orders to the CLOB
DRY_RUN=true

# Keep-alive heartbeat ping interval in seconds (prevents stale standing orders)
HEARTBEAT_INTERVAL_SECS=5

# Seconds prior to 5-minute contract resolution to cancel standing quotes
CONTRACT_EXPIRY_CUTOFF_SECS=15

# Gas price ceiling on Polygon (Gwei) for CTF mergePositions calls
MAX_GAS_PRICE_GWEI=80
```

---

## 2. Official Polymarket Repositories

To provide direct source definitions and compiler-verified examples for your coding agent, clone these official repositories into a `references/` directory in your workspace:

### Repository Reference Directory

| Repository Name | Architectural Role | Key Internal Paths |
| :--- | :--- | :--- |
| **`Polymarket/rs-clob-client-v2`** | **Official Rust SDK (`polymarket_client_sdk_v2`).** Primary engine dependency. | • `src/clob/client.rs`: REST client and order builders.<br>• `src/ws/`: Real-time order book WebSocket handlers.<br>• `examples/clob_auth.rs`: Deriving L2 API keys via EOA signature. |
| **`Polymarket/ctf-exchange-v2`** | **Core exchange smart contracts on Polygon.** | • `contracts/CTFExchange.sol`: Mixin-based exchange engine.<br>• `contracts/mixins/Signatures.sol`: EOA (`0`), Proxy (`1`), and Safe (`2`) signature logic.<br>• `contracts/mixins/AssetOperations.sol`: Collateral escrow and token redemption. |
| **`Polymarket/polymarket-v2-external`** | **Next-generation Foundry contract suite.** | • `src/PositionManager.sol`: ERC-1155 position token management.<br>• `src/modules/oracles/`: Modular oracle resolution adapters (Chainlink / UMA). |
| **`Polymarket/ts-sdk`** | **Official TypeScript SDK Monorepo (`@polymarket/client`).** High-level workflow reference. | • `packages/client/`: Market discovery and multi-position portfolio management.<br>• `examples/scripts/`: Working interaction scripts. |
| **`Polymarket/py-sdk`** | **Official Python SDK (`polymarket-client`).** | • Reference implementation for batch combo position merging (`merge_multiple_positions`). |
| **`Polymarket/builder-signing-sdk`** | *Legacy Reference* | TypeScript client for generating builder attribution headers. |
| **`Polymarket/clob-client-v2`** | *Deprecated* | Legacy TypeScript client for CLOB v2 (superseded by `ts-sdk`). |
| **`Polymarket/py-builder-relayer-client`** | *Deprecated* | Legacy Python relayer client (superseded by `py-sdk`). |

---

## 3. Official Polymarket API Documentation & Endpoints

| Resource | Service Scope | Auth Scheme | Usage in 5-Minute Trading Engine |
| :--- | :--- | :--- | :--- |
| **Documentation Portal** | Official Polymarket Mintlify Docs | Public | Core engineering guides, market definitions, and order book rules. |
| **Machine Index (`llms.txt`)** | Token-optimized documentation index | Public | Condensed API overview designed for coding agents and LLM ingestion. |
| **CLOB REST API v2** | Central Limit Order Book Execution Engine | L1 / L2 Dual Auth | Order placement (`POST /order`), batch placement (`POST /orders`), cancel (`DELETE /order`, `DELETE /orders`), book snapshots (`GET /book`), and keep-alives (`POST /heartbeats`). |
| **Data API v2** | Public Analytics, Positions & PnL | Public | Real-time position tracking (`GET /v2/positions`), trade history (`GET /v2/trades`), on-chain activity logs (`GET /v2/activity`), and price history (`GET /v2/prices-history`). |
| **Data API OpenAPI Contract** | Machine-readable OpenAPI 3.0 schema | Public | Complete schema definition for all Data API v2 request and response structures. |
| **Data API Interactive Docs** | Interactive Swagger UI Explorer | Public | Interactive environment for testing queries and inspecting envelope formats. |
| **Gamma API** | Market Discovery & Event Metadata | Public | Event metadata & market discovery (`GET /events`, `GET /markets`). Used by the discovery actor to identify active 5-minute BTC contract IDs. |
| **Bridge API** | Cross-Chain Deposits & Withdrawals | Public | Collateral bridging across EVM chains (`POST /deposit`, `GET /supported-assets`). |
| **CLOB Market Streams** | Polymarket WebSocket Subscription Feeds | Public / Auth | WebSocket feed for Level-2 book deltas (`book`), price changes (`price_change`), and user fills (`orders`). |
| **PolyBolt Live Stream** | High-throughput live order book stream | Public | Low-latency real-time market data streaming channel. |
| **Trading Fees & Rebates** | [Upcoming Fee & Rebate Changes (Nov 20, 2026)](https://docs.polymarket.com/programs/fee-and-rebate-changes-november-2026) · [Library Fee Spec](../../../Library/03-exchanges-and-protocols/polymarket/05-fees-and-maker-rebates.md) | Public | Taker fee coefficient set to 0.05 for BTC 5m/15m (was 0.07) and 0.01 for other crypto. Makers pay 0% fees and earn 3%–15% maker rebates via 30-day weighted volume tiers ($wV$). |

---

## 4. Smart Contracts on Polygon Mainnet (Chain ID: 137)

These deployed smart contracts govern order matching and collateral redemption on Polygon.

* **Conditional Token Framework (CTF):** `0x4D97DCdE725A8964c18F938002996A407217E759`  
  *Interface:* `mergePositions(collateralToken, parentCollectionId, conditionId, partition, amount)`.  
  *Function:* Merges matching quantities of UP and DOWN ERC-1155 tokens to redeem underlying USDC.e collateral at a guaranteed 1:1 ratio.
* **CTF Exchange v2:** `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`  
  *Function:* Operator-matched CLOB settlement engine executing signed EIP-712 limit orders.
* **Collateral Token (Bridged USDC.e):** `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`  
  *Decimals:* 6. Standard collateral token used across all CTF binary prediction markets on Polymarket.

---

## 5. Academic Foundations & Mathematical Literature

1. **Marco Avellaneda & Sasha Stoikov (2006)**  
   *Title:* High-frequency trading in a limit order book  
   *Application:* Derives the closed-form Hamilton-Jacobi-Bellman (HJB) optimal spread $s^*$ and inventory reservation price $r_i$ under CARA utility preferences.
2. **Kevin Wang (arXiv)**  
   *Title:* Exploring Microstructural Dynamics in Cryptocurrency Limit Order Books: Better Inputs Matter More Than Stacking Another Hidden Layer  
   *Application:* Mathematical foundation for Station 1. Establishes that Savitzky–Golay local polynomial convolution filters high-frequency LOB noise without introducing phase lag.
3. **Feil, Nendel, et al. (2024)**  
   *Title:* Market Making in Binary Prediction Markets: A Comparison of Feil–Nendel and Avellaneda–Stoikov  
   *Application:* Adapts the Avellaneda-Stoikov model to bounded $[0, 1]$ binary outcomes and validates the sub-\$1.00 dual-bidding matrix.
4. **arXiv:2607.17991**  
   *Title:* Optimal Market Making in Prediction Markets  
   *Application:* Mathematical derivation of inventory skew penalties under finite contract resolution horizons.
5. **arXiv: Volatility-Aware Extreme Event Detection**  
   *Title:* Volatility-Aware Extreme Event Detection in High-Frequency Financial Markets  
   *Application:* Microstructural variance decay formulation for fixed-duration settlement intervals.
6. **PMC Journal of Financial Engineering**  
   *Title:* A reinforcement learning approach to improve the performance of the Avellaneda-Stoikov market-making algorithm  
   *Application:* Empirical estimation of dynamic Poisson arrival intensities ($\kappa$) across volatile crypto markets.

---

## 6. Oracle Settlement & External Feeds

* **Chainlink Data Streams (Cryptocurrency Feeds):**  
  *Documentation:* Chainlink Crypto Data Streams Reference & Crypto Standard v2 Schema  
  *Settlement Rule:* Polymarket 5-minute Bitcoin contracts resolve based on a **60-second Time-Weighted Average Price (TWAP)** generated by Chainlink Data Streams over the final minute $[T - 60\text{s}, T]$.
* **Binance Spot Depth Feeds (`btcusdt@depth20@100ms`):**  
  *Stream:* Binance Spot Depth 20 Level WebSocket  
  *Role:* Primary ultra-low-latency leading indicator providing 100ms order book imbalance and spot price momentum.

---

## 7. Third-Party Data Intelligence & Backtesting Tools

* **Codex API:**  
  *Endpoint:* Codex Prediction Markets GraphQL Engine  
  *Usage:* Unified GraphQL schema indexing historical Polymarket markets, OHLC probability candlesticks, and real-time trade event triggers (`onPredictionTradesCreated`).
* **PolyTest:**  
  *Service:* Specialized backtesting recorder and historical order book replay engine built specifically for 5-minute Up/Down prediction markets.

---

## 8. Complete Master Documentation Suite

All specifications are published and cross-linked in your Studio workspace:

* **01: Central Topology & Pipeline:** [`01-pipeline-overview.md`](./01-pipeline-overview.md)
* **02: Mathematical Derivations & Risk Models:** [`02-math-and-microstructure.md`](./02-math-and-microstructure.md)
* **03: Rust Architecture & Official API Endpoints:** [`03-rust-engine-implementation.md`](./03-rust-engine-implementation.md)
* **04: CTF Smart Contract Settlement:** [`04-ctf-settlement-lifecycle.md`](./04-ctf-settlement-lifecycle.md)
* **05: Operational Runbook & Paper Simulation:** [`05-operational-bootstrap-and-runbook.md`](./05-operational-bootstrap-and-runbook.md)
* **06: Developer Bibliography & Resource Hub (This Document):** [`06-developer-bibliography-and-resources.md`](./06-developer-bibliography-and-resources.md)
