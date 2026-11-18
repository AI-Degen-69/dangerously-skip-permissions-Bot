# Polymarket Bot: Operational Bootstrap, Market Discovery & Simulation Runbook

## 1. Overview and Operational Scope

This document provides the operational runbook and engineering implementation for the components connecting the quantitative pricing engine to the live Polymarket exchange environment:

1. **Environment & Secrets Configuration:** Management of L1 ECDSA keys, L2 HMAC trading credentials, RPC endpoints, and proxy wallet addressing.
2. **Dynamic Market Discovery & 5-Minute Contract Rollover:** Polling and streaming mechanics to identify active Bitcoin 5-minute contracts, resolve `condition_id` and outcome token IDs, and manage the transition between expiring and new 300-second epochs.
3. **Paper-Trading & Execution Simulation Engine:** A deterministic simulation actor to test order placement, hysteresis decisions, and fill mechanics against live WebSocket book updates without committing capital.
4. **End-to-End System Bootstrap:** Complete orchestrator wiring market ingestion, quantitative evaluation, order lifecycle management, and on-chain settlement.
5. **Polymarket Rust SDK Repository Guidance:** Best practices for integrating `polymarket_client_sdk_v2` (`rs-clob-client-v2`).

---

## 2. Environment & Secrets Specification

The bot requires two distinct credential tiers to operate across Polymarket's hybrid architecture: Layer 1 (Polygon blockchain) and Layer 2 (Off-chain CLOB matching engine).

### 2.1 Configuration Schema

| Environment Key | Category | Purpose | Example / Format |
| :--- | :--- | :--- | :--- |
| `SIGNER_SECRET_KEY` | Layer 1 Auth | Signing EOA private key (signs EIP-712 orders & auth headers) | 64-character hex string |
| `POLYGON_RPC_URL` | Layer 1 Node | High-throughput Polygon JSON-RPC HTTP endpoint | RPC provider URL (Alchemy / Infura / QuickNode) |
| `POLYGON_RPC_WSS` | Layer 1 Node | High-throughput Polygon JSON-RPC WebSocket stream | Dedicated WSS provider URL |
| `CHAIN_ID` | Layer 1 Network | Polygon PoS Mainnet chain identifier | `137` |
| `POLYMARKET_PROXY_ADDRESS` | Layer 1 Account | Polymarket Proxy / Gnosis Safe holding collateral & tokens | `0x...` 40-character hex address |
| `CLOB_API_KEY` | Layer 2 Auth | Off-chain API trading key UUID | Derived via L1 wallet signature |
| `CLOB_API_SECRET` | Layer 2 Auth | Base64 HMAC authentication secret | Derived via L1 wallet signature |
| `CLOB_API_PASSPHRASE`| Layer 2 Auth | API client passphrase | Derived via L1 wallet signature |
| `GAMMA_API_URL` | Market Discovery | Endpoint for querying active market events | Discovery host endpoint |
| `MAX_NOTIONAL_PER_LEG_USD` | Risk Engine | Hard dollar capital cap per outcome leg ($V_{\max}$) | `50.0` (USD) |
| `BASE_ORDER_SIZE_UNITS`| Risk Engine | Base capital allocation per placed Bid | `10.0` (USD) |
| `ENGINE_GAMMA`| Quantitative | CARA inventory risk aversion parameter ($\gamma$) | `0.15` |
| `HYSTERESIS_TICK_EPSILON` | Execution Gate | Native tick cancellation deadband ($\epsilon$) | `0.01` (USDC) |
| `DRY_RUN` | Operational Safety | Set to `true` for SIMULATION, `false` for PRODUCTION | `true` or `false` |
| `GASLESS_RELAYER_ENABLED` | On-Chain Settlement | Enables zero-gas meta-transactions via Relayer | `true` or `false` |
| `POLYMARKET_RELAYER_URL` | On-Chain Settlement | Endpoint for Polymarket Relayer v2 | `https://relayer-v2.polymarket.com/submit` |
| `RELAYER_API_KEY` | On-Chain Settlement | Relayer API authorization key | `01a01551-4415-7a54-a382-f09ad02bf050` |
| `RELAYER_API_KEY_ADDRESS` | On-Chain Settlement | Relayer proxy signer address | `0x832cBcdece2724eA0174c9fbE8D584b75C872163` |

