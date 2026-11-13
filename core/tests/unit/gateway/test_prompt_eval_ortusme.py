"""Prompt örnekleri ile değerlendirme girdileri örtüşmez (011 test mimarı 3. tur #2: "eval'e
öğretme").

Prompt'taki örnek (tırnaklı ifade, kod bloğu, sayı + birim, ürün/kayıt kodu, kod tanımlayıcısı,
alan sözcüğü) değerlendirme setlerinin girdisinde de geçiyorsa canlı eval sonucu genelleme kanıtı
olmaz: model vakanın cevabını prompt'tan okur. Bu modül iki yönü denetler:

- `case-generation`, `design-model` ve `assistant` prompt'larından örnek parçalarını çıkarır
  (`ornek_parcalari`);
- `rules/evaluation/*.json` (sonuç raporları hariç) girdilerinden metin derlemi kurar
  (`eval_derlemi`): vaka mesajları (platform eki metni prompt'tur, çıkarılır), beklentiler,
  açıklamalar. Bekletme (holdout) vakaları da bu setlerdedir, onlar da denetlenir;
- örnek parçasının kendisi, sayı + birim kalıpları, kodları, tanımlayıcıları, içerik sözcükleri
  ve sözcük 3-gram'ları derlemde aranır. Genel terimler (şema alan adları, teknik kodları, rol
  adları, kural sözcükleri) izin listesindedir (`IZINLI_*`).

Betik olarak da çalışır (bulguları listeler, çıkış kodu bulgu varsa 1):

    cd core && uv run python -m tests.unit.gateway.test_prompt_eval_ortusme
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from tp_core.gateway import find_rules_dir

RULES = find_rules_dir()
PROMPTLAR = ("case-generation", "design-model", "assistant")
EVAL_DIR = RULES / "evaluation"

# Platform eki metni (Testing Probe kuralları) eval girdisinde prompt olarak taşınır; veri değildir.
_PLATFORM_EKI = re.compile(r"Platform ekleri \(Testing Probe kuralları.*?(?=<untrusted|\Z)", re.S)


def _kucuk(metin: str) -> str:
    """Türkçe küçük harf + boşluk sadeleştirme."""
    metin = metin.replace("İ", "i").replace("I", "ı").lower()
    return re.sub(r"\s+", " ", metin).strip()


_SOZCUK = re.compile(r"[0-9a-zçğıöşü_]+(?:[.,][0-9]+)*", re.IGNORECASE)


def _sozcukler(metin: str) -> list[str]:
    return _SOZCUK.findall(_kucuk(metin))


# ------------------------------------------------------------------ izin listesi (genel terimler)


@lru_cache(maxsize=1)
def _sema_terimleri() -> frozenset[str]:
    """Şema alan adları ve enum değerleri (`rules/schemas/*.json`): prompt'un sözleşmesidir."""
    out: set[str] = set()

    def gez(x: Any) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                out.add(_kucuk(str(k)))
                if k == "enum" and isinstance(v, list):
                    out.update(_kucuk(str(e)) for e in v)
                if k == "const":
                    out.add(_kucuk(str(v)))
                gez(v)
        elif isinstance(x, list):
            for v in x:
                gez(v)

    for path in (RULES / "schemas").glob("*.json"):
        gez(json.loads(path.read_text(encoding="utf-8")))
    return frozenset(out)


