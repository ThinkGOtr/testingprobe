"""Kod/veri araçları (salt okuma) ve deterministik kanıt doğrulayıcı — gerçek demoapp_ro
veritabanı ve demo-app/'dan kurulan forge deposuna karşı."""

from __future__ import annotations

import copy
import json
from typing import Any

import psycopg
import pytest

from tp_core.features.requirements import datatools
from tp_core.features.requirements.codetools import TOOL_SPECS, CodeToolError, CodeTools
from tp_core.features.requirements.datatools import (
    DataToolError,
    DataTools,
    DemoDb,
    QueryResult,
    digest_matches_any,
    masked_digest,
)
from tp_core.features.requirements.sqlguard import QueryRejected
from tp_core.features.requirements.verifier import EvidenceVerifier
from tp_core.gateway import ALLOWED_AGENT_TOOLS, PiiMasker, result_digest
from tp_core.integrations.forge_local import LocalForge

from .conftest import RULES
from .test_content import TPD1_ACS

GOLDEN_SQL = "SELECT anahtar, deger FROM ayar WHERE anahtar = 'min_siparis_tutari'"


def golden(name: str) -> dict[str, Any]:
    path = RULES / "replay" / "consistency_check" / "golden" / f"{name}.json"
    return json.loads(path.read_text("utf-8"))


def test_arac_adlari_gecit_izin_listesiyle_ayni() -> None:
    assert {t.name for t in TOOL_SPECS} == set(ALLOWED_AGENT_TOOLS["consistency_check"])


# ------------------------------------------------------------------ veri


def test_db_query_golden_ozetini_uretir(demo_db: DemoDb) -> None:
    res = demo_db.query(GOLDEN_SQL)
    assert res.columns == ["anahtar", "deger"]
    assert res.rows == [("min_siparis_tutari", "750.00")]
    assert result_digest(res.rows) == "min_siparis_tutari=750.00"
    assert digest_matches_any(" min_siparis_tutari=750.00 ", res.rows)
    assert digest_matches_any(masked_digest(res.rows), res.rows)
    assert not digest_matches_any("min_siparis_tutari=500.00", res.rows)
    assert not digest_matches_any(masked_digest([("x", "1")]), res.rows)


def test_db_query_100_satirla_sinirli(demo_db: DemoDb) -> None:
    res = demo_db.query("SELECT a.kod, b.kod FROM urun a, urun b, urun c, urun d")
    assert len(res.rows) == 100 and res.truncated


