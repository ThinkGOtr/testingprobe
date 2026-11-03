"""Asistanın worker tarafı durumu (AI-ASISTAN-PLANI §10.1).

İki parça:

1. **Servis durumu (`asistan_durum`, kalp atışı).** Tekil satırı (`id = 1`) YALNIZ worker yazar;
   core-api okur ve kalp atışı 2 dakikadan eskiyse asistanı `etkin=false, neden=worker_yok`
   gösterir (core-api model anahtarını ve kipini bilmez, İlke II). Worker açılış kancası
   (`jobs.on_worker_start`) ve ayrı bir zamanlayıcı iş parçacığı (`worker.run`, 30 sn) yazar:
   - `mod` = `TP_ASISTAN_MODEL_MODE` (`live` | `off`; boş/bilinmeyen → `off`);
   - `maskeleme` = `TP_PII_MASKING`, `musteri_verisi` = `TP_ASISTAN_MUSTERI_VERISI`;
   - `model_hazir` = anahtar var **ve** mod `live` **ve** (müşteri verisi değil **veya** maskeleme
     açık) — müşteri verisi kurulumunda maskeleme kapalıysa canlı dala hiç girilmez;
   - `paket_commit`/`paket_uretim` = ürün bilgi paketinin MANIFEST'i (yoksa boş);
   - `kalp_atisi` = DB saati (`now()`; API de DB saatiyle karşılaştırır).
   `TP_WORKER_ASISTAN_SERIT=0` iken asistan şeridi koşmaz ve kalp atışı yazılmaz → asistan kapalı
   görünür (belgelenmiş davranış).

2. **Mesaj durumu (yarış korumaları ve uzlaştırma).** API, işleyici ve iptal ucu aynı satıra
   eşzamanlı yazabilir; her yazım koşullu `UPDATE`'tir ve etkilediği satır sayısıyla "kazandım mı"
   bilgisini döndürür:
   - `baslat`: `pending → running` (iptal edilmiş/uzlaştırılmış mesaj başlatılmaz);
   - `sonuc_yaz`: içerik/durum alanları yalnız `durum = 'running'` iken (iptal edilen ya da zaman
     aşımıyla `error`'a çekilen mesajın sonucu geç biten iş tarafından ezilmez);
   - `harcama_yaz`: maliyet/token/süre `durum IN ('running', 'iptal')` iken (iptal edilen koşan
     mesajın harcaması kaybolmaz);
   - `hata_yaz`: beklenmedik işleyici hatasında `pending`/`running` → `error`;
   - `durdurulmali` / `durdurma_kontrolu`: geçidin `should_stop`'u (`durum != 'running'`);
   - `uzlastir`: işi bitmiş (`done`/`failed`/`cancelled`) ya da hiç olmayan `pending`/`running`
     mesajları `error/zaman_asimi` yapar (asistan şeridi her turda; zaman aşımı ve önceki süreçten
     kalan işler). Kapanan her mesaj için `assistant.answered` olayı yayınlanır.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import Connection, Engine, func, text, update

from tp_core.events import publish_tx
from tp_core.models import enums
from tp_core.models.asistan import AsistanMesaj

log = logging.getLogger("tp_core.worker")

EV_ANSWERED: Final = "assistant.answered"

ORTAM_SERIT: Final = "TP_WORKER_ASISTAN_SERIT"
ORTAM_MOD: Final = "TP_ASISTAN_MODEL_MODE"
ORTAM_MUSTERI_VERISI: Final = "TP_ASISTAN_MUSTERI_VERISI"

HATA_ZAMAN_ASIMI: Final = "zaman_asimi"
HATA_MODEL: Final = "model_hatasi"
HATA_BUTCE: Final = "butce_asildi"
# İşi olmayan (job_id boş) bekleyen mesaj bu kadar eskiyse uzlaştırılır. API mesajı ve işi aynı
# transaction'da yazar; boş `job_id` ancak elle/yarım kayıtla oluşur — taze satıra dokunulmaz.
ISSIZ_MESAJ_ESIGI_S: Final = 60

_DOGRU = frozenset({"1", "true", "yes", "on", "evet"})
_YANLIS = frozenset({"0", "false", "no", "off", "hayir", "hayır"})


def _bayrak(ad: str, varsayilan: bool, ortam: Mapping[str, str] | None = None) -> bool:
    deger = (os.environ if ortam is None else ortam).get(ad, "").strip().lower()
    if deger in _DOGRU:
        return True
    if deger in _YANLIS:
        return False
    return varsayilan


def asistan_serit_acik(ortam: Mapping[str, str] | None = None) -> bool:
    """`TP_WORKER_ASISTAN_SERIT` (varsayılan açık)."""
    return _bayrak(ORTAM_SERIT, True, ortam)


# ------------------------------------------------------------------ servis durumu


@dataclass(frozen=True)
class AsistanDurumu:
    mod: str
    model_hazir: bool
    maskeleme: bool
    musteri_verisi: bool
    paket_commit: str | None = None
    paket_uretim: datetime | None = None


def model_hazir_mi(*, anahtar_var: bool, mod: str, musteri_verisi: bool, maskeleme: bool) -> bool:
    """§10.1 kuralı: anahtar ve `live` kip; müşteri verisi kurulumunda maskeleme şart."""
    return anahtar_var and mod == "live" and (not musteri_verisi or maskeleme)


def _mod(ortam: Mapping[str, str]) -> str:
    deger = ortam.get(ORTAM_MOD, "").strip().lower() or "off"
    if deger not in enums.ASISTAN_MOD:
        log.warning("%s geçersiz (live|off bekleniyor); asistan kapalı (off)", ORTAM_MOD)
        return "off"
    return deger


def _paket() -> tuple[str | None, datetime | None]:
    """Ürün bilgi paketinin commit'i ve üretim zamanı (paket yoksa/bozuksa boş)."""
    from tp_core.features.assistant.tools.product import ProductToolError, UrunBilgisi

    try:
        manifest = UrunBilgisi().manifest()
    except ProductToolError:
        return None, None
    except OSError:
        return None, None
    commit = manifest.get("commit")
    commit = commit[:64] if isinstance(commit, str) and commit else None
    uretim: datetime | None = None
    ham = manifest.get("uretim")
    if isinstance(ham, str) and ham:
        try:
            uretim = datetime.fromisoformat(ham.replace("Z", "+00:00"))
        except ValueError:
            uretim = None
        if uretim is not None and uretim.tzinfo is None:
            uretim = None  # timestamptz'e saat dilimsiz değer yazılmaz
    return commit, uretim


