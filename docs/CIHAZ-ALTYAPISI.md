# Cihaz Altyapısı ve app-mcp

Mobil (Android, iOS) ve Windows masaüstü test yeteneğinin (specs/009-mobil-masaustu) yerel cihaz
katmanı ve doğrulama ajanının aracı **app-mcp**. Plan bağları: §2.6 (app-mcp araçları), §2.7
(koşum ortamı).

```
 core-worker ──app-mcp-net (internal)──▶ app-mcp ──cihaz-net──▶ host.docker.internal:4723
                                         (konteyner)              │ (Docker Desktop → host loopback)
                                                                  ▼
                                                     Appium 3 (127.0.0.1:4723, host)
                                                      ├─ uiautomator2 → AVD tp-android
                                                      ├─ xcuitest     → simülatör "TP iPhone"
                                                      └─ (novawindows → UTM Windows VM, ayrı adres)
```

## 1. Önkoşullar (bu Mac)

| Bileşen | Beklenen |
|---|---|
| Node | 22 LTS (global npm paketi gerekmez) |
| Java | 17 (Android araçları + Ş3 Java testleri) |
| Android SDK | `~/Library/Android/sdk` (`ANDROID_HOME` ile değiştirilebilir): `emulator`, `platform-tools`, `cmdline-tools/latest`, arm64 sistem imajı (android-36) |
| Xcode | 26+ (DeviceHub), en az bir iOS simülatör çalışma zamanı (18.x tercih) |
| Docker Desktop | konteyner → host Appium erişimi için |

## 2. Make hedefleri

| Hedef | İş |
|---|---|
| `make cihaz-kur` | Appium 3 + sürücüleri `tools/appium/` altına kurar (`npm ci`; `APPIUM_HOME` bu dizin), AVD `tp-android` ve simülatör `TP iPhone`'u yoksa oluşturur, `toolchain/app-mcp`'yi derler. İdempotent. |
| `make cihaz-baslat PLATFORM=android\|ios` | Cihazı açar (açıksa dokunmaz), animasyonları kapatır (Android), `demo-app/mobile/build/*.apk\|*.app` varsa kurar (yoksa uyarıp geçer), Appium'u `127.0.0.1:4723`'te başlatır (çalışıyorsa dokunmaz). `GORUNMEZ=1`: Android penceresiz, iOS Simulator penceresi açılmaz. |
| `make cihaz-durdur [PLATFORM=…]` | Appium + kanonik cihazları durdurur; `PLATFORM` verilirse yalnız o cihaz. |
| `make cihaz-durum` | Appium, cihazlar, uygulama kurulumu ve derlemeler (salt okuma). |
| `make cihaz-wda` | iOS WebDriverAgent ön derlemesi (bkz. §4). |
| `make cihaz-ag` | Konteyner → `host.docker.internal:4723` erişimini ve LAN'dan erişilemezliği doğrular (bkz. §5). |

Durum dosyaları ve günlükler `var/cihaz/` altındadır (git dışı): `appium.pid`, `appium.log`,
`emulator.log`, `android.seri`, `ios.udid`, `wda-derleme.log`, `kanit/`.

## 3. Kanonik cihazlar

| Platform | Ad | Ayrıntı |
|---|---|---|
| Android | AVD `tp-android` | Kurulu arm64 imajdan: önce `google_apis`, yoksa `google_apis_playstore` (bu Mac'te: android-36 playstore), cihaz profili `pixel_7`, donanım GPU'su + donanım klavyesi açık |
| iOS | simülatör `TP iPhone` | `iPhone 16` tipi, kurulu iOS çalışma zamanlarından 18.x'in en yenisi (bu Mac'te 18.5); `TP_IOS_RUNTIME` ile değiştirilebilir |

Betikler yalnızca bu iki cihaza dokunur. Başka şeritlerin cihazları (ör. `tp-mobil-gelistirme`) ve
kullanıcının diğer AVD/simülatörleri seri numarası / UDID adıyla ayrılarak atlanır.

Uygulama kimliği `com.antreklabs.bayisiparis` (Android paketi, etkinlik `.MainActivity`; iOS bundle id
aynı). Betiklerde `TP_APP_PAKETI`, app-mcp'de `APP_ANDROID_PACKAGE` / `APP_ANDROID_ACTIVITY` /
`APP_IOS_BUNDLE_ID` ile değiştirilir (compose varsayılanları bunlardır). Derlemeler
`demo-app/mobile/build/bayi-siparis.apk` ve `BayiSiparis.app`; `cihaz-baslat` en yenisini kurar.

## 4. Appium (proje içi) ve WebDriverAgent

