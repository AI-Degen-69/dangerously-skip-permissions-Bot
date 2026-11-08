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
  verdict: { action: 'enter' | 'skip' | 'blocked' | 'refuse' | 'done'; reason: string; detail: Record<string, unknown> }
  oddsHistory?: { t: number; v: number }[]
}

export interface RiskState {
  dayKey: string
  tradesToday: number
  tradesTodayByInterval: Record<Interval, number>
  consecutiveLosses: number
  realizedPnlUsd: number
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

export interface BotSnapshot {
  version: 1
  mode: 'paper' | 'live'
  asset: string
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
    maxDrawdownPct: number
    maxConcurrentPositions: number
    minEdge: number
    feeRate: number
    profitTargetCents: number
  }
  killSwitch: boolean
  newsBlocked: boolean
  feed: { price: number | null; updatedAtMs: number | null; history: { ts: number; value: number }[] }
  markets: MarketView[]
  positions: PositionView[]
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
}

export interface PerfGate {
  key: string
  label: string
  value: string
  target: string
  status: 'pass' | 'warn' | 'fail' | 'sample'
  judged: boolean
  detail: string
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
  upFills: number
  downFills: number
  zeroPriceFills: number
  mShape: number[]
}

export interface PerfNote {
  tone: 'success' | 'info' | 'warning' | 'danger'
  title: string
  body: string
}

export interface BotPerf {
  summary: {
    bankrollUsd?: number
    settled: number
    pending: number
    fills: number
    costUsd: number
    payoutUsd: number
    netUsd: number
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
  }
  targets: {
    windows: number
    medianFills: number
    meanFills: number
    medianCostUsd: number
    meanCostUsd: number
    bothSides: number
  }
  gate: PerfGate[]
  mShape: {
    live: number[]
    target: number[]
    liveShare: number[]
    targetShare: number[]
    distance: number
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
    minEdge: number
    minModelProb: number
    maxModelProb: number
    maxEntryPriceCents: number
    minMovePct: number
    maxMovePct: number
    minHourlyRangePct: number
    tightChopRangeUsd: number
    maxSpreadCents: number
    noisePct: number
    nonLiveAnchorExtraMovePct: number
    kellyCut: number
    maxPositionPct: number
    minPositionUsd: number
    feeRate: number
  }
  exit: { profitTargetCents: number; stallBandLow: number; stallBandHigh: number; acceptLossBelowCents?: number; stopLossBelowCents?: number }
  risk: {
    maxConcurrentPositions: number
    maxTradesPerDay: number
    maxConsecutiveLosses: number
    dailyLossLimitPct: number
    maxDrawdownPct: number
    cooldownAfterLossSec: number
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
    retry: false,
  })

export const useBotEvents = () =>
  useQuery({
    queryKey: ['bot', 'events'],
    queryFn: () => getJson<{ items: BotEvent[] }>('/events?limit=150'),
    refetchInterval: 3_000,
    retry: false,
  })

export const useBotTrades = () =>
  useQuery({
    queryKey: ['bot', 'trades'],
    queryFn: () => getJson<{ items: BotTrade[] }>('/trades?limit=80'),
    refetchInterval: 5_000,
    retry: false,
  })

export const useBotKpis = () =>
  useQuery({
    queryKey: ['bot', 'kpis'],
    queryFn: () => getJson<{ kpis: BotKpis }>('/kpis'),
    refetchInterval: 5_000,
    retry: false,
  })

export const useBotControl = () =>
  useQuery({
    queryKey: ['bot', 'control'],
    queryFn: () => getJson<BotControl>('/control'),
    placeholderData: (prev) => prev,
    refetchInterval: 3_000,
    retry: false,
  })

export const useBotWsTicks = () =>
  useQuery({
    queryKey: ['bot', 'ws-ticks'],
    queryFn: () => getJson<{ status: WsStatus; ticks: WsTick[] }>('/ws-ticks'),
    placeholderData: (prev) => prev,
    refetchInterval: 1_000,
    retry: false,
  })

export const useBotPerf = () =>
  useQuery({
    queryKey: ['bot', 'perf'],
    queryFn: () => getJson<BotPerf>('/perf'),
    refetchInterval: 5_000,
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
  useBotMutation(() => send<{ running: boolean; pid: number | null; reason?: string }>('/start', 'POST'))

export const useStopBot = () =>
  useBotMutation(() => send<{ running: boolean; pid: number | null }>('/stop', 'POST'))
