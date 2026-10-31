"""CasesToCode uçtan uca (gerçek Postgres, LocalForge, REPLAY golden'ları, sahte MCP/toolchain).

Demo-B: onaylı TPD-1 case'i → doğrula/eşle (REPLAY) → şablon → yerel kontrol → PR → kırarak
doğrula → insan onaylı merge; ayrıca defect adayı, locator düzeltme turu, eksik metot,
REPLAY-MISS ve GitHub kod yolu (aynı servis, farklı ForgePort).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tests.unit.features.codegen.conftest import (
    ASSERT_MSG,
    LOCATOR_MSG,
    arka_plan_worker,
    gecti,
    kirmizi,
)
from tp_core.audit import content_hash
from tp_core.events.bus import parse_payload
from tp_core.features.codegen import service
from tp_core.features.codegen.render import parse_dealers
from tp_core.models import (
    AiCall,
    PullRequest,
    Review,
    Script,
    ScriptTestCase,
    StepMapping,
    TestCase,
    session_scope,
)
from tp_core.models.codegen_feature import ScriptAdim, ScriptCodegen, ScriptKontrol
from tp_core.ports import PullRequest as PortPR
from tp_core.workflow.service import Principal, content_hash_of, record_approval, transition

from .conftest import run_jobs

# Golden TPD-1-C2'deki kayıtlı tarayıcı adımı sayısı (replay'de çalışan MCP'ye yeniden koşturulur).
_GOLDEN = Path(__file__).resolve().parents[5] / "rules/replay/verify_and_map/golden"
ADIM_C2 = len(json.loads((_GOLDEN / "TPD-1-C2.json").read_text("utf-8"))["steps"])


def uret(api: TestClient, case_ids: Sequence[uuid.UUID]) -> dict[str, Any]:
    r = api.post("/code/generate", json={"case_ids": [str(c) for c in case_ids]})
    assert r.status_code == 202, r.text
    return r.json()


def script_of(sid: str | uuid.UUID) -> tuple[Script, ScriptCodegen]:
    with session_scope() as s:
        return s.get(Script, uuid.UUID(str(sid))), s.get(ScriptCodegen, uuid.UUID(str(sid)))


def dinleyici(db: Any) -> psycopg.Connection:
    c = psycopg.connect(
        db.app_url.replace("postgresql+psycopg://", "postgresql://"), autocommit=True
    )
    c.execute("LISTEN tp_events")
    return c


def olaylar(c: psycopg.Connection) -> list[dict[str, Any]]:
    return [parse_payload(n.payload) for n in c.notifies(timeout=0.5, stop_after=500)]


@pytest.fixture
def muhendis(api: TestClient, make_user: Any) -> Principal:
    u = make_user("engineer")
    from .conftest import login

    login(api, u)
    return u


# ------------------------------------------------------------------- mutlu yol


def test_demo_b_case_den_pr_a(
    api: TestClient, db: Any, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    cid = hazir["cases"][2]  # 7 adet Portakal Gazozu → 1 adet bedava
    dinle = dinleyici(db)
    yanit = uret(api, [cid])
    assert yanit["durum"] == "started" and len(yanit["script_ids"]) == 1
    sid = yanit["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "pr_open", cg.engel_nedeni
    assert sc.pass_at_1 is True and cg.uretim_modu == "replay" and cg.engel_turu is None

    # Forge: dal tp/case-<uuid>, dosya şablon çıktısı, PR açık; main değişmedi.
    branch = f"tp/case-{cid}"
    assert sc.branch == branch and sc.dosya_yolu.startswith("e2e/tests/generated/tpd-1-c2-")
    assert codegen.forge.read_file(sc.dosya_yolu, ref=branch) == sc.icerik
    assert codegen.forge.head_sha(branch) == sc.head_sha
    pr = codegen.forge.find_open_pr(branch)
    assert pr is not None and pr.number == sc.pr_no and pr.head_sha == sc.head_sha
    assert "AI-generated" in pr.labels and "TPD-1" in pr.labels
    assert "AI-generated" in pr.body and str(cid) in pr.body
    assert "Denetim zinciri başı" in pr.body and cg.denetim_hash in pr.body
    assert '`CartPage.expectFreeQuantity("P-001", 1)`' in pr.body
    assert "REPLAY (hazırlanmış örnek çıktı; canlı model değil)" in pr.body
    with pytest.raises(Exception):  # noqa: B017 — main'de dosya yok
        codegen.forge.read_file(sc.dosya_yolu, ref="main")

    # Üretilen kod: şablon, onaylı değerler, bayi sabitlemesi, AI-generated başlığı.
    kod = sc.icerik
    assert kod.startswith("// AI-generated")
    assert 'import { test } from "../fixtures";' in kod
    assert 'test.use({ dealerUsername: "bayi1" });' in kod
    assert 'await cartPage.expectFreeQuantity("P-001", 1);' in kod
    assert f"Onaylı case hash: {content_hash(_icerik(cid))}" in kod
    assert cg.bundle_hash and cg.bundle_hash in kod

    # Yerel kontrol: yalnızca bu dosya, repeat_each=3, retries=0, PR dalının commit'i.
    (istek,) = codegen.toolchain.checks()
    assert istek["sha"] == sc.head_sha and istek["repeat_each"] == 3 and istek["retries"] == 0
    assert istek["test_files"] == [sc.dosya_yolu.removeprefix("e2e/")]
    assert istek["env"] == {}
    symbols = [b for p, b in codegen.toolchain.istekler if p == "/symbols"]
    assert symbols == [{"sha": codegen.forge.head_sha("main")}]

    with session_scope() as s:
        # Kayıtlar: script_test_case, step_mapping (4 eylem + 5 beklenen), pull_request.
        assert s.scalars(select(ScriptTestCase).where(ScriptTestCase.script_id == sc.id)).all()
        maps = s.scalars(
            select(StepMapping).where(StepMapping.script_id == sc.id).order_by(StepMapping.adim_no)
        ).all()
        assert [m.beklenen for m in maps] == [False] * 4 + [True] * 5
        assert all(m.dogrulandi for m in maps)
        assert maps[5].po_metodu == "expectFreeQuantity" and maps[5].kanit_ref
        kayit = s.get(PullRequest, sc.pr_no)
        assert kayit is not None and kayit.durum == "open" and kayit.acan == "tp-bot"
        # Ajan adımları ve model dışı ekran görüntüleri.
        adimlar = s.scalars(select(ScriptAdim).where(ScriptAdim.script_id == sc.id)).all()
        assert len(adimlar) == ADIM_C2 and all(a.izinli for a in adimlar)
        assert all(a.ekran_goruntusu for a in adimlar)
        for a in adimlar:
            assert (codegen.artifacts / a.ekran_goruntusu).is_file()
        parola = next(a for a in adimlar if a.arguman.get("element") == "Parola")
        assert parola.arguman["text"] == "***"
        # AI çağrısı REPLAY ve denetlenmiş.
        call = s.get(AiCall, uuid.UUID(cg.ai_call_ids[0]))
        assert call.amac == "verify_and_map" and call.mod == "replay"
        eylemler = [
            r[0]
            for r in s.execute(
                text("SELECT eylem FROM audit_event WHERE nesne = :n ORDER BY id"),
                {"n": f"script:{sc.id}"},
            )
        ]
    assert "codegen.requested" in eylemler and "codegen.pr_opened" in eylemler
    assert "script.transition" in eylemler

    # Ajan tarayıcısı: e2e bayisi yerine doğrulama bayisi; görüntü çağrısı modele gitmedi.
    (oturum,) = codegen.oturumlar
    yazilan = [a.get("text") for n, a in oturum.calls if n == "browser_type"]
    assert "bayi3" in yazilan and "bayi1" not in yazilan
    assert oturum.closed
    assert any(n == "browser_take_screenshot" for n, _ in oturum.calls)

    # SSE olayları.
    ev = olaylar(dinle)
    adlar = [e["event"] for e in ev]
    assert adlar.count("agent.step") == ADIM_C2
    adim = next(e for e in ev if e["event"] == "agent.step")["data"]
    assert (
        adim["script_id"] == sid and adim["screenshot_url"] == f"/api/scripts/{sid}/screenshots/1"
    )
    acilan = next(e for e in ev if e["event"] == "pr.opened")["data"]
    assert acilan["pr_number"] == sc.pr_no and acilan["script_id"] == sid
    assert "script.state" in adlar and "codegen.check" in adlar
    dinle.close()

    # ci-runs şeridinin yerel CI tetiği.
    assert codegen.ci == [{"sha": sc.head_sha, "trigger": "pr", "pr_number": sc.pr_no}]

    # API: liste, detay, ekran görüntüsü.
    liste = api.get("/scripts").json()
    assert liste[0]["id"] == sid and liste[0]["durum"] == "pr_open"
    assert liste[0]["pr"]["ci"] == "passed" and liste[0]["yerel_sinif"] == "gecti"
    d = api.get(f"/scripts/{sid}").json()
    assert d["kod"] == kod and len(d["adimlar"]) == ADIM_C2 and len(d["eslemeler"]) == 9
    assert d["pr"]["icerik_hash"] == content_hash_of(sc) and d["pr"]["head_sha"] == sc.head_sha
    assert d["merge_engelleri"] == [] and d["yerel_kontrol"]["sinif"] == "gecti"
    assert d["eslemeler"][4]["kaynak_metin"].startswith("P-001 satırında adet 7")
    g = api.get(adim["screenshot_url"].removeprefix("/api"))
    assert g.status_code == 200 and g.headers["content-type"] == "image/png"
    assert g.content.startswith(b"\x89PNG")

    # Aynı onaylı içerik için yeniden üretim yeni PR açmaz.
    tekrar = uret(api, [cid])
    assert tekrar["durum"] == "none" and tekrar["sonuclar"][0]["durum"] == "pr_acik"


def _icerik(cid: uuid.UUID) -> dict[str, Any]:
    with session_scope() as s:
        return dict(s.get(TestCase, cid).icerik)


def test_ekran_goruntusu_yol_dogrulamasi(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    sid = uret(api, [hazir["cases"][1]])["script_ids"][0]
    run_jobs(engine)
    assert api.get(f"/scripts/{sid}/screenshots/0").status_code == 404
    assert api.get(f"/scripts/{sid}/screenshots/999").status_code == 404
    assert api.get(f"/scripts/{uuid.uuid4()}/screenshots/1").status_code == 404
    gizli = codegen.artifacts / "gizli.png"
    gizli.write_bytes(b"\x89PNGgizli")
    with session_scope() as s:
        a = s.scalars(select(ScriptAdim).where(ScriptAdim.script_id == uuid.UUID(sid))).first()
        a.ekran_goruntusu = "codegen/../gizli.png"
        b = s.scalars(
            select(ScriptAdim).where(ScriptAdim.script_id == uuid.UUID(sid), ScriptAdim.sira == 2)
        ).one()
        b.ekran_goruntusu = f"codegen/{uuid.uuid4()}/step-2.png"  # başka script'in yolu
    assert api.get(f"/scripts/{sid}/screenshots/1").status_code == 404
    assert api.get(f"/scripts/{sid}/screenshots/2").status_code == 404
    api.cookies.clear()
    assert api.get(f"/scripts/{sid}/screenshots/3").status_code == 401


# ---------------------------------------------------------- kırarak doğrula + merge


def test_kirarak_dogrula_ve_insan_onayli_merge(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    sid = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    sc, _ = script_of(sid)
    codegen.toolchain.kirik.append(kirmizi(ASSERT_MSG, "assertion", n=1))
    r = api.post(f"/scripts/{sid}/break-verify")
    assert r.status_code == 202, r.text
    assert api.post(f"/scripts/{sid}/break-verify").status_code == 409  # sürüyor
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert cg.break_durum == "passed" and sc.zayif_test is False
    asamalar = {a["ad"]: a["sonuc"] for a in sc.kirma_dogrulama["asamalar"]}
    assert asamalar == {"baseline": "passed", "broken": "failed", "restored": "passed"}
    kontroller = codegen.toolchain.checks()[-2:]
    assert kontroller[0]["env"] == {"BREAK_CAMPAIGN": "1"} and kontroller[1]["env"] == {}
    assert kontroller[0]["sha"] == kontroller[1]["sha"] == sc.head_sha

    # Merge: görülen içerik hash'i ve head sha'sı bağlı; insan aktör; forge kapısı local-ci.
    d = api.get(f"/scripts/{sid}").json()
    yanlis = api.post(
        f"/prs/{sc.pr_no}/merge", json={"icerik_hash": d["pr"]["icerik_hash"], "head_sha": "0" * 40}
    )
    assert yanlis.status_code == 409
    with arka_plan_worker(engine):
        r = api.post(
            f"/prs/{sc.pr_no}/merge",
            json={"icerik_hash": d["pr"]["icerik_hash"], "head_sha": d["pr"]["head_sha"]},
        )
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "merged"
    sc, _ = script_of(sid)
    assert sc.durum == "merged" and sc.insan_review_sonucu == "kabul"
    push = {"sha": codegen.forge.head_sha("main"), "trigger": "push", "pr_number": None}
    assert codegen.ci[-1] == push  # merge sonrası main CI
    assert codegen.forge.read_file(sc.dosya_yolu, ref="main") == sc.icerik
    kayit = codegen.forge.get_pr_record(sc.pr_no)
    assert kayit["merged_by"] == muhendis.kullanici_adi and not kayit["bypass"]
    with session_scope() as s:
        rv = s.scalars(select(Review).where(Review.nesne_id == sc.id)).one()
        assert rv.karar == "merge" and rv.user_id == muhendis.id
        pr = s.get(PullRequest, sc.pr_no)
        assert pr.durum == "merged" and pr.merge_eden == muhendis.kullanici_adi
    gorunum = api.get(f"/scripts/{sid}").json()["pr"]
    assert gorunum["merge_sha"] == pr.merge_sha and gorunum["merge_eden"] == muhendis.kullanici_adi
    assert gorunum["merge_zamani"]


def test_zayif_test_ve_kirmizi_ci_merge_reddi(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    sid = uret(api, [hazir["cases"][4]])["script_ids"][0]  # 5 adet → bedava yok
    run_jobs(engine)
    codegen.toolchain.kirik.append(gecti(1))  # kırılmada da yeşil
    codegen.toolchain.kontroller.append(kirmizi("TypeError: boom", n=1))  # bayraksız kırmızı
    api.post(f"/scripts/{sid}/break-verify")
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert cg.break_durum == "failed"  # bayraksız koşu kırmızı → sonuç kanıt değil
    # local-ci artık failure: merge kapısı kapalı; ret denetime yazılır.
    d = api.get(f"/scripts/{sid}").json()
    assert any("local-ci" in e for e in d["merge_engelleri"])
    assert d["merge_kabul_gerekli"]  # kırarak doğrulama tamamlanamadı → açık kabul
    govde = {"icerik_hash": d["pr"]["icerik_hash"], "head_sha": d["pr"]["head_sha"]}
    r = api.post(f"/prs/{sc.pr_no}/merge", json=govde)
    assert r.status_code == 409 and "onay_notu" in r.json()["detail"]
    with arka_plan_worker(engine):
        r = api.post(
            f"/prs/{sc.pr_no}/merge", json={**govde, "onay_notu": "Kanıtsız merge kabul edildi."}
        )
    # Bilinen kapı engeli (local-ci kırmızı) merge onayı (review) yazılmadan reddedilir.
    assert r.status_code == 409 and "Zorunlu kontrol 'local-ci'" in r.json()["detail"]
    sc, _ = script_of(sid)
    assert sc.durum == "pr_open"
    with session_scope() as s:
        assert not s.scalars(select(Review).where(Review.nesne_id == sc.id)).all()

    # Yeniden yeşil + kırılmada yeşil → zayıf test.
    codegen.toolchain.kirik.append(gecti(1))
    api.post(f"/scripts/{sid}/break-verify")
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert cg.break_durum == "weak" and sc.zayif_test is True
    assert "Zayıf test" in " ".join(api.get(f"/scripts/{sid}").json()["uyarilar"])


# --------------------------------------------------------- insana düşen yollar


def test_assertion_hatasi_defect_adayi_onarim_yok(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    codegen.toolchain.kontroller.append(kirmizi(ASSERT_MSG, "assertion"))
    sid = uret(api, [hazir["cases"][3]])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "blocked" and cg.engel_turu == "defect_candidate"
    assert sc.pass_at_1 is False and sc.pr_no is None and cg.duzeltme_turu == 0
    assert 'beklenen "0", gerçekleşen "1"' in cg.engel_nedeni
    assert len(codegen.toolchain.checks()) == 1  # onarım/yeniden eşleme yok
    assert codegen.forge.find_open_pr(sc.branch) is None
    d = api.get(f"/scripts/{sid}").json()
    assert d["yerel_sinif"] == "defect_adayi" and d["engel"]["tur"] == "defect_candidate"
    assert d["yerel_kontrol"]["basarisiz"][0]["gerceklesen"] == '"1"'
    # Aynı case yeniden üretilebilir (bloklu script kapanır).
    tekrar = uret(api, [hazir["cases"][3]])
    assert tekrar["durum"] == "started"
    assert script_of(sid)[0].durum == "closed"


def test_locator_hatasi_tek_duzeltme_turu(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    codegen.toolchain.kontroller += [kirmizi(LOCATOR_MSG, "locator_timeout"), gecti()]
    sid = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "pr_open", cg.engel_nedeni
    assert cg.duzeltme_turu == 1 and sc.pass_at_1 is False and sc.onarim_sonrasi_sonuc == "passed"
    assert len(cg.ai_call_ids) == 2 and len(codegen.oturumlar) == 2
    assert cg.ilk_eslesme["expects"] == cg.eslesme["expects"]
    with session_scope() as s:
        turler = [
            k.tur
            for k in s.scalars(
                select(ScriptKontrol)
                .where(ScriptKontrol.script_id == sc.id)
                .order_by(ScriptKontrol.zaman)
            )
        ]
        adim_turleri = {
            a.tur for a in s.scalars(select(ScriptAdim).where(ScriptAdim.script_id == sc.id))
        }
    assert turler == ["local_check", "remap_check"] and adim_turleri == {1, 2}
    pr = codegen.forge.find_open_pr(sc.branch)
    assert "Eşleme düzeltme turu: 1" in pr.body


def test_ikinci_turda_da_locator_insana(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    codegen.toolchain.kontroller += [kirmizi(LOCATOR_MSG), kirmizi(LOCATOR_MSG)]
    sid = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "blocked" and cg.engel_turu == "locator" and cg.duzeltme_turu == 1
    assert len(codegen.toolchain.checks()) == 2


def test_eksik_metot_kod_uretmez(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    sid = uret(api, [hazir["cases"][7]])["script_ids"][0]  # kredi limiti (bilinen kod hatası)
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "blocked" and cg.engel_turu == "missing_method"
    assert "page object'te eksik metot" in cg.engel_nedeni
    assert sc.icerik is None and codegen.toolchain.checks() == []
    assert cg.dogrulama and cg.dogrulama[0]["tur"] == "missing_method"


def test_degistirilmis_case_replay_miss_insana(
    api: TestClient,
    engine: Engine,
    codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
    make_user: Any,
) -> None:
    cid = hazir["cases"][2]
    analist = hazir["analist"]
    with session_scope() as s:
        tc = s.get(TestCase, cid)
        transition(s, tc, "draft", analist, "approved")
    with session_scope() as s:
        tc = s.get(TestCase, cid)
        yeni = dict(tc.icerik, title="8 adet kampanyalı üründe 1 adet bedava verilir")
        record_approval(
            s, tc, analist, "edit", beklenen_hash=content_hash_of(tc), degisiklik={"icerik": yeni}
        )
        tc.icerik_hash = content_hash(yeni)
        transition(s, tc, "approved", analist, "draft")
    sid = uret(api, [cid])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "blocked" and cg.engel_turu == "replay_miss"
    assert cg.uretim_modu == "replay_miss" and sc.icerik is None
    assert "başka case'in eşlemesinden kod üretilmez" in cg.engel_nedeni


def test_onaysiz_ya_da_degismis_case_reddedilir(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    cid = hazir["cases"][2]
    with session_scope() as s:
        tc = s.get(TestCase, cid)
        tc.icerik = dict(tc.icerik, title="onaydan sonra değişti")
    r = api.post("/code/generate", json={"case_ids": [str(cid)]})
    assert r.status_code == 409 and "onaydan sonra değişmiş" in r.json()["detail"]
    r = api.post("/code/generate", json={"case_ids": [str(uuid.uuid4())]})
    assert r.status_code == 409
    # Rol: analist kod üretemez.
    from .conftest import login

    login(api, hazir["analist"])
    assert api.post("/code/generate", json={"case_ids": [str(cid)]}).status_code == 403


def test_case_is_baslamadan_degisirse_is_durur(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    cid = hazir["cases"][2]
    sid = uret(api, [cid])["script_ids"][0]
    with session_scope() as s:
        tc = s.get(TestCase, cid)
        tc.icerik = dict(tc.icerik, title="kuyruktayken değişti")
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "failed" and cg.engel_turu == "case_changed"
    assert codegen.oturumlar == []  # ajan hiç başlamadı


# --------------------------------------------------- GitHub kod yolu (sahte forge)


class SahteGitHubForge:
    """`ForgePort` — GitHubForge yerine; aynı servis kod yolu, kimliksiz."""

    # GitHub kipinde depo bu monorepodur: uygulama `demo-app/` altında (ci.yml APP_ROOT).
    FIXTURES = "demo-app/e2e/tests/fixtures.ts"

    def __init__(self, main_sha: str, fixtures_src: str) -> None:
        self.main = main_sha
        self.fixtures = fixtures_src
        self.okunan: list[str] = []
        self.commits: list[tuple[str, Mapping[str, str]]] = []
        self.bases: list[str] = []
        self.branches: dict[str, str] = {}
        self.prs: dict[int, PortPR] = {}
        self.comments: list[tuple[int, str]] = []

    def head_sha(self, ref: str = "main") -> str:
        from tp_core.integrations.forge import ForgeNotFoundError

        if ref == "main":
            return self.main
        if ref not in self.branches:
            raise ForgeNotFoundError(f"ref bulunamadı: {ref}")
        return self.branches[ref]

    def read_file(self, path: str, ref: str = "main") -> str:
        from tp_core.integrations.forge import ForgeNotFoundError

        self.okunan.append(path)
        if path != self.FIXTURES:
            raise ForgeNotFoundError(f"dosya yok: {path}")
        return self.fixtures

    def commit_files(self, branch: str, files: Mapping[str, str], message: str, base: str = "main"):
        sha = uuid.uuid4().hex + "abcdefgh"
        self.commits.append((sha, dict(files)))
        self.bases.append(base)
        self.branches[branch] = sha
        return sha

    def find_open_pr(self, branch: str) -> PortPR | None:
        return next((p for p in self.prs.values() if p.branch == branch), None)

    def open_pr(self, branch: str, title: str, body: str, labels: Sequence[str] = ()) -> PortPR:
        pr = PortPR(
            number=101 + len(self.prs),
            branch=branch,
            title=title,
            body=body,
            head_sha=self.branches[branch],
            url=f"https://github.com/acme/demo-app/pull/{101 + len(self.prs)}",
            labels=list(labels),
        )
        self.prs[pr.number] = pr
        return pr

    def get_pr(self, number: int) -> PortPR:
        pr = self.prs[number]
        if pr.state != "open":
            return pr
        return pr.model_copy(update={"head_sha": self.branches[pr.branch]})

    def comment_pr(self, number: int, body: str) -> None:
        self.comments.append((number, body))


def github_kipi(codegen: Any, monkeypatch: pytest.MonkeyPatch) -> SahteGitHubForge:
    """GitHub kod yolu: sahte GitHubForge + monorepo düzeni (`demo-app/e2e`). Toolchain commit'i
    aynadan (TP_FORGE_REMOTE_URL) okur: sahte toolchain her sha'yı bulur."""
    monkeypatch.setenv("TP_FORGE_APP_ROOT", "demo-app")
    gh = SahteGitHubForge(codegen.forge.head_sha("main"), codegen.forge.read_file(
        "e2e/tests/fixtures.ts"))  # fmt: skip
    service.set_factories(
        gateway=service._factories["gateway"],
        browser=service._factories["browser"],
        toolchain=service._factories["toolchain"],
        forge=lambda: gh,
    )
    return gh


