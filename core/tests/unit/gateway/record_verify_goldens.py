"""verify_and_map golden'larının tarayıcı adımlarını gerçek Playwright MCP'de yeniden kaydeder.

pytest bu dosyayı toplamaz (adı `test_` ile başlamaz); golden'lar demo-app ile sürüklendiğinde elle
koşturulur. Model çıktısı (step_mapping / expects / missing_methods) **elle hazırlanmıştır** ve
burada case'ten deterministik olarak kurulur; yalnızca tarayıcı adımları ve gözlemler (snapshot
özetleri, evidence_ref'teki gözlenen değerler) gerçek uygulamadan gelir.

Önkoşul (compose dışı, yerel; e2e `webServer` yolunun aynısı):

    # demo-app API (SQLite, test modu) ve web (vite preview) — ayrı terminallerde
    cd demo-app/api && DEMOAPP_DATABASE_URL=sqlite:////tmp/kayit.db DEMOAPP_TEST_MODE=1 \\
        DEMOAPP_TEST_TOKEN=yerel uv run uvicorn demoapp_api.main:app --port 18300
    cd demo-app/web && npx vite build --outDir /tmp/webdist && \\
        DEMOAPP_API_URL=http://127.0.0.1:18300 npx vite preview --outDir /tmp/webdist --port 18381
    # Playwright MCP (toolchain/package.json sürümü), compose'daki bayraklarla
    npx @playwright/mcp@<sürüm> --headless --browser chromium --port 18931 --isolated \\
        --caps=testing --allowed-origins http://127.0.0.1:18381

    cd core && uv run python -m tests.unit.gateway.record_verify_goldens \\
        --mcp http://localhost:18931/mcp --app http://127.0.0.1:18381 \\
        --api http://127.0.0.1:18300 --token yerel [--only TPD-1-C3]

Her case'ten önce doğrulama bayisi (`bayi3`) `/test/reset` ile sıfırlanır (kod üretimi de her
case'ten önce aynısını yapmalıdır). Kayıttaki yerel kök `http://demo-app-web:8080` ile değiştirilir.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tp_core.gateway import (
    VERIFY_AGENT_DEALER,
    VERIFY_BASE_URL,
    approved_case_text,
    find_rules_dir,
)
from tp_core.gateway.snapshot_refs import Hedef, locate_line

RULES = find_rules_dir()
REPLAY = RULES / "replay"
PASSWORD = "Demo123!"
SCENARIO_F2 = "f2-kod-hatasi"

NOTE = (
    "Adlandırılmış golden kayıt (REPLAY-MISS yedeği). Model çıktısı (step_mapping/expects/"
    "missing_methods) elle hazırlandı (canlı model çıktısı değil; ai_call.model = golden-elle). "
    "Tarayıcı adımları demo-app'in güncel kaynağına (e2e webServer yolu) karşı Playwright MCP "
    "{mcp} (--isolated, --caps=testing) ile koşturulup kaydedildi "
    "(core/tests/unit/gateway/record_verify_goldens.py); yerel kök "
    f"{VERIFY_BASE_URL} ile değiştirildi. Ajan tarayıcısı doğrulama bayisiyle "
    f"({VERIFY_AGENT_DEALER}) girer; case'teki giriş verisi eşleme argümanıdır. Locator "
    "doğrulaması: eylemde kullanılan her locator ilk kullanımından önce doğrulanır — eleman son "
    "snapshot'ta sembol tablosundaki rol/adla bulunur, browser_generate_locator o snapshot "
    "ref'iyle çağrılır ve dönen getByTestId page object'in testId'siyle karşılaştırılır; "
    "eylemler testId seçicisiyle yapılır. Snapshot ref'leri oturuma özgüdür ve aynı yörüngede "
    "bile koşudan koşuya kayabilir: kayıttaki ref yalnızca o kaydın gözlemidir; adımın "
    "`hedef` alanı (rol/ad/kapsam) REPLAY'de ref'in canlı son snapshot'tan yeniden çözülmesi "
    "içindir (gateway.snapshot_refs). evidence_ref'teki 'kayıttaki not' değerleri kayıt "
    "anındaki sayfadandır; REPLAY koşusunda yeniden ölçülmez. Canlı modelle yeniden "
    "kaydedilmeli (TP_MODEL_MODE=record). Girdi beyanı (input_match) eşleşirse mod "
    "REPLAY (köken golden_matched), eşleşmezse REPLAY-MISS."
)


def tid(*ids: str) -> str:
    return " ".join(f'[data-testid="{i}"]' for i in ids)


# ------------------------------------------------------------------ snapshot özeti


def _yaml(result: str) -> list[str]:
    m = re.search(r"```yaml\n(.*?)```", result, re.DOTALL)
    return m.group(1).splitlines() if m else []


def _url_path(result: str) -> str | None:
    m = re.search(r"Page URL: https?://[^/\s]+(/\S*)", result)
    return m.group(1) if m else None


_REF = re.compile(r"\s*\[ref=e\d+\]|\s*\[cursor=pointer\]|\s*\[active\]")
_NOISE = re.compile(r"\s*\[cursor=pointer\]|\s*\[active\]")


def _clean(line: str) -> str:
    return _REF.sub("", line).strip().removeprefix("- ").rstrip(":")


def _with_ref(line: str) -> str:
    """Özet satırı: snapshot ref'i KALIR (ajan elemanı rol/ad + ref ile bulur)."""
    return _NOISE.sub("", line).strip().removeprefix("- ").rstrip(":")


