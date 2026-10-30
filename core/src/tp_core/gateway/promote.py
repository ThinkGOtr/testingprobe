"""Golden yükseltme: adlandırılmış golden'ı birebir replay kaydına çevirir.

Sorun: anahtarsız demoda her AI çıktısı adlandırılmış golden'a düşer (`replay_miss`, portalda
turuncu REPLAY-MISS rozeti) ve `TP_REPLAY_STRICT=1` (§13 provası "REPLAY-MISS olmadan replay") her
birinde hata verir; canlı anahtar olmadan `record` ile birebir kayıt üretilemez.

Çözüm: elle hazırlanmış golden çıktısı, geçidin o çağrı için arayacağı **birebir anahtarla**
yazılır. Kayıt dürüst etiketlidir: `provenance: "golden_promoted"`, kaynak golden adı ve özeti
(`golden_sha256`), "canlı model çıktısı değildir" notu. Geçit bu kaydı `replay` modunda döndürür
(asla `live`), `ai_call.ek.replay_kokeni = "golden_promoted"` yazar. Golden sonradan değişirse kayıt
bayatlar ve kullanılmaz (`ReplayStore.is_stale`).

Anahtar her zaman geçidin kendi hesabıyla üretilir; ayrı bir "girdi kurucu" kopyası yoktur:

1. **Girdiden (kütüphane):** `promote_call` / `promote_agent`; çağıranın gerçek mesajları, şeması
   ve araçlarıyla `Gateway.replay_key_for_call/agent` (call/run_agent ile aynı kod yolu).
2. **Prova koşusunun denetim kaydından (CLI):** demo bir kez `TP_REPLAY_STRICT=0` ile koşulur;
   geçit her `replay_miss` satırına hesapladığı birebir anahtarı (`ai_call.replay_anahtari`) ve
   golden çıktısını (`cikti`) yazar. Komut bu satırları okur, çıktıyı golden'larla eşleştirir ve
   birebir kayıtları yazar. Sonraki koşu `TP_REPLAY_STRICT=1` ile REPLAY-MISS'siz geçer.

       cd core && uv run python -m tp_core.gateway.promote \\
           --database-url "$TP_DATABASE_URL" [--workflow <uuid>] [--dry-run]

   (compose'da rules/ salt okunur bağlıdır; komut host'tan çalıştırılır, DB 127.0.0.1'den.)

Not: PII maskeleme açıkken yer tutucu numaraları iş akışı oturumuna bağlıdır; girdiden yükseltme
`workflow_id=None` (yeni oturum) varsayar. Demo maskeleme kapalı çalışır; açıkken denetim yolu
kullanılmalıdır (anahtar zaten gerçek oturumla hesaplanmıştır).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from tp_core.gateway.canonical import canonical_json
from tp_core.gateway.config import find_rules_dir
from tp_core.gateway.core import Gateway, ReplayKeyInfo
from tp_core.gateway.errors import GatewayConfigError
from tp_core.gateway.replay import PROMOTED, ReplayStore, golden_digest
from tp_core.ports import ModelMessage, ToolSpec

log = logging.getLogger(__name__)

PROMOTED_NOTE = (
    "Elle hazırlanmış golden kayıttan birebir anahtara yükseltildi (prova kipi). Canlı model "
    "çıktısı değildir; portalda REPLAY olarak görünür. Canlı kayıt için TP_MODEL_MODE=record."
)


def _load_golden(store: ReplayStore, purpose: str, name: str) -> dict[str, Any]:
    path = store.golden_path(purpose, name)
    if not path.is_file():
        raise GatewayConfigError(f"golden yok: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "output" not in data:
        raise GatewayConfigError(f"{path}: golden kaydında 'output' yok")
    return data


def write_promoted(
    store: ReplayStore,
    purpose: str,
    key: str,
    golden_name: str,
    golden: Mapping[str, Any],
    *,
    info: ReplayKeyInfo | None = None,
    bundle_hash: str | None = None,
) -> Path:
    record: dict[str, Any] = {
        "kind": golden.get("kind", "call"),
        "purpose": purpose,
        "provenance": PROMOTED,
        "golden": golden_name,
        "golden_sha256": golden_digest(golden),
        "note": PROMOTED_NOTE,
        "bundle_hash": info.bundle_hash if info else bundle_hash,
    }
    if info is not None:
        record.update(
            bundle=info.bundle_label,
            model=info.model,
            replay_key=info.key_fields,
            input_hash=info.input_hash,
        )
    record["output"] = golden["output"]
    if golden.get("steps") is not None:
        record["steps"] = golden["steps"]
    return store.save(purpose, key, record)


def _golden_name_of(key_fields: Mapping[str, Any]) -> str:
    name = key_fields.get("name")
    if not name:
        raise GatewayConfigError("replay_key 'name' (golden adı) olmadan yükseltme yapılamaz")
    return str(name)


def promote_call(
    gw: Gateway,
    purpose: str,
    bundle: str,
    messages: Sequence[ModelMessage],
    schema: dict[str, Any],
    *,
    replay_key: Mapping[str, Any],
    workflow_id: UUID | None = None,
) -> Path:
    """`gw.call(...)` aynı argümanlarla birebir kaydı bulacak şekilde golden'ı yükseltir."""
    name = _golden_name_of(replay_key)
    golden = _load_golden(gw.replay_store, purpose, name)
    info = gw.replay_key_for_call(
        purpose, bundle, messages, schema, replay_key=replay_key, workflow_id=workflow_id
    )
    return write_promoted(gw.replay_store, purpose, info.key, name, golden, info=info)


