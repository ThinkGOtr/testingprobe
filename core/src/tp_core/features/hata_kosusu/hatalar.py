"""Ekilmiş hata koşusu hata sınıfları (ANALIZ §5; MIMARI-SOZLESME §5 `kod` sözleşmesi).

`kod` sınıf başına sabittir; anlamı `rules/assistant/hata-sozlugu.yaml`'dadır. Bu modül ağır
içe aktarma yapmaz (paket `__init__`'i servisi yükler; `karar_tablosu.hatalar` geriye uyum için
sınıfı tembel olarak buradan verir).
"""

from __future__ import annotations

from tp_core.workflow.service import WorkflowError


class HataKosusuSuruyor(WorkflowError):
    """Süren (queued | running) bir ekilmiş hata koşusu varken yenisi başlatılamaz."""

    status_code = 409
    kod = "hata_kosusu_suruyor"


__all__ = ["HataKosusuSuruyor"]
