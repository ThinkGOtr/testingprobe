"""Home "Sıfırla" — demo tam sıfırlaması (`features/demo/tam_sifirlama.py`, `/admin/demo-sifirla`).

En önemli güvence: proje kapsamlı silme YALNIZ hedef projenin iş verisini siler; diğer projenin
(Maintenance Agent) her tablosu aynen kalır, hedef projenin yapılandırması / denetim zinciri /
test verisi kataloğu korunur.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

import tp_core.features.demo.jobs  # noqa: F401  (iş işleyicileri)
from tests.unit.features.bugs.helpers import (
    make_requirement,
    seed_failure,
    seed_finding_draft,
)
from tests.unit.features.demo.test_demo import Ortam, forge, ortam  # noqa: F401  (fikstürler)
from tp_core.audit import append_audit
from tp_core.config import get_settings
from tp_core.features.demo import tam_sifirlama as ts
from tp_core.features.otomasyon import ayarlar
from tp_core.integrations.jira import RestJira
from tp_core.models import Script, session_scope
from tp_core.proje import proje_icinde
from tp_core.workflow.jobs import JobContext, enqueue

REPO = Path(__file__).resolve().parents[5]
SIM_SRC = REPO / "sims" / "jira-sim" / "src"
if str(SIM_SRC) not in sys.path:
    sys.path.insert(0, str(SIM_SRC))

from jira_sim.app import create_app  # noqa: E402

BASE = "http://jira-sim:8090"
WRITER = ("writer@sim.local", "t")


# ------------------------------------------------------------------------------ yardımcılar


def _tum_kapsamli_tablolar(engine: Engine) -> list[str]:
    with engine.connect() as c:
        return list(
            c.execute(
                text(
                    "SELECT table_name FROM information_schema.columns WHERE table_schema = "
                    "'public' AND column_name = 'project_id' AND table_name <> 'demo_sifirlama' "
                    "ORDER BY 1"
                )
            ).scalars()
        )


def _sayimlar(engine: Engine, pid: str) -> dict[str, int]:
    with engine.connect() as c:
        return {
            t: int(
                c.execute(
                    text(f"SELECT count(*) FROM {t} WHERE project_id = :p"), {"p": pid}
                ).scalar_one()
            )
            for t in _tum_kapsamli_tablolar(engine)
        }


def _tohumla(engine: Engine, pid: str) -> None:
    """Bir projeye prova izi: gereksinim, case, koşu, hata, bug taslakları, script (failure_id
    döngüsü), iş kuyruğu, otomasyon ayarı + tetik tabanı, denetim kaydı."""
    with proje_icinde(pid, kaynak="test"):
        rid = make_requirement("TPD-1" if pid.endswith("a") else "MNT-1")
        f = seed_failure(None, req_id=rid, test_issue=False, triage_ek=True)
        seed_finding_draft("F4", req_id=rid)
        with session_scope() as s:
            sc = Script(dosya_yolu=f"tests/generated/{pid}.spec.ts", failure_id=f["failure_id"])
            s.add(sc)
            s.flush()
            ayarlar.yaz(s, "jira_tetik", {"acik": True, "durum": "QA To Do"}, "test")
            ayarlar.tetik_tabani_yaz(s, "QA To Do", datetime.now(UTC))
        with engine.begin() as c:
            c.execute(text("UPDATE run SET script_id = :s WHERE project_id = :p"),
                      {"s": sc.id, "p": pid})  # fmt: skip
            enqueue(c, "noop", {}, idempotency_key=f"bekleyen-{pid}")
            j = enqueue(c, "noop", {}, idempotency_key=f"bitmis-{pid}")
            c.execute(text("UPDATE job SET durum = 'failed' WHERE id = :j"), {"j": j})
            append_audit(c, "test", "test.olay", "x", {}, project_id=pid)
            c.execute(
                text("INSERT INTO hata_kosusu (project_id, durum) VALUES (:p, 'done')"),
                {"p": pid},
            )


@pytest.fixture
def demo_kipi(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TP_DEMO_MODE", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    ts.reset_factories()


# --------------------------------------------------------------------- proje kapsamlı silme


def test_silme_yalniz_hedef_projeye_dokunur(engine: Engine, iki_proje: tuple[str, str]) -> None:
    a, b = iki_proje
    _tohumla(engine, a)
    _tohumla(engine, b)
    once_a, once_b = _sayimlar(engine, a), _sayimlar(engine, b)
    assert once_a["requirement"] and once_a["run"] and once_a["bug_draft"] and once_a["script"]
    assert once_a["job"] >= 2 and once_a["hata_kosusu"] == 1

    sayim = ts.proje_verisini_sil(engine, a)
    assert sayim["gereksinim"] == once_a["requirement"]

    assert _sayimlar(engine, b) == once_b  # diğer proje: HER tablo aynen
    sonra_a = _sayimlar(engine, a)
    for t in ts.BOS_OLMALI:
        assert sonra_a[t] == 0, t
    assert sonra_a["job"] == 0
    # Korunanlar: denetim zinciri (append-only), model çağrıları, otomasyon AYARLARI (taban hariç).
    assert sonra_a["audit_event"] >= once_a["audit_event"]
    with engine.connect() as c:
        anahtarlar = set(
            c.execute(
                text("SELECT anahtar FROM otomasyon_ayari WHERE project_id = :p"), {"p": a}
            ).scalars()
        )
    assert anahtarlar == {"jira_tetik"}  # fmt: skip
    for t in ("ai_call", "tool_call", "review", "test_verisi", "api_token", "asistan_sohbet"):
        assert sonra_a[t] == once_a[t], t


def test_kosan_is_varsa_bekler_sure_dolunca_hicbir_sey_silmez(
    engine: Engine, iki_proje: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, _ = iki_proje
    _tohumla(engine, a)
    with engine.begin() as c:
        c.execute(
            text("UPDATE job SET durum = 'running' WHERE project_id = :p AND durum = 'failed'"),
            {"p": a},
        )
    monkeypatch.setenv(ts.BEKLE_ENV, "0")
    once = _sayimlar(engine, a)
    with pytest.raises(ts.TamSifirlamaHatasi, match="süren iş var"):
        ts.proje_verisini_sil(engine, a)
    sonra = _sayimlar(engine, a)
    assert sonra["requirement"] == once["requirement"] and sonra["run"] == once["run"]
    with engine.connect() as c:
        durumlar = set(c.execute(text("SELECT durum FROM job WHERE project_id = :p"),
                                 {"p": a}).scalars())  # fmt: skip
    assert durumlar == {"running", "cancelled"}  # bekleyen iş claim edilmesin diye iptal


# ------------------------------------------------------------------------- istek / işlem


def _aktor() -> dict[str, str]:
    return {"uid": "u1", "email": "admin@ornek.com", "ad": "Yönetici"}


def test_istek_reddi_kurallari(
    engine: Engine, iki_proje: tuple[str, str], demo_kipi: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = iki_proje
    with pytest.raises(ts.IstekReddi) as e:
        ts.istek(engine, "yok-proje", _aktor())
    assert e.value.kod == "proje_yok"
    with pytest.raises(ts.IstekReddi) as e:
        ts.istek(engine, b, _aktor())  # varsayılan proje değil
    assert e.value.kod == "demo_proje_degil"
    islem = ts.istek(engine, a, _aktor())
    assert islem["durum"] == "kuyrukta" and [x["kod"] for x in islem["adimlar"]] == list(ts.ADIMLAR)
    with pytest.raises(ts.IstekReddi) as e:
        ts.istek(engine, a, _aktor())
    assert e.value.kod == "suruyor" and e.value.islem and e.value.islem["id"] == islem["id"]
    # İş düştüyse (zaman aşımı) işlem "hata" görünür ve yeni istek kabul edilir.
    with engine.begin() as c:
        c.execute(text("UPDATE job SET durum = 'failed' WHERE tur = :t"), {"t": ts.TAM_JOB})
    assert ts.oku(engine, uuid.UUID(islem["id"]))["durum"] == "hata"
    yeni = ts.istek(engine, a, _aktor())
    assert yeni["id"] != islem["id"]
    monkeypatch.setenv("TP_DEMO_MODE", "0")
    get_settings.cache_clear()
    with engine.begin() as c:
        c.execute(text("UPDATE demo_sifirlama SET durum = 'tamam'"))
    with pytest.raises(ts.IstekReddi) as e:
        ts.istek(engine, a, _aktor())
    assert e.value.kod == "demo_proje_degil"


@pytest.fixture
def sim_jira() -> Iterator[RestJira]:
    class T(httpx.BaseTransport):
        def __init__(self, c: TestClient) -> None:
            self.c = c

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            r = self.c.request(request.method, str(request.url), headers=dict(request.headers),
                               content=request.read())  # fmt: skip
            return httpx.Response(r.status_code, headers=dict(r.headers), content=r.content)

    with TestClient(create_app(data_path="", base_url=BASE, po_password="p"), base_url=BASE) as c:
        yield RestJira(BASE, ("reader@sim.local", "t"), WRITER, http=httpx.Client(transport=T(c)))


def _calistir(engine: Engine, islem: dict[str, Any]) -> dict[str, Any]:
    with engine.connect() as c:
        job_id = c.execute(text("SELECT job_id FROM demo_sifirlama WHERE id = :i"),
                           {"i": islem["id"]}).scalar_one()  # fmt: skip
        c.execute(text("SELECT 1"))
    with engine.begin() as c:
        c.execute(text("UPDATE job SET durum = 'running' WHERE id = :j"), {"j": job_id})
    ts.run(
        JobContext(job_id, ts.TAM_JOB, {"islem_id": islem["id"], "project_id": islem["project_id"]},
                   1, 1),
        engine,
    )  # fmt: skip
    return ts.oku(engine, uuid.UUID(islem["id"]))


def test_uctan_uca_tamam_ve_kontrol_listesi(
    engine: Engine,
    iki_proje: tuple[str, str],
    ortam: Ortam,  # noqa: F811
    sim_jira: RestJira,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b = iki_proje
    _tohumla(engine, a)
    _tohumla(engine, b)
    once_b = _sayimlar(engine, b)
    monkeypatch.setenv("JIRA_BASE_URL", BASE)
    monkeypatch.setenv("JIRA_PROJECT", "TPD")
    monkeypatch.setenv("JIRA_PO_ACCOUNT_IDS", "po-hesabi-1")
    ts.set_factories(
        jira=lambda: sim_jira,
        forge=lambda: ortam.forge,
        kancalar=lambda pid: [],
        web_izleyici=lambda: {"calisiyor": True, "ayrinti": "izleyici çalışıyor"},
        calisan=lambda: type("C", (), {"sha": ortam.forge.head_sha("main")})(),
        uyku=lambda s: None,
    )
    try:
        islem = ts.istek(engine, a, _aktor())
        son = _calistir(engine, islem)
    finally:
        ts.reset_factories()
    assert son["durum"] == "tamam", son
    assert [x["durum"] for x in son["adimlar"]] == ["tamam"] * len(ts.ADIMLAR)
    kontrol = {k["kod"]: k["durum"] for k in son["kontrol"]}
    for kod in ("tp_bos", "otomasyon", "jira_durumlar", "jira_icerik", "jira_fazla", "jira_po",
                "github_main", "github_pr", "web_izleyici", "uygulama_main"):  # fmt: skip
        assert kontrol.get(kod) == "tamam", (kod, son["kontrol"])
    assert son["hazir"] is True
    assert _sayimlar(engine, b) == once_b  # diğer proje uçtan uca da aynen
    with proje_icinde(a, kaynak="test"), session_scope() as s:
        assert ayarlar.jira_tetik(s) == ayarlar.JiraTetik(
            acik=False, durum="To Do", aralik_s=30, otomatik_case=False)  # fmt: skip
        assert ayarlar.otomatik_kod(s).acik is False
    with engine.connect() as c:
        eylemler = list(
            c.execute(
                text("SELECT eylem FROM audit_event WHERE project_id = :p ORDER BY id"), {"p": a}
            ).scalars()
        )
    for eylem in (ts.AUDIT_ISTENDI, ts.AUDIT_TAMAM, "demo.reset"):
        assert eylem in eylemler


def test_adim_hatasi_kalinan_adimi_gosterir_ve_yeniden_denenebilir(
    engine: Engine,
    iki_proje: tuple[str, str],
    demo_kipi: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, _ = iki_proje

    def patla(_e: Engine, _b: dict[str, Any]) -> tuple[str, Any]:
        raise ts.TamSifirlamaHatasi("Jira erişilemedi")

    monkeypatch.setattr(ts, "adim_jira", patla)
    ts.set_factories(kancalar=lambda pid: [])
    islem = ts.istek(engine, a, _aktor())
    son = _calistir(engine, islem)
    assert son["durum"] == "hata" and son["hata"] == "Jira erişilemedi"
    durumlar = {x["kod"]: x["durum"] for x in son["adimlar"]}
    assert durumlar == {"otomasyon": "tamam", "tp_veri": "tamam", "jira": "hata",
                        "github": "bekliyor", "dogrulama": "bekliyor"}  # fmt: skip
    assert ts.istek(engine, a, _aktor())["id"] != islem["id"]  # yeniden denenir


def test_baseline_korumasi_eski_etiketi_durdurur() -> None:
    class F:
        def __init__(self, main: list[str], etiket: list[str]) -> None:
            self.d = {"main": main, "demo-baseline": etiket}

        def list_files(self, prefix: str = "", ref: str = "main") -> list[str]:
            return self.d[ref]

    temel = ["demo-app/web/index.html", "README.md"]
    uretilen = [
        "demo-app/e2e/tests/generated/tpd-1-c1-0a1b2c3d.spec.ts",
        "demo-app/e2e-app/src/test/java/com/antreklabs/bayi/uretilen/TPD1AndroidC3_0a1bTest.java",
        "demo-app/e2e-csharp/Tests/Generated/Tpd1C2.cs",
    ]
    assert ts.baseline_korumasi(F(temel + uretilen, temel))["silinecek_uretilen"] == 3
    with pytest.raises(ts.TamSifirlamaHatasi, match="etiketi eski"):
        ts.baseline_korumasi(F([*temel, "demo-app/mobile/App.tsx"], temel))


def test_api_yalniz_home_servis_kimligi(db: Any, iki_proje: tuple[str, str], demo_kipi: None,
                                        monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    from tp_core.api.main import create_app as tp_app
    from tp_core.auth import aiprobe

    monkeypatch.setenv("TP_AUTH_MODE", "aiprobe")
    monkeypatch.setenv("AIPROBE_HOME_SA", "home@sa.iam")
    monkeypatch.setenv("AIPROBE_TP_AUDIENCE", "https://tp")
    get_settings.cache_clear()

    def dogrula(token: str, aud: str) -> dict[str, Any]:
        if token == "home":
            return {"email": "home@sa.iam", "email_verified": True, "aud": aud}
        if token == "baska":
            return {"email": "baska@sa.iam", "email_verified": True, "aud": aud}
        raise ValueError("imza")

    eski = aiprobe.dogrulayici
    monkeypatch.setattr(aiprobe, "dogrulayici", lambda: dogrula)
    a, _ = iki_proje
    with TestClient(tp_app()) as c:
        assert c.get("/admin/demo-sifirla", params={"project_id": a}).status_code == 401
        r = c.get("/admin/demo-sifirla", params={"project_id": a},
                  headers={"Authorization": "Bearer baska"})  # fmt: skip
        assert r.status_code == 403
        h = {"Authorization": "Bearer home"}
        r = c.get("/admin/demo-sifirla/onizleme", params={"project_id": a}, headers=h)
        assert r.status_code == 200 and r.json()["jira"]["tohum"][0] == "TPD-1"
        r = c.post("/admin/demo-sifirla", json={"project_id": a, "aktor": _aktor()}, headers=h)
        assert r.status_code == 202, r.text
        iid = r.json()["islem"]["id"]
        r = c.post("/admin/demo-sifirla", json={"project_id": a, "aktor": _aktor()}, headers=h)
        assert r.status_code == 409 and r.json()["kod"] == "suruyor"
        assert r.json()["islem"]["id"] == iid
        assert c.get(f"/admin/demo-sifirla/{iid}", headers=h).json()["islem"]["id"] == iid
        assert c.get("/admin/demo-sifirla/yok", headers=h).status_code == 404
        assert c.get("/admin/demo-sifirla", params={"project_id": a},
                     headers=h).json()["islem"]["id"] == iid  # fmt: skip
    assert eski is not None


def test_izleyici_kalp_atisi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tp_core.features.demo import web

    dosya = tmp_path / "demo-web-sync.alive"
    monkeypatch.setenv(web.IZLEYICI_FILE_ENV, str(dosya))
    assert web.izleyici_durumu()["calisiyor"] is False  # dosya yok
    dosya.write_text("1000\n")
    assert web.izleyici_durumu(simdi=1030)["calisiyor"] is True
    eski = web.izleyici_durumu(simdi=1000 + web.IZLEYICI_ESIK_S + 5)
    assert eski["calisiyor"] is False and "durmuş" in eski["ayrinti"]


def test_demo_web_sync_izleyicisi_kalp_atisi_yazar_ve_tp_vmde_kurulur() -> None:
    kok = REPO
    betik = (kok / "scripts" / "demo-web-sync.sh").read_text()
    assert "/forge/demo-web-sync.alive" in betik
    up = (kok / "deploy" / "aiprobe" / "bin" / "up.sh").read_text()
    assert "tp-demo-web-sync.service" in up and "TP_DEMO_MODE" in up
    birim = (kok / "deploy" / "aiprobe" / "tp-demo-web-sync.service").read_text()
    assert "demo-web-sync A=--watch" in birim and "Restart=always" in birim