def promote_agent(
    gw: Gateway,
    purpose: str,
    bundle: str,
    messages: Sequence[ModelMessage],
    tools: Sequence[ToolSpec],
    output_schema: dict[str, Any],
    *,
    replay_key: Mapping[str, Any],
    workflow_id: UUID | None = None,
) -> Path:
    """`gw.run_agent(...)` aynı argümanlarla birebir kaydı bulacak şekilde golden'ı yükseltir."""
    name = _golden_name_of(replay_key)
    golden = _load_golden(gw.replay_store, purpose, name)
    info = gw.replay_key_for_agent(
        purpose,
        bundle,
        messages,
        tools,
        output_schema,
        replay_key=replay_key,
        workflow_id=workflow_id,
    )
    return write_promoted(gw.replay_store, purpose, info.key, name, golden, info=info)


# ------------------------------------------------------------------ denetim kaydından


@dataclass(frozen=True)
class PromoteOutcome:
    purpose: str
    key: str
    golden: str | None
    path: Path | None
    reason: str  # "yazıldı" | "zaten var" | "deneme" | eşleşmeme gerekçesi


def promote_from_rows(
    store: ReplayStore, rows: Iterable[Mapping[str, Any]], *, dry_run: bool = False
) -> list[PromoteOutcome]:
    """`ai_call` satırlarından (`amac`, `mod`, `replay_anahtari`, `cikti`, `bundle_hash`) yükseltir.

    Yalnızca `mod = 'replay_miss'` satırları işlenir. Çıktı, amacın golden'larından birinin
    çıktısıyla kanonik olarak birebir eşleşmelidir; eşleşme yoksa veya birden fazlaysa yazılmaz.
    """
    outcomes: list[PromoteOutcome] = []
    seen: set[tuple[str, str]] = set()
    by_purpose: dict[str, dict[str, list[tuple[str, dict[str, Any]]]]] = {}
    for row in rows:
        if row.get("mod") != "replay_miss":
            continue
        purpose, key = str(row["amac"]), row.get("replay_anahtari")
        if not key or (purpose, key) in seen:
            continue
        seen.add((purpose, key))
        index = by_purpose.get(purpose)
        if index is None:
            index = by_purpose[purpose] = _golden_index(store, purpose)
        matches = index.get(canonical_json(row.get("cikti")), [])
        if len(matches) != 1:
            why = "golden eşleşmesi yok" if not matches else "birden fazla golden eşleşti"
            outcomes.append(PromoteOutcome(purpose, key, None, None, why))
            continue
        name, golden = matches[0]
        existing = store.exact_path(purpose, key)
        if existing.is_file():
            outcomes.append(PromoteOutcome(purpose, key, name, existing, "zaten var"))
            continue
        if dry_run:
            outcomes.append(PromoteOutcome(purpose, key, name, existing, "deneme"))
            continue
        path = write_promoted(store, purpose, key, name, golden, bundle_hash=row.get("bundle_hash"))
        outcomes.append(PromoteOutcome(purpose, key, name, path, "yazıldı"))
    return outcomes


def _golden_index(store: ReplayStore, purpose: str) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    index: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    folder = store.root / purpose / "golden"
    for path in sorted(folder.glob("*.json")):
        golden = json.loads(path.read_text(encoding="utf-8"))
        index.setdefault(canonical_json(golden.get("output")), []).append((path.stem, golden))
    return index


def stale_promotions(store: ReplayStore) -> list[Path]:
    """Kaynağı değişmiş/silinmiş yükseltilmiş kayıtlar (geçit bunları kullanmaz)."""
    out = []
    for path in sorted(store.root.glob("*/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("provenance") == PROMOTED and store.is_stale(path.parent.name, record):
            out.append(path)
    return out


_MISS_SQL = (
    "SELECT amac, mod, replay_anahtari, cikti, bundle_hash FROM ai_call "
    "WHERE mod = 'replay_miss'{where} ORDER BY olusturma, id"
)


def fetch_replay_misses(engine: Any, workflow_id: UUID | None = None) -> list[dict[str, Any]]:
    from sqlalchemy import text

    sql = _MISS_SQL.format(where=" AND workflow_id = :wf" if workflow_id else "")
    params = {"wf": workflow_id} if workflow_id else {}
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql), params)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tp_core.gateway.promote",
        description=(
            "Prova koşusundaki REPLAY-MISS çağrılarının golden'larını birebir replay kaydına "
            "yükseltir (provenance: golden_promoted; mod replay, asla live)."
        ),
    )
    parser.add_argument("--database-url", default=os.environ.get("TP_DATABASE_URL"))
    parser.add_argument("--rules", default=None, help="rules/ dizini (varsayılan: bulunur)")
    parser.add_argument("--workflow", type=UUID, default=None, help="yalnızca bu iş akışı")
    parser.add_argument("--dry-run", action="store_true", help="yazmadan listele")
    parser.add_argument("--check-stale", action="store_true", help="bayat kayıtları listele")
    args = parser.parse_args(argv)

    store = ReplayStore(find_rules_dir(args.rules) / "replay")
    if args.check_stale:
        stale = stale_promotions(store)
        for path in stale:
            print(f"BAYAT  {path}")
        return 1 if stale else 0
    if not args.database_url:
        parser.error("--database-url veya TP_DATABASE_URL gerekli")
    from sqlalchemy import create_engine

    engine = create_engine(args.database_url)
    try:
        outcomes = promote_from_rows(
            store, fetch_replay_misses(engine, args.workflow), dry_run=args.dry_run
        )
    finally:
        engine.dispose()
    for o in outcomes:
        print(f"{o.reason:<28} {o.purpose:<20} {o.golden or '-':<12} {o.key[:16]}")
    failed = [o for o in outcomes if o.golden is None]
    print(f"toplam {len(outcomes)}, eşleşmeyen {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
