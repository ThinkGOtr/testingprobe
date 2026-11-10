# tp-windows — Windows masaüstü testi için GCP VM (operatör kılavuzu)

Sözleşme: [`specs/009-mobil-masaustu/windows-gcp.md`](../../../specs/009-mobil-masaustu/windows-gcp.md).
WPF uygulaması (`demo-app/desktop`) bu VM'de Appium + NovaWindows sürücüsüyle sürülür; tp-demo
VM'indeki runner/app-mcp iç ağ üzerinden `<iç IP>:4723`'e bağlanır. VM **yalnızca demo/test sırasında**
açık tutulur.

Komutlar Mac'te, `gcloud` oturumu açık ve `testingprobe` projesine yetkili bir hesapla koşar.

## Ne oluşturulur

| Alan | Değer | Ortam değişkeni |
|---|---|---|
| Proje | `testingprobe` | `TP_GCP_PROJECT` |
| Ad | `tp-windows` | `TP_WINDOWS_VM_NAME` |
| Bölge | `europe-west1-b` | `TP_WINDOWS_VM_ZONE` |
| Makine | `e2-medium` (yetmezse `e2-standard-2`) | `TP_WINDOWS_VM_MACHINE` |
| İmaj | `windows-cloud/windows-2022` (Desktop Experience) | — |
| Disk | 50 GB `pd-standard` (VM silinince silinir) | — |
| Ekran | `--enable-display-device` | — |
| Ağ | `default`, geçici dış IP, **ağ etiketi yok** | — |
| Shielded VM | secure boot + vTPM + integrity monitoring | — |

Metadata: `tp-repo` (`TP_WINDOWS_VM_REPO`, varsayılan `ThinkGOtr/testingprobe`), `tp-repo-ref`
(`TP_WINDOWS_VM_REF`, `dev`), `tp-izinli-kaynak` (`TP_WINDOWS_VM_IZINLI`; boşsa tp-demo'nun iç IP'si
`gcloud … describe tp-demo --zone europe-west3-a` ile okunur, okunamazsa `10.156.0.2`), `tp-api-url`
(`TP_WINDOWS_VM_API_URL`) ve `windows-startup-script-ps1` ← [`kurulum.ps1`](kurulum.ps1) (her açılışta
koşar, idempotent).

## Maliyet (yaklaşık, liste fiyatı)

- e2-medium europe-west1 ~0,04 $/sa + Windows lisansı → **açıkken ~0,08–0,13 $/sa**.
- 50 GB pd-standard ~2–3 $/ay — **VM kapalıyken de** ödenir; tamamen sıfırlamak için `make windows-vm-sil`.
- Yalnızca demo sırasında açılırsa ayda birkaç dolar.

## Yaşam döngüsü

```bash
make windows-vm-olustur DRY_RUN=1   # önce komutu gör (hiçbir şey oluşturulmaz)
make windows-vm-olustur             # VM adını yazarak onayla (ya da EVET=1)
make windows-vm-bekle               # ilk kurulum ~20–40 dk; HAZIR satırını bekler (TP_WINDOWS_VM_BEKLE_DK=45)
make windows-vm-ip                  # → tp-demo .env: TP_WINDOWS_VM_APPIUM=<ip>:4723

make windows-vm-kapat               # demo bitince
make windows-vm-ac && make windows-vm-bekle   # sonraki demo
make windows-vm-durum               # durum + iç IP + son TP-WINDOWS-HAZIR/HATA satırı
make windows-vm-sil                 # VM + disk (onay ister; EVET=1)
```

`DRY_RUN=1` yazan her komutta (`olustur`, `ac`, `kapat`, `sil`) gcloud komutunu yalnızca yazdırır.
`olustur` ve `sil` etkileşimsiz kipte `EVET=1` olmadan reddeder. Öz test (GCP'ye dokunmaz):
`make windows-vm-selftest`.

İç IP VM durdurulup başlatılınca genellikle korunur, ama silinip yeniden oluşturulursa değişir —
o zaman tp-demo `.env`'indeki `TP_WINDOWS_VM_APPIUM` güncellenir. tp-demo tarafı ayarları için
sözleşmedeki "tp-demo tarafı" bölümüne bakın.

## Güvenlik

- İnternetten **gelen erişim yok**: VM'e ağ etiketi verilmez, betik GCP güvenlik duvarı kuralı
  **oluşturmaz**. Geçerli kurallar yalnızca `default-allow-internal` (10.128.0.0/9) ve
  `default-allow-icmp`. RDP (3389) ve Appium (4723) internete açılmaz. Dış IP yalnızca dışarı
  bağlantı (indirme/depo zip'i) içindir.
- Appium 4723'e Windows güvenlik duvarında **yalnızca** `tp-izinli-kaynak` (tp-demo iç IP) izinlidir;
  betik bu değeri tek bir IPv4 adresi olarak doğrular (CIDR / `0.0.0.0` kabul edilmez).
- `tpotomasyon` kullanıcısının parolası VM içinde rastgele üretilir, dışarı çıkmaz; seri porta sır
  yazılmaz ve `vm.sh` seri çıktıdan yalnızca durum satırını gösterir.

## Sorun giderme

- **Ekran görüntüsü:** `make windows-vm-ekran` → `var/windows-vm/ekran-<zaman>.png` (oturum açık mı,
  uygulama/hata penceresi var mı).
- **Seri port:** `make windows-vm-durum` son `TP-WINDOWS-HAZIR` / `TP-WINDOWS-HATA <adım> <mesaj>`
  satırını gösterir. Tam çıktı (yalnızca hata ayıklarken):
  `gcloud compute instances get-serial-port-output tp-windows --zone europe-west1-b --port 1 --project testingprobe`.
- `bekle` en son durum satırına bakar; çok yeni açılmış bir VM'de önceki açılıştan kalma satır
  görülürse satırdaki `ref=` değerini ve zamanı kontrol edin, birkaç dakika sonra yeniden `durum` alın.
- `HATA` sonrası: sorunu giderip `make windows-vm-kapat && make windows-vm-ac` — `kurulum.ps1` her
  açılışta yeniden koşar ve tamamlanmış adımları atlar.
- Makine yetmiyorsa (yavaş UI Automation): `make windows-vm-kapat`, ardından
  `gcloud compute instances set-machine-type tp-windows --zone europe-west1-b --machine-type e2-standard-2 --project testingprobe`, sonra `make windows-vm-ac`.
