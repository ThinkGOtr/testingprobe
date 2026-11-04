"""Asistan hız sayacı (`hiz.py`) ve bütçe/sayaç sorguları (`budget.py`) — AI-ASISTAN-PLANI §6.2,
§6.4, §9. Gerçek Postgres."""

from __future__ import annotations

import json
import threading
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tp_core.features.assistant import budget, hiz
from tp_core.gateway.errors import BudgetExceeded

# ------------------------------------------------------------------ yardımcılar


def _sohbet(engine: Engine, kullanici_id: uuid.UUID) -> uuid.UUID:
    sid = uuid.uuid4()
    with engine.begin() as c:
        c.execute(
            text("INSERT INTO asistan_sohbet (id, kullanici_id) VALUES (:i, :k)"),
            {"i": sid, "k": kullanici_id},
        )
    return sid


def _mesaj(
    engine: Engine,
    sohbet: uuid.UUID,
    kullanici_id: uuid.UUID,
    sira: int,
    *,
    ust: uuid.UUID | None = None,
    amac: str | None = None,
    tetik: str = "kullanici",
    durum: str = "done",
    ai_call_id: uuid.UUID | None = None,
) -> uuid.UUID:
    mid = uuid.uuid4()
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO asistan_mesaj (id, sohbet_id, kullanici_id, sira, rol, ust_mesaj_id, "
                "amac, tetik, durum, ai_call_id) VALUES (:i, :s, :k, :n, 'assistant', :u, :a, "
                ":t, :d, :c)"
            ),
            {
                "i": mid,
                "s": sohbet,
                "k": kullanici_id,
                "n": sira,
                "u": ust,
                "a": amac,
                "t": tetik,
                "d": durum,
                "c": ai_call_id,
            },
        )
    return mid


def _ai_call(
    engine: Engine,
    maliyet: str,
    *,
    kullanici_id: uuid.UUID | None = None,
    amac: str = "assistant",
    parent: uuid.UUID | None = None,
    gun_once: int = 0,
) -> uuid.UUID:
    cid = uuid.uuid4()
    ek = {"kanal": "asistan", "kullanici_id": str(kullanici_id)} if kullanici_id else None
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO ai_call (id, parent_call_id, amac, saglayici, model, mod, maliyet, "
                "ek, olusturma) VALUES (:id, :p, :a, 'anthropic', 'm', 'live', :m, "
                "CAST(:ek AS jsonb), now() - make_interval(days => :g))"
            ),
            {
                "id": cid,
                "p": parent,
                "a": amac,
                "m": Decimal(maliyet),
                "ek": json.dumps(ek),
                "g": gun_once,
            },
        )
    return cid


def _is(engine: Engine, kullanici_id: uuid.UUID, *, tetik: str, durum: str = "queued") -> uuid.UUID:
    with engine.begin() as c:
        return c.execute(
            text(
                "INSERT INTO job (tur, yuk, durum) VALUES ('assistant.answer', CAST(:y AS jsonb), "
                ":d) RETURNING id"
            ),
            {
                "y": json.dumps(
                    {
                        "mesaj_id": str(uuid.uuid4()),
                        "kullanici_id": str(kullanici_id),
                        "tetik": tetik,
                    }
                ),
                "d": durum,
            },
        ).scalar_one()


# ------------------------------------------------------------------ hız sayacı


# Sayaç testleri geniş pencerede (`sabit_hiz_penceresi`): saate hizalı 60 sn'lik pencerede
# çağrılar dakika sınırını aşarsa sayaç sıfırlanır. Bugün `session` tek transaction ve `now()`
# sabit olduğundan bu olmaz; ama fikstür ara commit yaparsa yanlış kırmızı çıkardı (API testleri
# de aynı nedenle geniş pencere kullanır). Pencere hizası ayrıca aşağıda sınanır.


def test_hiz_sabit_pencere_sinir_dahil(
    session: Session, make_user, sabit_hiz_penceresi: int
) -> None:
    u = make_user("analyst")
    p = sabit_hiz_penceresi
    sonuc = [
        hiz.hiz_kontrol(session, "oneri_liste", kullanici_id=u.id, sinir=60, pencere_s=p)
        for _ in range(61)
    ]
    assert sonuc[:60] == [True] * 60 and sonuc[60] is False
    # başka kullanıcı ve başka kova ayrı sayılır
    v = make_user("po")
    assert hiz.hiz_kontrol(session, "oneri_liste", kullanici_id=v.id, sinir=60, pencere_s=p)
    assert hiz.kova_kontrol(session, hiz.KOVA_ONERI_GERI_BILDIRIM, kullanici_id=u.id)


