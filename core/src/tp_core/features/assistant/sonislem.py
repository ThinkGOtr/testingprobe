"""Deterministik son işlem (AI-ASISTAN-PLANI §7.3, §17.5; constitution III, XI).

Model çıktısı (`assistant.schema.json`) saklanmadan ve gösterilmeden önce burada işlenir; hiçbir
adım modele sorulmaz:

- **Metin**: bloklardaki Markdown görsel/bağlantı kalıpları (`![..](..)`, `[..](..)`) metnine,
  çıplak URL'ler ve `javascript:`/`data:` kalıpları "[bağlantı kaldırıldı]"na çevrilir; toplam 6000
  karakterde kırpılır. Portal blokları düz metin çizer (HTML yok).
- **Linkler**: yalnız `rotalar.json` kalıbına uyan iç rota (`yonlendirmeler`) ve Testing Probe'da
  kaydı olan Jira anahtarı (`jira_anahtarlari`; bağlantıyı sunucu kurar). Başka dış link yok.
- **Kaynak doğrulama**: `urun_kodu`/`dokuman` (MANIFEST'te dosya, satır aralıkta, alıntı satırda),
  `uygulama_kodu` (aynı sha'da forge), `uygulama_verisi` (havuzdaki SQL yeniden çalıştırılır, en
  çok 5, `bitis` içinde; özet `digest_matches_any`), `probe_verisi`/`jira`/`ci_log` (`kN` türü
  uyuşmalı; alıntı havuzdaki metnin aynı oturumla maskesi açılmış hâlinde, yalnız bellekte).
  Doğrulanmayan kaynak silinmez, `dogrulandi=false` olur.
- **Öneri eylemleri** (yalnız öneri kipi; soru kipinde `oneriler` boşaltılır): rota dışı → `bilgi`;
  taslak metninde URL "[bağlantı kaldırıldı]", Jira wiki bağlantısı ve mention temizlenir; proje
  daima sunucudaki `JIRA_PROJECT`; bilinmeyen anahtar → null (`jira_yorum`/`jira_kaydi` → `bilgi`);
  en çok 3; kural önerisiyle aynı başlık (normalize) atılır.
- **Güven gösterimi**: §7.3 tablosu (`guven_gosterimi`).
- Müşteri verisi kurulumunda cevap aynı oturumla yeniden maskelenir; her kaynağın sha256'sı
  `dogrulama`'ya yazılır.

Saklanan biçim (portal `AsistanCevabi`): şema alanları + `guven_gosterimi`, `dogrulama`,
`urune_ozgu`, `toparlama`, `notlar`, `jira_baglantilari`.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from tp_core.features.assistant.siniflandir import normalize
from tp_core.features.assistant.tools.base import KanitHavuzu, sir_temizle
from tp_core.gateway.masking import MaskingSession

log = logging.getLogger(__name__)

DOGRULANDI: Final = "Kaynakla doğrulandı"
KISMEN: Final = "Kısmen"
EMIN_DEGIL: Final = "Emin değil"
GENEL_BILGI: Final = "Genel bilgi"

METIN_AZAMI: Final = 6000
ETIKET_AZAMI: Final = 80
ALINTI_AZAMI: Final = 600
YONLENDIRME_AZAMI: Final = 5
JIRA_ANAHTAR_AZAMI: Final = 10
KAYNAK_AZAMI: Final = 20
ONERI_AZAMI: Final = 3
ONERI_BASLIK_AZAMI: Final = 80
ONERI_NEDEN_AZAMI: Final = 400
TASLAK_OZET_AZAMI: Final = 200
TASLAK_ACIKLAMA_AZAMI: Final = 3000
VERI_DOGRULAMA_AZAMI: Final = 5
VERI_SORGU_UST_S: Final = 10.0
VERI_EN_AZ_KALAN_S: Final = 0.5
URUN_SATIR_AZAMI: Final = 400
ALINTI_EN_AZ: Final = 8  # requirements/verifier.MIN_SNIPPET ile aynı

BAGLANTI_KALDIRILDI: Final = "[bağlantı kaldırıldı]"
NOT_URUN_KAYNAGI_YOK: Final = "Ürün kaynağıyla doğrulanmadı; genel bilgiye dayanıyor."
NOT_TOPARLAMA: Final = "Cevap süre/bağlam sınırında eldeki bilgiyle toparlandı."

KAYNAK_TURLERI: Final = frozenset(
    {
        "urun_kodu",
        "uygulama_kodu",
        "uygulama_verisi",
        "probe_verisi",
        "jira",
        "ci_log",
        "dokuman",
        "genel_bilgi",
    }
)
HAVUZ_TURLERI: Final = frozenset({"probe_verisi", "jira", "ci_log"})
BLOK_TURLERI: Final = frozenset({"baslik", "paragraf", "liste", "kod"})
EYLEM_TURLERI: Final = frozenset({"rota", "jira_taslak", "jira_yorum", "jira_kaydi", "bilgi"})
YENI_KAYIT_TURLERI: Final = frozenset({"Task", "Bug", "Story"})

# ASCII rakam (`\d` Unicode rakamı da kabul ederdi).
JIRA_ANAHTARI: Final = re.compile(r"[A-Z][A-Z0-9]+-[0-9]+")
_GORSEL: Final = re.compile(r"!\[([^\]\n]*)\]\([^)\n]*\)")
_MD_BAGLANTI: Final = re.compile(r"\[([^\]\n]*)\]\([^)\n]*\)")
_URL: Final = re.compile(
    r"(?i)(?:\b[a-z][a-z0-9+.\-]*://|\bwww\.)[^\s<>\"'`]*"
    r"|\b(?:javascript|data|vbscript|file)\s*:[^\s<>\"'`]*"
)
_WIKI_BAGLANTI: Final = re.compile(r"\[([^\[\]|\n]*)\|[^\[\]\n]*\]")
_MENTION_ID: Final = re.compile(r"\[~[^\]\n]*\]")
_MENTION: Final = re.compile(r"(?<![\w.@])@[\w.\-]+")
_SATIR_REF: Final = re.compile(r"^(?P<yol>[^\s:][^:]*):(?P<bas>[0-9]+)(?:-(?P<son>[0-9]+))?$")
_SATIR_ONEKI: Final = re.compile(r"(?m)^\s*[0-9]+\|\s?")
_ROTA: Final = re.compile(r"^/[A-Za-z0-9_\-/]*$")


def bos_cevap() -> dict[str, Any]:
    """Saklanan cevabın iskeleti (sözlük/şablon/kapalı cevaplar da bunu doldurur)."""
    return {
        "cevap_bloklari": [],
        "guven": None,
        "guven_gosterimi": None,
        "kaynaklar": [],
        "yonlendirmeler": [],
        "jira_anahtarlari": [],
        "jira_baglantilari": [],
        "eylem_reddi": False,
        "oneriler": [],
        "notlar": [],
        "dogrulama": {},
        "urune_ozgu": False,
        "toparlama": False,
    }


# ------------------------------------------------------------------ metin


def duz_metin(metin: Any) -> str:
    """Markdown görsel/bağlantı → metni; URL ve `javascript:`/`data:` → "[bağlantı kaldırıldı]"."""
    if not isinstance(metin, str):
        return ""
    metin = _GORSEL.sub(lambda m: m.group(1), metin)
    metin = _MD_BAGLANTI.sub(lambda m: m.group(1), metin)
    return _URL.sub(BAGLANTI_KALDIRILDI, metin)


def taslak_metni(metin: Any) -> str:
    """Model taslağı (§17.5): URL silinir, Jira wiki bağlantısı ve mention sözdizimi temizlenir."""
    if not isinstance(metin, str):
        return ""
    metin = _MENTION_ID.sub("", metin)
    metin = _WIKI_BAGLANTI.sub(lambda m: m.group(1), metin)
    metin = duz_metin(metin)
    metin = _MENTION.sub("", metin)
    return re.sub(r"[ \t]{2,}", " ", metin).strip()


def kirp(metin: str, ust: int) -> str:
    metin = metin.strip()
    return metin if len(metin) <= ust else metin[: ust - 1].rstrip() + "…"


def norm_ws(metin: str) -> str:
    return " ".join(str(metin).split())


def _bloklar(ham: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    kalan = METIN_AZAMI
    for b in ham if isinstance(ham, list) else []:
        if kalan <= 0 or not isinstance(b, Mapping):
            break
        tur = b.get("tur") if b.get("tur") in BLOK_TURLERI else "paragraf"
        metin = duz_metin(b.get("metin"))
        if len(metin) > kalan:
            metin = metin[: max(kalan - 1, 0)] + "…"
        kalan -= len(metin)
        maddeler: list[str] = []
        if tur == "liste":
            for m in b.get("maddeler") or []:
                if kalan <= 0:
                    break
                madde = duz_metin(m)
                if len(madde) > kalan:
                    madde = madde[: max(kalan - 1, 0)] + "…"
                kalan -= len(madde)
                maddeler.append(madde)
        out.append({"tur": tur, "metin": metin, "maddeler": maddeler})
    return out


# ------------------------------------------------------------------ rota


def rota_gecerli(rota: Any) -> bool:
    """İç rota: düz yol karakterleri ve `rotalar.json` kalıbına uyum (sorgu, şema, `..` yok)."""
    if not isinstance(rota, str) or not _ROTA.match(rota) or "//" in rota or ".." in rota:
        return False
    from tp_core.features.assistant.schemas import rota_indirge

    return rota_indirge(rota) is not None


# ------------------------------------------------------------------ doğrulayıcı


class Dogrulayici(Protocol):
    """Kaynak doğrulamasının dış okumaları (testler sahtesini verir)."""

    def urun_satirlari(self, yol: str, bas: int, son: int) -> list[str] | None:
        """MANIFEST'teki dosyanın [bas, son] satırları; dosya/satır yoksa None."""

    def uygulama_satirlari(self, yol: str) -> list[str] | None:
        """Test edilen uygulamanın dosyası (aynı sha); yoksa None."""

    def veri_sorgula(self, sql: str) -> Sequence[Sequence[Any]]:
        """`sqlguard`'dan geçmiş sorguyu yeniden çalıştırır; satırlar."""


