"""Asistan cevap akışı — `assistant.answer` işinin mantığı (AI-ASISTAN-PLANI §10.2, §6.2, §10.1).

`cevapla(session_factory, mesaj_id, *, gateway_factory=None)` bir asistan mesajını cevaplar:

1. `pending → running` (+ `ai_call_id = deterministic_call_id(mesaj_id, amaç)`; koşan mesaj
   bütçe sayımına girer), `assistant.step yanitlaniyor`; maskeleyici ve mesajın tek oturumu.
   Mesaj artık `pending` değilse (iptal, uzlaştırma) hiçbir şey yapılmaz.
2. **Sözlük** (`sozluk`): `kip='soru'`, üst mesaj ve öneri bağlamı yok, bağlamda `son_hata` ve soru
   "ne demek/neden" sınıfında → `kaynak=sozluk`.
3. **Şablon** (`sablon`): aynı koşullarda tek Jira anahtarı + "neden/durum/nerede" → `probe_get`,
   "bugün ne yapmalıyım" → `probe_my_queue` (aynı araç fonksiyonu, oturumdaki rol) →
   `kaynak=sablon`.
4. **Kapalı**: `asistan_durum.model_hazir=false` → sabit cevap, `kaynak=kapali`. Geçit kurulmaz.
   Öneri kipinde sabit metin "Ek öneri için canlı model gerekir; kural önerileri yukarıda."
5. **Canlı**: `gateway_factory(budget=AsistanBudget(...))` (varsayılan: `build_gateway(
   mode_override="live", replay_fallback=False, budget=…)` — pipeline kipinden bağımsız, asla
   `record`, dosya yazmaz) → `run_agent(..., masking_session=oturum, tool_channel="asistan",
   caller_user_id, ek, bitis, should_stop, toparlama=True)`. Öneri kipinde (`kip='oneri'`) ilk
   kullanıcı mesajına aynı motorla yeniden hesaplanan kural önerileri `<untrusted kind=oneriler>`
   olarak eklenir; "Neden? Sor" sohbetinde öneri bağlamı sunucuda kuraldan yeniden üretilir.
6. §7.3 son işlem (`sonislem.isle`) → otomatik yükseltme kararı (§6.2) → `done` (+ gerekirse çocuk
   mesaj ve işi, **aynı transaction**) → `assistant.answered {…, derin_bekliyor}`.
6b. **Denetim** (011 F7; `denetim.py`, `TP_ASISTAN_DENETIM`): soru kural ön denetimi her yolda
   (2'den önce); canlı yolda soru port ile modelden önce, cevap (gösterilen tüm serbest metin,
   tavanda kesilmiş; önce modelsiz kural ön denetimi) port ile yazmadan önce puanlanır.
   `engelle` → `kaynak='denetim'` açıklama; `uyar` → not; port hatası → fail-closed.
7. İstisnalar yakalanır → `error` + `hata_kodu` (`butce_asildi`, `girdi_tavani`, `zaman_asimi`,
   `model_hatasi`); iptal hata değildir (durum `iptal` kalır). Kayda yalnız sınıf adı yazılır
   (`str(exc)` soru/araç metni taşıyabilir); şerit çökmez.

**Yarış korumaları (§10.1):** içerik/durum yazımı `UPDATE … WHERE durum='running'`
(`durum.sonuc_yaz`), maliyet/token/süre ayrı `UPDATE … WHERE durum IN ('running','iptal')`
(`durum.harcama_yaz`; iptal edilen koşan mesajın harcaması kaybolmaz).

**Otomatik yükseltme transaction sırası (§6.2; API POST ile aynı kilit anahtarı):**
(1) `budget.global_kilit` — İLK ifade; (2) harcama + `done` (`WHERE durum='running'`; 0 satır →
iptal edilmiş: çocuk yaratılmaz, yalnız harcama yazılır); (3) ön koşul sayımları (kendi işi
`job.id <> :mevcut_is`); (4) çocuk `asistan_mesaj` (`pending`, `assistant_deep`,
`tetik='otomatik'`); (5) `jobs.enqueue` aynı bağlantıyla ve çocuğun `job_id`'si.

Süre: iş başında mutlak `bitis = simdi + 75 sn` (geçit ve araçlar aynı `time.monotonic` ekseninde).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, cast

from sqlalchemy import Connection, Engine, text
from sqlalchemy.orm import Session

from tp_core.events import publish_tx
from tp_core.features.assistant import budget as asistan_budget
from tp_core.features.assistant import denetim as asistan_denetim
from tp_core.features.assistant import durum as mesaj_durumu
from tp_core.features.assistant import siniflandir, sonislem, sozluk
from tp_core.features.assistant.sablon import sablon_cevabi
from tp_core.features.assistant.tools.base import sir_temizle
from tp_core.gateway.errors import AgentDeadlineExceeded, AgentStopped, BudgetExceeded
from tp_core.gateway.untrusted import UntrustedKind, wrap_untrusted
from tp_core.ports import ModelMessage

log = logging.getLogger(__name__)

EV_STEP: Final = "assistant.step"
EV_ANSWERED: Final = mesaj_durumu.EV_ANSWERED
# `assistant.step` adım kodları (sabit sözlük; argüman/soru metni yok).
ADIM_YANITLANIYOR: Final = "yanitlaniyor"
ADIM_ARAC: Final = "arac"
ADIM_DOGRULANIYOR: Final = "dogrulaniyor"

CANLI_SURE_S: Final = 75.0
MAX_TURNS: Final = 6
GECMIS_MESAJ: Final = 6
GECMIS_KIRP: Final = 600
BUNDLE: Final = "assistant"
VARSAYILAN_AMAC: Final = "assistant"
DERIN_AMAC: Final = "assistant_deep"
ORTAM_OTOMATIK_DERIN: Final = "TP_ASISTAN_OTOMATIK_DERIN"
IS_ZAMAN_ASIMI_S: Final = asistan_budget.IS_ZAMAN_ASIMI_S  # tek kaynak budget.py

HATA_BUTCE: Final = mesaj_durumu.HATA_BUTCE
HATA_GIRDI: Final = "girdi_tavani"
HATA_ZAMAN: Final = mesaj_durumu.HATA_ZAMAN_ASIMI
HATA_MODEL: Final = mesaj_durumu.HATA_MODEL
GIRDI_KAPSAMI: Final = "ajan girdi token'ı"  # gateway.core BudgetExceeded.scope

KAPALI_METNI: Final = (
    "Canlı model kapalı; hata mesajlarını ve gereksinim/iş durumunu sorabilirsiniz."
)
KAPALI_CIPLERI: Final = (
    "Bu hata ne demek?",
    "Bugün ne yapmalıyım?",
)
# Üçüncü çip ekrandaki varlığın gerçek Jira anahtarıyla üretilir (portal `sorular.ts` gibi);
# anahtar yoksa genel biçim verilir (müşteri kurulumunda sabit bir örnek anahtar yanıltır).
KAPALI_DURUM_CIPI: Final = "{anahtar} neden bekliyor?"
KAPALI_DURUM_GENEL: Final = "<Jira anahtarı> neden bekliyor?"
ONERI_KAPALI_METNI: Final = "Ek öneri için canlı model gerekir; kural önerileri yukarıda."

ROL_ETIKETI: Final = {
    "analyst": "Analist",
    "po": "Ürün sahibi (PO)",
    "engineer": "Mühendis",
    "tester": "Testçi",
    "presenter": "Sunucu (sunum yapan)",
}

SessionFactory = Callable[[], Session]
GatewayFactory = Callable[..., Any]
"""`gateway_factory(budget=AsistanBudget) -> Gateway` (testler ve eval sahte sağlayıcılı geçit)."""


# ------------------------------------------------------------------ istisna sınıfları


def hata_kodu(exc: BaseException) -> str | None:
    """İstisna → `asistan_mesaj.hata_kodu`; iptal (`AgentStopped`) hata değildir → None."""
    if isinstance(exc, AgentStopped):
        return None
    if isinstance(exc, BudgetExceeded):
        return HATA_GIRDI if exc.scope == GIRDI_KAPSAMI else HATA_BUTCE
    if isinstance(exc, AgentDeadlineExceeded):
        return HATA_ZAMAN
    return HATA_MODEL


# ------------------------------------------------------------------ mesaj


@dataclass(frozen=True)
class Mesaj:
    id: uuid.UUID
    sohbet_id: uuid.UUID
    kullanici_id: uuid.UUID
    kullanici_adi: str
    rol: str
    sira: int
    icerik: str | None
    baglam: dict[str, Any] | None
    kip: str
    tetik: str
    amac: str | None
    ust_mesaj_id: uuid.UUID | None
    job_id: uuid.UUID | None
    oneri_kural_id: str | None

    @property
    def hedef_amac(self) -> str:
        return self.amac or VARSAYILAN_AMAC

    @property
    def derin(self) -> bool:
        return self.ust_mesaj_id is not None

    def oneri_kural(self) -> str | None:
        """Öneri bağlamı ("Neden? Sor"): mesajdaki `oneri.kural_id` ya da sohbetinki."""
        oneri = (self.baglam or {}).get("oneri")
        if isinstance(oneri, Mapping) and isinstance(oneri.get("kural_id"), str):
            return str(oneri["kural_id"])
        return self.oneri_kural_id


def _mesaj_oku(conn: Connection, mesaj_id: uuid.UUID) -> Mesaj:
    r = (
        conn.execute(
            text(
                "SELECT m.id, m.sohbet_id, m.kullanici_id, u.kullanici_adi, u.rol, m.sira, "
                "m.icerik, m.baglam, m.kip, m.tetik, m.amac, m.ust_mesaj_id, m.job_id, "
                "s.oneri_kural_id FROM asistan_mesaj m "
                "JOIN app_user u ON u.id = m.kullanici_id "
                "JOIN asistan_sohbet s ON s.id = m.sohbet_id WHERE m.id = :i"
            ),
            {"i": mesaj_id},
        )
        .mappings()
        .one()
    )
    return Mesaj(**{k: r[k] for k in Mesaj.__dataclass_fields__})


def _musteri_verisi(conn: Connection) -> bool:
    return bool(
        conn.execute(text("SELECT musteri_verisi FROM asistan_durum WHERE id = 1")).scalar()
    )


def _adim(conn: Connection, m: Mesaj, kod: str) -> None:
    publish_tx(
        conn,
        EV_STEP,
        {"mesaj_id": str(m.id), "kullanici_id": str(m.kullanici_id), "adim_kodu": kod},
    )


def _cevaplandi(conn: Connection, m: Mesaj, durum: str, *, derin_bekliyor: bool = False) -> None:
    publish_tx(
        conn,
        EV_ANSWERED,
        {
            "mesaj_id": str(m.id),
            "kullanici_id": str(m.kullanici_id),
            "durum": durum,
            "derin_bekliyor": derin_bekliyor,
        },
    )


def _sure_ms(conn: Connection, mesaj_id: uuid.UUID) -> int | None:
    deger = conn.execute(
        text(
            "SELECT (EXTRACT(EPOCH FROM (now() - olusturma)) * 1000)::int "
            "FROM asistan_mesaj WHERE id = :i"
        ),
        {"i": mesaj_id},
    ).scalar()
    return max(0, int(deger)) if deger is not None else None


def _mevcut_durum(conn: Connection, mesaj_id: uuid.UUID) -> str | None:
    return conn.execute(
        text("SELECT durum FROM asistan_mesaj WHERE id = :i"), {"i": mesaj_id}
    ).scalar()


# ------------------------------------------------------------------ yardımcı kurulumlar


def _engine(session_factory: SessionFactory) -> Engine:
    with session_factory() as s:
        bind = s.get_bind()
    return cast(Engine, getattr(bind, "engine", bind))


def varsayilan_gecit_fabrikasi(engine: Engine) -> GatewayFactory:
    """Üretim geçidi: pipeline kipinden bağımsız canlı, yedeksiz; `ai_call` Postgres'e yazılır."""

    def kur(*, budget: Any) -> Any:
        from tp_core.audit import PgCallRecorder
        from tp_core.gateway import build_gateway

        return build_gateway(
            PgCallRecorder(engine),
            engine=engine,
            mode_override="live",
            replay_fallback=False,
            budget=budget,
        )

    return kur