def test_hiz_global_kova_null_kullanici_tek_satir(
    session: Session, sabit_hiz_penceresi: int
) -> None:
    for _ in range(30):
        assert hiz.kova_kontrol(session, hiz.KOVA_JIRA_GLOBAL, kullanici_id=None)
    assert hiz.kova_kontrol(session, hiz.KOVA_JIRA_GLOBAL, kullanici_id=None) is False
    satir = session.execute(
        text("SELECT count(*), max(sayi) FROM asistan_hiz WHERE kova = 'jira_global'")
    ).one()
    assert tuple(satir) == (1, 31)


def test_hiz_pencere_baslangici_hizali(session: Session) -> None:
    hiz.hiz_kontrol(session, "x", kullanici_id=None, sinir=5, pencere_s=60)
    bas = session.execute(
        text("SELECT extract(epoch FROM pencere_baslangic) FROM asistan_hiz WHERE kova = 'x'")
    ).scalar_one()
    assert int(bas) % 60 == 0


def test_hiz_cok_surecte_atomik(engine: Engine) -> None:
    """Eşzamanlı 40 artırım: tam 30'u kabul, sayaç 40 (kayıp güncelleme yok)."""
    kabul: list[bool] = []
    kilit = threading.Lock()
    engel = threading.Barrier(8)

    def kos() -> None:
        engel.wait()
        for _ in range(5):
            with Session(engine) as s, s.begin():
                ok = hiz.hiz_kontrol(s, "yaris", kullanici_id=None, sinir=30, pencere_s=3600)
            with kilit:
                kabul.append(ok)

    tlar = [threading.Thread(target=kos) for _ in range(8)]
    for t in tlar:
        t.start()
    for t in tlar:
        t.join(30)
    assert kabul.count(True) == 30 and len(kabul) == 40
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT sum(sayi) FROM asistan_hiz WHERE kova = 'yaris'")).scalar() == 40
        )


def test_hiz_gecersiz_arguman(session: Session) -> None:
    with pytest.raises(ValueError):
        hiz.hiz_kontrol(session, "", kullanici_id=None, sinir=1, pencere_s=60)
    with pytest.raises(ValueError):
        hiz.hiz_kontrol(session, "k", kullanici_id=None, sinir=0, pencere_s=60)


def test_hiz_temizle_eski_satirlar(session: Session) -> None:
    session.execute(
        text(
            "INSERT INTO asistan_hiz (kova, pencere_baslangic, sayi) VALUES "
            "('eski', now() - interval '25 hours', 3), ('yeni', now(), 1)"
        )
    )
    assert hiz.hiz_temizle(session) == 1
    kalan = session.execute(text("SELECT kova FROM asistan_hiz")).scalars().all()
    assert kalan == ["yeni"]


# ------------------------------------------------------------------ harcama sorguları


def test_soru_harcamasi_kok_cocuk_ve_turlar(engine: Engine, make_user) -> None:
    u = make_user("engineer")
    s = _sohbet(engine, u.id)
    kok_call = _ai_call(engine, "0.01", kullanici_id=u.id)
    _ai_call(engine, "0.02", kullanici_id=u.id, parent=kok_call)
    kok = _mesaj(engine, s, u.id, 2, amac="assistant", ai_call_id=kok_call)
    cocuk_call = _ai_call(engine, "0.10", kullanici_id=u.id, amac="assistant_deep")
    _ai_call(engine, "0.05", kullanici_id=u.id, amac="assistant_deep", parent=cocuk_call)
    cocuk = _mesaj(
        engine, s, u.id, 3, ust=kok, amac="assistant_deep", tetik="otomatik", ai_call_id=cocuk_call
    )
    _ai_call(engine, "0.40", kullanici_id=u.id)  # ilgisiz çağrı
    with engine.connect() as c:
        assert budget.soru_harcamasi_usd(c, kok) == Decimal("0.18")
        assert budget.kok_mesaj_id(c, cocuk) == kok
        assert budget.kok_mesaj_id(c, kok) == kok
        assert budget.kok_mesaj_id(c, uuid.uuid4()) is None


