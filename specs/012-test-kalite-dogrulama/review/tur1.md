# 012 — Review turu 1 bulguları (2026-11-12)

Altı rol bağımsız inceledi (`git diff e0e5015..HEAD`, o günkü `feat/test-kalite-dogrulama`). Kararlar
ANALIZ §13'te. Kimlikler (ör. `guvenlik-3`, `test-K1`) tur 2'de "kapandı mı" denetimi için kullanılır.

## Ön yüz / UX / erişilebilirlik (`onyuz`)

KRİTİK
1. "İstisnayla düzeltip onayla" ilk gönderimdeki içeriği yolluyor; analistin sonraki düzeltmesi kaybolur (kalite/oracle.tsx:479-481, CaseKarti.tsx:132-150).
2. Kapsayan tablo var ama kayıt yoksa "Kontrol sürüyor" yüksek riskli onayı zaman aşımı olmadan kalıcı engelliyor (oracle.tsx:54-63, 92). Yalnız sunucu `kontrol_suruyor: true` dediğinde engelle; "Kontrolü yeniden iste".

ÖNEMLİ
3. Ligatürler `>=` → `≥` gösteriyor (`.kt-ifade`, `.mono` girdiler) → `font-variant-ligatures: none`.
4. İfade dili yardımı yalın; örnek, girdi adları, metin sabiti, ondalık ayırıcı, `//`, `yuvarla` açıklaması yok.
5. İlişki düzenleyicisinde sağ taraftaki adların (kaynak değer) ve `←` anlamı yazmıyor.
6. PO neyin değiştiğini görmüyor; SSE yenilemesi içerik hash'ini sessizce değiştirip PO'ya okumadığı içeriği onaylatabiliyor. Hash'i sabitle, "siz bakarken değişti", onaylı sürüme fark, onay notu.
7. Durum geçişlerinden sonra odak `<body>`'ye düşüyor, duyuru yok.
8. Hata koşusu süre tahmini yanlış/eksik ("9 hata × 1 platform = 11 koşu"; temel+kapanış; web süresi; uzun koşuda onay yok).
9. İlerlemede geçen/kalan süre yok.
10. SSE yokken Kule KPI'ları bayat kalıyor (yoklama koşuyu bitirince `olcuDegisti` çağrılmıyor).
11. Hata koşusu kartında odak kaybı (başlat, iptal, geçmişte "Aç").
12. Gereksinim yüklenemezse eylemler açılıyor ve "kabul kriteri yok" yanıltıcı mesajı.
13. Türetme sonucu bağlantıları genel case listesine gidiyor.
14. Türetme geçmişi ekranı yok (`metamorfikTuretmeler` çağrılmıyor).

KÜÇÜK
15. Onaylı kayıtta "AI taslağı" çipi → "AI kökenli".
16. "bu ölçümü bildirmiyor" / "bu ölçüyü bildirmedi" tutarsızlığı.
17. Atlama nedenleri jargon ("olgu yok", "belirsiz alıntı").
18. "Alıntı" sütunu → "Case metnindeki ifade".
19. Karşılaştırmada tolerans görünmüyor.
20. "Örnekle dene" bayat sonuç tutuyor; tür başına ipucu yok.
21. Satır kimliği hataları alana bağlı değil.
22. Yeniden üretim kutusunda Vazgeç odağı geri vermiyor.
23. İlerleme `role="status"` her yoklamada yeniden duyuruluyor.

## Analist / PO (`analist`)

