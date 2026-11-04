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
    ("openai_key", "sk-" + "proj-" + GOVDE + "_" + GOVDE),
    ("openai_key", "sk-" + GOVDE + GOVDE),
    ("atlassian_token", "ATA" + "TT" + GOVDE + "=" + GOVDE),
    ("google_api_key", "AI" + "za" + "Sy" + GOVDE + "xyz12345"),
    ("aws_access_key", "AK" + "IA" + "ABCDEFGHIJ234567"),
    ("slack_token", "xo" + "xb-" + "1234567890-" + GOVDE),
    ("npm_token", "np" + "m_" + GOVDE),
    ("stripe_key", "sk" + "_live_" + GOVDE),
    ("stripe_key", "rk" + "_test_" + GOVDE),
    ("grafana_token", "gl" + "sa_" + GOVDE + "_" + "0a1b2c3d"),
    ("huggingface_token", "h" + "f_" + GOVDE + "XyZ"),
    ("sendgrid_key", "S" + "G." + GOVDE + "." + GOVDE + "-" + GOVDE),
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
        "header_token",
        "bare_auth_scheme",
        "cli_user_password",
        "cli_password_flag",
        "azure_connection_key",
        "session_cookie",
        "url_signature",
        "github_add_mask",
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


@pytest.mark.parametrize(
    "ad",
    [
        "PGPASSWORD",  # alt çizgisiz sonek
        "DB_PASS",
        "MYSQL_ROOT_PASSWD",
        "export AWS_SECRET_ACCESS_KEY",
        "DJANGO_SECRET_KEY",
        "MY_APIKEY",
        "OPENAI_APIKEY",
    ],
)
def test_ortam_atamasi_genis_sonekler(ad: str) -> None:
    assert scrub_secret_patterns(f"{ad}=Abcdef123456ghij x") == f"{ad}=*** x"
    assert "env_assignment" in {f.name for f in find_secret_patterns(f"{ad}=Abcdef123456ghij")}


@pytest.mark.parametrize(
    "ad", ["DB_PASSWORD", "GITHUB_TOKEN", "SMTP_PASS", "AWS_SECRET_ACCESS_KEY"]
)
def test_ortam_atamasi_yaml_iki_nokta(ad: str) -> None:
    deger = "Sup3r" + "S3cret9"
    assert scrub_secret_patterns(f"{ad}: {deger}") == f"{ad}: ***"
    assert scrub_secret_patterns(f"  {ad}: '{deger}'\n") == f"  {ad}: '***'\n"
    assert "env_assignment" in {f.name for f in find_secret_patterns(f"{ad}: {deger}")}


@pytest.mark.parametrize(
    "metin",
    [
        "DB_PASSWORD: str",
        "DB_PASSWORD: str = Field(default='')",
        "SMTP_PASS: Optional[str] = None",
        "GITHUB_TOKEN: ${GITHUB_TOKEN}",
        "DB_PASSWORD: <parola>",
        "DB_PASSWORD: ***",
    ],
)
def test_ortam_atamasi_iki_nokta_kaynak_kodu_ve_yer_tutucuya_dokunmaz(metin: str) -> None:
    assert scrub_secret_patterns(metin) == metin


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
        (f"SECRET_KEY={SIR}", "SECRET_KEY=***"),
        (f"secret-key: {SIR}", "secret-key: ***"),
        # Alt çizgili önekli küçük harfli adlar (YAML/compose, araç çıktısı).
        (f"db_password: {SIR}", "db_password: ***"),
        (f"github_token: {SIR}", "github_token: ***"),
        (f"jira_token: {SIR}", "jira_token: ***"),
        (f"aws_secret_access_key={SIR}", "aws_secret_access_key=***"),
        (f'  "smtp_auth_token": "{SIR}",', '  "smtp_auth_token": "***",'),
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
        "def baglan(db_password: str, github_token: str | None = None) -> None:",
        "jira_token = ayarlar.jira_token",
        "db_password: ${DB_PASSWORD}",
        "github_token_url: " + SIR,  # farklı alan adı
    ],
)
def test_oneksiz_atama_kaynak_kodu_ve_yer_tutucuya_dokunmaz(metin: str) -> None:
    assert scrub_secret_patterns(metin) == metin


