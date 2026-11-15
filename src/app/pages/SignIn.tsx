import { ArrowRight, Database, ShieldCheck, Terminal } from 'lucide-react'
import { motion } from 'motion/react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import { Separator } from '@/components/ui/separator'

const deskMetrics = [
  { label: 'Paper Equity', value: '$12,480', tone: 'text-primary' },
  { label: 'Pair Avg Cost', value: '$0.962', tone: 'text-emerald-600 dark:text-emerald-400' },
  { label: 'Window Win Rate', value: '61.4%', tone: 'text-foreground' },
]

const deskFeed = [
  {
    code: 'HC',
    title: 'HAPCS-v1 Core',
    subtitle: 'BTC 5m Up/Down · Pair cap $0.970',
    stat: '+$184.20',
    badge: 'Active',
  },
  {
    code: 'AB',
    title: 'Variant B · Tight Spread',
    subtitle: 'A/B control · Skew guard enabled',
    stat: '+$92.50',
    badge: 'Testing',
  },
  {
    code: 'WN',
    title: 'Window #4182 Redeemed',
    subtitle: 'Matched Up/Down legs · Delta neutral',
    stat: '100% Fill',
    badge: 'Settled',
  },
]

// Shown when /api/me returns 401. Sign-in is a plain link to the SDK route; the
// Worker (not this page) decides who is signed in.
export function SignIn() {
  const returnTo = encodeURIComponent(`${window.location.pathname}${window.location.search}`)

  return (
    <div className="h-full overflow-y-auto bg-background text-foreground">
      <div className="grid min-h-full lg:grid-cols-2">
        <div className="flex flex-col justify-between gap-10 p-6 sm:p-10 lg:p-14">
          <div className="flex items-center gap-2.5">
            <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-primary text-primary-foreground shadow-xs">
              <span className="text-sm leading-none font-bold">🎯</span>
            </span>
            <span className="font-heading text-base font-semibold tracking-tight">Up/Down desk</span>
            <Badge variant="secondary" className="font-mono text-[10px] tracking-wider uppercase">
              BTC Paper Bot
            </Badge>
          </div>

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
            className="flex max-w-md flex-col items-start gap-5"
          >
            <Badge variant="outline" className="font-mono text-[11px]">
              HAPCS-v1 · Paper Simulation Workspace
            </Badge>
            <div className="flex flex-col gap-3">
              <h1 className="font-heading text-4xl font-semibold tracking-tight text-balance sm:text-[42px] sm:leading-[1.08]">
                Deterministic BTC prediction desk, built for clarity.
              </h1>
              <p className="text-base leading-relaxed text-muted-foreground">
                Monitor live 5-minute Up/Down windows, inspect pair-cost mechanics, and benchmark
                A/B strategy changes without ever exposing wallet keys.
              </p>
            </div>

            <div className="flex flex-col items-start gap-3 pt-2">
              <Button
                size="lg"
                nativeButton={false}
                render={<a href={`/auth/freebuff/signin?returnTo=${returnTo}`} />}
              >
                <span className="grid size-5 place-items-center rounded-md bg-primary-foreground/20 font-mono text-[11px] font-bold">
                  F
                </span>
                <span>Sign in with Freebuff</span>
                <ArrowRight data-icon="inline-end" />
              </Button>
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <ShieldCheck className="size-3.5 shrink-0 text-primary" />
                <span>Uses your Freebuff account. Paper only — the loop never holds keys or funding.</span>
              </p>
            </div>
          </motion.div>

          <p className="text-xs text-muted-foreground">
            © {new Date().getFullYear()} Up/Down desk · BTC Paper Trading Lab
          </p>
        </div>

        <div className="relative hidden items-center justify-center overflow-hidden border-l border-border bg-muted/40 p-10 lg:flex">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_50%_at_70%_25%,oklch(0.646_0.222_41.116/0.14),transparent),radial-gradient(45%_45%_at_25%_80%,oklch(0.715_0.143_215.221/0.12),transparent)]" />

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.12, ease: [0.22, 1, 0.36, 1] }}
            className="relative w-full max-w-[540px]"
          >
            <Card className="border border-border/80 shadow-xl">
              <CardHeader>
                <CardTitle>Live Desk Snapshot</CardTitle>
                <CardDescription className="font-mono text-xs">
                  HAPCS-v1 · BTC-USD 5m paper loop
                </CardDescription>
                <CardAction>
                  <Badge variant="secondary" className="font-mono text-[10px] uppercase">
                    Paper Mode
                  </Badge>
                </CardAction>
              </CardHeader>

              <CardContent className="flex flex-col gap-4">
                <div className="grid grid-cols-3 gap-3">
                  {deskMetrics.map((metric) => (
                    <div
                      key={metric.label}
                      className="rounded-xl border border-border/60 bg-muted/40 p-3"
                    >
                      <p className="text-xs text-muted-foreground">{metric.label}</p>
                      <p
                        className={`mt-1 font-mono text-lg font-semibold tracking-tight tabular-nums ${metric.tone}`}
                      >
                        {metric.value}
                      </p>
                    </div>
                  ))}
                </div>

                <Separator />

                <ul className="flex flex-col gap-3">
                  {deskFeed.map((item) => (
                    <li key={item.title} className="flex items-center gap-3">
                      <Avatar size="sm">
                        <AvatarFallback className="font-mono text-[11px] font-semibold">
                          {item.code}
                        </AvatarFallback>
                      </Avatar>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{item.title}</p>
                        <p className="truncate text-xs text-muted-foreground">{item.subtitle}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-medium tabular-nums">
                          {item.stat}
                        </span>
                        <Badge variant="outline" className="text-[11px]">
                          {item.badge}
                        </Badge>
                      </div>
                    </li>
                  ))}
                </ul>
              </CardContent>

              <CardFooter className="justify-between border-t text-xs text-muted-foreground">
                <span>Zero custodial risk</span>
                <span className="font-mono">Sign in to open workspace</span>
              </CardFooter>
            </Card>
          </motion.div>
        </div>
      </div>
    </div>
  )
}

export function SetupNeeded({ message }: { message: string }) {
  return (
    <div className="flex h-full items-center justify-center overflow-y-auto bg-background p-6 text-foreground">
      <Card className="w-full max-w-lg border border-border">
        <CardContent>
          <Empty className="p-6">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Database />
              </EmptyMedia>
              <EmptyTitle>Almost there</EmptyTitle>
              <EmptyDescription>{message}</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Alert>
                <Terminal />
                <AlertTitle>Worker bindings required</AlertTitle>
                <AlertDescription>
                  In Freebuff, ask the agent to add D1 storage named DB and R2 storage named FILES,
                  then deploy again.
                </AlertDescription>
              </Alert>
            </EmptyContent>
          </Empty>
        </CardContent>
      </Card>
    </div>
  )
}