def test_soru_harcamasi_iki_kademe_zincir(engine: Engine, make_user) -> None:
    """Sözlük cevabı → elle `assistant` → elle `assistant_deep`: torun da köke sayılır."""
    u = make_user("tester")
    s = _sohbet(engine, u.id)
    kok = _mesaj(engine, s, u.id, 2, amac=None)
    c1 = _ai_call(engine, "0.01", kullanici_id=u.id)
    orta = _mesaj(engine, s, u.id, 3, ust=kok, amac="assistant", ai_call_id=c1)
    c2 = _ai_call(engine, "0.09", kullanici_id=u.id, amac="assistant_deep")
    torun = _mesaj(engine, s, u.id, 4, ust=orta, amac="assistant_deep", ai_call_id=c2)
    with engine.connect() as c:
        assert budget.kok_mesaj_id(c, torun) == kok
        assert budget.soru_harcamasi_usd(c, kok) == Decimal("0.10")


def test_kullanici_ve_asistan_gunluk(engine: Engine, make_user) -> None:
    u, v = make_user("analyst"), make_user("po")
    _ai_call(engine, "0.30", kullanici_id=u.id)
    _ai_call(engine, "0.20", kullanici_id=u.id, amac="assistant_deep")
    _ai_call(engine, "0.70", kullanici_id=v.id)
    _ai_call(engine, "5.00", kullanici_id=u.id, gun_once=1)  # dün
    _ai_call(engine, "1.00", amac="requirement_analysis")  # pipeline
    with engine.connect() as c:
        assert budget.kullanici_gunluk_usd(c, u.id) == Decimal("0.50")
        assert budget.asistan_gunluk_usd(c) == Decimal("1.20")
        k = budget.kalanlar(c, u.id)
    assert k.kullanici == Decimal("0.50") and k.asistan == Decimal("8.80")
    assert k.soru is None and k.asilan() is None


def test_butce_on_kontrol_kapsam_sirasi(engine: Engine, make_user, monkeypatch) -> None:
    u = make_user("presenter")
    monkeypatch.setenv("TP_DAILY_BUDGET_USD", "2")
    from tp_core.config import get_settings

    get_settings.cache_clear()
    try:
        _ai_call(engine, "2.00", amac="requirement_analysis")
        with engine.connect() as c:
            assert budget.butce_on_kontrol(c, u.id) == "genel"
            _ai_call(engine, "1.00", kullanici_id=u.id)
            assert budget.butce_on_kontrol(c, u.id) == "kullanici"
    finally:
        get_settings.cache_clear()


# ------------------------------------------------------------------ sayaçlar


def test_sayaclar_job_tablosundan(engine: Engine, make_user, monkeypatch) -> None:
    u, v = make_user("analyst"), make_user("tester")
    _is(engine, u.id, tetik="kullanici", durum="running")
    _is(engine, u.id, tetik="otomatik")
    _is(engine, u.id, tetik="kullanici", durum="done")
    _is(engine, u.id, tetik="kullanici", durum="cancelled")
    haric = _is(engine, v.id, tetik="kullanici", durum="retry")
    with engine.connect() as c:
        assert budget.kullanici_bekleyen(c, u.id) == 1
        assert budget.kullanici_bekleyen(c, v.id) == 1
        assert budget.global_bekleyen(c) == 3
        assert budget.global_bekleyen(c, haric_is=haric) == 2
    monkeypatch.setenv("TP_WORKER_ASISTAN_PARALEL", "5")
    assert budget.global_sinir() == 10
    monkeypatch.setenv("TP_WORKER_ASISTAN_PARALEL", "bozuk")
    assert budget.global_sinir() == 6


def test_sayaclar_mesaj_eslemesi_uuid_ve_bozuk_kimlik(engine: Engine, make_user) -> None:
    """Yükteki `mesaj_id` uuid'e çevrilip PK ile eşlenir; boş/bozuk kimlik hata vermez."""
    u = make_user("po")
    sohbet = _sohbet(engine, u.id)
    bitmis = _mesaj(engine, sohbet, u.id, 1, durum="done")
    iptal = _mesaj(engine, sohbet, u.id, 2, durum="iptal")
    with engine.begin() as c:
        for mid in (str(bitmis), str(iptal).upper(), "", "bozuk"):
            c.execute(
                text(
                    "INSERT INTO job (tur, yuk, durum) VALUES ('assistant.answer', "
                    "CAST(:y AS jsonb), 'running')"
                ),
                {
                    "y": json.dumps(
                        {"mesaj_id": mid, "kullanici_id": str(u.id), "tetik": "kullanici"}
                    )
                },
            )
    with engine.connect() as c:
        # done mesajlı iş sayılmaz; iptal + iki kimliksiz iş sayılır.
        assert budget.kullanici_bekleyen(c, u.id) == 3
        assert budget.kullanici_kapanan(c, u.id) == 1


