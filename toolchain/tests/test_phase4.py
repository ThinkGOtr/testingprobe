"""Faz 4 (triage + locator onarımı) toolchain desteği.

- hata girdisi: locator testId zinciri, page object konumu, aria/trace kanıt yolları
- `/aria-match` ve `/locator-probe` aria doğrulaması + onarım adayı
- `/trace-summary`: gerçek Playwright 1.64.1 trace'i (tests/data/pw_1_64_trace_locator.zip)
- `/affected-tests` ve `/check {affected_by}`: etkilenen testler (içe aktarma grafiği)
- `/ast-guard` onarım modu: gerçek yama (add-to-cart → cart-add) ve kurcalanmış yamalar
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from runner.results import failure_inputs, parse_locator
from tests.conftest import (
    DEMO_E2E,
    Forge,
    make_fake_node,
    requires_ast_guard,
    requires_e2e_node_modules,
    requires_node,
)
from tests.test_check import fake_tools, runner_client
from toolchain_common import aria, trace
from toolchain_common.settings import settings
from worker import affected
from worker import app as worker_app
from worker import check as checks
from worker.app import app

DATA = Path(__file__).parent / "data"
TRACE_ZIP = DATA / "pw_1_64_trace_locator.zip"
CATALOG_LOCATORS = "e2e/pages/catalog/locators.ts"
ARIA_PAGE = (
    "- banner:\n"
    '  - link "Katalog"\n'
    "- main:\n"
    '  - article "Portakal Gazozu":\n'
    '    - heading "Portakal Gazozu" [level=2]\n'
    '    - paragraph: "Kampanya: 6 al 1 bedava"\n'
    '    - spinbutton "Adet": "1"\n'
    '    - button "Sepete ekle" [ref=e12]\n'
    '  - article "Maden Suyu":\n'
    '    - spinbutton "Adet": "1"\n'
    '    - button "Sepete ekle" [ref=e20]\n'
    "  - text: Adet\n"
)


@pytest.fixture
def client(env: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TP_NODE", "node")
    worker_app._SYMBOL_CACHE.clear()
    return TestClient(app)


def _edit(forge: Forge, rel: str, old: str, new: str) -> str:
    text = (forge.work / rel).read_text()
    assert old in text, old
    return text.replace(old, new)


# ------------------------------------------------------------------------- hata girdileri


def test_parse_locator_chain_role_and_internal_selector() -> None:
    p = parse_locator("getByTestId('product-card-P-001').getByTestId('add-to-cart')")
    assert p["locator_test_id"] == "add-to-cart"
    assert p["locator_scope_test_id"] == "product-card-P-001"
    p = parse_locator(
        "getByTestId('product-card-P-001').getByRole('button', { name: 'Sepete ekle' })"
    )
    assert p["locator_test_id"] is None and p["locator_scope_test_id"] == "product-card-P-001"
    assert (p["locator_role"], p["locator_name"]) == ("button", "Sepete ekle")
    p = parse_locator('internal:testid=[data-testid="add-to-cart"s]')
    assert p["locator_test_id"] == "add-to-cart"
    assert parse_locator(None)["locator_test_ids"] == []
    assert parse_locator("getByText('x')")["locator_test_id"] is None


def test_failure_inputs_for_broken_scoped_locator(tmp_path: Path) -> None:
    """`make break` sonrası: CatalogPage.addToCart'taki kapsamlı tıklama zaman aşımına uğrar."""
    artifacts = tmp_path / "artifacts"
    e2e = artifacts / "runs" / "r1" / "src" / "e2e"
    out = e2e / "results" / "artifacts" / "cart-sepet"
    out.mkdir(parents=True)
    (out / "error-context.md").write_text(
        "# Test info\n\n# Page snapshot\n\n```yaml\n" + ARIA_PAGE + "```\n", encoding="utf-8"
    )
    shutil.copy(TRACE_ZIP, out / "trace.zip")
    message = (
        "TimeoutError: locator.click: Timeout 5000ms exceeded.\nCall log:\n"
        "  - waiting for getByTestId('product-card-P-001').getByTestId('add-to-cart')\n"
    )
    result = {
        "retry": 0,
        "status": "failed",
        "errors": [{"message": message}],
        "error": {
            "message": message,
            "stack": (
                f"TimeoutError: locator.click\n    at CatalogPage.addToCart "
                f"({e2e}/pages/catalog/catalog.page.ts:44:8)\n"
                f"    at {e2e}/tests/cart.spec.ts:21:5"
            ),
        },
        "errorLocation": {"file": f"{e2e}/pages/catalog/catalog.page.ts", "line": 44, "column": 8},
        "attachments": [
            {"name": "error-context", "path": str(out / "error-context.md")},
            {"name": "trace", "path": str(out / "trace.zip")},
        ],
    }
    f = failure_inputs(result, artifacts / "runs" / "r1", e2e, artifacts)
    assert f["type"] == "locator_timeout"
    assert f["locator_test_id"] == "add-to-cart"
    assert f["locator_scope_test_id"] == "product-card-P-001"
    assert f["location"] == {"file": "pages/catalog/catalog.page.ts", "line": 44, "column": 8}
    assert f["page_location"]["file"] == "pages/catalog/catalog.page.ts"
    assert f["test_location"] == {"file": "tests/cart.spec.ts", "line": 21, "column": 5}
    assert f["aria_snapshot_rel"] == "runs/r1/src/e2e/results/artifacts/cart-sepet/error-context.md"
    assert f["trace_rel"] == "runs/r1/src/e2e/results/artifacts/cart-sepet/trace.zip"
    assert 'button "Sepete ekle"' in f["aria_snapshot"]
    # Kanıt yolları doğrudan /aria-match ve /trace-summary'ye verilebilir.
    text = aria.load_snapshot(artifacts, f["aria_snapshot_rel"])
    assert aria.match(text, "button", "Sepete ekle")["eslesen"] == 2
    t = trace.load_and_summarize(
        artifacts,
        f["trace_rel"],
        role="button",
        name="Sepete ekle",
        scope_test_id="product-card-P-001",
    )
    assert t["rol_ad"]["test_id"] == "cart-add"


