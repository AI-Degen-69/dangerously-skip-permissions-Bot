import { Hono } from 'hono'

import { privateJson } from '../auth'
import { ACTIVITY_SELECT, CONTACT_SELECT, DEAL_SELECT, hueFor, id, mapActivity, mapCompany, mapContact, mapDeal, now } from '../db'
import type { AppContext } from '../env'

export const companies = new Hono<AppContext>()

const COMPANY_SELECT = `
  SELECT co.*,
    (SELECT COUNT(*) FROM contacts c WHERE c.company_id = co.id AND c.owner_sub = co.owner_sub) AS contact_count,
    (SELECT COUNT(*) FROM deals d WHERE d.company_id = co.id AND d.owner_sub = co.owner_sub AND d.stage NOT IN ('won','lost')) AS deal_count,
    (SELECT COALESCE(SUM(value),0) FROM deals d WHERE d.company_id = co.id AND d.owner_sub = co.owner_sub AND d.stage NOT IN ('won','lost')) AS open_value
  FROM companies co`

companies.get('/', async (c) => {
  const q = (c.req.query('q') ?? '').trim()
  const owner = c.get('user').sub
  const like = `%${q.replace(/[%_]/g, '')}%`
  const rows = await c
    .get('db')
    .prepare(`${COMPANY_SELECT} WHERE co.owner_sub = ? ${q ? 'AND (co.name LIKE ? OR co.domain LIKE ? OR co.industry LIKE ?)' : ''} ORDER BY co.name ASC LIMIT 200`)
    .bind(...(q ? [owner, like, like, like] : [owner]))
    .all()
  return privateJson(c, { items: (rows.results as Record<string, unknown>[]).map(mapCompany) })
})

companies.get('/:id', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const companyId = c.req.param('id')
  const [row, people, deals, activities] = await db.batch([
    db.prepare(`${COMPANY_SELECT} WHERE co.owner_sub = ? AND co.id = ?`).bind(owner, companyId),
    db.prepare(`${CONTACT_SELECT} WHERE c.owner_sub = ? AND c.company_id = ? ORDER BY c.last_activity_at DESC`).bind(owner, companyId),
    db.prepare(`${DEAL_SELECT} WHERE d.owner_sub = ? AND d.company_id = ? ORDER BY d.updated_at DESC`).bind(owner, companyId),
    db.prepare(`${ACTIVITY_SELECT} WHERE a.owner_sub = ? AND a.company_id = ? ORDER BY a.created_at DESC LIMIT 30`).bind(owner, companyId),
  ])
  const company = row.results[0]
  if (!company) return c.json({ error: 'Not found.' }, 404)
  return privateJson(c, {
    company: mapCompany(company as Record<string, unknown>),
    contacts: (people.results as Record<string, unknown>[]).map(mapContact),
    deals: (deals.results as Record<string, unknown>[]).map(mapDeal),
    activities: (activities.results as Record<string, unknown>[]).map(mapActivity),
  })
})

type CompanyInput = { name?: string; domain?: string | null; industry?: string | null; size?: string | null; location?: string | null }

companies.post('/', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const input = await c.req.json<CompanyInput>()
  const name = input.name?.trim().slice(0, 100)
  if (!name) return c.json({ error: 'Name is required.' }, 400)
  const companyId = id()
  const t = now()
  await db
    .prepare(
      `INSERT INTO companies (id, owner_sub, name, domain, industry, size, location, hue, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .bind(
      companyId,
      owner,
      name,
      input.domain?.trim().toLowerCase().replace(/^https?:\/\//, '').slice(0, 120) || null,
      input.industry?.trim().slice(0, 60) || null,
      input.size?.trim().slice(0, 30) || null,
      input.location?.trim().slice(0, 80) || null,
      hueFor(name),
      t,
      t,
    )
    .run()
  const row = await db.prepare(`${COMPANY_SELECT} WHERE co.owner_sub = ? AND co.id = ?`).bind(owner, companyId).first()
  return privateJson(c, { company: mapCompany(row as Record<string, unknown>) }, 201)
})

companies.patch('/:id', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const companyId = c.req.param('id')
  const input = await c.req.json<CompanyInput>()
  const existing = await db.prepare(`SELECT * FROM companies WHERE owner_sub = ? AND id = ?`).bind(owner, companyId).first<Record<string, unknown>>()
  if (!existing) return c.json({ error: 'Not found.' }, 404)
  const name = (input.name ?? (existing.name as string)).trim().slice(0, 100)
  if (!name) return c.json({ error: 'Name is required.' }, 400)
  const pick = (key: 'domain' | 'industry' | 'size' | 'location') =>
    input[key] === undefined ? (existing[key] as string | null) : input[key]?.trim() || null
  await db
    .prepare(`UPDATE companies SET name = ?, domain = ?, industry = ?, size = ?, location = ?, updated_at = ? WHERE owner_sub = ? AND id = ?`)
    .bind(name, pick('domain'), pick('industry'), pick('size'), pick('location'), now(), owner, companyId)
    .run()
  const row = await db.prepare(`${COMPANY_SELECT} WHERE co.owner_sub = ? AND co.id = ?`).bind(owner, companyId).first()
  return privateJson(c, { company: mapCompany(row as Record<string, unknown>) })
})

companies.delete('/:id', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const companyId = c.req.param('id')
  await db.batch([
    db.prepare(`UPDATE contacts SET company_id = NULL WHERE owner_sub = ? AND company_id = ?`).bind(owner, companyId),
    db.prepare(`UPDATE deals SET company_id = NULL WHERE owner_sub = ? AND company_id = ?`).bind(owner, companyId),
    db.prepare(`UPDATE activities SET company_id = NULL WHERE owner_sub = ? AND company_id = ?`).bind(owner, companyId),
    db.prepare(`DELETE FROM companies WHERE owner_sub = ? AND id = ?`).bind(owner, companyId),
  ])
  return privateJson(c, { ok: true })
})
