# 013 — Sprint otomasyonu (İsmail geri bildirimi) — Analiz

Tarih: 2026-11-11 · Dal: `feat/ismail-geri-bildirim` (dev `e0e5015`'ten) · Worktree `../tp-wt-ismail` ·
Durum: kararlar alındı, geliştirme başlıyor

Kaynak: Testing Probe'u test eden İsmail'in notu (2026-11-11):

> Hakan ekibe Copilot verip sprint içinde taskların otomatik koşmasını istiyor; bu yüzden test case
> onaylandıktan sonra hemen otomasyon kodu oluşturulmalı (Java, .NET, Python vs.), task QA To Do'ya
> geldiğinde case'ler yazılmalı. Test case'lere negatif senaryolar eklenmeli. Test case'lerin
> tamamı için "onayla" ya da "seçili onayla" olması işleri kolaylaştırır. Test verisinin task
> içinde değil, belli bir yerde adreslenmesi iyi olur.

Bu doküman kapsamı, kararları, şeritler arası sözleşmeleri ve geliştirme şeritlerini sabitler.
Şeritler bu dokümana göre çalışır; sözleşme değişikliği önce buraya yazılır.

## 1. Kapsam

| # | İş | İsmail'in maddesi |
|---|---|---|
| F1 | **Toplu onay**: "Seçili onayla" + "Tümünü onayla" (yalnız görülmüş case'ler) | 3 |
| F2 | **Onay sonrası otomatik kod üretimi** (ayarla kapatılır) | 1 (ilk yarı) |
| F3 | **Jira durum tetiği**: story "QA To Do"ya gelince çekilir, ön incelemeye girer; PO onayı gelince case üretimi kendiliğinden başlar | 1 (ikinci yarı) |
| F4 | **Merkezi test verisi kataloğu**: portalda düzenlenen, sürümlü katalog; case metni `{veri:anahtar}` atfı taşır | 4 |
| F5 | Portal ekranları: toplu onay, Test verisi, Otomasyon ayarları, case'te atıf gösterimi | 1, 3, 4 |

Kapsam dışı (başka dalda ya da sonraya):

| Madde | Neden / nerede |
|---|---|
| Kod üretim dili (Java / C# / Python) | `feat/uretim-dili` (specs/011-uretim-dili) yapıyor |
| Negatif senaryolar | v3 (`feat/case-gen-v3`, specs/011-test-uretim-v3) F1 negatif kapsam kararı + F4 "Negatif genişlet". v3 dev'e girince İsmail tekrar denesin |
| Copilot | Akış portal + Jira tetikleriyle insansız ilerliyor; Hakan'a sorulacak açık madde (§8) |
| Canlı model çağrısı | Gerekmiyor: prompt'a dokunulmuyor; golden/replay değişmiyor |
| Deploy | Yok; bitişte dev'e merge + push |

## 2. Kararlar (ürün sahibi, 2026-11-11)

| # | Konu | Karar |
|---|---|---|
| K1 | Kapsam | Çakışmayan 4 iş (F1–F4); dil ve negatif kendi dallarında |
| K2 | Taban dal | dev'den aç; v3 / uretim-dili dev'e girince çakışmayı bu dal çözer, yüzey dar tutulur |
| K3 | Toplu onay | "Seçili onayla" + "Tümünü onayla". Yalnız bu kullanıcının son karardan sonra **görüntülediği** ve onaya engeli olmayan taslaklar girer; her case kendi görülen hash'iyle onaylanır; görülmeyen atlanır, neden gösterilir |
| K4 | Kod tetiği | Her onayda hemen kuyruğa (aktör sistem, tetikleyen onaylayan). Ayar, varsayılan **açık**, portaldan kapatılır. Kod üretimi ekranındaki düğme kalır |
| K5 | Jira tetiği | Worker periyodik sorgu; durum adı ayarlanabilir (varsayılan "QA To Do"). Yeni story çekilir + ön incelemeye girer; **PO kapısı korunur**; PO onayı gelince case üretimi otomatik. Webhook yok |
| K6 | Test verisi yeri | Portalda katalog (DB, sürümlü); case anahtara atıf yapar; kod üretimi değeri aynı yerden okur. Parolalar kataloğa yazılmaz (ortam sırrı). Bugünkü demo DB okuması kataloğun ilk içeriği olur |
| K7 | Negatif | Ek iş yok; v3 sonrası İsmail tekrar dener |
| K8 | Copilot | Kapsam dışı; Hakan'a açık madde |
| K9 | Atıf üretimi | Prompt'a dokunulmaz. Üretimden sonra **deterministik eşleme** değeri `{veri:anahtar}`a çevirir; analist düzenlerken atıf ekleyebilir |
| K10 | Veri değişimi | Onay düşmez (case anahtarı tutar, hash değişmez); kod üretimi o anki değeri kullanır; etkilenen case/script'te "veri değişti" uyarısı + denetim kaydı |
| K11 | Katalog yetkisi | Analist + Otomasyon mühendisi düzenler, herkes görür; her değişiklik sürüm + denetim kaydı |
| K12 | Bitiş | Review döngüsü + ekran testi geçince dev'e merge + push; deploy yok |

Yorumlarım (ürün sahibi söylemedi, makul varsayılan olarak alındı; review'da itiraz edilebilir):
- **Y1** Otomatik kod üretiminin platformu `web`. Uygulama platformları (Android/iOS/Windows) cihaz
  gerektirdiği için otomatik tetiklenmez; elle düğme kalır. Dil seçimi uretim-dili dev'e girince
  "algılanan dil" olur (bu dalda alan yok).
- **Y2** Otomatik case üretimi yalnız Jira tetiğiyle akışa alınmış (`qa_tetik_zamani` dolu)
  gereksinimlerde çalışır. Elle çekilen gereksinimin akışı (demo provası) değişmez.
- **Y3** Otomasyon ayarlarını Analist ve Otomasyon mühendisi değiştirir (katalogla aynı).
- **Y4** Jira'ya yayınlanan case metninde atıflar değere çözülür; **gizli** anahtarlar
  çözülmez, `{veri:anahtar}` olarak kalır (bugün demo parolası Jira'ya açık yazılıyordu).
- **Y5** Jira tetiği varsayılan **açık**: seed'deki story'ler "To Do"da olduğundan bir story
  elle "QA To Do"ya taşınmadıkça etkisi yoktur.

## 3. Sözleşmeler

### 3.0 Veri modeli (Ş0, yazıldı)

Migration `core/alembic/versions/0030_sprint_otomasyonu.py` (revision `0030`, down `0020`; diğer
dalların 0021/0022'siyle çakışmasın diye; birleştirmede `down_revision` zincirin sonuna çekilir).
Modeller `tp_core/models/otomasyon_feature.py` + `Requirement`, `ScriptCodegen` ek kolonları.

| Tablo / kolon | Anlam |
|---|---|
| `otomasyon_ayari(anahtar PK, deger JSONB, guncelleyen, guncelleme)` | Ayar; satır yoksa varsayılan |
| `test_verisi(id, anahtar UNIQUE, grup, aciklama, deger?, gizli, sir_adi?, surum, silindi, guncelleyen, olusturma, guncelleme)` | Katalog. Gizli ⇔ `deger NULL` ve `sir_adi` dolu (CHECK) |
| `test_verisi_surum(test_verisi_id, surum, islem olustur\|guncelle\|sil, deger?, gizli, sir_adi?, degistiren, zaman)` | Değişmez geçmiş (tp_app yalnız INSERT/SELECT) |
| `requirement.jira_durumu`, `requirement.qa_tetik_zamani` | Tetiğin gördüğü son durum; tetikle akışa alınma anı |
| `script_codegen.veri_izi JSONB` | Üretimde çözülen `{anahtar: surum}` |
| `script_codegen.tetik` `elle\|otomatik` | Üretimi kim başlattı |

### 3.1 Otomasyon ayarları (Ş0 modülü `features/otomasyon/ayarlar.py`, yazıldı)

- `otomatik_kod_uretimi`: `{acik: bool=true}`
- `jira_tetik`: `{acik: bool=true, durum: str="QA To Do", aralik_s: int=60 (30..3600), otomatik_case: bool=true}`
- `ayarlar.oku/otomatik_kod/jira_tetik/hepsi/yaz(session, anahtar, kismi_deger, aktor)`; `yaz`
  geçersiz alanda `ValueError`, denetim `otomasyon.ayar`.
- API (Ş1): `GET /automation-settings` (herkes) → `ayarlar.hepsi()`;
  `PUT /automation-settings/{anahtar}` (analyst | engineer) gövde kısmi nesne → güncel hepsi; 422 Türkçe.

### 3.2 Toplu onay ve otomatik kod (Ş1)

`POST /cases/bulk-decision` (analyst):
```json
{"karar": "approve", "ogeler": [{"case_id": "…", "icerik_hash": "…"}]}   // 1..200 öğe
```
Yanıt 200:
```json
{"sonuclar": [{"case_id": "…", "durum": "onaylandi|atlandi|hata", "neden": "…|null",
               "otomatik_kod": {"durum": "kuyrukta|reddedildi|kapali|atlandi", "neden": "…|null",
                                "script_id": "…|null"} | null}],
 "ozet": {"onaylandi": 3, "atlandi": 1, "hata": 0}}
```
- Yalnız `approve`. Her öğe kendi savepoint'inde `cases.service.decide(..., karar="approve")` ile
  (tek onayla aynı kurallar: durum `draft`, hash eşleşmesi, gereksinim güncel, AC atfı). Birinin
  hatası diğerlerini geri almaz.
- **Görülme şartı**: bu kullanıcının bu case için son karardan sonra `case_goruntuleme` kaydı yoksa
  `atlandi`, neden "Bu case'i açıp görmediniz". (Tekli onay değişmez.)
- `serialize_cases` her case'e `goruldu: bool` ekler (istekte bulunan kullanıcı için; parametre
  `kullanici_id`), portal "Tümünü onayla"yı buna göre süzer. Sunucu yine de denetler.
- Denetim: öğe başına mevcut `review` kaydı + toplu istek için `cases.bulk_decision`
  (`{istenen, onaylandi, atlandi}`).

**Otomatik kod** (`features/otomasyon/otokod.py`, `kuyruga_al(session, tc, onaylayan) -> dict`):
- Tekli `decide(approve)` ve toplu onay, onaydan sonra çağırır (edit kararı da onaylar → çağırır).
- Ayar kapalıysa `{"durum":"kapali"}`. Açıksa savepoint içinde
  `codegen.service.start_generation(session, [case_id], OTOMASYON_AKTORU, platform="web", tetik="otomatik")`.
  `CodegenRejected` → `reddedildi` + neden; mevcut sonuç `suruyor|pr_acik|merge_edildi` → `atlandi`.
  Beklenmeyen hata onayı **geri almaz** (savepoint geri alınır, log + denetim `codegen.otomatik_hata`).
- `OTOMASYON_AKTORU`: `Principal(None, "otomasyon", "system", ...)`; iş akışı yükünde
  `baslatan` + `tetikleyen: <onaylayan kullanıcı adı>`. Engineer rol kapısı bilinçli olarak
  atlanır (K4). `start_generation` yeni `tetik` parametresiyle `script_codegen.tetik` yazar.
- Tekli karar yanıtına (`POST /cases/{id}/decision`) `otomatik_kod` alanı eklenir.

### 3.3 Test verisi kataloğu (Ş3)

Atıf sözdizimi ve saf fonksiyonlar: `features/testveri/atif.py` (Ş0, yazıldı):
`esle`, `coz`, `case_esle`, `case_coz`, `case_atiflari`, `bilinmeyen_atiflar`. Değişmez:
katalog aynıyken `coz(esle(m)) == m`.

Servis `features/testveri/service.py`:
- `katalog(session) -> dict[anahtar, deger]`: silinmemiş, **gizli olmayan** kayıtlar (eşleme için).
- `cozum_degerleri(session) -> (dict[anahtar, deger], dict[anahtar, surum])`: gizliler
  `os.environ[sir_adi]`'den; sır tanımsızsa o anahtar çözülemez (kod üretimi reddeder: "test verisi
  sırrı tanımsız: <anahtar>").
- Eşleme için gizli kayıtlar da kullanılır: eşleme `katalog + {gizli anahtar: ortam değeri}`
  (değer ortamda varsa) ile yapılır, böylece parola case metnine düz yazılmaz.
- CRUD + sürüm kaydı + denetim (`testveri.olustur|guncelle|sil`). Silme yumuşak (`silindi`).
- `tohumla(session)`: katalog boşsa `cases/testdata.py`'nin okuduğu demo DB satırlarından ve
  sabitlerden doldurur (anahtar şeması: `bayi.<kullanici_adi>.kullanici_adi|ad|kredi_limiti`,
  `urun.<kod>.kod|ad|fiyat`, `kampanya.<kod>.kod|ad`, `ayar.<anahtar>`, `ortak.demo_parola`
  (gizli, sır `TP_TESTVERI_DEMO_PAROLA`), `etiket.<slug>` UI etiketleri). `make seed` ve worker
  açılışında idempotent çağrılır. Biçim (fiyat "1.250,00 TL" vb.) `testdata.block()` ile aynı.
- `testdata.block()` (model girdisi) bu dalda **değişmez**: replay anahtarları korunur. Katalog
  doluysa blok katalogdan kurulur ama **aynı metni** üretmesi testle sabitlenir; fark varsa eski
  kaynak kullanılır ve uyarı loglanır.

API (Ş3):
| Yöntem | Yol | Rol | Not |
|---|---|---|---|
| GET | `/test-data` | herkes | `[{id, anahtar, grup, aciklama, deger (gizli → null), gizli, sir_adi, sir_tanimli: bool, surum, guncelleyen, guncelleme, kullanim: int}]` (`kullanim` = atıf yapan etkin case sayısı) |
| POST | `/test-data` | analyst, engineer | `{anahtar, grup?, aciklama?, deger? , gizli?, sir_adi?}` → 201; anahtar çakışması 409 |
| PUT | `/test-data/{id}` | analyst, engineer | `{deger?, aciklama?, grup?, sir_adi?, beklenen_surum}`; sürüm uyuşmazlığı 409 |
| DELETE | `/test-data/{id}` | analyst, engineer | `?beklenen_surum=`; atıf yapan etkin case varsa 409 + listesi |
| GET | `/test-data/{id}/history` | herkes | sürümler (gizli değer yok) |

Akışa bağlanma (Ş3):
- **Case üretimi** (`cases.service.store_cases`) ve **IDE kanalı** (`submit_drafts`): içerik yazılmadan
  önce `case_esle`. İçerik hash'i eşlenmiş içerikten hesaplanır.
- **Düzelt** (`decide(edit)`): `bilinmeyen_atiflar` boş değilse 422 "Katalogda olmayan test verisi
  anahtarı: …". Analistin yazdığı düz değer olduğu gibi kalır (zorla eşleme yok).
- **Kod üretimi**: case içeriği `case_coz` ile çözülür ve doğrulama ajanına / kontrollere / şablona
  **çözülmüş** gider (`checks.case_texts` çözülmüş metni görür). Çözülemeyen atıf → `CodegenRejected`
  (Türkçe neden). `script_codegen.veri_izi` = kullanılan anahtar sürümleri. Aynı hash'le açık PR
  varken atlama kuralına `veri_izi` de girer: veri sürümü değiştiyse yeniden üretime izin verilir.
- **Yayın** (Jira/Xray): gizli olmayan atıflar değere çözülür; gizliler atıf olarak kalır (Y4).
- **Serileştirme**: `serialize_cases` her case'e `veri: {anahtar: {deger|null, gizli, surum, var: bool}}`
  ekler; script serileştirmesi `veri_degisti: bool` (veri_izi'ndeki sürüm < güncel sürüm) ve
  `veri_izi` döner. Katalog değişiminde onay düşmez (K10).

### 3.4 Jira durum tetiği (Ş2)

- Jira portu: `JiraPort.search` mevcut; JQL `project = <P> AND issuetype = Story AND status = "<durum>"`
  (durum tırnak kaçışlı). `JiraIssue`'ya `status: str | None` alanı (gerçek Jira + sim).
- İş `requirements.jira_tetik` (worker, kendini `aralik_s` sonra yeniden planlar; `po_poll`
  kalıbı; worker açılışında `ensure`). Ayar kapalıysa yalnız yeniden planlar.
- Her eşleşen issue: `upsert_issue(..., aktor="jira-tetik")`, `req.jira_durumu = durum`.
  Gereksinim `new` durumundaysa ve `qa_tetik_zamani` NULL ise: `qa_tetik_zamani = now()`,
  `flow.start_review(..., OTOMASYON_AKTORU)`; denetim `requirements.jira_tetik`
  (`{jira_key, durum}`). Diğer durumlarda dokunulmaz (çift tetik yok). Hata bir issue'yu atlar,
  diğerlerini durdurmaz; Jira erişilemezse sonraki tura kalır.
- **Otomatik case üretimi**: gereksinim `po_approved`'a girdiğinde (Jira PO etiketi yolu) ve
  `qa_tetik_zamani` doluysa ve `jira_tetik.otomatik_case` açıksa `requirements.otomatik_case`
  işi kuyruğa alınır → `cases.service.start_generation(session, req.id, OTOMASYON_AKTORU)`.
  Kapı reddederse denetim + `req` olduğu gibi kalır (analist elle başlatabilir).
- Durum API'si: `GET /automation/jira-trigger` (herkes) → `{acik, durum, aralik_s, son_tur: {zaman, bulunan, tetiklenen, hata}|null, son_tetiklenenler: [{jira_key, zaman}]}` (son tur bilgisi job sonucundan / denetimden).
- **jira-sim**: "QA To Do" durumu (`STATUSES`), `GET/POST /rest/api/3/issue/{key}/transitions`
  (gerçek Jira biçimi), JQL `status = "QA To Do"` desteği. Demo kontrolü:
  `POST /demo/jira-status {jira_key, durum}` (yalnız demo/sim modunda; gerçek Jira'da 409).

### 3.5 Portal (Ş4)

- **Case review** (`pages/CaseReview.tsx`): taslak satırlarında onay kutusu; üst çubukta
  "Seçili onayla (n)" ve "Tümünü onayla (n)". "Tümünü" yalnız `goruldu && !onay_engeli` taslakları
  sayar; görülmeyen sayısı "n case açılmadığı için dışarıda" notuyla gösterilir. Sonuç özeti
  (onaylandı / atlandı + neden / otomatik kod durumu) satır içi bildirim. Tarayıcı diyaloğu
  (`confirm`) kullanılmaz; onay için portalın kendi onay kutusu bileşeni.
- **Case kartı**: `{veri:anahtar}` atıfları çip olarak (anahtar + değer; gizli → "••• (gizli)");
  bilinmeyen anahtar kırmızı çip. Düzelt formunda "Test verisi ekle" seçicisi (katalogdan anahtar
  seçip imlece atıf ekler).
- **Test verisi** sayfası (yeni, menü: Analist + Mühendis + herkes görüntüler): grup bazlı tablo,
  arama, ekle/düzenle/sil (yetkiye göre), sürüm geçmişi çekmecesi, gizli kayıtlarda "sır tanımlı /
  tanımsız" rozeti, kullanım sayısı.
- **Otomasyon** sayfası (yeni): iki ayar kartı (otomatik kod, Jira tetiği: aç/kapa, durum adı,
  aralık, otomatik case), Jira tetiği son tur bilgisi ve son tetiklenen story'ler.
- **Kod üretimi / Script detay**: `tetik = otomatik` rozeti ("Onayla otomatik"), `veri_degisti`
  uyarısı ("Test verisi değişti; yeniden üretin").
- **Demo kontrolleri**: "Story'yi QA To Do'ya taşı" (jira-sim).
- API tipleri `src/api/` altında; mevcut stil (Türkçe metin, erişilebilirlik kuralları, koyu tema
  token'ları) korunur; vitest testleri.

## 4. Değişmeyen ilkeler

- İnsan onayı: model ve otomasyon hiçbir case'i onaylamaz; toplu onay da görülmüş case'lerle
  sınırlı ve her case kendi görülen hash'iyle onaylanır.
- PO kapısı: Jira tetiği PO onayını atlamaz.
- Replay/golden: prompt ve model girdileri değişmez (`testdata.block()` aynı metin; doğrulama
  ajanına giden case metni çözülmüş, yani bugünküyle aynı).
- Denetim: her otomatik işlem aktör `otomasyon` / `jira-tetik` ve tetikleyen bilgisiyle yazılır.
- Dış sistemlere yazma: Jira'ya tetik yalnız okur; mevcut yazma yolları (ön inceleme yorumu vb.)
  değişmez.

## 5. Şeritler

Taban: `feat/ismail-geri-bildirim` üzerindeki Ş0 commit'i. Her şerit ayrı worktree/dal
(`feat/ism-s<n>-<ad>`), yalnız kendi dosyalarına dokunur, hedefli test + ruff + (portal) tsc/vitest
koşar, sonunda raporunda sözleşmeden sapmayı gerekçesiyle yazar.

| Şerit | Dal | Kapsam | Dokunduğu yerler |
|---|---|---|---|
| Ş1 core-onay | `feat/ism-s1-onay` | §3.1 API, §3.2 toplu onay, otomatik kod, `goruldu`, `codegen.start_generation(tetik=)` | `features/cases/{api,service}.py`, `features/otomasyon/{api,otokod}.py`, `features/codegen/service.py` (yalnız `start_generation` imzası + `tetik`) |
| Ş2 core-jira | `feat/ism-s2-jira` | §3.4 tümü + jira-sim | `features/requirements/{jobs,flow}.py`, `features/otomasyon/jira_tetik.py`, `integrations/jira.py`, `ports.py`, `sims/jira-sim/`, `features/demo/` |
| Ş3 core-veri | `feat/ism-s3-veri` | §3.3 tümü | `features/testveri/`, `features/cases/{service,testdata}.py` (store/submit/edit kancaları), `features/codegen/{service,checks}.py` (çözüm), `integrations/testmgmt.py`, `seed.py` |
| Ş4 portal | `feat/ism-s4-portal` | §3.5 tümü (API'ye karşı tip + mock'la) | `review-portal/src/**` |

Çakışma notu: Ş1 ve Ş3 ikisi de `cases/service.py` ve `codegen/service.py`'ye dokunur. Ş1 yalnız
`decide` sonu + `serialize_cases` (`goruldu`) + `start_generation` imzası; Ş3 yalnız
`store_cases`/`submit_drafts`/`decide(edit)` doğrulaması + `serialize_cases` (`veri`) + `run_generation`
içindeki case okuma noktası. Birleştirmeyi ana oturum yapar.

## 6. Test planı

- Birim (her şerit): toplu onay (görülmemiş atlanır, hash uyuşmazlığı tek öğeyi düşürür, diğerleri
  onaylanır), otomatik kod (ayar açık/kapalı, reddedilen case onayı geri almaz), ayar doğrulaması,
  Jira tetiği (yeni issue → ön inceleme; tekrar turda çift tetik yok; PO onayı → case üretimi
  kuyruğu; ayar kapalı), atıf eşleme/çözüm (belirsiz/kısa değer, kelime sınırı, değişmez),
  katalog CRUD + sürüm + 409'lar, kod üretiminde çözüm + `veri_izi`, yayında gizli korunması,
  `testdata.block()` metninin katalogdan aynı çıkması, migration/model eşitliği.
- Portal: vitest (toplu onay düğmeleri ve süzme, atıf çipleri, Test verisi CRUD, Otomasyon ayarları).
- Entegrasyon (birleşik worktree, izole compose `COMPOSE_PROJECT_NAME=tp-ismail`,
  `TP_IMAGE_PREFIX=tp-ismail`): Chrome for Testing ile ekran testi —
  (1) Demo kontrolünden TPD-x'i "QA To Do"ya taşı → Gereksinimler'de otomatik çekilip ön incelemeye
  girdiğini gör; (2) case review'da 3 case aç, "Tümünü onayla" → yalnız 3'ünün onaylandığını, kod
  üretiminin otomatik başladığını gör; (3) Test verisi'nde bir değeri değiştir → case kartında yeni
  değer ve script'te "veri değişti" uyarısı; (4) Otomasyon ayarında otomatik kodu kapat → onayda kod
  başlamadığını gör. Ekran görüntüleri `var/ekran-testi/013/`.
- Tam paket (pytest unit + vitest + ruff/tsc) yalnız dev'e birleştirmeden önce.

## 7. Review döngüsü

Birleşik worktree'de roller: **QA lideri / testçi** (İsmail'in gözüyle iş akışı), **güvenlik**
(rol kapıları, gizli veri, denetim izi, otomasyon aktörü), **backend mimar** (transaction/savepoint,
idempotentlik, iş kuyruğu, çakışma yüzeyi), **frontend / erişilebilirlik**, **ürün sahibi** (K1–K12
uyumu). Bulgu → düzeltme → yeniden review; kritik/yüksek bulgu kalmayınca döngü biter.

## 8. Açık maddeler (bu dalı engellemez)

- Hakan: "Copilot verip" ile kastedilen (GitHub Copilot IDE'de mi, Copilot Studio mu)?
- İsmail: v3 dev'e girince negatif senaryoları tekrar denesin.
- v3 ve uretim-dili dev'e girince: migration zinciri (`0030` → son halka), v3'ün case şemasındaki
  "test verisi" alanının katalog atfıyla ilişkisi, uretim-dili'nin `POST /code/generate` gövdesindeki
  `dil` alanı (otomatik kodda `null` = algılanan).

## 9. Review turu 1 (2026-11-12) — kararlar ve düzeltme sözleşmeleri

Beş rol (QA, güvenlik, backend, frontend, ürün sahibi) ~70 bulgu verdi; ürün kararı gerekenler:

| # | Konu | Karar |
|---|---|---|
| K13 | "Görüldü" | Kart **en az 3 sn kesintisiz görünür** kalınca görüldü sayılır (portal 3 sn sonra `POST /viewed`). Sunucu: toplu onayda görüntüleme ile karar arasında ≥ 3 sn şartı. Metinler tek dil: "en az 3 saniye ekranda kalan case'ler" |
| K14 | Tetik güvenliği | `jira_tetik.acik` varsayılanı **sim'de açık, gerçek Jira'da kapalı**. Açılınca (ve ilk turda) o anda durumda bekleyenler yalnız **işaretlenir** (`jira_durumu` yazılır, tetiklenmez); yalnız sonradan duruma **giren** story tetiklenir. Tur başına en çok **10** tetik. `durum` alanını yalnız **engineer** değiştirir. Otomasyon sayfası Jira'ya yazımı açıkça söyler |
| K15 | Tetik kapsamı | (a) Tetikle alınmış story içeriği değişip `new`'e dönerse yeniden ön incelemeye girer. (b) QA To Do'ya giren, `po_approved` ve etkin case'i olmayan story'de case üretimi hemen başlar. Gereksinim serileştirmesinde `otomatik_akis` rozeti (sürüyor / durdu + neden) |
| K16 | Açık PR / toplu | Otomatik üretim `pr_open` (ve süren) script'e **dokunmaz**: `atlandi` "Açık PR var; yeniden üretim mühendis kararıyla". Toplu onayda kod üretimi onay isteğinden ayrılır: tek `codegen.otomatik` arka plan işi, 20'lik parçalar. Teyit metni "n case için web kodu üretilecek" |
| K17 | Katalog → üretim | Model kipi **live/record**'da modele giden test verisi bloğu **katalogdan**; **replay**'de bugünkü DB bloğu. Test verisi sayfası bunu açıkça yazar |
| K18 | Eşleme kapsamı | Yalnız `bayi.*`, `urun.*`, `kampanya.*`, `ortak.*` (parola) eşlenir; `etiket.*` ve `ayar.*` eşlenmez. Tutar biçimli değerler (`… TL`, sayı) yalnız `steps[].data` ve `preconditions`'ta eşlenir |
| K19 | Gizli veri | Üretilen kod gizli değeri **ortam değişkeninden** okur (TS `process.env.<SIR>`, Java `System.getenv("<SIR>")`); PR/commit'te düz değer yok. Bug taslağı, `ScriptAdim` kayıtları, API/ekranlar **maskeler** (`•••`). Model/ajan girdisi çözülmüş kalır (REPLAY). Sır tanımsızsa ayrı engel türü **`test_verisi`** ("Test verisi sırrı tanımsız: <anahtar>") |

Düzeltme sözleşmeleri (şeritler bunlara uyar):
- `serialize_cases`: `onay_engeli: str | null` (approve'un reddedeceği neden: durum/RequirementChanged/bilinmeyen AC/katalogda olmayan atıf), `goruldu` K13'e göre (bu kullanıcının son karardan sonraki görüntülemesi ≥ 3 sn önce).
- `POST /cases/bulk-decision` yanıtı: öğe `otomatik_kod` artık `null`; üst düzey `otomatik_kod: {durum: "kuyrukta"|"kapali"|"yok", job_id|null, case_sayisi}`. Kilit sırası case_id'ye göre; `DBAPIError` öğe `hata`. Denetim özetinde öğe listesi (case_id, durum, neden); review'a `kanal: "toplu"` işareti.
- Tekli karar `otomatik_kod` aynen; açık PR'da `atlandi` (K16).
- `veri_izi`: `{anahtar: "<değer özeti sha256[:12]>"}` (sürüm değil); script serileştirmesi `veri_degisen: [anahtar]`, `veri_degisti = len(veri_degisen) > 0`. Açıklama/grup değişimi "veri değişti" saymaz.
- `script_codegen.engel_turu` CHECK'ine `test_verisi` (migration 0030 içinde).
- `test_verisi_surum` FK `ON DELETE RESTRICT`; tp_app'te `test_verisi` için DELETE yok.
- Gereksinim serileştirmesi: `otomatik_akis: {tetik_zamani, durum: "suruyor"|"durdu"|"tamam", neden: str|null} | null`.
- `GET /automation/jira-trigger` `son_tur`'a `sonuclar: [{jira_key, sonuc, neden}]` (hata metni sabit Türkçe; istisna ayrıntısı yalnız log).
- `PUT /automation-settings/jira_tetik` gövdesinde `durum` varsa engineer değilse 403.
