import { useState } from 'react'

import { Avatar, Badge, Button, ConfirmDialog, Field, Input, PageHeader, useToast } from '../components/ui'
import { api, useApiMutation, useMe } from '../lib/api'

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

  return (
    <div className="mx-auto max-w-[720px] p-5 sm:p-8">
      <PageHeader title="Settings" />

      <section className="mt-8">
        <h2 className="text-[14px] font-semibold">Account</h2>
        <div className="mt-3 flex items-center gap-4 rounded-card border border-line p-4">
          <Avatar name={me.user.name ?? me.user.email ?? 'You'} hue={210} src={me.user.picture} size={48} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-medium">{me.user.name ?? 'Signed in'}</p>
            {me.user.email && <p className="truncate text-[13px] text-muted">{me.user.email}</p>}
          </div>
          {me.capabilities.auth === 'freebuff' ? (
            <form method="post" action="/auth/freebuff/signout">
              <input type="hidden" name="returnTo" value="/" />
              <Button type="submit">Sign out</Button>
            </form>
          ) : (
            <Badge tone="warning">Development user</Badge>
          )}
        </div>
        {me.capabilities.auth === 'development' && (
          <p className="mt-2 text-[12.5px] text-faint">Sign in with Freebuff is not configured yet. Run the app with FREEBUFF_CLIENT_ID set to use real accounts.</p>
        )}
      </section>

      <section className="mt-8">
        <h2 className="text-[14px] font-semibold">Workspace</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (value.trim() && value !== me.workspace.name) rename.mutate(value.trim())
          }}
          className="mt-3 flex items-end gap-2"
        >
          <Field label="Name" className="flex-1">
            <Input value={value} onChange={(e) => setName(e.target.value)} maxLength={60} />
          </Field>
          <Button variant="primary" type="submit" loading={rename.isPending} disabled={!value.trim() || value === me.workspace.name}>
            Save
          </Button>
        </form>
      </section>

      <section className="mt-8">
        <h2 className="text-[14px] font-semibold">Connections</h2>
        <ul className="mt-3 divide-y divide-line rounded-card border border-line">
          {[
            ['Database', me.capabilities.database, 'D1 via the DB binding'],
            ['File storage', me.capabilities.files, 'R2 via the FILES binding'],
            ['Sign in with Freebuff', me.capabilities.auth === 'freebuff', 'FREEBUFF_CLIENT_ID'],
          ].map(([label, ok, detail]) => (
            <li key={label as string} className="flex h-13 items-center gap-3 px-4">
              <span className="min-w-0 flex-1">
                <span className="block text-[13.5px] font-medium">{label}</span>
                <span className="block truncate text-[12px] text-faint">{detail}</span>
              </span>
              <Badge tone={ok ? 'success' : 'neutral'} dot>
                {ok ? 'Connected' : 'Not connected'}
              </Badge>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-8">
        <h2 className="text-[14px] font-semibold">Data</h2>
        <div className="mt-3 divide-y divide-line rounded-card border border-line">
          <div className="flex items-center gap-3 p-4">
            <span className="min-w-0 flex-1">
              <span className="block text-[13.5px] font-medium">Restore sample data</span>
              <span className="block text-[12.5px] text-muted">Replaces everything with the starter companies, contacts and deals.</span>
            </span>
            <Button onClick={() => setConfirm('reset')}>Restore</Button>
          </div>
          <div className="flex items-center gap-3 p-4">
            <span className="min-w-0 flex-1">
              <span className="block text-[13.5px] font-medium">Clear workspace</span>
              <span className="block text-[12.5px] text-muted">Deletes every record and file. This cannot be undone.</span>
            </span>
            <Button variant="danger" onClick={() => setConfirm('clear')}>
              Clear
            </Button>
          </div>
        </div>
      </section>

      <ConfirmDialog
        open={confirm === 'reset'}
        onClose={() => setConfirm(null)}
        onConfirm={() => reset.mutate(undefined)}
        loading={reset.isPending}
        title="Restore sample data?"
        description="Everything in the workspace is replaced with the starter data."
        confirmLabel="Restore"
      />
      <ConfirmDialog
        open={confirm === 'clear'}
        onClose={() => setConfirm(null)}
        onConfirm={() => clear.mutate(undefined)}
        loading={clear.isPending}
        title="Clear the workspace?"
        description="Every contact, company, deal, task, note and file is deleted."
        confirmLabel="Clear everything"
      />
    </div>
  )
}
