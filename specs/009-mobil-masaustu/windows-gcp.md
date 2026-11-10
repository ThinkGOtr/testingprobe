# 009 ek — Windows masaüstü testi için GCP Windows VM (sözleşme)

Karar (2026-11-10, kullanıcı): Android/iOS ileride Sauce Labs; Windows masaüstü (WPF) için GCP'de
**testin çalışabileceği en ucuz** Windows VM. VM yalnızca demo/test sırasında açılır.

## Kaynak

| Alan | Değer (varsayılan; ortamdan değiştirilebilir) |
|---|---|
| Proje | `testingprobe` (`TP_GCP_PROJECT`) |
| Ad | `tp-windows` (`TP_WINDOWS_VM_NAME`) |
| Bölge | `europe-west1-b` (`TP_WINDOWS_VM_ZONE`) — europe-west3'ten ucuz; aynı `default` VPC, tp-demo'ya iç IP ile ulaşır |
| Makine | `e2-medium` (`TP_WINDOWS_VM_MACHINE`); yetmezse `e2-standard-2` |
| İmaj | `windows-cloud/windows-2022` (Desktop Experience; Server Core WPF çalıştırmaz) |
| Disk | 50 GB `pd-standard` |
| Ekran | `--enable-display-device` (UI Automation + `get-screenshot`) |
| Ağ | `default`, geçici dış IP (yalnızca dışarı: indirme/klonlama). **Ağ etiketi yok** → yalnızca `default-allow-internal` (10.128.0.0/9) ve `default-allow-icmp` geçerli. RDP/4723 internete **açılmaz**; yeni GCP güvenlik duvarı kuralı **yok**. |
| Shielded VM | açık (secure boot, vTPM, integrity) |

## Metadata anahtarları (VM ← betik)

| Anahtar | Anlam | Varsayılan |
|---|---|---|
| `windows-startup-script-ps1` | `deploy/gcp/windows-vm/kurulum.ps1` içeriği; **her açılışta** koşar, idempotent | — |
| `tp-repo` | genel depo | `ThinkGOtr/testingprobe` |
| `tp-repo-ref` | dal/etiket (codeload zip ile indirilir, git gerekmez) | `dev` |
| `tp-izinli-kaynak` | Appium 4723'e Windows güvenlik duvarında izin verilen tek kaynak (tp-demo iç IP) | `10.156.0.2` |
| `tp-api-url` | uygulamanın varsayılan API adresi (`BAYI_API_URL`) | `https://bayi.testing-probe.antreklabs.com/api` |

## VM içi sözleşme (kurulum.ps1 sağlar)

- Yerel kullanıcı `tpotomasyon` (rastgele parola, VM dışına çıkmaz) + otomatik oturum açma; kilit
  ekranı/ekran koruyucu/uyku kapalı; ekran çözünürlüğü ≥ 1440×900.
- Appium 3.9.0 + appium-novawindows-driver 1.5.0 — depodaki `tools/appium` kilit dosyasıyla `npm ci`
  (APPIUM_HOME=`C:\tp\appium`); Node sürümü sabit + SHA256 doğrulamalı.
- Appium, `tpotomasyon` oturumunda (oturum açılışında zamanlanmış görev) `0.0.0.0:4723`'te.
  Windows güvenlik duvarı: 4723 gelen yalnızca `tp-izinli-kaynak`'tan.
- Uygulama: `C:\tp\uygulama\BayiSiparis.exe` (win-x64, self-contained yayın; `demo-app/desktop`).
- Hazır olunca seri porta (COM1) tek satır: `TP-WINDOWS-HAZIR appium=4723 uygulama=<yol> ref=<ref>`;
  hata: `TP-WINDOWS-HATA <adım> <mesaj>`. Sır seri porta yazılmaz.

## tp-demo tarafı (env)

```
COMPOSE_PROFILES=...,mobil-windows
TP_WINDOWS_VM_APPIUM=<tp-windows iç IP>:4723
TP_RUNNER_APPIUM_URL_WINDOWS=http://appium-gw-windows:4723
APPIUM_URL_WINDOWS=http://appium-gw-windows:4723        # app-mcp
APP_WINDOWS_APP=C:\tp\uygulama\BayiSiparis.exe
APP_WINDOWS_ARGS=--api-url https://bayi.testing-probe.antreklabs.com/api
```

## Komutlar (Mac, Makefile)

`make windows-vm-olustur | windows-vm-ac | windows-vm-kapat | windows-vm-durum | windows-vm-ekran |
windows-vm-sil` — tümü `gcloud`; `olustur`/`sil` onay ister (`EVET=1` ile atlanır), `DRY_RUN=1` yalnızca
komutu yazdırır.

## Maliyet (yaklaşık, liste fiyatı)

e2-medium europe-west1 ~0,04 $/sa + Windows lisansı → açıkken ~0,08–0,13 $/sa; 50 GB pd-standard ~2–3 $/ay
(kapalıyken de). Yalnızca demo sırasında açılırsa ayda birkaç dolar.
