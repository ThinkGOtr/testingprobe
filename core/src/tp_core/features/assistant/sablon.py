"""Şablon dalı (AI-ASISTAN-PLANI §10.2 adım 3; constitution XI — modelsiz, ücretsiz).

İki soru sınıfı modelsiz cevaplanır (`kaynak=sablon`):

- Tek Jira anahtarı + "neden/durum/nerede" (S3: "TPD-3 neden case üretimine geçmiyor?") →
  `probe_get` (gereksinim, bug taslağı, yayınlanmış case, script sırasıyla aranır);
- "Bugün ne yapmalıyım?" (S6) → `probe_my_queue`.

Araç uygulaması modelin kullandığı **aynı fonksiyondur** ve oturumdaki rolle çağrılır (uç-düzeyi
rol kısıtı ve alan izin listesi aynen geçerli). Çağrı `tool_call`'a `kanal='asistan'`,
`cagiran_user_id` ve `ai_call_id=NULL` ile yazılır (constitution VIII); kayıttaki sonuç özeti sır
temizlenmiş ve mesajın oturumuyla maskelenmiştir.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from tp_core.features.assistant import siniflandir
from tp_core.features.assistant.sonislem import DOGRULANDI, bos_cevap, rota_gecerli
from tp_core.features.assistant.tools.base import (
    AracBaglami,
    AracHatasi,
    AracSonucu,
    KanitHavuzu,
    sir_temizle,
)

# Anahtarla aranan türler (probe.varlik_bul'un anahtar desteklediği sırayla).
ANAHTARLI_TURLER: Final = ("requirement", "bug_draft", "case", "script")
JIRA_KAYITLI_TURLER: Final = frozenset({"requirement", "bug_draft", "case"})
OZET_AZAMI: Final = 500
SATIR_AZAMI: Final = 40
TUR_ETIKETI: Final = {
    "requirement": "Gereksinim",
    "bug_draft": "Bug taslağı",
    "case": "Case",
    "script": "Script",
}


@dataclass(frozen=True)
class SablonCevabi:
    cevap: dict[str, Any]
    arac: str


def _satir_degeri(metin: str, alan: str) -> str | None:
    onek = f"{alan}: "
    for s in metin.splitlines():
        if s.startswith(onek):
            deger = s[len(onek) :].strip()
            return None if deger in ("", "-") else deger
    return None


def _kaydet(
    baglam: AracBaglami,
    kaydedici: Callable[[Mapping[str, Any]], Any] | None,
    arac: str,
    arg: Mapping[str, Any],
    sonuc: str,
    izinli: bool,
) -> None:
    """`tool_call` kaydı (append-only): sonuç sır temizlenmiş ve maskeli, 500 karakter."""
    ozet, _ = baglam.oturum.mask_text(sir_temizle(sonuc, baglam.sir_degerleri))
    satir = {
        "id": uuid.uuid4(),
        "ai_call_id": None,
        "kanal": "asistan",
        "cagiran_user_id": baglam.kullanici_id,
        "arac": arac,
        "arguman_ozeti": json.loads(json.dumps(dict(arg), ensure_ascii=False, default=str)),
        "sonuc_ozeti": ozet[:OZET_AZAMI],
        "izin_verildi": izinli,
    }
    if kaydedici is not None:
        kaydedici(satir)
        return
    from tp_core.audit.recorder import record_tool_call

    with baglam.db() as s:
        record_tool_call(s.connection(), satir)
        s.commit()


def _cagir(
    baglam: AracBaglami,
    kaydedici: Callable[[Mapping[str, Any]], Any] | None,
    arac: str,
    fn: Callable[..., AracSonucu],
    arg: dict[str, Any],
) -> AracSonucu | None:
    try:
        sonuc = fn(baglam, **arg)
    except AracHatasi as exc:
        _kaydet(baglam, kaydedici, arac, arg, f"hata: {exc}", True)
        return None
    _kaydet(baglam, kaydedici, arac, arg, sonuc.metin, True)
    return sonuc


def _temiz_satirlar(baglam: AracBaglami, metin: str, musteri_verisi: bool) -> list[str]:
    metin = sir_temizle(metin, baglam.sir_degerleri)
    if musteri_verisi:
        metin, _ = baglam.oturum.mask_text(metin)
    return [s for s in metin.splitlines() if s.strip()][:SATIR_AZAMI]


def _kaynak(
    havuz: KanitHavuzu, arac: str, sonuc: AracSonucu, alinti: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    kanit = havuz.ekle(arac, sonuc.kanit_turu, lambda _k: sonuc.metin, meta=sonuc.meta)
    kaynak = {
        "tur": "probe_verisi",
        "ref": kanit.kimlik,
        "alinti": alinti[:300],
        "dogrulandi": True,
    }
    return kaynak, {kanit.kimlik: {"dogrulandi": True, "sha256": kanit.sha256}}


def durum_cevabi(
    baglam: AracBaglami,
    anahtar: str,
    *,
    kaydedici: Callable[[Mapping[str, Any]], Any] | None = None,
    jira_adresi: Callable[[str], str | None] | None = None,
    musteri_verisi: bool = False,
) -> SablonCevabi | None:
    """`probe_get` ile anahtarlı kaydın durumu; kayıt yoksa/rolüne kapalıysa None (model dalı)."""
    from tp_core.features.assistant.tools.probe import probe_get

    for tur in ANAHTARLI_TURLER:
        try:
            sonuc = probe_get(baglam, tur=tur, id_or_key=anahtar)
        except AracHatasi:
            continue
        _kaydet(
            baglam, kaydedici, "probe_get", {"tur": tur, "id_or_key": anahtar}, sonuc.metin, True
        )
        return SablonCevabi(
            _durum_cevabi_kur(baglam, anahtar, tur, sonuc, jira_adresi, musteri_verisi),
            "probe_get",
        )
    return None


def _durum_cevabi_kur(
    baglam: AracBaglami,
    anahtar: str,
    tur: str,
    sonuc: AracSonucu,
    jira_adresi: Callable[[str], str | None] | None,
    musteri_verisi: bool,
) -> dict[str, Any]:
    metin = sonuc.metin
    kapi = _satir_degeri(metin, "bekleyen_kapi")
    sorumlu = _satir_degeri(metin, "sorumlu_rol")
    son_hata = _satir_degeri(metin, "son_hata")
    rota = _satir_degeri(metin, "ekran_rotasi")
    durum = _satir_degeri(metin, "durum")
    out = bos_cevap()
    baslik = f"{anahtar} · {TUR_ETIKETI[tur]}" + (f" · {durum}" if durum else "")
    ozet = []
    if kapi:
        ozet.append(f"Bekleyen kapı: {kapi}.")
    if sorumlu:
        ozet.append(f"Sorumlu: {sorumlu}.")
    if son_hata:
        ozet.append(f"Son hata: {son_hata}.")
    if not ozet:
        ozet.append("Kayıtta bekleyen bir kapı görünmüyor.")
    out["cevap_bloklari"] = [
        {"tur": "baslik", "metin": baslik, "maddeler": []},
        {"tur": "paragraf", "metin": " ".join(ozet), "maddeler": []},
        {
            "tur": "liste",
            "metin": "Kayıt ayrıntısı:",
            "maddeler": _temiz_satirlar(baglam, metin, musteri_verisi),
        },
    ]
    havuz = KanitHavuzu()
    alinti = f"bekleyen_kapi: {kapi}" if kapi else metin.splitlines()[0]
    kaynak, dogrulama = _kaynak(havuz, "probe_get", sonuc, alinti)
    out["kaynaklar"], out["dogrulama"] = [kaynak], dogrulama
    out["guven"] = "yuksek"
    out["guven_gosterimi"] = DOGRULANDI
    out["urune_ozgu"] = True
    if rota and rota_gecerli(rota):
        out["yonlendirmeler"] = [{"etiket": f"{TUR_ETIKETI[tur]} ekranı", "rota": rota}]
    # Script'in test anahtarı Probe'un "bilinen anahtar" kümesinde değildir (§5.6): bağlantı yok.
    if tur in JIRA_KAYITLI_TURLER:
        out["jira_anahtarlari"] = [anahtar]
        url = jira_adresi(anahtar) if jira_adresi is not None else None
        if url:
            out["jira_baglantilari"] = [{"anahtar": anahtar, "url": url}]
    if musteri_verisi:
        out, _ = baglam.oturum.mask(out)
    return out


def kuyruk_cevabi(
    baglam: AracBaglami,
    *,
    kaydedici: Callable[[Mapping[str, Any]], Any] | None = None,
    musteri_verisi: bool = False,
) -> SablonCevabi | None:
    """`probe_my_queue`: çağıranın rolüne düşen bekleyen işler."""
    from tp_core.features.assistant.tools.probe import probe_my_queue

    sonuc = _cagir(baglam, kaydedici, "probe_my_queue", probe_my_queue, {})
    if sonuc is None:
        return None
    satirlar = _temiz_satirlar(baglam, sonuc.metin, musteri_verisi)
    out = bos_cevap()
    maddeler: list[str] = []
    yonlendirmeler: list[dict[str, str]] = []
    for s in satirlar[1:]:
        parca = [p.strip() for p in s.lstrip("- ").split(" | ")]
        if len(parca) == 4:
            _tur, etiket, neden, rota = parca
            maddeler.append(f"{etiket}: {neden}")
            if rota_gecerli(rota) and len(yonlendirmeler) < 5:
                yonlendirmeler.append({"etiket": etiket[:80], "rota": rota})
        else:
            maddeler.append(s.lstrip("- "))
    out["cevap_bloklari"] = [
        {"tur": "paragraf", "metin": satirlar[0] if satirlar else "", "maddeler": []},
        {"tur": "liste", "metin": "", "maddeler": maddeler},
    ]
    havuz = KanitHavuzu()
    kaynak, dogrulama = _kaynak(havuz, "probe_my_queue", sonuc, sonuc.metin.splitlines()[0])
    out["kaynaklar"], out["dogrulama"] = [kaynak], dogrulama
    out["guven"] = "yuksek"
    out["guven_gosterimi"] = DOGRULANDI
    out["urune_ozgu"] = True
    out["yonlendirmeler"] = yonlendirmeler
    if musteri_verisi:
        out, _ = baglam.oturum.mask(out)
    return SablonCevabi(out, "probe_my_queue")


def sablon_cevabi(
    baglam: AracBaglami,
    soru: str | None,
    *,
    kaydedici: Callable[[Mapping[str, Any]], Any] | None = None,
    jira_adresi: Callable[[str], str | None] | None = None,
    musteri_verisi: bool = False,
) -> SablonCevabi | None:
    """Sorunun şablon sınıfı varsa modelsiz cevap; yoksa None."""
    anahtar = siniflandir.durum_sorusu(soru)
    if anahtar is not None:
        cevap = durum_cevabi(
            baglam,
            anahtar,
            kaydedici=kaydedici,
            jira_adresi=jira_adresi,
            musteri_verisi=musteri_verisi,
        )
        if cevap is not None:
            return cevap
    if siniflandir.kuyruk_sorusu(soru):
        return kuyruk_cevabi(baglam, kaydedici=kaydedici, musteri_verisi=musteri_verisi)
    return None


__all__ = ["SablonCevabi", "durum_cevabi", "kuyruk_cevabi", "sablon_cevabi"]
