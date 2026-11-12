"""LocalForge: geçici bir bare git deposuna karşı gerçek git ile."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import threading
from pathlib import Path

import pytest

from tp_core.integrations.forge import (
    ForgeConflictError,
    ForgeError,
    ForgeNotFoundError,
    ForgeProtectionError,
    ForgeStateError,
    ForgeValidationError,
    get_forge,
)
from tp_core.integrations.forge_local import LocalForge
from tp_core.ports import ForgePort

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git yok")

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

LOGIN_PAGE = """export const loginLocators = {
  username: 'login-username',
  submit: 'login-submit',
};
"""
CATALOG = """export function Card() {
  return <button data-testid="add-to-cart">Sepete ekle</button>;
}
// fiyat (TL) [kampanya]
"""


def git(*args: str, cwd: Path | None = None, git_dir: Path | None = None) -> str:
    cmd = ["git"]
    if git_dir is not None:
        cmd += ["--git-dir", str(git_dir)]
    out = subprocess.run(
        [*cmd, *args], cwd=cwd, env=GIT_ENV, capture_output=True, check=True, text=True
    )
    return out.stdout.strip()


@pytest.fixture
def bare(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    (work / "e2e" / "pages" / "login").mkdir(parents=True)
    (work / "web" / "src").mkdir(parents=True)
    (work / "ci").mkdir()
    (work / "README.md").write_text("# Demo\n")
    (work / "e2e" / "pages" / "login" / "locators.ts").write_text(LOGIN_PAGE)
    (work / "web" / "src" / "Catalog.tsx").write_text(CATALOG)
    run_sh = work / "ci" / "run.sh"
    run_sh.write_text("#!/bin/sh\necho ok\n")
    run_sh.chmod(0o755)
    git("init", "-q", "-b", "main", str(work))
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "baslangic", cwd=work)
    git("tag", "demo-baseline", cwd=work)
    repo = tmp_path / "forge" / "demo-app.git"
    repo.parent.mkdir()
    git("init", "-q", "--bare", "-b", "main", str(repo))
    git("push", "-q", str(repo), "main", "--tags", cwd=work)
    return repo


@pytest.fixture
def artifacts(tmp_path: Path) -> Path:
    path = tmp_path / "artifacts"
    (path / "checks").mkdir(parents=True)
    return path


@pytest.fixture
def forge(bare: Path, artifacts: Path) -> LocalForge:
    return LocalForge(bare, artifacts)


def write_checks(artifacts: Path, sha: str, payload: object) -> None:
    (artifacts / "checks" / f"{sha}.json").write_text(json.dumps(payload))


def ci_green(artifacts: Path, sha: str) -> None:
    write_checks(
        artifacts, sha, [{"name": "local-ci", "status": "completed", "conclusion": "success"}]
    )


# ----------------------------------------------------------------------- okuma


def test_protocol_uyumu(forge: LocalForge) -> None:
    assert isinstance(forge, ForgePort)


def test_head_sha_dal_ve_etiket(forge: LocalForge, bare: Path) -> None:
    main = forge.head_sha()
    assert main == git("rev-parse", "main", git_dir=bare)
    assert forge.head_sha("demo-baseline") == main
    assert forge.head_sha(main) == main
    with pytest.raises(ForgeNotFoundError):
        forge.head_sha("yok-boyle-dal")
    with pytest.raises(ForgeNotFoundError):
        forge.head_sha("0" * 40)


def test_read_file(forge: LocalForge) -> None:
    assert forge.read_file("e2e/pages/login/locators.ts") == LOGIN_PAGE
    with pytest.raises(ForgeNotFoundError):
        forge.read_file("yok.txt")
    with pytest.raises(ForgeNotFoundError):
        forge.read_file("e2e/pages")  # dizin


def test_list_files_onek(forge: LocalForge) -> None:
    assert forge.list_files() == [
        "README.md",
        "ci/run.sh",
        "e2e/pages/login/locators.ts",
        "web/src/Catalog.tsx",
    ]
    assert forge.list_files("e2e/") == ["e2e/pages/login/locators.ts"]
    assert forge.list_files("web/src/Cat") == ["web/src/Catalog.tsx"]
    assert forge.list_files("yok/") == []


def test_search_code_sabit_metin_ve_satir(forge: LocalForge) -> None:
    assert forge.search_code("add-to-cart") == [
        (
            "web/src/Catalog.tsx",
            2,
            '  return <button data-testid="add-to-cart">Sepete ekle</button>;',
        )
    ]
    # regex meta karakterleri sabit metin olarak aranır
    assert forge.search_code("(TL) [kampanya]") == [
        ("web/src/Catalog.tsx", 4, "// fiyat (TL) [kampanya]")
    ]
    assert forge.search_code("bulunmayan-metin") == []
    hits = forge.search_code("login-")
    assert [(p, n) for p, n, _ in hits] == [
        ("e2e/pages/login/locators.ts", 2),
        ("e2e/pages/login/locators.ts", 3),
    ]


def test_search_code_dalda(forge: LocalForge) -> None:
    forge.commit_files(
        "tp/x", {"web/src/Catalog.tsx": CATALOG.replace("add-to-cart", "cart-add")}, "m"
    )
    assert forge.search_code("cart-add", ref="tp/x")[0][0] == "web/src/Catalog.tsx"
    assert forge.search_code("cart-add") == []


# ---------------------------------------------------------------- doğrulama


@pytest.mark.parametrize(
    "path",
    ["", "../etc/passwd", "/etc/passwd", "a/../b", "./a", "a//b", ".git/config", "a/.GIT/x",
     "-rf", "a\\b", "a\nb", "a\x00b"],
)  # fmt: skip
def test_gecersiz_yollar(forge: LocalForge, path: str) -> None:
    with pytest.raises(ForgeValidationError):
        forge.read_file(path)
    with pytest.raises(ForgeValidationError):
        forge.commit_files("tp/x", {path: "x"}, "m")


@pytest.mark.parametrize(
    "ref",
    ["", "-h", "--upload-pack=touch /tmp/pwn", "--output=/tmp/x", "main..dev", "refs/heads/main",
     "a b", "a~1", "a^", "a:b", "x.lock", "a/.b", "dal/", "HEAD", "@{-1}", "a" * 300],
)  # fmt: skip
def test_gecersiz_refler(forge: LocalForge, ref: str) -> None:
    with pytest.raises(ForgeValidationError):
        forge.head_sha(ref)
    with pytest.raises(ForgeValidationError):
        forge.commit_files(ref, {"a.txt": "x"}, "m")


def test_gecersiz_sorgu(forge: LocalForge) -> None:
    for q in ["", "   ", "a\nb", "x" * 300]:
        with pytest.raises(ForgeValidationError):
            forge.search_code(q)


def test_depo_yoksa_anlasilir_hata(tmp_path: Path) -> None:
    f = LocalForge(tmp_path / "yok.git", tmp_path)
    assert not f.available()
    with pytest.raises(ForgeNotFoundError, match="forge-init"):
        f.head_sha()


# ---------------------------------------------------------------------- commit


def test_commit_yeni_dal(forge: LocalForge, bare: Path) -> None:
    main_before = forge.head_sha()
    new_content = LOGIN_PAGE.replace("login-submit", "login-btn")
    sha = forge.commit_files(
        "tp/fix-1",
        {"e2e/pages/login/locators.ts": new_content, "e2e/pages/cart/locators.ts": "x\n"},
        "fix: locator",
    )
    assert forge.head_sha("tp/fix-1") == sha
    assert forge.head_sha() == main_before  # main değişmedi
    assert forge.read_file("e2e/pages/login/locators.ts", "tp/fix-1") == new_content
    assert forge.read_file("e2e/pages/cart/locators.ts", "tp/fix-1") == "x\n"
    assert forge.read_file("e2e/pages/login/locators.ts") == LOGIN_PAGE
    assert git("log", "-1", "--format=%an <%ae>|%cn|%P|%s", sha, git_dir=bare) == (
        f"tp-bot <bot@testingprobe.local>|tp-bot|{main_before}|fix: locator"
    )
    # diğer dosyalar korunur
    assert "README.md" in forge.list_files(ref="tp/fix-1")


def test_commit_var_olan_dala_ekler_ve_degisiklik_yoksa_ayni_sha(
    forge: LocalForge, bare: Path
) -> None:
    first = forge.commit_files("tp/a", {"a.txt": "1\n"}, "bir")
    second = forge.commit_files("tp/a", {"b.txt": "2\n"}, "iki")
    assert git("rev-parse", f"{second}^", git_dir=bare) == first
    assert forge.read_file("a.txt", "tp/a") == "1\n"
    assert forge.commit_files("tp/a", {"b.txt": "2\n"}, "uc") == second


def test_commit_degisiklik_yoksa_dal_yine_olusur(forge: LocalForge) -> None:
    main = forge.head_sha()
    assert forge.commit_files("tp/bos", {"README.md": "# Demo\n"}, "m") == main
    assert forge.head_sha("tp/bos") == main


def test_commit_calistirilabilir_kipi_korur(forge: LocalForge, bare: Path) -> None:
    sha = forge.commit_files("tp/ci", {"ci/run.sh": "#!/bin/sh\necho iki\n"}, "m")
    assert git("ls-tree", sha, "ci/run.sh", git_dir=bare).startswith("100755 ")


def test_commit_main_reddedilir(forge: LocalForge) -> None:
    before = forge.head_sha()
    with pytest.raises(ForgeProtectionError):
        forge.commit_files("main", {"a.txt": "x"}, "m")
    assert forge.head_sha() == before


def test_commit_dizin_dosya_cakismasi(forge: LocalForge) -> None:
    with pytest.raises(ForgeValidationError):
        forge.commit_files("tp/x", {"e2e/pages": "x"}, "m")
    with pytest.raises(ForgeValidationError):
        forge.commit_files("tp/x", {"README.md/alt": "x"}, "m")


def test_commit_bos_girdiler(forge: LocalForge) -> None:
    with pytest.raises(ForgeValidationError):
        forge.commit_files("tp/x", {}, "m")
    with pytest.raises(ForgeValidationError):
        forge.commit_files("tp/x", {"a": "x"}, "  ")


def test_update_ref_cas(forge: LocalForge) -> None:
    sha = forge.commit_files("tp/cas", {"a.txt": "1"}, "m")
    with pytest.raises(ForgeConflictError):
        forge._update_ref("tp/cas", sha, forge.head_sha(), "test")


# ---------------------------------------------------------------------- PR


def test_pr_ac_idempotent_ve_bul(forge: LocalForge, tmp_path: Path) -> None:
    forge.commit_files("tp/fix", {"a.txt": "1"}, "m")
    assert forge.find_open_pr("tp/fix") is None
    pr = forge.open_pr("tp/fix", "Locator onarımı", "gövde", labels=["tp-repair", "tp-repair"])
    assert pr.number == 1
    assert pr.state == "open"
    assert pr.base == "main"
    assert pr.labels == ["tp-repair"]
    assert forge.open_pr("tp/fix", "baska", "x").number == 1
    assert forge.find_open_pr("tp/fix") == pr
    # dala yeni commit → head_sha güncel
    new = forge.commit_files("tp/fix", {"b.txt": "2"}, "m2")
    assert forge.get_pr(1).head_sha == new
    store = tmp_path / "forge" / "tp-prs.json"
    assert stat.S_IMODE(store.stat().st_mode) == 0o666
    assert json.loads(store.read_text())["prs"][0]["title"] == "Locator onarımı"


def test_pr_commitsiz_dal_reddedilir(forge: LocalForge) -> None:
    forge.commit_files("tp/bos", {"README.md": "# Demo\n"}, "m")
    with pytest.raises(ForgeStateError):
        forge.open_pr("tp/bos", "t", "b")
    with pytest.raises(ForgeNotFoundError):
        forge.open_pr("tp/yok", "t", "b")
    with pytest.raises(ForgeValidationError):
        forge.open_pr("main", "t", "b")
    with pytest.raises(ForgeValidationError):
        forge.open_pr("tp/bos", "", "b")


def test_pr_yorum(forge: LocalForge) -> None:
    forge.commit_files("tp/c", {"a.txt": "1"}, "m")
    pr = forge.open_pr("tp/c", "t", "b")
    forge.comment_pr(pr.number, "CI kırmızı: ayrıntı")
    forge.comment_pr(pr.number, "ikinci", author="ali.muhendis")
    comments = forge.get_pr_record(pr.number)["comments"]
    assert [(c["author"], c["body"]) for c in comments] == [
        ("tp-bot", "CI kırmızı: ayrıntı"),
        ("ali.muhendis", "ikinci"),
    ]
    with pytest.raises(ForgeNotFoundError):
        forge.comment_pr(99, "x")


def test_pr_numaralari_eszamanli_benzersiz(forge: LocalForge) -> None:
    for i in range(8):
        forge.commit_files(f"tp/p{i}", {f"f{i}.txt": "x"}, "m")
    numbers: list[int] = []
    errors: list[BaseException] = []

    def ac(i: int) -> None:
        try:
            numbers.append(forge.open_pr(f"tp/p{i}", f"t{i}", "b").number)
        except BaseException as exc:  # pragma: no cover - hata durumunda raporlanır
            errors.append(exc)

    threads = [threading.Thread(target=ac, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert sorted(numbers) == list(range(1, 9))
    assert len(forge.list_prs("open")) == 8


def test_pr_kapat(forge: LocalForge) -> None:
    forge.commit_files("tp/k", {"a.txt": "1"}, "m")
    pr = forge.open_pr("tp/k", "t", "b")
    forge.close_pr(pr.number)
    assert forge.get_pr(pr.number).state == "closed"
    assert forge.find_open_pr("tp/k") is None
    with pytest.raises(ForgeStateError):
        forge.merge_pr(pr.number, "ali")


# ---------------------------------------------------------------------- merge


def test_merge_ci_yoksa_reddedilir(forge: LocalForge) -> None:
    forge.commit_files("tp/m", {"a.txt": "1"}, "m")
    pr = forge.open_pr("tp/m", "t", "b")
    main = forge.head_sha()
    with pytest.raises(ForgeProtectionError, match="local-ci"):
        forge.merge_pr(pr.number, "ali")
    assert forge.head_sha() == main
    assert forge.get_pr(pr.number).state == "open"


def test_merge_ci_kirmiziysa_reddedilir(forge: LocalForge, artifacts: Path) -> None:
    head = forge.commit_files("tp/m", {"a.txt": "1"}, "m")
    pr = forge.open_pr("tp/m", "t", "b")
    write_checks(
        artifacts, head, [{"name": "local-ci", "status": "completed", "conclusion": "failure"}]
    )
    with pytest.raises(ForgeProtectionError, match="failure"):
        forge.merge_pr(pr.number, "ali")
    # eski commit yeşil, yeni commit kontrolsüz → yine reddedilir
    ci_green(artifacts, head)
    forge.commit_files("tp/m", {"b.txt": "2"}, "m2")
    with pytest.raises(ForgeProtectionError):
        forge.merge_pr(pr.number, "ali")


def test_merge_bot_reddedilir(forge: LocalForge, artifacts: Path) -> None:
    head = forge.commit_files("tp/m", {"a.txt": "1"}, "m")
    ci_green(artifacts, head)
    pr = forge.open_pr("tp/m", "t", "b")
    with pytest.raises(ForgeProtectionError, match="bot"):
        forge.merge_pr(pr.number, "tp-bot")
    with pytest.raises(ForgeValidationError):
        forge.merge_pr(pr.number, "--force")


def test_merge_fast_forward(forge: LocalForge, artifacts: Path) -> None:
    head = forge.commit_files("tp/m", {"a.txt": "1"}, "m")
    ci_green(artifacts, head)
    pr = forge.open_pr("tp/m", "t", "b")
    result = forge.merge_pr_detailed(pr.number, "ali")
    assert result.method == "fast-forward"
    assert result.sha == head
    assert result.bypass is False
    assert forge.head_sha() == head
    merged = forge.get_pr(pr.number)
    assert merged.state == "merged"
    rec = forge.get_pr_record(pr.number)
    assert (rec["merged_sha"], rec["merged_by"]) == (head, "ali")
    with pytest.raises(ForgeStateError):
        forge.merge_pr(pr.number, "ali")


def test_merge_commit_ayrismis_main_kural_kapaliyken(
    forge: LocalForge, bare: Path, artifacts: Path
) -> None:
    """`require_up_to_date=False`: eski davranış: test edilmemiş merge commit'i."""
    forge.require_up_to_date = False
    a = forge.commit_files("tp/a", {"a.txt": "1"}, "a")
    b = forge.commit_files("tp/b", {"b.txt": "2"}, "b")
    ci_green(artifacts, a)
    ci_green(artifacts, b)
    pr_a = forge.open_pr("tp/a", "A", "")
    pr_b = forge.open_pr("tp/b", "B", "")
    assert forge.merge_pr(pr_a.number, "ali") == a
    result = forge.merge_pr_detailed(pr_b.number, "ali")
    assert result.method == "merge-commit"
    assert forge.head_sha() == result.sha
    parents = git("log", "-1", "--format=%P|%an", result.sha, git_dir=bare)
    assert parents == f"{a} {b}|ali"
    assert forge.read_file("a.txt") == "1"
    assert forge.read_file("b.txt") == "2"


