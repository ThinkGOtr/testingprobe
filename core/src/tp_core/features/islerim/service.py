"""İşlerim (TP UX denetimi IA-01/IA-02): rolün iş kuyruğu ve ekipte bekleyenler.

Kaynak, durum makinelerinin insan kapılarıdır (asistanın `probe_my_queue` sayımıyla aynı kapı
sözlüğü: `features/assistant/tools/probe.py` `*_KAPILARI`). Her **kaynak** bir rolün kapısıdır
(tür, sorgu, başlık, sıradaki adım); çağıranın rolüne düşenler `benim`, diğer rollerinkiler
`ekip` grubunda döner. Sistem işleri (denetim sürüyor, üretim kuyrukta) kuyruğa girmez.

- Case kararları gereksinim başına tek öğedir ("TPD-1 · 3 case karar bekliyor"); gereksinimin
  önceki (PO onayı yenilenmiş) içeriğine ait case'ler sayılmaz (`old_content_case_ids`).
- Kasıtlı kırma (`failure_ek.kirma`) ve kırarak doğrulama koşuları kuyruğa girmez.
- Aynı testin tekrarlayan hataları (aynı test adı + sınıf) tek öğedir (en yenisi).
- `menu`: rota → çağıranın bekleyen iş sayısı (portal menü rozeti; 0 ise rozet yok).

Yalnız SELECT; proje kapsamı ORM filtresinden gelir.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from tp_core.auth import yetki
from tp_core.models import AppUser, BugDraft, Failure, Requirement, Run, Script, TestCase
from tp_core.models.codegen_feature import ScriptCodegen
from tp_core.models.triage_feature import FailureEk

OGE_UST = 20
EKIP_OGE_UST = 5
KISI_UST = 3
KOSU_GUN = 7
HATA_TARAMA = 300

# Tür → öğe ayrıntısını görmek için gereken izin (sayılar herkese açık; ayrıntı rol okumasına göre).
TUR_IZNI: dict[str, str] = {
    "requirement": "requirement.read",
    "case": "case.analysis_read",
    "script": "code.read",
    "run": "run.read",
    "failure": "failure.read",
    "bug_draft": "case.analysis_read",
}
# Tür → menü rotası (rozet sayısı).
TUR_ROTASI: dict[str, str] = {
    "requirement": "/gereksinimler",
    "case": "/caseler",
    "script": "/kod",
    "run": "/kosular",
    "failure": "/hatalar",
    "bug_draft": "/bug-taslaklari",
}
MENU_ROTALARI = ("/islerim", *dict.fromkeys(TUR_ROTASI.values()))


@dataclass
class Oge:
    id: str
    tur: str
    etiket: str
    neden: str
    rota: str
    zaman: datetime | None
    jira_key: str | None = None
    sayi: int = 1

    def json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tur": self.tur,
            "etiket": self.etiket,
            "neden": self.neden,
            "rota": self.rota,
            "zaman": self.zaman.isoformat() if self.zaman else None,
            "jira_key": self.jira_key,
            "sayi": self.sayi,
        }


@dataclass
class Grup:
    anahtar: str
    tur: str
    rol: str
    baslik: str
    sonraki_adim: str
    ogeler: list[Oge] = field(default_factory=list)

    @property
    def sayi(self) -> int:
        return sum(o.sayi for o in self.ogeler)

    def json(self, oge_ust: int, ayrinti: bool) -> dict[str, Any]:
        return {
            "anahtar": self.anahtar,
            "tur": self.tur,
            "rol": self.rol,
            "rol_etiketi": yetki.ROL_ETIKETLERI.get(self.rol, self.rol),
            "baslik": self.baslik,
            "sonraki_adim": self.sonraki_adim,
            "sayi": self.sayi,
            "oge_sayisi": len(self.ogeler),
            "ogeler": [o.json() for o in self.ogeler[:oge_ust]] if ayrinti else [],
        }


def _kirp(m: str | None, n: int = 80) -> str:
    m = " ".join((m or "").split())
    return m if len(m) <= n else m[: n - 1] + "…"


def _req_etiket(r: Requirement) -> str:
    return f"{r.jira_key or 'Serbest metin'} · {_kirp(r.baslik, 70)}"


# ----------------------------------------------------------------- kaynaklar


def _gereksinimler(s: Session, durumlar: Iterable[str]) -> list[Requirement]:
    return list(
        s.scalars(
            select(Requirement)
            .where(Requirement.durum.in_(list(durumlar)))
            .order_by(Requirement.olusturma.desc(), Requirement.id)
        )
    )


def _req_grubu(
    s: Session,
    anahtar: str,
    rol: str,
    durumlar: tuple[str, ...],
    baslik: str,
    sonraki: str,
    neden: Callable[[Requirement], str],
    suzgec: Callable[[Requirement], bool] = lambda _r: True,
) -> Grup:
    g = Grup(anahtar, "requirement", rol, baslik, sonraki)
    for r in _gereksinimler(s, durumlar):
        if suzgec(r):
            g.ogeler.append(
                Oge(
                    str(r.id),
                    "requirement",
                    _req_etiket(r),
                    neden(r),
                    f"/gereksinimler/{r.id}",
                    r.olusturma,
                    r.jira_key,
                )
            )
    return g


def _case_grubu(
    s: Session, anahtar: str, rol: str, durum: str, baslik: str, sonraki: str, neden: str
) -> Grup:
    """Gereksinim başına tek öğe; önceki içeriğe ait case'ler sayılmaz."""
    from tp_core.features.cases.service import old_content_case_ids

    g = Grup(anahtar, "case", rol, baslik, sonraki)
    satirlar = s.execute(
        select(TestCase.id, TestCase.requirement_id, TestCase.olusturma)
        .where(TestCase.durum == durum)
        .order_by(TestCase.olusturma.desc())
    ).all()
    gruplar: dict[Any, list[Any]] = {}
    for cid, rid, zaman in satirlar:
        gruplar.setdefault(rid, []).append((cid, zaman))
    for rid, caseler in gruplar.items():
        req = s.get(Requirement, rid)
        if req is None:
            continue
        eski = old_content_case_ids(s, req)
        guncel = [c for c in caseler if c[0] not in eski]
        if not guncel:
            continue
        g.ogeler.append(
            Oge(
                str(req.id),
                "case",
                _req_etiket(req),
                neden.format(n=len(guncel)),
                f"/gereksinimler/{req.id}/caseler",
                max(z for _c, z in guncel),
                req.jira_key,
                sayi=len(guncel),
            )
        )
    g.ogeler.sort(key=lambda o: o.zaman or datetime.min.replace(tzinfo=UTC), reverse=True)
    return g


