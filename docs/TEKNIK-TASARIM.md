# AI Automation Testing (Test Engineering Suite) — Demo Teknik Tasarımı

> **Sürüm:** v1.4 · 2026-10-30 · **Hazırlayan:** Gökhan Sipahi · **Gözden geçirecek:** Cengizhan Bey, Hakan, İsmail
> **Bağlayıcı kaynak:** "AI Automation Testing — Geliştirme Ekibi için Ürün Brief'i" (Cengizhan Bey, 30.10.2026). Bu doküman o brief'in **demo dilimini** tarif eder. Brief'ten sapmalar §19'dadır.
> **Spec Kit nedir:** GitHub'ın açık kaynak "spesifikasyon güdümlü geliştirme" aracı. Bu doküman önce projenin değişmez kurallarına (constitution, §3), sonra her kilometre taşı için ayrı spec → plan → görev → uygulama döngüsüne (§21) girdi olur.
>
> **v1.1 → v1.2:** Ekibin istediği 14 adımlı uçtan uca akış (ön inceleme + PO teyidi, kasıtlı kırma, gece/deploy CI, JUnit XML + Allure, Kontrol Kulesi, mükerrer tespitli triage, testçinin onaylı taslaktan kayıt açması) demo senaryosu oldu; **tüm akış canlı**; demo için sadeleştirmeler §2.1'de (Temporal yerine Postgres durum makinesi dahil). Sauce Labs eklendi (§0-13).
>
> **v1.0 → v1.1 (2026-10-30 ekip toplantısı kararları, §0):** demo 1 hafta içinde ve canlı; kapsam Demo-A + kısa otomasyon akışı; 4b kanalı Claude; tüm sapmalar onaylı; repo public.
>
> **v0.5 → v1.0:** Onayın doğruluk kaynağı Postgres (Update doğrulayıcı); test koşusu ayrı, izole `test-runner` servisinde; kırılma `demo-admin` bypass ile merge; CI imaj erişimi (izin, kimlik, çok mimarili build) ve `paths` çelişkisi giderildi; beklenen değer kontrolünde normalizasyon; Azure eşdeğerlik koşusuna sahip.
> **Değerlendirme:** 6 rol (mimar, test otomasyon lideri, AI/LLM mühendisi, güvenlik, DevOps, ürün sahibi) × 4 tur. Son tur puanları 8–9.
>
> **v0.4 → v0.5:** Kırılma ve sıfırlama branch korumasıyla uyumlu hale getirildi; testId kanıtı DOM'dan okunuyor; yerel kontrol CI ile aynı mekanizmada; assertion değerleri onaylı case'e bağlandı; şablon enjeksiyonu kapatıldı; IDE kanalı kimliği ve `submit_draft_cases` eklendi; deterministik kimlikler ve REPLAY-MISS; değerlendirme protokolü; sahipler paralelleştirildi; onay koruması sadeleştirildi.
>
> **v0.3 → v0.4:** 6 rollü değerlendirme sonrası. Kırılma adımı CI'da gerçekten çalışacak şekilde commit'e dayandı; doğrulama ve kod üretimi ayrıldı, kod şablondan üretiliyor; tehdit modeli ve prompt injection savunması eklendi; model geçidi ajan döngüsünü kapsıyor; triage önce deterministik; ölçüm tanımları düzeltildi; Docker/CI somutlaştı; Copilot kanalı demoya girdi; teslimat sırası ve sahipler eklendi.

---

## 0. Karar kaydı — 2026-10-30 ekip toplantısı

| # | Konu | Karar | Tasarıma etkisi |
|---|---|---|---|
| 1 | Demo tarihi | **1 hafta içinde** | Teslimat §17'deki "1 haftalık demo planı"na göre |
| 2 | Format | **Canlı**, katılımcılar iş birimi | Güvenlik gösterimi kapsam dışı; REPLAY ve video yedek kalır |
| 3 | CCI Jira | **Jira Cloud** | Rovo MCP kullanılabilir (CCI ortamında da) |
| 4 | CCI test yönetimi | **Jira (Xray'siz)** | Demodaki Jira yolu CCI'ın gerçek yolu; Octane öncelik dışı |
| 5 | Case üreten AI istemcisi (4b) | **Claude** (bizim kaynaklarımız; Claude Code) | Copilot lisansı demo için gerekmez; aynı MCP araçları |
| 6 | Brief'ten sapmalar (§19) | **Hepsi onaylı** (Claude, kendi uygulamamız, Jira, yerel Docker) | §19 durumları "onaylandı" |
| 7 | Agent Probe ilişkisi | **Tamamen bağımsız ürün** | Ortak çekirdek yok (ADR gerekmez) |
| 8 | GitHub | **Repo public** (demo için); Team planı demodan sonra | Ruleset ve GHCR public olarak ücretsiz; tasarım belgelerinin public olması kabul edildi; gizli RFI belgeleri `.gitignore`'da |
| 9 | Playwright dili | **TypeScript** | Değişiklik yok |
| 10 | Sahipler | F1 Hakan · F2a İsmail · çekirdek/Jira/portal Gökhan | §17 aynen |
| 11 | Jira demo sitesi + Rovo token | **Recep Bey** açacak | §18 |
| 13 | Test koşum platformu | **Sauce Labs (SaaS)**, Antrek hesabı, gerçek cihaz + bulut tarayıcı planı, 1–2 eşzamanlı oturum, hesabın bölgesi; kimlik (kullanıcı + access key) ekipten gelecek | §8.5 Sauce job'u; mobil fazda gerçek cihazlar; triage kanıtına Sauce video/log |
| 12 | 1 haftalık kapsam | ~~Demo-A canlı + kısa otomasyon~~ → **Tüm akış canlı** (karar 14–20) | §2 senaryosu, §2.1 sadeleştirmeler, §17 plan |
| 14 | Hedef akış | Ekibin 14 adımlı diyagramı (Jira → Ön inceleme → PO teyidi → Test case → Kod taslağı → Review + kasıtlı kırma → Korumalı ana dal → CI gece/deploy → Sauce + QA ortamı → Sonuçlar → Kontrol Kulesi → Triage → Kaydı açar → Jira) | §2 baştan yazıldı |
| 15 | PO teyidi | **Jira'da**: AI soruları story'ye yorum olarak yazar; PO Jira'da cevaplar ve onay etiketi koyar; ürün etiketi okuyup devam eder | §8.2a |
| 16 | Kasıtlı kırma | **İkisi de**: (a) hata yakalama kanıtı — uygulamada bilerek hata açılır, test kırmızıya dönmeli; (b) locator kırılması ve onarımı | §2 adım 6, 13–14 |
| 17 | Kontrol Kulesi | **Bizim ürünümüzde, portalda bir ekran**: kalite, flaky, karne | §8.11 |
| 18 | Jira bug "Faz 2 alanları" | Sonraki fazda; demoda temel bug alanları | §8.12 |
| 19 | 1 hafta, tüm akış canlı | **Tüm 14 adım canlı**, ince sürümlerle | §2.1 |
| 21 | Rakip analizinden (TheRafi) | **Demoya:** erişilebilirlik denetimi, serbest metin gereksinim girişi, Xray arka ucu. **Sonra:** TestRail, Zephyr. **Gerek yok:** tasarım dosyasından case üretimi, kurulum seçenekleri | §2.1, §17, §18, §20.1 |
| 22 | Doküman tutarlılık denetimi | **Sistem, test edilen uygulamanın GitHub reposuna ve veritabanına salt okuma erişimle analistin dokümanını (Jira story açıklaması + AC) iç tutarlılık, kod ve veri açısından denetler**; AI düzeltme önerir, analist onaylar, sistem Jira'yı günceller; kod hatalıysa bug taslağı; engelleyici bulgu kalmayınca "son hal" → PO teyidi | §2 adım 2, §8.2b, §17 |
| 20 | Demo sadeleştirmeleri | **Onaylı** (Temporal yerine demoda Postgres durum makinesi; tek ekran Kontrol Kulesi; deploy tetiği elle; triage kural + mükerrer arama) | §2.1, §19 sapma 14 |

---

## 1. Amaç ve başarı tanımı

**Amaç:** CCI'a, bir Jira story'sinin AI ön incelemesi ve PO teyidiyle netleştiğini, insan onaylı test case'lere ve AI olmadan koşan otomasyon koduna dönüştüğünü, sonuçların Kontrol Kulesi'nde izlendiğini ve başarısızlıkların AI triage'ı ile testçinin onayladığı Jira hata kaydına dönüştüğünü **canlı ve uçtan uca** göstermek.

**Demo başarılı sayılır, eğer:**
1. Tek bir Jira story'sinden başlayan 14 adımlık akış, yalnızca insan kapılarıyla müdahalesiz tamamlanır.
2. Üretilen test PR'da CI tarafından **AI olmadan** koşar ve yeşildir; kasıtlı açılan hata ile kırmızıya döner (test gerçekten hata yakalıyor).
3. Kırılan locator sonrası kırmızı CI, ürünün açtığı ve **yalnızca locator değerini değiştiren** onarım PR'ı ile tekrar yeşile döner.
4. Gerçek hata için AI triage mükerrerleri kontrol eder, taslak hazırlar; testçi onaylar ve Jira'da bug açılır.
5. Her AI çağrısı, araç çağrısı, onay ve ret kayıt altındadır.
6. Ekranda case hazırlamanın gerçek süresi ve kabul oranı görünür (RFI'daki "%30–50 hazırlık süresi azalması" hedefinin somut karşılığı).
7. Canlı akış aksarsa aynı adımlar "REPLAY" etiketiyle kayıtlı çıktılardan sürdürülür.

**Süre:** 20–25 dakika canlı akış + 5 dakika soru (CI beklemeleri Kontrol Kulesi ve mimari anlatımıyla doldurulur).

---

## 2. Demo senaryosu (ekibin 14 adımlı akışı)

Renkler ekibin diyagramıyla aynı: **AI adımı (taslak)** · **İnsan kapısı** · **Sistem**.

| # | Adım (diyagram) | Tür | Kim | Sistem davranışı | Ekranda |
|---|---|---|---|---|---|
| 1 | **Jira** — AC ve açıklama | Sistem | Analist | Rovo MCP ile story, açıklama ve kabul kriterleri okunur | Story listesi |
| 2 | **Ön inceleme** — soru, eksik ve **kod/veri tutarlılığı** | AI + İnsan | AI, Analist | (a) İç tutarlılık: belirsizlik, eksik AC, çelişki, test edilemeyen madde. (b) **Kodla karşılaştırma:** uygulamanın GitHub reposu salt okunur incelenir. (c) **Veriyle karşılaştırma:** uygulamanın veritabanı salt okunur sorgulanır. Her bulgu kanıtlıdır (dosya:satır, sorgu + sonuç) ve kanıt deterministik olarak yeniden doğrulanır. Analist her bulgu için: **dokümanı düzelt** (AI önerisi → onay → sistem Jira'daki açıklama/AC'yi günceller) · **kod/veri hatalı** (bug taslağı) · **bilinçli fark** (gerekçeli). Engelleyici bulgu kalmayana kadar yeniden kontrol → doküman "son hal". Kalan sorular Jira yorumu olarak yazılır, `tp-po-pending` etiketi eklenir (§8.2b) | Portal: bulgu kartları + kanıt; önerilen metin farkı; Jira'da güncellenmiş story |
| 3 | **PO teyidi** — insan kapısı | İnsan | PO | PO Jira'da soruları cevaplar (gerekirse AC'yi günceller) ve `tp-po-approved` etiketini koyar; ürün etiketi okur, story'yi güncel haliyle yeniden çeker. Etiket yoksa case üretimine geçilmez | Jira'da PO cevabı → portalda "PO onaylı" |
| 4 | **Test case** — AI iskelet, QA onay | AI + İnsan | AI, Analist (QA) | Şemalı pozitif/negatif/sınır case'ler (AC ve PO cevaplarına bağlı); QA onay/düzelt/reddet; onaylılar `publish_test_cases` ile Jira'ya (önizleme → yayın). **Claude kanalı:** Claude Code taslak üretir → `submit_draft_cases` → aynı QA onayı | Case kartları, sayaç, kabul oranı; Jira'da Test issue'ları |
| 5 | **Kod taslağı** — AI, ayrı dalda PR | AI | Mühendis + AI | Playwright MCP ile adımlar uygulamada doğrulanır → page object eşlemesi → şablonla TypeScript test → yerel kontrol → bot ayrı dalda PR açar | Adım ekran görüntüleri; PR linki |
| 6 | **Review** — insan + kasıtlı kırma | İnsan | Mühendis | Mühendis kodu inceler. **Kasıtlı kırma (a), hata yakalama kanıtı:** portaldaki "kırarak doğrula" düğmesi uygulamayı `BREAK_CAMPAIGN` bayrağıyla açar ve testi koşturur; test **kırmızı** olmalı (değilse PR "zayıf test" işaretlenir). Sonra bayraksız yeşil. Ardından merge | Yeşil → kırmızı → yeşil; "test hata yakalıyor ✓" |
| 7 | **Kurum git'i** — korumalı ana dal | Sistem | — | Ruleset: doğrudan push yok, CI + 1 insan onayı ile merge | Merge edilmiş PR |
| 8 | **CI runner** — gece ve deploy | Sistem | — | Workflow tetikleri: PR, `main` push, **gece** (`schedule`), **deploy** (`repository_dispatch`, demoda portal düğmesiyle elle) | Tetiklenen koşu |
| 9 | **Cihaz ve API** — Sauce, QA ortamı | Sistem | — | Onaylı testler **Sauce Labs** bulut tarayıcısında (Sauce Connect) ve yerel yedek job'da koşar; uygulama QA ortamı olarak CI'da ayağa kalkar | Sauce video linki |
| 10 | **Sonuçlar** — JUnit XML, Allure | Sistem | — | Playwright reporter'ları: `junit` (JUnit XML), `allure-playwright` (allure-results), JSON; artefakt olarak saklanır ve çekirdek tarafından alınır | Allure raporu linki |
| 11 | **Kontrol Kulesi** — kalite, flaky, karne | Sistem | — | Çekirdek JUnit XML'i ayrıştırıp veritabanına yazar; portalda tek ekran: son koşular, geçme oranı, flaky testler (aynı commit'te değişen sonuç / retry ile geçen), uygulama/story karnesi, AI katkısı (kabul oranı, süre) | Kontrol Kulesi ekranı |
| 12 | **Triage** — AI: mükerrer, taslak | AI | AI | Başarısız testler: önce deterministik kurallar (ortam / veri / gerçek defect / flaky; locator → bakım). Gerçek defect için Jira'da **benzer açık bug araması** (mükerrer tespiti: JQL metin araması + AI benzerlik yorumu) ve **bug taslağı** (adımlar, beklenen/gerçekleşen, kanıt linkleri: Sauce video, Allure). Locator kırılmasında onarım PR'ı önerisi | Sınıf, eşleşen sinyaller, "olası mükerrer: XYZ-12" |
| 13 | **Kaydı açar** — testçi, onaylı taslak | İnsan | Testçi | Testçi taslağı inceler, düzeltir ve onaylar (ya da mükerrerse mevcut kayda bağlar); onaysız kayıt açılmaz | Taslak → onay |
| 14 | **Jira** — hata (+ Faz 2 alanları) | Sistem | — | `publish_bug` ile Jira'da Bug açılır (temel alanlar; Faz 2 alanları sonra), story ve teste bağlanır | Jira'da yeni Bug |

