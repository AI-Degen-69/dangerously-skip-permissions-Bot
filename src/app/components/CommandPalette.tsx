import {
  Activity,
  BookOpen,
  FlaskConical,
  LayoutDashboard,
  Moon,
  SlidersHorizontal,
  Sun,
  SunMoon,
} from 'lucide-react'
import { useNavigate } from 'react-router'

import { Badge } from '@/components/ui/badge'
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from '@/components/ui/command'
import { cn } from '@/lib/utils'
import { useBotControl } from '../lib/bot'
import { StatusDot } from './StatusDot'

type NavItem = {
  key: string
  label: string
  to: string
  shortcut: string
  keywords: string[]
  icon: React.ReactNode
}

const navItems: NavItem[] = [
  {
    key: 'dashboard',
    label: 'Go to Dashboard',
    to: '/',
    shortcut: 'G D',
    keywords: ['home', 'overview', 'pnl'],
    icon: <LayoutDashboard />,
  },
  {
    key: 'live',
    label: 'Go to Live Bot',
    to: '/live',
    shortcut: 'G L',
    keywords: ['trading', 'windows', 'orders', 'fills'],
    icon: <Activity />,
  },
  {
    key: 'ab-test',
    label: 'Go to A/B Testing Lab',
    to: '/ab-test',
    shortcut: 'G A',
    keywords: ['experiment', 'comparison', 'variants'],
    icon: <FlaskConical />,
  },
  {
    key: 'config',
    label: 'Go to Configuration',
    to: '/config',
    shortcut: 'G C',
    keywords: ['parameters', 'risk', 'thresholds'],
    icon: <SlidersHorizontal />,
  },
  {
    key: 'strategy',
    label: 'Go to Strategy',
    to: '/strategy',
    shortcut: 'G R',
    keywords: ['rules', 'hapcs', 'docs'],
    icon: <BookOpen />,
  },
]

export function CommandPalette({
  open,
  onClose,
  onToggleTheme,
  theme,
}: {
  open: boolean
  onClose: () => void
  onToggleTheme?: () => void
  theme?: 'dark' | 'light'
}) {
  const navigate = useNavigate()
  const control = useBotControl()
  const botRunning = Boolean(control.data?.running)
  const isRealMode = control.data?.mode === 'live'
  const executionModeLabel = isRealMode ? 'Real' : 'Paper'

  function handleSelectRoute(to: string) {
    onClose()
    navigate(to)
  }

  function handleToggleTheme() {
    onClose()
    onToggleTheme?.()
  }

  const themeIcon = theme === 'dark' ? <Sun /> : theme === 'light' ? <Moon /> : <SunMoon />
  const themeLabel =
    theme === 'dark' ? 'Switch to light theme' : theme === 'light' ? 'Switch to dark theme' : 'Toggle color theme'

  return (
    <CommandDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose()
      }}
      title="Command Palette"
      description="Jump to a desk view or run an action."
    >
      <Command>
        <CommandInput placeholder="Jump to a page or command..." />
        <CommandList>
          <CommandEmpty>No matching pages or commands.</CommandEmpty>
          <CommandGroup heading="Navigation">
            {navItems.map((item) => (
              <CommandItem
                key={item.key}
                value={item.label}
                keywords={item.keywords}
                onSelect={() => handleSelectRoute(item.to)}
              >
                {item.icon}
                <span>{item.label}</span>
                {item.key === 'live' && (
                  <span className="inline-flex items-center gap-1.5">
                    <Badge
                      variant="outline"
                      className={cn(
                        'h-4 px-1.5 font-mono text-[9.5px] font-semibold tracking-wider uppercase',
                        isRealMode
                          ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                          : 'border-amber-500/35 bg-amber-500/10 text-amber-600 dark:text-amber-400',
                      )}
                    >
                      {executionModeLabel}
                    </Badge>
                    <StatusDot
                      tone={botRunning ? 'live' : 'stopped'}
                      size="xs"
                      label={`${executionModeLabel} · ${botRunning ? 'Bot running' : 'Bot stopped'}`}
                    />
                  </span>
                )}
                <CommandShortcut>{item.shortcut}</CommandShortcut>
              </CommandItem>
            ))}
          </CommandGroup>
          {onToggleTheme && (
            <>
              <CommandSeparator />
              <CommandGroup heading="Preferences">
                <CommandItem value={themeLabel} keywords={['theme', 'dark', 'light', 'mode']} onSelect={handleToggleTheme}>
                  {themeIcon}
                  <span>{themeLabel}</span>
                </CommandItem>
              </CommandGroup>
            </>
          )}
        </CommandList>
      </Command>
    </CommandDialog>
  )
}
