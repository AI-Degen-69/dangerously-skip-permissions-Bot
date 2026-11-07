import { Hono } from 'hono'

import { privateJson } from '../auth'
import { id, mapFile, now } from '../db'
import type { AppContext } from '../env'

// Files live in R2 under <owner>/<random>; the row in D1 is the only way to
// reach a key, and every read checks the row's owner first.
export const files = new Hono<AppContext>()

const MAX_BYTES = 10 * 1024 * 1024
const IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif'])

function requireBucket(bucket: R2Bucket | undefined) {
  if (!bucket) {
    throw Object.assign(new Error('No file storage is attached yet. Add R2 storage named FILES and redeploy.'), { status: 503 })
  }
  return bucket
}

files.onError((error, c) => {
  const status = (error as { status?: number }).status
  if (status === 503) return c.json({ error: 'storage_missing', message: error.message }, 503)
  console.error(error)
  return c.json({ error: 'Something went wrong.' }, 500)
})

files.post('/', async (c) => {
  const bucket = requireBucket(c.env.FILES)
  const db = c.get('db')
  const owner = c.get('user').sub
  const form = await c.req.formData()
  const file = form.get('file')
  if (!(file instanceof File)) return c.json({ error: 'Choose a file.' }, 400)
  if (file.size > MAX_BYTES) return c.json({ error: 'Files are limited to 10 MB.' }, 400)
  const contactId = String(form.get('contactId') ?? '') || null
  const dealId = String(form.get('dealId') ?? '') || null
  const companyId = String(form.get('companyId') ?? '') || null
  if (!contactId && !dealId && !companyId) return c.json({ error: 'Attach the file to a contact, deal or company.' }, 400)

  const fileId = id()
  const key = `${owner}/${fileId}`
  await bucket.put(key, file.stream(), { httpMetadata: { contentType: file.type || 'application/octet-stream' } })
  const t = now()
  await db.batch([
    db
      .prepare(`INSERT INTO files (id, owner_sub, key, name, size, mime, contact_id, deal_id, company_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
      .bind(fileId, owner, key, file.name.slice(0, 200), file.size, file.type || 'application/octet-stream', contactId, dealId, companyId, t),
    db
      .prepare(`INSERT INTO activities (id, owner_sub, kind, body, contact_id, deal_id, company_id, created_at) VALUES (?, ?, 'file', ?, ?, ?, ?, ?)`)
      .bind(id(), owner, `Attached ${file.name.slice(0, 200)}`, contactId, dealId, companyId, t),
  ])
  const row = await db.prepare(`SELECT * FROM files WHERE owner_sub = ? AND id = ?`).bind(owner, fileId).first()
  return privateJson(c, { file: mapFile(row as Record<string, unknown>) }, 201)
})

files.get('/:id', async (c) => {
  const bucket = requireBucket(c.env.FILES)
  const owner = c.get('user').sub
  const row = await c.get('db').prepare(`SELECT key, name, mime FROM files WHERE owner_sub = ? AND id = ?`).bind(owner, c.req.param('id')).first<{ key: string; name: string; mime: string }>()
  if (!row) return c.json({ error: 'Not found.' }, 404)
  const object = await bucket.get(row.key)
  if (!object) return c.json({ error: 'Not found.' }, 404)
  const disposition = c.req.query('download') !== undefined ? 'attachment' : 'inline'
  return new Response(object.body, {
    headers: {
      'Content-Type': row.mime,
      'Content-Length': String(object.size),
      'Content-Disposition': `${disposition}; filename*=UTF-8''${encodeURIComponent(row.name)}`,
      'Cache-Control': 'private, no-store',
      'X-Content-Type-Options': 'nosniff',
    },
  })
})

files.delete('/:id', async (c) => {
  const bucket = requireBucket(c.env.FILES)
  const db = c.get('db')
  const owner = c.get('user').sub
  const row = await db.prepare(`SELECT key FROM files WHERE owner_sub = ? AND id = ?`).bind(owner, c.req.param('id')).first<{ key: string }>()
  if (!row) return c.json({ error: 'Not found.' }, 404)
  await db.prepare(`DELETE FROM files WHERE owner_sub = ? AND id = ?`).bind(owner, c.req.param('id')).run()
  await bucket.delete(row.key)
  return privateJson(c, { ok: true })
})

// Contact avatars: one image per contact, replaced on upload.
files.put('/avatar/:contactId', async (c) => {
  const bucket = requireBucket(c.env.FILES)
  const db = c.get('db')
  const owner = c.get('user').sub
  const contactId = c.req.param('contactId')
  const contact = await db.prepare(`SELECT avatar_key FROM contacts WHERE owner_sub = ? AND id = ?`).bind(owner, contactId).first<{ avatar_key: string | null }>()
  if (!contact) return c.json({ error: 'Not found.' }, 404)
  const form = await c.req.formData()
  const file = form.get('file')
  if (!(file instanceof File) || !IMAGE_TYPES.has(file.type)) return c.json({ error: 'Choose a PNG, JPEG, WebP or GIF image.' }, 400)
  if (file.size > 4 * 1024 * 1024) return c.json({ error: 'Images are limited to 4 MB.' }, 400)
  const key = `${owner}/avatars/${contactId}/${crypto.randomUUID()}`
  await bucket.put(key, file.stream(), { httpMetadata: { contentType: file.type } })
  await db.prepare(`UPDATE contacts SET avatar_key = ?, updated_at = ? WHERE owner_sub = ? AND id = ?`).bind(key, now(), owner, contactId).run()
  if (contact.avatar_key) await bucket.delete(contact.avatar_key)
  return privateJson(c, { avatarKey: key })
})

files.get('/avatar/:contactId', async (c) => {
  const bucket = requireBucket(c.env.FILES)
  const owner = c.get('user').sub
  const contact = await c.get('db').prepare(`SELECT avatar_key FROM contacts WHERE owner_sub = ? AND id = ?`).bind(owner, c.req.param('contactId')).first<{ avatar_key: string | null }>()
  if (!contact?.avatar_key) return c.json({ error: 'Not found.' }, 404)
  const object = await bucket.get(contact.avatar_key)
  if (!object) return c.json({ error: 'Not found.' }, 404)
  return new Response(object.body, {
    headers: {
      'Content-Type': object.httpMetadata?.contentType ?? 'image/jpeg',
      'Cache-Control': 'private, max-age=300',
      'X-Content-Type-Options': 'nosniff',
    },
  })
})
