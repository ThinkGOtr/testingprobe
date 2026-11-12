"""Demo locator kırılması ve sıfırlaması (TEKNIK-TASARIM §2 adım 12, §10, §13).

`break_locator`: `demo/break-locator` dalından PR açar (varsa açık olanı kullanır), `demo-admin`
kimliğiyle kural bypass'ı ile merge eder ve denetim kaydına "demo kırılması" yazar.

Bypass yalnızca demo kırılmasının kendisi içindir (anayasa): PR açılmadan ÖNCE dalın head'i
(`H`) okunur ve `ortak-ata(main, H)..H` farkı doğrulanır — değişen her dosya `web/src/` altında
olmalı, satır sayısı aynı kalmalı ve değişen her satır yalnızca tırnaklı `add-to-cart` →
`cart-add` dönüşümü olmalıdır (ekleme/silme/yeniden adlandırma/kip değişikliği/ikili içerik
reddedilir). Merge `H`'ye bağlıdır (`expected_head_sha=H`); PR head'i `H` değilse merge edilmez.
Doğrulanan fark özeti denetim kaydına (`fark`) yazılır.

`restore_baseline` (yalnızca LocalForge): `main`'i `demo-baseline` etiketine geri taşır ve
"demo sıfırlaması" denetim olayını yazar.

**GitHub kipi (TP_FORGE=github)** — bot hiçbir adımda kullanılmaz; her şey İNSAN kimliğiyle
(`GITHUB_MERGE_TOKEN`: `demo-admin` takımındaki mühendisin token'ı, `GitHubForge.human_forge`):
- `break_locator_github`: main'in o anki head'inden `demo/break-locator-<main12>` dalına tek
  commit (yalnızca `<app>/web/src` altındaki tırnaklı `add-to-cart` → `cart-add`), PR açılır,
  fark yerel kipteki AYNI `verify_break_diff` ile doğrulanır ve PR head'ine bağlı olarak
  `demo-admin` ruleset bypass'ıyla merge edilir. Dal adı main sha'sına bağlı olduğundan
  yinelenen istek aynı dalı/PR'ı kullanır (idempotent); sıfırlamadan sonra yeni main yeni dal
  verir (eski dal main'in geçmişinde olduğu için PR açılamazdı).
- `restore_baseline_github`: force-push YOK. main'in üstüne ağacı `demo-baseline` etiketinin
  ağacıyla birebir aynı olan tek commit (`demo/reset-baseline-<main12>`) yazılır, PR açılır ve
  aynı insan kimliğiyle bypass merge edilir; merge sonrası main ağacı baseline ağacına eşit
  olmalıdır (değilse hata). Geçmiş korunur ve denetlenebilir; yalnızca kırılmayı geri alan bir
  `git revert` yetmezdi: arada merge edilen onarım (e2e testId) ve üretilen testler de geri
  alınmalıdır (yerel kipte `main → demo-baseline` ile aynı sonuç).
Testid durumu GitHub'da kod aramasıyla değil (arama yalnızca varsayılan dalın gecikmeli
dizinidir) `<app>/web/src` ağacının listesi + dosya okumasıyla belirlenir (commit sha'sına göre
önbellekli). `<app>` = `TP_FORGE_APP_ROOT`, yoksa forge'un varsayılanı (yerel '', GitHub
'demo-app').

İkisi de idempotenttir: durum zaten hedefteyse forge'a ve denetime dokunmaz (`changed=False`).

`main` değiştiğinde ikisi de `main`'in yeni head'i için `push` tetikli CI koşusunu kuyruğa alır
(`features.ci.enqueue_ci(sha, "push", isteyen=demo-admin)` — GitHub'daki `on: push` karşılığı;
github modunda aynı çağrı Actions push koşusunu bekler). Böylece `make break` sonrası `main` CI'ı
kendiliğinden kırmızıya döner ve FailureToFix triage'ı başlar (TEKNIK-TASARIM §13 adım 7).
CI tetiği başarısız olursa forge değişikliği geri alınmaz; hata sonuca ve denetim özetine yazılır.

CLI (core-worker içinde; forge rw + Postgres erişimi gerekir):

    python -m tp_core.integrations.forge_demo break       # JSON özet → stdout
    python -m tp_core.integrations.forge_demo baseline    # JSON özet → stdout
    python -m tp_core.integrations.forge_demo status      # JSON: main sha + testid durumu
    python -m tp_core.integrations.forge_demo archive [--ref main] [--path web]  # tar → stdout
    python -m tp_core.integrations.forge_demo web-state   # JSON: çalışan demo-app-web main mi?
    python -m tp_core.integrations.forge_demo web-path    # JSON: {kip, web_yolu} (API çağrısı yok)

`scripts/forge-init.sh break|baseline|sync-web` bu CLI'ı çağırır ve demo-app-web imajını
`archive` çıktısından (forge `main` HEAD) yeniden derler — ama yalnızca `web-state` çalışan
uygulamanın main'i yansıtmadığını söylerse (`guncel=false`). Yansıtıyorsa derleme ve yeniden
oluşturma atlanır: ikinci bir `make break` süren push CI'ının altındaki uygulamayı öldürmez.
`mesgul` (koşan `ci.run`/`repair.fix` işleri) doluysa betik zorlanmadıkça yeniden oluşturmaz.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from pydantic import BaseModel

from tp_core.integrations.forge import (
    BYPASS_ACTOR,
    ForgeError,
    ForgeNotFoundError,
    ForgeValidationError,
    MergeResult,
    get_forge,
    is_sha,
)
from tp_core.ports import AuditLog, ForgePort

BREAK_BRANCH = "demo/break-locator"
BASELINE_TAG = "demo-baseline"
OLD_TESTID = "add-to-cart"
NEW_TESTID = "cart-add"
WEB_SRC_PREFIX = "web/src/"
BREAK_PR_TITLE = "demo: Sepete ekle butonunun data-testid'si değişti (add-to-cart → cart-add)"
BREAK_PR_BODY = (
    "Demo locator kırılması (TEKNIK-TASARIM §2 adım 12). Yalnızca `data-testid` değeri değişir; "
    "e2e testleri kırmızıya döner ve bakım (locator onarımı) yolu tetiklenir.\n\n"
    f'Merge: `{BYPASS_ACTOR}` kural bypass\'ı ile; denetim kaydına "demo kırılması" yazılır.'
)
BREAK_LABELS = ("demo",)
BREAK_COMMIT_MESSAGE = "demo: Sepete ekle butonunun data-testid'si değişti (add-to-cart → cart-add)"
RESET_BRANCH = "demo/reset-baseline"
RESET_PR_TITLE = "demo: main'i demo-baseline ağacına döndür (demo sıfırlaması)"
RESET_COMMIT_MESSAGE = "demo: demo sıfırlaması — ağaç demo-baseline'a döndü"
GITHUB_INSAN_NOTU = (
    "GitHub kipi: bu PR bot (App) ile değil, insan kimliğiyle (`GITHUB_MERGE_TOKEN`, "
    f"`{BYPASS_ACTOR}` takımı üyesi) açıldı ve aynı kimlikle ruleset bypass'ıyla merge edilir."
)
APP_ROOT_ENV = "TP_FORGE_APP_ROOT"
AUDIT_BREAK = "demo kırılması"
AUDIT_BASELINE = "demo sıfırlaması"
CI_TRIGGER = "push"

# (yeni main sha, aktör) → kuyruğa alınan CI koşusunun kimliği.
CiTrigger = Callable[[str, str], Any]


# Kırılma dalında değişebilecek en fazla dosya (demo-app'te 1; sınır savunma amaçlı).
MAX_BREAK_FILES = 5


class DemoForge(ForgePort, Protocol):
    """`merge_pr_detailed` sunan forge (LocalForge, GitHubForge); `merge_base` / `changed_paths`
    `ForgePort`'tadır."""

    def merge_pr_detailed(
        self, number: int, actor: str, *, expected_head_sha: str | None = None
    ) -> MergeResult: ...


