"""Çok proje çekirdeği (TP-COK-PROJE-PLANI §2, §3.2, §4.1, Şerit 0).

Bağlam (`baglam`), merkezî ORM filtresi (`orm`), proje başına config (`ayar`), sayaç (`sayac`) ve
istemci fabrikası (`istemciler`). Bağlam API'si buradan yeniden dışa aktarılır.
"""

from tp_core.proje.baglam import (
    KURULUM,
    Kaynak,
    ProjeBaglami,
    ProjeBaglamiYok,
    ProjeIhlali,
    baglamla,
    kurulu_projeler,
    mevcut,
    mevcut_pid,
    pid_param,
    proje_icinde,
    proje_kaydet,
    varsa,
    varsayilan_pid,
)

__all__ = [
    "KURULUM",
    "Kaynak",
    "ProjeBaglami",
    "ProjeBaglamiYok",
    "ProjeIhlali",
    "baglamla",
    "kurulu_projeler",
    "mevcut",
    "mevcut_pid",
    "pid_param",
    "proje_icinde",
    "proje_kaydet",
    "varsa",
    "varsayilan_pid",
]