@dataclass
class Page:
    path: str
    lines: list[str]

    def find(self, pattern: str) -> list[str]:
        rx = re.compile(pattern)
        return [_clean(x) for x in self.lines if rx.search(x)]

    def find_refs(self, pattern: str) -> list[str]:
        rx = re.compile(pattern)
        return [_with_ref(x) for x in self.lines if rx.search(x)]

    def locate(self, hedef: Hedef) -> tuple[str, str]:
        """Rol + erişilebilir ad (+ kapsam) ile eleman (ajanın ve REPLAY'in yaptığı gibi;
        `gateway.snapshot_refs.locate_line`): (ref, özet satırı)."""
        found = locate_line(self.lines, hedef)
        if found is None:
            raise SystemExit(f"eleman yok: {hedef.describe()} ({self.path})")
        return found[0], _with_ref(found[1])


def parse_page(result: str) -> Page:
    return Page(_url_path(result) or "?", _yaml(result))


def _product_card(page: Page, code: str) -> list[str]:
    out: list[str] = []
    inside = False
    for raw in page.lines:
        line = _clean(raw)
        if line.startswith("paragraph: ") and re.fullmatch(r"paragraph: P-\d{3}", line):
            inside = line == f"paragraph: {code}"
        if inside and re.match(r"(heading|paragraph|spinbutton|button|status)", line):
            out.append(_with_ref(raw) if line.startswith(("spinbutton", "button")) else line)
    return out


def summarize_snapshot(page: Page, *, product: str | None = None) -> str:
    parts = [f"URL {page.path}"]
    parts += page.find(r"heading \"")[:1]
    if page.path.startswith("/giris"):
        parts += page.find_refs(r"textbox \"|button \"Giriş yap\"|alert")
    else:
        parts += page.find_refs(r"link \"Sepet \d+ ürün\"")
        parts += page.find(r": [^:]*Bayi$")[:1]
    if page.path.startswith("/katalog") and product:
        parts += _product_card(page, product)
    if page.path.startswith("/sepet"):
        parts += page.find(r"rowheader \"|cell \"|term|definition")
        parts += page.find_refs(r"alert|button \"Siparişi onayla")
        parts += page.find(r"Sepetiniz boş")
    if page.path.startswith("/siparis/"):
        parts += page.find(r"strong|term|definition")
    if page.path.startswith("/siparisler"):
        # Tarih hücresi her koşuda değişir; özete girmez.
        parts += page.find(r'link "SP-\d+"|cell "[\d.]+,\d{2} TL"|Henüz siparişiniz yok')
    summary = " | ".join(p for p in parts if p)
    return summary[:500]


