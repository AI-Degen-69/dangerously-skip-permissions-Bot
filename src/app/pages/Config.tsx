import { useMemo, useState, type ReactNode } from 'react'
import { Coins, Filter, RotateCcw, Scale, ShieldAlert, SlidersHorizontal } from 'lucide-react'

import { Badge, Button, Card, Field, Input, PageHeader, Select, Skeleton, useToast } from '../components/ui'
import { useBotConfig, useBotControl, useSaveBotConfig, type BotConfigView } from '../lib/bot'
import { cx } from '../lib/cx'
import { DEFAULT_CONFIG, EDITABLE } from '../botDefaults'

type Draft = Record<string, number>

interface FieldSpec {
  path: string
  label: string
  hint?: string
  tip?: ReactNode
  step?: number
}

const rangeError = ([min, max]: [number, number]): string =>
  max === Number.POSITIVE_INFINITY ? `At least ${min}` : `Between ${min} and ${max}`
const inRange = (path: string, value: number): boolean => {
  const range = EDITABLE[path]
  return !range || (Number.isFinite(value) && value >= range[0] && value <= range[1])
}
const errorFor = (path: string, value: number): string | undefined => {
  const range = EDITABLE[path]
  return range && !inRange(path, value) ? rangeError(range) : undefined
}

function ResetFieldButton({ onReset, label, className }: { onReset: () => void; label: string; className?: string }) {
  return (
    <button
      type="button"
      onClick={onReset}
      aria-label={`Reset ${label} to default`}
      title="Reset to default"
      className={cx(
        'grid h-9 w-9 shrink-0 place-items-center border border-l-0 border-line-strong bg-surface-2 text-faint transition-colors hover:bg-raised hover:text-fg',
        className ?? 'rounded-r-control',
      )}
    >
      <RotateCcw className="size-4" aria-hidden="true" />
    </button>
  )
}

function EdgeTip({ title, gist, lowLabel, lowText, highLabel, highText, foot }: {
  title: string; gist: string; lowLabel: string; lowText: string;
  highLabel: string; highText: string; foot: string
}) {
  return (
    <span className="block">
      <span className="block text-[12px] font-semibold">{title}</span>
      <span className="mt-1 block text-[11.5px] leading-snug text-surface/85">{gist}</span>
      <span className="mt-2 block space-y-1.5 border-t border-surface/15 pt-2 text-[11px] leading-snug text-surface/85">
        <span className="flex gap-2">
          <span className="w-10 shrink-0 font-mono font-semibold text-surface">{lowLabel}</span>
          <span>{lowText}</span>
        </span>
        <span className="flex gap-2">
          <span className="w-10 shrink-0 font-mono font-semibold text-surface">{highLabel}</span>
          <span>{highText}</span>
        </span>
      </span>
      <span className="mt-2 block border-t border-surface/15 pt-2 text-[10.5px] leading-snug text-surface/60">{foot}</span>
    </span>
  )
}

const TONES = {
  success: 'bg-success-soft text-success',
  info: 'bg-info-soft text-info',
  accent: 'bg-accent-soft text-accent',
  warning: 'bg-warning-soft text-warning',
  danger: 'bg-danger-soft text-danger',
} as const
type Tone = keyof typeof TONES

