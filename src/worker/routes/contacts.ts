import { Hono } from 'hono'

import { privateJson } from '../auth'
import { ACTIVITY_SELECT, CONTACT_SELECT, DEAL_SELECT, hueFor, id, mapActivity, mapContact, mapDeal, mapFile, now } from '../db'
import type { AppContext } from '../env'
import { CONTACT_STATUSES } from '../../shared/types'

export const contacts = new Hono<AppContext>()

const PAGE = 25

contacts.get('/', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const q = (c.req.query('q') ?? '').trim()
  const status = c.req.query('status')
  const companyId = c.req.query('companyId')
  const sort = c.req.query('sort') === 'name' ? 'c.last_name ASC, c.first_name ASC' : 'c.last_activity_at DESC'
  const page = Math.max(0, Number(c.req.query('page') ?? 0))

  const where: string[] = ['c.owner_sub = ?']
  const binds: unknown[] = [owner]
  if (q) {
    where.push(`(c.first_name || ' ' || c.last_name LIKE ? OR c.email LIKE ? OR co.name LIKE ?)`)
    const like = `%${q.replace(/[%_]/g, '')}%`
    binds.push(like, like, like)
  }
  if (status && CONTACT_STATUSES.includes(status as never)) {
    where.push('c.status = ?')
    binds.push(status)
  }
  if (companyId) {
    where.push('c.company_id = ?')
    binds.push(companyId)
  }
  const clause = where.join(' AND ')
  const [rows, count] = await db.batch([
    db.prepare(`${CONTACT_SELECT} WHERE ${clause} ORDER BY ${sort} LIMIT ? OFFSET ?`).bind(...binds, PAGE, page * PAGE),
    db.prepare(`SELECT COUNT(*) AS n FROM contacts c LEFT JOIN companies co ON co.id = c.company_id WHERE ${clause}`).bind(...binds),
  ])
  return privateJson(c, {
    items: (rows.results as Record<string, unknown>[]).map(mapContact),
    total: Number((count.results[0] as { n: number }).n),
    page,
    pageSize: PAGE,
  })
})

contacts.get('/:id', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const contactId = c.req.param('id')
  const [row, activities, deals, files] = await db.batch([
    db.prepare(`${CONTACT_SELECT} WHERE c.owner_sub = ? AND c.id = ?`).bind(owner, contactId),
    db.prepare(`${ACTIVITY_SELECT} WHERE a.owner_sub = ? AND a.contact_id = ? ORDER BY a.created_at DESC LIMIT 50`).bind(owner, contactId),
    db.prepare(`${DEAL_SELECT} WHERE d.owner_sub = ? AND d.contact_id = ? ORDER BY d.updated_at DESC`).bind(owner, contactId),
    db.prepare(`SELECT * FROM files WHERE owner_sub = ? AND contact_id = ? ORDER BY created_at DESC`).bind(owner, contactId),
  ])
  const contact = row.results[0]
  if (!contact) return c.json({ error: 'Not found.' }, 404)
  return privateJson(c, {
    contact: mapContact(contact as Record<string, unknown>),
    activities: (activities.results as Record<string, unknown>[]).map(mapActivity),
    deals: (deals.results as Record<string, unknown>[]).map(mapDeal),
    files: (files.results as Record<string, unknown>[]).map(mapFile),
  })
})

type ContactInput = {
  firstName?: string
  lastName?: string
  email?: string | null
  phone?: string | null
  title?: string | null
  status?: string
  companyId?: string | null
}

function clean(input: ContactInput) {
  const firstName = input.firstName?.trim().slice(0, 80)
  return {
    firstName,
    lastName: input.lastName?.trim().slice(0, 80) ?? '',
    email: input.email?.trim().slice(0, 160) || null,
    phone: input.phone?.trim().slice(0, 40) || null,
    title: input.title?.trim().slice(0, 80) || null,
    status: CONTACT_STATUSES.includes(input.status as never) ? (input.status as string) : 'lead',
    companyId: input.companyId || null,
  }
}

