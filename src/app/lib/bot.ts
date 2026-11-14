import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

export type Interval = '5m' | '15m'
export type Side = 'Up' | 'Down'

export interface MarketView {
  slug: string
  interval: Interval
  startMs: number
  endMs: number
  price: number | null
  anchor: { value: number; source: 'live' | 'history' | 'published' } | null
  movePct: number | null
  requiredMovePct: number
  side: Side | null
  quotes: Record<Side, { bid: number | null; ask: number | null }>
  modelProb: number | null
  edge: number | null
  spreadCents: number | null
  secondsRemaining: number
  verdict: { action: 'enter' | 'skip' | 'blocked' | 'refuse' | 'done' | 'snipe'; reason: string; detail: Record<string, unknown> }
  oddsHistory?: { t: number; v: number }[]
  lean?: number | null
  leanSource?: string | null
}

export interface RiskState {
  dayKey: string
  tradesToday: number
  tradesTodayByInterval: Record<Interval, number>
  consecutiveLosses: number
  realizedPnlUsd: number
  dailyLossUsd?: number
  dayStartEquityUsd: number
  highWaterEquityUsd: number
  halted: boolean
  haltReason: string | null
  cooldownUntilMs: number
}

export interface PositionView {
  id: string
  slug: string
  interval: Interval
  side: Side
  shares: number
  entryPrice: number
  costUsd: number
  modelProb: number
  edge: number
  entryAtMs: number
  endMs: number
  bid: number | null
  mark: number | null
  markValueUsd: number | null
  unrealizedPnlUsd: number | null
  secondsLeft: number
  stalledSec: number | null
  resolving?: boolean
}

export interface OpenOrderView {
  side: Side
  price: number
  shares: number
  queueAhead: number
  placedAtMs: number
  ageMs: number
  minute: number
  subReason: string
}

export interface WsBookSummary {
  asset_id: string
  outcome: string
  best_bid: number | null
  best_ask: number | null
  midpoint: number | null
  bid_depth: number
  ask_depth: number
  last_update_ts: number
}

export interface WsStatus {
  state: 'connecting' | 'connected' | 'stale' | 'disconnected' | 'fallback_active'
  is_connected: boolean
  is_stale: boolean
  age_ms: number | null
  reconnect_count: number
  tick_count: number
  up_book?: WsBookSummary
  down_book?: WsBookSummary
}

export interface WsTick {
  ts: number
  time_str: string
  outcome: Side
  event_type: 'snapshot' | 'price_change'
  side: 'BUY' | 'SELL' | null
  price: number | null
  size: number | null
  best_bid: number | null
  best_ask: number | null
  midpoint: number | null
  bid_size?: number | null
  ask_size?: number | null
}

export interface StrategyInfo {
  id: string
  symbol: string
  name: string
  signature?: string
  makerShareTarget?: number
  pairCostTarget?: number
  priceFloor?: number
  priceCeiling?: number
  cutoffSec?: number
}

export interface StrategyFeatures {
  sizing?: string
  dollarRisk?: number
  preflightGate?: boolean
  patientHedge?: boolean
  heavyAtomic?: boolean
  sweep?: boolean
  pairedVolumeCapped?: boolean
  blurb?: string
}

export interface StrategySetup {
  id: string
  symbol: string
  name: string
  signature: string
  description: string
  configHighlights?: Record<string, string>
  features?: StrategyFeatures
  entry: {
    clipSharesDefault: number
    maxShares: number
    minFillPrice: number
    maxFillPrice: number
    benchmarkPairCost: number
    targetPairCost: number
    maxPairCost: number
    maxShareLead: number
    maxUnhedgedUsd?: number
    dipCurve?: { lo: number; hi: number; sharesLo: number; sharesHi: number }
    rescuePairCostMax?: number
    rescueCeilingPrice?: number
    maxDepthShares?: number
    startAfterOpenSec: number
    stopBeforeCloseSec: number
    minSpacingMoveSec: number
    minSpacingStaticSec: number
    includeTakerFee: boolean
    wholeLadderClips: boolean
  }
  isActive?: boolean
}

