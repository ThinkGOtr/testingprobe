# Windows masaüstü testi — GCP Windows VM (`tp-windows`)

Windows masaüstü uygulamasını (`demo-app/desktop`, WPF) GCP'deki yayın yığınından (`tp-demo`)
doğrulama ajanıyla (app-mcp) ve Java testleriyle (test-runner, `local-ci-windows`) sürmek için
**birincil canlı yol**. VM yalnızca demo/test sırasında açılır; geri kalan zamanda kapalıdır.

Sözleşme: [`specs/009-mobil-masaustu/windows-gcp.md`](../specs/009-mobil-masaustu/windows-gcp.md).
VM yaşam döngüsü: `deploy/gcp/windows-vm/` (`vm.sh`, `kurulum.ps1`, README) ve `make windows-vm-*`.
Yığının kendisi: [GCP-KURULUM.md](GCP-KURULUM.md). İsteğe bağlı yerel alternatif (Mac + UTM):
[WINDOWS-VM.md](WINDOWS-VM.md). Genel çerçeve: [MOBIL-MASAUSTU.md](MOBIL-MASAUSTU.md).

> **Durum (2026-11-10): uçtan uca henüz koşturulmadı.** Compose yapılandırması (`docker compose
> --profile mobil-windows config`), ortam geçişi ve tünel betiği birim testli
> (`core/tests/unit/platform/test_compose_windows_gcp.py`); VM'in kendisi ve tp-demo → tp-windows
> bağlantısı ilk kurulumda görülecek (§10).

---

## 1. Mimari

```
 Mac (operatör)                       GCP projesi testingprobe — `default` VPC (10.128.0.0/9)
 ┌───────────────────────┐           ┌──────────────────────────────────────────────────────────────┐
 │ make windows-vm-*     │─ gcloud ─▶│ tp-windows (europe-west1-b, e2-medium, Windows Server 2022)  │
 │ (oluştur/aç/kapat/    │           │  iç IP 10.132.x.x · etiket YOK · RDP/4723 internete kapalı   │
 │  durum/ekran/sil)     │           │  ┌────────────────────────────────────────────────────────┐ │
 │                       │           │  │ Appium 3 + NovaWindows 0.0.0.0:4723                    │ │
 │ (isteğe bağlı §7)     │           │  │  Windows güvenlik duvarı: 4723 yalnız 10.156.0.2'den   │ │
 │ windows-gcp-tunel.sh  │           │  │ BayiSiparis.exe (C:\tp\uygulama\) ── HTTPS ──┐          │ │
 │ 127.0.0.1:14723 ──IAP─┼──┐        │  └──────────────────────────────▲──────────────┼──────────┘ │
 └───────────────────────┘  │        │                                 │ TCP 4723     │ (dış IP,    │
                            │        │                                 │ kaynak       │  yalnız     │
                            │        │ tp-demo (europe-west3-a) iç IP 10.156.0.2      │  dışarı)    │
                            └───SSH─▶│  ┌──────────────────────────────┴───────────┐  │             │
                                     │  │ Docker Engine — cihaz-net (internal değil; │  │             │
                                     │  │ çıkış host IP'sine NAT → 10.156.0.2)       │  │             │
                                     │  │  appium-gw-windows (socat, tek hedef       │  │             │
                                     │  │   TP_WINDOWS_VM_APPIUM)                    │  │             │
                                     │  │     ▲ appium-net (internal)   ▲ cihaz-net  │  │             │
                                     │  │  test-runner               app-mcp         │  │             │
                                     │  │  (Java/TestNG)             (ajan aracı)    │  │             │
                                     │  │     │ demo-net: /test/reset, /test/break   │  │             │
                                     │  │     ▼                                       │  │             │
                                     │  │  demo-app-api ◀── demo-app-web ◀── edge ◀──┼──┘             │
                                     │  │  (aynı veritabanı)  (nginx /api)  (Caddy   │ https://bayi.  │
                                     │  │                                    443)    │ testing-probe. │
                                     │  └────────────────────────────────────────────┘ antreklabs.com │
                                     └──────────────────────────────────────────────────────────────┘
```

