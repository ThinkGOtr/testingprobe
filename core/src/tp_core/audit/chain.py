"""Append-only denetim kaydı ve `prev_hash` zinciri (Constitution VIII, MIMARI-SOZLESME §4).

Her satır için ``hash = sha256(prev_hash + kanonik JSON({id, zaman, aktor, eylem, nesne, ozet}))``.
İlk satırın ``prev_hash`` değeri 64 sıfırdır. Ekleme bir Postgres advisory lock'u (işlem kapsamlı)
altında yapılır; böylece eşzamanlı yazıcılar zinciri çatallandıramaz (`prev_hash` ayrıca UNIQUE).
Kimlik `nextval` ile kilit altında alınır: zincir sırası = `id` sırası.

`append_audit(conn, ...)` çağıranın işlemine katılır (durum geçişi + denetim aynı işlemde);
`PgAuditLog` ise kendi işlemini açan `AuditLog` Protocol uygulamasıdır.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, Engine, text

from tp_core.audit.canonical import GENESIS_HASH, canonical_json, chain_hash, iso_utc

# pg_advisory_xact_lock anahtarı (rastgele seçilmiş sabit; yalnızca denetim zinciri için).
AUDIT_LOCK_KEY = 7_310_001

MAX_AKTOR = 200
MAX_EYLEM = 200


def _satir(
    id_: int, zaman: datetime, aktor: str, eylem: str, nesne: str | None, ozet: Any
) -> dict[str, Any]:
    return {
        "id": id_,
        "zaman": iso_utc(zaman),
        "aktor": aktor,
        "eylem": eylem,
        "nesne": nesne,
        "ozet": ozet,
    }


def _jsonb_normalize(conn: Connection, ozet: Mapping[str, Any] | None) -> Any:
    """Özeti Postgres jsonb'den geçirip geri okur: hash, saklanan değerle birebir aynı olur
    (ör. 1e20 → 100000000000000000000)."""
    if ozet is None:
        return None
    return conn.execute(text("SELECT CAST(:j AS jsonb)"), {"j": canonical_json(ozet)}).scalar_one()


def append_audit(
    conn: Connection,
    aktor: str,
    eylem: str,
    nesne: str | None = None,
    ozet: Mapping[str, Any] | None = None,
) -> int:
    """Zincire bir satır ekler ve `id` döndürür. Çağıranın işleminde çalışır; commit çağırana."""
    if not aktor or len(aktor) > MAX_AKTOR:
        raise ValueError("aktor boş olamaz ve 200 karakteri aşamaz")
    if not eylem or len(eylem) > MAX_EYLEM:
        raise ValueError("eylem boş olamaz ve 200 karakteri aşamaz")
    conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": AUDIT_LOCK_KEY})
    ozet_n = _jsonb_normalize(conn, ozet)
    prev = conn.execute(
        text("SELECT hash FROM audit_event ORDER BY id DESC LIMIT 1")
    ).scalar_one_or_none()
    prev_hash = prev or GENESIS_HASH
    id_ = conn.execute(
        text("SELECT nextval(pg_get_serial_sequence('audit_event', 'id'))")
    ).scalar_one()
    zaman = datetime.now(UTC)
    h = chain_hash(prev_hash, _satir(id_, zaman, aktor, eylem, nesne, ozet_n))
    conn.execute(
        text(
            "INSERT INTO audit_event (id, zaman, aktor, eylem, nesne, ozet, prev_hash, hash) "
            "VALUES (:id, :zaman, :aktor, :eylem, :nesne, CAST(:ozet AS jsonb), :prev, :hash)"
        ),
        {
            "id": id_,
            "zaman": zaman,
            "aktor": aktor,
            "eylem": eylem,
            "nesne": nesne,
            "ozet": None if ozet_n is None else json.dumps(ozet_n, ensure_ascii=False),
            "prev": prev_hash,
            "hash": h,
        },
    )
    return int(id_)


class PgAuditLog:
    """`ports.AuditLog` uygulaması: her `append` kendi işleminde."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(self, aktor: str, eylem: str, nesne: str | None, ozet: Mapping[str, Any]) -> int:
        with self._engine.begin() as conn:
            return append_audit(conn, aktor, eylem, nesne, ozet)


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    count: int
    tip_hash: str
    broken_at: int | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "count": self.count,
            "tip_hash": self.tip_hash,
            "broken_at": self.broken_at,
            "reason": self.reason,
        }


def verify_chain(conn: Connection, batch: int = 1000) -> ChainVerification:
    """Tüm zinciri `id` sırasıyla yeniden hesaplar. İlk tutarsızlıkta durur."""
    expected_prev = GENESIS_HASH
    count = 0
    son_id = 0
    while True:
        rows = conn.execute(
            text(
                "SELECT id, zaman, aktor, eylem, nesne, ozet, prev_hash, hash FROM audit_event "
                "WHERE id > :son ORDER BY id LIMIT :n"
            ),
            {"son": son_id, "n": batch},
        ).all()
        if not rows:
            break
        for r in rows:
            if r.hash is None or r.prev_hash is None:
                return ChainVerification(False, count, expected_prev, r.id, "hash alanı boş")
            if r.prev_hash != expected_prev:
                return ChainVerification(
                    False, count, expected_prev, r.id, "prev_hash önceki satırın hash'i değil"
                )
            hesap = chain_hash(
                r.prev_hash, _satir(r.id, r.zaman, r.aktor, r.eylem, r.nesne, r.ozet)
            )
            if hesap != r.hash:
                return ChainVerification(
                    False, count, expected_prev, r.id, "satır içeriği hash ile uyuşmuyor"
                )
            expected_prev = r.hash
            count += 1
            son_id = r.id
    return ChainVerification(True, count, expected_prev)


def chain_tip(conn: Connection) -> str:
    """Zincirin son hash'i (Jira yorumlarına ve PR açıklamalarına sabitlenir)."""
    tip = conn.execute(
        text("SELECT hash FROM audit_event ORDER BY id DESC LIMIT 1")
    ).scalar_one_or_none()
    return tip or GENESIS_HASH