def _script_grubu(
    s: Session, anahtar: str, durum: str, baslik: str, sonraki: str, varsayilan_neden: str
) -> Grup:
    g = Grup(anahtar, "script", yetki.ENGINEER, baslik, sonraki)
    q = (
        select(Script, ScriptCodegen)
        .outerjoin(ScriptCodegen, ScriptCodegen.script_id == Script.id)
        .where(Script.durum == durum)
        .order_by(Script.olusturma.desc(), Script.id)
    )
    for sc, cg in s.execute(q).all():
        if cg is not None:
            etiket = (
                f"{cg.story_key or '—'} · C{cg.sira_no} · {_kirp(cg.baslik or sc.dosya_yolu, 60)}"
            )
            neden = _kirp(cg.engel_nedeni, 140) if durum == "blocked" and cg.engel_nedeni else None
        else:
            etiket = _kirp(sc.dosya_yolu.rsplit("/", 1)[-1], 70)
            neden = None
        if durum == "pr_open" and sc.pr_no:
            neden = f"PR #{sc.pr_no} açık: kırarak doğrulama ve birleştirme kararı"
        g.ogeler.append(
            Oge(
                str(sc.id),
                "script",
                etiket,
                neden or varsayilan_neden,
                f"/kod/{sc.id}",
                sc.olusturma,
                cg.story_key if cg else None,
            )
        )
    return g


