import { useState } from 'react'
import { History, Pause, Play, RotateCcw, ShieldAlert, SlidersHorizontal } from 'lucide-react'

import { Badge, Button, Card, ConfirmDialog, useToast } from './ui'
import {
  BOT_ORIGIN,
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
  mergeStrategySetups,
  type StrategySetup,
} from '../lib/bot'
import { STRATEGY_PRESETS } from '../botDefaults'
import { cx } from '../lib/cx'
import { money2, relativeTime } from '../lib/format'
import { reasonLabel } from '../lib/labels'

/** Session-picker value meaning "open a brand-new run with 0 windows". */
const NEW_SESSION = '__new__'

/** '⚡ DSP-v2.2' -> { icon: '⚡', label: 'DSP-v2.2' } */
function splitSymbol(symbol: string): { icon: string; label: string } {
  const space = symbol.indexOf(' ')
  return space > 0 ? { icon: symbol.slice(0, space), label: symbol.slice(space + 1) } : { icon: '', label: symbol }
}

/**
 * The single place the bot is driven from: pick a strategy setup, pick a
 * session (resume a past run or start fresh), then Start / Stop. The Live page
 * only observes what this tile sets in motion.
 */
export function BotControlTile() {
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

  const [pickedStrategyId, setPickedStrategyId] = useState<string | null>(null)
  const [pickedSession, setPickedSession] = useState<string | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)
  const [starting, setStarting] = useState(false)

  const isViewOnly = control.data?.isViewOnly ?? false
  const running = (control.data?.running ?? false) && !isViewOnly
  const activeRunId = control.data?.activeRunId ?? runsQuery.data?.activeRunId ?? null
  const selectedRunId = control.data?.selectedRunId ?? runsQuery.data?.selectedRunId ?? null
  const setups: StrategySetup[] = mergeStrategySetups(setupsQuery.data?.setups, STRATEGY_PRESETS as unknown as Record<string, StrategySetup>)
  const activeStrategyId = control.data?.strategy?.id ?? setupsQuery.data?.activeSetupId ?? setups[0]?.id

  // While the loop runs, the tile always shows what the engine is running.
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

  const killEngaged = snapshot.data?.snapshot?.killSwitch ?? false
  const risk = snapshot.data?.snapshot?.risk
  const heartbeatMs = control.data?.snapshotAgeMs ?? snapshot.data?.ageMs ?? null
  const busy = starting || stop.isPending

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

  return (
    <Card className="mt-4 overflow-hidden border-accent/40">
      {/* Header: what this tile is + live engine state */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface-2/40 px-4 py-3 sm:px-5">
        <div className="flex items-center gap-2.5">
          <span className="grid size-8 shrink-0 place-items-center rounded-tile bg-accent-soft text-accent">
            <SlidersHorizontal className="size-4" />
          </span>
          <div>
            <h2 className="text-[14px] font-semibold">Bot control</h2>
            <p className="text-[12px] text-muted">Pick a strategy and session, then start. The Live page only watches.</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {isViewOnly ? (
            <Badge tone="warning" dot>
              Previewing past session
            </Badge>
          ) : (
            <Badge tone={running ? 'success' : 'neutral'} dot>
              {running ? `Running · pid ${control.data?.pid ?? '—'}` : 'Stopped'}
            </Badge>
          )}
          {running && killEngaged && <Badge tone="warning">Entries paused</Badge>}
          <Badge tone="info" className="font-mono text-[10.5px]">
            {BOT_ORIGIN}
          </Badge>
        </div>
      </div>

      <div className="grid gap-4 p-4 sm:p-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        {/* Strategy setup picker + details */}
        <div className="min-w-0">
          <p className="font-mono text-[11px] font-bold uppercase tracking-wider text-muted">Strategy setup</p>
          <div
            role="radiogroup"
            aria-label="Strategy setup"
            className="mt-2 flex flex-wrap gap-1 rounded-control border border-line/60 bg-raised/70 p-1"
          >
            {setups.map((item) => {
              const { icon, label } = splitSymbol(item.symbol)
              const selected = item.id === setup?.id
              return (
                <button
                  key={item.id}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  disabled={running}
                  title={running ? 'Stop the bot to switch strategy' : item.name}
                  onClick={() => pickStrategy(item.id)}
                  className={cx(
                    'flex items-center gap-1.5 rounded-[7px] px-3 py-1.5 text-[12.5px] font-semibold transition-all disabled:cursor-not-allowed',
                    selected ? 'bg-surface text-fg shadow-card' : 'text-muted hover:bg-raised/40 hover:text-fg disabled:opacity-50',
                  )}
                >
                  {icon && <span aria-hidden>{icon}</span>}
                  <span className="font-mono">{label}</span>
                  {item.id === activeStrategyId && (
                    <span className="inline-flex items-center gap-1 rounded-pill bg-success-soft px-1.5 py-0.5 font-mono text-[9.5px] font-bold uppercase text-success">
                      <span className="size-1 rounded-full bg-success" />
                      active
                    </span>
                  )}
                </button>
              )
            })}
          </div>

          {setup && (
            <div className="mt-3 rounded-tile border border-line bg-surface-2/30 p-3.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[14px] font-semibold text-fg">{setup.name}</span>
                {isActiveStrategy ? (
                  <Badge tone="success">Active in engine</Badge>
                ) : (
                  <Badge tone="accent">Applies on Start</Badge>
                )}
              </div>
              <p className="mt-1 font-mono text-[11.5px] text-muted">{setup.signature}</p>
              <p className="mt-2 text-[12px] leading-relaxed text-muted">{setup.description}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Param label="Target pair" value={`$${Number(setup.entry.targetPairCost).toFixed(3)}`} />
                <Param label="Pair cap" value={`$${Number(setup.entry.maxPairCost).toFixed(3)}`} />
                <Param label="Max buy" value={`${Math.round(Number(setup.entry.maxFillPrice) * 100)}¢`} />
                <Param label="Clip / max" value={`${setup.entry.clipSharesDefault} / ${setup.entry.maxShares} sh`} />
                <Param label="Gap veto" value={`≥${setup.entry.maxShareLead} sh`} />
                <Param label="Cutoff" value={`${setup.entry.stopBeforeCloseSec}s`} />
              </div>
            </div>
          )}
        </div>

        {/* Session + lifecycle */}
        <div className="flex flex-col gap-3">
          <div>
            <label
              htmlFor="control-session"
              className="font-mono text-[11px] font-bold uppercase tracking-wider text-muted"
            >
              Session
            </label>
            <div className="relative mt-2 flex items-center gap-2 rounded-control border border-line-strong bg-surface px-2.5">
              <History className="size-3.5 shrink-0 text-muted" />
              <select
                id="control-session"
                value={session}
                disabled={running || busy}
                onChange={(e) => pickSession(e.target.value)}
                className="h-9 w-full min-w-0 cursor-pointer bg-transparent font-mono text-[11.5px] font-semibold text-fg outline-none disabled:cursor-not-allowed disabled:opacity-60"
              >
                <option value={NEW_SESSION}>＋ New session (from 0)</option>
                {sessions.map((run) => (
                  <option key={run.runId} value={run.runId}>
                    {run.runId} ({run.windowsCount ?? 0}w · {run.isActive ? 'current' : run.status})
                  </option>
                ))}
              </select>
            </div>
            <p className="mt-1.5 text-[11.5px] leading-snug text-faint">
              {session === NEW_SESSION
                ? `Opens a fresh ${setup ? splitSymbol(setup.symbol).label : ''} run with 0 windows.`
                : sessions.length > 0
                  ? `Resumes on the existing run database. ${sessions.length} past ${sessions.length === 1 ? 'run' : 'runs'} for this strategy.`
                  : ''}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {running ? (
              <Button variant="secondary" size="sm" className="flex-1" loading={stop.isPending} onClick={onStop}>
                <Pause /> Stop bot
              </Button>
            ) : (
              <Button variant="primary" size="sm" className="flex-1" loading={busy} disabled={!setup} onClick={onStart}>
                <Play /> {startLabel}
              </Button>
            )}
            {running && (
              <Button
                variant={killEngaged ? 'primary' : 'danger'}
                size="sm"
                loading={killSwitch.isPending}
                onClick={() =>
                  killSwitch.mutate(!killEngaged, {
                    onSuccess: () => toast(killEngaged ? 'Entries resumed' : 'Entries paused'),
                    onError: (error: Error) => toast(error.message, 'danger'),
                  })
                }
              >
                {killEngaged ? <Play /> : <ShieldAlert />}
                {killEngaged ? 'Resume entries' : 'Pause entries'}
              </Button>
            )}
            {!isViewOnly && (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Reset bot"
                title="Reset paper bot"
                onClick={() => setConfirmReset(true)}
              >
                <RotateCcw />
              </Button>
            )}
          </div>

          <div className="rounded-tile border border-line bg-surface-2/30 p-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              {(() => {
                const tape = tapeQuery.data ?? control.data?.tape ?? null
                return (
                  <Badge tone="success" dot>
                    {`Tape ON · ${tape?.prints ?? 0} prints · ${tape?.books ?? 0} books · ${(tape?.mb ?? 0).toFixed(2)} MB`}
                  </Badge>
                )
              })()}
            </div>
            <p className="mt-1.5 font-mono text-[10.5px] leading-snug text-faint">
              {(tapeQuery.data?.tapeDir ?? control.data?.tape?.tapeDir ?? (activeRunId ? `bot/runs/${activeRunId}/tape` : 'bot/runs/<run-id>/tape'))}
              {' '}· prints.jsonl + book.jsonl · same WS connection, no terminal
            </p>
            {!running && (tapeQuery.data?.enabled ?? control.data?.tape?.enabled ?? false) && (
              <p className="mt-1 text-[11px] text-muted">Tape arms on Start / Resume — the next window starts writing, and every fill is audited against it.</p>
            )}
          </div>

          <p className="text-[11.5px] text-muted">
            {running
              ? `Trading ${activeRunId ?? 'current session'}.`
              : isViewOnly
                ? `Previewing ${selectedRunId}. Start resumes it on its own database.`
                : 'The loop is not running — no new windows are being taken.'}
            {!running && heartbeatMs != null && <> Last heartbeat {relativeTime(Date.now() - heartbeatMs)}.</>}
          </p>

          {risk?.halted && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-tile bg-danger-soft p-2.5 text-[12px] text-danger">
              <span>Halted for the day: {reasonLabel(risk.haltReason)}</span>
              <Button
                size="sm"
                variant="secondary"
                loading={clearHalt.isPending}
                onClick={() =>
                  clearHalt.mutate(undefined, {
                    onSuccess: () => toast('Risk halt cleared and entries resumed'),
                    onError: (error: Error) => toast(error.message, 'danger'),
                  })
                }
              >
                Clear halt
              </Button>
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirmReset}
        onClose={() => setConfirmReset(false)}
        loading={reset.isPending}
        title="Reset the paper bot?"
        description="This wipes every paper window, fill and risk counter and restarts from the configured bankroll. It cannot be undone."
        confirmLabel="Reset to clean state"
        onConfirm={() =>
          reset.mutate(undefined, {
            onSuccess: (result) => {
              setConfirmReset(false)
              toast(`Bot reset to ${money2(result.bankrollUsd)} — window history wiped`)
            },
          })
        }
      />
    </Card>
  )
}

function Param({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-[78px] rounded-[8px] border border-line bg-surface px-2.5 py-1 text-center">
      <div className="font-mono text-[9.5px] font-bold uppercase text-faint">{label}</div>
      <div className="font-mono text-[12.5px] font-semibold text-fg">{value}</div>
    </div>
  )
}
