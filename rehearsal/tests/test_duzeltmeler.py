"""Review düzeltmeleri: sır taraması, Z1 kritik, P1 güvenlik, C6, rapor bağlantıları, rapor adı."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from typing import Any

import pytest

from tp_rehearsal import __main__ as cli
from tp_rehearsal import sir_tarama, steps
from tp_rehearsal.client import Yanit
from tp_rehearsal.env import Sirlar
from tp_rehearsal.runner import FAIL, PASS, UYARI, Basarisiz, Calistirici
from tp_rehearsal.stack import KomutSonucu

SIR = "Gizli-Parola/42+ü"  # JSON/URL kodlamasında değişen karakterler içerir


# ---------------------------------------------------------------- sır taraması


def test_bicimler_ham_json_url():
    b = sir_tarama.bicimler(SIR)
    assert SIR.encode() in b
    assert b"Gizli-Parola%2F42%2B%C3%BC" in b  # quote / form gövdesi
    assert b"Gizli-Parola/42+\\u00fc" in b  # json.dumps (ascii)


def test_tara_duz_dosya_ve_zip_uyesi(tmp_path):
    (tmp_path / "temiz.md").write_text("PASS\n", encoding="utf-8")
    (tmp_path / "sizinti.log").write_text(f'{{"parola": "{SIR}"}}', encoding="utf-8")
    iz = tmp_path / "video" / "x" / "trace.zip"
    iz.parent.mkdir(parents=True)
    with zipfile.ZipFile(iz, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("1-trace.network", "parola=Gizli-Parola%2F42%2B%C3%BC")
        z.writestr("temiz.json", "{}")
    bulgu = dict(sir_tarama.tara(tmp_path, Sirlar([SIR])))
    assert set(bulgu) == {"sizinti.log", "video/x/trace.zip!1-trace.network"}
    assert all(n == 1 for n in bulgu.values())


def test_tara_parca_sinirinda_bolunen_deger(tmp_path, monkeypatch):
    monkeypatch.setattr(sir_tarama, "PARCA", 7)
    (tmp_path / "v.webm").write_bytes(b"\x00" * 5 + SIR.encode() + b"\x00" * 30)
    assert sir_tarama.tara(tmp_path, Sirlar([SIR])) == [("v.webm", 1)]


def test_akista_bul_cok_sir():
    d = sir_tarama._desenler(["birinci-sir", "ikinci-sir"])
    assert sir_tarama._akista_bul(io.BytesIO(b"..ikinci-sir..birinci-sir"), d) == {0, 1}
    assert sir_tarama._akista_bul(io.BytesIO(b"yok"), d) == set()


def test_iz_sil_ve_main_cikis_kodlari(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text(f"SEED_USER_PASSWORD={SIR}\nTP_MODEL_MODE=replay\n", "utf-8")
    rapor = tmp_path / "rapor"
    (rapor / "video").mkdir(parents=True)
    with zipfile.ZipFile(rapor / "video" / "trace.zip", "w") as z:
        z.writestr("test.trace", f'{{"value": "{SIR}"}}')
    (rapor / "rapor.md").write_text("ok", "utf-8")

    assert sir_tarama.main([str(rapor), "--repo", str(repo)]) == 1
    cikti = capsys.readouterr()
    assert SIR not in cikti.out + cikti.err  # değer asla yazdırılmaz
    assert "trace.zip!test.trace" in cikti.out

    assert sir_tarama.main([str(rapor), "--repo", str(repo), "--iz-sil"]) == 0
    assert not (rapor / "video" / "trace.zip").exists()
    assert (rapor / "rapor.md").exists()


# ---------------------------------------------------------------- sahte yığın / API


class Api:
    def __init__(self, yanitlar: dict[str, Any] | None = None, durumlar=None) -> None:
        self.yanitlar = yanitlar or {}
        self.durumlar = durumlar or {}
        self.postlar: list[tuple[str, str, Any]] = []

    def get(self, rol: str, yol: str) -> Any:
        y = self.yanitlar[yol]
        return y() if callable(y) else y

    def istek(self, rol: str, yontem: str, yol: str, govde: Any = None) -> Yanit:
        return Yanit(self.durumlar.get(yol, 200), None, 0.01)

    def post(self, rol, yol, govde=None, beklenen=(200, 202)):
        self.postlar.append((rol, yol, govde))
        return {}


V3_TEMIZ = [
    {
        "amac": a,
        "mod": "replay",
        "koken": "golden_matched",
        "kaynak": f"{a}/golden/f2-kod-hatasi/TPD-1.json",
    }
    for a in ("design_model", "case_generation", "case_review", "case_audit")
]


class Yigin:
    def __init__(self, kipler=None, push=None, sec_kod=0, kokenler=V3_TEMIZ) -> None:
        self.kipler, self.push, self.sec_kod = kipler, push, sec_kod
        self.kokenler = kokenler
        self.hedefler: list[str] = []

    def ai_call_kipleri(self, _):
        return self.kipler

    def ai_call_kokenleri(self, _, amaclar):
        return None if self.kokenler is None else [k for k in self.kokenler if k["amac"] in amaclar]

    def bot_main_push_dene(self):
        return self.push

    def make(self, hedef, zaman_asimi_s=600):
        self.hedefler.append(hedef)
        return KomutSonucu(f"make {hedef}", self.sec_kod, "PASS  1/port\nÖzet: 10/10\n", 1.0)


class Jira:
    def __init__(self, issues):
        self.issues = issues

    def issue(self, anahtar, alanlar=""):
        return self.issues[anahtar]


def _z1_api(cagri=15, replay=15):
    return Api(
        {
            "/control-tower": {
                "ai_katkisi": {
                    "cagri_sayisi": cagri,
                    "replay_cagri": replay,
                    "script_replay_miss": 0,
                }
            },
            "/audit?verify=true&limit=1": {"verify": {"ok": True, "anchors": {"ok": True}}},
            "/bug-drafts": [],
        }
    )


# ---------------------------------------------------------------- Z1


def test_z1_ai_call_okunamazsa_fail(baglam):
    b = baglam(api=_z1_api())
    b.yigin = Yigin(kipler=None)
    b.veri.update(baslangic_iso="x", model_modu="replay")
    with pytest.raises(Basarisiz, match="ai_call kipleri okundu"):
        steps.son_denetim(b)


def test_z1_kontrol_kulesi_capraz_kontrol_sahte_live(baglam):
    b = baglam(api=_z1_api(cagri=16, replay=15))
    b.yigin = Yigin(kipler=[{"mod": "replay", "amac": "x", "sayi": 15}])
    b.veri.update(baslangic_iso="x", model_modu="replay")
    with pytest.raises(Basarisiz, match="sahte 'live' yok"):
        steps.son_denetim(b)


def test_z1_temiz(baglam):
    b = baglam(api=_z1_api())
    b.yigin = Yigin(kipler=[{"mod": "replay", "amac": "x", "sayi": 15}])
    b.veri.update(baslangic_iso="x", model_modu="replay")
    steps.son_denetim(b)
    assert {k.sonuc for k in b.kontroller} == {PASS}


def test_z1_v3_cagrisi_eksikse_fail(baglam):
    b = baglam(api=_z1_api())
    b.yigin = Yigin(
        kipler=[{"mod": "replay", "amac": "x", "sayi": 15}],
        kokenler=[k for k in V3_TEMIZ if k["amac"] != "case_audit"],
    )
    b.veri.update(baslangic_iso="x", model_modu="replay")
    with pytest.raises(Basarisiz, match="case_audit"):
        steps.son_denetim(b)


def test_z1_v3_cagrisi_golden_matched_degilse_fail(baglam):
    b = baglam(api=_z1_api())
    sapan = [dict(k) for k in V3_TEMIZ]
    sapan[2]["koken"] = "miss_neutral"
    b.yigin = Yigin(kipler=[{"mod": "replay", "amac": "x", "sayi": 15}], kokenler=sapan)
    b.veri.update(baslangic_iso="x", model_modu="replay")
    with pytest.raises(Basarisiz, match="golden_matched"):
        steps.son_denetim(b)


# ---------------------------------------------------------------- P1


def test_p1_bot_push_kabul_edilirse_fail(baglam):
    b = baglam()
    b.yigin = Yigin(push={"reddedildi": False, "main_degismedi": False})
    with pytest.raises(Basarisiz, match="reddedildi"):
        steps.guvenlik(b)
    assert b.yigin.hedefler == ["security-check"]


def test_p1_security_check_fail(baglam):
    b = baglam()
    b.yigin = Yigin(push={"reddedildi": True, "main_degismedi": True}, sec_kod=1)
    with pytest.raises(Basarisiz, match="security-check"):
        steps.guvenlik(b)


def test_p1_gecer_ve_denetimde_push_yok(baglam):
    b = baglam()
    b.yigin = Yigin(push={"reddedildi": True, "main_degismedi": True})
    steps.guvenlik(b)
    assert b.kanit["security_check"]["ozet"] == "Özet: 10/10"
    d = baglam(kip="denetim")
    d.yigin = Yigin(push=None)
    steps.guvenlik(d)  # push denenmez: None olsa da geçer
    assert "bot_main_push" not in d.kanit


def test_p1_erisilemezse_fail(baglam):
    b = baglam()
    b.yigin = Yigin(push=None)
    with pytest.raises(Basarisiz, match="push denemesi koştu"):
        steps.guvenlik(b)


# ---------------------------------------------------------------- C6


def _c6(baglam, linkler, test_key="TPD-9"):
    taslak = {
        "id": "t1",
        "durum": "published",
        "karar": "new",
        "jira_key": "TPD-14",
        "hazirlik": {"durum": "hazir"},
        "icerik": {"story_key": "TPD-1", "test_case_key": test_key},
    }
    b = baglam(api=Api({"/bug-drafts/t1": taslak}))
    b.jira = Jira(
        {
            "TPD-14": {
                "fields": {
                    "issuetype": {"name": "Bug"},
                    "issuelinks": [
                        {"type": {"name": t}, "inwardIssue": {"key": k}} for t, k in linkler
                    ],
                }
            }
        }
    )
    b.veri.update(taslak_kirma="t1", test_anahtarlari={2: "TPD-9"})
    return b


def test_c6_yeni_bug_story_ve_test_bagli(baglam):
    b = _c6(baglam, [("Relates", "TPD-1"), ("Test", "TPD-9")])
    steps.kirma_yeni_bug(b)
    assert all(k.sonuc == PASS for k in b.kontroller)


def test_c6_test_bagi_yoksa_fail(baglam):
    b = _c6(baglam, [("Relates", "TPD-1")])
    with pytest.raises(Basarisiz, match="Test TPD-9"):
        steps.kirma_yeni_bug(b)


def test_c6_yanlis_test_issuesu_fail(baglam):
    b = _c6(baglam, [("Relates", "TPD-1"), ("Test", "TPD-8")], test_key="TPD-8")
    with pytest.raises(Basarisiz, match="C2'nin Test"):
        steps.kirma_yeni_bug(b)


def test_adimlar_p1_ve_istege_bagli_c6():
    nolar = [a.no for a in steps.adimlar()]
    assert nolar[:2] == ["P0", "P1"] and "C6" not in nolar
    ile = [a.no for a in steps.adimlar(kirma_yayinla=True)]
    assert ile[ile.index("C5") + 1] == "C6" and ile[-1] == "Z1"


# ---------------------------------------------------------------- rapor bağlantıları (adım 9–10)


def _kosu(**kw):
    k = {
        "kaynak": "local",
        "sauce_url": None,
        "rapor_url": "/api/artifacts/k/imza/runs/r/html/index.html",
        "junit_url": "/api/artifacts/runs/r/junit.xml",
        "allure_url": "/api/artifacts/runs/r/allure-report/index.html",
    }
    return {**k, **kw}


def test_rapor_baglantilari_200(baglam):
    b = baglam(api=Api())
    steps.rapor_baglantilari(b, _kosu())
    assert [k.sonuc for k in b.kontroller] == [PASS] * 4
    assert b.kanit["rapor_baglantilari"]["junit_url"] == 200


def test_rapor_baglantilari_kirik_link_fail(baglam):
    b = baglam(api=Api(durumlar={"/artifacts/runs/r/allure-report/index.html": 404}))
    with pytest.raises(Basarisiz, match="Allure"):
        steps.rapor_baglantilari(b, _kosu())


def test_rapor_baglantilari_sahte_sauce_fail(baglam):
    b = baglam(api=Api())
    with pytest.raises(Basarisiz, match="Sauce"):
        steps.rapor_baglantilari(b, _kosu(sauce_url="https://saucelabs.com/x"))


def test_api_yolu():
    assert steps.api_yolu("/api/artifacts/x") == "/artifacts/x"
    assert steps.api_yolu("https://ci.example/x") is None


# ---------------------------------------------------------------- rapor adı (yerel saat)


def test_rapor_adi_yerel_saat_ve_ekler():
    z = datetime(2026, 11, 1, 12, 26, 3)
    assert cli.rapor_adi(z, 1, "prova") == "20261101-122603-k1"
    assert cli.rapor_adi(z, None, "denetim") == "20261101-122603-denetim"


def test_cli_rapor_yolu_ezer():
    a = cli._arguman().parse_args(["--rapor-yolu", "/tmp/x-k1", "--kirma-yayinla"])
    assert str(a.rapor_yolu) == "/tmp/x-k1" and a.kirma_yayinla


def test_runner_z1_kritik_fail_rapora(baglam):
    """Z1 adımı çalıştırıcıda FAIL olur (UYARI değil): prova geçmez."""
    b = baglam(api=_z1_api())
    b.yigin = Yigin(kipler=None)
    b.veri.update(baslangic_iso="x", model_modu="replay")
    s = Calistirici([a for a in steps.adimlar() if a.no == "Z1"], b).calistir()
    assert s[0].durum == FAIL
    assert all(k.sonuc != UYARI for k in s[0].kontroller)


def test_caseler_ide_uretimini_atlar(baglam):
    """012 demo: IDE taslağı (uretim 2, tek case) portal üretiminin (uretim 1) yerine geçmez."""
    from .conftest import SahteApi

    hepsi = [
        {"id": "a", "sira_no": 1, "uretim_no": 1, "kanal": "portal"},
        {"id": "b", "sira_no": 2, "uretim_no": 1, "kanal": "portal"},
        {"id": "v", "sira_no": 6, "uretim_no": 2, "kanal": "ide"},
    ]
    b = baglam(api=SahteApi({"/cases?requirement_id=r": hepsi}))
    assert {n: c["id"] for n, c in steps.caseler(b, "r").items()} == {1: "a", 2: "b"}
    b = baglam(api=SahteApi({"/cases?requirement_id=r": hepsi[2:]}))
    assert list(steps.caseler(b, "r")) == [6]


def test_yayin_ide_taslagini_onizlemede_saymaz(baglam):
    """012 demo: IDE varyantı taslakken önizlemede `blocked_not_approved`; portal case'leri
    yayınlanır."""
    from .conftest import SahteApi

    class Api(SahteApi):
        def post(self, rol, yol, govde=None, beklenen=(200, 202)):
            self.cagrilar.append((rol, "POST", yol))
            self.gonderilen = govde
            return {"sonuclar": [{"durum": "created"} for _ in govde["case_ids"]]}

    hepsi = [
        {"id": "a", "sira_no": 1, "uretim_no": 1, "kanal": "portal", "jira_test_key": "TPD-11"},
        {"id": "v", "sira_no": 6, "uretim_no": 2, "kanal": "ide"},
    ]
    api = Api(
        {
            "/cases?requirement_id=r": hepsi,
            "/publish/preview?requirement_id=r": {
                "kalemler": [
                    {"case_id": "a", "islem": "create"},
                    {"case_id": "v", "islem": "blocked_not_approved"},
                ]
            },
        }
    )
    b = baglam(api=api)
    b.veri["req_id"] = "r"
    # Sonraki kontroller (10 case, jira-sim) sahte veride düşer; yalnız gönderim denetlenir.
    with pytest.raises(Basarisiz):
        steps.yayin(b)
    assert api.gonderilen == {"case_ids": ["a"]}
