"""Test tasarım modeli (011 F3, iki tur) — şema ve deterministik model kontrolleri.

Şemanın tek kaynağı `rules/schemas/design_model.schema.json`'dır (`coverage_items`,
`open_questions`, `assumptions` öğeleri case-generation v3 ile birebir aynı biçimdedir: K13).
Model AI çıktısıdır ve insan onayından geçer; onaylı model tur 2'de case üretiminin girdisidir.

Kontroller (`model_problems`, modelden önce gelen deterministik kapı; Constitution XI):

1. Kimlik tekilliği: kapsam öğesi, koşul, açık soru, varsayım, karar tablosu ve durum modeli
   kimlikleri tekildir.
2. Koşul ↔ teknik: her teknik kaydı tanımlı bir koşula bağlıdır; her koşulun en az bir tekniği var.
3. Koşulların ve kapsam öğelerinin AC atıfları gereksinimde vardır (kabul kriterleri verilirse).
4. Ayrıntılı modellerin (bölüm, sınır, karar tablosu kuralı, geçerli/geçersiz geçiş, akış) her
   öğesi `coverage_items`'ta tanımlıdır ve öğenin öneki modelin tekniğine uyar (bölüm `EP-`,
   sınır `BV-`, kural `DT-`, geçiş `ST-`, akış `UC-`); bir öğe tek bir ayrıntılı satıra bağlıdır.
5. Her kapsam öğesinin tekniği (önekinden) bir koşul için seçilmiştir; ayrıntılı model isteyen
   öğe (EG ve PW dışındakiler) ayrıntılı modelde geçer.
6. Geçerlilik: bölümün `valid`'i öğesininkine eşit; `reject` sınır `valid:false`, `accept` sınır
   `valid:true` öğeye bağlı; geçersiz geçiş `valid:false`, geçerli geçiş `valid:true`; `EP-I` öneki
   `valid:false`, `EP-V` öneki `valid:true`.
   `ST-X` (yasak geçiş) öneki `valid:false`, `ST-T` (geçiş) öneki `valid:true`.
7. Ref'ler: `open_question` beklenen sınır, tanımsız karar tablosu kombinasyonu ve tanımsız geçiş
   `question_ref` ile tanımlı bir açık soruya bağlıdır (sınırın öğesi yine `valid` seçer:
   soru yanıtlanınca değişebilir); verilen her `question_ref` tanımlıdır. Karar tablosu kuralının
   koşul değerleri tablonun koşullarının TAMAMIDIR (fazlası da eksiği de yok); geçişlerin
   durumları modelin durumlarıdır; akış türü öğe kimliğine uyar (`UC-MF` ↔ MF …).
8. Sınır değer (BVA, iki değer): her alanda `on` sınır sayısı komşu (`below` / `above`) değer
   sayısına eşittir; alanın hem sınır hem komşu değeri vardır (tek başına sınır ya da tek başına
   komşu değer eksik çifttir).

İhlal: model taslak olarak yazılır, sorunlar gösterilir ve **onay reddedilir** (case kararıyla aynı
desen); insan düzeltmesinde (`edit`) ihlal → 422.

`model_summary(model)` modelden case-generation v3'ün üst düzey listelerini türetir (tur 2'de
case üretiminin `coverage_items` / `open_questions` / `assumptions`'ı bununla aynı olmalıdır).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from tp_core.features.cases.schema import TEKNIK_ONEKI, acceptance_criteria
from tp_core.gateway import find_rules_dir

MAX_HATA = 30
# Tur 2'de modelden aynen kopyalanan üst düzey listeler (case-generation v3 ile ortak biçim).
MODEL_OZET_ALANLARI = ("coverage_items", "open_questions", "assumptions")
# Ayrıntılı model gerektirmeyen teknikler (hata tahmini; pairwise satırı üretilmez).
AYRINTISIZ = frozenset({"EG", "PW", "CL"})  # hata tahmini, pairwise, kontrol listesi


@lru_cache(maxsize=4)
def _schema(rules_dir: str) -> dict[str, Any]:
    path = Path(rules_dir) / "schemas" / "design_model.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def model_schema(rules_dir: Path | None = None) -> dict[str, Any]:
    return _schema(str(find_rules_dir(rules_dir)))


def validate_model(icerik: Any, rules_dir: Path | None = None) -> list[str]:
    """Şema hataları (boş = geçerli); `yol: mesaj` biçiminde, en çok `MAX_HATA`."""
    v = Draft202012Validator(model_schema(rules_dir))
    out = []
    for h in sorted(v.iter_errors(icerik), key=lambda e: list(e.absolute_path)):
        yol = "/".join(str(p) for p in h.absolute_path) or "(kök)"
        out.append(f"{yol}: {h.message}")
        if len(out) >= MAX_HATA:
            break
    return out


def _kayitlar(deger: Any) -> list[Mapping[str, Any]]:
    return [x for x in (deger or []) if isinstance(x, Mapping)] if isinstance(deger, list) else []


def _cift(liste: Iterable[str]) -> list[str]:
    gorulen: set[str] = set()
    cift: set[str] = set()
    for x in liste:
        (cift if x in gorulen else gorulen).add(x)
    return sorted(cift)


def teknik_of(oge_id: str) -> str | None:
    """Kapsam öğesi kimliğinin tekniği (önekten)."""
    for teknik, onek in TEKNIK_ONEKI.items():
        if oge_id.startswith(onek):
            return teknik
    return None


def detail_items(model: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Ayrıntılı modellerdeki `(öğe kimliği, modelin tekniği)` çiftleri (geçiş sırasıyla)."""
    out: list[tuple[str, str]] = []
    out += [(str(p.get("item_id")), "EP") for p in _kayitlar(model.get("partitions"))]
    out += [(str(b.get("item_id")), "BVA") for b in _kayitlar(model.get("boundaries"))]
    for dt in _kayitlar(model.get("decision_tables")):
        out += [(str(r.get("item_id")), "DT") for r in _kayitlar(dt.get("rules"))]
    for sm in _kayitlar(model.get("state_models")):
        out += [(str(t.get("item_id")), "ST") for t in _kayitlar(sm.get("valid_transitions"))]
        out += [(str(t.get("item_id")), "ST") for t in _kayitlar(sm.get("invalid_transitions"))]
    out += [(str(f.get("item_id")), "UC") for f in _kayitlar(model.get("flows"))]
    return out


