# Feature Specification: Geliştirme ve Demo Ortamı Temeli

**Feature Branch**: `001-dev-foundation`

**Created**: 2026-10-30

**Status**: Draft

**Input**: User description: "001-foundation — docs/TEKNIK-TASARIM.md §17 F0: repo, Spec Kit, constitution, tüm servislerin tek komutla ayağa kalktığı yerel ortam iskeleti, sağlık kontrolleri, sıfırlama ve temel güvenlik kısıtları."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Tek komutla ortamı ayağa kaldırmak (Priority: P1)

Ekipteki bir geliştirici (Gökhan, Hakan veya İsmail) repoyu kendi Mac'ine çekip tek bir komutla
ürünün çalışması için gereken tüm bileşenleri başlatır ve hepsinin sağlıklı olduğunu görür. Başka bir
kurulum adımı, kişiye özel ayar veya ekip içi "bende çalışıyor" bilgisi gerekmez.

**Why this priority**: Sonraki tüm özellikler (F1–F6) bu ortamın üzerinde geliştirilir ve demo bu
ortamda yapılır. Ortam güvenilir şekilde kalkmadan hiçbir ekip üyesi paralel çalışamaz.

**Independent Test**: Temiz bir makinede repo çekilir, örnek sırlar dosyası doldurulur ve başlatma
komutu çalıştırılır; tüm bileşenlerin sağlık durumu "sağlıklı" olarak raporlanır.

**Acceptance Scenarios**:

1. **Given** önkoşulları karşılanmış bir Mac ve doldurulmuş sırlar dosyası, **When** geliştirici
   başlatma komutunu çalıştırır, **Then** tüm bileşenler doğru sırayla başlar ve komut, her bileşenin
   sağlıklı olduğunu bildirerek tamamlanır.
2. **Given** çalışan ortam, **When** geliştirici durum komutunu çalıştırır, **Then** her bileşenin
   adı, sağlık durumu ve (varsa) yerel erişim adresi listelenir.
3. **Given** eksik veya boş bırakılmış zorunlu bir sır, **When** başlatma komutu çalıştırılır,
   **Then** başlatma hangi sırrın eksik olduğunu açıkça söyleyerek durur ve hiçbir bileşen yarım
   başlamış halde kalmaz.

---

### User Story 2 - Ortamı temiz başlangıç durumuna döndürmek (Priority: P2)

Demo sunucusu veya geliştirici, ortamı tek komutla bilinen temiz başlangıç durumuna döndürür; böylece
her prova ve her demo aynı noktadan başlar. Sıfırlamadan önce denetim kaydı dışa aktarılır ve
kaybolmaz.

**Why this priority**: Brief ve tasarım "3 ardışık sorunsuz prova, her biri temiz sıfırlama
sonrası" şartını koyuyor. Sıfırlama olmadan demo tekrarlanabilir değildir. Ancak ortam kalkmadan
(US1) sıfırlamanın anlamı yoktur.

**Independent Test**: Ortamda veri oluşturulur, sıfırlama komutu çalıştırılır; denetim kaydının
dışa aktarım dosyası oluşmuş ve ortam ilk kurulumdaki duruma dönmüş olmalıdır.

**Acceptance Scenarios**:

1. **Given** içinde veri ve iş akışı geçmişi olan çalışan ortam, **When** sıfırlama komutu çalışır,
   **Then** önce denetim kaydı imzalı bir dosyaya dışa aktarılır, ardından uygulama verisi ve iş
   akışı geçmişi temizlenir ve ortam sağlıklı biçimde yeniden başlar.
2. **Given** denetim kaydı dışa aktarımı başarısız olur, **When** sıfırlama sürerken, **Then**
   sıfırlama hiçbir veriyi silmeden durur ve hatayı bildirir.
3. **Given** sıfırlanmış ortam, **When** başlangıç verisi yükleme komutu çalışır, **Then** demo
   kullanıcıları ve başlangıç verisi deterministik olarak (her seferinde aynı kimliklerle) yüklenir.

