// Factory defaults for the MSR-v2 paper bot knobs (mirrors bot/config.json).
// Bounds clamp what the Config page will save; the engine re-reads the file
// every window, so a save applies on the next tick.

export const DEFAULT_CONFIG = {
  asset: 'BTC',
  intervals: ['5m'],
  mode: 'paper',
  bankrollUsd: 1000,
  entry: {
    startAfterOpenSec: 4,
    stopBeforeCloseSec: 12,
    clipSharesDefault: 30,
    maxShares: 50,
    minFillPrice: 0.07,
    maxFillPrice: 0.975,
    benchmarkPairCost: 0.965,
    targetPairCost: 0.965,
    maxPairCost: 0.990,
    maxShareLead: 90,
    minSpacingMoveSec: 0.5,
    minSpacingStaticSec: 2.5,
    includeTakerFee: true,
    wholeLadderClips: true,
  },
  risk: {
    maxUsdPerWindow: 4000,
    maxFillsPerWindow: 500,
    dailyLossCapUsd: 500,
    maxConcurrentPositions: 1,
  },
} as const

export const EDITABLE: Record<string, [number, number]> = {
  bankrollUsd: [100, 100000],
  'entry.clipSharesDefault': [1, 50],
  'entry.maxShares': [5, 100],
  'entry.minFillPrice': [0.01, 0.50],
  'entry.maxFillPrice': [0.70, 0.99],
  'entry.benchmarkPairCost': [0.80, 0.99],
  'entry.targetPairCost': [0.80, 0.99],
  'entry.maxPairCost': [0.90, 0.999],
  'entry.maxShareLead': [10, 300],
  'entry.startAfterOpenSec': [0, 30],
  'entry.stopBeforeCloseSec': [5, 60],
  'entry.minSpacingMoveSec': [0.1, 5.0],
  'entry.minSpacingStaticSec': [0.5, 10.0],
  'risk.maxUsdPerWindow': [500, 20000],
  'risk.maxFillsPerWindow': [50, 1000],
  'risk.dailyLossCapUsd': [50, 10000],
  'risk.maxConcurrentPositions': [1, 2],
}