def test_bayat_dal_merge_edilmez_guncelle_ve_yeniden_ci(
    forge: LocalForge, bare: Path, artifacts: Path
) -> None:
    """GitHub strict status checks: kontroller yalnızca head'de koştu; base ilerlediyse merge yok.

    Bulgudaki senaryo: C1 PR'ı, C2 merge edilmeden önce dallanmış; local-ci yalnızca C1 head'inde
    başarılı. Merge, hiç test edilmemiş C1+C2 ağacını main'e koyardı.
    """
    assert forge.require_up_to_date is True  # varsayılan açık
    a = forge.commit_files("tp/a", {"a.txt": "1"}, "a")
    b = forge.commit_files("tp/b", {"b.txt": "2"}, "b")
    ci_green(artifacts, a)
    ci_green(artifacts, b)
    pr_a = forge.open_pr("tp/a", "A", "")
    pr_b = forge.open_pr("tp/b", "B", "")
    assert forge.merge_pr(pr_a.number, "ali") == a
    main = forge.head_sha()
    with pytest.raises(ForgeProtectionError, match="güncel değil"):
        forge.merge_pr(pr_b.number, "ali", expected_head_sha=b)
    assert forge.head_sha() == main  # main'e test edilmemiş birleşim girmedi
    assert forge.get_pr(pr_b.number).state == "open"

    # "Update branch": main → tp/b; yeni head, eski CI sonucu ona taşınmaz.
    new_head = forge.update_branch(pr_b.number, "tp-bot")
    assert new_head != b
    assert git("log", "-1", "--format=%P", new_head, git_dir=bare) == f"{b} {a}"
    assert forge.get_pr(pr_b.number).head_sha == new_head
    assert forge.get_pr_record(pr_b.number)["head_sha"] == new_head
    assert forge.update_branch(pr_b.number) == new_head  # idempotent: zaten güncel
    with pytest.raises(ForgeConflictError):  # onay eski head'e bağlı → yeniden onay
        forge.merge_pr(pr_b.number, "ali", expected_head_sha=b)
    with pytest.raises(ForgeProtectionError, match="local-ci"):  # yeni head'de CI yok
        forge.merge_pr(pr_b.number, "ali", expected_head_sha=new_head)
    ci_green(artifacts, new_head)
    result = forge.merge_pr_detailed(pr_b.number, "ali", expected_head_sha=new_head)
    # main'e giren commit tam olarak local-ci'nin koştuğu commit.
    assert (result.method, result.sha, result.bypass) == ("fast-forward", new_head, False)
    assert forge.head_sha() == new_head
    assert forge.read_file("a.txt") == "1" and forge.read_file("b.txt") == "2"