- Sürümler `tools/appium/package.json` + kilit dosyasında sabittir: `appium 3.9.0`,
  `appium-uiautomator2-driver 8.7.3`, `appium-xcuitest-driver 12.22.8` (sürücülerin 9.x/13.x
  hatları Appium 4 beta ister; Appium 3 ile uyumlu son sürümler seçildi).
- `APPIUM_HOME=tools/appium`: Appium kendi `package.json`'undaki sürücüleri bulur; global kurulum yok.
- Appium `--relaxed-security` olmadan koşar (adb shell vb. güvensiz özellikler kapalı).
- **WebDriverAgent:** xcuitest'in ilk oturumu WDA'yı xcodebuild ile derler (dakikalar). `make cihaz-wda`
  derlemeyi Xcode DerivedData önbelleğine alır; sonraki oturum açılışı ~20 sn'dir. Xcode sürümü
  değişince yeniden çalıştırın. Not: xcuitest 12.x `build-wda` betiği derleme bitince 13 koduyla
  çıkar ("unsettled top-level await"); betik başarıyı xcodebuild'in `** TEST BUILD SUCCEEDED **`
  satırından ölçer.
- iOS'ta cihaz **UDID ile** seçilir (`APP_IOS_UDID`, `var/cihaz/ios.udid`): xcuitest yalnız
  `deviceName` verilince o adda cihaz *tipi* arar ve "No supported device type named 'TP iPhone'"
  hatası verir.

## 5. Ağ kararı: Appium 127.0.0.1'de kalır

Doğrulama (`make cihaz-ag`, 2026-11-08):

```
• Konteynerden: http://host.docker.internal:4723/status (curlimages/curl:8.11.1)
✓ Konteyner → host.docker.internal:4723 erişilebilir
• Appium dinleme adresleri: 127.0.0.1:4723
✓ LAN adresinden (192.168.1.41:4723) erişilemez
```

- **Docker Desktop (macOS)** `host.docker.internal` bağlantılarını kendi süreciyle host'un
  loopback'ine vekiller. Bu yüzden Appium `127.0.0.1`'e bağlı kalır; `0.0.0.0` (tüm arayüzler)
  **gerekmez ve kullanılmaz** — LAN'daki başka bir makine Appium'a (dolayısıyla cihaza) ulaşamaz.
