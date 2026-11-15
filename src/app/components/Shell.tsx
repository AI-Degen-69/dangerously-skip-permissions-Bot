import {
  Activity,
  BookOpen,
  FlaskConical,
  LayoutDashboard,
  Moon,
  Search,
  SlidersHorizontal,
  Sun,
  TrendingUp,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { Separator } from '@/components/ui/separator'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
} from '@/components/ui/sidebar'
import { cn } from '@/lib/utils'
import { useBotControl } from '../lib/bot'
import { CommandPalette } from './CommandPalette'
import { StatusDot } from './StatusDot'

const links = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/live', label: 'Live Bot', icon: Activity },
  { to: '/ab-test', label: 'A/B Testing', icon: FlaskConical },
  { to: '/config', label: 'Configuration', icon: SlidersHorizontal },
  { to: '/strategy', label: 'Strategy', icon: BookOpen },
]

function getInitialTheme(): 'dark' | 'light' {
  if (typeof window === 'undefined') return 'dark'
  const saved = localStorage.getItem('bot-theme')
  if (saved === 'dark' || saved === 'light') return saved
  return 'dark'
}

export function Shell() {
  const control = useBotControl()
  const botRunning = Boolean(control.data?.running)
  const isRealMode = control.data?.mode === 'live'
  const executionModeLabel = isRealMode ? 'Real' : 'Paper'
  const strat = control.data?.strategy
  const stratSymbol = strat?.symbol ?? 'HAPCS-v1'
  const [theme, setTheme] = useState<'dark' | 'light'>(getInitialTheme)
  const [cmdOpen, setCmdOpen] = useState(false)
  const location = useLocation()

  useEffect(() => {
    document.title = strat ? `Up/Down Desk — ${strat.symbol} ${strat.name}` : 'Up/Down Desk — Trading Bot'
  }, [strat?.id, strat?.symbol, strat?.name])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    if (theme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
    localStorage.setItem('bot-theme', theme)
  }, [theme])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        setCmdOpen((prev) => !prev)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const toggleTheme = () => setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'))

  return (
    <SidebarProvider className="h-svh overflow-hidden">
      <Sidebar variant="inset" collapsible="icon">
        <SidebarHeader>
          <div className="flex items-center gap-2.5 py-1 group-data-[collapsible=icon]:justify-center">
            <span
              className="grid size-8 shrink-0 place-items-center rounded-xl bg-primary/15 text-primary ring-1 ring-primary/30 shadow-xs"
              title={`Up/Down Desk · ${stratSymbol}`}
            >
              <TrendingUp className="size-4" />
            </span>
            <div className="min-w-0 flex-1 group-data-[collapsible=icon]:hidden">
              <p className="truncate font-heading text-[14px] leading-tight font-semibold tracking-tight text-sidebar-foreground">
                Up/Down Desk
              </p>
              <p
                className="mt-0.5 truncate font-mono text-[11px] leading-tight text-muted-foreground"
                title={strat?.name ? `${stratSymbol} · ${strat.name}` : stratSymbol}
              >
                {stratSymbol}
              </p>
            </div>
            <SidebarTrigger className="hidden shrink-0 group-data-[collapsible=icon]:hidden md:inline-flex" />
          </div>

          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                type="button"
                tooltip="Jump to… (⌘K)"
                onClick={() => setCmdOpen(true)}
                className="border border-sidebar-border bg-background/70 text-muted-foreground hover:text-sidebar-accent-foreground"
              >
                <Search />
                <span>Jump to…</span>
                <Kbd className="ml-auto group-data-[collapsible=icon]:hidden">⌘K</Kbd>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>

        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Desk</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {links.map(({ to, label, icon: Icon, end }) => {
                  const active = end
                    ? location.pathname === to
                    : location.pathname === to || location.pathname.startsWith(`${to}/`)
                  const isLiveLink = to === '/live'
                  const liveStatusLabel = `${executionModeLabel} · ${botRunning ? 'Bot running' : 'Bot stopped'}`
                  return (
                    <SidebarMenuItem key={to}>
                      <SidebarMenuButton
                        isActive={active}
                        tooltip={isLiveLink ? `${label} · ${liveStatusLabel}` : label}
                        render={<NavLink to={to} end={end} />}
                        className={isLiveLink ? 'pr-20' : undefined}
                      >
                        <Icon />
                        <span>{label}</span>
                      </SidebarMenuButton>
                      {isLiveLink && (
                        <div className="pointer-events-none absolute top-1/2 right-2 flex -translate-y-1/2 items-center gap-1.5 group-data-[collapsible=icon]:top-1 group-data-[collapsible=icon]:right-1 group-data-[collapsible=icon]:translate-y-0">
                          <Badge
                            variant="outline"
                            className={cn(
                              'h-4 px-1.5 font-mono text-[9.5px] font-semibold tracking-wider uppercase group-data-[collapsible=icon]:hidden',
                              isRealMode
                                ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                                : 'border-amber-500/35 bg-amber-500/10 text-amber-600 dark:text-amber-400',
                            )}
                          >
                            {executionModeLabel}
                          </Badge>
                          <StatusDot
                            tone={botRunning ? 'live' : 'stopped'}
                            size="sm"
                            label={liveStatusLabel}
                          />
                        </div>
                      )}
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>

        <SidebarFooter>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                type="button"
                tooltip={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
                onClick={toggleTheme}
              >
                {theme === 'dark' ? <Moon /> : <Sun />}
                <span>{theme === 'dark' ? 'Dark theme' : 'Light theme'}</span>
                <Badge
                  variant="outline"
                  className="ml-auto font-mono text-[10px] uppercase group-data-[collapsible=icon]:hidden"
                >
                  {theme}
                </Badge>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>

        <SidebarRail />
      </Sidebar>

      <SidebarInset className="min-w-0 overflow-hidden">
        <header className="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-border bg-background/95 px-3 backdrop-blur md:hidden">
          <div className="flex min-w-0 items-center gap-2">
            <SidebarTrigger />
            <Separator orientation="vertical" className="h-4" />
            <span className="truncate font-heading text-sm font-semibold">Up/Down Desk</span>
            <Badge variant="secondary" className="font-mono text-[10px] uppercase">
              {stratSymbol}
            </Badge>
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => setCmdOpen(true)}
              aria-label="Open command palette"
            >
              <Search />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={toggleTheme}
              aria-label="Toggle theme"
            >
              {theme === 'dark' ? <Moon /> : <Sun />}
            </Button>
          </div>
        </header>

        <div className="scrollbar-thin flex-1 overflow-y-auto bg-surface md:rounded-2xl md:border md:border-border">
          <Outlet />
        </div>
      </SidebarInset>

      <CommandPalette
        open={cmdOpen}
        onClose={() => setCmdOpen(false)}
        onToggleTheme={toggleTheme}
        theme={theme}
      />
    </SidebarProvider>
  )
}