@dataclass(frozen=True)
class JiraAdresleri:
    kayit: Callable[[str], str | None] | None = None
    yeni_kayit: str | None = None
    proje: str | None = None


def _jira_adresleri() -> JiraAdresleri:
    """Jira bağlantıları yalnız sunucuda kurulur (§7.3, §17.4); ayar yoksa bağlantı yok."""
    try:
        from tp_core.features.assistant.oneri import jira_baglantisi

        j = jira_baglantisi()
    except Exception as exc:
        log.info("asistan: Jira bağlantı ayarı okunamadı (%s); bağlantı yok", type(exc).__name__)
        return JiraAdresleri()
    return JiraAdresleri(j.kayit_adresi, j.yeni_kayit_adresi(), j.proje)


def _otomatik_derin_acik() -> bool:
    return os.environ.get(ORTAM_OTOMATIK_DERIN, "1").strip().lower() not in ("0", "false", "off")


def _baglam_metni(baglam: Any, alan: str) -> str | None:
    deger = baglam.get(alan) if isinstance(baglam, Mapping) else None
    return deger if isinstance(deger, str) and deger else None


def _principal(m: Mesaj) -> Any:
    from tp_core.workflow.service import Principal

    return Principal(m.kullanici_id, m.kullanici_adi, m.rol)


