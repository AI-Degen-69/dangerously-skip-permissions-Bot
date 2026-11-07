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
    seeded_at INTEGER,
    created_at INTEGER NOT NULL
  )`,
  `CREATE TABLE IF NOT EXISTS companies (
    id TEXT PRIMARY KEY,
    owner_sub TEXT NOT NULL,
    name TEXT NOT NULL,
    domain TEXT,
    industry TEXT,
    size TEXT,
    location TEXT,
    hue INTEGER NOT NULL DEFAULT 220,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS companies_owner ON companies(owner_sub, name)`,
  `CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    owner_sub TEXT NOT NULL,
    company_id TEXT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL DEFAULT '',
    email TEXT,
    phone TEXT,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'lead',
    avatar_key TEXT,
    hue INTEGER NOT NULL DEFAULT 220,
    last_activity_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS contacts_owner ON contacts(owner_sub, last_activity_at DESC)`,
  `CREATE INDEX IF NOT EXISTS contacts_company ON contacts(owner_sub, company_id)`,
  `CREATE TABLE IF NOT EXISTS deals (
    id TEXT PRIMARY KEY,
    owner_sub TEXT NOT NULL,
    title TEXT NOT NULL,
    company_id TEXT,
    contact_id TEXT,
    value INTEGER NOT NULL DEFAULT 0,
    stage TEXT NOT NULL DEFAULT 'lead',
    position REAL NOT NULL DEFAULT 0,
    close_date TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS deals_owner ON deals(owner_sub, stage, position)`,
  `CREATE TABLE IF NOT EXISTS activities (
    id TEXT PRIMARY KEY,
    owner_sub TEXT NOT NULL,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    contact_id TEXT,
    deal_id TEXT,
    company_id TEXT,
    created_at INTEGER NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS activities_owner ON activities(owner_sub, created_at DESC)`,
  `CREATE INDEX IF NOT EXISTS activities_contact ON activities(owner_sub, contact_id, created_at DESC)`,
  `CREATE INDEX IF NOT EXISTS activities_deal ON activities(owner_sub, deal_id, created_at DESC)`,
  `CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    owner_sub TEXT NOT NULL,
    title TEXT NOT NULL,
    due_at INTEGER,
    done_at INTEGER,
    contact_id TEXT,
    deal_id TEXT,
    created_at INTEGER NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS tasks_owner ON tasks(owner_sub, done_at, due_at)`,
  `CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    owner_sub TEXT NOT NULL,
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    size INTEGER NOT NULL,
    mime TEXT NOT NULL,
    contact_id TEXT,
    deal_id TEXT,
    company_id TEXT,
    created_at INTEGER NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS files_owner ON files(owner_sub, created_at DESC)`,
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

export function hueFor(text: string): number {
  let h = 0
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) % 360
  return h
}

type Row = Record<string, unknown>

export function mapCompany(r: Row) {
  return {
    id: r.id as string,
    name: r.name as string,
    domain: (r.domain as string | null) ?? null,
    industry: (r.industry as string | null) ?? null,
    size: (r.size as string | null) ?? null,
    location: (r.location as string | null) ?? null,
    hue: Number(r.hue ?? 220),
    createdAt: Number(r.created_at),
    updatedAt: Number(r.updated_at),
    ...(r.contact_count !== undefined ? { contactCount: Number(r.contact_count) } : {}),
    ...(r.deal_count !== undefined ? { dealCount: Number(r.deal_count) } : {}),
    ...(r.open_value !== undefined ? { openValue: Number(r.open_value ?? 0) } : {}),
  }
}

export function mapContact(r: Row) {
  return {
    id: r.id as string,
    companyId: (r.company_id as string | null) ?? null,
    companyName: (r.company_name as string | null) ?? null,
    firstName: r.first_name as string,
    lastName: (r.last_name as string) ?? '',
    email: (r.email as string | null) ?? null,
    phone: (r.phone as string | null) ?? null,
    title: (r.title as string | null) ?? null,
    status: r.status as 'lead' | 'active' | 'customer' | 'churned',
    avatarKey: (r.avatar_key as string | null) ?? null,
    hue: Number(r.hue ?? 220),
    lastActivityAt: Number(r.last_activity_at),
    createdAt: Number(r.created_at),
    updatedAt: Number(r.updated_at),
  }
}

export function mapDeal(r: Row) {
  return {
    id: r.id as string,
    title: r.title as string,
    companyId: (r.company_id as string | null) ?? null,
    companyName: (r.company_name as string | null) ?? null,
    contactId: (r.contact_id as string | null) ?? null,
    contactName: (r.contact_name as string | null) ?? null,
    contactHue: r.contact_hue === null || r.contact_hue === undefined ? null : Number(r.contact_hue),
    value: Number(r.value ?? 0),
    stage: r.stage as 'lead' | 'qualified' | 'proposal' | 'negotiation' | 'won' | 'lost',
    position: Number(r.position ?? 0),
    closeDate: (r.close_date as string | null) ?? null,
    createdAt: Number(r.created_at),
    updatedAt: Number(r.updated_at),
  }
}

export function mapActivity(r: Row) {
  return {
    id: r.id as string,
    kind: r.kind as 'note' | 'call' | 'email' | 'meeting' | 'stage' | 'file' | 'created',
    body: r.body as string,
    contactId: (r.contact_id as string | null) ?? null,
    dealId: (r.deal_id as string | null) ?? null,
    companyId: (r.company_id as string | null) ?? null,
    contactName: (r.contact_name as string | null) ?? null,
    dealTitle: (r.deal_title as string | null) ?? null,
    createdAt: Number(r.created_at),
  }
}

export function mapTask(r: Row) {
  return {
    id: r.id as string,
    title: r.title as string,
    dueAt: r.due_at === null || r.due_at === undefined ? null : Number(r.due_at),
    doneAt: r.done_at === null || r.done_at === undefined ? null : Number(r.done_at),
    contactId: (r.contact_id as string | null) ?? null,
    dealId: (r.deal_id as string | null) ?? null,
    contactName: (r.contact_name as string | null) ?? null,
    dealTitle: (r.deal_title as string | null) ?? null,
    createdAt: Number(r.created_at),
  }
}

export function mapFile(r: Row) {
  return {
    id: r.id as string,
    name: r.name as string,
    size: Number(r.size),
    mime: r.mime as string,
    contactId: (r.contact_id as string | null) ?? null,
    dealId: (r.deal_id as string | null) ?? null,
    companyId: (r.company_id as string | null) ?? null,
    createdAt: Number(r.created_at),
  }
}

export const CONTACT_SELECT = `
  SELECT c.*, co.name AS company_name
  FROM contacts c LEFT JOIN companies co ON co.id = c.company_id AND co.owner_sub = c.owner_sub`

export const DEAL_SELECT = `
  SELECT d.*, co.name AS company_name,
    CASE WHEN ct.id IS NULL THEN NULL ELSE ct.first_name || ' ' || ct.last_name END AS contact_name,
    ct.hue AS contact_hue
  FROM deals d
  LEFT JOIN companies co ON co.id = d.company_id AND co.owner_sub = d.owner_sub
  LEFT JOIN contacts ct ON ct.id = d.contact_id AND ct.owner_sub = d.owner_sub`

export const ACTIVITY_SELECT = `
  SELECT a.*,
    CASE WHEN ct.id IS NULL THEN NULL ELSE ct.first_name || ' ' || ct.last_name END AS contact_name,
    d.title AS deal_title
  FROM activities a
  LEFT JOIN contacts ct ON ct.id = a.contact_id AND ct.owner_sub = a.owner_sub
  LEFT JOIN deals d ON d.id = a.deal_id AND d.owner_sub = a.owner_sub`

export const TASK_SELECT = `
  SELECT t.*,
    CASE WHEN ct.id IS NULL THEN NULL ELSE ct.first_name || ' ' || ct.last_name END AS contact_name,
    d.title AS deal_title
  FROM tasks t
  LEFT JOIN contacts ct ON ct.id = t.contact_id AND ct.owner_sub = t.owner_sub
  LEFT JOIN deals d ON d.id = t.deal_id AND d.owner_sub = t.owner_sub`
