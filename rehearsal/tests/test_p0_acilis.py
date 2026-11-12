"""P0: strict REPLAY kipi zorunlu, demo-reset temel koşusu, açılış sayacı (DEMO-AKISI)."""

from __future__ import annotations

from typing import Any

import pytest

from tp_rehearsal import __main__ as cli
from tp_rehearsal.runner import FAIL, PASS, UYARI, Basarisiz
from tp_rehearsal.steps import PORTAL_HESAPLARI, acilis_tamam_adimlari, on_kontrol

from .conftest import SahteApi

MAIN = "a" * 40


class SahteYigin:
    def __init__(self, mod: str) -> None:
        self.mod = mod

    def worker_ortami(self) -> dict[str, str]:
        return {"TP_MODEL_MODE": self.mod, "TP_REPLAY_STRICT": "1", "TP_FORGE": "local"}


class SahteOrtam:
    def al(self, _ad: str) -> str:
        return ""


def _durum(hazir: bool = True) -> dict[str, Any]:
    return {
        "locator_durumu": "baseline",
        "locator_demo": {"destekleniyor": True},
        "forge": {"main": MAIN, "main_baseline_mi": True},
        "uygulama": {"main_ile_eslesiyor": True},
        "onarim_on_kosulu": {
            "hazir": hazir,
            "son_yesil_kosu": {"run_id": "r1", "commit": MAIN, "tetik": "push"} if hazir else None,
        },
    }


TEMEL_KOSU = {
    "id": "r1",
    "tetik": "push",
    "kaynak": "local",
    "durum": "passed",
    "commit": MAIN,
    "junit_url": "/runs/r1/junit",
    "allure_url": "/runs/r1/allure",
}


class RolluApi(SahteApi):
    """`/auth/me` hesaba göre rol döner (seed: 012 rol modeli)."""

    def __init__(self, yanitlar, roller=None) -> None:
        super().__init__(yanitlar)
        self.roller = dict(PORTAL_HESAPLARI if roller is None else roller)

    def get(self, rol: str, yol: str):
        if yol == "/auth/me":
            self.cagrilar.append((rol, "GET", yol))
            return {"rol": self.roller.get(rol)}
        return super().get(rol, yol)


def _api(hazir: bool = True, kosular=None, kule=None, roller=None) -> SahteApi:
    kosular = [] if kosular is None else kosular
    return RolluApi(
        {
            "/demo/status": _durum(hazir),
            "/requirements": [],
            "/scripts": [],
            "/runs?limit=200&limit=50": kosular,
            "/runs?limit=200": kosular,
            "/control-tower": kule if kule is not None else {"son_kosular": []},
            "/bug-drafts": [],
        },
        roller,
    )


def _p0(baglam, mod: str = "replay", kip: str = "prova", **api_kw):
    b = baglam(kip=kip, api=_api(**api_kw))
    b.yigin = SahteYigin(mod)
    b.ortam = SahteOrtam()
    return b


def _kontrol(b, parca: str):
    return next(k for k in b.kontroller if parca in k.ad)


@pytest.mark.parametrize("mod", ["auto", "live"])
def test_p0_prova_replay_disi_kritik_fail(baglam, mod):
    b = _p0(baglam, mod)
    with pytest.raises(Basarisiz, match="TP_MODEL_MODE=replay"):
        on_kontrol(b)
    assert _kontrol(b, "TP_MODEL_MODE=replay").sonuc == FAIL
    # Z1 için de canlı çağrı izinli sayılmaz.
    assert b.veri["izinli_modlar"] == {"replay"}


def test_p0_canli_izinli_uyari_ve_live_izinli(baglam):
    b = _p0(baglam, "auto")
    b.veri["canli_izinli"] = True
    on_kontrol(b)
    assert _kontrol(b, "TP_MODEL_MODE=replay").sonuc == UYARI
    assert b.veri["izinli_modlar"] == {"replay", "live"}


def test_p0_replay_temiz_baslangic_gecer(baglam):
    b = _p0(baglam, "replay", kosular=[])
    on_kontrol(b)
    assert _kontrol(b, "TP_MODEL_MODE=replay").sonuc == PASS
    assert _kontrol(b, "temel push CI yeşil").sonuc == PASS
    assert _kontrol(b, "açılış: yol haritası 0/14").sonuc == PASS
    assert b.kanit["acilis_sayaci"] == "0/14"


def test_p0_sekiz_hesap_012_rolleriyle_giris_yapar(baglam):
    b = _p0(baglam, "replay")
    on_kontrol(b)
    assert _kontrol(b, "portal hesabı giriş yaptı").sonuc == PASS
    assert b.kanit["roller"]["sunucu"] == "admin"
    assert b.kanit["roller"]["testci"] == "tester"
    assert {r for r, _y, yol in b.api.cagrilar if yol == "/auth/me"} == set(PORTAL_HESAPLARI)