**Demoda iki kırılma senaryosu** (karar §0-16):
- **Hata yakalama (adım 6 ve 12–14):** `BREAK_CAMPAIGN` ile kampanya indirimi yanlış hesaplanır → test kırmızı → triage "gerçek defect" → mükerrer kontrolü → taslak → testçi onayı → Jira'da Bug.
- **Locator kırılması (adım 12, bakım yolu):** `make break` (`add-to-cart` → `cart-add`) → triage "test bakımı/locator" → yalnızca locator'ı değiştiren onarım PR'ı → mühendis onayı → yeşil.

Demo story'si mutlaka `add-to-cart` ve kampanya hesabı adımlarını içerir.

### 2.1 Demo sürümü sadeleştirmeleri (karar §0-20)

| Konu | Ürün tasarımı | Demoda |
|---|---|---|
| İş akışı motoru | Temporal (§8.1) | **Postgres'te durum makinesi + basit worker (arka plan görev kuyruğu)**. İnsan kapıları aynı kuralla: onay yalnızca Postgres'teki oturumlu kullanıcı kaydıyla ve içerik hash'iyle; durum geçişleri tek bir servis fonksiyonundan yapılır. Temporal demodan sonra (§19 sapma 14) |
| Kontrol Kulesi | Kalite, flaky, karne, trendler, Power BI | Tek ekran (adım 11) |
| Deploy tetiği | Gerçek deploy olayından | Portal düğmesiyle `repository_dispatch` |
| Triage | Kural + LLM + benzerlik | Kural + JQL mükerrer araması + kısa LLM yorumu |
| PO teyidi | Jira iş akışı/geçiş ile | Etiket (`tp-po-approved`) + 15 sn'de bir sorgulama |
| Bug alanları | Faz 2 alanları dahil | Temel alanlar |
| Denetim zinciri, REPLAY, Allure tarihçesi | Tam | Kayıt var; zincir doğrulama ekranı, tarihçe sonra; REPLAY yalnızca adım 4 ve 5 için |
| Güvenlik gösterimi | Opsiyonel adım | Kapsam dışı |
| Erişilebilirlik denetimi | WCAG 2.2 AA, CI'da her koşuda (§20.1) | `@axe-core/playwright` ile demo story'sinin sayfalarında kontrol; ihlal sayısı Kontrol Kulesi'nde; kritik ihlal için bug taslağı |
| Serbest metin gereksinim | Ürün özelliği (§20.1) | Portalda gereksinim kutusu; PO teyidi Jira yerine portalda (PO rolü); sonra aynı akış |
| Test yönetimi arka uçları | Jira, Xray, TestRail, Zephyr, Octane | Jira + **Xray Cloud (deneme sürümü)**; TestRail ve Zephyr sonra |

---

## 3. Değişmez kurallar (constitution) ve teknik karşılıkları

| # | Kural (brief) | Teknik karşılık |
|---|---|---|
| 1 | AI üretir, insan onaylar | Onayın doğruluk kaynağı Postgres: core-api oturumdaki kullanıcıyla `review` satırını (`kullanıcı + nesne_id + içerik_hash`) yazar, ardından Temporal **Update** gönderir; iş akışının Update doğrulayıcısı Postgres'te eşleşen satır yoksa Update'i reddeder (Docker ağı içinden sahte Update etkisizdir). DB yazma kimliği yalnızca core-api ve core-worker'da. Yayın ve PR adımları güncel hash'i onaylanan hash ile karşılaştırır (onay sonrası değişiklik → red). Temporal gRPC ve UI yalnızca host'un `127.0.0.1`'inde; portal dışında onay yolu yok |
| 2 | CI'da AI yok | CI'da model anahtarı, MCP sunucusu ve ajan bağımlılığı yok; workflow `permissions: contents: read`; `pull_request_target` kullanılmaz |
| 3 | Yapılandırılmış çıktı | Claude'un yerel yapılandırılmış çıktı / strict tool kullanımı; Pydantic doğrulaması; şema hatasında hata mesajıyla en fazla 2 yeniden istek |
| 4 | Kütüphaneye bağlı kod | Kod modelden değil, doğrulanmış adım→page object eşlemesinden **şablonla** üretilir; ayrıca ESLint (`--no-inline-config`) ve `tsc --strict` PR'da ve CI'da zorunlu |
| 5 | Uygulamayı gerçekten gör | Her adım Playwright MCP snapshot'ında doğrulanmadan eşleme kabul edilmez; `--caps=vision` kapalı |
| 6 | Onarım yalnızca locator | `locators.ts` saf veri; AST koruması: anahtar kümesi ve niyet değişmez, yalnızca ilgili `testId` değeri değişir; aynı kontrol CI'da zorunlu check |
| 7 | Veri müşteride kalır | Model geçidinde ters çevrilebilir PII maskeleme (§8.9); demo yalnızca sentetik veri |
| 8 | Her şey kayıt altında | `ai_call`, `tool_call`, `audit_event` append-only ve `prev_hash` zinciriyle; zincirin son hash'i her yayında Jira yorumuna ve her PR açıklamasına yazılarak dışarıya sabitlenir; her AI çağrısı onaylayan kişiye iş akışı üzerinden bağlı |
| 9 | Ürün opsiyonel kalabilmeli | `rules/` altındaki prompt, kural ve şemalardan `CLAUDE.md` ve `.github/copilot-instructions.md` üretilir; `publish_test_cases` MCP aracı ürünsüz kanaldan da kullanılabilir |
| 10 | Her çıktı ölçülür | §12 ölçüm tanımları; her karar ve düzeltme kaydedilir |

