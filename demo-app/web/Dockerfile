# demo-app-web — Bayi Sipariş Portalı web iskeleti (F0)
FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
# Derleme kimliği (isteğe bağlı): imaj forge'dan derlenirken verilir (scripts/forge-init.sh
# break|baseline|sync-web); compose'un çalışma ağacından derlemesinde boş kalır. GET /build.json
# çalışan uygulamanın hangi commit'ten (ve web/ ağacından) derlendiğini söyler.
ARG DEMO_APP_BUILD_SHA=""
ARG DEMO_APP_WEB_TREE=""
RUN case "$DEMO_APP_BUILD_SHA$DEMO_APP_WEB_TREE" in *[!0-9a-f]*) echo "geçersiz sha" >&2; exit 1;; esac \
 && printf '{"service":"demo-app-web","sha":"%s","web_tree":"%s"}\n' "$DEMO_APP_BUILD_SHA" "$DEMO_APP_WEB_TREE" \
    > /usr/share/nginx/html/build.json
USER 101
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
