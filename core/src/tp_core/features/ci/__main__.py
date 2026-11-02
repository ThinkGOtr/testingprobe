"""CI operatör komutları (core-worker içinde çalışır; GitHub kimlik bilgisi yalnızca orada).

    python -m tp_core.features.ci aria-doldur <run_id> [<run_id> ...] [--isteyen AD]

`aria-doldur`: GitHub kaynaklı koşunun `test-local-results` artefaktındaki `<sayfa>.aria.yml`
dosyalarını `run_aria`'ya (0016) geri doldurur — 0016 öncesi içe aktarılan yeşil koşuların locator
onarımına son yeşil aria kanıtı olabilmesi için. İdempotent (var olan yollar yeniden yazılmaz);
denetim kaydı `ci.aria_snapshots_backfilled`. `run_id` tam UUID ya da en az 8 karakterlik tekil
önek olabilir. Çıktı koşu başına tek satır JSON'dur.
Çıkış: 0 tamam · 3 en az bir koşu reddedildi · 2 kullanım hatası.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections.abc import Sequence
from typing import Any

RED_KODU = 3
ONEK_RE = re.compile(r"^[0-9a-f-]{8,36}$")


def _run_bul(session: Any, kimlik: str) -> Any:
    from sqlalchemy import String, cast, select

    from tp_core.features.ci.service import CiError
    from tp_core.models import Run

    k = kimlik.strip().lower()
    try:
        return session.get(Run, uuid.UUID(k))
    except ValueError:
        pass
    if not ONEK_RE.match(k):
        raise CiError(f"geçersiz koşu kimliği: {kimlik!r}")
    adaylar = session.scalars(select(Run).where(cast(Run.id, String).like(f"{k}%")).limit(2)).all()
    if len(adaylar) > 1:
        raise CiError(f"'{kimlik}' öneki birden çok koşuya uyuyor; tam kimlik verin")
    return adaylar[0] if adaylar else None


def aria_doldur(kimlik: str, isteyen: str) -> dict[str, Any]:
    from tp_core.features.ci import service
    from tp_core.models import session_scope

    with session_scope() as s:
        run = _run_bul(s, kimlik)
        if run is None:
            raise service.CiError(f"koşu yok: {kimlik}")
        return service.github_aria_doldur(s, run, isteyen)


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tp_core.features.ci")
    alt = p.add_subparsers(dest="komut", required=True)
    a = alt.add_parser("aria-doldur", help="GitHub koşusunun aria snapshot'larını geri doldurur")
    a.add_argument("run_id", nargs="+")
    a.add_argument("--isteyen", default="operator")
    args = p.parse_args(argv)
    from tp_core.features.ci.clients import GitHubCiError
    from tp_core.features.ci.service import CiError

    kod = 0
    for kimlik in args.run_id:
        try:
            out = aria_doldur(kimlik, args.isteyen)
        except (CiError, GitHubCiError) as exc:
            hata = {"tamam": False, "run": kimlik, "neden": str(exc)}
            print(json.dumps(hata, ensure_ascii=False))
            kod = RED_KODU
            continue
        print(json.dumps({"tamam": True, **out}, ensure_ascii=False, default=str))
    return kod


if __name__ == "__main__":
    sys.exit(main())
