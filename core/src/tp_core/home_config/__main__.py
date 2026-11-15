"""Açılış: compose'un okuduğu env dosyasına Home etkin config'ini işler (yalnız standart kütüphane).

    PYTHONPATH=core/src python3 -m tp_core.home_config --env-dosyasi .env --lkg <yol>

Dosyadaki `CONFIG_SOURCE` `home` değilse hiçbir şey yapmaz (çıkış 0). `home` iken Home erişilemezse
LKG kullanılır; o da yoksa (ya da TP_HOME_PROJECT / Home adresi eksikse) çıkış kodu
`CIKIS_HOME_YOK` (3): açılış betiği DURUR — `home` kipinde env'e sessizce düşmek, Home'da
kapatılmış özellikleri / değiştirilmiş hedefleri yok sayardı. Geri dönüş: `CONFIG_SOURCE=env`.
Kullanım hatası 2. Değer hiçbir zaman yazdırılmaz.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from tp_core.home_config import yukleyici as y

CIKIS_HOME_YOK = 3


def calistir(
    env_dosyasi: str,
    lkg: str | None,
    *,
    http: y.Http = y.urllib_http,
    kimlik: y.MetadataKimligi | None = None,
) -> int:
    try:
        with open(env_dosyasi, encoding="utf-8") as f:
            taban = f.read()
    except OSError as exc:
        print(f"home-config: env dosyası okunamadı: {exc.strerror}", file=sys.stderr)
        return 2
    env = y.env_metni_coz(taban)
    if y.kaynak(env) != "home":
        print("home-config: CONFIG_SOURCE=env — env dosyası değiştirilmedi")
        return 0
    proje = y.ayar(env, y.PROJE_ENV)
    url, audience = y.home_adresi(env)
    if not proje or not url:
        print(
            "home-config: HATA CONFIG_SOURCE=home ama TP_HOME_PROJECT / AIPROBE_HOME_RUN_URL "
            "eksik — açılış durduruldu (geri dönüş: CONFIG_SOURCE=env)",
            file=sys.stderr,
        )
        return CIKIS_HOME_YOK
    kimlik = kimlik or y.MetadataKimligi(http)
    lkg = lkg or y.ayar(env, y.LKG_ENV) or None
    istemci = y.HomeConfigIstemcisi(url, proje, kimlik.id_token, audience=audience, http=http)
    sonuc = y.Yukleyici(istemci, lkg).yukle()
    if sonuc.cfg is None:
        print(
            f"home-config: HATA Home erişilemedi ve LKG yok ({sonuc.hata}) — açılış durduruldu "
            "(geri dönüş: CONFIG_SOURCE=env)",
            file=sys.stderr,
        )
        return CIKIS_HOME_YOK
    sir_projesi = y.ayar(env, y.SIR_PROJESI_ENV) or None
    cozucu = y.SecretManagerCozucu(kimlik.erisim_tokeni, http, sir_projesi)
    gorunum = y.env_gorunumu(sonuc.cfg, cozucu, sir_projesi=sir_projesi, taban=env)
    metin, yazilamayan = y.env_dosyasi_birlestir(taban, gorunum.degerler, gorunum.kaldirilan)
    y.atomik_yaz(env_dosyasi, metin, 0o600)
    print(
        f"home-config: kaynak={sonuc.kaynak} proje={proje} anahtar={len(gorunum.degerler)} "
        f"reddedilen={len(gorunum.reddedilen)} cozulemeyen={len(gorunum.cozulemeyen)} "
        f"yazilamayan={len(yazilamayan)} kaldirilan={len(gorunum.kaldirilan)}"
    )
    for ad, liste in (
        ("reddedilen", gorunum.reddedilen),
        ("kaldırılan (hedefe bağlı sır)", gorunum.kaldirilan),
        ("çözülemeyen sır (env değeri kaldı)", gorunum.cozulemeyen),
        ("yazılamayan", yazilamayan),
    ):
        if liste:
            print(f"home-config: {ad}: {', '.join(sorted(liste))}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tp_core.home_config")
    p.add_argument("--env-dosyasi", required=True)
    p.add_argument("--lkg", default=os.environ.get(y.LKG_ENV) or None)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="home-config: %(message)s")
    return calistir(a.env_dosyasi, a.lkg)


if __name__ == "__main__":
    sys.exit(main())
