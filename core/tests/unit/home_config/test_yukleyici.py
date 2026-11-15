"""Config R1 — Home etkin config yükleyicisi (yalnız stdlib): ETag, LKG, Home kapalı, env görünümü,
korunan anahtarlar, sır referansı denetimi, env dosyası birleştirme ve açılış CLI'si."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from tests.unit.home_config.sahte_home import HOME, REF, SM_PROJESI, SahteHome, ornek_yanit
from tp_core.home_config import __main__ as cli
from tp_core.home_config import yukleyici as y


def _istemci(home: SahteHome) -> y.HomeConfigIstemcisi:
    return y.HomeConfigIstemcisi(HOME, "aaaabbbbcccc", lambda aud: f"id:{aud}", http=home)


def test_kaynak_varsayilan_env() -> None:
    assert y.kaynak({}) == "env"
    assert y.kaynak({"CONFIG_SOURCE": ""}) == "env"
    assert y.kaynak({"CONFIG_SOURCE": "HOME"}) == "home"
    assert y.kaynak({"CONFIG_SOURCE": "baska"}) == "env"


def test_cek_kimlik_ve_proje_parametresi() -> None:
    home = SahteHome()
    cfg = _istemci(home).cek()
    assert cfg is not None and cfg.etag == "v1"
    _m, url, bas, _g = home.istekler[0]
    assert url == f"{HOME}/v1/config/effective?project=aaaabbbbcccc"
    assert bas["Authorization"] == f"Bearer id:{HOME}"
    assert "If-None-Match" not in bas
    assert cfg.ozellikler == {
        "web": True, "android": True, "ios": False, "windows": True, "ai_agent": False,
    }  # fmt: skip


def test_etag_304_ve_lkg(tmp_path: Path) -> None:
    home = SahteHome()
    lkg = tmp_path / "d" / "lkg.json"
    yk = y.Yukleyici(_istemci(home), str(lkg))
    s1 = yk.yukle()
    assert (s1.kaynak, s1.degisti) == ("home", True)
    assert stat.S_IMODE(lkg.stat().st_mode) == 0o600
    # LKG yalnız referans tutar, sır değeri değil.
    icerik = lkg.read_text()
    assert REF in icerik and "gizli-deger" not in icerik
    s2 = yk.yukle()
    assert s2.kaynak == "home" and not s2.degisti and s2.cfg is s1.cfg
    assert home.istekler[-1][2]["If-None-Match"] == "v1"
    # Yeni süreç (bellek boş) LKG'nin ETag'ini gönderir; 304 → LKG.
    yk2 = y.Yukleyici(_istemci(home), str(lkg))
    s3 = yk2.yukle()
    assert s3.kaynak == "home" and s3.cfg is not None and s3.cfg.etag == "v1"
    assert home.istekler[-1][2]["If-None-Match"] == "v1"


def test_degisiklik_yeni_etag(tmp_path: Path) -> None:
    home = SahteHome()
    yk = y.Yukleyici(_istemci(home), str(tmp_path / "lkg.json"))
    yk.yukle()
    home.yanit = ornek_yanit(etag="v2", env={"JIRA_PROJECT": "ABC"})
    s = yk.yukle()
    assert s.degisti and s.cfg is not None and s.cfg.env["JIRA_PROJECT"] == "ABC"
    assert json.loads((tmp_path / "lkg.json").read_text())["etag"] == "v2"


@pytest.mark.parametrize("ariza", ["kapali", 503, 429, 401])
def test_home_kapali_lkg_ile_acilir(tmp_path: Path, ariza: object) -> None:
    lkg = str(tmp_path / "lkg.json")
    y.Yukleyici(_istemci(SahteHome()), lkg).yukle()
    home = SahteHome()
    if ariza == "kapali":
        home.kapali = True
    else:
        home.durum = int(ariza)  # type: ignore[arg-type]
        home.yanit = ornek_yanit(etag="v9")  # ETag eşleşmesin
    s = y.Yukleyici(_istemci(home), lkg).yukle()
    assert s.kaynak == "lkg" and s.cfg is not None and s.cfg.etag == "v1" and s.hata


@pytest.mark.parametrize("kod", [403, 404])
def test_home_reddederse_lkg_kullanilmaz_ve_silinir(tmp_path: Path, kod: int) -> None:
    """N4: Home 403/404 (proje/ürün erişimi yok) → `reddedildi`; LKG'ye düşülmez, LKG silinir
    (sonraki bir ağ kesintisinde geri çekilmiş değerler geri gelmesin)."""
    lkg = tmp_path / "lkg.json"
    y.Yukleyici(_istemci(SahteHome()), str(lkg)).yukle()
    assert lkg.exists()
    home = SahteHome(durum=kod, yanit=ornek_yanit(etag="v9"))
    yk = y.Yukleyici(_istemci(home), str(lkg))
    s = yk.yukle()
    assert (s.kaynak, s.cfg) == ("reddedildi", None) and s.hata and str(kod) in s.hata
    assert s.geri_cekilen is not None and s.geri_cekilen.etag == "v1"
    assert not lkg.exists() and yk.son is None
    # Ardından ağ kesintisi: LKG yok → env (geri çekilen değerler dönmez).
    s2 = y.Yukleyici(_istemci(SahteHome(kapali=True)), str(lkg)).yukle()
    assert (s2.kaynak, s2.cfg) == ("env", None)


def test_home_kapali_lkg_yok_env(tmp_path: Path) -> None:
    home = SahteHome(kapali=True)
    s = y.Yukleyici(_istemci(home), str(tmp_path / "yok.json")).yukle()
    assert (s.kaynak, s.cfg) == ("env", None)


def test_bozuk_lkg_yok_sayilir(tmp_path: Path) -> None:
    lkg = tmp_path / "lkg.json"
    lkg.write_text("{bozuk")
    assert y.lkg_oku(str(lkg)) is None


def test_sozlesme_disi_yanit_lkg_kalir(tmp_path: Path) -> None:
    lkg = str(tmp_path / "lkg.json")
    y.Yukleyici(_istemci(SahteHome()), lkg).yukle()
    home = SahteHome(yanit={"etag": "v3", "project": "yanlis"})
    s = y.Yukleyici(_istemci(home), lkg).yukle()
    assert s.kaynak == "lkg"


def test_env_gorunumu_degerler_ve_sirlar() -> None:
    home = SahteHome()
    cfg = _istemci(home).cek()
    assert cfg is not None
    yalniz_env = y.env_gorunumu(cfg)
    assert yalniz_env.degerler == {
        "JIRA_PROJECT": "TPD", "TP_DENETIM_KAPISI": "on", "TP_CT_SON_KOSU": "25",
    }  # fmt: skip
    coz = y.SecretManagerCozucu(lambda: "at", home, SM_PROJESI)
    g = y.env_gorunumu(cfg, coz, sir_projesi=SM_PROJESI)
    assert g.degerler["JIRA_READ_TOKEN"] == "gizli-deger"
    _m, url, bas, _g = home.istekler[-1]
    assert url.endswith(f"/v1/{REF}:access") and bas["Authorization"] == "Bearer at"


def test_korunan_ve_gecersiz_anahtarlar_reddedilir() -> None:
    cfg = y.EtkinConfig.coz(
        ornek_yanit(
            env={
                "TP_DATABASE_URL": "postgresql://kotu",
                "AIPROBE_HOME_RUN_URL": "https://saldirgan",
                "CONFIG_SOURCE": "env",
                "TP_TEST_TEK_HESAP": "1",
                "TP_PORTAL_PORT": "1",
                "kucuk_harf": "x",
                "SATIR": "a\nKOTU=1",
                "LISTE": ["a", "b"],
                "BAYRAK": True,
            },
            env_secrets={
                "TP_SESSION_SECRET": REF,
                "JIRA_READ_TOKEN": "projects/x/secrets/baska/versions/1",
            },
        )
    )
    g = y.env_gorunumu(cfg, lambda ref: "x", sir_projesi=SM_PROJESI)
    assert g.degerler == {"LISTE": "a,b", "BAYRAK": "1"}
    assert set(g.reddedilen) >= {
        "TP_DATABASE_URL", "AIPROBE_HOME_RUN_URL", "CONFIG_SOURCE", "TP_TEST_TEK_HESAP",
        "TP_PORTAL_PORT", "kucuk_harf", "SATIR", "TP_SESSION_SECRET", "JIRA_READ_TOKEN",
    }  # fmt: skip


def test_sir_ref_proje_denetimi() -> None:
    assert y.sir_ref_gecerli(REF, SM_PROJESI)
    assert y.sir_ref_gecerli(REF, None)
    assert not y.sir_ref_gecerli(REF, "baska-proje")
    assert not y.sir_ref_gecerli("projects/p/secrets/tp-env/versions/latest")
    coz = y.SecretManagerCozucu(lambda: "at", SahteHome(), "baska-proje")
    with pytest.raises(y.Reddedildi):
        coz(REF)


def test_cozulemeyen_sir_env_degeri_kalir() -> None:
    home = SahteHome(sirlar={})
    cfg = _istemci(home).cek()
    assert cfg is not None
    g = y.env_gorunumu(cfg, y.SecretManagerCozucu(lambda: "at", home), sir_projesi=SM_PROJESI)
    assert "JIRA_READ_TOKEN" not in g.degerler and g.cozulemeyen == ["JIRA_READ_TOKEN"]


def test_env_dosyasi_birlestir() -> None:
    taban = "# yorum\nJIRA_PROJECT=ESKI\nKALAN=1\nexport TP_CT_SON_KOSU='5'\n"
    metin, yazilamayan = y.env_dosyasi_birlestir(
        taban, {"JIRA_PROJECT": "TPD", "TP_CT_SON_KOSU": "25", "TIRNAK": "a'b", "KOTU": "a'$b"}
    )
    assert yazilamayan == ["KOTU"]
    assert "JIRA_PROJECT=ESKI" not in metin and "KALAN=1" in metin
    cozulmus = y.env_metni_coz(metin)
    assert cozulmus["JIRA_PROJECT"] == "TPD" and cozulmus["TIRNAK"] == "a'b"
    assert cozulmus["TP_CT_SON_KOSU"] == "25" and cozulmus["KALAN"] == "1"
    # Kendi üzerine yeniden üretim: eski blok tekrarlanmaz.
    metin2, _ = y.env_dosyasi_birlestir(metin, {"JIRA_PROJECT": "TPD"})
    assert metin2.count(y.BLOK_BASI) == 1 and "TIRNAK" not in metin2


def test_cli_env_kipinde_dosyaya_dokunmaz(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("CONFIG_SOURCE=env\nJIRA_PROJECT=X\n")
    home = SahteHome()
    assert cli.calistir(str(env), str(tmp_path / "lkg.json"), http=home) == 0
    assert env.read_text() == "CONFIG_SOURCE=env\nJIRA_PROJECT=X\n"
    assert home.istekler == []


def _home_env(tmp_path: Path) -> Path:
    env = tmp_path / ".env"
    env.write_text(
        "CONFIG_SOURCE=home\nTP_HOME_PROJECT=aaaabbbbcccc\n"
        f"AIPROBE_HOME_RUN_URL={HOME}\nSECRETS_PROJECT={SM_PROJESI}\n"
        "JIRA_PROJECT=ESKI\nTP_DATABASE_URL=postgresql://dokunma\n"
    )
    os.chmod(env, 0o600)
    return env


def test_cli_home_kipinde_env_dosyasini_uretir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = _home_env(tmp_path)
    home = SahteHome()
    home.yanit["env"]["TP_DATABASE_URL"] = "postgresql://kotu"
    lkg = tmp_path / "lkg.json"
    assert cli.calistir(str(env), str(lkg), http=home, kimlik=y.MetadataKimligi(home)) == 0
    sonuc = y.env_metni_coz(env.read_text())
    assert sonuc["JIRA_PROJECT"] == "TPD"
    assert sonuc["JIRA_READ_TOKEN"] == "gizli-deger"
    assert sonuc["TP_DATABASE_URL"] == "postgresql://dokunma"  # korunan
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    cikti = capsys.readouterr()
    assert "gizli-deger" not in cikti.out + cikti.err
    assert "kaynak=home" in cikti.out
    # Home kapalı: LKG ile aynı sonuç (sır yine Secret Manager'dan).
    env2 = _home_env(tmp_path)
    home2 = SahteHome(kapali=True)
    assert cli.calistir(str(env2), str(lkg), http=home2, kimlik=y.MetadataKimligi(home2)) == 0
    assert y.env_metni_coz(env2.read_text())["JIRA_PROJECT"] == "TPD"
    assert "kaynak=lkg" in capsys.readouterr().out


def test_cli_home_ve_lkg_yok_acilis_durur(tmp_path: Path) -> None:
    """SRE m2: `home` kipinde Home da LKG de yoksa çıkış ≠ 0 (up.sh açılışı durdurur); dosya
    değişmez. env kipinde aynı durum 0 (bkz. test_cli_env_kipinde_dosyaya_dokunmaz)."""
    env = _home_env(tmp_path)
    once = env.read_text()
    home = SahteHome(kapali=True)
    rc = cli.calistir(
        str(env), str(tmp_path / "yok.json"), http=home, kimlik=y.MetadataKimligi(home)
    )
    assert rc == cli.CIKIS_HOME_YOK and env.read_text() == once


def test_cli_home_reddederse_lkg_ile_acilmaz(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """N4: açılışta Home 403 → LKG olsa da açılış durur; env dosyası değişmez."""
    lkg = tmp_path / "lkg.json"
    env = _home_env(tmp_path)
    home = SahteHome()
    assert cli.calistir(str(env), str(lkg), http=home, kimlik=y.MetadataKimligi(home)) == 0
    env2 = _home_env(tmp_path)
    once = env2.read_text()
    home2 = SahteHome(durum=403, yanit=ornek_yanit(etag="v9"))
    rc = cli.calistir(str(env2), str(lkg), http=home2, kimlik=y.MetadataKimligi(home2))
    assert rc == cli.CIKIS_HOME_YOK and env2.read_text() == once
    assert "reddetti" in capsys.readouterr().err
    assert not lkg.exists()


def test_cli_home_kipinde_proje_eksikse_acilis_durur(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(f"CONFIG_SOURCE=home\nAIPROBE_HOME_RUN_URL={HOME}\n")
    home = SahteHome()
    assert cli.calistir(str(env), None, http=home) == cli.CIKIS_HOME_YOK
    assert home.istekler == []


# ------------------------------------------------------------------ A1: hedef–sır bağı


def _gorunum(home: SahteHome, taban: dict[str, str] | None = None) -> y.EnvGorunumu:
    cfg = _istemci(home).cek()
    assert cfg is not None
    return y.env_gorunumu(
        cfg, y.SecretManagerCozucu(lambda: "at", home), sir_projesi=SM_PROJESI, taban=taban or {}
    )


def test_env_unset_uygulanir_ve_korunanlar_silinemez() -> None:
    home = SahteHome()
    home.yanit["env_unset"] = ["TP_FORGE_REMOTE_TOKEN", "GITHUB_MERGE_TOKEN", "TP_DATABASE_URL",
                               "JIRA_READ_TOKEN", "kotu ad"]  # fmt: skip
    g = _gorunum(home)
    # Bağlı sır (korunan GITHUB_MERGE_TOKEN dahil) silinir; Home'un verdiği sır da silinir
    # (silme kazanır); korunan başka bir ad ve geçersiz ad reddedilir.
    assert g.kaldirilan == ["GITHUB_MERGE_TOKEN", "JIRA_READ_TOKEN", "TP_FORGE_REMOTE_TOKEN"]
    assert "JIRA_READ_TOKEN" not in g.degerler
    assert {"TP_DATABASE_URL", "kotu ad"} <= set(g.reddedilen)


def test_env_unset_liste_degilse_sozlesme_hatasi() -> None:
    with pytest.raises(y.SozlesmeHatasi):
        y.EtkinConfig.coz(ornek_yanit(env_unset="GITHUB_TOKEN"))


def test_yerel_kural_hedef_homedan_gelirse_deployment_sirri_kullanilmaz() -> None:
    """Home `env_unset` göndermese bile: hedef Home'dan (varsayılan / Deployment değeri değil) ve
    sır Home'dan gelmiyorsa sır silinir — korunan GITHUB_MERGE_TOKEN ve TP_FORGE_REMOTE_TOKEN."""
    home = SahteHome()
    home.yanit["env"].update(
        {"GITHUB_API_URL": "https://kotu.example.test/api/v3",
         "TP_FORGE_REMOTE_URL": "https://kotu.example.test/r.git"}
    )  # fmt: skip
    g = _gorunum(home)
    assert {"GITHUB_MERGE_TOKEN", "GITHUB_TOKEN", "TP_FORGE_REMOTE_TOKEN"} <= set(g.kaldirilan)
    assert "JIRA_READ_TOKEN" in g.degerler  # Jira hedefi Home'dan değil


