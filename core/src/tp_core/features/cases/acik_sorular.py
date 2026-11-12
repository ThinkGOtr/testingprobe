"""Açık soru / varsayım döngüsü (specs/011 K16; D6 şeridi).

Akış:

1. **Gönderim** (`send`, analist): gereksinimin güncel v3 case setinin birleşik özetindeki
   yanıtlanmamış açık sorular (`open_questions`; isteğe bağlı olarak case'lerin dayandığı
   varsayımlar, `assumptions`) story'ye **tek** Jira yorumu olarak gider — ön inceleme hattının
   yorum biçimi ve idempotency deseniyle (`flow.jira_once`, `Kayıt: tp-<uuid>` işareti, PO +
   analist bahsetmesi). Her soru PO'nun yanıtta kullanacağı kimlikle (`CQn` soru, `CAn` varsayım;
   ön inceleme `Qn`'leriyle çakışmasın diye ayrı önek) ve bekleyen case'lerle yazılır. Aynı soru
   (normalize metin hash'i) aynı PO onaylı içerik için ikinci kez gönderilmez.
2. **Yanıtın geri okunması** (`read_answers`): PO etiket sorgusu (`flow.run_po_poll`) ve
   `POST …/open-questions/refresh` ile PO hesaplarının (yetki kimliği; görünen ad değil) gönderimden
   sonra yazdığı yorumlardaki `CQn: …` bölümleri soruya bağlanır (yanıt, yazar, zaman). Yanıt
   güvenilmeyen içeriktir; düz metindir.
3. **Case'e yansıması**: case listesinde soru kaydının durumu/yanıtı (`case_fields`,
   `po_sorulari`) ve yanıtlanan soruya bağlı taslak case için "düzelt / yeniden üret" önerisi;
   düzeltmeyle soru atfı kaldırılıp case hazır yapılırsa denetim kaydına "kaynak: PO yanıtı
   CQn" yazılır (`record_correction_source`).
4. **Sonraki üretimler**: yanıtlanan sorular (`generation_input`) üretim/derinleştirme girdisine
   ayrı güvenilmeyen blokta girer; yanıt yoksa girdi bayt bayt aynı kalır (replay golden'ları).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.features.cases.schema import READY, is_legacy, normalize_ozet, readiness_of
from tp_core.models import Requirement, TestCase
from tp_core.models.acik_soru import AcikSoru
from tp_core.workflow.service import GateClosed, Principal, WorkflowError

ONEK = {"soru": "CQ", "varsayim": "CA"}
DURUM_GONDERILMEDI = "gonderilmedi"
# PO yorumundaki yanıt bölümü: "CQ3: …", "ca1 - …" (önceki harf/rakamla bitişik değil). Ön
# inceleme sorusunun "Q3: …" bölümü de bir bölümü bitirir (aynı yorumda iki tür yanıt olabilir).
_ETIKET = re.compile(r"(?<![\w])(C[QA]|Q)(\d{1,3})\s*[:.)\-–]\s*", re.IGNORECASE)
_SAHIP_TR = {"PO": "PO", "analyst": "analist", "developer": "geliştirici"}
YANIT_SINIRI = 4000


class AcikSoruYok(WorkflowError):
    """Gönderilecek yanıtlanmamış soru yok (409)."""


def normalize(metin: Any) -> str:
    return " ".join(str(metin or "").split()).casefold()


def text_hash(tur: str, metin: Any) -> str:
    return hashlib.sha256(f"{tur}\n{normalize(metin)}".encode()).hexdigest()


def _etiket_no(etiket: str) -> int:
    try:
        return int(etiket[2:])
    except ValueError:
        return 0


# --------------------------------------------------------------------------- güncel kalemler


@dataclass
class Kalem:
    """Güncel setin bir açık sorusu / varsayımı (birleşik özetten) ve ona atıf yapan case'ler."""

    tur: str
    kaynak_id: str
    metin: str
    sahip: str
    hash: str
    caseler: list[TestCase] = field(default_factory=list)


