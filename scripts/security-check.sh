#!/usr/bin/env bash
# make security-check — research R10'daki 4 güvenlik kontrolü (FR-015, SC-004) + Faz 1'in 4 kontrolü + Faz 3 kapı yalıtımı ve CI imajında ajan yok.
# Her kontrol PASS/FAIL yazar; özet "N/10"; herhangi bir FAIL → ≠0.
#   1. Host'a açılan tüm portlar yalnızca 127.0.0.1'e bağlı (istisna: GCP katmanında edge 80/443)
#   2. test-runner'dan postgres, core-api, playwright-mcp, host (host.docker.internal) ve internete
#      erişim yok (demo-app-web ve demo-app-api'ye var; `mobil` profilinde appium-gw:4723'e,
#      `mobil-windows` profilinde appium-gw-windows:4723'e var)
#   3. tp_app audit_event'i UPDATE/DELETE/TRUNCATE edemez
#   4. Depoda sır yok (gitleaks; git geçmişi + commit edilmemiş izlenen/izlenmeyen dosyalar)
#   5. demoapp_ro yalnızca izinli tablo/kolonları okur; yazamaz, parola özeti ve sipariş verisi kapalı
#   6. Model anahtarı değişkeni yalnızca core-worker'da (anayasa); core-api'de tanımlı değil.
#      Asistanın `ci_log` okuma token'ı (GITHUB_ACTIONS_READ_TOKEN, contracts/env.md) da aynı sınıfta
#   7. playwright-mcp (ajan tarayıcısı) core-api, jira-sim, postgres, demo-app-api (/test/*),
#      test-runner ve internete erişemez; demo-app-web'e erişir; core-worker MCP'ye mcp-net
#      üzerinden erişir
#   8. Yazma yetkili dış sistem kimlikleri (Jira/Xray/GitHub) yalnızca core-worker'da;
#      DEMOAPP_TEST_TOKEN yalnızca demo-app-api ve test-runner'da; gerçek Jira kipinde okuma hesabı
#      (JIRA_READ_*) ADD_COMMENTS/CREATE_ISSUES/EDIT_ISSUES iznini taşımaz (mypermissions;
#      AI-ASISTAN-PLANI §5.6, R14 — scripts/jira-okuma-izni.py; simülatörde atlanır)
#   9. Merge kapısı (checks/<sha>.json) ayrı tp_checks volume'ünde: yalnızca toolchain-worker yazar,
#      test-runner bağlamaz ve yazdığı kanarya kapıda görünmez; toolchain-worker belirteç ister,
#      test-runner'da belirteç yok (toolchain/security/checks-isolation.sh)
#  10. CI/test imajlarında ajan yok (Constitution II): test-runner ve toolchain-worker'da
#      @playwright/mcp, mcp, anthropic, claude_agent_sdk çözülemez (toolchain/security/no-mcp-in-image.sh)
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

GITLEAKS_IMAGE="zricethezav/gitleaks:v8.28.0@sha256:cdbb7c955abce02001a9f6c9f602fb195b7fadc1e812065883f695d1eeaba854"

passed=0
pass() { printf 'PASS  %s\n' "$*"; passed=$((passed + 1)); }
fail() { printf 'FAIL  %s\n' "$*"; }
info() { printf '      %s\n' "$*"; }

docker info >/dev/null 2>&1 || die "Docker çalışmıyor"
[ -f .env ] || die ".env bulunamadı — 'make env' çalıştırın"
rows="$(ps_rows || true)"

# --- 9. Merge kapısı yalıtımı ---------------------------------------------------
check_gate_isolation() {
  local out
  if out="$("$TP_REPO_ROOT/toolchain/security/checks-isolation.sh" 2>&1)"; then
    pass "9/kapı: checks/<sha>.json yalnızca toolchain-worker'da (tp_checks); test-runner ulaşamıyor"
  else
    fail "9/kapı: merge kapısı yalıtımı bozuk"
    printf '%s\n' "$out" | while IFS= read -r l; do info "$l"; done
  fi
}