def test_bayat_dal_demo_admin_bypass_nedeni_kayitli(forge: LocalForge, artifacts: Path) -> None:
    a = forge.commit_files("tp/a", {"a.txt": "1"}, "a")
    b = forge.commit_files("tp/b", {"b.txt": "2"}, "b")
    ci_green(artifacts, a)
    ci_green(artifacts, b)
    forge.merge_pr(forge.open_pr("tp/a", "A", "").number, "ali")
    pr_b = forge.open_pr("tp/b", "B", "")
    result = forge.merge_pr_detailed(pr_b.number, "demo-admin")
    assert result.method == "merge-commit" and result.bypass is True
    assert "güncel değil" in (result.bypass_reason or "")
    assert forge.get_pr_record(pr_b.number)["bypass_reason"] == result.bypass_reason


def test_update_branch_kapali_ve_cakisan_pr(forge: LocalForge, artifacts: Path) -> None:
    a = forge.commit_files("tp/a", {"README.md": "# A\n"}, "a")
    b = forge.commit_files("tp/b", {"README.md": "# B\n"}, "b")
    ci_green(artifacts, a)
    forge.merge_pr(forge.open_pr("tp/a", "A", "").number, "ali")
    pr_b = forge.open_pr("tp/b", "B", "")
    with pytest.raises(ForgeConflictError, match=r"README\.md"):
        forge.update_branch(pr_b.number)
    assert forge.head_sha("tp/b") == b
    forge.close_pr(pr_b.number)
    with pytest.raises(ForgeStateError):
        forge.update_branch(pr_b.number)


