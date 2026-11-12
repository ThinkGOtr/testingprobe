"""Üretim dilinin hedef repodan algılanması (specs/011-uretim-dili §2.4, karar K1; inceleme turu 1
K-T7).

`algila(forge, ref, platform) -> Algilama{dil, kaynak, sayilar}`: saf dosya sayımı, model yok.
Uygulama kökü (`TP_FORGE_APP_ROOT`) altında **elle yazılmış** test dosyaları sayılır; aracın kendi
ürettiği dizinler sayılmaz (yoksa ilk üretimden sonra algılama kendi çıktısını ölçerdi). Bağımlılık
ve derleme çıktısı dizinleri (`node_modules`, `.venv`, `bin`, `obj`, `target`, …) hiç izlenmez.

| Dil | Sayılan dosyalar |
|---|---|
| `ts` | `<e2e>/tests/**/*.spec.ts` (`tests/generated/` hariç) |
| `java` (web) | Java test kalıbı (`platform.JAVA_TEST_SONEKLERI`), `uretilen/` + `birim/` hariç |
| `csharp` | Playwright'a başvuran bir `*.csproj`'un dizini altında `*Tests.cs` / `*Test.cs` |
| `python` | Playwright'a başvuran proje dosyasının dizini altında `test_*.py` / `*_test.py` |

Java test kalıbı: `*Test.java`, `*Testi.java`, `*Tests.java`, `*IT.java`; algılama sinyali olarak
`*Test.kt` de. `<e2e-java>/src/test/**` her zaman sayılır; başka bir `src/test/**` ağacı (ör. kökte
standart Maven / Gradle) yalnız Playwright for Java'ya **bağımlı** `pom.xml` / `build.gradle(.kts)`
altındaysa (`<dependencies>` altında `com.microsoft.playwright`; `<playwright.version>` özelliği
ya da `dependencyManagement` değil) **ve** test dosyası `com.microsoft.playwright` içe aktarıyorsa
(dizin başına bir dosya okunarak; QA-Y1 tur 2). Soyut taban sınıflar (`BaseTest`, `Abstract*`,
`*TestBase`, içerikte `abstract class`) test sayılmaz (QA-Y7).

`<e2e-app>` (Appium) ve `<e2e-java>` ağaçları C# / Python sayımına girmez; `<e2e-app>` web Java
sayımına da girmez. En çok dosyası olan dil seçilir; eşitlikte öncelik `ts > java > csharp >
python`; hiç dosya yoksa platformun varsayılanı (`kaynak="varsayilan"`). Uygulama platformlarında
tek dil Java'dır (`<e2e-app>/src/test/**` Java test kalıbı sayılır; el testleri `*Testi.java`).

**Playwright işareti:** C#, Python ve e2e-java dışı Java'da yalnız Playwright projesinin testleri
sayılır (proje dosyasının içeriğinde `playwright`). Ham `**/test_*.py` sayımı uygulamanın kendi
birim testlerini (ör. `api/tests/test_*.py`) uçtan uca test sanırdı. Uygulama kökündeki bağımlılık
bildirimi (`pyproject.toml`, `requirements*.txt`, …) tüm depoyu kapsadığı için zayıf işarettir:
yalnız `conftest.py` (herhangi bir dizinde) ya da test dosyasının kendi içeriği Playwright'ı
kullanıyorsa (`from/import playwright` ya da `page: Page`; `page: int` değil, QA-Y2 tur 2) o testler
sayılır.

**Okuma bütçesi:** işaret/test dosyası okuması (GitHub kipinde her biri bir API çağrısı) **dil
başına** `MAX_ISARET_OKUMA` ile sınırlıdır. Yalnız altında o dilin test dosyası bulunan proje
dosyaları okunur; adında test sözcüğü taşıyan dizinler (`tests/`, `E2E`, `*.Tests`, `spec`, …)
önce, sonra sığ olan.

**Önbellek:** sonuç `(forge, commit sha, platform, uygulama kökü)` ile süreç içinde önbelleklenir
(commit'ler değişmez). Dal adı → sha çözümü `HEAD_TTL_S` (60 sn) önbelleklenir (`GET
/code/languages` her istekte forge'a gitmesin; GÜV-D2). Forge hatasında sonuç `varsayilan`'dır
(`hata` dolu) ve `HATA_TTL_S` boyunca kısa önbellekte tutulur: algılama kod üretimini hiçbir zaman
engellemez.
"""

