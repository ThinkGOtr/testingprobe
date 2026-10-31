#!/usr/bin/env bash
# make reset — (1) denetim kaydını dışa aktar (başarısızsa hiçbir şey silinmez)
#              (2) docker compose down + Postgres ve artefakt volume'lerini sil
#              (3) make up (forge-init'siz) → forge-init --force → jira-sim /sim/reset → durum tablosu
# Yarıda kesilirse tekrar çalıştırmak güvenlidir: dışa aktarım her zaman silmeden önce yapılır.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

[ -f .env ] || die ".env bulunamadı — 'make env' çalıştırın"
docker info >/dev/null 2>&1 || die "Docker çalışmıyor"

if docker volume inspect "$TP_PG_VOLUME" >/dev/null 2>&1; then
  started_pg=0
  if ! svc_healthy postgres; then
    # Ortam kapalı ama veri var: dışa aktarım için yalnızca Postgres'i başlat
    echo "Dışa aktarım için yalnızca postgres başlatılıyor..."
    if ! compose up -d --no-deps --wait --wait-timeout 120 postgres; then
      die "postgres başlatılamadı; dışa aktarım yapılamadı, hiçbir şey silinmedi"
    fi
    started_pg=1
  fi
  if ! TP_EXPORT_ALLOW_NO_TABLE=1 "$TP_REPO_ROOT/scripts/export-audit.sh"; then
    [ "$started_pg" -eq 0 ] || compose stop postgres >/dev/null 2>&1 || true
    die "dışa aktarım başarısız; sıfırlama iptal edildi, hiçbir şey silinmedi"
  fi
else
  echo "Postgres volume'ü ($TP_PG_VOLUME) yok; dışa aktarılacak denetim kaydı yok."
fi

echo "Servisler durduruluyor..."
compose down
if docker volume inspect "$TP_PG_VOLUME" >/dev/null 2>&1; then
  docker volume rm "$TP_PG_VOLUME" >/dev/null
  echo "Çekirdek veri silindi ($TP_PG_VOLUME)."
fi
# Koşu artefaktları (trace, rapor, ekran görüntüsü) silinen koşulara aittir.
if docker volume inspect "$TP_ARTIFACTS_VOLUME" >/dev/null 2>&1; then
  docker volume rm "$TP_ARTIFACTS_VOLUME" >/dev/null
  echo "Artefaktlar silindi ($TP_ARTIFACTS_VOLUME)."
fi
# Kod üretimi ajan ekran görüntüleri silinen script'lere aittir.
if docker volume inspect "$TP_CODEGEN_VOLUME" >/dev/null 2>&1; then
  docker volume rm "$TP_CODEGEN_VOLUME" >/dev/null
  echo "Kod üretimi ekran görüntüleri silindi ($TP_CODEGEN_VOLUME)."
fi
# Merge kapısı sonuçları ve GitHub aynası silinen koşulara/PR'lara aittir.
for vol in "$TP_CHECKS_VOLUME" "$TP_MIRROR_VOLUME"; do
  if docker volume inspect "$vol" >/dev/null 2>&1; then
    docker volume rm "$vol" >/dev/null
    echo "Silindi ($vol)."
  fi
done

# forge'u up.sh değil aşağıdaki --force kurar (iki kez kurulmasın); tablo en sonda yazılır.
TP_SKIP_FORGE_INIT=1 TP_SKIP_STATUS=1 "$TP_REPO_ROOT/scripts/up.sh"

# Çekirdek veri silindi → dış sistemlerin yerel simülasyonları da demo başlangıcına döner.
echo "Yerel forge demo başlangıcına döndürülüyor (PR kaydı ve tp/* dalları silinir)..."
"$TP_REPO_ROOT/scripts/forge-init.sh" --force >/dev/null || die "forge-init --force başarısız"
JIRA_BASE="$(env_get JIRA_BASE_URL)"
if [ -z "$JIRA_BASE" ]; then
  # Gerçek Jira kullanılmıyor → jira-sim'i yeniden tohumla (TPD-1..TPD-7).
  jira_port="$(env_get JIRA_SIM_PORT)"
  if curl -fsS -X POST -H "X-Sim-Admin-Token: $(env_get JIRA_SIM_ADMIN_TOKEN)" \
      "http://127.0.0.1:${jira_port:-8090}/sim/reset" >/dev/null; then
    echo "jira-sim yeniden tohumlandı."
  else
    die "jira-sim sıfırlanamadı (POST /sim/reset)"
  fi
else
  # Gerçek Jira: önce plan yazdırılır (yazmaz), operatör onaylarsa TPD-1..4 demo başlangıcına
  # döner ve koşu issue'ları kapanır (yazma kimliği yalnızca core-worker'da).
  echo "Gerçek Jira yapılandırılmış ($JIRA_BASE). jira-seed planı:"
  compose exec -T core-worker python -m tp_core.integrations.jira_seed || true
  c=""
  if [ -t 0 ]; then
    read -r -p "Gerçek Jira ($JIRA_BASE) demo başlangıcına döndürülsün mü? [e/H] " c || c=""
  fi
  if [ "$c" = e ] || [ "$c" = E ]; then
    compose exec -T core-worker python -m tp_core.integrations.jira_seed --onay \
      || die "jira-seed başarısız"
  else
    echo "Gerçek Jira verisine dokunulmadı (sonra: make jira-seed)."
  fi
fi
# Kullanıcılar ve başlangıç verisi silindi; tohum idempotenttir.
"$TP_REPO_ROOT/scripts/seed.sh" || die "seed başarısız (sonra: make seed)"
echo
"$TP_REPO_ROOT/scripts/status.sh"
echo "ortam temiz"
