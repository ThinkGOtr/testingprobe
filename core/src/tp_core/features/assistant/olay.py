"""Asistan güvenlik olayları ve dondurma (specs/013 §6.1–6.2; K4, K11).

- `olay_yaz`: `asistan_guvenlik_olay` satırı; `ciddi` türden türetilir (`enums.ASISTAN_CIDDI_OLAY`).
  `ayrinti` yalnız kimlik/sayı taşır: anahtarlar `IZINLI_AYRINTI`'dadır, değerler kısa kimlik
  dizgesi, sayı ya da bunların listesidir. Soru metni, sır değeri ya da eşleşen parça yazılamaz
  (izinsiz anahtar / uzun metin `ValueError`).
- `ardisik_ciddi`: kullanıcının son **kabul edilen** sorusundan (`asistan_mesaj`, `rol='user'`,
  `tetik='kullanici'`) sonraki ciddi olay sayısı ve en yenisinin zamanı. Kabul edilen soru sayacı
  sıfırlar; niyet sinyalleri ve `kisisel_veri` sayılmaz (ciddi değil).
- `dondurma_kalan_s`: sayım ≥ `DONDURMA_ESIK` ve son ciddi olay `DONDURMA_SURE_S` içindeyse kalan
  saniye (≥ 1), değilse None. Saat veritabanından (`now()`) verilir.
- `dondurma_baslat`: dondurmanın ilk reddinde bir kez `donduruldu` olayı ve `audit_event`
  `asistan.supheli` satırı (aktör kullanıcı; ayrıntıda yalnız sayı). Kullanıcı başı advisory
  kilit altında: eşzamanlı iki ret çift kayıt yazmaz.

Çağıranlar olayı ayrı, hemen commit edilen bağlantıda yazar (422/429 isteği geri alır).
"""

from __future__ import annotations

import json
import math
import re
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from sqlalchemy import Connection, text

from tp_core.audit.chain import append_audit
from tp_core.features.assistant.budget import DONDURMA_ESIK, DONDURMA_SURE_S
from tp_core.models import enums

TUR_SIR: Final = "sir_icerik"
TUR_KISISEL: Final = "kisisel_veri"
TUR_KANARYA: Final = "kanarya"
TUR_SIZINTI: Final = "istem_sizintisi"
TUR_SINYAL: Final = "sinyal"
TUR_DONDURULDU: Final = "donduruldu"

DENETIM_EYLEMI: Final = "asistan.supheli"
# `advisory lock` ad alanı (budget.KILIT_NS ve jobs ad alanlarıyla çakışmaz).
KILIT_NS: Final = 7_310_021

# `ayrinti` sözlüğünde izin verilen anahtarlar (değer yazılmasın diye kapalı liste).
IZINLI_AYRINTI: Final = frozenset({"desen", "desenler", "sinyaller", "sayi", "kaynak", "alan"})
_KIMLIK: Final = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")
LISTE_AZAMI: Final = 20


def _guvenli_deger(deger: Any) -> bool:
    if isinstance(deger, int):  # bool dahil
        return True
    if isinstance(deger, str):
        return bool(_KIMLIK.match(deger))
    if isinstance(deger, list | tuple):
        return len(deger) <= LISTE_AZAMI and all(
            isinstance(d, str) and _KIMLIK.match(d) for d in deger
        )
    return False


def ayrinti_dogrula(ayrinti: Mapping[str, Any] | None) -> dict[str, Any]:
    """`ayrinti`yı denetler: izinli anahtar + kimlik/sayı değerleri; aksi `ValueError`."""
    out: dict[str, Any] = {}
    for anahtar, deger in (ayrinti or {}).items():
        if anahtar not in IZINLI_AYRINTI or not _guvenli_deger(deger):
            raise ValueError(f"güvenlik olayı ayrıntısında izinsiz alan: {anahtar}")
        out[anahtar] = list(deger) if isinstance(deger, list | tuple) else deger
    return out


def ciddi_mi(tur: str) -> bool:
    return tur in enums.ASISTAN_CIDDI_OLAY


