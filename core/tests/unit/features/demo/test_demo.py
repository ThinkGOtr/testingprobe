"""Sunucu demo kontrolleri: locator kırılması (demo-admin bypass, denetim), uygulama yenileme
isteği, CI'ın uygulama main'i yansıtana dek bekletilmesi ve demo sıfırlaması.

Gerçek Postgres + geçici LocalForge (main, demo-baseline, demo/break-locator). `enqueue_ci`
sahtedir; çalışan uygulamanın commit'i fabrikayla verilir.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select, text

CORE = Path(__file__).resolve().parents[4]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import tp_core.features.demo.jobs  # noqa: E402, F401
from tests.unit.features.cases.helpers import (  # noqa: E402, F401  (pytest fikstürleri)
    api,
    jira,
    login,
    sim,
    sim_transport,
)
from tp_core.config import get_settings  # noqa: E402
from tp_core.features.demo import service, web  # noqa: E402
from tp_core.integrations.forge_demo import AUDIT_BASELINE, AUDIT_BREAK, BREAK_BRANCH  # noqa: E402
from tp_core.integrations.forge_local import LocalForge  # noqa: E402
from tp_core.integrations.jira import JiraNotFound, RestJira, get_jira_settings  # noqa: E402
from tp_core.models import (  # noqa: E402
    AuditEvent,
    BugDraft,
    ExternalRef,
    PullRequest,
    Run,
    Script,
    session_scope,
)
from tp_core.workflow.jobs import REGISTRY, process_one  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    "HOME": "/tmp",
}
CATALOG = (
    "export function Card() {\n"
    '  return <button data-testid="add-to-cart">Sepete ekle</button>;\n'
    "}\n"
)


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=GIT_ENV
    ).stdout.strip()


@pytest.fixture
def forge(tmp_path: Path) -> LocalForge:
    work = tmp_path / "work"
    (work / "web" / "src").mkdir(parents=True)
    (work / "e2e" / "pages").mkdir(parents=True)
    (work / "web" / "Dockerfile").write_text("FROM scratch\n")
    (work / "web" / "src" / "CatalogPage.tsx").write_text(CATALOG)
    (work / "e2e" / "pages" / "locators.ts").write_text("export const x = {};\n")
    git("init", "-q", "-b", "main", str(work))
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "baslangic", cwd=work)
    git("tag", "demo-baseline", cwd=work)
    git("checkout", "-q", "-b", BREAK_BRANCH, cwd=work)
    (work / "web" / "src" / "CatalogPage.tsx").write_text(
        CATALOG.replace("add-to-cart", "cart-add")
    )
    git("commit", "-q", "-am", "kirilma", cwd=work)
    git("checkout", "-q", "main", cwd=work)
    git("checkout", "-q", "-b", "tp/repair-x", cwd=work)
    (work / "e2e" / "pages" / "locators.ts").write_text("export const x = { a: 1 };\n")
    git("commit", "-q", "-am", "onarim", cwd=work)
    repo = tmp_path / "forge" / "demo-app.git"
    repo.parent.mkdir()
    git("init", "-q", "--bare", "-b", "main", str(repo))
    git("push", "-q", str(repo), "main", BREAK_BRANCH, "tp/repair-x", "--tags", cwd=work)
    artifacts = tmp_path / "artifacts"
    (artifacts / "checks").mkdir(parents=True)
    return LocalForge(repo, artifacts)


class Ortam:
    forge: LocalForge
    calisan_sha: str | None
    ci: list[dict[str, Any]]
    jira: list[int]
    saat: datetime
    istek_dosyasi: Path
    calisan_kaynak: str
    dosya_sha: str | None


@pytest.fixture
def ortam(
    engine: Engine, forge: LocalForge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Ortam]:
    o = Ortam()
    o.forge = forge
    o.calisan_sha = forge.head_sha("demo-baseline")
    o.ci, o.jira = [], []
    o.saat = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    o.istek_dosyasi = tmp_path / "forge" / "demo-web-refresh.json"
    monkeypatch.setenv(web.REQUEST_FILE_ENV, str(o.istek_dosyasi))
    monkeypatch.setenv("TP_FORGE", "local")
    get_settings.cache_clear()

    def jira_reset() -> dict[str, Any]:
        o.jira.append(1)
        return {"durum": "tamam", "http": 200}

    o.calisan_kaynak = "dosya"
    o.dosya_sha = None
    service.set_factories(
        forge=lambda: forge,
        calisan=lambda: web.CalisanUygulama(o.calisan_sha, o.calisan_kaynak),
        sha_dosyasi=lambda: o.dosya_sha,
        jira_reset=jira_reset,
        simdi=lambda: o.saat,
    )
    import tp_core.features.ci as ci_mod

    def enqueue_ci(session: Any, sha: str, trigger: str, pr_number: Any = None, **kw: Any):
        o.ci.append({"sha": sha, "trigger": trigger, **kw})
        return uuid.uuid4()

    monkeypatch.setattr(ci_mod, "enqueue_ci", enqueue_ci)
    # Onarım ön koşulu: kırılmadan önce yeşil temel koşu (baseline push CI).
    with session_scope() as s:
        s.add(Run(id=uuid.uuid4(), commit=o.calisan_sha, kaynak="local", tetik="push",
                  sonuc="passed", ortam={"saglik": {"ok": True}}))  # fmt: skip
    yield o
    service.reset_factories()
    get_settings.cache_clear()


def _istegi_uygula(o: Any) -> None:
    """Host betiğinin (`scripts/demo-web-sync.sh`) uyguladığı isteği `.done`'a yazması."""
    istek = json.loads(o.istek_dosyasi.read_text())
    o.istek_dosyasi.with_suffix(".done").write_text(istek["istek_id"] + "\n")