HEX = "a1b2c3d4" + "e5f60718" * 3


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        # DEMOAPP_TEST_TOKEN core-worker'da yok (security-check 8): yalnız biçimden yakalanır.
        (f"> X-Demoapp-Test-Token: {HEX}", "> X-Demoapp-Test-Token: ***"),
        (f"x-api-key: {SIR} devam", "x-api-key: *** devam"),
        ('{"Private-Token": "' + SIR + '"}', '{"Private-Token": "***"}'),
        (f"X-Auth: {SIR}", "X-Auth: ***"),
        (f"X-Request-Id: {SIR}", f"X-Request-Id: {SIR}"),  # sır adı taşımayan başlık
    ],
)
def test_tireli_baslik(metin: str, beklenen: str) -> None:
    assert scrub_secret_patterns(metin) == beklenen


@pytest.mark.parametrize(
    "metin",
    [
        '{"X-Demoapp-Test-Token": token}',
        "headers = {'X-Api-Key': settings.api_key}",
        "X-Demoapp-Test-Token: <token>",
        "X-Demoapp-Test-Token: ${DEMOAPP_TEST_TOKEN}",
    ],
)
def test_tireli_baslik_kaynak_kodu_ve_yer_tutucuya_dokunmaz(metin: str) -> None:
    assert scrub_secret_patterns(metin) == metin


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        ("istek Basic " + "dXNlcjpwYXNzd29yZDEyMw==" + " gönderildi", "istek Basic *** gönderildi"),
        ("-H 'Bearer " + GOVDE + "'", "-H 'Bearer ***'"),
        ("curl -u admin:" + "S3cretPassw0rd" + " https://x", "curl -u admin:*** https://x"),
        ("wget --user=ci:" + "S3cretPassw0rd", "wget --user=ci:***"),
    ],
)
def test_oneksiz_sema_ve_cli_kimligi(metin: str, beklenen: str) -> None:
    assert scrub_secret_patterns(metin) == beklenen


@pytest.mark.parametrize(
    "metin",
    [
        "Basic authentication kullanılır",
        "Bearer token ile çağrılır",
        'curl -u "$KULLANICI:$PAROLA" https://x',
        "curl -u kullanici:<parola>",
        "ls -u",
        "scikit-learn ve risk-free",
    ],
)
def test_oneksiz_sema_ve_cli_dogal_metne_dokunmaz(metin: str) -> None:
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


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        (
            "docker login -u ci -p " + "S3cretPassw0rd" + " reg.local",
            "docker login -u ci -p *** reg.local",
        ),
        ("podman login --password=" + "S3cretPassw0rd", "podman login --password=***"),
        (
            "helm registry login r.local -p '" + "S3cretPassw0rd" + "'",
            "helm registry login r.local -p '***'",
        ),
        (
            "docker login -u ci -p" + "S3cretPassw0rd" + " reg.local",
            "docker login -u ci -p*** reg.local",
        ),
        (
            "helm registry login r.local -p=" + "S3cretPassw0rd",
            "helm registry login r.local -p=***",
        ),
        ("mysql -u root -p" + "S3cretPassw0rd" + " tp", "mysql -u root -p*** tp"),
        ("mysqldump --password=" + "parola" + " tp", "mysqldump --password=*** tp"),
    ],
)
def test_cli_parola_bayragi(metin: str, beklenen: str) -> None:
    assert scrub_secret_patterns(metin) == beklenen


