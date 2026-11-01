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
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from pydantic import BaseModel

from tp_core.integrations.forge import (
    BYPASS_ACTOR,
    ForgeError,
    ForgeValidationError,
    MergeResult,
    get_forge,
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
AUDIT_BREAK = "demo kırılması"
AUDIT_BASELINE = "demo sıfırlaması"
CI_TRIGGER = "push"

# (yeni main sha, aktör) → kuyruğa alınan CI koşusunun kimliği.
CiTrigger = Callable[[str, str], Any]


# Kırılma dalında değişebilecek en fazla dosya (demo-app'te 1; sınır savunma amaçlı).
MAX_BREAK_FILES = 5


class DemoForge(ForgePort, Protocol):
    """`merge_pr_detailed`, `merge_base`, `changed_paths` sunan forge (LocalForge, GitHubForge)."""

    def merge_pr_detailed(
        self, number: int, actor: str, *, expected_head_sha: str | None = None
    ) -> MergeResult: ...

    def merge_base(self, a: str, b: str) -> str: ...

    def changed_paths(self, base: str, head: str) -> list[str] | None: ...


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


def _quoted_hits(forge: ForgePort, value: str, ref: str) -> list[tuple[str, int, str]]:
    """web/src altında tırnak içinde `value` geçen satırlar (yalnızca testid değeri)."""
    hits = []
    for path, line_no, line in forge.search_code(value, ref):
        if not path.startswith(WEB_SRC_PREFIX):
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
        metin = forge.read_file(E2E_LOCATOR_PATH, ref)
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


def verify_break_diff(forge: DemoForge, head_sha: str, base_ref: str = "main") -> dict[str, Any]:
    """`ortak-ata(base_ref, head_sha)..head_sha` farkı yalnızca testid değişimi mi? Değilse hata.

    Dönen değer denetim için fark özetidir: {head, taban, dosyalar, degisen_satir}.
    """
    merge_base = getattr(forge, "merge_base", None)
    changed_paths = getattr(forge, "changed_paths", None)
    if not callable(merge_base) or not callable(changed_paths):
        raise ForgeValidationError(
            "forge kırılma farkını doğrulayamıyor (merge_base/changed_paths)"
        )
    base = merge_base(base_ref, head_sha)
    paths = changed_paths(base, head_sha)
    if paths is None:
        raise ForgeError(f"'{BREAK_BRANCH}' farkı okunamadı (liste kesilmiş olabilir)")
    if not paths:
        raise ForgeError(f"'{BREAK_BRANCH}' dalında {base_ref}'e göre değişiklik yok")
    if len(paths) > MAX_BREAK_FILES:
        raise ForgeError(
            f"'{BREAK_BRANCH}' beklenenden çok dosya değiştiriyor "
            f"({len(paths)} > {MAX_BREAK_FILES})"
        )
    disari = [p for p in paths if not p.startswith(WEB_SRC_PREFIX)]
    if disari:
        raise ForgeError(f"'{BREAK_BRANCH}' {WEB_SRC_PREFIX} dışını değiştiriyor: {disari[:5]}")
    satir = 0
    for path in paths:
        try:
            old = forge.read_file(path, base)
            new = forge.read_file(path, head_sha)
        except ForgeError as exc:  # ekleme/silme/yeniden adlandırma
            raise ForgeError(
                f"'{BREAK_BRANCH}' yalnızca mevcut dosyada testid değiştirebilir: {path} ({exc})"
            ) from exc
        if "\ufffd" in old or "\ufffd" in new:
            raise ForgeError(f"'{BREAK_BRANCH}' metin olmayan içerik değiştiriyor: {path}")
        old_lines, new_lines = old.split("\n"), new.split("\n")
        if len(old_lines) != len(new_lines):
            raise ForgeError(f"'{BREAK_BRANCH}' satır ekliyor/siliyor: {path}")
        degisen = 0
        for no, (a, b) in enumerate(zip(old_lines, new_lines, strict=True), start=1):
            if a == b:
                continue
            if _swap_testid(a) != b:
                raise ForgeError(
                    f"'{BREAK_BRANCH}' beklenmeyen değişiklik içeriyor: {path}:{no} "
                    f"(yalnızca '{OLD_TESTID}' → '{NEW_TESTID}' izinli)"
                )
            degisen += 1
        if degisen == 0:  # yalnızca kip/ikili değişiklik
            raise ForgeError(f"'{BREAK_BRANCH}' içerik dışı değişiklik içeriyor: {path}")
        satir += degisen
    return {"head": head_sha, "taban": base, "dosyalar": paths, "degisen_satir": satir}


def break_locator(
    forge: DemoForge,
    audit: AuditLog,
    *,
    actor: str = BYPASS_ACTOR,
    ci: CiTrigger | None = None,
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
    head = forge.head_sha(BREAK_BRANCH)
    if testid_state(forge, head) != NEW_TESTID:
        raise ForgeError(f"'{BREAK_BRANCH}' dalı beklenen kırılmayı ({NEW_TESTID}) içermiyor")
    # Bypass yalnızca doğrulanmış testid değişimi için: fark PR açılmadan önce, head'e bağlı.
    fark = verify_break_diff(forge, head, "main")

    pr = forge.find_open_pr(BREAK_BRANCH) or forge.open_pr(
        BREAK_BRANCH, BREAK_PR_TITLE, BREAK_PR_BODY, BREAK_LABELS
    )
    if pr.head_sha != head:
        raise ForgeError(
            f"'{BREAK_BRANCH}' PR head'i ({pr.head_sha[:12]}) doğrulanan head'den ({head[:12]}) "
            "farklı; merge edilmedi"
        )
    result = forge.merge_pr_detailed(pr.number, actor, expected_head_sha=head)
    after = forge.head_sha("main")
    final = testid_state(forge, "main")
    ci_info = _trigger_push_ci(ci, after, actor) if after != before else None
    ozet: dict[str, Any] = {
        "pr": pr.number,
        "dal": BREAK_BRANCH,
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
            main_tree = tree_fn(main, "web")
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
    sub.add_parser("baseline", help="main'i demo-baseline'a döndürür (yalnızca yerel forge)")
    sub.add_parser("status", help="main sha ve testid durumu")
    arc = sub.add_parser("archive", help="ref'teki dizinin tar arşivi (stdout)")
    arc.add_argument("--ref", default="main")
    arc.add_argument("--path", default="web")
    sub.add_parser("web-state", help="çalışan demo-app-web main'i yansıtıyor mu (JSON)")
    args = parser.parse_args(argv)

    forge = get_forge(env)
    try:
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
            }
            # Yerel forge'da baseline sha'sı: main ondan farklıysa (make break sonrası) make up
            # demo-app-web'i çalışma ağacından değil forge main'den derlemelidir.
            try:
                out["baseline"] = forge.head_sha(BASELINE_TAG)
            except ForgeError:
                out["baseline"] = None
            out["main_baseline_mi"] = out["baseline"] == out["main"]
        else:
            if audit is not None:
                sink = audit
            else:
                try:
                    sink = _pg_audit()
                except Exception as exc:  # forge'a dokunmadan önce: denetimsiz değişiklik yok
                    print(f"HATA: denetim veritabanına erişilemiyor: {exc}", file=sys.stderr)
                    return 3
            fn = break_locator if args.cmd == "break" else restore_baseline
            varsayilan_ci = functools.partial(_enqueue_push_ci, eylem=args.cmd)
            res = fn(forge, sink, ci=ci or varsayilan_ci)  # type: ignore[arg-type]
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
