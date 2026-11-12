"""Model geçidi çekirdeği: `ports.ModelGateway` uygulaması (TEKNIK-TASARIM §8.8).

Sağlayıcıdan bağımsızdır; sağlayıcıya özgü her şey `providers/` altındadır.

`CallRecorder.record_ai_call` satırı; anahtarlar `ai_call` kolonlarıdır (tp_core.audit.recorder):
    id, parent_call_id, workflow_id, amac, saglayici, model, surum (bundle id@sürüm), bundle_hash,
    maskeli_girdi, cikti, sema_gecerli, deneme, girdi_token, cikti_token, maliyet (USD), sure_ms,
    mod ('live'|'replay'|'replay_miss'), replay_anahtari, hata (şema hataları dahil),
    maskeleme_farki
    `record_extras=True` ise ayrıca `ek` (jsonb): replay_kaynagi, replay_kokeni (recorded |
    golden_promoted | golden_matched | golden | miss_neutral), cikti_kokeni (model_kaydi |
    elle_hazirlanmis | notr_yedek), replay_eslesme (REPLAY-MISS'te golden'ın girdi
    beyanıyla uyuşmazlıklar), sema_hatalari, yeniden_deneme,
    onbellek_okuma_token, onbellek_yazma_token. Kolon eklenene kadar varsayılan kapalı.
    Replay satırında `model` çıktıyı GERÇEKTEN üreten modeldir: kayıt üst verisi olmayan
    (elle hazırlanmış golden, nötr yedek) çıktıda `HAND_PREPARED_MODEL` ("golden-elle").
`record_tool_call` satırı:
    id, ai_call_id, kanal ('agent' | `run_agent(tool_channel=)`, ör. 'asistan'), cagiran_user_id
    (`run_agent(caller_user_id=)`), arac, arguman_ozeti (jsonb), sonuc_ozeti, izin_verildi
`run_agent(ek=)` verilirse çağıranın alanları (ör. asistan `kullanici_id`) ajanın her `ai_call`
satırının `ek`ine yazılır; geçidin kendi `ek` alanları çakışmada önceliklidir.

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
import re
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
    AgentDeadlineExceeded,
    AgentStopped,
    AgentTurnLimit,
    BudgetExceeded,
    GatewayConfigError,
    ProviderNotConfigured,
    ProviderPermanentError,
    ProviderRefusal,
    ProviderTransientError,
    ReplayNotFound,
    SchemaValidationFailed,
)
from tp_core.gateway.evaluation import evaluation_summary
from tp_core.gateway.masking import (
    MaskingSession,
    PiiMasker,
    mask_tool_args,
    scrub_secrets,
    scrub_secrets_in,
    secret_tool_values,
)
from tp_core.gateway.providers.base import (
    Provider,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
    Usage,
)
from tp_core.gateway.replay import (
    HAND_PREPARED_MODEL,
    ReplayMode,
    ReplayStore,
    output_origin,
    replay_key,
)
from tp_core.gateway.snapshot_refs import (
    APP_GENERATE_LOCATOR,
    APP_SNAPSHOT_TOOL,
    SNAPSHOT_TOOL,
    Hedef,
    app_locator,
    is_inline_snapshot,
    locate_ref,
    ref_arg,
    snapshot_lines,
    strip_mcp_file_links,
)
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
# Asistan araçları (§5.1–5.3, 5.6, 5.7): ürün paketi, probe verisi, canlı Jira okuma, CI logu ve
# test edilen uygulamanın mevcut kod/veri araçları. Hepsi salt okumadır.
ASSISTANT_TOOLS = frozenset(
    {
        "product_search",
        "product_read",
        "probe_get",
        "probe_list",
        "probe_jobs",
        "probe_audit",
        "probe_my_queue",
        "jira_issue",
        "ci_log",
        "search_code",
        "get_file_contents",
        "db_schema",
        "db_query",
    }
)
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
        # 009 §2.6 mobil/masaüstü doğrulama ve eşleme: app-mcp (Appium) araçlarının Playwright
        # MCP eşleri; `app_screenshot` yalnız çekirdeğin canlı görünüm kanalıdır (FORBIDDEN_TOOLS).
        "verify_and_map_app": frozenset(
            {
                "app_launch",
                "app_snapshot",
                "app_click",
                "app_type",
                "app_select_option",
                "app_wait_for",
                "app_generate_locator",
            }
        ),
        # §8.2b tutarlılık denetimi: GitHub MCP salt okuma (repos, code_search) + db araçlarımız.
        "consistency_check": frozenset(
            {"search_code", "get_file_contents", "db_schema", "db_query"}
        ),
        # Portal asistanı (AI-ASISTAN-PLANI §5): iki kademe aynı salt okuma araç listesini görür;
        # rol kısıtı araç uygulamasındadır (iş yükündeki kullanıcı/rol, asla argüman).
        "assistant": ASSISTANT_TOOLS,
        "assistant_deep": ASSISTANT_TOOLS,
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
        # app-mcp (009 §2.6): ekran görüntüsü yalnız çekirdeğin model dışı canlı görünüm kanalıdır;
        # ajan erişilebilirlik ağacıyla çalışır (anayasa V).
        "app_screenshot",
    }
)
# Verilen araçların bile hiçbir zaman sunulmayan/kabul edilmeyen argümanları (en az yetki,
# anayasa V). `filename`: Playwright MCP sonucu modele döndürmek yerine MCP çalışma alanına dosya
# YAZAR (browser_snapshot dahil); `boxes`: snapshot'a piksel koordinatları ekler (görsel düzen
# bilgisi; ajan role/ad ile çalışır). Şemadan çıkarılır (model görmez) ve çağrıda gelirse araç
# çalıştırılmadan reddedilir (canlı ve replay). Kayıtlı tools/list fikstürüyle test edilir.
FORBIDDEN_TOOL_ARGS = frozenset({"filename"})
RESTRICTED_TOOL_ARGS: Mapping[str, frozenset[str]] = MappingProxyType(
    {"browser_snapshot": frozenset({"filename", "boxes"})}
)


def restricted_args(tool: str) -> frozenset[str]:
    """`tool` için şemadan çıkarılan ve çağrıda reddedilen argüman adları."""
    return FORBIDDEN_TOOL_ARGS | RESTRICTED_TOOL_ARGS.get(tool, frozenset())


def narrow_tool(spec: ToolSpec) -> ToolSpec:
    """Girdi şemasından yasak argümanları (`properties` ve `required`) çıkarır (kopya)."""
    banned = restricted_args(spec.name)
    schema = dict(spec.input_schema or {})
    props = schema.get("properties")
    if not isinstance(props, Mapping) or not banned & set(props):
        return spec
    schema["properties"] = {k: v for k, v in props.items() if k not in banned}
    if isinstance(schema.get("required"), list):
        schema["required"] = [r for r in schema["required"] if r not in banned]
    return spec.model_copy(update={"input_schema": schema})


def _banned_args(tool: str, args: Any) -> list[str]:
    return sorted(set(args) & restricted_args(tool)) if isinstance(args, Mapping) else []


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
# İç satırda çağıranın `ek` alanlarını taşıyan anahtar (`_record` `ek` jsonb'sine birleştirir).
_CALLER_EK = "_cagiran_ek"
DEFAULT_TOOL_CHANNEL = "agent"
_CALL_ID_NAMESPACE = uuid5(NAMESPACE_URL, "tp:ai_call")


def executor_secrets(execute: Any) -> frozenset[str]:
    """Araç yürütücüsünün bildirdiği sır değerleri (`gateway_gizliler`; ör. `AgentApp`'in
    snapshot'taki `[password]` işaretinden tanıdığı parola alanına yazılan metin). Bunlar
    `tool_call` argüman/sonuç kaydından silinir; bildirmeyen yürütücüde boş küme (web değişmez)."""
    degerler = getattr(execute, "gateway_gizliler", None)
    if not degerler:
        return frozenset()
    return frozenset(v for v in degerler if isinstance(v, str) and v)


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

# Toparlama (§6.4; yalnız `run_agent(toparlama=True)`): girdi tavanının bu oranı geçildiğinde
# ya da sondan bir önceki tur bittiğinde model eldekiyle son çıktıyı vermeye yönlendirilir.
TOPARLAMA_ORANI = 0.75
TOPARLAMA_NUDGE = (
    f"Süre/bağlam sınırına yaklaşıldı: başka araç kullanma; eldeki bilgiyle hemen `{FINAL_TOOL}` "
    "çağır (guven=dusuk)."
)

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
    # İstemci zaman aşımı: uzun üretim (case üretimi 16K token) yeniden denemede yine sürer ve
    # yeniden faturalanır; en çok bir kez daha denenir.
    max_timeout_retries: int = 1
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
    """Sonuç sayfa snapshot'ı mı? `browser_snapshot` ya da satır içi snapshot YAML'ı taşıyan
    eylem sonucu (Playwright MCP 1.64: `### Snapshot` + ```yaml```; eski `- Page Snapshot`).
    Eylemlerin dosya bağlantılı snapshot'ı (`- [Snapshot](…yml)`) snapshot sayılmaz."""
    return tool in (SNAPSHOT_TOOL, APP_SNAPSHOT_TOOL) or is_inline_snapshot(text)


@dataclass
class _Turn:
    response: ProviderResponse
    results: list[tuple[ToolCall, str, bool]] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)


