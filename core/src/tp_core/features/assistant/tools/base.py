"""Asistan araçlarının ortak tipleri ve sarmalayıcısı (AI-ASISTAN-PLANI §5.0).

Araç sözleşmesi (yeni araçlar: `probe_*`, `jira_issue`, `ci_log`)::

    def arac(baglam: AracBaglami, **arg) -> AracSonucu

- Araç **ham** metin döndürür (maskesiz, sarılmamış). Sır temizleme, maskeleme, kanıt havuzu ve
  `<untrusted>` sarma `AracSarmalayici`'dadır; araç bunları kendisi yapmaz.
- Rol/kullanıcı yalnızca `baglam`'dan okunur, asla argümandan.
- Modele gösterilebilir hata için `AracHatasi` fırlatılır (mesajı modele gider; ayrıntı/sır
  taşımamalı). Başka her istisna sınıf adıyla "araç çalıştırılamadı" olur; `str(exc)` ne modele ne
  kayda yazılır.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.orm import Session

from tp_core.gateway.masking import (
    PLACEHOLDER_RE,
    MaskingSession,
    scrub_secret_patterns,
    scrub_secrets,
)
from tp_core.gateway.untrusted import UntrustedKind, wrap_untrusted

# §7.2 `kaynaklar[].tur` değerlerinden kanıt havuzuna giren türler.
KanitTuru = Literal[
    "probe_verisi", "jira", "ci_log", "uygulama_verisi", "uygulama_kodu", "urun_kodu"
]


class AracHatasi(RuntimeError):
    """Modele araç hatası olarak dönen, ayrıntı sızdırmayan hata (mesajı güvenli olmalı)."""


@dataclass(frozen=True)
class AracSonucu:
    """Yeni araçların dönüşü.

    - `metin`: ham sonuç (sarmalayıcı sır temizler, maskeler, sarar).
    - `kanit_turu`: §7.2 kaynak türü; §7.3 doğrulaması `ref=kN`'in türünü bununla eşler.
    - `tur`: `<untrusted kind=…>` (probe → `data`, jira → `jira`, ci_log → `ci_log`).
    - `kaynak`: sarma bloğunun kaynak bağlamı (ör. Jira anahtarı, koşu kimliği); sır içermemeli.
    - `meta`: kanıt havuzuna eklenen, sır/PII içermeyen küçük alanlar (ör. `{"anahtar": "TPD-3"}`).
    """

    metin: str
    kanit_turu: KanitTuru = "probe_verisi"
    tur: UntrustedKind = "data"
    kaynak: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class AracBaglami:
    """Mesaj başına araç bağlamı (iş yükünden; modelden asla).

    - `kullanici_id`, `rol`: çağıran (oturumdan). Rol kısıtları bununla uygulanır.
    - `oturum`: mesajın tek maskeleme oturumu (geçide ve `DataTools`'a verilen oturumun aynısı).
    - `db`: kısa ömürlü SQLAlchemy oturumu açan fabrika (`with baglam.db() as s:`).
    - `bitis`: mutlak son an (`time.monotonic()` ekseninde); `None` → süre sınırı yok.
    - `sir_degerleri`: çalışma anı sır değerleri (`known_secret_values()`; ≥ 8 karakter).
    - `durum`: mesaj boyunca araçlar arası sayaçlar (ör. `durum["jira_anahtarlari"]`); araç kendi
      ad alanı anahtarını kullanır.
    """

    kullanici_id: UUID
    rol: str
    oturum: MaskingSession
    db: Callable[[], Session]
    bitis: float | None = None
    sir_degerleri: tuple[str, ...] = ()
    durum: dict[str, Any] = field(default_factory=dict)

    def kalan_s(self) -> float:
        """Kalan süre (sn); sınırsızsa `inf`, dolduysa 0."""
        if self.bitis is None:
            return float("inf")
        return max(0.0, self.bitis - time.monotonic())


Arac = Callable[..., AracSonucu]
"""Yeni araç: `arac(baglam, **arg) -> AracSonucu`."""

MevcutArac = Callable[[dict[str, Any]], str]
"""Mevcut araç (`CodeTools`/`DataTools` metodu): kendisi sarar (`DataTools` ayrıca maskeler)."""

KANIT_ONEKI = "[kanit:{kimlik}]"
HATA_METNI_UST = 300


# ------------------------------------------------------------------ kanıt havuzu


@dataclass(frozen=True)
class Kanit:
    """Bir araç çağrısının kanıt kaydı (iş belleği; kalıcı değil).

    `metin` modele giden metindir (sır temizlenmiş, maskeli, sarılmış); ham (maskesiz) sonuç
    hiçbir alanda tutulmaz. §7.3 alıntı doğrulaması `oturum.unmask(metin)` üzerinde yalnız
    bellekte yapılır.
    """

    kimlik: str
    arac: str
    tur: KanitTuru
    metin: str
    sha256: str
    sql: str | None = None
    result_digest: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)


class KanitHavuzu:
    """Mesaj başına kanıt havuzu: `k1`, `k2`, … (§5.0)."""

    def __init__(self) -> None:
        self._kayitlar: dict[str, Kanit] = {}

    def ekle(
        self,
        arac: str,
        tur: KanitTuru,
        metin_govdesi: Callable[[str], str],
        *,
        sql: str | None = None,
        result_digest: str | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> Kanit:
        """Yeni kimlik ayırır; `metin_govdesi(kimlik)` modele gidecek tam metni üretir."""
        kimlik = f"k{len(self._kayitlar) + 1}"
        metin = metin_govdesi(kimlik)
        kanit = Kanit(
            kimlik=kimlik,
            arac=arac,
            tur=tur,
            metin=metin,
            sha256=hashlib.sha256(metin.encode("utf-8")).hexdigest(),
            sql=sql,
            result_digest=result_digest,
            meta=dict(meta or {}),
        )
        self._kayitlar[kimlik] = kanit
        return kanit

    def al(self, kimlik: str, tur: str | None = None) -> Kanit | None:
        """Kimliğin kaydı; `tur` verilirse türü uyuşmayan kimlik yok sayılır (§7.3)."""
        kanit = self._kayitlar.get((kimlik or "").strip())
        if kanit is None or (tur is not None and kanit.tur != tur):
            return None
        return kanit

    def __iter__(self) -> Iterator[Kanit]:
        return iter(list(self._kayitlar.values()))

    def __len__(self) -> int:
        return len(self._kayitlar)

    def temizle(self) -> None:
        self._kayitlar.clear()


# ------------------------------------------------------------------ sarmalayıcı


def sir_temizle(metin: str, sir_degerleri: Iterable[str] = ()) -> str:
    """Biçimden tanınan sırlar + çalışma anı sır değerleri (`scrub_secret_patterns`), ardından
    kısa bilinen değerler (eski demo parolası; `known_secret_values` yalnız onu < 8 bırakır)."""
    degerler = [v for v in sir_degerleri if isinstance(v, str) and v]
    metin = scrub_secret_patterns(metin, degerler)
    return scrub_secrets(metin, degerler)


def kesik_temizle(parca: str) -> str:
    """Kırpılan parçayı kırpma işareti eklenmeden ÖNCE temizler: parça `\\Z` ile bitiyorken
    `scrub_secret_patterns`'ın kesme sınırı koruması (yarım token, bilinen değerin öneki) devreye
    girer; işaret eklendikten sonra yapılan temizlik yarım token'ı düz bırakırdı."""
    from tp_core.gateway.factory import known_secret_values

    return scrub_secret_patterns(parca, known_secret_values())


def _db_query_ozeti(metin: str) -> tuple[str | None, str | None]:
    """`DataTools.db_query` çıktısının başındaki `query:` ve `result_digest:` satırları."""
    if not metin.startswith("query: "):
        return None, None
    ayrac = "\nresult_digest: "
    i = metin.find(ayrac)
    if i < 0:
        return None, None
    sql = metin[len("query: ") : i]
    kalan = metin[i + len(ayrac) :]
    digest = kalan.split("\n", 1)[0].strip()
    return sql, digest or None


def _yer_tutucu_notr(metin: str) -> str:
    """Maskelenmemiş kod çıktısındaki hazır `<<PII_…>>` dizgisini etkisizleştirir (`mask_text`'in
    yaptığı gibi `<<` → `< <`); geçit son çıktıyı açarken oturumdaki gerçek değeri koymasın.
    İkinci maskeleme değildir: veri araçlarının (`DataTools`) oturumla maskeli yer tutucusuna
    dokunulmaz (§12)."""
    return PLACEHOLDER_RE.sub(lambda m: m.group(0).replace("<<", "< <", 1), metin)


class AracSarmalayici:
    """Geçide verilen `ToolExecutor` (`execute(name, args) -> str`).

    - Yeni araçlar: sonuç → sır temizleme → `oturum.mask_text` → kanıt havuzu → `<untrusted>`.
    - Mevcut araçlar (`mevcut`): yalnız sır temizleme + kanıt havuzu; zaten sarılı (ve `DataTools`
      maskeli) sonuca ikinci maske/sarma uygulanmaz.
    - Modele giden her başarılı sonuç `[kanit:kN]` ile başlar.
    - Hata: `AracHatasi` (mesajı temizlenip maskelenmiş) yükseltilir; geçit bunu araç hatası olarak
      modele iletir. Beklenmeyen istisnanın `str(exc)`'i hiçbir yere yazılmaz.
    """

    def __init__(
        self,
        baglam: AracBaglami,
        *,
        yeni: Mapping[str, Arac] | None = None,
        mevcut: Mapping[str, MevcutArac] | None = None,
        mevcut_turleri: Mapping[str, KanitTuru] | None = None,
        guvenli_hatalar: tuple[type[BaseException], ...] = (),
        havuz: KanitHavuzu | None = None,
    ) -> None:
        self.baglam = baglam
        self.yeni: dict[str, Arac] = dict(yeni or {})
        self.mevcut: dict[str, MevcutArac] = dict(mevcut or {})
        self.mevcut_turleri: dict[str, KanitTuru] = dict(mevcut_turleri or {})
        # Mesajı modele gösterilebilen araç hataları (ör. ProductToolError, DataToolError).
        self.guvenli_hatalar = (AracHatasi, *guvenli_hatalar)
        self.havuz = havuz if havuz is not None else KanitHavuzu()
        cakisan = set(self.yeni) & set(self.mevcut)
        if cakisan:
            raise ValueError(f"araç iki kez tanımlı: {sorted(cakisan)}")

    @property
    def adlar(self) -> frozenset[str]:
        return frozenset(self.yeni) | frozenset(self.mevcut)

    def __call__(self, name: str, args: dict[str, Any]) -> str:
        args = args if isinstance(args, dict) else {}
        if name in self.yeni:
            return self._yeni(name, args)
        if name in self.mevcut:
            return self._mevcut(name, args)
        raise AracHatasi(f"bilinmeyen araç: {name[:60]}")

    # ------------------------------------------------------------ iç

    def _temiz(self, metin: str) -> str:
        return sir_temizle(metin, self.baglam.sir_degerleri)

    def _hata(self, exc: BaseException) -> AracHatasi:
        if isinstance(exc, self.guvenli_hatalar):
            mesaj = str(exc).strip() or type(exc).__name__
            mesaj, _ = self.baglam.oturum.mask_text(self._temiz(mesaj[:HATA_METNI_UST]))
            return AracHatasi(mesaj)
        return AracHatasi(f"araç çalıştırılamadı ({type(exc).__name__})")

    def _yeni(self, name: str, args: dict[str, Any]) -> str:
        try:
            sonuc = self.yeni[name](self.baglam, **{str(k): v for k, v in args.items()})
        except Exception as exc:
            raise self._hata(exc) from None
        if not isinstance(sonuc, AracSonucu):
            raise AracHatasi(f"araç çalıştırılamadı ({type(sonuc).__name__})")
        maskeli, _ = self.baglam.oturum.mask_text(self._temiz(sonuc.metin or ""))
        kaynak = f"tool:{name}" + (f":{sonuc.kaynak}" if sonuc.kaynak else "")

        def govde(kimlik: str) -> str:
            blok = wrap_untrusted(maskeli, source=f"{kaynak}:{kimlik}", kind=sonuc.tur)
            return f"{KANIT_ONEKI.format(kimlik=kimlik)}\n{blok}"

        return self.havuz.ekle(name, sonuc.kanit_turu, govde, meta=sonuc.meta).metin

    def _mevcut(self, name: str, args: dict[str, Any]) -> str:
        try:
            ham = self.mevcut[name](args)
        except Exception as exc:
            raise self._hata(exc) from None
        temiz = self._temiz(str(ham))
        sql, digest = _db_query_ozeti(temiz) if name == "db_query" else (None, None)
        tur = self.mevcut_turleri.get(name, "uygulama_kodu")
        if tur == "uygulama_kodu":
            temiz = _yer_tutucu_notr(temiz)
        return self.havuz.ekle(
            name,
            tur,
            lambda kimlik: f"{KANIT_ONEKI.format(kimlik=kimlik)}\n{temiz}",
            sql=sql,
            result_digest=digest,
        ).metin