class DemoOutcome(BaseModel):
    action: str  # break | baseline
    changed: bool
    main_before: str
    main_after: str
    testid: str  # main HEAD'deki durum: add-to-cart | cart-add | belirsiz
    pr_number: int | None = None
    merge: MergeResult | None = None
    audit_id: int | None = None
    ci_run_id: str | None = None  # main değiştiyse kuyruğa alınan push CI koşusu
    ci_error: str | None = None


def _trigger_push_ci(ci: CiTrigger | None, sha: str, actor: str) -> dict[str, Any]:
    """`main`'in yeni head'i için push CI'ı; hata yutulmaz, sonuca yazılır (forge geri alınmaz)."""
    if ci is None:
        return {"tetik": CI_TRIGGER, "run_id": None, "hata": "CI tetikleyici verilmedi"}
    try:
        run_id = ci(sha, actor)
    except Exception as exc:  # merge yapıldı; CI hatası denetime yazılır
        return {"tetik": CI_TRIGGER, "run_id": None, "hata": f"{type(exc).__name__}: {exc}"[:500]}
    return {"tetik": CI_TRIGGER, "run_id": None if run_id is None else str(run_id), "hata": None}


def app_root_for(forge: Any, env: Mapping[str, str] | None = None) -> str:
    """Uygulamanın forge deposundaki kökü: `TP_FORGE_APP_ROOT`, yoksa forge'un varsayılanı
    (LocalForge '' — depo demo-app'in kendisi; GitHubForge 'demo-app')."""
    env = os.environ if env is None else env
    deger = env.get(APP_ROOT_ENV)
    if deger is None:
        deger = getattr(forge, "default_app_root", "") or ""
    return str(deger).strip().strip("/")