def test_yerel_kural_varsayilan_ya_da_ayni_hedefte_sir_kalir() -> None:
    home = SahteHome()
    home.yanit["env"].update(
        {"GITHUB_API_URL": "https://api.github.com/", "JIRA_BASE_URL": "https://ornek.example.test"}
    )
    # Hedef varsayılan (api.github.com) ve Jira hedefi Deployment'ın kendi değeriyle aynı.
    g = _gorunum(home, taban={"JIRA_BASE_URL": "https://ornek.example.test/"})
    assert g.kaldirilan == []
    # Jira hedefi farklı ama sır Home'dan çözüldü: kalır; çözülemeseydi taban değeri o hedefe
    # gitmesin diye silinirdi.
    home.yanit["env"]["JIRA_BASE_URL"] = "https://baska.example.test"
    assert "JIRA_READ_TOKEN" not in _gorunum(home).kaldirilan
    home.sirlar = {}
    g = _gorunum(home)
    assert "JIRA_READ_TOKEN" in g.kaldirilan and "JIRA_WRITE_TOKEN" in g.kaldirilan


def test_cli_kaldirilan_satirlari_env_dosyasindan_siler(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = _home_env(tmp_path)
    env.write_text(
        env.read_text()
        + "GITHUB_MERGE_TOKEN=insan-tokeni\nexport TP_FORGE_REMOTE_TOKEN='ayna'\nKALAN=1\n"
    )
    home = SahteHome()
    home.yanit["env"]["GITHUB_API_URL"] = "https://kotu.example.test"
    home.yanit["env_unset"] = ["TP_FORGE_REMOTE_TOKEN"]
    assert cli.calistir(str(env), str(tmp_path / "l.json"), http=home,
                        kimlik=y.MetadataKimligi(home)) == 0  # fmt: skip
    metin = env.read_text()
    sonuc = y.env_metni_coz(metin)
    assert "GITHUB_MERGE_TOKEN" not in sonuc and "TP_FORGE_REMOTE_TOKEN" not in sonuc
    assert "insan-tokeni" not in metin and sonuc["KALAN"] == "1"
    assert "kaldirilan=" in capsys.readouterr().out


def test_env_dosyasi_birlestir_kaldir() -> None:
    metin, _ = y.env_dosyasi_birlestir("A=1\nB=2\n", {"B": "3", "C": "4"}, ["A", "C"])
    assert y.env_metni_coz(metin) == {"B": "3"}
