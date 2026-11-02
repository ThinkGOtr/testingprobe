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
| `https://testing-probe.antreklabs.com` | Review portal (analist, PO, mühendis, testçi, sunucu) |
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

"Locator'ı kır" ve "Demo sıfırla" sonrasında bayi uygulamasını yeniden derleyen izleyici; VM
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
   (`sunucu` / `.env`'deki `SEED_USER_PASSWORD`) → **Demo yol haritası** açılır, "0/14".
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
