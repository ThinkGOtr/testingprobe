# demo-app/desktop — Bayi Sipariş Portalı (Windows masaüstü, WPF)

Web uygulamasının (`demo-app/web`) Windows masaüstü sürümü: aynı ekranlar (giriş, katalog, sepet,
sipariş onayı, siparişlerim), aynı davranış, **aynı demo API** ve **aynı erişilebilirlik kimlikleri**
(plan `specs/009-mobil-masaustu/plan.md` §2.2). Backend'de değişiklik yoktur.

| Proje | Hedef | İçerik |
|---|---|---|
| `src/BayiSiparis.Cekirdek` | `net8.0` | API istemcisi (`HttpClient` + çerez kabı), modeller, tutar/tarih biçimi, görünüm modelleri (`INotifyPropertyChanged`, komutlar). WPF türü yok → macOS'ta derlenir ve test edilir |
| `src/BayiSiparis.Masaustu` | `net8.0-windows` (WPF) | Pencere, ekranlar (XAML), UI Automation yardımcı denetimleri (`Otomasyon/`). `EnableWindowsTargeting` ile macOS'ta da derlenir; **yalnız Windows'ta çalışır**. Çıktı: `BayiSiparis.exe` |
| `tests/BayiSiparis.Cekirdek.Testler` | `net8.0` (xUnit) | Sahte `HttpMessageHandler` ile API istemcisi + görünüm modeli akışları; bir test gerçek `HttpListener` ile oturum çerezini doğrular |

Uygulama projelerinde dış NuGet paketi yoktur; test paketlerinin sürümleri `Directory.Packages.props`'ta sabittir.

## Derleme, test, yayın

.NET SDK 8 veya üstü gerekir (macOS'ta `brew install dotnet` ile gelen SDK 10 da olur: `net8.0`
hedeflenir, testler `RollForward=Major` ile makinedeki yeni çalışma zamanında koşar).

```bash
cd demo-app/desktop
dotnet build BayiSiparis.sln          # üç proje (WPF dahil) — macOS'ta da
dotnet test  BayiSiparis.sln          # çekirdek testleri
python3 scripts/kimlik-kontrol.py     # web data-testid ↔ masaüstü AutomationId karşılaştırması

scripts/yayinla.sh                    # win-x64 + win-arm64, self-contained → build/<rid>/BayiSiparis.exe
scripts/yayinla.sh win-arm64          # yalnız ARM64 (Windows 11 ARM sanal makinesi)
scripts/yayinla.sh --fd win-x64       # çatıya bağımlı (~250 KB; hedefte .NET 8 Desktop Runtime gerekir)
scripts/yayinla.sh --test             # önce testler
```

Windows'ta aynısı: `.\scripts\yayinla.ps1 [-Rid win-arm64] [-CatiyaBagimli] [-Test]`.

Varsayılan yayın **self-contained**'dır (~160–175 MB tek klasör): sanal makineye .NET kurmadan klasörü
kopyalayıp `BayiSiparis.exe`'yi çalıştırmak yeterlidir. `build/` git'e girmez.

## API adresi

Öncelik sırası (ilk dolu olan kullanılır):

