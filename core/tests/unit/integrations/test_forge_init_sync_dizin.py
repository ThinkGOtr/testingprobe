"""scripts/forge-init.sh sync-dizin — mevcut LocalForge deposuna tek dizin ekleme (OPS-O3).

Docker sahte: PATH'teki `docker`, `run ... -s` çağrısında iç betiği yerelde `sh -eu -s` ile koşar;
`/forge` volume'ü geçici dizine, `/src` bağlaması kaynak dizine eşlenir (FORGE_DIR / SRC_DIR).
Beklenen: main'e yalnız `<dizin>/` altına dokunan TEK commit (fast-forward), PR kaydı ve diğer
dallar korunur, ikinci koşu no-op; `--baseline` etiketi ve demo/break-locator'ı yeni commit'e taşır;
`--koru` alt yolları forge main'deki hâliyle kalır (K-T14); forge deposunun hook'ları çalışmaz
(GÜV-Y2); volume yoksa oluşturulmadan hata verilir (OPS-D2).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "scripts" / "forge-init.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None or not SCRIPT.exists(),
    reason="bash / git / forge-init.sh yok",
)

FAKE_DOCKER = r"""
import os, subprocess, sys
st = os.environ["FAKE_STATE"]
a = sys.argv[1:]
with open(os.path.join(st, "docker.log"), "a") as f:
    f.write(" ".join(a) + "\n")
if a[:2] == ["volume", "inspect"]:
    sys.exit(1 if os.environ.get("FAKE_NO_VOLUME") == "1" else 0)
if a[:2] == ["image", "inspect"]:
    sys.exit(0)
if a[:1] == ["run"]:
    if "command -v git" in a:
        sys.exit(0)
    env = dict(os.environ)
    i = 1
    while i < len(a):
        if a[i] == "-e":
            k, v = a[i + 1].split("=", 1)
            env[k] = v
            i += 2
        elif a[i] == "-v":
            host, cont = a[i + 1].split(":")[:2]
            if not host.startswith("/"):
                host = os.path.join(st, "vol", host)
            env["FORGE_DIR" if cont == "/forge" else "SRC_DIR"] = host
            i += 2
        else:
            i += 1
    sys.exit(subprocess.run(["sh", "-eu", "-s"], env=env).returncode)
