"""GitHub kipi demo kırılması / sıfırlaması: insan kimliği, PR + bypass merge, baseline ağacı.

Sahte GitHub deposu (`github_repo_fake`, httpx MockTransport) uçtan uca: dal, commit, PR, merge
ve ruleset benzetimi. Bot token'ı hiçbir yazma işleminde kullanılmamalıdır.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import httpx
import pytest

from tests.unit.integrations.github_repo_fake import (
    BOT_TOKEN,
    HUMAN_LOGIN,
    HUMAN_TOKEN,
    REPO,
    FakeGitHubRepo,
)
from tp_core.features.demo import web
from tp_core.integrations import forge_demo
from tp_core.integrations.forge import ForgeError, ForgeProtectionError
from tp_core.integrations.forge_github import GitHubForge, TokenAuth

WEB = "demo-app/web/src/pages/CatalogPage.tsx"
E2E = "demo-app/e2e/pages/catalog/locators.ts"


class FakeAudit:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str | None, dict[str, Any]]] = []

    def append(self, aktor: str, eylem: str, nesne: str | None, ozet: Mapping[str, Any]) -> int:
        self.rows.append((aktor, eylem, nesne, dict(ozet)))
        return len(self.rows)


@pytest.fixture(autouse=True)
def _temiz(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(forge_demo.APP_ROOT_ENV, raising=False)
    forge_demo.clear_cache()
    yield
    forge_demo.clear_cache()


@pytest.fixture
def gh() -> FakeGitHubRepo:
    return FakeGitHubRepo()


def _forge(gh: FakeGitHubRepo, *, merge: bool = True) -> GitHubForge:
    return GitHubForge(
        REPO,
        TokenAuth(BOT_TOKEN),
        merge_auth=TokenAuth(HUMAN_TOKEN) if merge else None,
        transport=httpx.MockTransport(gh),
    )


@pytest.fixture
def forge(gh: FakeGitHubRepo) -> GitHubForge:
    return _forge(gh)


def test_testid_durumu_agactan_okunur_arama_kullanilmaz(
    gh: FakeGitHubRepo, forge: GitHubForge
) -> None:
    assert forge_demo.app_root_for(forge) == "demo-app"
    assert forge_demo.testid_state(forge, "main") == forge_demo.OLD_TESTID
    assert forge_demo.e2e_testid_state(forge, "main") == forge_demo.OLD_TESTID
    assert not [c for c in gh.calls if c[1] == "/search/code"]


def test_kirilma_insan_kimligiyle_pr_ve_bypass_merge(
    gh: FakeGitHubRepo, forge: GitHubForge
) -> None:
    audit = FakeAudit()
    ci: list[tuple[str, str]] = []
    before = gh.refs["heads/main"]

    out = forge_demo.demo_break(forge, audit, ci=lambda sha, actor: ci.append((sha, actor)) or "r1")

    assert out.changed is True and out.testid == forge_demo.NEW_TESTID
    after = gh.refs["heads/main"]
    assert out.main_before == before and out.main_after == after != before
    files = gh.files_at("main")
    assert '"cart-add"' in files[WEB] and "add-to-cart" not in files[WEB]
    assert files[E2E] == gh.files_at(before)[E2E]  # test tarafı değişmez (onarım ayrı PR)
    # Bot hiçbir şey yazmadı; dal, commit, PR ve merge insan kimliğiyle.
    assert gh.writes_by(BOT_TOKEN) == []
    yazmalar = [p for _m, p in gh.writes_by(HUMAN_TOKEN)]
    assert any(p.endswith("/git/commits") for p in yazmalar)
    assert any(p.endswith("/pulls") for p in yazmalar)
    assert any(p.endswith("/merge") for p in yazmalar)
    pr = gh.prs[out.pr_number or 0]
    assert pr["author"] == HUMAN_LOGIN and pr["merged_by"] == HUMAN_LOGIN
    assert pr["branch"] == f"{forge_demo.BREAK_BRANCH}-{before[:12]}"
    assert "insan kimliğiyle" in pr["body"] and pr["labels"] == ["demo"]
    assert ci == [(after, "demo-admin")]
    (aktor, eylem, nesne, ozet), = audit.rows  # fmt: skip
    assert (aktor, eylem, nesne) == ("demo-admin", forge_demo.AUDIT_BREAK, f"pr:{out.pr_number}")
    assert ozet["bypass"] is True and ozet["kimlik"]["github_login"] == HUMAN_LOGIN
    assert ozet["github_merge_eden"] == HUMAN_LOGIN
    assert ozet["fark"]["dosyalar"] == [WEB] and ozet["fark"]["degisen_satir"] == 1

    # İdempotent: ikinci istek forge'a yazmaz, denetime eklemez.
    n = len(gh.calls)
    again = forge_demo.demo_break(forge, audit)
    assert again.changed is False and len(audit.rows) == 1
    assert all(m == "GET" for m, _p, _t in gh.calls[n:])


def test_merge_tokeni_yoksa_kirilma_reddedilir_ve_hicbir_sey_yazilmaz(gh: FakeGitHubRepo) -> None:
    with pytest.raises(ForgeProtectionError, match="GITHUB_MERGE_TOKEN"):
        forge_demo.demo_break(_forge(gh, merge=False), FakeAudit())
    with pytest.raises(ForgeProtectionError, match="GITHUB_MERGE_TOKEN"):
        forge_demo.demo_baseline(_forge(gh, merge=False), FakeAudit())
    assert [c for c in gh.calls if c[0] != "GET"] == []


def test_bypass_yetkisi_olmayan_insan_merge_edemez(gh: FakeGitHubRepo, forge: GitHubForge) -> None:
    """Token sahibi demo-admin takımında değilse GitHub ruleset'i merge'ü reddeder."""
    gh.bypass_tokens.clear()
    before = gh.refs["heads/main"]
    with pytest.raises(ForgeProtectionError):
        forge_demo.demo_break(forge, FakeAudit())
    assert gh.refs["heads/main"] == before


def _onarim_merge(gh: FakeGitHubRepo, forge: GitHubForge) -> None:
    """Bot onarım PR'ı açar (yalnızca testId), insan merge eder."""
    yeni = gh.files_at("main")[E2E].replace("add-to-cart", "cart-add")
    forge.commit_files("tp/repair-x", {E2E: yeni}, "onarım")
    pr = forge.open_pr("tp/repair-x", "Locator onarımı", "gövde", ("tp-repair",))
    forge.merge_pr_detailed(pr.number, "demo-admin", expected_head_sha=pr.head_sha)