def _hata_grubu(
    s: Session,
    anahtar: str,
    rol: str,
    baslik: str,
    sonraki: str,
    kosul: Any,
    neden: Callable[[Failure], str],
) -> Grup:
    g = Grup(anahtar, "failure", rol, baslik, sonraki)
    q = (
        select(Failure)
        .outerjoin(FailureEk, FailureEk.failure_id == Failure.id)
        .join(Run, Run.id == Failure.run_id)
        .where(
            kosul,
            or_(FailureEk.kirma.is_(None), FailureEk.kirma.is_(False)),
            Run.tetik.notin_(("break_verify",)),
        )
        .order_by(Failure.olusturma.desc(), Failure.id)
        .limit(HATA_TARAMA)
    )
    gorulen: set[tuple[str, str]] = set()
    for f in s.scalars(q):
        k = (f.test_adi, f.sinif)
        if k in gorulen:
            continue
        gorulen.add(k)
        g.ogeler.append(
            Oge(
                str(f.id),
                "failure",
                _kirp(f.test_adi, 80),
                neden(f),
                f"/hatalar/{f.id}",
                f.olusturma,
            )
        )
    return g


def _belirsiz_neden(f: Failure) -> str:
    if f.uretim_modu == "replay_miss":
        return "REPLAY-MISS: AI yorumu alınamadı; sınıfı siz belirleyin"
    return "Kural eşleşmedi, AI sınıflandıramadı; sınıfı siz belirleyin"


def _bakim_neden(f: Failure) -> str:
    if f.oneri_durumu == "pr_open":
        return "Onarım PR'ı açık: birleştirme kararı"
    return {
        "test_maintenance": "Test bakımı: locator ya da adım onarımı",
        "flaky": "Kararsız test: takip edin ya da sabitleyin",
        "environment": "Ortam hatası: ortamı inceleyin",
    }.get(f.sinif, "İnceleyin")


def _kosu_grubu(s: Session) -> Grup:
    g = Grup(
        "kosu_hatasi",
        "run",
        yetki.ENGINEER,
        "Başarısız ya da hatalı koşu",
        "Koşuyu açın; kırmızı testlerin triage sonucuna ya da CI günlüğüne bakın",
    )
    sinir = datetime.now(UTC) - timedelta(days=KOSU_GUN)
    q = (
        select(Run)
        .where(
            Run.sonuc.in_(("failed", "error")),
            Run.tetik.notin_(("break_verify", "local_check")),
            Run.olusturma >= sinir,
        )
        .order_by(Run.olusturma.desc(), Run.id)
        .limit(OGE_UST)
    )
    tetik = {"pr": "PR", "push": "Push", "nightly": "Gece", "deploy": "Dağıtım", "manual": "Elle"}
    for r in s.scalars(q):
        ad = tetik.get(r.tetik, r.tetik) + (f" #{r.pr_no}" if r.pr_no else "")
        neden = (
            "Testler koşmadı: CI ortam hatası"
            if r.sonuc == "error"
            else "Kırmızı test var: triage sonucunu inceleyin"
        )
        g.ogeler.append(
            Oge(str(r.id), "run", f"{ad} koşusu", neden, f"/kosular/{r.id}", r.olusturma)
        )
    return g


