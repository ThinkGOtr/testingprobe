"""Yerel CI: enqueue_ci → ci.run → toolchain /check (sahte) → run + test_result (Postgres)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import SHA, FakeToolchain, kosu_yaz, run_jobs
from tp_core.features.ci import enqueue_ci, service, services
from tp_core.models import Job, Run, Script, ScriptTestCase, TestResult
from tp_core.models.ci_feature import CiTetik, TestResultEk
from tp_core.ports import PullRequest
from tp_core.workflow.jobs import PermanentJobError

pytestmark = pytest.mark.usefixtures("ci_env")


def _enqueue(engine: Engine, sha: str | None = SHA, tetik: str = "pr", pr: int | None = 7, **kw):
    with Session(engine) as s, s.begin():
        return enqueue_ci(s, sha, tetik, pr, **kw)


def _run(engine: Engine, run_id: uuid.UUID) -> Run:
    with Session(engine) as s:
        return s.get(Run, run_id)


def test_enqueue_kuyruga_alir_ve_etkin_kosuyu_tekrarlamaz(engine: Engine) -> None:
    rid = _enqueue(engine)
    run = _run(engine, rid)
    assert (run.sonuc, run.tetik, run.kaynak, run.commit, run.pr_no) == (
        "queued",
        "pr",
        "local",
        SHA,
        7,
    )
    assert run.ortam["retries"] == 1 and run.ortam["repeat_each"] == 1
    # Aynı commit + PR için ikinci çağrı aynı koşuyu döndürür.
    assert _enqueue(engine) == rid
    # Farklı PR yeni koşu açar.
    assert _enqueue(engine, pr=8) != rid
    with Session(engine) as s:
        isler = s.scalars(select(Job).where(Job.tur == service.JOB_RUN)).all()
        assert len(isler) == 2
        assert {j.idempotency_key for j in isler} >= {f"ci.run:{rid}"}
        olaylar = s.execute(
            text("SELECT eylem, nesne FROM audit_event WHERE eylem = 'ci.queued'")
        ).all()
        assert ("ci.queued", f"run:{rid}") in [tuple(o) for o in olaylar]


def test_gecersiz_tetik_ve_eksik_pr_reddedilir(engine: Engine) -> None:
    with pytest.raises(service.CiError):
        _enqueue(engine, tetik="break_verify")
    with pytest.raises(service.CiError):
        _enqueue(engine, tetik="pr", pr=None)
    with pytest.raises(service.CiError):
        _enqueue(engine, sha="--upload-pack=x")


def test_ci_status_olayi_yayinlanir(engine: Engine, db) -> None:
    with psycopg.connect(db.app_url.replace("+psycopg", ""), autocommit=True) as dinle:
        dinle.execute("LISTEN tp_events")
        rid = _enqueue(engine)
        olaylar = [json.loads(n.payload) for n in dinle.notifies(timeout=2, stop_after=1)]
    assert olaylar and olaylar[0]["event"] == "ci.status"
    assert olaylar[0]["data"]["id"] == str(rid)
    assert olaylar[0]["data"]["durum"] == "queued"


def test_is_toolchain_check_cagirir_sonuclari_yazar(
    engine: Engine, toolchain: FakeToolchain, artefakt_kok: Path
) -> None:
    rid = _enqueue(engine)
    run_jobs(engine)
    assert len(toolchain.istekler) == 1
    body = toolchain.istekler[0]
    # CI ile aynı: tüm testler, retries=1, repeat_each=1, AI yok.
    assert body["test_files"] == [] and body["retries"] == 1 and body["repeat_each"] == 1
    assert body["sha"] == SHA and body["ast_guard_mode"] == "pr"
    assert body["run_id"] == f"ci-{rid}-1"
    run = _run(engine, rid)
    assert run.sonuc == "failed"
    assert run.sure_ms == 15000
    a = run.artefaktlar
    assert a["dizin"] == f"runs/ci-{rid}-1"
    assert a["junit"] == "src/e2e/results/junit.xml"
    assert a["html"] == "src/e2e/results/html"
    assert a["checks"] == {
        "yol": f"checks/{SHA}.json",
        "var": True,
        "durum": "completed",
        "conclusion": "failure",
    }
    assert a["sayilar"] == {"toplam": 9, "gecen": 4, "basarisiz": 3, "flaky": 1, "atlanan": 1}
    with Session(engine) as s:
        rows = {
            r.test_adi: r for r in s.scalars(select(TestResult).where(TestResult.run_id == rid))
        }
        assert len(rows) == 9
        alti = rows["TPD-1 › 6 adet → bedava yok"]
        assert (alti.sonuc, alti.retry, alti.commit, alti.tetik, alti.kaynak) == (
            "failed",
            1,
            SHA,
            "pr",
            "local",
        )
        flaky = rows["TPD-1 › Sepete ekle sepet sayacını artırır"]
        assert (flaky.sonuc, flaky.retry) == ("flaky", 1)
        ek = s.get(
            TestResultEk, rows["Erişilebilirlik @a11y › sepet sayfası (uyarı ve satırlarla)"].id
        )
        assert (ek.a11y_ihlal, ek.a11y_kritik) == (3, 1)
        assert (
            s.scalar(
                select(text("count(*)"))
                .select_from(text("audit_event"))
                .where(text("eylem = 'ci.completed'"))
            )
            == 1
        )
    # Çekirdek checks/<sha>.json'u yazmaz: toolchain'in yazdığı dosya aynen durur.
    veri = json.loads((artefakt_kok / "checks" / f"{SHA}.json").read_text())
    assert veri["checks"][0]["conclusion"] == "failure"


def test_basarili_kosu_passed(engine: Engine, toolchain: FakeToolchain) -> None:
    toolchain.secenek = {
        "durum": "passed",
        "conclusion": "success",
        "junit": b'<testsuites><testsuite name="a"><testcase name="x" classname="a.spec.ts" time="1"/></testsuite></testsuites>',  # noqa: E501
        "results": b"",
    }
    rid = _enqueue(engine, tetik="push", pr=None)
    run_jobs(engine)
    run = _run(engine, rid)
    assert run.sonuc == "passed"
    assert run.artefaktlar["raporlar"] == {"junit": True, "json": False}


def test_statik_adim_kirmiziysa_failed_test_yok(engine: Engine, toolchain: FakeToolchain) -> None:
    def yanit(body):
        return httpx.Response(
            200,
            json={
                "sha": body["sha"],
                "conclusion": "failure",
                "failed_steps": ["tsc"],
                "summary": "Yerel CI başarısız: tsc",
                "deps": {"ok": True},
                "tsc": {"ok": False, "error": "TS2304"},
                "eslint": {"ok": False, "skipped": True, "reason": "önceki adım başarısız"},
                "ast_guard": {"ok": False, "skipped": True, "reason": "önceki adım başarısız"},
                "run": {"ok": False, "skipped": True, "reason": "önceki adım başarısız"},
                "duration_ms": 900,
            },
        )

    toolchain.yanit = yanit
    rid = _enqueue(engine)
    run_jobs(engine)
    run = _run(engine, rid)
    assert run.sonuc == "failed"
    assert run.artefaktlar["adimlar"]["tsc"]["ok"] is False
    assert run.artefaktlar["sayilar"]["toplam"] == 0
    assert any("koşmadı" in u for u in run.artefaktlar["uyarilar"])


def test_saglik_hatasi_error_ve_serilestirmede_gorunur(
    engine: Engine, toolchain: FakeToolchain
) -> None:
    toolchain.secenek = {"durum": "error", "saglik_ok": False, "junit": b"", "results": b""}
    rid = _enqueue(engine)
    run_jobs(engine)
    with Session(engine) as s:
        k = service.list_runs(s)[0]
    assert k["id"] == str(rid) and k["durum"] == "error"
    assert "sağlık" in k["saglik_hatasi"]
    # Playwright başlatılmadı: kırık rapor bağlantısı verilmez.
    assert k["rapor_url"] is None and k["junit_url"] is None


def test_gecici_toolchain_hatasi_yeniden_denenir_son_denemede_error(
    engine: Engine, toolchain: FakeToolchain
) -> None:
    toolchain.yanit = lambda body: httpx.Response(409, json={"detail": "Başka kontrol sürüyor"})
    rid = _enqueue(engine)
    with pytest.raises(Exception, match="409"):
        service.run_job(engine, rid, deneme=1, son_deneme=False)
    assert _run(engine, rid).sonuc == "running"
    with pytest.raises(Exception, match="409"):
        service.run_job(engine, rid, deneme=3, son_deneme=True)
    run = _run(engine, rid)
    assert run.sonuc == "error" and "409" in run.artefaktlar["hata"]
    # Bitmiş koşu yeniden işlenmez.
    assert service.run_job(engine, rid, deneme=4, son_deneme=True)["durum"] == "atlandi"


def test_kalici_toolchain_hatasi_hemen_error(engine: Engine, toolchain: FakeToolchain) -> None:
    toolchain.yanit = lambda body: httpx.Response(404, json={"detail": "Commit yok"})
    rid = _enqueue(engine)
    with pytest.raises(PermanentJobError):
        service.run_job(engine, rid, deneme=1, son_deneme=False)
    assert _run(engine, rid).sonuc == "error"


def test_onarim_pr_ast_guard_repair_modu(
    engine: Engine, toolchain: FakeToolchain, fake_forge
) -> None:
    fake_forge.prs[9] = PullRequest(
        number=9, branch="tp/repair-abc", title="x", head_sha=SHA, labels=["tp-repair"]
    )
    _enqueue(engine, pr=9)
    run_jobs(engine)
    assert toolchain.istekler[0]["ast_guard_mode"] == "repair"


def test_ref_ile_kuyruk_head_sha_cozulur(engine: Engine, toolchain: FakeToolchain) -> None:
    rid = _enqueue(engine, sha=None, tetik="deploy", pr=None)
    assert _run(engine, rid).commit is None
    run_jobs(engine)
    assert _run(engine, rid).commit == SHA
    assert toolchain.istekler[0]["sha"] == SHA


def test_test_sonucu_script_uzerinden_case_e_baglanir(
    engine: Engine, make_requirement_case
) -> None:
    case_id = make_requirement_case()
    with Session(engine) as s, s.begin():
        sc = Script(
            id=uuid.uuid4(),
            dosya_yolu="e2e/tests/generated/tpd-1-kampanya.spec.ts",
            durum="pending",
        )
        s.add(sc)
        s.flush()
        s.add(ScriptTestCase(script_id=sc.id, test_case_id=case_id))
    rid = _enqueue(engine)
    run_jobs(engine)
    with Session(engine) as s:
        rows = s.scalars(select(TestResult).where(TestResult.run_id == rid)).all()
    bagli = {r.test_adi for r in rows if r.test_case_id == case_id}
    assert bagli == {
        "TPD-1 › 7 adet Portakal Gazozu → 1 adet bedava",
        "TPD-1 › 6 adet → bedava yok",
        "TPD-1 › Minimum sipariş tutarı 750,00 TL uyarısı",
        "TPD-1 › Sepete ekle sepet sayacını artırır",
    }


def test_sonuclar_iki_kez_yazilmaz(engine: Engine, artefakt_kok: Path) -> None:
    rid = _enqueue(engine)
    rep = kosu_yaz(artefakt_kok, "ci-manual", sha=SHA)
    with Session(engine) as s, s.begin():
        run = s.get(Run, rid)
        service.ingest_check_report(s, run, rep)
    with Session(engine) as s, s.begin():
        run = s.get(Run, rid)
        ayr = service.parse_files(None, None, None)
        assert service.record_results(s, run, ayr)["toplam"] == 9
        assert (
            s.scalar(
                select(text("count(*)")).select_from(TestResult).where(TestResult.run_id == rid)
            )
            == 9
        )


def test_kotu_rapor_kosuyu_dusurmez_json_kaydedilir(engine: Engine, artefakt_kok: Path) -> None:
    """Desteklenmeyen kodlamalı junit.xml + koşu dizini dışına sembolik bağ: ingest istisna
    atmaz (iş yeniden denenmez, suite yeniden koşmaz), results.json sonuçları yazılır."""
    rid = _enqueue(engine)
    junit = '<?xml version="1.0" encoding="utf-16-le"?><testsuites/>'.encode("utf-16-le")
    rep = kosu_yaz(artefakt_kok, "ci-manual", sha=SHA, junit=junit)
    with Session(engine) as s, s.begin():
        run = s.get(Run, rid)
        assert service.ingest_check_report(s, run, rep) == "failed"
        uyarilar = run.artefaktlar["uyarilar"]
        assert run.artefaktlar["raporlar"] == {"junit": False, "json": True}
        assert run.artefaktlar["sayilar"]["toplam"] > 0
        assert any("kodlama" in u for u in uyarilar)
    sonuc = artefakt_kok / "runs" / "ci-manual" / "src" / "e2e" / "results"
    (sonuc / "junit.xml").unlink()
    (sonuc / "junit.xml").symlink_to("/etc/hosts")
    (sonuc / "results.json").unlink()
    (sonuc / "results.json").symlink_to("/dev/zero")
    ayr = service.parse_files(
        sonuc / "junit.xml",
        sonuc / "results.json",
        service.KosuDizini("/uzak", artefakt_kok / "runs" / "ci-manual"),
    )
    assert ayr.testler == [] and ayr.raporlar == {"junit": False, "json": False}
    assert sum("sembolik bağ" in u for u in ayr.uyarilar) == 2


# ---------------------------------------------------------------------------- gece


def test_gece_saati_istanbul_02() -> None:
    tarih, zaman = service.next_nightly(
        datetime(2026, 10, 31, 10, 0, tzinfo=UTC), service.time(2, 0)
    )
    assert tarih == "2026-11-01"
    assert zaman == datetime(2026, 10, 31, 23, 0, tzinfo=UTC)
    # 23:30 UTC = 02:30 İstanbul → ertesi gece
    tarih, zaman = service.next_nightly(
        datetime(2026, 10, 31, 23, 30, tzinfo=UTC), service.time(2, 0)
    )
    assert tarih == "2026-11-02"


def test_gece_planı_idempotent_ve_cift_tetik_yok(
    engine: Engine, toolchain: FakeToolchain, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TP_CI_NIGHTLY_SAAT", raising=False)
    sabit = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    with engine.begin() as conn:
        a = service.plan_nightly(conn, sabit)
    with engine.begin() as conn:
        b = service.plan_nightly(conn, sabit)
    assert a == b
    with Session(engine) as s:
        job = s.get(Job, a)
        assert job.idempotency_key == "ci.nightly:2026-11-01"
        assert job.run_after == datetime(2026, 10, 31, 23, 0, tzinfo=UTC)
    # Aynı tarih için iki kez koşsa da tek koşu (ci_tetik.anahtar UNIQUE).
    with services.override(now=lambda: datetime(2026, 10, 31, 23, 0, 5, tzinfo=UTC)):
        r1 = service.nightly_job(engine, "2026-11-01")
        r2 = service.nightly_job(engine, "2026-11-01")
    assert r1["yeni"] is True and r2["yeni"] is False and r1["run_id"] == r2["run_id"]
    with Session(engine) as s:
        assert (
            s.scalar(
                select(text("count(*)"))
                .select_from(CiTetik)
                .where(CiTetik.anahtar == "nightly:2026-11-01")
            )
            == 1
        )
        runs = s.scalars(select(Run).where(Run.tetik == "nightly")).all()
        assert len(runs) == 1
        # Ertesi gün planlandı.
        keys = set(s.scalars(select(Job.idempotency_key).where(Job.tur == service.JOB_NIGHTLY)))
        assert "ci.nightly:2026-11-02" in keys


def test_gece_kapatilabilir(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_CI_NIGHTLY_SAAT", "kapali")
    with engine.begin() as conn:
        assert service.plan_nightly(conn) is None


def test_gece_kosusu_acilamasa_da_zincir_kopmaz(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regresyon: _enqueue hata verirse ertesi günün işi geri alınmaz (ayrı işlem)."""
    monkeypatch.delenv("TP_CI_NIGHTLY_SAAT", raising=False)

    def bozuk(*a, **k):
        raise service.CiError("veritabanı hatası")

    monkeypatch.setattr(service, "_enqueue", bozuk)
    with (
        services.override(now=lambda: datetime(2026, 10, 31, 23, 0, 5, tzinfo=UTC)),
        pytest.raises(service.CiError),
    ):
        service.nightly_job(engine, "2026-11-01")
    with Session(engine) as s:
        keys = set(s.scalars(select(Job.idempotency_key).where(Job.tur == service.JOB_NIGHTLY)))
    assert "ci.nightly:2026-11-02" in keys


