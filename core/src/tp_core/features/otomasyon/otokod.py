"""Case onayı sonrası otomatik kod üretimi (specs/013-sprint-otomasyonu §3.2, K4).

Tekli karar (`approve` / `edit`) ve toplu onay, onay yazıldıktan sonra `kuyruga_al`ı çağırır.
Kod üretimi sistem aktörüyle (`OTOMASYON_AKTORU`) başlar; onaylayan kullanıcı `tetikleyen`
olarak iş akışı yüküne ve denetime yazılır. Engineer rol kapısı bilinçli olarak atlanır: kod
üretimi yalnızca onaylı içerikle başlar (Constitution I), PR merge'ü yine insan işidir.

Kural: otomatik kod üretimi **onayı asla geri almaz**. Üretim kendi SAVEPOINT'inde başlar;
reddedilir ya da beklenmedik biçimde patlarsa yalnız o SAVEPOINT geri alınır.

Toplu onay (K16) üretimi onay isteğinden ayırır: `toplu_kuyruga_al` tek `codegen.otomatik` işi
kuyruğa alır; iş (`toplu_uret`, işleyici `codegen/jobs.py`) `MAX_CASE`'lik parçalarla
`start_generation` çağırır. Otomatik üretim süren ya da açık PR'lı script'e dokunmaz (K16,
`codegen.service.start_generation`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from tp_core.audit.session import _ANAHTAR as _DENETIM_ANAHTARI
from tp_core.audit.session import audit_on_commit
from tp_core.features.codegen import platform as platformlar
from tp_core.features.codegen.service import MAX_CASE, CodegenRejected, start_generation
from tp_core.features.otomasyon import ayarlar
from tp_core.models import Job, Review, Script, TestCase, session_scope
from tp_core.models.codegen_feature import ScriptCodegen
from tp_core.workflow.jobs import enqueue
from tp_core.workflow.service import Principal

log = logging.getLogger(__name__)

OTOMASYON_AKTORU = ayarlar.OTOMASYON_AKTORU
JOB_OTOMATIK_KOD = "codegen.otomatik"

# start_generation'ın "zaten var" sonuçları: yeni üretim gerekmiyor.
ATLANAN_SONUCLAR = frozenset({"suruyor", "pr_acik", "merge_edildi", "dogrulanmamis_var"})

HATA_NEDENI = (
    "Otomatik kod üretimi beklenmedik bir hatayla başlatılamadı; onay geçerli. "
    "Kod üretimi ekranından elle başlatın."
)


class _GeriAl(Exception):
    """`savepoint` içinden yalnız SAVEPOINT'i geri almak için (dışarı sızmaz)."""


@contextmanager
def savepoint(session: Session) -> Iterator[None]:
    """SAVEPOINT + bekleyen denetim kayıtlarının birlikte geri alınması.

    `audit_on_commit` kayıtları oturumda bekler ve SAVEPOINT geri alımında atılmaz
    (`audit/session.py`); burada geri alınan bölümün eklediği kayıtlar da düşürülür.
    Hata yeniden fırlatılır (çağıran yakalar).
    """
    bekleyen = session.info.get(_DENETIM_ANAHTARI)
    once = len(bekleyen) if bekleyen else 0
    sp = session.begin_nested()
    try:
        yield
    except BaseException:
        if sp.is_active:
            sp.rollback()
        liste = session.info.get(_DENETIM_ANAHTARI)
        if liste is not None:
            del liste[once:]
        raise
    else:
        if sp.is_active:
            sp.commit()


def _sonuc(durum: str, neden: str | None = None, script_id: str | None = None) -> dict[str, Any]:
    return {"durum": durum, "neden": neden, "script_id": script_id}


# Denetime (`GET /audit`, tüm roller) giden sabit metin: istisna metni SQL parametrelerini (case
# içeriği, çözülmüş test verisi) taşıyabilir; ayrıntı yalnız log'da (§9, güvenlik #4).
DENETIM_HATA_METNI = "Otomatik kod üretimi başlatılamadı; ayrıntı sunucu günlüğünde"