# --- 10. CI imajında ajan yok --------------------------------------------------
check_no_agent_in_ci() {
  local out svc ok=1
  for svc in test-runner toolchain-worker; do
    if ! out="$("$TP_REPO_ROOT/toolchain/security/no-mcp-in-image.sh" compose "$svc" 2>&1)"; then
      ok=0
      printf '%s\n' "$out" | while IFS= read -r l; do info "${svc}: $l"; done
    fi
  done
  if [ "$ok" -eq 1 ]; then
    pass "10/CI'da AI yok: test-runner ve toolchain-worker imajında MCP/model istemcisi yok"
  else
    fail "10/CI'da AI yok: CI imajında ajan bağımlılığı bulundu"
  fi
}

# --- 1. Port bağlama adresleri -------------------------------------------------
# (a) statik: compose yapılandırmasındaki her port host_ip=127.0.0.1 olmalı
# (b) çalışma anı: docker compose ps'teki her yayınlanmış port 127.0.0.1'de olmalı
check_ports() {
  local cfg_bad live_bad live_count
  cfg_bad="$(compose config --format json | python3 -c '
import json, sys
cfg = json.load(sys.stdin)
for name, svc in sorted((cfg.get("services") or {}).items()):
    for p in svc.get("ports") or []:
        if isinstance(p, dict):
            ip = p.get("host_ip") or "0.0.0.0"
            # GCP dış kapısı (deploy/gcp): yalnızca edge/Caddy 80 ve 443 dışa açılabilir.
            if name == "edge" and str(p.get("published")) in ("80", "443") and p.get("target") in (80, 443):
                continue
            if p.get("published") and ip != "127.0.0.1":
                print("%s: %s:%s" % (name, ip, p.get("published")))
        else:
            print("%s: tanımlanamayan port biçimi %r" % (name, p))
')" || { fail "1/port: compose yapılandırması okunamadı"; return; }
  live_count="$(printf '%s\n' "$rows" | cut -f5 | tr ',' '\n' | grep -c -- '->' || true)"
  live_bad="$(printf '%s\n' "$rows" | awk -F '\t' '$5 != "-" && $5 != "" {
      n = split($5, a, ","); for (i = 1; i <= n; i++) {
        if ($1 == "edge" && a[i] ~ /^(0\.0\.0\.0|\[::\]|::):(80|443)->(80|443)(\/tcp)?$/) continue
        if (a[i] !~ /^127\.0\.0\.1:/) print $1 ": " a[i] } }')"
  if [ -n "$cfg_bad" ] || [ -n "$live_bad" ]; then
    fail "1/port: 127.0.0.1 dışına açılan port var"
    [ -z "$cfg_bad" ] || printf '%s\n' "$cfg_bad" | while IFS= read -r l; do info "yapılandırma  $l"; done
    [ -z "$live_bad" ] || printf '%s\n' "$live_bad" | while IFS= read -r l; do info "çalışan       $l"; done
  elif [ "$live_count" -eq 0 ]; then
    fail "1/port: yayınlanmış port bulunamadı (ortam çalışmıyor?) — kontrol anlamsız"
  else
    pass "1/port: $live_count yayınlanmış portun tümü yalnızca 127.0.0.1'de"
  fi
}

