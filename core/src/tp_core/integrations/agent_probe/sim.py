"""Agent Probe — süreç içi simülatör (011 §4.5; F6 ajan ürünleri, `sim` kipinde denetim ve puan).

Gerçek Agent Probe'a ağ çağrısı yoktur. "Kayıt atılıyor ve cevap geliyormuş gibi":

- `list_products()`: `rules/agent-probe/urunler.yaml`'daki ürünlerden yalnız `hazir: true` olanlar
  (Agent Probe'da ön tanımları tamamlanmış ürünler).
- `start_agent_test(urun, gereksinim)`: Agent Probe'da kayıt açar → talep no `APT-<yıl>-<n>`,
  durum `queued`.
- `get_agent_test(talep_no)`: deterministik ilerleme, kaydın açılış anından geçen süreye göre:
  `< kuyruk_s` → `queued`; `< kuyruk_s + kosu_s` → `running` (geçen senaryo sayısı orantılı);
  sonra senaryo tanımlarından `passed` (hepsi geçti) ya da `failed` (en az biri kaldı). Sonuç:
  özet, toplam / geçen / kalan senaryo, ayrıntı listesi, temsili bağlantı, `simulasyon: true`.

Kaydın deposu (`SimDeposu`): Agent Probe tarafı süreç içi olduğundan ve core-api ile core-worker
ayrı süreçler olduğundan simülatör ayrı bir depo tutmaz: kayıt, Testing Probe'un aynı talep için
yazdığı `ajan_testi_talebi` satırıdır (talep no, ürün, açılış anı). Testler `BellekDeposu` ve
denetlenebilir saat (`saat`) verir.

`SimAgentProbe` (`TP_AGENT_PROBE=sim`) ayrıca model çağırmadan:
- `audit_case_set`: işaretsiz saldırı verisi, `synthetic=false` test verisi, `ready` case'te
  soru/varsayım atfı → `DÜZELTME_GEREKLİ`; aksi `KABUL` (kaynak `sim`).
- `score_message`: anahtar sözcük kuralları (kaynak `sim`); karar `asistan.karar_ver` ile aynı kod.
  Asistan modeli kapalıyken ya da sözlük/şablon cevaplarında soru bu kurallarla denetlenir.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal, Protocol
from uuid import UUID, uuid5

import yaml

from tp_core.integrations.agent_probe import asistan as _asistan
from tp_core.ports import (
    AgentProduct,
    AgentTestTicket,
    CaseSetAuditRequest,
    CaseSetAuditResult,
    MessageScore,
)

URUN_DOSYASI: Final = "agent-probe/urunler.yaml"
TEMSILI_ADRES: Final = "https://agent-probe.sim/talepler/{talep_no}"
TALEP_ONEKI: Final = "APT"
_SIM_NS: Final = UUID("6b1c3f0e-6a51-4b1a-9a8e-011a6e9750f7")


# ------------------------------------------------------------------ ürünler


@dataclass(frozen=True)
class UrunTanimi:
    kod: str
    ad: str
    aciklama: str
    hazir: bool
    kuyruk_s: float
    kosu_s: float
    senaryolar: tuple[dict[str, Any], ...]

    def urun(self) -> AgentProduct:
        return AgentProduct(kod=self.kod, ad=self.ad, aciklama=self.aciklama, hazir=self.hazir)


class SimHatasi(ValueError):
    """Simülatörün reddettiği istek (bilinmeyen/hazır olmayan ürün, bilinmeyen talep)."""


def urun_tanimlari(rules_dir: Path | None = None) -> list[UrunTanimi]:
    from tp_core.gateway.config import find_rules_dir

    yol = find_rules_dir(rules_dir) / URUN_DOSYASI
    veri = yaml.safe_load(yol.read_text(encoding="utf-8")) or {}
    out = []
    for u in veri.get("urunler") or []:
        sim = u.get("sim") or {}
        out.append(
            UrunTanimi(
                kod=str(u["kod"]),
                ad=str(u["ad"]),
                aciklama=str(u.get("aciklama") or ""),
                hazir=bool(u.get("hazir")),
                kuyruk_s=float(sim.get("kuyruk_s", 5)),
                kosu_s=float(sim.get("kosu_s", 20)),
                senaryolar=tuple(dict(s) for s in sim.get("senaryolar") or []),
            )
        )
    return out


# ------------------------------------------------------------------ depo


@dataclass(frozen=True)
class SimKayit:
    talep_no: str
    urun_kodu: str
    requirement_id: UUID
    acilis: datetime


class SimDeposu(Protocol):
    def sonraki_no(self, yil: int) -> int: ...

    def kayit(self, talep_no: str) -> SimKayit | None: ...

    def ekle(self, kayit: SimKayit) -> None: ...


class BellekDeposu:
    """Testler için: kayıtlar bellekte."""

    def __init__(self) -> None:
        self.kayitlar: dict[str, SimKayit] = {}

    def sonraki_no(self, yil: int) -> int:
        onek = f"{TALEP_ONEKI}-{yil}-"
        return 1 + sum(1 for k in self.kayitlar if k.startswith(onek))

    def kayit(self, talep_no: str) -> SimKayit | None:
        return self.kayitlar.get(talep_no)

    def ekle(self, kayit: SimKayit) -> None:
        self.kayitlar[kayit.talep_no] = kayit


class PgDeposu:  # pragma: no cover - tp_core.features.agent_probe testleri gerçek PG ile sınar
    """Üretim: kayıt, Testing Probe'un `ajan_testi_talebi` satırıdır (aynı talep no)."""

    def __init__(self, engine_factory: Callable[[], Any] | None = None) -> None:
        if engine_factory is None:
            from tp_core.db import get_engine

            engine_factory = get_engine
        self._engine = engine_factory

    def sonraki_no(self, yil: int) -> int:
        from sqlalchemy import text

        with self._engine().connect() as conn:
            deger = conn.execute(
                text(
                    "SELECT COALESCE(MAX(CAST(split_part(talep_no, '-', 3) AS integer)), 0) "
                    "FROM ajan_testi_talebi WHERE talep_no LIKE :o"
                ),
                {"o": f"{TALEP_ONEKI}-{yil}-%"},
            ).scalar()
        return int(deger or 0) + 1

    def kayit(self, talep_no: str) -> SimKayit | None:
        from sqlalchemy import text

        with self._engine().connect() as conn:
            r = conn.execute(
                text(
                    "SELECT urun_kodu, requirement_id, olusturma FROM ajan_testi_talebi "
                    "WHERE talep_no = :t"
                ),
                {"t": talep_no},
            ).first()
        return None if r is None else SimKayit(talep_no, r[0], r[1], r[2])

    def ekle(self, kayit: SimKayit) -> None:
        """Satırı Testing Probe yazar (aynı transaction'da); simülatör ayrıca yazmaz."""