def test_check_zaman_asimi_toolchain_zincirinden_uzun(monkeypatch: pytest.MonkeyPatch) -> None:
    from tp_core.features.ci import clients
    from tp_core.workflow import jobs as jobq

    for ad, _ in clients.TOOLCHAIN_ZINCIRI:
        monkeypatch.delenv(ad, raising=False)
    monkeypatch.delenv("TP_CI_CHECK_TIMEOUT_S", raising=False)
    # En kötü zincir: 900 + 60 + 180 + 240 + 60 + 600 + 900 = 2940 sn (+ pay).
    assert clients.check_timeout_s() >= 2940 + clients.CHECK_PAYI_S
    assert clients.ToolchainClient("http://x")._timeout == clients.check_timeout_s()
    monkeypatch.setenv("TP_RUN_TIMEOUT_S", "1800")
    assert clients.check_timeout_s() >= 3840
    monkeypatch.setenv("TP_CI_CHECK_TIMEOUT_S", "100")  # zincirden kısa verilemez
    assert clients.check_timeout_s() >= 3840
    # İş süre sınırı istemci zaman aşımından uzun: sınır aşımı worker'ı düşürmez.
    politika = jobq.REGISTRY[service.JOB_RUN]
    assert politika.zaman_asimi_s > clients.CHECK_TIMEOUT_S