# --- 2. test-runner ağ izolasyonu ----------------------------------------------
NET_JS='
const net = require("net");
const targets = process.argv.slice(1).map((t) => { const i = t.lastIndexOf(":"); return [t.slice(0, i), Number(t.slice(i + 1))]; });
let left = targets.length;
setTimeout(() => process.exit(0), 8000);
for (const [h, p] of targets) {
  let done = false;
  const s = net.connect({ host: h, port: p });
  const fin = (r) => {
    if (done) return; done = true; s.destroy();
    console.log(h + ":" + p + " " + r);
    if (--left === 0) process.exit(0);
  };
  const t = setTimeout(() => fin("TIMEOUT"), 3000);
  s.on("connect", () => { clearTimeout(t); fin("OPEN"); });
  s.on("error", (e) => { clearTimeout(t); fin("ERR_" + (e.code || "UNKNOWN")); });
}
'
check_isolation() {
  local out ok=1 target res
  if ! svc_running test-runner; then
    fail "2/izolasyon: test-runner çalışmıyor — kontrol yapılamadı"; return
  fi
  # host.docker.internal: test-runner hosta (Appium dahil) DOĞRUDAN çıkamaz; tek yol appium-gw
  # (`mobil` profili, yalnızca host:4723'e yönlendirir; 009 §2.7, docs/CIHAZ-ALTYAPISI.md §5.1).
  local targets="postgres:5432 core-api:8000 playwright-mcp:8931 example.com:443 host.docker.internal:4723 host.docker.internal:8081 demo-app-web:8080 demo-app-api:8000"
  local gw=0
  if svc_running appium-gw; then gw=1; targets="$targets appium-gw:4723"; fi
  # Windows VM yönlendiricisi (`mobil-windows` profili; hedef yalnızca TP_WINDOWS_VM_APPIUM).
  if svc_running appium-gw-windows; then targets="$targets appium-gw-windows:4723"; fi
  # shellcheck disable=SC2086  # hedefler bilinçli olarak sözcüklere bölünür
  if ! out="$(compose exec -T test-runner node -e "$NET_JS" $targets 2>&1)"; then
    fail "2/izolasyon: test-runner içinde node çalıştırılamadı"; info "$out"; return
  fi
  for target in $targets; do
    res="$(printf '%s\n' "$out" | awk -v t="$target" '$1 == t { print $2 }' | head -n 1)"
    [ -n "$res" ] || res="SONUÇ_YOK"
    if [ "$target" = "demo-app-web:8080" ] || [ "$target" = "demo-app-api:8000" ] || [ "$target" = "appium-gw:4723" ] || [ "$target" = "appium-gw-windows:4723" ]; then
      # pozitif kontrol: erişilmesi gereken hedef; erişilemiyorsa test anlamsız
      if [ "$res" = "OPEN" ]; then info "$target erişilebilir (beklenen)"; else ok=0; info "$target $res — erişilebilir olmalıydı (pozitif kontrol)"; fi
    else
      if [ "$res" = "OPEN" ]; then ok=0; info "$target AÇIK — erişilememeliydi"; else info "$target engelli ($res)"; fi
    fi
  done
  if [ "$ok" -eq 1 ]; then
    [ "$gw" -eq 1 ] || info "appium-gw çalışmıyor (mobil profili kapalı): Appium yolu denetlenmedi"
    pass "2/izolasyon: test-runner postgres, core-api, playwright-mcp, host ve internete erişemiyor"
  else
    fail "2/izolasyon: test-runner ağ kısıtı beklendiği gibi değil"
  fi
}

# --- 3. tp_app denetim kaydını değiştiremez --------------------------------------
# Her deneme BEGIN … ROLLBACK içinde: yetki yanlışlıkla verilmişse bile hiçbir şey değişmez.
check_audit_role() {
  local ok=1 stmt out
  if ! svc_healthy postgres; then
    fail "3/denetim: postgres çalışmıyor — kontrol yapılamadı"; return
  fi
  if ! out="$(psql_app -v ON_ERROR_STOP=1 -At -c "select count(*) from audit_event" 2>&1)"; then
    fail "3/denetim: tp_app audit_event'i okuyamıyor (pozitif kontrol)"; info "$out"; return
  fi
  for stmt in "UPDATE audit_event SET aktor = aktor" "DELETE FROM audit_event" "TRUNCATE audit_event"; do
    if out="$(printf 'BEGIN;\n%s;\nROLLBACK;\n' "$stmt" | psql_app -v ON_ERROR_STOP=1 -q 2>&1)"; then
      ok=0; info "$stmt → İZİN VERİLDİ (geri alındı)"
    elif printf '%s' "$out" | grep -qi "permission denied"; then
      info "$stmt → permission denied"
    else
      ok=0; info "$stmt → beklenmeyen hata: $(printf '%s' "$out" | head -n 1)"
    fi
  done
  if [ "$ok" -eq 1 ]; then
    pass "3/denetim: tp_app audit_event üzerinde UPDATE/DELETE/TRUNCATE yapamıyor"
  else
    fail "3/denetim: tp_app denetim kaydını değiştirebiliyor veya kontrol yapılamadı"
  fi
}