def test_db_query_zaman_asimi(demo_db: DemoDb, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(datatools, "STATEMENT_TIMEOUT_MS", 1)
    agir = "SELECT count(*) FROM " + ", ".join(f"urun t{i}" for i in range(11))
    with pytest.raises(DataToolError, match="zaman aşımı"):
        demo_db.query(agir)


def test_db_rolu_izinsiz_kolonu_okuyamaz(demoapp_ro_url: str) -> None:
    """Derinlemesine savunma: SQL koruması atlansa bile rol parola özetini ve siparişi okuyamaz,
    işlem salt okunurdur."""
    url = demoapp_ro_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, autocommit=True) as c:
        for sql in ("SELECT parola_hash FROM bayi", "SELECT numara FROM siparis"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(sql)
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            c.execute("CREATE TEMP TABLE t (x int)")


def test_db_query_koruma_ve_sema(demo_db: DemoDb) -> None:
    with pytest.raises(QueryRejected):
        demo_db.query("SELECT parola_hash FROM bayi")
    sema = demo_db.schema()
    assert set(sema) == {"urun", "kampanya", "ayar", "bayi"}
    assert "parola_hash" not in {k for k, _ in sema["bayi"]}


def test_veri_araci_yapilandirilmamis() -> None:
    with pytest.raises(DataToolError, match="DEMOAPP_RO_DATABASE_URL"):
        DemoDb(None).query("SELECT kod FROM urun")


def test_db_query_araci_guvenilmeyen_blok_ve_maske() -> None:
    class SahteDb(DemoDb):
        def query(self, sql: str) -> QueryResult:
            return QueryResult(sql, ["ad", "eposta"], [("Ali", "ali@ornek.com.tr")], False)

    acik = DataTools(SahteDb(None), PiiMasker(enabled=True)).db_query({"sql": "SELECT 1"})
    assert '<untrusted kind="data"' in acik
    assert "ali@ornek.com.tr" not in acik and "<<PII_EMAIL_1>>" in acik
    assert f"result_digest: {masked_digest([('Ali', 'ali@ornek.com.tr')])}" in acik
    kapali = DataTools(SahteDb(None)).db_query({"sql": "SELECT 1"})
    assert "result_digest: Ali=ali@ornek.com.tr" in kapali


# ------------------------------------------------------------------ kod


def test_kod_araclari_sabit_committe(forge: LocalForge) -> None:
    sha = forge.head_sha("main")
    code = CodeTools(forge, sha)
    out = code.search_code({"query": "return adet // 6"})
    assert "api/src/demoapp_api/campaign.py:23:" in out
    assert out.startswith('<untrusted kind="code"')
    dosya = code.get_file_contents(
        {"path": "api/src/demoapp_api/campaign.py", "start_line": 22, "end_line": 23}
    )
    assert "23| " in dosya and "return adet // 6" in dosya and "21| " not in dosya
    liste = code.get_file_contents({"path": "api/src/demoapp_api"})
    assert "api/src/demoapp_api/pricing.py" in liste
    assert "eşleşme yok" in code.search_code({"query": "Kredi limiti aşıldı"})
    with pytest.raises(CodeToolError):
        code.get_file_contents({"path": "yok/boyle.py"})
    with pytest.raises(CodeToolError):
        code.search_code({"query": ""})


# ------------------------------------------------------------------ doğrulayıcı


@pytest.fixture
def verifier(forge: LocalForge, demo_db: DemoDb) -> EvidenceVerifier:
    return EvidenceVerifier(forge, forge.head_sha("main"), demo_db, repo="demo-app")


def test_golden_tpd1_kanitlari_dogrulanir(verifier: EvidenceVerifier) -> None:
    for f in golden("TPD-1")["output"]["findings"]:
        v = verifier.verify(f, TPD1_ACS)
        assert v.ok, (f["id"], v.checks)


@pytest.mark.parametrize("ad", ["TPD-2", "TPD-3", "TPD-1-r2"])
def test_diger_golden_kanitlari_dogrulanir(verifier: EvidenceVerifier, ad: str) -> None:
    acs = {"TPD-2": [], "TPD-3": ["AC1: x", "AC2: y"], "TPD-1-r2": TPD1_ACS}[ad]
    for f in golden(ad)["output"]["findings"]:
        assert verifier.verify(f, acs).ok


def _bozuk(f: dict[str, Any], **ev: Any) -> dict[str, Any]:
    g = copy.deepcopy(f)
    g["evidence"][0].update(ev)
    return g


@pytest.mark.parametrize(
    ("degisiklik", "neden"),
    [
        ({"snippet": "return adet // 7"}, "alıntı"),
        ({"line": 22}, "alıntı"),
        ({"line": 9999}, "dışında"),
        ({"path": "api/src/demoapp_api/yok.py"}, "bulunamadı"),
        ({"repo": "baska-depo"}, "farklı depo"),
        ({"snippet": "6"}, "kısa"),
    ],
)
def test_bozuk_kod_kaniti_elenir(
    verifier: EvidenceVerifier, degisiklik: dict[str, Any], neden: str
) -> None:
    f2 = {f["id"]: f for f in golden("TPD-1")["output"]["findings"]}["F2"]
    v = verifier.verify(_bozuk(f2, **degisiklik), TPD1_ACS)
    assert not v.ok
    assert any(neden in c["neden"] for c in v.checks if not c["ok"])


@pytest.mark.parametrize("repo", ["demo-app", "antrek/demo-app", "demo-app@abc123", "", None])
def test_kod_kaniti_depo_adi_normalize(verifier: EvidenceVerifier, repo: str | None) -> None:
    # Prompt `tool:get_file_contents:<repo>@<commit>:<path>` kaynağını gösterir; model
    # owner/ öneki ya da @commit ekleyebilir. Dosya her durumda denetim commit'inde okunur.
    f2 = {f["id"]: f for f in golden("TPD-1")["output"]["findings"]}["F2"]
    assert verifier.verify(_bozuk(f2, repo=repo), TPD1_ACS).ok


@pytest.mark.parametrize("repo", ["baska-depo@abc", "antrek/baska-depo", "demo-app-2"])
def test_kod_kaniti_baska_depo_normalize_sonrasi_elenir(
    verifier: EvidenceVerifier, repo: str
) -> None:
    f2 = {f["id"]: f for f in golden("TPD-1")["output"]["findings"]}["F2"]
    v = verifier.verify(_bozuk(f2, repo=repo), TPD1_ACS)
    assert not v.ok
    assert any("farklı depo" in c["neden"] for c in v.checks if not c["ok"])


def test_bosluk_normalize_alinti_kabul(verifier: EvidenceVerifier) -> None:
    f2 = {f["id"]: f for f in golden("TPD-1")["output"]["findings"]}["F2"]
    assert verifier.verify(_bozuk(f2, snippet="return   adet //\t6"), TPD1_ACS).ok


@pytest.mark.parametrize(
    "degisiklik",
    [
        {"result_digest": "min_siparis_tutari=500.00"},
        {"query": "SELECT anahtar, deger FROM ayar WHERE anahtar = 'yok'"},
        {"query": "DELETE FROM ayar"},
        {"query": "SELECT parola_hash FROM bayi"},
    ],
)
def test_bozuk_veri_kaniti_elenir(verifier: EvidenceVerifier, degisiklik: dict[str, Any]) -> None:
    f3 = {f["id"]: f for f in golden("TPD-1")["output"]["findings"]}["F3"]
    assert not verifier.verify(_bozuk(f3, **degisiklik), TPD1_ACS).ok


def test_belge_referansi_ve_kanitsiz_bulgu(verifier: EvidenceVerifier) -> None:
    bulgu = {"type": "internal_contradiction", "doc_ref": "AC3 ↔ AC6", "evidence": []}
    assert verifier.verify(bulgu, TPD1_ACS).ok
    assert not verifier.verify({**bulgu, "doc_ref": "AC3 ↔ AC9"}, TPD1_ACS).ok
    assert not verifier.verify({**bulgu, "type": "doc_vs_code"}, TPD1_ACS).ok


def test_sabit_projeksiyonlu_uydurma_veri_kaniti_elenir(
    verifier: EvidenceVerifier, demo_db: DemoDb
) -> None:
    """Sorgu metnine yazılan değer veriden gelmez: gerçekte 750.00 olan ayarı 500.00 gösteren
    sorgu salt okuma veritabanında çalışır ve özeti tutar, ama kanıt olamaz."""
    uydurma = "SELECT anahtar, '500.00' FROM ayar WHERE anahtar = 'min_siparis_tutari'"
    # Araç (keşif) yolunda sorgu çalışır ve "uydurma" özeti üretir…
    assert result_digest(demo_db.query(uydurma).rows) == "min_siparis_tutari=500.00"
    f3 = {f["id"]: f for f in golden("TPD-1")["output"]["findings"]}["F3"]
    bulgu = _bozuk(
        {**f3, "observed": "ayar tablosunda min_siparis_tutari = 500.00"},
        query=uydurma,
        result_digest="min_siparis_tutari=500.00",
    )
    # …ama doğrulayıcı bunu kanıt saymaz: bulgu elenir (gösterilmez).
    v = verifier.verify(bulgu, TPD1_ACS)
    assert not v.ok
    assert any("sorgu reddedildi" in c["neden"] for c in v.checks if not c["ok"])
    # FROM'suz sabit sorgu da kanıt olamaz.
    v = verifier.verify(_bozuk(f3, query="SELECT 'x'", result_digest="x"), TPD1_ACS)
    assert not v.ok


@pytest.mark.parametrize(
    ("query", "digest"),
    [
        # Çapraz birleştirme: gerçek kolon değeri başka satırın anahtarıyla eşlenir (gerçek 750.00).
        (
            "SELECT a.anahtar, u.fiyat FROM ayar a, urun u "
            "WHERE a.anahtar = 'min_siparis_tutari' AND u.kod = 'P-004'",
            "min_siparis_tutari=30.00",
        ),
        # Takma ad kolon listesi: aciklama metni "deger" olarak görünür.
        (
            "SELECT anahtar, deger FROM ayar AS a(anahtar, aciklama, deger) "
            "WHERE anahtar = 'min_siparis_tutari'",
            "min_siparis_tutari=Minimum sipariş tutarı",
        ),
        # LATERAL / VALUES: değer sorgu metninden gelir.
        (
            "SELECT anahtar, deger FROM urun, LATERAL (SELECT 'min_siparis_tutari' AS anahtar, "
            "'500.00' AS deger FROM ayar) x LIMIT 1",
            "min_siparis_tutari=500.00",
        ),
        (
            "SELECT anahtar, deger FROM urun CROSS JOIN LATERAL (SELECT 'min_siparis_tutari' "
            "AS anahtar, '500.00' AS deger FROM ayar) x LIMIT 1",
            "min_siparis_tutari=500.00",
        ),
        (
            "SELECT deger FROM urun, (VALUES ('500.00')) AS v(deger) "
            "WHERE kod NOT IN (SELECT anahtar FROM ayar) LIMIT 1",
            "500.00",
        ),
        # 2. inceleme turu: kayıplı dönüşüm / bağımsız toplamalar (gerçek 750.00; P-001 25.00).
        (
            "SELECT anahtar, CAST(deger AS varchar(1)) FROM ayar "
            "WHERE anahtar='min_siparis_tutari'",
            "min_siparis_tutari=7",
        ),
        (
            "SELECT anahtar, round(CAST(deger AS numeric), -3) FROM ayar "
            "WHERE anahtar='min_siparis_tutari'",
            "min_siparis_tutari=1000",
        ),
        ("SELECT kullanici_adi, round(kredi_limiti, -5) FROM bayi", "bayi1=0; bayi2=0"),
        ("SELECT kullanici_adi, CAST(kredi_limiti AS INT) FROM bayi", "bayi1=2000; bayi2=500"),
        ("SELECT anahtar, CAST(deger AS numeric(5,0)) FROM ayar", "min_siparis_tutari=750"),
        ("SELECT anahtar, length(deger) FROM ayar", "min_siparis_tutari=6"),
        ("SELECT MIN(kod), MAX(fiyat) FROM urun", "P-001=30.00"),
    ],
)
def test_birlestirme_ve_yeniden_adlandirma_kaniti_elenir(
    verifier: EvidenceVerifier, query: str, digest: str
) -> None:
    ok, neden = verifier.check_data({"kind": "data", "query": query, "result_digest": digest})
    assert not ok and neden.startswith("sorgu reddedildi"), neden
    f3 = {f["id"]: f for f in golden("TPD-1")["output"]["findings"]}["F3"]
    assert not verifier.verify(_bozuk(f3, query=query, result_digest=digest), TPD1_ACS).ok


def test_veri_kaniti_dogrulanan_sorguyu_ve_bos_sonucu_gosterir(verifier: EvidenceVerifier) -> None:
    q = "SELECT anahtar, deger FROM ayar WHERE anahtar = 'min_siparis_tutari'"
    ok, neden = verifier.check_data(
        {"kind": "data", "query": q, "result_digest": "min_siparis_tutari=750.00"}
    )
    assert ok and "1 satır" in neden and "FROM ayar" in neden
    ok, neden = verifier.check_data(
        {
            "kind": "data",
            "query": "SELECT anahtar FROM ayar WHERE anahtar = 'min_siparis_tutar'",
            "result_digest": "(sonuç yok)",
        }
    )
    assert ok and "boş sonuç" in neden and "min_siparis_tutar'" in neden