# Ürünün kendi sözlüğü ve test tasarımı terimleri: her story'de doğal olarak geçer, vaka cevabı
# taşımaz. Yeni bir öğe eklerken örnek DEĞİL, genel kural/terim olduğundan emin olun.
IZINLI_IFADELER = frozenset(
    _kucuk(x)
    for x in (
        # Girdi satırları ve kural işaretleri (girdi kurucusu bunları her vakaya yazar).
        "Test seviyesi: SYSTEM",
        "BVA kipi: 2-değer",
        "BVA kipi: 3-değer",
        "Risk notları:",
        "Risk notları: …",
        "Hata geçmişi:",
        "Hata geçmişi: …",
        "AÇIK NOKTA",
        "hata gösterilir (mesaj metni: AÇIK NOKTA)",
        "Test verisi hazırlığı:",
        "1.250,00 TL",  # tutar biçimi örneği; demo test verisi bloğunun "Tutar biçimi" satırı
        "0,01 TL",  # tutar adımı (genel)
        "kip=oneri",
        "kind=oneriler",
        "Başka ne yapabilirim?",
        "Daha ayrıntılı incele",
        "emin değilim",
        "doğrulayamadım",
        "doğrulamadım",
        "bulamadım",
        "submit_result",
        # 013 asistan güvenlik sözleşmesi (dev birleştirmesi): prompt bu sözcükleri zorunlu kural
        # sözcüğü ("sentetik", "hata adayı") ya da yasak iddia ("%100 test edildi", "hiç hata
        # yok") olarak tanımlar; eval aynı sözleşmeyi ölçer. Vaka cevabı öğreten örnek değildir.
        "sentetik",
        "hata adayı",
        "%100 test edildi",
        "hiç hata yok",
    )
)
IZINLI_SOZCUKLER = frozenset(
    _kucuk(x)
    for x in (
        # Roller ve süreç (ürün sözlüğü).
        "analist",
        "analyst",
        "po",
        "ürün",
        "sahibi",
        "mühendis",
        "testçi",
        "sunucu",
        "developer",
        "rol",
        "yapar",
        "onayla",
        "onaylı",
        "case",
        "case'i",
        "caseler",
        "gereksinimler",
        "jira",
        "yorum",
        "story",
        "task",
        "bug",
        "test",
        "verisi",
        "hazırlığı",
        "hazırlanır",
        "sentetik",
        "seviyesi",
        "system",
        "kipi",
        "değer",
        "risk",
        "notları",
        "hata",
        "geçmişi",
        "açık",
        "nokta",
        "mesaj",
        "metni",
        "gösterilir",
        "kurulabilen",
        "kurulabilir",
        "en",
        "yakın",
        "değer",
        "fiyatı",
        "fiyatlı",
        "olan",
        "tl",
        "adet",
        "kod",
        "kodu",
        "toplam",
        "nasıl",
        "kim",
        "olarak",
        "bunu",
        "ben",
        "eylem",
        "yapamam",
        "rota",
        "id",
        "web",
        "erişilebilirlik",
        "girdi",
        "güvenliği",
        "wcag",
        "ve",
        "ile",
        "bir",
        "bu",
        "için",
        "da",
        "de",
        "mi",
        "mı",
        "ya",
        "veya",
        "ayrıntılı",
        "kaynakla",
        "doğrulayarak",
        "yeniden",
        "incele",
        "kayıtta",
        "talimat",
        "içeren",
        "metin",
        "var",
        "uygulamadım",
        "path",
        "line",
        "start",
        "end",
        "kn",
        "kanit",
    )
)
# Asistan bağlam alanları ve araç adları (asistanın sözleşmesi; prompt'un "Context"/"Tools"
# bölümleri), etiketler ve portal rotaları (`rules/assistant/rotalar.json`).
IZINLI_TANIMLAYICILAR = frozenset(
    {
        "rota_kalibi",
        "varlik",
        "son_hata",
        "secili_eleman",
        "product_read",
        "product_search",
        "probe_get",
        "db_query",
        "get_file_contents",
        "search_code",
        "security",
    }
)
# Şemanın kimlik biçimleri (AC1, Q1, C3, BV-2, EP-I1, TCOND-1, S1, …): her vakada geçer.
_KIMLIK = re.compile(
    r"(?:ac|q|a|c|p|s|u|k|tcond-|ep-[vi]|bv-|dt-r|st-[tx]|pw-|uc-(?:mf|af|ef)?|eg-|cl-)\d*",
)
# Sayı + birim, kod: genel biçim örnekleri (girdi kurucusu / şema bunları her vakaya koyar).
IZINLI_SAYI_BIRIM = frozenset({"0,01 tl", "1.250,00 tl"})


# ------------------------------------------------------------------ prompt örnekleri


@dataclass(frozen=True)
class Parca:
    prompt: str
    satir: int
    metin: str


_BACKTICK = re.compile(r"`([^`\n]+)`")
_TIRNAK = re.compile(r"[\"“]([^\"”\n]{2,200})[\"”]")
_ORNEK_PARANTEZ = re.compile(
    r"\((?:for example|e\.g\.|örneğin|such as)\s+([^()]*(?:\([^()]*\)[^()]*)*)\)", re.I | re.S
)


def _prompt_metni(ad: str) -> str:
    return (RULES / "prompts" / f"{ad}.md").read_text(encoding="utf-8")


def ornek_parcalari(ad: str) -> list[Parca]:
    """Prompt'taki örnek parçaları: kod içi (`…`), tırnak içi ("…") ve "(for example …)"
    parantezleri; satır numarasıyla."""
    metin = _prompt_metni(ad)
    out: list[Parca] = []
    for desen in (_BACKTICK, _TIRNAK, _ORNEK_PARANTEZ):
        for m in desen.finditer(metin):
            satir = metin.count("\n", 0, m.start()) + 1
            out.append(Parca(ad, satir, m.group(1).strip()))
    return out


