"""Durum tutan sahte GitHub deposu (httpx MockTransport): commit/ağaç/ref/PR/merge.

Demo kırılması/sıfırlamasının GitHub yolunu uçtan uca sınamak için: Git Data API (ağaç, commit,
ref), içerik okuma, compare, PR açma/listeleme/merge ve ruleset benzetimi. Her istek hangi
token'la yapıldığıyla kaydedilir (`calls`): testler yazma işlemlerinin bot değil insan kimliğiyle
yapıldığını doğrular.

Ruleset benzetimi: `main`'e doğrudan ref yazımı yok; PR merge'ü yalnızca `bypass_tokens`
(demo-admin takımı üyesi insan) ile ya da onay + yeşil kontrol varken yapılır. Bot token'ı ile
merge 405 döner. Kod araması (`/search/code`) kasıtlı olarak 500 döner: GitHub yolu aramaya
dayanmamalıdır (dizin yalnızca varsayılan dalı ve gecikmeli kapsar).
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote

import httpx

REPO = "ThinkGOtr/testingprobe-demo-app"
BOT_TOKEN = "bot-tok"
HUMAN_TOKEN = "insan-tok"
HUMAN_LOGIN = "gokhansipahi"
BOT_LOGIN = "tp-bot[bot]"

CATALOG = (
    "export function Card() {\n"
    '  return <button data-testid="add-to-cart">Sepete ekle</button>;\n'
    "}\n"
)
E2E_LOCATORS = (
    "export const catalog = {\n"
    '  addToCart: { testId: "add-to-cart", role: "button", name: "Sepete ekle" },\n'
    "};\n"
)
BASE_FILES: dict[str, str] = {
    "README.md": "demo\n",
    ".github/workflows/ci.yml": "name: ci\n",
    "demo-app/web/Dockerfile": "FROM scratch\n",
    "demo-app/web/src/pages/CatalogPage.tsx": CATALOG,
    "demo-app/web/src/main.tsx": "import './styles.css';\n",
    "demo-app/web/src/styles.css": ".x { color: red; }\n",
    "demo-app/api/app.py": "print('api')\n",
    "demo-app/e2e/pages/catalog/locators.ts": E2E_LOCATORS,
}


def _h(*parts: Any) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True).encode()).hexdigest()


class FakeGitHubRepo:
    def __init__(
        self,
        files: Mapping[str, str] | None = None,
        *,
        repo: str = REPO,
        baseline_tag: bool = True,
    ) -> None:
        self.repo = repo
        self.prefix = f"/repos/{repo}"
        self.trees: dict[str, dict[str, str]] = {}
        self.commits: dict[str, dict[str, Any]] = {}
        self.refs: dict[str, str] = {}
        self.prs: dict[int, dict[str, Any]] = {}
        self.calls: list[tuple[str, str, str]] = []  # (method, path, token)
        self.logins = {BOT_TOKEN: BOT_LOGIN, HUMAN_TOKEN: HUMAN_LOGIN}
        self.bypass_tokens = {HUMAN_TOKEN}
        self.check_runs: dict[str, list[dict[str, Any]]] = {}
        self._seq = 0
        root = self._commit(dict(files or BASE_FILES), [], "Demo uygulaması: başlangıç durumu")
        self.refs["heads/main"] = root
        if baseline_tag:
            self.refs["tags/demo-baseline"] = root

    # ------------------------------------------------------------------ model

    def _tree(self, files: Mapping[str, str]) -> str:
        sha = _h("tree", sorted(files.items()))
        self.trees[sha] = dict(files)
        return sha

    def _commit(self, files: Mapping[str, str], parents: list[str], message: str) -> str:
        tree = self._tree(files)
        self._seq += 1
        sha = _h("commit", tree, parents, message, self._seq)
        self.commits[sha] = {"tree": tree, "parents": list(parents), "message": message}
        return sha

    def files_at(self, ref: str) -> dict[str, str]:
        return dict(self.trees[self.commits[self.resolve(ref)]["tree"]])

    def resolve(self, ref: str) -> str:
        if ref in self.commits:
            return ref
        for k in (f"heads/{ref}", f"tags/{ref}"):
            if k in self.refs:
                return self.refs[k]
        raise KeyError(ref)

    def ancestors(self, sha: str) -> list[str]:
        seen: list[str] = []
        stack = [sha]
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.append(c)
            stack.extend(self.commits[c]["parents"])
        return seen

    def merge_base(self, a: str, b: str) -> str:
        anc_a = self.ancestors(a)
        for c in self.ancestors(b):
            if c in anc_a:
                return c
        raise KeyError("ortak ata yok")

    def _subtree_sha(self, files: Mapping[str, str], d: str) -> str:
        sub = {k[len(d) + 1 :]: v for k, v in files.items() if k.startswith(d + "/")}
        return _h("tree", sorted(sub.items()))

    def writes_by(self, token: str) -> list[tuple[str, str]]:
        return [(m, p) for m, p, t in self.calls if t == token and m != "GET"]

    # ------------------------------------------------------------------ HTTP

    def __call__(self, request: httpx.Request) -> httpx.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        path = unquote(request.url.path)
        self.calls.append((request.method, path, token))
        body = json.loads(request.content) if request.content else {}
        try:
            return self._route(request.method, path, request.url.params, body, token)
        except KeyError:
            return httpx.Response(404, json={"message": "Not Found"})

    def _json(self, data: Any, status: int = 200) -> httpx.Response:
        return httpx.Response(status, json=data)

    def _route(
        self, method: str, path: str, params: Any, body: dict[str, Any], token: str
    ) -> httpx.Response:
        if path == "/user":
            return self._json({"login": self.logins[token]})
        if path == "/search/code":
            return httpx.Response(500, json={"message": "kod araması kullanılmamalı"})
        if not path.startswith(self.prefix + "/"):
            raise KeyError(path)
        p = path[len(self.prefix) + 1 :]

        if method == "GET" and p.startswith("commits/") and p.endswith("/check-runs"):
            sha = self.resolve(p[len("commits/") : -len("/check-runs")])
            return self._json({"check_runs": self.check_runs.get(sha, [])})
        if method == "GET" and p.startswith("commits/"):
            return self._json({"sha": self.resolve(p[len("commits/") :])})
        if method == "GET" and p.startswith("git/commits/"):
            sha = p[len("git/commits/") :]
            c = self.commits[sha]
            return self._json(
                {"sha": sha, "tree": {"sha": c["tree"]},
                 "parents": [{"sha": x} for x in c["parents"]]}
            )  # fmt: skip
        if method == "GET" and p.startswith("git/trees/"):
            files = self.trees[p[len("git/trees/") :]]
            dirs = sorted(
                {"/".join(f.split("/")[:i]) for f in files for i in range(1, f.count("/") + 1)}
            )
            entries = [
                {"path": d, "type": "tree", "mode": "040000", "sha": self._subtree_sha(files, d)}
                for d in dirs
            ] + [
                {"path": f, "type": "blob", "mode": "100644", "sha": _h("blob", v)}
                for f, v in sorted(files.items())
            ]
            return self._json({"truncated": False, "tree": entries})
        if method == "GET" and p.startswith("contents/"):
            files = self.files_at(params.get("ref") or "main")
            text = files[p[len("contents/") :]]
            return self._json(
                {"type": "file", "encoding": "base64", "sha": _h("blob", text),
                 "content": base64.b64encode(text.encode()).decode()}
            )  # fmt: skip
        if method == "GET" and p.startswith("compare/"):
            a, b = p[len("compare/") :].split("...", 1)
            sa, sb = self.resolve(a), self.resolve(b)
            base = self.merge_base(sa, sb)
            fb, fh = self.files_at(base), self.files_at(sb)
            changed = sorted(k for k in set(fb) | set(fh) if fb.get(k) != fh.get(k))
            behind = len([c for c in self.ancestors(sa) if c not in self.ancestors(sb)])
            return self._json(
                {"merge_base_commit": {"sha": base}, "behind_by": behind,
                 "files": [{"filename": k} for k in changed]}
            )  # fmt: skip
        if method == "GET" and p.startswith("git/ref/"):
            return self._json({"object": {"sha": self.refs[p[len("git/ref/") :]]}})
        if method == "POST" and p == "git/trees":
            files = dict(self.trees[body["base_tree"]])
            for e in body["tree"]:
                files[e["path"]] = e["content"]
            return self._json({"sha": self._tree(files)}, 201)
        if method == "POST" and p == "git/commits":
            if body["tree"] not in self.trees:
                return self._json({"message": "tree yok"}, 422)
            self._seq += 1
            sha = _h("commit", body["tree"], body["parents"], body["message"], self._seq)
            self.commits[sha] = {
                "tree": body["tree"], "parents": list(body["parents"]), "message": body["message"],
                "author": self.logins[token],
            }  # fmt: skip
            return self._json({"sha": sha}, 201)
        if method == "POST" and p == "git/refs":
            ref = body["ref"].removeprefix("refs/")
            if ref == "heads/main":
                return self._json({"message": "ruleset: main'e doğrudan yazılamaz"}, 422)
            if ref in self.refs:
                return self._json({"message": "Reference already exists"}, 422)
            self.refs[ref] = body["sha"]
            return self._json({"ref": body["ref"]}, 201)
        if method == "PATCH" and p.startswith("git/refs/"):
            ref = p[len("git/refs/") :]
            if ref == "heads/main":
                return self._json({"message": "ruleset: main'e doğrudan yazılamaz"}, 422)
            if self.refs[ref] not in self.ancestors(body["sha"]) and not body.get("force"):
                return self._json({"message": "Update is not a fast forward"}, 422)
            self.refs[ref] = body["sha"]
            return self._json({"ref": ref})
        if method == "GET" and p == "pulls":
            state = params.get("state") or "open"
            head = params.get("head")
            out = [
                self._pr_json(n) for n, pr in sorted(self.prs.items())
                if (state == "all" or pr["state"] == state)
                and (head is None or head == f"{self.repo.split('/')[0]}:{pr['branch']}")
            ]  # fmt: skip
            return self._json(out)
        if method == "POST" and p == "pulls":
            head = self.refs[f"heads/{body['head']}"]
            main = self.refs["heads/main"]
            if head in self.ancestors(main):
                return self._json({"message": f"No commits between main and {body['head']}"}, 422)
            n = len(self.prs) + 1
            self.prs[n] = {
                "branch": body["head"], "title": body["title"], "body": body.get("body") or "",
                "state": "open", "merged": False, "labels": [], "author": self.logins[token],
                "merged_by": None, "merge_commit_sha": None,
            }  # fmt: skip
            return self._json(self._pr_json(n), 201)
        if method == "POST" and p.startswith("issues/") and p.endswith("/labels"):
            n = int(p.split("/")[1])
            self.prs[n]["labels"] += [x for x in body["labels"] if x not in self.prs[n]["labels"]]
            return self._json([{"name": x} for x in self.prs[n]["labels"]])
        if method == "POST" and p.startswith("issues/") and p.endswith("/comments"):
            return self._json({"id": 1}, 201)
        if method == "GET" and p.startswith("pulls/") and p.endswith("/reviews"):
            return self._json([])
        if method == "GET" and p.startswith("pulls/"):
            return self._json(self._pr_json(int(p.split("/")[1])))
        if method == "PATCH" and p.startswith("pulls/"):
            n = int(p.split("/")[1])
            self.prs[n]["state"] = body.get("state", self.prs[n]["state"])
            return self._json(self._pr_json(n))
        if method == "PUT" and p.startswith("pulls/") and p.endswith("/merge"):
            return self._merge(int(p.split("/")[1]), body, token)
        raise KeyError(p)

    def _pr_json(self, n: int) -> dict[str, Any]:
        pr = self.prs[n]
        head = self.refs.get(f"heads/{pr['branch']}", "0" * 40)
        return {
            "number": n,
            "state": pr["state"],
            "title": pr["title"],
            "body": pr["body"],
            "head": {"ref": pr["branch"], "sha": head},
            "base": {"ref": "main", "sha": self.refs["heads/main"]},
            "html_url": f"https://github.com/{self.repo}/pull/{n}",
            "labels": [{"name": x} for x in pr["labels"]],
            "merged": pr["merged"],
            "merged_at": "2026-11-01T10:00:00Z" if pr["merged"] else None,
            "merged_by": {"login": pr["merged_by"]} if pr["merged_by"] else None,
            "merge_commit_sha": pr["merge_commit_sha"],
            "mergeable_state": "blocked",
            "user": {"login": pr["author"]},
        }

    def _merge(self, n: int, body: dict[str, Any], token: str) -> httpx.Response:
        pr = self.prs[n]
        if token not in self.bypass_tokens:
            return self._json({"message": "Repository rule violations found"}, 405)
        head = self.refs[f"heads/{pr['branch']}"]
        if body.get("sha") and body["sha"] != head:
            return self._json({"message": "Head branch was modified"}, 409)
        main = self.refs["heads/main"]
        base = self.merge_base(main, head)
        fb, fm, fh = self.files_at(base), self.files_at(main), self.files_at(head)
        merged = dict(fm)
        for k in set(fb) | set(fh):
            if fb.get(k) != fh.get(k):
                if fh.get(k) is None:
                    merged.pop(k, None)
                else:
                    merged[k] = fh[k]
        sha = self._commit(merged, [main, head], f"Merge pull request #{n}")
        self.refs["heads/main"] = sha
        pr.update(state="closed", merged=True, merged_by=self.logins[token], merge_commit_sha=sha)
        return self._json({"merged": True, "sha": sha, "message": "Pull Request merged"})
