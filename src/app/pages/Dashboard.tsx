import { Activity, AlertTriangle, CheckCircle2, Info, Pause, Play, RotateCcw, Target } from 'lucide-react'
import { Link } from 'react-router'
import { useState } from 'react'

import { Badge, Button, Card, ConfirmDialog, EmptyState, PageHeader, Skeleton, useToast } from '../components/ui'
import { BOT_ORIGIN, useBotControl, useBotPerf, useResetBot, useStartBot, useStopBot } from '../lib/bot'
import type { BotPerf, PerfGate, PerfNote, PerfWindow } from '../lib/bot'
import { cx } from '../lib/cx'
import { money2, relativeTime } from '../lib/format'

const usd = money2
const share = (value: number) => `${Math.round(value * 100)}%`
const windowTime = (ms: number) =>
  new Date(ms).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })

function windowLabel(slug: string | null): string {
  if (!slug) return '—'
  const epoch = Number(slug.split('-').pop())
  return Number.isFinite(epoch) ? windowTime(epoch * 1000) : slug
}

function cumulative(windows: PerfWindow[]) {
  let run = 0
  return windows.map((window) => {
    run += window.netUsd ?? 0
    return { ts: window.startMs, value: Math.round(run * 100) / 100 }
  })
}

const GATE_TONE: Record<PerfGate['status'], 'success' | 'warning' | 'danger' | 'neutral'> = {
  pass: 'success',
  warn: 'warning',
  fail: 'danger',
  sample: 'neutral',
}
const GATE_LABEL: Record<PerfGate['status'], string> = {
  pass: 'pass',
  warn: 'watch',
  fail: 'off',
  sample: 'sample',
}

const NOTE_TONE: Record<PerfNote['tone'], string> = {
  danger: 'bg-danger-soft text-danger',
  warning: 'bg-warning-soft text-warning',
  info: 'bg-info-soft text-info',
  success: 'bg-success-soft text-success',
}

