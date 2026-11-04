"""Asistan şeridi, işleyici, kalp atışı, uzlaştırma ve yarış korumaları (AI-ASISTAN-PLANI §10.1, §13
"Worker").

Uçtan uca şerit testleri `test_worker_seritler` desenindedir: olay (Event) tabanlı bekleme, gerçek
Postgres, `worker.run` ayrı iş parçacığında. Asistan mantığı (`flow.cevapla`) burada sahte
işleyicilerle temsil edilir; sözlük/şablon/canlı akış testleri akış şeridindedir.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from tp_core import worker
from tp_core.features.assistant import durum
from tp_core.features.assistant import jobs as asistan_jobs
from tp_core.gateway.errors import BudgetExceeded
from tp_core.workflow import jobs
from tp_core.workflow.jobs import (
    ASISTAN_SERIT,
    UZUN_SERIT,
    HandlerSpec,
    JobContext,
    PermanentJobError,
    enqueue,
    job_handler,
    process_one,
    serit_turleri,
    uzun_turler,
)

ASISTAN_TUR = "assistant.answer"


@pytest.fixture(scope="module", autouse=True)
def _kayit_temizligi() -> Iterator[None]:
    """Bu modülün içe aktardığı `assistant.answer` kaydı diğer modüllerin `worker.run`
    testlerine asistan şeridi açtırmasın (kayıt süreç genelidir)."""
    yield
    if (spec := jobs.REGISTRY.get(ASISTAN_TUR)) is not None and spec.fn is asistan_jobs.answer:
        jobs.REGISTRY.pop(ASISTAN_TUR, None)


@pytest.fixture(autouse=True)
def _ortam(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_WORKER_LIVENESS_FILE", str(tmp_path / "canli"))
    monkeypatch.setenv("TP_WORKER_STATE_FILE", str(tmp_path / "surec"))
    monkeypatch.setenv("TP_BILGI_DIZIN", str(tmp_path / "bilgi-yok"))
    for ad in (
        "ANTHROPIC_API_KEY",
        "TP_ASISTAN_MODEL_MODE",
        "TP_ASISTAN_MUSTERI_VERISI",
        "TP_PII_MASKING",
        "TP_WORKER_ASISTAN_SERIT",
        "TP_WORKER_ASISTAN_PARALEL",
    ):
        monkeypatch.delenv(ad, raising=False)
    monkeypatch.setattr(worker, "_son_uzlastirma", 0.0)
    monkeypatch.setattr(worker, "UZLASTIRMA_ARALIGI_S", 0.0)


def _sahte_anahtar() -> str:
    # Gerçek biçimli sır repoya yazılmaz; çalışma anında birleştirilir.
    return "sk-" + "ant-" + "test-" + "x" * 24


def _bekle(kosul, sure: float = 10.0) -> bool:
    son = time.monotonic() + sure
    while time.monotonic() < son:
        if kosul():
            return True
        time.sleep(0.02)
    return False


def _is_durumu(engine: Engine, job_id: uuid.UUID) -> str:
    with engine.connect() as c:
        return c.execute(text("SELECT durum FROM job WHERE id = :i"), {"i": job_id}).scalar_one()


def _mesaj(engine: Engine, mesaj_id: uuid.UUID) -> dict:
    with engine.connect() as c:
        return dict(
            c.execute(text("SELECT * FROM asistan_mesaj WHERE id = :i"), {"i": mesaj_id})
            .mappings()
            .one()
        )


def _mesaj_ekle(
    engine: Engine,
    kullanici_id: uuid.UUID,
    *,
    durum_: str = "pending",
    job_id: uuid.UUID | None = None,
    yas_s: int = 0,
) -> uuid.UUID:
    sohbet_id, mesaj_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as c:
        c.execute(
            text("INSERT INTO asistan_sohbet (id, kullanici_id) VALUES (:s, :k)"),
            {"s": sohbet_id, "k": kullanici_id},
        )
        c.execute(
            text(
                "INSERT INTO asistan_mesaj (id, sohbet_id, kullanici_id, sira, rol, icerik, "
                "durum, job_id, olusturma) VALUES (:m, :s, :k, 2, 'assistant', NULL, :d, :j, "
                "now() - make_interval(secs => :yas))"
            ),
            {"m": mesaj_id, "s": sohbet_id, "k": kullanici_id, "d": durum_, "j": job_id,
             "yas": yas_s},
        )  # fmt: skip
    return mesaj_id


def _is_ve_mesaj(engine: Engine, kullanici_id: uuid.UUID, tur: str) -> tuple[uuid.UUID, uuid.UUID]:
    with engine.begin() as c:
        jid = enqueue(c, tur, {"mesaj_id": "", "kullanici_id": str(kullanici_id)})
    mid = _mesaj_ekle(engine, kullanici_id, job_id=jid)
    with engine.begin() as c:
        c.execute(
            text("UPDATE job SET yuk = jsonb_set(yuk, '{mesaj_id}', to_jsonb(CAST(:m AS text))) "
                 "WHERE id = :j"),
            {"m": str(mid), "j": jid},
        )  # fmt: skip
    return jid, mid


def _durum_satiri(engine: Engine) -> dict | None:
    with engine.connect() as c:
        row = c.execute(text("SELECT * FROM asistan_durum WHERE id = 1")).mappings().first()
    return dict(row) if row else None


# ------------------------------------------------------------------ şerit kaydı


def test_asistan_seridi_kaydi_ve_serit_turleri() -> None:
    reg: dict[str, HandlerSpec] = {}
    job_handler("a.cevap", registry=reg, serit=ASISTAN_SERIT)(lambda _c: None)
    job_handler("a.uzun", registry=reg, serit=UZUN_SERIT)(lambda _c: None)
    job_handler("a.genel", registry=reg)(lambda _c: None)
    assert serit_turleri(ASISTAN_SERIT, registry=reg) == frozenset({"a.cevap"})
    assert serit_turleri(UZUN_SERIT, [" ek "], reg) == frozenset({"a.uzun", "ek"})
    assert uzun_turler(registry=reg) == frozenset({"a.uzun"})
    with pytest.raises(ValueError):
        serit_turleri("hizli", registry=reg)
    with pytest.raises(ValueError):
        job_handler("a.x", registry=reg, serit="hizli")


def test_assistant_answer_kaydi() -> None:
    spec = jobs.REGISTRY[ASISTAN_TUR]
    assert spec.fn is asistan_jobs.answer
    assert (spec.serit, spec.max_deneme, spec.zaman_asimi_s) == (ASISTAN_SERIT, 1, 120)


def test_asistan_serit_yapilandirmasi(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ASISTAN_TUR in worker.asistan_serit_turleri()  # varsayılan açık
    assert worker.asistan_paralel() == 3
    monkeypatch.setenv("TP_WORKER_ASISTAN_PARALEL", "5")
    assert worker.asistan_paralel() == 5
    monkeypatch.setenv("TP_WORKER_ASISTAN_PARALEL", "abc")
    assert worker.asistan_paralel() == 3
    monkeypatch.setenv("TP_WORKER_ASISTAN_SERIT", "0")
    assert worker.asistan_serit_turleri() == frozenset()


# ------------------------------------------------------------------ servis durumu


@pytest.mark.parametrize(
    ("anahtar", "mod", "musteri", "maske", "beklenen"),
    [
        (True, "live", False, False, True),
        (True, "live", True, True, True),
        (True, "live", True, False, False),  # müşteri verisi + maskeleme kapalı → canlı yok
        (False, "live", False, False, False),
        (True, "off", False, True, False),
    ],
)
def test_model_hazir_kurali(anahtar, mod, musteri, maske, beklenen) -> None:
    assert (
        durum.model_hazir_mi(anahtar_var=anahtar, mod=mod, musteri_verisi=musteri, maskeleme=maske)
        is beklenen
    )


def test_durum_hesapla_ortamdan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert durum.durum_hesapla() == durum.AsistanDurumu("off", False, False, False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", _sahte_anahtar())
    monkeypatch.setenv("TP_ASISTAN_MODEL_MODE", "LIVE")
    assert durum.durum_hesapla().model_hazir is True
    monkeypatch.setenv("TP_ASISTAN_MUSTERI_VERISI", "1")
    d = durum.durum_hesapla()
    assert (d.musteri_verisi, d.maskeleme, d.model_hazir) == (True, False, False)
    monkeypatch.setenv("TP_PII_MASKING", "1")
    assert durum.durum_hesapla().model_hazir is True
    monkeypatch.setenv("TP_ASISTAN_MODEL_MODE", "record")  # bilinmeyen → off
    assert durum.durum_hesapla().mod == "off"
    # bilgi paketi MANIFEST'i
    kok = tmp_path / "bilgi"
    (kok / "surumler" / "v1").mkdir(parents=True)
    (kok / "MANIFEST.json").write_text(
        json.dumps({"surum": 1, "commit": "abc123", "uretim": "2026-11-03T10:00:00+00:00",
                    "dizin": "surumler/v1", "dosyalar": {}})
    )  # fmt: skip
    monkeypatch.setenv("TP_BILGI_DIZIN", str(kok))
    d = durum.durum_hesapla()
    assert d.paket_commit == "abc123" and d.paket_uretim is not None


def test_durum_yaz_ve_kalp_atisi(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _durum_satiri(engine) is None
    durum.kalp_atisi_yaz(engine)
    ilk = _durum_satiri(engine)
    assert ilk is not None and ilk["mod"] == "off" and ilk["model_hazir"] is False
    assert ilk["kalp_atisi"] is not None
    monkeypatch.setenv("ANTHROPIC_API_KEY", _sahte_anahtar())
    monkeypatch.setenv("TP_ASISTAN_MODEL_MODE", "live")
    time.sleep(0.01)
    durum.kalp_atisi_yaz(engine)
    ikinci = _durum_satiri(engine)
    assert ikinci["mod"] == "live" and ikinci["model_hazir"] is True
    assert ikinci["kalp_atisi"] > ilk["kalp_atisi"]
    with engine.connect() as c:
        assert durum.model_hazir_oku(c) is True
        assert c.execute(text("SELECT count(*) FROM asistan_durum")).scalar_one() == 1


def test_on_worker_start_bayraga_uyar(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_WORKER_ASISTAN_SERIT", "0")
    with engine.begin() as c:
        asistan_jobs.on_worker_start(c)
    assert _durum_satiri(engine) is None  # şerit kapalı → kalp atışı yok (worker_yok)
    monkeypatch.delenv("TP_WORKER_ASISTAN_SERIT")
    with engine.begin() as c:
        asistan_jobs.on_worker_start(c)
    assert _durum_satiri(engine) is not None


# ------------------------------------------------------------------ yarış korumaları


def test_yaris_korumalari(engine: Engine, make_user) -> None:
    u = make_user("analyst")
    mid = _mesaj_ekle(engine, u.id)
    with engine.begin() as c:
        assert durum.durdurulmali(c, mid) is True  # henüz running değil
        assert durum.sonuc_yaz(c, mid, durum="done") is False  # pending'e sonuç yazılmaz
        assert durum.baslat(c, mid) is True
        assert durum.baslat(c, mid) is False  # ikinci kez başlatılmaz
        assert durum.durdurulmali(c, mid) is False
    assert durum.durdurma_kontrolu(engine, mid)() is False
    # iptal (API) → geç biten iş sonucu ezmez ama harcamayı yazar
    with engine.begin() as c:
        c.execute(text("UPDATE asistan_mesaj SET durum = 'iptal' WHERE id = :i"), {"i": mid})
    assert durum.durdurma_kontrolu(engine, mid)() is True
    with engine.begin() as c:
        assert durum.sonuc_yaz(c, mid, durum="done", cevap={"metin": "x"}, kaynak="model") is False
        assert durum.harcama_yaz(
            c, mid, maliyet_usd=Decimal("0.0123"), token_girdi=100, token_cikti=20, sure_ms=900
        )
    m = _mesaj(engine, mid)
    assert (m["durum"], m["cevap"], m["kaynak"]) == ("iptal", None, None)
    assert (m["maliyet_usd"], m["token_girdi"], m["token_cikti"], m["sure_ms"]) == (
        Decimal("0.0123"), 100, 20, 900,
    )  # fmt: skip
    with pytest.raises(ValueError), engine.begin() as c:
        durum.sonuc_yaz(c, mid, icerik="soru metni yazılamaz")


def test_sonuc_yaz_running_iken_ve_tamamlanma(engine: Engine, make_user) -> None:
    u = make_user("tester")
    mid = _mesaj_ekle(engine, u.id, durum_="running")
    with engine.begin() as c:
        assert durum.sonuc_yaz(c, mid, durum="done", cevap={"metin": "ok"}, kaynak="sozluk")
        assert durum.harcama_yaz(c, mid) is False  # boş harcama yazılmaz
        assert durum.hata_yaz(c, mid, durum.HATA_MODEL) is False  # done'a hata yazılmaz
    m = _mesaj(engine, mid)
    assert m["durum"] == "done" and m["cevap"] == {"metin": "ok"} and m["tamamlanma"] is not None
    with engine.begin() as c:
        assert durum.harcama_yaz(c, mid, sure_ms=5) is False  # done → harcama da kapalı


# ------------------------------------------------------------------ uzlaştırma


def test_uzlastirma(engine: Engine, make_user) -> None:
    reg_tur = f"t.uz.{uuid.uuid4().hex[:6]}"
    job_handler(reg_tur, max_deneme=1)(lambda _c: None)
    try:
        kullanicilar = [make_user("analyst") for _ in range(6)]
        with engine.begin() as c:
            is_ids = {d: enqueue(c, reg_tur) for d in ("queued", "running", "failed", "done")}
            c.execute(text("UPDATE job SET durum = 'running' WHERE id = :i"),
                      {"i": is_ids["running"]})  # fmt: skip
            c.execute(text("UPDATE job SET durum = 'failed' WHERE id = :i"),
                      {"i": is_ids["failed"]})  # fmt: skip
            c.execute(text("UPDATE job SET durum = 'done' WHERE id = :i"), {"i": is_ids["done"]})
        kuyrukta = _mesaj_ekle(engine, kullanicilar[0].id, job_id=is_ids["queued"])
        kosan = _mesaj_ekle(engine, kullanicilar[1].id, durum_="running", job_id=is_ids["running"])
        basarisiz = _mesaj_ekle(engine, kullanicilar[2].id, durum_="running",
                                job_id=is_ids["failed"])  # fmt: skip
        bitmis_is = _mesaj_ekle(engine, kullanicilar[3].id, job_id=is_ids["done"])
        yok_eski = _mesaj_ekle(engine, kullanicilar[4].id, job_id=uuid.uuid4())
        issiz_taze = _mesaj_ekle(engine, kullanicilar[5].id, job_id=None)
        with engine.begin() as c:
            kapanan = set(durum.uzlastir(c))
        assert kapanan == {basarisiz, bitmis_is, yok_eski}
        for mid in kapanan:
            m = _mesaj(engine, mid)
            assert (m["durum"], m["hata_kodu"]) == ("error", "zaman_asimi")
            assert m["tamamlanma"] is not None
        assert _mesaj(engine, kuyrukta)["durum"] == "pending"
        assert _mesaj(engine, kosan)["durum"] == "running"
        assert _mesaj(engine, issiz_taze)["durum"] == "pending"  # taze, işsiz: dokunulmaz
        # eski işsiz mesaj kapanır
        with engine.begin() as c:
            c.execute(text("UPDATE asistan_mesaj SET olusturma = now() - interval '2 minutes' "
                           "WHERE id = :i"), {"i": issiz_taze})  # fmt: skip
            assert durum.uzlastir(c) == [issiz_taze]
            assert durum.uzlastir(c) == []  # idempotent
    finally:
        jobs.REGISTRY.pop(reg_tur, None)


def test_zaman_asimi_uzlastirilan_mesaja_harcama_yazilir(engine: Engine, make_user) -> None:
    """Asılı iş uzlaştırmadan sonra bittiğinde harcaması `asistan_mesaj`'a da yazılır; başka
    hata koduyla kapanmış mesaja yazılmaz."""
    u = make_user("engineer")
    asili = _mesaj_ekle(engine, u.id, durum_="running", job_id=uuid.uuid4())  # iş yok → uzlaşır
    with engine.begin() as c:
        assert durum.uzlastir(c) == [asili]
        assert durum.sonuc_yaz(c, asili, durum="done", cevap={"metin": "geç"}) is False
        assert durum.harcama_yaz(
            c, asili, maliyet_usd=Decimal("0.02"), token_girdi=50, token_cikti=7, sure_ms=130000
        )
    m = _mesaj(engine, asili)
    assert (m["durum"], m["hata_kodu"], m["cevap"]) == ("error", "zaman_asimi", None)
    assert (m["maliyet_usd"], m["token_girdi"], m["token_cikti"], m["sure_ms"]) == (
        Decimal("0.02"), 50, 7, 130000,
    )  # fmt: skip
    diger = _mesaj_ekle(engine, u.id, durum_="running")
    with engine.begin() as c:
        assert durum.hata_yaz(c, diger, durum.HATA_MODEL)
        assert durum.harcama_yaz(c, diger, sure_ms=5) is False


# ------------------------------------------------------------------ işleyici


def _ctx(mesaj_id: object) -> JobContext:
    return JobContext(uuid.uuid4(), ASISTAN_TUR, {"mesaj_id": str(mesaj_id)}, 1, 1)


def test_isleyici_flow_cevapla_cagirir(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    cagrilar: list[tuple] = []

    def sahte(session_factory, mesaj_id, *, gateway_factory=None) -> None:
        with session_factory() as s:
            assert s.execute(text("SELECT 1")).scalar_one() == 1
        cagrilar.append((mesaj_id, gateway_factory))

    monkeypatch.setattr(asistan_jobs.flow, "cevapla", sahte)
    mid = uuid.uuid4()
    assert asistan_jobs.answer(_ctx(mid)) == {"mesaj_id": str(mid)}
    assert cagrilar == [(mid, None)]


def test_isleyici_gecersiz_yuk() -> None:
    with pytest.raises(PermanentJobError):
        asistan_jobs.answer(JobContext(uuid.uuid4(), ASISTAN_TUR, {}, 1, 1))
    with pytest.raises(PermanentJobError):
        asistan_jobs.answer(_ctx("degil-uuid"))


@pytest.mark.parametrize(
    ("istisna", "kod"),
    [
        (RuntimeError("gizli soru metni ali@ornek.com"), "model_hatasi"),
        (BudgetExceeded("gizli-kapsam", 1.5, 1.0), "butce_asildi"),
    ],
)
def test_isleyici_istisnasi_mesaji_kapatir_ve_ayrinti_yazmaz(
    engine: Engine, make_user, monkeypatch: pytest.MonkeyPatch, istisna, kod
) -> None:
    def patla(*_a, **_k) -> None:
        raise istisna

    monkeypatch.setattr(asistan_jobs.flow, "cevapla", patla)
    u = make_user("analyst")
    jid, mid = _is_ve_mesaj(engine, u.id, ASISTAN_TUR)
    sonuc = process_one(engine, "w", turler=[ASISTAN_TUR])
    assert sonuc is not None and sonuc.durum == "failed"
    assert "gizli" not in (sonuc.hata or "") and "@" not in (sonuc.hata or "")
    with engine.connect() as c:
        hata = c.execute(text("SELECT son_hata FROM job WHERE id = :i"), {"i": jid}).scalar_one()
    assert "gizli" not in hata and kod in hata
    m = _mesaj(engine, mid)
    assert (m["durum"], m["hata_kodu"]) == ("error", kod)


# ------------------------------------------------------------------ uçtan uca şerit


def _kaydet(tur: str, fn, **kw) -> None:
    job_handler(tur, max_deneme=1, serit=ASISTAN_SERIT, **kw)(fn)


def _calistir(dur: threading.Event, uzun: set[str] | None = None) -> tuple[threading.Thread, list]:
    sonuc: list[int] = []
    t = threading.Thread(
        target=lambda: sonuc.append(worker.run(dur, aralik=0.02, uzun=uzun)), daemon=True
    )
    t.start()
    return t, sonuc


def test_uzun_is_bloke_iken_asistan_isi_biter(engine: Engine) -> None:
    ek = uuid.uuid4().hex[:6]
    uzun_tur, a_tur = f"t.ci.{ek}", f"t.as.{ek}"
    basladi, serbest = threading.Event(), threading.Event()

    def uzun_is(_c) -> None:
        basladi.set()
        assert serbest.wait(10)

    job_handler(uzun_tur, max_deneme=1, zaman_asimi_s=30)(uzun_is)
    _kaydet(a_tur, lambda _c: None, zaman_asimi_s=30)
    dur = threading.Event()
    try:
        with engine.begin() as c:
            uzun_id = enqueue(c, uzun_tur)
        t, sonuc = _calistir(dur, {uzun_tur})
        assert basladi.wait(10)
        with engine.begin() as c:
            a_id = enqueue(c, a_tur)
        assert _bekle(lambda: _is_durumu(engine, a_id) == "done")
        assert _is_durumu(engine, uzun_id) == "running"
        serbest.set()
        assert _bekle(lambda: _is_durumu(engine, uzun_id) == "done")
    finally:
        serbest.set()
        dur.set()
        jobs.REGISTRY.pop(uzun_tur, None)
        jobs.REGISTRY.pop(a_tur, None)
    t.join(timeout=10)
    assert sonuc == [0]
    assert worker._genel_haric is None


def test_uc_is_parcacigi_ayni_isi_iki_kez_almaz_ve_bloke_is_digerlerini_durdurmaz(
    engine: Engine,
) -> None:
    ek = uuid.uuid4().hex[:6]
    a_tur, bloke_tur = f"t.as.{ek}", f"t.asb.{ek}"
    alinanlar: list[str] = []
    kilit = threading.Lock()
    engel = threading.Barrier(3, timeout=10)  # üç iş aynı anda koşmalı
    serbest = threading.Event()

    def is_(c: JobContext) -> None:
        with kilit:
            alinanlar.append(str(c.job_id))
        engel.wait()

    def bloke(_c) -> None:
        assert serbest.wait(15)

    _kaydet(a_tur, is_, zaman_asimi_s=30)
    _kaydet(bloke_tur, bloke, zaman_asimi_s=30)
    dur = threading.Event()
    try:
        with engine.begin() as c:
            ids = [enqueue(c, a_tur) for _ in range(3)]
        t, sonuc = _calistir(dur)
        assert _bekle(lambda: all(_is_durumu(engine, i) == "done" for i in ids))
        # Engel üç işin aynı anda koştuğunu kanıtlar; her iş tam bir kez alındı.
        assert sorted(alinanlar) == sorted(str(i) for i in ids)
        # Bir asistan işi bloke iken diğerleri bitmeye devam eder.
        with engine.begin() as c:
            bloke_id = enqueue(c, bloke_tur)
        assert _bekle(lambda: _is_durumu(engine, bloke_id) == "running")
        tekli_tur = f"t.ast.{ek}"
        _kaydet(tekli_tur, lambda _c: None, zaman_asimi_s=30)
        with engine.begin() as c:
            digerleri = [enqueue(c, tekli_tur) for _ in range(4)]
        assert _bekle(lambda: all(_is_durumu(engine, i) == "done" for i in digerleri))
        assert _is_durumu(engine, bloke_id) == "running"
        serbest.set()
        assert _bekle(lambda: _is_durumu(engine, bloke_id) == "done")
    finally:
        serbest.set()
        dur.set()
        for tur in (a_tur, bloke_tur, f"t.ast.{ek}"):
            jobs.REGISTRY.pop(tur, None)
    t.join(timeout=10)
    assert sonuc == [0]


def test_asistan_zaman_asimi_sureci_kapatmaz_ve_mesaj_uzlastirilir(
    engine: Engine, make_user
) -> None:
    ek = uuid.uuid4().hex[:6]
    a_tur, genel_tur = f"t.asz.{ek}", f"t.gen.{ek}"
    serbest = threading.Event()
    _kaydet(a_tur, lambda _c: serbest.wait(8), zaman_asimi_s=1)
    job_handler(genel_tur, max_deneme=1)(lambda _c: None)
    dur = threading.Event()
    u = make_user("analyst")
    try:
        jid, mid = _is_ve_mesaj(engine, u.id, a_tur)
        with engine.begin() as c:
            c.execute(text("UPDATE asistan_mesaj SET durum = 'running' WHERE id = :i"), {"i": mid})
        t, sonuc = _calistir(dur)
        assert _bekle(lambda: _is_durumu(engine, jid) == "failed")
        assert _bekle(lambda: _mesaj(engine, mid)["durum"] == "error")
        assert _mesaj(engine, mid)["hata_kodu"] == "zaman_asimi"
        # süreç yaşıyor: yeni işler işlenir
        time.sleep(0.2)
        assert t.is_alive() and sonuc == []
        with engine.begin() as c:
            g_id = enqueue(c, genel_tur)
        assert _bekle(lambda: _is_durumu(engine, g_id) == "done")
        # asılı iş parçacığı geç bitse de sonucu yazamaz
        with engine.begin() as c:
            assert durum.sonuc_yaz(c, mid, durum="done", cevap={"metin": "geç"}) is False
    finally:
        serbest.set()
        dur.set()
        jobs.REGISTRY.pop(a_tur, None)
        jobs.REGISTRY.pop(genel_tur, None)
    t.join(timeout=10)
    assert sonuc == [0]


def test_uzun_seritte_zaman_asimi_sureci_hala_durdurur(engine: Engine) -> None:
    """Asistan şeridi açıkken de uzun/genel şeritte zaman aşımı süreci kapatır."""
    ek = uuid.uuid4().hex[:6]
    tur = f"t.asili.{ek}"
    serbest = threading.Event()
    job_handler(tur, max_deneme=1, zaman_asimi_s=1)(lambda _c: serbest.wait(6))
    try:
        assert worker.asistan_serit_turleri()  # asistan şeridi de açık
        with engine.begin() as c:
            jid = enqueue(c, tur)
        t0 = time.monotonic()
        kod = worker.run(threading.Event(), aralik=0.02, uzun={tur})
        assert kod == worker.ZAMAN_ASIMI_CIKIS_KODU
        assert time.monotonic() - t0 < 8
        assert _is_durumu(engine, jid) == "failed"
    finally:
        serbest.set()
        jobs.REGISTRY.pop(tur, None)


def test_kalp_atisi_serit_bloke_iken_yazar(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "KALP_ATISI_ARALIGI_S", 0.1)
    monkeypatch.setenv("TP_WORKER_ASISTAN_PARALEL", "1")
    ek = uuid.uuid4().hex[:6]
    a_tur = f"t.askb.{ek}"
    basladi, serbest = threading.Event(), threading.Event()

    def bloke(_c) -> None:
        basladi.set()
        assert serbest.wait(10)

    _kaydet(a_tur, bloke, zaman_asimi_s=30)
    dur = threading.Event()
    try:
        with engine.begin() as c:
            enqueue(c, a_tur)
        t, sonuc = _calistir(dur)
        assert basladi.wait(10)  # tek asistan iş parçacığı bloke
        assert _bekle(lambda: _durum_satiri(engine) is not None)
        ilk = _durum_satiri(engine)["kalp_atisi"]
        assert _bekle(lambda: _durum_satiri(engine)["kalp_atisi"] > ilk)
    finally:
        serbest.set()
        dur.set()
        jobs.REGISTRY.pop(a_tur, None)
    t.join(timeout=10)
    assert sonuc == [0]


def test_asistan_seridi_kapaliyken_kalp_atisi_ve_serit_yok(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_WORKER_ASISTAN_SERIT", "0")
    monkeypatch.setattr(worker, "KALP_ATISI_ARALIGI_S", 0.05)
    monkeypatch.setattr(worker, "_son_kapali_temizlik", 0.0)
    ek = uuid.uuid4().hex[:6]
    a_tur = f"t.askap.{ek}"
    _kaydet(a_tur, lambda _c: None, zaman_asimi_s=30)
    haricler: list[list[str] | None] = []
    gercek = worker.tek_tur

    def izle() -> bool:
        haricler.append(worker._genel_haric)
        return gercek()

    monkeypatch.setattr(worker, "tek_tur", izle)
    dur = threading.Event()
    try:
        with engine.begin() as c:
            a_id = enqueue(c, a_tur)
            # Temizlik yalnız eşikten eski işi kapatır (yeni kabul edilen iş korunur).
            c.execute(
                text("UPDATE job SET olusturma = now() - interval '1 hour' WHERE id = :i"),
                {"i": a_id},
            )
        t, sonuc = _calistir(dur)
        # Şerit kapalı: tür genel döngüde de koşmaz (haric'te; orada zaman aşımı süreci
        # kapatırdı); kalp atışı yazılmaz. Kalp atışı olmadığından genel şerit bekleyen işi
        # süresiz `queued` bırakmaz, `cancelled` yapar (kapali_serit_temizle).
        assert _bekle(lambda: len(haricler) >= 3)
        assert _bekle(lambda: _is_durumu(engine, a_id) == "cancelled")
        assert _durum_satiri(engine) is None
        assert all(h is not None and a_tur in h for h in haricler)
    finally:
        dur.set()
        jobs.REGISTRY.pop(a_tur, None)
    t.join(timeout=10)
    assert sonuc == [0]
