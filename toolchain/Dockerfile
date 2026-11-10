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

# Java araçları (009 §2.3–2.5): java-araclar.jar (JavaParser; yalnızca ayrıştırır) + Maven
# dağıtımı + e2e-app bağımlılıklarının çevrimdışı deposu. Sürümler sabit: JDK imajı özetle,
# Maven resmi SHA-512 ile, bağımlılıklar e2e-app-deps/pom.xml'le
# (demo-app/e2e-app/pom.xml'in birebir kopyası; tests/test_java.py denetler).
FROM eclipse-temurin:17.0.16_8-jdk-noble@sha256:bbc959486c469c589091571ba524e6a98f27e19bd99489c683d9b465e4f8db8d AS javabuild
# Maven: java-araclar/.mvn/wrapper ile aynı sürüm; resmi SHA-512 ile doğrulanır. (mvnw unzip yoksa
# tar.gz indirir ve zip'in sha256'sıyla karşılaştırıp başarısız olur; imajda doğrudan kurulur.)
ARG MAVEN_VERSION=3.9.11
ARG MAVEN_SHA512=bcfe4fe305c962ace56ac7b5fc7a08b87d5abd8b7e89027ab251069faebee516b0ded8961445d6d91ec1985dfe30f8153268843c89aa392733d1a3ec956c9978
RUN mkdir -p /build/maven \
 && curl -fsSL -o /tmp/maven.tar.gz \
      "https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/${MAVEN_VERSION}/apache-maven-${MAVEN_VERSION}-bin.tar.gz" \
 && echo "${MAVEN_SHA512}  /tmp/maven.tar.gz" | sha512sum -c - \
 && tar -xzf /tmp/maven.tar.gz -C /build/maven --strip-components=1 \
 && rm /tmp/maven.tar.gz \
 && /build/maven/bin/mvn --version
WORKDIR /build/java-araclar
COPY java-araclar/ ./
# Derle + JUnit golden testleri (sözleşme kırılırsa imaj derlenmez).
RUN /build/maven/bin/mvn -B -q -Dmaven.repo.local=/build/m2-araclar package \
 && cp target/java-araclar.jar /build/java-araclar.jar
# e2e-app deposunu ısıt: güvenilir pom + java-araclar'ın fikstür ağacı (aynı API'ler) derlenir;
# Surefire/TestNG sağlayıcısı da çekilir (test-runner'ın Java koşusu için). Ağ yalnızca burada.
WORKDIR /build/e2e-app
COPY e2e-app-deps/pom.xml ./pom.xml
RUN cp -r /build/java-araclar/src/test/resources/e2e-app/src ./src \
 && /build/maven/bin/mvn -B -q -Dmaven.repo.local=/build/e2e-m2 test-compile \
 && /build/maven/bin/mvn -B -q -Dmaven.repo.local=/build/e2e-m2 surefire:test \
      -Dtest=YokBoyleBirTest -Dsurefire.failIfNoSpecifiedTests=false \
 && rm -rf target src \
 && chmod -R a-w /build/e2e-m2 /build/maven
# Çalışma zamanı JDK'sı: derleme için gereksiz jmods/kaynak/man atılır.
RUN cp -a /opt/java/openjdk /build/jdk \
 && rm -rf /build/jdk/jmods /build/jdk/lib/src.zip /build/jdk/man /build/jdk/demo

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

# Java (009): JDK 17 (başsız kullanım), sabit Maven, java-araclar.jar ve e2e-app'in çevrimdışı
# deposu. Depo ve pom salt okunur: toolchain-worker `maven.repo.local.tail` olarak okur, koşu başına
# geçici bir baş deposuna yazar (worker/java.py). Model/MCP/ajan bağımlılığı içermez (anayasa II).
COPY --from=javabuild /build/jdk /opt/java/openjdk
COPY --from=javabuild /build/maven /opt/maven
COPY --from=javabuild /build/java-araclar.jar /opt/toolchain/java-araclar/java-araclar.jar
COPY --from=javabuild /build/e2e-m2 /opt/e2e-app/m2
COPY --chmod=444 e2e-app-deps/pom.xml /opt/e2e-app/pom.xml
ENV JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/java/openjdk/bin:/opt/maven/bin:$PATH
RUN java -version 2>&1 | head -n 1 \
 && java -jar /opt/toolchain/java-araclar/java-araclar.jar --help >/dev/null

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