---

## 4. Mimari

```
            Analist · Mühendis (tarayıcı)          IDE: GitHub Copilot / Claude Code
                       │                                         │ MCP
          Review Portal (React, nginx) ── REST + SSE ──┐         │
                                                       ▼         ▼
┌──────────────────────── Çekirdek (Python 3.12, FastAPI) ─────────────────────────────────┐
│  core-api: REST, SSE, kimlik, onay Update'leri, publish_test_cases MCP sunucusu           │
│  core-worker (Temporal, kuyruk: tp-core): iş akışları, model geçidi, ajan döngüsü,        │
│      Rovo okuma, Jira yazma, GitHub, triage, PII maskeleme (kütüphane)                    │
│  toolchain-worker (Temporal, kuyruk: tp-toolchain; toolchain imajı):                      │
│      checkout, sembol tablosu, şablonla kod üretimi, tsc, eslint, AST koruması,           │
│      commit/push — DB kimliği ve model anahtarı yok                                       │
│  test-runner (toolchain imajı): üretilen testleri ve demo uygulamasını koşturur —         │
│      yalnızca demo ağı + toolchain-worker kontrol ağı; Temporal, DB, sır, internet yok    │
├───────────────────────────────────────── Veri ───────────────────────────────────────────┤
│  PostgreSQL (alan verisinin tek doğruluk kaynağı) · Temporal (yalnızca ID ve kapı durumu)│
├──────────────────────────────────────── Araçlar ─────────────────────────────────────────┤
│  Rovo MCP (salt okuma) · Jira REST · Playwright MCP (Docker, demo-app-web'e kısıtlı) ·    │
│  GitHub App (PR açar, merge edemez)                                                        │
└──────────────────────────────────────────────────────────────────────────────────────────┘
                          │ PR (bot)
              GitHub Actions: AI'sız test + lint + AST koruması + Semgrep → JSON rapor, trace
              (çekirdek sonuçları GitHub API ile sorgular; Mac'e gelen bağlantı yok)
```

**Kararlar**
- **Doğruluk kaynağı:** Alan varlıkları (story, case, review, script, run, failure) Postgres'te. Temporal yalnızca kimlikleri ve kapı durumunu taşır; iş akışı geçmişinde içerik tutulmaz.
- **Gelen bağlantı yok:** CI durumu 5 sn aralıkla GitHub API'den sorgulanır.
- **AI yalnızca core-worker'da:** Model anahtarı yalnızca core-worker'da; toolchain-worker ve CI'da yok.
- **Okuma MCP ile, yazma kendi aracımızla** (brief).

---

## 5. Tehdit modeli ve prompt injection savunması

**Güven sınırları:** (a) Güvenilmeyen girdi: Jira story/açıklama, Confluence, uygulama sayfa içeriği (snapshot), CI log'ları. (b) Ajan: tarayıcıyı yönetir, kod önerir. (c) Etkili eylemler: Jira'ya yazma, PR açma, kod çalıştırma.

| Tehdit | Kontrol |
|---|---|
| Story'deki talimat ajanı kötüye kullanır ("şu URL'ye git", "testleri sil") | Güvenilmeyen içerik prompt'ta ayrı ve etiketli veri bloğunda; sistem kuralı: veri bloğundaki talimatlar uygulanmaz. Ajanın etkili eylemi yoktur: Jira yazma ve PR açma yalnızca onaylı kimliklerle, deterministik kodla yapılır |
| Ajan uygulama dışına gider / veri sızdırır | Playwright MCP `--allowed-origins http://demo-app-web`; aşama başına araç izin listesi (§8.4); `browser_evaluate`, dosya ve ağ araçları kapalı |
| Üretilen kod zararlı iş yapar | Kod şablonla üretilir (model serbest kod yazmaz); ESLint ile yalnızca `@playwright/test` ve `pages/` içe aktarımı; `fetch`, `process.env`, `child_process`, `eval`, dış URL yasak; kod yalnızca `test-runner`'da çalışır: Docker ağları `demo-net` (demo uygulaması) ve `runner-net` (yalnızca toolchain-worker'ın iş gönderdiği kontrol portu); Temporal, Postgres, sır ve internet erişimi yok. toolchain-worker'ın Temporal ve GitHub erişimi vardır ama kod çalıştırmaz ve DB kimliği yoktur |
| Onay adımı atlanır / taklit edilir | Onay Postgres'teki oturumlu kullanıcı kaydına bağlı; Update doğrulayıcısı eşleşen `review` satırı olmadan reddeder; toolchain-worker ve test-runner'da DB kimliği yok; Temporal host'ta yalnızca localhost. **Güvenlik testi:** test-runner'dan Temporal'a ve core-api'ye erişim denemesi başarısız olmalı |
| Şablona giren değerlerle kod enjeksiyonu | `args` değerleri yalnızca `JSON.stringify` ile string/number literal olarak basılır; metot imzasındaki türe göre doğrulanır; template literal ve birleştirme yok; enjeksiyon payload'ı ile birim testi |
| IDE kanalından yetkisiz yayın | Portalın verdiği kullanıcıya özel, kısa ömürlü, yalnızca `publish`/`submit` kapsamlı bearer token; MCP sunucusu yalnızca `127.0.0.1`; IDE'de araç için otomatik onay kapalı; kayıtta kanal ve çağıran |
| Onarım kılığında mantık değişikliği | AST koruması (§8.7) + CI'da zorunlu check + insan onayı |
| Bot kendi PR'ını merge eder veya `main`'e push eder | Repository ruleset: `main`'e doğrudan push yok, merge için CI + 1 insan onayı, "enforce for admins"; bypass yalnızca `demo-admin` insan hesabında, bot App'te yok. GitHub Team planı **kesin ön koşul** (§18); prova listesinde "bot `main`'e push eder → reddedilir" testi |
| Kayıt değiştirilir | `prev_hash` zinciri, append-only DB rolü, sıfırlamadan önce imzalı JSONL dışa aktarımı |
| Tedarik zinciri | İmajlar digest ile, Action'lar SHA ile sabit; lockfile'lar; Dependabot; Semgrep |

---

## 6. Bileşenler ve teknoloji

| Alan | Seçim |
|---|---|
| Çekirdek | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, resmi `mcp` Python SDK, `anthropic` SDK; bağımlılıklar `uv.lock` ile kilitli |
| İş akışı | Temporal Python SDK; sunucu `temporalio/temporal` imajı, `server start-dev` (SQLite dosyası, named volume), UI 8233 |
| Veri | PostgreSQL 16 |
| Model | Claude; görev başına sabit model kimliği (§8.8) |
| PII | Presidio **kütüphane olarak** core-worker içinde: TR regex tanıyıcıları (TCKN, IBAN, TR telefon, e-posta) + küçük spaCy modeli; ayrı servis yok |
| Gereksinim okuma | Rovo MCP (`https://mcp.atlassian.com/v1/mcp`), API token (Basic), istemcide yalnızca okuma araçları; B planı `JiraRestReader` |
| Test case yazma | `publish_test_cases` (Jira REST v3) + aynı servis MCP aracı olarak |
| Web otomasyonu | `mcr.microsoft.com/playwright/mcp` (sürüm sabit) |
| Üretilen kod | TypeScript + `@playwright/test` + `eslint-plugin-playwright` |
| Sembol tablosu | `ts-morph` (toolchain-worker) |
| Portal | React + Vite + TypeScript, build edilip nginx ile sunulur; SSE |
| Kod ve CI | GitHub, GitHub Actions, GitHub App (bot) |
| Örnek uygulama | FastAPI API + React web (nginx) |

**Tek sürüm kaynağı:** `.playwright-version` dosyası; MCP imajı, toolchain imajı, CI container imajı ve `@playwright/test` aynı Playwright sürümüne sabitlenir.

**Playwright Test Agents (Planner/Generator/Healer) neden demo hattında değil:** Generator serbest TypeScript ve ham locator yazar (kural 4 ile çelişir); Healer assertion değiştirebilir ve `test.fixme` ekleyebilir (kural 6 ile çelişir). Bu ajanlar **ürünsüz kanal** (kural 9) için `rules/` ile yapılandırılarak sunulur; ürün hattında kendi doğrulama döngümüz ve koruma katmanımız kullanılır. Karar demodan sonra ADR ile yeniden değerlendirilir.

---

## 7. Veri modeli

| Tablo | Alanlar (özet) |
|---|---|
| `app_user` | id, ad, rol (`analyst`/`engineer`/`presenter`), parola hash'i |
| `requirement` | id, jira_key, başlık, kabul kriterleri, kaynak_hash, çekim_zamanı, `ac_missing` |
| `test_case` | id (deterministik: `uuid5(jira_key + case_sıra_no + üretim_no)`), requirement_id, kanal (`portal`/`ide`), sürüm, tür, risk, ön koşul, adımlar, beklenen sonuç, AC referansları, durum, `ai_generated`, içerik_hash, onaylanan_hash |
| `review` | id, test_case_id, user_id, karar, ret_nedeni, önce/sonra, düzeltme_ölçüleri (§12), onaylanan_hash, zaman |
| `api_token` | id, user_id, kapsam (`publish`/`submit`), son_kullanma, iptal |
| `step_mapping` | id, test_case_id, adım_no, po_sınıfı, po_metodu, argümanlar, doğrulandı, ekran_görüntüsü_ref |
| `script` | id, dosya_yolu, branch, pr_no, durum, pass@1, onarım_sonrası_sonuç, insan_review_sonucu |
| `script_test_case` | script_id, test_case_id |
| `run` | id, script_id, pr_no, commit, github_run_id, sonuç, artefaktlar, süre |
| `failure` | id, run_id, test_adı, hata_imzası, sınıf, alt_tür, eşleşen_sinyaller, karar_kaynağı (`rule`/`llm`), öneri_türü, öneri_durumu |
| `requirement_review` | id, requirement_id, sorular (JSON), verdict, jira_comment_id, po_onay_kullanıcısı, po_onay_zamanı, durum (`pending_po`/`approved`) |
| `consistency_finding` | id, requirement_id, tur (tür), doc_ref, kanıtlar (JSON), kanıt_doğrulandı, severity, önerilen_metin, analist_kararı (`fix_doc`/`code_defect`/`accept_difference`), gerekçe, karar_veren, kontrol_turu, durum |
| `test_result` | id, run_id, test_adı, durum, süre, retry, commit, tetik (`pr`/`push`/`nightly`/`deploy`), kaynak (`local`/`sauce`) |
| `bug_draft` | id, failure_id, içerik (JSON), mükerrer_adayları, karar (`new`/`link`), onaylayan, onaylanan_hash, jira_key, durum |
| `external_ref` | entity_id, sistem (`jira`/`github`), idempotency_key, external_key, durum (`intent`/`created`/`failed`) |
| `workflow_instance` | id, tür, temporal_id, durum, başlatan |
| `ai_call` | id, parent_call_id, workflow_id, amaç, sağlayıcı, model, sürüm, bundle_hash (§8.8), maskeli girdi, çıktı, şema_geçerli, deneme, token, maliyet, süre, `replay` (`live`/`replay`/`replay_miss`) |
| `tool_call` | id, ai_call_id, kanal (`agent`/`ide`), çağıran_user_id, araç, argüman özeti, sonuç özeti, izin_verildi, zaman |
| `audit_event` | id, aktör, eylem, nesne, önce/sonra özeti, zaman, `prev_hash`, `hash` |

