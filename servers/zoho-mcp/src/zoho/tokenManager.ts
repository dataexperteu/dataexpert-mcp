/**
 * Zoho access-token manager — refresh-on-demand with in-memory cache and mutex.
 *
 * Env-only model (no database). Zoho's refresh token is long-lived and stable
 * (Zoho returns the same one on every refresh), so it lives in the env / shared
 * secrets.env as ZOHO_REFRESH_TOKEN — like the other servers' static credentials.
 * The short-lived access token is cached in memory and refreshed on demand.
 *
 * - In-memory cache: a fresh access token is reused without a network round-trip.
 * - Mutex: if the token is expired, ONE caller refreshes and all others await it,
 *   so concurrent callers don't each POST to Zoho's token endpoint.
 *
 * The cache is module-level state, so it survives across MCP requests even when
 * the server uses a per-request McpServer instance (stateless transport).
 */

import { config } from '../config.js';
import { ZohoAuthError } from './errors.js';

let cachedToken: string | null = null;
let cacheExpiry: Date | null = null;
let refreshInFlight: Promise<string> | null = null;
// Scopes Zoho actually granted, captured from the last refresh response. Zoho
// silently narrows scopes by the user's CRM role; surfacing this lets auth_status
// report the real operational ceiling without a database.
let grantedScopes: string[] = [];

const EXPIRE_BUFFER_SECONDS = 60;

function isTokenFresh(): boolean {
    if (!cachedToken || !cacheExpiry) return false;
    return cacheExpiry.getTime() - Date.now() > EXPIRE_BUFFER_SECONDS * 1000;
}

/** POST to Zoho's token endpoint with the configured refresh token. */
async function performRefresh(): Promise<string> {
    const { clientId, clientSecret, refreshToken } = config.zoho;
    if (!clientId || !clientSecret || !refreshToken) {
        throw new ZohoAuthError(
            '[tokenManager] Zoho credentials not configured (need ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN).'
        );
    }

    const body = new URLSearchParams({
        grant_type: 'refresh_token',
        client_id: clientId,
        client_secret: clientSecret,
        refresh_token: refreshToken,
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
    cachedToken = accessToken;
    cacheExpiry = new Date(Date.now() + expiresInSeconds * 1000);
    if (typeof scopesRaw === 'string') {
        grantedScopes = scopesRaw.split(' ').filter(Boolean);
    }

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

/** Scopes Zoho granted (from the last refresh). Empty until the first refresh. */
export function getGrantedScopes(): string[] {
    return grantedScopes;
}

/** True if the minimum Zoho credentials are present in the env. */
export function isConfigured(): boolean {
    const { clientId, clientSecret, refreshToken } = config.zoho;
    return Boolean(clientId && clientSecret && refreshToken);
}

/** Resets all in-memory state. Used by unit tests for isolation. */
export function clearCache(): void {
    cachedToken = null;
    cacheExpiry = null;
    refreshInFlight = null;
    grantedScopes = [];
}