# --- 4. Depoda sır yok (gitleaks) ------------------------------------------------
# (a) `gitleaks git`: tüm commit geçmişi (repo salt okunur bağlanır).
# (b) `gitleaks dir`: commit edilmemiş içerik — yalnızca git'in izlediği veya izleyeceği
#     dosyalar (`git ls-files -co --exclude-standard`). .env, exports/, node_modules gibi
#     .gitignore'daki dosyalar bilinçli olarak taranmaz: zaten depoya giremezler ve .env
#     her zaman gerçek sır içerir. Dosyalar host'ta geçici kopya oluşturmadan tar akışıyla
#     konteynere aktarılır (Colima'da paylaşılmayan dizin sorunu da olmaz).
check_secrets() {
  local ok=1 out
  if ! out="$(docker run --rm -v "$TP_REPO_ROOT:/repo:ro" \
        -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*' \
        "$GITLEAKS_IMAGE" git /repo --no-banner --redact --no-color --verbose --exit-code 1 2>&1)"; then
    ok=0; info "git geçmişi:"; printf '%s\n' "$out" | tail -n 30 | while IFS= read -r l; do info "  $l"; done
  else
    info "git geçmişi: $(printf '%s\n' "$out" | grep -E 'commits scanned' | sed 's/.*INF //' | head -n 1) sızıntı yok"
  fi
  if ! out="$(git ls-files -z -co --exclude-standard \
        | while IFS= read -r -d '' f; do [ -f "$f" ] && printf '%s\0' "$f"; done \
        | tar -cf - --null -T - \
        | docker run --rm -i --entrypoint sh "$GITLEAKS_IMAGE" -c \
            'mkdir -p /tmp/scan && tar -xf - -C /tmp/scan && gitleaks dir /tmp/scan --no-banner --redact --no-color --verbose --exit-code 1' 2>&1)"; then
    ok=0; info "çalışma ağacı:"; printf '%s\n' "$out" | tail -n 30 | while IFS= read -r l; do info "  $l"; done
  else
    info "çalışma ağacı (izlenen + izlenmeyen, .gitignore hariç): sızıntı yok"
  fi
  if [ "$ok" -eq 1 ]; then
    pass "4/sır: gitleaks depoda sır bulmadı"
  else
    fail "4/sır: gitleaks bulgusu var veya tarama çalışmadı"
  fi
}

