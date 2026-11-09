# Windows 11 ARM sanal makinesi (UTM) — yerel Windows masaüstü testi

Windows masaüstü uygulamasını (`demo-app/desktop`, WPF) bu Mac'te doğrulama ajanıyla (app-mcp) ve
Java testleriyle sürmek için UTM içinde Windows 11 ARM kurulumu. Plan: `specs/009-mobil-masaustu/plan.md`
§2.7 (K2: Docker'da Windows Apple Silicon'da KVM olmadığı için olmaz). Birincil Windows koşusu
GitHub'daki `masaustu-windows` iş akışıdır (`windows-latest`, x64); VM isteğe bağlıdır.

> **Durum (2026-11-09): bu rehberin hiçbir adımı henüz uçtan uca koşturulmadı.** Komutlar ve ortam
> adları depodaki koda göre doğrulandı (betik, compose, app-mcp yapılandırması, iş akışı); VM'in
> kendisi kurulmadı. Her bölümdeki **[denenmedi]** işareti, o adımın bu depoda hiç çalıştırılmadığını
> belirtir. İlk kurulumu yapan, sonucu bu belgeye işlemelidir.

```
 Mac (host)                                                    UTM "Shared Network" (192.168.64.0/24)
 ┌──────────────────────────────────────────────┐             ┌──────────────────────────────────────┐
 │ demo-app-web 127.0.0.1:8081 (compose)        │◀─ socat ────│ BayiSiparis.exe  (API: 192.168.64.1:  │
 │ socat 192.168.64.1:18081 → 127.0.0.1:8081    │   18081     │                   18081/api)          │
 │ app-mcp (konteyner) ─────── APPIUM_URL_WINDOWS ──────────▶│ Appium 3 + NovaWindows                │
 │ run-app-checks.sh windows ── APPIUM_URL ─────────────────▶│   <VM-IP>:4723 (güvenlik duvarı:     │
 │                                              │             │   yalnız 192.168.64.0/24)            │
 └──────────────────────────────────────────────┘             └──────────────────────────────────────┘
```

Kural: Mac tarafında hiçbir şey `0.0.0.0`'a bağlanmaz. Demo yığını `127.0.0.1`'de kalır; VM'e yalnızca
UTM köprü arayüzünün adresinden (ya da SSH tünelinden) erişim verilir.

## 1. Önkoşullar

