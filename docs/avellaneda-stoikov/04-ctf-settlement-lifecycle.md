# CTF Settlement Lifecycle & On-Chain Collateral Management

## 1. The Conditional Token Framework (CTF) Architecture

Polymarket's prediction market infrastructure is anchored on the Gnosis Conditional Token Framework (CTF) deployed on Polygon. In this framework, positions are represented as ERC-1155 multi-tokens whose state transitions (splits, merges, redemptions) are governed by deterministic smart contracts.

### 1.1 Verified Smart Contract Specifications

* **Polygon Network ID:** `137`
* **CTF Exchange Contract:** `0x4D97DCdE725A8964c18F938002996A407217E759`
* **Collateral Asset:** Bridged USDC / Native USDC collateral token on Polygon.
* **Core Contract Reference:** `ctf-exchange-v2` and `polymarket-v2-external`.

---

## 2. The `mergePositions` Mechanism

When both sides of a binary market fill ($p_{\text{bid}}^{\text{UP}}$ and $p_{\text{bid}}^{\text{DN}}$), the bot holds matching balances of both outcome tokens. To realize the risk-free arbitrage spread and restore liquid USDC to the quoting wallet, the engine calls the `mergePositions` function on the CTF contract.

### 2.1 Solidity Interface

```solidity
interface IConditionalTokens {
    function mergePositions(
        IERC20 collateralToken,
        bytes32 parentCollectionId,
        bytes32 conditionId,
        uint[] calldata partition,
        uint amount
    ) external;
}
```

### 2.2 Parameter Definitions

| Parameter | Type | Value / Purpose |
| :--- | :--- | :--- |
| `collateralToken` | `IERC20` | The address of the underlying collateral token (USDC on Polygon). |
| `parentCollectionId` | `bytes32` | `bytes32(0)` for root prediction markets (unconditioned on previous outcomes). |
| `conditionId` | `bytes32` | The unique identifier of the 5-minute Bitcoin market question. |
| `partition` | `uint[]` | Binary slot partition: `[1, 2]` representing index `0` (UP) and index `1` (DOWN). |
| `amount` | `uint256` | The number of paired outcome tokens to burn (in 6-decimal token units). |

### 2.3 The Economic Payoff Invariant

Calling `mergePositions` with $N$ units of UP and $N$ units of DOWN burns both sets of outcome tokens atomically:

$$\text{Burn}(N \cdot \text{UP}) + \text{Burn}(N \cdot \text{DOWN}) \implies \text{Mint}(N \cdot 1.00\text{ USDC})$$

If the total acquisition cost was $N \times 0.96\text{ USDC}$, the merge transaction returns $N \times 1.00\text{ USDC}$, locking in an immediate net profit of $N \times 0.04\text{ USDC}$ without waiting for the 5-minute contract resolution or oracle finalization.

---

## 3. Asynchronous Settlement Actor in Rust

To prevent blockchain transaction latency from blocking the ultra-low-latency market making loop, on-chain merging is delegated to an isolated asynchronous worker.

```rust
use alloy_primitives::{Address, B256, U256};
use alloy_sol_types::sol;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

sol! {
    interface IConditionalTokens {
        function mergePositions(
            address collateralToken,
            bytes32 parentCollectionId,
            bytes32 conditionId,
            uint256[] calldata partition,
            uint256 amount
        ) external;
    }
}

pub struct CtfSettlementManager {
    collateral_token: Address,
    condition_id: B256,
    partition: Vec<U256>,
    min_batch_threshold: u64, // Minimum shares before triggering merge
}

impl CtfSettlementManager {
    pub fn new(collateral: Address, condition: B256, min_batch: u64) -> Self {
        Self {
            collateral_token: collateral,
            condition_id: condition,
            partition: vec![U256::from(1), U256::from(2)],
            min_batch_threshold: min_batch,
        }
    }

    #[inline(always)]
    pub fn evaluate_pairable_inventory(&self, inventory_up: u64, inventory_dn: u64) -> Option<u64> {
        let pairable = inventory_up.min(inventory_dn);
        if pairable >= self.min_batch_threshold {
            Some(pairable)
        } else {
            None
        }
    }
}
```

---


---

## 3.1 Primary Gasless Settlement Path (Polymarket Relayer)

When `GASLESS_RELAYER_ENABLED=true`, the bot delegates transaction broadcast to Polymarket's Relayer service. The relayer sponsors 100% of the gas cost, allowing on-chain merges to execute with **zero POL** in the developer wallet:

* **Relayer Endpoint:** Configured via `POLYMARKET_RELAYER_URL`
* **Relayer API Key Header:** `POLY_API_KEY: 01a01551-4415-7a54-a382-f09ad02bf050`
* **Relayer Signer Address:** `0x832cBcdece2724eA0174c9fbE8D584b75C872163`
* **On-Chain Gas Cost to User:** **0.00 POL**

```rust
pub async fn submit_gasless_merge(
    http_client: &reqwest::Client,
    relayer_url: &str,
    relayer_api_key: &str,
    signed_meta_tx_payload: serde_json::Value,
) -> Result<String, Box<dyn std::error::Error + Send + Sync>> {
    let response = http_client
        .post(relayer_url)
        .header("Content-Type", "application/json")
        .header("POLY_API_KEY", relayer_api_key)
        .json(&signed_meta_tx_payload)
        .send()
        .await?;

    let result: serde_json::Value = response.json().await?;
    let tx_hash = result["transactionHash"]
        .as_str()
        .ok_or("Missing transactionHash in relayer response")?
        .to_string();

    Ok(tx_hash)
}
```

## 4. Polygon Gas Management & Batching Economics (Fallback Direct Mode)

Executing a transaction on Polygon involves gas costs (base fee + priority tip). Merging individual shares ($1 pair) continuously is economically destructive:

* **Standard `mergePositions` Gas Consumption:** $\approx 85,000\text{ to } 120,000\text{ gas}$.
* **Gas Cost at 50 Gwei:** $100,000 \times 50 \times 10^{-9}\text{ POL} \approx 0.005\text{ POL} \approx \$0.002\text{ to } \$0.004$.

### 4.1 Optimal Batch Sizing Threshold

If the engine captures a spread of $\$0.01$ per pair:
* Merging 1 pair costs $\approx \$0.003$ in gas, consuming **30% of the arbitrage profit**.
* Merging 50 pairs ($N = 50$) costs the exact same $\approx \$0.003$ in gas, reducing gas drag to **0.6% of gross profit**.

The settlement actor enforces a dynamic minimum batch threshold:

$$N_{\text{min}} = \left\lceil \frac{10 \times \text{TxCost}_{\text{gas}}}{s^*} \right\rceil$$

This formula guarantees that on-chain gas overhead never exceeds 10% of the harvested spread.

---

## 5. Cross-Document Navigation

* 📖 **Pipeline Topology & Overview:** [01-pipeline-overview.md](./01-pipeline-overview.md)
* 📐 **Mathematical Formulas & Proofs:** [02-math-and-microstructure.md](./02-math-and-microstructure.md)
* 🦀 **Rust Engine Implementation & Official APIs:** [03-rust-engine-implementation.md](./03-rust-engine-implementation.md)
* 🚀 **Operational Runbook & Telemetry:** [`05-operational-bootstrap-and-runbook.md`](./05-operational-bootstrap-and-runbook.md)
* 📚 **Developer Bibliography & Secrets:** [`06-developer-bibliography-and-resources.md`](./06-developer-bibliography-and-resources.md)
