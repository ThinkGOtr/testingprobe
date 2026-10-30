import threading

import pytest

from tp_core import worker
from tp_core.worker import GecersizGecis, calistir, gecis


@pytest.mark.parametrize(
    ("mevcut", "hedef"),
    [("queued", "running"), ("running", "done"), ("running", "failed")],
)
def test_izinli_gecisler(mevcut: str, hedef: str) -> None:
    assert gecis(mevcut, hedef) == hedef


@pytest.mark.parametrize(
    ("mevcut", "hedef"),
    [
        ("queued", "done"),
        ("done", "running"),
        ("failed", "queued"),
        ("running", "queued"),
        ("x", "running"),
    ],
)
def test_yasak_gecisler(mevcut: str, hedef: str) -> None:
    with pytest.raises(GecersizGecis):
        gecis(mevcut, hedef)


def test_noop_done() -> None:
    sonuc = calistir("noop", None)
    assert (sonuc.durum, sonuc.deneme_artisi, sonuc.hata) == ("done", 0, None)


def test_hata_failed_ve_deneme_artar() -> None:
    def patla(_: object) -> None:
        raise RuntimeError("boom")

    sonuc = calistir("noop", {}, handlers={"noop": patla})
    assert (sonuc.durum, sonuc.deneme_artisi, sonuc.hata) == ("failed", 1, "boom")


def test_bilinmeyen_tur_failed() -> None:
    assert calistir("bilinmez", None).durum == "failed"


def test_run_durdurma_olayinda_cikar(monkeypatch: pytest.MonkeyPatch) -> None:
    dur = threading.Event()
    turlar: list[int] = []

    def tek_tur() -> bool:
        turlar.append(1)
        dur.set()
        return False

    monkeypatch.setattr(worker, "tek_tur", tek_tur)
    worker.run(dur, aralik=0.01)
    assert turlar == [1]
