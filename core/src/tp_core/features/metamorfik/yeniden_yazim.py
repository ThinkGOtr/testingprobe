"""Metamorfik türetmenin saf (DB'siz, LLM'siz) çekirdeği (ANALIZ §4.5).

Girdi: kaynak case içeriği, kaynağın güncel oracle kontrolünün bir grubu (§4.3 `ayrintilar.
gruplar[]`) ve ilişki içeriği. Çıktı: türetilen case içeriği ya da atlama nedeni.

Kurallar (spesifikasyonun sustuğu yerlerde burada sabitlenir):

- **Yalnız uyumlu grup.** Grubun `durum`'u varsa `uyumlu` olmalı (değilse `olgu_yok`): tabloyla
  çelişen ya da değerlendirilemeyen bir case'in değerleri ilişkiyle çoğaltılmaz.
- **Doğrulanmış olgu.** Grubun `girdiler[]` olguları (`{column, value, field, quote}`) girdi,
  `karsilastirmalar[]` (`{column, alan, alinti, case_degeri}`) çıktı olgusudur. Kontrol kaydı
  yalnız doğrulanmış olguları taşır; yine de burada yeniden doğrulanır: alan case'te bulunmalı,
  alıntı o alanda geçmeli ve sayı alıntısı `sayi_ayristir` ile değere eşit okunmalı. Tutmayan
  olgu yok sayılır. `uyumlu: false` karşılaştırma olgu sayılmaz.
- **Karşılaştırılamayan değer dönüştürülmez.** `karsilastirilamayan[]` (tablonun eksik girdi
  yüzünden hesaplayamadığı beklenen değer) doğrulanmamış bir beklentidir: ilişkiyle yeni değere
  taşınmaz. Grupta böyle bir değer varsa ve alıntısı tümüyle bir `degismez` parçasında değilse
  türetme yapılmaz (`tutarsiz_kalan_deger`): eski değer türetilen case'te yanlış kalırdı.
- **Kalan değer denetimi.** Değişen (yeniden yazılan) her alanda, hiçbir olgunun alıntısıyla ya
  da ilişkinin `degismez` parçalarıyla örtülmeyen bir sayı varsa türetme yapılmaz
  (`tutarsiz_kalan_deger`): ör. 7 → 14 adette "ara toplam 175,00 TL" kaynaktaki değerde kalırdı.
  Sonuç kodu `TUTARSIZ_KALAN_DEGER` değer kümesinde (`enums.TURETME_SONUC`) yoksa `belirsiz_alinti`
  yazılır ve `neden` `tutarsiz_kalan_deger:` ile başlar.
- Aynı kolon için farklı değerli iki olgu → `belirsiz_alinti` (hangisinin dönüştürüleceği belli
  değil).
- `iliski_uygula`: eksik ad, ifade hatası ya da sağlanmayan `on_kosul` → `iliski_gecersiz`.
- Grubun her çıktı olgusunun kolonu ilişkinin `iliski` bölümünde olmalı; olmayan varsa
  `iliski_gecersiz` (yeni beklenen değeri belirsiz kalacak bir case yazılmaz).
- Değeri değişmeyen olgunun alıntısına dokunulmaz. Değişen sayı olgusu `bicimle` ile yazılır;
  sayı olmayan (metin / mantıksal) olgunun değeri değişiyorsa `iliski_gecersiz`.
- Alıntı alanda **sınırlı** aranır (önünde/arkasında harf, rakam ya da sayının parçası olabilecek
  ayırıcı yok): `"25"`, `"125"` ya da `"25,00"` içinde bulunmaz. Hiç bulunamazsa, aynı alan +
  alıntı farklı yeni metinlere gidiyorsa ya da farklı alıntıların konumları çakışıyorsa
  `belirsiz_alinti`. Aynı alıntının bütün geçişleri aynı yeni metinle değiştirilir.
- Değeri değişen bir alıntı, o alıntıya ait olgusu olmayan başka bir alanda da (sınırlı) geçiyorsa
  `belirsiz_alinti`: o kopya eski değerde kalır ve case kendi içinde tutarsızlaşırdı.
- Başlığa ` (ilişki: <ad>)` eklenir; başlık 120 karakteri aşacaksa özgün başlık kısaltılır.
  `tags`'e `metamorfik` eklenir; şemanın istediği `AI-generated` etiketi korunur (case şeması onu
  her case'te ister).
- **Bilinen olgular.** Türetilen case'in beklenen değerleri deterministik olarak bilinir:
  `Sonuc.olgular`, değer çıkarma (`case_facts`) çıktısı biçimindedir (`{groups: [{table_ref,
  inputs, expected}]}`; alıntılar yeni metinler) ve model çağırmadan oracle değerlendirmesine
  (`oracle.dogrulama.degerlendir`) verilebilir.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from tp_core.features.karar_tablosu import ifade
from tp_core.models import enums

ETIKET = "metamorfik"
BASLIK_AZAMI = 120
_ALAN_DESENI = re.compile(
    r"^(?:(?P<kok>title|expected_result)|preconditions\[(?P<on>\d+)\]"
    r"|steps\[(?P<adim>\d+)\]\.(?P<adim_alan>action|data|expected))$"
)
_SAYI_GOVDESI = re.compile(r"\d+(?:([.,])(\d+))?")
# Metindeki bağımsız sayı (kod ya da sözcüğün parçası olmayan): "P-004", "S2", "bayi1" sayı değil.
_SERBEST_SAYI = re.compile(r"(?<![\w.,\-−])\d+(?:[.,]\d+)*(?!\w)")

TUTARSIZ_KALAN_DEGER = "tutarsiz_kalan_deger"


def _tutarsiz(neden: str) -> Sonuc:
    """`tutarsiz_kalan_deger` sonucu; değer kümesinde yoksa `belirsiz_alinti` + önekli neden."""
    if TUTARSIZ_KALAN_DEGER in enums.TURETME_SONUC:
        return Sonuc(TUTARSIZ_KALAN_DEGER, neden)
    return Sonuc("belirsiz_alinti", f"{TUTARSIZ_KALAN_DEGER}: {neden}")


@dataclass(frozen=True)
class Olgu:
    """Doğrulanmış tek olgu: `alan` içinde `alinti` metniyle geçen `column = deger`."""

    column: str
    alan: str
    alinti: str
    deger: Any  # Decimal | str | bool
    cikti: bool


@dataclass(frozen=True)
class Sonuc:
    """Bir grubun türetme sonucu: `sonuc == "turetildi"` ise `icerik` doludur."""

    sonuc: str
    neden: str | None = None
    icerik: dict[str, Any] | None = None
    # Türetilen case'in olguları (`case_facts` çıktı biçimi); yalnız `turetildi`'de dolu.
    olgular: dict[str, Any] | None = None


# ---------------------------------------------------------------------- alan yolu


def alan_oku(icerik: Mapping[str, Any], alan: str) -> str | None:
    """Case içindeki yol (`steps[2].expected`, `preconditions[0]`, `title` …) → metin ya da None."""
    m = _ALAN_DESENI.match(alan or "")
    if m is None:
        return None
    try:
        if m["kok"]:
            deger = icerik.get(m["kok"])
        elif m["on"] is not None:
            deger = (icerik.get("preconditions") or [])[int(m["on"])]
        else:
            deger = (icerik.get("steps") or [])[int(m["adim"])].get(m["adim_alan"])
    except (IndexError, AttributeError, TypeError):
        return None
    return deger if isinstance(deger, str) else None


def _metin_alanlari(icerik: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Case'in serbest metin alanları `(yol, metin)`: başlık, ön koşullar, adımlar, sonuç."""
    out: list[tuple[str, str]] = []
    adaylar = ["title", "expected_result"]
    adaylar += [f"preconditions[{i}]" for i in range(len(icerik.get("preconditions") or []))]
    adaylar += [
        f"steps[{i}].{a}"
        for i in range(len(icerik.get("steps") or []))
        for a in ("action", "data", "expected")
    ]
    for alan in adaylar:
        metin = alan_oku(icerik, alan)
        if metin is not None:
            out.append((alan, metin))
    return out