def _job(engine: Engine, rid: uuid.UUID) -> Job:
    with Session(engine) as s:
        return s.scalar(select(Job).where(Job.idempotency_key == f"ci.run:{rid}"))


def test_son_denemede_beklenmeyen_hata_kosuyu_error_yapar(
    engine: Engine, toolchain: FakeToolchain
) -> None:
    """Toolchain dışı bir hata (ör. ayrıştırma/DB/taşıma) son denemede koşuyu `running`'de
    bırakmaz; aynı tetik yeniden açılabilir."""
    with Session(engine) as s, s.begin():
        ilk = service.trigger_manual(s, "deploy", "sunucu")

    def patla(body):
        raise RuntimeError("beklenmeyen hata")

    toolchain.yanit = patla
    with pytest.raises(RuntimeError):
        service.run_job(engine, ilk["run_id"], deneme=1, son_deneme=False)
    assert _run(engine, ilk["run_id"]).sonuc == "running"  # yeniden denenecek
    with pytest.raises(RuntimeError):
        service.run_job(engine, ilk["run_id"], deneme=5, son_deneme=True)
    run = _run(engine, ilk["run_id"])
    assert run.sonuc == "error" and "beklenmeyen hata" in run.artefaktlar["hata"]
    with Session(engine) as s, s.begin():
        ikinci = service.trigger_manual(s, "deploy", "sunucu")
    assert ikinci["durum"] == "queued" and ikinci["run_id"] != ilk["run_id"]


