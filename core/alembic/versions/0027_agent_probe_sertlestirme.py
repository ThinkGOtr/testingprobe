"""Agent Probe / asistan içerik kontrolü sertleştirmesi (specs/011 D4 düzeltmeleri).

- **Yetkiler (güvenlik #14):** `asistan_denetim` ve `ajan_testi_talebi` kayıt niteliğindedir.
  0025 `tp_app`'e dört DML yetkisini de vermişti; kodun gerçekten kullandığına daraltılır:
  `asistan_denetim` → SELECT, INSERT (satır yazılır, değiştirilmez/silinmez);
  `ajan_testi_talebi` → SELECT, INSERT, UPDATE (durum/sonuç/işlenme yazılır; silinmez).
  Asistan mesajı (saklama temizliği) ya da gereksinim silinince satırlar `ON DELETE CASCADE` ile
  gider: PostgreSQL referans eylemleri tablo sahibinin yetkisiyle çalıştığından `tp_app`'in
  DELETE yetkisi gerekmez. `ajan_urunu_baglantisi` (kaldırılabilir bağlantı) tam DML kalır.
- **Talep numarası (güvenlik #9):** simülatörün `APT-<yıl>-<n>` numarası `MAX+1` ile kilitsiz
  hesaplanıyordu (eşzamanlı iki talep aynı numarayı alabilir). `ajan_testi_talebi_no_seq`
  dizisinden alınır (`nextval` işlemden bağımsız ve yarışsızdır); dizi mevcut en büyük numaradan
  sonra başlar. `tp_app`: USAGE, SELECT.
- **Süreç değeri `simule` (güvenlik #5):** simülasyon talebinin `passed` sonucu gereksinimi
  `done`'a taşımaz (yalnız gösterilir); işlenmiş talebin `surec`'i `simule` olur.

Downgrade: yetkiler 0025'teki hâline (dört DML) döner, dizi düşürülür; `surec='simule'` satırları
`onay_gecersiz` yapılır (0025 kısıtına sığan en yakın anlam: "geçti ama gereksinim
ilerletilmedi"), sonra kısıt geri daraltılır.

Not (0025 downgrade'i, güvenlik #14): 0025'in downgrade'i `asistan_mesaj.kaynak='denetim'`
satırlarını silmez, `kapali` olarak yeniden yazar — kısıt `denetim` değerini kaldırmadan önce
daraltılamaz. Bu bilinçli bir veri dönüşümüdür: o mesajların cevap metni zaten içerik kontrolünün
açıklamasıdır (engel / kontrol çalışmıyor), asistan modelinin cevabı değildir; `kapali` (model
hazır değil sabit cevabı) en yakın anlamdır. Geri alma sonrası bu mesajlar engel kaydı olarak
ayırt edilemez; denetim zinciri (`asistan.denetim`, `asistan.denetim_calismiyor`) kaydı korur.

Birleştirmede zincir sahibi tarafından düzeltilir (D1 0026 kullanır); bu dalda
`down_revision = "0025"`.

Revision ID: 0027
Revises: 0025
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIZI = "ajan_testi_talebi_no_seq"
_SUREC_ESKI = "surec IS NULL OR surec IN ('bulgu', 'hata', 'onay_gecersiz', 'tamamlandi')"
_SUREC_YENI = "surec IS NULL OR surec IN ('bulgu', 'hata', 'onay_gecersiz', 'simule', 'tamamlandi')"


def upgrade() -> None:
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON asistan_denetim FROM tp_app")
    op.execute("GRANT SELECT, INSERT ON asistan_denetim TO tp_app")
    op.execute("REVOKE DELETE, TRUNCATE ON ajan_testi_talebi FROM tp_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON ajan_testi_talebi TO tp_app")

    op.execute(f"CREATE SEQUENCE {DIZI} AS bigint START WITH 1 MINVALUE 1")
    op.execute(
        f"SELECT setval('{DIZI}', COALESCE((SELECT MAX(CAST(split_part(talep_no, '-', 3) AS "
        "bigint)) FROM ajan_testi_talebi WHERE talep_no ~ '^APT-[0-9]+-[0-9]+$'), 0) + 1, false)"
    )
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {DIZI} TO tp_app")

    op.drop_constraint("ajan_testi_talebi_surec_ck", "ajan_testi_talebi", type_="check")
    op.create_check_constraint("ajan_testi_talebi_surec_ck", "ajan_testi_talebi", _SUREC_YENI)


def downgrade() -> None:
    op.execute("UPDATE ajan_testi_talebi SET surec = 'onay_gecersiz' WHERE surec = 'simule'")
    op.drop_constraint("ajan_testi_talebi_surec_ck", "ajan_testi_talebi", type_="check")
    op.create_check_constraint("ajan_testi_talebi_surec_ck", "ajan_testi_talebi", _SUREC_ESKI)
    op.execute(f"DROP SEQUENCE IF EXISTS {DIZI}")
    for tablo in ("ajan_testi_talebi", "asistan_denetim"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tablo} TO tp_app")
