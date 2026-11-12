"""Şeritler arası sözleşme: dış sistem portları ve ortak veri tipleri.

Her dış sistem (Jira, test yönetimi, git forge, model sağlayıcı) bir Protocol arkasındadır.
Gerçek adaptör ve yerel simülatör aynı Protocol'ü uygular; iş akışları yalnızca bu dosyadaki
tiplere bağımlıdır. Değişiklik yalnızca lider (entegrasyon) tarafından yapılır.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- Jira


class JiraIssue(BaseModel):
    key: str
    issue_type: str
    summary: str
    description: str = ""  # düz metin (ADF → metin dönüşümü adaptörde)
    acceptance_criteria: list[str] = Field(default_factory=list)  # "AC1: ..." sırasıyla
    labels: list[str] = Field(default_factory=list)
    status: str = ""
    updated: datetime | None = None
    reporter: str | None = None


class JiraComment(BaseModel):
    id: str
    author: str
    body: str
    created: datetime | None = None
    # Yetki eşlemesi için yazarın tüm kimlikleri (e-posta ve accountId; görünen ad asla).
    author_ids: list[str] = Field(default_factory=list)


class LabelChange(BaseModel):
    label: str
    author: str  # etiketi koyan (changelog'dan)
    at: datetime | None = None
    # Yetki eşlemesi için yazarın tüm kimlikleri (e-posta ve accountId; görünen ad asla). Jira
    # Cloud e-postayı gösterdiğinde ``author`` e-postadır; accountId ile yapılandırılmış PO listesi
    # yine eşleşmelidir.
    author_ids: list[str] = Field(default_factory=list)


@runtime_checkable
class JiraPort(Protocol):
    """Jira Cloud REST v3 alt kümesi. Okuma ve yazma ayrı kimliklerle yapılır (adaptör içinde)."""

    def search(self, jql: str, max_results: int = 50) -> list[JiraIssue]: ...
    def get_issue(self, key: str) -> JiraIssue: ...
    def get_comments(self, key: str) -> list[JiraComment]: ...
    def label_history(self, key: str, label: str) -> list[LabelChange]: ...

    def add_comment(self, key: str, body: str) -> str: ...  # yorum id
    def add_labels(self, key: str, labels: Sequence[str]) -> None: ...
    def remove_labels(self, key: str, labels: Sequence[str]) -> None: ...
    def update_description(
        self, key: str, description: str, acceptance_criteria: Sequence[str]
    ) -> None: ...
    def create_issue(
        self,
        project: str,
        issue_type: str,
        summary: str,
        description: str,
        labels: Sequence[str] = (),
        fields: Mapping[str, Any] | None = None,
    ) -> str: ...  # yeni issue key
    def link_issues(self, inward_key: str, outward_key: str, link_type: str) -> None: ...


# ----------------------------------------------------------------- Test yönetimi


class PublishedCase(BaseModel):
    case_id: UUID
    external_key: str
    url: str | None = None


@runtime_checkable
class TestManagementPort(Protocol):
    """Onaylı case'leri hedef sisteme yazar.

    Jira Test issue, Xray Cloud; ileride TestRail/Zephyr.
    """

    name: str

    def find_existing(self, case_id: UUID) -> str | None: ...  # idempotency: tp-<uuid> araması
    def publish_case(self, case: Mapping[str, Any], story_key: str) -> PublishedCase: ...


# ----------------------------------------------------------------------- Forge


class PullRequest(BaseModel):
    number: int
    branch: str
    base: str = "main"
    title: str
    body: str = ""
    state: Literal["open", "merged", "closed"] = "open"
    head_sha: str
    url: str | None = None
    labels: list[str] = Field(default_factory=list)


class CheckRun(BaseModel):
    name: str
    status: Literal["queued", "in_progress", "completed"]
    conclusion: Literal["success", "failure", "cancelled", "skipped"] | None = None
    url: str | None = None


@runtime_checkable
class ForgePort(Protocol):
    """Test edilen uygulamanın deposu: `local` (bare git + /forge PR kaydı) veya `github`."""

    def head_sha(self, ref: str = "main") -> str: ...
    def read_file(self, path: str, ref: str = "main") -> str: ...
    def list_files(self, prefix: str = "", ref: str = "main") -> list[str]: ...
    def search_code(self, query: str, ref: str = "main") -> list[tuple[str, int, str]]: ...
    def commit_files(
        self, branch: str, files: Mapping[str, str], message: str, base: str = "main"
    ) -> str: ...  # yeni commit sha
    def find_open_pr(self, branch: str) -> PullRequest | None: ...
    def open_pr(
        self, branch: str, title: str, body: str, labels: Sequence[str] = ()
    ) -> PullRequest: ...
    def get_pr(self, number: int) -> PullRequest: ...
    # merge commit sha. expected_head_sha: insanın onayladığı head; PR head'i farklıysa çakışma.
    def merge_pr(self, number: int, actor: str, *, expected_head_sha: str | None = None) -> str: ...
    def comment_pr(self, number: int, body: str) -> None: ...
    def checks(self, sha: str) -> list[CheckRun]: ...


# --------------------------------------------------------------- Model geçidi


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class ModelMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: Any  # str veya içerik blokları (sağlayıcıdan bağımsız sözlükler)


class CallResult(BaseModel):
    output: Any  # şemaya göre doğrulanmış yapılandırılmış sonuç
    call_id: UUID
    mode: Literal["live", "replay", "replay_miss"]
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    # Kural yeniden istemesi (`output_check`) yapıldıysa ilk şemaya uyan çıktı (maskesiz): çağıran
    # denemeler arasında silinen atıfları uyarıya yazabilir (ör. hazır case'te düşen soru atfı).
    ilk_cikti: Any = None
    # Geçidin çağırana notları (ör. iş süresi yetmediği için yeniden istenmedi; son deneme şemayı
    # bozdu, önceki şemaya uyan çıktı döndü).
    uyarilar: list[str] = Field(default_factory=list)


class AgentStep(BaseModel):
    tool: str
    args: dict[str, Any]
    result_summary: str
    allowed: bool = True


class AgentResult(BaseModel):
    output: Any
    steps: list[AgentStep] = Field(default_factory=list)
    call_ids: list[UUID] = Field(default_factory=list)
    mode: Literal["live", "replay", "replay_miss"]


class ToolExecutor(Protocol):
    def __call__(self, name: str, args: dict[str, Any]) -> str: ...


@runtime_checkable
class ModelGateway(Protocol):
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
        call_id: UUID | None = None,  # deterministik (iş + adım) → yeniden denemede tek çağrı
        ek: Mapping[str, Any] | None = None,  # çağıranın ai_call.ek alanları (011 platform ekleri)
        # Şemaya uyan çıktının deterministik kural denetimi (ihlalde yeniden istenir; 011 §4.2).
        output_check: Callable[[Any], list[str]] | None = None,
    ) -> CallResult: ...

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
        call_id: UUID | None = None,
    ) -> AgentResult: ...


# ------------------------------------------------------------------ Kayıt (audit)


@runtime_checkable
class CallRecorder(Protocol):
    """Model geçidinin ai_call / tool_call yazımı. Uygulaması tp_core.audit'te (Postgres)."""

    def record_ai_call(self, row: Mapping[str, Any]) -> UUID: ...
    def record_tool_call(self, row: Mapping[str, Any]) -> UUID: ...


