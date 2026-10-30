#!/usr/bin/env bash
# make security-check — research R10'daki 4 güvenlik kontrolü (FR-015, SC-004).
# Her kontrol PASS/FAIL yazar; özet "N/4"; herhangi bir FAIL → ≠0.
#   1. Host'a açılan tüm portlar yalnızca 127.0.0.1'e bağlı
#   2. test-runner'dan postgres, core-api ve internete erişim yok (demo-app-web'e var)
#   3. tp_app audit_event'i UPDATE/DELETE/TRUNCATE edemez
#   4. Depoda sır yok (gitleaks; git geçmişi + commit edilmemiş izlenen/izlenmeyen dosyalar)
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
            if p.get("published") and ip != "127.0.0.1":
                print("%s: %s:%s" % (name, ip, p.get("published")))
        else:
            print("%s: tanımlanamayan port biçimi %r" % (name, p))
')" || { fail "1/port: compose yapılandırması okunamadı"; return; }
  live_count="$(printf '%s\n' "$rows" | cut -f5 | tr ',' '\n' | grep -c -- '->' || true)"
  live_bad="$(printf '%s\n' "$rows" | awk -F '\t' '$5 != "-" && $5 != "" {
      n = split($5, a, ","); for (i = 1; i <= n; i++) if (a[i] !~ /^127\.0\.0\.1:/) print $1 ": " a[i] }')"
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
const targets = [["postgres",5432],["core-api",8000],["example.com",443],["demo-app-web",8080]];
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
  if ! out="$(compose exec -T test-runner node -e "$NET_JS" 2>&1)"; then
    fail "2/izolasyon: test-runner içinde node çalıştırılamadı"; info "$out"; return
  fi
  for target in postgres:5432 core-api:8000 example.com:443 demo-app-web:8080; do
    res="$(printf '%s\n' "$out" | awk -v t="$target" '$1 == t { print $2 }' | head -n 1)"
    [ -n "$res" ] || res="SONUÇ_YOK"
    if [ "$target" = "demo-app-web:8080" ]; then
      # pozitif kontrol: erişilmesi gereken hedef; erişilemiyorsa test anlamsız
      if [ "$res" = "OPEN" ]; then info "$target erişilebilir (beklenen)"; else ok=0; info "$target $res — erişilebilir olmalıydı (pozitif kontrol)"; fi
    else
      if [ "$res" = "OPEN" ]; then ok=0; info "$target AÇIK — erişilememeliydi"; else info "$target engelli ($res)"; fi
    fi
  done
  if [ "$ok" -eq 1 ]; then
    pass "2/izolasyon: test-runner postgres, core-api ve internete erişemiyor"
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

echo "Güvenlik kontrolleri:"
check_ports
check_isolation
check_audit_role
check_secrets
echo "Özet: $passed/4"
[ "$passed" -eq 4 ]