export interface BotSnapshot {
  version: 1
  mode: 'paper' | 'live'
  asset: string
  strategy?: StrategyInfo
  updatedAt: string
  equityUsd: number
  bankrollUsd: number
  exposureUsd: number
  cashUsd: number
  realizedPnlUsd: number
  risk: RiskState
  limits: {
    maxTradesPerDay: number
    maxConsecutiveLosses: number
    dailyLossLimitPct: number
    dailyLossCapUsd?: number
    maxDrawdownPct: number
    maxConcurrentPositions: number
    minEdge: number
    feeRate: number
    profitTargetCents: number
  }
  killSwitch: boolean
  newsBlocked: boolean
  feed: { price: number | null; updatedAtMs: number | null; history: { ts: number; value: number }[] }
  lean?: number | null
  leanSource?: string | null
  markets: MarketView[]
  positions: PositionView[]
  openOrders?: OpenOrderView[]
  ws?: WsStatus
  recentTicks?: WsTick[]
}

export interface BotEvent {
  ts: string
  kind: string
  slug?: string
  interval?: Interval
  side?: Side
  reason: string
  detail?: Record<string, unknown>
  mode?: 'paper' | 'live'
}

export interface BotTrade {
  ts: string | number
  kind: string
  slug?: string
  interval?: Interval
  side?: Side
  shares?: number
  price?: number
  usd?: number
  pnlUsd?: number
  reason?: string
  mode?: 'paper' | 'live'
  detail?: Record<string, unknown>
}

export interface BotKpis {
  bankrollUsd: number
  equityUsd: number
  netPnlUsd: number
  closedTrades: number
  wins: number
  losses: number
  winRate: number
  profitFactor: number
  avgWinUsd: number
  avgLossUsd: number
  largestWinUsd: number
  largestLossUsd: number
  openPositions: number
  byInterval: { interval: Interval; trades: number; wins: number; pnlUsd: number }[]
  equitySeries: { ts: number; equity: number }[]
  recentClosed: BotTrade[]
}

export interface RunItem {
  runId: string
  startedAt: string
  endedAt: string | null
  status: 'running' | 'completed' | 'interrupted' | 'failed' | 'view_only'
  mode: string
  label: string
  isActive?: boolean
  windowsCount?: number
  summary?: Record<string, unknown>
  /** Config captured when the run was opened; `strategy.id` ties the session to a strategy setup. */
  configSnapshot?: { strategy?: { id?: string; symbol?: string; name?: string } } & Record<string, unknown>
}

export interface TapeStatus {
  enabled: boolean
  runId: string | null
  tapeDir: string | null
  prints: number
  books: number
  mb: number
}

export interface BotControl {
  running: boolean
  pid: number | null
  snapshotAgeMs: number | null
  mode: 'paper' | 'live'
  logPath: string
  activeRunId?: string | null
  selectedRunId?: string | null
  isViewOnly?: boolean
  strategy?: StrategyInfo
  tape?: TapeStatus
}

/** One cell of the execution-health matrix: a label, the number, its parts. */
export interface PerfCell {
  key: string
  label: string
  value: string
  /** `stat` cells are plain measurements with no target to judge against. */
  status: 'pass' | 'warn' | 'fail' | 'stat'
  /** Layer above the rest: the number the other cells are built from. */
  big?: boolean
  /** How many grid columns the cell spans. */
  span?: number
  sub: { label: string; value: string; tone?: string }[]
}

