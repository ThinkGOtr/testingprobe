"""Öneri uçları (AI-ASISTAN-PLANI §9, §13 "API" ve "Güvenlik"): `GET /assistant/suggestions`,
`POST /assistant/suggestions/{kural_id}/feedback` — 5 rol, 404/422/429, `kod` alanı, bayrak,
yan etkisizlik.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.unit.conftest import PAROLA, Db
from tp_core.api import main
from tp_core.auth.login import THROTTLE
from tp_core.config import get_settings
from tp_core.features.assistant import hiz, oneri, oneri_api
from tp_core.workflow.service import Principal

from .oneri_tohum import Tohum

ROLLER = oneri.ROLLER
MakeUser = Callable[..., Principal]
UC = "/assistant/suggestions"


@pytest.fixture(autouse=True)
def _ortam(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TP_DAILY_BUDGET_USD", "10")
    monkeypatch.delenv("TP_ASISTAN_ONERI", raising=False)
    get_settings.cache_clear()
    oneri.ONBELLEK.temizle()
    THROTTLE._kayit.clear()
    yield
    THROTTLE._kayit.clear()
    oneri.ONBELLEK.temizle()
    get_settings.cache_clear()


@pytest.fixture
def client(db: Db) -> Iterator[TestClient]:
    app = main.create_app()
    # Router `features/assistant/api.py`'de bağlanır; o dosya henüz bağlamadıysa test bağlar.
    if not any(getattr(r, "path", "") == UC for r in app.routes):
        app.include_router(oneri_api.router)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def tohum(engine: Engine) -> Tohum:
    return Tohum(engine)


def _giris(client: TestClient, kisi: Principal) -> None:
    client.cookies.clear()
    r = client.post("/auth/login", json={"kullanici_adi": kisi.kullanici_adi, "parola": PAROLA})
    assert r.status_code == 200, r.text


def _sayi(engine: Engine, tablo: str) -> int:
    with engine.connect() as c:
        return int(c.execute(text(f"SELECT count(*) FROM {tablo}")).scalar_one())


@pytest.mark.parametrize("rol", ROLLER)
def test_oneriler_rol_oturumdan(
    rol: str, client: TestClient, engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    req = tohum.gereksinim("findings_open")
    tohum.bulgu(req)
    _giris(client, make_user(rol))
    r = client.get(UC, params={"rota": f"/gereksinimler/{req}", "rol": "analyst"})
    assert r.status_code == 200, r.text
    govde = r.json()
    assert govde["rota_kalibi"] == "/gereksinimler/:id"
    assert set(govde) >= {
        "oneriler",
        "hesaplandi",
        "ekranda_kural_var",
        "bastirilan",
        "diger_ekranlar",
    }
    ids = [c["kural_id"] for c in govde["oneriler"]]
    if rol == "analyst":
        assert ids == ["gereksinim-bulgu-karari"]
        kart = govde["oneriler"][0]
        assert set(kart) >= {"kural_id", "baslik", "neden", "oncelik", "eylem"}
        assert kart["eylem"] == {"tur": "rota", "rota": f"/gereksinimler/{req}", "capa": "bulgular"}
    else:
        assert ids == []  # istemcinin "rol" parametresi yok sayılır
    assert govde["ekranda_kural_var"] is oneri.ekranda_kural_var("/gereksinimler/:id", rol)


def test_varlik_ve_ekran_404(client: TestClient, tohum: Tohum, make_user: MakeUser) -> None:
    _giris(client, make_user("analyst"))
    for params in (
        {"rota": f"/gereksinimler/{uuid.uuid4()}"},  # varlık yok
        {"rota": "/gereksinimler/:id", "varlik_tur": "requirement", "varlik_id": "TPD-1"},
        {"rota": "/gereksinimler/:id"},  # kimlik yok
        {"rota": f"/gereksinimler/{tohum.script()}"},  # başka türde varlık
        {"rota": "/demo"},  # Analist açamaz
        {"rota": "/ayarlar"},  # rotalar.json dışı
    ):
        r = client.get(UC, params=params)
        assert r.status_code == 404, (params, r.text)
        assert r.json()["kod"] == "bulunamadi"
    assert client.get(UC).status_code == 422  # rota zorunlu


def test_cerezsiz_ve_bearer_401(client: TestClient) -> None:
    sahte = "tpt_" + "x" * 40
    r = client.get(UC, params={"rota": "/"}, headers={"Authorization": f"Bearer {sahte}"})
    assert r.status_code == 401 and r.json()["kod"] == "yetkisiz"
    r = client.post(f"{UC}/gereksinim-basarisiz/feedback", json={"deger": -1})
    assert r.status_code == 401


def test_jira_taslak_karti_ve_ai_call_yazilmaz(
    client: TestClient, engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    rid = tohum.kosu("error")
    _giris(client, make_user("engineer"))
    once = _sayi(engine, "ai_call"), _sayi(engine, "tool_call"), _sayi(engine, "job")
    r = client.get(UC, params={"rota": f"/kosular/{rid}"})
    assert r.status_code == 200, r.text
    (kart,) = r.json()["oneriler"]
    e = kart["eylem"]
    assert e["tur"] == "jira_taslak" and e["taslak"]["tur"] == "Task"
    assert e["taslak"]["proje"] == "TPD"
    assert "baglanti" not in e and e["baglanti_yok_nedeni"]  # simülatör: yeni kayıt sayfası yok
    assert "http" not in str(e["taslak"])
    assert (_sayi(engine, "ai_call"), _sayi(engine, "tool_call"), _sayi(engine, "job")) == once


def test_geri_bildirim_gizle_ve_yaptim(
    client: TestClient, engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    testci, diger = make_user("tester"), make_user("tester")
    bid = tohum.bug_taslagi("draft")
    params = {"rota": f"/bug-taslaklari/{bid}"}
    _giris(client, testci)
    assert [c["kural_id"] for c in client.get(UC, params=params).json()["oneriler"]] == [
        "bug-taslagi-karari"
    ]
    r = client.post(
        f"{UC}/bug-taslagi-karari/feedback",
        json={"deger": -1, "varlik_id": str(bid), "varlik_durum": "uydurma"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["varlik_durum"] == "draft"  # istemcinin değeri yok sayıldı
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT varlik_durum FROM asistan_oneri_geri_bildirim")).scalar_one()
            == "draft"
        )
    # Önbellek geri bildirimde temizlenir: gizleme hemen görünür.
    assert client.get(UC, params=params).json()["oneriler"] == []

    _giris(client, diger)
    assert len(client.get(UC, params=params).json()["oneriler"]) == 1
    r = client.post(
        f"{UC}/bug-taslagi-karari/feedback",
        json={"deger": 2, "varlik_id": str(bid), "jira_anahtari": "TPD-12"},
    )
    assert r.status_code == 200 and r.json()["jira_anahtari"] == "TPD-12"
    _giris(client, make_user("tester"))
    govde = client.get(UC, params=params).json()
    assert govde["oneriler"] == []
    assert govde["bastirilan"][0]["jira_anahtari"] == "TPD-12"
    assert govde["bastirilan"][0]["kisi"] == diger.kullanici_adi


@pytest.mark.parametrize(
    ("kural", "govde", "durum"),
    [
        ("yok-boyle", {"deger": -1}, 422),
        ("bug-taslagi-karari", {"deger": 0}, 422),
        ("bug-taslagi-karari", {"deger": 2, "jira_anahtari": "tpd-1"}, 422),
        ("bug-taslagi-karari", {"deger": 2, "jira_anahtari": "TPD-1?expand=x"}, 422),
        ("bug-taslagi-karari", {"deger": 1, "jira_anahtari": "TPD-1"}, 422),
        ("bug-taslagi-karari", {"deger": -1}, 422),  # varlık kimliği zorunlu
        ("bug-taslagi-karari", {"deger": -1, "varlik_id": "YOK"}, 404),
        ("gereksinim-basarisiz", {"deger": -1, "varlik_id": "VAR"}, 404),  # rol dışı kural
    ],
)
def test_geri_bildirim_hatalari(
    kural: str,
    govde: dict[str, Any],
    durum: int,
    client: TestClient,
    engine: Engine,
    tohum: Tohum,
    make_user: MakeUser,
) -> None:
    bid = tohum.bug_taslagi("draft")
    if govde.get("varlik_id") == "YOK":
        govde = {**govde, "varlik_id": str(uuid.uuid4())}
    elif govde.get("varlik_id") == "VAR":
        govde = {**govde, "varlik_id": str(tohum.gereksinim("failed"))}
    elif "varlik_id" not in govde and govde.get("deger") != -1:
        govde = {**govde, "varlik_id": str(bid)}
    _giris(client, make_user("tester"))
    r = client.post(f"{UC}/{kural}/feedback", json=govde)
    assert r.status_code == durum, r.text
    assert r.json()["kod"] == ("gecersiz_istek" if durum == 422 else "bulunamadi")
    assert "Traceback" not in r.text and "Error" not in r.json()["detail"]
    assert _sayi(engine, "asistan_oneri_geri_bildirim") == 0


def test_hiz_siniri_liste_60_geri_bildirim_30(
    client: TestClient,
    tohum: Tohum,
    make_user: MakeUser,
    sabit_hiz_penceresi: int,
) -> None:
    _giris(client, make_user("presenter"))
    for i in range(60):
        r = client.get(UC, params={"rota": "/kosular"})
        assert r.status_code == 200, (i, r.text)
    r = client.get(UC, params={"rota": "/kosular"})
    assert r.status_code == 429 and r.json()["kod"] == "hiz_siniri"
    tohum.harcama("9")
    for i in range(30):
        r = client.post(f"{UC}/butce-uyarisi/feedback", json={"deger": 1})
        assert r.status_code == 200, (i, r.text)
    r = client.post(f"{UC}/butce-uyarisi/feedback", json={"deger": 1})
    assert r.status_code == 429 and r.json()["kod"] == "hiz_siniri"


def test_sunucu_onbellegi_kullanici_ve_varlik_bazinda(
    client: TestClient, engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    from sqlalchemy.orm import Session

    from tp_core.models import Requirement
    from tp_core.models.guard import allow_state_write

    req = tohum.gereksinim("failed")
    params = {"rota": f"/gereksinimler/{req}"}
    _giris(client, make_user("analyst"))
    ilk = client.get(UC, params=params).json()
    assert [c["kural_id"] for c in ilk["oneriler"]] == ["gereksinim-basarisiz"]
    with allow_state_write(), Session(engine) as s, s.begin():
        s.get(Requirement, req).durum = "in_review"  # type: ignore[union-attr]
    # Önbellek süresi içinde aynı (kullanıcı, rota, varlık) önbellekten döner.
    assert client.get(UC, params=params).json() == ilk
    # Başka kullanıcı kendi hesabını alır.
    _giris(client, make_user("analyst"))
    assert client.get(UC, params=params).json()["oneriler"] == []


def test_bayrak_kapaliyken_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, make_user: MakeUser
) -> None:
    _giris(client, make_user("presenter"))
    monkeypatch.setenv("TP_ASISTAN_ONERI", "0")
    r = client.get(UC, params={"rota": "/kosular"})
    assert r.status_code == 404 and r.json()["kod"] == "bulunamadi"
    r = client.post(f"{UC}/butce-uyarisi/feedback", json={"deger": 1})
    assert r.status_code == 404


def test_model_kapaliyken_ve_worker_yokken_calisir(
    client: TestClient, engine: Engine, tohum: Tohum, make_user: MakeUser
) -> None:
    """Asistan durumu (`asistan_durum`) hiç yazılmamışken de öneri ucu çalışır."""
    assert _sayi(engine, "asistan_durum") == 0
    fid = tohum.hata("test_maintenance")
    _giris(client, make_user("engineer"))
    r = client.get(UC, params={"rota": f"/hatalar/{fid}"})
    assert r.status_code == 200
    assert [c["kural_id"] for c in r.json()["oneriler"]] == ["hata-bakim-onarim"]


def test_hiz_sayaci_404_ile_biten_istekte_de_artar(
    client: TestClient,
    tohum: Tohum,
    make_user: MakeUser,
    sabit_hiz_penceresi: int,
) -> None:
    """Sayaç ayrı bağlantıda commit edilir: geçersiz varlık/kural istekleri de sınıra takılır."""
    _giris(client, make_user("analyst"))
    for i in range(60):
        r = client.get(UC, params={"rota": f"/gereksinimler/{uuid.uuid4()}"})
        assert r.status_code == 404, (i, r.text)
    r = client.get(UC, params={"rota": f"/gereksinimler/{uuid.uuid4()}"})
    assert r.status_code == 429 and r.json()["kod"] == "hiz_siniri"
    for i in range(30):
        r = client.post(f"{UC}/olmayan-kural/feedback", json={"deger": 1})
        assert r.status_code == 422, (i, r.text)
    r = client.post(f"{UC}/olmayan-kural/feedback", json={"deger": 1})
    assert r.status_code == 429 and r.json()["kod"] == "hiz_siniri"


def test_diger_ekranlar_ozeti_kuyruktan_gelir(
    client: TestClient, tohum: Tohum, make_user: MakeUser
) -> None:
    """§17.3 `*` özet: rolün bekleyen işleri (`probe_my_queue` sayımı) `{sayi, rota}` döner;
    açık ekrandaki varlık sayıdan düşer, kuyruk boşsa sayı 0 ve rota yok."""
    _giris(client, make_user("engineer"))
    bos = client.get(UC, params={"rota": "/kosular"}).json()["diger_ekranlar"]
    assert bos == {"sayi": 0, "rota": None}

    rid = tohum.kosu("error")
    oneri.ONBELLEK.temizle()
    ozet = client.get(UC, params={"rota": "/kosular"}).json()["diger_ekranlar"]
    assert ozet == {"sayi": 1, "rota": f"/kosular/{rid}"}
    # Tek iş açık ekrandaysa "diğer ekranlarda" iş kalmaz.
    burada = client.get(UC, params={"rota": f"/kosular/{rid}"}).json()["diger_ekranlar"]
    assert burada == {"sayi": 0, "rota": None}

    rid2 = tohum.kosu("error")
    oneri.ONBELLEK.temizle()
    ozet = client.get(UC, params={"rota": f"/kosular/{rid}"}).json()["diger_ekranlar"]
    assert ozet == {"sayi": 1, "rota": f"/kosular/{rid2}"}

    _giris(client, make_user("analyst"))  # rol kapısı: koşu hatası mühendisin işidir
    assert client.get(UC, params={"rota": "/kosular"}).json()["diger_ekranlar"]["sayi"] == 0


P95_ESIK_MS = float(os.environ.get("TP_TEST_ONERI_P95_MS", "300"))
P95_TEKRAR = int(os.environ.get("TP_TEST_ONERI_P95_TEKRAR", "6"))


@pytest.mark.perf
@pytest.mark.skipif(
    os.environ.get("TP_TEST_PERF", "0").strip() != "1",
    reason="süre ölçümü varsayılan kapalı (yük altında yanlış kırmızı); TP_TEST_PERF=1 ile açılır",
)
def test_oneri_ucu_tohumlu_veride_p95_300ms_alti(
    client: TestClient,
    tohum: Tohum,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§16.12: tohumlu veride 5 rol × ana ekranlar, önbellek dışı p95 < 300 ms.

    Her çağrı öncesi `ONBELLEK.temizle()` (sunucu önbelleği ölçümü yanıltmaz). Rol × rota başına
    bir ısınma çağrısı ölçülmez (ilk sorgu planı/bağlantı ısınması p95'i oynatmasın). Eşik yavaş
    CI makinesi için `TP_TEST_ONERI_P95_MS`, tekrar `TP_TEST_ONERI_P95_TEKRAR` ile ayarlanır;
    `perf` işaretli (`-m 'not perf'`), `TP_TEST_PERF=0` atlar.
    """
    monkeypatch.setitem(hiz.VARSAYILAN_SINIRLAR, hiz.KOVA_ONERI_LISTE, (10_000, 60))
    req = tohum.gereksinim("findings_open", po_bekleme=30)
    tohum.bulgu(req)
    tohum.case(req)
    rid = tohum.kosu("error")
    fid = tohum.hata("test_maintenance", run_id=rid)
    sid = tohum.script("failed")
    bid = tohum.bug_taslagi("draft", failure_id=fid)
    tohum.harcama("7")
    rotalar = [
        "/",
        "/gereksinimler",
        f"/gereksinimler/{req}",
        f"/gereksinimler/{req}/caseler",
        "/kod",
        f"/kod/{sid}",
        "/kosular",
        f"/kosular/{rid}",
        f"/hatalar/{fid}",
        "/bug-taslaklari",
        f"/bug-taslaklari/{bid}",
        "/kontrol-kulesi",
    ]
    sureler: list[float] = []
    for rol in ROLLER:
        _giris(client, make_user(rol))
        for rota in rotalar:
            oneri.ONBELLEK.temizle()
            assert client.get(UC, params={"rota": rota}).status_code == 200  # ısınma
            for _ in range(P95_TEKRAR):
                oneri.ONBELLEK.temizle()
                bas = time.perf_counter()
                r = client.get(UC, params={"rota": rota})
                sureler.append((time.perf_counter() - bas) * 1000)
                assert r.status_code == 200, (rol, rota, r.text)
    sureler.sort()
    p95 = sureler[int(len(sureler) * 0.95) - 1]
    assert p95 < P95_ESIK_MS, f"p95={p95:.1f} ms (n={len(sureler)}, eşik {P95_ESIK_MS} ms)"