def app_path(forge: Any, rel: str) -> str:
    """Uygulama köküne göre yol (`web/src/` → `demo-app/web/src/` GitHub kipinde)."""
    kok = app_root_for(forge)
    return f"{kok}/{rel}" if kok else rel


# GitHub: commit sha'sı → web/src dosyaları (içerik sha'ya göre değişmez; küçük, sınırlı önbellek).
_WEB_SRC_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".html")
_WEB_SRC_MAX_FILES = 200
_WEB_SRC_CACHE: dict[tuple[str, str, str], dict[str, str]] = {}
_WEB_SRC_CACHE_MAX = 16


def clear_cache() -> None:
    _WEB_SRC_CACHE.clear()


def _web_src_files(forge: Any, ref: str, prefix: str) -> dict[str, str]:
    """`ref`'teki `prefix` altındaki kaynak dosyalar (ağaç listesi + okuma; arama dizini yok)."""
    sha = ref if is_sha(ref) else forge.head_sha(ref)
    key = (str(getattr(forge, "repo", id(forge))), sha, prefix)
    hit = _WEB_SRC_CACHE.get(key)
    if hit is not None:
        return hit
    paths = [p for p in forge.list_files(prefix, sha) if p.endswith(_WEB_SRC_SUFFIXES)]
    if len(paths) > _WEB_SRC_MAX_FILES:
        raise ForgeError(f"{prefix} altında beklenenden çok dosya ({len(paths)})")
    files = {p: forge.read_file(p, sha) for p in paths}
    if len(_WEB_SRC_CACHE) >= _WEB_SRC_CACHE_MAX:
        _WEB_SRC_CACHE.pop(next(iter(_WEB_SRC_CACHE)))
    _WEB_SRC_CACHE[key] = files
    return files


def _quoted_hits(forge: ForgePort, value: str, ref: str) -> list[tuple[str, int, str]]:
    """<app>/web/src altında tırnak içinde `value` geçen satırlar (yalnızca testid değeri)."""
    prefix = app_path(forge, WEB_SRC_PREFIX)
    if getattr(forge, "code_search_is_indexed", False):
        aday = [
            (path, no, line)
            for path, metin in _web_src_files(forge, ref, prefix).items()
            for no, line in enumerate(metin.splitlines(), start=1)
            if value in line
        ]
    else:
        aday = forge.search_code(value, ref)
    hits = []
    for path, line_no, line in aday:
        if not path.startswith(prefix):
            continue
        if any(f"{q}{value}{q}" in line for q in ("'", '"', "`")):
            hits.append((path, line_no, line))
    return hits


def testid_state(forge: ForgePort, ref: str = "main") -> str:
    """`ref`'teki "Sepete ekle" testid durumu."""
    old = bool(_quoted_hits(forge, OLD_TESTID, ref))
    new = bool(_quoted_hits(forge, NEW_TESTID, ref))
    if new and not old:
        return NEW_TESTID
    if old and not new:
        return OLD_TESTID
    return "belirsiz"


E2E_LOCATOR_PATH = "e2e/pages/catalog/locators.ts"
_E2E_ADD_TO_CART = re.compile(r"addToCart\s*:\s*\{[^}]*?testId\s*:\s*[\"'`]([^\"'`]+)[\"'`]")


def e2e_testid_state(forge: ForgePort, ref: str = "main") -> str | None:
    """`ref`'teki e2e page object'inin (catalog.addToCart) testId değeri; okunamazsa None."""
    try:
        metin = forge.read_file(app_path(forge, E2E_LOCATOR_PATH), ref)
    except Exception:
        return None
    m = _E2E_ADD_TO_CART.search(metin or "")
    return m.group(1) if m else None


def locator_durumu(web_testid: str | None, e2e_testid: str | None) -> str | None:
    """Locator demosunun evresi: baseline · kirik (uygulama değişti, test eski) · onarildi."""
    if web_testid == OLD_TESTID and e2e_testid == OLD_TESTID:
        return "baseline"
    if web_testid == NEW_TESTID and e2e_testid == OLD_TESTID:
        return "kirik"
    if web_testid == NEW_TESTID and e2e_testid == NEW_TESTID:
        return "onarildi"
    return None


def _swap_testid(line: str) -> str:
    for q in ("'", '"', "`"):
        line = line.replace(f"{q}{OLD_TESTID}{q}", f"{q}{NEW_TESTID}{q}")
    return line


