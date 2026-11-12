"""Gherkin dışa aktarımı (specs/011 F8, K14) — deterministik; model çağrısı yok.

Gereksinimin onaylı (`approved` / `published`) ve hazır (`readiness_of == ready`; eski v2 case de
hazırdır, K9) güncel case'lerinden Türkçe Gherkin (`# language: tr`) üretir. Aynı girdi her zaman
aynı baytları verir (zaman damgası yok, sıra = üretim no + sıra no).

Dönüşüm kuralları (docs/TEKNIK-TASARIM.md §8.3 "Gherkin dışa aktarımı"):

- `Özellik:` gereksinim anahtarı + başlık; kabul kriterleri özelliğin altına yorum olarak yazılır.
- Case başına `Senaryo:` (başlık). Ön koşullar `Diyelim ki` / `Ve`; test verisi `test verileri:`
  adımına bağlı tablo (`| ad | değer | sınıf |`). Her adım `Eğer ki <eylem>` + `O zaman <beklenen>`
  (adım–beklenen eşlemesi korunur: otomasyonda her ara beklenen bir doğrulamadır; art arda aynı
  türde adım — ör. beklenensiz adımın ardından gelen eylem — `Ve` olur). Case'in genel beklenen
  sonucu son beklenenden farklıysa sona `Ve` olarak eklenir.
- Adım verisi test verisi tablosundaki bir değerle birebir aynıysa değer yinelenmez, satırın
  sonuna `(test verisi: <ad>)` yazılır (saldırı verisi de böylece yalnız tabloda kalır). Değilse,
  tek satır ve tırnaksızsa `(veri: "<değer>")` eklenir; çok satırlı, tırnaklı ya da uzun veri
  `, veri:` + docstring (`\"\"\"`) olur.

Doğal adım dili (`dogal_metin`, `kosul_kipi`; yalnız ön koşul, eylem ve beklenen metinlerine
uygulanır, başlık/tablo/etiket değişmez):

- Anahtar kelimeden sonra büyük harf kayması yok: metnin ilk kelimesi yalnız harflerden oluşan,
  baş harfi büyük gerisi küçük bir kelimeyse ve ardından büyük harfle başlayan bir kelime
  gelmiyorsa (özel ad olasılığı: "Portakal Gazozu", "Merkez Bayi") baş harf Türkçe kurala göre
  küçülür ("Sepet boş" → "sepet boş", "I" → "ı", "İ" → "i"). Kod/ürün kimliği, tırnak, rakam ya
  da kısaltmayla başlayan metin olduğu gibi kalır.
- `Eğer ki` adımında eylemin emir kipindeki son fiili koşul kipine çevrilir ("Giriş sayfasını
  aç" → "giriş sayfasını açarsa", "butonuna bas" → "butonuna basarsa", "sepete git" → "sepete
  giderse", "kaydet" → "kaydederse"). Fiil, tek heceli fiil sözlüğünden (`TEK_HECELI_FIILLER`,
  geniş zaman -ar/-er; `GENIS_ZAMAN_IR` istisnaları -ır/-ir/-ur/-ür) ya da çok heceli fiil
  ekinden (-la/-le; araç eki -yla/-yle ve `_FIIL_OLMAYAN` hariç) ya da sözlükten
  (`COK_HECELI_FIILLER`) tanınır; geniş zaman + -sa/-se
  ünlü uyumuyla eklenir. Edilgen geniş zamanla biten eylem ("… açılır") yalnız -sa/-se alır.
  Tanınmayan son kelimede metin değişmez (yanlış çekim yerine olduğu gibi bırakılır).
- Senaryo taslağında bu dönüşümler yer tutuculu metne uygulanır; her örnek satırı için
  "taslağın açılmış hâli = case'in tek başına dönüşümü" denetlenir, tutmazsa case'ler ayrı senaryo
  kalır (kayıpsızlık korunur).
- Temizlik (`teardown`) senaryonun sonunda `# Temizlik:` yorumudur: Gherkin'de "after" adımı
  yoktur; `Ve` adımı olarak yazılsa önceki `O zaman`'a bağlanır ve doğrulama gibi okunurdu.
  Otomasyonda temizlik kancası (hook) bu yorumdan yazılır.
- Etiketler: `@AC2 @BVA @EP @P1 @sınır-değer @tp-<case uuid>` (AC, teknik, öncelik, tür, case).
- Saldırı verisi (`is_attack_payload`) yalnız test verisi tablosunda, kaçışlı hücrede ve önünde
  `# güvenlik testi girdisi` yorumuyla yer alır (kural 6: başka alanda geçmez).

Senaryo taslağı birleştirmesi (`_taslak`): aynı AC kümesi, aynı birincil teknik (`technique[0]`),
aynı tür, öncelik, doğrulama noktası, test seviyesi, platform, ön koşullar, temizlik, adım
kimlikleri (ve verinin olup olmaması) ve aynı test verisi adları olan v3 case'ler aday gruptur.
Grup yalnız şu koşullarla `Senaryo taslağı:` + `Örnekler:` olur; biri tutmazsa case'ler ayrı
senaryo kalır (birleştirme anlam kaybettirmez):

1. Eylem metinleri yalnız küçük bir kelime aralığında (≤ 3 kelime) farklıdır, sabit kısım kalır.
2. Değişen girdi değeri en az birdir ve satırlar girdide birbirinden farklıdır (aynı girdili
   tekrar case taslakta saklanmaz, ayrı senaryo olarak görünür kalır).
3. Değişen alanlar en çok 2 girdi, 2 sınıf, 1 beklenen ve 3 ara beklenen sütunu açar.
4. Çok satırlı veri yoktur ve hiçbir metin taslak yer tutucusu (`<girdi>` vb.) içermez.

Örnekler tablosu belgedeki kolonlarla başlar: `| teknik | bölüm_id | girdi | beklenen |`; gerekirse
`girdi_2`, `sınıf`, `ara_beklenen…` eklenir. Değişen kelime aralığı bir girdi sütunuyla aynıysa
(ör. "adedi 6" ↔ "Sepet sayacı 6 olur") beklenen metninde de aynı yer tutucu kullanılır. Her case
kendi `Örnekler:` bloğundadır (adı case başlığı, etiketi `@tp-<uuid>`): böylece her örnek satırı
case'ine ve Jira/Xray kaydına geri bağlanabilir.

Kaçış: tablo hücresinde `\\` → `\\\\`, `|` → `\\|`, satır sonu → `\\n`; docstring'de `\"\"\"` →
`\\"\\"\\"`; tek satırlık alanlarda (başlık, adım, yorum) satır sonları boşluğa indirgenir; etiket
içindeki boşluk, `#` ve `@` `-` olur. Satır başı `#` yalnız yorum/tablo dışı satırlarda anlamlıdır;
üretilen her satır anahtar kelime, `|`, `@`, `#` ya da docstring ayırıcısıyla başladığından metin
içeriği satır başına düşmez.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.features.cases import service
from tp_core.features.cases.schema import READY, acceptance_criteria, is_legacy, readiness_of
from tp_core.integrations.testmgmt import CASE_TYPE_TR, TECHNIQUE_TR
from tp_core.models import TestCase
from tp_core.workflow.service import WorkflowError, approved_hash_matches

ONAYLI = ("approved", "published")
YAYINLANMIS = ("published",)
GIRINTI = "  "
# Adım verisi bu uzunluğu aşarsa satır içinde değil docstring olarak yazılır.
SATIR_ICI_VERI_SINIRI = 80
# Taslak birleştirme sınırları (bkz. modül açıklaması).
EYLEM_FARK_SINIRI = 3
SUTUN_SINIRI = {"girdi": 2, "sınıf": 2, "beklenen": 1, "ara_beklenen": 3}
SUTUN_SIRASI = ("girdi", "sınıf", "beklenen", "ara_beklenen")
GUVENLIK_YORUMU = "# güvenlik testi girdisi"
BOS_NEDEN = (
    "Gherkin'e aktarılacak case yok: yalnız onaylı (ya da yayınlanmış) ve hazır olan güncel "
    "case'ler dahil edilir."
)


class GherkinCaseYok(WorkflowError):
    """Dahil edilecek case yok (404): boş bir `.feature` dosyası indirilmez."""

    status_code = 404
    kod = "bulunamadi"  # asistan hata sözlüğündeki genel kayıt (yeni kod sözlüğü bayatlatır)


@dataclass(frozen=True)
class GherkinCase:
    id: str
    icerik: Mapping[str, Any]


@dataclass(frozen=True)
class GherkinCikti:
    dosya_adi: str
    metin: str
    case_sayisi: int
    senaryo_sayisi: int
    taslak_sayisi: int


# --------------------------------------------------------------------------- dahil etme


def uygun_mu(
    durum: str, icerik: Mapping[str, Any] | None, *, yalniz_yayinlanan: bool = False
) -> bool:
    """Case Gherkin'e girer mi: onaylı/yayınlanmış ve hazır (eski v2 case hazır sayılır)."""
    durumlar = YAYINLANMIS if yalniz_yayinlanan else ONAYLI
    return durum in durumlar and readiness_of(icerik) == READY


