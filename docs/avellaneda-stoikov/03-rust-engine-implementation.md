# Polymarket Rust Engine Implementation & Verified API Reference

## 1. Official Polymarket API v2 Specification

This specification references and adheres strictly to the official Polymarket CLOB and Data API v2 protocols as documented in Polymarket's engineering references and the official `rs-clob-client-v2` (`polymarket_client_sdk_v2`) repository.

### 1.1 Verified CLOB REST v2 Endpoints

* **CLOB Endpoint Target:** Polymarket CLOB Base Host (Production v2 / Fallback endpoints)
* **Transport:** HTTPS with JSON payloads.
* **Authentication Scheme:**
  * **L1 Authentication:** EIP-712 cryptographic signatures (`POLY_ADDRESS`, `POLY_SIGNATURE`, `POLY_TIMESTAMP`, `POLY_NONCE`).
  * **L2 Authentication:** Trading API key credentials (API Key, Passphrase, Signature, and Timestamp headers).

| Action | Method | Path | Required Headers / Params | Payload / Description |
| :--- | :--- | :--- | :--- | :--- |
| **Get Order Book** | `GET` | `/book` | `token_id={asset_id}` | Returns bids and asks sorted by price priority. |
| **Get Midpoint** | `GET` | `/midpoint` | `token_id={asset_id}` | Current mid-price between best bid and ask. |
| **Get Price** | `GET` | `/price` | `token_id={asset_id}&side={BUY,SELL}` | Current best clearing price for specified side (`BUY` or `SELL`). |
| **Get Spread** | `GET` | `/spread` | `token_id={asset_id}` | Absolute and percentage bid-ask spread. |
| **Post Single Order** | `POST` | `/order` | L2 Auth Headers | Submits a signed EIP-712 order structure. |
| **Post Batch Orders** | `POST` | `/orders` | L2 Auth Headers | Submits an array of signed limit orders atomically. |
| **Cancel Single Order** | `DELETE` | `/order` | L2 Auth Headers | Body: `{"orderID": "<order_hash>"}`. |
| **Cancel Batch Orders** | `DELETE` | `/orders` | L2 Auth Headers | Body: `{"orderIDs": ["<hash_1>", "<hash_2>"]}`. |
| **Cancel Market Orders** | `DELETE` | `/cancel-market-orders` | L2 Auth Headers | Cancels all active orders for a specific market asset. |
| **Cancel All Orders** | `DELETE` | `/cancel-all` | L2 Auth Headers | Global kill switch; drops all standing quotes immediately. |
| **Heartbeat Keep-Alive** | `POST` | `/heartbeats` | L2 Auth Headers | Automated keep-alive; triggers cancel-on-disconnect if dropped. |

### 1.2 Verified Data API v2 Endpoints

* **Data API Target:** Polymarket Data API v2 Host
* **Conventions:** Envelope responses `{ "data": [...], "pagination": { "next_cursor": "..." } }`.
* **Critical Requirement:** When querying positions via `/v2/positions`, you **must pass the account proxy wallet address** (`proxy_wallet`), not the signing EOA address.

| Action | Method | Path | Required Parameters |
| :--- | :--- | :--- | :--- |
| **List Positions** | `GET` | `/v2/positions` | `user={proxy_wallet_address}&market={condition_id}` |
| **Trade Execution History** | `GET` | `/v2/trades` | `maker_address={proxy_wallet}&limit=100` |
| **On-Chain Activity Feed** | `GET` | `/v2/activity` | `user={proxy_wallet}&type=MERGE,SPLIT,TRADE` |
| **Historical Price Candlesticks** | `GET` | `/v2/prices-history` | `market={condition_id}&interval=1m&fidelity=60` |

### 1.3 Streaming WebSockets (PolyBolt & CLOB Feeds)

