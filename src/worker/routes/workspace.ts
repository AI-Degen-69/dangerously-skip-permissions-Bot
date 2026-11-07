import { Hono } from 'hono'

import { authMode, privateJson } from '../auth'
import { ACTIVITY_SELECT, TASK_SELECT, mapActivity, mapTask, now } from '../db'
import type { AppContext } from '../env'
import { clearWorkspace, seedWorkspace } from '../seed'
import type { DealStage, Me, Overview } from '../../shared/types'

export const workspace = new Hono<AppContext>()

async function ensureWorkspace(db: D1Database, owner: string, name: string) {
  const row = await db.prepare(`SELECT name, seeded_at FROM workspaces WHERE owner_sub = ?`).bind(owner).first<{ name: string; seeded_at: number | null }>()
  if (row) return row
  await db.prepare(`INSERT INTO workspaces (owner_sub, name, created_at) VALUES (?, ?, ?)`).bind(owner, name, now()).run()
  // A brand-new workspace gets sample data so the product is furnished on first open.
  await seedWorkspace(db, owner)
  return { name, seeded_at: now() }
}

workspace.get('/me', async (c) => {
  const user = c.get('user')
  const db = c.get('db')
  const ws = await ensureWorkspace(db, user.sub, `${user.name?.split(' ')[0] ?? 'Your'}'s workspace`)
  const body: Me = {
    user: { sub: user.sub, name: user.name, email: user.email, picture: user.picture },
    workspace: { name: ws.name, seededAt: ws.seeded_at },
    capabilities: {
      database: true,
      files: Boolean(c.env.FILES),
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

workspace.post('/workspace/reset', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  await clearWorkspace(db, owner)
  await seedWorkspace(db, owner)
  return privateJson(c, { ok: true })
})

workspace.delete('/workspace/data', async (c) => {
  await clearWorkspace(c.get('db'), c.get('user').sub)
  return privateJson(c, { ok: true })
})

workspace.get('/overview', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const t = now()
  const startOfMonth = new Date(t)
  startOfMonth.setDate(1)
  startOfMonth.setHours(0, 0, 0, 0)
  const startOfLast = new Date(startOfMonth)
  startOfLast.setMonth(startOfLast.getMonth() - 1)
  const month = startOfMonth.toISOString().slice(0, 10)
  const lastMonth = startOfLast.toISOString().slice(0, 10)
  const sixMonths = new Date(startOfMonth)
  sixMonths.setMonth(sixMonths.getMonth() - 5)

  const [pipeline, wonThis, wonLast, openDeals, newContacts, tasksDue, stages, revenue, activity, tasks] = await db.batch([
    db.prepare(`SELECT COALESCE(SUM(value),0) AS v FROM deals WHERE owner_sub = ? AND stage NOT IN ('won','lost')`).bind(owner),
    db.prepare(`SELECT COALESCE(SUM(value),0) AS v FROM deals WHERE owner_sub = ? AND stage = 'won' AND close_date >= ?`).bind(owner, month),
    db.prepare(`SELECT COALESCE(SUM(value),0) AS v FROM deals WHERE owner_sub = ? AND stage = 'won' AND close_date >= ? AND close_date < ?`).bind(owner, lastMonth, month),
    db.prepare(`SELECT COUNT(*) AS n FROM deals WHERE owner_sub = ? AND stage NOT IN ('won','lost')`).bind(owner),
    db.prepare(`SELECT COUNT(*) AS n FROM contacts WHERE owner_sub = ? AND created_at >= ?`).bind(owner, t - 30 * 86_400_000),
    db.prepare(`SELECT COUNT(*) AS n FROM tasks WHERE owner_sub = ? AND done_at IS NULL AND due_at IS NOT NULL AND due_at <= ?`).bind(owner, t + 86_400_000),
    db.prepare(`SELECT stage, COUNT(*) AS n, COALESCE(SUM(value),0) AS v FROM deals WHERE owner_sub = ? GROUP BY stage`).bind(owner),
    db
      .prepare(
        `SELECT substr(close_date, 1, 7) AS ym, COALESCE(SUM(value),0) AS v FROM deals
         WHERE owner_sub = ? AND stage = 'won' AND close_date >= ? GROUP BY ym ORDER BY ym`,
      )
      .bind(owner, sixMonths.toISOString().slice(0, 10)),
    db.prepare(`${ACTIVITY_SELECT} WHERE a.owner_sub = ? ORDER BY a.created_at DESC LIMIT 8`).bind(owner),
    db.prepare(`${TASK_SELECT} WHERE t.owner_sub = ? AND t.done_at IS NULL ORDER BY t.due_at IS NULL, t.due_at ASC LIMIT 6`).bind(owner),
  ])

  const months: { label: string; value: number }[] = []
  const byMonth = new Map((revenue.results as { ym: string; v: number }[]).map((r) => [r.ym, Number(r.v)]))
  for (let i = 0; i < 6; i++) {
    const d = new Date(sixMonths)
    d.setMonth(d.getMonth() + i)
    const key = d.toISOString().slice(0, 7)
    months.push({ label: d.toLocaleString('en', { month: 'short' }), value: byMonth.get(key) ?? 0 })
  }

  const stageRows = stages.results as { stage: DealStage; n: number; v: number }[]
  const body: Overview = {
    kpis: {
      pipelineValue: Number((pipeline.results[0] as { v: number }).v),
      wonThisMonth: Number((wonThis.results[0] as { v: number }).v),
      wonLastMonth: Number((wonLast.results[0] as { v: number }).v),
      openDeals: Number((openDeals.results[0] as { n: number }).n),
      newContacts: Number((newContacts.results[0] as { n: number }).n),
      tasksDue: Number((tasksDue.results[0] as { n: number }).n),
    },
    revenueSeries: months,
    stageTotals: (['lead', 'qualified', 'proposal', 'negotiation', 'won', 'lost'] as DealStage[]).map((stage) => {
      const row = stageRows.find((r) => r.stage === stage)
      return { stage, count: Number(row?.n ?? 0), value: Number(row?.v ?? 0) }
    }),
    recentActivity: (activity.results as Record<string, unknown>[]).map(mapActivity),
    upcomingTasks: (tasks.results as Record<string, unknown>[]).map(mapTask),
  }
  return privateJson(c, body)
})

workspace.get('/search', async (c) => {
  const q = (c.req.query('q') ?? '').trim()
  if (q.length < 1) return privateJson(c, { contacts: [], companies: [], deals: [] })
  const db = c.get('db')
  const owner = c.get('user').sub
  const like = `%${q.replace(/[%_]/g, '')}%`
  const [contacts, companies, deals] = await db.batch([
    db
      .prepare(
        `SELECT id, first_name, last_name, email, hue FROM contacts WHERE owner_sub = ? AND (first_name || ' ' || last_name LIKE ? OR email LIKE ?) ORDER BY last_activity_at DESC LIMIT 5`,
      )
      .bind(owner, like, like),
    db.prepare(`SELECT id, name, domain, hue FROM companies WHERE owner_sub = ? AND name LIKE ? ORDER BY name LIMIT 5`).bind(owner, like),
    db.prepare(`SELECT id, title, stage, value FROM deals WHERE owner_sub = ? AND title LIKE ? ORDER BY updated_at DESC LIMIT 5`).bind(owner, like),
  ])
  return privateJson(c, {
    contacts: (contacts.results as Record<string, unknown>[]).map((r) => ({
      id: r.id,
      name: `${r.first_name} ${r.last_name}`.trim(),
      email: r.email,
      hue: r.hue,
    })),
    companies: companies.results,
    deals: deals.results,
  })
})
