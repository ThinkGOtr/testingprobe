# Sözleşme: Ortam değişkenleri

Bağlayıcı karşılığı `docs/MIMARI-SOZLESME.md` §6. Compose ve `.env.example` satırları Şerit E'nindir;
`.env.example`'a **değer yazılmaz** (açıklamalı boş satır). Hiçbiri zorunlu değildir: boş = aşağıdaki
varsayılan. Repo public → commit öncesi sır taraması.

| Değişken | Varsayılan | Nerede | Anlam |
|---|---|---|---|
| `TP_ASISTAN_MODEL_MODE` | `off` | yalnız core-worker | `live` \| `off`. Pipeline `TP_MODEL_MODE`'dan bağımsız (K1). core-api'ye **verilmez** |
| `TP_ASISTAN_ONERI` | `1` | `x-core-env` | `0` → öneri uçları ve düğme kapalı (asistandan bağımsız geri alma) |
| `TP_ASISTAN_OTOMATIK_DERIN` | `1` | yalnız core-worker | `0` → otomatik yükseltme kapalı ("Daha ayrıntılı incele" kalır) |
| `TP_ASISTAN_MUSTERI_VERISI` | `0` | yalnız core-worker | `1` → müşteri verisi kurulumu; `TP_PII_MASKING` kapalıysa `model_hazir=false` (`maskeleme_kapali`) |
| `TP_ASISTAN_VERI_ROLLERI` | boş (tüm roller) | yalnız core-worker | `db_schema`/`db_query` için izinli roller, virgülle (K5) |
| `TP_ASISTAN_SAKLAMA_GUN` | `90` | `x-core-env` | sohbet/mesaj/öneri geri bildirimi saklama süresi (K4) |
| `TP_WORKER_ASISTAN_SERIT` | `1` | yalnız core-worker | `0` → asistan şeridi ve kalp atışı yok → `etkin=false, neden=worker_yok` |
| `TP_WORKER_ASISTAN_PARALEL` | `3` | `x-core-env` | asistan şeridi iş parçacığı; global bekleyen sınırı = 2 × bu (core-api de okur) |
| `JIRA_CREATE_URL` | boş | `x-core-env` | "Jira'yı aç" (yeni kayıt) adresi; `https` (simülatörde `http://127.0.0.1`) ve kökeni `JIRA_BROWSE_URL` ile aynı olmalı, değilse yok sayılır + uyarı |
| `GITHUB_ACTIONS_READ_TOKEN` | boş | yalnız core-worker (**sır**) | `ci_log` GitHub iş logu için yalnız `actions:read` token; boşsa mevcut okuma kimliği. `SECRET_ENV_VARS`'a ve `make security-check` 6'ya eklenir |
| `TP_ASISTAN_DENETIM` | `on` | yalnız core-worker | 011 F7: `off` → asistan denetimi kapalı (011 öncesi davranış). Açıkken soru modelden önce, cevap gösterilmeden önce puanlanır; port hatası fail-closed |
| `TP_ASISTAN_DENETIM_ENGEL` / `TP_ASISTAN_DENETIM_UYARI` | `40` / `70` | yalnız core-worker | puan < engel → engelle; < uyarı → uyarı notu; kategori tabanları ayrıca (`integrations/agent_probe/asistan.py`) |
| `TP_AGENT_PROBE` | `tp` | `x-core-env` | 011 §4.5 Agent Probe portu: `tp` (geçitte model) \| `sim` (kurallar, model yok) |

Mevcut ve değişmeyen: `ANTHROPIC_API_KEY` (yalnız core-worker), `TP_PII_MASKING`, `JIRA_READ_*`
(`jira_issue` okuyucusu), `JIRA_BROWSE_URL`, `JIRA_PROJECT`, `JIRA_HESAP_*` (yorum yazarı rol etiketi),
`TP_DAILY_BUDGET_USD` (`butce_orani` olgusu), `TP_EVAL_BUDGET_USD` (host; asistan canlı seti için ≥ 10).

Asistan bütçe/hız tavanları (K3: $10/gün asistan, $1/gün kullanıcı, $0.50/kök soru, 30 soru/saat,
1 bekleyen/kullanıcı) v1'de **kod sabitidir**; ortam değişkeni yoktur.

**Canlıya geçiş (sunucu):** `.env`'ye `TP_ASISTAN_MODEL_MODE=live` eklenir; `make up` core-worker'ı
yeniden oluşturur; `GET /assistant/status` → `mod: "live"`, `etkin: true`.