def _bilinmeyen_ac(refs: Iterable[Any], gecerli: set[str] | None) -> list[str]:
    if gecerli is None:
        return []
    return sorted({str(r) for r in refs if r is not None and str(r) not in gecerli})


def model_problems(
    model: Mapping[str, Any], kabul_kriterleri: Sequence[Any] | None = None
) -> list[str]:
    """Model içi tutarlılık ihlalleri (Türkçe; boş = tutarlı). Şema ayrıca `validate_model`'dir."""
    s: list[str] = []
    ogeler = {str(o.get("id")): o for o in _kayitlar(model.get("coverage_items"))}
    kosullar = _kayitlar(model.get("conditions"))
    teknikler = _kayitlar(model.get("techniques"))
    sorular = _kayitlar(model.get("open_questions"))
    gecerli_ac = (
        {ref for ref, _ in acceptance_criteria(kabul_kriterleri)}
        if kabul_kriterleri is not None
        else None
    )

    # 1. Kimlik tekilliği.
    for ad, liste in (
        ("kapsam öğesi", [str(o.get("id")) for o in _kayitlar(model.get("coverage_items"))]),
        ("koşul", [str(c.get("id")) for c in kosullar]),
        ("açık soru", [str(q.get("id")) for q in sorular]),
        ("varsayım", [str(a.get("id")) for a in _kayitlar(model.get("assumptions"))]),
        ("karar tablosu", [str(d.get("id")) for d in _kayitlar(model.get("decision_tables"))]),
        ("durum modeli", [str(d.get("id")) for d in _kayitlar(model.get("state_models"))]),
    ):
        cift = _cift(liste)
        if cift:
            s.append(f"yinelenen {ad} kimliği: {', '.join(cift)}")

    # 2. Koşul ↔ teknik.
    kosul_ids = {str(c.get("id")) for c in kosullar}
    tanimsiz_kosul = sorted({str(t.get("condition_id")) for t in teknikler} - kosul_ids)
    if tanimsiz_kosul:
        s.append(f"teknik tanımsız koşula bağlı: {', '.join(tanimsiz_kosul)}")
    teknikli = {str(t.get("condition_id")) for t in teknikler}
    for c in kosullar:
        if str(c.get("id")) not in teknikli:
            s.append(f"{c.get('id')}: teknik seçilmemiş")

    # 3. AC atıfları gereksinimde.
    bilinmeyen = _bilinmeyen_ac(
        [r for c in kosullar for r in (c.get("ac_refs") or [])]
        + [o.get("ac_ref") for o in ogeler.values()],
        gecerli_ac,
    )
    if bilinmeyen:
        s.append(f"gereksinimde olmayan kabul kriteri: {', '.join(bilinmeyen)}")

    # 4. Ayrıntılı öğeler coverage_items'ta; önek modelin tekniğine uyar; öğe tek satıra bağlı.
    ayrinti = detail_items(model)
    tanimsiz = sorted({k for k, _ in ayrinti if k not in ogeler})
    if tanimsiz:
        s.append(f"ayrıntılı modelde coverage_items'ta olmayan öğe: {', '.join(tanimsiz)}")
    uyumsuz = sorted({k for k, t in ayrinti if teknik_of(k) != t})
    if uyumsuz:
        s.append(f"öğe kimliği modelin tekniğine uymuyor: {', '.join(uyumsuz)}")
    cift_bag = _cift(k for k, _ in ayrinti)
    if cift_bag:
        s.append(f"öğe birden çok ayrıntılı satıra bağlı: {', '.join(cift_bag)}")

    # 5. Öğenin tekniği seçilmiş; ayrıntı isteyen öğe ayrıntılı modelde.
    secilen = {str(t.get("technique")) for t in teknikler}
    bagli = {k for k, _ in ayrinti}
    for oge_id in ogeler:
        teknik = teknik_of(oge_id)
        if teknik is not None and teknik not in secilen:
            s.append(f"{oge_id}: tekniği ({teknik}) hiçbir koşul için seçilmemiş")
        if teknik is not None and teknik not in AYRINTISIZ and oge_id not in bagli:
            s.append(f"{oge_id}: ayrıntılı modelde yok")

    # 6. Geçerlilik tutarlılığı.
    def gecerli(k: str) -> bool | None:
        o = ogeler.get(k)
        return None if o is None else o.get("valid") is True

    for oge_id in ogeler:
        if oge_id.startswith("EP-I") and gecerli(oge_id):
            s.append(f"{oge_id}: geçersiz bölüm kimliği ama valid:true")
        if oge_id.startswith("EP-V") and gecerli(oge_id) is False:
            s.append(f"{oge_id}: geçerli bölüm kimliği ama valid:false")
        if oge_id.startswith("ST-X") and gecerli(oge_id):
            s.append(f"{oge_id}: yasak geçiş kimliği ama valid:true")
        if oge_id.startswith("ST-T") and gecerli(oge_id) is False:
            s.append(f"{oge_id}: geçiş kimliği ama valid:false")
    for p in _kayitlar(model.get("partitions")):
        k = str(p.get("item_id"))
        if gecerli(k) is not None and gecerli(k) != (p.get("valid") is True):
            s.append(f"{k}: bölümün geçerliliği kapsam öğesiyle çelişiyor")
    soru_var = bool(sorular)
    for b in _kayitlar(model.get("boundaries")):
        k, beklenen = str(b.get("item_id")), b.get("expected")
        if beklenen == "reject" and gecerli(k):
            s.append(f"{k}: reddedilen sınır değer valid:true")
        if beklenen == "accept" and gecerli(k) is False:
            s.append(f"{k}: kabul edilen sınır değer valid:false")
        if beklenen == "open_question" and not soru_var:
            s.append(f"{k}: sınır sonucu açık soru ama open_questions boş")
        if beklenen == "open_question" and not b.get("question_ref"):
            s.append(f"{k}: sınır sonucu açık soru ama question_ref yok")
        if k in ogeler and not isinstance(ogeler[k].get("valid"), bool):
            s.append(f"{k}: sınırın kapsam öğesi valid seçmemiş (true/false)")
        if beklenen in ("accept", "reject") and not str(b.get("inclusive_source") or "").strip():
            s.append(f"{k}: sınırın dahil/hariç kaynağı (inclusive_source) yok")
    for sm in _kayitlar(model.get("state_models")):
        # Durumlar kimlikli nesnedir (`{id: S1, name}`); geçişler kimliğe bağlanır.
        durumlar = {
            str(x.get("id")) if isinstance(x, Mapping) else str(x) for x in sm.get("states") or []
        }
        for t in _kayitlar(sm.get("valid_transitions")):
            k = str(t.get("item_id"))
            if gecerli(k) is False:
                s.append(f"{k}: geçerli geçiş valid:false")
            eksik = {str(t.get("from")), str(t.get("to"))} - durumlar
            if eksik:
                s.append(f"{k}: geçişte tanımsız durum: {', '.join(sorted(eksik))}")
        for t in _kayitlar(sm.get("invalid_transitions")):
            k = str(t.get("item_id"))
            if gecerli(k):
                s.append(f"{k}: geçersiz geçiş valid:true")
            if str(t.get("from")) not in durumlar:
                s.append(f"{k}: geçişte tanımsız durum: {t.get('from')}")
        if sm.get("undefined_transitions") and not soru_var:
            s.append(f"{sm.get('id')}: tanımsız geçiş var ama open_questions boş")
        for metin, ref in _tanimsizlar(sm.get("undefined_transitions")):
            if not ref:
                s.append(
                    f"{sm.get('id')}: tanımsız geçişin açık sorusu (question_ref) yok: {metin}"
                )

    # 7. Karar tablosu ve akış ref'leri.
    for dt in _kayitlar(model.get("decision_tables")):
        tablo_kosul = {str(c) for c in dt.get("conditions") or []}
        for r in _kayitlar(dt.get("rules")):
            adlar = {str(v.get("condition")) for v in _kayitlar(r.get("condition_values"))}
            if adlar - tablo_kosul:
                s.append(
                    f"{r.get('item_id')}: tabloda olmayan koşul: "
                    + ", ".join(sorted(adlar - tablo_kosul))
                )
            if tablo_kosul - adlar:
                s.append(
                    f"{r.get('item_id')}: kuralda değeri verilmeyen koşul: "
                    + ", ".join(sorted(tablo_kosul - adlar))
                )
        if dt.get("undefined_combinations") and not soru_var:
            s.append(f"{dt.get('id')}: tanımsız kombinasyon var ama open_questions boş")
        for metin, ref in _tanimsizlar(dt.get("undefined_combinations")):
            if not ref:
                s.append(
                    f"{dt.get('id')}: tanımsız kombinasyonun açık sorusu (question_ref) yok: "
                    + metin
                )
    for f in _kayitlar(model.get("flows")):
        k, tur = str(f.get("item_id")), str(f.get("kind"))
        if k.startswith("UC-") and not k.removeprefix("UC-").startswith(tur):
            s.append(f"{k}: akış türü ({tur}) kimlikle uyuşmuyor")
    soru_ids = {str(q.get("id")) for q in sorular}
    tanimsiz_soru = sorted({r for r in _question_refs(model) if r not in soru_ids})
    if tanimsiz_soru:
        s.append(f"question_ref tanımlı olmayan açık soruya: {', '.join(tanimsiz_soru)}")

    # 8. Sınır değer çiftleri (alan başına sınır + komşu).
    alanlar: dict[str, list[str]] = {}
    for b in _kayitlar(model.get("boundaries")):
        alanlar.setdefault(str(b.get("field")), []).append(str(b.get("side")))
    for alan, yanlar in alanlar.items():
        on = yanlar.count("on")
        komsu = len(yanlar) - on
        if on != komsu or not on:
            s.append(
                f"sınır değer çifti eksik ({alan}): {on} sınır, {komsu} komşu değer "
                "(her sınır değerin komşu bölümdeki en yakın değeri de olmalı)"
            )
    return s


