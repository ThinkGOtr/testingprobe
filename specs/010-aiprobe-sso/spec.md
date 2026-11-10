# Feature Specification: AI Probe Ortak Girişi (SSO)

**Feature Branch**: `feat/010-aiprobe-sso` (hedef `dev`; spec klasörü `010-aiprobe-sso`)

**Created**: 2026-11-10

**Status**: Onaylı (ADR-0001 ve constitution v2.0.0 onaylandı, 2026-11-10; onaycı isimleri F0
notuna işlenecek)

**Input**: "Testing Probe, AI Probe ortak girişine katılır (aiprobe-platform-plan/PLAN.md §2.3,
§4.2 F4b, §5 yolculuk 6, 11, 13, 14). Bağlayıcı arayüz aiprobe-platform/docs/CONTRACT.md v1."

Bu spec **ne/neden**dir; teknik ayrıntı [plan.md](./plan.md), kaynak tasarım
[TEKNIK-TASARIM §8.14](../../docs/TEKNIK-TASARIM.md), karar [ADR-0001](../../docs/adr/0001-aiprobe-ortak-kimligi.md).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - AI Probe hesabıyla giriş (Priority: P1)

Antrek'in barındırdığı ortamda (`TP_AUTH_MODE=aiprobe`) bir kullanıcı Testing Probe'a gelir; oturumu
yoksa AI Probe giriş sayfasına yönlendirilir, giriş yaptıktan (ya da zaten açık bir AI Probe
oturumuyla parola sorulmadan) sonra geldiği sayfaya döner. TP'de hesabı hiç yoksa ama AI Probe'da
TP rolü varsa, o rol adına TP hesabı otomatik açılır (JIT).

**Why this priority**: Diğer bütün hikâyelerin önkoşulu; değiştiriciyle ürünler arası geçiş bunun
üzerine kuruludur (yolculuk 5).

**Independent Test**: Sahte `aiprobe-home` ile `/auth/aiprobe/login` → `/auth/aiprobe/callback` →
`/auth/me` turu; bağsız kullanıcıda JIT hesabı ve bağ oluşur.

**Acceptance Scenarios**:

1. **Given** oturumu olmayan kullanıcı, **When** `/auth/aiprobe/login?continue=/x` açılır, **Then**
   `state` çerezi yazılır ve `id.` giriş sayfasına `product=testing-probe&state=…&continue=/x` ile
   yönlenir.
2. **Given** geçerli kod ve eşleşen `state`, **When** callback gelir, **Then** kod sunucudan
   sunucuya takas edilir, `__Host-tp_session` açılır, kullanıcı `/x`'e döner.
3. **Given** değiştirilmiş `state`, **When** callback gelir, **Then** 400 `durum_uyusmuyor`,
   oturum açılmaz, takas çağrısı yapılmaz.
4. **Given** bağı olmayan, rolü `tester` olan kişi, **When** ilk kez girer, **Then** `tester`
   rollü yeni `app_user` (`ad_soyad` = AI Probe adı) ve `kimlik_bagi` oluşur; parola ile yerel
   giriş yapamaz.

---

### User Story 2 - Çok rollü kullanıcı ve "Rol değiştir" (Priority: P1) — yolculuk 6

Sunum yapan kişi birden çok TP rol hesabına (ör. `analist`, `po`) bağlıdır. Girişte rol seçici
görür; sunum sırasında "Rol değiştir" ile parola girmeden PO'ya geçer.

**Why this priority**: Demo akışı (14 adım) rol değiştirmeden yürümez.

**Independent Test**: İki bağlı hesap + `roles=[analyst, po]` → callback rol seçiciye yönlenir;
`rol-sec` oturum açar; `rol-degistir` yeni `sid` ile diğer hesaba geçer.

**Acceptance Scenarios**:

1. **Given** iki eşleşen bağlı hesap, **When** callback, **Then** 302 `/rol-sec`, oturum yok,
   `GET /auth/aiprobe/hesaplar` iki hesabı listeler.
2. **Given** AI Probe oturumu (`analyst`), **When** `POST /auth/aiprobe/rol-degistir` (po
   hesabı), **Then** eski oturum iptal, yeni oturum kimliği, `/auth/me` rolü `po`.
3. **Given** kişiye bağlı olmayan hesap kimliği, **When** rol-degistir, **Then** 403, oturum
   değişmez.

---

### User Story 3 - İptal ve devre dışı bırakma ≤60 sn (Priority: P1) — yolculuk 13

Admin kullanıcıyı devre dışı bırakır ya da kullanıcı "Çıkış" ile tüm ürünlerden çıkar. 60 saniye
içinde TP istekleri 401 döner, SSE akışı kapanır, kullanıcının `tpt_` token'ları reddedilir.

