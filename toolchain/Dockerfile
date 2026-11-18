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
 && chmod -R a-w /build/e2e-m2
# Web + Java (011 §2.6; Playwright for Java + TestNG): ikinci ısıtılmış depo. Güvenilir pom
# (e2e-java-deps/pom.xml; demo-app/e2e-java/pom.xml ile bayt eşit) + toolchain'in kendi ısınma
# testi (e2e-java-isinma/: Playwright, TestNG, opentest4j API'leri) derlenir; Surefire TestNG
# sağlayıcısı da çekilir. Tarayıcı burada AÇILMAZ (bu aşamada yok); çevrimdışı açılış son imajda
# ağsız denenir (aşağıda, ci aşaması). Playwright Java sürücüsü (driver + driver-bundle) yalnızca
# jar'dır; koşuda geçici dizine açılır, ağa çıkmaz.
WORKDIR /build/e2e-java
COPY e2e-java-deps/pom.xml ./pom.xml
COPY e2e-java-isinma/src ./src
RUN /build/maven/bin/mvn -B -q -Dmaven.repo.local=/build/e2e-java-m2 test-compile \
 && /build/maven/bin/mvn -B -q -Dmaven.repo.local=/build/e2e-java-m2 surefire:test \
      -Dtest=YokBoyleBirTest -Dsurefire.failIfNoSpecifiedTests=false \
 && rm -rf target src \
 && chmod -R a-w /build/e2e-java-m2 /build/maven
# Çalışma zamanı JDK'sı: derleme için gereksiz jmods/kaynak/man atılır.
RUN cp -a /opt/java/openjdk /build/jdk \
 && rm -rf /build/jdk/jmods /build/jdk/lib/src.zip /build/jdk/man /build/jdk/demo

# ============================================================== 014 test dilleri: dil aşamaları
# Sözleşme specs/014-test-dilleri/plan.md §5. Ş0 aşamaları boş bıraktı; her şerit YALNIZ kendi
# işaretli bloğunu düzenler (bloklar arasındaki boş satırlar git birleştirmesi için korunur).
# Aşama çıktıları `ci` aşamasında "dil COPY" bölümünde kopyalanır.

# ==== dil-python (Ş1) başı ====
# Python test hattı (TASARIM §3.1; plan.md §5): /opt/e2e-python/venv güvenilir kilitten
# (e2e-python-deps/requirements.lock, --require-hashes, --no-deps) kurulur; tarayıcılar ortak
# (/ms-playwright). Playwright (PyPI) sürümü PLAYWRIGHT_VERSION ile eşit olmalı (R3). py-guard
# (yalnız stdlib; analiz ettiği kodu içe aktarmaz/çalıştırmaz) aynı dizine girer: `ci` aşamasında
# tek `COPY --from=dil-python /opt/e2e-python` yeter. Ağsız duman: paketler içe aktarılır.
FROM base AS dil-python
ARG PLAYWRIGHT_VERSION
COPY --chmod=444 e2e-python-deps/requirements.lock /opt/e2e-python/requirements.lock
COPY --chmod=444 py-guard/py_guard.py /opt/e2e-python/py-guard/py_guard.py
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    UV_PYTHON_DOWNLOADS=never uv venv --python /usr/bin/python3.12 /opt/e2e-python/venv \
 && UV_PYTHON_DOWNLOADS=never uv pip install --no-cache --require-hashes --no-deps \
      --python /opt/e2e-python/venv/bin/python -r /opt/e2e-python/requirements.lock \
 && installed="$(/opt/e2e-python/venv/bin/python -c 'import importlib.metadata as m; print(m.version("playwright"))')" \
 && { [ "$installed" = "$PLAYWRIGHT_VERSION" ] || { \
      echo "playwright (PyPI) $installed != PLAYWRIGHT_VERSION $PLAYWRIGHT_VERSION: e2e-python-deps kilidini güncelleyin" >&2; exit 1; }; }
RUN --network=none /opt/e2e-python/venv/bin/python -I -c \
      "import playwright, pytest, pytest_playwright, pytest_repeat, appium, allure_pytest" \
 && /usr/bin/python3.12 -I /opt/e2e-python/py-guard/py_guard.py --help >/dev/null \
 && chmod -R a-w /opt/e2e-python
# ==== dil-python (Ş1) sonu ====