const GROUPS: { title: string; note?: string; icon: typeof Coins; tone: Tone; fields: FieldSpec[] }[] = [
  {
    title: 'Capital',
    note: 'Paper bankroll the KPIs are measured against. No real money moves, ever.',
    icon: Coins,
    tone: 'success',
    fields: [{ path: 'bankrollUsd', label: 'Bankroll (USD)', step: 10 }],
  },
  {
    title: 'Execution',
    note: 'How each 5-minute window is worked: open timing, clips, cadence.',
    icon: Filter,
    tone: 'info',
    fields: [
      { path: 'entry.clipSharesDefault', label: 'Clip size (shares)', hint: '30 = the target signature', tip: <EdgeTip title="Clip size" gist="Default fill size. Every Nth fill uses the full clip, the rest use the median size — that mix reproduces the 30.4% exact-30s fingerprint." lowLabel="1" lowText="Dust fills — nothing like the target's tape." highLabel="50" highText="Every fill at the cap — overshoots the $316 median window." foot="Default 30 · clamped 1–50" />, step: 1 },
      { path: 'entry.clipEveryNth', label: 'Full clip every Nth fill', step: 1 },
      { path: 'entry.medianShares', label: 'Median fill (shares)', hint: '13.86 measured', step: 0.5 },
      { path: 'entry.maxShares', label: 'Max shares per fill', step: 1 },
      { path: 'entry.medianFillsTarget', label: 'Fills per window target', hint: '45 measured median', tip: <EdgeTip title="Fills target" gist="Paper fills planned per window, spread over M1–M3 with an M4 snipe. 45 matches the target's median; 58 is its mean (fat tail to 404)." lowLabel="5" lowText="Thin tape — fidelity diff fails on cadence." highLabel="400" highText="Machine-gun tape — trips the window cap." foot="Default 45 · clamped 5–400" />, step: 1 },
      { path: 'entry.openDelaySec', label: 'First touch delay (s)', hint: '13s median measured', step: 1 },
      { path: 'entry.hedgeDelaySec', label: 'Hedge leg delay (s)', hint: '15s median measured', step: 1 },
      { path: 'entry.stopBeforeCloseSec', label: 'Stop before close (s)', step: 1 },
      { path: 'entry.minFillPrice', label: 'Min fill price', hint: 'skip quotes under 1¢', step: 0.01 },
    ],
  },
  {
    title: 'Sizing',
    icon: Scale,
    tone: 'accent',
    fields: [],
  },
  {
    title: 'Risk limits',
    note: 'Paper guardrails. The kill-switch file pauses entries mid-loop.',
    icon: ShieldAlert,
    tone: 'danger',
    fields: [
      { path: 'risk.maxUsdPerWindow', label: 'Max USD per window', hint: '$3,804 max observed', step: 50 },
      { path: 'risk.maxFillsPerWindow', label: 'Max fills per window', step: 10 },
      { path: 'risk.dailyLossCapUsd', label: 'Daily loss cap (USD)', tip: <EdgeTip title="Daily loss cap" gist="Paper loop halts for the day once realized paper loss passes this. Approve a value before any live-size conversation." lowLabel="$10" lowText="Hair-trigger — a single bad window halts the day." highLabel="$100k" highText="Effectively off." foot="Default $500 · set with the operator" />, step: 25 },
      { path: 'risk.maxConcurrentPositions', label: 'Max open positions', step: 1 },
    ],
  },
]

const ALL_PATHS = GROUPS.flatMap((group) => group.fields.map((field) => field.path))

function readPath(source: unknown, path: string): number {
  const value = path.split('.').reduce<unknown>((cursor, key) => (cursor as Record<string, unknown> | undefined)?.[key], source)
  return typeof value === 'number' ? value : 0
}

function flatten(config: BotConfigView): Draft {
  const draft: Draft = {}
  for (const group of GROUPS) for (const field of group.fields) draft[field.path] = readPath(config, field.path)
  return draft
}