# ------------------------------------------------------------------ ilk kullanıcı mesajı


def _cevap_metni(cevap: Any) -> str:
    if not isinstance(cevap, Mapping):
        return ""
    parcalar: list[str] = []
    for b in cevap.get("cevap_bloklari") or []:
        if not isinstance(b, Mapping):
            continue
        if b.get("metin"):
            parcalar.append(str(b["metin"]))
        parcalar += [str(x) for x in b.get("maddeler") or []]
    return " ".join(" ".join(parcalar).split())


def _derin_siniri(conn: Connection, m: Mesaj) -> tuple[int, uuid.UUID | None]:
    """Derin mesajın geçmiş sınırı: kök sorunun sırası ve üst (kısa) cevabın kimliği.

    "Daha ayrıntılı" eski bir cevaba da basılabilir ve çocuk sohbetin sonuna eklenir; geçmiş kök
    sorudan öncesiyle sınırlanır (kök soru `Soru:` satırında gider, sonraki sorular ilgisizdir).
    Kök soru `ust_mesaj_id` zincirinin başındaki cevabın sorusudur (zincirli derinde üst mesaj
    da sohbetin sonundadır; onun sırasından önceki son soru araya giren başka bir soru olabilir).
    Üst (kısa) cevap geçmişin son satırı olarak ayrıca eklenir."""
    if m.ust_mesaj_id is None:
        return m.sira, None
    kok_id = asistan_budget.kok_mesaj_id(conn, m.ust_mesaj_id)
    kok_sira = (
        conn.execute(
            text("SELECT sira FROM asistan_mesaj WHERE id = :k AND sohbet_id = :s"),
            {"k": kok_id, "s": m.sohbet_id},
        ).scalar_one_or_none()
        if kok_id is not None
        else None
    )
    if kok_sira is None:
        return m.sira, None
    soru = conn.execute(
        text(
            "SELECT MAX(sira) FROM asistan_mesaj WHERE sohbet_id = :s AND rol = 'user' "
            "AND sira < :k"
        ),
        {"s": m.sohbet_id, "k": kok_sira},
    ).scalar_one_or_none()
    return (soru if soru is not None else kok_sira), m.ust_mesaj_id


def sohbet_gecmisi(conn: Connection, m: Mesaj) -> str | None:
    """§6.5: son 6 mesajın metni, cevaplar 600 karaktere kırpılı (bu sorunun kendisi hariç).
    Derin mesajda kök sorudan öncesi + üst kısa cevap (`_derin_siniri`)."""
    sinir, ust_id = _derin_siniri(conn, m) if m.derin else (m.sira, None)
    satirlar = (
        conn.execute(
            text(
                "SELECT rol, icerik, cevap, sira FROM asistan_mesaj WHERE sohbet_id = :s "
                "AND (sira < :n OR id = :u) AND durum = 'done' ORDER BY sira DESC LIMIT :k"
            ),
            {"s": m.sohbet_id, "n": sinir, "u": ust_id, "k": GECMIS_MESAJ + 1},
        )
        .mappings()
        .all()
    )
    secilen = []
    for r in satirlar:
        if (
            not m.derin
            and r["rol"] == "user"
            and r["sira"] == m.sira - 1
            and r["icerik"] == m.icerik
        ):
            continue  # cevaplanan sorunun kendisi geçmiş değildir
        secilen.append(r)
    secilen = list(reversed(secilen[:GECMIS_MESAJ]))
    out = []
    for r in secilen:
        if r["rol"] == "user":
            out.append(f"Kullanıcı: {sonislem.kirp(' '.join((r['icerik'] or '').split()), 2000)}")
        else:
            metin = _cevap_metni(r["cevap"])
            if metin:
                out.append(f"Asistan: {sonislem.kirp(metin, GECMIS_KIRP)}")
    return "\n".join(out) or None


def _ekran_baglami(m: Mesaj, oneri_baglami: Mapping[str, Any] | None) -> dict[str, Any] | None:
    ekran = {k: v for k, v in (m.baglam or {}).items() if k != "oneri"}
    if oneri_baglami:
        ekran["oneri"] = {
            k: oneri_baglami.get(k) for k in ("kural_id", "baslik", "neden") if k in oneri_baglami
        }
    return ekran or None


def _blok(veri: Any, *, kaynak: str, tur: str) -> str:
    metin = veri if isinstance(veri, str) else json.dumps(veri, ensure_ascii=False, indent=1)
    return wrap_untrusted(metin, source=kaynak, kind=cast(UntrustedKind, tur))


def ilk_mesaj(
    m: Mesaj,
    *,
    ekran: Mapping[str, Any] | None,
    kural_onerileri: list[Mapping[str, Any]] | None,
    gecmis: str | None,
    sir_degerleri: Iterable[str] = (),
) -> list[ModelMessage]:
    """Rol ve bağlam sabit önekte değil ilk kullanıcı mesajında (§6.5 önbellek).

    Bütün metin worker'ın sır değerleriyle (`sir_temizle`) bir kez daha süzülür: core-api'nin
    422 `sir_icerik` taraması yalnız kendi ortamındaki değerleri bilir (Jira/GitHub okuma
    token'ları yalnız worker'dadır); soru, bağlam ve geçmiş modele sırsız gider."""
    parcalar = [
        f"Kullanıcının rolü: {ROL_ETIKETI.get(m.rol, m.rol)}",
        f"kip={m.kip}",
    ]
    if m.derin:
        parcalar.append(
            "Bu soru daha önce kısa yoldan cevaplandı; şimdi ayrıntılı ve kaynakla doğrulayarak "
            "yeniden incele. Cevabın dayandığı çağrılan fonksiyonların tanımını açıp kaynak göster."
        )
    if ekran:
        parcalar.append(_blok(ekran, kaynak="ekran", tur="ekran"))
    if kural_onerileri is not None:
        parcalar.append(_blok(kural_onerileri, kaynak="kural_onerileri", tur="oneriler"))
    if gecmis:
        parcalar.append(_blok(gecmis, kaynak="sohbet_gecmisi", tur="text"))
    parcalar.append(f"Soru: {m.icerik or ''}")
    icerik = sir_temizle("\n\n".join(parcalar), sir_degerleri)
    return [ModelMessage(role="user", content=icerik)]