def kaynaklar(s: Session) -> list[Grup]:
    """Tüm rollerin insan kapıları (sıra: iş akışı sırası)."""
    from tp_core.features.assistant.tools import probe

    rk = probe.REQUIREMENT_KAPILARI
    return [
        _req_grubu(
            s,
            "on_inceleme",
            yetki.ANALYST,
            ("new",),
            "Ön inceleme bekleyen gereksinim",
            "Gereksinimi açın, ön incelemeyi başlatın",
            lambda r: "Kabul kriteri yok: PO'ya sorun" if r.ac_missing else rk["new"].ad,
        ),
        _req_grubu(
            s,
            "bulgu_karari",
            yetki.ANALYST,
            ("findings_open",),
            "Bulgu kararı bekleyen",
            "Tutarlılık bulgularına karar verin (düzelt / kod hatası / bilinçli fark)",
            lambda _r: rk["findings_open"].ad,
        ),
        _req_grubu(
            s,
            "po_gonder",
            yetki.ANALYST,
            ("doc_final",),
            "PO onayına gönderilecek",
            "Doküman son hal: PO teyidi için gönderin",
            lambda _r: rk["doc_final"].ad,
        ),
        _req_grubu(
            s,
            "gereksinim_hata",
            yetki.ANALYST,
            ("failed",),
            "Son işlemi başarısız gereksinim",
            "Hatanın nedenine bakıp yeniden deneyin",
            lambda _r: rk["failed"].ad,
        ),
        _req_grubu(
            s,
            "po_teyidi",
            yetki.PO,
            ("pending_po",),
            "PO teyidi bekleyen",
            "Jira story'sini inceleyip onay etiketini ekleyin (serbest metinde portalda onaylayın)",
            lambda r: (
                "Jira'da onay etiketi bekleniyor"
                if r.kaynak == "jira"
                else "Serbest metin: portalda onaylayın"
            ),
        ),
        _req_grubu(
            s,
            "case_uretimi",
            yetki.TESTER,
            ("po_approved", "model_ready"),
            "Case üretimi bekleyen",
            "Tasarım modelini üretin ya da kararını verin",
            lambda r: rk[r.durum].ad,
        ),
        _case_grubu(
            s,
            "case_karari",
            yetki.TESTER,
            "draft",
            "Case kararı bekleyen",
            "Case review'da kabul / düzelterek kabul / ret kararı verin",
            "{n} case Test Uzmanı kararı bekliyor",
        ),
        _case_grubu(
            s,
            "case_son_onay",
            yetki.ANALYST,
            "ready",
            "Son onay bekleyen case",
            "Case review'da onaylayın ya da gerekçeyle geri gönderin",
            "{n} case Analist son onayı bekliyor",
        ),
        _case_grubu(
            s,
            "case_yayini",
            yetki.TESTER,
            "approved",
            "Yayın bekleyen onaylı case",
            "Yayın önizlemesinden Jira'ya yayınlayın",
            "{n} onaylı case yayın bekliyor",
        ),
        _script_grubu(
            s,
            "kod_insana",
            "blocked",
            "Kod üretiminde insana düşen",
            "Script'i açın; engeli giderin (ör. page object'e metot ekleyin) ya da yeniden üretin",
            probe.SCRIPT_KAPILARI["blocked"].ad,
        ),
        _script_grubu(
            s,
            "acik_pr",
            "pr_open",
            "Açık PR",
            "PR'ı inceleyin, kırarak doğrulayın ve birleştirin",
            probe.SCRIPT_KAPILARI["pr_open"].ad,
        ),
        _script_grubu(
            s,
            "kod_hata",
            "failed",
            "Başarısız kod üretimi",
            "Nedenine bakıp yeniden üretin",
            probe.SCRIPT_KAPILARI["failed"].ad,
        ),
        _hata_grubu(
            s,
            "siniflandirma",
            yetki.TESTER,
            "Sınıflandırma bekleyen hata",
            "Hatayı açın; ürün hatası, test bakımı, veri ya da ortam olarak sınıflandırın",
            Failure.sinif == "unknown",
            _belirsiz_neden,
        ),
        _hata_grubu(
            s,
            "urun_hatasi",
            yetki.TESTER,
            "Bug taslağı açılmamış ürün hatası",
            "Hatayı açın; bug taslağı oluşturun",
            and_(
                Failure.sinif == "product_defect",
                Failure.oneri_turu == "none",
                Failure.oneri_durumu == "none",
            ),
            lambda _f: "Ürün hatası; bug taslağı yok",
        ),
        _hata_grubu(
            s,
            "test_verisi",
            yetki.TESTER,
            "Test verisi sorunu",
            "Test verisi kataloğunu düzeltin ya da veri sahibine iletin",
            and_(Failure.sinif == "test_data", Failure.oneri_durumu.in_(("none", "proposed"))),
            lambda _f: "Test verisi sorunu",
        ),
        _hata_grubu(
            s,
            "test_bakimi",
            yetki.ENGINEER,
            "Test bakımı / ortam hatası",
            "Hatayı açın; otomatik onarımı başlatın ya da ortamı inceleyin",
            and_(
                Failure.sinif.in_(("test_maintenance", "flaky", "environment")),
                Failure.oneri_durumu.in_(("none", "proposed", "pr_open")),
                or_(Failure.alt_tur.is_(None), Failure.alt_tur != "beklenti"),
            ),
            _bakim_neden,
        ),
        _hata_grubu(
            s,
            "beklenti_uyusmazligi",
            yetki.TESTER,
            "Beklentisi uyuşmayan case",
            "Case beklentisini onaylı karar tablosuna göre düzeltin",
            and_(
                Failure.sinif == "test_maintenance",
                Failure.alt_tur == "beklenti",
                Failure.oneri_durumu.in_(("none", "proposed")),
            ),
            lambda _f: "Case beklentisi onaylı karar tablosuyla uyuşmuyor",
        ),
        _bug_grubu(s),
        _kosu_grubu(s),
    ]


