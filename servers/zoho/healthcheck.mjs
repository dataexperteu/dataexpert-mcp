// Container healthcheck — hits the local /healthz liveness route.
// Deliberately does NOT call Zoho (a 30s healthcheck must not burn API quota).
import http from 'node:http';

const port = process.env.MCP_PORT || '3001';
const req = http.get(
    { host: '127.0.0.1', port, path: '/healthz', timeout: 5000 },
    (res) => process.exit(res.statusCode === 200 ? 0 : 1),
);
req.on('error', () => process.exit(1));
req.on('timeout', () => {
    req.destroy();
    process.exit(1);
});
