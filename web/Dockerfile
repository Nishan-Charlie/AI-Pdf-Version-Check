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

# Where /api/* is forwarded. This has to be set for the *build*, not just the
# runtime: Next resolves rewrite destinations into .next/routes-manifest.json
# when it builds, so a value supplied only to the running container is ignored
# and the proxy keeps pointing at whatever was baked in.
ARG API_ORIGIN=http://api:8000

# Switches next.config.ts to standalone output.
ENV DOCKER_BUILD=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    API_ORIGIN=${API_ORIGIN}

RUN npm run build

# ─── Runtime ─────────────────────────────────────────────────────────
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Kept for reference and for anything that reads it at runtime. The rewrite
# itself was fixed at build time by the ARG above.
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