def test_update_branch_beklenen_head_yabanci_commiti_reddeder(
    forge: LocalForge, artifacts: Path
) -> None:
    """PR kilidi altında: dala yabancı commit girdiyse güncelleme hiçbir şey yazmaz."""
    a = forge.commit_files("tp/a", {"a.txt": "1"}, "a")
    b = forge.commit_files("tp/b", {"b.txt": "2"}, "b")
    ci_green(artifacts, a)
    forge.merge_pr(forge.open_pr("tp/a", "A", "").number, "ali")
    pr_b = forge.open_pr("tp/b", "B", "")
    yabanci = forge.commit_files("tp/b", {"b.txt": "mallory"}, "foreign")
    with pytest.raises(ForgeStateError, match="beklenen head"):
        forge.update_branch(pr_b.number, "tp-bot", expected_head_sha=b)
    assert forge.head_sha("tp/b") == yabanci
    with pytest.raises(ForgeValidationError):
        forge.update_branch(pr_b.number, expected_head_sha="zz")
    yeni = forge.update_branch(pr_b.number, "tp-bot", expected_head_sha=yabanci)
    assert yeni != yabanci and forge.get_pr(pr_b.number).head_sha == yeni


def test_require_up_to_date_env(bare: Path, artifacts: Path) -> None:
    env = {"TP_FORGE_PATH": str(bare), "TP_ARTIFACTS_PATH": str(artifacts)}
    assert LocalForge.from_env(env).require_up_to_date is True
    assert (
        LocalForge.from_env({**env, "TP_FORGE_REQUIRE_UP_TO_DATE": "0"}).require_up_to_date is False
    )
    with pytest.raises(ForgeValidationError):
        LocalForge.from_env({**env, "TP_FORGE_REQUIRE_UP_TO_DATE": "belki"})