def eligible_cases(
    session: Session, requirement_id: uuid.UUID, *, yalniz_yayinlanan: bool = False
) -> list[TestCase]:
    """Gereksinimin Gherkin'e girecek güncel case'leri (üretim no, sıra no düzeninde).

    Güncel: önceki (PO onayı yenilenmiş) içeriğe ait değil; `approved` case'in onaylanan hash'i
    güncel içerikle aynı (yayın kapısıyla aynı denetim). Gereksinim PO onayının dışındaysa
    (story değişti) case'ler kullanılamaz: 409.
    """
    req = service.get_requirement(session, requirement_id)
    neden = service.requirement_change_reason(req)
    if neden is not None:
        raise service.RequirementChanged(neden)
    eski = service.old_content_case_ids(session, req)
    durumlar = YAYINLANMIS if yalniz_yayinlanan else ONAYLI
    cases = session.scalars(
        select(TestCase)
        .where(TestCase.requirement_id == requirement_id, TestCase.durum.in_(durumlar))
        .order_by(TestCase.uretim_no, TestCase.sira_no, TestCase.id)
    ).all()
    return [
        tc
        for tc in cases
        if tc.id not in eski
        and uygun_mu(tc.durum, tc.icerik, yalniz_yayinlanan=yalniz_yayinlanan)
        and (tc.durum != "approved" or approved_hash_matches(session, tc))
    ]


