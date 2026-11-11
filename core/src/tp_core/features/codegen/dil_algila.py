"""Üretim dilinin hedef repodan algılanması (specs/011-uretim-dili §2.4, karar K1).

`algila(forge, ref, platform) -> Algilama{dil, kaynak, sayilar}`: saf dosya sayımı, model yok.
Uygulama kökü (`TP_FORGE_APP_ROOT`) altında **elle yazılmış** test dosyaları sayılır; aracın kendi
ürettiği dizinler sayılmaz (yoksa ilk üretimden sonra algılama kendi çıktısını ölçerdi):

| Dil | Sayılan dosyalar |
|---|---|
| `ts` | `<e2e>/tests/**/*.spec.ts` (`tests/generated/` hariç) |
| `java` (web) | `<e2e-java>/src/test/java/**/*Test.java` (`uretilen/` ve `birim/` hariç) |
| `csharp` | Playwright'a başvuran bir `*.csproj`'un dizini altında `*Tests.cs` / `*Test.cs` |
| `python` | Playwright'a başvuran proje dosyasının dizini altında `test_*.py` / `*_test.py` |

En çok dosyası olan dil seçilir; eşitlikte öncelik `ts > java > csharp > python`; hiç dosya yoksa
platformun varsayılanı (`kaynak="varsayilan"`). Uygulama platformlarında tek dil Java'dır
(`<e2e-app>/src/test/java/**/*Test.java` sayılır).

**Playwright işareti (sözleşmeye ek):** C# ve Python'da yalnız Playwright projesinin testleri
sayılır (`*.csproj` içinde `Microsoft.Playwright`; `pyproject.toml` / `requirements*.txt` /
`conftest.py` / `pytest.ini` içinde `playwright`). Ham `**/test_*.py` sayımı, uygulamanın kendi
birim testlerini (ör. `demo-app/api/tests/test_*.py`) uçtan uca test sanır ve dili yanlış seçerdi.

Sonuç `(commit sha, platform, uygulama kökü)` ile süreç içinde önbelleklenir (commit'ler
değişmez). Forge hatasında sonuç `varsayilan`'dır ve önbelleğe yazılmaz: algılama kod üretimini
hiçbir zaman engellemez.
"""

from __future__ import annotations

import logging
import posixpath
import re
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from tp_core.features.codegen import platform as platformlar

log = logging.getLogger(__name__)

_CACHE_MAX = 64
_SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
TS_URETILEN = "tests/generated/"
JAVA_HARIC = ("/uretilen/", "/birim/")
PY_PROJE_DOSYALARI = ("pyproject.toml", "conftest.py", "pytest.ini", "setup.cfg", "tox.ini")
_PY_REQ_RE = re.compile(r"^requirements[\w.-]*\.txt$")
_PY_TEST_RE = re.compile(r"^(test_[^/]*|[^/]*_test)\.py$")
_CS_TEST_RE = re.compile(r"^[^/]*Tests?\.cs$")
# Okunan işaret dosyası sayısı sınırı (GitHub kipinde her okuma bir API çağrısıdır).
MAX_ISARET_OKUMA = 20


@dataclass(frozen=True)
class Algilama:
    """`dil`: seçilen dil; `kaynak`: `algilandi` | `varsayilan`; `sayilar`: dil → dosya sayısı
    (platformun geçerli dilleri). `projeler`: tam hat dilinin test projesi repoda var mı
    (ts → `<e2e>/package.json`, java → `pom.xml`); forge okunamadıysa boş (bilinmiyor)."""

    dil: str
    kaynak: str
    sayilar: dict[str, int] = field(default_factory=dict)
    projeler: dict[str, bool] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"dil": self.dil, "kaynak": self.kaynak, "sayilar": dict(self.sayilar)}


_CACHE: OrderedDict[tuple[str, str, str], Algilama] = OrderedDict()
_LOCK = threading.Lock()


def onbellegi_temizle() -> None:
    with _LOCK:
        _CACHE.clear()


def varsayilan(platform: str | None) -> Algilama:
    """Algılama sonuçsuz / yapılamadı: platformun varsayılan dili, sayılar sıfır."""
    return Algilama(
        platformlar.varsayilan_dil(platform),
        "varsayilan",
        {d: 0 for d in platformlar.platform_dilleri(platform)},
    )


def _kok(uygulama_koku: str, dizin: str) -> str:
    return f"{uygulama_koku}/{dizin}" if uygulama_koku else dizin


def _altinda(yol: str, kok: str) -> str | None:
    """`yol` `kok` dizininin altındaysa köke göre yol; değilse None (`kok=""` → tüm depo)."""
    if not kok:
        return yol
    return yol[len(kok) + 1 :] if yol.startswith(kok + "/") else None


def _ts_say(dosyalar: Sequence[str], e2e: str) -> int:
    n = 0
    for yol in dosyalar:
        goreli = _altinda(yol, e2e)
        if goreli is None or not goreli.startswith("tests/") or not goreli.endswith(".spec.ts"):
            continue
        if goreli.startswith(TS_URETILEN):
            continue
        n += 1
    return n


def _java_say(dosyalar: Sequence[str], kok: str) -> int:
    n = 0
    for yol in dosyalar:
        goreli = _altinda(yol, kok)
        if goreli is None or not goreli.startswith("src/test/java/"):
            continue
        if not goreli.endswith("Test.java") or any(h in "/" + goreli for h in JAVA_HARIC):
            continue
        n += 1
    return n


