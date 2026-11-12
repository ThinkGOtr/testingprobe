"""AI ajan ürünleri ve Agent Probe ajan testi talepleri (specs/011 F6, K10).

Ürün sahibi kararı: test edilen ürün bir AI ajanıysa test Agent Probe'da koşar (Sauce Labs benzeri);
yalnız Agent Probe'da ön tanımları tamamlanmış ürünler Testing Probe'da görünür ve Testing Probe
yalnız sonuca göre süreci sürdürür. Bu sürümde Agent Probe simüle edilir (kayıt atılır, cevap
gelir).

Akış ve durumlar:

1. Analist gereksinimi bir ajan ürününe bağlar (`urun_bagla`). Gereksinimin güncel case'i varsa,
   case üretimi ya da tasarım modeli (iki tur: `modeling`, `model_ready`) sürüyorsa ya da
   gereksinim `done` ise bağlanamaz/kaldırılamaz; bağlıyken case üretimi (portal, IDE) ve tasarım
   modeli üretimi (`model_service.start_model_generation`) 409 `ajan_urunu` alır.
2. "Agent Probe'da test başlat" (`test_baslat`): yalnız `po_approved` ve PO onayı güncel içerikte;
   süren talep yokken. Port kaydı açar (talep no `APT-<yıl>-<n>`), satır `queued`. Port çağrısı
   gereksinim satır kilidi altında YAPILMAZ (ileride http portu): ön denetim kilitsiz, çağrıdan
   sonra satır kilitlenip engel yeniden denetlenir.
3. Sorgulama (`yenile`, `POST /requirements/{id}/agent-test/refresh`, analist): bitmemiş talebin
   durumu porttan okunur ve yazılır (queued → running → passed | failed | error; geri gitmez).
   `GET /requirements/{id}/agent-test` yan etkisizdir (yalnız okur).
4. Sonuç bir kez işlenir (`islenme`; talep satırı `FOR UPDATE` ile tazelenir, eşzamanlı iki
   işleme yarışmaz):
   - `passed` → gereksinim `po_approved → done` (kapı: PO onayı güncel; koşul: bu içerik için geçen
     **gerçek** ajan testi). PO onayı bu arada geçersizleştiyse geçiş yapılmaz,
     `surec = onay_gecersiz`. **Simülasyon** talebi (`simulasyon=True`) gereksinimi ilerletmez:
     sonuç gösterilir, `surec = simule` (güvenlik #5). Demo için `TP_AGENT_PROBE_SIM_TAMAMLAR=on`
     ile açılabilir (varsayılan kapalı).
   - `failed` → `surec = bulgu`: kalan senaryolar talebin sonucunda listelenir; gereksinim
     `po_approved` kalır, ajan düzeltilince test yeniden başlatılır. Bug taslağı ÜRETİLMEZ: Testing
     Probe'un bug akışı CI koşusundaki bir hataya (`failure`) bağlıdır ve Jira'ya yayın kapısıyla
     çıkar; ajan testi bulgusunun kaydı ve kanıtı Agent Probe'dadır — ikinci bir kayıt açmak çift
     kaynak yaratır. Portal kalan senaryoları ve Agent Probe bağlantısını gösterir.
   - `error` → `surec = hata`; yeniden başlatılabilir.
Her adım `audit_on_commit` ile denetim zincirine yazılır.
"""

from __future__ import annotations

import logging
import os
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
from tp_core.workflow.states import AJAN_TESTI_GECTI, register_guard

log = logging.getLogger(__name__)

AKTOR: Final = "agent-probe"
SIM_TAMAMLAR_ORTAMI: Final = "TP_AGENT_PROBE_SIM_TAMAMLAR"
# Bağlantının değiştirilemediği gereksinim durumları (case/tasarım modeli akışı ya da tamamlandı).
BAGLANTI_KILITLI: Final = frozenset(
    {"generating", "cases_ready", "modeling", "model_ready", "done"}
)
# Durum makinesi koruması (`workflow.states.REQUIREMENT`): kayıt edilebilir biçim (D1 bağlar).
DONE_GECISI: Final = ("po_approved", "done")
DONE_KORUMASI_ACIKLAMASI: Final = (
    "yalnız Agent Probe testi geçen AI ajan ürünü gereksinimi case'siz tamamlanır"
)
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


def baglanti(
    session: Session, requirement_id: uuid.UUID, *, tazele: bool = False
) -> AjanUrunuBaglantisi | None:
    if not tazele:
        return session.get(AjanUrunuBaglantisi, requirement_id)
    return session.scalars(
        select(AjanUrunuBaglantisi)
        .where(AjanUrunuBaglantisi.requirement_id == requirement_id)
        .execution_options(populate_existing=True)
    ).first()


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


def sim_tamamlar() -> bool:
    """`TP_AGENT_PROBE_SIM_TAMAMLAR=on`: simülasyon sonucu gereksinimi `done`'a taşıyabilir
    (yalnız demo; varsayılan kapalı)."""
    return (os.environ.get(SIM_TAMAMLAR_ORTAMI) or "").strip().lower() in (
        "1",
        "on",
        "true",
        "acik",
    )


def ajan_testi_gecti(req: Any) -> bool:
    """Durum makinesi koşulu (`po_approved → done`): bağlı ürünün son talebi bu içerikte geçti ve
    talep gerçek Agent Probe sonucudur (simülasyon yalnız `TP_AGENT_PROBE_SIM_TAMAMLAR=on` iken)."""
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
        and (not son.simulasyon or sim_tamamlar())
    )


