/**
 * Shared server context — the singleton Prisma client + token store.
 *
 * The MCP uses a per-request McpServer instance (stateless Streamable HTTP), but
 * the datastore connection and the token cache must be process-wide singletons.
 * They live here and are initialised once at startup via initContext().
 */

import { PrismaClient } from '@prisma/client';
import { config } from './config.js';
import { PrismaTokenStore } from './zoho/tokenStore.js';
import { warmup } from './zoho/tokenManager.js';

export const prisma = new PrismaClient();
export const tokenStore = new PrismaTokenStore(prisma);

/** Called once at startup: warms the token cache from the datastore. */
export async function initContext(): Promise<void> {
    await warmup(prisma);
}

/** Closes datastore connections on shutdown. */
export async function disposeContext(): Promise<void> {
    await prisma.$disconnect();
}

/**
 * The scopes Zoho actually granted (space-separated string → array). Read from the
 * datastore, not from Zoho — Zoho records this on every refresh. Empty if not yet
 * bootstrapped or credentials are unconfigured.
 */
export async function getGrantedScopes(): Promise<string[]> {
    const { clientId, userMail } = config.zoho;
    if (!clientId || !userMail) return [];
    try {
        const row = await tokenStore.load(clientId, userMail);
        return row?.scopes ? row.scopes.split(' ').filter(Boolean) : [];
    } catch {
        return [];
    }
}
