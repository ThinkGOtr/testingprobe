"""011 K15: iki tur (tasarım modeli → analist onayı → case), otomatik review, denetim kapısı."""

from __future__ import annotations

from typing import Any

import pytest

from tp_rehearsal import steps
from tp_rehearsal.runner import PASS, Basarisiz

RID = "r1"


class Api:
    """Yol → yanıt (çağrılabilir: her okumada yeniden); POST'lar kaydedilir."""

    def __init__(self, yanitlar: dict[str, Any], postlar: dict[str, Any] | None = None) -> None:
        self.yanitlar = yanitlar
        self.post_yanitlari = postlar or {}
        self.postlar: list[tuple[str, str, Any]] = []

    def get(self, rol: str, yol: str) -> Any:
        y = self.yanitlar[yol]
        return y() if callable(y) else y

    def post(self, rol, yol, govde=None, beklenen=(200, 202)):
        self.postlar.append((rol, yol, govde))
        y = self.post_yanitlari.get(yol, {})
        return y() if callable(y) else y


def _model(durum: str = "draft", **ek: Any) -> dict[str, Any]:
    return {
        "id": "m1",
        "surum": 1,
        "durum": durum,
        "icerik_hash": "h1",
        "onaylanan_hash": "h1" if durum == "approved" else None,
        "uretim_modu": "replay",
        "sorunlar": [],
        "ozet": {"oge": steps.MODEL_OGE_SAYISI},
        "kararlar": [{"karar": "approve", "kullanici": "analist"}] if durum == "approved" else [],
        **ek,
    }


def _hazir(b, api):
    b.veri.update(req_id=RID, izinli_modlar={"replay"})
    b.api = api
    return b


def test_model_uret_iki_tur_govdesi_ve_kontroller(baglam):
    api = Api(
        {
            f"/requirements/{RID}": {"durum": "model_ready"},
            f"/requirements/{RID}/design-model": {
                "model": _model(),
                "case_uretimi_hazir": False,
                "engel": "Onaylı tasarım modeli yok",
            },
        },
        {f"/requirements/{RID}/generate-cases": {"kip": "iki_tur", "asama": "model"}},
    )
    b = _hazir(baglam(), api)
    steps.model_uret(b)
    assert api.postlar == [("analist", f"/requirements/{RID}/generate-cases", {"kip": "iki_tur"})]
    assert {k.sonuc for k in b.kontroller} == {PASS}
    assert b.veri["model"]["id"] == "m1"


def test_model_uret_oge_sayisi_sapinca_fail(baglam):
    api = Api(
        {
            f"/requirements/{RID}": {"durum": "model_ready"},
            f"/requirements/{RID}/design-model": {
                "model": _model(ozet={"oge": 17}),
                "case_uretimi_hazir": False,
            },
        },
        {f"/requirements/{RID}/generate-cases": {"kip": "iki_tur", "asama": "model"}},
    )
    with pytest.raises(Basarisiz, match="21 kapsam öğesi"):
        steps.model_uret(_hazir(baglam(), api))


def test_model_onayi_hash_ile_onaylar(baglam):
    durum = {"m": _model()}

    def onay():
        durum["m"] = _model("approved")
        # 011 K20: onay yanıtı tur 2'nin kendiliğinden başladığını söyler.
        return {
            "durum": "approved",
            "tur2_baslatildi": True,
            "tur2": {"kip": "iki_tur", "asama": "case", "uretim_no": 1},
            "tur2_engeli": None,
        }

    api = Api(
        {
            f"/requirements/{RID}/design-model": lambda: {
                "model": durum["m"],
                "case_uretimi_hazir": durum["m"]["durum"] == "approved",
            }
        },
        {"/design-models/m1/decision": onay},
    )
    b = _hazir(baglam(), api)
    b.veri["model"] = _model()
    steps.model_onayi(b)
    assert api.postlar == [
        ("analist", "/design-models/m1/decision", {"karar": "approve", "icerik_hash": "h1"})
    ]
    assert {k.sonuc for k in b.kontroller} == {PASS}


def test_case_review_skor_ve_mod(baglam):
    api = Api(
        {
            f"/requirements/{RID}/case-review": {
                "review": {
                    "durum": "tamamlandi",
                    "skor": steps.REVIEW_SKORU,
                    "mode": "replay",
                    "isteyen": "system",
                    "icerik": {},
                },
                "bayat": False,
                "calisiyor": False,
            }
        }
    )
    b = _hazir(baglam(), api)
    steps.case_review(b)
    assert {k.sonuc for k in b.kontroller} == {PASS}


def test_case_denetim_kabul_bekler_ve_gonderir(baglam):
    yol = f"/requirements/{RID}/case-audit"
    durum = {"gonderildi": False}

    def gorunum():
        if not durum["gonderildi"]:
            return {
                "kapi_acik": True,
                "yayin_engeli": "Denetim kararı yok",
                "gonder_engeli": None,
                "calisiyor": False,
                "denetim": None,
                "guncel_karar": None,
            }
        d = {
            "durum": "tamamlandi",
            "karar": "KABUL",
            "guncel": True,
            "icerik": {"mode": "replay"},
        }
        return {
            "kapi_acik": True,
            "yayin_engeli": None,
            "calisiyor": False,
            "denetim": d,
            "guncel_karar": d,
        }

    def gonder():
        durum["gonderildi"] = True
        return {"calisiyor": True}

    api = Api(
        {
            yol: gorunum,
            f"/publish/preview?requirement_id={RID}": {"kalemler": [{"islem": "blocked_gate"}]},
        },
        {yol: gonder},
    )
    b = _hazir(baglam(), api)
    steps.case_denetim(b)
    assert [p[1] for p in api.postlar] == [yol]
    assert {k.sonuc for k in b.kontroller} == {PASS}


def test_case_denetim_duzeltme_gerekli_fail(baglam):
    d = {"durum": "tamamlandi", "karar": "DÜZELTME_GEREKLİ", "guncel": True, "icerik": {}}
    api = Api(
        {
            f"/requirements/{RID}/case-audit": {
                "calisiyor": False,
                "denetim": d,
                "guncel_karar": d,
                "yayin_engeli": "DÜZELTME_GEREKLİ: x",
            }
        }
    )
    b = _hazir(baglam(kip="denetim"), api)
    with pytest.raises(Basarisiz, match="KABUL"):
        steps.case_denetim(b)


def test_adim_sirasi_iki_tur_review_denetim():
    nolar = [a.no for a in steps.adimlar()]
    i = nolar.index
    assert i("A5") < i("A6") < i("A7") < i("A8") < i("A9") < i("A10") < i("A11") < i("A12")
    adlar = {a.no: a.ad for a in steps.adimlar()}
    assert adlar["A6"].startswith("Tasarım modeli") and adlar["A7"].startswith("Model onayı")
