"""Asistan denetimi — akış tarafı (specs/011 F7, K11).

Asistana yazılan soru, asistan modeline GİTMEDEN; asistanın cevabı kullanıcıya GÖSTERİLMEDEN önce
Agent Probe portu (`score_message`) ile puanlanır; kararı kod verir
(`integrations.agent_probe.asistan.karar_ver`). `TP_ASISTAN_DENETIM=off` iken bugünkü davranış.

Sıra (`flow.cevapla`):

1. **Kural ön denetimi** (her yolda, modelsiz, maliyetsiz; constitution XI "deterministik önce"):
   soru `sim` kurallarıyla (anahtar sözcük) puanlanır. `engelle` → model çağrılmaz, mesaj
   `kaynak='denetim'` açıklamayla biter. Sözlük / şablon / kapalı (model hazır değil) yollarında
   sorunun denetimi budur (cevap kendi kural/veri içeriğimizdir, modelden gelmez).
2. **Canlı yolda soru** port ile (`tp`: geçitte Haiku `assistant_guard`; `sim`: kurallar):
   `engelle` → asistan modeli çağrılmaz; `uyar` → devam, cevaba not.
   Derin ("Daha ayrıntılı") mesajda aynı soru üst mesajda **model tabanlı** (`tp-gecit` /
   `agent-probe`) puanlandıysa yeniden çağrılmaz; üst mesaj yalnız kurallarla (sözlük / şablon /
   kapalı yolu, `sim`) denetlendiyse port puanı alınır.
3. **Canlı yolda cevap** (son işlemden sonra, yazmadan önce): gösterilen tüm serbest metin
   (`gosterilen_metin`: bloklar, maddeler, öneri başlık/neden/taslak, yönlendirme etiketi, kaynak
   ref/alıntı) puanlanır; tavanı (`METIN_TAVANI`) aşan cevap tavanda kesilir (`tavana_kes`, not
   eklenir). Önce modelsiz kural ön denetimi (`cevap_kural_puani`: doğrulanmış kişisel veri
   değeri, nefret kalıbı) → `engelle` ise port çağrılmaz. Sonra port: `engelle` → cevap
   saklanmaz/gösterilmez, açıklama; `uyar` → notla gösterilir.
4. **Fail-closed**: port kurulamaz ya da çağrı hata verirse asistan cevap vermez ("denetim
   çalışmıyor"); denetim zincirine `asistan.denetim_calismiyor`.

Kullanıcıya dönen metinler "İçerik kontrolü" der (K22); engel metni kullanıcıyı suçlamaz.
Modelin gerekçesi kayıttan ve portaldan önce kişisel veriden temizlenir (`gerekce_temizle`).

Her puan `asistan_denetim`'e (metin YOK: puan, kategoriler, karar, gerekçe, kaynak, talep no,
ai_call_id, süre) ve denetim zincirine (`asistan.denetim`) yazılır. Maliyet: denetim çağrıları
asistanın geçidinden (aynı `AsistanBudget`) geçer; `ai_call.ek.kullanici_id` kullanıcı günlük
tavanına, `asistan_denetim.ai_call_id` soru başı tavanına girer; mesajın `maliyet_usd`'sine eklenir.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.integrations.agent_probe import asistan as guard
from tp_core.integrations.agent_probe import sim
from tp_core.ports import MessageScore

log = logging.getLogger(__name__)

ORTAM: Final = "TP_ASISTAN_DENETIM"
KAYNAK: Final = "denetim"
# K22: kullanıcıya dönen metinlerde "İçerik kontrolü" (iç adlar — tablo, modül, olay — "denetim").
ETIKET: Final = "İçerik kontrolü"
NOT_ONEKI: Final = "İçerik kontrolü uyarısı"
KESILDI_NOTU: Final = (
    "Cevap uzun olduğu için içerik kontrolü sınırında kısaltıldı; ayrıntı için soruyu daraltın."
)
# Derin mesajda yeniden kullanılabilen soru puanı kaynakları (model tabanlı). `sim` (kural) puanı
# yeniden kullanılmaz: sözlük/şablon/kapalı yolundan gelen üst mesajın derini canlı modele gider ve
# sorunun model tabanlı kontrolden geçmesi gerekir (güvenlik #3).
MODEL_KAYNAKLARI: Final = ("tp-gecit", "agent-probe")

KATEGORI_ETIKETI: Final = {
    "yanlis_bilgi": "yanlış bilgi",
    "nefret_irkcilik": "nefret söylemi / ırkçılık",
    "ayrimcilik": "ayrımcılık",
    "rekabete_aykiri": "rekabete aykırı içerik",
    "kufur_taciz": "küfür / taciz",
    "kisisel_veri": "kişisel veri",
    "prompt_injection": "talimat manipülasyonu",
    "zararli_icerik": "zararlı içerik",
    "kapsam_disi": "kapsam dışı",
    "temiz": "temiz",
}

# Engel metinleri kullanıcıyı suçlamaz (K22); başlık + gövde. Portal `denetim.baslik/aciklama`yı
# gösterir; `cevap_bloklari` aynı metni taşır (eski istemciler için).
SORU_ENGEL_BASLIGI: Final = "Bu soruyu yanıtlayamıyorum"
SORU_ENGEL_METNI: Final = (
    "Soru içerik kurallarına takıldı ({kategoriler}). İş akışıyla ilgili olarak yeniden "
    "sorabilirsiniz. Yanlış olduğunu düşünüyorsanız 👎 ile bildirin."
)
# Kişisel veri nedeniyle engellenen soruda güvenli yol (test verisi isteği gerçek veriye değil
# sentetik veriye yönlendirilir; Test verisi ekranı, specs/013 §3.3).
SORU_KISISEL_VERI_IPUCU: Final = (
    "Test verisi gerekiyorsa gerçek kişisel veri yerine sentetik veri kullanın "
    "(Test verisi ekranı)."
)
CEVAP_ENGEL_BASLIGI: Final = "Bu cevabı gösteremiyorum"
CEVAP_ENGEL_METNI: Final = (
    "Asistanın cevabı içerik kurallarına takıldı ({kategoriler}) ve gösterilmiyor. Soruyu farklı "
    "biçimde sorabilir ya da ilgili ekranı inceleyebilirsiniz. Yanlış olduğunu düşünüyorsanız 👎 "
    "ile bildirin."
)
CALISMIYOR_BASLIGI: Final = "Şu an yanıt veremiyorum"
CALISMIYOR_METNI: Final = (
    "Asistan içerik kontrolü şu an çalışmıyor; güvenlik gereği cevap verilmedi. Biraz sonra "
    "yeniden deneyin."
)


def acik() -> bool:
    return (os.environ.get(ORTAM) or "on").strip().lower() not in ("0", "off", "false", "kapali")


class DenetimCalismiyor(RuntimeError):
    """Port kurulamadı ya da puanlama hata verdi (fail-closed)."""


@dataclass
class Puan:
    yon: Literal["soru", "cevap"]
    skor: MessageScore
    sure_ms: int = 0

    @property
    def karar(self) -> str:
        return self.skor.karar

    def ozet(self) -> dict[str, Any]:
        return {
            "puan": self.skor.puan,
            "karar": self.skor.karar,
            "kategoriler": list(self.skor.kategoriler),
            "gerekce": guard.gerekce_temizle(self.skor.gerekce),
            "kaynak": self.skor.kaynak,
        }


@dataclass
class Denetim:
    """Bir mesajın denetim durumu (akış boyunca birikir)."""

    soru: list[Puan] = field(default_factory=list)
    cevap: Puan | None = None
    kesildi: bool = False
    ai_call_ids: list[uuid.UUID] = field(default_factory=list)

    def soru_karari(self) -> str:
        return guard.en_agir(*(p.karar for p in self.soru))

    def soru_temsilcisi(self) -> Puan | None:
        """Gösterilen soru puanı: en ağır karar, eşitse en düşük puan."""
        if not self.soru:
            return None
        sira = {"gec": 0, "uyar": 1, "engelle": 2}
        return max(self.soru, key=lambda p: (sira[p.karar], -p.skor.puan))


# ------------------------------------------------------------------ puanlama


def kural_puani(metin: str, yon: Literal["soru", "cevap"], mesaj_id: uuid.UUID) -> Puan:
    bas = time.monotonic()
    skor = sim.sim_score(metin or "", yon, {"mesaj_id": str(mesaj_id)})
    return Puan(yon, skor, int((time.monotonic() - bas) * 1000))


def cevap_kural_puani(metin: str, mesaj_id: uuid.UUID, izin: Iterable[str] = ()) -> Puan:
    """Cevabın modelsiz ön denetimi (doğrulanmış kişisel veri değeri, nefret kalıbı); `engelle`
    → port çağrılmadan cevap gösterilmez (`sim.cevap_on_puani`). `izin`: kişisel veri sayılmayan
    birebir değerler (test verisi kataloğunun sentetik değerleri, `test_verisi_izinleri`)."""
    bas = time.monotonic()
    skor = sim.cevap_on_puani(metin or "", {"mesaj_id": str(mesaj_id), "izin": tuple(izin)})
    return Puan("cevap", skor, int((time.monotonic() - bas) * 1000))


def test_verisi_izinleri(session_factory: Callable[[], Any]) -> tuple[str, ...]:
    """Test verisi kataloğunun gizli olmayan değerleri (sentetik demo verisi; specs/013 §3.3).
    Cevap ön denetiminde birebir eşleşen değer kişisel veri sayılmaz. Katalog okunamazsa boş
    (denetim gevşemez)."""
    from tp_core.features.testveri import service as testveri

    try:
        with session_factory() as s:
            return tuple(v for v in testveri.katalog(s).values() if v)
    except Exception as exc:
        log.warning("asistan denetimi: test verisi kataloğu okunamadı (%s)", type(exc).__name__)
        return ()


# ------------------------------------------------------------------ gösterilen cevap metni

_Alan = tuple[Any, Any, str]  # (kap, anahtar/indeks, etiket)


def _alanlar(cevap: Mapping[str, Any]) -> list[_Alan]:
    """Kullanıcıya gösterilen serbest metin alanları, gösterim sırasıyla (güvenlik #4).

    Cevap blokları (metin, maddeler), öneriler (başlık, neden, Jira taslağının özeti/açıklaması),
    yönlendirme etiketleri, kaynaklar (ref, alıntı). `notlar` sonislemin sabit metinleridir,
    `jira_anahtarlari` sunucuda kalıpla doğrulanır; kontrole girmez."""
    out: list[_Alan] = []

    def metin_mi(kap: Any, k: Any) -> bool:
        try:
            return isinstance(kap[k], str)
        except (KeyError, IndexError, TypeError):
            return False

    def ekle(kap: Any, k: Any, etiket: str) -> None:
        if metin_mi(kap, k):
            out.append((kap, k, etiket))

    for b in cevap.get("cevap_bloklari") or []:
        if not isinstance(b, dict):
            continue
        ekle(b, "metin", "")
        maddeler = b.get("maddeler")
        if isinstance(maddeler, list):
            for i in range(len(maddeler)):
                ekle(maddeler, i, "- ")
    for o in cevap.get("oneriler") or []:
        if not isinstance(o, dict):
            continue
        ekle(o, "baslik", "Öneri: ")
        ekle(o, "neden", "Öneri gerekçesi: ")
        eylem = o.get("eylem")
        taslak = eylem.get("taslak") if isinstance(eylem, dict) else None
        if isinstance(taslak, dict):
            ekle(taslak, "ozet", "Jira taslağı özeti: ")
            ekle(taslak, "aciklama", "Jira taslağı açıklaması: ")
    for y in cevap.get("yonlendirmeler") or []:
        if isinstance(y, dict):
            ekle(y, "etiket", "Yönlendirme: ")
    for k in cevap.get("kaynaklar") or []:
        if isinstance(k, dict):
            ekle(k, "ref", "Kaynak: ")
            ekle(k, "alinti", "Kaynak alıntısı: ")
    return out


def gosterilen_metin(cevap: Mapping[str, Any]) -> str:
    """Puanlanan metin: gösterilen tüm serbest metin alanları, satır satır."""
    return "\n".join(etiket + kap[k] for kap, k, etiket in _alanlar(cevap) if str(kap[k]).strip())


def tavana_kes(cevap: Mapping[str, Any], tavan: int | None = None) -> tuple[dict[str, Any], bool]:
    """Gösterilen metin `tavan`ı (vars. puanlama girdisinin tavanı) aşarsa cevap tavanda kesilir:
    tavanı aşan alan kısaltılır, sonrakiler boşaltılıp ayıklanır. Böylece puanlanan metin
    gösterilen metnin tamamıdır (kontrol edilmeyen kuyruk gösterilmez). (kopya, kesildi_mi)."""
    import copy

    tavan = guard.METIN_TAVANI if tavan is None else tavan
    out: dict[str, Any] = copy.deepcopy(dict(cevap))
    kullanilan = 0
    kesildi = False
    for kap, k, etiket in _alanlar(out):
        deger = str(kap[k])
        if not deger.strip():
            continue
        if kesildi:
            kap[k] = ""
            continue
        maliyet = len(etiket) + len(deger) + 1
        if kullanilan + maliyet <= tavan:
            kullanilan += maliyet
            continue
        kesildi = True
        kalan = tavan - kullanilan - len(etiket) - 1
        kap[k] = deger[: max(0, kalan)].rstrip()
    if kesildi:
        _ayikla(out)
    return out, kesildi


def _ayikla(cevap: dict[str, Any]) -> None:
    """Kesmeden sonra boş kalan öğeleri atar (yarım öneri/taslak gösterilmez)."""
    bloklar = []
    for b in cevap.get("cevap_bloklari") or []:
        if not isinstance(b, dict):
            continue
        if isinstance(b.get("maddeler"), list):
            b["maddeler"] = [x for x in b["maddeler"] if not isinstance(x, str) or x.strip()]
        if (b.get("metin") or "").strip() or b.get("maddeler"):
            bloklar.append(b)
    cevap["cevap_bloklari"] = bloklar

    def tam_oneri(o: Any) -> bool:
        if not isinstance(o, dict) or not (o.get("baslik") or "").strip():
            return False
        if not (o.get("neden") or "").strip():
            return False
        eylem = o.get("eylem")
        taslak = eylem.get("taslak") if isinstance(eylem, dict) else None
        return not isinstance(taslak, dict) or bool(
            (taslak.get("ozet") or "").strip() and (taslak.get("aciklama") or "").strip()
        )

    cevap["oneriler"] = [o for o in cevap.get("oneriler") or [] if tam_oneri(o)]
    cevap["yonlendirmeler"] = [
        y
        for y in cevap.get("yonlendirmeler") or []
        if isinstance(y, dict) and (y.get("etiket") or "").strip()
    ]
    cevap["kaynaklar"] = [
        k
        for k in cevap.get("kaynaklar") or []
        if isinstance(k, dict) and ((k.get("ref") or "").strip() or (k.get("alinti") or "").strip())
    ]


def port_puani(
    metin: str,
    yon: Literal["soru", "cevap"],
    *,
    mesaj_id: uuid.UUID,
    kullanici_id: uuid.UUID,
    gw: Any,
    soru: str | None = None,
    kaynak_ozetleri: list[str] | None = None,
) -> Puan:
    """Port ile puan (`tp`: geçitte model; asistanın geçidi `gecit_kullan` ile verilir)."""
    from tp_core.gateway.core import deterministic_call_id
    from tp_core.integrations.agent_probe import get_agent_probe

    bas = time.monotonic()
    try:
        port = get_agent_probe()
        baglam = {
            "mesaj_id": str(mesaj_id),
            "call_id": deterministic_call_id(mesaj_id, f"{guard.AMAC}:{yon}"),
            "ek": {
                "kanal": "asistan",
                "kullanici_id": str(kullanici_id),
                "mesaj_id": str(mesaj_id),
                "denetim": yon,
            },
            "soru": soru,
            "kaynak_ozetleri": kaynak_ozetleri or [],
        }
        with guard.gecit_kullan(gw):
            skor = port.score_message(metin or "", yon, baglam)
    except Exception as exc:
        raise DenetimCalismiyor(type(exc).__name__) from exc
    return Puan(yon, skor, int((time.monotonic() - bas) * 1000))


def onceki_soru_puani(session_factory: Callable[[], Session], ust_id: uuid.UUID) -> Puan | None:
    """Derin mesaj: üst zincirdeki son **model tabanlı** soru puanı (aynı soru; yeniden
    çağrılmaz). Yalnız `kaynak IN MODEL_KAYNAKLARI`; üst mesaj yalnız kurallarla (`sim`)
    denetlendiyse None döner ve çağıran port puanı alır (güvenlik #3)."""
    with session_factory() as s:
        r = (
            s.execute(
                text(
                    "WITH RECURSIVE yukari AS (SELECT id, ust_mesaj_id, 0 AS d FROM asistan_mesaj "
                    "WHERE id = :u UNION ALL SELECT a.id, a.ust_mesaj_id, y.d + 1 FROM "
                    "asistan_mesaj a JOIN yukari y ON a.id = y.ust_mesaj_id WHERE y.d < 10) "
                    "SELECT d.puan, d.kategoriler, d.karar, d.gerekce, d.kaynak, d.talep_no "
                    "FROM asistan_denetim d JOIN yukari y ON y.id = d.mesaj_id "
                    "WHERE d.yon = 'soru' AND d.kaynak IN ('tp-gecit', 'agent-probe') "
                    "ORDER BY y.d, d.olusturma DESC LIMIT 1"
                ),
                {"u": ust_id},
            )
            .mappings()
            .first()
        )
        s.rollback()
    if r is None:
        return None
    skor = MessageScore(
        puan=r["puan"],
        kategoriler=list(r["kategoriler"] or []),
        karar=r["karar"],
        gerekce=r["gerekce"] or "",
        talep_no=r["talep_no"] or "",
        kaynak=r["kaynak"],
    )
    return Puan("soru", skor)


# ------------------------------------------------------------------ kayıt


def kaydet(
    session_factory: Callable[[], Session],
    mesaj_id: uuid.UUID,
    aktor: str,
    *puanlar: Puan,
) -> None:
    """`asistan_denetim` satırları + denetim zinciri (metin yazılmaz). Hata akışı düşürmez."""
    if not puanlar:
        return
    try:
        with session_factory() as s:
            for p in puanlar:
                s.execute(
                    text(
                        "INSERT INTO asistan_denetim (mesaj_id, yon, puan, kategoriler, karar, "
                        "gerekce, kaynak, talep_no, ai_call_id, sure_ms) VALUES (:m, :y, :p, "
                        "CAST(:k AS jsonb), :karar, :g, :kaynak, :t, :c, :sure)"
                    ),
                    {
                        "m": mesaj_id,
                        "y": p.yon,
                        "p": p.skor.puan,
                        "k": _json(p.skor.kategoriler),
                        "karar": p.skor.karar,
                        "g": guard.gerekce_temizle(p.skor.gerekce),
                        "kaynak": p.skor.kaynak,
                        "t": p.skor.talep_no,
                        "c": p.skor.ai_call_id,
                        "sure": p.sure_ms,
                    },
                )
                ozet: dict[str, Any] = {
                    "yon": p.yon,
                    "puan": p.skor.puan,
                    "karar": p.skor.karar,
                    "kategoriler": list(p.skor.kategoriler),
                    "kaynak": p.skor.kaynak,
                    "talep_no": p.skor.talep_no,
                    "ai_call_id": str(p.skor.ai_call_id) if p.skor.ai_call_id else None,
                }
                # Tur 3 güvenlik #2: cevapta injection işaretli ama yüksek puan → karar engel
                # kalır; tutarsız etiket ayrıca izlenir (denetim kaydında işaret + log sayacı).
                if guard.tutarsiz_etiket(p.skor.puan, p.skor.kategoriler, p.yon):
                    ozet["tutarsiz_etiket"] = True
                    log.warning(
                        "asistan_denetim.tutarsiz_etiket yon=%s puan=%s talep_no=%s",
                        p.yon,
                        p.skor.puan,
                        p.skor.talep_no,
                    )
                audit_on_commit(s, aktor, "asistan.denetim", f"asistan_mesaj:{mesaj_id}", ozet)
            s.commit()
    except Exception as exc:  # kayıt hatası cevabı düşürmez (karar zaten verildi)
        log.warning("asistan denetimi kaydedilemedi (%s)", type(exc).__name__)


def calismiyor_kaydet(
    session_factory: Callable[[], Session], mesaj_id: uuid.UUID, yon: str, neden: str
) -> None:
    try:
        with session_factory() as s:
            audit_on_commit(
                s,
                "agent-probe",
                "asistan.denetim_calismiyor",
                f"asistan_mesaj:{mesaj_id}",
                {"yon": yon, "hata": neden},
            )
            s.commit()
    except Exception as exc:
        log.warning("denetim hatası kaydedilemedi (%s)", type(exc).__name__)


def _json(deger: Any) -> str:
    import json

    return json.dumps(deger, ensure_ascii=False)


# ------------------------------------------------------------------ cevap


def etiketler(kategoriler: list[str]) -> str:
    anlamli = [k for k in kategoriler if k != "temiz"] or kategoriler
    return ", ".join(KATEGORI_ETIKETI.get(k, k) for k in anlamli)


def denetim_alani(
    d: Denetim,
    *,
    karar: str,
    engellenen: str | None,
    baslik: str | None = None,
    aciklama: str | None = None,
    kategori_etiketi: str | None = None,
) -> dict[str, Any]:
    """Cevaptaki `denetim` alanı (portal sözleşmesi; D5).

    `etiket` ("İçerik kontrolü"), `karar` (gec|uyar|engelle|calismiyor), `engellenen`
    (soru|cevap|None), `baslik`/`aciklama` (engel ve çalışmıyor durumunda gösterilecek metin),
    `kategori_etiketi` (insan okur kategori listesi), `kesildi` (cevap tavanda kısaltıldı),
    `soru`/`cevap` (puan, karar, kategoriler, temizlenmiş gerekçe, kaynak)."""
    temsil = d.soru_temsilcisi()
    return {
        "etiket": ETIKET,
        "karar": karar,
        "engellenen": engellenen,
        "baslik": baslik,
        "aciklama": aciklama,
        "kategori_etiketi": kategori_etiketi,
        "kesildi": d.kesildi,
        "soru": temsil.ozet() if temsil else None,
        "cevap": d.cevap.ozet() if d.cevap else None,
    }


def _metin_cevabi(baslik: str, govde: str) -> dict[str, Any]:
    from tp_core.features.assistant import sonislem

    out = sonislem.bos_cevap()
    out["cevap_bloklari"] = [
        {"tur": "baslik", "metin": baslik, "maddeler": []},
        {"tur": "paragraf", "metin": govde, "maddeler": []},
    ]
    return out


def engel_cevabi(d: Denetim, yon: Literal["soru", "cevap"]) -> dict[str, Any]:
    p = d.soru_temsilcisi() if yon == "soru" else d.cevap
    kat = etiketler(list(p.skor.kategoriler) if p else [])
    baslik = SORU_ENGEL_BASLIGI if yon == "soru" else CEVAP_ENGEL_BASLIGI
    govde = (SORU_ENGEL_METNI if yon == "soru" else CEVAP_ENGEL_METNI).format(kategoriler=kat)
    if yon == "soru" and p is not None and "kisisel_veri" in p.skor.kategoriler:
        govde += " " + SORU_KISISEL_VERI_IPUCU
    out = _metin_cevabi(baslik, govde)
    out["denetim"] = denetim_alani(
        d,
        karar="engelle",
        engellenen=yon,
        baslik=baslik,
        aciklama=govde,
        kategori_etiketi=kat,
    )
    return out


def calismiyor_cevabi(d: Denetim, yon: str) -> dict[str, Any]:
    out = _metin_cevabi(CALISMIYOR_BASLIGI, CALISMIYOR_METNI)
    out["denetim"] = denetim_alani(
        d,
        karar="calismiyor",
        engellenen=yon,
        baslik=CALISMIYOR_BASLIGI,
        aciklama=CALISMIYOR_METNI,
    )
    return out


def isaretle(cevap: dict[str, Any], d: Denetim) -> dict[str, Any]:
    """Gösterilecek cevaba denetim alanı ve (uyarıda) not eklenir."""
    karar = guard.en_agir(d.soru_karari(), d.cevap.karar if d.cevap else None)
    out = dict(cevap)
    notlar = list(out.get("notlar") or [])
    kat_etiketi = None
    if karar == "uyar":
        kat: list[str] = []
        for p in [*d.soru, *([d.cevap] if d.cevap else [])]:
            if p.karar == "uyar":
                kat += [k for k in p.skor.kategoriler if k not in kat]
        kat_etiketi = etiketler(kat or ["temiz"])
        notlar.append(f"{NOT_ONEKI}: bu içerik dikkatle değerlendirilmeli ({kat_etiketi}).")
    if d.kesildi:
        notlar.append(KESILDI_NOTU)
    out["notlar"] = notlar
    out["denetim"] = denetim_alani(d, karar=karar, engellenen=None, kategori_etiketi=kat_etiketi)
    return out


def kaynak_ozetleri(cevap: Mapping[str, Any]) -> list[str]:
    """Cevabın kaynakları (tür, ref, alıntı) — `yanlis_bilgi` denetiminin girdisi."""
    out = []
    for k in cevap.get("kaynaklar") or []:
        if not isinstance(k, Mapping):
            continue
        parca = " ".join(str(x) for x in (k.get("tur"), k.get("ref")) if isinstance(x, str) and x)
        alinti = k.get("alinti")
        if isinstance(alinti, str) and alinti.strip():
            parca += f": {alinti.strip()[:400]}"
        if parca:
            out.append(parca)
    return out[:12]