def summarize_action(result: str) -> str:
    code = re.search(r"```js\n(.*?)\n```", result, re.DOTALL)
    head = code.group(1).strip() if code else ""
    loc = re.search(r"### Result\n(.*?)(?:\n###|\Z)", result, re.DOTALL)
    if not head and loc:
        head = loc.group(1).strip()
    path = _url_path(result)
    return f"{head} · URL {path}" if path else head


# ------------------------------------------------------------------ plan (case → araç çağrıları)


@dataclass
class Call:
    tool: str
    args: dict[str, Any]
    product: str | None = None
    tag: str | None = None  # gözlem etiketi: "catalog", "cart", "confirmation", "history", …
    # browser_generate_locator: hedef (rol, ad, kapsam) — ref, SON snapshot'ta rol/adla bulunur
    # (oturuma özgü; kayıt anında çözülür, REPLAY'de yeniden) ve sonuç bu testId'yi göstermelidir.
    locate: Hedef | None = None
    expect_test_id: str | None = None


@dataclass
class Plan:
    calls: list[Call] = field(default_factory=list)

    def add(self, tool: str, args: dict[str, Any] | None = None, **kw: Any) -> None:
        self.calls.append(Call(tool, args or {}, **kw))


def _cart_lines(step: dict[str, Any]) -> list[tuple[str, int]]:
    return [
        (m.group(1), int(m.group(2)))
        for m in re.finditer(r"(P-\d{3}) × (\d+)", step.get("data") or "")
    ]