def test_isi_bicilen_takili_kosu_yeni_tetigi_engellemez(engine: Engine) -> None:
    """Worker öldü / süre aşıldı: `reap_stale` yalnızca işi `failed` yapar; koşu `running`'de
    kalır. Yeni tetik bu koşuyu `error` ile kapatıp yeni koşu açar."""
    with Session(engine) as s, s.begin():
        ilk = service.trigger_manual(s, "deploy", "sunucu")
    rid = ilk["run_id"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE run SET sonuc = 'running' WHERE id = :r"), {"r": rid})
        conn.execute(
            text(
                "UPDATE job SET durum = 'running', baslama = now(), guncelleme = now() "
                "WHERE id = :j"
            ),
            {"j": ilk["job_id"]},
        )
    # İş sürerken koşu etkin sayılır.
    with Session(engine) as s, s.begin():
        assert service.trigger_manual(s, "deploy", "sunucu")["durum"] == "zaten_kuyrukta"
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE job SET durum = 'failed', son_hata = 'zaman aşımı: worker yanıt "
                "vermedi (nabız kesildi)', bitis = now(), guncelleme = now() WHERE id = :j"
            ),
            {"j": ilk["job_id"]},
        )
    with Session(engine) as s, s.begin():
        ikinci = service.trigger_manual(s, "deploy", "sunucu")
    assert ikinci["durum"] == "queued" and ikinci["run_id"] != rid
    run = _run(engine, rid)
    assert run.sonuc == "error" and run.bitis is not None
    assert "yarıda kaldı" in run.artefaktlar["hata"] and "nabız" in run.artefaktlar["hata"]
    with Session(engine) as s:
        assert s.scalar(
            text("SELECT count(*) FROM audit_event WHERE eylem = 'ci.completed' AND nesne = :n"),
            {"n": f"run:{rid}"},
        )


