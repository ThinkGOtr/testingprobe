"""Üretim dili boyutunun CI / triage / onarım ortak yardımcıları (011 §2.8). Veritabanı yazmaz.

Dil platformdan türetilmez (K1): `web` × `ts | java`, uygulama platformları × `java`. Bu modül
şu sorulara tek yerden yanıt verir:

- **Script'in dili** (`script_dili`): `Script.dil` (0021); boşsa platformun varsayılanı
  (`web → ts`, uygulama → `java`).
- **Koşunun dili** (`kosu_dili`): `run.ortam.dil` → `run.ortam.lang` (009'un Java işareti) →
  platformun varsayılanı. Koşu kaydında dilin yeri `run.ortam.dil`'dir (portal bunu gösterir).
- **Repoda hangi tam hat dillerinin web testi var** (`repodaki_web_dilleri`): paket koşuları
  (gece / push / deploy; script'li push dahil, K-T2) web için her birini ayrı koşuda koşturur.
- **Script'siz PR hangi dilleri koşar** (`degisen_web_dilleri`): değişen web test köklerine
  göre (K-T1).

Dil kümeleri ve Java test kalıbı `codegen/platform.py`'dendir (tek kaynak).

Web + Java (Playwright for Java + TestNG) hedef projesi `<uygulama kökü>/e2e-java`'dır
(`e2e_java_root`); konvansiyonu `e2e-app` ile aynıdır (`ekranlar/Kimlikler.java`, `uretilen/`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from tp_core.features.codegen import platform as platformlar

WEB = platformlar.WEB
TS = platformlar.TS
JAVA = platformlar.JAVA
# CI'da koşan (tam hat) diller; doğrulanmamış diller (csharp | python) CI'a giremez (011 K3).
TAM_HAT_DILLERI = platformlar.TAM_HAT_DILLERI
# Forge deposunda web + Java test projesinin kökü (uygulama köküne göre); toolchain
# `TP_E2E_JAVA_ROOT` varsayılanıyla aynı (011 §2.6).
E2E_JAVA_DIZINI = platformlar.E2E_JAVA_DIZINI


def tam_hat_dili(deger: Any) -> str | None:
    """Değer CI'da koşan bir dil mi (`ts` | `java`)? Değilse None. (`platform.gecerli_dil`
    ValueError atan doğrulayıcıdır; bu süzgeç sessizdir.)"""
    return deger if isinstance(deger, str) and deger in TAM_HAT_DILLERI else None


def script_dili(script: Any) -> str:
    """Script'in üretim dili (`Script.dil`, 0021); boşsa platformun varsayılanı."""
    return script.dil or platformlar.varsayilan_dil(script.platform)


def ortam_dili(ortam: Mapping[str, Any] | None) -> str | None:
    """`ortam.dil` → `ortam.lang` (009: Java koşusu işareti); yoksa None."""
    o = ortam or {}
    return tam_hat_dili(o.get("dil")) or tam_hat_dili(o.get("lang"))


def kosu_dili(run: Any) -> str:
    """Koşunun dili: `run.ortam.dil` → `run.ortam.lang` → platformun varsayılanı."""
    o = getattr(run, "ortam", None) or {}
    return ortam_dili(o) or platformlar.varsayilan_dil(o.get("platform"))


def web_java_mi(platform: str | None, dil: str | None) -> bool:
    """Web + Java hattı mı (Playwright for Java + TestNG)?"""
    return (platform or WEB) == WEB and dil == JAVA


def e2e_java_root() -> str:
    """Forge deposunda web + Java test projesinin kökü (`e2e-java` ya da `demo-app/e2e-java`)."""
    from tp_core.features.codegen import service as cg  # döngüsel içe aktarmayı önlemek için geç

    return cg.e2e_java_root()


def java_testi_mi(yol: str) -> bool:
    """Forge yolu bir (cihaz/tarayıcı) Java testi mi? Kalıp `platform.java_test_dosyasi_mi`
    (tek kaynak, K-T7); tarayıcısız birim testleri (`birim/`) koşu sayılmaz, üretilen testler
    (`uretilen/`) sayılır (paket koşusu onları da koşar)."""
    return platformlar.java_test_dosyasi_mi(yol, haric=("birim",))


def repodaki_web_dilleri(
    list_files: Callable[[str, str], list[str]], ref: str, *, e2e: str, e2e_java: str
) -> tuple[str, ...]:
    """`ref`'te web testi bulunan tam hat dilleri (sıra `ts`, `java`).

    Saf sayım (model yok): ts → `<e2e>/tests/**/*.spec.ts`; java →
    `<e2e-java>/src/test/java/**` + `platform.java_test_dosyasi_mi` (`birim/` hariç). Hiçbiri yoksa
    ya da forge okunamazsa `("ts",)` döner: bugünkü davranış (koşu engellenmez).
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


def degisen_web_dilleri(degisen: Sequence[str], *, e2e: str, e2e_java: str) -> tuple[str, ...]:
    """Script'siz PR'ın değiştirdiği web test kökleri → koşacak diller (011 K-T1; sıra `ts`,
    `java`). `<e2e>/` → `ts`, `<e2e-java>/` → `java`; ikisi de değiştiyse ikisi. Hiçbiri
    değişmediyse (ör. yalnız uygulama kodu) `("ts",)`: bugünkü davranış, yapılandırılmış
    `local-ci` kapısı."""
    ts_kok, java_kok = f"{e2e.rstrip('/')}/", f"{e2e_java.rstrip('/')}/"
    out: list[str] = []
    if any(y.startswith(ts_kok) for y in degisen):
        out.append(TS)
    if any(y.startswith(java_kok) for y in degisen):
        out.append(JAVA)
    return tuple(out) or (TS,)