# ------------------------------------------------------------------------------ aria


def test_aria_match_counts_scope_and_exact() -> None:
    m = aria.match(ARIA_PAGE, "button", "Sepete ekle")
    assert m["eslesen"] == 2 and m["tam_eslesen"] == 2 and m["var"]
    assert m["yollar"][0] == ["main", 'article "Portakal Gazozu"', 'button "Sepete ekle"']
    # getByRole varsayılanı: harf duyarsız alt dize.
    assert aria.match(ARIA_PAGE, "button", "sepete")["eslesen"] == 2
    assert aria.match(ARIA_PAGE, "button", "sepete")["tam_eslesen"] == 0
    scoped = aria.match(
        ARIA_PAGE, "button", "Sepete ekle", scope_role="article", scope_name="Portakal"
    )
    assert scoped["eslesen"] == 1 and scoped["kapsam"]["eslesen"] == 1
    assert aria.match(ARIA_PAGE, "button", "Sepetten çıkar")["var"] is False
    assert aria.match(ARIA_PAGE, "link", "Sepete ekle")["eslesen"] == 0
    assert aria.match(ARIA_PAGE, "text", "Adet")["eslesen"] == 1


def test_aria_load_snapshot_path_safety(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    run = artifacts / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "snap.yml").write_text(ARIA_PAGE, encoding="utf-8")
    (run / "error-context.md").write_text("# Test info\n\nyok\n", encoding="utf-8")
    (artifacts / "checks").mkdir()
    (artifacts / "checks" / "x.yml").write_text(ARIA_PAGE, encoding="utf-8")
    outside = tmp_path / "gizli.yml"
    outside.write_text('- button "Gizli"\n', encoding="utf-8")
    (run / "bag.yml").symlink_to(outside)
    assert "Sepete ekle" in aria.load_snapshot(artifacts, "runs/r1/snap.yml")
    for bad in (
        "/etc/passwd.yml",
        "runs/../checks/x.yml",
        "checks/x.yml",
        "runs/r1/snap.txt",
        "runs/r1/bag.yml",
        "runs/r1/yok.yml",
        "-runs/r1/snap.yml",
    ):
        with pytest.raises(aria.AriaSourceError):
            aria.load_snapshot(artifacts, bad)
    with pytest.raises(aria.AriaSourceError, match="aria snapshot bulunamadı"):
        aria.load_snapshot(artifacts, "runs/r1/error-context.md")


