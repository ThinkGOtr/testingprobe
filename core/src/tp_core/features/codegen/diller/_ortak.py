"""Dil eklentilerinin ortak yardımcıları (keşifte atlanır: `_` öneki)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from tp_core.features.codegen.render import RenderInput


def sizinti_tara(content: str, inp: RenderInput) -> None:
    """013 K19: üretilen kod düz sır taşımaz (`render.GizliSizinti`). Her eklenti render sonunda
    çağırır."""
    from tp_core.features.codegen import render

    render._sizinti_tara(content, inp)
