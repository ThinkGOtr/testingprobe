"""Faz 3 inceleme düzeltmeleri, 3. tur (codegen).

- "Update branch" PR dalındaki yabancı commit'i onaylı head'e taşımaz (Constitution I): dal head'i
  çekirdeğin ürettiği head değilse güncelleme reddedilir, merge kapısı kapanır; güncelleme
  sırasında dala yabancı değişiklik girerse de yakalanır.
- REPLAY etiketi ajan koşarken (ve kuyruktayken) de görünür: `uretim_modu` iş başlamadan yazılır.
- Hatalı parola case'i ajan bayisinde de hatalı kalır (yalnızca gerçek parola değiştirilir);
  TPD-4-C2 golden'ı tarayıcı katmanından geçince /giris'te kalır.
- Canlı kipte locator çapraz kontrolü modelin `element` metnine bağlı değildir: hedef ref'in
  canlı snapshot'taki rol/adı → kütüphane locator'ı; ref olmayan `target` reddedilir.
- Model turu sınırı araç bütçesinden büyüktür: 25 sıralı araç turu + `submit_result` geçer.
- Ajan bayisi kilidi süreçler arasıdır (bayi adına bağlı danışma kilidi).
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.unit.features.codegen.test_browser import SNAPSHOT, FakeSession
from tests.unit.features.codegen.test_checks import symbols
from tests.unit.features.codegen.test_flow import script_of, uret
from tests.unit.features.codegen.test_review_fixes2 import (
    _ci_yesil,
    _isi_isle,
    _merge_kuyruga,
    _pr_ac,
)
from tp_core.features.codegen import service
from tp_core.features.codegen.browser import (
    AgentBrowser,
    AgentConfig,
    LocatorHedefi,
    ToolOutput,
    ajan_bayisi_kilidi,
    locator_hedefi,
)
from tp_core.gateway import FINAL_TOOL, Gateway, load_schema
from tp_core.gateway.config import find_rules_dir, load_model_table
from tp_core.gateway.replay import golden_name
from tp_core.gateway.testing import FakeProvider, InMemoryCallRecorder, tool_response
from tp_core.models import Script, session_scope
from tp_core.ports import AgentStep, ModelMessage

from .conftest import login, run_jobs

RULES = find_rules_dir()


@pytest.fixture
def muhendis(api: TestClient, make_user: Any) -> Any:
    u = make_user("engineer")
    login(api, u)
    return u


# --------------------------------------------- update-branch: yabancı commit (Constitution I)


def _audit(eylem: str) -> list[dict[str, Any]]:
    with session_scope() as s:
        return [
            r.ozet
            for r in s.execute(
                text("SELECT ozet FROM audit_event WHERE eylem = :e ORDER BY id"), {"e": eylem}
            )
        ]


def test_dalda_yabanci_commit_varsa_update_branch_reddeder_ve_merge_kapali_kalir(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    a = _pr_ac(api, engine, hazir["cases"][2])
    # Forge'a yazabilen biri bot PR dalına commit atar (core'un üretmediği içerik).
    yabanci = codegen.forge.commit_files(
        a.branch, {a.dosya_yolu: a.icerik + "\n// foreign\n"}, "mallory foreign"
    )
    assert codegen.forge.get_pr(a.pr_no).head_sha == yabanci != a.head_sha

    r = api.post(f"/prs/{a.pr_no}/update-branch")
    assert r.status_code == 202, r.text
    run_jobs(engine)
    sc, cg = script_of(a.id)
    # Yabancı head onaylı head'e taşınmadı; kanıt/hash korunur, kapı kapalı.
    assert sc.head_sha == a.head_sha and sc.icerik_hash == a.icerik_hash
    assert cg.dal["yabanci"] is True and cg.dal["guncelleme"] == "failed"
    assert "yabancı commit" in cg.dal["neden"]
    (kayit,) = _audit("codegen.branch_foreign_commit")
    assert kayit["bulunan_head"] == yabanci and kayit["beklenen_head"] == a.head_sha
    assert not _audit("codegen.branch_updated")
    _ci_yesil(codegen, a.head_sha)
    _ci_yesil(codegen, yabanci)
    d = api.get(f"/scripts/{a.id}").json()
    assert any("yabancı" in e for e in d["merge_engelleri"])
    assert "// foreign" not in d["kod"]
    # Ne onaylı head ne yabancı head ile merge edilebilir; main'e yabancı içerik girmez.
    for head in (a.head_sha, yabanci):
        r = api.post(
            f"/prs/{a.pr_no}/merge",
            json={"icerik_hash": d["pr"]["icerik_hash"], "head_sha": head, "onay_notu": "kabul"},
        )
        assert r.status_code == 409, r.text
    assert a.dosya_yolu not in codegen.forge.list_files(ref="main")


def test_guncelleme_sirasinda_dala_giren_yabanci_degisiklik_yakalanir(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    a = _pr_ac(api, engine, hazir["cases"][2])
    b = _pr_ac(api, engine, hazir["cases"][1])
    assert _isi_isle(engine, _merge_kuyruga(a.id, muhendis))[0] == "done"
    gercek = codegen.forge.update_branch

    def yarisli(number: int, *args: Any, **kw: Any) -> str:
        # Ön kontrol ile forge güncellemesi arasında dala yabancı dosya girer (TOCTOU).
        codegen.forge.commit_files(b.branch, {"e2e/tests/yabanci.spec.ts": "// x\n"}, "foreign")
        return gercek(number)

    codegen.forge.update_branch = yarisli
    try:
        (is_,) = [
            j for j in _bekleyen(engine, service.UPDATE_JOB) if j.yuk["script_id"] == str(b.id)
        ]
        durum, hata = _isi_isle(engine, is_.id)
    finally:
        del codegen.forge.update_branch
    assert durum == "failed" and "yabancı değişiklik" in (hata or "")
    sc, cg = script_of(b.id)
    assert sc.head_sha == b.head_sha and cg.dal["yabanci"] is True
    assert any("yabancı" in e for e in api.get(f"/scripts/{b.id}").json()["merge_engelleri"])


def _bekleyen(engine: Engine, tur: str) -> list[Any]:
    with engine.begin() as c:
        return list(
            c.execute(
                text("SELECT id, yuk FROM job WHERE tur = :t AND durum IN ('queued', 'retry')"),
                {"t": tur},
            )
        )


def test_guncelleme_icerigi_dogrulama_birim() -> None:
    class F:
        def __init__(self, agaclar: dict[str, dict[str, str]]) -> None:
            self.agaclar = agaclar

        def list_files(self, prefix: str = "", ref: str = "main") -> list[str]:
            return sorted(self.agaclar[ref])

        def read_file(self, path: str, ref: str = "main") -> str:
            return self.agaclar[ref][path]

    eski = {"a.ts": "1", "spec.ts": "S"}
    main = {"a.ts": "2", "b.ts": "B"}
    f = F({"eski": eski, "main": main, "iyi": {"a.ts": "2", "b.ts": "B", "spec.ts": "S"}})
    assert service._guncelleme_icerigi_dogrula(f, "eski", "iyi", "main", "spec.ts") is None
    f.agaclar["kotu1"] = {**f.agaclar["iyi"], "spec.ts": "S // foreign"}
    f.agaclar["kotu2"] = {**f.agaclar["iyi"], "c.ts": "?"}
    f.agaclar["kotu3"] = {**f.agaclar["iyi"], "a.ts": "3"}
    for ref, parca in (("kotu1", "spec.ts"), ("kotu2", "c.ts"), ("kotu3", "a.ts")):
        neden = service._guncelleme_icerigi_dogrula(f, "eski", ref, "main", "spec.ts")
        assert neden and parca in neden


def test_forge_expected_head_destekliyorsa_onayli_head_iletilir() -> None:
    gelen: dict[str, Any] = {}

    def yeni(number: int, actor: str = "tp-bot", *, expected_head_sha: str | None = None) -> str:
        gelen.update(number=number, expected=expected_head_sha)
        return "f" * 40

    def eski(number: int, actor: str = "tp-bot") -> str:
        return "e" * 40

    assert service._forge_dal_guncelle(yeni, 7, "a" * 40) == "f" * 40
    assert gelen == {"number": 7, "expected": "a" * 40}
    assert service._forge_dal_guncelle(eski, 7, "a" * 40) == "e" * 40


# ----------------------------------------------------- REPLAY etiketi ajan koşarken de var


def test_replay_etiketi_kuyrukta_ve_ajan_kosarken_gorunur(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    sid = uret(api, [hazir["cases"][2]])["script_ids"][0]
    d = api.get(f"/scripts/{sid}").json()
    assert d["durum"] in ("pending", "verifying") and d["mode"] == "replay"
    assert any(u.startswith("REPLAY kipi") for u in d["uyarilar"])
    assert next(x for x in api.get("/scripts").json() if x["id"] == str(sid))["mode"] == "replay"
    gorulen: list[str | None] = []
    fabrika = service._factories["browser"]

    def browser() -> FakeSession:
        # Tarayıcı oturumu ajan döngüsü başlarken açılır: o an etiket yazılı olmalı.
        with session_scope() as s:
            gorulen.append(s.get(Script, uuid.UUID(str(sid))).uretim_modu)
        return fabrika()

    service._factories["browser"] = browser
    run_jobs(engine)
    assert gorulen and all(m == "replay" for m in gorulen)
    sc, cg = script_of(sid)
    assert sc.uretim_modu == cg.uretim_modu == "replay"


def test_beklenen_uretim_modu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_MODEL_MODE", "replay")
    assert service.beklenen_uretim_modu() == "replay"
    monkeypatch.setenv("TP_MODEL_MODE", "live")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert service.beklenen_uretim_modu() == "live"
    assert service._gateway_modu(type("G", (), {"mode": "record"})()) == "live"
    assert service._gateway_modu(type("G", (), {"mode": "replay"})()) == "replay"


# ---------------------------------------------------------- hatalı parola ajan bayisinde


def test_hatali_parola_ajan_bayisinde_de_hatali_kalir() -> None:
    cfg = AgentConfig(agent_dealer="bayi3", agent_password="Ajan!Parola9")
    for kullanici in ("bayi1", "bayi3"):
        agent = AgentBrowser(
            FakeSession(), config=cfg, case_dealers=["bayi1"], case_passwords=["Demo123!"]
        )
        assert (
            agent._hazirla("browser_type", {"element": "Kullanıcı adı", "text": kullanici})["text"]
            == "bayi3"
        )
        out = agent._hazirla("browser_type", {"element": "Parola", "text": "Yanlis123!"})
        assert out["text"] == "Yanlis123!"
        # Gerçek parola (fikstür ya da demo tohumu) ajanınkiyle değişir.
        out = agent._hazirla("browser_type", {"element": "Parola", "text": "Demo123!"})
        assert out["text"] == "Ajan!Parola9"


class GirisSayfasi(FakeSession):
    """Giriş davranışı olan sahte MCP: yalnızca bayi3 / Demo123! girişi kataloğa geçer."""

    SAYFA = (
        "### Page\n- Page URL: http://demo-app-web:8080{url}\n### Snapshot\n```yaml\n"
        '- heading "Bayi girişi" [level=1] [ref=e1]\n'
        '- textbox "Kullanıcı adı" [ref=e7]\n'
        '- textbox "Parola" [ref=e8]\n'
        '- button "Giriş yap" [ref=e9]\n'
        "{alert}```\n"
    )
    TESTID: ClassVar[dict[str, str]] = {
        "e7": "login-username",
        "e8": "login-password",
        "e9": "login-submit",
    }

    def __init__(self) -> None:
        super().__init__()
        self.url = "/giris"
        self.alanlar: dict[str, str] = {}

    def call(self, name: str, args: Mapping[str, Any]) -> ToolOutput:
        if name == "browser_take_screenshot":
            return super().call(name, args)
        self.calls.append((name, dict(args)))
        hedef = str(args.get("target") or "")
        if name == "browser_type":
            self.alanlar[hedef] = str(args.get("text"))
        if name == "browser_click" and "login-submit" in hedef:
            ok = (
                self.alanlar.get('[data-testid="login-username"]') == "bayi3"
                and self.alanlar.get('[data-testid="login-password"]') == "Demo123!"
            )
            self.url = "/katalog" if ok else "/giris"
        if name == "browser_generate_locator":
            return ToolOutput(f"### Result\ngetByTestId('{self.TESTID.get(hedef, '?')}')\n")
        if name in ("browser_snapshot", "browser_navigate"):
            alert = (
                "- alert [ref=e10]: Kullanıcı adı veya parola hatalı\n"
                if self.url == "/giris" and self.alanlar
                else ""
            )
            return ToolOutput(self.SAYFA.format(url=self.url, alert=alert))
        return ToolOutput(
            "### Ran Playwright code\n```js\n// eylem\n```\n"
            f"### Page\n- Page URL: http://demo-app-web:8080{self.url}\n"
        )


def _replay_gateway() -> Gateway:
    return Gateway(
        provider=None,
        recorder=InMemoryCallRecorder(),
        mode="replay",
        models=load_model_table(RULES),
        rules_dir=RULES,
    )


def _golden_mesajlari(story: str, sira: int) -> list[ModelMessage]:
    from tp_core.gateway.demo_check import case_message
    from tp_core.gateway.replay_check import _case_of

    golden = json.loads(
        (RULES / "replay" / "verify_and_map" / "golden" / f"{story}-C{sira}.json").read_text(
            "utf-8"
        )
    )
    return [
        ModelMessage.model_validate(m) for m in case_message(story, sira, _case_of(RULES, golden))
    ]


def test_tpd4_c2_hatali_parola_golden_replay_giris_sayfasinda_kalir() -> None:
    page = GirisSayfasi()
    agent = AgentBrowser(
        page,
        config=AgentConfig(agent_dealer="bayi3", agent_password="Demo123!"),
        case_dealers=["bayi1", "bayi2"],
        case_passwords=["Demo123!"],
    )
    sonuclar: list[tuple[AgentStep, Any, LocatorHedefi | None]] = []

    def on_step(step: AgentStep) -> None:
        sonuclar.append((step, agent.pop_sonuc(), agent.pop_locator_hedefi()))

    gw = _replay_gateway()
    out = gw.run_agent(
        "verify_and_map",
        "verify-and-map",
        _golden_mesajlari("TPD-4", 2),
        agent.tool_specs(),
        agent,
        load_schema(RULES, "verify_and_map"),
        replay_key={"name": golden_name("TPD-4", case_no=2), "jira_key": "TPD-4"},
        on_step=on_step,
    )
    assert out.mode == "replay"
    yazilan = [a["text"] for n, a in page.calls if n == "browser_type"]
    assert yazilan == ["bayi3", "Yanlis123!"]
    tik = [s for st, s, _ in sonuclar if st.tool == "browser_click"]
    assert tik and tik[-1].ok and tik[-1].url and tik[-1].url.endswith("/giris")
    assert page.url == "/giris"
    # Hedefler snapshot'tan çözüldü: canlı kipte de anahtar ipucusuz kontrol edilebilir.
    hedefler = [h for st, _, h in sonuclar if st.tool == "browser_generate_locator"]
    assert [(h.rol, h.ad) for h in hedefler if h] == [
        ("textbox", "Kullanıcı adı"),
        ("textbox", "Parola"),
        ("button", "Giriş yap"),
    ]


# ------------------------------------------- canlı kip: element ipucusuz locator kontrolü


def _canli_snapshot_hedefi(element_satiri: str) -> LocatorHedefi:
    satirlar = SNAPSHOT.split("```yaml\n")[1].split("```")[0].splitlines()
    ref = re.search(r"\[ref=(e\d+)\]", element_satiri)
    assert ref is not None
    return locator_hedefi(satirlar, ref.group(1))


def test_locator_hedefi_snapshottan_rol_ad_ve_urun_kodu() -> None:
    h = _canli_snapshot_hedefi('button "Giriş yap" [ref=e20]')
    assert (h.ref_gecerli, h.rol, h.ad, h.kod) == (True, "button", "Giriş yap", None)
    h = _canli_snapshot_hedefi('button "Sepete ekle" [ref=e53]')  # P-002 kartı
    assert (h.rol, h.ad, h.kod) == ("button", "Sepete ekle", "P-002")
    h = locator_hedefi(["- button [ref=e1]"], '[data-testid="login-submit"]')
    assert h.ref_gecerli is False


def test_canli_kipte_ipucusuz_yanlis_testid_yakalanir() -> None:
    t = symbols()
    f = service.locator_capraz_kontrol
    giris = _canli_snapshot_hedefi('button "Giriş yap" [ref=e20]')
    p1 = _canli_snapshot_hedefi('button "Sepete ekle" [ref=e43]')
    sepet = _canli_snapshot_hedefi('link "Sepet 6 ürün" [ref=e33]')
    iyi = [
        (1, "Giriş yap butonu", "getByTestId('login-submit')", giris),
        (2, "Sepete ekle", "getByTestId('product-card-P-001').getByTestId('add-to-cart')", p1),
        (3, "Sepet bağlantısı", "getByTestId('nav-cart')", sepet),
    ]
    assert f(iyi, t, canli=True) == []
    kotu = [
        # Giriş butonu için parola alanının testId'si (kütüphanede var; eskiden geçiyordu).
        (1, "Giriş yap butonu", "getByTestId('login-password')", giris),
        # P-001 adımı için P-002 kartı.
        (2, "Sepete ekle", "getByTestId('product-card-P-002').getByTestId('add-to-cart')", p1),
        # target seçici (ref değil).
        (3, "Giriş", "getByTestId('login-submit')", LocatorHedefi("#submit", False)),
        # ref çözülemedi, ipucu yok: canlı kipte eşlenemez.
        (4, "bir şey", "getByTestId('nav-cart')", LocatorHedefi("e999", True)),
        (5, "ipucusuz", "getByTestId('nav-cart')", None),
    ]
    sonuc = f(kotu, t, canli=True)
    assert [n for n, _ in sonuc] == [1, 2, 3, 4, 5]
    assert "login-password" in sonuc[0][1] and "P-001" in sonuc[1][1]
    # REPLAY'de (golden'lar ipucu taşır) eski davranış: ipucusuz bilinen testId geçer.
    assert f([(5, "ipucusuz", "getByTestId('nav-cart')", None)], t) == []


# ----------------------------------------------- tur sınırı > araç bütçesi (25 + submit)


def test_25_sirali_arac_turu_sonra_submit_gecer() -> None:
    golden = json.loads(
        (RULES / "replay" / "verify_and_map" / "golden" / "TPD-4-C2.json").read_text("utf-8")
    )
    cfg = AgentConfig()
    assert service.max_turns(cfg.max_tool_calls) > cfg.max_tool_calls
    script = [tool_response(("browser_snapshot", {}))] * cfg.max_tool_calls + [
        tool_response((FINAL_TOOL, golden["output"]))
    ]
    gw = Gateway(
        provider=FakeProvider(script),
        recorder=InMemoryCallRecorder(),
        mode="live",
        models=load_model_table(RULES),
        rules_dir=RULES,
    )
    agent = AgentBrowser(FakeSession(), config=cfg)
    out = gw.run_agent(
        "verify_and_map",
        "verify-and-map",
        [ModelMessage(role="user", content="Case: S1 giriş")],
        agent.tool_specs(),
        agent,
        load_schema(RULES, "verify_and_map"),
        replay_key={"name": "TPD-4-case-2", "jira_key": "TPD-4", "case_no": 2},
        max_turns=service.max_turns(cfg.max_tool_calls),
    )
    assert out.output == golden["output"] and agent.calls == cfg.max_tool_calls


# ----------------------------------------------------- ajan bayisi kilidi (süreçler arası)


def test_ajan_bayisi_kilidi_baska_baglantiyi_bekletir(engine: Engine) -> None:
    olaylar: list[str] = []
    girdi = threading.Event()

    def ikinci() -> None:
        girdi.wait(5)
        with ajan_bayisi_kilidi(engine, "bayi3"):
            olaylar.append("ikinci")

    t = threading.Thread(target=ikinci)
    with ajan_bayisi_kilidi(engine, "bayi3"):
        t.start()
        girdi.set()
        time.sleep(0.4)
        olaylar.append("birinci-bitti")
        # Başka bayinin kilidi bağımsızdır.
        with ajan_bayisi_kilidi(engine, "bayi4"):
            pass
    t.join(5)
    assert olaylar == ["birinci-bitti", "ikinci"]


def test_ajan_bayisi_kilidi_kod_uretimiyle_ayni_anahtar(engine: Engine) -> None:
    """`replay_check` `ajan_bayisi_kilidi()` alırsa kod üretiminin `ajan_kilidi`yle çakışır."""
    with service.ajan_kilidi(engine), engine.connect() as c:
        alindi = c.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": "agent-dealer:bayi3"}
        ).scalar_one()
        assert alindi is False