# --- 5. demoapp_ro en az yetki -----------------------------------------------------
# Pozitif: ayar/urun/kampanya ve bayi'nin izinli kolonları okunur.
# Negatif: parola özeti, sipariş/sepet/oturum tabloları, her türlü yazma ve tablo oluşturma reddedilir.
check_demoapp_ro() {
  local ok=1 stmt out
  if ! svc_healthy postgres; then
    fail "5/salt-okuma: postgres çalışmıyor — kontrol yapılamadı"; return
  fi
  for stmt in "SELECT count(*) FROM ayar" "SELECT count(*) FROM urun" "SELECT count(*) FROM kampanya" \
              "SELECT id, kullanici_adi, ad, kredi_limiti FROM bayi LIMIT 1"; do
    if out="$(psql_demoapp_ro -v ON_ERROR_STOP=1 -At -c "$stmt" 2>&1)"; then
      info "$stmt → okunabiliyor (beklenen)"
    else
      ok=0; info "$stmt → okunamadı (pozitif kontrol): $(printf '%s' "$out" | head -n 1)"
    fi
  done
  for stmt in "SELECT parola_hash FROM bayi" "SELECT count(*) FROM siparis" "SELECT count(*) FROM sepet_satiri" \
              "SELECT count(*) FROM oturum" "SELECT count(*) FROM test_kirilma" "UPDATE ayar SET deger = deger" "CREATE TABLE tp_probe(x int)"; do
    if out="$(printf 'BEGIN;\n%s;\nROLLBACK;\n' "$stmt" | psql_demoapp_ro -v ON_ERROR_STOP=1 -q 2>&1)"; then
      ok=0; info "$stmt → İZİN VERİLDİ (geri alındı)"
    elif printf '%s' "$out" | grep -qiE "permission denied|read-only transaction"; then
      info "$stmt → reddedildi"
    else
      ok=0; info "$stmt → beklenmeyen hata: $(printf '%s' "$out" | head -n 1)"
    fi
  done
  # Parola düz metin istenirse libpq göndermesin: demoapp URL'leri require_auth taşımalı
  # (core'un TP_DATABASE_URL'ine tp_core.config ekler).
  local urls
  urls="$(compose config --format json | python3 -c '
import json, sys
cfg = json.load(sys.stdin)
for name, svc in sorted((cfg.get("services") or {}).items()):
    for k, v in (svc.get("environment") or {}).items():
        if k in ("DEMOAPP_DATABASE_URL", "DEMOAPP_RO_DATABASE_URL") and "require_auth=scram-sha-256" not in str(v):
            print("%s: %s" % (name, k))
')" || urls="compose yapılandırması okunamadı"
  if [ -n "$urls" ]; then
    ok=0; printf '%s\n' "$urls" | while IFS= read -r l; do info "require_auth=scram-sha-256 yok: $l"; done
  fi
  if [ "$ok" -eq 1 ]; then
    pass "5/salt-okuma: demoapp_ro yalnızca izinli verileri okuyabiliyor"
  else
    fail "5/salt-okuma: demoapp_ro yetkileri beklendiği gibi değil"
  fi
}

# --- 6. Model anahtarı yalnızca core-worker'da ----------------------------------------
# Değer yazdırılmaz; yalnızca değişkenin konteyner ortamında tanımlı olup olmadığına bakılır.
check_model_key() {
  local svc ok=1
  if ! svc_running core-worker; then
    fail "6/anahtar: core-worker çalışmıyor — kontrol yapılamadı"; return
  fi
  if compose exec -T core-worker sh -c 'env | grep -q "^ANTHROPIC_API_KEY="'; then
    info "core-worker: ANTHROPIC_API_KEY tanımlı (beklenen; boş olabilir → REPLAY)"
  else
    ok=0; info "core-worker: ANTHROPIC_API_KEY tanımlı değil (beklenen: tanımlı)"
  fi
  # Bilgi (başarısızlık değil): gerçek GitHub kipinde ayrı okuma token'ı yoksa ci_log forge
  # kimliğiyle okur (yalnız GET; en az yetki sapması). Değer yazdırılmaz, yalnız boşluğa bakılır.
  if compose exec -T core-worker sh -c '[ "$(printf %s "${TP_FORGE:-local}" | tr A-Z a-z)" = github ] && [ -z "${GITHUB_ACTIONS_READ_TOKEN}${GITHUB_READ_TOKEN}" ]' 2>/dev/null; then
    info "core-worker: ci_log forge kimliğiyle okuyor (actions:read token önerilir: GITHUB_ACTIONS_READ_TOKEN)"
  fi
  # Çalışma alanı kimliği ve asistanın CI log okuma token'ı da anahtarla aynı sınıftadır
  # (sır; yalnızca core-worker). Token core-worker'da boş olabilir (mevcut okuma kimliği kullanılır).
  for svc in core-api review-portal jira-sim toolchain-worker test-runner playwright-mcp app-mcp demo-app-api demo-app-web; do
    svc_running "$svc" || continue
    for var in ANTHROPIC_API_KEY ANTHROPIC_WORKSPACE_ID GITHUB_ACTIONS_READ_TOKEN; do
      if compose exec -T "$svc" sh -c "env | grep -q '^${var}='" 2>/dev/null; then
        ok=0; info "$svc: $var tanımlı — olmamalı"
      fi
    done
  done
  if [ "$ok" -eq 1 ]; then
    pass "6/anahtar: model anahtarı ve asistan CI okuma token'ı değişkeni yalnızca core-worker'da"
  else
    fail "6/anahtar: model anahtarı ya da GITHUB_ACTIONS_READ_TOKEN core-worker dışında tanımlı"
  fi
}

