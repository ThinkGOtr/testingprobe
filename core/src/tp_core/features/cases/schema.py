"""Test case şeması (TEKNIK-TASARIM §7) ve deterministik içerik kontrolleri.

Şemanın tek kaynağı `rules/schemas/case_generation.schema.json`'daki `cases.items` tanımıdır:
modelin ürettiği, insanın düzelttiği (`edit`) ve IDE'den gelen (`submit_draft_cases`) case'ler
aynı şemayla doğrulanır. Şemaya ek deterministik kurallar (Constitution XI; specs/011 §4.2):

- case'in andığı kabul kriterleri gereksinimde bulunmalıdır (`unknown_ac_refs`);
- case, aynı üretimin üst düzey listeleriyle ("özet": açık sorular, varsayımlar, kapsam öğeleri…)
  tutarlı olmalıdır (`consistency_problems`); set düzeyi kurallar `set_problems`'tadır;
- kapsam matrisi modele yazdırılmaz, `coverage_matrix` ile kodda hesaplanır.

Eski (v2) case (K9): `readiness` anahtarı olmayan içerik `legacy`'dir; hazır sayılır, yalnız v2
alan kümesiyle doğrulanır ve tutarlılık kuralları aranmaz.
"""

from __future__ import annotations

import copy
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from tp_core.gateway import find_rules_dir

AC_DESENI = re.compile(r"^\s*(AC\s*\d+)\s*[:.)\-–]\s*(.*)$", re.IGNORECASE | re.DOTALL)
MAX_HATA = 20

# Üretim çıktısının case dışındaki üst düzey listeleri (`case_uretim.ozet`'e yazılır).
OZET_ALANLARI = (
    "open_questions",
    "assumptions",
    "coverage_items",
    "negative_coverage",
    "not_covered",
    "observations",
    "automation_open_points",
    "config_matrix",
    "testability_gaps",
)
# v2 case'in zorunlu alanları (eski case'ler ve onların düzeltmeleri yalnız bunlarla doğrulanır).
V2_ZORUNLU = (
    "title",
    "type",
    "risk",
    "acceptance_criteria_refs",
    "preconditions",
    "steps",
    "expected_result",
    "tags",
)
READINESS = ("ready", "assumption_dependent", "blocked")
READY = "ready"
# Teknik → kapsam öğesi kimliği öneki (prompt "Traceability" kuralı).
TEKNIK_ONEKI = {
    "EP": "EP-",
    "BVA": "BV-",
    "DT": "DT-",
    "ST": "ST-",
    "PW": "PW-",
    "UC": "UC-",
    "EG": "EG-",
    "CL": "CL-",
}
# Kısa saldırı verisi (ör. `'`) alt dizgi olarak değil, tek başına bir sözcük/simge olarak aranır
# (`bayi'nin` gibi metinler yanlış pozitif vermesin).
KISA_VERI = 4
# Yalnız soru/varsayım bekleyen case'in yazabileceği belirteç (P5/P6: "mesaj metni: AÇIK NOKTA");
# büyük/küçük harf ve Türkçe ı/i farkı gözetilmez.
ACIK_NOKTA = re.compile(r"a[çc][ıiİI]k\s+nokta", re.IGNORECASE)


@lru_cache(maxsize=4)
def _gen_schema(rules_dir: str) -> dict[str, Any]:
    path = Path(rules_dir) / "schemas" / "case_generation.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def generation_schema(rules_dir: Path | None = None) -> dict[str, Any]:
    """Model çıktısının şeması (üst düzey listeler + `cases`)."""
    return _gen_schema(str(find_rules_dir(rules_dir)))


def case_schema(rules_dir: Path | None = None) -> dict[str, Any]:
    """Tek bir case'in şeması: `cases.items` + `$schema` + `$defs` (kapsam öğesi kimliği için)."""
    gen = generation_schema(rules_dir)
    item = dict(gen["properties"]["cases"]["items"])
    item["$schema"] = gen.get("$schema", "https://json-schema.org/draft/2020-12/schema")
    if "$defs" in gen:
        item["$defs"] = gen["$defs"]
    return item


