"""Ajan tarayıcı vekili: izin listesi, güvenilmeyen sarma, ajan bayisi, model dışı görüntü."""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import Image, MCPServer

from tp_core.features.codegen.browser import (
    AgentBrowser,
    AgentConfig,
    BrowserError,
    McpBrowserSession,
    McpToolError,
    ToolBudgetExceeded,
    ToolOutput,
    allowed_tools,
    mask_args,
    screenshot_writer,
)
from tp_core.gateway import FORBIDDEN_TOOLS

PNG = b"\x89PNG\r\n\x1a\nfake-png"


def _locatorlar() -> dict[str, dict[str, Any]]:
    import json

    tablo = json.loads((Path(__file__).resolve().parent / "symbols.json").read_text("utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for po in tablo["page_objects"]:
        for k, v in (po.get("locators") or {}).items():
            out.setdefault(k, v)
    return out


_LOCATORLAR = _locatorlar()


def _kart(kod: str, ref: int) -> str:
    return (
        f"  - generic [ref=e{ref}]:\n"
        f"    - paragraph [ref=e{ref + 1}]: {kod}\n"
        f'    - spinbutton "Adet" [ref=e{ref + 2}]\n'
        f'    - button "Sepete ekle" [ref=e{ref + 3}]\n'
    )


# Playwright MCP 1.64 `browser_snapshot` biçimi: golden adımlarının `hedef`lerinin (rol/ad/kapsam)
# hepsini taşıyan tek sayfa (gateway REPLAY ref'leri bu canlı snapshot'tan çözer).
SNAPSHOT = (
    "### Page\n- Page URL: http://demo-app-web:8080/katalog\n### Snapshot\n```yaml\n"
    "- generic [ref=e1]:\n"
    '  - textbox "Kullanıcı adı" [ref=e16]\n'
    '  - textbox "Parola" [ref=e19]\n'
    '  - button "Giriş yap" [ref=e20]\n'
    '  - link "Sepet 6 ürün" [ref=e33]\n'
    '  - link "Siparişlerim" [ref=e34]\n'
    + _kart("P-001", 40)
    + _kart("P-002", 50)
    + _kart("P-004", 60)
    + "  - alert [ref=e90]: Minimum sipariş tutarı 250,00 TL\n"
    + '  - button "Siparişi onayla" [ref=e91]\n'
    + "```\n"
)
# Playwright MCP 0.0.83 tools/list (--caps=testing): izinli + yasak + verilmeyen araçlar.
MCP_TOOLS = [
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_select_option",
    "browser_wait_for",
    "browser_generate_locator",
    "browser_take_screenshot",
    "browser_evaluate",
    "browser_run_code",
    "browser_file_upload",
    "browser_press_key",
    "browser_verify_text_visible",
]


class FakeSession:
    """Sahte Playwright MCP oturumu. `browser_type` gerçek MCP gibi yazılan metni yankılar
    (`fill('…')`); `hata(araç)` True dönerse araç `isError` sonucu verir."""

    def __init__(
        self, araclar: list[str] = MCP_TOOLS, hata: Callable[[str], bool] | None = None
    ) -> None:
        self.araclar = araclar
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False
        self.hata = hata

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {"name": n, "description": f"{n} aracı", "input_schema": {"type": "object"}}
            for n in self.araclar
        ]

    def call(self, name: str, args: Mapping[str, Any]) -> ToolOutput:
        self.calls.append((name, dict(args)))
        if name == "browser_take_screenshot":
            return ToolOutput("ekran görüntüsü", [("image/png", PNG)])
        if self.hata is not None and self.hata(name):
            return ToolOutput(
                f'### Error\nError: "{args.get("target")}" does not match any elements',
                is_error=True,
            )
        if name == "browser_snapshot":
            return ToolOutput(SNAPSHOT)
        if name == "browser_generate_locator":
            return ToolOutput(f"### Result\n{self.locator(str(args.get('element') or ''))}\n")
        if name == "browser_type":
            return ToolOutput(
                "### Ran Playwright code\n```js\n"
                f"await page.locator('{args.get('target')}').fill('{args.get('text')}');\n```\n"
                "### Page\n- Page URL: http://demo-app-web:8080/giris\n"
                "- [Snapshot](../../tmp/playwright-mcp/page-2026-10-31T09-58-52-983Z.yml)"
            )
        return ToolOutput(f'- Page Snapshot\n  - button "Giriş yap" [ref=e{len(self.calls)}]')

    # `yanlis_locator` verilirse `browser_generate_locator` onu döner (ref kayması / yanlış
    # eleman benzetimi); yoksa page object kütüphanesindeki (symbols.json) testId zinciri.
    yanlis_locator: str | None = None

    def locator(self, element: str) -> str:
        import re

        if self.yanlis_locator is not None:
            return self.yanlis_locator
        m = re.search(r"\(([A-Za-z]\w*\.[A-Za-z]\w*)", element)
        spec = _LOCATORLAR.get(m.group(1) if m else "")
        if spec is None:
            return "getByRole('button')"
        kod = re.search(r"\b([A-Z]-\d{3})\b", element)
        kod_ = kod.group(1) if kod else "P-001"
        if spec.get("prefix"):
            return f"getByTestId('{spec['testId']}{kod_}')"
        if spec.get("within"):
            return f"getByTestId('{spec['within']}{kod_}').getByTestId('{spec['testId']}')"
        return f"getByTestId('{spec['testId']}')"

    def close(self) -> None:
        self.closed = True


def test_araclar_izin_listesiyle_suzulur() -> None:
    agent = AgentBrowser(FakeSession())
    adlar = {t.name for t in agent.tool_specs()}
    assert adlar == allowed_tools()
    assert not adlar & FORBIDDEN_TOOLS
    assert "browser_take_screenshot" not in adlar and "browser_press_key" not in adlar


def test_izinsiz_arac_ve_disari_gezinme_reddedilir() -> None:
    s = FakeSession()
    agent = AgentBrowser(s)
    with pytest.raises(BrowserError):
        agent("browser_evaluate", {"function": "() => document.cookie"})
    with pytest.raises(BrowserError):
        agent("browser_navigate", {"url": "http://jira-sim:8090/"})
    with pytest.raises(BrowserError):
        agent("browser_navigate", {"url": "http://demo-app-web:8080.evil.com/"})
    assert s.calls == []
    agent("browser_navigate", {"url": "http://demo-app-web:8080/giris"})
    assert s.calls == [("browser_navigate", {"url": "http://demo-app-web:8080/giris"})]


def test_sonuc_guvenilmeyen_blokta_ve_goruntu_modele_gitmez(tmp_path: Path) -> None:
    s = FakeSession()
    agent = AgentBrowser(s, screenshot_sink=screenshot_writer(tmp_path, "sid-1"), step_offset=4)
    out = agent("browser_click", {"element": "Giriş yap", "target": "[data-testid=login-submit]"})
    assert out.startswith('<untrusted kind="snapshot" source="tool:browser_click"')
    assert "Page Snapshot" in out
    assert "image" not in out and "ekran görüntüsü" not in out  # görüntü sonucu modele gitmez
    assert s.calls[-1] == ("browser_take_screenshot", {"type": "png"})
    ref = agent.pop_screenshot()
    assert ref == "codegen/sid-1/step-5.png"
    assert (tmp_path / ref).read_bytes() == PNG
    assert agent.pop_screenshot() is None


def test_goruntu_yazilamazsa_akis_durmaz(tmp_path: Path) -> None:
    def bozuk(_n: int, _png: bytes) -> str:
        raise PermissionError("salt okunur")

    agent = AgentBrowser(FakeSession(), screenshot_sink=bozuk)
    assert "### Snapshot" in agent("browser_snapshot", {})
    assert agent.pop_screenshot() is None


def test_ajan_bayisi_yerine_gecer() -> None:
    s = FakeSession()
    agent = AgentBrowser(s, config=AgentConfig(agent_dealer="bayi3"), case_dealers=["bayi1"])
    agent("browser_type", {"element": "Kullanıcı adı", "target": "#u", "text": "bayi1"})
    agent("browser_type", {"element": "Adet", "target": "#q", "text": "7"})
    assert s.calls[0][1]["text"] == "bayi3" and s.calls[1][1]["text"] == "7"
    assert agent.substitutions == 1


def test_arac_butcesi() -> None:
    agent = AgentBrowser(FakeSession(), config=AgentConfig(max_tool_calls=2))
    agent("browser_snapshot", {})
    agent("browser_snapshot", {})
    with pytest.raises(ToolBudgetExceeded):
        agent("browser_snapshot", {})


def test_parola_kayitta_gizlenir() -> None:
    assert mask_args({"element": "Parola", "text": "Demo123!"})["text"] == "***"
    assert mask_args({"element": "Adet", "text": "7"})["text"] == "7"


def test_mcp_oturumu_sdk_istemcisiyle() -> None:
    """Eşzamanlı sarmalayıcı: resmi `mcp.Client` ile (süreç içi sunucu; URL'de aynı kod yolu)."""
    server = MCPServer("sahte-playwright")

    @server.tool()
    def browser_snapshot() -> str:
        return '- Page Snapshot\n  - heading "Bayi girişi"'

    @server.tool()
    def browser_take_screenshot(type: str = "png") -> Image:
        return Image(data=PNG, format="png")

    oturum = McpBrowserSession(server, timeout_s=10)
    try:
        adlar = {t["name"] for t in oturum.list_tools()}
        assert {"browser_snapshot", "browser_take_screenshot"} <= adlar
        assert "Bayi girişi" in oturum.call("browser_snapshot", {}).text
        goruntu = oturum.call("browser_take_screenshot", {"type": "png"})
        assert goruntu.images and goruntu.images[0][1] == PNG
    finally:
        oturum.close()
    with pytest.raises(BrowserError):
        oturum.call("browser_snapshot", {})


def test_base64_cozulur() -> None:
    from tp_core.features.codegen.browser import _output_of

    class Blok:
        def __init__(self, **kw: Any) -> None:
            self.__dict__.update(kw)

    sonuc = Blok(
        content=[
            Blok(type="text", text="a"),
            Blok(type="image", data=base64.b64encode(PNG).decode(), mime_type="image/png"),
        ],
        is_error=True,
    )
    out = _output_of(sonuc)
    assert out.text == "a" and out.images == [("image/png", PNG)] and out.is_error


def test_ajan_sepeti_herkese_acik_api_ile_bosaltilir() -> None:
    import httpx

    from tp_core.features.codegen.browser import AgentConfig, reset_agent_cart

    istekler: list[tuple[str, str, bytes]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        istekler.append((req.method, req.url.path, req.content))
        return httpx.Response(200, json={})

    cfg = AgentConfig.from_env({"TP_AGENT_DEALER": "bayi3"})
    with httpx.Client(base_url=cfg.demo_web_url, transport=httpx.MockTransport(handler)) as c:
        assert reset_agent_cart(cfg, client=c) is True
    assert [(m, p) for m, p, _ in istekler] == [
        ("POST", "/api/auth/login"),
        ("DELETE", "/api/cart"),
        ("POST", "/api/auth/logout"),
    ]
    assert b'"bayi3"' in istekler[0][2]

    def hata(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    with httpx.Client(base_url=cfg.demo_web_url, transport=httpx.MockTransport(hata)) as c:
        assert reset_agent_cart(cfg, client=c) is False  # doğrulamayı durdurmaz


def test_adim_ozeti_sarmal_ve_kod_citlerini_atar() -> None:
    from tp_core.features.codegen.service import adim_ozeti

    ham = (
        '<untrusted kind="snapshot" source="tool:x" id="1">\n'
        "### Page\n```yaml\n- main\n```\n</untrusted>"
    )
    assert adim_ozeti(ham) == "### Page - main"
    assert adim_ozeti(None) == ""


# ------------------------------------------------- parola, MCP hatası, insan özeti


def test_parola_ozetlerde_ve_model_metninde_maskelenir() -> None:
    from tp_core.features.codegen.ozet import adim_ozeti, ham_cikti

    s = FakeSession()
    agent = AgentBrowser(s, config=AgentConfig(agent_password="Gizli!Parola9"), secrets=["x"])
    out = agent("browser_type", {"element": "Parola", "target": "#p", "text": "Demo123!"})
    assert "Demo123!" not in out and "fill('***')" in out  # modele/denetime de gitmez
    assert s.calls[0][1]["text"] == "Demo123!"  # ajan bayisi girişi yok: case parolası yazılır
    ham = "await page.locator('[data-testid=\"login-password\"]').fill('Demo123!');"
    assert "Demo123!" not in adim_ozeti(ham, gizli=["Demo123!"])
    assert "Demo123!" not in ham_cikti(ham, agent.gizliler)


def test_ajan_bayisi_girisinde_ajan_parolasi_yazilir() -> None:
    s = FakeSession()
    cfg = AgentConfig(agent_dealer="bayi3", agent_password="Ajan!Parola9")
    agent = AgentBrowser(s, config=cfg, case_dealers=["bayi1"])
    agent("browser_type", {"element": "Kullanıcı adı", "target": "#u", "text": "bayi1"})
    out = agent("browser_type", {"element": "Parola", "target": "#p", "text": "Demo123!"})
    assert s.calls[0][1]["text"] == "bayi3"
    assert s.calls[1][1]["text"] == "Ajan!Parola9"
    assert "Ajan!Parola9" not in out and "Demo123!" not in out
    assert agent.yerine_gecenler == {"bayi1": "bayi3"}
    # REPLAY kaydı ajan bayisini doğrudan yazar: parola yine ajanınkiyle değişir.
    s2 = FakeSession()
    agent2 = AgentBrowser(s2, config=cfg, case_dealers=["bayi1"])
    agent2("browser_type", {"element": "Kullanıcı adı", "target": "#u", "text": "bayi3"})
    agent2("browser_type", {"element": "Parola", "target": "#p", "text": "Demo123!"})
    assert [a["text"] for n, a in s2.calls if n == "browser_type"] == ["bayi3", "Ajan!Parola9"]


def test_mcp_hatasi_yapilandirilmis_sonuc_ve_istisna() -> None:
    s = FakeSession(hata=lambda ad: ad == "browser_click")
    agent = AgentBrowser(s)
    agent("browser_snapshot", {})
    sonuc = agent.pop_sonuc()
    assert sonuc is not None and sonuc.ok and agent.pop_sonuc() is None
    with pytest.raises(McpToolError) as exc:
        agent("browser_click", {"element": "Sepete ekle", "target": "#yok"})
    assert str(exc.value).startswith('<untrusted kind="snapshot"')  # model hatayı sarmalı görür
    sonuc = agent.pop_sonuc()
    assert sonuc is not None and not sonuc.ok and "does not match" in (sonuc.hata or "")
    with pytest.raises(BrowserError):
        agent("browser_navigate", {"url": "http://evil/"})
    sonuc = agent.pop_sonuc()
    assert sonuc is not None and not sonuc.ok


def test_gateway_mcp_hatasini_is_error_olarak_isaretler() -> None:
    from tp_core.gateway.core import Gateway

    agent = AgentBrowser(FakeSession(hata=lambda _ad: True))
    metin, is_error = Gateway._execute(agent, "browser_click", {"target": "#x"})
    assert is_error and metin.startswith("Araç hatası (McpToolError)")


def test_insan_ozeti_ve_ham_cikti() -> None:
    from tp_core.features.codegen.ozet import ham_cikti, insan_ozeti

    assert insan_ozeti("browser_navigate", {"url": "http://demo-app-web:8080/giris"}) == (
        "Sayfa açıldı: /giris"
    )
    assert insan_ozeti("browser_click", {"element": "Sepet"}, url="/sepet") == (
        "Tıklandı: Sepet — /sepet"
    )
    assert insan_ozeti("browser_type", {"element": "Parola", "text": "***"}) == (
        'Yazıldı: Parola = "***"'
    )
    assert insan_ozeti("browser_type", {"element": "Adet", "text": "7"}) == 'Yazıldı: Adet = "7"'
    assert insan_ozeti("browser_evaluate", {}, izinli=False).startswith("İzinsiz araç")
    assert "başarısız: yok" in insan_ozeti("browser_click", {"element": "X"}, ok=False, hata="yok")
    ham = (
        '<untrusted kind="snapshot" source="tool:browser_type" id="1">### Ran Playwright code\n'
        "```js\nawait page.fill('bayi3');\n```\n- Page URL: http://demo-app-web:8080/katalog\n"
        "- [Snapshot](../../tmp/playwright-mcp/page-1.yml) /tmp/playwright-mcp/x.yml</untrusted>"
    )
    temiz = ham_cikti(ham)
    assert "untrusted" not in temiz and "```" not in temiz
    assert "Snapshot" not in temiz and "tmp/" not in temiz and "/katalog" in temiz
