# Mobil demo eki — aynı case, Android'de (6–8 dk, ölçülmedi)

Ana demonun (Demo-B, [DEMO-AKISI.md](DEMO-AKISI.md) adım 5–7) ardından oynanan ek: **aynı onaylı
case** (TPD-1 C2, "7 adet kampanyalı üründe 1 adet bedava verilir") bu kez **Android** için koda
dönüşür. Mesaj: case bir kez yazılır ve onaylanır; hat, insan kapıları ve kanıtlar platformdan
bağımsızdır, yalnız sürücü ve üretilen kodun dili değişir. Ayrıntı: [MOBIL-MASAUSTU.md](MOBIL-MASAUSTU.md).

> **Durum (2026-11-09): bu ek henüz uçtan uca provası yapılmadı; süreler ölçülmedi.** Aşağıdaki
> "Hazır mı" listesinin tamamı geçmeden sunuma alınmaz. Dürüstlük kuralları DEMO-AKISI.md ile aynıdır
> (REPLAY her yerde söylenir, ölçülmemiş sayı söylenmez, onaylar yalnız portaldan verilir, ekranda sır
> yok).

## 1. Hazırlık (sunumdan ≥ 30 dk önce)

| # | İş | Komut / yer | Beklenen |
|---|---|---|---|
| 1 | Ana yığın | `make up`, `make status` | tüm servisler sağlıklı |
| 2 | Android derlemesi | `cd demo-app/mobile && npm ci && scripts/derle-android.sh` | `demo-app/mobile/build/bayi-siparis.apk` |
| 3 | Emülatör + Appium | `make cihaz-baslat PLATFORM=android` (**`GORUNMEZ=1` vermeyin**: emülatör penceresi ekranda olmalı) | `make cihaz-durum`: Appium `127.0.0.1:4723` hazır, uygulama kurulu |
| 4 | Ajan aracı + yönlendirici | `docker compose --profile mobil up -d app-mcp appium-gw` | `docker compose ps app-mcp appium-gw` → running |
| 5 | Ağ | `make cihaz-ag` | konteyner → `host.docker.internal:4723` erişilebilir, LAN'dan erişilemez |
| 6 | Uygulama dumanı | `cd toolchain/app-mcp && npm run build && node scripts/duman-demo.mjs android` | `SONUÇ: BAŞARILI`; `add-to-cart` locator'ı |
| 7 | Ekran düzeni | emülatör penceresi portalın yanında; portal %100–125 | izleyici ikisini aynı anda görür |
| 8 | Çakışma yok | Portal → Koşular: çalışan web CI koşusu yok | web e2e ile uygulama e2e'si aynı demo API'ye karşı aynı anda koşmaz (bayi kilitleri ortak değil) |

**Hazır mı (provada bir kez, sunum günü değil):**

- [ ] Portalda "Kod üret" platform seçimi (Android) görünüyor (portal şeridi Ş7).
- [ ] REPLAY golden `rules/replay/verify_and_map_app/golden/TPD-1-C2-android.json` emülatörde
      tekrarlanıyor: ajan adımları kırmızıya düşmeden biter (golden sözleşmeden yazıldı, canlı
      cihazda kaydedilmedi — ilk provada kırılırsa yeniden kaydedilmeli).
- [ ] PR açıldıktan sonra merge kapısında **`local-ci-android`** kaydı oluşuyor ve yeşil oluyor.
      Yalnız `e2e-app/` değiştiren PR web `local-ci` ile değil, en az bir platform kontrolüyle
      merge edilir; bu kayıt oluşmuyorsa adım A5 oynanamaz.
- [ ] "Kırarak doğrula" Android script'inde yeşil → kırmızı (assertion) → yeşil bitiyor.
- [ ] Bu ekin süreleri ölçülüp aşağıdaki tabloya yazıldı.

## 2. Akış

Ana demoda C2'nin web PR'ı merge edilmiş olabilir; Android script'i ayrı script, ayrı dal
(`tp/case-android-<uuid>`) ve ayrı PR'dır, web PR'ına dokunmaz.

