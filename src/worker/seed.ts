import { hueFor, id } from './db'
import type { ContactStatus, DealStage } from '../shared/types'

const DAY = 86_400_000

const companies = [
  { name: 'Northwind Traders', domain: 'northwind.com', industry: 'Logistics', size: '200 to 500', location: 'Seattle, US' },
  { name: 'Vertex Labs', domain: 'vertexlabs.io', industry: 'Software', size: '50 to 200', location: 'Berlin, DE' },
  { name: 'Lumen Health', domain: 'lumenhealth.co', industry: 'Healthcare', size: '500 to 1000', location: 'Boston, US' },
  { name: 'Halcyon Studio', domain: 'halcyon.studio', industry: 'Design', size: '10 to 50', location: 'Lisbon, PT' },
  { name: 'Fathom Analytics', domain: 'fathom.dev', industry: 'Data', size: '50 to 200', location: 'Toronto, CA' },
  { name: 'Orbital Energy', domain: 'orbital.energy', industry: 'Energy', size: '1000+', location: 'Houston, US' },
  { name: 'Meridian Bank', domain: 'meridian.bank', industry: 'Finance', size: '1000+', location: 'London, UK' },
  { name: 'Quill Press', domain: 'quillpress.com', industry: 'Media', size: '10 to 50', location: 'Melbourne, AU' },
]

const people: Array<[string, string, string, number, ContactStatus]> = [
  ['Maya', 'Chen', 'Head of Operations', 0, 'customer'],
  ['Tom', 'Reyes', 'Procurement Lead', 0, 'active'],
  ['Daniel', 'Okafor', 'Engineering Manager', 1, 'customer'],
  ['Lena', 'Fischer', 'CTO', 1, 'active'],
  ['Sofia', 'Marin', 'Product Lead', 2, 'lead'],
  ['Arjun', 'Patel', 'Director of IT', 2, 'active'],
  ['Grace', 'Whitfield', 'Clinical Programs', 2, 'churned'],
  ['Jonas', 'Weber', 'Founder', 3, 'customer'],
  ['Inês', 'Carvalho', 'Studio Manager', 3, 'lead'],
  ['Priya', 'Natarajan', 'VP Engineering', 4, 'active'],
  ['Marcus', 'Hall', 'Data Platform Lead', 4, 'lead'],
  ['Lucas', 'Ferreira', 'COO', 5, 'active'],
  ['Hannah', 'Brooks', 'Sustainability Lead', 5, 'lead'],
  ['Omar', 'Haddad', 'Field Operations', 5, 'customer'],
  ['Charlotte', 'Ng', 'Head of Digital', 6, 'active'],
  ['Felix', 'Lindqvist', 'Risk and Compliance', 6, 'lead'],
  ['Amara', 'Osei', 'Innovation Lab', 6, 'churned'],
  ['Eli', 'Thompson', 'Editor in Chief', 7, 'customer'],
  ['Nora', 'Kaur', 'Growth Marketing', 7, 'active'],
  ['Sam', 'Delgado', 'Independent Consultant', -1, 'lead'],
  ['Yuki', 'Tanaka', 'Advisor', -1, 'active'],
  ['Ravi', 'Menon', 'Partnerships', 1, 'lead'],
]

const dealSeeds: Array<[string, number, number, DealStage, number, number]> = [
  // title, company index, contact index, stage, value, close offset days
  ['Fleet tracking rollout', 0, 0, 'negotiation', 48000, 12],
  ['Warehouse analytics pilot', 0, 1, 'proposal', 18500, 24],
  ['Platform licence renewal', 1, 2, 'won', 36000, -6],
  ['Developer seats expansion', 1, 3, 'qualified', 22000, 40],
  ['Patient portal integration', 2, 5, 'proposal', 64000, 30],
  ['Compliance reporting suite', 2, 4, 'lead', 27500, 55],
  ['Brand system subscription', 3, 7, 'won', 9600, -14],
  ['Studio onboarding', 3, 8, 'lead', 4800, 35],
  ['Data pipeline migration', 4, 9, 'negotiation', 52000, 9],
  ['Dashboard add-on', 4, 10, 'qualified', 12000, 28],
  ['Site operations platform', 5, 11, 'proposal', 120000, 45],
  ['Sustainability reporting', 5, 12, 'lead', 38000, 70],
  ['Digital banking workspace', 6, 14, 'negotiation', 95000, 18],
  ['Newsroom collaboration', 7, 17, 'won', 15500, -2],
  ['Audience analytics', 7, 18, 'lost', 11000, -20],
  ['Advisory retainer', -1, 20, 'qualified', 6000, 21],
]

const noteBodies = [
  'Walked through the proposal. They want a pilot with two teams before committing.',
  'Intro call went well. Main concern is migration effort from their current tool.',
  'Sent the updated quote with annual billing. Waiting on procurement.',
  'Demoed the reporting module. Asked about SSO and audit logs.',
  'Follow-up scheduled for next week with their engineering lead.',
  'Legal returned redlines on the MSA. Two minor changes.',
  'Champion is moving to a new role. Need a second contact on the account.',
  'Renewal conversation started early. Looking to expand seats.',
  'They compared us with two alternatives and prefer our onboarding.',
  'Budget approved for Q1. Kickoff planned for the second week.',
]

const taskTitles = [
  'Send revised proposal',
  'Book technical deep-dive',
  'Share security questionnaire answers',
  'Prepare renewal summary',
  'Follow up on contract redlines',
  'Intro to customer success',
  'Confirm pilot start date',
  'Send case study from Northwind',
  'Review usage report before call',
  'Add second contact on the account',
]