from __future__ import annotations

import logging
import posixpath
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from tp_core.features.codegen import platform as platformlar

log = logging.getLogger(__name__)

_CACHE_MAX = 64
_SHA_RE = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")
TS_URETILEN = "tests/generated/"
PY_PROJE_DOSYALARI = ("pyproject.toml", "conftest.py", "pytest.ini", "setup.cfg", "tox.ini")
JAVA_PROJE_DOSYALARI = ("pom.xml", "build.gradle", "build.gradle.kts")
_PY_REQ_RE = re.compile(r"requirements[\w.-]*\.txt")
_PY_TEST_RE = re.compile(r"(test_[^/]*|[^/]*_test)\.py")
_CS_TEST_RE = re.compile(r"[^/]*Tests?\.cs")
# Hiç izlenmeyen dizinler: bağımlılıklar ve derleme çıktıları (yanlış sayım + boş okuma bütçesi).
IZLENMEYEN_DIZINLER = frozenset(
    {"node_modules", ".venv", "venv", "site-packages", ".git", "bin", "obj", "target", "build"}
)
# Adında bunlardan birini taşıyan dizinlerin proje dosyaları önce okunur (test projesi adayı).
_TEST_DIZIN_RE = re.compile(r"test|e2e|spec|playwright", re.IGNORECASE)
# Kökte yalnız bağımlılık bildirimi varken test dosyası içerik taramasında önce okunan dizinler
# (tarayıcı/uçtan uca test adı taşıyanlar; genel `tests/` birim testleri sonra).
_UCTAN_UCA_DIZIN_RE = re.compile(r"e2e|ui|playwright|browser|web|acceptance", re.IGNORECASE)
# Dil başına okunan işaret / test dosyası sınırı (GitHub kipinde her okuma bir API çağrısıdır).
MAX_ISARET_OKUMA = 20
PLAYWRIGHT = "playwright"
# Test dosyasının kendisinde Playwright kullanımı (kökte yalnız bağımlılık bildirimi varken;
# QA-Y2 tur 2): `from playwright…` / `import playwright…` ya da `page: Page` tür açıklaması.
# Dosyada geçen `playwright` sözcüğü ya da `page: int` gibi bir parametre işaret değildir.
_PY_PLAYWRIGHT_RE = re.compile(
    r"^\s*(?:from|import)\s+playwright\b|\bpage\s*:\s*(?:[\w.]+\.)?Page\b", re.MULTILINE
)
# Java/Kotlin test dosyasında Playwright for Java kullanımı (QA-Y1 tur 2).
_JAVA_PLAYWRIGHT_RE = re.compile(r"^\s*import\s+(?:static\s+)?com\.microsoft\.playwright\b", re.M)
JAVA_PLAYWRIGHT_GRUBU = "com.microsoft.playwright"
# Maven pom'unda bağımlılık sayılmayan bölümler: yorumlar, `dependencyManagement` (yalnız sürüm
# sabitler), `build` (eklenti bağımlılıkları), `properties` (`<playwright.version>`).
_POM_HARIC_RE = re.compile(
    r"<!--.*?-->|<(dependencyManagement|build|properties)\b.*?</\1\s*>", re.DOTALL
)
_POM_BAGIMLILIK_RE = re.compile(r"<dependency\b.*?</dependency\s*>", re.DOTALL)
_POM_GRUP_RE = re.compile(r"<groupId>\s*com\.microsoft\.playwright\s*</groupId>")
# Soyut taban sınıf adı (QA-Y7): `Abstract*`, `Base*`, `Taban*`, `*BaseTest(s)`, `*TestBase`.
_TABAN_AD_RE = re.compile(
    r"(?:Abstract|Base|Taban[iı]?)(?=[A-Z0-9_]|$)|[A-Za-z0-9_]*(?:Base|Taban[iı]?)"
    r"(?:Tests?|Testi|IT)$|[A-Za-z0-9_]*TestBase$"
)
_SOYUT_SINIF_RE = re.compile(r"\babstract\s+(?:\w+\s+)*class\b")
HEAD_TTL_S = 60.0
HATA_TTL_S = 15.0


