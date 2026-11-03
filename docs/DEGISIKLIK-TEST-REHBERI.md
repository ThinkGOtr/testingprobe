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
| 2.2 | Ön incelemeyi başlat → kararlar (F1/F3 dokümanı düzelt, F2/F4 kod hatalı) → "Düzeltmeleri Jira'ya yaz" (bir kez) | Bittikten sonra tutarlılık kartının sağ üstünde düğme yerine **"✓ Doküman son hal · PO teyidi bekliyor"**; altında "… karar gerekmez" notu | ☐ |
| 2.3 | Jira'da PO cevabı + `tp-po-approved` → portalda TPD-1'i yenile | PO kartında **"✓ İnsan kapısı geçildi: PO onayı alındı, case üretimine geçilebilir."** | ☐ |
| 2.4 | Kontrol Kulesi → Hazırlık süresi | TPD-1 Manuel baz **2700 sn · ölçüm (Gokhan Sipahi)**; kazanç "(REPLAY: yalnız review)" etiketli | ☐ |

## 3. Jira'ya yazılan kayıtlar (şablon)

| # | Ne yap | Beklenen | ☐ |
|---|---|---|---|
| 3.1 | Case üret → Case review'da **yalnızca C8**'de "Düzelt", gerisini onayla → Yayın → "Seçilenleri yayınla" | Tüm case'ler **"oluşturuldu"**, **yeni** anahtarlar (TPD-8 ve sonrası); "farklı (eski) içerikle açılmış" hatası **yok** | ☐ |
| 3.2 | Jira'da yayınlanan bir Test'i aç | Açıklama 7 bölümlü şablonda; Test türü/Risk **Türkçe** (pozitif/negatif/sınır değer, yüksek/orta/düşük); Xray'de adımlar Action/Data/Expected | ☐ |
| 3.3 | Bölüm C'de F4 "Onayla ve Jira'da aç" → açılan Bug'ı aç | Açıklama 7 bölümlü şablonda, ilk satır "🤖 AI Testing Probe:"; Kullanıcı Akışı'nda adımlar, Diğer Bilgiler'de ortam + kanıt bağlantıları | ☐ |

## 4. Kod üretimi, kırarak doğrula, merge

| # | Ne yap | Beklenen | ☐ |
|---|---|---|---|
| 4.1 | Mühendis → Kod üretimi → C1, C2, C3, C5 (başlıklarıyla) → kod üret | 3 PR açılır (C1, C2, C5); C3 **"Defect adayı"**, PR yok | ☐ |
| 4.2 | C1 → Kırarak doğrula | 2. adım (BREAK_CAMPAIGN) yeşil ama **sarı ⚠ simgesiyle** "beklenmeyen sonuç"; sarı "Zayıf test" kutusu | ☐ |
| 4.3 | C1 → "Merge et"e GitHub Approve **olmadan** bas | "Merge reddedildi … onaylı insan review'u yok" (doğru davranış) | ☐ |
| 4.4 | GitHub'da C1 PR'ını Approve → portalda "Uyarıyı gördüm…" kutusu + Merge et | PR birleşir; GitHub PR'ında **"Testing Probe — açık kabulle merge"** yorumu (uyarı, kabul eden, not, kırarak doğrulama sonucu) | ☐ |
| 4.5 | Kod üretimi → Üretilen testler | Merge edilen C1 için Kırarak doğrula sütunu **"Kırma etkilemedi · kabulle birleşti"** | ☐ |
| 4.6 | Bir PR'da "Değişiklik iste" → (ret nedeni seç) → onayla | PR kapanır; o case üstteki **listeye geri gelir**, yeniden kod üretilebilir | ☐ |

## 5. Koşular, raporlar, Sauce

| # | Ne yap | Beklenen | ☐ |
|---|---|---|---|
| 5.1 | Sunucu → Koşular | Sağ üst düğmeler **"Gece koşusunu şimdi başlat"** ve **"Deploy sonrası testleri koş"**; üzerine gelince açıklama | ☐ |
| 5.2 | Merge'den hemen sonra "Deploy sonrası testleri koş" | GitHub Actions'ta deploy koşusunun `sauce` job'u öndeki Sauce bitene kadar **"Waiting"**; "concurrent session limit" hatası **yok** (bu, demo reposu CI güncellemesi merge edildikten sonra geçerli) | ☐ |
| 5.3 | Bir GitHub koşusunu aç → Raporlar ve bağlantılar | Playwright HTML raporu, JUnit XML, Allure, Koşu günlüğü **portalda** açılır (GitHub'a gitmez); "CI işi ↗" GitHub'a gider | ☐ |
| 5.4 | Aynı sayfada **Test sonuçları** | Durum düğmeleri (sayılarıyla), arama, dosya seçimi, sıralama, "Yalnız başarısızlar"; filtre adres çubuğunda | ☐ |
| 5.5 | Kırmızı bir teste tıkla | Hata + stack, Playwright adımları (hatalı adım vurgulu), ekran görüntüsü, video; trace için indirme + açma talimatı | ☐ |
| 5.6 | Aynı sayfada **CI adımları** kartı | GitHub job'ları bağlantılarıyla + ci-meta özeti; "Koşu günlüğünü burada göster" | ☐ |
| 5.7 | GitHub Actions'ta bir deploy koşusunun özetine bak | Sauce testleri kırmızıysa koşu **kırmızı**; Sauce'a ulaşılamadıysa koşu yeşil + **"⚠️ Sauce koşmadı: …"** uyarısı | ☐ |

## 6. Test bakımı demosu

| # | Ne yap | Beklenen | ☐ |
|---|---|---|---|
| 6.1 | Sunucu → Demo kontrolleri | Kart adı **"Test bakımı demosu"**, mavi "Bu demo ne gösteriyor? Test bakımı" açıklaması, düğme **"Buton kimliğini değiştir"** | ☐ |
| 6.2 | Düğme → "Evet, buton kimliğini değiştir" | Olay günlüğü akar; "Çalışan uygulama … main ile eşleşiyor" (birkaç saniye içinde) | ☐ |
| 6.3 | Kırmızı push koşusu → bir hatanın Triage sonucu → Mühendis → "Onarım PR'ı aç" | Onarım PR satırı **tıklanabilir** ve GitHub'daki PR'ı açar ("LocalForge'un web arayüzü yok" yazmaz) | ☐ |

## 7. Demo yol haritası (kapanış)

| # | Ne yap | Beklenen | ☐ |
|---|---|---|---|
| 7.1 | Sunucu → Demo yol haritası, 9. adım | Sauce koştuysa **"N koşu Sauce Labs'ta da koştu"** (tamam); ulaşılamadıysa nedeniyle uyarı — **"Sauce Labs kimliği yok" yazmaz** | ☐ |
| 7.2 | 12. adım (Triage) | C3'ün ürün hatası (kasıtlı kırma koşusu **değil**) | ☐ |

---

**Bilinen sınırlar (hata sayma):** Flaky kartı demo uygulaması deterministik olduğu için boştur.
"Case başına AI + review" ve maliyet REPLAY'de ölçülmez. Allure'un HTML raporu yoktur (CI yalnız ham
sonuç üretir; portal listeler). Trace tarayıcıda açılmaz, indirilir.
