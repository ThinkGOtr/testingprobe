# syntax=docker/dockerfile:1
FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY tsconfig.json tsconfig.test.json vite.config.ts index.html ./
COPY src ./src
# Compose/canlı portal örnek veriye HİÇ düşmez: core'un sunmadığı ekranlar "bu fazda yok" gösterir
# (uydurma KPI canlı veri gibi görünmez). Tamamen örnek veriyle çalışan derleme: `npm run build:mock`.
ARG VITE_MOCK=0
ENV VITE_MOCK=${VITE_MOCK}
RUN npm run build

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
# CSP kimlik kipine göre (TP_AUTH_MODE=local|aiprobe|both): başlangıçta docker/40-tp-kimlik-csp.sh
# değişmez şablondan etkin nginx.conf'u yazar (local → aynen). Etkin dosya nginx kullanıcısına ait.
COPY nginx.conf /etc/nginx/tp/nginx.conf.sablon
COPY --chown=nginx:nginx nginx.conf /etc/nginx/nginx.conf
COPY --chmod=0755 docker/40-tp-kimlik-csp.sh /docker-entrypoint.d/40-tp-kimlik-csp.sh
COPY --from=build /app/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