---

### User Story 3 - Güvenli varsayılanlar (Priority: P2)

Bir güvenlik incelemecisi (CCI'ın güvenlik ekibi veya kendi AppSec'imiz), ortamın dışarıya kapalı
olduğunu, sırların depoya girmediğini ve kod çalıştıran bileşenin ağ ve sır erişiminin kısıtlı
olduğunu doğrulayabilir.

**Why this priority**: Constitution'daki güvenlik ve mimari kısıtlar ilk günden ortamın yapısına
gömülü olmalı; sonradan eklemek pahalıdır. Kısıtları otomatik doğrulayan kontroller sonraki
özelliklerin regresyonunu da önler.

**Independent Test**: Otomatik güvenlik kontrolü çalıştırılır; dışarıya açık port, depoda sır ve
izole bileşenden yasaklı hedeflere erişim bulunmadığı raporlanır.

**Acceptance Scenarios**:

1. **Given** çalışan ortam, **When** ağdaki başka bir makineden ortamın herhangi bir portuna
   bağlanılmaya çalışılır, **Then** bağlantı kurulamaz (tüm erişim yalnızca yerel makineden).
2. **Given** çalışan ortam, **When** kod çalıştıran izole bileşenden iş akışı motoruna, veritabanına
   veya internete bağlantı denenir, **Then** tüm denemeler başarısız olur.
3. **Given** depo, **When** sır tarama kontrolü çalışır, **Then** depoda hiçbir gerçek sır bulunmaz;
   yalnızca örnek sırlar dosyası vardır.

---

### User Story 4 - Ortak çalışma kuralları ve proje iskeleti (Priority: P3)

Yeni katılan bir ekip üyesi, deponun yapısını, çalışma kurallarını (constitution), sürüm
sabitleme politikasını ve özelliklerin hangi dizinlere yazılacağını tek bir giriş dokümanından
öğrenir ve kendi özelliğine (F1, F2a) yabancılık çekmeden başlar.

**Why this priority**: Paralel çalışmanın (Hakan F1, İsmail F2a) sürtünmesiz olması için gerekli,
ancak ortam çalışmadan değer üretmez.

**Independent Test**: Yeni bir ekip üyesi yalnızca giriş dokümanını okuyarak ortamı kaldırır ve
kendi özelliğinin dizinini doğru bulur.

**Acceptance Scenarios**:

1. **Given** depo, **When** ekip üyesi giriş dokümanını açar, **Then** önkoşulları, başlatma,
   durum, sıfırlama ve temizlik komutlarını, dizin yapısını ve constitution bağlantısını bulur.
2. **Given** depo, **When** ekip üyesi sürüm sabitleme dosyalarına bakar, **Then** tarayıcı
   otomasyon aracı sürümünün tek bir kaynaktan yönetildiğini görür.

### Edge Cases

- Docker çalışmıyorsa veya ayrılan disk/bellek yetersizse başlatma komutu ne yapar? → Başlamadan önce
  önkoşul kontrolü yapar ve hangi kaynağın eksik olduğunu (ör. "en az 30 GB boş disk gerekli")
  söyleyerek durur.
- Bir bileşen sağlık kontrolünden belirli süre içinde geçemezse? → Başlatma, hangi bileşenin
  sağlıksız olduğunu ve son log satırlarını göstererek başarısız olur.
- Ortam zaten çalışırken başlatma komutu tekrar çalıştırılırsa? → Komut idempotenttir; çalışan
  bileşenleri bozmaz, yalnızca eksikleri başlatır.
- Sıfırlama yarıda kesilirse (ör. kullanıcı iptal eder)? → Bir sonraki sıfırlama kaldığı yerden
  güvenle tamamlanabilir; denetim kaydı dışa aktarımı her zaman silmeden önce yapılmış olur.