sys.exit(97)
"""

GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(d: Path, *args: str, bare: bool = False) -> str:
    cmd = ["git", "-c", "safe.directory=*"]
    cmd += [f"--git-dir={d}"] if bare else ["-C", str(d)]
    return subprocess.run(
        [*cmd, *args],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **GIT_ENV},
    ).stdout.strip()


@pytest.fixture
def ortam(tmp_path: Path) -> Any:
    state = tmp_path / "state"
    (state / "vol" / "tpvol").mkdir(parents=True)
    forge = state / "vol" / "tpvol"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(f"#!{sys.executable}\n{FAKE_DOCKER}")
    docker.chmod(0o755)

    # Kaynak demo-app (init anındaki hali): web + e2e.
    src = tmp_path / "demo-app"
    (src / "web" / "src").mkdir(parents=True)
    (src / "web" / "src" / "Katalog.tsx").write_text('<button data-testid="add-to-cart" />\n')
    (src / "web" / "Dockerfile").write_text("FROM scratch\n")
    (src / "e2e").mkdir()
    (src / "e2e" / "a.spec.ts").write_text("test\n")

    # forge-init'in kurduğu depo: main = demo-baseline, demo/break-locator tek commit.
    w = tmp_path / "w"
    shutil.copytree(src, w)
    _git(w, "init", "-q", "-b", "main")
    _git(w, "add", "-A")
    _git(w, "commit", "-q", "-m", "baslangic")
    _git(w, "tag", "demo-baseline")
    _git(w, "checkout", "-q", "-b", "demo/break-locator")
    (w / "web" / "src" / "Katalog.tsx").write_text('<button data-testid="cart-add" />\n')
    _git(w, "commit", "-q", "-am", "kirilma")
    bare = forge / "demo-app.git"
    # forge-init init ile aynı: --shared=0666 → receive.denyNonFastforwards=true
    # (zorla push reddedilir).
    _git(w, "init", "-q", "--bare", "--shared=0666", "-b", "main", str(bare))
    assert _git(bare, "config", "receive.denyNonFastforwards", bare=True) == "true"
    _git(w, "push", "-q", str(bare), "main", "demo/break-locator", "refs/tags/demo-baseline")
    # Açık bir PR dalı ve PR kaydı: sync-dizin bunlara dokunmamalı.
    _git(w, "push", "-q", str(bare), "main:refs/heads/tp/case-1")
    prs = forge / "tp-prs.json"
    prs.write_text(json.dumps({"prs": [{"id": 1, "head": "tp/case-1", "state": "open"}]}))
    (forge / "demo-app-web.sha").write_text(_git(w, "rev-parse", "main") + "\n")

    # Sonradan eklenen proje (011): e2e-java; target/ yok sayılır.
    (src / "e2e-java" / "src").mkdir(parents=True)
    (src / "e2e-java" / "pom.xml").write_text("<project/>\n")
    (src / "e2e-java" / "src" / "SepetTest.java").write_text("class SepetTest {}\n")
    (src / "e2e-java" / ".gitignore").write_text("target/\n")
    (src / "e2e-java" / "target").mkdir()
    (src / "e2e-java" / "target" / "x.class").write_text("ikili\n")
    # .gitignore'da olmasa da Java koşu çıktıları (results/, kanit/) depoya girmez (GÜV-Y6).
    for d in ("results", "kanit"):
        (src / "e2e-java" / d).mkdir()
        (src / "e2e-java" / d / "r.json").write_text("{}\n")

    def run(*args: str, **ek: str) -> subprocess.CompletedProcess[str]:
        env = {
            **{k: v for k, v in os.environ.items() if not k.startswith(("TP_FORGE", "GIT_"))},
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_STATE": str(state),
            "TP_FORGE_VOLUME": "tpvol",
            "TP_FORGE_IMAGE": "sahte-core:local",
            "TP_FORGE_SRC": str(src),
            "TMPDIR": str(tmp_path),
            **ek,
        }
        return subprocess.run(
            ["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60
        )

    run.bare = bare  # type: ignore[attr-defined]
    run.forge = forge  # type: ignore[attr-defined]
    run.src = src  # type: ignore[attr-defined]
    run.state = state  # type: ignore[attr-defined]
    return run


def _ref(bare: Path, ref: str) -> str:
    return _git(bare, "rev-parse", ref, bare=True)


def test_tek_commit_yalniz_dizin_pr_kaydi_korunur(ortam: Any) -> None:
    bare = ortam.bare
    eski_main = _ref(bare, "main")
    eski_kir = _ref(bare, "demo/break-locator")
    prs = (ortam.forge / "tp-prs.json").read_text()
    web_sha = (ortam.forge / "demo-app-web.sha").read_text()

    r = ortam("sync-dizin", "e2e-java")
    assert r.returncode == 0, r.stderr + r.stdout
    yeni = _ref(bare, "main")
    assert yeni != eski_main
    assert _ref(bare, "main^") == eski_main  # fast-forward, tek commit
    degisen = _git(bare, "diff", "--name-only", eski_main, yeni, bare=True).splitlines()
    assert sorted(degisen) == [
        "e2e-java/.gitignore",
        "e2e-java/pom.xml",
        "e2e-java/src/SepetTest.java",
    ]  # target/, results/, kanit/ girmez
    # PR kaydı, açık PR dalı, kırılma dalı, etiket ve çalışan uygulama sha'sı değişmez.
    assert (ortam.forge / "tp-prs.json").read_text() == prs
    assert (ortam.forge / "demo-app-web.sha").read_text() == web_sha
    assert _ref(bare, "tp/case-1") == eski_main
    assert _ref(bare, "demo/break-locator") == eski_kir
    assert _ref(bare, "demo-baseline^{commit}") == eski_main
    assert "demo-baseline taşınmadı" in r.stdout

    # İkinci koşu no-op (idempotent).
    r2 = ortam("sync-dizin", "e2e-java")
    assert r2.returncode == 0, r2.stderr
    assert "commit yazılmadı" in r2.stdout
    assert _ref(bare, "main") == yeni


def test_degisiklik_tekrar_eslenir(ortam: Any) -> None:
    assert ortam("sync-dizin", "e2e-java").returncode == 0
    once = _ref(ortam.bare, "main")
    (ortam.src / "e2e-java" / "pom.xml").write_text("<project><v>2</v></project>\n")
    (ortam.src / "e2e-java" / "src" / "SepetTest.java").unlink()
    r = ortam("sync-dizin", "e2e-java")
    assert r.returncode == 0, r.stderr
    degisen = _git(ortam.bare, "diff", "--name-status", once, "main", bare=True).splitlines()
    assert sorted(degisen) == ["D\te2e-java/src/SepetTest.java", "M\te2e-java/pom.xml"]


def test_baseline_etiketi_ve_kirilma_dali_tasinir(ortam: Any) -> None:
    bare = ortam.bare
    r = ortam("sync-dizin", "e2e-java", "--baseline")
    assert r.returncode == 0, r.stderr + r.stdout
    yeni = _ref(bare, "main")
    assert _ref(bare, "demo-baseline^{commit}") == yeni
    kir = _ref(bare, "demo/break-locator")
    assert _ref(bare, "demo/break-locator^") == yeni
    assert _git(bare, "diff", "--name-only", yeni, kir, bare=True) == "web/src/Katalog.tsx"
    assert _git(bare, "cat-file", "-e", f"{kir}:e2e-java/pom.xml", bare=True) == ""


def test_baseline_main_baseline_degilse_reddedilir(ortam: Any) -> None:
    bare = ortam.bare
    # make break sonrası: main = demo/break-locator.
    _git(bare, "update-ref", "refs/heads/main", _ref(bare, "demo/break-locator"), bare=True)
    once = _ref(bare, "main")
    r = ortam("sync-dizin", "e2e-java", "--baseline")
    assert r.returncode != 0 and "demo-baseline'da değil" in r.stderr
    assert _ref(bare, "main") == once


def test_baseline_ikinci_kosu_noop(ortam: Any) -> None:
    assert ortam("sync-dizin", "e2e-java", "--baseline").returncode == 0
    refs = {r: _ref(ortam.bare, r) for r in ("main", "demo/break-locator", "demo-baseline")}
    r = ortam("sync-dizin", "e2e-java", "--baseline")
    assert r.returncode == 0, r.stderr
    assert "commit yazılmadı" in r.stdout
    assert {k: _ref(ortam.bare, k) for k in refs} == refs


def test_baseline_basarisizsa_hicbir_ref_degismez(ortam: Any) -> None:
    """Kırılma dalı beklenen biçimde değilse main de ilerlemez (yarım durum yok, OPS-Y1)."""
    bare = ortam.bare
    w = ortam.forge.parent / "w2"
    _git(ortam.forge, "clone", "-q", "--branch", "demo/break-locator", str(bare), str(w))
    (w / "ek.txt").write_text("ikinci commit\n")
    _git(w, "add", "-A")
    _git(w, "commit", "-q", "-m", "ikinci")
    _git(w, "push", "-q", "origin", "demo/break-locator")
    once = {r: _ref(bare, r) for r in ("main", "demo/break-locator", "demo-baseline")}
    r = ortam("sync-dizin", "e2e-java", "--baseline")
    assert r.returncode != 0 and "tek commit değil" in r.stderr
    assert {k: _ref(bare, k) for k in once} == once


def _forge_main_commit(ortam: Any, dosyalar: dict[str, str]) -> str:
    """Forge main'e merge edilmiş bir PR'ı taklit eden commit (ör. üretilen test)."""
    w = ortam.forge.parent / "merge-w"
    if w.exists():
        shutil.rmtree(w)
    _git(ortam.forge, "clone", "-q", "--branch", "main", str(ortam.bare), str(w))
    for yol, icerik in dosyalar.items():
        (w / yol).parent.mkdir(parents=True, exist_ok=True)
        (w / yol).write_text(icerik)
    _git(w, "add", "-A")
    _git(w, "commit", "-q", "-m", "merge: uretilen test")
    _git(w, "push", "-q", "origin", "main")
    return _git(w, "rev-parse", "HEAD")


URETILEN = "e2e-java/src/test/java/com/antreklabs/bayi/uretilen"


def test_koru_uretilen_forge_mainde_kalir(ortam: Any) -> None:
    """K-T14: güvenilir pom değişince e2e-java eşitlenir; merge edilmiş üretilen testler (forge
    main) korunur, çalışma ağacındaki uretilen/ içeriği forge'a girmez."""
    assert ortam("sync-dizin", "e2e-java").returncode == 0
    merge = _forge_main_commit(
        ortam,
        {
            f"{URETILEN}/MergeEdilenTest.java": "class MergeEdilenTest {}\n",
            "e2e-java/src/test/java/com/antreklabs/bayi/birim/uretilen/IcTest.java": "class I {}\n",
        },
    )
    kaynak_uretilen = ortam.src / URETILEN
    kaynak_uretilen.mkdir(parents=True)
    (kaynak_uretilen / "YerelTest.java").write_text("class YerelTest {}\n")
    (kaynak_uretilen / ".gitkeep").write_text("")
    (ortam.src / "e2e-java" / "pom.xml").write_text("<project><tmpdir/></project>\n")

    r = ortam("sync-dizin", "e2e-java", "--koru", "uretilen")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "forge main'deki 2 dosya olduğu gibi kaldı" in r.stdout
    assert _ref(ortam.bare, "main^") == merge
    degisen = _git(ortam.bare, "diff", "--name-status", merge, "main", bare=True).splitlines()
    assert degisen == ["M\te2e-java/pom.xml"]
    agac = _git(ortam.bare, "ls-tree", "-r", "--name-only", "main", bare=True).splitlines()
    assert f"{URETILEN}/MergeEdilenTest.java" in agac
    assert f"{URETILEN}/YerelTest.java" not in agac

    # Korumasız eşitleme merge edilmiş testi siler (seçeneğin neden gerektiğinin kanıtı).
    r = ortam("sync-dizin", "e2e-java")
    assert r.returncode == 0, r.stderr
    agac = _git(ortam.bare, "ls-tree", "-r", "--name-only", "main", bare=True).splitlines()
    assert f"{URETILEN}/MergeEdilenTest.java" not in agac
    assert f"{URETILEN}/YerelTest.java" in agac