def run_jobs(engine: Engine, limit: int = 10) -> list[Any]:
    out = []
    for _ in range(limit):
        s = process_one(engine, "test-demo", REGISTRY)
        if s is None:
            break
        out.append(s)
    return out


def _bekleyen_is(engine: Engine, tur: str) -> list[Any]:
    with engine.connect() as c:
        return list(
            c.execute(
                text("SELECT id, yuk, run_after FROM job WHERE tur = :t AND durum = 'queued'"),
                {"t": tur},
            )
        )


def _hemen(engine: Engine) -> None:
    with engine.begin() as c:
        c.execute(text("UPDATE job SET run_after = now() WHERE durum = 'queued'"))


def _eylemler(engine: Engine) -> list[tuple[str, str, Any]]:
    with session_scope() as s:
        return [
            (r.aktor, r.eylem, r.ozet)
            for r in s.execute(
                select(AuditEvent.aktor, AuditEvent.eylem, AuditEvent.ozet).order_by(AuditEvent.id)
            )
        ]


def test_kirilma_bypass_denetim_ve_ci_uygulamayi_bekler(
    engine: Engine, ortam: Ortam, make_user: Any
) -> None:
    sunucu = make_user("presenter")
    once = ortam.forge.head_sha("main")
    with session_scope() as s:
        out = service.request_break(s, sunucu)
    assert out["durum"] == "queued"
    assert [x.durum for x in run_jobs(engine, 1)] == ["done"]

    main = ortam.forge.head_sha("main")
    assert main != once
    assert 'data-testid="cart-add"' in ortam.forge.read_file("web/src/CatalogPage.tsx")
    pr = next(p for p in ortam.forge.list_prs() if p.branch == BREAK_BRANCH)
    kayit = ortam.forge.get_pr_record(pr.number)
    assert (kayit["merged_by"], kayit["bypass"]) == ("demo-admin", True)

    eylemler = _eylemler(engine)
    assert ("demo-admin", AUDIT_BREAK) in [(a, e) for a, e, _ in eylemler]
    demo = [oz for a, e, oz in eylemler if e == "demo.break"]
    assert demo and demo[0]["isteyen"] == sunucu.kullanici_adi
    assert demo[0]["bypass_aktoru"] == "demo-admin"
    # Uygulama yenileme isteği forge volume'üne yazıldı.
    istek = json.loads(ortam.istek_dosyasi.read_text())
    assert (istek["eylem"], istek["sha"]) == ("break", main)

    # Uygulama henüz baseline'da: CI kuyruğa ALINMAZ, iş kendini yeniden planlar.
    assert [x.durum for x in run_jobs(engine, 1)] == ["done"]
    assert ortam.ci == []
    assert len(_bekleyen_is(engine, service.AWAIT_JOB)) == 1

    # Konteyner /build.json ile main'i beyan ediyor ama toolchain'in okuduğu sha dosyası geride
    # (demo-web-sync.sh onu servis sağlıklı olunca yazar): CI hâlâ kuyruğa alınmaz.
    ortam.calisan_sha, ortam.calisan_kaynak, ortam.dosya_sha = main, "build_json", once
    _hemen(engine)
    assert [x.durum for x in run_jobs(engine, 1)] == ["done"]
    assert ortam.ci == []

    # Uygulama main'den derlendi ve sha dosyası yazıldı ama demo-web-sync isteği henüz `.done`
    # yazmadı (konteyner yeniden oluşturuluyor olabilir): CI hâlâ beklemede.
    ortam.dosya_sha = main
    _hemen(engine)
    assert [x.durum for x in run_jobs(engine, 1)] == ["done"]
    assert ortam.ci == []
    # demo-web-sync isteği uyguladı (.done) → push CI.
    _istegi_uygula(ortam)
    _hemen(engine)
    assert [x.durum for x in run_jobs(engine, 1)] == ["done"]
    assert ortam.ci == [
        {
            "sha": main,
            "trigger": "push",
            "isteyen": sunucu.kullanici_adi,
            "anahtar": ortam.ci[0]["anahtar"],
        }
    ]
    assert "demo.ci_enqueued" in [e for _, e, _ in eylemler + _eylemler(engine)]

    # İkinci kırılma idempotent: forge değişmez; aynı değişiklik için ikinci push CI açılmaz
    # (ilk bekleme işinin açtığı koşu run tablosunda).
    from tp_core.models import Run

    with session_scope() as s:
        s.add(Run(commit=main, tetik="push", kaynak="local"))
    with session_scope() as s:
        service.request_break(s, sunucu)
    run_jobs(engine, 1)
    assert ortam.forge.head_sha("main") == main
    _hemen(engine)
    run_jobs(engine, 3)
    assert len(ortam.ci) == 1


