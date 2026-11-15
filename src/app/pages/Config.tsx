import { useMemo, useState, type ReactNode } from 'react'
import { Coins, Filter, Info, RotateCcw, Scale, ShieldAlert, SlidersHorizontal, Zap } from 'lucide-react'

import { PageHeader, useToast } from '../components/ui'
import { StatusDot } from '../components/StatusDot'
import { useBotConfig, useBotControl, useSaveBotConfig, useStrategySetups, mergeStrategySetups, type BotConfigView, type StrategySetup } from '../lib/bot'
import { DEFAULT_CONFIG, EDITABLE, STRATEGY_PRESETS } from '../botDefaults'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Field, FieldDescription, FieldError, FieldLabel } from '@/components/ui/field'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from '@/components/ui/input-group'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

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

function EdgeTip({
  title,
  gist,
  lowLabel,
  lowText,
  highLabel,
  highText,
  foot,
}: {
  title: string
  gist: string
  lowLabel: string
  lowText: string
  highLabel: string
  highText: string
  foot: string
}) {
  return (
    <span className="block">
      <span className="block text-[12px] font-semibold text-popover-foreground">{title}</span>
      <span className="mt-1 block text-[11.5px] leading-snug text-muted-foreground">{gist}</span>
      <span className="mt-2 block space-y-1.5 border-t border-border/60 pt-2 text-[11px] leading-snug text-muted-foreground">
        <span className="flex gap-2">
          <span className="w-10 shrink-0 font-mono font-semibold text-popover-foreground">{lowLabel}</span>
          <span>{lowText}</span>
        </span>
        <span className="flex gap-2">
          <span className="w-10 shrink-0 font-mono font-semibold text-popover-foreground">{highLabel}</span>
          <span>{highText}</span>
        </span>
      </span>
      <span className="mt-2 block border-t border-border/60 pt-2 text-[10.5px] leading-snug text-muted-foreground/80">{foot}</span>
    </span>
  )
}

