import { useState } from 'react'

import { PageHeader, useToast } from '../components/ui'
import { StatusDot } from '../components/StatusDot'
import { api, useApiMutation, useMe } from '../lib/api'
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
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Field, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'

export function Settings() {
  const { data: me } = useMe()
  const toast = useToast()
  const [name, setName] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<'reset' | 'clear' | null>(null)

  const rename = useApiMutation((value: string) => api('/workspace', { method: 'PATCH', json: { name: value } }), ['me'], {
    onSuccess: () => toast('Workspace renamed'),
  })
  const reset = useApiMutation(() => api('/workspace/reset', { method: 'POST' }), ['me', 'overview', 'contacts', 'companies', 'deals', 'tasks'], {
    onSuccess: () => {
      setConfirm(null)
      toast('Sample data restored')
    },
  })
  const clear = useApiMutation(() => api('/workspace/data', { method: 'DELETE' }), ['me', 'overview', 'contacts', 'companies', 'deals', 'tasks'], {
    onSuccess: () => {
      setConfirm(null)
      toast('Workspace cleared')
    },
  })

  if (!me) return null
  const value = name ?? me.workspace.name
  const initials = (me.user.name ?? me.user.email ?? 'You').slice(0, 2).toUpperCase()

  return (
    <div className="mx-auto max-w-[720px] p-5 sm:p-8">
      <PageHeader title="Settings" />

      <section className="mt-8">
        <h2 className="font-heading text-sm font-semibold text-foreground">Account</h2>
        <Card className="mt-3 flex flex-row items-center gap-4 p-4">
          <Avatar size="lg" className="size-12">
            <AvatarImage src={me.user.picture ?? undefined} alt={me.user.name ?? 'You'} />
            <AvatarFallback className="font-semibold text-foreground">{initials}</AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-medium text-foreground">{me.user.name ?? 'Signed in'}</p>
            {me.user.email && <p className="truncate text-[13px] text-muted-foreground">{me.user.email}</p>}
          </div>
          {me.capabilities.auth === 'freebuff' ? (
            <form method="post" action="/auth/freebuff/signout">
              <input type="hidden" name="returnTo" value="/" />
              <Button variant="outline" size="sm" type="submit">
                Sign out
              </Button>
            </form>
          ) : (
            <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400">
              Development user
            </Badge>
          )}
        </Card>
        {me.capabilities.auth === 'development' && (
          <p className="mt-2 text-[12.5px] text-muted-foreground">
            Sign in with Freebuff is not configured yet. Run the app with FREEBUFF_CLIENT_ID set to use real accounts.
          </p>
        )}
      </section>

      <section className="mt-8">
        <h2 className="font-heading text-sm font-semibold text-foreground">Workspace</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (value.trim() && value !== me.workspace.name) rename.mutate(value.trim())
          }}
          className="mt-3 flex items-end gap-2"
        >
          <Field className="flex-1 gap-1.5">
            <FieldLabel htmlFor="workspace-name">Name</FieldLabel>
            <Input
              id="workspace-name"
              value={value}
              onChange={(e) => setName(e.target.value)}
              maxLength={60}
            />
          </Field>
          <Button
            variant="default"
            type="submit"
            disabled={rename.isPending || !value.trim() || value === me.workspace.name}
          >
            {rename.isPending && <Spinner data-icon="inline-start" />}
            Save
          </Button>
        </form>
      </section>

      <section className="mt-8">
        <h2 className="font-heading text-sm font-semibold text-foreground">Connections</h2>
        <Card className="mt-3 gap-0 overflow-hidden p-0">
          <ul className="divide-y divide-border">
            {[
              ['Database', me.capabilities.database, 'D1 via the DB binding'],
              ['File storage', me.capabilities.files, 'R2 via the FILES binding'],
              ['Sign in with Freebuff', me.capabilities.auth === 'freebuff', 'FREEBUFF_CLIENT_ID'],
            ].map(([label, ok, detail]) => (
              <li key={label as string} className="flex h-14 items-center gap-3 px-4">
                <span className="min-w-0 flex-1">
                  <span className="block text-[13.5px] font-medium text-foreground">{label}</span>
                  <span className="block truncate text-[12px] text-muted-foreground">{detail}</span>
                </span>
                <Badge
                  variant="outline"
                  className={cn(
                    'gap-1.5',
                    ok
                      ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                      : 'text-muted-foreground',
                  )}
                >
                  <StatusDot tone={ok ? 'live' : 'stopped'} size="xs" />
                  {ok ? 'Connected' : 'Not connected'}
                </Badge>
              </li>
            ))}
          </ul>
        </Card>
      </section>

      <section className="mt-8">
        <h2 className="font-heading text-sm font-semibold text-foreground">Data</h2>
        <Card className="mt-3 gap-0 divide-y divide-border overflow-hidden p-0">
          <div className="flex items-center gap-3 p-4">
            <span className="min-w-0 flex-1">
              <span className="block text-[13.5px] font-medium text-foreground">Restore sample data</span>
              <span className="block text-[12.5px] text-muted-foreground">
                Replaces everything with the starter companies, contacts and deals.
              </span>
            </span>
            <Button variant="outline" size="sm" onClick={() => setConfirm('reset')}>
              Restore
            </Button>
          </div>
          <div className="flex items-center gap-3 p-4">
            <span className="min-w-0 flex-1">
              <span className="block text-[13.5px] font-medium text-foreground">Clear workspace</span>
              <span className="block text-[12.5px] text-muted-foreground">
                Deletes every record and file. This cannot be undone.
              </span>
            </span>
            <Button variant="destructive" size="sm" onClick={() => setConfirm('clear')}>
              Clear
            </Button>
          </div>
        </Card>
      </section>

      <AlertDialog open={confirm === 'reset'} onOpenChange={(open) => !open && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Restore sample data?</AlertDialogTitle>
            <AlertDialogDescription>
              Everything in the workspace is replaced with the starter data.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={reset.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => reset.mutate(undefined)} disabled={reset.isPending}>
              {reset.isPending && <Spinner data-icon="inline-start" />}
              Restore
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirm === 'clear'} onOpenChange={(open) => !open && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Clear the workspace?</AlertDialogTitle>
            <AlertDialogDescription>
              Every contact, company, deal, task, note and file is deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={clear.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => clear.mutate(undefined)}
              disabled={clear.isPending}
            >
              {clear.isPending && <Spinner data-icon="inline-start" />}
              Clear everything
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