def plan_for(case: dict[str, Any], app: str) -> Plan:
    plan = Plan()
    located: set[str] = set()
    last_product: str | None = None
    for step in case["steps"]:
        action = step["action"]
        if action == "Giriş sayfasını aç":
            plan.add("browser_navigate", {"url": f"{app}/giris"})
            plan.add("browser_snapshot", tag="login-form")
        elif "giriş yap" in action.lower() or "Giriş yap" in action:
            _, _, pwd = (step.get("data") or "").partition(" / ")
            password = pwd or PASSWORD
            # Eylemde kullanılan her locator ilk kullanımından önce doğrulanır (prompt v3).
            for element, hedef, test_id in (
                (
                    'textbox "Kullanıcı adı" (login.username)',
                    Hedef("textbox", "Kullanıcı adı"),
                    "login-username",
                ),
                ('textbox "Parola" (login.password)', Hedef("textbox", "Parola"), "login-password"),
                ('button "Giriş yap" (login.submit)', Hedef("button", "Giriş yap"), "login-submit"),
            ):
                plan.add(
                    "browser_generate_locator",
                    {"element": element},
                    locate=hedef,
                    expect_test_id=test_id,
                )
            plan.add(
                "browser_type",
                {
                    "element": "Kullanıcı adı",
                    "target": tid("login-username"),
                    "text": VERIFY_AGENT_DEALER,
                },
            )
            plan.add(
                "browser_type",
                {"element": "Parola", "target": tid("login-password"), "text": password},
            )
            plan.add("browser_click", {"element": "Giriş yap", "target": tid("login-submit")})
            plan.add("browser_snapshot", tag="after-login", product=_first_product(case))
        elif _cart_lines(step):
            for code, qty in _cart_lines(step):
                card = f"product-card-{code}"
                if f"qty-input-{code}" not in located:
                    plan.add(
                        "browser_generate_locator",
                        {"element": f'{code} kartında spinbutton "Adet" (catalog.quantityInput)'},
                        locate=Hedef("spinbutton", "Adet", f"paragraph: {code}"),
                        expect_test_id=f"qty-input-{code}",
                    )
                    located.add(f"qty-input-{code}")
                if "add-to-cart" not in located:
                    plan.add(
                        "browser_generate_locator",
                        {"element": f'{code} kartında button "Sepete ekle" (catalog.addToCart)'},
                        locate=Hedef("button", "Sepete ekle", f"paragraph: {code}"),
                        expect_test_id="add-to-cart",
                    )
                    located.add("add-to-cart")
                plan.add(
                    "browser_type",
                    {
                        "element": f"{code} adet",
                        "target": tid(card, f"qty-input-{code}"),
                        "text": str(qty),
                    },
                )
                plan.add(
                    "browser_click",
                    {"element": f"{code} kartında Sepete ekle", "target": tid(card, "add-to-cart")},
                )
                plan.add("browser_wait_for", {"text": f"{qty} adet sepete eklendi."})
                last_product = code
            plan.add("browser_snapshot", tag="catalog", product=last_product)
            if "sayacı" in step["expected"] and "nav-cart" not in located:
                # Sayaç (nav.cartCount) etkileşimsiz bir alt elemandır; generate_locator onu en
                # yakın etkileşimli ataya (nav.cart bağlantısı) çevirir. Doğrulanan bağlantıdır;
                # sayaç değeri snapshot'ta bağlantının içinde okunur.
                plan.add(
                    "browser_generate_locator",
                    {"element": 'link "Sepet" (nav.cart; sayaç içinde)'},
                    locate=Hedef("link", "Sepet"),
                    expect_test_id="nav-cart",
                )
                located.add("nav-cart")
        elif action == "Üst menüden sepete git":
            plan.add("browser_click", {"element": "Sepet", "target": tid("nav-cart")})
            plan.add("browser_snapshot", tag="cart")
            text = " ".join([step["expected"], case["expected_result"]])
            if "Minimum sipariş tutarı" in text and "uyarısı görünür" in text:
                plan.add(
                    "browser_generate_locator",
                    {"element": "alert: minimum sipariş uyarısı (cart.minOrderWarning)"},
                    locate=Hedef("alert"),
                    expect_test_id="min-order-warning",
                )
        elif "Siparişi onayla" in action:
            plan.add(
                "browser_generate_locator",
                {"element": 'button "Siparişi onayla" (cart.checkoutSubmit)'},
                locate=Hedef("button", "Siparişi onayla"),
                expect_test_id="checkout-submit",
            )
            plan.add(
                "browser_click", {"element": "Siparişi onayla", "target": tid("checkout-submit")}
            )
            plan.add("browser_snapshot", tag="confirmation")
            plan.add(
                "browser_generate_locator",
                {"element": 'link "Siparişlerim" (nav.orders)'},
                locate=Hedef("link", "Siparişlerim"),
                expect_test_id="nav-orders",
            )
            plan.add("browser_click", {"element": "Siparişlerim", "target": tid("nav-orders")})
            plan.add("browser_snapshot", tag="history")
        else:
            raise SystemExit(f"plan yok: {action!r}")
    return plan


def _first_product(case: dict[str, Any]) -> str | None:
    for step in case["steps"]:
        lines = _cart_lines(step)
        if lines:
            return lines[0][0]
    return None


# ------------------------------------------------------------------ MCP


_GEN_TEST_ID = re.compile(r"getByTestId\('([^']+)'\)")


