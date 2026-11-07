import { Hono } from 'hono'

import { privateJson } from '../auth'
import { ACTIVITY_SELECT, id, mapActivity, now } from '../db'
import type { AppContext } from '../env'

export const activities = new Hono<AppContext>()

const KINDS = new Set(['note', 'call', 'email', 'meeting'])

activities.post('/', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const input = await c.req.json<{ kind?: string; body?: string; contactId?: string | null; dealId?: string | null }>()
  const body = input.body?.trim().slice(0, 2000)
  if (!body) return c.json({ error: 'Write something first.' }, 400)
  const kind = KINDS.has(input.kind ?? '') ? (input.kind as string) : 'note'
  const t = now()
  const activityId = id()
  let companyId: string | null = null
  if (input.contactId) {
    const contact = await db.prepare(`SELECT company_id FROM contacts WHERE owner_sub = ? AND id = ?`).bind(owner, input.contactId).first<{ company_id: string | null }>()
    if (!contact) return c.json({ error: 'Not found.' }, 404)
    companyId = contact.company_id
  } else if (input.dealId) {
    const deal = await db.prepare(`SELECT company_id FROM deals WHERE owner_sub = ? AND id = ?`).bind(owner, input.dealId).first<{ company_id: string | null }>()
    if (!deal) return c.json({ error: 'Not found.' }, 404)
    companyId = deal.company_id
  }
  const statements = [
    db
      .prepare(`INSERT INTO activities (id, owner_sub, kind, body, contact_id, deal_id, company_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`)
      .bind(activityId, owner, kind, body, input.contactId || null, input.dealId || null, companyId, t),
  ]
  if (input.contactId) statements.push(db.prepare(`UPDATE contacts SET last_activity_at = ? WHERE owner_sub = ? AND id = ?`).bind(t, owner, input.contactId))
  await db.batch(statements)
  const row = await db.prepare(`${ACTIVITY_SELECT} WHERE a.owner_sub = ? AND a.id = ?`).bind(owner, activityId).first()
  return privateJson(c, { activity: mapActivity(row as Record<string, unknown>) }, 201)
})

activities.delete('/:id', async (c) => {
  await c.get('db').prepare(`DELETE FROM activities WHERE owner_sub = ? AND id = ?`).bind(c.get('user').sub, c.req.param('id')).run()
  return privateJson(c, { ok: true })
})