def test_p0_eski_presenter_rolu_kritik_fail(baglam):
    b = _p0(baglam, "replay", roller=PORTAL_HESAPLARI | {"sunucu": "presenter"})
    with pytest.raises(Basarisiz, match="012 kataloğuyla"):
        on_kontrol(b)
    assert _kontrol(b, "portal hesabı giriş yaptı").sonuc == FAIL


def test_p0_temel_kosu_yoksa_bekler_sonra_fail(baglam, saat):
    b = _p0(baglam, "replay", hazir=False)
    with pytest.raises(Basarisiz, match="make demo-reset"):
        on_kontrol(b)
    assert _kontrol(b, "temel push CI yeşil").sonuc == FAIL
    assert saat.t >= 420  # demo-reset sonrası derleme + CI için beklendi


def test_p0_acilis_sayaci_temel_kosu_story_kosusu_sayilmaz(baglam):
    # make demo-reset'in yeşil push koşusu story'ye ait değil (portal storyKosusuMu) → 0/14.
    b = _p0(
        baglam,
        "replay",
        kosular=[TEMEL_KOSU],
        kule={"son_kosular": [TEMEL_KOSU]},
    )
    on_kontrol(b)
    k = _kontrol(b, "açılış: yol haritası 0/14")
    assert k.sonuc == PASS
    assert b.kanit["acilis_sayaci"] == "0/14"


def test_acilis_story_kosusu_merge_sonrasi_sayilir_uyari_verir():
    # Story script'i merge edilmiş ve sonrasında raporlu push + deploy koşmuş: 8, 9, 10, 11 tamam.
    script = {
        "case_ref": "TPD-1-C2",
        "durum": "merged",
        "olusturma": "2026-11-01T10:00:00+00:00",
        "pr": {"number": 7, "durum": "merged", "merge_zamani": "2026-11-01T10:05:00+00:00"},
    }
    once = dict(TEMEL_KOSU, id="r0", baslangic="2026-11-01T09:00:00+00:00")
    sonra = dict(TEMEL_KOSU, id="r2", baslangic="2026-11-01T10:06:00+00:00")
    deploy = dict(sonra, id="r3", tetik="deploy")
    kule = {"son_kosular": [sonra]}
    assert acilis_tamam_adimlari(None, [once], kule, [script], []) == [5]
    hepsi = [once, sonra, deploy]
    assert acilis_tamam_adimlari(None, hepsi, kule, [script], []) == [5, 8, 9, 10, 11]
    # PR koşusu (merge öncesi) story'ye sayılır
    pr_kosusu = dict(TEMEL_KOSU, id="r4", pr_no=7, baslangic="2026-11-01T10:01:00+00:00")
    acik = dict(script, durum="pr_open", pr={"number": 7, "durum": "open"})
    assert acilis_tamam_adimlari(None, [pr_kosusu], kule, [acik], []) == [5, 9, 10, 11]


def test_p0_denetim_kipinde_canli_mod_fail_olmaz(baglam):
    api = _api()
    api.yanitlar["/requirements"] = [{"jira_key": "TPD-1", "id": "g1"}]
    api.yanitlar["/requirements/g1"] = {"id": "g1", "durum": "done"}
    b = baglam(kip="denetim", api=api)
    b.yigin, b.ortam = SahteYigin("live"), SahteOrtam()
    on_kontrol(b)
    assert not any("TP_MODEL_MODE=replay" in k.ad for k in b.kontroller)
    assert b.veri["izinli_modlar"] == {"replay", "live"}


def test_acilis_tamam_adimlari_kurallari():
    assert acilis_tamam_adimlari(None, [], {"son_kosular": []}, [], []) == []
    # yalnız push: 8 sürüyor (tamam değil); deploy da varsa tamam
    push = dict(TEMEL_KOSU, junit_url=None, allure_url=None, durum="running")
    assert acilis_tamam_adimlari(None, [push], None, [], []) == []
    deploy = dict(push, tetik="deploy")
    # story script'i yoksa CI koşuları story'ye sayılmaz (portal storyKosusuMu)
    assert acilis_tamam_adimlari(None, [push, deploy], None, [], []) == []
    script = {"durum": "merged", "olusturma": "2026-01-01T00:00:00+00:00", "pr": {"number": 1}}
    push2 = dict(push, baslangic="2026-01-02T00:00:00+00:00")
    deploy2 = dict(push2, tetik="deploy")
    assert acilis_tamam_adimlari(None, [push2, deploy2], None, [script], []) == [5, 8]
    # kırma/yerel kontrol koşuları CI tetiği değil
    bv = dict(TEMEL_KOSU, tetik="break_verify")
    assert acilis_tamam_adimlari(None, [bv], None, [], []) == []
    # story kanıtı
    req = {"durum": "po_approved"}
    assert acilis_tamam_adimlari(req, [], None, [{"pr": 3}], [{"id": "d"}]) == [1, 2, 3, 5, 13]


def test_cli_canli_izinli_bayragi():
    a = cli._arguman().parse_args(["--canli-izinli"])
    assert a.canli_izinli is True
    assert cli._arguman().parse_args([]).canli_izinli is False
