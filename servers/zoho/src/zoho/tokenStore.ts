/**
 * Prisma-backed token DAO for the Zoho gateway.
 *
 * Ported from the CSM app (server/src/integrations/zoho/tokenStore.ts), repointed
 * at the MCP's OWN Prisma client / datastore. Logic is unchanged.
 *
 * Design notes
 * ------------
 * - `save()` ALWAYS upserts by (clientId, userMailId). Zoho caps each user at 20
 *   active refresh tokens; a new row per refresh would leak toward that cap.
 *   Upsert = exactly one row, always.
 * - `load()` returns null if never bootstrapped — callers must handle null.
 * - `scopes` records what Zoho actually granted (often narrower than requested),
 *   so auth_status can surface the operational ceiling without re-querying Zoho.
 *
 * Encryption at rest: refreshToken/accessToken are AES-256-GCM wrapped via
 * tokenCipher before they hit Prisma; reads decrypt automatically; legacy
 * plaintext rows pass through unchanged (supports the cutover migration).
 */

import { PrismaClient } from '@prisma/client';
import { encryptSecret, decryptSecret } from './tokenCipher.js';

export interface ZohoTokenRecord {
    id: string;
    clientId: string;
    userMailId: string;
    refreshToken: string;
    accessToken: string | null;
    accessTokenExpiry: Date | null;
    apiDomain: string;
    scopes: string | null;
}

export class PrismaTokenStore {
    constructor(private readonly prisma: PrismaClient) {}

    /** Load the token row for (clientId, userMail). Returns null if not bootstrapped. */
    async load(clientId: string, userMail: string): Promise<ZohoTokenRecord | null> {
        const row = await this.prisma.zohoToken.findUnique({
            where: { clientId_userMailId: { clientId, userMailId: userMail } },
        });
        if (!row) return null;
        return {
            ...row,
            refreshToken: decryptSecret(row.refreshToken),
            accessToken: decryptSecret(row.accessToken),
        };
    }

    /** Persist a full token row (bootstrap). Upserts so a re-bootstrap replaces in place. */
    async save(record: {
        clientId: string;
        userMail: string;
        refreshToken: string;
        accessToken: string;
        accessTokenExpiry: Date;
        apiDomain: string;
        scopes: string | null;
    }): Promise<void> {
        const encryptedRefresh = encryptSecret(record.refreshToken);
        const encryptedAccess = encryptSecret(record.accessToken);
        await this.prisma.zohoToken.upsert({
            where: {
                clientId_userMailId: {
                    clientId: record.clientId,
                    userMailId: record.userMail,
                },
            },
            update: {
                refreshToken: encryptedRefresh,
                accessToken: encryptedAccess,
                accessTokenExpiry: record.accessTokenExpiry,
                apiDomain: record.apiDomain,
                scopes: record.scopes,
                updatedAt: new Date(),
            },
            create: {
                clientId: record.clientId,
                userMailId: record.userMail,
                refreshToken: encryptedRefresh,
                accessToken: encryptedAccess,
                accessTokenExpiry: record.accessTokenExpiry,
                apiDomain: record.apiDomain,
                scopes: record.scopes,
            },
        });
    }

    /**
     * Update only the access token fields after a refresh cycle. The refresh token
     * itself is NOT changed — Zoho returns the same refresh token on refresh.
     */
    async updateAccessToken(
        clientId: string,
        userMail: string,
        patch: { accessToken: string; accessTokenExpiry: Date; scopes?: string }
    ): Promise<void> {
        await this.prisma.zohoToken.update({
            where: { clientId_userMailId: { clientId, userMailId: userMail } },
            data: {
                accessToken: encryptSecret(patch.accessToken),
                accessTokenExpiry: patch.accessTokenExpiry,
                ...(patch.scopes !== undefined ? { scopes: patch.scopes } : {}),
                updatedAt: new Date(),
            },
        });
    }

    /** Wipe the token row (before a re-bootstrap / revocation). No-op if absent. */
    async clear(clientId: string, userMail: string): Promise<void> {
        await this.prisma.zohoToken
            .delete({ where: { clientId_userMailId: { clientId, userMailId: userMail } } })
            .catch(() => { /* swallow not-found */ });
    }

    /** List all rows (diagnostics + bootstrap guard). Normally zero or one. */
    async list(): Promise<ZohoTokenRecord[]> {
        const rows = await this.prisma.zohoToken.findMany();
        return rows.map((row) => ({
            ...row,
            refreshToken: decryptSecret(row.refreshToken),
            accessToken: decryptSecret(row.accessToken),
        }));
    }
}

/** Factory helper — returns an instance bound to the given Prisma client. */
export function createPrismaTokenStore(prisma: PrismaClient): PrismaTokenStore {
    return new PrismaTokenStore(prisma);
}
