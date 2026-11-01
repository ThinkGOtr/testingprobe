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
  `replay_miss` olur (portalda REPLAY-MISS). Golden dosyası hiç yoksa (ör. demo sırasında
  jira-sim'de açılan yeni story) ve amacın nötr yedeği varsa yine nötr REPLAY-MISS döner
  (`_mismatch = ["bu anahtar için golden yok"]`); yedek de yoksa `ReplayNotFound`.
- Aynı story'nin tur golden'ları (`TPD-1` → `TPD-1-r2`): 1. tur adı uymazsa ya da yoksa aynı
  önekli `-rN` golden'ları da denenir; içeriği uyan ilk golden `golden_matched` döner (düzeltilmiş
  TPD-1 metniyle `make reset` olmadan yeniden koşu REPLAY-MISS olmaz). Geriye (r2 → 1. tur)
  bakılmaz: düzeltilmemiş belgenin 2. turu dürüstçe REPLAY-MISS kalır.
- Iskalama politikası `on_miss.json` içinde `"policy": "raise"` ise (case üretimi: şema en az bir
  case ister, nötr çıktı yoktur) başka dokümanın çıktısı **hiç döndürülmez**; `ReplayNoOutput`
  fırlatılır ("REPLAY-MISS: bu girdi için kayıtlı model çıktısı yok; canlı model gerekir"), sıfır
  taslak. Geçit bu durumu da `ai_call`'a (mod `replay_miss`, `hata`) yazar.
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
- Senaryo golden'ları (`golden/<senaryo>/<ad>.json`): aynı ad için analistin başka bir kararla
  vardığı belge (ör. `f2-kod-hatasi/`: F2 `code_defect`, AC2 değişmez). Ana golden ve tur
  golden'ları uymazsa senaryo dizinleri ada göre sıralı denenir; yalnızca girdi beyanı
  (`input_match`) taşıyan ve girdiye UYAN senaryo golden'ı döner (`golden_matched`; kayıttaki
  `golden` = `<senaryo>/<ad>`, `ek.replay_kaynagi` gerçek dosya). Beyansız ya da uymayan senaryo
  golden'ı hiçbir zaman döndürülmez (iskalama yine ana golden'ın politikasıyla). `f2-kod-hatasi`
  demo'nun ANA senaryosudur (Demo-B'nin "defect adayı" anı); `golden/*.json` F2 `fix_doc`
  alternatifini ve senaryonun değişmeyen case'lerini taşır, CI/portal kopyaları değişmez.
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
from tp_core.gateway.errors import (
    GatewayConfigError,
    ReplayMiss,
    ReplayNoOutput,
    ReplayNotFound,
)
from tp_core.gateway.matching import MATCHED, input_mismatches, matched_output

