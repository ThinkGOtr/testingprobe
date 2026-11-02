# Canlı platform demo senaryosu — testing-probe.antreklabs.com

Toplantıda **canlı platform** üzerinden yapılacak sunumun tık tık senaryosu. Her adımda: hangi
ekran, neye tıklanır, ne yazılır, ekranda ne görülür, ne söylenir.

- Süre: **~30 dk** sunum + 10 dk soru. Zaman darsa §9'daki atlama listesi.
- Yerel (127.0.0.1) kurulum için ayrıntılı sunucu metni: [DEMO-AKISI.md](DEMO-AKISI.md). Bu belge
  onun **canlı ortam (GCP + gerçek Jira/Xray/GitHub)** uyarlamasıdır; ikisi çelişirse ürünün
  ekranda gösterdiği doğrudur.

## 0. Canlı ortamda ne var?

| Parça | Canlıda | Adres |
|---|---|---|
| Review portal | GCP VM `tp-demo` | https://testing-probe.antreklabs.com |
| Test edilen uygulama (Bayi Sipariş Portalı) | aynı VM | https://bayi.testing-probe.antreklabs.com |
| Jira | **Gerçek Jira Cloud**, proje `TPD` | https://iyzitrace.atlassian.net/browse/TPD-1 |
| Test yönetimi | **Xray Cloud** (adımlı Manual Test) | Jira içinde, TPD projesi |
| Git + PR + CI | **GitHub** + **GitHub Actions** | https://github.com/ThinkGOtr/testingprobe-demo-app |
| Cihaz bulutu | **Sauce Labs** job'u (Actions içinde) | koşu detayındaki Sauce bağlantısı |
| Model | **REPLAY** (küratörlü golden kayıtlar) | portalda her AI çıktısında REPLAY rozeti |

> **Altın kurallar (sunum boyunca)**
> 1. **"REPLAY" her AI adımında söylenir.** Doğru cümle: *"Bu adımın AI çıktısı REPLAY: önceden
>    hazırlanmış, girdisi doğrulanmış bir kayıttan geliyor. Kayıt, şema doğrulama, kanıt doğrulama
>    ve insan kapıları canlıdakiyle aynı kod yolundan geçiyor."*
> 2. **Ölçülmemiş sayı söylenmez.** Kazanç oranı ekranda "ölçülmedi" diyorsa sen de öyle söyle.
> 3. **İnsan onayı hiçbir yerde terminalden/API'den verilmez**; her onay ilgili rolün ekranından.
> 4. **Ekranda sır yok.** `.env`, parola, token gösterilmez; parolalar parola yöneticisinden.

---

## 1. Hazırlık

### 1.1 Toplantıdan 1 gün önce

| # | Ne | Nasıl | Beklenen |
|---|---|---|---|
| 1 | VM açık mı | Mac: `gcloud compute instances list --project testingprobe` | `tp-demo RUNNING` (kapalıysa `gcloud compute instances start tp-demo --zone europe-west3-a --project testingprobe`) |
| 2 | **Tek hesap test kipini kapat** | VM `.env`: `TP_TEST_TEK_HESAP=0`; `JIRA_PO_ACCOUNT_IDS`'te **yalnızca PO'nun** (ör. Cengizhan) accountId'si → `make up` | `make status`'ta "UYARI: TP_TEST_TEK_HESAP" satırı **yok**. Bugün değer `1` — kapatılmazsa PO onayını ürün hesabı da verebilir, bu sunumda söylediğimiz kuralı çiğner |
| 3 | PO hesabı hazır | PO kendi Atlassian hesabıyla iyzitrace.atlassian.net'e girebiliyor, TPD'de etiket ekleyebiliyor | PO ürünün okuma/yazma hesabından **farklı** bir hesap olmalı |
| 4 | Sauce'u push'tan çıkar | Mac: `gh variable set SAUCE_TETIKLER --repo ThinkGOtr/testingprobe-demo-app --body deploy,nightly` | Push koşuları ~11 dk Sauce beklemez; Sauce "Deploy tetikle"de görünür. Sunumdan sonra `gh variable delete SAUCE_TETIKLER --repo ThinkGOtr/testingprobe-demo-app` |
| 5 | Tam prova | Bu belgenin §3–§8'i baştan sona, kronometreyle | Her adımın gerçek süresini not al |
| 6 | Yedek video | `make demo-prova UI=1` (VM ya da yerel) | Aksaklıkta açılacak kayıt sunum makinesinde |