**Independent Test**: `session/check` `valid=false` döndürünce bir sonraki istek (kontrol aralığı
dolduğunda) 401, aynı kullanıcının `tpt_` token'ı 401.

**Acceptance Scenarios**:

1. **Given** son kontrolden ≥60 sn geçmiş oturum, **When** home `valid=false`, **Then** 401,
   `app_user.auth_epoch` artmış, `external_uid` oturumları iptal.
2. **Given** aynı kişinin `tpt_` token'ı, **When** MCP çağrısı, **Then** 401.
3. **Given** home erişilemez (ağ/5xx), **When** istek gelir, **Then** oturum korunur, yanıt
   `X-Aiprobe-Degraded: 1` taşır.

---

### User Story 4 - Oturum süreleri (Priority: P2) — yolculuk 14

Boşta 30 dk kayan, mutlak 8 sa. 25 dk aralıklı çalışan kullanıcı düşmez; 30 dk hiç istek yapmayan
kullanıcının sonraki isteği 401 alır (portal form verisini korur, yeniden giriş ister). SSE'nin
arka plan denetimi süreyi uzatmaz.

**Independent Test**: `oturum.son_kullanma` sürüklenir ve `olusturma + 8 sa`'yı aşmaz.

---

### User Story 5 - TP kapalıyken başlatma (Priority: P3) — yolculuk 11

Değiştiricideki "Kapalı · Başlat" `aiprobe-home` ve VM'in işidir; TP tarafında gereken yalnızca
VM açıldığında `/health` ve giriş devrinin çalışmasıdır. Bu spec'te TP kodu değişmez; e2e F4b
taşımada (PLAN §6) doğrulanır.

---

### User Story 6 - Yönetim: kişiye TP rol hesabı bağlama (Priority: P2)

`home/admin` "TP rol hesabı bağla" ekranı TP'nin `/admin/kimlik-bagi` ucunu `aiprobe-home` servis
kimliğiyle çağırır. Başka hiçbir çağıran (kullanıcı oturumu, başka servis hesabı, imzasız token)
kabul edilmez.

**Acceptance Scenarios**:

1. **Given** `email` = `AIPROBE_HOME_SA` olan doğrulanmış Google ID token, **When** `PUT`, **Then**
   bağ oluşur; aynı hesap başka kişiye bağlıysa 409.
2. **Given** başka e-posta, doğrulanmamış token ya da token yok, **When** herhangi bir uç,
   **Then** 401/403.
3. **Given** bağ kaldırılır, **Then** o hesabın epoch'u artar, açık oturumu düşer. Bağı kaldırmak
   **tek başına erişimi kesmez**: kişinin AI Probe'da TP rolü sürdükçe sonraki girişte JIT o rol
   için yeni bir rol hesabı açar. Erişimi kesen, rolün AI Probe'dan (home/admin) kaldırılmasıdır;
   bağ kaldırma yalnız kişiyi o belirli hesaptan ayırır.
4. **Given** iki eşzamanlı `PUT` aynı hesabı farklı kişilere bağlamaya çalışır, **Then** biri 200,
   diğeri 409 (`app_user_id UNIQUE` ihlali 500 değil).

### Edge Cases

- `TP_AUTH_MODE=local`: hiçbir `aiprobe` ucu yok (404), dış çağrı yok, çerez `tp_session`,
  mevcut testler değişmeden yeşil.
- `both`: yerel giriş de `__Host-tp_session` (Secure) kullanır; yerel oturumlar home'a sorulmaz.
  Bir AI Probe kişisine bağlı (`kimlik_bagi` satırı olan) hesap yerel parolayla **açılmaz**: parola
  doğruysa 403 `aiprobe_gerekli` (+ `auth.login_rejected`), yanlışsa her zamanki 401 (bağ durumu
  parolayı bilmeyene sızmaz). Bağlı hesap yalnız AI Probe ile girer.