class VarsayilanDogrulayici:
    """Üretim doğrulayıcısı: ürün bilgi paketi, test edilen uygulamanın forge'u, demo DB.

    Kurulumlar tembeldir (yalnız ilgili kaynak türü doğrulanırken).
    """

    def __init__(
        self,
        *,
        urun: Any = None,
        kod: Callable[[], Any] | None = None,
        db: Callable[[], Any] | None = None,
    ) -> None:
        self._urun = urun
        self._kod_kur = kod
        self._kod: Any = None
        self._db_kur = db
        self._db: Any = None
        self._dosyalar: dict[str, list[str] | None] = {}

    def urun_satirlari(self, yol: str, bas: int, son: int) -> list[str] | None:
        if self._urun is None:
            from tp_core.features.assistant.tools.product import UrunBilgisi

            self._urun = UrunBilgisi()
        try:
            cikti = self._urun.product_read({"path": yol, "start_line": bas, "end_line": son})
        except Exception:
            return None
        satirlar = str(cikti).splitlines()[1:]
        return [s.split("| ", 1)[1] if "| " in s else "" for s in satirlar]

    def uygulama_satirlari(self, yol: str) -> list[str] | None:
        if yol not in self._dosyalar:
            try:
                if self._kod is None:
                    from tp_core.features.assistant.tools import kod_araclari

                    self._kod = (self._kod_kur or kod_araclari)()
                self._dosyalar[yol] = self._kod.forge.read_file(yol, ref=self._kod.sha).splitlines()
            except Exception:
                self._dosyalar[yol] = None
        return self._dosyalar[yol]

    def veri_sorgula(self, sql: str) -> Sequence[Sequence[Any]]:
        from tp_core.features.requirements.sqlguard import validate_select

        if self._db is None:
            if self._db_kur is not None:
                self._db = self._db_kur()
            else:
                from tp_core.features.requirements import services

                self._db = services.demo_db()
        vq = validate_select(sql, kanit=True)
        return self._db.query(vq.sql).rows


