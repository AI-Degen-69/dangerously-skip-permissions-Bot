// Factory defaults for the paper bot knobs (mirrors bot/config.json).
// Bounds clamp what the Config page will save; the engine re-reads the file
// every window, so a save applies on the next tick.

export const DEFAULT_CONFIG = {
  asset: 'BTC',
  intervals: ['5m'],
  mode: 'paper',
  bankrollUsd: 1000,
  entry: {
    clipSharesDefault: 30,
    clipEveryNth: 3,
    medianShares: 13.86,
    maxShares: 50,
    medianFillsTarget: 45,
    openDelaySec: 13,
    hedgeDelaySec: 15,
    stopBeforeCloseSec: 15,
    minFillPrice: 0.01,
    leanSource: 'microprice',
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
  'entry.clipEveryNth': [1, 10],
  'entry.medianShares': [1, 50],
  'entry.maxShares': [1, 50],
  'entry.medianFillsTarget': [5, 400],
  'entry.openDelaySec': [0, 120],
  'entry.hedgeDelaySec': [0, 120],
  'entry.stopBeforeCloseSec': [0, 120],
  'entry.minFillPrice': [0, 0.5],
  'risk.maxUsdPerWindow': [50, 50000],
  'risk.maxFillsPerWindow': [5, 500],
  'risk.dailyLossCapUsd': [10, 100000],
  'risk.maxConcurrentPositions': [1, 2],
}
