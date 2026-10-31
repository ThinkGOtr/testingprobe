"""GitHubForge'un `update_branch` / `close_pr`'ı kod üretiminin GERÇEK yolundan (gerçek Postgres).

Senaryo (Demo-B çoklu PR, GitHub kipi): iki bot PR açık; birincisi GitHub arayüzünde merge
edilir → PR senkronu (`sync_prs`) diğer PR'ı "main'in gerisinde" işaretler ve
`codegen.update_branch` işini açar → iş GitHubForge.update_branch ile dalı günceller (yeni head
core'dan gelir, PR CI yeni head'de, kırarak doğrulama sıfırlanır) → ikinci PR yeni head'iyle
merge edilince "yabancı head" SAYILMAZ (`kabul`). İnsan reddi ise PR'ı GitHub'da kapatır.

Kod üretimi (commit/PR açma) codegen şeridinin sahte forge'uyla yapılır; dal güncelleme, kapatma
ve senkron gerçek `GitHubForge` + httpx MockTransport (durumlu sahte GitHub REST) ile koşar.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.unit.features.codegen.conftest import (  # noqa: F401  (pytest fikstürleri)
    api,
    ci_cagrilari,
    codegen,
    demo_bare,
    forge_dirs,
    hazir,
    login,
    make_requirement,
    run_jobs,
)
from tests.unit.features.codegen.test_flow import github_kipi, script_of, uret
from tp_core.features.codegen import service
from tp_core.integrations.forge_github import GitHubForge, TokenAuth
from tp_core.models import PullRequest, session_scope
from tp_core.workflow.service import Principal

REPO = "acme/demo-app"
R = f"/repos/{REPO}"


@dataclass
class _Pr:
    number: int
    branch: str
    head: str
    state: str = "open"
    merged: bool = False
    merge_sha: str | None = None
    merged_by: str | None = None


@dataclass
class DurumluGitHub:
    """Dal güncelleme / kapatma / senkron ve okuma (commit, contents, git ağacı) uçları.

    Her commit `(ebeveynler, dosyalar)`; GitHub'ın asenkron update-branch'i (202 → head biraz
    sonra değişir) `gecikme` ile taklit edilir."""

    main: str
    commits: dict[str, tuple[list[str], dict[str, str]]]
    prs: dict[int, _Pr] = field(default_factory=dict)
    istekler: list[tuple[str, str, Any]] = field(default_factory=list)
    bekleyen: dict[int, tuple[str, int]] = field(default_factory=dict)
    gecikme: int = 1

    def commit(self, parents: list[str], files: dict[str, str], sha: str | None = None) -> str:
        sha = sha or uuid.uuid4().hex + "abcdef01"  # 40 hane hex
        self.commits[sha] = (parents, dict(files))
        return sha

    def pr_json(self, p: _Pr) -> dict[str, Any]:
        return {
            "number": p.number,
            "state": "open" if p.state == "open" else "closed",
            "merged": p.merged,
            "merged_at": "2026-10-31T10:00:00Z" if p.merged else None,
            "merge_commit_sha": p.merge_sha,
            "merged_by": {"login": p.merged_by} if p.merged_by else None,
            "title": "TP üretilen test",
            "body": "",
            "head": {"ref": p.branch, "sha": p.head},
            "base": {"ref": "main", "sha": self.main},
            "html_url": f"https://github.com/{REPO}/pull/{p.number}",
            "labels": [],
        }

    def _birlesim(self, a: str, b: str) -> dict[str, str]:
        return {**self.commits[a][1], **self.commits[b][1]}

    def merge_github_arayuzunde(self, number: int, kim: str = "muhendis-gh") -> str:
        p = self.prs[number]
        sha = self.commit([self.main, p.head], self._birlesim(self.main, p.head))
        self.main = sha
        p.state, p.merged, p.merge_sha, p.merged_by = "merged", True, sha, kim
        return sha

    def _ata(self, p: _Pr) -> bool:
        """main, PR head'inin atası mı (dal güncel mi)?"""
        gorulen, yigin = set(), [p.head]
        while yigin:
            c = yigin.pop()
            if c == self.main:
                return True
            if c not in gorulen:
                gorulen.add(c)
                yigin.extend(self.commits[c][0])
        return False

    def _coz(self, ref: str) -> str:
        return self.main if ref == "main" else ref

    def __call__(self, req: httpx.Request) -> httpx.Response:
        yol, govde = req.url.path, json.loads(req.content) if req.content else None
        self.istekler.append((req.method, yol, govde))
        parca = yol.removeprefix(R).strip("/").split("/")
        yok = httpx.Response(404, json={"message": "Not Found"})
        if parca[0] == "pulls" and len(parca) >= 2:
            p = self.prs.get(int(parca[1]))
            if p is None:
                return yok
            if req.method == "GET" and len(parca) == 2:
                if p.number in self.bekleyen:  # asenkron güncelleme: önce eski head görünür
                    yeni, kalan = self.bekleyen[p.number]
                    if kalan <= 0:
                        p.head = yeni
                        del self.bekleyen[p.number]
                    else:
                        self.bekleyen[p.number] = (yeni, kalan - 1)
                return httpx.Response(200, json=self.pr_json(p))
            if req.method == "PATCH" and len(parca) == 2:
                if govde.get("state") == "closed":
                    p.state = "closed"
                return httpx.Response(200, json=self.pr_json(p))
            if req.method == "PUT" and parca[2:] == ["update-branch"]:
                if govde.get("expected_head_sha") != p.head:
                    return httpx.Response(
                        422, json={"message": "expected head sha didn't match current head ref."}
                    )
                yeni = self.commit([p.head, self.main], self._birlesim(self.main, p.head))
                self.bekleyen[p.number] = (yeni, self.gecikme)
                return httpx.Response(202, json={"message": "Updating pull request branch."})
        if parca[0] == "issues" and parca[2:] == ["comments"] and req.method == "POST":
            return httpx.Response(201, json={"id": len(self.istekler), "body": govde["body"]})
        if req.method != "GET":
            return yok
        if parca[0] == "compare":
            base, head = "/".join(parca[1:]).split("...")
            if base != "main":  # değişen dosya listesi (codegen güncelleme içerik doğrulaması)
                a = self.commits.get(self._coz(base), ([], {}))[1]
                b = self.commits.get(self._coz(head), ([], {}))[1]
                dosyalar = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
                return httpx.Response(200, json={"files": [{"filename": k} for k in dosyalar]})
            p = next(x for x in self.prs.values() if x.head == head)
            return httpx.Response(200, json={"behind_by": 0 if self._ata(p) else 1})
        if parca[0] == "commits":
            sha = self._coz(parca[1])
            if sha not in self.commits:
                return yok
            ebeveyn = self.commits[sha][0]
            return httpx.Response(200, json={"sha": sha,
                                             "parents": [{"sha": e} for e in ebeveyn]})  # fmt: skip
        if parca[0] == "contents":
            ref = self._coz(req.url.params.get("ref", "main"))
            icerik = self.commits.get(ref, ([], {}))[1].get("/".join(parca[1:]))
            if icerik is None:
                return yok
            return httpx.Response(200, json={
                "type": "file", "encoding": "base64",
                "content": base64.b64encode(icerik.encode()).decode()})  # fmt: skip
        if parca[:2] == ["git", "commits"]:
            return httpx.Response(200, json={"sha": parca[2], "tree": {"sha": parca[2]}})
        if parca[:2] == ["git", "trees"]:
            dosyalar = self.commits[parca[2]][1]
            return httpx.Response(200, json={"truncated": False, "tree": [
                {"path": y, "type": "blob"} for y in sorted(dosyalar)]})  # fmt: skip
        return yok