# Durum makinesi koşulu (`po_approved → done`): workflow katmanı features'a bağımlı olmaz,
# koşul burada kaydedilir (011 D1 #16).
register_guard(AJAN_TESTI_GECTI, ajan_testi_gecti)


def _gereksinim(
    session: Session, requirement_id: uuid.UUID, *, kilitle: bool = False
) -> Requirement:
    req = session.get(
        Requirement,
        requirement_id,
        with_for_update=kilitle or None,
        populate_existing=kilitle,
    )
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
    # Ürün listesi port çağrısıdır: satır kilidi alınmadan önce denetlenir.
    if urun_kodu is not None and _urun(urun_kodu) is None:
        raise AjanUrunuBaglanamaz("Ürün Agent Probe'da hazır değil ya da yok.")
    req = _gereksinim(session, requirement_id, kilitle=True)
    son = son_talep(session, req.id)
    if son is not None and son.durum in BITMEMIS:
        raise AjanUrunuBaglanamaz("Süren bir ajan testi varken ürün bağlantısı değiştirilemez.")
    if req.durum in BAGLANTI_KILITLI:
        raise AjanUrunuBaglanamaz(
            "Gereksinim case üretimi, tasarım modeli ya da tamamlanmış durumda "
            f"({req.durum}); ajan ürünü bağlantısı değiştirilemez."
        )
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
    if _aktif_case_var(session, req.id):
        raise AjanUrunuBaglanamaz(
            "Bu gereksinim için case üretilmiş ya da üretim sürüyor; ajan ürününe bağlanamaz."
        )
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
    """Ön denetim kilitsiz → port çağrısı (satır kilidi YOK) → satır kilidi + engel yeniden
    denetimi → kayıt. Yarışta kaybeden istek 409 alır; açılmış uzak talep kaydı (yetim) günlüğe
    ve denetim zincirine yazılmaz (işlem geri alınır), uyarı olarak loglanır."""
    req = _gereksinim(session, requirement_id)
    engel = baslatma_engeli(session, req)
    if engel is not None:
        raise AjanTestiBaslatilamaz(engel)
    b = baglanti(session, req.id)
    assert b is not None
    urun_kodu = b.urun_kodu
    icerik_hash = content_hash_of(req)
    ozet = _gereksinim_ozeti(req)
    port = _port()
    try:
        bilet = port.start_agent_test(urun_kodu, req.id, ozet)
    except WorkflowError:
        raise
    except Exception as exc:
        raise AgentProbeErisilemiyor("Agent Probe'a test talebi atılamadı") from exc
    req = _gereksinim(session, requirement_id, kilitle=True)
    b = baglanti(session, req.id, tazele=True)
    engel = baslatma_engeli(session, req)
    if engel is None and (
        b is None or b.urun_kodu != urun_kodu or content_hash_of(req) != icerik_hash
    ):
        engel = "Gereksinim ya da ürün bağlantısı talep sırasında değişti; yeniden deneyin."
    if engel is not None:
        log.warning(
            "ajan testi talebi %s kayda alınmadı (eşzamanlı değişiklik); Agent Probe'da yetim",
            bilet.talep_no,
        )
        raise AjanTestiBaslatilamaz(engel)
    talep = AjanTestiTalebi(
        requirement_id=req.id,
        urun_kodu=urun_kodu,
        talep_no=bilet.talep_no,
        durum=bilet.durum,
        ozet=bilet.ozet,
        sonuc=dict(bilet.sonuc),
        url=bilet.url,
        simulasyon=bilet.simulasyon,
        baslatan=user.kullanici_adi,
        gereksinim_hash=icerik_hash,
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
    if talep.durum == "passed" and talep.simulasyon and not sim_tamamlar():
        talep.surec = "simule"
        talep.surec_notu = (
            "Simülasyon sonucu: senaryolar geçti, ancak simüle edilmiş sonuç gereksinimi "
            "tamamlanmış saymaz. Gerçek Agent Probe sonucu gerekir."
        )
    elif talep.durum == "passed":
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
    """Sorgulama (`POST …/agent-test/refresh`): bitmemiş son talebin durumunu porttan okur, sonucu
    işler. Port çağrısı kilitsizdir; yazmadan önce gereksinim ve talep satırı `FOR UPDATE` ile
    tazelenir (eşzamanlı iki yenileme sonucu iki kez işleyemez). Port erişilemezse mevcut kayıt
    kalır (sorgulama hatası talebi `error` yapmaz; yeniden denenir)."""
    son = son_talep(session, requirement_id)
    if son is None:
        return
    bilet: AgentTestTicket | None = None
    if son.durum in BITMEMIS:
        try:
            bilet = _port().get_agent_test(son.talep_no)
        except Exception:
            return
    elif son.islenme is not None:
        return
    req = _gereksinim(session, requirement_id, kilitle=True)
    session.refresh(son, with_for_update=True)
    if bilet is not None:
        _uygula(session, son, bilet)
        session.flush()
    _isle(session, req, son)
    session.flush()


def yenilenebilir(talep: AjanTestiTalebi | None) -> bool:
    """Portal: yenileme (`POST …/refresh`) gerekir mi (bitmemiş ya da işlenmemiş son talep)."""
    return talep is not None and (talep.durum in BITMEMIS or talep.islenme is None)


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
        "sim_tamamlar": sim_tamamlar(),
        "yenilenebilir": yenilenebilir(liste[0] if liste else None),
        "baslatilabilir": engel is None,
        "engel": engel,
        "talep": talep_ozeti(liste[0]) if liste else None,
        "gecmis": [talep_ozeti(t) for t in liste[1:]],
    }
