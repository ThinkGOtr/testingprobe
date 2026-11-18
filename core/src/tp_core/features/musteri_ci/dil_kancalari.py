"""Müşteri CI hattının dil şeridi kancaları (014 entegrasyonu; Ş3 Kotlin, Ş4 Swift).

Ş5 çekirdeği dilden bağımsızdır; test kimliği dönüşümü (`tp_results_ayristir(kimlik=…)`) ve
kurulum PR'ı iskeleti (`kurulum_plani(iskelet=…)`) dil eklentisindedir. Bu modül ikisini çiftten
çözer (yoksa None; çağıran kancasız davranır). Saf değildir: kök çözümü proje ayarını okur.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from tp_core.features.musteri_ci.kurulum import KurulumParametreleri

log = logging.getLogger(__name__)

# Kotlin kurulum iskeletinin kaynağı (demo ekran nesnesi kütüphanesi `altyapi/`, `ekranlar/`).
KOTLIN_ISKELET_AYARI = "TP_KOTLIN_ISKELET_KAYNAGI"
_KOTLIN_DEMO_KUTUPHANESI = "demo-app/mobile/android-test/java/com/antreklabs/bayisiparis/tp"


def _kok(platform: str, dil: str) -> str:
    """Dil kökü (`codegen.service.dil_koku`); ayar okunamazsa (ör. ayarsız birim testi) çatının
    varsayılanı."""
    try:
        from tp_core.features.codegen.service import dil_koku

        return dil_koku(platform, dil)
    except Exception:
        from tp_core.features.codegen import platform as platformlar

        log.warning("dil kökü çözülemedi (%s/%s); çatı varsayılanı kullanılıyor", platform, dil)
        cati = platformlar.cati_bul(platform, dil)
        return cati.kok_varsayilan if cati is not None else ""


def varsayilan_kimlik(platform: str, dil: str) -> Any | None:
    """Çiftin JUnit → script kimlik dönüşümü (Kotlin: `kimlik_donusturucu(kök)`); yoksa None."""
    if (platform, dil) == ("android", "kotlin"):
        from tp_core.features.codegen.diller import kotlin

        return kotlin.kimlik_donusturucu(_kok(platform, dil))
    return None


def kotlin_iskelet_kaynagi() -> Path | None:
    """Demo Kotlin kütüphanesinin paket dizini: `TP_KOTLIN_ISKELET_KAYNAGI` > depo kopyası
    (geliştirme); yoksa None (iskelet önerilmez, plan yine iş akışı eksiklerini gösterir)."""
    deger = os.environ.get(KOTLIN_ISKELET_AYARI, "").strip()
    if deger:
        yol = Path(deger)
        return yol if yol.is_dir() else None
    for ata in Path(__file__).resolve().parents:
        aday = ata / _KOTLIN_DEMO_KUTUPHANESI
        if aday.is_dir():
            return aday
    return None


def varsayilan_iskelet(p: KurulumParametreleri, rules: Path) -> dict[str, str] | None:
    """Kurulum PR'ının dil iskeleti (depo yolu → içerik); üretilemiyorsa None."""
    if (p.platform, p.dil) == ("android", "kotlin"):
        from tp_core.features.codegen.diller import kotlin

        kaynak = kotlin_iskelet_kaynagi()
        if kaynak is None or not p.test_paketi:
            return None
        try:
            return kotlin.kurulum_iskeleti(kaynak, _kok(p.platform, p.dil), p.test_paketi)
        except Exception:  # bozuk paket adı / okunamayan kaynak: iskelet önerilmez
            return None
    if (p.platform, p.dil) == ("ios", "swift"):
        from tp_core.features.codegen.diller import swift

        try:
            return swift.iskelet(_kok(p.platform, p.dil), rules)
        except OSError:
            return None
    return None
