"""Web page object eşitliği: TS `demo-app/e2e/pages` ↔ Java `demo-app/e2e-java` (011 plan §2.5).

`verify_and_map` REPLAY golden'ları dilden bağımsız kalsın diye Java page object'leri TS'nin birebir
karşılığıdır: sınıf adları, public metot adları, parametre adları ve sırası aynı; tür eşlemesi
`string→String`, `number→int|double`, `boolean→boolean`; dönüş `Promise<T>` → `T`. Tek istisna Java
ayrılmış sözcükleridir: ad `JAVA_AD_ESLEME` tablosundan gelir (koordinatör kararı; birleştirmede
`tp_core.features.codegen.platform.JAVA_AD_ESLEME`'ye bağlanacak).

Kaynaklar:
- TS: `demo-app/e2e/pages/**/*.page.ts` doğrudan okunur (fikstür `symbols.json` eski olabilir; o
  yalnız alt küme olarak denetlenir).
- Java: `symbols-java-web.json` = `java-araclar symbols --root demo-app/e2e-java` çıktısı. Jar
  derliyse (`toolchain/java-araclar/target/java-araclar.jar`) fikstürün güncelliği de denetlenir.

Fikstürü yenileme (demo-app/e2e-java/README.md "Sembol tablosu fikstürü"):
    (cd toolchain/java-araclar && ./mvnw -B -q package -DskipTests)
    java -jar toolchain/java-araclar/target/java-araclar.jar symbols --root demo-app/e2e-java \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); \
          print(json.dumps(d, ensure_ascii=False, indent=1))' \
      > core/tests/unit/features/codegen/symbols-java-web.json
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tp_core.features.codegen import platform as platformlar

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
TS_PAGES = REPO / "demo-app/e2e/pages"
TS_FIXTURES = REPO / "demo-app/e2e/tests/fixtures.ts"
JAVA_ROOT = REPO / "demo-app/e2e-java"
TEST_TABANI = JAVA_ROOT / "src/test/java/com/antreklabs/bayi/altyapi/TestTabani.java"
JAR = REPO / "toolchain/java-araclar/target/java-araclar.jar"
# Gerçek render çıktısı (test_render_dil golden'ı) ↔ e2e-java'daki derlenen/koşan örneği (MİM-O7).
WEB_JAVA_GOLDEN = HERE / "golden/TPD1WebC2_3f9b1c2eTest.java"
WEB_JAVA_ORNEK = (
    JAVA_ROOT / "src/test/java/com/antreklabs/bayi/uretilen/TPD1WebC2_3f9b1c2eTest.java"
)
JAVA = json.loads((HERE / "symbols-java-web.json").read_text("utf-8"))
TS_FIXTURE = json.loads((HERE / "symbols.json").read_text("utf-8"))

# TS metot adı Java ayrılmış sözcüğüyse Java adı (tek kaynak).
JAVA_AD_ESLEME = platformlar.JAVA_AD_ESLEME
TUR = {"string": {"String"}, "number": {"int", "double"}, "boolean": {"boolean"}}
EXPECT_ADI = re.compile(r"^expect(?:$|[A-Z0-9_])")  # toolchain/symbols ile aynı kural

_SINIF = re.compile(r"export class (\w+)")
_METOT = re.compile(r"^  async (\w+)\(([^)]*)\): Promise<(\w+)>", re.M)


def _ts_tablosu() -> dict[str, list[tuple[str, list[tuple[str, str]], str]]]:
    """TS kaynağından: sınıf → [(metot, [(param, tür)], dönüş)] (kaynak sırası; private hariç)."""
    out: dict[str, list[tuple[str, list[tuple[str, str]], str]]] = {}
    for f in sorted(TS_PAGES.rglob("*.page.ts")):
        metin = f.read_text("utf-8")
        sinif = _SINIF.search(metin)
        assert sinif, f
        metotlar = []
        for ad, params, donus in _METOT.findall(metin):
            ps = []
            for p in filter(None, (x.strip() for x in params.split(","))):
                pad, ptur = (s.strip() for s in p.split(":"))
                ps.append((pad, ptur))
            metotlar.append((ad, ps, donus))
        out[sinif.group(1)] = metotlar
    return out


def _java_tablosu() -> dict[str, list[dict]]:
    return {po["class"]: po["methods"] for po in JAVA["page_objects"]}


def test_siniflar_ayni() -> None:
    assert sorted(_java_tablosu()) == sorted(_ts_tablosu())


@pytest.mark.parametrize("sinif", sorted(_ts_tablosu()))
def test_metotlar_parametreler_birebir(sinif: str) -> None:
    ts = _ts_tablosu()[sinif]
    java = _java_tablosu()[sinif]
    assert [JAVA_AD_ESLEME.get(a, a) for a, _, _ in ts] == [m["name"] for m in java], (
        "metot adları/sırası"
    )
    for (ad, ts_params, ts_donus), jm in zip(ts, java, strict=True):
        assert [p for p, _ in ts_params] == [p["name"] for p in jm["params"]], (
            f"{sinif}.{ad} parametre adları"
        )
        for (p, t), jp in zip(ts_params, jm["params"], strict=True):
            assert jp["type"] in TUR[t], f"{sinif}.{ad}({p}): {t} → {jp['type']}"
        beklenen = {"void": "void", "string": "String"}[ts_donus]
        assert jm["returns"] == beklenen, f"{sinif}.{ad} dönüş"


def test_eski_ts_fikstur_alt_kume() -> None:
    """`symbols.json` (REPLAY golden'larının tablosu) her metodu Java'da aynı imzayla bulunur."""
    java = _java_tablosu()
    for po in TS_FIXTURE["page_objects"]:
        adlar = {m["name"]: m for m in java[po["class"]]}
        for m in po["methods"]:
            jm = adlar[JAVA_AD_ESLEME.get(m["name"], m["name"])]
            assert [p["name"] for p in m["params"]] == [p["name"] for p in jm["params"]]


def test_fikstur_erisimcileri() -> None:
    """Java `fixtures` = lowerCamel(PO sınıfı); TS `interface Fixtures` adları TestTabani'nda."""
    assert JAVA["fixtures"] == sorted(c[:1].lower() + c[1:] for c in _ts_tablosu())
    blok = re.search(r"interface Fixtures \{([^}]*)\}", TS_FIXTURES.read_text("utf-8"))
    assert blok
    ts_adlar = re.findall(r"(\w+)\s*:", blok.group(1))
    java_adlar = set(
        re.findall(r"protected final [\w.<>]+ (\w+)\(\)", TEST_TABANI.read_text("utf-8"))
    )
    assert ts_adlar and set(ts_adlar) <= java_adlar, set(ts_adlar) - java_adlar


def test_tek_sozlesme_hatasi_okuma_metodu() -> None:
    """Tek bilinen `errors` girdisi: TS'de de değer döndüren `OrderPage.readOrderNumber`
    (üretilen testler kullanamaz; java-araclar guard reddeder)."""
    assert [e["message"].split(":")[0] for e in JAVA["errors"]] == ["readOrderNumber"]


def test_kind_ts_ile_ayni() -> None:
    for sinif, metotlar in _java_tablosu().items():
        for m in metotlar:
            beklenen = "expect" if EXPECT_ADI.match(m["name"]) else "action"
            assert m["kind"] == beklenen, f"{sinif}.{m['name']}"


@pytest.mark.skipif(
    not JAR.exists() or shutil.which("java") is None, reason="java-araclar jar'ı derlenmemiş"
)
def test_java_fikstur_guncel() -> None:
    cikti = subprocess.run(
        ["java", "-jar", str(JAR), "symbols", "--root", str(JAVA_ROOT)],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout
    assert json.loads(cikti) == JAVA, (
        "symbols-java-web.json eski: modül belgesindeki komutla yenileyin"
    )


def test_uretilen_ornek_golden_ile_bayt_esit() -> None:
    """e2e-java `uretilen/` örneği, Java web şablonunun golden çıktısıyla BAYT EŞİT.

    Örnek, CI'da (run-java-checks.sh) guard'dan geçer, derlenir ve demo uygulamasına karşı koşar:
    eşitlik, gerçek şablon çıktısının derlendiğini ve yeşil olduğunu kanıtlar (MİM-O7).
    """
    assert WEB_JAVA_ORNEK.read_bytes() == WEB_JAVA_GOLDEN.read_bytes(), (
        "golden/TPD1WebC2_3f9b1c2eTest.java değişti: e2e-java örneği de güncellenmeli —\n"
        f"  cp {WEB_JAVA_GOLDEN.relative_to(REPO)} {WEB_JAVA_ORNEK.relative_to(REPO)}\n"
        "ardından demo-app/ci/run-java-checks.sh ile derleyip koşun."
    )