@pytest.fixture
def muhendis(api: TestClient, make_user: Any) -> Principal:  # noqa: F811
    u = make_user("engineer")
    login(api, u)
    return u


@pytest.fixture
def github(
    api: TestClient,  # noqa: F811
    engine: Engine,
    codegen: Any,  # noqa: F811
    hazir: dict[str, Any],  # noqa: F811
    muhendis: Principal,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[DurumluGitHub, GitHubForge, list[uuid.UUID]]]:
    """İki açık bot PR (GitHub kipi) + o PR'ları bilen durumlu sahte GitHub'a bağlı GitHubForge."""
    sahte = github_kipi(codegen, monkeypatch)
    ilk_commit = sahte.commit_files

    def commit_files(*a: Any, **k: Any) -> str:  # gerçek GitHub gibi 40 hane hex sha
        eski = ilk_commit(*a, **k)
        sha = uuid.uuid4().hex + "0" * 8
        sahte.commits[-1] = (sha, sahte.commits[-1][1])
        sahte.branches = {d: (sha if h == eski else h) for d, h in sahte.branches.items()}
        return sha

    monkeypatch.setattr(sahte, "commit_files", commit_files)
    sids = [uuid.UUID(uret(api, [hazir["cases"][i]])["script_ids"][0]) for i in (2, 1)]
    run_jobs(engine)
    gh = DurumluGitHub(main=sahte.main, commits={})
    gh.commit([], {sahte.FIXTURES: sahte.fixtures}, sha=sahte.main)
    for sid in sids:
        sc, cg = script_of(sid)
        assert sc.durum == "pr_open", cg.engel_nedeni
        gh.prs[sc.pr_no] = _Pr(sc.pr_no, sc.branch, sc.head_sha)
        gh.commit([sahte.main], {sahte.FIXTURES: sahte.fixtures, sc.dosya_yolu: sc.icerik},
                  sha=sc.head_sha)  # fmt: skip
    forge = GitHubForge(
        REPO, TokenAuth("ghs_bot"), transport=httpx.MockTransport(gh), sleep=lambda _s: None
    )
    service.set_factories(
        gateway=service._factories["gateway"],
        browser=service._factories["browser"],
        toolchain=service._factories["toolchain"],
        forge=lambda: forge,
    )
    yield gh, forge, sids
    forge.close()


