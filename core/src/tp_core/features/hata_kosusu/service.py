"""Ekilmiş hata koşusu (F3; specs/012-test-kalite-dogrulama/ANALIZ.md §4.6, §4.7, §13).

Kontrol Kulesi'nden elle başlatılır (K5; `engineer`, `presenter` — V4). Seçilen platformlar
**sırayla** koşar; platform başına:

1. `temel`: hatasız tam suite. Ortam/altyapı/derleme hatası (ya da toolchain'e ulaşılamaması) →
   platformun kalan adımları `gecersiz` ("temel koşu yeşil değil"). Temelde **kırmızı testler**
   platformu geçersiz kılmaz (K12): adım `kirmizi` olur, bu testler sonraki adımlarda sayımdan
   çıkarılır ve adımda `temelde_kirmizi` olarak listelenir.
2. `hata`: her hata için tam suite (`fault=<kod>`). Bir test hatayı ancak **temelde yeşilken bu
   koşuda assertion ile kırmızıya döndüyse** yakalar (locator/zaman aşımı/belirsiz kırmızı kanıt
   değildir). ≥1 böyle test → `yakalandi` (`kiran_testler: [{test, kaynak}]`); temelde yeşil
   testlerin hiçbiri kırmızı değil → `kacti`; ortam/altyapı/derleme hatası ya da yalnız assertion
   dışı kırmızı → `gecersiz` (Türkçe `neden`).
3. `kapanis`: hatasız tam suite. Temelde yeşil olup burada kırmızı olan test varsa (ya da koşu
   geçersizse) hataların geri alındığı doğrulanamaz: o platformun `yakalandi`/`kacti` adımları
   `gecersiz` olur ve koşu `uyarilar`'a not düşer.

Kıran testin kaynağı (`kaynak`): testin kendi dosyası (`t.file`; failure konumu değil) o platformda
onaylı bir case'in onaylı içerik hash'inden üretilmiş bir `script_codegen` kaydının dosyasıysa `ai`,
değilse `el` (yol adı taklit edilemez; codegen kaydı yoksa her test `el`). Ana oran yalnız `ai`
testlerden hesaplanır (K12); el yazısı suite `el_yazisi` altında ayrı verilir. Kaynak envanteri
yalnız **temelde yeşil** testlerden sayılır: platformun temel koşusunda o kaynaktan yeşil test yoksa
o kaynağın oranı ölçülmez (`null`; ör. üretilen testlerin hepsi temelde kırmızıysa AI oranı %0
değil "ölçülmedi").

"Temelde yeşil" üyelikle denetlenir: temel koşudaki yeşil testlerin anahtar kümesi saklanır
(`_ic.temel.<platform>.yesil`) ve bir hata ancak bu kümedeki bir testle yakalanır; temelde
görülmeyen (atlanan, yeni, başlığı değişen) kırmızı test kanıt sayılmaz. Temelde kırmızı test
sayısı `MAX_TEMEL_KIRMIZI`'yı (ya da yeşil sayısı `MAX_TEMEL_YESIL`'i) aşarsa platform `gecersiz`
olur.

Adım `neden`'i kategorize Türkçe metindir: ham toolchain/istisna metni ve Appium adresleri
`neden`'e yazılmaz, yalnız denetim kaydına (`hata_kosusu.adim_detayi`, `hata_kosusu.finished`
`detay`) gider.

Yeniden koşu (kıran testleri hatasız tekrar koşup kararlılığı doğrulamak) yapılmaz: her biri ayrı
bir `/check` (uygulama derlemesi + koşu) demektir. Yerine iki koruma vardır: kıran test temelde
yeşil olmalıdır ve platformun kapanış koşusu (hatasız) yeşil olmalıdır; değilse o platformda kredi
verilmez.

**İş tasarımı.** Her adım ayrı bir iştir (`hata_kosusu.calistir`, uzun şerit, `max_deneme=2`): iş
ilk `bekliyor` adımı koşar, sonucu yazar ve aynı işlemde sonraki adımın işini kuyruğa alır
(`idempotency_key = hata_kosusu.calistir:<koşu>:<sıra>`). Uzun şerit adımlar arasında serbest
kalır (sıradaki diğer uzun işler araya girebilir). Worker yeniden başlarsa yarıda kalan adımın işi
kuyruğun yeniden deneme kuralıyla aynı adımdan sürer. İş hakları da tükenirse koşu `failed` +
nedenle kapanır: kapatma yalnız `baslat`, worker açılışı (`jobs.on_worker_start`) ve periyodik
tarama işinde (`hata_kosusu.tarama`) yapılır; GET uçları salt okunurdur.

İptal: kuyruktaki iş hemen iptal edilir ve koşu `cancelled` kapanır. Koşan adım varsa koşu
`running` kalır, `iptal_istendi` işaretlenir; adım bitince iş koşuyu `cancelled` kapatır. Bitmiş
(`done | failed | cancelled`) koşunun durumu hiçbir yoldan değişmez: her yazma satırı kilitleyip
(`populate_existing`) durumu yeniden okur.

Adım işinde DB/taşıma hatası (`DBAPIError`, `httpx.TransportError`, bağlantı/zaman aşımı) yeniden
fırlatılır: iş kuyruğun yeniden deneme kuralıyla aynı adımdan sürer (adım `bekliyor` kalır); koşu
yalnız son denemede `failed` kapanır. İptal istenmişken beklenmeyen hata koşuyu `cancelled` kapatır.

İş durumu (iptal işareti, temel koşunun test envanteri ve temelde kırmızı testleri, adımların
`temelde_kirmizi` listesi) `hata_kosusu.ozet._ic`'te tutulur; API bunu `iptal_istendi` ve adım
`temelde_kirmizi` alanlarıyla verir, `ozet`'te göstermez.

Her adım bir toolchain `/check`'tir: CI'ın o platform için gönderdiği gövde (`test_files=[]`,
`check_body_platformu`), `retries=0`, `repeat_each=1`, `record_check=false`. Koşu `run` tablosuna
`tetik='break_verify'` ile yazılır (V6) ve sonuçlar codegen kontrolleri gibi `ingest_check_report`
ile işlenir. `run.ortam`: `hata_kodu`, `hata_kosusu_id`, `hata_kosusu_asama`, `platform`. Bu tetik
Kontrol Kulesi KPI'larından (`_kirma_degil`) dışlanır; triage `ortam.hata_kosusu_id` taşıyan koşuyu
sınıflandırmaz (bug taslağı açılmaz).

Tek süren koşu kuralı servistedir (advisory lock + sorgu; DB kısıtı yok).
"""

from __future__ import annotations

import copy
import logging
import os
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.events.bus import publish_tx
from tp_core.features.ci import services as ci_services
from tp_core.features.ci.clients import ToolchainError, check_timeout_s
from tp_core.features.codegen.classify import classify, java_raporu_mu, test_error_kind
from tp_core.features.hata_kosusu import katalog as kat
from tp_core.features.hata_kosusu.hatalar import HataKosusuSuruyor
from tp_core.models import (
    AppUser,
    HataKosusu,
    HataKosusuAdim,
    Run,
    Script,
    TestCase,
    enums,
    session_scope,
)
from tp_core.models.codegen_feature import ScriptCodegen
from tp_core.workflow import jobs as jobq
from tp_core.workflow.jobs import JobContext, PermanentJobError
from tp_core.workflow.service import Principal, WorkflowError

log = logging.getLogger("tp_core.hata_kosusu")

