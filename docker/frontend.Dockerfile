# syntax=docker/dockerfile:1.7
# Build context: frontend/
#   docker build -f docker/frontend.Dockerfile --build-arg HOOKLENS_API_URL=http://api:8000 frontend
#
# Next.js evaluates rewrites at build time, so the API URL the server proxies to is a build arg.
# It is used only by the Next.js server; the browser always calls same-origin /api/v1/*.

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
ARG HOOKLENS_API_URL=http://api:8000
ENV HOOKLENS_API_URL=${HOOKLENS_API_URL} NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
RUN addgroup -S -g 10001 hooklens && adduser -S -u 10001 -G hooklens hooklens
COPY --from=build --chown=hooklens:hooklens /app/.next/standalone ./
COPY --from=build --chown=hooklens:hooklens /app/.next/static ./.next/static
COPY --from=build --chown=hooklens:hooklens /app/public ./public
USER hooklens
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD wget -qO- http://127.0.0.1:3000/ >/dev/null || exit 1
CMD ["node", "server.js"]
