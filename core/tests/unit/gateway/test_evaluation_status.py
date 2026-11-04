"""Constitution X: prompt paketlerinin canlı değerlendirme durumu (`rules/evaluations.yaml`)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from tests.unit.gateway.demo_sources import RULES
from tp_core.gateway.errors import GatewayConfigError
from tp_core.gateway.evaluation import (
    ICERIK_KAYNAKLARI,
    PENDING_LABEL,
    blocking,
    evaluation_status,
    evaluation_statuses,
    icerik_dosyalari,
    icerik_hash,
    load_evaluations,
    main,
    prompt_versions,
)


@pytest.fixture
def rules_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "rules"
    dst.mkdir()
    shutil.copytree(RULES / "prompts", dst / "prompts")
    shutil.copy(RULES / "evaluations.yaml", dst / "evaluations.yaml")
    return dst


def _set(rules_dir: Path, bundle: str, **entry) -> None:
    path = rules_dir / "evaluations.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["bundles"][bundle] = entry
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


# --- Gerçek rules/ ---------------------------------------------------------------------------


def test_every_prompt_bundle_has_a_current_evaluation_record() -> None:
    statuses = evaluation_statuses(RULES)
    assert set(statuses) == set(prompt_versions(RULES))
    stale_or_missing = [s.bundle_id for s in statuses.values() if s.status in ("stale", "missing")]
    assert not stale_or_missing, f"evaluations.yaml güncellenmedi: {stale_or_missing}"


def test_verify_and_map_v3_is_pending_live_evaluation_without_waiver() -> None:
    """Faz 3 bulgusu: v3 + yeniden kaydedilen golden'lar canlı modelle değerlendirilmedi ve onaylı
    istisna yok. Golden'larda `recording` (canlı kayıt üst verisi) olunca bu test güncellenir."""
    st = evaluation_status(RULES, "verify-and-map")
    assert st.prompt_version == 3
    goldens = sorted((RULES / "replay" / "verify_and_map" / "golden").rglob("*.json"))
    assert goldens
    live = [p for p in goldens if '"recording"' in p.read_text(encoding="utf-8")]
    if not live:
        assert st.status == "pending"
        assert st.label == PENDING_LABEL
        assert not st.mergeable


def test_no_waiver_is_recorded_without_owner_approval() -> None:
    """İstisna yalnızca sahip onayıyla yazılır; bugün depoda onaylı istisna yoktur."""
    raw = load_evaluations(RULES)
    assert all(r["status"] != "waived" for r in raw.values())


def test_readme_status_table_matches_manifest() -> None:
    readme = (RULES / "README.md").read_text(encoding="utf-8")
    statuses = evaluation_statuses(RULES)
    for st in statuses.values():
        row = re.search(
            rf"^\| `{re.escape(st.bundle_id)}`[^|]*\| v(\d+) \| (.+) \|$", readme, re.MULTILINE
        )
        assert row, f"rules/README.md canlı değerlendirme tablosunda {st.bundle_id} satırı yok"
        assert int(row.group(1)) == st.prompt_version
        assert st.label in row.group(2)
    assert "evaluations.yaml" in readme


def test_merge_gate_reports_pending_bundles(capsys) -> None:
    code = main(["--rules-dir", str(RULES), "--check"])
    pending = blocking(RULES)
    assert code == (1 if pending else 0)
    out = capsys.readouterr()
    assert "verify-and-map@v3" in out.out
    if pending:
        assert "Constitution X" in out.err


# --- Kurallar (geçici kopya) -----------------------------------------------------------------


def test_version_bump_without_record_update_is_stale(rules_copy: Path) -> None:
    _set(rules_copy, "verify-and-map", version=2, status="pending")
    st = evaluation_status(rules_copy, "verify-and-map")
    assert st.status == "stale" and not st.mergeable


def test_missing_record_blocks_merge(rules_copy: Path) -> None:
    (rules_copy / "prompts" / "yeni-paket.md").write_text(
        "---\nid: yeni-paket\nversion: 1\n---\nx\n", encoding="utf-8"
    )
    st = evaluation_status(rules_copy, "yeni-paket")
    assert st.status == "missing"
    assert main(["--rules-dir", str(rules_copy), "--check"]) == 1