@dataclass(frozen=True)
class Algilama:
    """`dil`: seçilen dil; `kaynak`: `algilandi` | `varsayilan`; `sayilar`: dil → dosya sayısı
    (platformun geçerli dilleri). `projeler`: tam hat dilinin test projesi repoda var mı
    (ts → `<e2e>/package.json`, java → `pom.xml`); forge okunamadıysa boş (bilinmiyor).
    `hata`: forge okunamadıysa nedeni (sonuç bilinmiyor; `varsayilan` döner)."""

    dil: str
    kaynak: str
    sayilar: dict[str, int] = field(default_factory=dict)
    projeler: dict[str, bool] = field(default_factory=dict)
    hata: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"dil": self.dil, "kaynak": self.kaynak, "sayilar": dict(self.sayilar)}


_CACHE: OrderedDict[tuple[str, str, str, str], Algilama] = OrderedDict()
# (forge kimliği, dal) → (sha, zaman); (forge kimliği, ref, platform, kök) → (sonuç, zaman).
_HEAD: dict[tuple[str, str], tuple[str, float]] = {}
_HATA: dict[tuple[str, str, str, str], tuple[Algilama, float]] = {}
_LOCK = threading.Lock()


def _simdi() -> float:
    return time.monotonic()


def onbellegi_temizle() -> None:
    with _LOCK:
        _CACHE.clear()
        _HEAD.clear()
        _HATA.clear()


def varsayilan(platform: str | None, hata: str | None = None) -> Algilama:
    """Algılama sonuçsuz / yapılamadı: platformun varsayılan dili, sayılar sıfır. `hata` verilirse
    forge okunamamıştır (sonuç bilinmiyor)."""
    return Algilama(
        platformlar.varsayilan_dil(platform),
        "varsayilan",
        {d: 0 for d in platformlar.platform_dilleri(platform)},
        hata=hata,
    )


def _forge_kimligi(forge: Any) -> str | None:
    """Önbellek anahtarı: aynı depoya bakan forge nesneleri (istek başına yeniden kurulur) aynı
    kimliği taşır (GitHub `repo`, LocalForge `path`). Depo bilinmiyorsa None: dal → sha çözümü
    önbelleklenmez (`id()` yeniden kullanılabilir; başka deponun sha'sı dönmesin)."""
    yer = getattr(forge, "repo", None) or getattr(forge, "path", None)
    return f"{type(forge).__name__}:{yer}" if yer is not None else None


def _kok(uygulama_koku: str, dizin: str) -> str:
    return f"{uygulama_koku}/{dizin}" if uygulama_koku else dizin


def _altinda(yol: str, kok: str) -> str | None:
    """`yol` `kok` dizininin altındaysa köke göre yol; değilse None (`kok=""` → tüm depo)."""
    if not kok:
        return yol
    return yol[len(kok) + 1 :] if yol.startswith(kok + "/") else None


def _kapsar(dizin: str, yol: str) -> bool:
    """`yol` `dizin`'in altında mı? (`dizin=""` → her yol)."""
    return dizin == "" or yol.startswith(dizin + "/")