# ------------------------------------------------------------------ eval derlemi


def _yapraklar(x: Any, anahtar: str = "") -> Iterator[str]:
    if isinstance(x, dict):
        for k, v in x.items():
            # Setin üst bilgisi (not, paket adı) ve geçit ayarı girdi değildir.
            if k in ("note", "bundle", "call_bundle", "purpose", "agent"):
                continue
            yield from _yapraklar(v, k)
    elif isinstance(x, list):
        for v in x:
            yield from _yapraklar(v, anahtar)
    elif isinstance(x, str):
        yield _PLATFORM_EKI.sub(" ", x) if anahtar == "content" else x


def eval_dosyalari() -> list[Path]:
    return sorted(p for p in EVAL_DIR.glob("*.json") if p.is_file())


@lru_cache(maxsize=1)
def eval_derlemi() -> str:
    """Tüm değerlendirme setlerinin girdileri + beklentileri, küçük harfli tek metin."""
    parcalar: list[str] = []
    for path in eval_dosyalari():
        parcalar += list(_yapraklar(json.loads(path.read_text(encoding="utf-8"))))
    return _kucuk("\n".join(parcalar))


@lru_cache(maxsize=1)
def _derlem_sozcukleri() -> frozenset[str]:
    return frozenset(_sozcukler(eval_derlemi()))


@lru_cache(maxsize=1)
def _derlem_3gram() -> frozenset[tuple[str, ...]]:
    s = _sozcukler(eval_derlemi())
    return frozenset(zip(s, s[1:], s[2:], strict=False))


# ------------------------------------------------------------------ denetim