| Bileşen | Beklenen |
|---|---|
| Mac | Apple Silicon, ≥ 16 GB bellek önerilir (VM 8 GB + Docker Desktop + Android emülatörü), ≥ 70 GB boş disk |
| Depo | `make up` çalışıyor (`demo-app-web` → `127.0.0.1:8081`); `curl http://127.0.0.1:8081/health` |
| .NET SDK | 8 veya üstü (Mac'te Windows yayını için; `demo-app/desktop/README.md`) |
| `socat` | `brew install socat` (yalnız socat yolu için) |
| Windows lisansı | aşağıda §2.2 |

## 2. UTM ve Windows 11 ARM **[denenmedi]**

### 2.1 UTM

```bash
brew install --cask utm
```

### 2.2 Kurulum görüntüsü ve lisans

Yalnızca Microsoft'un dağıttığı görüntüyü kullanın:

- Microsoft'un "Windows 11 for Arm-based PCs" indirme sayfasındaki ARM64 ISO'su
  (`https://www.microsoft.com/software-download/windows11arm64`), ya da
- **CrystalFetch** (`brew install --cask crystalfetch`): ISO'yu Microsoft'un güncelleme
  sunucularından indirip oluşturur.

Üçüncü taraf sitelerden ISO indirmeyin. **Lisans:** Windows 11 lisanslıdır; VM'i kurumun lisans
politikasına uygun bir anahtarla (ör. Windows 11 Pro / kurumsal toplu lisans) etkinleştirin.
Etkinleştirilmemiş kurulum teknik olarak çalışır ama bu, kullanım hakkı vermez — kurulumdan önce
lisans sorumlusuyla netleştirin. Lisans anahtarını depoya, `.env`'e veya bu belgeye yazmayın.

### 2.3 Sanal makine

UTM → **Create a New Virtual Machine** → **Virtualize** → **Windows**:

| Ayar | Değer | Neden |
|---|---|---|
| ISO | §2.2'deki ARM64 ISO | |
| "Install Windows 10 or higher" | açık | UTM TPM 2.0 + Secure Boot'u Windows 11 için ayarlar |
| "Install drivers and SPICE tools" | açık | ağ, ekran çözünürlüğü, pano için UTM Guest Tools |
| Bellek | ≥ 8192 MB | Appium + .NET uygulaması + UIA |
| CPU | 4 çekirdek | |
| Disk | 64 GB | |
| Ağ | **Shared Network** (varsayılan) | Mac VM'e `192.168.64.1` adresinden görünür; VM LAN'a doğrudan açılmaz (Bridged kullanmayın) |
| Ekran | çözünürlük ≥ 1280×900 (ör. 1440×900) | WPF penceresi 1200×860; daha küçük ekranda elemanlar `IsOffscreen` olur (`demo-app/desktop/README.md`) |

Kurulumdan sonra Windows içinde:

1. UTM Guest Tools kurulmadıysa: UTM araç çubuğu → CD simgesi → "Install Windows Guest Tools…".
2. Ayarlar → Sistem → Ekran: çözünürlüğü ≥ 1280×900, ölçek %100.
3. Ekranın kilitlenmemesi (UI Automation kilitli masaüstünde çalışmaz), yönetici PowerShell'de:

   ```powershell
   powercfg /change standby-timeout-ac 0
   powercfg /change monitor-timeout-ac 0
   ```

4. Ekran koruyucuyu ve oturum açılışında parola istemeyi kurum politikasına göre kapatın; Appium ve
   uygulama oturum açmış kullanıcının etkileşimli masaüstünde koşmalıdır (Windows hizmeti olarak değil).

## 3. Ağ

### 3.1 Adresler **[denenmedi]**

```bash
# Mac: UTM köprüsünün adresi (VM çalışırken var olur; genelde bridge100 → 192.168.64.1)
ifconfig | grep -B3 'inet 192.168.64.'
```

```powershell
# VM: kendi adresi (ör. 192.168.64.5) — aşağıda <VM-IP>
ipconfig | findstr IPv4
```

Adres `192.168.64.1` değilse aşağıdaki komutlarda gerçek değeri kullanın. UTM DHCP kira süresinden
sonra `<VM-IP>` değişebilir; değişince §5'teki ortam değerlerini güncelleyin.

### 3.2 Demo uygulamasını VM'e açmak (Mac) **[denenmedi]**

Compose `demo-app-web`'i yalnız `127.0.0.1:8081`'e bağlar; VM bu adrese ulaşamaz. Compose
değiştirilmez. İki yoldan birini seçin:

**Yol A — socat, yalnız köprü arayüzünde:**

```bash
socat TCP-LISTEN:18081,bind=192.168.64.1,fork,reuseaddr,range=192.168.64.0/24 TCP:127.0.0.1:8081
```

- `bind=192.168.64.1`: yalnız UTM köprüsünde dinler; LAN arayüzünde değil. `0.0.0.0` **kullanmayın**.
- `range=192.168.64.0/24`: başka kaynaktan gelen bağlantıyı reddeder.
- Yalnız `demo-app-web` (nginx) açılır: `/api/*` → demo API, `/api/test/*` nginx'te kapalıdır.
  Test uçları ve `DEMOAPP_TEST_TOKEN` VM'e hiç verilmez.
- Ön planda çalışır; iş bitince Ctrl+C. macOS güvenlik duvarı izin sorarsa yalnız bu süreç için verin.

Doğrulama:

```bash
lsof -nP -iTCP:18081 -sTCP:LISTEN        # 192.168.64.1:18081 görünmeli, *:18081 değil
```

**Yol B — SSH ters tüneli (Mac → VM):** VM'de OpenSSH Server gerekir (Ayarlar → Sistem → İsteğe
bağlı özellikler → OpenSSH Server; güvenlik duvarı kuralı §4.4'teki gibi `192.168.64.0/24` ile
sınırlanmalı). Mac'ten:

