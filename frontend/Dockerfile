# Requires Caddyfile mounted at /etc/caddy/Caddyfile (see compose).
# Standalone build without compose will fail at container start.
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY --from=builder /app/dist /srv
