"""Test yönetimi adaptörleri (``TestManagementPort``): Jira Test issue ve fabrika.

Eşleme (TEKNIK-TASARIM §8.3): issue türü ``Test`` (projede yoksa ``Task`` + ``test-case`` etiketi);
özet; açıklama Jira görev şablonunda (``case_description_adf``: ADF adım tablosu, onaylayan,
kaynak story, kimlik/hash izi); etiketler ``AI-generated`` ve ``tp-<uuid>``; story bağlantısı
``is tested by`` (``Test`` bağlantı türü), yoksa ``Relates``.
Idempotency: yayından önce ``labels = tp-<uuid>`` araması.

Bu katman yalnızca **onaylı** case'leri yazar; onay ve içerik hash kontrolü çağıranın (yayın
iş akışının) sorumluluğundadır.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import httpx
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from tp_core.integrations import jira_adf as adf
from tp_core.integrations.jira import (
    JiraAuthError,
    JiraBadRequest,
    JiraError,
    JiraNotFound,
    JiraSettings,
    get_jira,
    get_jira_settings,
)
from tp_core.ports import JiraPort, PublishedCase, TestManagementPort

log = logging.getLogger(__name__)

AI_LABEL = "AI-generated"
FALLBACK_LABEL = "test-case"
TEST_LINK = "Test"
RELATES_LINK = "Relates"


class TestManagementError(Exception):
    """Yayın başarısız. Issue oluşturulduysa ``external_key`` doludur (kısmi başarı)."""

    __test__ = False  # pytest bunu test sınıfı sanmasın

    def __init__(self, message: str, external_key: str | None = None) -> None:
        super().__init__(message)
        self.external_key = external_key


# -------------------------------------------------------------------- case içeriği


class CaseStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    action: str
    data: str | None = None
    expected: str = ""


class CaseContent(BaseModel):
    """Onaylı case (TEKNIK-TASARIM §7 test case şeması + kimlik ve onay bilgisi)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    case_id: UUID = Field(validation_alias=AliasChoices("case_id", "id"))
    title: str = Field(min_length=1)
    type: str | None = None
    risk: str | None = None
    acceptance_criteria_refs: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    steps: list[CaseStep] = Field(default_factory=list)
    expected_result: str = ""
    approved_by: str | None = Field(
        default=None, validation_alias=AliasChoices("approved_by", "onaylayan")
    )
    content_hash: str | None = Field(
        default=None,
        validation_alias=AliasChoices("content_hash", "approved_hash", "onaylanan_hash"),
    )
    # Üretim modunun görünen adı (ör. "REPLAY (…)"); yayın iş akışı verir, içerik hash'ine girmez.
    uretim_modu: str | None = None

    @classmethod
    def from_mapping(cls, case: Mapping[str, Any]) -> CaseContent:
        """Düz şema ya da ``{"id": ..., "icerik"/"content": {şema}}`` biçimini kabul eder."""
        data = dict(case)
        for nested in ("icerik", "content"):
            inner = data.pop(nested, None)
            if isinstance(inner, Mapping):
                data = {**inner, **data}
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise TestManagementError(f"Geçersiz case içeriği: {exc}") from exc

    @property
    def tp_label(self) -> str:
        return tp_label(self.case_id)


def tp_label(case_id: UUID) -> str:
    return f"tp-{case_id}"


# Şema değerleri (rules/schemas/case_generation.schema.json) → Jira açıklamasındaki Türkçe karşılık.
CASE_TYPE_TR = {"positive": "pozitif", "negative": "negatif", "boundary": "sınır değer"}
CASE_RISK_TR = {"high": "yüksek", "medium": "orta", "low": "düşük"}


