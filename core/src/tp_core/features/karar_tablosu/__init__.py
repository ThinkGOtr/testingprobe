"""Karar tablosu (012 test kalite doğrulama; specs/012-test-kalite-dogrulama/ANALIZ.md §4.1–§4.2).

Karar tablosu, bir hesaplama kuralının PO onaylı girdi → çıktı tanımıdır; case'in beklenen
değerleri onaydan önce bu tabloyla karşılaştırılır (bağımsız beklenen sonuç kontrolü).

Ortak modüller (Ş0; diğer şeritler bunları kullanır, yeniden yazmaz):

    from tp_core.features.karar_tablosu import ifade
    ifade.dogrula(icerik)                  # şema + ifadeler; Türkçe hata metinleri
    ifade.degerlendir(icerik, girdiler)    # ilk koşulu sağlayan satır → Degerlendirme
    ifade.sayi_ayristir("1.250,00 TL")     # Decimal("1250.00")
    ifade.sayi_bicimle(Decimal(300), "150,00 TL")   # "300,00 TL"
    ifade.esit_mi(a, b, tolerans)

    from tp_core.features.karar_tablosu.hatalar import OracleUyumsuz, KararTablosuGecersiz, …

`ifade` saf ve yan etkisizdir (`eval` yok; kendi ayrıştırıcısı). `hatalar` 012'nin API hata
kodlarını taşır (`rules/assistant/hata-sozlugu.yaml` ile eşit).

Ş1 (tablo ve ilişki servisi):

- `service`: elle tablo/ilişki, içerik güncelleme (yalnız `draft`; görülen `icerik_hash`),
  gönder / geri çek / yeniden aç (analist), onay / değişiklik isteği (PO), "örnekle dene",
  liste (`bayat` hesaplanır), AI taslağı (`karar_tablosu.draft`, amaç `decision_table_draft`).
  Diğer şeritlerin okuma yardımcıları:

      service.gecerli_tablolar(session, requirement_id, ac_refs=None)  # onaylı, bayat değil
      service.gecerli_iliskiler(session, requirement_id)
      service.bayat_mi(nesne, requirement)

  Tablo onaylanınca / onaylı tablo yeniden açılınca `oracle.check_requirement` işi kuyruğa girer
  (işleyici oracle şeridindedir).
- `api`: uçlar (modül belgesindeki tablo); `jobs`: `karar_tablosu.draft` işleyicisi.
"""