async def _run(mcp_url: str, calls: list[Call]) -> list[tuple[str, bool]]:
    """Plandaki çağrıları sırayla koşar. `locate`'li çağrının hedefi son snapshot'ta rol/adla
    bulunan ref olur (çağrının `args`'ına yazılır); sonuç beklenen testId'yi göstermezse kayıt
    durur (page object bayat ya da plan yanlış)."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    out: list[tuple[str, bool]] = []
    last: Page | None = None
    async with streamable_http_client(mcp_url) as streams:  # noqa: SIM117 (streams gerekli)
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            for call in calls:
                if call.locate is not None:
                    if last is None:
                        raise SystemExit(f"snapshot olmadan {call.tool}")
                    ref, _ = last.locate(call.locate)
                    call.args = {**call.args, "target": ref}
                res = await session.call_tool(call.tool, call.args)
                text = "\n".join(getattr(c, "text", "") for c in res.content)
                err = bool(getattr(res, "is_error", False) or getattr(res, "isError", False))
                if call.tool == "browser_snapshot":
                    last = parse_page(text)
                if call.expect_test_id is not None:
                    got = _GEN_TEST_ID.findall(text)
                    if not got or got[-1] != call.expect_test_id:
                        raise SystemExit(
                            f"{call.args}: locator {got} ≠ beklenen testId {call.expect_test_id}"
                        )
                out.append((text, err or text.startswith("### Error")))
    return out


def reset_dealer_public(app: str) -> None:
    """compose'a karşı kayıt: test API'si kapalıdır; ajan bayisinin sepeti uygulamanın herkese
    açık API'siyle boşaltılır (kod üretiminin `reset_agent_cart`'ı ile aynı yol)."""
    from tp_core.features.codegen.browser import AgentConfig, reset_agent_cart

    if not reset_agent_cart(AgentConfig(demo_web_url=app)):
        raise SystemExit("ajan bayisinin sepeti boşaltılamadı")


def reset_dealer(api: str, token: str) -> None:
    req = urllib.request.Request(
        f"{api}/test/reset",
        data=json.dumps({"kullanici_adi": VERIFY_AGENT_DEALER}).encode(),
        headers={"Content-Type": "application/json", "X-Demoapp-Test-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.status == 200


# ------------------------------------------------------------------ çıktı (elle; case'ten)


def _observed_cart(page: Page) -> dict[str, str]:
    cells = [re.sub(r'^cell "(.*)"$', r"\1", c) for c in page.find(r'cell "')]
    obs: dict[str, str] = {}
    if len(cells) >= 4:
        obs.update(adet=cells[1], bedava=cells[2], tutar=cells[3])
    for term, key in (
        ("Ara toplam", "ara"),
        ("Kampanya indirimi", "indirim"),
        ("Genel toplam", "toplam"),
    ):
        idx = next((i for i, x in enumerate(page.lines) if "term [ref" in x and term in x), None)
        if idx is not None and idx + 1 < len(page.lines):
            obs[key] = _clean(page.lines[idx + 1]).split(": ", 1)[-1].replace("−", "")
    warn = page.find(r"alert")
    if warn:
        obs["uyari"] = warn[0].split(": ", 1)[-1]
    btn = page.find(r'button "Siparişi onayla"')
    if btn:
        obs["onay"] = "pasif" if "[disabled]" in btn[0] else "aktif"
    return obs


def _cart_evidence(obs: dict[str, str], code: str | None) -> str:
    parts = []
    if code and "adet" in obs:
        parts.append(f"{code} satırı adet {obs['adet']}, bedava {obs['bedava']}")
    for key, label in (("ara", "ara toplam"), ("indirim", "indirim"), ("toplam", "toplam")):
        if key in obs:
            parts.append(f"{label} {obs[key]}")
    if "uyari" in obs:
        parts.append(f'uyarı "{obs["uyari"]}"')
    if "onay" in obs:
        parts.append(f'"Siparişi onayla" {obs["onay"]}')
    return "; ".join(parts)


def _cart_mismatch(step: dict[str, Any], obs: dict[str, str]) -> str:
    """Case'in beklediği ve sayfada gözlenenden farklı değerler (boş = fark yok)."""
    text = step["expected"]
    want: list[tuple[str, str, str]] = []
    m = re.search(r"bedava adet (\d+)", text)
    if m:
        want.append(("bedava", m.group(1), "bedava"))
    for key, label in (("ara", "ara toplam"), ("indirim", "indirim"), ("toplam", "toplam")):
        guard = r"(?<!ara )" if key == "toplam" else ""
        m = re.search(rf"(?<![A-Za-zçğıöşü]){guard}{label} ([\d.]+,\d{{2}} TL)", text)
        if m:
            want.append((key, m.group(1), label))
    return "; ".join(f"{label} {value}" for key, value, label in want if obs.get(key) != value)


