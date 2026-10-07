# syntax=docker/dockerfile:1
# Legal Lens frontend image: the production build in "backend" mode, served by unprivileged nginx,
# which also proxies /api to the backend container. Used by ../compose.yaml.

# ---------------------------------------------------------------- build
FROM node:24-slim AS build
WORKDIR /app

# Dependencies first, so code changes don't invalidate this layer.
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --ignore-scripts --no-audit --no-fund

COPY . .
# typecheck + build with VITE_USE_MOCKS=false (.env.backend); the mock worker isn't needed.
RUN npm run build:api && rm -f dist-backend/mockServiceWorker.js

# ---------------------------------------------------------------- runtime
FROM nginxinc/nginx-unprivileged:1.29-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist-backend /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
