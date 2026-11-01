"""Ajan amaçlarının (consistency_check, verify_and_map) canlı değerlendirmesi için araç ortamları.

Değerlendirme setinde `"agent": {"tool_env": <ad>, "max_turns": n}` taşıyan paketler, modelin
araç çağrılarını ÜRETİMDEKİ araç uygulamalarıyla yürütür (sahte araç sonucu yoktur; aksi hâlde
canlı değerlendirme ölçmesi gereken şeyi ölçmezdi):

- `consistency`: `features.requirements` kod araçları (`CodeTools`: forge üzerinde salt okuma,
  sabit commit) + veri araçları (`DataTools`: `DEMOAPP_RO_DATABASE_URL` salt okuma rolü). Bulgu
  kanıtları üretimdeki `EvidenceVerifier` ile aynı commit/veritabanında YENİDEN doğrulanır;
  doğrulanamayan kanıt vakayı düşürür (§8.2b adım 4).
- `browser`: kod üretiminin Playwright MCP oturumu (`AgentBrowser` + `McpBrowserSession`,
  doğrulama bayisi bayi3; `replay_check` ile aynı kurulum, ajan bayisi kilidi alınır).

Ortam kurulamazsa (`ToolEnvUnavailable`: forge/veritabanı/MCP erişilemiyor) vaka ÇAĞRILMAZ ve
koşu eksik sayılır; durum "canlı değerlendirme bekliyor" kalır. Bu ortamlar compose yığınını ister
(`make up`): host'tan koşturulursa `DEMOAPP_RO_DATABASE_URL`, `TP_FORGE_PATH` ve
`PLAYWRIGHT_MCP_URL` host'a açılmış adresleri göstermelidir; yoksa core-worker içinde koşturun.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any

from tp_core.ports import ToolExecutor, ToolSpec


class ToolEnvUnavailable(RuntimeError):
    """Ajan araç ortamı kurulamadı (yığın kapalı, yapılandırma eksik)."""


@dataclass
class ToolEnv:
    name: str
    tools: list[ToolSpec]
    execute: ToolExecutor
    close: Callable[[], None] = lambda: None
    # Çıktıya ortama özgü ek denetim (ör. kanıtın yeniden doğrulanması); boş liste = geçti.
    check: Callable[[Any, Mapping[str, Any]], list[str]] = field(default=lambda output, expect: [])


EnvFactory = Callable[[], ToolEnv]


def _consistency_env() -> ToolEnv:  # pragma: no cover - canlı yığın (forge + demo-app PG)
    from tp_core.features.requirements import services
    from tp_core.features.requirements.codetools import TOOL_SPECS, CodeTools
    from tp_core.features.requirements.datatools import DataTools
    from tp_core.features.requirements.settings import get_requirements_settings
    from tp_core.features.requirements.verifier import EvidenceVerifier

    ayar = get_requirements_settings()
    try:
        forge = services.forge()
        sha = forge.head_sha(ayar.forge_ref)
        db = services.demo_db()
        db.schema()  # erişim denetimi: bağlanamıyorsa vakayı çağırmadan dur
    except Exception as exc:
        raise ToolEnvUnavailable(
            f"kod/veri araçları kurulamadı ({type(exc).__name__}: {str(exc)[:200]}); "
            "forge (TP_FORGE_PATH) ve DEMOAPP_RO_DATABASE_URL gerekli (make up)"
        ) from exc
    code = CodeTools(forge, sha, ayar.forge_repo)
    data = DataTools(db)
    table: dict[str, Callable[[dict[str, Any]], str]] = {
        "search_code": code.search_code,
        "get_file_contents": code.get_file_contents,
        "db_schema": data.db_schema,
        "db_query": data.db_query,
    }

    def execute(name: str, args: dict[str, Any]) -> str:
        fn = table.get(name)
        if fn is None:
            raise PermissionError(f"Araç izinli değil: {name}")
        return fn(args or {})

    verifier = EvidenceVerifier(forge, sha, db, repo=ayar.forge_repo)

    def check(output: Any, expect: Mapping[str, Any]) -> list[str]:
        acs = list(expect.get("acs") or [])
        out = []
        for finding in (output or {}).get("findings") or []:
            result = verifier.verify(finding, acs)
            if not result.ok:
                reasons = "; ".join(c.get("neden", "") for c in result.checks if not c.get("ok"))
                out.append(f"{finding.get('id')}: kanıt doğrulanamadı ({reasons})")
        return out

    return ToolEnv("consistency", list(TOOL_SPECS), execute, check=check)


def _browser_env() -> ToolEnv:  # pragma: no cover - canlı yığın (Playwright MCP + demo-app)
    from tp_core.features.codegen.browser import ajan_bayisi_kilidi
    from tp_core.gateway.replay_check import _production_session

    lock: AbstractContextManager[Any] | None = None
    try:
        lock = ajan_bayisi_kilidi()
        lock.__enter__()
        session = _production_session()
    except (Exception, SystemExit) as exc:
        if lock is not None:
            lock.__exit__(None, None, None)
        raise ToolEnvUnavailable(
            f"Playwright MCP oturumu kurulamadı ({type(exc).__name__}: {str(exc)[:200]}); "
            "compose yığını (playwright-mcp, demo-app-web) ve PLAYWRIGHT_MCP_URL gerekli"
        ) from exc

    def close() -> None:
        try:
            session.close()
        finally:
            if lock is not None:
                lock.__exit__(None, None, None)

    return ToolEnv("browser", session.tools, session.execute, close=close)


ENVS: dict[str, EnvFactory] = {
    "consistency": _consistency_env,
    "browser": _browser_env,
}


def open_env(name: str, envs: Mapping[str, EnvFactory] | None = None) -> ToolEnv:
    table = ENVS if envs is None else envs
    factory = table.get(name)
    if factory is None:
        raise ToolEnvUnavailable(f"bilinmeyen araç ortamı: {name!r}")
    return factory()


def mapping_problems(output: Any, expect: Mapping[str, Any]) -> list[str]:
    """verify_and_map beklentisi (deterministik): her adım eşlenmiş ya da eksik metot olarak
    bildirilmiş, metotlar sembol tablosunda var, beklenen assertion'lar mevcut."""
    out = output if isinstance(output, Mapping) else {}
    failures: list[str] = []
    mapped = {m.get("step_id") for m in out.get("step_mapping") or [] if isinstance(m, Mapping)}
    missing = {m.get("step_id") for m in out.get("missing_methods") or [] if isinstance(m, Mapping)}
    for step in expect.get("steps") or []:
        if step not in mapped and step not in missing:
            failures.append(f"adım {step} eşlenmedi")
    allowed = set(expect.get("methods") or [])
    if allowed:
        for item in [*(out.get("step_mapping") or []), *(out.get("expects") or [])]:
            if not isinstance(item, Mapping):
                continue
            ref = f"{item.get('po')}.{item.get('method')}"
            if ref not in allowed:
                failures.append(f"sembol tablosunda olmayan metot: {ref}")
    have = {f"{e.get('po')}.{e.get('method')}" for e in out.get("expects") or []}
    failures += [
        f"beklenen assertion yok: {m}" for m in expect.get("expects_include") or [] if m not in have
    ]
    if expect.get("no_missing_methods") and missing:
        failures.append(f"eksik metot bildirildi: {sorted(s for s in missing if s)}")
    unverified = [
        m.get("step_id")
        for m in out.get("step_mapping") or []
        if isinstance(m, Mapping) and m.get("verified") is not True
    ]
    if expect.get("all_verified") and unverified:
        failures.append(f"doğrulanmamış adım: {unverified}")
    return failures