def test_koru_yol_ve_cok_deger(ortam: Any) -> None:
    """`/` içeren yol <dizin>'e göre korunur (ör. e2e tests/generated); virgül + tekrar birleşir."""
    merge = _forge_main_commit(ortam, {"e2e/tests/generated/merged.spec.ts": "m\n"})
    (ortam.src / "e2e" / "tests" / "generated").mkdir(parents=True)
    (ortam.src / "e2e" / "tests" / "generated" / "yerel.spec.ts").write_text("y\n")
    (ortam.src / "e2e" / "a.spec.ts").write_text("test v2\n")
    r = ortam("sync-dizin", "e2e", "--koru", "tests/generated,yok-boyle", "--koru", "uretilen")
    assert r.returncode == 0, r.stderr + r.stdout
    degisen = _git(ortam.bare, "diff", "--name-status", merge, "main", bare=True).splitlines()
    assert degisen == ["M\te2e/a.spec.ts"]


def test_forge_hooklari_calismaz_fetch_head_yazilmaz(ortam: Any) -> None:
    """GÜV-Y2: root git forge deposunun hook'larını (deponun core.hooksPath'i dahil) çalıştırmaz."""
    isaret = ortam.state / "kanca-calisti"
    kanca = f"#!/bin/sh\necho calisti >> '{isaret}'\n"
    hooks = ortam.bare / "hooks"
    hooks.mkdir(exist_ok=True)
    ozel = ortam.bare / "ozel-hooks"
    ozel.mkdir()
    for d in (hooks, ozel):
        for ad in ("reference-transaction", "post-checkout", "pre-auto-gc", "post-merge"):
            (d / ad).write_text(kanca)
            (d / ad).chmod(0o755)
    _git(ortam.bare, "config", "core.hooksPath", str(ozel), bare=True)
    r = ortam("sync-dizin", "e2e-java", "--baseline", "--koru", "uretilen")
    assert r.returncode == 0, r.stderr + r.stdout
    assert _ref(ortam.bare, "demo-baseline^{commit}") == _ref(ortam.bare, "main")
    assert not isaret.exists(), isaret.read_text()
    assert not (ortam.bare / "FETCH_HEAD").exists()


