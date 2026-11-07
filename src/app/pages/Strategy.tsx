import {
  BookOpen,
  Clock,
  Coins,
  LogOut,
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

// ----------------------------------------------------------------------
// This desk mimics one wallet: dangerously-skip-permissions on BTC 5m.
// 24h replay: 16,855 buys / 0 sells, 30-share clips, hold-to-redeem.
// ----------------------------------------------------------------------

const RULES = [
  {
    step: 1,
    title: 'First touch at ~T+13s',
    subtitle: 'Window open',
    icon: Clock,
    body: 'No orders in the opening seconds. The target\'s median first touch is 13 seconds (mean 24s) — the paper loop waits out the open, then lifts its first side. First side splits 152 Down / 136 Up: the open is a coin flip, not a signal.',
    setting: 'openDelaySec: 13s',
    keyMetric: 'T+13s',
    metricLabel: 'Median first touch',
    tone: 'neutral' as const,
  },
  {
    step: 2,
    title: 'Hedge leg +15s later',
    subtitle: 'Straddle, not a pick',
    icon: ShieldCheck,
    body: 'Fifteen seconds after the first touch the loop buys the other side: 69% of target windows hedge within 30s, and 280 of 288 touch both outcomes. The position starts as a straddle — direction is discovered mid-window, never assumed.',
    setting: 'hedgeDelaySec: 15s',
    keyMetric: '+15s',
    metricLabel: 'Median hedge gap',
    tone: 'accent' as const,
  },
  {
    step: 3,
    title: 'Lean tilts size, never picks sides',
    subtitle: 'Book microprice',
    icon: TrendingUp,
    body: 'First-trade side predicts the final lean only 61% of the time — lean forms mid-window. Each fill is tilted by live book microprice (lean in [−1,+1] with confidence from the spread). Dumb mode (lean = 0) runs the neutral straddle for plumbing tests.',
    setting: 'leanSource: microprice',
    keyMetric: '|tilt| 28%',
    metricLabel: 'Median absolute tilt',
    tone: 'info' as const,
  },
  {
    step: 4,
    title: '30-share clips, $316 median window',
    subtitle: 'Clip discipline',
    icon: Coins,
    body: '30.4% of target fills are exactly 30.0 shares; the cap is 50 and the median fill is ~14 shares. Every third paper fill takes the full clip, the rest take the median — that mix reproduces the signature. Adds grind: same-side price steps average +0.0006, 40% flat.',
    setting: 'clip 30 · cap 50',
    keyMetric: '58.5 / 45',
    metricLabel: 'Mean / median fills',
    tone: 'success' as const,
  },
  {
    step: 5,
    title: 'M4 fades — extremes only late',
    subtitle: 'Cadence shape',
    icon: Zap,
    body: 'Minute buckets run 3,081 / 3,821 / 4,289 / 3,914 / 1,750 — the fourth minute fades hard. Prices ≤15¢ or ≥85¢ appear almost exclusively in M4 (19.8% / 11.4% vs ~1% earlier). The loop only snipes extremes late; early extremes are skipped as noise.',
    setting: 'stopBeforeCloseSec: 15s',
    keyMetric: '1,750',
    metricLabel: 'M4 fills vs ~4k',
    tone: 'warning' as const,
  },
  {
    step: 6,
    title: 'Hold to redeem — never sell',
    subtitle: 'Resolution',
    icon: Target,
    body: '16,855 buys, 0 sells. Winners pay $1/share at resolution; the target even leaves winners unclaimed for weeks (lazy redeeming). The paper loop holds every fill to the market outcome — there is no stop-loss, no take-profit, no exit matrix.',
    setting: 'buy-only · hold',
    keyMetric: '+$533',
    metricLabel: '24h replay net',
    tone: 'danger' as const,
  },
]

const TOC = [
  {
    id: 'strategy-timeline',
    label: 'Window Timeline & Walkthrough',
    short: '1. Window Timeline',
    icon: Clock,
    children: [
      { id: 'timeline-anatomy', label: '5-Minute Market Anatomy' },
      { id: 'timeline-walkthrough', label: 'A Window, Minute by Minute' },
      { id: 'entry-gates', label: 'The Six Execution Rules' },
    ],
  },
  {
    id: 'strategy-math',
    label: 'Sizing Math & Tilt',
    short: '2. Math & Tilt',
    icon: Sigma,
    children: [
      { id: 'formula-tilt', label: 'Microprice Tilt' },
      { id: 'formula-clip', label: 'Clip Mix' },
      { id: 'formula-payout', label: 'Hold-to-Redeem Payout' },
    ],
  },
  {
    id: 'strategy-exits',
    label: 'No Exits: Hold to Redeem',
    short: '3. Resolution',
    icon: LogOut,
    children: [{ id: 'exit-matrix', label: 'What Happens at Close' }],
  },
  {
    id: 'strategy-risk',
    label: 'Paper Guardrails',
    short: '4. Guardrails',
    icon: ShieldCheck,
    children: [
      { id: 'risk-caps', label: 'Per-Window Caps' },
      { id: 'risk-fidelity', label: 'Fidelity Gate Before Size' },
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
        title="Strategy"
        subtitle="Straddle-plus-lean on BTC 5-minute windows — cloned from 24 hours of one wallet's tape."
        actions={
          <Link
            to="/config"
            className="inline-flex h-8 items-center gap-1.5 rounded-tile border border-line-strong bg-surface px-3 text-[13px] font-medium shadow-[0_1px_1px_rgb(20_20_24/0.04)] hover:bg-surface-2"
          >
            <SlidersHorizontal className="size-3.5" /> Tune thresholds
          </Link>
        }
      />

      <Card className="mt-5 p-6">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="accent">BTC Up or Down</Badge>
          <Badge tone="neutral">5-Minute Windows (288 / day)</Badge>
          <Badge tone="info">Paper by Default</Badge>
        </div>
        <p className="mt-4 text-[14px] leading-relaxed text-muted">
          The wallet <strong className="text-fg font-semibold">0xc533…69a9</strong> buys both sides of every
          5-minute BTC window in 30-share clips and holds everything to redemption — 16,855 buys, zero sells, +$533
          on $128k staked in 24 hours. This desk replays that behavior live: first touch at ~T+13s, hedge leg +15s,
          lean-weighted adds through M1–M3, extreme-sniping in M4, hold to the market outcome.
        </p>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <div className="rounded-tile border border-line bg-surface-2/50 p-3.5">
            <span className="flex items-center gap-2 text-[11.5px] font-medium uppercase tracking-wider text-faint">
              <Clock className="size-4 text-accent" /> Open & Hedge
            </span>
            <p className="mt-1.5 text-[15px] font-bold text-fg">T+13s, then +15s</p>
            <p className="text-[12px] text-muted">First touch, then the other side</p>
          </div>

          <div className="rounded-tile border border-line bg-surface-2/50 p-3.5">
            <span className="flex items-center gap-2 text-[11.5px] font-medium uppercase tracking-wider text-faint">
              <Target className="size-4 text-success" /> Work Phase
            </span>
            <p className="mt-1.5 text-[15px] font-bold text-fg">M1 – M3 grind</p>
            <p className="text-[12px] text-muted">Lean-tilted clips near the touch</p>
          </div>

          <div className="rounded-tile border border-line bg-surface-2/50 p-3.5">
            <span className="flex items-center gap-2 text-[11.5px] font-medium uppercase tracking-wider text-faint">
              <TrendingUp className="size-4 text-info" /> Fidelity Target
            </span>
            <p className="mt-1.5 text-[15px] font-bold text-fg">45 fills · both sides</p>
            <p className="text-[12px] text-muted">Median window, 97% cover</p>
          </div>
        </div>
      </Card>

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
              className="min-w-[170px] flex-1 whitespace-nowrap"
              aria-current={isActive ? 'true' : undefined}
            >
              <Icon />
              {item.short}
            </Button>
          )
        })}
      </div>

      <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_236px]">
        <div className="min-w-0 space-y-6">
          <section id="strategy-timeline" aria-label="Window timeline" className="scroll-mt-16 space-y-6">
            <Card id="timeline-anatomy" className="scroll-mt-16 p-6">
              <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h3 className="text-[16px] font-semibold text-fg">5-Minute Market Anatomy</h3>
                  <p className="text-[13px] text-muted">How the loop sections the 300-second window</p>
                </div>
                <Badge tone="accent">300 Seconds Total</Badge>
              </div>

              <div className="mt-6">
                <div className="grid h-10 w-full grid-cols-12 overflow-hidden rounded-tile border border-line text-[11px] font-semibold text-white">
                  <div className="col-span-2 flex items-center justify-center bg-danger/80 px-2 text-center">T+0–13s</div>
                  <div className="col-span-6 flex items-center justify-center bg-success/85 px-2 text-center">M0–M3 work</div>
                  <div className="col-span-4 flex items-center justify-center bg-info/80 px-2 text-center">M4 snipe + hold</div>
                </div>
                <div className="mt-3 grid grid-cols-12 text-[11.5px] font-mono text-faint">
                  <div className="col-span-2">0:00 open</div>
                  <div className="col-span-6 text-center">0:13 touch · +15s hedge</div>
                  <div className="col-span-4 text-right">5:00 redeem</div>
                </div>

                <div className="mt-5 grid gap-3 sm:grid-cols-3">
                  <div className="rounded-tile border border-danger/20 bg-danger-soft/25 p-3.5">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-danger">00:00 – 00:13</span>
                    <p className="mt-1 text-[13.5px] font-semibold text-fg">Silence</p>
                    <p className="mt-1 text-[12px] leading-relaxed text-muted">No orders. The open prints are noise; the median first touch lands at 13 seconds.</p>
                  </div>
                  <div className="rounded-tile border border-success/20 bg-success-soft/25 p-3.5">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-success">00:13 – 04:00</span>
                    <p className="mt-1 text-[13.5px] font-semibold text-fg">Straddle + lean</p>
                    <p className="mt-1 text-[12px] leading-relaxed text-muted">Hedge the open at +15s, then lean-tilted clips. Median gap between fills is 1 second.</p>
                  </div>
                  <div className="rounded-tile border border-info/20 bg-info-soft/25 p-3.5">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-info">04:00 – 05:00</span>
                    <p className="mt-1 text-[13.5px] font-semibold text-fg">Snipe + hold</p>
                    <p className="mt-1 text-[12px] leading-relaxed text-muted">Extremes only count late. Everything is held to the market outcome — no sells.</p>
                  </div>
                </div>
              </div>
            </Card>

            <section id="entry-gates" className="scroll-mt-16">
              <h3 className="text-[16px] font-semibold text-fg">The Six Execution Rules</h3>
              <p className="mt-0.5 text-[13px] text-muted">Measured from the tape, enforced by the loop.</p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {RULES.map((rule) => {
                  const IconComponent = rule.icon
                  return (
                    <Card key={rule.title} className="p-5">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-start gap-3">
                          <span className="grid size-8 shrink-0 place-items-center rounded-[9px] bg-surface-2 text-muted">
                            <IconComponent className="size-4" aria-hidden="true" />
                          </span>
                          <div>
                            <h4 className="text-[14px] font-semibold text-fg">{rule.title}</h4>
                            <span className="text-[12px] font-medium text-accent">{rule.subtitle}</span>
                          </div>
                        </div>
                        <Badge tone={rule.tone}>{rule.keyMetric}</Badge>
                      </div>
                      <p className="mt-3 text-[13px] leading-relaxed text-muted">{rule.body}</p>
                      <div className="mt-4 flex items-center justify-between border-t border-line pt-2.5">
                        <span className="text-[11px] uppercase tracking-wider text-faint">{rule.metricLabel}</span>
                        <code className="font-mono text-[11.5px] text-fg">{rule.setting}</code>
                      </div>
                    </Card>
                  )
                })}
              </div>
            </section>
          </section>

          <section id="strategy-math" aria-label="Sizing math" className="scroll-mt-16 space-y-6">
            <Card className="p-6">
              <h3 className="text-[16px] font-semibold text-fg">Sizing Math & Tilt</h3>
              <p className="text-[13px] text-muted">No edge model — allocation follows the book and the clip mix.</p>
              <div className="mt-6 space-y-6">
                <div id="formula-tilt" className="scroll-mt-16 rounded-card border border-line bg-surface-2/30 p-5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-[14.5px] font-bold text-fg">1. Microprice Tilt</h4>
                    <Badge tone="accent">Per-fill bias</Badge>
                  </div>
                  <div className="my-4 overflow-x-auto rounded-tile border border-line bg-surface p-4 text-center font-serif text-[18px] text-fg shadow-sm">
                    lean = clamp(4 · (mid<sub>Up</sub> − mid<sub>Down</sub>) / 2), up-share = 0.5 + lean · 0.25 · (0.5 + 0.5 · conf)
                  </div>
                  <p className="text-[12.5px] text-muted">Confidence falls as the cross-book spread widens. Dumb mode pins lean to 0.</p>
                </div>
                <div id="formula-clip" className="scroll-mt-16 rounded-card border border-line bg-surface-2/30 p-5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-[14.5px] font-bold text-fg">2. Clip Mix</h4>
                    <Badge tone="info">Signature match</Badge>
                  </div>
                  <div className="my-4 overflow-x-auto rounded-tile border border-line bg-surface p-4 text-center font-serif text-[18px] text-fg shadow-sm">
                    shares = 30 every 3rd fill, else 13.86 (cap 50)
                  </div>
                  <p className="text-[12.5px] text-muted">Yields ~30% exact-30s fills and a $316 median window, matching the tape.</p>
                </div>
                <div id="formula-payout" className="scroll-mt-16 rounded-card border border-line bg-surface-2/30 p-5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-[14.5px] font-bold text-fg">3. Hold-to-Redeem Payout</h4>
                    <Badge tone="success">No exits</Badge>
                  </div>
                  <div className="my-4 overflow-x-auto rounded-tile border border-line bg-surface p-4 text-center font-serif text-[18px] text-fg shadow-sm">
                    payout = Σ shares<sub>winner</sub> · $1 &nbsp;&nbsp;·&nbsp;&nbsp; net = payout − cost
                  </div>
                  <p className="text-[12.5px] text-muted">24h replay: $129,251 paid on $128,718 staked across 280 resolved windows.</p>
                </div>
              </div>
            </Card>
          </section>

          <section id="strategy-exits" aria-label="Resolution" className="scroll-mt-16 space-y-6">
            <Card id="exit-matrix" className="scroll-mt-16 p-6">
              <h3 className="text-[16px] font-semibold text-fg">What Happens at Close</h3>
              <p className="text-[13px] text-muted">There is no exit matrix. Every fill is held to the market outcome.</p>
              <div className="mt-5 space-y-3">
                <div className="rounded-tile border border-line bg-surface p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2.5">
                      <Badge tone="success">Winner pays $1</Badge>
                      <span className="text-[14px] font-semibold text-fg">Resolution settles each side at $1 or $0</span>
                    </div>
                  </div>
                  <p className="mt-2 text-[13px] leading-relaxed text-muted">The loop polls the market until one outcome prices at 1, credits winning shares at face, and logs the window net.</p>
                </div>
                <div className="rounded-tile border border-line bg-surface p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2.5">
                      <Badge tone="neutral">Losers expire worthless</Badge>
                      <span className="text-[14px] font-semibold text-fg">No stop-loss, no salvage sale</span>
                    </div>
                  </div>
                  <p className="mt-2 text-[13px] leading-relaxed text-muted">Selling a dying side locks in the loss for pennies — the tape shows zero sells, so neither does the loop.</p>
                </div>
              </div>
            </Card>
          </section>

          <section id="strategy-risk" aria-label="Guardrails" className="scroll-mt-16 space-y-6">
            <Card className="p-6">
              <h3 className="text-[16px] font-semibold text-fg">Paper Guardrails</h3>
              <p className="text-[13px] text-muted">Caps that keep a runaway loop honest — all paper, all pre-live.</p>
              <div id="risk-caps" className="mt-6 grid scroll-mt-16 gap-4 sm:grid-cols-3">
                <div className="rounded-tile border border-line bg-surface p-3.5">
                  <span className="text-[11px] font-mono uppercase text-faint">Per-window cap</span>
                  <p className="mt-1 text-[16px] font-bold">$4,000 · 500 fills</p>
                  <p className="text-[12px] text-muted">Stops above the $3,804 max observed</p>
                </div>
                <div className="rounded-tile border border-line bg-surface p-3.5">
                  <span className="text-[11px] font-mono uppercase text-faint">Single-window invariant</span>
                  <p className="mt-1 text-[16px] font-bold">One window at a time</p>
                  <p className="text-[12px] text-muted">The target never overlaps windows</p>
                </div>
                <div id="risk-fidelity" className="scroll-mt-16 rounded-tile border border-line bg-surface p-3.5">
                  <span className="text-[11px] font-mono uppercase text-faint">Fidelity gate</span>
                  <p className="mt-1 text-[16px] font-bold">288 paper windows</p>
                  <p className="text-[12px] text-muted">No live funding until the diff passes</p>
                </div>
              </div>
              <p className="mt-3 flex items-start gap-2 text-[12px] leading-relaxed text-muted">
                <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warning" />
                The kill-switch pauses entries mid-loop and the desk resumes on demand; every knob behind these caps lives on the Config page.
              </p>
            </Card>
          </section>
        </div>

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
                        isActive ? 'bg-surface font-semibold text-accent shadow-sm' : 'font-medium text-muted hover:bg-surface hover:text-fg'
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
            <p className="text-[13.5px] font-medium text-fg">Measured, not modeled</p>
            <p className="text-[12.5px] text-muted">Every number above comes from dangerously-skip-permissions_24h_trades.csv.</p>
          </div>
        </div>
        <Link to="/config" className="text-[12.5px] font-medium text-fg hover:underline">
          Tune threshold settings →
        </Link>
      </Card>
    </div>
  )
}
