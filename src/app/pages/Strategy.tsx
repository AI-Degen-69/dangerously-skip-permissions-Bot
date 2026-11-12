import {
  Activity,
  AlertTriangle,
  BookOpen,
  Clock,
  Coins,
  Cpu,
  Layers,
  Radio,
  ShieldAlert,
  ShieldCheck,
  Sigma,
  SlidersHorizontal,
  Target,
  TrendingUp,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'

import { Badge, Button, Card, PageHeader } from '../components/ui'
import { BOT_ORIGIN, useBotControl, useStrategySetups, mergeStrategySetups, type StrategySetup } from '../lib/bot'
import { STRATEGY_PRESETS } from '../botDefaults'

// ----------------------------------------------------------------------
// This page documents whatever setup bot/config.json currently selects.
// Every number below is read from the active setup's live entry block, so
// switching setups on the Config page changes this text. The only fixed
// content is the reference tape section, which is explicitly not live.
// ----------------------------------------------------------------------

const HARD_CUTOFF_S = 12 // bot/constants.py HARD_CUTOFF_SBC
const PRE_OPEN_S = 10 // bot/constants.py PRE_OPEN_PIPELINE_S

const cents = (v: number | undefined | null) => {
  if (v == null) return '—'
  const c = Math.round(Number(v) * 1000) / 10 // 0.985 -> 98.5, 0.45 -> 45
  return `${Number.isInteger(c) ? c : c.toFixed(1)}¢`
}
const usd = (v: number | undefined | null, digits = 3) => (v == null ? '—' : `$${Number(v).toFixed(digits)}`)
const sh = (v: number | undefined | null) => (v == null ? '—' : `${Number(v)} sh`)

/** Sizing sentence + dollar cost of one clip, derived from the active entry block. */
function sizingLine(picked: StrategySetup) {
  const { entry } = picked
  const curve = entry.dipCurve
  if (curve) {
    return {
      label: 'Inverse-dip curve',
      value: `${sh(curve.sharesLo)} at ${cents(curve.lo)} → ${sh(curve.sharesHi)} at ${cents(curve.hi)} (linear)`,
      cost: `One clip costs ≈ $${(Number(curve.sharesLo) * Number(curve.lo)).toFixed(2)} at the bottom of the band and ≈ $${(Number(curve.sharesHi) * Number(curve.hi)).toFixed(2)} at the top.`,
    }
  }
  return {
    label: 'Clip sizing',
    value: `${sh(entry.clipSharesDefault)} default · ${sh(entry.maxShares)} max`,
    cost: 'Deficit-closing fills snap straight to the deficit instead of the default clip.',
  }
}

function specRows(picked: StrategySetup) {
  const e = picked.entry
  const sizing = sizingLine(picked)
  const gapUsd = Number(e.maxUnhedgedUsd ?? 0)
  const lead = Number(e.maxShareLead)
  const rescuePx = e.rescueCeilingPrice
  const rescuePc = e.rescuePairCostMax
  return [
    {
      key: 'Fresh dip band',
      value: `${cents(e.minFillPrice)} – ${cents(e.maxFillPrice)}`,
      note: 'Only prices inside this band are bought as fresh dips. Above it the engine waits for a hedge instead of chasing.',
    },
    { key: sizing.label, value: sizing.value, note: sizing.cost },
    {
      key: 'Pair-cost gates',
      value: `fresh ≤ ${usd(e.targetPairCost)} · gap-close ≤ ${usd(e.maxPairCost)}${rescuePc ? ` · rescue ≤ ${usd(rescuePc)}` : ''}`,
      note: 'A pair must cost under $1.00 to be entered. Closing an existing deficit is allowed a wider gate because the alternative is a naked leg.',
    },
    {
      key: 'Unhedged gap cap',
      value: gapUsd > 0 ? `≈ ${usd(gapUsd, 2)} of net unhedged cost · ${sh(lead)} share knob` : `never ${sh(lead)} on one side`,
      note: gapUsd > 0
        ? `The dollar cap does the work; the ${sh(lead)} share knob is a second limit the engine never reaches. Paired volume stays uncapped.`
        : `The share knob is a strict veto, so the largest unhedged lead ever held is ${sh(lead - 1)}.`,
    },
    {
      key: 'Rescue hedge ceiling',
      value: `${cents(rescuePx)} per share${rescuePc ? ` at pair cost ≤ ${usd(rescuePc)}` : ''}`,
      note: `Much higher than the ${cents(e.maxFillPrice)} fresh-dip ceiling: this is the price of closing a leg that would otherwise redeem at $0.00.`,
    },
    {
      key: 'Late cutoff',
      value: `no new dips after T−${e.stopBeforeCloseSec}s · hard stop T−${HARD_CUTOFF_S}s`,
      note: 'Between the two the loop only equalizes an existing imbalance with resting maker orders.',
    },
    {
      key: 'Fill spacing',
      value: `${e.minSpacingMoveSec}s after a price move · ${e.minSpacingStaticSec}s on a static quote`,
      note: 'Prevents double-filling the same quote and thins out to 0.5s while a deficit is being closed.',
    },
    {
      key: 'Fees',
      value: '0% maker · taker 0.07 · p · (1 − p)',
      note: 'Passive fills pay nothing. The parabolic taker fee peaks at 1.75¢/share at 50¢.',
    },
    {
      key: 'Window risk caps',
      value: '500 fills per window · daily stop −$500 · 1 window at a time',
      note: 'Enforced by check_window() before every clip, and by the daily settled-PnL check.',
    },
  ]
}

const CALIBRATION_SUMMARY = [
  {
    band: '0.01 – 0.07',
    role: 'Refused (Dust / Lottery Tail)',
    fills: '170 (1.7%)',
    implied: '4.5%',
    actualWin: '0.6%',
    roiPct: '−89.8%',
    verdict: 'Blocked by the 7¢ price floor',
    tone: 'danger' as const,
  },
  {
    band: '0.07 – 0.30',
    role: 'Deep Maker Dip Ladder',
    fills: '2,949 (28.8%)',
    implied: '19.1%',
    actualWin: '19.8%',
    roiPct: '+3.7%',
    verdict: 'Lowers avg cost and accumulates shares at 0% fee',
    tone: 'success' as const,
  },
  {
    band: '0.30 – 0.50',
    role: 'Core Maker Straddle Grid',
    fills: '3,932 (38.4%)',
    implied: '40.2%',
    actualWin: '41.9%',
    roiPct: '+4.2%',
    verdict: 'Primary liquidity-provision zone, mostly passive maker',
    tone: 'success' as const,
  },
  {
    band: '0.50 – 0.75',
    role: 'Mid-Band Dead Zone',
    fills: '1,475 (14.4%)',
    implied: '60.8%',
    actualWin: '59.4%',
    roiPct: '−2.3%',
    verdict: 'No fresh buys; only a deficit hedge may fill here',
    tone: 'warning' as const,
  },
  {
    band: '0.75 – 0.95',
    role: 'Dynamic Pairing Equalizer',
    fills: '1,706 (16.7%)',
    implied: '83.1%',
    actualWin: '90.1%',
    roiPct: '+8.4%',
    verdict: 'High-conviction share catch-up on the lagging side',
    tone: 'accent' as const,
  },
  {
    band: '0.90 – 0.975',
    role: 'Reference-only: M4 snipe tail',
    fills: 'Tape tail',
    implied: '93.5%',
    actualWin: '98.2%',
    roiPct: '+4.8%',
    verdict: 'DSP setups never buy fresh here — only hedge a deficit',
    tone: 'info' as const,
  },
  {
    band: '0.975 – 1.00',
    role: 'Refused (Ceiling Tail)',
    fills: '4 (0.04%)',
    implied: '98.5%',
    actualWin: '75.0%',
    roiPct: '−20.7%',
    verdict: 'Blocked by the price ceiling',
    tone: 'danger' as const,
  },
]

const TOC = [
  {
    id: 'strategy-active',
    label: '1. What the Active Engine Does',
    short: '1. Active Engine',
    icon: Zap,
    children: [
      { id: 'core-thesis', label: 'The Sub-$1.00 Pair Arbitrage' },
      { id: 'four-pillars', label: 'Four Pillars of This Setup' },
    ],
  },
  {
    id: 'strategy-spec',
    label: '2. Active Parameters & Gates',
    short: '2. Parameters',
    icon: Sigma,
    children: [{ id: 'spec-table', label: 'Live Entry Block' }],
  },
  {
    id: 'strategy-lifecycle',
    label: '3. Window Lifecycle & Wiring',
    short: '3. Lifecycle',
    icon: Cpu,
    children: [
      { id: 'window-lifecycle', label: '300-Second Window' },
      { id: 'ws-and-api', label: 'Dual-Book & API Wiring' },
    ],
  },
  {
    id: 'strategy-risks',
    label: '4. Risks & Guardrails',
    short: '4. Risks',
    icon: ShieldAlert,
    children: [
      { id: 'failure-modes', label: 'When a Window Loses Money' },
      { id: 'guardrails', label: 'Active Safety Guardrails' },
    ],
  },
  {
    id: 'strategy-reference',
    label: '5. Reference Tape (Not Live)',
    short: '5. Reference Tape',
    icon: BookOpen,
    children: [{ id: 'tape-calibration', label: 'Price-Regime Calibration' }],
  },
] as const

const TOC_IDS = TOC.flatMap((item) => [item.id, ...item.children.map((child) => child.id)])

export function Strategy() {
  const control = useBotControl()
  const setupsQuery = useStrategySetups()
  const allSetups = mergeStrategySetups(setupsQuery.data?.setups, STRATEGY_PRESETS as unknown as Record<string, StrategySetup>)
  const pickedId = control.data?.strategy?.id ?? setupsQuery.data?.activeSetupId
  const picked = allSetups.find((s) => s.id === pickedId) ?? allSetups[0]
  const [activeId, setActiveId] = useState<string>(TOC[0].id)

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActiveId(entry.target.id)
        }
      },
      { rootMargin: '-10% 0px -70% 0px' },
    )
    for (const id of TOC_IDS) {
      const el = document.getElementById(id)
      if (el) observer.observe(el)
    }
    return () => observer.disconnect()
  }, [])

  const jumpTo = (id: string) => {
    setActiveId(id)
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const rows = picked ? specRows(picked) : []
  const entry = picked?.entry
  const others = allSetups.filter((s) => s.id !== picked?.id)
  const gapUsd = Number(entry?.maxUnhedgedUsd ?? 0)
  const rescuePx = entry?.rescueCeilingPrice
  const rescuePc = entry?.rescuePairCostMax

  return (
    <div className="mx-auto max-w-[1180px] p-5 sm:p-8">
      <PageHeader
        title={picked ? `Strategy · ${picked.symbol}` : 'Strategy'}
        subtitle={picked ? `${picked.name} — ${picked.signature}` : 'Waiting for the bot API to report the active setup.'}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="accent" className="font-mono font-semibold">
              {picked ? `${picked.symbol} · Active` : 'Engine'}
            </Badge>
            <Badge tone="info" className="font-mono text-[11px]">
              API {BOT_ORIGIN}
            </Badge>
            <Link
              to="/config"
              className="inline-flex h-8 items-center gap-1.5 rounded-tile border border-line-strong bg-surface px-3 text-[13px] font-medium shadow-[0_1px_1px_rgb(20_20_24/0.04)] hover:bg-surface-2"
            >
              <SlidersHorizontal className="size-3.5" /> Tune thresholds
            </Link>
          </div>
        }
      />

      {picked && entry && (
        <Card className="mt-5 border-accent/40 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="success">Currently picked: {picked.symbol}</Badge>
            <span className="text-[14px] font-semibold text-fg">{picked.name}</span>
            <Badge tone="neutral" className="font-mono text-[11px]">
              {picked.id}
            </Badge>
          </div>
          <p className="mt-1 font-mono text-[11.5px] text-muted">{picked.signature}</p>
          <p className="mt-2 text-[12.5px] leading-relaxed text-muted">{picked.description}</p>
          <div className="mt-3 flex flex-wrap gap-2 font-mono text-[11.5px]">
            <span className="rounded-[8px] border border-line bg-surface px-2 py-1">
              Band {cents(entry.minFillPrice)}–{cents(entry.maxFillPrice)}
            </span>
            <span className="rounded-[8px] border border-line bg-surface px-2 py-1">
              {entry.dipCurve
                ? `Curve ${entry.dipCurve.sharesLo}→${entry.dipCurve.sharesHi} sh`
                : `Clip ${entry.clipSharesDefault} / max ${entry.maxShares} sh`}
            </span>
            <span className="rounded-[8px] border border-line bg-surface px-2 py-1">
              {gapUsd > 0 ? `Gap cap $${gapUsd.toFixed(2)}` : `Gap veto ≥${entry.maxShareLead} sh`}
            </span>
            <span className="rounded-[8px] border border-line bg-surface px-2 py-1">
              Pair cap ${Number(entry.maxPairCost).toFixed(3)}
            </span>
            <span className="rounded-[8px] border border-line bg-surface px-2 py-1">
              Cutoff {entry.stopBeforeCloseSec}s
            </span>
          </div>
          {others.length > 0 && (
            <details className="mt-4 border-t border-line pt-3">
              <summary className="cursor-pointer text-[12.5px] font-medium text-muted hover:text-fg">
                {others.length} other setup{others.length === 1 ? '' : 's'} in the registry — not active
              </summary>
              <ul className="mt-2 space-y-1">
                {others.map((s) => (
                  <li key={s.id} className="flex flex-wrap items-baseline gap-2 text-[12px] text-faint">
                    <span className="font-mono text-[11.5px] text-muted">{s.symbol}</span>
                    <span>{s.name}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </Card>
      )}

      {/* Top Executive Banner */}
      {picked && entry && (
        <Card className="mt-5 border-accent/40 bg-accent-soft/15 p-6">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="accent">{picked.symbol}</Badge>
            <Badge tone="info">Dip band {cents(entry.minFillPrice)}–{cents(entry.maxFillPrice)}</Badge>
            <Badge tone="success">Fresh gate ≤ {usd(entry.targetPairCost)}</Badge>
            {gapUsd > 0 && <Badge tone="warning">Gap cap {usd(gapUsd, 2)}</Badge>}
            <Badge tone="neutral">Hold to redeem (no sells)</Badge>
          </div>

          <h2 className="mt-4 text-[17px] font-bold text-fg">
            How it works: buying $1.00 of guaranteed payout for under $1.00
          </h2>
          <p className="mt-2 text-[14px] leading-relaxed text-muted">
            A binary market pays exactly $1.00 to one outcome and $0.00 to the other. Buy 1 Up share and 1 Down
            share for a combined {usd(entry.targetPairCost)} and the pair is worth $1.00 at resolution no matter
            what BTC does. <strong className="font-semibold text-fg">{picked.symbol}</strong> spends the 300-second
            window accumulating both sides inside those gates: fresh dips only between{' '}
            <strong className="font-semibold text-fg">{cents(entry.minFillPrice)} and {cents(entry.maxFillPrice)}</strong>,
            then hedging the lagging side before the {entry.stopBeforeCloseSec}s cutoff.
          </p>

          <div className="mt-5 grid gap-3 sm:grid-cols-4">
            <div className="rounded-tile border border-line bg-surface p-3.5">
              <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-faint">
                <Coins className="size-3.5 text-success" /> Fresh dip band
              </span>
              <p className="mt-1.5 font-mono text-[16px] font-bold text-fg">
                {cents(entry.minFillPrice)} – {cents(entry.maxFillPrice)}
              </p>
              <p className="text-[11.5px] text-muted">Above the band: hedge only, never a fresh buy</p>
            </div>

            <div className="rounded-tile border border-line bg-surface p-3.5">
              <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-faint">
                <Layers className="size-3.5 text-accent" /> Clip sizing
              </span>
              <p className="mt-1.5 font-mono text-[16px] font-bold text-fg">
                {entry.dipCurve ? `${entry.dipCurve.sharesLo}→${entry.dipCurve.sharesHi} sh` : `${entry.clipSharesDefault} sh`}
              </p>
              <p className="text-[11.5px] text-muted">
                {entry.dipCurve ? `Fattest clips at ${cents(entry.dipCurve.lo)}, thinnest at ${cents(entry.dipCurve.hi)}` : `max ${entry.maxShares} sh`}
              </p>
            </div>

            <div className="rounded-tile border border-line bg-surface p-3.5">
              <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-faint">
                <ShieldCheck className="size-3.5 text-warning" /> Unhedged cap
              </span>
              <p className="mt-1.5 font-mono text-[16px] font-bold text-fg">
                {gapUsd > 0 ? usd(gapUsd, 2) : `${entry.maxShareLead} sh`}
              </p>
              <p className="text-[11.5px] text-muted">
                {gapUsd > 0 ? `net cost at risk · ${entry.maxShareLead} sh knob as backup` : 'net lead never reaches the knob'}
              </p>
            </div>

            <div className="rounded-tile border border-line bg-surface p-3.5">
              <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-faint">
                <Clock className="size-3.5 text-info" /> Cutoff
              </span>
              <p className="mt-1.5 font-mono text-[16px] font-bold text-fg">T−{entry.stopBeforeCloseSec}s</p>
              <p className="text-[11.5px] text-muted">sweep until T−{HARD_CUTOFF_S}s, then hold to redeem</p>
            </div>
          </div>
        </Card>
      )}

      {/* Quick Jump Bar */}
      <div className="mt-6 flex gap-2 overflow-x-auto pb-1" aria-label="Jump to section">
        {TOC.map((item) => {
          const isActive = activeId === item.id || item.children.some((child) => child.id === activeId)
          const Icon = item.icon
          return (
            <Button
              key={item.id}
              variant={isActive ? 'primary' : 'secondary'}
              size="md"
              onClick={() => jumpTo(item.id)}
              className="min-w-[165px] flex-1 whitespace-nowrap"
              aria-current={isActive ? 'true' : undefined}
            >
              <Icon />
              {item.short}
            </Button>
          )
        })}
      </div>

      <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_240px]">
        <div className="min-w-0 space-y-8">
          {/* ================================================================
              SECTION 1: WHAT THE ACTIVE ENGINE DOES
             ================================================================ */}
          <section id="strategy-active" aria-label="What the active engine does" className="scroll-mt-16 space-y-6">
            <Card id="core-thesis" className="scroll-mt-16 p-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-[16px] font-semibold text-fg">
                    1. What {picked?.symbol ?? 'the active setup'} actually does
                  </h3>
                  <p className="text-[13px] text-muted">Market-neutral volatility harvest, one 5-minute BTC Up/Down window at a time</p>
                </div>
                <Badge tone="success">Pairs under $1.00</Badge>
              </div>

              <p className="mt-4 text-[13.5px] leading-relaxed text-muted">
                On a simultaneous snapshot, <code className="font-mono text-fg">best_ask(Up) + best_ask(Down) &gt; $1.01</code>{' '}
                plus taker fees, so a bot that crosses the spread on both sides loses on every trade. This engine beats
                that spread with <strong className="font-semibold text-fg">asynchronous timing</strong> — buying Up
                when Up dips, then Down seconds or minutes later when Down dips — and with{' '}
                <strong className="font-semibold text-fg">passive maker bids</strong> that pay no fee.
              </p>

              <div id="four-pillars" className="mt-6 scroll-mt-16 space-y-3">
                <h4 className="text-[14px] font-semibold text-fg">The four pillars of this setup</h4>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-tile border border-line bg-surface-2/40 p-4">
                    <div className="flex items-center gap-2">
                      <Target className="size-4 text-success" />
                      <span className="text-[13.5px] font-semibold text-fg">1. Sub-$1.00 pair arbitration</span>
                    </div>
                    <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                      Every fill is simulated against current inventory before execution. Fresh dips need a projected
                      pair cost of <code className="font-mono">{usd(entry?.targetPairCost)}</code> or less; closing an
                      existing gap is allowed up to <code className="font-mono">{usd(entry?.maxPairCost)}</code>.
                      Anything at or above $1.00 is refused.
                    </p>
                  </div>

                  <div className="rounded-tile border border-line bg-surface-2/40 p-4">
                    <div className="flex items-center gap-2">
                      <TrendingUp className="size-4 text-accent" />
                      <span className="text-[13.5px] font-semibold text-fg">2. Price-aware clip sizing</span>
                    </div>
                    <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                      {entry?.dipCurve ? (
                        <>
                          Clips are linear in price: <code className="font-mono">{entry.dipCurve.sharesLo} sh</code> at{' '}
                          <code className="font-mono">{cents(entry.dipCurve.lo)}</code> falling to{' '}
                          <code className="font-mono">{entry.dipCurve.sharesHi} sh</code> at{' '}
                          <code className="font-mono">{cents(entry.dipCurve.hi)}</code>. Deep dips get size, the thin end
                          of the band gets a token clip, and dollars per clip stay in a narrow range.
                        </>
                      ) : (
                        <>
                          Dips are sized at <code className="font-mono">{entry?.clipSharesDefault} sh</code> by default,
                          up to <code className="font-mono">{entry?.maxShares} sh</code> when closing a deficit.
                        </>
                      )}
                    </p>
                  </div>

                  <div className="rounded-tile border border-line bg-surface-2/40 p-4">
                    <div className="flex items-center gap-2">
                      <Activity className="size-4 text-info" />
                      <span className="text-[13.5px] font-semibold text-fg">3. Deficit equalizer with rescue</span>
                    </div>
                    <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                      A cheap average pair cost only pays if both sides hold similar share counts. When one side leads,
                      the lagging side is bought first — at any price up to{' '}
                      <code className="font-mono">{cents(rescuePx)}</code>
                      {rescuePc ? <> with pair cost up to <code className="font-mono">{usd(rescuePc)}</code></> : null}.
                      Closing the naked leg beats letting it redeem at $0.00.
                    </p>
                  </div>

                  <div className="rounded-tile border border-line bg-surface-2/40 p-4">
                    <div className="flex items-center gap-2">
                      <ShieldCheck className="size-4 text-warning" />
                      <span className="text-[13.5px] font-semibold text-fg">4. Hard unhedged cap</span>
                    </div>
                    <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                      {gapUsd > 0 ? (
                        <>
                          A fill that would leave more than <code className="font-mono">{usd(gapUsd, 2)}</code> of net
                          unhedged cost is vetoed, and so is one that would push the leader to{' '}
                          <code className="font-mono">{entry?.maxShareLead} sh</code>. Once a side leads, only the
                          lagging side may be bought. Total paired volume is uncapped.
                        </>
                      ) : (
                        <>
                          A fill that would leave the leading side at or above{' '}
                          <code className="font-mono">{entry?.maxShareLead} sh</code> is vetoed, so that lead is never
                          held. Once a side leads, only the lagging side may be bought.
                        </>
                      )}
                    </p>
                  </div>
                </div>
              </div>
            </Card>
          </section>

          {/* ================================================================
              SECTION 2: ACTIVE PARAMETERS & GATES
             ================================================================ */}
          <section id="strategy-spec" aria-label="Active parameters" className="scroll-mt-16 space-y-6">
            <Card id="spec-table" className="scroll-mt-16 p-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-[16px] font-semibold text-fg">
                    2. Active parameters &amp; gates (<code className="font-mono text-[14px]">bot/config.json</code>)
                  </h3>
                  <p className="text-[13px] text-muted">
                    The entry block the engine re-reads at the start of every window — not a historical reconstruction
                  </p>
                </div>
                <Badge tone="neutral">{picked?.symbol ?? 'No setup'} · live values</Badge>
              </div>

              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[680px] text-left text-[12.5px]">
                  <thead className="border-b border-line text-[11px] font-semibold uppercase tracking-wider text-faint">
                    <tr>
                      <th className="py-2 px-2.5">Parameter</th>
                      <th className="py-2 px-2.5">Active value</th>
                      <th className="py-2 px-2.5">What it means</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {rows.map((r) => (
                      <tr key={r.key} className="hover:bg-surface-2/40">
                        <td className="py-2.5 px-2.5 font-mono text-[12px] font-semibold text-fg">{r.key}</td>
                        <td className="py-2.5 px-2.5 font-mono text-[12px] text-accent">{r.value}</td>
                        <td className="py-2.5 px-2.5 text-[12px] leading-relaxed text-muted">{r.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-[11.5px] text-faint">
                Source of truth: <code className="font-mono">bot/config.json</code>, mirrored in{' '}
                <code className="font-mono">bot/constants.py</code> and enforced by{' '}
                <code className="font-mono">bot/executor.py</code>. Change a value on the Config page and this table
                follows on the next refresh.
              </p>
            </Card>
          </section>

          {/* ================================================================
              SECTION 3: WINDOW LIFECYCLE & WIRING
             ================================================================ */}
          <section id="strategy-lifecycle" aria-label="Window lifecycle" className="scroll-mt-16 space-y-6">
            <Card id="window-lifecycle" className="scroll-mt-16 p-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-[16px] font-semibold text-fg">
                    3. Window lifecycle ({entry ? `T+${entry.startAfterOpenSec}s` : 'T+4s'} first fill, T−{entry?.stopBeforeCloseSec ?? 75}s
                    cutoff)
                  </h3>
                  <p className="text-[13px] text-muted">How one 300-second market is traded end to end</p>
                </div>
                <Badge tone="accent">Single-window lock</Badge>
              </div>

              <div className="mt-5 grid gap-3 sm:grid-cols-5">
                <div className="rounded-tile border border-line bg-surface-2/40 p-3.5">
                  <span className="font-mono text-[11px] font-bold uppercase text-info">0. T−{PRE_OPEN_S}s</span>
                  <p className="mt-1 text-[13.5px] font-semibold text-fg">Pre-open pipeline</p>
                  <p className="mt-1 text-[12px] leading-relaxed text-muted">
                    Market discovery and WebSocket book initialization before the window opens.
                  </p>
                </div>

                <div className="rounded-tile border border-line bg-surface-2/40 p-3.5">
                  <span className="font-mono text-[11px] font-bold uppercase text-danger">
                    1. T+0s – T+{entry?.startAfterOpenSec ?? 4}s
                  </span>
                  <p className="mt-1 text-[13.5px] font-semibold text-fg">Opening buffer</p>
                  <p className="mt-1 text-[12px] leading-relaxed text-muted">
                    No scheduled trading before the T+{entry?.startAfterOpenSec ?? 4}s threshold; the first fill is the
                    opening leg on the cheaper side.
                  </p>
                </div>

                <div className="rounded-tile border border-line bg-surface-2/40 p-3.5">
                  <span className="font-mono text-[11px] font-bold uppercase text-success">2. Grid &amp; equalizer</span>
                  <p className="mt-1 text-[13.5px] font-semibold text-fg">Dip curve, then hedge</p>
                  <p className="mt-1 text-[12px] leading-relaxed text-muted">
                    Fresh dips between {cents(entry?.minFillPrice)}–{cents(entry?.maxFillPrice)}; the lagging side is
                    hedged whenever a deficit exists.
                  </p>
                </div>

                <div className="rounded-tile border border-line bg-surface-2/40 p-3.5">
                  <span className="font-mono text-[11px] font-bold uppercase text-accent">3. T−{entry?.stopBeforeCloseSec ?? 75}s sweep</span>
                  <p className="mt-1 text-[13.5px] font-semibold text-fg">Maker-only close</p>
                  <p className="mt-1 text-[12px] leading-relaxed text-muted">
                    No new dips. While imbalanced, the gap is closed with resting no-fee orders until T−{HARD_CUTOFF_S}s.
                  </p>
                </div>

                <div className="rounded-tile border border-line bg-surface-2/40 p-3.5">
                  <span className="font-mono text-[11px] font-bold uppercase text-warning">4. T−{HARD_CUTOFF_S}s → settle</span>
                  <p className="mt-1 text-[13.5px] font-semibold text-fg">Cutoff &amp; redeem</p>
                  <p className="mt-1 text-[12px] leading-relaxed text-muted">
                    Zero fills. Inventory is held to binary resolution and the winning token redeems at $1.00.
                  </p>
                </div>
              </div>

              <div id="ws-and-api" className="mt-6 grid scroll-mt-16 gap-4 sm:grid-cols-2">
                <div className="rounded-tile border border-line bg-surface p-4">
                  <div className="flex items-center gap-2">
                    <Radio className="size-4 text-success" />
                    <h4 className="text-[14px] font-semibold text-fg">
                      Dual-book reads with no extra REST (<code className="font-mono text-[12.5px]">live_quote_pair</code>)
                    </h4>
                  </div>
                  <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
                    <code className="font-mono">live_bid_price()</code> reads{' '}
                    <code className="font-mono">book.best_bid</code> straight from the in-memory WebSocket orderbook,
                    so maker bids are distinguished from taker sweeps without doubling REST traffic. Spacing gates
                    fills by <code className="font-mono">{entry?.minSpacingMoveSec ?? 0.5}s</code> on a price change and{' '}
                    <code className="font-mono">{entry?.minSpacingStaticSec ?? 2.5}s</code> on a static quote.
                  </p>
                </div>

                <div className="rounded-tile border border-line bg-surface p-4">
                  <div className="flex items-center gap-2">
                    <Activity className="size-4 text-accent" />
                    <h4 className="text-[14px] font-semibold text-fg">
                      Desk API &amp; telemetry (<code className="font-mono text-[12.5px]">:5173 → :8789</code>)
                    </h4>
                  </div>
                  <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
                    The UI runs on port <code className="font-mono">5173</code> and{' '}
                    <code className="font-mono">bot/api.py</code> on <code className="font-mono">127.0.0.1:8789</code>.
                    Each fill streams its <code className="font-mono">role</code> (
                    <code className="font-mono">MAKER</code>/<code className="font-mono">TAKER</code>),{' '}
                    <code className="font-mono">subReason</code>, <code className="font-mono">feeUsd</code> and live{' '}
                    <code className="font-mono">pairCost</code> into the state file and the Live Fills table.
                  </p>
                </div>
              </div>
            </Card>
          </section>

          {/* ================================================================
              SECTION 4: RISKS & GUARDRAILS
             ================================================================ */}
          <section id="strategy-risks" aria-label="Risks and guardrails" className="scroll-mt-16 space-y-6">
            <Card id="failure-modes" className="scroll-mt-16 p-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-[16px] font-semibold text-fg">4. Risks &amp; what bounds them</h3>
                  <p className="text-[13px] text-muted">
                    When {picked?.symbol ?? 'the engine'} loses money on a window, and what stops the loss growing
                  </p>
                </div>
                <Badge tone="warning">
                  {gapUsd > 0 ? `${usd(gapUsd, 2)} max unhedged cost` : `${entry?.maxShareLead ?? 90} sh max unhedged lead`}
                </Badge>
              </div>

              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div className="rounded-tile border border-warning/30 bg-warning-soft/20 p-4">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="size-4 text-warning" />
                    <h4 className="text-[14px] font-semibold text-fg">Failure mode 1: one-way runaway open</h4>
                  </div>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                    If BTC trends straight up or down from the open without a pullback, the favored side never
                    re-enters the {cents(entry?.minFillPrice)}–{cents(entry?.maxFillPrice)} band and the first leg stays
                    naked. Only a rescue hedge — up to <code className="font-mono">{cents(rescuePx)}</code>
                    {rescuePc ? <> at pair cost <code className="font-mono">{usd(rescuePc)}</code></> : null} — can close
                    it, which turns a total loss into a thin one. The unhedged gap cap bounds how much can be exposed
                    before that hedge is forced.
                  </p>
                </div>

                <div className="rounded-tile border border-danger/30 bg-danger-soft/20 p-4">
                  <div className="flex items-center gap-2">
                    <ShieldAlert className="size-4 text-danger" />
                    <h4 className="text-[14px] font-semibold text-fg">Failure mode 2: V-reversal share imbalance</h4>
                  </div>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                    Cheap clips accumulate on the side that dipped. If BTC V-reverses late in the window, the other side
                    wins while the engine still holds fewer winning shares than dollars spent. Equalizing before the
                    T−{entry?.stopBeforeCloseSec ?? 75}s cutoff is what converts that into a small loss; if the quote
                    never becomes hedgeable under the gates, the window takes the full hit on the unhedged side.
                  </p>
                </div>
              </div>

              <div id="guardrails" className="mt-6 grid scroll-mt-16 gap-4 sm:grid-cols-3">
                <div className="rounded-tile border border-line bg-surface p-3.5">
                  <span className="font-mono text-[11px] uppercase text-faint">Unhedged exposure</span>
                  <p className="mt-1 text-[15.5px] font-bold text-fg">
                    {gapUsd > 0 ? usd(gapUsd, 2) : `${entry?.maxShareLead ?? 90} sh`}
                  </p>
                  <p className="text-[12px] text-muted">
                    {gapUsd > 0
                      ? `Net unhedged cost vetoed above the cap; the ${entry?.maxShareLead} sh knob is a backup`
                      : 'A fill leaving the leader at the knob is vetoed, so the knob is never held'}
                  </p>
                </div>

                <div className="rounded-tile border border-line bg-surface p-3.5">
                  <span className="font-mono text-[11px] uppercase text-faint">Per-window cap</span>
                  <p className="mt-1 text-[15.5px] font-bold text-fg">500 fills</p>
                  <p className="text-[12px] text-muted">Enforced by check_window() before every clip</p>
                </div>

                <div className="rounded-tile border border-line bg-surface p-3.5">
                  <span className="font-mono text-[11px] uppercase text-faint">Daily stop-loss</span>
                  <p className="mt-1 text-[15.5px] font-bold text-fg">$500.00 realized</p>
                  <p className="text-[12px] text-muted">Halts new entries once settled daily net PnL reaches −$500</p>
                </div>
              </div>
            </Card>
          </section>

          {/* ================================================================
              SECTION 5: REFERENCE TAPE — NOT LIVE CONFIG
             ================================================================ */}
          <section id="strategy-reference" aria-label="Reference tape" className="scroll-mt-16 space-y-6">
            <Card id="tape-calibration" className="scroll-mt-16 border-line-strong p-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-[15.5px] font-semibold text-fg">5. Reference tape: price-regime calibration</h3>
                  <p className="text-[12.5px] text-muted">
                    Measured on 10,007 settled fills of the HAPCS-v1 reconstruction tape (Nov 7–8, 2026)
                  </p>
                </div>
                <Badge tone="neutral">Evidence, not active config</Badge>
              </div>

              <p className="mt-3 rounded-tile border border-line bg-surface-2/40 p-3 text-[12.5px] leading-relaxed text-muted">
                This table is the historical evidence behind the 7¢ price floor and the mid-band skip. It comes from a
                different wallet and a different engine generation, so its names, fills and ROI figures do not describe
                the setup running now — nothing on this page above reads from it.
              </p>

              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[680px] text-left text-[12.5px]">
                  <thead className="border-b border-line text-[11px] font-semibold uppercase tracking-wider text-faint">
                    <tr>
                      <th className="py-2 px-2.5">Price band</th>
                      <th className="py-2 px-2.5">Tape regime</th>
                      <th className="py-2 px-2.5 text-right">Fills</th>
                      <th className="py-2 px-2.5 text-right">Price paid</th>
                      <th className="py-2 px-2.5 text-right">Actual win</th>
                      <th className="py-2 px-2.5 text-right">ROI / $</th>
                      <th className="py-2 px-2.5">What it implies</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {CALIBRATION_SUMMARY.map((row) => (
                      <tr key={row.band} className="hover:bg-surface-2/40">
                        <td className="py-2.5 px-2.5 font-mono font-semibold text-fg">{row.band}</td>
                        <td className="py-2.5 px-2.5">
                          <Badge tone={row.tone}>{row.role}</Badge>
                        </td>
                        <td className="py-2.5 px-2.5 text-right font-mono tabular-nums text-muted">{row.fills}</td>
                        <td className="py-2.5 px-2.5 text-right font-mono tabular-nums text-muted">{row.implied}</td>
                        <td className="py-2.5 px-2.5 text-right font-mono font-semibold tabular-nums text-fg">
                          {row.actualWin}
                        </td>
                        <td
                          className={`py-2.5 px-2.5 text-right font-mono font-semibold tabular-nums ${
                            row.roiPct.startsWith('+') ? 'text-success' : 'text-danger'
                          }`}
                        >
                          {row.roiPct}
                        </td>
                        <td className="py-2.5 px-2.5 text-[12px] text-muted">{row.verdict}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </section>
        </div>

        {/* Sticky Right-Hand Table of Contents */}
        <aside className="hidden lg:block">
          <nav aria-label="Table of contents" className="sticky top-6 rounded-card border border-line bg-surface-2/30 p-4">
            <p className="px-2 text-[11px] font-semibold uppercase tracking-wider text-faint">On this page</p>
            <ul className="mt-2 space-y-1.5">
              {TOC.map((item) => {
                const isActive = activeId === item.id || item.children.some((child) => child.id === activeId)
                return (
                  <li key={item.id}>
                    <a
                      href={`#${item.id}`}
                      onClick={(e) => {
                        e.preventDefault()
                        jumpTo(item.id)
                      }}
                      aria-current={isActive ? 'location' : undefined}
                      className={`block rounded-tile px-2 py-1.5 text-[12.5px] leading-snug transition-colors ${
                        isActive
                          ? 'bg-surface font-semibold text-accent shadow-sm'
                          : 'font-medium text-muted hover:bg-surface hover:text-fg'
                      }`}
                    >
                      {item.label}
                    </a>
                    <ul className="ml-2 mt-0.5 space-y-0.5 border-l border-line pl-3">
                      {item.children.map((child) => {
                        const childActive = activeId === child.id
                        return (
                          <li key={child.id}>
                            <a
                              href={`#${child.id}`}
                              onClick={(e) => {
                                e.preventDefault()
                                jumpTo(child.id)
                              }}
                              aria-current={childActive ? 'location' : undefined}
                              className={`block rounded-tile px-2 py-1 text-[12px] leading-snug transition-colors ${
                                childActive ? 'font-semibold text-accent' : 'text-faint hover:text-fg'
                              }`}
                            >
                              {child.label}
                            </a>
                          </li>
                        )
                      })}
                    </ul>
                  </li>
                )
              })}
            </ul>
          </nav>
        </aside>
      </div>

      <Card className="mt-6 flex flex-wrap items-center justify-between gap-3 p-5">
        <div className="flex items-start gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-tile bg-accent-soft text-accent">
            <BookOpen className="size-4.5" />
          </span>
          <div>
            <p className="text-[13.5px] font-medium text-fg">
              {picked ? `${picked.symbol} — ${picked.name}` : 'No active setup reported'}
            </p>
            <p className="text-[12.5px] text-muted">
              This page mirrors <code className="font-mono">bot/config.json</code>; the engine re-reads it every
              window. Running on port 5173 → {BOT_ORIGIN}.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Link to="/live" className="text-[12.5px] font-medium text-accent hover:underline">
            Watch live execution →
          </Link>
          <Link to="/config" className="text-[12.5px] font-medium text-fg hover:underline">
            Tune threshold settings →
          </Link>
        </div>
      </Card>
    </div>
  )
}
