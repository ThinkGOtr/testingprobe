"""Çok proje çekirdeği (TP-COK-PROJE-PLANI §7 Şerit 0): bağlam, ORM filtresi, ayar, sayaç,
istemci fabrikası, migrasyon 0044.

ORM filtresi DB'siz (SQLite, testin kendi modelleri) sınanır; `tp_proje`/`proje_sayac` ve
migrasyon gerçek Postgres'te (`db` fikstürü; Docker yoksa atlanır).
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import ForeignKey, String, create_engine, delete, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

import tp_core.models  # noqa: F401 — orm.kur(Session) burada bağlanır
from tp_core.models.base import ProjeKapsamli
from tp_core.proje import (
    KURULUM,
    ProjeBaglamiYok,
    ProjeIhlali,
    baglamla,
    istemciler,
    kurulu_projeler,
    mevcut,
    mevcut_pid,
    orm,
    pid_param,
    proje_icinde,
    proje_kaydet,
    sayac,
    varsa,
    varsayilan_pid,
)
from tp_core.proje import ayar as ayar_mod
from tp_core.proje.ayar import (
    PROJE_ANAHTARLARI,
    ayar,
    ayar_bool,
    ayar_float,
    ayar_int,
    kaynak_bagla,
    sir,
    surum,
)

# ------------------------------------------------------------------------------- bağlam


def test_baglam_yokken_hata() -> None:
    assert varsa() is None
    with pytest.raises(ProjeBaglamiYok):
        mevcut()
    with pytest.raises(ProjeBaglamiYok):
        mevcut_pid()
    with pytest.raises(ProjeBaglamiYok):
        pid_param()


def test_proje_icinde_ic_ice_ve_geri_alma() -> None:
    with proje_icinde("a", kaynak="cli") as b:
        assert b.pid == "a" and b.kaynak == "cli"
        assert mevcut() == b
        with proje_icinde("b"):
            assert mevcut_pid() == "b"
            assert mevcut().kaynak == "sistem"
            assert pid_param(x=1) == {"pid": "b", "x": 1}
        assert mevcut_pid() == "a"
    assert varsa() is None


def test_proje_icinde_istisnada_geri_alir() -> None:
    with pytest.raises(ValueError, match="x"), proje_icinde("a"):
        raise ValueError("x")
    assert varsa() is None


@pytest.mark.parametrize("pid", ["", "  ", " a", "a ", "x" * 65])
def test_gecersiz_pid(pid: str) -> None:
    with pytest.raises(ValueError), proje_icinde(pid):
        pass


def test_varsayilan_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TP_HOME_PROJECT", raising=False)
    assert varsayilan_pid() == "varsayilan"
    monkeypatch.setenv("TP_HOME_PROJECT", "  bayi-pid ")
    assert varsayilan_pid() == "bayi-pid"
    assert KURULUM == "_kurulum"


def test_thread_baglami_miras_almaz_baglamla_tasir() -> None:
    sonuc: dict[str, Any] = {}

    def oku(ad: str) -> None:
        b = varsa()
        sonuc[ad] = b.pid if b else None

    with proje_icinde("a"):
        t1 = threading.Thread(target=oku, args=("ham",))
        t2 = threading.Thread(target=baglamla(oku), args=("sarili",))
        t1.start(), t2.start()
        t1.join(), t2.join()
    assert sonuc == {"ham": None, "sarili": "a"}


def test_baglamla_cagri_basina_kopya() -> None:
    def ic() -> tuple[str, str]:
        once = mevcut_pid()
        with proje_icinde("z"):
            return once, mevcut_pid()

    def sizdir() -> tuple[str, str]:
        from tp_core.proje.baglam import _BAGLAM, ProjeBaglami

        once = mevcut_pid()
        _BAGLAM.set(ProjeBaglami("sizinti", "test"))  # çağrı içinde geri alınmayan değişiklik
        return once, mevcut_pid()

    with proje_icinde("a"):
        f = baglamla(ic)
        g = baglamla(sizdir)
    assert f() == ("a", "z")
    assert g() == ("a", "sizinti")
    assert g() == ("a", "sizinti")  # önceki çağrının değişikliği sonraki çağrıya sızmaz
    assert f() == ("a", "z")
    assert varsa() is None


# ------------------------------------------------------------------- ORM filtresi (SQLite)


class _TBase(DeclarativeBase):
    pass


class Ebeveyn(ProjeKapsamli, _TBase):
    __tablename__ = "t_ebeveyn"
    id: Mapped[int] = mapped_column(primary_key=True)
    ad: Mapped[str] = mapped_column(String(20))
    cocuklar: Mapped[list[Cocuk]] = relationship(back_populates="ebeveyn")


class Cocuk(ProjeKapsamli, _TBase):
    __tablename__ = "t_cocuk"
    id: Mapped[int] = mapped_column(primary_key=True)
    ebeveyn_id: Mapped[int] = mapped_column(ForeignKey("t_ebeveyn.id"))
    ebeveyn: Mapped[Ebeveyn] = relationship(back_populates="cocuklar")


class Kurulum(_TBase):
    __tablename__ = "t_kurulum"
    id: Mapped[int] = mapped_column(primary_key=True)


@pytest.fixture
def sq() -> Iterator[Engine]:
    eng = create_engine("sqlite://")
    _TBase.metadata.create_all(eng)
    with Session(eng) as s:
        with proje_icinde("a"):
            s.add_all([Ebeveyn(id=1, ad="a1"), Ebeveyn(id=2, ad="a2"), Cocuk(id=1, ebeveyn_id=1)])
            s.flush()
        with proje_icinde("b"):
            s.add_all([Ebeveyn(id=3, ad="b1"), Cocuk(id=2, ebeveyn_id=3)])
            s.flush()
        s.add(Kurulum(id=1))
        s.commit()
    yield eng
    eng.dispose()


def test_kur_idempotent() -> None:
    from sqlalchemy import event

    orm.kur(Session)
    orm.kur(Session)
    assert event.contains(Session, "do_orm_execute", orm._orm_execute)
    assert event.contains(ProjeKapsamli, "load", orm._yuklendi)


def test_insert_baglamdan_doldurur(sq: Engine) -> None:
    with sq.connect() as c:
        satirlar = c.execute(text("SELECT id, project_id FROM t_ebeveyn ORDER BY id")).all()
    assert [tuple(r) for r in satirlar] == [(1, "a"), (2, "a"), (3, "b")]


def test_select_baglamdaki_projeye_suzulur(sq: Engine) -> None:
    # Aynı (önbelleğe alınmış) ifade iki bağlamda farklı pid ile koşmalı.
    for pid, beklenen in (("a", [1, 2]), ("b", [3]), ("a", [1, 2])):
        with Session(sq) as s, proje_icinde(pid):
            assert s.scalars(select(Ebeveyn.id).order_by(Ebeveyn.id)).all() == beklenen
            assert s.scalars(select(Ebeveyn).order_by(Ebeveyn.id)).all()[0].project_id == pid


def test_get_baska_projede_yok(sq: Engine) -> None:
    with Session(sq) as s, proje_icinde("b"):
        assert s.get(Ebeveyn, 1) is None
        assert s.get(Ebeveyn, 3) is not None


def test_join_ve_iliski_yuklemesi_suzulur(sq: Engine) -> None:
    with Session(sq) as s, proje_icinde("a"):
        e = s.get(Ebeveyn, 1)
        assert e is not None and [c.id for c in e.cocuklar] == [1]
        q = select(Cocuk.id).join(Cocuk.ebeveyn).order_by(Cocuk.id)
        assert s.scalars(q).all() == [1]


def test_baglamsiz_kapsamli_sorgu_hata_kapsamsiz_serbest(sq: Engine) -> None:
    with Session(sq) as s:
        with pytest.raises(ProjeBaglamiYok):
            s.scalars(select(Ebeveyn)).all()
        with pytest.raises(ProjeBaglamiYok):
            s.get(Ebeveyn, 1)
        assert s.scalars(select(Kurulum.id)).all() == [1]


def test_tum_projeler_kacisi(sq: Engine) -> None:
    with Session(sq) as s:
        q = select(Ebeveyn).order_by(Ebeveyn.id).execution_options(tum_projeler=True)
        assert [e.project_id for e in s.scalars(q)] == ["a", "a", "b"]


def test_yukleme_koruyucusu_yanlis_projeyi_reddeder(sq: Engine) -> None:
    # from_statement ölçüt almaz → B satırı A bağlamında yüklenirse ProjeIhlali.
    with Session(sq) as s, proje_icinde("a"):
        q = select(Ebeveyn).from_statement(text("SELECT * FROM t_ebeveyn WHERE id = 3"))
        with pytest.raises(ProjeIhlali):
            s.scalars(q).all()


def test_toplu_update_delete_suzulur(sq: Engine) -> None:
    with Session(sq) as s, proje_icinde("b"):
        s.execute(update(Ebeveyn).values(ad="degisti"))
        s.execute(delete(Cocuk))
        s.commit()
    with sq.connect() as c:
        adlar = dict(c.execute(text("SELECT id, ad FROM t_ebeveyn")).all())
        cocuklar = c.execute(text("SELECT id FROM t_cocuk")).scalars().all()
    assert adlar == {1: "a1", 2: "a2", 3: "degisti"}
    assert cocuklar == [1]


def test_yanlis_projeye_yazma_reddedilir(sq: Engine) -> None:
    with Session(sq) as s, proje_icinde("a"):
        s.add(Ebeveyn(id=9, ad="x", project_id="b"))
        with pytest.raises(ProjeIhlali):
            s.flush()


def test_baglamsiz_ekleme_acik_pid_ile_serbest_pidsiz_hata(sq: Engine) -> None:
    with Session(sq) as s:
        s.add(Ebeveyn(id=9, ad="x", project_id="c"))
        s.flush()
        s.add(Ebeveyn(id=10, ad="y"))
        with pytest.raises(ProjeBaglamiYok):
            s.flush()


def test_cocuk_ebeveyn_projesi_esit_olmali(sq: Engine) -> None:
    with Session(sq) as s:
        with proje_icinde("a"):
            e = s.get(Ebeveyn, 1)
        with proje_icinde("b"):
            s.add(Cocuk(id=9, ebeveyn=e))
            with pytest.raises(ProjeIhlali):
                s.flush()


def test_proje_degistirilemez(sq: Engine) -> None:
    with Session(sq) as s, proje_icinde("a"):
        e = s.get(Ebeveyn, 1)
        assert e is not None
        e.project_id = "b"
        with pytest.raises(ProjeIhlali):
            s.flush()


def test_kapsamli_tablolar_yalniz_tp_modelleri() -> None:
    # Şerit 1 mixin'i §1.1 A tablolarına uyguladı; test modelleri sayılmaz.
    from tests.unit.platform.test_proje_kapsami import PLAN_KAPSAMLI

    assert orm.kapsamli_tablolar() == PLAN_KAPSAMLI
    assert orm.TUM_PROJELER == "tum_projeler"


# ------------------------------------------------------------------------------------ ayar


@pytest.fixture
def _kaynaksiz() -> Iterator[None]:
    ayar_mod._kaynak_coz()
    yield
    ayar_mod._kaynak_coz()


def test_ayar_env_varsayilan_projede(monkeypatch: pytest.MonkeyPatch, _kaynaksiz: None) -> None:
    monkeypatch.setenv("TP_HOME_PROJECT", "p1")
    monkeypatch.setenv("JIRA_PROJECT", "ABC")
    assert ayar("JIRA_PROJECT") == "ABC"  # bağlamsız, kaynak yok → tek proje
    with proje_icinde("p1"):
        assert ayar("JIRA_PROJECT") == "ABC"
    with proje_icinde("p2"):
        assert ayar("JIRA_PROJECT") is None
        assert ayar("JIRA_PROJECT", "VAR") == "VAR"
    assert ayar("JIRA_PROJECT", pid="p2") is None


@pytest.mark.parametrize(
    ("deger", "beklenen"),
    [("1", True), ("true", True), ("Evet", True), ("0", False), ("off", False), ("??", None)],
)
def test_ayar_bool(
    monkeypatch: pytest.MonkeyPatch, _kaynaksiz: None, deger: str, beklenen: bool | None
) -> None:
    monkeypatch.delenv("TP_HOME_PROJECT", raising=False)
    monkeypatch.setenv("TP_X", deger)
    for vars_ in (True, False):
        assert ayar_bool("TP_X", vars_) is (vars_ if beklenen is None else beklenen)


def test_ayar_sayisal(monkeypatch: pytest.MonkeyPatch, _kaynaksiz: None) -> None:
    monkeypatch.delenv("TP_HOME_PROJECT", raising=False)
    monkeypatch.setenv("TP_I", " 42 ")
    monkeypatch.setenv("TP_F", "2.5")
    monkeypatch.setenv("TP_BOZUK", "x")
    assert ayar_int("TP_I", 1) == 42
    assert ayar_float("TP_F", 1.0) == 2.5
    assert ayar_int("TP_BOZUK", 7) == 7
    assert ayar_float("TP_BOZUK", 7.5) == 7.5
    assert ayar_int("TP_YOK", 3) == 3
    monkeypatch.setenv("TP_BOS", "")
    assert sir("TP_BOS") is None


def test_kaynak_bagli_cozum_sirasi_ve_katilik(
    monkeypatch: pytest.MonkeyPatch, _kaynaksiz: None
) -> None:
    monkeypatch.setenv("TP_HOME_PROJECT", "p1")
    monkeypatch.setenv("JIRA_PROJECT", "ENV")
    monkeypatch.setenv("TP_FORGE", "local")
    kaynak = {"p1": {"JIRA_PROJECT": "HOME1"}, "p2": {"JIRA_PROJECT": "HOME2"}}
    kaynak_bagla(lambda pid: kaynak.get(pid), lambda pid: f"etag-{pid}")
    with proje_icinde("p1"):
        assert ayar("JIRA_PROJECT") == "HOME1"  # proje config env'in önünde
        assert ayar("TP_FORGE") == "local"  # varsayılan projede env'e düşer
        # `+N` eki: test fikstürü (`proje_ayar`) sayacı; önceki testlere bağlı, etag tabandır.
        assert surum().split("+")[0] == "etag-p1"
    with proje_icinde("p2"):
        assert ayar("JIRA_PROJECT") == "HOME2"
        assert ayar("TP_FORGE") is None  # başka projeye env sızmaz
    assert ayar("JIRA_PROJECT", pid="p2") == "HOME2"
    with pytest.raises(ProjeBaglamiYok):
        ayar("JIRA_PROJECT")  # çok proje kaynağı bağlıyken bağlamsız okuma


def test_proje_ayar_fikstur(proje: Any, proje_ayar: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_PROJECT", "ENV")
    s0 = surum()
    proje_ayar(JIRA_PROJECT="FIX", TP_FORGE="github")
    proje_ayar(pid="test-b", JIRA_PROJECT="B")
    assert ayar("JIRA_PROJECT") == "FIX"
    assert ayar("JIRA_PROJECT", pid="test-b") == "B"
    assert surum() != s0
    proje_ayar(JIRA_PROJECT=None)
    assert ayar("JIRA_PROJECT") == "ENV"


def test_proje_anahtarlari_d_icermez() -> None:
    assert {"JIRA_PROJECT", "TP_FORGE", "GITHUB_REPO", "ANTHROPIC_API_KEY"} <= PROJE_ANAHTARLARI
    d = {"TP_DATABASE_URL", "TP_SESSION_SECRET", "TOOLCHAIN_URL", "TP_FORGE_PATH", "TP_ORTAM"}
    assert not d & PROJE_ANAHTARLARI


def test_ozellik_acik_home_yokken_acik(proje: Any) -> None:
    assert ayar_mod.ozellik_acik("web") is True


# ------------------------------------------------------------------------------ istemciler


@pytest.fixture
def _temiz_istemci() -> Iterator[None]:
    istemciler.sifirla()
    yield
    istemciler.sifirla()


def test_forge_onbellek_surume_bagli(
    proje: Any, proje_ayar: Any, monkeypatch: pytest.MonkeyPatch, _temiz_istemci: None
) -> None:
    kurulan: list[object] = []

    def sahte() -> object:
        kurulan.append(object())
        return kurulan[-1]

    monkeypatch.setattr("tp_core.integrations.forge.get_forge", sahte)
    f1 = istemciler.forge()
    assert istemciler.forge() is f1
    proje_ayar(TP_FORGE="local")  # sürüm değişir → yeniden kurulur
    f2 = istemciler.forge()
    assert f2 is not f1
    with proje_icinde("test-b"):
        assert istemciler.forge() is not f2  # proje başına ayrı
    istemciler.sifirla("test-a")
    assert istemciler.forge() is not f2
    assert len(kurulan) == 4


def test_xray_ci_kipine_gore(
    proje: Any, proje_ayar: Any, monkeypatch: pytest.MonkeyPatch, _temiz_istemci: None
) -> None:
    proje_ayar(TP_TEST_MGMT="jira", TP_FORGE="local")
    assert istemciler.xray() is None
    assert istemciler.ci() is None
    monkeypatch.setattr("tp_core.integrations.xray.get_xray_client", lambda: "xray")
    proje_ayar(TP_TEST_MGMT="xray")
    assert istemciler.xray() == "xray"
    assert istemciler.toolchain_proje_blogu() == {"pid": "test-a"}


# ------------------------------------------------------------------ Postgres: 0044, sayaç


def test_migrasyon_varsayilan_proje_satiri(engine: Engine) -> None:
    with engine.connect() as c:
        satir = c.execute(text("SELECT pid, kaynak, aktif FROM tp_proje")).one()
        assert tuple(satir) == ("varsayilan", "env", True)
        assert c.execute(text("SELECT secili_proje FROM app_user LIMIT 0")).all() == []


def test_proje_kaydet_ve_kurulu_projeler(engine: Engine) -> None:
    with engine.begin() as c:
        assert proje_kaydet(c, "p-b", kod=None, ad=None, kaynak="kesif") is True
        assert proje_kaydet(c, "p-a", kod="PA", ad="Proje A", kaynak="env") is True
        assert proje_kaydet(c, "p-b", kod="PB", ad=None, kaynak="env") is False
        assert proje_kaydet(c, "p-b", kod=None, ad="Proje B", kaynak="env") is False
        c.execute(text("UPDATE tp_proje SET aktif = false WHERE pid = 'varsayilan'"))
    with engine.connect() as c:
        assert kurulu_projeler(c) == ["p-a", "p-b"]
        assert tuple(
            c.execute(text("SELECT kod, ad, kaynak FROM tp_proje WHERE pid = 'p-b'")).one()
        ) == ("PB", "Proje B", "kesif")
    with pytest.raises(ValueError), engine.begin() as c:
        proje_kaydet(c, "x", kod=None, ad=None, kaynak="baska")  # type: ignore[arg-type]


def test_sayac_proje_basina_ve_islem_kapsamli(engine: Engine) -> None:
    with engine.begin() as c, proje_icinde("p1"):
        assert [sayac.sonraki(c, "pr") for _ in range(3)] == [1, 2, 3]
        assert sayac.sonraki(c, "talep") == 1
        assert sayac.sonraki(c, "pr", project_id="p2") == 1
    with pytest.raises(RuntimeError), engine.begin() as c:
        assert sayac.sonraki(c, "pr", "p1") == 4
        raise RuntimeError("geri al")
    with engine.begin() as c:
        assert sayac.sonraki(c, "pr", "p1") == 4
        with pytest.raises(ProjeBaglamiYok):
            sayac.sonraki(c, "pr")


def test_sayac_eszamanli_tekil(engine: Engine) -> None:
    sonuclar: list[int] = []
    kilit = threading.Lock()

    def al() -> None:
        for _ in range(10):
            with engine.begin() as c:
                n = sayac.sonraki(c, "pr", "es")
            with kilit:
                sonuclar.append(n)

    ipler = [threading.Thread(target=al) for _ in range(4)]
    for t in ipler:
        t.start()
    for t in ipler:
        t.join()
    assert sorted(sonuclar) == list(range(1, 41))


def test_proje_fiksturu_db_kaydi(proje: Any, engine: Engine) -> None:
    with engine.connect() as c:
        assert "test-a" in kurulu_projeler(c)
    assert mevcut_pid() == "test-a" and mevcut().kaynak == "test"


def test_iki_proje_fiksturu(iki_proje: tuple[str, str], engine: Engine) -> None:
    assert iki_proje == ("test-a", "test-b")
    assert varsa() is None
    with engine.connect() as c:
        assert {"test-a", "test-b"} <= set(kurulu_projeler(c))
    assert varsayilan_pid() == "test-a"


def test_tp_app_tp_proje_silemez(db: Any) -> None:
    import psycopg

    with psycopg.connect(db.app_url.replace("+psycopg", ""), autocommit=True) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("DELETE FROM tp_proje")
        c.execute("UPDATE tp_proje SET aktif = true")
        c.execute(
            "INSERT INTO proje_sayac (project_id, ad, deger) VALUES (%s, 'x', 1)",
            (uuid.uuid4().hex[:8],),
        )