### 1.2 Toplantıdan 30 dk önce (VM'de)

```bash
gcloud compute ssh tp-demo --project testingprobe --zone europe-west3-a --tunnel-through-iap
cd /opt/testingprobe
make reset && make seed && make demo-reset   # reset gerçek Jira temizlik planını gösterir → "e"
                                             # (TPD-1..7 yorumları da silinir; bağlantılar kalır)
make status                                  # hepsi healthy, son satır "Model kipi: REPLAY"
make security-check                          # Özet: 10/10
systemctl is-active tp-demo-web-sync         # active (locator demosu için şart)
```

Sonra portalda **sunucu** ile **Koşular** ekranını aç: `make demo-reset`'in tetiklediği GitHub
koşusu **yeşil** bitmiş olmalı. Yeşil temel koşu yoksa "Locator'ı kır" çalışmaz.

### 1.3 Tarayıcı profilleri

Portal oturumu tarayıcı başına tek kullanıcı. Chrome'da her rol için **ayrı profil** aç, hepsi aynı
boyut/konumda; geçiş Cmd + \` ile. Zoom %125.

| Profil | Açık sekmeler | Giriş |
|---|---|---|
| **Sunucu** | Portal → Demo yol haritası, Kontrol Kulesi, Koşular, Demo kontrolleri, Denetim | portal `sunucu` |
| **Analist** | Portal → Gereksinimler · Jira `TPD-1` | portal `analist` |
| **PO** | Jira `https://iyzitrace.atlassian.net/browse/TPD-1` | PO'nun Atlassian hesabı |
| **Mühendis** | Portal → Kod üretimi · GitHub demo reposu → Pull requests · Bayi uygulaması | portal `muhendis`; GitHub demo-admin hesabı; bayi `bayi1` / `Demo123!` |
| **Testçi** | Portal → Bug taslakları · Jira `TPD-5` | portal `testci` |

Portal parolaları: VM `.env` → `SEED_USER_PASSWORD` (parola yöneticisinden yapıştır).
Portalın sağ üstündeki **Canlı olaylar** göstergesi yeşil olmalı.

### 1.4 Kritik kararlar (ezberle — yanlış tık sonraki "vay" anlarını siler)

| Bulgu | Konu | Karar |
|---|---|---|
| F1 | AC3 ↔ AC6 çelişkisi | **Dokümanı düzelt** |
| F2 | Kampanya kodu (`adet // 6`) | **Kod/veri hatalı** |
| F3 | Minimum tutar (veride 750,00) | **Dokümanı düzelt** |
| F4 | Kredi limiti uyarısı kodda yok | **Kod/veri hatalı** |

Bug taslaklarında: **C3 → TPD-5'e bağla**, **F2 → TPD-5'e bağla**, **F4 → Onayla ve Jira'da aç**,
**C2 kırma koşusu taslağı → dokunma**.

---

## 2. Akışın haritası

```
Açılış       Demo yol haritası (0/14)
Bölüm A      1 Jira'dan çek → 2 Ön inceleme (kod+veri) → 3 PO onayı (Jira) → 4 Case üret/onayla/Xray'e yayınla
Bölüm B      5 Kod üret (ajan + şablon) → 6 Kırarak doğrula → 7 GitHub PR + merge
             → 8 GitHub Actions (push/deploy/gece) → 9 Sauce → 10 Raporlar → 11 Kontrol Kulesi
Bakım        L1 Locator'ı kır → L2 kırmızı koşu → L3 tek satırlık onarım PR'ı → L4 yeşil
Bölüm C      12 Triage → 13 Testçi kararı → 14 Jira'da Bug / mevcut kayda bağlama
Kapanış      Yol haritası 14/14 · Denetim zinciri
```

---

## 3. Açılış (2 dk)

**Profil: Sunucu** → sol menü **Demo yol haritası**