const TONES = {
  success: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
  info: 'bg-sky-500/10 text-sky-600 dark:text-sky-400',
  accent: 'bg-primary/10 text-primary',
  warning: 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
  danger: 'bg-rose-500/10 text-rose-600 dark:text-rose-400',
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
    title: 'Microstructure & Pair Bounds',
    note: 'Regime bands and mathematical sub-$1.00 pair-cost arbitrage constraints.',
    icon: Scale,
    tone: 'accent',
    fields: [
      {
        path: 'entry.targetPairCost',
        label: 'Target pair cost ($)',
        hint: 'Measured median: $0.9654',
        tip: (
          <EdgeTip
            title="Target Pair Cost"
            gist="The target combined price of 1 Up + 1 Down share. Accumulating below this level creates guaranteed spread margin upon redemption."
            lowLabel="$0.85"
            lowText="Demands steep dips — fewer dual fills."
            highLabel="$0.98"
            highText="More frequent hedges — narrower margin."
            foot="Default $0.965 · range $0.80–$0.99"
          />
        ),
        step: 0.005,
      },
      {
        path: 'entry.maxPairCost',
        label: 'Max pair cost cap ($)',
        hint: 'Strictly < $1.00 (0.990 cap)',
        tip: (
          <EdgeTip
            title="Max Pair Cost Ceiling"
            gist="Hard ceiling on equalizing hedges. Guarantees the bot NEVER enters an unhedged or losing pair ($1.00+ loses money)."
            lowLabel="$0.95"
            lowText="Strict safety — refuses any tight hedge."
            highLabel="$0.99"
            highText="Tolerates tighter hedges to avoid unhedged bias."
            foot="Default $0.990 · range $0.90–$0.999"
          />
        ),
        step: 0.005,
      },
      {
        path: 'entry.minFillPrice',
        label: 'Price floor (dust cutoff)',
        hint: '7¢ floor (blocked lottery tail)',
        tip: (
          <EdgeTip
            title="Price Floor"
            gist="Fills below 7¢ went 1-for-170 (−89.8% ROI) on the tape and are strictly refused."
            lowLabel="1¢"
            lowText="Allows dust lottery buys with terrible hit rate."
            highLabel="15¢"
            highText="Blocks valuable deep maker dip fills."
            foot="Default 0.07 (7¢) · range 0.01–0.50"
          />
        ),
        step: 0.01,
      },
      {
        path: 'entry.maxFillPrice',
        label: 'Price ceiling (favorite cutoff)',
        hint: '95¢ cap (blocked extreme favorites)',
        tip: (
          <EdgeTip
            title="Price Ceiling"
            gist="Fills above 95¢ lost −20.73% per dollar on the tape and are strictly refused."
            lowLabel="85¢"
            lowText="Limits late-window M4 equalizer hedges."
            highLabel="98¢"
            highText="Takes negative-EV extreme favorite lottery bets."
            foot="Default 0.95 (95¢) · range 0.70–0.99"
          />
        ),
        step: 0.01,
      },
      {
        path: 'entry.maxShareLead',
        label: 'Max one-sided lead (shares)',
        hint: '90 shares = 3x 30sh clips',
        tip: (
          <EdgeTip
            title="Max Share Lead"
            gist="Prevents runaway one-sided accumulation when a dipping token trends down without rebounding."
            lowLabel="30"
            lowText="Locks immediately after 1 unhedged clip."
            highLabel="180"
            highText="Allows high directional exposure before hedging."
            foot="Default 90 shares · range 10–300"
          />
        ),
        step: 10,
      },
    ],
  },
  {
    title: 'Execution Timing & Sizing',
    note: 'Active trading window (T+4s to T+288s), clip sizing, and anti-runaway pacing.',
    icon: Filter,
    tone: 'info',
    fields: [
      {
        path: 'entry.startAfterOpenSec',
        label: 'Opening buffer (s)',
        hint: '4s buffer (sbc 296–300)',
        tip: (
          <EdgeTip
            title="Opening Buffer"
            gist="Strictly 0 fills in first 4s on tape while orderbooks establish initial liquidity."
            lowLabel="0s"
            lowText="Acts immediately at T+0s on empty books."
            highLabel="15s"
            highText="Delays opening straddle needlessly."
            foot="Default 4s · range 0–30s"
          />
        ),
        step: 1,
      },
      {
        path: 'entry.stopBeforeCloseSec',
        label: 'Stop before close (s)',
        hint: '12s cutoff (sbc 0–12)',
        tip: (
          <EdgeTip
            title="Settlement Cutoff"
            gist="Strictly 0 fills in final 12s on tape. All trading ceases at T−12s to hold inventory to resolution."
            lowLabel="5s"
            lowText="Trades dangerously close to oracle expiry."
            highLabel="30s"
            highText="Cuts off M4 snipe window prematurely."
            foot="Default 12s · range 5–60s"
          />
        ),
        step: 1,
      },
      {
        path: 'entry.clipSharesDefault',
        label: 'Default clip size (shares)',
        hint: '30 shares = target signature',
        tip: (
          <EdgeTip
            title="Default Clip Size"
            gist="Single most common fill size on tape (5,134 fills, 30.4% exact-30s)."
            lowLabel="10"
            lowText="Smaller fills, slower grid accumulation."
            highLabel="50"
            highText="Every fill at cap — higher capital commitment."
            foot="Default 30 · range 1–50"
          />
        ),
        step: 1,
      },
      {
        path: 'entry.maxShares',
        label: 'Max shares per fill',
        hint: '50 shares = deficit catch-up cap',
        step: 5,
      },
      {
        path: 'entry.minSpacingMoveSec',
        label: 'Dynamic spacing on tick (s)',
        hint: '0.5s on orderbook price move',
        tip: (
          <EdgeTip
            title="Dynamic Spacing on Move"
            gist="Allows fast reactive execution when prices tick into deep discount."
            lowLabel="0.1s"
            lowText="Ultra-fast machine gun execution."
            highLabel="2.0s"
            highText="Slow execution, misses transient dips."
            foot="Default 0.5s · range 0.1–5.0s"
          />
        ),
        step: 0.1,
      },
      {
        path: 'entry.minSpacingStaticSec',
        label: 'Static replenishment spacing (s)',
        hint: '2.5s on unchanged quotes',
        tip: (
          <EdgeTip
            title="Static Spacing"
            gist="Prevents rapid orderbook self-fill runaway on resting static bids."
            lowLabel="1.0s"
            lowText="Fast grid fills on unchanged quotes."
            highLabel="5.0s"
            highText="Slow grid pacing."
            foot="Default 2.5s · range 0.5–10.0s"
          />
        ),
        step: 0.5,
      },
    ],
  },
  {
    title: 'Risk limits',
    note: 'Paper guardrails. The kill-switch file pauses entries mid-loop.',
    icon: ShieldAlert,
    tone: 'danger',
    fields: [
      { path: 'risk.dailyLossCapUsd', label: 'Daily loss cap (USD)', hint: '$500 daily stop-loss', step: 25 },
      { path: 'risk.maxFillsPerWindow', label: 'Max fills per window', hint: '500 trade cap', step: 10 },
      { path: 'risk.maxConcurrentPositions', label: 'Max open windows', hint: '1 active window max', step: 1 },
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

  const setupsQuery = useStrategySetups()
  const allSetups = mergeStrategySetups(setupsQuery.data?.setups, STRATEGY_PRESETS as unknown as Record<string, StrategySetup>)
  const strategyId = (query.data?.config as unknown as { strategy?: { id?: string } } | null)?.strategy?.id ?? control.data?.strategy?.id ?? setupsQuery.data?.activeSetupId
  const activeSetup = allSetups.find((s) => s.id === strategyId) ?? allSetups[0]
  const config = query.data?.config ?? null
  const defaultValues = useMemo(() => flatten(DEFAULT_CONFIG as unknown as BotConfigView), [])
  const values = draft ?? (config ? flatten(config) : null)
  const dirty = draft !== null
  const hasErrors = values !== null && ALL_PATHS.some((path) => !inRange(path, values[path] ?? 0))

  const set = (path: string, raw: string) => {
    const parsed = Number(raw)
    if (!Number.isFinite(parsed)) return
    setDraft({ ...(values ?? {}), [path]: parsed })
  }

  const onSave = () => {
    if (!values) return
    save.mutate(values, {
      onSuccess: (result) => {
        setDraft(null)
        const warnings = result.warnings ?? []
        toast(warnings.length ? `Saved with ${warnings.length} adjustment(s)` : 'Configuration saved')
      },
      onError: (error: Error) => toast(error.message, 'danger'),
    })
  }

  return (
    <div className="mx-auto max-w-[1000px] p-5 sm:p-8">
      <PageHeader
        icon={<SlidersHorizontal className="size-5" />}
        title={activeSetup ? `Configuration · ${activeSetup.symbol}` : 'Configuration'}
        actions={
          <div className="flex items-center gap-2">
            {control.data && (
              <Badge
                variant="outline"
                className={cn(
                  'gap-1.5',
                  control.data.running
                    ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                    : 'text-muted-foreground',
                )}
              >
                <StatusDot tone={control.data.running ? 'live' : 'stopped'} size="xs" />
                {control.data.running ? 'Running' : 'Stopped'}
              </Badge>
            )}
            <Button
              variant="default"
              size="sm"
              onClick={onSave}
              disabled={!dirty || !values || hasErrors || save.isPending}
              title={hasErrors ? 'Fix the highlighted fields first' : undefined}
            >
              {save.isPending && <Spinner data-icon="inline-start" />}
              Save changes
            </Button>
          </div>
        }
      />

      {query.isLoading || !config || !values ? (
        <Skeleton className="mt-6 h-[420px] rounded-3xl" />
      ) : (
        <>
          <Card className="mt-4 flex flex-row flex-wrap items-center gap-3 border-primary/30 bg-primary/5 p-5">
            <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
              <Zap className="size-4.5" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-heading text-sm font-semibold text-foreground">
                  {activeSetup ? `${activeSetup.symbol} Strategy Status` : 'Strategy Status'}
                </h2>
                {activeSetup && (
                  <Badge variant="outline" className="border-primary/30 bg-primary/10 text-primary">
                    {activeSetup.name}
                  </Badge>
                )}
                <Badge
                  variant="outline"
                  className="border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                >
                  0% Maker Fee
                </Badge>
              </div>
              {activeSetup?.signature && (
                <p className="mt-1 text-[12px] text-muted-foreground">
                  {activeSetup.signature}
                </p>
              )}
            </div>
          </Card>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            {GROUPS.filter((g) => g.fields.length > 0).map((group) => {
              const Icon = group.icon
              return (
                <Card key={group.title} className={cn('gap-0 p-5', group.fields.length > 4 && 'lg:col-span-2')}>
                  <div className="flex items-center gap-3">
                    <span className={cn('grid size-8 shrink-0 place-items-center rounded-xl', TONES[group.tone])}>
                      <Icon className="size-4" aria-hidden="true" />
                    </span>
                    <h2 className="font-heading text-[15px] font-semibold text-foreground">{group.title}</h2>
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {group.fields.map((field) => {
                      const value = values[field.path] ?? 0
                      const fieldError = errorFor(field.path, value)
                      return (
                        <Field key={field.path} data-invalid={fieldError !== undefined || undefined} className="gap-1.5">
                          <div className="flex items-center justify-between gap-2">
                            <FieldLabel htmlFor={field.path} className="text-xs font-medium text-muted-foreground">
                              {field.label}
                            </FieldLabel>
                            {field.tip && (
                              <Tooltip>
                                <TooltipTrigger
                                  render={
                                    <button
                                      type="button"
                                      aria-label={`About ${field.label}`}
                                      className="inline-flex text-muted-foreground/70 transition-colors hover:text-foreground focus-visible:text-foreground"
                                    />
                                  }
                                >
                                  <Info className="size-3.5" aria-hidden="true" />
                                </TooltipTrigger>
                                <TooltipContent side="top" className="w-72 max-w-xs flex-col items-start p-3 text-left">
                                  {field.tip}
                                </TooltipContent>
                              </Tooltip>
                            )}
                          </div>
                          <InputGroup>
                            <InputGroupInput
                              id={field.path}
                              type="number"
                              step={field.step ?? 0.01}
                              value={value}
                              onChange={(event) => set(field.path, event.target.value)}
                              aria-invalid={fieldError !== undefined || undefined}
                              className="font-mono tabular-nums"
                            />
                            <InputGroupAddon align="inline-end">
                              <InputGroupButton
                                variant="ghost"
                                size="icon-xs"
                                aria-label={`Reset ${field.label} to default`}
                                title="Reset to default"
                                onClick={() => set(field.path, String(defaultValues[field.path] ?? 0))}
                              >
                                <RotateCcw className="size-3.5" aria-hidden="true" />
                              </InputGroupButton>
                            </InputGroupAddon>
                          </InputGroup>
                          {fieldError ? (
                            <FieldError className="text-xs">{fieldError}</FieldError>
                          ) : field.hint ? (
                            <FieldDescription className="text-xs">{field.hint}</FieldDescription>
                          ) : null}
                        </Field>
                      )
                    })}
                  </div>
                </Card>
              )
            })}
          </div>

          {hasErrors && (
            <p role="alert" className="mt-3 text-[12px] font-medium text-destructive">
              Some fields are out of range — Save is disabled until they are fixed.
            </p>
          )}

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <span className="font-mono text-xs text-muted-foreground">bot/config.json</span>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setDraft(null)}
                disabled={!dirty}
              >
                <RotateCcw data-icon="inline-start" /> Discard
              </Button>
              <Button
                variant="default"
                size="sm"
                onClick={onSave}
                disabled={!dirty || hasErrors || save.isPending}
                title={hasErrors ? 'Fix the highlighted fields first' : undefined}
              >
                {save.isPending && <Spinner data-icon="inline-start" />}
                Save changes
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
