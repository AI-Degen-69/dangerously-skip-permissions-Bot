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
  const lead = num(e.maxShareLead, 15)
  const tgt = money(e.targetPairCost ?? e.benchmarkPairCost, 0.965)
  const cap = money(e.maxPairCost, 0.985)
  const rescue = money(e.rescuePairCostMax, 0.995)
  const cutoff = num(e.stopBeforeCloseSec, 75)
  const empty = !candidate?.entry

  const preflight = f.preflightGate === true
  const sizing = f.sizing ?? ''
  const risk = num(f.dollarRisk, 4.5)
  const uncapped = f.pairedVolumeCapped === false

  const t1body = empty
    ? 'Waiting for a candidate run — its live gates will appear here.'
    : preflight
      ? `Hard ceiling (${rescue}) + Pre-Flight Gate: never buys an unhedged dip unless the opposite ask allows an immediate hedge under ${rescue}.`
      : `No pre-flight check. Fresh dips must project ${tgt} pair cost or better, deficit closes ${cap}, rescue ${rescue} — so entries keep flowing and equalize on the next swing.`

  const t2body =
    hl.dipClips ??
    (empty
      ? 'Waiting for a candidate run — its live sizing will appear here.'
      : sizing === 'constant-risk'
        ? `Every dip sized as $${risk.toFixed(2)} / price (${clip} at ${hiC}c up to ${mx} at 10c), dips at ${hiC}c or cheaper only. No heavy bulk fills; net gap capped at ${lead} while total paired volume ${uncapped ? 'has no cap' : 'is capped'}.`
        : sizing === 'confidence'
          ? `Sizes heavy (${mx} sh) on 100% risk-free atomic pairs and deficit equalizations, while micro-sizing speculative dips to ${clip} sh.`
          : `Dip clips of ${clip} sh (max ${mx} sh), dips at ${hiC}c or cheaper.`)

  return [
    {
      kicker: 'Tweak 1 · Hard Gate',
      badge: empty ? '—' : preflight ? `Max ${rescue}` : `${tgt} fresh`,
      title: preflight ? 'Pre-Flight Arb Check & Cap' : 'Pair-Cost Gate & Cap',
      body: t1body,
    },
    {
      kicker: 'Tweak 2 · Intake',
      badge: empty ? '—' : sizing === 'constant-risk' ? `${clip}-${mx} sh` : sizing === 'confidence' ? `${mx} sh / ${clip} sh` : `max ${mx} sh`,
      title: sizing === 'constant-risk' ? 'Constant Dollar-Risk Sizing' : sizing === 'confidence' ? 'Bi-Modal Confidence Sizing' : 'Dip Intake',
      body: t2body,
    },
    {
      kicker: 'Tweak 3 · Sweep',
      badge: `T-${cutoff}s..15s Maker`,
      title: 'Passive Maker Sweep',
      body: `Fills remaining deficits with resting maker orders at 0% fee between T-${cutoff}s and T-15s, avoiding taker fee drag.`,
    },
  ]
}
