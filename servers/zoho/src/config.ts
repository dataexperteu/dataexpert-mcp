/**
 * Config for the Zoho MCP server.
 *
 * The gateway owns all Zoho-specific knowledge, including which datacenter's URLs
 * to talk to. The CSM app no longer knows any of this — that's the whole point of
 * the re-platform.
 *
 * Datacenter handling: Zoho runs regional datacenters with distinct hostnames
 * (eu/com/in/au/...). We derive both the CRM API base and the OAuth/accounts base
 * from ZOHO_DC. Only 'eu' is tested/approved for this deployment.
 */

function opt(v: string | undefined): string | undefined {
    const t = v?.trim();
    return t ? t : undefined;
}

const dc = (process.env.ZOHO_DC?.trim() || 'eu').toLowerCase();

export const config = {
    zoho: {
        clientId: opt(process.env.ZOHO_CLIENT_ID),
        clientSecret: opt(process.env.ZOHO_CLIENT_SECRET),
        userMail: opt(process.env.ZOHO_USER_MAIL),
        redirectUri: opt(process.env.ZOHO_REDIRECT_URI),
        dc,
        // CRM record API base, e.g. https://www.zohoapis.eu/crm/v8
        apiBase: `https://www.zohoapis.${dc}/crm/v8`,
        // OAuth/accounts base, e.g. https://accounts.zoho.eu
        accountsBase: `https://accounts.zoho.${dc}`,
    },
    mcp: {
        port: parseInt(process.env.MCP_PORT || '3001', 10),
    },
} as const;