def _hata_ozeti(exc: BaseException, **ek: Any) -> dict[str, Any]:
    """`codegen.otomatik_hata` denetim özeti: istisna sınıfı + sabit Türkçe metin."""
    return {**ek, "hata": type(exc).__name__, "mesaj": DENETIM_HATA_METNI}


def kuyruga_al(session: Session, tc: TestCase, onaylayan: Principal) -> dict[str, Any]:
    """Onaylanan case için web kod üretimini kuyruğa alır.

    Dönen `durum`: `kuyrukta` (script_id dolu) | `atlandi` (süren üretim / açık ya da merge
    edilmiş PR) | `reddedildi` (kod üretimi kapısı; neden Türkçe) | `kapali` (ayar kapalı) |
    `hata` (beklenmedik; onay geçerli, denetim `codegen.otomatik_hata`).
    """
    if not ayarlar.otomatik_kod(session).acik:
        return _sonuc("kapali", "Otomatik kod üretimi ayarı kapalı")
    if tc.durum != "approved":
        return _sonuc("atlandi", f"case onaylı değil (durum: {tc.durum})")
    try:
        with savepoint(session):
            cevap = start_generation(
                session,
                [tc.id],
                OTOMASYON_AKTORU,
                platform=platformlar.WEB,
                dil=None,  # 011: hedef repodan algılanan dil
                tetik="otomatik",
                tetikleyen=onaylayan.kullanici_adi,
            )
    except CodegenRejected as exc:
        return _sonuc("reddedildi", str(exc))
    except Exception as exc:
        log.exception("otomatik kod üretimi başlatılamadı (case %s)", tc.id)
        audit_on_commit(
            session,
            OTOMASYON_AKTORU.kullanici_adi,
            "codegen.otomatik_hata",
            f"test_case:{tc.id}",
            _hata_ozeti(exc, tetikleyen=onaylayan.kullanici_adi),
        )
        return _sonuc("hata", HATA_NEDENI)
    return _ogeden((cevap.get("sonuclar") or [{}])[0], cevap.get("mesaj"))


def _ogeden(oge: dict[str, Any], mesaj: str | None = None) -> dict[str, Any]:
    """`start_generation` öğe sonucu → otomatik kod sonucu."""
    durum = oge.get("durum")
    if durum == "basladi":
        return _sonuc("kuyrukta", None, oge.get("script_id"))
    if durum in ATLANAN_SONUCLAR:
        return _sonuc("atlandi", oge.get("neden"), oge.get("script_id"))
    return _sonuc("reddedildi", oge.get("neden") or mesaj)


# ---------------------------------------------------------------- toplu onay (K16)


SURUYOR_NEDENI = "Kod üretimi sürüyor"
PARCA_HATA_NEDENI = (
    "Otomatik kod üretimi beklenmedik bir hatayla başlatılamadı; onay geçerli. "
    "Kod üretimi ekranından elle başlatın."
)


