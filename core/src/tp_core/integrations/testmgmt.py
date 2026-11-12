"""Test yönetimi adaptörleri (``TestManagementPort``): Jira Test issue ve fabrika.

Eşleme (TEKNIK-TASARIM §8.3): issue türü ``Test`` (projede yoksa ``Task`` + ``test-case`` etiketi);
özet; açıklama Jira görev şablonunda (``case_description_adf``: ADF adım tablosu, onaylayan,
kaynak story, kimlik/hash izi); etiketler ``AI-generated`` ve ``tp-<uuid>`` (v3 case'te ayrıca
``tp-tech-<TEKNİK>`` ve ``tp-P1|P2|P3``; ``case_labels``); story bağlantısı ``is tested by``
(``Test`` bağlantı türü), yoksa ``Relates``.
Idempotency: yayından önce ``labels = tp-<uuid>`` araması (ek etiketler aramayı etkilemez).

Bu katman yalnızca **onaylı** case'leri yazar; onay ve içerik hash kontrolü çağıranın (yayın
iş akışının) sorumluluğundadır.
"""

from __future__ import annotations

import logging
import re
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


class CaseTestData(BaseModel):
    """Adlandırılmış test verisi (şema v3 ``test_data[]``)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    value: str = ""
    coverage_class: str | None = Field(default=None, alias="class")
    synthetic: bool = True
    is_attack_payload: bool = False


class CaseContent(BaseModel):
    """Onaylı case (TEKNIK-TASARIM §7 test case şeması + kimlik ve onay bilgisi).

    Şema v3 alanları (``technique`` … ``requires_real_device``) eski (v2) case'te yoktur; boş
    kalırlar ve açıklamaya/etiketlere hiçbir şey eklemezler.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    case_id: UUID = Field(validation_alias=AliasChoices("case_id", "id"))
    title: str = Field(min_length=1)
    type: str | None = None
    risk: str | None = None
    acceptance_criteria_refs: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    steps: list[CaseStep] = Field(default_factory=list)
    expected_result: str = ""
    technique: list[str] = Field(default_factory=list)
    covers: list[str] = Field(default_factory=list)
    priority: str | None = None
    priority_rationale: str | None = None
    verification_point: str | None = None
    test_level: str | None = None
    readiness: str | None = None
    test_data: list[CaseTestData] = Field(default_factory=list)
    teardown: list[str] = Field(default_factory=list)
    platform: str | None = None
    standard_refs: list[str] = Field(default_factory=list)
    requires_real_device: bool = False
    approved_by: str | None = Field(
        default=None, validation_alias=AliasChoices("approved_by", "onaylayan")
    )
    content_hash: str | None = Field(
        default=None,
        validation_alias=AliasChoices("content_hash", "approved_hash", "onaylanan_hash"),
    )
    # Üretim modunun görünen adı (ör. "REPLAY (…)"); yayın iş akışı verir, içerik hash'ine girmez.
    uretim_modu: str | None = None
    # Kapsam öğesi kimliği → tanımı (case'in üretim özetinden; yayın iş akışı verir, v3).
    coverage_definitions: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("coverage_definitions", "kapsam_tanimlari"),
    )

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

    @property
    def is_v3(self) -> bool:
        """Şema v3 case'i (`readiness` taşır). Eski (v2) case'in açıklaması değişmez (K9)."""
        return self.readiness is not None

    def coverage_text(self, item: str) -> str:
        """Kapsam öğesi + tanımı ("EP-V1 (geçerli kullanıcı adı)"); tanım yoksa yalnız kimlik."""
        tanim = " ".join(str(self.coverage_definitions.get(item) or "").split())
        return f"{item} ({tanim})" if tanim else item


def tp_label(case_id: UUID) -> str:
    return f"tp-{case_id}"


