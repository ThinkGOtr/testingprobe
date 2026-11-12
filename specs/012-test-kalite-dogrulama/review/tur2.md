# 012 — Review turu 2 bulguları (2026-11-12, 75bd7f2)

## Güvenlik + doğrulama bağımsızlığı (`g2`)

Tur 1 hükümleri: güvenlik 3,4,5,6,9,11 KAPANDI; 1,2,7,10,12,13 KISMEN; 8 AÇIK (karar gereği).
Bağımsızlık K1,O4,O6,O8,O9,S1,S2,S3 KAPANDI; K2,K3,K4,K5,O1,O3,O5,O7,S4,S5,S6 KISMEN; O2 AÇIK.

KRİTİK
- Y1. Tamlık denetimi atlatılıyor: "Toplam 45,00TL" (harfe bitişik), "kırk beş TL" (yazıyla) ve `ignored` ile yanlış değer `uyumlu` çıkıyor (dogrulama.py:484 sayi_gecisleri, :590, :689 _eksik_mi). Düzeltme: birime bitişik sayıları say (kod benzeri P-001/S1 hariç); beklenen alanda çıktı kolonunun birimi/adı geçip olgu yoksa en az kismen; `ignored` boş değilse en iyi kismen (zorunlu kapıda gerekçe) ya da çıktı birimli ignored alıntısını reddet; yazıyla sayıya kismen uyarısı.
- Y2. AC ref iki adımda aklanıyor: edit AC1→AC2 doğru değerlerle onay → taslağa al → yanlış değerli edit; saklı ∪ gönderilen = {AC2}, kapsayan tablo yok → sessiz onay (kapi.py:134-135, :185-186, service.py:382 karar_sonrasi). Düzeltme: taban = saklı ∪ AI özgün ∪ önceden onaylanmış içerikler (ya da kalıcı ac_tabani/risk_tabani); tabandan düşüş istisnasız onaylanmasın.

ÖNEMLİ
- Y3. Türetilen / AI dışı case'te risk iki adımda düşüyor (service.py:174 ai_icerikleri yalnız ai_generated). Düzeltme: Y2 tabanı; türetilen case'te kaynak case içeriği "özgün".
- Y4. `kismen` yüksek risk onayına kapı açıyor (sıfır genişlikli karakterle alıntı düşürme) (kapi.py:207-208). Düzeltme: zorunlu kapıda, nedeni atılan olgu / kapsanmayan sayı olan kismen gerekçe istesin; alanlarda NFKC + sıfır genişlik temizliği.
- Y5. Geçici model hatası kalıcı `kontrol_edilemedi` olarak önbellekte (service.py:514). Düzeltme: neden cagri_hatasi/replay_miss kaydını geçersiz say, hız sınırıyla yeniden kuyruğa al.
- Y6. Kapı 409 yolu sınırsız model çağrısı açıyor; hız sınırı yalnız /oracle-check'te, case'ler arası ve TOCTOU kaçağı (kapi.py:192, api.py:89). Düzeltme: sınırı kontrol_kuyruga_al içinde; kullanıcı ve gereksinim başına; sayımda advisory lock.
- Y7. K12 ai/el ayrımı yol adıyla taklit edilebilir; failure location da bakılıyor (hata_kosusu/service.py:800 test_kaynagi). Düzeltme: ai = ScriptCodegen kaydıyla (onaylı case + hash) eşleşen dosya; yalnız t.file.
- Y8. "Temelde yeşil" şartı doğrulanmıyor (skipped / başlığı değişen test; MAX_TEMEL_KIRMIZI aşımı) (service.py:915-917). Düzeltme: temelde yeşil anahtar kümesini sakla, üyelik iste; sınır aşılırsa platform gecersiz.
- Y9. İstisna analistin gördüğü kayda bağlı değil; tür verilmezse sonuçtan çıkarılıyor (kapi.py:209-227). Düzeltme: gövdeye görülen tablo_hashleri/kayıt damgası, uymazsa 409; gerekçe varsa tür zorunlu.

