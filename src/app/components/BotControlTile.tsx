import {
  ChevronDown,
  History,
  Pause,
  Play,
  RotateCcw,
  Server,
  ShieldAlert,
  SlidersHorizontal,
} from 'lucide-react'
import { useState } from 'react'

import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Separator } from '@/components/ui/separator'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'
import { STRATEGY_PRESETS } from '../botDefaults'
import {
  BOT_ORIGIN,
  mergeStrategySetups,
  useBotControl,
  useBotRuns,
  useBotSnapshot,
  useBotTape,
  useResetBot,
  useResumeBot,
  useResumeRun,
  useSelectRun,
  useSelectStrategySetup,
  useSetKillSwitch,
  useStartBot,
  useStopBot,
  useStrategySetups,
  type StrategySetup,
} from '../lib/bot'
import { money2, relativeTime } from '../lib/format'
import { reasonLabel } from '../lib/labels'
import { StatusDot, type StatusDotTone } from './StatusDot'
import { useToast } from './ui'

/** Session-picker value meaning "open a brand-new run with 0 windows". */
const NEW_SESSION = '__new__'

export interface BotHealthView {
  snapshotAgeSec: number | null
  stateSlug: string | null
  stateFills: number
  killSwitch: boolean
}

/** '⚡ DSP-v2.6' -> { icon: '⚡', label: 'DSP-v2.6' } */
function splitSymbol(symbol: string): { icon: string; label: string } {
  const space = symbol.indexOf(' ')
  return space > 0 ? { icon: symbol.slice(0, space), label: symbol.slice(space + 1) } : { icon: '', label: symbol }
}