# ------------------------------------------------------------------ bağlam


def _bilinmiyor(_anahtar: str) -> bool:
    return False


@dataclass
class SonIslemBaglami:
    """Son işlemin girdileri (işleyici kurar; testler doğrudan verir).

    - `havuz`, `oturum`: mesajın kanıt havuzu ve tek maskeleme oturumu.
    - `urune_ozgu`: §5.4 kararı (model araç çağrıları dahil, işleyici hesaplar).
    - `toparlama`: ajan toparlama nudge'ından sonra bitti.
    - `bilinen_anahtar`: Jira anahtarı Testing Probe'da kayıtlı mı.
    - `kayit_adresi` / `yeni_kayit_adresi` / `proje`: "Jira'yı aç" bağlantıları (yalnız sunucu).
    - `kural_basliklari`: öneri kipinde gösterilen kural önerilerinin başlıkları (mükerrer atma).
    - `bitis`, `saat`: veri sorgusu yeniden çalıştırmanın süre sınırı (`time.monotonic` ekseni).
    """

    havuz: KanitHavuzu | None = None
    oturum: MaskingSession | None = None
    urune_ozgu: bool = False
    toparlama: bool = False
    kip: str = "soru"
    dogrulayici: Dogrulayici | None = None
    bilinen_anahtar: Callable[[str], bool] = _bilinmiyor
    kayit_adresi: Callable[[str], str | None] | None = None
    yeni_kayit_adresi: str | None = None
    proje: str | None = None
    kural_basliklari: Iterable[str] = ()
    bitis: float | None = None
    saat: Callable[[], float] = time.monotonic
    musteri_verisi: bool = False
    sir_degerleri: tuple[str, ...] = ()
    rota_gecerli: Callable[[Any], bool] = rota_gecerli
    _anahtar_onbellek: dict[str, bool] = field(default_factory=dict, repr=False)

    def anahtar_bilinir(self, anahtar: Any) -> bool:
        if not isinstance(anahtar, str) or not JIRA_ANAHTARI.fullmatch(anahtar):
            return False
        if anahtar not in self._anahtar_onbellek:
            try:
                self._anahtar_onbellek[anahtar] = bool(self.bilinen_anahtar(anahtar))
            except Exception:
                self._anahtar_onbellek[anahtar] = False
        return self._anahtar_onbellek[anahtar]

    def adres(self, anahtar: str) -> str | None:
        if self.kayit_adresi is None:
            return None
        try:
            return self.kayit_adresi(anahtar)
        except Exception:
            return None