def test_merge_cakisma_reddedilir(forge: LocalForge, artifacts: Path) -> None:
    forge.require_up_to_date = False  # çakışma denetimini doğrudan merge yolunda sına
    a = forge.commit_files("tp/a", {"README.md": "# A\n"}, "a")
    b = forge.commit_files("tp/b", {"README.md": "# B\n"}, "b")
    ci_green(artifacts, a)
    ci_green(artifacts, b)
    forge.merge_pr(forge.open_pr("tp/a", "A", "").number, "ali")
    main = forge.head_sha()
    pr_b = forge.open_pr("tp/b", "B", "")
    with pytest.raises(ForgeConflictError, match=r"README\.md"):
        forge.merge_pr(pr_b.number, "ali")
    assert forge.head_sha() == main
    assert forge.get_pr(pr_b.number).state == "open"


def test_merge_demo_admin_bypass_kaydedilir(forge: LocalForge) -> None:
    head = forge.commit_files("demo/break-locator", {"README.md": "# kirik\n"}, "k")
    pr = forge.open_pr("demo/break-locator", "Kırılma", "")
    result = forge.merge_pr_detailed(pr.number, "demo-admin")
    assert result.bypass is True
    assert "demo-admin" in (result.bypass_reason or "")
    assert forge.head_sha() == head
    rec = forge.get_pr_record(pr.number)
    assert rec["bypass"] is True
    assert rec["merged_by"] == "demo-admin"


def test_merge_zaten_icerilen_dal(forge: LocalForge, artifacts: Path) -> None:
    head = forge.commit_files("tp/a", {"a.txt": "1"}, "a")
    ci_green(artifacts, head)
    forge.commit_files("tp/b", {"a.txt": "1"}, "a")  # aynı ağaç → aynı commit değil, ayrı dal
    pr_a = forge.open_pr("tp/a", "A", "")
    pr_b = forge.open_pr("tp/b", "B", "")
    forge.merge_pr(pr_a.number, "ali")
    # tp/b'nin içeriği main'de ama dal bayat → önce güncellenir, yeni head'de CI koşar
    ci_green(artifacts, forge.update_branch(pr_b.number))
    result = forge.merge_pr_detailed(pr_b.number, "ali")
    assert result.method in {"fast-forward", "already-merged"}
    assert forge.read_file("a.txt") == "1"


