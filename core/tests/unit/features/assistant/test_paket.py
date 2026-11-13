"""Ürün bilgi paketi üretici: izin/hariç listesi, MANIFEST, sır taraması (AI-ASISTAN-PLANI §5.1).

Repo public: sahte token'lar çalışma anında birleştirilerek üretilir.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from tp_core.features.assistant import paket
from tp_core.features.assistant.paket import (
    MANIFEST_ADI,
    env_degerleri,
    main,
    secilir_mi,
    uret,
)

GOVDE = "A1b2C3d4E5f6G7h8J9k0Lm"


@pytest.mark.parametrize(
    "yol",
    [
        "review-portal/src/App.tsx",
        "review-portal/src/api/client.ts",
        "review-portal/src/styles/tema.css",
        "core/src/tp_core/worker/__init__.py",
        "core/src/tp_core/features/assistant/flow.py",
        "docs/ONBOARDING.md",
        "docs/GERCEK-SISTEMLER.md",
        "README.md",
        "rules/assistant/oneriler.yaml",
    ],
)
def test_izin_listesi(yol: str) -> None:
    assert secilir_mi(yol)


@pytest.mark.parametrize(
    "yol",
    [
        # hariç listesi
        "review-portal/src/pages/sayfa.test.tsx",
        "review-portal/src/api/mock/handlers.ts",
        "core/src/tp_core/x/tests/a.py",
        "core/src/tp_core/x/test/a.py",
        "core/src/tp_core/x/fixtures/veri.py",
        "review-portal/src/node_modules/x/index.ts",
        "review-portal/src/dist/a.css",
        "docs/DAHILI-Notlar.md",
        # spec 013 K7: dedektör desenleri ve uygulayan modüller
        "rules/assistant/sinyaller.yaml",
        "rules/assistant/istem-izleri.yaml",
        "core/src/tp_core/features/assistant/guvenlik.py",
        "core/src/tp_core/features/assistant/guvenlik_cikti.py",
        ".env",
        ".env.example",
        "core/src/tp_core/.env.py",
        # izin listesinde değil
        "docs/AI-ASISTAN-PLANI.md",
        "docs/sunumlar/sunum.md",
        "docs/teklif.docx",
        "core/tests/unit/test_a.py",
        "core/pyproject.toml",
        "deploy/gcp/kurulum.sh",
        "rules/models.yaml",
        "rules/assistant/alt/x.yaml",
        "review-portal/src/App.js",
        "readme.md",
    ],
)
def test_haric_ve_izin_disi(yol: str) -> None:
    assert not secilir_mi(yol)


def _repo(kok: Path) -> Path:
    dosyalar = {
        "README.md": "# Testing Probe\nÜrün özeti.\n",
        "docs/ONBOARDING.md": "Kurulum: make up\nSEED_USER_PASSWORD=Demo123!\n",
        "docs/DAHILI-Notlar.md": "gizli not\n",
        "docs/AI-ASISTAN-PLANI.md": "plan\n",
        "core/src/tp_core/a.py": "def f():\n    return 1\n",
        "core/src/tp_core/tests/b.py": "x = 1\n",
        "review-portal/src/App.tsx": "export const App = () => null;\n",
        "review-portal/src/App.test.tsx": "test\n",
        "review-portal/src/api/mock/handlers.ts": "mock\n",
        "rules/assistant/oneriler.yaml": "kurallar: []\n",
        # belgelerdeki yer tutucu örnekleri bulgu değildir
        "docs/GERCEK-SISTEMLER.md": (
            "JIRA_READ_TOKEN=<okuma API token'ı>\n"
            "Authorization: Bearer $TP_TOOLCHAIN_TOKEN\n"
            "postgresql+psycopg://tp_app:${TP_APP_PASSWORD}@postgres:5432/tp\n"
            "`Authorization: Bearer tpt_...`\n"
            "JIRA_WRITE_TOKEN=sim\n"
        ),
    }
    for yol, metin in dosyalar.items():
        p = kok / yol
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(metin, encoding="utf-8")
    return kok


def test_uretim_manifest_ve_dosyalar(tmp_path: Path) -> None:
    kaynak = _repo(tmp_path / "repo")
    cikti = tmp_path / "out"
    sonuc = uret(kaynak, cikti, commit="abc123def4567890", ortam_degerleri=[])
    assert not sonuc.bulgular
    manifest = json.loads((cikti / MANIFEST_ADI).read_text(encoding="utf-8"))
    assert manifest["commit"] == "abc123def4567890"
    assert sorted(manifest["dosyalar"]) == [
        "README.md",
        "core/src/tp_core/a.py",
        "docs/GERCEK-SISTEMLER.md",
        "docs/ONBOARDING.md",
        "review-portal/src/App.tsx",
        "rules/assistant/oneriler.yaml",
    ]
    for yol, kayit in manifest["dosyalar"].items():
        kopya = cikti / manifest["dizin"] / yol
        veri = kopya.read_bytes()
        assert veri == (kaynak / yol).read_bytes()
        assert kayit["sha256"] == hashlib.sha256(veri).hexdigest()
        assert kayit["boyut"] == len(veri)
    assert manifest["dosyalar"]["core/src/tp_core/a.py"]["satir"] == 2
    assert sonuc.dosya_sayisi == 6


def test_yeniden_uretim_atomik_ve_eski_surum_temizlenir(tmp_path: Path) -> None:
    kaynak = _repo(tmp_path / "repo")
    cikti = tmp_path / "out"
    dizinler = []
    for _ in range(4):
        uret(kaynak, cikti, ortam_degerleri=[])
        dizinler.append(json.loads((cikti / MANIFEST_ADI).read_text("utf-8"))["dizin"])
    kalan = sorted(p.name for p in (cikti / "surumler").iterdir())
    # geçerli + bir önceki (o anda okuyan çağrı için) tutulur
    assert len(kalan) == 2
    assert dizinler[-1].split("/")[1] in kalan and dizinler[-2].split("/")[1] in kalan
    assert not [p for p in cikti.iterdir() if p.name.startswith(".")]


def test_symlink_pakete_alinmaz(tmp_path: Path) -> None:
    kaynak = _repo(tmp_path / "repo")
    disari = tmp_path / "disari.py"
    disari.write_text("SIR = 1\n", encoding="utf-8")
    os.symlink(disari, kaynak / "core/src/tp_core/link.py")
    os.symlink(tmp_path, kaynak / "core/src/tp_core/linkdizin")
    sonuc = uret(kaynak, tmp_path / "out", ortam_degerleri=[])
    manifest = json.loads((tmp_path / "out" / MANIFEST_ADI).read_text("utf-8"))
    assert "core/src/tp_core/link.py" not in manifest["dosyalar"]
    assert not any("linkdizin" in k for k in manifest["dosyalar"])
    assert any("link.py" in u for u in sonuc.uyarilar)


def test_utf8_olmayan_dosya_alinmaz(tmp_path: Path) -> None:
    kaynak = _repo(tmp_path / "repo")
    (kaynak / "core/src/tp_core/ikili.py").write_bytes(b"\xff\xfe\x00bozuk")
    sonuc = uret(kaynak, tmp_path / "out", ortam_degerleri=[])
    assert (
        "core/src/tp_core/ikili.py"
        not in json.loads((tmp_path / "out" / MANIFEST_ADI).read_text("utf-8"))["dosyalar"]
    )
    assert any("ikili.py" in u for u in sonuc.uyarilar)


@pytest.mark.parametrize(
    "sir",
    [
        "gh" + "p_" + GOVDE,
        "sk-" + "ant-api03-" + GOVDE,
        "-----BEGIN "
        + "OPENSSH PRIVATE KEY-----\n"
        + GOVDE
        + "\n-----END "
        + "OPENSSH PRIVATE KEY-----",
        "TP_SESSION_SECRET=" + GOVDE,
        "https://ali:" + GOVDE + "@forge.local/r.git",
    ],
)
def test_desen_bulgusu_uretimi_dusurur(tmp_path: Path, sir: str) -> None:
    kaynak = _repo(tmp_path / "repo")
    (kaynak / "core/src/tp_core/a.py").write_text(f"x = 1\n# {sir}\n", encoding="utf-8")
    cikti = tmp_path / "out"
    sonuc = uret(kaynak, cikti, ortam_degerleri=[])
    assert sonuc.bulgular
    assert sonuc.bulgular[0].yol == "core/src/tp_core/a.py"
    assert sonuc.bulgular[0].satir == 2
    assert not (cikti / MANIFEST_ADI).exists()
    assert not (cikti / "surumler").exists()


def test_env_degeri_bulgusu_ve_cikis_kodu(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paket, "known_secret_values", lambda: [])
    kaynak = _repo(tmp_path / "repo")
    deger = "Pg" + "x7Kq2LmZ"  # .env'deki rastgele parola (desene uymaz)
    (kaynak / ".env").write_text(
        f"DEMOAPP_RO_PASSWORD={deger}\nTP_PII_MASKING=false\nTP_AGENT_DEALER_PASSWORD=Demo123!\n",
        encoding="utf-8",
    )
    (kaynak / "docs/ONBOARDING.md").write_text(f"parola: {deger}\n", encoding="utf-8")
    kod = main(["--kaynak", str(kaynak), "--cikti", str(tmp_path / "out")])
    cikti = capsys.readouterr()
    assert kod == 2
    assert "docs/ONBOARDING.md:1: known_value" in cikti.err
    assert deger not in cikti.out + cikti.err
    assert not (tmp_path / "out" / MANIFEST_ADI).exists()


def test_demo_parolasi_pakette_kalabilir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paket, "known_secret_values", lambda: ["Demo123!"])
    kaynak = _repo(tmp_path / "repo")
    (kaynak / ".env").write_text("SEED_USER_PASSWORD=Demo123!\n", encoding="utf-8")
    kod = main(["--kaynak", str(kaynak), "--cikti", str(tmp_path / "out"), "--commit", "abc"])
    assert kod == 0, capsys.readouterr().err
    assert "Bilgi paketi hazır: 6 dosya" in capsys.readouterr().out


def test_calisma_ani_ortam_degeri_bulgusu(tmp_path: Path) -> None:
    kaynak = _repo(tmp_path / "repo")
    deger = "Rt" + "9vWq3ZkPa"
    (kaynak / "README.md").write_text(f"a\nb {deger}\n", encoding="utf-8")
    sonuc = uret(kaynak, tmp_path / "out", ortam_degerleri=[deger])
    assert [(b.yol, b.satir, b.tur) for b in sonuc.bulgular] == [("README.md", 2, "known_value")]


def test_env_degerleri_filtresi(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "# yorum",
                "TP_APP_PASSWORD='Uz" + "unParola9'",
                "JIRA_WRITE_TOKEN=sim",
                "TP_PII_MASKING=false",
                "TP_PORTAL_PORT=8080",
                "TP_PUBLIC_BASE_URL=http://127.0.0.1:8080",
                "TP_MODEL=claude-sonnet-4-5-20250929",
                "TP_CI_NIGHTLY_SAAT=02:00:00:00",
                "SEED_USER_PASSWORD=Demo123!",
                "BIR_DEGER=Xk" + "9pQ2mZr7Lw4Tn8Yb",  # adı sır değil ama rastgele görünümlü
                'export GITHUB_TOKEN="Gh' + GOVDE + '"',
            ]
        ),
        encoding="utf-8",
    )
    assert env_degerleri(env) == [
        "Uz" + "unParola9",
        "Xk" + "9pQ2mZr7Lw4Tn8Yb",
        "Gh" + GOVDE,
    ]
    assert env_degerleri(tmp_path / "yok") == []


def test_kaynak_yoksa_cikis_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--kaynak", str(tmp_path / "yok"), "--cikti", str(tmp_path / "out")]) == 1
    assert "HATA" in capsys.readouterr().err
    (tmp_path / "bos").mkdir()
    assert main(["--kaynak", str(tmp_path / "bos"), "--cikti", str(tmp_path / "out")]) == 1
