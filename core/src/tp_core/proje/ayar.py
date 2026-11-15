"""Proje başına çalışma anı config erişimi (TP-COK-PROJE-PLANI §3.2).

Çözüm sırası: proje etkin config (legacy env adıyla, `kaynak_bagla` ile bağlanan çözücü) →
`os.environ` (yalnız `pid == varsayilan_pid()`; geçiş geriye uyumluluğu) → `varsayilan`.

Şerit 0: çözücü bağlı değil → tek proje, `os.environ` (bugünkü davranış birebir). Şerit 2 Home
kaynağını `kaynak_bagla(cozucu, surumcu)` ile bağlar; bundan sonra `pid` verilmeyen ve bağlam
olmayan çağrı `ProjeBaglamiYok` verir (çok projede sessizce varsayılana düşülmez).

`PROJE_ANAHTARLARI`: §3.3 T/A/P sınıfı legacy env adları; statik test bu adları
`os.environ`/`os.getenv` ile okuyan kodu işaretler (yalnız `home_config/` ve bu modül izinli).
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping

from tp_core.proje.baglam import ProjeBaglamiYok, varsa, varsayilan_pid

_ORG: frozenset[str] = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_WORKSPACE_ID",
        "TP_MODEL_PROVIDER",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_ENDPOINT",
        "TP_PII_MASKING",
        "TP_DAILY_BUDGET_USD",
        "JIRA_BASE_URL",
        "JIRA_BROWSE_URL",
        "JIRA_CREATE_URL",
        "JIRA_READ_EMAIL",
        "JIRA_READ_TOKEN",
        "JIRA_WRITE_EMAIL",
        "JIRA_WRITE_TOKEN",
        "XRAY_BASE_URL",
        "XRAY_CLIENT_ID",
        "XRAY_CLIENT_SECRET",
        "TP_JIRA_BOT_ACCOUNT_IDS",
        "GITHUB_API_URL",
        "TP_FORGE_WEB_URL",
        "GH_APP_INSTALLATION_ID",
        "GITHUB_TOKEN",
        "GITHUB_READ_TOKEN",
        "GITHUB_ACTIONS_READ_TOKEN",
        "GITHUB_MERGE_TOKEN",
        "TP_FORGE_REMOTE_TOKEN",
        "TP_GITHUB_ARTIFACTS_KEEP",
        "TP_GITHUB_ARTIFACTS_MAX_GB",
        "TP_CODEGEN_SCREENSHOT_DAYS",
        "AIPROBE_IDLE_S",
        "AIPROBE_ABSOLUTE_S",
        "AIPROBE_ALLOWED_ORGS",
    }
)

_PROJE: frozenset[str] = frozenset(
    {
        "JIRA_PROJECT",
        "TP_TEST_MGMT",
        "JIRA_PO_ACCOUNT_IDS",
        "TP_PO_JIRA_USERS",
        "JIRA_HESAP_ANALIST",
        "JIRA_HESAP_MUHENDIS",
        "JIRA_HESAP_PO",
        "JIRA_HESAP_TESTCI",
        "CONTENT_FIELDS",
        "TP_FORGE",
        "GITHUB_REPO",
        "TP_FORGE_REMOTE_URL",
        "TP_FORGE_APP_ROOT",
        "TP_FORGE_REPO_NAME",
        "TP_FORGE_CHECK_REF",
        "PROTECTED_BRANCHES",
        "TP_REQUIRED_CHECKS",
        "TP_PLATFORMS",
        "TP_WEB_DILLERI",
        "TP_FORGE_REQUIRE_UP_TO_DATE",
        "BYPASS_ACTOR",
        "TP_CI_NIGHTLY_SAAT",
        "TP_CI_NIGHTLY_GEC_S",
        "TP_MANUAL_BASELINE_S",
        "TP_DEMO_WEB_URL",
        "TP_AGENT_DEALER",
        "TP_AGENT_DEALER_PASSWORD",
        "TP_PROBE_PASSWORD",
        "VERIFY_AGENT_DEALER",
        "VERIFY_AGENT_DEALER_NAME",
        "VERIFY_BASE_URL",
        "DEMOAPP_RO_DATABASE_URL",
        "DEMOAPP_RO_PASSWORD",
        "TP_TESTVERI_DEMO_PAROLA",
    }
)

_URUN: frozenset[str] = frozenset(
    {
        "TP_WORKFLOW_BUDGET_USD",
        "TP_CI_KOSU_ZAMAN_ASIMI_S",
        "TP_CI_GITHUB_TIMEOUT_S",
        "TP_TRIAGE_KIRMA",
        "TP_TRIAGE_KIRMA_TASLAK",
        "TP_REPAIR_ARIA_FALLBACK",
        "TP_DENETIM_KAPISI",
        "TP_DENETIM_GUNLUK_SINIR",
        "TP_REVIEW_GUNLUK_SINIR",
        "TP_CONSISTENCY_MAX_ROUNDS",
        "TP_HATA_KOSUSU_GECERLI_ESIK",
        "HEDEFLER",
        "TP_CT_SON_KOSU",
        "TP_CT_FLAKY_GUN",
        "TP_CT_TREND_GUN",
        "TP_CT_REVIEW_MIN_S",
        "TP_CODEGEN_STEP5_BUDGET_S",
        "TP_ASISTAN_ONERI",
        "TP_ASISTAN_OTOMATIK_DERIN",
        "TP_ASISTAN_VERI_ROLLERI",
        "TP_ASISTAN_DENETIM_ENGEL",
        "TP_ASISTAN_DENETIM_UYARI",
        "TP_KURAL_YENIDEN_ISTEME",
    }
)

PROJE_ANAHTARLARI: frozenset[str] = _ORG | _PROJE | _URUN

_DOGRU = frozenset({"1", "true", "yes", "on", "evet", "acik"})
_YANLIS = frozenset({"0", "false", "no", "off", "hayir", "kapali", ""})

_KILIT = threading.RLock()
_COZUCU: Callable[[str], Mapping[str, str] | None] | None = None
_SURUMCU: Callable[[str], str] | None = None
# Testler (`proje_ayar` fikstürü): pid → ad → değer; çözücünün önünde. Sürüm sayacı önbellekleri
# geçersiz kılar.
_UST: dict[str, dict[str, str]] = {}
_UST_SURUM = 0


def kaynak_bagla(
    cozucu: Callable[[str], Mapping[str, str] | None], surumcu: Callable[[str], str]
) -> None:
    """Proje etkin config kaynağını bağlar (Şerit 2). `cozucu(pid)` legacy env adı → değer
    haritası (proje bilinmiyorsa None), `surumcu(pid)` etag."""
    global _COZUCU, _SURUMCU
    with _KILIT:
        _COZUCU, _SURUMCU = cozucu, surumcu


def _kaynak_coz() -> None:
    """Kaynak bağını kaldırır (test; tek proje env davranışına dönüş)."""
    global _COZUCU, _SURUMCU
    with _KILIT:
        _COZUCU = _SURUMCU = None


def _ust_ayarla(pid: str, degerler: Mapping[str, str | None]) -> None:
    global _UST_SURUM
    with _KILIT:
        hedef = _UST.setdefault(pid, {})
        for ad, deger in degerler.items():
            if deger is None:
                hedef.pop(ad, None)
            else:
                hedef[ad] = str(deger)
        _UST_SURUM += 1


def _ust_temizle() -> None:
    global _UST_SURUM
    with _KILIT:
        _UST.clear()
        _UST_SURUM += 1


def _pid(pid: str | None) -> str:
    if pid is not None:
        return pid
    b = varsa()
    if b is not None:
        return b.pid
    if _COZUCU is None:
        return varsayilan_pid()
    raise ProjeBaglamiYok("proje ayarı bağlamsız okundu (pid verin ya da proje_icinde kurun)")


def _ham(ad: str, pid: str | None) -> str | None:
    p = _pid(pid)
    with _KILIT:
        ust = _UST.get(p)
        if ust is not None and ad in ust:
            return ust[ad]
        cozucu = _COZUCU
    if cozucu is not None:
        harita = cozucu(p)
        if harita is not None and ad in harita:
            return harita[ad]
    if p == varsayilan_pid():
        return os.environ.get(ad)
    return None


def ayar(ad: str, varsayilan: str | None = None, *, pid: str | None = None) -> str | None:
    deger = _ham(ad, pid)
    return varsayilan if deger is None else deger


def ayar_bool(ad: str, varsayilan: bool = False, *, pid: str | None = None) -> bool:
    deger = _ham(ad, pid)
    if deger is None:
        return varsayilan
    d = deger.strip().lower()
    if d in _DOGRU:
        return True
    if d in _YANLIS:
        return False
    return varsayilan


def ayar_int(ad: str, varsayilan: int, *, pid: str | None = None) -> int:
    deger = _ham(ad, pid)
    if deger is None or not deger.strip():
        return varsayilan
    try:
        return int(deger.strip())
    except ValueError:
        return varsayilan


def ayar_float(ad: str, varsayilan: float, *, pid: str | None = None) -> float:
    deger = _ham(ad, pid)
    if deger is None or not deger.strip():
        return varsayilan
    try:
        return float(deger.strip())
    except ValueError:
        return varsayilan


def sir(ad: str, *, pid: str | None = None) -> str | None:
    """Sır değeri (Şerit 2: Secret Manager, proje başına); boş değer None."""
    return _ham(ad, pid) or None


def ozellik_acik(ad: str, *, pid: str | None = None) -> bool:
    """Proje özelliği (`web`/`android`/`ios`/`windows`/`ai_agent`).

    Şerit 0: süreç geneli `home_config.durum.ozellik_acik` (Home config yoksa her özellik açık);
    Şerit 2 proje başına durumu bağlar.
    """
    _pid(pid)
    from tp_core.home_config import durum

    return durum.ozellik_acik(ad)


def surum(pid: str | None = None) -> str:
    """Config sürümü (etag); istemci/ayar önbellek anahtarı `(pid, surum(pid))`."""
    p = _pid(pid)
    with _KILIT:
        surumcu = _SURUMCU
        ust = _UST_SURUM
    taban = "env" if surumcu is None else surumcu(p)
    return f"{taban}+{ust}" if ust else taban
