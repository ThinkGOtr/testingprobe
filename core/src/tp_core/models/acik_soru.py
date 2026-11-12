"""Açık soru / varsayım döngüsü (specs/011 K16, migrasyon 0028; D6 şeridi).

`acik_soru`: case üretiminin birleşik özetindeki bir açık sorunun (`open_questions`) ya da doğrulama
bekleyen varsayımın (`assumptions`) PO'ya gönderim ve yanıt kaydı. Satır yalnız gönderimle oluşur;
özette olup satırı olmayan soru "gönderilmedi"dir.

- Kimlik: soru metninin normalize hash'i (`metin_hash`) gereksinim, tür ve PO onaylı içerik
  (`gereksinim_hash`) başına tekildir — aynı soru (farklı üretimde farklı `Qn` kimliğiyle gelse
  de) aynı içerik için iki kez gönderilmez.
- `etiket` (`CQn` soru, `CAn` varsayım): PO'nun yanıtta kullandığı kimlik. Ön inceleme sorularının
  `Qn` kimlikleriyle çakışmasın diye ayrı önek; gereksinim başına artan numara.
- `durum`: `bekliyor` (satır yazıldı, Jira yorumu henüz doğrulanmadı) → `gonderildi` →
  `yanitlandi` (PO yorumu soruya bağlandı). Yanıt metni Jira'dan gelen güvenilmeyen içeriktir.
- `gereksinim_hash`: gönderim anındaki PO onaylı içerik hash'i; kayıt (durum, yanıt) yalnız bu
  içerik için geçerlidir (story değişip yeniden onaylanırsa soru yeniden gönderilebilir, eski
  yanıt kaynak sayılmaz).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models.base import Base, guncelleme_col, in_check, olusturma_col, uuid_pk

ACIK_SORU_TUR = frozenset({"soru", "varsayim"})
ACIK_SORU_DURUM = frozenset({"bekliyor", "gonderildi", "yanitlandi"})


class AcikSoru(Base):
    __tablename__ = "acik_soru"
    __table_args__ = (
        in_check("tur", ACIK_SORU_TUR, "acik_soru_tur_ck"),
        in_check("durum", ACIK_SORU_DURUM, "acik_soru_durum_ck"),
        UniqueConstraint(
            "requirement_id", "tur", "metin_hash", "gereksinim_hash", name="acik_soru_metin_uq"
        ),
        UniqueConstraint("requirement_id", "etiket", name="acik_soru_etiket_uq"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE")
    )
    tur: Mapped[str]
    etiket: Mapped[str]
    # Gönderim anında birleşik özetteki kimlik (Q1/A1) — bilgi amaçlı; eşleme metin hash'iyle.
    kaynak_id: Mapped[str]
    metin: Mapped[str]
    metin_hash: Mapped[str]
    sahip: Mapped[str] = mapped_column(server_default="", default="")
    durum: Mapped[str] = mapped_column(server_default="bekliyor", default="bekliyor")
    gereksinim_hash: Mapped[str]
    gonderen: Mapped[str]
    gonderim_zamani: Mapped[datetime | None]
    jira_comment_id: Mapped[str | None]
    yanit: Mapped[str | None]
    yanit_yazari: Mapped[str | None]
    yanit_zamani: Mapped[datetime | None]
    yanit_yorum_id: Mapped[str | None]
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()
