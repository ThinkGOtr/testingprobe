"""Gereksinim, ön inceleme, tutarlılık bulguları, test case'ler ve insan kararları (review)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    UniqueConstraint,
    event,
    false,
    inspect,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, UOWTransaction, mapped_column

from tp_core.models import enums
from tp_core.models.base import NOW, Base, guncelleme_col, in_check, olusturma_col, uuid_pk
from tp_core.workflow.states import CONTENT_FIELDS, MACHINES

EMPTY_LIST = text("'[]'::jsonb")
EMPTY_OBJ = text("'{}'::jsonb")


def _durum(entity: str) -> Mapped[str]:
    m = MACHINES[entity]
    return mapped_column(default=m.initial, server_default=m.initial)


class Requirement(Base):
    """Jira story'si veya serbest metin gereksinim (TEKNIK-TASARIM §7, §8.2, §8.2a)."""

    __tablename__ = "requirement"
    __table_args__ = (
        in_check("kaynak", enums.REQUIREMENT_KAYNAK, "requirement_kaynak_ck"),
        in_check("durum", enums.durumlar("requirement"), "requirement_durum_ck"),
        in_check("po_onay_kaynagi", enums.PO_ONAY_KAYNAGI, "requirement_po_kaynak_ck", True),
        CheckConstraint("kaynak <> 'jira' OR jira_key IS NOT NULL", name="requirement_jira_key_ck"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kaynak: Mapped[str]
    jira_key: Mapped[str | None] = mapped_column(unique=True)
    baslik: Mapped[str]
    aciklama: Mapped[str] = mapped_column(server_default="", default="")
    kabul_kriterleri: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=EMPTY_LIST, default=list
    )
    kaynak_hash: Mapped[str]
    ac_missing: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    durum: Mapped[str] = _durum("requirement")
    cekim_zamani: Mapped[datetime | None]
    olusturan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    kontrol_turu: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    po_onaylayan: Mapped[str | None]
    po_onay_zamani: Mapped[datetime | None]
    po_onay_kaynagi: Mapped[str | None]
    po_cevaplari: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    # PO onayıyla (`po_approved`'a giriş) yazılan içerik hash'i; case üretimi bunu yeniden denetler.
    onaylanan_hash: Mapped[str | None]
    # Son üretim seçenekleri (011 K5; `features.cases.secenekler`); null = seçim yok.
    uretim_secenekleri: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Jira durum tetiği (013): son görülen Jira durumu ve tetikle otomatik akışa alındığı an.
    jira_durumu: Mapped[str | None]
    qa_tetik_zamani: Mapped[datetime | None]
    # İçerik alanlarının (baslik/aciklama/kabul_kriterleri) en son değiştiği an. ORM bunu içerik
    # değişince kendisi günceller; Jira'dan ilk çekimde senkron kodu Jira changelog'undaki açıklama
    # değişim zamanını verebilir. Jira kanalındaki PO onayı (etiket zamanı) bundan önceyse geçersiz.
    icerik_degisim: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=NOW,
        default=lambda: datetime.now(UTC),
    )
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


def _icerik_degisimini_isle(session: Session, _ctx: UOWTransaction, _instances: Any) -> None:
    """Gereksinimin içerik alanı değiştiyse `icerik_degisim = now` (açıkça verilmediyse)."""
    alanlar = CONTENT_FIELDS["requirement"]
    for obj in session.dirty:
        if not isinstance(obj, Requirement):
            continue
        st = inspect(obj)
        if st.attrs.icerik_degisim.history.has_changes():
            continue
        if any(st.attrs[a].history.has_changes() for a in alanlar):
            obj.icerik_degisim = datetime.now(UTC)


event.listen(Session, "before_flush", _icerik_degisimini_isle)


# Test case kimliği ad alanı (Constitution XI: deterministik uuid5). Değişmez: değişirse aynı
# case'in yayın idempotency'si (`tp-<uuid>` etiketi) kırılır.
NAMESPACE_TEST_CASE: Final = uuid.UUID("3c5e9a10-7d2b-5b84-a1f6-0e9d8c7b6a51")


def case_id(requirement: Requirement, sira_no: int, uretim_no: int) -> uuid.UUID:
    """`test_case.id = uuid5(jira_key + sira_no + uretim_no)` (TEKNIK-TASARIM §7).

    Serbest metin gereksinimde (jira_key yok) gereksinimin kendi kimliği kullanılır. Aynı girdiyle
    yeniden üretim (iş yeniden denemesi) aynı kimliği verir; ikinci ekleme PK/UNIQUE ile reddedilir.
    """
    if sira_no < 1 or uretim_no < 1:
        raise ValueError("sira_no ve uretim_no 1'den başlar")
    kaynak = f"jira:{requirement.jira_key}" if requirement.jira_key else f"req:{requirement.id}"
    return uuid.uuid5(NAMESPACE_TEST_CASE, f"{kaynak}:{sira_no}:{uretim_no}")


