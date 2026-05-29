# Repo conventions

This repo hosts **isolated MCP servers for the DataExpert platform**. Each server
is self-contained: its own dependency closure, build pipeline, datastore, and
version. The Zoho server (`servers/zoho/`) is the first, and sets the pattern below.

## Layout

```
servers/
  <integration>/
    package.json        # own deps + scripts; name "@dataexpert-mcp/<integration>"
    tsconfig.json       # ESM, NodeNext, strict, src → dist
    Dockerfile          # multi-stage; non-root runtime; HEALTHCHECK
    .env.example        # authoritative env template (this server owns its secrets)
    prisma/             # only if the server needs its own datastore
    src/
      config.ts         # env → typed config; owns integration-specific URLs
      server.ts         # Streamable HTTP entrypoint (POST /mcp, GET /healthz)
      <integration>/    # the gateway internals (HTTP client, auth, mappers, errors)
      tools/            # MCP tool registration + handlers
    README.md
```

## Principles

1. **Stateless gateway.** A server owns the integration's auth, mapping, rate
   limits, and error translation — nothing about a consuming app's domain. If
   logic needs a *consumer's* database row, it belongs in the consumer, not here.
2. **Canonical shapes.** Tool outputs are clean and source-faithful; they do not
   bake in any one consumer's presentation rules.
3. **Transport: Streamable HTTP**, stateless, `POST /mcp`. `GET /healthz` is a
   cheap liveness probe that must not call the upstream API.
4. **Structured errors.** Failed tools return `{ isError: true, structuredContent:
   { error: { kind, message, retryAfterSeconds? } } }` so deterministic clients
   can branch precisely.
5. **Secrets are the server's.** Each server owns its own `.env`/datastore. A
   compromise of a consumer must not yield the integration's credentials.
6. **Own version + build.** Each server is independently versioned and built into
   an immutable image; consumers pin a version, never `latest`.