### 2.2 Address & Signature Type Architecture

* **External Wallet EOA Setup (`POLYMARKET_SIGNATURE_TYPE=0`):**
  * When operating with a standard external wallet (MetaMask, Ledger, or private key `SIGNER_SECRET_KEY`), the developer address `0xeE3B778A783510BC833384919F709e3d2fee1624` is simultaneously the **signer**, the **maker**, and the **funder**.
  * The wallet holds the USDC.e collateral and ERC-1155 outcome tokens directly on Polygon.
  * In Data API v2 queries (`GET /v2/positions?user=0xeE3B778A783510BC833384919F709e3d2fee1624`), pass your EOA address directly.
* **Smart Contract Proxy Setup (`POLYMARKET_SIGNATURE_TYPE=1` or `2`):**
  * Used for Magic Link / Gnosis Safe setups. The `SIGNER_SECRET_KEY` signs EIP-712 orders, while a derived proxy contract holds inventory. In this mode, Data API v2 and `mergePositions` must target `POLYMARKET_PROXY_ADDRESS`.

---

## 3. Dynamic Market Discovery & 5-Minute Rollover

Bitcoin 5-minute prediction markets expire and resolve continuously every 300 seconds. An operational bot cannot rely on hardcoded contract addresses; it must dynamically discover active contracts and execute seamless rollovers.

### 3.1 Market Discovery Workflow

Every 5 minutes, Polymarket deploys or activates a new condition representing the next price window. Discovery operates via the Gamma API or Data API v2:

```text
[Cron / Timer: Every 30s]
          │
          ▼
┌──────────────────────────────────────────┐
│ Query Markets Discovery API              │
│ GET /markets?tag_slug=bitcoin&active=true│
└─────────────────┬────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────┐
│ Filter by Series & Expiration            │
│ Slug matches "btc-updown-5min-*"         │
│ Window: t_current < T_expiration         │
└─────────────────┬────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────┐
│ Extract Metadata:                        │
│ • condition_id                           │
│ • token_id_up (Asset ID for UP)          │
│ • token_id_dn (Asset ID for DOWN)        │
│ • resolution_timestamp (T)               │
│ • initial_reference_price S(t_0)         │
└─────────────────┬────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────┐
│ Epoch Transition / State Re-Init         │
│ Unsubscribe old WSS -> Subscribe new WSS │
│ Reset Savitzky-Golay Denoising Buffer    │
│ Set net inventory q = 0                  │
└──────────────────────────────────────────┘
```

### 3.2 Rust Market Discovery Implementation