- **Komut yolu:** test-runner ve app-mcp → `appium-gw-windows:4723` → (Docker NAT, kaynak
  `10.156.0.2`) → `tp-windows:4723`. test-runner yalnız internal ağlardadır; VM'e, hosta ve internete
  doğrudan çıkamaz, tek yolu yönlendiricidir. Yönlendiricinin hedefi tek ve sabittir
  (`TP_WINDOWS_VM_APPIUM`, açılışta `host:port` biçimi doğrulanır).
- **Uygulama verisi:** `BayiSiparis.exe` tp-demo'nun dış kapısına konuşur
  (`--api-url https://bayi.testing-probe.antreklabs.com/api` → Caddy → demo-app-web nginx `/api/` →
  demo-app-api). Testlerin sıfırlama/kırılma çağrıları (`POST /test/reset`, `/test/break`, belirteçli)
  test-runner'dan **doğrudan** aynı demo-app-api'ye gider (`DEMO_API_URL=http://demo-app-api:8000`,
  demo-net). İkisi aynı veritabanıdır → test verisi tutarlı. Dış kapı `/api/test/*`'i kapatır
  (nginx 404), belirteç yalnızca demo-app-api ve test-runner'dadır.

## 2. Önkoşullar

- tp-demo [GCP-KURULUM.md](GCP-KURULUM.md) ile kurulu ve `https://bayi.testing-probe.antreklabs.com`
  açılıyor (Windows uygulaması bu adrese gider).
- Mac'te `gcloud` girişi ve projede Compute Admin (+ tp-demo'ya IAP SSH) yetkisi.
- Projenin `default` ağında `default-allow-internal` kuralı (10.128.0.0/9) var: tp-windows ağ etiketi
  taşımaz, tp-demo'dan gelen 4723 bu kuralla geçer. **Yeni GCP güvenlik duvarı kuralı açılmaz.**
- tp-demo'da Docker ağları 10.x VPC aralığıyla çakışmamalı (varsayılan havuz 172.17+/192.168 —
  `/etc/docker/daemon.json`'da `default-address-pools` 10.x verilmediyse sorun yok; §9).

## 3. VM'i aç (Mac)

```bash
cd ~/projects/agent-probe/testing-probe
make windows-vm-olustur          # ilk kez: VM + metadata (onay ister; EVET=1 atlar, DRY_RUN=1 yalnız yazdırır)
make windows-vm-bekle            # seri portta TP-WINDOWS-HAZIR satırını bekler (ilk açılış ~15-25 dk)
deploy/gcp/windows-vm/vm.sh ip   # iç IP (ör. 10.132.0.5) — aşağıda <winIP>
```

Sonraki demolarda VM silinmediyse: `make windows-vm-ac` + `make windows-vm-bekle` (kurulum betiği her
açılışta idempotent koşar; iç IP genelde aynı kalır, yine de `vm.sh ip` ile doğrulayın).

## 4. tp-demo `.env` (VM, bir kez)

```bash
gcloud compute ssh tp-demo --zone europe-west3-a --tunnel-through-iap     # Mac
cd /opt/testingprobe && nano .env                                          # tp-demo
```

`.env`'e ekleyin (`<winIP>` = §3'teki iç IP; `COMPOSE_PROFILES` zaten varsa değerin sonuna
`,mobil-windows` ekleyin):

```bash
# --- GCP Windows VM (docs/WINDOWS-GCP.md) ---
COMPOSE_PROFILES=mobil-windows
TP_WINDOWS_VM_APPIUM=<winIP>:4723
TP_RUNNER_APPIUM_URL_WINDOWS=http://appium-gw-windows:4723
APPIUM_URL_WINDOWS=http://appium-gw-windows:4723
APP_WINDOWS_APP=C:\tp\uygulama\BayiSiparis.exe
APP_WINDOWS_ARGS=--api-url https://bayi.testing-probe.antreklabs.com/api
TP_APP_PATH_WINDOWS=C:\tp\uygulama\BayiSiparis.exe
TP_APP_ARGS_WINDOWS=--api-url https://bayi.testing-probe.antreklabs.com/api
```

