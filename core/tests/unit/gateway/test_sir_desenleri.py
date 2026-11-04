"""`scrub_secret_patterns` ve çalışma anı sır değerleri (AI-ASISTAN-PLANI §10.3 Şerit C1).

Repo public: sahte token'lar çalışma anında birleştirilerek üretilir (push koruması / gitleaks).
"""

from __future__ import annotations

import pytest

from tp_core.gateway.factory import SECRET_ENV_VARS, known_secret_values
from tp_core.gateway.masking import (
    SECRET_MASK,
    SECRET_PATTERNS,
    find_secret_patterns,
    scrub_secret_patterns,
)

GOVDE = "A1b2C3d4E5f6G7h8J9k0Lm"  # 22 karakter, harf+rakam

# (desen adı, sahte sır, çevreleyen metinde korunması gereken kısım)
VAKALAR: list[tuple[str, str]] = [
    ("github_pat", "github" + "_pat_" + GOVDE + "_" + GOVDE),
    ("github_token", "gh" + "p_" + GOVDE),
    ("github_token", "gh" + "s_" + GOVDE),
    ("github_token", "gh" + "o_" + GOVDE),
    ("github_token", "gh" + "u_" + GOVDE),
    ("github_token", "gh" + "r_" + GOVDE),
    ("gitlab_pat", "gl" + "pat-" + GOVDE),
    ("anthropic_key", "sk-" + "ant-" + "api03-" + GOVDE),
    ("atlassian_token", "ATA" + "TT" + GOVDE + "=" + GOVDE),
    ("google_api_key", "AI" + "za" + "Sy" + GOVDE + "xyz12345"),
    ("aws_access_key", "AK" + "IA" + "ABCDEFGHIJ234567"),
    ("slack_token", "xo" + "xb-" + "1234567890-" + GOVDE),
    ("npm_token", "np" + "m_" + GOVDE),
    ("jwt", "ey" + "JhbGciOiJIUzI1NiJ9" + "." + "ey" + "JzdWIiOiIxIn0" + "." + "c2lnbmF0dXJl"),
    ("tp_token", "tp" + "t_" + GOVDE),
    ("tp_mcp_token", "tp" + "k_" + "mock_" + GOVDE),
]


def test_her_desenin_vakasi_var() -> None:
    adlar = {ad for ad, _ in VAKALAR} | {
        "private_key",
        "private_key_tail",
        "authorization",
        "env_assignment",
        "generic_assignment",
        "url_credentials",
    }
    assert adlar == {p.name for p in SECRET_PATTERNS}


@pytest.mark.parametrize(
    ("ad", "sir"), VAKALAR, ids=[f"{a}-{i}" for i, (a, _) in enumerate(VAKALAR)]
)
def test_desen_temizlenir(ad: str, sir: str) -> None:
    metin = f"önce {sir} sonra"
    assert ad in {f.name for f in find_secret_patterns(metin)}
    temiz = scrub_secret_patterns(metin)
    assert sir not in temiz
    assert temiz == f"önce {SECRET_MASK} sonra"