- **Internal Docker ağından host'a ulaşılamaz** (denendi: `--internal` ağda ad çözümü zaman aşımı;
  `--add-host host-gateway` ile de bağlantı reddi). Bu nedenle app-mcp iki ağdadır:
  `app-mcp-net` (internal; yalnız core-worker ↔ app-mcp) ve `cihaz-net` (internal değil; yalnız
  app-mcp, hosttaki Appium'a çıkış). `cihaz-net` teknik olarak internete de çıkış verir; app-mcp
  ise yalnızca yapılandırılmış `APPIUM_URL_*` adreslerine bağlanır, kod çalıştırma / ağ aracı yoktur.
  playwright-mcp'nin (kod çalıştırabilen) bulunduğu `mcp-net`'e app-mcp konmadı.
- Host'taki her konteyner (Docker Desktop VM'i) `host.docker.internal:4723`'e ulaşabilir; bu,
  LocalForge test-runner'ının (§2.7, tek ağ istisnası) da kullanacağı yoldur. Linux'ta (Docker
  Engine) aynı davranış yoktur: orada Appium `docker0`/host-gateway arayüzüne bağlanmalı ve
  güvenlik duvarıyla sınırlandırılmalıdır (bu Mac'te gerekmedi).
- Konteyner yolunun uçtan uca kanıtı: `var/cihaz/kanit/duman-android-konteyner-*.txt`.

### 5.1 test-runner → Appium: `appium-gw` (LocalForge Java koşusu, 009 §2.7)

test-runner koşan test kodunu (üretilmiş + elle yazılmış Java) çalıştırır; bu yüzden internete ve
hosta çıkışı yoktur (yalnız internal ağlar: `demo-net`, `runner-net`). Java koşusu ise hosttaki
Appium'a ulaşmalıdır ve internal ağdan host'a ulaşılamaz. En az yetkili çözüm:

```
test-runner ──appium-net (internal)──▶ appium-gw ──cihaz-net──▶ host.docker.internal:4723 (Appium)
```

- `appium-gw` (`mobil` profili) tek amaçlı bir TCP yönlendiricidir (`alpine/socat`, özetle sabit):
  `TCP-LISTEN:4723` → `TCP:host.docker.internal:4723`. Hedef komut satırında sabittir; gelen akış
  hedefi değiştiremez. Root değil (`65534`), salt okunur kök, tüm yetenekler düşürülmüş,
  `no-new-privileges`, 64 MB.
- test-runner `cihaz-net`'e **konmaz** (konsaydı internete çıkardı); yalnız `appium-net` eklenir.
  `APPIUM_URL_ANDROID|IOS=http://appium-gw:4723` (`TP_RUNNER_APPIUM_URL_*` ile değişir).
- **Windows (UTM VM): `appium-gw-windows`** (`mobil-windows` profili; VM yokken `mobil` profili
  etkilenmez). `appium-gw` ile aynı imaj ve sertleştirme; tek hedefi `TP_WINDOWS_VM_APPIUM`
  (varsayılan `192.168.64.2:4723`). Konteyner açılışında değer `host:port` biçiminde doğrulanır
  (`[A-Za-z0-9.-]+:<1–65535>`; virgül/boşluk vb. reddedilir → socat adres seçeneği enjekte
  edilemez; hatalı değerde çıkış kodu 64). test-runner'da `TP_RUNNER_APPIUM_URL_WINDOWS` varsayılan
  boştur (Windows Java koşusu sağlık kontrolünde `error`); açmak için
  `TP_RUNNER_APPIUM_URL_WINDOWS=http://appium-gw-windows:4723`. Uygulama yolu/argümanları:
  `TP_APP_PATH_WINDOWS`, `TP_APP_ARGS_WINDOWS`, `TP_APP_WORKDIR_WINDOWS` (→ e2e-app `APP_PATH`,
  `APP_ARGS`, `APP_WORKDIR`). Doğrulama (2026-11-09, yalıtılmış `tp-s10-gwtest` projesi): yedi
  hatalı hedef (`x:1,exec:sh`, portsuz, `:99999`, boşluklu, boş host, `-x:1`, satır sonuyla eklenmiş ikinci satır) 64 ile reddedildi;
  geçerli hedefle (`host.docker.internal:4723`, VM yerine) `appium-net`'ten
  `GET http://appium-gw-windows:4723/status` → `ready=true`; konteyner `65534`, salt okunur,
  `CapDrop=[ALL]`, `no-new-privileges`, 64 MB. **VM ile denenmedi:** Docker Desktop'ın konteynerden
  UTM ağına (`192.168.64.0/24`) yönlendirmesi doğrulanmadı ([WINDOWS-VM.md §5.3](WINDOWS-VM.md)).
- Uygulama demo API'ye emülatörden `10.0.2.2:8081` (host → compose `demo-app-web`) ile gider;
  testlerin `/test/*` çağrıları test-runner'dan doğrudan `demo-app-api:8000`'e (demo-net) gider.
  İkisi aynı API'dir; hosttaki geçici vekile (`127.0.0.1:18000`) bağımlılık yoktur.
- `make security-check` 2. madde: test-runner'dan `host.docker.internal:4723/8081`, internet,
  postgres, core-api, playwright-mcp kapalı; `appium-gw` çalışıyorsa `appium-gw:4723`,
  `appium-gw-windows` çalışıyorsa `appium-gw-windows:4723` açık olmalı.

Doğrulama (2026-11-08, yalıtılmış `tp-s8` yığını, test-runner içinden TCP denemesi):

```
1.1.1.1:443 ERR_ENETUNREACH          example.com:443 ERR_EAI_AGAIN
host.docker.internal:4723 ERR_EAI_AGAIN   host.docker.internal:8081 ERR_EAI_AGAIN
testingprobe-postgres-1:5432 ERR_EAI_AGAIN
appium-gw:4723 OPEN   →  GET http://appium-gw:4723/status: ready=true (Appium 3.9.0)
demo-app-api:8000 OPEN
```

**Kalan risk (bilinçli):** appium-gw TCP hedefini sabitler ama Appium API'sini sınırlamaz. Appium
oturumu açabilen test kodu cihazı sürebilir; `appium:app` yeteneğine URL verilirse Appium hostu
dosyayı indirir (hostun ağına SSRF / sızdırma yolu) ve emülatörün kendi internet çıkışı vardır.
Koşan kod `/check` yolunda bağımlılık kilidi + Java AST koruması (üretilen testler) ve insan onaylı
PR'dan gelir; ancak test-runner `/run` bu korumayı kendisi yinelemez (yalnızca pom/.mvn kilidi) ve
runner-net'ten (toolchain-worker) çağrılır. Appium `--relaxed-security` olmadan koşar (`mobile:
shell` vb. kapalı). Sertleştirme seçenekleri (yapılmadı): Appium önünde `app` yeteneğini süzen
vekil; emülatörü ağsız açmak (uygulama API'ye `10.0.2.2` IP'siyle gider).

## 6. app-mcp (`toolchain/app-mcp/`)

Kendi MCP sunucumuz (Node 22 + TypeScript, `@modelcontextprotocol/sdk` 1.32, streamable HTTP
`/mcp`, durumlu oturum). Appium'a WebdriverIO 9 (`remote`, W3C) ile bağlanır. Hazır Appium MCP'leri
ekran görüntüsü, kod çalıştırma ve dosya araçlarını kapatılamaz biçimde açtığı için kullanılmadı.

### 6.1 Araçlar (kapalı liste)

Argüman adları Playwright MCP eşleriyle aynıdır; şemalar kapalıdır (`additionalProperties: false`,
bilinmeyen argüman = hata). `filename` gibi dosyaya yazan argüman yoktur.

| Araç | Argümanlar | Döner |
|---|---|---|
| `app_launch` | `platform: "android"\|"ios"\|"windows"` (zorunlu), `reset?: boolean` | Uygulamayı sıfırdan başlatır: oturum yoksa Appium oturumu açar; aynı platformda tekrar çağrıda uygulamayı kapatıp açar; `reset=true` uygulama verisini temizleyerek yeni oturum açar (Android: `noReset=false` → `pm clear`). Uygulama kimliği **yapılandırmadan** gelir. + snapshot |
| `app_snapshot` | — | Erişilebilirlik ağacı (salt okuma) |
| `app_click` | `ref`, `element?` | Dokunur/tıklar + durulmuş snapshot |
| `app_type` | `ref`, `text` (≤2000), `element?` | Alanı temizler, yazar. Parola alanında yazılan metin hiçbir çıktıda (sonuç, hata) yer almaz: `Yazıldı: *** → …` |
| `app_select_option` | `ref`, `values: [tek değer]`, `element?` | iOS çark: değer doğrudan; açılır liste (Android Spinner, Windows ComboBox): aç → seçeneği görünen adıyla bul → tıkla |
| `app_wait_for` | `text` \| `textGone` \| `time` (tam olarak biri) | Metin görünür/kaybolur (500 ms yoklama) ya da süre; üst sınır `APP_MCP_WAIT_MAX_S` (10 sn) |
| `app_generate_locator` | `ref`, `element?` | `### Locator\n{"platform","strategy","id"}`; Android `strategy:"id"`, iOS/Windows `"accessibilityId"`; kimlik yoksa `id:null` + uyarı (çekirdek bunu eksik locator sayar) |
| `app_screenshot` | — | PNG (image içerik). **Yalnız çekirdeğin canlı görünüm kanalı**; ajanın izin listesine girmez, çekirdekte `FORBIDDEN_TOOLS`'a eklenecek (Ş6) |

`ref` biçimi `^e\d{1,6}$`. Yok: kod/script çalıştırma, `mobile:`/`execute`, uygulama kurma/kaldırma,
dosya push/pull, serbest XPath sorgusu, ham kaynak dökümü. (`mobile: terminateApp/activateApp`
yalnızca sunucu içinde, sabit adla ve yapılandırılmış uygulama kimliğiyle çağrılır.)

Hatalar `isError: true` ve tek biçimde döner: `### Hata\n<mesaj>` (ör. `ref e12 son snapshot'ta
yok; app_snapshot ile güncel ref alın`, `Uygulama başlatılmadı: önce app_launch çağırın`,
`android cihazı başka bir MCP oturumunda kullanılıyor…`). Sürücü hatalarının yalnız ilk satırı
gösterilir (yığın / iç yol yok).

### 6.2 Snapshot biçimi

Sonuç metni Playwright MCP'ye benzer bölümlerdir; snapshot satır içi ```` ```yaml ```` bloğundadır
(çekirdeğin `is_inline_snapshot` / `snapshot_lines` / `locate_line` ayrıştırıcılarıyla uyumlu):

~~~
### Sonuç
Tıklandı: Giriş yap [ref=e7]
### Uygulama
- Platform: android
- Uygulama: com.antreklabs.bayisiparis
### Snapshot
```yaml
- <rol> "<ad>" [id=<kimlik>] [password] [disabled] [checked] [selected] [ref=eN]: <değer>
```
~~~

- **Rol** üç platformda ortaktır: `button, link, textbox, text, heading, checkbox, switch, radio,
  combobox, option, list, listitem, image, slider, progressbar, tablist, tab, navigation, menu,
  menuitem, window, group …` (Android sınıf adı / iOS `XCUIElementType…` / UIA ControlType'tan).
- **Kimlik** `[id=…]`: Android `resource-id` (RN `testID`), iOS `accessibilityIdentifier` (`name`;
  label'a eşitse kimlik sayılmaz), Windows `AutomationId`.
- **Sadeleştirme:** görünmeyen (`displayed/visible=false`, `IsOffscreen`), sıfır boyutlu, klavye /
  başlık çubuğu / kaydırma çubuğu alt ağaçları, adsız resimler ve anlamsız düzen kapları atılır.
  Adsız düğme/satırın adı alt metinlerinden hesaplanır ve o metinler ayrıca basılmaz. Kimlikli tek
  çocuklu sarmalayıcı kimliğini çocuğa devreder (RN: `<View testID="cart-total"><Text>…`).
  Parola alanının değeri her zaman `***`.
- **Ref'ler** oturum içinde kararlıdır: aynı eleman (kimlik + kaynak sırası, kimlik yoksa XPath;
  + rol + ad) sonraki snapshot'larda aynı `eN`'i alır; `app_launch` sıfırlar. Eylemler yalnız son
  snapshot'taki ref'leri kabul eder. Ref → konum sunucuda tutulur: önce kimlik (Android
  `UiSelector().resourceId(…)`, iOS `name == …` yüklemi, Windows accessibility id) + sıra, olmazsa
  kaynaktan üretilmiş mutlak XPath.
- Eylem sonrası snapshot ekran **durulunca** alınır (art arda iki aynı kaynak, en çok 3 sn).
- Üst sınır: `APP_MCP_SNAPSHOT_MAX_SATIR` (400) / `APP_MCP_SNAPSHOT_MAX_KARAKTER` (40 000);
  aşılırsa `(Snapshot N satırda kesildi.)`.

**Android (gerçek, Ayarlar → Network & internet, app-mcp çıktısı):**

```yaml
- list [id=com.android.settings:id/content_parent] [ref=e33]:
  - button "Navigate up" [id=com.android.settings:id/action_bar] [ref=e34]
  - list [id=com.android.settings:id/recycler_view] [ref=e5]:
    - button "Internet AndroidWifi" [ref=e35]:
      - text "Internet" [id=android:id/title] [ref=e7]
      - text "AndroidWifi" [id=android:id/summary] [ref=e8]
    - button "Airplane mode" [ref=e37]:
      - text "Airplane mode" [id=android:id/title] [ref=e13]
      - switch [id=com.android.settings:id/switchWidget] [ref=e38]
```

**iOS (gerçek XCUITest kaynağı, Ayarlar; `test/fixtures/ios-ayarlar.snapshot.txt`):**

```yaml
- navigation [id=Settings] [ref=e1]:
  - heading "Settings" [ref=e2]
  - textbox "Search" [ref=e3]:
    - button "Dictate" [ref=e4]
- list [ref=e6]:
  - listitem [ref=e10]:
    - button "General" [id=com.apple.settings.general] [ref=e11]
  - listitem [ref=e12]:
    - button "Accessibility" [id=com.apple.settings.accessibility] [ref=e13]
```

**Bayi giriş ekranı (RN, elle yazılmış fikstür; iOS):**

```yaml
- heading "Bayi Sipariş Portalı" [ref=e1]
- textbox "Kullanıcı adı" [id=login-username] [ref=e2]: bayi3
- textbox "Parola" [id=login-password] [password] [ref=e3]: ***
- switch "Beni hatırla" [id=login-remember] [checked] [ref=e4]
- button "Giriş yap" [id=login-submit] [ref=e5]
- text "Kullanıcı adı veya parola hatalı" [id=login-error] [ref=e6]
- list [id=product-list] [ref=e10]:
  - group [id=product-card-P-001] [ref=e11]:
    - text "P-001" [ref=e12]
    - button "Sepete ekle" [id=add-to-cart] [ref=e13]
```

### 6.3 Yapılandırma (ortam)

| Değişken | Varsayılan | Not |
|---|---|---|
| `APPIUM_URL_ANDROID` / `_IOS` / `_WINDOWS` | — | Boş = platform kapalı. Compose: `http://host.docker.internal:4723` (Windows: VM adresi) |
| `APP_ANDROID_PACKAGE` (zorunlu), `APP_ANDROID_ACTIVITY`, `APP_ANDROID_APK`, `APP_ANDROID_UDID` | | Ajan uygulama seçemez |
| `APP_IOS_BUNDLE_ID` (zorunlu), `APP_IOS_UDID` (önerilir), `APP_IOS_APP`, `APP_IOS_DEVICE_NAME`, `APP_IOS_PLATFORM_VERSION` | | |
| `APP_WINDOWS_APP` (zorunlu: .exe yolu ya da AUMID), `APP_WINDOWS_ARGS` (→ `appium:appArguments`), `APP_WINDOWS_WORKDIR` (→ `appium:appWorkingDir`) | | NovaWindows. Yetenek adları sabit sürücü sürümünün (`appium-novawindows-driver@1.5.0`) README'si ve `lib/constraints.ts`'iyle doğrulandı. Sürücü `app` ve `appArguments`'ı PowerShell'de tek tırnak içine **kaçışsız** gömdüğü için (`Start-Process '<app>' -ArgumentList '<args>'`) üç değerde de tek tırnak (akıllı tırnaklar dahil) ve denetim karakteri reddedilir (e2e-app `SurucuFabrikasi` aynı kural) |
| `APP_MCP_HOST` / `APP_MCP_PORT` | `127.0.0.1` / `8932` | İmajda `0.0.0.0` |
| `APP_MCP_ALLOWED_HOSTS` | `127.0.0.1:<port>,localhost:<port>` | Host başlığı denetimi (DNS rebinding); compose: `app-mcp:8932,app-mcp` |
| `APP_MCP_IDLE_S` | 300 | Boşta kalan MCP oturumu + Appium oturumu kapanır; `newCommandTimeout = idle + 60` |
| `APP_MCP_WAIT_MAX_S` | 10 | `app_wait_for` üst sınırı (≤30) |
| `APP_MCP_OTURUM_ACMA_S` | 300 | Appium oturum açma zaman aşımı (ilk WDA derlemesi) |

### 6.4 Oturum yaşam döngüsü

- MCP oturumu başına bir `McpServer` + bir Appium oturumu. `DELETE /mcp`, bağlantı kapanışı, boşta
  zaman aşımı ya da SIGTERM'de Appium oturumu kapatılır.
- **Cihaz kilidi:** platform başına tek cihaz olduğundan aynı anda yalnız bir MCP oturumu bir
  platformu sürebilir; diğeri `isError` alır.
- Aynı oturumdaki araç çağrıları sıraya konur; en çok 8 eşzamanlı MCP oturumu; istek gövdesi ≤1 MiB.
- `/health` (GET) sağlık ucu.

### 6.5 Compose

Servis `app-mcp` (`profiles: [mobil]`; varsayılan `make up` yığınına girmez, mevcut servisler
etkilenmez): `docker compose --profile mobil up -d app-mcp`. core-worker'a `APP_MCP_URL=
http://app-mcp:8932/mcp` (`.env`'den değişir) ve `app-mcp-net` eklendi. Host'a port açılmaz.

**Yedek yol — app-mcp hostta süreç:** konteyner bir Appium adresine ulaşamazsa (ör. Windows VM,
WINDOWS-VM.md §5.1) app-mcp hostta koşar, core-worker ona `host.docker.internal` ile bağlanır:

```bash
cd toolchain/app-mcp && npm ci && npm run build
APPIUM_URL_WINDOWS=http://<VM-IP>:4723 APP_WINDOWS_APP='C:\tp\bayi\win-arm64\BayiSiparis.exe' \
  APP_MCP_HOST=127.0.0.1 APP_MCP_PORT=8932 APP_MCP_ALLOWED_HOSTS=host.docker.internal:8932 \
  node dist/src/index.js
# .env: APP_MCP_URL=http://host.docker.internal:8932/mcp → docker compose up -d core-worker
```

Docker Desktop `host.docker.internal` bağlantısını hostun loopback'ine vekillediği için süreç
`127.0.0.1`'de kalır (LAN'a açılmaz); `APP_MCP_ALLOWED_HOSTS` konteynerin gönderdiği Host başlığını
kabul eder. Doğrulama (2026-11-09, Android emülatörü ile): hostta `127.0.0.1:18934`'teki app-mcp'ye
bir konteynerden (`node:22` imajı, varsayılan köprü ağı) `DUMAN_MCP_URL=http://host.docker.internal:18934/mcp
node scripts/duman.mjs android` → `SONUÇ: BAŞARILI` (launch, snapshot, locator, tıklama, ekran
görüntüsü, geçersiz ref hata yolu). Linux'ta (Docker Engine) core-worker'a
`extra_hosts: host.docker.internal:host-gateway` ve hostta uygun bağlama adresi gerekir. İmaj
`toolchain/app-mcp/Dockerfile` (node:22 slim, sabit özet; derleme aşamasında birim testleri koşar;
`USER node`, salt okunur uygulama dizini). `make security-check` 6 ve 8'deki sır döngülerine app-mcp
eklendi (çalışıyorsa denetlenir).

### 6.6 Testler ve duman

- Birim: `cd toolchain/app-mcp && npm test` (node:test; sahte Appium katmanı; 78 test). Fikstürler
  `test/fixtures/`: **gerçek** `android-ayarlar.xml`, `android-ayarlar-arama.xml`, `ios-ayarlar.xml`
  (`scripts/kaynak-yakala.mjs` ile canlı cihazdan yakalandı) ve **elle yazılmış** RN/WPF Bayi
  giriş ekranları (`*-bayi-giris.xml`). Her fikstürün altın snapshot'ı `*.snapshot.txt`
  (determinizm testi; yenileme `ALTIN_GUNCELLE=1 npm test`).
- Duman (canlı cihaz): `make cihaz-baslat PLATFORM=android && node toolchain/app-mcp/scripts/duman.mjs
  android` — stok Ayarlar uygulamasını MCP istemcisiyle başlatır, snapshot alır, bir satıra tıklar,
  locator üretir, ekran görüntüsü alır, geçersiz ref hata yolunu dener. Kanıt
  `var/cihaz/kanit/duman-<platform>[-konteyner]-<zaman>.txt|.png`. Konteynerdeki app-mcp'ye karşı:
  `DUMAN_MCP_URL=http://127.0.0.1:<port>/mcp`.
- Windows dumanı: `APP_WINDOWS_APP=… node toolchain/app-mcp/scripts/duman.mjs windows` — stok
  uygulama olmadığı için yapılandırılmış uygulamayı başlatır, snapshot + locator + ekran görüntüsü
  alır, **tıklamaz**. Appium adresi `APPIUM_URL` ya da `http://$TP_WINDOWS_VM_APPIUM` (varsayılan
  `192.168.64.2:4723`); `APP_WINDOWS_ARGS` / `APP_WINDOWS_WORKDIR` geçer. Platform ortamı
  `scripts/duman-ortami.mjs`'tedir ve `test/duman.test.ts` cihazsız sınar (Windows demo akışı
  dahil: elle yazılmış UIA fikstürü üzerinde sahte NovaWindows ile).
