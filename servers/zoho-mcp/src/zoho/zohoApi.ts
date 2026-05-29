/**
 * Zoho CRM API wrapper — direct HTTP with typed helpers.
 *
 * Ported from the CSM app (server/src/integrations/zoho/zohoApi.ts). The only
 * change is the API base URL now comes from config (DC-derived) instead of a
 * hardcoded EU constant. This is the single file that knows Zoho's URL structure.
 *
 * Why direct fetch() instead of the Zoho SDK
 * -------------------------------------------
 * The Zoho user can only be granted three module READ scopes (accounts/contacts/
 * emails). The official SDK requires ZohoCRM.settings.fields.READ for EVERY call
 * (it fetches field metadata first) — a scope this non-admin user cannot obtain.
 * Direct fetch() only needs the module-level scope that's actually in the request.
 *
 * Token handling: all calls go through zohoFetch(), which gets a valid token from
 * tokenManager, attaches `Authorization: Zoho-oauthtoken <token>`, retries once on
 * 401 with a forced refresh, throws ZohoRateLimitError on 429, and returns null on
 * 204 (empty result).
 */

import { getAccessToken, forceRefresh } from './tokenManager.js';
import { config } from '../config.js';
import { ZohoAuthError, ZohoRateLimitError } from './errors.js';

// ---- Raw Zoho record shapes (as delivered by Zoho, before canonical mapping) ----

export interface ZohoAccountRaw {
    id: string;
    Account_Name: string;
    Website: string | null;
    Industry: string | null;
    Modified_Time?: string | null;
    Next_Step?: string | null;
    [key: string]: unknown;
}

interface ZohoFetchOptions {
    method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
    params?: Record<string, string | number | boolean>;
    body?: unknown;
}

/**
 * Authenticated request to the Zoho CRM v8 API. `path` starts with '/'.
 * Returns parsed JSON on 2xx, null on 204. On 401 retries once with a forced
 * refresh; on 429 throws ZohoRateLimitError; on other non-2xx throws with status.
 */
async function zohoFetch(path: string, opts: ZohoFetchOptions = {}): Promise<unknown> {
    const { method = 'GET', params, body } = opts;

    const url = new URL(`${config.zoho.apiBase}${path}`);
    if (params) {
        for (const [key, value] of Object.entries(params)) {
            url.searchParams.set(key, String(value));
        }
    }

    async function attemptRequest(token: string): Promise<Response> {
        const fetchOptions: RequestInit = {
            method,
            headers: {
                'Authorization': `Zoho-oauthtoken ${token}`,
                'Content-Type': 'application/json',
            },
        };
        if (body !== undefined) {
            fetchOptions.body = JSON.stringify(body);
        }
        return fetch(url.toString(), fetchOptions);
    }

    let token = await getAccessToken();
    let response = await attemptRequest(token);

    if (response.status === 401) {
        token = await forceRefresh();
        response = await attemptRequest(token);
        if (response.status === 401) {
            throw new ZohoAuthError(
                `[zohoFetch] 401 even after token refresh on ${method} ${path}. ` +
                'The refresh token may be revoked — re-bootstrap may be needed.'
            );
        }
    }

    if (response.status === 429) {
        const retryAfter = response.headers.get('Retry-After');
        const retrySeconds = retryAfter ? parseInt(retryAfter, 10) : undefined;
        throw new ZohoRateLimitError(`[zohoFetch] Zoho rate limit hit on ${method} ${path}`, retrySeconds);
    }

    if (response.status === 204) {
        return null;
    }

    if (!response.ok) {
        let errorDetail = '';
        try {
            const errBody = await response.json() as Record<string, unknown>;
            const code = errBody.code ?? errBody.errorCode ?? '';
            const message = errBody.message ?? '';
            errorDetail = code ? ` (${code}: ${message})` : '';
        } catch {
            // Body not JSON — ignore.
        }
        throw new Error(`[zohoFetch] HTTP ${response.status} from Zoho${errorDetail} — ${method} ${path}`);
    }

    return response.json();
}

// ---- Typed module helpers (the only Zoho calls the tool layer makes) ----

/** Search Zoho Accounts by a word/phrase (Zoho WORD search, matches Account_Name). */
export async function searchAccounts(opts: {
    q: string;
    perPage?: number;
    fields?: string[];
}): Promise<ZohoAccountRaw[]> {
    const { q, perPage = 25, fields = ['Account_Name', 'Website', 'Industry', 'id'] } = opts;
    const result = await zohoFetch('/Accounts/search', {
        params: { word: q, per_page: perPage, fields: fields.join(',') },
    });
    if (!result) return [];
    const bodyData = result as { data?: ZohoAccountRaw[] };
    return bodyData.data ?? [];
}

/** Fetch a single Zoho Account by record ID. Returns null if it doesn't exist. */
export async function getAccount(zohoId: string): Promise<ZohoAccountRaw | null> {
    const result = await zohoFetch(`/Accounts/${encodeURIComponent(zohoId)}`, {
        params: { fields: 'Account_Name,Website,Industry,Next_Step,Modified_Time,id' },
    });
    if (!result) return null;
    const bodyData = result as { data?: ZohoAccountRaw[] };
    const records = bodyData.data ?? [];
    return records.length > 0 ? records[0] : null;
}

// Phase 2+ adds: listContactsByAccount, getContact
// Phase 3+ adds: listContactEmails, getEmail, downloadEmailAttachment

// ---- Write path (Phase 2.5 — the one approved write surface: Next_Step) ----

/**
 * Per-record status from a Zoho PUT response. Zoho returns HTTP 207 (Multi-Status)
 * even for a single record; the per-record outcome is in `code` (not the HTTP status).
 */
export interface ZohoUpdateRecordResult {
    code: string;   // 'SUCCESS' | 'INVALID_DATA' | 'MANDATORY_NOT_FOUND' | ...
    status: string; // 'success' | 'error'
    message: string;
    details?: {
        id?: string;
        Modified_Time?: string;
        Modified_By?: { id: string; name: string };
        [key: string]: unknown;
    };
}

/**
 * Update a Zoho Account record. `record` is in Zoho api_name shape (use the
 * canonical mapper to build it) and its `id` MUST equal `zohoId`.
 *
 * Does NOT throw on per-record failures (code !== 'SUCCESS') — the HTTP call
 * succeeded; only the business outcome differs. The caller branches on `code`.
 * Throws ZohoAuthError/ZohoRateLimitError (via zohoFetch) on auth/rate-limit.
 */
export async function updateAccount(
    zohoId: string,
    record: { id: string } & Record<string, unknown>,
): Promise<ZohoUpdateRecordResult> {
    if (!zohoId) {
        throw new Error('[zohoApi.updateAccount] zohoId is required');
    }
    if (record.id !== zohoId) {
        throw new Error(
            `[zohoApi.updateAccount] record.id (${record.id}) does not match URL zohoId (${zohoId})`
        );
    }

    const result = await zohoFetch(`/Accounts/${encodeURIComponent(zohoId)}`, {
        method: 'PUT',
        body: { data: [record] },
    });

    if (!result) {
        throw new Error('[zohoApi.updateAccount] Zoho returned empty response on PUT');
    }

    const bodyData = result as { data?: ZohoUpdateRecordResult[] };
    const records = bodyData.data ?? [];
    if (records.length === 0) {
        throw new Error('[zohoApi.updateAccount] Zoho response had no data array');
    }
    return records[0];
}
