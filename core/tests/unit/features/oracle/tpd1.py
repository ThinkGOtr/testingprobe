"""Demo story TPD-1 için karar tabloları ve `case_facts` golden'larının kaynağı (012 §4.3 REPLAY).

`TABLOLAR`: Ş1'in AI taslak golden'ından (`rules/replay/decision_table_draft/golden/TPD-1.json`)
YÜKLENİR — analistin düzenleyip PO'nun demoda onayladığı tablolar bunlardır; burada kopya yoktur.
T2'de AI'ın sınır yorumu yanlıştır (`<= 750`, `T2_TASLAK`); onaylı T2 `< 750`'dir (review 2 u2 N2).
Model çıktısı `karar_tablosu.service.taslak_tablo_icerigi` ile içerik biçimine çevrilir (worker'ın
yazdığıyla aynı). T1 "Kampanya: 6 al 1 bedava (7 adette 1 bedava)" (AC2; girdiler `adet`,
`birim_fiyat`; çıktılar `bedava_adet = adet // 7`, `indirim`), T2 "Minimum sipariş tutarı" (AC3,
AC6; girdiler `kampanyali_sepet`, `sepet_tutari`; çıktı `minimum_uyarisi`, eşik 750). Tablolar
story'yi izler (7 adette 1 bedava), demo uygulamanın kodunu değil (`adet // 6`).

`OLGULAR`: case_generation golden'larının case'lerinden dikkatli bir modelin çıkaracağı olgular.
Alıntılar case alanlarından birebirdir; deterministik doğrulama (`features/oracle/dogrulama.py`)
hepsini kabul eder (`test_cikarma_golden.py` denetler). Bir değer case'te birden çok yerde
geçiyorsa (başlık, eylem, veri, beklenen, sonuç) her geçiş ayrı olgudur: metamorfik türetme
değişen her alıntının bütün kopyalarını ister. Case'lerde birim fiyat yazmaz: `birim_fiyat` olgusu
YOKTUR (uydurulmaz); T1'de birim fiyata dayanan `indirim` yalnız R2'de (7'den az, sabit 0)
karşılaştırılır, R1'de `karsilastirilamayan` olur (`dogrulama.kismi_degerlendir`).

İki case kaynağı vardır:

- Ana golden (`case_generation/golden/TPD-1.json`): F2 `fix_doc` alternatifi + senaryonun
  değişmeyen case'leri. C3 burada "6 adette 1 bedava"dır (koda uyarlanmış AC2).
- Senaryo golden'ı `f2-kod-hatasi/TPD-1.json` (demo ANA yolu, AC2 özgün): tek farkı C3'tür —
  "6 adette bedava yok" (story). `case_facts` golden'ı `f2-kod-hatasi/TPD-1-C3.json`'dur.

AC1/AC4/AC5 case'leri (C1, C7, C8) hiçbir tabloyla kesişmez (`kapsam_disi`, model çağrılmaz) ve
golden'ı yoktur.

Golden'lar bu modülden üretilir:

    cd core && uv run python -m tests.unit.features.oracle.tpd1

`test_cikarma_golden.py` depodaki golden'ların bu modülün çıktısıyla aynı olduğunu denetler.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from tp_core.gateway import approved_case_text, find_rules_dir, golden_name

RULES = find_rules_dir()
STORY = "TPD-1"
SENARYO = "f2-kod-hatasi"  # demo ana yolu (AC2 özgün; F2 code_defect)
_NS = uuid.UUID("6c1b5a1e-0f6e-4a55-9d5e-012000000001")


def taslak_golden() -> dict[str, Any]:
    path = RULES / "replay" / "decision_table_draft" / "golden" / f"{STORY}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _tablolar() -> dict[int, dict[str, Any]]:
    from tp_core.features.karar_tablosu.service import taslak_tablo_icerigi

    out: dict[int, dict[str, Any]] = {}
    for n, oge in enumerate(taslak_golden()["output"]["tables"], start=1):
        icerik, hatalar = taslak_tablo_icerigi(oge)
        assert not hatalar, hatalar
        out[n] = icerik
    return out


def _iliski() -> dict[str, Any]:
    from tp_core.features.karar_tablosu.service import taslak_iliski_icerigi

    [oge] = taslak_golden()["output"]["relations"]
    icerik, hatalar = taslak_iliski_icerigi(oge)
    assert not hatalar, hatalar
    return {**icerik, "tablo_ref": oge["tablo_ref"]}


def _t2_duzeltilmis(taslak: dict[str, Any]) -> dict[str, Any]:
    """AI taslağının T2'si sınırı yanlış yorumlar (`sepet_tutari <= 750`: tam 750,00 TL'de uyarı;
    review 2 u2 N2). Demo: PO sınır örneklerinde yakalar → değişiklik ister → analist `< 750`
    yapar → PO onaylar. Onaylı (düzeltilmiş) T2 budur; oracle testleri bunu kullanır."""
    out = json.loads(json.dumps(taslak))
    for satir in out["satirlar"]:
        if satir["id"] == "R2":
            assert satir["kosul"] == "sepet_tutari <= 750", satir
            satir["kosul"] = "sepet_tutari < 750"
            satir["aciklama"] = "AC3: 750,00 TL altında uyarı"
        elif satir["id"] == "R3":
            satir["aciklama"] = "750,00 TL ve üstü: uyarı yok"
    return out


_TASLAK = _tablolar()  # AI taslağı (golden'daki hâli)
T2_TASLAK = _TASLAK[2]
# sira_no → PO'nun onayladığı içerik (ref `T<sira_no>`): T1 taslakla aynı, T2 düzeltilmiş.
TABLOLAR = {1: _TASLAK[1], 2: _t2_duzeltilmis(T2_TASLAK)}
T1, T2 = TABLOLAR[1], TABLOLAR[2]
ILISKI = _iliski()  # T1: adet 7'nin katıyken ×2 → bedava adet ve indirim ×2


def tablo_id(sira_no: int) -> str:
    """Değerlendirme setinde ve birim testlerde kullanılan sabit tablo kimliği."""
    return str(uuid.uuid5(_NS, f"{STORY}:T{sira_no}"))


def kolon_girdisi() -> list[dict[str, Any]]:
    """`cikarma.facts_messages`'a giden tablo listesi (sabit kimliklerle)."""
    return [{"ref": f"T{n}", "id": tablo_id(n), "icerik": TABLOLAR[n]} for n in sorted(TABLOLAR)]