Evidence = Callable[[dict[str, Page]], str]
RECORDED_NOTE = "kayıttaki not —"


def defect_candidate(case: dict[str, Any], pages: dict[str, Page]) -> dict[str, Any] | None:
    """Yapılandırılmış defect adayı beyanı (golden `defect_adayi`; demo_check bunu okur).

    Sepet adımında kayıt anında gözlenen değer case'in beklediğinden farklıysa (yerel kontrolde
    assertion kırmızı olacak) adım ve fark yazılır; fark yoksa None."""
    if "cart" not in pages:
        return None
    cart = _observed_cart(pages["cart"])
    for step in case["steps"]:
        if step["action"] != "Üst menüden sepete git":
            continue
        diff = _cart_mismatch(step, cart)
        if diff:
            return {
                "step_id": step["id"],
                "beklenen": diff,
                "kayittaki_gozlem": _cart_evidence(cart, _first_product(case)),
            }
    return None


def build_output(
    case: dict[str, Any], pages: dict[str, Page], previous: dict[str, Any] | None
) -> dict[str, Any]:
    """Elle hazırlanmış eşleme: case'in eylem/veri alanlarından; evidence_ref gözlemden.

    `previous` (aynı adlı eski golden) varsa eşleme ve beklentiler ondan korunur; yalnızca
    evidence_ref gözlemle güncellenir. Yoksa (yeni senaryo case'i) `expects` verilir."""
    first = _first_product(case)
    cart = _observed_cart(pages["cart"]) if "cart" in pages else {}
    mapping = []
    base = (previous or {}).get("step_mapping") or []
    by_id = {m["step_id"]: m for m in base}
    for step in case["steps"]:
        sid = step["id"]
        m = dict(by_id.get(sid) or _default_mapping(step))
        if m["verified"]:
            m["evidence_ref"] = _evidence(step, m, pages, cart, first)
        mapping.append(m)
    return {
        "step_mapping": mapping,
        "expects": (previous or {}).get("expects") or [],
        "missing_methods": (previous or {}).get("missing_methods") or [],
    }


def _default_mapping(step: dict[str, Any]) -> dict[str, Any]:
    action = step["action"]
    if action == "Giriş sayfasını aç":
        po, method, args = "LoginPage", "goto", []
    elif "giriş yap" in action.lower():
        user, _, pwd = (step.get("data") or "").partition(" / ")
        po, method, args = "LoginPage", "login", [user, pwd]
    elif _cart_lines(step):
        code, qty = _cart_lines(step)[0]
        po, method, args = "CatalogPage", "addToCart", [code, qty]
    elif action == "Üst menüden sepete git":
        po, method, args = "CatalogPage", "openCart", []
    elif "Siparişi onayla" in action:
        po, method, args = "CartPage", "checkout", []
    else:
        raise SystemExit(f"eşleme yok: {action!r}")
    return {
        "step_id": step["id"],
        "po": po,
        "method": method,
        "args": args,
        "verified": True,
        "evidence_ref": None,
    }