export interface PerfWindow {
  slug: string
  market: string | null
  startMs: number
  trades: number
  costUsd: number
  payoutUsd: number
  netUsd: number | null
  winner: Side | null
  pending: boolean
  redeemed: boolean
  bothSides: boolean
  /** Lock-in cost of a both-sided window (avg Up + avg Down); null otherwise. */
  pairCost: number | null
  upFills: number
  downFills: number
  zeroPriceFills: number
  /** Maker fills - the ones the tape can corroborate. */
  makerFills?: number
  /** Taker fills - paper mode has no real book, so these cannot be checked. */
  takerFills?: number
  mShape: number[]
  /** Per-minute queue verdicts for audited maker fills. */
  mAttainable: number[]
  mPhantom: number[]
  /** Taker fees already charged inside costUsd. */
  feesUsd?: number
  /** Taker fees on the maker fills, the pool a maker rebate is drawn from. */
  makerFeeBaseUsd?: number
  /** What the fill auditor found once the window resolved; null when unaudited. */
  fidelity?: WindowFidelity | null
  /** The same window recomputed from the fills the tape verifier confirmed. */
  verified?: {
    trades: number
    costUsd: number
    payoutUsd: number
    netUsd: number | null
    feesUsd: number
    makerFeeBaseUsd: number
    upFills: number
    downFills: number
    zeroPriceFills: number
  }
}

/**
 * The window measured by what a real resting bid could have got, not by what
 * the price touched: a maker fill needs taker selling at or below its limit
 * that outlasts the queue already resting at that level.
 */
export interface WindowFidelity {
  makerFills: number
  attainableFills: number
  phantomFills: number
  /** Maker fills where the queue ahead was recorded at fill time. */
  queueKnown: number
  assumedShares: number
  attainableShares: number
  attainableCostUsd: number
  attainablePayoutUsd: number
  attainableNetUsd: number
}

export interface PerfNote {
  tone: 'success' | 'info' | 'warning' | 'danger'
  title: string
  body: string
}

export interface BotPerf {
  strategy?: StrategyInfo
  summary: {
    bankrollUsd?: number
    settled: number
    pending: number
    fills: number
    costUsd: number
    payoutUsd: number
    netUsd: number
    feesUsd?: number
    makerFeeBaseUsd?: number
    roi: number
    profitable: number
    hitRate: number
    bothSides: number
    bothSidesRate: number
    medianFills: number
    meanFills: number
    medianCostUsd: number
    meanCostUsd: number
    bestUsd: number
    worstUsd: number
    zeroPriceFills: number
    upFills: number
    downFills: number
    upWins: number
    downWins: number
    winRate?: number
    lossRate?: number
    winsCount?: number
    lossesCount?: number
    grossProfitUsd?: number
    grossLossUsd?: number
    profitFactor?: number
    avgWinUsd?: number
    avgLossUsd?: number
    payoffRatio?: number
    expectancyUsd?: number
    expectancyRatio?: number
    breakEvenWinRate?: number | null
    edgePct?: number | null
    sharpeRatio?: number
    sortinoRatio?: number
    maxDrawdownUsd?: number
    maxDrawdownPct?: number
    currentDrawdownUsd?: number
    currentDrawdownPct?: number
    currentStreak?: number
    maxWinStreak?: number
    maxLossStreak?: number
    upWindows?: number
    downWindows?: number
    upNetUsd?: number
    downNetUsd?: number
    upWinRate?: number
    downWinRate?: number
    /** The run judged by what a real resting bid could have got, pre-rebate. */
    attainable?: {
      windows: number
      makerFills: number
      attainableFills: number
      phantomFills: number
      queueKnownFills: number
      costUsd: number
      payoutUsd: number
      netUsd: number
      fillRate: number
      shareRate: number
    }
  }
  cells: PerfCell[]
  mShape: {
    live: number[]
    liveShare: number[]
    /** Per-minute audited maker fills a real bid could have got. */
    attainable: number[]
    /** Per-minute audited maker fills the queue ahead never cleared. */
    phantom: number[]
  }
  redeem: { count: number; payoutUsd: number }
  health: {
    loopRunning: boolean
    pid: number | null
    killSwitch: boolean
    stateSlug: string | null
    stateFills: number
    snapshotAgeSec: number | null
    windowEndsInSec: number | null
  }
  notes: PerfNote[]
  windows: PerfWindow[]
  generatedAt: string
}