def test_worker_acilisi_takili_kosulari_kapatir(engine: Engine) -> None:
    from tp_core.features.ci import jobs as ci_jobs

    takili = _enqueue(engine, pr=21)
    suren = _enqueue(engine, pr=22)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE job SET durum = 'failed', son_hata = 'iş süresini aştı' WHERE id = :j"),
            {"j": _job(engine, takili).id},
        )
        conn.execute(text("UPDATE run SET sonuc = 'running' WHERE id = :r"), {"r": takili})
    with engine.begin() as conn:
        ci_jobs.on_worker_start(conn)
    assert _run(engine, takili).sonuc == "error"
    assert "iş süresini aştı" in _run(engine, takili).artefaktlar["hata"]
    assert _run(engine, suren).sonuc == "queued"  # işi kuyrukta: dokunulmaz


def test_acik_defect_adayinin_kirmizi_kosusu_listeden_dusmez(
    engine: Engine, make_requirement_case
) -> None:
    """C3 (6 adet sınır case'i) yerel kontrolde kaldı → defect adayı. Sonraki tetikler pencereyi
    doldursa da kırmızı kanıt koşusu filtresiz listede kalır."""
    from datetime import timedelta

    from tp_core.models.codegen_feature import ScriptCodegen
    from tp_core.models.guard import allow_state_write

    case_id = make_requirement_case(title="6 adet → bedava yok")
    eski = datetime.now(UTC) - timedelta(days=1)
    with Session(engine) as s, s.begin(), allow_state_write():
        sc = Script(id=uuid.uuid4(), dosya_yolu="e2e/tests/generated/c3.spec.ts", durum="blocked")
        s.add(sc)
        s.flush()
        s.add(
            ScriptCodegen(
                script_id=sc.id, test_case_id=case_id, case_hash="h", sira_no=3,
                engel_turu="defect_candidate",
            )
        )  # fmt: skip
        kanit = Run(
            id=uuid.uuid4(), script_id=sc.id, commit=SHA, kaynak="local", tetik="local_check",
            sonuc="failed", ortam={}, artefaktlar={},
        )  # fmt: skip
        s.add(kanit)
        s.flush()
        kanit_id = str(kanit.id)
        s.execute(text("UPDATE run SET olusturma = :t WHERE id = :r"), {"t": eski, "r": kanit.id})
    for pr in (31, 32, 33):
        _enqueue(engine, pr=pr)
    with Session(engine) as s:
        liste = service.list_runs(s, limit=2)
        filtreli = service.list_runs(s, tetik="pr", limit=2)
    ids = [x["id"] for x in liste]
    assert len(ids) == 3 and ids[-1] == kanit_id  # en eski: sona sıralı
    assert [x["sabit"] for x in liste] == [False, False, True]
    assert kanit_id not in [x["id"] for x in filtreli]