def _onceden_atlananlar(session: Session, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Kuyruğa almadan önce bilinen atlamalar (K16; `start_generation` ile aynı kural): web
    platformunda üretimi gerçekten süren (`AKTIF` ve işi bitmemiş) ya da açık PR'lı
    (`pr_open`) script'i olan case.

    Takılı script (`AKTIF` ama işi bitmiş: iş dışı çöküş) atlanmaz: işte `start_generation`
    `recover_stuck` ile kurtarıp yeniden üretir. Takılılık kuralı `recover_stuck`'ınkiyle aynı
    yardımcıdan (`_job_bitti`) gelir; burada durum yazılmaz (onay isteği salt okur).
    """
    from tp_core.features.codegen.service import AKTIF, OTOMATIK_PR_ACIK, _job_bitti

    out: dict[uuid.UUID, str] = {}
    for cid, durum, job_id in session.execute(
        select(ScriptCodegen.test_case_id, Script.durum, ScriptCodegen.job_id)
        .join(Script, Script.id == ScriptCodegen.script_id)
        .where(
            ScriptCodegen.test_case_id.in_(ids),
            Script.platform == platformlar.WEB,
            Script.durum.in_([*AKTIF, "pr_open"]),
        )
    ).all():
        if durum in AKTIF:
            if _job_bitti(session, job_id) is None:
                out[cid] = SURUYOR_NEDENI
        else:
            out.setdefault(cid, OTOMATIK_PR_ACIK)
    return out


def toplu_kuyruga_al(
    session: Session, case_ids: Sequence[uuid.UUID], onaylayan: Principal
) -> dict[str, Any]:
    """Toplu onayda onaylanan case'ler için tek `codegen.otomatik` işi (onayla aynı işlemde).

    Dönen (bulk yanıtı üst düzey `otomatik_kod`): `{durum: "kuyrukta"|"kapali"|"yok", job_id,
    case_sayisi, atlanan: [{case_id, neden}]}`. Üretimi süren ya da açık PR'lı case'ler
    (K16) işe alınmaz, `atlanan`da nedeniyle döner; `case_sayisi` yalnız işe alınanlardır
    (hepsi atlandıysa `yok`). Kapının kesin kararı (ör. engel, merge edilmiş PR) işte verilir;
    case başına sonuç `GET /automation/codegen-jobs/{job_id}`. İdempotent anahtar işe alınan
    case'lerin onay review kayıtlarından türer (aynı onay kümesi = aynı iş).
    """
    ids = list(dict.fromkeys(case_ids))
    if not ids:
        return {"durum": "yok", "job_id": None, "case_sayisi": 0, "atlanan": []}
    if not ayarlar.otomatik_kod(session).acik:
        return {"durum": "kapali", "job_id": None, "case_sayisi": 0, "atlanan": []}
    onceden = _onceden_atlananlar(session, ids)
    atlanan = [{"case_id": str(c), "neden": onceden[c]} for c in ids if c in onceden]
    ids = [c for c in ids if c not in onceden]
    if not ids:
        return {"durum": "yok", "job_id": None, "case_sayisi": 0, "atlanan": atlanan}
    son_review = {
        nesne_id: rid
        for nesne_id, rid in session.execute(
            select(Review.nesne_id, func.max(Review.sira))
            .where(Review.nesne_turu == "test_case", Review.nesne_id.in_(ids))
            .group_by(Review.nesne_id)
        ).all()
    }
    ozet = "|".join(f"{cid}:{son_review.get(cid)}" for cid in sorted(ids))
    anahtar = f"{JOB_OTOMATIK_KOD}:{hashlib.sha256(ozet.encode()).hexdigest()[:32]}"
    job_id = enqueue(
        session.connection(),
        JOB_OTOMATIK_KOD,
        {
            "case_ids": [str(c) for c in ids],
            "tetikleyen": onaylayan.kullanici_adi,
        },
        idempotency_key=anahtar,
    )
    return {
        "durum": "kuyrukta",
        "job_id": str(job_id),
        "case_sayisi": len(ids),
        "atlanan": atlanan,
    }


class GeciciHata(Exception):
    """Parça geçici bir hatayla (DB bağlantısı, forge erişimi) başlatılamadı: iş yeniden denenir.

    Mesaj yalnız istisna sınıfını taşır (`job.son_hata`'ya SQL parametreleri yazılmasın)."""


def gecici_hata_mi(exc: BaseException) -> bool:
    """Yeniden denemeye değer hata: DB bağlantı/işletim hatası ya da forge erişimi (doğrulama,
    bulunamadı ve koruma hataları kalıcıdır)."""
    from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
    from sqlalchemy.exc import TimeoutError as HavuzZamanAsimi

    from tp_core.integrations.forge import (
        ForgeError,
        ForgeNotFoundError,
        ForgeProtectionError,
        ForgeValidationError,
    )

    if isinstance(exc, OperationalError | InterfaceError | HavuzZamanAsimi):
        return True
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return True
    if isinstance(exc, ForgeError):
        return not isinstance(exc, ForgeValidationError | ForgeNotFoundError | ForgeProtectionError)
    return isinstance(exc, ConnectionError | TimeoutError)


_ILERLEME = "ara"  # job.sonuc'ta iş sürerken tamamlanan parçalar (yeniden denemede korunur)


def _ilerleme_yaz(
    s: Session, job_id: uuid.UUID | None, sonraki: int, sonuclar: list[dict[str, Any]]
) -> None:
    """Tamamlanan parçaları işin satırına yazar (parçanın kendi işleminde: atomik)."""
    if job_id is None:
        return
    s.execute(
        text("UPDATE job SET sonuc = CAST(:s AS jsonb) WHERE id = :id AND durum = 'running'"),
        {
            "id": job_id,
            "s": json.dumps({_ILERLEME: {"sonraki": sonraki, "sonuclar": sonuclar}}),
        },
    )


def _ilerleme_oku(job_id: uuid.UUID | None) -> tuple[int, list[dict[str, Any]]]:
    if job_id is None:
        return 0, []
    with session_scope() as s:
        sonuc = s.scalar(select(Job.sonuc).where(Job.id == job_id))
    ara = sonuc.get(_ILERLEME) if isinstance(sonuc, dict) else None
    if not isinstance(ara, dict) or not isinstance(ara.get("sonraki"), int):
        return 0, []
    return ara["sonraki"], [o for o in ara.get("sonuclar") or [] if isinstance(o, dict)]


def _parca_uret(
    parca: list[uuid.UUID],
    tetikleyen: str | None,
    *,
    job_id: uuid.UUID | None = None,
    sonraki: int = 0,
    onceki: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Bir parça kendi işleminde. Kesin ret (`CodegenRejected`) parça sonucudur; diğer hatalar
    çağırana yükselir (işlem geri alınır). İlerleme (`onceki` + bu parça) aynı işlemde yazılır."""
    with session_scope() as s:
        if not ayarlar.otomatik_kod(s).acik:
            out = [
                {"case_id": str(c), **_sonuc("kapali", "Otomatik kod üretimi ayarı kapalı")}
                for c in parca
            ]
        else:
            try:
                with savepoint(s):
                    cevap = start_generation(
                        s,
                        parca,
                        OTOMASYON_AKTORU,
                        platform=platformlar.WEB,
                        dil=None,  # 011: hedef repodan algılanan dil
                        tetik="otomatik",
                        tetikleyen=tetikleyen,
                    )
            except CodegenRejected as exc:
                out = [{"case_id": str(c), **_sonuc("reddedildi", str(exc))} for c in parca]
            else:
                out = [
                    {"case_id": o.get("case_id"), **_ogeden(o, cevap.get("mesaj"))}
                    for o in cevap.get("sonuclar") or []
                ]
        _ilerleme_yaz(s, job_id, sonraki, [*(onceki or []), *out])
        return out


def toplu_uret(
    yuk: dict[str, Any], *, job_id: uuid.UUID | None = None, son_deneme: bool = True
) -> dict[str, Any]:
    """`codegen.otomatik` işinin gövdesi: `MAX_CASE`'lik parçalarla `start_generation`.

    Her parça kendi işleminde (önceki parçaların üretimi kalıcı). Ayar iş sırasında kapanırsa
    kalan case'ler `kapali`. Hata izolasyonu (backend #8):

    - **Geçici hata** (`gecici_hata_mi`: DB bağlantısı, forge erişimi) ve son deneme değil:
      iş `GeciciHata` ile yeniden denenir. Tamamlanan parçaların sonucu `job.sonuc["ara"]`'da
      (parçanın kendi işleminde yazılır) korunur; yeniden deneme kaldığı parçadan sürer.
      Parça idempotenttir: işlem geri alındığı için yarım üretim kalmaz.
    - **Kalıcı hata** (ya da son denemedeki geçici hata): yalnız o parçanın case'leri `hata`,
      denetime `codegen.otomatik_hata` (istisna sınıfı + sabit metin) yazılır, sonraki parçaya
      geçilir.

    Dönen (`job.sonuc`): `{tetikleyen, case_sayisi, ozet: {durum: n}, sonuclar: [{case_id,
    durum: kuyrukta|atlandi|reddedildi|kapali|hata, neden, script_id}]}`.
    """
    ids = [uuid.UUID(str(c)) for c in yuk.get("case_ids") or []]
    tetikleyen = yuk.get("tetikleyen")
    baslangic, sonuclar = _ilerleme_oku(job_id)
    for i in range(baslangic, len(ids), MAX_CASE):
        parca = ids[i : i + MAX_CASE]
        sonraki = i + len(parca)
        try:
            sonuclar += _parca_uret(
                parca, tetikleyen, job_id=job_id, sonraki=sonraki, onceki=sonuclar
            )
        except Exception as exc:
            log.exception("otomatik kod: parça %d başlatılamadı", i // MAX_CASE + 1)
            if gecici_hata_mi(exc) and not son_deneme:
                raise GeciciHata(type(exc).__name__) from exc
            sonuclar += [{"case_id": str(c), **_sonuc("hata", PARCA_HATA_NEDENI)} for c in parca]
            try:
                with session_scope() as s:
                    audit_on_commit(
                        s,
                        OTOMASYON_AKTORU.kullanici_adi,
                        "codegen.otomatik_hata",
                        None,
                        _hata_ozeti(exc, tetikleyen=tetikleyen, case_ids=[str(c) for c in parca]),
                    )
                    _ilerleme_yaz(s, job_id, sonraki, sonuclar)
            except Exception:
                log.exception("otomatik kod: hata denetimi yazılamadı")
    ozet: dict[str, int] = {}
    for o in sonuclar:
        ozet[o["durum"]] = ozet.get(o["durum"], 0) + 1
    return {"tetikleyen": tetikleyen, "case_sayisi": len(ids), "ozet": ozet, "sonuclar": sonuclar}


# ------------------------------------------------------------------ iş sonucu (API)

IS_DURUMU_HATA = "İş başarısız oldu; ayrıntı sunucu günlüğünde"


def is_ozeti(session: Session, job_id: uuid.UUID) -> dict[str, Any] | None:
    """`GET /automation/codegen-jobs/{job_id}` gövdesi (iş yoksa ya da tür farklıysa None).

    `{job_id, durum: queued|running|retry|done|failed|cancelled, tetikleyen, case_ids,
    case_sayisi, olusturma, bitis, ozet: {durum: n}|null, sonuclar: [...]|[], hata: str|null}`;
    `sonuclar` iş bitince dolar (`toplu_uret` biçimi). İstisna ayrıntısı dönmez.
    """
    job = session.get(Job, job_id)
    if job is None or job.tur != JOB_OTOMATIK_KOD:
        return None
    yuk = job.yuk if isinstance(job.yuk, dict) else {}
    sonuc = job.sonuc if isinstance(job.sonuc, dict) else {}
    case_ids = [str(c) for c in yuk.get("case_ids") or []]
    return {
        "job_id": str(job.id),
        "durum": job.durum,
        "tetikleyen": yuk.get("tetikleyen"),
        "case_ids": case_ids,
        "case_sayisi": len(case_ids),
        "olusturma": job.olusturma,
        "bitis": job.bitis,
        "ozet": sonuc.get("ozet") if sonuc else None,
        "sonuclar": list(sonuc.get("sonuclar") or []),
        "hata": IS_DURUMU_HATA if job.durum == "failed" else None,
    }
