"""Replay deposu (TEKNIK-TASARIM §8.8, constitution VIII/XI).

- Anahtar: sha256(kanonik {purpose, bundle_hash, replay_key alanları, input_hash}); rastgele
  UUID içermez, `input_hash` zaman damgası/UUID/snapshot ref'i normalize edilmiş girdiden.
- Dosya: rules/replay/<purpose>/<key>.json (birebir kayıt).
- Yükseltilmiş golden (`tp_core.gateway.promote`): elle hazırlanmış golden çıktısı birebir anahtarla
  yazılır (`provenance: golden_promoted`, `golden_sha256`); mod `replay` olur, asla `live` değil.
  Golden sonradan değişirse kayıt bayattır ve kullanılmaz (golden'a düşer → REPLAY-MISS).
- Golden eşleşmesi (`tp_core.gateway.matching`): golden `input_match` ile hazırlandığı girdiyi
  beyan eder; gerçek girdi beyana uyuyorsa mod `replay` (köken `golden_matched`). Senaryodaki demo
  yolu böylece REPLAY-MISS'siz koşar; story değiştiyse eşleşme bozulur ve dürüstçe REPLAY-MISS olur.
- Iskalama sessiz geçmez: rules/replay/<purpose>/golden/<replay_key["name"]>.json bulunursa mod
  `replay_miss` olur (portalda REPLAY-MISS); o da yoksa `ReplayNotFound`.
- Nötr REPLAY-MISS yedeği (`rules/replay/<amaç>/on_miss.json`): golden girdi beyanı (`input_match`)
  taşıyor ve gerçek girdi buna UYMUYORSA golden başka bir dokümanın cevabıdır; o amaç için
  `on_miss.json` varsa golden çıktısı yerine bu nötr çıktı döner (köken `miss_neutral`). Ör.
  ön incelemede başka gereksinimin soruları (olmayan AC'lere atıflar) gösterilmez. Beyansız
  golden'lar (senaryo adları: triage, bug_draft, dup_rank) eskisi gibi golden çıktısına düşer.
- Çıktı kökeni (`output_origin`): golden'lar elle hazırlanmıştır; canlı modelle kaydedilmiş bir
  çıktının `recording` üst verisi (model, kayıt zamanı, süre, token) vardır. Kayıt üst verisi
  olmayan çıktı `ai_call.model = HAND_PREPARED_MODEL` ("golden-elle") ile yazılır, model adı
  taşımaz (constitution VIII/X: hazırlanmış örnek, model kaydı gibi sunulmaz).
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
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from tp_core.gateway.canonical import canonical_json, normalize, sha256_hex
from tp_core.gateway.errors import GatewayConfigError, ReplayMiss, ReplayNotFound
from tp_core.gateway.matching import MATCHED, input_mismatches

ReplayMode = Literal["replay", "replay_miss"]
PROMOTED = "golden_promoted"
MISS_NEUTRAL = "miss_neutral"
MISS_FILE = "on_miss.json"
# Kayıt üst verisi olmayan (elle hazırlanmış) replay çıktısının `ai_call.model` değeri.
HAND_PREPARED_MODEL = "golden-elle"
# `ai_call.ek.cikti_kokeni`: çıktının gerçekte nereden geldiği.
ORIGIN_MODEL_RECORDING = "model_kaydi"
ORIGIN_HAND_PREPARED = "elle_hazirlanmis"
ORIGIN_NEUTRAL = "notr_yedek"
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
    """Birebir replay anahtarı. `key_fields` de normalize edilir (çağıran yanlışlıkla zaman damgası
    veya UUID koysa da anahtar koşudan koşuya değişmez)."""
    return sha256_hex(
        canonical_json(
            {
                "purpose": purpose,
                "bundle_hash": bundle_hash,
                "replay_key": normalize(dict(key_fields)),
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
        self,
        purpose: str,
        key: str,
        golden_name: str | None,
        messages: Sequence[Any] | None = None,
    ) -> tuple[dict[str, Any], ReplayMode, Path]:
        """Birebir kayıt → eşleşen golden (`replay`) → eşleşmeyen golden (`replay_miss`).

        Eşleşen golden'ın döndürülen kopyasında `provenance = "golden_matched"`; eşleşmeyen
        golden'da `_mismatch` (neden listesi, `ai_call.ek.replay_eslesme`) bulunur. Golden girdi
        beyanı taşıyıp girdiye uymuyorsa ve amacın nötr yedeği (`on_miss.json`) varsa onun çıktısı
        döner (`provenance = "miss_neutral"`, adım yok, dönen yol nötr yedeğin yolu).
        """
        exact = self.exact_path(purpose, key)
        if exact.is_file():
            record = _read(exact)
            if not self.is_stale(purpose, record):
                return record, "replay", exact
        if golden_name:
            golden = self.golden_path(purpose, golden_name)
            if golden.is_file():
                record = _read(golden)
                reasons = self.golden_mismatches(record, messages)
                if not reasons:
                    return {**record, "provenance": MATCHED}, "replay", golden
                if self.strict:
                    raise ReplayMiss(purpose, key, golden_name)
                neutral = self.miss_path(purpose)
                if "input_match" in record and neutral.is_file():
                    fallback = _read(neutral)
                    return (
                        {
                            "kind": record.get("kind"),
                            "purpose": purpose,
                            "golden": golden_name,
                            "provenance": MISS_NEUTRAL,
                            "output": fallback["output"],
                            "_mismatch": reasons,
                        },
                        "replay_miss",
                        neutral,
                    )
                return {**record, "_mismatch": reasons}, "replay_miss", golden
        raise ReplayNotFound(purpose, key, golden_name)

    def miss_path(self, purpose: str) -> Path:
        """Amacın nötr REPLAY-MISS yedeği (yoksa eşleşmeyen golden çıktısı kullanılır)."""
        return self._dir(purpose) / MISS_FILE

    def neutral_output(self, purpose: str) -> Any | None:
        path = self.miss_path(purpose)
        return _read(path)["output"] if path.is_file() else None

    @staticmethod
    def golden_mismatches(record: Mapping[str, Any], messages: Sequence[Any] | None) -> list[str]:
        """Golden'ın `input_match` beyanına göre uyuşmazlıklar (boş = eşleşir)."""
        spec = record.get("input_match")
        if not isinstance(spec, Mapping):
            return ["golden girdi beyanı (input_match) içermiyor"]
        if messages is None:
            return ["girdi verilmedi"]
        return input_mismatches(spec, messages)

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


