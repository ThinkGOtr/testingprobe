"""Agent Probe — asistan denetimi puanı (011 F7, K11; §4.5 `score_message`).

`score_message(metin, yon, baglam)`: asistana yazılan soru (`yon="soru"`) ya da asistanın cevabı
(`yon="cevap"`) Testing Probe geçidinde ayrı bir model çağrısıyla (`assistant_guard`, Haiku 5.5)
puanlanır. Model yalnız **puan (0–100), kategoriler ve kısa gerekçe** üretir; **kararı kod verir**
(`karar_ver`): eşikler + kategori tabanları. Kaynak `"tp-gecit"`; talep no `APG-<yıl>-<çağrı>`.

Geçit: asistan akışı kendi geçidini (aynı `AsistanBudget`, aynı kayıtçı; eval'de eval sağlayıcısı)
`gecit_kullan(gw)` bağlamıyla verir; verilmezse üretim geçidi kurulur (canlı, yedeksiz). Hata dışarı
taşar: çağıran fail-closed davranır (denetimsiz cevap verilmez).

Eşikler (`TP_ASISTAN_DENETIM_ENGEL`, vars. 40; `TP_ASISTAN_DENETIM_UYARI`, vars. 70):
puan < engel → engelle; puan < uyarı → uyar; aksi geç.

Kategori tabanları (eşikten bağımsız, karar en az bu olur; gerekçe):
- `nefret_irkcilik` → engelle (iki yön): hiçbir iş bağlamında gösterilmez, puanın modelce
  yumuşatılması kararı değiştirmemeli.
- `prompt_injection` → engelle (iki yön): soruda asistanın araçları (Jira/CI/kod/veri okuma) ve
  sistem talimatı hedef alınır — sistem/araç kötüye kullanımı modele hiç ulaşmamalı; cevapta
  talimat sızıntısı ya da ele geçirilmiş model belirtisidir.
- `kisisel_veri` → cevapta engelle (sızıntı: veri kullanıcıya gösterilmez), soruda uyar
  (kullanıcı kendi yazdı; geçit maskelemesi modele gideni ayrıca korur).
- `zararli_icerik`, `rekabete_aykiri`, `ayrimcilik`, `kufur_taciz` → en az uyar (puan düşükse
  engelle; ör. fiyat anlaşması isteği modelce düşük puanlanır).
- `yanlis_bilgi` → cevapta en az uyar; soruda kullanılmaz (kategori atılır).
- `kapsam_disi`, `temiz` → taban yok (puan karar verir).
"""

from __future__ import annotations

import contextvars
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from tp_core.ports import AsistanKarari, MessageScore, ModelMessage

AMAC: Final = "assistant_guard"
BUNDLE: Final = "assistant-guard"

KATEGORILER: Final = (
    "yanlis_bilgi",
    "nefret_irkcilik",
    "ayrimcilik",
    "rekabete_aykiri",
    "kufur_taciz",
    "kisisel_veri",
    "prompt_injection",
    "zararli_icerik",
    "kapsam_disi",
    "temiz",
)
# Güvenlik/gizlilik kategorileri: eval raporunda "kaçırma 0" hedefi bunlarda ölçülür.
GUVENLIK_KATEGORILERI: Final = frozenset({"nefret_irkcilik", "prompt_injection", "kisisel_veri"})

ORTAM_ENGEL: Final = "TP_ASISTAN_DENETIM_ENGEL"
ORTAM_UYARI: Final = "TP_ASISTAN_DENETIM_UYARI"
VARSAYILAN_ENGEL: Final = 40
VARSAYILAN_UYARI: Final = 70

METIN_TAVANI: Final = 6000
KAYNAK_TAVANI: Final = 4000

_SIRA: Final[dict[str, int]] = {"gec": 0, "uyar": 1, "engelle": 2}

# (kategori, yön) → taban karar; yön None = iki yön.
_TABAN: Final[dict[tuple[str, str | None], AsistanKarari]] = {
    ("nefret_irkcilik", None): "engelle",
    ("prompt_injection", None): "engelle",
    ("kisisel_veri", "cevap"): "engelle",
    ("kisisel_veri", "soru"): "uyar",
    ("zararli_icerik", None): "uyar",
    ("rekabete_aykiri", None): "uyar",
    ("ayrimcilik", None): "uyar",
    ("kufur_taciz", None): "uyar",
    ("yanlis_bilgi", "cevap"): "uyar",
}


def _esik(ad: str, varsayilan: int) -> int:
    try:
        deger = int((os.environ.get(ad) or "").strip() or varsayilan)
    except ValueError:
        return varsayilan
    return min(100, max(0, deger))


def esikler() -> tuple[int, int]:
    """(engel, uyarı); uyarı engelden küçükse engele eşitlenir (tutarsız ayar uyarıyı kapatmaz)."""
    engel = _esik(ORTAM_ENGEL, VARSAYILAN_ENGEL)
    uyari = _esik(ORTAM_UYARI, VARSAYILAN_UYARI)
    return engel, max(engel, uyari)


def kategorileri_duzelt(kategoriler: Sequence[Any], yon: str) -> list[str]:
    """Bilinmeyen ve soruda `yanlis_bilgi` atılır; başka kategori varsa `temiz` atılır."""
    out: list[str] = []
    for k in kategoriler:
        if not isinstance(k, str) or k not in KATEGORILER or k in out:
            continue
        if k == "yanlis_bilgi" and yon == "soru":
            continue
        out.append(k)
    if len(out) > 1 and "temiz" in out:
        out.remove("temiz")
    return out or ["temiz"]