@runtime_checkable
class AuditLog(Protocol):
    def append(self, aktor: str, eylem: str, nesne: str | None, ozet: Mapping[str, Any]) -> int: ...


@runtime_checkable
class EventBus(Protocol):
    """Portala SSE ile akan olaylar (case.generated, agent.step, pr.opened, ci.status, ...)."""

    def publish(self, event: str, data: Mapping[str, Any]) -> None: ...


# ------------------------------------------------------------------ Agent Probe (011 §4.5)
# Agent Probe, Testing Probe çıktısını ve asistan trafiğini denetleyen ayrı üründür. Bu sürümde
# port arkasındadır: denetim (P9) ve asistan puanı Testing Probe geçidinde ayrı model çağrısıyla,
# ajan ürünleri ve ajan testi talepleri süreç içi simülatörle karşılanır (TP_AGENT_PROBE).

DenetimKarari = Literal["KABUL", "DÜZELTME_GEREKLİ", "ENGELLE"]
AsistanKarari = Literal["gec", "uyar", "engelle"]


class CaseSetAuditRequest(BaseModel):
    """P9 girdisi: gereksinim, üretilmiş set (case'ler + üst düzey listeler), varsa P8 sonucu."""

    requirement_id: UUID
    requirement_key: str
    set_hash: str
    requirement_block: str  # güvenilmeyen veri bloğu olarak hazırlanmış gereksinim metni
    generated_set: Mapping[str, Any]  # {"cases": [...], "ozet": {...}}
    review_result: Mapping[str, Any] | None = None
    policies: Sequence[str] = ()
    # Üretime verilen test verisi bloğu (güvenilmeyen; kullanıcı, bayi adı, fiyat, UI etiketi
    # kaynağıdır) ve izinli test ortamları (`synthetic: true` parola muafiyeti yalnız bunlarda).
    # Denetim akışı (`denetim_akisi`) ikisini de doldurur; değerlendirme seti (`case-audit.json`)
    # bu bölümlerle kurulur. Boş bırakılırsa bölümler denetim girdisine hiç yazılmaz (girdi,
    # dolayısıyla replay anahtarı, bölümsüz biçimdir) — "golden'lar değişmez" güvencesi yalnız
    # bu boş durum içindir.
    test_data_block: str | None = None
    allowed_hosts: Sequence[str] = ()