def requirement_feature(
    session: Session, requirement_id: uuid.UUID, *, yalniz_yayinlanan: bool = False
) -> GherkinCikti:
    """`GET /requirements/{id}/cases.feature` gövdesi. Uygun case yoksa `GherkinCaseYok` (404)."""
    req = service.get_requirement(session, requirement_id)
    cases = eligible_cases(session, requirement_id, yalniz_yayinlanan=yalniz_yayinlanan)
    if not cases:
        raise GherkinCaseYok(BOS_NEDEN + (" Yayınlanmış case yok." if yalniz_yayinlanan else ""))
    anahtar = service.requirement_key(req)
    girdiler = [GherkinCase(str(tc.id), tc.icerik) for tc in cases]
    senaryolar = plan_scenarios(girdiler)
    metin = render_feature(anahtar, req.baslik, girdiler, req.kabul_kriterleri, plan=senaryolar)
    return GherkinCikti(
        dosya_adi=feature_filename(anahtar),
        metin=metin,
        case_sayisi=len(girdiler),
        senaryo_sayisi=len(senaryolar),
        taslak_sayisi=sum(1 for s in senaryolar if isinstance(s, _Taslak)),
    )


def feature_filename(anahtar: str) -> str:
    """`TPD-1.feature`; anahtar dışı karakterler `_` olur (Content-Disposition güvenliği)."""
    return (re.sub(r"[^A-Za-z0-9._-]", "_", anahtar) or "gereksinim") + ".feature"


# --------------------------------------------------------------------------- kaçış


def tek_satir(metin: Any) -> str:
    """Tek satırlık alan: tüm boşluk/satır sonu dizileri tek boşluk olur."""
    return " ".join(str(metin if metin is not None else "").split())


def tablo_hucresi(deger: Any) -> str:
    """Gherkin tablo hücresi kaçışı: `\\` → `\\\\`, `|` → `\\|`, satır sonu → `\\n`."""
    metin = str(deger if deger is not None else "")
    metin = metin.replace("\r\n", "\n").replace("\r", "\n")
    return metin.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "\\n")


def etiket(deger: Any) -> str:
    """Etiket gövdesi: boşluk, `#`, `@` ve `,` `-` olur (etiket satırında `#` yorum başlatır)."""
    return re.sub(r"[\s#@,]+", "-", str(deger).strip()).strip("-")


def _docstring(metin: str, girinti: str) -> list[str]:
    govde = str(metin).replace("\r\n", "\n").replace("\r", "\n").replace('"""', '\\"\\"\\"')
    return [
        f'{girinti}"""',
        *(f"{girinti}{s}" if s else "" for s in govde.split("\n")),
        f'{girinti}"""',
    ]


def _satir_ici_mi(veri: str) -> bool:
    return (
        "\n" not in veri
        and "\r" not in veri
        and '"' not in veri
        and len(veri) <= SATIR_ICI_VERI_SINIRI
    )


def _tablo(
    satirlar: Sequence[Sequence[str]], girinti: str, yorumlar: Mapping[int, str] | None = None
) -> list[str]:
    """Hücreleri kaçışlı, sütunları hizalı tablo; `yorumlar[i]` i. satırın önüne yazılır."""
    hucreler = [[tablo_hucresi(h) for h in s] for s in satirlar]
    genislik = [max(len(s[i]) for s in hucreler) for i in range(len(hucreler[0]))]
    out: list[str] = []
    for i, s in enumerate(hucreler):
        if yorumlar and i in yorumlar:
            out.append(f"{girinti}{yorumlar[i]}")
        out.append(
            girinti + "| " + " | ".join(h.ljust(genislik[j]) for j, h in enumerate(s)) + " |"
        )
    return out


# --------------------------------------------------------------------------- doğal adım dili

