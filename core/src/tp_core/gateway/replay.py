"""Replay deposu (TEKNIK-TASARIM §8.8, constitution VIII/XI).

- Anahtar: sha256(kanonik {purpose, bundle_hash, replay_key alanları, input_hash}); rastgele
  UUID içermez, `input_hash` zaman damgası/UUID/snapshot ref'i normalize edilmiş girdiden.
- Dosya: rules/replay/<purpose>/<key>.json (birebir kayıt).
- Yükseltilmiş golden (`tp_core.gateway.promote`): elle hazırlanmış golden çıktısı birebir anahtarla
  yazılır (`provenance: golden_promoted`, `golden_sha256`); mod `replay` olur, asla `live` değil.
  Golden sonradan değişirse kayıt bayattır ve kullanılmaz (golden'a düşer → REPLAY-MISS).
- Iskalama sessiz geçmez: rules/replay/<purpose>/golden/<replay_key["name"]>.json bulunursa mod
  `replay_miss` olur (portalda REPLAY-MISS); o da yoksa `ReplayNotFound`.
- Golden adlandırma (`golden_name`): story düzeyi `<jira_key>` (ör. `TPD-1`), case düzeyi
  `<jira_key>-C<sira_no>` (ör. `TPD-1-C2`, verify_and_map), tutarlılık denetiminin 2. ve sonraki
  turları `<jira_key>-r2` (düzeltilmiş doküman). Çağıran `replay_key={"name": golden_name(...)}`
  verir.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from tp_core.gateway.canonical import canonical_json, sha256_hex
from tp_core.gateway.errors import GatewayConfigError, ReplayMiss, ReplayNotFound

ReplayMode = Literal["replay", "replay_miss"]
PROMOTED = "golden_promoted"
_GOLDEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_PURPOSE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def golden_name(jira_key: str, *, case_no: int | None = None, check_round: int = 1) -> str:
    """Adlandırılmış golden kaydın adı (yukarıdaki kural).

    >>> golden_name("TPD-1"), golden_name("TPD-1", case_no=2), golden_name("TPD-1", check_round=2)
    ('TPD-1', 'TPD-1-C2', 'TPD-1-r2')
    """
    if case_no is not None and check_round != 1:
        raise ValueError("case_no ve check_round birlikte verilemez")
    if case_no is not None:
        if case_no < 1:
            raise ValueError("case_no 1'den başlar")
        return f"{jira_key}-C{case_no}"
    if check_round < 1:
        raise ValueError("check_round 1'den başlar")
    # Replay'de 2. turun kaydı engelleyici bulgu içermez; 3. tura düşülmez. Yine de 3+ tur
    # (canlıda düzeltme reddedilirse) düzeltilmiş doküman kaydına düşer.
    return jira_key if check_round == 1 else f"{jira_key}-r2"


def golden_digest(golden: Mapping[str, Any]) -> str:
    """Golden'ın replay'e giren içeriğinin (çıktı + kayıtlı ajan adımları) özeti."""
    return sha256_hex(
        canonical_json({"output": golden.get("output"), "steps": golden.get("steps")})
    )


def replay_key(
    purpose: str, bundle_hash: str, key_fields: Mapping[str, Any], input_digest: str
) -> str:
    return sha256_hex(
        canonical_json(
            {
                "purpose": purpose,
                "bundle_hash": bundle_hash,
                "replay_key": dict(key_fields),
                "input_hash": input_digest,
            }
        )
    )


class ReplayStore:
    """`strict=True` (prova kipi, `TP_REPLAY_STRICT=1`): golden'a düşmek yerine `ReplayMiss`
    fırlatır; §13 prova listesi "REPLAY-MISS olmadan replay" bu kipte koşan demo yoluyla doğrulanır.
    """

    def __init__(self, root: Path, *, strict: bool = False) -> None:
        self.root = Path(root)
        self.strict = strict

    def _dir(self, purpose: str) -> Path:
        if not _PURPOSE_RE.match(purpose):
            raise GatewayConfigError(f"Geçersiz amaç adı: {purpose!r}")
        return self.root / purpose

    def exact_path(self, purpose: str, key: str) -> Path:
        return self._dir(purpose) / f"{key}.json"

    def golden_path(self, purpose: str, name: str) -> Path:
        if not _GOLDEN_RE.match(name) or ".." in name:
            raise GatewayConfigError(f"Geçersiz golden adı: {name!r}")
        return self._dir(purpose) / "golden" / f"{name}.json"

    def lookup(
        self, purpose: str, key: str, golden_name: str | None
    ) -> tuple[dict[str, Any], ReplayMode, Path]:
        exact = self.exact_path(purpose, key)
        if exact.is_file():
            record = _read(exact)
            if not self.is_stale(purpose, record):
                return record, "replay", exact
        if golden_name:
            golden = self.golden_path(purpose, golden_name)
            if golden.is_file():
                if self.strict:
                    raise ReplayMiss(purpose, key, golden_name)
                return _read(golden), "replay_miss", golden
        raise ReplayNotFound(purpose, key, golden_name)

    def is_stale(self, purpose: str, record: Mapping[str, Any]) -> bool:
        """Yükseltilmiş kayıt, kaynağı olan golden değiştiyse (veya silindiyse) bayattır."""
        if record.get("provenance") != PROMOTED:
            return False
        name = record.get("golden")
        if not isinstance(name, str):
            return True
        golden = self.golden_path(purpose, name)
        if not golden.is_file():
            return True
        return golden_digest(_read(golden)) != record.get("golden_sha256")

    def ensure_writable(self) -> None:
        """record modu için başlangıç kontrolü: dizin yazılamıyorsa hemen hata (ücretli canlı
        çağrının sonucu kaydedilemeden kaybolmasın; compose'da `./rules:/rules:ro`)."""
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".yazma-testi-"):
                pass
        except OSError as exc:
            raise GatewayConfigError(
                f"TP_MODEL_MODE=record ama replay dizini yazılamıyor: {self.root} ({exc}). "
                "Bağlamayı yazılabilir yapın (':ro' kaldırın) veya modu değiştirin."
            ) from exc
        if not os.access(self.root, os.W_OK):
            raise GatewayConfigError(
                f"TP_MODEL_MODE=record ama replay dizini salt okunur: {self.root}"
            )

    def save(self, purpose: str, key: str, record: Mapping[str, Any]) -> Path:
        path = self.exact_path(purpose, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**record, "key": key, "recorded_at": datetime.now(UTC).isoformat()}
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return path


def _read(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "output" not in data:
        raise GatewayConfigError(f"{path}: replay kaydında 'output' yok")
    return data
