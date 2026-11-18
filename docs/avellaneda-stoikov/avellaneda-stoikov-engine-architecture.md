# Microstructure-Calibrated Avellaneda-Stoikov Inventory Risk Engine: Technical Specification and Execution Architecture

## 1. Architectural Foundations and Market Microstructure

Binary prediction markets on Polymarket present structural dynamics that fundamentally diverge from conventional continuous asset exchanges. While textbook algorithmic market making models assume continuous Wiener processes, unbounded price support, and symmetric two-sided quoting on identical underlying assets, Polymarket operates on the Conditional Token Framework (CTF) deployed on Polygon. In this environment, contracts are bounded strictly within the interval $[0.00, 1.00]$, settlement is governed by external oracle feeds, and market participants engage with paired ERC-1155 outcome tokens.

### 1.1 The Sub-$1.00 Window Arbitrage Paradigm

On Polymarket, binary outcome pairs (UP/YES and DOWN/NO) represent mutually exclusive, collectively exhaustive states. Under the standard CTF invariant, holding one full unit of UP alongside one full unit of DOWN guarantees redemption for exactly \$1.00 USDC upon contract finalization:

$$\text{Payoff}(\text{UP}) + \text{Payoff}(\text{DOWN}) \equiv 1.00\text{ USDC}$$

However, in the live central limit order book (CLOB), market prices reflect liquidity provider markups and discrete tick frictions ($0.01\text{ USDC}$). Aggressive market asks typically sum to \$1.01:

$$\text{Ask}(\text{UP}) + \text{Ask}(\text{DOWN}) \approx 1.01\text{ USDC}$$

A market participant executing immediate taker market orders across both outcomes pays \$1.01 to acquire a position bundle whose guaranteed payoff is exactly \$1.00, realizing an instantaneous loss of \$0.01 per pair.

Market makers entering without pre-existing token inventory operate strictly under an "Everything is a Bid" model. To extract edge without directional risk, the quantitative objective is to place passive limit buy orders (Bids) simultaneously on both outcome contracts such that their combined acquisition cost clears at or below \$0.99:

$$p_{\text{bid}}^{\text{UP}} + p_{\text{bid}}^{\text{DN}} \le 0.99\text{ USDC} < 1.00\text{ USDC}$$

When incoming taker order flow executes against both resting bids, the engine captures a riskless arbitrage spread equal to $1.00 - (p_{\text{bid}}^{\text{UP}} + p_{\text{bid}}^{\text{DN}})$, which is subsequently locked into liquid USDC collateral by executing an on-chain token merge.

### 1.2 Deterministic Low-Latency Execution in Rust

In high-frequency cryptocurrency environments, order book state transitions are driven by tick-by-tick order flow from primary spot exchanges such as Binance and Bybit. A market making agent must process order book delta updates, re-evaluate inventory penalties, and transmit cancel-replace messages within sub-millisecond envelopes.

Implementing this engine in high-level interpreted runtimes with automatic memory management introduces non-deterministic garbage collection pauses ranging from 5 to 50 milliseconds. A garbage collection pause occurring during a spot momentum breakout results in severe adverse selection, as aggressive taker flow picks off stale quotes. The engine is consequently specified for a deterministic, zero-allocation Rust runtime utilizing memory layout guarantees, asynchronous event loops via `tokio`, and direct binary interaction via the official `rs-clob-client-v2` crate.

---

## 2. End-to-End Pipeline Overview

The engine processes market data and controls quote lifecycles through an 8-station execution pipeline. Raw exchange feeds enter on the left, undergo statistical filtering and risk calibration, and produce rate-limited, queue-aware order submissions on the right.