def test_volume_yoksa_olusturmadan_hata(ortam: Any) -> None:
    """OPS-D2: yanlış COMPOSE_PROJECT_NAME'de boş volume oluşturulup bırakılmaz."""
    r = ortam("sync-dizin", "e2e-java", FAKE_NO_VOLUME="1")
    assert r.returncode != 0 and "forge volume'ü yok" in r.stderr
    log = (ortam.state / "docker.log").read_text() if (ortam.state / "docker.log").exists() else ""
    assert "volume create" not in log
    assert "run " not in log


def test_ic_betik_safe_directory_global_yapilandirmadan() -> None:
    """git 2.39'da yerel clone/push alt süreçleri `-c safe.directory`'yi görmez (OPS-Y1): iç betik
    safe.directory'yi GIT_CONFIG_GLOBAL dosyasından verir ve zorla push kullanmaz."""
    ic = SCRIPT.read_text().split('if [ "$MODE" = sync-dizin ]; then\n  [ -d "$SRC_ABS/$DIZIN" ]')[
        1
    ]
    ic = ic.split("INNER\n  exit 0")[0]
    assert "directory = *" in ic and 'GIT_CONFIG_GLOBAL="$W/gitconfig"' in ic
    assert "push -q -f" not in ic and "push -f" not in ic
    assert "fetch -q --atomic --no-tags --no-write-fetch-head" in ic
    assert "hooksPath = /dev/null" in ic
    assert "g() { git -c safe.directory='*' -c core.hooksPath=/dev/null" in ic
    # Tüm git çağrıları g() üzerinden (doğrudan `git ` yalnız g tanımında).
    git_satirlari = [
        s
        for s in ic.splitlines()
        if re.search(r"(?<![.\w-])git\s", s) and not s.lstrip().startswith("#")
    ]
    assert git_satirlari == [
        "g() { git -c safe.directory='*' -c core.hooksPath=/dev/null \"$@\"; }"
    ]