```rust
use serde::Deserialize;
use reqwest::Client;

#[derive(Debug, Deserialize, Clone)]
pub struct MarketOutcomeToken {
    pub token_id: String,
    pub outcome: String, // "UP" or "DOWN" (or "Yes" / "No")
    pub price: f64,
}

#[derive(Debug, Deserialize, Clone)]
pub struct Active5MinMarket {
    pub condition_id: String,
    pub question: String,
    pub end_date_iso: String,
    pub token_id_up: String,
    pub token_id_dn: String,
    pub expiration_timestamp: i64,
    pub strike_price: Option<f64>,
}

pub struct MarketDiscoveryService {
    http_client: Client,
    discovery_base_url: String,
}

impl MarketDiscoveryService {
    pub fn new(discovery_base_url: &str) -> Self {
        Self {
            http_client: Client::new(),
            discovery_base_url: discovery_base_url.to_string(),
        }
    }

    /// Fetches the currently active 5-minute BTC contract expiring nearest in the future
    /// Extracts the Bitcoin strike price S(t_0) from the Gamma market question title
    pub fn extract_strike_price(question: &str) -> Option<f64> {
        let re = regex::Regex::new(r"(?i)(?:strike|above|at)\s*\$?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)").ok()?;
        let caps = re.captures(question)?;
        let raw_val = caps.get(1)?.as_str().replace(',', "");
        raw_val.parse::<f64>().ok()
    }

    pub async fn fetch_active_5min_btc_market(&self) -> Result<Active5MinMarket, Box<dyn std::error::Error + Send + Sync>> {
        let url = format!("{}/markets?active=true&closed=false&limit=50", self.discovery_base_url);
        let response = self.http_client.get(&url).send().await?.json::<serde_json::Value>().await?;

        let markets = response.as_array().ok_or("Invalid response: expected array of markets")?;

        let now_sec = chrono::Utc::now().timestamp();

        for m in markets {
            let question = m.get("question").and_then(|q| q.as_str()).unwrap_or("");
            let slug = m.get("slug").and_then(|s| s.as_str()).unwrap_or("");

            // Target BTC 5-minute UP/DOWN markets
            if (question.contains("Bitcoin") || question.contains("BTC")) 
                && (slug.contains("5m") || question.contains("5-Minute")) 
            {
                let end_date_str = m.get("endDate").and_then(|e| e.as_str()).unwrap_or("");
                let end_timestamp = chrono::DateTime::parse_from_rfc3339(end_date_str)
                    .map(|dt| dt.timestamp())
                    .unwrap_or(0);

                // Check that the contract expires within the next 300 seconds
                if end_timestamp > now_sec && end_timestamp <= now_sec + 360 {
                    let condition_id = m.get("conditionId").and_then(|c| c.as_str()).unwrap_or("").to_string();
                    let tokens = m.get("tokens").and_then(|t| t.as_array()).ok_or("Tokens array missing")?;

                    let mut token_id_up = String::new();
                    let mut token_id_dn = String::new();

                    for tok in tokens {
                        let outcome = tok.get("outcome").and_then(|o| o.as_str()).unwrap_or("");
                        let tid = tok.get("token_id").and_then(|t| t.as_str()).unwrap_or("").to_string();

                        if outcome.to_uppercase() == "UP" || outcome.to_uppercase() == "YES" {
                            token_id_up = tid;
                        } else if outcome.to_uppercase() == "DOWN" || outcome.to_uppercase() == "NO" {
                            token_id_dn = tid;
                        }
                    }

                    if !token_id_up.is_empty() && !token_id_dn.is_empty() {
                        let parsed_strike = Self::extract_strike_price(question);
                        return Ok(Active5MinMarket {
                            condition_id,
                            question: question.to_string(),
                            end_date_iso: end_date_str.to_string(),
                            token_id_up,
                            token_id_dn,
                            expiration_timestamp: end_timestamp,
                            strike_price: parsed_strike,
                        });
                    }
                }
            }
        }

        Err("No active 5-minute Bitcoin contract found currently trading".into())
    }
}
```

---

## 4. Paper-Trading & Execution Simulation Engine

Before placing live capital on the CLOB, the trading engine must support a zero-capital simulation mode. The paper-trading engine consumes live WebSocket order book and trade feeds, simulates passive limit order placement, and models executions deterministically against incoming trade prints.

### 4.1 Fill Simulation Rules

1. **Queue Priority Simulation:** When a simulated limit bid is placed at price $p$, it is assigned a virtual queue position equal to the resting volume already present at $p$ in the live book:
   $$V_{\text{ahead}} = \text{Depth}(p)$$
2. **Execution Trigger:** A simulated bid is filled if:
   * A trade executes at price $p_{\text{trade}} < p$ (market traded through the price level).
   * A trade executes at $p_{\text{trade}} = p$ with cumulative traded volume $\sum V_{\text{trades}} \ge V_{\text{ahead}}$ (queue cleared).
3. **Sub-\$1.00 Verification:** Fills are paired:
   $$\text{Pair Profit} = 1.00 - (p_{\text{fill}}^{\text{UP}} + p_{\text{fill}}^{\text{DN}})$$