def durum_hesapla(ortam: Mapping[str, str] | None = None) -> AsistanDurumu:
    """Ortamdan (ve bilgi paketinden) asistanın servis durumunu hesaplar; DB'ye dokunmaz."""
    from tp_core.gateway.config import GatewaySettings

    ortam = os.environ if ortam is None else ortam
    ayar = GatewaySettings()
    anahtar_var = bool(ayar.anthropic_api_key and ayar.anthropic_api_key.get_secret_value())
    mod = _mod(ortam)
    maskeleme = bool(ayar.pii_masking)
    musteri_verisi = _bayrak(ORTAM_MUSTERI_VERISI, False, ortam)
    commit, uretim = _paket()
    return AsistanDurumu(
        mod=mod,
        model_hazir=model_hazir_mi(
            anahtar_var=anahtar_var, mod=mod, musteri_verisi=musteri_verisi, maskeleme=maskeleme
        ),
        maskeleme=maskeleme,
        musteri_verisi=musteri_verisi,
        paket_commit=commit,
        paket_uretim=uretim,
    )


def durum_yaz(conn: Connection, durum: AsistanDurumu | None = None) -> AsistanDurumu:
    """`asistan_durum` tekil satırını yazar (yoksa ekler) ve kalp atışını DB saatine tazeler."""
    d = durum or durum_hesapla()
    conn.execute(
        text(
            "INSERT INTO asistan_durum (id, mod, model_hazir, maskeleme, musteri_verisi, "
            "paket_commit, paket_uretim, kalp_atisi) "
            "VALUES (1, :mod, :hazir, :maske, :musteri, :commit, :uretim, now()) "
            "ON CONFLICT (id) DO UPDATE SET mod = EXCLUDED.mod, "
            "model_hazir = EXCLUDED.model_hazir, maskeleme = EXCLUDED.maskeleme, "
            "musteri_verisi = EXCLUDED.musteri_verisi, paket_commit = EXCLUDED.paket_commit, "
            "paket_uretim = EXCLUDED.paket_uretim, kalp_atisi = EXCLUDED.kalp_atisi"
        ),
        {
            "mod": d.mod,
            "hazir": d.model_hazir,
            "maske": d.maskeleme,
            "musteri": d.musteri_verisi,
            "commit": d.paket_commit,
            "uretim": d.paket_uretim,
        },
    )
    return d


