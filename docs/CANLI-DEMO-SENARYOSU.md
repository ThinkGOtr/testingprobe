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

### Jira'da demonun ihtiyaç duyduğu kayıtlar (TPD projesi)

Yalnızca bu yedi kayıt gerekir; **anahtarları sabittir** (REPLAY kayıtları bunlara bağlı), silinmez:

| Anahtar | Tür | Başlık | Durum | Rolü |
|---|---|---|---|---|
| TPD-1 | Story | Kampanyalı sepet ve sipariş onayı | To Do | Ana senaryo |
| TPD-2 | Story | Sipariş geçmişini tarihe göre filtreleme | To Do | Kabul kriteri olmayan story |
| TPD-3 | Story | Ürün arama | To Do | Bilerek konmuş prompt-injection cümlesi |
| TPD-4 | Story | Bayi girişi | To Do | İkinci küçük story |
| TPD-5 | Bug | Kampanya indirimi sepette yanlış hesaplanıyor | To Do (açık) | Mükerrer aramanın bağladığı kayıt (Bölüm C) |
| TPD-6 | Bug | Sipariş geçmişinde tarih sıralaması ters görünüyor | In Progress | Benzer ama farklı açık bug |
| TPD-7 | Bug | Giriş sayfasında hata mesajı İngilizce görünüyor | Done | Kapalı bug (aday sayılmaz) |