```bash
ssh -N -R 127.0.0.1:8081:127.0.0.1:8081 <windows-kullanicisi>@<VM-IP>
```

VM'in kendi `127.0.0.1:8081`'i Mac'teki `demo-app-web`'e gider; uygulamanın varsayılan adresi
(`http://127.0.0.1:8081/api`) değişmeden çalışır, §4.3'teki `appsettings.json` düzenlemesi gerekmez.
(`demo-app/desktop/README.md`'deki VM → Mac `ssh -L` yolu da çalışır, ama Mac'te Uzaktan Oturum
Açma'yı açar; bu rehber onu önermez.)

## 4. Windows içinde

### 4.1 Uygulamayı yayınlayıp VM'e taşımak **[denenmedi]**

Mac'te, self-contained ARM64 yayını (VM'e .NET kurmak gerekmez):

```bash
cd demo-app/desktop
scripts/yayinla.sh win-arm64              # → build/win-arm64/BayiSiparis.exe (+ appsettings.json)
cd ../..                                   # depo kökü
mkdir -p var/vm-paket/appium
ditto -c -k --keepParent demo-app/desktop/build/win-arm64 var/vm-paket/bayi-win-arm64.zip
cp tools/appium/package.json tools/appium/package-lock.json var/vm-paket/appium/   # node_modules taşınmaz
(cd var/vm-paket && zip -qr appium-paket.zip appium)
```

`var/` git dışıdır. Taşıma: UTM paylaşılan dizini ya da geçici bir HTTP sunucusu — yine yalnız köprü
adresinde, iş bitince kapatın:

```bash
python3 -m http.server 18090 --bind 192.168.64.1 --directory var/vm-paket
```

```powershell
New-Item -ItemType Directory -Force C:\tp | Out-Null
curl.exe -o C:\tp\bayi.zip   http://192.168.64.1:18090/bayi-win-arm64.zip
curl.exe -o C:\tp\appium.zip http://192.168.64.1:18090/appium-paket.zip
Expand-Archive C:\tp\bayi.zip   -DestinationPath C:\tp\bayi   -Force   # → C:\tp\bayi\win-arm64\BayiSiparis.exe
Expand-Archive C:\tp\appium.zip -DestinationPath C:\tp         -Force   # → C:\tp\appium\package.json
```

### 4.2 Node 22 ARM64 **[denenmedi]**

`nodejs.org` → Node.js **22** LTS → "Windows Installer (.msi)" **ARM64** sürümünü kurun (CI ile aynı ana
sürüm: `masaustu-windows.yml` `NODE_VERSION: "22"`). Yeni bir PowerShell'de: `node -v` → `v22.…`.

### 4.3 API adresi **[denenmedi]**

Uygulama API kökünü şu sırayla okur: `--api-url` argümanı > `BAYI_API_URL` ortamı > exe yanındaki
`appsettings.json` > `http://127.0.0.1:8081/api`. **app-mcp Windows'ta uygulamaya argüman geçirmez**
(`toolchain/app-mcp/src/yapilandirma.ts`: yalnız `appium:app`), bu yüzden ajan yolu için adres
`appsettings.json`'a yazılmalıdır (Yol A):

```powershell
@'
{ "BayiApi": { "TabanAdres": "http://192.168.64.1:18081/api" } }
'@ | Set-Content -Encoding utf8 C:\tp\bayi\win-arm64\appsettings.json
```

