"""Java dil eklentisi (014 Ş0): web Playwright for Java + TestNG, uygulama Appium + TestNG.
Bugünkü render işlevlerini sarmalar: çıktı bayt eşittir (`render.render_java_test`)."""

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


class _Java:
    ad = platformlar.JAVA
    proje_dosyasi = "pom.xml"
    algila_kaliplari = (
        AlgilaKalibi(frozenset({platformlar.WEB}), "TP_E2E_JAVA_ROOT", "src/test/java/"),
        AlgilaKalibi(
            frozenset(platformlar.UYGULAMA_PLATFORMLARI), "TP_E2E_APP_ROOT", "src/test/java/"
        ),
    )

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

        return render.render_java_test(inp, cati.platform, rules)

    def literal(self, value: Any) -> str:
        from tp_core.features.codegen import render

        return render.java_literal(value)

    def ident(self, value: Any) -> str:
        from tp_core.features.codegen import render

        return render.java_ident(value)

    def sinif_adi(
        self, story_key: str | None, platform: str, sira_no: int, case_id: uuid.UUID
    ) -> str | None:
        from tp_core.features.codegen import render

        return render.java_class_name(story_key, platform, sira_no, case_id)

    def uretilen_yol(
        self, cati: Cati, kok: str, story_key: str | None, sira_no: int, case_id: uuid.UUID
    ) -> str:
        from tp_core.features.codegen import render

        return render.java_repo_path(kok, story_key, cati.platform, sira_no, case_id)

    def test_dosyasi_mi(self, yol: str) -> bool:
        return platformlar.java_test_dosyasi_mi(yol)

    def eslemeyi_donustur(self, output: Any) -> Any:
        return platformlar.java_eslemesi(output)


EKLENTI = _Java()
