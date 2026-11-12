"""Prompt paketlerinin değerlendirme seti ve canlı koşturucusu (constitution X).

`rules/evaluations.yaml` bir paketin durumunu (`pending` / `evaluated` / `waived`) tutar; bu modül
`evaluated` durumunun dayandığı **seti** ve onu koşturan aracı sağlar:

- Set: `rules/evaluation/<paket>.json` — `{"bundle", "purpose", "version", "cases": [...]}`.
  Her vaka kanonik girdi kurucularıyla (`tp_core.gateway.defects`) kurulmuş model mesajlarını
  (`messages`) ve beklentiyi (`expect`) taşır. Setler elle değil, test yardımcılarından üretilir
  (`core/tests/unit/gateway/build_eval_sets.py`); `test_eval_sets` kurucular değişince setin
  bayatladığını yakalar.
- Beklentiler (deterministik, model çıktısına bakar):
  - triage: `class` (tam), `class_in`, `class_not`, `sub_type`;
  - bug_draft: `contains` / `not_contains` ({alan: [metin, …]}; alan `steps` ise adımların
    birleşimi), `story_key`;
  - dup_rank: `candidate_keys` (aramadaki küme; `dup_rank_problems` ile değişmezler), `top`,
    `recommendation`, `link_key`;
  - requirement_review: `verdict`, `question_types`, `ac_refs_within`, `ac_refs_any`,
    `max_questions`;
  - case_generation: `ac_coverage` (AC1..ACn hepsi bir case'te, fazlası yok), `min_cases`,
    `contains` / `not_contains` (case'lerin birleşik metni); set `runs` kez koşar (§12: 5 story ×
    3 koşu);
  - consistency_check (ajan): `doc_refs_include`, `acs`, `min_blocking`/`max_blocking`; kanıt
    araç ortamında üretimin `EvidenceVerifier`'ıyla yeniden doğrulanır (`eval_agents`);
  - verify_and_map (ajan): `steps`, `methods` (sembol tablosu), `expects_include`,
    `no_missing_methods`, `all_verified`;
  - assistant / assistant_deep (AI-ASISTAN-PLANI §13; işleyici üzerinden, `run_flow_case`):
    `contains`/`not_contains` (görünür cevap metni), `kaynak_tur_include`, `kaynak_ref_include`,
    `rota_in`, `eylem_reddi`, `guven_gosterimi`, `otomatik_derin`, `oneri_eylem_tur`,
    `oneri_max`, `jira_anahtarlari_include`, `cevap_kaynagi_in`
    (`eval_agents.asistan_problems`). Set `esikler` taşıyorsa geçiş vaka vaka değil eşiklerle
    ölçülür (`asistan_olcumleri`).
- Vaka düzeyi `replay_key` setinkini geçersiz kılar (story başına golden kökü).
- Koşturucu: geçit **canlı** (`live`/`record`) olmalıdır; REPLAY'de koşu yalnızca duman testi
  sayılır (`--allow-replay`) ve durum kaydını asla `evaluated` yapmaz. Sonuç raporu
  `rules/evaluation/results/<paket>-v<sürüm>-<tarih>.json`'a yazılır; `--update-status` ile tüm
  vakalar geçtiyse `rules/evaluations.yaml` kaydı `evaluated` olur
  (`evaluation: {date, model, provider, results}`). Geçmeyen vaka varsa kayıt değişmez.

    cd core && ANTHROPIC_API_KEY=… uv run python -m tp_core.gateway.eval_set --bundle triage \\
        --update-status
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tp_core.gateway.bundle import load_schema
from tp_core.gateway.defects import dup_rank_problems
from tp_core.gateway.errors import GatewayConfigError, GatewayError
from tp_core.gateway.eval_agents import (
    ASISTAN_AMACLARI,
    TohumYok,
    ToolEnv,
    asistan_problems,
    coverage_problems,
    dogrulanmis_kaynak_var,
    findings_problems,
    mapping_problems,
    review_problems,
)
from tp_core.gateway.evaluation import EVALUATIONS_FILE, prompt_versions
from tp_core.ports import ModelMessage

EVAL_DIR = "evaluation"
RESULTS_DIR = "results"
LIVE_MODES = ("live", "record")


@dataclass
class CaseResult:
    id: str
    ok: bool
    failures: list[str] = field(default_factory=list)
    output: Any = None
    mode: str | None = None
    error: str | None = None
    # Vaka başına harcama ve uçtan uca süre (rapordaki medyan/p90; işleyici koşularında dolu).
    cost_usd: float | None = None
    sure_ms: int | None = None


def set_path(rules_dir: Path, bundle: str) -> Path:
    return rules_dir / EVAL_DIR / f"{bundle}.json"


def load_set(rules_dir: Path, bundle: str) -> dict[str, Any]:
    path = set_path(rules_dir, bundle)
    if not path.is_file():
        raise GatewayConfigError(f"değerlendirme seti yok: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("bundle") != bundle or not data.get("cases"):
        raise GatewayConfigError(f"{path}: geçersiz değerlendirme seti")
    ids = [c.get("id") for c in data["cases"]]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i for i in ids):
        raise GatewayConfigError(f"{path}: vaka kimlikleri benzersiz ve dolu olmalı")
    return data


def _fact_value(value: Any) -> Any:
    """Olgu değerinin karşılaştırma biçimi: sayı/sayı metni → Decimal, diğerleri olduğu gibi."""
    from decimal import Decimal, InvalidOperation

    if isinstance(value, bool) or value is None:
        return value
    try:
        return Decimal(str(value).strip())
    except InvalidOperation:
        return str(value).strip()


def case_facts_problems(output: Mapping[str, Any], expect: Mapping[str, Any]) -> list[str]:
    """`case_facts` (012 §4.3): beklenen her olgu (`table_ref`, `column`, `value`, `kind`) çıktıda
    var; çıktı yalnız beyan edilen tablolara atıf yapar. Alıntıların birebir doğrulaması ürünün
    deterministik adımıdır (`features/oracle/dogrulama.py`); burada değer ve kolon denetlenir."""
    failures: list[str] = []
    have: set[tuple[str, str, str, Any]] = set()
    tables = set(expect.get("table_refs") or [])
    for group in output.get("groups") or []:
        if not isinstance(group, Mapping):
            continue
        ref = str(group.get("table_ref"))
        if tables and ref not in tables:
            failures.append(f"beyan dışı tablo: {ref}")
        for kind in ("inputs", "expected"):
            for fact in group.get(kind) or []:
                if isinstance(fact, Mapping):
                    have.add((ref, kind, str(fact.get("column")), _fact_value(fact.get("value"))))
    for fact in expect.get("facts") or []:
        key = (fact["table_ref"], fact["kind"], fact["column"], _fact_value(fact["value"]))
        if key not in have:
            failures.append(f"olgu yok: {fact['table_ref']}.{fact['column']} = {fact['value']!r}")
    return failures


def _text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return "" if value is None else str(value)


def check_output(purpose: str, expect: Mapping[str, Any], output: Any) -> list[str]:
    """Beklentiye aykırılıklar (boş = geçti). Türkçe, kısa."""
    out = output if isinstance(output, Mapping) else {}
    failures: list[str] = []
    if purpose == "triage":
        cls, sub = out.get("class"), out.get("sub_type")
        if "class" in expect and cls != expect["class"]:
            failures.append(f"sınıf {cls!r}, beklenen {expect['class']!r}")
        if "class_in" in expect and cls not in expect["class_in"]:
            failures.append(f"sınıf {cls!r} şunlardan biri değil: {expect['class_in']}")
        if cls in (expect.get("class_not") or []):
            failures.append(f"sınıf {cls!r} olmamalı")
        if "sub_type" in expect and sub != expect["sub_type"]:
            failures.append(f"alt tür {sub!r}, beklenen {expect['sub_type']!r}")
    elif purpose == "bug_draft":
        for name, needles in (expect.get("contains") or {}).items():
            have = _text(out.get(name))
            failures += [f"{name} '{n}' içermiyor" for n in needles if n not in have]
        for name, needles in (expect.get("not_contains") or {}).items():
            have = _text(out.get(name))
            failures += [f"{name} '{n}' içermemeli" for n in needles if n in have]
        if "story_key" in expect and out.get("story_key") != expect["story_key"]:
            failures.append(f"story_key {out.get('story_key')!r}, beklenen {expect['story_key']!r}")
    elif purpose == "dup_rank":
        keys = list(expect.get("candidate_keys") or [])
        failures += dup_rank_problems(out, [{"key": k} for k in keys])
        ranked = sorted(
            (c for c in out.get("candidates") or [] if isinstance(c, Mapping)),
            key=lambda c: c.get("rank") or 0,
        )
        top = ranked[0].get("key") if ranked else None
        if "top" in expect and top != expect["top"]:
            failures.append(f"ilk aday {top!r}, beklenen {expect['top']!r}")
        for name in ("recommendation", "link_key"):
            if name in expect and out.get(name) != expect[name]:
                failures.append(f"{name} {out.get(name)!r}, beklenen {expect[name]!r}")
    elif purpose == "requirement_review":
        failures += review_problems(out, expect)
    elif purpose == "case_generation":
        failures += coverage_problems(out, expect)
    elif purpose == "consistency_check":
        failures += findings_problems(out, expect)
    elif purpose == "verify_and_map":
        failures += mapping_problems(out, expect)
    elif purpose == "case_facts":
        failures += case_facts_problems(out, expect)
    elif purpose in ASISTAN_AMACLARI:
        failures += asistan_problems(output, expect, purpose=purpose)
    else:
        raise GatewayConfigError(f"değerlendirme beklentisi tanımlı değil: {purpose}")
    return failures


def case_replay_key(data: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, Any]:
    """Vakanın golden kökü: vaka düzeyi `replay_key` setinkini geçersiz kılar (story başına)."""
    return dict(case.get("replay_key") or data.get("replay_key") or {})


def runs_of(data: Mapping[str, Any]) -> int:
    """Setin vaka başına koşu sayısı (`runs`, varsayılan 1; §12 case üretimi 5 story × 3 koşu)."""
    runs = int(data.get("runs") or 1)
    if runs < 1:
        raise GatewayConfigError(f"{data.get('bundle')}: 'runs' en az 1 olmalı")
    return runs


def run_id(case: Mapping[str, Any], run: int, runs: int) -> str:
    return str(case["id"]) if runs == 1 else f"{case['id']}#k{run}"


def case_messages(case: Mapping[str, Any]) -> list[ModelMessage]:
    return [ModelMessage(**m) for m in case["messages"]]


def run_case(
    gw: Any,
    data: Mapping[str, Any],
    case: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    env: ToolEnv | None = None,
    case_id: str | None = None,
) -> CaseResult:
    """Tek vakayı geçitten geçirir (vakanın golden kökü: `case_replay_key`). Geçit hatası vakayı
    düşürür, koşuyu değil (`eval_live` vaka başına bütçe denetimi için bunu tek tek çağırır).

    Ajan setleri (`agent`) üretimdeki araç ortamıyla (`env`) koşar; ortam yoksa vaka çağrılmaz."""
    purpose, bundle = str(data["purpose"]), str(data["bundle"])
    cid = case_id or str(case["id"])
    expect = case.get("expect") or {}
    agent = data.get("agent")
    try:
        if agent:
            if env is None:
                return CaseResult(cid, False, ["araç ortamı yok"], error="ajan araç ortamı yok")
            res = gw.run_agent(
                purpose,
                bundle,
                case_messages(case),
                env.tools,
                env.execute,
                dict(schema),
                replay_key=case_replay_key(data, case),
                max_turns=int(agent.get("max_turns") or 15),
            )
        else:
            res = gw.call(
                purpose,
                bundle,
                case_messages(case),
                dict(schema),
                replay_key=case_replay_key(data, case),
            )
    except GatewayError as exc:
        return CaseResult(cid, False, [type(exc).__name__], error=str(exc)[:500])
    failures = check_output(purpose, expect, res.output)
    if agent and env is not None:
        failures += env.check(res.output, expect)
    return CaseResult(cid, not failures, failures, res.output, res.mode)


def is_flow_set(data: Mapping[str, Any]) -> bool:
    """Set işleyici üzerinden mi koşar (asistan: `agent.tool_env == "assistant"`)?"""
    agent = data.get("agent") or {}
    return isinstance(agent, Mapping) and agent.get("tool_env") == "assistant"


def set_purposes(data: Mapping[str, Any]) -> list[str]:
    """Setin koşturulabileceği amaçlar (`purposes`; yoksa yalnız `purpose`)."""
    return [str(p) for p in data.get("purposes") or [data["purpose"]]]


def flow_env_name(case: Mapping[str, Any]) -> str:
    """Asistan vakasının araç ortamı: `assistant:<rol>` (`eval_agents.ENVS`)."""
    return f"assistant:{case.get('rol')}"


def run_flow_case(
    env: ToolEnv | None,
    case: Mapping[str, Any],
    purpose: str,
    gateway_factory: Any,
    *,
    case_id: str | None = None,
    clock: Any = None,
) -> CaseResult:
    """Asistan vakasını işleyici (`flow.cevapla`) üzerinden koşturur ve beklentiyle karşılaştırır.

    Ortam yoksa (rol ortamı kurulamadı) vaka çağrılmaz. Tohum çözülemezse vaka düşer. Süre
    uçtan uçtur (mesaj yazımından cevap okunana kadar, `clock`); maliyet mesaja yazılan harcama."""
    import time

    cid = case_id or str(case["id"])
    if env is None or env.akis is None:
        return CaseResult(cid, False, ["araç ortamı yok"], error="asistan rol ortamı yok")
    saat = clock or time.monotonic
    basla = saat()
    try:
        sonuc = env.akis.sor(case, purpose, gateway_factory)
    except TohumYok as exc:
        return CaseResult(cid, False, ["tohum yok"], error=str(exc)[:500])
    sure_ms = int((saat() - basla) * 1000)
    if sonuc.output is None:
        return CaseResult(
            cid,
            False,
            [sonuc.hata or "cevap yok"],
            error=sonuc.hata,
            mode="flow",
            cost_usd=sonuc.maliyet_usd,
            sure_ms=sure_ms,
        )
    failures = check_output(purpose, case.get("expect") or {}, sonuc.output)
    return CaseResult(
        cid,
        not failures,
        failures,
        sonuc.output,
        "flow",
        cost_usd=sonuc.maliyet_usd,
        sure_ms=sure_ms,
    )


def _yuzdelik(degerler: Sequence[float], oran: float) -> float | None:
    """En yakın sıra yöntemi (p50 = medyan alt değer, p90)."""
    import math

    sirali = sorted(degerler)
    if not sirali:
        return None
    return sirali[max(0, math.ceil(oran * len(sirali)) - 1)]


def asistan_olcumleri(
    data: Mapping[str, Any], results: Sequence[CaseResult], purpose: str
) -> dict[str, Any]:
    """§13 ölçümleri ve eşik kararı (asistan seti).

    - beklenti geçişi: geçen vaka / tüm vaka;
    - doğrulanmış kaynak: `urune_ozgu` etiketli vakalarda genel bilgi dışı doğrulanmış kaynak oranı;
    - eylem reddi + injection direnci: `eylem_istegi`/`injection` etiketli vakaların geçiş oranı;
    - otomatik yükseltme oranı (yalnız `assistant`, `kip=soru` model cevapları);
    - medyan/p90 maliyet (USD) ve uçtan uca süre (sn)."""
    by_id = {str(c["id"]): c for c in data["cases"]}

    def vaka(r: CaseResult) -> Mapping[str, Any]:
        return by_id.get(r.id.split("#", 1)[0], {})

    def etiketli(*etiketler: str) -> list[CaseResult]:
        return [r for r in results if set(vaka(r).get("etiketler") or []) & set(etiketler)]

    def oran(pay: int, payda: int) -> float | None:
        return round(pay / payda, 4) if payda else None

    urune = etiketli("urune_ozgu")
    guvenlik = etiketli("eylem_istegi", "injection")
    model_sorulari = [
        r
        for r in results
        if vaka(r).get("kip", "soru") == "soru"
        and isinstance(r.output, Mapping)
        and r.output.get("cevap_kaynagi") == "model"
    ]
    maliyetler = [r.cost_usd for r in results if r.cost_usd is not None]
    sureler = [r.sure_ms / 1000 for r in results if r.sure_ms is not None]
    olcum: dict[str, Any] = {
        "amac": purpose,
        "beklenti_gecis_orani": oran(sum(r.ok for r in results), len(results)),
        "dogrulanmis_kaynak_orani": oran(
            sum(isinstance(r.output, Mapping) and dogrulanmis_kaynak_var(r.output) for r in urune),
            len(urune),
        ),
        "eylem_ve_injection_orani": oran(sum(r.ok for r in guvenlik), len(guvenlik)),
        "otomatik_derin_orani": (
            oran(
                sum(bool(r.output.get("otomatik_derin")) for r in model_sorulari),
                len(model_sorulari),
            )
            if purpose == "assistant"
            else None
        ),
        "maliyet_usd": {
            "medyan": _yuzdelik(maliyetler, 0.5),
            "p90": _yuzdelik(maliyetler, 0.9),
            "toplam": round(sum(maliyetler), 6),
        },
        "sure_s": {"medyan": _yuzdelik(sureler, 0.5), "p90": _yuzdelik(sureler, 0.9)},
    }
    olcum["esikler"] = esik_karari(data.get("esikler") or {}, olcum, purpose)
    return olcum


def _amac_degeri(deger: Any, purpose: str) -> Any:
    return deger.get(purpose) if isinstance(deger, Mapping) else deger


def esik_karari(
    esikler: Mapping[str, Any], olcum: Mapping[str, Any], purpose: str
) -> list[dict[str, Any]]:
    """`esikler` → [{ad, deger, esik, gecti}]. Ölçülemeyen değer (None) eşiği geçmez; amaca
    özgü eşik (`{assistant: …, assistant_deep: …}`) o amaç için tanımlı değilse atlanır."""
    tablo = (
        ("beklenti_gecis_min", olcum.get("beklenti_gecis_orani"), "min"),
        ("dogrulanmis_kaynak_min", olcum.get("dogrulanmis_kaynak_orani"), "min"),
        ("eylem_ve_injection_min", olcum.get("eylem_ve_injection_orani"), "min"),
        ("otomatik_derin_max", olcum.get("otomatik_derin_orani"), "max"),
        ("medyan_maliyet_usd_max", (olcum.get("maliyet_usd") or {}).get("medyan"), "max"),
        ("p90_sure_s_max", (olcum.get("sure_s") or {}).get("p90"), "max"),
    )
    out = []
    for ad, deger, yon in tablo:
        if ad not in esikler:
            continue
        esik = _amac_degeri(esikler[ad], purpose)
        if esik is None:
            continue
        if ad == "otomatik_derin_max" and purpose != "assistant":
            continue
        gecti = deger is not None and (deger >= esik if yon == "min" else deger <= esik)
        out.append({"ad": ad, "deger": deger, "esik": esik, "gecti": bool(gecti)})
    return out


def set_passed(data: Mapping[str, Any], results: Sequence[CaseResult], purpose: str) -> bool:
    """Set geçti mi: `esikler` varsa tüm eşikler (§13), yoksa her vaka."""
    if not results:
        return False
    if data.get("esikler"):
        return all(e["gecti"] for e in asistan_olcumleri(data, results, purpose)["esikler"])
    return all(r.ok for r in results)


def run_set(
    gw: Any, rules_dir: Path, data: Mapping[str, Any], *, env: ToolEnv | None = None
) -> list[CaseResult]:
    """Setin her vakasını (`runs` kez) geçitten geçirir."""
    schema = load_schema(rules_dir, str(data["purpose"]))
    runs = runs_of(data)
    return [
        run_case(gw, data, case, schema, env=env, case_id=run_id(case, k, runs))
        for case in data["cases"]
        for k in range(1, runs + 1)
    ]


def write_report(
    rules_dir: Path,
    data: Mapping[str, Any],
    results: Sequence[CaseResult],
    *,
    model: str,
    provider: str,
    mode: str,
    today: dt.date | None = None,
    extra: Mapping[str, Any] | None = None,
    tag: str | None = None,
) -> Path:
    """`extra`: rapora eklenen ek alanlar (ör. `eval_live`: maliyet, bütçe, tamamlanma).
    `tag`: çok amaçlı setlerde amaç adı (`assistant-v1-assistant_deep-<tarih>.json`)."""
    today = today or dt.date.today()
    folder = rules_dir / EVAL_DIR / RESULTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    suffix = "" if mode in LIVE_MODES else "-replay-duman"
    path = folder / f"{report_stem(data, today, tag)}{suffix}.json"
    report = {
        "bundle": data["bundle"],
        "version": data["version"],
        "date": today.isoformat(),
        "model": model,
        "provider": provider,
        "mode": mode,
        "passed": sum(r.ok for r in results),
        "total": len(results),
        "runs": runs_of(data),
        "cases": [r.__dict__ for r in results],
        **dict(extra or {}),
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def report_stem(data: Mapping[str, Any], today: dt.date, tag: str | None = None) -> str:
    middle = f"-{tag}" if tag else ""
    return f"{data['bundle']}-v{data['version']}{middle}-{today.isoformat()}"


def mark_evaluated(
    rules_dir: Path,
    bundle: str,
    version: int,
    *,
    model: str,
    provider: str,
    results: str,
    today: dt.date | None = None,
    passed: int | None = None,
    total: int | None = None,
    guardrails_version: int | None = None,
    calls: str | None = None,
    icerik_hash: str | None = None,
    amaclar: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    """`rules/evaluations.yaml` kaydını `evaluated` yapar (baştaki açıklama yorumu korunur).

    Eski `note` ("canlı değerlendirme yapılmadı" gibi) bayatlar: yerine üretilmiş bir satır yazılır
    ki kayıt kendisiyle çelişmesin. `guardrails_version`: koşu sırasında ortak `_guardrails`
    paketinin sürümü (`guardrails` geçişli kapsamı bunu okur). `calls`: çağrı kaydı (JSONL) yolu.
    `icerik_hash`: koşu anındaki içerik hash'i (`evaluation.icerik_hash`; §4.2 X). `amaclar`:
    çok amaçlı paketlerde amaç başına model/rapor/ölçüm (`evaluation.amaclar`)."""
    when = (today or dt.date.today()).isoformat()
    evaluation: dict[str, Any] = {
        "date": when,
        "model": model,
        "provider": provider,
        "results": results,
    }
    if guardrails_version is not None:
        evaluation["guardrails_version"] = guardrails_version
    if calls:
        evaluation["calls"] = calls
    if icerik_hash:
        evaluation["icerik_hash"] = icerik_hash
    if amaclar:
        evaluation["amaclar"] = {k: dict(v) for k, v in amaclar.items()}
    score = f", {passed}/{total} vaka geçti" if passed is not None and total is not None else ""
    note = f"Canlı değerlendirme {when}, {model} ({provider}){score}: {results}"
    _write_entry(rules_dir, bundle, version, evaluation, note)


def _write_entry(
    rules_dir: Path, bundle: str, version: int, evaluation: dict[str, Any], note: str
) -> None:
    path = rules_dir / EVALUATIONS_FILE
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    header = "".join(_leading_comments(lines))
    data = yaml.safe_load(text) or {}
    entry = data.setdefault("bundles", {}).setdefault(bundle, {})
    entry.pop("waiver", None)
    entry.update({"version": version, "status": "evaluated", "note": note})
    entry["evaluation"] = evaluation
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)
    path.write_text(header + body, encoding="utf-8")


GUARDRAILS = "guardrails"


def guardrails_coverage(rules_dir: Path) -> tuple[bool, list[str]]:
    """Ortak `_guardrails` paketi kendi başına çağrılmaz; her prompt'a eklenir. Geçişli kapsam:
    guardrails'i içeren HER paket güncel sürümüyle `evaluated` ve kaydı aynı guardrails sürümünü
    taşıyorsa guardrails de değerlendirilmiştir. Dönen liste: eksik paketler (neden)."""
    from tp_core.gateway.evaluation import load_evaluations

    versions = prompt_versions(rules_dir)
    guard_v = versions.get(GUARDRAILS)
    records = load_evaluations(rules_dir)
    missing: list[str] = []
    for name, version in versions.items():
        if name == GUARDRAILS:
            continue
        rec = records.get(name) or {}
        ev = rec.get("evaluation") or {}
        if rec.get("status") != "evaluated" or rec.get("version") != version:
            missing.append(f"{name}@v{version} (canlı değerlendirilmedi)")
        elif ev.get("guardrails_version") != guard_v:
            missing.append(f"{name}@v{version} (guardrails v{guard_v} ile değil)")
    return not missing, missing


def mark_guardrails_if_covered(
    rules_dir: Path, *, model: str, provider: str, today: dt.date | None = None
) -> bool:
    """Geçişli kapsam tamamsa `guardrails` kaydını `evaluated` yapar (aksi hâlde dokunmaz)."""
    covered, _ = guardrails_coverage(rules_dir)
    if not covered:
        return False
    from tp_core.gateway.evaluation import load_evaluations

    versions = prompt_versions(rules_dir)
    records = load_evaluations(rules_dir)
    others = sorted(n for n in versions if n != GUARDRAILS)
    reports = ", ".join(str(records[n]["evaluation"]["results"]) for n in others)
    when = (today or dt.date.today()).isoformat()
    _write_entry(
        rules_dir,
        GUARDRAILS,
        versions[GUARDRAILS],
        {
            "date": when,
            "model": model,
            "provider": provider,
            "results": "geçişli: " + reports,
            "kapsam": "transitive",
        },
        f"Canlı değerlendirme {when} (geçişli): guardrails v{versions[GUARDRAILS]}'i içeren tüm "
        f"paketler ({', '.join(others)}) bu sürümle canlı değerlendirildi.",
    )
    return True


def _leading_comments(lines: Sequence[str]) -> list[str]:
    out = []
    for line in lines:
        if line.startswith("#") or not line.strip():
            out.append(line)
        else:
            break
    return out


def main(argv: list[str] | None = None) -> int:
    from tp_core.gateway.config import GatewaySettings, find_rules_dir, resolve_mode
    from tp_core.gateway.factory import build_gateway
    from tp_core.gateway.testing import InMemoryCallRecorder

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", required=True, help="prompt paketi (ör. triage, dup-rank)")
    parser.add_argument("--rules-dir", type=Path, default=None)
    parser.add_argument("--update-status", action="store_true")
    parser.add_argument(
        "--allow-replay", action="store_true", help="anahtarsız duman koşusu (durum yazılmaz)"
    )
    args = parser.parse_args(argv)
    settings = GatewaySettings()
    rules_dir = args.rules_dir or find_rules_dir(settings.rules_dir)
    mode = resolve_mode(settings)
    if mode not in LIVE_MODES and not args.allow_replay:
        print(
            "HATA: değerlendirme canlı model ister (ANTHROPIC_API_KEY, TP_MODEL_MODE=live).",
            file=sys.stderr,
        )
        return 2
    data = load_set(rules_dir, args.bundle)
    version = prompt_versions(rules_dir).get(args.bundle)
    if version != data["version"]:
        print(f"HATA: set v{data['version']}, prompt v{version}; seti yenileyin", file=sys.stderr)
        return 2
    gw = build_gateway(InMemoryCallRecorder(), settings=settings)
    model = gw.models.purpose(str(data["purpose"])).model
    results = run_set(gw, rules_dir, data)
    report = write_report(
        rules_dir, data, results, model=model, provider=gw.provider_name, mode=mode
    )
    for r in results:
        print(f"{'GEÇTİ' if r.ok else 'KALDI'}\t{r.id}\t{'; '.join(r.failures)}")
    passed = all(r.ok for r in results)
    print(f"{sum(r.ok for r in results)}/{len(results)} → {report}")
    if args.update_status and passed and mode in LIVE_MODES:
        mark_evaluated(
            rules_dir,
            args.bundle,
            int(data["version"]),
            model=model,
            provider=gw.provider_name,
            results=str(report.relative_to(rules_dir)),
        )
        print(f"{EVALUATIONS_FILE}: {args.bundle}@v{data['version']} evaluated")
    return 0 if passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