def summary_schema(rules_dir: Path | None = None) -> dict[str, Any]:
    """Üretim özetinin şeması: üst düzey listeler (`cases` hariç); hiçbiri zorunlu değildir.

    IDE taslağıyla gelen `ozet` bununla doğrulanır; verilmeyen liste boş sayılır (`normalize_ozet`).
    """
    gen = generation_schema(rules_dir)
    sema: dict[str, Any] = {
        "$schema": gen.get("$schema", "https://json-schema.org/draft/2020-12/schema"),
        "type": "object",
        "properties": {k: gen["properties"][k] for k in OZET_ALANLARI if k in gen["properties"]},
        "additionalProperties": False,
    }
    if "$defs" in gen:
        sema["$defs"] = gen["$defs"]
    return sema


@lru_cache(maxsize=4)
def _legacy_schema(rules_dir: str) -> dict[str, Any]:
    """Eski (v2) case şeması: yalnız v2 alanları zorunlu; beklenen sonuçlar boş olamaz.

    v3 alanları içerikte varsa yine v3 tanımlarıyla doğrulanır (bilinmeyen alan reddedilir).
    """
    sema = copy.deepcopy(case_schema(Path(rules_dir)))
    # 011 K18: v3 şemasında `risk` yok; eski case'te v2 alanı olarak kalır ve okunur.
    sema["properties"].setdefault("risk", {"type": "string", "enum": ["high", "medium", "low"]})
    sema["required"] = list(V2_ZORUNLU)
    sema["properties"]["expected_result"]["minLength"] = 1
    sema["properties"]["steps"]["items"]["properties"]["expected"]["minLength"] = 1
    return sema


def _yol(hata: Any) -> str:
    return "/".join(str(p) for p in hata.absolute_path) or "(kök)"


def _sema_hatalari(sema: Mapping[str, Any], icerik: Any) -> list[str]:
    validator = Draft202012Validator(sema)
    hatalar = sorted(validator.iter_errors(icerik), key=lambda e: [str(p) for p in e.absolute_path])
    return [f"{_yol(h)}: {h.message}" for h in hatalar[:MAX_HATA]]


def validate_case(icerik: Any, rules_dir: Path | None = None, *, legacy: bool = False) -> list[str]:
    """Şema hataları (boş liste = geçerli). Mesajlar `alan/yolu: açıklama` biçimindedir.

    `legacy=True` (K9): yalnız v2 zorunlu alanları aranır.
    """
    if legacy:
        return _sema_hatalari(_legacy_schema(str(find_rules_dir(rules_dir))), icerik)
    return _sema_hatalari(case_schema(rules_dir), icerik)


def validate_summary(ozet: Any, rules_dir: Path | None = None) -> list[str]:
    """Üretim özetinin (üst düzey listeler) şema hataları + yinelenen kimlikler."""
    hatalar = _sema_hatalari(summary_schema(rules_dir), ozet)
    if hatalar or not isinstance(ozet, Mapping):
        return hatalar
    for alan in ("open_questions", "assumptions", "coverage_items"):
        sayim = Counter(str(x.get("id")) for x in ozet.get(alan) or [])
        tekrar = sorted(k for k, n in sayim.items() if n > 1)
        if tekrar:
            hatalar.append(f"{alan}: yinelenen kimlik: " + ", ".join(tekrar))
    return hatalar


def normalize_ozet(ozet: Mapping[str, Any] | None) -> dict[str, Any]:
    """Özet, tüm üst düzey alanlarıyla (eksik liste boş; `cases` ve bilinmeyen anahtar atılır)."""
    ozet = ozet or {}
    out: dict[str, Any] = {}
    for alan in OZET_ALANLARI:
        if alan == "config_matrix":
            cm = ozet.get(alan) if isinstance(ozet.get(alan), Mapping) else {}
            out[alan] = {
                "parameters": list(cm.get("parameters") or []),
                "constraints": list(cm.get("constraints") or []),
            }
        else:
            out[alan] = list(ozet.get(alan) or [])
    return out


