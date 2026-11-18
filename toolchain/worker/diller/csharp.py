"""C# / .NET yolu (014 test dilleri §3.2, Ş2): sembol tablosu, statik kontrol ve AST koruması.

İki hedef proje aynı hattı paylaşır (`CsKok`): web (`e2e-csharp`, Playwright .NET + NUnit) ve
Windows (`e2e-app-csharp`, Appium .NET + NUnit, NovaWindows). Adımlar Java hattıyla aynıdır:
`app → deps → guard → compile → run` (worker/java.py deseni).

Araç `cs-araclar.dll`dir (`toolchain/cs-araclar/`, Roslyn): kodu yalnızca AYRIŞTIRIR.

- **Bağımlılık kilidi (`deps`):** MSBuild proje dosyası ve NuGet yapılandırması kod çalıştırabilir
  (hedefler, görevler, `Exec`; `Directory.Build.*`, `*.rsp`). Commit'teki dört kilitli dosya
  (`<proje>.csproj`, `Directory.Packages.props`, `packages.lock.json`, `nuget.config`) imajdaki
  güvenilir kopyayla (`TP_E2E_CSHARP_DEPS/<web|windows>/`, `toolchain/e2e-csharp-deps/`) bayt bayt
  aynı olmalı. Proje ağacında başka hiçbir MSBuild/NuGet dosyası (`*.props`, `*.targets`, `*.rsp`,
  `*.sln(x)`, başka `*.csproj`, `global.json`, `Directory.Build.*`, `.config/dotnet-tools.json`,
  `NuGet.Config` türevleri), derleme çıktısı (`bin/`, `obj/`: `obj/*.nuget.g.props` SDK tarafından
  içe aktarılır) ya da ikili (`*.dll`, `*.exe`) ve hiçbir sembolik bağ bulunamaz.
- **Derleme (`compile`):** imajdaki sabit `dotnet` (`TP_DOTNET`). Önce çevrimdışı, kilitli restore:
  kaynak ve geri dönüş klasörü imajda ısıtılmış salt okunur paket klasörüdür
  (`TP_E2E_CSHARP_DEPS/nuget`), yazılabilir `NUGET_PACKAGES` koşu başına geçici dizindir
  (Maven `repo.local.tail` karşılığı). Sonra `dotnet build --no-restore -warnaserror`; derleme
  sunucusu ve düğüm yeniden kullanımı kapalı. Ortam izin listesidir: `DOTNET_*`, `MSBUILD*`,
  `NUGET_*`, `PLATFORM` (MSBuild özelliğine dönüşür) geçmez.
- **Koruma (`guard`):** `Tests/Generated/` altındaki her test `cs-araclar guard` ile (izin listesi)
  denetlenir; `Kimlikler.cs` saf veri olmalı. `repair` modunda ayrıca base..head farkında yalnızca
  `Kimlikler.cs` sabit literal'leri değişebilir (`cs-araclar locators diff`).

Ş0 eklenti protokolü (plan.md §3.1) modül sonundaki `EKLENTI` ile sağlanır (keşif
`worker/diller/__init__.py`; `/symbols`, `/ast-guard`, `/check` dağıtımı oradan). Ayarlar
`Settings` alanından, yoksa ortamdan okunur (`cs_ayarlari`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from toolchain_common import gitforge, proc
from toolchain_common.settings import Settings

if TYPE_CHECKING:  # pragma: no cover
    import httpx

    from toolchain_common import repos

LANG = "csharp"
WEB = "web"
WINDOWS = "windows"
PLATFORMS = (WEB, WINDOWS)
STEPS = ("app", "deps", "guard", "compile", "run")
GENERATED_DIR = "Tests/Generated"
CHECK_PREFIX = "local-ci"
# Kilitli (güvenilir kopyası olan) dosyalar; proje dosyasının adı köke göre değişir.
KILITLI_ORTAK = ("Directory.Packages.props", "packages.lock.json", "nuget.config")
PROJE_DOSYASI = {WEB: "Antreklabs.Bayi.E2e.csproj", WINDOWS: "Antreklabs.Bayi.E2eApp.csproj"}
# MSBuild / NuGet / dotnet CLI'nin proje ağacından okuduğu (kod çalıştırabilen) dosyalar.
_YASAK_UZANTILAR = (".props", ".targets", ".rsp", ".sln", ".slnx", ".slnf", ".csproj", ".fsproj",
                    ".vbproj", ".proj", ".dll", ".exe", ".so", ".dylib")  # fmt: skip
_YASAK_ADLAR = frozenset({"global.json", "nuget.config", "dotnet-tools.json",
                          "directory.build.props", "directory.build.targets", "directory.build.rsp",
                          "directory.packages.props", "packages.lock.json"})  # fmt: skip
_YASAK_DIZINLER = frozenset({"bin", "obj", ".config"})
KIMLIK_RE = re.compile(r"\A(?:Pages|Ekranlar)/Kimlikler\.cs\Z")
# Test dosyası (proje köküne göre): Tests/**/<Ad>Tests.cs (üretilen ve elle yazılmış).
CS_TEST_FILE_RE = re.compile(
    r"\ATests/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*Tests?\.cs\Z"
)
# MSBuild tanısı: "/yol/Dosya.cs(12,5): error CS1002: ; expected [/yol/proje.csproj]"
COMPILE_LINE = re.compile(
    r"^(?P<file>[^\s(][^(]*?\.cs)\((?P<line>\d+),(?P<col>\d+)\): "
    r"(?P<sev>error|warning) (?P<code>[A-Z]+\d+): (?P<msg>.*?)(?: \[[^\]]*\])?$"
)
MAX_DIAGNOSTICS = 200
# dotnet/MSBuild/NuGet davranışını dışarıdan değiştiren ortam (geçmez).
_ORTAM_ONEKLERI = ("DOTNET_", "MSBUILD", "NUGET_", "COMPLUS_", "CORECLR_", "ASPNETCORE_")
_ORTAM_ADLARI = frozenset({"PLATFORM", "CONFIGURATION", "TARGETFRAMEWORK", "OUTDIR",
                           "BASEINTERMEDIATEOUTPUTPATH", "RESTORESOURCES"})  # fmt: skip


class CsAracError(RuntimeError):
    """cs-araclar ya da dotnet çalışamadı (süre aşımı, bozuk çıktı, beklenmeyen çıkış kodu)."""


@dataclass(frozen=True)
class CsAyarlari:
    """C# hattının ayarları (Ş0 `Settings`'e taşıyana dek ortamdan; adlar TASARIM §2.2)."""

    e2e_csharp_root: str
    e2e_app_csharp_root: str
    deps: Path
    dotnet: str
    araclar_dll: Path
    build_timeout_s: float


