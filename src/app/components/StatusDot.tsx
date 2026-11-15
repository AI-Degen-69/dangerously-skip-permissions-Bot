import { cn } from '@/lib/utils'

export type StatusDotTone = 'live' | 'stopped' | 'warning' | 'danger'

const PING_COLORS: Record<StatusDotTone, string> = {
  live: 'bg-emerald-400',
  stopped: 'bg-muted-foreground/40',
  warning: 'bg-amber-400',
  danger: 'bg-rose-400',
}

const CORE_COLORS: Record<StatusDotTone, string> = {
  live: 'bg-emerald-500',
  stopped: 'bg-muted-foreground/50',
  warning: 'bg-amber-500',
  danger: 'bg-rose-500',
}

/**
 * Compact status indicator dot.
 * Renders a blinking ping halo when `tone === 'live'` (or `blink` is true)
 * and a crisp static dot for stopped/idle/warning states.
 */
export function StatusDot({
  tone = 'stopped',
  blink,
  size = 'sm',
  className,
  label,
}: {
  tone?: StatusDotTone
  blink?: boolean
  size?: 'xs' | 'sm' | 'md'
  className?: string
  label?: string
}) {
  const shouldBlink = blink ?? tone === 'live'
  const sizeClass =
    size === 'xs' ? 'size-1.5' : size === 'md' ? 'size-2.5' : 'size-2'

  return (
    <span
      className={cn(
        'relative inline-flex shrink-0 items-center justify-center',
        sizeClass,
        className,
      )}
      role={label ? 'status' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {shouldBlink && (
        <span
          className={cn(
            'absolute inline-flex size-full animate-ping rounded-full opacity-75',
            PING_COLORS[tone],
          )}
        />
      )}
      <span
        className={cn(
          'relative inline-flex size-full rounded-full',
          CORE_COLORS[tone],
        )}
      />
    </span>
  )
}
