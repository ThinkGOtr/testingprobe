# Değişiklik test rehberi — 2026-11-03 sürümü (+ 2026-11-11: 011 üretim dili, §4a)

Bu sürümde canlıya giden değişiklikleri **tek tek doğrulamak** için kontrol listesi. Tam demo
akışı için [CANLI-DEMO-SENARYOSU.md](CANLI-DEMO-SENARYOSU.md); bu belge yalnızca **yeni ve
değişen** davranışı sınar. Her madde: nerede, ne yap, ne görmelisin. Sonucu ☐ kutusuna işaretle;
beklenenden farklıysa ekran görüntüsüyle bildir.

Ön koşul: yükleme yapıldı, ardından sunucuda `make reset` (soruya `e`) ve `make demo-reset`
çalıştırıldı; Koşular'da başlangıç koşusu yeşil.

Portal: https://testing-probe.antreklabs.com · Jira: https://iyzitrace.atlassian.net/browse/TPD-1 ·
Demo reposu: https://github.com/ThinkGOtr/testingprobe-demo-app

---

## 1. Jira: reset ve görev şablonu

| # | Ne yap | Beklenen | ☐ |
|---|---|---|---|
| 1.1 | `make reset` → plan çıktısını oku | TPD-1..4 ve **TPD-5..7** için "döndürülecek / değişiklik yok" satırları; "Koşu kayıtları (silinecek, açık ve kapalı): …" listesi (önceki provaların TPD-8+ kayıtları); "Silinecek yorumlar" satırı. Soru: "… (koşu kayıtları SİLİNİR)? [e/H]" | ☐ |
| 1.2 | `e` ile onayla, sonra Jira backlog'u aç | Yalnızca **TPD-1..6** görünür (TPD-7 Done); TPD-8+ kayıtlar **silinmiş**. `HATA` satırı yok (varsa: TPD-7 Done düzenleme izni ya da silme izni eksik — bildir) | ☐ |
| 1.3 | Jira'da **TPD-5** ve **TPD-6**'yı aç | Açıklama 7 bölümlü şablonda (🎯 Objective … 🧪 QA Checklist); eski cümleler bölümlerin içinde; yorum yok | ☐ |
| 1.4 | Sunucuda `docker compose exec -T core-worker python -m tp_core.integrations.jira_seed` | Her satır "değişiklik yok"; "Jira zaten demo başlangıcında". (Değilse Jira emoji/biçimi değiştiriyor — bildir) | ☐ |

## 2. Portal: gereksinim ekranı

| # | Ne yap | Beklenen | ☐ |
|---|---|---|---|
| 2.1 | Analist → Gereksinimler → "Jira'dan çek" → **TPD-1** | **Doküman** kartı Jira'daki gibi: bölüm başlıkları ayrı satır, maddeler liste, akış numaralı; kabul kriterleri (AC1…AC6) "🔑 Acceptance Criteria" başlığı altında, QA Checklist'ten **önce** | ☐ |
| 2.2 | Ön incelemeyi başlat → kararlar (F1/F3 dokümanı düzelt, F2/F4 kod hatalı) → "Düzeltmeleri Jira'ya yaz" (bir kez) | Bittikten sonra tutarlılık kartının sağ üstünde düğme yerine **"✓ Doküman son hâl · PO teyidi bekliyor"** (sarı uyarı tonunda değil, mavi bilgi tonunda); altında "… karar gerekmez" notu | ☐ |
| 2.3 | Jira'da PO cevabı + `tp-po-approved` → portalda TPD-1'i yenile | PO kartında **"✓ İnsan kapısı geçildi: PO onayı alındı, case üretimine geçilebilir."** | ☐ |
| 2.4 | Kontrol Kulesi → Hazırlık süresi | TPD-1 Manuel baz **2700 sn · ölçüm (Gokhan Sipahi)**; kazanç "(REPLAY: yalnız review)" etiketli | ☐ |

## 3. Jira'ya yazılan kayıtlar (şablon)

