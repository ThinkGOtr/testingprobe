"""Mükerrer araması için güvenli JQL (TEKNIK-TASARIM §8.12, §5 güvenilmeyen girdi).

Hata imzasının metinleri (test adı, hata mesajı, AC metni) test kodundan ve Jira'dan gelir:
güvenilmezdir. JQL'e asla ham metin girmez:

- Proje anahtarı yalnızca `^[A-Z][A-Z0-9_]+$` olabilir (aksi hâlde `ValueError`).
- Tırnaklı her değer `quote()` ile kaçışlanır (ters bölü ve çift tırnak).
- Metin araması yalnızca **kelime terimlerinden** kurulur: Unicode harf/rakam dışı her karakter
  ayırıcıdır, bu yüzden Lucene/JQL özel karakterleri (`+ - & | ! ( ) { } [ ] ^ ~ * ? \\ / : "`)
  terime giremez. JQL ayrılmış sözcükleri ve Lucene işleçleri (`AND`, `OR`, `NOT`, `TO`, …),
  kısa terimler ve yaygın sözcükler atılır; terim sayısı sınırlıdır.
- Terimler `text ~ "t1" OR text ~ "t2" …` olarak birleştirilir (tek ifadede çok terim Jira'da da
  simülatörde de "hepsi" anlamına gelir; mükerrer adayını kaçırmamak için her terim ayrı).

Sorgu: ``project = "TPD" AND issuetype = "Bug" AND statusCategory != "Done" AND (…)``.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence

PROJE_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")
ANAHTAR_RE = re.compile(r"^[A-Z][A-Z0-9_]+-[0-9]+$")
MAX_TERIM = 8
MIN_TERIM_UZUNLUGU = 3
MAX_TERIM_UZUNLUGU = 40

_KELIME = re.compile(r"[^\W_]+", re.UNICODE)


def _sozcukler(metin: str) -> list[str]:
    return metin.split()


# Jira'nın ayrılmış JQL sözcükleri (tırnaksız kullanılamaz) ve Lucene işleçleri. Terimler tırnak
# içinde olsa da metin araması bunları işleç sayabilir; hiç gönderilmez.
JQL_AYRILMIS = frozenset(
    w.casefold()
    for w in _sozcukler(
        "a an abort access add after alias all alter and any are as asc audit avg before begin "
        "between boolean break by byte catch cf char character check checkpoint collate collation "
        "column commit connect continue count create current date decimal declare decrement "
        "default defaults define delete delimiter desc difference distinct divide do double drop "
        "else empty encoding end equals escape exclusive exec execute exists explain false fetch "
        "file field first float for from function go goto grant greater group having identified "
        "if immediate in increment index initial inner inout input insert int integer intersect "
        "intersection into is isempty isnull join last left less like limit lock long max "
        "message min minus mode modify modulo more multiply next noaudit not notin nowait null "
        "number object of on option or order outer output power previous prior privileges "
        "public raise raw remainder rename resource return returns revoke right row rowid rownum "
        "rows select session set share size sqrt start strict string subtract sum synonym table "
        "then to trans transaction trigger true uid union unique update user validate values "
        "view when whenever where while with"
    )
)

# Yaygın, ayırt edici olmayan sözcükler (Türkçe/İngilizce) ve test kodu gürültüsü.
DURAK = frozenset(
    w.casefold()
    for w in _sozcukler(
        "ve veya ile için gibi bir bu şu da de ki mi mı mu mü ama fakat olarak olan olur "
        "yok var değil daha çok her hiç sonra önce kadar göre üzerinde içinde sayfa sayfası "
        "butonu buton bas basar basıldığında gösterilir görünür beklenen gerçekleşen test "
        "testi adet tutarı the and for with not was are expect expected received tohavetext "
        "tobe toequal tocontain locator getbytestid getbyrole timeout error hata page "
        # Görev şablonunun her Bug'da geçen başlık sözcükleri (bugs/content.py description_adf):
        # ortak isabet üretmesin. Kalıp cümlelerdeki alan sözcükleri ("kullanıcı", "hatalı")
        # bilinçli olarak dışarıda: gerçek hata metninde ayırt edicidirler.
        "objective amaç scope kapsam flow akışı dependencies integration bağımlılıklar "
        "entegrasyon information assets kaynaklar acceptance criteria kriterleri checklist "
        "applicable regresyon gözlenmez izlenir"
    )
)


# Demo alanında her kayıtta geçen kökler (bayi, bayinin, sipariş, siparişi …) ve kabul kriteri
# numaraları (ac1, ac4): ayırt edici değildir, alakasız Bug'ları aday yapar.
DURAK_ONEK = ("bayi", "sipariş")
_AC_NO = re.compile(r"^ac\d+$")


def quote(deger: str) -> str:
    """JQL çift tırnaklı değer: ters bölü ve çift tırnak kaçışlanır, kontrol karakteri atılır."""
    temiz = "".join(ch for ch in str(deger) if unicodedata.category(ch)[0] != "C")
    return '"' + temiz.replace("\\", "\\\\").replace('"', '\\"') + '"'


def check_project(proje: str) -> str:
    if not isinstance(proje, str) or not PROJE_RE.fullmatch(proje):
        raise ValueError(f"Geçersiz Jira proje anahtarı: {proje!r}")
    return proje


def is_issue_key(deger: object) -> bool:
    return isinstance(deger, str) and bool(ANAHTAR_RE.fullmatch(deger))


def _fold(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold().replace("i̇", "i")


def key_terms(
    metinler: Iterable[str | None], limit: int = MAX_TERIM, gizliler: Iterable[str] = ()
) -> list[str]:
    """Metinlerden mükerrer araması terimleri: sıra korunur, tekrarsız, güvenli.

    Yalnızca harf/rakam dizileri; sayılar, ayrılmış sözcükler, yaygın sözcükler ve çok kısa/uzun
    terimler atılır. 013 K19 (güvenlik #1): bilinen bir gizli değerin (katlanmış biçiminde)
    parçası olan terim de atılır; parola Jira aramasına, `ek.jql`'e ve denetime girmez.
    """
    katli = [_fold(g) for g in gizliler if isinstance(g, str) and g]
    out: list[str] = []
    gorulen: set[str] = set()
    for metin in metinler:
        if not metin:
            continue
        for kelime in _KELIME.findall(str(metin)):
            k = _fold(kelime)
            if (
                len(k) < MIN_TERIM_UZUNLUGU
                or len(k) > MAX_TERIM_UZUNLUGU
                or k.isdigit()
                or k in JQL_AYRILMIS
                or k in DURAK
                or k.startswith(DURAK_ONEK)
                or _AC_NO.fullmatch(k)
                or k in gorulen
                or any(k in g for g in katli)
            ):
                continue
            gorulen.add(k)
            out.append(k)
            if len(out) >= limit:
                return out
    return out


def duplicate_search_jql(proje: str, terimler: Sequence[str]) -> str | None:
    """Açık Bug'larda metin araması. Terim yoksa None (arama yapılmaz)."""
    check_project(proje)
    guvenli = key_terms(terimler, limit=MAX_TERIM)
    if not guvenli:
        return None
    metin = " OR ".join(f"text ~ {quote(t)}" for t in guvenli)
    return (
        f"project = {quote(proje)} AND issuetype = {quote('Bug')} "
        f"AND statusCategory != {quote('Done')} AND ({metin}) ORDER BY updated DESC"
    )


def label_jql(proje: str, etiket: str) -> str:
    """Kendi kaydımızı (etiket `tp-<uuid>`) bulma sorgusu (idempotency)."""
    check_project(proje)
    return f"project = {quote(proje)} AND labels = {quote(etiket)}"


def overlap_score(terimler: Sequence[str], metin: str) -> int:
    """Adayın metninde geçen terim sayısı (kaba kök eşleşmesi; AI'dan önceki deterministik sıra)."""
    kelimeler = [_fold(k) for k in _KELIME.findall(metin or "")]
    puan = 0
    for t in terimler:
        kok = t if len(t) <= 4 else t[: max(4, len(t) - 3)]
        if any(k.startswith(kok) for k in kelimeler):
            puan += 1
    return puan
