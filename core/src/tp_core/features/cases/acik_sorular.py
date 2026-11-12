"""Açık soru / varsayım döngüsü (specs/011 K16; D6 şeridi).

Akış:

1. **Gönderim** (`send`, analist): gereksinimin güncel v3 case setinin birleşik özetindeki
   yanıtlanmamış açık sorular (`open_questions`; isteğe bağlı olarak case'lerin dayandığı
   varsayımlar, `assumptions`) story'ye **tek** Jira yorumu olarak gider — ön inceleme hattının
   yorum biçimi ve idempotency deseniyle (`flow.jira_once`, `Kayıt: tp-<uuid>` işareti, PO +
   analist bahsetmesi). Her soru PO'nun yanıtta kullanacağı kimlikle (`CQn` soru, `CAn` varsayım;
   ön inceleme `Qn`'leriyle çakışmasın diye ayrı önek) ve bekleyen case'lerle yazılır. Aynı soru
   (normalize metin hash'i) aynı PO onaylı içerik için ikinci kez gönderilmez. Jira çağrısı
   gereksinim satır kilidi altında yapılmaz (satırlar `bekliyor` yazılıp commit edilir, yorum
   kilitsiz yazılır, sonra satırlar kilitle `gonderildi` olur). Yorum boyutu sınırlıdır; sığmayan
   sorular sonraki gönderime kalır.
2. **Yanıtın geri okunması** (`read_answers`): PO etiket sorgusu (`flow.run_po_poll`) ve
   `POST …/open-questions/refresh` ile PO hesaplarının (yetki kimliği; görünen ad değil) gönderimden
   sonra yazdığı yorumlardaki `CQn: …` bölümleri soruya bağlanır (yanıt, yazar, zaman). Yanıt
   güvenilmeyen içeriktir; düz metindir.
3. **Case'e yansıması**: case listesinde soru kaydının durumu/yanıtı (`case_fields`,
   `po_sorulari`) ve yanıtlanan soruya bağlı taslak case için "düzelt / yeniden üret" önerisi;
   düzeltmeyle soru atfı kaldırılıp case hazır yapılırsa denetim kaydına "kaynak: PO yanıtı
   CQn" yazılır (`record_correction_source`; değişmez zincire yalnız etiket ve metin özetleri
   girer, soru/yanıt metni `acik_soru` tablosunda kalır). Yanıtlanan soruya bağlı case yoksa
   (yetim soru) öneri "yeniden üret"tir: yanıt bir sonraki üretimin girdisine girer.
4. **Sonraki üretimler**: yanıtlanan sorular (`generation_input`) üretim/derinleştirme girdisine
   ayrı güvenilmeyen blokta girer; yanıt yoksa girdi bayt bayt aynı kalır (replay golden'ları).
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import uuid
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.features.cases.schema import READY, is_legacy, normalize_ozet, readiness_of
from tp_core.models import Requirement, TestCase
from tp_core.models.acik_soru import AcikSoru
from tp_core.workflow.service import ConcurrentTransition, GateClosed, Principal, WorkflowError

ONEK = {"soru": "CQ", "varsayim": "CA"}
DURUM_GONDERILMEDI = "gonderilmedi"
# PO yorumundaki yanıt bölümü: "CQ3: …", "ca1 - …" (önceki harf/rakamla bitişik değil). Ön
# inceleme sorusunun "Q3: …" bölümü de bir bölümü bitirir (aynı yorumda iki tür yanıt olabilir).
_ETIKET = re.compile(r"(?<![\w])(C[QA]|Q)(\d{1,3})\s*[:.)\-–]\s*", re.IGNORECASE)
_SAHIP_TR = {"PO": "PO", "analyst": "analist", "developer": "geliştirici"}
YANIT_SINIRI = 4000
# PO yanıtının yazarı Jira görünen adı vermezse gösterilen etiket (e-posta gösterilmez; B17).
PO_YAZAR_ETIKETI = "PO"
# Jira yorumunun boyutu (alan sınırı 32.767 karakter; önek ve bahsetmeler için pay bırakılır).
# Soru metni ve case başlıkları model üretimidir: satır başına kırpılır, sığmayan soru sonraki
# gönderime kalır.
YORUM_SINIRI = 24000
SORU_METNI_SINIRI = 600
CASE_BASLIGI_SINIRI = 80
SATIR_CASE_SINIRI = 5


class AcikSoruYok(WorkflowError):
    """Gönderilecek yanıtlanmamış soru yok (409)."""


class GonderimSuruyor(ConcurrentTransition):
    """Aynı soru seti için başka bir gönderim Jira çağrısında (409; tur 3 güvenlik #1)."""


# Gönderim danışma kilidinin ad alanı (iki argümanlı; `workflow.jobs.IDEMPOTENCY_LOCK_NS` ile
# çakışmaz: `jira_once` aynı anahtar için kendi işlem kilidini başka bağlantıda alır).
GONDERIM_KILIT_NS = 7_310_031


@contextlib.contextmanager
def _gonderim_kilidi(engine: Engine, anahtar: str) -> Iterator[None]:
    """İdempotency anahtarı üzerinde oturum düzeyi danışma kilidi (`pg_try_advisory_lock`),
    ayrı bir bağlantıda Jira çağrısı boyunca tutulur. Kilit alınamazsa aynı soru seti şu an
    gönderiliyordur: bekletilmez, `GonderimSuruyor` (409). Böylece eşzamanlı iki gönderim (çift
    tık, iki analist) `jira_once`'un `intent` kaydını "belirsiz" sayıp yorumu ikinci kez yazamaz.
    Süreç düşerse kilit bağlantıyla birlikte bırakılır."""
    conn = engine.connect()
    try:
        alindi = conn.execute(
            text("SELECT pg_try_advisory_lock(:ns, hashtext(:k))"),
            {"ns": GONDERIM_KILIT_NS, "k": anahtar},
        ).scalar()
        conn.commit()
        if not alindi:
            raise GonderimSuruyor(
                "Bu açık sorular şu anda gönderiliyor; birkaç saniye sonra listeyi yenileyin."
            )
        try:
            yield
        finally:
            try:
                conn.execute(
                    text("SELECT pg_advisory_unlock(:ns, hashtext(:k))"),
                    {"ns": GONDERIM_KILIT_NS, "k": anahtar},
                )
                conn.commit()
            except Exception:  # pragma: no cover - kilit bağlantıyla birlikte düşer
                conn.invalidate()
    finally:
        conn.close()


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
    from tp_core.features.cases import ozet as ozet_modulu
    from tp_core.features.cases.review import current_cases
    from tp_core.features.cases.service import summaries

    cases = current_cases(session, req)
    birlesik = ozet_modulu.merged_summary(session, req, cases)
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
YENIDEN_URET_MESAJI = (
    "PO yanıtladı ama bu soruya bağlı case yok (soru hiçbir case'te anılmıyordu): yanıt bir "
    "sonraki üretimin girdisine girer; yanıtı kaynak alarak case'leri yeniden üretin."
)


def _oneri(satir: AcikSoru | None, caseler: Sequence[TestCase]) -> dict[str, Any] | None:
    if satir is None or satir.durum != "yanitlandi":
        return None
    if not caseler:
        # Yetim soru (011 tur 2 #1): düzeltilecek taslak yok; yanıt ancak yeniden üretimle döner.
        return {"eylem": "yeniden_uret", "case_ids": [], "mesaj": YENIDEN_URET_MESAJI}
    bekleyen = [tc for tc in caseler if tc.durum == "draft"]
    if not bekleyen:
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
                # Etiketli ama `bekliyor` satır: gönderim yarıda kaldı (Jira hatası/zaman aşımı;
                # yorum yazılmış olabilir). Portal "gönderim belirsiz" ipucu gösterir; yeniden
                # gönderim aynı anahtarla yorumu bulur, ikinci kez yazmaz (tur 3 güvenlik #11).
                "gonderim_belirsiz": satir is not None and satir.durum == "bekliyor",
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


def _kes(metin: Any, sinir: int) -> str:
    metin = " ".join(str(metin or "").split())
    return metin if len(metin) <= sinir else metin[: sinir - 1] + "…"


def _soru_satiri(satir: AcikSoru, caseler: Sequence[TestCase]) -> str:
    """Yorumdaki tek satır; model üretimi metinler kırpılır (soru metni, case başlıkları, en çok
    `SATIR_CASE_SINIRI` case; fazlası "+N case")."""
    sahip = _SAHIP_TR.get(satir.sahip, satir.sahip)
    ek = f" [yanıtlayacak: {sahip}]" if sahip and sahip != "PO" else ""
    gosterilen = [
        f"#{tc.sira_no} {_kes(tc.icerik.get('title'), CASE_BASLIGI_SINIRI)}".strip()
        for tc in caseler[:SATIR_CASE_SINIRI]
    ]
    if len(caseler) > SATIR_CASE_SINIRI:
        gosterilen.append(f"+{len(caseler) - SATIR_CASE_SINIRI} case")
    bekleyen = ", ".join(gosterilen)
    kim = "bekleyen case'ler" if satir.tur == "soru" else "dayanan case'ler"
    metin = _kes(satir.metin, SORU_METNI_SINIRI)
    return f"- {satir.etiket}{ek} {metin}" + (f" — {kim}: {bekleyen}" if bekleyen else "")


def comment_body(
    req: Requirement,
    gidecek: Sequence[tuple[AcikSoru, Sequence[TestCase]]],
    marker: str,
    *,
    kalan: int = 0,
) -> str:
    """PO'ya giden tek yorum (ön inceleme soru yorumunun biçiminde: başlık, liste, nasıl
    yanıtlanır, `Kayıt:` işareti). `kalan`: boyut sınırı yüzünden bu yoruma sığmayan soru sayısı
    (portalda bekler, sonraki gönderimde gider)."""
    sorular = [_soru_satiri(s, c) for s, c in gidecek if s.tur == "soru"]
    varsayimlar = [_soru_satiri(s, c) for s, c in gidecek if s.tur == "varsayim"]
    # Bekleyen case'i olmayan sorular (ör. hiçbir case'in atıf yapmadığı soru) için "case'ler
    # onaylanamaz" denmez: PO'ya yanlış bilgi verilmez (UX4 Bulgu 3).
    bagli_case_var = any(c for _, c in gidecek)
    satirlar = [
        "Test case üretiminde açık kalan sorular. Yanıtlanana kadar ilgili case'ler "
        '"Soru bekliyor" durumunda kalır ve onaylanamaz.'
        if bagli_case_var
        else "Test case üretiminde açık kalan sorular. Şu an bu sorulara bağlı bir case yok; "
        "yanıtınız test kapsamının doğru olması için kullanılır.",
    ]
    if sorular:
        satirlar += ["", "Açık sorular:", *sorular]
    if varsayimlar:
        satirlar += [
            "",
            "Doğrulanması istenen varsayımlar (case'ler bunlara dayanarak yazıldı):",
            *varsayimlar,
        ]
    if kalan:
        satirlar += ["", f"+{kalan} soru daha portalda bekliyor; ayrı bir yorumla gönderilecek."]
    ornek = gidecek[0][0].etiket
    satirlar += [
        "",
        "Yanıtlarınızı bu story'ye yorum olarak, sorunun kimliğiyle yazın (ör. "
        f"'{ornek}: …'); bir yorumda birden çok yanıt olabilir. Varsayım doğruysa "
        "'CAn: doğru', değilse doğrusunu yazın.",
        f"Kayıt: {marker}",
    ]
    return "\n".join(satirlar)


def idempotency_key(req_id: uuid.UUID, gereksinim_hash: str, satirlar: Sequence[AcikSoru]) -> str:
    """Yorumun idempotency anahtarı: gereksinim + PO onaylı içerik + etiketler + (etiket, metin
    hash'i) özetinin hash'i. Etiketler yeniden kullanılsa (geri alınmış gönderim, değişen set) bile
    farklı soru metni farklı anahtar (ve farklı `Kayıt:` işareti) verir; eski yorum yeni soruların
    "mevcut" gönderimi sayılmaz ve PO'nun eski yanıtı yeni soruya bağlanmaz (tur 2 güvenlik #5)."""
    sirali = sorted(satirlar, key=lambda s: s.etiket)
    etiketler = ",".join(s.etiket for s in sirali)
    ozet = hashlib.sha256(
        "\n".join(f"{s.etiket}={s.metin_hash}" for s in sirali).encode()
    ).hexdigest()[:16]
    return f"jira:comment:acik_soru:{req_id}:{gereksinim_hash}:{etiketler}:{ozet}"


def send(
    session: Session, requirement_id: uuid.UUID, user: Principal, *, varsayimlar: bool = False
) -> dict[str, Any]:
    """`POST /requirements/{id}/open-questions/send`: gönderilmemiş soruları tek yorumla gönderir.

    Üç aşama (D4 deseni: dış çağrı gereksinim satır kilidi altında yapılmaz; tur 2 güvenlik #4):

    1. Gereksinim kilitlenir; gidecek kalemler seçilir, yeni satırlar `bekliyor` ve deterministik
       etiketle (gereksinim başına artan) yazılır; işlem commit edilir (kilit bırakılır). Yorum
       boyut sınırına (`YORUM_SINIRI`) sığmayan kalemlere satır açılmaz; sonraki gönderime kalır.
    2. Yorum kilitsiz, `flow.jira_once` ile bir kez yazılır (anahtar: `idempotency_key`). Jira
       hatasında satırlar `bekliyor` kalır (portalda "gönderilmedi"); yeniden denemede aynı
       satırlar, etiketler ve anahtar kullanılır (yorum ikinci kez yazılmaz). Jira çağrısı
       boyunca anahtar üzerinde oturum düzeyi danışma kilidi tutulur; aynı anda aynı seti
       gönderen ikinci istek 409 (`GonderimSuruyor`) alır (tur 3 güvenlik #1).
    3. Satırlar kilitlenip `gonderildi` yapılır; gönderim zamanı yorumun Jira'daki zamanıdır
       (yanıtlar bundan sonraki PO yorumlarıdır). Denetim kaydı yalnız bu istek en az bir satırı
       `gonderildi` yaptıysa yazılır."""
    from tp_core.features.cases.service import get_requirement
    from tp_core.features.requirements import flow, services
    from tp_core.integrations import jira_notify

    # ---- 1. kilit altında hazırlık
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
    boyut = 0
    adaylar = [
        (k, satirlar.get((k.tur, k.hash)))
        for k in kalemler
        if satirlar.get((k.tur, k.hash)) is None or satirlar[(k.tur, k.hash)].durum == "bekliyor"
    ]
    kalan = 0
    for i, (k, satir) in enumerate(adaylar):
        yeni = satir is None
        if satir is None:
            satir = AcikSoru(
                requirement_id=req.id,
                tur=k.tur,
                etiket=f"{ONEK[k.tur]}{sonraki[k.tur] + 1}",
                kaynak_id=k.kaynak_id,
                metin=k.metin,
                metin_hash=k.hash,
                sahip=k.sahip,
                durum="bekliyor",
                gereksinim_hash=req.onaylanan_hash or "",
                gonderen=user.kullanici_adi,
            )
        satir_boyu = len(_soru_satiri(satir, k.caseler)) + 1
        if gidecek and boyut + satir_boyu > YORUM_SINIRI:
            kalan = len(adaylar) - i  # sıra korunur: sığmayan ve sonrakiler sonraki gönderime
            break
        boyut += satir_boyu
        if yeni:
            sonraki[k.tur] += 1
            session.add(satir)
        gidecek.append((satir, k.caseler))
    if not gidecek:
        raise AcikSoruYok(
            "Gönderilecek açık soru yok: güncel case setindeki sorular zaten gönderildi ya da "
            "yanıtlandı."
        )
    session.flush()
    rid, key = req.id, req.jira_key
    satir_idleri = [s.id for s, _ in gidecek]
    anahtar = idempotency_key(req.id, req.onaylanan_hash or "", [s for s, _ in gidecek])
    marker = flow._marker(anahtar)
    govde = comment_body(req, gidecek, marker, kalan=kalan)
    session.commit()  # gereksinim satır kilidi Jira çağrısından önce bırakılır

    # ---- 2. kilitsiz Jira yorumu (bir kez); aynı anahtarlı eşzamanlı gönderim 409 alır
    jira = services.jira()
    motor: Engine = session.get_bind()  # type: ignore[assignment]
    with _gonderim_kilidi(motor, anahtar):
        yorum_id = flow.jira_once(
            motor,
            entity_turu="requirement",
            entity_id=rid,
            idempotency_key=anahtar,
            action=lambda: jira_notify.post_comment(jira, key, govde, jira_notify.PO_SORU),
            find_existing=lambda: flow._comment_with_marker(jira, key, marker),
        )
    zaman = _yorum_zamani(jira, key, marker) or datetime.now(UTC)

    # ---- 3. kilitle ve gönderildi yaz (eşzamanlı aynı gönderim de aynı yorumu bulur)
    yazilan = session.scalars(
        select(AcikSoru)
        .where(AcikSoru.id.in_(satir_idleri))
        .order_by(AcikSoru.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    guncellenen: list[str] = []
    for satir in yazilan:
        if satir.durum != "bekliyor":
            continue
        satir.durum = "gonderildi"
        satir.gonderim_zamani = zaman
        satir.jira_comment_id = yorum_id
        guncellenen.append(satir.etiket)
    if guncellenen:  # denetim kaydı yalnız bu istek satırları gerçekten gönderildi yaptıysa
        audit_on_commit(
            session,
            user.kullanici_adi,
            "acik_soru.gonderildi",
            f"requirement:{rid}",
            {
                "jira_key": key,
                "etiketler": sorted(guncellenen),
                "jira_comment_id": yorum_id,
                "kalan": kalan,
            },
        )
    session.flush()
    return view(session, rid)


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
    sayılır; aynı soruya birden çok yorum yanıt verdiyse sırayla birleştirilir.

    Eşzamanlılık (tur 2 güvenlik #12): periyodik sorgu ve `refresh` ucu aynı anda okuyabilir.
    Jira yorumları kilitsiz okunur; yazmadan önce satırlar `FOR UPDATE SKIP LOCKED` ile alınıp
    durumları yeniden denetlenir. Başka okuyucunun tuttuğu satır atlanır, yanıtlanmış satır
    yeniden yazılmaz (`acik_soru.yanitlandi` denetim kaydı bir kez düşer). Oturum gereksinim
    başına commit edilir; çağıran açık bir `session.begin()` bloğu içinde çağırmamalıdır."""
    from tp_core.features.requirements import flow

    q = select(AcikSoru).where(AcikSoru.durum == "gonderildi")
    if requirement_ids is not None:
        q = q.where(AcikSoru.requirement_id.in_(list(requirement_ids)))
    bekleyen: dict[uuid.UUID, list[tuple[uuid.UUID, datetime | None]]] = defaultdict(list)
    for satir in session.scalars(q.order_by(AcikSoru.requirement_id, AcikSoru.etiket)):
        bekleyen[satir.requirement_id].append((satir.id, satir.gonderim_zamani))
    session.commit()  # okuma işlemi Jira çağrısından önce kapanır
    yanitlanan = 0
    for rid, adaylar in bekleyen.items():
        jira_key = session.scalar(select(Requirement.jira_key).where(Requirement.id == rid))
        session.commit()
        if not jira_key:
            continue
        esik = min((z for _, z in adaylar if z), default=None)
        yorumlar = flow._po_cevaplari(jira, jira_key, hesaplar, esik)
        satirlar = session.scalars(
            select(AcikSoru)
            .where(
                AcikSoru.id.in_([i for i, _ in adaylar]),
                AcikSoru.durum == "gonderildi",
            )
            .order_by(AcikSoru.etiket)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).all()
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
            # B17: portalda e-posta değil görünen ad gösterilir (Jira displayName); yoksa "PO"
            # etiketi. Denetim kaydında yazarın kimliği (e-posta/accountId) kalır.
            satir.yanit_yazari = str(son.get("yazar_adi") or "").strip() or PO_YAZAR_ETIKETI
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
                    "yazar": str(son.get("yazar") or ""),
                    "yazar_adi": satir.yanit_yazari,
                    "jira_comment_id": satir.yanit_yorum_id,
                },
            )
        # Gereksinim başına commit (tur 3 güvenlik #10): satır kilitleri sonraki gereksinimlerin
        # Jira okumaları boyunca tutulmaz; denetim kayıtları da bu commit'le düşer.
        session.commit()
    return yanitlanan


def poll(jira: Any, hesaplar: frozenset[str]) -> int:
    """PO etiket sorgusunun (`flow.run_po_poll`) çağırdığı giriş: kendi oturumuyla okur;
    `read_answers` gereksinim başına commit eder (hata olursa yalnız o gereksinim geri alınır)."""
    from tp_core.models import new_session

    with new_session() as s:
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
            # Değişmez zincire metin girmez (PO yanıtında kişisel veri olabilir; KVKK silme
            # talebi zinciri bozamaz): etiket + metin özetleri. Metin `acik_soru` satırındadır.
            "sorular": [
                {
                    "etiket": s.etiket,
                    "acik_soru_id": str(s.id),
                    "soru_hash": s.metin_hash,
                    "yanit_hash": hashlib.sha256((s.yanit or "").encode()).hexdigest(),
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
