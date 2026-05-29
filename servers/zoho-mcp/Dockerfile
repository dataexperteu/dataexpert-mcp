# Zoho MCP server — multi-stage build.
#
# Stage 1 (build): install deps, compile TS → dist.
# Stage 2 (runtime): non-root, carries node_modules + dist. No database, no Prisma.

# ---------- build ----------
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY tsconfig.json ./
COPY src ./src

RUN npm run build

# ---------- runtime ----------
FROM node:20-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production
ENV MCP_PORT=3001
ARG GIT_SHA=dev
ENV GIT_SHA=${GIT_SHA}

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json ./
COPY healthcheck.mjs ./

# Run as non-root.
RUN addgroup -g 1001 -S app && adduser -u 1001 -S app -G app
USER app

EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=20s \
    CMD ["node", "/app/healthcheck.mjs"]

CMD ["node", "dist/server.js"]