def _o(column: str, value: Any, field: str, quote: str) -> dict[str, Any]:
    return {"column": column, "value": value, "field": field, "quote": quote}


S3_EYLEM, S3_VERI, S3_BEKLENEN = "steps[2].action", "steps[2].data", "steps[2].expected"
S4 = "steps[3].expected"
SONUC = "expected_result"


def _kampanya(
    adet: str,
    bedava: str,
    ara_toplam: str,
    indirim: str,
    toplam: str,
    *,
    adet_baslikta: bool,
    bedava_metinde: bool,
) -> dict[str, Any]:
    """T1 grubu (V9: girdiler adet, ara_toplam; çıktılar bedava_adet, indirim, toplam). Adet: S3
    eylemi ("adedi 7"), verisi ("P-001 × 7"), beklenen sayaç ("Sepet sayacı 7"), S4 satırı
    ("adet 7"), sonuç ("7 adette") ve varsa başlık. Bedava: S4 ve sonuçtaki "bedava adet N"
    ("adet N" alıntısı) ya da "N adet bedava" ("N adet"). Ara toplam yalnız S4'te; indirim ve
    toplam S4 ve sonuçta. Her geçiş ayrı olgudur (prompt: değerin her geçişi)."""
    girdi = [
        _o("adet", adet, alan, adet)
        for alan in (
            *(("title",) if adet_baslikta else ()),
            S3_EYLEM,
            S3_VERI,
            S3_BEKLENEN,
            S4,
            SONUC,
        )
    ]
    girdi.append(_o("ara_toplam", _ondalik(ara_toplam), S4, f"{ara_toplam} TL"))
    bedava_olgulari = [_o("bedava_adet", bedava, S4, f"adet {bedava}")]
    if bedava_metinde:  # "… 1 adet bedava verilir" (başlık ve sonuç)
        bedava_olgulari = [
            _o("bedava_adet", bedava, "title", f"{bedava} adet"),
            *bedava_olgulari,
            _o("bedava_adet", bedava, SONUC, f"{bedava} adet"),
        ]
    else:  # "… bedava adet 0 olur" (sonuç)
        bedava_olgulari.append(_o("bedava_adet", bedava, SONUC, f"adet {bedava}"))
    return {
        "table_ref": "T1",
        "inputs": girdi,
        "expected": [
            *bedava_olgulari,
            *(_o("indirim", _ondalik(indirim), a, f"{indirim} TL") for a in (S4, SONUC)),
            *(_o("toplam", _ondalik(toplam), a, f"{toplam} TL") for a in (S4, SONUC)),
        ],
    }


