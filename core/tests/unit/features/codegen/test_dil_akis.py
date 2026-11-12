"""011 üretim dili — uçtan uca REPLAY akışları (Ş1 core-akış; inceleme turu 1 MİM-O7, K-T4).

Şablonlar **gerçektir** (`render.render_dil`; Ş2 şablonları), sembol tablosu gerçek e2e-java
tablosudur (`symbols-java-web.json` = `java-araclar symbols --root demo-app/e2e-java`):

- Web + Java: `POST /code/generate {dil: "java"}` → web ajanı (`verify_and_map`, Playwright MCP;
  REPLAY anahtarı dilden bağımsız) → e2e-java sembol tablosu (`/symbols {lang: java, platform:
  web}`) → `goto` → `goTo` normalizasyonu → `check_mapping` → gerçek Playwright for Java şablonu
  (çıktı golden `TPD1WebC2_3f9b1c2eTest.java` ile aynı gövde) → `<e2e-java>/…/uretilen/` → sahte
  toolchain `/check {lang: java, platform: web}` (3 tekrar) → PR.
- Doğrulanmamış dil (csharp, python): ajan yine tarayıcıda doğrular, referans tablo TS'dir
  (repoda yalnız e2e-java varsa Java; başlık bunu söyler); render edilen kaynak
  `script_codegen.kaynak_kod`'a yazılır, commit/PR/yerel kontrol yoktur, durum `unverified`; yol
  üretimden önce ve sonra aynıdır (K-T6); yeniden üretim aynı kaydı `pending`'e alır.
- K-T4: doğrulanmamış üretim tam hat script'inin açık PR'ına / merge'üne dokunmaz; başka dilde merge
  edilmiş script varken tam hat isteği 409.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tests.unit.features.cases.helpers import run_jobs
from tests.unit.features.codegen.conftest import REPO, git
from tp_core.features.codegen import dil_algila, render, views
from tp_core.models import AiCall, AuditEvent, Script, StepMapping, session_scope
from tp_core.models.codegen_feature import ScriptCodegen

HERE = Path(__file__).resolve().parent
JAVA_KOK = "src/test/java/com/antreklabs/bayi"
BAYILER = REPO / "demo-app/e2e-app/src/test/java/com/antreklabs/bayi/altyapi/Bayiler.java"
GOLDEN_JAVA = HERE / "golden" / "TPD1WebC2_3f9b1c2eTest.java"


def java_web_tablosu() -> dict[str, Any]:
    """Gerçek e2e-java sembol tablosu (toolchain `/symbols {lang: java, platform: web}` yanıtı)."""
    return {**json.loads((HERE / "symbols-java-web.json").read_text("utf-8")), "lang": "java"}


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


def senaryo_govdesi(kaynak: str) -> list[str]:
    """Java testinin `senaryo()` gövdesi (başlık/sınıf adı case kimliğine göre değişir)."""
    satirlar = kaynak.splitlines()
    bas = satirlar.index("  public void senaryo() {")
    return satirlar[bas : satirlar.index("  }", bas) + 1]


@pytest.fixture
def dil_codegen(codegen: Any) -> Any:
    dil_algila.onbellegi_temizle()
    tc = codegen.toolchain
    eski = tc.handler
    tablo = java_web_tablosu()

    def handler(request: httpx.Request) -> httpx.Response:
        govde = json.loads(request.content or b"{}")
        if request.url.path == "/symbols" and govde.get("lang") == "java":
            tc.istekler.append((request.url.path, govde))
            return httpx.Response(200, json={**tablo, "sha": govde["sha"]})
        if request.url.path == "/check" and govde.get("lang") == "java" and not tc.kontroller:
            tc.kontroller.append(java_web_gecti())
        return eski(request)

    tc.handler = handler
    yield codegen
    dil_algila.onbellegi_temizle()


def depo_degistir(
    bare: Path, tmp_path: Path, *, e2e_java: bool = True, ts_sil: bool = False
) -> None:
    """Forge main'ine `e2e-java/` (pom + Bayiler + 12 elle yazılmış test) ekler; `ts_sil` →
    `e2e/package.json` silinir (repoda TS test projesi kalmaz). Algılama önbelleği temizlenir
    (dal → sha çözümü 60 sn önbellekli)."""
    work = tmp_path / f"depo-{uuid.uuid4().hex[:6]}"
    git("clone", "-q", str(bare), str(work))
    if e2e_java:
        kok = work / "e2e-java"
        (kok / JAVA_KOK / "altyapi").mkdir(parents=True)
        (kok / JAVA_KOK / "testler").mkdir(parents=True)
        (kok / "pom.xml").write_text("<project><artifactId>e2e-java</artifactId></project>\n")
        shutil.copy(BAYILER, kok / JAVA_KOK / "altyapi" / "Bayiler.java")
        for i in range(12):  # TS'den çok: algılama Java seçer
            (kok / JAVA_KOK / "testler" / f"Elle{i}Test.java").write_text("class X {}\n")
    if ts_sil:
        (work / "e2e" / "package.json").unlink()
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "depo", cwd=work)
    git("push", "-q", "origin", "main", cwd=work)
    dil_algila.onbellegi_temizle()


def test_web_java_case_den_pr_a(
    api: TestClient,
    engine: Engine,
    dil_codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
    tmp_path: Path,
) -> None:
    o = dil_codegen
    tc = o.toolchain
    depo_degistir(o.bare, tmp_path)

    diller = api.get("/code/languages").json()
    assert diller["algilanan"] == "java" and diller["kaynak"] == "algilandi"
    assert diller["sayilar"]["java"] == 12 and diller["neden"] is None
    assert {x["dil"]: x["kullanilabilir"] for x in diller["secenekler"]}["java"] is True

    cid = hazir["cases"][2]
    r = api.post("/code/generate", json={"case_ids": [str(cid)], "dil": "java"})
    assert r.status_code == 202, r.text
    yanit = r.json()
    assert yanit["dil"] == "java" and yanit["dil_kaynagi"] == "secildi"
    assert yanit["sonuclar"][0]["dil"] == "java" and "(Java)." in yanit["mesaj"]
    sid = uuid.UUID(yanit["script_ids"][0])
    with session_scope() as s:
        baslangic = s.get(Script, sid).dosya_yolu
    run_jobs(engine)

    with session_scope() as s:
        sc, cg = s.get(Script, sid), s.get(ScriptCodegen, sid)
        assert sc.durum == "pr_open", cg.engel_nedeni
        assert (sc.platform, sc.dil, sc.dil_kaynagi) == ("web", "java", "secildi")
        assert sc.branch == f"tp/case-{cid}"  # dal adı platformundur
        assert sc.dosya_yolu == baslangic
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
        # REPLAY'de ajana da denetim tablosu (Java) verilir; audit hangisinin verildiğini yazar.
        tablolar = s.scalars(
            select(AuditEvent).where(
                AuditEvent.eylem == "codegen.tablolar", AuditEvent.nesne == f"script:{sid}"
            )
        ).one()
        assert tablolar.ozet["ajan_tablosu"] == "java"
        assert tablolar.ozet["denetim_tablosu"] == "java"
        kod, dosya, head, pr_no = sc.icerik, sc.dosya_yolu, sc.head_sha, sc.pr_no
    # Gerçek şablon çıktısı: golden ile aynı gövde (başlık/sınıf adı case kimliğini taşır).
    assert senaryo_govdesi(kod) == senaryo_govdesi(GOLDEN_JAVA.read_text("utf-8"))
    assert "    loginPage().goTo();" in kod and '@Bayi("bayi1")' in kod
    assert "package com.antreklabs.bayi.uretilen;" in kod
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
    # MİM-B2: toolchain web + Java kaydını `local-ci-web-java` adıyla yazar (K-T1).
    assert [c["ad"] for c in detay["pr"]["checks"]] == ["local-ci-web-java"]
    assert detay["pr"]["checks"][0]["durum"] == "passed"
    with session_scope() as s:
        sc = s.get(Script, sid)
        zorunlu, ek = views.yerel_zorunlu_checkler(
            views.read_checks(head), views.pr_degisen_yollari(sc), sc.platform, sc.dil
        )
        assert (zorunlu, ek) == (("local-ci-web-java",), None)
        assert views.merge_engelleri(sc, s.get(ScriptCodegen, sid)) == []
    assert [a["ad"] for a in detay["yerel_kontrol"]["adimlar"]] == ["deps", "guard", "compile"]
    assert all(a["durum"] == "passed" for a in detay["yerel_kontrol"]["adimlar"])

    # Aynı dil + aynı onaylı içerik: yeniden üretilmez.
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

    # Başka tam hat dili (ts) istemek açık PR'ı kapatıp yeniden üretir (merge edilmemiş).
    ts = api.post("/code/generate", json={"case_ids": [str(cid)], "dil": "ts"}).json()
    assert ts["durum"] == "started" and ts["dil"] == "ts"
    with session_scope() as s:
        assert s.get(Script, sid).durum == "closed"

    # Merge kapısının kendisi (LocalForge): head'de yalnız `local-ci-web-java` kaydı var ve
    # yeşil → e2e-java/ değiştiren PR merge edilir (kapı `local-ci`'ı beklemez).
    assert [c.name for c in o.forge.checks(head)] == ["local-ci-web-java"]
    assert o.forge.merge_pr(pr_no, "muhendis", expected_head_sha=head)


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
        baslangic = sc.dosya_yolu
    run_jobs(engine)

    with session_scope() as s:
        sc, cg = s.get(Script, sid), s.get(ScriptCodegen, sid)
        assert sc.durum == "unverified", cg.engel_nedeni
        assert sc.icerik is None and sc.pr_no is None and sc.head_sha is None
        # K-T6: başlangıç yolu = render yolu = <e2e-csharp>/<alt yol>.
        assert sc.branch is None and sc.dosya_yolu == baslangic
        assert sc.dosya_yolu == render.dogrulanmamis_repo_path("csharp", "TPD-1", 2, cid)
        assert sc.dosya_yolu.startswith("e2e-csharp/tests/Generated/")
        # Gerçek şablon; referans tablo TS (MİM-O1: başlık tablonun dilini söyler).
        assert "TypeScript tablosundan" in cg.kaynak_kod
        assert "LoginPage" in cg.kaynak_kod and "P-001" in cg.kaynak_kod
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
    assert detay["kod"] == render_kaynak(sid)
    assert detay["pr"] is None and detay["merge_engelleri"] == []

    # Başka doğrulanmamış dilde yeniden üretim: aynı kayıt unverified → pending → unverified.
    r = api.post("/code/generate", json={"case_ids": [str(cid)], "dil": "python"}).json()
    assert r["script_ids"] == [str(sid)]
    run_jobs(engine)
    with session_scope() as s:
        sc, cg = s.get(Script, sid), s.get(ScriptCodegen, sid)
        assert (sc.durum, sc.dil) == ("unverified", "python")
        assert "TypeScript tablosundan" in cg.kaynak_kod
        assert sc.dosya_yolu == render.dogrulanmamis_repo_path("python", "TPD-1", 2, cid)
        assert sc.dosya_yolu.startswith("e2e-python/tests/generated/test_")

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


def render_kaynak(sid: uuid.UUID) -> str:
    with session_scope() as s:
        return s.get(ScriptCodegen, sid).kaynak_kod


def test_dogrulanmamis_uretim_tam_hat_scriptine_dokunmaz_ve_merge_cakismasi_409(
    api: TestClient,
    engine: Engine,
    dil_codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
    tmp_path: Path,
) -> None:
    """MİM-Y1 / K-T4 regresyonu: (A) açık TS PR'ı varken C# üretimi TS script'ini ve PR'ını
    kapatmaz; (B) TS merge edilmişken Java isteği 409 (repoda aynı case iki kez olmaz), C# ise
    yine üretilir ve merge edilmiş script'e dokunmaz."""
    o = dil_codegen
    cid = hazir["cases"][2]
    r = api.post("/code/generate", json={"case_ids": [str(cid)], "dil": "ts"}).json()
    ts_sid = uuid.UUID(r["script_ids"][0])
    run_jobs(engine)
    with session_scope() as s:
        ts = s.get(Script, ts_sid)
        assert ts.durum == "pr_open", s.get(ScriptCodegen, ts_sid).engel_nedeni
        pr_no = ts.pr_no

    # (A) Açık TS PR'ı varken doğrulanmamış üretim: yeni kayıt, TS'e ve PR'a dokunulmaz.
    r = api.post("/code/generate", json={"case_ids": [str(cid)], "dil": "csharp"})
    assert r.status_code == 202, r.text
    cs_sid = uuid.UUID(r.json()["script_ids"][0])
    assert cs_sid != ts_sid
    with session_scope() as s:
        assert s.get(Script, ts_sid).durum == "pr_open"
    run_jobs(engine)
    with session_scope() as s:
        assert s.get(Script, ts_sid).durum == "pr_open"
        assert s.get(Script, cs_sid).durum == "unverified"
        assert not s.scalars(
            select(AuditEvent).where(AuditEvent.eylem == "codegen.pr_superseded")
        ).all()
    pr = o.forge.find_open_pr(f"tp/case-{cid}")
    assert pr is not None and pr.number == pr_no

    # (B) TS merge edildi (kayıt düzeyinde) + repoya e2e-java eklendi: Java isteği 409.
    with session_scope() as s:
        s.execute(text("UPDATE script SET durum = 'merged' WHERE id = :i"), {"i": ts_sid})
    depo_degistir(o.bare, tmp_path)
    r = api.post("/code/generate", json={"case_ids": [str(cid)], "dil": "java"})
    assert r.status_code == 409, r.text
    assert "TypeScript ile merge edildi" in r.text and "önce mevcut testi kaldırın" in r.text
    assert r.json().get("kod") in (None, "dil_cakismasi")
    assert "silen bir PR'ı merge edin, sonra yeniden üretin" in r.json()["detail"]
    # K-T12: toplu istekte çakışan case sessizce kaybolmaz; sayı ve neden yanıtta.
    diger = hazir["cases"][1]
    r = api.post("/code/generate", json={"case_ids": [str(cid), str(diger)], "dil": "java"})
    assert r.status_code == 202, r.text
    toplu = r.json()
    assert toplu["cakisma_sayisi"] == 1 and len(toplu["script_ids"]) == 1
    assert "1 case başka dilde merge edilmiş testi olduğu için üretilmedi" in toplu["mesaj"]
    (cakisan,) = [x for x in toplu["sonuclar"] if x["durum"] == "cakisma"]
    assert cakisan["case_id"] == str(cid) and "TypeScript ile merge edildi" in cakisan["neden"]
    with session_scope() as s:
        assert s.get(Script, ts_sid).durum == "merged"
        assert s.get(Script, cs_sid).durum == "unverified"
    # Doğrulanmamış dil repoya yazmaz: merge edilmiş TS varken de üretilir (eski unverified kayıt
    # yeniden kullanılır), TS'e dokunulmaz.
    r = api.post("/code/generate", json={"case_ids": [str(cid)], "dil": "python"})
    assert r.status_code == 202, r.text
    assert r.json()["script_ids"] == [str(cs_sid)]
    run_jobs(engine)
    with session_scope() as s:
        assert s.get(Script, ts_sid).durum == "merged"
        assert (s.get(Script, cs_sid).durum, s.get(Script, cs_sid).dil) == ("unverified", "python")