def _metin(tur: str, kayit: Mapping[str, Any]) -> str:
    return str(kayit.get("question" if tur == "soru" else "statement") or "")


def current_items(session: Session, req: Requirement) -> list[Kalem]:
    """Birleşik özetteki açık sorular + case'lerin dayandığı varsayımlar (sıra: soru, varsayım).

    Case → soru eşlemesi case'in kendi üretim özetindeki metinle yapılır (aynı `Q1` farklı
    üretimlerde farklı soru olabilir); varsayımlar yalnız bir case'in dayandığıysa listelenir.
    """
    from tp_core.features.cases.review import _birlesik_ozet, current_cases
    from tp_core.features.cases.service import summaries

    cases = current_cases(session, req)
    birlesik = _birlesik_ozet(session, req, {tc.uretim_no for tc in cases})
    ozetler = {u.uretim_no: normalize_ozet(u.ozet) for u in summaries(session, {req.id}).values()}
    kalemler: dict[tuple[str, str], Kalem] = {}
    for tur, alan in (("soru", "open_questions"), ("varsayim", "assumptions")):
        for kayit in birlesik.get(alan) or []:
            if not isinstance(kayit, Mapping) or not _metin(tur, kayit).strip():
                continue
            h = text_hash(tur, _metin(tur, kayit))
            kalemler.setdefault(
                (tur, h),
                Kalem(
                    tur=tur,
                    kaynak_id=str(kayit.get("id") or ""),
                    metin=" ".join(_metin(tur, kayit).split()),
                    sahip=str(kayit.get("owner") or ""),
                    hash=h,
                ),
            )
    for tc in cases:
        ozet = ozetler.get(tc.uretim_no) or {}
        for tur, ref_alani, alan in (
            ("soru", "open_question_refs", "open_questions"),
            ("varsayim", "assumption_refs", "assumptions"),
        ):
            tanim = {
                str(x.get("id")): _metin(tur, x)
                for x in ozet.get(alan) or []
                if isinstance(x, Mapping)
            }
            for ref in tc.icerik.get(ref_alani) or []:
                metin = tanim.get(str(ref))
                kalem = kalemler.get((tur, text_hash(tur, metin))) if metin else None
                if kalem is not None and tc not in kalem.caseler:
                    kalem.caseler.append(tc)
    return [k for k in kalemler.values() if k.tur == "soru" or k.caseler]


def _rows(session: Session, req: Requirement) -> dict[tuple[str, str], AcikSoru]:
    """Güncel PO onaylı içeriğe ait kayıtlar: (tür, metin hash'i) → satır."""
    satirlar = session.scalars(
        select(AcikSoru).where(
            AcikSoru.requirement_id == req.id,
            AcikSoru.gereksinim_hash == (req.onaylanan_hash or ""),
        )
    ).all()
    return {(r.tur, r.metin_hash): r for r in satirlar}


def _durum(satir: AcikSoru | None) -> str:
    if satir is None or satir.durum == "bekliyor":
        return DURUM_GONDERILMEDI
    return satir.durum


def _yanit(satir: AcikSoru | None) -> dict[str, Any] | None:
    if satir is None or satir.durum != "yanitlandi":
        return None
    return {
        "metin": satir.yanit,
        "yazar": satir.yanit_yazari,
        "zaman": satir.yanit_zamani,
        "jira_comment_id": satir.yanit_yorum_id,
    }


def _case_ozeti(tc: TestCase) -> dict[str, Any]:
    return {
        "id": str(tc.id),
        "sira_no": tc.sira_no,
        "uretim_no": tc.uretim_no,
        "title": tc.icerik.get("title"),
        "durum": tc.durum,
        "readiness": readiness_of(tc.icerik),
    }


ONERI_MESAJI = (
    "PO yanıtladı: beklenen sonucu yanıta göre yazıp atfı kaldırarak case'i düzeltin (hazır "
    "yapın) ya da yanıtı kaynak alarak yeniden üretin."
)