class RequirementReview(Base):
    """AI ön incelemesi: PO'ya sorular (§8.2a)."""

    __tablename__ = "requirement_review"
    __table_args__ = (
        in_check("verdict", enums.VERDICT, "requirement_review_verdict_ck"),
        in_check("durum", enums.durumlar("requirement_review"), "requirement_review_durum_ck"),
        in_check("uretim_modu", enums.URETIM_MODU, "requirement_review_mod_ck", True),
        Index("requirement_review_req_ix", "requirement_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE")
    )
    sorular: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    verdict: Mapped[str]
    jira_comment_id: Mapped[str | None]
    po_onay_kullanicisi: Mapped[str | None]
    po_onay_zamani: Mapped[datetime | None]
    durum: Mapped[str] = _durum("requirement_review")
    ai_call_id: Mapped[uuid.UUID | None]
    uretim_modu: Mapped[str | None]
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class ConsistencyFinding(Base):
    """Doküman ↔ kod/veri tutarlılık bulgusu (§8.2b); kanıt doğrulanmadan gösterilmez."""

    __tablename__ = "consistency_finding"
    __table_args__ = (
        in_check("tur", enums.FINDING_TUR, "consistency_finding_tur_ck"),
        in_check("severity", enums.SEVERITY, "consistency_finding_severity_ck"),
        in_check("analist_karari", enums.FINDING_KARAR, "consistency_finding_karar_ck", True),
        in_check("durum", enums.durumlar("consistency_finding"), "consistency_finding_durum_ck"),
        in_check("uretim_modu", enums.URETIM_MODU, "consistency_finding_mod_ck", True),
        Index("consistency_finding_req_ix", "requirement_id", "kontrol_turu"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE")
    )
    kontrol_turu: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    tur: Mapped[str]
    doc_ref: Mapped[str]
    kanitlar: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    kanit_dogrulandi: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    severity: Mapped[str]
    onerilen_metin: Mapped[str | None]
    analist_karari: Mapped[str | None]
    gerekce: Mapped[str | None]
    karar_veren_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    karar_zamani: Mapped[datetime | None]
    durum: Mapped[str] = _durum("consistency_finding")
    ai_call_id: Mapped[uuid.UUID | None]
    uretim_modu: Mapped[str | None]
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class TestCase(Base):
    """Şemalı test case (§7). `icerik` case şemasındaki JSON'dur; hash bunun üstündendir."""

    __tablename__ = "test_case"
    __test__ = False  # pytest bu sınıfı test sınıfı sanmasın
    __table_args__ = (
        in_check("kanal", enums.CASE_KANAL, "test_case_kanal_ck"),
        in_check("durum", enums.durumlar("test_case"), "test_case_durum_ck"),
        in_check("uretim_modu", enums.URETIM_MODU, "test_case_mod_ck", True),
        Index("test_case_req_ix", "requirement_id"),
        UniqueConstraint("requirement_id", "sira_no", "uretim_no", name="test_case_sira_uq"),
    )

    # Rastgele varsayılan YOK: kimlik `case_id(requirement, sira_no, uretim_no)` ile verilir.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE")
    )
    sira_no: Mapped[int] = mapped_column(Integer)
    uretim_no: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    kanal: Mapped[str] = mapped_column(server_default="portal", default="portal")
    surum: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    icerik: Mapped[dict[str, Any]] = mapped_column(JSONB)
    icerik_hash: Mapped[str]
    onaylanan_hash: Mapped[str | None]
    durum: Mapped[str] = _durum("test_case")
    ai_generated: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    ai_call_id: Mapped[uuid.UUID | None]
    uretim_modu: Mapped[str | None]
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class Review(Base):
    """İnsan kararı / onay kaydı: onayın doğruluk kaynağı (Constitution I).

    §7'deki `review` tablosunun genelleştirilmiş hali: `nesne_turu` + `nesne_id` ile test_case,
    requirement (PO teyidi), bug_draft, script (merge) ve consistency_finding kararlarını tutar.
    `onaylanan_hash` karar anındaki içerik hash'idir. Jira'daki PO etiketi gibi dış onaylar
    `harici_onaylayan` + `kanal='jira'` ile yazılır.
    """

    __tablename__ = "review"
    __table_args__ = (
        in_check("nesne_turu", enums.REVIEW_NESNE, "review_nesne_turu_ck"),
        in_check("karar", enums.REVIEW_KARAR, "review_karar_ck"),
        in_check("kanal", enums.REVIEW_KANAL, "review_kanal_ck"),
        in_check("ret_nedeni", enums.RET_NEDENI, "review_ret_nedeni_ck", True),
        CheckConstraint(
            "user_id IS NOT NULL OR harici_onaylayan IS NOT NULL", name="review_onaylayan_ck"
        ),
        CheckConstraint("karar <> 'reject' OR ret_nedeni IS NOT NULL", name="review_ret_ck"),
        Index("review_nesne_ix", "nesne_turu", "nesne_id", "sira"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    nesne_turu: Mapped[str]
    nesne_id: Mapped[uuid.UUID]
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    harici_onaylayan: Mapped[str | None]
    kanal: Mapped[str] = mapped_column(server_default="portal", default="portal")
    karar: Mapped[str]
    ret_nedeni: Mapped[str | None]
    gerekce: Mapped[str | None]
    once: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sonra: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    duzeltme_olculeri: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    onaylanan_hash: Mapped[str]
    # 012 öncesi analist `edit`'i (son onay); yalnız 0033 göçü işaretler (yeni kayıtlarda false).
    eski_onay: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    # Kesin sıra: aynı işlemdeki kararlar `zaman` ile ayrılamaz; son karar = en büyük `sira`.
    sira: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    zaman: Mapped[datetime] = olusturma_col()