Yol B (SSH ters tüneli) kullanılıyorsa dosyaya dokunmayın. Elle deneme:
`C:\tp\bayi\win-arm64\BayiSiparis.exe` → `bayi1` ile giriş → katalog görünmeli.

### 4.4 Appium 3 + NovaWindows **[denenmedi]**

Sürümler GitHub iş akışıyla aynıdır: Appium `tools/appium/package-lock.json`'dan (`appium 3.9.0`),
NovaWindows `masaustu-windows.yml` → `NOVAWINDOWS_VERSION: "1.5.0"`.

```powershell
cd C:\tp\appium
npm ci --no-audit --no-fund --loglevel=error
$env:APPIUM_HOME = 'C:\tp\appium-home'
New-Item -ItemType Directory -Force $env:APPIUM_HOME | Out-Null
node C:\tp\appium\node_modules\appium\index.js driver install --source=npm appium-novawindows-driver@1.5.0
node C:\tp\appium\node_modules\appium\index.js driver list --installed
```

(`npm ci` kilit dosyasındaki uiautomator2/xcuitest sürücülerini de indirir; Windows'ta kullanılmazlar.
İş akışı da aynı şeyi yapar.)

Güvenlik duvarı — yalnız UTM ağından, **Appium'u ilk kez başlatmadan önce** (yönetici PowerShell):

```powershell
New-NetFirewallRule -DisplayName 'TP Appium 4723 (yalniz UTM agi)' -Direction Inbound -Action Allow `
  -Protocol TCP -LocalPort 4723 -RemoteAddress 192.168.64.0/24 -Profile Any