KÜÇÜK
- Y10. Kule oranı tek geçerli adımla "tam katalog" (gecersiz adımlar kosulan'a giriyor). Düzeltme: geçerli adım oranı alt eşiği (≥ %50), yoksa oran null.
- Y11. Saklı istisnanın yeniden kullanımı iz bırakmıyor. Düzeltme: oracle.exception_reused + review ölçülerine istisna_id.
- Y12. Aynı (case, hash) kontrol satırını farklı tablo kümeleri üzerine yazıyor (kapı saklı ∪ gönderilen ile, karar_sonrasi/gereksinim işi içerik ref'leriyle). Düzeltme: anahtara tablo kümesi özeti ya da ayrıntıyı ekleme-yalnız sakla.
- Y13. Birleştirilmiş gereksinim işinde olay kaybı (retry'daki işe birleşen neden, iş kalıcı başarısız olursa kaybolur) (service.py:331). Düzeltme: yalnız queued işlere birleştir ya da başarısızlıkta yeniden kuyruğa al.
- Y14. Tamlık denetimi dar: title ve girdi alanları (steps[i].data, test_data) taranmıyor.
- Y15. İptal istenmişken beklenmeyen hata → koşu cancelled yerine failed (service.py:965). Düzeltme: _kapat öncesi iptal_istendi'ye bak.
- Ayrıca: hata koşusu `neden` alanı ham toolchain metni + Appium URL'si taşıyor (güvenlik-12); evaluate `icerik` boyut sınırı yok (güvenlik-13); portalda "tek bağımsızlık insan incelemesidir" metni yok (O2); codegen onaylı-uyumsuz case'i bilmiyor (S5).

## Ön yüz/UX + analist/PO (`u2`)

Tur 1 hükümleri: ön yüz 1–5,7–15,17–20,23 KAPANDI; 6,21,22 KISMEN; 16 doğrulanmadı.
Analist 2,4,7,8,9,13,14,15,17,18,19,20 KAPANDI; 1,3,5,6,10,12 KISMEN; 11,16 AÇIK (demo dokümanları; 500→750 geçmişi).
axe 0 ihlal (3 sayfa), 390 px'te taşma yok.

KRİTİK
- N1. Kule beklenti doğruluğu mock'ta sabit (mock/kule.ts:340 MOCK_BEKLENTI, kuleVerisi.ts:260); başlangıçta "%83 · 1 uyuşmayan · 1 kısmen · 1 istisna" ama case kartlarında 0; uyuşmazlık insanın yanlış tablosundan geliyor ama AI'a yazılıyor; payda 6, "n = 10". Düzeltme: KPI'ı kaliteVerisi(v)'den hesapla; "5/6" yaz; "Tablo yanlış" yoluyla kapanan uyuşmazlığı AI'a yazma (core metrik.py'de de karar).
- N2. "AI sınır hatası engellendi" hikâyesi yok: sınır hatasını analist yapıyor (`<= 750`), kapı doğru AI case'ini (C6) engelliyor (kaliteVerisi.ts:13-17, 84-92). Düzeltme: `<= 750` AI taslağının hatası olsun, PO ızgarada yakalasın; ayrıca AI'ın yanlış yazdığı case golden'ı ("750,00 TL'de uyarı görünür") → uyumsuz → engel → düzelt.

ÖNEMLİ
- N3. Özet cümlesinde Python repr ("tablo True") — core oracle/dogrulama.py:769, mock kalite.ts:507. Türkçe biçimleyici (doğru/yanlış, “…”, 1.234,56).
- N4. Kule "üretilmiş test yok" derken triage tests/generated/ altındaki testin kırmızısını gösteriyor (fixtures.ts:1399-1430). Not ya da mock koşusuna üretilmiş testler (C3 "temelde kırmızı, hariç").
- N5. "Tablo yanlış" yolu tabloyu tek tıkla gerekçesiz yeniden açıyor (oracle.tsx:470-505). Etki onayı ("N case'in kontrolü durur"), zorunlu gerekçe, PO'ya ve case'e bağlı kayıt.
- N6. kampanya_tek_bedava açıklaması yanlış ("12 adet ve üstünde" — 12'de story de 1 der). "14 adette (7'nin 2 katı) ayrılır"; ayirt_edici öne.
- N7. "Bu girdiyle ek case türet" girdiyi (adet 14, İ1, C2) taşımıyor; mühendis/sunucu analist kilitli düğmeye düşüyor (HataKosusuKarti.tsx ~625). ?iliski=&kaynak= + önizleme; analist dışı rolde "Analiste ilet (kopyala)".
- N8. "Satırların anlamı" PO için hâlâ formül; girdi adı Türkçe karaktersiz. Çıktı/girdi aciklama alanlarıyla cümle.
- N9. İçerik değişince PO neyin değiştiğini görmüyor (ortak.tsx:221-235). Görülen hash ile güncel arasında satır farkı.
- N10. Onaylı-uyumsuz listesi istisnalı case'i de sayıyor (mock kule.ts:326-334); §13.2 hariç tutmasını uygula.

KÜÇÜK
- N11. Türetilen case başlığı kesiliyor; AI olmayan case'te "AI 0 ms".
- N12. Ek case türet kaynak listesi ilişkinin AC/tablosuyla süzülmüyor.
- N13. Tablo satırlarında dogru/yanlis ASCII; okuma görünümünde Türkçe.
- N14. Kural dağılımında geçersiz adım hücrede görünmüyor.
- N15. Yakalanan adım notunda test adı cümleye karışıyor.
- N16. Son koşular tablosunun son sütunu başlıksız ("gösteriliyor").
- N17. Yüzen "Asistanı aç" düğmesi 1440 px'te T1 Tolerans sütununu ve C10 Reddet'i örtüyor.
- N18. Mantıksal çıktı "doğru · satır R2" yerine iş dili ("uyarı görünür/görünmez").
- N19. Sınır örnekleri ızgarasında "story ne diyor" sütunu yok; eşik satırları işaretli değil.

### Önerilen müşteri demo akışı (8 adım; N1, N2, N4 düzelince birebir)
1. Analist → TPD-1 → Karar tabloları: T1 onaylı, satır anlamı + sınır örnekleri (6/7/8, 13/14).
2. PO → T2 → sınır örnekleri: 750'de uyarı satırı → "Değişiklik iste" → analist `< 750` → PO onay.
3. Case review → AI'ın sınır hatası yaptığı case: "Tabloyla uyuşmuyor ✗", yüksek risk, iki yol.
4. C2 → tablo karşılaştırması (ara toplam 175, indirim 25, toplam 150).
5. Hatalar → C3 testi: ürün hatası, "Uygulama onaylı kurala aykırı (T1 · R2)".
6. Kule → ekilmiş hata koşusu: el yazısı 8/9, AI "ölçülmedi", kural dağılımı.
7. Kaçan `kampanya_tek_bedava` → "Bu girdiyle ek case türet" (İ1, C2, adet 14) → 14 adetlik case.
8. Kule KPI'ları: n, "gösterge", REPLAY/elle golden etiketleri.

## Test + mimari (`t2`)

Tur 1 hükümleri: test K1,K2,Ö2,Ö4–Ö8,S2–S6,S8,S9 KAPANDI; Ö1,Ö3,S1 (çelişki),S7 KISMEN.
Mimari 3,5–11,13,14,20,21 KAPANDI; 1,2,4,12,15,17,18 KISMEN; 16,19 AÇIK (16 birleştirmeye ertelendi); 22 kabul.
§9 senaryoları: hepsi kapsanmış; #4 Kule (istisna > 0 Kule-API testi yok) ve #17 (sessiz atlanabilir) zayıf.

KRİTİK: yok.

ÖNEMLİ
- N1. Bitmiş ama kayıt yazmadan atlamış kontrol işi anahtarı kilitliyor → A→B→A ya da T→T'→T sonrası kapı sonsuz 409 (oracle/service.py:261-275 _bos_anahtar yalnız failed/cancelled'ı atlıyor; kapi.py:192-198; kayit_damgasi "yok"). karar_sonrasi ve run_check_requirement anahtarları da aynı. Düzeltme: geçerli kayıt yokken done'ı da failed gibi say (sonek) ya da işçi "atlandı" damgası yazsın; A→B→A testi.
- N2. S1 sözleşme çelişkisi: core aynı tür geçerli saklı istisnayla gerekçesiz onaylıyor (kapi.py:229-231, §13.2), portal engelliyor (oracle.tsx:691, oracle.test.tsx:269); mock portalı izliyor. Tek kural + mock/core uyum testi.
- N3. Tüm üretilmiş testler temelde kırmızıysa AI oranı "ölçülmedi" yerine %0 (hata_kosusu _envanter, ozet_hesapla ai_var). Envanteri kaynak başına temelde yeşil testlerle say.
- N4. Adımda herhangi bir beklenmeyen istisna (DB OperationalError, deadlock) çok saatlik koşuyu kalıcı failed yapıyor (calistir catch-all). DBAPIError/taşıma hatalarını yeniden fırlat; yalnız son denemede failed.
- N5. Kapı FOR SHARE'i (kapi.py:102-108, ORDER BY yok, tüm durumlar) ile _ai_taslaklari_gecersiz_kil FOR UPDATE (sira_no sırası) arasında deadlock → 500. Yalnız approved/pending_po, id sırası; ya da gereksinim başına advisory lock (decide paylaşımlı, onayla/yeniden_ac/gecersiz_kil özel).
- N7. v3 birleşmesi listeden zor: 0022 revision çakışması; docstring (0022_kalite_dogrulama.py:26) ve ANALIZ §12.1 hâlâ "0021"; downgrade v3 kısıt kümesini geri yüklemeli; tests/unit/platform/test_aiprobe_sso.py:938-943 ["0022"] ve down_revision "0020" sabit; v3 0026 review_ret_nedeni_ck ile request_changes review'ları; v3 toplu onay (cases/toplu.py) savepoint içinde decide → 409 yolunda case başına ek bağlantı, oracle_istisna_gerekce geçirilemiyor.

KÜÇÜK
- N6. Birleştirici retry'daki işe de neden ekliyor; iş başarısız olursa kaybolur (service.py:342-358). Yalnız queued; TP_ORACLE_BIRLESTIRME_S=0 nedeniyle 2 sn yolu ve running'e birleştirme test edilmiyor.
- N8. Aynı (case, hash) satırı iki tablo kümesiyle değerlendiriliyor (kapı/oracle-check birleşim, karar_sonrasi/check_requirement kendi ref'leri) → karşılıklı geçersizleştirme, fazla model çağrısı, istisna gecerli:false.
- N9. Triage inceltme bastırması istisna türüne ve tablo kümesine bakmıyor; her çağrıda to_regclass (triage/service.py:578-669). tur='uyumsuz' + güncel tablo_hashleri.
- N10. İndekssiz iş tablosu taramaları (oracle/api.py:89-110 yuk->>'case_id', atomik değil; hata_kosusu/service.py:219 LIKE); oracle.check_* işleri için saklama yok.
- N11. Kule'de O(n) kalan iş (metrik.py:77-149, onayli_uyumsuz, hata_yakalama_ozeti 20 _adimlar sorgusu).
- N12. _baslangic hata_kosusu FOR UPDATE tutarken forge().head_sha ağ çağrısı → iptal bekler.
- N13. test_sabit_satirlar.py:51 skipif → core konteynerinde sessiz atlanıyor; CI/TP_TEST_REQUIRE_DB'de başarısız olsun.
- N14. Kapı görülen-hash denetiminden önce çalışıyor (bayat istekte de 409 işi + dusurme audit + ikinci bağlantı). beklenen_hash'i önce denetle.
- N15. Portal testleri hâlâ gerçek zamana bağlı (oracle.test.tsx:47,380,425).