def cs_ayarlari(cfg: Settings, env: dict[str, str] | None = None) -> CsAyarlari:
    e = os.environ if env is None else env

    def deger(alan: str, ad: str, varsayilan: str) -> str:
        v = getattr(cfg, alan, None)
        return str(v) if v else (e.get(ad) or "").strip() or varsayilan

    return CsAyarlari(
        e2e_csharp_root=deger("e2e_csharp_root", "TP_E2E_CSHARP_ROOT", "e2e-csharp"),
        e2e_app_csharp_root=deger(
            "e2e_app_csharp_root", "TP_E2E_APP_CSHARP_ROOT", "e2e-app-csharp"
        ),
        deps=Path(deger("e2e_csharp_deps", "TP_E2E_CSHARP_DEPS", "/opt/e2e-csharp")),
        dotnet=deger("dotnet", "TP_DOTNET", "/usr/share/dotnet/dotnet"),
        araclar_dll=Path(
            deger("cs_araclar_dll", "TP_CS_ARACLAR_DLL", "/opt/cs-araclar/cs-araclar.dll")
        ),
        build_timeout_s=float(
            getattr(cfg, "dotnet_timeout_s", None) or e.get("TP_DOTNET_TIMEOUT_S") or 600
        ),
    )


@dataclass(frozen=True)
class CsKok:
    """Bir C# hattının hedef projesi: forge'daki kök + imajdaki güvenilir kopyalar."""

    platform: str
    root: str  # forge deposundaki proje kökü
    trusted: Path  # güvenilir kopya dizini (`<deps>/web` | `<deps>/windows`)
    nuget: Path  # ısıtılmış, salt okunur paket klasörü (çevrimdışı kaynak + geri dönüş)
    ad: str  # iletilerdeki proje adı (`e2e-csharp` | `e2e-app-csharp`)

    @property
    def proje(self) -> str:
        return PROJE_DOSYASI[self.platform]

    @property
    def kilitli(self) -> tuple[str, ...]:
        return (self.proje, *KILITLI_ORTAK)

    @property
    def kimlikler(self) -> str:
        return "Pages/Kimlikler.cs" if self.platform == WEB else "Ekranlar/Kimlikler.cs"


