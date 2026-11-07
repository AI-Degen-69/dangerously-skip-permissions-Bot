import { Hono } from 'hono'

import { privateJson } from '../auth'
import { ACTIVITY_SELECT, DEAL_SELECT, id, mapActivity, mapDeal, mapFile, now } from '../db'
import type { AppContext } from '../env'
import { DEAL_STAGES } from '../../shared/types'

export const deals = new Hono<AppContext>()

const stageLabel = (stage: string) => DEAL_STAGES.find((s) => s.key === stage)?.label ?? stage
const isStage = (stage: unknown): stage is string => DEAL_STAGES.some((s) => s.key === stage)

deals.get('/', async (c) => {
  const rows = await c
    .get('db')
    .prepare(`${DEAL_SELECT} WHERE d.owner_sub = ? ORDER BY d.stage, d.position ASC, d.updated_at DESC LIMIT 500`)
    .bind(c.get('user').sub)
    .all()
  return privateJson(c, { items: (rows.results as Record<string, unknown>[]).map(mapDeal) })
})

deals.get('/:id', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const dealId = c.req.param('id')
  const [row, activities, files] = await db.batch([
    db.prepare(`${DEAL_SELECT} WHERE d.owner_sub = ? AND d.id = ?`).bind(owner, dealId),
    db.prepare(`${ACTIVITY_SELECT} WHERE a.owner_sub = ? AND a.deal_id = ? ORDER BY a.created_at DESC LIMIT 50`).bind(owner, dealId),
    db.prepare(`SELECT * FROM files WHERE owner_sub = ? AND deal_id = ? ORDER BY created_at DESC`).bind(owner, dealId),
  ])
  const deal = row.results[0]
  if (!deal) return c.json({ error: 'Not found.' }, 404)
  return privateJson(c, {
    deal: mapDeal(deal as Record<string, unknown>),
    activities: (activities.results as Record<string, unknown>[]).map(mapActivity),
    files: (files.results as Record<string, unknown>[]).map(mapFile),
  })
})

type DealInput = {
  title?: string
  companyId?: string | null
  contactId?: string | null
  value?: number
  stage?: string
  position?: number
  closeDate?: string | null
}

deals.post('/', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const input = await c.req.json<DealInput>()
  const title = input.title?.trim().slice(0, 120)
  if (!title) return c.json({ error: 'Title is required.' }, 400)
  const stage = isStage(input.stage) ? input.stage : 'lead'
  const dealId = id()
  const t = now()
  const top = await db.prepare(`SELECT MIN(position) AS p FROM deals WHERE owner_sub = ? AND stage = ?`).bind(owner, stage).first<{ p: number | null }>()
  await db.batch([
    db
      .prepare(
        `INSERT INTO deals (id, owner_sub, title, company_id, contact_id, value, stage, position, close_date, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .bind(
        dealId,
        owner,
        title,
        input.companyId || null,
        input.contactId || null,
        Math.max(0, Math.round(Number(input.value) || 0)),
        stage,
        (top?.p ?? 1) - 1,
        input.closeDate || null,
        t,
        t,
      ),
    db
      .prepare(`INSERT INTO activities (id, owner_sub, kind, body, contact_id, deal_id, company_id, created_at) VALUES (?, ?, 'created', ?, ?, ?, ?, ?)`)
      .bind(id(), owner, `Deal created in ${stageLabel(stage)}`, input.contactId || null, dealId, input.companyId || null, t),
  ])
  const row = await db.prepare(`${DEAL_SELECT} WHERE d.owner_sub = ? AND d.id = ?`).bind(owner, dealId).first()
  return privateJson(c, { deal: mapDeal(row as Record<string, unknown>) }, 201)
})

deals.patch('/:id', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const dealId = c.req.param('id')
  const input = await c.req.json<DealInput>()
  const existing = await db.prepare(`SELECT * FROM deals WHERE owner_sub = ? AND id = ?`).bind(owner, dealId).first<Record<string, unknown>>()
  if (!existing) return c.json({ error: 'Not found.' }, 404)
  const title = (input.title ?? (existing.title as string)).trim().slice(0, 120)
  if (!title) return c.json({ error: 'Title is required.' }, 400)
  const stage = isStage(input.stage) ? input.stage : (existing.stage as string)
  const t = now()
  const statements = [
    db
      .prepare(
        `UPDATE deals SET title = ?, company_id = ?, contact_id = ?, value = ?, stage = ?, position = ?, close_date = ?, updated_at = ?
         WHERE owner_sub = ? AND id = ?`,
      )
      .bind(
        title,
        input.companyId === undefined ? (existing.company_id as string | null) : input.companyId || null,
        input.contactId === undefined ? (existing.contact_id as string | null) : input.contactId || null,
        input.value === undefined ? Number(existing.value) : Math.max(0, Math.round(Number(input.value) || 0)),
        stage,
        input.position === undefined ? Number(existing.position) : Number(input.position),
        input.closeDate === undefined ? (existing.close_date as string | null) : input.closeDate || null,
        t,
        owner,
        dealId,
      ),
  ]
  if (stage !== existing.stage) {
    statements.push(
      db
        .prepare(`INSERT INTO activities (id, owner_sub, kind, body, contact_id, deal_id, company_id, created_at) VALUES (?, ?, 'stage', ?, ?, ?, ?, ?)`)
        .bind(
          id(),
          owner,
          `Moved from ${stageLabel(existing.stage as string)} to ${stageLabel(stage)}`,
          (existing.contact_id as string | null) ?? null,
          dealId,
          (existing.company_id as string | null) ?? null,
          t,
        ),
    )
  }
  await db.batch(statements)
  const row = await db.prepare(`${DEAL_SELECT} WHERE d.owner_sub = ? AND d.id = ?`).bind(owner, dealId).first()
  return privateJson(c, { deal: mapDeal(row as Record<string, unknown>) })
})

deals.delete('/:id', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const dealId = c.req.param('id')
  const keys = await db.prepare(`SELECT key FROM files WHERE owner_sub = ? AND deal_id = ?`).bind(owner, dealId).all<{ key: string }>()
  await db.batch([
    db.prepare(`DELETE FROM files WHERE owner_sub = ? AND deal_id = ?`).bind(owner, dealId),
    db.prepare(`DELETE FROM activities WHERE owner_sub = ? AND deal_id = ?`).bind(owner, dealId),
    db.prepare(`UPDATE tasks SET deal_id = NULL WHERE owner_sub = ? AND deal_id = ?`).bind(owner, dealId),
    db.prepare(`DELETE FROM deals WHERE owner_sub = ? AND id = ?`).bind(owner, dealId),
  ])
  if (c.env.FILES && keys.results.length) await c.env.FILES.delete(keys.results.map((r) => r.key))
  return privateJson(c, { ok: true })
})