def _playwright_dizinleri(
    forge: Any, sha: str, adaylar: Sequence[str], isaret: str, butce: list[int]
) -> list[str]:
    """İçeriği `isaret`'i (büyük/küçük harf duyarsız) taşıyan aday dosyaların dizinleri."""
    dizinler: list[str] = []
    for yol in sorted(adaylar, key=lambda y: (y.count("/"), y)):
        if butce[0] <= 0:
            break
        dizin = posixpath.dirname(yol)
        if any(dizin == d or dizin.startswith(d + "/") or d == "" for d in dizinler):
            continue  # üst dizin zaten Playwright projesi
        butce[0] -= 1
        try:
            icerik = forge.read_file(yol, ref=sha)
        except Exception:  # okunamayan işaret dosyası proje sayılmaz
            continue
        if isaret in (icerik or "").lower():
            dizinler.append(dizin)
    return dizinler


def _proje_altinda(yol: str, dizinler: Sequence[str]) -> bool:
    dizin = posixpath.dirname(yol)
    return any(d == "" or dizin == d or dizin.startswith(d + "/") for d in dizinler)


def _csharp_say(forge: Any, sha: str, dosyalar: Sequence[str], butce: list[int]) -> int:
    projeler = [y for y in dosyalar if y.endswith(".csproj")]
    if not projeler:
        return 0
    dizinler = _playwright_dizinleri(forge, sha, projeler, "microsoft.playwright", butce)
    return sum(
        1
        for y in dosyalar
        if _CS_TEST_RE.match(posixpath.basename(y)) and _proje_altinda(y, dizinler)
    )


def _python_say(forge: Any, sha: str, dosyalar: Sequence[str], butce: list[int]) -> int:
    testler = [y for y in dosyalar if _PY_TEST_RE.match(posixpath.basename(y))]
    if not testler:
        return 0
    isaretler = [
        y
        for y in dosyalar
        if posixpath.basename(y) in PY_PROJE_DOSYALARI or _PY_REQ_RE.match(posixpath.basename(y))
    ]
    dizinler = _playwright_dizinleri(forge, sha, isaretler, "playwright", butce)
    return sum(1 for y in testler if _proje_altinda(y, dizinler))


def _say(forge: Any, sha: str, platform: str, uygulama_koku: str) -> Algilama:
    tum = forge.list_files(prefix=f"{uygulama_koku}/" if uygulama_koku else "", ref=sha)
    kume = set(tum)
    if platformlar.uygulama_mi(platform):
        kok = _kok(uygulama_koku, platformlar.E2E_APP_DIZINI)
        sayilar = {platformlar.JAVA: _java_say(tum, kok)}
        projeler = {platformlar.JAVA: f"{kok}/pom.xml" in kume}
    else:
        e2e = _kok(uygulama_koku, "e2e")
        e2e_java = _kok(uygulama_koku, platformlar.E2E_JAVA_DIZINI)
        # e2e-app (Appium) ve e2e-java ağaçları C#/Python sayımına girmez; node_modules izlenmez.
        butce = [MAX_ISARET_OKUMA]
        sayilar = {
            "ts": _ts_say(tum, e2e),
            "java": _java_say(tum, e2e_java),
            "csharp": _csharp_say(forge, sha, tum, butce),
            "python": _python_say(forge, sha, tum, butce),
        }
        projeler = {"ts": f"{e2e}/package.json" in kume, "java": f"{e2e_java}/pom.xml" in kume}
    en_cok = max(sayilar.values(), default=0)
    if en_cok <= 0:
        return Algilama(platformlar.varsayilan_dil(platform), "varsayilan", sayilar, projeler)
    # Eşitlikte öncelik DILLER sırasıdır: ts > java > csharp > python.
    dil = next(d for d in platformlar.DILLER if sayilar.get(d) == en_cok)
    return Algilama(dil, "algilandi", sayilar, projeler)


def algila(
    forge: Any, ref: str = "main", platform: str | None = None, *, uygulama_koku: str | None = None
) -> Algilama:
    """Hedef repodaki elle yazılmış testlerden üretim dilini algılar (bkz. modül açıklaması).

    `ref` dal adı ya da commit sha'sıdır (dal sha'ya çözülür; önbellek sha'ya bağlıdır).
    `uygulama_koku` verilmezse `TP_FORGE_APP_ROOT` kuralı (`service.app_root`). Hiçbir hata dışarı
    sızmaz: forge okunamazsa `varsayilan` döner.
    """
    p = platform or platformlar.WEB
    if p not in platformlar.PLATFORMLAR:
        return varsayilan(platformlar.WEB)
    try:
        if uygulama_koku is None:
            from tp_core.features.codegen.service import app_root

            uygulama_koku = app_root()
        kok = uygulama_koku.strip().strip("/")
        sha = ref if _SHA_RE.match(ref or "") else forge.head_sha(ref or "main")
        anahtar = (str(sha), p, kok)
        with _LOCK:
            if anahtar in _CACHE:
                _CACHE.move_to_end(anahtar)
                return _CACHE[anahtar]
        sonuc = _say(forge, str(sha), p, kok)
    except Exception as exc:  # forge erişilemez / depo okunamaz: üretimi engelleme
        log.warning("dil algılanamadı (%s, %s): %s", p, ref, exc)
        return varsayilan(p)
    with _LOCK:
        _CACHE[anahtar] = sonuc
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return sonuc
