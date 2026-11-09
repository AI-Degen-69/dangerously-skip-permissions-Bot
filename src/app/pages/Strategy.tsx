import {
  Activity,
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Clock,
  Coins,
  Cpu,
  Layers,
  Radio,
  Scale,
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
import { BOT_ORIGIN } from '../lib/bot'

// ----------------------------------------------------------------------
// 🎯 HAPCS-v1 Strategy Documentation:
// Hybrid Arbitrage Pairing & Certainty Sniping v1
// Reconstructed quantitatively from 27,091 on-chain fills across two consecutive
// 24-hour ledgers (Nov 6–7: 17,416 rows; Nov 7–8: 10,748 rows) of wallet
// 0xc53375ff94e96100f2b30a4b5775db35218d69a9 on Polymarket 5m BTC Up/Down.
// ----------------------------------------------------------------------

const CONSTANTS_TABLE = [
  {
    name: 'STRATEGY_ID / SYMBOL',
    value: 'hapcs-v1 · 🎯 HAPCS-v1',
    location: 'bot/constants.py',
    meaning: 'Identifies the reconstructed Hybrid Arbitrage Pairing & Certainty Sniping v1 engine across API and UI.',
  },
  {
    name: 'STRADDLE_BAND',
    value: '[0.34, 0.55] (34¢ – 55¢, median 43¢)',
    location: 'bot/constants.py',
    meaning: 'Opening straddle IQR measured across the first 30 seconds (T+0..30s) in the 24h ledger (median 43¢). Opens on the cheaper side first before hedging the opposite side.',
  },
  {
    name: 'PRICE_FLOOR (minFillPrice)',
    value: '0.07 (7¢)',
    location: 'bot/constants.py · config.json',
    meaning: 'Hard lower bound. Fills below 7¢ went 1-for-170 (−89.8% ROI) on the tape and are strictly refused.',
  },
  {
    name: 'DIP_LADDER_MAX',
    value: '0.50 (50¢)',
    location: 'bot/constants.py',
    meaning: 'Upper bound of passive Maker Dip Grid [7¢–50¢]. 67.5% of fills accumulate the cheaper leg at 0% fee with resting limit bids.',
  },
  {
    name: 'DEAD_ZONE_BAND',
    value: '(0.50, 0.75) (50¢ – 75¢)',
    location: 'bot/constants.py',
    meaning: 'Mid-band dead zone (only 14.4% of tape fills). Skipped unless equalizing a share deficit at pair cost ≤ $0.965; pivots to opposite token dip instead.',
  },
  {
    name: 'HEDGE_FAV_BAND',
    value: '[0.75, 0.95] (75¢ – 95¢)',
    location: 'bot/constants.py',
    meaning: 'Dynamic Arbitrage Pairing (Lagging-Leg Equalizer). Fills here aggressively buy the lagging share side to lock in matched pairs (+5.7% to +11.5% ROI/$).',
  },
  {
    name: 'RESOLUTION_SNIPE_BAND',
    value: '[0.90, 0.975] (90¢ – 97.5¢)',
    location: 'bot/constants.py · executor.py',
    meaning: 'Minute 4 (T-60s) resolution certainty snipe window. Captures high-certainty winner resolution up to 97.5¢ subject to pair cost cap.',
  },
  {
    name: 'PRICE_CEILING (maxFillPrice)',
    value: '0.975 (97.5¢)',
    location: 'bot/constants.py · config.json',
    meaning: 'Hard upper price cap (up to 97.5¢ for Minute 4 certainty sniping). Fills > 97.5¢ are strictly refused.',
  },
  {
    name: 'HARD_CUTOFF_SBC (stopBeforeCloseSec)',
    value: '12s before close (T+288s)',
    location: 'bot/constants.py · config.json',
    meaning: '99.83% of all on-chain fills occur ≥ 12s before expiry; the final 11 seconds have zero fills across 24 hours.',
  },
  {
    name: 'PRE_OPEN_PIPELINE_S',
    value: '10s (T-310s to T-300s)',
    location: 'bot/constants.py · live_paper.py',
    meaning: 'Phase 0 pre-open discovery, book initialization & resting limit order placement before window start.',
  },
  {
    name: 'TAKER_FEE_COEFF',
    value: '0.07 → fee = 0.07 · p · (1 − p)',
    location: 'bot/constants.py · executor.py',
    meaning: 'Exact Polymarket parabolic taker fee formula (peaks at 1.75¢/share at p = 0.50; 0¢ on passive Maker fills).',
  },
  {
    name: 'PAIR_COST_BENCHMARK / MEAN / MAX',
    value: '$0.965 benchmark (median $0.9654) · $0.9462 mean · ≤ $0.990 hard max',
    location: 'bot/constants.py · executor.py',
    meaning: 'Measured median combined cost (avg_Up + avg_Down) across 256 dual-sided windows is $0.9654 ($0.965 benchmark), and mean is $0.9462. Hard ceiling is strictly capped at ≤ $0.990 (< $1.00 bound); any pair cost > $1.00 is a guaranteed losing pair.',
  },
  {
    name: 'MAX_SHARE_LEAD',
    value: '90 shares (3x 30sh clips)',
    location: 'bot/constants.py · executor.py',
    meaning: 'Prevents one-sided runaway dip stacking; once a dipping side leads by 90 shares, further adds require opposite leg hedging or deep discount.',
  },
  {
    name: 'LADDER_CLIPS',
    value: '(50, 30, 25, 20, 15, 10, 5) shares',
    location: 'bot/constants.py · executor.py',
    meaning: 'Submitted order sizes are whole numbers (30 default, 50 max). The CSV 13.86 median is an artifact of partial Maker fills.',
  },
]

const CALIBRATION_SUMMARY = [
  {
    band: '0.01 – 0.07',
    role: 'Refused (Dust / Lottery Tail)',
    fills: '170 (1.7%)',
    implied: '4.5%',
    actualWin: '0.6%',
    roiPct: '−89.8%',
    verdict: 'Blocked by PRICE_FLOOR = 0.07',
    tone: 'danger' as const,
  },
  {
    band: '0.07 – 0.30',
    role: 'Regime 2: Deep Maker Dip Ladder',
    fills: '2,949 (28.8%)',
    implied: '19.1%',
    actualWin: '19.8%',
    roiPct: '+3.7%',
    verdict: 'Lowers avg cost & accumulates cheap shares at 0% fee',
    tone: 'success' as const,
  },
  {
    band: '0.30 – 0.50',
    role: 'Regime 2: Core Maker Straddle Grid',
    fills: '3,932 (38.4%)',
    implied: '40.2%',
    actualWin: '41.9%',
    roiPct: '+4.2%',
    verdict: 'Primary liquidity provision zone; 73% passive Maker',
    tone: 'success' as const,
  },
  {
    band: '0.50 – 0.75',
    role: 'Regime 3: Mid-Band Dead Zone',
    fills: '1,475 (14.4%)',
    implied: '60.8%',
    actualWin: '59.4%',
    roiPct: '−2.3%',
    verdict: 'Skipped unless equalizing deficit at pair cost < $0.98',
    tone: 'warning' as const,
  },
  {
    band: '0.75 – 0.95',
    role: 'Regime 1: Dynamic Pairing Equalizer',
    fills: '1,706 (16.7%)',
    implied: '83.1%',
    actualWin: '90.1%',
    roiPct: '+8.4%',
    verdict: 'High-conviction share catch-up on lagging side',
    tone: 'accent' as const,
  },
  {
    band: '0.90 – 0.975',
    role: 'Phase 3: Minute 4 Certainty Snipe',
    fills: 'Tape tail',
    implied: '93.5%',
    actualWin: '98.2%',
    roiPct: '+4.8%',
    verdict: 'Certainty snipe & deficit close in final minute',
    tone: 'info' as const,
  },
  {
    band: '0.975 – 1.00',
    role: 'Refused (Ceiling Tail)',
    fills: '4 (0.04%)',
    implied: '98.5%',
    actualWin: '75.0%',
    roiPct: '−20.7%',
    verdict: 'Blocked by PRICE_CEILING = 0.975',
    tone: 'danger' as const,
  },
]

const TOC = [
  {
    id: 'strategy-overview',
    label: '1. How It Works & Why It Has Edge',
    short: '1. Edge & Core Thesis',
    icon: Zap,
    children: [
      { id: 'core-thesis', label: 'The Sub-$1.00 Pair Arbitrage' },
      { id: 'four-pillars', label: 'Four Pillars of Measured Edge' },
      { id: 'calibration-proof', label: 'Calibration & Regime ROI Table' },
    ],
  },
  {
    id: 'strategy-regimes',
    label: '2. Three-Regime Inventory & Fee Engine',
    short: '2. 3-Regime Engine',
    icon: Layers,
    children: [
      { id: 'price-spectrum', label: 'Bimodal Price Spectrum (0¢–100¢)' },
      { id: 'three-regimes', label: 'Regimes 1, 2 & 3 Decision Logic' },
      { id: 'fee-and-clip-math', label: 'Parabolic Fee & Ladder Clip Math' },
    ],
  },
  {
    id: 'strategy-constants',
    label: '3. Reconstructed Constants',
    short: '3. Constants Table',
    icon: Sigma,
    children: [{ id: 'constants-ledger', label: 'Measured Constants Ledger' }],
  },
  {
    id: 'strategy-wiring',
    label: '4. Live Paper Loop & API Wiring',
    short: '4. Loop & API Wiring',
    icon: Cpu,
    children: [
      { id: 'window-lifecycle', label: '300-Second Window Lifecycle' },
      { id: 'ws-and-api', label: 'Zero-REST Dual-Book & Isolated API' },
    ],
  },
  {
    id: 'strategy-risks',
    label: '5. Risks & What Worth Knowing',
    short: '5. Risks & Nuances',
    icon: ShieldAlert,
    children: [
      { id: 'failure-modes', label: 'When a Window Loses Money' },
      { id: 'guardrails', label: 'Active Safety Guardrails' },
    ],
  },
] as const

const TOC_IDS = TOC.flatMap((item) => [item.id, ...item.children.map((child) => child.id)])

export function Strategy() {
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

  return (
    <div className="mx-auto max-w-[1180px] p-5 sm:p-8">
      <PageHeader
        title="Strategy · 🎯 HAPCS-v1"
        subtitle="Hybrid Arbitrage Pairing & Certainty Sniping v1 — recovered from 27,091 on-chain fills."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="accent" className="font-mono font-semibold">
              🎯 HAPCS-v1 · Engine
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

      {/* Top Executive Banner */}
      <Card className="mt-5 border-accent/40 bg-accent-soft/15 p-6">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="accent">🎯 HAPCS-v1 (hapcs-v1)</Badge>
          <Badge tone="success">72.95% Maker (0% Fee)</Badge>
          <Badge tone="info">$0.965 Benchmark · $0.9462 Mean</Badge>
          <Badge tone="warning">Hard Cap ≤ $0.990 (&lt; $1.00)</Badge>
          <Badge tone="neutral">Hold-to-Redeem (0 Sells)</Badge>
        </div>

        <h2 className="mt-4 text-[17px] font-bold text-fg">
          How It Works in Plain English: Buying $1.00 of Guaranteed Payout for $0.946–$0.965
        </h2>
        <p className="mt-2 text-[14px] leading-relaxed text-muted">
          Instead of predicting whether Bitcoin will finish higher or lower in 5 minutes,{' '}
          <strong className="font-semibold text-fg">🎯 HAPCS-v1</strong> harvests intra-window volatility by accumulating{' '}
          <strong className="font-semibold text-fg">both outcomes (Up and Down)</strong> across the 300-second window so
          that the combined average price of 1 Up share + 1 Down share stays{' '}
          <strong className="font-semibold text-success">below $1.00 (measured median: $0.9654, mean: $0.9462)</strong>. Because every
          binary market resolves to exactly $1.00 on one side and $0.00 on the other, holding equal shares of both sides
          below $1.00 (with a strict hard cap at <strong className="font-semibold text-fg">≤ $0.990</strong>, ensuring zero losing pairs)
          locks in <strong className="font-semibold text-fg">+$0.035 to +$0.054 per pair</strong>{' '}
          regardless of which direction Bitcoin moves.
        </p>

        <div className="mt-5 grid gap-3 sm:grid-cols-4">
          <div className="rounded-tile border border-line bg-surface p-3.5">
            <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-faint">
              <Coins className="size-3.5 text-success" /> Paired Straddle PnL
            </span>
            <p className="mt-1.5 font-mono text-[16px] font-bold text-success">+$4,123.52</p>
            <p className="text-[11.5px] text-muted">249 dual-sided markets (64.6% win)</p>
          </div>

          <div className="rounded-tile border border-line bg-surface p-3.5">
            <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-faint">
              <Scale className="size-3.5 text-accent" /> Mean Pair Cost
            </span>
            <p className="mt-1.5 font-mono text-[16px] font-bold text-fg">$0.9462</p>
            <p className="text-[11.5px] text-muted">67.3% of windows &lt; $1.00 combined</p>
          </div>

          <div className="rounded-tile border border-line bg-surface p-3.5">
            <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-faint">
              <Layers className="size-3.5 text-info" /> Maker / Taker Split
            </span>
            <p className="mt-1.5 font-mono text-[16px] font-bold text-fg">73.0% / 27.0%</p>
            <p className="text-[11.5px] text-muted">0% fee on resting 1¢ grid bids</p>
          </div>

          <div className="rounded-tile border border-line bg-surface p-3.5">
            <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-faint">
              <Clock className="size-3.5 text-warning" /> Hard Cutoff
            </span>
            <p className="mt-1.5 font-mono text-[16px] font-bold text-fg">T−12s (288s)</p>
            <p className="text-[11.5px] text-muted">99.83% of fills land ≥12s pre-close</p>
          </div>
        </div>
      </Card>

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
              SECTION 1: HOW IT WORKS & WHY IT HAS AN EDGE
             ================================================================ */}
          <section id="strategy-overview" aria-label="How it works and why it has edge" className="scroll-mt-16 space-y-6">
            <Card id="core-thesis" className="scroll-mt-16 p-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-[16px] font-semibold text-fg">1. Why This Strategy Has an Edge</h3>
                  <p className="text-[13px] text-muted">
                    Decomposing the +$3,415.73 settled gross PnL (+2.69% on $126.9k deployed) + $789.49 rebates
                  </p>
                </div>
                <Badge tone="success">Market-Neutral Volatility Harvest</Badge>
              </div>

              <p className="mt-4 text-[13.5px] leading-relaxed text-muted">
                On a simultaneous orderbook snapshot, <code className="font-mono text-fg">best_ask(Up) + best_ask(Down) &gt; $1.01</code>{' '}
                (plus taker fees), so a naive bot that crosses the spread on both sides loses money on every trade.
                The on-chain ledger proves that <strong className="font-semibold text-fg">0xc533…69a9</strong> beats the
                spread by combining <strong className="font-semibold text-fg">asynchronous timing</strong> (buying Up
                when Up dips, and buying Down seconds or minutes later when Down dips) with{' '}
                <strong className="font-semibold text-fg">passive Maker limit orders</strong>:
              </p>

              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div className="rounded-tile border border-success/30 bg-success-soft/20 p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-[12px] font-bold uppercase tracking-wider text-success">
                      Paired Dual-Sided Windows (97.0%)
                    </span>
                    <Badge tone="success">249 Settled</Badge>
                  </div>
                  <p className="mt-2 font-mono text-[20px] font-bold text-success">+$4,123.52 PnL</p>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-muted">
                    <strong>64.6% market win rate</strong> (161W / 88L). In <strong>67.3%</strong> of these windows, the
                    bot locked in <code className="font-mono">avg_price_Up + avg_price_Down &lt; $1.00</code> (mean{' '}
                    <code className="font-mono">$0.9462</code>).
                  </p>
                </div>

                <div className="rounded-tile border border-danger/30 bg-danger-soft/20 p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-[12px] font-bold uppercase tracking-wider text-danger">
                      Unhedged Single-Sided Windows (3.0%)
                    </span>
                    <Badge tone="danger">8 Settled</Badge>
                  </div>
                  <p className="mt-2 font-mono text-[20px] font-bold text-danger">−$707.79 PnL</p>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-muted">
                    <strong>25.0% market win rate</strong> (2W / 6L). When BTC trends non-stop from the opening second
                    and never lets the second leg fill, the unhedged position bleeds.
                  </p>
                </div>
              </div>

              <div id="four-pillars" className="mt-6 scroll-mt-16 space-y-3">
                <h4 className="text-[14px] font-semibold text-fg">The Four Structural Pillars of Edge</h4>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-tile border border-line bg-surface-2/40 p-4">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="size-4 text-success" />
                      <span className="text-[13.5px] font-semibold text-fg">1. 0%-Fee Maker Bid Grid (72.95% of Fills)</span>
                    </div>
                    <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                      Polymarket charges takers a parabolic fee <code className="font-mono">0.07 · p · (1 − p)</code>{' '}
                      (up to 1.75¢/share at 50¢), while passive Makers pay <strong>0% fee</strong> and earn rebates.
                      72.95% of all fills in the ledger have exact <code className="font-mono">shares × price == USD</code>{' '}
                      (0% fee Maker orders resting on the 1¢ grid).
                    </p>
                  </div>

                  <div className="rounded-tile border border-line bg-surface-2/40 p-4">
                    <div className="flex items-center gap-2">
                      <TrendingUp className="size-4 text-accent" />
                      <span className="text-[13.5px] font-semibold text-fg">2. Lagging-Leg Share Equalization</span>
                    </div>
                    <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                      Low average pair cost (<code className="font-mono">$0.94</code>) only guarantees a profit if{' '}
                      <code className="font-mono">shares_Up ≈ shares_Down</code>. When one side rallies into{' '}
                      <code className="font-mono">[75¢, 95¢]</code> and has fewer shares than the dip side, the bot
                      aggressively buys the lagging side to equalize share counts.
                    </p>
                  </div>

                  <div className="rounded-tile border border-line bg-surface-2/40 p-4">
                    <div className="flex items-center gap-2">
                      <Target className="size-4 text-info" />
                      <span className="text-[13.5px] font-semibold text-fg">3. Mid-Band Dead-Zone Avoidance</span>
                    </div>
                    <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                      Whenever one outcome trades in <code className="font-mono">(50¢, 75¢)</code>, its complement
                      automatically trades in <code className="font-mono">(25¢, 50¢)</code>. Rather than paying 60¢
                      for a noisy favorite, the bot bids passively on the complement at 40¢.
                    </p>
                  </div>

                  <div className="rounded-tile border border-line bg-surface-2/40 p-4">
                    <div className="flex items-center gap-2">
                      <ShieldCheck className="size-4 text-warning" />
                      <span className="text-[13.5px] font-semibold text-fg">4. Strict Tail Truncation (&lt;7¢ &amp; &gt;97.5¢)</span>
                    </div>
                    <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                      On-chain calibration proves two negative-EV traps: lottery tickets <code className="font-mono">&lt;7¢</code>{' '}
                      (0.6% win rate, −89.8% ROI) and extreme certainty tail <code className="font-mono">&gt;97.5¢</code>{' '}
                      where downside asymmetry destroys edge. 🎯 HAPCS-v1 blocks both tails while capturing high-certainty snipes up to 97.5¢ in Minute 4.
                    </p>
                  </div>
                </div>
              </div>
            </Card>

            {/* Calibration Proof Table */}
            <Card id="calibration-proof" className="scroll-mt-16 p-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-[15.5px] font-semibold text-fg">Empirical Calibration across Price Regimes</h3>
                  <p className="text-[12.5px] text-muted">
                    Measured across 10,007 settled fills (Nov 7–8 ledger) — why 🎯 HAPCS-v1 trades bimodal bands
                  </p>
                </div>
                <Badge tone="info">10,007 Settled Fills</Badge>
              </div>

              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[680px] text-left text-[12.5px]">
                  <thead className="border-b border-line text-[11px] font-semibold uppercase tracking-wider text-faint">
                    <tr>
                      <th className="py-2 px-2.5">Price Band</th>
                      <th className="py-2 px-2.5">🎯 HAPCS-v1 Regime</th>
                      <th className="py-2 px-2.5 text-right">Fills</th>
                      <th className="py-2 px-2.5 text-right">Price Paid</th>
                      <th className="py-2 px-2.5 text-right">Actual Win</th>
                      <th className="py-2 px-2.5 text-right">ROI / $</th>
                      <th className="py-2 px-2.5">Engine Action</th>
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

          {/* ================================================================
              SECTION 2: THREE-REGIME INVENTORY & FEE ENGINE
             ================================================================ */}
          <section id="strategy-regimes" aria-label="Three-regime engine" className="scroll-mt-16 space-y-6">
            <Card id="price-spectrum" className="scroll-mt-16 p-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-[16px] font-semibold text-fg">
                    2. The 3-Regime Inventory &amp; Fee Engine (<code className="font-mono text-[14px]">bot/executor.py</code>)
                  </h3>
                  <p className="text-[13px] text-muted">
                    How <code className="font-mono">evaluate_microstructure_ladder()</code> maps every live quote into
                    an action
                  </p>
                </div>
                <Badge tone="accent">Bimodal Execution</Badge>
              </div>

              {/* Visual 0-100c Price Spectrum Bar */}
              <div className="mt-6">
                <p className="mb-2 text-[12px] font-medium text-muted">
                  Token Price Spectrum (<code className="font-mono">0¢ → 100¢</code>):
                </p>
                <div className="grid h-11 w-full grid-cols-12 overflow-hidden rounded-tile border border-line text-[11px] font-semibold text-white shadow-xs">
                  <div className="col-span-1 flex items-center justify-center bg-danger/85 px-1 text-center" title="0¢–7¢ Refused">
                    &lt;7¢
                  </div>
                  <div className="col-span-5 flex items-center justify-center bg-success/85 px-2 text-center" title="7¢–50¢ Maker Dip Grid">
                    Regime 2: Maker Dip [7¢–50¢]
                  </div>
                  <div className="col-span-3 flex items-center justify-center bg-warning/80 px-2 text-center" title="50¢–75¢ Dead Zone">
                    Regime 3: Dead Zone
                  </div>
                  <div className="col-span-2 flex items-center justify-center bg-info/85 px-1.5 text-center" title="75¢–95¢ Lagging Equalizer">
                    Regime 1: [75–95¢]
                  </div>
                  <div className="col-span-1 flex items-center justify-center bg-accent/90 px-1 text-center" title="90¢–97.5¢ Minute 4 Certainty Snipe">
                    M4 Snipe
                  </div>
                </div>
                <div className="mt-2 grid grid-cols-12 font-mono text-[10.5px] text-faint">
                  <div className="col-span-1">0¢</div>
                  <div className="col-span-5">7¢ (Floor) → 50¢ (67.2% of fills)</div>
                  <div className="col-span-3">50¢ → 75¢ (Skip / Pivot)</div>
                  <div className="col-span-2">75¢ → 95¢ (Pair Arbitrage)</div>
                  <div className="col-span-1 text-right">97.5¢ (Ceil)</div>
                </div>
              </div>

              {/* Detailed 3 Regimes Cards */}
              <div id="three-regimes" className="mt-6 grid scroll-mt-16 gap-4 sm:grid-cols-3">
                <div className="rounded-tile border border-info/30 bg-info-soft/20 p-4">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[11px] font-bold uppercase text-info">Dynamic Pairing &amp; M4 Snipe</span>
                    <Badge tone="info">Pair Arbitrage</Badge>
                  </div>
                  <h4 className="mt-1.5 text-[14px] font-semibold text-fg">Regime 1 &amp; M4: Dynamic Equalizer &amp; Snipe</h4>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                    Checks any side with a share deficit (<code className="font-mono">deficit = shares_opp − shares_side &gt; 0</code>).
                    Buys the lagging leg at any price in <code className="font-mono">[7¢, 97.5¢]</code> as long as projected{' '}
                    <code className="font-mono">pair_cost ≤ $0.990</code> (strictly &lt; $1.00 bound). In Minute 4 (T-60s), executes resolution certainty snipes up to <code className="font-mono">97.5¢</code>.
                  </p>
                </div>

                <div className="rounded-tile border border-success/30 bg-success-soft/20 p-4">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[11px] font-bold uppercase text-success">Passive Grid · [7¢, 50¢]</span>
                    <Badge tone="success">0% Maker</Badge>
                  </div>
                  <h4 className="mt-1.5 text-[14px] font-semibold text-fg">Regime 2: Passive Maker Dip Grid</h4>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                    Evaluates resting <code className="font-mono">best_bid</code> on both outcomes in{' '}
                    <code className="font-mono">[0.07, 0.50]</code>. Prioritizes the deficit side, capped at{' '}
                    <code className="font-mono">MAX_SHARE_LEAD = 90</code> shares to prevent runaway unhedged stacking. Executes as{' '}
                    <code className="font-mono">MAKER</code> at <code className="font-mono">0%</code> fee whenever
                    projected <code className="font-mono">pair_cost ≤ $0.965</code> (or <code className="font-mono">≤ $0.990</code> if equalizing).
                  </p>
                </div>

                <div className="rounded-tile border border-warning/30 bg-warning-soft/20 p-4">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[11px] font-bold uppercase text-warning">Mid-Band · (50¢, 75¢)</span>
                    <Badge tone="warning">Dead Zone</Badge>
                  </div>
                  <h4 className="mt-1.5 text-[14px] font-semibold text-fg">Regime 3: Complement Pivot / Skip</h4>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                    When the preferred side is in <code className="font-mono">(0.50, 0.75)</code>, the engine checks the
                    opposite token first (which sits in <code className="font-mono">[0.25, 0.50]</code>, Regime 2). Inside
                    opening straddle upper band <code className="font-mono">[0.50, 0.55]</code> or when equalizing, it only
                    fills if projected <code className="font-mono">pair_cost ≤ $0.965</code>; otherwise logs <code className="font-mono">dead-zone-skip</code>.
                  </p>
                </div>
              </div>

              {/* Math Boxes */}
              <div id="fee-and-clip-math" className="mt-6 scroll-mt-16 space-y-4">
                <div className="rounded-card border border-line bg-surface-2/30 p-5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-[14px] font-bold text-fg">
                      A. Exact Maker vs. Parabolic Taker Fee Accounting (<code className="font-mono">compute_fill_usd</code>)
                    </h4>
                    <Badge tone="accent">0% Maker / Parabolic Taker</Badge>
                  </div>
                  <div className="my-3 overflow-x-auto rounded-tile border border-line bg-surface p-3.5 text-center font-mono text-[13.5px] text-fg shadow-xs">
                    MAKER: usd = round(shares × p, 2) &nbsp;|&nbsp; TAKER: usd = round(shares × (p + 0.07 · p · (1 − p)), 2)
                  </div>
                  <p className="text-[12.5px] text-muted">
                    Recovered directly from the CSV residuals <code className="font-mono">(USD_Amount / Shares) − Price</code>:
                    72.95% of fills had zero residual (Maker), while 27.05% followed the exact parabola{' '}
                    <code className="font-mono">0.07 · p · (1 − p)</code> ($814.70 total taker fees on Nov 7–8).
                  </p>
                </div>

                <div className="rounded-card border border-line bg-surface-2/30 p-5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-[14px] font-bold text-fg">
                      B. Projected Combined Pair-Cost Gate (<code className="font-mono">_projected_pair_cost</code>)
                    </h4>
                    <Badge tone="success">Strict Sub-$1.00 Profit Bound</Badge>
                  </div>
                  <div className="my-3 overflow-x-auto rounded-tile border border-line bg-surface p-3.5 text-center font-mono text-[13.5px] text-fg shadow-xs">
                    pair_cost = (cost_Up / shares_Up) + (cost_Down / shares_Down) ≤ $0.965 (Target) &nbsp;|&nbsp; ≤ $0.990 (Hard Ceiling)
                  </div>
                  <p className="text-[12.5px] text-muted">
                    Every candidate fill is simulated against current window inventory <code className="font-mono">inv[&quot;Up&quot;]</code>{' '}
                    and <code className="font-mono">inv[&quot;Down&quot;]</code> before execution. Because a binary token resolves to $1.00,
                    any matched pair with <code className="font-mono">pair_cost &gt; $1.00</code> is a guaranteed loss. 🎯 HAPCS-v1 strictly
                    enforces a hard ceiling of <code className="font-mono">≤ $0.990</code> (locking in ≥ +1.0¢/share arbitrage profit).
                  </p>
                </div>

                <div className="rounded-card border border-line bg-surface-2/30 p-5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-[14px] font-bold text-fg">
                      C. Whole-Share Ladder Clip Sizing (<code className="font-mono">select_ladder_clip</code>)
                    </h4>
                    <Badge tone="info">Whole-Number Rungs</Badge>
                  </div>
                  <div className="my-3 overflow-x-auto rounded-tile border border-line bg-surface p-3.5 text-center font-mono text-[13.5px] text-fg shadow-xs">
                    deficit ≥ 50 → 50 sh &nbsp;|&nbsp; deficit &gt; 0 → snap to (50, 30, 25, 20, 15, 10, 5) &nbsp;|&nbsp; base → 30 / 25 / 20 sh
                  </div>
                  <p className="text-[12.5px] text-muted">
                    Grouping on-chain fills by <code className="font-mono">(tx_hash, token, price)</code> revealed that
                    the bot submits whole-number clips (<code className="font-mono">30</code>, <code className="font-mono">50</code>,{' '}
                    <code className="font-mono">25</code>, <code className="font-mono">20</code>, <code className="font-mono">10</code>).
                    Fractional fill rows in the raw CSV are partial fills of resting Maker orders.
                  </p>
                </div>
              </div>
            </Card>
          </section>

          {/* ================================================================
              SECTION 3: RECONSTRUCTED MICROSTRUCTURE CONSTANTS
             ================================================================ */}
          <section id="strategy-constants" aria-label="Reconstructed constants" className="scroll-mt-16 space-y-6">
            <Card id="constants-ledger" className="scroll-mt-16 p-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-[16px] font-semibold text-fg">
                    3. Reconstructed Microstructure Constants (<code className="font-mono text-[14px]">bot/constants.py</code>)
                  </h3>
                  <p className="text-[13px] text-muted">
                    Cross-validated across both 24h ledgers (Nov 6–7 &amp; Nov 7–8) and wired into{' '}
                    <code className="font-mono">bot/config.json</code>
                  </p>
                </div>
                <Badge tone="neutral">Zero Invented Thresholds</Badge>
              </div>

              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[680px] text-left text-[12.5px]">
                  <thead className="border-b border-line text-[11px] font-semibold uppercase tracking-wider text-faint">
                    <tr>
                      <th className="py-2 px-2.5">Constant / Key</th>
                      <th className="py-2 px-2.5">Measured Value</th>
                      <th className="py-2 px-2.5">Source File</th>
                      <th className="py-2 px-2.5">Role in 🎯 HAPCS-v1</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {CONSTANTS_TABLE.map((c) => (
                      <tr key={c.name} className="hover:bg-surface-2/40">
                        <td className="py-2.5 px-2.5 font-mono text-[12px] font-semibold text-fg">{c.name}</td>
                        <td className="py-2.5 px-2.5 font-mono text-[12px] text-accent">{c.value}</td>
                        <td className="py-2.5 px-2.5 font-mono text-[11.5px] text-faint">{c.location}</td>
                        <td className="py-2.5 px-2.5 text-[12px] leading-relaxed text-muted">{c.meaning}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </section>

          {/* ================================================================
              SECTION 4: LIVE PAPER LOOP & API WIRING
             ================================================================ */}
          <section id="strategy-wiring" aria-label="Live paper loop and API wiring" className="scroll-mt-16 space-y-6">
            <Card id="window-lifecycle" className="scroll-mt-16 p-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-[16px] font-semibold text-fg">
                    4. Live Paper Loop &amp; API Wiring (<code className="font-mono text-[14px]">bot/live_paper.py</code> &amp;{' '}
                    <code className="font-mono text-[14px]">bot/api.py</code>)
                  </h3>
                  <p className="text-[13px] text-muted">
                    How the real-time WebSocket streamer, execution loop, background resolver, and isolated UI desk
                    fit together
                  </p>
                </div>
                <Badge tone="accent">Event-Driven ≤250ms Wake</Badge>
              </div>

              <div className="mt-5 grid gap-3 sm:grid-cols-5">
                <div className="rounded-tile border border-line bg-surface-2/40 p-3.5">
                  <span className="font-mono text-[11px] font-bold uppercase text-info">0. T-310s (Pre-Open)</span>
                  <p className="mt-1 text-[13.5px] font-semibold text-fg">Phase 0 Pipeline</p>
                  <p className="mt-1 text-[12px] leading-relaxed text-muted">
                    Pre-open discovery &amp; WebSocket book initialization 10s before window open.
                  </p>
                </div>

                <div className="rounded-tile border border-line bg-surface-2/40 p-3.5">
                  <span className="font-mono text-[11px] font-bold uppercase text-danger">1. T+0s – T+4s (sbc 296–300)</span>
                  <p className="mt-1 text-[13.5px] font-semibold text-fg">Opening Buffer</p>
                  <p className="mt-1 text-[12px] leading-relaxed text-muted">
                    Observes opening book liquidity. Strictly 0 fills occur in the first 4s (sbc 296–300).
                  </p>
                </div>

                <div className="rounded-tile border border-line bg-surface-2/40 p-3.5">
                  <span className="font-mono text-[11px] font-bold uppercase text-accent">2. T+4s First Touch</span>
                  <p className="mt-1 text-[13.5px] font-semibold text-fg">Opening Straddle Leg</p>
                  <p className="mt-1 text-[12px] leading-relaxed text-muted">
                    Opens on cheaper token in <code className="font-mono">[34¢, 55¢]</code> (preferring Maker at 0% fee), priming the hedge.
                  </p>
                </div>

                <div className="rounded-tile border border-line bg-surface-2/40 p-3.5">
                  <span className="font-mono text-[11px] font-bold uppercase text-success">3. M0–M4 Trading</span>
                  <p className="mt-1 text-[13.5px] font-semibold text-fg">Dynamic Grid &amp; Snipe</p>
                  <p className="mt-1 text-[12px] leading-relaxed text-muted">
                    Maker dip grid [7¢–50¢], dynamic pairing equalizer, and Minute 4 certainty snipes up to 97.5¢.
                  </p>
                </div>

                <div className="rounded-tile border border-line bg-surface-2/40 p-3.5">
                  <span className="font-mono text-[11px] font-bold uppercase text-warning">4. T+288s (sbc 0–12)</span>
                  <p className="mt-1 text-[13.5px] font-semibold text-fg">Cutoff &amp; Async Settle</p>
                  <p className="mt-1 text-[12px] leading-relaxed text-muted">
                    Strictly 0 fills in final 12s. Holds inventory to binary resolution and redeems winning token at $1.00.
                  </p>
                </div>
              </div>

              <div id="ws-and-api" className="mt-6 grid scroll-mt-16 gap-4 sm:grid-cols-2">
                <div className="rounded-tile border border-line bg-surface p-4">
                  <div className="flex items-center gap-2">
                    <Radio className="size-4 text-success" />
                    <h4 className="text-[14px] font-semibold text-fg">
                      Zero-Extra-REST Dual-Book Reads (<code className="font-mono text-[12.5px]">live_quote_pair</code>)
                    </h4>
                  </div>
                  <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
                    To distinguish passive <code className="font-mono">MAKER</code> bid fills from{' '}
                    <code className="font-mono">TAKER</code> ask sweeps without doubling REST traffic,{' '}
                    <code className="font-mono">live_bid_price()</code> reads <code className="font-mono">book.best_bid</code>{' '}
                    directly from <code className="font-mono">LiveBookStreamer</code>’s in-memory WebSocket orderbook
                    in O(1) time. Anti-runaway spacing gates fills by <code className="font-mono">0.5s</code> on price
                    changes and <code className="font-mono">3.0s</code> on static quotes.
                  </p>
                </div>

                <div className="rounded-tile border border-line bg-surface p-4">
                  <div className="flex items-center gap-2">
                    <Activity className="size-4 text-accent" />
                    <h4 className="text-[14px] font-semibold text-fg">
                      Desk API &amp; Telemetry (<code className="font-mono text-[12.5px]">:5173 → :8789</code>)
                    </h4>
                  </div>
                  <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
                    This desk serves the UI on port <code className="font-mono">5173</code> and{' '}
                    <code className="font-mono">bot/api.py</code> on <code className="font-mono">127.0.0.1:8789</code>.
                    Every fill event streams <code className="font-mono">role</code> (<code className="font-mono">MAKER</code>{' '}
                    vs <code className="font-mono">TAKER</code>), <code className="font-mono">subReason</code> (
                    <code className="font-mono">maker-dip-ladder</code> vs <code className="font-mono">hedge-equalizer</code>),{' '}
                    <code className="font-mono">feeUsd</code>, and live <code className="font-mono">pairCost</code> into{' '}
                    <code className="font-mono">state.json</code> and the Live Fills table.
                  </p>
                </div>
              </div>
            </Card>
          </section>

          {/* ================================================================
              SECTION 5: RISKS, FAILURE MODES & WHAT WORTH KNOWING
             ================================================================ */}
          <section id="strategy-risks" aria-label="Risks and guardrails" className="scroll-mt-16 space-y-6">
            <Card id="failure-modes" className="scroll-mt-16 p-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-[16px] font-semibold text-fg">5. Risks, Failure Modes &amp; What Worth Knowing</h3>
                  <p className="text-[13px] text-muted">
                    When 🎯 HAPCS-v1 loses money on a window and how the risk manager bounds drawdowns
                  </p>
                </div>
                <Badge tone="warning">Max DD $957.99 on $127k Vol</Badge>
              </div>

              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div className="rounded-tile border border-warning/30 bg-warning-soft/20 p-4">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="size-4 text-warning" />
                    <h4 className="text-[14px] font-semibold text-fg">
                      Failure Mode 1: The V-Reversal Share Imbalance
                    </h4>
                  </div>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                    If BTC drops early in the window, the bot accumulates heavy <code className="font-mono">Down</code>{' '}
                    shares on the dip ladder (e.g., 910 Down shares at 39¢). If BTC suddenly V-reverses upward in M3–M4
                    and rockets past 97.5¢ before the bot can equalize <code className="font-mono">Up</code> shares,{' '}
                    <code className="font-mono">Up</code> wins while the bot holds fewer <code className="font-mono">Up</code>{' '}
                    shares than total dollars spent (worst single-window loss in the 24h ledger: <strong>−$207.88</strong>).
                  </p>
                </div>

                <div className="rounded-tile border border-danger/30 bg-danger-soft/20 p-4">
                  <div className="flex items-center gap-2">
                    <ShieldAlert className="size-4 text-danger" />
                    <h4 className="text-[14px] font-semibold text-fg">
                      Failure Mode 2: One-Way Runaway Open (3.0% of Windows)
                    </h4>
                  </div>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                    When BTC trends straight up or down from <code className="font-mono">T+0s</code> without a single
                    pullback, the favorite immediately breaches the <code className="font-mono">97.5¢</code> ceiling while
                    the underdog falls below the <code className="font-mono">7¢</code> floor, leaving the opening leg
                    unhedged.
                  </p>
                </div>
              </div>

              <div id="guardrails" className="mt-6 grid scroll-mt-16 gap-4 sm:grid-cols-3">
                <div className="rounded-tile border border-line bg-surface p-3.5">
                  <span className="font-mono text-[11px] uppercase text-faint">Per-Window Risk Cap</span>
                  <p className="mt-1 text-[15.5px] font-bold text-fg">$4,000 · 500 Fills</p>
                  <p className="text-[12px] text-muted">Hard ceiling enforced by check_window() before every clip</p>
                </div>

                <div className="rounded-tile border border-line bg-surface p-3.5">
                  <span className="font-mono text-[11px] uppercase text-faint">Daily Stop-Loss</span>
                  <p className="mt-1 text-[15.5px] font-bold text-fg">$500.00 Realized</p>
                  <p className="text-[12px] text-muted">Halts new entries if settled daily net PnL drops ≤ −$500</p>
                </div>

                <div className="rounded-tile border border-line bg-surface p-3.5">
                  <span className="font-mono text-[11px] uppercase text-faint">Single-Window Lock</span>
                  <p className="mt-1 text-[15.5px] font-bold text-fg">1 Active Window Max</p>
                  <p className="text-[12px] text-muted">assert_single_window() prevents overlapping exposure</p>
                </div>
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
              🎯 HAPCS-v1 — Hybrid Arbitrage Pairing &amp; Certainty Sniping v1
            </p>
            <p className="text-[12.5px] text-muted">
              Reconstructed from 27,091 on-chain fills (Nov 6–8, 2026). Running on port 5173 → {BOT_ORIGIN}.
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