class CaseSetAuditResult(BaseModel):
    decision: DenetimKarari
    decision_rationale: str
    findings: list[dict[str, Any]] = Field(default_factory=list)
    missing_scenarios: list[str] = Field(default_factory=list)
    talep_no: str  # Agent Probe tarafındaki kayıt numarası
    kaynak: Literal["tp-gecit", "agent-probe", "sim"]
    ai_call_id: UUID | None = None


class MessageScore(BaseModel):
    """Asistan sorusu/cevabı için denetim puanı (0 = en riskli, 100 = temiz)."""

    puan: int = Field(ge=0, le=100)
    kategoriler: list[str] = Field(default_factory=list)
    karar: AsistanKarari
    gerekce: str = ""
    talep_no: str
    kaynak: Literal["tp-gecit", "agent-probe", "sim"]
    ai_call_id: UUID | None = None


class AgentProduct(BaseModel):
    """Agent Probe'da ön tanımları tamamlanmış (Testing Probe'da görünür) AI ajan ürünü."""

    kod: str
    ad: str
    aciklama: str = ""
    hazir: bool = True


class AgentTestTicket(BaseModel):
    talep_no: str
    urun_kodu: str
    requirement_id: UUID
    durum: Literal["queued", "running", "passed", "failed", "error"]
    ozet: str = ""
    sonuc: dict[str, Any] = Field(default_factory=dict)
    url: str | None = None
    simulasyon: bool = True
    guncelleme: datetime | None = None


@runtime_checkable
class AgentProbePort(Protocol):
    name: str

    def audit_case_set(self, istek: CaseSetAuditRequest) -> CaseSetAuditResult: ...

    def score_message(
        self, metin: str, yon: Literal["soru", "cevap"], baglam: Mapping[str, Any]
    ) -> MessageScore: ...

    def list_products(self) -> list[AgentProduct]: ...

    def start_agent_test(
        self, urun_kodu: str, requirement_id: UUID, gereksinim: Mapping[str, Any]
    ) -> AgentTestTicket: ...

    def get_agent_test(self, talep_no: str) -> AgentTestTicket: ...
