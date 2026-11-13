"""CI'ın üretim dili boyutu (011 §2.8, Ş5): web + Java (Playwright for Java + TestNG) PR koşusu
`/check`'e `{lang: java, platform: web}` gönderir, Surefire raporu alınır, check adı
`local-ci-web-java`'dır (K-T1); paket koşuları (script'li push dahil, K-T2) repoda testi bulunan
her tam hat dili için ayrı koşar, script'siz PR değişen web test köklerinin dillerini koşar ve koşu
kaydı dili `run.ortam.dil`'de taşır. GitHub kipinde Java kardeşi yalnız `TP_WEB_DILLERI` Java'yı
içerirken açılır (K-T3). Web + TS ve uygulama davranışı değişmez (test_ci_platform)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import (
    SHA,
    UZAK_KOK,
    FakeForge,
    FakeToolchain,
    kosu_yaz,
    run_jobs,
)
from tests.unit.features.ci.test_ci_platform import JUNIT
from tp_core.features.ci import clients, dil, enqueue_ci, service, services
from tp_core.features.codegen import platform as p
from tp_core.models import Run, Script, TestResult
from tp_core.ports import PullRequest

pytestmark = pytest.mark.usefixtures("ci_env")

WEB_JAVA_DOSYA = "e2e-java/src/test/java/com/antreklabs/bayi/uretilen/TPD1Web2_0a1b2c3dTest.java"


@dataclass
class DilliForge(FakeForge):
    dosyalar: list[str] = field(default_factory=list)
    hata: bool = False
    # Script'siz PR'ın değiştirdiği yollar (None: fark okunamıyor).
    degisen: list[str] | None = None
    farklar: list[tuple[str, str]] = field(default_factory=list)

    def list_files(self, prefix: str, ref: str) -> list[str]:
        if self.hata:
            raise RuntimeError("forge yok")
        return [d for d in self.dosyalar if d.startswith(prefix)]

    def merge_base(self, a: str, b: str) -> str:
        return "c" * 40

    def changed_paths(self, base: str, head: str) -> list[str] | None:
        self.farklar.append((base, head))
        return self.degisen


def _web_script(engine: Engine, d: str) -> uuid.UUID:
    sid = uuid.uuid4()
    with Session(engine) as s, s.begin():
        s.add(Script(id=sid, tur="test", dosya_yolu=WEB_JAVA_DOSYA, platform="web", dil=d))
    return sid


def _checks_yaz(kok: Path, sha: str, ad: str, conclusion: str) -> None:
    """toolchain worker'ın kayıt biçimi: her ad yalnız kendi girdisini değiştirir."""
    (kok / "checks").mkdir(exist_ok=True)
    yol = kok / "checks" / f"{sha}.json"
    eski = json.loads(yol.read_text())["checks"] if yol.exists() else []
    girdi = {"name": ad, "status": "completed", "conclusion": conclusion}
    yol.write_text(json.dumps({"checks": [c for c in eski if c["name"] != ad] + [girdi]}))


def _web_java_yaniti(kok: Path, *, lang_yok: bool = False):
    def yanit(body: dict[str, Any]) -> httpx.Response:
        run_dir = body["run_id"]
        yerel = kok / "runs" / run_dir
        (yerel / "results").mkdir(parents=True)
        (yerel / "results" / "junit.xml").write_bytes(JUNIT)
        _checks_yaz(kok, body["sha"], "local-ci-web-java", "failure")
        uzak = f"{UZAK_KOK}/runs/{run_dir}"
        dil_alani = {} if lang_yok else {"lang": "java", "platform": "web"}
        return httpx.Response(
            200,
            json={
                "sha": body["sha"],
                **dil_alani,
                "check_name": "local-ci-web-java",
                "conclusion": "failure",
                "failed_steps": ["run"],
                "summary": "Yerel CI başarısız: run",
                "app": {"ok": True},
                "deps": {"ok": True},
                "guard": {"ok": True, "mode": "pr"},
                "compile": {"ok": True},
                "run": {
                    "run_id": run_dir,
                    **dil_alani,
                    "status": "failed",
                    "artifacts_dir": uzak,
                    "artifacts_rel": f"runs/{run_dir}",
                    "junit": f"{uzak}/results/junit.xml",
                    "json": None,
                    "html_dir": None,
                    "log": f"{uzak}/runner.log",
                    "saglik": {"ok": True},
                },
                "duration_ms": 20000,
            },
        )

    return yanit


