# syntax=docker/dockerfile:1
# app-mcp imajı (specs/009-mobil-masaustu §2.6): doğrulama ajanının mobil/masaüstü aracı.
# Yalnızca app-mcp servisi kullanır; CI / test-runner imajına girmez (anayasa II).
#   docker build -t testingprobe-app-mcp:local toolchain/app-mcp
# Ağ: core-worker → app-mcp (app-mcp-net, internal); app-mcp → hosttaki Appium
# (host.docker.internal:4723, cihaz-net). Bkz. docs/CIHAZ-ALTYAPISI.md §Ağ.

FROM node:22.23.3-bookworm-slim@sha256:3ed98443660ff48413b5af19ecefce3b9d50845a901a43420d47cc63a9fddbe9 AS derleme
WORKDIR /build
COPY package.json package-lock.json tsconfig.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY src ./src
COPY test ./test
# test/duman.test.ts betiklerin ortam modülünü (scripts/duman-ortami.mjs) sınar; son imaja girmez.
COPY scripts ./scripts
# Birim testleri imaj derlemesinde de koşar (sahte Appium; ağ yok).
RUN npm test && npm prune --omit=dev --no-audit --no-fund

FROM node:22.23.3-bookworm-slim@sha256:3ed98443660ff48413b5af19ecefce3b9d50845a901a43420d47cc63a9fddbe9
LABEL org.opencontainers.image.title="testingprobe-app-mcp"
ENV NODE_ENV=production \
    APP_MCP_HOST=0.0.0.0 \
    APP_MCP_PORT=8932
WORKDIR /opt/app-mcp
COPY --from=derleme /build/package.json ./package.json
COPY --from=derleme /build/node_modules ./node_modules
COPY --from=derleme /build/dist/src ./dist/src
RUN chmod -R a-w /opt/app-mcp
USER node
EXPOSE 8932
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD ["node", "-e", "require('net').connect(8932,'127.0.0.1').on('connect',()=>process.exit(0)).on('error',()=>process.exit(1))"]
CMD ["node", "dist/src/index.js"]