def _evidence(
    step: dict[str, Any],
    m: dict[str, Any],
    pages: dict[str, Page],
    cart: dict[str, str],
    code: str | None,
) -> str:
    method = m["method"]
    if method == "goto":
        return 'Giriş formu (textbox "Kullanıcı adı", "Parola", button "Giriş yap") · /giris'
    if method == "login":
        page = pages.get("after-login")
        if page and page.path.startswith("/giris"):
            alert = page.find(r"alert")
            shown = alert[0].split(": ", 1)[-1] if alert else "?"
            return (
                f'button "Giriş yap" → /giris kalındı; alert "{shown}" '
                "(doğrulama bayisiyle denendi)"
            )
        dealer = next((x.split(": ", 1)[-1] for x in (page.find(r"Bayi$") if page else [])), "?")
        return (
            f'button "Giriş yap" → /katalog; oturum "{dealer}" '
            f"(doğrulama bayisi {VERIFY_AGENT_DEALER}; case'in bayisi {m['args'][0]} "
            "eşleme argümanıdır)"
        )
    if method == "addToCart":
        page = pages.get("catalog")
        count = page.find(r'link "Sepet \d+ ürün"') if page else []
        status = [x for x in (page.find(r"status") if page else []) if "eklendi" in x]
        shown = count[0].removeprefix("link ") if count else "?"
        stat = status[0].split(": ", 1)[-1] if status else "?"
        return (
            f'button "Sepete ekle" (product-card-{m["args"][0]}) → status "{stat}"; '
            f"sepet bağlantısı {shown}"
        )
    if method == "openCart":
        observed = _cart_evidence(cart, code)
        diff = _cart_mismatch(step, cart)
        # Değerler kayıt anındaki sayfadandır; REPLAY koşusunda yeniden ölçülmez (etiket bunu
        # söyler). Defect adayı kararı bu metinden değil golden'ın `defect_adayi` alanından okunur.
        return f'link "Sepet" → /sepet; {RECORDED_NOTE} gözlenen: {observed}' + (
            f" · beklenen: {diff}" if diff else ""
        )
    if method == "checkout":
        conf = pages.get("confirmation")
        number = conf.find(r"strong") if conf else []
        hist = pages.get("history")
        listed = bool(hist and hist.find(r"SP-\d{6}"))
        num = number[0].split(": ", 1)[-1] if number else "?"
        return (
            f'button "Siparişi onayla" → {conf.path if conf else "?"}; {RECORDED_NOTE} '
            f"sipariş numarası {num}; sipariş geçmişinde {'listelendi' if listed else 'görülmedi'}"
        )
    raise SystemExit(f"kanıt yok: {method}")


# ------------------------------------------------------------------ golden yazımı


def case_input_match(case: dict[str, Any], *, jira: str, sira: int) -> dict[str, Any]:
    """Girdi beyanı: yalnızca `case:<KEY>-C<n>` bloğu ve onaylı case'in TAM kanonik metni (case'e
    eklenen tek kelime bile REPLAY-MISS; `matching.input_mismatches` `case_text`)."""
    return {"sources": [f"case:{jira}-C{sira}"], "case_text": approved_case_text(case)}