# --- 7. playwright-mcp ağ izolasyonu --------------------------------------------------
# MCP, sayfada kod çalıştıran araçları (browser_run_code_unsafe …) kapatmaya izin vermez; sınır ağdır.
check_mcp_isolation() {
  local out ok=1 target res
  if ! svc_running playwright-mcp; then
    fail "7/mcp: playwright-mcp çalışmıyor — kontrol yapılamadı"; return
  fi
  local targets="core-api:8000 jira-sim:8090 postgres:5432 toolchain-worker:8100 test-runner:8200 demo-app-api:8000 example.com:443 demo-app-web:8080"
  # shellcheck disable=SC2086
  if ! out="$(compose exec -T playwright-mcp node -e "$NET_JS" $targets 2>&1)"; then
    fail "7/mcp: playwright-mcp içinde node çalıştırılamadı"; info "$out"; return
  fi
  for target in $targets; do
    res="$(printf '%s\n' "$out" | awk -v t="$target" '$1 == t { print $2 }' | head -n 1)"
    [ -n "$res" ] || res="SONUÇ_YOK"
    if [ "$target" = "demo-app-web:8080" ]; then
      if [ "$res" = "OPEN" ]; then info "$target erişilebilir (beklenen)"; else ok=0; info "$target $res — erişilebilir olmalıydı (pozitif kontrol)"; fi
    else
      if [ "$res" = "OPEN" ]; then ok=0; info "$target AÇIK — erişilememeliydi"; else info "$target engelli ($res)"; fi
    fi
  done
  # Ajan tarayıcısı demo-app-web üzerinden test uçlarına (sıfırlama/kırılma) ulaşamaz: nginx 404.
  local http_code
  http_code="$(compose exec -T playwright-mcp node -e '
    fetch("http://demo-app-web:8080/api/test/break", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ kullanici_adi: "bayi1", kampanya: true }) })
      .then((r) => console.log(r.status)).catch((e) => console.log("ERR_" + (e.cause?.code || e.message)));' 2>&1 | tail -n 1)"
  if [ "$http_code" = "404" ]; then
    info "demo-app-web /api/test/break → 404 (beklenen: test uçları dışarı kapalı)"
  else
    ok=0; info "demo-app-web /api/test/break → $http_code (beklenen 404)"
  fi
  # pozitif: core-worker (tek istemci) MCP'ye ulaşır
  if svc_running core-worker && compose exec -T core-worker python -c \
      "import socket; socket.create_connection(('playwright-mcp', 8931), 3).close()" >/dev/null 2>&1; then
    info "core-worker → playwright-mcp:8931 erişilebilir (beklenen)"
  else
    ok=0; info "core-worker → playwright-mcp:8931 erişilemiyor (pozitif kontrol)"
  fi
  if [ "$ok" -eq 1 ]; then
    pass "7/mcp: ajan tarayıcısı yalnızca demo uygulamasına erişiyor"
  else
    fail "7/mcp: playwright-mcp ağ kısıtı beklendiği gibi değil"
  fi
}