@pytest.mark.parametrize(
    ("ad", "sir"), VAKALAR, ids=[f"{a}-{i}" for i, (a, _) in enumerate(VAKALAR)]
)
def test_kesme_sinirinda_yarim_token_temizlenir(ad: str, sir: str) -> None:
    # Araç çıktısı kırpılır (log kuyruğu, satır sınırı): metnin sonunda tokenın yalnız başı kalır.
    yarim = sir[: max(len(sir) // 2, len(sir) - 12)]
    metin = f"log satırı ... {yarim}"
    temiz = scrub_secret_patterns(metin)
    assert yarim not in temiz
    assert temiz.endswith(SECRET_MASK)


def test_yarim_token_metin_ortasinda_eslesmez() -> None:
    # Kısa gövde yalnız metin SONUNDA token sayılır; ortada sıradan kelimeye dokunulmaz.
    metin = "gh" + "p_abc ve npm_install komutu"
    assert scrub_secret_patterns(metin) == metin


def test_ozel_anahtar_blogu_ve_kesik_blok() -> None:
    bas = "-----BEGIN " + "RSA PRIVATE KEY-----"
    son = "-----END " + "RSA PRIVATE KEY-----"
    blok = f"{bas}\nMIIEowIBAAKCAQEA{GOVDE}\n{GOVDE}==\n{son}"
    assert scrub_secret_patterns(f"anahtar:\n{blok}\nbitti") == f"anahtar:\n{SECRET_MASK}\nbitti"
    # BEGIN'den sonra kesilmiş
    assert scrub_secret_patterns(f"x {bas}\nMIIEow{GOVDE}") == f"x {SECRET_MASK}"
    # BEGIN'i kesilmiş (log kuyruğu ortadan başlar)
    assert scrub_secret_patterns(f"{GOVDE}\n{GOVDE}==\n{son}\nsonra") == f"{SECRET_MASK}\nsonra"


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        ("Authorization: Bearer " + GOVDE, "Authorization: Bearer ***"),
        ("authorization: basic dXNlcjpwYXNz", "authorization: basic ***"),
        ("Authorization: token " + GOVDE + " devam", "Authorization: token *** devam"),
    ],
)
def test_authorization_basligi(metin: str, beklenen: str) -> None:
    assert scrub_secret_patterns(metin) == beklenen


@pytest.mark.parametrize(
    "ad",
    [
        "SEED_USER_PASSWORD",
        "TP_SESSION_SECRET",
        "JIRA_WRITE_TOKEN",
        "JIRA_API_TOKEN",
        "GITHUB_TOKEN",
    ],
)
def test_ortam_atamasi(ad: str) -> None:
    assert scrub_secret_patterns(f"{ad}=s3cr3tDeger x") == f"{ad}=*** x"


def test_ortam_atamasi_yer_tutucuya_dokunmaz() -> None:
    metin = "JIRA_READ_TOKEN=<okuma token'ı> TP_APP_PASSWORD=${TP_APP_PASSWORD}"
    assert scrub_secret_patterns(metin) == metin


SIR = "Xy7" + "pQ9wLm2"  # ≥ 8, harf + rakam


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        (f"PASSWORD={SIR} x", "PASSWORD=*** x"),
        (f"password: {SIR}", "password: ***"),
        (f"Password = '{SIR}';", "Password = '***';"),
        ('{"password": "' + SIR + '", "u": 1}', '{"password": "***", "u": 1}'),
        (f"export TOKEN={SIR}", "export TOKEN=***"),
        (f"curl --password {SIR} -X", "curl --password *** -X"),
        (f"cli --api-key={SIR}", "cli --api-key=***"),
        (f"client_secret: {SIR}", "client_secret: ***"),
        (f"secret={SIR}", "secret=***"),
    ],
)
def test_oneksiz_atama(metin: str, beklenen: str) -> None:
    assert scrub_secret_patterns(metin) == beklenen
    assert "generic_assignment" in {f.name for f in find_secret_patterns(metin)}


@pytest.mark.parametrize(
    "metin",
    [
        "def giris(password: str, token: str | None = None) -> None:",
        "token = get_token()",
        "token = tokens[0]",
        "api_key = settings.anthropic_api_key",
        "password: ${DB_PASSWORD}",
        "password: <parola>",
        "password: ***",
        "secret: kisa1",
        "secret: yalnizharf",  # rakamsız düz kelime
        "password_hash: " + SIR,  # farklı alan adı
        "pwd: /home/user1/build",
    ],
)
def test_oneksiz_atama_kaynak_kodu_ve_yer_tutucuya_dokunmaz(metin: str) -> None:
    assert scrub_secret_patterns(metin) == metin


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        ("https://kullanici:" + "p4rola" + "@forge.local/a.git", "https://***@forge.local/a.git"),
        (
            "postgresql+psycopg://tp_app:" + "Gizli123" + "@postgres:5432/tp",
            "postgresql+psycopg://***@postgres:5432/tp",
        ),
        ("https://x-access-token:" + GOVDE + "@github.com/o/r", "https://***@github.com/o/r"),
    ],
)
def test_url_ici_kimlik(metin: str, beklenen: str) -> None:
    assert scrub_secret_patterns(metin) == beklenen