def test_sifirlama_baseline_agacini_pr_ile_geri_getirir(
    gh: FakeGitHubRepo, forge: GitHubForge
) -> None:
    audit = FakeAudit()
    baseline = gh.refs["tags/demo-baseline"]
    forge_demo.demo_break(forge, audit)
    _onarim_merge(gh, forge)
    assert (
        forge_demo.locator_durumu(
            forge_demo.testid_state(forge, "main"), forge_demo.e2e_testid_state(forge, "main")
        )
        == "onarildi"
    )
    kirik_main = gh.refs["heads/main"]
    yazan_bot = len(gh.writes_by(BOT_TOKEN))

    ci: list[str] = []
    out = forge_demo.demo_baseline(forge, audit, ci=lambda sha, _a: ci.append(sha) or "r")

    assert out.changed is True
    main = gh.refs["heads/main"]
    assert gh.files_at(main) == gh.files_at(baseline)  # ağaç birebir baseline
    assert kirik_main in gh.ancestors(main)  # geçmiş korunur (force-push yok)
    assert len(gh.writes_by(BOT_TOKEN)) == yazan_bot  # sıfırlama bot kimliği kullanmaz
    pr = gh.prs[out.pr_number or 0]
    assert pr["author"] == HUMAN_LOGIN and pr["merged_by"] == HUMAN_LOGIN
    assert pr["branch"] == f"{forge_demo.RESET_BRANCH}-{kirik_main[:12]}"
    assert ci == [main]
    ozet = audit.rows[-1][3]
    assert audit.rows[-1][1] == forge_demo.AUDIT_BASELINE
    assert ozet["yontem"] == "baseline-agaci-pr" and ozet["hedef_sha"] == baseline
    assert ozet["main_agac_sonra"] == ozet["hedef_agac"]
    assert forge_demo.main_is_baseline(forge, main, baseline) is True
    assert out.testid == forge_demo.OLD_TESTID

    # İdempotent: ağaç zaten baseline.
    assert forge_demo.demo_baseline(forge, audit).changed is False
    # Sıfırlamadan sonra yeniden kırılabilir (yeni main → yeni dal adı).
    tekrar = forge_demo.demo_break(forge, audit)
    assert tekrar.changed is True and tekrar.testid == forge_demo.NEW_TESTID