export interface BotConfigView {
  asset: string
  intervals: Interval[]
  mode: 'paper' | 'live'
  bankrollUsd: number
  entry: {
    startAfterOpenSec?: number
    stopBeforeCloseSec?: number
    clipSharesDefault?: number
    maxShares?: number
    minFillPrice?: number
    maxFillPrice?: number
    targetPairCost?: number
    maxPairCost?: number
    maxShareLead?: number
    minSpacingMoveSec?: number
    minSpacingStaticSec?: number
    includeTakerFee?: boolean
    wholeLadderClips?: boolean
    minEdge?: number
    minModelProb?: number
    maxModelProb?: number
    maxEntryPriceCents?: number
    minMovePct?: number
    maxMovePct?: number
    minHourlyRangePct?: number
    tightChopRangeUsd?: number
    maxSpreadCents?: number
    noisePct?: number
    nonLiveAnchorExtraMovePct?: number
    kellyCut?: number
    maxPositionPct?: number
    minPositionUsd?: number
    feeRate?: number
    [key: string]: unknown
  }
  exit: { profitTargetCents: number; stallBandLow?: number; stallBandHigh?: number; acceptLossBelowCents?: number; stopLossBelowCents?: number }
  risk: {
    maxFillsPerWindow?: number
    dailyLossCapUsd?: number
    maxConcurrentPositions: number
    maxTradesPerDay: number
    maxConsecutiveLosses: number
    dailyLossLimitPct: number
    maxDrawdownPct: number
    cooldownAfterLossSec: number
    [key: string]: unknown
  }
  news: { blackoutMinutes: number; events: string[] }
  intervalParams: Record<
    Interval,
    { observationSeconds: number; minDirectionHoldSeconds: number; minRemainingSeconds: number; stallSeconds: number }
  >
}

/**
 * The bot's API is a separate local process on loopback, so it is addressed
 * directly rather than through the app's worker (which never reaches the
 * machine). Its CORS policy accepts loopback origins only.
 */
export const BOT_ORIGIN = import.meta.env.VITE_BOT_ORIGIN ?? 'http://127.0.0.1:8789'
const botUrl = (path: string) => `${BOT_ORIGIN}/api/bot${path}`

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(botUrl(path), { headers: { accept: 'application/json' } })
  if (!response.ok) throw new Error(`Bot API returned ${response.status}`)
  return (await response.json()) as T
}

async function send<T>(path: string, method: 'POST' | 'PUT', body?: unknown): Promise<T> {
  const response = await fetch(botUrl(path), {
    method,
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const json = (await response.json().catch(() => ({}))) as T & { error?: string }
  if (!response.ok) throw new Error(json.error ?? `Bot API returned ${response.status}`)
  return json
}

// ---------------------------------------------------------------- read queries

export const useBotSnapshot = () =>
  useQuery({
    queryKey: ['bot', 'snapshot'],
    queryFn: () => getJson<{ online: boolean; snapshot: BotSnapshot | null; ageMs: number | null }>('/snapshot'),
    placeholderData: (prev) => prev,
    refetchInterval: 2_000,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    staleTime: 1_000,
    retry: false,
  })

export const useBotEvents = () =>
  useQuery({
    queryKey: ['bot', 'events'],
    queryFn: () => getJson<{ items: BotEvent[] }>('/events?limit=150'),
    refetchInterval: 3_000,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    retry: false,
  })

export const useBotTrades = () =>
  useQuery({
    queryKey: ['bot', 'trades'],
    // risk.maxFillsPerWindow is 500: a smaller limit would truncate the active
    // window's fills and drop its oldest chart markers.
    queryFn: () => getJson<{ items: BotTrade[] }>('/trades?limit=500'),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    retry: false,
  })

export const useBotKpis = () =>
  useQuery({
    queryKey: ['bot', 'kpis'],
    queryFn: () => getJson<{ kpis: BotKpis }>('/kpis'),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    retry: false,
  })

export const useBotControl = (live = true) =>
  useQuery({
    queryKey: ['bot', 'control'],
    queryFn: () => getJson<BotControl>('/control'),
    placeholderData: (prev) => prev,
    refetchInterval: live ? 3_000 : false,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: live,
    retry: false,
  })

export const useBotWsTicks = () =>
  useQuery({
    queryKey: ['bot', 'ws-ticks'],
    queryFn: () => getJson<{ status: WsStatus; ticks: WsTick[] }>('/ws-ticks'),
    placeholderData: (prev) => prev,
    refetchInterval: 1_000,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    staleTime: 500,
    retry: false,
  })

export const useBotPerf = () =>
  useQuery({
    queryKey: ['bot', 'perf'],
    queryFn: () => getJson<BotPerf>('/perf'),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    retry: false,
  })

export const useBotConfig = () =>
  useQuery({
    queryKey: ['bot', 'config'],
    queryFn: () => getJson<{ config: BotConfigView; configFile: string }>('/config'),
    retry: false,
    staleTime: 10_000,
  })

// --------------------------------------------------------------------- writes

function useBotMutation<TInput, TResult>(run: (input: TInput) => Promise<TResult>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => client.invalidateQueries({ queryKey: ['bot'] }),
  })
}

