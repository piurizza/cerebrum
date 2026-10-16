# The build stage's output is static JS/CSS/HTML, identical for every CPU
# architecture, so it runs natively on the build machine even when the image
# is built for another one (the release builds arm64 too), not under emulation.
FROM --platform=$BUILDPLATFORM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
# The cache mount keeps npm's downloaded tarballs between builds, so a
# rebuild after a lockfile change only fetches what changed.
RUN --mount=type=cache,target=/root/.npm npm ci

COPY . .
RUN npm run build

FROM nginx:alpine
# openssl CLI (not bundled with nginx:alpine by default -- only the shared
# libs nginx itself links against are) is needed by docker-entrypoint.sh to
# generate a self-signed cert for offline mode's HTTPS listener (KD4/U1).
RUN apk add --no-cache openssl
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx-locations.conf /etc/nginx/nginx-locations.conf
COPY docker-entrypoint.sh /docker-entrypoint.d/../cerebrum-entrypoint.sh
RUN chmod +x /cerebrum-entrypoint.sh

EXPOSE 80 443
ENTRYPOINT ["/cerebrum-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
