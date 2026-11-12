"""Ekilmiş hata koşusu (F3; specs/012-test-kalite-dogrulama/ANALIZ.md §4.6, §4.7, §5).

Kontrol Kulesi'nden elle başlatılır (K5; `engineer`, `presenter` — V4). Seçilen platformlar
**sırayla** koşar; platform başına:

1. `temel`: hatasız tam suite. Yeşil değilse platformun kalan adımları `gecersiz` ("temel koşu
   yeşil değil") ve sonraki platforma geçilir.
2. `hata`: her hata için tam suite (`fault=<kod>`). ≥1 test assertion ile kırmızı → `yakalandi`;
   tümü yeşil → `kacti`; ortam/altyapı/derleme hatası, toolchain'e ulaşılamaması, cihaz/Appium
   kapalı → `gecersiz` (Türkçe `neden`).
3. `kapanis`: hatasız tam suite; yeşil değilse koşu `uyarilar`'a not düşer.

Her adım bir toolchain `/check`'tir: CI'ın o platform için gönderdiği gövde (`test_files=[]`,
`check_body_platformu`), `retries=0`, `repeat_each=1`. Koşu `run` tablosuna `tetik='break_verify'`
ile yazılır (V6) ve sonuçlar codegen kontrolleri gibi `ingest_check_report` ile işlenir (koşu
detay sayfası aynen çalışır). `run.ortam`: `hata_kodu`, `hata_kosusu_id`, `hata_kosusu_asama`,
`platform`. Bu tetik Kontrol Kulesi KPI'larından (`_kirma_degil`) dışlanır; triage
`ortam.hata_kosusu_id` taşıyan koşuyu sınıflandırmaz (bug taslağı açılmaz).

Tek süren koşu kuralı servistedir (advisory lock + sorgu; DB kısıtı yok). İş kesilirse (worker
durdu, süre aşıldı) koşu `failed` + nedenle kapanır: yeni başlatma isteği, liste/detay okuması ve
worker açılışı (`jobs.on_worker_start`) işi bitmiş süren koşuları kapatır.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.events.bus import publish_tx
from tp_core.features.ci import services as ci_services
from tp_core.features.ci.clients import ToolchainError, check_timeout_s
from tp_core.features.codegen.classify import classify, java_raporu_mu, test_error_kind
from tp_core.features.hata_kosusu import katalog as kat
from tp_core.features.karar_tablosu.hatalar import HataKosusuSuruyor
from tp_core.models import AppUser, HataKosusu, HataKosusuAdim, Run, enums, session_scope
from tp_core.workflow import jobs as jobq
from tp_core.workflow.jobs import JobContext, PermanentJobError
from tp_core.workflow.service import Principal, WorkflowError

log = logging.getLogger("tp_core.hata_kosusu")

JOB = "hata_kosusu.calistir"
OLAY = "hata_kosusu.ilerleme"
# Platformlar bu sırayla koşar (web önce; uygulama platformları cihaz/VM ister).
PLATFORM_SIRASI = ("web", "android", "ios", "windows")
KILIT = "hata_kosusu:tek"
TEMEL_YESIL_DEGIL = "temel koşu yeşil değil"
YARIM_KALDI = "Koşu yarıda kaldı (worker durdu, süre aşıldı ya da iş başarısız oldu)"
# İş süre sınırı: adım başına toolchain `/check` istemci zaman aşımı + pay (commit çözümü, kayıt).
IS_PAYI_S = 600
ADIM_PAYI_S = 60
GECEN = ("passed", "expected", "flaky")
MAX_NEDEN = 500
MAX_KIRAN = 50


class GecersizIstek(ValueError):
    """İstek gövdesi geçersiz (bilinmeyen platform ya da hata kodu); API 422."""


def _simdi() -> datetime:
    return datetime.now(UTC)


def _kirp(metin: Any, n: int = MAX_NEDEN) -> str | None:
    if metin is None:
        return None
    s = " ".join(str(metin).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _oran(pay: int, payda: int) -> float | None:
    return round(pay / payda, 4) if payda else None


def is_zaman_asimi_s(adim_sayisi: int) -> int:
    """Tüm koşuyu kapsayan iş süre sınırı: adım × (`/check` istemci zaman aşımı + pay) + pay."""
    return int(max(adim_sayisi, 1) * (check_timeout_s() + ADIM_PAYI_S) + IS_PAYI_S)


# ============================================================================== doğrulama


def platformlari_dogrula(platformlar: Iterable[str]) -> list[str]:
    secilen = list(dict.fromkeys(platformlar))
    if not secilen:
        raise GecersizIstek("En az bir platform seçilmeli (web, android, ios, windows).")
    bilinmeyen = [p for p in secilen if p not in enums.PLATFORM]
    if bilinmeyen:
        raise GecersizIstek(
            f"Bilinmeyen platform: {', '.join(map(str, bilinmeyen))} (web, android, ios, windows)."
        )
    return [p for p in PLATFORM_SIRASI if p in secilen]


def hatalari_dogrula(hatalar: Iterable[str] | None) -> list[str]:
    tum = kat.kodlar()
    if hatalar is None:
        return tum
    secilen = list(dict.fromkeys(hatalar))
    if not secilen:
        raise GecersizIstek("En az bir hata seçilmeli (boş bırakılırsa kataloğun tamamı koşar).")
    bilinmeyen = [h for h in secilen if h not in tum]
    if bilinmeyen:
        raise GecersizIstek(f"Katalogda olmayan hata kodu: {', '.join(map(str, bilinmeyen))}.")
    return [h for h in tum if h in secilen]


# ============================================================================== olay, iş


def _olay(
    session: Session,
    kosu: HataKosusu,
    *,
    platform: str | None = None,
    hata_kodu: str | None = None,
    asama: str | None = None,
    sonuc: str | None = None,
) -> None:
    publish_tx(
        session.connection(),
        OLAY,
        {
            "id": str(kosu.id),
            "durum": kosu.durum,
            "platform": platform,
            "hata_kodu": hata_kodu,
            "asama": asama,
            "sonuc": sonuc,
        },
    )


def is_anahtari(kosu_id: uuid.UUID) -> str:
    return f"{JOB}:{kosu_id}"


def _is_bitti(session: Session, kosu_id: uuid.UUID) -> str | None:
    """Koşunun işi bitmişse (done/failed/cancelled ya da kayıt yok) son hata/durum; sürüyorsa
    None."""
    row = session.execute(
        text("SELECT durum, son_hata FROM job WHERE idempotency_key = :k"),
        {"k": is_anahtari(kosu_id)},
    ).first()
    if row is None:
        return "iş kaydı yok"
    if row.durum in ("queued", "retry", "running"):
        return None
    return str(row.son_hata or row.durum)


# ============================================================================== başlatma


def baslat(
    session: Session,
    platformlar: Sequence[str],
    hatalar: Sequence[str] | None,
    user: Principal,
) -> dict[str, Any]:
    """Koşuyu ve tüm adımlarını yazar, işi uzun şeritte kuyruğa alır (çağıranın işleminde).

    Süren (queued | running) koşu varsa `HataKosusuSuruyor` (409). İşi bitmiş ama süren durumda
    kalmış koşu önce `failed` olarak kapatılır.
    """
    pl = platformlari_dogrula(platformlar)
    hk = hatalari_dogrula(hatalar)
    conn = session.connection()
    jobq.idempotency_lock(conn, KILIT)
    for eski in session.scalars(
        select(HataKosusu).where(HataKosusu.durum.in_(enums.HATA_KOSUSU_SUREN)).with_for_update()
    ).all():
        if not kurtar(session, eski):
            raise HataKosusuSuruyor(
                "Süren bir ekilmiş hata koşusu var; bitmesini bekleyin ya da iptal edin."
            )
    kosu = HataKosusu(
        id=uuid.uuid4(),
        durum="queued",
        platformlar=pl,
        hatalar=hk,
        baslatan_id=user.id,
        ozet={},
        uyarilar=[],
    )
    session.add(kosu)
    session.flush()
    sira = 0
    for p in pl:
        plan: list[tuple[str, str | None]] = [
            ("temel", None),
            *(("hata", h) for h in hk),
            ("kapanis", None),
        ]
        for asama, kod in plan:
            session.add(
                HataKosusuAdim(
                    id=uuid.uuid4(),
                    kosu_id=kosu.id,
                    platform=p,
                    hata_kodu=kod,
                    asama=asama,
                    sonuc="bekliyor",
                    kiran_testler=[],
                    sira=sira,
                )
            )
            sira += 1
    session.flush()
    job_id = jobq.enqueue(
        conn,
        JOB,
        {"kosu_id": str(kosu.id)},
        idempotency_key=is_anahtari(kosu.id),
        max_deneme=1,
        zaman_asimi_s=is_zaman_asimi_s(sira),
    )
    audit_on_commit(
        session,
        user.kullanici_adi,
        "hata_kosusu.requested",
        f"hata_kosusu:{kosu.id}",
        {"platformlar": pl, "hatalar": hk, "adim": sira, "job_id": str(job_id)},
    )
    _olay(session, kosu)
    return {"id": str(kosu.id), "durum": kosu.durum}


def kurtar(session: Session, kosu: HataKosusu) -> bool:
    """İşi bitmiş ama `queued/running`'de kalmış koşuyu `failed` yapar (çağıranın işleminde).

    İşleyici kendi hatasında koşuyu kapatır; worker öldürülür, süre aşılır ya da nabız kesilirse
    yalnızca iş `failed` olur. Bu durumda koşu burada nedeniyle kapanır. Sürerken iptal edilmiş
    ama işi kapanamadan kesilmiş koşu (`cancelled`, `bitis` boş) da `bitis`/`ozet` alır.
    """
    iptal_yarim = kosu.durum == "cancelled" and kosu.bitis is None
    if kosu.durum not in enums.HATA_KOSUSU_SUREN and not iptal_yarim:
        return False
    neden = _is_bitti(session, kosu.id)
    if neden is None:
        return False
    if iptal_yarim:
        _kapat(session, kosu, "cancelled")
    else:
        _kapat(session, kosu, "failed", f"{YARIM_KALDI}: {_kirp(neden, 300)}")
    return True


def kurtar_hepsi(session: Session) -> int:
    n = 0
    for kosu in session.scalars(
        select(HataKosusu)
        .where(
            HataKosusu.durum.in_(enums.HATA_KOSUSU_SUREN)
            | ((HataKosusu.durum == "cancelled") & HataKosusu.bitis.is_(None))
        )
        .with_for_update(skip_locked=True)
    ).all():
        n += kurtar(session, kosu)
    return n


def _kapat(session: Session, kosu: HataKosusu, durum: str, uyari: str | None = None) -> None:
    kosu.durum = durum
    kosu.bitis = _simdi()
    if uyari:
        kosu.uyarilar = [*(kosu.uyarilar or []), uyari]
    kosu.ozet = ozet_hesapla(_adimlar(session, kosu.id), kosu.platformlar)
    session.flush()
    audit_on_commit(
        session,
        "system",
        "hata_kosusu.finished",
        f"hata_kosusu:{kosu.id}",
        {"durum": durum, "uyari": uyari, "oran": kosu.ozet.get("oran")},
    )
    _olay(session, kosu)


def iptal(session: Session, kosu_id: uuid.UUID, user: Principal) -> dict[str, Any] | None:
    """Kuyruktaki koşu hemen iptal olur; süren koşu `cancelled` işaretlenir ve iş bir sonraki
    adıma geçmeden durur (koşmakta olan `/check` bitene kadar beklenir). Yoksa None."""
    kosu = session.get(HataKosusu, kosu_id, with_for_update=True)
    if kosu is None:
        return None
    if kosu.durum not in enums.HATA_KOSUSU_SUREN:
        # Bitmiş koşu (done | failed | cancelled): 409.
        raise WorkflowError(f"Koşu iptal edilemez (durum: {kosu.durum}).")
    onceki = kosu.durum
    uyari = f"{user.kullanici_adi} tarafından iptal edildi."
    if onceki == "queued":
        job_id = session.execute(
            text("SELECT id FROM job WHERE idempotency_key = :k"), {"k": is_anahtari(kosu.id)}
        ).scalar_one_or_none()
        if job_id is not None:
            jobq.cancel(session.connection(), job_id)
        _kapat(session, kosu, "cancelled", uyari)
    else:
        # İş adımlar arasında durumu okur; son adım bitince `bitis` ve `ozet` yazılır.
        kosu.durum = "cancelled"
        kosu.uyarilar = [*(kosu.uyarilar or []), uyari]
        session.flush()
        _olay(session, kosu)
    audit_on_commit(
        session,
        user.kullanici_adi,
        "hata_kosusu.cancel_requested",
        f"hata_kosusu:{kosu.id}",
        {"onceki_durum": onceki},
    )
    return {"id": str(kosu.id), "durum": kosu.durum}


# ============================================================================== okuma


def _adimlar(session: Session, kosu_id: uuid.UUID) -> list[HataKosusuAdim]:
    return list(
        session.scalars(
            select(HataKosusuAdim)
            .where(HataKosusuAdim.kosu_id == kosu_id)
            .order_by(HataKosusuAdim.sira)
        ).all()
    )


def _iso(t: datetime | None) -> str | None:
    return t.isoformat() if t is not None else None


def _kosu_sozluk(kosu: HataKosusu, baslatan: str | None) -> dict[str, Any]:
    return {
        "id": str(kosu.id),
        "durum": kosu.durum,
        "platformlar": list(kosu.platformlar or []),
        "hatalar": list(kosu.hatalar or []),
        "commit": kosu.commit,
        "baslatan_id": str(kosu.baslatan_id) if kosu.baslatan_id else None,
        "baslatan": baslatan,
        # Koşu bitince yazılır; süren koşuda null.
        "ozet": dict(kosu.ozet) if kosu.ozet else None,
        "uyarilar": list(kosu.uyarilar or []),
        "baslama": _iso(kosu.baslama),
        "bitis": _iso(kosu.bitis),
        "olusturma": _iso(kosu.olusturma),
    }


def _adim_sozluk(a: HataKosusuAdim, adlar: Mapping[str, str]) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "platform": a.platform,
        "hata_kodu": a.hata_kodu,
        "hata_adi": adlar.get(a.hata_kodu) if a.hata_kodu else None,
        "asama": a.asama,
        "run_id": str(a.run_id) if a.run_id else None,
        "sonuc": a.sonuc,
        "kiran_testler": list(a.kiran_testler or []),
        "neden": a.neden,
        "sure_ms": a.sure_ms,
        "sira": a.sira,
    }


def _kullanici_adlari(session: Session, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    kume = {i for i in ids if i is not None}
    if not kume:
        return {}
    satirlar = session.execute(
        select(AppUser.id, AppUser.kullanici_adi).where(AppUser.id.in_(kume))
    ).all()
    return {uid: ad for uid, ad in satirlar}


def _adlar() -> dict[str, str]:
    return {h["kod"]: h["ad"] for h in kat.katalog()}


def _suren_kosulari_kurtar(session: Session) -> None:
    for kosu in session.scalars(
        select(HataKosusu).where(HataKosusu.durum.in_(enums.HATA_KOSUSU_SUREN))
    ).all():
        if _is_bitti(session, kosu.id) is not None:
            kilitli = session.get(HataKosusu, kosu.id, with_for_update=True)
            if kilitli is not None:
                kurtar(session, kilitli)


def liste(session: Session, limit: int = 20) -> list[dict[str, Any]]:
    _suren_kosulari_kurtar(session)
    kosular = session.scalars(
        select(HataKosusu).order_by(HataKosusu.olusturma.desc(), HataKosusu.id).limit(limit)
    ).all()
    adlar = _kullanici_adlari(session, (k.baslatan_id for k in kosular))
    return [_kosu_sozluk(k, adlar.get(k.baslatan_id)) for k in kosular]  # type: ignore[arg-type]


def detay(session: Session, kosu_id: uuid.UUID) -> dict[str, Any] | None:
    kosu = session.get(HataKosusu, kosu_id)
    if kosu is None:
        return None
    if kosu.durum in enums.HATA_KOSUSU_SUREN and _is_bitti(session, kosu.id) is not None:
        kilitli = session.get(HataKosusu, kosu.id, with_for_update=True)
        if kilitli is not None:
            kurtar(session, kilitli)
    adlar = _kullanici_adlari(session, [kosu.baslatan_id])
    hata_adlari = _adlar()
    return {
        **_kosu_sozluk(kosu, adlar.get(kosu.baslatan_id) if kosu.baslatan_id else None),
        "adimlar": [_adim_sozluk(a, hata_adlari) for a in _adimlar(session, kosu.id)],
    }


# ============================================================================== özet


def ozet_hesapla(
    adimlar: Sequence[HataKosusuAdim], platformlar: Sequence[str] | None = None
) -> dict[str, Any]:
    """Platform başına ve toplam `{yakalanan, kacan, gecersiz, oran}`; `oran = yakalanan /
    (yakalanan + kacan)` (payda 0 → None). `gecersiz` paydaya girmez. Koşmamış (`bekliyor`) hata
    adımları `bekleyen` olarak ayrı sayılır."""
    sira = list(dict.fromkeys([*(platformlar or []), *(a.platform for a in adimlar)]))
    adlar = _adlar()
    out_pl: list[dict[str, Any]] = []
    kacanlar: list[dict[str, Any]] = []
    top = {"yakalanan": 0, "kacan": 0, "gecersiz": 0, "bekleyen": 0}
    for p in sira:
        pa = [a for a in adimlar if a.platform == p]
        hatalar = [a for a in pa if a.asama == "hata"]
        say = {
            "yakalanan": sum(a.sonuc == "yakalandi" for a in hatalar),
            "kacan": sum(a.sonuc == "kacti" for a in hatalar),
            "gecersiz": sum(a.sonuc == "gecersiz" for a in hatalar),
            "bekleyen": sum(a.sonuc == "bekliyor" for a in hatalar),
        }
        for k, v in say.items():
            top[k] += v
        temel = next((a.sonuc for a in pa if a.asama == "temel"), None)
        kapanis = next((a.sonuc for a in pa if a.asama == "kapanis"), None)
        out_pl.append(
            {
                "platform": p,
                "oran": _oran(say["yakalanan"], say["yakalanan"] + say["kacan"]),
                **say,
                "temel": temel,
                "kapanis": kapanis,
            }
        )
        kacanlar.extend(
            {
                "hata_kodu": a.hata_kodu,
                "ad": adlar.get(a.hata_kodu or "", a.hata_kodu),
                "platform": p,
            }
            for a in hatalar
            if a.sonuc == "kacti"
        )
    return {
        "oran": _oran(top["yakalanan"], top["yakalanan"] + top["kacan"]),
        **top,
        "platformlar": out_pl,
        "kacanlar": kacanlar,
    }


def hata_yakalama_ozeti(session: Session) -> dict[str, Any] | None:
    """Kontrol Kulesi `hata_yakalama` (§4.7): son tamamlanmış (`done`) koşu; koşu yoksa None.

    Şekil: `{son_kosu: {id, bitis, durum}, oran, yakalanan, kacan, gecersiz, platformlar:
    [{platform, oran, yakalanan, kacan, gecersiz, …}], kacanlar: [{hata_kodu, ad, platform}],
    kaynak}`. Sayılar okuma anında `hata_kosusu_adim` satırlarından hesaplanır.
    """
    kosu = session.scalars(
        select(HataKosusu)
        .where(HataKosusu.durum == "done")
        .order_by(HataKosusu.bitis.desc().nulls_last(), HataKosusu.olusturma.desc())
        .limit(1)
    ).first()
    if kosu is None:
        return None
    oz = ozet_hesapla(_adimlar(session, kosu.id), kosu.platformlar)
    tarih = kosu.bitis.astimezone(_istanbul()).strftime("%Y-%m-%d %H:%M") if kosu.bitis else "?"
    oran_metni = f"oran %{round(oz['oran'] * 100)}" if oz["oran"] is not None else "oran ölçülmedi"
    kaynak = (
        f"Son tamamlanan ekilmiş hata koşusu ({tarih}; {', '.join(kosu.platformlar or [])}): "
        f"yakalanan {oz['yakalanan']}, kaçan {oz['kacan']}, geçersiz {oz['gecersiz']}; "
        f"{oran_metni}. Oran = yakalanan / (yakalanan + kaçan); geçersiz adımlar paydaya girmez "
        "(hata_kosusu, hata_kosusu_adim)."
    )
    return {
        "son_kosu": {"id": str(kosu.id), "bitis": _iso(kosu.bitis), "durum": kosu.durum},
        "oran": oz["oran"],
        "yakalanan": oz["yakalanan"],
        "kacan": oz["kacan"],
        "gecersiz": oz["gecersiz"],
        "platformlar": [
            {k: p[k] for k in ("platform", "oran", "yakalanan", "kacan", "gecersiz")}
            for p in oz["platformlar"]
        ],
        "kacanlar": oz["kacanlar"],
        "kaynak": kaynak,
    }


def _istanbul() -> Any:
    from tp_core.features.ci.service import _istanbul as ist

    return ist()


# ============================================================================== sınıflama


@dataclass
class AdimSonucu:
    sonuc: str
    neden: str | None = None
    kiran_testler: list[str] = field(default_factory=list)


def _testler(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rr = report.get("run") if isinstance(report.get("run"), Mapping) else {}
    return [t for t in (rr or {}).get("tests") or [] if isinstance(t, Mapping)]


def _kirmizilar(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [t for t in _testler(report) if t.get("status") not in (*GECEN, "skipped")]


def _test_turu(t: Mapping[str, Any], java: bool) -> str:
    failure = t.get("failure") if isinstance(t.get("failure"), Mapping) else {}
    mesaj = str(t.get("error") or (failure or {}).get("message") or "")
    return test_error_kind(mesaj, (failure or {}).get("type"), java=java)


def _ilk_satir(t: Mapping[str, Any]) -> str:
    failure = t.get("failure") if isinstance(t.get("failure"), Mapping) else {}
    m = str(
        t.get("error") or (failure or {}).get("message") or (failure or {}).get("first_line") or ""
    )
    return m.strip().splitlines()[0] if m.strip() else ""


def _adlar_listesi(testler: Iterable[Mapping[str, Any]]) -> list[str]:
    return list(dict.fromkeys(str(t.get("title") or "?") for t in testler))[:MAX_KIRAN]


def ortam_nedeni(report: Mapping[str, Any], sinif: Any) -> str:
    """`classify` sonucu `ortam`/`derleme` olan koşunun Türkçe nedeni (sağlık bilgisi dahil)."""
    rr = report.get("run") if isinstance(report.get("run"), Mapping) else None
    app = report.get("app")
    if isinstance(app, Mapping) and not app.get("skipped") and app.get("ok") is False:
        return f"Çalışan uygulama koşulan commit'le eşleşmiyor ya da doğrulanamadı: {sinif.hata}"
    if sinif.sinif == "derleme":
        return f"Derleme/statik kontrol başarısız ({sinif.hata}); testler koşmadı."
    if not rr:
        return f"Toolchain raporunda test koşusu yok: {_kirp(report.get('summary'), 300) or '?'}"
    saglik = rr.get("saglik") if isinstance(rr.get("saglik"), Mapping) else None
    if saglik and saglik.get("ok") is False:
        appium = saglik.get("appium") if isinstance(saglik.get("appium"), Mapping) else None
        if appium and appium.get("hata"):
            url = f" ({appium['url']})" if appium.get("url") else ""
            return f"Cihaz/Appium erişilemiyor{url}: {appium['hata']}"
        return str(saglik.get("hata") or "Uygulama sağlık kontrolü başarısız.")
    if rr.get("status") == "error":
        return f"Test koşucusu hata verdi: {rr.get('error') or report.get('summary') or '?'}"
    java = java_raporu_mu(report)
    for t in _kirmizilar(report):
        if _test_turu(t, java) == "ortam":
            return (
                f"Test ortamı/kurulum hatası ({t.get('title') or '?'}): {_ilk_satir(t)} — hata "
                "uygulanamamış ya da uygulama erişilemiyor olabilir."
            )
    return str(sinif.aciklama)


def siniflandir(asama: str, report: Mapping[str, Any] | None, hata: str | None) -> AdimSonucu:
    """Bir adımın sonucu. Temel/kapanış: `yesil | kirmizi | gecersiz`. Hata adımı: `yakalandi`
    (≥1 test assertion ile kırmızı) | `kacti` (tümü yeşil) | `gecersiz` (ortam/altyapı/derleme ya
    da kırmızıların hiçbiri assertion değil)."""
    if report is None:
        return AdimSonucu(
            "gecersiz", _kirp(f"Toolchain'e ulaşılamadı ya da istek reddedildi: {hata or '?'}")
        )
    s = classify(report)
    kirmizi = _kirmizilar(report)
    adlar = _adlar_listesi(kirmizi)
    if s.sinif == "gecti":
        if asama == "hata":
            return AdimSonucu("kacti", "Tüm testler yeşil kaldı: hata hiçbir testte yakalanmadı.")
        return AdimSonucu("yesil")
    if s.sinif in ("ortam", "derleme"):
        return AdimSonucu("gecersiz", _kirp(ortam_nedeni(report, s)), adlar)
    if not kirmizi:
        neden = _kirp(
            f"Koşu kırmızı ama başarısız test bilgisi yok: {report.get('summary') or s.aciklama}"
        )
        return AdimSonucu("gecersiz" if asama == "hata" else "kirmizi", neden)
    if asama != "hata":
        return AdimSonucu(
            "kirmizi", _kirp(f"{len(adlar)} test kırmızı: {', '.join(adlar[:5])}"), adlar
        )
    java = java_raporu_mu(report)
    if any(_test_turu(t, java) == "assertion" for t in kirmizi):
        return AdimSonucu("yakalandi", None, adlar)
    return AdimSonucu(
        "gecersiz",
        _kirp(
            "Kırmızı testlerin hiçbiri assertion ile kalmadı (locator/zaman aşımı/belirsiz); "
            f"hata yakalama kanıtı sayılmaz: {', '.join(adlar[:5])}"
        ),
        adlar,
    )


# ============================================================================== iş


def calistir(ctx: JobContext) -> dict[str, Any]:
    """`hata_kosusu.calistir` gövdesi. Beklenmeyen hata koşuyu `failed` + nedenle kapatır."""
    try:
        kosu_id = uuid.UUID(str((ctx.yuk or {})["kosu_id"]))
    except (KeyError, ValueError) as exc:
        raise PermanentJobError("iş yükünde geçerli kosu_id yok") from exc
    try:
        return _calistir(kosu_id)
    except Exception as exc:
        try:
            with session_scope() as s:
                kosu = s.get(HataKosusu, kosu_id, with_for_update=True)
                if kosu is not None and kosu.durum in enums.HATA_KOSUSU_SUREN:
                    _kapat(
                        s, kosu, "failed", _kirp(f"Beklenmeyen hata: {type(exc).__name__}: {exc}")
                    )
                elif kosu is not None and kosu.durum == "cancelled" and kosu.bitis is None:
                    _kapat(s, kosu, "cancelled")
        except Exception:  # asıl hata yüzeye çıksın; kalan koşuyu kurtarma kapatır
            log.exception("hata koşusu %s failed olarak kapatılamadı", kosu_id)
        raise


def _iptal_mi(kosu_id: uuid.UUID) -> bool:
    with session_scope() as s:
        return s.scalar(select(HataKosusu.durum).where(HataKosusu.id == kosu_id)) == "cancelled"


def _calistir(kosu_id: uuid.UUID) -> dict[str, Any]:
    with session_scope() as s:
        kosu = s.get(HataKosusu, kosu_id, with_for_update=True)
        if kosu is None:
            raise PermanentJobError("hata koşusu bulunamadı")
        if kosu.durum != "queued":
            return {"durum": kosu.durum, "atlandi": True}
        try:
            sha = ci_services.forge().head_sha("main")
        except Exception as exc:
            _kapat(s, kosu, "failed", _kirp(f"Koşulacak commit çözülemedi (main): {exc}"))
            return {"durum": "failed"}
        if not sha:
            _kapat(s, kosu, "failed", "Koşulacak commit çözülemedi (main boş döndü).")
            return {"durum": "failed"}
        kosu.commit = sha
        kosu.durum = "running"
        kosu.baslama = _simdi()
        s.flush()
        _olay(s, kosu)
        isteyen = "system"
        if kosu.baslatan_id is not None:
            isteyen = (
                s.scalar(select(AppUser.kullanici_adi).where(AppUser.id == kosu.baslatan_id))
                or "system"
            )
        platformlar = list(kosu.platformlar or [])
        adimlar = [(a.id, a.platform, a.asama, a.hata_kodu) for a in _adimlar(s, kosu_id)]
    iptal_edildi = False
    for platform in platformlar:
        pa = [a for a in adimlar if a[1] == platform]
        temel = next(a for a in pa if a[2] == "temel")
        hatalar = [a for a in pa if a[2] == "hata"]
        kapanis = next(a for a in pa if a[2] == "kapanis")
        if _iptal_mi(kosu_id):
            iptal_edildi = True
            break
        ts = _adim_kos(kosu_id, temel, sha, isteyen)
        if ts.sonuc != "yesil":
            neden = _kirp(f"{TEMEL_YESIL_DEGIL}: {ts.neden}" if ts.neden else TEMEL_YESIL_DEGIL)
            for a in [*hatalar, kapanis]:
                _adim_yaz(kosu_id, a, AdimSonucu("gecersiz", neden), None, None)
            continue
        for a in hatalar:
            if _iptal_mi(kosu_id):
                iptal_edildi = True
                break
            _adim_kos(kosu_id, a, sha, isteyen)
        if iptal_edildi:
            break
        ks = _adim_kos(kosu_id, kapanis, sha, isteyen)
        if ks.sonuc != "yesil":
            with session_scope() as s:
                kosu = s.get(HataKosusu, kosu_id, with_for_update=True)
                if kosu is not None:
                    kosu.uyarilar = [
                        *(kosu.uyarilar or []),
                        _kirp(
                            f"{platform}: kapanış koşusu yeşil değil ({ks.sonuc}); hatalar geri "
                            f"alınmamış ya da uygulama kararsız olabilir. {ks.neden or ''}"
                        ),
                    ]
    with session_scope() as s:
        kosu = s.get(HataKosusu, kosu_id, with_for_update=True)
        if kosu is None:
            raise PermanentJobError("hata koşusu bulunamadı")
        durum = "cancelled" if kosu.durum == "cancelled" or iptal_edildi else "done"
        _kapat(s, kosu, durum)
        return {"durum": durum, "ozet": kosu.ozet}


def _adim_kos(
    kosu_id: uuid.UUID,
    adim: tuple[uuid.UUID, str, str, str | None],
    sha: str,
    isteyen: str,
) -> AdimSonucu:
    _, platform, asama, kod = adim
    from tp_core.features.ci.service import check_body_platformu

    with session_scope() as s:
        kosu = s.get(HataKosusu, kosu_id)
        if kosu is not None:
            _olay(s, kosu, platform=platform, hata_kodu=kod, asama=asama, sonuc=None)
    body: dict[str, Any] = {
        "sha": sha,
        "test_files": [],
        "repeat_each": 1,
        "retries": 0,
        "ast_guard_mode": "pr",
        "run_id": f"hk-{kosu_id.hex[:8]}-{asama}-{uuid.uuid4().hex[:6]}",
        # CI ile aynı dil alanları: web boş, uygulama `lang=java` + `platform`.
        **check_body_platformu(platform),
    }
    if kod:
        body["fault"] = kod
    baslama = _simdi()
    t0 = time.monotonic()
    report: Mapping[str, Any] | None = None
    hata: str | None = None
    try:
        report = ci_services.toolchain().check(body)
    except ToolchainError as exc:
        hata = str(exc)
    sure_ms = int((time.monotonic() - t0) * 1000)
    sonuc = siniflandir(asama, report, hata)
    run_id = _kosu_kaydet(kosu_id, platform, asama, kod, sha, isteyen, report, hata, baslama)
    _adim_yaz(kosu_id, adim, sonuc, run_id, sure_ms)
    return sonuc


def _adim_yaz(
    kosu_id: uuid.UUID,
    adim: tuple[uuid.UUID, str, str, str | None],
    sonuc: AdimSonucu,
    run_id: uuid.UUID | None,
    sure_ms: int | None,
) -> None:
    adim_id, platform, asama, kod = adim
    with session_scope() as s:
        a = s.get(HataKosusuAdim, adim_id, with_for_update=True)
        kosu = s.get(HataKosusu, kosu_id)
        if a is None or kosu is None:
            return
        a.sonuc = sonuc.sonuc
        a.neden = sonuc.neden
        a.kiran_testler = list(sonuc.kiran_testler)
        a.run_id = run_id
        a.sure_ms = sure_ms
        s.flush()
        _olay(s, kosu, platform=platform, hata_kodu=kod, asama=asama, sonuc=sonuc.sonuc)


def _kosu_kaydet(
    kosu_id: uuid.UUID,
    platform: str,
    asama: str,
    kod: str | None,
    sha: str,
    isteyen: str,
    report: Mapping[str, Any] | None,
    hata: str | None,
    baslama: datetime,
) -> uuid.UUID | None:
    """Adımın `run` satırı (`tetik='break_verify'`, V6). Kayıt hatası koşuyu durdurmaz."""
    from tp_core.features.ci.service import ingest_check_report

    try:
        with session_scope() as s:
            run = Run(
                id=uuid.uuid4(),
                script_id=None,
                pr_no=None,
                commit=sha,
                kaynak="local",
                tetik="break_verify",
                sonuc="running",
                baslama=baslama,
                ortam={
                    "retries": 0,
                    "repeat_each": 1,
                    "break_campaign": False,
                    "isteyen": isteyen,
                    "ref": None,
                    "platform": platform,
                    # 012 §4.6 / V6: KPI dışlama `tetik`'ten, triage atlaması `hata_kosusu_id`'den.
                    "hata_kodu": kod,
                    "hata_kosusu_id": str(kosu_id),
                    "hata_kosusu_asama": asama,
                },
                artefaktlar={},
            )
            s.add(run)
            s.flush()
            if report is None:
                bitis = _simdi()
                run.sonuc = "error"
                run.bitis = bitis
                run.sure_ms = int((bitis - baslama).total_seconds() * 1000)
                run.artefaktlar = {"hata": _kirp(hata or "toolchain /check koşturulamadı")}
            else:
                ingest_check_report(s, run, report)
                rr = report.get("run")
                if isinstance(rr, Mapping):
                    run.artefaktlar = {
                        **(run.artefaktlar or {}),
                        "toolchain_run_id": rr.get("run_id"),
                    }
            return run.id
    except Exception as exc:
        log.warning("hata koşusu adımı run tablosuna yazılamadı: %s", exc)
        return None