def _oneri(satir: AcikSoru | None, caseler: Sequence[TestCase]) -> dict[str, Any] | None:
    bekleyen = [tc for tc in caseler if tc.durum == "draft"]
    if satir is None or satir.durum != "yanitlandi" or not bekleyen:
        return None
    return {
        "eylem": "duzelt_veya_yeniden_uret",
        "case_ids": [str(tc.id) for tc in bekleyen],
        "mesaj": ONERI_MESAJI,
    }


# --------------------------------------------------------------------------- liste (GET)


def view(session: Session, requirement_id: uuid.UUID) -> dict[str, Any]:
    """`GET /requirements/{id}/open-questions`: güncel setin soruları/varsayımları ve durumları."""
    from tp_core.features.cases.service import get_requirement

    req = get_requirement(session, requirement_id)
    kalemler = current_items(session, req)
    satirlar = _rows(session, req)
    out = []
    for k in kalemler:
        satir = satirlar.get((k.tur, k.hash))
        out.append(
            {
                "etiket": satir.etiket if satir is not None else None,
                "kaynak_id": k.kaynak_id,
                "tur": k.tur,
                "metin": k.metin,
                "sahip": k.sahip,
                "durum": _durum(satir),
                "gonderim": (
                    {
                        "zaman": satir.gonderim_zamani,
                        "gonderen": satir.gonderen,
                        "jira_comment_id": satir.jira_comment_id,
                    }
                    if satir is not None and satir.durum != "bekliyor"
                    else None
                ),
                "yanit": _yanit(satir),
                "bekleyen_caseler": [_case_ozeti(tc) for tc in k.caseler],
                "oneri": _oneri(satir, k.caseler),
            }
        )
    sayim = {DURUM_GONDERILMEDI: 0, "gonderildi": 0, "yanitlandi": 0}
    for s in out:
        sayim[s["durum"]] += 1
    engel = _gonderim_engeli(req, out)
    return {
        "requirement_id": str(req.id),
        "jira_key": req.jira_key,
        "sayim": sayim,
        "gonderilebilir": engel is None,
        "gonderim_engeli": engel,
        "sorular": out,
    }


def _gonderim_engeli(req: Requirement, sorular: Sequence[Mapping[str, Any]]) -> str | None:
    if not req.jira_key:
        return "Gereksinimin Jira story'si yok; açık sorular PO'ya story yorumu olarak gönderilir."
    if not any(s["durum"] == DURUM_GONDERILMEDI for s in sorular):
        return "Gönderilmemiş açık soru yok."
    return None


# --------------------------------------------------------------------------- gönderim


def _soru_satiri(satir: AcikSoru, caseler: Sequence[TestCase]) -> str:
    sahip = _SAHIP_TR.get(satir.sahip, satir.sahip)
    ek = f" [yanıtlayacak: {sahip}]" if sahip and sahip != "PO" else ""
    bekleyen = ", ".join(f"#{tc.sira_no} {tc.icerik.get('title') or ''}".strip() for tc in caseler)
    kim = "bekleyen case'ler" if satir.tur == "soru" else "dayanan case'ler"
    return f"- {satir.etiket}{ek} {satir.metin}" + (f" — {kim}: {bekleyen}" if bekleyen else "")