@pytest.mark.parametrize(
    ("args", "mesaj"),
    [
        (("sync-dizin",), "dizin adı ister"),
        (("sync-dizin", "../core"), "geçersiz dizin adı"),
        (("sync-dizin", "a/b"), "geçersiz dizin adı"),
        (("sync-dizin", "..\ne2e-java"), "geçersiz dizin adı"),
        (("sync-dizin", "e2e-java\n"), "geçersiz dizin adı"),
        (("sync-dizin", "web"), "uygulama dizini"),
        (("sync-dizin", "yok-boyle"), "kaynak dizin yok"),
        (("sync-dizin", "e2e-java", "--force"), "--force ile birlikte"),
        (("--baseline",), "yalnızca sync-dizin"),
        (("--koru", "uretilen"), "yalnızca sync-dizin"),
        (("sync-dizin", "e2e-java", "--koru"), "alt yol ister"),
        (("sync-dizin", "e2e-java", "--koru", "../core"), "geçersiz --koru"),
        (("sync-dizin", "e2e-java", "--koru", "/etc"), "geçersiz --koru"),
        (("sync-dizin", "e2e-java", "--koru", "a/../../b"), "geçersiz --koru"),
        (("sync-dizin", "e2e-java", "--koru", "uret*"), "geçersiz --koru"),
        (("sync-dizin", "e2e-java", "--koru", "a,,b"), "geçersiz --koru"),
        (("sync-dizin", "e2e-java", "--koru", "uretilen\nx"), "geçersiz --koru"),
    ],
)
def test_hatali_argumanlar(ortam: Any, args: tuple[str, ...], mesaj: str) -> None:
    once = _ref(ortam.bare, "main")
    r = ortam(*args)
    assert r.returncode != 0
    assert mesaj in r.stderr
    assert _ref(ortam.bare, "main") == once


DUMAN_IMAJ = os.environ.get("TP_FORGE_IMAGE_DUMAN", "testingprobe-core:local")


