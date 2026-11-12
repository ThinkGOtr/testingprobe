"""İlişki tabanlı ek case türetme servisi (ANALIZ §4.5, §5 `metamorfik_turetme`, §6).

`turet` (analist, `POST /requirements/{id}/metamorphic-cases`):

1. Gereksinim kilitlenir (sıra no ayırma yarışını kapatır); case'leri kullanılabilir olmalı
   (`cases_ready | done`, PO onayı güncel) — değilse 409.
2. İlişki gereksinime ait, `approved` ve bayat olmamalı (`IliskiGecersiz`, 422). Bağlı karar tablosu
   (`karar_tablosu_id`) olmalı, `approved` ve bayat olmamalı ve ilişkinin onaylandığı sürümde
   olmalı (`karar_tablosu.service.iliski_tablo_engeli`); değilse `IliskiGecersiz`.
3. Kaynak case'ler: verilmezse gereksinimin `superseded` olmayan, AC atıfları ilişkinin
   `ac_refs`'iyle kesişen ve kendisi metamorfik türetme ürünü olmayan case'leri (zincirleme ×2 ×2
   varsayılan olmasın). Verilen `case_ids` gereksinime ait, `superseded` olmayan ve AC'si kesişen
   case'ler olmalı (değilse 404 / 422); türetilmiş bir case açıkça verilirse kaynak olabilir.
4. Her kaynak için: (ilişki, kaynak) çifti zaten `turetildi` ise atlanır (`zaten_turetildi`, satıra
   dokunulmaz). Değilse case'in GÜNCEL içeriğine ait **geçerli** kontrol kaydı aranır (oracle'ın
   tek geçerlilik tanımı: `oracle.service.gecerli_kayit` — güncel kapsayan tablo hash'leriyle
   yapılmış kayıt). Kayıt yoksa, sonucu `uyumlu` değilse ya da ilişkinin tablosuna ait uyumlu
   grubun girdi olgusu yoksa `olgu_yok`. Gruplar kayıttaki sırayla denenir; **türetebilen ilk
   grup** kullanılır (çift başına tek türetilen case). Hiçbiri türetemezse ilk grubun nedeni
   raporlanır. Türetilen içerik case içerik denetiminden
   (`content_errors`: şema + AC atıfları) geçmezse `iliski_gecersiz`.
5. Türetilen case `draft`, kaynağın `uretim_no`'su, o üretimdeki sıradaki boş `sira_no`, kimlik
   `case_id(req, sira_no, uretim_no)`; `kanal` ve `uretim_modu` kaynaktan, `ai_generated=False`
   (deterministik türetme; beklenti doğruluğu metriği yalnız AI çıktısını saymalıdır),
   `ai_call_id` boş. Gereksinimin güncel bir case'iyle aynı içerik hash'i çıkarsa yazılmaz
   (`iliski_gecersiz`, "aynı içerikte case var").
6. `metamorfik_turetme` satırı yazılır ya da (tekrar denemede) güncellenir. Her yeni case için
   `case.generated` olayı, toplu `metamorfik.derived` denetim kaydı ve yeni case varsa
   `oracle.check_requirement` işi (`neden: "metamorfik"`) aynı işlemdedir.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit, content_hash
from tp_core.events.bus import publish_tx
from tp_core.features.cases.schema import content_errors
from tp_core.features.cases.service import (
    CaseNotFound,
    RequirementChanged,
    get_requirement,
    requirement_change_reason,
)
from tp_core.features.karar_tablosu.hatalar import IliskiGecersiz
from tp_core.features.karar_tablosu.service import iliski_tablo_engeli
from tp_core.features.metamorfik import yeniden_yazim
from tp_core.features.metamorfik.iliskiler import bayat_mi
from tp_core.features.oracle.service import (
    gecerli_kayit,
    gereksinim_kontrolu_kuyruga_al,
    kapsayan_tablolar,
)
from tp_core.models import (
    CaseOracleKontrol,
    MetamorfikIliski,
    MetamorfikTuretme,
    Requirement,
    TestCase,
    case_id,
)
from tp_core.workflow.service import Principal, WorkflowError

ORACLE_IS = "oracle.check_requirement"
ZATEN = "zaten_turetildi"


class IliskiBulunamadi(WorkflowError):
    """İlişki yok ya da başka bir gereksinime ait (404)."""

    status_code = 404
    kod = "iliski_bulunamadi"


# ---------------------------------------------------------------------- yardımcılar


def _iliski(session: Session, req: Requirement, iliski_id: uuid.UUID) -> MetamorfikIliski:
    iliski = session.get(MetamorfikIliski, iliski_id)
    if iliski is None or iliski.requirement_id != req.id:
        raise IliskiBulunamadi("İlişki bu gereksinimde bulunamadı")
    if iliski.durum != "approved":
        raise IliskiGecersiz(
            "İlişki PO onaylı değil; türetme yalnız onaylı ilişkiyle yapılır",
            [f"durum: {iliski.durum}"],
        )
    if bayat_mi(iliski, req):
        raise IliskiGecersiz(
            "İlişki bayat: gereksinim PO onayından sonra değişmiş; ilişki yeniden onaylanmalı"
        )
    if iliski.karar_tablosu_id is None:
        raise IliskiGecersiz("İlişkinin bağlı karar tablosu yok; olgular tabloya göre seçilir")
    engel = iliski_tablo_engeli(session, iliski, req)
    if engel is not None:
        raise IliskiGecersiz("İlişki kullanılamaz", [engel])
    return iliski


def _ac_kesisir(tc: TestCase, ac_refs: set[str]) -> bool:
    ham = tc.icerik.get("acceptance_criteria_refs") or []
    refs = {str(r).replace(" ", "").upper() for r in ham}
    return bool(refs & ac_refs)


def _kaynaklar(
    session: Session,
    req: Requirement,
    iliski: MetamorfikIliski,
    case_ids: Sequence[uuid.UUID] | None,
) -> list[TestCase]:
    ac_refs = {str(r).upper() for r in iliski.icerik.get("ac_refs") or []}
    if case_ids is None:
        turetilmis = select(MetamorfikTuretme.turetilen_case_id).where(
            MetamorfikTuretme.turetilen_case_id.is_not(None)
        )
        adaylar = session.scalars(
            select(TestCase)
            .where(
                TestCase.requirement_id == req.id,
                TestCase.durum != "superseded",
                TestCase.id.not_in(turetilmis),
            )
            .order_by(TestCase.uretim_no, TestCase.sira_no)
        ).all()
        return [tc for tc in adaylar if _ac_kesisir(tc, ac_refs)]
    out: list[TestCase] = []
    for cid in dict.fromkeys(case_ids):
        tc = session.get(TestCase, cid)
        if tc is None or tc.requirement_id != req.id:
            raise CaseNotFound(f"Case bu gereksinimde bulunamadı: {cid}")
        if tc.durum == "superseded":
            raise IliskiGecersiz(f"Case geçersiz kılınmış (superseded): {cid}")
        if not _ac_kesisir(tc, ac_refs):
            raise IliskiGecersiz(f"Case ilişkinin kabul kriterlerine atıf yapmıyor: {cid}")
        out.append(tc)
    return out


def _kontrol(session: Session, tc: TestCase) -> CaseOracleKontrol | None:
    """Case'in güncel içeriğine ait, güncel kapsayan tablolarla yapılmış (geçerli) kontrol kaydı.
    Geçerlilik oracle'ın tek tanımıdır (`gecerli_kayit`); burada yeniden yazılmaz."""
    return gecerli_kayit(session, tc, tc.icerik_hash, kapsayan_tablolar(session, tc))


