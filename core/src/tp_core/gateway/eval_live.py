"""Canlı model hazırlığı: bağlantı denetimi, maliyet tahmini, değerlendirme koşusu (constitution X).

Yalnızca **açıkça** çağrıldığında çalışır (`scripts/eval-live.sh`, `make eval-live`); demo, CI ve
core-worker bu modülü hiç çağırmaz. `TP_MODEL_MODE` (.env'de `replay`) bu komutu etkilemez: komutun
kendisi canlı çağrı isteğidir. Üç kip:

- `--ping`     tek küçük çağrı (en ucuz amacın modeli, `max_tokens` 16). Çıktı `OK …` ya da API'nin
               hata türü/iletisi; anahtar ve çalışma alanı kimliği hiçbir zaman yazdırılmaz
               (yalnızca "çalışma alanı başlığı: gönderildi/gönderilmedi").
- `--dry-run`  API'ye hiç gitmeden her paketin setini ve tahmini maliyetini gösterir (token sayısı
               karakter/3 ile yukarı yuvarlanır; Türkçe metinde temkinli tahmin).
- (varsayılan) her prompt paketinin değerlendirme setini (`rules/evaluation/<paket>.json`) canlı
               modelle koşturur. Sert bütçe tavanı `TP_EVAL_BUDGET_USD` (varsayılan 5): her vakadan
               önce vakanın **en kötü durum** maliyeti (girdi + şema yeniden istemleri dahil tam
               `max_tokens` çıktı) harcanana eklenir; tavanı aşacaksa koşu durur (vaka çağrılmaz).
               Sonuç raporu mevcut mekanizmaya yazılır: `rules/evaluation/results/<paket>-v<n>-
               <tarih>.json` (`eval_set.write_report`). `--update-status` yalnızca set TAMAMEN
               koşup her vaka geçtiyse `rules/evaluations.yaml` kaydını `evaluated` yapar; aksi
               hâlde durum "canlı değerlendirme bekliyor" kalır.

`--record`: aynı koşu `record` kipinde, birebir kayıtları AYRI bir dizine yazar (varsayılan
`exports/eval-live/<zaman>/replay-adaylari/`, git'e girmez). Commit'li golden'lar
(`rules/replay/**`) asla yazılmaz; dizin `rules/replay` içindeyse komut reddeder. Dizindeki
`INDEX.json` her kaydın hangi vakaya ve (girdi beyanına göre) hangi golden'a karşılık geldiğini,
`README.md` insan incelemesi adımlarını verir.

Setler: 7 paketin hepsinde (`rules/evaluation/<paket>.json`, `build_eval_sets.py` üretir). Case
üretimi §12'deki gibi 5 story × 3 koşudur (`runs`). Ajan setleri (consistency-check,
verify-and-map) modelin araç çağrılarını üretimdeki araçlarla yürütür (`eval_agents`: forge +
demo-app salt okuma veritabanı; Playwright MCP); araç ortamı kurulamazsa paket ATLANIR ve durumu
değişmez. Ortak `guardrails` paketinin seti yoktur: guardrails'i içeren HER paket aynı guardrails
sürümüyle `evaluated` olunca `--update-status` onu da geçişli olarak `evaluated` yazar
(`eval_set.guardrails_coverage`). Bu komut değerlendirme kaydı uydurmaz; istisna (`waived`) yazmaz.

Denetim (constitution VIII): host'ta veritabanı yoktur; her canlı çağrı (vaka çağrıları ve
`--ping`) geçidin `ai_call` satırı biçiminde (model, bundle_hash, maskeli girdi, çıktı, token,
maliyet, hata) sır temizlenmiş olarak ekle-yalnız, hash zincirli deftere yazılır:
`exports/eval-live/ai_call.jsonl` (`--ledger`; `CallLedger.verify` zinciri denetler). Paketin
çağrıları ayrıca raporun yanına `<rapor>.calls.jsonl` olarak yazılır ve `evaluations.yaml`
kaydındaki `evaluation.calls` onu gösterir ("evaluated" iddiası sonradan denetlenebilir).
Değerlendirme koşusu REPLAY yedeğine hiçbir zaman düşmez (`replay_fallback=False`).

    cd core && uv run python -m tp_core.gateway.eval_live --ping
    cd core && uv run python -m tp_core.gateway.eval_live --dry-run
    cd core && uv run python -m tp_core.gateway.eval_live --bundle triage --record --update-status
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tp_core.gateway.budget import Budget, InMemorySpendLedger
from tp_core.gateway.bundle import load_schema
from tp_core.gateway.config import (
    GatewaySettings,
    ModelTable,
    find_rules_dir,
    load_model_table,
)
from tp_core.gateway.core import MAX_SCHEMA_REASKS, Gateway
from tp_core.gateway.errors import GatewayConfigError, GatewayError
from tp_core.gateway.eval_agents import EnvFactory, ToolEnv, ToolEnvUnavailable, open_env
from tp_core.gateway.eval_set import (
    GUARDRAILS,
    CaseResult,
    case_messages,
    case_replay_key,
    guardrails_coverage,
    load_set,
    mark_evaluated,
    mark_guardrails_if_covered,
    run_case,
    run_id,
    runs_of,
    set_path,
    write_report,
)
from tp_core.gateway.evaluation import PENDING_LABEL, prompt_versions
from tp_core.gateway.factory import build_provider, load_pii_allowlist
from tp_core.gateway.masking import PiiMasker
from tp_core.gateway.providers.base import Provider, ProviderRequest
from tp_core.gateway.replay import ReplayStore
from tp_core.gateway.testing import InMemoryCallRecorder

BUDGET_ENV = "TP_EVAL_BUDGET_USD"
DEFAULT_BUDGET_USD = 5.0
PING_PURPOSE = "triage"  # en ucuz amaç (Haiku sınıfı)
PING_MAX_TOKENS = 16
CHARS_PER_TOKEN = 3  # temkinli (Türkçe metin token başına ~3-4 karakter)
# Önbelleğe yazma 1.25× girdi fiyatıdır; tahmin her girdiyi yazma fiyatıyla sayar (üst sınır).
CACHE_WRITE_FACTOR = 1.25
REASK_OVERHEAD_TOKENS = 200  # yeniden istem mesajı
AGENT_TYPICAL_TURNS = 8  # ajan "tek deneme" tahmini: tipik yörünge (en kötü durum max_turns)
CANDIDATES_SUBDIR = "replay-adaylari"
CANDIDATES_README = """# REPLAY kayıt adayları (insan incelemesi bekliyor)