def kalp_atisi_yaz(engine: Engine) -> AsistanDurumu:
    """Zamanlayıcı iş parçacığının çağırdığı tek adım (kendi transaction'ı)."""
    with engine.begin() as conn:
        return durum_yaz(conn)


def model_hazir_oku(conn: Connection) -> bool:
    """İşleyicinin "canlı dala girilebilir mi" sorusu: satırdaki `model_hazir` (yoksa False)."""
    deger = conn.execute(text("SELECT model_hazir FROM asistan_durum WHERE id = 1")).scalar()
    return bool(deger)


# ------------------------------------------------------------------ mesaj durumu

_MESAJ = AsistanMesaj.__table__
# `sonuc_yaz`'ın yazabileceği alanlar (harcama alanları ayrı: `harcama_yaz`).
SONUC_ALANLARI: Final = frozenset(
    {"durum", "cevap", "kaynak", "amac", "hata_kodu", "ai_call_id", "tamamlanma"}
)
HARCAMA_ALANLARI: Final = frozenset({"maliyet_usd", "token_girdi", "token_cikti", "sure_ms"})
_SON_DURUMLAR: Final = frozenset({"done", "error", "iptal"})


def _olay(conn: Connection, mesaj_id: uuid.UUID, kullanici_id: uuid.UUID, durum: str) -> None:
    publish_tx(
        conn,
        EV_ANSWERED,
        {"mesaj_id": str(mesaj_id), "kullanici_id": str(kullanici_id), "durum": durum},
    )


def baslat(conn: Connection, mesaj_id: uuid.UUID) -> bool:
    """`pending → running`; mesaj iptal edildiyse/uzlaştırıldıysa False (iş hiçbir şey yapmaz)."""
    sonuc = conn.execute(
        update(_MESAJ)
        .where(_MESAJ.c.id == mesaj_id, _MESAJ.c.durum == "pending")
        .values(durum="running")
    )
    return sonuc.rowcount == 1


def sonuc_yaz(conn: Connection, mesaj_id: uuid.UUID, **alanlar: Any) -> bool:
    """İçerik/durum alanlarını yalnız mesaj hâlâ `running` iken yazar; yazıldıysa True.

    Son duruma (`done`/`error`) geçişte `tamamlanma` verilmemişse DB saati yazılır.
    """
    bilinmeyen = set(alanlar) - SONUC_ALANLARI
    if bilinmeyen:
        raise ValueError(f"sonuc_yaz alanı değil: {', '.join(sorted(bilinmeyen))}")
    degerler = dict(alanlar)
    if degerler.get("durum") in _SON_DURUMLAR and "tamamlanma" not in degerler:
        degerler["tamamlanma"] = func.now()
    if not degerler:
        return False
    sonuc = conn.execute(
        update(_MESAJ)
        .where(_MESAJ.c.id == mesaj_id, _MESAJ.c.durum == "running")
        .values(**degerler)
    )
    return sonuc.rowcount == 1