def _kural_onerileri(session_factory: SessionFactory, m: Mesaj) -> list[dict[str, Any]]:
    """Öneri kipinde ekrandaki kural önerileri (aynı motor; modelsiz). `TP_ASISTAN_ONERI=0`
    (geri alma) iken boş: kuyrukta kalmış öneri kipi işi de kural önerisi taşımaz."""
    from tp_core.features.assistant import oneri

    if not oneri.oneri_etkin():
        return []
    baglam = m.baglam or {}
    varlik = baglam.get("varlik") if isinstance(baglam.get("varlik"), Mapping) else {}
    rota = baglam.get("rota_kalibi") or ""
    try:
        with session_factory() as s:
            sonuc = oneri.oneriler(s, _principal(m), str(rota), varlik.get("tur"), varlik.get("id"))
            s.rollback()
    except Exception as exc:
        log.info("asistan: kural önerileri hesaplanamadı (%s)", type(exc).__name__)
        return []
    return [
        {
            "kural_id": k.get("kural_id"),
            "baslik": k.get("baslik"),
            "neden": k.get("neden"),
            "eylem": (k.get("eylem") or {}).get("tur"),
        }
        for k in sonuc.get("oneriler") or []
    ]


def _oneri_baglami(session_factory: SessionFactory, m: Mesaj) -> dict[str, Any] | None:
    kural_id = m.oneri_kural()
    if not kural_id:
        return None
    from tp_core.features.assistant import oneri

    try:
        with session_factory() as s:
            sonuc = oneri.oneri_baglami(s, _principal(m), kural_id, m.baglam)
            s.rollback()
    except Exception as exc:
        log.info("asistan: öneri bağlamı hesaplanamadı (%s)", type(exc).__name__)
        return None
    return sonuc


# ------------------------------------------------------------------ sabit cevaplar


def kapali_cipleri(baglam: Mapping[str, Any] | None = None) -> list[str]:
    varlik = baglam.get("varlik") if isinstance(baglam, Mapping) else None
    anahtar = varlik.get("anahtar") if isinstance(varlik, Mapping) else None
    anahtarlar = siniflandir.jira_anahtarlari(anahtar if isinstance(anahtar, str) else None)
    durum = (
        KAPALI_DURUM_CIPI.format(anahtar=anahtarlar[0])
        if len(anahtarlar) == 1 and anahtarlar[0] == anahtar
        else KAPALI_DURUM_GENEL
    )
    return [*KAPALI_CIPLERI, durum]


def kapali_cevabi(kip: str, baglam: Mapping[str, Any] | None = None) -> dict[str, Any]:
    out = sonislem.bos_cevap()
    if kip == "oneri":
        out["cevap_bloklari"] = [{"tur": "paragraf", "metin": ONERI_KAPALI_METNI, "maddeler": []}]
        return out
    out["cevap_bloklari"] = [
        {"tur": "paragraf", "metin": KAPALI_METNI, "maddeler": []},
        {"tur": "liste", "metin": "Şunları sorabilirsiniz:", "maddeler": kapali_cipleri(baglam)},
    ]
    return out


# ------------------------------------------------------------------ harcama


@dataclass(frozen=True)
class Harcama:
    maliyet: Decimal = Decimal("0")
    girdi: int = 0
    cikti: int = 0
    toparlama: bool = False


def harcama_oku(engine: Engine, call_id: uuid.UUID, gw: Any = None) -> Harcama:
    """Kök çağrı + turları (`parent_call_id`); bellek içi kayıtçıda (eval) onun satırlarından."""
    satirlar = getattr(getattr(gw, "recorder", None), "ai_calls", None)
    if isinstance(satirlar, list):
        ilgili = [r for r in satirlar if call_id in (r.get("id"), r.get("parent_call_id"))]
        return Harcama(
            sum((Decimal(str(r.get("maliyet") or 0)) for r in ilgili), Decimal("0")),
            sum(int(r.get("girdi_token") or 0) for r in ilgili),
            sum(int(r.get("cikti_token") or 0) for r in ilgili),
            any(bool((r.get("ek") or {}).get("toparlama")) for r in ilgili),
        )
    with engine.connect() as conn:
        r = conn.execute(
            text(
                "SELECT COALESCE(SUM(maliyet), 0), COALESCE(SUM(girdi_token), 0), "
                "COALESCE(SUM(cikti_token), 0), "
                "COALESCE(bool_or((ek->>'toparlama')::boolean), false) "
                "FROM ai_call WHERE id = :c OR parent_call_id = :c"
            ),
            {"c": call_id},
        ).one()
    return Harcama(Decimal(str(r[0])), int(r[1]), int(r[2]), bool(r[3]))


# ------------------------------------------------------------------ otomatik yükseltme


# Modelin kendi cevabında yazdığı belirsizlik (birinci tekil; "emin değilseniz" gibi kullanıcıya
# yönelik kalıplar sayılmaz). Model `guven=orta` verip metinde "emin değilim" dediğinde rozet
# "Kaynakla doğrulandı" kalabilir (canlı eval s13, 2026-11-12): metin de tetik sayılır.
_BELIRSIZLIK: Final = re.compile(
    r"\b(emin değilim|emin olamadım|doğrulayamadım|teyit edemedim|bilmiyorum)\b"
)


def belirsizlik_ifadesi(cevap: Mapping[str, Any]) -> bool:
    """Cevap bloklarının görünen metninde belirsizlik ifadesi var mı (son işlem notları hariç)."""
    parcalar: list[str] = []
    for blok in cevap.get("cevap_bloklari") or []:
        if isinstance(blok, Mapping):
            parcalar.append(str(blok.get("metin") or ""))
            parcalar += [str(x) for x in blok.get("maddeler") or []]
    return bool(_BELIRSIZLIK.search(siniflandir.normalize(" ".join(parcalar))))


