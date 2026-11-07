# CRM

A complete, single-workspace CRM: overview dashboard, contacts, companies, a
drag-and-drop deal board, tasks, notes and file attachments. It runs on
Freebuff Sites with Sign in with Freebuff, D1 for data and R2 for files, and
every record is scoped to the signed-in user.

## Run it

```sh
bun install
bun run dev        # http://localhost:5173 with local D1 and R2 (Miniflare)
bun run build      # dist/client (assets) + dist/crm/index.js (Worker)
```

On localhost without a `FREEBUFF_CLIENT_ID`, the app signs you in as a local
development user so everything works before auth is provisioned. A new
workspace is seeded with sample data; Settings can restore or clear it.

## Connect it to Freebuff

1. `sites_create`, then `sites_add_storage` for D1 named `DB` and R2 named `FILES`.
2. `sites_enable_auth` (pass `http://localhost:5173` as the local origin while
   developing). Copy the development variables into `.dev.vars` (see
   `.dev.vars.example`) to use real accounts locally.
3. `bun run build`, then `sites_deploy` with `deploy.json`. The deploy injects
   `FREEBUFF_CLIENT_ID`, `FREEBUFF_ISSUER` and `APP_ORIGIN`, and attaches the
   `DB` and `FILES` bindings.

If a binding is missing the app says so instead of failing: Settings shows what
is connected, and file uploads are hidden until R2 is attached.

## Where things are

- `src/worker/` is the Hono API. `db.ts` owns the schema (created on first
  request), `seed.ts` the sample data, `auth.ts` the Freebuff integration and
  the loopback-only development user, `routes/*` the endpoints.
- `src/app/` is the React app. `components/ui.tsx` holds the primitives
  (buttons, inputs, dialogs, drawer, menus, toasts); `pages/*` the screens;
  `lib/api.ts` the data hooks (TanStack Query).
- `src/shared/types.ts` is the contract between the two.
- `src/styles.css` holds the design tokens. Everything rounded is a squircle
  via `corner-shape`; true circles use the `round` class.

## Security notes

Every `/api/*` route requires a signed-in user and scopes queries by
`owner_sub`. Mutations must be same-origin (`isSameOriginRequest`). Files are
addressed by database row, never by R2 key, so one user cannot read another's.
Personalised responses are `Cache-Control: private, no-store`.