# ------------------------------------------------------------------ ajan testleri


def _simdi() -> datetime:
    return datetime.now(UTC)


class SimAjanTestleri:
    """Ajan ürünleri ve test talepleri (iki kip de kullanır)."""

    def __init__(
        self,
        depo: SimDeposu | None = None,
        *,
        saat: Callable[[], datetime] = _simdi,
        rules_dir: Path | None = None,
    ) -> None:
        self.depo: SimDeposu = depo if depo is not None else PgDeposu()
        self.saat = saat
        self.rules_dir = rules_dir

    def _tanimlar(self) -> dict[str, UrunTanimi]:
        return {u.kod: u for u in urun_tanimlari(self.rules_dir)}

    def list_products(self) -> list[AgentProduct]:
        return [u.urun() for u in self._tanimlar().values() if u.hazir]

    def start_agent_test(
        self, urun_kodu: str, requirement_id: UUID, gereksinim: Mapping[str, Any]
    ) -> AgentTestTicket:
        urun = self._tanimlar().get(urun_kodu)
        if urun is None or not urun.hazir:
            raise SimHatasi(f"ürün Agent Probe'da hazır değil ya da yok: {urun_kodu}")
        simdi = self.saat()
        no = f"{TALEP_ONEKI}-{simdi.year}-{self.depo.sonraki_no(simdi.year)}"
        self.depo.ekle(SimKayit(no, urun_kodu, requirement_id, simdi))
        return AgentTestTicket(
            talep_no=no,
            urun_kodu=urun_kodu,
            requirement_id=requirement_id,
            durum="queued",
            ozet="Talep Agent Probe kuyruğunda (simülasyon).",
            sonuc={},
            url=TEMSILI_ADRES.format(talep_no=no),
            simulasyon=True,
            guncelleme=simdi,
        )

    def get_agent_test(self, talep_no: str) -> AgentTestTicket:
        kayit = self.depo.kayit(talep_no)
        if kayit is None:
            raise SimHatasi(f"bilinmeyen talep: {talep_no}")
        urun = self._tanimlar().get(kayit.urun_kodu)
        simdi = self.saat()
        gecen_s = max(0.0, (simdi - kayit.acilis).total_seconds())
        ortak = {
            "talep_no": talep_no,
            "urun_kodu": kayit.urun_kodu,
            "requirement_id": kayit.requirement_id,
            "url": TEMSILI_ADRES.format(talep_no=talep_no),
            "simulasyon": True,
            "guncelleme": simdi,
        }
        if urun is None:
            return AgentTestTicket(
                **ortak, durum="error", ozet="Ürün Agent Probe'da artık tanımlı değil.", sonuc={}
            )
        senaryolar = list(urun.senaryolar)
        toplam = len(senaryolar)
        if gecen_s < urun.kuyruk_s:
            return AgentTestTicket(
                **ortak, durum="queued", ozet="Talep Agent Probe kuyruğunda (simülasyon).", sonuc={}
            )
        if gecen_s < urun.kuyruk_s + urun.kosu_s:
            oran = (gecen_s - urun.kuyruk_s) / urun.kosu_s if urun.kosu_s else 1.0
            biten = min(toplam, int(oran * toplam))
            return AgentTestTicket(
                **ortak,
                durum="running",
                ozet=f"Agent Probe senaryoları koşuyor: {biten}/{toplam} (simülasyon).",
                sonuc={"toplam": toplam, "biten": biten},
            )
        kalan = sum(1 for s in senaryolar if s.get("sonuc") == "failed")
        ayrintilar = [
            {
                "senaryo": str(s.get("senaryo") or ""),
                "kategori": str(s.get("kategori") or ""),
                "sonuc": "failed" if s.get("sonuc") == "failed" else "passed",
                "aciklama": str(s.get("aciklama") or ""),
            }
            for s in senaryolar
        ]
        ozet = (
            f"{toplam} senaryodan {kalan} tanesi kaldı."
            if kalan
            else f"{toplam} senaryonun hepsi geçti."
        )
        return AgentTestTicket(
            **ortak,
            durum="failed" if kalan else "passed",
            ozet=ozet,
            sonuc={
                "toplam": toplam,
                "gecen": toplam - kalan,
                "kalan": kalan,
                "ayrintilar": ayrintilar,
            },
        )