def test_github_kipinde_dal_guncellenebilir(github: Any) -> None:
    assert service._dal_guncellenebilir() is True


def test_github_merge_sonrasi_diger_pr_guncellenir_ve_yabanci_head_sayilmaz(
    engine: Engine,
    codegen: Any,  # noqa: F811
    github: Any,
) -> None:
    gh, forge, (a_id, b_id) = github
    a, _ = script_of(a_id)
    b, _ = script_of(b_id)
    b_eski = b.head_sha

    # A GitHub arayüzünde merge edildi → senkron: A merged, B "geride" + güncelleme işi.
    gh.merge_github_arayuzunde(a.pr_no)
    sonuc = service.sync_prs(engine, forge)
    assert sonuc["merged"] == 1
    _, bcg = script_of(b_id)
    assert bcg.dal["geride"] is True and bcg.dal["guncelleme"] == "queued"

    # İş GitHubForge.update_branch ile dalı günceller: beklenen head = core'un bildiği head.
    run_jobs(engine)
    put = [g for m, y, g in gh.istekler if m == "PUT" and y.endswith("/update-branch")]
    assert put == [{"expected_head_sha": b_eski}]
    b, bcg = script_of(b_id)
    assert b.head_sha != b_eski and b.head_sha == gh.prs[b.pr_no].head
    assert bcg.dal["geride"] is False and bcg.dal["guncelleme"] == "done"
    assert bcg.dal["onceki_head"] == b_eski and bcg.break_durum == "not_started"
    assert codegen.ci[-1] == {"sha": b.head_sha, "trigger": "pr", "pr_number": b.pr_no}
    with session_scope() as s:
        assert s.get(PullRequest, b.pr_no).head_sha == b.head_sha

    # B GitHub'da (güncellenmiş head'iyle) merge edilir → yabancı head değil, ilk review başarısı.
    gh.merge_github_arayuzunde(b.pr_no)
    service.sync_prs(engine, forge)
    b, _ = script_of(b_id)
    assert b.durum == "merged" and b.insan_review_sonucu == "kabul"
    with session_scope() as s:
        yabanci = s.execute(
            text("SELECT count(*) FROM audit_event WHERE eylem = 'codegen.merged_foreign_head'")
        ).scalar_one()
    assert yabanci == 0


def test_github_dal_guncelleme_cakismasi_isi_basarisiz_yapar(engine: Engine, github: Any) -> None:
    gh, forge, (a_id, b_id) = github
    a, _ = script_of(a_id)
    b, _ = script_of(b_id)

    def cakisma(req: httpx.Request, _onceki: Any = gh.__call__) -> httpx.Response:
        if req.method == "PUT" and req.url.path.endswith("/update-branch"):
            return httpx.Response(422, json={"message": "merge conflict between base and head"})
        return _onceki(req)

    forge._client._transport = httpx.MockTransport(cakisma)
    gh.merge_github_arayuzunde(a.pr_no)
    service.sync_prs(engine, forge)
    run_jobs(engine)
    b2, bcg = script_of(b_id)
    assert b2.head_sha == b.head_sha and b2.durum == "pr_open"
    assert bcg.dal["guncelleme"] == "failed" and "çakışıyor" in bcg.dal["neden"]


def test_github_insan_reddi_pr_kapatir(
    api: TestClient,  # noqa: F811
    engine: Engine,
    github: Any,
    muhendis: Principal,
) -> None:
    gh, _forge, (a_id, _b_id) = github
    a, _ = script_of(a_id)
    d = api.get(f"/scripts/{a.id}").json()
    r = api.post(
        f"/prs/{a.pr_no}/review",
        json={"karar": "reddet", "icerik_hash": d["pr"]["icerik_hash"],
              "head_sha": d["pr"]["head_sha"], "not": "Yanlış ürün kartı.",
              "ret_nedeni": "wrong_element"},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    run_jobs(engine)
    assert ("PATCH", f"{R}/pulls/{a.pr_no}", {"state": "closed"}) in gh.istekler
    assert gh.prs[a.pr_no].state == "closed"
    with session_scope() as s:
        assert s.get(PullRequest, a.pr_no).durum == "closed"
        hata = s.execute(
            text("SELECT count(*) FROM audit_event WHERE eylem = 'codegen.pr_close_failed'")
        ).scalar_one()
    assert hata == 0