def _izlenir(yol: str, haric_kokler: Sequence[str] = ()) -> bool:
    if any(_kapsar(k, yol) for k in haric_kokler):
        return False
    return not any(parca in IZLENMEYEN_DIZINLER for parca in yol.split("/")[:-1])


def _oncelik(yol: str) -> tuple[int, int, str]:
    """Okuma sırası: adında test sözcüğü taşıyan dizin önce, sonra sığ olan, sonra alfabe."""
    dizin = posixpath.dirname(yol)
    return (0 if _TEST_DIZIN_RE.search(dizin) else 1, yol.count("/"), yol)


class _Butce:
    """Dil başına okuma bütçesi."""

    def __init__(self, n: int = MAX_ISARET_OKUMA) -> None:
        self.kalan = n

    def oku(self, forge: Any, sha: str, yol: str) -> str | None:
        """Bütçe varsa dosyayı okur (okunamazsa ""); bütçe bittiyse None."""
        if self.kalan <= 0:
            return None
        self.kalan -= 1
        try:
            return forge.read_file(yol, ref=sha) or ""
        except Exception:  # okunamayan dosya işaret sayılmaz
            return ""


def _playwright_icerir(yol: str, icerik: str) -> bool:
    return PLAYWRIGHT in icerik.lower()


def _isaretli_dizinler(
    forge: Any,
    sha: str,
    adaylar: Sequence[str],
    testler: Sequence[str],
    butce: _Butce,
    isaret: Callable[[str, str], bool] = _playwright_icerir,
) -> list[str]:
    """İçeriği Playwright'a başvuran (`isaret(yol, içerik)`) aday proje dosyalarının dizinleri.
    Yalnız altında en az bir test dosyası bulunan adaylar okunur (`_oncelik` sırasıyla, bütçe
    kadar)."""
    dizinler: list[str] = []
    ilgili = [y for y in adaylar if any(_kapsar(posixpath.dirname(y), t) for t in testler)]
    for yol in sorted(ilgili, key=_oncelik):
        dizin = posixpath.dirname(yol)
        if any(_kapsar(d, dizin + "/") for d in dizinler):
            continue  # üst (ya da aynı) dizin zaten Playwright projesi
        icerik = butce.oku(forge, sha, yol)
        if icerik is None:
            break
        if isaret(yol, icerik):
            dizinler.append(dizin)
    return dizinler


def _proje_altinda(yol: str, dizinler: Sequence[str]) -> int:
    return int(any(_kapsar(d, yol) for d in dizinler))


def _ts_say(dosyalar: Sequence[str], e2e: str) -> int:
    n = 0
    for yol in dosyalar:
        goreli = _altinda(yol, e2e)
        if goreli is None or not goreli.startswith("tests/") or not goreli.endswith(".spec.ts"):
            continue
        if goreli.startswith(TS_URETILEN) or not _izlenir(goreli):
            continue
        n += 1
    return n


def _taban_adi_mi(yol: str) -> bool:
    """Ad soyut taban sınıfı gibi mi (QA-Y7: `BaseTest.java`, `AbstractUiTest.java`,
    `PageTestBase.cs`)? Bunlar test değil, testlerin türediği sınıflardır."""
    kok = posixpath.basename(yol).rsplit(".", 1)[0]
    return bool(_TABAN_AD_RE.match(kok))


def _java_testi(yol: str) -> bool:
    """`src/test/` ağacındaki elle yazılmış Java (ya da Kotlin) testi mi? (K-T7 tek kalıbı;
    soyut taban sınıf adları sayılmaz, QA-Y7)"""
    return (
        "/src/test/" in "/" + yol
        and platformlar.java_test_dosyasi_mi(yol, kotlin=True)
        and not _taban_adi_mi(yol)
    )


def _java_say(dosyalar: Sequence[str], kok: str) -> int:
    """Bilinen Java test projesi (`e2e-java` / `e2e-app`) altındaki testler: işaret aranmaz."""
    return sum(
        1
        for yol in dosyalar
        if (goreli := _altinda(yol, kok)) is not None
        and goreli.startswith("src/test/")
        and _izlenir(goreli)
        and _java_testi(goreli)
    )


