# syntax=docker/dockerfile:1
# Toolchain imajı (research R4), iki hedef:
#   ci  (varsayılan, son aşama): toolchain-worker, test-runner ve GitHub CI Yol A (test-local).
#        Playwright MCP sunucusu YOKTUR — anayasa II: "CI ortamında model anahtarı, MCP sunucusu ve
#        ajan bağımlılığı bulunamaz". security/no-mcp-in-image.sh bunu imaj üzerinde denetler.
#   mcp : ci + /opt/mcp (@playwright/mcp, mcp/package-lock.json). Yalnızca playwright-mcp servisi.
#   docker build --target mcp -t testingprobe-toolchain-mcp:local toolchain
# PLAYWRIGHT_VERSION comes from .playwright-version (make up); the digest pins v1.64.1-noble.
ARG PLAYWRIGHT_VERSION

FROM ghcr.io/astral-sh/uv:0.8@sha256:1d31be550ff927957472b2a491dc3de1ea9b5c2d319a9cea5b6a48021e2990a6 AS uv

FROM mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-noble@sha256:47b510dd9230bf0b9bfc9b20102241e577ea7a99334ab4c3ca19f19770e9b8ea AS base

# TypeScript araçları (ast-guard, sembol çıkarıcı) aynı sabit imajda derlenir; son imaja yalnızca
# dist/ + üretim bağımlılıkları (ts-morph) girer. Testleri repo içinde koşar (npm test).
FROM base AS nodebuild
WORKDIR /build/ast-guard
COPY ast-guard/package.json ast-guard/package-lock.json ast-guard/tsconfig.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY ast-guard/src ./src
COPY ast-guard/test ./test
RUN npm run build && npm prune --omit=dev --no-audit --no-fund
WORKDIR /build/symbols
COPY symbols/package.json symbols/package-lock.json symbols/tsconfig.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY symbols/src ./src
COPY symbols/test ./test
RUN npm run build && npm prune --omit=dev --no-audit --no-fund

FROM base AS ci
ARG PLAYWRIGHT_VERSION
LABEL org.opencontainers.image.title="testingprobe-toolchain" \
      io.testingprobe.playwright-version="${PLAYWRIGHT_VERSION}"

ENV UV_PYTHON=/usr/bin/python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/toolchain/.venv \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH=/opt/toolchain/bin:/opt/toolchain/.venv/bin:$PATH

# PID 1 = tini (-s alt biçici, -g sinyal süreç grubuna): Chromium yardımcı süreçleri PID 1'e
# devredilir; Python/node PID 1 onları biçmez (zombi birikimi). Compose `init: true` gerekmez.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini \
 && rm -rf /var/lib/apt/lists/* \
 && /usr/bin/tini --version

WORKDIR /opt/toolchain

# Node: @playwright/test (+ axe, allure) — MCP sunucusu yok (mcp hedefi ekler); overrides force a
# single playwright-core (= image browsers).
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --omit=dev --no-audit --no-fund \
 && npm cache clean --force
RUN installed="$(node -p "require('playwright-core/package.json').version")"; \
    [ "$installed" = "$PLAYWRIGHT_VERSION" ] || { \
      echo "playwright-core $installed != PLAYWRIGHT_VERSION $PLAYWRIGHT_VERSION: update toolchain/package.json" >&2; exit 1; }

# demo-app e2e bağımlılıkları, çevrimdışı (/check ve /run checkout'a bağlar): demo-app/e2e'nin
# package.json + package-lock.json'ının birebir kopyası (e2e-deps/; tests/test_e2e_deps.py denetler).
# eslint.config.js buradaki güvenilir kopyadır: toolchain-worker yalnızca bununla aynı olanı yükler.
WORKDIR /opt/e2e
# e2e-deps/ = manifestler + eslint.config.js (+ içe aktardığı yerel modüller, varsa tools/).
COPY e2e-deps/ ./
RUN npm ci --ignore-scripts --no-audit --no-fund \
 && npm cache clean --force \
 && installed="$(node -p "require('playwright-core/package.json').version")" \
 && { [ "$installed" = "$PLAYWRIGHT_VERSION" ] || { \
      echo "e2e playwright-core $installed != PLAYWRIGHT_VERSION $PLAYWRIGHT_VERSION" >&2; exit 1; }; } \
 && chmod -R a-w /opt/e2e
WORKDIR /opt/toolchain

COPY --from=nodebuild /build/ast-guard/package.json ./ast-guard/package.json
COPY --from=nodebuild /build/ast-guard/dist ./ast-guard/dist
COPY --from=nodebuild /build/ast-guard/node_modules ./ast-guard/node_modules
COPY --from=nodebuild /build/symbols/package.json ./symbols/package.json
COPY --from=nodebuild /build/symbols/dist ./symbols/dist
COPY --from=nodebuild /build/symbols/node_modules ./symbols/node_modules
COPY probe ./probe

# Allure 3 CLI (Node, sabit sürüm): test-runner her koşudan sonra statik tek dosyalık Allure
# raporu üretir (allure2 eklentisi, ALLURE_NO_ANALYTICS; ağ yok, AI yok). Yapılandırma güvenilir
# kopyadır; commit'teki allurerc okunmaz.
WORKDIR /opt/allure
COPY allure/package.json allure/package-lock.json allure/allurerc.mjs ./
RUN npm ci --ignore-scripts --omit=dev --no-audit --no-fund \
 && npm cache clean --force \
 && node node_modules/allure/cli.js --version \
 && chmod -R a-w /opt/allure
WORKDIR /opt/toolchain

# Python: dependencies first (cache), then the project itself.
COPY pyproject.toml uv.lock ./
# uv is only mounted at build time; it is not shipped in the image.
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-install-project --no-cache
COPY toolchain_common ./toolchain_common
COPY worker ./worker
COPY runner ./runner
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-editable --no-cache

COPY bin ./bin

# Bağlama noktaları pwuser'ın: boş bir named volume ilk bağlamada bu sahipliği alır.
# /checks = merge kapısı volume'ü (tp_checks; yalnızca toolchain-worker rw, test-runner bağlamaz).
# /forge-mirror = GitHub modu aynası (tp_forge_mirror; toolchain-worker rw, test-runner ro).
RUN mkdir -p /artifacts /checks /forge-mirror \
 && chown pwuser:pwuser /artifacts /checks /forge-mirror

USER pwuser
WORKDIR /home/pwuser
EXPOSE 8100 8200
ENTRYPOINT ["/usr/bin/tini", "-s", "-g", "--"]

# ---------------------------------------------------------------------------------------- mcp
# Playwright MCP sunucusu (ajanın tarayıcısı; core-worker → mcp-net). CI/test-runner imajına girmez.
FROM ci AS mcp
ARG PLAYWRIGHT_VERSION
LABEL org.opencontainers.image.title="testingprobe-toolchain-mcp"
USER root
WORKDIR /opt/mcp
COPY mcp/package.json mcp/package-lock.json ./
RUN npm ci --ignore-scripts --omit=dev --no-audit --no-fund \
 && npm cache clean --force \
 && installed="$(node -p "require('playwright-core/package.json').version")" \
 && { [ "$installed" = "$PLAYWRIGHT_VERSION" ] || { \
      echo "mcp playwright-core $installed != PLAYWRIGHT_VERSION $PLAYWRIGHT_VERSION" >&2; exit 1; }; } \
 && chmod -R a-w /opt/mcp
USER pwuser
WORKDIR /home/pwuser
EXPOSE 8931

# Varsayılan hedef (hedef verilmeyen `docker build`): MCP'siz ci imajı.
FROM ci
