"""Ekilmiş hata koşusu (012 F3; specs/012-test-kalite-dogrulama/ANALIZ.md §4.6).

Uçlar `/fault-runs…` (`api`), adım işi `hata_kosusu.calistir` (`jobs`, uzun şerit) ve tarama işi
`hata_kosusu.tarama`, katalog
`katalog.katalog()`. Kontrol Kulesi için `hata_yakalama_ozeti(session)` (§4.7 `hata_yakalama`).
"""

from tp_core.features.hata_kosusu.service import hata_yakalama_ozeti

__all__ = ["hata_yakalama_ozeti"]