- Port çakışması (yerelde aynı portu kullanan başka bir uygulama) olursa? → Başlatma, çakışan portu
  ve onu kullanan süreci bildirerek durur.
- Apple Silicon dışı bir makinede çalıştırılırsa? → Desteklenen mimariler belgelenir; tüm
  bileşenler hem arm64 hem amd64 için kullanılabilir olmalıdır.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Sistem, ürünün ve demonun ihtiyaç duyduğu tüm yerel bileşenleri (iş akışı motoru,
  veritabanı, çekirdek servis ve çalışan iş süreçleri, kod araç zinciri, izole test koşucusu,
  tarayıcı otomasyon sunucusu, inceleme portalı, örnek uygulama) tek bir komutla başlatabilmelidir.
  F0 kapsamında henüz iş mantığı olmayan bileşenler, sağlık kontrolüne cevap veren iskelet olarak
  bulunur.
- **FR-002**: Sistem, bileşenleri bağımlılık sırasına göre başlatmalı ve bir bileşen ancak
  bağımlı olduğu bileşenler sağlıklı olduğunda başlamalıdır.
- **FR-003**: Her bileşen bir sağlık kontrolü sunmalı; durum komutu tüm bileşenlerin sağlık
  durumunu tek ekranda göstermelidir.
- **FR-004**: Başlatma öncesinde önkoşullar (konteyner çalışma ortamı, boş disk ≥ 30 GB, ayrılmış
  bellek, zorunlu sırlar) kontrol edilmeli; eksik önkoşul açık mesajla bildirilmelidir.
- **FR-005**: Zorunlu sırlar yalnızca depo dışında tutulan bir yerel dosyadan okunmalı; depoda
  yalnızca tüm anahtarları açıklamalı listeleyen bir örnek dosya bulunmalıdır.
- **FR-006**: Ortamın dışarıya açtığı tüm erişim noktaları yalnızca yerel makineye (localhost)
  bağlanmalıdır.
- **FR-007**: Kod çalıştıran izole test koşucusu yalnızca örnek uygulamaya ve kendisine iş gönderen
  araç zinciri bileşenine erişebilmeli; iş akışı motoruna, veritabanına, sırlara ve internete
  erişememelidir.
- **FR-008**: Veritabanında denetim kayıtları için kullanılan uygulama rolü yalnızca ekleme ve okuma
  yetkisine sahip olmalı; güncelleme ve silme yetkisine sahip olmamalıdır (constitution VIII).
- **FR-009**: Sistem, ortamı temiz başlangıç durumuna döndüren bir sıfırlama komutu sunmalıdır.
  Sıfırlama, herhangi bir veriyi silmeden önce denetim kaydını imzalı bir dosyaya dışa aktarmalı;
  dışa aktarım başarısızsa hiçbir şey silmeden durmalıdır. (Jira ve GitHub temizliği sonraki
  özelliklerde bu komuta eklenir.)
- **FR-010**: Sistem, demo kullanıcılarını ve başlangıç verisini deterministik kimliklerle yükleyen
  bir başlangıç verisi komutu sunmalıdır.
- **FR-011**: Sistem, kullanılmayan konteyner imajlarını ve önbellekleri temizleyen bir temizlik
  komutu sunmalıdır.
- **FR-012**: Tarayıcı otomasyon aracının sürümü tek bir kaynak dosyadan yönetilmeli; bu sürümü
  kullanan tüm bileşenler (otomasyon sunucusu, araç zinciri, test koşucusu, test kütüphanesi) aynı
  sürüme bağlanmalıdır.
- **FR-013**: Kullanılan tüm dış imajlar sabit sürüm ve özet (digest) ile tanımlanmalı; bağımlılıklar
  kilit dosyalarıyla sabitlenmelidir.
- **FR-014**: Depoda proje constitution'ı, teknik tasarım dokümanı bağlantısı ve yeni ekip üyesi için
  bir giriş dokümanı (önkoşullar, komutlar, dizin yapısı) bulunmalıdır.
