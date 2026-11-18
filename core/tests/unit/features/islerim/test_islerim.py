"""İşlerim (`GET /work-queue`), insan sınıflandırması (`POST /failures/{id}/classify`) ve kayıt yeri
(`GET /locate`) — TP UX denetimi IA-01/02/05/16. Gerçek Postgres (platform fikstürü)."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tp_core.api import main
from tp_core.auth.login import THROTTLE
from tp_core.models import BugDraft, Failure, Requirement, Run, Script, TestCase
from tp_core.models.triage_feature import FailureEk
from tp_core.proje import proje_icinde
from tp_core.workflow.service import Principal

from ...conftest import PAROLA

MakeUser = Callable[..., Principal]
PID = "varsayilan"


@pytest.fixture(autouse=True)
def _throttle() -> Iterator[None]:
    THROTTLE._kayit.clear()
    yield
    THROTTLE._kayit.clear()


@pytest.fixture
def client(db: Any) -> Iterator[TestClient]:
    with TestClient(main.create_app(), raise_server_exceptions=False) as c:
        yield c


def _giris(client: TestClient, user: Principal) -> None:
    client.cookies.clear()
    r = client.post("/auth/login", json={"kullanici_adi": user.kullanici_adi, "parola": PAROLA})
    assert r.status_code == 200, r.text


def _durum(engine: Engine, tablo: str, kimlik: uuid.UUID, durum: str, alan: str = "durum") -> None:
    with engine.begin() as c:
        c.execute(text(f"UPDATE {tablo} SET {alan} = :d WHERE id = :i"), {"d": durum, "i": kimlik})


class Tohum:
    def __init__(self, engine: Engine, pid: str = PID) -> None:
        self.req = uuid.uuid4()
        self.case_draft = [uuid.uuid4(), uuid.uuid4()]
        self.case_ready = uuid.uuid4()
        self.script = uuid.uuid4()
        self.run = uuid.uuid4()
        self.f_belirsiz = uuid.uuid4()
        self.f_kirma = uuid.uuid4()
        self.f_bakim = uuid.uuid4()
        h = hashlib.sha256(self.req.bytes).hexdigest()
        with Session(engine) as s, proje_icinde(pid, kaynak="test"):
            s.add(Requirement(id=self.req, kaynak="jira", jira_key="ISL-1", baslik="Sepet",
                              kaynak_hash=h))  # fmt: skip
            s.flush()
            for i, cid in enumerate([*self.case_draft, self.case_ready], 1):
                s.add(TestCase(id=cid, requirement_id=self.req, sira_no=i,
                               icerik={"title": f"C{i}"}, icerik_hash=h))  # fmt: skip
            s.add(Script(id=self.script, dosya_yolu="e2e/tests/x.spec.ts", pr_no=7))
            s.flush()
            s.add(Run(id=self.run, script_id=self.script, kaynak="local", tetik="nightly",
                      sonuc="failed"))  # fmt: skip
            s.flush()
            for fid, sinif, ad in (
                (self.f_belirsiz, "unknown", "giriş testi"),
                (self.f_kirma, "unknown", "kırma testi"),
                (self.f_bakim, "test_maintenance", "sepet testi"),
            ):
                s.add(Failure(id=fid, run_id=self.run, test_adi=ad, hata_imzasi=f"imza-{ad}",
                              sinif=sinif))  # fmt: skip
            s.flush()
            s.add(FailureEk(failure_id=self.f_kirma, anahtar=f"k-{self.f_kirma}", kirma=True))
            s.commit()
        _durum(engine, "requirement", self.req, "cases_ready")
        _durum(engine, "test_case", self.case_ready, "ready")
        _durum(engine, "script", self.script, "blocked")


def _grup(yanit: dict[str, Any], liste: str, anahtar: str) -> dict[str, Any] | None:
    return next((g for g in yanit[liste] if g["anahtar"] == anahtar), None)


def test_test_uzmani_kuyrugu_ve_ekip(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    t = Tohum(engine)
    _giris(client, make_user("tester"))
    r = client.get("/work-queue")
    assert r.status_code == 200, r.text
    y = r.json()
    assert y["rol"] == "tester"
    karar = _grup(y, "benim", "case_karari")
    assert karar and karar["sayi"] == 2 and karar["ogeler"][0]["rota"].endswith("/caseler")
    assert karar["sonraki_adim"]
    sinif = _grup(y, "benim", "siniflandirma")
    # Kasıtlı kırma hatası kuyruğa girmez.
    assert sinif and [o["id"] for o in sinif["ogeler"]] == [str(t.f_belirsiz)]
    assert sinif["ogeler"][0]["rota"] == f"/hatalar/{t.f_belirsiz}"
    # Analistin son onayı ve mühendisin insana düşen script'i ekipte.
    son_onay = _grup(y, "ekip", "case_son_onay")
    assert son_onay and son_onay["sayi"] == 1 and son_onay["rol_etiketi"] == "Analist"
    insana = _grup(y, "ekip", "kod_insana")
    assert insana and insana["sayi"] == 1
    assert y["menu"]["/caseler"] == 2 and y["menu"]["/hatalar"] == 1
    assert y["menu"]["/islerim"] == y["toplam"]
    assert y["menu"]["/kod"] == 0


def test_siniflandirma_izni_olan_her_rolun_isi_ve_rozet_liste_sayisi(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    """YD-06: `failure.classify` Otomasyon Mühendisinde de var → sınıflandırma onun da işi; Hatalar
    rozeti = Hatalar listesinin "Sınıflandırılmamış" sayısı (aynı test adının iki hatası iki iş)."""
    t = Tohum(engine)
    ikinci = uuid.uuid4()
    with Session(engine) as s, proje_icinde(PID, kaynak="test"):
        s.add(Failure(id=ikinci, run_id=t.run, test_adi="giriş testi", hata_imzasi="imza-2",
                      sinif="unknown"))  # fmt: skip
        s.commit()
    _giris(client, make_user("engineer"))
    y = client.get("/work-queue").json()
    sinif = _grup(y, "benim", "siniflandirma")
    assert sinif and sinif["sayi"] == 2
    assert sinif["roller"] == ["tester", "engineer"]
    assert sinif["rol_etiketi"] == "Test Uzmanı ya da Otomasyon Mühendisi"
    assert _grup(y, "ekip", "siniflandirma") is None
    # Test bakımı da mühendisin; ama Hatalar rozeti yalnız varsayılan sekmedir (Sınıflandırılmamış).
    assert _grup(y, "benim", "test_bakimi")
    liste = client.get("/failures", params={"sinif": "unknown", "limit": 200}).json()
    siniflanmamis = [h for h in liste if not h.get("kirma")]
    assert y["menu"]["/hatalar"] == len(siniflanmamis) == 2
    assert y["menu"]["/islerim"] == y["toplam"]
    # Analist için ekipte: iki rol birlikte beklenir.
    _giris(client, make_user("analyst"))
    y = client.get("/work-queue").json()
    ekip = _grup(y, "ekip", "siniflandirma")
    assert ekip and ekip["rol_etiketi"] == "Test Uzmanı ya da Otomasyon Mühendisi"


def test_gorüntuleyici_yalniz_sayi_gorur(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    Tohum(engine)
    _giris(client, make_user("viewer"))
    y = client.get("/work-queue").json()
    assert y["benim"] == [] and y["toplam"] == 0
    karar = _grup(y, "ekip", "case_karari")
    assert karar and karar["sayi"] == 2 and karar["ogeler"] == []


def test_onceki_icerik_case_karar_bekliyor_sayilmaz(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    t = Tohum(engine)
    po = make_user("po")
    # Case'ler eski bir PO onayından sonra üretildi; gereksinim yeniden `new` (onaylanan hash yok).
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO review (project_id, nesne_turu, nesne_id, karar, user_id, kanal, "
                "onaylanan_hash, zaman) VALUES (:p, 'requirement', :r, 'po_approve', :u, 'jira', "
                "'eski', now() - interval '1 day')"
            ),
            {"p": PID, "r": t.req, "u": po.id},
        )
        c.execute(text("UPDATE requirement SET onaylanan_hash = NULL WHERE id = :r"), {"r": t.req})
    _durum(engine, "requirement", t.req, "new")
    _giris(client, make_user("tester"))
    y = client.get("/work-queue").json()
    assert _grup(y, "benim", "case_karari") is None
    assert _grup(y, "ekip", "on_inceleme")


def test_siniflandirma_urun_hatasi_bug_taslagi_acar(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    t = Tohum(engine)
    tester = make_user("tester")
    _giris(client, tester)
    yol = f"/failures/{t.f_belirsiz}/classify"
    assert client.post(yol, json={"sinif": "product_defect", "gerekce": ""}).status_code == 422
    assert client.post(yol, json={"sinif": "unknown", "gerekce": "x"}).status_code == 422
    r = client.post(yol, json={"sinif": "product_defect", "gerekce": "Buton gerçekten pasif"})
    assert r.status_code == 200, r.text
    y = r.json()
    assert y["sinif"] == "product_defect" and y["karar_kaynagi"] == "human"
    assert y["acilan_bug_draft_id"] and y["bug_draft_id"] == y["acilan_bug_draft_id"]
    with Session(engine) as s, proje_icinde(PID, kaynak="test"):
        assert s.get(BugDraft, uuid.UUID(y["acilan_bug_draft_id"])) is not None
        f = s.get(Failure, t.f_belirsiz)
        assert f is not None and f.gerekce == "Buton gerçekten pasif"
    with engine.connect() as c:
        ozet = c.execute(
            text("SELECT ozet FROM audit_event WHERE eylem = 'failure.classified' AND nesne = :n"),
            {"n": f"failure:{t.f_belirsiz}"},
        ).scalar_one()
    assert ozet["once"] == "unknown" and ozet["sonra"] == "product_defect"
    # Bağlı taslak varken başka sınıfa alınamaz.
    r2 = client.post(yol, json={"sinif": "environment", "gerekce": "ortamdı"})
    assert r2.status_code == 409
    # Kuyruk: sınıflandırılan hata artık sınıflandırma bekleyenlerde değil; bug kararı bekliyor.
    q = client.get("/work-queue").json()
    assert _grup(q, "benim", "siniflandirma") is None
    assert _grup(q, "benim", "bug_karari")


def test_siniflandirma_izni(client: TestClient, make_user: MakeUser, engine: Engine) -> None:
    t = Tohum(engine)
    for rol, beklenen in (("analyst", 403), ("viewer", 403), ("engineer", 200)):
        _giris(client, make_user(rol))
        r = client.post(
            f"/failures/{t.f_belirsiz}/classify",
            json={"sinif": "test_maintenance", "gerekce": "locator değişti"},
        )
        assert r.status_code == beklenen, (rol, r.text)
    # Test bakımı → Otomasyon Mühendisi kuyruğu.
    q = client.get("/work-queue").json()
    bakim = _grup(q, "benim", "test_bakimi")
    assert bakim and str(t.f_belirsiz) in {o["id"] for o in bakim["ogeler"]}


def test_locate(client: TestClient, make_user: MakeUser, engine: Engine) -> None:
    t = Tohum(engine)
    _giris(client, make_user("tester"))
    r = client.get("/locate", params={"tur": "requirement", "id": str(t.req)})
    assert r.status_code == 200, r.text
    y = r.json()
    assert y["bulundu"] and y["ayni_proje"] and y["proje"]["pid"] == PID
    yok = client.get("/locate", params={"tur": "script", "id": str(uuid.uuid4())}).json()
    assert yok == {"bulundu": False, "ayni_proje": False, "proje": None}


def test_ayni_kisi_tek_ad_gorunen_ad_onceligi() -> None:
    """YD-05: aynı kişinin iki AI Probe hesabı ("Gokhan Sipahi" ve "gokhansipahi LNU") tek kişi;
    tercih edilen ad yer tutucusuz ad soyad. Ortak AI Probe kimliği de birleştirir."""
    from tp_core.auth.display import ayni_kisi_adlari

    kisi = ayni_kisi_adlari(
        [
            ("cengiz", "analyst", None, None, None),
            ("gs-analyst", "analyst", "gokhansipahi LNU", "aiprobe", None),
            ("gokhan.sipahi-analyst", "analyst", "Gokhan Sipahi", "aiprobe", None),
            ("gs-engineer", "engineer", "G. S.", "aiprobe", "uid-1"),
            ("gs-tester", "tester", "Gokhan Sipahi", "aiprobe", "uid-1"),
            ("ayse", "tester", "Ayşe Yılmaz", None, None),
        ],
        {"cengiz": "Cengizhan Gunaydin"},
    )
    assert kisi["gs-analyst"][1] == kisi["gokhan.sipahi-analyst"][1] == "Gokhan Sipahi (AI Probe)"
    assert kisi["gs-analyst"][2] == "gokhan.sipahi-analyst"
    # Ortak external_uid ("G. S." anahtarı kısa) → aynı kişi, iyi ad.
    assert kisi["gs-engineer"][0] == kisi["gs-tester"][0] == kisi["gs-analyst"][0]
    assert kisi["gs-engineer"][1] == "Gokhan Sipahi (AI Probe)"
    assert kisi["cengiz"][1] == "Cengizhan Gunaydin"
    assert kisi["ayse"][0] != kisi["cengiz"][0]


def test_ekip_kisileri_tekil(client: TestClient, make_user: MakeUser, engine: Engine) -> None:
    """Ekip grubundaki kişi listesi aynı kişiyi iki kez yazmaz (YD-05)."""
    Tohum(engine)
    a1 = make_user("analyst")
    a2 = make_user("analyst")
    ad_yaz = text(
        "UPDATE app_user SET ad_soyad = :a, ad_kaynak = 'aiprobe' WHERE kullanici_adi = :k"
    )
    with engine.begin() as c:
        c.execute(ad_yaz, {"a": "Gokhan Sipahi", "k": a1.kullanici_adi})
        c.execute(ad_yaz, {"a": "gokhansipahi LNU", "k": a2.kullanici_adi})
    _giris(client, make_user("tester"))
    y = client.get("/work-queue").json()
    son_onay = _grup(y, "ekip", "case_son_onay")
    assert son_onay
    assert a1.kullanici_adi in son_onay["kisiler"]
    assert a2.kullanici_adi not in son_onay["kisiler"]
    me = client.get("/auth/me").json()
    assert me["kisiler"][a2.kullanici_adi] == me["kisiler"][a1.kullanici_adi]


def test_yeni_yesil_kosu_eski_kirmiziyi_dusurur(
    client: TestClient, make_user: MakeUser, engine: Engine
) -> None:
    """CL-06: yalnız SON durumu kırmızı olan koşu bekleyen iştir. Aynı dal için daha yeni yeşil
    koşu eski kırmızıyı düşürür; CI ortam hatasını aynı kaynakta herhangi bir yeni yeşil düşürür;
    başka PR'ın yeşili düşürmez. Koşu düzeyindeki hata başlığı koşudan üretilir."""
    from datetime import UTC, datetime, timedelta

    simdi = datetime.now(UTC)
    once = simdi - timedelta(days=2)
    k = {
        ad: uuid.uuid4()
        for ad in ("gece_kirmizi", "gece_yesil", "ortam", "pr5", "pr6_yesil", "dal_b")
    }
    with Session(engine) as s, proje_icinde(PID, kaynak="test"):
        for ad, tetik, sonuc, zaman, pr, ref, kaynak in (
            ("gece_kirmizi", "nightly", "failed", once, None, "main", "github"),
            ("gece_yesil", "nightly", "passed", simdi, None, "main", "github"),
            ("ortam", "push", "error", once, None, "dev", "github"),
            ("pr5", "pr", "failed", once, 5, None, "github"),
            ("pr6_yesil", "pr", "passed", simdi, 6, None, "local"),
            ("dal_b", "push", "failed", once, None, "ozellik-b", "local"),
        ):
            s.add(Run(id=k[ad], tetik=tetik, sonuc=sonuc, olusturma=zaman, pr_no=pr,
                      kaynak=kaynak, ortam={"ref": ref} if ref else {}))  # fmt: skip
        s.flush()
        fid = uuid.uuid4()
        s.add(Failure(id=fid, run_id=k["dal_b"], test_adi="(koşu: test sonucu yok)",
                      hata_imzasi="imza-kosu", sinif="environment"))  # fmt: skip
        s.commit()
    _giris(client, make_user("engineer"))
    y = client.get("/work-queue").json()
    kosu = _grup(y, "benim", "kosu_hatasi")
    assert kosu
    idler = {o["id"] for o in kosu["ogeler"]}
    assert str(k["gece_kirmizi"]) not in idler
    assert str(k["ortam"]) not in idler
    assert {str(k["pr5"]), str(k["dal_b"])} <= idler
    assert y["menu"]["/kosular"] == kosu["sayi"] == 2
    bakim = _grup(y, "benim", "test_bakimi")
    assert bakim
    oge = next(o for o in bakim["ogeler"] if o["id"] == str(fid))
    assert oge["etiket"] == f"Push koşusu {str(k['dal_b'])[:8]} · test sonucu yok"
