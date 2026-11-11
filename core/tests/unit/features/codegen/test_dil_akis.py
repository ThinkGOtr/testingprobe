"""011 üretim dili — uçtan uca REPLAY akışları (Ş1 core-akış).

- Web + Java: `POST /code/generate {dil: "java"}` → web ajanı (`verify_and_map`, Playwright MCP;
  REPLAY anahtarı dilden bağımsız) → e2e-java sembol tablosu (`/symbols {lang: java, platform:
  web}`) → `goto` → `goTo` normalizasyonu → şablon (`render_dil`) → `<e2e-java>/…/uretilen/` →
  `/check {lang: java, platform: web}` (3 tekrar) → PR (`local-ci`).
- Doğrulanmamış dil (csharp, python): ajan yine tarayıcıda doğrular, referans tablo TS'dir;
  render edilen kaynak `script_codegen.kaynak_kod`'a yazılır, commit/PR/yerel kontrol yoktur,
  durum `unverified`; yeniden üretim aynı kaydı `pending`'e alır.

Web Java / C# / Python şablonları Ş2'nindir: bu testler `render.render_dil`'i sahte ile değiştirir
(ts yolu gerçek şablondur).
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tests.unit.features.cases.helpers import run_jobs
from tests.unit.features.codegen.conftest import REPO, git
from tests.unit.features.codegen.test_dil import java_web_tablosu
from tp_core.features.codegen import dil_algila
from tp_core.features.codegen import render as render_modulu
from tp_core.features.codegen.render import (
    Rendered,
    RenderInput,
    java_class_name,
    java_literal,
    mapping_hash,
)
from tp_core.models import AiCall, AuditEvent, Script, StepMapping, session_scope
from tp_core.models.codegen_feature import ScriptCodegen

JAVA_KOK = "src/test/java/com/antreklabs/bayi"
BAYILER = REPO / "demo-app/e2e-app/src/test/java/com/antreklabs/bayi/altyapi/Bayiler.java"


def java_web_gecti(n: int = 3) -> dict[str, Any]:
    return {
        "conclusion": "success",
        "summary": "Yerel CI geçti (Java web)",
        "lang": "java",
        "platform": "web",
        "app": {"ok": True},
        "deps": {"ok": True},
        "guard": {"ok": True},
        "compile": {"ok": True},
        "run": {
            "run_id": f"run-{uuid.uuid4().hex[:6]}",
            "status": "passed",
            "saglik": {"ok": True},
            "tests": [{"title": "senaryo", "status": "expected", "error": None}] * n,
        },
        "duration_ms": 2345,
    }


def sahte_render_dil(gercek: Any) -> Any:
    """Ş2'nin `render_dil`'i yerine: ts gerçek şablon; web Java / C# / Python deterministik metin
    (eşlemedeki çağrılar satır satır, Java satırı `_JAVA_CAGRI_SATIRI` biçiminde)."""

    def render_dil(inp: RenderInput, *, dil: str, platform: str, rules: Path) -> Rendered:
        if dil == "ts":
            return gercek(inp, dil=dil, platform=platform, rules=rules)
        cagrilar = [*(inp.mapping.get("step_mapping") or []), *(inp.mapping.get("expects") or [])]
        if dil == "java":
            sinif = java_class_name(inp.story_key, platform, inp.sira_no, inp.case_id)
            test_file = f"{JAVA_KOK}/uretilen/{sinif}.java"
            satirlar = [
                f"        {c['po'][:1].lower()}{c['po'][1:]}().{c['method']}("
                + ", ".join(java_literal(a) for a in c.get("args") or [])
                + ");"
                for c in cagrilar
            ]
        elif dil == "csharp":
            test_file = "Uretilen/SahteTests.cs"
            satirlar = [f"        await {c['po']}.{c['method']}Async();" for c in cagrilar]
        else:
            test_file = "tests/uretilen/test_sahte.py"
            satirlar = [f"    {c['po'].lower()}.{c['method']}()" for c in cagrilar]
        icerik = f"// AI-generated ({dil}, {platform})\n" + "\n".join(satirlar) + "\n"
        return Rendered(
            content=icerik,
            repo_path=f"{inp.e2e_root.strip('/')}/{test_file}",
            test_file=test_file,
            template_hash="t" * 64,
            mapping_hash=mapping_hash(inp.mapping),
            dealer="bayi1",
        )

    return render_dil


@pytest.fixture
def dil_codegen(codegen: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(render_modulu, "render_dil", sahte_render_dil(render_modulu.render_dil))
    dil_algila.onbellegi_temizle()
    yield codegen
    dil_algila.onbellegi_temizle()


def e2e_java_ekle(bare: Path, tmp_path: Path) -> None:
    """Forge main'ine `e2e-java/` (pom + Bayiler + elle yazılmış testler) ekler."""
    work = tmp_path / "e2e-java-ekle"
    git("clone", "-q", str(bare), str(work))
    kok = work / "e2e-java"
    (kok / JAVA_KOK / "altyapi").mkdir(parents=True)
    (kok / JAVA_KOK / "testler").mkdir(parents=True)
    (kok / "pom.xml").write_text("<project><artifactId>e2e-java</artifactId></project>\n")
    shutil.copy(BAYILER, kok / JAVA_KOK / "altyapi" / "Bayiler.java")
    for i in range(12):  # TS'den çok: algılama Java seçer
        (kok / JAVA_KOK / "testler" / f"Elle{i}Test.java").write_text("class X {}\n")
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "e2e-java", cwd=work)
    git("push", "-q", "origin", "main", cwd=work)