_HARF = "A-Za-zÇĞİÖŞÜÂÎÛçğıöşüâîû"
_KELIME = re.compile(rf"^[{_HARF}]+$")
_KUCUK_KELIME = re.compile(r"^[a-zçğıöşüâîû]+$")
_INCE = set("eiöü")
_KALIN = set("aıou")
_UNLU = _INCE | _KALIN | set("âîû")
# Tek heceli fiiller (emir kipi). Geniş zaman -ar/-er alır; `GENIS_ZAMAN_IR` istisnadır.
TEK_HECELI_FIILLER = frozenset(
    {
        "aç", "al", "an", "as", "at", "bak", "bas", "bil", "bin", "boz", "bul", "çal", "çek",
        "çık", "çiz", "dök", "dur", "et", "geç", "gel", "gir", "git", "gör", "it", "kal", "kap",
        "kes", "kır", "koş", "koy", "ol", "sar", "seç", "sık", "sil", "sor", "sür", "tak", "tut",
        "var", "ver", "vur", "yak", "yap", "yaz", "yık", "yüz",
    }
)  # fmt: skip
GENIS_ZAMAN_IR = frozenset(
    {"al", "bil", "bul", "dur", "gel", "gör", "kal", "ol", "san", "var", "ver", "vur", "öl"}
)
# Ek ailesiyle tanınmayan çok heceli fiiller (emir kipi).
COK_HECELI_FIILLER = frozenset(
    {
        "ara", "aktar", "artır", "azalt", "başlat", "bekle", "bırak", "bitir", "boşalt",
        "çalıştır", "çevir", "daralt", "değiştir", "dene", "doldur", "durdur", "düzelt",
        "genişlet", "gerçekleştir", "getir", "göster", "götür", "gönder", "indir", "kaldır",
        "kapat", "kaydet", "kaydır", "oku", "öde", "seyret", "uzat", "yerleştir", "yükselt",
    }
)  # fmt: skip
# -la/-le ile biten ama fiil olmayan sık kelimeler (araç eki -(y)la/-(y)le ayrıca elenir).
_FIIL_OLMAYAN = frozenset(
    {"bile", "hala", "hâlâ", "ile", "kola", "lale", "kale", "parola", "cümle"}
)
# Yumuşayan gövdeler: git → gider, et → eder (kaydet → kaydeder).
_YUMUSAMA = {"git": "gid", "et": "ed", "kaydet": "kayded", "seyret": "seyred"}
_FIIL_EKI = re.compile(r"(?<!y)l[ae]$")
_EDILGEN_GENIS = re.compile(r"(?:[ln][ıiuü]r|[ln][ae]n[ıi]r)$")


def _son_unlu(kelime: str) -> str:
    for h in reversed(kelime):
        if h in _UNLU:
            return h
    return "e"


def _dortlu(kelime: str) -> str:
    """Dört yönlü ünlü uyumu (ı/i/u/ü)."""
    u = _son_unlu(kelime)
    return {"a": "ı", "ı": "ı", "o": "u", "u": "u", "e": "i", "i": "i", "ö": "ü", "ü": "ü"}.get(
        u, "i"
    )


def _sart_eki(kelime: str) -> str:
    return "se" if _son_unlu(kelime) in _INCE or _son_unlu(kelime) == "î" else "sa"


def _hece_sayisi(kelime: str) -> int:
    return sum(1 for h in kelime if h in _UNLU)


def _genis_zaman(fiil: str) -> str | None:
    """Emir kipindeki fiilin geniş zaman (3. tekil) biçimi; fiil tanınmazsa None."""
    govde = _YUMUSAMA.get(fiil, fiil)
    if govde.endswith("ed") and fiil.endswith("et"):
        return govde + "er"  # et-bileşikleri tek heceli "et" gibi çekilir: kaydet → kaydeder
    if _hece_sayisi(fiil) == 1:
        if fiil not in TEK_HECELI_FIILLER and fiil not in GENIS_ZAMAN_IR:
            return None
        if fiil in GENIS_ZAMAN_IR:
            return govde + _dortlu(govde) + "r"
        return govde + ("e" if _son_unlu(govde) in _INCE else "a") + "r"
    if fiil not in COK_HECELI_FIILLER and (not _FIIL_EKI.search(fiil) or fiil in _FIIL_OLMAYAN):
        return None
    if govde[-1] in _UNLU:
        return govde + "r"
    return govde + _dortlu(govde) + "r"


def kosul_kipi(eylem: str) -> str:
    """Eylemin son kelimesi emir kipinde fiilse koşul kipine çevrilir ("aç" → "açarsa");
    edilgen geniş zamanla bitiyorsa -sa/-se eklenir; tanınmazsa metin olduğu gibi döner."""
    govde, _, son = eylem.rpartition(" ")
    if not _KUCUK_KELIME.match(son):
        return eylem
    if _hece_sayisi(son) >= 2 and _EDILGEN_GENIS.search(son) and son not in COK_HECELI_FIILLER:
        cekim: str | None = son
    else:
        cekim = _genis_zaman(son)
    if cekim is None:
        return eylem
    yeni = cekim + _sart_eki(cekim)
    return f"{govde} {yeni}" if govde else yeni


def _kucuk(harf: str) -> str:
    return {"I": "ı", "İ": "i"}.get(harf, harf.lower())


def dogal_metin(metin: str) -> str:
    """Anahtar kelimeden sonra gelen metnin baş harfi (özel ad değilse) küçük harf olur."""
    kelimeler = metin.split(" ")
    ilk = kelimeler[0]
    if not ilk or not _KELIME.match(ilk) or len(ilk) < 2:
        return metin
    if not (ilk[0].isupper() and ilk[1:] == "".join(_kucuk(h) for h in ilk[1:])):
        return metin
    if len(kelimeler) > 1 and kelimeler[1][:1].isupper():
        return metin
    return _kucuk(ilk[0]) + metin[1:]


def _eylem_metni(eylem: str) -> str:
    return kosul_kipi(dogal_metin(tek_satir(eylem)))


# --------------------------------------------------------------------------- etiketler


def _ac_refs(icerik: Mapping[str, Any]) -> list[str]:
    return [
        re.sub(r"\s+", "", str(r)).upper() for r in icerik.get("acceptance_criteria_refs") or []
    ]


def _tur_etiketi(icerik: Mapping[str, Any]) -> str | None:
    tur = icerik.get("type")
    return etiket(CASE_TYPE_TR.get(str(tur), str(tur))) if tur else None