# ------------------------------------------------------------------ kaynak doğrulama


def _sha(metin: str) -> str:
    return hashlib.sha256(metin.encode("utf-8")).hexdigest()


def alinti_gecer(alinti: Any, satirlar: Sequence[str]) -> bool:
    """Boşluk normalize; çok kısa alıntı yalnız tam satırsa geçer (verifier deseni)."""
    if not isinstance(alinti, str):
        return False
    a = norm_ws(_SATIR_ONEKI.sub("", alinti))
    if not a:
        return False
    norm_satirlar = [norm_ws(s) for s in satirlar]
    if len(a) < ALINTI_EN_AZ:
        return a in norm_satirlar
    return a in " ".join(norm_satirlar) or any(a in s for s in norm_satirlar)


def _satir_ref(ref: Any) -> tuple[str, int, int] | None:
    if not isinstance(ref, str):
        return None
    m = _SATIR_REF.match(ref.strip())
    if m is None:
        return None
    bas = int(m.group("bas"))
    son = int(m.group("son") or bas)
    if bas < 1 or son < bas or son - bas >= URUN_SATIR_AZAMI:
        return None
    return m.group("yol"), bas, son


@dataclass
class _Sonuc:
    dogrulandi: bool
    sha256: str | None = None
    neden: str | None = None