def test_aria_match_endpoint(client: TestClient, env: Path) -> None:
    run = env / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "error-context.md").write_text(
        "# Page snapshot\n\n```yaml\n" + ARIA_PAGE + "```\n", encoding="utf-8"
    )
    data = client.post(
        "/aria-match",
        json={
            "role": "button",
            "name": "Sepete ekle",
            "aria_snapshot_rel": "runs/r1/error-context.md",
        },
    ).json()
    assert data["eslesen"] == 2 and data["kaynak_rel"] == "runs/r1/error-context.md"
    data = client.post(
        "/aria-match", json={"role": "button", "name": "Sepete ekle", "aria_snapshot": ARIA_PAGE}
    ).json()
    assert data["var"] is True
    assert client.post("/aria-match", json={"role": "button", "name": "x"}).status_code == 422
    resp = client.post(
        "/aria-match", json={"role": "button", "name": "x", "aria_snapshot_rel": "checks/a.yml"}
    )
    assert resp.status_code == 422 and "runs/" in resp.json()["detail"]


# ----------------------------------------------------------------------------- trace


def test_trace_summary_real_trace() -> None:
    t = trace.summarize_trace(TRACE_ZIP)
    failed = t["basarisiz_eylem"]
    assert failed["metot"] == "click" and "Timeout" in failed["hata"]
    assert failed["secici_test_ids"] == ["product-card-P-001", "add-to-cart"]
    assert any("waiting for getByTestId" in line for line in failed["log"])
    els = {(e["test_id"], tuple(e["kapsam_test_ids"])) for e in t["dom"]["elemanlar"]}
    assert ("cart-add", ("product-card-P-001",)) in els
    assert ("cart-add", ("product-card-P-002",)) in els
    assert t["dom"]["kismi"] is False and t["dom"]["yaklasik"] is True
    # Eski testId DOM'da yok (locator 0 eleman) — kural 3'ün girdisi.
    assert not any(e["test_id"] == "add-to-cart" for e in t["dom"]["elemanlar"])

    scoped = trace.summarize_trace(
        TRACE_ZIP, role="button", name="Sepete ekle", scope_test_id="product-card-P-001"
    )["rol_ad"]
    assert scoped["eslesen"] == 1 and scoped["test_id"] == "cart-add"
    unscoped = trace.summarize_trace(TRACE_ZIP, role="button", name="Sepete ekle")["rol_ad"]
    assert unscoped["eslesen"] == 2 and unscoped["test_id"] is None  # çoklu → öneri yok
    spin = trace.summarize_trace(
        TRACE_ZIP, role="spinbutton", name="Adet", scope_test_id="product-card-P-001"
    )["rol_ad"]
    assert spin["test_id"] == "qty-input-P-001"  # label[for] adı


def _zip(tmp_path: Path, members: dict[str, bytes], name: str = "t.zip") -> Path:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for k, v in members.items():
            zf.writestr(k, v)
    p = tmp_path / name
    p.write_bytes(buf.getvalue())
    return p


def test_trace_rejects_hostile_archives(tmp_path: Path) -> None:
    bomb = _zip(tmp_path, {"trace.trace": b"\n" * (20 * 1024 * 1024)}, "bomb.zip")
    with pytest.raises(trace.TraceError, match="zip bombası"):
        trace.summarize_trace(bomb)
    notzip = tmp_path / "x.zip"
    notzip.write_bytes(b"PK no zip")
    with pytest.raises(trace.TraceError, match="geçerli bir zip"):
        trace.summarize_trace(notzip)
    link = tmp_path / "link.zip"
    link.symlink_to(TRACE_ZIP)
    with pytest.raises(trace.TraceError):
        trace.summarize_trace(link)
    # Alt dizindeki / yol kaçışlı üyeler okunmaz; bozuk satırlar yok sayılır.
    odd = _zip(tmp_path, {"../x.trace": b'{"type":"before"}', "a.trace": b"{bozuk\n[]\n"}, "o.zip")
    t = trace.summarize_trace(odd)
    assert t["uyeler"] == ["a.trace"] and t["eylemler"] == [] and t["dom"] is None


