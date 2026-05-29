/**
 * Canonical field mappers — pure functions, no I/O.
 *
 * This is the "canonical half" of the CSM app's old mappers.ts. The split rule
 * (plan decision #6): the gateway emits a CLEAN, source-faithful shape and carries
 * NO CSM presentation rules. Specifically it returns `website` (the full URL Zoho
 * stores), NOT `domain` (a hostname). The CSM app applies its own parseDomain() on
 * the way in. A future LLM agent / the Trend Engine therefore gets the real URL,
 * not CSM's hostname convention.
 *
 * Analogy: a codec. It translates between Zoho's API shape and our canonical shape
 * without touching anything outside itself.
 */

import type { ZohoAccountRaw } from './zohoApi.js';

// ---- Canonical read shape ----

export interface CanonicalAccount {
    zohoId: string;
    name: string | null;
    website: string | null;     // full URL as Zoho stores it (NOT a parsed hostname)
    industry: string | null;
    nextStep: string | null;
    modifiedTime: string | null; // ISO 8601 string exactly as Zoho delivers it
}

/** A Zoho raw value that is a non-empty string, else null. */
function str(v: unknown): string | null {
    return typeof v === 'string' && v.trim() ? v : null;
}

/** Map a raw Zoho account record to the canonical shape. */
export function toCanonicalAccount(raw: ZohoAccountRaw): CanonicalAccount {
    return {
        zohoId: raw.id,
        name: str(raw.Account_Name),
        website: str(raw.Website),
        industry: str(raw.Industry),
        nextStep: str(raw.Next_Step),
        modifiedTime: str(raw.Modified_Time),
    };
}

// ---- Canonical write shape ----

/**
 * Canonical fields a client may write to an account. All optional — only the keys
 * present are sent to Zoho (partial-update idiom). `website` is a full URL; the
 * gateway passes it through unchanged (no domain<->URL conversion here).
 */
export interface CanonicalAccountWrite {
    name?: string;
    website?: string;
    industry?: string;
    nextStep?: string;
}

/** The Zoho api_name PUT payload shape. */
export interface ZohoAccountUpdateRecord {
    id: string;
    Account_Name?: string;
    Website?: string;
    Industry?: string;
    Next_Step?: string;
}

/**
 * Map canonical write fields to the Zoho update payload.
 *
 * Null-safety: undefined/empty-string keys are OMITTED ("don't touch in Zoho").
 * The gateway never CLEARS a Zoho field — clearing would require an explicit
 * affordance the CSM side owns. Non-empty strings are emitted under their api_name.
 */
export function toZohoUpdateRecord(
    zohoId: string,
    fields: CanonicalAccountWrite,
): ZohoAccountUpdateRecord {
    const record: ZohoAccountUpdateRecord = { id: zohoId };

    if (typeof fields.name === 'string' && fields.name.trim()) {
        record.Account_Name = fields.name.trim();
    }
    if (typeof fields.website === 'string' && fields.website.trim()) {
        record.Website = fields.website.trim();
    }
    if (typeof fields.industry === 'string' && fields.industry.trim()) {
        record.Industry = fields.industry.trim();
    }
    if (typeof fields.nextStep === 'string' && fields.nextStep.trim()) {
        record.Next_Step = fields.nextStep.trim();
    }

    return record;
}