JOB = "hata_kosusu.calistir"
JOB_TARAMA = "hata_kosusu.tarama"
OLAY = "hata_kosusu.ilerleme"
# Platformlar bu sırayla koşar (web önce; uygulama platformları cihaz/VM ister).
PLATFORM_SIRASI = ("web", "android", "ios", "windows")
KILIT = "hata_kosusu:tek"
TEMEL_YESIL_DEGIL = "temel koşu yeşil değil"
YARIM_KALDI = "Koşu yarıda kaldı (worker durdu, süre aşıldı ya da iş başarısız oldu)"
KAPANIS_KIRMIZI = "kapanış koşusu yeşil değil"
# Adım işi: `/check` istemci zaman aşımı + pay (commit çözümü, kayıt). Yarıda kalan adım bir kez
# daha denenir (worker yeniden başlatma); ikinci kesintide koşu `failed` kapanır.
ADIM_PAYI_S = 120
ADIM_DENEME = 2
TARAMA_S = 60
GECEN = ("passed", "expected", "flaky")
MAX_NEDEN = 500
MAX_KIRAN = 50
MAX_TEMEL_KIRMIZI = 500
MAX_TEMEL_YESIL = 5000
MAX_DETAY = 2000
IC = "_ic"
ONAYLI_CASE = ("approved", "published")
# Kule: koşu ancak her platformda geçerli (yakalandi | kacti) hata adımı kataloğun bu oranına
# ulaşırsa oran verir (Y10); `TP_HATA_KOSUSU_GECERLI_ESIK` (0–1) ile ayarlanır.
GECERLI_ESIK_ENV = "TP_HATA_KOSUSU_GECERLI_ESIK"
GECERLI_ESIK = 0.5
# Yeniden denenecek (geçici) hatalar: DB ve ağ taşıma katmanı (N4).
GECICI_HATALAR: tuple[type[BaseException], ...] = (
    DBAPIError,
    httpx.TransportError,
    ConnectionError,
    TimeoutError,
)


class GecersizIstek(ValueError):
    """İstek gövdesi geçersiz (bilinmeyen platform ya da hata kodu); API 422 `gecersiz_istek`."""

    status_code = 422
    kod = "gecersiz_istek"


def _simdi() -> datetime:
    return datetime.now(UTC)