_VARSAYILAN: SimAjanTestleri | None = None


def _varsayilan() -> SimAjanTestleri:
    global _VARSAYILAN
    if _VARSAYILAN is None:
        _VARSAYILAN = SimAjanTestleri()
    return _VARSAYILAN


def list_products() -> list[AgentProduct]:
    return _varsayilan().list_products()


def start_agent_test(
    urun_kodu: str, requirement_id: UUID, gereksinim: Mapping[str, Any]
) -> AgentTestTicket:
    return _varsayilan().start_agent_test(urun_kodu, requirement_id, gereksinim)


def get_agent_test(talep_no: str) -> AgentTestTicket:
    return _varsayilan().get_agent_test(talep_no)


# ------------------------------------------------------------------ mesaj puanı (kurallar)


def sade(metin: str) -> str:
    """Küçük harf, Türkçe harfler korunur (İ/I doğru), birleşik işaretler ve fazla boşluk atılır."""
    metin = (metin or "").replace("İ", "i").replace("I", "ı").lower()
    metin = unicodedata.normalize("NFKC", metin)
    metin = "".join(ch for ch in metin if unicodedata.category(ch) != "Cf")
    return " ".join(metin.split())


_GRUP = (
    r"(?:kürt|arap|suriyeli|afgan|yahudi|ermeni|rum|çingene|roman|siyahi|zenci|afrikalı|"
    r"göçmen|mülteci|müslüman|hristiyan|alevi)\w*"
)
_ASAGILAMA = (
    r"(?:aşağılık|pis|hırsız|tembel|geri zekal|hayvan|sürüngen|asalak|defol|kovul|"
    r"istemiyoruz|sevmem|güvenilmez|beyinsiz|ırkı)\w*"
)