# --- 8. Yazma kimlikleri yalnızca core-worker'da ----------------------------------------
# Değerler yazdırılmaz; yalnızca değişkenin tanımlı olup olmadığına bakılır.
WRITE_VARS="JIRA_WRITE_EMAIL JIRA_WRITE_TOKEN XRAY_CLIENT_ID XRAY_CLIENT_SECRET GITHUB_TOKEN GITHUB_MERGE_TOKEN GH_APP_ID GH_APP_PRIVATE_KEY GH_APP_PRIVATE_KEY_PATH GH_APP_INSTALLATION_ID"
check_write_creds() {
  local svc ok=1 found pattern
  pattern="^($(printf '%s' "$WRITE_VARS" | tr ' ' '|'))="
  if ! svc_running core-worker; then
    fail "8/yazma: core-worker çalışmıyor — kontrol yapılamadı"; return
  fi
  if compose exec -T core-worker sh -c 'env | grep -q "^JIRA_WRITE_TOKEN="'; then
    info "core-worker: yazma kimlikleri tanımlı (beklenen)"
  else
    ok=0; info "core-worker: JIRA_WRITE_TOKEN tanımlı değil (pozitif kontrol)"
  fi
  for svc in core-api review-portal jira-sim toolchain-worker test-runner playwright-mcp app-mcp demo-app-api demo-app-web; do
    svc_running "$svc" || continue
    found="$(compose exec -T "$svc" sh -c 'env' 2>/dev/null | grep -E "$pattern" | cut -d= -f1 | tr '\n' ' ' || true)"
    if [ -n "$found" ]; then
      ok=0; info "${svc}: ${found}— olmamalı"
    fi
  done
  # demo-app test belirteci (/test/reset, /test/break) yalnızca demo-app-api ve test-runner'da
  for svc in demo-app-api test-runner; do
    svc_running "$svc" || continue
    if ! compose exec -T "$svc" sh -c 'test -n "$DEMOAPP_TEST_TOKEN"' 2>/dev/null; then
      ok=0; info "${svc}: DEMOAPP_TEST_TOKEN tanımlı değil (pozitif kontrol)"
    fi
  done
  for svc in core-api core-worker review-portal jira-sim toolchain-worker playwright-mcp app-mcp demo-app-web; do
    svc_running "$svc" || continue
    if compose exec -T "$svc" sh -c 'env | grep -q "^DEMOAPP_TEST_TOKEN="' 2>/dev/null; then
      ok=0; info "${svc}: DEMOAPP_TEST_TOKEN tanımlı — olmamalı"
    fi
  done
  # Jira okuma hesabı Jira'da yazma izni taşımaz (asistanın jira_issue aracı bu kimliği kullanır).
  # Betik yalnız durum + izin adı/hata sınıfı yazar; kimlik ve adres yazdırılmaz.
  local izin
  izin="$(compose exec -T core-worker python - < "$TP_REPO_ROOT/scripts/jira-okuma-izni.py" 2>/dev/null | tail -n 1 || true)"
  case "$izin" in
    "ATLA simulator") info "Jira okuma hesabı izni: simülatör, atlandı" ;;
    TAMAM) info "Jira okuma hesabı: ADD_COMMENTS/CREATE_ISSUES/EDIT_ISSUES yok (beklenen)" ;;
    "YAZMA "*) ok=0; info "Jira okuma hesabı yazma izni taşıyor: ${izin#YAZMA } — olmamalı" ;;
    "HATA "*) ok=0; info "Jira okuma hesabı izni doğrulanamadı: ${izin#HATA }" ;;
    *) ok=0; info "Jira okuma hesabı izni doğrulanamadı: betik sonuç vermedi" ;;
  esac
  if [ "$ok" -eq 1 ]; then
    pass "8/yazma: Jira/Xray/GitHub yazma kimlikleri yalnızca core-worker'da; Jira okuma hesabında yazma izni yok; demo test belirteci yalnızca demo-app-api + test-runner'da"
  else
    fail "8/yazma: yazma kimlikleri core-worker dışında tanımlı"
  fi
}

echo "Güvenlik kontrolleri:"
check_ports
check_isolation
check_audit_role
check_secrets
check_demoapp_ro
check_model_key
check_mcp_isolation
check_write_creds
check_gate_isolation
check_no_agent_in_ci
echo "Özet: $passed/10"
[ "$passed" -eq 10 ]
