"""Üretim dili boyutunun CI / triage / onarım ortak yardımcıları (011 §2.8). Veritabanı yazmaz.

Dil platformdan türetilmez (K1): `web` × `ts | java`, uygulama platformları × `java`. Bu modül üç
soruya tek yerden yanıt verir:

- **Script'in dili** (`script_dili`): `Script.dil` (Ş1, 0021); alan yoksa / eski kayıtta
  platformun varsayılanı (`web → ts`, uygulama → `java`).
- **Koşunun dili** (`kosu_dili`): `run.ortam.dil` → `run.ortam.lang` (009'un Java işareti) →
  platformun varsayılanı. Koşu kaydında dilin yeri `run.ortam.dil`'dir (portal bunu gösterir).
- **Repoda hangi tam hat dillerinin web testi var** (`repodaki_web_dilleri`): paket koşuları
  (gece / push / deploy) web için her birini ayrı koşuda koşturur.

Web + Java (Playwright for Java + TestNG) hedef projesi `<uygulama kökü>/e2e-java`'dır
(`e2e_java_root`); konvansiyonu `e2e-app` ile aynıdır (`ekranlar/Kimlikler.java`, `uretilen/`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from tp_core.features.codegen import platform as platformlar

WEB = platformlar.WEB
TS = "ts"
JAVA = "java"
# Forge deposunda web + Java test projesinin kökü (uygulama köküne göre); toolchain
# `TP_E2E_JAVA_ROOT` varsayılanıyla aynı (011 §2.6).
E2E_JAVA_DIZINI = "e2e-java"
# Paket koşusunda sayılan Java testleri: `*Test.java` / `*Testi.java`; tarayıcısız birim testleri
# (`birim/`) koşu sayılmaz (Surefire'da `birim-raporlari/` ayrıdır).
_JAVA_TEST_SONEKLERI = ("Test.java", "Testi.java")


def gecerli_dil(deger: Any) -> str | None:
    return deger if isinstance(deger, str) and deger in platformlar.DILLER else None


def script_dili(script: Any) -> str:
    """Script'in üretim dili: `script.dil`; yoksa platformun varsayılanı."""
    platform = getattr(script, "platform", None)
    return gecerli_dil(getattr(script, "dil", None)) or platformlar.varsayilan_dil(platform)


def ortam_dili(ortam: Mapping[str, Any] | None) -> str | None:
    """`ortam.dil` → `ortam.lang` (009: Java koşusu işareti); yoksa None."""
    o = ortam or {}
    return gecerli_dil(o.get("dil")) or gecerli_dil(o.get("lang"))


def kosu_dili(run: Any) -> str:
    """Koşunun dili: `run.ortam.dil` → `run.ortam.lang` → platformun varsayılanı."""
    o = getattr(run, "ortam", None) or {}
    return ortam_dili(o) or platformlar.varsayilan_dil(o.get("platform"))


def web_java_mi(platform: str | None, dil: str | None) -> bool:
    """Web + Java hattı mı (Playwright for Java + TestNG)?"""
    return (platform or WEB) == WEB and dil == JAVA


def e2e_java_root() -> str:
    """Forge deposunda web + Java test projesinin kökü (`e2e-java` ya da `demo-app/e2e-java`)."""
    from tp_core.features.codegen import service as cg

    kok_f = getattr(cg, "e2e_java_root", None)  # Ş1 eklediyse tek kaynak odur
    if callable(kok_f):
        return str(kok_f())
    kok = cg.app_root()
    return f"{kok}/{E2E_JAVA_DIZINI}" if kok else E2E_JAVA_DIZINI


def java_testi_mi(yol: str) -> bool:
    """Forge yolu bir (cihaz/tarayıcı) Java testi mi? `birim/` altı sayılmaz."""
    return yol.endswith(_JAVA_TEST_SONEKLERI) and "/birim/" not in yol


def repodaki_web_dilleri(
    list_files: Callable[[str, str], list[str]], ref: str, *, e2e: str, e2e_java: str
) -> tuple[str, ...]:
    """`ref`'te web testi bulunan tam hat dilleri (sıra `ts`, `java`).

    Saf sayım (model yok): ts → `<e2e>/tests/**/*.spec.ts`; java →
    `<e2e-java>/src/test/java/**/*Test.java` (`birim/` hariç). Hiçbiri yoksa ya da forge
    okunamazsa `("ts",)` döner: bugünkü davranış (koşu engellenmez).
    """
    out: list[str] = []
    try:
        if any(y.endswith(".spec.ts") for y in list_files(f"{e2e}/tests/", ref)):
            out.append(TS)
    except Exception:
        return (TS,)
    try:
        if any(java_testi_mi(y) for y in list_files(f"{e2e_java}/src/test/java/", ref)):
            out.append(JAVA)
    except Exception:
        return tuple(out) or (TS,)
    return tuple(out) or (TS,)