# ---------------------------------------------------------------------- checks


def test_checks_yok_liste_sozluk_ve_bozuk(forge: LocalForge, artifacts: Path) -> None:
    sha = forge.head_sha()
    assert forge.checks(sha) == []
    write_checks(artifacts, sha, {"checks": [{"name": "local-ci", "status": "in_progress"}]})
    assert [(c.name, c.status) for c in forge.checks(sha)] == [("local-ci", "in_progress")]
    write_checks(
        artifacts, sha, {"name": "local-ci", "status": "completed", "conclusion": "success"}
    )
    assert forge.checks("main")[0].conclusion == "success"
    (artifacts / "checks" / f"{sha}.json").write_text("{bozuk")
    with pytest.raises(ForgeError):
        forge.checks(sha)
    write_checks(artifacts, sha, [{"name": "local-ci", "status": "bilinmez"}])
    with pytest.raises(ForgeError):
        forge.checks(sha)


def test_checks_artifacts_yoksa_bos(bare: Path) -> None:
    f = LocalForge(bare, None)
    assert f.checks(f.head_sha()) == []


def test_checks_ayri_kapi_dizininden_okunur(bare: Path, artifacts: Path, tmp_path: Path) -> None:
    """TP_CHECKS_PATH (tp_checks volume'ü) verilince kapı `<checks>/<sha>.json`'dan okunur;
    `<artifacts>/checks` (test-runner'ın yazabildiği yer) yok sayılır."""
    kapi = tmp_path / "kapi"
    kapi.mkdir()
    f = get_forge(
        {
            "TP_FORGE": "local",
            "TP_FORGE_PATH": str(bare),
            "TP_ARTIFACTS_PATH": str(artifacts),
            "TP_CHECKS_PATH": str(kapi),
        }
    )
    assert isinstance(f, LocalForge)
    sha = f.head_sha()
    write_checks(
        artifacts, sha, {"name": "local-ci", "status": "completed", "conclusion": "success"}
    )
    assert f.checks(sha) == []
    (kapi / f"{sha}.json").write_text(
        json.dumps(
            {"checks": [{"name": "local-ci", "status": "completed", "conclusion": "failure"}]}
        )
    )
    assert [c.conclusion for c in f.checks(sha)] == ["failure"]


# ---------------------------------------------------------------------- fabrika


def test_get_forge_local(bare: Path, artifacts: Path) -> None:
    f = get_forge(
        {"TP_FORGE": "local", "TP_FORGE_PATH": str(bare), "TP_ARTIFACTS_PATH": str(artifacts)}
    )
    assert isinstance(f, LocalForge)
    assert f.head_sha() == git("rev-parse", "main", git_dir=bare)
    assert isinstance(get_forge({"TP_FORGE_PATH": str(bare)}), LocalForge)


def test_get_forge_bilinmeyen() -> None:
    with pytest.raises(ForgeValidationError):
        get_forge({"TP_FORGE": "gitlab"})


# ------------------------------------------------- onaylanan head / zorunlu kontroller


def test_merge_onaylanan_head_ilerlediyse_reddedilir(forge: LocalForge, artifacts: Path) -> None:
    approved = forge.commit_files("tp/m", {"a.txt": "1"}, "m")
    ci_green(artifacts, approved)
    pr = forge.open_pr("tp/m", "t", "b")
    main = forge.head_sha()
    # onaydan sonra fix turu aynı dala commit attı; yeni commit de yeşil
    moved = forge.commit_files("tp/m", {"a.txt": "2"}, "fix turu")
    ci_green(artifacts, moved)
    with pytest.raises(ForgeConflictError, match="onaylanandan farklı"):
        forge.merge_pr(pr.number, "ali", expected_head_sha=approved)
    assert forge.head_sha() == main
    assert forge.get_pr(pr.number).state == "open"
    # bypass yetkisi de onaylanmamış içeriği merge ettirmez
    with pytest.raises(ForgeConflictError):
        forge.merge_pr(pr.number, "demo-admin", expected_head_sha=approved)
    with pytest.raises(ForgeValidationError):
        forge.merge_pr(pr.number, "ali", expected_head_sha="tp/m")
    assert forge.merge_pr(pr.number, "ali", expected_head_sha=moved) == moved
    assert forge.read_file("a.txt") == "2"


def test_zorunlu_kontroller_yapilandirilabilir(bare: Path, artifacts: Path) -> None:
    forge = LocalForge(bare, artifacts, required_checks=("local-ci", "ast-guard"))
    head = forge.commit_files("tp/m", {"a.txt": "1"}, "m")
    pr = forge.open_pr("tp/m", "t", "b")
    ci_green(artifacts, head)
    with pytest.raises(ForgeProtectionError, match="'ast-guard' durumu: yok"):
        forge.merge_pr(pr.number, "ali")
    write_checks(
        artifacts,
        head,
        [
            {"name": "local-ci", "status": "completed", "conclusion": "success"},
            {"name": "ast-guard", "status": "completed", "conclusion": "failure"},
            {"name": "ast-guard", "status": "completed", "conclusion": "success"},  # yeniden koşu
        ],
    )
    result = forge.merge_pr_detailed(pr.number, "ali", expected_head_sha=head)
    assert result.bypass is False
    with pytest.raises(ForgeValidationError):
        LocalForge(bare, artifacts, required_checks=())


