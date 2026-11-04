"""Asistan hız sınırı: `asistan_hiz` üzerinde sabit pencere sayacı (AI-ASISTAN-PLANI §9).

core-api'de bugün genel bir hız sınırlayıcı yok; asistan uçları ve worker'ın Jira aracı bu tek
mekanizmayı kullanır. Sayaç `INSERT … ON CONFLICT DO UPDATE SET sayi = sayi + 1 RETURNING sayi`
ile artar: çok süreçte (birden çok uvicorn/worker) atomiktir, okuma-yazma yarışı yoktur.

- Pencere başlangıcı veritabanı saatinden hesaplanır (`now()`): süreçler arası saat kayması
  pencereyi bölmez.
- `kullanici_id=None` global kovadır (ör. `jira_global`); tekillik NULLS NOT DISTINCT olduğundan
  global kova da tek satırda sayılır.
- Sayaç çağıranın işleminde (oturum ya da bağlantı) artar. Reddedilen istek (429) işlemi geri
  alırsa artış da geri alınır; sınır yine korunur çünkü kabul edilen her istek sayılmıştır. Öneri
  uçları sayacı ayrı, hemen commit edilen bağlantıda artırır (404/422 ile biten istek de sayılır).
- Saatlik soru sınırı bu tabloda değil, mesaj tablosundan sayılır (iptal/hata dahil; §9).
- 1 günden eski satırlar `hiz_temizle` ile silinir (saklama işi çağırır).

Kovalar (sabitler aşağıda): `oneri_liste` 60/dk ve `oneri_geri_bildirim` 30/dk (kullanıcı başı,
Şerit R), `jira_global` 30 HTTP isteği/dk (global, Şerit J; yeniden denemeler dahil her istek),
`sohbet_olustur` 30/dk (kullanıcı başı; yalnız satır büyümesine karşı, model maliyeti yok).
"""

from __future__ import annotations

import uuid
from typing import Final

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from tp_core.models.asistan import HIZ_UQ

KOVA_ONERI_LISTE: Final = "oneri_liste"
KOVA_ONERI_GERI_BILDIRIM: Final = "oneri_geri_bildirim"
KOVA_JIRA_GLOBAL: Final = "jira_global"
KOVA_SOHBET_OLUSTUR: Final = "sohbet_olustur"

# Kova → (sınır, pencere saniyesi). Çağıran isterse doğrudan `hiz_kontrol`'e kendi değerini verir.
VARSAYILAN_SINIRLAR: Final[dict[str, tuple[int, int]]] = {
    KOVA_ONERI_LISTE: (60, 60),
    KOVA_ONERI_GERI_BILDIRIM: (30, 60),
    KOVA_JIRA_GLOBAL: (30, 60),
    KOVA_SOHBET_OLUSTUR: (30, 60),
}

SAKLAMA_SAAT: Final = 24

_ARTIR = text(
    f"""
    INSERT INTO asistan_hiz (id, kullanici_id, kova, pencere_baslangic, sayi)
    VALUES (
        :id, :kullanici_id, :kova,
        to_timestamp(floor(extract(epoch FROM now()) / :pencere_s) * :pencere_s),
        1
    )
    ON CONFLICT ON CONSTRAINT {HIZ_UQ} DO UPDATE SET sayi = asistan_hiz.sayi + 1
    RETURNING sayi
    """
)


def hiz_kontrol(
    session: Session | Connection,
    kova: str,
    *,
    kullanici_id: uuid.UUID | None,
    sinir: int,
    pencere_s: int,
) -> bool:
    """Kovanın geçerli penceredeki sayacını bir artırır; sınır içindeyse True.

    `sinir`-inci istek kabul edilir, `sinir + 1`-inci reddedilir (ör. 60/dk → 61. istek False).
    """
    if not kova:
        raise ValueError("kova boş olamaz")
    if sinir < 1 or pencere_s < 1:
        raise ValueError("sinir ve pencere_s pozitif olmalı")
    sayi = session.execute(
        _ARTIR,
        {
            "id": uuid.uuid4(),
            "kullanici_id": kullanici_id,
            "kova": kova,
            "pencere_s": int(pencere_s),
        },
    ).scalar_one()
    return int(sayi) <= sinir


def kova_kontrol(
    session: Session | Connection, kova: str, *, kullanici_id: uuid.UUID | None
) -> bool:
    """`VARSAYILAN_SINIRLAR`'daki kova için `hiz_kontrol`."""
    sinir, pencere_s = VARSAYILAN_SINIRLAR[kova]
    return hiz_kontrol(session, kova, kullanici_id=kullanici_id, sinir=sinir, pencere_s=pencere_s)


def hiz_temizle(session: Session, *, saat: int = SAKLAMA_SAAT) -> int:
    """`saat`'ten eski pencereleri siler; silinen satır sayısı."""
    sonuc = session.execute(
        text(
            "DELETE FROM asistan_hiz WHERE pencere_baslangic < now() - make_interval(hours => :s)"
        ),
        {"s": int(saat)},
    )
    return int(sonuc.rowcount or 0)