def _bug_grubu(s: Session) -> Grup:
    from tp_core.features.assistant.tools import probe

    g = Grup(
        "bug_karari",
        "bug_draft",
        yetki.TESTER,
        "Bug taslağı kararı",
        "Taslağı açın: yeni kayıt, mevcut kayda bağla ya da reddet",
    )
    for b in s.scalars(
        select(BugDraft)
        .where(BugDraft.durum.in_(("draft", "approved")))
        .order_by(BugDraft.olusturma.desc(), BugDraft.id)
    ):
        icerik = b.icerik if isinstance(b.icerik, dict) else {}
        ozet = icerik.get("ozet") or icerik.get("summary") or icerik.get("title") or "Bug taslağı"
        g.ogeler.append(
            Oge(
                str(b.id),
                "bug_draft",
                _kirp(str(ozet), 80),
                probe.BUG_DRAFT_KAPILARI[b.durum].ad,
                f"/bug-taslaklari/{b.id}",
                b.olusturma,
            )
        )
    return g


def _kisiler(s: Session) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ad, rol in s.execute(
        select(AppUser.kullanici_adi, AppUser.rol).order_by(AppUser.kullanici_adi)
    ):
        rol = yetki.normalize_rol(rol)
        if len(out.setdefault(rol, [])) < KISI_UST:
            out[rol].append(ad)
    return out


def is_kuyrugu(s: Session, rol: str) -> dict[str, Any]:
    rol = yetki.normalize_rol(rol)
    gruplar = [g for g in kaynaklar(s) if g.ogeler]
    benim = [g for g in gruplar if g.rol == rol]
    ekip = [g for g in gruplar if g.rol != rol]
    kisiler = _kisiler(s)
    menu: dict[str, int] = dict.fromkeys(MENU_ROTALARI, 0)
    for g in benim:
        menu[TUR_ROTASI[g.tur]] += g.sayi
        menu["/islerim"] += g.sayi

    def ayrinti(g: Grup) -> bool:
        return yetki.izinli(rol, TUR_IZNI[g.tur])

    return {
        "rol": rol,
        "rol_etiketi": yetki.ROL_ETIKETLERI.get(rol, rol),
        "toplam": sum(g.sayi for g in benim),
        "ekip_toplam": sum(g.sayi for g in ekip),
        "benim": [g.json(OGE_UST, ayrinti(g)) for g in benim],
        "ekip": [
            {**g.json(EKIP_OGE_UST, ayrinti(g)), "kisiler": kisiler.get(g.rol, [])} for g in ekip
        ],
        "menu": menu,
    }