def test_uygulama_yenilenmezse_ci_yok_zaman_asimi(
    engine: Engine, ortam: Ortam, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(service.WAIT_ENV, "60")
    with session_scope() as s:
        service.request_break(s, make_user("presenter"))
    run_jobs(engine, 1)
    run_jobs(engine, 1)  # bekliyor
    ortam.saat += timedelta(seconds=120)
    _hemen(engine)
    sonuc = run_jobs(engine, 1)
    assert sonuc[0].durum == "failed"
    assert ortam.ci == []
    assert "demo.web_timeout" in [e for _, e, _ in _eylemler(engine)]


def test_yalnizca_e2e_farkliysa_uygulama_eslesir(ortam: Ortam) -> None:
    base = ortam.forge.head_sha("demo-baseline")
    onarim = ortam.forge.head_sha("tp/repair-x")
    kirik = ortam.forge.head_sha(BREAK_BRANCH)
    assert web.uygulama_eslesiyor(ortam.forge, onarim, base)[0] is True
    ok, neden = web.uygulama_eslesiyor(ortam.forge, kirik, base)
    assert ok is False and "web" in neden
    assert web.uygulama_eslesiyor(ortam.forge, kirik, None)[0] is False


def test_sifirlama(engine: Engine, ortam: Ortam, make_user: Any) -> None:
    sunucu = make_user("presenter")
    with session_scope() as s:
        service.request_break(s, sunucu)
    run_jobs(engine, 1)
    # Açık bir onarım PR'ı (tp/*) ve ona bağlı script.
    pr = ortam.forge.open_pr("tp/repair-x", "fix", "govde", ("tp-repair",))
    sid = uuid.uuid4()
    with session_scope() as s:
        s.add(
            Script(id=sid, tur="locator_fix", dosya_yolu="e2e/pages/locators.ts", pr_no=pr.number)
        )
        s.add(
            PullRequest(
                number=pr.number,
                branch=pr.branch,
                baslik="fix",
                head_sha=pr.head_sha,
                acan="tp-bot",
            )
        )
    with engine.begin() as c:
        c.execute(text("UPDATE script SET durum = 'pr_open' WHERE id = :i"), {"i": sid})
    with engine.begin() as c:
        c.execute(text("DELETE FROM job WHERE tur = :t"), {"t": service.AWAIT_JOB})

    with session_scope() as s:
        service.request_reset(s, sunucu)
    assert [x.durum for x in run_jobs(engine, 1)] == ["done"]
    base = ortam.forge.head_sha("demo-baseline")
    assert ortam.forge.head_sha("main") == base
    assert ortam.forge.get_pr(pr.number).state == "closed"
    with session_scope() as s:
        assert s.get(Script, sid).durum == "closed"  # type: ignore[union-attr]
        assert s.get(PullRequest, pr.number).durum == "closed"  # type: ignore[union-attr]
    assert ortam.jira == [1]
    istek = json.loads(ortam.istek_dosyasi.read_text())
    assert (istek["eylem"], istek["sha"]) == ("baseline", base)
    eylemler = _eylemler(engine)
    assert ("demo-admin", AUDIT_BASELINE) in [(a, e) for a, e, _ in eylemler]
    reset = next(oz for _, e, oz in eylemler if e == "demo.reset")
    assert reset["veritabani"]["durum"] == "dokunulmadi"
    assert [k["pr"] for k in reset["kapanan_prlar"]] == [pr.number]
    # Uygulama zaten baseline'da; ama demo-web-sync yenileme isteğini henüz uygulamadı (konteyneri
    # yeniden oluştururken koşan CI sağlıkta düşerdi — prova P0 yarışı): CI bekler.
    onceki = len(ortam.ci)
    run_jobs(engine, 1)
    assert len(ortam.ci) == onceki
    assert len(_bekleyen_is(engine, service.AWAIT_JOB)) == 1
    # İstek uygulandı (.done) → baseline CI kuyruğa.
    _istegi_uygula(ortam)
    _hemen(engine)
    run_jobs(engine, 1)
    assert ortam.ci and ortam.ci[-1]["sha"] == base


def test_uygulanmamis_istek_bekleme_suresi_dolunca_ci_acilir(
    engine: Engine, ortam: Ortam, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Host'ta demo-web-sync çalışmıyorsa ve uygulama zaten hedef commit'teyse CI sonsuza dek
    beklemez: istek bekleme süresi (TP_DEMO_WEB_ISTEK_BEKLEME_S) dolunca açılır."""
    monkeypatch.setenv(service.ISTEK_GRACE_ENV, "30")
    sunucu = make_user("presenter")
    with session_scope() as s:
        service.request_break(s, sunucu)
    run_jobs(engine, 1)
    with engine.begin() as c:
        c.execute(text("DELETE FROM job WHERE tur = :t"), {"t": service.AWAIT_JOB})
    with session_scope() as s:
        service.request_reset(s, sunucu)
    run_jobs(engine, 1)
    base = ortam.forge.head_sha("demo-baseline")
    run_jobs(engine, 1)
    assert ortam.ci == []
    ortam.saat += timedelta(seconds=45)
    _hemen(engine)
    run_jobs(engine, 1)
    assert ortam.ci and ortam.ci[-1]["sha"] == base


def test_api_rol_ve_durum(
    engine: Engine,
    ortam: Ortam,
    api: Any,  # noqa: F811
    make_user: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tp_core.features.demo import api as demo_api

    monkeypatch.setattr(demo_api, "BEKLEME_S", 0.3)

    login(api, make_user("analyst"))
    assert api.post("/demo/break-locator").status_code == 403
    assert api.post("/demo/reset").status_code == 403
    d = api.get("/demo/status").json()
    assert d["forge"]["testid"] == "add-to-cart" and d["forge"]["main_baseline_mi"] is True
    assert d["uygulama"]["main_ile_eslesiyor"] is True

    assert d["onarim_on_kosulu"]["hazir"] is True
    assert d["onarim_on_kosulu"]["son_yesil_kosu"]["tetik"] == "push"

    login(api, make_user("presenter"))
    r = api.post("/demo/break-locator")  # worker yok: iş kuyrukta kalır → 202
    assert r.status_code == 202, r.text
    # Süren demo işi varken ikinci istek reddedilir.
    assert api.post("/demo/reset").status_code == 409


def test_kirilma_yesil_temel_kosu_yoksa_reddedilir(
    engine: Engine,
    ortam: Ortam,
    api: Any,  # noqa: F811
    make_user: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """make reset → make break: yeşil koşu yoksa locator onarımı "son yeşil" kanıt bulamaz.
    Kırılma 409 + yönerge ile reddedilir (forge'a dokunulmaz); zorla=true bilerek atlar."""
    from tp_core.features.demo import api as demo_api

    monkeypatch.setattr(demo_api, "BEKLEME_S", 0.3)
    with engine.begin() as c:
        c.execute(text("DELETE FROM run"))
    once = ortam.forge.head_sha("main")
    login(api, make_user("presenter"))
    d = api.get("/demo/status").json()
    assert d["onarim_on_kosulu"]["hazir"] is False
    assert "make demo-reset" in d["onarim_on_kosulu"]["yonerge"]
    r = api.post("/demo/break-locator")
    assert r.status_code == 409 and "yeşil koşu yok" in r.json()["detail"]
    assert "make demo-reset" in r.json()["detail"]
    assert _bekleyen_is(engine, service.BREAK_JOB) == []
    assert ortam.forge.head_sha("main") == once
    assert "demo.break_refused" in [e for _, e, _ in _eylemler(engine)]
    r = api.post("/demo/break-locator?zorla=true")
    assert r.status_code == 202, r.text
    assert "UYARI" in r.json()["mesaj"]


def test_esszamanli_demo_istekleri_tek_is(engine: Engine, ortam: Ortam, make_user: Any) -> None:
    """İki eşzamanlı "kır" isteği: advisory kilit ikinciyi birincinin commit'ine dek bekletir;
    ikinci süren işi görür ve reddedilir (iki demo.break_locator işi açılmaz)."""
    import threading

    sunucu = make_user("presenter")
    sonuc: dict[str, Any] = {}
    s1 = session_scope().__enter__()
    try:
        service.request_break(s1, sunucu)

        def ikinci() -> None:
            try:
                with session_scope() as s2:
                    service.request_break(s2, sunucu)
                sonuc["b"] = "kabul"
            except service.DemoRejected as exc:
                sonuc["b"] = str(exc)

        t = threading.Thread(target=ikinci)
        t.start()
        t.join(1.0)
        assert t.is_alive(), "ikinci istek kilitte beklemeliydi"
        s1.commit()
    finally:
        s1.close()
    t.join(10)
    assert "sürüyor" in sonuc["b"]
    assert len(_bekleyen_is(engine, service.BREAK_JOB)) == 1


# ------------------------------------------------- jira: sıfırlama sonrası anahtar çakışması yok


def _ref(tur: str, key: str) -> None:
    with session_scope() as s:
        s.add(ExternalRef(entity_turu=tur, entity_id=uuid.uuid4(), sistem="jira",
                          idempotency_key=f"t:{tur}:{uuid.uuid4()}", external_key=key,
                          durum="created"))  # fmt: skip


def test_sifirlama_jira_simi_sifirlamaz_anahtarlar_cakismaz(
    engine: Engine,
    ortam: Ortam,
    jira: RestJira,  # noqa: F811
    make_user: Any,
) -> None:
    """make demo-reset → yayın: Test issue'ları yerinde, AI Bug'ları silinir, yeni Bug yeni anahtar.

    Eski davranış (`/sim/reset`): TPD-8.. Test issue'ları kaybolur (bug yayını 'Issue Does Not
    Exist'), sayaç geri sarılır ve yeni Bug eski bir `external_ref` anahtarını (TPD-8) yeniden alır.
    """
    test_key = jira.create_issue("TPD", "Test", "C1 · Sepete ekle", "", ["AI-generated"])
    _ref("test_case", test_key)
    ai_bug = jira.create_issue(
        "TPD",
        "Bug",
        "Sepet: 6 adette bedava",
        "",
        ["AI-generated", f"tp-{uuid.uuid4()}", "tp-mod-live"],
    )
    _ref("bug_draft", ai_bug)
    # AI etiketli ama `tp-<uuid>` işareti olmayan Bug (insan elle etiketlemiş): dokunulmaz.
    insan = jira.create_issue("TPD", "Bug", "Elle açılan", "", ["AI-generated"])
    service.set_factories(
        forge=lambda: ortam.forge,
        calisan=lambda: web.CalisanUygulama(ortam.calisan_sha, ortam.calisan_kaynak),
        sha_dosyasi=lambda: ortam.dosya_sha,
        jira_reset=lambda: service.ai_buglarini_sil(jira, "TPD"),
        simdi=lambda: ortam.saat,
    )
    # Taslaklar: biri silinecek AI Bug'ını açmış (new), biri tohum TPD-5'e bağlanmış (link).
    from tp_core.models.guard import allow_state_write

    with session_scope() as s, allow_state_write():  # test kurulumu: yayınlanmış taslaklar
        acan = BugDraft(icerik={"summary": "a"}, icerik_hash="h1", karar="new",
                        jira_key=ai_bug, durum="published")  # fmt: skip
        baglanan = BugDraft(icerik={"summary": "b"}, icerik_hash="h2", karar="link",
                            link_key="TPD-5", jira_key="TPD-5", durum="published")  # fmt: skip
        s.add_all([acan, baglanan])
        s.flush()
        acan_id, baglanan_id = acan.id, baglanan.id
    with session_scope() as s:
        service.request_reset(s, make_user("presenter"))
    assert [x.durum for x in run_jobs(engine, 1)] == ["done"]

    from tp_core.features.bugs.serialize import bug_draft_view

    with session_scope() as s:
        v_acan = bug_draft_view(s, s.get(BugDraft, acan_id))
        v_bag = bug_draft_view(s, s.get(BugDraft, baglanan_id))
    # Silinen kayda ölü bağlantı gösterilmez; durum/onay geçmişi değişmez; TPD-5 bağı kalır.
    assert v_acan["jira_silindi"] is True and v_acan["jira_url"] is None
    assert v_acan["durum"] == "published" and "silindi" in v_acan["sonuc_metni"]
    assert v_bag["jira_silindi"] is False and v_bag["jira_url"]

    with pytest.raises(JiraNotFound):
        jira.get_issue(ai_bug)
    for kalan in (test_key, insan, "TPD-1", "TPD-5"):
        assert jira.get_issue(kalan).key == kalan
    reset = next(oz for _, e, oz in _eylemler(engine) if e == "demo.reset")
    assert reset["jira"]["silinen"] == [ai_bug] and reset["jira"]["durum"] == "tamam"
    assert reset["veritabani"]["jira_silindi_isaretlenen_taslaklar"] == [str(acan_id)]

    # Sıfırlama sonrası yayın (publish_bug'ın Jira adımları): Bug açılır, Test issue'ya bağlanır;
    # yeni anahtar veritabanındaki hiçbir external_ref anahtarıyla çakışmaz.
    yeni = jira.create_issue("TPD", "Bug", "Yeni prova", "", ["AI-generated"])
    jira.link_issues(yeni, test_key, "Relates")
    with session_scope() as s:
        db_anahtarlari = set(s.scalars(select(ExternalRef.external_key)).all())
    assert yeni not in db_anahtarlari and yeni not in (ai_bug, test_key)


def test_sifirlama_gercek_jiraya_dokunmaz(
    engine: Engine, ortam: Ortam, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://ornek.atlassian.net")
    get_jira_settings.cache_clear()
    try:
        service.set_factories(
            forge=lambda: ortam.forge,
            calisan=lambda: web.CalisanUygulama(ortam.calisan_sha, ortam.calisan_kaynak),
            sha_dosyasi=lambda: ortam.dosya_sha,
            simdi=lambda: ortam.saat,
        )
        with session_scope() as s:
            service.request_reset(s, make_user("presenter"))
        assert [x.durum for x in run_jobs(engine, 1)] == ["done"]
    finally:
        get_jira_settings.cache_clear()
    reset = next(oz for _, e, oz in _eylemler(engine) if e == "demo.reset")
    assert reset["jira"]["durum"] == "atlandi" and "gerçek Jira" in reset["jira"]["neden"]


# ------------------------------------- GitHub kipi: insan kimliğiyle PR (bot asla yazmaz/merge)


class _GithubGibi:
    """Yerel forge'u saran ama `reset_branch` sunmayan (GitHub kipi) forge."""

    def __init__(self, ic: LocalForge) -> None:
        self._ic = ic

    def __getattr__(self, ad: str) -> Any:
        if ad == "reset_branch":
            raise AttributeError(ad)
        return getattr(self._ic, ad)


def _gh_forge(gh: Any, *, merge: bool = True) -> Any:
    import httpx

    from tests.unit.integrations.github_repo_fake import BOT_TOKEN, HUMAN_TOKEN, REPO
    from tp_core.integrations.forge_github import GitHubForge, TokenAuth

    return GitHubForge(
        REPO,
        TokenAuth(BOT_TOKEN),
        merge_auth=TokenAuth(HUMAN_TOKEN) if merge else None,
        transport=httpx.MockTransport(gh),
    )


@pytest.fixture
def github_ortam(ortam: Ortam, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Ortam, Any]]:
    from tests.unit.integrations.github_repo_fake import FakeGitHubRepo
    from tp_core.integrations import forge_demo

    monkeypatch.delenv(forge_demo.APP_ROOT_ENV, raising=False)
    forge_demo.clear_cache()
    gh = FakeGitHubRepo()
    forge = _gh_forge(gh)
    service.set_factories(
        forge=lambda: forge,
        calisan=lambda: web.CalisanUygulama(ortam.calisan_sha, ortam.calisan_kaynak),
        sha_dosyasi=lambda: ortam.dosya_sha,
        jira_reset=lambda: {"durum": "atlandi"},
        simdi=lambda: ortam.saat,
    )
    yield ortam, gh
    forge_demo.clear_cache()


def test_github_kipinde_kirilma_ve_sifirlama_insan_kimligiyle(
    engine: Engine,
    github_ortam: tuple[Ortam, Any],
    api: Any,  # noqa: F811
    make_user: Any,
) -> None:
    from tests.unit.integrations.github_repo_fake import BOT_TOKEN, HUMAN_LOGIN

    ortam, gh = github_ortam
    login(api, make_user("presenter"))
    d = api.get("/demo/status").json()
    assert d["locator_demo"]["destekleniyor"] is True and d["locator_demo"]["kip"] == "github"
    assert d["forge"]["main_baseline_mi"] is True and d["locator_durumu"] == "baseline"

    sunucu = make_user("presenter")
    once = gh.refs["heads/main"]
    with session_scope() as s:
        out = service.request_break(s, sunucu)
    assert "GitHub" in out["mesaj"]
    assert [x.durum for x in run_jobs(engine, 1)] == ["done"]
    main = gh.refs["heads/main"]
    assert main != once and gh.writes_by(BOT_TOKEN) == []
    kirilma_pr = next(pr for pr in gh.prs.values() if pr["branch"].startswith(BREAK_BRANCH))
    assert kirilma_pr["merged_by"] == HUMAN_LOGIN
    demo = next(oz for _, e, oz in _eylemler(engine) if e == "demo.break")
    assert demo["kip"] == "github" and demo["main_sonra"] == main
    # GitHub CI (Actions push) doğrudan izlenir; çalışan uygulama için yenileme isteği yazılır.
    assert [(c["sha"], c["trigger"]) for c in ortam.ci] == [(main, "push")]
    istek = json.loads(ortam.istek_dosyasi.read_text())
    assert (istek["eylem"], istek["sha"]) == ("break", main)
    assert _bekleyen_is(engine, service.AWAIT_JOB) == []
    assert api.get("/demo/status").json()["locator_durumu"] == "kirik"

    # Açık bir tp/* PR'ı (bot) sıfırlamada kapatılır.
    forge = service._forge()
    forge.commit_files("tp/case-x", {"demo-app/e2e/tests/generated/x.spec.ts": "x\n"}, "m")
    acik = forge.open_pr("tp/case-x", "case", "gövde")
    with session_scope() as s:
        service.request_reset(s, sunucu)
    assert [x.durum for x in run_jobs(engine, 1)] == ["done"]
    assert gh.files_at("main") == gh.files_at("demo-baseline")
    assert main in gh.ancestors(gh.refs["heads/main"])  # force-push yok
    assert gh.prs[acik.number]["state"] == "closed"
    reset = next(oz for _, e, oz in _eylemler(engine) if e == "demo.reset")
    assert reset["kip"] == "github" and reset["forge"]["degisti"] is True
    assert reset["kapanan_prlar"] == [{"pr": acik.number, "dal": "tp/case-x", "hata": None}]
    sifirlama_pr = gh.prs[reset["forge"]["pr"]]
    assert sifirlama_pr["author"] == HUMAN_LOGIN and sifirlama_pr["merged_by"] == HUMAN_LOGIN
    assert api.get("/demo/status").json()["forge"]["main_baseline_mi"] is True


def test_github_kipinde_insan_kimligi_yoksa_is_duser(
    engine: Engine, github_ortam: tuple[Ortam, Any], make_user: Any
) -> None:
    ortam, gh = github_ortam
    service.set_factories(
        forge=lambda: _gh_forge(gh, merge=False),
        calisan=lambda: web.CalisanUygulama(ortam.calisan_sha, ortam.calisan_kaynak),
        simdi=lambda: ortam.saat,
    )
    once = gh.refs["heads/main"]
    with session_scope() as s:
        service.request_break(s, make_user("presenter"))
    assert [x.durum for x in run_jobs(engine, 1)] == ["failed"]
    assert gh.refs["heads/main"] == once and gh.prs == {}
    hata = next(oz for _, e, oz in _eylemler(engine) if e == "demo.break_failed")
    assert hata["kip"] == "github" and "GITHUB_MERGE_TOKEN" in hata["yonerge"]
    assert ortam.ci == []


def test_yerel_kipte_locator_demo_destekli(ortam: Ortam) -> None:
    assert service.durum(ortam.forge)["locator_demo"] == {"destekleniyor": True, "neden": None}


# ------------------------------------------- make break (host yolu): yeşil koşu ön denetimi


def test_make_break_on_denetimi(
    engine: Engine,
    ortam: Ortam,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`scripts/demo-break.sh --make` (make break) core API'sini atlar; aynı ön koşul burada."""
    from tp_core.features.demo import __main__ as cli

    assert cli.main(["on-kosul", "--isteyen", "make-break:t"]) == 0
    assert json.loads(capsys.readouterr().out)["hazir"] is True

    with engine.begin() as c:
        c.execute(text("DELETE FROM run"))  # make reset && make seed: koşu yok
    assert cli.main(["on-kosul", "--isteyen", "make-break:t"]) == cli.RED_KODU
    out = json.loads(capsys.readouterr().out)
    assert out["hazir"] is False and "yeşil koşu yok" in out["neden"]
    assert "make demo-reset" in out["neden"]
    red = [oz for a, e, oz in _eylemler(engine) if e == "demo.break_refused"]
    assert red and red[-1]["yol"] == "make break"

    assert cli.main(["on-kosul", "--zorla"]) == 0
    assert "son yeşil yok" in json.loads(capsys.readouterr().out)["uyari"]
    assert "demo.break_forced" in [e for _, e, _ in _eylemler(engine)]

    # GitHub kipi: insan kimliği (GITHUB_MERGE_TOKEN) yoksa make break de kırmaz.
    service.set_factories(forge=lambda: _GithubGibi(ortam.forge))
    monkeypatch.delenv("GITHUB_MERGE_TOKEN", raising=False)
    assert cli.main(["on-kosul", "--zorla"]) == cli.RED_KODU
    assert "GITHUB_MERGE_TOKEN" in json.loads(capsys.readouterr().out)["neden"]
    monkeypatch.setenv("GITHUB_MERGE_TOKEN", "insan")
    assert cli.main(["on-kosul", "--zorla"]) == 0  # insan kimliği var: GitHub kipi engel değil


def test_demo_break_betigi_make_yolunda_on_denetim_ister() -> None:
    """Host yolu ön denetimi atlayamaz: core-worker'a ulaşılamazsa da kırmaz."""
    betik = (CORE.parent / "scripts" / "demo-break.sh").read_text()
    make_blogu = betik[betik.index('if [ "$MAKE" = 1 ]') : betik.index("demo_api_login\non_kosul")]
    assert "python -m tp_core.features.demo on-kosul" in make_blogu
    assert make_blogu.index("on-kosul") < make_blogu.index('forge-init.sh" break')
    assert "kırılma yapılmadı" in make_blogu.split("*)")[-1]
    reset = (CORE.parent / "scripts" / "demo-reset.sh").read_text()
    assert '/sim/reset"' not in reset and "curl" not in reset