- Demo uygulama dumanı: `node toolchain/app-mcp/scripts/duman-demo.mjs android|ios|windows` — Bayi Sipariş
  Portalı'nı `reset` ile başlatır, snapshot'ta giriş kimliklerini bulur, kullanıcı adı + parola yazar
  (parola çıktıda `***`), giriş yapar, kataloğu bekler ve "Sepete ekle" için
  `{"platform":"android","strategy":"id","id":"add-to-cart"}` (iOS ve Windows: `accessibilityId`)
  bekler. Windows'ta WPF uygulaması (`demo-app/desktop`, aynı kimlikler) varsayılan
  `C:\tp\bayi\win-arm64\BayiSiparis.exe` yolundan açılır; `APP_WINDOWS_ARGS='--api-url …'` ile API
  adresi verilebilir. Kanıt `var/cihaz/kanit/duman-demo-<platform>-<zaman>.txt`. **Windows dumanları
  gerçek VM'de henüz koşturulmadı.**

### 6.7 Çekirdek → yerel CI bağlantısı (Ş6b)

- `enqueue_ci(script_id)` platformu `script.platform`'dan alır (`run.ortam.platform`); uygulama
  platformunda `ci.run` toolchain `/check`'e `lang: "java"` + `platform` gönderir. Tam kapsamlı
  Java koşusu merge kapısının `local-ci-<platform>` kaydını yazar. Aynı commit'te web ve uygulama
  koşuları ayrı etkin koşudur (biri ötekini yutmaz).
