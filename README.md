# dataexpert-mcp

Isolated MCP servers for the DataExpert platform. Each MCP has its own dependency
closure, build pipeline, and version.

See [`CONVENTIONS.md`](./CONVENTIONS.md) for the per-server layout and principles.

## Servers

| Server | Path | Status | Purpose |
|---|---|---|---|
| Zoho CRM | [`servers/zoho`](./servers/zoho) | Phase 0 (scaffold) | Stateless gateway to Zoho CRM — account/contact/email tools over Streamable HTTP. First server in the repo; sets the convention. |

## Quick start (a server)

```bash
cd servers/zoho
cp .env.example .env
npm install
npm run build
npm start
```