def verify_break_diff(
    forge: DemoForge, head_sha: str, base_ref: str = "main", *, branch: str = BREAK_BRANCH
) -> dict[str, Any]:
    """`ortak-ata(base_ref, head_sha)..head_sha` farkı yalnızca testid değişimi mi? Değilse hata.

    Dönen değer denetim için fark özetidir: {head, taban, dosyalar, degisen_satir}.
    """
    web_src = app_path(forge, WEB_SRC_PREFIX)
    merge_base = getattr(forge, "merge_base", None)
    changed_paths = getattr(forge, "changed_paths", None)
    if not callable(merge_base) or not callable(changed_paths):
        raise ForgeValidationError(
            "forge kırılma farkını doğrulayamıyor (merge_base/changed_paths)"
        )
    base = merge_base(base_ref, head_sha)
    paths = changed_paths(base, head_sha)
    if paths is None:
        raise ForgeError(f"'{branch}' farkı okunamadı (liste kesilmiş olabilir)")
    if not paths:
        raise ForgeError(f"'{branch}' dalında {base_ref}'e göre değişiklik yok")
    if len(paths) > MAX_BREAK_FILES:
        raise ForgeError(
            f"'{branch}' beklenenden çok dosya değiştiriyor ({len(paths)} > {MAX_BREAK_FILES})"
        )
    disari = [p for p in paths if not p.startswith(web_src)]
    if disari:
        raise ForgeError(f"'{branch}' {web_src} dışını değiştiriyor: {disari[:5]}")
    satir = 0
    for path in paths:
        try:
            old = forge.read_file(path, base)
            new = forge.read_file(path, head_sha)
        except ForgeError as exc:  # ekleme/silme/yeniden adlandırma
            raise ForgeError(
                f"'{branch}' yalnızca mevcut dosyada testid değiştirebilir: {path} ({exc})"
            ) from exc
        if "\ufffd" in old or "\ufffd" in new:
            raise ForgeError(f"'{branch}' metin olmayan içerik değiştiriyor: {path}")
        old_lines, new_lines = old.split("\n"), new.split("\n")
        if len(old_lines) != len(new_lines):
            raise ForgeError(f"'{branch}' satır ekliyor/siliyor: {path}")
        degisen = 0
        for no, (a, b) in enumerate(zip(old_lines, new_lines, strict=True), start=1):
            if a == b:
                continue
            if _swap_testid(a) != b:
                raise ForgeError(
                    f"'{branch}' beklenmeyen değişiklik içeriyor: {path}:{no} "
                    f"(yalnızca '{OLD_TESTID}' → '{NEW_TESTID}' izinli)"
                )
            degisen += 1
        if degisen == 0:  # yalnızca kip/ikili değişiklik
            raise ForgeError(f"'{branch}' içerik dışı değişiklik içeriyor: {path}")
        satir += degisen
    return {"head": head_sha, "taban": base, "dosyalar": paths, "degisen_satir": satir}


def break_locator(
    forge: DemoForge,
    audit: AuditLog,
    *,
    actor: str = BYPASS_ACTOR,
    ci: CiTrigger | None = None,
    branch: str = BREAK_BRANCH,
    kimlik: Mapping[str, Any] | None = None,
) -> DemoOutcome:
    """Kırılma PR'ını açar, `actor` (demo-admin) bypass'ıyla merge eder, denetime yazar."""
    before = forge.head_sha("main")
    state = testid_state(forge, "main")
    if state == NEW_TESTID:
        return DemoOutcome(
            action="break", changed=False, main_before=before, main_after=before, testid=state
        )
    if state != OLD_TESTID:
        raise ForgeError(f"main'de '{OLD_TESTID}' testid'i bulunamadı (durum: {state})")
    head = forge.head_sha(branch)
    if testid_state(forge, head) != NEW_TESTID:
        raise ForgeError(f"'{branch}' dalı beklenen kırılmayı ({NEW_TESTID}) içermiyor")
    # Bypass yalnızca doğrulanmış testid değişimi için: fark PR açılmadan önce, head'e bağlı.
    fark = verify_break_diff(forge, head, "main", branch=branch)

    govde = BREAK_PR_BODY if kimlik is None else f"{BREAK_PR_BODY}\n\n{GITHUB_INSAN_NOTU}"
    pr = forge.find_open_pr(branch) or forge.open_pr(branch, BREAK_PR_TITLE, govde, BREAK_LABELS)
    if pr.head_sha != head:
        raise ForgeError(
            f"'{branch}' PR head'i ({pr.head_sha[:12]}) doğrulanan head'den ({head[:12]}) "
            "farklı; merge edilmedi"
        )
    result = forge.merge_pr_detailed(pr.number, actor, expected_head_sha=head)
    after = forge.head_sha("main")
    final = testid_state(forge, "main")
    ci_info = _trigger_push_ci(ci, after, actor) if after != before else None
    ozet: dict[str, Any] = {
        "pr": pr.number,
        "dal": branch,
        "head_sha": pr.head_sha,
        "merge_sha": result.sha,
        "yontem": result.method,
        "bypass": result.bypass,
        "bypass_nedeni": result.bypass_reason,
        "main_once": before,
        "main_sonra": after,
        "testid": {"once": OLD_TESTID, "sonra": final},
        "fark": fark,
        "ci": ci_info,
    }
    if kimlik is not None:
        ozet["kimlik"] = dict(kimlik)
        ozet["github_merge_eden"] = getattr(result, "github_merge_eden", None)
    audit_id = audit.append(actor, AUDIT_BREAK, f"pr:{pr.number}", ozet)
    if final != NEW_TESTID:
        raise ForgeError(f"merge sonrası main testid durumu beklenmedik: {final}")
    return DemoOutcome(
        action="break",
        changed=True,
        main_before=before,
        main_after=after,
        testid=final,
        pr_number=pr.number,
        merge=result,
        audit_id=audit_id,
        ci_run_id=ci_info["run_id"] if ci_info else None,
        ci_error=ci_info["hata"] if ci_info else None,
    )


