"""Model geçidi çekirdeği: `ports.ModelGateway` uygulaması (TEKNIK-TASARIM §8.8).

Sağlayıcıdan bağımsızdır; sağlayıcıya özgü her şey `providers/` altındadır.

`CallRecorder.record_ai_call` satırı; anahtarlar `ai_call` kolonlarıdır (tp_core.audit.recorder):
    id, parent_call_id, workflow_id, amac, saglayici, model, surum (bundle id@sürüm), bundle_hash,
    maskeli_girdi, cikti, sema_gecerli, deneme, girdi_token, cikti_token, maliyet (USD), sure_ms,
    mod ('live'|'replay'|'replay_miss'), replay_anahtari, hata (şema hataları dahil),
    maskeleme_farki
    `record_extras=True` ise ayrıca `ek` (jsonb): replay_kaynagi, sema_hatalari, yeniden_deneme,
    onbellek_okuma_token, onbellek_yazma_token. Kolon eklenene kadar varsayılan kapalı.
`record_tool_call` satırı:
    id, ai_call_id, kanal ('agent'), cagiran_user_id, arac, arguman_ozeti (jsonb), sonuc_ozeti,
    izin_verildi

İdempotency (§8.8 "aktivite yeniden denemesi ai_call.id ile idempotent"): `call()` ve `run_agent()`
isteğe bağlı `call_id` alır (iş kimliği + adımdan `uuid5`, bkz. `deterministic_call_id`). Mantıksal
çağrının kök satırı bu kimlikle yazılır; diğer satırlar (şema yeniden istemleri, ajan turları,
çökme sonrası yeni deneme) `parent_call_id = call_id` taşır. Çağrıdan önce `CallLookup` ile aile
okunur: başarılı sonuç varsa sağlayıcı çağrılmaz, bütçe tekrar düşülmez, yeni satır yazılmaz ve
kayıtlı sonuç (kayıtlı mod ve token/maliyetle) döner.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from jsonschema import Draft202012Validator

from tp_core.gateway.budget import Budget
from tp_core.gateway.bundle import Bundle, load_bundle
from tp_core.gateway.canonical import canonical_json, input_hash, sha256_hex
from tp_core.gateway.config import EffectiveMode, ModelTable, PurposeConfig
from tp_core.gateway.errors import (
    AgentTurnLimit,
    BudgetExceeded,
    GatewayConfigError,
    ProviderNotConfigured,
    ProviderTransientError,
    SchemaValidationFailed,
)
from tp_core.gateway.masking import MaskingSession, PiiMasker
from tp_core.gateway.providers.base import (
    Provider,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
    Usage,
)
from tp_core.gateway.replay import ReplayStore, replay_key
from tp_core.ports import (
    AgentResult,
    AgentStep,
    CallRecorder,
    CallResult,
    ModelMessage,
    ToolExecutor,
    ToolSpec,
)

log = logging.getLogger(__name__)

FINAL_TOOL = "submit_result"
# Aşama başına araç İZİN listesi (anayasa "En az yetki"; TEKNIK-TASARIM §8.4, §8.2b). Birincil
# kontrol budur: listede olmayan her araç (MCP'nin yeni sürümlerinin eklediği araçlar dahil)
# reddedilir. Listesi olmayan amaç ajan olarak koşamaz.
ALLOWED_AGENT_TOOLS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        # §8.4 doğrulama ve eşleme: yalnızca gezinme, okuma ve form etkileşimi.
        "verify_and_map": frozenset(
            {
                "browser_navigate",
                "browser_snapshot",
                "browser_click",
                "browser_type",
                "browser_select_option",
                "browser_wait_for",
                "browser_generate_locator",
            }
        ),
        # §8.2b tutarlılık denetimi: GitHub MCP salt okuma (repos, code_search) + db araçlarımız.
        "consistency_check": frozenset(
            {"search_code", "get_file_contents", "db_schema", "db_query"}
        ),
    }
)
# İkinci kontrol: hiçbir aşamada verilemeyen araçlar (kod çalıştırma, dosya, ağ, ekran görüntüsü;
# TEKNIK-TASARIM §8.4, anayasa V). Playwright MCP bunları kapatmaya izin vermez; izin listesi
# yanlışlıkla genişletilse veya çağıran listeye koysa bile geçit reddeder.
FORBIDDEN_TOOLS = frozenset(
    {
        "browser_run_code_unsafe",
        "browser_run_code",
        "browser_evaluate",
        "browser_take_screenshot",
        "browser_file_upload",
        "browser_drop",  # yerel dosya yollarını sayfaya bırakır (dosya erişimi)
        "browser_network_request",
        "browser_network_requests",
        "browser_install",
        "browser_pdf_save",
    }
)
# İncelenmiş, zararsız ama §8.4 izin listesinde olmadığı için hiçbir aşamaya verilmeyen Playwright
# MCP araçları. Yalnızca sınıflandırma kaydıdır (izin listesi zaten reddeder); kayıtlı tools/list
# fikstürüyle test edilir: MCP yükseltmesi yeni araç eklerse test kırmızı olur ve araç bilinçli
# olarak izin listesine, yasak listesine veya buraya konur.
UNGRANTED_MCP_TOOLS = frozenset(
    {
        "browser_close",
        "browser_resize",
        "browser_console_messages",
        "browser_handle_dialog",
        "browser_emulate_media",
        "browser_find",
        "browser_fill_form",
        "browser_press_key",
        "browser_navigate_back",
        "browser_drag",
        "browser_hover",
        "browser_tabs",
        "browser_verify_element_visible",
        "browser_verify_text_visible",
        "browser_verify_list_visible",
        "browser_verify_value",
    }
)
REPLAY_SAVE_FAILED = "replay_kaydedilemedi"
_CALL_ID_NAMESPACE = uuid5(NAMESPACE_URL, "tp:ai_call")


def deterministic_call_id(job_id: UUID | str, step: str) -> UUID:
    """İş yeniden denemesinde aynı kalan çağrı kimliği (iş kimliği + adım adı)."""
    return uuid5(_CALL_ID_NAMESPACE, f"{job_id}:{step}")


@runtime_checkable
class CallLookup(Protocol):
    """Bir mantıksal çağrının `ai_call` satırları: `id = root_id` veya `parent_call_id = root_id`.

    Satır anahtarları `ai_call` kolonlarıdır (en az id, parent_call_id, amac, mod, cikti,
    sema_gecerli, hata, girdi_token, cikti_token, maliyet); yazım sırasıyla döner.
    """

    def find_ai_calls(self, root_id: UUID) -> list[Mapping[str, Any]]: ...


MAX_SCHEMA_REASKS = 2  # constitution III
DEFAULT_MAX_TOKENS = 4096  # ports.ModelGateway.call varsayılanı
SUMMARY_LIMIT = 500
ELIDED_SNAPSHOT = "[önceki sayfa snapshot'ı bağlamdan çıkarıldı; yalnızca son snapshot tutulur]"

AGENT_ADDENDUM = (
    "## Tool use protocol\n"
    "- Only the tools listed in this request exist. Calling any other tool is denied and logged.\n"
    f"- When you are done, call the `{FINAL_TOOL}` tool exactly once with the final result. Its "
    "input must match the result schema. Do not put the final result in plain text.\n"
    f"- If `{FINAL_TOOL}` returns a validation error, fix the listed problems and call it again."
)


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3  # 429/529/5xx için (ilk deneme hariç)
    base_delay_s: float = 1.0
    max_delay_s: float = 20.0

    def delay(self, attempt: int) -> float:
        return min(self.base_delay_s * (2**attempt), self.max_delay_s)


@dataclass(frozen=True)
class ReplayKeyInfo:
    """Bir çağrının birebir replay anahtarı ve bileşenleri (`replay.replay_key` ile aynı hesap)."""

    purpose: str
    key: str
    bundle_hash: str
    bundle_label: str
    model: str
    input_hash: str
    key_fields: dict[str, Any]


SnapshotPredicate = Callable[[str, str], bool]  # (araç adı, sonuç metni) -> snapshot mı


def default_is_snapshot(tool: str, text: str) -> bool:
    """Playwright MCP araçları eylemden sonra sayfa snapshot'ı döndürür."""
    return tool == "browser_snapshot" or "Page Snapshot" in text or "- Page Snapshot" in text