def test_github_kod_yolu_ayni(
    api: TestClient,
    engine: Engine,
    codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh = github_kipi(codegen, monkeypatch)
    sid = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "pr_open", cg.engel_nedeni
    assert sc.pass_at_1 is True and cg.yerel_kontrol["atlandi"] is False
    assert cg.pr_url == "https://github.com/acme/demo-app/pull/101"
    # Uygulama kökü demo-app/: fikstürler, üretilen dosya ve /check test yolu ona göre.
    assert gh.okunan == ["demo-app/e2e/tests/fixtures.ts"]
    assert sc.dosya_yolu.startswith("demo-app/e2e/tests/generated/tpd-1-c2-")
    ((sha, files),) = gh.commits
    assert files == {sc.dosya_yolu: sc.icerik} and sc.head_sha == sha
    istek = codegen.toolchain.checks()[-1]
    assert istek["sha"] == sha
    assert istek["test_files"] == [sc.dosya_yolu.removeprefix("demo-app/e2e/")]
    assert codegen.ci[-1] == {"sha": sha, "trigger": "pr", "pr_number": 101}
    assert gh.bases == [codegen.forge.head_sha("main")]  # dal sembol tablosunun main'inden
    # Aynı case yeniden üretilince eski dal yeniden kullanılmaz: yeni dal main'den, yeni PR;
    # eski PR'a (GitHubForge kapatamaz) "yerine geçildi" yorumu yazılır.
    with session_scope() as s:
        sc_ = s.get(Script, uuid.UUID(sid))
        transition(s, sc_, "closed", "test", "pr_open")
    sid2 = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    sc2, _ = script_of(sid2)
    assert sc2.durum == "pr_open" and sc2.pr_no == 102 and len(gh.prs) == 2
    assert sc2.branch == f"{sc.branch}-2" and gh.prs[102].branch == sc2.branch
    assert gh.comments and gh.comments[0][0] == 101 and "yeniden kod üretimi" in gh.comments[0][1]
    # Yerine geçilen (bot kapatamadığı) eski PR GitHub'da merge edilirse senkron onu da işler:
    # PR kaydı merged + merge sonrası push CI; script son durumunda (closed) kalır.
    gh.prs[101] = gh.prs[101].model_copy(update={"state": "merged"})
    once = len(codegen.ci)
    sonuc = service.sync_prs(engine, gh)
    assert sonuc["eski_merged"] == 1 and sonuc["merged"] == 0
    with session_scope() as s:
        assert s.get(PullRequest, 101).durum == "merged"
        assert s.get(Script, uuid.UUID(sid)).durum == "closed"
        olay = s.execute(
            text("SELECT ozet FROM audit_event WHERE eylem = 'codegen.superseded_pr_merged'")
        ).scalar_one()
    assert olay["pr"] == 101
    assert codegen.ci[once:] == [{"sha": None, "trigger": "push", "pr_number": None}]
    assert service.sync_prs(engine, gh)["eski_bakilan"] == 0


def test_sablon_bayileri_fikstur_kaynagindan() -> None:
    src = (Path(__file__).resolve().parents[5] / "demo-app/e2e/tests/fixtures.ts").read_text()
    assert set(parse_dealers(src)) == {"bayi1", "bayi2"}
    assert json.dumps(sorted(parse_dealers(src)))  # sözdizimsel okuma; kod çalıştırılmaz


# ------------------------------------------------- canlı model kod yolu (FakeProvider)


def test_canli_ajan_yolu_izin_listesi_ve_goruntu(
    api: TestClient,
    engine: Engine,
    codegen: Any,
    hazir: dict[str, Any],
    muhendis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tp_core.audit import PgCallRecorder
    from tp_core.gateway import FINAL_TOOL, build_gateway
    from tp_core.gateway.config import GatewaySettings
    from tp_core.gateway.testing import FakeProvider, tool_response

    from .test_checks import golden_mapping

    monkeypatch.setenv("TP_MODEL_MODE", "live")
    provider = FakeProvider(
        [
            tool_response(("browser_navigate", {"url": "http://demo-app-web:8080/giris"})),
            tool_response(("browser_evaluate", {"function": "() => document.cookie"})),
            tool_response(("browser_type", {"element": "Kullanıcı adı", "text": "bayi1"})),
            tool_response(("browser_click", {"element": "Giriş yap", "target": "e20"})),
            tool_response(("browser_snapshot", {})),
            tool_response((FINAL_TOOL, golden_mapping(2))),
        ]
    )
    gw = build_gateway(
        PgCallRecorder(engine), settings=GatewaySettings(), engine=engine, provider=provider
    )
    service.set_factories(
        gateway=lambda _e: gw,
        browser=service._factories["browser"],
        toolchain=service._factories["toolchain"],
        forge=service._factories["forge"],
    )
    sid = uret(api, [hazir["cases"][2]])["script_ids"][0]
    run_jobs(engine)
    sc, cg = script_of(sid)
    assert sc.durum == "pr_open", cg.engel_nedeni
    assert cg.uretim_modu == "live"
    # Modele verilen araçlar: yalnızca §8.4 izin listesi (+ son çıktı aracı).
    verilen = {t.name for t in provider.requests[0].tools}
    assert verilen == {
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_select_option",
        "browser_wait_for",
        "browser_generate_locator",
        FINAL_TOOL,
    }
    # Snapshot güvenilmeyen blokta; ekran görüntüsü modele hiç gitmedi.
    son = json.dumps(provider.requests[-1].messages, ensure_ascii=False)
    assert '<untrusted kind=\\"snapshot\\"' in son
    assert "image" not in son and "ekran görüntüsü" not in son
    (oturum,) = codegen.oturumlar
    assert ("browser_evaluate", {"function": "() => document.cookie"}) not in oturum.calls
    assert ("browser_type", {"element": "Kullanıcı adı", "text": "bayi3"}) in oturum.calls
    with session_scope() as s:
        adimlar = s.scalars(
            select(ScriptAdim).where(ScriptAdim.script_id == sc.id).order_by(ScriptAdim.sira)
        ).all()
    assert [(a.arac, a.izinli) for a in adimlar] == [
        ("browser_navigate", True),
        ("browser_evaluate", False),
        ("browser_type", True),
        ("browser_click", True),
        ("browser_snapshot", True),
    ]
    assert adimlar[1].ekran_goruntusu is None and adimlar[0].ekran_goruntusu


def test_coken_is_takili_script_birakmaz(
    api: TestClient, engine: Engine, codegen: Any, hazir: dict[str, Any], muhendis: Any
) -> None:
    from tp_core.features.codegen import jobs as cg_jobs

    cid = hazir["cases"][2]
    sid = uret(api, [cid])["script_ids"][0]
    assert uret(api, [cid])["sonuclar"][0]["durum"] == "suruyor"
    with session_scope() as s:  # worker iş dışında öldü: iş failed, script pending'de kaldı
        s.execute(
            text("UPDATE job SET durum = 'failed', son_hata = 'nabız kaybı' WHERE id = :j"),
            {"j": script_of(sid)[1].job_id},
        )
    with engine.begin() as conn:
        cg_jobs.on_worker_start(conn)
    sc, cg = script_of(sid)
    assert sc.durum == "failed" and "nabız kaybı" in cg.engel_nedeni
    yeni = uret(api, [cid])
    assert yeni["durum"] == "started" and script_of(sid)[0].durum == "closed"