export function Dashboard() {
  const perf = useBotPerf()
  const control = useBotControl()
  const start = useStartBot()
  const stop = useStopBot()
  const reset = useResetBot()
  const toast = useToast()
  const [confirmReset, setConfirmReset] = useState(false)

  const running = control.data?.running ?? false
  const data = perf.data
  const summary = data?.summary
  const health = data?.health
  const notes = data?.notes ?? []
  const windows = data?.windows ?? []
  const settled = windows.filter((window) => !window.pending)
  const curve = cumulative(settled)
  const gateJudged = settled.length >= 288

  return (
    <div className="mx-auto max-w-[1200px] p-5 sm:p-8">
      <PageHeader
        title="Paper desk"
        subtitle="BTC 5-minute straddle-plus-lean, held to redeem. Every number is the loop's own paper tape."
        actions={
          <div className="flex items-center gap-2">
            <Badge tone={running ? 'success' : 'neutral'} dot>
              {running ? 'Running' : 'Stopped'}
            </Badge>
            <Badge tone="warning">Paper only</Badge>
            <Button
              variant={running ? 'secondary' : 'primary'}
              size="sm"
              loading={start.isPending || stop.isPending}
              onClick={() =>
                running
                  ? stop.mutate(undefined, { onSuccess: () => toast('Bot stopped') })
                  : start.mutate(undefined, {
                      onSuccess: (result) =>
                        toast(result.reason === 'already-running' ? 'Bot already running' : 'Paper bot started'),
                    })
              }
            >
              {running ? <Pause /> : <Play />}
              {running ? 'Stop bot' : 'Start bot'}
            </Button>
            <Button variant="ghost" size="icon-sm" aria-label="Reset bot" onClick={() => setConfirmReset(true)}>
              <RotateCcw />
            </Button>
          </div>
        }
      />

      {perf.isError && (
        <Card className="mt-4 p-5">
          <div className="flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-tile bg-warning-soft text-warning">
              <Activity className="size-4.5" />
            </span>
            <div>
              <p className="text-[13.5px] font-medium">Bot API not reachable</p>
              <p className="mt-0.5 text-[12.5px] text-muted">
                Nothing answered at {BOT_ORIGIN}. Start it with <code className="font-mono">python bot/api.py</code>; this
                page refills on its own.
              </p>
            </div>
          </div>
        </Card>
      )}

      {!running && !perf.isError && (
        <Card className="mt-4 flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-tile bg-warning-soft text-warning">
              <Activity className="size-4.5" />
            </span>
            <div>
              <p className="text-[13.5px] font-medium">The loop is not running</p>
              <p className="text-[12.5px] text-muted">
                No new windows are being taken.
                {health?.snapshotAgeSec != null && (
                  <> Last heartbeat {relativeTime(Date.now() - health.snapshotAgeSec * 1000)}.</>
                )}
              </p>
            </div>
          </div>
          <Button size="sm" loading={start.isPending} onClick={() => start.mutate(undefined, { onSuccess: () => toast('Paper bot started') })}>
            <Play /> Start paper bot
          </Button>
        </Card>
      )}

      <Card className="mt-3 grid gap-x-6 gap-y-2 px-4 py-3 sm:grid-cols-2 lg:grid-cols-4">
        <HealthItem
          label="Loop"
          value={running ? `running · pid ${control.data?.pid ?? '—'}` : 'stopped'}
          tone={running ? 'success' : 'warning'}
        />
        <HealthItem
          label="Heartbeat"
          value={
            health?.snapshotAgeSec == null
              ? 'no state'
              : health.snapshotAgeSec < 120
                ? `${Math.round(health.snapshotAgeSec)}s ago`
                : relativeTime(Date.now() - health.snapshotAgeSec * 1000)
          }
          tone={health?.snapshotAgeSec == null ? 'neutral' : health.snapshotAgeSec > 120 ? 'warning' : 'success'}
        />
        <HealthItem
          label="Window"
          value={health?.stateSlug ? `${windowLabel(health.stateSlug)} · ${health.stateFills} fills` : 'idle between windows'}
          tone="neutral"
        />
        <HealthItem
          label="Kill switch"
          value={health?.killSwitch ? 'engaged — entries paused' : 'clear'}
          tone={health?.killSwitch ? 'danger' : 'neutral'}
        />
      </Card>

      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {!summary ? (
          Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-[104px] rounded-card" />)
        ) : (
          <>
            <Stat
              label="Paper net"
              value={usd(summary.netUsd)}
              hint={`${summary.profitable}/${summary.settled} windows profitable · ${(summary.roi * 100).toFixed(1)}% on cost`}
              tone={summary.netUsd >= 0 ? 'success' : 'danger'}
            />
            <Stat
              label="Staked"
              value={usd(summary.costUsd)}
              hint={`${summary.fills} fills · median ${summary.medianFills} / window`}
            />
            <Stat
              label="Returned"
              value={usd(summary.payoutUsd)}
              hint={`held to resolution${summary.pending ? ` · ${summary.pending} settling` : ''}`}
            />
            <Stat
              label="Redeem due"
              value={usd(data?.redeem.payoutUsd ?? 0)}
              hint={`${data?.redeem.count ?? 0} winning window${data?.redeem.count === 1 ? '' : 's'} unclaimed`}
              tone={(data?.redeem.count ?? 0) > 0 ? 'warning' : undefined}
            />
          </>
        )}
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h2 className="text-[14px] font-semibold">Fidelity gate</h2>
              <p className="text-[12.5px] text-muted">
                How close the live paper tape is to the frozen 24h sample — 45 median fills, both sides, $316/$447 cost,
                M0–M4 shape.
              </p>
            </div>
            <Badge tone={gateJudged ? 'success' : 'neutral'}>
              {gateJudged ? 'judged' : `sample · ${settled.length}/288`}
            </Badge>
          </div>

          <div className="mt-3 divide-y divide-line">
            {(data?.gate ?? []).map((row) => (
              <div key={row.key} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="text-[13px]">{row.label}</p>
                  <p className="text-[11.5px] text-faint">{row.detail}</p>
                </div>
                <span className="tabular-nums text-[13px] font-medium">{row.value}</span>
                <span className="w-[92px] text-right text-[12px] text-faint">tape {row.target}</span>
                <Badge tone={GATE_TONE[row.status]} className="w-[74px] justify-center">
                  {GATE_LABEL[row.status]}
                </Badge>
              </div>
            ))}
            {!data && <Skeleton className="my-4 h-[180px]" />}
          </div>

          {data && <ShapeChart mShape={data.mShape} />}
        </Card>

        <Card className="flex flex-col p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-[14px] font-semibold">Things to note</h2>
            <Badge tone="neutral">{notes.length}</Badge>
          </div>
          <p className="text-[12.5px] text-muted">What the tape says about this run, worst first.</p>
          <ul className="scrollbar-thin mt-3 -mr-2 max-h-[430px] space-y-2.5 overflow-y-auto pr-2">
            {notes.map((note) => (
              <li key={note.title} className="rounded-tile border border-line bg-surface-2/40 p-3">
                <div className="flex items-start gap-2">
                  <span className={cx('mt-0.5 grid size-5 shrink-0 place-items-center rounded-[6px]', NOTE_TONE[note.tone])}>
                    {note.tone === 'danger' || note.tone === 'warning' ? (
                      <AlertTriangle className="size-3" />
                    ) : note.tone === 'success' ? (
                      <CheckCircle2 className="size-3" />
                    ) : (
                      <Info className="size-3" />
                    )}
                  </span>
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium leading-snug">{note.title}</p>
                    <p className="mt-1 text-[12px] leading-relaxed text-muted">{note.body}</p>
                  </div>
                </div>
              </li>
            ))}
            {!data && <Skeleton className="h-[220px]" />}
          </ul>
        </Card>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h2 className="text-[14px] font-semibold">Paper P&amp;L</h2>
              <p className="text-[12.5px] text-muted">Cumulative net per settled window; pending windows are excluded.</p>
            </div>
            {summary && (
              <span
                className={cx(
                  'tabular-nums text-[22px] font-semibold tracking-[-0.02em]',
                  summary.netUsd >= 0 ? 'text-success' : 'text-danger',
                )}
              >
                {usd(summary.netUsd)}
              </span>
            )}
          </div>

          {settled.length > 0 ? (
            <>
              <div className="mt-3">
                <NetCurve points={curve} />
              </div>
              <div className="mt-4 border-t border-line pt-3">
                <div className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-muted">
                  <span>Last {Math.min(settled.length, 24)} windows</span>
                  <span className="text-faint">
                    best {usd(summary?.bestUsd ?? 0)} · worst {usd(summary?.worstUsd ?? 0)}
                  </span>
                </div>
                <WindowBars windows={settled.slice(-24)} />
              </div>
            </>
          ) : (
            <div className="mt-3">
              <EmptyState
                icon={<Target />}
                title="No settled windows yet"
                description="The first window settles about five minutes after the loop opens it. Everything here fills in on its own."
              />
            </div>
          )}
        </Card>

        <Card className="p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-[14px] font-semibold">Resolution &amp; redeem</h2>
            <Target className="size-4 text-faint" />
          </div>

          {summary ? (
            <>
              <div className="mt-3">
                <div className="flex items-baseline justify-between">
                  <p className="text-[13px] text-muted">Windows profitable</p>
                  <p className="tabular-nums text-[13px] font-medium">
                    {summary.profitable}/{summary.settled}
                  </p>
                </div>
                <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-2">
                  <div className="h-full rounded-full bg-success" style={{ width: `${summary.hitRate * 100}%` }} />
                </div>
              </div>

              <ul className="mt-4 space-y-2.5 text-[12.5px]">
                <Row label="Best window" value={usd(summary.bestUsd)} tone={summary.bestUsd >= 0 ? 'success' : undefined} />
                <Row label="Worst window" value={usd(summary.worstUsd)} tone="danger" />
                <Row label="Winning sides" value={`Up ${summary.upWins} · Down ${summary.downWins}`} />
                <Row label="Settling now" value={String(summary.pending)} />
              </ul>

              <div className="mt-4 border-t border-line pt-3">
                <div className="flex items-center justify-between text-[12.5px]">
                  <span className="text-muted">Fill mix</span>
                  <span className="tabular-nums text-faint">
                    Up {summary.upFills} · Down {summary.downFills}
                  </span>
                </div>
                <div className="mt-1.5 flex h-2 overflow-hidden rounded-full bg-surface-2">
                  <div
                    className="h-full bg-success/80"
                    style={{
                      width: `${(summary.upFills / Math.max(1, summary.upFills + summary.downFills)) * 100}%`,
                    }}
                    title={`${share(summary.upFills / Math.max(1, summary.upFills + summary.downFills))} Up`}
                  />
                  <div className="h-full flex-1 bg-danger/70" />
                </div>
                <p className="mt-1 text-[11.5px] text-faint">
                  {share(summary.upFills / Math.max(1, summary.upFills + summary.downFills))} Up ·{' '}
                  {share(summary.downFills / Math.max(1, summary.upFills + summary.downFills))} Down
                </p>
              </div>

              <div className="mt-4 rounded-tile bg-surface-2/60 p-3">
                <p className="text-[12.5px] font-medium">
                  {data?.redeem.count ?? 0} unredeemed · {usd(data?.redeem.payoutUsd ?? 0)}
                </p>
                <p className="mt-1 text-[11.5px] leading-relaxed text-muted">
                  Winners only pay when claimed. Run <code className="font-mono">python bot/redeem.py --dry-run</code>,
                  then without the flag.
                </p>
              </div>
            </>
          ) : (
            <Skeleton className="mt-4 h-[280px]" />
          )}
        </Card>
      </div>

      <Card className="mt-3 p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="text-[14px] font-semibold">Window log</h2>
            <p className="text-[12.5px] text-muted">
              One row per 5-minute window, newest first. Net is payout minus staked cost at resolution.
            </p>
          </div>
          <Link to="/live" className="text-[12.5px] text-muted hover:text-fg">
            Live view
          </Link>
        </div>

        {windows.length === 0 ? (
          <EmptyState
            icon={<Target />}
            title="No windows traded yet"
            description="Start the loop and the first row appears when it opens a window."
          />
        ) : (
          <div className="scrollbar-thin mt-3 max-h-[460px] overflow-auto">
            <table className="w-full min-w-[720px] text-left text-[13px]">
              <thead className="sticky top-0 bg-surface text-[11.5px] uppercase tracking-wide text-faint">
                <tr className="border-b border-line">
                  <th className="py-2 font-medium">Window</th>
                  <th className="py-2 text-right font-medium">Fills</th>
                  <th className="py-2 font-medium">Sides</th>
                  <th className="py-2 text-right font-medium">Cost</th>
                  <th className="py-2 text-right font-medium">Payout</th>
                  <th className="py-2 text-right font-medium">Net</th>
                  <th className="py-2 font-medium">Winner</th>
                  <th className="py-2 font-medium">Redeem</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {[...windows].reverse().map((window) => (
                  <tr key={window.slug}>
                    <td className="py-2.5 tabular-nums text-muted">{windowTime(window.startMs)}</td>
                    <td className="py-2.5 text-right tabular-nums">
                      {window.trades}
                      {window.zeroPriceFills > 0 && (
                        <span className="ml-1 text-[11px] text-danger" title={`${window.zeroPriceFills} fills at $0.00`}>
                          ({window.zeroPriceFills} zero)
                        </span>
                      )}
                    </td>
                    <td className="py-2.5">
                      <Badge tone={window.bothSides ? 'neutral' : 'warning'} className="capitalize">
                        {window.bothSides ? 'both' : 'single'}
                      </Badge>
                    </td>
                    <td className="py-2.5 text-right tabular-nums text-muted">{usd(window.costUsd)}</td>
                    <td className="py-2.5 text-right tabular-nums text-muted">{usd(window.payoutUsd)}</td>
                    <td
                      className={cx(
                        'py-2.5 text-right font-medium tabular-nums',
                        window.netUsd == null ? 'text-faint' : window.netUsd >= 0 ? 'text-success' : 'text-danger',
                      )}
                    >
                      {window.netUsd == null ? 'settling…' : usd(window.netUsd)}
                    </td>
                    <td className="py-2.5">
                      {window.winner ? (
                        <Badge tone={window.winner === 'Up' ? 'success' : 'danger'}>{window.winner}</Badge>
                      ) : (
                        <span className="text-faint">—</span>
                      )}
                    </td>
                    <td className="py-2.5 text-muted">
                      {window.pending ? '—' : window.redeemed ? 'claimed' : 'due'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

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
              toast(`Bot reset to ${usd(result.bankrollUsd)} — window history wiped`)
            },
          })
        }
      />
    </div>
  )
}

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string
  value: string
  hint: string
  tone?: 'success' | 'danger' | 'warning'
}) {
  return (
    <Card className="flex h-[104px] flex-col justify-between p-4">
      <p className="text-[13px] text-muted">{label}</p>
      <div>
        <p
          className={cx(
            'text-[22px] font-semibold tracking-[-0.02em] tabular-nums',
            tone === 'danger' && 'text-danger',
            tone === 'warning' && 'text-warning',
          )}
        >
          {value}
        </p>
        <p className="mt-0.5 truncate text-[12px] text-faint">{hint}</p>
      </div>
    </Card>
  )
}

