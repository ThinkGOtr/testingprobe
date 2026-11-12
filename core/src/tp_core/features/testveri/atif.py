"""`{veri:anahtar}` atfı: saf fonksiyonlar (veritabanı yok; specs/013-sprint-otomasyonu §3.3).

Sözleşme:
- Atıf biçimi `{veri:<anahtar>}`; anahtar `^[a-z0-9_]+(\\.[a-z0-9_]+){0,5}$`.
- `esle(metin, katalog)`: katalogdaki değerlerin metindeki tam geçişlerini atfa çevirir.
  Kurallar: değer en az 3 karakter; eşleşme kelime sınırında (önünde/arkasında harf-rakam yok);
  uzun değer önce; aynı değer birden çok anahtarda varsa (belirsiz) eşlenmez; zaten atıf içinde
  olan metne dokunulmaz.
- `coz(metin, degerler)`: atıfları değere çevirir. Değişmez: katalog değişmediyse
  `coz(esle(m, k), k) == m` (replay girdileri ve kod üretimindeki kaynak kontrolü bunu bekler).
- Case içeriğinde yalnız şu alanlar eşlenir/çözülür: `preconditions[]`, `steps[].action`,
  `steps[].data`, `steps[].expected`, `expected_result` (başlıkta açık değer kalır; K22: gizli
  değer başlık dahil her metin alanında atfa döner, bkz. aşağı; çözüm yalnız bu alanlarda).
- K18 (013 §9): `case_esle` yalnız `bayi.*`, `urun.*`, `kampanya.*`, `ortak.*` anahtarlarını eşler
  (`etiket.*`, `ayar.*` katalogda kalır, eşlenmez). Tutar biçimli değerler (`… TL`, salt sayı)
  yalnız `steps[].data` ve `preconditions`'ta eşlenir: beklenen sonuçtaki hesaplanmış bir toplam
  tesadüfen kredi limitine eşit diye atfa dönmez.
- QA #11: değerin tekilliği (belirsizlik) **tüm katalogla** sınanır, grup/tutar süzgeci sonra
  uygulanır: bir ürün değeri bir `etiket.*` değeriyle aynıysa belirsizdir, eşlenmez.
- `case_esle(..., takma=...)`: katalog dışı bilinen değer → anahtar eşlemesi (ör. DB bloğunun
  sabit demo parolası → `ortak.demo_parola`; K19 "sır tanımsız → engel" yolu için).
- `maskele` / `maskele_obje`: bilinen gizli değerlerin geçişlerini `•••` yapar (K19; case dışı
  metinler: bug taslağı, PR, log, denetim, yayın). Güvenlik tur 3 #2: en az `MIN_DEGER` karakter,
  **alt dize** (kelime sınırı yok: `Demo123!x`, `"Demo123!"`, JSON kaçışlı biçim de yakalanır);
  atıf metnine (`{veri:…}`) dokunulmaz; `maskele_obje` yapısal alanlara (id, hash, sha, durum...)
  dokunmaz. `gizli_geciyor_mu` (render sonrası sızıntı taraması) aynı alt dize kuralıyla.
  Kelime sınırı yalnız atıf eşlemesinde (`esle`, `case_esle`, `case_gizli_esle`) kalır.
- K22 (013 §9): case içeriğinde gizli değer `•••` değil geri dönüşebilir atıf olarak gösterilir.
  `gizli_eslem`: yalnız gizli kayıtların değer → anahtar eşlemi (tekillik tüm katalogla; açık
  değerler K18 gereği başlıkta eşlenmez). `case_gizli_esle`: başlık ve etiketler dahil tüm metin
  alanlarında (yapısal alanlar hariç) gizli değeri atfa çevirir. `case_gorunum`: API görünümü =
  `case_gizli_esle` + kalan (bitişik / belirsiz) geçişlerin maskesi. `maske_iceriyor_mu` /
  `gizli_kalan`: düzeltme (edit) gövdesi denetimleri.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

ANAHTAR_DESEN = r"[a-z0-9_]+(?:\.[a-z0-9_]+){0,5}"
ANAHTAR_RE = re.compile(rf"^{ANAHTAR_DESEN}$")
ATIF_RE = re.compile(rf"\{{veri:({ANAHTAR_DESEN})\}}")
MIN_DEGER = 3
# K18: eşlemeye giren anahtar grupları (anahtarın ilk parçası).
ESLENEN_GRUPLAR = frozenset({"bayi", "urun", "kampanya", "ortak"})
# Tutar biçimi: "1.250,00 TL", "500,00 TL", "750.00", "12" (isteğe bağlı eksi, " TL" son eki).
TUTAR_RE = re.compile(r"^-?\d[\d.,]*(?: TL)?$")
MASKE = "•••"


def atif(anahtar: str) -> str:
    if not ANAHTAR_RE.match(anahtar):
        raise ValueError(f"geçersiz test verisi anahtarı: {anahtar!r}")
    return f"{{veri:{anahtar}}}"


def atiflar(metin: str) -> list[str]:
    """Metindeki atıf anahtarları (sırayla, tekrarsız)."""
    return list(dict.fromkeys(ATIF_RE.findall(metin or "")))


def _sayac(katalog: Mapping[str, str]) -> dict[str, list[str]]:
    """değer → anahtarlar (yalnız eşlenebilir uzunluktaki, kırpılmış değerler)."""
    sayac: dict[str, list[str]] = {}
    for anahtar, deger in katalog.items():
        if isinstance(deger, str) and len(deger.strip()) >= MIN_DEGER and deger == deger.strip():
            sayac.setdefault(deger, []).append(anahtar)
    return sayac


def _tekil_degerler(katalog: Mapping[str, str]) -> dict[str, str]:
    """değer → anahtar; belirsiz (birden çok anahtarlı) ve kısa değerler çıkarılır."""
    return {d: a[0] for d, a in _sayac(katalog).items() if len(a) == 1}


def _esle_tekil(metin: str, tekil: Mapping[str, str]) -> str:
    if not metin or not tekil:
        return metin
    degerler = sorted(tekil, key=len, reverse=True)
    desen = re.compile(r"(?<![\w])(" + "|".join(re.escape(d) for d in degerler) + r")(?![\w])")
    # Mevcut atıfları koru: metni atıflar ve aradaki parçalar olarak böl.
    out: list[str] = []
    son = 0
    for m in ATIF_RE.finditer(metin):
        out.append(desen.sub(lambda x: atif(tekil[x.group(1)]), metin[son : m.start()]))
        out.append(m.group(0))
        son = m.end()
    out.append(desen.sub(lambda x: atif(tekil[x.group(1)]), metin[son:]))
    return "".join(out)


def esle(metin: str, katalog: Mapping[str, str]) -> str:
    """Değerleri atfa çevirir (yukarıdaki kurallar). `katalog`: anahtar → değer."""
    if not metin:
        return metin
    return _esle_tekil(metin, _tekil_degerler(katalog))


def coz(metin: str, degerler: Mapping[str, str], *, bilinmeyen: str = "hata") -> str:
    """Atıfları değerlerle değiştirir. `bilinmeyen`: "hata" (KeyError) | "birak"."""

    def _yerine(m: re.Match[str]) -> str:
        anahtar = m.group(1)
        if anahtar in degerler:
            return degerler[anahtar]
        if bilinmeyen == "birak":
            return m.group(0)
        raise KeyError(anahtar)

    return ATIF_RE.sub(_yerine, metin or "")


def _alanlari_donustur(
    case: Mapping[str, Any],
    f: Callable[[str], str],
    f_serbest: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """`f`: `preconditions[]`, `steps[].data`; `f_serbest` (varsayılan `f`): `steps[].action`,
    `steps[].expected`, `expected_result`."""
    g = f_serbest or f
    out = dict(case)
    if isinstance(out.get("preconditions"), list):
        out["preconditions"] = [f(p) if isinstance(p, str) else p for p in out["preconditions"]]
    if isinstance(out.get("steps"), list):
        adimlar = []
        for s in out["steps"]:
            if isinstance(s, Mapping):
                s = dict(s)
                for k in ("action", "data", "expected"):
                    if isinstance(s.get(k), str):
                        s[k] = (f if k == "data" else g)(s[k])
            adimlar.append(s)
        out["steps"] = adimlar
    if isinstance(out.get("expected_result"), str):
        out["expected_result"] = g(out["expected_result"])
    return out


def eslenebilir_mi(anahtar: str) -> bool:
    """K18: yalnız bayi / ürün / kampanya / ortak grupları eşlenir."""
    return anahtar.split(".", 1)[0] in ESLENEN_GRUPLAR


def tutar_mi(deger: str) -> bool:
    return bool(TUTAR_RE.match(deger.strip()))


def case_esle(
    case: Mapping[str, Any],
    katalog: Mapping[str, str],
    takma: Mapping[str, str] | None = None,
    gizli_anahtarlar: Iterable[str] = (),
) -> dict[str, Any]:
    """K18 kurallarıyla eşleme: grup süzgeci; tutar değerleri yalnız veri/ön koşul alanlarında.

    Tekillik tüm katalogla sınanır, süzgeç sonra (QA #11). `takma`: değer → anahtar (katalogda
    değeri olmayan bilinen değerler); katalogdaki bir değerle çakışmıyorsa eklenir. K22: ardından
    gizli değerler (`gizli_anahtarlar` + takma) başlık dahil tüm metin alanlarında atfa çevrilir.
    """
    sayac = _sayac(katalog)
    tekil = {d: a[0] for d, a in sayac.items() if len(a) == 1}
    tum = {d: a for d, a in tekil.items() if eslenebilir_mi(a)}
    for d, a in (takma or {}).items():
        if (
            isinstance(d, str)
            and len(d.strip()) >= MIN_DEGER
            and d == d.strip()
            and eslenebilir_mi(a)
            and all(x == a for x in sayac.get(d, [a]))
        ):
            tum.setdefault(d, a)
    serbest = {d: a for d, a in tum.items() if not tutar_mi(d)}
    out = _alanlari_donustur(case, lambda m: _esle_tekil(m, tum), lambda m: _esle_tekil(m, serbest))
    return case_gizli_esle(out, gizli_eslem(katalog, gizli_anahtarlar, takma))


def case_coz(
    case: Mapping[str, Any], degerler: Mapping[str, str], *, bilinmeyen: str = "hata"
) -> dict[str, Any]:
    return _alanlari_donustur(case, lambda m: coz(m, degerler, bilinmeyen=bilinmeyen))


def case_atiflari(case: Mapping[str, Any]) -> list[str]:
    toplanan: list[str] = []

    def _topla(m: str) -> str:
        toplanan.extend(atiflar(m))
        return m

    _alanlari_donustur(case, _topla)
    return list(dict.fromkeys(toplanan))


def bilinmeyen_atiflar(case: Mapping[str, Any], anahtarlar: Iterable[str]) -> list[str]:
    bilinen = set(anahtarlar)
    return [a for a in case_atiflari(case) if a not in bilinen]


def _maske_listesi(gizliler: Iterable[str]) -> list[str]:
    return sorted(
        {g for g in gizliler if isinstance(g, str) and len(g.strip()) >= MIN_DEGER},
        key=len,
        reverse=True,
    )


def _maske_deseni(gizliler: Iterable[str]) -> re.Pattern[str] | None:
    """Alt dize deseni (güvenlik tur 3 #2: bitişik sır da yakalanır; uzundan kısaya)."""
    liste = _maske_listesi(gizliler)
    if not liste:
        return None
    return re.compile("|".join(re.escape(g) for g in liste))


def _atif_disinda(metin: str, f: Callable[[str], str]) -> str:
    """`f`'i yalnız atıfların (`{veri:…}`) dışındaki parçalara uygular."""
    out: list[str] = []
    son = 0
    for m in ATIF_RE.finditer(metin):
        out.append(f(metin[son : m.start()]))
        out.append(m.group(0))
        son = m.end()
    out.append(f(metin[son:]))
    return "".join(out)


# Maskelenmeyen yapısal alanlar (güvenlik #10): kimlik, özet, durum; değerleri sırrı taşımaz,
# alt dize değişimi bunları bozardı.
YAPISAL_ALANLAR = frozenset(
    {"id", "ids", "case_ids", "durum", "sha", "hash", "branch", "veri_izi", "mode", "platform"}
)
_YAPISAL_SONEK = ("_id", "_ids", "_hash", "_sha", "_key", "_url", "_zamani")


def yapisal_mi(anahtar: Any) -> bool:
    return isinstance(anahtar, str) and (
        anahtar in YAPISAL_ALANLAR or anahtar.endswith(_YAPISAL_SONEK)
    )


def gizli_geciyor_mu(metin: str, gizliler: Iterable[str]) -> list[str]:
    """Metinde (alt dize olarak, atıf dışında) geçen bilinen gizli değerler (render sonrası sızıntı
    taraması; boş = temiz). Güvenlik tur 3 #2: kelime sınırı yok; bulursa engel (fail-closed)."""
    desen = _maske_deseni(gizliler)
    if desen is None or not metin:
        return []
    bulunan: list[str] = []
    _atif_disinda(metin, lambda p: bulunan.extend(m.group(0) for m in desen.finditer(p)) or p)
    return list(dict.fromkeys(bulunan))


def _maskele_desenle(metin: str, desen: re.Pattern[str]) -> str:
    return _atif_disinda(metin, lambda p: desen.sub(MASKE, p))


def maskele(metin: str, gizliler: Iterable[str]) -> str:
    """Bilinen gizli değerlerin geçişlerini `•••` yapar (uzundan kısaya; en az `MIN_DEGER`
    karakter, alt dize; atıf metnine dokunmaz)."""
    if not metin:
        return metin
    desen = _maske_deseni(gizliler)
    return _maskele_desenle(metin, desen) if desen is not None else metin


def maskele_obje(obj: Any, gizliler: Iterable[str]) -> Any:
    """`maskele`'nin JSON benzeri yapılar (dict / list / str) için özyinelemeli hâli; yapısal
    alanlar (`yapisal_mi`) olduğu gibi kalır."""
    desen = _maske_deseni(gizliler)
    if desen is None:
        return obj

    def _m(x: Any) -> Any:
        if isinstance(x, str):
            return _maskele_desenle(x, desen)
        if isinstance(x, Mapping):
            return {k: (v if yapisal_mi(k) else _m(v)) for k, v in x.items()}
        if isinstance(x, list | tuple):
            return [_m(v) for v in x]
        return x

    return _m(obj)


# ------------------------------------------------------------------ K22: case görünümü / düzeltme

# Case içeriğinde gizli eşlemenin / maskenin dokunmadığı yapısal alanlar (enum, AC ref, adım no).
CASE_YAPISAL = frozenset({"type", "risk", "acceptance_criteria_refs", "id"})


def gizli_eslem(
    katalog: Mapping[str, str],
    gizli_anahtarlar: Iterable[str],
    takma: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """K22: değer → anahtar, YALNIZ gizli kayıtlar (+ gizli takma değerler). Tekillik tüm katalogla
    sınanır: aynı değer başka bir anahtarda da varsa belirsizdir, eşlenmez (görünümde maskelenir).
    Açık değerler burada yoktur (K18: başlıkta açık değer eşlenmez)."""
    gizli = set(gizli_anahtarlar)
    sayac = _sayac(katalog)
    out = {d: a[0] for d, a in sayac.items() if len(a) == 1 and a[0] in gizli}
    for d, a in (takma or {}).items():
        if (
            isinstance(d, str)
            and len(d.strip()) >= MIN_DEGER
            and d == d.strip()
            and all(x == a for x in sayac.get(d, [a]))
        ):
            out.setdefault(d, a)
    return out


def _case_metinleri(case: Mapping[str, Any], f: Callable[[str], str]) -> dict[str, Any]:
    """`f`'i case'in tüm metin alanlarına (başlık, etiketler, ön koşullar, adımlar, beklenen sonuç
    ve şema dışı ek alanlar) uygular; `CASE_YAPISAL` alanlar olduğu gibi kalır."""

    def _d(x: Any) -> Any:
        if isinstance(x, str):
            return f(x)
        if isinstance(x, Mapping):
            return {k: (v if k in CASE_YAPISAL else _d(v)) for k, v in x.items()}
        if isinstance(x, list | tuple):
            return [_d(v) for v in x]
        return x

    return {k: (v if k in CASE_YAPISAL else _d(v)) for k, v in case.items()}


def case_gizli_esle(case: Mapping[str, Any], eslem: Mapping[str, str]) -> dict[str, Any]:
    """K22: gizli değerleri başlık dahil tüm metin alanlarında atfa çevirir (kelime sınırında,
    tekil değerler; mevcut atıflara dokunulmaz). `eslem`: `gizli_eslem` çıktısı."""
    if not eslem:
        return dict(case)
    return _case_metinleri(case, lambda m: _esle_tekil(m, eslem))


def case_gorunum(
    case: Mapping[str, Any], eslem: Mapping[str, str], gizliler: Iterable[str]
) -> dict[str, Any]:
    """K22 API görünümü: gizli değer atfa (`case_gizli_esle`); atfa dönemeyen kalan geçişler
    (bitişik sır, belirsiz değer) `•••`. Yalnız görünüm: saklanan içerik ve hash değişmez."""
    desen = _maske_deseni(gizliler)

    def _f(m: str) -> str:
        m = _esle_tekil(m, eslem) if eslem else m
        return _maskele_desenle(m, desen) if desen is not None else m

    return _case_metinleri(case, _f)


def metin_gorunum(metin: str, eslem: Mapping[str, str], gizliler: Iterable[str]) -> str:
    """`case_gorunum`'un tek metin (ör. case başlığı) hâli."""
    return str(case_gorunum({"x": metin}, eslem, gizliler)["x"])


def maske_iceriyor_mu(case: Mapping[str, Any]) -> bool:
    """Düzeltme gövdesinde maske (`•••`) var mı (maskeli görünüm geri gönderilmiş)?"""
    bulundu = False

    def _f(m: str) -> str:
        nonlocal bulundu
        bulundu = bulundu or MASKE in m
        return m

    _case_metinleri(case, _f)
    return bulundu


def gizli_kalan(case: Mapping[str, Any], gizliler: Iterable[str]) -> bool:
    """`case_gizli_esle` sonrası atıf dışında hâlâ gizli değer geçiyor mu (bitişik yazım)?"""
    kalan = False

    def _f(m: str) -> str:
        nonlocal kalan
        kalan = kalan or bool(gizli_geciyor_mu(m, gizliler))
        return m

    _case_metinleri(case, _f)
    return kalan


def case_tum_atiflari(case: Mapping[str, Any]) -> list[str]:
    """Başlık / etiketler dahil tüm metin alanlarındaki atıflar (sırayla, tekrarsız)."""
    toplanan: list[str] = []

    def _f(m: str) -> str:
        toplanan.extend(atiflar(m))
        return m

    _case_metinleri(case, _f)
    return list(dict.fromkeys(toplanan))
