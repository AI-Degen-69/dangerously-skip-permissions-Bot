import type { MiddlewareHandler } from 'hono'

import type { AppContext } from './env'

// Schema lives with the Worker: D1 has no migration tool on Freebuff Sites, so
// tables are created on the first request of each isolate (cheap: one batch of
// IF NOT EXISTS statements). Add new statements at the end for new columns or
// tables; never edit existing ones in place once deployed.
const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS workspaces (
    owner_sub TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at INTEGER NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS bot_windows (
    event_slug TEXT PRIMARY KEY,
    owner_sub TEXT NOT NULL,
    market TEXT NOT NULL,
    condition_id TEXT,
    up_token_id TEXT,
    down_token_id TEXT,
    trades INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    payout_usd REAL NOT NULL DEFAULT 0,
    net_usd REAL NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS bot_windows_owner ON bot_windows(owner_sub, event_slug)`,
  `CREATE TABLE IF NOT EXISTS bot_trades (
    id TEXT PRIMARY KEY,
    owner_sub TEXT NOT NULL,
    event_slug TEXT NOT NULL,
    type TEXT NOT NULL,
    outcome TEXT,
    side TEXT,
    price REAL,
    shares REAL,
    usd_amount REAL,
    tx_hash TEXT,
    ts_utc TEXT,
    created_at INTEGER NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS bot_trades_owner ON bot_trades(owner_sub, event_slug, created_at)`,
]

let ready: Promise<void> | undefined

export function ensureSchema(db: D1Database): Promise<void> {
  ready ??= db.batch(SCHEMA.map((sql) => db.prepare(sql))).then(
    () => undefined,
    (error) => {
      ready = undefined
      throw error
    },
  )
  return ready
}

/** Rejects early with a clear message when the database binding is missing. */
export const requireDb: MiddlewareHandler<AppContext> = async (c, next) => {
  const db = c.env.DB
  if (!db) {
    return c.json(
      { error: 'database_missing', message: 'No database is attached yet. Add D1 storage named DB and redeploy.' },
      503,
    )
  }
  await ensureSchema(db)
  c.set('db', db)
  await next()
}

export const id = () => crypto.randomUUID()
export const now = () => Date.now()
