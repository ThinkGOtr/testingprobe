"""012 §4.4 uçtan uca (gerçek Postgres): koşu + hata kanıtı + bağlı onaylı case + karar tablosu +
`case_oracle_kontrol` kaydı → kaydedilen `failure` sınıfı / alt türü / sinyalleri, bug taslağı ve
LLM'siz karar. Kayıt seçimi: case'in `onaylanan_hash`'i, sonuç `uyumlu|uyumsuz`, tablo değişmemiş.
"""

from __future__ import annotations

import sys
import types
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from tp_core.features.triage import classify_run, get_failure
from tp_core.features.triage.rules import BEKLENTI_ONERISI
from tp_core.models import Failure, Requirement, Script, TestCase, TestResult
from tp_core.models.codegen_feature import ScriptCodegen
from tp_core.models.guard import allow_state_write
from tp_core.models.kalite_feature import CaseOracleKontrol, KararTablosu, OracleIstisna
from tp_core.models.triage_feature import FailureEk
from tp_core.workflow.service import content_hash, content_hash_of

from .conftest import KTest, kosu_kur

pytestmark = pytest.mark.usefixtures("triage_env")

DOSYA = "tests/generated/TPD-1-c3-abcd1234.spec.ts"
# Üretilen testin kaynağı (şablon biçimi); `_failure` test_location satırı 14 = toplam doğrulaması.
URETILEN_TEST = "\n".join(
    [
        "// AI-generated — AI Testing Probe (CasesToCode).",
        'import { test } from "../fixtures";',
        "",
        'test.describe("TPD-1 · C3", () => {',
        '  test("6 adet toplam", async ({ cartPage, catalogPage }) => {',
        "    // S1 — Sepete 6 adet ekle",
        '    await catalogPage.addToCart("P-001", 6);',
        "    // S2 — Sepete git",
        "    await catalogPage.openCart();",
        "    // Beklenen sonuç (değerler onaylı case metninden)",
        "    await catalogPage.expectCartCount(6);",
        '    await cartPage.expectLineQuantity("P-001", 6);',
        '    await cartPage.expectFreeQuantity("P-001", 0);',
        '    await cartPage.expectTotal("125,00 TL");',
        "  });",
        "});",
    ]
)
ARIA = """- main:
  - definition: "Toplam: 125,00 TL\""""
TABLO_ICERIK: dict[str, Any] = {
    "ad": "Kampanya toplamı",
    "ac_refs": ["AC1"],
    "girdiler": [{"ad": "adet", "tur": "sayi"}],
    "ciktilar": [{"ad": "toplam", "tur": "sayi", "tolerans": "0.01"}],
    "satirlar": [{"id": "R1", "kosul": "adet >= 1", "cikti": {"toplam": "adet * 25"}}],
}


ADIM_S2 = "S2 — Sepete git"


def _failure(beklenen: str, gerceklesen: str, adim: str | None = ADIM_S2) -> dict[str, Any]:
    """Playwright hata girdisi. `adim`: başarısız `test.step` başlığı (elle yazılmış testte case
    adımı; None → adım yok, üretilen testin satırından bulunur)."""
    return {
        "type": "assertion",
        "message": "Error: expect(locator).toHaveText(expected) failed\n\n"
        f"Locator: getByTestId('cart-total')\nExpected: \"{beklenen}\"\n"
        f'Received: "{gerceklesen}"',
        "matcher": "toHaveText",
        "locator": "getByTestId('cart-total')",
        "expected": f'"{beklenen}"',
        "received": f'"{gerceklesen}"',
        "location": {"file": "pages/cart/cart.page.ts", "line": 40},
        "test_location": {"file": DOSYA, "line": 14},
        "aria_snapshot": ARIA,
        "aria_snapshot_scope": "page",
        "step": {"title": adim, "path": [adim]} if adim else None,
    }


@dataclass
class Kurulum:
    req: uuid.UUID
    case: uuid.UUID
    tablo: uuid.UUID
    case_hash: str