def cs_kok(cfg: Settings, platform: str | None) -> CsKok:
    """Platformun C# projesi: web (ya da platform yok) → `e2e-csharp`, windows →
    `e2e-app-csharp`."""
    from worker import diller as _diller

    a = cs_ayarlari(cfg)
    p = platform or WEB
    if p == WEB:
        # Kök çözümü Ş0 kuralı: proje bloğu `dil_kokleri` > env > Settings/varsayılan.
        root = _diller.kok(cfg, "TP_E2E_CSHARP_ROOT", a.e2e_csharp_root, None).strip("/")
        return CsKok(WEB, root, a.deps / "web", a.deps / "nuget", "e2e-csharp")
    if p == WINDOWS:
        root = _diller.kok(cfg, "TP_E2E_APP_CSHARP_ROOT", a.e2e_app_csharp_root, WINDOWS)
        return CsKok(
            WINDOWS, root.strip("/"), a.deps / "windows", a.deps / "nuget", "e2e-app-csharp"
        )
    raise ValueError(f"C# hattı platformu yalnızca {PLATFORMS} olabilir: {platform!r}")


def check_name(platform: str | None) -> str:
    """Kontrol kaydı adı (core `diller/csharp.check_adi` ile aynı): `local-ci-<p>-csharp`."""
    p = platform or WEB
    if p not in PLATFORMS:
        raise ValueError(f"C# kontrolü platformu: {PLATFORMS}")
    return f"{CHECK_PREFIX}-{p}-{LANG}"


def validate_test_file(value: str) -> str:
    if not isinstance(value, str) or not CS_TEST_FILE_RE.match(value) or ".." in value:
        raise ValueError(f"geçersiz C# test dosyası: {value!r} (beklenen: Tests/**/<Ad>Tests.cs)")
    return value


def validate_test_files(values: list[str]) -> list[str]:
    if len(values) > 200:
        raise ValueError("en fazla 200 test dosyası verilebilir")
    return list(dict.fromkeys(validate_test_file(x) for x in values))


# ------------------------------------------------------------------------------- ortam


def dotnet_env(
    home: Path, nuget_packages: Path, base: dict[str, str] | None = None
) -> dict[str, str]:
    """dotnet/MSBuild/NuGet yapılandıran değişkenler geçmez; ev dizini ve paket klasörü koşu
    başına geçicidir. `base` verilmezse süreç ortamı (worker: derleme test kodu çalıştırmaz);
    test-runner yalnız izin listesini (`base`) verir."""
    kaynak = os.environ if base is None else base
    env = {
        k: v
        for k, v in kaynak.items()
        if not k.upper().startswith(_ORTAM_ONEKLERI) and k.upper() not in _ORTAM_ADLARI
    }
    env.update(
        {
            "HOME": str(home),
            "DOTNET_CLI_HOME": str(home),
            "NUGET_PACKAGES": str(nuget_packages),
            "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
            "DOTNET_NOLOGO": "1",
            "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
            "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false",
            "DOTNET_ADD_GLOBAL_TOOLS_TO_PATH": "0",
            "DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE": "1",
            "MSBUILDDISABLENODEREUSE": "1",
            "MSBuildEnableWorkloadResolver": "false",
            "UseSharedCompilation": "false",
        }
    )
    return env


