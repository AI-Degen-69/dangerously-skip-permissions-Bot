import { Hono } from 'hono'

import { privateJson } from '../auth'
import { id, now } from '../db'
import type { AppContext } from '../env'
import { BOT_PERF } from '../../shared/botPerf'
import type { BotConstants, BotStatus } from '../../shared/types'

export const BOT_CONSTANTS: BotConstants = {
  clipSharesDefault: 30,
  clipSharesFraction: 0.304,
  maxShares: 50,
  meanTradesPerWindow: 58.5,
  medianTradesPerWindow: 45,
  bothSidesRate: 0.972,
  numWindows24h: 288,
  buyOnly: true,
  holdToRedeem: true,
}

const TARGET_PROXY = '0xc53375ff94e96100f2b30a4b5775db35218d69a9'

export const bot = new Hono<AppContext>()

bot.get('/status', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const counts = await db.batch([
    db.prepare(`SELECT COUNT(*) AS n, COALESCE(SUM(trades),0) AS t FROM bot_windows WHERE owner_sub = ?`).bind(owner),
    db.prepare(`SELECT COUNT(*) AS n FROM bot_trades WHERE owner_sub = ?`).bind(owner),
  ])
  const windows = (counts[0].results[0] ?? {}) as { n?: number; t?: number }
  const trades = (counts[1].results[0] ?? {}) as { n?: number }
  const body: BotStatus = {
    constants: BOT_CONSTANTS,
    windows: Number(windows.n ?? 0),
    trades: Number(trades.n ?? 0),
    paperGate: '288-window paper fidelity (45 median trades/window, both-sides rate, M0-M4 shape) — no live funding until gate passes',
  }
  return privateJson(c, body)
})

bot.get('/constants', (c) => privateJson(c, BOT_CONSTANTS))

// Frozen 24h replay of the target wallet (method in botPerf.ts header).
bot.get('/performance', (c) => privateJson(c, BOT_PERF))

// Live target-wallet snapshot via public Data API v2 (proxy wallet, no keys).
bot.get('/target', async (c) => {
  const [positions, value] = await Promise.all([
    fetch(`https://data-api.polymarket.com/v2/positions?user=${TARGET_PROXY}&limit=5`).then((r) => r.json()).catch(() => null),
    fetch(`https://data-api.polymarket.com/v2/value?user=${TARGET_PROXY}`).then((r) => r.json()).catch(() => null),
  ])
  return privateJson(c, { proxy: TARGET_PROXY, positions, value })
})

bot.get('/windows', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const limit = Math.min(Number(c.req.query('limit') ?? 20), 100)
  const rows = await db
    .prepare(`SELECT event_slug, market, trades, cost_usd, payout_usd, net_usd FROM bot_windows WHERE owner_sub = ? ORDER BY event_slug DESC LIMIT ?`)
    .bind(owner, limit)
    .all()
  return privateJson(c, { items: rows.results ?? [] })
})

bot.post('/windows/seed', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const body = await c.req.json<{ event_slug: string; market: string }>().catch(() => null)
  if (!body?.event_slug || !body?.market) return c.json({ error: 'event_slug and market are required.' }, 400)
  await db
    .prepare(
      `INSERT OR IGNORE INTO bot_windows (event_slug, owner_sub, market, trades, cost_usd, payout_usd, net_usd, created_at) VALUES (?, ?, ?, 0, 0, 0, 0, ?)`,
    )
    .bind(body.event_slug, owner, body.market, now())
    .run()
  return privateJson(c, { ok: true, id: id() })
})

// Bulk import paper windows (from bot/run_paper.py). Same-origin + auth enforced by middleware.
bot.post('/import', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const body = await c.req.json<{ windows?: { event_slug: string; market: string; trades: number; cost_usd: number; payout_usd: number; net_usd: number }[] }>().catch(() => null)
  const items = body?.windows ?? []
  if (!Array.isArray(items) || items.length === 0 || items.length > 500) {
    return c.json({ error: 'windows must be a non-empty array (max 500).' }, 400)
  }
  const stmts = items.slice(0, 500).map((w) =>
    db
      .prepare(
        `INSERT OR REPLACE INTO bot_windows (event_slug, owner_sub, market, trades, cost_usd, payout_usd, net_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .bind(w.event_slug, owner, w.market ?? w.event_slug, Number(w.trades ?? 0), Number(w.cost_usd ?? 0), Number(w.payout_usd ?? 0), Number(w.net_usd ?? 0), now()),
  )
  await db.batch(stmts)
  return privateJson(c, { ok: true, imported: stmts.length })
})
