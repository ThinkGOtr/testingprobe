"""Bağımsız beklenen sonuç kontrolü (012 test kalite doğrulama, ANALIZ §4.3) ve onay kapısı.

AI'ın ürettiği case'lerin beklenen değerleri PO onaylı karar tablolarıyla karşılaştırılır:

1. `tablolar.gecerli_tablolar`: case'in AC atıflarıyla kesişen onaylı, bayat olmayan tablolar
   (yoksa `kapsam_disi`).
2. `cikarma`: model (`case_facts`) case'ten olguları alıntısıyla çıkarır; tabloların yalnız
   kolon tanımlarını görür.
3. `dogrulama`: olgular deterministik doğrulanır (alıntı birebir, değer alıntıyla aynı), tablo
   `ifade.degerlendir` ile hesaplanır ve beklenen değerler `esit_mi` ile karşılaştırılır.
4. `service`: sonuç `case_oracle_kontrol`'e `(test_case_id, icerik_hash)` anahtarıyla yazılır;
   kayıt yalnız `tablo_hashleri` güncel kapsayan tablolarla aynıyken geçerlidir.
5. `kapi.onay_denetimi`: `cases.service.decide` (approve/edit) onay kapısı (§4.3 tablosu).
6. `metrik.beklenti_dogrulugu`: §4.7 metriği.

Kontrol sonucu case içeriğini asla değiştirmez (bağımsızlık kuralı 3).
"""
