// Types shared by the Worker (src/worker) and the app (src/app).

export interface BotConstants {
  clipSharesDefault: number
  clipSharesFraction: number
  maxShares: number
  meanTradesPerWindow: number
  medianTradesPerWindow: number
  bothSidesRate: number
  numWindows24h: number
  buyOnly: boolean
  holdToRedeem: boolean
}

export interface BotStatus {
  constants: BotConstants
  windows: number
  trades: number
  paperGate: string
}

export interface Me {
  user: { sub: string; name?: string; email?: string; picture?: string }
  workspace: { name: string }
  capabilities: { database: boolean; auth: 'freebuff' | 'development' }
}
