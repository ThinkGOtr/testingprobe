"""Güncel case seti ve birleşik üretim özeti — tek tanım (specs/011 §4.2, §4.3).

Önceden üç ayrı birleştirme vardı (`service._coverage_state`, `review._birlesik_ozet`,
`deepen.merged_summary`/`overlay`) ve "güncel set" iki ayrı yerde tanımlıydı. Hepsi buradaki
fonksiyonları kullanır:

- `current_cases(session, req, include_legacy=...)`: superseded/ret olmayan, gereksinimin GÜNCEL
  PO onaylı içeriği için üretilmiş case'ler (üretim + sıra no sırasıyla). Review/denetim seti
  (`set_hash`) eski (v2) case'leri dışarıda bırakır (`include_legacy=False`, K9); kapsam matrisi ve
  derinleştirme hepsini kullanır.
- `merge(ozetler)` / `overlay(birlesik, yeni)`: kimlikli kayıtlar (kapsam öğesi, soru, varsayım,
  negatif karar, kapsanmayan, test edilebilirlik açığı) için SONRAKİ üretimin kaydı geçerlidir
  (ilk görüldüğü konumda değiştirilir); kimliksiz listeler (gözlemler, otomasyon açık noktaları,
  yapılandırma matrisi) tekrarsız birleşir. Sonuç her zaman `normalize_ozet` biçimindedir.
- `merged_summary(session, req, cases)`: verilen case'lerin üretimlerinin özetleri (özeti olan,
  üretim no sırasıyla) birleşik.
- `audit_summary(...)`: bir case'in tutarlılık kurallarına karşı denetlendiği özet. Derinleştirme
  (`tur ∈ {negatif, teknik}`) case'i mevcut sete EKTİR ve mevcut Q/A/kapsam öğelerine atıf
  yapabilir: özeti = overlay(kendisinden önceki üretimlerin birleşik özeti, kendi özeti).
  Diğer üretimlerde kendi özeti. Özeti olmayan üretim (IDE özetsiz) None (kimlik denetimi yok).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.features.cases.schema import OZET_ALANLARI, is_legacy, normalize_ozet
from tp_core.models import CaseUretim, Requirement, TestCase

# Kimlikli özet listeleri: alan → kimlik anahtarı.
ANAHTAR = {
    "coverage_items": "id",
    "open_questions": "id",
    "assumptions": "id",
    "negative_coverage": "item",
    "not_covered": "item",
    "testability_gaps": "control",
}
# Mevcut sete EK case üreten üretim türleri (011 F4, K7).
EK_TURLER = frozenset({"negatif", "teknik"})
GECERSIZ_DURUMLAR = ("superseded", "rejected")


def current_cases(
    session: Session, req: Requirement, *, include_legacy: bool = True
) -> list[TestCase]:
    """Gereksinimin güncel case'leri (üretim + sıra no sırasıyla)."""
    from tp_core.features.cases.service import old_content_case_ids

    eski = old_content_case_ids(session, req)
    return [
        tc
        for tc in session.scalars(
            select(TestCase)
            .where(
                TestCase.requirement_id == req.id,
                TestCase.durum.notin_(GECERSIZ_DURUMLAR),
            )
            .order_by(TestCase.uretim_no, TestCase.sira_no)
        ).all()
        if tc.id not in eski and (include_legacy or not is_legacy(tc.icerik))
    ]


def _kimlik(alan: str, kayit: Any) -> str | None:
    k = ANAHTAR.get(alan)
    if k is None or not isinstance(kayit, Mapping) or kayit.get(k) is None:
        return None
    if alan == "not_covered" and kayit.get("question_ref"):
        # Aynı öğe (ör. AC3) iki ayrı açık soru yüzünden kapsanmamış olabilir: kayıtlar soruyla
        # ayrışır, biri diğerini ezmez (011 K16; açık soru bağı).
        return f"{kayit.get(k)}#{kayit.get('question_ref')}"
    return str(kayit.get(k))


def overlay(birlesik: Mapping[str, Any] | None, yeni: Mapping[str, Any] | None) -> dict[str, Any]:
    """Birleşik özete yeni üretimin özeti (aynı kimlikte yeni geçerli; saf)."""
    out = normalize_ozet(birlesik)
    ek = normalize_ozet(yeni)
    for alan in OZET_ALANLARI:
        if alan == "config_matrix":
            for k in ("parameters", "constraints"):
                for x in ek[alan][k]:
                    if x not in out[alan][k]:
                        out[alan][k].append(x)
            continue
        liste = out[alan]
        konum = {kim: i for i, x in enumerate(liste) if (kim := _kimlik(alan, x)) is not None}
        for x in ek[alan]:
            kim = _kimlik(alan, x)
            if kim is not None and kim in konum:
                liste[konum[kim]] = x
            elif kim is not None:
                konum[kim] = len(liste)
                liste.append(x)
            elif x not in liste:
                liste.append(x)
    return out