def _check(name: str, conclusion: str) -> dict[str, str]:
    return {"name": name, "status": "completed", "conclusion": conclusion}


def test_platform_kapisi_kayitli_uygulama_kontrolu_zorunlu(
    forge: LocalForge, artifacts: Path
) -> None:
    """009 §2.7: web PR'ında davranış aynı; kayıtlı kırmızı local-ci-android merge'i durdurur."""
    head = forge.commit_files("tp/w", {"web/src/x.ts": "1"}, "w")
    pr = forge.open_pr("tp/w", "t", "b")
    write_checks(
        artifacts,
        head,
        {"checks": [_check("local-ci", "success"), _check("local-ci-android", "failure")]},
    )
    with pytest.raises(ForgeProtectionError, match="'local-ci-android' durumu: failure"):
        forge.merge_pr(pr.number, "ali")
    write_checks(
        artifacts,
        head,
        {"checks": [_check("local-ci", "success"), _check("local-ci-android", "success")]},
    )
    assert forge.merge_pr(pr.number, "ali", expected_head_sha=head) == head


def test_platform_kapisi_yalniz_e2e_app_degisikligi(forge: LocalForge, artifacts: Path) -> None:
    """Yalnızca e2e-app/ değişen PR: web local-ci gerekmez, en az bir platform kontrolü gerekir."""
    head = forge.commit_files(
        "tp/case-a", {"e2e-app/src/test/java/a/XTest.java": "class XTest {}"}, "a"
    )
    pr = forge.open_pr("tp/case-a", "t", "b")
    ci_green(artifacts, head)  # yalnızca web yeşili yetmez
    with pytest.raises(ForgeProtectionError, match="en az bir uygulama kontrolü"):
        forge.merge_pr(pr.number, "ali")
    # Kaydedilmiş kırmızı web kontrolü yine durdurur (simetri).
    write_checks(
        artifacts,
        head,
        {"checks": [_check("local-ci", "failure"), _check("local-ci-ios", "success")]},
    )
    with pytest.raises(ForgeProtectionError, match="'local-ci' durumu: failure"):
        forge.merge_pr(pr.number, "ali")
    write_checks(artifacts, head, {"checks": [_check("local-ci-ios", "success")]})
    result = forge.merge_pr_detailed(pr.number, "ali", expected_head_sha=head)
    assert result.bypass is False and result.sha == head


def test_platform_kapisi_karisik_degisiklik_iki_kontrol(forge: LocalForge, artifacts: Path) -> None:
    head = forge.commit_files(
        "tp/k", {"e2e-app/src/test/java/a/XTest.java": "x", "e2e/tests/a.spec.ts": "y"}, "k"
    )
    pr = forge.open_pr("tp/k", "t", "b")
    write_checks(artifacts, head, {"checks": [_check("local-ci-android", "success")]})
    with pytest.raises(ForgeProtectionError, match="'local-ci' durumu: yok"):
        forge.merge_pr(pr.number, "ali")
    ci_green(artifacts, head)
    with pytest.raises(ForgeProtectionError, match="en az bir uygulama kontrolü"):
        forge.merge_pr(pr.number, "ali")
    # demo-admin bypass'ı nedenleri kayda yazar.
    result = forge.merge_pr_detailed(pr.number, "demo-admin", expected_head_sha=head)
    assert result.bypass is True and "uygulama kontrolü" in (result.bypass_reason or "")


def test_zorunlu_kontroller_ortamdan(bare: Path, artifacts: Path) -> None:
    forge = LocalForge.from_env(
        {
            "TP_FORGE_PATH": str(bare),
            "TP_ARTIFACTS_PATH": str(artifacts),
            "TP_REQUIRED_CHECKS": "local-ci, local-ci-android",
        }
    )
    assert forge.required_checks == ("local-ci", "local-ci-android")
    assert LocalForge.from_env(
        {"TP_FORGE_PATH": str(bare), "TP_ARTIFACTS_PATH": str(artifacts)}
    ).required_checks == ("local-ci",)


# ---------------------------------------------------------------- demo yönetimi


def test_archive_alt_dizin(forge: LocalForge) -> None:
    import io
    import tarfile

    data = forge.archive("main", "web")
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        names = [m.name for m in tar.getmembers() if m.isfile()]
        assert names == ["src/Catalog.tsx"]
        extracted = tar.extractfile("src/Catalog.tsx")
        assert extracted is not None and extracted.read().decode() == CATALOG
    with pytest.raises(ForgeNotFoundError):
        forge.archive("main", "README.md")  # dizin değil
    with pytest.raises(ForgeValidationError):
        forge.archive("main", "../x")


