# Fire Safety Regulation Comparison — dashboard
#
# Built once, then served. `next dev` compiles on demand and wants 1.5–2 GB;
# `next start` over a prebuilt app needs a fraction of that, which is the
# difference between running and being killed on a small machine.

# ─── Dependencies ────────────────────────────────────────────────────
FROM node:22-alpine AS deps
WORKDIR /app

# npm ci installs exactly the lockfile, so the image cannot drift from what
# was tested.
COPY package.json package-lock.json ./
RUN npm ci

# ─── Build ───────────────────────────────────────────────────────────
FROM node:22-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Switches next.config.ts to standalone output.
ENV DOCKER_BUILD=1 \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ─── Runtime ─────────────────────────────────────────────────────────
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Where the browser's /api/* calls are forwarded. Compose points this at the
# API container; the browser itself only ever talks to this service, so it
# needs no address of its own for the API and there is no CORS to configure.
ENV API_ORIGIN=http://api:8000

RUN addgroup --system --gid 10001 nodejs \
 && adduser --system --uid 10001 nextjs

# The standalone bundle carries its own minimal node_modules and server.js.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "require('http').get('http://127.0.0.1:3000',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "server.js"]