def test_trace_self_reference_does_not_loop(tmp_path: Path) -> None:
    snaps = [
        {"type": "before", "callId": "c1", "class": "Frame", "method": "click", "params": {}},
        {"type": "after", "callId": "c1", "error": {"message": "x"}},
        {
            "type": "frame-snapshot",
            "snapshot": {"callId": "c1", "frameId": "f", "html": ["HTML", {}, [[0, 0]]]},
        },
        {
            "type": "frame-snapshot",
            "snapshot": {
                "callId": "c1",
                "frameId": "f",
                "html": ["HTML", {}, [[1, 0]], [[1, 99]], ["BUTTON", {"data-testid": "b"}, "OK"]],
            },
        },
    ]
    body = "\n".join(json.dumps(s) for s in snaps).encode()
    t = trace.summarize_trace(_zip(tmp_path, {"trace.trace": body}))
    assert t["dom"]["kismi"] is True
    assert [e["test_id"] for e in t["dom"]["elemanlar"]] == ["b"]


def test_trace_summary_endpoint(client: TestClient, env: Path) -> None:
    run = env / "runs" / "r1" / "src" / "e2e" / "results" / "artifacts" / "x"
    run.mkdir(parents=True)
    shutil.copy(TRACE_ZIP, run / "trace.zip")
    rel = "runs/r1/src/e2e/results/artifacts/x/trace.zip"
    data = client.post(
        "/trace-summary",
        json={
            "trace_rel": rel,
            "role": "button",
            "name": "Sepete ekle",
            "scope_test_id": "product-card-P-001",
        },
    ).json()
    assert data["trace_rel"] == rel and data["rol_ad"]["test_id"] == "cart-add"
    assert client.post("/trace-summary", json={"trace_rel": "runs/yok.zip"}).status_code == 422
    assert client.post("/trace-summary", json={"trace_rel": "../x.zip"}).status_code == 422


# ------------------------------------------------------------------- etkilenen testler


def test_import_graph_on_demo_e2e() -> None:
    res = affected.affected_tests(DEMO_E2E, ["pages/catalog/locators.ts"])
    # pages/index.ts barrel'ı ve tests/fixtures.ts üzerinden tüm spec'ler etkilenir.
    assert "tests/cart.spec.ts" in res["test_files"]
    assert "tests/locators.spec.ts" in res["test_files"]
    assert all(f.startswith("tests/") and f.endswith(".spec.ts") for f in res["test_files"])
    assert res["tam_kapsam"] is False
    unknown = affected.affected_tests(DEMO_E2E, ["pages/yok/locators.ts"])
    assert unknown["tam_kapsam"] is True and "bulunamadı" in unknown["tam_kapsam_nedeni"]


def test_import_graph_narrow(tmp_path: Path) -> None:
    root = tmp_path / "e2e"
    (root / "pages" / "a").mkdir(parents=True)
    (root / "tests" / "generated").mkdir(parents=True)
    (root / "pages" / "a" / "locators.ts").write_text("export const a = {} as const;\n")
    (root / "pages" / "a" / "a.page.ts").write_text('import { a } from "./locators";\n')
    (root / "pages" / "b.ts").write_text("export const b = 1;\n")
    (root / "tests" / "one.spec.ts").write_text('import { x } from "../pages/a/a.page.js";\n')
    (root / "tests" / "generated" / "two.spec.ts").write_text(
        'import type { B } from "../../pages/b";\nexport * from "../../pages/a/a.page";\n'
    )
    (root / "tests" / "three.spec.ts").write_text('import "../pages/b";\n')
    res = affected.affected_tests(root, ["pages/a/locators.ts"])
    assert res["test_files"] == ["tests/generated/two.spec.ts", "tests/one.spec.ts"]
    res = affected.affected_tests(root, ["pages/b.ts"])
    assert res["test_files"] == ["tests/generated/two.spec.ts", "tests/three.spec.ts"]
    with pytest.raises(ValueError):
        affected.validate_source_path("../pages/a.ts")


def test_affected_tests_endpoint(client: TestClient, forge: Forge) -> None:
    head = forge.commit(
        "tp/repair-sepete-ekle",
        {
            CATALOG_LOCATORS: _edit(
                forge, CATALOG_LOCATORS, 'testId: "add-to-cart"', 'testId: "cart-add"'
            )
        },
    )
    data = client.post("/affected-tests", json={"sha": head, "base_sha": forge.main}).json()
    assert data["sha"] == head and data["kaynak"] == ["pages/catalog/locators.ts"]
    assert "tests/cart.spec.ts" in data["test_files"] and data["tam_kapsam"] is False
    data = client.post(
        "/affected-tests", json={"sha": "main", "changed": ["pages/cart/locators.ts"]}
    ).json()
    assert "tests/order.spec.ts" in data["test_files"]
    assert client.post("/affected-tests", json={"sha": "main"}).status_code == 422
    resp = client.post("/affected-tests", json={"sha": "main", "changed": ["../x.ts"]})
    assert resp.status_code == 422


