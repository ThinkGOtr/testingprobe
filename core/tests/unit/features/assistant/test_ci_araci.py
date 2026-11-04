"""`ci_log` aracı, `log_yolu`, `GitHubCiOkuyucu` ve forge akışlı okuma (AI-ASISTAN-PLANI §5.7, §13).

Sahte token'lar çalışma anında birleştirilir (repo public; push koruması).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tp_core.features.assistant.tools import ci as araci
from tp_core.features.assistant.tools.base import AracBaglami, AracHatasi, AracSarmalayici
from tp_core.features.ci import artifacts, services
from tp_core.features.ci.clients import GitHubCiOkuyucu
from tp_core.gateway.masking import PiiMasker
from tp_core.integrations.forge_github import GitHubForge, TokenAuth

GHP = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
GHS = "gh" + "s_" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2"
JWT = "ey" + "JhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlLXZhbHVl"
CALISMA_SIRRI = "calisma-" + "ani-sir-degeri-42"
FORGE_TOKEN = "gh" + "p_" + "F0rgeT0kenF0rgeT0kenF0rgeT0ken12345"
KB = 1024


# ------------------------------------------------------------------ yardımcılar


def _baglam(engine: Engine, **ek: Any) -> AracBaglami:
    return AracBaglami(
        kullanici_id=uuid.uuid4(),
        rol="engineer",
        oturum=PiiMasker(enabled=True).new_session(),
        db=lambda: Session(engine),
        sir_degerleri=(CALISMA_SIRRI,),
        **ek,
    )


def _kosu(engine: Engine, **alan: Any) -> str:
    run_id = uuid.uuid4()
    deger = {
        "id": run_id,
        "kaynak": "local",
        "tetik": "manual",
        "sonuc": "failed",
        "github_run_id": None,
        "artefaktlar": {},
        **alan,
    }
    deger["artefaktlar"] = json.dumps(deger["artefaktlar"])
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO run (id, kaynak, tetik, sonuc, github_run_id, artefaktlar) "
                "VALUES (:id, :kaynak, :tetik, :sonuc, :github_run_id, "
                "CAST(:artefaktlar AS jsonb))"
            ),
            deger,
        )
    return str(run_id)


@pytest.fixture
def kokler(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    yerel = tmp_path / "artifacts"
    gh = tmp_path / "gh-artifacts"
    (yerel / "runs").mkdir(parents=True)
    gh.mkdir()
    with services.override(artifacts_root=lambda: yerel, github_artifacts_root=lambda: gh):
        yield yerel, gh


def _yaz(yol: Path, veri: bytes) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_bytes(veri)


# ------------------------------------------------------------------ işleme (saf)


def test_ansi_zaman_damgasi_ve_kontrol_temizlenir() -> None:
    ham = (
        b"2026-11-03T10:11:12.1234567Z \x1b[31mFAIL\x1b[0m sepet.spec.ts\r\n"
        b"\x1b]0;baslik\x07normal\x07 satir\n"
        b"bozuk \xff\xfe utf8\n"
    )
    out = araci.log_isle(ham, kirpildi=False, ara=None, satir=120)
    assert "1| FAIL sepet.spec.ts" in out
    assert "2| normal satir" in out
    assert "\x1b" not in out and "\x07" not in out and "2026-11-03T" not in out
    assert "bozuk �� utf8" in out


def test_kirpilmis_kuyrukta_ilk_yarim_satir_atilir() -> None:
    out = araci.log_isle(b"rim satir\ntam satir\n", kirpildi=True, ara=None, satir=120)
    assert "rim satir" not in out and "tam satir" in out


@pytest.mark.parametrize(
    "sir",
    [
        GHP,
        GHS,
        JWT,
        CALISMA_SIRRI,
        "https://kullanici:" + "parola123@forge.local/repo.git",
        "Authorization: Bearer " + "abcdef0123456789",
    ],
)
def test_sirlar_temizlenir(sir: str) -> None:
    ham = f"önce\nclone {sir} sonra\n".encode()
    out = araci.log_isle(ham, kirpildi=False, ara=None, satir=120, sir_degerleri=[CALISMA_SIRRI])
    assert sir not in out
    gizli = sir.split(":")[-1].split("@")[0][-10:]
    assert gizli not in out
    assert "***" in out


def test_kesme_sinirinda_yarim_calisma_sirri_temizlenir() -> None:
    # Kuyruk tam sırrın ortasından başlıyor: ilk yarım satır atılsa da sondaki yarım değer kalmaz.
    ham = b"x\nson satir " + CALISMA_SIRRI[:12].encode()
    out = araci.log_isle(ham, kirpildi=False, ara=None, satir=120, sir_degerleri=[CALISMA_SIRRI])
    assert CALISMA_SIRRI[:12] not in out


def test_ara_sabit_metin_regex_degil_ve_baglam() -> None:
    satirlar = [f"satir {i}" for i in range(30)]
    satirlar[10] = "hata: a.*b (x+)? [1]"
    satirlar[11] = "axxxb"  # regex olsaydı eşleşirdi
    ham = "\n".join(satirlar).encode()
    out = araci.log_isle(ham, kirpildi=False, ara="a.*b (x+)? [1]", satir=120)
    assert out.startswith("'a.*b (x+)? [1]' için 1 eşleşme")
    assert "8| satir 7" in out and "14| satir 13" in out
    assert "7| satir 6" not in out and "15| satir 14" not in out


def test_ara_50_eslesme_siniri() -> None:
    ham = "\n".join(f"HATA {i}" for i in range(80)).encode()
    out = araci.log_isle(ham, kirpildi=False, ara="hata", satir=120)
    assert "için 50 eşleşme" in out
    assert "… 30 eşleşme daha" in out
    # 50. eşleşmenin ±3 bağlamı görünür; sonrası yok.
    assert "50| HATA 49" in out and "53| HATA 52" in out and "HATA 53" not in out


def test_satir_ve_16kb_siniri() -> None:
    ham = "\n".join(f"satir-{i}-" + "y" * 200 for i in range(1000)).encode()
    out = araci.log_isle(ham, kirpildi=False, ara=None, satir=200)
    assert len(out.encode()) <= 16 * KB + 64
    assert "satir-999-" in out and "satir-799-" not in out
    out = araci.log_isle(ham, kirpildi=False, ara=None, satir=20)
    assert "satir-980-" in out and "satir-979-" not in out


def test_ikili_icerik_cokmez() -> None:
    out = araci.log_isle(bytes(range(256)) * 50, kirpildi=False, ara=None, satir=120)
    assert isinstance(out, str)
    assert "\x00" not in out


# ------------------------------------------------------------------ log_yolu + araç (DB)


def test_yerel_log_okunur_ve_256kb_kuyruk(engine: Engine, kokler) -> None:
    yerel, _ = kokler
    govde = b"".join(b"satir %06d\n" % i for i in range(40_000))  # ~480 KB
    _yaz(yerel / "runs/r1/runner.log", govde + f"son: {GHP}\n".encode())
    run_id = _kosu(engine, artefaktlar={"dizin": "runs/r1", "log": "runner.log"})
    sonuc = araci.ci_log(_baglam(engine), run_id=run_id, satir=20)
    assert sonuc.kanit_turu == "ci_log" and sonuc.tur == "ci_log"
    assert "[Log: yerel log]" in sonuc.metin
    assert "son: ***" in sonuc.metin and GHP not in sonuc.metin
    assert "satir 039999" in sonuc.metin and "satir 039980" not in sonuc.metin
    assert len(sonuc.metin.encode()) <= 16 * KB


def test_github_yerel_kopyasi_okunur(engine: Engine, kokler) -> None:
    _, gh = kokler
    yol = "src/e2e/results/run-checks.log"
    _yaz(gh / "gh/555-1" / yol, b"lint: 3 error\nFAILED\n")
    run_id = _kosu(
        engine,
        kaynak="github",
        github_run_id="555",
        artefaktlar={
            "github_yerel": {"dizin": "gh/555-1", "durum": "indirildi", "yollar": {"log": yol}}
        },
    )
    metin = araci.ci_log(_baglam(engine), run_id=run_id, ara="FAILED").metin
    assert "[Log: GitHub logunun yerel kopyası]" in metin
    assert "2| FAILED" in metin


def test_yolu_olmayan_kosu_log_yok_ve_db_ozeti(engine: Engine, kokler) -> None:
    run_id = _kosu(
        engine,
        artefaktlar={
            "conclusion": "failure",
            "basarisiz_adimlar": ["eslint"],
            "adimlar": {
                "eslint": {"ok": False, "atlandi": False, "error": "no-unused-vars x3"},
                "run": {"ok": False, "atlandi": True, "reason": "önceki adım başarısız"},
                "tsc": {"ok": True, "atlandi": False},
            },
            "uyarilar": ["Testler koşmadı: önceki CI adımı başarısız."],
        },
    )
    metin = araci.ci_log(_baglam(engine), run_id=run_id).metin
    assert "Başarısız adımlar: eslint" in metin
    assert "Adım eslint: error: no-unused-vars x3" in metin
    assert "Adım run: atlandı; reason: önceki adım başarısız" in metin
    assert "Adım tsc" not in metin
    assert metin.endswith("[Log: -]\nlog yok")


@pytest.mark.parametrize("log", ["../../etc/passwd", "src/../runner.log", "/etc/passwd", "x.log"])
def test_kacis_yolu_reddedilir(engine: Engine, kokler, log: str) -> None:
    yerel, _ = kokler
    _yaz(yerel / "runs/r2/runner.log", b"gizli degil\n")
    run_id = _kosu(engine, artefaktlar={"dizin": "runs/r2", "log": log})
    metin = araci.ci_log(_baglam(engine), run_id=run_id).metin
    assert metin.endswith(araci.MESAJ_LOG_OKUNAMADI)


def test_symlink_log_disariya_reddedilir(engine: Engine, kokler, tmp_path: Path) -> None:
    yerel, _ = kokler
    disari = tmp_path / "disari.txt"
    disari.write_text("DISARIDAKI SIR\n")
    (yerel / "runs/r3").mkdir(parents=True)
    os.symlink(disari, yerel / "runs/r3/runner.log")
    run_id = _kosu(engine, artefaktlar={"dizin": "runs/r3", "log": "runner.log"})
    metin = araci.ci_log(_baglam(engine), run_id=run_id).metin
    assert "DISARIDAKI" not in metin and metin.endswith(araci.MESAJ_LOG_OKUNAMADI)


def test_kontrol_sonrasi_ara_dizin_symlinke_cevrilirse_okunmaz(
    engine: Engine, kokler, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    yerel, _ = kokler
    yol = "src/e2e/results/run.log"
    _yaz(yerel / "runs/r4" / yol, b"asil log\n")
    sahte = tmp_path / "sahte-results"
    _yaz(sahte / "run.log", b"SALDIRGAN ICERIK\n")
    gercek_coz = artifacts.coz

    def coz_sonra_degistir(kok: Path, istek: str) -> Path:
        hedef = gercek_coz(kok, istek)
        sonuc_dizini = yerel / "runs/r4/src/e2e/results"
        sonuc_dizini.rename(yerel / "runs/r4/src/e2e/eski")
        os.symlink(sahte, sonuc_dizini)
        return hedef

    monkeypatch.setattr(artifacts, "coz", coz_sonra_degistir)
    run_id = _kosu(engine, artefaktlar={"dizin": "runs/r4", "log": yol})
    metin = araci.ci_log(_baglam(engine), run_id=run_id).metin
    assert "SALDIRGAN" not in metin and "asil log" not in metin
    assert metin.endswith(araci.MESAJ_LOG_OKUNAMADI)


def test_kontrol_sonrasi_dosya_degistirilirse_inode_uyusmaz(
    engine: Engine, kokler, monkeypatch: pytest.MonkeyPatch
) -> None:
    yerel, _ = kokler
    _yaz(yerel / "runs/r5/runner.log", b"ilk\n")
    gercek_stat = os.stat
    cagrildi = []

    def stat_sonra_degistir(yol: Any, *a: Any, **k: Any) -> os.stat_result:
        sonuc = gercek_stat(yol, *a, **k)
        if str(yol).endswith("runs/r5/runner.log") and not cagrildi:
            cagrildi.append(1)
            Path(yol).unlink()
            Path(yol).write_bytes(b"YENI DOSYA\n")
        return sonuc

    monkeypatch.setattr(araci.os, "stat", stat_sonra_degistir)
    run_id = _kosu(engine, artefaktlar={"dizin": "runs/r5", "log": "runner.log"})
    metin = araci.ci_log(_baglam(engine), run_id=run_id).metin
    assert cagrildi and "YENI DOSYA" not in metin
    assert metin.endswith(araci.MESAJ_LOG_OKUNAMADI)


def test_bilinmeyen_kosu_ve_gecersiz_argumanlar(engine: Engine, kokler) -> None:
    b = _baglam(engine)
    with pytest.raises(AracHatasi, match="bulunamadı"):
        araci.ci_log(b, run_id=str(uuid.uuid4()))
    for arg in (
        {"run_id": "1; DROP TABLE run"},
        {"run_id": str(uuid.uuid4()), "ara": "x" * 81},
        {"run_id": str(uuid.uuid4()), "ara": "a\nb"},
        {"run_id": str(uuid.uuid4()), "yol": "/etc/passwd"},
    ):
        with pytest.raises(AracHatasi):
            araci.ci_log(b, **arg)


def test_sarmalayici_ile_untrusted_ve_maskeli(engine: Engine, kokler) -> None:
    yerel, _ = kokler
    _yaz(yerel / "runs/r6/runner.log", f"hata ali@ornek.com {GHP}\n".encode())
    run_id = _kosu(engine, artefaktlar={"dizin": "runs/r6", "log": "runner.log"})
    cikti = AracSarmalayici(_baglam(engine), yeni=araci.ARACLAR)("ci_log", {"run_id": run_id})
    assert cikti.startswith("[kanit:k1]") and '<untrusted kind="ci_log"' in cikti
    assert "ali@ornek.com" not in cikti and "<<PII_EMAIL_1>>" in cikti
    assert GHP not in cikti


# ------------------------------------------------------------------ GitHub (sahte forge)


class SahteGitHub:
    def __init__(self, log_govdesi: Any = b"", jobs: list[dict[str, Any]] | None = None) -> None:
        self.istekler: list[httpx.Request] = []
        self.log_govdesi = log_govdesi
        self.jobs = jobs or [
            {"id": 1, "name": "ast-guard", "conclusion": "success"},
            {"id": 7, "name": "test-local", "conclusion": "failure"},
        ]

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.istekler.append(req)
        yol = req.url.path
        if yol.endswith("/actions/runs/555/jobs"):
            return httpx.Response(200, json={"jobs": self.jobs})
        if yol.endswith("/logs"):
            return httpx.Response(
                302, headers={"Location": f"https://blob.ornek.net/log{yol.split('/')[-2]}"}
            )
        if req.url.host == "blob.ornek.net":
            govde = self.log_govdesi
            return httpx.Response(200, content=govde() if callable(govde) else govde)
        return httpx.Response(404, json={"message": "yok"})


def _okuyucu(sahte: SahteGitHub) -> GitHubCiOkuyucu:
    forge = GitHubForge(
        "ornek/uygulama",
        TokenAuth(FORGE_TOKEN),
        api_url="https://api.github.com",
        transport=httpx.MockTransport(sahte),
    )
    return GitHubCiOkuyucu(forge)


def test_okuyucuda_dispatch_yok() -> None:
    ok = _okuyucu(SahteGitHub())
    for ad in ("repository_dispatch", "workflow_dispatch", "artifact_zip", "artifacts"):
        assert not hasattr(ok, ad)


def test_job_logs_yonlendirmede_authorization_duser() -> None:
    sahte = SahteGitHub(b"log satiri\n")
    kuyruk = _okuyucu(sahte).job_logs(7)
    assert kuyruk.veri == b"log satiri\n" and not kuyruk.kirpildi and kuyruk.kesildi is None
    api, blob = sahte.istekler
    assert api.headers["Authorization"] == f"Bearer {FORGE_TOKEN}"
    assert blob.url.host == "blob.ornek.net"
    assert "Authorization" not in blob.headers


def test_content_length_siz_buyuk_akis_20mb_de_kesilir() -> None:
    uretilen = []

    def sonsuz() -> Iterator[bytes]:
        parca = (b"z" * 1023 + b"\n") * 1024  # 1 MB
        while True:
            uretilen.append(1)
            yield parca

    kuyruk = _okuyucu(SahteGitHub(sonsuz)).job_logs(7)
    assert kuyruk.kesildi == "boyut"
    assert kuyruk.okunan == 20 * 1024 * KB
    assert len(kuyruk.veri) == 256 * KB and kuyruk.kirpildi
    assert len(uretilen) <= 21


def test_sure_dolunca_akis_kesilir() -> None:
    zaman = [0.0]

    def akis() -> Iterator[bytes]:
        for _ in range(100):
            zaman[0] += 1.0
            yield b"x\n" * 100

    forge = GitHubForge(
        "ornek/uygulama",
        TokenAuth(FORGE_TOKEN),
        transport=httpx.MockTransport(SahteGitHub(akis)),
    )
    kuyruk = GitHubCiOkuyucu(forge, saat=lambda: zaman[0]).job_logs(7, sure_s=5)
    assert kuyruk.kesildi == "sure"


def test_actions_read_token_varsa_o_kullanilir() -> None:
    sahte = SahteGitHub()
    tok = "gh" + "p_" + "ActionsReadOnlyToken0123456789abcd"
    ok = GitHubCiOkuyucu.kur(
        {"GITHUB_ACTIONS_READ_TOKEN": tok, "GITHUB_REPO": "ornek/uygulama"},
        transport=httpx.MockTransport(sahte),
    )
    ok.jobs(555)
    assert sahte.istekler[0].headers["Authorization"] == f"Bearer {tok}"
    okuma = "gh" + "p_" + "ContentsReadToken0123456789abcdefgh"
    ok = GitHubCiOkuyucu.kur(
        {"GITHUB_READ_TOKEN": okuma, "GITHUB_TOKEN": FORGE_TOKEN, "GITHUB_REPO": "ornek/uygulama"},
        transport=httpx.MockTransport(sahte),
    )
    ok.jobs(555)
    assert sahte.istekler[-1].headers["Authorization"] == f"Bearer {okuma}"


def test_okuma_tokeni_yoksa_forge_kimligi_uyariyla(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """İki okuma token'ı da boşsa forge kimliğine düşülür ve en az yetki sapması loglanır."""
    sahte = SahteGitHub()
    forge = _okuyucu(sahte)._forge
    monkeypatch.setattr(services, "forge", lambda: forge)
    with caplog.at_level(logging.WARNING, logger="tp_core.ci"):
        ok = GitHubCiOkuyucu.kur({"GITHUB_TOKEN": FORGE_TOKEN, "GITHUB_REPO": "ornek/uygulama"})
    assert ok._forge is forge
    uyari = [r.getMessage() for r in caplog.records if r.name == "tp_core.ci"]
    assert uyari and "forge kimliği" in uyari[0] and FORGE_TOKEN not in uyari[0]
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="tp_core.ci"):
        GitHubCiOkuyucu.kur(
            {"GITHUB_READ_TOKEN": "gh" + "p_" + "x" * 36, "GITHUB_REPO": "ornek/uygulama"}
        )
    assert not [r for r in caplog.records if r.name == "tp_core.ci"]


