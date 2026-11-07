// Types shared by the Worker (src/worker) and the app (src/app).

export type ContactStatus = 'lead' | 'active' | 'customer' | 'churned'
export const CONTACT_STATUSES: ContactStatus[] = ['lead', 'active', 'customer', 'churned']

export type DealStage = 'lead' | 'qualified' | 'proposal' | 'negotiation' | 'won' | 'lost'
export const DEAL_STAGES: { key: DealStage; label: string }[] = [
  { key: 'lead', label: 'Lead' },
  { key: 'qualified', label: 'Qualified' },
  { key: 'proposal', label: 'Proposal' },
  { key: 'negotiation', label: 'Negotiation' },
  { key: 'won', label: 'Won' },
  { key: 'lost', label: 'Lost' },
]

export type ActivityKind = 'note' | 'call' | 'email' | 'meeting' | 'stage' | 'file' | 'created'

export interface Company {
  id: string
  name: string
  domain: string | null
  industry: string | null
  size: string | null
  location: string | null
  hue: number
  createdAt: number
  updatedAt: number
  contactCount?: number
  dealCount?: number
  openValue?: number
}

export interface Contact {
  id: string
  companyId: string | null
  companyName?: string | null
  firstName: string
  lastName: string
  email: string | null
  phone: string | null
  title: string | null
  status: ContactStatus
  avatarKey: string | null
  hue: number
  lastActivityAt: number
  createdAt: number
  updatedAt: number
}

export interface Deal {
  id: string
  title: string
  companyId: string | null
  companyName?: string | null
  contactId: string | null
  contactName?: string | null
  contactHue?: number | null
  value: number
  stage: DealStage
  position: number
  closeDate: string | null
  createdAt: number
  updatedAt: number
}

export interface Activity {
  id: string
  kind: ActivityKind
  body: string
  contactId: string | null
  dealId: string | null
  companyId: string | null
  contactName?: string | null
  dealTitle?: string | null
  createdAt: number
}

export interface Task {
  id: string
  title: string
  dueAt: number | null
  doneAt: number | null
  contactId: string | null
  dealId: string | null
  contactName?: string | null
  dealTitle?: string | null
  createdAt: number
}

export interface StoredFile {
  id: string
  name: string
  size: number
  mime: string
  contactId: string | null
  dealId: string | null
  companyId: string | null
  createdAt: number
}

export interface BotConstants {
  clipSharesDefault: number
  clipSharesFraction: number
  maxShares: number
  meanTradesPerWindow: number
  medianTradesPerWindow: number
  bothSidesRate: number
  numWindows24h: number
  buyOnly: boolean
  holdToRedeem: boolean
}

export interface BotStatus {
  constants: BotConstants
  windows: number
  trades: number
  paperGate: string
}

export interface Me {
  user: { sub: string; name?: string; email?: string; picture?: string }
  workspace: { name: string; seededAt: number | null }
  capabilities: { database: boolean; files: boolean; auth: 'freebuff' | 'development' }
}

export interface Overview {
  kpis: {
    pipelineValue: number
    wonThisMonth: number
    wonLastMonth: number
    openDeals: number
    newContacts: number
    tasksDue: number
  }
  revenueSeries: { label: string; value: number }[]
  stageTotals: { stage: DealStage; count: number; value: number }[]
  recentActivity: Activity[]
  upcomingTasks: Task[]
}