def test_global_kilit_ikinci_transactioni_bekletir(engine: Engine) -> None:
    sira: list[str] = []
    birinci_aldi = threading.Event()

    def ikinci() -> None:
        birinci_aldi.wait(5)
        with engine.begin() as c:
            budget.global_kilit(c)
            sira.append("ikinci")

    t = threading.Thread(target=ikinci)
    t.start()
    with engine.begin() as c:
        budget.global_kilit(c)
        birinci_aldi.set()
        t.join(0.5)
        assert t.is_alive()  # kilit bırakılana kadar bekler
        sira.append("birinci")
    t.join(10)
    assert sira == ["birinci", "ikinci"]


# ------------------------------------------------------------------ otomatik yükseltme ön koşulları


@pytest.fixture
def kok(engine: Engine, make_user) -> tuple[Any, uuid.UUID]:
    u = make_user("engineer")
    s = _sohbet(engine, u.id)
    return u, _mesaj(engine, s, u.id, 2, amac="assistant")


def _karar(engine: Engine, u: Any, kok_id: uuid.UUID, **kw: Any) -> budget.OtomatikKarar:
    with engine.begin() as c:
        budget.global_kilit(c)
        return budget.otomatik_on_kosul(c, u.id, kok_id, **kw)


def test_otomatik_tum_on_kosullar_tamam(engine: Engine, kok) -> None:
    u, kok_id = kok
    assert _karar(engine, u, kok_id) == budget.OtomatikKarar(True)


def test_otomatik_kullanici_kalani_az(engine: Engine, kok) -> None:
    u, kok_id = kok
    _ai_call(engine, "0.81", kullanici_id=u.id)
    assert _karar(engine, u, kok_id).neden == "kullanici_kalani"


def test_otomatik_asistan_kalani_az(engine: Engine, kok) -> None:
    u, kok_id = kok
    _ai_call(engine, "9.81", amac="assistant_deep")
    assert _karar(engine, u, kok_id).neden == "asistan_kalani"


def test_otomatik_kok_soru_kalani_az(engine: Engine, kok) -> None:
    u, kok_id = kok
    cid = _ai_call(engine, "0.31", kullanici_id=u.id)
    with engine.begin() as c:
        c.execute(
            text("UPDATE asistan_mesaj SET ai_call_id = :c WHERE id = :m"), {"c": cid, "m": kok_id}
        )
    assert _karar(engine, u, kok_id).neden == "soru_kalani"


def test_otomatik_global_dolu_kendi_isi_haric(engine: Engine, kok, make_user) -> None:
    u, kok_id = kok
    isler = [_is(engine, make_user("tester").id, tetik="kullanici") for _ in range(6)]
    assert _karar(engine, u, kok_id).neden == "global_dolu"
    assert _karar(engine, u, kok_id, mevcut_is=isler[0]).yukselt is True


def test_otomatik_kullanici_orani_esigi(engine: Engine, kok, monkeypatch) -> None:
    """Kalan ≥ $0.20 ama tavanın %20'sinin altında (tavan büyütülünce ayrışır)."""
    u, kok_id = kok
    monkeypatch.setattr(budget, "KULLANICI_GUNLUK_USD", Decimal("2"))
    _ai_call(engine, "1.65", kullanici_id=u.id)  # kalan 0.35 < 0.40
    assert _karar(engine, u, kok_id).neden == "kullanici_orani"


# ------------------------------------------------------------------ geçit bütçesi


def test_asistan_budget_check(engine: Engine, kok) -> None:
    u, kok_id = kok
    b = budget.AsistanBudget(engine, kullanici_id=u.id, kok_id=kok_id)
    b.check(None, 0.1)
    b.charge(None, 5.0)  # yazmaz
    cid = _ai_call(engine, "0.45", kullanici_id=u.id)
    with engine.begin() as c:
        c.execute(
            text("UPDATE asistan_mesaj SET ai_call_id = :c WHERE id = :m"), {"c": cid, "m": kok_id}
        )
    b.check(None, 0.04)
    with pytest.raises(BudgetExceeded) as hata:
        b.check(None, 0.05)
    assert hata.value.scope == "soru başı"
    b2 = budget.AsistanBudget(
        engine, kullanici_id=u.id, kok_id=uuid.uuid4(), genel_sinir_usd=lambda: Decimal("0.4")
    )
    with pytest.raises(BudgetExceeded) as hata:
        b2.check(None)
    assert hata.value.scope == "günlük"