TPD-8 ve sonrası (Test kayıtları, yeni Bug'lar) demo sırasında ürünce açılır; `make reset` onları
kapatır ve kimlik etiketini kaldırır — gerekmezler. Projede ayrıca: Xray (`Test` iş türü), bağlantı
türleri `Test` ve `Relates`, ürünün yazma hesabı ve **ayrı** PO hesabı.

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
| 4 | Sauce tetikleri | Değişiklik yok: Sauce push, deploy ve gece koşularının hepsinde koşar (`SAUCE_TETIKLER` tanımsız). Mac: `gh variable list --repo ThinkGOtr/testingprobe-demo-app` → `SAUCE_TETIKLER` satırı **olmamalı** | Hesap tek eşzamanlı oturum: Sauce job'ları sıraya girer (her biri ~1–11 dk). Merge'lerin push Sauce'u bitmeden tetiklenen deploy'un Sauce'u **bekler** (düşmez) |
| 5 | Tam prova | Bu belgenin §3–§8'i baştan sona, kronometreyle | Her adımın gerçek süresini not al |
| 6 | Yedek video | `make demo-prova UI=1` (VM ya da yerel) | Aksaklıkta açılacak kayıt sunum makinesinde |
| 7 | **Manuel baz değer ölçümü** (bir kez; Kontrol Kulesi'ndeki "Hazırlık kazancı" için) | **Kim:** bu işi normalde elle yapan bir analist / test mühendisi (ideali müşteri ekibinden). TPD-1'i okuyup test case'lerini **AI'sız** yazar, kronometreyle süreyi tutar — tahmin/uydurma değer yazılmaz. **Nereye:** `rules/baz-degerler.yaml` (`story: TPD-1`, `deger_s`: saniye, `giren`: ad soyad, `not`: "F0 ölçümü, tarih, kronometre") → commit → sunucuya yükle. `make reset` silmez; Jira'dan çekmede otomatik uygulanır. Hızlı ama reset'te silinen yol: portal TPD-1 → **Manuel baz değer** → "Ölçüm gir" (analist/PO) | Kontrol Kulesi → Hazırlık süresi (story bazında): TPD-1 Manuel baz **ölçüm** (giren + not), kazanç sütunu dolu. Ölçüm yoksa "ölçülmedi" doğrudur |

#### Manuel baz değer: ölçüm yöntemi (§1.1 #7)

Elle, **tek seferlik** hazırlık adımıdır; demo akışının parçası değildir. Değer **ölçülür**, tahmin
edilmez ve kimse (Claude dahil) uydurmaz: Kontrol Kulesi bu sayıyı "ölçüm · giren: …" diye gösterir
ve kazancı ondan hesaplar.

| | |
|---|---|
| **Kim** | Bu işi bugün elle yapan bir analist / test mühendisi. İdeali müşteri ekibinden biri (sunumda en inandırıcısı); TPD-1'i daha önce görmemiş olmalı. |
| **Ne ölçülür** | TPD-1 için **test case hazırlama süresi**, AI'sız: story'yi ve 6 kabul kriterini okumak, belirsizlikleri not etmek, pozitif / negatif / sınır case'leri adımları ve beklenen sonuçlarıyla yazmak (portaldaki 10 case'in kapsamına denk). |
| **Dahil değil** | Otomasyon kodu yazmak, case'leri Jira/Xray'e girmek, PO ile toplantı beklemek. |
| **Kronometre** | Story ekranda açılınca başlar; kişi "case'ler hazır" deyince durur. Mola varsa düşülür. |
| **Kayıt** | `rules/baz-degerler.yaml` → `story: TPD-1`, `deger_s` (saniye), `giren: "Ad Soyad"`, `not: "F0 ölçümü, <tarih>, kronometre, <kişi rolü>"` → commit → sunucuya yükle. |
| **Ölçüm yoksa** | Kart "ölçülmedi" kalır — doğrudur. **Söyle:** "Kazancı yalnızca sizin ekibinizin ölçtüğü manuel süreyle hesaplıyoruz; pilotta ilk iş bu ölçümü birlikte almak." |

REPLAY'de ölçüm girilse bile AI süresi ölçülmez; kazanç "(REPLAY: yalnız review)" etiketlidir ve
verimlilik iddiası olarak söylenmez.

### 1.2 Toplantıdan 30 dk önce (VM'de)

Önce Mac'te bağlan ve sunucunun komut satırını (`…@tp-demo:~$`) bekle. Bağlantı komutunu
aşağıdakilerle birlikte yapıştırma; sonraki satırlar bağlanırken kaybolur:

```bash
gcloud compute ssh tp-demo --project testingprobe --zone europe-west3-a --tunnel-through-iap
```

Sonra sunucuda (`make reset` tek başına: soruyu yanıtlayabilmek için):

```bash
cd /opt/testingprobe
make reset          # Jira temizlik planını gösterir, "[e/H]" sorusuna → e
                    # (TPD-1..7 yorumları da silinir; bağlantılar kalır; seed'i de kendisi çalıştırır)
```

```bash
make demo-reset
make status                                  # hepsi healthy, son satır "Model kipi: REPLAY"
make security-check                          # Özet: 10/10
systemctl is-active tp-demo-web-sync         # active (locator demosu için şart)
```

Sonra portalda **sunucu** ile **Koşular** ekranını aç: `make demo-reset`'in tetiklediği GitHub
koşusu **yeşil** bitmiş olmalı. Yeşil temel koşu yoksa "Buton kimliğini değiştir" çalışmaz.

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
Bakım        L1 Buton kimliğini değiştir → L2 kırmızı koşu → L3 tek satırlık onarım PR'ı → L4 yeşil
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
3. Kanıtı göster — tıklama gerekmez, kartın başlığının altında açık durur:
   - **F2** kartı: gri **"Kod"** kutusu, `campaign.py:23`, vurgulu satır `return adet // 6`.
   - **F3** kartı: **"Veri"** kutusu, SQL sorgusu ve altında sonucu (`750.00`).
   - **F1**'de kanıt kutusu yoktur ("Kanıt dokümanın kendisi"): çelişki dokümanın içinde.
   - Her kartın sağ üstündeki yeşil **"✓ kanıt doğrulandı"** rozetini işaret et.

**Söyle:** "AI dokümanı yalnızca kendi içinde okumadı; uygulamanın **koduyla ve veritabanıyla**
karşılaştırdı, salt okunur. Her bulgunun kanıtı var ve kanıt ekrana gelmeden önce deterministik
olarak yeniden doğrulanıyor — doğrulanamayan bulgu hiç gösterilmez. AI çıktısı REPLAY, kanıt
doğrulaması canlı."

4. Kararları **§1.4 tablosundan okuyarak** ver:
   **F1 → "Dokümanı düzelt"**, **F2 → "Kod/veri hatalı"**, **F3 → "Dokümanı düzelt"**,
   **F4 → "Kod/veri hatalı"**
5. **"Düzeltmeleri Jira'ya yaz"** — **bir kez** tıkla; birkaç saniye sürer (Jira'ya yazım +
   2. kontrol turu + PO sorusu).

- Görülen: önerilen metin farkı (AC3 → "Kampanyasız siparişlerde minimum sipariş tutarı 750,00 TL…");
  "Belge son hal yapıldı; PO teyidi bekleniyor." Tutarlılık kartının sağ üstünde düğmenin yerine
  **"✓ Doküman son hal · PO teyidi bekliyor"** çıkar; altındaki kartlar 2. turun kaydıdır
  ("Güncelliğini yitirdi" etiketi normaldir), karar gerekmez.
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

| Alt adım | Kim yapar | Nerede |
|---|---|---|
| Case üret | **AI** (REPLAY) | TPD-1 sayfası, sağ üst **"Case üret"** |
| Onayla / düzelt | **İnsan** | Sol menü **Case review** |
| Yayınla | **Ürünün Xray bağlantısı** (AI yok) — yalnızca onaylı case'ler | Sol menü **Yayın** |

Akış göstergesinde 4. adımın kesikli halkası "AI adımı" demektir; AI sen **"Case üret"**e basınca
çalışır. PO kartında "✓ İnsan kapısı geçildi" yazmalı.

1. TPD-1 → **"Case üret"** → 10 case kartı (pozitif/negatif/sınır), her biri bir AC'ye bağlı.
   **C3** = "6 adet kampanyalı üründe bedava ürün verilmez" — bunu göster, sonra lazım olacak.
2. Sol menü **Case review** → birkaç case'i **"Onayla"**; **yalnızca C8**'de ("Onaylanan siparişin
   numarası gösterilir…") **"Düzelt"** → küçük bir metin değişikliği → onay; kalanları onayla.
   > ⚠️ **C1, C2, C3, C5'i düzeltme.** Bunlar Bölüm B'de koda dönüşür; REPLAY kaydı case metnine
   > bağlıdır, değişen case kod üretiminde REPLAY-MISS verir. C3 değişirse "defect adayı" anı
   > (5b) ve Bölüm C'deki TPD-5 bağlantısı kaybolur.
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

1. Listede C-numarası yok; satırlar Jira anahtarıyla, case sırasıyla gelir (1. satır C1, 2. satır
   C2 …). Şu dört başlığı işaretle:
   | Case | Başlık |
   |---|---|
   | **C1** | Sepete ekle ile ürün sepete eklenir ve sepet sayacı artar |
   | **C2** | 7 adet kampanyalı üründe 1 adet bedava verilir |
   | **C3** | 6 adet kampanyalı üründe bedava ürün verilmez |
   | **C5** | Kampanyasız siparişte minimum tutarın altında uyarı gösterilir ve onay pasif olur |
2. **"Seçilenler için kod üret (4)"**
3. Ajan adımları canlı akar: navigate → snapshot → click → generate_locator, her adımın ekran
   görüntüsüyle; sonra adım → page object eşleme tablosu, şablondan üretilen TypeScript ve yerel
   kontrol: `tsc ✓ eslint ✓ AST ✓`, Playwright `--repeat-each=3`.

**Söyle (beklerken):** "Model TypeScript yazmıyor. Ajan her adımı gerçek uygulamada — az önce
gösterdiğim bayi portalında — doğruluyor ve page object kütüphanesine eşliyor; kod bu eşlemeden
şablonla üretiliyor, assertion değerleri onaylı case metninden geliyor. Tarayıcı adımları şu an
gerçekten koşuyor; modelin kararı REPLAY."

### Adım 5b · Defect adayı anı (0,5 dk) — **sunumun en önemli anı**

1. Aynı ekranın altındaki **Üretilen testler** tablosunda C3 satırına ("6 adet kampanyalı üründe
   bedava ürün verilmez") tıkla — testin detay sayfası açılır.
- Görülen: tabloda Durum **"Defect adayı"**; detayda `beklenen "0", gerçekleşen "1" (3/3 tekrar)`
  (test 6 adette bedava beklemiyor, uygulama 1 bedava veriyor); PR **açılmadı**.

**Söyle:** "İşte değer burada. Test, dokümandaki doğru davranışı bekliyor; bugünkü kod onu
karşılamıyor. Ürün testi 'yeşile boyamaya' çalışmıyor — bunu ürün hatası adayı olarak insana
getiriyor. Adım 2'de analistin 'kod hatalı' dediği F2 bulgusu buydu."

### Adım 6 · Kırarak doğrula (2 dk)

Merge'den **önce** yapılır: testin hata yakaladığı kanıtlanmadan test kalıcı pakete alınmaz.
Uygulama bilerek bozulur (`BREAK_CAMPAIGN=1`, yalnızca koşunun bayisi için kampanya kuralı),
test kırmızıya dönmeli.

**Profil: Mühendis** → **Kod üretimi** → altta **Üretilen testler** tablosu:

1. **"7 adet kampanyalı üründe 1 adet bedava verilir"** (C2) satırına tıkla → test detayı açılır.
2. Sağdaki **Kırarak doğrula** kartında **"Kırarak doğrula"** düğmesine bas (~1,5 dk).
   - Görülen zaman çizelgesi: Bayraksız **yeşil** → `BREAK_CAMPAIGN=1` **kırmızı** → Bayrak
     kaldırıldı **yeşil** = **"Test hata yakalıyor ✓"**.
3. Geri dön; **C1** ("Sepete ekle…") ve **C5** ("Kampanyasız siparişte minimum tutar…") için aynısı.
   - Görülen: üç adım da yeşil, sarı kutu **"Zayıf test: kırılmış uygulamada da yeşil kaldı"**.
     Beklenen budur: kampanya bozulması bu testleri etkilemez (sepet sayacı / minimum tutar
     kontrolü). Merge engellenmez, açık kabul ister (Adım 7).

**Söyle (C2 koşarken, ~1,5 dk):** "Yeşil test yetmez; testin hatayı yakaladığını kanıtlıyoruz.
Uygulamada kampanyayı bilerek bozuyoruz, test kırmızıya dönmeli. Kampanya dışı testlerde kırılma
etki etmez — ürün bunu gizlemiyor, merge için açık insan kabulü istiyor."

### Adım 7 · GitHub'da onay → portalda merge (2,5 dk)

Ana dal korumalı (GitHub ruleset): PR, GitHub'da bir insan **Approve** etmeden merge edilemez.
Portal senin adına GitHub onayı göndermez — onay insanın kendi GitHub hesabından gelir. Sıra
her PR için aynıdır: **önce GitHub'da Approve, sonra portalda "Merge et"**. Approve etmeden
"Merge et"e basarsan "Merge reddedildi: … onaylı insan review'u yok" çıkar; bu doğru davranıştır.

**C2 (#11) için:**

1. **Profil: Mühendis** → C2 test detayı → **Pull request** kartında **"PR'ı aç ↗"** → GitHub'da
   PR açılır.
2. GitHub'da göster: yazar `antreklabs-testing-probe[bot]`, **Files changed** sekmesinde üretilen
   test dosyası, PR açıklamasında case bağlantısı ve eşleme tablosu, CI yorumu.
3. GitHub'da sağ üst **Review changes** → **Approve** → **Submit review**.
4. Portala dön (sayfayı yenile) → **Pull request** kartında **Merge kapısı açık ✓** → **"Merge et"**.
   - Görülen: PR **Birleşti**; main'e push koşusu otomatik başlar.

**C1 (#10) ve C5 (#12) için (vakit varsa):** aynı 1–4; 4. adımda merge kapısının altındaki sarı
kutuda **"Uyarıyı gördüm; zayıf test olarak merge et (not denetime yazılır)"** kutusunu işaretle,
sonra **"Merge et"**. Bu kabul, kim/ne zaman bilgisiyle ürünün **Denetim** kaydına (hash zincirli)
ve Kontrol Kulesi'ne yazılır.

> **Dikkat — "Değişiklik iste" / "Reddet":** merge kartının altındaki bu düğmeler "kod yanlış,
> PR'ı kapat" demektir; merge reddedildiğinde (Approve eksik) **basma**. Yanlışlıkla basıldıysa:
> Kod üretimi → üst listede o case'i işaretle → "Seçilenler için kod üret (1)" → yeni PR, kırarak
> doğrula, GitHub'da Approve, Merge et.
>
> **Dikkat:** her merge main'i ilerletir; kalan PR'ların CI'ı yeniden koşar (~1,5 dk) ve GitHub
> önceki onayları düşürür → kalan PR'ı GitHub'da **yeniden Approve** et, CI yeşil olunca merge et.
> Vakit yoksa yalnız C2 yeter.

**Söyle:** "Ana dal korumalı: doğrudan push yok, bot merge edemez; CI yeşil ve insan onayı olmadan
merge yok — bu GitHub ruleset'i. Ve önemli: **CI'da AI yok.** Model anahtarı, MCP, ajan yok;
yalnızca onaylı, deterministik test kodu koşuyor."

### Adım 8 · CI tetikleri (1 dk)

**Profil: Sunucu** → sol menü **Koşular**

Dört tetik, aynı deterministik test paketi (GitHub Actions; CI'da AI yok):

| Tetik | Ne zaman | Neden |
|---|---|---|
| PR | Bot PR açınca / günceller | Merge kapısı: test ana dala girmeden yeşil olmalı |
| push | Main'e merge olunca (otomatik) | Ana dalın yeni hâli bütün paketle doğrulanır |
| deploy | Müşterinin deploy hattı yükleme bitince sinyal gönderir | Yeni ortamda (QA) testler koşar |
| gece | Her gece 02:00 UTC (zamanlanmış) | Kod değişmese de veri/ortam bozulmaları ve kararsız (flaky) testler yakalanır; pahalı geniş regresyon gündüzü yormaz |

1. Az önceki merge'lerin başlattığı **push** koşularını göster.
2. **"Deploy sonrası testleri koş"** → listeye **deploy** koşusu düşer. Bu düğme uygulamayı
   **yüklemez**; müşterinin deploy hattının göndereceği sinyali taklit eder (demoda deploy hattı yok).
3. Vakit varsa **"Gece koşusunu şimdi başlat"** (zamanlanmış gece koşusunun elle başlatılması).
4. İstersen GitHub → **Actions** sekmesinde aynı koşuları göster.

**Söyle:** "Aynı onaylı paket dört tetikte koşar: PR'da kapı, merge'de ana dal, deploy'da yeni
ortam, gece de kod değişmese bile ortam ve veri kayması için. Gerçek kurulumda deploy sinyalini
sizin deploy hattınız gönderir; burada düğmeyle taklit ediyoruz."

**Sauce sonucu (deploy/gece):** Sauce'ta testler kırmızıysa koşu kırmızı olur. Sauce'a
ulaşılamadıysa (ör. oturum sınırı) koşu yeşil kalır, özette **"⚠️ Sauce koşmadı"** uyarısı
görünür — test koşmadığı için uygulama hatası sayılmaz.

### Adım 9 · Sauce Labs (0,5 dk)

Sauce her koşuda (push, deploy, gece) çalışır. Merge'lerin push koşusundaki **Sauce** job'unu
göster (Koşular → push koşusu → Sauce satırı / GitHub Actions → `sauce` job'u → Sauce sonuç
bağlantısı). Deploy'un Sauce job'u, öndeki Sauce bitene kadar GitHub'da **"Waiting"** görünür —
hata değil, sıradır.

**Söyle:** "Aynı testler Sauce Labs'in bulut tarayıcılarında da koşuyor; sonuç bağlantısı koşuya
yazılıyor. Hesap tek eşzamanlı oturumlu, koşular sıraya giriyor." (Sauce job'u tamamlanmadıysa:
"Sauce sonucu kapanışta göstereceğim.")

### Adım 10 · Raporlar (0,5 dk, isteğe bağlı)

Koşu detayı → **Allure raporu** / Playwright HTML / JUnit XML.
**Söyle:** "Standart çıktılar; mevcut raporlama araçlarınıza olduğu gibi girer."

### Adım 11 · Kontrol Kulesi (1 dk)

Sol menü **Kontrol Kulesi** → gez: son koşular, geçme oranı, flaky testler, alan karnesi, açık defect
adayı, AI katkısı (kabul oranı, review süresi).

Beklenen boşluklar (hata değil):
- **Case başına AI + review "ölçülmedi"** ve **Maliyet $0,00**: REPLAY'de model çağrısı yok, süre ve
  ücret ölçülmez. Canlı modelde otomatik dolar; elle girilecek bir şey yok.
- **Hazırlık kazancı "ölçülmüş baz yok"**: §1.1 #7'deki manuel ölçüm girilmediyse. Girildiyse bile
  kazanç **"(REPLAY: yalnız review)"** etiketlidir — verimlilik iddiası olarak söylenmez.
- **Flaky testler "yok"**: demo uygulaması deterministik; gerçek uygulamada aralıklı kırılan
  testler (yeniden denemede geçen / aynı commit'te farklı sonuç) burada listelenir.
  **Söyle:** "Gerçek uygulamalarda burada aralıklı kırılan testler listelenir; demo uygulaması
  deterministik olduğu için boş — ürün olmayan bir flaky'yi uydurmuyor."

**Söyle:** "Tek ekranda kalite. Her KPI'nın hangi veriden ve hangi pencereden hesaplandığı yazıyor.
Kazanç oranını yalnızca manuel baz süresi **ölçülmüş** story'lerde gösteriyoruz; ölçüm yoksa ekran
'ölçülmedi' diyor — uydurma rakam yok. REPLAY'de AI süresi ~0, gördüğünüz süre yalnızca insan review
süresi."

---

## 6. Bakım — locator kırılması ve tek satırlık onarım (4 dk)

**Ne anlatılıyor:** test otomasyonunun en pahalı kısmı yazmak değil **bakımı**. Geliştirici
"Sepete ekle" butonunun teknik kimliğini değiştirir (`data-testid` `add-to-cart` → `cart-add`);
işlev aynı, uygulama sağlam — ama o butona tıklayan bütün testler kırmızı olur. Ürün: (1) kural
tabanlı, AI'sız ayırt eder — butonun rolü + adı sayfada duruyor, yalnız kimlik değişmiş → **ürün
hatası değil, test bakımı** (22 kırmızı için 22 bug açmaz); (2) **tek satırlık onarım PR'ı** açar,
AST koruması assertion'lara dokunulamayacağını garanti eder (gerçek hata testi değiştirerek
gizlenemez); (3) insan bir satırı görüp merge eder, hepsi yeşile döner. **"Buton kimliğini değiştir"**
düğmesi o geliştiriciyi taklit eder: kimliği değiştiren commit'i main'e alır, uygulamayı yeniden
derler, CI'ı başlatır.

> **Zamanlama:** Adım 7–8'in koşuları **bittikten sonra** L1'i başlat, sonra hemen Bölüm C'ye geç;
> kırmızı koşu Bölüm C sırasında oluşur (GitHub Actions birkaç dakika sürer). Push koşusu bitmeden
> kırma: koşu ortasında uygulama değişirse sonuçlar `environment` sınıflanır, onarım önerilmez.

### L1 · Buton kimliğini değiştir — locator kırılması (0,5 dk)

**Profil: Sunucu** → sol menü **Demo kontrolleri** → **"Buton kimliğini değiştir"** → **"Evet, buton kimliğini değiştir"**

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

Göstermelik adım — karar yok. Anlatılan: kırmızı C3 testini ürün nasıl sınıflıyor (ürün hatası mı,
test bakımı mı, ortam mı, flaky mi) ve hazır bug taslağını nasıl çıkarıyor.

**Profil: Testçi** → sol menü **Bug taslakları** → **C3** satırı ("6 adet kampanyalı üründe bedava
ürün verilmez") → detay açılır. (C3 kodu üretilmediyse — ör. C3 düzeltildiyse — bu satır yoktur;
adımı atla, 13'e geç.)

- Görülen: sınıf **product_defect**, "Karar kaynağı: deterministik kural"; eşleşen sinyaller
  (assertion farkı, eleman bulundu, sayfa yapısı beklenen, tutarlı tekrar); hazır bug taslağı;
  Jira'da benzer açık bug araması → **TPD-5** "Kampanya indirimi sepette yanlış hesaplanıyor",
  benzerlik **high**, öneri **bağla**.

**Söyle:** "Önce deterministik kurallar: kuralın verebildiği kararı modele bırakmıyoruz. Model
yalnızca taslağı yazıyor ve mükerrer adayları sıralıyor — o da REPLAY. Uydurma aday ya da gerçek
değeri içermeyen taslak otomatik reddedilir."

### Adım 13 · Testçi kararı (1,5 dk)

**Profil: Testçi** → sol menü **Bug taslakları**. Ekranda C/F numarası yazmaz; satırları **özet**
ve **Kaynak** sütunuyla tanı. Her satırı aç (özete tıkla) ve kararı ver:

| Ekrandaki özet (başı) | Kaynak | Nedir | Karar |
|---|---|---|---|
| "Sepet: **6 adet** … bedava adet 0 beklenirken 1 **görünüyor**" | **Triage** | C3 testi (kod üretiminde yakalanan) | **"TPD-5 kaydına bağla"** |
| "Sepet: **6 adet** … bedava adet 0 beklenirken 1 **veriliyor**" | **Tutarlılık denetimi** | F2 — Bölüm A'da analistin "kod hatalı" dediği kampanya bulgusu | **"TPD-5 kaydına bağla"** |
| "Sepet: **Kredi limiti** aşıldığında … uyarısı gösterilmiyor" | **Tutarlılık denetimi** | F4 — kredi limiti bulgusu; mükerrer adayı yok | **"Onayla ve Jira'da aç"** |
| "Sepet: **7 adet** … bedava adet 1 beklenirken 0 görünüyor" + **"Kasıtlı kırma koşusu"** etiketi | Triage | Adım 6'da bilerek bozduğumuz koşu | **Dokunma** |

(C3 kodu üretilmediyse ilk satır yoktur; diğer üçüyle devam et.)

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

Sunum sonrası (VM): `make export-audit`.

---

## 9. Zaman darsa atla (sırayla)

1. Claude Code kanalı dakikası
2. Adım 10 (raporlar) — yalnız soru gelirse
3. Adım 8'de "Gece koşusunu şimdi başlat"
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
