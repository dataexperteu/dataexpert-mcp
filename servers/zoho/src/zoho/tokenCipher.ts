/**
 * tokenCipher.ts — AES-256-GCM envelope for Zoho secrets at rest.
 *
 * Ported VERBATIM from the CSM app (server/src/crypto/tokenCipher.ts). The format
 * is identical so the existing encrypted refresh token migrates across to the MCP
 * datastore and decrypts as-is — provided ZOHO_TOKEN_ENCRYPTION_KEY is MOVED, not
 * regenerated (see the plan, decision #7).
 *
 * ON-DISK FORMAT
 * --------------
 * `enc:v1:<base64url(iv || authTag || ciphertext)>`
 *   iv          12 bytes (96-bit GCM nonce; random per encryption)
 *   authTag     16 bytes (128-bit GCM tag)
 *   ciphertext  variable length, equals plaintext length
 *
 * The `enc:v1:` prefix is the version marker. A token without this prefix is
 * treated as legacy plaintext and read through unchanged.
 *
 * KEY MANAGEMENT
 * --------------
 * - Key lives in ZOHO_TOKEN_ENCRYPTION_KEY (32 random bytes, base64-encoded).
 *   Generate: node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"
 * - Missing/malformed key → encrypt() throws on first write; reads of existing
 *   legacy-plaintext rows still work, so a misconfigured deploy degrades loudly
 *   on writes but not silently.
 */

import crypto from 'node:crypto';

const VERSION_PREFIX = 'enc:v1:';
const IV_BYTES = 12;
const TAG_BYTES = 16;
const KEY_BYTES = 32; // 256-bit key for AES-256

let cachedKey: Buffer | null = null;
let cachedKeySource: string | null = null;

function loadKey(): Buffer {
    const raw = process.env.ZOHO_TOKEN_ENCRYPTION_KEY ?? '';
    if (!raw) {
        throw new Error(
            'ZOHO_TOKEN_ENCRYPTION_KEY is not set. Generate with: node -e "console.log(require(\'crypto\').randomBytes(32).toString(\'base64\'))" and add to your environment.'
        );
    }
    if (cachedKey && cachedKeySource === raw) {
        return cachedKey;
    }
    let buf: Buffer;
    try {
        buf = Buffer.from(raw, 'base64');
    } catch {
        throw new Error('ZOHO_TOKEN_ENCRYPTION_KEY is not valid base64.');
    }
    if (buf.length !== KEY_BYTES) {
        throw new Error(`ZOHO_TOKEN_ENCRYPTION_KEY must decode to exactly ${KEY_BYTES} bytes (got ${buf.length}).`);
    }
    cachedKey = buf;
    cachedKeySource = raw;
    return buf;
}

/** True if `value` is a ciphertext blob produced by this module. */
export function isEncrypted(value: unknown): boolean {
    return typeof value === 'string' && value.startsWith(VERSION_PREFIX);
}

/** Encrypt a plaintext secret. Throws if the key is missing/invalid. */
export function encryptSecret(plaintext: string): string {
    if (typeof plaintext !== 'string') {
        throw new Error('encryptSecret: plaintext must be a string');
    }
    const key = loadKey();
    const iv = crypto.randomBytes(IV_BYTES);
    const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
    const ct = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()]);
    const tag = cipher.getAuthTag();
    const blob = Buffer.concat([iv, tag, ct]).toString('base64url');
    return `${VERSION_PREFIX}${blob}`;
}

/**
 * Decrypt a value produced by encryptSecret.
 * - Legacy plaintext (no `enc:v1:` prefix) is returned unchanged.
 * - null is returned as null (accessToken is nullable).
 * Throws if the value has the prefix but the payload is malformed or the GCM tag
 * fails — a corrupted ciphertext is a security signal, not a soft fallback.
 */
export function decryptSecret(value: string): string;
export function decryptSecret(value: null): null;
export function decryptSecret(value: string | null): string | null;
export function decryptSecret(value: string | null): string | null {
    if (value === null) return null;
    if (typeof value !== 'string') {
        throw new Error('decryptSecret: value must be a string or null');
    }
    if (!value.startsWith(VERSION_PREFIX)) {
        return value;
    }
    const key = loadKey();
    let blob: Buffer;
    try {
        blob = Buffer.from(value.slice(VERSION_PREFIX.length), 'base64url');
    } catch {
        throw new Error('decryptSecret: ciphertext is not valid base64url');
    }
    if (blob.length < IV_BYTES + TAG_BYTES) {
        throw new Error('decryptSecret: ciphertext payload too short');
    }
    const iv = blob.subarray(0, IV_BYTES);
    const tag = blob.subarray(IV_BYTES, IV_BYTES + TAG_BYTES);
    const ct = blob.subarray(IV_BYTES + TAG_BYTES);
    const decipher = crypto.createDecipheriv('aes-256-gcm', key, iv);
    decipher.setAuthTag(tag);
    const pt = Buffer.concat([decipher.update(ct), decipher.final()]).toString('utf8');
    return pt;
}

/** Reset the cached key. Test helper only. */
export function _resetKeyCacheForTesting(): void {
    cachedKey = null;
    cachedKeySource = null;
}