KRİTİK
1. Rehber 8.6 kapı gösterimi REPLAY'de çalışmıyor (düzeltilmiş C5 metni için golden yok → kontrol edilemedi). Rehber metniyle birebir golden.
2. `kampanya_esik_7` story'ye göre doğru davranış; tek "kaçan" bu (→ K9).
3. Demoda AI hiç yanılmıyor; %100 fazla iddialı (elle golden; tekrar case'ler; indirim karşılaştırılmıyor; n görünmüyor). AI'ın sınır hatası yaptığı golden; "kısmen"; "n = …, REPLAY/elle golden".

ÖNEMLİ
4. T1 parasal kuralı kontrol etmiyor (→ V9 ara_toplam/toplam).
5. PO ifade dilini onaylıyor, iş kuralını değil: satır başına düz Türkçe, sınır örnekleri ızgarası, AI taslağı sınır yorumlarını PO sorusu olarak işaretlesin.
6. Kaçan hata bulgusu uygulanabilir değil: kural bağlantısı, ayırt edici girdi, "Bu girdiyle ek case türet", case isteği.
7. Türetilmiş case'te tutarsız metin (14 adette "ara toplam 175,00 TL").
8. V2 kapıyı delinebilir yapıyor (→ K10).
9. Analist PO'nun onayladığı oracle'ı tek başına aşıyor; "tablo yanlış" yolu yok (→ V10).
10. Ekran görüntüleri / örnek veri gerçek çekirdekle aynı hikâyeyi anlatmıyor.
11. Demo dokümanları (DEMO-VERISI, DEMO-AKISI, CANLI-DEMO-SENARYOSU) 012'yi bilmiyor.
12. Kapsam oranı yanlış okunur: "tablosu olan story: n / m"; kredi limiti için T3 önerisi.
13. Yakalama oranı mutation score gibi okunur: kural × hata dağılımı.
14. Ekilmiş hata koşusu yalnız yeşil suite'te anlamlı; dışarıda kalan testler görünmeli.

KÜÇÜK
15. Bağımsızlık sınırı: "Tablo koddan değil, PO'nun onayladığı metinden çıkar."
16. Minimum sipariş 500 → 750 geçmişi anlatılmalı.
17. 12/13/14 ara değerleri örneklerde olsun.
18. Karşılaştırılamayan değerler gri satır olarak listelensin.
19. Triage sinyal metni uzun → tek satır başlık.
20. Mock'ta golden'da olmayan elle "I2" ilişkisi.

## Güvenlik (`guvenlik`) — KRİTİK yok

ÖNEMLİ
1. Düzeltmede risk düşürülünce kapı engellemiyor (kapi.py:87).
2. AC referansı değiştirilerek kapıdan çıkılıyor (kapi.py:88).
3. Yüksek riskte `kontrol_edilemedi` geçiriyor; model atlayarak/injection ile oraya götürülebilir; prompt "tekrarlama" talimatı.
4. Kapı sıraya bağlı; sonradan onaylanan tablo onaylı case'i yeniden kapılamıyor; kapıda tablo kilidi yok.
5. Onaylı ilişki bağlı tablonun sürümüne bağlı değil.

KÜÇÜK
6. İstisna kaydı değişken kolonlarda; sayaç eksik sayıyor.
7. İstisna gerekçesi yalnız uzunluk.
8. Aynı kişi tablo yazıp onaylayabilir (kararlara uygun; `oz_onay` audit).
9. Çok büyük tolerans.
10. Oracle kontrolünde hız/maliyet sınırı yok.
11. Yeni AI taslağı analistin düzenlediği taslakları geçersiz kılıyor.
12. Ham iş hata metni tüm rollere görünüyor.
13. `evaluate` gövdesi sınırsız.

## Test mühendisi (`test`)

KRİTİK
K1. Risk düşürülerek kapı aşılıyor.
K2. Triage kayıtlı istisnayı yok sayıyor.

ÖNEMLİ
Ö1. Oracle/KPI sayıları döngüsel (golden'lar, eval seti, beklenen sonuçlar aynı test kodundan).
Ö2. Hata koşusu testleri gerçek sınıflandırıcıyı atlıyor (önceden etiketli rapor).
Ö3. "8/9" matrisi gönderilen kod yolundan üretilmedi; Java/web asimetrisi.
Ö4. "Yakalandı" hataya bağlı değil; temel %100 yeşil şartı gerçek hatayı yakalayan testle çelişiyor.
Ö5. Oracle → triage zinciri tek boru hattı olarak test edilmiyor.
Ö6. Metamorfik test yanlış beklentiyi kilitliyor.
Ö7. Kurtarmayla failed olan koşu done'a yeniden yazılabilir.
Ö8. Kule ölçüsü son done koşuyu içeriğine bakmadan alıyor.

KÜÇÜK
S1. Portal saklı istisnada onayı açık gösteriyor, core yine gerekçe istiyor.
S2. Eşzamanlı iki hata koşusu testi yok.
S3. İptal yalnız adımlar arasında test ediliyor.
S4. Temel/kapanış `record_check: false` göndermiyor.
S5. `istisna` sayımı farklı tabanları karıştırıyor.
S6. Eşzamanlı oracle işlerinde son yazan kazanır.
S7. Portal zamanlama testleri gerçek zamanlayıcı.
S8. `kampanya_esik_7` story'nin gerektirdiği davranış.
S9. Sabit demo-app satırlarının içerik regresyon testi yok.

## Doğrulama bağımsızlığı (`bagimsizlik`)

KRİTİK
K1. Kapı `kontrol_edilemedi` ile açık kalıyor (düzeltilmiş içerik REPLAY'i kaçırır).
K2. Düzeltmede risk / AC ref değişimiyle kapı aşılıyor.
K3. Kısmi değerlendirme `uyumlu` raporlanıyor (→ K11 `kismen`).
K4. Alıntı denetimi anlamı kanıtlamıyor; mantıksal kutup alıntıyı kırparak yeniliyor; olumsuzluk sezgiseli hatalı.
K5. F3 oranı el yazısı testlerin payını AI'a veriyor (→ K12).

ÖNEMLİ
O1. Değer çıkarıcı kuralı tablo adı/açıklamasından görüyor; tamlık denetimi yok.
O2. Tek bağımsızlık insan incelemesi; UI söylemiyor.
O3. Demo yalnız başarılı olabilir (elle golden; metrik `uretim_modu`'na bakmıyor).
O4. F1 ve F3 çelişen oracle'lar.
O5. "yakalandı" = herhangi bir assertion kırmızısı (flaky, sayfa çökmesi, kapanış kırmızısı).
O6. Triage beklenen değeri tüm kolonlarda eşliyor; adım eşlemesi yok.
O7. `beklenti` bug taslağını hep bastırıyor; "tablo da yanlış olabilir".
O8. Metamorfik türetme doğrulanmamış/yanlış değerleri yayıyor.
O9. Çıkarma promptu golden'larla çelişiyor.

KÜÇÜK
S1. `kapsam_orani` kontrol edilemeyeni kapsanmış sayıyor.
S2. Doğruluk case bazında; tekrar case'ler şişiriyor.
S3. Çakışan / erişilemeyen satır denetimi yok.
S4. Triage ayrıştırıcısı çoğu gerçek assertion'ı kaçırıyor.
S5. Onaylı-ama-uyumsuz case'ler işaretsiz codegen'e gidiyor.
S6. `gecersiz` hatalar paydadan düşüyor; kapsam gösterilmiyor.

## Arka uç mimarı (`mimari`)

KRİTİK
1. `feat/case-gen-v3` ile migrasyon numarası çakışması (v3: 0021–0028) → birleşmede 0029/0028.
2. `review_nesne_turu_ck` üzerine yazılıyor (v3 `design_model`) → birleşim listesi.
3. v3 case içeriğinde kapı çalışmıyor (`priority`, `test_data`, `verification_point`, `teardown`) → V11/V12.
4. Tekillik anahtarı başarısız işte onayı kalıcı 409'a kilitleyebilir.

ÖNEMLİ
5. Düzeltilmiş içerik otomatik denetlenmiyor.
6. `published` case'ler yeniden denetlenmiyor.
7. Oracle kancası yalnız `run_generation`'da (v3 deepen, submit_drafts).
8. GET uçları yazıyor; kimlik haritası bayat (başarılı koşu failed olabilir).
9. Hata koşusu uzun şeridi saatlerce tutuyor, devam yok.
10. İptal semantiği iki eşzamanlı koşuya izin veriyor.
11. Metamorfik türetme bayat/uyumsuz olgular kullanıyor.
12. Kontrol Kulesi O(tüm AI case) + N+1.
13. Metrik tanımları yanıltıcı (paydalar, istisna, hata_yakalama kapsamı).
14. Model maliyeti ve çift çağrılar.
15. Katmanlama/döngü/yinelenen geçerlilik mantığı; `HataKosusuSuruyor` yeri.
16. Gereksinim durumları ve model girdileri v3'ten ayrışıyor.

KÜÇÜK
17. Şema boşlukları (approved ⇒ hash'ler; `olusturma` sürüm damgası olarak).
18. "Asla silinmez" doğru değil (CASCADE, yerinde UPDATE).
19. Kapı 409 yolunda ikinci DB bağlantısı; toplu onayda `kod`.
20. Tablo onayı ile kapı arasında yarış; sonradan uyumsuz onaylı case için sinyal yok.
21. `GecersizIstek` ve `IliskiBulunamadi` kodsuz.
22. Olay/iş yükleri küçük; saklama yok (kabul).

### `feat/case-gen-v3` birleştirme kontrol listesi
1. Migrasyon 0029 (down 0028), `review_nesne_turu_ck` birleşimi, downgrade, `test_alembic_tek_bas`.
2. `cases/service.py` kancaları (store_cases / case.generated, decide + toplu onay, serialize_cases, requirement_metrics), `cases/api.py`.
3. `states.py` / `enums.py` / `models/__init__.py` birleşimleri.
4. `ONAYLI_GEREKSINIM` += modeling, model_ready; taslak girdisine açık soru yanıtları.
5. risk → priority; alan grameri; golden'ları v3 TPD-1'e göre yeniden kaydet.
6. `assistant/tools/probe.py`; asistan kural testleri.
7. Kule KPI yinelenmesi (`case_kalitesi.py`).
8. Tam paket.
