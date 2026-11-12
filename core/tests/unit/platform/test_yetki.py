"""İzin kataloğu (specs/012-rol-yetki §4): her uç bir izin ister, red 403 + `authz.denied`.

- Katalog testi: gerçek uygulamanın her API ucu bir `izin(...)` bağımlılığı taşır ya da açık
  istisna listesindedir (yeni uç izinsiz eklenirse test kırılır; varsayılan ret).
- Rol × uç matrisi: yasak uç 403 (`yetki_yok`) ve `authz.denied` denetim satırı; izinli uç 403
  değildir.
- Ortam/demo bayrakları, developer'ın üretimde koşu başlatamaması, `presenter` → `admin`, 0024 göçü.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Iterator
from typing import Any

import psycopg
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tp_core.api import main
from tp_core.auth import yetki
from tp_core.auth.login import THROTTLE
from tp_core.config import Settings, baslangic_denetimi, get_settings
from tp_core.workflow.service import Principal

from .conftest import PAROLA, Db, PgServer, run_alembic

MakeUser = Callable[..., Principal]

# Kapsam dışı uçlar (ANALIZ §4.2 sonu): giriş akışı, servis kimliği, MCP, sağlık ve imzalı
# (oturumsuz, süreli) rapor bağlantısı. İmzalı bağlantı yalnız `run.artifacts` sahibine verilir
# (koşu yanıtı diğer rollere maskelenir), bu yüzden ucun kendisi izin dışıdır.
ISTISNA: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health"),
        ("POST", "/auth/login"),
        ("POST", "/auth/logout"),
        ("GET", "/auth/me"),
        ("GET", "/auth/aiprobe/login"),
        ("GET", "/auth/aiprobe/callback"),
        ("GET", "/auth/aiprobe/hesaplar"),
        ("POST", "/auth/aiprobe/rol-sec"),
        ("POST", "/auth/aiprobe/rol-degistir"),
        ("GET", "/admin/kimlik-bagi"),
        ("GET", "/admin/kimlik-bagi/hesaplar"),
        ("PUT", "/admin/kimlik-bagi"),
        ("DELETE", "/admin/kimlik-bagi/{app_user_id}"),
        ("POST", "/mcp"),
        ("GET", "/mcp"),
        ("GET", "/artifacts/k/{token}/runs/{run_id}/{yol:path}"),
    }
)

# Karar bazlı izin: uç, gövdedeki karara göre izni kendisi denetler (`case.decide` ya da
# `case.approve`; `CurrentUser` + `yetki.reddet`, red yine 403 + `authz.denied`). S2 şeridi.
KARAR_BAZLI: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/cases/{case_id}/decision"),
        ("POST", "/cases/{case_id}/viewed"),
    }
)

# GEÇİCİ — S2 (case akışı) şeridinin uçları: S2 birleşince `izin(...)` taşırlar ve bu küme
# silinir. Küme yalnız bugün izinsiz olanları kapsar; S2 birleşince test bunu hatırlatır.
S2_GECICI: frozenset[tuple[str, str]] = frozenset()  # 012 birleşmesiyle boşaldı


def _rotalar(routes: Iterable[Any], prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    for r in routes:
        if isinstance(r, APIRoute):
            yield prefix + r.path, r
            continue
        alt = getattr(r, "original_router", None)
        if alt is not None:
            ek = getattr(getattr(r, "include_context", None), "prefix", "") or ""
            yield from _rotalar(alt.routes, prefix + ek)


def _izinler(dep: Any) -> set[str]:
    out: set[str] = set()
    cagri = dep.call
    if cagri is not None:
        if hasattr(cagri, "izin_adi"):
            out.add(cagri.izin_adi)
        out.update(getattr(cagri, "izin_adlari", ()))
    for alt in dep.dependencies:
        out |= _izinler(alt)
    return out


def uc_izinleri() -> dict[tuple[str, str], set[str]]:
    out: dict[tuple[str, str], set[str]] = {}
    for yol, r in _rotalar(main.create_app().router.routes):
        for yontem in r.methods or ():
            out[(yontem, yol)] = _izinler(r.dependant)
    return out


# ------------------------------------------------------------------ katalog


def test_her_uc_izin_tasir_ya_da_acik_istisnadir() -> None:
    muaf = ISTISNA | KARAR_BAZLI | S2_GECICI
    izinsiz = sorted(k for k, v in uc_izinleri().items() if not v and k not in muaf)
    assert izinsiz == [], f"izinsiz uç (yetki.izin(...) ekleyin): {izinsiz}"


def test_istisnalar_izin_tasimaz_ve_izinler_katalogda() -> None:
    uclar = uc_izinleri()
    for k in KARAR_BAZLI:
        assert k in uclar, f"karar bazlı uç uygulamada yok: {k}"
    for k in ISTISNA | KARAR_BAZLI:
        assert not uclar.get(k), k
    for k, izinler in uclar.items():
        for i in izinler:
            assert i in yetki.IZINLER, (k, i)


def test_s2_gecici_kumesi_guncel() -> None:
    """S2 bir ucu izne geçirince bu kümeden silinmelidir (bayat istisna kalmasın)."""
    uclar = uc_izinleri()
    bayat = sorted(k for k in S2_GECICI if uclar.get(k))
    assert bayat == [], f"S2_GECICI'den silin: {bayat}"


def test_katalog_rolleri_ve_eski_rol() -> None:
    from tp_core.models import enums

    assert enums.ROLLER == yetki.ROLLER
    assert set(yetki.ROL_ETIKETLERI) == set(yetki.ROLLER)
    assert yetki.normalize_rol("presenter") == "admin"
    assert yetki.izinli("presenter", "demo.manage")
    assert not yetki.izinli("presenter", "run.trigger_scheduled")
    assert not yetki.izinli("analyst", "olmayan.izin")  # katalogda olmayan → ret
    assert "requirement.doc_fix" not in yetki.IZINLER
    assert yetki.roller_icin("requirement.po_approve_free_text") == {"po"}


# ------------------------------------------------------------------ yardımcılar


@pytest.fixture(autouse=True)
def _throttle_sifirla() -> Iterator[None]:
    THROTTLE._kayit.clear()
    yield
    THROTTLE._kayit.clear()


@pytest.fixture
def client(db: Db) -> Iterator[TestClient]:
    with TestClient(main.create_app(), raise_server_exceptions=False) as c:
        yield c


def _giris(client: TestClient, user: Principal) -> None:
    client.cookies.clear()
    r = client.post("/auth/login", json={"kullanici_adi": user.kullanici_adi, "parola": PAROLA})
    assert r.status_code == 200, r.text


def _redler(engine: Engine, aktor: str) -> list[dict[str, Any]]:
    with engine.connect() as c:
        return [
            dict(r)
            for r in c.execute(
                text(
                    "SELECT ozet FROM audit_event WHERE eylem = 'authz.denied' AND aktor = :a "
                    "ORDER BY id"
                ),
                {"a": aktor},
            ).scalars()
        ]


# ------------------------------------------------------------------ rol × uç matrisi

R = str(uuid.UUID(int=1))
# (yöntem, yol, gövde, izin). İzinli istek kayıt olmadığı için 404/422/409/200 döner; önemli olan
# yetki katmanının ret/izin kararıdır.
MATRIS: tuple[tuple[str, str, dict[str, Any] | None, str], ...] = (
    ("GET", "/requirements", None, "requirement.read"),
    ("POST", f"/requirements/{R}/review", None, "requirement.review"),
    (
        "POST",
        f"/findings/{R}/decision",
        {"karar": "fix_doc", "icerik_hash": "h"},
        "requirement.review",
    ),
    ("POST", f"/requirements/{R}/apply-doc-fixes", None, "requirement.review"),
    (
        "POST",
        f"/requirements/{R}/po-approve",
        {"icerik_hash": "h"},
        "requirement.po_approve_free_text",
    ),
    ("PUT", f"/requirements/{R}/baseline", {"deger_s": 60, "not": "x"}, "baseline.manage"),
    ("GET", "/bug-drafts", None, "bug.read"),
    ("POST", f"/bug-drafts/{R}/prepare", None, "bug.decide"),
    ("POST", "/code/generate", {"case_ids": [R]}, "code.generate"),
    ("POST", f"/scripts/{R}/break-verify", None, "code.break_verify"),
    ("GET", "/scripts", None, "code.read"),
    ("POST", f"/failures/{R}/fix", None, "code.repair"),
    ("GET", "/failures", None, "failure.read"),
    ("GET", "/runs", None, "run.read"),
    ("GET", f"/artifacts/runs/{R}/rapor.html", None, "run.artifacts"),
    ("GET", "/control-tower", None, "dashboard.read"),
    ("GET", "/audit", None, "audit.read_all|audit.read_own"),
    ("GET", "/audit?verify=true", None, "audit.verify"),
    ("GET", "/assistant/conversations", None, "assistant.use"),
)


def _izinli(rol: str, izin_adi: str) -> bool:
    if izin_adi == "audit.verify":  # okuma + doğrulama
        return yetki.izinli(rol, "audit.verify")
    return any(yetki.izinli(rol, i) for i in izin_adi.split("|"))


@pytest.mark.parametrize("rol", sorted(yetki.ROLLER))
def test_rol_matrisi(rol: str, client: TestClient, make_user: MakeUser, engine: Engine) -> None:
    u = make_user(rol)
    _giris(client, u)
    # Aynı (izin, yol) reddi 60 sn içinde bir kez yazılır (sorgu dizgesi yola girmez).
    redler: set[tuple[str, str]] = set()
    for yontem, yol, govde, izin_adi in MATRIS:
        r = client.request(yontem, yol, json=govde)
        if _izinli(rol, izin_adi):
            assert r.status_code != 403, (rol, yontem, yol, r.text)
        else:
            assert r.status_code == 403, (rol, yontem, yol, r.status_code, r.text)
            assert r.json()["kod"] == "yetki_yok", r.text
            son = _redler(engine, u.kullanici_adi)[-1]
            beklenen = izin_adi
            if izin_adi == "audit.verify" and not _izinli(rol, "audit.read_all|audit.read_own"):
                beklenen = "audit.read_all|audit.read_own"  # okuma kapısı önce
            assert son["izin"] == beklenen and son["rol"] == rol, (yol, son)
            redler.add((beklenen, yol.split("?", 1)[0]))
    assert len(_redler(engine, u.kullanici_adi)) == len(redler)


@pytest.mark.parametrize("rol", ["auditor", "viewer"])
def test_canli_olaylar_auditor_ve_viewer_kapali(
    rol: str, client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    u = make_user(rol)
    _giris(client, u)
    r = client.get("/events")
    assert r.status_code == 403 and r.json()["kod"] == "yetki_yok"
    assert _redler(engine, u.kullanici_adi)[-1]["izin"] == "events.read"


def test_me_izinler_ve_rol_etiketi(client: TestClient, make_user: MakeUser) -> None:
    for rol in ("tester", "viewer"):
        _giris(client, make_user(rol))
        me = client.get("/auth/me").json()
        assert me["izinler"] == yetki.rol_izinleri(rol)
        assert me["rol_etiketi"] == yetki.ROL_ETIKETLERI[rol]
    assert "case.publish" not in me["izinler"] and "run.read" in me["izinler"]


# ------------------------------------------------------------------ okuma süzgeçleri


def test_denetim_kapsami_kendi_olaylari(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    from tp_core.audit import append_audit

    analist, denetci = make_user("analyst"), make_user("auditor")
    with engine.begin() as c:
        append_audit(c, analist.kullanici_adi, "deneme.kendi", None, {})
        append_audit(c, "baskasi", "deneme.baska", None, {})
    _giris(client, analist)
    aktorler = {e["aktor"] for e in client.get("/audit").json()["events"]}
    assert aktorler == {analist.kullanici_adi}
    _giris(client, denetci)
    r = client.get("/audit?verify=true")
    assert r.status_code == 200 and r.json()["verify"]["ok"] is True
    assert {"baskasi", analist.kullanici_adi} <= {e["aktor"] for e in r.json()["events"]}


def test_denetci_gorunumunde_ozet_maskelidir(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    from tp_core.audit import append_audit

    with engine.begin() as c:
        append_audit(c, "biri", "deneme.pii", None, {"not": "iletisim ayse.yilmaz@ornek.com"})
    _giris(client, make_user("auditor"))
    ozet = next(e for e in client.get("/audit").json()["events"] if e["eylem"] == "deneme.pii")
    assert "ayse.yilmaz@ornek.com" not in str(ozet) and "<<PII_EMAIL_1>>" in ozet["ozet"]["not"]
    _giris(client, make_user("admin"))
    ozet = next(e for e in client.get("/audit").json()["events"] if e["eylem"] == "deneme.pii")
    assert ozet["ozet"]["not"] == "iletisim ayse.yilmaz@ornek.com"


def _kosu(engine: Engine) -> str:
    with engine.begin() as c:
        return str(
            c.execute(
                text(
                    "INSERT INTO run (kaynak, tetik, sonuc, artefaktlar) VALUES "
                    "('local', 'deploy', 'passed', CAST(:a AS jsonb)) RETURNING id"
                ),
                {"a": '{"dizin": "runs/r1", "html": "html", "junit": "junit.xml", "log": "x.log"}'},
            ).scalar_one()
        )


@pytest.mark.parametrize("rol", ["auditor", "viewer"])
def test_kosu_maskeli_gorunum_imzali_baglanti_vermez(
    rol: str, client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    run_id = _kosu(engine)
    _giris(client, make_user("engineer"))
    acik = client.get(f"/runs/{run_id}").json()
    assert acik["rapor_url"] and "/artifacts/k/" in acik["rapor_url"] and acik["junit_url"]
    _giris(client, make_user(rol))
    for govde in (client.get(f"/runs/{run_id}").json(), client.get("/runs").json()[0]):
        assert govde["maskeli"] is True
        for alan in ("rapor_url", "junit_url", "log_url", "allure_url"):
            assert govde[alan] is None, alan
        assert "/artifacts/" not in str(govde)


def test_kosu_maskesi_ic_ice_url_ve_ham_ciktiyi_atar() -> None:
    from tp_core.features.ci.service import maskele_kosu

    kosu = {
        "rapor_url": "/api/artifacts/k/imza/runs/x/html/index.html",
        "ci_url": "https://github.com/o/r/actions/runs/1",
        "artefakt_kok": "/api/artifacts/runs/x/",
        "sauce": {"url": "https://saucelabs.com/x", "urls": ["https://saucelabs.com/y"]},
        "github": {"isler": [{"ad": "e2e", "url": "https://github.com/o/r/runs/2"}]},
        "sonuclar": [
            {
                "ekler": [{"yol": "a.png", "url": "/api/artifacts/runs/x/a.png"}],
                "denemeler": [{"durum": "failed", "stdout": "sır", "stderr": "iz"}],
            }
        ],
        "ozet": {"gecen": 1},
    }
    m = maskele_kosu(kosu)
    assert m["maskeli"] is True and m["ozet"] == {"gecen": 1}
    assert m["rapor_url"] is m["ci_url"] is m["artefakt_kok"] is None
    assert m["sauce"] == {"url": None, "urls": None}
    assert m["github"]["isler"] == [{"ad": "e2e", "url": None}]
    assert m["sonuclar"][0]["ekler"] == []
    assert m["sonuclar"][0]["denemeler"] == [{"durum": "failed"}]
    assert "http" not in str(m) and "/api/artifacts" not in str(m)


def _zengin_kosu(engine: Engine) -> str:
    """Bağlantılı (imzalı rapor, CI, Sauce, GitHub işi) ve ham çıktılı bir CI koşusu."""
    import json

    a = {
        "dizin": "runs/r1", "html": "html", "junit": "junit.xml", "log": "x.log",
        "ci_url": "https://github.com/o/r/actions/runs/1",
        "sauce": {"url": "https://saucelabs.com/x", "durum": "passed"},
        "github": {"isler": [{"ad": "e2e", "url": "https://github.com/o/r/runs/2"}]},
    }  # fmt: skip
    with engine.begin() as c:
        rid = c.execute(
            text(
                "INSERT INTO run (kaynak, tetik, sonuc, artefaktlar) VALUES "
                "('github', 'deploy', 'failed', CAST(:a AS jsonb)) RETURNING id"
            ),
            {"a": json.dumps(a)},
        ).scalar_one()
        tr = c.execute(
            text(
                "INSERT INTO test_result (run_id, tetik, test_adi, dosya, sonuc) "
                "VALUES (:r, 'deploy', 't', 'a.spec.ts', 'failed') RETURNING id"
            ),
            {"r": rid},
        ).scalar_one()
        c.execute(
            text(
                "INSERT INTO test_result_ek (test_result_id, ekler, denemeler) VALUES "
                "(:t, CAST(:e AS jsonb), CAST(:d AS jsonb))"
            ),
            {
                "t": tr,
                "e": json.dumps([{"yol": "a.png", "ad": "ekran"}]),
                "d": json.dumps([{"durum": "failed", "stdout": "SIR-CIKTI", "stderr": "IZ"}]),
            },
        )
    return str(rid)


@pytest.mark.parametrize("rol", ["auditor", "viewer"])
def test_maskeli_rol_hicbir_uctan_baglanti_almaz(
    rol: str, client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    run_id = _zengin_kosu(engine)
    _giris(client, make_user("engineer"))
    acik = client.get(f"/runs/{run_id}").json()
    assert "SIR-CIKTI" in str(acik) and "/artifacts/k/" in str(acik)
    ct = client.get("/control-tower").json()["son_kosular"]
    assert any(k["rapor_url"] for k in ct)
    _giris(client, make_user(rol))
    govdeler = [
        client.get(f"/runs/{run_id}").json(),
        client.get("/runs").json(),
        client.get("/control-tower").json()["son_kosular"],
    ]
    for govde in govdeler:
        metin = str(govde)
        for yasak in ("/artifacts/", "http", "SIR-CIKTI", "IZ'"):
            assert yasak not in metin, (yasak, metin[:300])
    assert all(k["maskeli"] is True for k in govdeler[2])


def test_red_kaydi_tekrar_ve_eszamanlilik_sinirli(engine: Engine, make_user: MakeUser) -> None:
    u = make_user("viewer")
    for _ in range(5):
        yetki.denetle_red(engine, u, "case.read", "rol", "/cases\x00\n" + "x" * 500)
    yetki.denetle_red(engine, u, "case.read", "rol", "/baska")
    with engine.connect() as c:
        nesneler = (
            c.execute(
                text("SELECT nesne FROM audit_event WHERE eylem = 'authz.denied' AND aktor = :a"),
                {"a": u.kullanici_adi},
            )
            .scalars()
            .all()
        )
    assert len(nesneler) == 2  # aynı red 60 sn içinde bir kez
    uzun = next(n for n in nesneler if n != "/baska")
    assert len(uzun) == yetki.NESNE_UST and "\x00" not in uzun and "\n" not in uzun
    # Eşzamanlı yazım sınırı doluysa beklenmez, kayıt atlanır.
    tutulan = [yetki._red_yazici.acquire(blocking=False) for _ in range(yetki.RED_ESZAMANLI)]
    try:
        assert all(tutulan)
        yetki.denetle_red(engine, u, "bug.read", "rol", "/bug-drafts")
    finally:
        for _ in tutulan:
            yetki._red_yazici.release()
    yetki.denetle_red(engine, u, "bug.read", "rol", "/bug-drafts")  # sınır boşaldı: yazılır
    with engine.connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM audit_event WHERE eylem = 'authz.denied' AND aktor = :a "
                    "AND nesne = '/bug-drafts'"
                ),
                {"a": u.kullanici_adi},
            ).scalar_one()
            == 1
        )


def _bug(engine: Engine, durum: str) -> str:
    with engine.begin() as c:
        return str(
            c.execute(
                text(
                    "INSERT INTO bug_draft (icerik, icerik_hash, durum) "
                    "VALUES (CAST(:i AS jsonb), 'h', :d) RETURNING id"
                ),
                {"i": '{"ozet": "x"}', "d": durum},
            ).scalar_one()
        )


def test_developer_yalniz_yayinlanmis_bugu_gorur(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    taslak, yayinda = _bug(engine, "draft"), _bug(engine, "published")
    _giris(client, make_user("developer"))
    assert [b["id"] for b in client.get("/bug-drafts").json()] == [yayinda]
    assert client.get(f"/bug-drafts/{taslak}").status_code == 404
    assert client.get(f"/bug-drafts/{taslak}/detail").status_code == 404
    assert client.get(f"/bug-drafts/{yayinda}").status_code == 200
    _giris(client, make_user("tester"))
    assert {b["id"] for b in client.get("/bug-drafts").json()} == {taslak, yayinda}


def test_developer_hata_detayinda_yayinlanmamis_bug_gormez(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    with engine.begin() as c:
        rid = c.execute(
            text("INSERT INTO run (kaynak, tetik, sonuc) VALUES ('local','deploy','failed') "
                 "RETURNING id")
        ).scalar_one()  # fmt: skip
        fid = c.execute(
            text(
                "INSERT INTO failure (run_id, test_adi, hata_imzasi, sinif, oneri_turu) "
                "VALUES (:r, 't', 'imza', 'product_defect', 'bug_draft') RETURNING id"
            ),
            {"r": rid},
        ).scalar_one()
        bid = c.execute(
            text(
                "INSERT INTO bug_draft (icerik, icerik_hash, durum, failure_id) "
                "VALUES (CAST(:i AS jsonb), 'h', 'draft', :f) RETURNING id"
            ),
            {"i": '{"ozet": "x"}', "f": fid},
        ).scalar_one()
    _giris(client, make_user("tester"))
    acik = client.get(f"/failures/{fid}").json()
    assert acik["bug_draft_id"] == str(bid) and acik["oneri"]["taslak_durumu"] == "draft"
    _giris(client, make_user("developer"))
    for govde in (client.get(f"/failures/{fid}").json(), client.get("/failures").json()[0]):
        assert govde["bug_draft_id"] is None and govde["oneri"] is None
        assert str(bid) not in str(govde)
    with engine.begin() as c:
        c.execute(text("UPDATE bug_draft SET durum = 'published' WHERE id = :b"), {"b": bid})
    assert client.get(f"/failures/{fid}").json()["bug_draft_id"] == str(bid)


# ------------------------------------------------------------------ PO onayı (K6)


def _gereksinim(engine: Engine, kaynak: str) -> str:
    with engine.begin() as c:
        return str(
            c.execute(
                text(
                    "INSERT INTO requirement (kaynak, jira_key, baslik, kaynak_hash, durum) "
                    "VALUES (:k, :j, 'b', 'h', 'pending_po') RETURNING id"
                ),
                {"k": kaynak, "j": "TPD-99" if kaynak == "jira" else None},
            ).scalar_one()
        )


def test_po_portal_onayi_jira_gereksiniminde_410(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    rid = _gereksinim(engine, "jira")
    _giris(client, make_user("po"))
    r = client.post(f"/requirements/{rid}/po-approve", json={"icerik_hash": "h"})
    assert r.status_code == 410 and r.json()["kod"] == "po_onayi_jira", r.text
    _giris(client, make_user("analyst"))
    assert client.post(f"/requirements/{rid}/po-approve", json={}).status_code == 403


def test_po_portal_onayi_serbest_metinde_calisir(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    rid = _gereksinim(engine, "free_text")
    po = make_user("po")
    _giris(client, po)
    d = client.get(f"/requirements/{rid}").json()
    assert client.post(f"/requirements/{rid}/po-approve", json={}).status_code == 422
    r = client.post(f"/requirements/{rid}/po-approve", json={"icerik_hash": "x" * 64})
    assert r.status_code == 409, r.text
    r = client.post(f"/requirements/{rid}/po-approve", json={"icerik_hash": d["icerik_hash"]})
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "po_approved" and r.json()["po"]["kanal"] == "portal"


def test_po_portal_reddi_serbest_metinde_analiste_doner(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    jira_rid = _gereksinim(engine, "jira")
    rid = _gereksinim(engine, "free_text")
    po = make_user("po")
    _giris(client, make_user("analyst"))
    r = client.post(f"/requirements/{rid}/po-reject", json={"gerekce": "x"})
    assert r.status_code == 403 and r.json()["kod"] == "yetki_yok"
    _giris(client, po)
    r = client.post(f"/requirements/{jira_rid}/po-reject", json={"gerekce": "x"})
    assert r.status_code == 410 and r.json()["kod"] == "po_onayi_jira", r.text
    d = client.get(f"/requirements/{rid}").json()
    for govde in ({}, {"gerekce": ""}, {"gerekce": "   ", "icerik_hash": d["icerik_hash"]},
                  {"gerekce": "x" * 2001}):  # fmt: skip
        assert client.post(f"/requirements/{rid}/po-reject", json=govde).status_code == 422
    r = client.post(f"/requirements/{rid}/po-reject", json={"gerekce": "x", "icerik_hash": "e"})
    assert r.status_code == 409, r.text
    r = client.post(
        f"/requirements/{rid}/po-reject",
        json={"gerekce": "AC2 ölçülebilir değil", "icerik_hash": d["icerik_hash"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "new"
    with engine.connect() as c:
        rv = c.execute(
            text("SELECT karar, gerekce, user_id FROM review WHERE nesne_id = :i"), {"i": rid}
        ).one()
        assert (rv.karar, rv.gerekce, rv.user_id) == ("po_reject", "AC2 ölçülebilir değil", po.id)
        eylemler = set(
            c.execute(
                text("SELECT eylem FROM audit_event WHERE nesne = :n"), {"n": f"requirement:{rid}"}
            ).scalars()
        )
        assert {"review.po_reject", "requirement.transition"} <= eylemler
    # Artık PO teyidi beklemiyor: ikinci ret / onay 409.
    r = client.post(
        f"/requirements/{rid}/po-reject", json={"gerekce": "x", "icerik_hash": d["icerik_hash"]}
    )
    assert r.status_code == 409


# ------------------------------------------------------------------ ortam, demo, CI tetik


def test_prod_ve_demo_kipi_birlikte_baslamaz(monkeypatch: pytest.MonkeyPatch, db: Db) -> None:
    baslangic_denetimi(Settings(TP_DATABASE_URL="postgresql://x/y"))  # varsayılan: dev, kapalı
    with pytest.raises(RuntimeError, match="TP_ORTAM=prod"):
        baslangic_denetimi(
            Settings(TP_DATABASE_URL="postgresql://x/y", TP_ORTAM="prod", TP_DEMO_MODE=True)
        )
    monkeypatch.setenv("TP_ORTAM", "prod")
    monkeypatch.setenv("TP_DEMO_MODE", "1")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError), TestClient(main.create_app()):
        pass
    monkeypatch.setenv("TP_DEMO_MODE", "0")
    get_settings.cache_clear()
    with TestClient(main.create_app()) as c:
        assert c.get("/health").status_code in (200, 503)


def test_worker_prod_ve_demo_kipinde_baslamaz(monkeypatch: pytest.MonkeyPatch, db: Db) -> None:
    from tp_core import worker

    monkeypatch.setenv("TP_ORTAM", "prod")
    monkeypatch.setenv("TP_DEMO_MODE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(worker, "discover", lambda: pytest.fail("denetimden önce başladı"))
    with pytest.raises(RuntimeError, match="TP_DEMO_MODE"):
        worker.main()


@pytest.mark.parametrize("ortam", ["prod", "staging"])
def test_developer_manuel_tetik_uretimde_403(
    ortam: str,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    make_user: MakeUser,
    engine: Engine,
) -> None:
    from tp_core.features.ci import service

    cagri: list[tuple[str, str]] = []
    monkeypatch.setattr(
        service,
        "trigger_manual",
        lambda _s, tetik, isteyen: cagri.append((tetik, isteyen))
        or {"job_id": None, "run_id": None, "durum": "queued", "mesaj": "", "kaynak": "local",
            "tetik": tetik},
    )  # fmt: skip
    monkeypatch.setenv("TP_ORTAM", ortam)
    get_settings.cache_clear()
    dev = make_user("developer")
    _giris(client, dev)
    r = client.post("/ci/trigger", json={"tetik": "manual"})
    if ortam == "prod":
        assert r.status_code == 403 and r.json()["kod"] == "yetki_yok"
        son = _redler(engine, dev.kullanici_adi)[-1]
        assert son == {**son, "izin": "run.trigger_manual", "neden": "prod_ortam"}
        assert cagri == []
    else:
        assert r.status_code == 202, r.text
        assert cagri == [("manual", dev.kullanici_adi)]
    # Developer zamanlanmış tetik (deploy/nightly) başlatamaz; engineer üretimde de başlatır.
    assert client.post("/ci/trigger", json={"tetik": "deploy"}).status_code == 403
    _giris(client, make_user("engineer"))
    assert client.post("/ci/trigger", json={"tetik": "manual"}).status_code == 202
    assert client.post("/ci/trigger", json={"tetik": "nightly"}).status_code == 202


@pytest.mark.parametrize("rol", ["admin", "engineer"])
def test_demo_kontrolleri_demo_kipi_kapaliyken_403(
    rol: str,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    make_user: MakeUser,
    engine: Engine,
) -> None:
    monkeypatch.setenv("TP_DEMO_MODE", "0")
    get_settings.cache_clear()
    u = make_user(rol)
    _giris(client, u)
    for yol in ("/demo/reset", "/demo/break-locator"):
        r = client.post(yol)
        assert r.status_code == 403 and r.json()["kod"] == "demo_kapali", r.text
        assert "Demo kipi kapalı (TP_DEMO_MODE=0)" in r.text
        assert _redler(engine, u.kullanici_adi)[-1]["neden"] == "demo_kapali"
    durum = client.get("/demo/status")
    if durum.status_code == 200:  # forge erişilemezse durum ucu bu testin konusu değil
        assert durum.json()["demo_modu"] is False and durum.json()["ortam"] == "dev"
    _giris(client, make_user("tester"))
    r = client.post("/demo/reset")
    assert r.status_code == 403 and r.json()["kod"] == "yetki_yok"


def test_demo_isleri_ve_cli_demo_kipi_kapaliyken_calismaz(
    monkeypatch: pytest.MonkeyPatch, db: Db, engine: Engine
) -> None:
    from tp_core.features.demo import __main__ as cli
    from tp_core.features.demo import service as demo
    from tp_core.workflow.jobs import JobContext, PermanentJobError

    monkeypatch.setenv("TP_DEMO_MODE", "0")
    get_settings.cache_clear()
    ctx = JobContext(job_id=uuid.uuid4(), tur="demo.break", yuk={"isteyen": "x"}, deneme=1,
                     max_deneme=1)  # fmt: skip
    for fn in (demo.run_break, demo.run_reset):
        with pytest.raises(PermanentJobError, match="Demo kipi kapalı"):
            fn(ctx, engine)
    assert cli.main(["on-kosul", "--isteyen", "t"]) == cli.RED_KODU
    assert cli.main(["web-istek", "--eylem", "break"]) == cli.RED_KODU


# ------------------------------------------------------------------ AI Probe rol eşlemesi


def test_presenter_admin_sayilir_ve_mfa_ister() -> None:
    from tp_core.auth import aiprobe
    from tp_core.auth.display import display_name

    assert {"admin", "po"} == aiprobe.ADMIN_ROLLERI
    assert aiprobe.tp_rolleri(["presenter", "analyst"], "2") == ("admin", "analyst")
    assert aiprobe.tp_rolleri(["presenter", "admin", "po", "viewer"], "1") == ("viewer",)
    assert aiprobe.tp_rolleri(["presenter", "admin"], "2") == ("admin",)  # tekrarsız
    assert aiprobe.tp_rolleri(["auditor", "developer", "bilinmeyen"], None) == (
        "auditor",
        "developer",
    )
    assert display_name("eski", "presenter", {}) == "eski · Sistem Yöneticisi"


# ------------------------------------------------------------------ 0024 göçü (rol modeli)


def test_0024_rol_presenter_admin_olur_ve_geri_alinir(pg: PgServer) -> None:
    ad = pg.create_empty_db()
    owner = pg.url("tp_owner", ad)
    try:
        run_alembic(owner, "0023")
        with psycopg.connect(owner.replace("+psycopg", ""), autocommit=True) as c:
            c.execute(
                "INSERT INTO app_user (id, kullanici_adi, rol, parola_hash) VALUES "
                "(gen_random_uuid(), 'sunucu', 'presenter', 'x'), "
                "(gen_random_uuid(), 'analist', 'analyst', 'x')"
            )
        run_alembic(owner, "0024")
        with psycopg.connect(owner.replace("+psycopg", ""), autocommit=True) as c:
            roller = dict(c.execute("SELECT kullanici_adi, rol FROM app_user").fetchall())
            assert roller == {"sunucu": "admin", "analist": "analyst"}
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute(
                    "INSERT INTO app_user (id, kullanici_adi, rol, parola_hash) "
                    "VALUES (gen_random_uuid(), 'y', 'presenter', 'x')"
                )
            c.execute(
                "INSERT INTO app_user (id, kullanici_adi, rol, parola_hash) "
                "VALUES (gen_random_uuid(), 'izleyici', 'viewer', 'x')"
            )
        with pytest.raises(RuntimeError, match="izleyici"):
            run_alembic(owner, "0023", "downgrade")
        with psycopg.connect(owner.replace("+psycopg", ""), autocommit=True) as c:
            c.execute("DELETE FROM app_user WHERE kullanici_adi = 'izleyici'")
        run_alembic(owner, "0023", "downgrade")
        with psycopg.connect(owner.replace("+psycopg", ""), autocommit=True) as c:
            assert c.execute(
                "SELECT rol FROM app_user WHERE kullanici_adi = 'sunucu'"
            ).fetchone() == ("presenter",)
        run_alembic(owner, "head")
    finally:
        with pg.super_conn() as c:
            c.execute(f'DROP DATABASE IF EXISTS "{ad}" WITH (FORCE)')


def test_0026_eski_analist_editi_isaretlenir_ve_po_reject(pg: PgServer) -> None:
    ad = pg.create_empty_db()
    owner = pg.url("tp_owner", ad)
    dsn = owner.replace("+psycopg", "")
    try:
        run_alembic(owner, "0025")
        with psycopg.connect(dsn, autocommit=True) as c:
            analist, testci = (
                c.execute(
                    "INSERT INTO app_user (id, kullanici_adi, rol, parola_hash) VALUES "
                    "(gen_random_uuid(), %s, %s, 'x') RETURNING id",
                    (ad_, rol),
                ).fetchone()[0]
                for ad_, rol in (("analist", "analyst"), ("testci", "tester"))
            )
            for kullanici, karar in ((analist, "edit"), (testci, "edit"), (analist, "approve")):
                c.execute(
                    "INSERT INTO review (id, nesne_turu, nesne_id, user_id, karar, "
                    "onaylanan_hash) VALUES (gen_random_uuid(), 'test_case', gen_random_uuid(), "
                    "%s, %s, 'h')",
                    (kullanici, karar),
                )
        run_alembic(owner, "0026")
        with psycopg.connect(dsn, autocommit=True) as c:
            satirlar = c.execute(
                "SELECT u.kullanici_adi, r.karar, r.eski_onay FROM review r "
                "JOIN app_user u ON u.id = r.user_id ORDER BY r.sira"
            ).fetchall()
            assert satirlar == [
                ("analist", "edit", True),
                ("testci", "edit", False),
                ("analist", "approve", False),
            ]
            c.execute(
                "INSERT INTO review (id, nesne_turu, nesne_id, user_id, karar, onaylanan_hash, "
                "gerekce) VALUES (gen_random_uuid(), 'requirement', gen_random_uuid(), %s, "
                "'po_reject', 'h', 'x')",
                (analist,),
            )
            # Append-only tetikleyicisi göçten sonra yine açık.
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
                c.execute("UPDATE review SET eski_onay = false")
        run_alembic(owner, "0025", "downgrade")
        run_alembic(owner, "head")
    finally:
        with pg.super_conn() as c:
            c.execute(f'DROP DATABASE IF EXISTS "{ad}" WITH (FORCE)')