- Görülen: 14 adımlı akış, sayaç **0/14 tamam**, model kipi **REPLAY**, prompt değerlendirme durumu.
  (0/14 görmüyorsan ortam temiz değil — açılışı yol haritasız yap.)

**Söyle:**
> "Bir Jira story'sinden başlayıp; AI'ın dokümanı uygulamanın koduyla ve verisiyle
> karşılaştırmasına, insan onaylı test case'lere, AI olmadan koşan Playwright otomasyonuna, GitHub
> PR'ına, CI'a, Kontrol Kulesi'ne ve testçinin onayladığı Jira hata kaydına kadar uçtan uca
> gideceğiz. Mor adımlar AI taslağı, yeşil adımlar insan kapısı. Hiçbir AI çıktısı insan onayı
> olmadan test varlığına dönüşmüyor. Bugün her şey gerçek: gerçek Jira, Xray, GitHub, GitHub
> Actions. Tek fark: AI çıktıları REPLAY kipinde, ekranda her yerde bu rozeti göreceksiniz."

Kısaca **Bayi uygulamasını** göster (Mühendis profili → `https://bayi.testing-probe.antreklabs.com`,
`bayi1` / `Demo123!` ile giriş, bir ürünü sepete ekle):
> "Test edeceğimiz uygulama bu: bayilerin sipariş verdiği bir portal. Kampanya, minimum tutar,
> kredi limiti gibi iş kuralları var."

---

## 4. Bölüm A — Gereksinimden yayınlanmış test case'e (8 dk)

### Adım 1 · Jira'dan çek (1 dk)

**Profil: Analist** → önce Jira sekmesinde **TPD-1 "Kampanyalı sepet ve sipariş onayı"**nı göster
(açıklama + 6 kabul kriteri). Sonra portal:

1. Sol menü **Gereksinimler**
2. **"Jira'dan çek"** düğmesi
3. Listede **TPD-1**'e tıkla

- Görülen: TPD-1..TPD-4 listesi; TPD-1'in açıklaması ve 6 AC'si portalda.

**Söyle:** "Analistin dokümanı olduğu gibi. Ürün Jira'yı salt okur; yazma ayrı, yetkisi kısıtlı bir
hesapla ve yalnızca insan onaylı içerikle yapılır."

### Adım 2 · Ön inceleme ve kod/veri tutarlılık denetimi (3 dk)

1. TPD-1 detayında **"Ön incelemeyi başlat"**
2. 4 bulgu kartı gelir:
   - **F1** AC3 ↔ AC6 çelişkisi
   - **F2** kampanya kuralı — kanıt `campaign.py:23` → `return adet // 6`
   - **F3** minimum tutar — kanıt SQL: `ayar.min_siparis_tutari = 750.00`
   - **F4** kredi limiti uyarısı kodda yok
3. Bir kartın **kanıtını** aç (dosya:satır / SQL + sonuç).

**Söyle:** "AI dokümanı yalnızca kendi içinde okumadı; uygulamanın **koduyla ve veritabanıyla**
karşılaştırdı, salt okunur. Her bulgunun kanıtı var ve kanıt ekrana gelmeden önce deterministik
olarak yeniden doğrulanıyor — doğrulanamayan bulgu hiç gösterilmez. AI çıktısı REPLAY, kanıt
doğrulaması canlı."

4. Kararları **§1.4 tablosundan okuyarak** ver:
   **F1 → "Dokümanı düzelt"**, **F2 → "Kod/veri hatalı"**, **F3 → "Dokümanı düzelt"**,
   **F4 → "Kod/veri hatalı"**
5. **"Düzeltmeleri Jira'ya yaz"**

- Görülen: önerilen metin farkı (AC3 → "Kampanyasız siparişlerde minimum sipariş tutarı 750,00 TL…");
  "Belge son hal yapıldı; PO teyidi bekleniyor."
