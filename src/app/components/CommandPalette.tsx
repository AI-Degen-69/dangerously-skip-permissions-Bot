import { AnimatePresence, motion } from 'motion/react'
import { Activity, BookOpen, LayoutDashboard, Search, Settings, SlidersHorizontal } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

import { cx } from '../lib/cx'

type Item = { key: string; label: string; to: string; icon: React.ReactNode }

const shortcuts: Item[] = [
  { key: 's-dashboard', label: 'Go to Dashboard', to: '/', icon: <LayoutDashboard className="size-4 text-muted" /> },
  { key: 's-live', label: 'Go to Live bot', to: '/live', icon: <Activity className="size-4 text-muted" /> },
  { key: 's-config', label: 'Go to Configuration', to: '/config', icon: <SlidersHorizontal className="size-4 text-muted" /> },
  { key: 's-strategy', label: 'Go to Strategy', to: '/strategy', icon: <BookOpen className="size-4 text-muted" /> },
  { key: 's-settings', label: 'Go to Settings', to: '/settings', icon: <Settings className="size-4 text-muted" /> },
]

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const navigate = useNavigate()

  useEffect(() => {
    if (open) {
      setQ('')
      setActive(0)
    }
  }, [open])

  const list = shortcuts.filter((s) => s.label.toLowerCase().includes(q.trim().toLowerCase()))

  useEffect(() => setActive(0), [q])

  function go(item: Item) {
    onClose()
    navigate(item.to)
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center bg-fg/25 px-4 pt-[12vh] backdrop-blur-[2px]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
          <motion.div
            role="dialog"
            aria-label="Go to"
            className="w-full max-w-[560px] overflow-hidden rounded-dialog bg-surface shadow-dialog"
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="flex h-12 items-center gap-3 border-b border-line px-4">
              <Search className="size-4 text-faint" />
              <input
                autoFocus
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'ArrowDown') (e.preventDefault(), setActive((a) => Math.min(a + 1, list.length - 1)))
                  if (e.key === 'ArrowUp') (e.preventDefault(), setActive((a) => Math.max(a - 1, 0)))
                  if (e.key === 'Enter' && list[active]) go(list[active])
                  if (e.key === 'Escape') onClose()
                }}
                placeholder="Go to…"
                className="h-full flex-1 bg-transparent text-[14px] outline-none placeholder:text-faint"
              />
            </div>
            <ul className="max-h-[50vh] overflow-y-auto p-1.5">
              {list.length === 0 && <li className="px-3 py-8 text-center text-[13.5px] text-muted">Nothing matches “{q}”</li>}
              {list.map((item, i) => (
                <li key={item.key}>
                  <button
                    type="button"
                    onMouseEnter={() => setActive(i)}
                    onClick={() => go(item)}
                    className={cx('flex h-10 w-full items-center gap-3 rounded-control px-2.5 text-left', i === active && 'bg-surface-2')}
                  >
                    {item.icon}
                    <span className="min-w-0 flex-1 truncate text-[13.5px]">{item.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
