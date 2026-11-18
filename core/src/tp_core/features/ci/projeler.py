"""Açılış kancalarının proje döngüsü (TP-COK-PROJE-PLANI §5.2).

Periyodik işler (gece koşusu, PR senkronu, triage/bug/hata koşusu taramaları) ve takılı kayıt
temizlikleri proje başınadır: kanca bağlamsız çağrılırsa (worker açılışı) her aktif projede
(`tp_proje WHERE aktif`) ayrı bağlam kurulur; bağlam zaten varsa (worker kancayı proje başına
çağırıyorsa) yalnız o projede koşar. Böylece kuyruğa giren iş `project_id`'yi bağlamdan alır ve
işleyici kendi projesinde çalışır (K3).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection

from tp_core.proje import kurulu_projeler, proje_icinde, varsa, varsayilan_pid


def acilis_projeleri(conn: Connection) -> list[str]:
    """Bağlam varsa yalnız o proje; yoksa aktif projeler (kayıt yoksa varsayılan proje)."""
    b = varsa()
    if b is not None:
        return [b.pid]
    return kurulu_projeler(conn) or [varsayilan_pid()]


def her_projede(conn: Connection, fn: Callable[[Connection], None]) -> None:
    """`fn(conn)`'u her açılış projesinin bağlamında sırayla çağırır."""
    if varsa() is not None:
        fn(conn)
        return
    for pid in acilis_projeleri(conn):
        with proje_icinde(pid, kaynak="sistem"):
            fn(conn)


# Uygulamaya karşı koşan uçlar: varsayılan dışı projede ortam ayarı (BASE_URL, DEMO_API_URL)
# eksikse 409 `proje_ayari_eksik` (toolchain env'e — varsayılan projenin uygulamasına — düşerdi).
KOSU_UCLARI: frozenset[str] = frozenset({"/check", "/locator-probe"})

# toolchain-worker'ın `proje` bloğu kabul eden uçları (`toolchain/worker/app.py` `proje:
# ProjeBlogu | None`): depo, sembol önbelleği ve uygulama ayarları projeye göre seçilir.
PROJE_BLOKLU_UCLAR: frozenset[str] = frozenset(
    {"/symbols", "/ast-guard", "/check", "/locator-probe", "/affected-tests"}
)


def toolchain_govdesi(yol: str, body: dict[str, Any]) -> dict[str, Any]:
    """`yol` proje bloğu kabul ediyorsa gövdenin kopyasına bloğu ekler (`toolchain_projesi`)."""
    if yol not in PROJE_BLOKLU_UCLAR or "proje" in body:
        return body
    return toolchain_projesi(dict(body), kosu=yol in KOSU_UCLARI)


def toolchain_projesi(body: dict[str, Any], *, kosu: bool = True) -> dict[str, Any]:
    """Toolchain istek gövdesine `proje` bloğunu ekler (TP-COK-PROJE-PLANI §4.4) ve gövdeyi döner.

    Varsayılan projede (ve bağlamsız çağrıda) blok eklenmez: toolchain süreç ortamı varsayılan
    projeninkidir ve gövde baytları eski toolchain'lerle (`extra="forbid"`) aynı kalır.

    Platform deposu (0046): gövdenin `platform`'u (android | ios | windows) ayrı depodaysa blok
    varsayılan projede de eklenir ve o deponun bloğudur (ayna yolu, uzak adres, Java kökü);
    toolchain koşuyu/sembol tablosunu o deponun aynasında yapar.
    """
    from tp_core.features.codegen import depo as depolar
    from tp_core.proje.ortam import mevcut_ortam

    platform = depolar.uygulama_platformu(body.get("platform"))
    ayri = bool(depolar.depo_anahtari(platform)) if platform else False
    b = varsa()
    # Test ortamı bağlamında (koşu bir Home ortamında) blok varsayılan projede de gider: adres,
    # test hesapları ve uygulama argümanları o ortamın etkin config'inden (`proje.ortam`).
    ortam = mevcut_ortam()
    if ortam is not None or ayri or (b is not None and b.pid != varsayilan_pid()):
        from tp_core.proje import istemciler

        blok = istemciler.toolchain_proje_blogu(platform)
        if kosu:
            from tp_core.integrations.toolchain_blogu import ortam_denetle

            ortam_denetle(blok)
        body["proje"] = blok
    return body