def _ondalik(tl: str) -> str:
    return tl.replace(".", "").replace(",", ".")


def _yok(field: str, quote: str, reason: str) -> dict[str, str]:
    return {"field": field, "quote": quote, "reason": reason}


def _sayac(n: int, urun: str) -> list[dict[str, str]]:
    """T2 case'lerinde sepet sayacı ve S3 verisindeki ürün adedi tablonun kolonu değildir
    (`ignored`; review 2 g2 Y14: girdi alanlarındaki sayılar da taranır)."""
    return [
        _yok(S3_VERI, f"{urun} × {n}", "ürün kodu ve adedi; tabloda kolonu yok"),
        _yok(S3_BEKLENEN, f"Sepet sayacı {n}", "sepetteki ürün adedi; tabloda kolonu yok"),
    ]


KAMPANYASIZ = (False, "preconditions[1]", "Sepette kampanyalı ürün yok")


def _minimum(
    kampanya: tuple[bool, str, str],
    tutar: str,
    tutar_alanlari: tuple[str, ...],
    uyari: bool,
    uyari_alintilari: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    kampanyali, k_alan, k_alinti = kampanya
    return {
        "table_ref": "T2",
        "inputs": [
            _o("kampanyali_sepet", kampanyali, k_alan, k_alinti),
            *[_o("sepet_tutari", _ondalik(tutar), a, f"{tutar} TL") for a in tutar_alanlari],
        ],
        "expected": [_o("minimum_uyarisi", uyari, a, q) for a, q in uyari_alintilari],
    }


def _cikti(groups: list[dict[str, Any]], ignored: list[dict[str, str]] | None = None) -> dict:
    return {"groups": groups, "ignored": list(ignored or [])}


UYARI = '"Minimum sipariş tutarı 750,00 TL" uyarısı'
C2 = _kampanya("7", "1", "175,00", "25,00", "150,00", adet_baslikta=True, bedava_metinde=True)
# case no → model çıktısı `{groups, ignored}` (ana golden; C3 fix_doc alternatifi).
OLGULAR: dict[int, dict[str, Any]] = {
    2: _cikti([C2]),
    # Ana golden C3 (fix_doc alternatifi: "6 adette 1 bedava"): story tablosuyla uyuşmaz.
    3: _cikti(
        [_kampanya("6", "1", "150,00", "25,00", "125,00", adet_baslikta=True, bedava_metinde=True)]
    ),
    4: _cikti(
        [_kampanya("5", "0", "125,00", "0,00", "125,00", adet_baslikta=True, bedava_metinde=False)]
    ),
    5: _cikti(
        [
            _minimum(
                KAMPANYASIZ,
                "150,00",
                (S4,),
                True,
                ((S4, f"{UYARI} görünür"), (SONUC, f"{UYARI} gösterilir")),
            )
        ],
        _sayac(10, "P-002"),
    ),
    6: _cikti(
        [
            _minimum(
                KAMPANYASIZ,
                "750,00",
                (S4, SONUC),
                False,
                ((S4, "minimum sipariş uyarısı görünmez"), (SONUC, "uyarı gösterilmez")),
            )
        ],
        _sayac(25, "P-004"),
    ),
    9: _cikti(
        [
            _minimum(
                (True, SONUC, "Kampanyalı sepette"),
                "150,00",
                (S4, SONUC),
                False,
                (
                    (S4, "minimum sipariş uyarısı görünmez"),
                    (SONUC, "minimum sipariş uyarısı gösterilmez"),
                ),
            )
        ],
        _sayac(7, "P-001"),
    ),
    # C10, C2'nin bilerek tekrarıdır; başlığında "7" geçer, bedava adet geçmez.
    10: _cikti(
        [_kampanya("7", "1", "175,00", "25,00", "150,00", adet_baslikta=True, bedava_metinde=False)]
    ),
}
# C10'un sonuç metni "7 adette 1 adet bedava verilir" (C2 ile aynı): bedava olgusu "1 adet".
OLGULAR[10]["groups"][0]["expected"][1] = _o("bedava_adet", "1", SONUC, "1 adet")

# Senaryo (demo ana yolu) C3: "6 adette bedava adet 0 olur (bedava 7. adette başlar)".
SENARYO_OLGULARI: dict[int, dict[str, Any]] = {
    3: _cikti(
        # "7. adette" sıra sayısıdır; tamlık denetimi saymaz (`ignored` gerekmez).
        [_kampanya("6", "0", "150,00", "0,00", "150,00", adet_baslikta=True, bedava_metinde=False)],
    ),
}

# ------------------------------------------------------------------ varyant golden'lar
#
# case_generation golden'ında OLMAYAN iki içerik; aynı case numarasının senaryo golden'ı olarak
# (`<varyant>/TPD-1-C<n>`) girdi beyanıyla eşleşir. Kapının REPLAY'de gösterimi içindir.

REHBER = "rehber-duzeltme"  # docs/DEGISIKLIK-TEST-REHBERI.md §8.6
AI_HATASI = "ai-sinir-hatasi"  # analist/PO review 1 #3a: AI'ın sınır hatası

# Rehber §8.6: analist C5'in S4 beklenenini aşağıdaki metinle değiştirir (başka alan değişmez).
C5_REHBER_S4 = (
    'Toplam 150,00 TL; "Minimum sipariş tutarı 750,00 TL" uyarısı görünmez ve '
    '"Siparişi onayla" butonu aktiftir'
)


def _degistir(case: dict[str, Any], **alanlar: Any) -> dict[str, Any]:
    out = json.loads(json.dumps(case))
    for yol, deger in alanlar.items():
        if yol.startswith("S"):
            out["steps"][int(yol[1:]) - 1]["expected"] = deger
        else:
            out[yol] = deger
    return out


def _ana_yol_case(n: int) -> dict[str, Any]:
    return tpd1_cases(SENARYO)[n - 1]


def c5_rehber_duzeltme() -> dict[str, Any]:
    """Rehber §8.6'daki düzeltilmiş C5 (yalnız S4 beklenen değişir)."""
    return _degistir(_ana_yol_case(5), S4=C5_REHBER_S4)


def c6_ai_sinir_hatasi() -> dict[str, Any]:
    """AI'ın klasik sınır hatası: tam 750,00 TL'de uyarı görünür sanılır (tablo R3: uyarı yok)."""
    return _degistir(
        _ana_yol_case(6),
        title=(
            "Kampanyasız siparişte minimum tutara eşit toplamda uyarı gösterilir ve onay pasif olur"
        ),
        S4=(
            'Toplam 750,00 TL; "Minimum sipariş tutarı 750,00 TL" uyarısı görünür ve '
            '"Siparişi onayla" butonu pasiftir'
        ),
        expected_result=(
            'Toplam 750,00 TL olduğunda "Minimum sipariş tutarı 750,00 TL" uyarısı gösterilir '
            "ve sipariş onaylanamaz"
        ),
    )


VARYANT_OLGULARI: dict[tuple[str, int], dict[str, Any]] = {
    (REHBER, 5): _cikti(
        [
            _minimum(
                KAMPANYASIZ,
                "150,00",
                (S4,),
                True,  # sonuç metni hâlâ "uyarısı gösterilir" der
                ((SONUC, f"{UYARI} gösterilir"),),
            )
        ],
        _sayac(10, "P-002"),
    ),
    (AI_HATASI, 6): _cikti(
        [
            _minimum(
                KAMPANYASIZ,
                "750,00",
                (S4, SONUC),
                True,
                ((S4, f"{UYARI} görünür"), (SONUC, f"{UYARI} gösterilir")),
            )
        ],
        _sayac(25, "P-004"),
    ),
}
# Rehber C5'inde S4 artık "uyarısı görünmez" der: mantıksal olgu `false`.
VARYANT_OLGULARI[(REHBER, 5)]["groups"][0]["expected"].insert(
    0, _o("minimum_uyarisi", False, S4, f"{UYARI} görünmez")
)
VARYANT_CASELERI = {(REHBER, 5): c5_rehber_duzeltme, (AI_HATASI, 6): c6_ai_sinir_hatasi}
BEKLENEN_SONUC_VARYANT = {(REHBER, 5): "uyumsuz", (AI_HATASI, 6): "uyumsuz"}

# Golden'ı olmayan (hiçbir tabloyla kesişmeyen) case'ler.
KAPSAM_DISI = (1, 7, 8)

# Story tablolarıyla (T1 `adet // 7`, indirim ve toplam ara toplamdan; T2 eşik 750) dürüst
# sonuçlar. Ana yol = senaryo.
BEKLENEN_SONUC_ANA_YOL: dict[int, str] = {
    1: "kapsam_disi",
    2: "uyumlu",  # bedava 1 = 7 // 7; indirim 25,00 = 175 / 7; toplam 150,00
    3: "uyumlu",  # bedava 0, indirim 0, toplam = ara toplam (uygulama 6 // 6 = 1 → defect adayı)
    4: "uyumlu",
    # T2 case'leri: S3 beklenendeki sepet sayacı ("Sepet sayacı 10") `ignored`'da (tabloda kolonu
    # yok); beklenen alandaki kabul edilmiş `ignored` kontrolü en iyi `kismen` yapar (review 2 g2
    # Y1; `kismen_nedeni: [yok_sayilan]`). S3 verisindeki ürün adedi (girdi alanı) etkilemez.
    5: "kismen",
    6: "kismen",
    7: "kapsam_disi",
    8: "kapsam_disi",
    9: "kismen",
    10: "uyumlu",
}
# Ana golden (fix_doc alternatifi) yalnız C3'te farklıdır: "6 adette 1 bedava" story tablosuyla
# uyuşmaz (bu yolda AC2 değiştiği için Ş1 taslağı REPLAY-MISS olur; tablo elle yazılmadıkça C3
# kontrol edilmez). Onay kapısının gösterimi için saf testlerde kullanılır.
BEKLENEN_SONUC_FIX_DOC = {**BEKLENEN_SONUC_ANA_YOL, 3: "uyumsuz"}

NOTE = (
    "Adlandırılmış golden kayıt (REPLAY-MISS yedeği). Olgular elle hazırlandı (canlı model "
    "çıktısı değil; ai_call.model = golden-elle): case metninden dikkatli bir modelin çıkaracağı "
    "değerler, alıntılar case alanlarından birebir, bir değerin her geçişi ayrı olgu; beklenen "
    "alanlardaki kolonsuz sayılar ignored'da. Kolon adları Ş1'in TPD-1 taslak golden'ındaki "
    "demo tablolarınındır (T1 kampanya: adet, ara_toplam → bedava_adet, indirim, toplam; T2 "
    "minimum sipariş: kampanyali_sepet, sepet_tutari → minimum_uyarisi). Elle golden'la ölçülen "
    "doğruluk bir model ölçümü değildir. Üretildi: python -m tests.unit.features.oracle.tpd1 "
    "(elle düzenlemeyin). Girdi beyanı (input_match.case_text) eşleşirse mod REPLAY (köken "
    "golden_matched); case başka bir metne düzeltilirse REPLAY-MISS ve nötr çıktı (groups: [] → "
    "kontrol_edilemedi). Canlı modelle yeniden kaydedilmeli (TP_MODEL_MODE=record)."
)
VARYANT_NOTU = {
    REHBER: (
        "Varyant: docs/DEGISIKLIK-TEST-REHBERI.md §8.6'da analistin yazdığı düzeltilmiş C5 "
        "(S4 beklenen: uyarı görünmez). Kapının (422 oracle_uyumsuz) REPLAY'de gösterimi. "
    ),
    AI_HATASI: (
        "Varyant: AI'ın klasik sınır hatası (tam 750,00 TL'de uyarı görünür; tablo R3 uyarı "
        "yok). case_generation golden'ında yoktur; içerik bu metinle geldiğinde (IDE taslağı ya "
        "da ileride bir case_generation senaryosu) eşleşir. "
    ),
}


def tpd1_cases(senaryo: str | None = None) -> list[dict[str, Any]]:
    """Ana (`None`) ya da senaryo (`f2-kod-hatasi`) case_generation golden'ının case'leri."""
    alt = f"{senaryo}/" if senaryo else ""
    path = RULES / "replay" / "case_generation" / "golden" / f"{alt}{STORY}.json"
    return json.loads(path.read_text(encoding="utf-8"))["output"]["cases"]


def ana_yol_cases() -> list[dict[str, Any]]:
    return tpd1_cases(SENARYO)


def _golden(
    ad_on_eki: str | None,
    n: int,
    case: dict[str, Any],
    cikti: dict[str, Any],
    case_golden: str,
    not_: str = NOTE,
) -> tuple[str, dict]:
    ad = golden_name(STORY, case_no=n)
    tam = f"{ad_on_eki}/{ad}" if ad_on_eki else ad
    return tam, {
        "kind": "call",
        "purpose": "case_facts",
        "golden": tam,
        "note": not_,
        "input_match": {"sources": [f"case:{ad}"], "case_text": approved_case_text(case)},
        "case": {
            "jira_key": STORY,
            "sira_no": n,
            "title": case["title"],
            "case_golden": case_golden,
        },
        "output": cikti,
    }


def build_goldens() -> dict[str, dict[str, Any]]:
    """`<ad>` ya da `<senaryo>/<ad>` → golden kaydı."""
    out = dict(_golden(None, n, tpd1_cases()[n - 1], g, STORY) for n, g in OLGULAR.items())
    out.update(
        _golden(SENARYO, n, _ana_yol_case(n), g, f"{SENARYO}/{STORY}")
        for n, g in SENARYO_OLGULARI.items()
    )
    out.update(
        _golden(v, n, VARYANT_CASELERI[(v, n)](), g, f"{SENARYO}/{STORY}", VARYANT_NOTU[v] + NOTE)
        for (v, n), g in VARYANT_OLGULARI.items()
    )
    return out


def olgular(n: int, senaryo: str | None = SENARYO) -> dict[str, Any] | None:
    """Case'in golden çıktısı `{groups, ignored}` (senaryo case'i varsa o; golden yoksa None)."""
    if senaryo and n in SENARYO_OLGULARI:
        return SENARYO_OLGULARI[n]
    return OLGULAR.get(n)


def dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def golden_dir(rules_dir: Path = RULES) -> Path:
    return rules_dir / "replay" / "case_facts" / "golden"


def write_goldens(rules_dir: Path = RULES) -> list[Path]:
    out = []
    for ad, data in build_goldens().items():
        path = golden_dir(rules_dir) / f"{ad}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump(data), encoding="utf-8")
        out.append(path)
    return out


if __name__ == "__main__":  # pragma: no cover
    for p in write_goldens():
        print(p)
