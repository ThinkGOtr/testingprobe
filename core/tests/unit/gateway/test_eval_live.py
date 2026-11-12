"""Canlı model hazırlığı (`tp_core.gateway.eval_live`, `ANTHROPIC_WORKSPACE_ID`): çalışma alanı
başlığı, bağlantı denetimi, kuru koşu, sert bütçe tavanı, kayıt adayları ve sır temizliği.

Hiçbir test gerçek API'ye gitmez: sağlayıcı `FakeProvider` ya da `httpx2.MockTransport`'lu gerçek
`AnthropicProvider`'dır.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx2
import pytest

from tests.unit.gateway.demo_sources import load_golden
from tp_core.gateway import ProviderPermanentError
from tp_core.gateway.config import GatewaySettings, load_model_table
from tp_core.gateway.eval_live import (
    CANDIDATES_SUBDIR,
    api_error_of,
    default_record_dir,
    main,
    plan_bundles,
    redact,
    repo_goreli,
    run_live,
)
from tp_core.gateway.eval_set import load_set
from tp_core.gateway.evaluation import PENDING_LABEL, evaluation_status, evaluation_summary
from tp_core.gateway.factory import build_provider
from tp_core.gateway.providers.anthropic_provider import WORKSPACE_HEADER, AnthropicProvider
from tp_core.gateway.providers.base import ProviderRequest
from tp_core.gateway.testing import FakeProvider, text_response

KEY = "sk-ant-api03-TESTKEYabcdefghijklmnop"
WORKSPACE = "wrkspc_01TESTWORKSPACEsecret"
TODAY = dt.date(2026, 11, 2)
BUG_GOLDENS = {
    "c3-6-adet": "HATA",
    "kirma-7-adet": "kirma-kampanya/HATA",
    "f2-kampanya-bulgusu": "f2-kampanya/HATA",
    "f4-kredi-limiti-bulgusu": "f4-kredi-limiti/HATA",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, rules_dir: Path) -> None:
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "TP_EVAL_BUDGET_USD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TP_MODEL_MODE", "replay")  # .env gibi: komut bunu okumaz
    monkeypatch.setenv("TP_RULES_DIR", str(rules_dir))


def _anthropic_message(text: str = "OK") -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 1},
    }


def _mock_provider(
    handler, *, workspace_id: str | None = WORKSPACE
) -> tuple[AnthropicProvider, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    provider = AnthropicProvider(
        api_key=KEY,
        workspace_id=workspace_id,
        http_client=httpx2.Client(transport=httpx2.MockTransport(record)),
    )
    return provider, seen


def _request() -> ProviderRequest:
    return ProviderRequest(
        model="claude-haiku-5-5",
        system="s",
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=16,
    )


# ------------------------------------------------------------------ çalışma alanı başlığı


def test_workspace_id_is_sent_as_header_on_every_request() -> None:
    provider, seen = _mock_provider(lambda r: httpx2.Response(200, json=_anthropic_message()))
    assert provider.complete(_request()).text == "OK"
    assert seen[0].headers[WORKSPACE_HEADER] == WORKSPACE
    assert provider.workspace_header is True
    assert WORKSPACE not in repr(provider) and KEY not in repr(provider)


def test_no_workspace_header_without_workspace_id() -> None:
    provider, seen = _mock_provider(
        lambda r: httpx2.Response(200, json=_anthropic_message()), workspace_id="  "
    )
    provider.complete(_request())
    assert WORKSPACE_HEADER not in seen[0].headers
    assert provider.workspace_header is False


def test_factory_reads_workspace_id_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", WORKSPACE)
    settings = GatewaySettings()
    assert WORKSPACE not in repr(settings) and KEY not in repr(settings)  # SecretStr
    provider = build_provider(settings)
    assert isinstance(provider, AnthropicProvider) and provider.workspace_header
    assert provider._client.default_headers.get(WORKSPACE_HEADER) == WORKSPACE


# ------------------------------------------------------------------ --ping


def test_ping_ok(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    fake = FakeProvider([text_response("OK", input_tokens=12, output_tokens=1)])
    assert main(["--ping"], provider_factory=lambda s: fake) == 0
    out = capsys.readouterr().out
    assert "OK:" in out and "çalışma alanı başlığı gönderilmedi" in out
    assert fake.requests[0].max_tokens == 16 and fake.requests[0].model == "claude-haiku-5-5"


def test_ping_reports_api_error_type_without_secrets(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bugünkü durum: çalışma alanına bağlı anahtar başlıksız 400 döner; tür ve ileti görünür, sır
    görünmez (sunucu iletisi anahtarı/kimliği yansıtsa bile)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", WORKSPACE)
    body = {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": f"anthropic-workspace-id header is required (key {KEY}, ws {WORKSPACE})",
        },
    }
    provider, seen = _mock_provider(
        lambda r: httpx2.Response(400, json=body, headers={"request-id": "req_011"})
    )
    assert main(["--ping"], provider_factory=lambda s: provider) == 1
    out = capsys.readouterr().out
    assert "HATA: invalid_request_error (HTTP 400): anthropic-workspace-id header" in out
    assert "req_011" in out and "çalışma alanı başlığı gönderildi" in out
    assert KEY not in out and WORKSPACE not in out
    assert seen[0].headers[WORKSPACE_HEADER] == WORKSPACE


def test_ping_without_key_is_a_config_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--ping"]) == 2
    assert "ProviderNotConfigured" in capsys.readouterr().out


def test_api_error_of_plain_gateway_error() -> None:
    err = api_error_of(ProviderPermanentError("bağlantı yok", status=403))
    assert (err.kind, err.status) == ("ProviderPermanentError", 403)


def test_redact_masks_known_secrets_and_key_shapes() -> None:
    text = f"x {KEY} y {WORKSPACE} z sk-ant-admin01-OTHERKEY123"
    out = redact(text, [KEY, WORKSPACE])
    assert KEY not in out and WORKSPACE not in out and "OTHERKEY123" not in out


# ------------------------------------------------------------------ --dry-run


def test_dry_run_never_builds_a_provider(capsys: pytest.CaptureFixture[str]) -> None:
    def refuse(_settings: GatewaySettings):
        raise AssertionError("kuru koşu sağlayıcı kurmamalı")

    assert main(["--dry-run"], provider_factory=refuse) == 0
    out = capsys.readouterr().out
    assert "KURU KOŞU — API çağrısı yapılmaz" in out
    # 7 paketin hepsinin seti var (guardrails geçişli); hiçbiri "set yok" diye atlanmaz.
    for bundle in (
        "triage@v2",
        "bug-draft@v2",
        "dup-rank@v2",
        "requirement-review@v3",
        "case-generation@v2",
        "consistency-check@v4",
        "verify-and-map@v3",
    ):
        assert f"{bundle}: " in out and "en kötü durum" in out, bundle
    assert "değerlendirme seti yok" not in out
    assert "guardrails@v1: ATLANIR — ayrı set yok; kapsam geçişli" in out
    assert "case-generation@v2: 5 vaka × 3 koşu" in out
    assert "verify-and-map@v3: 3 vaka, ajan (araç ortamı 'browser'" in out
    # Varsayılan 5 USD tavanı tüm setin en kötü durumunu karşılamaz: dürüstçe söylenir.
    assert "tavanı aşabilir" in out and "--budget-usd" in out


def test_dry_run_of_defect_sets_fits_default_budget(capsys: pytest.CaptureFixture[str]) -> None:
    args = ["--dry-run", "--bundle", "triage", "--bundle", "bug-draft", "--bundle", "dup-rank"]
    assert main(args) == 0
    assert "tavanın altında" in capsys.readouterr().out


def test_unknown_bundle_and_bad_budget_are_config_errors(capsys) -> None:
    assert main(["--dry-run", "--bundle", "yok"]) == 2
    assert main(["--dry-run", "--budget-usd", "-1"]) == 2
    assert "pozitif" in capsys.readouterr().out


def test_asistan_seti_dusuk_butcede_uyarir(capsys: pytest.CaptureFixture[str]) -> None:
    # Plan §13: asistan seti + model/effort matrisi için tavan ≥ 10; daha azı engellenmez, uyarılır.
    assert main(["--dry-run", "--bundle", "assistant", "--budget-usd", "5"]) == 0
    out = capsys.readouterr().out
    assert "UYARI: asistan seti için TP_EVAL_BUDGET_USD ≥ 10" in out
    assert "--budget-usd 10" in out and "--rules-dir" in out
    assert main(["--dry-run", "--bundle", "assistant", "--budget-usd", "10"]) == 0
    assert "UYARI: asistan seti" not in capsys.readouterr().out
    # Asistan seti seçilmediyse uyarı yok.
    assert main(["--dry-run", "--bundle", "triage", "--budget-usd", "5"]) == 0
    assert "UYARI: asistan seti" not in capsys.readouterr().out


# ------------------------------------------------------------------ canlı koşu (sahte sağlayıcı)


def _bug_draft_script(rules_dir: Path) -> list[Any]:
    data = load_set(rules_dir, "bug-draft")
    return [
        text_response(load_golden("bug_draft", BUG_GOLDENS[c["id"]])["output"])
        for c in data["cases"]
    ]


def _run(rules_dir: Path, fake: FakeProvider, budget: float = 5.0, **kw: Any) -> tuple[int, str]:
    lines: list[str] = []
    code = run_live(
        GatewaySettings(),
        rules_dir,
        plan_bundles(rules_dir, ["bug-draft"]),
        budget,
        provider_factory=lambda s: fake,
        out=lines.append,
        today=TODAY,
        **kw,
    )
    return code, "\n".join(lines)


def test_live_run_writes_report_and_keeps_status_pending_without_flag(rules_dir: Path) -> None:
    code, out = _run(rules_dir, FakeProvider(_bug_draft_script(rules_dir)))
    assert code == 0, out
    report = rules_dir / "evaluation" / "results" / "bug-draft-v2-2026-11-02.json"
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["mode"] == "live" and data["passed"] == data["total"] == 4
    assert data["tamamlandi"] is True and data["butce_usd"] == 5.0
    assert data["maliyet_usd"] > 0 and data["kayit_adaylari"] is None
    assert evaluation_status(rules_dir, "bug-draft").status == "pending"
    assert evaluation_summary(rules_dir, "bug-draft")["etiket"] == PENDING_LABEL
    assert "durum değişmedi: canlı değerlendirme bekliyor" in out


def test_update_status_marks_evaluated_only_after_a_complete_passing_run(rules_dir: Path) -> None:
    code, _ = _run(rules_dir, FakeProvider(_bug_draft_script(rules_dir)), update_status=True)
    assert code == 0
    st = evaluation_status(rules_dir, "bug-draft")
    assert st.status == "evaluated" and st.detail["provider"] == "fake"
    assert st.detail["results"] == "evaluation/results/bug-draft-v2-2026-11-02.json"
    assert evaluation_status(rules_dir, "triage").status == "pending"


def test_failing_case_never_marks_evaluated(rules_dir: Path) -> None:
    script = _bug_draft_script(rules_dir)
    script[0] = ProviderPermanentError(f"400: geçersiz istek ({KEY})", status=400)
    code, out = _run(rules_dir, FakeProvider(script), update_status=True)
    assert code == 1
    assert evaluation_status(rules_dir, "bug-draft").status == "pending"
    report = (rules_dir / "evaluation" / "results" / "bug-draft-v2-2026-11-02.json").read_text(
        encoding="utf-8"
    )
    assert KEY not in report and KEY not in out  # sır rapora/çıktıya girmez


def test_budget_cap_stops_before_any_call(rules_dir: Path) -> None:
    fake = FakeProvider([])  # çağrılırsa AssertionError
    code, out = _run(rules_dir, fake, budget=0.001, update_status=True)
    assert code == 1 and not fake.requests
    assert "DURDU: bug-draft/" in out
    assert evaluation_status(rules_dir, "bug-draft").status == "pending"
    assert not (rules_dir / "evaluation" / "results").exists()


def test_budget_cap_stops_mid_set_and_reports_incomplete(rules_dir: Path) -> None:
    gw_models = load_model_table(rules_dir)
    assert gw_models.purpose("bug_draft").model == "claude-haiku-5-5"
    # İlk vakanın en kötü durumu sığar, ikinci vakanınki harcamayla birlikte sığmaz.
    from tp_core.gateway.eval_live import _offline_gateway, estimate_case

    data = load_set(rules_dir, "bug-draft")
    gw = _offline_gateway(rules_dir)
    first = estimate_case(gw, data, data["cases"][0]).worst_usd
    second = estimate_case(gw, data, data["cases"][1]).worst_usd
    budget = first + second * 0.5
    script = _bug_draft_script(rules_dir)
    # İlk vakanın gerçek maliyeti tavanın %90'ı (Haiku: 0,10 USD / 1M girdi token).
    script[0].usage.input_tokens = int(budget * 0.9 / 0.10 * 1_000_000)
    script[0].usage.output_tokens = 0
    fake = FakeProvider(script)
    code, out = _run(rules_dir, fake, budget=budget, update_status=True)
    assert code == 1 and len(fake.requests) == 1, out
    report = json.loads(
        (rules_dir / "evaluation" / "results" / "bug-draft-v2-2026-11-02.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["tamamlandi"] is False and report["total"] == 1
    assert report["set_vaka_sayisi"] == 4
    assert evaluation_status(rules_dir, "bug-draft").status == "pending"


# ------------------------------------------------------------------ --record: ayrı aday dizini


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            h.update(str(path.relative_to(root)).encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def test_record_writes_candidates_outside_committed_goldens(
    rules_dir: Path, tmp_path: Path
) -> None:
    before = _tree_digest(rules_dir / "replay")
    record_dir = tmp_path / "exports" / "eval-live" / "t" / CANDIDATES_SUBDIR
    code, out = _run(rules_dir, FakeProvider(_bug_draft_script(rules_dir)), record_dir=record_dir)
    assert code == 0, out
    assert _tree_digest(rules_dir / "replay") == before  # commit'li golden'lar değişmedi
    index = json.loads((record_dir / "INDEX.json").read_text(encoding="utf-8"))["kayitlar"]
    assert {e["vaka"]: e["golden"] for e in index} == {
        case: f"replay/bug_draft/golden/{name}.json" for case, name in BUG_GOLDENS.items()
    }
    for entry in index:
        rec = json.loads((record_dir / entry["kayit"]).read_text(encoding="utf-8"))
        assert rec["recording"]["provider"] == "fake" and rec["recorded_at"]
    assert "insan incelemesi" in (record_dir / "README.md").read_text(encoding="utf-8")
    report = json.loads(
        (rules_dir / "evaluation" / "results" / "bug-draft-v2-2026-11-02.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["mode"] == "record" and report["kayit_adaylari"] == repo_goreli(
        record_dir, rules_dir
    )


def test_record_dir_inside_committed_goldens_is_refused(rules_dir: Path) -> None:
    fake = FakeProvider(_bug_draft_script(rules_dir))
    with pytest.raises(Exception, match="commit'li golden"):
        _run(rules_dir, fake, record_dir=rules_dir / "replay" / "bug_draft")
    assert not fake.requests


def test_default_record_dir_is_under_gitignored_exports(rules_dir: Path) -> None:
    path = default_record_dir(rules_dir, dt.datetime(2026, 11, 2, 9, 30, tzinfo=dt.UTC))
    assert path == rules_dir.resolve().parent / "exports" / "eval-live" / "20261102T093000Z" / (
        CANDIDATES_SUBDIR
    )