# ------------------------------------------------------------------ hazır olma / eski case


def is_legacy(icerik: Mapping[str, Any] | None) -> bool:
    """Eski (v2) case mi: `readiness` anahtarı yok (K9)."""
    return not isinstance(icerik, Mapping) or "readiness" not in icerik


def readiness_of(icerik: Mapping[str, Any] | None) -> str:
    """Case'in hazır olma durumu; eski (v2) case `ready` sayılır (K9)."""
    if is_legacy(icerik):
        return READY
    return str((icerik or {}).get("readiness") or "")


# ------------------------------------------------------------------------ kabul kriterleri


def acceptance_criteria(kabul_kriterleri: Sequence[Any]) -> list[tuple[str, str]]:
    """Gereksinimin kabul kriterleri `(ref, metin)` listesi.

    Kayıt biçimleri: `"AC1: metin"` (Jira adaptörü), `{"ref": "AC1", "metin": "..."}` (portal),
    `{"id"/"key": ..., "text": ...}`. Ref'i olmayan maddeler sırayla `AC<n>` alır.
    """
    out: list[tuple[str, str]] = []
    for i, ac in enumerate(kabul_kriterleri or [], start=1):
        if isinstance(ac, Mapping):
            ref = str(ac.get("ref") or ac.get("id") or ac.get("key") or f"AC{i}")
            metin = str(ac.get("metin") or ac.get("text") or ac.get("aciklama") or "")
        else:
            m = AC_DESENI.match(str(ac))
            ref, metin = (m.group(1), m.group(2)) if m else (f"AC{i}", str(ac))
        out.append((re.sub(r"\s+", "", ref).upper(), metin.strip()))
    return out


def unknown_ac_refs(icerik: Mapping[str, Any], kabul_kriterleri: Sequence[Any]) -> list[str]:
    """Case'in andığı ama gereksinimde olmayan kabul kriterleri (gereksinimde AC yoksa boş)."""
    bilinen = {ref for ref, _ in acceptance_criteria(kabul_kriterleri)}
    if not bilinen:
        return []
    refs = icerik.get("acceptance_criteria_refs") or []
    return sorted({str(r) for r in refs if str(r).upper() not in bilinen})


def _ac_refs(case: Mapping[str, Any]) -> set[str]:
    return {str(r).replace(" ", "").upper() for r in (case.get("acceptance_criteria_refs") or [])}


def uncovered_acs(cases: Sequence[Mapping[str, Any]], kabul_kriterleri: Sequence[Any]) -> list[str]:
    """Hiçbir case'in referans vermediği kabul kriterleri (prompt: her AC en az bir case'te)."""
    kapsanan = {r for c in cases for r in _ac_refs(c)}
    return [ref for ref, _ in acceptance_criteria(kabul_kriterleri) if ref not in kapsanan]


# ---------------------------------------------------------------------- tutarlılık (§4.2)


def _kimlikler(ozet: Mapping[str, Any], alan: str, anahtar: str = "id") -> set[str]:
    return {str(x.get(anahtar)) for x in (ozet.get(alan) or []) if isinstance(x, Mapping)}


def _sade(deger: Any) -> str:
    return re.sub(r"\s+", " ", str(deger or "")).strip().casefold()


def _dolu(deger: Any) -> bool:
    return bool(str(deger or "").strip())


