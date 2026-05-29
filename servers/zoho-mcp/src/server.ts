/**
 * Zoho MCP server — Streamable HTTP entrypoint.
 *
 * Transport choice (plan decision #4): Streamable HTTP, NOT stdio. The gateway is
 * a long-lived sidecar container the CSM app reaches over the internal docker
 * network at http://zoho-mcp:<port>/mcp. stdio would re-couple lifecycles.
 *
 * Session model: stateless. Each POST /mcp gets a fresh McpServer + transport.
 * The token cache (tokenManager) is a module-level singleton, so it survives
 * across requests regardless. There is no database — the refresh token comes from
 * the env (secrets.env), the access token is cached in memory.
 *
 * /healthz is a cheap liveness probe that does NOT call Zoho — a 30s healthcheck
 * must never burn Zoho's daily API quota.
 */

import express, { type Request, type Response } from 'express';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { config } from './config.js';
import { isConfigured } from './zoho/tokenManager.js';
import { registerZohoTools } from './tools/register.js';

const SERVER_NAME = 'zoho-mcp';
const SERVER_VERSION = '0.1.0';
const GIT_SHA = process.env.GIT_SHA ?? 'dev';

/** Build a fresh MCP server with the Zoho tools registered. */
function buildMcpServer(): McpServer {
    const server = new McpServer({ name: SERVER_NAME, version: SERVER_VERSION });
    registerZohoTools(server);
    return server;
}

async function main(): Promise<void> {
    if (!isConfigured()) {
        // Non-fatal: the server still boots and /healthz works, but tools will
        // error until ZOHO_CLIENT_ID/SECRET/REFRESH_TOKEN are set in the env.
        console.warn('[zoho-mcp] Zoho credentials not fully configured (need ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN) — tools will error until set.');
    }

    const app = express();
    app.use(express.json());

    // Liveness — no Zoho call. Surfaces version so the CSM deploy guard can assert
    // the running gateway matches the pinned version.
    app.get('/healthz', (_req: Request, res: Response) => {
        res.status(200).json({ status: 'ok', service: SERVER_NAME, version: SERVER_VERSION, gitSha: GIT_SHA });
    });

    // The MCP endpoint — stateless: a new server + transport per request.
    app.post('/mcp', async (req: Request, res: Response) => {
        const server = buildMcpServer();
        const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
        res.on('close', () => {
            void transport.close();
            void server.close();
        });
        try {
            await server.connect(transport);
            await transport.handleRequest(req, res, req.body);
        } catch (err) {
            console.error('[zoho-mcp] Error handling MCP request:', err);
            if (!res.headersSent) {
                res.status(500).json({
                    jsonrpc: '2.0',
                    error: { code: -32603, message: 'Internal server error' },
                    id: null,
                });
            }
        }
    });

    // Stateless mode doesn't support the SSE GET stream or session DELETE.
    const methodNotAllowed = (_req: Request, res: Response) => {
        res.status(405).json({
            jsonrpc: '2.0',
            error: { code: -32000, message: 'Method not allowed (stateless server).' },
            id: null,
        });
    };
    app.get('/mcp', methodNotAllowed);
    app.delete('/mcp', methodNotAllowed);

    const httpServer = app.listen(config.mcp.port, () => {
        console.log(`[zoho-mcp] Listening on :${config.mcp.port} (v${SERVER_VERSION}, ${GIT_SHA}) — DC=${config.zoho.dc}`);
    });

    // Graceful shutdown — give in-flight requests a moment, then force.
    const shutdown = (signal: string) => {
        console.log(`[zoho-mcp] ${signal} received — shutting down.`);
        httpServer.close(() => process.exit(0));
        setTimeout(() => process.exit(0), 5000).unref();
    };
    process.on('SIGTERM', () => shutdown('SIGTERM'));
    process.on('SIGINT', () => shutdown('SIGINT'));
}

main().catch((err) => {
    console.error('[zoho-mcp] Fatal startup error:', err);
    process.exit(1);
});
