"""Demo locator kırılması ve sıfırlaması (TEKNIK-TASARIM §2 adım 12, §10, §13).

`break_locator`: `demo/break-locator` dalından PR açar (varsa açık olanı kullanır), `demo-admin`
kimliğiyle kural bypass'ı ile merge eder ve denetim kaydına "demo kırılması" yazar. Merge,
PR açıldığında okunan head sha'ya bağlıdır (`expected_head_sha`).

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

`scripts/forge-init.sh break|baseline` bu CLI'ı çağırır ve demo-app-web imajını `archive`
çıktısından (forge `main` HEAD) yeniden derler.
"""

from __future__ import annotations

import argparse
import json
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


class DemoForge(ForgePort, Protocol):
    """`merge_pr_detailed` ayrıntısını da sunan forge (LocalForge ve GitHubForge)."""

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
    if testid_state(forge, BREAK_BRANCH) != NEW_TESTID:
        raise ForgeError(f"'{BREAK_BRANCH}' dalı beklenen kırılmayı ({NEW_TESTID}) içermiyor")

    pr = forge.find_open_pr(BREAK_BRANCH) or forge.open_pr(
        BREAK_BRANCH, BREAK_PR_TITLE, BREAK_PR_BODY, BREAK_LABELS
    )
    result = forge.merge_pr_detailed(pr.number, actor, expected_head_sha=pr.head_sha)
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


# ---------------------------------------------------------------------- CLI


def _pg_audit() -> AuditLog:
    """Postgres denetim kaydı; forge'a dokunmadan önce bağlantı doğrulanır."""
    from tp_core.audit import PgAuditLog
    from tp_core.db import get_engine, ping

    ping()
    return PgAuditLog(get_engine())


def _enqueue_push_ci(sha: str, actor: str) -> str:
    """`features.ci.enqueue_ci(sha, "push")` kendi işleminde (commit edilir)."""
    from tp_core.features.ci import enqueue_ci
    from tp_core.models import session_scope

    with session_scope() as s:
        return str(enqueue_ci(s, sha, CI_TRIGGER, None, isteyen=actor))


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
        if args.cmd == "status":
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
            res = fn(forge, sink, ci=ci or _enqueue_push_ci)  # type: ignore[arg-type]
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
