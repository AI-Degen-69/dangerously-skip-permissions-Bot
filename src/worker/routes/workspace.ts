import { Hono } from 'hono'

import { authMode, privateJson } from '../auth'
import { now } from '../db'
import type { AppContext } from '../env'
import type { Me } from '../../shared/types'

export const workspace = new Hono<AppContext>()

async function ensureWorkspace(db: D1Database, owner: string, name: string) {
  const row = await db.prepare(`SELECT name FROM workspaces WHERE owner_sub = ?`).bind(owner).first<{ name: string }>()
  if (row) return row
  await db.prepare(`INSERT INTO workspaces (owner_sub, name, created_at) VALUES (?, ?, ?)`).bind(owner, name, now()).run()
  return { name }
}

workspace.get('/me', async (c) => {
  const user = c.get('user')
  const db = c.get('db')
  const ws = await ensureWorkspace(db, user.sub, `${user.name?.split(' ')[0] ?? 'Your'}'s workspace`)
  const body: Me = {
    user: { sub: user.sub, name: user.name, email: user.email, picture: user.picture },
    workspace: { name: ws.name },
    capabilities: {
      database: true,
      auth: authMode(c.env, c.req.raw) === 'freebuff' ? 'freebuff' : 'development',
    },
  }
  return privateJson(c, body)
})

workspace.patch('/workspace', async (c) => {
  const { name } = await c.req.json<{ name?: string }>()
  const clean = name?.trim().slice(0, 60)
  if (!clean) return c.json({ error: 'Name is required.' }, 400)
  await c.get('db').prepare(`UPDATE workspaces SET name = ? WHERE owner_sub = ?`).bind(clean, c.get('user').sub).run()
  return privateJson(c, { ok: true })
})

// Clears the only per-user data the hosted desk keeps: imported paper windows
// and their trades. The workspace row (and its name) stays.
workspace.delete('/workspace/data', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  await db.batch([
    db.prepare(`DELETE FROM bot_trades WHERE owner_sub = ?`).bind(owner),
    db.prepare(`DELETE FROM bot_windows WHERE owner_sub = ?`).bind(owner),
  ])
  return privateJson(c, { ok: true })
})