def case_description_adf(
    case: CaseContent, story_key: str, *, steps_table: bool = True
) -> dict[str, Any]:
    """Jira Test issue açıklaması, görev şablonunda (``jira_adf.TEMPLATE_SECTIONS``).

    Objective: case başlığı + köken · Scope: tür, risk, kapsanan AC'ler · User Flow: ön koşullar +
    adım tablosu (#, Adım, Veri, Beklenen) · Dependencies: kaynak story · Other: üretim modu ·
    Acceptance Criteria: beklenen sonuç + AC'ler · QA Checklist: adım başına beklenen. Son satır
    kimlik/hash izidir (``Kimlik: tp-… · onaylanan içerik hash: …``); yayın, mevcut issue'nun
    içeriğini bu satırdan doğrular. Xray yolu (``steps_table=False``) adımları Xray adım
    alanında taşır; açıklamada tablo yerine adım sayısı yazılır.
    """
    origin = "AI tarafından üretildi, insan onayından geçti."
    if case.approved_by:
        origin = f"AI tarafından üretildi; onaylayan: {case.approved_by}."
    refs = ", ".join(case.acceptance_criteria_refs)

    scope = []
    if case.type:
        scope.append(f"Test türü: {CASE_TYPE_TR.get(case.type, case.type)}")
    if case.risk:
        scope.append(f"Risk: {CASE_RISK_TR.get(case.risk, case.risk)}")
    if refs:
        scope.append(f"Kapsanan kabul kriterleri: {refs}")

    flow: list[dict[str, Any]] = []
    if case.preconditions:
        flow += [adf.paragraph("Ön koşullar:"), adf.bullet_list(case.preconditions)]
    if case.steps and steps_table:
        flow.append(
            adf.table(
                ["#", "Adım", "Veri", "Beklenen"],
                [
                    [str(i), s.action, s.data or "—", s.expected or "—"]
                    for i, s in enumerate(case.steps, start=1)
                ],
            )
        )
    elif case.steps:
        flow.append(adf.paragraph(f"Adımlar Xray test adımlarında ({len(case.steps)} adım)."))

    criteria: list[dict[str, Any]] = []
    if case.expected_result:
        criteria.append(adf.paragraph(case.expected_result))
    if refs:
        criteria.append(adf.paragraph(f"Karşılanan story kriterleri: {refs}"))

    checks = [
        f"Adım {i}: {s.expected}" for i, s in enumerate(case.steps, start=1) if s.expected.strip()
    ]

    trail = f"Kimlik: {case.tp_label}"
    if case.content_hash:
        trail += f" · onaylanan içerik hash: {case.content_hash}"
    return adf.template_doc(
        {
            "objective": [adf.paragraph(f"Doğrulanan: {case.title}"), adf.paragraph(origin)],
            "scope": [adf.bullet_list(scope)] if scope else None,
            "user_flow": flow,
            "dependencies": f"Kaynak story: {story_key}" if story_key else None,
            "other": f"Üretim modu: {case.uretim_modu}" if case.uretim_modu else None,
            "acceptance_criteria": criteria,
            "qa_checklist": [adf.bullet_list(checks)] if checks else None,
        },
        trailer=[adf.paragraph(trail)],
    )


def case_description_text(case: CaseContent, story_key: str, *, steps_table: bool = True) -> str:
    return adf.adf_to_text(case_description_adf(case, story_key, steps_table=steps_table))


# ------------------------------------------------------------- ortak yardımcılar


def find_by_label(jira: JiraPort, project: str, case_id: UUID) -> str | None:
    hits = jira.search(f'project = "{project}" AND labels = "{tp_label(case_id)}"', max_results=1)
    return hits[0].key if hits else None


def link_to_story(
    jira: JiraPort, test_key: str, story_key: str, available: list[str] | None
) -> str:
    """Test → story bağlantısı (story tarafında "is tested by"); yoksa ``Relates``.

    Kullanılan bağlantı türünün adını döner.
    """
    candidates = [TEST_LINK, RELATES_LINK]
    if available is not None:
        candidates = [c for c in candidates if c in available]
        if not candidates:
            raise TestManagementError(
                "Jira projesinde 'Test' ya da 'Relates' bağlantı türü yok", test_key
            )
    last: Exception | None = None
    for link_type in candidates:
        try:
            jira.link_issues(test_key, story_key, link_type)
            return link_type
        except (JiraBadRequest, JiraNotFound) as exc:
            log.warning("Bağlantı türü %s kullanılamadı: %s", link_type, exc)
            last = exc
    raise TestManagementError(f"{test_key} story'ye bağlanamadı: {last}", test_key)