6. **Jira sekmesine geç** (TPD-1'i yenile): açıklama güncellenmiş, `🤖 AI Testing Probe:` ile
   başlayan PO soru yorumu, `tp-po-pending` etiketi.

**Söyle:** "Analist her bulguya karar verdi: doküman mı yanlış, kod mu? 'Kod hatalı' dediği iki
bulgu için sistem bug taslağı açtı — birazdan testçinin önüne gelecek. Jira'ya yazılan içerik,
onaylanan içeriğin hash'iyle bağlı."

### Adım 3 · PO onayı — Jira'da (1,5 dk)

**Profil: PO** → Jira TPD-1

1. Ürünün soru yorumunu oku (PO @bahsedilmiş, bildirim de gitti).
2. Yoruma kısa bir cevap yaz, ör.: *"Kampanyasız siparişte alt limit 750 TL, onaylıyorum."*
3. Etiketlere **`tp-po-approved`** ekle.
4. **Analist** profiline dön → ≤15 sn içinde TPD-1'de **PO onaylı** rozeti (gelmezse sayfayı yenile).

**Söyle:** "İnsan kapısı Jira'nın içinde: PO kendi aracında cevaplıyor ve onaylıyor. Ürün etiketi
koyanın gerçekten izinli PO olduğunu Jira changelog'undan doğruluyor — ürünün kendi hesabının
koyduğu etiket onay sayılmaz, hatta geri kaldırılır. Onaydan sonra içerik değişirse onay düşer."

### Adım 4 · Case üret → insan onayı → Xray'e yayınla (2,5 dk)

**Profil: Analist**

1. TPD-1 → **"Case üret"** → 10 case kartı (pozitif/negatif/sınır), her biri bir AC'ye bağlı.
   **C3** = "6 adet kampanyalı üründe bedava ürün verilmez" — bunu göster, sonra lazım olacak.
2. Sol menü **Case review** → birkaç case'i **"Onayla"**; birinde **"Düzelt"** → küçük bir metin
   değişikliği → onay; kalanları onayla.
   - Görülen: sayaç, **kabul oranı**, düzeltmede alan bazlı fark.
3. Sol menü **Yayın** → **"Yayın önizleme"** (hedef: `xray`) → **"Seçilenleri yayınla (n)"**
4. **Jira sekmesi** → TPD-1'e `Test` bağlantısıyla bağlı yeni Test issue'ları; birini aç → Xray'de
   **adımlı Manual Test**.

**Söyle:** "Case'ler AC'lere ve PO cevabına bağlı; şemaya uymayan çıktı reddedilir. Her insan kararı
ölçülüyor: kabul oranı, ret nedeni, düzeltme büyüklüğü. Yayın önce kuru çalışıyor, yalnızca onaylı
ve onaydan sonra değişmemiş case yazılıyor; ikinci kez basmak ikinci kayıt açmaz."

*İsteğe bağlı (1 dk):* **Claude Code kanalı** → "8 saatlik token oluştur" → "Aynı akışı IDE'den de
besleyebilirsiniz; Claude Code taslak gönderir, onay yine burada insanda."

---

## 5. Bölüm B — Onaylı case'ten korumalı main'e (10 dk)

### Adım 5 · Kod üretimi (2,5 dk)

**Profil: Mühendis** → sol menü **Kod üretimi**

1. **C1** (sepet sayacı), **C2** (7 adet), **C3** (6 adet), **C5** (750,00 TL) seçili olsun.
2. **"Seçilenler için kod üret (4)"**
3. Ajan adımları canlı akar: navigate → snapshot → click → generate_locator, her adımın ekran
   görüntüsüyle; sonra adım → page object eşleme tablosu, şablondan üretilen TypeScript ve yerel
   kontrol: `tsc ✓ eslint ✓ AST ✓`, Playwright `--repeat-each=3`.

**Söyle (beklerken):** "Model TypeScript yazmıyor. Ajan her adımı gerçek uygulamada — az önce
gösterdiğim bayi portalında — doğruluyor ve page object kütüphanesine eşliyor; kod bu eşlemeden
şablonla üretiliyor, assertion değerleri onaylı case metninden geliyor. Tarayıcı adımları şu an
gerçekten koşuyor; modelin kararı REPLAY."

### Adım 5b · Defect adayı anı (0,5 dk) — **sunumun en önemli anı**

1. **C3** script'ini aç.
- Görülen: **Defect adayı** — `beklenen "0", gerçekleşen "1" (3/3 tekrar)`; PR **açılmadı**.

**Söyle:** "İşte değer burada. Test, dokümandaki doğru davranışı bekliyor; bugünkü kod onu
karşılamıyor. Ürün testi 'yeşile boyamaya' çalışmıyor — bunu ürün hatası adayı olarak insana
getiriyor. Adım 2'de analistin 'kod hatalı' dediği F2 bulgusu buydu."

### Adım 6 · Kırarak doğrula (2 dk)

1. **C2** script'i → **"Kırarak doğrula"**
- Görülen zaman çizelgesi: bayraksız **yeşil** → `BREAK_CAMPAIGN=1` **kırmızı** → bayrak kaldırıldı
  **yeşil** = **"Test hata yakalıyor ✓"**
2. **C1** ve **C5** için aynısı → "Kırma etkilemedi · kabul gerekli".

**Söyle (C2 koşarken, ~1,5 dk):** "Yeşil test yetmez; testin hatayı yakaladığını kanıtlıyoruz.
Uygulamada kampanyayı bilerek bozuyoruz, test kırmızıya dönmeli. Kampanya dışı testlerde kırılma
etki etmez — ürün bunu gizlemiyor, merge için açık insan kabulü istiyor."

### Adım 7 · GitHub PR ve korumalı main'e merge (2,5 dk)

1. **GitHub sekmesi** → demo reposu → **Pull requests**: botun (`antreklabs-testing-probe[bot]`)
   açtığı PR'ları göster; C2 PR'ında diff ve PR gövdesi (case bağlantısı, eşleme tablosu, CI sonucu
   yorumu).
2. GitHub'da C2 PR'ına **Approve**.
3. Portal → C2 PR'ı → merge kapısını göster (zorunlu check yeşil + insan onayı) → **"Merge et"**.
   - Görülen: PR **Birleşti**; main'e push koşusu otomatik başlar.
4. Zaman varsa C1/C5'i de kabul notu yazarak merge et. **Dikkat:** her merge main'i ilerletir;
   kalan PR'ların CI'ı yeniden koşar (~1,5 dk) ve GitHub onayları düşer → yeniden **Approve** gerekir.
   Vakit yoksa yalnız C2 yeter.

**Söyle:** "Ana dal korumalı: doğrudan push yok, bot merge edemez; CI yeşil ve insan onayı olmadan
merge yok — bu GitHub ruleset'i. Ve önemli: **CI'da AI yok.** Model anahtarı, MCP, ajan yok;
yalnızca onaylı, deterministik test kodu koşuyor."

### Adım 8 · CI tetikleri (1 dk)

**Profil: Sunucu** → sol menü **Koşular**

1. Push koşusunu göster (GitHub Actions'tan canlı akıyor).
2. **"Deploy tetikle"** (vakit varsa **"Gece koşusu"**).
3. İstersen GitHub → **Actions** sekmesinde aynı koşuyu göster.

**Söyle:** "Tetikler: PR, main'e push, gece ve deploy olayı — hepsi aynı deterministik paket,
GitHub Actions'ta."

### Adım 9 · Sauce Labs (0,5 dk)

Deploy koşusunun detayında **Sauce** job'u ve sonuç bağlantısı.
**Söyle:** "Aynı testler Sauce Labs'in bulut tarayıcılarında da koşuyor; sonuç bağlantısı koşuya
yazılıyor." (Sauce job'u tamamlanmadıysa: "Sauce tek eşzamanlı oturumla ~10 dk sürüyor, sonucu
kapanışta göstereceğim.")

### Adım 10 · Raporlar (0,5 dk, isteğe bağlı)

Koşu detayı → **Allure raporu** / Playwright HTML / JUnit XML.
**Söyle:** "Standart çıktılar; mevcut raporlama araçlarınıza olduğu gibi girer."

### Adım 11 · Kontrol Kulesi (1 dk)

Sol menü **Kontrol Kulesi** → gez: son koşular, geçme oranı, flaky testler, alan karnesi, açık defect
adayı, AI katkısı (kabul oranı, review süresi).

**Söyle:** "Tek ekranda kalite. Her KPI'nın hangi veriden ve hangi pencereden hesaplandığı yazıyor.
Kazanç oranını yalnızca manuel baz süresi **ölçülmüş** story'lerde gösteriyoruz; ölçüm yoksa ekran
'ölçülmedi' diyor — uydurma rakam yok. REPLAY'de AI süresi ~0, gördüğünüz süre yalnızca insan review
süresi."

---

## 6. Bakım — locator kırılması ve tek satırlık onarım (4 dk)

> **Zamanlama:** Adım 7–8'in koşuları **bittikten sonra** L1'i başlat, sonra hemen Bölüm C'ye geç;
> kırmızı koşu Bölüm C sırasında oluşur (GitHub Actions birkaç dakika sürer). Push koşusu bitmeden
> kırma: koşu ortasında uygulama değişirse sonuçlar `environment` sınıflanır, onarım önerilmez.

### L1 · Locator'ı kır (0,5 dk)

**Profil: Sunucu** → sol menü **Demo kontrolleri** → **"Locator'ı kır"** → **"Evet, locator'ı kır"**

- Görülen: Demo olay günlüğü — GitHub'da `demo/break-locator-…` PR'ı açıldı ve insan kimliğiyle
  merge edildi (`add-to-cart` → `cart-add`, rol ve ad aynı), bayi uygulaması yeniden derleniyor,
  push koşusu başladı. GitHub'da o PR'ı göster: fark tek satır `data-testid`.

**Söyle:** "Bir geliştirici butonun test kimliğini değiştirdi — işlev aynı. Klasik otomasyonda bu,
sabah onlarca kırmızı test demek."

→ **Şimdi Bölüm C'ye geç (§7)**, sonra L2'ye dön.

### L2 · Kırmızı koşu (0,5 dk)

**Profil: Sunucu** → **Koşular** → kırmızı koşu

- Görülen: çok sayıda kırmızı; hepsi **test_maintenance / locator** (`catalog.addToCart`).
  Ekrandaki sayıyı oku (merge ettiğin case sayısına göre değişir).

**Söyle:** "Ürün kırmızıları tek tek bug açmıyor. Kural, elemanın niyetinin — rol + ad — sayfada
durduğunu ve tek bir farklı testId'ye çözüldüğünü kanıtlıyor: bu ürün hatası değil, test bakımı."

### L3 · Onarım PR'ı (1,5 dk)

**Profil: Mühendis** → kırmızı hatalardan biri → **"Onarım PR'ı aç"**

- Görülen: yalnızca `e2e/pages/catalog/locators.ts` içinde **1 satır** testId; AST koruması (onarım
  modu) ✓; tam paket yerel kontrol ✓; PR gövdesinde sinyaller, diff, aria doğrulaması,
  "AI üretimi: hayır"; tüm kardeş hatalar aynı PR'ı paylaşır. GitHub'da PR'ı göster.

**Söyle:** "Onarım deterministik, modelsiz. Yalnızca locator değeri değişebilir; test dosyası ve
assertion asla otomatik değişmez — AST koruması bunu hem burada hem CI'da zorunlu kılıyor. Beklenen
sonuçtaki her sapma defect adayıdır, onarılmaz."

### L4 · Merge → yeşil (1,5 dk)

GitHub'da **Approve** → portalda **"Merge et"** → push koşusu → **tamamı yeşil**.

**Söyle:** "Tek insan onayıyla bütün kırmızılar yeşile döndü; değişiklik tek satır, gözden geçirmesi
saniyeler." (CI beklerken **Denetim** ekranını göster — §8.)

---

## 7. Bölüm C — Başarısızlıktan Jira kaydına (4 dk)

### Adım 12 · Triage (1,5 dk)

**Profil: Testçi** (ya da Mühendis) → C3'ün triage bağlantısı / **Bug taslakları** → C3

- Görülen: sınıf **product_defect**, "Karar kaynağı: deterministik kural"; eşleşen sinyaller
  (assertion farkı, eleman bulundu, sayfa yapısı beklenen, tutarlı tekrar); hazır bug taslağı;
  Jira'da benzer açık bug araması → **TPD-5** "Kampanya indirimi sepette yanlış hesaplanıyor",
  benzerlik **high**, öneri **bağla**.

**Söyle:** "Önce deterministik kurallar: kuralın verebildiği kararı modele bırakmıyoruz. Model
yalnızca taslağı yazıyor ve mükerrer adayları sıralıyor — o da REPLAY. Uydurma aday ya da gerçek
değeri içermeyen taslak otomatik reddedilir."

### Adım 13 · Testçi kararı (1,5 dk)

**Bug taslakları** listesinde dört taslak var. Sırayla:

1. **C3** taslağı → **"TPD-5 kaydına bağla"**
2. **F2** (kampanya, Bölüm A'dan) → **"TPD-5 kaydına bağla"**
3. **F4** (kredi limiti) → **"Onayla ve Jira'da aç"**
4. **C2 kırma koşusu** taslağı → **dokunma** (bilerek bozduğumuz koşudan geldi)

**Söyle:** "Kayıt açma kararı testçinin. Mükerrerse mevcut kayda kanıt eklenir, yeni kayıt açılmaz.
Analistin dokümandan bulduğu hata ile testin yakaladığı hata **aynı Jira kaydında buluştu.**"

### Adım 14 · Jira'da sonuç (1 dk)

**Jira sekmeleri:**

- **TPD-5**: iki kanıt yorumu (C3 ve F2: beklenen/gerçekleşen, kanıt bağlantıları, denetim zinciri
  başı), `Relates` TPD-1, C3'ün Test issue'suna bağlantı; mühendis + testçi @bahsedilmiş.
- **Yeni Bug** (F4): `AI-generated` etiketli, açıklaması `🤖 AI Testing Probe:` ile başlıyor,
  `Relates` TPD-1.

**Söyle:** "Kayıt story'ye ve teste bağlı, kanıt bağlantılı. Kim onayladı, hangi içerik hash'i,
hangi zincir başı — hepsi kayıtta."

→ **L2'ye dön (§6).**

---

## 8. Kapanış (2 dk)

1. **Sunucu** → **Demo yol haritası**: adımlar işaretli, REPLAY rozeti. Sayaçta ne yazıyorsa onu oku.
   > "Açılışta 0'dı; şimdi uçtan uca tamam — ve hangi adımın REPLAY olduğunu ekran kendisi
   > söylüyor." (Bilinen kozmetik sorun: TPD-1 adım göstergesi 5. adımı "sıradaki" gösterebilir;
   > işaret etme, sorulursa "gösterge hatası, kayıt tamam".)
2. **Sunucu** → **Denetim** → zincir doğrulaması (**verify**) yeşil.
   > "Her AI çağrısı, araç çağrısı, onay ve ret kayıtta. Kayıtlar append-only ve hash zinciriyle
   > korunuyor; zincirin başı Jira yorumlarına ve PR açıklamalarına sabitleniyor. **AI üretti, her
   > adımda insan onayladı.**"
3. (Sauce job'u o ana kadar bittiyse) deploy koşusundaki Sauce sonucunu göster.

Sunum sonrası (VM): `make export-audit`; Sauce değişkenini geri al (§1.1 #4).

---

## 9. Zaman darsa atla (sırayla)

1. Claude Code kanalı dakikası
2. Adım 10 (raporlar) — yalnız soru gelirse
3. Adım 8'de "Gece koşusu"
4. Adım 7'de C1/C5 merge'ü — yalnız C2
5. Adım 4'te "Düzelt" gösterimi
6. Adım 11 tek cümleye
7. L3'te PR gövdesi gezintisi — yalnız 1 satırlık diff

**Atlanmayacaklar:** REPLAY cümlesi, insan kapıları (2, 3, 4, 7, 13, L4), **5b defect adayı anı**,
**F2 + C3 → TPD-5** buluşması.

---

## 10. Aksaklık rehberi

| Belirti | Ne yap |
|---|---|
| Portal açılmıyor / 502 | VM'de `make status`; tek servis düştüyse `make up` (veriyi korur) |
| "Canlı olaylar" kırmızı | Sayfayı yenile; oturum düştüyse yeniden giriş |
| Jira'dan çek boş | Jira'da TPD-1..4 var mı; "Jira'dan çek"i tekrar; olmazsa yedek video |
| REPLAY-MISS rozeti | Dürüstçe söyle: "bu adımın girdisi kayıtla eşleşmedi, ürün bunu gizlemiyor"; yedek video |
| PO onayı portala gelmiyor | 30 sn bekle, sayfayı yenile. Etiket kendiliğinden silindiyse etiketi PO değil ürün hesabı koymuştur (doğru davranış) |
| 5b'de defect adayı yok | Adım 2'de F2 yanlışlıkla "Dokümanı düzelt" seçilmiş; söyle, yedek videoya geç |
| GitHub merge kapısı kırmızı | Kalan PR'lar main ilerleyince yeniden CI koşar ve onay düşer: CI bitsin, GitHub'da yeniden Approve |
| GitHub Actions uzun sürüyor | Kontrol Kulesi'ni ya da Denetim'i anlat; koşu bitince devam |
| Locator kırıldı ama bayi uygulaması değişmedi | VM: `systemctl status tp-demo-web-sync`, `journalctl -u tp-demo-web-sync -n 50` |
| "Önce yeşil temel koşu" uyarısı | Yeşil push koşusu yok; Koşular'dan bitmesini bekle |
| Tam çöküş | Yedek video; sunum sonrası `make reset` |

**Sahnede yapılmayacaklar:** `make reset`, `.env` düzenleme, API'den elle onay, `make break Z=1`.

---

## 11. Soru-cevap kopya kâğıdı

| Soru | Kısa cevap |
|---|---|
| **AI yanlış case/kod üretirse?** | Hiçbir AI çıktısı insan onayı olmadan test varlığına dönüşmez; onay içeriğin hash'ine bağlı. Kod modelden değil, doğrulanmış eşlemeden şablonla üretilir; `tsc --strict`, eslint, AST koruması zorunlu. |
| **Bugünkü AI canlı mı?** | Hayır, REPLAY. Canlıya geçiş tek ayar (`TP_MODEL_MODE`); geçmeden her prompt paketi canlı değerlendirme setinden geçmek zorunda (bugün 8 paketten 4'ü değerlendirildi). |
| **Prompt injection?** | Jira, kod, veri, sayfa ve CI log içeriği güvenilmez veri sayılır, içindeki talimat uygulanmaz (TPD-3'te bilerek bir injection cümlesi var). Ajan yalnızca izin listesindeki araçları, tarayıcı yalnızca demo uygulamasını kullanır. |
| **Kodumuz/verimiz dışarı çıkar mı?** | Ürün müşteri ortamında çalışır; kod ve DB'ye yalnızca salt okuma (izinli tablolar, tek `SELECT`, satır/zaman sınırı, maskeli sonuç). |
| **Model nerede çalışır?** | Ürün fazında müşterinin tenant'ında ya da on-prem; model geçidi sağlayıcıdan bağımsız (Anthropic adaptörü çalışıyor, Azure OpenAI adaptörü iskelet). Müşteri verisi eğitimde kullanılmaz. |
| **KVKK?** | Müşteri verisinde model girdisi maskeleme zorunlu (TCKN, IBAN, telefon, e-posta). Demo sentetik veriyle çalıştığı için bugün kapalı — kayıtlı karar. |
| **Kazanç ne kadar?** | Yalnızca ölçtüğümüzü söylüyoruz: kabul oranı ve review süresi ekranda. Hedefler: hazırlıkta %30–50 azalma, case kabulünde ≥ %70, script ilk review başarısında ≥ %60. |
| **Xray / TestRail / Zephyr?** | Test yönetimi bir port: bugün Xray Cloud (adımlı Manual Test); diğerleri aynı arayüzle sonraki fazda. |
| **GitHub dışı (GitLab/Azure DevOps)?** | Forge bir port: bugün yerel forge ve GitHub; diğerleri aynı arayüzle. |
| **Copilot kullanıyoruz?** | Kurallar ve prompt'lar `rules/` altında düz dosya; Copilot/Claude Code kural dosyaları buradan üretilir. IDE kanalından (MCP) taslak gönderilir, onay yine portalda. |
| **Neden bu ortam GCP'de?** | Demo için tek VM; ürün fazında aynı imajlar müşteri ortamına (Azure Container Apps / Kubernetes) kurulur. |
