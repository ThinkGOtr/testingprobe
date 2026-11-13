# 011 — İnceleme turu 1: bulgular ve kararlar

Kaynak: 4 rol incelemesi (güvenlik, test otomasyon mühendisi, mimar, DevOps/SRE) + Chrome for Testing 157
ekran testi, `feat/uretim-dili` @ 9de6f92..d6f4488. Kısaltmalar: GÜV, QA, MİM, OPS, EKR.

## Koordinatör kararları (bağlayıcı)

- **K-T1 Check adı (MİM-Y3):** web+TS `local-ci` (değişmez); **web+Java `local-ci-web-java`** (GitHub
  karşılığı `web-java` ile aynı mantık); uygulama `local-ci-<platform>` (değişmez). Tek kaynak
  `platform.check_adi(platform, dil)`; core, toolchain worker ve portal bunu kullanır/aynalar. Yerel
  merge kuralı: `e2e-java/` değişen PR `local-ci-web-java` ister, `e2e/` değişen `local-ci`.
  Script'siz PR CI'ı değişen yollardan dil(ler)i seçer (ikisi de değiştiyse ikisi de koşar).
- **K-T2 Push koşusu (MİM-O4):** merge sonrası push da paket koşusudur: repodaki tüm tam hat
  dilleri koşar (script'li push'a da kardeş dağıtımı uygulanır). Sözleşme metni buna göre.
- **K-T3 GitHub kipinde kardeş koşu (OPS-Y1/O1, GÜV-D3):** GitHub kipinde Java kardeş koşusu ve
  web+Java üretimi yalnız `java ∈ TP_WEB_DILLERI` iken; değilse `/code/languages` Java'yı
  `kullanilabilir=false` + neden döner. LocalForge'da repodaki dosyalar belirler (bugünkü).