def test_sir_olmayan_metin_degismez() -> None:
    metin = 'Sepete ekle düğmesi `data-testid="add-to-cart"`; https://jira.local/browse/TPD-3'
    assert scrub_secret_patterns(metin) == metin
    assert scrub_secret_patterns("") == ""


# ------------------------------------------------------------------ çalışma anı sır değerleri


def test_bilinen_deger_tam_ve_kesik_temizlenir() -> None:
    deger = "Zq" + "9xLmN4pQr7"
    assert scrub_secret_patterns(f"a {deger} b {deger}", [deger]) == "a *** b ***"
    # sonda değerin başı (≥ 8), başta değerin sonu (≥ 8)
    assert scrub_secret_patterns(f"kuyruk {deger[:9]}", [deger]) == "kuyruk ***"
    assert scrub_secret_patterns(f"{deger[-8:]} baş", [deger]) == "*** baş"
    # 8'den kısa parça ve kısa değer temizlenmez
    assert scrub_secret_patterns(f"kuyruk {deger[:5]}", [deger]) == f"kuyruk {deger[:5]}"
    assert scrub_secret_patterns("sim değeri", ["sim"]) == "sim değeri"


def test_bulgu_degeri_tasimaz() -> None:
    sir = "gh" + "p_" + GOVDE
    for f in find_secret_patterns(f"x {sir}"):
        assert sir not in repr(f)


def test_secret_env_vars_genisletildi() -> None:
    for ad in (
        "TP_AGENT_DEALER_PASSWORD",
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
        "GITHUB_MERGE_TOKEN",
        "GH_APP_PRIVATE_KEY",
        "JIRA_WRITE_TOKEN",
        "TP_APP_PASSWORD",
        "TP_SESSION_SECRET",
    ):
        assert ad in SECRET_ENV_VARS


def test_known_secret_values_ortamdan() -> None:
    anahtar = (
        "-----BEGIN " + "PRIVATE KEY-----\n" + GOVDE + GOVDE + "\n-----END " + "PRIVATE KEY-----"
    )
    env = {
        "TP_AGENT_DEALER_PASSWORD": "Demo123!",
        "ANTHROPIC_API_KEY": "sk-" + "ant-" + GOVDE,
        "JIRA_WRITE_TOKEN": "sim",  # < 8: rastgele eşleşmesin
        "JIRA_YENI_OKUMA_TOKEN": "Jt" + GOVDE,  # listede yok, adı desene uyar
        "GITHUB_OZEL_TOKEN": "Gt" + GOVDE,
        "GH_APP_PRIVATE_KEY": anahtar,
        "GH_APP_PRIVATE_KEY_PATH": "/run/secrets/gh-app.pem",  # yol, sır değil
        "TP_PORTAL_PORT": "8080808080",
    }
    degerler = known_secret_values(env)
    assert "Demo123!" in degerler
    assert "sk-" + "ant-" + GOVDE in degerler
    assert "Jt" + GOVDE in degerler and "Gt" + GOVDE in degerler
    assert anahtar in degerler and GOVDE + GOVDE in degerler
    assert "sim" not in degerler
    assert "/run/secrets/gh-app.pem" not in degerler
    assert "8080808080" not in degerler


def test_known_secret_values_eski_davranis(monkeypatch: pytest.MonkeyPatch) -> None:
    for ad in SECRET_ENV_VARS:
        monkeypatch.delenv(ad, raising=False)
    monkeypatch.setenv("TP_AGENT_DEALER_PASSWORD", "kisa")
    assert "kisa" in known_secret_values()