def restore_baseline(
    forge: Any,
    audit: AuditLog,
    *,
    actor: str = BYPASS_ACTOR,
    ci: CiTrigger | None = None,
) -> DemoOutcome:
    """`main` → `demo-baseline` (yalnızca LocalForge; GitHub'da sıfırlama elle/revert PR ile)."""
    reset = getattr(forge, "reset_branch", None)
    if reset is None:
        raise ForgeValidationError(
            "baseline'a dönüş yalnızca yerel forge'da (TP_FORGE=local) desteklenir"
        )
    target = forge.head_sha(BASELINE_TAG)
    before = forge.head_sha("main")
    if before == target:
        return DemoOutcome(
            action="baseline",
            changed=False,
            main_before=before,
            main_after=before,
            testid=testid_state(forge, "main"),
        )
    _old, after = reset("main", BASELINE_TAG, actor=actor)
    final = testid_state(forge, "main")
    ci_info = _trigger_push_ci(ci, after, actor) if after != before else None
    audit_id = audit.append(
        actor,
        AUDIT_BASELINE,
        "forge:main",
        {
            "main_once": before,
            "main_sonra": after,
            "hedef": BASELINE_TAG,
            "testid": final,
            "ci": ci_info,
        },
    )
    return DemoOutcome(
        action="baseline",
        changed=True,
        main_before=before,
        main_after=after,
        testid=final,
        audit_id=audit_id,
        ci_run_id=ci_info["run_id"] if ci_info else None,
        ci_error=ci_info["hata"] if ci_info else None,
    )


# --------------------------------------------------------------------- GitHub kipi


def _insan(forge: Any) -> Any:
    fn = getattr(forge, "human_forge", None)
    if not callable(fn):
        raise ForgeValidationError("forge insan kimliğiyle demo işlemi sunmuyor (GitHub değil)")
    return fn()  # merge token'ı yoksa ForgeProtectionError


def _kimlik(human: Any) -> dict[str, Any]:
    login = None
    fn = getattr(human, "merge_token_login", None)
    if callable(fn):
        login = fn()
    return {"tur": "insan", "kaynak": "GITHUB_MERGE_TOKEN", "github_login": login}


def break_locator_github(
    forge: Any,
    audit: AuditLog,
    *,
    actor: str = BYPASS_ACTOR,
    ci: CiTrigger | None = None,
) -> DemoOutcome:
    """GitHub kipi kırılması: insan kimliğiyle dal + commit + PR + bypass merge (modül belgesi)."""
    human = _insan(forge)
    before = human.head_sha("main")
    state = testid_state(human, "main")
    if state == NEW_TESTID:
        return DemoOutcome(
            action="break", changed=False, main_before=before, main_after=before, testid=state
        )
    if state != OLD_TESTID:
        raise ForgeError(f"main'de '{OLD_TESTID}' testid'i bulunamadı (durum: {state})")
    branch = f"{BREAK_BRANCH}-{before[:12]}"
    if human.find_open_pr(branch) is None:
        prefix = app_path(human, WEB_SRC_PREFIX)
        files: dict[str, str] = {}
        for path, metin in _web_src_files(human, before, prefix).items():
            yeni = "\n".join(_swap_testid(satir) for satir in metin.split("\n"))
            if yeni != metin:
                files[path] = yeni
        if not files:
            raise ForgeError(f"{prefix} altında değiştirilecek '{OLD_TESTID}' bulunamadı")
        human.commit_files(branch, files, BREAK_COMMIT_MESSAGE, base=before)
    return break_locator(human, audit, actor=actor, ci=ci, branch=branch, kimlik=_kimlik(human))