def otomatik_tetik(m: Mesaj, cevap: Mapping[str, Any]) -> bool:
    """§6.2 tetik (deterministik, son işlemden sonra). Ön koşullar ayrıca (`otomatik_on_kosul`).

    Ürüne özgü soruda modelin metinde yazdığı belirsizlik ("emin değilim", "doğrulayamadım")
    rozetten bağımsız tetikler (`belirsizlik_ifadesi`)."""
    if m.hedef_amac != VARSAYILAN_AMAC or m.kip != "soru" or not _otomatik_derin_acik():
        return False
    if cevap.get("eylem_reddi"):
        return False
    gosterim = cevap.get("guven_gosterimi")
    urune_ozgu = bool(cevap.get("urune_ozgu"))
    return (
        gosterim == sonislem.EMIN_DEGIL
        or (urune_ozgu and gosterim == sonislem.KISMEN)
        or (urune_ozgu and belirsizlik_ifadesi(cevap))
        or bool(cevap.get("toparlama"))
    )


def _cocuk_ekle(conn: Connection, m: Mesaj) -> uuid.UUID | None:
    """Otomatik "Daha ayrıntılı" çocuğu; `unique(ust_mesaj_id)` elle basışla yarışı çözer."""
    cocuk = uuid.uuid4()
    eklenen = conn.execute(
        text(
            "INSERT INTO asistan_mesaj (id, sohbet_id, kullanici_id, sira, rol, ust_mesaj_id, "
            "icerik, baglam, durum, amac, kip, tetik) "
            "SELECT :id, :s, :k, COALESCE(MAX(sira), 0) + 1, 'assistant', :u, :icerik, "
            "CAST(:baglam AS jsonb), 'pending', :amac, 'soru', 'otomatik' "
            "FROM asistan_mesaj WHERE sohbet_id = :s "
            # Silinmiş sohbete çocuk eklenmez (silme commit'lendikten sonra gelen ekleme).
            # HAVING: toplamlı SELECT boş kümede de bir satır döndürür, WHERE yetmez.
            "HAVING EXISTS (SELECT 1 FROM asistan_sohbet WHERE id = :s AND NOT silindi) "
            "ON CONFLICT (ust_mesaj_id) WHERE ust_mesaj_id IS NOT NULL DO NOTHING RETURNING id"
        ),
        {
            "id": cocuk,
            "s": m.sohbet_id,
            "k": m.kullanici_id,
            "u": m.id,
            "icerik": m.icerik,
            "baglam": json.dumps(m.baglam, ensure_ascii=False) if m.baglam is not None else None,
            "amac": DERIN_AMAC,
        },
    ).scalar()
    if eklenen is None:
        return None
    from tp_core.workflow import jobs

    is_id = jobs.enqueue(
        conn,
        asistan_budget.ASISTAN_IS_TURU,
        {"mesaj_id": str(cocuk), "kullanici_id": str(m.kullanici_id), "tetik": "otomatik"},
        idempotency_key=f"{asistan_budget.ASISTAN_IS_TURU}:{cocuk}",
        max_deneme=1,
        zaman_asimi_s=IS_ZAMAN_ASIMI_S,
    )
    conn.execute(
        text("UPDATE asistan_mesaj SET job_id = :j WHERE id = :i"), {"j": is_id, "i": cocuk}
    )
    return cocuk


def model_cevabini_yaz(
    session_factory: SessionFactory,
    m: Mesaj,
    cevap: dict[str, Any],
    harcama: Harcama,
) -> str:
    """Canlı cevabın tek transaction'ı (§6.2 sırası). Dönüş: mesajın son durumu."""
    tetik = otomatik_tetik(m, cevap)
    kok: uuid.UUID | None = None
    kalan: asistan_budget.Kalanlar | None = None
    if tetik:
        # Bütçe kalanları (`ai_call` toplamları) global kilitten ÖNCE, ayrı okumada: kilit
        # altında yalnız sayaçlar kalır (API POST de bütçeyi kilitten önce okur; §6.2).
        with session_factory() as s:
            kok = asistan_budget.kok_mesaj_id(s.connection(), m.id) or m.id
            kalan = asistan_budget.kalanlar(s.connection(), m.kullanici_id, kok_id=kok)
            s.rollback()
    with session_factory() as s:
        conn = s.connection()
        if tetik:
            asistan_budget.global_kilit(conn)  # (1) İLK ifade — API POST ile aynı kilit sırası
        mesaj_durumu.harcama_yaz(
            conn,
            m.id,
            maliyet_usd=harcama.maliyet,
            token_girdi=harcama.girdi,
            token_cikti=harcama.cikti,
            sure_ms=_sure_ms(conn, m.id),
        )
        yazildi = mesaj_durumu.sonuc_yaz(
            conn, m.id, durum="done", cevap=cevap, kaynak="model", amac=m.hedef_amac
        )  # (2)
        if not yazildi:  # kullanıcı iptal etti / uzlaştırıldı: yalnız harcama kalır
            son = _mevcut_durum(conn, m.id) or "iptal"
            s.commit()
            return son
        derin_bekliyor = False
        if tetik and kok is not None:
            karar = asistan_budget.otomatik_on_kosul(  # (3)
                conn, m.kullanici_id, kok, mevcut_is=m.job_id, kalan=kalan
            )
            if karar.yukselt:
                derin_bekliyor = _cocuk_ekle(conn, m) is not None  # (4) + (5)
            else:
                # Ön koşul tutmadı: düğme kalır ve kart "Daha ayrıntılı incele"yi önerir.
                conn.execute(
                    text(
                        "UPDATE asistan_mesaj SET cevap = cevap || "
                        "jsonb_build_object('derin_onerilir', true) WHERE id = :i"
                    ),
                    {"i": m.id},
                )
        _cevaplandi(conn, m, "done", derin_bekliyor=derin_bekliyor)
        s.commit()
    return "done"


def _modelsiz_yaz(
    session_factory: SessionFactory, m: Mesaj, cevap: dict[str, Any], kaynak: str
) -> str:
    with session_factory() as s:
        conn = s.connection()
        mesaj_durumu.harcama_yaz(conn, m.id, sure_ms=_sure_ms(conn, m.id))
        yazildi = mesaj_durumu.sonuc_yaz(
            conn, m.id, durum="done", cevap=cevap, kaynak=kaynak, ai_call_id=None
        )
        if not yazildi:
            son = _mevcut_durum(conn, m.id) or "iptal"
            s.commit()
            return son
        _cevaplandi(conn, m, "done")
        s.commit()
    return "done"