def test_check_affected_by_diff_runs_affected_tests_and_is_never_recorded(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    head = forge.commit(
        "tp/repair-sepete-ekle",
        {
            CATALOG_LOCATORS: _edit(
                forge, CATALOG_LOCATORS, 'testId: "add-to-cart"', 'testId: "cart-add"'
            )
        },
    )
    client, calls = runner_client()
    req = checks.CheckRequest(
        sha=head,
        base_sha=forge.main,
        ast_guard_mode="repair",
        affected_by=["@diff"],
        repeat_each=1,
    )
    report = checks.execute(settings(), req, runner_client=client)
    assert report["conclusion"] == "success"
    sent = calls[0]["body"]["test_files"]
    assert "tests/cart.spec.ts" in sent and all(f.endswith(".spec.ts") for f in sent)
    kapsam = report["kapsam"]
    assert kapsam["tam"] is False and kapsam["affected_by"] == ["@diff"]
    assert kapsam["etkilenen"]["kaynak"] == ["pages/catalog/locators.ts"]
    assert report["check_recorded"] is False and not (env / "checks").exists()
    assert report["ast_guard"]["mode"] == "repair"


def test_check_affected_by_unknown_falls_back_to_full_suite(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    client, calls = runner_client()
    req = checks.CheckRequest(sha=forge.main, affected_by=["pages/yok.ts"], repeat_each=1)
    report = checks.execute(settings(), req, runner_client=client)
    assert calls[0]["body"]["test_files"] == []  # belirsiz → tüm testler
    assert report["kapsam"]["etkilenen"]["tam_kapsam"] is True
    assert report["check_recorded"] is False  # yine de kapsamlı istek: kayıt yok


def test_check_endpoint_affected_by_validation(client: TestClient) -> None:
    base = {"sha": "main", "affected_by": ["pages/catalog/locators.ts"]}
    bad = [
        {**base, "test_files": ["tests/cart.spec.ts"]},
        {**base, "grep": "x"},
        {**base, "record_check": True},
        {"sha": "main", "affected_by": ["../etc/passwd.ts"]},
        {"sha": "main", "affected_by": ["pages/x.js"]},
    ]
    for body in bad:
        assert client.post("/check", json=body).status_code == 422, body


@requires_node
@requires_e2e_node_modules
@requires_ast_guard
def test_real_repair_check_on_demo_e2e(
    env: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gerçek tsc/eslint/ast-guard (onarım modu) + etkilenen testler, sahte test-runner."""
    monkeypatch.setenv("TP_NODE", "node")
    head = forge.commit(
        "tp/repair-sepete-ekle",
        {
            CATALOG_LOCATORS: _edit(
                forge, CATALOG_LOCATORS, 'testId: "add-to-cart"', 'testId: "cart-add"'
            )
        },
    )
    client, calls = runner_client()
    req = checks.CheckRequest(
        sha=head, base_sha=forge.main, ast_guard_mode="repair", affected_by=["@diff"], repeat_each=1
    )
    report = checks.execute(settings(), req, runner_client=client)
    assert report["conclusion"] == "success", report["summary"]
    guard = report["ast_guard"]["report"]
    assert guard["ok"] is True and guard["testid_changes"][0]["after"] == "cart-add"
    assert "tests/cart.spec.ts" in calls[0]["body"]["test_files"]


# ------------------------------------------------------------- /ast-guard onarım modu


@requires_node
@requires_ast_guard
@pytest.mark.parametrize(
    ("label", "files", "codes"),
    [
        (
            "ad değişti",
            {CATALOG_LOCATORS: ('name: "Sepete ekle"', 'name: "Ekle"')},
            {"field_changed"},
        ),
        (
            "rol değişti",
            {
                CATALOG_LOCATORS: (
                    'role: "button", name: "Sepete ekle"',
                    'role: "link", name: "Sepete ekle"',
                )
            },
            {"field_changed"},
        ),
        (
            "kapsam değişti",
            {
                CATALOG_LOCATORS: (
                    'name: "Sepete ekle", within: "product-card-"',
                    'name: "Sepete ekle", within: "product-list-"',
                )
            },
            {"field_changed"},
        ),
        (
            "page object dosyası da değişti",
            {
                CATALOG_LOCATORS: ('testId: "add-to-cart"', 'testId: "cart-add"'),
                "e2e/pages/catalog/catalog.page.ts": (
                    "/** Ürün kataloğu sayfası. */",
                    "/** Ürün kataloğu sayfası (değişti). */",
                ),
            },
            {"non_locator_file_changed"},
        ),
    ],
)
def test_ast_guard_repair_rejects_tampered_patches(
    client: TestClient, forge: Forge, label: str, files: dict[str, tuple[str, str]], codes: set[str]
) -> None:
    head = forge.commit(
        "tp/repair-" + str(abs(hash(label)) % 10_000),
        {rel: _edit(forge, rel, old, new) for rel, (old, new) in files.items()},
    )
    data = client.post("/ast-guard", json={"base_sha": forge.main, "head_sha": head}).json()
    assert data["ok"] is False, label
    assert codes <= {v["code"] for v in data["violations"]}, data["violations"]


@requires_node
@requires_ast_guard
def test_ast_guard_repair_rejects_extra_locator_file_and_key(
    client: TestClient, forge: Forge
) -> None:
    extra_key = _edit(
        forge,
        CATALOG_LOCATORS,
        'addToCart: { testId: "add-to-cart"',
        'buyNow: { testId: "buy-now", role: "button", name: "Al", intent: "x" },\n'
        '  addToCart: { testId: "cart-add"',
    )
    head = forge.commit(
        "tp/repair-ek",
        {
            CATALOG_LOCATORS: extra_key,
            "e2e/pages/extra/locators.ts": (
                "export const extra = "
                '{ a: { testId: "a", role: "button", name: "A", intent: "A" } } as const;\n'
            ),
        },
    )
    data = client.post("/ast-guard", json={"base_sha": forge.main, "head_sha": head}).json()
    assert data["ok"] is False
    codes = {v["code"] for v in data["violations"]}
    assert {"key_added", "locator_file_added"} <= codes, data["violations"]


# --------------------------------------------------------- /locator-probe (aday, aria)


def _fake_probe(tmp_path: Path, out: dict[str, Any]) -> Path:
    return make_fake_node(
        tmp_path,
        f"""
        pathlib.Path({str(tmp_path / "probe-input.json")!r}).write_text(sys.argv[2])
        print({json.dumps(out)!r})
        """,
        name="fake-probe-node",
    )


PROBE_OUT = {
    "ok": True,
    "matches": 1,
    "test_id": "cart-add",
    "test_ids": ["cart-add"],
    "scope_matches": 1,
    "page_matches": 2,
    "candidate": {"test_id": "cart-add", "matches": 1, "role_name_matches": 1},
    "aria_snapshot": '- article "Portakal Gazozu":\n  - button "Sepete ekle"',
    "aria_snapshot_scope": "scope",
    "http_status": 200,
    "final_path": "/katalog",
}
PROBE_BODY = {
    "sha": "main",
    "role": "button",
    "name": "Sepete ekle",
    "url_path": "/katalog",
    "scope_test_id": "product-card-P-001",
    "candidate_test_id": "cart-add",
}


def test_locator_probe_candidate_and_aria_validation(
    client: TestClient, env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(_fake_probe(tmp_path, PROBE_OUT)))
    monkeypatch.setenv("DEMO_APP_BUILD_SHA", forge.main)
    run = env / "runs" / "green"
    run.mkdir(parents=True)
    (run / "error-context.md").write_text(
        "# Page snapshot\n\n```yaml\n" + ARIA_PAGE + "```\n", encoding="utf-8"
    )
    body = {**PROBE_BODY, "aria_snapshot_rel": "runs/green/error-context.md"}
    data = client.post("/locator-probe", json=body).json()
    assert data["test_id"] == "cart-add" and data["oneri_uretilebilir"] is True
    assert data["engeller"] == []
    assert data["aday"] == {
        "test_id": "cart-add",
        "matches": 1,
        "rol_ad_eslesen": 1,
        "gecerli": True,
        "yoklanan_ile_ayni": True,
    }
    assert data["aria_dogrulama"]["var"] is True and data["aria_dogrulama"]["eslesen"] == 2
    assert data["page_matches"] == 2 and data["scope_matches"] == 1
    assert data["aria_snapshot_scope"] == "scope" and "Sepete ekle" in data["aria_snapshot"]
    assert data["sha_eslesmesi"] == "eslesiyor" and data["olculen"] == "calisan_uygulama"
    sent = json.loads((tmp_path / "probe-input.json").read_text())
    assert sent["candidate_test_id"] == "cart-add" and sent["scope_test_id"] == "product-card-P-001"

    # Referans snapshot'ta rol + ad yoksa öneri engellenir (yanlış butona onarım).
    (run / "other.yml").write_text('- button "Sepetten çıkar"\n', encoding="utf-8")
    data = client.post(
        "/locator-probe", json={**body, "aria_snapshot_rel": "runs/green/other.yml"}
    ).json()
    assert data["oneri_uretilebilir"] is False
    assert "rol + ad referans aria snapshot'ında yok" in data["engeller"]
    # Geçersiz kanıt yolu tarayıcı açılmadan 422.
    resp = client.post("/locator-probe", json={**body, "aria_snapshot_rel": "checks/x.yml"})
    assert resp.status_code == 422


def test_locator_probe_candidate_mismatch_and_zero_match(
    client: TestClient, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = {
        **PROBE_OUT,
        "candidate": {"test_id": "add-to-cart", "matches": 0, "role_name_matches": 0},
    }
    monkeypatch.setenv("TP_NODE", str(_fake_probe(tmp_path, out)))
    data = client.post(
        "/locator-probe", json={**PROBE_BODY, "candidate_test_id": "add-to-cart"}
    ).json()
    assert data["aday"]["gecerli"] is False and data["aday"]["yoklanan_ile_ayni"] is False
    assert data["oneri_uretilebilir"] is False
    zero = {**PROBE_OUT, "matches": 0, "test_id": None, "test_ids": [], "candidate": None}
    monkeypatch.setenv("TP_NODE", str(_fake_probe(tmp_path, zero)))
    data = client.post(
        "/locator-probe", json={k: v for k, v in PROBE_BODY.items() if k != "candidate_test_id"}
    ).json()
    assert data["oneri_uretilebilir"] is False and data["aday"] is None
    assert data["engeller"] == ["rol + ad çalışan uygulamada bulunamadı"]


# ------------------------------------------------- locator-probe.mjs (gerçek Chromium)

PROBE_NODE_TESTS = Path(__file__).resolve().parents[1] / "probe" / "test"
HAVE_PLAYWRIGHT = (Path(__file__).resolve().parents[1] / "node_modules" / "playwright").is_dir()


@requires_node
@pytest.mark.skipif(not HAVE_PLAYWRIGHT, reason="toolchain/node_modules yok (npm ci)")
def test_locator_probe_script_with_real_browser() -> None:
    """probe/test/locator-probe.test.mjs: yerel katalog kopyasında gerçek yoklama."""
    files = sorted(str(p) for p in PROBE_NODE_TESTS.glob("*.test.mjs"))
    res = subprocess.run(
        ["node", "--test", *files], capture_output=True, text=True, timeout=180, check=False
    )
    if "Executable doesn't exist" in res.stdout + res.stderr:
        pytest.skip("Playwright Chromium kurulu değil")
    assert res.returncode == 0, res.stdout[-3000:] + res.stderr[-2000:]


def test_trace_summary_real_test_runner_trace() -> None:
    """@playwright/test trace'i: 0-trace/1-trace (bağlamlar) + test.trace (adımlar)."""
    t = trace.summarize_trace(
        DATA / "pw_1_64_test_trace_locator.zip",
        role="button",
        name="Sepete ekle",
        scope_test_id="product-card-P-001",
    )
    assert t["uyeler"] == ["0-trace.trace", "1-trace.trace", "test.trace"]
    assert t["basarisiz_eylem"]["secici_test_ids"] == ["product-card-P-001", "add-to-cart"]
    assert t["rol_ad"]["test_id"] == "cart-add" and t["rol_ad"]["eslesen"] == 1