def _refs(doc_ref: Any) -> set[str]:
    return {p.strip() for p in str(doc_ref or "").replace("↔", ",").split(",") if p.strip()}


def findings_problems(output: Any, expect: Mapping[str, Any]) -> list[str]:
    """consistency_check beklentisi: beklenen belge yerleri bulguda, engelleyici sayısı sınırda,
    bulgu belgede olmayan AC'ye atıf yapmıyor."""
    out = output if isinstance(output, Mapping) else {}
    findings = [f for f in out.get("findings") or [] if isinstance(f, Mapping)]
    failures: list[str] = []
    seen: set[str] = set()
    for f in findings:
        seen |= _refs(f.get("doc_ref"))
    for ref in expect.get("doc_refs_include") or []:
        if ref not in seen:
            failures.append(f"{ref} için bulgu yok")
    known = {a.split(":", 1)[0].strip() for a in expect.get("acs") or []} | {"Açıklama"}
    unknown = sorted(r for r in seen if r not in known)
    if unknown:
        failures.append(f"belgede olmayan yer: {unknown}")
    blocking = sum(1 for f in findings if f.get("severity") == "blocking")
    if "max_blocking" in expect and blocking > int(expect["max_blocking"]):
        failures.append(f"{blocking} engelleyici bulgu, en çok {expect['max_blocking']}")
    if "min_blocking" in expect and blocking < int(expect["min_blocking"]):
        failures.append(f"{blocking} engelleyici bulgu, en az {expect['min_blocking']}")
    no_evidence = [
        f.get("id")
        for f in findings
        if not f.get("evidence") and f.get("type") != "internal_contradiction"
    ]
    if no_evidence:
        failures.append(f"kanıtsız bulgu: {no_evidence}")
    return failures


