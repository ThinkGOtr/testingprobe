"""toolchain-worker HTTP uçları: /symbols, /ast-guard (gerçek Node araçlarıyla), /locator-probe."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    Forge,
    make_fake_node,
    requires_ast_guard,
    requires_node,
    requires_symbols,
)
from worker import app as worker_app
from worker.app import app


@pytest.fixture
def client(env: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TP_NODE", "node")
    worker_app._SYMBOL_CACHE.clear()
    return TestClient(app)


CATALOG_LOCATORS = "e2e/pages/catalog/locators.ts"


def _edit_locators(forge: Forge, old: str, new: str) -> str:
    text = (forge.work / CATALOG_LOCATORS).read_text()
    assert old in text
    return text.replace(old, new)


@requires_node
@requires_symbols
def test_symbols_from_forge_commit(client: TestClient, forge: Forge) -> None:
    resp = client.post("/symbols", json={"sha": "main"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["sha"] == forge.main
    assert data["errors"] == []
    catalog = next(p for p in data["page_objects"] if p["class"] == "CatalogPage")
    add = next(m for m in catalog["methods"] if m["name"] == "addToCart")
    assert add["params"] == [
        {"name": "productCode", "type": "string", "optional": False},
        {"name": "quantity", "type": "number", "optional": False},
    ]
    assert add["kind"] == "action"
    assert catalog["locators"]["catalog.addToCart"]["within"] == "product-card-"
    # Commit'e göre: yeni bir metot yalnızca o commit'in tablosunda görünür.
    page = (forge.work / "e2e/pages/cart/cart.page.ts").read_text()
    head = forge.commit(
        "tp/case-yeni-metot",
        {
            "e2e/pages/cart/cart.page.ts": page.rstrip().removesuffix("}")
            + "\n  /** Yeni doğrulama. */\n  async expectYeni(adet: number): Promise<void> {\n"
            "    await expect(this.page.getByTestId(cart.total.testId)).toHaveText(String(adet));\n"
            "  }\n}\n"
        },
    )
    cart = next(
        p
        for p in client.post("/symbols", json={"sha": head}).json()["page_objects"]
        if p["class"] == "CartPage"
    )
    yeni = next(m for m in cart["methods"] if m["name"] == "expectYeni")
    assert yeni["kind"] == "expect" and yeni["doc"] == "Yeni doğrulama."
    main_cart = next(
        p
        for p in client.post("/symbols", json={"sha": forge.main}).json()["page_objects"]
        if p["class"] == "CartPage"
    )
    assert "expectYeni" not in [m["name"] for m in main_cart["methods"]]


def test_symbols_unknown_and_invalid(client: TestClient) -> None:
    assert client.post("/symbols", json={"sha": "f" * 40}).status_code == 404
    resp = client.post("/symbols", json={"sha": "-x"})
    assert resp.status_code == 422
    assert "geçersiz commit/ref" in resp.json()["detail"]


@requires_node
@requires_ast_guard
def test_ast_guard_repair_accepts_testid_only_change(client: TestClient, forge: Forge) -> None:
    head = forge.commit(
        "tp/repair-sepete-ekle",
        {CATALOG_LOCATORS: _edit_locators(forge, 'testId: "add-to-cart"', 'testId: "cart-add"')},
    )
    resp = client.post("/ast-guard", json={"base_sha": forge.main, "head_sha": head})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True and data["violations"] == []
    assert data["mode"] == "repair"
    assert data["report"]["testid_changes"][0]["after"] == "cart-add"


@requires_node
@requires_ast_guard
def test_ast_guard_repair_rejects_intent_and_test_change(client: TestClient, forge: Forge) -> None:
    head = forge.commit(
        "tp/repair-kotu",
        {
            CATALOG_LOCATORS: _edit_locators(
                forge, "Ürün kartında sepete ekleme butonu", "Başka bir buton"
            ),
            "e2e/tests/cart.spec.ts": "// testler silindi\n",
        },
    )
    data = client.post("/ast-guard", json={"base_sha": forge.main, "head_sha": head}).json()
    assert data["ok"] is False
    codes = {v["code"] for v in data["violations"]}
    assert {"field_changed", "non_locator_file_changed"} <= codes
    # pr modunda test dosyası değişikliği serbesttir.
    pr = client.post("/ast-guard", json={"base_sha": forge.main, "head_sha": head, "mode": "pr"})
    assert pr.json()["ok"] is True


def test_ast_guard_invalid_mode_and_unknown_commit(client: TestClient, forge: Forge) -> None:
    resp = client.post("/ast-guard", json={"base_sha": "main", "head_sha": "main", "mode": "x"})
    assert resp.status_code == 422
    resp = client.post("/ast-guard", json={"base_sha": "main", "head_sha": "e" * 40})
    assert resp.status_code == 404


# ------------------------------------------------------------------------- /locator-probe


def fake_probe(tmp_path: Path, out: dict[str, Any] | str) -> Path:
    text = out if isinstance(out, str) else json.dumps(out)
    return make_fake_node(
        tmp_path,
        f"""
        pathlib.Path({str(tmp_path / "probe-input.json")!r}).write_text(sys.argv[2])
        print({text!r})
        """,
        name="fake-probe-node",
    )


def _probe_input(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "probe-input.json").read_text())


def test_locator_probe_single_match_scoped(
    client: TestClient, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = {
        "ok": True,
        "matches": 1,
        "test_id": "cart-add",
        "test_ids": ["cart-add"],
        "scope_matches": 1,
        "http_status": 200,
        "final_path": "/katalog",
    }
    monkeypatch.setenv("TP_NODE", str(fake_probe(tmp_path, out)))
    monkeypatch.setenv("DEMO_WEB_URL", "http://demo-app-web:8080")
    resp = client.post(
        "/locator-probe",
        json={
            "sha": "main",
            "role": "button",
            "name": "Sepete ekle",
            "url_path": "/katalog",
            "within_test_id": "product-card-P-001",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["matches"] == 1 and data["test_id"] == "cart-add"
    assert data["oneri_uretilebilir"] is True
    assert data["scope_test_id"] == "product-card-P-001"
    assert data["sha"] == forge.main
    # DEMO_APP_BUILD_SHA yok: ölçüm çalışan uygulamada, sha uyumu doğrulanamadı → açık uyarı.
    assert data["olculen"] == "calisan_uygulama"
    assert data["sha_eslesmesi"] == "dogrulanamadi" and data["uygulama_sha"] is None
    assert "çalışan demo uygulamasında" in data["uyari"]
    sent = _probe_input(tmp_path)
    assert sent["base_url"] == "http://demo-app-web:8080"
    assert sent["scope_test_id"] == "product-card-P-001"
    assert sent["login"] == {"kullanici_adi": "bayi1", "parola": "Demo123!"}


SINGLE_MATCH = {"ok": True, "matches": 1, "test_id": "cart-add", "test_ids": ["cart-add"]}
PROBE_BODY = {"sha": "main", "role": "button", "name": "Sepete ekle", "url_path": "/katalog"}


def test_locator_probe_app_build_sha_matches(
    client: TestClient, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_probe(tmp_path, SINGLE_MATCH)))
    monkeypatch.setenv("DEMO_APP_BUILD_SHA", forge.main[:12])  # kısa sha çözülür
    data = client.post("/locator-probe", json=PROBE_BODY).json()
    assert data["sha_eslesmesi"] == "eslesiyor" and data["uygulama_sha"] == forge.main
    assert data["uyari"] is None and data["oneri_uretilebilir"] is True


def test_locator_probe_app_build_sha_differs_blocks_suggestion(
    client: TestClient, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = forge.commit("tp/case-x", {"web/src/x.tsx": "x"})
    monkeypatch.setenv("TP_NODE", str(fake_probe(tmp_path, SINGLE_MATCH)))
    monkeypatch.setenv("DEMO_APP_BUILD_SHA", forge.main)
    data = client.post("/locator-probe", json={**PROBE_BODY, "sha": other}).json()
    assert data["sha"] == other and data["uygulama_sha"] == forge.main
    assert data["sha_eslesmesi"] == "farkli" and data["farkli_yollar"] == ["web"]
    # Ölçüm başka uygulama ağacında yapıldı: tek eşleşme olsa bile öneri üretilmez, insana gider.
    assert data["matches"] == 1 and data["test_id"] == "cart-add"
    assert data["oneri_uretilebilir"] is False and other[:12] in data["uyari"]


def test_locator_probe_e2e_only_branch_matches_running_app(
    client: TestClient, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kod üretimi/onarım dalı yalnızca e2e/ değiştirir: uygulama ağacı aynı → `eslesiyor`."""
    other = forge.commit("tp/case-y", {"e2e/x.txt": "x"})
    monkeypatch.setenv("TP_NODE", str(fake_probe(tmp_path, SINGLE_MATCH)))
    monkeypatch.setenv("DEMO_APP_BUILD_SHA", forge.main)
    data = client.post("/locator-probe", json={**PROBE_BODY, "sha": other}).json()
    assert data["sha_eslesmesi"] == "eslesiyor" and data["uygulama_sha"] == forge.main
    assert data["oneri_uretilebilir"] is True and data["uyari"] is None