def _denetim_yaz(
    session_factory: SessionFactory,
    m: Mesaj,
    cevap: dict[str, Any],
    harcama: Harcama | None,
    *,
    model_calisti: bool,
) -> str:
    """Denetimin engellediği / denetimsiz kalan mesaj (`kaynak='denetim'`; derin incelenemez)."""
    with session_factory() as s:
        conn = s.connection()
        h = harcama or Harcama()
        mesaj_durumu.harcama_yaz(
            conn,
            m.id,
            maliyet_usd=h.maliyet,
            token_girdi=h.girdi,
            token_cikti=h.cikti,
            sure_ms=_sure_ms(conn, m.id),
        )
        yazildi = mesaj_durumu.sonuc_yaz(
            conn,
            m.id,
            durum="done",
            cevap=cevap,
            kaynak=asistan_denetim.KAYNAK,
            amac=m.hedef_amac,
            **({} if model_calisti else {"ai_call_id": None}),
        )
        if not yazildi:
            son = _mevcut_durum(conn, m.id) or "iptal"
            s.commit()
            return son
        _cevaplandi(conn, m, "done")
        s.commit()
    return "done"


def _harcama_ekle(a: Harcama, b: Harcama) -> Harcama:
    return Harcama(a.maliyet + b.maliyet, a.girdi + b.girdi, a.cikti + b.cikti, a.toparlama)


def _denetim_harcamasi(engine: Engine | None, d: Any, gw: Any) -> Harcama:
    toplam = Harcama()
    if engine is None:
        return toplam
    for cid in d.ai_call_ids:
        try:
            toplam = _harcama_ekle(toplam, harcama_oku(engine, cid, gw))
        except Exception:
            continue
    return toplam


def _hata_yaz(
    session_factory: SessionFactory, m: Mesaj, kod: str | None, harcama: Harcama | None
) -> str:
    """Hata/iptal: harcama (`running`/`iptal`) her durumda; `error` yalnız hâlâ `running` ise."""
    with session_factory() as s:
        conn = s.connection()
        if harcama is not None:
            mesaj_durumu.harcama_yaz(
                conn,
                m.id,
                maliyet_usd=harcama.maliyet,
                token_girdi=harcama.girdi,
                token_cikti=harcama.cikti,
                sure_ms=_sure_ms(conn, m.id),
            )
        if kod is not None and mesaj_durumu.sonuc_yaz(conn, m.id, durum="error", hata_kodu=kod):
            _cevaplandi(conn, m, "error")
            s.commit()
            return "error"
        son = _mevcut_durum(conn, m.id) or "iptal"
        if kod is None and son == "running":
            # Geçit durdu ama mesaj hâlâ koşuyor (should_stop yarışı): iptal gibi kapat.
            mesaj_durumu.sonuc_yaz(conn, m.id, durum="iptal")
            _cevaplandi(conn, m, "iptal")
            son = "iptal"
        s.commit()
    return son


# ------------------------------------------------------------------ giriş noktası


def _baslat(
    session_factory: SessionFactory, mesaj_id: uuid.UUID
) -> tuple[Mesaj, bool, bool] | None:
    with session_factory() as s:
        conn = s.connection()
        if not mesaj_durumu.baslat(conn, mesaj_id):
            s.rollback()
            return None
        m = _mesaj_oku(conn, mesaj_id)
        # Koşan mesaj bütçe sayımına girsin (§6.4): kök çağrı kimliği baştan yazılır.
        mesaj_durumu.sonuc_yaz(
            conn,
            mesaj_id,
            ai_call_id=_cagri_kimligi(m),
        )
        _adim(conn, m, ADIM_YANITLANIYOR)
        hazir = mesaj_durumu.model_hazir_oku(conn)
        musteri = _musteri_verisi(conn)
        s.commit()
    return m, hazir, musteri


def _cagri_kimligi(m: Mesaj) -> uuid.UUID:
    from tp_core.gateway.core import deterministic_call_id

    return deterministic_call_id(m.id, m.hedef_amac)


