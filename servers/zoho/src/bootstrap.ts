/**
 * bootstrap.ts — One-time OAuth grant-token exchange for Zoho CRM.
 *
 * Ported from the CSM app (server/scripts/zoho-bootstrap.ts). Now writes into the
 * MCP's OWN datastore via this package's token store. Run it as a one-shot inside
 * the zoho-mcp container:
 *
 *   docker compose run --rm -e ZOHO_BOOTSTRAP_GRANT_TOKEN=1000.xxxx zoho-mcp \
 *     node dist/bootstrap.js
 *
 * Required env (set before running):
 *   DATABASE_URL, ZOHO_TOKEN_ENCRYPTION_KEY, ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET,
 *   ZOHO_USER_MAIL, ZOHO_DC=eu, and ZOHO_BOOTSTRAP_GRANT_TOKEN (shell only).
 *
 * IMPORTANT — Zoho caps each user at 20 active refresh tokens. Every successful
 * exchange consumes one slot. Run this exactly ONCE. To re-bootstrap, delete the
 * existing ZohoToken row AND revoke the old token in api-console.zoho.eu first.
 *
 * NOTE: at the production cutover you do NOT run bootstrap — you migrate the
 * existing encrypted ZohoToken row from the CSM database (carrying the same
 * ZOHO_TOKEN_ENCRYPTION_KEY), which decrypts as-is. Bootstrap is for a fresh install.
 */

import { PrismaClient } from '@prisma/client';
import { config } from './config.js';
import { createPrismaTokenStore } from './zoho/tokenStore.js';

async function main() {
    const clientId = config.zoho.clientId;
    const clientSecret = config.zoho.clientSecret;
    const userMail = config.zoho.userMail;
    const redirectUri = config.zoho.redirectUri ?? null;
    const grantToken = process.env.ZOHO_BOOTSTRAP_GRANT_TOKEN?.trim();
    const dc = config.zoho.dc;

    const missing: string[] = [];
    if (!clientId) missing.push('ZOHO_CLIENT_ID');
    if (!clientSecret) missing.push('ZOHO_CLIENT_SECRET');
    if (!userMail) missing.push('ZOHO_USER_MAIL');
    if (!grantToken) missing.push('ZOHO_BOOTSTRAP_GRANT_TOKEN');

    if (missing.length > 0) {
        console.error('[bootstrap] ERROR: Missing required environment variables:');
        missing.forEach((v) => console.error(`  - ${v}`));
        console.error('[bootstrap] Set them in your shell (grant token shell-only) and retry.');
        process.exit(1);
    }

    if (dc !== 'eu') {
        console.warn(`[bootstrap] WARNING: ZOHO_DC="${dc}" — only "eu" is tested.`);
    }

    const prisma = new PrismaClient();
    const store = createPrismaTokenStore(prisma);

    const existing = await store.list();
    if (existing.length > 0) {
        console.warn('[bootstrap] WARNING: A ZohoToken row already exists.');
        console.warn('[bootstrap] Re-running creates a NEW refresh token (one of your 20 Zoho slots).');
        console.warn('[bootstrap] To abort: Ctrl-C now and clear ZOHO_BOOTSTRAP_GRANT_TOKEN.');
        await new Promise((r) => setTimeout(r, 3000));
        console.log('[bootstrap] Continuing...');
    }

    console.log('[bootstrap] Exchanging grant token with Zoho token endpoint...');

    const body = new URLSearchParams({
        grant_type: 'authorization_code',
        client_id: clientId!,
        client_secret: clientSecret!,
        code: grantToken!,
        ...(redirectUri ? { redirect_uri: redirectUri } : {}),
    });

    const response = await fetch(`${config.zoho.accountsBase}/oauth/v2/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
    });

    const data = await response.json() as Record<string, unknown>;

    if (data.error) {
        console.error(`[bootstrap] ERROR: Zoho token exchange failed: ${data.error}`);
        if (data.error_description) console.error(`[bootstrap]   Description: ${data.error_description}`);
        console.error('[bootstrap] Common causes: grant token already used / expired (~3 min) / redirect_uri mismatch.');
        await prisma.$disconnect();
        process.exit(1);
    }

    const accessToken = data.access_token;
    const refreshToken = data.refresh_token;
    const expiresIn = data.expires_in;
    const scopesRaw = data.scope;

    const EU_DEFAULT_API_DOMAIN = `https://www.zohoapis.${dc}`;
    const rawApiDomain = data.api_domain as string | undefined;
    const apiDomain =
        typeof rawApiDomain === 'string' && rawApiDomain.startsWith('https://www.zohoapis.')
            ? rawApiDomain
            : (() => {
                if (rawApiDomain !== undefined) {
                    console.warn(`[bootstrap] WARNING: api_domain "${rawApiDomain}" not recognized; using ${EU_DEFAULT_API_DOMAIN}.`);
                }
                return EU_DEFAULT_API_DOMAIN;
            })();

    if (typeof accessToken !== 'string' || !accessToken) {
        console.error('[bootstrap] ERROR: Response did not include an access_token.');
        console.error(`[bootstrap]   keys present: [${Object.keys(data).join(', ')}]`);
        await prisma.$disconnect();
        process.exit(1);
    }
    if (typeof refreshToken !== 'string' || !refreshToken) {
        console.error('[bootstrap] ERROR: Response did not include a refresh_token.');
        await prisma.$disconnect();
        process.exit(1);
    }

    const expiresInSeconds = typeof expiresIn === 'number' ? expiresIn : 3600;
    const accessTokenExpiry = new Date(Date.now() + expiresInSeconds * 1000);
    const scopes = typeof scopesRaw === 'string' ? scopesRaw : null;

    await store.save({
        clientId: clientId!,
        userMail: userMail!,
        refreshToken,
        accessToken,
        accessTokenExpiry,
        apiDomain,
        scopes,
    });

    console.log('[bootstrap] Token stored successfully.');
    console.log('[bootstrap] Verifying token with a live Accounts search...');

    const verifyResponse = await fetch(
        `${apiDomain}/crm/v8/Accounts/search?word=aa&per_page=1&fields=Account_Name,id`,
        { method: 'GET', headers: { 'Authorization': `Zoho-oauthtoken ${accessToken}` } },
    );
    const verifyOk = verifyResponse.status === 200 || verifyResponse.status === 204;

    if (!verifyOk) {
        const errBody = await verifyResponse.text();
        console.error(`[bootstrap] WARNING: Verification returned HTTP ${verifyResponse.status}. Body: ${errBody}`);
        console.error('[bootstrap] Token stored, but the scope may not include accounts.READ. Check the scopes column.');
    } else {
        console.log('[bootstrap] Verification OK — accounts.READ is working.');
    }

    console.log('');
    console.log('Bootstrap complete.');
    console.log(`  User mail  : ${userMail}`);
    console.log(`  API domain : ${apiDomain}`);
    console.log(`  Datacenter : ${dc.toUpperCase()}`);
    if (scopes) {
        console.log('  Scopes granted:');
        scopes.split(' ').filter(Boolean).forEach((s) => console.log(`    - ${s}`));
    } else {
        console.log('  Scopes     : (not returned by Zoho in this response)');
    }
    console.log('');
    console.log('IMPORTANT: unset ZOHO_BOOTSTRAP_GRANT_TOKEN from your shell now.');
    console.log('');

    await prisma.$disconnect();
    process.exit(0);
}

main().catch((err) => {
    console.error('[bootstrap] FATAL ERROR:');
    console.error(err instanceof Error ? err.message : err);
    if (err?.stack) console.error(err.stack);
    process.exit(1);
});