function HealthItem({ label, value, tone }: { label: string; value: string; tone: 'success' | 'warning' | 'danger' | 'neutral' }) {
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span className="text-[11px] uppercase tracking-wide text-faint">{label}</span>
      <span
        className={cx(
          'min-w-0 truncate text-[12.5px] font-medium',
          tone === 'success' && 'text-success',
          tone === 'warning' && 'text-warning',
          tone === 'danger' && 'text-danger',
          tone === 'neutral' && 'text-fg',
        )}
      >
        {value}
      </span>
    </div>
  )
}

function Row({ label, value, tone }: { label: string; value: string; tone?: 'success' | 'danger' }) {
  return (
    <li className="flex items-center justify-between">
      <span className="text-muted">{label}</span>
      <span className={cx('font-medium tabular-nums', tone === 'success' && 'text-success', tone === 'danger' && 'text-danger')}>
        {value}
      </span>
    </li>
  )
}

function ShapeChart({ mShape }: { mShape: BotPerf['mShape'] }) {
  const max = Math.max(0.05, ...mShape.liveShare, ...mShape.targetShare)
  return (
    <div className="mt-4 rounded-tile border border-line bg-surface-2/30 p-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[12.5px] font-medium">Fill cadence · minutes 0–4</p>
        <div className="flex items-center gap-3 text-[11px] text-faint">
          <span className="flex items-center gap-1">
            <span className="size-2 rounded-[2px] bg-accent" /> live
          </span>
          <span className="flex items-center gap-1">
            <span className="size-2 rounded-[2px] bg-line-strong" /> tape
          </span>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-5 gap-3">
        {mShape.liveShare.map((live, index) => (
          <div key={index}>
            <div className="flex h-16 items-end justify-center gap-1.5">
              <div
                className="w-1/3 rounded-t-[3px] bg-accent"
                style={{ height: `${Math.max(2, (live / max) * 100)}%` }}
                title={`live ${share(live)} · ${mShape.live[index]} fills`}
              />
              <div
                className="w-1/3 rounded-t-[3px] bg-line-strong"
                style={{ height: `${Math.max(2, (mShape.targetShare[index] / max) * 100)}%` }}
                title={`tape ${share(mShape.targetShare[index])} · ${mShape.target[index]} fills`}
              />
            </div>
            <p className="mt-1 text-center text-[11px] text-faint">
              M{index} <span className="text-fg">{share(live)}</span> / {share(mShape.targetShare[index])}
            </p>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11.5px] text-faint">
        {(mShape.distance * 100).toFixed(1)}% total-variation distance from the tape.{' '}
        {mShape.distance > 0.2 ? 'Live is late-heavy: M4 carries far more fills than the tape.' : 'Shape is inside the band.'}
      </p>
    </div>
  )
}

function NetCurve({ points }: { points: { ts: number; value: number }[] }) {
  if (points.length === 0) return null
  const width = 600
  const height = 170
  const padX = 8
  const padTop = 14
  const padBottom = 22
  const values = points.map((point) => point.value)
  const min = Math.min(0, ...values)
  const max = Math.max(0, ...values)
  const span = max - min || 1
  const x = (index: number) =>
    padX + (points.length === 1 ? (width - padX * 2) / 2 : (index * (width - padX * 2)) / (points.length - 1))
  const y = (value: number) => padTop + (height - padTop - padBottom) * (1 - (value - min) / span)
  const line = points.map((point, index) => `${index === 0 ? 'M' : 'L'}${x(index)},${y(point.value)}`).join(' ')
  const zeroY = y(0)
  const last = values[values.length - 1]
  const tone = last >= 0 ? 'var(--color-success)' : 'var(--color-danger)'

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" preserveAspectRatio="none" role="img" aria-label="Cumulative paper net">
      <line x1={padX} x2={width - padX} y1={zeroY} y2={zeroY} stroke="var(--color-line-strong)" strokeDasharray="3 4" />
      <text x={width - padX} y={Math.max(11, zeroY - 5)} fontSize="11" textAnchor="end" fill="var(--color-faint)">
        $0
      </text>
      <path d={line} fill="none" stroke={tone} strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      <circle cx={x(points.length - 1)} cy={y(last)} r="3.5" fill={tone} />
      <text x={padX} y={height - 4} fontSize="11" fill="var(--color-faint)">
        {windowTime(points[0].ts)}
      </text>
      <text x={width - padX} y={height - 4} fontSize="11" textAnchor="end" fill="var(--color-faint)">
        {windowTime(points[points.length - 1].ts)}
      </text>
    </svg>
  )
}

function WindowBars({ windows }: { windows: PerfWindow[] }) {
  if (windows.length === 0) return null
  const maxAbs = Math.max(1, ...windows.map((window) => Math.abs(window.netUsd ?? 0)))
  return (
    <div className="relative mt-2 flex h-24 items-stretch gap-[3px]">
      <div className="pointer-events-none absolute inset-x-0 top-1/2 border-t border-line-strong" />
      {windows.map((window) => {
        const net = window.netUsd ?? 0
        const height = Math.max(3, (Math.abs(net) / maxAbs) * 48)
        return (
          <div
            key={window.slug}
            className="relative flex-1"
            title={`${windowTime(window.startMs)} · ${net >= 0 ? '+' : '−'}${usd(Math.abs(net))} · ${window.trades} fills · ${window.winner ?? 'pending'}`}
          >
            <div
              className={cx(
                'absolute inset-x-0 rounded-[2px]',
                net >= 0 ? 'bottom-1/2 bg-success/80' : 'top-1/2 bg-danger/80',
              )}
              style={{ height: `${height}%` }}
            />
          </div>
        )
      })}
    </div>
  )
}