def restore_baseline_github(
    forge: Any,
    audit: AuditLog,
    *,
    actor: str = BYPASS_ACTOR,
    ci: CiTrigger | None = None,
) -> DemoOutcome:
    """GitHub kipi sıfırlaması: main üstüne baseline ağacı (insan kimliği, PR, bypass merge)."""
    human = _insan(forge)
    try:
        target = human.head_sha(BASELINE_TAG)
    except ForgeNotFoundError as exc:
        raise ForgeError(
            f"'{BASELINE_TAG}' etiketi GitHub deposunda yok: demo deposu "
            "scripts/github-demo-repo-init.sh ile kurulmalı (etiketi o yazar)"
        ) from exc
    before = human.head_sha("main")
    target_tree = human.tree_sha(target)
    main_tree = human.tree_sha(before)
    if not target_tree or not main_tree:
        raise ForgeError("GitHub ağaç kimliği okunamadı (main / demo-baseline)")
    if target_tree == main_tree:
        return DemoOutcome(
            action="baseline",
            changed=False,
            main_before=before,
            main_after=before,
            testid=testid_state(human, "main"),
        )
    branch = f"{RESET_BRANCH}-{before[:12]}"
    head = human.commit_tree(branch, target_tree, RESET_COMMIT_MESSAGE, before)
    if human.tree_sha(head) != target_tree:
        raise ForgeError(f"'{branch}' ağacı demo-baseline ağacı değil; merge edilmedi")
    govde = (
        f"Demo sıfırlaması: main'in ağacı `{BASELINE_TAG}` ({target[:12]}) ağacına döner; "
        "geçmiş korunur (force-push yok). Kırılma, onarım ve üretilen testler bu commit'le geri "
        f"alınır.\n\n{GITHUB_INSAN_NOTU}"
    )
    pr = human.find_open_pr(branch) or human.open_pr(branch, RESET_PR_TITLE, govde, BREAK_LABELS)
    if pr.head_sha != head:
        raise ForgeError(
            f"'{branch}' PR head'i ({pr.head_sha[:12]}) yazılan commit'ten ({head[:12]}) farklı; "
            "merge edilmedi"
        )
    result = human.merge_pr_detailed(pr.number, actor, expected_head_sha=head)
    after = human.head_sha("main")
    after_tree = human.tree_sha(after)
    final = testid_state(human, "main")
    ci_info = _trigger_push_ci(ci, after, actor) if after != before else None
    audit_id = audit.append(
        actor,
        AUDIT_BASELINE,
        f"pr:{pr.number}",
        {
            "yontem": "baseline-agaci-pr",
            "pr": pr.number,
            "dal": branch,
            "head_sha": head,
            "merge_sha": result.sha,
            "bypass": result.bypass,
            "bypass_nedeni": result.bypass_reason,
            "main_once": before,
            "main_sonra": after,
            "hedef": BASELINE_TAG,
            "hedef_sha": target,
            "hedef_agac": target_tree,
            "main_agac_sonra": after_tree,
            "testid": final,
            "kimlik": _kimlik(human),
            "github_merge_eden": getattr(result, "github_merge_eden", None),
            "ci": ci_info,
        },
    )
    if after_tree != target_tree:
        raise ForgeError(
            f"merge sonrası main ağacı demo-baseline ağacı değil ({str(after_tree)[:12]}); "
            "main bu arada ilerlemiş olabilir — sıfırlamayı yeniden deneyin"
        )
    return DemoOutcome(
        action="baseline",
        changed=True,
        main_before=before,
        main_after=after,
        testid=final,
        pr_number=pr.number,
        merge=result,
        audit_id=audit_id,
        ci_run_id=ci_info["run_id"] if ci_info else None,
        ci_error=ci_info["hata"] if ci_info else None,
    )


def is_local_forge(forge: Any) -> bool:
    return callable(getattr(forge, "reset_branch", None))


def demo_break(forge: Any, audit: AuditLog, *, actor: str = BYPASS_ACTOR,
               ci: CiTrigger | None = None) -> DemoOutcome:  # fmt: skip
    """Kipe göre kırılma: yerel forge → `break_locator`; GitHub → `break_locator_github`."""
    if is_local_forge(forge):
        return break_locator(forge, audit, actor=actor, ci=ci)
    return break_locator_github(forge, audit, actor=actor, ci=ci)


def demo_baseline(forge: Any, audit: AuditLog, *, actor: str = BYPASS_ACTOR,
                  ci: CiTrigger | None = None) -> DemoOutcome:  # fmt: skip
    """Kipe göre sıfırlama: yerel forge → `restore_baseline`; GitHub → baseline ağacı PR'ı."""
    if is_local_forge(forge):
        return restore_baseline(forge, audit, actor=actor, ci=ci)
    return restore_baseline_github(forge, audit, actor=actor, ci=ci)