def _tanimsizlar(deger: Any) -> list[tuple[str, str | None]]:
    """Tanımsız kombinasyon / geçiş kayıtları `(metin, question_ref)`. Eski kayıtta (düz metin)
    `question_ref` yoktur."""
    out: list[tuple[str, str | None]] = []
    for x in deger if isinstance(deger, list) else []:
        if isinstance(x, Mapping):
            metin = str(x.get("description") or "")
            ref = x.get("question_ref")
            out.append((metin, str(ref) if ref else None))
        else:
            out.append((str(x), None))
    return out


def _question_refs(model: Mapping[str, Any]) -> list[str]:
    """Modeldeki tüm `question_ref`'ler (sınır, tanımsız kombinasyon, tanımsız geçiş)."""
    refs = [b.get("question_ref") for b in _kayitlar(model.get("boundaries"))]
    for dt in _kayitlar(model.get("decision_tables")):
        refs += [r for _, r in _tanimsizlar(dt.get("undefined_combinations"))]
    for sm in _kayitlar(model.get("state_models")):
        refs += [r for _, r in _tanimsizlar(sm.get("undefined_transitions"))]
    return [str(r) for r in refs if r]


def model_summary(model: Mapping[str, Any]) -> dict[str, Any]:
    """Modelden case-generation v3 üst düzey listeleri (tur 2'de aynen kopyalanır)."""
    return {alan: [dict(x) for x in _kayitlar(model.get(alan))] for alan in MODEL_OZET_ALANLARI}