- `aiprobe`: yerel oturum (`external_uid` boş; ör. `both`'ta açılmış) kabul edilmez; `tpt_` token'ı
  yalnız sahibi bir kişiye bağlıysa ve token bir AI Probe oturumundan üretildiyse (`auth_time`
  dolu) geçer.
- Aynı kişinin eşzamanlı callback'leri (iki sekme) çift JIT hesabı açmaz ve 500 vermez: kişi başına
  `pg_advisory_xact_lock`, mevcut hesaplar kilitten sonra okunur.
- Yeni giriş (callback, rol seçimi) tarayıcıdaki önceki oturum satırını iptal eder.
- Rol seçici: seçim çerezi 10 dk geçerli; oturum açılmadan önce home'a taze kontrol yapılır
  (iptal → 401, rol kaldırıldı → 403, erişilemez → 503).
- `/auth/me` `roles`: bağlı rol hesaplarından yalnız AI Probe'un şu an verdiği rollerdekiler.
- Yerel geliştirme: düz `http://localhost` isteğinde state çerezi Secure'suz `aiprobe_state`
  (CONTRACT); diğer her durumda `__Host-aiprobe_state`.
- `local`'e dönülürse `external_uid`'li oturumlar reddedilir (fail-closed).
- `continue=//evil`, `\`, şema, kontrol karakteri → `/`.
- `org` izinli değil / TP rolü yok → 403, JIT yapılmaz.
- Devir yanıtındaki bilinmeyen roller yok sayılır.
- Home 401 `invalid_caller` (TP'nin servis kimliği yanlış) → 503, oturum açılmaz.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `TP_AUTH_MODE` `local|aiprobe|both`; varsayılan `local` ve davranış değişmez.
- **FR-002**: `aiprobe`/`both`'ta `/auth/aiprobe/login` ve `/auth/aiprobe/callback` CONTRACT v1
  "Ürün tarafı" akışını uygular (state çerezi, sabit zamanlı karşılaştırma, sunucu takası).
- **FR-003**: Takas ve oturum kontrolü TP servis hesabının Google ID token'ıyla yapılır; sağlayıcı
  enjekte edilebilir (testte sahte, prod'da GCE metadata).
- **FR-004**: `kimlik_bagi(external_uid, app_user_id UNIQUE)`; yetki yine `app_user.rol` ile.
- **FR-005**: Tek eşleşme → oturum; çok eşleşme → rol seçici; eşleşmeyen rol → JIT hesabı.
- **FR-006**: "Rol değiştir" bağı ve rolü taze kontrolle yeniden doğrular ve oturum kimliğini
  yeniler.
- **FR-007**: `session_valid` ve `verify_bearer` ≥60 sn'de bir (önbellekli) oturum kontrolü yapar;
  geçersizde `auth_epoch` artar, oturumlar iptal, `tpt_` token'ları reddedilir.
- **FR-008**: Home erişilemezse oturum korunur ve `X-Aiprobe-Degraded: 1`; yeni giriş 503.
- **FR-009**: AI Probe oturumunda boşta 30 dk kayan / mutlak 8 sa.
- **FR-010**: Çerez adı `aiprobe`/`both`'ta `__Host-tp_session` (Secure), `local`'de `tp_session`.
- **FR-011**: `/admin/kimlik-bagi` yalnızca `AIPROBE_HOME_SA` servis kimliğini kabul eder.
- **FR-012**: Tüm giriş/rol/bağ olayları denetim kaydına yazılır (İlke VIII).
- **FR-013**: Tek Alembic göçü; tüm yeni kolonlar `server_default`'lu (ya da boş bırakılabilir).

### Key Entities

- **Kimlik bağı** (`kimlik_bagi`): AI Probe kişisi (`external_uid`) ↔ TP rol hesabı (`app_user`).
- **Rol hesabı** (`app_user`): + `auth_epoch` (iptal sayacı), `ad_soyad`.
- **Oturum** (`oturum`): + `external_uid`, `auth_time`, `son_kontrol`.
- **IDE token'ı** (`api_token`): + `auth_epoch` (üretimdeki sahip epoch'u).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `local` kipte mevcut core birim testleri değişmeden yeşil.
- **SC-002**: İptalden sonra en geç 60 sn içinde oturum ve `tpt_` token'ı 401 (sahte saatle test).
- **SC-003**: Home kesintisinde açık oturum, süre sınırları içinde çalışmaya devam eder.
- **SC-004**: Yolculuk 6, 13, 14 birim testleriyle; 11 ve prod e2e F4b taşımada yeşil.

## Assumptions

- `aiprobe-home` CONTRACT v1'i uygular; `products/testing-probe.yaml` `callback_url`'si portal
  önekli `https://testing.aiprobe.antreklabs.com/api/auth/aiprobe/callback` olur (platform
  şeridine bildirilecek).
- Portal ekranları (rol seçici sayfası `/rol-sec`, "Rol değiştir" menüsü, uyarı bandı, 401'de
  `/auth/aiprobe/login`'e yönlendirme) ayrı bir portal görevidir (tasks.md T040–T043).
- `feat/mobil-masaustu`'nun `0018` göçü `dev`'e birleşir; bu spec'in `0019` göçü gerekirse
  yeniden ebeveynlenir.