def _available_link_types(jira: JiraPort) -> list[str] | None:
    fn = getattr(jira, "link_type_names", None)
    if fn is None:
        return None
    try:
        return list(fn())
    except JiraAuthError:
        raise
    except JiraError as exc:
        log.warning("Bağlantı türleri okunamadı: %s", exc)
        return None


def _url(jira: JiraPort, key: str) -> str | None:
    fn = getattr(jira, "issue_url", None)
    return fn(key) if fn else None


# --------------------------------------------------------------- Jira Test issue


class JiraTestManagement:
    """Onaylı case'i Jira'da ``Test`` issue'su olarak yayınlar (Xray'siz yol, CCI'ın yolu)."""

    name = "jira"

    def __init__(self, jira: JiraPort, project: str) -> None:
        self.jira = jira
        self.project = project
        self._issue_type: str | None = None
        self._link_types: list[str] | None = None
        self._link_types_loaded = False

    def find_existing(self, case_id: UUID) -> str | None:
        return find_by_label(self.jira, self.project, case_id)

    def _resolve_issue_type(self) -> str:
        if self._issue_type is None:
            fn = getattr(self.jira, "issue_types", None)
            if fn is not None:
                try:
                    types = list(fn(self.project))
                    self._issue_type = "Test" if "Test" in types else "Task"
                except JiraAuthError:
                    raise
                except JiraError as exc:
                    log.warning("Issue türleri okunamadı, Test denenecek: %s", exc)
                    return "Test"
            else:
                return "Test"
        return self._issue_type

    def _create(self, case: CaseContent, story_key: str) -> str:
        description = case_description_adf(case, story_key)
        labels = [AI_LABEL, case.tp_label]
        issue_type = self._resolve_issue_type()
        if issue_type == "Test":
            try:
                return self.jira.create_issue(
                    self.project,
                    "Test",
                    case.title,
                    "",
                    labels,
                    fields={"description": description},
                )
            except JiraBadRequest as exc:
                if "issuetype" not in exc.errors:
                    raise
                log.warning("Projede Test türü yok; Task + %s kullanılıyor", FALLBACK_LABEL)
                self._issue_type = "Task"
        return self.jira.create_issue(
            self.project,
            "Task",
            case.title,
            "",
            [*labels, FALLBACK_LABEL],
            fields={"description": description},
        )

    def publish_case(self, case: Mapping[str, Any], story_key: str) -> PublishedCase:
        content = CaseContent.from_mapping(case)
        key = self.find_existing(content.case_id) or self._create(content, story_key)
        if not self._link_types_loaded:
            self._link_types = _available_link_types(self.jira)
            self._link_types_loaded = True
        link_to_story(self.jira, key, story_key, self._link_types)
        return PublishedCase(case_id=content.case_id, external_key=key, url=_url(self.jira, key))


# ---------------------------------------------------------------------- fabrika


def get_test_management(
    settings: JiraSettings | None = None,
    *,
    jira: JiraPort | None = None,
    http: httpx.Client | None = None,
) -> TestManagementPort:
    """``TP_TEST_MGMT=jira|xray`` ile seçilen yayın arka ucu."""
    s = settings or get_jira_settings()
    j = jira or get_jira(s, http=http)
    if s.test_mgmt == "xray":
        from tp_core.integrations.xray import XrayTestManagement, get_xray_client

        return XrayTestManagement(get_xray_client(s, http=http), j, s.jira_project)
    return JiraTestManagement(j, s.jira_project)
