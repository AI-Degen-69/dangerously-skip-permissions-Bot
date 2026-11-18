# Up/Down Research Desk: Documentation Hub

Welcome to the documentation hub for **`dangerously-skip-permissions-bot`**.

This repository is an **empirical paper-trading desk and reverse-engineering lab** for Polymarket's 5-minute Bitcoin Up/Down markets. Its quantitative mission is **sub-$1.00 binary spread capture** ($p_{\text{UP}} + p_{\text{DN}} \le \$0.990$), resting bids on both outcome legs, managing queue ahead, and holding to settlement ($T=300\text{s}$) for guaranteed $1.00 cash redemption.

---

## 1. Desk Operations & Architecture

These documents cover operating, running, and configuring the active Python engine (`bot/`) and React/Vite dashboard (`src/app/`):

* 🏛️ **[System Architecture](./architecture.md):** Complete layout of the Python paper trading engine (shell + pure package architecture), tape recording pipelines, local loopback API, and frontend desk.
* 🚀 **[Runbook & Operations](./runbook.md):** Operational procedures for the paper loop, tape verification, kill-switch drills, paper redemption batches, and the live micro-size checklist.
* 🖥️ **[Desk User Guide](./usage-guide.md):** Comprehensive user manual for the 6 desk sections: Dashboard, Live Desk, A/B Lab, Config, Strategy, and Settings.

---

## 2. Quantitative Foundations & Exchange Protocol (`avellaneda-stoikov/`)

These documents detail the mathematical foundations, microstructure models, and on-chain contract interactions for 5-minute prediction markets:

* 📐 **[01. Pipeline Topology & System Overview](./avellaneda-stoikov/01-pipeline-overview.md):** The 8-station quantitative pipeline from LOB denoising to dual-bid execution and CTF merge.
* 🔢 **[02. Mathematical Foundations & Microstructure Models](./avellaneda-stoikov/02-math-and-microstructure.md):** Closed-form Hamilton-Jacobi-Bellman optimal spreads, TWAP variance decay integrals, and Poisson fill intensities.
* 🦀 **[03. Rust Engine Implementation & Official Endpoints](./avellaneda-stoikov/03-rust-engine-implementation.md):** High-throughput Tokio actor architectures, zero-allocation ringbuffers, and official Polymarket v2 API endpoints.
* ⛓️ **[04. CTF Settlement Lifecycle & Collateral Management](./avellaneda-stoikov/04-ctf-settlement-lifecycle.md):** Gnosis Conditional Token Framework on Polygon, `mergePositions` transaction bundling, gas scaling, and collateral reconciliation.
* 🛠️ **[05. Operational Bootstrap & Market Discovery](./avellaneda-stoikov/05-operational-bootstrap-and-runbook.md):** Dynamic Gamma market discovery, 300-second epoch rollover, simulation matching engine, and Gnosis Safe proxy auth.
* 📚 **[06. Developer Bibliography & Configuration](./avellaneda-stoikov/06-developer-bibliography-and-resources.md):** Production environment template, verified Polygon contract addresses, and academic literature index.

---

## 3. Reverse-Engineered Empirical Research (`leaderboard-traders/`)

This directory contains research reconstructed from top Polymarket 5-minute Bitcoin traders:

* 🔍 **[Leaderboard Traders Hub](./leaderboard-traders/README.md):** Reverse-engineering tools, trade pullers, and strategy analyzers.
* 📊 **Ledgers & Analysis:** Detailed empirical trade ledgers and mechanics write-ups for target wallet `0xc53375ff94e96100f2b30a4b5775db35218d69a9`.

---

## 4. Explanations & Presentations

* 🎨 **`docs/explanations/`:** Standalone interactive HTML explainers covering sizing simulations, maker vs. taker fee dynamics, verified-only tape math, and strategy breakdowns.
* 📽️ **`docs/pr-presentations/`:** Visual pull request presentations documenting feature additions and audit findings.

---

## 5. Relationship to the Centralized Knowledge Graph

This repository is closely connected to your centralized quantitative library at [`C:\Users\Tiger\Agents\Projects\AI Trading\Library`](../../Library/00-graph/README.md).

* **Repository Role:** Empirical paper testing, strategy parameter benchmarking (`STRATEGY_SETUPS`), tape replay, and live trading operations.
* **Library Role:** Master mathematical proofs, exchange-wide protocol specifications, verified credentials, and cross-venue latency arbitrage models.

### Key Library Cross-References

| Topic | Canonical Library Reference | Purpose |
| :--- | :--- | :--- |
| **Microstructure Model** | [Polymarket 5m BTC Microstructure Model](../../Library/01-foundations-and-models/polymarket-5m-btc-microstructure-model.md) | 300-second Jacobi diffusion and inventory decay. |
| **Strategy Mechanics** | [Binary Spread Capture Strategy](../../Library/02-strategies-and-alphas/binary-spread-capture.md) | Sub-$1.00 complementary pairing and fee barriers. |
| **Exchange Fees** | [Fee Schedule & Maker Rebates](../../Library/03-exchanges-and-protocols/polymarket/fees-and-maker-rebates.md) | Protocol fee curves ($0.05 \cdot p(1-p)$) and maker rebates. |
| **Account Auth** | [Account Credentials & Auth](../../Library/03-exchanges-and-protocols/polymarket/account-credentials-and-auth.md) | Live Gnosis Safe proxy addresses and static L2 keys. |
| **Smart Contracts** | [On-Chain CTF Contracts](../../Library/03-exchanges-and-protocols/polymarket/onchain-ctf-contracts.md) | Polygon CTF Exchange and Conditional Tokens ABIs. |
| **Auto-Cancel Safety** | [Market Making & Auto-Cancel](../../Library/03-exchanges-and-protocols/polymarket/market-making-and-auto-cancel.md) | Dead Man's Switch heartbeat (`PATCH /v1/trade/auto-cancel`). |
| **Rust Pipeline** | [Rust Actor Pipeline Architecture](../../Library/04-execution-and-infrastructure/rust-actor-pipeline-architecture.md) | High-performance Tokio execution actor engine. |
