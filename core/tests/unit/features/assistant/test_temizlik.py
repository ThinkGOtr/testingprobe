"""Asistan saklama temizliği (`temizlik.py`; AI-ASISTAN-PLANI §8): 90 gün, yumuşak silinenler
dahil; etkin sohbetin eski mesajları ve bitmiş cevap işleri de; bekleyen mesaja ve
`ai_call`/`tool_call`'a dokunmaz; hız sayacı 1 gün. Gerçek Postgres."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tp_core.features.assistant import jobs as asistan_jobs
from tp_core.features.assistant import temizlik
from tp_core.workflow.jobs import REGISTRY, process_one

# ------------------------------------------------------------------ yardımcılar


def _sohbet(
    engine: Engine,
    kullanici_id: uuid.UUID,
    *,
    gun_once: int = 0,
    silindi: bool = False,
    silinme_gun_once: int | None = None,
) -> uuid.UUID:
    sid = uuid.uuid4()
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO asistan_sohbet (id, kullanici_id, silindi, silinme, olusturma, "
                "guncelleme) VALUES (:i, :k, :sil, CASE WHEN CAST(:sg AS int) IS NULL THEN NULL "
                "ELSE now() - make_interval(days => CAST(:sg AS int)) END, "
                "now() - make_interval(days => :g), now() - make_interval(days => :g))"
            ),
            {"i": sid, "k": kullanici_id, "sil": silindi, "sg": silinme_gun_once, "g": gun_once},
        )
    return sid


def _mesaj(
    engine: Engine,
    sohbet: uuid.UUID,
    kullanici_id: uuid.UUID,
    sira: int,
    *,
    gun_once: int = 0,
    durum: str = "done",
    rol: str = "user",
    ust: uuid.UUID | None = None,
) -> uuid.UUID:
    mid = uuid.uuid4()
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO asistan_mesaj (id, sohbet_id, kullanici_id, sira, rol, durum, "
                "ust_mesaj_id, amac, olusturma) VALUES (:i, :s, :k, :n, :r, :d, :u, :a, "
                "now() - make_interval(days => :g))"
            ),
            {
                "i": mid,
                "s": sohbet,
                "k": kullanici_id,
                "n": sira,
                "r": rol,
                "d": durum,
                "u": ust,
                "a": "assistant_deep" if ust else None,
                "g": gun_once,
            },
        )
    return mid


def _var(engine: Engine, tablo: str, kimlik: uuid.UUID) -> bool:
    with engine.connect() as c:
        return bool(
            c.execute(text(f"SELECT count(*) FROM {tablo} WHERE id = :i"), {"i": kimlik}).scalar()
        )


def _say(engine: Engine, sorgu: str, **p: Any) -> int:
    with engine.connect() as c:
        return int(c.execute(text(sorgu), p).scalar_one())


# ------------------------------------------------------------------ ayarlar


@pytest.mark.parametrize(
    ("ham", "beklenen"),
    [(None, 90), ("", 90), ("30", 30), ("0", 1), ("-5", 1), ("abc", 90), (" 45 ", 45)],
)
def test_saklama_gun_ortami(ham: str | None, beklenen: int) -> None:
    ortam = {} if ham is None else {"TP_ASISTAN_SAKLAMA_GUN": ham}
    assert temizlik.saklama_gun(ortam) == beklenen


@pytest.mark.parametrize(
    ("ham", "beklenen"), [(None, 21600.0), ("0", 0.0), ("60", 60.0), ("x", 21600.0)]
)
def test_aralik_ortami(ham: str | None, beklenen: float) -> None:
    ortam = {} if ham is None else {"TP_ASISTAN_TEMIZLIK_S": ham}
    assert temizlik.aralik_s(ortam) == beklenen


# ------------------------------------------------------------------ temizlik


def test_saklama_suresi_ve_kapsam(engine: Engine, make_user) -> None:
    u = make_user("analyst")
    # Eski ve etkin olmayan sohbet: tüm mesajlarıyla gider.
    eski = _sohbet(engine, u.id, gun_once=120)
    eski_m = _mesaj(engine, eski, u.id, 1, gun_once=120)
    # Yumuşak silinmiş, eski: gider.
    silinmis_eski = _sohbet(engine, u.id, gun_once=100, silindi=True, silinme_gun_once=95)
    # Yumuşak silinmiş ama yakın zamanda silinmiş: süre dolmadı, kalır.
    silinmis_yeni = _sohbet(engine, u.id, gun_once=100, silindi=True, silinme_gun_once=10)
    # Etkin sohbet: süreden eski bitmiş mesaj tek tek gider (panel "90 gün saklanır"); süresi
    # dolmamış derin çocuğu olan eski cevap çocuğuyla kalır (yarım kalmaz), sonraki koşuda gider.
    etkin = _sohbet(engine, u.id, gun_once=1)
    etkin_eski = _mesaj(engine, etkin, u.id, 1, gun_once=95, rol="assistant")
    etkin_cocuk = _mesaj(engine, etkin, u.id, 2, gun_once=89, rol="assistant", ust=etkin_eski)
    etkin_yeni = _mesaj(engine, etkin, u.id, 3, gun_once=1)
    etkin_cok_eski = _mesaj(engine, etkin, u.id, 4, gun_once=120)
    cift_ust = _mesaj(engine, etkin, u.id, 5, gun_once=100, rol="assistant")
    cift_cocuk = _mesaj(engine, etkin, u.id, 6, gun_once=99, rol="assistant", ust=cift_ust)
    # Bitmemiş çocuğu olan eski mesaj (kullanıcı başı tek bekleyen: ayrı kullanıcı ve sohbet).
    v = make_user("tester")
    v_sohbet = _sohbet(engine, v.id, gun_once=1)
    acik_cocuk_ustu = _mesaj(engine, v_sohbet, v.id, 1, gun_once=100, rol="assistant")
    acik_cocuk = _mesaj(
        engine,
        v_sohbet,
        v.id,
        2,
        gun_once=100,
        rol="assistant",
        ust=acik_cocuk_ustu,
        durum="running",
    )
    # Eski ama bekleyen mesajı olan sohbet: dokunulmaz (worker koşuyor olabilir).
    bekleyen = _sohbet(engine, u.id, gun_once=200)
    bekleyen_m = _mesaj(engine, bekleyen, u.id, 1, gun_once=200, durum="running", rol="assistant")
    # Sohbet eski görünür ama yeni mesajı var: kalır.
    mesaji_yeni = _sohbet(engine, u.id, gun_once=150)
    _mesaj(engine, mesaji_yeni, u.id, 1, gun_once=2)

    with engine.begin() as c:
        for gun in (120, 10):
            c.execute(
                text(
                    "INSERT INTO asistan_oneri_geri_bildirim (id, kullanici_id, kural_id, deger, "
                    "olusturma) VALUES (:i, :k, 'r', -1, now() - make_interval(days => :g))"
                ),
                {"i": uuid.uuid4(), "k": u.id, "g": gun},
            )
        for saat in (30, 1):
            c.execute(
                text(
                    "INSERT INTO asistan_hiz (id, kullanici_id, kova, pencere_baslangic, sayi) "
                    "VALUES (:i, :k, 'oneri_liste', now() - make_interval(hours => :s), 3)"
                ),
                {"i": uuid.uuid4(), "k": u.id, "s": saat},
            )
        # Cevap işleri: bitmiş eski satır gider; yeni bitmiş ve eski ama bitmemiş satır kalır.
        isler = {}
        for ad, durum, gun in (
            ("eski_bitmis", "done", 100),
            ("eski_dusmus", "failed", 95),
            ("yeni_bitmis", "done", 10),
            ("eski_bekleyen", "running", 100),
        ):
            isler[ad] = c.execute(
                text(
                    "INSERT INTO job (tur, yuk, durum, bitis, guncelleme) VALUES "
                    "('assistant.answer', CAST(:y AS jsonb), :d, "
                    "CASE WHEN :d = 'running' THEN NULL "
                    "ELSE now() - make_interval(days => :g) END, "
                    "now() - make_interval(days => :g)) RETURNING id"
                ),
                {"y": f'{{"kullanici_id": "{u.id}", "tetik": "kullanici"}}', "d": durum, "g": gun},
            ).scalar_one()
        # Denetim kayıtları: 200 gün önceki ai_call ve tool_call kalır.
        cid = uuid.uuid4()
        c.execute(
            text(
                "INSERT INTO ai_call (id, amac, saglayici, model, mod, maliyet, olusturma) "
                "VALUES (:i, 'assistant', 'anthropic', 'm', 'live', :m, "
                "now() - make_interval(days => 200))"
            ),
            {"i": cid, "m": Decimal("0.01")},
        )
    ai_once = _say(engine, "SELECT count(*) FROM ai_call")
    tool_once = _say(engine, "SELECT count(*) FROM tool_call")

    with Session(engine) as s, s.begin():
        sonuc = temizlik.temizle(s)

    assert sonuc == {
        "saklama_gun": 90,
        "sohbet": 2,
        "mesaj": 3,  # etkin_cok_eski, cift_ust, cift_cocuk
        "cevap_isi": 2,
        "oneri_geri_bildirim": 1,
        "hiz": 1,
    }
    assert not _var(engine, "asistan_sohbet", eski) and not _var(engine, "asistan_mesaj", eski_m)
    assert not _var(engine, "asistan_sohbet", silinmis_eski)
    assert _var(engine, "asistan_sohbet", silinmis_yeni)
    assert _var(engine, "asistan_sohbet", etkin) and _var(engine, "asistan_mesaj", etkin_yeni)
    assert _var(engine, "asistan_mesaj", etkin_eski)
    assert _var(engine, "asistan_mesaj", etkin_cocuk)
    assert not _var(engine, "asistan_mesaj", etkin_cok_eski)
    assert not _var(engine, "asistan_mesaj", cift_ust)
    assert not _var(engine, "asistan_mesaj", cift_cocuk)
    assert _var(engine, "asistan_mesaj", acik_cocuk_ustu)
    assert _var(engine, "asistan_mesaj", acik_cocuk)
    assert {ad for ad, j in isler.items() if _var(engine, "job", j)} == {
        "yeni_bitmis",
        "eski_bekleyen",
    }
    assert _var(engine, "asistan_sohbet", bekleyen) and _var(engine, "asistan_mesaj", bekleyen_m)
    assert _var(engine, "asistan_sohbet", mesaji_yeni)
    assert _say(engine, "SELECT count(*) FROM asistan_oneri_geri_bildirim") == 1
    assert _say(engine, "SELECT count(*) FROM asistan_hiz") == 1
    assert _say(engine, "SELECT count(*) FROM ai_call") == ai_once
    assert _var(engine, "ai_call", cid)
    assert _say(engine, "SELECT count(*) FROM tool_call") == tool_once


def test_iki_kademeli_zincirde_taze_torun_korunur(engine: Engine, make_user) -> None:
    """Kök → "Daha ayrıntılı" → yeniden "Daha ayrıntılı": kök ve çocuk eski olsa da 5 günlük
    torun varken kök silinmez (FK CASCADE torunu süresinden önce götürürdü)."""
    u = make_user("analyst")
    sohbet = _sohbet(engine, u.id, gun_once=1)
    kok = _mesaj(engine, sohbet, u.id, 1, gun_once=100, rol="assistant")
    cocuk = _mesaj(engine, sohbet, u.id, 2, gun_once=95, rol="assistant", ust=kok)
    torun = _mesaj(engine, sohbet, u.id, 3, gun_once=5, rol="assistant", ust=cocuk)
    # Tümü eski üç kademeli zincir ise bütünüyle gider.
    e_kok = _mesaj(engine, sohbet, u.id, 4, gun_once=130, rol="assistant")
    e_cocuk = _mesaj(engine, sohbet, u.id, 5, gun_once=120, rol="assistant", ust=e_kok)
    e_torun = _mesaj(engine, sohbet, u.id, 6, gun_once=110, rol="assistant", ust=e_cocuk)

    with Session(engine) as s, s.begin():
        sonuc = temizlik.temizle(s)

    assert all(_var(engine, "asistan_mesaj", m) for m in (kok, cocuk, torun))
    assert not any(_var(engine, "asistan_mesaj", m) for m in (e_kok, e_cocuk, e_torun))
    assert sonuc["mesaj"] >= 1


def test_korunan_kok_cevabin_sorusu_da_korunur(engine: Engine, make_user) -> None:
    """Soru (sira n) ile kök cevap (sira n+1) arasında FK yok: taze derin çocuk kök cevabı
    korurken önceki `user` sorusu da kalır; geçmişte cevap sorusuz görünmez. Tümü eski çiftte
    soru da gider."""
    u = make_user("analyst")
    sohbet = _sohbet(engine, u.id, gun_once=1)
    eski_soru = _mesaj(engine, sohbet, u.id, 1, gun_once=120)
    eski_cevap = _mesaj(engine, sohbet, u.id, 2, gun_once=120, rol="assistant")
    soru = _mesaj(engine, sohbet, u.id, 3, gun_once=95)
    kok = _mesaj(engine, sohbet, u.id, 4, gun_once=95, rol="assistant")
    cocuk = _mesaj(engine, sohbet, u.id, 5, gun_once=92, rol="assistant", ust=kok)
    torun = _mesaj(engine, sohbet, u.id, 6, gun_once=5, rol="assistant", ust=cocuk)
    # Torundan sonraki eski çift: korunan bir cevaba bağlı değil, ikisi de gider.
    yalniz_soru = _mesaj(engine, sohbet, u.id, 7, gun_once=100)
    yalniz_cevap = _mesaj(engine, sohbet, u.id, 8, gun_once=100, rol="assistant")

    with Session(engine) as s, s.begin():
        sonuc = temizlik.temizle(s)

    assert all(_var(engine, "asistan_mesaj", m) for m in (soru, kok, cocuk, torun))
    assert not any(
        _var(engine, "asistan_mesaj", m) for m in (eski_soru, eski_cevap, yalniz_soru, yalniz_cevap)
    )
    assert sonuc["mesaj"] == 4


def test_saklama_gunu_ortamdan_okunur(
    engine: Engine, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = make_user("po")
    sid = _sohbet(engine, u.id, gun_once=40)
    monkeypatch.setenv("TP_ASISTAN_SAKLAMA_GUN", "60")
    with Session(engine) as s, s.begin():
        assert temizlik.temizle(s)["sohbet"] == 0
    monkeypatch.setenv("TP_ASISTAN_SAKLAMA_GUN", "30")
    with Session(engine) as s, s.begin():
        assert temizlik.temizle(s)["sohbet"] == 1
    assert not _var(engine, "asistan_sohbet", sid)


# ------------------------------------------------------------------ periyodik iş


def test_is_kayitli_genel_seritte() -> None:
    spec = REGISTRY[temizlik.TEMIZLIK_IS_TURU]
    assert spec.serit == "genel" and spec.max_deneme == 1


def test_planla_tek_bekleyen_ve_kapali(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    say = "SELECT count(*) FROM job WHERE tur = :t AND durum IN ('queued', 'retry')"
    with engine.begin() as c:
        assert temizlik.planla(c) is not None
        assert temizlik.planla(c) is None
    assert _say(engine, say, t=temizlik.TEMIZLIK_IS_TURU) == 1
    with engine.begin() as c:
        c.execute(text("DELETE FROM job WHERE tur = :t"), {"t": temizlik.TEMIZLIK_IS_TURU})
    monkeypatch.setenv("TP_ASISTAN_TEMIZLIK_S", "0")
    with engine.begin() as c:
        assert temizlik.planla(c) is None
    assert _say(engine, say, t=temizlik.TEMIZLIK_IS_TURU) == 0


def test_worker_acilisi_planlar(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_WORKER_ASISTAN_SERIT", "0")  # şerit kapalıyken de temizlik planlanır
    with engine.begin() as c:
        asistan_jobs.on_worker_start(c)
    assert (
        _say(
            engine,
            "SELECT count(*) FROM job WHERE tur = :t AND durum = 'queued'",
            t=temizlik.TEMIZLIK_IS_TURU,
        )
        == 1
    )


def test_is_kosar_ve_kendini_yeniden_planlar(engine: Engine, make_user) -> None:
    u = make_user("tester")
    eski = _sohbet(engine, u.id, gun_once=91)
    with engine.begin() as c:
        ilk = temizlik.planla(c)
        # Önceki koşudan kalmış, 2 gün önce bitmiş kayıt silinir.
        c.execute(
            text(
                "INSERT INTO job (tur, yuk, durum, bitis) VALUES (:t, '{}'::jsonb, 'done', "
                "now() - interval '2 days')"
            ),
            {"t": temizlik.TEMIZLIK_IS_TURU},
        )
    sonuc = process_one(engine, "test-worker", turler=[temizlik.TEMIZLIK_IS_TURU])
    assert sonuc is not None
    assert not _var(engine, "asistan_sohbet", eski)
    with engine.connect() as c:
        satirlar = c.execute(
            text("SELECT id, durum, sonuc, run_after > now() FROM job WHERE tur = :t"),
            {"t": temizlik.TEMIZLIK_IS_TURU},
        ).all()
    durumlar = {r[0]: r for r in satirlar}
    assert durumlar[ilk][1] == "done"
    assert durumlar[ilk][2]["sohbet"] == 1 and durumlar[ilk][2]["is_kaydi"] == 1
    sonraki = [r for r in satirlar if r[0] != ilk]
    assert len(sonraki) == 1 and sonraki[0][1] == "queued" and sonraki[0][3] is True
