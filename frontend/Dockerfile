# Build stage
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
# The browser talks only to this app's same-origin BFF proxy
# (src/app/api/v1/[...path]); the backend URL + bearer token are SERVER-side env
# read at runtime (BOOKING_AGENT_API_URL, API_AUTH_TOKEN) — never baked in here.
RUN npm run build

# Run stage: minimal standalone output, non-root.
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup -S nodejs && adduser -S nextjs -G nodejs
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