# ------------------------------------------------------------------------------ PR koşusu


def test_web_java_pr_kosusu_check_govdesi_surefire_ve_local_ci_web_java(
    engine: Engine,
    toolchain: FakeToolchain,
    artefakt_kok: Path,
) -> None:
    sid = _web_script(engine, "java")
    toolchain.yanit = _web_java_yaniti(artefakt_kok)
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 7, script_id=sid)
    with Session(engine) as s:
        assert (s.get(Run, rid).ortam["platform"], s.get(Run, rid).ortam["dil"]) == ("web", "java")
    run_jobs(engine)
    body = toolchain.istekler[0]
    assert (body["lang"], body["platform"]) == ("java", "web")
    with Session(engine) as s:
        run = s.get(Run, rid)
        assert run.sonuc == "failed"
        assert (run.ortam["platform"], run.ortam["dil"], run.ortam["lang"]) == (
            "web",
            "java",
            "java",
        )
        a = run.artefaktlar
        assert set(a["adimlar"]) == {"app", "deps", "guard", "compile", "run"}
        # K-T1: web + Java koşusunun kontrolü `local-ci-web-java`.
        assert (a["checks"]["durum"], a["checks"]["conclusion"]) == ("completed", "failure")
        assert set(a["checks"]["platformlar"]) == {"local-ci-web-java"}
        assert a["raporlar"] == {"junit": True, "json": False}
        assert not any("results.json" in u for u in a["uyarilar"])
        k = service.serialize_runs(s, [run], artefakt=True)[0]
        assert (k["platform"], k["dil"]) == ("web", "java")
        satirlar = {
            r.test_adi: r for r in s.scalars(select(TestResult).where(TestResult.run_id == rid))
        }
    # Surefire kimliği: `src/test/java/<paket>/<Sınıf>.java` + `<Sınıf> › <metot>`.
    assert "TPD1AndroidC2_0a1b2c3dTest › senaryo" in satirlar


def test_web_java_raporu_dil_bildirmese_kosunun_dili_kullanilir(
    engine: Engine,
    toolchain: FakeToolchain,
    artefakt_kok: Path,
) -> None:
    sid = _web_script(engine, "java")
    toolchain.yanit = _web_java_yaniti(artefakt_kok, lang_yok=True)
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 8, script_id=sid)
    run_jobs(engine)
    with Session(engine) as s:
        run = s.get(Run, rid)
        assert run.ortam["dil"] == "java" and run.ortam["platform"] == "web"
        assert set(run.artefaktlar["adimlar"]) == {"app", "deps", "guard", "compile", "run"}


def test_web_ts_scripti_govdesi_ve_kaydi_degismez(engine: Engine, toolchain: FakeToolchain) -> None:
    sid = _web_script(engine, "ts")
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 9, script_id=sid)
    run_jobs(engine)
    assert all("lang" not in b and "platform" not in b for b in toolchain.istekler)
    with Session(engine) as s:
        run = s.get(Run, rid)
        assert run.ortam["dil"] == "ts" and "lang" not in run.ortam
        assert service.serialize_runs(s, [run], artefakt=True)[0]["dil"] == "ts"


def test_dogrulanmamis_dil_ci_ye_giremez(engine: Engine) -> None:
    sid = _web_script(engine, "csharp")
    with Session(engine) as s, s.begin(), pytest.raises(service.CiError, match="csharp"):
        enqueue_ci(s, SHA, "pr", 10, script_id=sid)


def test_ayni_committe_ts_ve_java_kosulari_birbirini_yutmaz(engine: Engine) -> None:
    java = _web_script(engine, "java")
    with Session(engine) as s, s.begin():
        ts1 = enqueue_ci(s, SHA, "pr", 11)
        j1 = enqueue_ci(s, SHA, "pr", 11, script_id=java)
        j2 = enqueue_ci(s, SHA, "pr", 11, script_id=java)
        ts2 = enqueue_ci(s, SHA, "pr", 11)
    assert ts1 != j1 and j1 == j2 and ts1 == ts2


