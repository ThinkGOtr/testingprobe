"""AI ajan ürünleri ve Agent Probe ajan testi talepleri (specs/011 F6, K10).

Ürün sahibi kararı: test edilen ürün bir AI ajanıysa test Agent Probe'da koşar (Sauce Labs benzeri);
yalnız Agent Probe'da ön tanımları tamamlanmış ürünler Testing Probe'da görünür ve Testing Probe
yalnız sonuca göre süreci sürdürür. Bu sürümde Agent Probe simüle edilir (kayıt atılır, cevap
gelir).

Akış ve durumlar:

1. Analist gereksinimi bir ajan ürününe bağlar (`urun_bagla`). Gereksinimin güncel case'i varsa ya
   da üretim sürüyorsa bağlanamaz; bağlıyken case üretimi (portal ve IDE) 409 `ajan_urunu` alır.
2. "Agent Probe'da test başlat" (`test_baslat`): yalnız `po_approved` ve PO onayı güncel içerikte;
   süren talep yokken. Port kaydı açar (talep no `APT-<yıl>-<n>`), satır `queued`.
3. Sorgulama (`gorunum(..., yenile=True)`, `GET /requirements/{id}/agent-test`): bitmemiş talebin
   durumu porttan okunur ve yazılır (queued → running → passed | failed | error; geri gitmez).
4. Sonuç bir kez işlenir (`islenme`):
   - `passed` → gereksinim `po_approved → done` (kapı: PO onayı güncel; koşul: bu içerik için geçen
     ajan testi). PO onayı bu arada geçersizleştiyse geçiş yapılmaz, `surec = onay_gecersiz`.
   - `failed` → `surec = bulgu`: kalan senaryolar talebin sonucunda listelenir; gereksinim
     `po_approved` kalır, ajan düzeltilince test yeniden başlatılır. Bug taslağı ÜRETİLMEZ: Testing
     Probe'un bug akışı CI koşusundaki bir hataya (`failure`) bağlıdır ve Jira'ya yayın kapısıyla
     çıkar; ajan testi bulgusunun kaydı ve kanıtı Agent Probe'dadır — ikinci bir kayıt açmak çift
     kaynak yaratır. Portal kalan senaryoları ve Agent Probe bağlantısını gösterir.
   - `error` → `surec = hata`; yeniden başlatılabilir.
Her adım `audit_on_commit` ile denetim zincirine yazılır.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import select, text
from sqlalchemy.orm import Session, object_session

from tp_core.audit import audit_on_commit
from tp_core.integrations.agent_probe import AgentProbeUnavailable, get_agent_probe
from tp_core.models import Requirement
from tp_core.models.agent_probe_feature import AjanTestiTalebi, AjanUrunuBaglantisi
from tp_core.ports import AgentProduct, AgentTestTicket
from tp_core.workflow.service import (
    Principal,
    WorkflowError,
    content_hash_of,
    transition,
)

AKTOR: Final = "agent-probe"
BITMEMIS: Final = frozenset({"queued", "running"})
SON_DURUMLAR: Final = frozenset({"passed", "failed", "error"})
_SIRA: Final = {"queued": 0, "running": 1, "passed": 2, "failed": 2, "error": 2}
AKTIF_OLMAYAN_CASE: Final = ("superseded", "rejected")

AJAN_URUNU_NEDENI: Final = "Ajan ürünü — test Agent Probe'da koşar"


class AjanUrunuHatasi(WorkflowError):
    """Ajan ürününe bağlı gereksinimde case akışı istendi."""

    status_code = 409
    kod = "ajan_urunu"


class AjanUrunuBaglanamaz(WorkflowError):
    status_code = 409
    kod = "ajan_urunu_baglanamaz"


class AjanTestiBaslatilamaz(WorkflowError):
    status_code = 409
    kod = "ajan_testi_baslatilamaz"


class AgentProbeErisilemiyor(WorkflowError):
    status_code = 503
    kod = None


class GereksinimYok(WorkflowError):
    status_code = 404
    kod = None


# ------------------------------------------------------------------ sorgular


def baglanti(session: Session, requirement_id: uuid.UUID) -> AjanUrunuBaglantisi | None:
    return session.get(AjanUrunuBaglantisi, requirement_id)


def talepler(session: Session, requirement_id: uuid.UUID) -> list[AjanTestiTalebi]:
    return list(
        session.scalars(
            select(AjanTestiTalebi)
            .where(AjanTestiTalebi.requirement_id == requirement_id)
            .order_by(AjanTestiTalebi.olusturma.desc(), AjanTestiTalebi.talep_no.desc())
        )
    )


def son_talep(session: Session, requirement_id: uuid.UUID) -> AjanTestiTalebi | None:
    liste = talepler(session, requirement_id)
    return liste[0] if liste else None


def ajan_urunu_engeli(session: Session, requirement_id: uuid.UUID) -> None:
    """Case üretimi/IDE taslağı öncesi: bağlı gereksinimde 409 `ajan_urunu`."""
    if baglanti(session, requirement_id) is not None:
        raise AjanUrunuHatasi(
            "Bu gereksinim bir AI ajan ürününe bağlı — test Agent Probe'da koşar; case üretimi "
            "yapılmaz."
        )


def ajan_testi_gecti(req: Any) -> bool:
    """Durum makinesi koşulu (`po_approved → done`): bağlı ürünün son talebi bu içerikte geçti."""
    session = object_session(req)
    if session is None:
        return False
    b = baglanti(session, req.id)
    son = son_talep(session, req.id)
    return (
        b is not None
        and son is not None
        and son.urun_kodu == b.urun_kodu
        and son.durum == "passed"
        and son.gereksinim_hash == content_hash_of(req)
    )


def _gereksinim(
    session: Session, requirement_id: uuid.UUID, *, kilitle: bool = False
) -> Requirement:
    req = session.get(Requirement, requirement_id, with_for_update=kilitle or None)
    if req is None:
        raise GereksinimYok("Gereksinim bulunamadı")
    return req


def _aktif_case_var(session: Session, requirement_id: uuid.UUID) -> bool:
    return (
        session.execute(
            text(
                "SELECT 1 FROM test_case WHERE requirement_id = :r "
                "AND durum NOT IN ('superseded', 'rejected') LIMIT 1"
            ),
            {"r": requirement_id},
        ).first()
        is not None
    )


def _port() -> Any:
    try:
        return get_agent_probe()
    except AgentProbeUnavailable as exc:
        raise AgentProbeErisilemiyor(f"Agent Probe kullanılamıyor: {exc}") from exc


def urunler() -> tuple[str, list[AgentProduct]]:
    port = _port()
    try:
        liste = [u for u in port.list_products() if u.hazir]
    except Exception as exc:
        raise AgentProbeErisilemiyor("Agent Probe ürün listesi alınamadı") from exc
    return getattr(port, "name", "tp"), liste


def _urun(kod: str) -> AgentProduct | None:
    _kip, liste = urunler()
    return next((u for u in liste if u.kod == kod), None)


# ------------------------------------------------------------------ engel


def baslatma_engeli(session: Session, req: Requirement) -> str | None:
    b = baglanti(session, req.id)
    if b is None:
        return "Önce bir ajan ürününe bağlayın."
    son = son_talep(session, req.id)
    if son is not None and son.durum in BITMEMIS:
        return "Süren bir ajan testi talebi var."
    if req.durum == "done":
        return "Gereksinim tamamlandı; içerik değişirse yeniden test edilir."
    if req.durum != "po_approved":
        return "Ajan testi yalnız PO onaylı gereksinimde başlatılabilir."
    if req.onaylanan_hash is None or req.onaylanan_hash != content_hash_of(req):
        return "İçerik PO onayından sonra değişti; yeniden PO onayı gerekir."
    return None


# ------------------------------------------------------------------ işlemler


def urun_bagla(
    session: Session, requirement_id: uuid.UUID, urun_kodu: str | None, user: Principal
) -> None:
    req = _gereksinim(session, requirement_id, kilitle=True)
    son = son_talep(session, req.id)
    if son is not None and son.durum in BITMEMIS:
        raise AjanUrunuBaglanamaz("Süren bir ajan testi varken ürün bağlantısı değiştirilemez.")
    mevcut = baglanti(session, req.id)
    if urun_kodu is None:
        if mevcut is not None:
            session.delete(mevcut)
            audit_on_commit(
                session,
                user.kullanici_adi,
                "agent_probe.urun_baglantisi_kaldirildi",
                f"requirement:{req.id}",
                {"urun_kodu": mevcut.urun_kodu},
            )
        return
    if req.durum in ("generating", "cases_ready") or _aktif_case_var(session, req.id):
        raise AjanUrunuBaglanamaz(
            "Bu gereksinim için case üretilmiş ya da üretim sürüyor; ajan ürününe bağlanamaz."
        )
    if _urun(urun_kodu) is None:
        raise AjanUrunuBaglanamaz("Ürün Agent Probe'da hazır değil ya da yok.")
    if mevcut is None:
        session.add(
            AjanUrunuBaglantisi(
                requirement_id=req.id, urun_kodu=urun_kodu, baglayan=user.kullanici_adi
            )
        )
    else:
        mevcut.urun_kodu = urun_kodu
        mevcut.baglayan = user.kullanici_adi
    session.flush()
    audit_on_commit(
        session,
        user.kullanici_adi,
        "agent_probe.urun_baglandi",
        f"requirement:{req.id}",
        {"urun_kodu": urun_kodu, "onceki": mevcut.urun_kodu if mevcut else None},
    )


def _gereksinim_ozeti(req: Requirement) -> dict[str, Any]:
    return {
        "jira_key": req.jira_key,
        "baslik": req.baslik,
        "aciklama": req.aciklama,
        "kabul_kriterleri": list(req.kabul_kriterleri or []),
    }


def test_baslat(session: Session, requirement_id: uuid.UUID, user: Principal) -> AjanTestiTalebi:
    req = _gereksinim(session, requirement_id, kilitle=True)
    engel = baslatma_engeli(session, req)
    if engel is not None:
        raise AjanTestiBaslatilamaz(engel)
    b = baglanti(session, req.id)
    assert b is not None
    port = _port()
    try:
        bilet = port.start_agent_test(b.urun_kodu, req.id, _gereksinim_ozeti(req))
    except WorkflowError:
        raise
    except Exception as exc:
        raise AgentProbeErisilemiyor("Agent Probe'a test talebi atılamadı") from exc
    talep = AjanTestiTalebi(
        requirement_id=req.id,
        urun_kodu=b.urun_kodu,
        talep_no=bilet.talep_no,
        durum=bilet.durum,
        ozet=bilet.ozet,
        sonuc=dict(bilet.sonuc),
        url=bilet.url,
        simulasyon=bilet.simulasyon,
        baslatan=user.kullanici_adi,
        gereksinim_hash=content_hash_of(req),
    )
    session.add(talep)
    session.flush()
    audit_on_commit(
        session,
        user.kullanici_adi,
        "agent_probe.test_baslatildi",
        f"requirement:{req.id}",
        {
            "talep_no": talep.talep_no,
            "urun_kodu": talep.urun_kodu,
            "hash": talep.gereksinim_hash,
            "simulasyon": talep.simulasyon,
            "kip": getattr(port, "name", None),
        },
    )
    return talep


def _uygula(session: Session, talep: AjanTestiTalebi, bilet: AgentTestTicket) -> bool:
    """Port durumunu yazar (geri gitmez); değiştiyse True."""
    if talep.durum in SON_DURUMLAR or _SIRA[bilet.durum] < _SIRA[talep.durum]:
        return False
    if bilet.durum == talep.durum and dict(bilet.sonuc) == dict(talep.sonuc or {}):
        return False
    onceki = talep.durum
    talep.durum = bilet.durum
    talep.ozet = bilet.ozet
    talep.sonuc = dict(bilet.sonuc)
    talep.url = bilet.url or talep.url
    talep.guncelleme = datetime.now(UTC)
    if onceki != bilet.durum:
        audit_on_commit(
            session,
            AKTOR,
            "agent_probe.test_durumu",
            f"requirement:{talep.requirement_id}",
            {"talep_no": talep.talep_no, "from": onceki, "to": bilet.durum},
        )
    return True


def _isle(session: Session, req: Requirement, talep: AjanTestiTalebi) -> None:
    """Son durumdaki talebin sonucunu Testing Probe sürecine bir kez uygular."""
    if talep.durum not in SON_DURUMLAR or talep.islenme is not None:
        return
    talep.islenme = datetime.now(UTC)
    if talep.durum == "passed":
        if req.durum == "po_approved" and ajan_testi_gecti(req):
            try:
                with session.begin_nested():
                    transition(
                        session,
                        req,
                        "done",
                        AKTOR,
                        "po_approved",
                        sebep="Agent Probe ajan testi geçti",
                        ozet={"talep_no": talep.talep_no, "urun_kodu": talep.urun_kodu},
                    )
                talep.surec = "tamamlandi"
                talep.surec_notu = "Ajan testi geçti; gereksinim tamamlandı olarak işaretlendi."
            except WorkflowError:
                talep.surec = "onay_gecersiz"
                talep.surec_notu = (
                    "Ajan testi geçti ama PO onayı güncel değil; gereksinim ilerletilmedi."
                )
        else:
            talep.surec = "onay_gecersiz"
            talep.surec_notu = (
                "Ajan testi geçti ama gereksinim içeriği ya da durumu değişti; yeniden PO onayı ve "
                "test gerekir."
            )
    elif talep.durum == "failed":
        talep.surec = "bulgu"
        talep.surec_notu = (
            "Kalan senaryolar bulgu olarak listelendi; ajan düzeltildikten sonra testi yeniden "
            "başlatın. Bulgu kaydı Agent Probe'dadır."
        )
    else:
        talep.surec = "hata"
        talep.surec_notu = "Agent Probe talebi hata ile bitti; testi yeniden başlatabilirsiniz."
    audit_on_commit(
        session,
        AKTOR,
        "agent_probe.sonuc_islendi",
        f"requirement:{req.id}",
        {
            "talep_no": talep.talep_no,
            "durum": talep.durum,
            "surec": talep.surec,
            "gecen": (talep.sonuc or {}).get("gecen"),
            "kalan": (talep.sonuc or {}).get("kalan"),
        },
    )


def yenile(session: Session, requirement_id: uuid.UUID) -> None:
    """Sorgulama: bitmemiş son talebin durumunu porttan okur, sonucu işler. Port erişilemezse
    mevcut kayıt gösterilir (sorgulama hatası talebi `error` yapmaz; yeniden denenir)."""
    son = son_talep(session, requirement_id)
    if son is None:
        return
    if son.durum in BITMEMIS:
        try:
            bilet = _port().get_agent_test(son.talep_no)
        except Exception:
            return
        req = _gereksinim(session, requirement_id, kilitle=True)
        session.refresh(son, with_for_update=True)
        _uygula(session, son, bilet)
        session.flush()
        _isle(session, req, son)
    elif son.islenme is None:
        req = _gereksinim(session, requirement_id, kilitle=True)
        _isle(session, req, son)
    session.flush()


# ------------------------------------------------------------------ görünüm


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def talep_ozeti(t: AjanTestiTalebi) -> dict[str, Any]:
    return {
        "talep_no": t.talep_no,
        "urun_kodu": t.urun_kodu,
        "durum": t.durum,
        "ozet": t.ozet,
        "sonuc": t.sonuc or {},
        "url": t.url,
        "simulasyon": t.simulasyon,
        "baslatan": t.baslatan,
        "olusturma": _iso(t.olusturma),
        "guncelleme": _iso(t.guncelleme),
        "islenme": _iso(t.islenme),
        "surec": t.surec,
        "surec_notu": t.surec_notu,
    }


def gorunum(session: Session, requirement_id: uuid.UUID) -> dict[str, Any]:
    req = _gereksinim(session, requirement_id)
    b = baglanti(session, req.id)
    urun: AgentProduct | None = None
    if b is not None:
        try:
            urun = _urun(b.urun_kodu)
        except AgentProbeErisilemiyor:
            urun = None
    liste = talepler(session, req.id)
    engel = baslatma_engeli(session, req)
    return {
        "requirement_id": str(req.id),
        "urun_kodu": b.urun_kodu if b else None,
        "urun": urun.model_dump() if urun else None,
        "baglayan": b.baglayan if b else None,
        "baglanma": _iso(b.guncelleme) if b else None,
        "simulasyon": True,
        "baslatilabilir": engel is None,
        "engel": engel,
        "talep": talep_ozeti(liste[0]) if liste else None,
        "gecmis": [talep_ozeti(t) for t in liste[1:]],
    }
