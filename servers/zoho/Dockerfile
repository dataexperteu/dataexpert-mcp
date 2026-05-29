# Zoho MCP server — multi-stage build.
#
# Stage 1 (build): install all deps, generate the Prisma client, compile TS → dist.
# Stage 2 (runtime): non-root, carries node_modules (incl. generated Prisma client) + dist.

# ---------- build ----------
FROM node:20-alpine AS build
WORKDIR /app

# openssl is required by Prisma's query engine.
RUN apk add --no-cache openssl

COPY package.json package-lock.json* ./
RUN npm ci

COPY prisma ./prisma
COPY tsconfig.json ./
COPY src ./src

# Generate the Prisma client into node_modules, then compile.
RUN npx prisma generate
RUN npm run build

# ---------- runtime ----------
FROM node:20-alpine AS runtime
WORKDIR /app

RUN apk add --no-cache openssl

ENV NODE_ENV=production
ENV MCP_PORT=3001
ARG GIT_SHA=dev
ENV GIT_SHA=${GIT_SHA}

# Carry the full dependency closure (includes the generated Prisma client) + build output.
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY --from=build /app/prisma ./prisma
COPY package.json ./
COPY healthcheck.mjs ./

# Run as non-root.
RUN addgroup -g 1001 -S app && adduser -u 1001 -S app -G app
USER app

EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=20s \
    CMD ["node", "/app/healthcheck.mjs"]

CMD ["node", "dist/server.js"]
