"""Java / Appium (009 mobil-masaüstü) triage kanıtı ve kural 3'ün uygulama karşılığı. AI yok.

Uygulama testleri (`demo-app/e2e-app`, Java + Appium + TestNG) başarısız olunca kanıtı
`target/kanit/<Sınıf>.<metot>/{ekran.png, sayfa-kaynagi.xml}` altına yazar (`altyapi/Kanit.java`);
Surefire JUnit XML'de `testcase@classname` paketli sınıf adı, `@name` metot adıdır.

- `java_mi`: test bir Java testi mi? Önce dile bakar (011: `ts` | `java`; koşu raporu / script),
  sonra uygulama platformuna, sonra dosya/sınıf adına ya da Java istisnasına. `web` artık "Java
  değil" demek değildir: web + Java (Playwright for Java) testleri `triage.java_web`'de.
- `kanit_dizini_adi`: `Kanit.dizin` ile aynı indirgeme (`Sınıf.metot`, güvenli karakterler).
- `sayfa_kaynagi_oku`: koşu dizini içinden (sembolik bağ / kök dışı yol yok, boyut sınırlı) sayfa
  kaynağı + ekran görüntüsü yolu.
- `kimlik_dugumleri`: sayfa kaynağı XML'i (güvenilmeyen) DTD/varlık bildirimi olmadan, boyut ve
  düğüm sınırıyla ayrıştırılır; her öğenin erişilebilirlik kimliği (Android `resource-id`, iOS
  `name` — `label`'a eşitse kimlik sayılmaz, Windows `AutomationId`) ve kapsayıcı kimlik zinciri.
- `kimlik_zinciri`: hata metnindeki kimlikler (`Ekran.java`: "kimlik 'kapsayıcı' içinde 'aranan'").
- `aday_kimlik`: kırık kimliğin yerine geçen aday — hata anındaki ekranda eski kimlik YOK ve
  (kapsayıcı içinde) sembol tablosunda tanımsız, eski kimlikle ortak sözcüğü olan TEK kimlik var.
  Web'deki rol + ad yoklamasının yerine geçer (Java kimliklerinde rol/ad yoktur, §2.5); aday
  insan onaylı PR'dan önce cihazda tam paketle yeniden doğrulanır (onarım adım 7).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tp_core.features.codegen import platform as platformlar
from tp_core.features.triage import evidence as ev

UYGULAMA_PLATFORMLARI = frozenset(platformlar.UYGULAMA_PLATFORMLARI)
MAX_SAYFA_KAYNAGI = 4 * 1024 * 1024
MAX_DUGUM = 20_000
MAX_DERINLIK = 200
MAX_PAYLASIM = 20_000  # failure_ek / LLM girdisine giden sayfa kaynağı metni (kırpılır)
KANIT_EKRAN = "ekran.png"
KANIT_KAYNAK = "sayfa-kaynagi.xml"
# Koşu dizini içinde kanıt kökünün olası yerleri (test-runner Java yolu, Ş8).
KANIT_KOKLERI = ("target/kanit", "kanit", "e2e-app/target/kanit")
# Paketli Java sınıf adı (Surefire classname) ya da .java yolu.
_FQCN_RE = re.compile(r"\A(?:[a-z_][a-z0-9_]*\.)+[A-Z][A-Za-z0-9_$]*\Z")
_JAVA_ISTISNA_RE = re.compile(r"\b(?:java\.lang\.|org\.openqa\.selenium\.|io\.appium\.)")
_GUVENSIZ_RE = re.compile(r"[^A-Za-z0-9._-]")
# Ekran.java `ad()`: "kimlik 'a'" ya da "kimlik 'kapsayıcı' içinde 'aranan'"; `biriGorunurBekle`:
# "kimlik 'a' ya da 'b'" (iki aday: belirsiz).
_KIMLIK_RE = re.compile(
    r"kimlik '(?P<a>[^'\n]{1,200})'(?: (?P<bag>içinde|ya da) '(?P<b>[^'\n]{1,200})')?"
)
_SOZCUK_RE = re.compile(r"[A-Za-z0-9]+")


def java_mi(
    platform: str | None, dosya: str | None, mesaj: str | None = None, dil: str | None = None
) -> bool:
    """Kod/derleme sorusu dile bakar (011 §2.1): `dil` biliniyorsa o karar verir; uygulama
    platformu her zaman Java'dır; bilinmiyorsa dosya adı (`.java` / paketli sınıf → Java, `.ts` →
    Playwright TS) ya da (dosya yoksa ve platform web değilse) Java istisna metni."""
    if platform in UYGULAMA_PLATFORMLARI:
        return True
    if dil == "java":
        return True
    if dil == "ts":
        return False
    d = (dosya or "").strip()
    if d.endswith(".java") or _FQCN_RE.match(d):
        return True
    if d.endswith(".ts"):  # Playwright testi: Java istisna metni geçse de web
        return False
    if platform == "web":
        # Web'de dil ve dosya bilinmiyorsa (eski kayıt) TS varsayılır: metindeki bir Java istisna
        # adı tek başına Java demek değildir (bugünkü davranış).
        return False
    return bool(_JAVA_ISTISNA_RE.search(mesaj or ""))


def sinif_adi(dosya: str | None) -> str | None:
    """`com.x.TPD1C3_0a1b2c3dTest` ya da `…/TPD1C3_0a1b2c3dTest.java` → `TPD1C3_0a1b2c3dTest`."""
    d = (dosya or "").strip()
    if not d:
        return None
    d = d.rsplit("/", 1)[-1]
    if d.endswith(".java"):
        d = d[:-5]
    return d.rsplit(".", 1)[-1] or None


def kanit_dizini_adi(dosya: str | None, test_adi: str) -> str | None:
    """`Kanit.dizin` ile aynı: `Sınıf.metot`, `[^A-Za-z0-9._-]` → `_`.

    `test_adi` Surefire metot adı (`senaryo`), paketli ad (`…Test.senaryo`) ya da test-runner /
    çekirdek JUnit kimliği (`<Sınıf> › <metot>`, `ci.parse.java_test_kimligi`) olabilir."""
    sinif = sinif_adi(dosya)
    metot = (test_adi or "").strip().rsplit(" › ", 1)[-1].rsplit(".", 1)[-1]
    if not sinif or not metot:
        return None
    ad = _GUVENSIZ_RE.sub("_", f"{sinif}.{metot}")
    return ad if ad not in (".", "..") else None


@dataclass
class JavaKaniti:
    sayfa_kaynagi: str | None = None
    kaynak_rel: str | None = None  # koşu dizinine göre
    ekran_rel: str | None = None
    uyari: str | None = None


def sayfa_kaynagi_oku(
    kosu: Path | None,
    kosu_rel: str | None,
    failure: Mapping[str, Any],
    dosya: str | None,
    test_adi: str,
) -> JavaKaniti:
    """Koşu dizinindeki Java kanıtı. Önce raporun `failure.evidence.page_source|screenshot.rel`
    yolu (TP_ARTIFACTS_PATH'e göre), yoksa `KANIT_KOKLERI/<Sınıf.metot>/`."""
    out = JavaKaniti()
    if kosu is None or not kosu_rel:
        return out
    kanitlar = ev.mapping(failure.get("evidence"))
    adaylar_kaynak: list[str] = []
    adaylar_ekran: list[str] = []
    k = ev.kanit_yolu(kosu_rel, ev.mapping(kanitlar.get("page_source")).get("rel"))
    if k:
        adaylar_kaynak.append(k)
    e = ev.kanit_yolu(kosu_rel, ev.mapping(kanitlar.get("screenshot")).get("rel"))
    if e:
        adaylar_ekran.append(e)
    ad = kanit_dizini_adi(dosya, test_adi)
    if ad:
        adaylar_kaynak += [f"{kok}/{ad}/{KANIT_KAYNAK}" for kok in KANIT_KOKLERI]
        adaylar_ekran += [f"{kok}/{ad}/{KANIT_EKRAN}" for kok in KANIT_KOKLERI]
    for rel in adaylar_kaynak:
        try:
            veri = ev.guvenli_oku(kosu / rel, kosu, MAX_SAYFA_KAYNAGI)
        except ev.KanitHatasi as exc:
            out.uyari = f"sayfa kaynağı okunamadı: {exc}"
            continue
        if veri is not None:
            out.sayfa_kaynagi = veri.decode("utf-8", "replace")
            out.kaynak_rel = rel
            break
    for rel in adaylar_ekran:
        try:
            yol = kosu / rel
            if yol.is_file() and not yol.is_symlink():
                kok_c, yol_c = kosu.resolve(), yol.resolve()
                if kok_c in yol_c.parents:
                    out.ekran_rel = rel
                    break
        except OSError:
            continue
    return out


# ------------------------------------------------------------------------- sayfa kaynağı


@dataclass(frozen=True)
class KimlikDugumu:
    kimlik: str
    etiket: str  # XML öğe adı (android.widget.Button, XCUIElementTypeButton, Button)
    metin: str  # görünen metin / etiket (varsa)
    kapsayicilar: tuple[str, ...] = field(default_factory=tuple)  # dıştan içe kimlikler


class SayfaKaynagiHatasi(ValueError):
    pass


def _dtd_yok(veri: bytes) -> None:
    from xml.parsers import expat

    class _Dtd(Exception):
        pass

    def _reddet(*_: Any) -> None:
        raise _Dtd

    p = expat.ParserCreate()
    p.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    p.StartDoctypeDeclHandler = _reddet
    p.EntityDeclHandler = _reddet
    p.UnparsedEntityDeclHandler = _reddet
    p.ExternalEntityRefHandler = _reddet
    try:
        p.Parse(veri, True)
    except _Dtd as exc:
        raise SayfaKaynagiHatasi("sayfa kaynağı DTD/varlık bildirimi içeremez") from exc
    except (expat.ExpatError, ValueError, LookupError) as exc:
        raise SayfaKaynagiHatasi(f"sayfa kaynağı ayrıştırılamadı: {exc}") from exc


def _kimlik(oge: ET.Element, platform: str | None) -> str | None:
    """Öğenin erişilebilirlik kimliği (app-mcp `[id=…]` kuralıyla aynı)."""
    adaylar: list[str] = []
    if platform in (None, "android"):
        rid = oge.get("resource-id") or ""
        if rid:
            paket, ayrac, ad = rid.partition(":id/")
            if not ayrac:
                adaylar.append(rid)
            elif paket != "android":
                adaylar.append(ad)
    if platform in (None, "ios"):
        ad = oge.get("name") or ""
        if ad and ad != (oge.get("label") or ""):
            adaylar.append(ad)
    if platform in (None, "windows"):
        aid = oge.get("AutomationId") or ""
        if aid:
            adaylar.append(aid)
    for a in adaylar:
        a = a.strip()
        if a and ev.TESTID_RE.match(a):
            return a
    return None


def kimlik_dugumleri(metin: str | None, platform: str | None = None) -> list[KimlikDugumu]:
    """Sayfa kaynağındaki kimlikli öğeler (belge sırası). Bozuk/kötü niyetli XML → hata."""
    if not metin:
        return []
    veri = metin.encode("utf-8")
    if len(veri) > MAX_SAYFA_KAYNAGI:
        raise SayfaKaynagiHatasi("sayfa kaynağı boyut sınırını aşıyor")
    _dtd_yok(veri)
    try:
        kok = ET.fromstring(veri)
    except ET.ParseError as exc:
        raise SayfaKaynagiHatasi(f"sayfa kaynağı ayrıştırılamadı: {exc}") from exc
    out: list[KimlikDugumu] = []
    sayac = [0]

    def gez(oge: ET.Element, zincir: tuple[str, ...], derinlik: int) -> None:
        sayac[0] += 1
        if sayac[0] > MAX_DUGUM or derinlik > MAX_DERINLIK:
            raise SayfaKaynagiHatasi("sayfa kaynağı düğüm/derinlik sınırını aşıyor")
        k = _kimlik(oge, platform)
        if k:
            metin_ = oge.get("text") or oge.get("label") or oge.get("content-desc") or ""
            out.append(KimlikDugumu(k, str(oge.tag)[:80], ev.temiz(metin_, 120), zincir))
            zincir = (*zincir, k)
        for c in oge:
            gez(c, zincir, derinlik + 1)

    gez(kok, (), 0)
    return out


def kimlik_zinciri(*metinler: Any) -> tuple[str | None, str | None, bool]:
    """(aranan, kapsayıcı, belirsiz) — hata metnindeki ilk kimlik ifadesinden."""
    for m in metinler:
        if not m:
            continue
        r = _KIMLIK_RE.search(str(m)[:4000])
        if r is None:
            continue
        a, bag, b = r.group("a"), r.group("bag"), r.group("b")
        if bag == "içinde" and b:
            return b, a, False
        if bag == "ya da":
            return a, None, True
        return a, None, False
    return None, None, False


def _sozcukler(kimlik: str) -> set[str]:
    return {s.lower() for s in _SOZCUK_RE.findall(kimlik) if len(s) >= 3}


@dataclass
class AdaySonucu:
    yeni: str | None
    neden: str | None
    eski_ekranda: bool = False
    kapsam_bulundu: bool | None = None
    tanimsiz: list[str] = field(default_factory=list)
    benzer: list[str] = field(default_factory=list)


def bilinen_kimlikler(semboller: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    """Sembol tablosundaki (sabit kimlikler, önekler)."""
    sabit: set[str] = set()
    onek: set[str] = set()
    for po in semboller.get("page_objects") or []:
        if not isinstance(po, Mapping):
            continue
        for loc in ev.mapping(po.get("locators")).values():
            if not isinstance(loc, Mapping):
                continue
            tid = str(loc.get("testId") or "")
            if not tid:
                continue
            (onek if loc.get("prefix") else sabit).add(tid)
    return sabit, onek


def aday_kimlik(
    dugumler: Iterable[KimlikDugumu],
    eski: str,
    kapsam: str | None,
    sabit: set[str],
    onekler: set[str],
) -> AdaySonucu:
    """Kırık kimliğin hata anındaki ekranda tek adayı (deterministik; bkz. modül belgesi)."""
    liste = list(dugumler)
    if any(d.kimlik == eski for d in liste):
        return AdaySonucu(
            None,
            f"Eski kimlik '{eski}' hata anındaki ekranda var; kimlik kırılması değil "
            "(zamanlama / görünürlük olabilir)",
            eski_ekranda=True,
        )
    if kapsam:
        if not any(d.kimlik == kapsam for d in liste):
            return AdaySonucu(
                None,
                f"Kapsayıcı '{kapsam}' hata anındaki ekranda yok; aday aranamaz",
                kapsam_bulundu=False,
            )
        liste = [d for d in liste if kapsam in d.kapsayicilar]
    tanimsiz = sorted(
        {
            d.kimlik
            for d in liste
            if d.kimlik not in sabit
            and d.kimlik != kapsam
            and not any(d.kimlik.startswith(o) for o in onekler)
        }
    )
    hedef = _sozcukler(eski)
    benzer = [k for k in tanimsiz if hedef & _sozcukler(k)]
    sonuc = AdaySonucu(None, None, kapsam_bulundu=True if kapsam else None)
    sonuc.tanimsiz, sonuc.benzer = tanimsiz[:20], benzer[:20]
    if len(benzer) != 1:
        sonuc.neden = (
            f"Hata anındaki ekranda '{eski}' yerine geçen tek aday yok "
            f"(tanımsız kimlikler: {', '.join(tanimsiz[:5]) or '—'}; "
            f"ortak sözcüklü: {', '.join(benzer[:5]) or '—'})"
        )
        return sonuc
    sonuc.yeni = benzer[0]
    return sonuc


def kisalt(metin: str | None) -> str | None:
    """Sayfa kaynağının saklanan/LLM'e giden kırpılmış hali (kontrol karakterleri temizlenir)."""
    if not metin:
        return None
    return ev.temiz(metin, MAX_PAYLASIM)