# ------------------------------------------------------------------------- paket koşuları


def test_paket_kosusu_repodaki_her_tam_hat_dili_icin_kosar(
    engine: Engine, toolchain: FakeToolchain
) -> None:
    forge = DilliForge(
        dosyalar=[
            "e2e/tests/cart.spec.ts",
            "e2e-java/src/test/java/com/antreklabs/bayi/testler/SepetTesti.java",
            "e2e-java/src/test/java/com/antreklabs/bayi/birim/KimlikBirimTest.java",
        ]
    )
    with services.override(forge=lambda: forge):
        with Session(engine) as s, s.begin():
            rid = enqueue_ci(s, SHA, "push")
        with Session(engine) as s:
            assert "dil" not in s.get(Run, rid).ortam  # dil işte çözülür
        run_jobs(engine)
        with Session(engine) as s:
            kosular = list(s.scalars(select(Run).where(Run.tetik == "push", Run.commit == SHA)))
    diller = {r.ortam["dil"]: r for r in kosular}
    assert set(diller) == {"ts", "java"} and diller["ts"].id == rid
    assert diller["java"].ortam["kardes_kosu"] == str(rid)
    assert diller["java"].ortam["platform"] == "web" and diller["java"].script_id is None
    govdeler = sorted(f"{b.get('lang')}/{b.get('platform')}" for b in toolchain.istekler)
    assert govdeler == ["None/None", "java/web"]
    # İş yeniden koşsa da dağıtım tekrarlanmaz (dil yazılmış).
    with Session(engine) as s, s.begin():
        run = s.get(Run, rid)
        assert service._dilleri_dagit(s, run) == []


def test_paket_kosusu_yalniz_java_testi_varsa_tek_java_kosusu(
    engine: Engine, toolchain: FakeToolchain
) -> None:
    forge = DilliForge(dosyalar=["e2e-java/src/test/java/com/x/uretilen/AbcTest.java"])
    with services.override(forge=lambda: forge):
        with Session(engine) as s, s.begin():
            rid = enqueue_ci(s, SHA, "nightly", anahtar="nightly:2026-11-11")
        run_jobs(engine)
    with Session(engine) as s:
        assert s.get(Run, rid).ortam["dil"] == "java"
        assert s.scalar(select(Run).where(Run.id != rid, Run.tetik == "nightly")) is None
    assert [(b.get("lang"), b.get("platform")) for b in toolchain.istekler] == [("java", "web")]


def test_paket_kosusu_forge_okunamazsa_ts(engine: Engine, toolchain: FakeToolchain) -> None:
    forge = DilliForge(hata=True)
    with services.override(forge=lambda: forge):
        with Session(engine) as s, s.begin():
            rid = enqueue_ci(s, SHA, "deploy")
        run_jobs(engine)
    with Session(engine) as s:
        assert s.get(Run, rid).ortam["dil"] == "ts"
    assert all("lang" not in b for b in toolchain.istekler)


def test_repodaki_web_dilleri_saf() -> None:
    def lf(dosyalar: list[str]):
        return lambda p, r: [d for d in dosyalar if d.startswith(p)]

    kw = {"e2e": "demo-app/e2e", "e2e_java": "demo-app/e2e-java"}
    assert dil.repodaki_web_dilleri(lf([]), "main", **kw) == ("ts",)
    assert dil.repodaki_web_dilleri(
        lf(["demo-app/e2e-java/src/test/java/a/birim/XTest.java"]), "main", **kw
    ) == ("ts",)
    assert dil.repodaki_web_dilleri(
        lf(["demo-app/e2e/tests/a.spec.ts", "demo-app/e2e-java/src/test/java/a/YTesti.java"]),
        "main",
        **kw,
    ) == ("ts", "java")


# ------------------------------------------------------------------------------ GitHub kipi