def _alan_yaz(icerik: dict[str, Any], alan: str, metin: str) -> None:
    m = _ALAN_DESENI.match(alan)
    assert m is not None  # alan_oku ile doğrulanmış yollar yazılır
    if m["kok"]:
        icerik[m["kok"]] = metin
    elif m["on"] is not None:
        icerik["preconditions"][int(m["on"])] = metin
    else:
        icerik["steps"][int(m["adim"])][m["adim_alan"]] = metin


# ---------------------------------------------------------------------- sayı biçimi


def bicimle(deger: Decimal, ornek: str) -> str:
    """`ifade.sayi_bicimle`, bir ekle: binliği gösteremeyen örnekte binlik ayırıcıyı tamamlar.

    `"750,00 TL"` gibi 1000'den küçük, ondalıklı bir örnek binlik ayırıcı kullanılıp
    kullanılmadığını gösteremez; dört ve daha fazla haneli tam kısımda ondalık ayırıcının eşleniği
    (virgül → nokta, nokta → virgül) binlik ayırıcı olarak eklenir: `(1500, "750,00 TL")` →
    `"1.500,00 TL"`. Ondalıksız örnekte (`"25"`, `"25 adet"`) binlik eklenmez. Değer hiçbir
    durumda yuvarlanmaz; yazılamazsa `ValueError`.
    """
    sonuc = ifade.sayi_bicimle(deger, ornek)
    m = _SAYI_GOVDESI.search(ornek)
    if m is None or not m[1] or abs(deger) < 1000:
        return sonuc
    tam, ayirici, kesir = m[0].partition(m[1])
    sonra = ornek[m.end() : m.end() + 2]
    if len(sonra) == 2 and sonra[0] in ".," and sonra[1].isdigit():
        return sonuc  # "1.250,00": örnekte zaten binlik var
    if ayirici == "." and len(kesir) == 3 and len(tam) <= 3 and not tam.startswith("0"):
        return sonuc  # "1.250": nokta burada binliktir, örnek ondalıksız
    binlik = "." if ayirici == "," else ","
    sentetik = ornek[: m.start()] + f"1{binlik}000{ayirici}{'0' * len(kesir)}" + ornek[m.end() :]
    try:
        return ifade.sayi_bicimle(deger, sentetik)
    except ValueError:
        return sonuc


