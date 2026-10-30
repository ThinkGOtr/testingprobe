# syntax=docker/dockerfile:1
# Toolchain image shared by toolchain-worker, test-runner and playwright-mcp (research R4).
# PLAYWRIGHT_VERSION comes from .playwright-version (make up); the digest pins v1.64.1-noble.
ARG PLAYWRIGHT_VERSION

FROM ghcr.io/astral-sh/uv:0.8@sha256:1d31be550ff927957472b2a491dc3de1ea9b5c2d319a9cea5b6a48021e2990a6 AS uv

FROM mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-noble@sha256:47b510dd9230bf0b9bfc9b20102241e577ea7a99334ab4c3ca19f19770e9b8ea
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

WORKDIR /opt/toolchain

# Node: @playwright/mcp + @playwright/test; overrides force a single playwright-core (= image browsers).
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --omit=dev --no-audit --no-fund \
 && npm cache clean --force
RUN installed="$(node -p "require('playwright-core/package.json').version")"; \
    [ "$installed" = "$PLAYWRIGHT_VERSION" ] || { \
      echo "playwright-core $installed != PLAYWRIGHT_VERSION $PLAYWRIGHT_VERSION: update toolchain/package.json" >&2; exit 1; }

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

USER pwuser
WORKDIR /home/pwuser
EXPOSE 8100 8200 8931