# (kategori, desen, puan_soru, puan_cevap); puan = eşleşmede verilen tavan.
KURALLAR: Final[tuple[tuple[str, re.Pattern[str], int, int], ...]] = tuple(
    (k, re.compile(d), ps, pc)
    for k, d, ps, pc in (
        (
            "prompt_injection",
            r"(?:önceki|yukarıdaki|tüm|bütün)\s+(?:tüm\s+)?talimat\w*\s*(?:\w+\s+){0,2}"
            r"(?:unut|yok say|görmezden gel|iptal et|geçersiz)",
            15,
            15,
        ),
        (
            "prompt_injection",
            r"sistem\s*prompt|system\s*prompt|sistem talimat|gizli talimat|"
            r"ignore (?:all |the )?(?:previous|above) instructions|developer mode|"
            r"geliştirici modu|jailbreak|araç listesini (?:aynen|tam)",
            20,
            20,
        ),
        ("nefret_irkcilik", rf"\b{_GRUP}\b.{{0,40}}\b{_ASAGILAMA}", 10, 10),
        ("nefret_irkcilik", rf"\b{_ASAGILAMA}.{{0,20}}\b{_GRUP}", 10, 10),
        ("nefret_irkcilik", r"\bzenci\w*|ırkçı (?:şaka|fıkra|espri)|soykırım", 10, 10),
        (
            "rekabete_aykiri",
            r"fiyat\w*\s+(?:\w+\s+){0,3}(?:birlikte|beraber|ortak|anlaşarak)\s+belirle|"
            r"fiyat anlaşma|fiyatları sabitle|fiyat sabitle|pazarı paylaş|bölgeleri paylaş|"
            r"müşterileri paylaş|ihaleye (?:danışıklı|anlaşmalı)|danışıklı ihale",
            25,
            25,
        ),
        (
            "rekabete_aykiri",
            r"rakip\w*\s+(?:\w+\s+){0,6}(?:berbat|rezil|batık|batmak|dolandırıcı|kötüle|karala|"
            r"çöp|sahtekar|iflas)",
            55,
            50,
        ),
        (
            "zararli_icerik",
            r"zararlı yazılım|fidye yazılım|ransomware|keylogger|ddos saldırısı yap|"
            r"şifre\w* (?:çal|kır)|başkasının hesabına gir|virüs yaz",
            30,
            30,
        ),
        (
            "kufur_taciz",
            r"\b(?:siktir|amk|aq|orospu|piç|yavşak)\b|"
            r"\b(?:sen|siz|o|analist|po|testçi|mühendis)\b.{0,20}\b(?:aptal|salak|gerizekal|"
            r"ahmak|beyinsiz|mal)\w*",
            50,
            45,
        ),
        (
            "kisisel_veri",
            r"\b[1-9]\d{10}\b|\btr\d{2}\s?(?:\d{4}\s?){5}\d{2}\b|\b(?:\d{4}[ -]?){3}\d{4}\b|"
            r"\b0?5\d{2}[ -]?\d{3}[ -]?\d{2}[ -]?\d{2}\b|"
            r"[\w.+-]+@(?:gmail|hotmail|yahoo|outlook|icloud|yandex)\.\w+",
            60,
            20,
        ),
        (
            "kisisel_veri",
            r"(?:tc|t\.c\.) kimlik\w*|ev adres\w*|maaş\w* (?:ne|kaç|bilgi)|iban\w* (?:ver|nedir)",
            60,
            30,
        ),
    )
)
TEMIZ_PUAN: Final = 95


def kural_puani(metin: str, yon: str) -> tuple[int, list[str], list[str]]:
    """(puan, kategoriler, eşleşen kural adları). Eşleşme yoksa 95 / temiz."""
    s = sade(metin)
    puan, kategoriler, nedenler = TEMIZ_PUAN, [], []
    for kategori, desen, ps, pc in KURALLAR:
        if desen.search(s):
            puan = min(puan, ps if yon == "soru" else pc)
            if kategori not in kategoriler:
                kategoriler.append(kategori)
                nedenler.append(kategori)
    return puan, kategoriler or ["temiz"], nedenler


_GEREKCE: Final = {
    "prompt_injection": "talimatları geçersiz kılma ya da sistem talimatını isteme kalıbı",
    "nefret_irkcilik": "bir gruba yönelik aşağılayıcı ifade",
    "rekabete_aykiri": "rakip kötüleme ya da rekabet hukukuna aykırı yönlendirme kalıbı",
    "zararli_icerik": "zarar verme amaçlı yazılım/saldırı isteği",
    "kufur_taciz": "kişiye yönelik hakaret ya da küfür",
    "kisisel_veri": "kişisel veri kalıbı",
}