- Kod üretimi yerel kontrolü ve kırarak doğrulama cihazda `repeat_each=1` koşar. Kırarak
  doğrulama kararı çekirdeğin sınıfı (her kırmızı assertion) + test-runner'ın
  `kirmizi_denetimi.ok`'udur.
- Java raporunda JSON yoktur: sonuçlar `run.junit`'ten okunur, test kimliği test-runner özetiyle
  aynı biçime çevrilir (`<Sınıf> › <metot>`, `src/test/java/…/<Sınıf>.java`). Böylece triage
  `run.json` `failure` girdisini (tür, kimlik, `evidence.page_source|screenshot`, `page_location`)
  bulur. Sözleşme testi: `core/tests/unit/features/triage/test_surefire_sozlesmesi.py`.
- Portal `pr_checks` LocalForge kapısıyla aynı kuralı (`forge.local_required_checks`) uygular.
- GitHub kipi: `TP_PLATFORMS=android,windows` → `mobil-android`, `masaustu-windows` zorunlu
  check (ruleset'e de eklenmeli). `ios` kabul edilmez (iş akışı `paths` süzgeçli, no-op deseni
  yok). Koşu platformun iş akışından (`mobil-android.yml` …) ve `<job>-results` artefaktındaki
  `surefire-reports/TEST-*.xml`'den alınır (`birim-raporlari/` sayılmaz).