`ai_call`, `tool_call`, `audit_event` için uygulama rolünün yalnızca INSERT/SELECT yetkisi vardır.

**Test case şeması:**
```json
{
  "title": "string (≤120)",
  "type": "positive | negative | boundary",
  "risk": "high | medium | low",
  "acceptance_criteria_refs": ["AC1"],
  "preconditions": ["string"],
  "steps": [{"id": "S1", "action": "string", "data": "string|null", "expected": "string"}],
  "expected_result": "string",
  "tags": ["AI-generated"]
}
```

**Ret nedeni taksonomisi:** halüsinasyon adımı · eksik kabul kriteri · yanlış test verisi · kapsam dışı · tekrar · yanlış eleman/aksiyon.

---

## 8. Bileşen detayları

### 8.1 İş akışları (Temporal)

Her iş akışı **tek başına, kimliklerle başlatılabilir** (seed ve prova için).

```
RequirementToCases(jira_key)
  fetch_requirement → generate_cases → [Update: case kararları (case başına)] → [Update: review tamam]
  → publish_preview → [Update: yayınla(imzalı)] → publish_to_jira

CasesToCode(case_ids)
  verify_and_map (ajan, max 1 deneme) → render_test (şablon) → local_check
  → open_pr (bot) → poll_ci → [insan: GitHub'da review + merge] → poll_ci(main)

FailureToFix(run_id)
  collect_artifacts → classify (kural → gerekirse LLM) → propose_locator_fix
  → ast_guard → local_check → open_fix_pr (bot) → poll_ci → [insan: review + merge]
```

- **Ajan aktivitesi:** `maximum_attempts=1`, heartbeat 30 sn, `start_to_close` 10 dk; hata → otomatik yeniden deneme yok, insan kapısı.
- **Diğer aktiviteler:** idempotent; dış etkili olanlar `external_ref` kaydına bağlı.
- **Sürümleme:** iş akışı değişiklikleri `workflow.patched` ile.

### 8.2 Gereksinim okuma
- Rovo MCP, demo projesinde salt okuma kullanıcı + API token; istemci izin listesi yalnızca okuma araçları.
- Çekilen: özet, açıklama, kabul kriterleri. (Confluence sayfası varsa özetlenir; demoda zorunlu değil.)
- `ac_missing=true` → portalda uyarı ve analiste soru; story case üretimine gönderilmez.
- İstek sınırı: çağrı sayacı, küçük JQL, 5 dk önbellek.
- **B planı:** `JiraRestReader` (aynı arayüz). Demo günü Rovo bağlantısı prova edilir; sorun varsa B planı varsayılan olur.

### 8.3 `publish_test_cases`
- **Girdi:** yalnızca `approved` durumundaki case kimlikleri; içerik kabul etmez.
- **Kontrol:** her case için `içerik_hash == onaylanan_hash`; değilse red.
- **Eşleme:** issue türü `Test` (yoksa `Task` + `test-case` etiketi); özet, ADF tablo (adım/veri/beklenen), etiketler `AI-generated` ve `tp-<uuid>`, story bağlantısı (`is tested by`, yoksa `relates to`), açıklamada onaylayan ve kaynak story.
- **Idempotency:** önce `external_ref` (`intent` yazılır → create → `created` + anahtar); yeniden denemede önce bu tablo, kayıt yoksa `tp-<uuid>` JQL'i. Aynı hash'te çağrı yapılmaz.
- **Dry-run, hata yönetimi:** önizleme portalda; 429/5xx üstel geri çekilme (≤3); kısmi başarı raporlanır.
- **MCP araçları (IDE kanalı):**
  - `submit_draft_cases(requirement_key, cases[])`: IDE'deki Copilot'un ürettiği şemalı taslakları `draft` olarak portala düşürür; şema doğrulanır; Jira'ya yazmaz.
  - `publish_test_cases(case_ids: list[uuid])`: yalnızca onaylı kimliklerle yayın.
  - Kimlik: portalın kullanıcıya verdiği kısa ömürlü (8 saat), kapsamlı bearer token (`Authorization` başlığı); sunucu yalnızca `127.0.0.1`; kayıtta kanal = `ide`, çağıran ve onaylayan ayrı.

### 8.4 Kod üretimi: doğrula → eşle → şablon
1. **Bağlam:** onaylı case (≤5 adım demo için) + sembol tablosu (page object sınıfları, metotları, imzaları, locator niyetleri, `expect*` doğrulama metotları) + `rules/verify-and-map.md`.
2. **Doğrulama döngüsü (ajan):** her adım için uygulamada eylemi yapar, snapshot'ta hedef elemanı bulur ve **sembol tablosundaki bir metoda** eşler. Çıktı şemalı:
   `step_mapping[{step_id, po, method, args, verified, evidence_ref}]` ve `expects[{po, method, args}]`.
3. **Deterministik kontroller:**
   - her `po.method` sembol tablosunda var mı; argüman türleri imzaya uyuyor mu;
   - her `expects.args` değeri onaylı case'in `expected` / `expected_result` metninde geçiyor mu (assertion değerini model uyduramaz); karşılaştırma öncesi sayı, para ve boşluk biçimi normalize edilir (`1.250,00 TL` ≡ `1250`).
   Biri tutmazsa durur: eksik metot → mühendise "page object'te eksik metot"; kaynağı olmayan beklenen değer → insana.
4. **Şablon:** test dosyası eşlemeden şablonla üretilir; model TypeScript yazmaz; değerler `JSON.stringify` ile literal basılır.
5. **Yerel kontrol (toolchain-worker derler, `test-runner` koşturur; CI ile aynı mekanizma):** ilgili commit checkout edilir, uygulama `test-runner` içinde Playwright `webServer` ile o commit'ten başlatılır; `tsc --strict`, ESLint, `playwright test --repeat-each=3`.
   - Kırmızı ve hata **locator/eşleme** kaynaklıysa 1 düzeltme turu (yeniden eşleme); düzeltme turu `expects`'i değiştiremez.
   - Kırmızı ve hata **assertion** kaynaklıysa düzeltme yapılmaz; insana "defect adayı" olarak gider.
6. **PR (bot):** branch `tp/case-<uuid>`; önce aynı branch için açık PR aranır; açıklamada case, Jira, doğrulama özeti, "AI-generated".

**Ajan sınırları:** case başına en fazla 25 araç çağrısı ve ~150k girdi token'ı; bağlamda yalnızca son snapshot tutulur; sistem prompt'u ve sembol tablosu prompt önbelleğinde. **Araç izin listesi:** `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_select_option`, `browser_wait_for`, `browser_generate_locator`. Ekran görüntüsü aracı ajana **verilmez** (kural 5). **Gecikme bütçesi:** adım 5 için 120 sn; aşılırsa portal kullanıcıya REPLAY'e geçmeyi önerir.

**Canlı görünürlük:** her ajan eyleminden sonra core-worker, model döngüsünün dışında ayrı bir MCP oturum çağrısıyla ekran görüntüsü alır ve SSE ile portala akıtır; görüntü modele gönderilmez.

### 8.5 CI (AI'sız)
- **Toolchain imajı:** ayrı `build-toolchain` workflow'u, `docker/build-push-action` ile `platforms: linux/amd64,linux/arm64` ve `cache-from/to: type=gha`; etiket `.playwright-version`'dan türetilir, kullanıldığı her yerde digest ile sabitlenir; GHCR paket ayarında `testingprobe` reposuna Actions erişimi verilir.
- **Job:** `container: ghcr.io/thinkgotr/tp-toolchain@<digest>` (toolchain-worker ve test-runner ile aynı imaj: Playwright tarayıcıları + Node + Python + uv), `container.credentials: { username: ${{ github.actor }}, password: ${{ secrets.GITHUB_TOKEN }} }`; demo uygulaması her ortamda aynı yolla, Playwright `webServer` dizisiyle başlar: `uv run uvicorn` (API) ve `vite build && vite preview` (web); `BASE_URL` tek kaynaktan.
- **Adımlar:** `npm ci` (önbellekli) → `tsc --strict` → `eslint --no-inline-config` → AST koruması → `playwright test --retries=1 --project=chromium` (JSON + HTML + trace) → artefakt.
- **Zaman aşımları:** `actionTimeout` 5 sn, `expect.timeout` 5 sn, test 20 sn (kırık locator'lı kırmızı koşu < 60 sn).
- **Ayrı job:** Semgrep (SAST).
- **Zorunlu check'ler her PR'da koşar:** workflow düzeyinde `paths` filtresi **yok**; test, AST koruması ve Semgrep job'ları her PR'da tetiklenir, değişiklik tespiti job içinde (`dorny/paths-filter@<SHA>`) yapılır ve ilgisiz PR'da adımlar "no-op, başarılı" çıkar (atlanan zorunlu check PR'ı bekletir).
- **Ayarlar:** `permissions: { contents: read, packages: read }`; `concurrency: cancel-in-progress`; Action'lar SHA ile; `npm ci --ignore-scripts` (lockfile sabit).
- **Hedef süre:** koşu başına ≤ 2 dk (yerel job).
- **Sauce Labs job'u (demodaki ana gösterim, karar §0-13):** aynı onaylı testler `saucectl` ile Sauce Labs bulut tarayıcılarında (Chromium/Chrome) AI'sız koşar. Demo uygulaması CI runner'ında ayağa kalkar ve **Sauce Connect** tüneliyle yalnızca Sauce'a açılır. Kimlik: `SAUCE_USERNAME` ve `SAUCE_ACCESS_KEY` GitHub Actions secret'ı (Antrek hesabı; bölge hesabın bölgesi). Eşzamanlılık 1–2 oturum. Koşu sonucu, Sauce video ve log linki PR yorumuna yazılır; çekirdek sonucu GitHub API ve Sauce REST API'den alır. Yerel Chromium job'u **yedek** olarak koşmaya devam eder; Sauce veya tünel hatası PR'ı kilitlemez (Sauce job'u zorunlu check değildir, yerel test job'u zorunludur).
- **Ruleset:** `main`'e doğrudan push yok; merge için CI yeşil + 1 insan onayı + CODEOWNERS (`pages/**`, `.github/**`); "enforce for admins"; bypass yalnızca `demo-admin` (insan) hesabı. Ücretsiz planda private repoda kullanılamaz → GitHub Team (§18).