- `mobil-windows` profili `appium-gw-windows` ve `app-mcp`'yi başlatır. `mobil` profili **gerekmez**
  (tp-demo'da hostta Appium yok; `appium-gw` boşa açılır).
- `APP_WINDOWS_*` app-mcp'ye (ajanın başlatabileceği tek uygulama), `TP_APP_*_WINDOWS` test-runner'a
  (Java testleri → e2e-app `APP_PATH` / `APP_ARGS`) gider. Değerler tek tırnak ve denetim karakteri
  içeremez (NovaWindows PowerShell'e kaçışsız geçirir; app-mcp ve e2e-app reddeder).
- `--api-url` VM'deki varsayılanla (`tp-api-url` metadata → `BAYI_API_URL`) aynıdır; açıkça verilir ki
  oturum başka bir VM'e yönlense de doğru arka uca gitsin.
- `TP_PLATFORMS` bu iş için değişmez (yalnız GitHub kipindeki `masaustu-windows` zorunluluğunu açar).
- Sır yoktur; VM'e hiçbir sır gitmez.

## 5. Yığını yeniden başlat (tp-demo)

```bash
make up            # app-mcp imajı ilk kez derlenir; test-runner yeni ortamla yeniden oluşturulur
make status        # app-mcp ve appium-gw-windows "running" olmalı
docker compose logs appium-gw-windows --tail 20   # hatalı TP_WINDOWS_VM_APPIUM → açıklayıcı hata, çıkış 64
```

## 6. Windows kontrolünü koştur (tp-demo)

**6.1 Ağ** — test-runner ve app-mcp VM'in Appium'una yönlendiriciden ulaşıyor mu:

```bash
docker compose exec -T test-runner node -e \
  "fetch('http://appium-gw-windows:4723/status').then(r=>r.text()).then(console.log)"
docker compose exec -T app-mcp node -e \
  "fetch('http://appium-gw-windows:4723/status').then(r=>r.text()).then(console.log)"
# beklenen: {"value":{"ready":true,...}}
make security-check   # 2/izolasyon: appium-gw-windows erişilebilir, <winIP>:4723 test-runner'dan DOĞRUDAN engelli
```

**6.2 Java testleri (test-runner, `lang=java`, `platform=windows`)** — forge'daki `main` (ya da bir PR
head sha'sı) üzerinde tam kapsamlı koşu; sıfırlama ve isteğe bağlı kırılma test-runner'dan
demo-app-api'ye gider. Web e2e ile aynı anda koşturmayın (bayi kilitleri ortak değil).

```bash
docker compose exec -T toolchain-worker python - <<'EOF'
import json, time, httpx
govde = {"lang": "java", "platform": "windows", "sha": "main",
         "run_id": f"windows-elle-{int(time.time())}"}
# kırarak doğrulama: govde["break_campaign"] = True
r = httpx.post("http://test-runner:8200/run", json=govde, timeout=3600)
print(r.status_code)
print(json.dumps(r.json(), ensure_ascii=False, indent=1)[:4000])
EOF
```

Sonuç ve kanıt `tp_artifacts` volume'ünde `runs/<run_id>/` altındadır (Surefire özeti, `junit.xml`,
Allure, `kanit/`). Sağlık adımı Appium'a ulaşamazsa koşu `error` döner (triage: `environment`).
PR akışında aynı koşu toolchain-worker `/check` (`lang:"java"`, `platform:"windows"`) ile
`local-ci-windows` kaydını yazar ([MOBIL-MASAUSTU.md §7–8](MOBIL-MASAUSTU.md)).

**6.3 Doğrulama ajanı (app-mcp)** — portalda Windows platformlu bir case için "Kod üret"; ajan
`app_launch windows` ile yalnızca `APP_WINDOWS_APP`'i başlatır. Takılırsa `docker compose logs app-mcp`.

## 7. Mac'ten sürmek (isteğe bağlı tünel)

Geliştirme sırasında VM'i Mac'ten (duman betikleri, `run-app-checks.sh`) sürmek için tp-demo
üzerinden IAP SSH tüneli. VM'in güvenlik duvarı değişmez: bağlantı VM'e tp-demo'dan gelir.

```bash
scripts/cihaz/windows-gcp-tunel.sh        # iç IP: deploy/gcp/windows-vm/vm.sh ip ya da TP_WINDOWS_VM_IP
# = gcloud compute ssh tp-demo --zone europe-west3-a --tunnel-through-iap -- -N -L 127.0.0.1:14723:<winIP>:4723
# DRY_RUN=1 yalnız komutu yazdırır; yerel port TP_WINDOWS_TUNEL_PORT (14723). Ctrl+C kapatır.
curl -s http://127.0.0.1:14723/status     # başka bir kabukta
```

**Veri hedefi:** bu kipte Windows uygulaması yine **tp-demo'nun** arka ucuna konuşur. Mac'teki
testlerin sıfırlaması da tp-demo'ya gitmelidir, ama tp-demo'nun demo-app-api'si hosta port açmaz
(ikinci bir `-L` ile ulaşılacak `127.0.0.1` portu yoktur) ve dış kapı `/api/test/*`'i kapatır;
`DEMOAPP_TEST_TOKEN` da tp-demo'dan çıkarılmaz. Bu yüzden:

- Mac'ten yalnızca **sepet yalıtımıyla** koşun — sıfırlama yok, herkese açık API ile sepet boşaltılır,
  `sifir-veri` grubu atlanır, `BREAK_CAMPAIGN` olmaz:
  ```bash
  export APPIUM_URL=http://127.0.0.1:14723
  export APP_PATH='C:\tp\uygulama\BayiSiparis.exe'
  export APP_ARGS='--api-url https://bayi.testing-probe.antreklabs.com/api'
  export DEMO_API_URL=https://bayi.testing-probe.antreklabs.com/api
  export TP_E2E_NO_RESET=1
  demo-app/ci/run-app-checks.sh windows -Dgroups=duman
  ```
  `DEMO_API_URL`'i Mac'in yerel yığınına (`127.0.0.1:18000`) vermeyin: uygulama tp-demo'nun verisini
  görürken sıfırlama Mac'in veritabanına gider → tutarsız sonuç.
- **Tam kontrol** (sıfırlama + kırarak doğrula, `local-ci-windows`) **tp-demo'daki test-runner'dan**
  koşar (§6.2).
- app-mcp dumanı (Mac, `toolchain/app-mcp`):
  `TP_WINDOWS_VM_APPIUM=127.0.0.1:14723 APP_WINDOWS_ARGS='--api-url https://bayi.testing-probe.antreklabs.com/api' node scripts/duman-demo.mjs windows`.

## 8. Demo sonrası kapat (Mac)

```bash
make windows-vm-kapat      # VM durur; disk kalır (~2–3 $/ay). Silmek: make windows-vm-sil
```

VM kapalıyken tp-demo'da `appium-gw-windows` çalışmaya devam eder ama bağlantılar zaman aşımına düşer:
Windows Java koşusu sağlık adımında `error` döner, ajan Windows oturumu açamaz. Uzun süre
kullanılmayacaksa tp-demo `.env`'inden `mobil-windows`'u çıkarıp `docker compose --profile
mobil-windows stop appium-gw-windows app-mcp` ve `make up`. Tekrar açınca iç IP'yi doğrulayın (§3).

## 9. Maliyet (yaklaşık, liste fiyatı)

| Kalem | Açıkken | Kapalıyken |
|---|---|---|
| e2-medium europe-west1 + Windows Server lisansı | ~0,08–0,13 $/sa | 0 |
| 50 GB pd-standard | — | ~2–3 $/ay |
| Geçici dış IP (yalnız çıkış) | ~0,005 $/sa | 0 |

Yalnız demo/prova günlerinde açılırsa ayda birkaç dolar. tp-demo'nun maliyeti ayrıdır
([GCP-KURULUM.md §11](GCP-KURULUM.md)). Bütçe uyarısı önerilir.

## 10. Güvenlik

- **İnternete açık port yok:** tp-windows ağ etiketi taşımaz; RDP ve 4723 için GCP kuralı yoktur.
  Geçici dış IP yalnızca dışarı çıkış (indirme) içindir.
- **4723 yalnız tp-demo'dan:** Windows güvenlik duvarı kaynak `10.156.0.2` (metadata
  `tp-izinli-kaynak`). tp-demo'daki konteyner trafiği Docker NAT'ıyla bu adresle çıkar.