@pytest.mark.parametrize(
    "metin",
    [
        "docker run -p 8080:80 nginx",
        "mkdir -p build2/out1",
        "docker login -u ci -p $REGISTRY_PAROLA reg.local",
        'docker login -u ci -p "$PAROLA" reg.local',
        "docker login -u ci --password-stdin reg.local",
        "docker login -u ci -p${REGISTRY_PAROLA} reg.local",
        "docker login --platform linux/amd64 reg.local",
        "mysql -u root -p tpdb",
        "mysql -u root -p",
        "ssh -p 2222 kullanici@host",
    ],
)
def test_cli_parola_bayragi_dogal_komuta_dokunmaz(metin: str) -> None:
    assert scrub_secret_patterns(metin) == metin


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        (
            "DefaultEndpointsProtocol=https;AccountName=tp;AccountKey="
            + "QmFzZTY0"
            + GOVDE
            + "=="
            + ";EndpointSuffix=core.windows.net",
            "DefaultEndpointsProtocol=https;AccountName=tp;AccountKey=***"
            ";EndpointSuffix=core.windows.net",
        ),
        (
            "Endpoint=sb://ns.servicebus.windows.net/;SharedAccessKeyName=root;"
            "SharedAccessKey=" + GOVDE + "+/x=",
            "Endpoint=sb://ns.servicebus.windows.net/;SharedAccessKeyName=root;SharedAccessKey=***",
        ),
        (
            "BlobEndpoint=https://a.blob.core.windows.net;SharedAccessSignature=sv=2022&sig="
            + GOVDE,
            "BlobEndpoint=https://a.blob.core.windows.net;SharedAccessSignature=***",
        ),
    ],
)
def test_azure_baglanti_dizgisi(metin: str, beklenen: str) -> None:
    assert scrub_secret_patterns(metin) == beklenen


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        (f"Cookie: session={GOVDE}", "Cookie: session=***"),
        (
            f"cookie: theme=dark; sessionid={GOVDE}; lang=tr",
            "cookie: theme=dark; sessionid=***; lang=tr",
        ),
        (
            f"Set-Cookie: tp_session={GOVDE}; Path=/; HttpOnly",
            "Set-Cookie: tp_session=***; Path=/; HttpOnly",
        ),
        (f"Set-Cookie: auth_token={GOVDE}%3D%3D", "Set-Cookie: auth_token=***"),
        (f"Cookie: theme={GOVDE}", f"Cookie: theme={GOVDE}"),  # sır adı taşımayan çerez
    ],
)
def test_oturum_cerezi(metin: str, beklenen: str) -> None:
    assert scrub_secret_patterns(metin) == beklenen
    if metin != beklenen:
        assert "session_cookie" in {f.name for f in find_secret_patterns(metin)}


@pytest.mark.parametrize(
    "metin",
    [
        "Cookie: session=${OTURUM}",
        "Cookie: session=<oturum>",
        "Set-Cookie: tp_session=deleted; Path=/",
        "cookies = {'session': session_id}",
    ],
)
def test_oturum_cerezi_yer_tutucuya_dokunmaz(metin: str) -> None:
    assert scrub_secret_patterns(metin) == metin


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        (
            f"GET https://a.blob.core.windows.net/c?sv=2021&sig={GOVDE}%3D&se=2026",
            "GET https://a.blob.core.windows.net/c?sv=2021&sig=***&se=2026",
        ),
        (
            f"https://s3.local/b?X-Amz-Date=20260101T000000Z&X-Amz-Signature={HEX}",
            "https://s3.local/b?X-Amz-Date=20260101T000000Z&X-Amz-Signature=***",
        ),
        (
            f"https://storage.local/o?X-Goog-Signature={HEX}#bolum",
            "https://storage.local/o?X-Goog-Signature=***#bolum",
        ),
        (
            f"https://s3.local/b?X-Amz-Security-Token={GOVDE}&sayfa=2",
            "https://s3.local/b?X-Amz-Security-Token=***&sayfa=2",
        ),
        (f"imzalı istek X-Amz-Signature={HEX} 403", "imzalı istek X-Amz-Signature=*** 403"),
    ],
)
def test_imzali_url(metin: str, beklenen: str) -> None:
    assert scrub_secret_patterns(metin) == beklenen
    assert "url_signature" in {f.name for f in find_secret_patterns(metin)}


@pytest.mark.parametrize(
    "metin",
    [
        "https://x.local/a?sig=${IMZA}&sayfa=2",
        "https://x.local/ara?q=signature&sayfa=2",
        "https://x.local/a?sig=abc&sayfa=2",  # rastgele görünmeyen değer
    ],
)
def test_imzali_url_dogal_metne_dokunmaz(metin: str) -> None:
    assert scrub_secret_patterns(metin) == metin


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        (f"::add-mask::{GOVDE}", "::add-mask::***"),
        ("::add-mask::" + "duzparola", "::add-mask::***"),  # değer tanımı gereği sır
        (f'echo "::add-mask::{GOVDE}"', 'echo "::add-mask::***"'),
    ],
)
def test_github_add_mask(metin: str, beklenen: str) -> None:
    assert scrub_secret_patterns(metin) == beklenen
    assert "github_add_mask" in {f.name for f in find_secret_patterns(metin)}


@pytest.mark.parametrize(
    "metin",
    ['echo "::add-mask::$TOKEN"', "::add-mask::${{ steps.x.outputs.t }}", "::add-mask::***"],
)
def test_github_add_mask_yer_tutucuya_dokunmaz(metin: str) -> None:
    assert scrub_secret_patterns(metin) == metin


def test_azure_yer_tutucuya_dokunmaz() -> None:
    metin = "AccountKey=<anahtar>;SharedAccessKey=${SAS}"
    assert scrub_secret_patterns(metin) == metin


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