`scripts/eval-live.sh --record` ile canlı modelden (sağlayıcı {provider}) kaydedildi.
Bu dizin git'e girmez ve commit'li golden'ları (`rules/replay/**`) DEĞİŞTİRMEZ.

Bir golden'ı yenilemek için (insan kararı):

1. `INDEX.json`'da vakanın `golden` alanı hedef golden'ı gösterir. "(eşleşen golden yok…)"
   ise kayıt yeni bir girdi içindir; golden'a dönüştürmeden önce `input_match` beyanı yazılır.
2. Kaydın `output`'unu okuyun: demo hikâyesiyle (docs/DEMO-VERISI.md) ve kanıt testleriyle
   (`test_goldens.py`, `test_defect_goldens.py`) tutarlı mı?
3. Uygunsa golden'ın `output`'unu kaydınkiyle değiştirin; `recording` ve `recorded_at`
   alanlarını golden'a taşıyın (yoksa çıktı "hazırlanmış örnek" etiketlenir); `input_match`
   beyanını KORUYUN.
4. `cd core && uv run pytest tests/unit/gateway` yeşil olmalı; değişikliği PR ile önerin.
"""
_KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{4,}")
_MASK = "***"

ProviderFactory = Callable[[GatewaySettings], Provider]


# ------------------------------------------------------------------ sır temizliği


def secret_values(settings: GatewaySettings) -> list[str]:
    out = []
    for secret in (settings.anthropic_api_key, settings.anthropic_workspace_id):
        value = secret.get_secret_value().strip() if secret else ""
        if value:
            out.append(value)
    return out


def redact(text: Any, secrets: Iterable[str] = ()) -> str:
    """Bilinen sır değerlerini ve anahtar biçimli dizgileri `***` yapar (çıktı/rapor için)."""
    out = "" if text is None else str(text)
    for value in sorted({s for s in secrets if s and len(s) >= 4}, key=len, reverse=True):
        out = out.replace(value, _MASK)
    return _KEY_RE.sub("sk-ant-" + _MASK, out)


# ------------------------------------------------------------------ çağrı kaydı (constitution VIII)

LEDGER_NAME = "ai_call.jsonl"


def default_ledger_path(rules_dir: Path) -> Path:
    """Host'taki canlı çağrıların ekle-yalnız defteri (git dışı `exports/`)."""
    return rules_dir.resolve().parent / "exports" / "eval-live" / LEDGER_NAME