```

Appium'u ilk başlatışta Windows "erişime izin ver" penceresi açarsa **iptal edin**; ardından
node.exe için otomatik oluşturulan kuralları kaldırın (engelleme kuralı izin kuralından önce gelir,
izin kuralı ise tüm portları açar):

```powershell
Get-NetFirewallApplicationFilter -Program '*node.exe' | Get-NetFirewallRule | Remove-NetFirewallRule
```

Appium'u yalnız VM'in UTM adresinde başlatın (`0.0.0.0` değil; `--relaxed-security` yok), oturum açmış
kullanıcının PowerShell'inde:

```powershell
$env:APPIUM_HOME = 'C:\tp\appium-home'
node C:\tp\appium\node_modules\appium\index.js --address <VM-IP> --port 4723 --log-no-colors --log-timestamp
```

## 5. Mac tarafı yapılandırması

### 5.1 app-mcp (doğrulama ajanı) **[denenmedi]**

`.env`'e (compose `app-mcp` servisi bu adları okur; `docker-compose.yml`):

```bash
APPIUM_URL_WINDOWS=http://<VM-IP>:4723
APP_WINDOWS_APP='C:\tp\bayi\win-arm64\BayiSiparis.exe'
```

```bash
docker compose --profile mobil up -d app-mcp
```

Boş `APPIUM_URL_WINDOWS` = Windows platformu kapalı (varsayılan). `APP_WINDOWS_APP` zorunludur
(.exe yolu VM'deki yoldur, ya da AUMID); ajan başka uygulama seçemez. **Açık nokta:** app-mcp
konteyneri `cihaz-net` üzerinden çıkar; Docker Desktop konteynerinden UTM ağına (`192.168.64.0/24`)
erişim bu Mac'te denenmedi. Erişilemezse app-mcp'yi hostta süreç olarak koşturup doğrulayın
(`cd toolchain/app-mcp && npm run build`, `APPIUM_URL_WINDOWS=… APP_WINDOWS_APP=… node dist/src/index.js`;
varsayılan `127.0.0.1:8932`).

### 5.2 Java testleri (hosttan elle) **[denenmedi]**

Testler Mac'te koşar, Appium VM'dedir. `APP_PATH` VM'deki yoldur; adres argümanla verilir:

```bash
# /test/* için doğrudan API: demo-app/e2e-app/README.md'deki geçici tp-demo-api-vekil (127.0.0.1:18000)
export DEMOAPP_TEST_TOKEN="$(grep '^DEMOAPP_TEST_TOKEN=' .env | cut -d= -f2-)"   # ekrana yazdırmayın
export DEMO_API_URL=http://127.0.0.1:18000
export APPIUM_URL=http://<VM-IP>:4723
export APP_PATH='C:\tp\bayi\win-arm64\BayiSiparis.exe'
export APP_ARGS='--api-url http://192.168.64.1:18081/api'     # Yol B'de gerekmez
demo-app/ci/run-app-checks.sh windows -Dgroups=duman
```

### 5.3 Yerel kontrol (test-runner) — desteklenmiyor

test-runner yalnız internal ağlardadır; hosta tek çıkışı `appium-gw`'dir ve o yalnız
`host.docker.internal:4723`'e gider. `TP_RUNNER_APPIUM_URL_WINDOWS` (compose → test-runner
`APPIUM_URL_WINDOWS`) bu yüzden boştur ve VM adresi verilse de internal ağdan ulaşılamaz: Windows için
`local-ci-windows` yerelde üretilemez, Windows Java koşusu sağlık adımında `error` döner
([CIHAZ-ALTYAPISI.md §5.1](CIHAZ-ALTYAPISI.md)). Windows PR kanıtı GitHub'daki `masaustu-windows`
iş akışıdır.

## 6. Doğrulama listesi **[denenmedi]**

| # | Nerede | Komut | Beklenen |
|---|---|---|---|
| 1 | VM | `curl.exe http://192.168.64.1:18081/api/health` | 200 (Yol B'de `http://127.0.0.1:8081/api/health`) |
| 2 | Mac | `lsof -nP -iTCP:18081 -sTCP:LISTEN` | yalnız `192.168.64.1:18081` |
| 3 | Mac | `curl -s http://<VM-IP>:4723/status` | `"ready":true` |
| 4 | LAN'daki başka makine | `nc -z -w 2 <Mac-LAN-IP> 18081` | bağlantı kurulamaz |
| 5 | Mac | `demo-app/ci/run-app-checks.sh windows -Dgroups=duman` (§5.2) | `BUILD SUCCESS`; rapor `demo-app/e2e-app/target/surefire-reports/` |
| 6 | Mac | app-mcp Windows dumanı | **Henüz yok:** `toolchain/app-mcp/scripts/duman.mjs` ve `duman-demo.mjs` yalnız `android\|ios` kabul eder. Windows için bir duman eklenene dek 5. adım ve kod üretiminde ajanın ilk `app_launch` + `app_snapshot` adımları kanıttır |
| 7 | Mac | app-mcp `app_snapshot` çıktısı | `[id=login-username]` vb. kimlikler görünmeli; NovaWindows öznitelik adları (`Value.Value`, `Toggle.ToggleState`, `SelectionItem.IsSelected`) elle yazılmış fikstürle (`toolchain/app-mcp/test/fixtures/*-bayi-giris.xml`) karşılaştırılmalı, fark varsa fikstür ve ağaç dönüştürücüsü düzeltilmeli ([CIHAZ-ALTYAPISI.md §7](CIHAZ-ALTYAPISI.md) madde 3) |

## 7. Kapatma

Mac'te socat / SSH tüneli / `http.server` süreçlerini durdurun (Ctrl+C); VM'de Appium'u kapatın. Güvenlik
duvarı kuralını kaldırmak için: `Remove-NetFirewallRule -DisplayName 'TP Appium 4723 (yalniz UTM agi)'`.
`.env`'deki `APPIUM_URL_WINDOWS`'u boşaltıp `docker compose --profile mobil up -d app-mcp` ile Windows
platformunu kapatın.
