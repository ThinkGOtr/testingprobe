"""Prompt paketlerinin canlı değerlendirme durumu (constitution X) — `rules/evaluations.yaml`.

Constitution X: "Prompt/kural değişikliği değerlendirme setini canlı modelle koşturmadan
birleştirilmez." Bu modül her prompt paketinin güncel sürümü için durum kaydını okur ve doğrular:

- `pending`   → "canlı değerlendirme bekliyor" (kullanıcıya görünür etiket),
- `evaluated` → tarihli canlı değerlendirme kaydı (`evaluation`: date, model, provider, results),
- `waived`    → sahibin onayladığı tarihli istisna
  (`waiver`: approved_by, approved_at, reason, until).

Kayıt sürümü prompt ön bilgisindeki `version`'dan farklıysa kayıt bayattır (`stale`); prompt
yükseltilip durum yazılmadan birleştirilemez. `--check` birleştirme kapısıdır: bekleyen veya bayat
kayıt varsa çıkış kodu 1. Bu modül istisna üretmez; istisna yalnızca sahip onayıyla elle yazılır.

    cd core && uv run python -m tp_core.gateway.evaluation            # durum tablosu
    cd core && uv run python -m tp_core.gateway.evaluation --check    # birleştirme kapısı
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tp_core.gateway.bundle import parse_prompt_file
from tp_core.gateway.errors import GatewayConfigError

EVALUATIONS_FILE = "evaluations.yaml"
STATUSES = ("pending", "evaluated", "waived")
PENDING_LABEL = "canlı değerlendirme bekliyor"
_LABELS = {
    "pending": PENDING_LABEL,
    "evaluated": "canlı değerlendirildi",
    "waived": "onaylı istisna (canlı değerlendirme yok)",
    "stale": "değerlendirme kaydı bayat (prompt sürümü değişti)",
    "missing": "değerlendirme kaydı yok",
}
_EVALUATION_FIELDS = ("date", "model", "provider", "results")
_WAIVER_FIELDS = ("approved_by", "approved_at", "reason", "until")


@dataclass(frozen=True)
class EvaluationStatus:
    bundle_id: str
    prompt_version: int
    recorded_version: int | None
    status: str  # pending | evaluated | waived | stale | missing
    detail: Mapping[str, Any] | None = None

    @property
    def label(self) -> str:
        return _LABELS[self.status]

    @property
    def mergeable(self) -> bool:
        """Constitution X kapısı: güncel sürüm için canlı değerlendirme veya onaylı istisna."""
        return self.status in ("evaluated", "waived")


def _is_date(value: Any) -> bool:
    if isinstance(value, dt.date):
        return True
    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _require(entry: Mapping[str, Any], key: str, fields: tuple[str, ...], where: str) -> dict:
    block = entry.get(key)
    if not isinstance(block, Mapping):
        raise GatewayConfigError(f"{where}: '{key}' bloğu zorunlu")
    for field in fields:
        value = block.get(field)
        if value in (None, "") or (isinstance(value, str) and not value.strip()):
            raise GatewayConfigError(f"{where}: '{key}.{field}' zorunlu")
    date_field = "date" if key == "evaluation" else "approved_at"
    if not _is_date(block[date_field]):
        raise GatewayConfigError(f"{where}: '{key}.{date_field}' YYYY-MM-DD olmalı")
    return dict(block)


def _validate_entry(name: str, entry: Any, path: Path) -> dict[str, Any]:
    where = f"{path}: {name}"
    if not isinstance(entry, Mapping):
        raise GatewayConfigError(f"{where}: kayıt bir eşleme olmalı")
    version = entry.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise GatewayConfigError(f"{where}: 'version' tamsayı olmalı")
    status = entry.get("status")
    if status not in STATUSES:
        raise GatewayConfigError(f"{where}: 'status' {STATUSES} içinden olmalı, {status!r} geldi")
    out = dict(entry)
    if status == "evaluated":
        out["evaluation"] = _require(entry, "evaluation", _EVALUATION_FIELDS, where)
    elif status == "waived":
        out["waiver"] = _require(entry, "waiver", _WAIVER_FIELDS, where)
    elif entry.get("evaluation") or entry.get("waiver"):
        raise GatewayConfigError(f"{where}: 'pending' kayıt evaluation/waiver taşıyamaz")
    return out


def load_evaluations(rules_dir: Path) -> dict[str, dict[str, Any]]:
    path = rules_dir / EVALUATIONS_FILE
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise GatewayConfigError(f"{path} bulunamadı (constitution X durum kaydı)") from None
    bundles = data.get("bundles")
    if not isinstance(bundles, Mapping):
        raise GatewayConfigError(f"{path}: 'bundles' eşlemesi zorunlu")
    return {str(name): _validate_entry(str(name), entry, path) for name, entry in bundles.items()}


def prompt_versions(rules_dir: Path) -> dict[str, int]:
    """rules/prompts/*.md → {ön bilgideki id: version} (`_guardrails` dahil)."""
    out: dict[str, int] = {}
    for path in sorted((rules_dir / "prompts").glob("*.md")):
        meta, _ = parse_prompt_file(path.read_text(encoding="utf-8"), path)
        out[str(meta["id"])] = int(meta["version"])
    if not out:
        raise GatewayConfigError(f"{rules_dir / 'prompts'}: prompt dosyası yok")
    return out


def evaluation_statuses(rules_dir: Path) -> dict[str, EvaluationStatus]:
    records = load_evaluations(rules_dir)
    out: dict[str, EvaluationStatus] = {}
    for bundle_id, version in prompt_versions(rules_dir).items():
        rec = records.get(bundle_id)
        if rec is None:
            out[bundle_id] = EvaluationStatus(bundle_id, version, None, "missing")
            continue
        status = rec["status"] if rec["version"] == version else "stale"
        detail = rec.get("evaluation") or rec.get("waiver")
        out[bundle_id] = EvaluationStatus(bundle_id, version, rec["version"], status, detail)
    unknown = sorted(set(records) - set(out))
    if unknown:
        raise GatewayConfigError(
            f"{rules_dir / EVALUATIONS_FILE}: prompt dosyası olmayan kayıt(lar): {unknown}"
        )
    return out


def evaluation_status(rules_dir: Path, bundle_id: str) -> EvaluationStatus:
    statuses = evaluation_statuses(rules_dir)
    try:
        return statuses[bundle_id]
    except KeyError:
        raise GatewayConfigError(f"bilinmeyen prompt paketi: {bundle_id!r}") from None


def blocking(rules_dir: Path) -> list[EvaluationStatus]:
    """Constitution X kapısını kapatan paketler (bekleyen, bayat veya kaydı olmayan)."""
    return [s for s in evaluation_statuses(rules_dir).values() if not s.mergeable]


def main(argv: list[str] | None = None) -> int:
    from tp_core.gateway.config import find_rules_dir

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rules-dir", type=Path, default=None)
    parser.add_argument(
        "--check", action="store_true", help="birleştirme kapısı: bekleyen kayıt varsa çıkış 1"
    )
    args = parser.parse_args(argv)
    rules_dir = args.rules_dir or find_rules_dir()
    try:
        statuses = evaluation_statuses(rules_dir)
    except GatewayConfigError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2
    for s in statuses.values():
        print(f"{s.bundle_id}@v{s.prompt_version}\t{s.status}\t{s.label}")
    if args.check:
        blocked = [s for s in statuses.values() if not s.mergeable]
        if blocked:
            names = ", ".join(f"{s.bundle_id}@v{s.prompt_version} ({s.label})" for s in blocked)
            print(
                f"Constitution X: canlı değerlendirme veya onaylı istisna yok: {names}",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