def test_github_web_java_is_akisi_artefakt_ve_rapor_dili() -> None:
    web_java = Run(ortam={"platform": "web", "dil": "java"})
    web_ts = Run(ortam={"platform": "web", "dil": "ts"})
    android = Run(ortam={"platform": "android"})
    assert service.gh_is_akisi(web_java) == {"workflow": "web-java.yml"}
    assert service.gh_is_akisi(web_ts) == {} and service.gh_is_akisi(Run(ortam={})) == {}
    assert service.gh_sonuc_artefakti(web_java) == "web-java-results"
    assert service.gh_sonuc_artefakti(web_ts) == "test-local-results"
    assert service.java_kosusu_mu(web_java) and service.java_kosusu_mu(android)
    assert not service.java_kosusu_mu(web_ts)
    assert clients._is_akisi("web-java.yml") == "web-java.yml"
    # `/check` raporu: `lang=java, platform=web` web'dir; dil `java`.
    rapor = {"lang": "java", "platform": "web"}
    assert service.rapor_platformu(rapor) == "web" and service.rapor_dili(rapor) == "java"
    assert service.rapor_platformu({"lang": "java"}) is None
    assert service.rapor_platformu({}) == "web" and service.rapor_dili({}) is None
    assert service.check_body_platformu("web", "java") == {"lang": "java", "platform": "web"}
    assert service.check_body_platformu("web", "ts") == {}
    assert service.check_body_platformu("ios", "java") == {"lang": "java", "platform": "ios"}
    # Kendi iş akışı olan kardeş koşuya elle deploy `workflow_dispatch` ile gider.
    deploy_java = Run(
        tetik="deploy", ortam={"platform": "web", "dil": "java", "dispatch": "deploy"}
    )
    assert service._olaylar(deploy_java) == ("workflow_dispatch",)
    assert service._olaylar(Run(tetik="deploy", ortam={"dispatch": "deploy"})) == (
        "repository_dispatch",
    )


# ------------------------------------------------------------- K-T1: check adı ve kardeşler


def _iki_dilli_yanit(kok: Path):
    """Sahte toolchain: gövdeye göre TS (`local-ci`, yeşil) ya da Java (`local-ci-web-java`,
    kırmızı) kaydı yazar — gerçek worker gibi her koşu yalnız kendi girdisini değiştirir."""
    java_yaniti = _web_java_yaniti(kok)

    def yanit(body: dict[str, Any]) -> httpx.Response:
        if body.get("lang") == "java":
            return java_yaniti(body)
        rapor = kosu_yaz(kok, body["run_id"], sha=body["sha"], conclusion="success",
                         durum="passed", checks=False)  # fmt: skip
        _checks_yaz(kok, body["sha"], "local-ci", "success")
        return httpx.Response(200, json=rapor)

    return yanit


def test_ayni_shada_ts_ve_java_kardesleri_kendi_checkini_okur(
    engine: Engine, toolchain: FakeToolchain, artefakt_kok: Path
) -> None:
    """MİM-Y3 regresyonu: aynı sha'nın TS ve Java koşuları birbirinin check kaydını ezmez; her
    koşu kendi kontrolünü (`local-ci` / `local-ci-web-java`) okur."""
    toolchain.yanit = _iki_dilli_yanit(artefakt_kok)
    forge = DilliForge(
        dosyalar=["e2e/tests/cart.spec.ts", "e2e-java/src/test/java/a/uretilen/XTest.java"]
    )
    with services.override(forge=lambda: forge):
        with Session(engine) as s, s.begin():
            enqueue_ci(s, SHA, "push")
        run_jobs(engine)
    with Session(engine) as s:
        kosular = {
            r.ortam["dil"]: r
            for r in s.scalars(select(Run).where(Run.tetik == "push", Run.commit == SHA))
        }
    assert set(kosular) == {"ts", "java"}
    ts, java = kosular["ts"].artefaktlar["checks"], kosular["java"].artefaktlar["checks"]
    assert (ts["durum"], ts["conclusion"]) == ("completed", "success")
    assert (java["durum"], java["conclusion"]) == ("completed", "failure")
    kayit = json.loads((artefakt_kok / "checks" / f"{SHA}.json").read_text())
    assert {c["name"]: c["conclusion"] for c in kayit["checks"]} == {
        "local-ci": "success",
        "local-ci-web-java": "failure",
    }
    assert (kosular["ts"].sonuc, kosular["java"].sonuc) == ("passed", "failed")


