# Zoho MCP server

A self-contained **MCP (Model Context Protocol) gateway** to Zoho CRM. It owns all
Zoho-specific concerns — OAuth token refresh, the HTTP client, field mapping to a
canonical shape, and rate-limit/error translation — and exposes them as typed tools
over Streamable HTTP. Consumers (the DataExpert CSM app today; LLM agents / the
Trend Engine later) speak one stable protocol and never touch Zoho's API internals.

It sits beside the other servers in this repo (`servers/zoho-mcp/`) but is fully
**independent** — its own dependency closure, no `core_engine` import, no database.

## Why direct HTTP (not the Zoho SDK)

The Zoho user is a non-admin who can only be granted three module READ scopes
(`accounts`, `contacts`, `emails`). The official SDK fetches field metadata on
every call, which needs `settings.fields.READ` — unobtainable. So the gateway
calls the Zoho v8 REST API directly; module-level scopes are enough.

## No database — token handling

Zoho's **refresh token is long-lived and stable** (Zoho returns the same one on
every refresh), so it lives in the env as `ZOHO_REFRESH_TOKEN` — like the other
servers' static credentials. The short-lived **access token** is cached in memory
and refreshed on demand. No Postgres, no Prisma, no encryption-at-rest layer.

## Tools

| Tool | Input | Output (canonical) |
|---|---|---|
| `search_accounts` | `{ q (2–100), perPage? }` | `{ results: [{ zohoId, name, website, industry }] }` |
| `get_account` | `{ zohoId }` | `{ account: { zohoId, name, website, industry, nextStep, modifiedTime } \| null }` |
| `update_account` | `{ zohoId, fields: { name?, website?, industry?, nextStep? } }` | `{ code, status, message, modifiedTime }` |
| `auth_status` | `{}` | `{ authenticated, scopes[], lastError }` |

- **Canonical shape** emits `website` (full URL), not a parsed hostname — the
  consumer applies its own presentation rules.
- `update_account` is a **dumb pipe**: it performs the PUT only. Read-before-write
  conflict policy ("Zoho wins") stays in the consumer.
- **Errors**: a failed tool returns `{ isError: true, structuredContent: { error:
  { kind, message, retryAfterSeconds? } } }` where `kind ∈ auth | rate_limit |
  invalid_data | transient`.

Endpoints: `POST /mcp` (Streamable HTTP, stateless) and `GET /healthz` (liveness;
no Zoho call).

## Local development

```bash
cp .env.example .env          # fill in ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET / ZOHO_DC
npm install
# one-time: obtain a refresh token (grant token shell-only). It PRINTS the token:
ZOHO_BOOTSTRAP_GRANT_TOKEN=1000.xxxx npm run bootstrap
# paste the printed ZOHO_REFRESH_TOKEN into .env
npm run build
npm start                     # serves :$MCP_PORT
```

Smoke-test the tools with the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector
# connect to http://127.0.0.1:3001/mcp, call auth_status → expect the 3 READ scopes
```

## Deployment

Runs as a container next to the CSM app; the CSM app reaches it at
`http://zoho-mcp:3001/mcp` over the internal docker network. Config (incl.
`ZOHO_REFRESH_TOKEN`) comes from the env / shared `secrets.env`. No database
service is required. See the CSM repo's cutover runbook for compose + version-pin
details.

## Scripts

- `npm run build` — `tsc`
- `npm start` — run compiled server (`dist/server.js`)
- `npm run dev` — watch mode (`tsx`)
- `npm run typecheck` — `tsc --noEmit`
- `npm run bootstrap` — one-time OAuth grant-token exchange (prints `ZOHO_REFRESH_TOKEN`)
