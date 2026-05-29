/**
 * Typed error classes for the Zoho gateway.
 *
 * Having distinct error types lets the tool layer translate failures into a
 * structured `{ kind }` payload the CSM client can branch on — so the frozen
 * /api/zoho/* route error bodies are reconstructable on the other side.
 *
 * Ported near-verbatim from the CSM app's server/src/integrations/zoho/errors.ts.
 */

/** Thrown when Zoho returns an authentication / token error. */
export class ZohoAuthError extends Error {
    constructor(message: string, public readonly cause?: unknown) {
        super(message);
        this.name = 'ZohoAuthError';
    }
}

/** Thrown when Zoho responds with HTTP 429 (too many requests). */
export class ZohoRateLimitError extends Error {
    constructor(message: string, public readonly retryAfterSeconds?: number) {
        super(message);
        this.name = 'ZohoRateLimitError';
    }
}

/**
 * Thrown when a Zoho record cannot be mapped to a canonical shape —
 * e.g. a required field is absent or has an unexpected type.
 * These are data-quality problems, not network problems.
 */
export class ZohoMappingError extends Error {
    constructor(message: string, public readonly zohoRecord?: unknown) {
        super(message);
        this.name = 'ZohoMappingError';
    }
}