@dataclass
class _Turn:
    response: ProviderResponse
    results: list[tuple[ToolCall, str, bool]] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)


_EXTRA_KEYS = (
    "replay_kaynagi",
    "replay_kokeni",
    "sema_hatalari",
    "yeniden_deneme",
    "onbellek_okuma_token",
    "onbellek_yazma_token",
)


def _args_summary(args: Any, limit: int = 2000) -> Any:
    """Küçük argümanlar olduğu gibi (jsonb), büyükler kısaltılmış metin olarak yazılır."""
    return args if len(canonical_json(args)) <= limit else _summary(args, limit)


def _summary(value: Any, limit: int = SUMMARY_LIMIT) -> str:
    text = value if isinstance(value, str) else canonical_json(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _schema_errors(validator: Draft202012Validator, instance: Any) -> list[str]:
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    out = []
    for err in errors[:20]:
        path = "/".join(str(p) for p in err.absolute_path) or "(kök)"
        out.append(f"{path}: {err.message}")
    return out


def _parse_json(text: str) -> tuple[Any, str | None]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        candidate = candidate.split("\n", 1)[1] if "\n" in candidate else candidate
    try:
        return json.loads(candidate), None
    except json.JSONDecodeError as exc:
        return None, f"JSON ayrıştırılamadı: {exc.msg} (satır {exc.lineno}, sütun {exc.colno})"


class Gateway:
    """`ports.ModelGateway` uygulaması."""

    def __init__(
        self,
        *,
        provider: Provider | None,
        recorder: CallRecorder,
        mode: EffectiveMode,
        models: ModelTable,
        rules_dir: Path,
        budget: Budget | None = None,
        masker: PiiMasker | None = None,
        replay_store: ReplayStore | None = None,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        is_snapshot: SnapshotPredicate = default_is_snapshot,
        replay_executes_tools: bool = True,
        record_extras: bool = False,
        call_lookup: CallLookup | None = None,
        agent_tools: Mapping[str, Collection[str]] | None = None,
    ) -> None:
        if mode in ("live", "record") and provider is None:
            raise ProviderNotConfigured(f"'{mode}' modu için sağlayıcı gerekli")
        self.provider = provider
        self.recorder = recorder
        self.mode: EffectiveMode = mode
        self.models = models
        self.rules_dir = Path(rules_dir)
        self.budget = budget or Budget()
        self.masker = masker or PiiMasker(enabled=False)
        self.replay_store = replay_store or ReplayStore(self.rules_dir / "replay")
        self.retry = retry or RetryPolicy()
        self._sleep = sleep
        self._clock = clock
        self._is_snapshot = is_snapshot
        self.replay_executes_tools = replay_executes_tools
        self.record_extras = record_extras
        if call_lookup is None and isinstance(recorder, CallLookup):
            call_lookup = recorder
        self.call_lookup = call_lookup
        table = ALLOWED_AGENT_TOOLS if agent_tools is None else agent_tools
        self.agent_tools: dict[str, frozenset[str]] = {p: frozenset(n) for p, n in table.items()}
        for purpose_name, names in self.agent_tools.items():
            bad = sorted(names & FORBIDDEN_TOOLS)
            if bad:
                raise GatewayConfigError(
                    f"'{purpose_name}' izin listesinde yasak araç: {', '.join(bad)}"
                )
        self._sessions: dict[UUID, MaskingSession] = {}
        self._bundles: dict[tuple[str, str, str], Bundle] = {}

    # ---------------------------------------------------------------- yardımcılar

    @property
    def provider_name(self) -> str:
        return self.provider.name if self.provider is not None else "replay"

    def masking_session(self, workflow_id: UUID | None) -> MaskingSession:
        """Eşleme iş akışı kapsamında saklanır (§8.9); iş akışı yoksa çağrıya özel oturum."""
        if workflow_id is None:
            return self.masker.new_session()
        session = self._sessions.get(workflow_id)
        if session is None:
            session = self._sessions[workflow_id] = self.masker.new_session()
        return session

    def bundle(self, name: str, schema: Mapping[str, Any], cfg: PurposeConfig) -> Bundle:
        cache_key = (name, cfg.name, sha256_hex(canonical_json(schema)))
        cached = self._bundles.get(cache_key)
        if cached is None:
            cached = self._bundles[cache_key] = load_bundle(self.rules_dir, name, dict(schema), cfg)
        return cached

    def _estimate_input_cost(self, cfg: PurposeConfig, system: str, messages: Any) -> float:
        approx_tokens = (len(system) + len(canonical_json(messages))) // 4
        return self.models.cost(cfg.model, Usage(input_tokens=approx_tokens))

    def _complete(self, request: ProviderRequest) -> tuple[ProviderResponse, int]:
        assert self.provider is not None
        attempt = 0
        while True:
            try:
                return self.provider.complete(request), attempt
            except ProviderTransientError:
                if attempt >= self.retry.max_retries:
                    raise
                self._sleep(self.retry.delay(attempt))
                attempt += 1

    def _base_row(
        self,
        *,
        purpose: str,
        bundle: Bundle,
        cfg: PurposeConfig,
        workflow_id: UUID | None,
        parent_id: UUID | None,
        mode: str,
        key: str,
        row_id: UUID | None = None,
    ) -> dict[str, Any]:
        return {
            "id": row_id or uuid4(),
            "parent_call_id": parent_id,
            "workflow_id": workflow_id,
            "amac": purpose,
            "saglayici": self.provider_name if mode == "live" else "replay",
            "model": cfg.model,
            "surum": bundle.label,
            "bundle_hash": bundle.hash,
            "replay": mode,
            "replay_anahtari": key,
        }

    def _record(self, row: dict[str, Any]) -> UUID:
        """İç satırı `ai_call` kolonlarına çevirir; kolonu olmayan alanlar `ek`e gider."""
        extras = {k: row.pop(k) for k in _EXTRA_KEYS if k in row}
        row["mod"] = row.pop("replay")
        row["maliyet"] = row.pop("maliyet_usd", 0.0)
        schema_errors = extras.get("sema_hatalari")
        if schema_errors and not row.get("hata"):
            row["hata"] = "şema: " + "; ".join(schema_errors)
        if self.record_extras:
            row["ek"] = extras
        return self.recorder.record_ai_call(row)

    def _prior(self, call_id: UUID | None) -> list[Mapping[str, Any]]:
        if call_id is None:
            return []
        if self.call_lookup is None:
            log.warning(
                "call_id=%s verildi ama CallLookup yok; idempotency yalnızca satır düzeyinde",
                call_id,
            )
            return []
        return list(self.call_lookup.find_ai_calls(call_id))

    def _save_replay(self, purpose: str, key: str, record: dict[str, Any]) -> str | None:
        """record modu: kaydı yazar. Hata ölümcül değildir (ücretli canlı sonuç kaybolmasın)."""
        try:
            self.replay_store.save(purpose, key, record)
        except OSError as exc:
            log.error("replay kaydı yazılamadı (%s, %s): %s", purpose, key[:12], exc)
            return f"{REPLAY_SAVE_FAILED}: {type(exc).__name__}: {exc}"
        return None

    def _key_material(
        self,
        purpose: str,
        cfg: PurposeConfig,
        bundle: str,
        bundle_schema: Mapping[str, Any],
        messages: Sequence[ModelMessage],
        replay_key_fields: Mapping[str, Any],
        workflow_id: UUID | None,
    ) -> tuple[Bundle, MaskingSession, Any, dict[str, Any], str, str]:
        """call/run_agent ve golden yükseltme (`promote`) için TEK anahtar hesabı."""
        bnd = self.bundle(bundle, bundle_schema, cfg)
        session = self.masking_session(workflow_id)
        raw_messages = [m.model_dump(mode="json") for m in messages]
        masked, hits = session.mask(raw_messages)
        mask_diff = session.diff(hits)
        digest = input_hash(masked)
        key = _replay_key(purpose, bnd.hash, replay_key_fields, digest)
        return bnd, session, masked, mask_diff, digest, key

    def replay_key_for_call(
        self,
        purpose: str,
        bundle: str,
        messages: Sequence[ModelMessage],
        schema: dict[str, Any],
        *,
        replay_key: Mapping[str, Any],
        workflow_id: UUID | None = None,
    ) -> ReplayKeyInfo:
        """`call()` aynı girdiyle hangi birebir replay anahtarını arardı (çağrı yapmaz, yazmaz)."""
        cfg = self.models.purpose(purpose)
        bnd, _, _, _, digest, key = self._key_material(
            purpose, cfg, bundle, schema, messages, replay_key, workflow_id
        )
        return ReplayKeyInfo(purpose, key, bnd.hash, bnd.label, cfg.model, digest, dict(replay_key))

    def replay_key_for_agent(
        self,
        purpose: str,
        bundle: str,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec],
        output_schema: dict[str, Any],
        *,
        replay_key: Mapping[str, Any],
        workflow_id: UUID | None = None,
    ) -> ReplayKeyInfo:
        """`run_agent()` aynı girdiyle hangi birebir replay anahtarını arardı."""
        self._check_agent_tools(purpose, tools)
        cfg = self.models.purpose(purpose)
        bnd, _, _, _, digest, key = self._key_material(
            purpose,
            cfg,
            bundle,
            _agent_bundle_schema(output_schema, tools),
            messages,
            replay_key,
            workflow_id,
        )
        return ReplayKeyInfo(purpose, key, bnd.hash, bnd.label, cfg.model, digest, dict(replay_key))

    def _check_agent_tools(self, purpose: str, tools: Sequence[ToolSpec]) -> None:
        names = {t.name for t in tools}
        if FINAL_TOOL in names:
            raise GatewayConfigError(f"'{FINAL_TOOL}' adı son çıktı aracına ayrılmıştır")
        forbidden = sorted(names & FORBIDDEN_TOOLS)
        if forbidden:
            raise GatewayConfigError(f"Ajana verilemeyen araç: {', '.join(forbidden)}")
        permitted = self.agent_tools.get(purpose)
        if permitted is None:
            raise GatewayConfigError(
                f"'{purpose}' için araç izin listesi yok; bu amaç ajan olarak koşamaz"
            )
        outside = sorted(names - permitted)
        if outside:
            raise GatewayConfigError(
                f"'{purpose}' araç izin listesinde olmayan araç: {', '.join(outside)}"
            )

    # ---------------------------------------------------------------- call

    def call(
        self,
        purpose: str,
        bundle: str,
        messages: Sequence[ModelMessage],
        schema: dict[str, Any],
        *,
        replay_key: Mapping[str, Any],
        max_tokens: int = 4096,
        workflow_id: UUID | None = None,
        call_id: UUID | None = None,
    ) -> CallResult:
        cfg = self.models.purpose(purpose)
        bnd, session, masked, mask_diff, digest, key = self._key_material(
            purpose, cfg, bundle, schema, messages, replay_key, workflow_id
        )
        validator = Draft202012Validator(schema)

        prior = self._prior(call_id)
        done = _completed_call(prior, purpose)
        if done is not None:
            return _call_result_from(done, prior, session)
        root_id = call_id if call_id is not None and not _has_id(prior, call_id) else None

        if self.mode == "replay":
            return self._replay_call(
                purpose,
                bnd,
                cfg,
                validator,
                session,
                masked,
                mask_diff,
                key,
                replay_key,
                workflow_id,
                root_id=root_id,
                parent_id=call_id if root_id is None else None,
            )

        conversation: list[dict[str, Any]] = list(masked)
        # Protokol varsayılanı (4096) gelirse amaç ayarı (models.yaml) geçerlidir.
        effective_max = cfg.max_tokens if max_tokens == DEFAULT_MAX_TOKENS else max_tokens
        first_id: UUID | None = call_id if root_id is None else None
        totals = Usage()
        total_cost = 0.0
        errors: list[str] = []
        output: Any = None
        for attempt in range(1, MAX_SCHEMA_REASKS + 2):
            self.budget.check(
                workflow_id, self._estimate_input_cost(cfg, bnd.system_prompt, conversation)
            )
            request = ProviderRequest(
                model=cfg.model,
                system=bnd.system_prompt,
                messages=conversation,
                max_tokens=effective_max,
                output_schema=schema,
                params=cfg.params,
            )
            row = self._base_row(
                purpose=purpose,
                bundle=bnd,
                cfg=cfg,
                workflow_id=workflow_id,
                parent_id=first_id,
                mode="live",
                key=key,
                row_id=root_id if attempt == 1 else None,
            )
            row.update(
                maskeli_girdi=conversation if attempt == 1 else conversation[-2:],
                maskeleme_farki=mask_diff,
                deneme=attempt,
            )
            started = self._clock()
            try:
                response, retries = self._complete(request)
            except Exception as exc:
                row.update(
                    cikti=None,
                    sema_gecerli=False,
                    hata=f"{type(exc).__name__}: {exc}",
                    sure_ms=int((self._clock() - started) * 1000),
                    maliyet_usd=0.0,
                )
                self._record(row)
                raise
            cost = self.models.cost(cfg.model, response.usage)
            self.budget.charge(workflow_id, cost)
            total_cost += cost
            totals = _add_usage(totals, response.usage)
            output, parse_error = _parse_json(response.text)
            errors = [parse_error] if parse_error else _schema_errors(validator, output)
            row.update(
                cikti=output if parse_error is None else response.text,
                sema_gecerli=not errors,
                sema_hatalari=errors,
                yeniden_deneme=retries,
                girdi_token=response.usage.input_tokens,
                cikti_token=response.usage.output_tokens,
                onbellek_okuma_token=response.usage.cache_read_tokens,
                onbellek_yazma_token=response.usage.cache_write_tokens,
                maliyet_usd=cost,
                sure_ms=int((self._clock() - started) * 1000),
                hata=None,
            )
            if not errors and self.mode == "record":
                row["hata"] = self._save_replay(
                    purpose,
                    key,
                    {
                        "kind": "call",
                        "purpose": purpose,
                        "bundle": bnd.label,
                        "bundle_hash": bnd.hash,
                        "model": cfg.model,
                        "replay_key": dict(replay_key),
                        "input_hash": digest,
                        "output": output,
                    },
                )
            row_id = self._record(row)
            first_id = first_id or row_id
            if not errors:
                return CallResult(
                    output=session.unmask(output),
                    call_id=row_id,
                    mode="live",
                    input_tokens=totals.input_tokens,
                    output_tokens=totals.output_tokens,
                    cost_usd=round(total_cost, 6),
                )
            conversation = [
                *conversation,
                {"role": "assistant", "content": response.text or "(boş yanıt)"},
                {"role": "user", "content": _reask_text(errors)},
            ]
        raise SchemaValidationFailed(
            f"'{purpose}' çıktısı {MAX_SCHEMA_REASKS} yeniden istemeden sonra da şemaya uymadı",
            errors=errors,
            last_output=output,
        )

    def _replay_call(
        self,
        purpose: str,
        bnd: Bundle,
        cfg: PurposeConfig,
        validator: Draft202012Validator,
        session: MaskingSession,
        masked: Any,
        mask_diff: dict[str, Any],
        key: str,
        key_fields: Mapping[str, Any],
        workflow_id: UUID | None,
        *,
        root_id: UUID | None = None,
        parent_id: UUID | None = None,
    ) -> CallResult:
        record, mode, path = self.replay_store.lookup(purpose, key, _golden_name(key_fields))
        output = record["output"]
        errors = _schema_errors(validator, output)
        row = self._base_row(
            purpose=purpose,
            bundle=bnd,
            cfg=cfg,
            workflow_id=workflow_id,
            parent_id=parent_id,
            mode=mode,
            key=key,
            row_id=root_id,
        )
        row.update(
            replay_kaynagi=str(path.relative_to(self.replay_store.root)),
            replay_kokeni=_provenance(record, mode),
            maskeli_girdi=masked,
            maskeleme_farki=mask_diff,
            cikti=output,
            sema_gecerli=not errors,
            sema_hatalari=errors,
            deneme=1,
            yeniden_deneme=0,
            girdi_token=0,
            cikti_token=0,
            maliyet_usd=0.0,
            sure_ms=0,
            hata=None,
        )
        row_id = self._record(row)
        if errors:
            raise SchemaValidationFailed(
                f"replay kaydı şemaya uymuyor: {path}", errors=errors, last_output=output
            )
        return CallResult(output=session.unmask(output), call_id=row_id, mode=mode)

    # ---------------------------------------------------------------- run_agent

    def run_agent(
        self,
        purpose: str,
        bundle: str,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec],
        execute: ToolExecutor,
        output_schema: dict[str, Any],
        *,
        replay_key: Mapping[str, Any],
        max_turns: int = 25,
        workflow_id: UUID | None = None,
        on_step: Callable[[AgentStep], None] | None = None,
        is_snapshot: SnapshotPredicate | None = None,
        call_id: UUID | None = None,
    ) -> AgentResult:
        self._check_agent_tools(purpose, tools)
        cfg = self.models.purpose(purpose)
        bnd, session, masked, mask_diff, digest, key = self._key_material(
            purpose,
            cfg,
            bundle,
            _agent_bundle_schema(output_schema, tools),
            messages,
            replay_key,
            workflow_id,
        )
        validator = Draft202012Validator(output_schema)
        allowed = {t.name for t in tools}

        prior = self._prior(call_id)
        done = _completed_agent(prior, purpose, validator)
        if done is not None:
            output, mode = done
            return AgentResult(
                output=session.unmask(output),
                steps=[],
                call_ids=[r["id"] for r in prior],
                mode=mode,
            )
        root_id = call_id if call_id is not None and not _has_id(prior, call_id) else None

        if self.mode == "replay":
            return self._replay_agent(
                purpose,
                bnd,
                cfg,
                validator,
                session,
                masked,
                mask_diff,
                key,
                replay_key,
                workflow_id,
                allowed,
                execute,
                on_step,
                root_id=root_id,
                parent_id=call_id if root_id is None else None,
            )

        snapshot = is_snapshot or self._is_snapshot
        final_tool = ToolSpec(
            name=FINAL_TOOL,
            description="Görevi bitirdiğinde son sonucu bu araçla ver (sonuç şemasına uymalı).",
            input_schema=output_schema,
        )
        system = f"{bnd.system_prompt}\n\n{AGENT_ADDENDUM}"
        turns: list[_Turn] = []
        steps: list[AgentStep] = []
        call_ids: list[UUID] = []
        first_id: UUID | None = call_id if root_id is None else None
        schema_failures = 0
        used_input_tokens = 0
        last_errors: list[str] = []
        last_output: Any = None

        for turn_no in range(1, max_turns + 1):
            conversation = self._agent_messages(masked, turns, snapshot)
            self.budget.check(workflow_id, self._estimate_input_cost(cfg, system, conversation))
            if cfg.max_input_tokens and used_input_tokens >= cfg.max_input_tokens:
                raise BudgetExceeded(
                    "ajan girdi token'ı", float(used_input_tokens), float(cfg.max_input_tokens)
                )
            request = ProviderRequest(
                model=cfg.model,
                system=system,
                messages=conversation,
                max_tokens=cfg.max_tokens,
                tools=[*tools, final_tool],
                params=cfg.params,
            )
            row = self._base_row(
                purpose=purpose,
                bundle=bnd,
                cfg=cfg,
                workflow_id=workflow_id,
                parent_id=first_id,
                mode="live",
                key=key,
                row_id=root_id if turn_no == 1 else None,
            )
            row.update(
                maskeli_girdi=masked if turn_no == 1 else _last_results(turns),
                maskeleme_farki=mask_diff,
                deneme=turn_no,
            )
            started = self._clock()
            try:
                response, retries = self._complete(request)
            except Exception as exc:
                row.update(
                    cikti=None,
                    sema_gecerli=False,
                    hata=f"{type(exc).__name__}: {exc}",
                    sure_ms=int((self._clock() - started) * 1000),
                    maliyet_usd=0.0,
                )
                self._record(row)
                raise
            cost = self.models.cost(cfg.model, response.usage)
            self.budget.charge(workflow_id, cost)
            used_input_tokens += (
                response.usage.input_tokens
                + response.usage.cache_read_tokens
                + response.usage.cache_write_tokens
            )
            row.update(
                cikti={
                    "text": response.text,
                    "tool_calls": [c.model_dump() for c in response.tool_calls],
                    "stop_reason": response.stop_reason,
                },
                sema_gecerli=True,
                yeniden_deneme=retries,
                girdi_token=response.usage.input_tokens,
                cikti_token=response.usage.output_tokens,
                onbellek_okuma_token=response.usage.cache_read_tokens,
                onbellek_yazma_token=response.usage.cache_write_tokens,
                maliyet_usd=cost,
                sure_ms=int((self._clock() - started) * 1000),
                hata=None,
            )
            row_id = self._record(row)
            first_id = first_id or row_id
            call_ids.append(row_id)
            turn = _Turn(response=response)
            turns.append(turn)

            if not response.tool_calls:
                nudge = ToolCall(id="", name="", args={})
                turn.results.append(
                    (nudge, f"Sonucu `{FINAL_TOOL}` aracıyla ver; düz metin kabul edilmez.", True)
                )
                turn.tool_names.append("")
                continue

            final_output: Any = None
            final_ok = False
            for tc in response.tool_calls:
                if tc.name == FINAL_TOOL:
                    if final_ok:
                        result, is_error = "Sonuç zaten kabul edildi.", False
                    else:
                        errs = _schema_errors(validator, tc.args)
                        if errs:
                            schema_failures += 1
                            last_errors, last_output = errs, tc.args
                            result, is_error = _reask_text(errs), True
                        else:
                            final_ok, final_output = True, tc.args
                            result, is_error = "Sonuç kabul edildi.", False
                    self._record_tool(row_id, tc.name, tc.args, result, allowed_flag=True)
                elif tc.name not in allowed:
                    result = f"Araç izinli değil: {tc.name}. İzinli araçlar: {sorted(allowed)}"
                    is_error = True
                    step = AgentStep(
                        tool=tc.name, args=tc.args, result_summary=_summary(result), allowed=False
                    )
                    steps.append(step)
                    self._record_tool(row_id, tc.name, tc.args, result, allowed_flag=False)
                    if on_step:
                        on_step(step)
                else:
                    result, is_error = self._execute(execute, tc.name, session.unmask(tc.args))
                    result, _ = session.mask(result) if self._mask_tool_results else (result, [])
                    step = AgentStep(
                        tool=tc.name, args=tc.args, result_summary=_summary(result), allowed=True
                    )
                    steps.append(step)
                    self._record_tool(row_id, tc.name, tc.args, result, allowed_flag=True)
                    if on_step:
                        on_step(step)
                turn.results.append((tc, result, is_error))
                turn.tool_names.append(tc.name)

            if final_ok:
                if self.mode == "record":
                    failure = self._save_replay(
                        purpose,
                        key,
                        {
                            "kind": "agent",
                            "purpose": purpose,
                            "bundle": bnd.label,
                            "bundle_hash": bnd.hash,
                            "model": cfg.model,
                            "replay_key": dict(replay_key),
                            "input_hash": digest,
                            "output": final_output,
                            "steps": [s.model_dump() for s in steps],
                        },
                    )
                    if failure:
                        # Tur satırı zaten yazıldı (append-only); iz tool_call olarak kalır.
                        self._record_tool(row_id, "replay_kaydet", {}, failure, allowed_flag=True)
                return AgentResult(
                    output=session.unmask(final_output),
                    steps=steps,
                    call_ids=call_ids,
                    mode="live",
                )
            if schema_failures > MAX_SCHEMA_REASKS:
                raise SchemaValidationFailed(
                    f"'{purpose}' ajan sonucu {MAX_SCHEMA_REASKS} düzeltme isteğinden sonra da "
                    "şemaya uymadı",
                    errors=last_errors,
                    last_output=last_output,
                )
        raise AgentTurnLimit(f"'{purpose}' ajanı {max_turns} turda sonuç vermedi")

    # Gateway politikası: araç sonuçları (snapshot, kod) maskelenmez (§8.9); veri sorgusu
    # sonuçlarını maskelemek aracın sorumluluğudur (gateway.masking_session ile).
    _mask_tool_results = False

    def _agent_messages(
        self, initial: list[dict[str, Any]], turns: list[_Turn], is_snapshot: SnapshotPredicate
    ) -> list[dict[str, Any]]:
        """Sohbeti her tur yeniden kurar; yalnızca son snapshot bağlamda kalır (§8.4)."""
        assert self.provider is not None
        last_snapshot: tuple[int, int] | None = None
        for ti, turn in enumerate(turns):
            for ri, (_, text, is_error) in enumerate(turn.results):
                if not is_error and is_snapshot(turn.tool_names[ri], text):
                    last_snapshot = (ti, ri)
        conversation = list(initial)
        for ti, turn in enumerate(turns):
            conversation.append(self.provider.assistant_message(turn.response))
            calls = [(c, t, e) for c, t, e in turn.results if c.id]
            nudges = [t for c, t, _ in turn.results if not c.id]
            if calls:
                rendered = []
                for ri, (call, text, is_error) in enumerate(turn.results):
                    if not call.id:
                        continue
                    if (
                        not is_error
                        and is_snapshot(turn.tool_names[ri], text)
                        and (ti, ri) != last_snapshot
                    ):
                        text = ELIDED_SNAPSHOT
                    rendered.append((call, text, is_error))
                conversation.append(self.provider.tool_result_message(rendered))
            if nudges:
                conversation.append({"role": "user", "content": "\n".join(nudges)})
        return conversation

    @staticmethod
    def _execute(execute: ToolExecutor, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        try:
            return str(execute(name, args)), False
        except Exception as exc:
            return f"Araç hatası ({type(exc).__name__}): {exc}", True

    def _record_tool(
        self, ai_call_id: UUID, tool: str, args: Any, result: str, *, allowed_flag: bool
    ) -> UUID:
        return self.recorder.record_tool_call(
            {
                "id": uuid4(),
                "ai_call_id": ai_call_id,
                "kanal": "agent",
                "cagiran_user_id": None,
                "arac": tool,
                "arguman_ozeti": _args_summary(args),
                "sonuc_ozeti": _summary(result),
                "izin_verildi": allowed_flag,
            }
        )

    def _replay_agent(
        self,
        purpose: str,
        bnd: Bundle,
        cfg: PurposeConfig,
        validator: Draft202012Validator,
        session: MaskingSession,
        masked: Any,
        mask_diff: dict[str, Any],
        key: str,
        key_fields: Mapping[str, Any],
        workflow_id: UUID | None,
        allowed: set[str],
        execute: ToolExecutor,
        on_step: Callable[[AgentStep], None] | None,
        *,
        root_id: UUID | None = None,
        parent_id: UUID | None = None,
    ) -> AgentResult:
        record, mode, path = self.replay_store.lookup(purpose, key, _golden_name(key_fields))
        output = record["output"]
        errors = _schema_errors(validator, output)
        row = self._base_row(
            purpose=purpose,
            bundle=bnd,
            cfg=cfg,
            workflow_id=workflow_id,
            parent_id=parent_id,
            mode=mode,
            key=key,
            row_id=root_id,
        )
        row.update(
            replay_kaynagi=str(path.relative_to(self.replay_store.root)),
            replay_kokeni=_provenance(record, mode),
            maskeli_girdi=masked,
            maskeleme_farki=mask_diff,
            cikti=output,
            sema_gecerli=not errors,
            sema_hatalari=errors,
            deneme=1,
            yeniden_deneme=0,
            girdi_token=0,
            cikti_token=0,
            maliyet_usd=0.0,
            sure_ms=0,
            hata=None,
        )
        row_id = self._record(row)
        if errors:
            raise SchemaValidationFailed(
                f"replay kaydı şemaya uymuyor: {path}", errors=errors, last_output=output
            )
        steps: list[AgentStep] = []
        for raw in record.get("steps") or []:
            recorded = AgentStep.model_validate(raw)
            # İzin listesi replay'de de geçerlidir: kayıtta olsa bile listede olmayan araç koşmaz.
            is_allowed = recorded.allowed and recorded.tool in allowed
            summary = recorded.result_summary
            if is_allowed and self.replay_executes_tools:
                result, _ = self._execute(execute, recorded.tool, session.unmask(recorded.args))
                summary = _summary(result)
            elif not is_allowed:
                summary = f"Araç izinli değil: {recorded.tool}"
            step = AgentStep(
                tool=recorded.tool, args=recorded.args, result_summary=summary, allowed=is_allowed
            )
            steps.append(step)
            self._record_tool(row_id, step.tool, step.args, summary, allowed_flag=is_allowed)
            if on_step:
                on_step(step)
        return AgentResult(output=session.unmask(output), steps=steps, call_ids=[row_id], mode=mode)


# -------------------------------------------------------------------- yardımcılar


def _replay_key(purpose: str, bundle_hash: str, fields: Mapping[str, Any], digest: str) -> str:
    return replay_key(purpose, bundle_hash, fields, digest)


def _agent_bundle_schema(output_schema: Mapping[str, Any], tools: Sequence[ToolSpec]) -> dict:
    """Ajan bundle hash'ine çıktı şeması ve araç tanımları (ad, açıklama, girdi şeması) girer."""
    return {"output": output_schema, "tools": [t.model_dump() for t in tools]}


def _provenance(record: Mapping[str, Any], mode: str) -> str:
    """Replay kaynağının kökeni (ai_call.ek): canlı kayıt, golden yedeği, yükseltilmiş golden."""
    if mode == "replay_miss":
        return "golden"
    return str(record.get("provenance") or "recorded")


def _has_id(rows: Sequence[Mapping[str, Any]], row_id: UUID) -> bool:
    return any(_as_uuid(r.get("id")) == row_id for r in rows)


def _as_uuid(value: Any) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    return UUID(str(value))


def _row_ok(row: Mapping[str, Any]) -> bool:
    hata = row.get("hata")
    return (
        bool(row.get("sema_gecerli"))
        and row.get("cikti") is not None
        and (not hata or str(hata).startswith(REPLAY_SAVE_FAILED))
    )


def _completed_call(rows: Sequence[Mapping[str, Any]], purpose: str) -> Mapping[str, Any] | None:
    for row in reversed(rows):
        if row.get("amac") == purpose and _row_ok(row):
            return row
    return None


def _call_result_from(
    done: Mapping[str, Any], family: Sequence[Mapping[str, Any]], session: MaskingSession
) -> CallResult:
    return CallResult(
        output=session.unmask(done["cikti"]),
        call_id=_as_uuid(done["id"]),
        mode=done["mod"],
        input_tokens=sum(int(r.get("girdi_token") or 0) for r in family),
        output_tokens=sum(int(r.get("cikti_token") or 0) for r in family),
        cost_usd=round(sum(float(r.get("maliyet") or 0) for r in family), 6),
    )


def _completed_agent(
    rows: Sequence[Mapping[str, Any]], purpose: str, validator: Draft202012Validator
) -> tuple[Any, str] | None:
    """Tamamlanmış ajan: replay satırının çıktısı veya geçerli `submit_result` argümanı."""
    for row in reversed(rows):
        if row.get("amac") != purpose or not _row_ok(row):
            continue
        cikti = row["cikti"]
        if row.get("mod") != "live":
            return cikti, row["mod"]
        calls = cikti.get("tool_calls") if isinstance(cikti, Mapping) else None
        for call in reversed(calls or []):
            if call.get("name") == FINAL_TOOL and not _schema_errors(validator, call.get("args")):
                return call["args"], "live"
    return None


def _golden_name(fields: Mapping[str, Any]) -> str | None:
    name = fields.get("name")
    return str(name) if name else None


def _add_usage(a: Usage, b: Usage) -> Usage:
    return Usage(
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        cache_read_tokens=a.cache_read_tokens + b.cache_read_tokens,
        cache_write_tokens=a.cache_write_tokens + b.cache_write_tokens,
    )


def _reask_text(errors: list[str]) -> str:
    listed = "\n".join(f"- {e}" for e in errors)
    return (
        "Your previous output did not match the required JSON schema. Errors:\n"
        f"{listed}\n"
        "Respond again with only a JSON value that satisfies the schema."
    )


def _last_results(turns: list[_Turn]) -> list[dict[str, Any]]:
    if not turns:
        return []
    return [
        {"tool": name, "result": _summary(text), "is_error": is_error}
        for name, (_, text, is_error) in zip(turns[-1].tool_names, turns[-1].results, strict=True)
    ]