def merge(ozetler: Iterable[Mapping[str, Any] | None]) -> dict[str, Any]:
    """Özetler sırayla birleşik (sonraki geçerli)."""
    out = normalize_ozet(None)
    for o in ozetler:
        out = overlay(out, o)
    return out


def summary_rows(session: Session, req: Requirement) -> dict[int, CaseUretim]:
    """Gereksinimin üretim satırları: üretim no → satır."""
    return {
        u.uretim_no: u
        for u in session.scalars(select(CaseUretim).where(CaseUretim.requirement_id == req.id))
    }


def _ozet(satir: CaseUretim | None) -> dict[str, Any] | None:
    return dict(satir.ozet) if satir is not None and satir.ozet else None


def merged_summary(
    session: Session,
    req: Requirement,
    cases: Sequence[TestCase],
    *,
    satirlar: Mapping[int, CaseUretim] | None = None,
) -> dict[str, Any]:
    """`cases`'in üretimlerinin özetleri birleşik (özeti olan üretimler, üretim no sırasıyla)."""
    satirlar = summary_rows(session, req) if satirlar is None else satirlar
    uretimler = sorted({tc.uretim_no for tc in cases})
    return merge(_ozet(satirlar.get(n)) for n in uretimler)


def definition_conflicts(ozetler: Sequence[tuple[int, Mapping[str, Any]]]) -> list[str]:
    """Aynı kapsam öğesi ya da açık soru kimliği farklı üretimlerde farklı tanımlıysa uyarı
    satırları."""
    tanim: dict[str, Any] = {}
    out: list[str] = []
    for uretim_no, ozet in ozetler:
        for o in ozet.get("coverage_items") or []:
            if not isinstance(o, Mapping):
                continue
            kim = str(o.get("id"))
            if kim in tanim and tanim[kim] != o.get("definition"):
                out.append(
                    f"Kapsam öğesi {kim} farklı üretimlerde farklı tanımlı; matris son "
                    f"üretimin (#{uretim_no}) tanımını gösterir."
                )
            tanim[kim] = o.get("definition")
    # Tur 3 #12: farklı üretimlerin `Q1`'leri kimlikle birleşir (sonraki geçerli). Case atfı ve
    # yetim soru hesabı kimlikle eşleştiği için metni farklı aynı kimlik yanlış eşleşebilir:
    # görünür uyarı (açık soru listesi `acik_sorular.current_items` metinle eşleştirir).
    soru: dict[str, str] = {}
    for uretim_no, ozet in ozetler:
        for q in ozet.get("open_questions") or []:
            if not isinstance(q, Mapping):
                continue
            kim, metin = str(q.get("id")), " ".join(str(q.get("question") or "").split())
            if kim in soru and soru[kim] != metin:
                out.append(
                    f"Açık soru {kim} farklı üretimlerde farklı soru; birleşik özet son üretimin "
                    f"(#{uretim_no}) sorusunu gösterir, yetim soru hesabı kimlikle eşleşir."
                )
            soru[kim] = metin
    return out


class AuditSummaries:
    """Bir gereksinimin case'leri için denetim özeti önbelleği (`audit_summary`, N sorgu yok)."""

    def __init__(self, session: Session, req: Requirement) -> None:
        self.session = session
        self.req = req
        self.satirlar = summary_rows(session, req)
        self._guncel: list[TestCase] | None = None
        self._taban: dict[int, dict[str, Any]] = {}

    def _oncekiler(self, uretim_no: int) -> dict[str, Any]:
        if uretim_no not in self._taban:
            if self._guncel is None:
                self._guncel = current_cases(self.session, self.req)
            self._taban[uretim_no] = merged_summary(
                self.session,
                self.req,
                [tc for tc in self._guncel if tc.uretim_no < uretim_no],
                satirlar=self.satirlar,
            )
        return self._taban[uretim_no]

    def of(self, uretim_no: int) -> dict[str, Any] | None:
        satir = self.satirlar.get(uretim_no)
        kendi = _ozet(satir)
        if kendi is None:
            return None
        if satir is not None and satir.tur in EK_TURLER:
            return overlay(self._oncekiler(uretim_no), kendi)
        return kendi


def audit_summary(session: Session, tc: TestCase) -> dict[str, Any] | None:
    """Case'in tutarlılık kurallarına karşı denetlendiği özet (modül belgesi)."""
    req = session.get(Requirement, tc.requirement_id)
    if req is None:
        return None
    return AuditSummaries(session, req).of(tc.uretim_no)