- **K-T4 Doğrulanmamış dil ve etkin script (MİM-Y1):** `unverified` kayıt **etkin script sayılmaz**:
  doğrulanmamış üretim aynı case+platformun `pr_open`/`merged`/devam eden script'ine DOKUNMAZ
  (kapatma yok, forge'a yazma yok); eski `unverified` kayıtlar yenisi gelince `closed`.
  Tam hat dilinde istek, aynı case+platformda **başka dilde merge edilmiş** script varsa **409**
  (Türkçe: "Bu case'in web testi TypeScript ile merge edildi; dil değiştirmek için önce mevcut testi
  kaldırın"). `_eski_prlari_kapat` yalnız tam hat yolunda.
- **K-T5 Ajan tablosu (MİM-O5):** web'de doğrulama ajanına (canlı kip) repoda TS projesi varsa **TS
  sembol tablosu** verilir (PO eşitliği §2.5); Java tablosu deterministik denetim + render içindir.
  Repoda yalnız e2e-java varsa Java tablosu verilir ve audit'e `ajan_tablosu: java` yazılır.
  Prompt değişmez (değerlendirme kapısı etkilenmez).
- **K-T6 Doğrulanmamış çıktı yolu (MİM-O2, EKR-E3):** tek kaynak render: `Rendered.repo_path`
  doğrulanmamış dillerde `<e2e-csharp|e2e-python kökü>/<Ş2 alt yolu>`; `baslangic_dosya_yolu`
  aynı fonksiyonu çağırır.
- **K-T7 Java test dosyası kalıbı (MİM-O3, QA-Y1):** tek sabit `platform.py`: tam hat sayımı
  `*Test.java | *Testi.java | *Tests.java | *IT.java` (`birim/`, `uretilen/` hariç); algılama
  sinyali olarak `*Test.kt` de sayılır. `dil_algila` ve `ci/dil` aynı sabiti kullanır. Okuma
  bütçesi dil başına; test adı taşıyan dizinler önce.
- **K-T8 Rol kısıtı (GÜV-B1, QA):** Kod üretimi/Koşular kısıtı **arayüz düzenidir, yetki sınırı
  değil**; belgelenir. Yalnız `GET /code/languages` ucu `engineer|presenter` rollerine daraltılır.
- **K-T9 Ertelenenler (backlog, bu turda yok):** C#/Python namespace/paket proje ayarı ve PO iskelet
  indirmesi (QA-Y3'ün büyük kısmı), üretilen Java metot adının başlıktan türetilmesi (QA-O6),
  login literal'i yerine `dealer()` erişimcisi (QA-O4), Test case'leri CSV dışa aktarma ve satır içi
  adımlar, `@TmsLink` (guard değişikliği gerektirir). Bu turda QA-Y3'ün küçük kısmı yapılır: başlık
  "Elle düzenlemeyin" demez, gereken PO sınıf/metot imzalarını listeler; Python'da marker kaydı
  için `conftest.py` parçası başlıkta verilir.

## Şeritler (tur 1 düzeltme)

| Şerit | Bulgular |
|---|---|
| D1 core-codegen | MİM-Y1 (K-T4), MİM-O1 `referans_dil`, MİM-O2 yol (service tarafı, K-T6), MİM-O3/QA-Y1/QA-O1 algılama (K-T7), MİM-O5 (K-T5), MİM-L1 tek kaynak (codegen içi), MİM-L3 `dogrulanmamis` tek tanım, MİM-L7 docstring, GÜV-D2 (`head_sha` 60 sn önbellek, hata önbelleği, rol K-T8), MİM-O7 gerçek şablonla web+Java akış testi |
| D2 render-şablon | GÜV-D1 `fullmatch`, MİM-O2/K-T6 render yolu, QA-Y3 küçük kısım (K-T9), QA-O7 marker parçası, QA-düşük C# `…Async` adları |
| D3 ci-triage-forge-toolchain | K-T1 check adı (core ci + forge + toolchain worker `check_name`), K-T2 push, K-T3 GitHub kapısı + `views.py` `etkin_web_dilleri` (OPS-O1), GÜV-O1 DOM ayrıştırma sınırları, MİM-Y2 Kontrol Kulesi `unverified` sayacı, MİM-L1/L2 ci/triage/repair kopyaları ve `getattr` artıkları, MİM-L4 değil (göç penceresi riski; OPS-O2 runbook) |
| D4 portal | QA-Y2 çift rozet, EKR-E1..E4 mock sadakati (golden çıktılarla aynı kod, `goTo`, yollar) + 390 px üretilen testler tablosu, QA-O5 (case'e doğrudan bağlantı, otomasyon durumu sütunu), MİM-L5 adım durumu tipi, MİM-L6 yeniden üretimde `dil_kaynagi`, QA-Y1 algılama mesajı metni, K-T1 check adı etiketi, Kontrol Kulesi doğrulanmamış sayacı, eski Extent yorumu |
| D5 java-projeleri | QA-O2 Extent arşivi yalnız tekrar kipinde, QA-O3 Extent adı = description + `tp-case-*` kategori süzgeci + Allure etiketleri (story/tp-case/Jira Test) TestTabani'ndan, MİM-O7 e2e-java `uretilen/` örneğinin gerçek golden ile aynı olması + bunu sabitleyen test, QA-düşük (yuva semaforu, xpath seçici, `file.encoding` → `argLine`), OPS-O6 bellek (`argLine -Xmx`, `MAVEN_OPTS`) — pom değişirse `toolchain/e2e-java-deps/pom.xml` bayt eşit |
| D6 ops-doküman | OPS-Y1 demo repo init listesi + testi + `run-java-checks.sh` CI'da pom kilidi zorunlu, OPS-O1 compose/.env, OPS-O3 `forge-init` dizin eşitleme alt komutu, OPS-O4 env dokümanları, OPS-L1 yol filtresi, OPS-L3 Dockerfile katman sırası, OPS-L5 Playwright yükseltme kontrol listesi/betiği, MİM-O6 CODEOWNERS, doküman borcu (anayasa IV/V/VI + akış, TT §8.4–8.7, MİMARI-SOZLESME, 009 notu, 011 plan K-T1..K-T9, DEGISIKLIK-TEST-REHBERI, GCP-KURULUM + dağıtım sırası ve O2 backfill runbook'u), asistan prompt/öneri kuralları (MİM-L8; değerlendirme bekler) |