def test_scriptsiz_pr_yalniz_e2e_java_degistiyse_java_kosar(
    engine: Engine, toolchain: FakeToolchain, artefakt_kok: Path, fake_forge: FakeForge
) -> None:
    """MİM-Y3 regresyonu: yalnız `e2e-java/` değiştiren script'siz PR TS koşup yeşil `local-ci`
    yazmaz; Java koşar ve `local-ci-web-java` yazar."""
    toolchain.yanit = _iki_dilli_yanit(artefakt_kok)
    forge = DilliForge(
        prs={21: PullRequest(number=21, branch="tp/repair-x", title="x", head_sha=SHA)},
        dosyalar=["e2e/tests/cart.spec.ts", "e2e-java/src/test/java/a/uretilen/XTest.java"],
        degisen=["e2e-java/src/test/java/com/antreklabs/bayi/ekranlar/Kimlikler.java"],
    )
    with services.override(forge=lambda: forge):
        with Session(engine) as s, s.begin():
            rid = enqueue_ci(s, SHA, "pr", 21)
        with Session(engine) as s:
            assert "dil" not in s.get(Run, rid).ortam  # dil işte, değişen yollardan çözülür
        run_jobs(engine)
    assert forge.farklar == [("c" * 40, SHA)]
    with Session(engine) as s:
        kosular = list(s.scalars(select(Run).where(Run.tetik == "pr", Run.pr_no == 21)))
    assert [(r.id, r.ortam["dil"]) for r in kosular] == [(rid, "java")]
    assert [(b.get("lang"), b.get("platform")) for b in toolchain.istekler] == [("java", "web")]
    kayit = json.loads((artefakt_kok / "checks" / f"{SHA}.json").read_text())
    assert [c["name"] for c in kayit["checks"]] == ["local-ci-web-java"]


@pytest.mark.parametrize(
    ("degisen", "beklenen"),
    [
        (["e2e/tests/a.spec.ts", "e2e-java/src/test/java/a/uretilen/XTest.java"], ["ts", "java"]),
        (["e2e/pages/CartPage.ts"], ["ts"]),
        # K-T11: test kökleri dışında değişiklik → repodaki tüm tam hat dilleri.
        (["web/src/App.tsx"], ["ts", "java"]),
        # GÜV-Y5 kilitlenmesi: api + e2e-java → iki dil koşar (kapı local-ci'ı da görür).
        (["api/app.py", "e2e-java/src/test/java/a/ekranlar/Kimlikler.java"], ["ts", "java"]),
        (["e2e-app/pom.xml"], ["ts"]),  # yalnız uygulama (Appium) test kökü: web genişlemez
        (None, ["ts", "java"]),  # fark okunamadı: repodaki tüm diller (güvenli taraf)
    ],
)
def test_scriptsiz_pr_dilleri_degisen_yollardan(
    engine: Engine, toolchain: FakeToolchain, degisen: list[str] | None, beklenen: list[str]
) -> None:
    forge = DilliForge(
        prs={22: PullRequest(number=22, branch="b", title="x", head_sha=SHA)},
        dosyalar=["e2e/tests/cart.spec.ts", "e2e-java/src/test/java/a/testler/SepetTesti.java"],
        degisen=degisen,
    )
    with services.override(forge=lambda: forge):
        with Session(engine) as s, s.begin():
            rid = enqueue_ci(s, SHA, "pr", 22)
        run_jobs(engine)
    with Session(engine) as s:
        kosular = list(
            s.scalars(select(Run).where(Run.tetik == "pr", Run.pr_no == 22).order_by(Run.olusturma))
        )
    assert [r.ortam["dil"] for r in kosular] == beklenen
    assert kosular[0].id == rid
    assert all(r.ortam.get("kardes_kosu") == str(rid) for r in kosular[1:])