def test_locator_probe_build_sha_file_wins_over_env(
    client: TestClient, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """forge-init/sync-web'in yazdığı dosya konteyner yeniden oluşturmadan güncel sha'yı verir."""
    web = forge.commit("tp/web", {"web/src/x.tsx": "y"})
    sha_file = tmp_path / "demo-app-web.sha"
    sha_file.write_text(f"{web}\n")
    monkeypatch.setenv("TP_APP_BUILD_SHA_FILE", str(sha_file))
    monkeypatch.setenv("DEMO_APP_BUILD_SHA", forge.main)
    monkeypatch.setenv("TP_NODE", str(fake_probe(tmp_path, SINGLE_MATCH)))
    data = client.post("/locator-probe", json={**PROBE_BODY, "sha": web}).json()
    assert data["sha_eslesmesi"] == "eslesiyor" and data["uygulama_sha"] == web
    data = client.post("/locator-probe", json=PROBE_BODY).json()  # main: web farklı
    assert data["sha_eslesmesi"] == "farkli"


def test_locator_probe_app_build_sha_unknown_in_forge(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_probe(tmp_path, SINGLE_MATCH)))
    for bad in ("f" * 40, "-x; rm"):
        monkeypatch.setenv("DEMO_APP_BUILD_SHA", bad)
        data = client.post("/locator-probe", json=PROBE_BODY).json()
        assert data["sha_eslesmesi"] == "dogrulanamadi" and "forge'da bulunamadı" in data["uyari"]


