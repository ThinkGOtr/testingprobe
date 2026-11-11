"""Testing Probe verisi araçları: `probe_*` (AI-ASISTAN-PLANI §5.2).

Kaynak, portalın GET uçlarının servis/serileştirme fonksiyonlarıdır (aynı veri, aynı kurallar):

- `probe_get {tur, id_or_key}`: `GET /requirements/{id}`, `/cases/{id}`, `/scripts/{id}`,
  `/runs/{id}`, `/failures/{id}`, `/bug-drafts/{id}` (+ yalnız analistte `GET /publish/preview`).
- `probe_list {tur, durum?, limit≤20}`: `GET /requirements`, `/cases`, `/scripts`, `/runs`,
  `/failures`, `/bug-drafts` (kısa satırlar).
- `probe_jobs {varlik_id}`: varlığın son 10 işi (`workflow_instance.nesne_id` / iş yükü).
- `probe_audit {varlik_id, limit≤20}`: `GET /audit?nesne=` + varlığın kararları (`review`) ve AI
  çağrıları (`ai_call`) özeti.
- `probe_my_queue {}`: çağıranın rolüne düşen bekleyen işler (`APPROVER_ROLES` + durum makineleri).

- **Rol** yalnızca `AracBaglami.rol`'den (oturum); argümanda rol yoktur. Uç-düzeyi rol kısıtları
  `UC_ROLLERI`'nde aynen tutulur (ör. `GET /publish/preview` yalnız analist): kısıtlı uca dayanan
  bölüm başka role **hiç** dönmez (alan adı dahil).
- **Alan izin listesi:** serileştiricinin çıktısından yalnız `*_ALANLARI` kümelerindeki alanlar
  alınır. Token/parola/oturum alanları, `*_url` bağlantıları (modele URL gitmez; §7.3), içerik
  hash'leri ve kişi adları (karar veren, onaylayan, isteyen) listeye girmez.
- Araçlar ham metin döndürür; sır temizleme, maskeleme, kanıt kimliği ve `<untrusted>` sarma ortak
  sarmalayıcıdadır (`tools.base`, §5.0). Kayıt yoksa ya da rol kısıtlıysa `AracHatasi`.

Öneri motoru (Şerit R) varlık erişimini buradan kullanır: `varlik_bul` (yoksa/rolüne kapalıysa
`VarlikBulunamadi`) ve `bekleyen_isler` (ekran dışı "sizi bekleyen N iş" sayımı).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.orm import Session

from tp_core.features.assistant.tools.base import (
    AracBaglami,
    AracHatasi,
    AracSonucu,
    kesik_temizle,
)
from tp_core.models import (
    AiCall,
    AuditEvent,
    BugDraft,
    ExternalRef,
    Failure,
    Job,
    Requirement,
    Review,
    Run,
    Script,
    TestCase,
    WorkflowInstance,
)
from tp_core.models.codegen_feature import ScriptCodegen
from tp_core.models.enums import FAILURE_SINIF, RUN_SONUC
from tp_core.ports import ToolSpec
from tp_core.workflow.states import MACHINES

TURLER: tuple[str, ...] = ("requirement", "case", "script", "run", "failure", "bug_draft")
# Araç türü → durum makinesi / tablo adı (audit `nesne` öneki, review `nesne_turu`).
TABLO: dict[str, str] = {
    "requirement": "requirement",
    "case": "test_case",
    "script": "script",
    "run": "run",
    "failure": "failure",
    "bug_draft": "bug_draft",
}
MODELLER: dict[str, Any] = {
    "requirement": Requirement,
    "case": TestCase,
    "script": Script,
    "run": Run,
    "failure": Failure,
    "bug_draft": BugDraft,
}

ROL_ETIKETI: dict[str, str] = {
    "analyst": "Analist",
    "engineer": "Mühendis",
    "presenter": "Sunucu",
    "po": "Ürün sahibi (PO)",
    "tester": "Testçi",
}
SISTEM = "sistem"

# Uç → izinli roller (None = oturum açmış her rol). Kaynak: ilgili router'daki `require_role`;
# hizalama testi FastAPI rotalarından okur (test_probe_tools::test_uc_rolleri_routerla_ayni).
UC_ROLLERI: dict[str, frozenset[str] | None] = {
    "GET /requirements": None,
    "GET /requirements/{req_id}": None,
    "GET /cases": None,
    "GET /cases/{case_id}": None,
    "GET /scripts": None,
    "GET /scripts/{script_id}": None,
    "GET /runs": None,
    "GET /runs/{run_id}": None,
    "GET /failures": None,
    "GET /failures/{failure_id}": None,
    "GET /bug-drafts": None,
    "GET /bug-drafts/{draft_id}": None,
    "GET /publish/preview": frozenset({"analyst"}),
    "GET /audit": None,
}
DETAY_UCU: dict[str, str] = {
    "requirement": "GET /requirements/{req_id}",
    "case": "GET /cases/{case_id}",
    "script": "GET /scripts/{script_id}",
    "run": "GET /runs/{run_id}",
    "failure": "GET /failures/{failure_id}",
    "bug_draft": "GET /bug-drafts/{draft_id}",
}
LISTE_UCU: dict[str, str] = {
    "requirement": "GET /requirements",
    "case": "GET /cases",
    "script": "GET /scripts",
    "run": "GET /runs",
    "failure": "GET /failures",
    "bug_draft": "GET /bug-drafts",
}

LISTE_UST = 20
IS_UST = 10
DENETIM_UST = 20
KUYRUK_UST = 20
METIN_UST = 300  # serbest metin alanları (başlık, hata, uyarı) kırpılır
LISTE_ALAN_UST = 8  # liste alanlarında en çok öğe
JIRA_ANAHTARI = re.compile(r"[A-Z][A-Z0-9]+-[0-9]+")

# ----------------------------------------------------------------- alan izin listeleri
# Serileştirici çıktısından yalnız bu alanlar alınır (iç içe sözlüklerde nokta ile yol).

REQUIREMENT_ALANLARI = (
    "id",
    "jira_key",
    "kaynak",
    "baslik",
    "durum",
    "ac_missing",
    "kabul_kriterleri",
    "po.durum",
    "po.kanal",
    "po.zaman",
    "sayaclar",
    "kontrol_turu",
    "kontrol_turu_ust_sinir",
    "insan_karari_gerekli",
    "denetim_guvenilmez",
    "uyarilar",
    "bulgu_sayaclari",
    "son_hata",
    "po_istegi.durum",
    "on_inceleme.verdict",
    "on_inceleme.durum",
)
CASE_ALANLARI = (
    "id",
    "requirement_id",
    "jira_key",
    "sira_no",
    "uretim_no",
    "kanal",
    "surum",
    "durum",
    "icerik.title",
    "icerik.type",
    "icerik.risk",
    "karar",
    "ret_nedeni",
    "jira_test_key",
    "mode",
    "uyarilar",
    "onceki_icerik",
)
SCRIPT_ALANLARI = (
    "id",
    "requirement_id",
    "requirement_key",
    "case_ref",
    "test_key",
    "baslik",
    "dosya_yolu",
    "durum",
    "failure_id",
    "pr.number",
    "pr.durum",
    "pr.ci",
    "pr.checks",
    "pr.dal.geride",
    "pass_at_1",
    "zayif_test",
    "break_verify.durum",
    "break_verify.neden",
    "break_verify.asamalar",
    "yerel_sinif",
    "mode",
    "engel",
    "hata",
)
RUN_ALANLARI = (
    "id",
    "kaynak",
    "tetik",
    "sonuc",
    "commit",
    "pr_no",
    "baslangic",
    "bitis",
    "sure_ms",
    "toplam",
    "gecen",
    "basarisiz",
    "flaky",
    "atlanan",
    "saglik_hatasi",
    "hata",
    "ozet",
    "script_id",
    "github_run_id",
    "artefakt_budandi",
    "github_artefakt",
)
FAILURE_ALANLARI = (
    "id",
    "run_id",
    "test_adi",
    "hata_mesaji",
    "sinif",
    "alt_tur",
    "karar_kaynagi",
    "kural",
    "gerekce",
    "oneri_turu",
    "oneri_durumu",
    "oneri_yok_nedeni",
    "bug_draft_id",
    "mode",
    "zaman",
    "script_id",
    "kaynak",
    "kirma",
    "jira_yazilmaz",
    "commit",
    "tetik",
    "pr_no",
    "kanit.hata_turu",
    "kanit.adim",
    "kanit.konum",
    "kanit.beklenen",
    "kanit.gerceklesen",
)
BUG_DRAFT_ALANLARI = (
    "id",
    "kaynak",
    "failure_id",
    "finding_id",
    "requirement_id",
    "icerik.ozet",
    "icerik.summary",
    "icerik.title",
    "karar",
    "durum",
    "link_key",
    "jira_key",
    "jira_silindi",
    "mode",
    "olusturma",
    "hazirlik.durum",
    "hazirlik.hata",
    "sonuc_metni",
    "ilgili_failure_ids",
    "mukerrer_aramasi_yapildi",
)
DETAY_ALANLARI: dict[str, tuple[str, ...]] = {
    "requirement": REQUIREMENT_ALANLARI,
    "case": CASE_ALANLARI,
    "script": SCRIPT_ALANLARI,
    "run": RUN_ALANLARI,
    "failure": FAILURE_ALANLARI,
    "bug_draft": BUG_DRAFT_ALANLARI,
}
# Değeri hiçbir koşulda modele gitmeyen alan adı parçaları (izin listesine yanlışlıkla girse de).
YASAK_ALAN = re.compile(
    r"token|parola|password|sifre|şifre|secret|oturum|session|cookie|_url$|^url$|hash",
    re.IGNORECASE,
)

# ----------------------------------------------------------------- bekleyen kapı / sorumlu


@dataclass(frozen=True)
class Kapi:
    ad: str
    rol: str  # ROL_ETIKETI anahtarı veya SISTEM


REQUIREMENT_KAPILARI: dict[str, Kapi] = {
    "new": Kapi("İncelemeye alınmalı (ön inceleme + tutarlılık denetimi)", "analyst"),
    "in_review": Kapi("Denetim sürüyor", SISTEM),
    "findings_open": Kapi("Tutarlılık bulguları analist kararı bekliyor", "analyst"),
    "doc_final": Kapi("Doküman son hal; PO onayına gönderilmeli", "analyst"),
    "pending_po": Kapi("PO onayı bekleniyor", "po"),
    "po_approved": Kapi("PO onayladı; case üretimi başlatılmalı", "analyst"),
    "generating": Kapi("Case üretimi sürüyor", SISTEM),
    "cases_ready": Kapi("Case incelemesi ve yayın", "analyst"),
    "failed": Kapi("Son işlem başarısız; neden incelenip yeniden denenmeli", "analyst"),
}
CASE_KAPILARI: dict[str, Kapi] = {
    "draft": Kapi("Case kararı bekleniyor (onay / düzelt / ret)", "analyst"),
    "approved": Kapi("Onaylı; Jira'ya yayın bekleniyor", "analyst"),
}
SCRIPT_KAPILARI: dict[str, Kapi] = {
    "pending": Kapi("Kod üretimi kuyrukta", SISTEM),
    "verifying": Kapi("Ajan doğrulaması sürüyor", SISTEM),
    "checking": Kapi("Yerel kontroller sürüyor", SISTEM),
    "pr_open": Kapi("PR açık: kırarak doğrulama ve merge kararı", "engineer"),
    "blocked": Kapi("Üretim insana düştü; engel incelenmeli", "engineer"),
    "failed": Kapi("Üretim başarısız; yeniden denenmeli", "engineer"),
}
RUN_KAPILARI: dict[str, Kapi] = {
    "queued": Kapi("Koşu kuyrukta", SISTEM),
    "running": Kapi("Koşu sürüyor", SISTEM),
    "failed": Kapi("Kırmızı testlerin triage sonucu incelenmeli", "engineer"),
    "error": Kapi("Testler koşmadı: CI ortam hatası incelenmeli", "engineer"),
}
BUG_DRAFT_KAPILARI: dict[str, Kapi] = {
    "draft": Kapi("Bug taslağı kararı bekleniyor (yeni / bağla / kapat)", "tester"),
    "approved": Kapi("Onaylı; Jira'ya yayın bekleniyor", "tester"),
}


def _failure_kapisi(f: Failure) -> Kapi | None:
    if f.oneri_durumu in ("merged", "rejected"):
        return None
    if f.sinif == "test_maintenance":
        if f.alt_tur == "beklenti":  # 012 §4.4: onarım/bug yok; case düzeltilir
            return Kapi(
                "Case beklentisi onaylı karar tablosuyla uyuşmuyor; case düzeltilmeli", "analyst"
            )
        if f.oneri_durumu == "pr_open":
            return Kapi("Onarım PR'ı açık; merge kararı", "engineer")
        return Kapi("Bakım hatası; otomatik onarım başlatılabilir", "engineer")
    if f.sinif == "product_defect":
        return Kapi("Ürün hatası; bug taslağı kararı", "tester")
    if f.sinif == "test_data":
        return Kapi("Test verisi sorunu; veri sahibine iletilmeli", "tester")
    if f.sinif == "flaky":
        return Kapi("Kararsız test; takip edilmeli", "engineer")
    if f.sinif == "environment":
        return Kapi("Ortam hatası; ortam incelenmeli", "engineer")
    return Kapi("Sınıflandırılamadı; elle incelenmeli", "engineer")


def _rol_metni(rol: str) -> str:
    if rol == SISTEM:
        return "sistem (otomatik iş; insan beklemiyor)"
    return f"{rol} ({ROL_ETIKETI.get(rol, rol)})"


# ----------------------------------------------------------------- erişim


class VarlikBulunamadi(AracHatasi):
    """Kayıt yok ya da çağıranın rolüne kapalı (API karşılığı 404)."""


def uc_izinli(rol: str, uc: str) -> bool:
    if uc not in UC_ROLLERI:
        return False
    izinli = UC_ROLLERI[uc]
    return izinli is None or rol in izinli


def _uc_kontrol(rol: str, uc: str) -> None:
    if not uc_izinli(rol, uc):
        roller = UC_ROLLERI.get(uc) or frozenset()
        kim = ", ".join(ROL_ETIKETI.get(r, r) for r in sorted(roller)) or "hiçbir rol"
        raise AracHatasi(f"Bu bilgi rolünüze açık değil ({uc}: yalnız {kim})")


def _uuid(deger: Any) -> uuid.UUID | None:
    if isinstance(deger, uuid.UUID):
        return deger
    if not isinstance(deger, str):
        return None
    try:
        return uuid.UUID(deger.strip())
    except ValueError:
        return None


def _tur_arg(tur: Any) -> str:
    if not isinstance(tur, str) or tur not in TURLER:
        raise AracHatasi(f"'tur' şunlardan biri olmalı: {', '.join(TURLER)}")
    return tur


def varlik_bul(session: Session, rol: str, tur: str, id_or_key: Any) -> Any:
    """`probe_get` ile aynı kural: UUID ya da (requirement/bug_draft/case/script için) anahtar.

    Kayıt yoksa ya da detay ucu rolüne kapalıysa `VarlikBulunamadi`.
    """
    tur = _tur_arg(tur)
    if not uc_izinli(rol, DETAY_UCU[tur]):
        raise VarlikBulunamadi(f"{tur} bulunamadı")
    model = MODELLER[tur]
    kimlik = _uuid(id_or_key)
    if kimlik is not None:
        nesne = session.get(model, kimlik)
        if nesne is None:
            raise VarlikBulunamadi(f"{tur} bulunamadı: {kimlik}")
        return nesne
    anahtar = id_or_key.strip() if isinstance(id_or_key, str) else ""
    if not anahtar or not JIRA_ANAHTARI.fullmatch(anahtar):
        raise VarlikBulunamadi(f"{tur} için geçerli bir kimlik (UUID) ya da Jira anahtarı verin")
    nesne = None
    if tur == "requirement":
        nesne = session.scalars(select(Requirement).where(Requirement.jira_key == anahtar)).first()
    elif tur == "bug_draft":
        nesne = session.scalars(select(BugDraft).where(BugDraft.jira_key == anahtar)).first()
    elif tur == "case":
        ref = session.scalars(
            select(ExternalRef.entity_id).where(
                ExternalRef.entity_turu == "test_case",
                ExternalRef.external_key == anahtar,
                ExternalRef.durum == "created",
            )
        ).first()
        nesne = session.get(TestCase, ref) if ref is not None else None
    elif tur == "script":
        sid = session.scalars(
            select(ScriptCodegen.script_id)
            .where(ScriptCodegen.test_key == anahtar)
            .order_by(ScriptCodegen.script_id)
        ).first()
        nesne = session.get(Script, sid) if sid is not None else None
    if nesne is None:
        raise VarlikBulunamadi(f"{tur} bulunamadı: {anahtar}")
    return nesne


def _varlik_turu(session: Session, varlik_id: uuid.UUID) -> str | None:
    for tur in TURLER:
        if session.get(MODELLER[tur], varlik_id) is not None:
            return tur
    return None


# ----------------------------------------------------------------- biçimleme


def _kirp(deger: str, ust: int = METIN_UST) -> str:
    deger = " ".join(deger.split())
    return deger if len(deger) <= ust else kesik_temizle(deger[: ust - 1]) + "…"


def _deger_metni(deger: Any) -> str:
    if deger is None:
        return "-"
    if isinstance(deger, bool):
        return "evet" if deger else "hayır"
    if isinstance(deger, int | float):
        return str(deger)
    if isinstance(deger, str):
        return _kirp(deger)
    if hasattr(deger, "isoformat"):
        return str(deger.isoformat())
    if isinstance(deger, Mapping):
        parcalar = [
            f"{k}={_deger_metni(v)}"
            for k, v in list(deger.items())[:LISTE_ALAN_UST]
            if not YASAK_ALAN.search(str(k)) and v not in (None, "", [], {})
        ]
        return "{" + ", ".join(parcalar) + "}" if parcalar else "-"
    if isinstance(deger, list | tuple):
        ogeler = [_deger_metni(v) for v in list(deger)[:LISTE_ALAN_UST]]
        ek = f" … (+{len(deger) - LISTE_ALAN_UST})" if len(deger) > LISTE_ALAN_UST else ""
        return ("; ".join(ogeler) + ek) if ogeler else "-"
    return _kirp(str(deger))


def _yol(veri: Mapping[str, Any], yol: str) -> tuple[bool, Any]:
    simdiki: Any = veri
    for parca in yol.split("."):
        if not isinstance(simdiki, Mapping) or parca not in simdiki:
            return False, None
        simdiki = simdiki[parca]
    return True, simdiki


def alanlari_sec(veri: Mapping[str, Any], alanlar: Iterable[str]) -> dict[str, Any]:
    """İzin listesindeki alanlar (nokta ile iç içe yol); yasak ad parçası taşıyan alan asla."""
    out: dict[str, Any] = {}
    for alan in alanlar:
        if any(YASAK_ALAN.search(p) for p in alan.split(".")):
            continue
        var, deger = _yol(veri, alan)
        if var:
            out[alan] = deger
    return out


def _satirlar(baslik: str, alanlar: Mapping[str, Any]) -> list[str]:
    satirlar = [baslik]
    for k, v in alanlar.items():
        satirlar.append(f"{k}: {_deger_metni(v)}")
    return satirlar


# ----------------------------------------------------------------- detay serileştirme


def _requirement_ham(s: Session, req: Requirement) -> dict[str, Any]:
    from tp_core.features.requirements import serialize

    return serialize.requirement_detail(s, req)


def _po_cevaplari_ozeti(req: Requirement) -> list[str]:
    out = []
    for c in (req.po_cevaplari or [])[:5]:
        metin = c.get("metin") if isinstance(c, Mapping) else c
        if isinstance(metin, str) and metin.strip():
            out.append(_kirp(metin, 400))
    return out


def _yayin_onizleme_ozeti(s: Session, req: Requirement) -> list[str]:
    """`GET /publish/preview` özeti (yalnız analist; çağıran `_uc_kontrol` ile denetler)."""
    from tp_core.features.publish import service as publish_service

    try:
        on = publish_service.preview(s, req.id)
    except Exception as exc:
        return [f"yayın önizlemesi alınamadı ({type(exc).__name__})"]
    sayac: dict[str, int] = {}
    for k in on.get("kalemler") or []:
        islem = str(k.get("islem") or "?") if isinstance(k, Mapping) else "?"
        sayac[islem] = sayac.get(islem, 0) + 1
    satirlar = [
        "yayin_onizleme.islemler: "
        + (", ".join(f"{k}={v}" for k, v in sorted(sayac.items())) or "kalem yok")
    ]
    uyarilar = [str(u) for u in on.get("uyarilar") or []]
    if uyarilar:
        satirlar.append(f"yayin_onizleme.uyarilar: {_deger_metni(uyarilar)}")
    return satirlar


def _ekran_rotasi(tur: str, nesne: Any) -> str:
    if tur == "requirement":
        return f"/gereksinimler/{nesne.id}"
    if tur == "case":
        return f"/gereksinimler/{nesne.requirement_id}/caseler"
    if tur == "script":
        return f"/kod/{nesne.id}"
    if tur == "run":
        return f"/kosular/{nesne.id}"
    if tur == "failure":
        return f"/hatalar/{nesne.id}"
    return f"/bug-taslaklari/{nesne.id}"


def _kapi(tur: str, nesne: Any) -> Kapi | None:
    if tur == "requirement":
        return REQUIREMENT_KAPILARI.get(nesne.durum)
    if tur == "case":
        return CASE_KAPILARI.get(nesne.durum)
    if tur == "script":
        return SCRIPT_KAPILARI.get(nesne.durum)
    if tur == "run":
        return RUN_KAPILARI.get(nesne.sonuc)
    if tur == "failure":
        return _failure_kapisi(nesne)
    return BUG_DRAFT_KAPILARI.get(nesne.durum)


def _detay_ham(s: Session, tur: str, nesne: Any) -> dict[str, Any]:
    if tur == "requirement":
        return _requirement_ham(s, nesne)
    if tur == "case":
        from tp_core.features.cases import service as cases_service

        return cases_service.serialize_cases(s, [nesne])[0]
    if tur == "script":
        from tp_core.features.codegen import views

        cift = views.get_pair(s, nesne.id)
        if cift is None:
            return {"id": str(nesne.id), "durum": nesne.durum, "dosya_yolu": nesne.dosya_yolu}
        return views.serialize(s, *cift)
    if tur == "run":
        from tp_core.features.ci import service as ci_service

        return ci_service.serialize_runs(s, [nesne])[0]
    if tur == "failure":
        from tp_core.features.triage import service as triage_service

        return triage_service.get_failure(s, nesne.id) or {}
    from tp_core.features.bugs import serialize as bugs_serialize

    return bugs_serialize.bug_draft_view(s, nesne)


def _son_hata(s: Session, tur: str, nesne: Any, ham: Mapping[str, Any]) -> str | None:
    if tur == "requirement":
        sh = ham.get("son_hata")
        if isinstance(sh, Mapping):
            return _kirp(f"{sh.get('neden') or ''} — {sh.get('oneri') or ''}".strip(" —"))
        return None
    if tur == "script":
        return ham.get("hata") or None
    if tur == "run":
        return ham.get("hata") or ham.get("saglik_hatasi") or None
    if tur == "failure":
        return ham.get("hata_mesaji") or None
    if tur == "bug_draft":
        hz = ham.get("hazirlik") if isinstance(ham.get("hazirlik"), Mapping) else {}
        return hz.get("hata") or None
    return None


def probe_detay(s: Session, rol: str, tur: str, nesne: Any) -> list[str]:
    """`probe_get` gövdesi (satırlar). Öneri motoru aynı veriyi buradan okuyabilir."""
    _uc_kontrol(rol, DETAY_UCU[tur])
    ham = _detay_ham(s, tur, nesne)
    alanlar = alanlari_sec(ham, DETAY_ALANLARI[tur])
    satirlar = _satirlar(f"{tur} {nesne.id}", alanlar)
    kapi = _kapi(tur, nesne)
    satirlar.append(f"bekleyen_kapi: {kapi.ad if kapi else '-'}")
    satirlar.append(f"sorumlu_rol: {_rol_metni(kapi.rol) if kapi else '-'}")
    son_hata = _son_hata(s, tur, nesne, ham)
    satirlar.append(f"son_hata: {_deger_metni(son_hata)}")
    satirlar.append(f"ekran_rotasi: {_ekran_rotasi(tur, nesne)}")
    if tur == "requirement":
        cevaplar = _po_cevaplari_ozeti(nesne)
        satirlar.append(f"po_cevaplari_ozeti: {_deger_metni(cevaplar) if cevaplar else '-'}")
        if uc_izinli(rol, "GET /publish/preview"):
            satirlar += _yayin_onizleme_ozeti(s, nesne)
    return satirlar


# ----------------------------------------------------------------- liste


def _durumlar(tur: str) -> frozenset[str]:
    if tur == "run":
        return RUN_SONUC
    if tur == "failure":
        return FAILURE_SINIF
    return MACHINES[TABLO[tur]].states


def _limit(deger: Any, ust: int, varsayilan: int) -> int:
    if deger is None:
        return varsayilan
    if isinstance(deger, bool):
        raise AracHatasi("'limit' tam sayı olmalı")
    try:
        sayi = int(deger)
    except (TypeError, ValueError) as exc:
        raise AracHatasi("'limit' tam sayı olmalı") from exc
    if sayi < 1:
        raise AracHatasi("'limit' en az 1")
    return min(sayi, ust)


def _liste_satiri(s: Session, tur: str, n: Any) -> str:
    if tur == "requirement":
        etiket = f"{n.jira_key or 'serbest'} · {_kirp(n.baslik, 80)}"
        durum = n.durum
    elif tur == "case":
        baslik = (n.icerik or {}).get("title") if isinstance(n.icerik, Mapping) else None
        etiket = f"C{n.sira_no} · {_kirp(str(baslik or '-'), 80)}"
        durum = n.durum
    elif tur == "script":
        etiket = n.dosya_yolu
        durum = n.durum
    elif tur == "run":
        etiket = f"{n.kaynak}/{n.tetik}"
        durum = n.sonuc
    elif tur == "failure":
        etiket = _kirp(n.test_adi, 80)
        durum = f"{n.sinif}/{n.oneri_durumu}"
    else:
        icerik = n.icerik if isinstance(n.icerik, Mapping) else {}
        baslik = icerik.get("ozet") or icerik.get("summary") or icerik.get("title")
        etiket = f"{n.jira_key or '-'} · {_kirp(str(baslik or '-'), 80)}"
        durum = n.durum
    return f"- {n.id} | {durum} | {etiket} | {_ekran_rotasi(tur, n)}"


def _liste_sorgusu(tur: str, durum: str | None) -> Any:
    model = MODELLER[tur]
    q = select(model)
    if durum is not None:
        if tur == "run":
            q = q.where(Run.sonuc == durum)
        elif tur == "failure":
            q = q.where(Failure.sinif == durum)
        else:
            q = q.where(model.durum == durum)
    return q.order_by(model.olusturma.desc(), model.id)


# ----------------------------------------------------------------- bekleyen işler


@dataclass(frozen=True)
class BekleyenIs:
    tur: str
    id: uuid.UUID
    neden: str
    rota: str
    etiket: str


def _kuyruk_kaynaklari(rol: str) -> list[tuple[str, Any, Callable[[Any], str]]]:
    """(tür, sorgu, neden) — rolün kapısındaki varlıklar (APPROVER_ROLES + durum makineleri)."""
    out: list[tuple[str, Any, Callable[[Any], str]]] = []
    if rol == "analyst":
        for durum in ("findings_open", "doc_final", "po_approved", "cases_ready", "failed", "new"):
            out.append(
                (
                    "requirement",
                    select(Requirement).where(Requirement.durum == durum),
                    lambda _n, d=durum: REQUIREMENT_KAPILARI[d].ad,
                )
            )
        out.append(
            (
                "case",
                select(TestCase).where(TestCase.durum == "draft"),
                lambda _n: CASE_KAPILARI["draft"].ad,
            )
        )
    elif rol == "po":
        out.append(
            (
                "requirement",
                select(Requirement).where(Requirement.durum == "pending_po"),
                lambda n: (
                    "PO onayı bekleniyor"
                    + (" (Jira'da etiketle)" if n.kaynak == "jira" else " (portalda)")
                ),
            )
        )
    elif rol == "engineer":
        for durum in ("pr_open", "blocked", "failed"):
            out.append(
                (
                    "script",
                    select(Script).where(Script.durum == durum),
                    lambda _n, d=durum: SCRIPT_KAPILARI[d].ad,
                )
            )
        out.append(
            (
                "failure",
                select(Failure).where(
                    Failure.sinif.in_(("test_maintenance", "flaky", "environment", "unknown")),
                    Failure.oneri_durumu.in_(("none", "proposed", "pr_open")),
                ),
                lambda n: (_failure_kapisi(n) or Kapi("-", "engineer")).ad,
            )
        )
        out.append(
            ("run", select(Run).where(Run.sonuc == "error"), lambda _n: RUN_KAPILARI["error"].ad)
        )
    elif rol == "tester":
        out.append(
            (
                "bug_draft",
                select(BugDraft).where(BugDraft.durum.in_(("draft", "approved"))),
                lambda n: BUG_DRAFT_KAPILARI[n.durum].ad,
            )
        )
        out.append(
            (
                "failure",
                select(Failure).where(
                    Failure.sinif == "test_data", Failure.oneri_durumu.in_(("none", "proposed"))
                ),
                lambda n: (_failure_kapisi(n) or Kapi("-", "tester")).ad,
            )
        )
    elif rol == "presenter":
        out.append(
            (
                "run",
                select(Run).where(Run.sonuc == "error"),
                lambda _n: "Koşu ortam hatasıyla bitti; mühendis inceliyor",
            )
        )
    return out


def _etiket(tur: str, n: Any) -> str:
    if tur == "requirement":
        return f"{n.jira_key or 'serbest'} · {_kirp(n.baslik, 60)}"
    if tur == "case":
        baslik = (n.icerik or {}).get("title") if isinstance(n.icerik, Mapping) else None
        return f"C{n.sira_no} · {_kirp(str(baslik or '-'), 60)}"
    if tur == "script":
        return n.dosya_yolu
    if tur == "run":
        return f"{n.kaynak}/{n.tetik}"
    if tur == "failure":
        return _kirp(n.test_adi, 60)
    return n.jira_key or str(n.id)


def bekleyen_isler(
    session: Session, rol: str, *, en_cok: int = KUYRUK_UST
) -> tuple[int, list[BekleyenIs]]:
    """(toplam, ilk `en_cok` iş) — çağıranın rolüne düşen bekleyen işler."""
    toplam = 0
    isler: list[BekleyenIs] = []
    for tur, sorgu, neden in _kuyruk_kaynaklari(rol):
        model = MODELLER[tur]
        toplam += int(session.scalar(select(func.count()).select_from(sorgu.subquery())) or 0)
        kalan = en_cok - len(isler)
        if kalan <= 0:
            continue
        for n in session.scalars(sorgu.order_by(model.olusturma.desc(), model.id).limit(kalan)):
            isler.append(BekleyenIs(tur, n.id, neden(n), _ekran_rotasi(tur, n), _etiket(tur, n)))
    return toplam, isler


def kuyrukta_mi(session: Session, rol: str, tur: str, kimlik: uuid.UUID) -> bool:
    """Varlık rolün bekleyen işlerinden biri mi (`bekleyen_isler` ile aynı kaynaklar)."""
    model = MODELLER.get(tur)
    if model is None:
        return False
    for kaynak_tur, sorgu, _neden in _kuyruk_kaynaklari(rol):
        if kaynak_tur == tur and session.scalar(
            select(func.count()).select_from(sorgu.where(model.id == kimlik).subquery())
        ):
            return True
    return False


# ----------------------------------------------------------------- araçlar


def _db(baglam: AracBaglami) -> Session:
    return baglam.db()


def _bilinmeyen(arg: Mapping[str, Any], izinli: Iterable[str]) -> None:
    fazla = sorted(set(arg) - set(izinli))
    if fazla:
        raise AracHatasi(f"bilinmeyen argüman: {', '.join(fazla)[:80]}")


def probe_get(baglam: AracBaglami, **arg: Any) -> AracSonucu:
    _bilinmeyen(arg, ("tur", "id_or_key"))
    tur = _tur_arg(arg.get("tur"))
    with _db(baglam) as s:
        nesne = varlik_bul(s, baglam.rol, tur, arg.get("id_or_key"))
        satirlar = probe_detay(s, baglam.rol, tur, nesne)
    return AracSonucu(
        "\n".join(satirlar),
        kanit_turu="probe_verisi",
        tur="data",
        kaynak=f"{tur}:{nesne.id}",
        meta={"tur": tur, "id": str(nesne.id)},
    )


def probe_list(baglam: AracBaglami, **arg: Any) -> AracSonucu:
    _bilinmeyen(arg, ("tur", "durum", "limit"))
    tur = _tur_arg(arg.get("tur"))
    _uc_kontrol(baglam.rol, LISTE_UCU[tur])
    durum = arg.get("durum")
    if durum is not None and (not isinstance(durum, str) or durum not in _durumlar(tur)):
        gecerli = ", ".join(sorted(_durumlar(tur)))
        raise AracHatasi(f"'durum' {tur} için şunlardan biri olmalı: {gecerli}")
    limit = _limit(arg.get("limit"), LISTE_UST, 10)
    with _db(baglam) as s:
        sorgu = _liste_sorgusu(tur, durum)
        toplam = int(s.scalar(select(func.count()).select_from(sorgu.subquery())) or 0)
        satirlar = [_liste_satiri(s, tur, n) for n in s.scalars(sorgu.limit(limit))]
    ust = f"{tur} listesi" + (f" (durum={durum})" if durum else "") + f": {toplam} kayıt"
    if toplam > len(satirlar):
        ust += f", ilk {len(satirlar)} gösteriliyor"
    govde = [ust, "kimlik | durum | etiket | ekran", *satirlar] if satirlar else [ust]
    return AracSonucu("\n".join(govde), kaynak=f"{tur}-liste", meta={"tur": tur})


def _varlik_id_arg(arg: Mapping[str, Any]) -> uuid.UUID:
    vid = _uuid(arg.get("varlik_id"))
    if vid is None:
        raise AracHatasi("'varlik_id' UUID olmalı")
    return vid


def _erisilebilir_varlik(s: Session, rol: str, vid: uuid.UUID) -> str:
    tur = _varlik_turu(s, vid)
    if tur is None or not uc_izinli(rol, DETAY_UCU[tur]):
        raise VarlikBulunamadi(f"varlık bulunamadı: {vid}")
    return tur


def _kisa_hata(metin: str | None) -> str:
    if not metin:
        return "-"
    ilk = metin.strip().splitlines()[0] if metin.strip() else ""
    return _kirp(ilk, 160) or "-"


def probe_jobs(baglam: AracBaglami, **arg: Any) -> AracSonucu:
    _bilinmeyen(arg, ("varlik_id",))
    vid = _varlik_id_arg(arg)
    with _db(baglam) as s:
        tur = _erisilebilir_varlik(s, baglam.rol, vid)
        akislar = select(WorkflowInstance.id).where(WorkflowInstance.nesne_id == vid)
        isler = s.scalars(
            select(Job)
            .where(
                or_(
                    Job.workflow_id.in_(akislar),
                    cast(Job.yuk, Text).contains(str(vid)),
                )
            )
            .order_by(Job.olusturma.desc(), Job.id)
            .limit(IS_UST)
        ).all()
        satirlar = [f"{tur} {vid} için son {IS_UST} iş: {len(isler)} kayıt"]
        for j in isler:
            satirlar.append(
                f"- {j.tur} | {j.durum} | deneme {j.deneme} | "
                f"{(j.bitis or j.olusturma).isoformat()} | hata: {_kisa_hata(j.son_hata)}"
            )
    return AracSonucu("\n".join(satirlar), kaynak=f"{tur}:{vid}:isler", meta={"id": str(vid)})


def _ozet_metni(ozet: Any) -> str:
    if not isinstance(ozet, Mapping):
        return "-"
    parcalar = []
    for k, v in list(ozet.items())[:6]:
        if YASAK_ALAN.search(str(k)) or isinstance(v, Mapping | list):
            continue
        parcalar.append(f"{k}={_kirp(_deger_metni(v), 60)}")
    return ", ".join(parcalar) or "-"


def probe_audit(baglam: AracBaglami, **arg: Any) -> AracSonucu:
    _bilinmeyen(arg, ("varlik_id", "limit"))
    vid = _varlik_id_arg(arg)
    limit = _limit(arg.get("limit"), DENETIM_UST, 10)
    _uc_kontrol(baglam.rol, "GET /audit")
    with _db(baglam) as s:
        tur = _erisilebilir_varlik(s, baglam.rol, vid)
        nesne = s.get(MODELLER[tur], vid)
        olaylar = s.scalars(
            select(AuditEvent)
            .where(AuditEvent.nesne == f"{TABLO[tur]}:{vid}")
            .order_by(AuditEvent.id.desc())
            .limit(limit)
        ).all()
        satirlar = [f"{tur} {vid} denetim izi (yeniden eskiye, en çok {limit}):"]
        for o in olaylar:
            satirlar.append(f"- {o.zaman.isoformat()} | {o.eylem} | {_ozet_metni(o.ozet)}")
        if not olaylar:
            satirlar.append("- kayıt yok")
        kararlar = s.scalars(
            select(Review)
            .where(Review.nesne_turu == TABLO[tur], Review.nesne_id == vid)
            .order_by(Review.sira.desc())
            .limit(limit)
        ).all()
        if kararlar:
            satirlar.append("kararlar (onay/ret):")
            for r in kararlar:
                ek = f", ret nedeni: {r.ret_nedeni}" if r.ret_nedeni else ""
                satirlar.append(f"- {r.zaman.isoformat()} | {r.karar} | kanal: {r.kanal}{ek}")
        cagri_idleri = [c for c in [getattr(nesne, "ai_call_id", None)] if isinstance(c, uuid.UUID)]
        if tur == "script":
            cg = s.get(ScriptCodegen, vid)
            for c in (cg.ai_call_ids if cg is not None else []) or []:
                cid = _uuid(c)
                if cid is not None:
                    cagri_idleri.append(cid)
        if cagri_idleri:
            cagrilar = s.scalars(
                select(AiCall)
                .where(AiCall.id.in_(cagri_idleri[:limit]))
                .order_by(AiCall.olusturma.desc())
            ).all()
            satirlar.append("AI çağrıları:")
            for c in cagrilar:
                hata = "hata var" if c.hata else "hata yok"
                gecerli = {True: "şema geçerli", False: "şema geçersiz"}.get(
                    c.sema_gecerli, "şema -"
                )
                satirlar.append(
                    f"- {c.olusturma.isoformat()} | {c.amac} | {c.mod} | {c.model} | "
                    f"{gecerli} | {hata} | ${float(c.maliyet or 0):.4f}"
                )
    return AracSonucu("\n".join(satirlar), kaynak=f"{tur}:{vid}:denetim", meta={"id": str(vid)})


def probe_my_queue(baglam: AracBaglami, **arg: Any) -> AracSonucu:
    _bilinmeyen(arg, ())
    with _db(baglam) as s:
        toplam, isler = bekleyen_isler(s, baglam.rol)
    rol = _rol_metni(baglam.rol)
    satirlar = [f"{rol} rolünü bekleyen işler: {toplam}"]
    if toplam > len(isler):
        satirlar[0] += f" (ilk {len(isler)} gösteriliyor)"
    satirlar += [f"- {i.tur} | {i.etiket} | {i.neden} | {i.rota}" for i in isler]
    if not isler:
        satirlar.append("- bekleyen iş yok")
    return AracSonucu("\n".join(satirlar), kaynak="kuyruk", meta={"rol": baglam.rol})


ARACLAR: dict[str, Callable[..., AracSonucu]] = {
    "probe_get": probe_get,
    "probe_list": probe_list,
    "probe_jobs": probe_jobs,
    "probe_audit": probe_audit,
    "probe_my_queue": probe_my_queue,
}

_TUR_SEMA = {"type": "string", "enum": list(TURLER)}

TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="probe_get",
        description=(
            "Testing Probe kaydının durumu: bekleyen kapı, sorumlu rol, son hata, ekran rotası; "
            "gereksinimde Jira anahtarı ve PO cevapları özeti. id_or_key: kayıt UUID'si ya da "
            "Jira anahtarı (gereksinim, bug taslağı, yayınlanmış case/test)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "tur": _TUR_SEMA,
                "id_or_key": {"type": "string", "minLength": 1, "maxLength": 64},
            },
            "required": ["tur", "id_or_key"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="probe_list",
        description=(
            "Testing Probe kayıtlarının kısa listesi (yeniden eskiye, en çok 20). durum: varlığın "
            "durumu (koşuda sonuç, hatada sınıf)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "tur": _TUR_SEMA,
                "durum": {"type": "string", "maxLength": 40},
                "limit": {"type": "integer", "minimum": 1, "maximum": LISTE_UST},
            },
            "required": ["tur"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="probe_jobs",
        description="Bir kaydın son 10 arka plan işi: tür, durum, deneme, kısa hata.",
        input_schema={
            "type": "object",
            "properties": {"varlik_id": {"type": "string", "format": "uuid"}},
            "required": ["varlik_id"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="probe_audit",
        description=(
            "Bir kaydın denetim izi (özet): durum geçişleri, onay/ret kararları, AI çağrıları."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "varlik_id": {"type": "string", "format": "uuid"},
                "limit": {"type": "integer", "minimum": 1, "maximum": DENETIM_UST},
            },
            "required": ["varlik_id"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="probe_my_queue",
        description="Oturumdaki kullanıcının rolüne düşen bekleyen işler (ekran rotalarıyla).",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
)