def test_ci_log_github_yedegi_basarisiz_job_once(
    engine: Engine, kokler, monkeypatch: pytest.MonkeyPatch
) -> None:
    govde = b"".join(b"2026-11-03T10:00:%02d.0000000Z adim %d\n" % (i % 60, i) for i in range(300))
    sahte = SahteGitHub(govde + f"token={GHS}\n".encode())
    monkeypatch.setattr(araci, "github_okuyucu", lambda: _okuyucu(sahte))
    run_id = _kosu(engine, kaynak="github", github_run_id="555", artefaktlar={})
    metin = araci.ci_log(_baglam(engine), run_id=run_id, satir=20).metin
    assert "[Log: GitHub job 'test-local' (failure)]" in metin
    assert "adim 299" in metin and "2026-11-03T10" not in metin
    assert GHS not in metin and "token=***" in metin
    assert sahte.istekler[1].url.path.endswith("/actions/jobs/7/logs")
    assert {r.method for r in sahte.istekler} == {"GET"}


def test_ci_log_github_hatasi_log_alinamadi(
    engine: Engine, kokler, monkeypatch: pytest.MonkeyPatch
) -> None:
    def patlayan() -> GitHubCiOkuyucu:
        raise RuntimeError(f"kimlik {FORGE_TOKEN}")

    monkeypatch.setattr(araci, "github_okuyucu", patlayan)
    run_id = _kosu(engine, kaynak="github", github_run_id="555", artefaktlar={})
    metin = araci.ci_log(_baglam(engine), run_id=run_id).metin
    assert metin.endswith(araci.MESAJ_LOG_ALINAMADI) and FORGE_TOKEN not in metin


def test_log_yolu_yerel_ve_github(kokler) -> None:
    from tp_core.features.ci.service import log_yolu
    from tp_core.models.delivery import Run

    yerel, gh = kokler
    r = Run(kaynak="local", artefaktlar={"dizin": "runs/a", "log": "runner.log"})
    assert log_yolu(r) == (yerel / "runs/a", "runner.log")
    r = Run(kaynak="local", artefaktlar={"dizin": "../x", "log": "runner.log"})
    assert log_yolu(r) is None
    gy = {"dizin": "gh/9-1", "durum": "mevcut", "yollar": {"log": "src/e2e/results/r.log"}}
    r = Run(kaynak="github", artefaktlar={"github_yerel": gy})
    assert log_yolu(r) == (gh / "gh/9-1", "src/e2e/results/r.log")
    r = Run(kaynak="github", artefaktlar={"github_yerel": {**gy, "durum": "budandi"}})
    assert log_yolu(r) is None
    r = Run(kaynak="github", artefaktlar={"github_yerel": {**gy, "yollar": {"log": "../x"}}})
    assert log_yolu(r) is None