- Yalıtılmış yığında uygulama demo API'ye hostun `DEMO_WEB_PORT`'u üzerinden gider: ana yığından
  farklı portta APK `EXPO_PUBLIC_API_URL_ANDROID=http://10.0.2.2:<port>/api` ile derlenmelidir.

## 7. Bilinen sorunlar / açık işler

1. **iOS + Xcode 26+ (DeviceHub) — macOS gizlilik izni. (Bu Mac'te çözüldü, 2026-11-10.)**
   xcuitest her oturumda simülatör tercihlerini `~/Library/Containers/com.apple.dt.Devices/…`
   altına yazar. Appium'u başlatan uygulamanın (Terminal / IDE) "diğer uygulamaların verilerine
   erişim" izni yoksa macOS bir izin penceresi açar ve dosya erişimi **yanıt verilene dek asılı
   kalır**; oturum açılışı zaman aşımına düşer (günlükte son satır `Updated … com.apple.iphonesimulator.plist`).
   Çözüm: Sistem Ayarları → Gizlilik ve Güvenlik → **Tam Disk Erişimi** (ya da **Uygulama
   Yönetimi**) altında Appium'u başlatan uygulamaya (burada VS Code) izin verin, **izinden önce
   başlamış Appium'u durdurup yeniden başlatın** (izin yeni süreçlere geçer). Çalışan bir Appium
   başka bir worktree'den başlatılmışsa `make cihaz-durdur` onu tanımaz (pid dosyası o
   worktree'dedir); süreci elle sonlandırın, sonra `make cihaz-baslat PLATFORM=ios`.
   Doğrulama (Xcode 27.2, iOS 18.5 simülatörü `TP iPhone`, xcuitest 12.22.8): izin sonrası
   `Updated DeviceHub preferences …` satırı anında geçti; WDA ilk oturumda derlenip **28 sn**'de
   hazır oldu, sonraki oturumlar birkaç saniyede açılıyor. `duman.mjs ios` (stok Ayarlar) 53 sn,
   `duman-demo.mjs ios` 11 sn BAŞARILI; Java referans paketi iOS'ta 17/17 yeşil (iki koşu).
2. **iOS'ta WDA'nın kaydırma ve klavye komutları RN ekranlarında işe yaramaz** (e2e-app'te aşıldı):
   `mobile: scroll toVisible` RN `ScrollView`'da "max scroll count reached" ile düşer (yalnız tablo
   hücrelerini tanır), `direction` kaydırması hiç kaydırmaz; `hideKeyboard` yalnızca klavyedeki
   "done" benzeri tuşa basarak kapatır — sayı klavyesinde (adet alanı) böyle tuş yoktur, giriş
   ekranının "next"/"go" tuşları ise eylem tetikler. e2e-app (`altyapi/Kaydirma`, `altyapi/Klavye`)
   iOS'ta kaydırma kabının kenar boşluğundan `mobile: dragFromToForDuration` sürüklemesi kullanır;
   katalog ekranı `keyboardDismissMode="on-drag"` olduğundan aynı sürükleme klavyeyi de kapatır.
3. **Port 4723 paylaşımı:** başka şeritler (Ş1/Ş3) de `127.0.0.1:4723` kullanır. `cihaz-baslat`
   çalışan bir Appium görürse yenisini başlatmaz (sahibi `make cihaz-durum`'da "harici süreç").
4. **Windows fikstürü elle yazıldı** (NovaWindows öznitelik adları — `Value.Value`,
   `Toggle.ToggleState`, `SelectionItem.IsSelected` — VM'de gerçek kaynakla doğrulanmalı;
   `docs/WINDOWS-VM.md`, Ş9).
5. **Çekirdek entegrasyonu (Ş6):** `ALLOWED_AGENT_TOOLS['verify_and_map_app']` = `app_screenshot`
   hariç yedi araç; `FORBIDDEN_TOOLS`'a `app_screenshot`; ref argümanı `ref` (Playwright 1.64
   `target` kullanır; `snapshot_refs.REF_ARGS` ikisini de tanır); locator çapraz kontrolü
   `app_generate_locator` JSON'undan.