def sim_score(metin: str, yon: Literal["soru", "cevap"], baglam: Mapping[str, Any]) -> MessageScore:
    puan, kategoriler, nedenler = kural_puani(metin, yon)
    kategoriler = _asistan.kategorileri_duzelt(kategoriler, yon)
    gerekce = (
        "Kural tabanlı denetim: " + "; ".join(_GEREKCE[n] for n in nedenler) + "."
        if nedenler
        else "Kural tabanlı denetim: risk kalıbı bulunmadı."
    )
    anahtar = str(baglam.get("mesaj_id") or "") + ":" + yon + ":" + sade(metin)[:200]
    return MessageScore(
        puan=puan,
        kategoriler=kategoriler,
        karar=_asistan.karar_ver(puan, kategoriler, yon),
        gerekce=gerekce,
        talep_no=f"APS-{_simdi().year}-{uuid5(_SIM_NS, anahtar).hex[:8]}",
        kaynak="sim",
        ai_call_id=None,
    )


# ------------------------------------------------------------------ case seti denetimi (sim)


def _kayitlar(deger: Any) -> list[Mapping[str, Any]]:
    return [x for x in deger or [] if isinstance(x, Mapping)]


def sim_audit(istek: CaseSetAuditRequest) -> CaseSetAuditResult:
    cases = _kayitlar((istek.generated_set or {}).get("cases"))
    bulgular: list[dict[str, Any]] = []
    for i, c in enumerate(cases, 1):
        for veri in _kayitlar(c.get("test_data")):
            if veri.get("synthetic") is False:
                bulgular.append(
                    {"case": i, "kural": "synthetic", "aciklama": "test verisi sentetik değil"}
                )
            if veri.get("is_attack_payload") is None and _saldiri_gibi(veri.get("value")):
                bulgular.append(
                    {
                        "case": i,
                        "kural": "isaretsiz_payload",
                        "aciklama": "saldırı verisi işaretsiz",
                    }
                )
        if c.get("readiness") == "ready" and (
            c.get("assumption_refs") or c.get("open_question_refs")
        ):
            bulgular.append(
                {
                    "case": i,
                    "kural": "ready_ref",
                    "aciklama": "hazır case soru/varsayıma atıf yapıyor",
                }
            )
    karar = "DÜZELTME_GEREKLİ" if bulgular else "KABUL"
    return CaseSetAuditResult(
        decision=karar,
        decision_rationale=(
            f"Kural tabanlı simülasyon: {len(bulgular)} bulgu."
            if bulgular
            else "Kural tabanlı simülasyon: bulgu yok."
        ),
        findings=bulgular,
        missing_scenarios=[],
        talep_no=f"APD-{_simdi().year}-{uuid5(_SIM_NS, istek.set_hash).hex[:8]}",
        kaynak="sim",
    )


_SALDIRI = re.compile(
    r"<script|'\s*or\s*'?1'?\s*=\s*'?1|;\s*drop\s+table|\.\./\.\./|\$\{jndi:", re.I
)


def _saldiri_gibi(deger: Any) -> bool:
    return isinstance(deger, str) and bool(_SALDIRI.search(deger))


# ------------------------------------------------------------------ port


class SimAgentProbe:
    """`TP_AGENT_PROBE=sim`: her şey deterministik; model çağrısı yok."""

    name = "sim"

    def __init__(self, testler: SimAjanTestleri | None = None) -> None:
        self._testler = testler

    @property
    def testler(self) -> SimAjanTestleri:
        return self._testler or _varsayilan()

    def audit_case_set(self, istek: CaseSetAuditRequest) -> CaseSetAuditResult:
        return sim_audit(istek)

    def score_message(
        self, metin: str, yon: Literal["soru", "cevap"], baglam: Mapping[str, Any]
    ) -> MessageScore:
        return sim_score(metin, yon, baglam)

    def list_products(self) -> list[AgentProduct]:
        return self.testler.list_products()

    def start_agent_test(
        self, urun_kodu: str, requirement_id: UUID, gereksinim: Mapping[str, Any]
    ) -> AgentTestTicket:
        return self.testler.start_agent_test(urun_kodu, requirement_id, gereksinim)

    def get_agent_test(self, talep_no: str) -> AgentTestTicket:
        return self.testler.get_agent_test(talep_no)
