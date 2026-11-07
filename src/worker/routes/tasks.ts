import { Hono } from 'hono'

import { privateJson } from '../auth'
import { TASK_SELECT, id, mapTask, now } from '../db'
import type { AppContext } from '../env'

export const tasks = new Hono<AppContext>()

tasks.get('/', async (c) => {
  const rows = await c
    .get('db')
    .prepare(`${TASK_SELECT} WHERE t.owner_sub = ? ORDER BY t.done_at IS NOT NULL, t.due_at IS NULL, t.due_at ASC, t.created_at DESC LIMIT 300`)
    .bind(c.get('user').sub)
    .all()
  return privateJson(c, { items: (rows.results as Record<string, unknown>[]).map(mapTask) })
})

type TaskInput = { title?: string; dueAt?: number | null; done?: boolean; contactId?: string | null; dealId?: string | null }

tasks.post('/', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const input = await c.req.json<TaskInput>()
  const title = input.title?.trim().slice(0, 160)
  if (!title) return c.json({ error: 'Title is required.' }, 400)
  const taskId = id()
  await db
    .prepare(`INSERT INTO tasks (id, owner_sub, title, due_at, done_at, contact_id, deal_id, created_at) VALUES (?, ?, ?, ?, NULL, ?, ?, ?)`)
    .bind(taskId, owner, title, input.dueAt ?? null, input.contactId || null, input.dealId || null, now())
    .run()
  const row = await db.prepare(`${TASK_SELECT} WHERE t.owner_sub = ? AND t.id = ?`).bind(owner, taskId).first()
  return privateJson(c, { task: mapTask(row as Record<string, unknown>) }, 201)
})

tasks.patch('/:id', async (c) => {
  const db = c.get('db')
  const owner = c.get('user').sub
  const taskId = c.req.param('id')
  const input = await c.req.json<TaskInput>()
  const existing = await db.prepare(`SELECT * FROM tasks WHERE owner_sub = ? AND id = ?`).bind(owner, taskId).first<Record<string, unknown>>()
  if (!existing) return c.json({ error: 'Not found.' }, 404)
  const title = (input.title ?? (existing.title as string)).trim().slice(0, 160)
  if (!title) return c.json({ error: 'Title is required.' }, 400)
  const doneAt = input.done === undefined ? (existing.done_at as number | null) : input.done ? now() : null
  await db
    .prepare(`UPDATE tasks SET title = ?, due_at = ?, done_at = ?, contact_id = ?, deal_id = ? WHERE owner_sub = ? AND id = ?`)
    .bind(
      title,
      input.dueAt === undefined ? (existing.due_at as number | null) : input.dueAt,
      doneAt,
      input.contactId === undefined ? (existing.contact_id as string | null) : input.contactId || null,
      input.dealId === undefined ? (existing.deal_id as string | null) : input.dealId || null,
      owner,
      taskId,
    )
    .run()
  const row = await db.prepare(`${TASK_SELECT} WHERE t.owner_sub = ? AND t.id = ?`).bind(owner, taskId).first()
  return privateJson(c, { task: mapTask(row as Record<string, unknown>) })
})

tasks.delete('/:id', async (c) => {
  await c.get('db').prepare(`DELETE FROM tasks WHERE owner_sub = ? AND id = ?`).bind(c.get('user').sub, c.req.param('id')).run()
  return privateJson(c, { ok: true })
})