def _kirp(metin: Any, n: int = MAX_NEDEN) -> str | None:
    if metin is None:
        return None
    s = " ".join(str(metin).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _oran(pay: int, payda: int) -> float | None:
    return round(pay / payda, 4) if payda else None


def gecerli_esik() -> float:
    """Kule ölçüsü için platform başına geçerli hata adımı alt oranı (varsayılan 0,5)."""
    try:
        v = float(os.environ.get(GECERLI_ESIK_ENV) or GECERLI_ESIK)
    except ValueError:
        return GECERLI_ESIK
    return min(max(v, 0.0), 1.0)


def gecici_mi(exc: BaseException) -> bool:
    """DB/taşıma hatası: iş yeniden denenir (adım `bekliyor` kalır)."""
    return isinstance(exc, GECICI_HATALAR)


def _detay(exc: BaseException) -> str:
    return _kirp(f"{type(exc).__name__}: {exc}", MAX_DETAY) or type(exc).__name__


def adim_zaman_asimi_s() -> int:
    """Tek adım işinin süre sınırı: `/check` istemci zaman aşımı + pay."""
    return int(check_timeout_s() + ADIM_PAYI_S)


def is_zaman_asimi_s(adim_sayisi: int = 1) -> int:
    """Geriye uyum: adım × adım süre sınırı (iş artık adım başınadır)."""
    return max(adim_sayisi, 1) * adim_zaman_asimi_s()


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


# ============================================================================== iç durum


def _ic(kosu: HataKosusu) -> dict[str, Any]:
    """`ozet._ic`'in kopyası (JSONB değişikliği yeniden atamayla yazılır)."""
    return copy.deepcopy(dict((kosu.ozet or {}).get(IC) or {}))


def _ic_yaz(kosu: HataKosusu, ic: Mapping[str, Any]) -> None:
    kosu.ozet = {**dict(kosu.ozet or {}), IC: dict(ic)}


def _kilitle(session: Session, kosu_id: uuid.UUID) -> HataKosusu | None:
    """Satırı kilitler ve kimlik haritasındaki eski kopyayı tazeler (durum yeniden okunur)."""
    return session.get(HataKosusu, kosu_id, with_for_update=True, populate_existing=True)


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


def is_anahtari(kosu_id: uuid.UUID, sira: int = 0) -> str:
    """Adım işinin anahtarı; `sira` adımın yürütme sırasıdır (ilk iş 0)."""
    return f"{JOB}:{kosu_id}:{sira}"


def is_anahtarlari(session: Session, kosu_id: uuid.UUID) -> list[str]:
    """Koşunun olası tüm adım işi anahtarları (`sira` 0…adım sayısı-1)."""
    n = session.scalar(
        select(func.count()).select_from(HataKosusuAdim).where(HataKosusuAdim.kosu_id == kosu_id)
    )
    return [is_anahtari(kosu_id, i) for i in range(max(int(n or 0), 1))]


def _isler(session: Session, kosu_id: uuid.UUID) -> list[Any]:
    """Koşunun adım işleri: tam anahtar listesiyle `job_idempotency_uq` (kısmi tekil indeks)
    üzerinden okunur (N10; `LIKE` taraması yok)."""
    return list(
        session.execute(
            text(
                "SELECT id, durum, son_hata FROM job WHERE idempotency_key = ANY(:k) "
                "ORDER BY olusturma, id"
            ),
            {"k": is_anahtarlari(session, kosu_id)},
        ).all()
    )


def _is_bitti(session: Session, kosu_id: uuid.UUID) -> str | None:
    """Koşunun hiç süren (queued | retry | running) işi yoksa son işin hatası/durumu; varsa
    None."""
    isler = _isler(session, kosu_id)
    if not isler:
        return "iş kaydı yok"
    if any(r.durum in ("queued", "retry", "running") for r in isler):
        return None
    son = isler[-1]
    return str(son.son_hata or son.durum)


def _adim_isi(conn: Connection, kosu_id: uuid.UUID, sira: int) -> uuid.UUID:
    return jobq.enqueue(
        conn,
        JOB,
        {"kosu_id": str(kosu_id)},
        idempotency_key=is_anahtari(kosu_id, sira),
        max_deneme=ADIM_DENEME,
        zaman_asimi_s=adim_zaman_asimi_s(),
    )


def tarama_planla(conn: Connection, *, gecikme_s: float = TARAMA_S) -> uuid.UUID | None:
    """Tarama işi kuyrukta yoksa ekler (tek bekleyen iş; `triage.sweep` gibi)."""
    jobq.idempotency_lock(conn, JOB_TARAMA)
    bekleyen = conn.execute(
        text("SELECT id FROM job WHERE tur = :t AND durum IN ('queued', 'retry') LIMIT 1"),
        {"t": JOB_TARAMA},
    ).scalar_one_or_none()
    if bekleyen is not None:
        return None
    zaman = _simdi() + timedelta(seconds=gecikme_s) if gecikme_s > 0 else None
    return jobq.enqueue(conn, JOB_TARAMA, {}, run_after=zaman, max_deneme=1)


def tarama_temizle(conn: Connection, saklama: timedelta = timedelta(hours=1)) -> int:
    return (
        conn.execute(
            text(
                "DELETE FROM job WHERE tur = :t AND durum IN ('done', 'failed', 'cancelled') "
                "AND COALESCE(bitis, guncelleme) < now() - make_interval(secs => :sn)"
            ),
            {"t": JOB_TARAMA, "sn": saklama.total_seconds()},
        ).rowcount
        or 0
    )


def suren_var(session: Session) -> bool:
    return (
        session.scalar(
            select(HataKosusu.id).where(HataKosusu.durum.in_(enums.HATA_KOSUSU_SUREN)).limit(1)
        )
        is not None
    )


# ============================================================================== başlatma


def baslat(
    session: Session,
    platformlar: Sequence[str],
    hatalar: Sequence[str] | None,
    user: Principal,
) -> dict[str, Any]:
    """Koşuyu ve tüm adımlarını yazar, ilk adımın işini uzun şeritte kuyruğa alır (çağıranın
    işleminde).

    Süren (queued | running) koşu varsa `HataKosusuSuruyor` (409). İşi bitmiş ama süren durumda
    kalmış koşu önce kapatılır (`kurtar`).
    """
    pl = platformlari_dogrula(platformlar)
    hk = hatalari_dogrula(hatalar)
    conn = session.connection()
    jobq.idempotency_lock(conn, KILIT)
    for eski in session.scalars(
        select(HataKosusu)
        .where(HataKosusu.durum.in_(enums.HATA_KOSUSU_SUREN))
        .with_for_update()
        .execution_options(populate_existing=True)
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
        ozet={IC: {"iptal_istendi": False, "temel": {}, "adim": {}}},
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
    job_id = _adim_isi(conn, kosu.id, 0)
    tarama_planla(conn)
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
    """Süren ama hiç süren işi kalmamış koşuyu kapatır (çağıranın işleminde, satır kilitli).

    İş hakları tükendiyse (worker iki kez öldü, süre aşıldı, nabız kesildi) ya da iş kaydı yoksa
    koşu `failed` + nedenle kapanır; iptal istenmişse `cancelled`. İşi sürüyorsa dokunmaz (False).
    """
    if kosu.durum not in enums.HATA_KOSUSU_SUREN:
        return False
    neden = _is_bitti(session, kosu.id)
    if neden is None:
        return False
    if _ic(kosu).get("iptal_istendi"):
        return _kapat(session, kosu, "cancelled", detay=neden)
    # İşin son hatası ham istisna metnidir: yalnız denetim kaydına (güvenlik-12).
    return _kapat(session, kosu, "failed", f"{YARIM_KALDI}.", detay=_kirp(neden, MAX_DETAY))


def kurtar_hepsi(session: Session) -> int:
    """Tarama ve worker açılışı: işi bitmiş süren koşuları kapatır (kilitli satır atlanır)."""
    n = 0
    for kosu in session.scalars(
        select(HataKosusu)
        .where(HataKosusu.durum.in_(enums.HATA_KOSUSU_SUREN))
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).all():
        n += kurtar(session, kosu)
    return n


def _kapat(
    session: Session,
    kosu: HataKosusu,
    durum: str,
    uyari: str | None = None,
    *,
    detay: str | None = None,
) -> bool:
    """Süren koşuyu `durum`'a kapatır; bitmiş koşuya dokunmaz (False). Satır kilitli olmalı.

    `uyari` koşuda görünür (kategorize Türkçe metin); `detay` (ham hata) yalnız denetime gider."""
    if kosu.durum not in enums.HATA_KOSUSU_SUREN:
        return False
    kosu.durum = durum
    kosu.bitis = _simdi()
    if uyari:
        kosu.uyarilar = [*(kosu.uyarilar or []), uyari]
    ic = _ic(kosu)
    kosu.ozet = {**ozet_hesapla(_adimlar(session, kosu.id), kosu.platformlar, ic), IC: ic}
    session.flush()
    audit_on_commit(
        session,
        "system",
        "hata_kosusu.finished",
        f"hata_kosusu:{kosu.id}",
        {"durum": durum, "uyari": uyari, "detay": detay, "oran": kosu.ozet.get("oran")},
    )
    _olay(session, kosu)
    return True


def iptal(session: Session, kosu_id: uuid.UUID, user: Principal) -> dict[str, Any] | None:
    """Kuyruktaki işler iptal edilir; koşan adım yoksa koşu hemen `cancelled` olur. Koşan adım
    varsa koşu `running` kalır ve `iptal_istendi` işaretlenir; iş adım bitince kapatır. Yoksa
    None; bitmiş koşu 409."""
    kosu = _kilitle(session, kosu_id)
    if kosu is None:
        return None
    if kosu.durum not in enums.HATA_KOSUSU_SUREN:
        raise WorkflowError(f"Koşu iptal edilemez (durum: {kosu.durum}).")
    onceki = kosu.durum
    conn = session.connection()
    calisan = False
    for r in _isler(session, kosu.id):
        if r.durum in ("queued", "retry"):
            if not jobq.cancel(conn, r.id):
                calisan = True  # bu arada sahiplenildi
        elif r.durum == "running":
            calisan = True
    uyari = f"{user.kullanici_adi} tarafından iptal edildi."
    if calisan:
        ic = _ic(kosu)
        ic["iptal_istendi"] = True
        ic["iptal_eden"] = user.kullanici_adi
        _ic_yaz(kosu, ic)
        kosu.uyarilar = [*(kosu.uyarilar or []), f"{uyari} Koşan adım bitince durur."]
        session.flush()
        _olay(session, kosu)
    else:
        _kapat(session, kosu, "cancelled", uyari)
    audit_on_commit(
        session,
        user.kullanici_adi,
        "hata_kosusu.cancel_requested",
        f"hata_kosusu:{kosu.id}",
        {"onceki_durum": onceki, "hemen": not calisan},
    )
    return {
        "id": str(kosu.id),
        "durum": kosu.durum,
        "iptal_istendi": bool(_ic(kosu).get("iptal_istendi")),
    }


# ============================================================================== okuma (salt)


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
    gorunen = {k: v for k, v in dict(kosu.ozet or {}).items() if k != IC}
    return {
        "id": str(kosu.id),
        "durum": kosu.durum,
        "iptal_istendi": bool(_ic(kosu).get("iptal_istendi")),
        "platformlar": list(kosu.platformlar or []),
        "hatalar": list(kosu.hatalar or []),
        "commit": kosu.commit,
        "baslatan_id": str(kosu.baslatan_id) if kosu.baslatan_id else None,
        "baslatan": baslatan,
        # Koşu bitince yazılır; süren koşuda null.
        "ozet": gorunen or None,
        "uyarilar": list(kosu.uyarilar or []),
        "baslama": _iso(kosu.baslama),
        "bitis": _iso(kosu.bitis),
        "olusturma": _iso(kosu.olusturma),
    }


def kiran_listesi(ham: Any) -> list[dict[str, Any]]:
    """`kiran_testler` → `[{test, kaynak}]` (K12 öncesi düz ad listesi `el` sayılır)."""
    out: list[dict[str, Any]] = []
    for x in ham or []:
        if isinstance(x, Mapping):
            out.append({"test": str(x.get("test") or "?"), "kaynak": x.get("kaynak") or "el"})
        elif isinstance(x, str):
            out.append({"test": x, "kaynak": "el"})
    return out


def _adim_sozluk(
    a: HataKosusuAdim, adlar: Mapping[str, str], ic: Mapping[str, Any]
) -> dict[str, Any]:
    ek = (ic.get("adim") or {}).get(str(a.id)) or {}
    return {
        "id": str(a.id),
        "platform": a.platform,
        "hata_kodu": a.hata_kodu,
        "hata_adi": adlar.get(a.hata_kodu) if a.hata_kodu else None,
        "asama": a.asama,
        "run_id": str(a.run_id) if a.run_id else None,
        "sonuc": a.sonuc,
        "kiran_testler": kiran_listesi(a.kiran_testler),
        "temelde_kirmizi": list(ek.get("temelde_kirmizi") or []),
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


def liste(session: Session, limit: int = 20) -> list[dict[str, Any]]:
    kosular = session.scalars(
        select(HataKosusu).order_by(HataKosusu.olusturma.desc(), HataKosusu.id).limit(limit)
    ).all()
    adlar = _kullanici_adlari(session, (k.baslatan_id for k in kosular))
    return [_kosu_sozluk(k, adlar.get(k.baslatan_id)) for k in kosular]  # type: ignore[arg-type]


def detay(session: Session, kosu_id: uuid.UUID) -> dict[str, Any] | None:
    kosu = session.get(HataKosusu, kosu_id)
    if kosu is None:
        return None
    adlar = _kullanici_adlari(session, [kosu.baslatan_id])
    hata_adlari = _adlar()
    ic = _ic(kosu)
    return {
        **_kosu_sozluk(kosu, adlar.get(kosu.baslatan_id) if kosu.baslatan_id else None),
        "adimlar": [_adim_sozluk(a, hata_adlari, ic) for a in _adimlar(session, kosu.id)],
    }


# ============================================================================== özet


def _sayac() -> dict[str, int]:
    return {"yakalanan": 0, "kacan": 0}


def _olcu(s: Mapping[str, int] | None) -> dict[str, Any]:
    if s is None:
        return {"oran": None, "yakalanan": 0, "kacan": 0, "olculdu": False}
    return {
        "oran": _oran(s["yakalanan"], s["yakalanan"] + s["kacan"]),
        "yakalanan": s["yakalanan"],
        "kacan": s["kacan"],
        "olculdu": True,
    }


def ozet_hesapla(
    adimlar: Sequence[HataKosusuAdim],
    platformlar: Sequence[str] | None = None,
    ic: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Koşu özeti (§13.2, K12).

    Geçerli hata adımı (`yakalandi | kacti`) her kaynak için ayrı sayılır: adımı o kaynaktan bir
    kıran test varsa `yakalanan`, yoksa `kacan`. Kaynak platformun temel koşusunda hiç test
    taşımıyorsa o platformda ölçülmez. `oran` = AI (üretilen testler) oranı; `el_yazisi` el yazısı
    suite; `tum_testler` iki kaynak birlikte (adımın kendi sonucu). `gecersiz` paydaya girmez.
    `kapsam.tam_katalog` koşu kataloğun tüm hatalarını içeriyorsa doğrudur. `kapsam.yeterli`:
    her platformda geçerli hata adımı ≥ `esik` × katalog (Y10; Kule yalnız bu durumda oran verir);
    değilse `kapsam.not` nedeni söyler.
    """
    ic = ic or {}
    temel_env = ic.get("temel") or {}
    sira = list(dict.fromkeys([*(platformlar or []), *(a.platform for a in adimlar)]))
    adlar = _adlar()
    out_pl: list[dict[str, Any]] = []
    kacanlar: list[dict[str, Any]] = []
    top_ai: dict[str, int] | None = None
    top_el: dict[str, int] | None = None
    top_tum = _sayac()
    top = {"gecersiz": 0, "bekleyen": 0}
    katalog = kat.kodlar()
    esik = gecerli_esik()
    yetersiz: list[str] = []
    for p in sira:
        pa = [a for a in adimlar if a.platform == p]
        hatalar = [a for a in pa if a.asama == "hata"]
        env = temel_env.get(p)
        # Envanter yoksa (K12 öncesi kayıt) iki kaynak da ölçülmüş sayılır.
        ai_var = env is None or int(env.get("ai") or 0) > 0
        el_var = env is None or int(env.get("el") or 0) > 0
        ai = _sayac() if ai_var else None
        el = _sayac() if el_var else None
        tum = _sayac()
        say = {
            "gecersiz": sum(a.sonuc == "gecersiz" for a in hatalar),
            "bekleyen": sum(a.sonuc == "bekliyor" for a in hatalar),
        }
        for a in hatalar:
            if a.sonuc not in ("yakalandi", "kacti"):
                continue
            kaynaklar = {k["kaynak"] for k in kiran_listesi(a.kiran_testler)}
            tum["yakalanan" if a.sonuc == "yakalandi" else "kacan"] += 1
            for kaynak, s in (("ai", ai), ("el", el)):
                if s is not None:
                    s["yakalanan" if kaynak in kaynaklar else "kacan"] += 1
            if ai is not None and "ai" not in kaynaklar:
                kacanlar.append(
                    {
                        "hata_kodu": a.hata_kodu,
                        "ad": adlar.get(a.hata_kodu or "", a.hata_kodu),
                        "platform": p,
                    }
                )
        for k in top:
            top[k] += say[k]
        for k in top_tum:
            top_tum[k] += tum[k]
        if ai is not None:
            top_ai = top_ai or _sayac()
            for k in top_ai:
                top_ai[k] += ai[k]
        if el is not None:
            top_el = top_el or _sayac()
            for k in top_el:
                top_el[k] += el[k]
        ai_o, el_o = _olcu(ai), _olcu(el)
        gecerli_p = tum["yakalanan"] + tum["kacan"]
        if gecerli_p < esik * len(katalog) or gecerli_p == 0:
            yetersiz.append(f"{p} {gecerli_p}/{len(katalog)}")
        out_pl.append(
            {
                "platform": p,
                "oran": ai_o["oran"],
                "yakalanan": ai_o["yakalanan"],
                "kacan": ai_o["kacan"],
                **say,
                "el_yazisi": {k: el_o[k] for k in ("oran", "yakalanan", "kacan")},
                "tum_testler": {k: _olcu(tum)[k] for k in ("oran", "yakalanan", "kacan")},
                "uretilen_test": None if env is None else int(env.get("ai") or 0),
                "el_test": None if env is None else int(env.get("el") or 0),
                "temel": next((a.sonuc for a in pa if a.asama == "temel"), None),
                "kapanis": next((a.sonuc for a in pa if a.asama == "kapanis"), None),
                "gecerli_adim": gecerli_p,
            }
        )
    ai_t, el_t = _olcu(top_ai), _olcu(top_el)
    kosulan = {a.hata_kodu for a in adimlar if a.asama == "hata" and a.sonuc != "bekliyor"}
    return {
        "oran": ai_t["oran"],
        "yakalanan": ai_t["yakalanan"],
        "kacan": ai_t["kacan"],
        **top,
        "el_yazisi": {k: el_t[k] for k in ("oran", "yakalanan", "kacan")},
        "tum_testler": {k: _olcu(top_tum)[k] for k in ("oran", "yakalanan", "kacan")},
        "kapsam": {
            "kosulan_hata": len(kosulan),
            "katalog": len(katalog),
            "platformlar": sira,
            "tam_katalog": set(katalog) <= kosulan,
            "gecerli_adim": top_tum["yakalanan"] + top_tum["kacan"],
            "esik": esik,
            "yeterli": not yetersiz,
            "not": (
                None
                if not yetersiz
                else (
                    f"Geçerli hata adımı kataloğun %{round(esik * 100)}'inin altında "
                    f"({'; '.join(yetersiz)}); oran ölçü sayılmaz."
                )
            ),
        },
        "platformlar": out_pl,
        "kacanlar": kacanlar,
    }


KULE_ARAMA = 20


def hata_yakalama_ozeti(session: Session) -> dict[str, Any] | None:
    """Kontrol Kulesi `hata_yakalama` (§4.7, §13.2): ölçüye giren son tamamlanmış koşu.

    Ölçüye giren koşu: `done`, kataloğun tamamını koşmuş (`kapsam.tam_katalog`) ve ≥ 1 geçerli
    adımı olan koşudur; kısmi ya da boş koşu önceki ölçünün yerini almaz. Yoksa None. Bu koşuda
    bir platformun geçerli hata adımı kataloğun `esik` oranının altındaysa (`kapsam.yeterli`
    false, Y10) sayılar gösterilir ama tüm `oran` alanları null olur ve `kapsam.not` nedeni
    söyler.

    Şekil: `{son_kosu: {id, bitis, durum}, oran, yakalanan, kacan, gecersiz, el_yazisi: {oran,
    yakalanan, kacan}, tum_testler: {…}, kapsam: {kosulan_hata, katalog, platformlar,
    tam_katalog, gecerli_adim}, platformlar: [{platform, oran, yakalanan, kacan, gecersiz,
    el_yazisi}], kacanlar: [{hata_kodu, ad, platform}], kaynak}` (`kaynak`'ı Kule `kaynaklar`'a
    taşır). Sayılar okuma anında `hata_kosusu_adim` satırlarından hesaplanır.
    """
    kosular = session.scalars(
        select(HataKosusu)
        .where(HataKosusu.durum == "done")
        .order_by(HataKosusu.bitis.desc().nulls_last(), HataKosusu.olusturma.desc())
        .limit(KULE_ARAMA)
    ).all()
    for kosu in kosular:
        oz = ozet_hesapla(_adimlar(session, kosu.id), kosu.platformlar, _ic(kosu))
        if oz["kapsam"]["tam_katalog"] and oz["kapsam"]["gecerli_adim"] > 0:
            return _kule_sekli(kosu, oz)
    return None


def _yuzde(o: float | None) -> str:
    return f"%{round(o * 100)}" if o is not None else "ölçülmedi"


def _orani_sil(d: Mapping[str, Any]) -> dict[str, Any]:
    return {**d, "oran": None}


def _kule_sekli(kosu: HataKosusu, oz: Mapping[str, Any]) -> dict[str, Any]:
    tarih = kosu.bitis.astimezone(_istanbul()).strftime("%Y-%m-%d %H:%M") if kosu.bitis else "?"
    if not oz["kapsam"].get("yeterli", True):
        # Y10: geçerli adım az; sayılar gösterilir, oranlar ölçü sayılmaz.
        oz = {
            **oz,
            "oran": None,
            "el_yazisi": _orani_sil(oz["el_yazisi"]),
            "tum_testler": _orani_sil(oz["tum_testler"]),
            "platformlar": [
                {**p, "oran": None, "el_yazisi": _orani_sil(p["el_yazisi"])}
                for p in oz["platformlar"]
            ],
        }
    el = oz["el_yazisi"]
    kaynak = (
        f"Son tam ekilmiş hata koşusu ({tarih}; {', '.join(kosu.platformlar or [])}; "
        f"{oz['kapsam']['kosulan_hata']}/{oz['kapsam']['katalog']} hata): üretilen testler "
        f"yakalanan {oz['yakalanan']}, kaçan {oz['kacan']}, oran {_yuzde(oz['oran'])}; el yazısı "
        f"suite yakalanan {el['yakalanan']}, kaçan {el['kacan']}, oran {_yuzde(el['oran'])}; "
        f"geçersiz {oz['gecersiz']}. Bir hata, temelde yeşil olup hatalı koşuda assertion ile "
        "kırmızıya dönen testle yakalanmış sayılır; geçersiz adımlar paydaya girmez; kısmi "
        "koşular ölçüye girmez (hata_kosusu, hata_kosusu_adim)."
    )
    if oz["kapsam"].get("not"):
        kaynak += f" {oz['kapsam']['not']}"
    return {
        "son_kosu": {"id": str(kosu.id), "bitis": _iso(kosu.bitis), "durum": kosu.durum},
        "oran": oz["oran"],
        "yakalanan": oz["yakalanan"],
        "kacan": oz["kacan"],
        "gecersiz": oz["gecersiz"],
        "el_yazisi": oz["el_yazisi"],
        "tum_testler": oz["tum_testler"],
        "kapsam": oz["kapsam"],
        "platformlar": [
            {k: p[k] for k in ("platform", "oran", "yakalanan", "kacan", "gecersiz", "el_yazisi")}
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
    kiran_testler: list[dict[str, Any]] = field(default_factory=list)
    temelde_kirmizi: list[str] = field(default_factory=list)
    # Yalnız temel: temelde yeşil {ai, el} test sayısı, kırmızı test anahtarları (sonraki
    # adımlarda hariç) ve yeşil test anahtarları (sonraki adımlarda kanıt için üyelik şartı).
    envanter: dict[str, int] | None = None
    temel_kirmizi_anahtarlari: list[str] = field(default_factory=list)
    temel_yesil_anahtarlari: list[str] = field(default_factory=list)
    # Ham ayrıntı (toolchain/istisna metni, Appium adresi): `neden`'e değil denetime yazılır.
    detay: str | None = None


def _testler(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rr = report.get("run") if isinstance(report.get("run"), Mapping) else {}
    return [t for t in (rr or {}).get("tests") or [] if isinstance(t, Mapping)]


def _kirmizilar(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [t for t in _testler(report) if t.get("status") not in (*GECEN, "skipped")]


def _yesiller(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [t for t in _testler(report) if t.get("status") in GECEN]


def _failure(t: Mapping[str, Any]) -> Mapping[str, Any]:
    f = t.get("failure")
    return f if isinstance(f, Mapping) else {}


def _test_turu(t: Mapping[str, Any], java: bool) -> str:
    failure = _failure(t)
    mesaj = str(t.get("error") or failure.get("message") or "")
    return test_error_kind(mesaj, failure.get("type"), java=java)


def _ilk_satir(t: Mapping[str, Any]) -> str:
    failure = _failure(t)
    m = str(t.get("error") or failure.get("message") or failure.get("first_line") or "")
    return m.strip().splitlines()[0] if m.strip() else ""


def _ad(t: Mapping[str, Any]) -> str:
    return str(t.get("title") or "?")


def test_anahtari(t: Mapping[str, Any]) -> str:
    """Testin koşular arası kimliği: dosya + başlık (başlık dosyalar arasında tekrarlanabilir)."""
    return f"{t.get('file') or ''}::{_ad(t)}"


def _yol(y: Any) -> str:
    return str(y or "").replace("\\", "/").strip().lstrip("./")


def uretilen_dosyalar(session: Session, platform: str) -> frozenset[str]:
    """Platformda onaylı case'lerden üretilmiş testlerin dosyaları (Y7).

    Kayıt: `script_codegen` (+ `script.tur='test'`, aynı platform) ki case `approved | published`
    ve `script_codegen.case_hash == test_case.onaylanan_hash` (onaylı içerikten üretilmiş). Her
    dosya rapordaki olası biçimleriyle verilir: forge yolu, toolchain `test_files` yolu
    (`e2e_goreli`) ve web'de Playwright `testDir`'ine (`tests/`) göre yol."""
    from tp_core.features.codegen.service import e2e_goreli

    satirlar = session.execute(
        select(Script.dosya_yolu, Script.platform)
        .join(ScriptCodegen, ScriptCodegen.script_id == Script.id)
        .join(TestCase, TestCase.id == ScriptCodegen.test_case_id)
        .where(
            Script.tur == "test",
            Script.platform == platform,
            TestCase.durum.in_(ONAYLI_CASE),
            TestCase.onaylanan_hash == ScriptCodegen.case_hash,
        )
    ).all()
    out: set[str] = set()
    for dosya, pl in satirlar:
        if not dosya:
            continue
        goreli = _yol(e2e_goreli(dosya, pl))
        out |= {_yol(dosya), goreli}
        if goreli.startswith("tests/"):
            out.add(goreli[len("tests/") :])
    out.discard("")
    return frozenset(out)


def test_kaynagi(t: Mapping[str, Any], ai_dosyalari: frozenset[str] = frozenset()) -> str:
    """`ai`: testin kendi dosyası (`t.file`; failure konumu bakılmaz) onaylı case'ten üretilmiş
    bir testin dosyası (`uretilen_dosyalar`); değilse `el`. Yol adı tek başına yetmez."""
    dosya = _yol(t.get("file"))
    return "ai" if dosya and dosya in ai_dosyalari else "el"


def _kiran(
    testler: Iterable[Mapping[str, Any]], ai_dosyalari: frozenset[str]
) -> list[dict[str, Any]]:
    gorulen: dict[str, dict[str, Any]] = {}
    for t in testler:
        gorulen.setdefault(
            test_anahtari(t), {"test": _ad(t), "kaynak": test_kaynagi(t, ai_dosyalari)}
        )
    return list(gorulen.values())[:MAX_KIRAN]


def _envanter(report: Mapping[str, Any], ai_dosyalari: frozenset[str]) -> dict[str, int]:
    """Kaynak başına **temelde yeşil** test sayısı (N3): temelde kırmızı ya da atlanan test
    kaynağı ölçülebilir yapmaz."""
    env = {"ai": 0, "el": 0}
    gorulen: set[str] = set()
    for t in _yesiller(report):
        if test_anahtari(t) in gorulen:
            continue
        gorulen.add(test_anahtari(t))
        env[test_kaynagi(t, ai_dosyalari)] += 1
    return env


def ortam_nedeni(report: Mapping[str, Any], sinif: Any) -> tuple[str, str | None]:
    """`classify` sonucu `ortam`/`derleme` olan koşunun kategorize Türkçe nedeni ve ham ayrıntısı
    (`(neden, detay)`). Ham metin (toolchain hatası, Appium adresi, test hata satırı) yalnız
    `detay`'dadır (güvenlik-12)."""
    rr = report.get("run") if isinstance(report.get("run"), Mapping) else None
    app = report.get("app")
    if isinstance(app, Mapping) and not app.get("skipped") and app.get("ok") is False:
        return (
            "Çalışan uygulama koşulan commit'le eşleşmiyor ya da doğrulanamadı.",
            _kirp(sinif.hata, MAX_DETAY),
        )
    if sinif.sinif == "derleme":
        return "Derleme/statik kontrol başarısız; testler koşmadı.", _kirp(sinif.hata, MAX_DETAY)
    if not rr:
        return "Toolchain raporunda test koşusu yok.", _kirp(report.get("summary"), MAX_DETAY)
    saglik = rr.get("saglik") if isinstance(rr.get("saglik"), Mapping) else None
    if saglik and saglik.get("ok") is False:
        appium = saglik.get("appium") if isinstance(saglik.get("appium"), Mapping) else None
        if appium and appium.get("hata"):
            ham = f"{appium.get('url') or '-'}: {appium['hata']}"
            if not appium.get("url"):
                return "Cihaz/Appium erişilemiyor: adres yapılandırılmamış.", _kirp(ham, MAX_DETAY)
            return "Cihaz/Appium erişilemiyor.", _kirp(ham, MAX_DETAY)
        return "Uygulama sağlık kontrolü başarısız.", _kirp(saglik.get("hata"), MAX_DETAY)
    if rr.get("status") == "error":
        return "Test koşucusu hata verdi.", _kirp(
            rr.get("error") or report.get("summary"), MAX_DETAY
        )
    java = java_raporu_mu(report)
    for t in _kirmizilar(report):
        if _test_turu(t, java) == "ortam":
            return (
                f"Test ortamı/kurulum hatası ({_ad(t)}) — hata uygulanamamış ya da uygulama "
                "erişilemiyor olabilir.",
                _kirp(_ilk_satir(t), MAX_DETAY),
            )
    return str(sinif.aciklama), _kirp(sinif.hata, MAX_DETAY)


def _adlar_metni(testler: Sequence[Mapping[str, Any]], n: int = 5) -> str:
    return ", ".join(list(dict.fromkeys(_ad(t) for t in testler))[:n])


def siniflandir(
    asama: str,
    report: Mapping[str, Any] | None,
    hata: str | None,
    temel_kirmizi: Iterable[str] = (),
    *,
    temel_yesil: Iterable[str] | None = None,
    ai_dosyalari: frozenset[str] = frozenset(),
) -> AdimSonucu:
    """Bir adımın sonucu (K12, Y8).

    - Temel: `yesil` | `kirmizi` (kırmızı testler listelenir, platform sürer) | `gecersiz`
      (ortam/altyapı/derleme, toolchain'e ulaşılamadı, test bilgisi olmadan kırmızı, temelde
      kırmızı test sayısı `MAX_TEMEL_KIRMIZI`'yı ya da yeşil sayısı `MAX_TEMEL_YESIL`'i aşıyor).
    - Hata: kanıt yalnız temelde yeşil (`temel_yesil` kümesinde) olup kırmızıya dönen testtir;
      temelde kırmızı ya da temelde görülmeyen testler sayılmaz. ≥ 1 assertion → `yakalandi`;
      temelde yeşil kırmızı yok → `kacti`; yalnız assertion dışı kırmızı ya da ortam →
      `gecersiz`. `temel_yesil` None ise (eski kayıt) temelde kırmızı olmayan her test sayılır.
    - Kapanış: temelde kırmızı olmayan kırmızı test → `kirmizi`; yoksa `yesil`; ortam →
      `gecersiz`.
    """
    if report is None:
        return AdimSonucu(
            "gecersiz",
            "Toolchain'e ulaşılamadı ya da istek reddedildi.",
            detay=_kirp(hata, MAX_DETAY),
        )
    s = classify(report)
    if s.sinif in ("ortam", "derleme"):
        neden, detay = ortam_nedeni(report, s)
        return AdimSonucu(
            "gecersiz", _kirp(neden), _kiran(_kirmizilar(report), ai_dosyalari), detay=detay
        )
    kirmizi = _kirmizilar(report)
    if asama == "temel":
        env = _envanter(report, ai_dosyalari)
        yesil = list(dict.fromkeys(test_anahtari(t) for t in _yesiller(report)))
        if len(yesil) > MAX_TEMEL_YESIL:
            return AdimSonucu(
                "gecersiz",
                f"Temelde {len(yesil)} yeşil test var (sınır {MAX_TEMEL_YESIL}); temel küme "
                "saklanamadı.",
                envanter=env,
            )
        if s.sinif == "gecti" and not kirmizi:
            return AdimSonucu("yesil", envanter=env, temel_yesil_anahtarlari=yesil)
        if not kirmizi:
            return AdimSonucu(
                "gecersiz",
                "Temel koşu kırmızı ama başarısız test bilgisi yok.",
                envanter=env,
                detay=_kirp(report.get("summary") or s.aciklama, MAX_DETAY),
            )
        anahtarlar = list(dict.fromkeys(test_anahtari(t) for t in kirmizi))
        if len(anahtarlar) > MAX_TEMEL_KIRMIZI:
            return AdimSonucu(
                "gecersiz",
                f"Temelde {len(anahtarlar)} test kırmızı (sınır {MAX_TEMEL_KIRMIZI}); platform "
                "ölçülemez.",
                _kiran(kirmizi, ai_dosyalari),
                envanter=env,
            )
        return AdimSonucu(
            "kirmizi",
            _kirp(
                f"Temelde {len(anahtarlar)} test kırmızı; bu testler hata adımlarında sayılmaz: "
                f"{_adlar_metni(kirmizi)}"
            ),
            _kiran(kirmizi, ai_dosyalari),
            envanter=env,
            temel_kirmizi_anahtarlari=anahtarlar,
            temel_yesil_anahtarlari=yesil,
        )
    haric = set(temel_kirmizi)
    temelde = [t for t in kirmizi if test_anahtari(t) in haric]
    temelde_adlar = list(dict.fromkeys(_ad(t) for t in temelde))[:MAX_KIRAN]
    if asama == "kapanis":
        yeni = [t for t in kirmizi if test_anahtari(t) not in haric]
        if not yeni:
            return AdimSonucu("yesil", temelde_kirmizi=temelde_adlar)
        return AdimSonucu(
            "kirmizi",
            _kirp(f"Temelde kırmızı olmayan {len(yeni)} test kırmızı: {_adlar_metni(yeni)}"),
            _kiran(yeni, ai_dosyalari),
            temelde_adlar,
        )
    if temel_yesil is None:
        yeni = [t for t in kirmizi if test_anahtari(t) not in haric]
        gorulmeyen: list[Mapping[str, Any]] = []
    else:
        yesil_kume = set(temel_yesil)
        yeni = [t for t in kirmizi if test_anahtari(t) in yesil_kume]
        gorulmeyen = [t for t in kirmizi if test_anahtari(t) not in yesil_kume | haric]
    ek = ""
    if gorulmeyen:
        ek = (
            f" Temel koşuda yeşil görülmeyen {len(gorulmeyen)} kırmızı test kanıt sayılmadı: "
            f"{_adlar_metni(gorulmeyen)}"
        )
    if not yeni:
        if s.sinif != "gecti" and not kirmizi:
            return AdimSonucu(
                "gecersiz",
                "Koşu kırmızı ama başarısız test bilgisi yok.",
                detay=_kirp(report.get("summary") or s.aciklama, MAX_DETAY),
            )
        neden = "Temelde yeşil testlerin hiçbiri kırmızıya dönmedi: hata yakalanmadı."
        if temelde_adlar:
            neden += f" (Temelde zaten kırmızı {len(temelde_adlar)} test sayılmadı.)"
        return AdimSonucu("kacti", _kirp(neden + ek), temelde_kirmizi=temelde_adlar)
    java = java_raporu_mu(report)
    assertion = [t for t in yeni if _test_turu(t, java) == "assertion"]
    if assertion:
        diger = [t for t in yeni if t not in assertion]
        parcalar = []
        if diger:
            parcalar.append(
                f"Assertion dışı kırmızı {len(diger)} test kanıt sayılmadı: {_adlar_metni(diger)}"
            )
        neden = _kirp(" ".join(parcalar) + ek) if parcalar or ek else None
        return AdimSonucu("yakalandi", neden, _kiran(assertion, ai_dosyalari), temelde_adlar)
    return AdimSonucu(
        "gecersiz",
        _kirp(
            "Kırmızı testlerin hiçbiri assertion ile kalmadı (locator/zaman aşımı/belirsiz); "
            f"hata yakalama kanıtı sayılmaz: {_adlar_metni(yeni)}{ek}"
        ),
        _kiran(yeni, ai_dosyalari),
        temelde_adlar,
    )


# ============================================================================== iş


def calistir(ctx: JobContext) -> dict[str, Any]:
    """`hata_kosusu.calistir` gövdesi: bir adım.

    DB/taşıma hatası (`gecici_mi`) son deneme değilse yeniden fırlatılır: iş yeniden denenir,
    adım `bekliyor` kalır (N4). Diğer beklenmeyen hatalar ve son denemedeki geçici hata koşuyu
    kapatır: iptal istenmişse `cancelled` (Y15), değilse `failed`. Görünen uyarı kategorize
    metindir; istisna metni yalnız denetime gider (güvenlik-12)."""
    try:
        kosu_id = uuid.UUID(str((ctx.yuk or {})["kosu_id"]))
    except (KeyError, ValueError) as exc:
        raise PermanentJobError("iş yükünde geçerli kosu_id yok") from exc
    try:
        return _adim_isle(kosu_id, son_deneme=ctx.son_deneme)
    except PermanentJobError:
        raise
    except Exception as exc:
        gecici = gecici_mi(exc)
        if gecici and not ctx.son_deneme:
            log.warning(
                "hata koşusu %s adımı geçici hatayla kesildi (deneme %d/%d); yeniden denenecek",
                kosu_id,
                ctx.deneme,
                ctx.max_deneme,
            )
            raise
        try:
            with session_scope() as s:
                kosu = _kilitle(s, kosu_id)
                if kosu is not None:
                    if _ic(kosu).get("iptal_istendi"):
                        _kapat(s, kosu, "cancelled", detay=_detay(exc))
                    else:
                        uyari = (
                            "Koşu veritabanı/ağ hatası nedeniyle yeniden denemelerden sonra durdu."
                            if gecici
                            else "Koşu beklenmeyen bir iç hatayla durdu."
                        )
                        _kapat(s, kosu, "failed", uyari, detay=_detay(exc))
        except Exception:  # asıl hata yüzeye çıksın; kalan koşuyu tarama kapatır
            log.exception("hata koşusu %s kapatılamadı", kosu_id)
        raise PermanentJobError(f"{type(exc).__name__}: {exc}") from exc


@dataclass(frozen=True)
class _Plan:
    adim_id: uuid.UUID
    platform: str
    asama: str
    kod: str | None
    sira: int
    sha: str
    isteyen: str
    temel_kirmizi: tuple[str, ...]
    temel_yesil: tuple[str, ...] | None
    ai_dosyalari: frozenset[str]


def _ilk_bekleyen(adimlar: Sequence[HataKosusuAdim]) -> HataKosusuAdim | None:
    return next((a for a in adimlar if a.sonuc == "bekliyor"), None)


def _commit_coz(son_deneme: bool) -> tuple[str | None, str | None]:
    """`main`'in commit'i — satır kilidi alınmadan önce (N12: ağ çağrısı iptali bekletmez).
    `(sha, hata ayrıntısı)`; geçici hata son deneme değilse yeniden fırlatılır."""
    try:
        sha = ci_services.forge().head_sha("main")
    except Exception as exc:
        if gecici_mi(exc) and not son_deneme:
            raise
        return None, _detay(exc)
    if not sha:
        return None, "main boş döndü"
    return str(sha), None


def _baslangic(s: Session, kosu: HataKosusu, sha: str | None, hata: str | None) -> bool:
    """`queued` → `running` (kilitli satır; commit önceden çözülmüştür). Çözülemediyse koşu
    `failed` (False); ayrıntı yalnız denetime."""
    if not sha:
        _kapat(s, kosu, "failed", "Koşulacak commit çözülemedi (main).", detay=hata)
        return False
    kosu.commit = sha
    kosu.durum = "running"
    kosu.baslama = _simdi()
    s.flush()
    _olay(s, kosu)
    return True


def _adim_isle(kosu_id: uuid.UUID, *, son_deneme: bool = True) -> dict[str, Any]:
    sha: str | None = None
    sha_hatasi: str | None = None
    with session_scope() as s:
        # Kilitsiz bakış: başlangıçta commit kilit dışında çözülür (N12).
        durum = s.scalar(select(HataKosusu.durum).where(HataKosusu.id == kosu_id))
    if durum == "queued":
        sha, sha_hatasi = _commit_coz(son_deneme)
    with session_scope() as s:
        kosu = _kilitle(s, kosu_id)
        if kosu is None:
            raise PermanentJobError("hata koşusu bulunamadı")
        if kosu.durum not in enums.HATA_KOSUSU_SUREN:
            return {"durum": kosu.durum, "atlandi": True}
        if _ic(kosu).get("iptal_istendi"):
            _kapat(s, kosu, "cancelled")
            return {"durum": kosu.durum}
        if kosu.durum == "queued":
            if sha is None and sha_hatasi is None:  # bakıştan sonra durum değişti (yarış)
                sha, sha_hatasi = None, "commit kilitten önce çözülmedi"
            if not _baslangic(s, kosu, sha, sha_hatasi):
                return {"durum": kosu.durum}
        adim = _ilk_bekleyen(_adimlar(s, kosu_id))
        if adim is None:
            _kapat(s, kosu, "done")
            return {"durum": kosu.durum, "ozet": _gorunen_ozet(kosu)}
        isteyen = "system"
        if kosu.baslatan_id is not None:
            isteyen = (
                s.scalar(select(AppUser.kullanici_adi).where(AppUser.id == kosu.baslatan_id))
                or "system"
            )
        temel = (_ic(kosu).get("temel") or {}).get(adim.platform) or {}
        yesil = temel.get("yesil")
        plan = _Plan(
            adim.id,
            adim.platform,
            adim.asama,
            adim.hata_kodu,
            adim.sira,
            str(kosu.commit),
            isteyen,
            tuple(temel.get("kirmizi") or ()),
            tuple(yesil) if isinstance(yesil, list) else None,
            uretilen_dosyalar(s, adim.platform),
        )
        _olay(s, kosu, platform=plan.platform, hata_kodu=plan.kod, asama=plan.asama, sonuc=None)
    # `/check` kilit dışında koşar (dakikalar sürebilir; iptal ve okuma beklemez).
    sonuc, run_id, sure_ms = _adim_kos(kosu_id, plan)
    with session_scope() as s:
        kosu = _kilitle(s, kosu_id)
        if kosu is None:
            raise PermanentJobError("hata koşusu bulunamadı")
        a = s.get(HataKosusuAdim, plan.adim_id, with_for_update=True, populate_existing=True)
        if kosu.durum not in enums.HATA_KOSUSU_SUREN or a is None or a.sonuc != "bekliyor":
            # Koşu bu arada kapandı (ör. tarama) ya da adım zaten yazıldı: bitmiş duruma dokunma.
            return {"durum": kosu.durum, "atlandi": True}
        _adim_yaz(s, kosu, a, sonuc, run_id, sure_ms)
        return _sonraki(s, kosu)


def _gorunen_ozet(kosu: HataKosusu) -> dict[str, Any]:
    return {k: v for k, v in dict(kosu.ozet or {}).items() if k != IC}


def _adim_yaz(
    s: Session,
    kosu: HataKosusu,
    a: HataKosusuAdim,
    sonuc: AdimSonucu,
    run_id: uuid.UUID | None,
    sure_ms: int | None,
) -> None:
    a.sonuc = sonuc.sonuc
    a.neden = _kirp(sonuc.neden)
    a.kiran_testler = list(sonuc.kiran_testler)
    a.run_id = run_id
    a.sure_ms = sure_ms
    ic = _ic(kosu)
    if sonuc.temelde_kirmizi:
        ic.setdefault("adim", {})[str(a.id)] = {"temelde_kirmizi": list(sonuc.temelde_kirmizi)}
    if a.asama == "temel":
        ic.setdefault("temel", {})[a.platform] = {
            **(sonuc.envanter or {"ai": 0, "el": 0}),
            "kirmizi": list(sonuc.temel_kirmizi_anahtarlari),
            "yesil": list(sonuc.temel_yesil_anahtarlari),
        }
    _ic_yaz(kosu, ic)
    s.flush()
    if sonuc.detay:
        audit_on_commit(
            s,
            "system",
            "hata_kosusu.adim_detayi",
            f"hata_kosusu:{kosu.id}",
            {
                "adim_id": str(a.id),
                "platform": a.platform,
                "hata_kodu": a.hata_kodu,
                "asama": a.asama,
                "sonuc": a.sonuc,
                "detay": sonuc.detay,
            },
        )
    _olay(s, kosu, platform=a.platform, hata_kodu=a.hata_kodu, asama=a.asama, sonuc=a.sonuc)
    platform_adimlari = [x for x in _adimlar(s, kosu.id) if x.platform == a.platform]
    if a.asama == "temel" and a.sonuc == "gecersiz":
        neden = _kirp(f"{TEMEL_YESIL_DEGIL}: {a.neden}" if a.neden else TEMEL_YESIL_DEGIL)
        for x in platform_adimlari:
            if x.sonuc == "bekliyor":
                x.sonuc = "gecersiz"
                x.neden = neden
        s.flush()
    elif a.asama == "kapanis" and a.sonuc != "yesil":
        # Hatalar geri alınmamış ya da uygulama kararsız: bu platformda kredi verilmez.
        etkilenen = 0
        for x in platform_adimlari:
            if x.asama == "hata" and x.sonuc in ("yakalandi", "kacti"):
                x.neden = _kirp(
                    f"{KAPANIS_KIRMIZI}; sonuç kanıt sayılmadı (önceki sonuç: {x.sonuc}). "
                    f"{x.neden or ''}"
                )
                x.sonuc = "gecersiz"
                etkilenen += 1
        kosu.uyarilar = [
            *(kosu.uyarilar or []),
            _kirp(
                f"{a.platform}: {KAPANIS_KIRMIZI} ({a.sonuc}); hatalar geri alınmamış ya da "
                f"uygulama kararsız olabilir, {etkilenen} hata adımı geçersiz sayıldı. "
                f"{a.neden or ''}"
            ),
        ]
        s.flush()


def _sonraki(s: Session, kosu: HataKosusu) -> dict[str, Any]:
    """Adım yazıldıktan sonra (aynı işlemde): iptal → `cancelled`; bekleyen adım → devam işi;
    yoksa `done`."""
    if _ic(kosu).get("iptal_istendi"):
        _kapat(s, kosu, "cancelled")
        return {"durum": kosu.durum}
    adim = _ilk_bekleyen(_adimlar(s, kosu.id))
    if adim is None:
        _kapat(s, kosu, "done")
        return {"durum": kosu.durum, "ozet": _gorunen_ozet(kosu)}
    job_id = _adim_isi(s.connection(), kosu.id, adim.sira)
    return {"durum": kosu.durum, "sonraki": adim.sira, "job_id": str(job_id)}


def _adim_kos(kosu_id: uuid.UUID, plan: _Plan) -> tuple[AdimSonucu, uuid.UUID | None, int]:
    from tp_core.features.ci.service import check_body_platformu

    body: dict[str, Any] = {
        "sha": plan.sha,
        "test_files": [],
        "repeat_each": 1,
        "retries": 0,
        "ast_guard_mode": "pr",
        # Hata koşusunun hiçbir adımı merge kapısına (`local-ci`) yazılmaz.
        "record_check": False,
        "run_id": f"hk-{kosu_id.hex[:8]}-{plan.asama}-{uuid.uuid4().hex[:6]}",
        # CI ile aynı dil alanları: web boş, uygulama `lang=java` + `platform`.
        **check_body_platformu(plan.platform),
    }
    if plan.kod:
        body["fault"] = plan.kod
    baslama = _simdi()
    t0 = time.monotonic()
    report: Mapping[str, Any] | None = None
    hata: str | None = None
    try:
        report = ci_services.toolchain().check(body)
    except ToolchainError as exc:
        hata = str(exc)
    sure_ms = int((time.monotonic() - t0) * 1000)
    sonuc = siniflandir(
        plan.asama,
        report,
        hata,
        plan.temel_kirmizi,
        temel_yesil=plan.temel_yesil,
        ai_dosyalari=plan.ai_dosyalari,
    )
    run_id = _kosu_kaydet(kosu_id, plan, report, hata, baslama)
    return sonuc, run_id, sure_ms


def _kosu_kaydet(
    kosu_id: uuid.UUID,
    plan: _Plan,
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
                commit=plan.sha,
                kaynak="local",
                tetik="break_verify",
                sonuc="running",
                baslama=baslama,
                ortam={
                    "retries": 0,
                    "repeat_each": 1,
                    "break_campaign": False,
                    "isteyen": plan.isteyen,
                    "ref": None,
                    "platform": plan.platform,
                    # 012 §4.6 / V6: KPI dışlama `tetik`'ten, triage atlaması `hata_kosusu_id`'den.
                    "hata_kodu": plan.kod,
                    "hata_kosusu_id": str(kosu_id),
                    "hata_kosusu_asama": plan.asama,
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


# ============================================================================== tarama


def tara() -> dict[str, Any]:
    """Periyodik tarama: işi bitmiş süren koşuları kapatır; süren koşu kaldıkça yeniden
    planlanır (`jobs.tarama`)."""
    with session_scope() as s:
        n = kurtar_hepsi(s)
        devam = suren_var(s)
        tarama_temizle(s.connection())
    return {"kapatilan": n, "devam": devam}
