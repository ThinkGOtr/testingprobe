"""012 test kalite doğrulama hata sınıfları (ANALIZ §5; MIMARI-SOZLESME §5 `kod` sözleşmesi).

Ortak modül: karar tablosu, oracle ve metamorfik şeritleri buradan içe aktarır. Hata koşusu hatası
(`HataKosusuSuruyor`) kendi özelliğindedir (`hata_kosusu.hatalar`); burada geriye uyum için tembel
olarak verilir.
`kod` sınıf başına sabittir; anlamları `rules/assistant/hata-sozlugu.yaml`'dadır (kural testi
`WorkflowError` alt sınıflarını bu sözlükle karşılaştırır).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tp_core.workflow.service import WorkflowError


def _ayrintili(mesaj: str, hatalar: Sequence[str]) -> str:
    """API yanıtı `str(hata)`'yı taşır; ayrıntılar metne eklenir (InvalidCaseContent gibi)."""
    return f"{mesaj} — {'; '.join(hatalar)}" if hatalar else mesaj


class OracleUyumsuz(WorkflowError):
    """Yüksek riskli case'in beklenen değeri onaylı karar tablosuyla uyuşmuyor, istisna yok (K3)."""

    status_code = 422
    kod = "oracle_uyumsuz"


class OracleBekleniyor(WorkflowError):
    """Yüksek riskli, tablo kapsamındaki case için kontrol henüz bitmedi (V3)."""

    status_code = 409
    kod = "oracle_bekleniyor"


class OracleKontrolsuz(WorkflowError):
    """Yüksek riskli, tablo kapsamındaki case'in beklenen değerleri kontrol edilemedi; gerekçe
    (tür `kontrolsuz`) olmadan onaylanamaz (review 1 K10)."""

    status_code = 422
    kod = "oracle_kontrolsuz"


class OracleKontrolSiniri(WorkflowError):
    """Aynı case için kısa sürede çok fazla karar tablosu kontrolü istendi (review 1 güv. 10)."""

    status_code = 429
    kod = "oracle_kontrol_siniri"


class KararTablosuGecersiz(WorkflowError):
    """Karar tablosu içeriği şemaya ya da ifade diline uymuyor; `hatalar` ayrıntıları taşır."""

    status_code = 422
    kod = "karar_tablosu_gecersiz"

    def __init__(self, mesaj: str, hatalar: Sequence[str] = ()) -> None:
        super().__init__(_ayrintili(mesaj, hatalar))
        self.hatalar = list(hatalar)


class IliskiGecersiz(WorkflowError):
    """Metamorfik ilişki içeriği geçersiz ya da ilişki bu durumda uygulanamaz; `hatalar` taşır."""

    status_code = 422
    kod = "iliski_gecersiz"

    def __init__(self, mesaj: str, hatalar: Sequence[str] = ()) -> None:
        super().__init__(_ayrintili(mesaj, hatalar))
        self.hatalar = list(hatalar)


def __getattr__(ad: str) -> Any:
    """Geriye uyum: `HataKosusuSuruyor` `hata_kosusu.hatalar`'a taşındı (döngüsel içe aktarma
    olmasın diye tembel)."""
    if ad == "HataKosusuSuruyor":
        from tp_core.features.hata_kosusu.hatalar import HataKosusuSuruyor

        return HataKosusuSuruyor
    raise AttributeError(f"module {__name__!r} has no attribute {ad!r}")


__all__ = [
    "HataKosusuSuruyor",  # noqa: F822  (tembel; modül __getattr__)
    "IliskiGecersiz",
    "KararTablosuGecersiz",
    "OracleBekleniyor",
    "OracleKontrolSiniri",
    "OracleKontrolsuz",
    "OracleUyumsuz",
]