def araclar_argv(cfg: Settings, *args: str) -> list[str]:
    a = cs_ayarlari(cfg)
    return [a.dotnet, str(a.araclar_dll), *args]


def _araclar_env() -> dict[str, str]:
    tmp = Path(tempfile.gettempdir())
    return dotnet_env(tmp, tmp / "tp-cs-araclar-nuget")


# ------------------------------------------------------------------------------ /symbols


def run_symbols(cfg: Settings, root: Path, kok: CsKok | None = None) -> proc.ProcResult:
    argv = araclar_argv(cfg, "symbols", "--root", str(root))
    if kok is not None:
        argv += ["--platform", kok.platform]
    return proc.run(
        argv, env=_araclar_env(), timeout_s=cfg.symbols_timeout_s, keep_full_stdout=True
    )


def symbols(cfg: Settings, root: Path, kok: CsKok | None = None) -> dict[str, Any]:
    """Eklenti protokolü: `symbols(root)` → TS `tp-symbols` şemasında tablo (+ `lang`)."""
    res = run_symbols(cfg, root, kok)
    if res.timed_out:
        raise CsAracError("cs-araclar symbols süre sınırını aştı")
    try:
        table = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise CsAracError(f"cs-araclar symbols çıktısı okunamadı: {res.stderr[:300]}") from exc
    if res.exit_code != 0 or not isinstance(table, dict) or "page_objects" not in table:
        msg = table.get("error") if isinstance(table, dict) else None
        raise CsAracError(f"Sembol tablosu çıkarılamadı: {msg or res.stderr[:300]}")
    table.setdefault("lang", LANG)
    return table


# --------------------------------------------------------------------------------- deps


def _sha256(path: Path) -> str | None:
    try:
        if path.is_symlink():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _yasak_mi(rel: Path) -> str | None:
    parcalar = rel.parts
    if any(p.lower() in _YASAK_DIZINLER for p in parcalar[:-1]):
        return (
            "derleme çıktısı / araç yapılandırması dizini (bin/, obj/, .config/) commit'e konamaz"
        )
    ad = parcalar[-1].lower()
    if ad in _YASAK_ADLAR or ad.endswith(_YASAK_UZANTILAR) or ad.startswith("directory.build."):
        return "MSBuild/NuGet bu dosyayı okur ve kod çalıştırabilir; yalnız güvenilir kopyalar"
    return None


def check_deps(cfg: Settings, root: Path, kok: CsKok) -> dict[str, Any]:
    """Kilitli dosyalar güvenilir kopyayla bayt eşit mi; ağaçta başka MSBuild/NuGet dosyası,
    derleme çıktısı ya da sembolik bağ var mı?"""
    sha: dict[str, str] = {}
    for ad in kok.kilitli:
        want = _sha256(kok.trusted / ad)
        if want is None:
            return {
                "ok": False,
                "error": f"İmajda {kok.ad} güvenilir {ad} yok (toolchain imajı hatalı).",
            }
        have = _sha256(root / ad)
        if have is None:
            return {"ok": False, "error": f"Commit'te {kok.root}/{ad} yok ya da sembolik bağ."}
        if have != want:
            return {
                "ok": False,
                "error": (
                    f"{kok.root}/{ad} imajdaki güvenilir kopyadan farklı; çevrimdışı ortamda yeni "
                    "bağımlılık kurulamaz ve MSBuild proje/yapılandırma dosyaları kod çalıştırır "
                    "(toolchain imajı yeniden derlenmeli: "
                    f"toolchain/e2e-csharp-deps/{kok.platform}/{ad})."
                ),
                "file": ad,
                "sha256": have,
                "image_sha256": want,
            }
        sha[ad] = have
    kilitli = set(kok.kilitli)
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_symlink():
            return {
                "ok": False,
                "error": f"{rel.as_posix()}: sembolik bağ kabul edilmez.",
                "file": rel.as_posix(),
            }
        if p.is_dir() or rel.as_posix() in kilitli:
            continue
        neden = _yasak_mi(rel)
        if neden:
            return {"ok": False, "error": f"{rel.as_posix()}: {neden}.", "file": rel.as_posix()}
    return {"ok": True, "sha256": sha}