def test_scriptli_push_kardes_dagitimi_alir(engine: Engine, toolchain: FakeToolchain) -> None:
    """K-T2 (MİM-O4): merge sonrası script'li push da paket koşusudur; ana koşu script'in dilinde,
    repodaki diğer tam hat dili kardeş koşuda."""
    sid = _web_script(engine, "java")
    forge = DilliForge(
        dosyalar=["e2e/tests/cart.spec.ts", "e2e-java/src/test/java/a/uretilen/XTest.java"]
    )
    with services.override(forge=lambda: forge):
        with Session(engine) as s, s.begin():
            rid = enqueue_ci(s, SHA, "push", script_id=sid)
        run_jobs(engine)
    with Session(engine) as s:
        kosular = {
            r.ortam["dil"]: r
            for r in s.scalars(select(Run).where(Run.tetik == "push", Run.commit == SHA))
        }
        ana = s.get(Run, rid)
        assert service._dilleri_dagit(s, ana) == []  # idempotent
    assert set(kosular) == {"java", "ts"}
    assert kosular["java"].id == rid and kosular["java"].script_id == sid
    assert kosular["ts"].script_id is None and kosular["ts"].ortam["kardes_kosu"] == str(rid)
    assert kosular["java"].ortam["dil_dagitimi"] == ["java", "ts"]
    assert sorted(f"{b.get('lang')}" for b in toolchain.istekler) == ["None", "java"]


def test_scriptli_pr_dagitim_almaz(engine: Engine, toolchain: FakeToolchain) -> None:
    sid = _web_script(engine, "java")
    forge = DilliForge(dosyalar=["e2e/tests/cart.spec.ts"], degisen=["e2e/tests/a.spec.ts"])
    with services.override(forge=lambda: forge):
        with Session(engine) as s, s.begin():
            enqueue_ci(s, SHA, "pr", 23, script_id=sid)
        run_jobs(engine)
    with Session(engine) as s:
        kosular = list(s.scalars(select(Run).where(Run.pr_no == 23)))
    assert [r.ortam["dil"] for r in kosular] == ["java"]


# --------------------------------------------------------------- K-T3: GitHub kipi kapısı


@pytest.mark.parametrize(("web_dilleri", "beklenen"), [("", ["ts"]), ("ts,java", ["ts", "java"])])
def test_github_kipinde_java_kardesi_yalniz_etkinse(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, web_dilleri: str, beklenen: list[str]
) -> None:
    """K-T3 (OPS-Y1/O1): `TP_WEB_DILLERI` Java'yı içermezse `web-java.yml` koşmaz; kardeş koşu
    açılmaz (gelmeyecek olayı saatlerce bekleyip `error` olmaz). LocalForge'da dosyalar belirler."""
    monkeypatch.setenv("TP_WEB_DILLERI", web_dilleri)
    forge = DilliForge(
        dosyalar=["e2e/tests/cart.spec.ts", "e2e-java/src/test/java/a/uretilen/XTest.java"]
    )
    with services.override(forge=lambda: forge, mode=lambda: "github"):
        with Session(engine) as s, s.begin():
            rid = enqueue_ci(s, SHA, "nightly", anahtar="nightly:gh")
        with Session(engine) as s, s.begin():
            service._dilleri_dagit(s, s.get(Run, rid))
        with Session(engine) as s:
            kosular = list(
                s.scalars(select(Run).where(Run.tetik == "nightly").order_by(Run.olusturma))
            )
    assert [r.ortam["dil"] for r in kosular] == beklenen
    assert all(r.kaynak == "github" for r in kosular)