def _java_proje_isareti(yol: str, icerik: str) -> bool:
    """Java proje dosyası Playwright for Java'ya **bağımlı** mı (QA-Y1 tur 2)? Maven: yorum,
    `dependencyManagement`, `build` ve `properties` dışındaki bir `<dependency>`'nin `groupId`'si
    `com.microsoft.playwright` (yalnız `<playwright.version>` özelliği ya da sürüm yönetimi işaret
    değildir). Gradle: `com.microsoft.playwright` koordinatı."""
    if posixpath.basename(yol) != "pom.xml":
        return JAVA_PLAYWRIGHT_GRUBU in icerik
    govde = _POM_HARIC_RE.sub("", icerik)
    return any(_POM_GRUP_RE.search(b) for b in _POM_BAGIMLILIK_RE.findall(govde))


def _icerikle_say(
    forge: Any,
    sha: str,
    testler: Sequence[str],
    butce: _Butce,
    kullanir: Callable[[str], bool],
) -> int:
    """Test dosyalarını dizin dizin örnekleyerek sayar: uçtan uca adlı dizinler önce; her
    dizinde ilk soyut olmayan dosya okunur, Playwright kullanıyorsa dizinin (okunup soyut çıkanlar
    dışındaki) tüm testleri sayılır, kullanmıyorsa dizin sayılmaz. Dizin başına tek okuma: 200
    birim testli bir servis bütçeyi tüketmez, Playwright testleri de bütçe kadarıyla sınırlanmaz.
    Bütçe biterse okunmamış dizinler sayılmaz (alt sınır)."""
    gruplar: dict[str, list[str]] = {}
    for yol in testler:
        gruplar.setdefault(posixpath.dirname(yol), []).append(yol)
    n = 0
    for dizin in sorted(
        gruplar, key=lambda d: (0 if _UCTAN_UCA_DIZIN_RE.search(d) else 1, *_oncelik(d + "/"))
    ):
        soyut = 0
        for yol in sorted(gruplar[dizin]):
            icerik = butce.oku(forge, sha, yol)
            if icerik is None:
                return n
            if _SOYUT_SINIF_RE.search(icerik):
                soyut += 1  # soyut taban sınıf (QA-Y7): sayılmaz, dizinin sonraki dosyasına bak
                continue
            if kullanir(icerik):
                n += len(gruplar[dizin]) - soyut
            break
    return n


def _java_diger_say(
    forge: Any, sha: str, dosyalar: Sequence[str], haric: Sequence[str], butce: _Butce
) -> int:
    """`e2e-java` / `e2e-app` dışındaki Java testleri (ör. kökte standart Maven / Gradle;
    QA-Y1 tur 2): yalnız Playwright for Java'ya **bağımlı** proje dosyasının altındakiler ve
    bunlardan da yalnız `com.microsoft.playwright` içe aktaranlar (zayıf işaret yolu, Python'daki
    gibi). Kökte Playwright bağımlılığı olan bir Spring Boot projesinin servis birim testleri
    sayılmaz; üst pom'da yalnız `<playwright.version>` özelliği tüm modülleri işaretlemez."""
    testler = [y for y in dosyalar if _izlenir(y, haric) and _java_testi(y)]
    if not testler:
        return 0
    adaylar = [
        y for y in dosyalar if posixpath.basename(y) in JAVA_PROJE_DOSYALARI and _izlenir(y, haric)
    ]
    dizinler = _isaretli_dizinler(forge, sha, adaylar, testler, butce, _java_proje_isareti)
    adaylar_t = [y for y in testler if _proje_altinda(y, dizinler)]
    return _icerikle_say(
        forge, sha, adaylar_t, butce, lambda i: bool(_JAVA_PLAYWRIGHT_RE.search(i))
    )


