import type { AbTestDistributionStats, StrategySetup } from './lib/bot'

/**
 * Frontend mirror of bot/constants.py describe_setup().
 * Every word below is computed from the live entry numbers + behavior flags,
 * so changing a threshold automatically changes what the user reads.
 * Chips in Strategy.tsx / BotControlTile.tsx already render from entry;
 * the A/B tweak cards here complete the link.
 */

export interface TweakCard {
  kicker: string
  badge: string
  title: string
  body: string
}

type EntryLike = Partial<StrategySetup['entry']> & Record<string, number | boolean | undefined>

function num(v: unknown, fallback: number): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

function cents(v: unknown, fallback: number): number {
  return Math.round(num(v, fallback) * 100)
}

function money(v: unknown, fallback: number): string {
  return `$${num(v, fallback).toFixed(3)}`
}

export function tweakCards(candidate: AbTestDistributionStats | null | undefined): TweakCard[] {
  const e = (candidate?.entry ?? {}) as EntryLike
  const f = candidate?.features ?? {}
  const hl = candidate?.configHighlights ?? {}

  const clip = num(e.clipSharesDefault, 10)
  const mx = num(e.maxShares, 45)
  const hiC = cents(e.maxFillPrice, 0.45)
  const tgt = money(e.targetPairCost ?? e.benchmarkPairCost, 0.965)
  const cap = money(e.maxPairCost, 0.985)
  const rescue = money(e.rescuePairCostMax, 0.995)
  const cutoff = num(e.stopBeforeCloseSec, 75)
  const sweep = num(e.sweepBeforeCloseSec, 15)
  const lateMax = money(e.lateRescueMaxPairCost ?? e.rescuePairCostMax, 0.995)
  const lateStart = num(e.lateRescueStartSec, 210)
  const probe = num(e.unhedgedProbeShares, 0)
  const step = num(e.unhedgedStepCents, 0)
  const empty = !candidate?.entry || Object.keys(candidate?.entry ?? {}).length === 0

  const preflight = f.preflightGate === true
  const sizing = f.sizing ?? ''
  const splitV19 = sizing === 'split-ladder-v19'
  const twoSidedV20 = sizing === 'two-sided-dip-v20'
  const risk = num(f.dollarRisk, 4.5)
  const uncapped = f.pairedVolumeCapped === false

  const t1body = empty
    ? 'Waiting for a candidate run — its live gates will appear here.'
    : twoSidedV20
      ? `Two-sided mutual gate (≤${tgt} fresh); imbalance > 0.5 sh cancels heavy-side orders and hedges via profit-lock taker (≤${tgt}) or clamped maker (≤${cap}), sweeping ≤${rescue}. Never pays ≥$1.00; no freeze latch.`
      : splitV19
        ? `Clamped Maker (≤$0.990) with strict resting order hygiene on lead > 0.5 sh; Patient Layer 3 taker bailout delayed 20s (marginal pair ≥$1.07 & ask ≤72¢); single-window freeze latch prevents breakout re-accumulation.`
        : preflight
          ? `Hard ceiling (${rescue}) + Pre-Flight Gate: never buys an unhedged dip unless the opposite ask allows an immediate hedge under ${rescue}.`
          : `No pre-flight check. Fresh dips must project ${tgt} pair cost or better, deficit closes ${cap}, rescue ${rescue} — so entries keep flowing and equalize on the next swing.`

  const t2body =
    twoSidedV20
      ? (hl.dipClips ?? `Simultaneous two-sided resting orders: inverse-dip curve (33 sh @ 7¢ → 8 sh @ 45–47¢, -1¢ off-touch in ATM band), strictly capped to $${num(e.maxUnhedgedUsd, 6).toFixed(2)} unhedged USD.`)
      : splitV19
        ? (hl.dipClips ?? `Single 5 sh maker probe at bid - 0.01 inside the 42–49¢ ATM band; Layer 1 freezes at elapsed ≥ 150s or matched ≥ 40 sh. Any fill triggers immediate Layer 2 maker hedge at ≤$0.990.`)
        : (hl.dipClips ??
          (empty
            ? 'Waiting for a candidate run — its live sizing will appear here.'
            : probe > 0
              ? `Leg-1 fresh clips capped at ${probe} sh unhedged probe; unlocks full ${mx} sh on Leg 2 and paired fills. Additional unhedged fills on the same side require an ${step}¢ step down.`
              : sizing === 'constant-risk'
                ? `Every dip sized as $${risk.toFixed(2)} / price (${clip} at ${hiC}c up to ${mx} at 10c), dips at ${hiC}c or cheaper only. No heavy bulk fills; no share veto while total paired volume ${uncapped ? 'has no cap' : 'is capped'}.`
                : `Dip clips of ${clip} sh (max ${mx} sh), dips at ${hiC}c or cheaper.`))

  return [
    {
      kicker: 'Tweak 1 · Hard Gate',
      badge: empty ? '—' : twoSidedV20 ? `≤${cap} / Never ≥$1` : splitV19 ? `≤$0.990 Clamp + 20s L3` : preflight ? `Max ${rescue}` : `${tgt} fresh`,
      title: twoSidedV20 ? 'Two-Sided Mutual Gate + Sub-$1 Equalizer' : splitV19 ? 'Clamped Maker + Patient L3 + Freeze Latch' : preflight ? 'Pre-Flight Arb Check & Cap' : 'Pair-Cost Gate & Cap',
      body: t1body,
    },
    {
      kicker: 'Tweak 2 · Intake',
      badge: empty ? '—' : twoSidedV20 ? `2-Sided 7–${hiC}¢ (≤$${num(e.maxUnhedgedUsd, 6).toFixed(0)})` : splitV19 ? `5 sh x 1 level (42–49¢)` : probe > 0 ? `${probe}-${mx} sh` : sizing === 'constant-risk' ? `${clip}-${mx} sh` : `max ${mx} sh`,
      title: twoSidedV20 ? 'Simultaneous Two-Sided + Inverse-Dip Curve' : splitV19 ? 'Single 5 sh Probe (T+150s / 40 sh Cutoff)' : probe > 0 ? 'Probe Sizing & Step Gate' : sizing === 'constant-risk' ? 'Constant Dollar-Risk Sizing' : 'Dip Intake',
      body: t2body,
    },
    {
      kicker: 'Tweak 3 / Sweep',
      badge: empty ? '---' : `T-${cutoff}s / T-${sweep}s`,
      title: (splitV19 || twoSidedV20) ? 'Stop + Sweep, No Rescue' : 'Stop + Sweep + Late Rescue',
      body: empty
        ? 'Waiting for a candidate run.'
        : twoSidedV20
          ? `Stop opening at T-${cutoff}s; sweep crosses ≤${rescue} deficits (or rests clamped maker) down to T-${sweep}s with zero ≥$1.00 fills.`
          : splitV19
          ? `Stop opening at T-${cutoff}s; the sweep holds the balanced book to settlement down to T-${sweep}s. No late chase ladder — deficits equalize via clamped maker or 20s delayed bailout.`

            : `Stop opening at T-${cutoff}s, sweep deficits with resting maker orders down to T-${sweep}s, late rescue to ${lateMax} from T+${lateStart}s.`,
    },
  ]
}
