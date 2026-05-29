/**
 * Registers the Zoho tools on an McpServer instance.
 *
 * Each tool: a name, a one-line description, a Zod input schema (validated by the
 * SDK before the handler runs), and a handler that returns a canonical payload.
 *
 * Error contract: a failed tool returns `{ isError: true }` with a structured
 * `{ error: { kind, message, retryAfterSeconds? } }`. The `kind` lets the CSM
 * client reconstruct its ZohoAuthError / ZohoRateLimitError branching, so the
 * frozen /api/zoho/* route error bodies survive the move behind the gateway.
 */

import { z } from 'zod';
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { ZohoAuthError, ZohoRateLimitError } from '../zoho/errors.js';
import {
    doSearchAccounts,
    doGetAccount,
    doUpdateAccount,
    doAuthStatus,
} from './handlers.js';

type ToolResult = {
    content: Array<{ type: 'text'; text: string }>;
    structuredContent?: Record<string, unknown>;
    isError?: boolean;
};

type ErrorKind = 'auth' | 'rate_limit' | 'invalid_data' | 'transient';

/** Wrap a successful payload as an MCP tool result. */
function ok(payload: object): ToolResult {
    return {
        content: [{ type: 'text', text: JSON.stringify(payload) }],
        // Handler payloads are named interfaces, which lack an implicit index
        // signature; the runtime shape is a plain JSON object, so this cast is safe.
        structuredContent: payload as Record<string, unknown>,
    };
}

/** Translate a thrown error into a structured tool error result. */
function fail(err: unknown): ToolResult {
    let kind: ErrorKind = 'transient';
    let retryAfterSeconds: number | undefined;

    if (err instanceof ZohoAuthError) {
        kind = 'auth';
    } else if (err instanceof ZohoRateLimitError) {
        kind = 'rate_limit';
        retryAfterSeconds = err.retryAfterSeconds;
    }

    const error = {
        kind,
        message: err instanceof Error ? err.message : String(err),
        ...(retryAfterSeconds !== undefined ? { retryAfterSeconds } : {}),
    };

    return {
        content: [{ type: 'text', text: JSON.stringify({ error }) }],
        structuredContent: { error },
        isError: true,
    };
}

// Reused validators.
const zohoIdSchema = z
    .string()
    .regex(/^\d+$/, 'zohoId must be a numeric string (Zoho record IDs are digits only)');

export function registerZohoTools(server: McpServer): void {
    server.registerTool(
        'search_accounts',
        {
            title: 'Search Zoho accounts',
            description:
                'Search Zoho CRM accounts by name (word search). Returns lean canonical results; pairing/annotation is the caller’s responsibility.',
            inputSchema: {
                q: z.string().min(2).max(100).describe('Search term (2–100 chars). Zoho rejects 1-char queries.'),
                perPage: z.number().int().positive().max(200).optional().describe('Max results (default 25).'),
            },
        },
        async (args): Promise<ToolResult> => {
            try {
                return ok(await doSearchAccounts(args));
            } catch (err) {
                return fail(err);
            }
        },
    );

    server.registerTool(
        'get_account',
        {
            title: 'Get a Zoho account',
            description:
                'Fetch a single Zoho CRM account by record ID. Returns the canonical account, or { account: null } if not found.',
            inputSchema: {
                zohoId: zohoIdSchema.describe('The Zoho account record ID.'),
            },
        },
        async (args): Promise<ToolResult> => {
            try {
                return ok(await doGetAccount(args));
            } catch (err) {
                return fail(err);
            }
        },
    );

    server.registerTool(
        'update_account',
        {
            title: 'Update a Zoho account',
            description:
                'Update fields on a Zoho CRM account (partial update — only provided fields are written; this is a dumb pipe, the caller owns conflict policy). Returns the per-record Zoho result code.',
            inputSchema: {
                zohoId: zohoIdSchema.describe('The Zoho account record ID to update.'),
                fields: z
                    .object({
                        name: z.string().optional(),
                        website: z.string().optional(),
                        industry: z.string().optional(),
                        nextStep: z.string().optional(),
                    })
                    .describe('Canonical fields to write. website is a full URL. Omitted/empty fields are not touched.'),
            },
        },
        async (args): Promise<ToolResult> => {
            try {
                return ok(await doUpdateAccount(args));
            } catch (err) {
                return fail(err);
            }
        },
    );

    server.registerTool(
        'auth_status',
        {
            title: 'Zoho auth status',
            description:
                'Report whether the gateway can reach Zoho (live probe) and which OAuth scopes were granted.',
            inputSchema: {},
        },
        async (): Promise<ToolResult> => {
            // doAuthStatus never throws — it reports failure in its payload.
            return ok(await doAuthStatus());
        },
    );
}
