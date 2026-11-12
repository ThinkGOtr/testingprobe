"""012 test kalite doğrulama hata sınıfları (ANALIZ §5; MIMARI-SOZLESME §5 `kod` sözleşmesi).

Tek ortak modül: karar tablosu, oracle, metamorfik ve hata koşusu şeritleri buradan içe aktarır.
`kod` sınıf başına sabittir; anlamları `rules/assistant/hata-sozlugu.yaml`'dadır (kural testi
`WorkflowError` alt sınıflarını bu sözlükle karşılaştırır).
"""

from __future__ import annotations

from collections.abc import Sequence

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


class OracleKayitDegisti(WorkflowError):
    """Kararla gelen `oracle_kayit_damgasi` güncel kontrol kaydının damgasına uymuyor: analistin
    gördüğü kayıt karar verilirken yeniden hesaplandı (review 2 g2 Y9)."""

    status_code = 409
    kod = "oracle_kayit_degisti"


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


class HataKosusuSuruyor(WorkflowError):
    """Süren (queued | running) bir ekilmiş hata koşusu varken yenisi başlatılamaz."""

    status_code = 409
    kod = "hata_kosusu_suruyor"


__all__ = [
    "HataKosusuSuruyor",
    "IliskiGecersiz",
    "KararTablosuGecersiz",
    "OracleBekleniyor",
    "OracleKayitDegisti",
    "OracleKontrolSiniri",
    "OracleKontrolsuz",
    "OracleUyumsuz",
]