4. **Fee Accounting (Nov 20, 2026 Fee Schedule):**
   * Passive maker orders pay **0.00%** fee.
   * If unhedged residual inventory is crossed via taker orders, the protocol applies the updated fee schedule:
     $$\text{Taker Fee} = \text{shares} \times 0.05 \times p \times (1 - p)$$
     Where `0.05` is the updated coefficient for BTC 5m/15m contracts (effective Nov 20, 2026 at 23:59 UTC; previously `0.07`). In addition, active market makers earn tiered maker rebates (3% to 15%) based on 30-day weighted volume ($wV$). See [05-fees-and-maker-rebates.md](../../../Library/03-exchanges-and-protocols/polymarket/05-fees-and-maker-rebates.md).

### 4.2 Simulated Execution Actor

```rust
use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct SimulatedOrder {
    pub order_id: String,
    pub token_id: String,
    pub price: f64,
    pub size: f64,
    pub side: String,
    pub volume_ahead: f64,
    pub created_at: i64,
}

pub struct PaperTradingEngine {
    pub active_orders: HashMap<String, SimulatedOrder>,
    pub filled_inventory_up: f64,
    pub filled_inventory_dn: f64,
    pub cost_basis_up: f64,
    pub cost_basis_dn: f64,
    pub realized_pnl_usdc: f64,
    pub total_pairs_merged: f64,
}

impl PaperTradingEngine {
    pub fn new() -> Self {
        Self {
            active_orders: HashMap::new(),
            filled_inventory_up: 0.0,
            filled_inventory_dn: 0.0,
            cost_basis_up: 0.0,
            cost_basis_dn: 0.0,
            realized_pnl_usdc: 0.0,
            total_pairs_merged: 0.0,
        }
    }

    /// Place or replace simulated limit order
    pub fn handle_order_action(
        &mut self,
        action: crate::OrderAction,
        token_id: &str,
        current_book_depth_at_price: f64,
    ) {
        match action {
            crate::OrderAction::Hold => {},
            crate::OrderAction::SubmitNew { price, size } => {
                let order_id = format!("sim_{}_{:.2}_{}", token_id, price, chrono::Utc::now().timestamp_millis());
                self.active_orders.insert(order_id.clone(), SimulatedOrder {
                    order_id,
                    token_id: token_id.to_string(),
                    price,
                    size,
                    side: "BUY".to_string(),
                    volume_ahead: current_book_depth_at_price,
                    created_at: chrono::Utc::now().timestamp_millis(),
                });
            },
            crate::OrderAction::Cancel { order_id } => {
                self.active_orders.remove(&order_id);
            },
            crate::OrderAction::CancelAndReplace { old_order_id, new_price, new_size } => {
                self.active_orders.remove(&old_order_id);
                if new_size > 0.0 {
                    let new_id = format!("sim_{}_{:.2}_{}", token_id, new_price, chrono::Utc::now().timestamp_millis());
                    self.active_orders.insert(new_id.clone(), SimulatedOrder {
                        order_id: new_id,
                        token_id: token_id.to_string(),
                        price: new_price,
                        size: new_size,
                        side: "BUY".to_string(),
                        volume_ahead: current_book_depth_at_price,
                        created_at: chrono::Utc::now().timestamp_millis(),
                    });
                }
            }
        }
    }

    /// Match resting simulated orders against public market trade events
    pub fn on_public_trade(&mut self, token_id: &str, trade_price: f64, trade_size: f64, is_up_token: bool) {
        let mut filled_order_ids = Vec::new();

        for (order_id, order) in self.active_orders.iter_mut() {
            if order.token_id == token_id {
                // If trade price hit or penetrated our bid
                if trade_price <= order.price {
                    if trade_price < order.price {
                        // Traded strictly through our price level: Instant Fill
                        filled_order_ids.push((order_id.clone(), order.size, order.price));
                    } else {
                        // Traded at our price: deplete volume ahead
                        order.volume_ahead -= trade_size;
                        if order.volume_ahead <= 0.0 {
                            filled_order_ids.push((order_id.clone(), order.size, order.price));
                        }
                    }
                }
            }
        }

        // Process completed fills
        for (id, size, price) in filled_order_ids {
            self.active_orders.remove(&id);
            if is_up_token {
                self.filled_inventory_up += size;
                self.cost_basis_up += size * price;
            } else {
                self.filled_inventory_dn += size;
                self.cost_basis_dn += size * price;
            }

            // Trigger simulated atomic merge if pairable inventory exists
            let pairable = self.filled_inventory_up.min(self.filled_inventory_dn);
            if pairable > 0.0 {
                // Exact Volume-Weighted Average Price (VWAP) calculation per leg
                let avg_cost_up = self.cost_basis_up / self.filled_inventory_up;
                let avg_cost_dn = self.cost_basis_dn / self.filled_inventory_dn;
                let pair_acquisition_cost = avg_cost_up + avg_cost_dn;

                // Profit calculation: 1.00 USDC collateral payout minus combined purchase costs
                let profit = pairable * (1.00 - pair_acquisition_cost);
                self.realized_pnl_usdc += profit;

                // Deduct merged inventory and cost basis proportionally
                self.cost_basis_up -= pairable * avg_cost_up;
                self.cost_basis_dn -= pairable * avg_cost_dn;
                self.filled_inventory_up -= pairable;
                self.filled_inventory_dn -= pairable;
                self.total_pairs_merged += pairable;

                println!(
                    "⚡ [SIMULATED MERGE] Merged {:.0} pairs. (Avg UP: ${:.3}, Avg DN: ${:.3}, Combined: ${:.3}) | Realized PnL: +${:.4} USDC",
                    pairable, avg_cost_up, avg_cost_dn, pair_acquisition_cost, self.realized_pnl_usdc
                );
            }
        }
    }

    /// Mark-to-market valuation for unmerged residual inventory
    pub fn get_unrealized_pnl(&self, current_mid_up: f64, current_mid_dn: f64) -> f64 {
        let mtm_up = (self.filled_inventory_up * current_mid_up) - self.cost_basis_up;
        let mtm_dn = (self.filled_inventory_dn * current_mid_dn) - self.cost_basis_dn;
        mtm_up + mtm_dn
    }
}
```

