"""Triage operatör komutları (core-worker içinde çalışır; API oturumu gerektirmez).

    python -m tp_core.features.triage yeniden <run_id> [--isteyen AD] [--kanit-doldurma]

`yeniden`: koşunun triage çıktılarını siler ve koşuyu yeniden sınıflandırır. GitHub kaynaklı
koşuda önce `test-local-results` artefaktındaki `error-context.md`'lerden eksik hata bağlamı
(`test_result_ek.hata_baglami`) geri doldurulur (`--kanit-doldurma` bunu atlar). Failure kayıtları
bug taslağına / onarım script'ine bağlıysa reddedilir. Çıktı tek satır JSON'dur.
Çıkış: 0 tamam · 3 reddedildi · 2 kullanım hatası.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Sequence
from typing import Any

RED_KODU = 3


def yeniden(run_id: uuid.UUID, isteyen: str, *, kanit_doldur: bool = True) -> dict[str, Any]:
    from tp_core.db import get_engine
    from tp_core.features.triage import service
    from tp_core.models import Run, session_scope

    out: dict[str, Any] = {"run_id": str(run_id)}
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise service.YenidenTriageReddi("koşu yok")
        github = run.kaynak == "github"
    if kanit_doldur and github:
        from tp_core.features.ci import service as ci_service

        with session_scope() as s:
            run = s.get(Run, run_id)
            assert run is not None
            out["kanit"] = ci_service.github_hata_baglami_doldur(s, run)
    with session_scope() as s:
        out["sifirlama"] = service.triage_sifirla(s, run_id, isteyen)
    out["triage"] = service.classify_run(get_engine(), run_id)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tp_core.features.triage")
    alt = p.add_subparsers(dest="komut", required=True)
    y = alt.add_parser("yeniden", help="koşunun triage'ını sıfırlayıp yeniden sınıflandırır")
    y.add_argument("run_id", type=uuid.UUID)
    y.add_argument("--isteyen", default="operator")
    y.add_argument("--kanit-doldurma", action="store_true", help="GitHub kanıt geri doldurma yok")
    a = p.parse_args(argv)
    from tp_core.features.ci.clients import GitHubCiError
    from tp_core.features.ci.service import CiError
    from tp_core.features.triage.service import YenidenTriageReddi

    try:
        out = yeniden(a.run_id, a.isteyen, kanit_doldur=not a.kanit_doldurma)
    except (YenidenTriageReddi, CiError, GitHubCiError) as exc:
        print(json.dumps({"tamam": False, "neden": str(exc)}, ensure_ascii=False))
        return RED_KODU
    print(json.dumps({"tamam": True, **out}, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
