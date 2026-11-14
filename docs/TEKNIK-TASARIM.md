# AI Automation Testing (Test Engineering Suite) — Demo Teknik Tasarımı

> **Sürüm:** v1.9 · 2026-11-11 · **Hazırlayan:** Gökhan Sipahi · **Gözden geçirecek:** Cengizhan Bey, Hakan, İsmail
> **Bağlayıcı kaynak:** "AI Automation Testing — Geliştirme Ekibi için Ürün Brief'i" (Cengizhan Bey, 30.10.2026). Bu doküman o brief'in **demo dilimini** tarif eder. Brief'ten sapmalar §19'dadır.
> **Spec Kit nedir:** GitHub'ın açık kaynak "spesifikasyon güdümlü geliştirme" aracı. Bu doküman önce projenin değişmez kurallarına (constitution, §3), sonra her kilometre taşı için ayrı spec → plan → görev → uygulama döngüsüne (§21) girdi olur.
>
> **v1.8 → v1.9 (2026-11-11, 012 rol ve yetki modeli v2, ADR-0002):** 8 rol (`admin` Sistem Yöneticisi, `auditor` Denetçi, `analyst` Analist, `po` PO, `tester` Testçi, `engineer` Automation Engineer, `developer` Developer, `viewer` Görüntüleyici); `presenter` kalktı (→ `admin`). Her uç bir izin anahtarı ister (`tp_core/auth/yetki.py`, MIMARI-SOZLESME §5); red 403 `yetki_yok` + `authz.denied`. Case kararı ve yayını Testçi'ye geçti, son onay Analist'te (yeni `ready` durumu); PO onayı Jira story'sinde yalnız Jira etiketiyle (portal ucu 410 `po_onayi_jira`), serbest metin gereksinimde portalda; CI tetik Automation Engineer; demo kontrolleri `TP_DEMO_MODE=1` ile Sistem Yöneticisi/Automation Engineer. §2, §2.1, §7, §8.10, §8.13, §8.14 güncellendi. Spec `specs/012-rol-yetki/ANALIZ.md`.
>
> **v1.7 → v1.8 (2026-11-11, specs/011-uretim-dili):** **Üretim dili** platformdan ayrı bir boyut oldu (`ts | java | csharp | python`; §7 `script`, §8.4–§8.7). Web için Java (Playwright for Java + TestNG, `demo-app/e2e-java`) tam hattır; C# ve Python **doğrulanmamış** üretilir (PR/merge yok, durum `unverified`). Constitution v2.1.0 (MINOR): İlke IV/V/VI dilden bağımsız; doğrulanmamış diller PR'a ve merge'e giremez. İnceleme turu 1 kararları K-T1..K-T9 (`specs/011-uretim-dili/inceleme-tur1.md`) bu sürüme işlendi.
>
> **v1.6 → v1.7 (2026-11-10, ADR-0001 onaylandı):** **AI Probe ortak kimliği** (§8.14; §3 satır 12, §8.10, §9, §14 güncellendi). Constitution v2.0.0 (MAJOR): İlke XII — AP ile kod/ekran/DB paylaşımı yok, ortak kimliğe yalnızca belgelenmiş HTTP kimlik API'si (devir + oturum kontrolü) ile bağlanılır, Firebase SDK'sı TP'ye girmez; İlke VII — on-prem `TP_AUTH_MODE=local` varsayılan. Spec `specs/010-aiprobe-sso/`.
>
> **v1.5 → v1.6 (2026-11-03, ürün sahibi kararları K1–K10):** portal içi **salt okuma asistan** ve kural tabanlı **Öneri** düğmesi eklendi (§8.13; §4, §7, §8.8, §9 güncellendi). Constitution v1.3.0: İlke II'ye "salt okuma bilgi ve yönlendirme asistanı; eylem yok; çıktısı karar dayanağı değildir". Ayrıntılı plan `docs/AI-ASISTAN-PLANI.md` v6, spec `specs/008-ai-asistan/`.
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
| 1 | Demo tarihi | ~~1 hafta içinde~~ → **~3 hafta** (karar 24) | Teslimat §17'deki "1 haftalık demo planı"na göre |
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
| 19 | Tüm akış canlı | **Tüm 14 adım canlı**, ince sürümlerle | §2.1 |
| 21 | Rakip analizinden (TheRafi) | **Demoya:** erişilebilirlik denetimi, serbest metin gereksinim girişi, Xray arka ucu. **Sonra:** TestRail, Zephyr. **Gerek yok:** tasarım dosyasından case üretimi, kurulum seçenekleri | §2.1, §17, §18, §20.1 |
| 22 | Doküman tutarlılık denetimi | **Sistem, test edilen uygulamanın GitHub reposuna ve veritabanına salt okuma erişimle analistin dokümanını (Jira story açıklaması + AC) iç tutarlılık, kod ve veri açısından denetler**; AI düzeltme önerir, analist onaylar, sistem Jira'yı günceller; kod hatalıysa bug taslağı; engelleyici bulgu kalmayınca "son hal" → PO teyidi | §2 adım 2, §8.2b, §17 |
| 23 | Kurulum ve veri güvenliği | **Uygulama on-prem çalışacak; veri dışarı çıkmayacak.** Demoda güvenlik sertleştirmesi öncelik değil (PII maskeleme, denetim zinciri doğrulama, tehdit gösterimi ürün fazına). Salt okuma erişim ve insan kapıları kalır. **İstisna:** model çağrıları — ürün fazında model müşteri ortamında olmalı (müşterinin bulut hesabında Claude / tenant'ta Azure OpenAI / on-prem açık model); demo sentetik veriyle Claude API | §2.1, Constitution VII |
| 24 | Demo süresi | **~3 hafta**; haftalık ara demolar (Demo-A, Demo-B, tam demo) | §17 3 haftalık plan |
| 25 | Sadeleştirmeler | **Kalıyor** (Postgres durum makinesi; Temporal ürün fazında) | §2.1 |
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
| 4 | **Test case** — AI iskelet, Testçi kararı, Analist onayı | AI + İnsan | AI, Testçi, Analist | Şemalı pozitif/negatif/sınır case'ler (AC ve PO cevaplarına bağlı); Testçi üretir ve kabul/düzelt/reddet kararı verir (`ready`); Analist son onayı verir ya da gerekçeyle geri gönderir; onaylıları Testçi `publish_test_cases` ile Jira'ya yayınlar (önizleme → yayın). **Claude kanalı:** Claude Code taslak üretir → `submit_draft_cases` → aynı Testçi kararı ve Analist onayı (token'ı Testçi alır) | Case kartları, sayaç, kabul oranı; Jira'da Test issue'ları |
| 5 | **Kod taslağı** — AI, ayrı dalda PR | AI | Automation Engineer + AI | Playwright MCP ile adımlar uygulamada doğrulanır → page object eşlemesi → şablonla TypeScript test → yerel kontrol → bot ayrı dalda PR açar | Adım ekran görüntüleri; PR linki |
| 6 | **Review** — insan + kasıtlı kırma | İnsan | Automation Engineer | Automation Engineer kodu inceler. **Kasıtlı kırma (a), hata yakalama kanıtı:** portaldaki "kırarak doğrula" düğmesi uygulamayı `BREAK_CAMPAIGN` bayrağıyla açar ve testi koşturur; test **kırmızı** olmalı (değilse PR "zayıf test" işaretlenir). Sonra bayraksız yeşil. Ardından merge | Yeşil → kırmızı → yeşil; "test hata yakalıyor ✓" |
| 7 | **Kurum git'i** — korumalı ana dal | Sistem | — | Ruleset: doğrudan push yok, CI + 1 insan onayı ile merge | Merge edilmiş PR |
| 8 | **CI runner** — gece ve deploy | Sistem | — | Workflow tetikleri: PR, `main` push, **gece** (çekirdek `TP_CI_NIGHTLY_SAAT`'te `workflow_dispatch` `tetik=nightly`; GitHub `schedule` cron'u kullanılmaz), **deploy** (`repository_dispatch`, demoda Automation Engineer portal düğmesiyle elle) | Tetiklenen koşu |
| 9 | **Cihaz ve API** — Sauce, QA ortamı | Sistem | — | Onaylı testler **Sauce Labs** bulut tarayıcısında (Sauce Connect) ve yerel yedek job'da koşar; uygulama QA ortamı olarak CI'da ayağa kalkar | Sauce video linki |
| 10 | **Sonuçlar** — JUnit XML, Allure | Sistem | — | Playwright reporter'ları: `junit` (JUnit XML), `allure-playwright` (allure-results), JSON; artefakt olarak saklanır ve çekirdek tarafından alınır | Allure raporu linki |
| 11 | **Kontrol Kulesi** — kalite, flaky, karne | Sistem | — | Çekirdek JUnit XML'i ayrıştırıp veritabanına yazar; portalda tek ekran: son koşular, geçme oranı, flaky testler (aynı commit'te değişen sonuç / retry ile geçen), uygulama/story karnesi, AI katkısı (kabul oranı, süre) | Kontrol Kulesi ekranı |
| 12 | **Triage** — AI: mükerrer, taslak | AI | AI | Başarısız testler: önce deterministik kurallar (ortam / veri / gerçek defect / flaky; locator → bakım). Gerçek defect için Jira'da **benzer açık bug araması** (mükerrer tespiti: JQL metin araması + AI benzerlik yorumu) ve **bug taslağı** (adımlar, beklenen/gerçekleşen, kanıt linkleri: Sauce video, Allure). Locator kırılmasında onarım PR'ı önerisi | Sınıf, eşleşen sinyaller, "olası mükerrer: XYZ-12" |
| 13 | **Kaydı açar** — testçi, onaylı taslak | İnsan | Testçi | Testçi taslağı inceler, düzeltir ve onaylar (ya da mükerrerse mevcut kayda bağlar); onaysız kayıt açılmaz | Taslak → onay |
| 14 | **Jira** — hata (+ Faz 2 alanları) | Sistem | — | `publish_bug` ile Jira'da Bug açılır (temel alanlar; Faz 2 alanları sonra), story ve teste bağlanır | Jira'da yeni Bug |

**Demoda iki kırılma senaryosu** (karar §0-16):
- **Hata yakalama (adım 6 ve 12–14):** `BREAK_CAMPAIGN` ile kampanya indirimi yanlış hesaplanır → test kırmızı → triage "gerçek defect" → mükerrer kontrolü → taslak → testçi onayı → Jira'da Bug.
- **Locator kırılması (adım 12, bakım yolu):** `make break` (`add-to-cart` → `cart-add`) → triage "test bakımı/locator" → yalnızca locator'ı değiştiren onarım PR'ı → Automation Engineer onayı → yeşil.

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
| PII maskeleme | Her model çağrısında | Demoda kapalı (sentetik veri, karar §0-23); geçitte kanca hazır, müşteri verisinde zorunlu |
| Güvenlik gösterimi | Opsiyonel adım | Kapsam dışı |
| Erişilebilirlik denetimi | WCAG 2.2 AA, CI'da her koşuda (§20.1) | `@axe-core/playwright` ile demo story'sinin sayfalarında kontrol; ihlal sayısı Kontrol Kulesi'nde; kritik ihlal için bug taslağı |
| Serbest metin gereksinim | Ürün özelliği (§20.1) | Portalda gereksinim kutusu; PO teyidi Jira yerine portalda (PO rolü, izin `requirement.po_approve_free_text`, içerik hash'i kontrolü; yalnız `kaynak == free_text`); sonra aynı akış. Jira story'sinde portal PO onayı 410 `po_onayi_jira` |
| Test yönetimi arka uçları | Jira, Xray, TestRail, Zephyr, Octane | Jira + **Xray Cloud (deneme sürümü)**; TestRail ve Zephyr sonra |

---

## 3. Değişmez kurallar (constitution) ve teknik karşılıkları

| # | Kural (brief) | Teknik karşılık |
|---|---|---|
| 1 | AI üretir, insan onaylar | Onayın doğruluk kaynağı Postgres: core-api oturumdaki kullanıcıyla `review` satırını (`kullanıcı + nesne_id + içerik_hash`) yazar, ardından Temporal **Update** gönderir; iş akışının Update doğrulayıcısı Postgres'te eşleşen satır yoksa Update'i reddeder (Docker ağı içinden sahte Update etkisizdir). DB yazma kimliği yalnızca core-api ve core-worker'da. Yayın ve PR adımları güncel hash'i onaylanan hash ile karşılaştırır (onay sonrası değişiklik → red). Temporal gRPC ve UI yalnızca host'un `127.0.0.1`'inde; portal dışında onay yolu yok |
| 2 | CI'da AI yok | CI'da model anahtarı, MCP sunucusu ve ajan bağımlılığı yok; workflow `permissions: contents: read`; `pull_request_target` kullanılmaz |
| 3 | Yapılandırılmış çıktı | Claude'un yerel yapılandırılmış çıktı / strict tool kullanımı; büyük şemalı amaçlarda (case üretimi, tasarım modeli, derinleştirme; `params: { output: prompt }`) şema sistem mesajında gönderilir çünkü API'nin yapılandırılmış çıktı dilbilgisi sınırını aşar, çıktı geçitte tam şemayla doğrulanır; Pydantic doğrulaması; şema hatasında hata mesajıyla en fazla 2 yeniden istek; şemaya uyan çıktının deterministik kural ihlalinde (`output_check`, `TP_KURAL_YENIDEN_ISTEME`, varsayılan açık) aynı döngüde düzeltme isteği, kalan ihlal uyarı/onay engeli (§8.8) |
| 4 | Kütüphaneye bağlı kod | Kod modelden değil, doğrulanmış adım→page object eşlemesinden **şablonla** üretilir (her dilde; §8.4 "Üretim dili"); tam hat dillerinde PR'da ve CI'da zorunlu kapı: TypeScript ESLint (`--no-inline-config`) + `tsc --strict`, Java pom kilidi + `java-araclar guard` + derleme. Doğrulanmamış diller (C#, Python) forge'a yazılmaz, PR açılmaz |
| 5 | Uygulamayı gerçekten gör | Her adım Playwright MCP (web) / app-mcp (uygulama) snapshot'ında doğrulanmadan eşleme kabul edilmez — üretim dili ne olursa olsun; `--caps=vision` kapalı |
| 6 | Onarım yalnızca locator | `locators.ts` (TS) / `ekranlar/Kimlikler.java` (Java) saf veri; AST koruması (`ast-guard` / `java-araclar`): anahtar kümesi ve niyet değişmez, yalnızca ilgili `testId` değeri değişir; aynı kontrol CI'da zorunlu check |
| 7 | Veri müşteride kalır | Model geçidinde ters çevrilebilir PII maskeleme (§8.9); demo yalnızca sentetik veri |
| 8 | Her şey kayıt altında | `ai_call`, `tool_call`, `audit_event` append-only ve `prev_hash` zinciriyle; zincirin son hash'i her yayında Jira yorumuna ve her PR açıklamasına yazılarak dışarıya sabitlenir; her AI çağrısı onaylayan kişiye iş akışı üzerinden bağlı |
| 9 | Ürün opsiyonel kalabilmeli | `rules/` altındaki prompt, kural ve şemalardan `CLAUDE.md` ve `.github/copilot-instructions.md` üretilir; `publish_test_cases` MCP aracı ürünsüz kanaldan da kullanılabilir |
| 10 | Her çıktı ölçülür | §12 ölçüm tanımları; her karar ve düzeltme kaydedilir |
| 12 | Bağımsız ürün, sözleşmeli kimlik (ADR-0001) | AP ile ortak kod/ekran/DB yok. `TP_AUTH_MODE=local` (varsayılan, on-prem): argon2 + `tp_session`, dış çağrı yok. `aiprobe`/`both`: yalnızca iki sunucu çağrısı (`/v1/handoff/redeem`, `/v1/session/check`), TP'nin servis hesabının Google ID token'ıyla; Firebase SDK'sı yok; dış kimlik `kimlik_bagi` ile TP rol hesaplarına bağlanır, yetki `app_user.rol` ile (§8.14) |

---

## 4. Mimari

```
            Analist · Automation Engineer (tarayıcı) IDE: GitHub Copilot / Claude Code
                       │                                         │ MCP
          Review Portal (React, nginx) ── REST + SSE ──┐         │
                                                       ▼         ▼
┌──────────────────────── Çekirdek (Python 3.12, FastAPI) ─────────────────────────────────┐
│  core-api: REST, SSE, kimlik, onay Update'leri, publish_test_cases MCP sunucusu,          │
│      asistan mesaj/öneri uçları (modelsiz; model kipini ve anahtarı bilmez)               │
│  core-worker (Temporal, kuyruk: tp-core): iş akışları, model geçidi, ajan döngüsü,        │
│      Rovo okuma, Jira yazma, GitHub, triage, PII maskeleme (kütüphane),                   │
│      asistan şeridi (salt okuma araçlar, ayrı iş parçacıkları, kalp atışı)                │
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
- **Portal asistanı salt okumadır (§8.13, constitution v1.3.0 İlke II):** eylem aracı yok; çıktısı karar dayanağı değildir ve hiçbir karar alanına girmez. core-api asistanın model durumunu worker'ın yazdığı `asistan_durum` satırından okur.
- **Okuma MCP ile, yazma kendi aracımızla** (brief).
- **Mobil/masaüstü (009, `specs/009-mobil-masaustu/plan.md`):** aynı hat `platform ∈ {web, android, ios, windows}` boyutuyla çalışır. Uygulama platformlarında doğrulama ajanının aracı kendi MCP sunucumuz **app-mcp**'dir (Appium istemcisi, `mobil` compose profili); Appium hostta koşar, test-runner'ın ona tek çıkışı **appium-gw**'dir. Ayrıntı: [MOBIL-MASAUSTU.md](MOBIL-MASAUSTU.md).

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
| Mobil/masaüstü otomasyonu (009) | Appium 3 (`uiautomator2`, `xcuitest`, `novawindows`; sürümler `tools/appium` kilidinde ve iş akışında sabit); ajan aracı `toolchain/app-mcp` (Node + TypeScript, kapalı araç listesi) |
| Üretilen kod | TypeScript + `@playwright/test` + `eslint-plugin-playwright` |
| Sembol tablosu | `ts-morph` (toolchain-worker) |
| Üretilen kod — uygulama (009) | Java 17 + Appium java-client + TestNG (Maven, `demo-app/e2e-app`); şablon `rules/templates/appium_testng.java.j2` |
| Java araçları (009) | `toolchain/java-araclar` (JavaParser): `symbols` (TS sembol tablosuyla aynı şema), `guard` (üretilen test AST koruması), `locators` (onarımda yalnız kimlik değeri) |
| Portal | React + Vite + TypeScript, build edilip nginx ile sunulur; SSE |
| Kod ve CI | GitHub, GitHub Actions, GitHub App (bot) |
| Örnek uygulama | FastAPI API + React web (nginx) |

**Tek sürüm kaynağı:** `.playwright-version` dosyası; MCP imajı, toolchain imajı, CI container imajı ve `@playwright/test` aynı Playwright sürümüne sabitlenir.

**Playwright Test Agents (Planner/Generator/Healer) neden demo hattında değil:** Generator serbest TypeScript ve ham locator yazar (kural 4 ile çelişir); Healer assertion değiştirebilir ve `test.fixme` ekleyebilir (kural 6 ile çelişir). Bu ajanlar **ürünsüz kanal** (kural 9) için `rules/` ile yapılandırılarak sunulur; ürün hattında kendi doğrulama döngümüz ve koruma katmanımız kullanılır. Karar demodan sonra ADR ile yeniden değerlendirilir.

---

## 7. Veri modeli

| Tablo | Alanlar (özet) |
|---|---|
| `app_user` | id, ad, rol (`admin`/`auditor`/`analyst`/`po`/`tester`/`engineer`/`developer`/`viewer`; 012 göçü `presenter` → `admin`), parola hash'i |
| `requirement` | id, jira_key, başlık, kabul kriterleri, kaynak_hash, çekim_zamanı, `ac_missing` |
| `test_case` | id (deterministik: `uuid5(jira_key + case_sıra_no + üretim_no)`), requirement_id, kanal (`portal`/`ide`), sürüm, tür, risk, ön koşul, adımlar, beklenen sonuç, AC referansları, durum, `ai_generated`, içerik_hash, onaylanan_hash |
| `case_uretim` | id, requirement_id, uretim_no (gereksinim içinde tekil), kanal (`portal`/`ide`), tur (`uretim`/`negatif`/`teknik`), ai_call_id, `ozet` (JSONB: üretimin case dışındaki üst düzey listeleri, aşağıda), oluşturma — migrasyon 0021 (specs/011 §4.3) |
| `tasarim_modeli` | id, requirement_id, sürüm, içerik (JSONB), içerik_hash, onaylanan_hash, durum (`draft`/`approved`/`rejected`/`superseded`), ai_call_id, üretim_modu — iki turlu üretimin onaylı test tasarım modeli (F3, 0022) |
| `case_set_review` · `case_set_audit` | P8 review (uretim_no, set_hash, skor, içerik) ve P9 denetim kararı (set_hash, karar `KABUL`/`DUZELTME_GEREKLI`/`ENGELLE`, kaynak `tp-gecit`/`agent-probe`, talep_no) (F2/F5, 0023) |
| `requirement.uretim_secenekleri` | Analistin son üretim seçimi (kip, platformlar, test seviyesi, benimsenen standartlar, kapsam dışı); sonraki üretimde varsayılan (K5, 0024) |
| `ajan_urunu_baglantisi` · `ajan_testi_talebi` · `asistan_denetim` | AI ajan ürünü bağlantısı ve Agent Probe test talebi (F6); asistan sorusu/cevabı puanı (yon, puan, kategoriler, karar `gec`/`uyar`/`engelle`) (F7, 0025) |
| `review` | id, test_case_id, user_id, karar, ret_nedeni, önce/sonra, düzeltme_ölçüleri (§12), onaylanan_hash, zaman |
| `api_token` | id, user_id, kapsam (`publish`/`submit`), son_kullanma, iptal |
| `step_mapping` | id, test_case_id, adım_no, po_sınıfı, po_metodu, argümanlar, doğrulandı, ekran_görüntüsü_ref |
| `script` | id, dosya_yolu, branch, pr_no, durum, pass@1, onarım_sonrası_sonuç, insan_review_sonucu, platform, **dil** (`ts`/`java`/`csharp`/`python`), **dil_kaynagi** (`algilandi`/`secildi`/`varsayilan`) — 011 |
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
| `tool_call` | id, ai_call_id, kanal (`agent`/`ide`/`asistan`), çağıran_user_id, araç, argüman özeti, sonuç özeti, izin_verildi, zaman |
| `audit_event` | id, aktör, eylem, nesne, önce/sonra özeti, zaman, `prev_hash`, `hash` |
| `asistan_sohbet` | id, kullanici_id, başlık, oneri_kural_id, silindi/silinme, oluşturma/güncelleme (§8.13) |
| `asistan_mesaj` | id, sohbet_id, kullanici_id, sıra, rol (`user`/`assistant`), ust_mesaj_id, içerik, bağlam, cevap, durum (`pending`/`running`/`done`/`error`/`iptal`), hata_kodu, kaynak (`model`/`sozluk`/`sablon`/`kapali`), amaç, kip (`soru`/`oneri`), tetik (`kullanici`/`otomatik`), job_id, ai_call_id, maliyet, token, süre, geri_bildirim |
| `asistan_durum` | tekil satır, yalnız worker yazar: mod (`live`/`off`), model_hazir, maskeleme, müşteri_verisi, paket_commit, kalp_atışı |
| `asistan_oneri_geri_bildirim` | id, kullanici_id, kural_id, varlik_id, varlik_durum, değer (`-1` gizle / `1` faydalı / `2` yaptım), jira_anahtari |
| `asistan_hiz` | kullanici_id (null = global), kova, pencere_başlangıç, sayı (sabit pencere hız sınırı) |

**SCRIPT durum makinesi (tek kaynak `core/src/tp_core/workflow`, sözleşme JSON'u `review-portal/src/api/sozlesme/durum-makineleri.json`):** `pending → verifying → checking → pr_open → merged`; `verifying|checking → blocked` (insana; `blocked → verifying` yeniden deneme), `→ failed` (`failed → pending`), `pr_open|blocked|failed → closed`. **011:** doğrulanmamış dillerde (C#, Python) uç durum **`unverified`**: `verifying → unverified`, `unverified → pending` (başka dilde / yeniden üret), `unverified → closed`; onay kapısı ve `merged` geçişi yoktur. `unverified` kayıt **etkin script sayılmaz** (K-T4): aynı case+platformun `pr_open`/`merged`/devam eden script'ine dokunmaz; yenisi gelince eski `unverified` kayıtlar `closed` olur. Kontrol Kulesi `unverified`'i ilk review başarısı paydasına katmaz, ayrı sayaçta gösterir. Doğrulanmamış kaynak `script_codegen.kaynak_kod`'dadır (forge'a commit edilmez).

`ai_call`, `tool_call`, `audit_event` için uygulama rolünün yalnızca INSERT/SELECT yetkisi vardır. Asistan tabloları append-only değildir (sohbet 90 gün saklanır); asistanın denetim izi `ai_call.ek` (`{kanal:"asistan", kullanici_id, mesaj_id}`) ve `tool_call` (`kanal='asistan'`) üzerinden kalıcıdır.

**Test case şeması (v3, specs/011 §4.1):** tek kaynak `rules/schemas/case_generation.schema.json`
(`cases.items`); model çıktısı, insan düzeltmesi (`edit`) ve IDE taslağı aynı şemayla doğrulanır.
v2 alanları korunur, v3 alanları eklenir (hepsi zorunlu; boş liste / `null` olabilenler belirtilmiştir):

| Alan | Değer | Not |
|---|---|---|
| `title`, `acceptance_criteria_refs`, `preconditions`, `steps[{id S1…, action, data\|null, expected}]`, `expected_result`, `tags` | v2 ile aynı | `tags` içinde `AI-generated` (kategori etiketleri `smoke`/`regression`/`security`/`a11y`/`performance`); ≤ 8 adım. v3'te `risk` yoktur (K18; risk `priority_rationale`'de), eski case'te okunur |
| `type` | `positive`/`negative`/`boundary`/`authorization`/`integration` | son ikisi v3'te eklendi (Jira'da "yetki", "entegrasyon") |
| `technique[]` | `EP`/`BVA`/`DT`/`ST`/`PW`/`UC`/`EG`/`CL` (kontrol listesi, K19) | `covers` önekleriyle çift yönlü uyumlu (BVA ↔ `BV-`) |
| `covers[]` | kapsam öğesi kimlikleri (`EP-V1`, `EP-I2`, `BV-3`, `DT-R2`, `ST-T1` geçerli geçiş / `ST-X1` geçersiz geçiş (durum + olay), `PW-1` parametre-değer çifti, `UC-MF\|AF1\|EF1`, `EG-1`, `CL-1` kontrol listesi maddesi) | `coverage_items`'ta tanımlı olmalı |
| `priority`, `priority_rationale` | `P1`/`P2`/`P3` + gerekçe (etki, olasılık, iş kritikliği) | |
| `test_level` | `UNIT`…`UAT` ya da `null` | üretim girdisindeki seviye (varsayılan `SYSTEM`) |
| `verification_point` | `UI`/`API`/`event`/`DB`/`log`/`other` | beklenen sonucun doğrulandığı yer |
| `readiness` | `ready`/`assumption_dependent`/`blocked` | aşağıdaki kural |
| `assumption_refs[]`, `open_question_refs[]` | `A1…`, `Q1…` | üst listelerde tanımlı olmalı |
| `test_data[{name, value, class, synthetic, is_attack_payload}]` | `synthetic: true` zorunlu | saldırı metni yalnız burada (`is_attack_payload: true`) |
| `teardown[]` | temizlik adımları | gerekmiyorsa boş |
| `platform`, `requires_real_device`, `standard_refs[]` | platform ya da `null`; boolean; standart maddeleri | platform eki yoksa `null` / `false` / boş |

**Üretimin üst düzey listeleri** (`case_uretim.ozet`; hepsi zorunlu, boş olabilir):
`open_questions[{id Qn, question, owner}]`, `assumptions[{id An, statement, owner}]`,
`coverage_items[{id, ac_ref, definition, valid}]`, `negative_coverage[{item, decision:
tested|covered_by|out_of_scope, rationale}]`, `not_covered[{item, reason}]`,
`observations[{standard_ref, note}]`, `automation_open_points[]`,
`config_matrix{parameters[{name, values[]}], constraints[]}`, `testability_gaps[{control, missing}]`.
Kapsam matrisi modele yazdırılmaz; `coverage_matrix` kodda hesaplanır (§12).

**Hazır olma (`readiness`) kuralı:** `ready` → iki atıf listesi boş, `expected_result` ve bütün
adım beklenenleri dolu; `assumption_dependent` → en az bir `assumption_refs`, beklenenler dolu;
`blocked` → en az bir `open_question_refs`, `expected_result` boş (adım beklenenleri boş olabilir).
Yalnız `ready` case onaylanır (K6), yayınlanır ve Gherkin'e aktarılır.

**Eski (v2) case kuralı (K9):** `readiness` anahtarı olmayan içerik eskidir (`legacy: true`): hazır
sayılır, olduğu gibi kalır, düzeltmesi yalnız v2 zorunlu alanlarıyla doğrulanır (düzeltmeye
`readiness` eklenirse tam v3 aranır), tutarlılık kuralları ve denetim kapısı aranmaz. IDE taslağı
her zaman tam v3 ister. Canlı ortamdaki v2 case'ler böylece korunur; migrasyonlar yalnız ekleme yapar.

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

**Case üretimi v3 (specs/011 §3):** `RequirementToCases` şu sırayla ilerler (köşeli parantez = insan):
`[üretim formu: kip, platformlar, test seviyesi, benimsenen standartlar, kapsam dışı]` →
(iki tur: tasarım modeli üretimi → `[model onayı]` →) case üretimi → otomatik review (P8, tavsiye)
→ isteğe bağlı derinleştirme (negatif / teknik; ek taslak) → `[case kararları]` → `[review tamam]`
→ denetim (P9, Agent Probe portu) → `[yayın]` → Gherkin dışa aktarımı (isteğe bağlı, §8.3).
Kısa bölümler: §8.2c (üretim ve tutarlılık), §8.2d (iki tur, review, denetim, platform; dalga 2).

### 8.2 Gereksinim okuma
- Rovo MCP, demo projesinde salt okuma kullanıcı + API token; istemci izin listesi yalnızca okuma araçları.
- Çekilen: özet, açıklama, kabul kriterleri. (Confluence sayfası varsa özetlenir; demoda zorunlu değil.)
- `ac_missing=true` → portalda uyarı ve analiste soru; story case üretimine gönderilmez.
- İstek sınırı: çağrı sayacı, küçük JQL, 5 dk önbellek.
- **B planı:** `JiraRestReader` (aynı arayüz). Demo günü Rovo bağlantısı prova edilir; sorun varsa B planı varsayılan olur.

### 8.2c Case üretimi v3: tutarlılık ve onay (specs/011 §4.2)

- **Çıktı:** case'ler + üretimin üst düzey listeleri (§7). Liste kısmı `case_uretim.ozet`'e,
  case'ler `test_case`'e `draft` olarak yazılır; aynı üretim numarası ikisini bağlar.
- **Case düzeyi kurallar** (`schema.consistency_problems`, eski case'te aranmaz): (1) `covers`
  kimlikleri `coverage_items`'ta tanımlı; (2) `technique` ↔ `covers` öneki çift yönlü uyumlu;
  (3) `assumption_refs` / `open_question_refs` üst listelerde tanımlı; (4) `readiness` kuralı (§7);
  (5) test verisi sentetik; (6) saldırı verisinin metni case'in başka hiçbir alanında (başlık, ön
  koşul, adım, adım verisi, beklenen, temizlik) geçmez (büyük/küçük harf ve boşluk sadeleştirilmiş
  alt dizgi); (7) AC atıfları gereksinimde var.
- **Set düzeyi kurallar** (`set_problems`): her geçersiz (`valid:false`) öğenin negatif kapsam kararı
  var; `tested`/`covered_by` kararlı öğe en az bir case'in `covers`'ında; kapsanmayan öğe/AC
  `not_covered`'da ya da `out_of_scope` kararında gerekçeli; **yetim açık soru yok** (011 K16,
  `orphan_questions`): her açık soru bir case'in `open_question_refs`'inde, bir `not_covered`
  kaydının `question_ref`'inde, bir negatif kapsam gerekçesinde ya da kapsam öğesi tanımında anılır
  (aksi halde PO yanıtı hiçbir case'e dönmez). `not_covered.question_ref` tanımlı bir soru olmalıdır;
  kapsanan bir AC için yazılan bu kayıt **soru bağıdır** (bir kombinasyonun sonucu tanımsız, PO
  yanıtını bekliyor): kapsam matrisinde satır `bekleyen_sorular`/`hazir_durumu: kismen_hazir`
  taşır ve hazır kapsam oranlarına girmez, review girdisinde `soru bekliyor Qn` diye işaretlenir.
  PO yanıtıyla kapanan soru (yanıtlandı + düzeltme denetim kaydı `case.po_yaniti_kaynak`;
  `acik_sorular.closed_question_ids`) yetim sayılmaz ve satırı bekletmez; açık soru listesinde
  `kapandi: true`, öneri yok. Farklı üretimlerde metni farklı aynı soru kimliği (`Q1`) uyarı
  verir (`definition_conflicts`): birleşik özet kimlikle birleştiğinden yetim hesabı yanlış
  eşleşebilir (açık soru listesi metinle eşler). Set ihlali 422 değil, `uyarilar` ve denetim
  kaydıdır (IDE taslağı parça parça gelebilir).
- **Uygulama:** model çıktısındaki ihlalde case yine taslak yazılır, `uyarilar`'da gösterilir ve
  **onay reddedilir**; insan düzeltmesinde ve IDE taslağında case düzeyi ihlal 422'dir.
- **Onay kuralı (K6):** yalnız hazır (`ready`) ve tutarlı case onaylanır; `serialize_cases`
  `onay_engeli` alanında nedeni döner (varsayıma bağlı / engelli / tutarsız). Analist "Düzelt" ile
  hazır yapar ya da reddeder. Eski (v2) case hazır sayılır (K9).
- **Sınırlar:** story başına ≤ 15 case (K17; derinleştirme tur başına ≤ 10), case başına ≤ 8 adım;
  test verisiyle kurulamayan sınır en yakın kurulabilen değerle ya da test verisi hazırlığı ön
  koşuluyla sınanır, P1 sınırı `out_of_scope` bırakılmaz; sığmayan öğe `not_covered`'a
  gerekçesiyle yazılır. Başlığa teknik öneki yazılmaz; case kimliği deterministik `uuid5`'tir.
- **Özet ucu:** `GET /requirements/{id}/case-summary` üretim başına üst listeleri, kodda hesaplanan
  kapsam matrisini (`coverage_matrix` → `{satirlar, oranlar}`; birden çok üretimin özetleri
  birleştirilir, aynı kimlikte sonraki üretim geçerli) ve teknik/readiness dağılımını döner.

### 8.2d Dalga 2 bileşenleri (specs/011 §4.3–§4.6)

- **İki tur (F3, K1):** varsayılan; önce test tasarım modeli (`design-model` v1, `tasarim_modeli`),
  analist onayı, sonra yalnız onaylı modelden case. "Tek tur (hızlı)" seçilebilir; IDE kanalı tek turdur.
- **Review (F2, K4):** her üretimden sonra ayrı çağrı (`case-review` v1, eleştirmen rolü, 12 madde);
  tavsiye niteliğinde, onayı ve yayını engellemez, denetime girdi olur (`case_set_review`).
- **Denetim kapısı (F5, K2–K3):** `case-audit` v1 (Opus) Agent Probe portu arkasında; karar
  `KABUL`/`DUZELTME_GEREKLI`/`ENGELLE` setin güncel `set_hash`'ine bağlanır (`case_set_audit`).
  `set_hash` = güncel v3 case'lerin içerik hash'lerinin sıralı birleşiminin hash'i; set değişince
  önceki karar geçersizdir. `TP_DENETIM_KAPISI=off` kapıyı kapatır. Denetim girdisi
  (`ports.CaseSetAuditRequest`) üretime verilen test verisi bloğunu (`test_data_block`;
  güvenilmeyen blok — kullanıcı, bayi adı, fiyat, UI etiketi kaynağı, böylece denetçi bu değerleri
  uydurma saymaz) ve izinli test ortamlarını (`allowed_hosts`; `synthetic: true` parola yalnız bu
  ortamlarda muaf) taşır.
- **Platform ve derinleştirme (F4, K5, K7):** platform ekleri (Web, Mobil, Desktop, API, Data)
  üretim girdisine eklenir, seçim `requirement.uretim_secenekleri`'nde saklanır; "Negatif genişlet"
  / "Teknik derinleştir" mevcut sete ek taslak üretir (mevcut kimliklerle çakışmayan öğe numaraları).
- **AI ajan ürünleri ve asistan denetimi (F6, F7):** ajan ürününde test Agent Probe'da koşar (bu
  sürümde simülatör); asistan sorusu ve cevabı `assistant-guard` v1 (Haiku) ile puanlanır,
  erişilemezse kapalı (fail-closed).

### 8.3 `publish_test_cases`
- **Girdi:** yalnızca `approved` durumundaki case kimlikleri; içerik kabul etmez.
- **Kontrol:** her case için `içerik_hash == onaylanan_hash`; değilse red.
- **Eşleme:** issue türü `Test` (yoksa `Task` + `test-case` etiketi); özet, etiketler `AI-generated` ve `tp-<uuid>`, story bağlantısı (`is tested by`, yoksa `relates to`). Açıklama müşterinin **Jira görev şablonundadır** (`jira_adf.template_doc`; başlıklar iki dilli, içerik Türkçe): 🎯 Objective (doğrulanan davranış, onaylayan) · 🚀 Scope (tür, risk, kapsanan AC) · 🔄 User Flow (ön koşullar + ADF adım tablosu; Xray'de adımlar Xray adım alanında) · 🔗 Dependencies & Integration (kaynak story) · ℹ️ Other Information & Assets (üretim modu) · 🔑 Acceptance Criteria (beklenen sonuç) · 🧪 QA Checklist (adım başına beklenen); son satır `Kimlik: tp-<uuid> · onaylanan içerik hash: …` (idempotency işareti). Boş bölüm "Not applicable". Ürünün açtığı Bug da aynı şablondadır (`bugs/content.py description_adf`: amaç = özet + beklenen/gerçekleşen, akış = adımlar, bağımlılık = story/test, diğer = ortam/önem/kanıt).
- **Yayın engeli sırası (specs/011 §4.7):** durum `approved` → onaylanan hash = güncel hash →
  gereksinim PO onayı güncel → hazır (`readiness_of == ready`; eski case hazır) → (v3 case ve kapı
  açıksa) setin güncel `set_hash`'i için `KABUL`. Önizleme her kalemde ilk engeli `islem`
  (`blocked_not_approved`/`blocked_hash_mismatch`/`blocked_requirement_changed`/`blocked_not_ready`/
  `blocked_gate`) ve Türkçe `neden` ile gösterir.
- **v3 eşlemesine eklenenler:** Scope bölümüne teknik (kod + Türkçe ad), kapsam öğeleri, öncelik
  (+ gerekçe), doğrulama noktası, test seviyesi, platform / gerçek cihaz, standart atıfları; User
  Flow'a test verisi tablosu (Ad, Değer, Sınıf) ve numaralı temizlik adımları. Saldırı verisi
  (`is_attack_payload`) tabloya yazılmaz: hücrede "kod bloğunda (tablonun altında)", değer tablonun
  altında "güvenlik testi girdisi" notuyla, biçimlendirilmeden kod bloğunda. Tür karşılıkları
  `authorization` → "yetki", `integration` → "entegrasyon".
- **Etiketler:** `AI-generated`, `tp-<uuid>`, üretim modu `tp-mod-…`; v3 case'te ayrıca
  `tp-tech-<TEKNİK>` ve `tp-P1|P2|P3`. Yalnız şemadaki değerler etiket olur (serbest metin etikete taşınmaz).
- **Idempotency:** önce `external_ref` (`intent` yazılır → create → `created` + anahtar); yeniden denemede önce bu tablo, kayıt yoksa `tp-<uuid>` JQL'i. Aynı hash'te çağrı yapılmaz.
- **Dry-run, hata yönetimi:** önizleme portalda; 429/5xx üstel geri çekilme (≤3); kısmi başarı raporlanır.
- **MCP araçları (IDE kanalı):**
  - `submit_draft_cases(requirement_key, cases[])`: IDE'deki Copilot'un ürettiği şemalı taslakları `draft` olarak portala düşürür; şema doğrulanır; Jira'ya yazmaz.
  - `publish_test_cases(case_ids: list[uuid])`: yalnızca onaylı kimliklerle yayın.
  - Kimlik: portalın kullanıcıya verdiği kısa ömürlü (8 saat), kapsamlı bearer token (`Authorization` başlığı); sunucu yalnızca `127.0.0.1`; kayıtta kanal = `ide`, çağıran ve onaylayan ayrı.

### 8.3a Gherkin dışa aktarımı (specs/011 F8, K14)

`GET /requirements/{id}/cases.feature[?yalniz_yayinlanan=1]` (herkes okur) gereksinimin onaylı
(`approved`/`published`; isteğe bağlı yalnız `published`) ve hazır güncel case'lerinden Türkçe
Gherkin üretir (`features/cases/gherkin.py`). Dönüşüm koddadır, **model çağrısı yoktur**; aynı
girdi aynı baytları verir. Yanıt `text/plain; charset=utf-8`, `Content-Disposition: attachment;
filename="<anahtar>.feature"`, `X-TP-Case-Sayisi` / `X-TP-Senaryo-Sayisi` / `X-TP-Taslak-Sayisi`.

- **Dahil olan:** onaylı/yayınlanmış + `readiness_of == ready` (eski v2 case dahil) + önceki
  (PO onayı yenilenmiş) içeriğe ait değil + `approved` case'in onaylanan hash'i güncel. Uygun case
  yoksa **404** (boş `.feature` indirilmez; portal düğmeyi zaten kapatır); gereksinim PO onayı
  dışındaysa **409** (yayınla aynı kural).
- **Biçim:** `# language: tr`, `Özellik: <anahtar> — <başlık>` (AC'ler yorum), case başına
  `Senaryo:`; ön koşullar `Diyelim ki`/`Ve`, test verisi `test verileri:` adımına bağlı
  `| ad | değer | sınıf |` tablosu; her adım `Eğer ki <eylem>` + `O zaman <beklenen>` (adım–beklenen
  eşlemesi korunur); genel beklenen son beklenenden farklıysa `Ve`. Doğal adım dili: anahtar
  kelimeden sonra baş harf (özel ad değilse) küçük; `Eğer ki` adımında emir kipindeki son fiil
  koşul kipine çevrilir ("Giriş sayfasını aç" → "giriş sayfasını açarsa"; tanınmayan kelime
  değişmez). Adım verisi test verisi tablosunda aynen varsa `(test verisi: <ad>)` (değer
  yinelenmez), yoksa tek satır ve tırnaksızsa `(veri: "<değer>")`, değilse docstring. Kurallar
  `gherkin.py` modül açıklamasındadır. Temizlik sonda `# Temizlik:` yorumudur
  (`Ve` adımı olsa `O zaman`'a bağlanıp doğrulama gibi okunurdu; otomasyonda hook'a dönüşür).
- **Etiketler:** `@AC2 @BVA @EP @P1 @sınır-değer @tp-<uuid>` (AC, teknik, öncelik, Türkçe tür, case).
- **Senaryo taslağı:** aynı AC kümesi, birincil teknik, tür, öncelik, doğrulama noktası, test
  seviyesi, platform, ön koşullar, temizlik, adım kimlikleri ve test verisi adları olan v3 case'ler
  — eylemleri yalnız ≤ 3 kelimelik bir aralıkta, girdileri birbirinden farklıysa — `Senaryo taslağı:`
  olur. Örnekler belgedeki kolonlarla başlar (`| teknik | bölüm_id | girdi | beklenen |`; gerekirse
  `girdi_2`, `sınıf`, `ara_beklenen…`). Her case kendi `Örnekler:` bloğundadır (adı case başlığı,
  etiketi `@tp-<uuid>`). Kural tutmazsa (sütun sınırı aşılır, çok satırlı/tırnaklı veri, metinde
  `<girdi>` gibi yer tutucu) birleştirilmez. Testler her örnek satırının açılmış hâlinin case'in
  tek başına senaryosuyla adım adım aynı olduğunu `gherkin-official` ayrıştırıcısıyla doğrular.
- **Kaçış:** tablo hücresinde `\` → `\\`, `|` → `\|`, satır sonu → `\n`; docstring'de `"""` →
  `\"\"\"`; tek satırlık alanlarda satır sonu boşluk olur; etiketteki boşluk/`#`/`@` `-` olur.
  Saldırı verisi yalnız tabloda, kaçışlı ve önünde `# güvenlik testi girdisi` yorumuyla. Sınır:
  Gherkin hücre kenarındaki boşlukları kırpar (baş/son boşluklu değer kırpılmış okunur).
- **Kullanım:** Case review ekranında "Gherkin indir" (uygun case sayısını gösterir; yoksa kapalı ve
  nedenli). Dosya Cucumber/Behave/SpecFlow projesine doğrudan konur; `--tags @tp-<uuid>` tek case'i,
  `--tags @P1` öncelik dilimini seçer. Taslak anahtar kelimesi parser'daki yazımıyla `Senaryo taslağı`dır.

### 8.4 Kod üretimi: doğrula → eşle → şablon
1. **Bağlam:** onaylı case (≤5 adım demo için) + sembol tablosu (page object sınıfları, metotları, imzaları, locator niyetleri, `expect*` doğrulama metotları) + `rules/verify-and-map.md`.
2. **Doğrulama döngüsü (ajan):** her adım için uygulamada eylemi yapar, snapshot'ta hedef elemanı bulur ve **sembol tablosundaki bir metoda** eşler. Çıktı şemalı:
   `step_mapping[{step_id, po, method, args, verified, evidence_ref}]` ve `expects[{po, method, args}]`.
3. **Deterministik kontroller:**
   - her `po.method` sembol tablosunda var mı; argüman türleri imzaya uyuyor mu;
   - her `expects.args` değeri onaylı case'in `expected` / `expected_result` metninde geçiyor mu (assertion değerini model uyduramaz); karşılaştırma öncesi sayı, para ve boşluk biçimi normalize edilir (`1.250,00 TL` ≡ `1250`).
   Biri tutmazsa durur: eksik metot → mühendise "page object'te eksik metot"; kaynağı olmayan beklenen değer → insana.
4. **Şablon:** test dosyası eşlemeden şablonla üretilir; model hiçbir dilde kod yazmaz; değerler dilin literal süzgeciyle basılır (`ts_literal` = `JSON.stringify`, `java_literal`, `cs_literal`, `py_literal`; hepsi enjeksiyona kapalı).
5. **Yerel kontrol (toolchain-worker derler, `test-runner` koşturur; CI ile aynı mekanizma):** ilgili commit checkout edilir, uygulama `test-runner` içinde Playwright `webServer` ile o commit'ten başlatılır; TS: `tsc --strict`, ESLint, `playwright test --repeat-each=3`; web + Java: `app → deps (pom kilidi) → guard → compile → run` (`--repeat-each=3` karşılığı; tarayıcı imajdaki `/ms-playwright`). Doğrulanmamış dillerde bu adım ve 6 yoktur.
   - Kırmızı ve hata **locator/eşleme** kaynaklıysa 1 düzeltme turu (yeniden eşleme); düzeltme turu `expects`'i değiştiremez.
   - Kırmızı ve hata **assertion** kaynaklıysa düzeltme yapılmaz; insana "defect adayı" olarak gider.
6. **PR (bot):** branch `tp/case-<uuid>`; önce aynı branch için açık PR aranır; açıklamada case, Jira, doğrulama özeti, "AI-generated".

**Ajan sınırları:** case başına en fazla 25 araç çağrısı ve ~150k girdi token'ı; bağlamda yalnızca son snapshot tutulur; sistem prompt'u ve sembol tablosu prompt önbelleğinde. **Araç izin listesi:** `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_select_option`, `browser_wait_for`, `browser_generate_locator`. Ekran görüntüsü aracı ajana **verilmez** (kural 5). **Gecikme bütçesi:** adım 5 için 120 sn; aşılırsa portal kullanıcıya REPLAY'e geçmeyi önerir.

**Canlı görünürlük:** her ajan eyleminden sonra core-worker, model döngüsünün dışında ayrı bir MCP oturum çağrısıyla ekran görüntüsü alır ve SSE ile portala akıtır; görüntü modele gönderilmez.

**Üretim dili (011, `specs/011-uretim-dili/plan.md`):** dil platformdan ayrı bir boyuttur. `POST /code/generate {case_ids, platform, dil?}`; `dil` yoksa hedef repodaki elle yazılmış testlerden **algılanır** (saf sayım, model yok; `GET /code/languages`), kullanıcı Kod üretimi ekranında değiştirebilir (`dil_kaynagi = algilandi | secildi | varsayilan`). Geçerli çiftler: web × `ts|java|csharp|python`; uygulama × yalnız `java`. Ajan ve amaç platforma bağlıdır (web'de dil ne olursa olsun `verify_and_map` + Playwright MCP); REPLAY anahtarına dil girmez (TS ↔ Java page object eşitliği bir testle sabit). Sembol tablosu hedef dilin projesinden alınır; web'de doğrulama ajanına repoda TS projesi varsa **TS tablosu** verilir, Java tablosu deterministik denetim + render içindir; repoda yalnız e2e-java varsa Java tablosu verilir ve denetime `ajan_tablosu: java` yazılır (K-T5). Doğrulanmamış dillerde tablo repodaki tam hat dilinden alınır ("referans tablo").
- **Tam hat (ts, java):** adımlar 1–6 aynen. Java web: proje `demo-app/e2e-java` (Playwright for Java + TestNG; paket/konvansiyon e2e-app ile aynı), üretilen dosya `src/test/java/com/antreklabs/bayi/uretilen/<Sınıf>Test.java`, merge kapısı **`local-ci-web-java`** (K-T1; GitHub'da `web-java`).
- **Doğrulanmamış (csharp, python):** adımlar 1–4 (ajan adımları tarayıcıda yine doğrular), render sonrası kaynak `script_codegen.kaynak_kod`'a yazılır; commit, yerel kontrol, PR, kırarak doğrulama ve merge yoktur; durum `unverified`; portal kodu gösterir ve indirir. Dosya yolu tek kaynak render'dan gelir (`<e2e-csharp kökü>/tests/Generated/<Story>WebC<n>_<u8>Tests.cs` (C# metotları `…Async`) · `<e2e-python kökü>/tests/generated/test_<slug>.py`, K-T6). `unverified` etkin script sayılmaz (§7, K-T4). Tam hat dilinde istek, aynı case+platformda **başka dilde merge edilmiş** script varsa **409** döner ("Bu case'in web testi TypeScript ile merge edildi; dil değiştirmek için önce mevcut testi kaldırın").
- **GitHub kipi (K-T3):** web + Java üretimi ve Java kardeş koşusu yalnız `java ∈ TP_WEB_DILLERI` iken; değilse `/code/languages` Java'yı `kullanilabilir=false` + neden döner. LocalForge'da repodaki dosyalar belirler.
- **Yetki (K-T8, 012):** yetki API uçlarındadır (`/code/generate` ve `GET /code/languages` → `code.generate`, Automation Engineer); Kod üretimi (`code.read`) ve Koşular (`run.read`) ekranlarının menü/rota görünürlüğü izin tablosundan gelir (`ROTA_IZINLERI`, ANALIZ 012 §4.2).

**Platform (009):** kod üretimi (case, platform) çiftinedir (`POST /code/generate {case_ids, platform?}`, varsayılan `web`). Uygulama platformlarında amaç `verify_and_map_app`, araç izin listesi `app_launch`, `app_snapshot`, `app_click`, `app_type`, `app_select_option`, `app_wait_for`, `app_generate_locator` (app-mcp); `app_screenshot` yalnız canlı görünüm içindir ve `FORBIDDEN_TOOLS`'tadır. Sembol tablosu `java-araclar symbols`, şablon Java/TestNG, statik kapı `javac` + `java-araclar guard`; dal `tp/case-<platform>-<uuid>`, merge kapısı `local-ci-<platform>`. Adımlar 1–6 ve kurallar değişmez. Ayrıntı: [MOBIL-MASAUSTU.md](MOBIL-MASAUSTU.md).

### 8.5 CI (AI'sız)
- **Toolchain imajı:** ayrı `build-toolchain` workflow'u, `docker/build-push-action` ile `platforms: linux/amd64,linux/arm64` ve `cache-from/to: type=gha`; etiket `.playwright-version`'dan türetilir, kullanıldığı her yerde digest ile sabitlenir; GHCR paket ayarında `testingprobe` reposuna Actions erişimi verilir.
- **Job:** `container: ghcr.io/thinkgotr/tp-toolchain@<digest>` (toolchain-worker ve test-runner ile aynı imaj: Playwright tarayıcıları + Node + Python + uv), `container.credentials: { username: ${{ github.actor }}, password: ${{ secrets.GITHUB_TOKEN }} }`; demo uygulaması her ortamda aynı yolla, Playwright `webServer` dizisiyle başlar: `uv run uvicorn` (API) ve `vite build && vite preview` (web); `BASE_URL` tek kaynaktan.
- **Adımlar:** `npm ci` (önbellekli) → `tsc --strict` → `eslint --no-inline-config` → AST koruması → `playwright test --retries=1 --project=chromium` (JSON + HTML + trace) → artefakt.
- **Zaman aşımları:** `actionTimeout` 5 sn, `expect.timeout` 5 sn, test 20 sn (kırık locator'lı kırmızı koşu < 60 sn).
- **Ayrı job:** Semgrep (SAST).
- **Web + Java (011):** ayrı iş akışı `web-java.yml` (check `web-java`): `demo-app/ci/run-java-checks.sh` — pom kilidi (CI'da güvenilir pom yoksa hata) → `java-araclar guard` → `test-compile` → birim → tarayıcı koşusu; AI yok. Yalnız Java web projesini değiştiren PR'da `test-local` no-op'tur. Paket koşuları (gece, **push**, deploy) repodaki tüm tam hat dillerini koşar (K-T2: merge sonrası push da paket koşusudur, script'li push'ta da kardeş dağıtımı); koşu kaydı dili `run.ortam.dil`'de taşır. Yerelde script'siz PR CI'ı değişen yollardan dil(ler)i seçer (`e2e/` → `local-ci`, `e2e-java/` → `local-ci-web-java`; ikisi de değiştiyse ikisi); **K-T11:** test köklerinin (`e2e/`, `e2e-java/`, `e2e-app/`) dışında değişiklik (uygulama kodu vb.) varsa repodaki tüm tam hat dilleri koşar ve merge kapısı aynı kuralla (`local-ci` + varsa `local-ci-web-java`); LocalForge'da böyle bir PR yerel CI'ı ~2× yükler. GitHub'da `web-java.yml` yol süzgeci daha dardır (ör. yalnız `mobile/`/`desktop/` değişen PR'da Java koşmaz, `web-java` no-op yeşil; LocalForge koşar). **K-T10:** GitHub kipinde `web-java` check'i `web-java.yml` depoda olduğu sürece her zaman zorunludur (ilgisiz PR'da `changes` + no-op ile hızla yeşil); `TP_WEB_DILLERI` yalnız Java üretimini ve kardeş koşuyu açar. **K-T13:** core'un merge kapısı zorunlu listeyi PR'ın base ∪ head ağacından hesaplar (`web-java.yml` birinde varsa `web-java` zorunlu); ağaç okunamaz ya da kesikse (`truncated`) kapalı taraf; portal aynası listeyi core'dan okur; `web-java.yml`'yi silen PR'da önce ruleset'ten çıkarılır (`docs/GCP-KURULUM.md` §10.2 adım 11). Ruleset güncellemesi mevcut platform check'lerini korur (`scripts/github-ruleset.sh --add-checks web-java`). **K-T14:** toolchain pom kilidi commit'teki `pom.xml`'i imajdaki güvenilir kopyayla karşılaştırdığından pom'u değiştiren dağıtımda (011: e2e-app + e2e-java) toolchain imajının hemen ardından depo/forge eşitlenir (`docs/GCP-KURULUM.md` §10.2 adım 5; LocalForge'da `uretilen/` korunarak). LocalForge'da dil/platform check'leri `TP_REQUIRED_CHECKS`'e yazılmaz (yazılan liste her PR'da zorunludur; yol kuralı ekler). **K-T12:** başka dilde merge edilmiş testin kaldırılması ürün akışı değildir: üretim 409 + çıkış yolu ("mevcut test dosyasını silen bir PR'ı merge edin, sonra yeniden üretin"), elle adım `docs/GCP-KURULUM.md` §10.2 adım 12. Ayrıntı: `.github/CI.md` "Web Java iş akışı".
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
5. **Web + Java (011):** "Java mı" sorusu platforma değil dile/rapora bakar. Playwright Java kalıpları: `com.microsoft.playwright.TimeoutError` / "waiting for locator" → locator; `AssertionFailedError` / `AssertionError` → assertion (ürün hatası adayı); bağlantı hataları → ortam. Kanıt web yöntemiyle (`target/kanit/<Sınıf>.<metot>/{trace.zip, sayfa.html, ekran.png}`); testId eşleme `Kimlikler.java` üzerinden; `sayfa.html` ayrıştırması düğüm/derinlik/testId sayısı ve süreyle sınırlıdır.
6. **Brief'in 4 sınıfı ile ilişki:** `test_maintenance` brief'teki "kırılan locator için onarım önerisi" yoludur; dört kök neden sınıfının dışında, ayrı izlenir (§19, onaylandı).

### 8.7 Locator onarımı
- **`locators.ts` saf veri:** `export const cart = { addToCart: { testId: 'add-to-cart', role: 'button', name: 'Sepete ekle', intent: 'Ürün kartında sepete ekleme butonu' } } as const;`
- **Aday üretimi (LLM'siz):** aria snapshot `data-testid` içermediği için testId DOM'dan okunur: toolchain-worker kırılan commit'te uygulamayı başlatır, kırılan testi hata adımına kadar koşturur ve `getByRole(role, { name }).getAttribute('data-testid')` değerini okur (alternatif kaynak: `trace.zip` içindeki DOM snapshot'ı). Rol + ad eşleşmesi 0 veya birden fazla eleman verirse öneri üretilmez, insana (veya LLM yorumuna) düşer. `browser_generate_locator` yalnızca çapraz kontrol.
- **Doğrulama:** aday, son yeşil koşudaki aria snapshot'ının `role + name` değerleriyle eşleşmeli (yanlış butona "onarmayı" önler).
- **Kapsam (`within`):** aynı rol + ad sayfada birden çok kez geçiyorsa (ör. her ürün kartında "Sepete ekle") locator metadata'sı
  kapsayıcının testId önekini `within` alanında taşır (`within: 'product-card-'`). Aday üretimi `scope_test_id`
  (`within` + başarısız adımdaki ürün kodu, ör. `product-card-P-001`) ile yalnızca o kapsayıcıdaki eşleşmeleri sayar;
  kapsam yokken çoklu eşleşme yine öneri üretmez. `within` onarımda değiştirilemez (AST koruması `field_changed`).
  demo-app `tests/locators.spec.ts`, `within`'siz çoklu eşleşen her adlı locator'ı reddeder.
- **PR dalı ve etiket:** `tp/repair-<anahtar>` + `tp-repair` etiketi (CI AST koruması onarım modunu buna göre seçer).
- **AST koruması:** değişen dosyalar yalnızca `pages/**/locators.ts`; anahtar kümesi, `role`, `name`, `intent` değişmemiş; yalnızca ilgili `testId` string değeri değişmiş. Aynı kontrol CI'da zorunlu check.
- **PR:** yerel kontrol **etkilenen tüm testlerde** yeşilse (AI'ın ürettikleri ve elle yazılmış olanlar) bot açar; insan onayı zorunlu.
- **Birim testleri:** 0 eşleşme, çoklu eşleşme, anahtar/niyet değişikliği denemesi, test dosyasına dokunan yama.
- **Web + Java (011):** aday bulma **web yöntemi** (DOM/aria, `/locator-probe`), yama **Java yöntemi**: değişen tek dosya `demo-app/e2e-java/.../ekranlar/Kimlikler.java`, yalnız ilgili sabitin string değeri (`java-araclar locators patch`); kapı `local-ci-web-java`.
- **Uygulama platformları (009):** aynı kural Java'da: değişen tek dosya `demo-app/e2e-app/.../ekranlar/Kimlikler.java`, yalnız ilgili sabitin string değeri değişir (`java-araclar locators patch` / `locators diff`); triage kanıtı hata anının sayfa kaynağı XML'i + ekran görüntüsüdür.

### 8.8 Model geçidi
- **İki giriş:** `gateway.call(purpose, bundle, messages, schema, max_tokens, budget)` ve `gateway.run_agent(purpose, bundle, tools, max_turns, budget)`.
- **Sağlayıcıdan bağımsız sözleşme:** girdiler (mesajlar, araç tanımları JSON Schema, çıktı şeması) ve çıktılar (yapılandırılmış sonuç, araç çağrıları, token) ortak tiptedir; sağlayıcıya özgü özellikler (Anthropic prompt caching, strict tool; Azure OpenAI structured outputs) yalnızca adaptörde. Değerlendirme seti her iki sağlayıcıda koşup kabul oranları yan yana raporlanır (Azure erişimi olduğunda).
- **Ajan:** Anthropic SDK tool-use döngüsü (kendi döngümüz); her tur bir `ai_call` satırı, `parent_call_id` ile bağlı; her araç çağrısı `tool_call`.
- **Görev başına model (sabit kimlik konfigürasyonda):** case üretimi ve doğrulama ajanı → Claude Sonnet sınıfı; triage ve özetleme → Claude Haiku sınıfı; **portal asistanı (`assistant`) → Haiku sınıfı, otomatik ("Emin değil") veya istek üzerine ("Daha ayrıntılı incele") `assistant_deep` → Sonnet sınıfı** (§8.13); `temperature` sabit (0–0,2).
- **Asistan kipi pipeline'dan bağımsız:** `TP_ASISTAN_MODEL_MODE=live|off` (varsayılan `off`); asistan geçidi `build_gateway(mode_override="live", replay_fallback=False, budget=AsistanBudget)` ile kurulur, `record` kipine girmez, golden kullanmaz. `run_agent`'ın yeni parametreleri (`tool_channel`, `caller_user_id`, `ek`, `masking_session`, `bitis`, `should_stop`, `toparlama`) varsayılanda eski davranışı korur.
- **Hata politikası:** 429/529/5xx → üstel geri çekilme, ≤3; şema hatası → hata metniyle ≤2 yeniden istek. Aktivite yeniden denemesi `ai_call.id` ile idempotent (aynı çağrı iki kez faturalanmaz).
- **Şema sistem mesajında (`params: { output: prompt }`):** `case_generation`, `design_model`, `case_deepening` şemaları Anthropic'in yapılandırılmış çıktı dilbilgisi sınırını aşar ("compiled grammar is too large"). Bu amaçlarda adaptör şemayı `output_config.format` yerine sistem mesajının önbelleklenen son bloğunda gönderir; çıktı geçitte tam şemayla doğrulanır, uymazsa yeniden istenir.
- **Kural yeniden isteme (`call(output_check=…)`):** şemaya uyan çıktının deterministik kural denetimi (011 §4.2: case tutarlılığı, AC kapsamı, yetim açık soru, tur 2'de onaylı modelden sapma). İhlal varsa model aynı yeniden isteme döngüsünde (≤2) yönlendirilir; ara deneme satırı `hata="kural: …"` taşır, kural hataları `ek.kural_hatalari`'ndadır; sonraki denemeler bozulursa en az ihlalli çıktı döner (`ek.secilen_deneme`). Döngü bitince yalnız kural ihlali kalırsa çıktı uyarıyla döner (hata değil). Anahtar `TP_KURAL_YENIDEN_ISTEME` (varsayılan açık, `off` kapatır); canlı değerlendirmede de açıktır, ham model için `eval-live --no-output-check`.
- **İş süresi bağlamı (`gateway.is_suresi`):** iş kuyruğu işleyiciyi `is_suresi(zaman_asimi_s)` içinde koşar; geçit yeniden istemeden önce kalan süreye bakar ve bir çağrının en kötü süresine (timeout × (1 + zaman aşımı yeniden denemesi) + pay) yetmiyorsa yeniden istemez, eldeki çıktıyı uyarıyla döndürür (iş zaman aşımına düşüp worker'ı çıkartmaz). İş dışında (eval, betik) süre tanımsızdır.
- **Değerlendirme ölçümleri (`olcumler`):** case üretimi canlı raporu geçit+model sonucunun yanında ham modeli ölçer: `ilk_deneme_gecis_orani` (bağlayıcı `ham_gecis_alt_siniri`, case-generation'da 0,6), kural/şema yeniden isteme oranı, `duzelme_orani`, `kalan_kural_ihlali`, ek maliyet/süre, kural türü histogramı, `sepet_okunamadi` (uydurma sayılmaz) ve alt küme başına ölçüm. Setin bekletme (holdout) alt kümesi prompt ayarında kullanılmamış, örtüşmeyen alanlardan story'lerdir ve bağlayıcıdır (`rules/README.md` "Bekletme").
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
- **Kimlik (demo):** seed kullanıcılar (rol başına bir hesap: `analist`, `po`, `testci`, `muhendis`, `sunucu` → `admin`; yeni roller için hesaplar `seed.py`'de), oturum çerezi; her karar kullanıcı adına imzalı.
- **Yetki (012):** her uç bir izin anahtarı ister (`tp_core/auth/yetki.py` `IZINLER`, `izin("case.approve")` bağımlılığı); katalogda olmayan izin reddedilir (yazma ve okuma). Red 403 `yetki_yok` + `authz.denied` denetim kaydı. `GET /auth/me` `izinler` listesini döner; portal menü, sayfa (`IzinGerekli`) ve düğmeleri (`useIzin`) buna göre gösterir — gizleme kontrol değildir, kontrol çekirdektedir. Görevler ayrılığı role göredir: bir kişi birden çok rol alır, rol hesapları arasında geçer (K1, K2). Rol ataması AI Probe'dadır (K5). Okuma süzgeçleri: `developer` yalnız onaylı/yayınlı case ve açılmış/bağlanmış bug görür, `TP_ORTAM=prod` iken koşu başlatamaz; `auditor` ve `viewer` ham artefakt ve canlı olay görmez; denetim kaydının tamamını `admin`/`auditor`, diğerleri kendi olaylarını görür. Rol ve izin tablosu: `specs/012-rol-yetki/ANALIZ.md` §3–§4. `aiprobe`/`both` kipinde giriş AI Probe hesabıyla (§8.14): çok rol hesabına bağlı kişiye rol seçici, üst çubukta "Rol değiştir".
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

### 8.13 Portal asistanı ve Öneri

**Amaç:** Portalın her ekranında Türkçe soru-cevap ("Bu buton neden gri?", "Bu hata ne demek?", "TPD-3 neden bekliyor?") ve o ekranda, o rolün **şimdi yapması gereken** işleri gerekçesiyle listeleyen Öneri düğmesi. Ayrıntılı plan `docs/AI-ASISTAN-PLANI.md` v6; spec ve sözleşmeler `specs/008-ai-asistan/`; bağlayıcı uçlar ve `kod` enum'u MIMARI-SOZLESME §5.

**Değişmez sınırlar (constitution v1.3.0 İlke II):** asistan **salt okuma bilgi ve yönlendirme asistanıdır**; eylem yapmaz (yazma aracı, onay, yayın, Jira kaydı/yorumu yok — eylem isteğinde `eylem_reddi` + ilgili ekrana bağlantı); çıktısı karar dayanağı değildir ve hiçbir karar alanına veya başka AI adımına girdi olmaz; model yalnızca core-worker'da.

**Bilgi kaynakları (13 salt okuma araç, `ALLOWED_AGENT_TOOLS["assistant"|"assistant_deep"]`):**
- Ürünün kendisi: `product_search`, `product_read` — imaja değil, `make up` ön adımında üretilen ve yalnız core-worker'a `:ro` bağlanan **bilgi paketinden** (`var/tp-bilgi/`, izin listeli portal/core kaynakları ve dokümanlar, MANIFEST + sha256 + üretim sır taraması).
- Testing Probe verisi: `probe_get`, `probe_list`, `probe_jobs`, `probe_audit`, `probe_my_queue` — mevcut GET servis fonksiyonları; araç → uç tablosu izin kataloğundan türetilir, asistanın okuduğu veri rolün okuma izinlerini aşmaz (012).
- Test edilen uygulama: mevcut `search_code`, `get_file_contents`, `db_schema`, `db_query` (§8.2b erişim kuralları).
- Canlı Jira: `jira_issue` — yalnız Testing Probe'da kaydı olan anahtarlar, dar `JiraOkuyucu` (yazma metodu yok, httpx katmanında yalnız GET), kısıtlı yorumlar elenir, kişi kimlikleri modele gitmez; global Jira kovası 30/dk.
- CI: `ci_log` — DB adım özeti → güvenli açılan yerel log (`O_NOFOLLOW` + inode) → GitHub iş logu (`actions:read`); ≤ 16 KB, sır temizliği + maskeleme.

**Güvenlik:** tüm araç sonuçları, ekran bağlamı, Jira yorumları, CI logu, öneri metni ve sohbet geçmişi `<untrusted>` (§5); her araç çıktısı `scrub_secret_patterns` + çalışma anı sır değerleri ile temizlenir; mesaj başına **tek maskeleme oturumu** (§8.9); müşteri verisi kurulumunda maskeleme kapalıysa asistan kapalı; soru/bağlam sır deseni içerirse 422 `sir_icerik`.

**Akış (worker, `assistant.answer`, ayrı `asistan` şeridi, 3 iş parçacığı, 75 sn bütçe):** hata sözlüğü (modelsiz) → şablonlar (Probe durumu, "bugün ne yapmalıyım"; modelsiz) → model kapalıysa sabit cevap → canlı ajan (`run_agent`, `max_turns=6`, toparlama) → **deterministik son işlem**: URL düzleştirme; link yalnız `rotalar.json` iç rotaları ve bilinen Jira anahtarları (bağlantıyı sunucu kurar); kaynak doğrulama (dosya:satır alıntısı, SQL yeniden çalıştırma + digest, `kN` kanıt kimliği); güven gösterimi (`Kaynakla doğrulandı` / `Kısmen` / `Emin değil` / `Genel bilgi`).

**Otomatik yükseltme:** Haiku cevabı ürüne özgü soruda "Emin değil" (veya "Kısmen"/toparlama) ise ve bütçe ön koşulları tutarsa (kalanlar ≥ $0.20, global sayaç) aynı transaction'da **ayrı çocuk mesaj** (`assistant_deep`, `tetik='otomatik'`) açılır; zincir yok; `unique(ust_mesaj_id)` elle basışla yarışı çözer.

**Öneri:** `rules/assistant/oneriler.yaml` kural dosyası (İlke IX), kapalı olgu ve operatör kümesi, ifade değerlendirme yok (İlke XI); modelsiz `GET /assistant/suggestions` (model kapalıyken de çalışır, `ai_call` yazmaz). Eylem: iç rota ("Git"), Jira yorum/kayıt taslağı (kullanıcı kopyalar ve kendisi açar; "Jira'yı aç" bağlantısını yalnız sunucu kurar), Jira kaydı, bilgi. Testing Probe'un kendi onaylı hattı olan işlerde (bug taslağı, case yayını, tutarlılık bulgusu) Jira eylemi yasak. Rol hizalama testi: `rota` eylemli kuralın rolleri, ilgili ucun izin anahtarına sahip rollerin (`yetki.py`) alt kümesi. "Neden? Sor" öneriyi sohbete bağlam olarak taşır; "Başka ne yapabilirim?" model destekli ≤ 3 ek öneri ("AI önerisi · doğrulanmadı").

**Bütçe ve hız (K3):** asistan günlük $10, kullanıcı günlük $1, kök soru başı $0.50 (çocuklar dahil); kullanıcı saatte 30 soru, kullanıcı başı 1 bekleyen (kısmi tekil indeks), global 6 bekleyen (advisory lock). Beklenen ≈ $0.03/soru.

**Kayıt (İlke VIII):** her model çağrısı `ai_call` (`ek` = kişi + mesaj), her araç çağrısı `tool_call` (`kanal='asistan'`, `cagiran_user_id`); sohbet 90 gün saklanır, `ai_call`/`tool_call` kalıcıdır.

**Ölçüm (İlke X):** paket `pending` girer; `main` öncesi ≥ 30 soruluk canlı set (eylem reddi ve injection direnci %100, doğrulanmış kaynak ≥ %70, otomatik yükseltme ≤ %35, medyan maliyet ve p90 süre eşikleri) → `evaluated`, `evaluations.yaml`'da içerik hash'i.

**Portal:** sağ altta panel (bindirme, mobilde modal; `role="complementary"`), bağlam çipleri (ekran, son hata, "? Bu ne?"), `HataKutusu`'nda "Asistana sor", üst çubukta tek Öneri düğmesi (sayı rozeti), kapalı kipte "HAZIR CEVAPLAR" rozeti (canlı kipte "CANLI" yazılmaz).

### 8.14 AI Probe ortak kimliği (ADR-0001, `specs/010-aiprobe-sso/`)

**Kip:** `TP_AUTH_MODE=local|aiprobe|both`. `local` (varsayılan; on-prem, İlke VII) bugünkü davranıştır: argon2 giriş, `tp_session` çerezi, dış çağrı yok. `aiprobe`: yalnız ortak kimlik (`POST /auth/login` 404). `both`: ikisi birden (geçiş ve acil erişim); yerel parola yalnız bağsız hesaplar içindir — `kimlik_bagi`'lı hesap yerel girişte 403 `aiprobe_gerekli`. `aiprobe`'da yerel oturum ve bağsız/yerel oturumdan üretilmiş `tpt_` token'ı reddedilir. `aiprobe`/`both`'ta oturum çerezi `__Host-tp_session` (Secure, HttpOnly, SameSite=Lax, Path=/), durum çerezi `__Host-aiprobe_state` (yalnız düz `http://localhost` geliştirmesinde Secure'suz `aiprobe_state`, CONTRACT).

**Giriş devri (PLAN §2.3, CONTRACT "Ürün tarafı"):** `GET /auth/aiprobe/login?continue=` → 32 baytlık `state` + çerez (10 dk) → `{AIPROBE_ID_ORIGIN}/login?product=testing-probe&state=&continue=`. Dönüş `GET /auth/aiprobe/callback?code=&state=` → çerezle sabit zamanlı karşılaştırma → `POST {AIPROBE_HOME_RUN_URL}/v1/handoff/redeem` (TP servis hesabının Google ID token'ı; sağlayıcı enjekte edilebilir, varsayılan GCE metadata sunucusu) → yanıtın `state`'i de eşleşmeli, `org` ∈ `AIPROBE_ALLOWED_ORGS` (boşsa red, fail-closed) → TP rolleri = `roles` ∩ TP rolleri (012: devirde gelen `presenter`, AI Probe'daki rol kayıtları güncellenene kadar `admin` sayılır). `continue` yalnız `/` ile başlayan göreli yol (`//`, `\`, kontrol karakteri reddedilir → `/`).

**Kişi ↔ rol hesabı:** `kimlik_bagi(external_uid, app_user_id UNIQUE)`. Aday hesaplar = kişiye bağlı ve rolü `roles` içinde olan `app_user`'lar. **JIT:** `roles`'taki bir rol için bağlı hesap yoksa o rol adına yeni `app_user` (`ad_soyad` = devirdeki `name`; kullanılamaz parola özeti → yerel girişle açılamaz) + bağ (`auth.jit_user` denetimi). Tek aday → oturum; birden çok → imzalı 10 dk'lık seçim çerezi + portal `/rol-sec` → `POST /auth/aiprobe/rol-sec`. **Rol değiştir:** `POST /auth/aiprobe/rol-degistir` — parola yok; sunucu bağı ve rolü taze oturum kontrolüyle yeniden doğrular, eski oturumu iptal eder, **yeni oturum kimliği** verir.

**Oturum ve iptal:** `oturum.external_uid`, `auth_time`, `son_kontrol`. Boşta 30 dk kayan (yalnız kullanıcı istekleri uzatır; SSE denetimi uzatmaz), mutlak 8 sa. `session_valid` ve `verify_bearer`, son kontrolden ≥ 60 sn geçtiyse `POST /v1/session/check {uid, auth_time}` çağırır; gövde `{uid, auth_time, acr, session_epoch_ms}` (oturumun/token'ın devirdeki değerleri; `session_epoch_ms` yoksa gönderilmez — CONTRACT v1.2). Süreç içi 60 sn önbellek; SSE'nin 15 sn döngüsü aynı yolu kullanır. Yanıttaki `roles` de `acr` "2" değilse `po`'suz süzülür (derinlemesine savunma; giriş, rol seçimi/değiştirme, oturum ve token kontrolünde). `valid=false` ya da oturumun rolü artık `roles`'ta değilse: kişinin bağlı hesaplarının `app_user.auth_epoch`'u artar, `external_uid` oturumları iptal edilir → çerez (`ae` alanı) ve `tpt_` token'ları (`api_token.auth_epoch`) reddedilir (≤ 60 sn, yolculuk 13). `aiprobe-home` erişilemezse (ağ hatası, 5xx, 408, 429) oturum ve token **en çok 10 dk** korunur (`oturum`/`api_token.degraded_baslangic`, ilk erişilemeyen kontrolde ayrı işlemde yazılır; boşta süresi bu sınırın ötesine uzatılmaz), yanıtta `X-Aiprobe-Degraded: 1`; sınır aşılınca oturum kapatılır (`auth.aiprobe_degraded_timeout`), token reddedilir; başarılı kontrol sınırı sıfırlar. Diğer 4xx yanıtları fail-closed'dur (`check_rejected_<kod>` ile iptal); 401 `invalid_caller` ayrıca dakikada bir ERROR `aiprobe_check_invalid_caller` (sayaçlı) olarak loglanır. Yeni giriş 503. Yerel kipe dönülünce AI Probe oturumları ve onlardan üretilmiş `tpt_` token'ları (`auth_time` dolu) reddedilir.

**Çıkış:** `POST /auth/logout` yerel oturumu iptal eder; AI Probe oturumunda yanıt `redirect: {AIPROBE_ID_ORIGIN}/logout?product=testing-probe` taşır (tüm ürünlerden çıkış; "yalnız bu üründen" yok).

**Yönetim:** `GET|PUT|DELETE /admin/kimlik-bagi` yalnızca `aiprobe-home` servis kimliğiyle: Google ID token (`aud` = `AIPROBE_TP_AUDIENCE`, `iss` Google, `email_verified`, `email` = `AIPROBE_HOME_SA`); doğrulayıcı enjekte edilebilir. Bağ kaldırma o hesabın epoch'unu artırır ve oturumlarını kapatır. Ekran `home/admin` "TP rol hesabı bağla"dadır (TP'de yönetim ekranı yok).

## 9. API sözleşmesi (özet)

| Yöntem | Yol | Amaç |
|---|---|---|
| POST | `/api/auth/login` | Oturum (`local`/`both`) |
| GET | `/api/auth/aiprobe/login` · `/api/auth/aiprobe/callback` | AI Probe giriş devri (`aiprobe`/`both`, §8.14) |
| GET · POST | `/api/auth/aiprobe/hesaplar` · `/rol-sec` · `/rol-degistir` | Rol seçici ve rol değiştir |
| GET · PUT · DELETE | `/api/admin/kimlik-bagi` | Kişi ↔ rol hesabı bağı; yalnız `aiprobe-home` servis kimliği |
| GET | `/api/requirements?project=` | Story listesi (Rovo) |
| POST | `/api/requirements/{key}/generate` | `RequirementToCases` başlat |
| GET | `/api/cases?requirement=` | Case listesi |
| POST | `/api/cases/{id}/decision` | Onay/düzelt/reddet (Update) |
| POST | `/api/requirements/{key}/review-complete` | Review tamam (Update) |
| GET | `/api/requirements/{id}/case-summary` | Üretim özetleri + kapsam matrisi + teknik/readiness dağılımı (§8.2c) |
| GET | `/api/requirements/{id}/cases.feature` | Gherkin dışa aktarımı (text/plain, §8.3a) |
| GET | `/api/publish/preview?requirement=` | Dry-run gövdesi |
| POST | `/api/publish` | Yayın (Update, imzalı) |
| POST | `/api/code/generate` | `CasesToCode(case_ids)` başlat |
| GET | `/api/runs/{id}` · `/api/failures/{id}` | Koşu ve triage |
| POST | `/api/failures/{id}/fix` | `FailureToFix` başlat |
| GET | `/api/audit?verify=true` | Denetim kaydı + zincir doğrulaması |
| GET | `/api/events` (SSE) | `case.generated`, `agent.step`, `pr.opened`, `ci.status`, `failure.classified`; `assistant.step`, `assistant.answered` yalnız sahibi olan oturuma |
| POST | `/api/tokens` | IDE kanalı için kısa ömürlü kapsamlı token |
| GET | `/api/assistant/status` | Asistan durumu (`asistan_durum`'dan; kalp atışı yoksa `worker_yok`) |
| GET · POST · DELETE | `/api/assistant/conversations[/{id}]` | Kendi sohbetleri; yumuşak silme |
| GET · POST | `/api/assistant/conversations/{id}/messages` | Mesajlar · soru / öneri modu / "Daha ayrıntılı incele" (`ust_mesaj_id`) → 202 |
| GET · POST | `/api/assistant/messages/{id}` · `/cancel` · `/feedback` | Yoklama · iptal · 👍/👎 |
| GET · POST | `/api/assistant/suggestions` · `/{kural_id}/feedback` | Kural tabanlı öneriler (modelsiz) · Gizle/Faydalı/Yaptım |
| MCP | `submit_draft_cases(requirement_key, cases[])` | IDE kanalı: taslakları portala düşürür |
| MCP | `publish_test_cases(case_ids)` | IDE kanalı: onaylıları yayınlar |

Hata gövdesi `{"detail", "kod"}`; `kod` sabit enum'dan (MIMARI-SOZLESME §5), 5xx'te `ic_hata`.

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

Tek doğruluk kaynağı repo kökündeki `docker-compose.yml`'dir; ayrıntılar `specs/001-dev-foundation/` (plan, research R1–R13, contracts). Temporal demoda yoktur (karar §0-25); iş akışı Postgres tabanlı kuyruk ve `core-worker` ile yürür.

| Servis | İmaj | Host portu (yalnızca 127.0.0.1) | Ağlar | Healthcheck |
|---|---|---|---|---|
| `postgres` | `postgres:16-alpine@sha256:…` | 55432 | core-net, data-net | `pg_isready` |
| `migrate` | çekirdek imajı (tek seferlik, `alembic upgrade head`, `tp_owner`) | — | core-net | `service_completed_successfully` |
| `core-api` | çekirdek imajı | 8000 | core-net | `/health` (DB) |
| `core-worker` | çekirdek imajı | — | core-net | `python -m tp_core.worker.healthcheck` |
| `toolchain-worker` | toolchain imajı | — | core-net, runner-net | `/health` :8100 (node, Playwright sürümü) |
| `test-runner` | toolchain imajı | — | demo-net, runner-net | `/health` :8200 |
| `playwright-mcp` | toolchain imajı, `@playwright/mcp` 0.0.83 (playwright-core 1.64.1'e sabit), `--headless --browser chromium --isolated --caps=testing --allowed-origins http://demo-app-web:8080` | 8931 (host'a açılmaz) | agent-net, mcp-net | TCP 8931 |
| `review-portal` | React + Vite → nginx (`/api/` → core-api) | 8080 | core-net | `/health` |
| `demo-app-api` | FastAPI | — | data-net, demo-net | `/health` (DB) |
| `demo-app-web` | React + Vite → nginx (`/api/` → demo-app-api) | 8081 | core-net, demo-net, agent-net | `/health` |

- **Ağlar:** `data-net`, `demo-net`, `agent-net`, `runner-net`, `mcp-net` `internal: true`. test-runner postgres'i, core-api'yi, playwright-mcp'yi ve interneti göremez; ajan tarayıcısı (playwright-mcp, `agent-net` + `mcp-net`) yalnızca demo-app-web'e ulaşır (`make security-check` 2 ve 7 doğrular; ayrıntı MIMARI-SOZLESME §6).
- **Toolchain imajı:** `mcr.microsoft.com/playwright:v<.playwright-version>-noble@sha256:…`; Playwright sürümü tek kaynaktan, uyuşmazlıkta build ve healthcheck başarısız.
- **Başlatma sırası:** `depends_on: condition: service_healthy`; `make up` = önkoşul kontrolü + `docker compose up -d --build --wait`.
- **Kaynak sınırları:** toplam ≤ ~9,6 GB (test-runner 3 GB, toolchain-worker ve MCP 2'şer GB, postgres 1 GB); Playwright içeren servislerde `shm_size: 1gb`.
- **Sabitleme:** tüm dış imajlar digest ile; Python `uv.lock`, Node `package-lock.json` + `npm ci --ignore-scripts`.

**Make hedefleri (F0):** `env` · `up` · `status` · `seed` · `reset` · `export-audit` · `security-check` · `prune` · `logs` · `down`. Sonraki özelliklerde eklenecekler: `seed STEP=n`, `break` (F1/F4).

**`make reset`:** önce `make export-audit` (JSONL + sha256 bütünlük özeti; imza ürün fazında, karar §0-23); başarısızsa hiçbir şey silinmez. Ardından yalnızca Postgres volume'ü silinir ve ortam yeniden başlatılır. Sonraki özelliklerde eklenecekler: `tp/*` branch'leri silinir, açık PR'lar kapatılır; `main`, `demo-admin` kimliğiyle (ruleset bypass) `demo-baseline` etiketine revert commit ile döner; Jira'da `project = TPD AND labels = tp-demo` kayıtları silinir; demo verisi yüklenir.

---

## 12. Ölçüm

| Ölçü | Tanım | Brief kapısı |
|---|---|---|
| Case kabul oranı | "Küçük düzeltmeyle" onaylanan / üretilen case. **Küçük düzeltme:** alan bazlı normalize karakter düzenleme mesafesi ≤ 0,15 **ve** beklenen sonuç anlamca değişmemiş (öneri; onay bekliyor, §19) | ≥ %70 |
| Script ilk review başarısı | İnsan review'unda değişiklik istenmeden kabul edilen ve CI'da geçen / üretilen script. **pass@1** (yerel düzeltme turu öncesi) ve **düzeltme sonrası** ayrı raporlanır | ≥ %60 |
| Triage doğruluğu | İnsanla eşleşen sınıf / örneklem; kural ve LLM kararları ayrı | Faz 3 |
| Hazırlık süresi | Story başına AI + review süresi (canlı ölçülür) ile manuel baz değer yan yana. **Baz değer:** İsmail, 4 demo story'si için manuel case hazırlama süresini F0 haftasında ölçer; ortalama demoda sayacın yanında gösterilir | %30–50 |
| AI maliyeti | İş akışı başına token ve USD | Raporlanır |

**Case üretimi v3 ölçüleri (specs/011 §4.9; `case-metrics` ve `case-summary`):**

| Ölçü | Tanım |
|---|---|
| Teknik dağılımı | Güncel case'lerde tekniğe göre sayım (`teknik_dagilimi`; bir case birden çok tekniğe sayılabilir) |
| Readiness dağılımı | `ready` / `assumption_dependent` / `blocked` sayımı (`readiness_dagilimi`; eski case `ready`) |
| Gereksinim kapsamı | En az bir güncel case'in atıf yaptığı AC / toplam AC (`kapsam_oranlari.gereksinim_kapsami`) |
| Öğe (bölüm) kapsamı | Bir case'in `covers`'ında yer alan kapsam öğesi / toplam öğe (`oge_kapsami`) |
| Negatif karar kapsamı | Negatif kapsam kararı olan geçersiz öğe / toplam geçersiz öğe (`negatif_karar_kapsami`) |
| Review skoru · denetim kararı · asistan denetimi | P8 skoru, P9 karar dağılımı, asistanda engel/uyarı oranı (dalga 2) |

Belgedeki başlangıç hedefleri (ör. öğe kapsamı, negatif karar kapsamı eşikleri) **ekip hedefidir,
standart değildir**: gösterilir, kod kapısı (eşik) yapılmaz.

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
| Ortak kimlik (§8.14) | Yalnız `aiprobe`/`both`: sunucudan sunucuya Google ID token'lı iki çağrı; tarayıcıdan gelen kimlik iddiasına güvenilmez; devir kodu tek kullanımlık ve `state`'e bağlı; `__Host-` çerezler; on-prem `local` |
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

### 3 haftalık demo planı (karar §0-24)

**Tüm akış canlı (14 adım + tutarlılık denetimi + rakip analizi eklemeleri).** Üç hat paralel; Claude Code her hatta kod üretiminde kullanılır. Her haftanın sonunda Cengizhan Bey'e ara demo.

| Hafta | Hat A — Gökhan (çekirdek, Jira, portal) | Hat B — Hakan (uygulama, test, CI, Sauce) | Hat C — İsmail (AI) | Hafta sonu ara demo |
|---|---|---|---|---|
| **1** | F0: repo, Compose, `make up`; Postgres şeması, durum makinesi; Rovo okuma; Jira yazma (yorum, etiket, açıklama/AC güncelleme, Test issue); PO etiketi sorgulama; portal: story, ön inceleme + tutarlılık bulguları, case review, yayın önizlemesi; serbest metin gereksinim girişi | F1: örnek uygulama + page object'ler + kırılma bayrakları; uygulama veritabanı + salt okuma rolü + bilerek konan doküman uyumsuzlukları; toolchain imajı; CI iskeleti (PR, push) | Model geçidi (Claude, şema doğrulama, kayıt); ön inceleme + **tutarlılık denetimi ajanı** (GitHub MCP read-only + `db_query`) + kanıt doğrulayıcı; case üretimi | **Demo-A:** Jira story → tutarlılık denetimi (kod/veri) → doküman düzeltme → PO teyidi → AI case → QA onayı → Jira; Claude Code kanalı |
| **2** | `submit_draft_cases` + `publish_test_cases` (Claude Code); test yönetimi adaptör arayüzü + **Xray Cloud**; sonuç alma (JUnit XML); "kırarak doğrula" ve "deploy" düğmeleri | CI tetikleri (gece, deploy), ruleset; JUnit + Allure; **Sauce Labs** job'u + Sauce Connect; **erişilebilirlik denetimi**; kasıtlı kırma (a) | Kod üretimi: Playwright MCP doğrulama + eşleme + şablon; yerel kontrol; PR akışı | **Demo-B:** onaylı case → kod PR → review + kırarak doğrulama → merge → CI (yerel + Sauce) → JUnit/Allure |
| **3** | **Kontrol Kulesi**; testçi kayıt açma ekranı + `publish_bug`; uçtan uca entegrasyon | Locator kırılması (`make break`) ve onarım PR akışı CI'da; hazır PR ve Sauce linkleri (yedek) | Triage: kurallar + JQL mükerrer + bug taslağı; locator onarımı + AST koruması; REPLAY kayıtları | **Tam demo provası ×3** (temiz sıfırlamayla); yedek video |

**Haftalık kontrol:** her ara demoda bir sonraki haftanın kapsamı gözden geçirilir; takılan iş yedeğiyle (hazır PR, REPLAY, önceden koşmuş Sauce linki) gösterilir ve bu açıkça söylenir.
**Bağımlılıklar:** Jira sitesi + Rovo token ve uygulama veritabanı 1. haftanın başında; Sauce kimliği ve Xray deneme sürümü 2. haftanın başında hazır olmalı.
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

## 20.2 Test kalite doğrulama (012)

Ayrıntı ve kararlar: [specs/012-test-kalite-dogrulama/ANALIZ.md](../specs/012-test-kalite-dogrulama/ANALIZ.md)
(birleştirme notları §12, review kararları ve güncel sözleşme §13, `feat/case-gen-v3` ile
birleştirme planı §14). AI'ın ürettiği testlerin doğru şeyi beklediğini ve hata yakaladığını
kanıtlayan beş parça; hepsi Postgres'te, okuma anında hesaplanır, canlı model REPLAY'dir:

| Parça | Ne yapar | Kod |
|---|---|---|
| F1 karar tablosu | AI story'den taslak çıkarır (`decision_table_draft`; yalnız onaylı gereksinim metni), analist düzenler, PO görülen hash'le onaylar; gereksinim değişince tablo bayat. Case'in beklenen değerleri `case_facts` ile alıntısıyla çıkarılır, LLM'siz doğrulanır ve sınırlı ifade diliyle hesaplanan tabloyla karşılaştırılır. Onay kapısı: yüksek riskli uyuşmazlık 422 `oracle_uyumsuz`, kontrol edilemeyen 422 `oracle_kontrolsuz` (ikisi de gerekçeli istisnayla; istisna formu "Case doğru" / "Tablo yanlış" iki yol), `kismen` yalnız uyarı, kontrol bitmemişse 409 `oracle_bekleniyor` | `features/karar_tablosu`, `features/oracle` |
| F2 triage ayrımı | Assertion farkı onaylı tabloyla karşılaştırılır: beklenti = tablo → `product_defect` (`karar_tablosu_uyumlu`); gerçekleşen = tablo → `test_maintenance/beklenti` (bug taslağı ve locator onarımı yok) | `features/triage/rules.py` |
| F3 ekilmiş hata koşusu | Demo uygulamaya test kipinde bayi bazında hata konur, onaylı suite koşar; hata yakalama oranı = yakalanan / (yakalanan + kaçan); yalnız temelde yeşil testin assertion kırmızısı sayılır, ana oran yalnız üretilen testlerden (el yazısı suite ayrı) | `features/hata_kosusu`, `demo-app/api/.../faults.py` |
| F4 beklenti doğruluğu | AI içeriğinin (insan düzeltmesinden önce) tabloyla uyuşma oranı; Kontrol Kulesi ve case metrikleri | `features/oracle/metrik.py` |
| F5 ilişki tabanlı ek case | PO onaylı metamorfik ilişkiden deterministik türetilen `draft` case (metriğe girmez) | `features/metamorfik` |

Bağımsızlık: case üretim girdisi tablo taşımaz; değer çıkarma tablonun yalnız kolonlarını görür;
kontrol case içeriğini değiştirmez.

---

## 21. Spec Kit planı

1. `specify init . --integration claude` (repo kökünde).
2. `/speckit-constitution` ← §3 (10 kural) + §5 (tehdit kontrolleri) + "AI yalnızca core-worker'da" + "Postgres tek doğruluk kaynağı".
3. Özellikler sırasıyla: `001-foundation` (F0) → `002-core` (F2a) → `003-requirement-to-cases` (F3) → `004-demo-app-and-ci` (F1) → `005-cases-to-code` (F4) → `006-failure-to-fix` (F5) → `007-demo-readiness` (F6). Her biri `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement` → `/speckit-converge`.