export const useBotRuns = () =>
  useQuery({
    queryKey: ['bot', 'runs'],
    queryFn: () => getJson<{ runs: RunItem[]; activeRunId: string | null; selectedRunId: string | null; isViewOnly: boolean }>('/runs'),
    refetchInterval: 5_000,
    retry: false,
  })

export const useSelectRun = () =>
  useBotMutation((runId: string | null) =>
    send<{ selectedRunId: string | null; activeRunId: string | null; isViewOnly: boolean }>('/select-run', 'POST', { runId }),
  )

export const useSaveBotConfig = () =>
  useBotMutation((patch: Record<string, unknown>) =>
    send<{ config: BotConfigView; warnings: string[] }>('/config', 'PUT', patch),
  )

export const useResetBot = () =>
  useBotMutation(() => send<{ bankrollUsd: number; resetAt: string }>('/reset', 'POST'))

export const useSetKillSwitch = () =>
  useBotMutation((active: boolean) => send<{ killSwitch: boolean }>('/kill-switch', 'POST', { active }))

export const useResumeBot = () =>
  useBotMutation(() => send<{ ok: boolean; killSwitch: boolean }>('/resume', 'POST'))

export const useStartBot = () =>
  useBotMutation((opts?: { runId?: string | null; newSession?: boolean }) =>
    send<{ running: boolean; pid: number | null; reason?: string; runId?: string }>(
      '/start',
      'POST',
      opts?.newSession ? { newSession: true } : opts?.runId ? { runId: opts.runId } : {},
    ),
  )

export const useResumeRun = () =>
  useBotMutation((runId?: string | null) =>
    send<{ running: boolean; pid: number | null; runId: string; activeRunId: string; isViewOnly: boolean }>(
      '/resume-run',
      'POST',
      runId ? { runId } : {},
    ),
  )

export const useStopBot = () =>
  useBotMutation(() => send<{ running: boolean; pid: number | null }>('/stop', 'POST'))

export const useBotTape = () =>
  useQuery({
    queryKey: ['bot', 'tape'],
    queryFn: () => getJson<TapeStatus>('/tape'),
    placeholderData: (prev) => prev,
    refetchInterval: 5_000,
    retry: false,
  })

export const useRedeemBot = () =>
  useBotMutation(() =>
    send<{
      ok: boolean
      redeemedCount: number
      zeroCleanCount: number
      totalWindowsMarked: number
      payoutUsd: number
      redeemedAt: string
    }>('/redeem', 'POST'),
  )

export const useStrategySetups = () =>
  useQuery({
    queryKey: ['bot', 'strategy-setups'],
    queryFn: () => getJson<{ activeSetupId: string; setups: StrategySetup[] }>('/strategy-setups'),
    refetchInterval: 5_000,
    retry: false,
  })

/** Union backend setups with local presets so a newly-added preset (e.g. DSP-v2.3)
 *  stays selectable even while an older API process is still serving a stale list. */
export function mergeStrategySetups(
  backend: StrategySetup[] | undefined,
  fallback: Record<string, StrategySetup>,
): StrategySetup[] {
  const byId = new Map<string, StrategySetup>()
  for (const preset of Object.values(fallback)) byId.set(preset.id, preset)
  for (const item of backend ?? []) byId.set(item.id, { ...(byId.get(item.id) ?? {} as StrategySetup), ...item })
  return [...byId.values()]
}