# ---------------------------------------------------------------------- olgular


def _olgu_degeri(deger: Any, alinti: str) -> Any:
    """Olgunun değeri alıntıyla doğrulanır; tutmazsa None (olgu atılır).

    Kayıttaki değer biçimleri (oracle `ayrintilar`): sayı düz ondalık metin (`"150.00"`),
    mantıksal JSON bool, metin JSON str. Mantıksal olgu önce ayrılır (alıntısı sayı içerse de —
    `"Minimum 750,00 TL" uyarısı görünür` — sayı sayılmaz); sayıya okunamayan değerli olgu metin
    olarak denenir. Değeri değişmeyen mantıksal/metin olgu türetmeyi engellemez (alıntısına
    dokunulmaz); değişirse `turet` `iliski_gecersiz` verir.
    """
    if isinstance(deger, bool):
        return deger
    sayi = ifade.sayi_ayristir(alinti)
    if sayi is not None:
        try:
            beklenen = ifade.girdi_donustur(deger, "sayi")
        except ifade.IfadeHatasi:
            beklenen = None
        if beklenen is not None:
            return sayi if beklenen == sayi else None
    if isinstance(deger, str) and deger.strip() and deger.strip() in alinti:
        return deger
    return None


def grup_olgulari(icerik: Mapping[str, Any], grup: Mapping[str, Any]) -> list[Olgu]:
    """Grubun yeniden doğrulanmış girdi ve çıktı olguları (sıra korunur).

    Çıktı olguları tabloyla uyumlu `karsilastirmalar[]`'dır. `karsilastirilamayan[]` (tablonun
    eksik girdi yüzünden hesaplayamadığı beklenen değerler) olgu sayılmaz: doğrulanmamış değer
    ilişkiyle dönüştürülmez (`turet` onları `tutarsiz_kalan_deger` için ayrıca denetler)."""
    hamlar: list[tuple[Any, Any, Any, Any, bool]] = [
        (o.get("column"), o.get("field"), o.get("quote"), o.get("value"), False)
        for o in grup.get("girdiler") or []
        if isinstance(o, Mapping)
    ] + [
        (k.get("column"), k.get("alan"), k.get("alinti"), k.get("case_degeri"), True)
        for k in grup.get("karsilastirmalar") or []
        if isinstance(k, Mapping) and k.get("uyumlu", True) is True
    ]
    out: list[Olgu] = []
    for column, alan, alinti, deger, cikti in hamlar:
        if not (isinstance(column, str) and isinstance(alan, str) and isinstance(alinti, str)):
            continue
        if not alinti.strip():
            continue
        metin = alan_oku(icerik, alan)
        if metin is None or alinti not in metin:
            continue
        dogrulanan = _olgu_degeri(deger, alinti)
        if dogrulanan is None:
            continue
        out.append(Olgu(column, alan, alinti, dogrulanan, cikti))
    return out


