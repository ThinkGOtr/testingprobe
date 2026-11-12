# Değişiklik test rehberi — 2026-11-03 sürümü

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

## 8. Test kalite doğrulama (012)

Ayrıntı: [specs/012-test-kalite-dogrulama/ANALIZ.md](../specs/012-test-kalite-dogrulama/ANALIZ.md)
§9 kabul senaryoları ve §12.2 TPD-1 sonuç tablosu. Ön koşul: TPD-1 F2 `code_defect` yolunda (AC2
özgün) PO onaylı, case'ler üretilmiş.

| # | Ne yap | Beklenen | ☐ |
|---|---|---|---|
| 8.1 | Analist → TPD-1 → Karar tabloları → "AI taslağı" | İki tablo (Kampanya: 7 adette 1 bedava; Minimum sipariş 750) + bir ilişki, mor "AI" taslak; "örnekle dene" 6 adet → bedava 0, 7 adet → 1 | ☐ |
| 8.2 | Analist "PO onayına gönder" → PO "Onayla" | Tablo `approved`, onaylayan ve zaman görünür; case kartlarında kontrol çipleri birkaç saniyede dolar | ☐ |
| 8.3 | Case review: C3 (6 adette bedava yok) | "Tabloyla uyumlu ✓"; karşılaştırma bedava adet 0 = 0, indirim 0,00 = 0, toplam 150,00 = ara toplam; "Onayla" serbest | ☐ |
| 8.4 | C2 kartı | "Tabloyla uyumlu ✓"; 7 değer karşılaştırıldı: bedava adet 1, indirim 25,00 (= 175,00 / 7), toplam 150,00; karşılaştırılamayan yok | ☐ |
| 8.5 | C1, C7, C8 | "Tablo yok" (kapsam dışı) | ☐ |
| 8.6 | C5'i düzelt: yalnız S4 "Beklenen" alanını şu metinle değiştir (birebir kopyala; başka alana dokunma), gönder: `Toplam 150,00 TL; "Minimum sipariş tutarı 750,00 TL" uyarısı görünmez ve "Siparişi onayla" butonu aktiftir` | Önce kontrol beklenir; sonra "Tabloyla uyuşmuyor ✗" (REPLAY golden `case_facts/golden/rehber-duzeltme/TPD-1-C5`; metin farklıysa "kontrol edilemedi" olur), "Onayla" pasif, API 422 `oracle_uyumsuz` | ☐ |
| 8.7 | Aynı düzeltmeyi gerekçeyle (en az 20 karakter, 10 harf) "İstisnayla onayla" | Onaylanır; denetimde `oracle.exception`; Kontrol Kulesi istisna sayacı 1 | ☐ |
| 8.8 | Kontrol Kulesi | "Beklenti doğruluğu" %100 (6 uyumlu, 0 kısmen, 3 kapsam dışı, 1 tekrar: C10 = C2 tek sayılır; tablosu olan story'lerde kapsam %67 = 6/9; n ve "REPLAY / elle golden" etiketi görünür — gösterge, model ölçümü değil); ekilmiş hata koşusu yoksa "Hata yakalama oranı" ölçülmedi; kaynak metinleri görünür | ☐ |
| 8.9 | Karar tabloları → İlişkiler → "Ek case türet" | C2 ve C10'dan iki `draft` case (14 adet, bedava 2, indirim 50,00); C3, C4 "ön koşul sağlanmadı"; ek case'ler beklenti doğruluğunu değiştirmez | ☐ |
| 8.10 | Gereksinim metnini değiştir | Tablolar "bayat"; kontrolde kullanılmaz | ☐ |
| 8.11 | C3 testinin kırmızı koşusu (uygulama 6 adette 1 bedava) → Hata detay | "Ürün hatası"; sinyal "Test beklentisi onaylı karar tablosu … ile aynı, uygulama tablodan farklı (test beklentisi 0, gerçekleşen 1, tablo 0)" | ☐ |
| 8.12 | Beklenti farkı sınıflı bir hata (test_maintenance/beklenti) → Öneri | Mühendis "otomatik onarımı başlatın" görmez; Analist "Case'in beklenen değeri onaylı karar tablosuyla uyuşmuyor; case'i düzeltin" görür | ☐ |
| 8.13 | Mühendis/Sunucu → Kontrol Kulesi → Ekilmiş hata koşusu (web) | Temel yeşil → her hata için yakalandı/kaçtı → kapanış yeşil; oran hesaplanır, kaçanlar listelenir; bu koşular geçme oranına girmez, bug taslağı açılmaz | ☐ |

---