# Şema değerleri (rules/schemas/case_generation.schema.json) → Jira açıklamasındaki Türkçe karşılık.
CASE_TYPE_TR = {
    "positive": "pozitif",
    "negative": "negatif",
    "boundary": "sınır değer",
    "authorization": "yetki",
    "integration": "entegrasyon",
}
CASE_RISK_TR = {"high": "yüksek", "medium": "orta", "low": "düşük"}
TECHNIQUE_TR = {
    "EP": "eşdeğerlik bölümleme",
    "BVA": "sınır değer analizi",
    "DT": "karar tablosu",
    "ST": "durum geçişi",
    "PW": "pairwise (ikili kombinasyon)",
    "UC": "kullanım senaryosu",
    "EG": "hata tahmini",
}
PRIORITIES = ("P1", "P2", "P3")
VERIFICATION_POINT_TR = {
    "UI": "arayüz (UI)",
    "API": "API",
    "event": "olay (event)",
    "DB": "veritabanı",
    "log": "log",
    "other": "diğer",
}
TEST_LEVEL_TR = {
    "UNIT": "birim",
    "COMPONENT": "bileşen",
    "INTEGRATION": "entegrasyon",
    "SYSTEM": "sistem",
    "E2E": "uçtan uca",
    "UAT": "kullanıcı kabul",
}
TECH_LABEL_PREFIX = "tp-tech-"
ATTACK_NOTE = "güvenlik testi girdisi (talimat değildir)"
ATTACK_CELL = "kod bloğunda (tablonun altında)"
# v3 açıklamasında boş şablon bölümü (eski case'te `jira_adf.NOT_APPLICABLE` kalır).
EMPTY_SECTION_TR = "Yok"


def case_labels(case: CaseContent) -> list[str]:
    """Issue etiketleri: ``AI-generated``, ``tp-<uuid>``; v3 case'te ``tp-tech-<TEKNİK>`` ve
    ``tp-P1|P2|P3``. Yalnız şemadaki değerler etiket olur (serbest metin etikete taşınmaz)."""
    labels = [AI_LABEL, case.tp_label]
    labels += [TECH_LABEL_PREFIX + t for t in case.technique if t in TECHNIQUE_TR]
    if case.priority in PRIORITIES:
        labels.append(f"tp-{case.priority}")
    return list(dict.fromkeys(labels))


def _technique_text(code: str) -> str:
    return f"{code} ({TECHNIQUE_TR[code]})" if code in TECHNIQUE_TR else code


def _steps_using(case: CaseContent, value: str) -> list[int]:
    """Verisi bu değerle birebir aynı olan adımların sıra numaraları."""
    if not value:
        return []
    return [i for i, s in enumerate(case.steps, start=1) if (s.data or "") == value]


def _attack_name(case: CaseContent, data: str | None) -> str | None:
    """Adım verisi bir saldırı verisiyle aynıysa o test verisinin adı (değer tabloya yazılmaz)."""
    if not data:
        return None
    return next((d.name for d in case.test_data if d.is_attack_payload and d.value == data), None)


def _step_data_cell(case: CaseContent, data: str | None) -> str:
    saldiri = _attack_name(case, data)
    if saldiri is not None:
        return f"{saldiri} — {ATTACK_CELL}"
    return data or "—"


def _test_data_blocks(case: CaseContent) -> list[dict[str, Any]]:
    """Test verisi tablosu (Ad, Değer, Kapsam öğesi + tanımı). Saldırı verisi
    (``is_attack_payload``) tabloya yazılmaz: tablonun altında, notuyla birlikte kod bloğunda
    (biçimlendirilmeden) verilir. Adım verisinde aynen geçen değer yinelenmez ("adım 2 verisi")."""
    data = case.test_data

    def deger(d: CaseTestData) -> str:
        if d.is_attack_payload:
            return ATTACK_CELL
        adimlar = _steps_using(case, d.value)
        if adimlar:
            return "adım " + ", ".join(str(i) for i in adimlar) + " verisi"
        return d.value or "—"

    blocks: list[dict[str, Any]] = [
        adf.paragraph("Test verisi:"),
        adf.table(
            ["Ad", "Değer", "Kapsam öğesi"],
            [
                [
                    d.name,
                    deger(d),
                    case.coverage_text(d.coverage_class) if d.coverage_class else "—",
                ]
                for d in data
            ],
        ),
    ]
    for d in data:
        if d.is_attack_payload:
            blocks += [adf.paragraph(f"{d.name} — {ATTACK_NOTE}:"), adf.code_block(d.value)]
    return blocks