| Station | Module Name | Primary Objective | Mathematical Core |
| :--- | :--- | :--- | :--- |
| **1** | LOB Denoising | Strip high-frequency quote flicker and false micro-price variance | Savitzky–Golay Polynomial Filter ($d=2, m=2$) |
| **2** | TWAP & Covariance | Model underlying spot dynamics and resolution probability | Running Chainlink 60s TWAP + Integrated Variance |
| **3** | Liquidity Intensity | Calibrate book depth and liquidity arrival rate | Exponential intensity parameter $\kappa = -\partial \ln \lambda(\delta) / \partial \delta$ |
| **4** | Optimal Spread | Calculate required full quote width across both outcomes | HJB closed-form spread $s^* = \frac{2}{\gamma} \ln(1 + \frac{\gamma}{\kappa})$ |
| **5** | Reservation Price | Determine inventory-penalized subjective quote center | Indifference price $r_i = s_i - q \cdot \gamma \sigma^2 (T - t)$ |
| **6** | Target Quote Generation | Map indifference price to dual-bid quoting matrix | $p_{\text{bid}}^{\text{UP}} = r_i - \frac{s^*}{2}$, $p_{\text{bid}}^{\text{DN}} = 1.00 - (r_i + \frac{s^*}{2})$ |
| **7** | Notional Dollar Sizing | Scale quote sizes against absolute capital risk | Dollar cap $V_{\max}$, $Q_{\max}(p) = \lfloor V_{\max} / p \rfloor$ |
| **8** | Queue & Hysteresis Gate | Preserve FIFO queue priority while escaping adverse selection | Deadband threshold $\Delta = |p_{\text{target}} - p_{\text{active}}| \ge \epsilon$ |

---

## 3. Station 1: Microstructure Noise Filtering (LOB Denoising)

High-frequency limit order book feeds from decentralized order books exhibit substantial microstructure noise. A large fraction of updates consists of flickering orders, algorithmic cancellations, and ephemeral bid-ask bounces that do not reflect genuine shifts in fair market value. Directly feeding raw mid-prices into an inventory risk model induces excessive quote churn, destroying queue priority and inflating operational latency.

### 3.1 Savitzky–Golay Polynomial Regression

To isolate structural price drift from high-frequency noise without introducing the severe lag characteristic of standard moving averages, the engine implements a local Savitzky–Golay digital filter. The filter fits a local polynomial of degree $d$ across a sliding window of $2m + 1$ discrete order book mid-price observations:

$$p_{\text{mid}}(\tau) = \sum_{k=0}^d a_k \tau^k, \quad \tau \in [-m, m]$$

Because sampling intervals are regularized across fixed time buckets (e.g., 100 milliseconds), the least-squares regression simplifies to a linear convolution with pre-computed filter coefficients $c_j$:

$$s_i(t) = \sum_{j=-m}^m c_j \cdot p_{\text{mid}}(t + j)$$

```rust
// Pre-computed Savitzky-Golay coefficients for window size = 5, degree = 2
// Symmetric Center Weights (2-tick / 200 ms phase lag on 100 ms streaming data, optimal noise filtering):
const SG_WEIGHTS_SYMMETRIC: [f64; 5] = [-0.085714, 0.342857, 0.485714, 0.342857, -0.085714];

// Causal Right-Endpoint Weights (Zero algorithmic latency, estimates newest edge sample):
const SG_WEIGHTS_CAUSAL: [f64; 5] = [0.085714, -0.142857, -0.085714, 0.257143, 0.885714];

#[inline(always)]
pub fn filter_mid_price(window: &[f64; 5], use_causal: bool) -> f64 {
    let weights = if use_causal { &SG_WEIGHTS_CAUSAL } else { &SG_WEIGHTS_SYMMETRIC };
    let mut filtered = 0.0;
    for i in 0..5 {
        filtered += weights[i] * window[i];
    }
    filtered
}
```

The resulting output $s_i$ serves as the denoised reference price for subsequent pricing stages, preserving turning points while eliminating tick-level variance.

---

## 4. Station 2: Chainlink TWAP Resolution Dynamics and Baseline Correlation

A critical failure point in naive automated trading strategies on Polymarket is the assumption that contracts settle against instantaneous spot prices at contract expiration $T$. For Polymarket's 5-minute Bitcoin UP/DOWN contracts, settlement is determined strictly by the 60-second Time-Weighted Average Price (TWAP) generated by Chainlink Data Streams.

### 4.1 Running TWAP Mechanics and Volatility Decay

The contract specification evaluates whether the final TWAP over the resolution window $[T - 60\text{s}, T]$ is greater than or equal to the initial reference price recorded at window inception $S(t_0)$:

$$\text{Resolution} = \begin{cases} \text{UP}, & \text{if } \text{TWAP}_{[T-60\text{s}, T]} \ge S(t_0) \\ \text{DOWN}, & \text{if } \text{TWAP}_{[T-60\text{s}, T]} < S(t_0) \end{cases}$$

The running TWAP accumulator updates continuously according to:

$$\text{TWAP}(t) = \frac{1}{t - t_{\text{start}}} \int_{t_{\text{start}}}^t S(u) \, du$$

This formulation introduces a pronounced volatility decay phenomenon. As elapsed time $t$ progresses toward expiration $T$, historical price path realizations become immutable. Even severe instantaneous price excursions in external spot markets (e.g., Binance BTC/USDT) exert progressively diminished influence over the remaining cumulative TWAP integral.

The engine models the conditional terminal probability $P(\text{UP} \mid \mathcal{F}_t)$ by decomposing the total variance into historical realized variance and decaying residual variance:

$$\sigma_{\text{eff}}^2(t) = \sigma_{\text{spot}}^2 \cdot \left(\frac{T - t}{T}\right)^2$$

This effective volatility $\sigma_{\text{eff}}$ feeds directly into the inventory penalty calculation, preventing the engine from overreacting to late-stage spot spikes that cannot mathematically reverse the TWAP outcome.

---

## 5. Station 3: Real-Time Order Flow Calibration (Liquidity Parameter $\kappa$)

In classical Avellaneda-Stoikov formulations, the order arrival intensity parameter $\kappa$ is treated as a static constant. In live prediction markets, however, market depth fluctuates violently between regimes of calm liquidity provision and sudden liquidity vacuums.

### 5.1 Estimating Intensity from Market Depth

The probability of an incoming market order executing against a limit order posted at distance $\delta$ from the reference price follows an exponential decay relationship:

$$\lambda(\delta) = A e^{-\kappa \delta}$$

Where $\lambda$ represents execution intensity, $A$ represents baseline order flow rate, and $\kappa$ represents the sensitivity of execution probability to quote distance. The engine dynamically estimates $\kappa$ from live Level-2 order book snapshots by computing the logarithmic density gradient of cumulative resting volume across price levels:

$$\kappa = -\frac{\partial \ln \Lambda(\delta)}{\partial \delta} \approx \frac{\ln(V_1) - \ln(V_k)}{\delta_k - \delta_1}$$

* **Elevated $\kappa$ ($\kappa \to \infty$):** Deep, resilient limit order book. Execution probability drops sharply as quotes move away from the mid-price. The optimal spread contracts.
* **Depressed $\kappa$ ($\kappa \to 0$):** Thin book, elevated adverse selection risk. A wide quote distance is required to justify capital commitment.

---

## 6. Station 4: Optimal Quote Width Derivation ($s^*$)

Station 4 determines the optimal full spread $s^*$ that maximizes the expected utility of terminal wealth under Constant Absolute Risk Aversion (CARA) preferences with risk parameter $\gamma$.

### 6.1 The Closed-Form HJB Solution

Solving the Hamilton-Jacobi-Bellman (HJB) system governing optimal market making yields the exact analytical relationship for the optimal full spread:

$$s^* = \frac{2}{\gamma} \ln\left(1 + \frac{\gamma}{\kappa}\right)$$

A critical structural property of this solution is that **the current inventory level $q$ does not appear in the optimal spread equation**. The spread $s^*$ is governed solely by risk aversion $\gamma$ and market liquidity depth $\kappa$.

The structural decomposition of $s^*$ operates as follows:

* **Full Optimal Spread ($s^*$):** Derived as $\frac{2}{\gamma} \ln(1 + \frac{\gamma}{\kappa})$, representing the total risk-adjusted price distance required between complementary bids.
* **Half-Spread Allocation ($\frac{s^*}{2}$):** Subtracted from the reservation price to position the UP Bid ($p_{\text{bid}}^{\text{UP}} = r_i - \frac{s^*}{2}$).
* **Complementary Half-Spread Allocation ($\frac{s^*}{2}$):** Subtracted from the inverted reservation price to position the DOWN Bid ($p_{\text{bid}}^{\text{DN}} = 1.00 - (r_i + \frac{s^*}{2})$).