def _case_metinleri(case: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Saldırı verisinin geçmemesi gereken alanlar: `(alan adı, metin)`."""
    out = [("title", case.get("title")), ("expected_result", case.get("expected_result"))]
    out += [(f"preconditions[{i}]", m) for i, m in enumerate(case.get("preconditions") or [], 1)]
    for adim in case.get("steps") or []:
        if not isinstance(adim, Mapping):
            continue
        for alan in ("action", "data", "expected"):
            out.append((f"steps[{adim.get('id')}].{alan}", adim.get(alan)))
    out += [(f"teardown[{i}]", m) for i, m in enumerate(case.get("teardown") or [], 1)]
    return [(ad, _sade(m)) for ad, m in out if _dolu(m)]


def veri_geciyor(deger: str, metin: str) -> bool:
    """Sadeleştirilmiş saldırı verisi sadeleştirilmiş metinde geçiyor mu? Kısa veri (`KISA_VERI`
    karakterden az; ör. `'`, `--`) yalnız tek başına (boşlukla ayrılmış) geçtiğinde sayılır."""
    if not deger:
        return False
    if len(deger) >= KISA_VERI:
        return deger in metin
    return re.search(rf"(?<!\S){re.escape(deger)}(?!\S)", metin) is not None


def consistency_problems(case: Mapping[str, Any], ozet: Mapping[str, Any] | None) -> list[str]:
    """Case'in, üretiminin özetiyle ve kendi içinde tutarsızlıkları (boş = tutarlı; §4.2 1–6).

    Eski (v2) case'te kural aranmaz. `ozet=None` (üretim özeti kayıtlı değil / IDE özet
    göndermedi): kapsam öğelerinin tanımlılığı (kural 1) denetlenemez ve atlanır; açık soru /
    varsayım atıfları ise tanımsız sayılır (metni gösterilemeyen atıf kabul edilmez).
    """
    if is_legacy(case):
        return []
    sorunlar: list[str] = []
    covers = [str(x) for x in case.get("covers") or []]
    teknikler = [str(x) for x in case.get("technique") or []]
    a_refs = [str(x) for x in case.get("assumption_refs") or []]
    q_refs = [str(x) for x in case.get("open_question_refs") or []]
    oz = ozet or {}

    if ozet is not None:
        tanimli = _kimlikler(oz, "coverage_items")
        eksik = [c for c in covers if c not in tanimli]
        if eksik:
            sorunlar.append("covers: tanımlı olmayan kapsam öğesi: " + ", ".join(eksik))
    for teknik in teknikler:
        onek = TEKNIK_ONEKI.get(teknik)
        if onek and not any(c.startswith(onek) for c in covers):
            sorunlar.append(
                f"technique: {teknik} tekniği için covers'ta '{onek}…' kapsam öğesi yok"
            )
    onekler = {TEKNIK_ONEKI[t] for t in teknikler if t in TEKNIK_ONEKI}
    sahipsiz = [c for c in covers if not any(c.startswith(o) for o in onekler)]
    if sahipsiz:
        sorunlar.append("covers: technique'te tekniği olmayan kapsam öğesi: " + ", ".join(sahipsiz))
    eksik_a = [r for r in a_refs if r not in _kimlikler(oz, "assumptions")]
    if eksik_a:
        sorunlar.append("assumption_refs: tanımlı olmayan varsayım: " + ", ".join(eksik_a))
    eksik_q = [r for r in q_refs if r not in _kimlikler(oz, "open_questions")]
    if eksik_q:
        sorunlar.append("open_question_refs: tanımlı olmayan açık soru: " + ", ".join(eksik_q))

    durum = readiness_of(case)
    bos_adimlar = [
        str(a.get("id"))
        for a in case.get("steps") or []
        if isinstance(a, Mapping) and not _dolu(a.get("expected"))
    ]
    beklenen_dolu = _dolu(case.get("expected_result"))
    if durum == READY:
        if a_refs or q_refs:
            sorunlar.append(
                "readiness: 'ready' case varsayıma ya da açık soruya atıf yapamaz "
                "(assumption_refs ve open_question_refs boş olmalı)"
            )
    elif durum == "assumption_dependent":
        if not a_refs:
            sorunlar.append(
                "readiness: 'assumption_dependent' case en az bir varsayıma atıf yapmalı "
                "(assumption_refs boş)"
            )
    elif durum == "blocked":
        if not q_refs:
            sorunlar.append(
                "readiness: 'blocked' case en az bir açık soruya atıf yapmalı "
                "(open_question_refs boş)"
            )
        if beklenen_dolu:
            sorunlar.append(
                "readiness: 'blocked' case'in beklenen sonucu (expected_result) boş olmalı; "
                "soru yanıtlanmadan beklenen sonuç yazılmaz"
            )
    if durum in (READY, "assumption_dependent"):
        if not beklenen_dolu:
            sorunlar.append(f"expected_result: '{durum}' case'te beklenen sonuç boş olamaz")
        if bos_adimlar:
            sorunlar.append(
                f"steps: '{durum}' case'te adımın beklenen sonucu boş olamaz: "
                + ", ".join(bos_adimlar)
            )

    metinler = _case_metinleri(case)
    acik_nokta = [alan for alan, metin in metinler if ACIK_NOKTA.search(metin)]
    if acik_nokta:
        if durum == READY:
            sorunlar.append(
                "readiness: 'ready' case 'AÇIK NOKTA' içeremez (" + ", ".join(acik_nokta) + "); "
                "bilinmeyen nokta varsayım ya da açık soruyla işaretlenir"
            )
        elif not (a_refs or q_refs):
            sorunlar.append(
                "'AÇIK NOKTA' bir açık soru ya da varsayım atfı gerektirir ("
                + ", ".join(acik_nokta)
                + "); open_question_refs / assumption_refs boş"
            )
    for veri in case.get("test_data") or []:
        if not isinstance(veri, Mapping):
            continue
        ad = str(veri.get("name"))
        if veri.get("synthetic") is not True:
            sorunlar.append(f"test_data[{ad}]: test verisi sentetik olmalı (synthetic: true)")
        deger = _sade(veri.get("value"))
        if veri.get("is_attack_payload") is True and deger:
            gecen = [alan for alan, metin in metinler if veri_geciyor(deger, metin)]
            if gecen:
                sorunlar.append(
                    f"test_data[{ad}]: saldırı verisi yalnız test_data'da yer alır; şu alanlarda "
                    "da geçiyor: " + ", ".join(gecen) + " (adımlar veriye adıyla atıf yapmalı)"
                )
    return sorunlar


def set_problems(
    cases: Sequence[Mapping[str, Any]],
    ozet: Mapping[str, Any] | None,
    kabul_kriterleri: Sequence[Any],
    *,
    korunan: Sequence[Mapping[str, Any]] = (),
) -> list[str]:
    """Set düzeyi tutarsızlıklar (§4.2): negatif kapsam kararları ve kapsanmayanların gerekçesi.

    - her `valid: false` kapsam öğesinin tam bir `negative_coverage` kararı vardır;
    - `tested` / `covered_by` kararlı öğe en az bir case'in `covers`'ındadır (yalnız soru bekleyen
      case'lerle kapsanması tutarsızlık değil, hazır olma uyarısıdır: `readiness_warnings`);
    - `out_of_scope` kararlı öğe hiçbir case'in `covers`'ında değildir (karar ile set çelişir);
    - [Ekip] case başına tek geçersiz değer: iki ya da daha çok geçersiz eşdeğerlik bölümünü
      (`EP-I…`, `valid: false`) kapsayan case uyarı alır (hatanın nedeni ayrışmaz). Sınır değer
      ya da hata tahmini öğesi aynı geçersiz değeri başka teknikle andığı için sayılmaz;
    - hiçbir case'in kapsamadığı öğe `not_covered`'da ya da `out_of_scope` kararında, kapsanmayan
      kabul kriteri `not_covered`'da gerekçelidir.

    `korunan`: üretimde korunan (önceki üretimlerin onaylı/yayınlı ya da IDE) case'leri; yalnız
    kabul kriteri kapsamına sayılır (kapsam öğesi kimlikleri kendi üretimlerine aittir).
    """
    oz = ozet or {}
    ogeler = [x for x in oz.get("coverage_items") or [] if isinstance(x, Mapping)]
    kararlar = [x for x in oz.get("negative_coverage") or [] if isinstance(x, Mapping)]
    gerekceli = {_ac_ya_da_oge(x.get("item")) for x in oz.get("not_covered") or []}
    kapsanan = {str(c) for case in cases for c in (case.get("covers") or [])}
    tanimli = {str(o.get("id")) for o in ogeler}
    gecersiz_bolum = {
        str(o.get("id"))
        for o in ogeler
        if o.get("valid") is False and str(o.get("id")).startswith("EP-I")
    }
    karar_sayisi = Counter(str(k.get("item")) for k in kararlar)
    karar_of = {str(k.get("item")): str(k.get("decision")) for k in kararlar}
    sorunlar: list[str] = []

    for kimlik in sorted(set(karar_sayisi) - tanimli):
        sorunlar.append(f"negative_coverage: tanımlı olmayan kapsam öğesi: {kimlik}")
    for o in ogeler:
        kimlik = str(o.get("id"))
        n = karar_sayisi.get(kimlik, 0)
        if o.get("valid") is False and n != 1:
            sorunlar.append(
                f"{kimlik}: geçersiz (valid: false) kapsam öğesi için "
                + ("negatif kapsam kararı yok" if n == 0 else f"{n} negatif kapsam kararı var")
                + " (tam bir karar gerekir)"
            )
        karar = karar_of.get(kimlik)
        if kimlik in kapsanan:
            if karar == "out_of_scope":
                sorunlar.append(
                    f"{kimlik}: negatif kapsam kararı 'out_of_scope' ama case kapsıyor "
                    "(karar ya da case düzeltilmeli)"
                )
            continue
        if karar in ("tested", "covered_by"):
            sorunlar.append(
                f"{kimlik}: negatif kapsam kararı '{karar}' ama hiçbir case'in covers'ında yok"
            )
        elif karar != "out_of_scope" and kimlik not in gerekceli:
            sorunlar.append(
                f"{kimlik}: hiçbir case kapsamıyor; not_covered'da ya da 'out_of_scope' "
                "kararında gerekçesi yok"
            )
    for no, case in enumerate(cases, start=1):
        coklu = [str(c) for c in case.get("covers") or [] if str(c) in gecersiz_bolum]
        if len(coklu) > 1:
            sorunlar.append(
                f"C{no}: birden çok geçersiz eşdeğerlik bölümü kapsıyor ("
                + ", ".join(coklu)
                + "); [Ekip] case başına tek geçersiz değer"
            )
    for ref in uncovered_acs([*cases, *korunan], kabul_kriterleri):
        if ref not in gerekceli:
            sorunlar.append(f"{ref}: hiçbir case kapsamıyor; not_covered'da gerekçesi yok")
    return sorunlar


def readiness_warnings(
    cases: Sequence[Mapping[str, Any]], ozet: Mapping[str, Any] | None
) -> list[str]:
    """Set düzeyi hazır olma uyarıları (tutarsızlık değil; onay engellemez): `tested` kararlı
    öğeyi yalnız açık soru bekleyen (`blocked`) case'ler kapsıyorsa öğe henüz test edilmiş
    sayılmaz (beklenen sonuç yok). Kapsam matrisinin `covered_by_ready` sütunu aynı durumu
    satır düzeyinde gösterir."""
    sorunlar: list[str] = []
    for k in (ozet or {}).get("negative_coverage") or []:
        if not isinstance(k, Mapping) or str(k.get("decision")) != "tested":
            continue
        kimlik = str(k.get("item"))
        kapsayan = [c for c in cases if kimlik in {str(x) for x in (c.get("covers") or [])}]
        if kapsayan and all(readiness_of(c) == "blocked" for c in kapsayan):
            sorunlar.append(
                f"{kimlik}: negatif kapsam kararı 'tested' ama yalnız açık soru bekleyen "
                "(blocked) case kapsıyor; soru yanıtlanana kadar test edilmiş sayılmaz"
            )
    return sorunlar


def _ac_ya_da_oge(item: Any) -> str:
    """`not_covered.item` serbest metindir: `ac 2` → `AC2`; kapsam öğesi kimliği olduğu gibi."""
    metin = str(item or "").strip()
    return re.sub(r"\s+", "", metin).upper() if re.fullmatch(r"(?i)ac\s*\d+", metin) else metin


def _oran(kapsanan: int, toplam: int) -> dict[str, Any]:
    return {
        "kapsanan": kapsanan,
        "toplam": toplam,
        "oran": round(kapsanan / toplam, 4) if toplam else None,
    }


def coverage_matrix(
    cases: Sequence[Mapping[str, Any]],
    ozet: Mapping[str, Any] | None,
    kabul_kriterleri: Sequence[Any],
) -> dict[str, Any]:
    """Kapsam matrisi (kodda hesaplanır; model yazmaz): `{"satirlar": [...], "oranlar": {...}}`.

    Satır: `{item, tur: "ac"|"oge", tanim, valid, ac_ref, karar, covered_by, covered_by_ready,
    gerekce}`. `covered_by` case'in `cases` içindeki 1 tabanlı sırasıdır; `covered_by_ready`
    bunların hazır (`ready`; eski v2 case hazır sayılır) olanlarıdır. `gerekce`: `not_covered`
    nedeni, yoksa negatif kapsam kararının gerekçesi. Oranlar: gereksinim (AC) kapsamı, öğe
    kapsamı, negatif karar kapsamı (kararı olan `valid: false` öğeler) ve yalnız hazır case'lerle
    hazır gereksinim / öğe kapsamı (varsayıma bağlı ya da soru bekleyen case kapsamı
    tamamlamaz); payda 0 ise oran `None`.
    """
    hazir = {i for i, c in enumerate(cases, start=1) if readiness_of(c) == READY}
    oz = ozet or {}
    neden = {
        _ac_ya_da_oge(x.get("item")): str(x.get("reason") or "")
        for x in oz.get("not_covered") or []
        if isinstance(x, Mapping)
    }
    kararlar = {
        str(k.get("item")): k for k in oz.get("negative_coverage") or [] if isinstance(k, Mapping)
    }
    satirlar: list[dict[str, Any]] = []
    for ref, metin in acceptance_criteria(kabul_kriterleri):
        satirlar.append(
            {
                "item": ref,
                "tur": "ac",
                "tanim": metin,
                "valid": None,
                "ac_ref": ref,
                "karar": None,
                "covered_by": [i for i, c in enumerate(cases, start=1) if ref in _ac_refs(c)],
                "gerekce": neden.get(ref) or None,
            }
        )
    ac_sayisi = len(satirlar)
    negatif = kararli = 0
    for o in oz.get("coverage_items") or []:
        if not isinstance(o, Mapping):
            continue
        kimlik = str(o.get("id"))
        karar = kararlar.get(kimlik)
        if o.get("valid") is False:
            negatif += 1
            kararli += karar is not None
        satirlar.append(
            {
                "item": kimlik,
                "tur": "oge",
                "tanim": str(o.get("definition") or ""),
                "valid": o.get("valid"),
                "ac_ref": o.get("ac_ref"),
                "karar": str(karar.get("decision")) if karar else None,
                "covered_by": [
                    i
                    for i, c in enumerate(cases, start=1)
                    if kimlik in {str(x) for x in (c.get("covers") or [])}
                ],
                "gerekce": neden.get(kimlik)
                or (str(karar.get("rationale") or "") if karar else "")
                or None,
            }
        )
    for satir in satirlar:
        satir["covered_by_ready"] = [i for i in satir["covered_by"] if i in hazir]
    ac_satirlari, oge_satirlari = satirlar[:ac_sayisi], satirlar[ac_sayisi:]
    return {
        "satirlar": satirlar,
        "oranlar": {
            "gereksinim_kapsami": _oran(
                sum(bool(s["covered_by"]) for s in ac_satirlari), ac_sayisi
            ),
            "oge_kapsami": _oran(
                sum(bool(s["covered_by"]) for s in oge_satirlari), len(oge_satirlari)
            ),
            "negatif_karar_kapsami": _oran(kararli, negatif),
            "hazir_gereksinim_kapsami": _oran(
                sum(bool(s["covered_by_ready"]) for s in ac_satirlari), ac_sayisi
            ),
            "hazir_oge_kapsami": _oran(
                sum(bool(s["covered_by_ready"]) for s in oge_satirlari), len(oge_satirlari)
            ),
        },
    }


# ------------------------------------------------------------------ birleşik içerik denetimi


def content_errors(
    icerik: Any,
    kabul_kriterleri: Sequence[Any],
    rules_dir: Path | None = None,
    *,
    ozet: Mapping[str, Any] | None = None,
    legacy: bool = False,
) -> list[str]:
    """Şema + kabul kriteri atıfı + tutarlılık (insan düzeltmesi ve IDE taslağı için; ihlal → 422).

    `legacy=True`: eski (v2) case'in düzeltmesi; yalnız v2 alanları ve AC atıfı denetlenir.
    Aksi halde tam v3 şeması ve `consistency_problems(icerik, ozet)`.
    """
    hatalar = validate_case(icerik, rules_dir, legacy=legacy)
    if hatalar or not isinstance(icerik, Mapping):
        return hatalar
    bilinmeyen = unknown_ac_refs(icerik, kabul_kriterleri)
    if bilinmeyen:
        hatalar.append(
            "acceptance_criteria_refs: gereksinimde olmayan kabul kriteri: " + ", ".join(bilinmeyen)
        )
    if not legacy:
        hatalar += consistency_problems(icerik, ozet)
    return hatalar


def rule_reask_enabled() -> bool:
    """Kural ihlalinde modelden düzeltme isteme (`Gateway.call(output_check=…)`) açık mı?
    `TP_KURAL_YENIDEN_ISTEME=off` ile kapatılır (birim testleri bilerek tutarsız sahte çıktı
    kullanır); varsayılan açık."""
    import os

    return os.environ.get("TP_KURAL_YENIDEN_ISTEME", "on").strip().lower() != "off"


def generation_output_problems(
    output: Mapping[str, Any],
    kabul_kriterleri: Sequence[Any],
    *,
    korunan: Sequence[Mapping[str, Any]] = (),
) -> list[str]:
    """Bir üretim çıktısının (`{cases, …üst listeler}`) deterministik kural ihlalleri: case başına
    §4.2 tutarlılığı (`C<n>: …` önekiyle), gereksinimde olmayan AC atfı ve set düzeyi kurallar.
    Geçit bunu canlı çağrıda `output_check` olarak kullanır: ihlal varsa model düzeltmeye
    yönlendirilir (011 — canlı eval 2026-11-12: dağınık tutarlılık hataları)."""
    if not isinstance(output, Mapping):
        return []
    cases = [c for c in output.get("cases") or [] if isinstance(c, Mapping)]
    ozet = normalize_ozet({k: v for k, v in output.items() if k != "cases"})
    out: list[str] = []
    for n, case in enumerate(cases, start=1):
        out += [f"C{n}: {p}" for p in consistency_problems(case, ozet)]
        bilinmeyen = unknown_ac_refs(case, kabul_kriterleri)
        if bilinmeyen:
            out.append(f"C{n}: acceptance_criteria_refs: source has no {', '.join(bilinmeyen)}")
    # Korunan (önceki üretimlerden onaylı/yayınlı) case'lerin kapsadığı AC eksik sayılmaz.
    out += set_problems(cases, ozet, kabul_kriterleri, korunan=korunan)
    return out
