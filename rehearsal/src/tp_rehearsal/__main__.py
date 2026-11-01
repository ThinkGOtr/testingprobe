"""Demo provası CLI.

    uv run --project rehearsal python -m tp_rehearsal               # tam prova (yığını değiştirir)
    uv run --project rehearsal python -m tp_rehearsal --kip denetim # salt okuma: son durum
    uv run --project rehearsal python -m tp_rehearsal --adim P0     # yalnızca seçili adım(lar)

Çıkış kodu: 0 = tüm adımlar PASS ve toplam bütçe içinde; 1 = herhangi bir FAIL / bütçe aşımı /
REPLAY-MISS; 2 = kullanım hatası (ör. parola yok). Rapor: rehearsal/reports/<zaman>/.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from tp_rehearsal import report
from tp_rehearsal.client import JiraSim, PortalIstemcisi
from tp_rehearsal.env import Ortam
from tp_rehearsal.runner import Baglam, Calistirici
from tp_rehearsal.stack import Yigin
from tp_rehearsal.steps import TOPLAM_BUTCE_S, adimlar

REPO = Path(__file__).resolve().parents[3]


def _arguman() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tp_rehearsal", description="AI Testing Probe demo provası (14 adım + locator)"
    )
    p.add_argument(
        "--kip",
        choices=("prova", "denetim"),
        default="prova",
        help="prova: sunucu gibi eylem yapar; denetim: yalnızca doğrular (salt okuma)",
    )
    p.add_argument(
        "--adim",
        action="append",
        default=None,
        help="yalnızca bu adım(lar) (ör. P0, B1); tekrarlanabilir",
    )
    p.add_argument(
        "--devam", action="store_true", help="bir adım başarısız olsa da sonrakileri dene"
    )
    p.add_argument("--butce-uyari", action="store_true", help="adım bütçesi aşımı FAIL değil UYARI")
    p.add_argument(
        "--strict-gerekmez",
        action="store_true",
        help="TP_REPLAY_STRICT=1 değilse P0 FAIL yerine UYARI (geliştirme; prova sayılmaz)",
    )
    p.add_argument(
        "--canli-izinli",
        action="store_true",
        help="TP_MODEL_MODE=replay değilse P0 FAIL yerine UYARI (canlı; §13 provası sayılmaz)",
    )
    p.add_argument(
        "--bekleme-carpani", type=float, default=1.0, help="zaman aşımlarını çarpar (yavaş makine)"
    )
    p.add_argument("--rapor-dizini", type=Path, default=REPO / "rehearsal" / "reports")
    p.add_argument(
        "--rapor-yolu",
        type=Path,
        default=None,
        help="raporun tam dizini (scripts/demo-prova.sh koşu başına verir; --rapor-dizini'ni ezer)",
    )
    p.add_argument(
        "--kirma-yayinla",
        action="store_true",
        help="isteğe bağlı C6: kırma taslağını yeni Bug olarak yayınla (Relates + Test bağı)",
    )
    p.add_argument(
        "--kosu-no", type=int, default=None, help="scripts/demo-prova.sh'ın koşu sırası (rapora)"
    )
    p.add_argument("--repo", type=Path, default=REPO)
    return p


def rapor_adi(zaman: datetime, kosu_no: int | None, kip: str) -> str:
    """Yerel saatle (demo-prova özetiyle aynı saat dilimi) rapor dizini adı."""
    return (
        zaman.strftime("%Y%m%d-%H%M%S")
        + (f"-k{kosu_no}" if kosu_no is not None else "")
        + ("-denetim" if kip == "denetim" else "")
    )


def main(argv: list[str] | None = None) -> int:
    a = _arguman().parse_args(argv)
    ortam = Ortam.yukle(a.repo)
    if not ortam.portal_parolasi:
        print(
            "HATA: portal parolası yok (.env SEED_USER_PASSWORD ya da TP_PROVA_PAROLA)",
            file=sys.stderr,
        )
        return 2
    dizin = a.rapor_yolu or a.rapor_dizini / rapor_adi(datetime.now(), a.kosu_no, a.kip)
    log_satirlari: list[str] = []

    def log(m: str) -> None:
        m = ortam.sirlar.maskele(m)
        satir = f"{datetime.now().strftime('%H:%M:%S')} {m}"
        log_satirlari.append(satir)
        print(satir, flush=True)

    api = PortalIstemcisi(ortam.api_url, ortam.portal_parolasi)
    jira = JiraSim(ortam.jira_url, ortam.po_parolasi)
    yigin = Yigin(a.repo, ortam.sirlar)
    b = Baglam(
        kip=a.kip,
        api=api,
        jira=jira,
        yigin=yigin,
        ortam=ortam,
        log=log,
        bekleme_carpani=a.bekleme_carpani,
    )
    b.veri["strict_gerekmez"] = a.strict_gerekmez
    b.veri["canli_izinli"] = a.canli_izinli

    log(f"Demo provası başlıyor — kip {a.kip}, API {ortam.api_url}, jira-sim {ortam.jira_url}")
    baslangic = datetime.now().astimezone().isoformat(timespec="seconds")
    t0 = time.monotonic()
    sonuclar = Calistirici(
        adimlar(kirma_yayinla=a.kirma_yayinla),
        b,
        devam=a.devam,
        butce_uyari=a.butce_uyari,
        secili=set(a.adim) if a.adim else None,
    ).calistir()
    toplam = time.monotonic() - t0

    notlar = []
    if a.kip == "prova":
        notlar.append(
            "API provası kararları insan bekleme süresi olmadan verir: portaldaki review süresi "
            "ölçüsü sunumu temsil etmez (case-metrics `review_sure_ms`)."
        )
        notlar.append(
            "Toplam süre makine süresidir; sunumda anlatım/bekleme payı eklenir "
            "(§1: 20–25 dk canlı akış)."
        )
    if a.kip == "prova" and b.veri.get("model_modu") not in (None, "replay"):
        notlar.append(
            f"Model kipi {b.veri.get('model_modu')!r}: canlı model çağrıları yapılmış olabilir; "
            "bu koşu strict REPLAY provası (TEKNIK-TASARIM §13) sayılmaz."
        )
    if b.veri.get("manuel_baz_s"):
        notlar.append(
            "Manuel baz değer yapılandırmadan okundu: "
            f"TP_MANUAL_BASELINE_S={b.veri['manuel_baz_s']} sn (prova değer üretmez; kaynağı F0 "
            "ölçümü olmalı)."
        )
    else:
        notlar.append("Manuel baz değer girilmedi: kazanç oranı gösterilmez (uydurulmaz).")
    worker = next((s.kanit.get("core_worker") for s in sonuclar if s.no == "P0"), None) or {}
    oz = report.ProvaOzeti(
        kip=a.kip,
        baslangic=baslangic,
        bitis=datetime.now().astimezone().isoformat(timespec="seconds"),
        toplam_s=toplam,
        toplam_butce_s=TOPLAM_BUTCE_S,
        model_modu=worker.get("TP_MODEL_MODE", ""),
        replay_strict=worker.get("TP_REPLAY_STRICT", ""),
        adimlar=sonuclar,
        notlar=notlar,
        kosu_no=a.kosu_no,
    )
    komut_logu = (
        "\n".join(log_satirlari)
        + "\n\n"
        + "\n".join(
            f"$ {k.komut}  (çıkış {k.kod}, {k.sure_s} sn)\n{k.cikti}" for k in yigin.komutlar
        )
    )
    cagri_logu = "rol\työntem\tyol\tdurum\tsüre_s\n" + "\n".join(
        f"{c.rol}\t{c.yontem}\t{c.yol}\t{c.durum}\t{c.sure_s}" for c in api.kayitlar
    )
    report.yaz(oz, dizin, ortam.sirlar.maskele, komut_logu, cagri_logu)
    print()
    print(report.konsol_tablosu(oz))
    print(f"Rapor: {dizin / 'rapor.md'}")
    return oz.cikis_kodu()


if __name__ == "__main__":
    sys.exit(main())