def _konumlar(metin: str, alinti: str) -> list[tuple[int, int]]:
    """`alinti`'nın `metin`'deki sınırlı geçişleri (sayının ya da sözcüğün parçası olmayan)."""
    desen = re.compile(r"(?<![\w.,\-−+])" + re.escape(alinti) + r"(?!\w)(?![.,]\d)")
    return [(m.start(), m.end()) for m in desen.finditer(metin)]


def _kolon_degerleri(olgular: Sequence[Olgu]) -> tuple[dict[str, Any], str | None]:
    degerler: dict[str, Any] = {}
    for o in olgular:
        if o.column in degerler and degerler[o.column] != o.deger:
            return degerler, f"'{o.column}' için case'te farklı değerli olgular var"
        degerler[o.column] = o.deger
    return degerler, None


def _baslik(baslik: str, ad: str) -> str:
    """Başlık + ` (ilişki: <ad>)`; 120 karakteri aşarsa önce başlık (en az 20 karakter kalır),
    sonra ilişki adı `…` ile kısaltılır."""
    ek = f" (ilişki: {ad})"
    if len(baslik) + len(ek) <= BASLIK_AZAMI:
        return baslik + ek
    pay = max(20, BASLIK_AZAMI - len(ek))
    if len(baslik) > pay:
        baslik = baslik[: pay - 1].rstrip() + "…"
    kalan = BASLIK_AZAMI - len(baslik)
    if len(ek) > kalan:
        ek = ek[: kalan - 2] + "…)"
    return baslik + ek


def _degismez_parcalar(iliski: Mapping[str, Any]) -> list[str]:
    return [p for p in iliski.get("degismez") or [] if isinstance(p, str) and p.strip()]