| # | Ne yap | Beklenen | ☐ |
|---|---|---|---|
| 3.1 | TPD-1 sayfası sağ üst **"Case üret"** → sağ üst **"Case review"** düğmesi → **yalnızca C8**'de "Düzelt", gerisini onayla → Case review sayfasında **"Yayın önizleme"** → "Hedef" kartında **"Seçilenleri yayınla (n)"** | Tüm case'ler **"oluşturuldu"**, **yeni** anahtarlar (TPD-8 ve sonrası); "farklı (eski) içerikle açılmış" hatası **yok** | ☐ |
| 3.2 | Jira'da yayınlanan bir Test'i aç | Açıklama 7 bölümlü şablonda; Test türü/Risk **Türkçe** (pozitif/negatif/sınır değer, yüksek/orta/düşük); Xray'de adımlar Action/Data/Expected | ☐ |
| 3.3 | Bölüm C'de F4 "Onayla ve Jira'da aç" → açılan Bug'ı aç | Açıklama 7 bölümlü şablonda, ilk satır "🤖 AI Testing Probe:"; Kullanıcı Akışı'nda adımlar, Diğer Bilgiler'de ortam + kanıt bağlantıları | ☐ |

## 4. Kod üretimi, kırarak doğrula, merge

| # | Ne yap | Beklenen | ☐ |
|---|---|---|---|
| 4.1 | Mühendis → Kod üretimi → C1, C2, C3, C5 (başlıklarıyla) → kod üret | 3 PR açılır (C1, C2, C5); C3 **"Defect adayı"**, PR yok | ☐ |
| 4.2 | C1 → Kırarak doğrula | Bayraksız yeşil → kırık adımda (BREAK_CAMPAIGN=1) **⚠ "Yeşil · beklenmeyen sonuç"** → Bayrak kaldırıldı yeşil; sarı kutu **"Zayıf test: kırılmış uygulamada da yeşil kaldı"** | ☐ |
| 4.3 | C1 → "Merge et"e GitHub Approve **olmadan** bas | "Merge reddedildi … onaylı insan review'u yok" (doğru davranış) | ☐ |
| 4.4 | GitHub'da C1 PR'ını Approve → portalda "Uyarıyı gördüm…" kutusu + Merge et | PR birleşir; GitHub PR'ında **"Testing Probe — açık kabulle merge"** yorumu (uyarı, kabul eden, not, kırarak doğrulama sonucu) | ☐ |
| 4.5 | Kod üretimi → Üretilen testler | Merge edilen C1 için Kırarak doğrula sütunu **"Kırma etkilemedi · kabulle birleşti"** | ☐ |
| 4.6 | Bir PR'da "Değişiklik iste" → (ret nedeni seç) → onayla | PR kapanır; o case üstteki **listeye geri gelir**, yeniden kod üretilebilir | ☐ |

## 4a. Üretim dili (011): web + Java ve doğrulanmamış diller

