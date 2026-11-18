# Quantitative Microstructure & Mathematical Foundations

## 1. Station 1: LOB Microstructure Denoising

High-frequency limit order books in prediction markets suffer from severe microstructure noise: micro-flickering quotes, rapid cancellations, and transient bid-ask bounces. Passing raw mid-prices into an inventory risk engine induces excessive quote churn, destroying queue priority.

### 1.1 Savitzky–Golay Polynomial Formulation

To isolate structural price drift from high-frequency noise without introducing the severe phase lag inherent in exponential moving averages, the engine implements a local Savitzky–Golay digital smoothing filter. 

Given a discrete series of mid-price samples $p_{\text{mid}}(\tau)$ sampled at regular time intervals $\Delta t = 100\text{ ms}$, we fit a local polynomial of degree $d$ across a symmetric sliding window of length $2m + 1$:

$$p_{\text{mid}}(\tau) = \sum_{k=0}^d a_k \tau^k, \quad \tau \in [-m, m]$$

Minimizing the sum of squared residuals:

$$\mathcal{E} = \sum_{\tau=-m}^m \left( p_{\text{mid}}(\tau) - \sum_{k=0}^d a_k \tau^k \right)^2$$

Because the evaluation occurs at the center of the window ($\tau = 0$), the smoothed mid-price $s_i(t)$ simplifies to an exact linear convolution with pre-computed coefficients $c_j$:

$$s_i(t) = \sum_{j=-m}^m c_j \cdot p_{\text{mid}}(t + j)$$

For a window parameter $m = 2$ ($2m + 1 = 5$ points) and polynomial degree $d = 2$, the convolution weights are given by the analytical projection matrix:

$$c = \frac{1}{35} \begin{bmatrix} -3 & 12 & 17 & 12 & -3 \end{bmatrix} \approx \begin{bmatrix} -0.085714 & 0.342857 & 0.485714 & 0.342857 & -0.085714 \end{bmatrix}$$

