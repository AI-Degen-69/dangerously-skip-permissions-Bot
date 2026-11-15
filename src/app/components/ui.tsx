import { createContext, useContext, type ReactNode } from 'react'

import { toast as shadcnToast } from '@/components/ui/toast'

// Toasts — bridged to the base-rhea Toast manager mounted at App root.
type ToastTone = 'neutral' | 'danger'

function pushLegacyToast(message: string, tone: ToastTone = 'neutral') {
  shadcnToast.add({
    title: message,
    type: tone === 'danger' ? 'error' : 'info',
  })
}

const ToastContext = createContext<(message: string, tone?: ToastTone) => void>(pushLegacyToast)
export const useToast = () => useContext(ToastContext)

export function ToastProvider({ children }: { children: ReactNode }) {
  return <ToastContext.Provider value={pushLegacyToast}>{children}</ToastContext.Provider>
}

export function PageHeader({
  title,
  subtitle,
  icon,
  actions,
}: {
  title: string
  subtitle?: string
  icon?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        {icon && (
          <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/25">
            {icon}
          </span>
        )}
        <div>
          <h1 className="font-heading text-xl font-semibold tracking-tight text-foreground sm:text-2xl">{title}</h1>
          {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