def _kur(
    engine: Engine,
    *,
    case_degeri: str,
    tablo_degeri: str = "150.00",
    sonuc: str = "uyumsuz",
    case_durum: str = "approved",
    kontrol_hash: str | None = None,
) -> Kurulum:
    """Gereksinim + onaylı case + onaylı tablo + bu case içeriğinin oracle kontrol kaydı."""
    icerik = {
        "title": "6 adet kampanyalı üründe toplam",
        "steps": [
            {"id": "S1", "action": "Sepete 6 adet ekle", "expected": "Sepet sayacı 6 olur"},
            {"id": "S2", "action": "Sepete git", "expected": f"Toplam {case_degeri} TL"},
        ],
    }
    h = content_hash(icerik)
    with allow_state_write(), Session(engine) as s, s.begin():
        req = Requirement(
            kaynak="jira",
            jira_key=f"TPD-{uuid.uuid4().hex[:6]}",
            baslik="Kampanya",
            aciklama="6 adet alana toplam 150 TL",
            kabul_kriterleri=["AC1: toplam doğru"],
            kaynak_hash="k",
            durum="po_approved",
        )
        s.add(req)
        s.flush()
        tc = TestCase(
            id=uuid.uuid4(),
            requirement_id=req.id,
            sira_no=3,
            icerik=icerik,
            icerik_hash=h,
            onaylanan_hash=h,
            durum=case_durum,
        )
        tablo = KararTablosu(
            requirement_id=req.id,
            sira_no=1,
            icerik=TABLO_ICERIK,
            icerik_hash=content_hash(TABLO_ICERIK),
            onaylanan_hash=content_hash(TABLO_ICERIK),
            durum="approved",
            gereksinim_hash=content_hash_of(req),
        )
        s.add_all([tc, tablo])
        s.flush()
        s.add(
            CaseOracleKontrol(
                test_case_id=tc.id,
                icerik_hash=kontrol_hash or h,
                sonuc=sonuc,
                tablo_hashleri={str(tablo.id): tablo.icerik_hash},
                ayrintilar={
                    "gruplar": [
                        {
                            "tablo_id": str(tablo.id),
                            "tablo_ad": "Kampanya toplamı",
                            "satir_id": "R1",
                            "girdiler": [{"column": "adet", "value": "6"}],
                            "karsilastirmalar": [
                                {
                                    "column": "toplam",
                                    "alan": "steps[1].expected",
                                    "alinti": f"Toplam {case_degeri} TL",
                                    "case_degeri": case_degeri,
                                    "tablo_degeri": tablo_degeri,
                                    "uyumlu": case_degeri == tablo_degeri,
                                }
                            ],
                            "durum": sonuc,
                            "neden": None,
                        }
                    ],
                    "atilan_olgular": 0,
                },
            )
        )
        return Kurulum(req.id, tc.id, tablo.id, h)


def _kosu(
    engine: Engine,
    kok: Path,
    k: Kurulum,
    beklenen: str,
    gerceklesen: str,
    adim: str | None = ADIM_S2,
) -> uuid.UUID:
    rid = kosu_kur(
        engine,
        kok,
        testler=[
            KTest(
                "TPD-1 C3 › 6 adet toplam",
                file=DOSYA,
                statuses=["unexpected"] * 2,
                failure=_failure(beklenen, gerceklesen, adim),
            )
        ],
    )
    with Session(engine) as s, s.begin():
        s.execute(update(TestResult).where(TestResult.run_id == rid).values(test_case_id=k.case))
    return rid