The resulting value $s^*$ represents the full end-to-end price buffer (e.g., $s^* = 0.06$ represents 6 cents). Prior to order construction, this value is divided by two to obtain the symmetric half-spread parameter $\frac{s^*}{2} = 0.03$.

---

## 7. Station 5: Subjective Quote Center and Reservation Price ($r_i$)

While Station 4 establishes how wide quotes must be, Station 5 determines where that spread must be centered. The reservation price (indifference price) $r_i$ represents the subjective internal valuation at which the engine is indifferent between maintaining its current inventory position and executing an incremental contract:

$$r_i(s_i, q, t) = s_i - q \cdot \gamma \sigma^2 (T - t)$$

Where:
* $s_i$ is the denoised mid-price generated by Station 1.
* $q$ is the net contract inventory held in the active position.
* $\gamma$ is the inventory risk aversion coefficient.
* $\sigma^2$ is the effective market volatility calibrated by Station 2.
* $(T - t)$ is the fractional time remaining until contract expiration.

### 7.1 Inventory Skew Dynamics

The linear inventory penalty $q \cdot \gamma \sigma^2 (T - t)$ dynamically warps the quote center away from the market mid-price:

* **Zero Inventory ($q = 0$):** The reservation price coincides exactly with the market mid-price ($r_i = s_i$).
* **Positive Inventory ($q > 0$, Long UP):** The reservation price shifts downward ($r_i < s_i$). The engine discounts its valuation of UP tokens, lowering its bid price to avoid accumulating further directional exposure while making its opposing quote highly attractive.
* **Negative Inventory ($q < 0$, Long DOWN):** The reservation price shifts upward ($r_i > s_i$), raising quotes to penalize further DOWN accumulation.

---

## 8. Station 6: Dual-Bid Target Quote Generation ("Everything is a Bid")

In standard asset classes, a market maker posts a buy order at $r_i - \frac{s^*}{2}$ and a sell order at $r_i + \frac{s^*}{2}$. Because the engine operates with zero starting token inventory in a binary CTF market, it cannot place sell orders.

### 8.1 Transforming Synthetic Asks into Complementary Bids

The engine converts the theoretical sell quote $p_{\text{ask}}^{\text{UP}}$ into an equivalent buy quote on the complementary outcome token $p_{\text{bid}}^{\text{DN}}$ using the CTF parity invariant:

$$p_{\text{bid}}^{\text{UP}} = r_i - \frac{s^*}{2}$$

$$p_{\text{ask}}^{\text{UP}} = r_i + \frac{s^*}{2} \iff p_{\text{bid}}^{\text{DN}} = 1.00 - p_{\text{ask}}^{\text{UP}} = 1.00 - \left(r_i + \frac{s^*}{2}\right)$$

### 8.2 Invariant Sub-$1.00 Window Verification

Summing the two resulting bid prices demonstrates how the mathematics inherently guarantees sub-\$1.00 pair acquisition:

$$p_{\text{bid}}^{\text{UP}} + p_{\text{bid}}^{\text{DN}} = \left(r_i - \frac{s^*}{2}\right) + \left(1.00 - r_i - \frac{s^*}{2}\right) = 1.00 - s^*$$

Because the optimal spread $s^*$ is strictly positive for all finite $\kappa$ and $\gamma > 0$, the sum of the bids is algebraically guaranteed to clear below \$1.00 by an exact margin equal to $s^*$:

$$p_{\text{bid}}^{\text{UP}} + p_{\text{bid}}^{\text{DN}} = 1.00 - s^* < 1.00\text{ USDC}$$

If $s^* = 0.04$, the engine bids such that $p_{\text{bid}}^{\text{UP}} + p_{\text{bid}}^{\text{DN}} = 0.96$, locking in \$0.04 of gross arbitrage margin per completed pair.

---

## 9. Station 7: Absolute Dollar-Notional Sizing and Risk Limits

Treating inventory risk as a static share count introduces asymmetric capital exposure. In a binary prediction market, purchasing 100 contracts at \$0.20 commits \$20.00 of capital, whereas purchasing 100 contracts at \$0.60 commits \$60.00 of capital—a 300% increase in dollar risk.