---


### 4.3 Baseline Model Telemetry Recorder (Pure Measurement Protocol)

To measure the raw, unadulterated Avellaneda-Stoikov model before introducing heuristics, the simulation harness records three baseline metrics:
1. **Requests Per Minute (RPM):** Total `CancelAndReplace` actions dispatched per 60-second window.
2. **$(T - t)$ Quote Skew Dynamics:** Tracking spread width $s^*(t)$ and reservation price $r_i(t)$ as the 300-second contract nears expiration.
3. **Paired-Fill Latency ($\Delta t_{\text{pair}}$):** Elapsed time between Leg A filling and Leg B filling under live order arrival.

```rust
use std::sync::atomic::{AtomicU64, Ordering};

pub struct BaselineTelemetry {
    pub cancel_replace_actions_60s: AtomicU64,
    pub window_start_time_ms: AtomicU64,
    pub leg_a_fill_timestamp_ms: AtomicU64,
    pub total_paired_fills: AtomicU64,
}

impl BaselineTelemetry {
    pub fn new() -> Self {
        Self {
            cancel_replace_actions_60s: AtomicU64::new(0),
            window_start_time_ms: AtomicU64::new(chrono::Utc::now().timestamp_millis() as u64),
            leg_a_fill_timestamp_ms: AtomicU64::new(0),
            total_paired_fills: AtomicU64::new(0),
        }
    }

    #[inline(always)]
    pub fn record_action(&self, action: &crate::OrderAction) {
        if let crate::OrderAction::CancelAndReplace { .. } = action {
            self.cancel_replace_actions_60s.fetch_add(1, Ordering::Relaxed);
        }

        let now = chrono::Utc::now().timestamp_millis() as u64;
        let start = self.window_start_time_ms.load(Ordering::Relaxed);
        if now - start >= 60_000 {
            let rpm = self.cancel_replace_actions_60s.swap(0, Ordering::Relaxed);
            self.window_start_time_ms.store(now, Ordering::Relaxed);
            println!("📊 [TELEMETRY] Order Dispatch Velocity: {} RPM (native tick deadband)", rpm);
        }
    }

    #[inline(always)]
    pub fn record_leg_fill(&self, is_paired: bool) {
        let now = chrono::Utc::now().timestamp_millis() as u64;
        if !is_paired {
            self.leg_a_fill_timestamp_ms.store(now, Ordering::Relaxed);
        } else {
            let leg_a_time = self.leg_a_fill_timestamp_ms.load(Ordering::Relaxed);
            if leg_a_time > 0 {
                let delta_ms = now - leg_a_time;
                self.total_paired_fills.fetch_add(1, Ordering::Relaxed);
                println!("⏱️ [TELEMETRY] Paired-Fill Latency: {:.2}s", delta_ms as f64 / 1000.0);
            }
        }
    }
}
```

