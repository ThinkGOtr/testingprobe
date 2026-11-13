# Demo provası (`rehearsal/`)

Sunucunun yapacağı akışın tamamını — TEKNIK-TASARIM §2'nin 14 adımı + locator kırma/onarım — canlı
yerel yığına karşı, doğru rollerle tek komutta koşturur ve her adımı beklenen duruma karşı doğrular.
Beklenen değerler `docs/DEMO-VERISI.md`'dir (ana yol: REPLAY senaryosu `f2-kod-hatasi`); uydurma değer yok.

## Komutlar

```bash
scripts/demo-prova.sh --runs 3          # make reset → prova, 3 kez; §13 "3 ardışık sorunsuz prova"
scripts/demo-prova.sh --ui              # aynı akış portal + jira-sim arayüzünden (video + ekranlar)
scripts/demo-prova.sh --ui-tur          # API provasından sonra salt okuma arayüz turu (yedek video)
scripts/demo-prova.sh --kirma-yayinla   # + isteğe bağlı C6: kırma taslağı → yeni Bug (story + Test bağı)
scripts/demo-prova.sh --temizle 5       # prova koşmadan yalnızca son 5 koşu rapor dizinini tut
scripts/demo-prova-selftest.sh          # demo-prova öz testi (yığın gerekmez)

uv run --project rehearsal python -m tp_rehearsal                 # tek prova (temiz yığın ister)
uv run --project rehearsal python -m tp_rehearsal --kip denetim   # salt okuma: son durumu doğrula
(cd rehearsal/ui && npm ci && UI_KIP=tur npx playwright test)     # salt okuma arayüz turu
```

`--kip prova` yığını değiştirir ve sunucunun açılış durumunu ister (P0: `TP_MODEL_MODE=replay`,
`TP_REPLAY_STRICT=1`, TPD-1 incelenmemiş, açık script yok, forge main = demo-baseline, demo-app-web
main'i yansıtıyor, `make demo-reset`in baseline push CI'ı yeşil). Bu durum DEMO-AKISI §1.2'deki
sırayla elde edilir: `make reset` (Demo-A ancak boş veritabanında yeniden oynar) → `make demo-reset`
→ temel koşu yeşil. `scripts/demo-prova.sh` her koşudan önce ikisini de yapar (P0 temel koşuyu
bekler), core-worker'ı `TP_REPLAY_STRICT=1` ile yeniden oluşturur, bitince önceki değere döndürür.

**Model kipi:** prova yalnızca strict REPLAY'de koşar. `scripts/demo-prova.sh`, .env/kabuktaki
`TP_MODEL_MODE` ya da core-worker'ın gerçek kipi `replay` değilse **çıkış 2** ile durur (`make env`
`auto` yazar; anahtar tanımlıysa auto canlı model çağırır). Özet, core-worker'dan okunan kipi yazar.
P0 de prova kipinde `TP_MODEL_MODE != replay` için kritik FAIL verir; yalnızca geliştirmede
`--canli-izinli` ile UYARI'ya iner ve rapora "§13 provası sayılmaz" notu düşer.

**Açılış sayacı:** P0, portal yol haritasının açılışta göstereceği sayacı (koşu tabanlı 8–11
kuralları birebir, story adımları yaklaşık) hesaplar; DEMO-AKISI "0/14 tamam" der, farklıysa UYARI
yazılır. Yetkili kontrol arayüz provasındadır: `--ui` ilk adımda ekrandaki sayacın `0/14 tamam`
olduğunu doğrular (uyuşmazsa FAIL).

## Adımlar ve roller