def _csharp_say(
    forge: Any, sha: str, dosyalar: Sequence[str], haric: Sequence[str], butce: _Butce
) -> int:
    testler = [
        y
        for y in dosyalar
        if _CS_TEST_RE.fullmatch(posixpath.basename(y))
        and _izlenir(y, haric)
        and not _taban_adi_mi(y)
    ]
    if not testler:
        return 0
    projeler = [y for y in dosyalar if y.endswith(".csproj") and _izlenir(y, haric)]
    dizinler = _isaretli_dizinler(forge, sha, projeler, testler, butce)
    return sum(_proje_altinda(y, dizinler) for y in testler)


def _py_isaret_mi(ad: str) -> bool:
    return ad in PY_PROJE_DOSYALARI or bool(_PY_REQ_RE.fullmatch(ad))


def _python_say(
    forge: Any,
    sha: str,
    dosyalar: Sequence[str],
    kok: str,
    haric: Sequence[str],
    butce: _Butce,
) -> int:
    testler = [
        y for y in dosyalar if _PY_TEST_RE.fullmatch(posixpath.basename(y)) and _izlenir(y, haric)
    ]
    if not testler:
        return 0
    isaretler = [y for y in dosyalar if _py_isaret_mi(posixpath.basename(y)) and _izlenir(y, haric)]
    # Uygulama kökündeki bağımlılık bildirimi tüm depoyu kapsar: zayıf işaret (QA-O1). Kökteki
    # `conftest.py` ise Playwright fikstürlerini gerçekten tanımlar: güçlü işarettir.
    kok_bildirimleri = [
        y
        for y in isaretler
        if posixpath.dirname(y) == kok and posixpath.basename(y) != "conftest.py"
    ]
    guclu = [y for y in isaretler if y not in kok_bildirimleri]
    dizinler = _isaretli_dizinler(forge, sha, guclu, testler, butce)
    n = sum(_proje_altinda(y, dizinler) for y in testler)
    if not kok_bildirimleri:
        return n
    kokte_playwright = False
    for yol in kok_bildirimleri:
        icerik = butce.oku(forge, sha, yol)
        if icerik is None:
            return n
        if PLAYWRIGHT in icerik.lower():
            kokte_playwright = True
            break
    if not kokte_playwright:
        return n
    # Kökte yalnız bildirim var: test dosyasının kendisi Playwright kullanıyorsa sayılır.
    for yol in sorted(
        (t for t in testler if not _proje_altinda(t, dizinler)),
        key=lambda y: (0 if _UCTAN_UCA_DIZIN_RE.search(posixpath.dirname(y)) else 1, *_oncelik(y)),
    ):
        icerik = butce.oku(forge, sha, yol)
        if icerik is None:
            break
        if _PY_PLAYWRIGHT_RE.search(icerik):
            n += 1
    return n


def _say(forge: Any, sha: str, platform: str, uygulama_koku: str) -> Algilama:
    tum = forge.list_files(prefix=f"{uygulama_koku}/" if uygulama_koku else "", ref=sha)
    kume = set(tum)
    e2e_app = _kok(uygulama_koku, platformlar.E2E_APP_DIZINI)
    if platformlar.uygulama_mi(platform):
        sayilar = {platformlar.JAVA: _java_say(tum, e2e_app)}
        projeler = {platformlar.JAVA: f"{e2e_app}/pom.xml" in kume}
    else:
        e2e = _kok(uygulama_koku, "e2e")
        e2e_java = _kok(uygulama_koku, platformlar.E2E_JAVA_DIZINI)
        # Java proje ağaçları (Appium e2e-app, web e2e-java) C# / Python sayımına girmez.
        java_agaclari = (e2e_app, e2e_java)
        sayilar = {
            "ts": _ts_say(tum, e2e),
            "java": _java_say(tum, e2e_java)
            + _java_diger_say(forge, sha, tum, java_agaclari, _Butce()),
            "csharp": _csharp_say(forge, sha, tum, java_agaclari, _Butce()),
            "python": _python_say(forge, sha, tum, uygulama_koku, java_agaclari, _Butce()),
        }
        projeler = {"ts": f"{e2e}/package.json" in kume, "java": f"{e2e_java}/pom.xml" in kume}
    en_cok = max(sayilar.values(), default=0)
    if en_cok <= 0:
        return Algilama(platformlar.varsayilan_dil(platform), "varsayilan", sayilar, projeler)
    # Eşitlikte öncelik DILLER sırasıdır: ts > java > csharp > python.
    dil = next(d for d in platformlar.DILLER if sayilar.get(d) == en_cok)
    return Algilama(dil, "algilandi", sayilar, projeler)