def record_case(
    *,
    jira: str,
    sira: int,
    case: dict[str, Any],
    target: Path,
    case_source: str,
    args: argparse.Namespace,
    mcp_version: str,
    extra_note: str = "",
) -> None:
    previous = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else None
    prev_out = previous["output"] if previous else None
    plan = plan_for(case, args.app)
    if args.api:
        reset_dealer(args.api, args.token)
    else:
        reset_dealer_public(args.app)
    results = asyncio.run(_run(args.mcp, plan.calls))
    steps, pages = [], {}
    last_snapshot: tuple[int, Page] | None = None
    for call, (text, err) in zip(plan.calls, results, strict=True):
        if err:
            raise SystemExit(f"{target.name}: {call.tool} hata verdi:\n{text[:800]}")
        if call.locate is not None and last_snapshot is not None:
            # Ajanın bulduğu eleman (rol, ad, ref) o snapshot'ın özetinde görünür.
            idx, page = last_snapshot
            _, line = page.locate(call.locate)
            if line not in steps[idx]["result_summary"]:
                steps[idx]["result_summary"] += f" | {line}"
        if call.tool == "browser_snapshot":
            page = parse_page(text)
            summary = summarize_snapshot(page, product=call.product)
            last_snapshot = (len(steps), page)
            if call.tag:
                pages[call.tag] = page
        else:
            summary = summarize_action(text)
            if call.tool == "browser_click" and call.args.get("target") == tid("login-submit"):
                pass
        rewritten_args = json.loads(json.dumps(call.args).replace(args.app, VERIFY_BASE_URL))
        step: dict[str, Any] = {
            "tool": call.tool,
            "args": rewritten_args,
            "result_summary": summary.replace(args.app, VERIFY_BASE_URL),
            "allowed": True,
        }
        if call.locate is not None:
            # REPLAY ref'i bundan canlı snapshot'ta yeniden çözer (kayıttaki ref oturuma özgü).
            step["hedef"] = call.locate.as_dict()
        steps.append(step)
    if "after-login" in pages and pages["after-login"].path.startswith("/giris"):
        pass
    output = build_output(case, pages, prev_out)
    golden = {
        "kind": "agent",
        "purpose": "verify_and_map",
        "golden": target.relative_to(REPLAY / "verify_and_map" / "golden")
        .with_suffix("")
        .as_posix(),
        "note": NOTE.format(mcp=mcp_version) + extra_note,
        "input_match": case_input_match(case, jira=jira, sira=sira),
        "case": {
            "jira_key": jira,
            "sira_no": sira,
            "title": case["title"],
            "case_golden": case_source,
        },
        "steps": steps,
        "output": output,
    }
    defect = defect_candidate(case, pages)
    if defect:
        golden["defect_adayi"] = defect
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(golden, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"yazıldı: {target.relative_to(RULES)} ({len(steps)} adım)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mcp", required=True)
    ap.add_argument("--app", required=True)
    ap.add_argument(
        "--api", default="", help="test API kökü (boşsa herkese açık API ile sıfırlama)"
    )
    ap.add_argument("--token", default="")
    ap.add_argument("--mcp-version", default="0.0.83")
    ap.add_argument("--only", action="append", default=[])
    args = ap.parse_args()
    golden_dir = REPLAY / "verify_and_map" / "golden"
    jobs: list[tuple[str, int, dict[str, Any], Path, str]] = []
    for jira in ("TPD-1", "TPD-4"):
        cases = json.loads(
            (REPLAY / "case_generation" / "golden" / f"{jira}.json").read_text(encoding="utf-8")
        )["output"]["cases"]
        for n, case in enumerate(cases, start=1):
            jobs.append((jira, n, case, golden_dir / f"{jira}-C{n}.json", jira))
    variant = REPLAY / "case_generation" / "golden" / SCENARIO_F2 / "TPD-1.json"
    if variant.is_file():
        base = json.loads((REPLAY / "case_generation" / "golden" / "TPD-1.json").read_text())
        base_cases = base["output"]["cases"]
        for n, case in enumerate(json.loads(variant.read_text())["output"]["cases"], start=1):
            if n <= len(base_cases) and case == base_cases[n - 1]:
                continue  # aynı case: ana golden eşleşir
            jobs.append(
                (
                    "TPD-1",
                    n,
                    case,
                    golden_dir / SCENARIO_F2 / f"TPD-1-C{n}.json",
                    f"{SCENARIO_F2}/TPD-1",
                )
            )
    for jira, n, case, target, source in jobs:
        name = target.relative_to(golden_dir).with_suffix("").as_posix()
        if args.only and name not in args.only:
            continue
        record_case(
            jira=jira,
            sira=n,
            case=case,
            target=target,
            case_source=source,
            args=args,
            mcp_version=args.mcp_version,
        )


if __name__ == "__main__":
    main()