def _json_line(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


class CallLedger:
    """Ekle-yalnız, hash zincirli JSONL çağrı defteri (constitution VIII, host tarafı).

    `eval-live` ve `--ping` core-worker dışında, veritabanına erişmeden koşar; çağrıları geçidin
    `ai_call` satırı biçiminde (model, bundle_hash, maskeli girdi, çıktı, token, maliyet) bu deftere
    yazar. Her satır `onceki_ozet` (önceki satırın `ozet`'i) ve kendi `ozet`'ini (satırın `ozet`
    hariç kanonik JSON'unun sha256'sı) taşır: silinen/değiştirilen satır `verify()` ile görünür.
    Sırlar `redact` ile satır yazılmadan önce temizlenir. Ayrıca her paketin çağrıları raporun
    yanında `<rapor>.calls.jsonl` olarak commit'lenebilir (değerlendirme kaydının dayanağı).
    """

    def __init__(self, path: Path, secrets: Iterable[str] = ()) -> None:
        self.path = Path(path)
        self.secrets = list(secrets)

    def _last_digest(self) -> str | None:
        if not self.path.is_file():
            return None
        last = None
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = line
        return json.loads(last)["ozet"] if last else None

    def append(self, kind: str, rows: Sequence[Mapping[str, Any]], **meta: Any) -> list[dict]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        prev = self._last_digest()
        written = []
        with self.path.open("a", encoding="utf-8") as fh:
            for row in rows:
                clean = json.loads(redact(_json_line(dict(row)), self.secrets))
                entry = {
                    "tur": kind,
                    "kayit_zamani": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                    **{k: v for k, v in meta.items() if v is not None},
                    "ai_call": clean,
                    "onceki_ozet": prev,
                }
                entry["ozet"] = hashlib.sha256(_json_line(entry).encode()).hexdigest()
                fh.write(_json_line(entry) + "\n")
                prev = entry["ozet"]
                written.append(entry)
        return written

    @staticmethod
    def verify(path: Path) -> list[str]:
        """Zincir kırıkları (boş = sağlam)."""
        problems: list[str] = []
        prev = None
        if not Path(path).is_file():
            return problems
        for no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            entry = json.loads(line)
            digest = entry.pop("ozet", None)
            if entry.get("onceki_ozet") != prev:
                problems.append(f"satır {no}: önceki özet uyuşmuyor")
            if hashlib.sha256(_json_line(entry).encode()).hexdigest() != digest:
                problems.append(f"satır {no}: içerik özeti uyuşmuyor")
            prev = digest
        return problems


def write_calls_file(path: Path, rows: Sequence[Mapping[str, Any]], secrets: Iterable[str]) -> Path:
    """Paketin canlı çağrı satırları (redakte) raporun yanına: `<rapor>.calls.jsonl`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(redact(_json_line(dict(r)), secrets) + "\n" for r in rows)
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------------ bağlantı denetimi


@dataclass(frozen=True)
class ApiError:
    kind: str  # API hata türü (ör. invalid_request_error) ya da istisna sınıfı
    message: str
    status: int | None = None
    request_id: str | None = None

    def line(self, secrets: Iterable[str] = ()) -> str:
        status = f" (HTTP {self.status})" if self.status else ""
        rid = f" [istek {self.request_id}]" if self.request_id else ""
        return f"HATA: {self.kind}{status}: {redact(self.message, secrets)}{rid}"


def api_error_of(exc: BaseException) -> ApiError:
    """Geçit/SDK istisna zincirinden API hata türü ve iletisi (`{"error": {type, message}}`)."""
    seen: BaseException | None = exc
    while seen is not None:
        body = getattr(seen, "body", None)
        if isinstance(body, Mapping):
            err = body.get("error") if isinstance(body.get("error"), Mapping) else body
            kind = err.get("type") if isinstance(err.get("type"), str) else type(seen).__name__
            message = err.get("message") if isinstance(err.get("message"), str) else str(seen)
            status = getattr(seen, "status_code", None)
            rid = getattr(seen, "request_id", None)
            return ApiError(
                kind,
                message,
                status if isinstance(status, int) else None,
                rid if isinstance(rid, str) else None,
            )
        seen = seen.__cause__
    status = getattr(exc, "status", None)
    return ApiError(type(exc).__name__, str(exc), status if isinstance(status, int) else None)


def ping(
    settings: GatewaySettings,
    models: ModelTable,
    provider_factory: ProviderFactory = build_provider,
    *,
    out: Callable[[str], None] = print,
    ledger: CallLedger | None = None,
) -> int:
    """Tek küçük canlı çağrı. Çıkış 0 = OK, 1 = API hatası, 2 = yapılandırma eksik.

    `ledger`: çağrı (başarılı ya da hatalı) ekle-yalnız deftere `ai_call` biçiminde yazılır."""
    secrets = secret_values(settings)
    try:
        provider = provider_factory(settings)
    except GatewayError as exc:
        out(f"HATA: {type(exc).__name__}: {redact(exc, secrets)}")
        return 2
    header = "gönderildi" if getattr(provider, "workspace_header", False) else "gönderilmedi"
    cfg = models.purpose(PING_PURPOSE)
    request = ProviderRequest(
        model=cfg.model,
        system="Bağlantı denetimi. Yalnızca OK yaz.",
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=PING_MAX_TOKENS,
        timeout_s=30,
    )
    out(f"Canlı bağlantı denetimi: model {cfg.model}, çalışma alanı başlığı {header}")
    started = time.monotonic()
    row: dict[str, Any] = {
        "amac": "ping",
        "saglayici": getattr(provider, "name", "?"),
        "model": cfg.model,
        "mod": "live",
        "maskeli_girdi": request.messages,
        "calisma_alani_basligi": header == "gönderildi",
    }
    try:
        response = provider.complete(request)
    except Exception as exc:  # her hata türü/iletisi insana gösterilir
        err = api_error_of(exc)
        if ledger is not None:
            row.update(
                hata=err.line(secrets),
                maliyet=0.0,
                sure_ms=int((time.monotonic() - started) * 1000),
            )
            ledger.append("ping", [row])
        out(err.line(secrets))
        return 1
    cost = models.cost(cfg.model, response.usage)
    if ledger is not None:
        row.update(
            model=response.model or cfg.model,
            cikti=response.text,
            girdi_token=response.usage.input_tokens,
            cikti_token=response.usage.output_tokens,
            maliyet=cost,
            sure_ms=int((time.monotonic() - started) * 1000),
            hata=None,
        )
        ledger.append("ping", [row])
    out(
        f"OK: yanıt modeli {response.model or cfg.model}, "
        f"{int((time.monotonic() - started) * 1000)} ms, "
        f"girdi {response.usage.input_tokens} / çıktı {response.usage.output_tokens} token, "
        f"~{cost:.6f} USD"
    )
    return 0


# ------------------------------------------------------------------ maliyet tahmini


@dataclass(frozen=True)
class CaseEstimate:
    input_tokens: int
    max_output_tokens: int
    single_usd: float  # tek deneme, tam max_tokens çıktı
    worst_usd: float  # şema yeniden istemleri dahil en kötü durum (bütçe denetimi bunu kullanır)


def estimate_case(gw: Gateway, data: Mapping[str, Any], case: Mapping[str, Any]) -> CaseEstimate:
    purpose = str(data["purpose"])
    cfg = gw.models.purpose(purpose)
    schema = load_schema(gw.rules_dir, purpose)
    system = gw.bundle(str(data["bundle"]), schema, cfg).system_prompt
    chars = len(system) + len(json.dumps(case["messages"], ensure_ascii=False))
    tokens = math.ceil(chars / CHARS_PER_TOKEN)
    price = gw.models.price(cfg.model)
    out_tokens = cfg.max_tokens
    attempts = 1 + MAX_SCHEMA_REASKS

    def attempt_cost(extra_in: int) -> float:
        return (
            (tokens + extra_in) * price.input * CACHE_WRITE_FACTOR + out_tokens * price.output
        ) / 1_000_000

    agent = data.get("agent")
    if agent:
        # Ajan: tur başına tam max_tokens çıktı; önbelleksiz+yazma girdi toplamı amaç tavanıyla
        # (`max_input_tokens`) sınırlı, önbellekten okunan önek her tur yeniden okunur.
        turns = int(agent.get("max_turns") or 15)
        cap = cfg.max_input_tokens or tokens * turns
        worst = (
            cap * price.input * CACHE_WRITE_FACTOR
            + turns * out_tokens * price.output
            + turns * min(cap, tokens * 4) * price.cache_read
        ) / 1_000_000
        single = attempt_cost(0) * min(turns, AGENT_TYPICAL_TURNS)
        return CaseEstimate(tokens, out_tokens * turns, round(single, 6), round(worst, 6))
    worst = sum(attempt_cost(a * (out_tokens + REASK_OVERHEAD_TOKENS)) for a in range(attempts))
    return CaseEstimate(tokens, out_tokens, round(attempt_cost(0), 6), round(worst, 6))


# ------------------------------------------------------------------ plan


@dataclass
class BundlePlan:
    bundle: str
    prompt_version: int
    data: dict[str, Any] | None = None
    skip_reason: str | None = None


def plan_bundles(rules_dir: Path, only: Sequence[str] = ()) -> list[BundlePlan]:
    versions = prompt_versions(rules_dir)
    unknown = sorted(set(only) - set(versions))
    if unknown:
        raise GatewayConfigError(f"bilinmeyen prompt paketi: {', '.join(unknown)}")
    plans = []
    for bundle, version in versions.items():
        if only and bundle not in only:
            continue
        plan = BundlePlan(bundle, version)
        if bundle == GUARDRAILS:
            plan.skip_reason = (
                "ayrı set yok; kapsam geçişli: diğer paketler guardrails "
                f"v{version} ile canlı değerlendirilince --update-status bunu da yazar"
            )
        elif not set_path(rules_dir, bundle).is_file():
            plan.skip_reason = (
                "değerlendirme seti yok (rules/evaluation/); durum değişmez: " + PENDING_LABEL
            )
        else:
            data = load_set(rules_dir, bundle)
            if int(data["version"]) != version:
                plan.skip_reason = (
                    f"set v{data['version']}, prompt v{version}: set bayat, yeniden üretin "
                    "(core/tests/unit/gateway/build_eval_sets.py)"
                )
            else:
                plan.data = data
        plans.append(plan)
    return plans


# ------------------------------------------------------------------ koşu


@dataclass
class BundleRun:
    bundle: str
    results: list[CaseResult] = field(default_factory=list)
    cost_usd: float = 0.0
    complete: bool = True
    report: Path | None = None
    marked: bool = False

    @staticmethod
    def report_calls_name(data: Mapping[str, Any], today: dt.date | None) -> str:
        day = (today or dt.date.today()).isoformat()
        return f"{data['bundle']}-v{data['version']}-{day}.calls.jsonl"


def _offline_gateway(rules_dir: Path) -> Gateway:
    """Tahmin için: sağlayıcısız (çağrı yapamaz) geçit; yalnızca paket/fiyat bilgisi."""
    return Gateway(
        provider=None,
        recorder=InMemoryCallRecorder(),
        mode="replay",
        models=load_model_table(rules_dir),
        rules_dir=rules_dir,
    )


def dry_run(
    rules_dir: Path, plans: Sequence[BundlePlan], budget: float, out: Callable[[str], None]
) -> int:
    gw = _offline_gateway(rules_dir)
    out(f"KURU KOŞU — API çağrısı yapılmaz. Bütçe tavanı {budget:.2f} USD ({BUDGET_ENV}).")
    total_single = total_worst = 0.0
    for plan in plans:
        if plan.data is None:
            out(f"  {plan.bundle}@v{plan.prompt_version}: ATLANIR — {plan.skip_reason}")
            continue
        model = gw.models.purpose(str(plan.data["purpose"])).model
        runs = runs_of(plan.data)
        ests = [estimate_case(gw, plan.data, c) for c in plan.data["cases"]] * runs
        single, worst = sum(e.single_usd for e in ests), sum(e.worst_usd for e in ests)
        total_single += single
        total_worst += worst
        agent = plan.data.get("agent")
        extra = f" × {runs} koşu" if runs > 1 else ""
        if agent:
            env_name, turns = agent.get("tool_env"), agent.get("max_turns")
            extra += f", ajan (araç ortamı '{env_name}', ≤{turns} tur)"
        out(
            f"  {plan.bundle}@v{plan.prompt_version}: {len(plan.data['cases'])} vaka{extra}, "
            f"{model}, ~{sum(e.input_tokens for e in ests)} girdi token; tek deneme "
            f"≤{single:.4f} USD, en kötü durum ≤{worst:.4f} USD"
        )
    verdict = (
        "tavanın altında"
        if total_worst <= budget
        else "tavanı aşabilir (koşu tavanda durur, kalan vakalar koşmaz)"
    )
    out(
        f"Toplam: tek deneme ≤{total_single:.4f} USD, en kötü durum ≤{total_worst:.4f} USD — "
        f"{verdict}."
    )
    if total_worst > budget:
        out(
            f"  Tüm paketleri tek koşuda bitirmek için: --budget-usd {math.ceil(total_worst)} "
            f"(ya da {BUDGET_ENV}); en kötü durum tahmini üst sınırdır, gerçek harcama raporda."
        )
    return 0


def _assert_outside_goldens(record_dir: Path, rules_dir: Path) -> None:
    committed = (rules_dir / "replay").resolve()
    target = record_dir.resolve()
    if target == committed or committed in target.parents:
        raise GatewayConfigError(
            f"kayıt dizini commit'li golden'ların içinde olamaz: {record_dir} "
            "(adaylar ayrı dizine yazılır; golden'lar insan incelemesiyle güncellenir)"
        )


def default_record_dir(rules_dir: Path, now: dt.datetime | None = None) -> Path:
    stamp = (now or dt.datetime.now(dt.UTC)).strftime("%Y%m%dT%H%M%SZ")
    return rules_dir.resolve().parent / "exports" / "eval-live" / stamp / CANDIDATES_SUBDIR


def _golden_target(rules_dir: Path, data: Mapping[str, Any], case: Mapping[str, Any]) -> str:
    """Vakanın girdisi commit'li hangi golden'ın beyanına uyuyor (kayıt neyi yenileyebilir)."""
    replay_key = case_replay_key(data, case)
    name = replay_key.get("name")
    if not name:
        return "(golden adı yok)"
    store = ReplayStore(rules_dir / "replay")
    msgs = [m.model_dump(mode="json") for m in case_messages(case)]
    if data.get("agent"):
        return f"(ajan golden'ı: {name}; adımlar insan incelemesiyle karşılaştırılır)"
    try:
        _record, mode, path = store.lookup(str(data["purpose"]), "-", str(name), msgs)
    except GatewayError as exc:
        return f"(eşleşen golden yok: {type(exc).__name__})"
    if mode != "replay":
        return "(eşleşen golden yok: REPLAY-MISS)"
    return str(path.relative_to(rules_dir))


def _write_candidate_index(record_dir: Path, entries: list[dict[str, Any]], provider: str) -> None:
    record_dir.mkdir(parents=True, exist_ok=True)
    (record_dir / "INDEX.json").write_text(
        json.dumps({"kayitlar": entries}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (record_dir / "README.md").write_text(
        CANDIDATES_README.format(provider=provider), encoding="utf-8"
    )


def run_live(
    settings: GatewaySettings,
    rules_dir: Path,
    plans: Sequence[BundlePlan],
    budget: float,
    *,
    record_dir: Path | None = None,
    update_status: bool = False,
    provider_factory: ProviderFactory = build_provider,
    out: Callable[[str], None] = print,
    today: dt.date | None = None,
    ledger: CallLedger | None = None,
    envs: Mapping[str, EnvFactory] | None = None,
) -> int:
    secrets = secret_values(settings)
    if record_dir is not None:
        _assert_outside_goldens(record_dir, rules_dir)
    try:
        provider = provider_factory(settings)
    except GatewayError as exc:
        out(f"HATA: {type(exc).__name__}: {redact(exc, secrets)}")
        return 2
    ledger = ledger if ledger is not None else CallLedger(default_ledger_path(rules_dir), secrets)
    mode = "record" if record_dir is not None else "live"
    replay_store = ReplayStore(record_dir if record_dir is not None else rules_dir / "replay")
    if record_dir is not None:
        replay_store.ensure_writable()
    recorder = InMemoryCallRecorder()
    gw = Gateway(
        provider=provider,
        recorder=recorder,
        mode=mode,
        models=load_model_table(rules_dir),
        rules_dir=rules_dir,
        # İkinci savunma: geçidin kendi tavanı (çağrı öncesi girdi tahmini) aynı bütçeyle.
        budget=Budget(workflow_cap_usd=budget, daily_cap_usd=budget, ledger=InMemorySpendLedger()),
        masker=PiiMasker(enabled=settings.pii_masking, allowlist=load_pii_allowlist(rules_dir)),
        replay_store=replay_store,
        record_extras=True,
        # Değerlendirme REPLAY'e asla düşmez (canlı hata vakayı düşürür; sahte başarı olmaz).
        replay_fallback=False,
    )
    guard_version = prompt_versions(rules_dir).get(GUARDRAILS)
    header = "gönderildi" if getattr(provider, "workspace_header", False) else "gönderilmedi"
    out(
        f"CANLI DEĞERLENDİRME ({mode}) — gerçek API çağrıları; bütçe tavanı {budget:.2f} USD "
        f"({BUDGET_ENV}); çalışma alanı başlığı {header}; çağrı defteri {ledger.path}."
    )
    spent = 0.0
    stopped = False
    runs: list[BundleRun] = []
    candidates: list[dict[str, Any]] = []
    failed_any = False
    models_used: set[str] = set()
    for plan in plans:
        if plan.data is None:
            out(f"  {plan.bundle}@v{plan.prompt_version}: ATLANDI — {plan.skip_reason}")
            continue
        data = plan.data
        purpose = str(data["purpose"])
        schema = load_schema(rules_dir, purpose)
        run = BundleRun(plan.bundle)
        if stopped:
            run.complete = False
            out(f"  {plan.bundle}: ATLANDI — bütçe tavanı")
            runs.append(run)
            continue
        env: ToolEnv | None = None
        agent = data.get("agent")
        if agent:
            try:
                env = open_env(str(agent.get("tool_env")), envs)
            except ToolEnvUnavailable as exc:
                run.complete = False
                failed_any = True
                out(
                    f"  {plan.bundle}@v{plan.prompt_version}: ATLANDI — araç ortamı yok: "
                    f"{redact(exc, secrets)}; durum değişmedi: {PENDING_LABEL}"
                )
                runs.append(run)
                continue
        bundle_rows: list[dict[str, Any]] = []
        repeat = runs_of(data)
        try:
            for case in data["cases"]:
                for k in range(1, repeat + 1):
                    cid = run_id(case, k, repeat)
                    est = estimate_case(gw, data, case)
                    if spent + est.worst_usd > budget:
                        stopped, run.complete = True, False
                        out(
                            f"  DURDU: {plan.bundle}/{cid} en kötü durumda {est.worst_usd:.4f} "
                            f"USD; harcanan {spent:.4f} + bu > tavan {budget:.2f} USD"
                        )
                        break
                    before = len(recorder.ai_calls)
                    result = run_case(gw, data, case, schema, env=env, case_id=cid)
                    rows = recorder.ai_calls[before:]
                    for r in rows:
                        r.setdefault("eval_vaka", cid)
                    bundle_rows += rows
                    ledger.append(
                        "eval-live", rows, paket=plan.bundle, surum=plan.prompt_version, vaka=cid
                    )
                    cost = round(sum(float(r.get("maliyet") or 0.0) for r in rows), 6)
                    spent += cost
                    run.cost_usd += cost
                    if result.error:
                        result.error = redact(result.error, secrets)
                    result.failures = [redact(f, secrets) for f in result.failures]
                    run.results.append(result)
                    out(
                        f"  {'GEÇTİ' if result.ok else 'KALDI'}\t{plan.bundle}/{result.id}\t"
                        f"{cost:.4f} USD\t{'; '.join(result.failures)}"
                        + (f"\t{result.error}" if result.error else "")
                    )
                    if record_dir is not None and result.mode == "live" and not agent:
                        info = gw.replay_key_for_call(
                            purpose,
                            str(data["bundle"]),
                            case_messages(case),
                            schema,
                            replay_key=case_replay_key(data, case),
                        )
                        path = replay_store.exact_path(purpose, info.key)
                        if path.is_file():
                            candidates.append(
                                {
                                    "paket": plan.bundle,
                                    "vaka": cid,
                                    "gecti": result.ok,
                                    "kayit": str(path.relative_to(record_dir)),
                                    "golden": _golden_target(rules_dir, data, case),
                                }
                            )
                if stopped:
                    break
        finally:
            if env is not None:
                env.close()
        model = gw.models.purpose(purpose).model
        models_used.add(model)
        total = len(data["cases"]) * repeat
        calls_rel: str | None = None
        if run.results:
            run.report = write_report(
                rules_dir,
                data,
                run.results,
                model=model,
                provider=gw.provider_name,
                mode=mode,
                today=today,
                extra={
                    "tamamlandi": run.complete,
                    "set_vaka_sayisi": len(data["cases"]),
                    "kosu_sayisi": total,
                    "maliyet_usd": round(run.cost_usd, 6),
                    "butce_usd": budget,
                    "calisma_alani_basligi": header == "gönderildi",
                    "guardrails_version": guard_version,
                    "kayit_adaylari": str(record_dir) if record_dir is not None else None,
                    "cagri_kaydi": run.report_calls_name(data, today),
                    "cagri_sayisi": len(bundle_rows),
                    "cagri_defteri": str(ledger.path),
                },
            )
            calls = write_calls_file(run.report.with_suffix(".calls.jsonl"), bundle_rows, secrets)
            calls_rel = str(calls.relative_to(rules_dir))
        passed = bool(run.results) and all(r.ok for r in run.results)
        complete = run.complete and len(run.results) == total
        failed_any = failed_any or not passed or not complete
        if update_status and passed and complete and run.report is not None:
            mark_evaluated(
                rules_dir,
                plan.bundle,
                int(data["version"]),
                model=model,
                provider=gw.provider_name,
                results=str(run.report.relative_to(rules_dir)),
                today=today,
                passed=sum(r.ok for r in run.results),
                total=total,
                guardrails_version=guard_version,
                calls=calls_rel,
            )
            run.marked = True
        status = "evaluated yazıldı" if run.marked else ("durum değişmedi: " + PENDING_LABEL)
        out(
            f"  {plan.bundle}: {sum(r.ok for r in run.results)}/{total} geçti, "
            f"{run.cost_usd:.4f} USD, {status}"
            + (f" → {run.report.relative_to(rules_dir)}" if run.report else "")
        )
        runs.append(run)
    if update_status and any(r.marked for r in runs):
        if mark_guardrails_if_covered(
            rules_dir,
            model=", ".join(sorted(models_used)),
            provider=gw.provider_name,
            today=today,
        ):
            out(f"  {GUARDRAILS}: geçişli kapsam tamam → evaluated yazıldı")
        else:
            _, missing = guardrails_coverage(rules_dir)
            out(f"  {GUARDRAILS}: {PENDING_LABEL} (geçişli kapsam eksik: {', '.join(missing)})")
    if record_dir is not None:
        _write_candidate_index(record_dir, candidates, provider.name)
        out(f"Kayıt adayları (insan incelemesi; golden'lar değişmedi): {record_dir}")
    out(f"Toplam harcama {spent:.4f} USD / tavan {budget:.2f} USD.")
    if not any(r.results for r in runs):
        return 1
    return 1 if failed_any or stopped else 0


# ------------------------------------------------------------------ CLI


def _budget(value: str | None) -> float:
    raw = value if value is not None else os.environ.get(BUDGET_ENV, "")
    if not raw:
        return DEFAULT_BUDGET_USD
    try:
        budget = float(raw)
    except ValueError:
        raise GatewayConfigError(f"{BUDGET_ENV} sayı olmalı: {raw!r}") from None
    if not math.isfinite(budget) or budget <= 0:
        raise GatewayConfigError(f"{BUDGET_ENV} pozitif olmalı: {raw!r}")
    return budget


def main(
    argv: list[str] | None = None,
    *,
    provider_factory: ProviderFactory = build_provider,
    out: Callable[[str], None] = print,
) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--ping", action="store_true", help="tek küçük canlı çağrı (OK / hata)")
    parser.add_argument("--dry-run", action="store_true", help="API çağrısı yok; maliyet tahmini")
    parser.add_argument("--bundle", action="append", default=[], help="yalnızca bu paket(ler)")
    parser.add_argument("--budget-usd", default=None, help=f"tavan (varsayılan {BUDGET_ENV}/5)")
    parser.add_argument("--record", action="store_true", help="kayıt adaylarını ayrı dizine yaz")
    parser.add_argument("--record-dir", type=Path, default=None)
    parser.add_argument("--update-status", action="store_true")
    parser.add_argument("--rules-dir", type=Path, default=None)
    parser.add_argument(
        "--ledger", type=Path, default=None, help="çağrı defteri (vars. exports/eval-live/)"
    )
    args = parser.parse_args(argv)
    try:
        settings = GatewaySettings()
        rules_dir = Path(args.rules_dir or find_rules_dir(settings.rules_dir))
        ledger = CallLedger(args.ledger or default_ledger_path(rules_dir), secret_values(settings))
        if args.ping:
            return ping(
                settings, load_model_table(rules_dir), provider_factory, out=out, ledger=ledger
            )
        budget = _budget(args.budget_usd)
        plans = plan_bundles(rules_dir, args.bundle)
        if args.dry_run:
            return dry_run(rules_dir, plans, budget, out)
        record_dir = args.record_dir or (default_record_dir(rules_dir) if args.record else None)
        return run_live(
            settings,
            rules_dir,
            plans,
            budget,
            record_dir=record_dir,
            update_status=args.update_status,
            provider_factory=provider_factory,
            out=out,
            ledger=ledger,
        )
    except GatewayConfigError as exc:
        out(f"HATA: {redact(exc, secret_values(GatewaySettings()))}")
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
