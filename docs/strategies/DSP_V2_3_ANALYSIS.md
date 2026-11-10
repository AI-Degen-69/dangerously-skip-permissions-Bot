# DSP-v2.3 Trade Analysis & Performance Tuning

- **Run analyzed:** `bot/runs/run_20261110_011956_paper_dsp_v2_3`
- **Frozen snapshot:** 30 settled windows `btc-updown-5m-1794273600` … `btc-updown-5m-1794282300`
  (first 30 window files with stem ≤ `…1794282300`). In-flight windows `…1794282600` (later settled),
  `…1794282900`, `…1794283200`, `…1794283500`, `…1794283800`, and pending `…1794284100` are **excluded**.
- **Run status at analysis time:** `run_meta.json → "status": "running"` (live; disk grew to 36 files
  during analysis — 35 settled + 1 pending `…1794284100`, vs 31–32 files at the prompt snapshot).
  All headline numbers below are on the frozen 30 unless stated otherwise.
- **Baseline:** `bot/runs/run_20261109_205116_paper_dsp_v2_2` (34 files: 32 settled incl. 15 zero-fill
  scratches, 2 pending; 17 wins / 0 losses).
- **Code read:** `bot/executor.py` (`evaluate_microstructure_ladder`, `select_ladder_clip`,
  `_projected_pair_cost`, `compute_fill_usd`), `bot/live_paper.py` (`trade_window`: pacing,
  `in_sweep_phase`, cutoff logic, semantic tagging), `bot/constants.py` (`STRATEGY_SETUPS`),
  `bot/risk.py`, `bot/config.json` (live file currently holds the **v2.3** id — note: it no longer
  holds v2.2; the prompt's §3.5 note about config.json holding v2.2 is stale), `bot/ab_test.py`,
  `CONSTRAINTS.md`.
- **Files touched:** `scratch/analyze_v23_frozen30.py` (new, read-only analysis script);
  this report (new). **No engine behavior modified.**
- **Reproduction:** `python scratch/analyze_v23_frozen30.py` re-derives the per-window table and
  the locked/residual split. All arithmetic below was computed in Python against the JSON
  (not read manually).

---

## 1. Executive summary

1. **Net −$27.26 on $3,092.26 cost (ROI −0.88%), 19W / 11L, win rate 63.3%** vs break-even 77.8%
   (avg win +$1.395 vs avg loss −$4.888).
2. **Locked pair capture +$55.17, residual/directional −$82.43** (≈ prompt's +$55.57 / −$82.83;
   ±$0.40 rounding, see §2). The hedged core works; the unhedged tail is the entire loss.
3. **Single root cause: 11/11 losses are stranded-share residuals.** Every losing window ended with
   imbalance 10/15/20 on the losing side; 19/19 winning windows ended flat (imbalance 0).
   `residual_loss = imbalance × avg_price_of_leading_side` holds exactly
   (e.g. `…1794274200`: 20 × 0.4733 = −$9.47; locked +$0.77; net −$8.70 ✅).
4. **Correction (operator direction, 2026-11-10): v2.3 fills throughout by design — no atomic
   path, no entry-refusal philosophy.** The v2.2 pre-flight gate (L1) and the ≤$1.00
   forced-flatten (L5) are **dropped**: the gate contradicts the micro-cycle design, and the
   ledger cannot prove a $1.00 close would even have filled (stranded windows go silent after
   M0–M2 — quotes unknown). Revised top 3, all philosophy-preserving: (a) single strict
   unhedged-gap veto knob `maxShareLead` (lead + shares >= knob is skipped, so the knob
   value is never held; v2.3 set to 20 = max hold 19, no hidden allowance); (b) decided-phase
   rescue cap 0.995 → 1.00 in the last 2 minutes (EV: closing a 20-gap at pc 1.00 costs cents
   vs stranding −$8.70; quotes proven present late by the decisions log); (c) behavior-preserving
   `.endswith` → capability-flag hygiene (DONE 2026-11-10). The log-driven entry freeze is
   **DROPPED by measurement 2026-11-10**: 1 dip fill after decision in 19 loser windows (§11) —
   the bot already buys nothing late, so a freeze saves ~$0.
5. **Expected effect (57-window re-analysis, §11):** 54 resolved, net −$46.10, 35W/19L; **19/19
   losers touched gap 20.** Knob 20 → 9 (max hold 8) puts worst case ≈ −$3.50/strand, tail
   ≈ −$82 → ≈−$35 at identical strand rate, zero philosophy change. Winners pay 0.992 median
   pair cost (paying up works); losers die of unhedged size at 0.955 (hedges were never the
   problem). The force-flat counterfactual is retained as an arithmetic bound only.
6. **Biggest unresolved risk:** the recorded ledger has **fills but no quotes**, so whether a deficit
   *could* have been closed (price vs pair-cost-cap vs code-path binding) is **NOT DETERMINABLE**
   from this data — it needs instrumented forward paper runs. Plus the paper fill model
   (maker-assumed-at-touch, no queue/depth/partial fills) conditions every P&L conclusion.

## 2. Anchor validation (§3 reproduced; deviations stated loudly)

| # | Anchor (prompt) | Reproduced on frozen 30 | Verdict |
|---|---|---|---|
| run scale | 31–32 files, 30 settles | 36 files at analysis time (live growth); frozen 30 settles `…3600`–`…2300` | ✅ frozen matches; drift is live growth, stated |
| events | info 1 · entry/hedge 495 · refuse 816 · settle 30 · done 31 | at analysis: info 1 · entry 350 + hedge 201 (=551) · refuse **941** · settle 35 · done 36 | ⚠️ **differs — run kept trading** (refusals are throttled 1/10 s, so 941 ≪ true refusals). Frozen-30 P&L unaffected |
| window fills | 493 excl. in-flight; MAKER/TAKER 469/24 | frozen-30 window files: **483** fills; **MAKER 459 / TAKER 24**; `maker-dip-ladder` 265 / `rescue-equalizer` 192 / `hedge-equalizer` 26 | ⚠️ −10 fills, −10 maker, −5/−5 sub-reasons vs prompt. Taker 24 exact; P&L/cost/fees exact (below), so this is a counting-snapshot difference (live growth + entry-vs-hedge tagging), not a P&L error |
| fees | $4.84 on ~$3,092 (~15.6 bps) | **$4.84 on $3,092.26** ✅ | ✅ exact |
| refusals | 816, all `extreme-price-skip` | 941 at analysis time, all `extreme-price-skip` | ✅ kind matches; count grew with live run |
| cost | $3,092.26 | **$3,092.26** ✅ | ✅ exact |
| payout / net | $3,065.00 / −$27.26 | **$3,065.00 / −$27.26** ✅ | ✅ exact |
| W/L, WR | 19/11, 63.3% | **19/11, 63.3%** ✅ | ✅ exact |
| break-even WR | 77.8% ($1.395 vs $4.888) | avg win 26.51/19 = **$1.395**; avg loss 53.77/11 = **$4.888**; BE = 4.888/6.283 = **77.8%** ✅ | ✅ exact |
| best/worst | +$4.87 / −$8.70 | **+4.87 (`…4500`) / −8.70 (`…4200`)** ✅ | ✅ |
| cost/window | min 18.70 · med 109.40 · max 183.55 | **18.70 · 110.85 · 183.55** | ⚠️ median differs ($110.85 recomputed as upper-median of 30; $109.40 may be a different median convention or snapshot) |
| fills/window | min 2 · med 17 · max 27 | **4 · 17 · 27** | ⚠️ min differs (prompt's "2" belongs to a post-snapshot in-flight window: `…1794282900` has exactly 2 fills) |
| final pair cost | min 0.9225 · med 0.9894 · max 0.9945 | recomputed blended avg-pair-cost med ≈ 0.989; exact per-fill `pairCost` stamping only exists on imbalance-reducing fills (see §C) | ~✅ same shape; stamping caveat noted |
| fill price | min 0.19 · med 0.45 · max 0.81 | **0.19 · 0.45 · 0.81** ✅ | ✅ exact |
| maker-dip px | min 0.19 · max 0.45 · med 0.35 | **0.19 · 0.45 · 0.35** ✅ | ✅ exact |
| rescue proj PC | min 0.9855 · med 0.9912 · max 0.995 | **0.9855 · 0.9912 · 0.995** (n=192 stamped rescue fills) ✅ | ✅ exact |
| locked/resid | +$55.57 / −$82.83 | **+$55.17 / −$82.43** (sum of per-window `locked = min_sh×(1−avg_up−avg_dn)`, `resid = net − locked`) | ⚠️ −$0.40/+$0.40 rounding-level difference; identity and thesis unchanged |
| v2.2 | +$18.00, 17W/0L, 32 settled, all-50 clips, first-fills 0.47–0.55 | **+$18.00, 17W/0L (+15 zero-fill scratches), 32 settled + 2 pending; locked +$18.00 / resid $0.00; all 34 fills-clip 50.0; first-fills 0.47–0.55** ✅ | ✅ modulo prompt's +18.50/−0.50 split (ours +18.00/0.00; $0.50 is fee-inclusive decomposition convention) and 34-vs-32 file count (2 pending) |
| config delta | table §3.5 | ✅ verified against `run_meta.json → configSnapshot` (maxFillPrice 0.45, maxShares 45, maxShareLead/freezeLead 15, clips 10, gates 0.965/0.985/0.995, SBC 75) | ✅ exact |
| strategy-field bug | `windows/*.json → strategy = "hapcs-v1"` vs `fills[].detail.strategy = v2.3` | ✅ confirmed: all 30 frozen files top-level `"strategy": "hapcs-v1"`(= `C.STRATEGY_ID` hardcoded in `live_paper.py` snapshot dict), fills say `dangerously-skip-permissions-v2.3`. Trust fills + run_meta | ✅ + new note: `bot/config.json` on disk NOW holds v2.3 (prompt's "holds v2.2" is stale) |

**Reconciliation:** for all 30 frozen windows `Σ fill.usd == cost_usd`, `Σ winner_shares == payout_usd`,
`net == payout − cost` — **30/30 pass, no double-counts, no failures.** In-flight/pending files
(`…1794284100` at analysis time) excluded explicitly. No window needed de-duplication.

## 3. Findings

### A. Reconcile & de-duplicate

- Frozen-30: cost $3,092.26 / payout $3,065.00 / net −$27.26; fees $4.84 (taker only, 24 fills).
- Fill reasons (window-file `detail.subReason`): maker-dip-ladder 265 · rescue-equalizer 192 ·
  hedge-equalizer 26. Event-kind `entry`/`hedge`/`straddle-open`/`hedge-leg` tagging is a *semantic
  overlay* in `trade_window` (first fill = straddle-open, second = hedge-leg, rescue-subReason =
  rescue-hedge, …) — it does **not** change economics; use `detail.subReason` + role for analysis.
- MAKER/TAKER 459/24. Taker fee model `0.07·p·(1−p)`/share confirmed via `compute_fill_usd`.
- Cost/window: 18.70 … 110.85 (med) … 183.55. Fills/window: 4 … 17 … 27.
- **Implication:** the ledger is internally consistent; the loss is real, not an accounting artifact.
- **To do:** freeze snapshots by slug list in all future analyses (this run never stops growing).

### B. Residual forensics (the core task)

Per-window loss anatomy (slug suffix | Up sh | Down sh | imb | lead | lead avg $ | locked $ | resid $ | net $ | winner):

| slug | Up | Down | imb | lead | leadAvg | locked | resid | net | W |
|---|---|---|---|---|---|---|---|---|---|
| …3600 | 135 | 135 | 0 | – | – | +1.58 | −0.00 | +1.58 | Dn |
| …3900 | 110 | 110 | 0 | – | – | +0.60 | −0.00 | +0.60 | Up |
| …4200 | 30 | 10 | 20 | Up | 0.4733 | +0.77 | −9.47 | −8.70 | Dn |
| …4500 | 160 | 160 | 0 | – | – | +4.87 | +0.00 | +4.87 | Up |
| …4800 | 145 | 145 | 0 | – | – | +1.39 | −0.00 | +1.39 | Dn |
| …5100 | 185 | 185 | 0 | – | – | +1.97 | −0.00 | +1.97 | Up |
| …5400 | 115 | 115 | 0 | – | – | +0.65 | +0.00 | +0.65 | Dn |
| …5700 | 20 | 40 | 20 | Dn | 0.5075 | +1.55 | −10.15 | −8.60 | Up |
| …6000 | 135 | 135 | 0 | – | – | +0.80 | +0.00 | +0.80 | Dn |
| …6300 | 95 | 95 | 0 | – | – | +0.65 | −0.00 | +0.65 | Dn |
| …6600 | 135 | 135 | 0 | – | – | +1.00 | +0.00 | +1.00 | Dn |
| …6900 | 130 | 110 | 20 | Up | 0.4046 | +4.46 | −8.09 | −3.63 | Dn |
| …7200 | 125 | 125 | 0 | – | – | +1.15 | +0.00 | +1.15 | Dn |
| …7500 | 145 | 145 | 0 | – | – | +1.11 | +0.00 | +1.11 | Up |
| …7800 | 30 | 20 | 10 | Up | 0.4000 | +0.80 | −4.00 | −3.20 | Dn |
| …8100 | 115 | 115 | 0 | – | – | +4.15 | +0.00 | +4.15 | Dn |
| …8400 | 70 | 70 | 0 | – | – | +0.53 | +0.00 | +0.53 | Dn |
| …8700 | 40 | 55 | 15 | Dn | 0.3455 | +1.48 | −5.18 | −3.70 | Up |
| …9000 | 155 | 155 | 0 | – | – | +0.92 | +0.00 | +0.92 | Up |
| …9300 | 95 | 95 | 0 | – | – | +0.65 | +0.00 | +0.65 | Dn |
| …9600 | 75 | 65 | 10 | Up | 0.5276 | +2.34 | −5.28 | −2.94 | Dn |
| …9900 | 185 | 185 | 0 | – | – | +1.45 | +0.00 | +1.45 | Up |
| …0200 | 50 | 30 | 20 | Up | 0.4180 | +1.96 | −8.36 | −6.40 | Dn |
| …0500 | 85 | 100 | 15 | Dn | 0.4825 | +3.79 | −7.24 | −3.45 | Up |
| …0800 | 105 | 90 | 15 | Up | 0.4602 | +3.63 | −6.90 | −3.27 | Dn |
| …1100 | 50 | 30 | 20 | Up | 0.4380 | +1.96 | −8.76 | −6.80 | Dn |
| …1400 | 150 | 130 | 20 | Up | 0.4500 | +5.92 | −9.00 | −3.08 | Dn |
| …1700 | 100 | 100 | 0 | – | – | +0.70 | +0.00 | +0.70 | Dn |
| …2000 | 130 | 130 | 0 | – | – | +1.19 | +0.00 | +1.19 | Dn |
| …2300 | 100 | 100 | 0 | – | – | +1.15 | +0.00 | +1.15 | Up |

- Imbalance distribution: **0 (19×) · 10 (2×) · 15 (3×) · 20 (6×).**
- `P(net<0 | imb>0) = 11/11 = 100%`; `P(net<0 | imb==0) = 0/19 = 0%`. The single scratch-free
  separator in the whole dataset.
- Loss-given-imbalance: imb 10 → mean −$3.07 (−3.20, −2.94); imb 15 → −$3.47; imb 20 → −$6.20
  (−8.70 … −3.08). Cost of being stranded scales with imb × lead-avg, not with window size.
- Counterfactual "force flat at observed rescue prices": net → **+$55.17** (the locked column).
  Assumption (weak, stated): the deficit *could* have closed at ≤ observed rescue prices —
  **the ledger cannot prove this** (no quotes; see §C/H).
- Close-to-flat (imb 10: `…7800`, `…9600`) vs structurally stranded (imb 20, esp. `…1400` 150-vs-130
  and `…6900` 130-vs-110): the latter are full micro-cycles that paired hundreds of shares yet
  ended one clip short — the cap binds the *net*, not the *volume*.
- **Implication:** cap the terminal imbalance and the loss disappears arithmetically; everything
  else is second-order.
- **To do:** L4 (lead-cap 15→8, allowance +5→+0), decided-market freeze, adaptive rescue cap —
  all sized/validated off the curve above and the new `decisions.jsonl` log (see §8). L1/L5
  dropped per operator direction (fill-throughout design; atomic stays out).

### C. Timing fingerprint

- Fills by minute (frozen 30): **M0 261 · M1 120 · M2 53 · M3 48 · M4 1.**
- **All 11 losing windows have ZERO M3/M4 fills; all 49 M3/M4 fills belong to balanced winners**
  (M3/M4 windows: `…3600`, `…4500`, `…5100`, `…5400`, `…6000`, `…6600`, `…7500`, `…8100` — all imb 0).
- Effective timeline (`trade_window`): open → trade at T+4 s → `end = slot+300−75` (T-75 s):
  loop breaks when `now >= sweep_end` OR (`now >= end` AND flat). Sweep = T-75…T-12 s
  (`sweep_end = slot+300−12`), only entered with imbalance > 0; cutoff T-12 s hard.
- In sweep: dip fills **forbidden** (`in_sweep_phase` → skip dips); only equalizer/rescue fills
  allowed, with maker-priority (`role=MAKER, exec=bid`) and relaxed 0.5 s pacing.
- [H] Sweep too short/constrained to close M0–M2 deficits: **consistent** with the fingerprint
  (stranded windows never even *attempt* visibly — zero M3/M4 fills), but the recorded data
  **cannot distinguish** price-binding (`opp > rescueCeilingPrice 0.985`) vs pair-cost binding
  (`proj > rescuePairCostMax 0.995`) vs code-path (`lead+shares > lead_cap+5`, `allowed_pc`,
  throttled refuse logging). Sweep is 63 s / 0.5 s ≈ 126 attempts — plenty of *time*; the block
  is almost surely a *gate*, not the clock. But which gate fired is NOT DETERMINABLE here.
- **Instrumentation required (read-only, `scratch/` first):** wrap `evaluate_microstructure_ladder`
  in a logging shim that, on every sweep skip, records `{slug, minute, side, px, opp_ref,
  proj_pair_cost, saw_ceiling, saw_pair_cap, saw_dust, lead, deficit, gate}`; run 3–5 h of
  forward paper; then decide L6/L7. Do **not** change decision logic to collect this.

### D. Price / entry selection

- First-fill prices: v2.3 frozen-30 **all ≤ 0.45** (0.45×11, 0.44×9, rest 0.33–0.43; min 0.33) vs
  v2.2 **0.47–0.55** (med ~0.50). ✅ verified.
- Reachability: with `maxFillPrice = 0.45`, the `STRADDLE_BAND (0.34,0.55]` opening-straddle branch
  (`px <= 0.55 and both inv == 0`) is reachable only for **px ∈ [0.34, 0.45]** — the (0.45, 0.55]
  half is dead code for v2.3. The bot can only open on the ≤45¢ side, i.e. **always the side the
  market prices as the underdog**. Verified by reading the branch (`dip_max = 0.45 if is_dsp`,
  `px > max_fill → saw_ceiling → skip`).
- [H] First fill is a directional bet by construction: first-fill side won **18/30 (60%)** vs a
  50% base rate — i.e. **no positive selection** (n=30, noise; 95% CI ≈ 42–76%). The cheap side
  is not systematically the winner.
- Calibration (shares-weighted, payout−cost $/bucket): cheap fills lose, expensive fills win —
  but that is *payoff mechanics* ($1 redemption), not skill. The honest table is the
  **residual-side-only** one: **hit rate 0.0 in every bucket** (by construction — all 11 stranded
  leads lost), residual P&L −$373 across buckets. There is **zero evidence of directional skill
  on the unhedged leg**; the residual is a lottery ticket that lost 11/11.
- **Implication:** stop opening only on the cheap side (L3) or stop leaving the open unhedged (L1).
- **To do:** L1 (gate) dominates L3 (symmetric open costs more capital); test both via A/B.

### E. Equalizer / rescue mechanism

- Rescue fills (stamped `pairCost`): n=192, min 0.9855 · med 0.9912 · max 0.995 — every rescue
  individually "profitable" on its matched quantity, yet the strategy lost $82.43 net residual.
- Mechanism: each rescue locks `matched × (1 − pair_cost)` (≈ +$0.005–0.015/share) on the matched
  leg while the *unmatched* 10–20 shares keep full directional exposure (≈ −$0.35–0.50/share if
  wrong). One stranded clip wipes ~30–60 successful rescues.
- Marginal value: a 20-share rescue at 0.995 locks **+$0.10** and leaves up to **−$9.00** tail.
  Rescue is **net-negative whenever `P(strand) × imb × avg_lead > matched × (1 − pair_cost)`** —
  which, at 11/30 strand rate, it massively is. A rescue that closes the *final* 10–20 shares is
  worth ~+$0.10 + ~+$4–9 of avoided tail; a rescue that *extends* a window (more dip cycles after
  a partial close) can be net-negative. The engine cannot tell the two apart.
- `rescuePairCostMax = 0.995` vs book at ~0.99: once the deficit side is quoted 0.99 and the held
  avg is ~0.44, `proj = 0.44 + 0.99 = 1.43 > 0.995` — wait, that math uses *averages*, so late
  rescues project from the *blended* avg (~0.44 + ~0.55 ≈ 0.99). Binding happens when the held
  average itself drifts up (deep rescue chains) — exactly when it matters most. Quantifying the
  frequency needs quote data (**NOT DETERMINABLE** from fills; needs §C instrumentation).
- Clip arithmetic (`select_ladder_clip` + `clip_shares` + lead gate): deficit > 0 → snap to deficit
  (capped at maxShares 45); fresh dips in v2.3 → `$4.50/price` snapped to 5-share steps in
  [10, 45] → at 0.19–0.45 that yields **10/15/20** observed (276/129/88 ≈ prompt's 10/15/20
  histogram modulo snapshot drift). Lead gate `lead >= 15 or lead+shares > 20` caps terminal
  imbalance at **exactly 20** ✅ — the observed max.
- **Implication:** rescues are correctly priced per-unit and wrongly risk-managed per-window.
- **To do:** L7/L8 adaptive rescue cap by time-to-close (validate fillability on `decisions.jsonl`
  first — L5 retired per operator), size closes against pair cost + tail.

### F. Guard-flag audit (`is_v22`) — the highest-value hypothesis

- Verified in `bot/executor.py`: `is_v22 = strategy_id.endswith("v2.2")` (line ~179); v2.3 id
  `dangerously-skip-permissions-v2.3` does **not** match → every `is_v22` gate is **silently OFF**:
  1. **Pre-flight hedge gate** (line ~359: `if is_v22 and deficit <= 0 and opp_ref is not None:
     if px + opp_ref > rescue_cap: skip`) — **OFF for v2.3** (confirmed; v2.3 comment says
     "drops this gate … so dips keep filling").
  2. `is_atomic → False` always → **no 60-share atomic path** (`select_ladder_clip` line ~77),
     `lead >= lead_cap` never relaxed (`atomic_bypass`, line ~388) — consistent with observed
     max clip 20 and zero 60-share fills in v2.3.
  3. `select_ladder_clip(..., is_v22=False)` → pre-v2.2 ladder for any non-deficit, non-v2.3 path —
     moot in practice (v2.3 takes the `is_v23` constant-risk branch first), but the call chain
     still threads the dead flag.
  4. `lead_cap = min(max_share_lead,15.0) = 15` for v2.3 (line ~190) vs 20 for v2.2 — confirmed;
     +5.0 allowance → max stranded 20 ✅ exactly as observed.
- Behavioral proof: v2.2 (gate ON) → 0/32 imbalanced, 0 losses, all-50 clips; v2.3 (gate OFF) →
  11/30 imbalanced, 11 losses, clips 10/15/20, zero atomic fills. The `STRATEGY_SETUPS` registry
  already documents this honestly (`preflightGate: False` for v2.3, "No pre-flight gate … relies
  on pair-cost gates below").
- Attempted refutation: is there a v2.3 window inconsistent with "gate OFF"? `…1400`-style
  windows pair hundreds of shares at good prices — but that is the *equalizer* (gate-independent),
  not the *entry gate*. **No refuting window found.** [H] stands: the missing gate explains the
  majority of the v2.2 → v2.3 residual regression (−$0.00 → −$82.43).
- Fix in the repo's idiom: add explicit capability booleans to `STRATEGY_SETUPS[...]["entry"]`
  (e.g. `preflightHedgeGate: bool`, `atomicSizing: bool`, `constantRiskSizing: bool`) plus
  `_SETUP_FEATURES` entries; thread them as parameters (`preflight_gate`, `atomic_sizing`) through
  `evaluate_microstructure_ladder`/`select_ladder_clip`; delete the three `.endswith()` tests
  (v2.2 at line ~179, v2.1 at ~191, atomic `is_confidence`). Full reference list:
  `executor.py` lines ~56 (`is_v22` param), ~77, ~87, ~179–194 (flag derivation + lead caps),
  ~263–264, ~359, ~378, ~388. Then set v2.4 = v2.3 numbers + `preflightHedgeGate: True`.
  Must keep `bot/tests/` green (CONSTRAINTS §1).

### G. Regime / environment check

| | v2.2 (32 settled) | v2.3 frozen-30 |
|---|---|---|
| net | +$18.00 | −$27.26 |
| W/L (excl. scratches) | 17/0 | 19/11 |
| locked / residual | +$18.00 / $0.00 | +$55.17 / −$82.43 |
| imb>0 windows | 0/32 | 11/30 |
| fills/window | exactly 2 (or 0 scratches) | 4–27 (med 17) |
| clip sizes | all 50 | 10/15/20 |
| first-fill px | 0.47–0.55 | ≤0.45 always |
| cost/window | ~$47–50 (paired atomics) | $19–184 |

- Verdict: **code regression (missing gate + cheap-only entry + micro-cycle volume), not
  environment.** v2.3's locked engine is *better* (+$55 vs +$18 — more windows traded, more pairs).
  The market did not compress the spread (locked/share is healthy); v2.3 donated it back via tails.
- Within-run degradation: losses cluster late (7 of 11 losses in the last 12 frozen windows;
  `…0200`–`…1400` = 5 straight losses) — but n=30 is too small to separate regime from streak.
  Treat as hypothesis: re-check on the next 30.

### H. What is NOT a lever (killed explicitly)

- **Fees:** $4.84 / $3,092.26 = **15.6 bps**. Contribution to −$27.26: **17.8%**, and only via 24
  taker fills. Maker-priority sweep already minimizes it. No material fee lever exists. Kill.
- **Risk caps:** peak window $183.55 vs $4,000 cap (4.6%); max 27 fills vs 500 cap; run drawdown
  $27.26 vs $500 daily cap (5.5%). **None bound, ever.** They did not cause the loss — and, worse,
  they provide no protection at v2.3 scale (a 20-share strand costs ~$9 regardless of a $4,000
  window cap). Kill as explanation; flag as gap (see L10).
- **benchmark/target 0.965:** fresh-dip gate `proj <= 0.965` — binding on *every* fresh dip by
  design (dips project ~0.80–0.95 when flat). It is the normal entry filter, not a special cause.
  Rescue/close-deficit paths use 0.985/0.995. Kill as "the" cause.
- **Maker/taker mix (459/24):** fee delta is basis points; the loss is dollars of directional tail.
  Kill.

## 4. Loss anatomy table

See §3B (the 30-row table). Loss-given-imbalance curve:

| terminal imb | n | mean net | nets |
|---|---|---|---|
| 0 | 19 | +$1.40 | +0.53 … +4.87 (all ≥ +0.53) |
| 10 | 2 | −$3.07 | −3.20, −2.94 |
| 15 | 3 | −$3.47 | −3.70, −3.45, −3.27 |
| 20 | 6 | −$6.20 | −8.70, −8.60, −6.80, −6.40, −3.63, −3.08 |

`P(loss|imb>0)=100%`, `P(loss|imb==0)=0%`. Eliminating terminal imbalance (holding entries fixed)
removes **$82.43 of $82.43** residual loss arithmetically — assumption: closure at ≤ observed
rescue prices (unproven; see §6-assumptions).

## 5. Counterfactual table (frozen 30, assumptions stated)

| # | Counterfactual | Assumption | Net (was −$27.26) |
|---|---|---|---|
| 1 | Force final imbalance → 0 (keep entries, close at observed rescue prices) | deficit closable at ≤ observed rescue px | **+$55.17** (= locked total) |
| 2 | Skip windows whose first fill ≤ $0.30 | first-fill px predicts strand | **−$27.26 (no-op — min first-fill is $0.33; nothing skipped)** |
| 2b | Skip windows whose first fill ≤ $0.35 (added: the actual cheap tail) | same | −$27.26 + $1.58 +$0.60 … ≈ −$24 (2 windows skipped; negligible — first-fill px does not predict) |
| 3 | Cap dip ladder at N fills/window | first-N fills keep their realized outcome | N=5 → **+$11.46**; N=10 → −$31.41; N=15 → −$53.11. (N=5 "works" by amputating volume — locked capture collapses with it; not a strategy, a demonstration that *late* fills create the strand) |
| 4 | Drop 4 worst windows | cherry-pick (NOT a strategy) | **+$3.24**, win rate 19/26 = 73% — still below the 77.8% break-even. Shows even ex-post selection barely breaks even |

## 5b. Forced-close backfill from market data (new 2026-11-10)

Yes — the API exists. Method: `gamma-api.polymarket.com/events?slug=` for archived
markets (gives both `clobTokenIds`), then `clob.polymarket.com/prices-history?market=
&startTs=&endTs=&fidelity=1` for trade prints. Winner-side token, late-window prints, all
11 stranded windows (mid-price prints, no spread/depth/fees — lower bound on close cost):

| window | W | imb | late prints (t−slot, px) | close cost |
|---|---|---|---|---|
| …4200 | Dn | 20 | (152, .945) (197, .998) (255, .9995) | $19.99 |
| …5700 | Up | 20 | (198, .985) (258, .995) | $19.90 |
| …6900 | Dn | 20 | (177, .865) (193, .835) (256, .995) | $19.90 |
| …7800 | Dn | 10 | (207, .975) (258, .995) | $9.95 |
| …8700 | Up | 15 | (197, .985) (258, .995) | $14.93 |
| …9600 | Dn | 10 | (152, .775) (196, .875) (255, .995) | $9.95 |
| …0200 | Dn | 20 | (193, .945) (256, .995) | $19.90 |
| …0500 | Up | 15 | (196, .975) (256, .9995) | $14.99 |
| …0800 | Dn | 15 | (196, .955) (255, .995) | $14.93 |
| …1100 | Dn | 20 | (192, .985) (255, .9995) | $19.99 |
| …1400 | Dn | 20 | (158, .675) (204, .985) (254, .995) | $19.90 |

Totals: close cost ≈ **$184.33** to recover **$185.00** payout → close legs net **+$0.67**,
so the run goes −$27.26 → **−$26.59**: a wash. CORRECTION (2026-11-10): an earlier draft
of this section claimed the residual is erased (−$27 → +$55.86). That was an arithmetic
error — it added the locked total to the close-leg net, but the residual does NOT vanish.
The stranded shares are the LOSING side and still score $0; buying winners at ~$1 to win
~$1 changes nothing. Worked example (…4200): cost $18.70 + close 20×$0.9995 = $19.99 →
$38.69 total; payout $10 + $20 = $30; net −$8.69 vs −$8.70 before — one cent saved.
The operator's "won't change PNL" is confirmed by the market data for late closes.
Two readings: (a) late closes (last ~60 s, px ≥ 0.985) are a wash — paying face to win
face while the dead shares stay dead; (b) earlier closes (M2–M3 prints, e.g. …1400 @ 0.675
→ +$6.50, …6900 @ 0.835 → +$3.30, …9600 @ 0.775 → +$2.25) WOULD have helped — but that is
exactly what the rescue engine already does while the book is quotable (observed rescues
at 0.54–0.75). Caveats: sparse last-trade prints (~5/window), no spread/depth/taker fee —
real fills worse. Bottom line: once the market is decided and the needed side costs ~face,
no close can recover the strand. The only lever is never building big strands (knob 9;
entry freeze dropped — §11).

## 6. Ranked recommendation list

| rank | lever | mechanism | evidence (numbers) | expected net effect | risk | confidence | falsification test | required N | impl. cost |
|---|---|---|---|---|---|---|---|---|---|
| 1 | L4 single strict gap-veto knob `maxShareLead` (DONE 2026-11-10: v2.3 = 20, max hold 19, hidden +5 allowance deleted; veto labelled `unhedged-cap` in decisions log) | knob value unreachable by construction (lead + shares >= knob skipped) | imb-20 mean −$6.20 vs imb-10 −$3.07; 6 of 11 losses are imb-20 | further tightening = set knob 9 (max hold 8): tail ≈ −$82 → ≈−$35 at identical strand rate, zero philosophy change | more partial closes → somewhat less locked; curve §4 | **Med-High** | strand rate same but max imb ≤ 8 over next 60 | 60 | one number |
| — | NEW decided-market entry freeze (log-driven) — DROPPED by measurement 2026-11-10 (§11) | stop opening NEW dips after N consecutive all-skip evaluations | 1 dip fill after decision in 19 loser windows — the bot already buys nothing late (cheap side falls below the 7¢ floor); freeze saves ~$0 | — | — | n/a | — | — | — |
| 3 | L2 capability flags (behavior-preserving hygiene) | version bumps stop silently changing behavior; flags mirror CURRENT v2.3 behavior exactly (gate OFF, lead 15, atomic OFF) | §F: 4 behaviors keyed off one string suffix | prevents recurrence; P&L effect zero by construction | touches hot path; must keep 119 tests green | **High** | grep zero `endswith("v2` in executor; paper behavior identical | 0 | small-medium |
| 4 | L7/L8 adaptive rescue cap by time-to-close | accept worse pair cost as cutoff nears (0.995 → ~1.00+); alternative is 100% loss | rescue max-out sits exactly at 0.995; decided-phase fillability UNKNOWN from fills | more late closes complete IF quotes exist | worse realized pair costs; needs log proof of quotes first | **Low-Med** | decisions log shows rescue-side quotes ≤1.00 during M2–M4 skips | 1 log session, then 60 | small |
| — | L1 pre-flight gate — DROPPED (operator 2026-11-10) | refuse speculative dips | 0/32 vs 11/30 | contradicts fill-throughout design; rejected as direction | — | n/a | — | — | — |
| — | L5 forced-flatten ≤$1.005 — DROPPED (operator 2026-11-10) | override caps to close at any px ≤1.005 | stranded windows silent after M0–M2; fillability at 0.99+ unproven from fills | operator: won't change PNL; ledger can neither prove nor refute — decisions log will | — | n/a | decisions log: deficit-side quotes present/absent in decided phase | 1 session | — |
| 5 | L10 engine-level flat invariant | structural, not probabilistic | §B separator is perfect (100%/0%) | strands become impossible, not rare | eng. cost; interacts with CONSTRAINTS pacing | **Med** | invariant holds on 100 consecutive windows | 100 | medium |
| 6 | L3 symmetric/neutral open | allow `maxFillPrice` → 0.55–0.88 or require two-sided open | all 30 first-fills ≤0.45; first-fill win rate 60% (no edge) | removes built-in underdog bias; costs more capital/fill | more $/window at risk; may reduce locked/share | **Med** | first-fill median ≥ 0.47 AND strand rate drops | 60+ | one number + branch |
| 7 | L7 consistent rescue caps | make 0.995 closable when book is 0.99 | rescue max-out at exactly 0.995 (cap binds by construction at the top) | more closes complete; slightly worse pair costs | higher realized pair cost per rescue | **Low-Med** | instrumented runs: cap-bind rate drops, closes complete | instrumented 20–30 h | small |
| 8 | L6 widen/lengthen sweep | T-75→T-90 s, T-12→T-8 s; relax `rescueCeilingPrice` | 0 M3/M4 fills in losers vs 49 in winners | more room to close | more taker fills; settlement risk near cutoff | **Low** | M3/M4 fills appear in would-be stranded windows | 60+ | small, risky |
| 9 | L8 size closes vs pair cost + tail | EV rule: close 20 sh at 0.9999 (−$0.20) beats −$9 strand | marginal math §E (10¢ locked vs $9 tail) | principled rescue sizing | needs explicit EV policy, not one line | **Med** | rescue policy doc + backtest on fills | 30 (fills) + forward | medium |
| 10 | L9 joint retune clips/maxShares/lead | 10/45/15 vs v2.2's 10/60/30 | §G table | unknown interaction | tuning one in isolation lies | **Low** | A/B each factor once | 100+ per factor (`ab_test.py` N≈113) | medium |

### Top-3 concrete diffs (against current repo style, CONSTRAINTS-compatible)

**L4 (single gap-veto knob — DONE 2026-11-10)** — one strict rule `lead + shares >= maxShareLead → skip` (no per-version min(), no hidden allowance); v2.3 `maxShareLead: 15.0 → 20.0` (max hold 19, dashboard square relabelled "Gap veto ≥20 sh"). Further tightening = set knob 9 (max hold 8). Re-tune after 60 windows. Supersedes the proposal below, which is RETIRED per operator direction (fill-throughout design; no atomic, no entry gate):

~~**L1+L2 (one change): capability-flagged pre-flight gate** — `bot/constants.py`:~~
```json
"dangerously-skip-permissions-v2.4": { "entry": {
  "clipSharesDefault": 10.0, "maxShares": 45.0, "minFillPrice": 0.07, "maxFillPrice": 0.45,
  "benchmarkPairCost": 0.965, "targetPairCost": 0.965, "maxPairCost": 0.985,
  "maxShareLead": 15.0, "freezeLead": 15.0, "rescuePairCostMax": 0.995,
  "rescueCeilingPrice": 0.985, "preflightHedgeGate": true, "atomicSizing": false,
  "constantRiskSizing": true, "stopBeforeCloseSec": 75, ... } }
```
`bot/executor.py`: replace `is_v22 = strategy_id.endswith("v2.2")` with
`caps = C.STRATEGY_SETUPS.get(strategy_id, {}).get("entry", {})`,
`preflight_gate = bool(caps.get("preflightHedgeGate", False))`, and gate the dip branch on
`preflight_gate` instead of `is_v22`. Same for `lead_cap` (derive from `caps` + sizing mode)
and `atomic_bypass` (from `atomicSizing`). Delete all `.endswith("v2…")` tests. Per operator
correction: v2.3 keeps NO atomic path and NO pre-flight gate — flags mirror current behavior
(gate OFF, lead 15, atomic OFF); this refactor is P&L-neutral hygiene, not a behavior change.

~~**L5 (forced flatten)** — RETIRED per operator 2026-11-10 (fillability unproven; won't-change-PNL).~~

**Decided-market freeze (after 1 log session)** — in `trade_window`, count consecutive
all-skip evaluations from the in-memory decision stream (not throttled events); after N
(tune from `decisions.jsonl`, start N=40 ≈ 10 s of silence), refuse NEW dips (`deficit <= 0`
branch) while still allowing deficit-closing rescues. Micro-cycles preserved; strand-feeding cut.

## 7. v2.4 parameter table

| parameter | v2.3 | proposed v2.4 | rationale (#) | tolerance |
|---|---|---|---|---|
| `preflightHedgeGate` (new) | n/a (OFF via `endswith`) | **false** (hygiene flag mirroring current behavior; L1 dropped per operator) | §F | do not enable without operator sign-off |
| `maxShareLead` (single gap knob: freeze + veto) | 20 | **11** (max hold 10; 9 would starve fresh 10 sh dips) | 19/19 losers touched gap 20 (§11); worst strand −$8.70 → ≈−$4.50 | ±2 after 60 windows |
| overshoot allowance | **deleted 2026-11-10** (was hardcoded `lead_cap + 5.0`) | n/a — single strict rule | knob value unreachable by construction | — |
| decided-market freeze (new) | none | **dropped** — 1 dip fill after decision in 19 losers (§11); saves ~$0 | measured zero | — |
| forced-flatten rule | none | **dropped** (operator 2026-11-10) | fillability unproven; won't-change-PNL per operator | decisions log settles fillability |
| `maxFillPrice` | 0.45 | **0.45** (hold; fill-throughout design) | cheap-only open is by design; first-fill win rate 60% (no edge) | A/B only |
| `rescuePairCostMax` | 0.995 | **1.00 in last 2 min** (separate bet, own 60 windows) | quotes proven present late (§11); closing 20-gap at pc 1.00 costs cents vs −$8.70 strand | revert if realized rescue pc > 1.00 with no strand-rate drop |
| `stopBeforeCloseSec` / sweep | 75 / T-12 | **75** / hold (widen only in C-arm) | time is not the binder (§C) | A/B only |
| `clipSharesDefault` / `maxShares` | 10 / 45 | **hold** | interaction effects unmeasured (L9) | `ab_test.py` N≈113 per factor |
| risk block | 500 / 4000 / 500 | **unchanged** (CONSTRAINTS) | never bound; not the cause (§H) | do not weaken |

## 8. What I could not determine (NOT DETERMINABLE + cost to settle)

1. **Which sweep gate fired** (price vs pair-cost vs code-path) — ✅ IMPLEMENTED 2026-11-10:
   `bot/live_paper.py log_decision()` writes every evaluation (fill AND skip, unthrottled) with
   quotes, projected pair cost, deficit and the guard (`subReason`) to
   `<run>/decisions.jsonl` (schema: ts/slug/minute/inSweepPhase/imbalance/fills/cost/action/
   outcome/price/shares/role/reason/subReason/projectedPairCost/shareDeficit/quotes).
   One live session with this log settles it. Engine behavior untouched; 119 tests pass.
2. **Whether stranded deficits were closable at all** (quotes, depth, queue position) — ✅ SETTLED
   2026-11-10 (§11): quotes stream continuously through the last evaluation minute in every
   window (book-exit theory dead). Closes fail on PRICE (lagging side 0.97–1.00 > all caps),
   not on missing quotes. Depth/queue position still unproven (paper assumes touch-fill).
3. **True refusal rate** — refuse EVENTS throttled to 1/10 s per category (941 logged ≪ actual
   evaluations). The loop itself decides on every tick-wake (≤250 ms); only the event *logging*
   is throttled, not the decision-making. `decisions.jsonl` now records the true rate — expect
   ~hundreds of evaluations per window vs a handful of logged refuses.
4. **Maker-fill realism** — paper assumes touch-fill, no queue/depth/partials, 0% maker fee. Every
   P&L number is conditional on this; live fills will be worse on entries and better on fees.
   Settle with small-size live or shadow-book replay.
5. **BTC spot / order-flow context** — no spot series, no book history, no fee schedule beyond the
   modeled taker fee. Directional questions ("did the market trend?") are NOT DETERMINABLE.
6. **Post-snapshot windows** (`…2600` onward, incl. pending `…4100`) — excluded by snapshot
   discipline; re-run this script with a new cutoff to extend.

## 9. Confidence ledger

| claim | conf | evidence | what raises it |
|---|---|---|---|
| 11/11 losses are stranded residuals | **High** | §B table, 100%/0% split, exact identity | independent re-run of script |
| v2.2→v2.3 delta is the missing gate | **High** | code read + 0/32 vs 11/30 + clip/first-fill fingerprints | A/B: v2.4-gate-ON next 30 |
| locked engine got better (+$55 vs +$18) | **High** | decomposed totals both runs | forward run confirmation |
| sweep time is not the binder | **Med** | 126 attempts available, 0 taken | §C instrumentation |
| first-fill cheap-side bias hurts | **Med** | all ≤0.45 + 60% win rate (no edge) + dead (0.45,0.55] branch | A/B symmetric-open arm |
| rescue caps bind at the top | **Low-Med** | max-out at exactly 0.995 | quote-level logs |
| any 30-window parameter conclusion | **Low** (stated) | n=30; `ab_test.py` wants N≈113 | 60–113 windows per lever |
| 19/19 losers touched gap 20 (57-window) | **High** | reconstructed max |up−dn| per window file | forward run confirmation |
| losers die of size, not price | **High** | loser pc med 0.955 vs winner 0.992; final books lopsided | forward run confirmation |
| entry freeze saves ~$0 | **High** | 1 late dip fill in 19 losers | none needed — dropped |
| book never exits; price kills | **High** | quotes present every minute to last eval in 8/8 logged windows | depth/queue still unproven |
| strand built in M0 at fair prices | **High** | 462 M0 fills pre-decision in sample; 139 exact-20 slips all M0-ish | forward run confirmation |

## 10. Falsifiable predictions (next 60 settled windows of v2.4 = v2.3 + knob 9 [+ rescue-cap bet])

1. Max gap **≤ 10 in every window** (was 20 in 19/19 losers) — checkable in `decisions.jsonl`.
2. Worst single-window loss **≥ −$5.00** (was −$8.70).
3. Tail loss **halved vs −$46.10/54 pace** at equal-or-lower strand rate.
4. Locked capture **≥ $40 per 30** (knob costs some M0 volume; winners already pay 0.992).
5. Net **> $0 per 30** with win rate **≥ 65%** (break-even falls as avg loss shrinks).
6. `unhedged-cap` vetoes appear in the log (proof the knob binds); zero holds ≥ 11 shares.
7. First-fill price distribution **unchanged** (knob caps quantity, doesn't relocate price).

---

## 11. 57-window re-analysis with decisions log (2026-11-10, supersedes §§1–10 where they differ)

Sample: 57 window files, 54 resolved, net **−$46.10**, **35W / 19L**. Winners +$1–$5
(top +4.87, +4.15, +3.60); losers −$3.00 to −$8.70. Avg win still can't cover avg loss — tail problem.

1. **19/19 losers touched gap 20** (max |Up−Dn| = 20 in every losing window; two newest stopped
   at 15). Winners touch 20 too — then close it (one touched 60 mid-flight, closed all, +$3.60).
   Gap-20 is the scene of every loss; closing is the difference between +$2 and −$8.
2. **Losers die of size, not price.** Loser median pair cost 0.9549 (max 0.9641) vs winner median
   0.9917 (max 0.9948). Winners *pay up* to complete pairs (299 stamped rescues, 0.985–0.995,
   cap binding exactly at 0.995). Losers end 30/10, 20/40, 50/30 — small lopsided books with the
   big side losing. The money is in shares that never got hedged.
3. **Entry freeze saves ~$0 — DROPPED.** 1 dip fill ($3.80) after the market visibly decided
   (|px−0.50| > 0.30) across all 19 losers. The bot already buys nothing late (losing side falls
   below the 7¢ floor). No freeze rule can beat zero.
4. **Book-exit theory dead.** Sample stranded window: 13,284 evaluations, quotes streaming through
   the final minute (Up 0.99 / Down 0.01). M0 built the strand (462 fills at fair 0.37–0.65);
   M1 decided (3,929 skips, 5 fills); M2–M3 4,400 evals, 0 fills, 100% ceiling-price-skip.
   The killer is price (lagging side 0.97–1.00 > all caps), never missing quotes.
5. **How 20 was reached with "cap 15" (log proof): 139 leading-side dip fills** with lead 10 +
   order 10 = 20, mostly in M0 — waved through because the old rule was `>` (20 > 20 is false),
   and 10-share clips jump the 15–19 freeze zone entirely. The single strict `>=` knob with no
   allowance closes exactly this hole (see §6 L4).
6. **Decisions log health:** 111,797 evaluations, 0 malformed; ceiling-price-skip 107,632 /
   rescue-equalizer 1,091 / maker-dip-ladder 407 / hedge-equalizer 262. `unhedged-cap` 0 hits in
   the 2 windows under the new code (no gap near 20 built yet — nothing to block).
7. **v2.4 verdict: knob 20 → 11, nothing else.** (9 would veto every fresh 10 sh dip — starvation;
   11 keeps 0+10 fills open while 10+10 is vetoed; max hold 10.) Worst strand −$8.70 → ≈−$4.50,
   tail ≈ −$136 → ≈−$70 at identical strand rate. Rescue cap 0.995 → 1.00 in last 2 min rides as a separate
   bet (EV lopsided, hittability unproven). Everything else stays dropped. Judge on 60 windows:
   max gap ≤ 10 everywhere, worst loss ≥ −$5, tail halved.

---

### Design decisions the operator got wrong (as instructed)

1. **`maxFillPrice = 0.45` as a "risk" control is a directional bet.** It deletes the (0.45, 0.55]
   half of the opening branch and forces every open onto the underdog side. Cheap ≠ safe.
2. **Constant-$4.50 dip risk controls the *entry*, not the *position*.** Ten safe $4.50 dips in one
   direction = one $45 directional position. The cap that matters (terminal imbalance) was left at
   15+5 while the entry gate was removed — the exact wrong combination.
3. **`rescuePairCostMax = 0.995` looks prudent and acts decoratively.** Every rescue passes it
   (median 0.9912, max exactly 0.995) while the window dies of the quantity it doesn't cover.
   A per-fill price cap cannot fix a terminal-quantity problem.
4. **`.endswith("v2.2")` as a feature flag** meant v2.3 silently shipped without v2.2's headline
   safety feature. Version strings are names, not capabilities.
5. **The `strategy: hapcs-v1` window field** has been lying in every file (serializer hardcodes
   `C.STRATEGY_ID`); analysis that groups by it misattributes all v2.3 windows. One-line fix,
   real consequences.
6. **Throttled refuse logging** makes the most-asked question ("why didn't it close?") unanswerable
   from the dataset. Throughput protection (1/10 s events) should never have been applied to the
   *decision audit trail* — count in memory, sample to disk.