def cevapla(
    session_factory: SessionFactory,
    mesaj_id: uuid.UUID,
    *,
    gateway_factory: GatewayFactory | None = None,
    arac_seti_fabrikasi: Callable[[Any], Any] | None = None,
    dogrulayici: sonislem.Dogrulayici | None = None,
    masker: Any = None,
    rules_dir: Path | None = None,
    saat: Callable[[], float] = time.monotonic,
) -> str | None:
    """Mesajı cevaplar; son durumu (`done` | `error` | `iptal`) ya da mesaj başlatılamadıysa None
    döndürür. Bilinen hiçbir hata dışarı taşmaz (şerit çökmez).

    - `gateway_factory(budget=...)`: canlı geçit; None → `varsayilan_gecit_fabrikasi`. Kapalı
      kipte, sözlük ve şablon dallarında **hiç çağrılmaz**.
    - `arac_seti_fabrikasi(arac_baglami) -> AracSeti`: vars. `varsayilan_araclar` (`tools.arac_seti`
      + aynı `CodeTools`/bilgi paketini paylaşan doğrulayıcı).
    - `dogrulayici`: §7.3 kaynak doğrulamasının dış okumaları (vars. bilgi paketi/forge/demo DB).
    - `masker`: `PiiMasker` (vars. `maskeleme.maskeleyici()`).
    """
    basla = _baslat(session_factory, mesaj_id)
    if basla is None:
        return None
    m, model_hazir, musteri_verisi = basla
    cid = _cagri_kimligi(m)
    canli = False
    gw: Any = None
    engine: Engine | None = None
    denetim_acik = asistan_denetim.acik()
    d = asistan_denetim.Denetim()
    try:
        from tp_core.features.assistant.maskeleme import mesaj_oturumu
        from tp_core.features.assistant.tools import arac_baglami

        bitis = saat() + CANLI_SURE_S
        oturum = mesaj_oturumu(masker)
        ab = arac_baglami(m.kullanici_id, m.rol, oturum, db=session_factory, bitis=bitis)
        jira = _jira_adresleri()
        # Öneri sohbetinde sözlük/şablon yalnız öneri bağlamı gerçekten kurulabiliyorsa atlanır:
        # bayrak (`TP_ASISTAN_ONERI`) kapandıysa ya da kural artık geçersizse bağlam None olur
        # ve takip sorusu normal kanallardan (sözlük → şablon → kapalı/canlı) cevaplanır.
        oneri_baglami = _oneri_baglami(session_factory, m) if m.oneri_kural() else None
        oneri_var = oneri_baglami is not None
        dogrudan = m.kip == "soru" and not m.derin and not oneri_var

        # (1b) Denetim: kural ön denetimi (modelsiz; her yol). Engel → model çağrılmaz.
        on_puan: Any = None
        if denetim_acik:
            on_puan = asistan_denetim.kural_puani(m.icerik or "", "soru", m.id)
            if on_puan.karar == "engelle":
                d.soru.append(on_puan)
                asistan_denetim.kaydet(session_factory, m.id, m.kullanici_adi, on_puan)
                return _denetim_yaz(
                    session_factory,
                    m,
                    asistan_denetim.engel_cevabi(d, "soru"),
                    None,
                    model_calisti=False,
                )

        def modelsiz(cevap: dict[str, Any], kaynak: str) -> str:
            if on_puan is not None:
                d.soru.append(on_puan)
                asistan_denetim.kaydet(session_factory, m.id, m.kullanici_adi, on_puan)
                cevap = asistan_denetim.isaretle(cevap, d)
            return _modelsiz_yaz(session_factory, m, cevap, kaynak)

        # (2) Sözlük
        son_hata = (m.baglam or {}).get("son_hata")
        if dogrudan and son_hata and siniflandir.sozluk_sorusu(m.icerik, m.baglam):
            kayit = sozluk.bul(son_hata, rules_dir=rules_dir)
            if kayit is not None:
                cevap = sozluk.cevap(kayit, m.baglam, rules_dir=rules_dir)
                if musteri_verisi:
                    cevap, _ = oturum.mask(cevap)
                return modelsiz(cevap, "sozluk")

        # (3) Şablon
        if dogrudan:
            sablon = sablon_cevabi(
                ab, m.icerik, jira_adresi=jira.kayit, musteri_verisi=musteri_verisi
            )
            if sablon is not None:
                return modelsiz(sablon.cevap, "sablon")

        # (4) Kapalı kip: geçit kurulmaz.
        if not model_hazir:
            return modelsiz(kapali_cevabi(m.kip, m.baglam), "kapali")

        # (5) Canlı
        canli = True
        engine = _engine(session_factory)
        with session_factory() as s:
            kok = asistan_budget.kok_mesaj_id(s.connection(), m.id) or m.id
            gecmis = sohbet_gecmisi(s.connection(), m)
            s.rollback()
        kural_onerileri = _kural_onerileri(session_factory, m) if m.kip == "oneri" else None
        butce = asistan_budget.AsistanBudget(engine, kullanici_id=m.kullanici_id, kok_id=kok)
        gw = (gateway_factory or varsayilan_gecit_fabrikasi(engine))(budget=butce)

        # (5a) Denetim: soru asistan modeline gitmeden (derinde üst mesajın puanı kullanılır).
        if denetim_acik:
            if on_puan is not None and on_puan.karar != "gec":
                d.soru.append(on_puan)
            onceki = (
                asistan_denetim.onceki_soru_puani(session_factory, m.ust_mesaj_id)
                if m.derin and m.ust_mesaj_id is not None
                else None
            )
            if onceki is not None:
                d.soru.append(onceki)
                asistan_denetim.kaydet(session_factory, m.id, m.kullanici_adi, *d.soru)
            else:
                try:
                    p = asistan_denetim.port_puani(
                        m.icerik or "", "soru", mesaj_id=m.id, kullanici_id=m.kullanici_id, gw=gw
                    )
                except asistan_denetim.DenetimCalismiyor as exc:
                    return _denetim_calismiyor(session_factory, m, d, "soru", str(exc), engine, gw)
                d.soru.append(p)
                if p.skor.ai_call_id:
                    d.ai_call_ids.append(p.skor.ai_call_id)
                asistan_denetim.kaydet(session_factory, m.id, m.kullanici_adi, *d.soru)
            if d.soru_karari() == "engelle":
                return _denetim_yaz(
                    session_factory,
                    m,
                    asistan_denetim.engel_cevabi(d, "soru"),
                    _denetim_harcamasi(engine, d, gw),
                    model_calisti=False,
                )
        if arac_seti_fabrikasi is None:
            araclar, varsayilan_dogrulayici = varsayilan_araclar(ab)
        else:
            araclar, varsayilan_dogrulayici = arac_seti_fabrikasi(ab), None
        from tp_core.gateway.bundle import load_schema
        from tp_core.gateway.config import find_rules_dir

        sema = load_schema(find_rules_dir(rules_dir), m.hedef_amac)
        motor = engine

        def adim(_step: Any) -> None:
            try:
                with motor.begin() as conn:
                    _adim(conn, m, ADIM_ARAC)
            except Exception as exc:  # olay yayını cevabı düşürmez
                log.debug("asistan adım olayı yayınlanamadı (%s)", type(exc).__name__)

        try:
            sonuc = gw.run_agent(
                m.hedef_amac,
                BUNDLE,
                ilk_mesaj(
                    m,
                    ekran=_ekran_baglami(m, oneri_baglami),
                    kural_onerileri=kural_onerileri,
                    gecmis=gecmis,
                    sir_degerleri=ab.sir_degerleri,
                ),
                araclar.specs,
                araclar.execute,
                sema,
                replay_key={},
                max_turns=MAX_TURNS,
                workflow_id=None,
                on_step=adim,
                is_snapshot=lambda *_: False,
                call_id=cid,
                tool_channel="asistan",
                caller_user_id=m.kullanici_id,
                ek={"kanal": "asistan", "kullanici_id": str(m.kullanici_id), "mesaj_id": str(m.id)},
                masking_session=oturum,
                bitis=bitis,
                should_stop=mesaj_durumu.durdurma_kontrolu(engine, m.id),
                toparlama=True,
            )
            with engine.begin() as conn:
                _adim(conn, m, ADIM_DOGRULANIYOR)
            harcama = harcama_oku(engine, cid, gw)
            arac_adlari = [st.tool for st in sonuc.steps if st.allowed]
            sb = sonislem.SonIslemBaglami(
                havuz=araclar.havuz,
                oturum=oturum,
                urune_ozgu=siniflandir.urune_ozgu(m.icerik, m.baglam, araclar=arac_adlari),
                toparlama=harcama.toparlama,
                kip=m.kip,
                dogrulayici=dogrulayici
                or varsayilan_dogrulayici
                or sonislem.VarsayilanDogrulayici(),
                bilinen_anahtar=_bilinen_anahtar(ab),
                gereksinim_kimligi=_gereksinim_kimligi(ab),
                kayit_adresi=jira.kayit,
                yeni_kayit_adresi=jira.yeni_kayit,
                proje=jira.proje,
                kural_basliklari=[str(k.get("baslik") or "") for k in kural_onerileri or []],
                bitis=bitis,
                saat=saat,
                musteri_verisi=musteri_verisi,
                sir_degerleri=ab.sir_degerleri,
                rota_kalibi=_baglam_metni(m.baglam, "rota_kalibi"),
                varlik_turu=_baglam_metni((m.baglam or {}).get("varlik"), "tur"),
                rol=m.rol,
                soru=m.icerik,
                baglam=m.baglam if isinstance(m.baglam, Mapping) else None,
            )
            cevap = sonislem.isle(sonuc.output, sb)
        finally:
            araclar.havuz.temizle()
        # (6a) İçerik kontrolü: cevap kullanıcıya gösterilmeden. Gösterilen tüm serbest metin
        # alanları puanlanır; tavanı aşan cevap tavanda kesilir; önce modelsiz kural ön denetimi.
        if denetim_acik:
            cevap, d.kesildi = asistan_denetim.tavana_kes(cevap)
            gosterilen = asistan_denetim.gosterilen_metin(cevap)
            on_cevap = asistan_denetim.cevap_kural_puani(gosterilen, m.id)
            if on_cevap.karar == "engelle":
                d.cevap = on_cevap
                asistan_denetim.kaydet(session_factory, m.id, m.kullanici_adi, on_cevap)
                return _denetim_yaz(
                    session_factory,
                    m,
                    asistan_denetim.engel_cevabi(d, "cevap"),
                    harcama,
                    model_calisti=True,
                )
            try:
                p = asistan_denetim.port_puani(
                    gosterilen or "(boş cevap)",
                    "cevap",
                    mesaj_id=m.id,
                    kullanici_id=m.kullanici_id,
                    gw=gw,
                    soru=m.icerik,
                    kaynak_ozetleri=asistan_denetim.kaynak_ozetleri(cevap),
                )
            except asistan_denetim.DenetimCalismiyor as exc:
                return _denetim_calismiyor(
                    session_factory, m, d, "cevap", str(exc), engine, gw, harcama=harcama
                )
            d.cevap = p
            if p.skor.ai_call_id:
                d.ai_call_ids.append(p.skor.ai_call_id)
            asistan_denetim.kaydet(session_factory, m.id, m.kullanici_adi, p)
            harcama = _harcama_ekle(harcama, _denetim_harcamasi(engine, d, gw))
            if p.karar == "engelle":
                return _denetim_yaz(
                    session_factory,
                    m,
                    asistan_denetim.engel_cevabi(d, "cevap"),
                    harcama,
                    model_calisti=True,
                )
            cevap = asistan_denetim.isaretle(cevap, d)
        return model_cevabini_yaz(session_factory, m, cevap, harcama)
    except Exception as exc:
        kod = hata_kodu(exc)
        # Kayda yalnız sınıf adı (`str(exc)` soru/araç metni taşıyabilir).
        log.warning("asistan mesajı %s: %s (%s)", m.id, kod or "durduruldu", type(exc).__name__)
        hata_harcamasi: Harcama | None = None
        if canli and engine is not None:
            try:
                hata_harcamasi = harcama_oku(engine, cid, gw)
            except Exception:
                hata_harcamasi = None
        try:
            return _hata_yaz(session_factory, m, kod, hata_harcamasi)
        except Exception as yazma:
            log.warning("asistan mesajı %s hata olarak yazılamadı (%s)", m.id, type(yazma).__name__)
            return "error"