1. Komut satırı: `BayiSiparis.exe --api-url http://HOST:PORT/api`
2. Ortam değişkeni: `BAYI_API_URL`
3. `appsettings.json` (exe'nin yanında): `{"BayiApi": {"TabanAdres": "..."}}`
4. Varsayılan: `http://127.0.0.1:8081/api` — compose'daki `demo-app-web` nginx'i (`/api/*` → demo API)

Geçersiz adres (http/https değil) açılışta hata kutusuyla bildirilir. Oturum, web'deki gibi API'nin
verdiği HttpOnly `bayi_oturum` çerezidir; uygulama çerezi bellekte tutar (her açılışta yeni oturum).
Test uçları (`/api/test/*`) uygulamadan çağrılmaz; nginx zaten dışarı açmaz.

### Windows 11 ARM sanal makinesinden (UTM) Mac'teki API'ye

Compose `demo-app-web`'i yalnız Mac'in loopback'ine bağlar (`127.0.0.1:8081`); sanal makine bu adrese
doğrudan ulaşamaz. Compose'u değiştirmeden iki yol:

- Mac'te, sanal makine ağının host adresine bir yönlendirme açın (UTM "Shared Network" kipinde Mac
  genelde `192.168.64.1`'dir): `socat TCP-LISTEN:18081,bind=192.168.64.1,fork,reuseaddr TCP:127.0.0.1:8081`
- ya da sanal makineden SSH tüneli: `ssh -N -L 8081:127.0.0.1:8081 kullanici@192.168.64.1`
  (bu durumda varsayılan adres değişmeden çalışır).

Ardından VM'de: `setx BAYI_API_URL http://192.168.64.1:18081/api` (yeni oturumda geçerli) ya da Appium
`appium:appArguments` ile `--api-url ...`. Ayrıntılı kurulum rehberi: `docs/WINDOWS-VM.md` (Ş9).

## Kimlik sözleşmesi (AutomationId = web data-testid)

Her etkileşimli/doğrulanan eleman `AutomationProperties.AutomationId` taşır ve değeri web'deki
`data-testid` ile **birebir aynıdır** (`demo-app/web/src`, `demo-app/e2e/pages/**/locators.ts`).
Dinamik kimlikler aynı önek şemasıyla öğe şablonunda bağlanır:

```xml
<o:OtomasyonGrubu AutomationProperties.AutomationId="{Binding Kod, StringFormat=product-card-{0}}">
```

| Ekran | Kimlikler |
|---|---|
| Üst menü | `nav-catalog`, `nav-cart` (içinde `cart-count`), `nav-orders`, `current-dealer`, `nav-logout` |
| Giriş | `login-username`, `login-password`, `login-submit`, `login-error` |
| Katalog | `product-list`, `product-card-<kod>`, `product-price-<kod>`, `qty-input-<kod>`, `add-to-cart` (kart içinde, her kartta aynı), `product-status-<kod>` |
| Sepet | `cart-table`, `cart-empty`, `cart-line-<kod>`, `cart-line-qty-<kod>`, `cart-line-free-<kod>`, `cart-line-total-<kod>`, `cart-line-remove-<kod>`, `cart-subtotal`, `cart-discount`, `cart-total`, `min-order-warning`, `checkout-error`, `checkout-submit` |
| Onay | `order-confirmation`, `order-number`, `order-discount`, `order-total`, `go-orders`, `go-catalog` |
| Siparişlerim | `orders-table`, `orders-empty`, `order-row-<numara>`, `order-total-<numara>` |

Yalnız masaüstünde olan (bilerek eklenmiş) kimlikler: `app-window` (pencere), `page-login`,
`page-catalog`, `page-cart`, `page-order-confirmation`, `page-orders` (ekran kökleri),
`busy-indicator` (meşgul göstergesi). Bunlar `scripts/kimlik-kontrol.py` içinde izinli listededir;
başka her fazla ya da eksik kimlik betiği **1** ile bitirir. Betik bağımsızdır: web kimliklerini kendisi
toplar (`demo-app/kimlikler.json`'a bağlı değildir; o dosya oluştuğunda ikisi aynı listeyi vermelidir).

Web'de kimliksiz olan elemanlara (sepet boşken "Kataloğa dön", sipariş satırındaki numara bağlantısı)
masaüstünde de kimlik verilmedi; bunlar UIA'da `Name` ile bulunur.

## UI Automation davranışı (test yazarı için)

- **Metinler:** doğrulanan metinler `OtomasyonMetni` (TextBlock) içindedir: UIA `Text` kontrolü,
  `Name` = görünen metin (ör. `cart-total` → `"150,00 TL"`, `cart-count` → `"7"`). Tutar biçimi web ile
  aynıdır (`1.250,00 TL`, tarih `8 Kas 2026 14:30`). Appium'da `getText()` / `getAttribute("Name")`.
- **Düğmeler:** UIA `Button`; `Name` = düğme metni (`checkout-submit` → `"Siparişi onayla"`, işlem
  sürerken `"Onaylanıyor…"`). Pasiflik `IsEnabled` ile (web'deki `disabled`) — `isEnabled()`.
  `nav-cart` düğmesinin adı `"Sepet"`tir, sayaç alt eleman `cart-count`'tadır.
- **Koşullu elemanlar gerçekten yok olur:** `login-error`, `min-order-warning`, `checkout-error`,
  `cart-empty`, `cart-table`, `orders-empty`, `orders-table`, `order-confirmation` koşul sağlanmadığında
  görsel ve UIA ağacında **bulunmaz** (WPF'nin `Collapsed` + `IsOffscreen` davranışı kullanılmaz;
  `Otomasyon/Kosullu`). "Görünmüyor" doğrulaması = eleman bulunamıyor.
- **Ekranlar:** aynı anda yalnız etkin ekran ağaçtadır (`page-*`). Pencere başlığı web'deki
  `document.title` ile aynıdır: `"Sepet · Bayi Sipariş Portalı"`.
- **Etkin menü:** etkin üst menü düğmesinin `ItemStatus`'u `"current"`dır (web: `aria-current="page"`).
- **Bildirim durumu:** `product-status-<kod>` metni boş olabilir (eleman her zaman vardır);
  `ItemStatus` = `"ok"` | `"err"` | `""`.
- **Bekleme:** bir API çağrısı sürerken pencerede `busy-indicator` bulunur, bitince ağaçtan çıkar.
  Önerilen bekleme: sonucu gösteren elemanı beklemek (ör. `order-number`); `busy-indicator`'ın
  kaybolması ek bir senkron noktasıdır. Not: UIA `Invoke` asenkron gönderildiği için tıklamadan hemen
  sonra gösterge henüz belirmemiş olabilir — "kayboldu" tek başına "iş bitti" demek değildir.
  `Thread.sleep` gerekmez.
- **Listeler sanallaştırılmaz:** `product-list`, `cart-table`, `orders-table` düz `StackPanel`/`WrapPanel`
  kullanan `OtomasyonListesi`'dir; tüm satırlar her zaman ağaçtadır. Varsayılan pencere 1200×860'tır;
  demo verisi (4 ürün) kaydırmasız sığar. Daha küçük ekranda kaydırma dışında kalan eleman `IsOffscreen`
  olur; kart/satır kapsayıcıları UIA `ScrollItem` desenini destekler (`ScrollIntoView`), yine de VM
  çözünürlüğünü ≥ 1280×900 tutmak fare tabanlı tıklamayı güvenli kılar.
- **Parola alanı:** `login-password` bir `PasswordBox`'tır; değer okunamaz (UIA `IsPassword`),
  `sendKeys` ile yazılır.

## Appium NovaWindows ile sürmek

Plan §2.7: Windows'ta Appium 3 + `appium-novawindows-driver` (UI Automation). Örnek yetenekler:

```json
{
  "platformName": "Windows",
  "appium:automationName": "NovaWindows",
  "appium:app": "C:\\bayi\\win-arm64\\BayiSiparis.exe",
  "appium:appArguments": "--api-url http://192.168.64.1:18081/api"
}
```

```java
driver.findElement(AppiumBy.accessibilityId("login-username")).sendKeys("bayi2");
driver.findElement(AppiumBy.accessibilityId("login-password")).sendKeys("…");
driver.findElement(AppiumBy.accessibilityId("login-submit")).click();
// ürün kartı kapsamında sepete ekle (web'deki `within: "product-card-"` karşılığı)
WebElement kart = driver.findElement(AppiumBy.accessibilityId("product-card-P-001"));
kart.findElement(AppiumBy.accessibilityId("qty-input-P-001")).clear();
kart.findElement(AppiumBy.accessibilityId("add-to-cart")).click();
```

`AppiumBy.accessibilityId` NovaWindows'ta UIA `AutomationId`'ye eşlenir. Her test uygulamayı yeniden
başlatır (bellekteki oturum çerezi kaybolur → giriş ekranı); sunucu tarafı sıfırlama web'deki gibi
`POST /test/reset` ile test altyapısından yapılır.

## Sınırlar / bilinen durumlar

- WPF kabuğu macOS'ta **yalnız derlenir**; çalıştırma ve UIA ağacının doğrulanması Windows gerektirir
  (CI `windows-latest` / Windows 11 ARM VM — Ş8/Ş9).
- Masaüstü uygulaması tek pencere ve gezinme geçmişi tutmaz (web'deki tarayıcı geri tuşu karşılığı yok).
