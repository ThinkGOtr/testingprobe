"""Jira durum tetiği (specs/013-sprint-otomasyonu §3.4, §9 K14, K15).

Worker işi `requirements.jira_tetik` her `aralik_s` saniyede bir Jira'da ayarlanan duruma
(varsayılan "QA To Do") gelmiş story'leri arar (sayfalı, en çok `ARAMA_SINIRI`).

**Yalnız duruma GİREN story tetiklenir (K14).** `requirement.jira_durumu` tetiğin story'yi bu
durumda son gördüğü değerdir (durumdan çıkan story'de tam listeli turda NULL'a çekilir). Tetiğin
"başlangıç işareti" `ayarlar.TETIK_TABANI` satırıdır:

- İşaret yoksa (ilk tur; tetik açıldı ya da `durum` değişti → `ayarlar.yaz` işareti siler) tur
  **taban turudur**: o anda durumda olan her story yalnız işaretlenir (`jira_durumu` yazılır;
  TP'de yoksa okunarak gereksinim olarak eklenir), hiçbiri tetiklenmez. Arama ve tüm story'ler
  hatasız işlenirse işaret yazılır; aksi halde sonraki tur tabanı yeniden kurar (işaretleme
  idempotenttir, tetik yoktur).
- İşaret varsa: `jira_durumu` bu durumu göstermeyen (yeni ya da durumdan çıkıp geri gelen) story
  duruma **girmiştir**: çekilir (`upsert_issue`), `jira_durumu` yazılır ve gereksinim durumuna
  göre:
  - `new` → `qa_tetik_zamani = now()`, ön inceleme başlar (`tetiklendi`).
  - `po_approved` ve etkin case'i yok, `otomatik_case` açık → `requirements.otomatik_case` işi
    hemen kuyruğa (`case_uretimi`, K15b).
  - inceleme/PO aşamasında (`in_review`, `findings_open`, `doc_final`, `pending_po`) →
    `qa_tetik_zamani` yazılır (`akisa_alindi`): PO onayı gelince case üretimi otomatik başlar.
  - diğerleri (`generating`, `cases_ready`, `done`, `failed`, case'li `po_approved`) →
    `dokunulmadi` + neden.
- Durumda kalmaya devam eden story'ye her turda **yazılmaz** (kilit yok). Yalnız tetikle akışa
  alınmış (`qa_tetik_zamani` dolu) story'nin Jira içeriği değiştiyse çekilir; içerik değişimi
  gereksinimi `new`'e döndürdüyse (`sifirlandi`) — ya da başka bir yol (PO sorgusu) döndürmüşse —
  ön inceleme yeniden başlar (`yeniden_tetiklendi`, K15a). Ön inceleme gereksinimi aynı işlemde
  `new`'den çıkardığı için çift tetik olmaz. Taban turunda işaretlenmiş (tetiklenmemiş) story'nin
  içeriğine tetik dokunmaz (elle eşitleme yapar).
- Tur başına en çok `TETIK_SINIRI` (10) tetik (`tetiklendi`, `yeniden_tetiklendi`,
  `case_uretimi`); kalan story'ler hiç yazılmadan `ertelendi` olur ve sonraki turda yine "giren"
  sayılır.
- Her story kendi işleminde işlenir: biri hata verirse atlanır (`hata`), diğerleri sürer. Jira
  erişilemezse tur boş geçer (sabit Türkçe "Jira'ya erişilemedi"; ayrıntı yalnız log'da).
- Ayar kapalıysa Jira'ya gidilmez; iş yalnız kendini yeniden planlar.

Tetik Jira'ya yazmaz; başlattığı ön incelemenin kendi yazma yolları (bulgusuz bitişte PO'ya soru
yorumu + etiket) değişmez. PO kapısı korunur: tetik PO onayını atlatmaz.

**Otomatik case üretimi**: tetikle akışa alınmış gereksinim Jira PO etiketiyle `po_approved`'a
girince (`flow.po_check` → `po_onayi_sonrasi`) ya da `po_approved` story duruma girince
`requirements.otomatik_case` işi → `cases.service.start_generation(..., OTOMASYON_AKTORU)`. Kapı
kesin reddederse denetim + `reddedildi`; Jira'ya geçici erişilemezse (`GateClosed.__cause__`) iş
yeniden denenir, son denemede `reddedildi`.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.orm import Session

from tp_core.audit.session import audit_on_commit
from tp_core.features.otomasyon import ayarlar
from tp_core.features.requirements import flow, services
from tp_core.models import Requirement, TestCase, session_scope
from tp_core.workflow.jobs import enqueue, idempotency_lock
from tp_core.workflow.service import GateClosed, WorkflowError

log = logging.getLogger("tp_core.features.otomasyon.jira_tetik")

JOB_JIRA_TETIK = "requirements.jira_tetik"
JOB_OTOMATIK_CASE = "requirements.otomatik_case"

# Otomasyonun principal'ı (insan değil; rol kapıları bilinçli olarak atlanır, K4/K5).
JIRA_TETIK_AKTORU = ayarlar.OTOMASYON_AKTORU
# Jira'dan çekme (upsert) ve tetik denetim kayıtlarının aktörü.
CEKIM_AKTORU = "jira-tetik"

ARAMA_SINIRI = 1000
TETIK_SINIRI = 10
SONUC_SINIRI = 200
TUR_SAKLAMA = timedelta(hours=1)
SON_TETIKLENEN_SAYISI = 10

ETKIN_CASE = ("draft", "approved", "published")
AKIS_SURUYOR = ("in_review", "findings_open", "doc_final", "pending_po")
TETIK_SONUCLARI = frozenset({"tetiklendi", "yeniden_tetiklendi", "case_uretimi"})

JIRA_HATASI = "Jira'ya erişilemedi"
YAPILANDIRMA_HATASI = "Jira tetiği yapılandırması geçersiz (JIRA_PROJECT)"
STORY_HATASI = "Story işlenemedi; ayrıntı sunucu günlüğünde"
ISARET_NEDENI = "Tetik açıldığında zaten bu durumdaydı; tetiklenmedi"
ERTELEME_NEDENI = f"Tur başına en çok {TETIK_SINIRI} tetik; sonraki turda işlenecek"
DURUMDA_NEDENI = "Önceki turda işlendi; değişiklik yok"
YENIDEN_INCELEME_NEDENI = "İçerik değişti; sonraki turda yeniden ön incelemeye girer"
ELLE_BASLAT_NEDENI = "İçerik değişti; story tetik durumunda değil, ön incelemeyi elle başlatın"
_CEKIM_NEDENI = {
    "yeniden_kontrol": "Jira'da içerik değişti; tutarlılık denetimi yeniden koşuyor",
    "mesgul": "Jira'da içerik değişti; süren iş bitince yeniden değerlendirilecek",
    "guncellendi": "Jira'da içerik değişti",
    "degismedi": "Değişiklik yok",
}

_KONTROL = re.compile(r"[\x00-\x1f\x7f]")


# ------------------------------------------------------------------------------ JQL


def jql_dizesi(deger: str) -> str:
    """JQL çift tırnaklı dize: `\\` ve `"` kaçışlı, kontrol karakterleri boşluk."""
    temiz = _KONTROL.sub(" ", deger)
    return '"' + temiz.replace("\\", "\\\\").replace('"', '\\"') + '"'


def tetik_jql(proje: str, durum: str) -> str:
    if not flow._PROJE_RE.match(proje):
        raise flow.FlowInputError(f"Geçersiz JIRA_PROJECT: {proje!r}")
    return (
        f"project = {proje} AND issuetype = Story AND status = {jql_dizesi(durum)} ORDER BY key ASC"
    )


def _ayni_durum(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return False
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def _issue_hash(issue: Any) -> str:
    return flow.requirement_hash(
        issue.summary, issue.description, [str(a) for a in issue.acceptance_criteria]
    )


# ------------------------------------------------------------------------- tetik turu


@dataclass(frozen=True)
class _Kayit:
    """Turun başında kilitsiz okunan gereksinim özeti (karar için; yazım kilitle yapılır)."""

    durum: str
    jira_durumu: str | None
    tetikli: bool  # qa_tetik_zamani dolu
    hash: str
    etkin_case: bool


def _kayitlar(s: Session, keys: list[str]) -> dict[str, _Kayit]:
    if not keys:
        return {}
    reqs = list(s.scalars(select(Requirement).where(Requirement.jira_key.in_(keys))))
    caseli = set(
        s.scalars(
            select(TestCase.requirement_id)
            .where(
                TestCase.requirement_id.in_([r.id for r in reqs]),
                TestCase.durum.in_(ETKIN_CASE),
            )
            .group_by(TestCase.requirement_id)
        )
    )
    return {
        r.jira_key: _Kayit(
            r.durum,
            r.jira_durumu,
            r.qa_tetik_zamani is not None,
            flow.content_hash_of(r),
            r.id in caseli,
        )
        for r in reqs
        if r.jira_key
    }


def _kilitle(s: Session, key: str) -> Requirement:
    return s.scalars(select(Requirement).where(Requirement.jira_key == key).with_for_update()).one()


def _durum_yaz(req: Requirement, issue: Any, durum: str) -> None:
    yeni = (issue.status or durum)[:200]
    if req.jira_durumu != yeni:
        req.jira_durumu = yeni


def _etkin_case_var(s: Session, req_id: uuid.UUID) -> bool:
    n = s.scalar(
        select(func.count())
        .select_from(TestCase)
        .where(TestCase.requirement_id == req_id, TestCase.durum.in_(ETKIN_CASE))
    )
    return bool(n)


def _denetle(s: Session, req: Requirement, sonuc: str, **ek: Any) -> None:
    audit_on_commit(
        s,
        CEKIM_AKTORU,
        "requirements.jira_tetik",
        f"requirement:{req.id}",
        {"jira_key": req.jira_key, "durum": req.jira_durumu, "sonuc": sonuc, **ek},
    )


def _incelemeye_al(
    s: Session, req: Requirement, sonuc: str, cekim: str | None
) -> tuple[str, str | None]:
    req.qa_tetik_zamani = flow.now()
    basladi = flow.start_review(s, req, JIRA_TETIK_AKTORU)
    _denetle(s, req, sonuc, cekim=cekim, workflow_id=basladi.workflow_id, job_id=basladi.job_id)
    return sonuc, None


def isaretle(s: Session, issue: Any, durum: str, kayit: _Kayit | None) -> tuple[str, str | None]:
    """Taban turu: story yalnız işaretlenir (TP'de yoksa okunarak eklenir), tetiklenmez."""
    if kayit is None:
        flow.upsert_issue(s, issue, CEKIM_AKTORU)
    _durum_yaz(_kilitle(s, issue.key), issue, durum)
    return "isaretlendi", ISARET_NEDENI


def giris_isle(
    s: Session, issue: Any, durum: str, ayar: ayarlar.JiraTetik
) -> tuple[str, str | None]:
    """Duruma yeni giren story: çek, `jira_durumu` yaz, gereksinim durumuna göre akışa al."""
    cekim = flow.upsert_issue(s, issue, CEKIM_AKTORU)
    req = _kilitle(s, issue.key)
    _durum_yaz(req, issue, durum)
    if req.durum == "new":
        return _incelemeye_al(s, req, "tetiklendi", cekim)
    if req.durum == "po_approved":
        if _etkin_case_var(s, req.id):
            return "dokunulmadi", "PO onaylı; etkin case'leri var"
        if not ayar.otomatik_case:
            return "dokunulmadi", "PO onaylı; otomatik case üretimi kapalı, elle başlatın"
        req.qa_tetik_zamani = flow.now()
        zaman = req.qa_tetik_zamani.isoformat()
        job_id = enqueue(
            s.connection(),
            JOB_OTOMATIK_CASE,
            {"requirement_id": str(req.id), "tetik_zamani": zaman},
            idempotency_key=f"{JOB_OTOMATIK_CASE}:{req.id}:giris:{zaman}",
        )
        _denetle(s, req, "case_uretimi", cekim=cekim, job_id=job_id)
        return "case_uretimi", None
    if req.durum in AKIS_SURUYOR:
        req.qa_tetik_zamani = flow.now()
        _denetle(s, req, "akisa_alindi", cekim=cekim)
        return "akisa_alindi", "Akış sürüyor; PO onayı gelince case üretimi otomatik başlar"
    return "dokunulmadi", f"Gereksinim durumu: {req.durum}"


def durumda_isle(s: Session, issue: Any) -> tuple[str, str | None]:
    """Durumda kalan, tetikle akışa alınmış story: içerik değiştiyse çek; `new`'e döndüyse
    ön incelemeyi yeniden başlat (K15a)."""
    req = _kilitle(s, issue.key)
    cekim = None
    if req.qa_tetik_zamani is not None and flow.content_hash_of(req) != _issue_hash(issue):
        cekim = flow.upsert_issue(s, issue, CEKIM_AKTORU)
    if req.durum == "new" and req.qa_tetik_zamani is not None:
        return _incelemeye_al(s, req, "yeniden_tetiklendi", cekim)
    if cekim is None:
        return "durumda", DURUMDA_NEDENI
    return "guncellendi", _CEKIM_NEDENI.get(cekim, "Jira'da içerik değişti")


def _durumdan_cikanlar(s: Session, kalan: list[str]) -> int:
    """Tam listeli turda listede olmayan story'lerin `jira_durumu`'nu temizler (yalnız değişen)."""
    return s.execute(
        text(
            "UPDATE requirement SET jira_durumu = NULL WHERE kaynak = 'jira' "
            "AND jira_durumu IS NOT NULL AND NOT (jira_key = ANY(:k))"
        ),
        {"k": kalan},
    ).rowcount


def tur(engine: Engine | None = None, jira: Any = None) -> dict[str, Any]:
    """Bir tetik turu; dönen özet iş sonucuna (`job.sonuc`) yazılır."""
    with session_scope() as s:
        ayar = ayarlar.jira_tetik(s)
        taban = ayarlar.tetik_tabani(s)
    taban_var = taban is not None and _ayni_durum(taban.get("durum"), ayar.durum)
    ozet: dict[str, Any] = {
        "zaman": flow.now(),
        "acik": ayar.acik,
        "durum": ayar.durum,
        "taban": not taban_var,
        "bulunan": 0,
        "tetiklenen": 0,
        "ertelenen": 0,
        "hata": None,
        "tetiklenenler": [],
        "sonuclar": [],
    }
    if not ayar.acik:
        ozet["taban"] = False
        return ozet
    try:
        jql = tetik_jql(flow.settings().jira_project, ayar.durum)
    except flow.FlowInputError:
        log.warning("Jira tetiği: geçersiz JIRA_PROJECT")
        ozet["hata"] = YAPILANDIRMA_HATASI
        return ozet
    try:
        issues = (jira or services.jira()).search(jql, ARAMA_SINIRI)
    except Exception:  # Jira erişilemedi: sonraki tura kalır; ayrıntı yalnız log'da
        log.warning("Jira tetiği: arama başarısız", exc_info=True)
        ozet["hata"] = JIRA_HATASI
        return ozet
    tam = len(issues) < ARAMA_SINIRI
    if not tam:
        log.warning("Jira tetiği: %d story sınırına ulaşıldı; liste eksik olabilir", ARAMA_SINIRI)
    eslesen = [
        i
        for i in issues
        if (not i.issue_type or i.issue_type == "Story")
        and (not i.status or _ayni_durum(i.status, ayar.durum))  # arama-okuma arası değişim
    ]
    ozet["bulunan"] = len(eslesen)
    with session_scope() as s:
        kayitlar = _kayitlar(s, [i.key for i in eslesen])

    sonuclar: list[dict[str, Any]] = []
    hata_sayisi = 0
    for issue in eslesen:
        kayit = kayitlar.get(issue.key)
        durumda = kayit is not None and _ayni_durum(kayit.jira_durumu, ayar.durum)
        try:
            if not taban_var:
                if durumda:
                    sonuc: tuple[str, str | None] = ("isaretlendi", ISARET_NEDENI)
                else:
                    with session_scope() as s:
                        sonuc = isaretle(s, issue, ayar.durum, kayit)
            elif durumda:
                assert kayit is not None
                is_var = kayit.tetikli and (
                    kayit.durum == "new" or kayit.hash != _issue_hash(issue)
                )
                if not is_var:
                    sonuc = ("durumda", DURUMDA_NEDENI)
                elif ozet["tetiklenen"] >= TETIK_SINIRI:
                    sonuc = ("ertelendi", ERTELEME_NEDENI)
                else:
                    with session_scope() as s:
                        sonuc = durumda_isle(s, issue)
            else:
                sayilir = (
                    kayit is None
                    or kayit.durum == "new"
                    or kayit.hash != _issue_hash(issue)
                    or (
                        kayit.durum == "po_approved" and not kayit.etkin_case and ayar.otomatik_case
                    )
                )
                if sayilir and ozet["tetiklenen"] >= TETIK_SINIRI:
                    sonuc = ("ertelendi", ERTELEME_NEDENI)
                else:
                    with session_scope() as s:
                        sonuc = giris_isle(s, issue, ayar.durum, ayar)
        except Exception:  # tek story'nin hatası turu durdurmaz; ayrıntı yalnız log'da
            log.warning("Jira tetiği: %s işlenemedi", issue.key, exc_info=True)
            sonuc = ("hata", STORY_HATASI)
            hata_sayisi += 1
        if sonuc[0] in TETIK_SONUCLARI:
            ozet["tetiklenen"] += 1
            ozet["tetiklenenler"].append(issue.key)
        elif sonuc[0] == "ertelendi":
            ozet["ertelenen"] += 1
        sonuclar.append({"jira_key": issue.key, "sonuc": sonuc[0], "neden": sonuc[1]})

    if tam:
        try:
            with session_scope() as s:
                _durumdan_cikanlar(s, [i.key for i in eslesen])
        except Exception:
            log.warning("Jira tetiği: durumdan çıkanlar temizlenemedi", exc_info=True)
    if not taban_var and hata_sayisi == 0:
        with session_scope() as s:
            ayarlar.tetik_tabani_yaz(s, ayar.durum, ozet["zaman"])
    if hata_sayisi:
        ozet["hata"] = f"{hata_sayisi} story işlenemedi"
    # Önce eylemli sonuçlar; liste sınırlı (iş sonucu ve API yanıtı büyümesin).
    sonuclar.sort(key=lambda r: r["sonuc"] == "durumda")
    ozet["sonuclar"] = sonuclar[:SONUC_SINIRI]
    return ozet


# --------------------------------------------------------------------------- zamanlama


def ensure(conn: Connection, *, gecikme_s: float = 0.0) -> uuid.UUID | None:
    """Tetik işini (kuyrukta bekleyen yoksa) ekler; tek bekleyen iş kuralı advisory lock ile."""
    idempotency_lock(conn, JOB_JIRA_TETIK)
    bekleyen = conn.execute(
        text("SELECT id FROM job WHERE tur = :t AND durum IN ('queued', 'retry') LIMIT 1"),
        {"t": JOB_JIRA_TETIK},
    ).scalar_one_or_none()
    if bekleyen is not None:
        return None
    zaman = flow.now() + timedelta(seconds=gecikme_s) if gecikme_s > 0 else None
    return enqueue(conn, JOB_JIRA_TETIK, {}, run_after=zaman)


def ayar_degisti(conn: Connection, *, hemen: bool, aralik_s: int) -> None:
    """`jira_tetik` ayarı yazıldı: bekleyen turu öne çek (`run_after = min(mevcut, hedef)`).

    `hemen` (tetik açıldı ya da durum değişti): hedef şimdi; değilse `now + aralik_s`. Bekleyen
    tur yoksa (zincir kopmuş) hedef zamana yeni tur eklenir.
    """
    idempotency_lock(conn, JOB_JIRA_TETIK)
    hedef = flow.now() + (timedelta() if hemen else timedelta(seconds=aralik_s))
    n = conn.execute(
        text(
            "UPDATE job SET run_after = LEAST(run_after, :h) "
            "WHERE tur = :t AND durum IN ('queued', 'retry')"
        ),
        {"h": hedef, "t": JOB_JIRA_TETIK},
    ).rowcount
    if not n:
        enqueue(conn, JOB_JIRA_TETIK, {}, run_after=hedef)


def yeniden_planla(engine: Engine | None = None) -> datetime:
    """Sonraki turu `aralik_s` sonrasına planlar (ayar kapalıyken de: açılınca devreye girer)."""
    with session_scope() as s:
        aralik = ayarlar.jira_tetik(s).aralik_s
        ensure(s.connection(), gecikme_s=aralik)
    return flow.now() + timedelta(seconds=aralik)


def eski_turlari_sil(engine: Engine, saklama: timedelta = TUR_SAKLAMA) -> int:
    """Bitmiş tur işlerini siler; son taramalı tur (API'nin `son_tur`'u) hep kalır."""
    with engine.begin() as conn:
        return conn.execute(
            text(
                "DELETE FROM job WHERE tur = :t AND durum IN ('done', 'failed', 'cancelled') "
                "AND COALESCE(bitis, guncelleme) < now() - make_interval(secs => :sn) "
                "AND id <> COALESCE((SELECT id FROM job WHERE tur = :t AND durum = 'done' "
                "AND sonuc ? 'bulunan' AND (sonuc->>'acik')::boolean "
                "ORDER BY bitis DESC NULLS LAST LIMIT 1), "
                "'00000000-0000-0000-0000-000000000000'::uuid)"
            ),
            {"t": JOB_JIRA_TETIK, "sn": saklama.total_seconds()},
        ).rowcount


# ------------------------------------------------------------------ otomatik case üretimi


def po_onayi_sonrasi(s: Session, req: Requirement) -> uuid.UUID | None:
    """`po_check` PO etiketiyle `po_approved`'a geçişten hemen sonra (aynı işlemde) çağırır.

    Yalnız tetikle akışa alınmış (`qa_tetik_zamani` dolu) gereksinimde ve `otomatik_case`
    açıkken `requirements.otomatik_case` işini kuyruğa alır; aksi halde hiçbir şey yapmaz.
    """
    if req.qa_tetik_zamani is None:
        return None
    if not ayarlar.jira_tetik(s).otomatik_case:
        return None
    onay = req.po_onay_zamani.isoformat() if req.po_onay_zamani else ""
    return enqueue(
        s.connection(),
        JOB_OTOMATIK_CASE,
        {"requirement_id": str(req.id), "po_onay_zamani": onay},
        idempotency_key=f"{JOB_OTOMATIK_CASE}:{req.id}:{onay}",
    )


def _gecici_jira_hatasi(exc: BaseException) -> bool:
    """PO etiketi Jira'dan doğrulanamadı (erişim hatası): kesin ret değil, yeniden denenir."""
    return isinstance(exc, GateClosed) and exc.__cause__ is not None


def otomatik_case_baslat(yuk: dict[str, Any], *, son_deneme: bool = True) -> dict[str, Any]:
    """`requirements.otomatik_case` işinin gövdesi: case üretimini otomasyon aktörüyle başlatır.

    Jira'ya geçici erişilemezse (`GateClosed.__cause__` dolu) son deneme değilse hata yeniden
    fırlatılır ve iş geri çekilmeyle yeniden denenir; son denemede `reddedildi` yazılır.
    """
    from tp_core.features.cases import service as cases_service
    from tp_core.features.otomasyon.otokod import savepoint

    req_id = uuid.UUID(str(yuk["requirement_id"]))
    with session_scope() as s:
        req = s.get(Requirement, req_id, with_for_update=True)
        if req is None:
            return {"durum": "atlandi", "neden": "gereksinim yok"}
        nesne = f"requirement:{req.id}"
        tetikleyen = "jira-durum-tetigi" if yuk.get("tetik_zamani") else "jira-po-onayi"
        temel = {"jira_key": req.jira_key, "tetikleyen": tetikleyen}
        if not ayarlar.jira_tetik(s).otomatik_case:
            audit_on_commit(s, CEKIM_AKTORU, "requirements.otomatik_case", nesne,
                            {**temel, "sonuc": "kapali"})  # fmt: skip
            return {"durum": "kapali"}
        if req.durum != "po_approved" or req.qa_tetik_zamani is None:
            # Analist elle başlatmış ya da onay geri çekilmiş: dokunma.
            return {"durum": "atlandi", "neden": f"gereksinim durumu {req.durum}"}
        try:
            with savepoint(s):
                out = cases_service.start_generation(s, req.id, JIRA_TETIK_AKTORU)
        except WorkflowError as exc:
            if _gecici_jira_hatasi(exc) and not son_deneme:
                log.warning("%s: otomatik case: Jira erişilemedi, yeniden denenecek", req.jira_key)
                raise
            neden = (str(exc).strip() or type(exc).__name__)[:300]
            audit_on_commit(s, CEKIM_AKTORU, "requirements.otomatik_case", nesne,
                            {**temel, "sonuc": "reddedildi", "neden": neden})  # fmt: skip
            return {"durum": "reddedildi", "neden": neden}
        audit_on_commit(
            s, CEKIM_AKTORU, "requirements.otomatik_case", nesne,
            {**temel, "sonuc": "baslatildi", "job_id": out["job_id"],
             "uretim_no": out["uretim_no"]},
        )  # fmt: skip
        return {"durum": "baslatildi", "job_id": out["job_id"], "uretim_no": out["uretim_no"]}


# ------------------------------------------------------------ otomatik akış (serileştirme)


def _akis(durum: str, neden: str | None, req: Requirement) -> dict[str, Any]:
    zaman = req.qa_tetik_zamani
    return {
        "tetik_zamani": zaman.isoformat() if zaman is not None else None,
        "durum": durum,
        "neden": neden,
    }


def _case_isi_akisi(req: Requirement, is_: Any, otomatik_case: bool) -> dict[str, Any]:
    if is_ is None:
        if not otomatik_case:
            return _akis("durdu", "Otomatik case üretimi kapalı; case üretimini elle başlatın", req)
        return _akis("durdu", "Otomatik case üretimi başlatılmadı; elle başlatın", req)
    if is_.durum in ("queued", "running", "retry"):
        return _akis("suruyor", "Case üretimi başlatılıyor", req)
    if is_.durum != "done":
        return _akis(
            "durdu", "Otomatik case üretimi başlatılamadı (Jira'ya erişilemedi); elle başlatın", req
        )
    sonuc = is_.sonuc if isinstance(is_.sonuc, dict) else {}
    d = sonuc.get("durum")
    if d == "reddedildi":
        return _akis("durdu", f"Case üretimi reddedildi: {sonuc.get('neden') or '—'}", req)
    if d == "kapali":
        return _akis("durdu", "Otomatik case üretimi kapalı; case üretimini elle başlatın", req)
    if d == "atlandi":
        return _akis("durdu", "Otomatik case üretimi atlandı; elle başlatın", req)
    return _akis("suruyor", "Case üretimi başlatıldı", req)


def otomatik_akis_hepsi(s: Session, reqs: list[Requirement]) -> dict[uuid.UUID, Any]:
    """Gereksinim → `otomatik_akis` rozeti (`{tetik_zamani, durum, neden}` ya da None).

    Yalnız tetikle akışa alınmış (`qa_tetik_zamani` dolu) gereksinimde doludur:
    - `tamam`: `cases_ready` / `done` (case'ler yazıldı).
    - `suruyor`: `in_review`, `doc_final` (ön inceleme/denetim), `pending_po` (PO onayı
      bekleniyor), `generating` (case üretimi), `po_approved` + bekleyen/süren otomatik case işi,
      `new` + story hâlâ tetik durumunda ve tetik açık (sonraki turda yeniden ön inceleme).
    - `durdu` (+ neden; insan adımı gerekir): `failed` (ön inceleme ya da case üretimi başarısız),
      `findings_open` (bulgular analist kararı bekliyor), `po_approved` + otomatik case işi
      reddedildi / kapalı / atlandı / başlatılamadı ya da hiç başlatılmadı, `new` + story tetik
      durumunda değil ya da tetik kapalı (içerik değişti, elle başlatılmalı).
    """
    tetikli = [r for r in reqs if r.qa_tetik_zamani is not None]
    if not tetikli:
        return {r.id: None for r in reqs}
    ayar = ayarlar.jira_tetik(s)
    onayli = [str(r.id) for r in tetikli if r.durum == "po_approved"]
    isler: dict[str, Any] = {}
    if onayli:
        for row in s.execute(
            text(
                "SELECT DISTINCT ON (yuk->>'requirement_id') yuk->>'requirement_id' AS rid, "
                "durum, sonuc, olusturma FROM job WHERE tur = :t "
                "AND yuk->>'requirement_id' = ANY(:ids) "
                "ORDER BY yuk->>'requirement_id', olusturma DESC"
            ),
            {"t": JOB_OTOMATIK_CASE, "ids": onayli},
        ):
            isler[row.rid] = row
    out: dict[uuid.UUID, Any] = {}
    for r in reqs:
        if r.qa_tetik_zamani is None:
            out[r.id] = None
            continue
        d = r.durum
        if d in ("cases_ready", "done"):
            out[r.id] = _akis("tamam", None, r)
        elif d in ("in_review", "doc_final"):
            out[r.id] = _akis("suruyor", "Ön inceleme sürüyor", r)
        elif d == "pending_po":
            out[r.id] = _akis("suruyor", "PO onayı bekleniyor", r)
        elif d == "generating":
            out[r.id] = _akis("suruyor", "Case üretimi sürüyor", r)
        elif d == "findings_open":
            out[r.id] = _akis("durdu", "Tutarlılık bulguları analist kararı bekliyor", r)
        elif d == "failed":
            neden = (
                "Case üretimi başarısız oldu; yeniden başlatın"
                if r.po_onaylayan
                else "Ön inceleme başarısız oldu; gereksinim ekranından yeniden başlatın"
            )
            out[r.id] = _akis("durdu", neden, r)
        elif d == "po_approved":
            is_ = isler.get(str(r.id))
            if is_ is not None and is_.olusturma < r.qa_tetik_zamani:
                is_ = None  # önceki akışın işi
            out[r.id] = _case_isi_akisi(r, is_, ayar.otomatik_case)
        elif d == "new" and ayar.acik and _ayni_durum(r.jira_durumu, ayar.durum):
            out[r.id] = _akis("suruyor", YENIDEN_INCELEME_NEDENI, r)
        else:
            out[r.id] = _akis("durdu", ELLE_BASLAT_NEDENI, r)
    return out


def otomatik_akis(s: Session, req: Requirement) -> dict[str, Any] | None:
    return otomatik_akis_hepsi(s, [req])[req.id]


# ------------------------------------------------------------------------- durum (API)


def _sonuc_satiri(r: Any) -> dict[str, Any] | None:
    if not isinstance(r, dict) or not r.get("jira_key"):
        return None
    return {"jira_key": r.get("jira_key"), "sonuc": r.get("sonuc"), "neden": r.get("neden")}


def durum_ozeti(s: Session) -> dict[str, Any]:
    """`GET /automation/jira-trigger` gövdesi."""
    ayar = ayarlar.jira_tetik(s)
    son = s.execute(
        text(
            "SELECT sonuc FROM job WHERE tur = :t AND durum = 'done' AND sonuc ? 'bulunan' "
            "AND (sonuc->>'acik')::boolean ORDER BY bitis DESC NULLS LAST LIMIT 1"
        ),
        {"t": JOB_JIRA_TETIK},
    ).scalar_one_or_none()
    son_tur = None
    if isinstance(son, dict):
        son_tur = {
            "zaman": son.get("zaman"),
            "bulunan": int(son.get("bulunan") or 0),
            "tetiklenen": int(son.get("tetiklenen") or 0),
            "ertelenen": int(son.get("ertelenen") or 0),
            "taban": bool(son.get("taban")),
            "hata": son.get("hata"),
            "sonuclar": [
                x for x in (_sonuc_satiri(r) for r in son.get("sonuclar") or []) if x is not None
            ],
        }
    satirlar = s.execute(
        text(
            "SELECT ozet->>'jira_key' AS jira_key, ozet->>'sonuc' AS sonuc, zaman "
            "FROM audit_event WHERE eylem = 'requirements.jira_tetik' ORDER BY id DESC LIMIT :n"
        ),
        {"n": SON_TETIKLENEN_SAYISI},
    ).all()
    return {
        "acik": ayar.acik,
        "durum": ayar.durum,
        "aralik_s": ayar.aralik_s,
        "son_tur": son_tur,
        "son_tetiklenenler": [
            {"jira_key": r.jira_key, "zaman": r.zaman, "sonuc": r.sonuc or "tetiklendi"}
            for r in satirlar
        ],
    }
