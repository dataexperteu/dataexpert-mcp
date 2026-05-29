/**
 * bootstrap.ts — One-time OAuth grant-token exchange for Zoho CRM.
 *
 * Exchanges a 10-minute grant token (from api-console.zoho.eu) for a long-lived
 * refresh token and PRINTS it. There is no database — you copy the printed
 * ZOHO_REFRESH_TOKEN into the env / shared secrets.env. The refresh token is
 * stable (Zoho returns the same one on every refresh), so it lives as a static
 * credential like the other servers' secrets.
 *
 * Run:
 *   ZOHO_CLIENT_ID=… ZOHO_CLIENT_SECRET=… ZOHO_DC=eu \
 *   ZOHO_BOOTSTRAP_GRANT_TOKEN=1000.xxxx npm run bootstrap
 *
 * IMPORTANT — Zoho caps each user at 20 active refresh tokens; every successful
 * exchange consumes one slot. Run this only when you need a (new) refresh token.
 */

import { config } from './config.js';

async function main() {
    const clientId = config.zoho.clientId;
    const clientSecret = config.zoho.clientSecret;
    const redirectUri = config.zoho.redirectUri ?? null;
    const grantToken = process.env.ZOHO_BOOTSTRAP_GRANT_TOKEN?.trim();
    const dc = config.zoho.dc;

    const missing: string[] = [];
    if (!clientId) missing.push('ZOHO_CLIENT_ID');
    if (!clientSecret) missing.push('ZOHO_CLIENT_SECRET');
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
        process.exit(1);
    }

    const accessToken = data.access_token;
    const refreshToken = data.refresh_token;
    const scopesRaw = data.scope;

    if (typeof refreshToken !== 'string' || !refreshToken) {
        console.error('[bootstrap] ERROR: Response did not include a refresh_token.');
        console.error(`[bootstrap]   keys present: [${Object.keys(data).join(', ')}]`);
        process.exit(1);
    }

    // Verify the token works against the accounts module (best-effort).
    let verifyNote = '(skipped — no access_token returned)';
    if (typeof accessToken === 'string' && accessToken) {
        const verifyResponse = await fetch(
            `${config.zoho.apiBase}/Accounts/search?word=aa&per_page=1&fields=Account_Name,id`,
            { method: 'GET', headers: { 'Authorization': `Zoho-oauthtoken ${accessToken}` } },
        );
        verifyNote = verifyResponse.status === 200 || verifyResponse.status === 204
            ? 'OK — accounts.READ works'
            : `WARNING: verification returned HTTP ${verifyResponse.status} (scope may not include accounts.READ)`;
    }

    console.log('');
    console.log('Bootstrap complete. Add this to your env / secrets.env:');
    console.log('');
    console.log(`ZOHO_REFRESH_TOKEN=${refreshToken}`);
    console.log('');
    console.log(`  Datacenter   : ${dc.toUpperCase()}`);
    console.log(`  Verification : ${verifyNote}`);
    if (typeof scopesRaw === 'string') {
        console.log('  Scopes granted:');
        scopesRaw.split(' ').filter(Boolean).forEach((s) => console.log(`    - ${s}`));
    }
    console.log('');
    console.log('IMPORTANT: unset ZOHO_BOOTSTRAP_GRANT_TOKEN from your shell now.');
    console.log('');

    process.exit(0);
}

main().catch((err) => {
    console.error('[bootstrap] FATAL ERROR:');
    console.error(err instanceof Error ? err.message : err);
    if (err?.stack) console.error(err.stack);
    process.exit(1);
});