def _bugs_modulu(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    cagrilar: list[uuid.UUID] = []
    mod = types.ModuleType("tp_core.features.bugs")

    def create_draft_from_failure(session: Session, failure_id: uuid.UUID) -> None:
        assert session.get(Failure, failure_id) is not None
        cagrilar.append(failure_id)

    mod.create_draft_from_failure = create_draft_from_failure  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tp_core.features.bugs", mod)
    return cagrilar


def _tek(engine: Engine, rid: uuid.UUID) -> tuple[Failure, FailureEk]:
    with Session(engine) as s:
        [(f, ek)] = s.execute(
            select(Failure, FailureEk)
            .join(FailureEk, FailureEk.failure_id == Failure.id)
            .where(Failure.run_id == rid)
        ).all()
        return f, ek


def _kodlar(f: Failure) -> list[str]:
    return [x["kod"] for x in f.eslesen_sinyaller]


# ----------------------------------------------------------------------------- senaryo 9 / 10


def test_senaryo9_beklenti_tabloda_uygulama_farkli_product_defect_ve_bug_taslagi(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cagrilar = _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="150.00", sonuc="uyumlu")
    rid = _kosu(engine, artefakt_kok, k, "150,00 TL", "125,00 TL")
    sonuc = classify_run(engine, rid)
    f, ek = _tek(engine, rid)
    assert (f.sinif, f.alt_tur, f.karar_kaynagi, f.oneri_turu, f.oneri_durumu) == (
        "product_defect",
        None,
        "rule",
        "bug_draft",
        "proposed",
    )
    assert ek.kural == "karar_tablosu" and ek.oneri is None
    assert f.ai_call_id is None and f.uretim_modu is None  # LLM çağrılmadı
    kodlar = _kodlar(f)
    assert kodlar[:2] == ["assertion_farki", "eleman_bulundu"]
    assert kodlar[-1] == "karar_tablosu_uyumlu"
    sinyal = f.eslesen_sinyaller[-1]
    assert "Kampanya toplamı" in sinyal["aciklama"]
    assert sinyal["baslik"] == "Uygulama onaylı kurala aykırı (T1 · R1: adet 6 → toplam 150,00)"
    assert str(k.case) in sinyal["kanit"] and k.case_hash in sinyal["kanit"]
    # Bug taslağı bugünkü product_defect ile aynı biçimde istenir.
    assert sonuc["bug_taslagi_istenen"] == 1 and cagrilar == [f.id]


def test_senaryo10_beklenti_farkli_test_maintenance_beklenti_bug_taslagi_yok(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cagrilar = _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00", sonuc="uyumsuz")
    rid = _kosu(engine, artefakt_kok, k, "125,00 TL", "150,00 TL")
    sonuc = classify_run(engine, rid)
    f, ek = _tek(engine, rid)
    assert (f.sinif, f.alt_tur, f.karar_kaynagi, f.oneri_turu, f.oneri_durumu) == (
        "test_maintenance",
        "beklenti",
        "rule",
        "none",
        "none",
    )
    assert ek.kural == "karar_tablosu" and ek.oneri is None
    assert f.gerekce == BEKLENTI_ONERISI
    assert ek.oneri_yok_nedeni and BEKLENTI_ONERISI in ek.oneri_yok_nedeni
    assert _kodlar(f)[-2:] == ["karar_tablosu_beklenti_farkli", "karar_tablosu_tablo_suphesi"]
    assert sonuc["bug_taslagi_istenen"] == 0 and cagrilar == []
    with Session(engine) as s:
        d = get_failure(s, f.id)
    assert d is not None
    assert (d["sinif"], d["alt_tur"], d["kural"], d["oneri"]) == (
        "test_maintenance",
        "beklenti",
        "karar_tablosu",
        None,
    )


def test_locator_onarimi_beklenti_icin_reddedilir(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.repair.service import uygunluk_engeli

    _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00")
    rid = _kosu(engine, artefakt_kok, k, "125,00 TL", "150,00 TL")
    classify_run(engine, rid)
    f, _ek = _tek(engine, rid)
    with Session(engine) as s:
        engel = uygunluk_engeli(s, f)
    assert engel and "test_maintenance/beklenti" in engel


def test_ikisi_de_farkli_product_defect(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cagrilar = _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00")
    rid = _kosu(engine, artefakt_kok, k, "125,00 TL", "100,00 TL")
    classify_run(engine, rid)
    f, ek = _tek(engine, rid)
    assert (f.sinif, ek.kural, f.oneri_turu) == ("product_defect", "karar_tablosu", "bug_draft")
    assert _kodlar(f)[-1] == "karar_tablosu_ikisi_de_farkli"
    assert cagrilar == [f.id]


def test_uretilen_test_script_codegen_bagi_ve_yayinlanmis_case(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bağ `script_codegen.test_case_id` üzerinden; yayınlanmış case'in onaylı hash'i kullanılır."""
    _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00", case_durum="published")
    sid = uuid.uuid4()
    with Session(engine) as s, s.begin():
        s.add(Script(id=sid, dosya_yolu=f"e2e/{DOSYA}", icerik=URETILEN_TEST))
        s.flush()
        s.add(
            ScriptCodegen(
                script_id=sid,
                test_case_id=k.case,
                requirement_id=k.req,
                case_hash=k.case_hash,
                story_key="TPD-1",
                sira_no=3,
            )
        )
    rid = kosu_kur(
        engine,
        artefakt_kok,
        script_id=sid,
        testler=[
            KTest("TPD-1 C3", file=DOSYA, failure=_failure("125,00 TL", "150,00 TL", adim=None))
        ],
    )
    classify_run(engine, rid)
    f, _ek = _tek(engine, rid)
    assert (f.sinif, f.alt_tur) == ("test_maintenance", "beklenti")


def test_uretilen_test_baska_icerikten_uretildiyse_adim_eslenmez(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Script başka bir case içeriğinden üretildiyse (`script_codegen.case_hash` ≠ onaylı hash)
    satırı onaylı içeriğe eşlenmez → inceltme yok."""
    _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00")
    sid = uuid.uuid4()
    with Session(engine) as s, s.begin():
        s.add(Script(id=sid, dosya_yolu=f"e2e/{DOSYA}", icerik=URETILEN_TEST))
        s.flush()
        s.add(
            ScriptCodegen(
                script_id=sid,
                test_case_id=k.case,
                requirement_id=k.req,
                case_hash="e" * 64,
                story_key="TPD-1",
                sira_no=3,
            )
        )
    rid = kosu_kur(
        engine,
        artefakt_kok,
        script_id=sid,
        testler=[
            KTest("TPD-1 C3", file=DOSYA, failure=_failure("125,00 TL", "150,00 TL", adim=None))
        ],
    )
    classify_run(engine, rid)
    _bugunku(engine, rid)


# ----------------------------------------------------------------------------- kayıt seçimi


def _bugunku(engine: Engine, rid: uuid.UUID) -> None:
    f, ek = _tek(engine, rid)
    assert (f.sinif, ek.kural) == ("product_defect", "product_defect")
    assert not any(c.startswith("karar_tablosu") for c in _kodlar(f))


def test_tablo_kontrolden_sonra_degistiyse_yok_sayilir(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00")
    yeni = {**TABLO_ICERIK, "ad": "Kampanya toplamı v2"}
    with allow_state_write(), Session(engine) as s, s.begin():
        t = s.get(KararTablosu, k.tablo)
        assert t is not None
        t.icerik, t.icerik_hash, t.onaylanan_hash = yeni, content_hash(yeni), content_hash(yeni)
    rid = _kosu(engine, artefakt_kok, k, "125,00 TL", "150,00 TL")
    classify_run(engine, rid)
    _bugunku(engine, rid)


def test_bayat_tablo_yok_sayilir(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00")
    with Session(engine) as s, s.begin():
        r = s.get(Requirement, k.req)
        assert r is not None
        r.aciklama = "Gereksinim onaydan sonra değişti"
    rid = _kosu(engine, artefakt_kok, k, "125,00 TL", "150,00 TL")
    classify_run(engine, rid)
    _bugunku(engine, rid)


def test_onayi_geri_cekilen_tablo_yok_sayilir(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00")
    with allow_state_write(), Session(engine) as s, s.begin():
        t = s.get(KararTablosu, k.tablo)
        assert t is not None
        t.durum, t.onaylanan_hash = "draft", None
    rid = _kosu(engine, artefakt_kok, k, "125,00 TL", "150,00 TL")
    classify_run(engine, rid)
    _bugunku(engine, rid)


def test_baska_icerik_hashinin_kontrolu_kullanilmaz(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kontrol kaydı case'in onaylı içeriğine değil (ör. düzeltme formundaki önerilen içeriğe)
    aitse kullanılmaz."""
    _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00", kontrol_hash="f" * 64)
    rid = _kosu(engine, artefakt_kok, k, "125,00 TL", "150,00 TL")
    classify_run(engine, rid)
    _bugunku(engine, rid)


def test_kismen_kaydin_dogrulanmis_karsilastirmalari_kullanilir(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """012 review 2: `kismen` kayıt (ör. beklenen alanda yok sayılan bir sayı) da karar verir;
    yalnız doğrulanmış `karsilastirmalar` okunur."""
    cagrilar = _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="150.00", sonuc="kismen")
    rid = _kosu(engine, artefakt_kok, k, "150,00 TL", "125,00 TL")
    sonuc = classify_run(engine, rid)
    f, ek = _tek(engine, rid)
    assert (f.sinif, f.karar_kaynagi, f.oneri_turu) == ("product_defect", "rule", "bug_draft")
    assert ek.kural == "karar_tablosu" and _kodlar(f)[-1] == "karar_tablosu_uyumlu"
    assert sonuc["bug_taslagi_istenen"] == 1 and cagrilar == [f.id]


@pytest.mark.parametrize("sonuc", ["kapsam_disi", "kontrol_edilemedi"])
def test_karar_vermeyen_kontrol_sonucu_kullanilmaz(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch, sonuc: str
) -> None:
    _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00", sonuc=sonuc)
    rid = _kosu(engine, artefakt_kok, k, "125,00 TL", "150,00 TL")
    classify_run(engine, rid)
    _bugunku(engine, rid)


def test_onaylanmamis_case_kullanilmaz(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00", case_durum="draft")
    rid = _kosu(engine, artefakt_kok, k, "125,00 TL", "150,00 TL")
    classify_run(engine, rid)
    _bugunku(engine, rid)


def test_oracle_sorgulari_kosu_basina_toplu(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Birden çok başarısız test: case / kontrol / tablo / gereksinim sorguları test sayısından
    bağımsızdır (N+1 yok)."""
    from sqlalchemy import event

    from tp_core.features.triage import service

    _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00")
    with Session(engine) as s:
        sayac: list[str] = []

        def say(_conn: Any, _cur: Any, stmt: str, *_a: Any) -> None:
            sayac.append(stmt)

        event.listen(engine, "before_cursor_execute", say)
        try:
            service.oracle_karsilastirmalari(s, [k.case] * 5)
            bir = len(sayac)
            sayac.clear()
            k2 = _kur(engine, case_degeri="150.00")
            sayac.clear()
            harita = service.oracle_karsilastirmalari(s, [k.case, k2.case, k.case])
            iki = len(sayac)
        finally:
            event.remove(engine, "before_cursor_execute", say)
    assert set(harita) == {k.case, k2.case}
    # case + kontrol + `oracle_istisna` (uyumsuz) + tablo + gereksinim.
    assert bir == iki <= 6


# ----------------------------------------------------------------------------- istisna (K2)


def _istisna(
    engine: Engine,
    k: Kurulum,
    *,
    tur: str = "uyumsuz",
    icerik_hash: str | None = None,
    tablo_hashleri: dict[str, str] | None = None,
) -> None:
    """`oracle_istisna` satırı (varsayılan: kaydın güncel tablo kümesiyle `uyumsuz`)."""
    with Session(engine) as s, s.begin():
        s.add(
            OracleIstisna(
                test_case_id=k.case,
                icerik_hash=icerik_hash or k.case_hash,
                tur=tur,
                gerekce="PO ile görüşüldü: case doğru, tablo güncellenecek.",
                tablo_hashleri=(
                    tablo_hashleri
                    if tablo_hashleri is not None
                    else {str(k.tablo): content_hash(TABLO_ICERIK)}
                ),
            )
        )


def test_senaryo10_istisna_ile_onaylanmissa_bugunku_davranis(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review K2: case 125 bekler, tablo 150, uygulama 150 — ama case içeriği tabloya rağmen
    gerekçeli `uyumsuz` istisnasıyla (aynı tablo kümesi) onaylanmış ("case doğru, tablo
    güncellenecek"). Tablo bu case için doğruluk kaynağı değildir: `test_maintenance/beklenti`
    DEĞİL, bugünkü `product_defect` + bug taslağı (gerçek hata gizlenmez)."""
    cagrilar = _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00", sonuc="uyumsuz")
    _istisna(engine, k)
    rid = _kosu(engine, artefakt_kok, k, "125,00 TL", "150,00 TL")
    sonuc = classify_run(engine, rid)
    _bugunku(engine, rid)
    f, _ek = _tek(engine, rid)
    assert f.oneri_turu == "bug_draft" and cagrilar == [f.id]
    assert sonuc["bug_taslagi_istenen"] == 1


def _inceltildi(engine: Engine, rid: uuid.UUID) -> None:
    f, _ = _tek(engine, rid)
    assert (f.sinif, f.alt_tur) == ("test_maintenance", "beklenti")


@pytest.mark.parametrize(
    "durum",
    ["kontrolsuz_turu", "baska_tablo_kumesi", "baska_hash", "yalniz_eski_kolon"],
)
def test_inceltmeyi_yalniz_guncel_tablo_kumesindeki_uyumsuz_istisnasi_kapatir_n9(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch, durum: str
) -> None:
    """t2 N9: bastırma yalnız `tur='uyumsuz'` + kaydın güncel `tablo_hashleri`'yle verilmiş
    istisnadadır. `kontrolsuz` istisnası, başka tablo kümesinde (tablo değişmeden önce) verilmiş
    istisna, başka içerik hash'inin istisnası ve yalnız geriye uyum kolonu
    (`case_oracle_kontrol.istisna_gerekce`) inceltmeyi kapatmaz."""
    _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00", sonuc="uyumsuz")
    if durum == "kontrolsuz_turu":
        _istisna(engine, k, tur="kontrolsuz")
    elif durum == "baska_tablo_kumesi":
        _istisna(engine, k, tablo_hashleri={str(k.tablo): "eski-tablo-hash"})
    elif durum == "baska_hash":
        _istisna(engine, k, icerik_hash="0" * 64)
    else:
        with Session(engine) as s, s.begin():
            kayit = s.scalars(
                select(CaseOracleKontrol).where(CaseOracleKontrol.test_case_id == k.case)
            ).one()
            kayit.istisna_gerekce = "PO ile görüşüldü: case doğru, tablo güncellenecek."
    rid = _kosu(engine, artefakt_kok, k, "125,00 TL", "150,00 TL")
    classify_run(engine, rid)
    _inceltildi(engine, rid)


def test_istisna_sorgusunda_to_regclass_yok(engine: Engine) -> None:
    """t2 N9: tablo birleştirmeden sonra vardır; çağrı başına varlık yoklaması yapılmaz."""
    from sqlalchemy import event

    from tp_core.features.triage import service

    k = _kur(engine, case_degeri="125.00")
    sorgular: list[str] = []

    def say(_c: Any, _cur: Any, stmt: str, *_a: Any) -> None:
        sorgular.append(stmt)

    with Session(engine) as s:
        event.listen(engine, "before_cursor_execute", say)
        try:
            service.oracle_karsilastirmalari(s, [k.case])
        finally:
            event.remove(engine, "before_cursor_execute", say)
    assert sorgular and not any("to_regclass" in q for q in sorgular)
    assert any("oracle_istisna" in q and "tur" in q for q in sorgular)


# ----------------------------------------------------------------------------- adım eşlemesi (O6)


def test_karsilastirma_baska_adima_aitse_inceltme_yok(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review O6: kırmızı S1'de (sepete ekleme); karşılaştırma S2'nin (`steps[1].expected`).
    Değerler tesadüfen eşleşse de tablo kullanılmaz."""
    _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00")
    rid = _kosu(engine, artefakt_kok, k, "125,00 TL", "150,00 TL", adim="S1 — Sepete 6 adet ekle")
    classify_run(engine, rid)
    _bugunku(engine, rid)


def test_adim_belirlenemezse_inceltme_yok(
    engine: Engine, artefakt_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Adım başlığı yok, koşu üretilen bir teste bağlı değil: başarısız adım bilinmez."""
    _bugs_modulu(monkeypatch)
    k = _kur(engine, case_degeri="125.00")
    rid = _kosu(engine, artefakt_kok, k, "125,00 TL", "150,00 TL", adim=None)
    classify_run(engine, rid)
    _bugunku(engine, rid)