def _denetim_calismiyor(
    session_factory: SessionFactory,
    m: Mesaj,
    d: Any,
    yon: str,
    neden: str,
    engine: Engine | None,
    gw: Any,
    *,
    harcama: Harcama | None = None,
) -> str:
    """Fail-closed: denetim yoksa asistan cevap vermez (K11)."""
    log.warning("asistan mesajı %s: denetim çalışmıyor (%s, %s)", m.id, yon, neden)
    asistan_denetim.calismiyor_kaydet(session_factory, m.id, yon, neden)
    toplam = _harcama_ekle(harcama or Harcama(), _denetim_harcamasi(engine, d, gw))
    if engine is not None:
        # Başarısız denetim çağrısının maliyeti (`ai_call` kök satırı + yeniden istemeler).
        from tp_core.gateway.core import deterministic_call_id

        try:
            ek = harcama_oku(engine, deterministic_call_id(m.id, f"assistant_guard:{yon}"), gw)
            toplam = _harcama_ekle(toplam, ek)
        except Exception:
            pass
    return _denetim_yaz(
        session_factory,
        m,
        asistan_denetim.calismiyor_cevabi(d, yon),
        toplam,
        model_calisti=yon == "cevap",
    )


def _tek_sefer(kur: Callable[[], Any]) -> Callable[[], Any]:
    """İlk çağrıda kurar, sonra aynı nesneyi döndürür (iş parçacığı güvenli)."""
    kilit = threading.Lock()
    kutu: list[Any] = []

    def al() -> Any:
        with kilit:
            if not kutu:
                kutu.append(kur())
            return kutu[0]

    return al


def varsayilan_araclar(ab: Any) -> tuple[Any, sonislem.VarsayilanDogrulayici]:
    """Üretim araç seti + aynı kaynakları paylaşan doğrulayıcı.

    §7.3 "aynı sha'da": test edilen uygulamanın `CodeTools`'u (forge + `head_sha`) araçla
    doğrulama arasında paylaşılır ve yalnız gerektiğinde bir kez kurulur; ürün bilgi paketi de
    aynı nesnedir.
    """
    from tp_core.features.assistant.tools import arac_seti, kod_araclari
    from tp_core.features.assistant.tools.product import UrunBilgisi

    urun = UrunBilgisi()
    kod = _tek_sefer(kod_araclari)
    return arac_seti(ab, urun=urun, kod=kod), sonislem.VarsayilanDogrulayici(urun=urun, kod=kod)


def _gereksinim_kimligi(ab: Any) -> Callable[[str], str | None]:
    def kimlik(anahtar: str) -> str | None:
        from tp_core.features.assistant.tools.jira import gereksinim_kimligi

        return gereksinim_kimligi(ab, anahtar)

    return kimlik


def _bilinen_anahtar(ab: Any) -> Callable[[str], bool]:
    def bilinir(anahtar: str) -> bool:
        from tp_core.features.assistant.tools.jira import bilinen_anahtar_mi

        return bilinen_anahtar_mi(ab, anahtar)

    return bilinir
