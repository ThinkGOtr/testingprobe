"""toolchain-worker Java yolu (009 §2.3–2.5): /symbols, /check, /ast-guard için `lang=java`.

Gerçek `java-araclar.jar` (toolchain/java-araclar/target/, `./mvnw -B package`) ve `java` varsa
uçtan uca koşar; Maven sahte bir betikle taklit edilir (çevrimdışı derlemenin kendisi isteğe bağlı
`TP_TEST_MVN` + `TP_TEST_E2E_APP_M2` testindedir).
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TOOLCHAIN, Forge, make_fake_node
from tests.test_check import runner_client
from toolchain_common.settings import settings
from worker import app as worker_app
from worker import check as checks
from worker import java as javayol
from worker.app import CheckBody, app

JAR = TOOLCHAIN / "java-araclar" / "target" / "java-araclar.jar"
FIXTURE = TOOLCHAIN / "java-araclar" / "src" / "test" / "resources" / "e2e-app"
TRUSTED_POM = TOOLCHAIN / "e2e-app-deps" / "pom.xml"
REPO = TOOLCHAIN.parent
DEMO_E2E_APP = REPO / "demo-app" / "e2e-app"
GEN = "src/test/java/com/antreklabs/bayi/uretilen/DEMO12C1_ab12cd34Test.java"
KIMLIK = "src/test/java/com/antreklabs/bayi/ekranlar/Kimlikler.java"

requires_jar = pytest.mark.skipif(
    not JAR.is_file() or shutil.which("java") is None,
    reason="java-araclar.jar yok (cd toolchain/java-araclar && ./mvnw -B package) ya da java yok",
)


def fixture_files() -> dict[str, str]:
    files = {
        f"e2e-app/{p.relative_to(FIXTURE).as_posix()}": p.read_text(encoding="utf-8")
        for p in sorted(FIXTURE.rglob("*"))
        if p.is_file()
    }
    files["e2e-app/pom.xml"] = TRUSTED_POM.read_text(encoding="utf-8")
    return files


@pytest.fixture
def java_env(env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """İmajdaki /opt/e2e-app karşılığı (güvenilir pom + boş m2) ve sahte mvn."""
    deps = tmp_path / "e2e-app-deps"
    (deps / "m2").mkdir(parents=True)
    shutil.copy(TRUSTED_POM, deps / "pom.xml")
    monkeypatch.setenv("TP_E2E_APP_DEPS", str(deps))
    monkeypatch.setenv("TP_JAVA_ARACLAR_JAR", str(JAR))
    monkeypatch.setenv("TP_MVN", str(fake_mvn(tmp_path)))
    worker_app._SYMBOL_CACHE.clear()
    return tmp_path


def fake_mvn(tmp_path: Path, exit_code: int = 0, out: str = "") -> Path:
    return make_fake_node(
        tmp_path,
        f"""
        log = pathlib.Path({str(tmp_path / "mvn.log")!r})
        with log.open("a") as fh:
            fh.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(),
                                  "skip_rc": os.environ.get("MAVEN_SKIP_RC"),
                                  "maven_opts": os.environ.get("MAVEN_OPTS")}}) + "\\n")
        print({out!r})
        sys.exit({exit_code})
        """,
        name=f"fake-mvn-{exit_code}",
    )


def mvn_calls(tmp_path: Path) -> list[dict[str, Any]]:
    log = tmp_path / "mvn.log"
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


# ------------------------------------------------------------------------- birim: dil, gövde


def test_resolve_lang() -> None:
    assert javayol.resolve_lang(None, None) == "ts"
    assert javayol.resolve_lang(None, "web") == "ts"
    assert javayol.resolve_lang(None, "android") == "java"
    assert javayol.resolve_lang("java", "ios") == "java"
    with pytest.raises(ValueError):
        javayol.resolve_lang("ts", "windows")
    with pytest.raises(ValueError):
        javayol.resolve_lang("kotlin", None)


def test_check_body_lang_rules() -> None:
    # Varsayılan TS: eski gövde aynen geçer, dil ts.
    b = CheckBody.model_validate({"sha": "main", "test_files": ["tests/a.spec.ts"]})
    assert b.dil == "ts" and b.test_files == ["tests/a.spec.ts"]
    b = CheckBody.model_validate({"sha": "main", "platform": "android", "test_files": [GEN, GEN]})
    assert b.dil == "java" and b.test_files == [GEN]
    for bad in (
        {"sha": "main", "lang": "java", "test_files": ["tests/a.spec.ts"]},
        {"sha": "main", "test_files": [GEN]},
        {"sha": "main", "lang": "java", "test_files": ["src/test/java/../x/YTest.java"]},
        {"sha": "main", "lang": "java", "grep": "x"},
        {"sha": "main", "lang": "java", "affected_by": ["@diff"]},
        {"sha": "main", "lang": "ts", "platform": "ios"},
        {"sha": "main", "platform": "symbian"},
    ):
        with pytest.raises(ValueError):
            CheckBody.model_validate(bad)


def test_check_deps(tmp_path: Path) -> None:
    deps = tmp_path / "deps"
    deps.mkdir()
    shutil.copy(TRUSTED_POM, deps / "pom.xml")
    root = tmp_path / "e2e-app"
    root.mkdir()
    cfg = dataclasses.replace(settings(), e2e_app_deps=deps)
    assert "pom.xml yok" in javayol.check_deps(cfg, root)["error"]
    shutil.copy(TRUSTED_POM, root / "pom.xml")
    assert javayol.check_deps(cfg, root)["ok"] is True
    (root / ".mvn" / "wrapper").mkdir(parents=True)
    (root / ".mvn" / "wrapper" / "maven-wrapper.properties").write_text("distributionUrl=x\n")
    assert javayol.check_deps(cfg, root)["ok"] is True
    (root / ".mvn" / "jvm.config").write_text("-javaagent:/tmp/x.jar\n")
    r = javayol.check_deps(cfg, root)
    assert r["ok"] is False and r["config_file"] == ".mvn/jvm.config"
    (root / ".mvn" / "jvm.config").unlink()
    (root / "pom.xml").write_text(TRUSTED_POM.read_text() + "<!-- x -->\n")
    r = javayol.check_deps(cfg, root)
    assert r["ok"] is False and r["pom_sha256"] != r["image_pom_sha256"]


def test_parse_compile_and_argv(tmp_path: Path) -> None:
    root = tmp_path / "e2e-app"
    out = (
        f"[ERROR] {root}/src/test/java/a/BTest.java:[12,5] cannot find symbol\n"
        "[ERROR]   symbol: method yok()\n"
        f"[WARNING] {root}/src/test/java/a/C.java:[3,1] deprecated\n"
    )
    assert javayol.parse_compile(out, root) == [
        {
            "file": "src/test/java/a/BTest.java",
            "line": 12,
            "column": 5,
            "severity": "error",
            "message": "cannot find symbol",
        },
        {
            "file": "src/test/java/a/C.java",
            "line": 3,
            "column": 1,
            "severity": "warning",
            "message": "deprecated",
        },
    ]
    argv = javayol.compile_argv(settings(), root, tmp_path / "head")
    assert argv[1:5] == ["-B", "-q", "-o", "-f"]
    assert "-Dmaven.compiler.proc=none" in argv and argv[-1] == "test-compile"
    assert any(a.startswith("-Dmaven.repo.local.tail=") for a in argv)


# ---------------------------------------------------------------------- uçtan uca (gerçek jar)


@pytest.fixture
def client(java_env: Path) -> TestClient:
    return TestClient(app)


@requires_jar
def test_symbols_java(client: TestClient, forge: Forge) -> None:
    head = forge.commit("tp/java", fixture_files())
    data = client.post("/symbols", json={"sha": head, "platform": "android"}).json()
    assert data["sha"] == head and data["lang"] == "java"
    assert data["schema_version"] == 1
    assert [p["class"] for p in data["page_objects"]] == [
        "GirisEkrani",
        "KatalogEkrani",
        "SepetEkrani",
    ]
    assert data["fixtures"] == ["girisEkrani", "katalogEkrani", "sepetEkrani"]
    assert data["errors"] == []
    loc = data["page_objects"][0]["locators"]["Giris.KULLANICI_ADI"]
    assert loc["testId"] == "login-username" and loc["file"] == KIMLIK
    # Golden: forge'dan çıkarılan tablo jar'ın fikstür çıktısıyla aynı (sha/lang/kaynak hariç).
    golden = json.loads(
        (TOOLCHAIN / "java-araclar/src/test/resources/beklenen/semboller.json").read_text()
    )
    assert {k: v for k, v in data.items() if k not in ("sha", "lang", "kaynak")} == golden
    # core'un SymbolTable'ı tabloyu değişmeden okur (anahtarlar, metot arama, locators()).
    assert data["page_objects"][1]["methods"][0]["params"][1] == {
        "name": "adet",
        "type": "int",
        "optional": False,
    }
    # TS yolu ayrı önbellek anahtarıyla, değişmeden.
    assert client.post("/symbols", json={"sha": head, "lang": "kotlin"}).status_code == 422


@requires_jar
def test_check_java_success(java_env: Path, forge: Forge) -> None:
    head = forge.commit("tp/java", fixture_files())
    client, calls = runner_client()
    report = checks.execute(
        settings(),
        checks.CheckRequest(sha=head, lang="java", platform="android", test_files=[GEN]),
        runner_client=client,
    )
    assert report["conclusion"] == "success", report
    assert report["lang"] == "java" and report["platform"] == "android"
    assert [report[s]["ok"] for s in javayol.STEPS] == [True] * len(javayol.STEPS)
    assert report["guard"]["report"]["files"] == [GEN]
    assert report["guard"]["report"]["violations"] == []
    (mvn,) = mvn_calls(java_env)
    assert mvn["argv"][-1] == "test-compile" and "-o" in mvn["argv"]
    assert mvn["skip_rc"] == "1" and mvn["maven_opts"] is None
    (call,) = calls
    assert call["body"]["lang"] == "java" and call["body"]["platform"] == "android"
    assert call["body"]["test_files"] == [GEN]
    # Tam kapsam değil (test_files) → merge kapısı dosyası yazılmaz.
    assert report["check_recorded"] is False


@requires_jar
def test_check_java_guard_blocks_compile(java_env: Path, forge: Forge) -> None:
    files = fixture_files()
    files[f"e2e-app/{GEN}"] = files[f"e2e-app/{GEN}"].replace(
        'girisEkrani().girisYap("bayi2", "Demo123!");', "Thread.sleep(1000);"
    )
    head = forge.commit("tp/java-bad", files)
    client, calls = runner_client()
    report = checks.execute(
        settings(), checks.CheckRequest(sha=head, lang="java"), runner_client=client
    )
    assert report["conclusion"] == "failure"
    assert report["failed_steps"] == ["guard"]
    codes = [v["code"] for v in report["guard"]["report"]["violations"]]
    assert "thread_sleep" in codes
    assert report["compile"]["skipped"] and report["run"]["skipped"]
    assert mvn_calls(java_env) == [] and calls == []


@requires_jar
def test_check_java_pom_mismatch_and_compile_error(
    java_env: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = fixture_files()
    files["e2e-app/pom.xml"] += "<!-- değişti -->\n"
    head = forge.commit("tp/java-pom", files)
    report = checks.execute(settings(), checks.CheckRequest(sha=head, lang="java"))
    assert report["failed_steps"] == ["deps"] and "pom.xml" in report["deps"]["error"]

    head = forge.commit("tp/java-ok", fixture_files())
    root = "/tmp/x/e2e-app"
    monkeypatch.setenv(
        "TP_MVN",
        str(
            fake_mvn(
                java_env,
                exit_code=1,
                out=f"[ERROR] {root}/src/test/java/a/BTest.java:[3,9] cannot find symbol",
            )
        ),
    )
    report = checks.execute(settings(), checks.CheckRequest(sha=head, lang="java"))
    assert report["failed_steps"] == ["compile"]
    assert report["compile"]["diagnostics"][0]["line"] == 3
    assert report["run"]["skipped"]


@requires_jar
def test_ast_guard_java_repair(client: TestClient, forge: Forge) -> None:
    base = forge.commit("tp/java-base", fixture_files())
    text = fixture_files()[f"e2e-app/{KIMLIK}"]
    ok = forge.commit(
        "tp/java-base", {f"e2e-app/{KIMLIK}": text.replace('"cart-total"', '"cart-sum"')}
    )
    resp = client.post(
        "/ast-guard", json={"base_sha": base, "head_sha": ok, "mode": "repair", "lang": "java"}
    )
    data = resp.json()
    assert resp.status_code == 200 and data["ok"] is True, data
    assert data["report"]["testid_changes"] == [
        {
            "file": f"e2e-app/{KIMLIK}",
            "entry": "Sepet.TOPLAM",
            "before": "cart-total",
            "after": "cart-sum",
        }
    ]
    bad = forge.commit(
        "tp/java-base",
        {
            f"e2e-app/{KIMLIK}": text.replace("Sepet toplamı", "Toplam"),
            "e2e-app/README.md": "değişti\n",
        },
    )
    data = client.post(
        "/ast-guard",
        json={"base_sha": ok, "head_sha": bad, "mode": "repair", "platform": "ios"},
    ).json()
    assert data["ok"] is False
    codes = {v["code"] for v in data["violations"]}
    assert {"non_testid_change", "non_locator_file_changed"} <= codes
    # pr modu: yalnızca üretilen test + Kimlikler saflığı (README/niyet değişikliği serbest).
    data = client.post(
        "/ast-guard", json={"base_sha": ok, "head_sha": bad, "mode": "pr", "lang": "java"}
    ).json()
    assert data["ok"] is True, data


def test_jar_error_is_reported(
    java_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """jar çalışamazsa (çıkış 2 / bozuk çıktı) JavaAracError — sessiz geçiş yok."""
    fake_java = make_fake_node(
        tmp_path,
        """
        print(json.dumps({"ok": False, "error": "kök yok"}))
        sys.exit(2)
        """,
        name="fake-java",
    )
    monkeypatch.setenv("TP_JAVA", str(fake_java))
    with pytest.raises(javayol.JavaAracError, match="kök yok"):
        javayol.run_guard(settings(), tmp_path, [])
    fake_java.write_text(
        fake_java.read_text()
        .replace("sys.exit(2)", "sys.exit(0)")
        .replace(
            'print(json.dumps({"ok": False, "error": "kök yok"}))',
            'print(json.dumps({"ok": False, "violations": [{"code": "x"}]}))',
        )
    )
    with pytest.raises(javayol.JavaAracError, match="beklenmeyen çıkış"):
        javayol.run_guard(settings(), tmp_path, [])


# ------------------------------------------------------------- güvenilir kopya + gerçek Maven


@pytest.mark.skipif(not DEMO_E2E_APP.joinpath("pom.xml").is_file(), reason="demo-app/e2e-app yok")
def test_trusted_pom_matches_demo_app() -> None:
    """İmaja giren pom demo-app/e2e-app/pom.xml ile birebir aynı olmalı (fark: cp + imaj derle)."""
    assert TRUSTED_POM.read_bytes() == (DEMO_E2E_APP / "pom.xml").read_bytes()


@pytest.mark.skipif(
    not (os.environ.get("TP_TEST_MVN") and os.environ.get("TP_TEST_E2E_APP_M2")),
    reason="gerçek derleme için TP_TEST_MVN ve TP_TEST_E2E_APP_M2 (ısıtılmış depo) gerekli",
)
def test_real_offline_test_compile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deps = tmp_path / "deps"
    deps.mkdir()
    shutil.copy(TRUSTED_POM, deps / "pom.xml")
    (deps / "m2").symlink_to(os.environ["TP_TEST_E2E_APP_M2"], target_is_directory=True)
    monkeypatch.setenv("TP_E2E_APP_DEPS", str(deps))
    monkeypatch.setenv("TP_MVN", os.environ["TP_TEST_MVN"])
    root = tmp_path / "e2e-app"
    shutil.copytree(FIXTURE, root)
    shutil.copy(TRUSTED_POM, root / "pom.xml")
    cfg = settings()
    assert javayol.check_deps(cfg, root)["ok"]
    res = javayol.run_test_compile(cfg, root)
    assert res["ok"], res
    gen = root / GEN
    gen.write_text(gen.read_text().replace('sepeteEkle("P-001", 7)', 'sepeteEkle("P-001", "7")'))
    res = javayol.run_test_compile(cfg, root)
    assert not res["ok"]
    assert res["diagnostics"] and res["diagnostics"][0]["file"] == GEN
    if (DEMO_E2E_APP / "pom.xml").is_file():
        # Ş3'ün gerçek projesi aynı ısıtılmış depoyla çevrimdışı derlenir.
        real = tmp_path / "gercek"
        shutil.copytree(DEMO_E2E_APP, real, ignore=shutil.ignore_patterns("target"))
        assert javayol.check_deps(cfg, real)["ok"]
        res = javayol.run_test_compile(cfg, real)
        assert res["ok"], res
