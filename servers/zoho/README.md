# Zoho MCP server

A stateless **MCP (Model Context Protocol) gateway** to Zoho CRM. It owns all
Zoho-specific concerns — OAuth, token refresh, encryption, the HTTP client, field
mapping to a canonical shape, and rate-limit/error translation — and exposes them
as typed tools over Streamable HTTP. Consumers (the DataExpert CSM app today;
LLM agents / the Trend Engine later) speak one stable protocol and never touch
Zoho's API internals.

Background & design: `~/.claude/plans/lets-plan-for-the-witty-backus.md` in the
CSM repo, and the project memory `project_zoho_mcp_pivot`.

## Why direct HTTP (not the Zoho SDK)

The Zoho user is a non-admin who can only be granted three module READ scopes
(`accounts`, `contacts`, `emails`). The official SDK fetches field metadata on
every call, which needs `settings.fields.READ` — unobtainable. So the gateway
calls the Zoho v8 REST API directly; module-level scopes are enough.

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
cp .env.example .env          # fill in DATABASE_URL, Zoho creds, encryption key
npm install
npx prisma db push            # create the ZohoToken table in your dev DB
npm run build                 # prisma generate + tsc
# one-time: obtain a refresh token (grant token shell-only):
ZOHO_BOOTSTRAP_GRANT_TOKEN=1000.xxxx npm run bootstrap
npm start                     # serves :$MCP_PORT
```

Smoke-test the tools with the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector
# connect to http://127.0.0.1:3001/mcp, call auth_status → expect the 3 READ scopes
```

## Deployment

Runs as a sidecar container next to the CSM app, with its **own Postgres**
(`zoho-mcp-db`) holding only the encrypted `ZohoToken` row. The CSM app reaches it
at `http://zoho-mcp:3001/mcp` over the internal docker network. See the CSM repo's
`DEPLOYMENT.md` (added in the cutover phase) for compose + secret + version-pin
details.

### Production cutover note

At cutover you do **not** run `bootstrap`. You migrate the existing encrypted
`ZohoToken` row out of the CSM database and **carry the same
`ZOHO_TOKEN_ENCRYPTION_KEY`** over, so the `enc:v1:` token decrypts as-is and no
Zoho token slot is consumed.

## Scripts

- `npm run build` — `prisma generate` + `tsc`
- `npm start` — run compiled server (`dist/server.js`)
- `npm run dev` — watch mode (`tsx`)
- `npm run typecheck` — `tsc --noEmit`
- `npm run bootstrap` — one-time OAuth grant-token exchange
