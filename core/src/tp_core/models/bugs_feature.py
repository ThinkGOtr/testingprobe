"""Bug taslağı şeridinin (Faz 4, TEKNIK-TASARIM §8.12) ek tablosu — migrasyon 0012.

Platform tablosu `bug_draft` olduğu gibi kullanılır (içerik, onaylı hash, karar, Jira anahtarı).
`bug_draft.icerik` onaya konu içeriktir ve hash'e girer; bu yüzden hazırlık ayrıntıları (hata
imzası, Jira araması, mükerrer sıralamasının modu, deterministik düzeltmeler, yayın sonucu) içerik
dışında, ayrı `bug_draft_ek` satırında tutulur (taslakla 1:1):

- `kaynak`: `failure` (triage → gerçek defect) | `finding` (tutarlılık bulgusu `code_defect`).
- `imza`: hata imzası (test adı, hata türü, sayfa/AC, anahtar terimler, beklenen/gerçekleşen).
- `jql` / `arama`: mükerrer araması için çalıştırılan güvenli JQL ve sonucu
  (`durum = yapildi|hata|atlandi`, `aday_sayisi`, `hata`).
- `dup_*` / `oneri`: AI sıralamasının çağrısı, modu (REPLAY rozeti) ve önerisi (`new|link`).
- `hazirlik_*`: `bugs.prepare` işinin durumu (portal "hazırlanıyor" göstergesi).
- `ai_icerik` / `duzeltmeler`: modelin ham taslağı ve üstüne uygulanan deterministik düzeltmeler
  (gerçekleşen değer literal, kanıt bağlantıları yalnızca koşudan, story/test anahtarları).
- `duzenleyen`: içeriği elle düzenleyen testçi (sonraki hazırlık içeriği ezmez).
- `ilgili_failure_ids`: aynı hata imzasıyla sonradan gelen başarısızlıklar (yeni taslak açılmaz).
- `yayin`: Jira'da açılan/bağlanan kayıt, bağlantılar, yorum kimliği, son hata.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models.base import Base, guncelleme_col, in_check, olusturma_col
from tp_core.models.requirements import EMPTY_LIST, EMPTY_OBJ

BUG_KAYNAK = frozenset({"failure", "finding"})
HAZIRLIK_DURUM = frozenset({"kuyrukta", "hazirlaniyor", "hazir", "basarisiz"})
URETIM = frozenset({"ai", "sablon"})


class BugDraftEk(Base):
    """Bug taslağının içerik dışı hazırlık/yayın ayrıntıları (bug_draft ile 1:1)."""

    __tablename__ = "bug_draft_ek"
    __table_args__ = (
        in_check("kaynak", BUG_KAYNAK, "bug_draft_ek_kaynak_ck"),
        in_check("hazirlik_durum", HAZIRLIK_DURUM, "bug_draft_ek_hazirlik_ck"),
        in_check("uretim", URETIM, "bug_draft_ek_uretim_ck", True),
    )

    bug_draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bug_draft.id", ondelete="CASCADE"), primary_key=True
    )
    kaynak: Mapped[str]
    imza: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJ, default=dict)
    jql: Mapped[str | None]
    arama: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJ, default=dict)
    dup_ai_call_id: Mapped[uuid.UUID | None]
    dup_uretim_modu: Mapped[str | None]
    oneri: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJ, default=dict)
    hazirlik_durum: Mapped[str] = mapped_column(server_default="kuyrukta", default="kuyrukta")
    hazirlik_no: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    hazirlik_hatasi: Mapped[str | None]
    job_id: Mapped[uuid.UUID | None]
    uretim: Mapped[str | None]
    ai_icerik: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # İçeriği elle düzenleyen testçi: hazırlık işi bundan sonra içeriği ezmez (adaylar güncellenir).
    duzenleyen: Mapped[str | None]
    duzeltmeler: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    ilgili_failure_ids: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=EMPTY_LIST, default=list
    )
    yayin: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJ, default=dict)
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()