# ------------------------------------------------------------------------------ compile


def _relpath(raw: str, root: Path) -> str:
    try:
        return Path(raw).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return Path(raw).name


def parse_compile(output: str, root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int, str]] = set()
    for line in output.splitlines():
        m = COMPILE_LINE.match(line.strip())
        if not m:
            continue
        key = (m["file"], int(m["line"]), int(m["col"]), m["code"])
        if key in seen:  # MSBuild özetinde aynı tanı ikinci kez basılır
            continue
        seen.add(key)
        out.append(
            {
                "file": _relpath(m["file"], root),
                "line": int(m["line"]),
                "column": int(m["col"]),
                "severity": m["sev"],
                "code": m["code"],
                "message": m["msg"][:500],
            }
        )
        if len(out) >= MAX_DIAGNOSTICS:
            break
    return out


def restore_argv(cfg: Settings, root: Path, kok: CsKok) -> list[str]:
    a = cs_ayarlari(cfg)
    return [
        a.dotnet,
        "restore",
        str(root / kok.proje),
        "--locked-mode",
        "--source",
        str(kok.nuget),
        f"-p:RestoreFallbackFolders={kok.nuget}",
        "-p:RestoreIgnoreFailedSources=false",
        "--disable-build-servers",
        "-nodeReuse:false",
        "-nologo",
        "-v:q",
    ]


def build_argv(cfg: Settings, root: Path, kok: CsKok, configuration: str = "Release") -> list[str]:
    a = cs_ayarlari(cfg)
    return [
        a.dotnet,
        "build",
        str(root / kok.proje),
        "--no-restore",
        "-c",
        configuration,
        "-warnaserror",
        "--disable-build-servers",
        "-nodeReuse:false",
        "-p:UseSharedCompilation=false",
        "-p:Platform=AnyCPU",
        "-nologo",
        "-clp:NoSummary",
        "-v:q",
    ]


