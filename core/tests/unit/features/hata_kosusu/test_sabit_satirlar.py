"""Demo uygulamanın sabitlenmiş satırları (ANALIZ §3 "Satır sabitlemeleri").

Core testleri, golden'lar ve portal bu satırlara numarasıyla atıf yapar (`campaign.py:23` …).
Ekilmiş hata işi demo uygulamaya dokunduğu için satırın hem numarası hem içeriği burada içerik
özetiyle (SHA-256, satır sonu hariç) sabitlenir: satır kayarsa ya da değişirse bu test kırılır.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parents[5]
KAYNAK = KOK / "demo-app" / "api" / "src" / "demoapp_api"

SABIT = [
    (
        "campaign.py",
        23,
        "    return adet // 6",
        "ac71e1480bb573a0dda58679ec675455fb96f40e7d04e8753306700ab20c79f3",
    ),
    (
        "pricing.py",
        94,
        "    min_aranir = not any(s.kampanyali for s in satirlar)  # kampanyalı siparişte aranmaz",
        "0d21cb41b35a585e1569a742535f56f466558a8768f9b12a5346a6cdf3ecc6d6",
    ),
    (
        "pricing.py",
        97,
        "        uyarilar.append(Uyari(UYARI_MIN_SIPARIS, min_siparis_mesaji(min_tutar)))",
        "b540c53b19b6ebed88537960169184f587a536c6055c9f8fe0c7e882b1a618a6",
    ),
    (
        "main.py",
        331,
        "def products(s: SessionDep, _bayi: BayiDep) -> list[dict]:",
        "35022fb8952c3c4346863f3ee7a9d2329a25b27001ba541819694e6edf7c74bb",
    ),
    (
        "main.py",
        450,
        "def list_orders(s: SessionDep, bayi: BayiDep) -> list[dict]:",
        "c973c3bf45c6de0184dfd8b5543b49ec78393396d3e76fa6d5fe55635c92dabd",
    ),
]


def zorunlu_mu() -> bool:
    """CI'da ya da `TP_TEST_REQUIRE_DB` verilmişse kaynak yokluğu atlama değil hatadır (t2 N13)."""
    return any((os.environ.get(ad) or "").strip() for ad in ("TP_TEST_REQUIRE_DB", "CI"))


def kaynak_gerekli(kaynak: Path = KAYNAK) -> None:
    if kaynak.exists():
        return
    mesaj = f"demo-app kaynağı yok: {kaynak}"
    if zorunlu_mu():
        pytest.fail(f"{mesaj} (CI / TP_TEST_REQUIRE_DB: sessiz atlanmaz)")
    pytest.skip(mesaj)


@pytest.mark.parametrize(("dosya", "satir", "metin", "ozet"), SABIT)
def test_sabit_satir_numarasi_ve_icerigi_degismez(
    dosya: str, satir: int, metin: str, ozet: str
) -> None:
    kaynak_gerekli()
    satirlar = (KAYNAK / dosya).read_text(encoding="utf-8").splitlines()
    assert len(satirlar) >= satir, f"{dosya} {satir} satırdan kısa"
    gercek = satirlar[satir - 1]
    assert gercek == metin, f"{dosya}:{satir} değişti: {gercek!r}"
    assert hashlib.sha256(gercek.encode("utf-8")).hexdigest() == ozet


def test_kaynak_yoksa_zorunlu_ortamda_basarisiz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yok = tmp_path / "yok"
    for ad in ("TP_TEST_REQUIRE_DB", "CI"):
        monkeypatch.delenv(ad, raising=False)
    with pytest.raises(pytest.skip.Exception):
        kaynak_gerekli(yok)
    for ad in ("TP_TEST_REQUIRE_DB", "CI"):
        monkeypatch.setenv(ad, "1")
        with pytest.raises(pytest.fail.Exception):
            kaynak_gerekli(yok)
        monkeypatch.delenv(ad)
