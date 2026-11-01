"""Ürün yorumlarında rol bazlı @bahsetme (yalnızca bildirim).

Roller ``.env``'deki ``JIRA_HESAP_<ROL>`` anahtarlarıyla Jira accountId'lerine eşlenir; boş anahtar
= o rol için bahsetme yok. Bahsetme yetki vermez ve hiçbir kapıyı açmaz (anayasa I): PO onayı
yalnızca PO'nun kendi koyduğu ``tp-po-approved`` etiketiyle sayılır; ürün o etiketi asla eklemez.

Yorum kuralı (``RestJira.add_comment``/``add_comment_adf``): her ürün yorumu
``🤖 AI Testing Probe:`` imiyle başlar, bahsetmeler aynı satırdadır. Idempotency işaretleri
(``Kayıt: …``, ``tp-<uuid>``, hash satırları) gövdede aynen kalır; im yalnızca başa eklenir.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from tp_core.integrations.jira_adf import unique_mentions

Rol = Literal["analist", "po", "muhendis", "testci"]
ROLLER: tuple[Rol, ...] = ("analist", "po", "muhendis", "testci")

# Yorum türü → bahsedilen roller (tek kaynak; dokümantasyon: docs/GERCEK-SISTEMLER.md §2.7).
PO_SORU: tuple[Rol, ...] = ("po", "analist")  # PO soru yorumu (ön inceleme, son hal)
PO_ETIKET_KALDIRILDI: tuple[Rol, ...] = ("po",)  # bayat/erken onay etiketi kaldırıldı
DOKUMAN_DUZELTME: tuple[Rol, ...] = ("po",)  # onaylı düzeltme Jira'ya yazıldı → yeniden teyit
YAYIN: tuple[Rol, ...] = ("testci",)  # onaylı case'ler Jira/Xray'e yayınlandı
BUG: tuple[Rol, ...] = ("muhendis", "testci")  # mevcut Bug'a bağlandı / yeni Bug açıldı


def role_mentions(roles: Sequence[str], settings: Any = None) -> list[str]:
    """Rollerin accountId'leri (boş/geçersiz atlanır, aynı kişi bir kez)."""
    if settings is None:
        from tp_core.integrations.jira import get_jira_settings

        settings = get_jira_settings()
    return unique_mentions([settings.role_account(r) for r in roles if r in ROLLER])


def post_comment(jira: Any, key: str, body: str, roles: Sequence[str] = ()) -> str:
    """Düz metin ürün yorumu + rol bahsetmeleri.

    Bahsetme yoksa ``add_comment(key, body)`` aynen çağrılır (``JiraPort`` sözleşmesi; sahte
    istemciler bozulmaz). İm ``RestJira`` tarafından eklenir.
    """
    ids = role_mentions(roles)
    if ids:
        return str(jira.add_comment(key, body, mentions=ids))
    return str(jira.add_comment(key, body))