def olay_yaz(
    conn: Connection,
    kullanici_id: uuid.UUID,
    tur: str,
    *,
    mesaj_id: uuid.UUID | None = None,
    ayrinti: Mapping[str, Any] | None = None,
) -> uuid.UUID:
    """Bir güvenlik olayı ekler (çağıranın işleminde); olay kimliği."""
    if tur not in enums.ASISTAN_OLAY_TUR:
        raise ValueError(f"bilinmeyen güvenlik olayı türü: {tur}")
    olay_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO asistan_guvenlik_olay (id, kullanici_id, mesaj_id, tur, ciddi, ayrinti) "
            "VALUES (:i, :k, :m, :t, :c, CAST(:a AS jsonb))"
        ),
        {
            "i": olay_id,
            "k": kullanici_id,
            "m": mesaj_id,
            "t": tur,
            "c": ciddi_mi(tur),
            "a": json.dumps(ayrinti_dogrula(ayrinti)),
        },
    )
    return olay_id


_ARDISIK = text(
    """
    SELECT count(*), max(o.zaman) FROM asistan_guvenlik_olay o
    WHERE o.kullanici_id = :k AND o.ciddi
      AND o.zaman > COALESCE(
            (SELECT max(m.olusturma) FROM asistan_mesaj m
             WHERE m.kullanici_id = :k AND m.rol = 'user' AND m.tetik = 'kullanici'
               -- K11: yalnız TEMİZ biten soru sıfırlar. Cevabı (ya da onun "Daha ayrıntılı"
               -- çocuğu; bir sonraki kullanıcı sorusuna kadarki asistan mesajları) kanarya /
               -- istem sızıntısı olayı almış soru sıfırlama noktası değildir; yoksa her
               -- sızıntıyı izleyen soru sayacı sıfırlar ve sızıntılar eşiğe hiç ulaşmazdı.
               AND NOT EXISTS (
                 SELECT 1 FROM asistan_guvenlik_olay so
                 JOIN asistan_mesaj a ON a.id = so.mesaj_id
                 WHERE so.ciddi AND a.sohbet_id = m.sohbet_id AND a.sira > m.sira
                   AND NOT EXISTS (
                     SELECT 1 FROM asistan_mesaj q2
                     WHERE q2.sohbet_id = m.sohbet_id AND q2.rol = 'user'
                       AND q2.sira > m.sira AND q2.sira < a.sira))),
            '-infinity'::timestamptz)
    """
)


def ardisik_ciddi(conn: Connection, kullanici_id: uuid.UUID) -> tuple[int, datetime | None]:
    """Son kabul edilen sorudan sonraki ciddi olay sayısı ve en yeni olayın zamanı."""
    sayi, son = conn.execute(_ARDISIK, {"k": kullanici_id}).one()
    return int(sayi or 0), son


def dondurma_kalan_s(conn: Connection, kullanici_id: uuid.UUID, simdi: datetime) -> int | None:
    """Dondurma sürüyorsa kalan saniye (≥ 1), sürmüyorsa None."""
    sayi, son = ardisik_ciddi(conn, kullanici_id)
    if sayi < DONDURMA_ESIK or son is None:
        return None
    kalan = DONDURMA_SURE_S - (simdi - son).total_seconds()
    if kalan <= 0:
        return None
    return max(1, math.ceil(kalan))


def dondurma_baslat(conn: Connection, kullanici_id: uuid.UUID, aktor: str) -> bool:
    """Bu dondurmanın ilk reddiyse `donduruldu` olayı + `asistan.supheli` denetimi yazar (True).

    Dondurmanın başlangıcı son ciddi olaydır; ondan sonra `donduruldu` olayı varsa yazılmaz."""
    conn.execute(
        text("SELECT pg_advisory_xact_lock(:ns, hashtext(:k))"),
        {"ns": KILIT_NS, "k": str(kullanici_id)},
    )
    sayi, son = ardisik_ciddi(conn, kullanici_id)
    if sayi < DONDURMA_ESIK or son is None:
        return False
    var = conn.execute(
        text(
            "SELECT 1 FROM asistan_guvenlik_olay WHERE kullanici_id = :k AND tur = :t "
            "AND zaman >= :s LIMIT 1"
        ),
        {"k": kullanici_id, "t": TUR_DONDURULDU, "s": son},
    ).first()
    if var is not None:
        return False
    olay_yaz(conn, kullanici_id, TUR_DONDURULDU, ayrinti={"sayi": sayi})
    append_audit(
        conn,
        aktor,
        DENETIM_EYLEMI,
        f"app_user:{kullanici_id}",
        {"ardisik_ciddi": sayi, "sure_s": DONDURMA_SURE_S},
    )
    return True
