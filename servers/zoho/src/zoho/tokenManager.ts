/**
 * Zoho access-token manager — refresh-on-demand with in-memory cache and mutex.
 *
 * Ported from the CSM app (server/src/integrations/zoho/tokenManager.ts). Only the
 * config source (env → config) and the accounts base URL (now DC-derived) changed.
 *
 * - In-memory cache: a fresh access token is reused without a network round-trip.
 * - Mutex: if the token is expired, ONE caller refreshes and all others await it,
 *   so concurrent callers don't each POST to Zoho's token endpoint.
 *
 * The cache is module-level state, so it survives across MCP requests even when
 * the server uses a per-request McpServer instance (stateless transport).
 */

import { PrismaClient } from '@prisma/client';
import { config } from '../config.js';
import { PrismaTokenStore } from './tokenStore.js';
import { ZohoAuthError } from './errors.js';

let cachedToken: string | null = null;
let cacheExpiry: Date | null = null;
let refreshInFlight: Promise<string> | null = null;
let store: PrismaTokenStore | null = null;

const EXPIRE_BUFFER_SECONDS = 60;

function isTokenFresh(): boolean {
    if (!cachedToken || !cacheExpiry) return false;
    return cacheExpiry.getTime() - Date.now() > EXPIRE_BUFFER_SECONDS * 1000;
}

/**
 * POST to Zoho's token endpoint with our stored refresh token.
 * Returns the new access token and writes it back to the DB.
 */
async function performRefresh(): Promise<string> {
    if (!store) {
        throw new ZohoAuthError('[tokenManager] Store not initialized. Call warmup() first.');
    }

    const { clientId, clientSecret, userMail } = config.zoho;
    if (!clientId || !clientSecret || !userMail) {
        throw new ZohoAuthError('[tokenManager] Zoho credentials not configured.');
    }

    const row = await store.load(clientId, userMail);
    if (!row) {
        throw new ZohoAuthError('[tokenManager] No ZohoToken row found. Run bootstrap first.');
    }

    const body = new URLSearchParams({
        grant_type: 'refresh_token',
        client_id: clientId,
        client_secret: clientSecret,
        refresh_token: row.refreshToken,
    });

    const response = await fetch(`${config.zoho.accountsBase}/oauth/v2/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
    });

    const data = await response.json() as Record<string, unknown>;

    if (!response.ok) {
        throw new ZohoAuthError(
            `[tokenManager] Zoho refresh failed: HTTP ${response.status} ${response.statusText} — ` +
            `${data.error ?? data.code ?? '<no error code>'}: ${data.error_description ?? data.message ?? '<no message>'}`
        );
    }

    if (data.error) {
        throw new ZohoAuthError(
            `[tokenManager] Zoho token refresh failed: ${data.error} — ${data.error_description ?? '(no description)'}`
        );
    }

    const accessToken = data.access_token;
    const expiresIn = data.expires_in;
    const scopesRaw = data.scope;

    if (typeof accessToken !== 'string' || !accessToken) {
        throw new ZohoAuthError('[tokenManager] Zoho refresh response missing access_token field.');
    }

    const expiresInSeconds = typeof expiresIn === 'number' ? expiresIn : 3600;
    const newExpiry = new Date(Date.now() + expiresInSeconds * 1000);

    await store.updateAccessToken(clientId, userMail, {
        accessToken,
        accessTokenExpiry: newExpiry,
        scopes: typeof scopesRaw === 'string' ? scopesRaw : undefined,
    });

    cachedToken = accessToken;
    cacheExpiry = newExpiry;

    return accessToken;
}

/** Returns a valid Zoho access token (cached or freshly refreshed). */
export async function getAccessToken(): Promise<string> {
    if (isTokenFresh()) {
        return cachedToken!;
    }
    if (refreshInFlight) {
        return refreshInFlight;
    }
    refreshInFlight = performRefresh().finally(() => {
        refreshInFlight = null;
    });
    return refreshInFlight;
}

/**
 * Forces an unconditional refresh, bypassing the cache check. Called by zohoFetch
 * after a 401. Drains any in-flight refresh first so we don't hand back the very
 * token that just 401'd.
 */
export async function forceRefresh(): Promise<string> {
    if (refreshInFlight) {
        await refreshInFlight.catch(() => { /* ignore prior attempt's error */ });
    }
    cachedToken = null;
    cacheExpiry = null;
    return getAccessToken();
}

/**
 * Wires up the token store and pre-loads any cached access token from the DB.
 * MUST be called once on server start before any getAccessToken() call.
 */
export async function warmup(prisma: PrismaClient): Promise<void> {
    store = new PrismaTokenStore(prisma);

    const { clientId, userMail } = config.zoho;
    if (!clientId || !userMail) {
        console.log('[zoho] Credentials not configured — skipping tokenManager warmup.');
        return;
    }

    try {
        const row = await store.load(clientId, userMail);
        if (!row) {
            console.log('[zoho] No ZohoToken row found — run bootstrap before making API calls.');
            return;
        }
        if (row.accessToken && row.accessTokenExpiry) {
            cachedToken = row.accessToken;
            cacheExpiry = row.accessTokenExpiry;
            const isFresh = isTokenFresh();
            console.log(
                `[zoho] Warmup complete. Cached access token is ${isFresh ? 'still valid' : 'expired — will refresh on first API call'}.`
            );
        } else {
            console.log('[zoho] Warmup: no access token in DB — will refresh on first API call.');
        }
    } catch (err) {
        console.error('[zoho] Warmup failed (non-fatal):', err instanceof Error ? err.message : err);
    }
}

/** Resets all in-memory state. Used by unit tests for isolation. */
export function clearCache(): void {
    cachedToken = null;
    cacheExpiry = null;
    refreshInFlight = null;
    store = null;
}

/** Injects a token store directly — used by unit tests without a live DB. */
export function _setStoreForTesting(s: PrismaTokenStore): void {
    store = s;
}