def test_waiver_requires_approver_date_reason_and_until(rules_copy: Path) -> None:
    _set(rules_copy, "verify-and-map", version=3, status="waived", waiver={"reason": "demo"})
    with pytest.raises(GatewayConfigError, match=r"waiver\.approved_by"):
        load_evaluations(rules_copy)
    _set(
        rules_copy,
        "verify-and-map",
        version=3,
        status="waived",
        waiver={"approved_by": "Sahip", "approved_at": "dün", "reason": "r", "until": "u"},
    )
    with pytest.raises(GatewayConfigError, match="YYYY-MM-DD"):
        load_evaluations(rules_copy)


def test_evaluated_requires_dated_results(rules_copy: Path) -> None:
    evaluation = {"date": "2026-11-01"}
    _set(rules_copy, "verify-and-map", version=3, status="evaluated", evaluation=evaluation)
    with pytest.raises(GatewayConfigError, match=r"evaluation\.model"):
        load_evaluations(rules_copy)


def test_pending_cannot_carry_waiver(rules_copy: Path) -> None:
    _set(rules_copy, "verify-and-map", version=3, status="pending", waiver={"approved_by": "x"})
    with pytest.raises(GatewayConfigError, match="pending"):
        load_evaluations(rules_copy)


def test_unknown_status_and_orphan_record_rejected(rules_copy: Path) -> None:
    _set(rules_copy, "verify-and-map", version=3, status="ok")
    with pytest.raises(GatewayConfigError, match="status"):
        load_evaluations(rules_copy)
    _set(rules_copy, "verify-and-map", version=3, status="pending")
    _set(rules_copy, "silinmis-paket", version=1, status="pending")
    with pytest.raises(GatewayConfigError, match="silinmis-paket"):
        evaluation_statuses(rules_copy)


def test_gate_opens_only_when_every_bundle_is_evaluated_or_waived(rules_copy: Path) -> None:
    for bundle_id, version in prompt_versions(rules_copy).items():
        _set(
            rules_copy,
            bundle_id,
            version=version,
            status="evaluated",
            evaluation={
                "date": "2026-11-01",
                "model": "claude-sonnet-5-5",
                "provider": "anthropic",
                "results": "docs/outcome/eval.md",
                # İçerik hash'i tutulan paketlerde (asistan) kayıt güncel hash'i taşımalı.
                **({"icerik_hash": h} if (h := icerik_hash(rules_copy, bundle_id)) else {}),
            },
        )
    assert blocking(rules_copy) == []
    assert main(["--rules-dir", str(rules_copy), "--check"]) == 0
    _set(
        rules_copy,
        "verify-and-map",
        version=3,
        status="waived",
        waiver={
            "approved_by": "Sahip",
            "approved_at": "2026-11-02",
            "reason": "kimlik bilgisi yok",
            "until": "ilk canlı koşu",
        },
    )
    st = evaluation_status(rules_copy, "verify-and-map")
    assert st.status == "waived" and st.mergeable and st.detail["approved_by"] == "Sahip"
    assert main(["--rules-dir", str(rules_copy), "--check"]) == 0


def test_missing_manifest_is_config_error(tmp_path: Path) -> None:
    (tmp_path / "prompts").mkdir()
    with pytest.raises(GatewayConfigError, match=r"evaluations\.yaml"):
        load_evaluations(tmp_path)
    assert main(["--rules-dir", str(tmp_path)]) == 2


# --- İçerik hash'i (AI-ASISTAN-PLANI §4.2 X) ------------------------------------------------


def test_asistan_icerik_hash_sabit_dosya_listesi() -> None:
    assert "assistant" in ICERIK_KAYNAKLARI
    dosyalar = icerik_dosyalari(RULES, "assistant")
    assert {
        "prompts/assistant.md",
        "schemas/assistant.schema.json",
        "schemas/assistant_deep.schema.json",
    } <= set(dosyalar)
    kural = {p for p in dosyalar if p.startswith("assistant/")}
    assert kural == {
        f"assistant/{p.name}"
        for desen in ("*.yaml", "*.json")
        for p in (RULES / "assistant").glob(desen)
    }
    assert "assistant/rotalar.json" in kural  # rota → bağlantı eşlemesi de değerlendirilen içerik
    assert "evaluation/assistant.json" not in dosyalar
    assert all((RULES / p).is_file() for p in dosyalar)
    h = icerik_hash(RULES, "assistant")
    assert h and h.startswith("sha256:") and h == icerik_hash(RULES, "assistant")
    assert icerik_hash(RULES, "triage") is None  # hash yalnız kayıtlı paketlerde


def _hash_ile(rules_dir: Path, rel: str, ek: str) -> str | None:
    path = rules_dir / rel
    path.write_text(path.read_text(encoding="utf-8") + ek, encoding="utf-8")
    return icerik_hash(rules_dir, "assistant")