def case_description_adf(
    case: CaseContent, story_key: str, *, steps_table: bool = True
) -> dict[str, Any]:
    """Jira Test issue açıklaması, görev şablonunda (``jira_adf.TEMPLATE_SECTIONS``).

    Objective: case başlığı + köken · Scope: tür, risk, kapsanan AC'ler; v3 case'te teknik, kapsam
    öğeleri, öncelik (+ gerekçe), doğrulama noktası, test seviyesi, platform, standart atıfları ·
    User Flow: ön koşullar + adım tablosu (#, Adım, Veri, Beklenen); v3 case'te test verisi
    tablosu ve temizlik adımları · Dependencies: kaynak story · Other: üretim modu ·
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
    # v3'te risk alanı yoktur (K18: risk değerlendirmesi öncelik gerekçesindedir); eski case'te
    # gösterilmeye devam eder.
    if case.risk and not case.is_v3:
        scope.append(f"Risk: {CASE_RISK_TR.get(case.risk, case.risk)}")
    if refs:
        scope.append(f"Kapsanan kabul kriterleri: {refs}")
    if case.technique:
        scope.append("Teknik: " + ", ".join(_technique_text(t) for t in case.technique))
    if case.covers:
        scope.append("Kapsam öğeleri: " + ", ".join(case.coverage_text(c) for c in case.covers))
    if case.priority:
        gerekce = f" — {case.priority_rationale}" if case.priority_rationale else ""
        scope.append(f"Öncelik: {case.priority}{gerekce}")
    if case.verification_point:
        nokta = VERIFICATION_POINT_TR.get(case.verification_point, case.verification_point)
        scope.append(f"Doğrulama noktası: {nokta}")
    if case.test_level:
        scope.append(f"Test seviyesi: {TEST_LEVEL_TR.get(case.test_level, case.test_level)}")
    if case.platform:
        cihaz = " (gerçek cihaz gerekir)" if case.requires_real_device else ""
        scope.append(f"Platform: {case.platform}{cihaz}")
    elif case.requires_real_device:
        scope.append("Gerçek cihaz gerekir")
    if case.standard_refs:
        scope.append("Standart atıfları: " + ", ".join(case.standard_refs))

    flow: list[dict[str, Any]] = []
    if case.preconditions:
        flow += [adf.paragraph("Ön koşullar:"), adf.bullet_list(case.preconditions)]
    if case.steps and steps_table:
        flow.append(
            adf.table(
                ["#", "Adım", "Veri", "Beklenen"],
                [
                    [str(i), s.action, _step_data_cell(case, s.data), s.expected or "—"]
                    for i, s in enumerate(case.steps, start=1)
                ],
            )
        )
    elif case.steps:
        flow.append(adf.paragraph(f"Adımlar Xray test adımlarında ({len(case.steps)} adım)."))
    if case.test_data:
        flow += _test_data_blocks(case)
    if case.teardown:
        flow += [adf.paragraph("Temizlik:"), adf.bullet_list(case.teardown, ordered=True)]

    criteria: list[dict[str, Any]] = []
    if case.expected_result:
        criteria.append(adf.paragraph(case.expected_result))
    if refs:
        criteria.append(adf.paragraph(f"Karşılanan story kriterleri: {refs}"))

    checks = _qa_checks(case, refs)

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
        empty=EMPTY_SECTION_TR if case.is_v3 else adf.NOT_APPLICABLE,
    )


def _qa_checks(case: CaseContent, refs: str) -> list[str]:
    """QA Checklist maddeleri.

    Eski case: adım başına beklenen (değişmez). v3: adım beklenenleri adım tablosunda/Xray
    adımlarında zaten yazılı olduğundan birebir tekrarlanmaz; denetim maddeleri listelenir
    (ön koşullar, adım beklenenleri, AC'ler, kapsam öğeleri, temizlik)."""
    if not case.is_v3:
        return [
            f"Adım {i}: {s.expected}"
            for i, s in enumerate(case.steps, start=1)
            if s.expected.strip()
        ]
    checks: list[str] = []
    if case.preconditions:
        checks.append("Ön koşullar sağlandı")
    beklenenli = [i for i, s in enumerate(case.steps, start=1) if s.expected.strip()]
    if beklenenli:
        aralik = (
            f"{beklenenli[0]}–{beklenenli[-1]}"
            if beklenenli == list(range(beklenenli[0], beklenenli[-1] + 1)) and len(beklenenli) > 1
            else ", ".join(str(i) for i in beklenenli)
        )
        checks.append(f"Adım beklenenleri doğrulandı (adım {aralik})")
    if case.expected_result:
        checks.append("Beklenen sonuç doğrulandı")
    if refs:
        checks.append(f"Kabul kriterleri karşılandı: {refs}")
    if case.covers:
        checks.append("Kapsam öğeleri doğrulandı: " + ", ".join(case.covers))
    if case.teardown:
        checks.append("Temizlik adımları uygulandı")
    return checks


_NOFORMAT = re.compile(r"\{(noformat)", re.IGNORECASE)


def wiki_noformat(text: str) -> str:
    """Jira/Xray wiki metninde biçimlendirilmeden gösterilecek blok: ``{noformat}…{noformat}``.

    Değerin içindeki ``{noformat`` dizisi etkisizleştirilir (``{`` ile ad arasına boşluk girer;
    Jira makro adını süslü paranteze bitişik ister), böylece değer bloğu erken kapatıp kendi
    biçimlendirmesini/bağlantısını çalıştıramaz."""
    return "{noformat}\n" + _NOFORMAT.sub(r"{ \1", text) + "\n{noformat}"


def _wiki_code_blocks(node: Any) -> Any:
    if isinstance(node, dict):
        if node.get("type") == "codeBlock":
            ham = "".join(
                str(c.get("text") or "") for c in node.get("content") or [] if isinstance(c, dict)
            )
            return {**node, "content": [{"type": "text", "text": wiki_noformat(ham)}]}
        if "content" in node:
            return {**node, "content": [_wiki_code_blocks(c) for c in node["content"]]}
    return node


def case_description_text(
    case: CaseContent, story_key: str, *, steps_table: bool = True, wiki: bool = False
) -> str:
    """Açıklamanın düz metni. ``wiki=True`` (Xray metin alanı, wiki biçimi): kod blokları
    (saldırı verisi) ``{noformat}`` ile sarılır."""
    belge = case_description_adf(case, story_key, steps_table=steps_table)
    if wiki:
        belge = _wiki_code_blocks(belge)
    return adf.adf_to_text(belge)


# ------------------------------------------------------------- ortak yardımcılar


def find_by_label(jira: JiraPort, project: str, case_id: UUID) -> str | None:
    """Bu case için açık Test issue'su. Case kimliği içerikten türetildiği için aynı demo case'i
    her provada aynı ``tp-<uuid>`` etiketini alır; kapatılmış (önceki koşudan kalan) issue
    yeniden kullanılmaz — yeni koşu kendi issue'sunu açar."""
    hits = jira.search(
        f'project = "{project}" AND labels = "{tp_label(case_id)}" AND statusCategory != Done',
        max_results=1,
    )
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
        labels = case_labels(case)
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