# ==== dil-csharp (Ş2) başı ====
# C# / .NET 10 (TASARIM §3.2): .NET SDK + cs-araclar (Roslyn; yalnızca ayrıştırır) + iki C# hedef
# projesinin (web: e2e-csharp, windows: e2e-app-csharp) çevrimdışı, ısıtılmış NuGet paket klasörü.
# SDK imajı özetle sabit; paketler güvenilir kopyaların kilit dosyalarıyla (--locked-mode;
# e2e-csharp-deps/, demo projelerle bayt eşit — tests/test_csharp.py denetler). Ağ yalnızca burada.
FROM mcr.microsoft.com/dotnet/sdk:10.0.401-noble@sha256:e70cdb7f80b0348f5cb85f19a8f670fca061f033d57eed12fa003d58b0e06317 AS dil-csharp
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1
WORKDIR /build/cs-araclar
COPY cs-araclar/ ./
# Derle + NUnit golden testleri (sözleşme kırılırsa imaj derlenmez), sonra tek dizine yayımla.
RUN dotnet test CsAraclar.slnx -c Release --nologo \
 && dotnet publish src/CsAraclar -c Release --no-restore -o /build/cs-araclar-yayin \
 && rm -rf /root/.nuget/packages
# Hedef projelerin paketleri: yalnızca güvenilir proje/kilit dosyalarıyla restore (kaynak kod
# gerekmez). Playwright paketi tarayıcı indirmez (tarayıcılar ortak: /ms-playwright).
COPY e2e-csharp-deps/ /build/e2e-csharp-deps/
RUN for d in web windows; do \
      NUGET_PACKAGES=/build/e2e-csharp/nuget dotnet restore --locked-mode \
        "$(ls /build/e2e-csharp-deps/$d/*.csproj)" || exit 1; \
    done \
 && rm -rf /build/e2e-csharp-deps/*/obj \
 && chmod -R a-w /build/e2e-csharp/nuget
# Çalışma zamanı SDK'sı (derleme + dotnet test); belgeler/örnekler atılır.
RUN cp -a /usr/share/dotnet /build/dotnet
# ==== dil-csharp (Ş2) sonu ====

# ==== dil-statik (Ş3 Kotlin / Ş4 Swift) başı ====
FROM base AS dil-statik
RUN mkdir -p /opt/dil-statik
# Ortak tree-sitter çekirdeği (Ş3 + Ş4; tek satır). Paketler /opt/dil-statik'e (worker PYTHONPATH'e
# eklenir); ağ yalnız derleme anında, sürümler sabit.
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv pip install --no-cache --python /usr/bin/python3.12 --target /opt/dil-statik \
      tree-sitter==0.26.1
# ---- Ş3 Kotlin satırları başı ----
# Hash kilitli (statik-deps/kotlin.txt; tree-sitter çekirdeği yukarıdaki ortak satırla aynı sürüm).
COPY --chmod=444 statik-deps/kotlin.txt /build/statik-deps/kotlin.txt
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv pip install --no-cache --python /usr/bin/python3.12 --require-hashes --no-deps \
      --target /opt/dil-statik -r /build/statik-deps/kotlin.txt
# ---- Ş3 Kotlin satırları sonu ----

# ---- Ş4 Swift satırları başı ----
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv pip install --no-cache --python /usr/bin/python3.12 --target /opt/dil-statik \
      tree-sitter-swift==0.7.4
# ---- Ş4 Swift satırları sonu ----
# ==== dil-statik sonu ====

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

# Katman sırası (OPS-L3): seyrek değişen Java katmanları ve ağsız duman testi, sık değişen kaynak
# COPY'lerinden (ast-guard/symbols dist, probe, Python paketleri) ÖNCE gelir; Python/TS kaynak
# değişikliği Java ısınmasını ve duman testini yeniden koşturmaz. Davranış aynıdır.

# Java (009): JDK 17 (başsız kullanım), sabit Maven, java-araclar.jar ve e2e-app'in çevrimdışı
# deposu. Depo ve pom salt okunur: toolchain-worker `maven.repo.local.tail` olarak okur, koşu başına
# geçici bir baş deposuna yazar (worker/java.py). Model/MCP/ajan bağımlılığı içermez (anayasa II).
COPY --from=javabuild /build/jdk /opt/java/openjdk
COPY --from=javabuild /build/maven /opt/maven
COPY --from=javabuild /build/java-araclar.jar /opt/toolchain/java-araclar/java-araclar.jar
COPY --from=javabuild /build/e2e-m2 /opt/e2e-app/m2
COPY --chmod=444 e2e-app-deps/pom.xml /opt/e2e-app/pom.xml
COPY --from=javabuild /build/e2e-java-m2 /opt/e2e-java/m2
COPY --chmod=444 e2e-java-deps/pom.xml /opt/e2e-java/pom.xml
ENV JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/java/openjdk/bin:/opt/maven/bin:$PATH
RUN java -version 2>&1 | head -n 1 \
 && java -jar /opt/toolchain/java-araclar/java-araclar.jar --help >/dev/null

# Web + Java duman testi (011 §2.6), AĞSIZ: güvenilir pom çevrimdışı (-o, ısıtılmış depo salt
# okunur kuyruk) derlenir, ısınma testi imajdaki tarayıcıyı (/ms-playwright) indirme yapmadan
# açar. Sürücü/tarayıcı sürümü uyuşmazsa ya da depo eksikse imaj derlenmez.
COPY e2e-java-isinma/src /tmp/e2e-java-duman/src
RUN --network=none cp /opt/e2e-java/pom.xml /tmp/e2e-java-duman/pom.xml \
 && cd /tmp/e2e-java-duman \
 && MAVEN_SKIP_RC=1 PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 HOME=/tmp/e2e-java-duman \
    /opt/maven/bin/mvn -B -q -o -Dmaven.repo.local=/tmp/e2e-java-duman/m2 \
      -Dmaven.repo.local.tail=/opt/e2e-java/m2 -Dmaven.compiler.proc=none \
      -Dtest=com/antreklabs/bayi/birim/IsinmaTest.java -Dsurefire.failIfNoSpecifiedTests=true \
      test-compile surefire:test \
 && grep -q 'tests="1" errors="0" skipped="0" failures="0"' \
      target/surefire-reports/TEST-com.antreklabs.bayi.birim.IsinmaTest.xml \
 && cd / && rm -rf /tmp/e2e-java-duman /tmp/playwright-java-*

# ==== dil COPY (014) başı ====
# ---- Ş1 Python ----
COPY --from=dil-python /opt/e2e-python /opt/e2e-python

# ---- Ş2 C# ----
# .NET SDK, cs-araclar ve ısıtılmış NuGet klasörü (salt okunur; worker/diller/csharp.py restore'da
# kaynak + geri dönüş klasörü olarak kullanır, yazılabilir NUGET_PACKAGES koşu başına geçicidir).
COPY --from=dil-csharp /build/dotnet /usr/share/dotnet
COPY --from=dil-csharp /build/cs-araclar-yayin /opt/cs-araclar
COPY --from=dil-csharp /build/e2e-csharp/nuget /opt/e2e-csharp/nuget
COPY --chmod=444 e2e-csharp-deps/web/ /opt/e2e-csharp/web/
COPY --chmod=444 e2e-csharp-deps/windows/ /opt/e2e-csharp/windows/
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 \
    TP_DOTNET=/usr/share/dotnet/dotnet \
    TP_CS_ARACLAR_DLL=/opt/cs-araclar/cs-araclar.dll \
    TP_E2E_CSHARP_DEPS=/opt/e2e-csharp
# C# duman testi, AĞSIZ: güvenilir web projesi çevrimdışı kilitli restore + derleme
# (worker/diller/csharp.py ile aynı bayraklar) ve cs-araclar açılışı. Paket eksikse imaj derlenmez.
RUN --network=none /usr/share/dotnet/dotnet /opt/cs-araclar/cs-araclar.dll --help >/dev/null \
 && mkdir -p /tmp/cs-duman && cp /opt/e2e-csharp/web/* /tmp/cs-duman/ \
 && cd /tmp/cs-duman \
 && HOME=/tmp/cs-duman NUGET_PACKAGES=/tmp/cs-duman/nuget /usr/share/dotnet/dotnet restore \
      --locked-mode --source /opt/e2e-csharp/nuget -p:RestoreFallbackFolders=/opt/e2e-csharp/nuget \
      "$(ls /tmp/cs-duman/*.csproj)" \
 && cd / && rm -rf /tmp/cs-duman

# ---- Ş3/Ş4 statik (tree-sitter) ----
COPY --from=dil-statik /opt/dil-statik /opt/dil-statik
# ==== dil COPY (014) sonu ====

COPY --from=nodebuild /build/ast-guard/package.json ./ast-guard/package.json
COPY --from=nodebuild /build/ast-guard/dist ./ast-guard/dist
COPY --from=nodebuild /build/ast-guard/node_modules ./ast-guard/node_modules
COPY --from=nodebuild /build/symbols/package.json ./symbols/package.json
COPY --from=nodebuild /build/symbols/dist ./symbols/dist
COPY --from=nodebuild /build/symbols/node_modules ./symbols/node_modules
COPY probe ./probe

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