- **FR-015**: Sistem, FR-006, FR-007 ve FR-008'i doğrulayan, tek komutla çalışan otomatik güvenlik
  kontrolleri sunmalıdır.
- **FR-016**: Başlatma komutu idempotent olmalı; çalışan ortamda tekrar çalıştırıldığında mevcut
  bileşenleri bozmamalıdır.
- **FR-017**: Ortam, Apple Silicon (arm64) Mac üzerinde Docker Desktop ile çalışmalı; kullanılan
  imajlar amd64 için de mevcut olmalıdır (CI uyumu).

### Key Entities *(include if feature involves data)*

- **Bileşen**: Ortamı oluşturan çalışan parça; adı, rolü, bağımlılıkları, sağlık durumu ve (varsa)
  yerel erişim adresi vardır.
- **Sırlar dosyası**: Depo dışında tutulan, ortamın ihtiyaç duyduğu anahtarların değerleri; örnek
  dosyası depoda anahtar listesi ve açıklamalarıyla durur.
- **Denetim kaydı dışa aktarımı**: Sıfırlama öncesinde üretilen, imzalı ve zaman damgalı dosya.
- **Başlangıç verisi**: Demo kullanıcıları (analist, mühendis, sunucu rolleri) ve deterministik
  kimlikli örnek kayıtlar.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Önkoşulları hazır bir makinede, imajlar indirilmiş durumdayken, başlatma komutundan
  tüm bileşenlerin sağlıklı raporlanmasına kadar geçen süre 3 dakikanın altındadır.
- **SC-002**: İlk kez kurulan bir makinede (imajlar indirilmemiş) ortam 20 dakika içinde tamamen
  sağlıklı hale gelir.
- **SC-003**: Sıfırlama + başlangıç verisi yükleme, 2 dakika içinde ortamı demoya hazır başlangıç
  durumuna döndürür ve 3 ardışık denemede aynı sonucu verir.
- **SC-004**: Otomatik güvenlik kontrolleri %100 geçer: dışarıdan erişilebilen port sayısı 0,
  izole bileşenden yasaklı hedeflere başarılı bağlantı sayısı 0, depoda tespit edilen sır sayısı 0.
- **SC-005**: Ekipten en az bir kişi (ortamı kurmamış olan), yalnızca giriş dokümanını kullanarak
  ortamı 30 dakika içinde ayağa kaldırır.
- **SC-006**: Ortam çalışırken toplam bellek kullanımı 10 GB'ı aşmaz; disk kullanımı 30 GB içinde
  kalır.

## Assumptions

- Ekip, Apple Silicon Mac'ler ve Docker Desktop kullanır; Docker Desktop lisans durumu şirketçe
  teyit edilecektir (alternatif: Colima).
- Sırlar (model sağlayıcı anahtarı, Jira, GitHub uygulaması) F0 için zorunlu değildir; F0'da
  yalnızca sağlık kontrolü için gereken yerel sırlar (veritabanı parolası, denetim imza anahtarı)
  zorunludur. Diğerleri ilgili özelliklerde zorunlu hale gelir.
- Denetim imza anahtarı macOS Keychain'de tutulur; giriş dokümanı bunu nasıl oluşturacağını anlatır.
- Jira ve GitHub temizliğini kapsayan tam sıfırlama F3 ve F1/F5 ile genişletilir; F0'daki sıfırlama
  yalnızca yerel veriyi kapsar.
- GitHub ruleset ve CI iş akışları F1 kapsamındadır (GitHub Team planına bağlı).
- `docs/` altındaki gizli belgeler (CCI'a giden belgeler, iç notlar) depo dışı bırakılır; teknik
  tasarım dokümanı depoya girer (karar bekliyor).
- Teknik ayrıntılar (imaj adları, portlar, sağlık kontrolleri) `docs/TEKNIK-TASARIM.md` §11'dedir
  ve plan aşamasında kullanılır.