def comment_body(
    req: Requirement, gidecek: Sequence[tuple[AcikSoru, Sequence[TestCase]]], marker: str
) -> str:
    """PO'ya giden tek yorum (ön inceleme soru yorumunun biçiminde: başlık, liste, nasıl
    yanıtlanır, `Kayıt:` işareti)."""
    sorular = [_soru_satiri(s, c) for s, c in gidecek if s.tur == "soru"]
    varsayimlar = [_soru_satiri(s, c) for s, c in gidecek if s.tur == "varsayim"]
    satirlar = [
        "Test case üretiminde açık kalan sorular. Yanıtlanana kadar ilgili case'ler "
        '"Soru bekliyor" durumunda kalır ve onaylanamaz.',
    ]
    if sorular:
        satirlar += ["", "Açık sorular:", *sorular]
    if varsayimlar:
        satirlar += [
            "",
            "Doğrulanması istenen varsayımlar (case'ler bunlara dayanarak yazıldı):",
            *varsayimlar,
        ]
    ornek = gidecek[0][0].etiket
    satirlar += [
        "",
        "Yanıtlarınızı bu story'ye yorum olarak, sorunun kimliğiyle yazın (ör. "
        f"'{ornek}: …'); bir yorumda birden çok yanıt olabilir. Varsayım doğruysa "
        "'CAn: doğru', değilse doğrusunu yazın.",
        f"Kayıt: {marker}",
    ]
    return "\n".join(satirlar)


def send(
    session: Session, requirement_id: uuid.UUID, user: Principal, *, varsayimlar: bool = False
) -> dict[str, Any]:
    """`POST /requirements/{id}/open-questions/send`: gönderilmemiş soruları tek yorumla gönderir.

    Satırlar `bekliyor` olarak yazılır, etiketler deterministik verilir (gereksinim başına artan),
    yorum `flow.jira_once` ile bir kez yazılır (anahtar: gereksinim + etiket kümesi; Jira hatası
    olursa istek geri alınır ve yeniden denemede aynı etiketler ve anahtar oluşur). Başarıda
    satırlar `gonderildi` olur; gönderim zamanı yorumun Jira'daki zamanıdır (yanıtlar bundan
    sonraki PO yorumlarıdır)."""
    from tp_core.features.cases.service import get_requirement
    from tp_core.features.requirements import flow, services
    from tp_core.integrations import jira_notify

    req = get_requirement(session, requirement_id, lock=True)
    if not req.jira_key:
        raise GateClosed(
            "Gereksinimin Jira story'si yok; açık sorular PO'ya story yorumu olarak gönderilir"
        )
    kalemler = [k for k in current_items(session, req) if varsayimlar or k.tur == "soru"]
    satirlar = _rows(session, req)
    tum_etiketler = session.scalars(
        select(AcikSoru.etiket).where(AcikSoru.requirement_id == req.id)
    ).all()
    sonraki = {
        tur: max((_etiket_no(e) for e in tum_etiketler if e.startswith(onek)), default=0)
        for tur, onek in ONEK.items()
    }
    gidecek: list[tuple[AcikSoru, list[TestCase]]] = []
    for k in kalemler:
        satir = satirlar.get((k.tur, k.hash))
        if satir is not None and satir.durum != "bekliyor":
            continue
        if satir is None:
            sonraki[k.tur] += 1
            satir = AcikSoru(
                requirement_id=req.id,
                tur=k.tur,
                etiket=f"{ONEK[k.tur]}{sonraki[k.tur]}",
                kaynak_id=k.kaynak_id,
                metin=k.metin,
                metin_hash=k.hash,
                sahip=k.sahip,
                durum="bekliyor",
                gereksinim_hash=req.onaylanan_hash or "",
                gonderen=user.kullanici_adi,
            )
            session.add(satir)
        gidecek.append((satir, k.caseler))
    if not gidecek:
        raise AcikSoruYok(
            "Gönderilecek açık soru yok: güncel case setindeki sorular zaten gönderildi ya da "
            "yanıtlandı."
        )
    session.flush()
    etiketler = sorted(s.etiket for s, _ in gidecek)
    anahtar = f"jira:comment:acik_soru:{req.id}:{req.onaylanan_hash or ''}:" + ",".join(etiketler)
    marker = flow._marker(anahtar)
    govde = comment_body(req, gidecek, marker)
    jira = services.jira()
    key = req.jira_key
    yorum_id = flow.jira_once(
        session.get_bind(),  # type: ignore[arg-type]
        entity_turu="requirement",
        entity_id=req.id,
        idempotency_key=anahtar,
        action=lambda: jira_notify.post_comment(jira, key, govde, jira_notify.PO_SORU),
        find_existing=lambda: flow._comment_with_marker(jira, key, marker),
    )
    zaman = _yorum_zamani(jira, key, marker) or datetime.now(UTC)
    for satir, _ in gidecek:
        satir.durum = "gonderildi"
        satir.gonderim_zamani = zaman
        satir.jira_comment_id = yorum_id
    audit_on_commit(
        session,
        user.kullanici_adi,
        "acik_soru.gonderildi",
        f"requirement:{req.id}",
        {"jira_key": key, "etiketler": etiketler, "jira_comment_id": yorum_id},
    )
    session.flush()
    return view(session, req.id)