## 5. End-to-End Orchestrator (`main.rs`)

The top-level binary initializes asynchronous runtime tasks using `tokio`, wires channels, and coordinates the 8-station pipeline.

```rust
use tokio::sync::mpsc;
use std::time::Duration;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    dotenv::dotenv().ok();
    println!("🚀 Starting Avellaneda-Stoikov Polymarket Market Maker...");

    let execution_mode = std::env::var("DRY_RUN").map(|v| if v.to_lowercase() == "false" { "PRODUCTION".to_string() } else { "SIMULATION".to_string() }).unwrap_or_else(|_| "SIMULATION".to_string());
    println!("⚙️ Execution Mode: {}", execution_mode);

    let discovery_url = std::env::var("GAMMA_API_URL").unwrap_or_else(|_| "http://localhost:8080".to_string());
    let discovery = MarketDiscoveryService::new(&discovery_url);

    // 1. Initial Market Discovery
    println!("🔍 Searching for active Bitcoin 5-minute contracts...");
    let market = match discovery.fetch_active_5min_btc_market().await {
        Ok(m) => {
            println!("✅ Discovered Market: {} (Condition: {})", m.question, m.condition_id);
            println!("   UP Token: {}", m.token_id_up);
            println!("   DN Token: {}", m.token_id_dn);
            m
        },
        Err(e) => {
            eprintln!("⚠️ Failed to discover market: {}. Retrying in 10s...", e);
            tokio::time::sleep(Duration::from_secs(10)).await;
            return Ok(());
        }
    };

    // 2. Initialize Internal Channels
    // Channel for market data events (L2 Book Deltas & Spot Prints)
    let (market_tx, mut market_rx) = mpsc::channel::<f64>(1000);

    // 3. Spawn Spot Price Monitor
    tokio::spawn(async move {
        let mut mock_mid = 0.505;
        loop {
            mock_mid += (rand::random::<f64>() - 0.5) * 0.004;
            mock_mid = mock_mid.clamp(0.10, 0.90);

            if market_tx.send(mock_mid).await.is_err() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    });

    // 4. Initialize Quantitative Components
    let mut denoising_buffer = MidPriceDenoisingBuffer::new();
    let risk_manager = DollarNotionalRiskManager::new(50.0, 10.0);
    let hysteresis_gate = HysteresisGate::new(0.01);
    let mut sim_engine = PaperTradingEngine::new();

    let mut active_bid_up: Option<(&str, f64, f64)> = None;
    let mut iteration = 0;

    println!("📊 Entering Pipeline Event Loop...");

    // 5. Main Execution Loop
    while let Some(raw_mid) = market_rx.recv().await {
        iteration += 1;

        // Station 1: LOB Denoising
        denoising_buffer.push(raw_mid);
        let smoothed_mid = denoising_buffer.get_smoothed_mid();

        // Stations 3 & 4: Liquidity Intensity & HJB Optimal Spread
        let kappa = 25.0; // Dynamically calibrated from book depth
        let gamma = 0.15;
        let sigma_eff_sq = 0.04;
        let time_remaining = 0.5; // Fractional window remaining
        let net_inventory = sim_engine.filled_inventory_up - sim_engine.filled_inventory_dn;

        // Station 4–6: Pricing
        let targets = calculate_dual_bids(
            smoothed_mid,
            kappa,
            gamma,
            sigma_eff_sq,
            time_remaining,
            net_inventory,
        );

        // Station 7: Dollar-Notional Sizing
        let sized_quote_up = risk_manager.compute_leg_allocation(targets.bid_up, sim_engine.filled_inventory_up);
        let sized_quote_dn = risk_manager.compute_leg_allocation(targets.bid_dn, sim_engine.filled_inventory_dn);

        // Station 8: Hysteresis Decision Gate
        let action_up = hysteresis_gate.evaluate(active_bid_up, sized_quote_up);

        if iteration % 20 == 0 {
            println!(
                "📈 Mid: {:.3} | Smoothed: {:.3} | Target Bids: UP {:.2} / DN {:.2} (Sum: {:.2}) | Action UP: {:?}",
                raw_mid, smoothed_mid, sized_quote_up.price, sized_quote_dn.price,
                sized_quote_up.price + sized_quote_dn.price, action_up
            );
        }

        // Apply action to execution engine
        if execution_mode == "SIMULATION" {
            sim_engine.handle_order_action(action_up, &market.token_id_up, 150.0);
        }
    }

    Ok(())
}
```