def karar_ver(
    puan: int, kategoriler: Sequence[str], yon: str, esik: tuple[int, int] | None = None
) -> AsistanKarari:
    """Kodun kararı: eşik + kategori tabanı (en ağır olan)."""
    engel, uyari = esik or esikler()
    karar: AsistanKarari = "engelle" if puan < engel else "uyar" if puan < uyari else "gec"
    for k in kategorileri_duzelt(kategoriler, yon):
        taban = _TABAN.get((k, yon)) or _TABAN.get((k, None))
        if taban is not None and _SIRA[taban] > _SIRA[karar]:
            karar = taban
    return karar


def en_agir(*kararlar: str | None) -> str:
    return max((k for k in kararlar if k), key=lambda k: _SIRA.get(k, 0), default="gec")


# ------------------------------------------------------------------ girdi


def _kirp(metin: str, tavan: int) -> str:
    metin = metin or ""
    return metin if len(metin) <= tavan else metin[:tavan] + " …(kırpıldı)"


def guard_mesajlari(
    metin: str, yon: Literal["soru", "cevap"], baglam: Mapping[str, Any] | None = None
) -> list[ModelMessage]:
    """Denetim çağrısının tek kullanıcı mesajı (eval seti aynı kurucuyla üretilir)."""
    from tp_core.gateway.untrusted import wrap_untrusted

    baglam = baglam or {}
    parcalar = [f"Yön: {yon}"]
    if yon == "cevap":
        soru = baglam.get("soru")
        if isinstance(soru, str) and soru.strip():
            parcalar.append(
                "Kullanıcının sorusu:\n"
                + wrap_untrusted(_kirp(soru, 2000), source="kullanici_sorusu", kind="text")
            )
        ozetler = [str(x) for x in baglam.get("kaynak_ozetleri") or [] if str(x).strip()]
        kaynak = "\n".join(f"- {x}" for x in ozetler) or "(asistan kaynak kullanmadı)"
        parcalar.append(
            "Asistanın kullandığı kaynak özetleri:\n"
            + wrap_untrusted(_kirp(kaynak, KAYNAK_TAVANI), source="kaynak_ozetleri", kind="text")
        )
    parcalar.append(
        "Denetlenecek metin:\n"
        + wrap_untrusted(_kirp(metin, METIN_TAVANI), source="denetlenen_metin", kind="text")
    )
    return [ModelMessage(role="user", content="\n\n".join(parcalar))]


# ------------------------------------------------------------------ geçit

_GECIT: contextvars.ContextVar[Any] = contextvars.ContextVar("asistan_denetim_gecidi", default=None)


@contextmanager
def gecit_kullan(gw: Any) -> Iterator[None]:
    """Bu bağlamda `score_message` verilen geçidi kullanır (asistanın bütçeli geçidi)."""
    belirtec = _GECIT.set(gw)
    try:
        yield
    finally:
        _GECIT.reset(belirtec)


def _varsayilan_gecit() -> Any:  # pragma: no cover - üretim kurulumu (canlı sağlayıcı)
    from tp_core.audit import PgCallRecorder
    from tp_core.db import get_engine
    from tp_core.gateway import build_gateway

    engine = get_engine()
    return build_gateway(
        PgCallRecorder(engine), engine=engine, mode_override="live", replay_fallback=False
    )


def talep_no(call_id: UUID, simdi: datetime | None = None) -> str:
    return f"APG-{(simdi or datetime.now(UTC)).year}-{call_id.hex[:8]}"


def score_message(
    metin: str, yon: Literal["soru", "cevap"], baglam: Mapping[str, Any]
) -> MessageScore:
    """Geçitte puanlar. `baglam`: `call_id` (deterministik kök kimlik), `ek` (ai_call.ek:
    kullanici_id, mesaj_id…), `soru` ve `kaynak_ozetleri` (yalnız cevap)."""
    from tp_core.gateway.bundle import load_schema
    from tp_core.gateway.config import find_rules_dir

    gw = _GECIT.get() or _varsayilan_gecit()
    sema = load_schema(find_rules_dir(getattr(gw, "rules_dir", None)), AMAC)
    call_id = baglam.get("call_id")
    ek = baglam.get("ek")
    sonuc = gw.call(
        AMAC,
        BUNDLE,
        guard_mesajlari(metin, yon, baglam),
        sema,
        replay_key={},
        call_id=call_id if isinstance(call_id, UUID) else None,
        ek=dict(ek) if isinstance(ek, Mapping) else None,
    )
    out = sonuc.output if isinstance(sonuc.output, Mapping) else {}
    puan = int(out.get("puan", 0))
    kategoriler = kategorileri_duzelt(out.get("kategoriler") or [], yon)
    return MessageScore(
        puan=max(0, min(100, puan)),
        kategoriler=kategoriler,
        karar=karar_ver(puan, kategoriler, yon),
        gerekce=str(out.get("gerekce") or "")[:400],
        talep_no=talep_no(sonuc.call_id),
        kaynak="tp-gecit",
        ai_call_id=sonuc.call_id,
    )