def kaynak_turet(
    tc: TestCase, kontrol: CaseOracleKontrol | None, iliski: MetamorfikIliski
) -> yeniden_yazim.Sonuc:
    """Bir kaynak case için türetme sonucu (DB'ye yazmaz): türetebilen ilk grup kullanılır.

    `kontrol` case'in güncel içeriğine ait GEÇERLİ kayıt olmalıdır (`_kontrol`); sonucu `uyumlu`
    değilse türetilmez (tabloyla çelişen ya da kısmen kontrol edilmiş case çoğaltılmaz)."""
    if kontrol is None:
        return yeniden_yazim.Sonuc(
            "olgu_yok",
            "Case'in güncel içeriği için güncel tablolarla yapılmış oracle kontrolü yok",
        )
    if kontrol.sonuc != "uyumlu":
        return yeniden_yazim.Sonuc(
            "olgu_yok",
            f"Kaynak case'in oracle kontrol sonucu uyumlu değil ({kontrol.sonuc}); yalnız tabloyla "
            "uyumlu case'ten türetilir",
        )
    tablo = str(iliski.karar_tablosu_id)
    gruplar = [
        g
        for g in (kontrol.ayrintilar or {}).get("gruplar") or []
        if isinstance(g, dict) and str(g.get("tablo_id")) == tablo
    ]
    ilk: yeniden_yazim.Sonuc | None = None
    for grup in gruplar:
        sonuc = yeniden_yazim.turet(tc.icerik, grup, iliski.icerik)
        if sonuc.sonuc == "turetildi":
            return sonuc
        if sonuc.sonuc != "olgu_yok" and ilk is None:
            ilk = sonuc
    return ilk or yeniden_yazim.Sonuc(
        "olgu_yok", "Oracle kontrolünde ilişkinin tablosu için doğrulanmış olgu yok"
    )


