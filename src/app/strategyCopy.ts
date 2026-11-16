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
  const balanced = sizing === 'balanced'
  const splitV18 = sizing === 'split-ladder-v18'
  const splitV19 = sizing === 'split-ladder-v19'
  const l3 = typeof f.l3Mode === 'string' ? f.l3Mode : 'patient'
  const risk = num(f.dollarRisk, 4.5)
  const uncapped = f.pairedVolumeCapped === false

  const t1body = empty
    ? 'Waiting for a candidate run — its live gates will appear here.'
    : splitV19 && l3 === 'immediate'
      ? `Clamped Maker (≤$0.990) with strict resting order hygiene on lead > 0.5 sh; Immediate Layer 3 taker equalizer (marginal pair ≥$1.00 & ask ≤72¢); single-window freeze latch prevents breakout re-accumulation.`
      : splitV19 && l3 === 'off'
      ? `Clamped Maker (≤$0.990) with strict resting order hygiene on lead > 0.5 sh; no Layer 3 taker bailout (pure maker execution); single-window freeze latch prevents breakout re-accumulation.`
      : splitV19
      ? `Clamped Maker (≤$0.990) with strict resting order hygiene on lead > 0.5 sh; Patient Layer 3 taker bailout delayed 20s (marginal pair ≥$1.07 & ask ≤72¢); single-window freeze latch prevents breakout re-accumulation.`
      : splitV18
        ? `Balanced rungs stay in 42–58¢ under $0.995 projected pair cost (Heavy-Side Floor Gate blocks <45¢ once heavy by >=10 sh); rebalance-maker bypasses pair-cost skips up to ${hiC}¢, and breakout rebalance-taker flattens deficits across 60–68¢ ask.`
        : balanced
          ? `No pair-cost gate anywhere: the lighter side is always eligible up to the ${hiC}c ceiling, and pair cost is computed per fill and reported against the $0.977 wallet benchmark instead of enforced.`
          : preflight
            ? `Hard ceiling (${rescue}) + Pre-Flight Gate: never buys an unhedged dip unless the opposite ask allows an immediate hedge under ${rescue}.`
            : `No pre-flight check. Fresh dips must project ${tgt} pair cost or better, deficit closes ${cap}, rescue ${rescue} — so entries keep flowing and equalize on the next swing.`

  const t2body =
    splitV19 && l3 === 'off'
      ? (hl.dipClips ?? `Two-sided simultaneous 5 sh maker resting at bid - 0.01 inside the 42–48¢ band at sub-$0.990 pair cost; zero taker fills.`)
      : splitV19
      ? (hl.dipClips ?? `Single 5 sh maker probe at bid - 0.01 inside the 42–49¢ ATM band; Layer 1 freezes at elapsed ≥ 150s or matched ≥ 40 sh. Any fill triggers immediate Layer 2 maker hedge at ≤$0.990.`)
      : splitV18
        ? (hl.dipClips ?? `2-level off-touch split ladder (-1¢, -2¢; 10→8 sh) inside 42–58¢; unblocked rebalance-maker splits deficits up to 10 sh at bid while 60–68¢ breakout triggers taker equalization.`)
        : balanced
          ? (hl.dipClips ?? `Both sides quoted together from the open; the lighter side is always bought first, top-ups close at most half the gap, size tilts to the cheaper side.`)
          : (hl.dipClips ??
        (empty
          ? 'Waiting for a candidate run — its live sizing will appear here.'
          : probe > 0
            ? `Leg-1 fresh clips capped at ${probe} sh unhedged probe; unlocks full ${mx} sh on Leg 2 and paired fills. Additional unhedged fills on the same side require an ${step}¢ step down.`
            : sizing === 'constant-risk'
              ? `Every dip sized as $${risk.toFixed(2)} / price (${clip} at ${hiC}c up to ${mx} at 10c), dips at ${hiC}c or cheaper only. No heavy bulk fills; no share veto while total paired volume ${uncapped ? 'has no cap' : 'is capped'}.`
              : sizing === 'confidence'
                ? `Sizes heavy (${mx} sh) on 100% risk-free atomic pairs and deficit equalizations, while micro-sizing speculative dips to ${clip} sh.`
                : `Dip clips of ${clip} sh (max ${mx} sh), dips at ${hiC}c or cheaper.`))

  return [
    {
      kicker: 'Tweak 1 · Hard Gate',
      badge: empty ? '—' : splitV19 && l3 === 'immediate' ? `≤$0.990 Clamp + Immediate L3` : splitV19 && l3 === 'off' ? `≤$0.990 Clamp, No Taker` : splitV19 ? `≤$0.990 Clamp + 20s L3` : splitV18 ? `3-Layer to ${hiC}c` : balanced ? `Max ${hiC}c, no gate` : preflight ? `Max ${rescue}` : `${tgt} fresh`,
      title: splitV19 && l3 === 'immediate' ? 'Clamped Maker + Immediate L3 + Freeze Latch' : splitV19 && l3 === 'off' ? 'Clamped Maker + Pure Maker + Freeze Latch' : splitV19 ? 'Clamped Maker + Patient L3 + Freeze Latch' : splitV18 ? '3-Layer Breakout Defense' : balanced ? 'Balance Rule, No Price Gate' : preflight ? 'Pre-Flight Arb Check & Cap' : 'Pair-Cost Gate & Cap',
      body: t1body,
    },
    {
      kicker: 'Tweak 2 · Intake',
      badge: empty ? '—' : splitV19 && l3 === 'off' ? `5 sh x 2 sides (42–48¢)` : splitV19 ? `5 sh x 1 level (42–49¢)` : splitV18 ? `10-8 sh x 2 rungs` : balanced ? `${clip}-${mx} sh` : probe > 0 ? `${probe}-${mx} sh` : sizing === 'constant-risk' ? `${clip}-${mx} sh` : sizing === 'confidence' ? `${mx} sh / ${clip} sh` : `max ${mx} sh`,
      title: splitV19 && l3 === 'off' ? 'Two-Sided 5 sh Resting (No Taker)' : splitV19 ? 'Single 5 sh Probe (T+150s / 40 sh Cutoff)' : splitV18 ? '2-Rung Split Ladder + Rebalance' : balanced ? 'Concurrent Accumulation' : probe > 0 ? 'Probe Sizing & Step Gate' : sizing === 'constant-risk' ? 'Constant Dollar-Risk Sizing' : sizing === 'confidence' ? 'Bi-Modal Confidence Sizing' : 'Dip Intake',
      body: t2body,
    },
    {
      kicker: 'Tweak 3 / Sweep',
      badge: empty ? '---' : `T-${cutoff}s / T-${sweep}s`,
      title: (balanced || splitV18 || splitV19) ? 'Stop + Sweep, No Rescue' : 'Stop + Sweep + Late Rescue',
      body: empty
        ? 'Waiting for a candidate run.'
        : splitV19 && l3 === 'immediate'
          ? `Stop opening at T-${cutoff}s; the sweep holds the balanced book to settlement down to T-${sweep}s. No late chase ladder — deficits equalize via clamped maker or immediate bailout.`
          : splitV19 && l3 === 'off'
          ? `Stop opening at T-${cutoff}s; the sweep holds the balanced book to settlement down to T-${sweep}s. No late chase ladder — deficits equalize via clamped maker only, never a taker.`
          : splitV19
          ? `Stop opening at T-${cutoff}s; the sweep holds the balanced book to settlement down to T-${sweep}s. No late chase ladder — deficits equalize via clamped maker or 20s delayed bailout.`
          : (balanced || splitV18)
            ? `Stop opening at T-${cutoff}s; the sweep holds the balanced book to settlement down to T-${sweep}s. No late chase ladder — breakout deficits equalize in 60–68¢ before stranding.`
            : `Stop opening at T-${cutoff}s, sweep deficits with resting maker orders down to T-${sweep}s, late rescue to ${lateMax} from T+${lateStart}s.`,
    },
  ]
}