### 8.6 Triage (önce kural)
1. **Kanıt:** JSON rapor, `trace.zip` (DOM snapshot'ları dahil), hata anındaki aria snapshot (`error-context`, yalnızca rol ve ad içerir), koşu öncesi sağlık kontrolü sonucu.
2. **Deterministik kurallar (sırayla):**
   - Sağlık kontrolü başarısız veya ağ hatası → `environment`
   - Playwright `flaky` durumu (retries ile) → `flaky`
   - Locator 0 eleman döndürdü **ve** niyete uyan eleman (rol + ad, aria snapshot'tan) aynı sayfada var **ve** DOM'daki `data-testid` değeri farklı (§8.7'deki yöntemle okunur) → `test_maintenance/locator`
   - Assertion farkı ve sayfa yapısı beklenen → `product_defect` adayı
   - Test verisi ön koşulu sağlanamadı (seed/reset hatası) → `test_data`
3. **LLM:** yalnızca hiçbir kural eşleşmezse; şemalı sınıf + gerekçe. Deterministik `environment` sonucunu ezemez.
4. **Gösterim:** sayısal güven yerine eşleşen sinyaller listesi.
5. **Brief'in 4 sınıfı ile ilişki:** `test_maintenance` brief'teki "kırılan locator için onarım önerisi" yoludur; dört kök neden sınıfının dışında, ayrı izlenir (§19, onaylandı).

### 8.7 Locator onarımı
- **`locators.ts` saf veri:** `export const cart = { addToCart: { testId: 'add-to-cart', role: 'button', name: 'Sepete ekle', intent: 'Ürün kartında sepete ekleme butonu' } } as const;`
- **Aday üretimi (LLM'siz):** aria snapshot `data-testid` içermediği için testId DOM'dan okunur: toolchain-worker kırılan commit'te uygulamayı başlatır, kırılan testi hata adımına kadar koşturur ve `getByRole(role, { name }).getAttribute('data-testid')` değerini okur (alternatif kaynak: `trace.zip` içindeki DOM snapshot'ı). Rol + ad eşleşmesi 0 veya birden fazla eleman verirse öneri üretilmez, insana (veya LLM yorumuna) düşer. `browser_generate_locator` yalnızca çapraz kontrol.
- **Doğrulama:** aday, son yeşil koşudaki aria snapshot'ının `role + name` değerleriyle eşleşmeli (yanlış butona "onarmayı" önler).
- **AST koruması:** değişen dosyalar yalnızca `pages/**/locators.ts`; anahtar kümesi, `role`, `name`, `intent` değişmemiş; yalnızca ilgili `testId` string değeri değişmiş. Aynı kontrol CI'da zorunlu check.
- **PR:** yerel kontrol **etkilenen tüm testlerde** yeşilse (AI'ın ürettikleri ve elle yazılmış olanlar) bot açar; insan onayı zorunlu.
- **Birim testleri:** 0 eşleşme, çoklu eşleşme, anahtar/niyet değişikliği denemesi, test dosyasına dokunan yama.

### 8.8 Model geçidi
- **İki giriş:** `gateway.call(purpose, bundle, messages, schema, max_tokens, budget)` ve `gateway.run_agent(purpose, bundle, tools, max_turns, budget)`.
- **Sağlayıcıdan bağımsız sözleşme:** girdiler (mesajlar, araç tanımları JSON Schema, çıktı şeması) ve çıktılar (yapılandırılmış sonuç, araç çağrıları, token) ortak tiptedir; sağlayıcıya özgü özellikler (Anthropic prompt caching, strict tool; Azure OpenAI structured outputs) yalnızca adaptörde. Değerlendirme seti her iki sağlayıcıda koşup kabul oranları yan yana raporlanır (Azure erişimi olduğunda).
- **Ajan:** Anthropic SDK tool-use döngüsü (kendi döngümüz); her tur bir `ai_call` satırı, `parent_call_id` ile bağlı; her araç çağrısı `tool_call`.
- **Görev başına model (sabit kimlik konfigürasyonda):** case üretimi ve doğrulama ajanı → Claude Sonnet sınıfı; triage ve özetleme → Claude Haiku sınıfı; `temperature` sabit (0–0,2).
- **Hata politikası:** 429/529/5xx → üstel geri çekilme, ≤3; şema hatası → hata metniyle ≤2 yeniden istek. Aktivite yeniden denemesi `ai_call.id` ile idempotent (aynı çağrı iki kez faturalanmaz).
- **Sürüm (bundle):** `bundle_hash` = kurallar + şema + few-shot örnekleri + model kimliği + parametrelerin birleşik hash'i.
- **Maliyet tavanı:** iş akışı başına 2 USD, günlük 30 USD; aşılırsa duraklat ve insana sor.
- **Replay:** anahtar `purpose + jira_key + case_sıra_no + input_hash + bundle_hash` (rastgele UUID içermez; `input_hash` zaman damgası ve snapshot ref'leri normalize edilmiş girdiden). Kod üretimi için dosya düzeyinde "golden" test dosyası ve doğrulama kaydı. Iskalama sessiz geçmez: portalda **REPLAY-MISS** gösterilir ve adlandırılmış golden kayda düşülür. Kayıtta `live`/`replay`/`replay_miss`.

### 8.9 PII maskeleme
- **Uygulanan yer:** gereksinim metni, Confluence, CI log'ları. **Uygulanmaz:** snapshot ve kod (yalnızca sentetik veri, `data-testid` ve rol adları korunur).
- **Ters çevrilebilir yer tutucular:** `<<PII_EMAIL_1>>`; eşleme iş akışı kapsamında saklanır, model çıktısında geri açılır.
- **İzin listesi:** sentetik test verisi alanları ve ürün/kampanya adları.
- **Kayıt:** maskeleme farkı `ai_call`'a yazılır; birim testleri TCKN, IBAN, telefon, e-posta ve yanlış pozitifleri kapsar.

### 8.10 Review Portal
- **Ekranlar:** Story listesi · Case review (onay/düzelt/reddet, ret nedeni, fark, AI süresi, kabul oranı) · Yayın önizlemesi · Kod üretimi (adım ekran görüntüleri canlı, PR linki) · Koşu ve triage (sinyaller, öneri, PR linki, **denetim paneli** ve zincir doğrulaması).
- **Kimlik (demo):** seed kullanıcılar (`analist`, `muhendis`), oturum çerezi; her karar kullanıcı adına imzalı.
- **REPLAY rozeti** kayıtlı çıktı kullanıldığında görünür.

---

### 8.2a Ön inceleme ve PO teyidi (adım 2–3)
- **Ön inceleme (AI):** girdi story + AC; çıktı şemalı `requirement_review{questions[{id, type: ambiguity|missing_ac|conflict|untestable, text, ac_ref}], verdict: ready|needs_po}`. Sorular güvenilmeyen içerik kuralına tabidir (§5).
- **Jira'ya yazma:** sorular tek bir yorum olarak (numaralı, "AI-generated" etiketiyle) story'ye eklenir; `tp-po-pending` etiketi konur. `verdict = ready` ise yine de PO teyidi istenir (insan kapısı atlanmaz).
- **PO teyidi:** PO cevapları Jira yorumu olarak yazar, gerekirse AC'yi günceller ve `tp-po-approved` etiketini koyar. Ürün 15 sn'de bir sorgular; etiket görülünce story yeniden çekilir (`kaynak_hash` güncellenir), PO cevapları case üretim bağlamına eklenir ve kapı açılır. Etiketi koyan kişi Jira'dan okunup kayda yazılır.
- **Yetki:** yazma kullanıcısı yalnızca yorum, etiket, Test ve Bug oluşturma yetkili.

### 8.2b Doküman tutarlılık denetimi: kod ve veriyle (adım 2, karar §0-22)

**Amaç:** Test case üretiminden önce analistin dokümanını (Jira story açıklaması + AC) kendi içinde ve uygulamanın gerçek kodu ve verisiyle tutarlı hale getirmek.

**Erişim (salt okuma, en az yetki):**
- **Kod:** GitHub'ın resmi MCP sunucusu (`github-mcp-server`) **read-only modda**, yalnızca `repos` ve `code_search` araç setleri; ince yetkili token, yalnızca test edilen uygulamanın reposunda `contents:read`.
- **Veri:** kendi `db_schema` ve `db_query` araçlarımız: yalnızca okuma yetkili veritabanı rolü (`demoapp_ro`); izin listesindeki şema/tablolar; tek `SELECT` (SQL ayrıştırıcıyla zorlanır), `statement_timeout` 5 sn, en fazla 100 satır; sonuçlar modele gitmeden PII maskelemesinden geçer. Genel amaçlı "her SQL'i çalıştıran" MCP sunucusu kullanılmaz.
- Kod ve veri içeriği **güvenilmeyen girdi**dir (§5).

**Akış:**
1. Story + AC okunur; AI önce iç tutarlılığı inceler.
2. AI, kod araçlarıyla ilgili modülleri (kampanya, sepet, sipariş kuralları) ve veri araçlarıyla ayar/tanım tablolarını inceler; dokümandaki her ölçülebilir iddiayı (tutar, oran, sınır, alan, durum, mesaj) kodla ve veriyle karşılaştırır.
3. Çıktı şemalı: `consistency_finding{id, type: internal_contradiction|doc_vs_code|doc_vs_data|missing_in_doc|missing_in_code|ambiguous, doc_ref (AC no / cümle), evidence[{kind: code, repo, path, line, snippet} | {kind: data, query, result_digest}], severity: blocking|warning, suggested_doc_text}`.
4. **Kanıt doğrulama (deterministik, LLM'siz):** kod kanıtı GitHub'dan yeniden çekilir, alıntı ilgili satırda birebir bulunmalı; veri kanıtı sorgusu yeniden çalıştırılır, sonuç özeti eşleşmeli. Doğrulanamayan bulgu gösterilmez (halüsinasyon önlemi, Constitution XI).
5. **Analist kararı (bulgu başına):** `fix_doc` (önerilen metni düzenler/onaylar) · `code_defect` (bug taslağına gider, §8.12) · `accept_difference` (gerekçe zorunlu).
6. **Jira güncelleme:** onaylanan `fix_doc` değişiklikleri tek seferde story açıklamasına/AC'ye yazılır (onaylanan içerik hash'i kontrol edilir; Jira geçmişi önceki sürümü saklar); değişiklik özeti Jira yorumu olarak eklenir; `requirement.kaynak_hash` güncellenir.
7. **Yeniden kontrol:** güncellenen doküman tekrar denetlenir; `blocking` bulgu kalmayınca doküman "son hal" olur ve PO teyidine (adım 3) geçilir. Döngü en fazla 3 tur; sonra insan kararı.

**Demoda bilerek konan uyumsuzluklar (örnek uygulamada):** story "6 al 1 bedava" der, kod 5+1 uygular (`doc_vs_code`) · story "min. sipariş 500 TL" der, ayar tablosunda 750 (`doc_vs_data`) · story "kredi limiti aşımı uyarısı" ister, kodda yok (`missing_in_code` → analist "kod hatalı" seçer → bug taslağı) · iki AC birbiriyle çelişir (`internal_contradiction`).

**Ürün fazı notu:** müşteri ortamında veritabanı erişimi okuma replikası üzerinden, tablo/kolon izin listesiyle ve kişisel veri içeren kolonlar hariç tutularak yapılır; müşteri güvenlik ekibinin onayı gerekir (KVKK).

### 8.11 Kontrol Kulesi (adım 11)
- **Girdi:** her koşunun JUnit XML'i (zorunlu) ve allure-results (artefakt linki); Sauce koşu linkleri.
- **Ayrıştırma:** çekirdek, GitHub API'den artefaktı alır, JUnit XML'i `test_result` satırlarına yazar (test adı, durum, süre, retry sayısı, commit, tetik türü: pr/push/nightly/deploy).
- **Ekran:** son koşular (tetik türüyle) · geçme oranı · **flaky** (retry ile geçen veya aynı commit'te sonucu değişen testler) · **karne** (story ve uygulama alanı bazında: case sayısı, otomasyon kapsamı, son sonuç) · **AI katkısı** (kabul oranı, AI + review süresi, maliyet).
- **Demoda:** tek ekran; trend grafikleri ve Power BI sonraki faz.

### 8.12 Bug taslağı ve kaydı (adım 12–14)
- **Mükerrer tespiti:** hata imzası (test adı, hata türü, ilgili sayfa/AC) ile Jira'da açık Bug'lar için JQL metin araması; aday listesi AI tarafından kısa gerekçeyle sıralanır. Karar testçidedir: "yeni kayıt" veya "mevcut kayda bağla".
- **Taslak:** şemalı `bug_draft{summary, steps, expected, actual, environment, evidence[sauce_video, allure, trace], story_key, test_case_key, severity_suggestion}`; "AI-generated" etiketi.
- **Onay ve yayın:** testçi portalda düzeltir ve onaylar; `publish_bug(draft_id)` yalnızca onaylı taslağı, onaylanan içerik hash'iyle yayınlar (idempotent, `external_ref`). Story ve Test issue'larına bağlanır. Faz 2 alanları sonraki fazda.

## 9. API sözleşmesi (özet)

| Yöntem | Yol | Amaç |
|---|---|---|
| POST | `/api/auth/login` | Oturum |
| GET | `/api/requirements?project=` | Story listesi (Rovo) |
| POST | `/api/requirements/{key}/generate` | `RequirementToCases` başlat |
| GET | `/api/cases?requirement=` | Case listesi |
| POST | `/api/cases/{id}/decision` | Onay/düzelt/reddet (Update) |
| POST | `/api/requirements/{key}/review-complete` | Review tamam (Update) |
| GET | `/api/publish/preview?requirement=` | Dry-run gövdesi |
| POST | `/api/publish` | Yayın (Update, imzalı) |
| POST | `/api/code/generate` | `CasesToCode(case_ids)` başlat |
| GET | `/api/runs/{id}` · `/api/failures/{id}` | Koşu ve triage |
| POST | `/api/failures/{id}/fix` | `FailureToFix` başlat |
| GET | `/api/audit?verify=true` | Denetim kaydı + zincir doğrulaması |
| GET | `/api/events` (SSE) | `case.generated`, `agent.step`, `pr.opened`, `ci.status`, `failure.classified` |
| POST | `/api/tokens` | IDE kanalı için kısa ömürlü kapsamlı token |
| MCP | `submit_draft_cases(requirement_key, cases[])` | IDE kanalı: taslakları portala düşürür |
| MCP | `publish_test_cases(case_ids)` | IDE kanalı: onaylıları yayınlar |

---

## 10. Örnek uygulama: Bayi Sipariş Portalı

- **İşlevler:** giriş, katalog, sepet, kampanya ("6 al 1 bedava"), minimum sipariş tutarı uyarısı, sipariş onayı, geçmiş. CCI markası yok.
- **Test edilebilirlik:** tüm etkileşimli elemanlarda `data-testid`, erişilebilir rol ve ad.
- **Page object kütüphanesi:** `LoginPage`, `CatalogPage`, `CartPage`, `OrderPage`; her biri `locators.ts` (saf veri) + `*.page.ts` (eylem ve `expect*` metotları).
- **Test verisi:** `/test/reset` API'si; worker başına kullanıcı; `storageState` ile oturum.
- **Kırılma:** `demo/break-locator` dalında hazır commit; `make break` bu daldan PR açar ve `demo-admin` kimliğiyle ruleset bypass kullanarak merge eder (`gh pr merge --admin`), ardından compose'daki demo uygulamasını `main` HEAD'den yeniden derler (yerel ve CI aynı commit'te). Bypass kullanımı denetim kaydına "demo kırılması" olarak yazılır.
- **Jira:** 4 story (biri kabul kriteri eksik, biri prompt injection içeren güvenlik gösterimi için).

---

## 11. Docker Compose ve yerel ortam

| Servis | İmaj | Port (yalnızca 127.0.0.1) | Healthcheck |
|---|---|---|---|
| `postgres` | `postgres:16` | 5432 | `pg_isready -U tp` |
| `temporal` | `temporalio/temporal` (`server start-dev --ip 0.0.0.0 --db-filename /data/t.db --ui-port 8233`) | 7233, 8233 | `temporal operator cluster health --address 127.0.0.1:7233` |
| `migrate` | çekirdek imajı (tek seferlik) | — | `service_completed_successfully` |
| `core-api` | çekirdek imajı | 8000 | `/health` |
| `core-worker` | çekirdek imajı | — | Temporal bağlantısı |
| `toolchain-worker` | toolchain imajı | — | Temporal bağlantısı |
| `test-runner` | toolchain imajı; ağlar: `demo-net` + `runner-net`; bağımlılıklar imajda önceden kurulu, `uv run --frozen --offline` ve `npm --offline` | — (iç ağ) | Kontrol portu |
| `playwright-mcp` | `mcr.microsoft.com/playwright/mcp` (`--headless --host 0.0.0.0 --port 8931 --allowed-hosts '*' --allowed-origins http://demo-app-web --isolated --caps=testing`), `shm_size: 1gb` | — (iç ağ) | TCP 8931 |
| `review-portal` | nginx | 3000 | HTTP 200 |
| `demo-app-api` | demo API imajı | 8080 | `/health` |
| `demo-app-web` | toolchain imajı, `vite build && vite preview` (CI ile aynı; `preview.allowedHosts` ayarlı) | 8081 | HTTP 200 |

- **Başlatma sırası:** `depends_on: condition: service_healthy`.
- **Kaynak sınırları:** MCP 2 GB, toolchain-worker 3 GB; `node_modules` named volume.
- **Disk:** Docker Desktop disk limiti 64 GB; `make prune`. Gerekli boş alan ~30 GB.
- **Sabitleme:** tüm imajlar digest ile; `.env.example`: `ANTHROPIC_API_KEY`, `JIRA_SITE`, `JIRA_READ_EMAIL/TOKEN`, `JIRA_WRITE_EMAIL/TOKEN`, `GH_APP_ID`, `GH_APP_PRIVATE_KEY`, `BASE_URL`.

**Make hedefleri:** `make up` · `make seed STEP=n` · `make break` · `make reset` · `make export-audit` · `make prune`.

**`make reset`:** önce `make export-audit` (imzalı JSONL; imza anahtarı macOS Keychain'de, `.env`'de değil); sonra DB ve Temporal sıfırlanır; `tp/*` branch'leri silinir, açık PR'lar kapatılır; `main`, `demo-admin` kimliğiyle (ruleset bypass) `demo-baseline` etiketine revert commit ile döner; Jira'da `project = TPD AND labels = tp-demo` kayıtları silinir (yazma kullanıcısında "Delete issues" yetkisi); demo uygulaması yeniden derlenir; demo verisi yüklenir. Her yayında kayıtlara sabit `tp-demo` etiketi de eklenir (JQL'de etiket jokeri yok).

---

## 12. Ölçüm

| Ölçü | Tanım | Brief kapısı |
|---|---|---|
| Case kabul oranı | "Küçük düzeltmeyle" onaylanan / üretilen case. **Küçük düzeltme:** alan bazlı normalize karakter düzenleme mesafesi ≤ 0,15 **ve** beklenen sonuç anlamca değişmemiş (öneri; onay bekliyor, §19) | ≥ %70 |
| Script ilk review başarısı | İnsan review'unda değişiklik istenmeden kabul edilen ve CI'da geçen / üretilen script. **pass@1** (yerel düzeltme turu öncesi) ve **düzeltme sonrası** ayrı raporlanır | ≥ %60 |
| Triage doğruluğu | İnsanla eşleşen sınıf / örneklem; kural ve LLM kararları ayrı | Faz 3 |
| Hazırlık süresi | Story başına AI + review süresi (canlı ölçülür) ile manuel baz değer yan yana. **Baz değer:** İsmail, 4 demo story'si için manuel case hazırlama süresini F0 haftasında ölçer; ortalama demoda sayacın yanında gösterilir | %30–50 |
| AI maliyeti | İş akışı başına token ve USD | Raporlanır |

**Değerlendirme seti (demo):** 5 story, her biri 3 kez (~120 case); ortalama ve sapma. Prompt/kural değişikliğinde canlı modelle koşan değerlendirme işi (replay değil). Brief'teki 30 story'lik insan etiketli set demodan sonradır.

**Etiketleme protokolü:** 1 analist, portal üzerinden kör review (case'in hangi koşudan geldiğini görmez); "beklenen sonuç anlamca değişmedi" yargısını insan verir; tahmini süre ~4 saat. Her story'den en az 1 case için kod üretimi koşar; pass@1 ve düzeltme sonrası sonuç bu setten ölçülür.

---

## 13. Demo güvenilirliği

| Adım | Olası kırılma | Belirti | Geri dönüş |
|---|---|---|---|
| 1 | Rovo bağlantısı | Story listesi boş / 401 | `JiraRestReader`'a geç (konfigürasyon) |
| 2 | Model gecikmesi / şema hatası | Sayaç 60 sn'yi aşar | REPLAY |
| 4 | Jira 429 / yetki | Kısmi yayın | Yeniden dene; seed'li durumdan devam |
| 5 | Eşleme başarısız / süre aşımı | "Eksik metot" veya 120 sn | Golden test + doğrulama kaydı (REPLAY) |
| 6, 8 | CI yavaş / kırmızı | 2 dk'yı aşar | Önceden koşmuş PR'a geç (`make seed STEP=6`) |
| 7 | `make break` başarısız (bypass merge reddi) | `main` CI'ı yeşil kalır | `demo-admin` yetkisini kontrol et; hazır kırmızı koşu kimliğiyle `FailureToFix` başlat |
| 7–8 | Yerel uygulama eski commit'te kalır | Onarımın yerel kontrolü kırmızı | Yerel kontrol her zaman checkout edilen commit'ten `webServer` ile başlar; `make break` compose uygulamasını da yeniden derler |
| 4b | Copilot aracı çağıramaz | MCP 401 / araç yok | Token yenile; yedek kanal Claude Code |

**Prova kontrol listesi:** temiz `make reset` · bot `main`'e push dener → reddedilir · `make break` bypass merge'ü çalışır · test-runner'dan Temporal'a erişim reddedilir · Rovo bağlantısı · REPLAY-MISS olmadan replay · 3 ardışık tam koşu gerçek CI ile.

- **Prova:** 3 ardışık sorunsuz prova, her biri temiz `make reset` sonrası ve gerçek CI ile.
- **Ön ısıtma:** imajlar, tarayıcılar, npm/uv önbellekleri, Actions önbelleği.
- **Yedek:** tam akışın videosu; bulut VM'de bir kez tam koşu (isteğe bağlı).

---

## 14. Güvenlik ve sırlar

| Konu | Uygulama |
|---|---|
| Sırlar | `.env` (git dışı), Docker secrets; dizüstünde FileVault; demo sonrası tüm token'lar iptal edilir |
| Jira | Okuma kullanıcısı (Rovo) ve yazma kullanıcısı, yalnızca demo projesinde |
| GitHub | GitHub App: `contents:write`, `pull_requests:write`, `actions:read`; merge yetkisi kullanılmaz; branch koruması insan onayı ister |
| Anthropic | Ayrı proje anahtarı, harcama limiti; API verisi model eğitiminde kullanılmaz; saklama süresi ve sıfır saklama (ZDR) seçeneği sözleşmeyle teyit edilir |
| Ağ | Tüm portlar `127.0.0.1`; MCP ve toolchain-worker yalnızca iç ağ ve demo uygulamasına erişir |
| Denetim | Zincirli hash, append-only, imzalı dışa aktarım |
| Üretim notu | Ürün ortamında: Azure Key Vault, Entra kimliği, OAuth 2.1 (Rovo), Azure OpenAI veya AB bölgeli model; KVKK m.9 aktarım mekanizması |

---

## 15. Ürünün kendi testleri

| Seviye | Kapsam |
|---|---|
| Birim | Şema, Jira eşleme, idempotency, AST koruması, PII maskeleme ve geri açma, düzeltme ölçüsü, onay hash kontrolü, hash zinciri, şablon enjeksiyonu, beklenen değer kaynağı kontrolü |
| Entegrasyon | Temporal iş akışları (zaman atlamalı ortam), Jira sandbox projesi, GitHub test repo |
| Uçtan uca | REPLAY ile tam demo akışı (model çağrısı yok) |
| Değerlendirme | §12 değerlendirme seti, canlı model |
| Güvenlik | Prompt injection story'si, izin dışı origin denemesi, onay atlatma denemesi |

---

## 16. Riskler

| Risk | Olasılık | Etki | Önlem |
|---|---|---|---|
| Ücretsiz GitHub planında branch koruması yok | Kesin | Yüksek | GitHub Team planı (§18). B planı: kod ve veri sentetik olduğu için repo public yapılabilir (ücretsiz ruleset); ancak ürün kodu IP'mizdir, şirket kararı gerekir |
| Kritik yol tek kişide | Orta | Yüksek | F1 ilk günden paralel (Hakan); İsmail F2a'da |
| Sauce Labs / Sauce Connect demoda aksar | Orta | Orta | Yerel CI job'u yedek ve zorunlu; Sauce job'u zorunlu değil; önceki yeşil Sauce koşusunun linki hazır |
| Sauce kimliği geç gelir | Orta | Düşük | Demo yerel CI ile yapılabilir; Sauce eklentisi bağımsız |
| Rovo MCP ücretsiz plan / API token sorunu | Orta | Orta | Bugün test; B planı |
| Kod üretim adımı demo süresini aşar | Orta | Yüksek | ≤5 adımlı case, 120 sn bütçe, REPLAY |
| Eşleme başarısız | Orta | Yüksek | Story'ler page object kapsamına göre seçilir |
| CI yavaş | Orta | Orta | Container job, önbellek, tek tarayıcı |
| Disk yetersiz | Yüksek | Yüksek | Kurulum öncesi ~30 GB |
| Docker Desktop lisansı | Düşük | Orta | Colima |

---

## 17. Sahipler ve teslimat sırası

Demo değerinin en hızlı görüneceği sıra: önce **case akışı** (CCI'ın ilk sorusu), otomasyon hattı **ilk günden paralel**.

| # | Özellik | Kabul kriteri | Sahip (öneri) | Tahmin | Paralel hat |
|---|---|---|---|---|---|
| F0 | Repo, Spec Kit, constitution, Compose iskeleti, `make up` | Tüm servisler sağlıklı | Gökhan | 1 gün | A |
| F1 | Örnek uygulama + page object kütüphanesi + toolchain imajı + CI (Semgrep) + bot + ruleset | Elle yazılmış 1 test PR'da yeşil, ≤2 dk | Hakan | 3 gün | B (1. günden) |
| F2a | Çekirdek: veri modeli, Temporal, kimlik (Gökhan); model geçidi, maskeleme, replay (İsmail) | Kayıtlı ve maskeli 1 uçtan uca çağrı | Gökhan + İsmail | 3 gün | A |
| F3 | Rovo okuma + case üretimi + review portal + `publish_test_cases` + `submit_draft_cases` | Story → onaylı case'ler Jira'da; dry-run, idempotent, hash kontrollü; Copilot kanalı çalışır | Gökhan | 3 gün | A |
| **Demo-A** | **Ara demo: story → case → onay → Jira; Copilot kanalı; AI + review süresi manuel baz değerle yan yana** | Cengizhan Bey'e gösterim | — | **≤ 7 iş günü (sabit)** | — |
| F4 | Toolchain-worker + doğrulama ajanı + şablonla kod + PR | Onaylı case → PR → CI yeşil | Gökhan + Hakan | 4 gün | A+B |
| F5 | Triage kuralları + locator onarımı + AST koruması | Kırılma → onarım PR'ı → etkilenen tüm testler yeşil | İsmail + Hakan | 3 gün | B |
| F6 | Seed, REPLAY, prova, video; zaman kalırsa güvenlik gösterimi | 3 ardışık sorunsuz prova | Ekip | 2 gün | — |

### 1 haftalık demo planı (karar §0-1, §0-12)

**Tüm 14 adım canlı (karar §0-19).** Üç hat paralel; Claude Code her hatta kod üretiminde kullanılır.

| Gün | Hat A — Gökhan (çekirdek, Jira, portal) | Hat B — Hakan (uygulama, test, CI, Sauce) | Hat C — İsmail (AI) |
|---|---|---|---|
| 1 | F0: repo, Compose, `make up`; Postgres şeması, durum makinesi iskeleti | F1: örnek uygulama + page object'ler + iki kırılma bayrağı; **uygulama veritabanı (Postgres) + salt okuma rolü + bilerek konan doküman uyumsuzlukları** | Model geçidi (Claude, şema doğrulama, kayıt, maskeleme) |
| 2 | Rovo okuma; Jira yazma (yorum, etiket, Test issue, Bug); PO etiketi sorgulama | F1: toolchain imajı, CI (PR, push, gece, deploy tetikleri), ruleset; JUnit + Allure reporter'ları | Ön inceleme (adım 2) ve case üretimi (adım 4) prompt/şemaları; **tutarlılık denetimi ajanı** (GitHub MCP read-only + `db_query`) **ve kanıt doğrulayıcı** |
| 3 | Portal: story, ön inceleme + **tutarlılık bulguları ekranı (karar, önerilen metin farkı) ve Jira açıklama/AC güncelleme**, case review, yayın önizlemesi; `submit_draft_cases` + `publish_test_cases` (Claude Code kanalı); **serbest metin gereksinim girişi** (portalda PO teyidi) | Sauce Labs job'u + Sauce Connect; elle yazılmış test PR'da yeşil; **erişilebilirlik denetimi** (`@axe-core/playwright`, sonuç JUnit'e) | Kod üretimi: Playwright MCP doğrulama + eşleme + şablon (adım 5) |
| 4 | Sonuç alma (JUnit XML) + **Kontrol Kulesi** ekranı (erişilebilirlik ihlalleri dahil); "kırarak doğrula" ve "deploy" düğmeleri; **test yönetimi adaptör arayüzü + Xray Cloud arka ucu** | Kod taslağı PR akışı uçtan uca; kasıtlı kırma (a) | Triage: kurallar + JQL mükerrer + bug taslağı; locator onarımı + AST koruması |
| 5 | Testçi kayıt açma ekranı + `publish_bug`; **uçtan uca prova ×2** | Prova; hazır PR'lar ve Sauce koşu linkleri (yedek) | Prova; REPLAY kayıtları (adım 4–5); yedek video |

**Günlük kesme kuralı:** her akşam 14 adımın durumu işaretlenir; bir adım ertesi gün öğlene kadar çalışmıyorsa o adım için yedeğe geçilir (hazır PR, REPLAY, önceden koşmuş Sauce linki) ve ekip sıradaki adıma geçer. Canlı gösterilemeyen adım demoda yedeğiyle gösterilir ve bu açıkça söylenir.
**Risk:** Plan çok sıkı (≈ 3 haftalık işin 1 haftaya sıkıştırılmış hali); başarı, üç hattın 1. günden paralel başlamasına ve Jira sitesi + Sauce kimliğinin 1. gün hazır olmasına bağlı.

**Kural:** Demo-A ≤ 7 iş günü sabittir; bu tarihi tehdit eden her ek kapsam ertelenir. **İlk kesilecekler (sırasıyla):** Confluence özeti · `ac_missing` soru akışı (yalnızca uyarı kalır) · REPLAY'in Demo-A'daki kapsamı.
**Azure eşdeğerlik koşusu (sapma 1 koşulu):** sahibi İsmail; Azure OpenAI erişimi sağlandıktan sonra, tam demo provasından önce değerlendirme seti her iki sağlayıcıda koşar. **Tam demo:** paralel hatlarla ~3 hafta. Tahminler ve sahipler ekip tarafından teyit edilecek.

---

## 18. Başlamadan önce gerekenler

| # | Ne | Kimden | Not |
|---|---|---|---|
| 1 | ~30 GB disk | Gökhan | F0 öncesi |
| 2 | Jira Cloud demo sitesi + Rovo MCP API token (admin etkinleştirme) | **Recep Bey** | İlk test edilecek |
| 3 | Anthropic API anahtarı (harcama limitli) | Gökhan | |
| 4 | ~~GitHub Team planı~~ → **Repo public** (karar §0-8) | Gökhan | Ruleset ve GHCR ücretsiz; Team planı demodan sonra, repo tekrar private yapılır |
| 5 | GitHub App (bot) + `demo-admin` insan hesabı (ruleset bypass) | Gökhan | Bot bypass listesinde yok |
| 6 | ~~GitHub Copilot lisansı~~ | — | Demo için gerekmez; 4b Claude Code ile (karar §0-5) |
| 6a | Jira yazma kullanıcısında "Delete issues" yetkisi (sıfırlama) | Gökhan | |
| 6d | **Xray Cloud deneme sürümü** demo Jira sitesine kurulu + Xray API kimliği (client id/secret) | Recep Bey | 30 günlük ücretsiz deneme; 2. gün hazır olmalı |
| 6c | **Sauce Labs kimliği** (kullanıcı adı + access key, Antrek hesabı) | Ekip | Geldiğinde GitHub Actions secret olarak eklenir; Playwright'ın hesapta açık olduğu ve sürüm uyumu teyit edilir |
| 6b | Manuel case hazırlama baz ölçümü (4 story) | İsmail | F0 haftasında |
| 7 | Docker Desktop lisans durumu | Şirket | |
| 8 | CCI test ortamındaki bir web uygulamasına erişim talebi | Cengizhan Bey | Demodan sonraki taşıma için |
| 9 | §19 sapmalarının ve ölçü tanımının onayı | Cengizhan Bey | |

---

## 19. Brief'ten sapmalar ve onay bekleyen kararlar

> **2026-10-30:** Aşağıdaki sapmaların tamamı ve "küçük düzeltme" tanımı onaylandı (§0). "Durum" sütunundaki koşullar demodan sonra izlenir.

| # | Brief | Demo kararı | Gerekçe | Durum |
|---|---|---|---|---|
| 1 | Model: Azure OpenAI | **Claude**, görev başına sabit sürüm | Kod ve araç kullanımında kalite, yapılandırılmış çıktı desteği, geliştirme hızı; model geçidi soyut | Koşullu kabul (ürün sahibi): demo öncesi `AzureOpenAIProvider` ile bir koşu; CCI'a açıkça söylenir; Claude'un Azure üzerindeki erişilebilirliği ve veri bölgesi teyit edilir |
| 2 | Gerçek CCI web uygulaması | **Kendi örnek uygulamamız** | Hemen başlanabilir | Koşullu kabul: CCI test ortamı erişim talebi şimdi açılır; demoda "sizin uygulamanıza taşıma" slaydı |
| 3 | Azure AI Search | Demo için yok | Bilgi tabanı brief gereği page object'lerle sınırlı | Kabul |
| 4 | Azure Container Apps | Yerel Docker Desktop | Demo bu Mac'te | Koşullu kabul: imajlar ACA'ya kurulabilir kalır |
| 5 | "Agent Probe ile ortak çekirdek" | **Demo tamamen bağımsız**; ortak çekirdek kararı demodan sonra ADR ile ürün sahibinde | — | Demo için kabul |
| 6 | Rovo MCP | Rovo; sorun olursa `JiraRestReader` | Ücretsiz planda teyit yok | Kabul |
| 7 | Rovo OAuth 2.1 | Demo: API token (Basic) | Arka plan servisi için | Bilgi |
| 8 | Key Vault | Demo: `.env` + Docker secrets | Yerel demo | Bilgi |
| 9 | Test yönetimi Jira **veya** Octane | **Jira** | Demo hızı; aynı `publish_test_cases` arayüzünün Octane arka ucu demodan sonra | Demoda sözlü belirtilir |
| 10 | Playwright Planner/Generator/Healer hazır | Ürün hattında kendi doğrulama + koruma katmanımız; Playwright ajanları ürünsüz kanalda | Kural 4 ve 6 ile uyum | Bilgi |
| 11 | "Küçük düzeltme" tanımı | Normalize düzenleme mesafesi ≤ 0,15 + beklenen sonuç değişmemiş (insan yargısı) | Adım sayısı oranı küçük case'lerde kendini cezalandırıyor | **Onay bekliyor** |
| 13 | Onay koruması | Oturumlu kullanıcı + içerik hash'i (HMAC imzası yok) | Demo için yeterli ve sade; kriptografik imza ürün fazında Entra kimliğiyle | Bilgi |
| 14 | İş akışı motoru: Temporal | **Demoda Postgres durum makinesi + basit worker** (§2.1); Temporal demodan sonra | 1 haftada 14 adımın canlı yetişmesi; kapı kuralları aynı | Onaylandı (§0-20) |
| 12 | `test_maintenance` alt türü | Dört kök neden sınıfının dışında, locator onarım yolu | Brief iki ayrı çıktı istiyor | Kabul |

---

## 20. Demodan sonra (kapsam dışı, kayıtlı)

Teams/Copilot Studio kanalı · Octane arka ucu · mobil (Appium MCP) · masaüstü (FlaUI-MCP) · API (OpenAPI) · 30 story'lik değerlendirme seti · Azure ortamı (ACA, Key Vault, Entra) · Azure AI Search ile framework indeksleyici · regresyon seçimi (öneri modu) · Power BI · Temporal (demodaki durum makinesinin yerine) · Jira bug Faz 2 alanları.

### 20.1 Rakip analizinden alınanlar (Testinium TheRafi, 2026-10-30)

Kaynak: therafi.ai ve testinium.com pazarlama sayfaları (teknik doküman yok; iddialar doğrulanmamış).

| Fikir | Kapsam | Uygulama | Gerekçe |
|---|---|---|---|
| **Erişilebilirlik denetimi** (RafiAccess karşılığı) | **Demo** (karar §0-21) | `@axe-core/playwright` ile onaylı testlerin ziyaret ettiği sayfalarda WCAG 2.2 AA kontrolü; CI'da AI'sız; ihlaller JUnit/Allure'a ve Kontrol Kulesi'ne; kritik ihlal için aynı bug taslağı akışı | Rakipte var; RFI kapsam sorusu; düşük maliyet |
| **Serbest metinle gereksinim girişi** | **Demo** (karar §0-21) | Portalda Jira'sız gereksinim kutusu; aynı ön inceleme → (PO teyidi portalda) → case akışı; sonradan Jira'ya bağlanabilir | Brief'te "story seçer ya da gereksinim verir"; Jira'sız ekipler ve hızlı deneme |
| **Çoklu test yönetimi arka ucu** | **Demo: Xray** (canlı) · Ürün: TestRail, Zephyr Scale (karar §0-21) | `publish_test_cases` için adaptör arayüzü (`TestManagementBackend`: `upsert_case`, `link_to_story`, `find_by_key`); demoda Jira (yerel) ve **Xray Cloud** (GraphQL API ile Test issue + adımlar) arka uçları; hedef proje ayarıyla seçilir | Başka müşterilere satış; demoda "aynı onaylı case, farklı test yönetimi aracı" gösterimi |

**Bilerek alınmayanlar:** koşu sırasında testi değiştiren "gerçek zamanlı AI self-healing" (Constitution II ve VI ile çelişir; gerçek hatayı gizleme riski) ve kapalı, kodsuz test formatı (taşınabilirlik ilkesiyle çelişir). Bu iki nokta teklifte ayrıştırıcı olarak kullanılır: **testler müşterinin repo'sunda, açık kaynak framework'te gerçek kod; koşuda AI yok; her değişiklik insan onaylı.**

---

## 21. Spec Kit planı

1. `specify init . --integration claude` (repo kökünde).
2. `/speckit-constitution` ← §3 (10 kural) + §5 (tehdit kontrolleri) + "AI yalnızca core-worker'da" + "Postgres tek doğruluk kaynağı".
3. Özellikler sırasıyla: `001-foundation` (F0) → `002-core` (F2a) → `003-requirement-to-cases` (F3) → `004-demo-app-and-ci` (F1) → `005-cases-to-code` (F4) → `006-failure-to-fix` (F5) → `007-demo-readiness` (F6). Her biri `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement` → `/speckit-converge`.