---

## 6. Official Polymarket Rust SDK Guidance

When instructing an autonomous AI coding agent to implement this project, follow these dependency and repository guidelines.

### 6.1 Cargo Dependency vs. Local Repository Reference

| Integration Dimension | Recommended Approach | Technical Rationale |
| :--- | :--- | :--- |
| **Project Build Dependency** | Add to `Cargo.toml` as a dependency: `polymarket_client_sdk_v2 = { version = "0.6", features = ["clob", "ws", "data"] }` (or via git repository url with features `["clob", "ws", "data"]`) | Ensures automated build reproducibility, compiler caching, and clean version pinning without manual build script entanglement. |
| **Agent Reference Directory** | Maintain a local copy or submodule of the `Polymarket/rs-clob-client-v2` repository in a reference folder (e.g., `references/rs-clob-client-v2`) | **Highly Recommended for AI Agents.** Because Polymarket's Rust SDK documentation is evolving, the repository's `examples/` directory contains canonical, compileable patterns for EIP-712 auth, WebSocket parsing, and response envelope handling that the agent can inspect directly. |

### 6.2 Key SDK Modules to Direct the Agent Toward

Inside the `references/rs-clob-client-v2` reference folder, instruct the agent to inspect:

1. `examples/clob_auth.rs`: Shows how to instantiate a client with an Alloy `LocalSigner` and derive L2 API credentials from an L1 Ethereum private key.
2. `examples/ws_market_data.rs`: Demonstrates subscribing to Level-2 order book snapshots and delta feeds.
3. `src/clob/types.rs`: Contains the concrete struct definitions for `Order`, `LimitOrder`, `OrderType::GTC`, and `Side::Buy`.
4. `src/data/positions.rs`: Demonstrates how to parse Data API v2 envelope payloads.

---

## 7. Knowledge Graph Cross-References

* 📖 **Central Architecture Hub:** [01-pipeline-overview.md](./01-pipeline-overview.md)
* 📐 **Mathematical Formulas & Microstructure Derivations:** [02-math-and-microstructure.md](./02-math-and-microstructure.md)
* 🦀 **Zero-Allocation Rust Pipeline Implementations:** [03-rust-engine-implementation.md](./03-rust-engine-implementation.md)
* ⛓️ **On-Chain CTF Settlement & Merging:** [04-ctf-settlement-lifecycle.md](./04-ctf-settlement-lifecycle.md)