| # | Adım | Rol | §2 |
|---|---|---|---|
| P0 | Ön kontrol (8 seed hesabı 012 rolleriyle: analist, po, testci, muhendis, sunucu=admin, denetci, gelistirici, izleyici; `TP_MODEL_MODE=replay` + strict, temiz başlangıç, demo-reset temel CI yeşil, açılış sayacı 0/14) | sunucu | — |
| P1 | Güvenlik (§13): `make security-check` 10/10; bot kimliğiyle main'e doğrudan commit reddedilir, main değişmez (yalnızca prova kipinde denenir) | sunucu | — |
| A1–A5 | Jira'dan çek → ön inceleme (4 kanıtlı bulgu) → F1/F3 `fix_doc`, F2/F4 `code_defect` → düzeltme + 2. tur → PO etiketi (jira-sim, `po@sim.local`) | analist, po | 1–3 |
| A6–A12 | 011 K15: **tasarım modeli** (iki tur, tur 1: `generate-cases {"kip":"iki_tur"}` → `model_ready`, 21 öğe, sorun yok) → **model onayı (testci**, 012 `design_model.decide`, görülen `icerik_hash`'e bağlı) → tur 2: 15 case (`cases.generated` kaydında `kip=iki_tur`, `tur2_farklari=[]`) → **otomatik review** (P8; `tamamlandi`, skor 10, REPLAY) → Testçi 15 `accept` (draft → ready) → Analist son onayı 15 `approve` (ready → approved; görevler ayrılığı; set değişmez) → **Denetime gönder** (P9, analist `case.approve`; önce önizleme `blocked_gate`, sonra güncel sete ait `KABUL`, `yayin_engeli=null`; `TP_DENETIM_KAPISI=on`) → yayın (testci) | testci, analist | 4 |
| B1–B5 | Kod üretimi C1/C2/C3/C5 (C3 defect adayı) → kırarak doğrula (C2 yeşil→kırmızı→yeşil, C1/C5 zayıf) → merge C2, C1, C5 (zayıf test açık kabul notu) → push + deploy + nightly (tetik: muhendis) → Kontrol Kulesi | muhendis, sunucu | 5–11 |
| C1–C5 | C3 triage (kural) → TPD-5'e bağla; F2 → TPD-5'e bağla; F4 → yeni Bug; kırma taslağı (TPD-5 medium, karar verilmez) | testci | 12–14 |
| C6 | İsteğe bağlı (`--kirma-yayinla`): C2 kırma taslağı → yeni Bug; jira-sim'de Relates TPD-1 + Test (C2'nin Test issue'su) | testci | 14 |
| D1–D5 | `make demo-break` → push CI kırmızı (19/22, hepsi locator) → onarım PR'ı (tek satır testId) → merge → push CI yeşil | sunucu, muhendis | 8, 12 |
| Z1 | `ai_call`'da REPLAY-MISS ve sahte "live" yok; `design_model`, `case_generation`, `case_review`, `case_audit` çağrıları REPLAY + `golden_matched` (`f2-kod-hatasi/TPD-1`) (okunamazsa FAIL; Kontrol Kulesi çağrı sayılarıyla çapraz kontrol); denetim zinciri + çapalar sağlam | sunucu | — |

B4 ayrıca deploy koşusunun Playwright HTML / JUnit / Allure bağlantılarının HTTP 200 döndüğünü ve
Sauce kimliği yokken sahte Sauce bağlantısı olmadığını doğrular (§2 adım 9–10).

Arayüz provası (`--ui`, `UI_KIP=canli`) sahnedeki yolları kullanır: locator kırılması **Demo
kontrolleri → "Buton kimliğini değiştir" → "Evet, buton kimliğini değiştir"** düğmesiyle yapılır ve prova, sunucunun
host'ta açık tuttuğu `scripts/demo-web-sync.sh --watch` izleyicisini arka planda başlatır (host'ta
zaten çalışıyorsa ikincisini açmaz); izleyicinin isteği uyguladığı `/forge/demo-web-refresh.done`
ile doğrulanır. `make demo-break` terminal yedeği API provasının D1 adımında ayrıca prova edilir.
Arayüz akışı ayrıca koşu detayındaki rapor bağlantılarını, C3 triage sayfasını (adım 12) ve son
adımda Denetim → "Zinciri yeniden doğrula"yı kapsar.

Her adım süresini bütçesine karşı ölçer (ajan adımı ≤120 sn, CI ≤120 sn uyarısı, toplam 25 dk).
Bir adım FAIL olunca sonrakiler ATLANDI olur (`--devam` ile sürer); çıkış kodu FAIL / bütçe aşımı /
REPLAY-MISS'te 1'dir.

## Rapor

`rehearsal/reports/<zaman>[-k<n>]/`: `rapor.md` (PASS/FAIL tablosu, süre/bütçe, kontroller, kanıt),
`rapor.json`, `komutlar.log` (`make demo-break` çıktısı dahil), `api-cagrilari.tsv`. Arayüz:
`rehearsal/reports/<zaman>-ui-<kip>[-k<n>]/` → `ekranlar/NN-*.png`, `video/**/*.webm`, `rapor.md`,
`izleyici.log`. `<zaman>` yerel saattir; `scripts/demo-prova.sh` koşu dizinini kendisi adlandırıp
koşuya verir (`--rapor-yolu`, `UI_RAPOR_DIZINI`), özet yalnızca o koşunun yazdığı raporu gösterir.

Sırlar: `.env` parolaları hiçbir çıktıya yazılmaz (maskelenir). Playwright izi (trace) **kapalıdır**:
iz, form doldurma argümanlarını ve giriş POST gövdelerini kaydeder (portal ve jira-sim PO parolası
düz metin olarak trace.zip'e girer). Her koşudan sonra `python -m tp_rehearsal.sir_tarama --iz-sil`
dizindeki trace.zip'leri siler ve kalan her dosyayı (zip üyeleri dahil; ham / JSON / URL kodlu)
`.env` sır değerlerine karşı tarar — değer yazdırmadan; bulursa koşu başarısızdır. Rapor kökü 700
izinlidir. Yedek video paketini sunum makinesine kopyalamadan önce tarama temiz olmalıdır.

Saklama: `scripts/demo-prova.sh` bitince **videosuz** koşu dizinlerinden en yeni 10'unu tutar
(`--sakla N`, 0 = silme); `--temizle [N]` yalnızca temizler. Video (`.webm`/`.mp4`) içeren arayüz
raporları (`-ui-canli-`, `-ui-tur-`: yedek video, 200–450 MB) otomatik temizlikte **ne sayılır ne
silinir**; yalnızca açıkça `scripts/demo-prova.sh --temizle N --video-dahil` ile, her biri için
uyarı yazılarak silinir.

## Dürüstlük notları

- API provası kararları insan beklemesi olmadan verir: review süresi ölçüsü sunumu temsil etmez.
- Manuel baz değer yalnızca `TP_MANUAL_BASELINE_S`'ten okunur; prova değer üretmez.
- Model kipi core-worker'dan okunur ve her çıktıya gözlenen değer yazılır (sabit "REPLAY" metni
  yok); prova kipinde replay dışı kip FAIL'dir, `ai_call`'da "live" görülürse Z1 FAIL.

## Geliştirme

```bash
cd rehearsal && uv run ruff check && uv run ruff format --check && uv run pytest
cd rehearsal/ui && npm run typecheck && npm run birim
scripts/demo-prova-selftest.sh
```