def coverage_problems(output: Any, expect: Mapping[str, Any]) -> list[str]:
    """case_generation beklentisi: her AC en az bir case'te, bilinmeyen AC yok, case sayısı,
    metin içerir/içermez (tüm case'lerin birleşik metni)."""
    out = output if isinstance(output, Mapping) else {}
    cases = [c for c in out.get("cases") or [] if isinstance(c, Mapping)]
    failures: list[str] = []
    refs: set[str] = set()
    for c in cases:
        refs |= {str(r) for r in c.get("acceptance_criteria_refs") or []}
    acs = list(expect.get("ac_coverage") or [])
    failures += [f"{ac} hiçbir case'te yok" for ac in acs if ac not in refs]
    if acs:
        extra = sorted(refs - set(acs))
        if extra:
            failures.append(f"belgede olmayan AC: {extra}")
    if len(cases) < int(expect.get("min_cases", 1)):
        failures.append(f"{len(cases)} case, en az {expect.get('min_cases', 1)}")
    blob = _blob(cases)
    failures += [f"'{n}' geçmiyor" for n in expect.get("contains") or [] if n not in blob]
    failures += [f"'{n}' geçmemeli" for n in expect.get("not_contains") or [] if n in blob]
    return failures


def review_problems(output: Any, expect: Mapping[str, Any]) -> list[str]:
    """requirement_review beklentisi: karar, soru türleri, AC atıfları belge içinde."""
    out = output if isinstance(output, Mapping) else {}
    questions = [q for q in out.get("questions") or [] if isinstance(q, Mapping)]
    failures: list[str] = []
    if "verdict" in expect and out.get("verdict") != expect["verdict"]:
        failures.append(f"karar {out.get('verdict')!r}, beklenen {expect['verdict']!r}")
    types = {q.get("type") for q in questions}
    failures += [
        f"'{t}' türünde soru yok" for t in expect.get("question_types") or [] if t not in types
    ]
    refs = {q.get("ac_ref") for q in questions if q.get("ac_ref")}
    within = expect.get("ac_refs_within")
    if within is not None:
        extra = sorted(str(r) for r in refs - set(within))
        if extra:
            failures.append(f"belgede olmayan AC'ye soru: {extra}")
    any_of = expect.get("ac_refs_any")
    if any_of and not refs & set(any_of):
        failures.append(f"şu AC'lerin hiçbirine soru yok: {any_of}")
    if "max_questions" in expect and len(questions) > int(expect["max_questions"]):
        failures.append(f"{len(questions)} soru, en çok {expect['max_questions']}")
    return failures


def _blob(items: Sequence[Any]) -> str:
    import json

    return json.dumps(list(items), ensure_ascii=False)