contacts.post('/', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const body = clean(await c.req.json<ContactInput>())
  if (!body.firstName) return c.json({ error: 'First name is required.' }, 400)
  const contactId = id()
  const t = now()
  await db.batch([
    db
      .prepare(
        `INSERT INTO contacts (id, owner_sub, company_id, first_name, last_name, email, phone, title, status, hue, last_activity_at, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .bind(contactId, owner, body.companyId, body.firstName, body.lastName, body.email, body.phone, body.title, body.status, hueFor(body.firstName + body.lastName), t, t, t),
    db
      .prepare(`INSERT INTO activities (id, owner_sub, kind, body, contact_id, company_id, created_at) VALUES (?, ?, 'created', ?, ?, ?, ?)`)
      .bind(id(), owner, 'Contact created', contactId, body.companyId, t),
  ])
  const row = await db.prepare(`${CONTACT_SELECT} WHERE c.owner_sub = ? AND c.id = ?`).bind(owner, contactId).first()
  return privateJson(c, { contact: mapContact(row as Record<string, unknown>) }, 201)
})

contacts.patch('/:id', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const contactId = c.req.param('id')
  const input = await c.req.json<ContactInput>()
  const existing = await db.prepare(`SELECT * FROM contacts WHERE owner_sub = ? AND id = ?`).bind(owner, contactId).first<Record<string, unknown>>()
  if (!existing) return c.json({ error: 'Not found.' }, 404)
  const merged = clean({
    firstName: input.firstName ?? (existing.first_name as string),
    lastName: input.lastName ?? (existing.last_name as string),
    email: input.email === undefined ? (existing.email as string | null) : input.email,
    phone: input.phone === undefined ? (existing.phone as string | null) : input.phone,
    title: input.title === undefined ? (existing.title as string | null) : input.title,
    status: input.status ?? (existing.status as string),
    companyId: input.companyId === undefined ? (existing.company_id as string | null) : input.companyId,
  })
  if (!merged.firstName) return c.json({ error: 'First name is required.' }, 400)
  await db
    .prepare(
      `UPDATE contacts SET first_name = ?, last_name = ?, email = ?, phone = ?, title = ?, status = ?, company_id = ?, updated_at = ?
       WHERE owner_sub = ? AND id = ?`,
    )
    .bind(merged.firstName, merged.lastName, merged.email, merged.phone, merged.title, merged.status, merged.companyId, now(), owner, contactId)
    .run()
  const row = await db.prepare(`${CONTACT_SELECT} WHERE c.owner_sub = ? AND c.id = ?`).bind(owner, contactId).first()
  return privateJson(c, { contact: mapContact(row as Record<string, unknown>) })
})

contacts.delete('/:id', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const contactId = c.req.param('id')
  const keys = await db.prepare(`SELECT key FROM files WHERE owner_sub = ? AND contact_id = ?`).bind(owner, contactId).all<{ key: string }>()
  await db.batch([
    db.prepare(`DELETE FROM files WHERE owner_sub = ? AND contact_id = ?`).bind(owner, contactId),
    db.prepare(`DELETE FROM activities WHERE owner_sub = ? AND contact_id = ?`).bind(owner, contactId),
    db.prepare(`UPDATE tasks SET contact_id = NULL WHERE owner_sub = ? AND contact_id = ?`).bind(owner, contactId),
    db.prepare(`UPDATE deals SET contact_id = NULL WHERE owner_sub = ? AND contact_id = ?`).bind(owner, contactId),
    db.prepare(`DELETE FROM contacts WHERE owner_sub = ? AND id = ?`).bind(owner, contactId),
  ])
  if (c.env.FILES && keys.results.length) await c.env.FILES.delete(keys.results.map((r) => r.key))
  return privateJson(c, { ok: true })
})