function windowLabel(slug: string | null): string {
  if (!slug) return '—'
  const epoch = Number(slug.split('-').pop())
  if (!Number.isFinite(epoch)) return slug
  return new Date(epoch * 1000).toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Consolidated dashboard status bar + grouped Bot Control menu.
 * Exposes live liveness checks inline and houses strategy switching,
 * session picking, lifecycle actions, tape telemetry, and strategy docs
 * inside an organized menu anchored to the bot API endpoint.
 */
export function BotControlTile({ health }: { health?: BotHealthView }) {
  const control = useBotControl()
  const runsQuery = useBotRuns()
  const setupsQuery = useStrategySetups()
  const snapshot = useBotSnapshot()
  const selectSetup = useSelectStrategySetup()
  const selectRun = useSelectRun()
  const start = useStartBot()
  const resumeRun = useResumeRun()
  const stop = useStopBot()
  const tapeQuery = useBotTape()
  const reset = useResetBot()
  const killSwitch = useSetKillSwitch()
  const clearHalt = useResumeBot()
  const toast = useToast()

  const [menuOpen, setMenuOpen] = useState(false)
  const [pickedStrategyId, setPickedStrategyId] = useState<string | null>(null)
  const [pickedSession, setPickedSession] = useState<string | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)
  const [starting, setStarting] = useState(false)

  const isViewOnly = control.data?.isViewOnly ?? false
  const running = (control.data?.running ?? false) && !isViewOnly
  const activeRunId = control.data?.activeRunId ?? runsQuery.data?.activeRunId ?? null
  const selectedRunId = control.data?.selectedRunId ?? runsQuery.data?.selectedRunId ?? null
  const setups: StrategySetup[] = mergeStrategySetups(
    setupsQuery.data?.setups,
    STRATEGY_PRESETS as unknown as Record<string, StrategySetup>,
  )
  const activeStrategyId = control.data?.strategy?.id ?? setupsQuery.data?.activeSetupId ?? setups[0]?.id

  // While the loop runs, always reflect what the engine is executing.
  const strategyId = running ? activeStrategyId : (pickedStrategyId ?? activeStrategyId)
  const setup = setups.find((s) => s.id === strategyId) ?? setups[0]
  const isActiveStrategy = setup?.id === activeStrategyId

  const sessions = (runsQuery.data?.runs ?? []).filter((run) => run.configSnapshot?.strategy?.id === setup?.id)
  const defaultSession =
    sessions.find((run) => run.runId === selectedRunId)?.runId ??
    sessions.find((run) => run.runId === activeRunId)?.runId ??
    NEW_SESSION
  const session = running
    ? (activeRunId ?? NEW_SESSION)
    : pickedSession && (pickedSession === NEW_SESSION || sessions.some((run) => run.runId === pickedSession))
      ? pickedSession
      : defaultSession

  const killEngaged = snapshot.data?.snapshot?.killSwitch ?? health?.killSwitch ?? false
  const risk = snapshot.data?.snapshot?.risk
  const heartbeatMs = control.data?.snapshotAgeMs ?? snapshot.data?.ageMs ?? null
  const hbAgeSec = health?.snapshotAgeSec ?? (heartbeatMs != null ? heartbeatMs / 1000 : null)
  const busy = starting || stop.isPending
  const tape = tapeQuery.data ?? control.data?.tape ?? null
  const tapePath =
    tape?.tapeDir ?? (activeRunId ? `data/runs/${activeRunId}/tape` : 'data/runs/<run-id>/tape')

  const hbTone: StatusDotTone =
    hbAgeSec == null ? 'stopped' : hbAgeSec > 120 ? 'warning' : running ? 'live' : 'stopped'
  const hbBlink = running && hbAgeSec != null && hbAgeSec <= 120
  const hbValue =
    hbAgeSec == null
      ? 'no state'
      : hbAgeSec < 120
        ? `${Math.round(hbAgeSec)}s ago`
        : relativeTime(Date.now() - hbAgeSec * 1000)
  const hbValueClass =
    hbAgeSec == null ? 'text-muted-foreground' : hbAgeSec > 120 ? 'text-warning' : 'text-success'

  const winTone: StatusDotTone = health?.stateSlug && running ? 'live' : 'stopped'
  const winBlink = Boolean(health?.stateSlug && running)
  const winValue = health?.stateSlug
    ? `${windowLabel(health.stateSlug)} · ${health.stateFills} fills`
    : 'idle between windows'

  const pickStrategy = (id: string) => {
    setPickedStrategyId(id)
    setPickedSession(null)
    if (isViewOnly) selectRun.mutate(null)
  }

  const pickSession = (value: string) => {
    setPickedSession(value)
    // Preview the chosen session's tape on the dashboard (view-only for past runs).
    if (value !== NEW_SESSION) selectRun.mutate(value)
    else if (isViewOnly) selectRun.mutate(null)
  }

  const onStart = async () => {
    if (!setup) return
    setStarting(true)
    try {
      if (!isActiveStrategy) await selectSetup.mutateAsync(setup.id)
      const result =
        session === NEW_SESSION ? await start.mutateAsync({ newSession: true }) : await resumeRun.mutateAsync(session)
      toast(
        session === NEW_SESSION
          ? `New ${splitSymbol(setup.symbol).label} session started · ${result.runId ?? ''}`
          : `Resumed ${result.runId}`,
      )
      setPickedStrategyId(null)
      setPickedSession(null)
    } catch (error) {
      toast(error instanceof Error ? error.message : 'Failed to start bot', 'danger')
    } finally {
      setStarting(false)
    }
  }

  const onStop = () =>
    stop.mutate(undefined, {
      onSuccess: () => toast('Bot stopped'),
      onError: (error: Error) => toast(error.message, 'danger'),
    })

  const startLabel =
    session === NEW_SESSION ? 'Start new session' : session === activeRunId ? 'Start bot' : 'Resume session'

  const statusBadge = isViewOnly ? (
    <Badge
      variant="outline"
      className="border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400"
    >
      <StatusDot tone="warning" blink={false} size="xs" />
      Previewing past session
    </Badge>
  ) : (
    <Badge
      variant="outline"
      className={
        running
          ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
          : 'border-border bg-muted/60 text-muted-foreground'
      }
    >
      <StatusDot tone={running ? 'live' : 'stopped'} size="xs" />
      {running ? `Running · pid ${control.data?.pid ?? '—'}` : 'Stopped'}
    </Badge>
  )

  return (
    <>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2.5 rounded-2xl border border-border bg-card px-3.5 py-2.5">
        {/* Left: consolidated liveness indicators */}
        <div className="flex min-w-0 flex-wrap items-center gap-2.5">
          {statusBadge}
          {running && killEngaged && (
            <Badge
              variant="outline"
              className="border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400"
            >
              <StatusDot tone="warning" blink={false} size="xs" />
              Entries paused
            </Badge>
          )}
          {risk?.halted && (
            <Badge
              variant="outline"
              className="border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-400"
            >
              <StatusDot tone="danger" blink={false} size="xs" />
              Entries halted
            </Badge>
          )}

          <Separator orientation="vertical" className="hidden h-4 sm:block" />

          <div
            className="flex items-center gap-1.5 text-xs"
            title="Latest engine snapshot heartbeat age"
          >
            <StatusDot tone={hbTone} blink={hbBlink} size="xs" />
            <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
              Heartbeat
            </span>
            <span className={cn('font-medium tabular-nums', hbValueClass)}>{hbValue}</span>
          </div>

          <Separator orientation="vertical" className="hidden h-4 sm:block" />

          <div
            className="flex items-center gap-1.5 text-xs"
            title="Current 5-minute window state"
          >
            <StatusDot tone={winTone} blink={winBlink} size="xs" />
            <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
              Window
            </span>
            <span className="truncate font-medium text-foreground">{winValue}</span>
          </div>
        </div>

        {/* Right: quick lifecycle control + Bot Control Menu */}
        <div className="flex flex-wrap items-center gap-2">
          {running ? (
            <Button variant="secondary" size="sm" disabled={stop.isPending} onClick={onStop}>
              {stop.isPending ? <Spinner data-icon="inline-start" /> : <Pause data-icon="inline-start" />}
              Stop
            </Button>
          ) : (
            <Button variant="default" size="sm" disabled={busy || !setup} onClick={onStart}>
              {busy ? <Spinner data-icon="inline-start" /> : <Play data-icon="inline-start" />}
              {startLabel}
            </Button>
          )}

          <Popover open={menuOpen} onOpenChange={setMenuOpen}>
            <PopoverTrigger
              render={
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2 pr-2.5"
                  title={`Open bot control menu (${BOT_ORIGIN})`}
                />
              }
            >
              <SlidersHorizontal className="size-3.5 text-primary" />
              <span>Bot control</span>
              {setup && (
                <span className="hidden items-center gap-1.5 rounded-md bg-muted px-1.5 py-0.5 font-mono text-[11px] font-semibold text-foreground sm:inline-flex">
                  <StatusDot
                    tone={running ? 'live' : isActiveStrategy ? 'live' : 'stopped'}
                    blink={running}
                    size="xs"
                  />
                  {splitSymbol(setup.symbol).label}
                </span>
              )}
              <span className="hidden font-mono text-[11px] text-muted-foreground md:inline">
                {BOT_ORIGIN}
              </span>
              <ChevronDown
                className={cn(
                  'size-3.5 text-muted-foreground transition-transform duration-150',
                  menuOpen && 'rotate-180',
                )}
              />
            </PopoverTrigger>

            <PopoverContent
              align="end"
              sideOffset={8}
              className="w-[min(95vw,660px)] gap-0 overflow-hidden rounded-3xl border border-border bg-popover p-0 shadow-xl"
            >
              {/* Section 1: Menu Header, Status, Endpoint & Engine Controls */}
              <div className="border-b border-border bg-muted/35 px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex items-center gap-2.5">
                    <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-primary/15 text-primary">
                      <SlidersHorizontal className="size-4" />
                    </span>
                    <div className="min-w-0">
                      <h3 className="font-sans text-sm font-semibold text-foreground">Bot control</h3>
                      <p className="text-xs text-muted-foreground">
                        Pick a strategy and session, then start. The Live page only watches.
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center justify-end gap-1.5">
                    {statusBadge}
                    <Badge variant="secondary" className="gap-1 font-mono text-[10.5px]">
                      <Server className="size-3 text-muted-foreground" />
                      {BOT_ORIGIN}
                    </Badge>
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {running ? (
                    <Button variant="secondary" size="sm" disabled={stop.isPending} onClick={onStop}>
                      {stop.isPending ? <Spinner data-icon="inline-start" /> : <Pause data-icon="inline-start" />}
                      Stop bot
                    </Button>
                  ) : (
                    <Button variant="default" size="sm" disabled={busy || !setup} onClick={onStart}>
                      {busy ? <Spinner data-icon="inline-start" /> : <Play data-icon="inline-start" />}
                      {startLabel}
                    </Button>
                  )}

                  {running && (
                    <Button
                      variant={killEngaged ? 'default' : 'destructive'}
                      size="sm"
                      disabled={killSwitch.isPending}
                      onClick={() =>
                        killSwitch.mutate(!killEngaged, {
                          onSuccess: () => toast(killEngaged ? 'Entries resumed' : 'Entries paused'),
                          onError: (error: Error) => toast(error.message, 'danger'),
                        })
                      }
                    >
                      {killSwitch.isPending ? (
                        <Spinner data-icon="inline-start" />
                      ) : killEngaged ? (
                        <Play data-icon="inline-start" />
                      ) : (
                        <ShieldAlert data-icon="inline-start" />
                      )}
                      {killEngaged ? 'Resume entries' : 'Pause entries'}
                    </Button>
                  )}

                  {!isViewOnly && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setMenuOpen(false)
                        setConfirmReset(true)
                      }}
                    >
                      <RotateCcw data-icon="inline-start" />
                      Reset
                    </Button>
                  )}

                  <span className="ml-auto text-[11.5px] text-muted-foreground">
                    {running
                      ? `Trading ${activeRunId ?? 'current session'}`
                      : isViewOnly
                        ? `Previewing ${selectedRunId}`
                        : hbAgeSec != null
                          ? `Last heartbeat ${hbValue}`
                          : 'Engine idle'}
                  </span>
                </div>

                {risk?.halted && (
                  <Alert variant="destructive" className="mt-3 pr-26">
                    <ShieldAlert />
                    <AlertTitle>Entries halted for the day</AlertTitle>
                    <AlertDescription>{reasonLabel(risk.haltReason)}</AlertDescription>
                    <AlertAction>
                      <Button
                        size="xs"
                        variant="outline"
                        disabled={clearHalt.isPending}
                        onClick={() =>
                          clearHalt.mutate(undefined, {
                            onSuccess: () => toast('Risk halt cleared and entries resumed'),
                            onError: (error: Error) => toast(error.message, 'danger'),
                          })
                        }
                      >
                        {clearHalt.isPending && <Spinner data-icon="inline-start" />}
                        Clear halt
                      </Button>
                    </AlertAction>
                  </Alert>
                )}
              </div>

              {/* Section 2: Grouped Strategy Setup, Session Picker & Tape Recorder */}
              <div className="grid max-h-[min(70vh,580px)] gap-4 overflow-y-auto p-5 scrollbar-thin">
                {/* Group A: Strategy Setup Dropdown + Whole Description */}
                <div className="rounded-2xl border border-border bg-muted/20 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <label
                        htmlFor="control-strategy-select"
                        className="font-mono text-[11px] font-bold tracking-wider text-muted-foreground uppercase"
                      >
                        Strategy setup
                      </label>
                      {isActiveStrategy ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 font-mono text-[10px] font-bold text-emerald-600 uppercase dark:text-emerald-400">
                          <StatusDot tone="live" blink={running} size="xs" />
                          Active
                        </span>
                      ) : (
                        <Badge variant="outline" className="border-primary/30 bg-primary/10 text-primary">
                          Applies on Start
                        </Badge>
                      )}
                    </div>

                    <div className="w-full sm:w-auto sm:min-w-[260px]">
                      <NativeSelect
                        id="control-strategy-select"
                        size="sm"
                        value={setup?.id ?? ''}
                        disabled={running}
                        title={running ? 'Stop the bot to switch strategy' : 'Choose a strategy version'}
                        onChange={(e) => pickStrategy(e.target.value)}
                        className="w-full [&_select]:truncate [&_select]:font-mono [&_select]:text-xs [&_select]:font-semibold"
                      >
                        {setups.map((item) => {
                          const { icon, label } = splitSymbol(item.symbol)
                          return (
                            <NativeSelectOption key={item.id} value={item.id}>
                              {icon ? `${icon} ` : ''}
                              {label} — {item.name}
                              {item.id === activeStrategyId ? ' (Active)' : ''}
                            </NativeSelectOption>
                          )
                        })}
                      </NativeSelect>
                    </div>
                  </div>

                  {setup && (
                    <div className="mt-3.5 border-t border-border/70 pt-3.5">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="text-sm font-semibold text-foreground">{setup.name}</span>
                        <span className="font-mono text-[11px] text-muted-foreground">{setup.symbol}</span>
                      </div>
                      <p className="mt-1 font-mono text-xs text-muted-foreground">{setup.signature}</p>
                      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{setup.description}</p>
                      <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-6">
                        <Param label="Target pair" value={`$${Number(setup.entry.targetPairCost).toFixed(3)}`} />
                        <Param label="Pair cap" value={`$${Number(setup.entry.maxPairCost).toFixed(3)}`} />
                        <Param label="Max buy" value={`${Math.round(Number(setup.entry.maxFillPrice) * 100)}¢`} />
                        <Param label="Clip / max" value={`${setup.entry.clipSharesDefault} / ${setup.entry.maxShares} sh`} />
                        <Param label="Gap cap" value={Number(setup.entry.maxUnhedgedUsd ?? 0) > 0 ? `≤$${Number(setup.entry.maxUnhedgedUsd ?? 0).toFixed(0)}` : 'no veto'} />
                        <Param label="Cutoff" value={`${setup.entry.stopBeforeCloseSec}s`} />
                      </div>
                    </div>
                  )}
                </div>

                {/* Group B: Session Pick + Tape Section */}
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-2xl border border-border bg-muted/20 p-3.5">
                    <div className="flex items-center justify-between gap-2">
                      <label
                        htmlFor="control-session"
                        className="flex items-center gap-1.5 font-mono text-[11px] font-bold tracking-wider text-muted-foreground uppercase"
                      >
                        <History className="size-3.5" aria-hidden />
                        Session
                      </label>
                      {sessions.length > 0 && (
                        <span className="font-mono text-[10.5px] text-muted-foreground">
                          {sessions.length} saved
                        </span>
                      )}
                    </div>
                    <NativeSelect
                      id="control-session"
                      size="sm"
                      value={session}
                      disabled={running || busy}
                      onChange={(e) => pickSession(e.target.value)}
                      className="mt-2 w-full [&_select]:truncate [&_select]:font-mono [&_select]:text-xs [&_select]:font-semibold"
                    >
                      <NativeSelectOption value={NEW_SESSION}>＋ New session (from 0)</NativeSelectOption>
                      {sessions.map((run) => (
                        <NativeSelectOption key={run.runId} value={run.runId}>
                          {run.runId} ({run.windowsCount ?? 0}w · {run.isActive ? 'current' : run.status})
                        </NativeSelectOption>
                      ))}
                    </NativeSelect>
                    <p className="mt-2 text-xs leading-snug text-muted-foreground">
                      {session === NEW_SESSION
                        ? `Opens a fresh ${setup ? splitSymbol(setup.symbol).label : ''} run with 0 windows.`
                        : sessions.length > 0
                          ? `Resumes on the existing run database. ${sessions.length} past ${sessions.length === 1 ? 'run' : 'runs'} for this strategy.`
                          : ''}
                    </p>
                  </div>

                  <div className="min-w-0 overflow-hidden rounded-2xl border border-border bg-muted/20 p-3.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <Badge
                        variant="outline"
                        className="border-emerald-500/30 bg-emerald-500/10 font-mono text-[11px] text-emerald-600 dark:text-emerald-400"
                      >
                        <StatusDot tone="live" blink={running} size="xs" />
                        Tape ON
                      </Badge>
                      <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                        {(tape?.prints ?? 0).toLocaleString('en-US')}p ·{' '}
                        {(tape?.books ?? 0).toLocaleString('en-US')}b · {(tape?.mb ?? 0).toFixed(1)} MB
                      </span>
                    </div>
                    <div className="mt-2 rounded-lg border border-border/70 bg-background/60 px-2.5 py-1.5">
                      <p className="truncate font-mono text-[10.5px] text-foreground/90" title={tapePath}>
                        {tapePath}
                      </p>
                      <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                        prints.jsonl + book.jsonl · same WS connection
                      </p>
                    </div>
                    {!running && (tape?.enabled ?? false) && (
                      <p className="mt-1.5 text-[11px] leading-snug text-muted-foreground">
                        Arms on Start / Resume and audits every fill against live tape.
                      </p>
                    )}
                  </div>
                </div>
              </div>
            </PopoverContent>
          </Popover>
        </div>
      </div>

      <AlertDialog open={confirmReset} onOpenChange={setConfirmReset}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reset the paper bot?</AlertDialogTitle>
            <AlertDialogDescription>
              This wipes every paper window, fill and risk counter and restarts from the configured bankroll. It cannot
              be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={reset.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={reset.isPending}
              onClick={() =>
                reset.mutate(undefined, {
                  onSuccess: (result) => {
                    setConfirmReset(false)
                    toast(`Bot reset to ${money2(result.bankrollUsd)} — window history wiped`)
                  },
                })
              }
            >
              {reset.isPending && <Spinner data-icon="inline-start" />}
              Reset to clean state
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function Param({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-border bg-card px-2 py-1.5 text-center">
      <div className="truncate font-mono text-[9.5px] font-bold text-muted-foreground uppercase">{label}</div>
      <div className="truncate font-mono text-xs font-semibold text-foreground tabular-nums">{value}</div>
    </div>
  )
}