* **Production WSS Feeds:** Polymarket WS Subscriptions and PolyBolt live v2 streaming endpoints.
* **Subscriptions:**
  * Market Depth: `{"action": "subscribe", "subscriptions": [{"topic": "book", "token_id": "<token_id>"}]}`
  * Price Shifts: `{"action": "subscribe", "subscriptions": [{"topic": "price_change", "token_id": "<token_id>"}]}`
  * User Order Updates: Authenticated channel streaming order state transitions (`FILLED`, `CANCELED`, `MATCHED`).

---

## 2. Station 1: Savitzky–Golay Filter Kernel

To eliminate allocation overhead on every incoming market book update, the convolution filter operates over a statically sized stack buffer.

```rust
// Pre-computed Savitzky-Golay convolution weights for window = 5, degree = 2
// Weights = [-3, 12, 17, 12, -3] / 35
const SG_WEIGHTS_M2_D2: [f64; 5] = [
    -0.08571428571428572,
     0.34285714285714286,
     0.48571428571428570,
     0.34285714285714286,
    -0.08571428571428572,
];

pub struct MidPriceDenoisingBuffer {
    buffer: [f64; 5],
    index: usize,
    count: usize,
}

impl MidPriceDenoisingBuffer {
    pub const fn new() -> Self {
        Self {
            buffer: [0.0; 5],
            index: 0,
            count: 0,
        }
    }

    #[inline(always)]
    pub fn push(&mut self, mid_price: f64) {
        self.buffer[self.index] = mid_price;
        self.index = (self.index + 1) % 5;
        if self.count < 5 {
            self.count += 1;
        }
    }

    #[inline(always)]
    pub fn get_smoothed_mid(&self) -> f64 {
        if self.count < 5 {
            return self.buffer[(self.index + 4) % 5];
        }

        let mut smoothed = 0.0;
        for i in 0..5 {
            let buffer_idx = (self.index + i) % 5;
            smoothed += SG_WEIGHTS_M2_D2[i] * self.buffer[buffer_idx];
        }
        smoothed
    }
}
```

