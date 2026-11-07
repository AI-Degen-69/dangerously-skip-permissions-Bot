import { motion } from 'motion/react'
import { ArrowRight, Database } from 'lucide-react'

import { Avatar } from '../components/ui'

// Shown when /api/me returns 401. Sign-in is a plain link to the SDK route; the
// Worker (not this page) decides who is signed in.
export function SignIn() {
  const returnTo = encodeURIComponent(`${window.location.pathname}${window.location.search}`)
  return (
    <div className="grid h-full lg:grid-cols-2">
      <div className="flex flex-col justify-between p-8 sm:p-12">
        <div className="flex items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-[10px] bg-fg text-white">
            <svg viewBox="0 0 24 24" className="size-4.5" fill="currentColor" aria-hidden>
              <circle cx="9" cy="9" r="3.2" />
              <path d="M3.5 19c.8-3.6 3.2-5.5 5.5-5.5s4.7 1.9 5.5 5.5z" />
              <circle cx="17" cy="8" r="2.2" />
              <path d="M14 14.5c.5-2 1.8-3 3-3s2.5 1 3 3z" />
            </svg>
          </span>
          <span className="text-[15px] font-semibold tracking-tight">Your Company</span>
        </div>

        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }} className="max-w-sm">
          <h1 className="text-balance text-[34px] font-semibold leading-[1.1] tracking-[-0.025em]">Every relationship, in one quiet place</h1>
          <p className="mt-3 text-[15px] leading-relaxed text-muted">Contacts, companies, deals and the notes that connect them. Sign in to open your workspace.</p>
          <a
            href={`/auth/freebuff/signin?returnTo=${returnTo}`}
            className="mt-8 inline-flex h-11 items-center gap-2 rounded-control bg-fg px-5 text-[14px] font-medium text-white transition-colors hover:bg-[#26262c]"
          >
            <span className="grid size-5 place-items-center rounded-[6px] bg-white text-[11px] font-bold text-fg">F</span>
            Sign in with Freebuff
            <ArrowRight className="size-4" />
          </a>
          <p className="mt-4 text-[12.5px] text-faint">Uses your Freebuff account. Nothing to install and no passwords to remember.</p>
        </motion.div>

        <p className="text-[12.5px] text-faint">© {new Date().getFullYear()} Your Company</p>
      </div>

      <div className="relative hidden overflow-hidden bg-bg lg:block">
        <div className="absolute inset-0 bg-[radial-gradient(60%_50%_at_70%_30%,rgb(90_85_222/0.12),transparent),radial-gradient(40%_40%_at_20%_80%,rgb(29_154_102/0.1),transparent)]" />
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
          className="absolute left-16 top-1/2 w-[640px] -translate-y-1/2 rounded-card bg-surface p-5 shadow-dialog"
        >
          <div className="flex items-center justify-between">
            <p className="text-[14px] font-semibold">Pipeline</p>
            <span className="text-[12px] text-faint">This quarter</span>
          </div>
          <div className="mt-4 grid grid-cols-3 gap-3">
            {[
              ['Open', '$438k', 'text-accent'],
              ['Won', '$61k', 'text-success'],
              ['Win rate', '34%', 'text-fg'],
            ].map(([label, value, tone]) => (
              <div key={label} className="rounded-[14px] bg-bg p-3">
                <p className="text-[12px] text-muted">{label}</p>
                <p className={`mt-1 text-[20px] font-semibold tracking-tight ${tone}`}>{value}</p>
              </div>
            ))}
          </div>
          <ul className="mt-4 divide-y divide-line">
            {[
              ['Maya Chen', 'Northwind Traders', 'Negotiation', 250],
              ['Priya Natarajan', 'Fathom Analytics', 'Proposal', 120],
              ['Charlotte Ng', 'Meridian Bank', 'Qualified', 20],
              ['Jonas Weber', 'Halcyon Studio', 'Won', 300],
            ].map(([name, company, stage, hue]) => (
              <li key={name as string} className="flex items-center gap-3 py-2.5">
                <Avatar name={name as string} hue={hue as number} size={28} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium">{name}</span>
                  <span className="block truncate text-[12px] text-faint">{company}</span>
                </span>
                <span className="rounded-[8px] bg-surface-2 px-2 py-0.5 text-[12px] text-muted">{stage}</span>
              </li>
            ))}
          </ul>
        </motion.div>
      </div>
    </div>
  )
}

export function SetupNeeded({ message }: { message: string }) {
  return (
    <div className="grid h-full place-items-center p-6">
      <div className="max-w-md text-center">
        <div className="mx-auto grid size-12 place-items-center rounded-card bg-surface-2 text-muted">
          <Database className="size-5" />
        </div>
        <h1 className="mt-4 text-[20px] font-semibold tracking-tight">Almost there</h1>
        <p className="mt-2 text-[14px] leading-relaxed text-muted">{message}</p>
        <p className="mt-4 text-[13px] text-faint">In Freebuff, ask the agent to add D1 storage named DB and R2 storage named FILES, then deploy again.</p>
      </div>
    </div>
  )
}
