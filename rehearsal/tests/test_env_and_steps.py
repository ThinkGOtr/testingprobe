"""`.env` okuma / sır maskeleme ve adım yardımcıları (canlı yığın gerekmez)."""

from __future__ import annotations

from tp_rehearsal import steps
from tp_rehearsal.client import baglantilar
from tp_rehearsal.env import Ortam, Sirlar, env_oku

from .conftest import SahteApi


def test_env_oku(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# yorum\n\nA=1\nexport B='iki'\nC=\"üç\"\nD=a=b\nbozuk satir\n", encoding="utf-8")
    assert env_oku(p) == {"A": "1", "B": "iki", "C": "üç", "D": "a=b"}
    assert env_oku(tmp_path / "yok") == {}


def test_sirlar_yalniz_sir_adli_ve_uzun_degerler():
    s = Sirlar.ortamdan(
        {
            "SEED_USER_PASSWORD": "parola-uzun-1",
            "JIRA_WRITE_TOKEN": "sim",  # kısa: maskelenmez (metni bozar)
            "ANTHROPIC_API_KEY": "sk-ant-xxxxxxxx",
            "TP_PORTAL_PORT": "808080",  # sır adı değil
        }
    )
    m = s.maskele("p=parola-uzun-1 k=sk-ant-xxxxxxxx t=sim port=808080")
    assert m == "p=*** k=*** t=sim port=808080"


def test_sirlar_uzun_deger_once():
    s = Sirlar.ortamdan({"A_TOKEN": "abcdef", "B_TOKEN": "abcdefgh"})
    assert s.maskele("abcdefgh") == "***"


def test_ortam_onceligi(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("TP_PORTAL_PORT=9999\nSEED_USER_PASSWORD=dosyadan\n")
    monkeypatch.delenv("TP_API_URL", raising=False)
    monkeypatch.delenv("TP_PROVA_PAROLA", raising=False)
    monkeypatch.delenv("SEED_USER_PASSWORD", raising=False)
    o = Ortam.yukle(tmp_path)
    assert o.api_url == "http://127.0.0.1:9999/api"
    assert o.portal_parolasi == "dosyadan"
    monkeypatch.setenv("TP_PROVA_PAROLA", "ortamdan")
    assert o.portal_parolasi == "ortamdan"


def test_yama_satirlari_tek_satir_degisim():
    yama = (
        "--- a/e2e/pages/catalog/locators.ts\n"
        "+++ b/e2e/pages/catalog/locators.ts\n@@ -8,3 +8,3 @@\n"
        '   q: { testId: "qty-input-" },\n'
        '-  addToCart: { testId: "add-to-cart" },\n'
        '+  addToCart: { testId: "cart-add" },\n'
    )
    eksi, arti = steps._yama_satirlari(yama)
    assert len(eksi) == 1 and "add-to-cart" in eksi[0]
    assert len(arti) == 1 and "cart-add" in arti[0]


def test_kirmizi_push_secimi():
    ks = [
        {"tetik": "pr", "commit": "a", "durum": "failed", "basarisiz": 22},
        {"tetik": "push", "commit": "b", "durum": "passed", "basarisiz": 0},
        {"tetik": "push", "commit": "c", "durum": "failed", "basarisiz": 22},
    ]
    assert steps._kirmizi_push(ks, "b")["commit"] == "b"
    assert steps._kirmizi_push(ks, None)["commit"] == "c"
    assert steps._kirmizi_push(ks, "yok") is None


def _script(head="h1", checks=("passed",), geride=False, engeller=(), durum="open"):
    return {
        "pr": {
            "durum": durum,
            "head_sha": head,
            "dal": {"geride": geride},
            "checks": [{"ad": "local-ci", "durum": c} for c in checks],
        },
        "merge_engelleri": list(engeller),
    }


def test_pr_hazir(baglam):
    api = SahteApi()
    b = baglam(api=api)

    def hazir(s, eski=None):
        api.yanitlar["/scripts/x"] = s
        return steps._pr_hazir(b, "x", eski)

    assert hazir(_script())
    assert hazir(_script(), eski="h1") is None, "dal yeni head'e taşınmadan merge edilmez"
    assert hazir(_script(head="h2"), eski="h1")
    assert hazir(_script(checks=("pending",))) is None
    assert hazir(_script(checks=())) is None
    assert hazir(_script(geride=True)) is None
    assert hazir(_script(engeller=("Zorunlu kontrol 'local-ci': pending",))) is None
    assert hazir(_script(durum="merged"))
    assert hazir(_script(durum="closed")) is None


def test_mod_kontrol_replay_disi_fail(baglam):
    b = baglam()
    b.veri["izinli_modlar"] = {"replay"}
    steps.mod_kontrol(b, "C1", "replay")
    try:
        steps.mod_kontrol(b, "C1", "live")
    except AssertionError as e:
        assert "live" in str(e)
    else:
        raise AssertionError("replay kipinde 'live' kabul edilmemeli")


def test_adim_listesi_tutarli():
    a = steps.adimlar()
    nolar = [x.no for x in a]
    assert len(nolar) == len(set(nolar))
    assert nolar[0] == "P0" and nolar[-1] == "Z1"
    # 14 adımın her biri en az bir prova adımına eşlenir
    kapsanan = set()
    for x in a:
        for parca in x.demo_adimi.replace("–", "-").replace(",", " ").split():
            if "-" in parca:
                i, j = parca.split("-")
                kapsanan |= set(range(int(i), int(j) + 1))
            elif parca.isdigit():
                kapsanan.add(int(parca))
    assert kapsanan == set(range(1, 15))
    kod = next(x for x in a if x.no == "B1")
    assert kod.ai_adimi and kod.butce_s >= steps.AJAN_BUTCESI_S * len(steps.KOD_CASELERI)


def test_baglantilar():
    issue = {
        "fields": {
            "issuelinks": [
                {"type": {"name": "Relates"}, "outwardIssue": {"key": "TPD-1"}},
                {"type": {"name": "Test"}, "inwardIssue": {"key": "TPD-10"}},
            ]
        }
    }
    assert baglantilar(issue) == [("Relates", "TPD-1"), ("Test", "TPD-10")]