@pytest.mark.skipif(
    os.environ.get("TP_DOCKER_DUMAN") != "1" or shutil.which("docker") is None,
    reason="docker duman testi: TP_DOCKER_DUMAN=1 ile açılır (gerçek core imajı, geçici volume)",
)
def test_docker_duman_kok_konteyner_10001_deposu(tmp_path: Path) -> None:
    """Gerçek forge koşulu (OPS-Y1): `forge-init` init depoyu 10001:1001 + --shared=0666 kurar;
    sync-dizin kök konteynerde (git 2.39) çalışır; --koru uretilen merge edilmiş testi korur, depo
    hook'u çalışmaz (K-T14, GÜV-Y2). Geçici volume testin sonunda silinir."""
    if subprocess.run(["docker", "image", "inspect", DUMAN_IMAJ], capture_output=True).returncode:
        pytest.skip(f"{DUMAN_IMAJ} imajı yok")
    vol = f"tpduman{os.getpid()}_tp_forge"
    src = tmp_path / "demo-app"
    yoksay = shutil.ignore_patterns("node_modules", "target", "results", "kanit", "e2e-java")
    shutil.copytree(REPO / "demo-app", src, ignore=yoksay)
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("TP_FORGE", "GIT_"))},
        "COMPOSE_PROJECT_NAME": f"tpduman{os.getpid()}",
        "TP_FORGE_VOLUME": vol,
        "TP_FORGE_SRC": str(src),
        "TP_FORGE_IMAGE": DUMAN_IMAJ,
    }

    def kos(*a: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT), *a], env=env, capture_output=True, text=True, timeout=300
        )

    def depo(komut: str) -> str:
        return subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                "10001:1001",
                "-v",
                f"{vol}:/forge",
                "--entrypoint",
                "sh",
                DUMAN_IMAJ,
                "-c",
                "g(){ git -c safe.directory='*' --git-dir=/forge/demo-app.git \"$@\"; }; " + komut,
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    try:
        r = kos()
        assert r.returncode == 0, r.stderr + r.stdout
        assert depo("g config receive.denyNonFastforwards") == "true"
        shutil.copytree(
            REPO / "demo-app" / "e2e-java",
            src / "e2e-java",
            ignore=shutil.ignore_patterns("target", "results", "kanit"),
        )
        r = kos("sync-dizin", "e2e-java", "--baseline")
        assert r.returncode == 0, r.stderr + r.stdout
        main, base, kir_ust = depo(
            "g rev-parse main 'demo-baseline^{commit}' demo/break-locator^"
        ).split()
        assert main == base == kir_ust
        assert depo("g cat-file -t demo/break-locator:e2e-java/pom.xml") == "blob"
        assert depo("find /forge/demo-app.git ! -uid 10001 | head -1") == ""
        r = kos("sync-dizin", "e2e-java", "--baseline")
        assert r.returncode == 0 and "commit yazılmadı" in r.stdout, r.stderr

        # K-T14 + GÜV-Y2: forge main'e merge edilmiş üretilen test (10001 olarak) + depoya hook;
        # kök konteynerde --koru uretilen eşitlemesi testi korur, hook'u çalıştırmaz.
        uretilen = "e2e-java/src/test/java/com/antreklabs/bayi/uretilen"
        depo(
            "export HOME=/tmp; cd /tmp && "
            "git -c safe.directory='*' clone -q /forge/demo-app.git c && cd c && "
            f"printf 'class MergeTest {{}}\\n' > {uretilen}/MergeTest.java && git add -A && "
            "git -c user.name=t -c user.email=t@x commit -q -m merge && git push -q origin main && "
            "printf '#!/bin/sh\\ntouch /forge/kanca-calisti\\n' "
            "> /forge/demo-app.git/hooks/reference-transaction && "
            "chmod +x /forge/demo-app.git/hooks/reference-transaction"
        )
        merge = depo("g rev-parse main")
        (src / uretilen / "YerelTest.java").write_text("class YerelTest {}\n")
        pom = src / "e2e-java" / "pom.xml"
        pom.write_text(pom.read_text() + "<!-- duman -->\n")
        r = kos("sync-dizin", "e2e-java", "--koru", "uretilen")
        assert r.returncode == 0, r.stderr + r.stdout
        assert depo("g rev-parse main^") == merge
        assert depo(f"g diff --name-only {merge} main") == "e2e-java/pom.xml"
        assert depo(f"g cat-file -t main:{uretilen}/MergeTest.java") == "blob"
        assert depo(f"g ls-tree --name-only main {uretilen}/YerelTest.java") == ""
        assert (
            depo("ls /forge/kanca-calisti /forge/demo-app.git/FETCH_HEAD 2>/dev/null; true") == ""
        )
        r = kos("sync-dizin", "e2e-app", "--koru", "uretilen")
        assert r.returncode == 0, r.stderr + r.stdout
    finally:
        subprocess.run(["docker", "volume", "rm", "-f", vol], capture_output=True)