*For the zero-allocation Rust implementation, see [03-rust-engine-implementation.md §2](./03-rust-engine-implementation.md#2-station-1-savitzkygolay-filter-kernel).*

---

## 2. Station 2: Chainlink TWAP Resolution & Variance Decay

Polymarket's 5-minute Bitcoin UP/DOWN contracts settle against the 60-second Time-Weighted Average Price (TWAP) provided by Chainlink Data Streams, evaluated over the final minute $[T - 60\text{s}, T]$ relative to the reference spot price at inception $S(t_0)$.

### 2.1 TWAP Accumulator & Terminal Probability

The contract settlement rule is binary:

$$\text{Resolution} = \begin{cases} \text{UP}, & \text{if } \text{TWAP}_{[T-60\text{s}, T]} \ge S(t_0) \\ \text{DOWN}, & \text{if } \text{TWAP}_{[T-60\text{s}, T]} < S(t_0) \end{cases}$$

The running TWAP accumulator updates continuously:

$$\text{TWAP}(t) = \frac{1}{t - t_{\text{start}}} \int_{t_{\text{start}}}^t S(u) \, du$$

### 2.2 Volatility Decay Function

As elapsed time $t$ progresses toward expiration $T$, realized spot prints become immutable. The remaining variance of the terminal TWAP decays quadratically with time:

$$\sigma_{\text{eff}}^2(t) = \sigma_{\text{spot}}^2 \cdot \left( \frac{T - t}{T} \right)^2$$

Where:
* $\sigma_{\text{spot}}$ is the instantaneous annualized volatility of the Bitcoin underlying spot market.
* $T - t$ is the fractional time remaining in the contract epoch.

This effective variance $\sigma_{\text{eff}}^2$ directly scales the inventory penalty in Station 5, preventing the engine from overreacting to late-stage spot fluctuations that cannot mathematically alter the terminal TWAP outcome.

---

## 3. Station 3: Order Flow Arrival Intensity ($\kappa$)

The probability of an incoming taker market order filling a passive quote placed at distance $\delta$ from the reference price follows an exponential Poisson arrival model:

$$\lambda(\delta) = A e^{-\kappa \delta}$$

Where:
* $\lambda(\delta)$ is the Poisson arrival rate of market orders.
* $A$ is the baseline order arrival intensity.
* $\kappa$ is the liquidity decay parameter (book depth elasticity).

### 3.1 Empirical Estimation from Level-2 Depth

Rather than assuming a static constant, $\kappa$ is calibrated dynamically from the live Level-2 order book depth profile by evaluating the logarithmic volume gradient across cumulative price levels:

$$\kappa = -\frac{\partial \ln \Lambda(\delta)}{\partial \delta} \approx \frac{\ln(V_1) - \ln(V_k)}{\delta_k - \delta_1}$$

* **High $\kappa$ ($\kappa \to \infty$):** Thick, resilient order book. Fill probability drops sharply as quotes move away from the mid-price. The optimal spread contracts.
* **Low $\kappa$ ($\kappa \to 0$):** Fragile, thin book. Execution risk is high, requiring a wider spread buffer to justify resting capital.

---

## 4. Station 4: Optimal Spread Derivation ($s^*$)

Station 4 determines the optimal full spread $s^*$ that maximizes the expected utility of terminal wealth under Constant Absolute Risk Aversion (CARA) preferences:

$$U(W) = -e^{-\gamma W}$$

Where $\gamma > 0$ represents the absolute risk aversion coefficient.

### 4.1 Closed-Form Solution of the HJB System

Solving the Hamilton-Jacobi-Bellman (HJB) value function for the market maker's optimal control problem yields the closed-form equation for the full spread:

$$s^* = \frac{2}{\gamma} \ln\left( 1 + \frac{\gamma}{\kappa} \right)$$

Key structural properties:
1. **Inventory Independence:** The optimal full spread $s^*$ is completely independent of current inventory $q$. Inventory affects the *center* of the quote (Station 5), not the *width* of the quote.
2. **Half-Spread Allocation:** The parameter $s^*$ is the total end-to-end buffer. Prior to order submission, it is split into symmetric halves:
   $$\delta_{\text{half}} = \frac{s^*}{2} = \frac{1}{\gamma} \ln\left( 1 + \frac{\gamma}{\kappa} \right)$$

*For the pipeline integration, see [01-pipeline-overview.md §2](./01-pipeline-overview.md#2-the-8-station-pipeline-topology).*

---

## 5. Station 5: Reservation Price & Inventory Skew ($r_i$)

The reservation price (or indifference price) $r_i$ represents the internal subjective valuation at which the market maker is indifferent between holding their current inventory and executing an incremental contract:

$$r_i(s_i, q, t) = s_i - q \cdot \gamma \sigma_{\text{eff}}^2 (T - t)$$

Where:
* $s_i$ is the denoised mid-price from Station 1.
* $q$ is the net unhedged contract inventory ($q > 0$ for excess UP, $q < 0$ for excess DOWN).
* $\gamma$ is the inventory risk aversion parameter.
* $\sigma_{\text{eff}}^2$ is the decayed effective volatility from Station 2.
* $T - t$ is the remaining duration of the contract.

### 5.1 Skew Dynamics Under Exposure

* **Neutral State ($q = 0$):** $r_i = s_i$. Quoting is centered exactly on the filtered mid-price.
* **Long Inventory ($q > 0$):** $r_i < s_i$. The reservation price drops, suppressing the Bid price to repel further UP accumulation while shifting the complementary quote closer to the market to accelerate offloading.
* **Short Inventory ($q < 0$):** $r_i > s_i$. The reservation price rises, penalizing further DOWN accumulation.

---

## 6. Station 6: Dual-Bid Quoting Matrix

Because the market maker begins with zero inventory, standard sell orders (Asks) cannot be placed. The engine maps the theoretical Ask quote into an equivalent limit buy order on the complementary contract via the CTF parity invariant:

$$p_{\text{bid}}^{\text{UP}} = r_i - \frac{s^*}{2}$$

$$p_{\text{ask}}^{\text{UP}} = r_i + \frac{s^*}{2} \iff p_{\text{bid}}^{\text{DN}} = 1.00 - p_{\text{ask}}^{\text{UP}} = 1.00 - \left( r_i + \frac{s^*}{2} \right)$$

### 6.1 Invariant Proof of Sub-$1.00 Arbitrage

Summing the two resulting target bids demonstrates that the pair acquisition cost is algebraically guaranteed to clear below $1.00:

$$p_{\text{bid}}^{\text{UP}} + p_{\text{bid}}^{\text{DN}} = \left( r_i - \frac{s^*}{2} \right) + \left( 1.00 - r_i - \frac{s^*}{2} \right) = 1.00 - s^*$$

Because $\kappa > 0$ and $\gamma > 0$, the optimal spread $s^*$ is strictly positive. Therefore:

$$p_{\text{bid}}^{\text{UP}} + p_{\text{bid}}^{\text{DN}} = 1.00 - s^* < 1.00\text{ USDC}$$

For example, when $s^* = 0.04$, the engine bids such that $p_{\text{bid}}^{\text{UP}} + p_{\text{bid}}^{\text{DN}} = 0.96$, locking in a guaranteed $0.04 gross margin per paired share upon redemption.

---

## 7. Station 7: Absolute Dollar-Notional Risk Management

Treating inventory risk as a static share count introduces dangerous capital asymmetry in prediction markets. In a contract trading near boundaries, 100 contracts at $0.20 represent $20.00 of capital risk, while 100 contracts at $0.60 represent $60.00 of capital risk—a 300% increase in dollar exposure.

### 7.1 Dollar-Notional Inventory Boundaries ($V_{\max}$)

The engine enforces an absolute dollar-notional capital boundary $V_{\max}$, representing the maximum unhedged financial capital permitted on any single outcome leg. The dynamic maximum share capacity $Q_{\max}(p)$ scales inversely with price:

$$Q_{\max}(p) = \left\lfloor \frac{V_{\max}}{p} \right\rfloor$$

Under a calibrated ceiling of $V_{\max} = \$50.00$:
* **Contract at $0.20:** Maximum leg capacity $Q_{\max} = \lfloor 50.00 / 0.20 \rfloor = 250$ contracts.
* **Contract at $0.60:** Maximum leg capacity contracts to $Q_{\max} = \lfloor 50.00 / 0.60 \rfloor = 83$ contracts.

### 7.2 Linear Scaling and Pair Completion Acceleration

The quote size submitted to the order book scales linearly with remaining capital capacity:

$$\text{Size}_{\text{bid}}(p) = \text{Size}_{\text{base}} \times \max\left( 0, \; 1 - \frac{q_{\text{leg}} \cdot p}{V_{\max}} \right)$$

When an unhedged execution occurs on one leg:
1. **Suppression:** As $q_{\text{UP}} \cdot p_{\text{UP}} \to V_{\max}$, the UP bid size contracts toward zero, preventing toxic inventory accumulation.
2. **Prioritization:** Available capital is allocated to the DOWN bid to expedite pair completion and trigger on-chain collateral redemption.

*For the Rust implementation, see [03-rust-engine-implementation.md §5](./03-rust-engine-implementation.md#5-station-7-dollar-notional-risk-engine).*

---

## 8. Station 8: Queue Preservation & Hysteresis Gate

Decentralized central limit order books enforce strict First-In, First-Out (FIFO) queue priority at each price tick. Canceling and replacing an order forfeits queue seniority. Conversely, maintaining stale quotes during rapid market drift leads to adverse selection by aggressive takers.

### 8.1 The Deadband Hysteresis Threshold ($\epsilon$)

Station 8 evaluates the absolute displacement between the newly computed target bid $p_{\text{target}}$ and the active order resting in the book $p_{\text{active}}$:

$$\Delta = |p_{\text{target}} - p_{\text{active}}|$$

$$\text{Decision} = \begin{cases} \text{HOLD}, & \text{if } \Delta < \epsilon \\ \text{CANCEL\_AND\_REPLACE}, & \text{if } \Delta \ge \epsilon \end{cases}$$

Where the threshold is calibrated to the native market tick size:

$$\epsilon = 0.01\text{ USDC}$$

* **Micro-drift ($\Delta < 0.01$):** Sub-tick price fluctuations generated by continuous model re-evaluations are ignored. Resting orders retain their prioritized position in the FIFO queue.
* **Macro-shift ($\Delta \ge 0.01$):** When spot momentum moves the market by one full tick or more, the gate triggers an immediate cancel-replace sequence, preventing adverse selection.

*For the complete Rust implementation and official API interactions, see [03-rust-engine-implementation.md §6](./03-rust-engine-implementation.md#6-station-8-fifo-hysteresis-decision-gate).*

---

## 9. Cross-Document Navigation

* 📖 **Pipeline Topology & Overview:** [01-pipeline-overview.md](./01-pipeline-overview.md)
* 🦀 **Rust Systems Architecture & APIs:** [03-rust-engine-implementation.md](./03-rust-engine-implementation.md)
* ⛓️ **CTF Smart Contract Settlement:** [04-ctf-settlement-lifecycle.md](./04-ctf-settlement-lifecycle.md)
* 🚀 **Operational Runbook & Telemetry:** [05-operational-bootstrap-and-runbook.md](./05-operational-bootstrap-and-runbook.md)
* 📚 **Developer Bibliography & Environment:** [06-developer-bibliography-and-resources.md](./06-developer-bibliography-and-resources.md)
* 🎨 **Color-Coded Math Reference:** [The-Math-for-Microstructure-Calibrated-Inventory-Risk-Engine.md](./The-Math-for-Microstructure-Calibrated-Inventory-Risk-Engine.md)