def test_locator_probe_multiple_matches_no_suggestion(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = {
        "ok": True,
        "matches": 5,
        "test_id": None,
        "test_ids": ["cart-add"] * 5,
        "scope_matches": None,
    }
    monkeypatch.setenv("TP_NODE", str(fake_probe(tmp_path, out)))
    data = client.post(
        "/locator-probe",
        json={"sha": "main", "role": "button", "name": "Sepete ekle", "url_path": "/katalog"},
    ).json()
    assert data["matches"] == 5 and data["test_id"] is None
    assert data["oneri_uretilebilir"] is False


def test_locator_probe_untrusted_testid_and_login_page(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = {"ok": True, "matches": 1, "test_id": 'x"] , evil', "test_ids": ['x"] , evil']}
    monkeypatch.setenv("TP_NODE", str(fake_probe(tmp_path, out)))
    data = client.post(
        "/locator-probe",
        json={"sha": "main", "role": "button", "name": "Giriş yap", "url_path": "/giris"},
    ).json()
    assert data["test_id"] is None and data["test_id_raw"] == 'x"] , evil'
    assert data["oneri_uretilebilir"] is False
    assert "login" not in _probe_input(tmp_path)


def test_locator_probe_errors(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "TP_NODE", str(fake_probe(tmp_path, {"ok": False, "error": "giriş başarısız"}))
    )
    body = {"sha": "main", "role": "button", "name": "Sepete ekle", "url_path": "/katalog"}
    resp = client.post("/locator-probe", json=body)
    assert resp.status_code == 502 and "giriş başarısız" in resp.json()["detail"]
    for bad in ({"url_path": "http://evil/"}, {"role": "button; x"}, {"scope_test_id": 'a"]'}):
        assert client.post("/locator-probe", json={**body, **bad}).status_code == 422


def test_check_endpoint_validation(client: TestClient) -> None:
    resp = client.post("/check", json={"sha": "main", "test_files": ["../../x.spec.ts"]})
    assert resp.status_code == 422
    resp = client.post("/check", json={"sha": "main", "env": {"PATH": "/tmp"}})
    assert resp.status_code == 422
    assert client.post("/check", json={"sha": "d" * 40}).status_code == 404
