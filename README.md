# dataexpert-mcp

Isolated MCP servers for the DataExpert platform. Each server owns its dependency
closure, build pipeline, configuration, and version so integrations can be
developed and deployed independently.

See [CONVENTIONS.md](./CONVENTIONS.md) for the per-server layout and principles.

## Servers

| Server | Path | Runtime | Status | Purpose |
|---|---|---|---|---|
| Nuix Automate | [servers/nuix-mcp](./servers/nuix-mcp) | Python 3.11+ | Active | MCP tools for Nuix Automate jobs, workflows, case sessions, searches, file libraries, and OpenAPI-assisted endpoint discovery. |
| Memgraph | [servers/memgraph-mcp](./servers/memgraph-mcp) | Python 3.11+ | Active | Evidence and context graph tools over Memgraph, including graph queries, entity/path lookup, hypotheses, findings, action cards, and case-scoped upserts. |
| GraphAware Hume | [servers/graphaware-mcp](./servers/graphaware-mcp) | Python 3.11+ | Active | Hume stack operations, health checks, and authenticated REST API passthrough tools. |
| Agentic Chat Deploy | [servers/agentic-chat-deploy-mcp](./servers/agentic-chat-deploy-mcp) | Python 3.11+ | Active | Day-2 deployment of the agentic-chat app over SSH: inventory lookup, status, and ref update + service restart. |
| DataExpert vSphere Lab | [servers/vsphere-lab-mcp](./servers/vsphere-lab-mcp) | Python 3.11+ | Phase 0 | Standard MCP interface for vSphere lab planning, preflight, provisioning, SSH readiness, inventory, final-network moves, and run evidence. It stops before product deployment. |
| Zoho CRM | [servers/zoho-mcp](./servers/zoho-mcp) | Node.js 20+ | Phase 0 | Stateless gateway to Zoho CRM account/contact/email tools over Streamable HTTP. |

## Configuration

Copy the shared environment template and fill in local secrets outside git:

```bash
mkdir -p security
cp secrets.env.example security/secrets.env
```

Each server reads only the settings it needs. Keep real credentials in
`security/secrets.env` or the server-local `.env` files described by that
server's README.

## Python Servers

Install and run a Python MCP server from its directory:

```bash
cd servers/nuix-mcp
python -m pip install -e .
dataexpert-nuix-mcp
```

The same pattern applies to:

```bash
cd servers/memgraph-mcp && python -m pip install -e . && dataexpert-memgraph-mcp
cd servers/graphaware-mcp && python -m pip install -e . && dataexpert-graphaware-mcp
cd servers/agentic-chat-deploy-mcp && python -m pip install -e . && dataexpert-agentic-chat-deploy-mcp
cd servers/vsphere-lab-mcp && python -m pip install -e . && dataexpert-vsphere-lab-mcp
```

## vSphere Lab Server

The DataExpert vSphere Lab MCP is the standard agent-facing contract for lab VM
readiness. It accepts structured topology JSON payloads, uses server-local
credential profiles, requires exact confirmation tokens for live mutations, and
returns structured Run Evidence references plus inline Ansible inventory content
when available.

Authoritative project topologies stay in the consuming project repository. This
repo only owns the MCP implementation and examples/templates. See
[servers/vsphere-lab-mcp/README.md](./servers/vsphere-lab-mcp/README.md).

Product and service deployment stays in the consuming project or a narrow deploy
server such as [servers/agentic-chat-deploy-mcp](./servers/agentic-chat-deploy-mcp).

## Zoho Server

```bash
cd servers/zoho-mcp
cp .env.example .env
npm install
npm run build
npm start
```

For the first OAuth setup, follow [servers/zoho-mcp/README.md](./servers/zoho-mcp/README.md)
and run `npm run bootstrap` with a one-time Zoho grant token.