_EXTRA_KEYS = (
    "replay_kaynagi",
    "replay_kokeni",
    "replay_eslesme",
    "cikti_kokeni",
    "sema_hatalari",
    "yeniden_deneme",
    "onbellek_okuma_token",
    "onbellek_yazma_token",
    "yedek_model",
    "maliyet_tahmini",
    "canli_hata_yedegi",
    "degerlendirme",
    "toparlama",
)


def _budgeted_input_tokens(usage: Usage) -> int:
    """Ajan girdi token tavanının (`max_input_tokens`) saydığı tur girdisi: önbelleksiz girdi +
    önbelleğe yazılan girdi (ikisi de ≥1× fiyatlanır).

    Önbellekten okunan önek (`cache_read_tokens`: sistem prompt'u, araç şemaları, case + sembol
    tablosu; ~0.1× fiyat) her tur yeniden gönderilir ve SAYILMAZ: saysaydık 15 turluk gerçekçi bir
    doğrulama yörüngesi (~10k token'lık önek × 15) yalnızca önekten ~150k'ye varır ve tavan
    sözleşmenin amacı olan kaçak bağlam büyümesi yerine yörünge uzunluğunu cezalandırırdı.
    Tavan böylece "tur başına yeni bağlam" birikimini (geçmiş, son snapshot, önbellek ıskası)
    sınırlar; USD harcaması ayrıca `Budget` ile (okuma dahil, gerçek fiyatla) sınırlanır.
    """
    return usage.input_tokens + usage.cache_write_tokens


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
        secret_values: Collection[str] = (),
        replay_fallback: bool = False,
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
        # Araç kaydından (tool_call) her zaman silinen bilinen sırlar (ör. ajan bayisinin parolası).
        self.secret_values = frozenset(v for v in secret_values if v)
        # Kriter 7: canlı çağrı sağlayıcı hatasıyla düşerse REPLAY golden'ına (etiketli) devam.
        # `record` kipinde hiçbir zaman (kayıt dizinine sahte canlı sonuç yazılmasın).
        self.replay_fallback = bool(replay_fallback) and mode == "live"
        self._sessions: dict[UUID, MaskingSession] = {}
        self._bundles: dict[tuple[str, str, str], Bundle] = {}
        self._evaluations: dict[str, dict[str, Any]] = {}

    # ---------------------------------------------------------------- yardımcılar

    def evaluation_of(self, bundle_id: str) -> dict[str, Any]:
        """Paketin canlı değerlendirme durumu (`rules/evaluations.yaml`, constitution X).

        `{"paket", "surum", "durum": pending|evaluated|waived|stale|missing, "etiket"}`; geçit
        her `ai_call` satırının `ek.degerlendirme` alanına yazar. Süreç başına önbelleklenir.
        """
        cached = self._evaluations.get(bundle_id)
        if cached is None:
            cached = self._evaluations[bundle_id] = evaluation_summary(self.rules_dir, bundle_id)
        return dict(cached)

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

    def _complete(
        self,
        request: ProviderRequest,
        cfg: PurposeConfig | None = None,
        *,
        bitis: float | None = None,
    ) -> tuple[ProviderResponse, int]:
        """Sağlayıcı çağrısı + yeniden deneme. Deneme sayıları amaç ayarından (`cfg.max_retries`,
        `cfg.max_timeout_retries`; None → `RetryPolicy`). `bitis` (geçit saatinde mutlak an)
        verilirse istek zaman aşımı ve yeniden deneme beklemesi kalan süreyle sınırlanır; süre
        yetmezse `AgentDeadlineExceeded`."""
        assert self.provider is not None
        max_retries = self.retry.max_retries
        max_timeout_retries = self.retry.max_timeout_retries
        if cfg is not None and cfg.max_retries is not None:
            max_retries = cfg.max_retries
        if cfg is not None and cfg.max_timeout_retries is not None:
            max_timeout_retries = cfg.max_timeout_retries
        attempt = 0
        while True:
            sent, capped = request, False
            if bitis is not None:
                remaining = bitis - self._clock()
                if remaining <= 0:
                    raise AgentDeadlineExceeded("ajan süresi doldu (sağlayıcı isteğinden önce)")
                if request.timeout_s is None or remaining < request.timeout_s:
                    sent = request.model_copy(update={"timeout_s": remaining})
                    capped = True
            try:
                return self.provider.complete(sent), attempt
            except ProviderTransientError as exc:
                timed_out = bool(getattr(exc, "timeout", False))
                if bitis is not None and (self._clock() >= bitis or (timed_out and capped)):
                    raise AgentDeadlineExceeded(
                        "ajan süresi doldu (sağlayıcı yanıtı süre içinde gelmedi)"
                    ) from exc
                if attempt >= max_retries:
                    raise
                if timed_out and attempt >= max_timeout_retries:
                    raise
                delay = self.retry.delay(attempt)
                if bitis is not None and self._clock() + delay >= bitis:
                    raise AgentDeadlineExceeded(
                        "ajan süresi doldu (yeniden deneme beklemesi kalan süreye sığmıyor)"
                    ) from exc
                self._sleep(delay)
                attempt += 1

    def _falls_back(self, exc: BaseException) -> bool:
        """Kriter 7: canlı çağrı sağlayıcı hatası/zaman aşımıyla düştü, REPLAY'e devam edilir mi?

        Yalnızca sağlayıcı hataları (zaman aşımı, 429/5xx tükenmesi, 4xx). Model reddi
        (`ProviderRefusal`) insana düşer, golden'la örtülmez; bütçe/şema hataları da öyle."""
        if not self.replay_fallback or isinstance(exc, ProviderRefusal):
            return False
        return isinstance(exc, ProviderTransientError | ProviderPermanentError)

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
        ek: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
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
            # Constitution X: paketin canlı değerlendirme durumu (portal "canlı değerlendirme
            # bekliyor" etiketini buradan gösterir; `ek.degerlendirme`).
            "degerlendirme": self.evaluation_of(bundle.id),
        }
        if ek:
            row[_CALLER_EK] = dict(ek)
        return row

    def _record(self, row: dict[str, Any]) -> UUID:
        """İç satırı `ai_call` kolonlarına çevirir; kolonu olmayan alanlar `ek`e gider."""
        extras = {k: row.pop(k) for k in _EXTRA_KEYS if k in row}
        caller_ek = row.pop(_CALLER_EK, None)
        row["mod"] = row.pop("replay")
        row["maliyet"] = row.pop("maliyet_usd", 0.0)
        schema_errors = extras.get("sema_hatalari")
        if schema_errors and not row.get("hata"):
            row["hata"] = "şema: " + "; ".join(schema_errors)
        if self.record_extras:
            row["ek"] = {**(caller_ek or {}), **extras}
        elif caller_ek:
            # Çağıranın alanları (ör. bütçe sorgusunun okuduğu `kullanici_id`) her zaman yazılır.
            row["ek"] = dict(caller_ek)
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
        session: MaskingSession | None = None,
    ) -> tuple[Bundle, MaskingSession, Any, dict[str, Any], str, str]:
        """call/run_agent ve golden yükseltme (`promote`) için TEK anahtar hesabı.

        `session` dışarıdan verilirse (asistan: mesaj başına tek oturum, araçlarla paylaşılır)
        iş akışı oturumu yerine o kullanılır."""
        bnd = self.bundle(bundle, bundle_schema, cfg)
        if session is None:
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
        tools = [narrow_tool(t) for t in tools]
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
        call_started = self._clock()
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
                timeout_s=cfg.timeout_s,
                fallbacks=cfg.fallbacks,
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
                response, retries = self._complete(request, cfg)
            except Exception as exc:
                row.update(
                    cikti=None,
                    sema_gecerli=False,
                    hata=f"{type(exc).__name__}: {exc}",
                    sure_ms=int((self._clock() - started) * 1000),
                    maliyet_usd=0.0,
                )
                failed_id = self._record(row)
                if not self._falls_back(exc):
                    raise
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
                    parent_id=first_id or failed_id,
                    live_failure=_live_failure(exc, failed_id),
                )
            cost = _response_cost(self.models, cfg, response)
            row.update(_fallback_fields(response, self.models))
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
                        "recording": _recording(
                            _served_model(cfg, response),
                            self.provider_name,
                            int((self._clock() - call_started) * 1000),
                            totals,
                        ),
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
        live_failure: dict[str, Any] | None = None,
    ) -> CallResult:
        record, mode, path = self._lookup_audited(
            purpose,
            bnd,
            cfg,
            key,
            key_fields,
            masked,
            mask_diff,
            workflow_id,
            root_id=root_id,
            parent_id=parent_id,
            live_failure=live_failure,
        )
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
        if live_failure is not None:
            row["canli_hata_yedegi"] = live_failure
        origin, recorded_model = output_origin(record)
        row.update(
            model=recorded_model or HAND_PREPARED_MODEL,
            replay_kaynagi=str(path.relative_to(self.replay_store.root)),
            replay_kokeni=_provenance(record, mode),
            cikti_kokeni=origin,
            **({"replay_eslesme": record["_mismatch"]} if record.get("_mismatch") else {}),
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

    def _lookup_audited(
        self,
        purpose: str,
        bnd: Bundle,
        cfg: PurposeConfig,
        key: str,
        key_fields: Mapping[str, Any],
        masked: Any,
        mask_diff: dict[str, Any],
        workflow_id: UUID | None,
        *,
        root_id: UUID | None,
        parent_id: UUID | None,
        live_failure: dict[str, Any] | None = None,
        ek: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ReplayMode, Path]:
        """Replay araması; bulunamayan/çıktısız iskalama da `ai_call`'a yazılır (constitution
        VIII: denetim izi yalnızca başarılı çağrıları değil, yapılamayanları da gösterir)."""
        try:
            return self.replay_store.lookup(purpose, key, _golden_name(key_fields), masked)
        except ReplayNotFound as exc:
            row = self._base_row(
                purpose=purpose,
                bundle=bnd,
                cfg=cfg,
                workflow_id=workflow_id,
                parent_id=parent_id,
                mode="replay_miss",
                key=key,
                row_id=root_id,
                ek=ek,
            )
            reasons = getattr(exc, "reasons", None)
            if live_failure is not None:
                row["canli_hata_yedegi"] = live_failure
            row.update(
                model=HAND_PREPARED_MODEL,
                replay_kokeni="yok",
                **({"replay_eslesme": reasons} if reasons else {}),
                maskeli_girdi=masked,
                maskeleme_farki=mask_diff,
                cikti=None,
                sema_gecerli=False,
                deneme=1,
                yeniden_deneme=0,
                girdi_token=0,
                cikti_token=0,
                maliyet_usd=0.0,
                sure_ms=0,
                hata=f"{type(exc).__name__}: {exc}",
            )
            self._record(row)
            raise

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
        tool_channel: str = DEFAULT_TOOL_CHANNEL,
        caller_user_id: UUID | None = None,
        ek: Mapping[str, Any] | None = None,
        masking_session: MaskingSession | None = None,
        bitis: float | None = None,
        should_stop: Callable[[], bool] | None = None,
        toparlama: bool = False,
        sistem_eki: str | None = None,
    ) -> AgentResult:
        """Araçlı ajan döngüsü.

        Asistan için eklenen parametrelerin (AI-ASISTAN-PLANI §10.3) varsayılanı eski davranıştır:
        - `tool_channel`, `caller_user_id`: `tool_call.kanal` / `cagiran_user_id`.
        - `ek`: her `ai_call` satırının `ek`ine eklenen çağıran alanları.
        - `masking_session`: dışarıdan maskeleme oturumu (araçlarla aynı yer tutucular).
        - `bitis`: geçit saatinde (`clock`, varsayılan `time.monotonic`) mutlak bitiş anı; her tur
          başında aşıldıysa `AgentDeadlineExceeded`; sağlayıcı zaman aşımı ve yeniden deneme
          beklemesi kalan süreyle sınırlı.
        - `should_stop`: her tur başında doğruysa `AgentStopped` (yazılmış turlar kayıtta kalır).
        - `toparlama`: girdi tavanının %75'i aşılınca ya da sondan bir önceki tur bitince model
          eldekiyle `submit_result` çağırmaya yönlendirilir (nudge geçmişte kalıcıdır).
        - `sistem_eki`: canlı isteğin sistem metninin EN SONUNA eklenir (asistan kanaryası;
          specs/013 §6.3). Replay anahtarı, girdi özeti ve bundle hash'i bundan hesaplanmaz;
          replay kipinde sistem metni kullanılmadığından etkisizdir. Sağlayıcının prompt
          önbelleği ise sistem metninin tamamını önek sayar: ek (kanarya) süreç başına
          değiştiğinden önbellek her worker sürecinde bir kez soğuk başlar, aynı süreçteki
          istekler isabet eder.
        """
        self._check_agent_tools(purpose, tools)
        # Model yasak argümanları (dosya yazma vb.) hiç görmez; anahtar da daraltılmış şemadandır.
        tools = [narrow_tool(t) for t in tools]
        cfg = self.models.purpose(purpose)
        bnd, session, masked, mask_diff, digest, key = self._key_material(
            purpose,
            cfg,
            bundle,
            _agent_bundle_schema(output_schema, tools),
            messages,
            replay_key,
            workflow_id,
            masking_session,
        )
        channel = {"kanal": tool_channel, "cagiran_user_id": caller_user_id}
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
                ek=ek,
                channel=channel,
            )

        snapshot = is_snapshot or self._is_snapshot
        final_tool = ToolSpec(
            name=FINAL_TOOL,
            description="Görevi bitirdiğinde son sonucu bu araçla ver (sonuç şemasına uymalı).",
            input_schema=output_schema,
        )
        system = f"{bnd.system_prompt}\n\n{AGENT_ADDENDUM}"
        if sistem_eki:
            system = f"{system}\n\n{sistem_eki}"
        turns: list[_Turn] = []
        agent_started = self._clock()
        steps: list[AgentStep] = []
        call_ids: list[UUID] = []
        first_id: UUID | None = call_id if root_id is None else None
        schema_failures = 0
        used_input_tokens = 0
        last_errors: list[str] = []
        last_output: Any = None
        secrets = set(self.secret_values)
        wrapping_up = False  # toparlama nudge'ı verildi mi

        for turn_no in range(1, max_turns + 1):
            # Tur başı: çağıran durdurduysa ya da süre dolduysa yeni (ücretli) tur açılmaz.
            if should_stop is not None and should_stop():
                raise AgentStopped(f"'{purpose}' ajanı çağıranın isteğiyle durduruldu")
            if bitis is not None and self._clock() >= bitis:
                raise AgentDeadlineExceeded(f"'{purpose}' ajanının süresi doldu (tur {turn_no})")
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
                timeout_s=cfg.timeout_s,
                fallbacks=cfg.fallbacks,
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
                ek=ek,
            )
            row.update(
                maskeli_girdi=masked if turn_no == 1 else _last_results(turns),
                maskeleme_farki=mask_diff,
                deneme=turn_no,
            )
            if wrapping_up:
                row["toparlama"] = True
            started = self._clock()
            try:
                response, retries = self._complete(request, cfg, bitis=bitis)
            except Exception as exc:
                row.update(
                    cikti=None,
                    sema_gecerli=False,
                    hata=f"{type(exc).__name__}: {exc}",
                    sure_ms=int((self._clock() - started) * 1000),
                    maliyet_usd=0.0,
                )
                failed_id = self._record(row)
                if not self._falls_back(exc):
                    raise
                # Kayıtlı yörünge baştan (REPLAY araç adımlarıyla) yürür; canlı turların araç
                # adımları denetimde kalır, sonuç REPLAY etiketlidir.
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
                    parent_id=first_id or failed_id,
                    live_failure=_live_failure(exc, failed_id, turn=turn_no),
                    ek=ek,
                    channel=channel,
                )
            cost = _response_cost(self.models, cfg, response)
            row.update(_fallback_fields(response, self.models))
            self.budget.charge(workflow_id, cost)
            used_input_tokens += _budgeted_input_tokens(response.usage)
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
                if (
                    toparlama
                    and not wrapping_up
                    and self._should_wrap_up(cfg, used_input_tokens, turn_no, max_turns)
                ):
                    wrapping_up = _add_wrap_up_nudge(turn)
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
                    self._record_tool(
                        row_id,
                        tc.name,
                        tc.args,
                        result,
                        allowed_flag=True,
                        secrets=secrets,
                        **channel,
                    )
                elif tc.name not in allowed or _banned_args(tc.name, tc.args):
                    banned = _banned_args(tc.name, tc.args)
                    result = (
                        f"Argüman izinli değil: {tc.name}({', '.join(banned)}). Bu argümanlar "
                        "(dosyaya yazma, koordinat) verilmez; argümansız tekrar çağır."
                        if tc.name in allowed
                        else f"Araç izinli değil: {tc.name}. İzinli araçlar: {sorted(allowed)}"
                    )
                    is_error = True
                    step = AgentStep(
                        tool=tc.name,
                        args=tc.args,
                        result_summary=_summary(scrub_secrets(result, secrets)),
                        allowed=False,
                    )
                    steps.append(step)
                    self._record_tool(
                        row_id,
                        tc.name,
                        tc.args,
                        result,
                        allowed_flag=False,
                        secrets=secrets,
                        **channel,
                    )
                    if on_step:
                        on_step(step)
                else:
                    result, is_error = self._execute(execute, tc.name, session.unmask(tc.args))
                    # MCP sunucu dosyası bağlantıları (snapshot .yml, konsol .log) modele gitmez.
                    result = strip_mcp_file_links(result)
                    result, _ = session.mask(result) if self._mask_tool_results else (result, [])
                    secrets.update(secret_tool_values(tc.args))
                    secrets.update(executor_secrets(execute))
                    step = AgentStep(
                        tool=tc.name,
                        args=tc.args,
                        result_summary=_summary(scrub_secrets(result, secrets)),
                        allowed=True,
                    )
                    steps.append(step)
                    self._record_tool(
                        row_id,
                        tc.name,
                        tc.args,
                        result,
                        allowed_flag=True,
                        secrets=secrets,
                        **channel,
                    )
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
                            "recording": _recording(
                                _served_model(cfg, response),
                                self.provider_name,
                                int((self._clock() - agent_started) * 1000),
                                _turns_usage(turns),
                            ),
                            "output": final_output,
                            "steps": [s.model_dump() for s in steps],
                        },
                    )
                    if failure:
                        # Tur satırı zaten yazıldı (append-only); iz tool_call olarak kalır.
                        self._record_tool(
                            row_id,
                            "replay_kaydet",
                            {},
                            failure,
                            allowed_flag=True,
                            secrets=secrets,
                            **channel,
                        )
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
            if (
                toparlama
                and not wrapping_up
                and self._should_wrap_up(cfg, used_input_tokens, turn_no, max_turns)
            ):
                wrapping_up = _add_wrap_up_nudge(turn)
        raise AgentTurnLimit(f"'{purpose}' ajanı {max_turns} turda sonuç vermedi")

    @staticmethod
    def _should_wrap_up(
        cfg: PurposeConfig, used_input_tokens: int, turn_no: int, max_turns: int
    ) -> bool:
        """Toparlama koşulu (§6.4): önbelleksiz girdi tavanın %75'ini geçti ya da sondan bir
        önceki tur bitti (son tur modelin eldekiyle son çıktıyı vermesine kalır)."""
        if cfg.max_input_tokens and used_input_tokens > TOPARLAMA_ORANI * cfg.max_input_tokens:
            return True
        return turn_no >= max_turns - 1

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
        # Geçmiş düzenleme (preserved thinking, §8.4): bir tool_result ELIDED_SNAPSHOT ile
        # değiştirildiğinde ondan SONRA üretilmiş thinking blokları geçersizleşir (Sonnet 5.5
        # `between_tools` ilerleme notları da `thinking` bloğudur; yeni hesaplarda 400).
        # `between_tools` ile `block_binding: drop_block` kullanılamaz; bu yüzden ilk düzenlenen
        # mesajdan sonraki asistan turlarından thinking/redacted_thinking blokları çıkarılır.
        first_edited: int | None = None
        for ti, turn in enumerate(turns):
            if any(
                c.id and not e and is_snapshot(turn.tool_names[ri], t) and (ti, ri) != last_snapshot
                for ri, (c, t, e) in enumerate(turn.results)
            ):
                first_edited = ti
                break
        for ti, turn in enumerate(turns):
            message = self.provider.assistant_message(turn.response)
            if first_edited is not None and ti > first_edited:
                message = _strip_thinking(message)
            conversation.append(message)
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
                message = self.provider.tool_result_message(rendered)
                content = message.get("content")
                if nudges and isinstance(content, list):
                    # Toparlama nudge'ı araç sonuçlarıyla aynı kullanıcı mesajında (art arda iki
                    # kullanıcı mesajı yerine): sonuç bloklarından sonra metin bloğu.
                    message = {
                        **message,
                        "content": [*content, {"type": "text", "text": "\n".join(nudges)}],
                    }
                    nudges = []
                conversation.append(message)
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
        self,
        ai_call_id: UUID,
        tool: str,
        args: Any,
        result: str,
        *,
        allowed_flag: bool,
        secrets: set[str] | None = None,
        kanal: str = DEFAULT_TOOL_CHANNEL,
        cagiran_user_id: UUID | None = None,
    ) -> UUID:
        """`tool_call` append-only'dir: parola alanı argümanı ve bilinen sırlar kayıttan ÖNCE
        gizlenir (sonradan silinemez). `secrets` çalıştırma boyunca birikir."""
        known = secrets if secrets is not None else set(self.secret_values)
        known.update(secret_tool_values(args))
        return self.recorder.record_tool_call(
            {
                "id": uuid4(),
                "ai_call_id": ai_call_id,
                "kanal": kanal,
                "cagiran_user_id": cagiran_user_id,
                "arac": tool,
                "arguman_ozeti": _args_summary(scrub_secrets_in(mask_tool_args(args), known)),
                "sonuc_ozeti": _summary(scrub_secrets(result, known)),
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
        live_failure: dict[str, Any] | None = None,
        ek: Mapping[str, Any] | None = None,
        channel: Mapping[str, Any] | None = None,
    ) -> AgentResult:
        channel = dict(channel or {})
        record, mode, path = self._lookup_audited(
            purpose,
            bnd,
            cfg,
            key,
            key_fields,
            masked,
            mask_diff,
            workflow_id,
            root_id=root_id,
            parent_id=parent_id,
            live_failure=live_failure,
            ek=ek,
        )
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
            ek=ek,
        )
        if live_failure is not None:
            row["canli_hata_yedegi"] = live_failure
        origin, recorded_model = output_origin(record)
        row.update(
            model=recorded_model or HAND_PREPARED_MODEL,
            replay_kaynagi=str(path.relative_to(self.replay_store.root)),
            replay_kokeni=_provenance(record, mode),
            cikti_kokeni=origin,
            **({"replay_eslesme": record["_mismatch"]} if record.get("_mismatch") else {}),
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
        secrets = set(self.secret_values)
        live_lines: list[str] | None = None  # bu oturumdaki son snapshot (ref çözümü için)
        for raw in record.get("steps") or []:
            recorded = AgentStep.model_validate(raw)
            secrets.update(secret_tool_values(recorded.args))
            # İzin listesi replay'de de geçerlidir: kayıtta olsa bile listede olmayan araç koşmaz.
            is_allowed = (
                recorded.allowed
                and recorded.tool in allowed
                and not _banned_args(recorded.tool, recorded.args)
            )
            summary = recorded.result_summary
            args = recorded.args
            if is_allowed and self.replay_executes_tools:
                args, unresolved = _resolve_recorded_ref(raw, recorded.args, live_lines)
                if unresolved is not None:
                    # Eleman bu oturumun sayfasında yok: kayıttaki ref'i körlemesine göndermek
                    # yanlış elemanı doğrulayabilir. Adım çalıştırılmaz, hata olarak akar.
                    summary = unresolved
                else:
                    result, is_error = self._execute(execute, recorded.tool, session.unmask(args))
                    result = strip_mcp_file_links(result)
                    if not is_error and self._is_snapshot(recorded.tool, result):
                        live_lines = snapshot_lines(result) or live_lines
                    summary = _summary(result)
                    if not is_error:
                        drift = _replay_drift(recorded, result)
                        if drift:
                            summary = _summary(f"{drift}\n{result}")
            elif not is_allowed:
                banned = _banned_args(recorded.tool, recorded.args)
                summary = (
                    f"Argüman izinli değil: {recorded.tool}({', '.join(banned)})"
                    if banned and recorded.tool in allowed
                    else f"Araç izinli değil: {recorded.tool}"
                )
            secrets.update(executor_secrets(execute))
            step = AgentStep(
                tool=recorded.tool,
                args=args,
                result_summary=scrub_secrets(summary, secrets),
                allowed=is_allowed,
            )
            steps.append(step)
            self._record_tool(
                row_id,
                step.tool,
                step.args,
                summary,
                allowed_flag=is_allowed,
                secrets=secrets,
                **channel,
            )
            if on_step:
                on_step(step)
        return AgentResult(output=session.unmask(output), steps=steps, call_ids=[row_id], mode=mode)


# -------------------------------------------------------------------- yardımcılar

REPLAY_UNRESOLVED = "Araç hatası (ReplayHedefYok)"
REPLAY_DRIFT = "REPLAY sapması"
_GENERATED_LOCATOR = re.compile(r"getBy[A-Za-z]+\([^)]*\)(?:\.getBy[A-Za-z]+\([^)]*\))*")


def _resolve_recorded_ref(
    raw: Mapping[str, Any], args: dict[str, Any], live_lines: list[str] | None
) -> tuple[dict[str, Any], str | None]:
    """Kayıttaki snapshot ref'ini (`e21`) bu oturumun son snapshot'ından çözer.

    Ref'ler oturuma özgüdür ve aynı yörüngede bile kayabilir (snapshot_refs modül notu). Adım
    yapılandırılmış hedef (`hedef`: rol/ad/kapsam) taşıyorsa ref canlı snapshot'tan bulunur;
    bulunamazsa adım çalıştırılmaz ve `(args, hata metni)` döner. Hedefsiz eski kayıtlar
    değiştirilmeden gönderilir (geriye uyum; golden sürüklenme testi hedefi zorunlu tutar).
    """
    key = ref_arg(args)
    hedef = Hedef.from_raw(raw.get("hedef"))
    if key is None or hedef is None:
        return args, None
    if live_lines is None:
        return args, (
            f"{REPLAY_UNRESOLVED}: {hedef.describe()} için bu oturumda snapshot alınmadı; "
            f"kayıttaki ref {args[key]} gönderilmedi."
        )
    ref = locate_ref(live_lines, hedef)
    if ref is None:
        return args, (
            f"{REPLAY_UNRESOLVED}: {hedef.describe()} bu oturumun son snapshot'ında bulunamadı; "
            f"kayıttaki ref {args[key]} gönderilmedi."
        )
    return {**args, key: ref}, None


_PAGE_URL = re.compile(r"(?:Page URL:\s*|\bURL\s+)(\S+)")


def _url_path(text: str | None) -> str | None:
    """Araç çıktısındaki sayfa yolu (`Page URL: http://h/sepet` ve `· URL /sepet` → `/sepet`)."""
    m = _PAGE_URL.search(text or "")
    if m is None:
        return None
    url = m.group(1).rstrip(".,;)|")
    if "://" in url:
        url = "/" + url.split("://", 1)[1].partition("/")[2]
    return url.split("?", 1)[0].split("#", 1)[0] or "/"


def _url_class(path: str) -> str:
    """Oturuma özgü kimlik (sipariş no) her koşuda farklıdır: `/siparis/SP-1` → `/siparis/*`."""
    head, sep, _ = path.rstrip("/").rpartition("/")
    return f"{head}/*" if sep and head and re.search(r"\d", path.rsplit("/", 1)[-1]) else path


def _replay_drift(recorded: AgentStep, result: str) -> str | None:
    """Canlı adım kayıttakinden saptıysa sapma notu (yoksa None).

    - `browser_generate_locator`: canlı locator kayıttakinden farklıysa — kayıttaki doğrulama
      başka bir elemanı göstermişse 'doğrulandı' işareti bu oturumda tekrarlanmamıştır.
    - Eylem/gezinti adımları: kayıttaki sayfa yolu (`· URL /katalog`) ile canlı sayfa yolu farklıysa
      (örn. hatalı parola girişte kalmalıyken katalog açıldı) yörünge artık kanıt değildir.
    Not adım özetinin başına yazılır (denetim + insan)."""
    if recorded.tool == APP_GENERATE_LOCATOR:
        want_app = app_locator(recorded.result_summary)
        if want_app is None:
            return None
        got_app = app_locator(result)
        if got_app == want_app:
            return None
        return (
            f"{REPLAY_DRIFT}: kayıtta kimlik {want_app[1] or '(yok)'} ({want_app[0]}), bu oturumda "
            + (f"{got_app[1] or '(yok)'} ({got_app[0]})" if got_app else "(locator yok)")
        )
    if recorded.tool != "browser_generate_locator":
        want_url = _url_path(recorded.result_summary)
        got_url = _url_path(result)
        if want_url and got_url and _url_class(want_url) != _url_class(got_url):
            return f"{REPLAY_DRIFT}: kayıtta sayfa {want_url}, bu oturumda {got_url}"
        return None
    want = _GENERATED_LOCATOR.findall(recorded.result_summary or "")
    if not want:
        return None
    got = _GENERATED_LOCATOR.findall(result)
    if want[-1] in got:
        return None
    return f"{REPLAY_DRIFT}: kayıtta {want[-1]}, bu oturumda {got[-1] if got else '(locator yok)'}"


_THINKING_BLOCKS = frozenset({"thinking", "redacted_thinking"})
_THINKING_STRIPPED = "[ara not bağlamdan çıkarıldı]"


def _add_wrap_up_nudge(turn: _Turn) -> bool:
    """Toparlama nudge'ını turun sonuçlarına ekler (geçmişte kalıcı; bir kez)."""
    turn.results.append((ToolCall(id="", name="", args={}), TOPARLAMA_NUDGE, True))
    turn.tool_names.append("")
    return True


def _strip_thinking(message: dict[str, Any]) -> dict[str, Any]:
    """Asistan mesajından thinking/redacted_thinking bloklarını çıkarır (yeni sözlük döner)."""
    content = message.get("content")
    if not isinstance(content, list):
        return message
    kept = [b for b in content if not (isinstance(b, dict) and b.get("type") in _THINKING_BLOCKS)]
    if len(kept) == len(content):
        return message
    if not kept:  # yalnızca thinking içeren tur: API boş asistan içeriğini kabul etmez
        kept = [{"type": "text", "text": _THINKING_STRIPPED}]
    return {**message, "content": kept}


def _replay_key(purpose: str, bundle_hash: str, fields: Mapping[str, Any], digest: str) -> str:
    return replay_key(purpose, bundle_hash, fields, digest)


def _agent_bundle_schema(output_schema: Mapping[str, Any], tools: Sequence[ToolSpec]) -> dict:
    """Ajan bundle hash'ine çıktı şeması ve araç tanımları (ad, açıklama, girdi şeması) girer."""
    return {"output": output_schema, "tools": [t.model_dump() for t in tools]}


def _recording(model: str, provider: str, latency_ms: int, usage: Usage) -> dict[str, Any]:
    """record modunun yazdığı kayıt üst verisi (kayıt zamanı `ReplayStore.save` ile eklenir)."""
    return {
        "model": model,
        "provider": provider,
        "latency_ms": latency_ms,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
    }


def _response_cost(models: ModelTable, cfg: PurposeConfig, response: ProviderResponse) -> float:
    """Ret yedeği başka modelde koştuysa o modelin fiyatı.

    Yedek model fiyat tablosunda yoksa EKSİK sayılmaz: tablodaki en pahalı fiyat uygulanır
    (`_unpriced_fallback` → `ek.maliyet_tahmini`); istenen modelin (daha ucuz) fiyatıyla iş akışı
    ve günlük bütçe olduğundan az doldurulmaz."""
    if response.fallback_from and response.model:
        if response.model in models.prices:
            return models.cost(response.model, response.usage)
        return models.max_price().cost(response.usage)
    return models.cost(cfg.model, response.usage)


def _unpriced_fallback(models: ModelTable, response: ProviderResponse) -> bool:
    return bool(response.fallback_from and response.model and response.model not in models.prices)


def _served_model(cfg: PurposeConfig, response: ProviderResponse) -> str:
    return response.model if response.fallback_from and response.model else cfg.model


def _fallback_fields(
    response: ProviderResponse, models: ModelTable | None = None
) -> dict[str, Any]:
    """Sağlayıcı tarafı ret yedeği: `ai_call.model` yanıtı üreten model, `ek.yedek_model` geçiş.

    Yedek model fiyatsızsa `ek.maliyet_tahmini` (en pahalı tablo fiyatıyla üst sınır tahmini)."""
    if not response.fallback_from or not response.model:
        return {}
    out: dict[str, Any] = {
        "model": response.model,
        "yedek_model": {"istenen": response.fallback_from, "yanitlayan": response.model},
    }
    if models is not None and _unpriced_fallback(models, response):
        out["maliyet_tahmini"] = {
            "neden": f"'{response.model}' fiyat tablosunda yok (rules/models.yaml)",
            "uygulanan": "tablodaki en pahalı fiyat (üst sınır)",
        }
        log.warning(
            "ret yedeği fiyatsız modelde koştu (%s); maliyet en pahalı fiyatla tahmin edildi",
            response.model,
        )
    return out


def _live_failure(
    exc: BaseException, failed_id: UUID, *, turn: int | None = None
) -> dict[str, Any]:
    """`ek.canli_hata_yedegi`: canlı çağrı düştü, çıktı REPLAY golden'ından (etiketli)."""
    out: dict[str, Any] = {
        "neden": type(exc).__name__,
        "zaman_asimi": bool(getattr(exc, "timeout", False)),
        "durum": getattr(exc, "status", None),
        "canli_cagri": str(failed_id),
        "etiket": "canlı çağrı başarısız; REPLAY ile sürdürüldü",
    }
    if turn is not None:
        out["tur"] = turn
    return out


def _turns_usage(turns: Sequence[_Turn]) -> Usage:
    total = Usage()
    for turn in turns:
        total = _add_usage(total, turn.response.usage)
    return total


def _provenance(record: Mapping[str, Any], mode: str) -> str:
    """Replay kaynağının kökeni (ai_call.ek): canlı kayıt, golden yedeği, yükseltilmiş golden,
    nötr REPLAY-MISS yedeği."""
    if mode == "replay_miss":
        return str(record.get("provenance") or "golden")
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