ReplayMode = Literal["replay", "replay_miss"]
PROMOTED = "golden_promoted"
MISS_NEUTRAL = "miss_neutral"
MISS_FILE = "on_miss.json"
# `on_miss.json` politikaları: nötr çıktı döndür (varsayılan, `output` gerekir) / hiç çıktı verme.
MISS_POLICY_NEUTRAL = "neutral"
MISS_POLICY_RAISE = "raise"
NO_GOLDEN_REASON = "bu anahtar için golden yok"
# Kayıt üst verisi olmayan (elle hazırlanmış) replay çıktısının `ai_call.model` değeri.
HAND_PREPARED_MODEL = "golden-elle"
# `ai_call.ek.cikti_kokeni`: çıktının gerçekte nereden geldiği.
ORIGIN_MODEL_RECORDING = "model_kaydi"
ORIGIN_HAND_PREPARED = "elle_hazirlanmis"
ORIGIN_NEUTRAL = "notr_yedek"
_GOLDEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
# Senaryo golden'ı adı: `<senaryo>/<ad>` (tek düzey alt dizin).
_SCENARIO_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")
_PURPOSE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_ROUND_RE = re.compile(r"-r(\d+)$")
_CASE_RE = re.compile(r"-C\d+$")


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
        """Golden dosyası; `name` düz (`TPD-1-C3`) ya da senaryo adı (`f2-kod-hatasi/TPD-1-C3`)."""
        if not (_GOLDEN_RE.match(name) or _SCENARIO_NAME_RE.match(name)) or ".." in name:
            raise GatewayConfigError(f"Geçersiz golden adı: {name!r}")
        return self._dir(purpose) / "golden" / f"{name}.json"

    def scenarios(self, purpose: str) -> list[str]:
        """Amacın senaryo dizinleri (`golden/<senaryo>/`), ada göre sıralı."""
        folder = self._dir(purpose) / "golden"
        if not folder.is_dir():
            return []
        return sorted(p.name for p in folder.iterdir() if p.is_dir() and _GOLDEN_RE.match(p.name))

    def lookup(
        self,
        purpose: str,
        key: str,
        golden_name: str | None,
        messages: Sequence[Any] | None = None,
    ) -> tuple[dict[str, Any], ReplayMode, Path]:
        """Birebir kayıt → eşleşen golden (`replay`) → aynı story'nin sonraki tur golden'ı
        (`replay`) → girdiye uyan senaryo golden'ı (`golden/<senaryo>/`, `replay`) → iskalama
        (`replay_miss`).

        Eşleşen golden'ın döndürülen kopyasında `provenance = "golden_matched"`; eşleşmeyen
        golden'da `_mismatch` (neden listesi, `ai_call.ek.replay_eslesme`) bulunur. Golden girdi
        beyanı taşıyıp girdiye uymuyorsa ya da golden hiç yoksa amacın `on_miss.json` politikası
        uygulanır: nötr çıktı (`provenance = "miss_neutral"`, adım yok, dönen yol nötr yedeğin yolu)
        veya `ReplayNoOutput` (`"policy": "raise"`).
        """
        exact = self.exact_path(purpose, key)
        if exact.is_file():
            record = _read(exact)
            if not self.is_stale(purpose, record):
                return record, "replay", exact
        if not golden_name:
            raise ReplayNotFound(purpose, key, golden_name)
        golden = self.golden_path(purpose, golden_name)
        record = _read(golden) if golden.is_file() else None
        reasons = self.golden_mismatches(record, messages) if record is not None else []
        if record is not None and not reasons:
            return _matched(record, messages, golden), "replay", golden
        for name, path in self._later_rounds(purpose, golden_name):
            sibling = _read(path)
            if "input_match" in sibling and not self.golden_mismatches(sibling, messages):
                return _matched(sibling, messages, path, golden=name), "replay", path
        for name, path in self._scenario_candidates(purpose, golden_name):
            variant = _read(path)
            if "input_match" in variant and not self.golden_mismatches(variant, messages):
                return _matched(variant, messages, path, golden=name), "replay", path
        if self.strict:
            raise ReplayMiss(purpose, key, golden_name)
        if record is None:
            reasons = [NO_GOLDEN_REASON]
        declared = record is None or "input_match" in record
        policy = self.miss_policy(purpose) if declared else None
        if policy == MISS_POLICY_RAISE:
            raise ReplayNoOutput(purpose, key, golden_name, reasons)
        if policy == MISS_POLICY_NEUTRAL:
            neutral = self.miss_path(purpose)
            return (
                {
                    "kind": record.get("kind") if record else None,
                    "purpose": purpose,
                    "golden": golden_name,
                    "provenance": MISS_NEUTRAL,
                    "output": _read(neutral)["output"],
                    "_mismatch": reasons,
                },
                "replay_miss",
                neutral,
            )
        if record is not None:
            # Beyansız golden (senaryo adı) veya iskalama yedeği olmayan amaç.
            return {**record, "_mismatch": reasons}, "replay_miss", golden
        raise ReplayNotFound(purpose, key, golden_name)

    def _later_rounds(self, purpose: str, golden_name: str) -> list[tuple[str, Path]]:
        """1. tur story golden'ı (`TPD-1`) için aynı önekli sonraki tur golden'ları (`TPD-1-r2`…).

        Case düzeyi (`TPD-1-C2`) ve zaten tur golden'ı olan adlar için boş: 2. turun belgesi
        düzeltilmemişse 1. tur golden'ına geri düşülmez (dürüst REPLAY-MISS)."""
        return _round_files(self._dir(purpose) / "golden", golden_name)

    def _scenario_candidates(self, purpose: str, golden_name: str) -> list[tuple[str, Path]]:
        """Senaryo dizinlerindeki aynı adlı golden'lar ve (1. tur story adı için) onların tur
        golden'ları: `[(<senaryo>/<ad>, yol), …]`, senaryo sırasıyla.

        Senaryo adı (`f2-kod-hatasi/TPD-1`) ile çağrılırsa aday yoktur: senaryolar iç içe geçmez."""
        if "/" in golden_name:
            return []
        out: list[tuple[str, Path]] = []
        for scenario in self.scenarios(purpose):
            folder = self._dir(purpose) / "golden" / scenario
            direct = folder / f"{golden_name}.json"
            if direct.is_file():
                out.append((f"{scenario}/{golden_name}", direct))
            for name, path in _round_files(folder, golden_name):
                out.append((f"{scenario}/{name}", path))
        return out

    def miss_path(self, purpose: str) -> Path:
        """Amacın REPLAY-MISS politikası/nötr yedeği (yoksa eşleşmeyen golden çıktısı döner)."""
        return self._dir(purpose) / MISS_FILE

    def miss_policy(self, purpose: str) -> str | None:
        """`on_miss.json` yoksa None; `"policy": "raise"` → çıktı yok; aksi hâlde nötr çıktı."""
        path = self.miss_path(purpose)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        policy = data.get("policy", MISS_POLICY_NEUTRAL) if isinstance(data, dict) else None
        if policy == MISS_POLICY_RAISE:
            return MISS_POLICY_RAISE
        if policy != MISS_POLICY_NEUTRAL or "output" not in data:
            raise GatewayConfigError(f"{path}: geçersiz iskalama politikası ({policy!r})")
        return MISS_POLICY_NEUTRAL

    def neutral_output(self, purpose: str) -> Any | None:
        if self.miss_policy(purpose) != MISS_POLICY_NEUTRAL:
            return None
        return _read(self.miss_path(purpose))["output"]

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