def test_icerik_hash_degisiklikleri_yakalar(rules_dir: Path) -> None:
    ilk = icerik_hash(rules_dir, "assistant")
    # Şema, prompt ve kural dosyası değişikliği hash'i değiştirir.
    h1 = _hash_ile(rules_dir, "schemas/assistant_deep.schema.json", "\n")
    assert _hash_ile(rules_dir, "assistant/oneriler.yaml", "# not\n") != h1
    h1 = icerik_hash(rules_dir, "assistant")
    assert h1 != ilk
    (rules_dir / "assistant" / "yeni.yaml").write_text("version: 1\n", encoding="utf-8")
    h2 = icerik_hash(rules_dir, "assistant")
    assert h2 != h1
    # Rota eşlemesi (rotalar.json) model çıktısının bağlantısını belirler → içerik.
    h2b = _hash_ile(rules_dir, "assistant/rotalar.json", "\n")
    assert h2b != h2
    h2 = h2b
    # CRLF ↔ LF farkı içerik değişikliği değildir.
    prompt = rules_dir / "prompts" / "assistant.md"
    prompt.write_bytes(prompt.read_bytes().replace(b"\n", b"\r\n"))
    assert icerik_hash(rules_dir, "assistant") == h2
    # models.yaml: yalnız asistan amaç blokları; yorum ve başka amaç hash'i değiştirmez.
    models = rules_dir / "models.yaml"
    metin = models.read_text(encoding="utf-8")
    models.write_text(
        "# yeni yorum\n" + metin.replace("max_tokens: 3000", "max_tokens: 3000 "), encoding="utf-8"
    )
    assert icerik_hash(rules_dir, "assistant") == h2
    data = yaml.safe_load(metin)
    data["purposes"]["triage"]["max_tokens"] = 123
    models.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert icerik_hash(rules_dir, "assistant") == h2
    data["purposes"]["assistant_deep"]["params"]["effort"] = "medium"
    models.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert icerik_hash(rules_dir, "assistant") != h2
    # Silinen dosya da değişikliktir.
    h3 = icerik_hash(rules_dir, "assistant")
    (rules_dir / "schemas" / "assistant.schema.json").unlink()
    assert icerik_hash(rules_dir, "assistant") != h3


def _evaluated(rules_dir: Path, **ek) -> None:
    _set(
        rules_dir,
        "assistant",
        version=prompt_versions(rules_dir)["assistant"],
        status="evaluated",
        evaluation={
            "date": "2026-11-03",
            "model": "assistant=claude-haiku-5-5, assistant_deep=claude-sonnet-5-5",
            "provider": "anthropic",
            "results": "evaluation/results/assistant-v1-assistant-2026-11-03.json",
            **ek,
        },
    )


def test_evaluated_asistan_kaydi_hashsiz_ya_da_bayat_hashle_kapiyi_kapatir(
    rules_dir: Path, capsys
) -> None:
    _evaluated(rules_dir)  # hash yok
    st = evaluation_status(rules_dir, "assistant")
    assert st.status == "icerik_degisti" and not st.mergeable
    assert "içerik değişti" in st.label
    _evaluated(rules_dir, icerik_hash=icerik_hash(rules_dir, "assistant"))
    assert evaluation_status(rules_dir, "assistant").status == "evaluated"
    assert "assistant" not in {s.bundle_id for s in blocking(rules_dir)}
    sema = rules_dir / "schemas" / "assistant.schema.json"
    sema.write_text(sema.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert evaluation_status(rules_dir, "assistant").status == "icerik_degisti"
    capsys.readouterr()
    assert main(["--rules-dir", str(rules_dir), "--check"]) == 1
    out = capsys.readouterr()
    assert "assistant@v1\ticerik_degisti" in out.out and "içerik hash'i: kayıtlı sha256:" in out.out
    assert "assistant@v1 (değerlendirme sonrası içerik değişti" in out.err


def test_waived_asistan_kaydinda_hash_denetlenmez(rules_dir: Path) -> None:
    _set(
        rules_dir,
        "assistant",
        version=1,
        status="waived",
        waiver={
            "approved_by": "Sahip",
            "approved_at": "2026-11-03",
            "reason": "test",
            "until": "ilk canlı koşu",
        },
    )
    assert evaluation_status(rules_dir, "assistant").status == "waived"


def test_hash_komutu(capsys) -> None:
    assert main(["--rules-dir", str(RULES), "--hash"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("assistant\tsha256:") and "  schemas/assistant.schema.json" in out