def _etiketler(
    ac: Iterable[str], teknikler: Iterable[str], oncelik: Any, tur: str | None, case_id: str | None
) -> str:
    parcalar = [*ac, *teknikler]
    if oncelik:
        parcalar.append(str(oncelik))
    if tur:
        parcalar.append(tur)
    if case_id:
        parcalar.append(f"tp-{case_id}")
    gorulen: list[str] = []
    for p in (etiket(x) for x in parcalar):
        if p and p not in gorulen:
            gorulen.append(p)
    return " ".join("@" + p for p in gorulen)


# --------------------------------------------------------------------------- adımlar


class _Adimlar:
    """Anahtar kelime seçimi: art arda aynı türdeki adım `Ve` olur."""

    ANAHTAR: ClassVar[dict[str, str]] = {
        "given": "Diyelim ki",
        "when": "Eğer ki",
        "then": "O zaman",
    }

    def __init__(self, girinti: str) -> None:
        self.girinti = girinti
        self.onceki: str | None = None
        self.satirlar: list[str] = []

    def ekle(self, tur: str, metin: str) -> None:
        kelime = "Ve" if self.onceki == tur else self.ANAHTAR[tur]
        self.onceki = tur
        self.satirlar.append(f"{self.girinti}{kelime} {metin}")

    def ham(self, satirlar: Iterable[str]) -> None:
        self.satirlar.extend(satirlar)


def _test_verisi_tablosu(
    veriler: Sequence[Mapping[str, Any]],
    degerler: Sequence[str],
    siniflar: Sequence[str],
    girinti: str,
) -> list[str]:
    satirlar = [["ad", "değer", "sınıf"]]
    yorumlar: dict[int, str] = {}
    for i, v in enumerate(veriler):
        satirlar.append([tek_satir(v.get("name")), degerler[i], siniflar[i]])
        if v.get("is_attack_payload"):
            yorumlar[i + 1] = GUVENLIK_YORUMU
    return _tablo(satirlar, girinti, yorumlar)


def _govde(
    icerik: Mapping[str, Any],
    girinti: str,
    *,
    eylemler: Sequence[str],
    veriler: Sequence[str | None],
    beklenenler: Sequence[str],
    sonuc: str,
    td_degerleri: Sequence[str],
    td_siniflari: Sequence[str],
) -> list[str]:
    """Senaryo gövdesi. Metinler çağırandan gelir (taslakta yer tutuculu biçim)."""
    a = _Adimlar(girinti)
    for on in icerik.get("preconditions") or []:
        if tek_satir(on):
            a.ekle("given", dogal_metin(tek_satir(on)))
    td = [v for v in icerik.get("test_data") or [] if isinstance(v, Mapping)]
    if td:
        a.ekle("given", "test verileri:")
        a.ham(_test_verisi_tablosu(td, td_degerleri, td_siniflari, girinti + GIRINTI))
    son_beklenen = ""
    for eylem, veri, beklenen in zip(eylemler, veriler, beklenenler, strict=True):
        metin = _eylem_metni(eylem)
        td_adi = _test_verisi_adi(veri, td, td_degerleri)
        if veri is None or veri == "":
            a.ekle("when", metin)
        elif td_adi is not None:
            a.ekle("when", f"{metin} (test verisi: {td_adi})")
        elif _satir_ici_mi(veri):
            a.ekle("when", f'{metin} (veri: "{veri}")')
        else:
            a.ekle("when", f"{metin}, veri:")
            a.ham(_docstring(veri, girinti + GIRINTI))
        if tek_satir(beklenen):
            a.ekle("then", dogal_metin(tek_satir(beklenen)))
            son_beklenen = tek_satir(beklenen)
    if tek_satir(sonuc) and tek_satir(sonuc) != son_beklenen:
        a.ekle("then", dogal_metin(tek_satir(sonuc)))
    for t in icerik.get("teardown") or []:
        if tek_satir(t):
            a.ham([f"{girinti}# Temizlik: {tek_satir(t)}"])
    return a.satirlar


def _test_verisi_adi(
    veri: str | None, td: Sequence[Mapping[str, Any]], degerler: Sequence[str]
) -> str | None:
    """Adım verisi test verisi tablosundaki bir değerle birebir aynıysa o satırın adı."""
    if not veri:
        return None
    for v, deger in zip(td, degerler, strict=True):
        ad = tek_satir(v.get("name"))
        if ad and deger == veri:
            return ad
    return None


def _adim_alanlari(icerik: Mapping[str, Any]) -> tuple[list[str], list[str | None], list[str]]:
    adimlar = [s for s in icerik.get("steps") or [] if isinstance(s, Mapping)]
    veriler: list[str | None] = []
    for s in adimlar:
        d = s.get("data")
        veriler.append(None if d is None or str(d) == "" else str(d))
    return (
        [str(s.get("action") or "") for s in adimlar],
        veriler,
        [str(s.get("expected") or "") for s in adimlar],
    )