_BIRIM = (
    r"tl|adet\w*|gün\w*|gece\w*|dakika\w*|saat\w*|sn|ms|karakter\w*|kitap\w*|hatalı|deneme\w*|"
    r"bedava|ücretsiz|kez|defa|kişi\w*|yaprak|paket\w*"
)
_SAYI_BIRIM = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*(" + _BIRIM + r")\b", re.I)
_KOD = re.compile(r"\b[A-Z]{1,5}-\d{1,5}\b")
_TANIMLAYICI = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b|\b[a-z_][a-z0-9_.]*(?=\()")
# İçerik sözcüğü: alan anahtar sözcüğü sayılacak kadar uzun (genel ekler/edatlar elenir).
_ICERIK_SOZCUK_UZUNLUK = 5


def _izinli_sozcuk(s: str) -> bool:
    return s in IZINLI_SOZCUKLER or s in _sema_terimleri() or bool(re.fullmatch(r"[\d.,]+", s))


def parca_bulgulari(p: Parca) -> list[str]:
    """Parçanın eval derleminde geçen öğeleri (boşsa örtüşme yok)."""
    derlem = eval_derlemi()
    kucuk = _kucuk(p.metin)
    if (
        kucuk in IZINLI_IFADELER
        or kucuk in _sema_terimleri()
        or kucuk in IZINLI_TANIMLAYICILAR
        or kucuk.startswith("/")  # portal rotası
        or _KIMLIK.fullmatch(kucuk)
        or (
            (m := re.fullmatch(r"([a-z_]+): (?:true|false|null)", kucuk))
            and m.group(1) in _sema_terimleri()
        )
    ):
        return []
    out: list[str] = []
    if len(kucuk) >= 6 and kucuk in derlem:
        out.append(f"ifade {p.metin!r}")
    for m in _SAYI_BIRIM.finditer(p.metin):
        sb = _kucuk(f"{m.group(1)} {m.group(2)}")
        if sb not in IZINLI_SAYI_BIRIM and re.search(
            r"(?<![\d.,])" + re.escape(_kucuk(m.group(1))) + r"\s*" + re.escape(_kucuk(m.group(2))),
            derlem,
        ):
            out.append(f"sayı+birim {m.group(0)!r}")
    for kod in _KOD.findall(p.metin):
        if _KIMLIK.fullmatch(_kucuk(kod)):
            continue
        if re.search(r"(?<![\w-])" + re.escape(_kucuk(kod)) + r"(?![\w-])", derlem):
            out.append(f"kod {kod!r}")
    for t in _TANIMLAYICI.findall(p.metin):
        if t in IZINLI_TANIMLAYICILAR:
            continue
        if t not in _sema_terimleri() and re.search(r"\b" + re.escape(t) + r"\b", derlem):
            out.append(f"tanımlayıcı {t!r}")
    sozcukler = _sozcukler(p.metin)
    for s in sozcukler:
        if (
            len(s) >= _ICERIK_SOZCUK_UZUNLUK
            and not _izinli_sozcuk(s)
            and s in _derlem_sozcukleri()
            and s in _ALAN_SOZCUKLERI
        ):
            out.append(f"alan sözcüğü {s!r}")
    for g in zip(sozcukler, sozcukler[1:], sozcukler[2:], strict=False):
        if all(_izinli_sozcuk(s) for s in g):
            continue
        if g in _derlem_3gram():
            out.append(f"3-gram {' '.join(g)!r}")
    return sorted(set(out))


# Eval story'lerinin alan sözcükleri (kök): bir örnekte geçmeleri, örneğin eval alanından
# alındığını gösterir. Bekletme (holdout) alanları da burada: prompt örnekleri onlardan da
# alınmaz. Liste eval derleminden türetilmiş kökleri tutar; kökle başlayan sözcük eşleşir.
_ALAN_KOKLERI = (
    # Demo story'leri (TPD-1/3/4, SERBEST) ve test verisi.
    "bayi",
    "sepet",
    "sipariş",
    "kampanya",
    "bedava",
    "portakal",
    "gazoz",
    "limonata",
    "maden",
    "şeftali",
    "katalog",
    "kredi",
    "limit",
    "parola",
    "kullanıcı",
    "giriş",
    "arama",
    "aranan",
    "limon",
    # Sentetik ST story'si (hesap kilidi).
    "kilit",
    "kilid",
    "yönetici",
    "sayaç",
    "sayac",
    "sıfırla",
    # Bekletme (holdout) alanları.
    "kütüphane",
    "ödünç",
    "kitap",
    "üye",
    "otopark",
    "plaka",
    "abone",
    "poliçe",
    "sigorta",
    "prim",
    "hasar",
    "yenile",
    "kırtasiye",
    "kargo",
)


class _Kokler:
    def __contains__(self, s: object) -> bool:
        return isinstance(s, str) and any(s.startswith(k) for k in _ALAN_KOKLERI)


_ALAN_SOZCUKLERI = _Kokler()


def ortusmeler(adlar: tuple[str, ...] = PROMPTLAR) -> list[str]:
    out = []
    for ad in adlar:
        for p in ornek_parcalari(ad):
            for b in parca_bulgulari(p):
                out.append(f"rules/prompts/{ad}.md:{p.satir}: {b} — örnek: {p.metin[:80]!r}")
    return sorted(set(out))


# ------------------------------------------------------------------ testler


def test_prompt_ornekleri_eval_girdileriyle_ortusmez() -> None:
    bulgular = ortusmeler()
    assert not bulgular, "prompt örneği eval girdisinde geçiyor:\n" + "\n".join(bulgular)


def test_derlem_bekletme_setini_ve_eval_story_lerini_icerir() -> None:
    """Derlem gerçekten eval girdilerini taşır (boş derlem her şeyi geçirirdi)."""
    derlem = eval_derlemi()
    assert "minimum sipariş tutarı 750,00 tl" in derlem
    assert "hesabınız kilitlendi" in derlem
    assert "holdout" in derlem  # bekletme vakalarının alt küme etiketi
    # Platform eki (prompt metni) derleme girmez.
    assert "checklist, not quota" not in derlem


def test_denetleyici_eval_kaynakli_ornegi_yakalar(monkeypatch) -> None:
    """Karşı örnek: eski prompt örnekleri (eval vakasından alınmış) yakalanır."""
    eski = [
        Parca("x", 1, "(7 adette 1 bedava)"),
        Parca("x", 2, "Yönetici hesabın kilidini açar"),
        Parca("x", 3, "PO olarak nasıl onaylarım?"),
        Parca("x", 4, "749,99 TL; demo fiyatlarıyla kurulabilen en yakın değer 749,00 TL"),
        Parca("x", 5, 'Arama alanına "limon" yazılır'),
    ]
    for p in eski:
        assert parca_bulgulari(p), p.metin
    # Kurgusal, eval dışı örnek geçer.
    assert parca_bulgulari(Parca("x", 6, "Sera sorumlusu sulama vanasını kapatır")) == []


def main() -> int:  # pragma: no cover - betik girişi
    bulgular = ortusmeler()
    for b in bulgular:
        print(b)
    toplam = sum(len(ornek_parcalari(a)) for a in PROMPTLAR)
    print(
        f"{len(bulgular)} örtüşme; {toplam} örnek parçası, {len(eval_dosyalari())} eval seti",
        file=sys.stderr,
    )
    return 1 if bulgular else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
