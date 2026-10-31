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
    """make break → push `run` satırı (main'in yeni sha'sı, isteyen demo-admin) + ci.run işi."""
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
    assert out["ci_error"] is None and out["ci_run_id"]
    with Session(engine) as s:
        runs = s.scalars(select(Run)).all()
        assert len(runs) == 1
        run = runs[0]
        assert str(run.id) == out["ci_run_id"]
        assert (run.tetik, run.commit, run.sonuc, run.kaynak) == (
            "push",
            forge.head_sha(),
            "queued",
            "local",
        )
        assert run.pr_no is None and run.ortam["isteyen"] == "demo-admin"
        isler = s.scalars(select(Job).where(Job.idempotency_key == f"ci.run:{run.id}")).all()
        assert len(isler) == 1