def test_web_java_case_den_pr_a(
    api: TestClient,
    engine: Engine,
    dil_codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
    tmp_path: Path,
) -> None:
    o = dil_codegen
    e2e_java_ekle(o.bare, tmp_path)
    tablo = java_web_tablosu()
    tc = o.toolchain
    eski = tc.handler

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        govde = json.loads(request.content or b"{}")
        if request.url.path == "/symbols" and govde.get("lang") == "java":
            tc.istekler.append((request.url.path, govde))
            return httpx.Response(200, json={"sha": govde["sha"], **tablo})
        if request.url.path == "/check" and govde.get("lang") == "java" and not tc.kontroller:
            tc.kontroller.append(java_web_gecti())
        return eski(request)

    tc.handler = handler

    diller = api.get("/code/languages").json()
    assert diller["algilanan"] == "java" and diller["kaynak"] == "algilandi"
    assert diller["sayilar"]["java"] == 12
    assert {x["dil"]: x["kullanilabilir"] for x in diller["secenekler"]}["java"] is True

    cid = hazir["cases"][2]
    r = api.post("/code/generate", json={"case_ids": [str(cid)], "dil": "java"})
    assert r.status_code == 202, r.text
    yanit = r.json()
    assert yanit["dil"] == "java" and yanit["dil_kaynagi"] == "secildi"
    assert yanit["sonuclar"][0]["dil"] == "java" and "(Java)." in yanit["mesaj"]
    sid = uuid.UUID(yanit["script_ids"][0])
    run_jobs(engine)

    with session_scope() as s:
        sc, cg = s.get(Script, sid), s.get(ScriptCodegen, sid)
        assert sc.durum == "pr_open", cg.engel_nedeni
        assert (sc.platform, sc.dil, sc.dil_kaynagi) == ("web", "java", "secildi")
        assert sc.branch == f"tp/case-{cid}"  # dal adı platformundur
        assert sc.dosya_yolu.startswith(f"e2e-java/{JAVA_KOK}/uretilen/TPD1WebC2_")
        assert cg.kaynak_kod is None and sc.pass_at_1 is True
        # Ajan web'dir: verify_and_map (Playwright MCP), REPLAY anahtarı web golden'ı.
        call = s.get(AiCall, uuid.UUID(cg.ai_call_ids[0]))
        assert call.amac == "verify_and_map" and call.mod == "replay"
        maps = s.scalars(
            select(StepMapping).where(StepMapping.script_id == sid).order_by(StepMapping.adim_no)
        ).all()
        # TS adlı golden (`goto`) Java adına normalize edildi; ham çıktı eşlemede kalır.
        assert (maps[0].po_sinifi, maps[0].po_metodu) == ("LoginPage", "goTo")
        assert cg.eslesme["step_mapping"][0]["method"] == "goto"
        kod, dosya, head, pr_no = sc.icerik, sc.dosya_yolu, sc.head_sha, sc.pr_no
    assert "loginPage().goTo();" in kod
    assert o.forge.read_file(dosya, ref=f"tp/case-{cid}") == kod
    assert len(o.oturumlar) == 1 and o.oturumlar[0].closed

    main = o.forge.head_sha("main")
    assert [b for p, b in tc.istekler if p == "/symbols"] == [
        {"sha": main, "lang": "java", "platform": "web"}
    ]
    (kontrol,) = tc.checks()
    assert (kontrol["lang"], kontrol["platform"], kontrol["sha"]) == ("java", "web", head)
    assert kontrol["repeat_each"] == 3
    assert kontrol["test_files"] == [dosya.removeprefix("e2e-java/")]

    pr = o.forge.find_open_pr(f"tp/case-{cid}")
    assert pr is not None and pr.number == pr_no
    assert "dil:java" in pr.labels and not any(x.startswith("platform:") for x in pr.labels)
    assert "· Java]" in pr.title
    assert "Model Java yazmadı" in pr.body and (
        "| Dil | Java (Playwright for Java + TestNG) |" in pr.body
    )
    assert "Playwright 3/3 geçti (repeat-each=3" in pr.body
    assert o.ci and o.ci[-1]["pr_number"] == pr_no

    detay = api.get(f"/scripts/{sid}").json()
    assert detay["dil"] == "java" and detay["dogrulanmamis"] is False
    assert detay["pr"]["checks"][0]["ad"] == "local-ci"
    assert [a["ad"] for a in detay["yerel_kontrol"]["adimlar"]] == ["deps", "guard", "compile"]
    assert all(a["durum"] == "passed" for a in detay["yerel_kontrol"]["adimlar"])

    # Aynı dil + aynı onaylı içerik: yeniden üretilmez; başka dil (ts) istemek yeniden üretir.
    tekrar = api.post("/code/generate", json={"case_ids": [str(cid)], "dil": "java"}).json()
    assert tekrar["sonuclar"][0]["durum"] == "pr_acik"

    # Kırarak doğrula: Java web gövdesi ve e2e-java'ya göre dosya.
    onceki = len(tc.checks())
    assert api.post(f"/scripts/{sid}/break-verify").status_code == 202
    tc.kontroller += [java_web_gecti(1), java_web_gecti(1)]
    kirik = java_web_gecti(1)
    kirik["conclusion"] = "failure"
    kirik["run"] = {**kirik["run"], "status": "failed", "tests": [{
        "title": "senaryo", "status": "unexpected",
        "error": "java.lang.AssertionError: toplam: beklenen <1>, görülen <0> (5000 ms)",
        "failure": {"type": "assertion"},
    }]}  # fmt: skip
    tc.kirik.append(kirik)
    run_jobs(engine)
    bv = tc.checks()[onceki:]
    assert len(bv) == 3 and all((b["lang"], b["platform"]) == ("java", "web") for b in bv)
    assert all(b["test_files"] == [dosya.removeprefix("e2e-java/")] for b in bv)
    with session_scope() as s:
        assert s.get(ScriptCodegen, sid).break_durum == "passed"

    ts = api.post("/code/generate", json={"case_ids": [str(cid)], "dil": "ts"}).json()
    assert ts["durum"] == "started" and ts["dil"] == "ts"
    with session_scope() as s:
        assert s.get(Script, sid).durum == "closed"


