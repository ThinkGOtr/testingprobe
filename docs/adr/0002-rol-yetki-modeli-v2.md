# ADR-0002 — Rol ve yetki modeli v2

- **Durum:** Kabul edildi — ürün sahibi kararları (2026-11-11), uygulama sürüyor
- **Tarih:** 2026-11-11
- **Kaynak:** "AI Testing Probe Rol ve Yetki Paketi v2" (Excel matris karar kaynağıdır; repoya
  girmez). Bağlayıcı analiz: `specs/012-rol-yetki/ANALIZ.md`.
- **Uygulama:** `core/src/tp_core/auth/yetki.py` (izin kataloğu), `specs/012-rol-yetki/`

## Bağlam

TP'de 5 rol vardı (`analyst`, `po`, `tester`, `engineer`, `presenter`); izinler router'lara dağılmış
`require_role(...)` çağrılarıyla veriliyordu ve okuma uçlarının çoğu oturum açan herkese açıktı.
Case kararı, yayını ve yayın token'ı Analist'teydi; PO onayı hem Jira etiketiyle hem portal
ucuyla verilebiliyordu; CI tetikleri ve demo kontrolleri `presenter`'daydı. Paket, görev
sahipliklerini ve rol setini yeniden tanımladı.

## Karar

1. **Rol seti (8):** `admin` Sistem Yöneticisi, `auditor` Denetçi, `analyst` Analist, `po` PO,
   `tester` Testçi, `engineer` Automation Engineer, `developer` Developer, `viewer` Görüntüleyici.
   Rol kimlikleri İngilizce kalır. `presenter` kalkar; göç `app_user.rol`'ü `admin`'e çevirir,
   AI Probe devrinde gelen `presenter` geçiş süresince `admin` sayılır.
2. **Tek izin kataloğu:** her uç bir izin anahtarı ister (`izin("case.approve")`); katalogda
   olmayan izin reddedilir (yazma ve okuma). Red 403 `yetki_yok` ve `authz.denied` denetim kaydı.
   Portal aynı kataloğu `/auth/me.izinler` ile kullanır; UI gizlemesi kontrol değildir.
3. **K1 çoklu rol:** bir kişi birden çok rol alır, rol hesapları arasında "Rol değiştir" ile geçer
   (ADR-0001 madde 3 korunur: yetki `app_user.rol` ile).
4. **K2 görevler ayrılığı role göre:** aynı kişinin Testçi ve Analist hesapları farklı aktördür;
   tek kişilik demo çalışır. Case son onayını veren hesap son düzenleyen hesaptan farklı olmalıdır.
5. **K3 PR kuralı:** "PR yazarı kendi PR'ını onaylayamaz" kuralı yoktur; Automation Engineer rolü,
   yeşil CI ve korumalı dal (merge kapısı) yeterlidir.
6. **K4 proje kapsamı:** tek proje; proje/tenant filtresi ve proje bazlı rol bu fazda yok.
7. **K5 rol ataması AI Probe'da:** TP'de kullanıcı/rol yönetim ekranı, `access.assign` izni ve
   Erişim Yöneticisi rolü yoktur. AI Probe ürün kaydında `admin_roles: [admin, po]`.
8. **K6 PO onayı Jira'da:** etiketi koyan aktör PO listesinde ve içerik hash'i eşleşir. Jira
   kaynaklı gereksinimde portal PO onay ucu (`POST /requirements/{id}/po-approve`) 410
   `po_onayi_jira` döner, düğmesi kalkar. Serbest metin gereksinimde (`kaynak == free_text`, Jira'da
   story yok) portal PO onayı kalır: izin `requirement.po_approve_free_text` (po), hash kontrolüyle.
9. **K7 paketin kapsamadığı özellikler:** sahibi PO (baz değer). Doküman düzeltmesini Jira'ya
   uygulama ve "Son hal olarak onayla" Analist'te kalır (`requirement.review`). İstisnalar: locator
   onarımı Automation Engineer, Claude Code yayın token'ı Testçi.
10. **Case akışı:** Testçi `accept`/`edit` → yeni `ready` durumu → Analist `approve` (ya da
    gerekçeli `send_back` → `draft`) → Testçi yayın. Yayın kapısı yalnız `approve`'u sayar.
11. **Ortam bayrakları:** `TP_ORTAM` (`dev|test|staging|prod`, varsayılan `dev`) ve `TP_DEMO_MODE`
    (varsayılan `0`). Demo kontrolleri yalnız `TP_DEMO_MODE=1` iken; `TP_ORTAM=prod` ile
    `TP_DEMO_MODE=1` birlikte verilirse çekirdek başlamaz. Developer `prod`'da koşu başlatamaz.

## Sonuçlar

- (+) Yetki tek dosyada okunur ve test edilir; yeni uç izinsiz eklenirse katalog testi kırılır
  (varsayılan ret).
- (+) Okuma da yetkiye bağlanır: Denetçi ve Görüntüleyici ham artefakt ve canlı olay görmez;
  denetim kaydının tamamını yalnız `admin`/`auditor` görür.
- (−) Canlı demo kurulumunun `.env`'ine `TP_DEMO_MODE=1` eklenmezse demo kontrolleri kapanır.
- (−) AI Probe'daki canlı rol kayıtlarının (`presenter` → `admin`) güncellenmesi dış sisteme
  yazmadır ve ayrı onay ister; o zamana kadar TP eşlemeyi kendisi yapar.
- (−) Demo akışında case adımı ikiye ayrılır (Testçi kararı + Analist onayı); tek kişi rol
  değiştirerek yürütür.

## Reddedilen seçenekler

- **Paketteki `rbac.ts` taslağını kopyalamak:** çekirdek Python; taslakta çalışmayan guard'lar var.
- **Rol kimliklerini Türkçeleştirmek:** mevcut kayıtlar, AI Probe claim'leri ve testler bozulur;
  etiketler zaten Türkçe gösterilir.
- **Paketin durum adlarına (`IMPORTED/REVIEWED/...`) geçmek:** mevcut durum makineleri korunur;
  yalnız case'e `ready` eklenir.