class _KaynakDogrulayici:
    def __init__(self, b: SonIslemBaglami) -> None:
        self.b = b
        self.veri_sayisi = 0

    def __call__(self, tur: str, ref: str, alinti: Any) -> _Sonuc:
        try:
            if tur in ("urun_kodu", "dokuman"):
                return self._urun(ref, alinti)
            if tur == "uygulama_kodu":
                return self._uygulama(ref, alinti)
            if tur == "uygulama_verisi":
                return self._veri(ref)
            if tur in HAVUZ_TURLERI:
                return self._havuz(tur, ref, alinti)
        except Exception as exc:  # doğrulama hatası cevabı düşürmez
            # Kullanıcıya sabit metin; istisna adı yalnız kayda (§9, §10.2).
            log.debug("asistan kaynak doğrulanamadı: %s (%s)", tur, type(exc).__name__)
            return _Sonuc(False, neden="doğrulanamadı")
        return _Sonuc(False, neden="doğrulanmaz")

    def _urun(self, ref: str, alinti: Any) -> _Sonuc:
        parca = _satir_ref(ref)
        if parca is None or self.b.dogrulayici is None:
            return _Sonuc(False, neden="ref biçimi geçersiz" if parca is None else "doğrulanamadı")
        yol, bas, son = parca
        satirlar = self.b.dogrulayici.urun_satirlari(yol, bas, son)
        if not satirlar or len(satirlar) < son - bas + 1:
            return _Sonuc(False, neden="dosya ya da satır pakette yok")
        if not alinti_gecer(alinti, satirlar):
            return _Sonuc(False, _sha("\n".join(satirlar)), "alıntı satırda yok")
        return _Sonuc(True, _sha("\n".join(satirlar)))

    def _uygulama(self, ref: str, alinti: Any) -> _Sonuc:
        parca = _satir_ref(ref)
        if parca is None or self.b.dogrulayici is None:
            return _Sonuc(False, neden="ref biçimi geçersiz" if parca is None else "doğrulanamadı")
        yol, bas, son = parca
        dosya = self.b.dogrulayici.uygulama_satirlari(yol)
        if dosya is None or son > len(dosya):
            return _Sonuc(False, neden="dosya ya da satır yok")
        satirlar = dosya[bas - 1 : son]
        if not alinti_gecer(alinti, satirlar):
            return _Sonuc(False, _sha("\n".join(satirlar)), "alıntı satırda yok")
        return _Sonuc(True, _sha("\n".join(satirlar)))

    def _veri(self, ref: str) -> _Sonuc:
        kanit = self.b.havuz.al(ref, "uygulama_verisi") if self.b.havuz is not None else None
        if kanit is None or not kanit.sql or not kanit.result_digest:
            return _Sonuc(False, neden="kanıt yok")
        if self.b.dogrulayici is None:
            return _Sonuc(False, kanit.sha256, "doğrulanamadı")
        if self.veri_sayisi >= VERI_DOGRULAMA_AZAMI:
            return _Sonuc(False, kanit.sha256, "doğrulama sınırı (5 sorgu)")
        kalan = VERI_SORGU_UST_S
        if self.b.bitis is not None:
            kalan = min(kalan, self.b.bitis - self.b.saat())
        if kalan < VERI_EN_AZ_KALAN_S:
            return _Sonuc(False, kanit.sha256, "zaman aşımı")
        self.veri_sayisi += 1
        from tp_core.features.requirements.datatools import digest_matches_any

        havuz = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asistan-dogrula")
        try:
            gelecek = havuz.submit(self.b.dogrulayici.veri_sorgula, kanit.sql)
            satirlar = gelecek.result(timeout=kalan)
        except FutureTimeout:
            return _Sonuc(False, kanit.sha256, "zaman aşımı")
        finally:
            havuz.shutdown(wait=False, cancel_futures=True)
        if not digest_matches_any(kanit.result_digest, satirlar):
            return _Sonuc(False, kanit.sha256, "sonuç özeti eşleşmiyor")
        return _Sonuc(True, kanit.sha256)

    def _havuz(self, tur: str, ref: str, alinti: Any) -> _Sonuc:
        kanit = self.b.havuz.al(ref, tur) if self.b.havuz is not None else None
        if kanit is None:
            return _Sonuc(False, neden="kanıt yok ya da türü uyuşmuyor")
        acik = kanit.metin
        if self.b.oturum is not None:
            acik = str(self.b.oturum.unmask(kanit.metin))
        metinler = [acik] if acik == kanit.metin else [acik, kanit.metin]
        if not any(alinti_gecer(alinti, [*m.splitlines(), m]) for m in metinler):
            return _Sonuc(False, kanit.sha256, "alıntı kanıtta yok")
        return _Sonuc(True, kanit.sha256)


