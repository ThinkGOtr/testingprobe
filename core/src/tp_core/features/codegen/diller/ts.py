"""TypeScript / Playwright Test dil eklentisi (014 Ş0; 011 öncesi tam hat). Bugünkü render
işlevlerini sarmalar: çıktı bayt eşittir (`render.render_test`)."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tp_core.features.codegen import platform as platformlar
from tp_core.features.codegen.diller import AlgilaKalibi

if TYPE_CHECKING:  # pragma: no cover
    from tp_core.features.codegen.platform import Cati
    from tp_core.features.codegen.render import Rendered, RenderInput


class _Ts:
    ad = platformlar.TS
    proje_dosyasi = "package.json"
    algila_kaliplari = (AlgilaKalibi(frozenset({platformlar.WEB}), "TP_E2E_ROOT", "tests/"),)

    def render(
        self,
        inp: RenderInput,
        cati: Cati,
        rules: Path,
        *,
        referans_dil: str | None = None,
        sembol_tablosu: Mapping[str, Any] | None = None,
    ) -> Rendered:
        from tp_core.features.codegen import render

        return render.render_test(inp, rules)

    def literal(self, value: Any) -> str:
        from tp_core.features.codegen import render

        return render.ts_literal(value)

    def ident(self, value: Any) -> str:
        from tp_core.features.codegen import render

        return render.ident(value)

    def sinif_adi(
        self, story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID
    ) -> str | None:
        return None

    def uretilen_yol(
        self, cati: Cati, kok: str, story_key: str | None, sira_no: int, case_id: uuid.UUID
    ) -> str:
        from tp_core.features.codegen import render

        ad = render.slug(story_key, sira_no, case_id)
        return f"{kok.strip('/')}/{cati.uretilen_alt_yol}/{ad}.spec.ts"

    def test_dosyasi_mi(self, yol: str) -> bool:
        return yol.endswith(".spec.ts") and "/generated/" not in f"/{yol}"

    def eslemeyi_donustur(self, output: Any) -> Any:
        return output


EKLENTI = _Ts()
