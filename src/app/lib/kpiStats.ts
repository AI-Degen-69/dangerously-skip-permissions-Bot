import type { BotPerf, PerfWindow } from './bot'

export interface CalculatedKpis {
  settled: number
  pending: number
  startingCapital: number
  currentCapital: number
  netUsd: number
  capitalReturnPct: number
  roiPct: number
  costUsd: number
  payoutUsd: number

  // Core KPIs
  winRate: number
  lossRate: number
  winsCount: number
  lossesCount: number
  scratchCount: number
  grossProfitUsd: number
  grossLossUsd: number
  profitFactor: number
  avgWinUsd: number
  avgLossUsd: number
  payoffRatio: number
  expectancyUsd: number
  expectancyRatio: number
  breakEvenWinRate: number | null
  edgePct: number | null

  // Risk & Volatility
  sharpeRatio: number
  sortinoRatio: number
  windowSharpe: number
  volatilityUsd: number
  maxDrawdownUsd: number
  maxDrawdownPct: number
  currentDrawdownUsd: number
  currentDrawdownPct: number
  highWaterUsd: number
  bestUsd: number
  worstUsd: number

  // Streaks
  currentStreak: number
  maxWinStreak: number
  maxLossStreak: number

  // Directional
  upCount: number
  downCount: number
  upWins: number
  downWins: number
  upWinRate: number
  downWinRate: number
  upNetUsd: number
  downNetUsd: number
  upFills: number
  downFills: number

  // Execution
  bothSidesCount: number
  bothSidesRate: number
  fills: number
  medianFills: number
  meanFills: number
  medianCostUsd: number
  meanCostUsd: number
  zeroPriceFills: number
}

function median(values: number[]): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

/**
 * Calculates quantitative KPIs and performance statistics for trading windows.
 * Grounded in quantitative finance methods with 105,120 5m-periods/year annualization.
 */