def test_reset_branch_yalnizca_demo_admin(forge: LocalForge) -> None:
    base = forge.head_sha("demo-baseline")
    head = forge.commit_files("demo/break-locator", {"README.md": "# kirik\n"}, "k")
    forge.merge_pr(forge.open_pr("demo/break-locator", "K", "").number, "demo-admin")
    assert forge.head_sha() == head
    with pytest.raises(ForgeProtectionError):
        forge.reset_branch("main", "demo-baseline", actor="ali")
    assert forge.reset_branch("main", "demo-baseline", actor="demo-admin") == (head, base)
    assert forge.head_sha() == base
    assert forge.reset_branch("main", "demo-baseline", actor="demo-admin") == (base, base)


def test_changed_paths(forge: LocalForge) -> None:
    a = forge.commit_files("tp/a", {"a.txt": "1", "b.txt": "2"}, "a")
    b = forge.commit_files("tp/a", {"b.txt": "3", "c.txt": "4"}, "b", base="tp/a")
    assert forge.changed_paths(a, b) == ["b.txt", "c.txt"]
    assert forge.changed_paths(b, b) == []


# ------------------------------------------------- K-T11 uçtan uca (MİM-D7, MİM-O1)

JAVA_WEB_TEST = "e2e-java/src/test/java/com/antreklabs/bayi/LoginTest.java"


def _main_e_ekle(forge: LocalForge, dosyalar: dict[str, str]) -> str:
    """main'e (korunan dal) test kurulum commit'i: dal + PR + demo-admin merge."""
    forge.commit_files("tp/kurulum", dosyalar, "kurulum")
    pr = forge.open_pr("tp/kurulum", "kurulum", "b")
    return forge.merge_pr(pr.number, "demo-admin")


def _ci_dilleri(forge: LocalForge, pr_no: int, head: str, monkeypatch: pytest.MonkeyPatch) -> tuple:
    """CI'ın script'siz PR koşusunda seçeceği web dilleri (`ci.service._web_dilleri`)."""
    from tp_core.features.ci import service as ci_service
    from tp_core.features.ci import services
    from tp_core.models import Run

    monkeypatch.setenv("TP_FORGE_APP_ROOT", "")
    run = Run(ortam={}, tetik="pr", pr_no=pr_no, commit=head)
    with services.override(forge=lambda: forge):
        return ci_service._web_dilleri(run)


def test_k_t11_uygulama_pr_repoda_iki_dil_iki_check_ister(
    forge: LocalForge, artifacts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MİM-D7: repoda TS + Java web testi; uygulama kodu PR'ı → CI iki dili koşar, kapı iki
    check'i ister; yalnız local-ci yeşili yetmez, ikisi yeşilken merge açılır."""
    _main_e_ekle(
        forge,
        {"e2e/tests/login.spec.ts": "test('x', () => {});", JAVA_WEB_TEST: "class LoginTest {}"},
    )
    head = forge.commit_files("tp/uyg", {"web/src/App.tsx": "export {};"}, "uygulama")
    pr = forge.open_pr("tp/uyg", "uygulama", "b")
    assert _ci_dilleri(forge, pr.number, head, monkeypatch) == ("ts", "java")
    ci_green(artifacts, head)
    with pytest.raises(ForgeProtectionError, match="'local-ci-web-java' durumu: yok"):
        forge.merge_pr(pr.number, "ali")
    write_checks(
        artifacts,
        head,
        {"checks": [_check("local-ci", "success"), _check("local-ci-web-java", "success")]},
    )
    sonuc = forge.merge_pr_detailed(pr.number, "ali", expected_head_sha=head)
    assert sonuc.bypass is False


def test_k_t11_repoda_yalniz_java_uygulama_pr_kilitlenmez(
    forge: LocalForge, artifacts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MİM-O1: repoda `e2e/tests/*.spec.ts` yok, yalnız e2e-java testi; uygulama PR'ında CI
    yalnız java koşar → kapı yalnız `local-ci-web-java` ister (local-ci beklenmez)."""
    _main_e_ekle(forge, {JAVA_WEB_TEST: "class LoginTest {}"})
    head = forge.commit_files("tp/uyg", {"web/src/App.tsx": "export {};"}, "uygulama")
    pr = forge.open_pr("tp/uyg", "uygulama", "b")
    assert _ci_dilleri(forge, pr.number, head, monkeypatch) == ("java",)
    write_checks(artifacts, head, {"checks": [_check("local-ci-web-java", "success")]})
    assert forge.merge_pr_detailed(pr.number, "ali", expected_head_sha=head).bypass is False


def test_k_t11_ortak_ata_yoksa_kapi_kapali(forge: LocalForge, artifacts: Path) -> None:
    """GÜV: PR dalının main ile ortak atası yok (fark bilinmiyor) → kapı kapalı tarafa düşer:
    her iki tam hat dilinin check'i zorunlu."""
    # Yetim dal: main ile ortak geçmişi olmayan commit.
    work = artifacts.parent / "yetim"
    git("init", "-q", "-b", "yetim", str(work))
    (work / "README.md").write_text("yetim\n")
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "yetim", cwd=work)
    git("push", "-q", str(forge.path), "yetim:tp/yetim", cwd=work)
    head = forge.head_sha("tp/yetim")
    pr = forge.open_pr("tp/yetim", "yetim", "b")
    ci_green(artifacts, head)
    with pytest.raises(ForgeProtectionError, match="'local-ci-web-java' durumu: yok"):
        forge.merge_pr(pr.number, "ali", expected_head_sha=head)