def main_is_baseline(forge: Any, main: str, baseline: str | None) -> bool:
    """main baseline'da mı: aynı commit ya da (GitHub sıfırlaması sonrası) aynı kök ağaç."""
    if baseline is None:
        return False
    if baseline == main:
        return True
    if is_local_forge(forge):
        return False
    tree_fn = getattr(forge, "tree_sha", None)
    if not callable(tree_fn):
        return False
    try:
        agac = tree_fn(main, "")
        return bool(agac) and agac == tree_fn(baseline, "")
    except ForgeError:
        return False


# ------------------------------------------------------------- çalışan demo-app-web

# Çalışırken demo-app-web'i yeniden oluşturmak bu işleri öldürür (bağlantı / `app` uyuşmazlığı →
# kalan testler environment/unknown sınıflanır).
WEB_BUSY_JOBS = ("ci.run", "repair.fix")


def _hex(value: Any) -> str | None:
    ok = isinstance(value, str) and 7 <= len(value) <= 64
    return value if ok and all(c in "0123456789abcdef" for c in value) else None


def web_state(
    forge: ForgePort,
    *,
    build_json: Mapping[str, Any] | None,
    sha_file: str | None,
    busy: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Çalışan demo-app-web forge `main`'i yansıtıyor mu (yeniden derleme gerekli mi)?

    `guncel`: çalışan konteynerin `/build.json` beyanı main'in commit'i ya da main'in `web/` ağacı.
    Çalışma ağacından (compose) derlenmiş imajın `sha`'sı boştur → güncel sayılmaz (bilinmiyor).
    `sha_dosyasi_guncel`: `/forge/demo-app-web.sha` main mi (değilse yalnızca dosya yazılır,
    konteyner yeniden oluşturulmaz). `mesgul`: koşan `ci.run`/`repair.fix` işleri
    (None = okunamadı).
    """
    main = forge.head_sha("main")
    tree_fn = getattr(forge, "tree_sha", None)
    main_tree: str | None = None
    if tree_fn is not None:
        try:
            main_tree = tree_fn(main, app_path(forge, "web"))
        except ForgeError:
            main_tree = None
    bj = build_json or {}
    run_sha, run_tree = _hex(bj.get("sha")), _hex(bj.get("web_tree"))
    if run_sha is not None and (run_sha == main or main.startswith(run_sha)):
        guncel, neden = True, "aynı commit"
    elif run_tree is not None and main_tree is not None and run_tree == main_tree:
        guncel, neden = True, "aynı web/ ağacı"
    elif not bj:
        guncel, neden = False, "çalışan uygulamanın /build.json'u okunamadı"
    elif run_sha is None:
        guncel, neden = False, "çalışan imaj çalışma ağacından derlenmiş (sha yok)"
    else:
        guncel, neden = False, f"çalışan uygulama {run_sha[:12]}, main {main[:12]}"
    dosya = _hex((sha_file or "").strip())
    return {
        "main": main,
        "main_web_tree": main_tree,
        "calisan": {"sha": run_sha, "web_tree": run_tree} if bj else None,
        "sha_dosyasi": dosya,
        "guncel": guncel,
        "neden": neden,
        "sha_dosyasi_guncel": dosya is not None and (dosya == main or main.startswith(dosya)),
        "mesgul": None if busy is None else [dict(b) for b in busy],
    }


def _busy_jobs() -> list[dict[str, Any]]:
    """Koşan `ci.run` / `repair.fix` işleri (Postgres)."""
    from sqlalchemy import text

    from tp_core.db import get_engine

    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, tur FROM job WHERE tur IN (:a, :b) AND durum = 'running' "
                "ORDER BY olusturma"
            ),
            {"a": WEB_BUSY_JOBS[0], "b": WEB_BUSY_JOBS[1]},
        ).all()
    return [{"id": str(r[0]), "tur": str(r[1])} for r in rows]


def _web_inputs() -> tuple[dict[str, Any] | None, str | None]:
    from tp_core.features.demo import web

    return web.build_json(), web.sha_dosyasindaki()


# ---------------------------------------------------------------------- CLI


def _pg_audit() -> AuditLog:
    """Postgres denetim kaydı; forge'a dokunmadan önce bağlantı doğrulanır."""
    from tp_core.audit import PgAuditLog
    from tp_core.db import get_engine, ping

    ping()
    return PgAuditLog(get_engine())


def _enqueue_push_ci(sha: str, actor: str, eylem: str = "make") -> str:
    """`sha` için push CI'ı — çalışan demo-app-web onu yansıtınca (Faz 4 entegrasyonu).

    `make break`/`make demo-baseline` merge'den SONRA demo-app-web'i yeniden derler; CI hemen
    kuyruğa girerse toolchain `/check` `app=farkli` görür ve koşu `environment` olur (locator
    onarım yolu hiç başlamaz). Bu yüzden `demo.await_web` işi planlanır: uygulama main'i
    yansıtınca `enqueue_ci(sha, "push")` çağrılır. Dönen değer bekleme işinin kimliğidir
    (`await-web:<job_id>`); koşu kimliği iş sonucundadır.
    """
    from tp_core.db import get_engine
    from tp_core.features.demo.service import ci_after_web

    with get_engine().begin() as conn:
        job_id = ci_after_web(conn, sha, eylem, actor)
    return f"await-web:{job_id}"


def _github_push_ci(sha: str, actor: str, eylem: str = "make") -> str | None:
    """GitHub kipi (`make break` / `make demo-baseline`): main'in Actions `push` koşusu doğrudan
    izlenir (CI çalışan uygulamaya bağlı değil: GitHub runner uygulamayı checkout'tan başlatır) ve
    çalışan demo-app-web'in GitHub main'inden yeniden derlenmesi istenir (locator onarımının
    `/locator-probe` + `/check` ölçümü için; host'ta `scripts/demo-web-sync.sh`)."""
    from tp_core.db import get_engine
    from tp_core.features.demo.service import github_ci_ve_web

    out = github_ci_ve_web(get_engine(), sha, eylem, actor)
    return out.get("ci_run_id")


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    audit: AuditLog | None = None,
    ci: CiTrigger | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="forge_demo", description="Demo kırılması / sıfırlama")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("break", help="demo/break-locator PR'ını demo-admin bypass'ıyla merge eder")
    sub.add_parser(
        "baseline", help="main'i demo-baseline'a döndürür (GitHub: baseline ağacı PR'ı, insan)"
    )
    sub.add_parser("status", help="main sha ve testid durumu")
    arc = sub.add_parser("archive", help="ref'teki dizinin tar arşivi (stdout)")
    arc.add_argument("--ref", default="main")
    arc.add_argument("--path", default="web")
    sub.add_parser("web-state", help="çalışan demo-app-web main'i yansıtıyor mu (JSON)")
    sub.add_parser("web-path", help="forge kipi ve web dizininin depo içi yolu (JSON; API yok)")
    args = parser.parse_args(argv)

    forge = get_forge(env)
    try:
        if args.cmd == "web-path":
            # Host betiği (demo-web-sync.sh) için: GitHub'a istek atmaz.
            yol = {"kip": "local" if is_local_forge(forge) else "github",
                   "web_yolu": app_path(forge, "web")}  # fmt: skip
            print(json.dumps(yol, ensure_ascii=False))
            return 0
        if args.cmd == "archive":
            archive = getattr(forge, "archive", None)
            if archive is None:
                raise ForgeValidationError("arşiv yalnızca yerel forge'da (TP_FORGE=local)")
            sys.stdout.buffer.write(archive(args.ref, args.path))
            sys.stdout.buffer.flush()
            return 0
        if args.cmd == "web-state":
            build, sha_file = _web_inputs()
            try:
                busy: list[dict[str, Any]] | None = _busy_jobs()
            except Exception as exc:  # DB yoksa: yalnızca uyarı (meşguliyet bilinmiyor)
                print(f"UYARI: koşan işler okunamadı: {exc}"[:300], file=sys.stderr)
                busy = None
            out = web_state(forge, build_json=build, sha_file=sha_file, busy=busy)
        elif args.cmd == "status":
            out: dict[str, Any] = {
                "main": forge.head_sha("main"),
                "testid": testid_state(forge, "main"),
                "kip": "local" if is_local_forge(forge) else "github",
                # Host betikleri (demo-web-sync.sh) web arşivini bu yoldan alır.
                "app_root": app_root_for(forge),
                "web_yolu": app_path(forge, "web"),
            }
            # Yerel forge'da baseline sha'sı: main ondan farklıysa (make break sonrası) make up
            # demo-app-web'i çalışma ağacından değil forge main'den derlemelidir.
            try:
                out["baseline"] = forge.head_sha(BASELINE_TAG)
            except ForgeError:
                out["baseline"] = None
            out["main_baseline_mi"] = main_is_baseline(forge, out["main"], out["baseline"])
        else:
            if audit is not None:
                sink = audit
            else:
                try:
                    sink = _pg_audit()
                except Exception as exc:  # forge'a dokunmadan önce: denetimsiz değişiklik yok
                    print(f"HATA: denetim veritabanına erişilemiyor: {exc}", file=sys.stderr)
                    return 3
            fn = demo_break if args.cmd == "break" else demo_baseline
            yerel = is_local_forge(forge)
            varsayilan_ci = functools.partial(
                _enqueue_push_ci if yerel else _github_push_ci, eylem=args.cmd
            )
            res = fn(forge, sink, ci=ci or varsayilan_ci)
            if res.ci_error:
                print(f"UYARI: main CI'ı kuyruğa alınamadı: {res.ci_error}", file=sys.stderr)
            out = res.model_dump(mode="json")
    except ForgeError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