def _yorum_zamani(jira: Any, key: str, marker: str) -> datetime | None:
    try:
        yorum = next((c for c in jira.get_comments(key) if marker in c.body), None)
    except Exception:  # zaman yalnız eşik; okunamazsa şimdiki zaman kullanılır
        return None
    return yorum.created if yorum is not None else None


# --------------------------------------------------------------------------- yanıt okuma


def parse_answers(metin: str) -> dict[str, str]:
    """Yorumdaki `CQn: …` / `CAn: …` bölümleri → {etiket: yanıt} (deterministik)."""
    eslesmeler = list(_ETIKET.finditer(metin))
    out: dict[str, list[str]] = {}
    for i, m in enumerate(eslesmeler):
        if m.group(1).upper() == "Q":
            continue
        etiket = f"{m.group(1).upper()}{int(m.group(2))}"
        son = eslesmeler[i + 1].start() if i + 1 < len(eslesmeler) else len(metin)
        parca = metin[m.end() : son].strip()
        if parca:
            out.setdefault(etiket, []).append(parca)
    return {k: " / ".join(v) for k, v in out.items()}


def read_answers(
    session: Session,
    jira: Any,
    hesaplar: frozenset[str],
    requirement_ids: Iterable[uuid.UUID] | None = None,
) -> int:
    """Gönderilmiş (yanıtsız) soruların PO yanıtlarını Jira yorumlarından okur; yanıtlanan
    soru sayısını döner. Yalnız PO hesaplarının (yetki kimliği) gönderimden sonraki yorumları
    sayılır; aynı soruya birden çok yorum yanıt verdiyse sırayla birleştirilir."""
    from tp_core.features.requirements import flow

    q = select(AcikSoru).where(AcikSoru.durum == "gonderildi")
    if requirement_ids is not None:
        q = q.where(AcikSoru.requirement_id.in_(list(requirement_ids)))
    bekleyen: dict[uuid.UUID, list[AcikSoru]] = defaultdict(list)
    for satir in session.scalars(q.order_by(AcikSoru.requirement_id, AcikSoru.etiket)):
        bekleyen[satir.requirement_id].append(satir)
    yanitlanan = 0
    for rid, satirlar in bekleyen.items():
        req = session.get(Requirement, rid)
        if req is None or not req.jira_key:
            continue
        esik = min((s.gonderim_zamani for s in satirlar if s.gonderim_zamani), default=None)
        yorumlar = flow._po_cevaplari(jira, req.jira_key, hesaplar, esik)
        for satir in satirlar:
            parcalar: list[tuple[str, dict[str, Any]]] = []
            for y in yorumlar:
                zaman = datetime.fromisoformat(y["zaman"]) if y.get("zaman") else None
                if satir.gonderim_zamani and zaman and zaman < satir.gonderim_zamani:
                    continue
                parca = parse_answers(str(y.get("metin") or "")).get(satir.etiket)
                if parca:
                    parcalar.append((parca, y))
            if not parcalar:
                continue
            son = parcalar[-1][1]
            satir.yanit = " / ".join(p for p, _ in parcalar)[:YANIT_SINIRI]
            satir.yanit_yazari = str(son.get("yazar") or "")
            satir.yanit_zamani = (
                datetime.fromisoformat(son["zaman"]) if son.get("zaman") else datetime.now(UTC)
            )
            satir.yanit_yorum_id = str(son.get("id") or "")
            satir.durum = "yanitlandi"
            yanitlanan += 1
            audit_on_commit(
                session,
                "system",
                "acik_soru.yanitlandi",
                f"requirement:{rid}",
                {
                    "etiket": satir.etiket,
                    "yazar": satir.yanit_yazari,
                    "jira_comment_id": satir.yanit_yorum_id,
                },
            )
    session.flush()
    return yanitlanan