def test_yalniz_e2e_java_olan_repoda_referans_tablo_java(
    api: TestClient,
    engine: Engine,
    dil_codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
    tmp_path: Path,
) -> None:
    """MİM-O1: repoda TS projesi yokken doğrulanmamış çıktının başlığı ve adları Java referans
    tablosundandır; audit `referans_tablo` / `ajan_tablosu` aynı dili yazar."""
    o = dil_codegen
    depo_degistir(o.bare, tmp_path, ts_sil=True)
    cid = hazir["cases"][2]
    r = api.post("/code/generate", json={"case_ids": [str(cid)], "dil": "csharp"})
    assert r.status_code == 202, r.text
    sid = uuid.UUID(r.json()["script_ids"][0])
    run_jobs(engine)
    with session_scope() as s:
        sc, cg = s.get(Script, sid), s.get(ScriptCodegen, sid)
        assert sc.durum == "unverified", cg.engel_nedeni
        assert "Java tablosundan" in cg.kaynak_kod and "TypeScript tablosundan" not in cg.kaynak_kod
        ozetler = {
            e.eylem: e.ozet
            for e in s.scalars(select(AuditEvent).where(AuditEvent.nesne == f"script:{sid}")).all()
        }
    assert ozetler["codegen.unverified"]["referans_tablo"] == "java"
    assert ozetler["codegen.tablolar"]["ajan_tablosu"] == "java"
    main = o.forge.head_sha("main")
    assert [b for p, b in o.toolchain.istekler if p == "/symbols"] == [
        {"sha": main, "lang": "java", "platform": "web"}
    ]


@pytest.fixture
def muhendis(api: TestClient, make_user: Any) -> Any:
    from .conftest import login

    u = make_user("engineer")
    login(api, u)
    return u
