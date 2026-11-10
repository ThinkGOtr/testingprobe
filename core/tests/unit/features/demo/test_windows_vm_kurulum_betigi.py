"""deploy/gcp/windows-vm/kurulum.ps1 — GCP Windows VM başlangıç betiğinin statik denetimi.

Sözleşme: specs/009-mobil-masaustu/windows-gcp.md. Betik Windows'ta (SYSTEM, PowerShell 5.1) koşar;
burada metni okunarak sabit sürümler, özet doğrulaması, güvenlik duvarı kısıtı, seri port satır
biçimleri ve sır bulunmaması denetlenir. `pwsh` kuruluysa PowerShell ayrıştırıcısıyla sözdizimi,
gömülü oturum betiği ve gömülü C# (LSA / ekran P/Invoke) derlemesi de sınanır.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
BETIK = REPO / "deploy" / "gcp" / "windows-vm" / "kurulum.ps1"
SOZLESME = REPO / "specs" / "009-mobil-masaustu" / "windows-gcp.md"
APPIUM_KILIT = REPO / "tools" / "appium" / "package-lock.json"
CI_WINDOWS = REPO / ".github" / "workflows" / "masaustu-windows.yml"


@pytest.fixture(scope="module")
def metin() -> str:
    return BETIK.read_text(encoding="utf-8")


def _sabit(metin: str, ad: str) -> str:
    m = re.search(rf"^\${ad}\s*=\s*'([^']*)'", metin, re.MULTILINE)
    assert m, f"${ad} sabiti yok"
    return m.group(1)


def test_yalnizca_ascii(metin: str) -> None:
    # PowerShell 5.1 BOM'suz betiği ANSI okur; UTF-8 tire/ok dize sözdizimini bozabilir.
    ascii_disi = [(i + 1, s) for i, s in enumerate(metin.splitlines()) if not s.isascii()]
    assert not ascii_disi, f"ASCII dışı satırlar: {ascii_disi[:3]}"


def test_surumler_sabit(metin: str) -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", _sabit(metin, "NodeSurum"))
    assert re.fullmatch(r"8\.0\.\d+", _sabit(metin, "DotnetSdkSurum"))
    nova = _sabit(metin, "NovaWindowsSurum")
    assert nova == "1.5.0"
    # NovaWindows sürümü CI ile aynı olmalı
    assert f'NOVAWINDOWS_VERSION: "{nova}"' in CI_WINDOWS.read_text(encoding="utf-8")
    # Appium sürümü kilit dosyasından gelir (npm ci); kilitte 3.9.0
    assert '"node_modules/appium": {\n      "version": "3.9.0"' in APPIUM_KILIT.read_text(
        encoding="utf-8"
    )
    assert re.search(r"'ci', '--no-audit'", metin), "npm ci (kilit dosyası) kullanılmalı"
    assert "appium-novawindows-driver@$NovaWindowsSurum" in metin
    # "latest" / aralıklı sürüm yok
    assert not re.search(r"latest|@\^|@~", metin, re.IGNORECASE)


def test_ozet_dogrulamasi(metin: str) -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", _sabit(metin, "NodeZipSha256"))
    assert re.fullmatch(r"[0-9a-f]{128}", _sabit(metin, "DotnetSdkZipSha512"))
    assert "Assert-Ozet $zip 'SHA256' $NodeZipSha256" in metin
    assert "Assert-Ozet $zip 'SHA512' $DotnetSdkZipSha512" in metin
    assert "Get-FileHash -Path $Dosya -Algorithm $Algoritma" in metin
    # İndirme yalnızca resmi kaynaklardan ve https ile
    for url in re.findall(r"https?://[^\s'\"`)]+", metin):
        if url.startswith("http://metadata.google.internal/") or url.startswith(
            "http://127.0.0.1:"
        ):
            continue
        assert url.startswith(
            (
                "https://nodejs.org/dist/",
                "https://builds.dotnet.microsoft.com/",
                "https://dotnetcli.blob.core.windows.net/",
                "https://codeload.github.com/",
                "https://api.github.com/",
                "https://bayi.testing-probe.antreklabs.com/",
            )
        ), url


def test_metadata_anahtarlari_ve_varsayilanlar(metin: str) -> None:
    sozlesme = SOZLESME.read_text(encoding="utf-8")
    beklenen = {
        "tp-repo": "ThinkGOtr/testingprobe",
        "tp-repo-ref": "dev",
        "tp-izinli-kaynak": "10.156.0.2",
        "tp-api-url": "https://bayi.testing-probe.antreklabs.com/api",
    }
    for anahtar, varsayilan in beklenen.items():
        assert f"| `{anahtar}` |" in sozlesme
        assert f"`{varsayilan}`" in sozlesme
        assert f"Get-Metadata '{anahtar}' '{varsayilan}'" in metin
    assert "'Metadata-Flavor' = 'Google'" in metin


def test_guvenlik_duvari_yalnizca_izinli_kaynak(metin: str) -> None:
    kurallar = re.findall(r"New-NetFirewallRule(?:[^\n`]|`(?!\n)|`\n)*", metin)
    assert len(kurallar) == 1, "tek güvenlik duvarı kuralı beklenir"
    kural = kurallar[0]
    assert "-Direction Inbound" in kural
    assert "-LocalPort $AppiumPort" in kural
    assert "-RemoteAddress $IzinliKaynak" in kural
    # 4723'ü açan başka kurallar ve node.exe program kuralları silinir
    assert "Remove-NetFirewallRule" in metin
    assert "-Program '*node.exe'" in metin
    assert "-NotifyOnListen False" in metin
    # İzinli kaynak tek IPv4 olarak doğrulanır
    assert r"'^\d{1,3}(\.\d{1,3}){3}$'" in metin
    # RDP'ye dokunulmaz
    assert not re.search(r"3389|Remote Desktop|fDenyTSConnections", metin)


def test_genis_uzak_adres_yok(metin: str) -> None:
    assert not re.search(r"0\.0\.0\.0/0|::/0|RemoteAddress\s+(Any|\*)", metin, re.IGNORECASE)
    # 0.0.0.0 yalnızca Appium'un dinleme adresi ve izinli kaynağın reddi için geçer
    for satir in metin.splitlines():
        if "0.0.0.0" in satir and not satir.lstrip().startswith("#"):
            assert (
                "--address 0.0.0.0" in satir or "-eq '0.0.0.0'" in satir or "0.0.0.0:" in (satir)
            ), satir


def test_seri_port_satir_bicimleri(metin: str) -> None:
    assert 'Write-Seri "TP-WINDOWS-BASLADI ref=$RefYazim"' in metin
    assert (
        'Write-Seri "TP-WINDOWS-HAZIR appium=$AppiumPort uygulama=$UygulamaExe ref=$Ref"' in metin
    )
    assert '"TP-WINDOWS-HATA {0} {1}" -f $Ad, (Get-TemizMesaj' in metin
    # BASLADI her açılışın ilk durum satırı: akıştaki ilk Write-Seri ve ilk adımdan önce
    akis = metin[metin.index("# Akis\n") :]
    ilk_seri = re.search(r"Write-Seri [\"(]", akis)
    assert ilk_seri and akis[ilk_seri.start() :].startswith('Write-Seri "TP-WINDOWS-BASLADI ref=')
    assert ilk_seri.start() < akis.index("Invoke-Adim ")
    assert akis.index("$Ref = Get-Metadata") < ilk_seri.start()
    # Sözleşmedeki yol ve port
    assert _sabit(metin, "Kullanici") == "tpotomasyon"
    assert "$UygulamaExe = Join-Path $UygulamaDizini 'BayiSiparis.exe'" in metin
    assert "$UygulamaDizini = Join-Path $Kok 'uygulama'" in metin
    assert "$Kok = 'C:\\tp'" in metin
    assert "$AppiumPort = 4723" in metin
    assert "`C:\\tp\\uygulama\\BayiSiparis.exe`" in SOZLESME.read_text(encoding="utf-8")
    # Adım adları boşluksuz (HATA satırında <adım> tek sözcük)
    for ad in re.findall(r"Invoke-Adim '([^']+)'", metin):
        assert re.fullmatch(r"[a-z-]+", ad), ad


def test_sir_yok(metin: str) -> None:
    # Sabit parola / SecureString'e düz metin sabiti yok
    assert not re.search(r"-AsPlainText[^\n]*-String\s+['\"]", metin)
    assert not re.search(r"ConvertTo-SecureString\s+['\"]", metin)
    assert not re.search(r"-Password\s+['\"]", metin)
    assert not re.search(r"DefaultPassword'?\s+-Value\s+['\"]", metin)
    assert not re.search(r"(?i)(parola|password)\s*=\s*['\"][^'\"]{4,}['\"]", metin)
    # Parola CSPRNG ile üretilir ve log/seri porta yazılmaz
    assert "[System.Security.Cryptography.RandomNumberGenerator]::Create()" in metin
    assert "Get-Random" not in metin
    for satir in metin.splitlines():
        if "Write-Seri" in satir or "Write-TpLog" in satir:
            assert "$parola" not in satir, satir
    # Hata mesajlarında parola maskelenir
    assert "$script:GizliDegerler = @($parola)" in metin
    # Otomatik oturum parolası öncelikle LSA gizli verisinde
    assert "LsaStorePrivateData" in metin


def test_idempotent_ve_yeniden_baslatma_korumasi(metin: str) -> None:
    assert "$ErrorActionPreference = 'Stop'" in metin
    for adim in ("kaynak", "node", "appium", "dotnet", "uygulama", "kullanici"):
        assert f"Get-Isaret '{adim}'" in metin, adim
    # Yeniden başlatma: işaret dosyası Restart-Computer'dan ÖNCE yazılır (döngü yok), tek çağrı
    assert metin.count("Restart-Computer") == 1
    assert metin.index("Set-Isaret 'yeniden-baslatma'") < metin.index("Restart-Computer")
    assert "if (-not (Get-Isaret 'yeniden-baslatma'))" in metin
    # Appium oturum görevinde, sözleşmedeki adres/port ve sürücüyle; relaxed-security yok
    assert "--address 0.0.0.0 --port __APPIUM_PORT__ --use-drivers novawindows" in metin
    assert "--relaxed-security" not in metin.replace("--relaxed-security YOK", "")
    assert "-LogonType Interactive" in metin
    assert "'__LOG_DIZINI__\\appium.log'" in metin
    assert "[Environment]::SetEnvironmentVariable('BAYI_API_URL', $ApiUrl, 'Machine')" in metin
    assert "$AppiumBeklemeSaniye = 600" in metin
    assert "http://127.0.0.1:$AppiumPort/status" in metin
    # Ekran çözünürlüğü sözleşmesi
    assert "$EkranMinGenislik = 1440" in metin
    assert "$EkranMinYukseklik = 900" in metin


# --- pwsh varsa: gerçek ayrıştırıcı + gömülü oturum betiği + gömülü C# derlemesi -----------------

PWSH_KONTROL = Path(__file__).with_name("windows_vm_kurulum_kontrol.ps1")


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh yok")
def test_powershell_ayristirici_ve_gomulu_kod() -> None:
    sonuc = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(PWSH_KONTROL), str(BETIK)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert sonuc.returncode == 0 and "TAMAM" in sonuc.stdout, sonuc.stdout + sonuc.stderr