- **tp-demo tarafı yalıtım değişmedi:** test-runner yalnız internal ağlarda (demo-net, runner-net,
  appium-net); VM'e tek yolu `appium-gw-windows` (sabit hedef, root değil, salt okunur, yetkisiz).
  `make security-check` 2. kontrolü yönlendiriciyi pozitif, VM adresini doğrudan negatif denetler.
  Hosta yeni port açılmaz (1. kontrol: yalnız `edge` 80/443).
- **Kalan risk (Appium API'sinin kendisi):** Appium oturumu açabilen kod (test-runner'da koşan test,
  app-mcp) VM'de uygulama başlatabilir. Bu yüzden VM'de sır tutulmaz, yalnız demo süresince açıktır,
  ayrı makinedir; app-mcp uygulamayı yapılandırmadan sabitler. Ayrıntı:
  [CIHAZ-ALTYAPISI.md §5.1](CIHAZ-ALTYAPISI.md).
- `tpotomasyon` parolası VM dışına çıkmaz; seri porta sır yazılmaz.

## 11. Sorun giderme

| Belirti | Neden / çözüm |
|---|---|
| `make windows-vm-bekle` bitmiyor | Seri çıktıya bakın: `gcloud compute instances get-serial-port-output tp-windows --zone europe-west1-b --port 1 \| grep TP-WINDOWS`. `TP-WINDOWS-HATA <adım> <mesaj>` hangi adımın düştüğünü söyler. |
| Masaüstü/uygulama ne durumda | `make windows-vm-ekran` (ekran görüntüsü; `--enable-display-device` sayesinde). Kilit ekranı görünüyorsa otomatik oturum açma bozulmuştur → `make windows-vm-kapat && make windows-vm-ac`. |
| 6.1 `fetch` zaman aşımı | VM kapalı / hazır değil (`make windows-vm-durum`), `TP_WINDOWS_VM_APPIUM` yanlış IP (`vm.sh ip`), ya da Windows güvenlik duvarındaki izinli kaynak tp-demo'nun iç IP'si değil (tp-demo yeniden oluşturulduysa IP değişmiş olabilir → `tp-izinli-kaynak` metadata'sını güncelleyip VM'i yeniden başlatın). |
| 6.1 `ECONNREFUSED` | Appium VM'de çalışmıyor (oturum açılmadı). `make windows-vm-ekran`; seri çıktıda `TP-WINDOWS-HAZIR` var mı. |
| `appium-gw-windows` sürekli yeniden başlıyor, log: "host:port biçiminde olmalı" | `.env`'deki `TP_WINDOWS_VM_APPIUM` değeri (boşluk, `http://` öneki vb.). Yalnız `10.132.x.x:4723`. |
| tp-demo konteynerinden 10.132.x.x'e ulaşılamıyor ama host'tan ulaşılıyor (`nc -z <winIP> 4723`) | Bir Docker ağı VPC aralığıyla çakışıyor: `docker network inspect $(docker network ls -q) \| grep Subnet`. `daemon.json`'da 10.x havuzu varsa 172.x'e çekin. |
| Küçük istekler geçiyor, ekran görüntüsü/sayfa kaynağı takılıyor | MTU (GCP VPC 1460, Docker köprüsü 1500). TCP MSS genelde bunu çözer; olmazsa cihaz-net'e `driver_opts: {com.docker.network.driver.mtu: "1460"}` verip `make up`. |
| Uygulama "sunucuya ulaşılamıyor" | VM'den dış kapıya çıkış: `https://bayi.testing-probe.antreklabs.com/api/health`. `APP_WINDOWS_ARGS` / `TP_APP_ARGS_WINDOWS` doğru mu. |
| Java koşusu `error`, "APPIUM_URL_WINDOWS yapılandırılmamış" | `TP_RUNNER_APPIUM_URL_WINDOWS` verilmemiş ya da test-runner yeniden oluşturulmamış (`make up`). |
| Testler sıfırlanmamış veriyle kırmızı | Koşu Mac'ten tam kipte yapılmış (§7) ya da web e2e ile eşzamanlı. Tam kontrolü tp-demo'dan koşun. |