def poll(jira: Any, hesaplar: frozenset[str]) -> int:
    """PO etiket sorgusunun (`flow.run_po_poll`) çağırdığı giriş: kendi işlemiyle okur."""
    from tp_core.models import session_scope

    with session_scope() as s:
        return read_answers(s, jira, hesaplar)


# --------------------------------------------------------------------------- case alanları


def case_fields(session: Session, cases: list[dict[str, Any]]) -> None:
    """`serialize_cases` çıktısına soru kaydı durumunu ekler (yerinde; mevcut alanlar değişmez).

    `po_sorulari`: case'in atıf yaptığı soru/varsayım kimliği (`Q1`/`A1`) → `{po_etiketi,
    po_durumu (gonderilmedi|gonderildi|yanitlandi), po_yaniti ({metin, yazar, zaman} | null)}`;
    `po_yanit_onerisi`: yanıtlanan soruya bağlı taslak v3 case için düzelt/yeniden üret önerisi."""
    req_ids = {uuid.UUID(c["requirement_id"]) for c in cases}
    reqs = {
        r.id: r for r in session.scalars(select(Requirement).where(Requirement.id.in_(req_ids)))
    }
    satirlar_by = {rid: _rows(session, r) for rid, r in reqs.items()}
    for c in cases:
        satirlar = satirlar_by.get(uuid.UUID(c["requirement_id"]), {})
        yanitli: list[str] = []
        durumlar: dict[str, dict[str, Any]] = {}
        for tur, alan in (("soru", "acik_sorular"), ("varsayim", "varsayimlar")):
            for kayit in c.get(alan) or []:
                satir = satirlar.get((tur, text_hash(tur, _metin(tur, kayit))))
                yanit = _yanit(satir)
                durumlar[str(kayit.get("id"))] = {
                    "tur": tur,
                    "po_etiketi": satir.etiket if satir is not None else None,
                    "po_durumu": _durum(satir),
                    "po_yaniti": (
                        {k: yanit[k] for k in ("metin", "yazar", "zaman")} if yanit else None
                    ),
                }
                if yanit and satir is not None:
                    yanitli.append(satir.etiket)
        c["po_sorulari"] = durumlar
        c["po_yanit_onerisi"] = (
            {"eylem": "duzelt_veya_yeniden_uret", "etiketler": yanitli, "mesaj": ONERI_MESAJI}
            if yanitli and c.get("durum") == "draft" and not c.get("legacy")
            else None
        )


def record_correction_source(
    session: Session, tc: TestCase, yeni: Mapping[str, Any], user: Principal
) -> list[str]:
    """Düzeltme yanıtlanmış bir soru/varsayım atfını kaldırıp case'i hazır yapıyorsa denetim
    kaydına "kaynak: PO yanıtı CQn" yazar; kaynak etiketlerini döner."""
    from tp_core.features.cases.service import get_requirement, summary_for

    if is_legacy(tc.icerik) or readiness_of(yeni) != READY:
        return []
    req = get_requirement(session, tc.requirement_id)
    ozet = normalize_ozet(summary_for(session, tc))
    satirlar = _rows(session, req)
    kaynaklar: list[AcikSoru] = []
    for tur, ref_alani, alan in (
        ("soru", "open_question_refs", "open_questions"),
        ("varsayim", "assumption_refs", "assumptions"),
    ):
        kalkan = [
            str(r)
            for r in tc.icerik.get(ref_alani) or []
            if str(r) not in {str(x) for x in yeni.get(ref_alani) or []}
        ]
        tanim = {str(x.get("id")): _metin(tur, x) for x in ozet.get(alan) or []}
        for ref in kalkan:
            satir = satirlar.get((tur, text_hash(tur, tanim.get(ref))))
            if satir is not None and satir.durum == "yanitlandi":
                kaynaklar.append(satir)
    if not kaynaklar:
        return []
    etiketler = [s.etiket for s in kaynaklar]
    audit_on_commit(
        session,
        user.kullanici_adi,
        "case.po_yaniti_kaynak",
        f"test_case:{tc.id}",
        {
            "kaynak": "PO yanıtı " + ", ".join(etiketler),
            "requirement_id": str(tc.requirement_id),
            "sorular": [
                {
                    "etiket": s.etiket,
                    "soru": s.metin,
                    "yanit": s.yanit,
                    "yanit_yazari": s.yanit_yazari,
                }
                for s in kaynaklar
            ],
        },
    )
    return etiketler