def test_baseline_etiketi_yoksa_acik_hata() -> None:
    gh = FakeGitHubRepo(baseline_tag=False)
    with pytest.raises(ForgeError, match=r"github-demo-repo-init\.sh"):
        forge_demo.demo_baseline(_forge(gh), FakeAudit())


def test_kirilma_dali_dogrulanir_baska_degisiklik_merge_edilmez(
    gh: FakeGitHubRepo, forge: GitHubForge
) -> None:
    """Açık kırılma PR'ının dalı kurcalanmışsa (testid dışı değişiklik) bypass ile merge edilmez.

    (Dal var ama PR yoksa ürün kendi commit'ini üstüne yazar ve doğrulanan NET fark yine yalnızca
    testid'dir; merge edilen de odur.)"""
    before = gh.refs["heads/main"]
    dal = f"{forge_demo.BREAK_BRANCH}-{before[:12]}"
    human = forge.human_forge()
    kurcali = gh.files_at("main")[WEB].replace("add-to-cart", "cart-add") + "// ek\n"
    human.commit_files(dal, {WEB: kurcali}, "kurcalanmış")
    human.open_pr(dal, "kurcalanmış", "gövde")
    with pytest.raises(ForgeError, match="satır ekliyor"):
        forge_demo.demo_break(forge, FakeAudit())
    assert gh.refs["heads/main"] == before and gh.prs[1]["merged"] is False


def test_tree_sha_ve_web_state_uygulama_koku(gh: FakeGitHubRepo, forge: GitHubForge) -> None:
    main = gh.refs["heads/main"]
    agac = forge.tree_sha(main, "demo-app/web")
    assert agac and forge.tree_sha(main, "demo-app/yok") is None
    assert forge.tree_sha(main, "demo-app/web/Dockerfile") is None  # dizin değil
    ws = forge_demo.web_state(forge, build_json={"sha": "f" * 40, "web_tree": agac}, sha_file=None)
    assert ws["guncel"] is True and ws["main_web_tree"] == agac


def test_uygulama_eslesmesi_github_uygulama_kokunu_bilir(
    gh: FakeGitHubRepo, forge: GitHubForge
) -> None:
    once = gh.refs["heads/main"]
    forge_demo.demo_break(forge, FakeAudit())
    sonra = gh.refs["heads/main"]
    ok, neden = web.uygulama_eslesiyor(forge, sonra, once)
    assert ok is False and "web" in neden
    _onarim_merge(gh, forge)  # yalnızca e2e değişir: uygulama aynı
    ok, neden = web.uygulama_eslesiyor(forge, gh.refs["heads/main"], sonra)
    assert ok is True, neden


def test_list_prs(gh: FakeGitHubRepo, forge: GitHubForge) -> None:
    forge_demo.demo_break(forge, FakeAudit())
    forge.commit_files("tp/case-1", {"demo-app/e2e/tests/generated/a.spec.ts": "x\n"}, "m")
    acik = forge.open_pr("tp/case-1", "case", "gövde")
    assert [p.number for p in forge.list_prs("open")] == [acik.number]
    assert [p.state for p in forge.list_prs("merged")] == ["merged"]
    assert len(forge.list_prs()) == 2


def test_cli_status_github(
    gh: FakeGitHubRepo, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    import json

    monkeypatch.setattr(forge_demo, "get_forge", lambda _env=None: _forge(gh))
    assert forge_demo.main(["status"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["kip"] == "github" and out["web_yolu"] == "demo-app/web"
    assert out["main_baseline_mi"] is True and out["testid"] == forge_demo.OLD_TESTID


def test_commit_tree_korunan_dal_ve_idempotent(gh: FakeGitHubRepo, forge: GitHubForge) -> None:
    from tp_core.integrations.forge import ForgeValidationError

    human = forge.human_forge()
    main = gh.refs["heads/main"]
    agac = forge.tree_sha(main)
    assert agac is not None
    with pytest.raises(ForgeProtectionError):
        human.commit_tree("main", agac, "m", main)
    with pytest.raises(ForgeValidationError):
        human.commit_tree("demo/x", "kisa", "m", main)
    ilk = human.commit_tree("demo/x", agac, "m", main)
    n = len(gh.calls)
    assert human.commit_tree("demo/x", agac, "m", main) == ilk  # aynı ağaç + ebeveyn: yazmaz
    assert all(m == "GET" for m, _p, _t in gh.calls[n:])
    assert gh.commits[ilk]["author"] == HUMAN_LOGIN
