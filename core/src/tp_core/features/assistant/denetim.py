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
   Derin ("Daha ayrıntılı") mesajda aynı soru üst mesajda denetlendiyse yeniden çağrılmaz.
3. **Canlı yolda cevap** (son işlemden sonra, yazmadan önce) port ile: `engelle` → cevap
   saklanmaz/gösterilmez, açıklama; `uyar` → notla gösterilir.
4. **Fail-closed**: port kurulamaz ya da çağrı hata verirse asistan cevap vermez ("denetim
   çalışmıyor"); denetim zincirine `asistan.denetim_calismiyor`.

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
from collections.abc import Callable, Mapping
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
NOT_ONEKI: Final = "Denetim uyarısı"

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

SORU_ENGEL_METNI: Final = (
    "Sorunuz asistana iletilmedi: içerik denetimi engelledi ({kategoriler}). Soruyu iş "
    "bağlamında, bu içerik olmadan yeniden yazabilirsiniz."
)
CEVAP_ENGEL_METNI: Final = (
    "Asistanın cevabı içerik denetiminden geçmedi ({kategoriler}) ve gösterilmiyor. Soruyu farklı "
    "biçimde sorabilir ya da ilgili ekranı inceleyebilirsiniz."
)
CALISMIYOR_METNI: Final = (
    "Asistan denetimi şu an çalışmıyor; güvenlik gereği cevap verilmedi. Biraz sonra yeniden "
    "deneyin."
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
            "gerekce": self.skor.gerekce,
            "kaynak": self.skor.kaynak,
        }


@dataclass
class Denetim:
    """Bir mesajın denetim durumu (akış boyunca birikir)."""

    soru: list[Puan] = field(default_factory=list)
    cevap: Puan | None = None
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
    """Derin mesaj: üst zincirdeki son soru denetimi (aynı soru; yeniden çağrılmaz)."""
    with session_factory() as s:
        r = (
            s.execute(
                text(
                    "WITH RECURSIVE yukari AS (SELECT id, ust_mesaj_id, 0 AS d FROM asistan_mesaj "
                    "WHERE id = :u UNION ALL SELECT a.id, a.ust_mesaj_id, y.d + 1 FROM "
                    "asistan_mesaj a JOIN yukari y ON a.id = y.ust_mesaj_id WHERE y.d < 10) "
                    "SELECT d.puan, d.kategoriler, d.karar, d.gerekce, d.kaynak, d.talep_no "
                    "FROM asistan_denetim d JOIN yukari y ON y.id = d.mesaj_id "
                    "WHERE d.yon = 'soru' ORDER BY y.d, d.olusturma DESC LIMIT 1"
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
                        "g": p.skor.gerekce,
                        "kaynak": p.skor.kaynak,
                        "t": p.skor.talep_no,
                        "c": p.skor.ai_call_id,
                        "sure": p.sure_ms,
                    },
                )
                audit_on_commit(
                    s,
                    aktor,
                    "asistan.denetim",
                    f"asistan_mesaj:{mesaj_id}",
                    {
                        "yon": p.yon,
                        "puan": p.skor.puan,
                        "karar": p.skor.karar,
                        "kategoriler": list(p.skor.kategoriler),
                        "kaynak": p.skor.kaynak,
                        "talep_no": p.skor.talep_no,
                        "ai_call_id": str(p.skor.ai_call_id) if p.skor.ai_call_id else None,
                    },
                )
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


def denetim_alani(d: Denetim, *, karar: str, engellenen: str | None) -> dict[str, Any]:
    temsil = d.soru_temsilcisi()
    return {
        "karar": karar,
        "engellenen": engellenen,
        "soru": temsil.ozet() if temsil else None,
        "cevap": d.cevap.ozet() if d.cevap else None,
    }


def engel_cevabi(d: Denetim, yon: Literal["soru", "cevap"]) -> dict[str, Any]:
    from tp_core.features.assistant import sonislem

    p = d.soru_temsilcisi() if yon == "soru" else d.cevap
    kat = etiketler(list(p.skor.kategoriler) if p else [])
    sablon = SORU_ENGEL_METNI if yon == "soru" else CEVAP_ENGEL_METNI
    out = sonislem.bos_cevap()
    out["cevap_bloklari"] = [
        {"tur": "paragraf", "metin": sablon.format(kategoriler=kat), "maddeler": []}
    ]
    out["denetim"] = denetim_alani(d, karar="engelle", engellenen=yon)
    return out


def calismiyor_cevabi(d: Denetim, yon: str) -> dict[str, Any]:
    from tp_core.features.assistant import sonislem

    out = sonislem.bos_cevap()
    out["cevap_bloklari"] = [{"tur": "paragraf", "metin": CALISMIYOR_METNI, "maddeler": []}]
    out["denetim"] = denetim_alani(d, karar="calismiyor", engellenen=yon)
    return out


def isaretle(cevap: dict[str, Any], d: Denetim) -> dict[str, Any]:
    """Gösterilecek cevaba denetim alanı ve (uyarıda) not eklenir."""
    karar = guard.en_agir(d.soru_karari(), d.cevap.karar if d.cevap else None)
    out = dict(cevap)
    out["denetim"] = denetim_alani(d, karar=karar, engellenen=None)
    if karar == "uyar":
        kat: list[str] = []
        for p in [*d.soru, *([d.cevap] if d.cevap else [])]:
            if p.karar == "uyar":
                kat += [k for k in p.skor.kategoriler if k not in kat]
        notlar = list(out.get("notlar") or [])
        notlar.append(
            f"{NOT_ONEKI}: bu içerik dikkatle değerlendirilmeli ({etiketler(kat or ['temiz'])})."
        )
        out["notlar"] = notlar
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