def _sonraki_sira(session: Session, requirement_id: uuid.UUID, uretim_no: int) -> int:
    son = session.scalar(
        select(func.max(TestCase.sira_no)).where(
            TestCase.requirement_id == requirement_id, TestCase.uretim_no == uretim_no
        )
    )
    return int(son or 0) + 1


def _kaydet(
    session: Session,
    satir: MetamorfikTuretme | None,
    iliski: MetamorfikIliski,
    tc: TestCase,
    user: Principal,
    sonuc: str,
    neden: str | None,
    turetilen: uuid.UUID | None = None,
) -> None:
    if satir is None:
        satir = MetamorfikTuretme(iliski_id=iliski.id, kaynak_case_id=tc.id)
        session.add(satir)
    satir.sonuc = sonuc
    satir.neden = (neden or "")[:1000] or None
    satir.turetilen_case_id = turetilen
    satir.olusturan_id = user.id


# ---------------------------------------------------------------------- türetme


def turet(
    session: Session,
    requirement_id: uuid.UUID,
    iliski_id: uuid.UUID,
    case_ids: Sequence[uuid.UUID] | None,
    user: Principal,
) -> dict[str, Any]:
    """`POST /requirements/{id}/metamorphic-cases` → `{turetilen: [...], atlanan: [...]}`."""
    req = get_requirement(session, requirement_id, lock=True)
    engel = requirement_change_reason(req)
    if engel is not None:
        raise RequirementChanged(engel)
    iliski = _iliski(session, req, iliski_id)
    kaynaklar = _kaynaklar(session, req, iliski, case_ids)

    mevcut_hashler = set(
        session.scalars(
            select(TestCase.icerik_hash).where(
                TestCase.requirement_id == req.id, TestCase.durum != "superseded"
            )
        ).all()
    )
    turetilen: list[dict[str, Any]] = []
    atlanan: list[dict[str, Any]] = []
    yeniler: list[TestCase] = []
    for tc in kaynaklar:
        satir = session.scalars(
            select(MetamorfikTuretme)
            .where(
                MetamorfikTuretme.iliski_id == iliski.id,
                MetamorfikTuretme.kaynak_case_id == tc.id,
            )
            .with_for_update()
        ).first()
        if satir is not None and satir.sonuc == "turetildi":
            atlanan.append(
                {
                    "kaynak_case_id": str(tc.id),
                    "sonuc": ZATEN,
                    "neden": f"Bu ilişkiyle zaten türetildi: {satir.turetilen_case_id}",
                }
            )
            continue
        sonuc = kaynak_turet(tc, _kontrol(session, tc), iliski)
        icerik = sonuc.icerik
        if icerik is not None:
            hatalar = content_errors(icerik, req.kabul_kriterleri)
            if hatalar:
                sonuc = yeniden_yazim.Sonuc(
                    "iliski_gecersiz",
                    "Türetilen case içerik denetiminden geçmedi: " + "; ".join(hatalar),
                )
            elif content_hash(icerik) in mevcut_hashler:
                sonuc = yeniden_yazim.Sonuc(
                    "iliski_gecersiz", "Gereksinimde aynı içerikte bir case zaten var"
                )
        if sonuc.sonuc != "turetildi" or sonuc.icerik is None:
            _kaydet(session, satir, iliski, tc, user, sonuc.sonuc, sonuc.neden)
            atlanan.append(
                {"kaynak_case_id": str(tc.id), "sonuc": sonuc.sonuc, "neden": sonuc.neden}
            )
            continue
        sira = _sonraki_sira(session, req.id, tc.uretim_no)
        yeni = TestCase(
            id=case_id(req, sira, tc.uretim_no),
            requirement_id=req.id,
            sira_no=sira,
            uretim_no=tc.uretim_no,
            kanal=tc.kanal,
            icerik=sonuc.icerik,
            icerik_hash=content_hash(sonuc.icerik),
            ai_generated=False,
            ai_call_id=None,
            uretim_modu=tc.uretim_modu,
        )
        session.add(yeni)
        session.flush()
        mevcut_hashler.add(yeni.icerik_hash)
        _kaydet(session, satir, iliski, tc, user, "turetildi", None, yeni.id)
        yeniler.append(yeni)
        turetilen.append(
            {
                "case_id": str(yeni.id),
                "kaynak_case_id": str(tc.id),
                "baslik": sonuc.icerik.get("title"),
            }
        )
    session.flush()

    for yeni in yeniler:
        publish_tx(
            session.connection(),
            "case.generated",
            {
                "id": yeni.id,
                "requirement_id": req.id,
                "title": yeni.icerik.get("title"),
                "kanal": yeni.kanal,
                "mode": yeni.uretim_modu,
                "metamorfik": True,
            },
        )
    is_id = None
    if yeniler:
        # Gereksinim başına tek bekleyen kontrol işi (oracle birleştirmesi); tekrar denemede yeni
        # case yoksa iş açılmaz.
        is_id = gereksinim_kontrolu_kuyruga_al(session, req.id, "metamorfik")
    audit_on_commit(
        session,
        user.kullanici_adi,
        "metamorfik.derived",
        f"metamorfik_iliski:{iliski.id}",
        {
            "requirement_id": req.id,
            "iliski_hash": iliski.icerik_hash,
            "turetilen": turetilen,
            "atlanan": atlanan,
            "oracle_job_id": is_id,
        },
    )
    return {"turetilen": turetilen, "atlanan": atlanan}


