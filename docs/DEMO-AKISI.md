# Demo akışı — sunucu senaryosu (20–25 dk + 5 dk soru)

Bu belge canlı demonun **sunucu metnidir**: sunumdan önce ne hazırlanır, hangi ekranda neye
tıklanır, izleyici ne görür, ne söylenir ve bir adım aksarsa ne yapılır. Bağlayıcı kaynaklar:
senaryo ve başarı ölçütleri [TEKNIK-TASARIM §1–§2](TEKNIK-TASARIM.md#1-amaç-ve-başarı-tanımı),
demo verisi ve sahne notları [DEMO-VERISI.md](DEMO-VERISI.md), güvenilirlik
[TEKNIK-TASARIM §13](TEKNIK-TASARIM.md#13-demo-güvenilirliği). Çelişki görürseniz bu belge değil
onlar doğrudur; bu belgeyi düzeltin.

> **Dürüstlük kuralları (sunum boyunca geçerli, pazarlık konusu değil)**
>
> 1. **REPLAY her yerde söylenir.** Bugün model kipi `TP_MODEL_MODE=replay`'dir: AI adımlarının
>    çıktısı canlı modelden değil, `rules/replay/` altındaki **küratörlü golden kayıtlardan** gelir
>    (girdi beyanı doğrulanmış; model çıktısı kısmı elle hazırlanmış, `ai_call.model = golden-elle`).
>    Portal bunu **REPLAY** rozetiyle gösterir. "Canlı model" ya da "kayıtlı model çıktısı" denmez;
>    doğru cümle: *"Bu adımın AI çıktısı REPLAY: önceden hazırlanmış ve girdisi doğrulanmış bir
>    kayıttan geliyor. Model geçidi, kayıt, şema doğrulama ve insan kapıları canlıdakiyle aynı kod
>    yolundan geçiyor."* Kod üretiminde ajanın **tarayıcı adımları** gerçek uygulamada gerçekten
>    koşar; yalnızca modelin kararı kayıttan gelir.
> 2. **Ölçülmemiş sayı söylenmez.** Manuel baz süre story başına ölçülüp portaldan (gereksinim
>    detayı → "Manuel baz değer", giren + kaynak notu) girilmediyse portal o story için kazanç oranı
>    göstermez ve sunucu da bir oran söylemez; `TP_MANUAL_BASELINE_S` yalnızca "varsayılan" etiketiyle
>    görünür ve kazanca girmez. REPLAY'de AI süresi ~0'dır;
>    "AI + review" süresi yalnızca insan review süresidir — bunu söyleyin.
> 3. **İnsan kapıları atlanmaz.** Hiçbir adımda onay "hızlandırmak için" API'den ya da terminalden
>    verilmez; her onay ilgili rolün portal oturumundan verilir.
> 4. **Simülatörler adlandırılır.** Jira = `jira-sim` (Jira Cloud REST v3 alt kümesi), git =
>    LocalForge (yerel git + PR kaydı), CI = yerel test-runner. Gerçek sistemlere geçiş yolu:
>    [GERCEK-SISTEMLER.md](GERCEK-SISTEMLER.md).
> 5. **Ekranda sır yok.** `.env` açılmaz, parola terminale yazdırılmaz; parolalar parola
>    yöneticisinden yapıştırılır.

## 1. Sunumdan önce

### 1.1 Bir gün önce (prova)

| # | Ne | Komut / eylem | Beklenen |
|---|---|---|---|
| 1 | Temiz ortam | `make reset` | Sonunda `ortam temiz`; denetim kaydı `exports/` altına alınmış |
| 2 | Otomatik prova | `make demo-prova RUNS=3` (host'ta `uv` zorunlu; koşu başına ~10,5 dk makine süresi, toplam ≈ 31–32 dk) | Çıkış `0`: 3 ardışık sorunsuz prova; her biri `make reset` → `make demo-reset` → yeşil temel (baseline) push koşusu beklenir → strict REPLAY (ayrıntı: rehearsal/README.md; `UI=1` arayüzden, video). Etkin model kipi (`TP_MODEL_MODE`, core-worker'dan okunur) `replay` değilse betik hiçbir şeyi sıfırlamadan çıkış `2` ile durur. Başarısızsa çıktıdaki ilk hatayı düzeltmeden sunuma geçilmez |
| 3 | Elle tam prova (insan temposunda, kronometreyle) | Bu belgenin 3. bölümü baştan sona, REPLAY'de, sunucu konuşarak ve profiller arasında geçerek | 14 adım + locator onarımı müdahalesiz biter; her adımın süresi 3. bölümdeki **Ölçülen** sütununa yazılır. Toplam 25 dk'yı aşarsa §3.1'deki "zaman darsa atla" listesi uygulanır ve prova tekrarlanır |
| 4 | Demo-B ön kontrolü | Demo-A kararları verildikten ve case'ler onaylandıktan sonra `make demo-check` | Çıkış `0`, çıktıda `C3 DEFECT ADAYI`. Değilse F2 yanlışlıkla "Dokümanı düzelt" seçilmiştir |
| 5 | Locator ön kontrolü (çevrimdışı) | `make locator-break-verify` | Kırılma → yalnızca add-to-cart locator hatası → testId onarımı → yeşil |
| 6 | Güvenlik | `make security-check` | `Özet: 10/10` |
| 7 | Yedek video | **Son build üzerinde** `make demo-prova UI=1` ile yeni kayıt, ardından bölümlere ayırma (§1.5) | Bölümler 1–4, 5–7, 8–11, 12–14, L1–L4; ses kapalı; sunum makinesinde yerel dosya; bölüm zaman damgaları §1.5 tablosuna yazılmış. Video içeren prova raporları otomatik temizlikte (`SAKLA`, `make prova-temizle`) **korunur**; yalnızca `scripts/demo-prova.sh --temizle N --video-dahil` ile (uyarıyla) silinir |

TEKNIK-TASARIM §13 kabulü: **3 ardışık sorunsuz prova**, her biri temiz `make reset` sonrası.

> **Durum (2026-11-01, dürüst kayıt):** son build üzerinde `make demo-prova RUNS=3` 3/3 ardışık PASS
> (her biri `make reset` + `make demo-reset` sonrası, strict REPLAY, REPLAY-MISS yok, koşu başına
> ≈10,7 dk makine süresi; özet `rehearsal/reports/prova-ozeti-20261101-153953.md`) ve
> `make demo-prova UI=1` 1/1 PASS (video). Otomatik provalar strict REPLAY'de geçti; ancak bunlar
> makine temposundadır (her karar 0,1–3 sn) ve sunum süresini temsil etmez. **İnsan temposunda,
> kronometreli bir prova henüz yapılmadı** — §3'teki "Ölçülen" sütunu bu yüzden boştur. 3. satır
> yapılmadan süre hedefi (20–25 dk) karşılanmış sayılmaz.

### 1.2 Sunumdan 30 dk önce

```bash
make reset          # veritabanı, artefaktlar, forge ve jira-sim demo başlangıcına döner; seed çalışır
make demo-reset     # main → demo-baseline, demo-app-web baseline'dan derlenir, baseline CI kuyruğa girer
make status         # tüm servisler healthy; son satır "Model kipi: REPLAY" olmalı (değilse .env'de TP_MODEL_MODE=replay, make up);
                    # manuel baz bilgisi varsa bilin (story başına ölçüm yoksa kazanç "ölçülmedi")
make security-check # Özet: 10/10
```

- Portalda **sunucu** olarak **Koşular** ekranını açın; `make demo-reset`'in kuyruğa aldığı main
  koşusunun **yeşil** bittiğini görün. Locator kırılması yeşil bir temel koşu ister; yoksa
  `POST /demo/break-locator` 409 ve Türkçe yönerge döner.
- Ayrı bir terminalde **sunum boyunca açık** bırakın (portaldaki "Buton kimliğini değiştir" düğmesi uygulamayı
  derleyemez, bunu host yapar):

  ```bash
  make demo-web-sync A=--watch
  ```

- **Manuel baz değer (reset'e dayanıklı kopya):** `make reset` portaldan girilen baz değerleri siler
  (gereksinimler yeni kimlikle kurulur). Kalıcı kopya gözden geçirilmiş `rules/baz-degerler.yaml`'dır
  (yalnızca gerçek F0 ölçümü; TPD-1: 2700 sn, Gokhan Sipahi, 2026-11-03). Demo-A adım 1 eşitlemesinden sonra `GET /baseline-file`
  (ya da TPD-1 gereksinim detayı) ile TPD-1'in `etkin_etiket='ölçüm'` okuduğunu doğrulayın;
  dosyada değer yoksa "ölçülmedi" doğrudur — sahnede değer uydurulmaz.
- İkinci terminal yedek komutlar için hazır dursun (`make status`, `make demo-check`, `make break`).
  Bu terminal ekrana yansıtılmaz.
- Docker Desktop bellek ≥ 8 GB; sunum makinesinde güç kablosu takılı, uyku kapalı, bildirimler
  kapalı.

#### Gerçek sistemlerle (Jira Cloud + Xray + GitHub) sunuluyorsa

- **`.env` test anahtarları kapalı:** `TP_TEST_TEK_HESAP=0` ve `JIRA_PO_ACCOUNT_IDS` yalnızca PO'nun
  (Cengizhan) accountId'si. `make status` "UYARI: TP_TEST_TEK_HESAP=1" satırı göstermemeli.
- **PO onayı insandan:** TPD-1'deki "PO teyidi" yorumu düştükten SONRA PO kendi oturumundan
  `tp-po-approved` etiketini ekler (önce konmuş etiket bayat sayılıp kaldırılır).
- **Merge süreleri (ölçülen):** her case PR'ı için GitHub'da insan **Approve** gerekir (ruleset).
  Bir merge main'i ilerletir; ürün kalan PR dallarını günceller, CI yeniden koşar (~1,5 dk) ve
  ruleset önceki onayları düşürür → kalan PR'lar **yeniden onaylanır**. Sahnede yalnızca C2'yi
  merge edin; C1/C5'i sunumdan önce merge etmiş olun.
- **Sauce süresi:** Sauce hesabı tek eşzamanlı oturum; push koşusundaki Sauce adımı ~11 dk sürer ve
  ürün push koşusunun bitmesini bekler. Sunum için demo reposunda
  `gh variable set SAUCE_TETIKLER --repo ThinkGOtr/testingprobe-demo-app --body deploy,nightly`
  (Sauce'u "Deploy sonrası testleri koş" ve gece koşusunda gösterin); sunumdan sonra değişkeni silin.

### 1.3 Tarayıcı ve oturumlar

Portal oturumu tarayıcı başına tek kullanıcıdır; her rol için **ayrı bir tarayıcı profili**
açın (Chrome: Profil ekle). Parolalar: portal kullanıcıları `.env` → `SEED_USER_PASSWORD`, jira-sim
PO'su `.env` → `JIRA_SIM_PO_PASSWORD` — parola yöneticisinden yapıştırın, ekranda göstermeyin.

| Profil | Sekmeler | Giriş |
|---|---|---|
| **Analist** | Portal `http://127.0.0.1:8080` → Gereksinimler · jira-sim `http://127.0.0.1:8090/browse/TPD-1` | portal `analist` |
| **PO** | jira-sim `http://127.0.0.1:8090/browse/TPD-1` | jira-sim `po@sim.local` (sayfadaki giriş) |
| **Mühendis** | Portal → Kod üretimi · Örnek uygulama `http://127.0.0.1:8081` (`bayi1` / `Demo123!`) | portal `muhendis` |
| **Sunucu** | Portal → Demo yol haritası · Kontrol Kulesi · Koşular · Demo kontrolleri · Denetim | portal `sunucu` |
| **Testçi** | Portal → Bug taslakları · jira-sim `http://127.0.0.1:8090/browse/TPD-5` | portal `testci` |

### 1.4 Ekran düzeni

- Yansıtılan ekran: tek tarayıcı penceresi, tam ekran, yakınlaştırma %125. Profiller arası geçiş
  macOS'ta Cmd + ters tırnak ile (profil pencereleri aynı boyutta ve aynı yerde).
- Yansıtılmayan ekran: bu belge, iki terminal, yedek video, kronometre.
- Portalın sağ üstündeki **Canlı olaylar** göstergesi yeşil olmalı (SSE bağlı).

### 1.5 Yedekler — gerçekte ne var

TEKNIK-TASARIM §13 adım 6 ve 8 için "önceden koşmuş PR'a geç (`make seed STEP=6`)" yedeğini öngörür.
**Bu yedek bugün yoktur:** ne `Makefile` ne `scripts/seed.sh` `STEP` parametresi alır; hazır,
merge edilmiş ve CI'ı yeşil PR'lar tohumlanmaz. Bu belgede bu yedeğin yerine **bölümlü yedek video**
kullanılır. Bu, §13'ten bir sapmadır ve onaylanması gerekir (onaylanana kadar açık madde); ya
`make seed STEP=n` uygulanır ya da TEKNIK-TASARIM §13 video yedeğine göre güncellenir.

Bugün elde olan kayıt (2026-11-01, Faz 5 son build): arayüz provası
`rehearsal/reports/20261101-161433-ui-canli-k1/` — `video/` altında iki ham `.webm` (bölümsüz) ve
30 ekran görüntüsü (`ekranlar/01…30`); prova PASS, 12,9 dk makine süresi, strict REPLAY, açılış
sayacı `0/14 tamam`. Video içeren rapor otomatik temizlikte korunur. `rehearsal/reports/` git'e
girmez; video sunum makinesine elle kopyalanmalıdır. **Bölümlere ayırma henüz yapılmadı** (aşağıdaki
tablo boş).

Sunumdan önce yapılacak: son build üzerinde `make reset && make demo-prova UI=1` (arayüz için bir kez
`cd rehearsal/ui && npm ci && npx playwright install chromium`), çıkan videoyu aşağıdaki bölümlere
ayırın ve zaman damgalarını yazın.

| Bölüm | Kapsam | Başlangıç | Bitiş | Dosya |
|---|---|---|---|---|
| V1 | Adım 1–4 (Demo-A) | kaydedilmedi | — | — |
| V2 | Adım 5–7 (kod taslağı, kırarak doğrula, merge) | kaydedilmedi | — | — |
| V3 | Adım 8–11 (CI, QA ortamı, raporlar, Kontrol Kulesi) | kaydedilmedi | — | — |
| V4 | Adım 12–14 (triage, testçi kararı, Jira) | kaydedilmedi | — | — |
| V5 | L1–L4 (locator kırılması ve onarımı) | kaydedilmedi | — | — |

Yedek videoya geçildiğinde izleyiciye söylenir: *"Bu bölümü az önce değil, provada kaydettik; aynı
sürüm, aynı REPLAY kayıtları."*

## 2. Akışın özeti

```
Demo-A  1 Jira → 2 Ön inceleme + kod/veri tutarlılığı → 3 PO teyidi → 4 Case + QA onayı + yayın
Demo-B  5 Kod taslağı (ajan + şablon) → 6 Review + kırarak doğrula → 7 Korumalı main'e merge
        → 8 CI (push / deploy / gece) → 9 QA ortamı → 10 JUnit + Allure → 11 Kontrol Kulesi
Faz 4   12 Triage (önce kural) → 13 Testçi kararı → 14 Jira'da Bug (ya da mevcut kayda bağlama)
Bakım   Locator kırılması → triage test_maintenance/locator → yalnızca testId değişen onarım PR'ı → yeşil
```

Ana senaryo REPLAY `f2-kod-hatasi`dır (DEMO-VERISI): F1 ve F3 **Dokümanı düzelt**, F2 (kampanya)
ve F4 (kredi limiti) **Kod/veri hatalı**. Bu iki karar Demo-B'deki "defect adayı" anını ve Faz 4'teki
TPD-5 bağlantısını üretir. **Tek yanlış tık bu anı sessizce siler** — kararları aşağıdaki tablodan
okuyarak verin.

## 3. Sahne sahne

**Süre** sütunu konuşma dahil hedeftir (toplam **22,5 dk**; profil geçişleri — yaklaşık 10 kez
Cmd + ters tırnak — sayılmadı, ~1 dk payla ≈ 23,5 dk). **Makine** sütunu provalarda ölçülen bekleme
süresidir: API provası `rehearsal/reports/20261101-160303-k3` (3 ardışık PASS serisinin sonuncusu, özet
`prova-ozeti-20261101-153953.md`) / arayüz provası `rehearsal/reports/20261101-161433-ui-canli-k1`; konuşma bu beklemenin üstüne değil, **içine**
yerleştirilmiştir. **Ölçülen** sütunu elle, insan temposunda kronometreli provada doldurulur
(§1.1 satır 3) — henüz yapılmadı. "Yedek" sütunu adım aksarsa yapılacak şeydir; hangi yedeğe
geçildiyse izleyiciye **açıkça söylenir**.

### 3.1 Zaman darsa atla

Sırayla uygulanır; her biri yaklaşık kazancıyla:

1. İsteğe bağlı Claude Code dakikası (zaten toplamda yok).
2. Adım 10 (Allure/JUnit) — toplamda yok; yalnızca soru gelirse.
3. Adım 8'de "Gece koşusunu şimdi başlat" — yalnız "Deploy sonrası testleri koş" (≈ 0,5 dk).
4. Adım 4b'de "Düzelt" gösterimi — hepsini doğrudan onaylayın (≈ 0,5 dk).
5. Adım 11 tek cümleye — yalnız AI katkısı ve "ölçülmedi" kutusu (≈ 0,5 dk).
6. L3'te PR gövdesinin gezilmesi — yalnız 1 satırlık diff (≈ 0,5 dk).

Atlanmayacaklar: REPLAY cümlesi, insan kapıları (2b, 3, 4b onayları, 7, 13, L4), 5b defect adayı
anı, F2 → TPD-5 bağlama.

### Açılış (≈1 dk)

Sunucu · **Demo yol haritası** (soldaki menü). Ekranda 14 adımlı akış, sayaç `make reset` sonrası **0/14 tamam** (başka bir şey görürseniz ortam temiz değildir — bildirin, açılışı yol haritasız yapın),
model kipi **REPLAY**, prompt değerlendirmesi **4/8 paket bekliyor** (2026-11-01: `requirement-review`,
`triage`, `bug-draft`, `dup-rank` canlı değerlendirildi; ajan paketleri, `case-generation` ve geçişli
`guardrails` bekliyor — ekranda ne yazıyorsa onu okuyun). 9. adım (Sauce) "yerel yedek" olarak
işaretlenir — bunu şimdi söyleyin.

**Söylenecek:** "Bir Jira story'sinden başlayıp insan onaylı test case'lere, AI olmadan koşan
otomasyon koduna, Kontrol Kulesi'ne ve testçinin onayladığı hata kaydına kadar uçtan uca gideceğiz —
bu ekrandaki 14 adım. Mor adımlar AI taslağı, yeşil adımlar insan kapısı. Bugün AI çıktıları REPLAY
kipinde; ekranın üstünde ve her AI çıktısının yanında REPLAY rozeti göreceksiniz. Sauce Labs adımı
bugün yerel yedekte — bunu da ekran kendisi söylüyor."

### Demo-A — gereksinimden yayınlanmış case'e (6 dk)

| # | Rol / ekran | Ne tıklanır | İzleyici ne görür | Söylenecek (iş değeri + dürüst not) | Süre | Makine (API / UI) | Ölçülen | Yedek |
|---|---|---|---|---|---|---|---|---|
| 1 | Analist · **Gereksinimler** | "Jira'dan çek" → TPD-1 "Kampanyalı sepet ve sipariş onayı" | Story listesi (TPD-1..TPD-4), TPD-1'in açıklaması ve 6 kabul kriteri | "Analistin bugünkü dokümanı, olduğu gibi. Ürün Jira'yı salt okur; yazma ayrı, yetkisi kısıtlı bir kullanıcıyla ve yalnızca onaylı içerikle yapılır. Bugün Jira yerine Jira Cloud API'sinin simülatörü var; aynı istemci kodu gerçek siteye bağlanır." | 0,5 dk | 0,1 sn / 2,0 sn | — | Liste boşsa: `make status` → jira-sim healthy mi; "Jira'dan çek"i tekrar. Hâlâ boşsa yedek video V1 |
| 2a | Analist · TPD-1 | "Ön incelemeyi başlat" | Denetim sürüyor → 4 bulgu kartı: **F1** AC3↔AC6 çelişkisi, **F2** kampanya kodu (`campaign.py:23` `return adet // 6`), **F3** minimum tutar (veri: `ayar.min_siparis_tutari = 750.00`), **F4** kredi limiti uyarısı kodda yok. Her kartta kanıt (dosya:satır / SQL + sonuç) ve REPLAY rozeti | "AI dokümanı yalnızca kendi içinde değil, uygulamanın **koduyla ve verisiyle** karşılaştırdı — salt okunur erişimle. Her bulgunun kanıtı var ve kanıt ekrana gelmeden önce deterministik olarak yeniden doğrulanıyor: doğrulanamayan bulgu hiç gösterilmez. AI çıktısı REPLAY; kanıt doğrulaması canlı." | 1,5 dk | 3,1 sn / 2,3 sn | — | REPLAY-MISS rozeti çıkarsa: dürüstçe "kayıtla eşleşmedi" deyin; denetim güvenilmez işaretlenir. `make reset` sonrası tekrar denenir — sahnede değil; yedek video V1 |
| 2b | Analist · bulgu kartları | **F1 → "Dokümanı düzelt"**, **F2 → "Kod/veri hatalı"**, **F3 → "Dokümanı düzelt"**, **F4 → "Kod/veri hatalı"** → "Düzeltmeleri Jira'ya yaz" | Önerilen metin farkı (AC3 → "Kampanyasız siparişlerde minimum sipariş tutarı 750,00 TL…"); ikinci tur engelleyici bulgu bırakmaz → "Belge son hal yapıldı; PO teyidi bekleniyor." jira-sim sekmesinde TPD-1 açıklaması güncellenmiş, PO'ya soru yorumu ve `tp-po-pending` etiketi | "Analist her bulguya karar veriyor: doküman mı yanlış, kod mu? Kod hatalı dediği iki bulgu için sistem bug taslağı açtı — bunlar Faz 4'te testçinin önüne gelecek. Düzeltme Jira'ya ancak analist onayından sonra, onaylanan içeriğin hash'iyle yazılıyor." | 1 dk | 3,2 sn / 3,2 sn | — | 409 "içerik değişti": sayfa yeniden yüklenir, kararı tekrar verin. Yanlış karar verildiyse sahnede düzeltmeye çalışmayın: Demo-B'de defect adayı anı olmaz, bunu söyleyip yedek video V2'ye geçin |
| 3 | PO · jira-sim TPD-1 | Soru yorumunu okuyun → "PO olarak" bölümünde kısa cevap yazın → onay düğmesi (`tp-po-approved`) | Jira'da PO cevabı ve onay etiketi; ≤15 sn sonra analist ekranında **PO onaylı** | "İnsan kapısı Jira'da: PO kendi aracında cevaplıyor ve onaylıyor. Ürün etiketi koyanın gerçekten izinli PO olduğunu changelog'dan doğruluyor; botun koyduğu etiket onay sayılmaz. Onaydan sonra içerik değişirse onay geçersizleşir." | 1 dk | 15,1 sn / 1,6 sn | — | Portal 30 sn'de güncellenmezse sayfayı yenileyin (PO sorgusu 15 sn'de bir). PO oturumu düştüyse jira-sim'e yeniden giriş |
| 4a | Analist · TPD-1 | "Case üret" | 10 case kartı (pozitif/negatif/sınır), her biri AC'ye bağlı; REPLAY rozeti; C3 = "6 adet kampanyalı üründe bedava ürün verilmez" | "Case'ler AC'lere ve PO cevaplarına bağlı, şemalı çıktı. Şemaya uymayan çıktı reddedilir. Hangi AC'nin kapsanmadığını da gösteriyor." | 0,5 dk | 3,1 sn / 15,4 sn | — | Hata: "Case üretimini yeniden dene". REPLAY-MISS'te üretim hiç taslak açmaz (politika: hata) — yedek video V1 |
| 4b | Analist · **Case review** | Birkaç case "Onayla"; birinde "Düzelt" (küçük metin düzeltmesi) → onay; kalanları onaylayın | Sayaç ve **kabul oranı** (ilk karara göre, hedef %70); düzeltmede alan bazlı fark | "Her karar ölçülüyor: kabul oranı, ret nedeni, düzeltme büyüklüğü. Süre sayacı gerçek review süresi. **Not:** REPLAY'de AI süresi ölçülmez; manuel baz değer ölçülmediyse kazanç oranı göstermiyoruz — uydurma rakam yok." | 1 dk | 0,2 sn / 1,8 sn | — | Zaman darsa "Düzelt"i atlayın (§3.1) |
| 4c | Analist · **Yayın** | "Yayın önizleme" → "Seçilenleri yayınla (n)" | Önizlemede kalem başına işlem (`create`), sonra Jira'da Test issue'ları (TPD-8…) — jira-sim sekmesinde TPD-1'e bağlı | "Yayın önce kuru çalışır; yalnızca onaylı ve onaydan sonra değişmemiş case yazılır. İdempotent: ikinci kez basmak ikinci kayıt açmaz." | 0,5 dk | 0,5 sn / 2,4 sn | — | Kısmi yayın: tekrar "Seçilenleri yayınla" (idempotent) |

İsteğe bağlı (vakit varsa, 1 dk; toplamda yok): Analist · **Claude Code kanalı** → "8 saatlik token
oluştur". "Aynı akışı IDE'den de besleyebilirsiniz: Claude Code taslak gönderir, onay yine burada
insanda." Ayrıntı: [CLAUDE-CODE-KANALI.md](CLAUDE-CODE-KANALI.md).

### Demo-B — onaylı case'ten korumalı main'e (8,5 dk)

| # | Rol / ekran | Ne tıklanır | İzleyici ne görür | Söylenecek | Süre | Makine (API / UI) | Ölçülen | Yedek |
|---|---|---|---|---|---|---|---|---|
| 5 | Mühendis · **Kod üretimi** | C1 (sepet sayacı), C2 (7 adet), C3 (6 adet), C5 (750,00 TL) seçili → "Seçilenler için kod üret (4)" | Ajan adımları canlı akar (Playwright MCP: navigate, snapshot, click, generate_locator) + adım ekran görüntüleri; adım → page object eşleme tablosu; şablondan üretilen TypeScript; yerel kontrol: tsc ✓ eslint ✓ AST ✓, Playwright `--repeat-each=3` | "Model TypeScript yazmıyor. Ajan her adımı gerçek uygulamada doğruluyor, page object kütüphanesine eşliyor; kod bu eşlemeden şablonla üretiliyor ve assertion değerleri onaylı case metninden geliyor. Ajanın tarayıcı adımları şu an gerçekten koşuyor; modelin kararı REPLAY." | 2 dk | 52,8 sn / 53,8 sn | — | 120 sn gecikme bütçesi aşılırsa portal uyarı verir; bekleyin. Bir case "doğrulanamadı" ile insana düşerse bu ürünün doğru davranışıdır — söyleyin, diğer case'lerle devam. Ajan hiç başlamazsa yedek video V2 |
| 5b | Mühendis · C3 script | C3'ü açın | **Defect adayı**: "beklenen "0", gerçekleşen "1" (3/3 tekrar)" — PR açılmadı | "İşte değer: test, dokümandaki doğru davranışı bekliyor ve bugünkü kod onu karşılamıyor. Ürün testi 'düzeltmeye' çalışmıyor; bunu bir ürün hatası adayı olarak insana getiriyor. Bunu Faz 4'te göreceğiz." | 0,5 dk | — / 1,5 sn | — | `make demo-check` provada 0 döndüyse bu an gelir; gelmezse F2 kararı yanlıştır (yedek video V2) |
| 6 | Mühendis · C2 script (sonra C1, C5) | "Kırarak doğrula" | Zaman çizelgesi: bayraksız **yeşil** → `BREAK_CAMPAIGN=1` **kırmızı** (assertion) → bayrak kaldırıldı **yeşil** = "Test hata yakalıyor ✓". C1/C5'te aynı işlem "Kırma etkilemedi · kabul gerekli" (zayıf test işareti) | "Yeşil test yetmez; testin hatayı yakaladığını kanıtlıyoruz: uygulamada kampanyayı bilerek bozuyoruz, test kırmızıya dönmeli. Kampanya dışı testlerde kırılma etki etmez — ürün bunu gizlemiyor, merge için açık insan kabulü istiyor." C2'nin ~1,5 dk'lık koşusu sırasında bu cümleyi söyleyin | 2 dk | 1 dk 45 sn / 120 sn (C2 86,9 + C1 16,7 + C5 16,6) | — | Kırma koşusu "tamamlanamadı" biterse tekrar "Kırarak doğrula"; ikinci kez olursa söyleyip merge'e geçin (merge kabul notu ister) |
| 7 | Mühendis · C2, C1, C5 PR'ları | Merge kapısını gösterin → "Merge et" (C1/C5'te kabul notu yazarak) | Merge kapısı: zorunlu `local-ci` yeşil + insan onayı; PR **Birleşti**; main'e push CI otomatik kuyruğa girer | "Ana dal korumalı: doğrudan push yok, bot merge edemez; CI yeşil ve insan onayı olmadan merge yok. GitHub'da bu bir ruleset; burada aynı kural yerel forge'da." **Merge beklemesinde (C1, C5) şunları söyleyin:** "CI'da AI yok: model anahtarı, MCP, ajan yok — yalnızca onaylı, deterministik test kodu" ve 9. adımın Sauce notu (aşağıda) | 2 dk | 2 dk 02 sn / 126,6 sn (C2 2,1 + C1 50,3 + C5 74,2) | — | CI sürüyorsa "CI sürüyor; yeşil olunca merge edilebilir" — bekleyin ve bekleme cümlelerini söyleyin. 2 dk'yı aşarsa yedek video V2 (§1.5: hazır PR yedeği yok) |
| 8 | Sunucu · **Koşular** | Push koşusunu gösterin → "Deploy sonrası testleri koş" (zaman varsa "Gece koşusunu şimdi başlat") | Tetik türleri: `push`, `deploy`, `nightly`; koşu durumu canlı akar | "Tetikler: PR, main'e push, gece ve deploy olayı — hepsi aynı deterministik paket." | 1 dk | 1 dk 15 sn / 77,1 sn (push + deploy + gece) | — | Koşu 2 dk'yı aşarsa adım 11'e geçin, koşuyu sonra gösterin; tamamen takılırsa yedek video V3 |
| 9 | (adım 7'de anlatıldı) | — | Koşunun yerel Chromium job'u; QA ortamı = compose'daki uygulama; yol haritasında "yerel yedek" | **Dürüst not:** "Sauce Labs job'u CI'da hazır ama hesabın kimliği henüz tanımlı değil; bugün aynı testler yerel Chromium job'unda koşuyor. Kimlik geldiğinde GitHub secret olarak eklenir, ek kod gerekmez." | 0 dk (7'nin içinde) | — | — | — |
| 10 | (isteğe bağlı) Sunucu · koşu detayı | "Allure raporu", JUnit bağlantısı | Allure raporu, Playwright HTML raporu, JUnit XML | "Standart çıktılar: JUnit XML ve Allure. Mevcut raporlama araçlarınıza olduğu gibi girer." | 0 dk (yalnız soru gelirse) | — | — | Rapor açılmazsa JUnit bağlantısını gösterin |
| 11 | Sunucu · **Kontrol Kulesi** | Ekranı gezin | Son koşular, koşu bazlı geçme oranı, flaky testler, uygulama/alan karnesi, açık defect adayı, AI katkısı (kabul oranı, süre) | "Tek ekranda kalite: hangi alan kırılgan, hangi test flaky, AI'ın katkısı ne. Her KPI'nın hangi tablodan ve hangi pencereden hesaplandığı yazıyor. Kazanç yalnızca story'ye özel ölçülmüş manuel bazı olan story'lerden hesaplanır; 'varsayılan' baz kazanca girmez, ölçüm yoksa 'ölçülmedi' görünür. REPLAY'de hazırlık süresi yalnız review süresidir." | 1 dk | 0,1 sn / 1,5 sn | — | — |

**Zamanlama:** adım 7'deki push CI ve adım 8'in koşuları bittiyse locator kırılmasını **şimdi**
başlatın (aşağıdaki L1, ≈ 0,5 dk), sonra Faz 4'e geçin. Kırmızı CI'ın oluşması provada 2 dk 35 sn
(API) / 157 sn (UI) sürdü; Faz 4'ün 3 dk'sı bunu yalnızca ~25 sn payla örter — Faz 4'te acele
etmeyin, gerekirse 12. adımdaki sinyalleri tek tek okuyun. Push CI bitmeden kırmayın: uygulama koşu
ortasında yeniden derlenirse o koşunun kalan testleri dürüstçe `unknown`/`environment` sınıflanır ve
onarım önerisi üretilmez.

### Faz 4 — başarısızlıktan Jira kaydına (3 dk)

| # | Rol / ekran | Ne tıklanır | İzleyici ne görür | Söylenecek | Süre | Makine (API / UI) | Ölçülen | Yedek |
|---|---|---|---|---|---|---|---|---|
| 12 | Mühendis/Testçi · C3 → hata detayı | C3'ün triage bağlantısı | Sınıf **product_defect**, "Karar kaynağı: deterministik kural"; eşleşen sinyaller (assertion farkı, eleman bulundu, sayfa yapısı beklenen, tutarlı tekrar); bug taslağı hazır; Jira'da benzer açık bug araması → **TPD-5** "Kampanya indirimi sepette yanlış hesaplanıyor", benzerlik **high**, öneri **bağla** | "Önce deterministik kurallar: kuralın verebildiği kararı modele bırakmıyoruz. Model yalnızca taslağı yazıyor ve mükerrer adaylarını sıralıyor — o da REPLAY. Uydurma aday anahtarı ya da gerçek değeri içermeyen taslak otomatik reddedilir." | 1 dk | 0,0 sn / — | — | Taslak "hazırlanıyor"da kalırsa "Aramayı yenile"; olmazsa yedek video V4 |
| 13 | Testçi · **Bug taslakları** | Listede **dört** taslak görünür. Sırayla: **C3** taslağı → "TPD-5 kaydına bağla"; **F2** (kampanya, Demo-A'dan) taslağı → "TPD-5 kaydına bağla"; **F4** (kredi limiti) taslağı → "Onayla ve Jira'da aç". **C2 kırma koşusu** taslağına **dokunmayın** | C3 ve F2 için yeni Bug açılmaz, ikisi de TPD-5'e bağlanır; F4 için yeni Bug (TPD-n). C2 kırma koşusu taslağı "bekliyor" kalır (TPD-5 `medium`, öneri **yeni kayıt**) | "Kayıt açma kararı testçinin. Mükerrerse mevcut kayda kanıt eklenir, yeni kayıt açılmaz. Onaysız hiçbir şey Jira'ya gitmez." F2'de: "Demo-A'da analistin 'kod hatalı' kararı da aynı kayda bağlandı — dokümandan gelen bulgu ile testten gelen kanıt aynı Jira kaydında buluştu." Kırma taslağı için (sorulursa ya da göz ucuyla): "Bu, 6. adımda kampanyayı **bilerek** bozduğumuz koşudan gelen hata; ürün onu da dürüstçe triage etti ama kararı insana bıraktı. Gerçek bir hata değil, bu yüzden bekliyor bırakıyoruz." | 1,5 dk | 3,3 sn (C3 + F2 + F4) / 6,0 sn | — | 409: içerik değişmiştir, sayfa yenilenir. Jira yazımı başarısızsa yayın taslakta "yeniden dene" ile tekrarlanır (idempotent). Kırma taslağı yanlışlıkla onaylandıysa söyleyin: "bilerek bozulmuş koşudan açılmış bir kayıt; sunum sonrası kapatılacak" |
| 14 | Testçi · jira-sim TPD-5 ve yeni Bug | Sekmeleri gösterin | TPD-5'te **iki kanıt yorumu** (C3'ten ve F2'den: beklenen/gerçekleşen, kanıt bağlantıları, denetim zinciri başı), `Relates` TPD-1, `Test` TPD-10 (C3'ün Test issue'su), bağlantılar tekrarlanmaz; yeni Bug `AI-generated` etiketli, `Relates` TPD-1 | "Kayıt story'ye ve teste bağlı, kanıt bağlantılı. Kim onayladı, hangi içerik hash'i, hangi zincir başı — hepsi kayıtta." | 0,5 dk | — | — | — |

### Bakım — locator kırılması ve onarımı (L1 0,5 dk + L2–L4 2,5 dk)

Sayılar ana yola göredir: Demo-B'de C1, C2, C5 merge edildiği için paket **36** testtir. Merge
yapılmadıysa (yalnız yedek yol) **19 kırmızı, 18 kardeş hata, tam paket 33/33**.

| # | Rol / ekran | Ne tıklanır | İzleyici ne görür | Söylenecek | Süre | Makine (API / UI) | Ölçülen | Yedek |
|---|---|---|---|---|---|---|---|---|
| L1 | Sunucu · **Demo kontrolleri** (adım 11'den sonra, Faz 4'ten önce) | "Buton kimliğini değiştir" → "Evet, buton kimliğini değiştir" | Demo olay günlüğü: kırılma merge'ü (`add-to-cart` → `cart-add`, rol ve ad aynı), demo uygulaması yeniden derleniyor, ardından push CI | "Geliştirici bir butonun test kimliğini değiştirdi — işlev aynı. Klasik otomasyonda bu, sabah onlarca kırmızı test demek." | 0,5 dk | 8,3 sn / 9,9 sn | — | "Demo uygulaması hâlâ yeniden kurulmadı": host'ta `make demo-web-sync A=--watch` açık mı? Kapalıysa açın. Düğme 409 dönerse yeşil temel koşu yoktur (yönergeyi okuyun). Son çare terminal: `make break` |
| L2 | Sunucu · Koşular → kırmızı koşu | Koşuyu açın | **22 kırmızı / 36**; hepsi **test_maintenance / locator** (`catalog.addToCart`, kapsam `product-card-P-00x`, sha eşleşiyor) | "Ürün kırmızıları tek tek bug açmıyor: kural, elemanın niyetinin (rol + ad) sayfada durduğunu ve tek bir farklı testId'ye çözüldüğünü kanıtlıyor. Bu bir ürün hatası değil, test bakımı." | 0,5 dk | 2 dk 35 sn / 157,1 sn (Faz 4 sırasında) | — | Hepsi `environment` sınıflandıysa uygulama koşu ortasında derlenmiştir: söyleyin, `make demo-reset` sonra tekrar — sahnede değil; yedek video V5 |
| L3 | Mühendis · hata detayı | "Onarım PR'ı aç" | Onarım: yalnızca `e2e/pages/catalog/locators.ts` içinde **1 satır** testId; AST koruması (onarım modu: yalnızca testId değeri) ✓; tam paket yerel kontrol **36/36** ✓; PR gövdesinde sinyaller, diff, yoklama, aria doğrulaması, "AI üretimi: hayır"; **21 kardeş hata** aynı PR'ı paylaşır (22 hatanın tümü tek onarımda) | "Onarım deterministik, modelsiz. Yalnızca locator değeri değişebilir: test dosyası ve assertion asla otomatik değişmez — bunu AST koruması hem burada hem CI'da zorunlu kılıyor. Beklenen sonuçtaki her sapma defect adayıdır, onarılmaz." | 1 dk | 27,2 sn / 28,9 sn | — | Onarım "engellendi" derse nedeni okuyun (ör. sha farklı); bu, ürünün doğru reddidir |
| L4 | Mühendis · onarım PR'ı | "Merge et" | Merge → push CI → **36/36 yeşil**; kırmızı hataların durumu `merged` | "Tek insan onayıyla 22 kırmızı yeşile döndü; ve bunu yapan kod değişikliği tek satır, gözden geçirilmesi saniyeler." | 1 dk | 25,7 sn / 31,3 sn | — | CI uzun sürerse bu arada **Denetim** ekranını gösterin (aşağıda) |

#### GitHub kipinde bakım yolu (TP_FORGE=github)

Ekranlar ve sözler aynıdır; arkadaki mekanizma farklıdır (ayrıntı: `docs/GERCEK-SISTEMLER.md` §5.7):

- **L1 "Buton kimliğini değiştir"**: bot DEĞİL, insan kimliği (`GITHUB_MERGE_TOKEN`, `demo-admin`) GitHub'da
  `demo/break-locator-<main12>` dalını, PR'ı açar ve bypass ile merge eder. GitHub'da PR'ı gösterin:
  yazar ve merge eden Gokhan, fark tek satır `data-testid`. Sunum boyunca ayrı terminalde
  `make demo-web-sync A=--watch` açık olmalı (demo-app-web GitHub main'inden, toolchain aynası
  üzerinden derlenir; `TP_FORGE_REMOTE_URL` gerekli).
- **L2 kırmızı koşu**: GitHub Actions `push` koşusu (`ci.yml`); portal onu izler. Süre Actions'a
  bağlıdır (runner kurulumu dahil birkaç dakika) — bekleme sırasında Denetim ekranını gösterin.
- **L3 "Onarım PR'ı aç"**: PR'ı **bot (GitHub App)** açar; `ast-guard` onarım kipinde koşar.
- **L4 merge**: portalda "Merge et" (insan token'ı) ya da GitHub arayüzünde onay + merge; bot merge
  edemez. Ardından `push` koşusu yeşil.
- **Sıfırlama**: force-push yok; insan kimliğiyle main'e `demo-baseline` ağacını geri getiren PR
  (`demo/reset-baseline-<main12>`) merge edilir; geçmiş korunur.
- Yedek: GitHub erişimi koparsa `.env`'de `TP_FORGE=local` + `make up` ile yerel forge'a dönün
  (§1.5).

### Kapanış (≈1 dk)

1. Sunucu · **Demo yol haritası**: 14 adım işaretli; Sauce adımı "yerel yedek", model kipi REPLAY,
   prompt değerlendirmesi "4/8 paket bekliyor". Sayaçta ne yazıyorsa onu okuyun (yerel yedek ayrıca sayılır).
   "Açılışta 0'dı; şimdi uçtan uca tamam — ve hangi adımın REPLAY, hangisinin yerel yedek olduğunu
   ekran kendisi söylüyor." **Bilinen kozmetik sorun:** akış bitince TPD-1 adım göstergesi hâlâ 5.
   adımı "sıradaki" gösterebilir; düzeltilene kadar ona işaret etmeyin, sorulursa "gösterge hatası,
   kayıt tamam" deyin.
2. Sunucu · **Denetim**: zincir doğrulaması (`verify`) yeşil. "Her AI çağrısı, araç çağrısı, onay ve
   ret kayıtta; kayıtlar append-only ve hash zinciriyle korunuyor, zincirin başı Jira yorumlarına ve
   PR açıklamalarına sabitleniyor. AI üretti, her adımda insan onayladı."

Sunum sonrası: `make export-audit` (denetim kaydı `exports/` altına, `.sha256` ile).

**Süre özeti (hedef):** açılış 1 + Demo-A 6 + Demo-B 8,5 + L1 0,5 + Faz 4 3 + L2–L4 2,5 + kapanış 1 =
**22,5 dk**; profil geçişleriyle (~1 dk) ≈ 23,5 dk, isteğe bağlı Claude Code dakikasıyla ≈ 24,5 dk. Ölçülen
toplam: **henüz ölçülmedi** (§1.1 satır 3).

## 4. Aksaklık rehberi (genel)

| Belirti | Ne yapılır |
|---|---|
| Portal boş / 502 | Yansıtmayan terminalde `make status`; tek servis düştüyse `make up` (idempotent, veriyi korur) |
| "Canlı olaylar" kırmızı | Sayfayı yenileyin; oturum düştüyse yeniden giriş |
| REPLAY-MISS rozeti | Dürüstçe söyleyin: "bu adımın girdisi kayıtla eşleşmedi, ürün bunu gizlemiyor". Sahnede düzeltilmez; ilgili yedek video bölümüne (§1.5) geçin |
| CI 2 dk'yı aşıyor | Kontrol Kulesi veya mimariyi anlatın; koşu bitince devam |
| Tam çöküş | Yedek video (§1.5, ilgili bölüm); sunum sonrası `make reset` |

Sahnede **yapılmayacaklar:** `make reset` (veritabanını siler, tüm akışı başa alır), `.env` düzenleme,
API'ye elle onay isteği, `make break Z=1` (yeşil temel koşu denetimini atlar; onarım sonra engellenir).

## 5. Soru-cevap kopya kâğıdı

| Soru | Kısa cevap |
|---|---|
| **AI yanlış case/kod üretirse?** | Hiçbir AI çıktısı insan onayı olmadan test varlığına dönüşmez. Onay, kullanıcının gördüğü içeriğin hash'ine bağlı; onaydan sonra değişen içerik yayınlanmaz/merge edilmez. Kod modelden değil, doğrulanmış eşlemeden şablonla üretilir; `tsc --strict`, eslint, AST koruması zorunlu. |
| **Güvenlik / prompt injection?** | Jira, kod, veri, sayfa ve CI log içeriği güvenilmez sayılır ve etiketli veri bloğunda taşınır; içindeki talimat uygulanmaz (demo story'si TPD-3'te bilerek bir injection cümlesi var). Ajan yalnızca izin listesindeki araçları kullanır; tarayıcı yalnızca demo uygulamasına erişir. Üretilen kod internetsiz, sırsız, izole bir servis içinde koşar. `make security-check` bunları her çalıştırmada doğrular (10 kontrol). |
| **Uygulamamızın kodu ve verisi dışarı çıkar mı?** | Ürün müşteri ortamında (on-prem) çalışır; koda ve veritabanına yalnızca salt okuma erişimi vardır (izinli tablolar, tek `SELECT`, satır/zaman sınırı, maskelenmiş sonuç; genel amaçlı SQL aracı yok). AI'ın kod/veri kanıtına dayanan her bulgusu gösterilmeden önce deterministik olarak yeniden doğrulanır. |
| **On-prem kurulum?** | Bugün tüm yığın tek makinede Docker Compose ile çalışıyor (dışarıdan port yok, hepsi `127.0.0.1`). Ürün fazında aynı imajlar müşteri ortamına (ör. Azure Container Apps / Kubernetes) kurulur; demoda Postgres durum makinesi olan iş akışı motoru ürün fazında Temporal'dır. |
| **Model nerede çalışır?** | Ürün fazında model de müşteri ortamında: müşterinin bulut hesabındaki/tenant'ındaki model ya da on-prem model. Model geçidi sağlayıcıdan bağımsızdır; sağlayıcıya özgü kod yalnızca adaptörlerde. Bugün Anthropic adaptörü çalışır durumda, Azure OpenAI adaptörü **iskelet** — dürüstçe söyleyin. Müşteri verisi model eğitimi veya ince ayar için kullanılmaz. |
| **KVKK / kişisel veri?** | Müşteri verisi işlenen her ortamda model girdisinde maskeleme zorunlu (`TP_PII_MASKING=1`): TCKN (sağlama algoritmasıyla), TR IBAN (mod-97), telefon, e-posta; geri açılabilir maskeleme, fark kayda yazılır. Demo yalnızca sentetik veriyle çalıştığı için bugün kapalı — bu bilinçli ve kayıtlı bir karar. |
| **Bugün gördüğümüz AI canlı mı?** | Hayır, REPLAY: AI adımlarının çıktısı önceden hazırlanmış ve girdisi doğrulanmış kayıtlardan geliyor; ekranda her yerde REPLAY yazıyor. Canlı modele geçiş tek ayardır (`TP_MODEL_MODE`); geçmeden önce her prompt paketi canlı değerlendirme setinden geçmek zorunda (2026-11-01 itibarıyla 8 paketten 4'ü — `requirement-review`, `triage`, `bug-draft`, `dup-rank` — canlı modelle değerlendirildi; ajan paketleri `consistency-check`, `verify-and-map`, ayrıca `case-generation` ve ortak `guardrails` hâlâ "canlı değerlendirme bekliyor". Değerlendirilmiş olmak REPLAY çıktısını canlı yapmaz: sahnedeki çıktılar yine elle hazırlanmış golden kayıtlardır). |
| **Kazanç ne kadar?** | Bugün yalnızca ölçtüğümüzü söylüyoruz: kabul oranı ve review süresi ekranda. Manuel baz süre ölçülmeden kazanç oranı göstermiyoruz. Ölçüm girilse bile demo REPLAY'de koştuğu için AI süresi ölçülmez: Kontrol Kulesi başlığı "REPLAY: hesaplanmaz" der, story satırındaki oran "(REPLAY: yalnız review)" etiketlidir — **sunumdaki yüzde bir verimlilik iddiası değildir.** Hedef: hazırlık süresinde %30–50 azalma, case kabulünde ≥ %70, script ilk review başarısında ≥ %60. |
| **Gerçek Jira?** | Aynı istemci kodu Jira Cloud REST v3'e bağlanır; seçim tek ayar (`JIRA_BASE_URL`). Okuma ve yazma ayrı kullanıcılar, yazma yalnızca demo projesinde. PO onayı Jira etiketiyle ve izinli PO hesabıyla. Bkz. GERCEK-SISTEMLER.md. |
| **Xray / test yönetimi?** | Test yönetimi bir port: bugün Jira Test issue'su; Xray Cloud adaptörü hazır ve simülatöre karşı test edildi, gerçek Xray hesabıyla henüz koşmadı. TestRail, Zephyr, Octane sonraki fazda aynı arayüzle. |
| **GitHub Copilot kullanıyoruz?** | Kurallar ve prompt'lar `rules/` altında düz dosya; Claude Code ve Copilot kural dosyaları buradan üretilir. Case gönderme ve yayın MCP araçları IDE kanalından da çağrılabilir; onay yine portalda insanda. Demoda IDE kanalı Claude Code ile gösterilir. |
| **Sauce Labs / cihaz bulutu?** | CI'da Sauce job'u hazır (Sauce Connect tüneli, sonuç linkleri koşuya yazılır); kimlik GitHub secret olarak eklenince koşar. Bugün kimlik tanımlı değil, aynı testler yerel Chromium job'unda koşuyor. Not: Sauce şu an Playwright 1.61.1'e kadar destekliyor; config buna sabitli. |
| **GitHub'a ne zaman?** | Forge bir port: `TP_FORGE=github` ile aynı akış GitHub PR'ları, ruleset ve Actions ile çalışır (bot App merge edemez, bypass yalnızca insan demo-admin'de). Bugün GitHub App kurulu olmadığı için yerel forge kullanılıyor; locator kırma demosu yalnızca yerel forge'da. |
| **Neden Temporal yok?** | Demoda iş akışı Postgres durum makinesi; insan kapısı kuralı aynı (onay Postgres'teki oturumlu kullanıcı + içerik hash'i). Temporal ürün fazında. |