export async function seedWorkspace(db: D1Database, owner: string) {
  const t = Date.now()
  const statements: D1PreparedStatement[] = []

  const companyIds = companies.map(() => id())
  companies.forEach((c, i) => {
    statements.push(
      db
        .prepare(
          `INSERT INTO companies (id, owner_sub, name, domain, industry, size, location, hue, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .bind(companyIds[i], owner, c.name, c.domain, c.industry, c.size, c.location, hueFor(c.name), t - (60 - i * 5) * DAY, t - i * DAY),
    )
  })

  const contactIds = people.map(() => id())
  people.forEach(([first, last, title, companyIndex, status], i) => {
    const domain = companyIndex >= 0 ? companies[companyIndex].domain : 'example.com'
    const email = `${first.toLowerCase().normalize('NFD').replace(/[^a-z]/g, '')}.${last.toLowerCase()}@${domain}`
    const lastActivity = t - ((i * 7) % 29) * DAY - (i % 5) * 3_600_000
    statements.push(
      db
        .prepare(
          `INSERT INTO contacts (id, owner_sub, company_id, first_name, last_name, email, phone, title, status, hue, last_activity_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .bind(
          contactIds[i],
          owner,
          companyIndex >= 0 ? companyIds[companyIndex] : null,
          first,
          last,
          email,
          `+1 (555) 01${String(i).padStart(2, '0')}-${String(2000 + i * 37).slice(-4)}`,
          title,
          status,
          hueFor(first + last),
          lastActivity,
          t - (90 - i * 3) * DAY,
          lastActivity,
        ),
    )
  })

  const dealIds = dealSeeds.map(() => id())
  dealSeeds.forEach(([title, companyIndex, contactIndex, stage, value, closeOffset], i) => {
    const closeDate = new Date(t + closeOffset * DAY).toISOString().slice(0, 10)
    statements.push(
      db
        .prepare(
          `INSERT INTO deals (id, owner_sub, title, company_id, contact_id, value, stage, position, close_date, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .bind(
          dealIds[i],
          owner,
          title,
          companyIndex >= 0 ? companyIds[companyIndex] : null,
          contactIds[contactIndex],
          value,
          stage,
          i,
          closeDate,
          t - (45 - i * 2) * DAY,
          t - (i % 6) * DAY,
        ),
    )
  })

  // Won deals across the previous months make the revenue chart meaningful.
  const historic: Array<[string, number, number, number]> = [
    ['Starter rollout', 0, 14000, 35],
    ['Reporting pack', 1, 8200, 48],
    ['Seat expansion', 2, 26000, 62],
    ['Onboarding services', 3, 5400, 75],
    ['Analytics licence', 4, 31000, 88],
    ['Field tooling', 5, 44000, 101],
    ['Advisory package', 6, 19000, 120],
    ['Content platform', 7, 12500, 134],
    ['Pilot extension', 2, 17500, 150],
    ['Integration work', 1, 9900, 166],
  ]
  historic.forEach(([title, companyIndex, value, daysAgo], i) => {
    statements.push(
      db
        .prepare(
          `INSERT INTO deals (id, owner_sub, title, company_id, contact_id, value, stage, position, close_date, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 'won', ?, ?, ?, ?)`,
        )
        .bind(
          id(),
          owner,
          title,
          companyIds[companyIndex],
          contactIds[companyIndex * 2],
          value,
          100 + i,
          new Date(t - daysAgo * DAY).toISOString().slice(0, 10),
          t - (daysAgo + 20) * DAY,
          t - daysAgo * DAY,
        ),
    )
  })

  const kinds = ['note', 'call', 'email', 'meeting'] as const
  for (let i = 0; i < 36; i++) {
    const contactIndex = (i * 5) % people.length
    const dealIndex = i % 3 === 0 ? (i * 7) % dealSeeds.length : -1
    statements.push(
      db
        .prepare(
          `INSERT INTO activities (id, owner_sub, kind, body, contact_id, deal_id, company_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .bind(
          id(),
          owner,
          kinds[i % kinds.length],
          noteBodies[i % noteBodies.length],
          contactIds[contactIndex],
          dealIndex >= 0 ? dealIds[dealIndex] : null,
          people[contactIndex][3] >= 0 ? companyIds[people[contactIndex][3]] : null,
          t - i * 0.8 * DAY - (i % 7) * 3_600_000,
        ),
    )
  }

  taskTitles.forEach((title, i) => {
    const due = i < 3 ? t + i * 3_600_000 * 4 : t + (i - 2) * DAY + 9 * 3_600_000
    statements.push(
      db
        .prepare(
          `INSERT INTO tasks (id, owner_sub, title, due_at, done_at, contact_id, deal_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .bind(
          id(),
          owner,
          title,
          due,
          i === 7 || i === 9 ? t - DAY : null,
          contactIds[(i * 3) % people.length],
          i % 2 === 0 ? dealIds[i % dealSeeds.length] : null,
          t - i * DAY,
        ),
    )
  })

  statements.push(db.prepare(`UPDATE workspaces SET seeded_at = ? WHERE owner_sub = ?`).bind(t, owner))
  // D1 batches are limited in size; chunk to stay well under the limit.
  for (let i = 0; i < statements.length; i += 40) await db.batch(statements.slice(i, i + 40))
}

export async function clearWorkspace(db: D1Database, owner: string) {
  await db.batch(
    ['activities', 'tasks', 'files', 'deals', 'contacts', 'companies'].map((table) =>
      db.prepare(`DELETE FROM ${table} WHERE owner_sub = ?`).bind(owner),
    ),
  )
  await db.prepare(`UPDATE workspaces SET seeded_at = NULL WHERE owner_sub = ?`).bind(owner).run()
}