*For mathematical derivations, see [02-math-and-microstructure.md §1](./02-math-and-microstructure.md#1-station-1-lob-microstructure-denoising).*

---


---

## 3. Station 2: Discrete Local TWAP & Variance Decay Accumulator

Polymarket's 5-minute Bitcoin UP/DOWN contracts settle against Chainlink's 60-second TWAP window ($[T - 60\text{s}, T]$). When operating without an institutional Chainlink PolyBolt credential, the engine computes the running 60-second TWAP locally from incoming ultra-low-latency spot trade prints (e.g. Binance BTC/USDT or PolyBolt standard `price.crypto` stream).

```rust
/// Station 2: Discrete Local TWAP & Volatility Decay Accumulator
/// Reconstructs the 60-second settlement benchmark locally from spot ticks.
#[derive(Debug, Clone)]
pub struct LocalTwapAccumulator {
    pub window_duration_secs: f64,
    pub start_time_ms: u64,
    pub last_update_ms: u64,
    pub cumulative_weighted_price: f64,
    pub current_spot: f64,
    pub reference_spot_inception: f64,
}

impl LocalTwapAccumulator {
    pub fn new(inception_time_ms: u64, reference_spot: f64, window_duration_secs: f64) -> Self {
        Self {
            window_duration_secs,
            start_time_ms: inception_time_ms,
            last_update_ms: inception_time_ms,
            cumulative_weighted_price: 0.0,
            current_spot: reference_spot,
            reference_spot_inception: reference_spot,
        }
    }

    /// Ingests a new spot tick update with timestamp in milliseconds
    #[inline(always)]
    pub fn update(&mut self, now_ms: u64, new_spot: f64) {
        if now_ms > self.last_update_ms {
            let dt = (now_ms - self.last_update_ms) as f64 / 1000.0;
            self.cumulative_weighted_price += self.current_spot * dt;
            self.last_update_ms = now_ms;
        }
        self.current_spot = new_spot;
    }

    /// Computes running TWAP over the elapsed window
    #[inline(always)]
    pub fn get_current_twap(&self, now_ms: u64) -> f64 {
        let total_dt = (now_ms.saturating_sub(self.start_time_ms)) as f64 / 1000.0;
        if total_dt <= 0.0 {
            return self.current_spot;
        }
        let current_dt = (now_ms.saturating_sub(self.last_update_ms)) as f64 / 1000.0;
        (self.cumulative_weighted_price + self.current_spot * current_dt) / total_dt
    }

    /// Computes effective decaying volatility sigma_eff^2(t) = sigma_spot^2 * ((T - t) / T)^2
    #[inline(always)]
    pub fn compute_effective_variance(
        &self,
        sigma_spot_sq: f64,
        time_remaining_secs: f64,
        contract_duration_secs: f64,
    ) -> f64 {
        if time_remaining_secs <= 0.0 || contract_duration_secs <= 0.0 {
            return 0.0;
        }
        let decay_ratio = (time_remaining_secs / contract_duration_secs).clamp(0.0, 1.0);
        sigma_spot_sq * decay_ratio * decay_ratio
    }
}
```

*For continuous mathematical derivation and terminal probability formulas, see [02-math-and-microstructure.md §2](./02-math-and-microstructure.md#2-station-2-chainlink-twap-resolution--variance-decay).*

---

## 4. Station 4–6: Pricing Engine & Dual-Bid Generation

Station 4 computes the optimal full spread $s^*$, Station 5 calculates the inventory-skewed reservation price $r_i$, and Station 6 generates the target Bids for both UP and DOWN contracts.

```rust
#[derive(Debug, Clone, Copy)]
pub struct DualBidTarget {
    pub bid_up: f64,
    pub bid_dn: f64,
    pub full_spread: f64,
    pub pair_acquisition_cost: f64,
}

#[inline(always)]
pub fn calculate_dual_bids(
    smoothed_mid: f64,
    kappa: f64,
    gamma: f64,
    sigma_eff_sq: f64,
    time_remaining: f64,
    net_inventory: f64,
) -> DualBidTarget {
    // Station 4: HJB Closed-Form Spread s*
    let full_spread = (2.0 / gamma) * (1.0 + gamma / kappa).ln();
    let half_spread = full_spread * 0.5;

    // Station 5: Reservation Price r_i
    let inventory_penalty = net_inventory * gamma * sigma_eff_sq * time_remaining;
    let reservation_price = smoothed_mid - inventory_penalty;

    // Station 6: Dual-Bid Placement (Everything is a Bid)
    let bid_up = reservation_price - half_spread;
    let bid_dn = 1.00 - (reservation_price + half_spread);

    DualBidTarget {
        bid_up,
        bid_dn,
        full_spread,
        pair_acquisition_cost: bid_up + bid_dn,
    }
}
```

---

## 5. Station 7: Dollar-Notional Risk Engine

Treating risk in absolute dollars rather than raw contract shares prevents asymmetrical losses when trading low-probability contracts.

```rust
#[derive(Debug, Clone, Copy)]
pub struct SizedQuote {
    pub price: f64,
    pub size: f64,
}

pub struct DollarNotionalRiskManager {
    pub max_notional_per_leg_usd: f64,
    pub base_order_size: f64,
}

impl DollarNotionalRiskManager {
    pub fn new(max_notional_usd: f64, base_order_size: f64) -> Self {
        Self {
            max_notional_per_leg_usd: max_notional_usd,
            base_order_size,
        }
    }

    #[inline(always)]
    pub fn compute_leg_allocation(&self, target_price: f64, current_inventory: f64) -> SizedQuote {
        if target_price <= 0.005 || target_price >= 0.995 {
            return SizedQuote { price: target_price, size: 0.0 };
        }

        // Current committed capital in dollars
        let committed_capital = current_inventory * target_price;
        let capital_remaining = (self.max_notional_per_leg_usd - committed_capital).max(0.0);

        // Linear inventory scaling factor
        let scaling_factor = (capital_remaining / self.max_notional_per_leg_usd).clamp(0.0, 1.0);
        let dynamic_size = (self.base_order_size * scaling_factor).floor();

        SizedQuote {
            price: (target_price * 100.0).round() / 100.0, // Discrete tick snap
            size: dynamic_size,
        }
    }
}
```

*For theoretical risk bounds, see [02-math-and-microstructure.md §7](./02-math-and-microstructure.md#7-station-7-absolute-dollar-notional-risk-management).*

---

## 6. Station 8: FIFO Hysteresis Decision Gate

Station 8 ensures limit orders are only canceled and replaced when market drift exceeds the native 1-cent tick threshold, protecting queue seniority.

```rust
#[derive(Debug, PartialEq)]
pub enum OrderAction {
    Hold,
    SubmitNew { price: f64, size: f64 },
    CancelAndReplace { old_order_id: String, new_price: f64, new_size: f64 },
}

pub struct HysteresisGate {
    pub epsilon: f64, // Native tick size = 0.01 USDC
}

impl HysteresisGate {
    pub fn new(epsilon: f64) -> Self {
        Self { epsilon }
    }

    #[inline(always)]
    pub fn evaluate(
        &self,
        active_order: Option<(&str, f64, f64)>, // (order_id, price, size)
        target_quote: SizedQuote,
    ) -> OrderAction {
        match active_order {
            None => {
                if target_quote.size > 0.0 {
                    OrderAction::SubmitNew {
                        price: target_quote.price,
                        size: target_quote.size,
                    }
                } else {
                    OrderAction::Hold
                }
            }
            Some((order_id, active_price, active_size)) => {
                let displacement = (target_quote.price - active_price).abs();

                // If displacement >= 1 tick, or if size scaling changed significantly
                if displacement >= self.epsilon || (target_quote.size == 0.0 && active_size > 0.0) {
                    OrderAction::CancelAndReplace {
                        old_order_id: order_id.to_string(),
                        new_price: target_quote.price,
                        new_size: target_quote.size,
                    }
                } else {
                    OrderAction::Hold
                }
            }
        }
    }
}
```

---

## 7. Official Rust SDK (`rs-clob-client-v2`) Integration

Below is an asynchronous order execution actor utilizing the official `polymarket_client_sdk_v2` client:

```rust
use polymarket_client_sdk_v2::clob::Client as ClobClient;
use polymarket_client_sdk_v2::clob::types::{OrderType, Side};
use std::sync::Arc;

pub struct OrderExecutionActor<S> {
    client: Arc<ClobClient<S>>,
    token_id_up: String,
    token_id_dn: String,
}

impl<S> OrderExecutionActor<S> {
    pub async fn execute_decision(
        &self,
        action: OrderAction,
        token_id: &str,
    ) -> Result<Option<String>, Box<dyn std::error::Error + Send + Sync>> {
        match action {
            OrderAction::Hold => Ok(None),
            OrderAction::SubmitNew { price, size } => {
                let order = self.client
                    .limit_order()
                    .token_id(token_id)
                    .price(price)
                    .size(size)
                    .side(Side::Buy)
                    .order_type(OrderType::GTC)
                    .build()?;

                let response = self.client.post_order(order).await?;
                Ok(Some(response.order_id))
            }
            OrderAction::CancelAndReplace { old_order_id, new_price, new_size } => {
                // Delete active resting order
                self.client.cancel_order(&old_order_id).await?;

                // Post replacement order if size remains positive
                if new_size > 0.0 {
                    let order = self.client
                        .limit_order()
                        .token_id(token_id)
                        .price(new_price)
                        .size(new_size)
                        .side(Side::Buy)
                        .order_type(OrderType::GTC)
                        .build()?;

                    let response = self.client.post_order(order).await?;
                    Ok(Some(response.order_id))
                } else {
                    Ok(None)
                }
            }
        }
    }
}
```

---

## 8. Cross-Document Navigation

* 📖 **Pipeline Topology & Overview:** [01-pipeline-overview.md](./01-pipeline-overview.md)
* 📐 **Mathematical Formulas & Proofs:** [02-math-and-microstructure.md](./02-math-and-microstructure.md)
* ⛓️ **CTF Smart Contract Settlement:** [04-ctf-settlement-lifecycle.md](./04-ctf-settlement-lifecycle.md)