| # | Rol / ekran | Ne tıklanır | İzleyici ne görür | Söylenecek | Yedek |
|---|---|---|---|---|---|
| A1 | Mühendis · **Kod üretimi** | Platform: **Android** → C2 seçili → "Kod üret" | İş kuyruğa girer; script satırında platform rozeti `android` | "Aynı onaylı case. Yeniden yazmıyoruz, yeniden onaylatmıyoruz; yalnız hedef platformu seçiyoruz." | Platform seçimi yoksa ek oynanmaz (Hazır mı listesi) |
| A2 | Mühendis · C2 Android script | Adım akışını izleyin; emülatör penceresini gösterin | Ajan adımları canlı akar (`app_launch`, `app_snapshot`, `app_type`, `app_click`, `app_generate_locator`), emülatörde uygulama gerçekten sürülür; adım ekran görüntüleri; parola `***` | "Ajan tarayıcı yerine kendi MCP sunucumuz app-mcp üzerinden Appium'la telefonu sürüyor. Gördüğü şey ekran görüntüsü değil, erişilebilirlik ağacı; ekran görüntüsünü yalnız biz, sizin için alıyoruz. Modelin kararı yine REPLAY." | Emülatör asılırsa: §3 |
| A3 | Mühendis · eşleme + kod | Eşleme tablosu → üretilen dosya | Adım → ekran nesnesi metodu (`girisEkrani().girisYap`, `katalogEkrani().sepeteEkle("P-001", 7)`, `sepetEkrani().dogrulaToplam("150,00 TL")`); şablondan Java + TestNG; kontroller: derleme ✓, Java AST koruması ✓, cihazda koşu | "Model Java yazmıyor. Eşleme Java ekran nesnesi kütüphanesine, beklenen değerler yine onaylı case metninden; dosya şablondan. Web'deki `add-to-cart` kimliği uygulamada da aynı — onarım kuralı tek." | Yerel kontrol kırmızıysa: hatayı okuyun (`locator` → 1 düzeltme turu, `assertion` → defect adayı) ve ana demonun yedek videosuna dönün |
| A4 | Mühendis · PR | PR'ı açın | Başlık `[TPD-1-C2 · android] …`, etiket `platform:android`, dosya `e2e-app/src/test/java/…/uretilen/TPD1AndroidC2_<uuid8>Test.java` | "Ayrı PR, ayrı dal: web ve Android script'leri birbirini bekletmez." | — |
| A5 | Mühendis · merge kapısı | Kapıyı gösterin | Zorunlu **`local-ci-android`** (emülatörde Java + TestNG koşusu) + insan onayı | "CI'da AI yok: bu koşu onaylı Java testini emülatörde koşturuyor. GitHub'da aynısı `mobil-android` iş akışı." | Koşu sürerken A6'ya geçin |
| A6 | Mühendis · C2 Android script | "Kırarak doğrula" | Yeşil → `BREAK_CAMPAIGN=1` **kırmızı** (assertion) → yeşil = "Test hata yakalıyor ✓" | "Aynı kanıt, telefonda: kampanyayı bu bayi için bozuyoruz, Android testi kırmızıya dönüyor." | "Tamamlanamadı" biterse bir kez tekrar; ikinci kez olursa söyleyip merge'e geçin (kabul notu ister) |
| A7 | Mühendis · PR | "Merge et" | PR **Birleşti** | "Korumalı ana dal kuralı platformdan bağımsız." | `local-ci-android` yoksa merge edilmez — bunu söyleyin, ekleri burada kapatın; bypass kullanmayın |

İsteğe bağlı kapanış (yalnız soru gelirse): `demo-app/e2e-app/target/kanit/` düzeni (hata anında ekran
görüntüsü + sayfa kaynağı XML'i) — triage'ın uygulama kanıtı. iOS ve Windows sorulursa
[MOBIL-MASAUSTU.md §8](MOBIL-MASAUSTU.md)'deki durumu olduğu gibi söyleyin: iOS bu Mac'te macOS
gizlilik izni yüzünden Appium oturumunda bekliyor; Windows uygulaması derleniyor, CI iş akışı yazıldı
ama henüz koşturulmadı.

## 3. Cihaz aksarsa — yedek cümleler

| Belirti | Ne yapılır | Söylenecek |
|---|---|---|
| Ajan adımı ilerlemiyor, emülatör donuk | Ayrı terminal: `make cihaz-durdur PLATFORM=android && make cihaz-baslat PLATFORM=android`, sonra script'te yeniden üret | "Emülatör yerel bir sanal cihaz; yeniden başlatıyoruz. Bu ortam sorunu — ürün bunu testin ya da uygulamanın hatası saymaz." |
| `android cihazı başka bir MCP oturumunda kullanılıyor` | 300 sn boşta kalma süresi dolunca kilit düşer; beklemeden: `docker compose --profile mobil restart app-mcp` | "Platform başına tek cihaz var; önceki oturumu kapatıyoruz." |
| Yerel kontrol / `local-ci-android` `error` (sağlık adımı) | `make cihaz-durum`; Appium yoksa `make cihaz-baslat PLATFORM=android`; `docker compose ps appium-gw` | "Koşu başlamadan sağlık kontrolü cihazı bulamadı; bu 'ortam' sınıfı — triage'da da öyle görünür." |
| Uygulama giriş ekranında API hatası | `curl http://127.0.0.1:8081/health`; emülatör API'ye `10.0.2.2:8081` ile gider | "Uygulama aynı demo API'ye bağlı; API'yi kontrol ediyoruz." |
| Toparlanmıyor (> 2 dk) | Eki bırakın; ana demoya (adım 8) dönün | "Mobil hattı sonra ayrı bir oturumda adım adım gösterelim; web'de gördüğünüz akışın aynısı." |