def test_dogrulanmamis_dil_unverified_ve_yeniden_uretim(
    api: TestClient, engine: Engine, dil_codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    o = dil_codegen
    cid = hazir["cases"][2]
    main_once = o.forge.head_sha("main")
    r = api.post("/code/generate", json={"case_ids": [str(cid)], "dil": "csharp"})
    assert r.status_code == 202, r.text
    assert "Doğrulanmamış dil" in r.json()["mesaj"]
    sid = uuid.UUID(r.json()["script_ids"][0])
    with session_scope() as s:
        sc = s.get(Script, sid)
        assert (sc.dil, sc.dil_kaynagi, sc.branch) == ("csharp", "secildi", None)
    run_jobs(engine)

    with session_scope() as s:
        sc, cg = s.get(Script, sid), s.get(ScriptCodegen, sid)
        assert sc.durum == "unverified", cg.engel_nedeni
        assert sc.icerik is None and sc.pr_no is None and sc.head_sha is None
        assert sc.branch is None and sc.dosya_yolu == "e2e-csharp/Uretilen/SahteTests.cs"
        assert cg.kaynak_kod.startswith("// AI-generated (csharp, web)")
        assert "LoginPage.gotoAsync();" in cg.kaynak_kod  # TS referans tablosu: ad aynen
        olay = s.scalars(
            select(AuditEvent).where(
                AuditEvent.eylem == "codegen.unverified", AuditEvent.nesne == f"script:{sid}"
            )
        ).one()
        assert olay.ozet["dil"] == "csharp" and olay.ozet["referans_tablo"] == "ts"
        assert len(s.scalars(select(StepMapping).where(StepMapping.script_id == sid)).all()) > 0
    # Ajan tarayıcıda doğruladı; referans tablo TS; forge'a hiçbir şey yazılmadı.
    assert len(o.oturumlar) == 1
    assert [b for p, b in o.toolchain.istekler if p == "/symbols"] == [{"sha": main_once}]
    assert o.toolchain.checks() == [] and o.ci == []
    assert o.forge.head_sha("main") == main_once
    assert o.forge.find_open_pr(f"tp/case-{cid}") is None

    detay = api.get(f"/scripts/{sid}").json()
    assert detay["dogrulanmamis"] is True and detay["durum"] == "unverified"
    assert detay["kod"].startswith("// AI-generated (csharp, web)")
    assert detay["pr"] is None and detay["merge_engelleri"] == []

    # Başka doğrulanmamış dilde yeniden üretim: aynı kayıt unverified → pending → unverified.
    r = api.post("/code/generate", json={"case_ids": [str(cid)], "dil": "python"}).json()
    assert r["script_ids"] == [str(sid)]
    run_jobs(engine)
    with session_scope() as s:
        sc, cg = s.get(Script, sid), s.get(ScriptCodegen, sid)
        assert (sc.durum, sc.dil) == ("unverified", "python")
        assert cg.kaynak_kod.startswith("// AI-generated (python, web)")
        assert sc.dosya_yolu == "e2e-python/tests/uretilen/test_sahte.py"

    # Tam hat diline geçiş: aynı kayıt tam akıştan geçer (commit → kontrol → PR).
    r = api.post("/code/generate", json={"case_ids": [str(cid)]}).json()
    assert r["dil"] == "ts" and r["dil_kaynagi"] == "algilandi"
    assert r["script_ids"] == [str(sid)]
    run_jobs(engine)
    with session_scope() as s:
        sc, cg = s.get(Script, sid), s.get(ScriptCodegen, sid)
        assert sc.durum == "pr_open", cg.engel_nedeni
        assert sc.dil == "ts" and cg.kaynak_kod is None and sc.dosya_yolu.endswith(".spec.ts")
    assert api.get(f"/scripts/{sid}").json()["dogrulanmamis"] is False


@pytest.fixture
def muhendis(api: TestClient, make_user: Any) -> Any:
    from .conftest import login

    u = make_user("engineer")
    login(api, u)
    return u