def test_github_kipinde_gecersiz_web_dilleri_yalniz_ts(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_WEB_DILLERI", "ts,csharp")
    forge = DilliForge(dosyalar=["e2e-java/src/test/java/a/uretilen/XTest.java"])
    with services.override(forge=lambda: forge, mode=lambda: "github"):
        with Session(engine) as s, s.begin():
            rid = enqueue_ci(s, SHA, "deploy")
        with Session(engine) as s, s.begin():
            assert service._dilleri_dagit(s, s.get(Run, rid)) == []
        with Session(engine) as s:
            assert s.get(Run, rid).ortam["dil"] == "ts"


def test_check_adi_tek_kaynak() -> None:
    from tp_core.integrations import forge as f

    assert p.check_adi("web") == p.check_adi("web", "ts") == "local-ci"
    assert p.check_adi("web", "java") == f.LOCAL_WEB_JAVA_CHECK == "local-ci-web-java"
    assert p.check_adi("android", "java") == "local-ci-android"
    assert f.APP_PLATFORM_CHECKS == ("local-ci-android", "local-ci-ios", "local-ci-windows")
    assert f.WEB_TAM_HAT_DILLERI == p.TAM_HAT_DILLERI


def test_java_test_kalibi_ve_degisen_diller_saf() -> None:
    def paket_testi(yol: str) -> bool:  # paket koşusu sayımı (`repodaki_web_dilleri`)
        return p.java_test_dosyasi_mi(yol, haric=("birim",))

    for ad in ("SepetTest.java", "SepetTesti.java", "SepetTests.java", "SepetIT.java"):
        assert paket_testi(f"e2e-java/src/test/java/a/testler/{ad}")
    # Üretilen testler paket koşusunda sayılır; birim testleri sayılmaz.
    assert paket_testi("e2e-java/src/test/java/a/uretilen/TPD1WebC2_abTest.java")
    assert not paket_testi("e2e-java/src/test/java/a/birim/KimlikTest.java")
    assert not paket_testi("e2e-java/src/test/java/a/ekranlar/LoginPage.java")
    kw = {"e2e": "demo-app/e2e", "e2e_java": "demo-app/e2e-java"}
    assert dil.degisen_web_dilleri(["demo-app/e2e-java/pom.xml"], **kw) == ("java",)
    assert dil.degisen_web_dilleri(["demo-app/e2e/x.ts", "demo-app/e2e-java/y"], **kw) == (
        "ts",
        "java",
    )
    assert dil.degisen_web_dilleri([], **kw) == ("ts",)


def test_degisen_web_dilleri_kokler_disi_degisiklik_repodaki_tum_diller() -> None:
    """K-T11: test kökleri dışında (uygulama kodu) değişiklik → repodaki tüm tam hat dilleri."""
    kw = {"e2e": "demo-app/e2e", "e2e_java": "demo-app/e2e-java"}
    iki = ("ts", "java")
    # Yalnız uygulama kodu: repodaki her iki dil koşar (bugün yalnız ts koşuyordu).
    assert dil.degisen_web_dilleri(["demo-app/api/x.py"], **kw, repodaki=iki) == iki
    # GÜV-Y5 kilitlenme senaryosu: api + e2e-java değişen PR → iki dil (TS kapısı da beslenir).
    assert (
        dil.degisen_web_dilleri(
            ["demo-app/api/x.py", "demo-app/e2e-java/pom.xml"], **kw, repodaki=iki
        )
        == iki
    )
    # Repoda yalnız TS varsa uygulama değişikliği yalnız ts koşar.
    assert dil.degisen_web_dilleri(["demo-app/web/App.tsx"], **kw, repodaki=("ts",)) == ("ts",)
    # Repoda yalnız Java varsa: java (ts kapısı yapılandırmadan gelir).
    assert dil.degisen_web_dilleri(["demo-app/web/App.tsx"], **kw, repodaki=("java",)) == ("java",)
    # Yalnız e2e-app/ (kendi kontrolü olan test kökü) değişti: web dilleri genişlemez.
    app = {**kw, "repodaki": iki, "diger_test_kokleri": ("demo-app/e2e-app",)}
    assert dil.degisen_web_dilleri(["demo-app/e2e-app/pom.xml"], **app) == ("ts",)
    assert dil.degisen_web_dilleri(["demo-app/e2e-java/a"], **app) == ("java",)
    # Doğrulanmamış diller repodaki listesinde olsa da CI'a girmez.
    assert dil.degisen_web_dilleri(["x"], **kw, repodaki=("csharp",)) == ("ts",)
    assert dil.tam_hat_dili("csharp") is None and dil.tam_hat_dili("java") == "java"
