"""Asistanın maskeleyicisi ve mesaj başına tek oturumu (AI-ASISTAN-PLANI §5.0).

İşleyici mesaj başına bir kez `oturum = maskeleyici().new_session()` açar ve aynı oturumu geçide
(`run_agent(..., masking_session=oturum)`), `DataTools(..., session=oturum)`'a ve yeni araçların
sarmalayıcısına (`tools.base.AracBaglami.oturum`) verir. Böylece yer tutucular
(`<<PII_EMAIL_1>>`) soru, geçmiş, bağlam ve tüm araç sonuçları boyunca tekildir; son çıktının
maskesi aynı oturumla açılır.

Yapılandırma geçidinkinin aynısıdır (`gateway/factory.py`): `TP_PII_MASKING` +
`rules/pii-allowlist.yaml`.
Geçit kurulmasa da (sözlük/şablon/kapalı kip) maskeleyici kurulur.
"""

from __future__ import annotations

from pathlib import Path

from tp_core.gateway.config import GatewaySettings, find_rules_dir
from tp_core.gateway.factory import load_pii_allowlist
from tp_core.gateway.masking import MaskingSession, PiiMasker


def maskeleyici(*, enabled: bool | None = None, rules_dir: Path | None = None) -> PiiMasker:
    """`PiiMasker(enabled=TP_PII_MASKING, allowlist=load_pii_allowlist(rules_dir))`."""
    if enabled is None:
        enabled = bool(GatewaySettings().pii_masking)
    return PiiMasker(enabled=enabled, allowlist=load_pii_allowlist(find_rules_dir(rules_dir)))


def mesaj_oturumu(masker: PiiMasker | None = None) -> MaskingSession:
    """Mesaj başına tek maskeleme oturumu."""
    return (masker or maskeleyici()).new_session()