Ön koşul: 011 dağıtımı yapıldı (`docs/GCP-KURULUM.md` §10.2 adım 0–8, e2e-app/e2e-java eşitlemesi
adım 5 dahil). GitHub kipinde web + Java için demo deposunda `demo-app/e2e-java/` + `web-java.yml`
merge edilmiş, ruleset'te `web-java` var ve `.env`'de `TP_WEB_DILLERI=ts,java` (§10.2 adım 10);
LocalForge'da `make forge-sync-dizin D=e2e-app K=uretilen` ve `make forge-sync-dizin D=e2e-java
K=uretilen` yapılmış (main demo-baseline'daysa `B=--baseline` ile).
Sunucu ve mühendis rolleri dil seçiciyi görür; Kod üretimi/Koşular ekranlarındaki rol kısıtı arayüz
düzenidir, yetki sınırı değildir (üretim ucu engineer ister).

| # | Ne yap | Beklenen | ☐ |
|---|---|---|---|
| 4a.1 | Mühendis → Kod üretimi → platform **Web** | Platform seçicinin yanında **dil seçici**; algılanan dil seçili gelir ve yanında "repodan algılandı" (sayılar ve nereye bakıldığı görünür). Değiştirince "elle seçildi" | ☐ |
| 4a.2 | `TP_WEB_DILLERI` boşken (GitHub kipi) dil seçici | **Java pasif**, nedeni görünür ("… TP_WEB_DILLERI …"); C# ve Python seçilebilir, "Doğrulanmamış" etiketli | ☐ |
| 4a.3 | Dil **Java** → C2 → kod üret | PR açılır; dosya `demo-app/e2e-java/src/test/java/com/antreklabs/bayi/uretilen/TPD1WebC2_<uuid8>Test.java` biçiminde; Kontroller'de **deps / guard / compile** adımları; kontrol adı **`local-ci-web-java`** (LocalForge) ya da **`web-java`** (GitHub); Kırarak doğrula çalışır | ☐ |
| 4a.4 | Java PR'ını merge et → Koşular | Merge sonrası push paket koşusu **iki dilde** koşar (TS + Java kardeş koşu); Java koşusunda **dil rozeti tek** ("Java", "Java Java" değil); rapor bağlantılarında Extent (test adları case açıklaması; `tp-case-*` kategori yok) ve Allure (story / tp-case etiketleri) | ☐ |
| 4a.5 | Aynı case (C2) için dil **TypeScript** seç → kod üret | **409**: "Bu case'in web testi Java ile merge edildi; dil değiştirmek için önce mevcut testi kaldırın" (başka dilde merge edilmiş script varken tam hat dili değiştirilemez) | ☐ |
| 4a.6 | Başka bir case (C5) için dil **C#** → üretimden önce uyarı → onayla | Ajan adımları tarayıcıda yine doğrulanır; durum **"Doğrulanmamış"**; kalıcı uyarı bandı + **"Kodu indir"**; PR / kırarak doğrula / merge kartları yerine "bu dilde yok" açıklaması; forge'da yeni dal/PR **yok** | ☐ |
| 4a.7 | C5'in açık TS PR'ı varken C# (ya da Python) üret | Açık TS PR'ı **kapanmaz**, script'i değişmez (doğrulanmamış kayıt etkin script sayılmaz); yalnız önceki doğrulanmamış kayıt "kapandı" olur | ☐ |
| 4a.8 | Doğrulanmamış Python çıktısını indir (C# için de) | Yol `…/tests/generated/test_<slug>.py` (C#: `…/tests/Generated/<Story>WebC<n>_<u8>Tests.cs`, metotlar `…Async`); dosya başlığı gereken PO sınıf/metot imzalarını ve `conftest.py` marker parçasını içerir; "Elle düzenlemeyin" yazmaz; portalda gösterilen yol indirilen dosyanınkiyle aynı | ☐ |
| 4a.9 | Kontrol Kulesi | "Doğrulanmamış" ayrı sayaçta; ilk review başarısı oranı doğrulanmamış script'lerden **etkilenmez** | ☐ |
| 4a.10 | Yalnız `demo-app/e2e-java/` değiştiren bir PR (GitHub) | `web-java` koşar; ci.yml `test-local` **no-op (başarılı)**. LocalForge'da yalnız `local-ci-web-java` aranır | ☐ |
| 4a.11 | "Yeniden üret" (algılanmış dille üretilmiş bir script) | Script'in dil kaynağı **"algılandı"** kalır ("elle seçildi"ye kaymaz) | ☐ |

## 5. Koşular, raporlar, Sauce

| # | Ne yap | Beklenen | ☐ |
|---|---|---|---|
| 5.1 | Sunucu → Koşular | Sağ üst düğmeler **"Gece koşusunu şimdi başlat"** ve **"Deploy sonrası testleri koş"**; ikisinin açıklaması başlığın altında **görünür** (gece: "… zamanlanmış koşuyu şimdi başlatır: aynı onaylı test paketi …"; "tam regresyon" yazmaz). Birine basınca yalnız o düğme döner | ☐ |
| 5.2 | Merge'den hemen sonra "Deploy sonrası testleri koş" | Deploy'un **"Sauce'ta Playwright (Chromium)"** adımı öndeki Sauce bitene kadar günlükte **"Sauce oturum sınırı dolu (başka koşu sürüyor); 60 sn sonra yeniden (n/20)"** notlarıyla bekler; "concurrent session limit" hatasıyla **düşmez** (bu, demo reposu CI güncellemesi merge edildikten sonra geçerli) | ☐ |
| 5.3 | Bir GitHub koşusunu aç → başlık + Raporlar ve bağlantılar | Başlıkta Sauce çipi ("Sauce: geçti" / "Sauce: kırmızı" / "Sauce koşmadı: …" / "Sauce atlandı: …"; koşu sürerken "Sauce: sırada/sürüyor"). Playwright HTML raporu, JUnit XML, Allure, Koşu günlüğü **portalda** açılır (GitHub'a gitmez); "CI işi ↗" GitHub'a gider. Yerel kopya alınamadıysa Allure "**(GitHub artefaktı)**" der; eksik dosyalar "(GitHub artefaktında)" diye GitHub koşusuna bağlanır; Allure hiç yoksa "(bu koşuda üretilmedi)" | ☐ |
| 5.4 | Aynı sayfada **Test sonuçları** | Durum düğmeleri (sayılarıyla), arama, dosya seçimi, sıralama, "Yalnız başarısızlar"; filtre adres çubuğunda | ☐ |
| 5.5 | Kırmızı bir teste tıkla | Hata + stack, Playwright adımları (hatalı adım vurgulu), ekran görüntüsü, video; trace için indirme + açma talimatı | ☐ |
| 5.6 | Aynı sayfada **CI adımları** kartı | GitHub job'ları bağlantılarıyla, sonuçları Türkçe (geçti / kaldı / atlandı / iptal / zaman aşımı) + ci-meta özeti; "Koşu günlüğünü burada göster" | ☐ |
| 5.7 | GitHub Actions'ta bir deploy koşusunun özetine bak | Sauce testleri kırmızıysa koşu **kırmızı**; Sauce altyapı adımı başarısızsa koşu yeşil + **"Sauce koşmadı: saucectl çalışmadı (başarısız altyapı adımı: …)"**; PR koşusunda uyarı değil **"Sauce atlandı"** notu | ☐ |

## 6. Test bakımı demosu

| # | Ne yap | Beklenen | ☐ |
|---|---|---|---|
| 6.1 | Sunucu → Demo kontrolleri | Kart adı **"Test bakımı demosu"**, mavi "Bu demo ne gösteriyor? Test bakımı" açıklaması, altında kapalı **"Teknik ayrıntı"**, düğme **"Buton kimliğini değiştir"**; ekranda "Locator kırma/kırılma" yazmaz (Demo yol haritası kartı: **"Test bakımı yolu"**) | ☐ |
| 6.2 | Düğme → "Evet, buton kimliğini değiştir" | Olay günlüğü akar; "Çalışan uygulama … main ile eşleşiyor" (birkaç saniye içinde) | ☐ |
| 6.3 | Kırmızı push koşusu → "Başarısızlıklar ve triage" kartında çip **"Test bakımı · locator"** → bir hatanın **"Triage sonucunu aç"** → Mühendis → "Onarım PR'ı aç" | Onarım PR satırı **tıklanabilir** ve GitHub'daki PR'ı açar ("LocalForge'un web arayüzü yok" yazmaz) | ☐ |

## 7. Demo yol haritası (kapanış)

| # | Ne yap | Beklenen | ☐ |
|---|---|---|---|
| 7.1 | Sunucu → Demo yol haritası, 9. adım | Sauce koştuysa **"N koşu Sauce Labs'ta da koştu"** (tamam); ulaşılamadıysa nedeniyle uyarı; koşu sürüyorsa **"Sauce job'u sırada/sürüyor"**; hepsi atlandıysa **"Sauce bu tetiklerde atlandı (…)"** — GitHub kipinde **"Sauce Labs kimliği yok" yazmaz** | ☐ |
| 7.2 | 12. adım (Triage) | C3'ün **"Ürün hatası"** (kasıtlı kırma koşusu **değil**) | ☐ |

---

**Bilinen sınırlar (hata sayma):** Flaky kartı demo uygulaması deterministik olduğu için boştur.
"Case başına AI + review" ve maliyet REPLAY'de ölçülmez. Allure'un HTML raporu yoktur (CI yalnız ham
sonuç üretir; portal listeler). Trace tarayıcıda açılmaz, indirilir.