def harcama_yaz(
    conn: Connection,
    mesaj_id: uuid.UUID,
    *,
    maliyet_usd: Decimal | float | None = None,
    token_girdi: int | None = None,
    token_cikti: int | None = None,
    sure_ms: int | None = None,
) -> bool:
    """Maliyet/token/süre: mesaj `running` ya da `iptal` iken (iptal sonrası harcama kaybolmaz)."""
    degerler = {
        k: v
        for k, v in {
            "maliyet_usd": maliyet_usd,
            "token_girdi": token_girdi,
            "token_cikti": token_cikti,
            "sure_ms": sure_ms,
        }.items()
        if v is not None
    }
    if not degerler:
        return False
    sonuc = conn.execute(
        update(_MESAJ)
        .where(_MESAJ.c.id == mesaj_id, _MESAJ.c.durum.in_(("running", "iptal")))
        .values(**degerler)
    )
    return sonuc.rowcount == 1


def hata_yaz(conn: Connection, mesaj_id: uuid.UUID, hata_kodu: str) -> bool:
    """Bekleyen/koşan mesajı `error` yapar (yalnız sınıf kodu; ayrıntı yazılmaz) ve olayı yayar."""
    satir = conn.execute(
        update(_MESAJ)
        .where(_MESAJ.c.id == mesaj_id, _MESAJ.c.durum.in_(("pending", "running")))
        .values(durum="error", hata_kodu=hata_kodu, tamamlanma=func.now())
        .returning(_MESAJ.c.kullanici_id)
    ).first()
    if satir is None:
        return False
    _olay(conn, mesaj_id, satir.kullanici_id, "error")
    return True


def durdurulmali(conn: Connection, mesaj_id: uuid.UUID) -> bool:
    """`should_stop`: mesaj artık `running` değil (iptal, uzlaştırma, silinmiş satır)."""
    durum = conn.execute(
        text("SELECT durum FROM asistan_mesaj WHERE id = :i"), {"i": mesaj_id}
    ).scalar()
    return durum != "running"


def durdurma_kontrolu(engine: Engine, mesaj_id: uuid.UUID) -> Callable[[], bool]:
    """Geçide verilecek `should_stop` (her çağrı kısa bir okuma; kendi bağlantısı)."""

    def kontrol() -> bool:
        with engine.connect() as conn:
            return durdurulmali(conn, mesaj_id)

    return kontrol


def uzlastir(conn: Connection) -> list[uuid.UUID]:
    """İşi bitmiş ya da hiç olmayan `pending`/`running` asistan mesajlarını `error/zaman_asimi`
    yapar; kapanan mesaj kimliklerini döndürür.

    `UPDATE` satır kilidiyle yarışır: aynı anda `sonuc_yaz` ile `done` olan mesaj yeniden
    değerlendirilir ve atlanır (READ COMMITTED). Bitmemiş (`queued`/`running`/`retry`) işi olan
    mesaja dokunulmaz.
    """
    satirlar = conn.execute(
        text(
            "UPDATE asistan_mesaj m SET durum = 'error', hata_kodu = :kod, tamamlanma = now() "
            "WHERE m.rol = 'assistant' AND m.durum IN ('pending', 'running') AND ("
            " (m.job_id IS NULL AND m.olusturma < now() - make_interval(secs => :esik))"
            " OR (m.job_id IS NOT NULL AND NOT EXISTS ("
            "   SELECT 1 FROM job j WHERE j.id = m.job_id"
            "   AND j.durum IN ('queued', 'running', 'retry')))"
            ") RETURNING m.id, m.kullanici_id"
        ),
        {"kod": HATA_ZAMAN_ASIMI, "esik": ISSIZ_MESAJ_ESIGI_S},
    ).all()
    for satir in satirlar:
        _olay(conn, satir.id, satir.kullanici_id, "error")
    if satirlar:
        log.warning("asistan: %d mesaj işi bittiği hâlde açıktı → error/zaman_asimi", len(satirlar))
    return [s.id for s in satirlar]
