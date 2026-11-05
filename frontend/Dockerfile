# syntax=docker/dockerfile:1
# Legal Lens frontend image: the production build in "backend" mode, served by unprivileged
# nginx, which also proxies /api to the backend. Full guide: DOCKER.md.
#
#   docker build --platform linux/amd64 -t legallens-frontend:local .      (from frontend/)
#   docker run --rm -p 127.0.0.1:8080:8080 -e BACKEND_URL=http://backend:8000 legallens-frontend:local

# ---------------------------------------------------------------- build
FROM node:24.22.1-slim AS build
WORKDIR /app

# Dependencies first, so code changes don't invalidate this layer.
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --ignore-scripts --no-audit --no-fund

COPY . .
# typecheck + build with VITE_USE_MOCKS=false (.env.backend); the mock worker isn't needed.
RUN npm run build:api && rm -f dist-backend/mockServiceWorker.js

# ---------------------------------------------------------------- runtime
# Runs as user 101 (numeric) and listens on 8080, so no root is needed anywhere.
FROM nginxinc/nginx-unprivileged:1.29.8-alpine3.23 AS runtime
LABEL org.opencontainers.image.title="legallens-frontend" \
      org.opencontainers.image.description="Legal Lens web UI (static build + /api proxy)"

# Filled in at container start by the image's entrypoint (only these variables, so nginx's own
# $host / $uri are never touched). BACKEND_URL: where /api goes; the default suits Compose.
ENV BACKEND_URL=http://backend:8000 \
    PROXY_READ_TIMEOUT=660s \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    NGINX_ENVSUBST_FILTER="^(BACKEND_URL|PROXY_READ_TIMEOUT|NGINX_LOCAL_RESOLVERS)$"
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist-backend /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