def round2_summary(model: Mapping[str, Any], ozet: Mapping[str, Any]) -> dict[str, Any]:
    """Tur 2'nin kayıtlı özeti: `coverage_items` / `open_questions` / `assumptions` ONAYLI
    MODELİN listeleridir (modelin kopyası değil); diğer üst listeler üretimden gelir.

    Böylece modelde olmayan öğeye / soruya / varsayıma atıf yapan case tutarlılık kurallarında
    (`consistency_problems`) yakalanır ve onaylanamaz. Modelin yazdığı kopya yalnız sapma
    karşılaştırmasına girer (`round2_differences`)."""
    return {**dict(ozet), **model_summary(model)}


def round2_differences(model: Mapping[str, Any], ozet: Mapping[str, Any]) -> list[str]:
    """Tur-2 çıktısının üst listeleri onaylı modelinkiyle aynı mı? Farklar (boş = eşit)."""
    beklenen = model_summary(model)
    out: list[str] = []
    for alan in MODEL_OZET_ALANLARI:
        a = beklenen[alan]
        b = [dict(x) for x in _kayitlar(ozet.get(alan))]
        if a == b:
            continue
        ak = [str(x.get("id")) for x in a]
        bk = [str(x.get("id")) for x in b]
        eksik = [k for k in ak if k not in bk]
        fazla = [k for k in bk if k not in ak]
        parca = []
        if eksik:
            parca.append("eksik: " + ", ".join(eksik))
        if fazla:
            parca.append("fazla: " + ", ".join(fazla))
        if not parca:
            parca.append("içerik ya da sıra farklı")
        out.append(f"{alan} onaylı modelden farklı ({'; '.join(parca)})")
    return out


def model_stats(model: Mapping[str, Any]) -> dict[str, Any]:
    """Portal özeti: koşul/öğe/soru sayıları ve teknik dağılımı."""
    teknik: dict[str, int] = {}
    for t in _kayitlar(model.get("techniques")):
        teknik[str(t.get("technique"))] = teknik.get(str(t.get("technique")), 0) + 1
    ogeler = _kayitlar(model.get("coverage_items"))
    return {
        "kosul": len(_kayitlar(model.get("conditions"))),
        "oge": len(ogeler),
        "gecersiz_oge": sum(1 for o in ogeler if o.get("valid") is False),
        "acik_soru": len(_kayitlar(model.get("open_questions"))),
        "varsayim": len(_kayitlar(model.get("assumptions"))),
        "model_sorunu": len(_kayitlar(model.get("model_issues"))),
        "teknik": dict(sorted(teknik.items())),
    }