# --------------------------------------------------------------------------- üretim girdisi


def generation_input(session: Session, req: Requirement) -> str:
    """Yanıtlanan soruların üretim girdisi metni (güvenilmeyen blokta gider). Yanıt yoksa ""
    (girdi bayt bayt aynı kalır). Yalnız güncel PO onaylı içerik için verilen yanıtlar."""
    satirlar = sorted(
        (s for s in _rows(session, req).values() if s.durum == "yanitlandi"),
        key=lambda s: (s.tur != "soru", _etiket_no(s.etiket)),
    )
    bloklar = []
    for s in satirlar:
        tur = "Soru" if s.tur == "soru" else "Varsayım"
        kim = f" ({s.yanit_yazari})" if s.yanit_yazari else ""
        bloklar.append(f"{s.etiket} — {tur}: {s.metin}\nPO yanıtı{kim}: {s.yanit or ''}")
    return "\n\n".join(bloklar)


def generation_parts(text: str, kaynak: str, kind: str) -> list[str]:
    """`generation_messages` / derinleştirme girdisine eklenecek parçalar (boşsa hiçbiri)."""
    if not text:
        return []
    from tp_core.gateway import wrap_untrusted

    return [
        "PO'nun açık soru yanıtları (önceki case üretiminde sorulan sorular; beklenen sonucu "
        "bu yanıtlardan türet, yanıtlanan soruya artık atıf yapma):",
        wrap_untrusted(text, source=f"{kaynak}:po-acik-soru", kind=kind),
    ]


# --------------------------------------------------------------------------- API

router = APIRouter(tags=["cases"])
Analyst = Annotated[Principal, Depends(require_role("analyst"))]


class GonderGirdisi(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Case'lerin dayandığı varsayımlar da doğrulama için gönderilsin mi (varsayılan: yalnız soru).
    varsayimlar: bool = False


@router.get("/requirements/{requirement_id}/open-questions")
def get_open_questions(
    requirement_id: uuid.UUID, session: DbSession, _user: CurrentUser
) -> dict[str, Any]:
    return view(session, requirement_id)


@router.post("/requirements/{requirement_id}/open-questions/send")
def post_send(
    requirement_id: uuid.UUID,
    session: DbSession,
    user: Analyst,
    body: GonderGirdisi | None = None,
) -> dict[str, Any]:
    return send(session, requirement_id, user, varsayimlar=bool(body and body.varsayimlar))


@router.post("/requirements/{requirement_id}/open-questions/refresh")
def post_refresh(requirement_id: uuid.UUID, session: DbSession, _user: Analyst) -> dict[str, Any]:
    """PO yanıtlarını şimdi oku (periyodik PO sorgusunu beklemeden)."""
    from tp_core.features.cases.service import get_requirement
    from tp_core.features.requirements import services

    req = get_requirement(session, requirement_id)
    if req.jira_key:
        read_answers(session, services.jira(), services.po_accounts(), [req.id])
    return view(session, requirement_id)