def output_origin(record: Mapping[str, Any]) -> tuple[str, str | None]:
    """(cikti_kokeni, kayıtlı model). Model adı yalnızca kayıt üst verisi olan çıktıda verilir.

    - nötr REPLAY-MISS yedeği → (`notr_yedek`, None)
    - `recording.model` taşıyan kayıt/golden (canlı modelle kaydedilmiş) → (`model_kaydi`, model)
    - `record` modunun birebir kaydı (`provenance` yok, `model` var) → (`model_kaydi`, model)
    - diğer her şey (elle hazırlanmış golden, ondan yükseltilmiş kayıt) → (`elle_hazirlanmis`,
      None)
    """
    if record.get("provenance") == MISS_NEUTRAL:
        return ORIGIN_NEUTRAL, None
    recording = record.get("recording")
    if isinstance(recording, Mapping) and isinstance(recording.get("model"), str):
        return ORIGIN_MODEL_RECORDING, recording["model"]
    if record.get("provenance") is None and isinstance(record.get("model"), str):
        return ORIGIN_MODEL_RECORDING, record["model"]
    return ORIGIN_HAND_PREPARED, None


def mode_label(mode: str, model: str | None = None) -> str:
    """Kullanıcıya gösterilecek dürüst üretim modu etiketi (Jira yorumu, portal ipucu).

    `model` çağrının `ai_call.model` değeridir. Replay çıktısı ancak gerçek bir model kaydıysa
    "kayıtlı model çıktısı" denir; elle hazırlanmış golden "hazırlanmış örnek çıktı"dır.

    >>> mode_label("replay", HAND_PREPARED_MODEL)
    'REPLAY (hazırlanmış örnek çıktı; canlı model değil)'
    >>> mode_label("replay", "claude-sonnet-5-5")
    'REPLAY (claude-sonnet-5-5 ile kaydedilmiş model çıktısı)'
    """
    if mode == "live":
        return f"canlı model ({model})" if model else "canlı model"
    if mode == "replay_miss":
        return "REPLAY-MISS (bu girdi için kayıtlı model çıktısı yok; canlı model gerekir)"
    if mode == "replay" and model and model != HAND_PREPARED_MODEL:
        return f"REPLAY ({model} ile kaydedilmiş model çıktısı)"
    if mode == "replay":
        return "REPLAY (hazırlanmış örnek çıktı; canlı model değil)"
    return mode


def _read(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "output" not in data:
        raise GatewayConfigError(f"{path}: replay kaydında 'output' yok")
    return data