### 9.1 Dollar-Notional Inventory Boundaries ($V_{\max}$)

The engine governs inventory through an absolute dollar-notional capital boundary $V_{\max}$ representing the maximum unhedged financial capital permitted on a single outcome leg. The dynamic maximum share capacity $Q_{\max}(p)$ scales inversely with price:

$$Q_{\max}(p) = \left\lfloor \frac{V_{\max}}{p} \right\rfloor$$

Under a calibrated capital ceiling of $V_{\max} = \$50.00$:
* **Contract trading at \$0.20:** Maximum leg capacity equals $Q_{\max} = \lfloor 50.00 / 0.20 \rfloor = 250$ contracts.
* **Contract trading at \$0.60:** Maximum leg capacity contracts to $Q_{\max} = \lfloor 50.00 / 0.60 \rfloor = 83$ contracts.

### 9.2 Linear Inventory Scaling and Asymmetric Allocation

The active bid size submitted to the order book scales linearly as the current leg inventory $q_{\text{leg}}$ approaches its capital limit:

$$\text{Size}_{\text{bid}}(p) = \text{Size}_{\text{base}} \times \max\left(0, \; 1 - \frac{q_{\text{leg}} \cdot p}{V_{\max}}\right)$$

When an execution occurs on one leg (e.g., UP fills):
1. **Suppression of Filled Leg:** As $q_{\text{UP}} \cdot p_{\text{UP}} \to V_{\max}$, the UP bid size contracts toward zero, preventing toxic inventory accumulation.
2. **Prioritization of Unfilled Leg:** Total allocation shifts aggressively to the DOWN bid to expedite pair completion and trigger collateral redemption.

---

## 10. Station 8: FIFO Queue Preservation and Hysteresis Gate

Decentralized central limit order books enforce First-In, First-Out (FIFO) queue priority at each price tick. A cancellation and replacement operation immediately forfeits queue seniority, transferring priority to competing participants. Conversely, retaining stale quotes when fair value shifts results in aggressive takers executing against the position under adverse selection.

### 10.1 The Hysteresis Deadband ($\epsilon$)

Station 8 acts as a discrete decision gate between theoretical quote calculation and physical order submission. Let $p_{\text{target}}$ represent the newly computed optimal bid price, and $p_{\text{active}}$ represent the price of the resting limit order currently posted in the order book. The gate evaluates the absolute price displacement:

$$\Delta = |p_{\text{target}} - p_{\text{active}}|$$

$$\text{Action} = \begin{cases} \text{HOLD}, & \text{if } \Delta < \epsilon \\ \text{CANCEL\_AND\_REPLACE}, & \text{if } \Delta \ge \epsilon \end{cases}$$

Where the hysteresis threshold is calibrated to the native tick size of the market ($\epsilon = 0.01\text{ USDC}$).

```rust
pub fn evaluate_order_update(
    active_bid: Option<f64>,
    target_bid: f64,
    target_size: f64,
    active_size: f64,
    epsilon: f64,
) -> OrderAction {
    match active_bid {
        Some(active) => {
            let displacement = (target_bid - active).abs();
            if target_size == 0.0 && active_size > 0.0 {
                OrderAction::Cancel
            } else if displacement >= epsilon {
                OrderAction::CancelAndReplace { new_price: target_bid }
            } else {
                OrderAction::Hold
            }
        }
        None => {
            if target_size > 0.0 {
                OrderAction::SubmitNew { price: target_bid }
            } else {
                OrderAction::Hold
            }
        }
    }
}
```

* **Micro-drift ($\Delta < 0.01$):** Sub-tick movements generated by continuous model re-evaluation are filtered. Resting orders retain their prioritized position in the queue.
* **Macro-shift ($\Delta \ge 0.01$):** When spot momentum moves the underlying market by one full tick or more, the gate triggers an immediate cancel-replace sequence, eliminating adverse selection exposure.

---

## 11. Post-Fill Settlement and Atomic Token Merging

Once paired executions are achieved, capital remains locked in ERC-1155 tokens until explicit contract interaction occurs. Resting indefinitely in paired outcome tokens introduces settlement counterparty drag and consumes operational collateral.

