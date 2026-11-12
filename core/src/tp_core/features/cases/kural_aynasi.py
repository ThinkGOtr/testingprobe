"""011 §4.2 deterministik kurallarının değerlendirme aynası (canlı eval ve derinleştirme denetimi).

Üretimdeki karşılığı `features.cases.schema` (`consistency_problems`, `set_problems`,
`generation_output_problems`); test tarafındaki üçüncü uygulama `tests/unit/gateway/case_v3_rules`.
Üçü bilerek ayrı yazılır: `test_case_goldens_v3.py` golden'ları ve bozulmuş golden'ları üçüne
birden sorar; biri kuralı farklı okursa orada görünür. Bu modül yalnız sabit desenleri
(`PLATFORM_KATEGORISI`, `NEGATIF_KATEGORISI`) `schema`'dan alır (tek kaynak).

Eskiden `gateway.eval_agents` içindeydi; üretimdeki derinleştirme (`deepen.py`) değerlendirme
modülünü içe aktarmasın diye özellik katmanına taşındı (tur 2 inceleme #16). `eval_agents`
aynı adlarla buradan kullanır.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from tp_core.features.cases.schema import (
    NEGATIF_KATEGORISI,
    PLATFORM_KATEGORISI,
    soru_aniliyor,
)

# Teknik ↔ kapsam öğesi kimliği öneki (rules/schemas/case_generation.schema.json).
TEKNIK_ONEKI: dict[str, str] = {
    "EP": "EP-",
    "BVA": "BV-",
    "DT": "DT-",
    "ST": "ST-",
    "PW": "PW-",
    "UC": "UC-",
    "EG": "EG-",
    "CL": "CL-",
}
READINESS = ("ready", "assumption_dependent", "blocked")
# Kısa saldırı verisi yalnız tek başına geçtiğinde sayılır (`schema.KISA_VERI`).
KISA_VERI = 4
ACIK_NOKTA = re.compile(r"a[çc][ıiİI]k\s+nokta", re.IGNORECASE)


def _liste(deger: Any) -> list[Any]:
    return list(deger) if isinstance(deger, (list, tuple)) else []


def _kayitlar(deger: Any) -> list[Mapping[str, Any]]:
    return [x for x in _liste(deger) if isinstance(x, Mapping)]


def _sade(deger: Any) -> str:
    """Boşlukları teke indirir, büyük/küçük harfi eşitler (saldırı verisi karşılaştırması)."""
    return re.sub(r"\s+", " ", str(deger or "")).strip().casefold()


def _saldiri_alanlari(case: Mapping[str, Any]) -> list[str]:
    """Saldırı verisinin GEÇMEMESİ gereken alanlar: başlık, ön koşul, adım, beklenen, temizlik."""
    parcalar = [str(case.get("title") or ""), str(case.get("expected_result") or "")]
    parcalar += [str(p) for p in _liste(case.get("preconditions"))]
    parcalar += [str(t) for t in _liste(case.get("teardown"))]
    for step in _kayitlar(case.get("steps")):
        parcalar += [str(step.get(k) or "") for k in ("action", "data", "expected")]
    return parcalar


def _veri_geciyor(deger: str, metin: str) -> bool:
    if not deger:
        return False
    if len(deger) >= KISA_VERI:
        return deger in metin
    return re.search(rf"(?<!\S){re.escape(deger)}(?!\S)", metin) is not None


def case_rule_problems(case: Mapping[str, Any], output: Mapping[str, Any]) -> list[str]:
    """011 §4.2 case düzeyi kurallar (1–6); `output` aynı üretimin üst düzey listeleri."""
    sorunlar: list[str] = []
    ogeler = {str(o.get("id")) for o in _kayitlar(output.get("coverage_items"))}
    sorular = {str(q.get("id")) for q in _kayitlar(output.get("open_questions"))}
    varsayimlar = {str(a.get("id")) for a in _kayitlar(output.get("assumptions"))}
    teknikler = [str(t) for t in _liste(case.get("technique"))]
    kapsar = [str(k) for k in _liste(case.get("covers"))]
    durum = case.get("readiness")
    for ad, deger in (("technique", teknikler), ("covers", kapsar)):
        if not deger:
            sorunlar.append(f"{ad} boş")
    if case.get("priority") not in ("P1", "P2", "P3"):
        sorunlar.append("priority boş")
    if not str(case.get("priority_rationale") or "").strip():
        sorunlar.append("priority_rationale boş")
    if durum not in READINESS:
        sorunlar.append(f"readiness geçersiz: {durum!r}")
    # 1. Tanımsız kapsam öğesi yok.
    tanimsiz = sorted(k for k in kapsar if k not in ogeler)
    if tanimsiz:
        sorunlar.append(f"tanımsız kapsam öğesi: {tanimsiz}")
    # 2. Teknik ↔ kapsam öneki: her tekniğin `covers`'ta en az bir öğesi var (yönerge kuralı).
    for teknik in teknikler:
        onek = TEKNIK_ONEKI.get(teknik)
        if onek is None or not any(k.startswith(onek) for k in kapsar):
            sorunlar.append(f"teknik {teknik} için kapsam öğesi yok")
    onekler = {TEKNIK_ONEKI[t] for t in teknikler if t in TEKNIK_ONEKI}
    sahipsiz = sorted(k for k in kapsar if not any(k.startswith(o) for o in onekler))
    if sahipsiz:
        sorunlar.append(f"tekniği technique'te olmayan kapsam öğesi: {sahipsiz}")
    # 3. Varsayım / açık soru atıfları üst listelerde tanımlı.
    a_refs = [str(r) for r in _liste(case.get("assumption_refs"))]
    q_refs = [str(r) for r in _liste(case.get("open_question_refs"))]
    eksik = sorted(
        {r for r in a_refs if r not in varsayimlar} | {r for r in q_refs if r not in sorular}
    )
    if eksik:
        sorunlar.append(f"tanımsız varsayım/soru atıfı: {eksik}")
    # 4. Hazır olma durumu ↔ atıflar ve beklenenler.
    beklenen = str(case.get("expected_result") or "").strip()
    adimlar = _kayitlar(case.get("steps"))
    bos_adim = [str(s.get("id")) for s in adimlar if not str(s.get("expected") or "").strip()]
    if durum == "ready":
        if a_refs or q_refs:
            sorunlar.append("ready case varsayım/soru atıfı taşıyor")
        if not beklenen or bos_adim:
            sorunlar.append("ready case'te beklenen sonuç boş")
    elif durum == "assumption_dependent":
        if not a_refs:
            sorunlar.append("assumption_dependent case'te varsayım atıfı yok")
        if not beklenen or bos_adim:
            sorunlar.append("assumption_dependent case'te beklenen sonuç boş")
    elif durum == "blocked":
        if not q_refs:
            sorunlar.append("blocked case'te açık soru atıfı yok")
        if beklenen:
            sorunlar.append("blocked case'te expected_result dolu")
    # "AÇIK NOKTA" yalnız varsayıma bağlı / soru bekleyen case'te, atfıyla.
    alanlar = [_sade(alan) for alan in _saldiri_alanlari(case)]
    if any(ACIK_NOKTA.search(alan) for alan in alanlar):
        if durum == "ready":
            sorunlar.append("ready case 'AÇIK NOKTA' içeriyor")
        elif not (a_refs or q_refs):
            sorunlar.append("'AÇIK NOKTA' var ama varsayım/soru atfı yok")
    # 5–6. Test verisi: sentetik; saldırı verisi başka alanda geçmez.
    for veri in _kayitlar(case.get("test_data")):
        if veri.get("synthetic") is not True:
            sorunlar.append(f"test verisi sentetik değil: {veri.get('name')}")
        deger = _sade(veri.get("value"))
        saldiri = veri.get("is_attack_payload") is True and bool(deger)
        if saldiri and any(_veri_geciyor(deger, alan) for alan in alanlar):
            sorunlar.append(f"saldırı verisi başka alanda geçiyor: {veri.get('name')}")
    return sorunlar


def yetim_sorular(output: Any, *, kapanan: Iterable[str] = ()) -> list[str]:
    """Hiçbir yerde anılmayan açık sorular: case atfı (`open_question_refs`), `not_covered`
    kaydının `question_ref`'i, negatif kapsam kararının gerekçesi ya da kapsam öğesinin tanımı
    soruyu anmıyor (011 K16; eval `yetim_soru` metriği). `schema.orphan_questions` ile aynı
    kural: serbest metin sınırı `schema.soru_aniliyor` (tek tanım; tur 3 #9), PO yanıtıyla
    kapanan sorular (`kapanan`) yetim değildir (tur 3 #1)."""
    kapali = {str(q) for q in kapanan}
    out = output if isinstance(output, Mapping) else {}
    anilan: set[str] = set()
    for case in _kayitlar(out.get("cases")):
        anilan.update(str(r) for r in _liste(case.get("open_question_refs")))
    for kayit in _kayitlar(out.get("not_covered")):
        if kayit.get("question_ref"):
            anilan.add(str(kayit.get("question_ref")))
    serbest = [k.get("rationale") for k in _kayitlar(out.get("negative_coverage"))]
    serbest += [o.get("definition") for o in _kayitlar(out.get("coverage_items"))]
    yetim: list[str] = []
    for soru in _kayitlar(out.get("open_questions")):
        kimlik = str(soru.get("id"))
        if kimlik in anilan or kimlik in kapali or any(soru_aniliyor(m, kimlik) for m in serbest):
            continue
        yetim.append(kimlik)
    return yetim


def generation_rule_problems(output: Any, *, ek_set: bool = False) -> list[str]:
    """011 §4.2 deterministik kurallarının tamamı, bir üretim çıktısının bütününe uygulanır:
    her case için `case_rule_problems` + set düzeyi (negatif kapsam kararı, kapsanmayan gerekçesi,
    yetim açık soru). AC atıfı (kural 7) belgeyi bilen `eval_agents.coverage_problems`'tedir
    (`ac_coverage`).

    `ek_set=True` (derinleştirme, P5/P6): çıktı mevcut sete EKtir; `covered_by` kararı ve yeniden
    anılan mevcut öğe mevcut case'lerle kapsanır, AC kapsamı tek başına aranmaz; `not_covered`
    kaydı negatif kategori kodu (`N8`) olabilir (yalnız derinleştirmede)."""
    out = output if isinstance(output, Mapping) else {}
    cases = _kayitlar(out.get("cases"))
    sorunlar = [
        f"C{n}: {s}" for n, case in enumerate(cases, start=1) for s in case_rule_problems(case, out)
    ]
    ogeler = _kayitlar(out.get("coverage_items"))
    kimlikler = [str(o.get("id")) for o in ogeler]
    soru_kimlikleri = [str(q.get("id")) for q in _kayitlar(out.get("open_questions"))]
    for ad, liste in (
        ("kapsam öğesi", kimlikler),
        ("açık soru", soru_kimlikleri),
        ("varsayım", [str(a.get("id")) for a in _kayitlar(out.get("assumptions"))]),
    ):
        cift = sorted({k for k in liste if liste.count(k) > 1})
        if cift:
            sorunlar.append(f"yinelenen {ad} kimliği: {cift}")
    kapsanan = {str(k) for c in cases for k in _liste(c.get("covers"))}
    ac_kapsanan = {str(r) for c in cases for r in _liste(c.get("acceptance_criteria_refs"))}
    kararlar: dict[str, list[Mapping[str, Any]]] = {}
    for karar in _kayitlar(out.get("negative_coverage")):
        kararlar.setdefault(str(karar.get("item")), []).append(karar)
    kapsanmayan = _kayitlar(out.get("not_covered"))
    gerekceli = {str(n.get("item")) for n in kapsanmayan if str(n.get("reason") or "").strip()}
    acler = {str(o.get("ac_ref")) for o in ogeler if o.get("ac_ref")}

    def _kategori(item: str) -> bool:
        if PLATFORM_KATEGORISI.fullmatch(item):
            return True
        return ek_set and NEGATIF_KATEGORISI.fullmatch(item) is not None

    # Karar yalnız tanımlı öğeye; kapsanmayan kaydı tanımlı öğeye, bir kabul kriterine (ACn) ya
    # da kategoriye; `question_ref` tanımlı bir açık soruya.
    tanimsiz = sorted(
        {k for k in kararlar if k not in kimlikler}
        | {
            str(n.get("item"))
            for n in kapsanmayan
            if str(n.get("item")) not in kimlikler
            and not re.fullmatch(r"AC[0-9]+", str(n.get("item")))
            and not _kategori(str(n.get("item")))
        }
    )
    if tanimsiz:
        sorunlar.append(f"tanımsız kapsam öğesine karar/gerekçe: {tanimsiz}")
    tanimsiz_soru = sorted(
        {
            str(n.get("question_ref"))
            for n in kapsanmayan
            if n.get("question_ref") and str(n.get("question_ref")) not in soru_kimlikleri
        }
    )
    if tanimsiz_soru:
        sorunlar.append(f"not_covered.question_ref tanımsız açık soru: {tanimsiz_soru}")
    gecersiz_bolum = {
        str(o.get("id"))
        for o in ogeler
        if o.get("valid") is False and str(o.get("id")).startswith("EP-I")
    }
    for n, case in enumerate(cases, start=1):
        coklu = [str(k) for k in _liste(case.get("covers")) if str(k) in gecersiz_bolum]
        if len(coklu) > 1:
            sorunlar.append(f"C{n}: birden çok geçersiz bölüm kapsıyor: {coklu}")
    for oge in ogeler:
        kimlik = str(oge.get("id"))
        karar_listesi = kararlar.get(kimlik, [])
        kapsayan = [c for c in cases if kimlik in {str(k) for k in _liste(c.get("covers"))}]
        if kapsayan and any(k.get("decision") == "out_of_scope" for k in karar_listesi):
            sorunlar.append(f"{kimlik}: karar out_of_scope ama case kapsıyor")
        kapsam_disi = any(
            k.get("decision") == "out_of_scope" and str(k.get("rationale") or "").strip()
            for k in karar_listesi
        )
        if oge.get("valid") is False:
            if len(karar_listesi) != 1:
                sorunlar.append(
                    f"{kimlik}: negatif kapsam kararı {len(karar_listesi)} adet (1 olmalı)"
                )
            elif not str(karar_listesi[0].get("rationale") or "").strip():
                sorunlar.append(f"{kimlik}: negatif kapsam kararının gerekçesi yok")
        for karar in karar_listesi:
            kararlar_ = ("tested",) if ek_set else ("tested", "covered_by")
            if karar.get("decision") in kararlar_ and kimlik not in kapsanan:
                sorunlar.append(
                    f"{kimlik}: karar {karar.get('decision')} ama hiçbir case kapsamıyor"
                )
        if ek_set:
            continue
        if kimlik not in kapsanan and kimlik not in gerekceli and not kapsam_disi:
            sorunlar.append(f"{kimlik}: kapsanmıyor ve gerekçesi yok")
    for ac in sorted(acler - ac_kapsanan - gerekceli if not ek_set else set()):
        sorunlar.append(f"{ac}: hiçbir case'te yok ve gerekçesi yok")
    for kimlik in yetim_sorular(out):
        sorunlar.append(
            f"{kimlik}: açık soru yetim (hiçbir case atfı, karar gerekçesi, not_covered."
            "question_ref ya da kapsam öğesi anmıyor)"
        )
    return sorunlar
