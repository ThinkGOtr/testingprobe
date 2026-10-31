"""Runner rapor okuma: sembolik bağ / aygıt / FIFO / boyut sınırı (RUN_LOCK tutarken bloklanmaz)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from runner.results import safe_read_bytes, summarize


def test_results_json_dev_zero_bagi_bloklamaz(tmp_path: Path) -> None:
    rj = tmp_path / "results.json"
    rj.symlink_to("/dev/zero")
    with pytest.raises(ValueError, match="okunamadı"):
        summarize(rj, tmp_path)


def test_results_json_disari_bag_okunmaz(tmp_path: Path) -> None:
    dis = tmp_path.parent / f"{tmp_path.name}-dis.json"
    dis.write_text('{"stats": {}, "suites": []}', encoding="utf-8")
    rj = tmp_path / "results.json"
    rj.symlink_to(dis)
    with pytest.raises(ValueError, match="sembolik"):
        summarize(rj, tmp_path)


def test_fifo_ve_boyut_siniri(tmp_path: Path) -> None:
    fifo = tmp_path / "f"
    os.mkfifo(fifo)
    with pytest.raises(OSError, match="düzenli"):
        safe_read_bytes(fifo, 10)
    buyuk = tmp_path / "b"
    buyuk.write_bytes(b"x" * 11)
    with pytest.raises(ValueError, match="büyük"):
        safe_read_bytes(buyuk, 10)
    assert safe_read_bytes(buyuk, 11) == b"x" * 11


def test_normal_rapor_okunur(tmp_path: Path) -> None:
    rj = tmp_path / "results.json"
    rj.write_text('{"stats": {"expected": 2}, "suites": []}', encoding="utf-8")
    assert summarize(rj, tmp_path)["stats"]["expected"] == 2