export function computeKpiStats(
  windows: PerfWindow[],
  startingCapital: number = 1000,
  apiSummary?: BotPerf['summary'],
): CalculatedKpis {
  const settled = windows.filter((w) => !w.pending)
  const pending = windows.filter((w) => w.pending)

  const costUsd = apiSummary?.costUsd ?? settled.reduce((sum, w) => sum + w.costUsd, 0)
  const payoutUsd = apiSummary?.payoutUsd ?? settled.reduce((sum, w) => sum + w.payoutUsd, 0)
  const netUsd = apiSummary?.netUsd ?? settled.reduce((sum, w) => sum + (w.netUsd ?? 0), 0)
  const currentCapital = startingCapital + netUsd
  const capitalReturnPct = startingCapital > 0 ? (netUsd / startingCapital) * 100 : 0
  const roiPct = costUsd > 0 ? (netUsd / costUsd) * 100 : 0

  const nets = settled.map((w) => w.netUsd ?? 0)
  const wins = nets.filter((n) => n > 0)
  const losses = nets.filter((n) => n < 0).map((n) => Math.abs(n))
  const scratches = nets.filter((n) => n === 0)

  const winsCount = apiSummary?.winsCount ?? apiSummary?.profitable ?? wins.length
  const lossesCount = apiSummary?.lossesCount ?? losses.length
  const scratchCount = scratches.length
  const winRate = settled.length > 0 ? winsCount / settled.length : 0
  const lossRate = settled.length > 0 ? lossesCount / settled.length : 0

  const grossProfitUsd = apiSummary?.grossProfitUsd ?? wins.reduce((sum, n) => sum + n, 0)
  const grossLossUsd = apiSummary?.grossLossUsd ?? losses.reduce((sum, n) => sum + n, 0)

  const profitFactor =
    apiSummary?.profitFactor ??
    (grossLossUsd > 0 ? grossProfitUsd / grossLossUsd : grossProfitUsd > 0 ? 99 : 0)

  const avgWinUsd =
    apiSummary?.avgWinUsd ?? (winsCount > 0 ? grossProfitUsd / winsCount : 0)
  const avgLossUsd =
    apiSummary?.avgLossUsd ?? (lossesCount > 0 ? grossLossUsd / lossesCount : 0)

  const payoffRatio =
    apiSummary?.payoffRatio ??
    (avgLossUsd > 0 ? avgWinUsd / avgLossUsd : avgWinUsd > 0 ? 99 : 0)

  const expectancyUsd =
    apiSummary?.expectancyUsd ?? (settled.length > 0 ? netUsd / settled.length : 0)
  const expectancyRatio =
    apiSummary?.expectancyRatio ?? (winRate * payoffRatio - lossRate)
  const activeRate = (winsCount + lossesCount) / (settled.length || 1)
  const breakEvenWinRate =
    apiSummary?.breakEvenWinRate !== undefined
      ? apiSummary.breakEvenWinRate
      : winsCount > 0 && payoffRatio > 0
        ? activeRate / (1 + payoffRatio)
        : null
  const edgePct =
    apiSummary?.edgePct !== undefined
      ? apiSummary.edgePct
      : breakEvenWinRate !== null
        ? (winRate - breakEvenWinRate) * 100
        : null

  // 105,120 5-minute windows in a 365-day year
  const ANNUAL_FACTOR = Math.sqrt(288 * 365)
  let sharpeRatio = apiSummary?.sharpeRatio ?? 0
  let sortinoRatio = apiSummary?.sortinoRatio ?? 0
  let windowSharpe = 0
  let volatilityUsd = 0

  if (nets.length >= 2) {
    const mean = nets.reduce((a, b) => a + b, 0) / nets.length
    const variance =
      nets.reduce((sum, n) => sum + Math.pow(n - mean, 2), 0) / (nets.length - 1)
    const stdev = Math.sqrt(variance)
    volatilityUsd = stdev

    if (stdev > 0.0001) {
      windowSharpe = mean / stdev
      if (!apiSummary?.sharpeRatio) {
        sharpeRatio = windowSharpe * ANNUAL_FACTOR
      }
    }

    const downsideSquares = nets.reduce(
      (sum, n) => sum + Math.pow(Math.min(0, n), 2),
      0,
    )
    const downsideVariance = downsideSquares / nets.length
    const downsideStdev = Math.sqrt(downsideVariance)

    if (!apiSummary?.sortinoRatio) {
      if (downsideStdev > 0.0001) {
        sortinoRatio = (mean / downsideStdev) * ANNUAL_FACTOR
      } else if (mean > 0) {
        sortinoRatio = 99
      }
    }
  }

  // Drawdown tracking along chronological equity curve
  const sortedChronological = [...settled].sort((a, b) => a.startMs - b.startMs)
  let equity = startingCapital
  let peak = equity
  let maxDdUsd = 0
  let maxDdPct = 0

  for (const w of sortedChronological) {
    const n = w.netUsd ?? 0
    equity += n
    if (equity > peak) peak = equity
    const dd = peak - equity
    const ddPct = peak > 0 ? (dd / peak) * 100 : 0
    if (dd > maxDdUsd) maxDdUsd = dd
    if (ddPct > maxDdPct) maxDdPct = ddPct
  }

  const currentDrawdownUsd = Math.max(0, peak - equity)
  const currentDrawdownPct = peak > 0 ? (currentDrawdownUsd / peak) * 100 : 0

  // Streaks
  let currentStreak = 0
  let maxWinStreak = 0
  let maxLossStreak = 0
  let streak = 0

  for (const w of sortedChronological) {
    const n = w.netUsd ?? 0
    if (n > 0) {
      streak = streak > 0 ? streak + 1 : 1
      if (streak > maxWinStreak) maxWinStreak = streak
    } else if (n < 0) {
      streak = streak < 0 ? streak - 1 : -1
      if (Math.abs(streak) > maxLossStreak) maxLossStreak = Math.abs(streak)
    } else {
      streak = 0
    }
  }
  currentStreak = streak

  // Directional metrics
  const upWindows = settled.filter((w) => w.winner === 'Up')
  const downWindows = settled.filter((w) => w.winner === 'Down')
  const upWins = upWindows.filter((w) => (w.netUsd ?? 0) > 0).length
  const downWins = downWindows.filter((w) => (w.netUsd ?? 0) > 0).length
  const upNetUsd = upWindows.reduce((sum, w) => sum + (w.netUsd ?? 0), 0)
  const downNetUsd = downWindows.reduce((sum, w) => sum + (w.netUsd ?? 0), 0)
  const upWinRate = upWindows.length > 0 ? upWins / upWindows.length : 0
  const downWinRate = downWindows.length > 0 ? downWins / downWindows.length : 0

  const bothSidesCount = apiSummary?.bothSides ?? settled.filter((w) => w.bothSides).length
  const bothSidesRate =
    apiSummary?.bothSidesRate ?? (settled.length > 0 ? bothSidesCount / settled.length : 0)

  const fills = apiSummary?.fills ?? settled.reduce((sum, w) => sum + w.trades, 0)
  const tradesList = settled.map((w) => w.trades)
  const costList = settled.map((w) => w.costUsd)

  return {
    settled: settled.length,
    pending: pending.length,
    startingCapital,
    currentCapital,
    netUsd,
    capitalReturnPct,
    roiPct,
    costUsd,
    payoutUsd,

    winRate,
    lossRate,
    winsCount,
    lossesCount,
    scratchCount,
    grossProfitUsd,
    grossLossUsd,
    profitFactor,
    avgWinUsd,
    avgLossUsd,
    payoffRatio,
    expectancyUsd,
    expectancyRatio,
    breakEvenWinRate,
    edgePct,

    sharpeRatio: apiSummary?.sharpeRatio ?? sharpeRatio,
    sortinoRatio: apiSummary?.sortinoRatio ?? sortinoRatio,
    windowSharpe,
    volatilityUsd,
    maxDrawdownUsd: apiSummary?.maxDrawdownUsd ?? maxDdUsd,
    maxDrawdownPct:
      apiSummary?.maxDrawdownPct != null
        ? apiSummary.maxDrawdownPct * 100
        : maxDdPct,
    currentDrawdownUsd: apiSummary?.currentDrawdownUsd ?? currentDrawdownUsd,
    currentDrawdownPct:
      apiSummary?.currentDrawdownPct != null
        ? apiSummary.currentDrawdownPct * 100
        : currentDrawdownPct,
    highWaterUsd: peak,
    bestUsd: apiSummary?.bestUsd ?? (nets.length > 0 ? Math.max(...nets) : 0),
    worstUsd: apiSummary?.worstUsd ?? (nets.length > 0 ? Math.min(...nets) : 0),

    currentStreak: apiSummary?.currentStreak ?? currentStreak,
    maxWinStreak: apiSummary?.maxWinStreak ?? maxWinStreak,
    maxLossStreak: apiSummary?.maxLossStreak ?? maxLossStreak,

    upCount: upWindows.length,
    downCount: downWindows.length,
    upWins: apiSummary?.upWinRate !== undefined ? (apiSummary.upWins ?? upWins) : upWins,
    downWins: apiSummary?.downWinRate !== undefined ? (apiSummary.downWins ?? downWins) : downWins,
    upWinRate: apiSummary?.upWinRate ?? upWinRate,
    downWinRate: apiSummary?.downWinRate ?? downWinRate,
    upNetUsd: apiSummary?.upNetUsd ?? upNetUsd,
    downNetUsd: apiSummary?.downNetUsd ?? downNetUsd,
    upFills: apiSummary?.upFills ?? settled.reduce((sum, w) => sum + w.upFills, 0),
    downFills: apiSummary?.downFills ?? settled.reduce((sum, w) => sum + w.downFills, 0),

    bothSidesCount,
    bothSidesRate,
    fills,
    medianFills: apiSummary?.medianFills ?? median(tradesList),
    meanFills:
      apiSummary?.meanFills ??
      (tradesList.length > 0
        ? tradesList.reduce((a, b) => a + b, 0) / tradesList.length
        : 0),
    medianCostUsd: apiSummary?.medianCostUsd ?? median(costList),
    meanCostUsd:
      apiSummary?.meanCostUsd ??
      (costList.length > 0
        ? costList.reduce((a, b) => a + b, 0) / costList.length
        : 0),
    zeroPriceFills:
      apiSummary?.zeroPriceFills ?? settled.reduce((sum, w) => sum + w.zeroPriceFills, 0),
  }
}
