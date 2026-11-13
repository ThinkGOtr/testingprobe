"""Metamorfik türetmenin kullandığı ilişki sorguları (ANALIZ §4.5, §11.2).

Tek kaynak `features/karar_tablosu/service.py`'dir; bu modül yalnız onları yeniden dışa aktarır.
Geçerli ilişki: `durum == "approved"` ve bayat değil (onay anındaki `gereksinim_hash` gereksinimin
güncel içerik hash'iyle aynı).
"""

from __future__ import annotations

from tp_core.features.karar_tablosu.service import bayat_mi, gecerli_iliskiler

__all__ = ["bayat_mi", "gecerli_iliskiler"]
