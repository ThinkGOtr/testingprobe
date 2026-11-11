"""Onaylı case'lerin test yönetimine yayını (TEKNIK-TASARIM §8.3).

Denetim kapısı (specs/011 K3) paket yüklenirken bağlanır: core-api (router keşfi), core-worker
(`publish.jobs` keşfi) ve testler aynı yoldan geçer; kapı `TP_DENETIM_KAPISI=off` ile kapanır.
"""

from tp_core.features.cases.denetim_akisi import bind_gate as _bind_gate

_bind_gate()