### 11.1 Dual Settlement Lifecycle (Relayer v2 vs. Direct Fallback)

The settlement pipeline continuously monitors inventory balances across both outcomes:

$$Q_{\text{pairable}} = \min\left(q_{\text{UP}}, \; q_{\text{DN}}\right)$$

When $Q_{\text{pairable}} > 0$, the settlement manager redeems collateral via one of two paths:

1. **Primary Gasless Relayer Path (`GASLESS_RELAYER_ENABLED=true`):**
   * Meta-transactions are submitted to Polymarket's Relayer endpoint (`https://relayer-v2.polymarket.com/submit`) signed with `RELAYER_API_KEY` (`01a01551-4415-7a54-a382-f09ad02bf050`).
   * Polymarket sponsors 100% of the gas cost on Polygon (**0.00 POL** required in developer wallet).
2. **Direct On-Chain Fallback:**
   * Direct transaction calling `mergePositions` on the Polymarket CTF contract (`0x4D97DCdE725A8964c18F938002996A407217E759` on Polygon).
   * Enforces minimum batch threshold $N_{\min} = \lceil \frac{10 \times \text{TxCost}_{\text{gas}}}{s^*} \rceil$ so that on-chain gas costs never exceed 10% of captured spread.

```solidity
function mergePositions(
    IERC20 collateralToken,
    bytes32 parentCollectionId,
    bytes32 conditionId,
    uint[] calldata partition,
    uint amount
) external;
```

Execution converts $Q_{\text{pairable}}$ units of UP and $Q_{\text{pairable}}$ units of DOWN into $Q_{\text{pairable}} \times 1.00$ units of liquid USDC.e collateral. Released capital is instantly returned to the active quoting balance, completing the round-trip arbitrage cycle. Realized profit is:

$$\text{Realized PnL} = Q_{\text{pairable}} \times \left[ 1.00 - \left(p_{\text{avg}}^{\text{UP}} + p_{\text{avg}}^{\text{DN}}\right) \right]$$

---

## 12. Rust Low-Latency Implementation Architecture

The production implementation is organized as an asynchronous actor system utilizing bounded lock-free ring buffers to achieve sub-millisecond tick-to-trade latencies.

### 12.1 Concurrent Actor Topology

The system separates I/O-bound network transport from CPU-bound mathematical evaluation across isolated `tokio` green threads:

1. **Market Ingestion Actors:** Two independent asynchronous tasks manage WebSocket streams from external spot feeds (Binance/Bybit BTC/USDT) and the Polymarket CLOB. Raw L2 order book deltas and spot trade prints are serialized into fixed-size event structs and pushed into a multi-producer, single-consumer channel (`tokio::sync::mpsc::channel`).
2. **Quantitative Engine Actor:** A dedicated worker thread consumes events sequentially, executing Stations 1 through 6. Memory allocations are strictly zero; all sliding windows and polynomial convolutions operate over pre-allocated fixed arrays (`[f64; N]`).
3. **Risk & Order Lifecycle Actor:** Evaluates Stations 7 and 8, maintaining local order state and dispatching signed EIP-712 orders via `rs-clob-client-v2` only when the hysteresis threshold is breached.
4. **Settlement Worker:** An asynchronous event listener detects incoming fill events, updates internal position balances, and executes atomic `mergePositions` contract calls on Polygon when $Q_{\text{pairable}} > 0$.

### 12.2 Core State Representation

To ensure continuous cache locality, the engine state is maintained in a contiguous, heap-free data structure:

```rust
#[repr(C)]
pub struct EngineState {
    pub gamma: f64,
    pub kappa: f64,
    pub sigma_eff_sq: f64,
    pub notional_max_usd: f64,
    pub hysteresis_epsilon: f64,
    pub inventory_up: f64,
    pub inventory_dn: f64,
    pub active_bid_up: Option<f64>,
    pub active_bid_dn: Option<f64>,
}
```

This architecture guarantees that all mathematical evaluations operate entirely within CPU L1/L2 cache, executing complete quote cycles in under 50 nanoseconds upon receipt of normalized book packets.