def turetmeler(session: Session, requirement_id: uuid.UUID) -> list[dict[str, Any]]:
    """`GET /requirements/{id}/metamorphic-derivations`: ilişkilerin türetme kayıtları."""
    get_requirement(session, requirement_id)
    satirlar = session.scalars(
        select(MetamorfikTuretme)
        .join(MetamorfikIliski, MetamorfikIliski.id == MetamorfikTuretme.iliski_id)
        .where(MetamorfikIliski.requirement_id == requirement_id)
        .order_by(MetamorfikTuretme.olusturma, MetamorfikTuretme.id)
    ).all()
    return [
        {
            "id": str(t.id),
            "iliski_id": str(t.iliski_id),
            "kaynak_case_id": str(t.kaynak_case_id),
            "turetilen_case_id": str(t.turetilen_case_id) if t.turetilen_case_id else None,
            "sonuc": t.sonuc,
            "neden": t.neden,
            "olusturan_id": str(t.olusturan_id) if t.olusturan_id else None,
            "olusturma": t.olusturma,
        }
        for t in satirlar
    ]


def turetilen_olgulari(session: Session, tc: TestCase) -> dict[str, Any] | None:
    """Türetilen case'in olguları, değer çıkarma (`case_facts`) çıktısı biçiminde; model çağrısı
    yerine oracle'a verilebilir (`oracle.dogrulama.degerlendir(icerik, tablolar, cikti)`).

    Case bir türetme ürünü değilse, kaynak ya da ilişki artık geçerli değilse ya da türetme bugün
    yeniden yapıldığında case'in GÜNCEL içeriğini (`icerik_hash`) vermiyorsa (ör. analist
    düzeltmiş) None döner; çağıran o zaman normal değer çıkarmayı kullanır.
    """
    satir = session.scalars(
        select(MetamorfikTuretme).where(
            MetamorfikTuretme.turetilen_case_id == tc.id,
            MetamorfikTuretme.sonuc == "turetildi",
        )
    ).first()
    if satir is None:
        return None
    kaynak = session.get(TestCase, satir.kaynak_case_id)
    iliski = session.get(MetamorfikIliski, satir.iliski_id)
    if kaynak is None or iliski is None or iliski.durum != "approved":
        return None
    req = session.get(Requirement, tc.requirement_id)
    if req is None or bayat_mi(iliski, req) or iliski_tablo_engeli(session, iliski, req):
        return None
    sonuc = kaynak_turet(kaynak, _kontrol(session, kaynak), iliski)
    if sonuc.icerik is None or content_hash(sonuc.icerik) != tc.icerik_hash:
        return None
    return sonuc.olgular


__all__ = [
    "ORACLE_IS",
    "IliskiBulunamadi",
    "kaynak_turet",
    "turet",
    "turetilen_olgulari",
    "turetmeler",
]