def _sha_coz(forge: Any, kimlik: str | None, ref: str) -> str:
    """Dal adı → commit sha (`HEAD_TTL_S` önbellekli); sha verildiyse kendisi."""
    if _SHA_RE.fullmatch(ref):
        return ref
    if kimlik is None:
        return str(forge.head_sha(ref))
    simdi = _simdi()
    with _LOCK:
        kayit = _HEAD.get((kimlik, ref))
        if kayit is not None and simdi - kayit[1] < HEAD_TTL_S:
            return kayit[0]
    sha = str(forge.head_sha(ref))
    with _LOCK:
        _HEAD[(kimlik, ref)] = (sha, simdi)
        if len(_HEAD) > _CACHE_MAX:
            _HEAD.pop(next(iter(_HEAD)))
    return sha


def algila(
    forge: Any, ref: str = "main", platform: str | None = None, *, uygulama_koku: str | None = None
) -> Algilama:
    """Hedef repodaki elle yazılmış testlerden üretim dilini algılar (bkz. modül açıklaması).

    `ref` dal adı ya da commit sha'sıdır (dal sha'ya çözülür, 60 sn önbellekli; sonuç önbelleği
    sha'ya bağlıdır). `uygulama_koku` verilmezse `TP_FORGE_APP_ROOT` kuralı (`service.app_root`).
    Hiçbir hata dışarı sızmaz: forge okunamazsa `varsayilan` (`hata` dolu) döner ve kısa süre
    önbelleklenir.
    """
    p = platform or platformlar.WEB
    if p not in platformlar.PLATFORMLAR:
        return varsayilan(platformlar.WEB)
    ref = ref or "main"
    kimlik = _forge_kimligi(forge)
    hata_anahtari: tuple[str, str, str, str] | None = None
    onek = kimlik or ""
    try:
        if uygulama_koku is None:
            from tp_core.features.codegen.service import app_root

            uygulama_koku = app_root()
        kok = uygulama_koku.strip().strip("/")
        hata_anahtari = (kimlik, ref, p, kok) if kimlik is not None else None
        with _LOCK:
            onceki = _HATA.get(hata_anahtari) if hata_anahtari else None
            if onceki is not None and _simdi() - onceki[1] < HATA_TTL_S:
                return onceki[0]
        sha = _sha_coz(forge, kimlik, ref)
        anahtar = (onek, sha, p, kok)
        with _LOCK:
            if anahtar in _CACHE:
                _CACHE.move_to_end(anahtar)
                return _CACHE[anahtar]
        sonuc = _say(forge, sha, p, kok)
    except Exception as exc:  # forge erişilemez / depo okunamaz: üretimi engelleme
        log.warning("dil algılanamadı (%s, %s): %s", p, ref, exc)
        sonuc = varsayilan(p, hata=f"depo okunamadı: {type(exc).__name__}")
        if hata_anahtari is not None:
            with _LOCK:
                _HATA[hata_anahtari] = (sonuc, _simdi())
                if len(_HATA) > _CACHE_MAX:
                    _HATA.pop(next(iter(_HATA)))
        return sonuc
    with _LOCK:
        _CACHE[anahtar] = sonuc
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return sonuc