def _parca_konumlari(metin: str, parcalar: Sequence[str]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for p in parcalar:
        bas = metin.find(p)
        while bas >= 0:
            out.append((bas, bas + len(p)))
            bas = metin.find(p, bas + 1)
    return out


def _ortulmeyen_sayilar(metin: str, ortu: Sequence[tuple[int, int]]) -> list[str]:
    """`metin`'deki, hiçbir `ortu` aralığının içinde kalmayan bağımsız sayılar."""
    return [
        m[0]
        for m in _SERBEST_SAYI.finditer(metin)
        if not any(b <= m.start() and m.end() <= s for b, s in ortu)
    ]


def _karsilastirilamayan_engeli(
    icerik: Mapping[str, Any], grup: Mapping[str, Any], degismez: Sequence[str]
) -> str | None:
    for o in grup.get("karsilastirilamayan") or []:
        if not isinstance(o, Mapping):
            continue
        alan, alinti = o.get("field"), o.get("quote")
        metin = alan_oku(icerik, alan) if isinstance(alan, str) else None
        if metin is None or not isinstance(alinti, str) or not alinti.strip():
            continue
        konumlar = _konumlar(metin, alinti) or (
            [(metin.find(alinti), metin.find(alinti) + len(alinti))] if alinti in metin else []
        )
        parcalar = _parca_konumlari(metin, degismez)
        if konumlar and all(any(b <= x and y <= s for b, s in parcalar) for x, y in konumlar):
            continue
        return (
            f"'{o.get('column')}' değeri ({alinti}, {alan}) tabloyla karşılaştırılamadı; "
            "doğrulanmamış değer ilişkiyle dönüştürülmez ve eski hâliyle türetilen case'te yanlış "
            "kalır"
        )
    return None


def turet(icerik: Mapping[str, Any], grup: Mapping[str, Any], iliski: Mapping[str, Any]) -> Sonuc:
    """Bir oracle grubunun olgularıyla ilişkiyi uygular ve case'i deterministik yeniden yazar."""
    durum = grup.get("durum")
    if durum is not None and durum != "uyumlu":
        return Sonuc("olgu_yok", f"Grup tabloyla uyumlu değil (durum: {durum})")
    olgular = grup_olgulari(icerik, grup)
    girdi_olgulari = [o for o in olgular if not o.cikti]
    if not girdi_olgulari:
        return Sonuc("olgu_yok", "Grupta doğrulanmış girdi olgusu yok")
    girdiler, cakisma = _kolon_degerleri(girdi_olgulari)
    ciktilar, cakisma2 = _kolon_degerleri([o for o in olgular if o.cikti])
    if cakisma or cakisma2:
        return Sonuc("belirsiz_alinti", cakisma or cakisma2)
    degismez = _degismez_parcalar(iliski)
    engel = _karsilastirilamayan_engeli(icerik, grup, degismez)
    if engel is not None:
        return _tutarsiz(engel)

    uygulama = ifade.iliski_uygula(iliski, girdiler, ciktilar)
    if uygulama.eksik:
        return Sonuc(
            "iliski_gecersiz", "Case'te doğrulanmış değeri olmayan ad: " + ", ".join(uygulama.eksik)
        )
    if uygulama.hata:
        return Sonuc("iliski_gecersiz", f"İlişki uygulanamadı: {uygulama.hata}")
    if not uygulama.gecerli:
        return Sonuc("iliski_gecersiz", f"Ön koşul sağlanmadı: {iliski.get('on_kosul')}")
    belirsiz_cikti = sorted({o.column for o in olgular if o.cikti} - set(uygulama.ciktilar))
    if belirsiz_cikti:
        return Sonuc(
            "iliski_gecersiz",
            "İlişki şu beklenen değerleri belirlemiyor: " + ", ".join(belirsiz_cikti),
        )

    # (alan, alıntı) → yeni metin
    yeni: dict[tuple[str, str], str] = {}
    for o in olgular:
        hedef = uygulama.ciktilar[o.column] if o.cikti else uygulama.girdiler[o.column]
        if hedef == o.deger and type(hedef) is type(o.deger):
            metin = o.alinti
        elif isinstance(hedef, Decimal) and isinstance(o.deger, Decimal):
            try:
                metin = bicimle(hedef, o.alinti)
            except ValueError as h:
                return Sonuc("iliski_gecersiz", f"'{o.column}' yeni değeri yazılamadı: {h}")
        else:
            return Sonuc(
                "iliski_gecersiz", f"'{o.column}' sayı değil; ilişki değerini değiştiremez"
            )
        anahtar = (o.alan, o.alinti)
        if anahtar in yeni and yeni[anahtar] != metin:
            return Sonuc(
                "belirsiz_alinti",
                f"'{o.alinti}' alıntısı {o.alan} alanında farklı yeni değerlere ait olgularda",
            )
        yeni[anahtar] = metin

    # Değişen alanda olgusu ve `degismez` parçası olmayan sayı eski değerde kalırdı (ör. 14 adette
    # "ara toplam 175,00 TL"): tutarsız case yazılmaz.
    for alan in sorted({a for (a, alinti), m in yeni.items() if m != alinti}):
        metin = alan_oku(icerik, alan)
        assert metin is not None
        if any(not _konumlar(metin, a) for (al, a) in yeni if al == alan):
            continue  # alıntı ayrı değer olarak yok: aşağıda `belirsiz_alinti`
        ortu = [k for o in olgular if o.alan == alan for k in _konumlar(metin, o.alinti)]
        ortu += _parca_konumlari(metin, degismez)
        kalan = _ortulmeyen_sayilar(metin, ortu)
        if kalan:
            return _tutarsiz(
                f"{alan} alanında ilişkinin belirlemediği değer var ({', '.join(kalan)}); "
                "dönüşümden sonra eski hâliyle yanlış kalırdı. Değer tablo kolonu değilse "
                "ilişkinin 'degismez' listesine yazın"
            )

    # Değişen bir alıntı, olgusu olmayan bir alanda da geçiyorsa o kopya eski değerde kalırdı
    # (ör. veri "50" ama beklenen "25 adet görünür"): tutarsız case yazılmaz.
    degisen = {alinti for (_, alinti), m in yeni.items() if m != alinti}
    for alan, metin in _metin_alanlari(icerik):
        for alinti in sorted(degisen):
            if (alan, alinti) not in yeni and _konumlar(metin, alinti):
                return Sonuc(
                    "belirsiz_alinti",
                    f"Değişen '{alinti}' alıntısı {alan} alanında doğrulanmış olgu olmadan da "
                    "geçiyor; o kopya güvenle güncellenemez",
                )

    sonuc = copy.deepcopy(dict(icerik))
    alanlar = sorted({alan for alan, _ in yeni})
    for alan in alanlar:
        metin = alan_oku(sonuc, alan)
        assert metin is not None
        degisimler: list[tuple[int, int, str, str]] = []
        for (a, alinti), yeni_metin in yeni.items():
            if a != alan:
                continue
            konumlar = _konumlar(metin, alinti)
            if not konumlar:
                return Sonuc(
                    "belirsiz_alinti",
                    f"'{alinti}' alıntısı {alan} alanında ayrı bir değer olarak bulunamadı",
                )
            degisimler.extend((b, s, alinti, yeni_metin) for b, s in konumlar)
        degisimler.sort()
        for i, x in enumerate(degisimler):
            for y in degisimler[i + 1 :]:
                if y[0] >= x[1]:
                    break  # başlangıca göre sıralı: sonrakiler de çakışmaz
                if x[2] != x[3] or y[2] != y[3]:
                    return Sonuc(
                        "belirsiz_alinti",
                        f"'{x[2]}' ve '{y[2]}' alıntıları {alan} alanında çakışıyor",
                    )
        for bas, son, alinti, yeni_metin in reversed(degisimler):
            if alinti != yeni_metin:
                metin = metin[:bas] + yeni_metin + metin[son:]
        _alan_yaz(sonuc, alan, metin)

    sonuc["title"] = _baslik(str(sonuc.get("title") or ""), str(iliski.get("ad") or ""))
    etiketler = [t for t in sonuc.get("tags") or [] if isinstance(t, str)]
    if ETIKET not in etiketler:
        etiketler.append(ETIKET)
    sonuc["tags"] = etiketler
    return Sonuc(
        "turetildi", icerik=sonuc, olgular=_turetilen_olgular(grup, olgular, yeni, uygulama)
    )


def _gosterim(deger: Any) -> Any:
    return str(deger) if isinstance(deger, Decimal) else deger


def _turetilen_olgular(
    grup: Mapping[str, Any],
    olgular: Sequence[Olgu],
    yeni: Mapping[tuple[str, str], str],
    uygulama: ifade.IliskiSonucu,
) -> dict[str, Any]:
    """Türetilen case'in olguları, değer çıkarma (`case_facts`) çıktı biçiminde.

    Değerler ilişkinin hesapladığı yeni değerler, alıntılar yeniden yazılmış metinlerdir; alan
    yolları aynı kalır (başlığa yalnız ek yapılır). `table_ref` grubun `tablo_id`'sidir (oracle
    tabloyu kimliğiyle de bulur)."""
    inputs: list[dict[str, Any]] = []
    expected: list[dict[str, Any]] = []
    for o in olgular:
        deger = uygulama.ciktilar[o.column] if o.cikti else uygulama.girdiler[o.column]
        kayit = {
            "column": o.column,
            "value": _gosterim(deger),
            "field": o.alan,
            "quote": yeni[(o.alan, o.alinti)],
        }
        (expected if o.cikti else inputs).append(kayit)
    return {
        "groups": [
            {"table_ref": str(grup.get("tablo_id") or ""), "inputs": inputs, "expected": expected}
        ]
    }


def turetilen_olgular(
    icerik: Mapping[str, Any], grup: Mapping[str, Any], iliski: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Kaynak case + uyumlu oracle grubu + ilişki → türetilen case'in olguları (`case_facts`
    çıktısı biçimi) ya da türetme yapılamıyorsa None. Model çağrısı yoktur."""
    return turet(icerik, grup, iliski).olgular


__all__ = [
    "ETIKET",
    "TUTARSIZ_KALAN_DEGER",
    "Olgu",
    "Sonuc",
    "alan_oku",
    "bicimle",
    "grup_olgulari",
    "turet",
    "turetilen_olgular",
]