def _kaynaklar(
    ham: Any, b: SonIslemBaglami
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    dogrula = _KaynakDogrulayici(b)
    out: list[dict[str, Any]] = []
    dogrulama: dict[str, dict[str, Any]] = {}
    for k in (ham if isinstance(ham, list) else [])[:KAYNAK_AZAMI]:
        if not isinstance(k, Mapping):
            continue
        tur = k.get("tur") if k.get("tur") in KAYNAK_TURLERI else "genel_bilgi"
        ref = k.get("ref") if isinstance(k.get("ref"), str) else ""
        ref = ref.strip()[:300]
        alinti = k.get("alinti") if isinstance(k.get("alinti"), str) else ""
        kayit: dict[str, Any] = {
            "tur": tur,
            "ref": duz_metin(ref) if tur == "genel_bilgi" else ref,
            "alinti": kirp(duz_metin(alinti), ALINTI_AZAMI),
            "dogrulandi": False,
        }
        if tur != "genel_bilgi":
            sonuc = dogrula(tur, ref, alinti)
            kayit["dogrulandi"] = sonuc.dogrulandi
            if sonuc.neden and not sonuc.dogrulandi:
                kayit["neden"] = sonuc.neden
            onceki = dogrulama.get(ref)
            if onceki is None or (sonuc.dogrulandi and not onceki["dogrulandi"]):
                dogrulama[ref] = {"dogrulandi": sonuc.dogrulandi, "sha256": sonuc.sha256}
            ek = _kaynak_eki(tur, ref, b)
            if ek:
                kayit.update(ek)
        out.append(kayit)
    return out, dogrulama


def _kaynak_eki(tur: str, ref: str, b: SonIslemBaglami) -> dict[str, Any]:
    """Jira/CI kaynağının sunucu tarafı ayrıntısı (havuz meta'sından; modelden değil)."""
    if b.havuz is None or tur not in ("jira", "ci_log"):
        return {}
    kanit = b.havuz.al(ref, tur)
    if kanit is None:
        return {}
    if tur == "jira":
        anahtar = kanit.meta.get("anahtar")
        if not b.anahtar_bilinir(anahtar):
            return {}
        return {"jira": {"anahtar": anahtar, "url": b.adres(anahtar)}}
    run_id = kanit.meta.get("run_id")
    return {"ci": {"run_id": str(run_id)}} if run_id else {}


# ------------------------------------------------------------------ bağlantılar


def _yonlendirmeler(ham: Any, b: SonIslemBaglami) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    gorulen: set[str] = set()
    for y in ham if isinstance(ham, list) else []:
        if len(out) >= YONLENDIRME_AZAMI:
            break
        if not isinstance(y, Mapping):
            continue
        rota = y.get("rota")
        if not isinstance(rota, str) or rota in gorulen or not b.rota_gecerli(rota):
            continue
        gorulen.add(rota)
        etiket = kirp(duz_metin(y.get("etiket")), ETIKET_AZAMI) or "Ekrana git"
        out.append({"etiket": etiket, "rota": rota})
    return out


def _jira(ham: Any, b: SonIslemBaglami) -> tuple[list[str], list[dict[str, str]]]:
    anahtarlar: list[str] = []
    for a in ham if isinstance(ham, list) else []:
        if len(anahtarlar) >= JIRA_ANAHTAR_AZAMI:
            break
        if isinstance(a, str) and a not in anahtarlar and b.anahtar_bilinir(a):
            anahtarlar.append(a)
    baglantilar = []
    for a in anahtarlar:
        url = b.adres(a)
        if url:
            baglantilar.append({"anahtar": a, "url": url})
    return anahtarlar, baglantilar


# ------------------------------------------------------------------ öneriler


def _bilgi() -> dict[str, Any]:
    return {"tur": "bilgi", "rota": None, "anahtar": None, "taslak": None}


def _taslak(ham: Any, tur: str, proje: str | None) -> dict[str, Any]:
    ham = ham if isinstance(ham, Mapping) else {}
    return {
        "tur": tur,
        "ozet": kirp(taslak_metni(ham.get("ozet")), TASLAK_OZET_AZAMI),
        "aciklama": kirp(taslak_metni(ham.get("aciklama")), TASLAK_ACIKLAMA_AZAMI),
        "proje": proje,
    }


def oneri_eylemi(ham: Any, b: SonIslemBaglami) -> dict[str, Any]:
    """Tek eylem sözleşmesi (§7.2) + §7.3 düşürme kuralları; bağlantıyı yalnız sunucu kurar."""
    if not isinstance(ham, Mapping) or ham.get("tur") not in EYLEM_TURLERI:
        return _bilgi()
    tur = ham["tur"]
    if tur == "rota":
        rota = ham.get("rota")
        if not b.rota_gecerli(rota):
            return _bilgi()
        return {"tur": "rota", "rota": rota, "anahtar": None, "taslak": None}
    anahtar = ham.get("anahtar") if b.anahtar_bilinir(ham.get("anahtar")) else None
    taslak_ham = ham.get("taslak") if isinstance(ham.get("taslak"), Mapping) else None
    if tur == "jira_taslak":
        taslak_turu = taslak_ham.get("tur") if taslak_ham else None
        if taslak_turu not in YENI_KAYIT_TURLERI:
            return _bilgi()
        out = {
            "tur": tur,
            "rota": None,
            "anahtar": anahtar,
            "taslak": _taslak(taslak_ham, str(taslak_turu), b.proje),
        }
        if b.yeni_kayit_adresi:
            out["baglanti"] = b.yeni_kayit_adresi
        return out
    if tur == "bilgi" or anahtar is None:
        return _bilgi()
    if tur == "jira_yorum":
        if taslak_ham is None:
            return _bilgi()
        out = {
            "tur": tur,
            "rota": None,
            "anahtar": anahtar,
            "taslak": _taslak(taslak_ham, "yorum", b.proje),
        }
    else:  # jira_kaydi
        out = {"tur": tur, "rota": None, "anahtar": anahtar, "taslak": None}
    baglanti = b.adres(anahtar)
    if baglanti:
        out["baglanti"] = baglanti
    return out


def _baslik_anahtari(baslik: str) -> str:
    """Mükerrer başlık karşılaştırması: normalize + sondaki noktalama yok sayılır."""
    return normalize(baslik).rstrip(" .…!?")


def _oneriler(ham: Any, b: SonIslemBaglami) -> list[dict[str, Any]]:
    if b.kip != "oneri":
        return []
    gorulen = {_baslik_anahtari(t) for t in b.kural_basliklari if isinstance(t, str)}
    out: list[dict[str, Any]] = []
    for o in ham if isinstance(ham, list) else []:
        if len(out) >= ONERI_AZAMI:
            break
        if not isinstance(o, Mapping):
            continue
        baslik = kirp(taslak_metni(o.get("baslik")), ONERI_BASLIK_AZAMI)
        anahtar = _baslik_anahtari(baslik)
        if not baslik or anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        out.append(
            {
                "baslik": baslik,
                "neden": kirp(taslak_metni(o.get("neden")), ONERI_NEDEN_AZAMI),
                "eylem": oneri_eylemi(o.get("eylem"), b),
            }
        )
    return out


# ------------------------------------------------------------------ güven


def guven_gosterimi(
    guven: Any,
    kaynaklar: Sequence[Mapping[str, Any]],
    *,
    urune_ozgu: bool,
    toparlama: bool,
) -> str:
    """§7.3 tablosu."""
    if toparlama:
        return EMIN_DEGIL
    dogrulanmis = sum(1 for k in kaynaklar if k.get("dogrulandi") and k["tur"] != "genel_bilgi")
    if dogrulanmis:
        return DOGRULANDI if guven in ("yuksek", "orta") else KISMEN
    urun_kaynagi = any(k["tur"] != "genel_bilgi" for k in kaynaklar)
    genel = any(k["tur"] == "genel_bilgi" for k in kaynaklar)
    if urune_ozgu:
        return KISMEN if genel and not urun_kaynagi else EMIN_DEGIL
    return EMIN_DEGIL if urun_kaynagi else GENEL_BILGI


# ------------------------------------------------------------------ giriş noktası


def _sir_temizle_tum(deger: Any, sirlar: tuple[str, ...]) -> Any:
    if isinstance(deger, str):
        return sir_temizle(deger, sirlar)
    if isinstance(deger, list):
        return [_sir_temizle_tum(v, sirlar) for v in deger]
    if isinstance(deger, dict):
        return {k: _sir_temizle_tum(v, sirlar) for k, v in deger.items()}
    return deger


def isle(cikti: Any, b: SonIslemBaglami) -> dict[str, Any]:
    """Model çıktısı → saklanan cevap. Çıktı şemaya uymasa da (savunma) çökmez."""
    cikti = cikti if isinstance(cikti, Mapping) else {}
    out = bos_cevap()
    out["cevap_bloklari"] = _bloklar(cikti.get("cevap_bloklari"))
    guven = cikti.get("guven") if cikti.get("guven") in ("yuksek", "orta", "dusuk") else "dusuk"
    out["guven"] = guven
    out["kaynaklar"], out["dogrulama"] = _kaynaklar(cikti.get("kaynaklar"), b)
    out["yonlendirmeler"] = _yonlendirmeler(cikti.get("yonlendirmeler"), b)
    out["jira_anahtarlari"], out["jira_baglantilari"] = _jira(cikti.get("jira_anahtarlari"), b)
    out["eylem_reddi"] = cikti.get("eylem_reddi") is True
    out["oneriler"] = _oneriler(cikti.get("oneriler"), b)
    out["urune_ozgu"] = bool(b.urune_ozgu)
    out["toparlama"] = bool(b.toparlama)
    out["guven_gosterimi"] = guven_gosterimi(
        guven, out["kaynaklar"], urune_ozgu=b.urune_ozgu, toparlama=b.toparlama
    )
    if (
        b.urune_ozgu
        and out["kaynaklar"]
        and all(k["tur"] == "genel_bilgi" for k in out["kaynaklar"])
    ):
        out["notlar"].append(NOT_URUN_KAYNAGI_YOK)
    if b.toparlama:
        out["notlar"].append(NOT_TOPARLAMA)
    out = _sir_temizle_tum(out, b.sir_degerleri)
    if b.musteri_verisi and b.oturum is not None:
        out, _ = b.oturum.mask(out)
    return out