def test_silinmis_kosu_dizini_budandi_isaretlenir_baglanti_uretilmez(
    engine: Engine, artefakt_kok: Path
) -> None:
    """test-runner `prune_runs` eski koşu dizinini silince kayıt uydurulur: portal kırık
    bağlantı göstermez; volume'de duran koşulara dokunulmaz."""
    import shutil

    from tp_core.features.ci import jobs as ci_jobs

    eski = _enqueue(engine, pr=31)
    run_jobs(engine)
    yeni = _enqueue(engine, pr=32)
    run_jobs(engine)
    assert _run(engine, eski).artefaktlar["dizin"] == f"runs/ci-{eski}-1"
    shutil.rmtree(artefakt_kok / "runs" / f"ci-{eski}-1")

    with engine.begin() as conn:
        ci_jobs.on_worker_start(conn)
    a = _run(engine, eski).artefaktlar
    assert a["dizin"] is None
    assert a["budanan_dizin"] == f"runs/ci-{eski}-1" and a["artefakt_budandi"]
    assert a["sayilar"]["toplam"] == 9  # sonuçlar kalır
    assert _run(engine, yeni).artefaktlar["dizin"] == f"runs/ci-{yeni}-1"

    with Session(engine) as s:
        d = service.run_detail(s, eski)
        assert d is not None and d["artefakt_budandi"]
        for k in ("rapor_url", "junit_url", "log_url", "allure_url", "artefakt_kok"):
            assert d[k] is None, k
        assert all(not e.get("url") for r in d["sonuclar"] for e in r["ekler"])
        assert service.artifact_dir(s, eski) is None
        assert service.run_detail(s, yeni)["rapor_url"]
        # İkinci geçiş bir şey değiştirmez (idempotent).
        assert service.mark_pruned_runs(s) == 0


def test_ci_isi_sonrasi_budananlar_isaretlenir(engine: Engine, artefakt_kok: Path) -> None:
    import shutil

    eski = _enqueue(engine, pr=33)
    run_jobs(engine)
    shutil.rmtree(artefakt_kok / "runs" / f"ci-{eski}-1")
    yeni = _enqueue(engine, pr=34)
    run_jobs(engine)  # ci.run sonrası geçiş (test-runner bu koşuda eskileri siler)
    assert _run(engine, eski).artefaktlar["dizin"] is None
    assert _run(engine, yeni).artefaktlar["dizin"] == f"runs/ci-{yeni}-1"


def test_artefakt_volume_yoksa_hicbir_kosu_budanmaz(engine: Engine, artefakt_kok: Path) -> None:
    import shutil

    rid = _enqueue(engine, pr=35)
    run_jobs(engine)
    shutil.rmtree(artefakt_kok / "runs")  # volume bağlı değil / boş kök: toplu işaretleme yok
    with Session(engine) as s, s.begin():
        assert service.mark_pruned_runs(s) == 0
    assert _run(engine, rid).artefaktlar["dizin"] == f"runs/ci-{rid}-1"