export function Config() {
  const query = useBotConfig()
  const save = useSaveBotConfig()
  const control = useBotControl()
  const toast = useToast()
  const [draft, setDraft] = useState<Draft | null>(null)
  const [lean, setLean] = useState<string | null>(null)

  const config = query.data?.config ?? null
  const defaultValues = useMemo(() => flatten(DEFAULT_CONFIG as unknown as BotConfigView), [])
  const values = draft ?? (config ? flatten(config) : null)
  const leanValue = lean ?? ((config?.entry as Record<string, unknown>)?.leanSource as string | undefined) ?? 'microprice'
  const dirty = draft !== null || lean !== null
  const hasErrors = values !== null && ALL_PATHS.some((path) => !inRange(path, values[path] ?? 0))

  const set = (path: string, raw: string) => {
    const parsed = Number(raw)
    if (!Number.isFinite(parsed)) return
    setDraft({ ...(values ?? {}), [path]: parsed })
  }

  const onSave = () => {
    if (!values) return
    save.mutate({ ...values, 'entry.leanSource': leanValue }, {
      onSuccess: (result) => {
        setDraft(null)
        setLean(null)
        const warnings = result.warnings ?? []
        toast(warnings.length ? `Saved with ${warnings.length} adjustment(s)` : 'Configuration saved')
      },
      onError: (error: Error) => toast(error.message, 'danger'),
    })
  }

  return (
    <div className="mx-auto max-w-[1000px] p-5 sm:p-8">
      <PageHeader
        title="Configuration"
        subtitle="Every knob the paper loop reads. A running loop picks changes up on its next window."
        actions={
          <div className="flex items-center gap-2">
            {control.data && (
              <Badge tone={control.data.running ? 'success' : 'neutral'} dot>
                {control.data.running ? 'Running' : 'Stopped'}
              </Badge>
            )}
            <Button variant="primary" size="sm" onClick={onSave} loading={save.isPending} disabled={!dirty || !values || hasErrors} title={hasErrors ? 'Fix the highlighted fields first' : undefined}>
              Save changes
            </Button>
          </div>
        }
      />

      {query.isLoading || !config || !values ? (
        <Skeleton className="mt-6 h-[420px] rounded-card" />
      ) : (
        <>
          <Card className="mt-4 flex flex-wrap items-center gap-3 p-5">
            <span className="grid size-9 shrink-0 place-items-center rounded-tile bg-accent-soft text-accent">
              <SlidersHorizontal className="size-4.5" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-[14px] font-semibold">Lean signal</h2>
              <p className="mt-0.5 text-[12px] leading-snug text-muted">
                Microprice tilts each fill toward the book's strong side; dumb runs a neutral straddle for plumbing tests.
              </p>
            </div>
            <Select value={leanValue} onChange={(e) => setLean(e.target.value)} className="w-[200px]">
              <option value="microprice">Book microprice</option>
              <option value="dumb">Dumb (lean = 0)</option>
            </Select>
          </Card>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            {GROUPS.filter((g) => g.fields.length > 0).map((group) => {
              const Icon = group.icon
              return (
                <Card key={group.title} className={cx('p-5', group.fields.length > 6 && 'lg:col-span-2')}>
                  <div className="flex items-center gap-3">
                    <span className={cx('grid size-9 shrink-0 place-items-center rounded-tile', TONES[group.tone])}>
                      <Icon className="size-4.5" aria-hidden="true" />
                    </span>
                    <div className="min-w-0">
                      <h2 className="text-[14px] font-semibold">{group.title}</h2>
                      {group.note && <p className="mt-0.5 text-[12px] leading-snug text-muted">{group.note}</p>}
                    </div>
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {group.fields.map((field) => {
                      const value = values[field.path] ?? 0
                      const fieldError = errorFor(field.path, value)
                      return (
                        <Field key={field.path} label={field.label} hint={field.hint} tip={field.tip} error={fieldError}>
                          <span className="flex min-w-0 items-stretch">
                            <Input
                              type="number"
                              step={field.step ?? 0.01}
                              value={value}
                              onChange={(event) => set(field.path, event.target.value)}
                              invalid={fieldError !== undefined}
                              className="rounded-r-none border-r-0 tabular-nums"
                            />
                            <ResetFieldButton label={field.label} onReset={() => set(field.path, String(defaultValues[field.path] ?? 0))} />
                          </span>
                        </Field>
                      )
                    })}
                  </div>
                </Card>
              )
            })}
          </div>

          {hasErrors && (
            <p role="alert" className="mt-3 text-[12px] font-medium text-danger">
              Some fields are out of range — Save is disabled until they are fixed.
            </p>
          )}

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-[12.5px] text-faint">
              Saved to <span className="font-mono">bot/config.json</span>. Paper only — there is no live mode in this desk.
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => { setDraft(null); setLean(null) }}
                disabled={!dirty}
              >
                <RotateCcw /> Discard
              </Button>
              <Button variant="primary" size="sm" onClick={onSave} loading={save.isPending} disabled={!dirty || hasErrors} title={hasErrors ? 'Fix the highlighted fields first' : undefined}>
                Save changes
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
