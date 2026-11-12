"""Kolon değer kümeleri (CHECK kısıtları). `durum` kümeleri workflow.states'ten gelir."""

from tp_core.workflow.states import KARARLAR, MACHINES, RET_NEDENLERI

ROLLER = frozenset({"analyst", "engineer", "presenter", "po", "tester"})
REQUIREMENT_KAYNAK = frozenset({"jira", "free_text"})
URETIM_MODU = frozenset({"live", "replay", "replay_miss"})
CASE_KANAL = frozenset({"portal", "ide"})
CASE_TUR = frozenset({"positive", "negative", "boundary"})
RISK = frozenset({"high", "medium", "low"})
REVIEW_NESNE = frozenset(KARARLAR)
REVIEW_KARAR = frozenset().union(*KARARLAR.values())
# github: GitHub arayüzünde insanın yaptığı merge (GitHub kipi; çekirdeğe senkronla işlenir, 0010).
REVIEW_KANAL = frozenset({"portal", "jira", "github"})
RET_NEDENI = RET_NEDENLERI
TOKEN_KAPSAM = frozenset({"publish", "submit"})
PO_ONAY_KAYNAGI = frozenset({"jira_label", "portal"})
VERDICT = frozenset({"ready", "needs_po"})
FINDING_TUR = frozenset(
    {
        "internal_contradiction",
        "doc_vs_code",
        "doc_vs_data",
        "missing_in_doc",
        "missing_in_code",
        "ambiguous",
    }
)
SEVERITY = frozenset({"blocking", "warning"})
FINDING_KARAR = KARARLAR["consistency_finding"]
SCRIPT_TUR = frozenset({"test", "locator_fix"})
# 009 §2.1: üretilen testin hedef platformu (web = Playwright/TS; diğerleri Appium/Java). 0018.
PLATFORM = frozenset({"web", "android", "ios", "windows"})
# 011 §2.1–2.2: üretim dili (platformdan bağımsız boyut) ve dilin nereden geldiği. 0021.
DIL = frozenset({"ts", "java", "csharp", "python"})
DIL_KAYNAGI = frozenset({"algilandi", "secildi", "varsayilan"})
RUN_KAYNAK = frozenset({"local", "github", "sauce"})
# CI ile ortak liste: .github/workflows/ci.yml `trigger` girdisi (workflow_dispatch → manual).
RUN_TETIK = frozenset({"pr", "push", "nightly", "deploy", "break_verify", "local_check", "manual"})
RUN_SONUC = frozenset({"queued", "running", "passed", "failed", "error"})
TEST_SONUC = frozenset({"passed", "failed", "flaky", "skipped", "timedout"})
FAILURE_SINIF = frozenset(
    {"environment", "flaky", "test_maintenance", "product_defect", "test_data", "unknown"}
)
KARAR_KAYNAGI = frozenset({"rule", "llm"})
ONERI_TURU = frozenset({"locator_fix", "bug_draft", "none"})
ONERI_DURUMU = frozenset({"none", "proposed", "pr_open", "merged", "rejected"})
BUG_KARAR = frozenset({"new", "link"})
EXTERNAL_SISTEM = frozenset({"jira", "xray", "github", "local_forge"})
EXTERNAL_DURUM = frozenset({"intent", "created", "failed"})
PR_DURUM = frozenset({"open", "merged", "closed"})
JOB_DURUM = frozenset({"queued", "running", "retry", "done", "failed", "cancelled"})
AI_MOD = URETIM_MODU
# asistan (0017): portal içi sohbet asistanının araç çağrıları.
TOOL_KANAL = frozenset({"agent", "ide", "asistan"})

# AI Asistan (0017, AI-ASISTAN-PLANI §8). `asistan_mesaj.durum` workflow.MACHINES'e konmaz.
ASISTAN_ROL = frozenset({"user", "assistant"})
ASISTAN_MESAJ_DURUM = frozenset({"pending", "running", "done", "error", "iptal"})
ASISTAN_BEKLEYEN_DURUM = frozenset({"pending", "running"})
ASISTAN_KAYNAK = frozenset({"model", "sozluk", "sablon", "kapali"})
ASISTAN_AMAC = frozenset({"assistant", "assistant_deep"})
ASISTAN_KIP = frozenset({"soru", "oneri"})
ASISTAN_TETIK = frozenset({"kullanici", "otomatik"})
ASISTAN_MOD = frozenset({"live", "off"})
ASISTAN_GERI_BILDIRIM = frozenset({-1, 1})
# Öneri geri bildirimi: -1 gizle, 1 faydalı, 2 yaptım (§17).
ASISTAN_ONERI_DEGER = frozenset({-1, 1, 2})


def durumlar(entity: str) -> frozenset[str]:
    return MACHINES[entity].states
