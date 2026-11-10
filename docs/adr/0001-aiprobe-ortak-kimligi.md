# ADR-0001 — AI Probe ortak kimliği

- **Durum:** Kabul edildi — **onaylandı (2026-11-10), onaycı isimleri F0 notuna işlenecek**
  (teknik lider + ürün sahibi; KVKK sorumlusu). Constitution İlke XII'yi yeniden tanımlar
  (MAJOR, v2.0.0).
- **Tarih:** 2026-11-10
- **Kaynak:** `aiprobe-platform-plan/PLAN.md` §2.3, §4.2 (F4a/F4b), §5 (yolculuk 6, 11, 13, 14);
  bağlayıcı arayüz `aiprobe-platform/docs/CONTRACT.md` v1 ("Ürün sunucusu uçları", "Ürün tarafı").
- **Uygulama:** `specs/010-aiprobe-sso/`

## Bağlam

Constitution v1.3.0 İlke XII: "Testing Probe, Agent Probe'dan bağımsız ayrı bir üründür; ortak kod,
ekran, veritabanı veya **kimlik** paylaşmaz (ortak çekirdek kararı ürün sahibinin ADR'sine
bırakılmıştır)."

AI Probe platformu (Antrek Labs) tek bir giriş (`id.aiprobe.antreklabs.com`, Identity Platform)
ve bir ürün değiştirici sunar. Kullanıcı bir kez giriş yapar ve Agent Probe ile Testing Probe
arasında parola sormadan geçer; çıkış ve hesabın devre dışı bırakılması iki üründe de ≤60 sn
içinde etkili olur. Bugün TP'nin kendi kullanıcı adı/parola girişi (argon2, `tp_session`) vardır;
müşteri ortamında (on-prem, İlke VII) dış bir kimlik servisine bağımlılık kabul edilemez.

## Karar

1. **İlke XII yeniden tanımlanır.** TP, Agent Probe ile **kod, ekran ve veritabanı paylaşmaz**
   (değişmedi). TP, ortak AI Probe kimliğine **yalnızca belgelenmiş HTTP kimlik API'si** üzerinden
   bağlanabilir:
   - **Giriş devri:** tarayıcı `id.` sayfasına yönlendirilir; dönüşte tek kullanımlık kod,
     sunucudan sunucuya `POST {AIPROBE_HOME_RUN_URL}/v1/handoff/redeem` ile takas edilir.
   - **Oturum kontrolü:** her TP oturumu (ve `tpt_` token'ı) en geç 60 sn'de bir
     `POST /v1/session/check` ile doğrulanır.
   - TP → `aiprobe-home` çağrıları TP'nin servis hesabının Google imzalı ID token'ıyla;
     `aiprobe-home` → TP admin çağrısı (`/admin/kimlik-bagi`) `aiprobe-home` servis hesabının
     Google ID token'ıyla doğrulanır (`email` = `AIPROBE_HOME_SA`).
2. **Firebase SDK'sı (istemci veya Admin) TP'ye girmez.** TP Firebase token'ı görmez, doğrulamaz,
   saklamaz; kimlik yalnızca devir yanıtındaki alanlardır (`uid`, `email`, `name`, `roles`,
   `org`, `auth_time`, `acr`). AP'nin kodu, ekranı ya da veritabanı import edilmez; platformun
   Python istemcisi kopyalanmaz — iki HTTP çağrısı TP kodunda, TP sahipliğinde yazılır.
3. **TP'nin yetki modeli değişmez.** Ortak kimlikteki kişi, TP'deki tek-rollü `app_user` rol
   hesaplarına `kimlik_bagi(external_uid, app_user_id UNIQUE)` ile bağlanır; yetki kararları yine
   `app_user.rol` ile verilir. Bir kişi birden çok rol hesabına bağlanabilir (rol seçici,
   "Rol değiştir").
4. **İlke VII korunur.** `TP_AUTH_MODE=local|aiprobe|both`; **varsayılan `local`** ve on-prem
   kurulumlar `local` çalışır: dış kimlik servisine hiçbir çağrı yapılmaz, davranış bugünküyle
   aynıdır (`tp_session` çerezi, argon2). `aiprobe` modu yalnızca Antrek'in barındırdığı SaaS/demo
   ortamında açılır; `both` geçiş ve acil erişim içindir. `both` kipinde yerel parola yalnız
   **bağsız** hesaplar içindir: bir AI Probe kişisine bağlanmış (`kimlik_bagi`) hesap yerel
   parolayla açılmaz (403 `aiprobe_gerekli`); `aiprobe` kipinde yerel oturum ve bağsız/yerel
   oturumdan üretilmiş `tpt_` token'ı kabul edilmez.
5. **Müşteri verisi kimlik servisine gitmez.** `aiprobe-home`'a giden veri yalnız oturum kimliğidir:
   `uid`, `auth_time`, `acr`, `session_epoch_ms` (CONTRACT v1.2 `/v1/session/check`; takasta
   yalnız tek kullanımlık kod). TP'nin alan verisi (story, case, kanıt) platforma hiç çıkmaz. Ters
   yönde bağlama API'si (`/admin/kimlik-bagi`) rol hesaplarının `kullanici_adi`, `ad_soyad` ve
   `rol`'ünü yalnız `aiprobe-home` servis kimliğine — dolayısıyla home/admin'deki yöneticilere —
   açar.

## Sonuçlar

- (+) Tek giriş, merkezi çıkış ve iptal; demo hesapları `home/admin`'den yönetilir.
- (+) On-prem dağıtım ve mevcut yerel giriş testleri değişmez.
- (−) `aiprobe` modunda `aiprobe-home` kesintisinde (ağ hatası, 5xx, 408, 429) yeni giriş
  yapılamaz; açık oturumlar ve `tpt_` token'ları ilk erişilemeyen kontrolden itibaren **en çok
  10 dk** (`degraded_baslangic`, ayrı işlemde kalıcı yazılır) korunur ve `X-Aiprobe-Degraded: 1`
  döner; sınır aşılınca oturum kapatılır / token home yeniden doğrulayana dek reddedilir. Diğer
  4xx yanıtları (400, 401 `invalid_caller`, 403, 404 …) fail-closed'dur: oturum geçersiz sayılır
  ve kişinin hesapları iptal edilir (kabul edilen sınır; PLAN §2.3).
- (−) İptal etkisi en çok 60 sn gecikir (önbellek); kabul edildi.
- KVKK: kişisel veri olarak yalnızca e-posta, ad ve platform `uid`'si işlenir; `app_user.ad_soyad`
  ve `kimlik_bagi.external_uid` TP veritabanında tutulur. Aktarım SaaS ortamı içindir; on-prem'de
  yoktur.

## Reddedilen seçenekler

- **Firebase Admin SDK ile ID token'ı TP'de doğrulamak:** TP'yi Firebase'e ve Google'a bağlar,
  on-prem'de anlamsız; iptal kontrolü yine merkezi çağrı ister.
- **AP ile ortak kullanıcı tablosu:** İlke XII'nin özü (ayrı veri) bozulur.
- **Platform istemci paketini (`aiprobe-auth-py`) vendor etmek:** küçük iki çağrı için yabancı kod
  sahipliği; TP'nin oturum/yetki modeline uymayan varsayımlar taşır.