def _td_alanlari(icerik: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    td = [v for v in icerik.get("test_data") or [] if isinstance(v, Mapping)]
    return [str(v.get("value") or "") for v in td], [str(v.get("class") or "") for v in td]


# --------------------------------------------------------------------------- senaryo planı


@dataclass(frozen=True)
class _Tekil:
    case: GherkinCase


@dataclass
class _Taslak:
    cases: list[GherkinCase]
    # Sütun adı → satır değerleri (satır = case sırası); sıra SUTUN_SIRASI'na göre.
    sutunlar: dict[str, list[str]] = field(default_factory=dict)
    eylemler: list[str] = field(default_factory=list)
    veriler: list[str | None] = field(default_factory=list)
    beklenenler: list[str] = field(default_factory=list)
    sonuc: str = ""
    td_degerleri: list[str] = field(default_factory=list)
    td_siniflari: list[str] = field(default_factory=list)


Senaryo = _Tekil | _Taslak

# Taslak sütun adlarıyla çakışan metin (`<girdi>` vb.) yer tutucu sanılırdı.
_YER_TUTUCU = re.compile(r"<(teknik|bölüm_id|girdi|sınıf|beklenen|ara_beklenen)(_\d+)?>")


def _grup_anahtari(icerik: Mapping[str, Any]) -> tuple[Any, ...] | None:
    """Taslak aday grubu anahtarı; eski (v2) ya da tekniksiz case birleştirilmez."""
    teknikler = icerik.get("technique") or []
    if is_legacy(icerik) or not teknikler:
        return None
    adimlar = [s for s in icerik.get("steps") or [] if isinstance(s, Mapping)]
    td = [v for v in icerik.get("test_data") or [] if isinstance(v, Mapping)]
    return (
        tuple(sorted(_ac_refs(icerik))),
        str(teknikler[0]),
        icerik.get("type"),
        icerik.get("priority"),
        icerik.get("verification_point"),
        icerik.get("test_level"),
        icerik.get("platform"),
        tuple(tek_satir(x) for x in icerik.get("preconditions") or []),
        tuple(tek_satir(x) for x in icerik.get("teardown") or []),
        tuple((s.get("id"), s.get("data") in (None, "")) for s in adimlar),
        tuple((tek_satir(v.get("name")), bool(v.get("is_attack_payload"))) for v in td),
    )


def _aralik(metinler: Sequence[str]) -> tuple[list[str], list[str], list[str]]:
    """Kelime düzeyinde ortak önek/sonek ve satır başına değişen aralık."""
    kelimeler = [m.split() for m in metinler]
    en_kisa = min(len(k) for k in kelimeler)
    on = 0
    while on < en_kisa and all(k[on] == kelimeler[0][on] for k in kelimeler):
        on += 1
    son = 0
    while son < en_kisa - on and all(k[-1 - son] == kelimeler[0][-1 - son] for k in kelimeler):
        son += 1
    onek = kelimeler[0][:on]
    sonek = kelimeler[0][len(kelimeler[0]) - son :] if son else []
    araliklar = [" ".join(k[on : len(k) - son]) for k in kelimeler]
    return onek, sonek, araliklar


class _Birlestirilemez(Exception):
    pass


class _Sutunlar:
    def __init__(self) -> None:
        self.degerler: dict[str, tuple[str, ...]] = {}

    def ad(self, rol: str, vektor: Sequence[str]) -> str:
        v = tuple(vektor)
        for ad, mevcut in self.degerler.items():
            if mevcut == v:
                return ad
        n = sum(1 for a in self.degerler if a == rol or a.startswith(rol + "_"))
        if n >= SUTUN_SINIRI[rol]:
            raise _Birlestirilemez(f"{rol} sütun sınırı")
        ad = rol if n == 0 else f"{rol}_{n + 1}"
        self.degerler[ad] = v
        return ad

    def girdi_ile_ayni(self, vektor: Sequence[str]) -> str | None:
        v = tuple(vektor)
        for ad, mevcut in self.degerler.items():
            if (ad == "girdi" or ad.startswith("girdi_")) and mevcut == v:
                return ad
        return None


def _sabit_mi(degerler: Sequence[str]) -> bool:
    return all(d == degerler[0] for d in degerler)


def _girdi_alani(sutunlar: _Sutunlar, degerler: Sequence[str], *, eylem: bool) -> str:
    """Girdi alanı (eylem, adım verisi, test verisi değeri): kelime aralığı yer tutucusu."""
    if _sabit_mi(degerler):
        return degerler[0]
    onek, sonek, araliklar = _aralik(degerler)
    if eylem and (
        not (onek or sonek) or any(len(a.split()) > EYLEM_FARK_SINIRI for a in araliklar)
    ):
        raise _Birlestirilemez("eylem dizisi farklı")
    ad = sutunlar.ad("girdi", araliklar)
    return " ".join([*onek, f"<{ad}>", *sonek])


def _beklenen_alani(sutunlar: _Sutunlar, degerler: Sequence[str], rol: str) -> str:
    """Beklenen alanı: değişen aralık bir girdi sütunuysa o yer tutucu, değilse tüm metin sütun."""
    if _sabit_mi(degerler):
        return degerler[0]
    onek, sonek, araliklar = _aralik(degerler)
    ad = sutunlar.girdi_ile_ayni(araliklar)
    if ad is not None and (onek or sonek):
        return " ".join([*onek, f"<{ad}>", *sonek])
    # Tüm metin sütunsa değerler doğal adım diliyle yazılır (yer tutucu satırda dönüşmez).
    return f"<{sutunlar.ad(rol, [dogal_metin(tek_satir(d)) for d in degerler])}>"


def _taslak(cases: Sequence[GherkinCase]) -> _Taslak | None:
    """Grup birleştirilebiliyorsa taslak, değilse None (kurallar modül açıklamasında)."""
    icerikler = [c.icerik for c in cases]
    alanlar = [_adim_alanlari(i) for i in icerikler]
    td = [_td_alanlari(i) for i in icerikler]
    tum_metin = [
        *(x for a in alanlar for liste in a for x in liste if x),
        *(x for t in td for liste in t for x in liste),
        *(str(i.get("expected_result") or "") for i in icerikler),
        *(tek_satir(x) for i in icerikler for x in i.get("preconditions") or []),
        *(tek_satir(v.get("name")) for i in icerikler for v in i.get("test_data") or []),
    ]
    if any(_YER_TUTUCU.search(m) for m in tum_metin):
        return None
    # Docstring gerektiren adım verisi (çok satır, tırnak, uzun) ve çok satırlı test verisi
    # kelime aralığına bölünmez.
    if any(not _satir_ici_mi(x) for a in alanlar for x in a[1] if x):
        return None
    if any("\n" in x or "\r" in x for t in td for x in t[0]):
        return None
    s = _Sutunlar()
    t = _Taslak(cases=list(cases))
    try:
        n_adim = len(alanlar[0][0])
        for k in range(n_adim):
            t.eylemler.append(_girdi_alani(s, [tek_satir(a[0][k]) for a in alanlar], eylem=True))
            veri = [a[1][k] for a in alanlar]
            if veri[0] is None:
                t.veriler.append(None)
            else:
                t.veriler.append(_girdi_alani(s, [str(v) for v in veri], eylem=False))
        for j in range(len(td[0][0])):
            t.td_degerleri.append(_girdi_alani(s, [x[0][j] for x in td], eylem=False))
        if not any(a == "girdi" or a.startswith("girdi_") for a in s.degerler):
            raise _Birlestirilemez("değişen girdi yok")
        for j in range(len(td[0][1])):
            siniflar = [x[1][j] for x in td]
            t.td_siniflari.append(
                siniflar[0] if _sabit_mi(siniflar) else f"<{s.ad('sınıf', siniflar)}>"
            )
        t.sonuc = _beklenen_alani(
            s, [tek_satir(i.get("expected_result")) for i in icerikler], "beklenen"
        )
        for k in range(n_adim):
            t.beklenenler.append(
                _beklenen_alani(s, [tek_satir(a[2][k]) for a in alanlar], "ara_beklenen")
            )
    except _Birlestirilemez:
        return None
    if not _dil_kayipsiz(t, s, icerikler, alanlar, td):
        return None
    girdi_satirlari = [
        tuple(v[r] for a, v in s.degerler.items() if a == "girdi" or a.startswith("girdi_"))
        for r in range(len(cases))
    ]
    if len(set(girdi_satirlari)) != len(girdi_satirlari):
        return None
    sira = {rol: i for i, rol in enumerate(SUTUN_SIRASI)}

    def _sira(ad: str) -> tuple[int, int]:
        rol, _, n = (
            ad.partition("_") if not ad.startswith("ara_") else ("ara_beklenen", "", ad[13:])
        )
        return sira[rol], int(n or 1)

    t.sutunlar = {ad: list(s.degerler[ad]) for ad in sorted(s.degerler, key=_sira)}
    return t


def _dil_kayipsiz(
    t: _Taslak,
    s: _Sutunlar,
    icerikler: Sequence[Mapping[str, Any]],
    alanlar: Sequence[tuple[list[str], list[str | None], list[str]]],
    td: Sequence[tuple[list[str], list[str]]],
) -> bool:
    """Doğal dil dönüşümleri (baş harf, koşul kipi, test verisi adı) yer tutuculu metinde de
    satırdaki gibi sonuç veriyor mu: taslağın her açılmış satırı = case'in tekil dönüşümü."""

    def doldur(metin: str, r: int) -> str:
        return re.sub(
            r"<([^<>]+)>",
            lambda m: s.degerler[m.group(1)][r] if m.group(1) in s.degerler else m.group(0),
            metin,
        )

    td_kayit = [v for v in icerikler[0].get("test_data") or [] if isinstance(v, Mapping)]
    for r, icerik in enumerate(icerikler):
        eylemler, veriler, beklenenler = alanlar[r]
        satir_td = [v for v in icerik.get("test_data") or [] if isinstance(v, Mapping)]
        for k, eylem in enumerate(eylemler):
            if doldur(_eylem_metni(t.eylemler[k]), r) != _eylem_metni(eylem):
                return False
            if doldur(dogal_metin(t.beklenenler[k]), r) != dogal_metin(tek_satir(beklenenler[k])):
                return False
            if _test_verisi_adi(t.veriler[k], td_kayit, t.td_degerleri) != _test_verisi_adi(
                veriler[k], satir_td, td[r][0]
            ):
                return False
        sonuc = tek_satir(icerik.get("expected_result"))
        if doldur(dogal_metin(t.sonuc), r) != dogal_metin(sonuc):
            return False
    return True


def plan_scenarios(cases: Sequence[GherkinCase]) -> list[Senaryo]:
    """Case'ler → senaryolar (tekil ya da taslak); taslak ilk üyesinin yerinde durur."""
    gruplar: dict[tuple[Any, ...], list[GherkinCase]] = {}
    for c in cases:
        anahtar = _grup_anahtari(c.icerik)
        if anahtar is not None:
            gruplar.setdefault(anahtar, []).append(c)
    taslaklar: dict[str, _Taslak] = {}
    for uyeler in gruplar.values():
        if len(uyeler) < 2:
            continue
        t = _taslak(uyeler)
        if t is not None:
            for u in uyeler:
                taslaklar[u.id] = t
    plan: list[Senaryo] = []
    yazilan: set[int] = set()
    for c in cases:
        t = taslaklar.get(c.id)
        if t is None:
            plan.append(_Tekil(c))
        elif id(t) not in yazilan:
            yazilan.add(id(t))
            plan.append(t)
    return plan


# --------------------------------------------------------------------------- yazım


def _teknik_sirali(icerikler: Iterable[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for i in icerikler:
        for t in i.get("technique") or []:
            if str(t) not in out:
                out.append(str(t))
    return out


def _tekil(c: GherkinCase, girinti: str) -> list[str]:
    i = c.icerik
    eylemler, veriler, beklenenler = _adim_alanlari(i)
    degerler, siniflar = _td_alanlari(i)
    return [
        girinti
        + _etiketler(_ac_refs(i), _teknik_sirali([i]), i.get("priority"), _tur_etiketi(i), c.id),
        f"{girinti}Senaryo: {tek_satir(i.get('title'))}",
        *_govde(
            i,
            girinti + GIRINTI,
            eylemler=eylemler,
            veriler=veriler,
            beklenenler=beklenenler,
            sonuc=str(i.get("expected_result") or ""),
            td_degerleri=degerler,
            td_siniflari=siniflar,
        ),
    ]


def _taslak_adi(t: _Taslak) -> str:
    ilk = t.cases[0].icerik
    birincil = str((ilk.get("technique") or [""])[0])
    ad = TECHNIQUE_TR.get(birincil, birincil)
    return f"{', '.join(_ac_refs(ilk))} · {ad} ({birincil}) — {len(t.cases)} örnek"


def _taslak_satirlari(t: _Taslak, girinti: str) -> list[str]:
    ilk = t.cases[0].icerik
    out = [
        girinti
        + _etiketler(
            _ac_refs(ilk),
            _teknik_sirali(c.icerik for c in t.cases),
            ilk.get("priority"),
            _tur_etiketi(ilk),
            None,
        ),
        f"{girinti}Senaryo taslağı: {_taslak_adi(t)}",
        *_govde(
            ilk,
            girinti + GIRINTI,
            eylemler=t.eylemler,
            veriler=t.veriler,
            beklenenler=t.beklenenler,
            sonuc=t.sonuc,
            td_degerleri=t.td_degerleri,
            td_siniflari=t.td_siniflari,
        ),
    ]
    basliklar = ["teknik", "bölüm_id", *t.sutunlar]
    for r, c in enumerate(t.cases):
        satir = [
            ", ".join(str(x) for x in c.icerik.get("technique") or []),
            ", ".join(str(x) for x in c.icerik.get("covers") or []),
            *(v[r] for v in t.sutunlar.values()),
        ]
        out += [
            "",
            f"{girinti}{GIRINTI}@tp-{etiket(c.id)}",
            f"{girinti}{GIRINTI}Örnekler: {tek_satir(c.icerik.get('title'))}",
            *_tablo([basliklar, satir], girinti + GIRINTI * 2),
        ]
    return out


def render_feature(
    anahtar: str,
    baslik: str,
    cases: Sequence[GherkinCase],
    kabul_kriterleri: Sequence[Any] = (),
    *,
    plan: Sequence[Senaryo] | None = None,
) -> str:
    """Türkçe Gherkin metni (sonda tek satır sonu). `cases` zaten süzülmüş ve sıralıdır."""
    plan = list(plan) if plan is not None else plan_scenarios(cases)
    satirlar = [
        "# language: tr",
        "# Testing Probe — onaylı ve hazır case'lerden deterministik dönüşüm (model çağrısı yok).",
        f"# {len(cases)} case · {len(plan)} senaryo "
        # "taslak" tek başına case durumu (draft) ile karışıyordu (UX4 Bulgu 9): Senaryo taslağı =
        # örnek tablolu senaryo.
        f"({sum(1 for s in plan if isinstance(s, _Taslak))} örnek tablolu senaryo)",
        f"Özellik: {tek_satir(anahtar)} — {tek_satir(baslik)}",
    ]
    for ref, metin in acceptance_criteria(kabul_kriterleri):
        satirlar.append(f"{GIRINTI}# {ref}: {tek_satir(metin)}")
    for s in plan:
        satirlar.append("")
        if isinstance(s, _Taslak):
            satirlar += _taslak_satirlari(s, GIRINTI)
        else:
            satirlar += _tekil(s.case, GIRINTI)
    return "\n".join(satirlar) + "\n"