def restore_and_build(
    cfg: Settings,
    root: Path,
    kok: CsKok,
    work: Path,
    *,
    timeout_s: float | None = None,
    base_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Çevrimdışı kilitli restore + `dotnet build -warnaserror`. `work` geçici ev/paket dizinidir
    (çağıran siler). Sonuç Java `run_test_compile` biçimindedir."""
    a = cs_ayarlari(cfg)
    limit = timeout_s or a.build_timeout_s
    home, pkgs = work / "home", work / "nuget"
    home.mkdir(parents=True, exist_ok=True)
    pkgs.mkdir(parents=True, exist_ok=True)
    env = dotnet_env(home, pkgs, base_env)
    for d in ("bin", "obj"):  # commit'te olamaz (deps); yine de temiz başlanır
        shutil.rmtree(root / d, ignore_errors=True)
    outputs: list[str] = []
    total_ms = 0
    for adim, argv in (
        ("restore", restore_argv(cfg, root, kok)),
        ("build", build_argv(cfg, root, kok)),
    ):
        res = proc.run(argv, cwd=root, env=env, timeout_s=limit)
        total_ms += res.duration_ms
        outputs.append(f"$ {' '.join(res.argv)}\n{res.stdout}\n{res.stderr}")
        if not res.ok:
            out = "\n".join(outputs)
            diagnostics = parse_compile(out, root)
            result: dict[str, Any] = {
                "ok": False,
                "step": adim,
                "exit_code": res.exit_code,
                "duration_ms": total_ms,
                "diagnostics": diagnostics,
                "output": proc.truncate(out, 16 * 1024),
            }
            if res.timed_out:
                result["error"] = f"dotnet {adim} süre sınırını aştı ({int(limit)} sn)"
            elif adim == "restore":
                result["error"] = (
                    "dotnet restore (çevrimdışı, kilitli) başarısız: paket imajın ısıtılmış "
                    "önbelleğinde yok ya da packages.lock.json uyuşmuyor (ayrıntı: output)"
                )
            elif not diagnostics:
                result["error"] = "dotnet build başarısız (ayrıntı: output)"
            return result
    return {
        "ok": True,
        "exit_code": 0,
        "duration_ms": total_ms,
        "diagnostics": parse_compile("\n".join(outputs), root),
        "output": proc.truncate("\n".join(outputs), 16 * 1024),
    }


def run_compile(cfg: Settings, root: Path, kok: CsKok) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="tp-dotnet-") as work:
        return restore_and_build(cfg, root, kok, Path(work))


# -------------------------------------------------------------------------------- guard


def generated_files(root: Path) -> list[str]:
    gen = root / GENERATED_DIR
    if not gen.is_dir() or gen.is_symlink():
        return []
    return sorted(p.relative_to(root).as_posix() for p in gen.rglob("*.cs"))


def _report(res: proc.ProcResult, what: str) -> dict[str, Any]:
    if res.timed_out:
        raise CsAracError(f"cs-araclar {what} süre sınırını aştı")
    try:
        report = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise CsAracError(
            f"cs-araclar {what} çıktısı okunamadı: {res.stderr.strip()[:500]}"
        ) from exc
    if res.exit_code == 2 or not isinstance(report, dict) or "violations" not in report:
        msg = report.get("error") if isinstance(report, dict) else None
        raise CsAracError(f"cs-araclar {what} çalışamadı: {msg or res.stderr.strip()[:500]}")
    if res.exit_code not in (0, 1) or bool(report.get("ok")) != (res.exit_code == 0):
        raise CsAracError(f"cs-araclar {what} beklenmeyen çıkış kodu {res.exit_code}")
    return report


def run_guard(
    cfg: Settings, root: Path, kok: CsKok, files: list[str] | None = None
) -> dict[str, Any]:
    files = generated_files(root) if files is None else files
    res = proc.run(
        araclar_argv(
            cfg, "guard", "--root", str(root), "--platform", kok.platform, "--kimlikler", "--",
            *files,
        ),
        env=_araclar_env(),
        timeout_s=cfg.ast_guard_timeout_s,
        keep_full_stdout=True,
    )  # fmt: skip
    return _report(res, "guard")


def _git_bytes(cfg: Settings, repo: Path, *args: str) -> bytes:
    try:
        out = subprocess.run(
            gitforge._git_argv(repo, *args),
            env=gitforge.git_env(),
            capture_output=True,
            timeout=cfg.git_timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise gitforge.ForgeError("git süre aşımı") from exc
    if out.returncode != 0:
        msg = out.stderr.decode("utf-8", "replace").strip()
        raise gitforge.ForgeError(f"git {args[0]} başarısız: {msg[:300]}")
    return out.stdout


def repair_guard(cfg: Settings, repo: Path, base: str, head: str, kok: CsKok) -> dict[str, Any]:
    """Onarım modu: base..head'de yalnızca `Kimlikler.cs` sabit literal'leri değişir."""
    raw = _git_bytes(
        cfg, repo, "diff", "--name-status", "--no-renames", "-z", "--end-of-options", base, head
    ).decode("utf-8", "replace")
    parts = [p for p in raw.split("\0") if p]
    prefix = kok.root.strip("/") + "/"
    changed: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    testid_changes: list[dict[str, Any]] = []
    for status, path in zip(parts[0::2], parts[1::2], strict=False):
        rel = path[len(prefix) :] if path.startswith(prefix) else None
        locator = rel is not None and bool(KIMLIK_RE.match(rel))
        st = {"A": "added", "D": "deleted"}.get(status[:1], "modified")
        changed.append({"path": path, "status": st, "locator": locator})
        if not locator:
            violations.append(
                {
                    "code": "non_locator_file_changed",
                    "file": path,
                    "message": f"onarımda yalnızca {kok.kimlikler} değişebilir",
                }
            )
            continue
        if st != "modified":
            fiil = "eklenemez" if st == "added" else "silinemez"
            violations.append(
                {
                    "code": f"locator_file_{st}",
                    "file": path,
                    "message": f"Kimlikler.cs onarımda {fiil}",
                }
            )
            continue
        with tempfile.TemporaryDirectory(prefix="tp-kimlik-") as tmp:
            a, b = Path(tmp) / "base.cs", Path(tmp) / "head.cs"
            a.write_bytes(_git_bytes(cfg, repo, "show", f"{base}:{path}"))
            b.write_bytes(_git_bytes(cfg, repo, "show", f"{head}:{path}"))
            res = proc.run(
                araclar_argv(
                    cfg, "locators", "diff", "--base", str(a), "--head", str(b), "--file", path
                ),
                env=_araclar_env(),
                timeout_s=cfg.ast_guard_timeout_s,
                keep_full_stdout=True,
            )
        rep = _report(res, "locators diff")
        violations += rep.get("violations") or []
        testid_changes += rep.get("testid_changes") or []
    ok = not violations
    return {
        "tool": "cs-araclar",
        "schema_version": 1,
        "mode": "repair",
        "ok": ok,
        "noop": not changed,
        "base": base,
        "head": head,
        "root": kok.root,
        "changed_files": changed,
        "testid_changes": testid_changes,
        "added_entries": [],
        "removed_entries": [],
        "violations": violations,
        "summary": (
            f"Kimlik koruması {'geçti' if ok else 'başarısız'} (mod: repair) · değişen dosya: "
            f"{len(changed)} · kimlik değişikliği: {len(testid_changes)}"
        ),
    }


def guard_report(
    cfg: Settings, repo: Path, base: str, head: str, mode: str, root: Path, kok: CsKok
) -> dict[str, Any]:
    """`/ast-guard` ve `/check` için tek rapor (TS ast-guard / java-araclar biçimi)."""
    gen = run_guard(cfg, root, kok)
    rep = repair_guard(cfg, repo, base, head, kok) if mode == "repair" else None
    violations = list(gen.get("violations") or []) + list((rep or {}).get("violations") or [])
    ok = not violations
    return {
        "tool": "cs-araclar",
        "schema_version": 1,
        "mode": mode,
        "ok": ok,
        "noop": False,
        "base": base,
        "head": head,
        "root": kok.root,
        "files": gen.get("files", []),
        "changed_files": (rep or {}).get("changed_files", []),
        "testid_changes": (rep or {}).get("testid_changes", []),
        "added_entries": [],
        "removed_entries": [],
        "violations": violations,
        "summary": (
            f"C# AST koruması {'geçti' if ok else 'başarısız'} (mod: {mode}) · üretilen test: "
            f"{len(gen.get('files', []))} · ihlal: {len(violations)}"
        ),
        "generated": gen,
        "repair": rep,
    }


# ----------------------------------------------------------------------------- /check adımları


def run_static(
    cfg: Settings,
    repo: Path,
    sha: str,
    base_sha: str,
    root: Path,
    kok: CsKok,
    *,
    test_files: list[str] | None = None,
    mode: str = "pr",
) -> dict[str, dict[str, Any]]:
    """Eklenti protokolü `run_static()`: `deps → guard → compile` (koruma derlemeden ÖNCE: yalnız
    ayrıştırır; MSBuild ise güvenilir proje dosyasıyla da olsa paket hedeflerini çalıştırır).
    İlk başarısız adımda durur; sonuç adım sözlüğüdür (`worker/check.aggregate` girdisi)."""
    steps: dict[str, dict[str, Any]] = {}
    missing = [f for f in (test_files or []) if not (root / f).is_file()]
    if missing:
        steps["deps"] = {
            "ok": False,
            "error": "Test dosyası commit'te yok: " + ", ".join(missing),
            "missing_test_files": missing,
        }
        return steps
    steps["deps"] = check_deps(cfg, root, kok)
    if not steps["deps"]["ok"]:
        return steps
    try:
        guard = guard_report(cfg, repo, base_sha, sha, mode, root, kok)
        steps["guard"] = {"ok": bool(guard.get("ok")), "mode": mode, "base_sha": base_sha,
                          "report": guard}  # fmt: skip
    except CsAracError as exc:
        steps["guard"] = {"ok": False, "mode": mode, "error": str(exc)}
    if not steps["guard"]["ok"]:
        return steps
    steps["compile"] = run_compile(cfg, root, kok)
    return steps


def run_steps(
    cfg: Settings,
    req: Any,
    head: repos.Located,
    base: str | None,
    runner_client: httpx.Client | None,
    steps: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """`worker/check._run_java_steps` karşılığı (Ş0 `_execute_locked` dil dağıtımı bunu çağırır):
    app → deps → guard → compile → run (test-runner `lang=csharp`)."""
    from worker import check as checks

    full = head.sha
    kok = cs_kok(cfg, req.platform)
    steps["app"] = checks.app_step(cfg, head)
    if not steps["app"]["ok"]:
        return steps
    base_sha = base or gitforge.merge_base(head.repo, full, "main", cfg.git_timeout_s) or full
    with gitforge.checkout(head.repo, full, kok.root, cfg.git_timeout_s) as root:
        steps.update(
            run_static(
                cfg, head.repo, full, base_sha, root, kok,
                test_files=list(req.test_files), mode=req.ast_guard_mode,
            )
        )  # fmt: skip
        if not all(steps.get(s, {}).get("ok") for s in ("deps", "guard", "compile")):
            return steps
    body: dict[str, Any] = {
        "sha": full,
        "run_id": req.run_id or checks.default_run_id(full),
        "repeat_each": req.repeat_each,
        "retries": req.retries,
        "test_files": list(req.test_files),
        "env": req.runner_env(),
        "keep": req.keep,
        "lang": LANG,
        "platform": kok.platform,
    }
    steps["run"] = checks._call_runner(cfg, body, runner_client)
    return steps


# ------------------------------------------------------------------- Ş0 eklenti protokolü


def guard(
    cfg: Settings, repo: Path, base: str, head: str, mode: str, platform: str
) -> dict[str, Any]:
    """`/ast-guard` (plan.md §3.1 `WorkerDili.guard`)."""
    kok = cs_kok(cfg, platform)
    with gitforge.checkout(repo, head, kok.root, cfg.git_timeout_s) as root:
        return guard_report(cfg, repo, base, head, mode, root, kok)


def symbols_for_sha(cfg: Settings, full_sha: str, repo: Path, platform: str) -> dict[str, Any]:
    """`/symbols` (plan.md §3.1 `WorkerDili.symbols`): commit'in C# kökünden tablo."""
    kok = cs_kok(cfg, platform)
    with gitforge.checkout(repo, full_sha, kok.root, cfg.git_timeout_s) as root:
        table = symbols(cfg, root, kok)
    if kok.platform == WEB:
        table.setdefault("platform", WEB)
    return table


class _CsharpEklentisi:
    """plan.md §3.1 `WorkerDili` (Ş0 keşfi `EKLENTI`'yi okur; entegrasyon adaptörü)."""

    ad = LANG
    platformlar = PLATFORMS
    steps = STEPS
    hat = "tam"

    def validate_test_file(self, yol: str) -> str:
        return validate_test_file(yol)

    def symbols(self, cfg: Settings, full_sha: str, repo: Path, platform: str) -> dict[str, Any]:
        return symbols_for_sha(cfg, full_sha, repo, platform)

    def guard(
        self, cfg: Settings, repo: Path, base: str, head: str, mode: str, platform: str
    ) -> dict[str, Any]:
        return guard(cfg, repo, base, head, mode, platform)

    def run_static(
        self,
        cfg: Settings,
        req: Any,
        head: repos.Located,
        base: str | None,
        runner_client: httpx.Client | None,
        steps: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        return run_steps(cfg, req, head, base, runner_client, steps)


EKLENTI = _CsharpEklentisi()
