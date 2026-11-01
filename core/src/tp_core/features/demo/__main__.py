"""Host betikleri için demo denetimleri (core-worker içinde çalışır; API oturumu gerektirmez).

    python -m tp_core.features.demo on-kosul [--isteyen AD] [--zorla]
    python -m tp_core.features.demo web-istek [--eylem sync] [--isteyen AD]

`make break` (host yolu: `scripts/demo-break.sh --make` → `forge-init.sh break`) core API'sini
atlar; `POST /demo/break-locator`'ın yeşil-koşu ve yerel-forge denetimleri burada da uygulanır.
Çıktı tek satır JSON'dur. Çıkış: 0 kırılabilir · 3 reddedildi (yeşil temel koşu yok ya da GitHub
kipinde insan kimliği `GITHUB_MERGE_TOKEN` yok; `demo.break_refused` denetime yazılır) · 2 kullanım
hatası.

`web-istek`: forge `main`'in güncel head'i için demo-app-web yenileme isteği yazar
(`scripts/demo-web-sync.sh --main`; ör. GitHub kipinde `make up` sonrası çalışan uygulamayı GitHub
main'iyle eşitlemek için). Çıktı: istek JSON'u.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

RED_KODU = 3


def kirilma_on_denetimi(isteyen: str, *, zorla: bool = False) -> tuple[int, dict[str, object]]:
    from tp_core.audit import audit_on_commit
    from tp_core.features.demo import service
    from tp_core.models import session_scope

    with session_scope() as s:
        if not service._yerel_forge_kipi() and not (os.environ.get("GITHUB_MERGE_TOKEN") or ""):
            neden = service.GITHUB_INSAN_KIMLIGI_YOK
            audit_on_commit(s, isteyen, "demo.break_refused", "forge:main",
                            {"neden": "GitHub kipi: insan kimliği (GITHUB_MERGE_TOKEN) yok",
                             "yol": "make break", "yonerge": neden})  # fmt: skip
            return RED_KODU, {"hazir": False, "neden": neden}
        on = service.onarim_on_kosulu(s)
        if on["hazir"]:
            return 0, on
        if zorla:
            audit_on_commit(s, isteyen, "demo.break_forced", "forge:main",
                            {"neden": "son yeşil koşu yok", "yol": "make break"})  # fmt: skip
            return 0, {
                **on,
                "uyari": "yeşil temel koşu yok; onarım 'son yeşil yok' ile engellenecek",
            }
        audit_on_commit(s, isteyen, "demo.break_refused", "forge:main",
                        {"neden": "son yeşil koşu yok", "yol": "make break",
                         "yonerge": service.ON_KOSUL_YONERGE})  # fmt: skip
        return RED_KODU, {**on, "neden": "Kırılma yapılmadı: kırılmadan önce yeşil koşu yok. "
                          + service.ON_KOSUL_YONERGE}  # fmt: skip


def web_istegi(eylem: str, isteyen: str) -> dict[str, object]:
    """Forge main'in güncel head'i için demo-app-web yenileme isteği (host betiği uygular)."""
    from tp_core.features.demo import service

    sha = service._forge().head_sha("main")
    return service._yenileyici().iste(sha, eylem, isteyen)


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tp_core.features.demo")
    alt = p.add_subparsers(dest="komut", required=True)
    k = alt.add_parser("on-kosul", help="make break öncesi yeşil temel koşu / forge kipi denetimi")
    k.add_argument("--isteyen", default="make-break")
    k.add_argument("--zorla", action="store_true")
    w = alt.add_parser("web-istek", help="forge main için demo-app-web yenileme isteği yazar")
    w.add_argument("--eylem", default="sync", choices=("sync", "break", "baseline"))
    w.add_argument("--isteyen", default="demo-web-sync")
    a = p.parse_args(argv)
    if a.komut == "web-istek":
        print(json.dumps(web_istegi(a.eylem, a.isteyen), ensure_ascii=False, default=str))
        return 0
    kod, out = kirilma_on_denetimi(a.isteyen, zorla=a.zorla)
    print(json.dumps(out, ensure_ascii=False, default=str))
    return kod


if __name__ == "__main__":
    sys.exit(main())
