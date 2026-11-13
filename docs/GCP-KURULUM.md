# AI Testing Probe — GCP'de yayın (tek VM)

Bu doküman, yerelde `make up` ile çalışan sistemin tamamını Google Cloud'da tek bir sanal makinede
(Compute Engine VM) yayına almak içindir. Komutlar sırayla, kopyala-yapıştır çalıştırılacak şekilde
yazıldı. Her bölümün başında komutun **nerede** çalışacağı yazar: **Mac** (kendi bilgisayarın) ya da
**VM** (GCP'deki makine, SSH ile bağlanılmış).

Toplam süre: ~45–60 dk (çoğu ilk derleme beklemesi).

---

## 0. Mimari kararı — neden tek VM

| Seçenek | Uygun mu | Neden |
|---|---|---|
| **Compute Engine VM + Docker Compose** | ✅ seçilen | Sistem 11 servis, 5 yalıtılmış (`internal`) ağ ve servisler arası paylaşılan volume'ler (forge, artefaktlar, kontrol dosyaları) kullanır; locator demosu host'ta çalışan bir izleyiciyle (`demo-web-sync`) container'ı yeniden derler. VM'de yerel kurulum birebir çalışır, kod değişikliği gerekmez. |
| Cloud Run | ❌ | Paylaşılan volume, yalıtılmış ağlar ve container yeniden derleme yok. |
| GKE | ❌ (şimdilik) | Çalışır ama ağ politikaları, PVC'ler ve izleyici için ayrı iş; demo için gereksiz maliyet ve karmaşıklık. |

Dış dünyaya yalnızca bir **dış kapı** açılır: Caddy (`deploy/gcp/docker-compose.gcp.yml`).

- 443 (HTTPS) ve 80 (yalnızca Let's Encrypt doğrulaması + https'e yönlendirme).
- Sertifika Let's Encrypt'ten otomatik alınır ve yenilenir.
- Kapıda ayrı bir kimlik doğrulama yoktur; giriş portal ve bayi uygulamasının kendi ekranlarıyla yapılır.
- Diğer bütün portlar (Postgres, core-api, jira-sim…) yerelde olduğu gibi yalnızca `127.0.0.1`'dedir.
  `make security-check` bunu denetler (yalnızca `edge` 80/443 istisnadır).

Yayına çıkan adresler (`antreklabs.com` DNS'i odeaweb cPanel'de; §3.3'te iki `A` kaydı eklenir):

| Adres | Ne |
|---|---|
| `https://testing-probe.antreklabs.com` | Review portal (8 rol: Sistem Yöneticisi, Denetçi, Analist, PO, Testçi, Automation Engineer, Developer, Görüntüleyici) |
| `https://bayi.testing-probe.antreklabs.com` | Demo uygulaması (Bayi Sipariş Portalı) |

Jira (iyzitrace.atlassian.net), Xray, GitHub (ThinkGOtr/testingprobe-demo-app + Actions), Sauce ve
Anthropic zaten bulutta; VM onlara yalnızca dışarı doğru bağlanır.

---

## 1. Önkoşullar (Mac)

1. Faturalandırması açık bir GCP projesi ve o projede **Owner** (ya da Compute Admin + IAP-secured
   Tunnel User) yetkisi.
2. `gcloud` CLI:
   ```bash
   brew install --cask google-cloud-sdk
   gcloud --version
   ```
3. **Yerel stack'i durdur.** Aynı Jira projesini ve GitHub reposunu iki ayrı ortam aynı anda yoklarsa
   PO onayları, CI sonuçları ve PR'lar iki kez işlenir:
   ```bash
   cd ~/projects/agent-probe/testing-probe && make down
   ```

---

## 2. Değişkenler (Mac)

Bu terminal oturumu boyunca kullanılacak. `PROJECT_ID`'yi kendi projenle değiştir.

```bash
export PROJECT_ID="antreklabs-main-project"   # gcloud projects list ile doğrula
export REGION="europe-west3"          # Frankfurt
export ZONE="europe-west3-a"
export VM="tp-demo"
```

---

## 3. GCP projesini hazırla (Mac)

```bash
gcloud auth login
gcloud config set project "$PROJECT_ID"
gcloud services enable compute.googleapis.com iap.googleapis.com
```

### 3.1 Sabit dış IP

VM durdurulup başlatılsa da adres (ve sertifika) değişmesin diye:

```bash
gcloud compute addresses create tp-demo-ip --region "$REGION"
export IP="$(gcloud compute addresses describe tp-demo-ip --region "$REGION" --format='value(address)')"
echo "$IP"
```

### 3.2 Güvenlik duvarı

```bash
# HTTPS + Let's Encrypt doğrulaması (80) — yalnızca dış kapı etiketli makineye
gcloud compute firewall-rules create tp-demo-web \
  --network default --direction INGRESS --action ALLOW \
  --rules tcp:80,tcp:443 --source-ranges 0.0.0.0/0 --target-tags tp-demo-web

# SSH yalnızca Google IAP üzerinden (makinenin 22'si internete açılmaz)
gcloud compute firewall-rules create tp-demo-ssh-iap \
  --network default --direction INGRESS --action ALLOW \
  --rules tcp:22 --source-ranges 35.235.240.0/20 --target-tags tp-demo-ssh
```

> `default` ağında projeyle gelen `default-allow-ssh` kuralı 22'yi herkese açar. Bu projede başka
> makine yoksa kapatman önerilir: `gcloud compute firewall-rules delete default-allow-ssh`

### 3.3 DNS kayıtları (cPanel — tarayıcı)

`antreklabs.com`'un ad sunucuları `de1/de2.odeaweb.com`; kayıtlar cPanel'den eklenir. **"Domains →
Create A New Domain" kullanma** (o, cPanel sunucusunda site açar); yalnızca DNS kaydı eklenecek.

1. cPanel → **Zone Editor** (Tools araması: "Zone") → `antreklabs.com` satırında **Manage**.
2. **Add Record** → **A**:
   - Name: `testing-probe` (cPanel sonuna `.antreklabs.com.` ekler)
   - TTL: `300`
   - Record: §3.1'de yazdırılan `$IP`
3. Bir **A** kaydı daha:
   - Name: `bayi.testing-probe`
   - TTL: `300`
   - Record: aynı `$IP`
4. Doğrula (Mac; birkaç dakika sürebilir):
   ```bash
   dig +short A testing-probe.antreklabs.com @de1.odeaweb.com
   dig +short A bayi.testing-probe.antreklabs.com @de1.odeaweb.com
   ```
   İkisi de `$IP`'yi göstermeden §8'e (ilk `make up`) geçme: Caddy sertifikayı ilk açılışta ister.

---

## 4. VM'i oluştur (Mac)

`e2-standard-4` = 4 vCPU, 16 GB bellek (sistem Docker'a en az 8 GB ister; Playwright, Postgres ve
derlemeler aynı makinede). Disk 100 GB (en az 30 GB boş ister; imajlar + artefaktlar).

```bash
gcloud compute instances create "$VM" \
  --zone "$ZONE" \
  --machine-type e2-standard-4 \
  --image-family ubuntu-2404-lts-amd64 --image-project ubuntu-os-cloud \
  --boot-disk-size 100GB --boot-disk-type pd-balanced \
  --address "$IP" \
  --tags tp-demo-web,tp-demo-ssh \
  --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring
```

Bağlan:

```bash
gcloud compute ssh "$VM" --zone "$ZONE" --tunnel-through-iap
```

İlk bağlantıda SSH anahtarı oluşturulur (parola sorarsa boş bırakabilirsin).

---

## 5. Makineyi hazırla (VM)

### 5.1 Docker Engine + Compose

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl make git jq python3
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Log dosyaları diski doldurmasın:

```bash
echo '{"log-driver":"json-file","log-opts":{"max-size":"20m","max-file":"3"}}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
sudo usermod -aG docker "$USER"
exit
```

`docker` grubunun geçerli olması için **çıkıp yeniden bağlan** (Mac'te):

```bash
gcloud compute ssh "$VM" --zone "$ZONE" --tunnel-through-iap
```

Kontrol (VM):

```bash
docker version --format '{{.Server.Version}}' && docker compose version
```

### 5.2 uv (isteğe bağlı)

Yalnızca `make demo-prova` (tam prova) ve `make eval-live` (canlı model değerlendirmesi) için gerekir:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 5.3 Kodu indir

```bash
sudo mkdir -p /opt/testingprobe && sudo chown "$USER": /opt/testingprobe
git clone --branch main https://github.com/ThinkGOtr/testingprobe.git /opt/testingprobe
cd /opt/testingprobe && git log --oneline -1
```

---

## 6. Sırları taşı (Mac → VM)

`.env` git'te yoktur ve olmamalıdır (repo public). Mac'teki dolu `.env`'yi IAP tüneliyle kopyala
(Mac'te, **yeni bir terminalde**; §2 değişkenlerini yeniden `export` et):

```bash
gcloud compute scp --zone "$ZONE" --tunnel-through-iap \
  ~/projects/agent-probe/testing-probe/.env "$VM":/tmp/tp.env
```

VM'de yerine koy ve yalnızca senin okuyabileceğin hale getir:

```bash
mv /tmp/tp.env /opt/testingprobe/.env && chmod 600 /opt/testingprobe/.env
```

---

## 7. GCP ayarlarını `.env`'ye ekle (VM)

```bash
cd /opt/testingprobe
PORTAL=testing-probe.antreklabs.com
BAYI=bayi.testing-probe.antreklabs.com
```

Ayarları ekle (`TP_ACME_EMAIL`'i kendine göre değiştir):

```bash
sed -i '/^TP_TRUSTED_PROXIES=/d' .env
cat >> .env <<EOF

# --- GCP yayını (docs/GCP-KURULUM.md) ---
COMPOSE_FILE=docker-compose.yml:deploy/gcp/docker-compose.gcp.yml
TP_PORTAL_HOST=${PORTAL}
TP_DEMO_HOST=${BAYI}
TP_ACME_EMAIL=gokhan.sipahi@antreklabs.com
TP_ALLOWED_ORIGINS=https://${PORTAL}
TP_PUBLIC_BASE_URL=https://${PORTAL}
TP_MCP_PUBLIC_URL=https://${PORTAL}/api/mcp
TP_SESSION_COOKIE_SECURE=true
TP_TRUSTED_PROXIES=review-portal,edge
EOF
grep -E '^(COMPOSE_FILE|TP_PORTAL_HOST|TP_DEMO_HOST|TP_ALLOWED_ORIGINS|TP_SESSION_COOKIE_SECURE)=' .env
```

- `COMPOSE_FILE` satırı sayesinde `docker compose` ve bütün `make` hedefleri GCP katmanını
  (Caddy) otomatik kullanır.

---

## 8. Başlat (VM)

```bash
cd /opt/testingprobe
make up            # ilk seferde imajlar derlenir: ~10–20 dk
make seed          # portal kullanıcıları
make status        # tüm servisler "healthy", edge dahil
make security-check   # Özet: 10/10
```

### 8.1 Sertifikanın alındığını gör

```bash
docker compose logs edge --since 10m | grep -iE 'certificate obtained|error' | tail -5
```

"certificate obtained successfully" görmelisin (genelde 1 dakika içinde).

### 8.2 Demo başlangıç durumu

```bash
make jira-seed ONAY=1   # gerçek Jira'da TPD-1..4 demo içeriği, açık koşu kayıtları kapanır
make demo-reset         # GitHub main → demo-baseline, demo-app-web GitHub'dan derlenir
```

### 8.3 Locator demosu izleyicisi (sürekli açık servis)

"Buton kimliğini değiştir" ve "Demo sıfırla" sonrasında bayi uygulamasını yeniden derleyen izleyici; VM
yeniden başlasa da kendiliğinden açılır:

```bash
sed "s/__KULLANICI__/$USER/" deploy/gcp/tp-demo-web-sync.service \
  | sudo tee /etc/systemd/system/tp-demo-web-sync.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now tp-demo-web-sync
systemctl status tp-demo-web-sync --no-pager | head -5
```

---

## 9. Tarayıcıdan doğrula

1. `https://testing-probe.antreklabs.com` → portal girişi
   (`sunucu` — Sistem Yöneticisi, rol `admin` / `.env`'deki `SEED_USER_PASSWORD`) → **Demo yol haritası**
   açılır, "0/14". Demo kontrolleri için sunucudaki `.env`'de `TP_DEMO_MODE=1` olmalı.
2. `https://bayi.testing-probe.antreklabs.com` → bayi girişi (`bayi1` / `Demo123!`).
3. Portalda **Koşular** ekranında `make demo-reset`'in kuyruğa aldığı GitHub koşusunun yeşil
   bittiğini gör.

Kısa uçtan uca prova (isteğe bağlı, uv gerekir): `make demo-prova`.

---

## 10. Günlük işletim

| İş | Komut (nerede) |
|---|---|
| Makineyi durdur (maliyet) | `gcloud compute instances stop "$VM" --zone "$ZONE"` (Mac) |
| Makineyi başlat | `gcloud compute instances start "$VM" --zone "$ZONE"` (Mac) — Docker ve container'lar (`restart: unless-stopped`) ile izleyici servisi kendiliğinden açılır; kontrol: `make status` (VM) |
| Bağlan | `gcloud compute ssh "$VM" --zone "$ZONE" --tunnel-through-iap` (Mac) |
| Kodu güncelle | `cd /opt/testingprobe && git pull && make up` (VM) |
| Loglar | `docker compose logs <servis> --since 10m` (VM) |
| Sunum öncesi | `make reset && make seed && make demo-reset` (VM) — `make reset` gerçek Jira'daki temizlik planını yazdırıp onay ister: `e` |

**Sunum günü `.env` (VM):** `TP_TEST_TEK_HESAP=0` yap, `JIRA_PO_ACCOUNT_IDS`'ten Gökhan'ın
accountId'sini çıkar, `make up`. `make status`'ta "UYARI: TP_TEST_TEK_HESAP" görünmemeli. Ayrıntı:
`docs/DEMO-AKISI.md` → "Gerçek sistemlerle sunuluyorsa".

### 10.1 Windows masaüstü testi (isteğe bağlı: `tp-windows` VM)

Windows uygulaması (WPF) için aynı `default` VPC'de ayrı, yalnız demo sırasında açılan bir Windows
Server 2022 VM'i (`tp-windows`, europe-west1-b) kullanılır; tp-demo ona iç IP ile ulaşır, internete
port açılmaz. Özet (ayrıntı ve sorun giderme: [WINDOWS-GCP.md](WINDOWS-GCP.md)):

1. Mac: `make windows-vm-olustur` (ilk kez) ya da `make windows-vm-ac`, ardından `make windows-vm-bekle`;
   iç IP: `deploy/gcp/windows-vm/vm.sh ip`.
2. VM (tp-demo) `.env`: `COMPOSE_PROFILES=mobil-windows`, `TP_WINDOWS_VM_APPIUM=<iç-IP>:4723`,
   `TP_RUNNER_APPIUM_URL_WINDOWS` / `APPIUM_URL_WINDOWS=http://appium-gw-windows:4723`,
   `APP_WINDOWS_APP` / `TP_APP_PATH_WINDOWS=C:\tp\uygulama\BayiSiparis.exe`,
   `APP_WINDOWS_ARGS` / `TP_APP_ARGS_WINDOWS=--api-url https://bayi.testing-probe.antreklabs.com/api`
   (tam blok: WINDOWS-GCP.md §4) → `make up`.
3. Demo bitince Mac: `make windows-vm-kapat` (açıkken ~0,08–0,13 $/sa; kapalıyken yalnız disk).

### 10.2 011 üretim dili güncellemesi: dağıtım sırası ve geri dönüş

`specs/011-uretim-dili` script tablosuna `dil` / `dil_kaynagi`, `script_codegen.kaynak_kod` ve SCRIPT
durumu `unverified` ekler (göç `0021_script_dil`). Toolchain ile core birlikte değişir (check adı
`local-ci-web-java`, `/check` gövdesi `{lang, platform}`); sıra önemlidir. `git pull && make up`
yerine aşağıdaki adımları izle (VM). Bu bölümdeki atıflar "§10.2 adım N" biçimindedir (N aşağıdaki
dağıtım sırasındaki numara).

**Güvenilir pom (K-T14).** 011, `demo-app/e2e-app/pom.xml` ile `toolchain/e2e-app-deps/pom.xml`'i de
değiştirir (Extent, `argLine`, `tp.java.tmpdir`; `e2e-java` için aynısı). Toolchain her Java koşusunda
(uygulama koşusu, onarım doğrulaması) commit'teki pom'u imajdaki güvenilir kopyayla bayt bayt
karşılaştırır. Yeni toolchain imajı (adım 4) forge/demo deposundaki **eski** e2e-app pom'unu görünce
koşu "pom.xml imajdaki güvenilir kopyadan farklı" hatasıyla düşer; tersi (eski imaj + yeni pom) de
öyle. Bu yüzden adım 4'ün **hemen ardından** e2e-app ve e2e-java depo/forge'da eşitlenir (adım 5).
**Adım 4 ile adım 5'in bitişi arasında Java uygulama koşusu ya da onarım TETİKLEMEYİN** (Koşular'dan
elle koşu, Jira "QA To Do" tetiği, onarım; gece koşusu saatine denk getirmeyin); bu pencerede düşen
koşuyu adım 5'ten sonra yeniden başlatın. **Açık PR'lar:** eski main'den açılmış dallar eski pom'u
taşır; adım 5'ten sonra açık uygulama/Java PR'larını (`gh pr list --state open`) GitHub'da
"Update branch" ile (ya da `git rebase origin/main`) güncelleyin; LocalForge'da açık PR dalı
güncellenemez: dağıtımdan önce merge edin ya da portaldan kapatıp adım 5'ten sonra yeniden üretin.

**Ortam değişkenleri (`.env`, GitHub kipi):**

| Değişken | Değer | Not |
|---|---|---|
| `TP_E2E_JAVA_ROOT` | `demo-app/e2e-java` | toolchain-worker + test-runner; boş = `e2e-java` (LocalForge). GitHub kipinde varsayılanda kalırsa toolchain-worker başlangıçta `UYARI:` yazar ve `/health` `java_kokleri` uyarı gösterir |
| `TP_E2E_APP_ROOT` | `demo-app/e2e-app` | toolchain-worker + test-runner (009'dan beri; değişmez); boş = `e2e-app` (LocalForge). Pom kilidi (K-T14) bu kökteki `pom.xml`'i karşılaştırır |
| `TP_REQUIRED_CHECKS` | genelde **boş** | core-api + core-worker (`x-core-env`); yazılan her check HER PR'da zorunlu. Core `web-java` (K-T10) ve `TP_PLATFORMS` check'lerini kendisi ekler; elle yazılırsa ruleset ile aynı tutun |
| `TP_WEB_DILLERI` | ilk dağıtımda **boş** (= `ts`); Java açılınca `ts,java` | core-api + core-worker; yalnız `ts\|java` geçerli |
| `TP_PLATFORMS` | değişmez (ör. boş ya da `android,windows`) | core-api de okur (011 ile compose'a eklendi) |

**Dağıtım sırası:**

```bash
cd /opt/testingprobe
# 0) Geri dönüş için çalışan imajları etiketle (yeniden derleme gerekmeden dönebilmek için)
for i in core toolchain toolchain-mcp review-portal; do
  docker tag testingprobe-$i:local testingprobe-$i:onceki-011
done
git pull
# 1) İmajları derle (çalışan servisler durmaz; toolchain derlemesi ağsız Java duman testini koşar).
#    Yalnız bu servisler: `docker compose build` demo-app-web'i de çalışma ağacından yeniden derleyip
#    kırık demo / forge main'den derlenmiş imajı ezer (OPS-L4). migrate = core imajı (core-api,
#    core-worker aynı imajı kullanır); toolchain-worker = toolchain imajı (test-runner aynı imaj).
docker compose build migrate toolchain-worker playwright-mcp review-portal
# 2) Postgres yedeği
mkdir -p ~/yedek
docker compose exec -T postgres pg_dump -U postgres -d tp -Fc > ~/yedek/tp-onceki-011-$(date +%Y%m%d%H%M).dump
# 3) Şema 0021 (eski core yeni kolonlarla çalışmaya devam eder: hepsinin sunucu varsayılanı var)
docker compose run --rm migrate
# 4) toolchain-worker ve test-runner BİRLİKTE (aynı imaj; check adı ve /check gövdesi birlikte değişir)
#    UYARI (K-T14): bundan adım 5 bitene kadar Java uygulama koşusu/onarım tetiklemeyin (pom penceresi).
docker compose up -d --no-build --no-deps --wait toolchain-worker test-runner
# 5) HEMEN ARDINDAN e2e-app + e2e-java'yı depo/forge'da eşitle (K-T14) — aşağıdaki "Adım 5" notu.
#    GitHub kipinde bu iki komut yerine önceden hazırlanmış güncelleme PR'ını şimdi merge edin.
#    LocalForge (bu VM): merge edilmiş üretilen testler (uretilen/) forge main'deki hâliyle KALIR.
#    main demo-baseline'daysa (`scripts/forge-init.sh status` → main_baseline_mi: true) B=--baseline da
#    ekleyin (make demo-reset yeni pom'u geri almasın).
make forge-sync-dizin D=e2e-app K=uretilen
make forge-sync-dizin D=e2e-java K=uretilen
# 6) core-api + core-worker + portal
docker compose up -d --no-build --no-deps --wait core-api core-worker review-portal playwright-mcp
# 7) Backfill (OPS-O2): göç penceresinde ESKİ core'un yazdığı uygulama script'leri sunucu varsayılanı
#    'ts' ile girmiş olabilir. İdempotenttir; her geri dönüş/yeniden yükseltmeden sonra da koşun.
docker compose exec -T postgres psql -U postgres -d tp -v ON_ERROR_STOP=1 \
  -c "UPDATE script SET dil='java' WHERE platform<>'web' AND dil='ts';"
# 8) Doğrula
make status && make security-check
```

**Adım 5 — e2e-app + e2e-java eşitleme (K-T14, zorunlu; adım 4'ün hemen ardından):**

   - **LocalForge:** yukarıdaki iki `make forge-sync-dizin … K=uretilen` komutu (main'e dizin başına tek
     commit, PR kaydı korunur, `uretilen/` altındaki merge edilmiş üretilen testler forge main'deki
     hâliyle kalır; ürün deposunun `uretilen/` örnekleri forge'a girmez). e2e-java forge'da yoksa
     ikinci komut onu ekler. `K=uretilen` olmadan çalıştırmayın: merge edilmiş Java testleri silinir.
     Volume yoksa betik oluşturmadan durur (`COMPOSE_PROJECT_NAME` yanlışsa boş volume bırakmaz).
     `B=--baseline` olmadan yapılan eşitlemeyi `make demo-reset` (main → demo-baseline) geri alır ve
     eski pom döner: sıfırlamadan sonra iki komutu `B=--baseline` ile yeniden koşun (`make reset` forge'u
     çalışma ağacından yeniden kurduğu için gerekmez).
   - **GitHub kipi:** `scripts/github-demo-repo-init.sh --push --update` (Mac; yeni ağaç e2e-app pom'unu
     ve `demo-app/e2e-java/`, `.github/workflows/web-java.yml`, `toolchain/java-araclar/`,
     `toolchain/e2e-java-deps/`'u taşır; merge edilmiş üretilen testler — `demo-app/e2e/tests/generated/`,
     `demo-app/{e2e-java,e2e-app}/src/test/java/**/uretilen/` — uzak main'deki hâliyle kalır) → PR'ı
     açın. Pencereyi kısaltmak için PR'ı adım 0'dan ÖNCE açıp CI'ını yeşillendirin, ama merge'ü adım 4'ün
     **hemen ardından** yapın (önce merge edilirse eski toolchain yeni pom'u reddeder; pencere bu PR'ın
     merge'üne kadar açıktır). PR farkını gözden geçirin: üretilen test dosyası silinmemeli.
     Ardından açık PR'ları "Update branch" ile güncelleyin (yukarıdaki "Açık PR'lar").

Sonraki adımlar (8'den sonra):

9. **(İsteğe bağlı) LocalForge'da e2e-java'yı kalıcılaştır.** Adım 5'teki eşitleme `B=--baseline`'sız
   yapıldıysa ve main sonradan demo-baseline'a döndüyse: `make forge-sync-dizin D=e2e-java B=--baseline
   K=uretilen` (demo-baseline etiketini ve demo/break-locator'ı da taşır; main demo-baseline'da değilse
   önce `make demo-baseline`). Aynısı `D=e2e-app` için.
10. **Java'yı GitHub'da aç (en son):** adım 5'teki PR main'e girmeden ve ruleset'e `web-java`
   eklenmeden `TP_WEB_DILLERI=ts,java` YAZMA: aksi halde Java kardeş koşusu gelmeyen check'i bekler.
   K-T10: `web-java.yml` demo deposunda olduğu sürece `web-java` **her zaman** zorunludur (ilgisiz
   PR'da iş akışı `changes` + no-op ile hızla yeşil olur); `TP_WEB_DILLERI` yalnız Java üretimini ve
   kardeş koşuyu açar. Ruleset'e ekleme mevcut check'leri KORUYARAK yapılır — `--checks` listeyi
   tümüyle değiştirir (PUT) ve orada yazılmayan platform check'lerini (`mobil-android`,
   `masaustu-windows`) siler:
   ```bash
   # Önerilen: mevcut listeyi okuyup birleştirir (önce kuru çalışma, sonra --apply)
   scripts/github-ruleset.sh --add-checks web-java
   scripts/github-ruleset.sh --add-checks web-java --apply
   # Ya da tam liste (TP_PLATFORMS'taki platformları da yazın; ör. android,windows):
   scripts/github-ruleset.sh --checks test-local,ast-guard,semgrep,mobil-android,masaustu-windows,web-java --apply
   ```
   Ruleset'e `web-java` eklendiğinde **açık PR'lar** bu check'i beklemeye başlar ama iş akışı ancak
   PR'a yeni bir olay (push, yeniden açma) geldiğinde koşar (OPS-L6): açık PR'ları listeleyip
   (`gh pr list --state open`) her birine boş commit/rebase gönderin ya da Actions'tan `web-java`'yı
   yeniden tetikleyin; aksi halde merge "Expected — Waiting for status" ile bekler. Sonra
   `.env`'ye `TP_WEB_DILLERI=ts,java` → `docker compose up -d --no-build --no-deps core-api core-worker`.
   `TP_REQUIRED_CHECKS` boşsa dokunmayın (core `web-java`'yı K-T10/K-T13'e, platformları
   `TP_PLATFORMS`'a göre kendisi ekler); elle yazılıyorsa ruleset'le aynı tutun (`web-java` dahil).
   `--add-checks` mevcut ruleset'te zorunlu check yoksa ya da liste boşsa `--checks` (varsayılan
   `test-local,ast-guard,semgrep`) ile birleştirir; `--apply` her zaman canlı ruleset'i okur
   (`--existing-json` yalnız kuru çalışma içindir, `--apply`'da yok sayılır ve farklıysa uyarır).
   **K-T13:** core'un merge kapısı zorunlu listeyi PR'ın **base ∪ head** ağacından hesaplar:
   `web-java.yml` ikisinden birinde varsa `web-java` zorunludur; ağaç okunamazsa ya da kesik
   (`truncated`) gelirse kapalı tarafa düşer (`web-java` zorunlu sayılır).
   **Kapasite (K-T11):** script'siz PR'da test kökleri (`e2e/`, `e2e-java/`, `e2e-app/`) dışında
   değişiklik (uygulama kodu vb.) varsa repodaki tüm tam hat dilleri koşar: LocalForge'da böyle bir
   uygulama PR'ı yerel CI'ı yaklaşık **iki kat** sürer/yükler (TS + Java tarayıcı koşusu; toolchain
   yuvası iki kez dolar). GitHub'da `web-java.yml`'nin yol süzgeci daha dardır (`demo-app/e2e-java/**`,
   `demo-app/api/**`, `demo-app/web/**`, Java araçları…): ör. yalnız `demo-app/mobile/**` ya da
   `demo-app/desktop/**` değiştiren PR'da GitHub Java'yı koşmaz (`web-java` no-op yeşil), LocalForge
   ise K-T11 gereği koşar.
11. **`web-java.yml`'yi depodan kaldırma (OPS-D4, K-T13 — yalnız gerekirse; önerilen: bırakın).**
   K-T13 gereği iş akışını silen PR'ın **base**'inde `web-java.yml` olduğundan `web-java` o PR için
   zorunludur, ama head'de iş akışı olmadığından GitHub check'i hiç göndermez — PR "Expected — Waiting
   for status" ile kilitlenir. Sıra: (1) `.env`'de `TP_WEB_DILLERI`'den `java`'yı çıkarın, core'u
   yeniden oluşturun; (2) ruleset'ten `web-java`'yı çıkarın — `--add-checks` çıkaramaz, tam liste
   `--checks` ile (önce kuru): `scripts/github-ruleset.sh --checks test-local,ast-guard,semgrep[,platform check'leri] --apply`;
   (3) silen PR'ı GitHub arayüzünden insan olarak merge edin (core'un kapısı bu PR'da hâlâ `web-java`
   ister; core üzerinden merge denemeyin); (4) main'de `web-java.yml` kalmayınca core artık `web-java`
   istemez. `TP_REQUIRED_CHECKS` elle yazılmışsa oradan da çıkarın.
12. **Başka dilde merge edilmiş testi kaldırma (K-T12, elle):** Bir case için TS testi merge edilmişken
   Java üretmek 409 döner ("mevcut test dosyasını silen bir PR'ı merge edin, sonra yeniden üretin").
   Ürün bunu otomatik yapmaz (backlog). Elle: demo deposunda `demo-app/e2e/tests/generated/<case>.spec.ts`
   (ya da `demo-app/e2e-java/.../uretilen/<Case>Test.java`) dosyasını silen bir PR açın, insan olarak
   merge edin (CODEOWNERS onayı gerekir), sonra portaldan Kod üretimi'nde case'i diğer dille yeniden
   üretin. LocalForge'da (demo/prova) elle PR açma yolu yoktur: forge `main`'ine doğrudan yazmayın;
   `make reset` forge'u demo-baseline'a döndürür (merge edilmiş TÜM üretilen testler gider).
   `make forge-sync-dizin D=e2e` yalnız `K=tests/generated` ile kullanılabilir (merge edilmiş TS
   testleri korunur); `K`'sız forge'da merge edilmiş diğer üretilen testleri de siler.

**Geri dönüş (önerilen: şema kalır):**

Önce: açık **web + Java PR'larını** (kod üretimi/onarım; `ortam.dil = java`) kapatın ya da merge edin —
eski core bu PR'ları TS sanır, Java kardeş koşusu ve `local-ci-web-java`/`web-java` kapısını bilmez.
Ruleset'te `web-java` kalırsa ve `web-java.yml` depoda kalırsa check gelmeye devam eder (sorun değil);
iş akışını depodan kaldırırsanız önce ruleset'ten çıkarın (§10.2 adım 11 sırası; aksi halde PR'lar
bekler). **Pom'lar da eskiye döner (K-T14):** eski toolchain imajının güvenilir pom'u eskidir; depo/forge
e2e-app pom'u yeni kalırsa geri dönüşten sonra her Java uygulama koşusu "pom.xml imajdaki güvenilir
kopyadan farklı" ile düşer. Bu yüzden b) ile c) arasında e2e-app eşitlenir (aşağıda b2; kuyruk boş ve
tetikler durmuş olduğundan pencere sorun olmaz). e2e-java için gerekmez (eski toolchain web + Java
koşturmaz; dosyalar depoda kalabilir).

```bash
cd /opt/testingprobe
# a) Yeni imajları sakla: şema downgrade'i (alembic downgrade 0020) YENİ core imajıyla yapılır.
for i in core toolchain toolchain-mcp review-portal; do
  docker tag testingprobe-$i:local testingprobe-$i:yeni-011
done
# b) Kuyruğu boşalt: tetikleri durdur (TP_WEB_DILLERI'yi .env'den kaldır, Jira/forge tetiklerini
#    beklet), koşan/kuyruktaki işler bitene kadar bekle — iki sorgu da BOŞ/sıfır olmalı
#    (job = Postgres iş kuyruğu: kod üretimi, onarım, CI, triage...; run = koşu kayıtları):
docker compose exec -T postgres psql -U postgres -d tp -tAc \
  "SELECT tur, count(*) FROM job WHERE durum IN ('queued','retry','running') GROUP BY tur;"
docker compose exec -T postgres psql -U postgres -d tp -tAc \
  "SELECT count(*) FROM run WHERE sonuc IN ('queued','running');"
# b2) e2e-app pom'unu eskiye döndür (K-T14; YENİ betiklerle, c'den ÖNCE — eski kodda sync-dizin yok).
#     LocalForge: eski commit'in e2e-app'i geçici dizinden, merge edilmiş testler korunarak:
ESKI=$(mktemp -d) && git archive <önceki commit> demo-app/e2e-app | tar -x -C "$ESKI"
TP_FORGE_SRC="$ESKI/demo-app" scripts/forge-init.sh sync-dizin e2e-app --koru uretilen
#     GitHub kipi: demo deposunda yalnız demo-app/e2e-app/pom.xml'i eski hâline getiren bir PR açıp
#     (içerik: git show <önceki commit>:demo-app/e2e-app/pom.xml) insan olarak merge edin.
#     github-demo-repo-init.sh --update'i eski commit'ten KOŞMAYIN: eski sürüm üretilen testleri korumaz.
# c) Çalışma ağacını ÖNCE eski commit'e al (compose dosyası ve betikler imajlarla aynı sürüm olsun)
git checkout <önceki commit>
# d) Eski imajları geri etiketle ve yalnız servisleri yeniden oluştur.
for i in core toolchain toolchain-mcp review-portal; do
  docker tag testingprobe-$i:onceki-011 testingprobe-$i:local
done
# migrate ÇALIŞTIRILMAZ (eski kodda 0021 yok; `make up` migrate'i düşürür) — yalnız servisler:
docker compose up -d --no-build --no-deps --force-recreate \
  toolchain-worker test-runner core-api core-worker review-portal playwright-mcp
```

Şema 0021'de kalır: eski core yeni kolonları bilmez, sunucu varsayılanlarıyla yazar. Yeniden
yükseltmede §10.2 adım 7'deki backfill'i tekrar koş ve adım 5'i (pom eşitleme) yinele. `make up` / `git pull` ile ileri dönmeden önce
çalışma ağacının yeni koda geçtiğinden emin ol.

**Şema geri alma (downgrade) — yalnız zorunluysa, yedekten dönmek daha güvenlidir:**
`alembic downgrade 0020` yeni core imajıyla yapılır (eski imaj 0021'i bilmez); geri dönüşün a)
adımında saklanan `:yeni-011` geçici olarak geri etiketlenir:
`docker tag testingprobe-core:yeni-011 testingprobe-core:local && docker compose run --rm migrate alembic downgrade 0020 && docker tag testingprobe-core:onceki-011 testingprobe-core:local`
(ardından core servislerini yukarıdaki d) adımıyla yeniden oluştur). Geri alınamaz veri kaybı yapar:
- `unverified` script'ler `closed` olur ve geri dönmez; `script_codegen.kaynak_kod` (C#/Python kaynağı)
  **silinir** — gerekiyorsa önce portaldan indir.
- `script.dil` / `dil_kaynagi` silinir: eski core web + Java script'lerini TypeScript sanır. Downgrade'den
  ÖNCE açık web + Java PR'larını kapat (portal ya da forge), merge edilmiş Java web testleri repoda
  (`e2e-java/`) kalır ama eski core onları koşturmaz; Koşular'daki `ortam.dil = java` kayıtları eski
  portalda TS gibi görünür.
- Downgrade sonrası `TP_WEB_DILLERI` ve ruleset'teki `web-java` kaldırılmalı.

---

## 11. Maliyet (yaklaşık)

Fiyatlar bölgeye ve zamana göre değişir; güncel değeri Console → Billing'den doğrula.

| Kalem | Sürekli açık | Yalnız sunum/prova günleri açık |
|---|---|---|
| e2-standard-4 (europe-west3) | ~110 USD/ay | saat başı ~0,15 USD |
| 100 GB pd-balanced disk | ~12 USD/ay | ~12 USD/ay (makine durunca da) |
| Sabit IP | ~4 USD/ay | ~7 USD/ay (makine dururken daha pahalı) |

Kullanılmadığında makineyi durdurmak aylık maliyeti ~20 USD'nin altına indirir. Console → Billing →
Budgets'tan bir bütçe uyarısı (ör. 50 USD) kurman önerilir.

---

## 12. Sorun giderme

| Belirti | Neden / çözüm |
|---|---|
| Tarayıcı "sertifika geçersiz", `edge` logunda `challenge failed` / `NXDOMAIN` | DNS kaydı henüz yayılmadı ya da yanlış IP'yi gösteriyor (§3.3 `dig` ile kontrol), veya 80 portu kapalı (`tp-demo-web` kuralı). Düzelince `docker compose restart edge`. |
| Logda `rateLimited` | Çok sayıda başarısız deneme; Let's Encrypt bir saat bekletir. DNS'i düzeltip bekle, sonra `docker compose restart edge`. |
| Portal girişi olmuyor (yeniden giriş sayfasına dönüyor) | `TP_SESSION_COOKIE_SECURE=true` ve adresin `https://` ile açıldığından emin ol. |
| Kaydet/onay işlemlerinde 403 | `TP_ALLOWED_ORIGINS` portalın tam adresi olmalı (`https://testing-probe.antreklabs.com`, sonda `/` yok); değiştirince `make up`. |
| Portaldaki canlı güncellemeler gelmiyor | SSE akışı; Caddyfile'da `flush_interval -1` olmalı. `docker compose logs edge`. |
| `make up` bellek/disk hatası | `make up` önce önkoşulları denetler; makine tipi en az e2-standard-4, disk en az 100 GB olmalı. |
| Locator kırıldı ama bayi uygulaması değişmedi | `systemctl status tp-demo-web-sync`; `journalctl -u tp-demo-web-sync -n 50`. |

### Alan adı olmadan (yedek: sslip.io)

DNS'e erişim yoksa `testing-probe.antreklabs.com` yerine `portal.<IP>.sslip.io`,
`bayi.testing-probe.antreklabs.com` yerine `bayi.<IP>.sslip.io` kullanılabilir (sslip.io IP'yi adrese
çevirir, DNS kaydı gerekmez): §7'de `PORTAL` ve `BAYI` değişkenlerini bu adlarla verip `make up`.

### Erişimi IP ile daraltmak (isteğe bağlı)

443'ü yalnızca ofis/sunum ağına açmak istersen (80 Let's Encrypt için herkese açık kalmalı):

```bash
gcloud compute firewall-rules update tp-demo-web --rules tcp:80
gcloud compute firewall-rules create tp-demo-https-ofis \
  --network default --direction INGRESS --action ALLOW \
  --rules tcp:443 --source-ranges <ofis-ip>/32 --target-tags tp-demo-web
```

---

## 13. Tamamen kaldırma (Mac)

```bash
gcloud compute instances delete "$VM" --zone "$ZONE"
gcloud compute addresses delete tp-demo-ip --region "$REGION"
gcloud compute firewall-rules delete tp-demo-web tp-demo-ssh-iap
```

---

## 14. Bu kurulumda henüz doğrulanmamış olanlar

Kod ve yapılandırma yerelde doğrulandı: compose katmanı geçerli, Caddyfile `caddy validate`'ten
geçiyor, `make security-check` 10/10 ve port denetimi yalnızca `edge` 80/443'e izin veriyor. Ama şu
üçü ancak ilk GCP kurulumunda görülecek:

- `testing-probe.antreklabs.com` ve `bayi.testing-probe.antreklabs.com` için Let's Encrypt sertifikasının alınması (§8.1).
- Portalın canlı güncelleme akışının (SSE) Caddy üzerinden kesintisiz geçmesi.
- IDE'nin MCP kanalının `https://testing-probe.antreklabs.com/api/mcp` üzerinden çalışması (demo akışı bunu
  kullanmaz; yalnızca IDE entegrasyonu için).