export const useSelectStrategySetup = () =>
  useBotMutation((setupId: string) =>
    send<{ ok: boolean; activeSetupId: string; setup: StrategySetup; config: BotConfigView }>('/strategy-setup', 'POST', { setupId }),
  )

export interface AbTestWindow {
  slug: string
  epoch: number
  net: number
  payout: number
  cost: number
  pairCost: number | null
  imbalance: number
  fills: number
  upShares: number
  downShares: number
  winner: string | null
}

export interface AbTestDistributionStats {
  runId: string | null
  name: string
  description?: string
  signature?: string
  configHighlights?: Record<string, string>
  entry?: Record<string, number | boolean>
  features?: StrategyFeatures
  samples: number
  targetSamples?: number
  progressPct?: number
  /** Total 5m windows observed with the loop on (informational only, never N). */
  observedWindows: number
  /** Active traded windows (fills > 0): the Welch t-test sample N. */
  activeWindows: number
  /** Paired windows (upShares > 0 && downShares > 0). Target 60. */
  pairedWindows: number
  /** Sub-$1.00 pairs (pairCost < 1.00). Target 35+. */
  subDollarPairs: number
  pairCostUnder096: number
  pairCost096to100: number
  pairCostOver100: number
  totalLockedShares: number
  pairsMerged: number
  wins: number
  losses: number
  scratches: number
  winRate: number
  lossRate: number
  netPnl: number
  meanPnl: number
  stdPnl: number
  variance: number
  medianPnl: number
  q25Pnl: number | null
  q75Pnl: number | null
  meanMinusStd: number | null
  meanPlusStd: number | null
  minPnl: number
  maxPnl: number
  meanPairCost: number
  /** Rebate bases for the with-rebates view (same inputs as the dashboard). */
  feesUsd?: number
  makerFeeBaseUsd?: number
  zeroImbalancePct: number
  pnlList: number[]
  windows: AbTestWindow[]
}

export interface AbTestHistogramBin {
  label: string
  range: [number, number]
  baselineCount: number
  baselinePct: number
  candidateCount: number
  candidatePct: number
}

export interface AbTestStatistics {
  targetSampleSize: number
  targetPaired: number
  targetSubDollar: number
  alpha: number
  confidenceLevel: string
  power: string
  tStatistic: number
  /** Dynamic one-tailed critical value from the Welch-Satterthwaite df (null when N too small). */
  tCritical: number | null
  /** Exact active-window mean the candidate must cross to reject H0 (null when N too small). */
  muCritical: number | null
  standardError: number
  pValue: number
  degreesOfFreedom: number
  cohenD: number
  meanDiff: number
  ci95: [number, number]
  significant: boolean
  verdict: string
  verdictTone: 'neutral' | 'info' | 'accent' | 'success' | 'danger'
}

export interface AbTestHypotheses {
  nullHypothesis: string
  altHypothesis: string
  decisionRule: string
}

export interface AbTestData {
  status: string
  updatedAt: string
  baseline: AbTestDistributionStats
  candidate: AbTestDistributionStats
  statistics: AbTestStatistics
  hypotheses: AbTestHypotheses
  histogram: AbTestHistogramBin[]
}

export const useAbTestData = (live = true) =>
  useQuery({
    queryKey: ['bot', 'ab-test'],
    queryFn: () => getJson<AbTestData>('/ab-test'),
    placeholderData: (prev) => prev,
    refetchInterval: live ? 10_000 : false,
    refetchOnWindowFocus: false,
    retry: false,
  })

export const useStartAbCandidate = () =>
  useBotMutation(() => send<{ ok: boolean; candidateRunId: string; data: AbTestData }>('/ab-test/start', 'POST'))

export const useStopAbCandidate = () =>
  useBotMutation(() => send<{ ok: boolean; data: AbTestData }>('/ab-test/stop', 'POST'))