def _round_files(folder: Path, golden_name: str) -> list[tuple[str, Path]]:
    """`folder` içindeki `<golden_name>-rN.json` dosyaları, N sırasıyla. Tur ya da case adı (veya
    senaryo adı) için boş: geriye ya da case'ler arasında atlanmaz."""
    if (
        "/" in golden_name
        or _ROUND_RE.search(golden_name)
        or _CASE_RE.search(golden_name)
        or not folder.is_dir()
    ):
        return []
    found: list[tuple[int, str, Path]] = []
    for path in folder.glob(f"{glob_escape(golden_name)}-r*.json"):
        m = _ROUND_RE.search(path.stem)
        if m and path.stem == f"{golden_name}-r{m.group(1)}":
            found.append((int(m.group(1)), path.stem, path))
    return [(name, path) for _, name, path in sorted(found)]


def glob_escape(name: str) -> str:
    """`glob` özel karakterlerini kaçırır (golden adları `_GOLDEN_RE` ile sınırlı; yine de)."""
    return re.sub(r"([*?\[])", r"[\1]", name)


def _matched(
    record: Mapping[str, Any], messages: Sequence[Any] | None, path: Path, **extra: Any
) -> dict[str, Any]:
    """Girdiye uyan golden'ın döndürülen kopyası: `provenance = golden_matched`; aday kümesi
    beyan eden (dup_rank) golden'ın çıktısı girdideki gerçek kümeye göre kurulur
    (`matching.matched_output`)."""
    try:
        output = matched_output(record, messages)
    except ValueError as exc:
        raise GatewayConfigError(f"{path}: {exc}") from exc
    return {**record, "provenance": MATCHED, **extra, "output": output}


def _read(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "output" not in data:
        raise GatewayConfigError(f"{path}: replay kaydında 'output' yok")
    return data
