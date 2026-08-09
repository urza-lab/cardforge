# Stage 1: build the static React app
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

# Stage 2: serve the static build + reverse-proxy /api to the backend.
# This single container is what CardForge exposes on the host — see
# docker-compose.yml (frontend service, port 666:80).
FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
  CMD wget -qO- http://localhost:80/healthz || exit 1

EXPOSE 80
