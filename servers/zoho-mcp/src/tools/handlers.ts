/**
 * Tool handlers — the Zoho business logic behind each MCP tool.
 *
 * These return canonical payloads (or throw a typed Zoho error). They are kept
 * free of MCP plumbing so they're trivially unit-testable; register.ts wraps them
 * with input validation and structured-error translation.
 */

import { searchAccounts, getAccount, updateAccount } from '../zoho/zohoApi.js';
import {
    toCanonicalAccount,
    toZohoUpdateRecord,
    type CanonicalAccount,
    type CanonicalAccountWrite,
} from '../zoho/mappers.js';
import { getGrantedScopes } from '../zoho/tokenManager.js';

// ---- search_accounts ----

export interface SearchAccountsResult {
    // Search returns a lean subset — pairing/annotation is the CSM client's job.
    results: Array<Pick<CanonicalAccount, 'zohoId' | 'name' | 'website' | 'industry'>>;
}

export async function doSearchAccounts(args: {
    q: string;
    perPage?: number;
}): Promise<SearchAccountsResult> {
    const raw = await searchAccounts({ q: args.q, perPage: args.perPage });
    return {
        results: raw.map(toCanonicalAccount).map((a) => ({
            zohoId: a.zohoId,
            name: a.name,
            website: a.website,
            industry: a.industry,
        })),
    };
}

// ---- get_account ----

export interface GetAccountResult {
    account: CanonicalAccount | null;
}

export async function doGetAccount(args: { zohoId: string }): Promise<GetAccountResult> {
    const raw = await getAccount(args.zohoId);
    return { account: raw ? toCanonicalAccount(raw) : null };
}

// ---- update_account (dumb pipe: just the PUT; conflict policy stays CSM-side) ----

export interface UpdateAccountResult {
    code: string;            // 'SUCCESS' | 'INVALID_DATA' | ...
    status: string;          // 'success' | 'error'
    message: string;
    modifiedTime: string | null; // Zoho's new Modified_Time, for the caller's watermark
}

export async function doUpdateAccount(args: {
    zohoId: string;
    fields: CanonicalAccountWrite;
}): Promise<UpdateAccountResult> {
    const record = toZohoUpdateRecord(args.zohoId, args.fields);
    // ZohoAccountUpdateRecord is a named interface (no index signature); the
    // write helper takes `{ id } & Record<string, unknown>`. Widen explicitly.
    const r = await updateAccount(args.zohoId, record as { id: string } & Record<string, unknown>);
    return {
        code: r.code,
        status: r.status,
        message: r.message,
        modifiedTime: r.details?.Modified_Time ?? null,
    };
}

// ---- auth_status ----

export interface AuthStatusResult {
    authenticated: boolean;
    scopes: string[];
    lastError: string | null;
}

export async function doAuthStatus(): Promise<AuthStatusResult> {
    // Probe with a 2-char word search — Zoho rejects 1-char with a 400, and this is
    // the cheapest call that proves accounts.READ works end-to-end (token + scope).
    try {
        await searchAccounts({ q: 'aa', perPage: 1 });
        return { authenticated: true, scopes: getGrantedScopes(), lastError: null };
    } catch (err) {
        return {
            authenticated: false,
            scopes: getGrantedScopes(),
            lastError: err instanceof Error ? err.message : String(err),
        };
    }
}
