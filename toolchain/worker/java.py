"""Java yolu (009 plan §2.3–2.5): sembol tablosu, statik kontrol ve AST koruması.

Araç `java-araclar.jar`dır (`toolchain/java-araclar/`, JavaParser): kodu yalnızca AYRIŞTIRIR.
Statik kontrol çevrimdışı `mvn -o test-compile`dır:

- **Bağımlılık kilidi (`deps`):** commit'teki `pom.xml` imajdaki güvenilir kopyayla
  (`TP_E2E_APP_DEPS/pom.xml`, `toolchain/e2e-app-deps/`) bayt bayt aynı olmalı. Maven eklentileri
  kod çalıştırır; yalnızca imajda önceden ısıtılmış (çevrimdışı) bağımlılıklarla derlenir.
  `.mvn/` altındaki yapılandırma (`jvm.config`, `maven.config`, `extensions.xml`) Maven başlatıcısı
  tarafından okunur ve JVM'e ajan/eklenti yükletebilir: güvenilir kopyası yoksa bulunamaz
  (`.mvn/wrapper/` hariç; sarmalayıcı hiç çalıştırılmaz).
- **Derleme (`compile`):** commit'teki `mvnw` DEĞİL, imajdaki sabit Maven (`TP_MVN`) koşar;
  `MAVEN_OPTS`/`MAVEN_ARGS`/`mavenrc` devre dışı, `-o`, açıklama işlemcisi kapalı
  (`-proc:none`: `src/test/resources` altına konmuş bir `.class` + `META-INF/services` javac'ta kod
  çalıştıramasın), kaynak kopyalama atlanır. Isıtılmış depo salt okunur kuyruk
  (`maven.repo.local.tail`), yazılabilir baş deposu koşu başına geçici dizindir.
- **Koruma (`guard`):** `uretilen/` altındaki her test `java-araclar guard` ile (§2.8 izin listesi)
  denetlenir; `ekranlar/Kimlikler.java` saf veri olmalı. `repair` modunda ayrıca base..head
  farkında yalnızca `Kimlikler.java` kimlik literal'leri değişebilir (TS ast-guard `repair`
  karşılığı).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from toolchain_common import gitforge, proc
from toolchain_common.settings import Settings

LANGS = ("ts", "java")
# platform (§2.1) → dil: web Playwright/TypeScript, diğerleri Appium/Java.
PLATFORM_LANG = {"web": "ts", "android": "java", "ios": "java", "windows": "java"}
STEPS = ("app", "deps", "guard", "compile", "run")
GENERATED_DIR = "src/test/java/com/antreklabs/bayi/uretilen"
KIMLIK_RE = re.compile(r"\A(?:[^/]+/)*ekranlar/Kimlikler\.java\Z")
# Java test dosyası (e2e-app köküne göre): src/test/java/**/<Ad>Test.java (üretilen) ya da
# <Ad>Testi.java (elle yazılmış referans testler, testler/)
JAVA_TEST_FILE_RE = re.compile(
    r"\Asrc/test/java/(?:[A-Za-z_][A-Za-z0-9_]*/)+[A-Za-z_][A-Za-z0-9_]*Testi?\.java\Z"
)
# Maven başlatıcısının proje kökünden okuduğu yapılandırma; sarmalayıcı dosyaları zararsızdır
# (mvnw hiç çalıştırılmaz).
MVN_WRAPPER_OK = (".mvn/wrapper/maven-wrapper.properties", ".mvn/wrapper/maven-wrapper.jar")
COMPILE_LINE = re.compile(
    r"^\[(?P<sev>ERROR|WARNING)\] (?P<file>/[^\[]+?\.java)"
    r":\[(?P<line>\d+),(?P<col>\d+)\] (?P<msg>.*)$"
)
MAX_DIAGNOSTICS = 200
# JVM'e komut satırı dışından seçenek veren ortam değişkenleri (ajan yükleyebilir).
JVM_OPTION_ENV = ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS")


class JavaAracError(RuntimeError):
    """java-araclar çalışamadı (süre aşımı, bozuk çıktı, beklenmeyen çıkış kodu)."""


def resolve_lang(lang: str | None, platform: str | None) -> str:
    """`lang` ya da `platform`'dan dil; ikisi de yoksa `ts` (geriye uyum)."""
    from_platform = PLATFORM_LANG.get(platform) if platform else None
    if platform and from_platform is None:
        raise ValueError(f"platform yalnızca {tuple(PLATFORM_LANG)} olabilir")
    if lang and lang not in LANGS:
        raise ValueError(f"lang yalnızca {LANGS} olabilir")
    if lang and from_platform and lang != from_platform:
        raise ValueError(f"lang={lang} ile platform={platform} uyuşmuyor")
    return lang or from_platform or "ts"


def validate_java_test_file(value: str) -> str:
    if not isinstance(value, str) or not JAVA_TEST_FILE_RE.match(value) or ".." in value:
        raise ValueError(
            f"geçersiz Java test dosyası: {value!r} (beklenen: src/test/java/**/<Ad>Test[i].java)"
        )
    return value


def jar_argv(cfg: Settings, *args: str) -> list[str]:
    return [cfg.java, "-jar", str(cfg.java_araclar_jar), *args]


def _java_env() -> dict[str, str]:
    """JVM'e kullanıcı ortamından seçenek sızmasın (JAVA_TOOL_OPTIONS ajan yükleyebilir)."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in JVM_OPTION_ENV and not k.startswith("MAVEN_")
    }
    env["MAVEN_SKIP_RC"] = "1"  # /etc/mavenrc, ~/.mavenrc kabukta kaynaklanmaz
    return env


# ------------------------------------------------------------------------------ /symbols


def run_symbols(cfg: Settings, root: Path) -> proc.ProcResult:
    return proc.run(
        jar_argv(cfg, "symbols", "--root", str(root)),
        env=_java_env(),
        timeout_s=cfg.symbols_timeout_s,
        keep_full_stdout=True,
    )


# --------------------------------------------------------------------------------- deps


def _sha256(path: Path) -> str | None:
    try:
        if path.is_symlink():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def check_deps(cfg: Settings, root: Path) -> dict[str, Any]:
    """Commit'in `pom.xml`'i ve `.mvn/` yapılandırması imajdaki güvenilir kopyayla aynı mı."""
    want = _sha256(cfg.e2e_app_deps / "pom.xml")
    if want is None:
        return {"ok": False, "error": "İmajda e2e-app pom.xml yok (toolchain imajı hatalı)."}
    have = _sha256(root / "pom.xml")
    if have is None:
        return {"ok": False, "error": f"Commit'te {cfg.e2e_app_root}/pom.xml yok."}
    if have != want:
        return {
            "ok": False,
            "error": (
                f"{cfg.e2e_app_root}/pom.xml imajdaki güvenilir kopyadan farklı; çevrimdışı "
                "ortamda yeni bağımlılık/eklenti kurulamaz ve Maven eklentileri kod çalıştırır "
                "(toolchain imajı yeniden derlenmeli: toolchain/e2e-app-deps/pom.xml)."
            ),
            "pom_sha256": have,
            "image_pom_sha256": want,
        }
    mvn_dir = root / ".mvn"
    if mvn_dir.is_symlink():
        return {"ok": False, "error": ".mvn sembolik bağ olamaz."}
    if mvn_dir.is_dir():
        for p in sorted(mvn_dir.rglob("*")):
            rel = p.relative_to(root).as_posix()
            if p.is_dir() and not p.is_symlink():
                continue
            if rel in MVN_WRAPPER_OK and not p.is_symlink():
                continue
            trusted = _sha256(cfg.e2e_app_deps / rel)
            if trusted is None or trusted != _sha256(p):
                return {
                    "ok": False,
                    "error": (
                        f"{rel}: Maven başlatıcısı bu dosyayı okur (JVM seçenekleri/eklentiler); "
                        "güvenilir kopyası olmayan .mvn yapılandırması kabul edilmez."
                    ),
                    "config_file": rel,
                }
    return {"ok": True, "pom_sha256": have}


# ------------------------------------------------------------------------------ compile


def _relpath(raw: str, root: Path) -> str:
    try:
        return Path(raw).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return Path(raw).name


def parse_compile(output: str, root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in output.splitlines():
        m = COMPILE_LINE.match(line.strip())
        if not m:
            continue
        out.append(
            {
                "file": _relpath(m["file"], root),
                "line": int(m["line"]),
                "column": int(m["col"]),
                "severity": m["sev"].lower(),
                "message": m["msg"][:500],
            }
        )
        if len(out) >= MAX_DIAGNOSTICS:
            break
    return out


def compile_argv(cfg: Settings, root: Path, head_repo: Path) -> list[str]:
    return [
        cfg.mvn,
        "-B",
        "-q",
        "-o",
        "-f",
        str(root / "pom.xml"),
        f"-Dmaven.repo.local={head_repo}",
        f"-Dmaven.repo.local.tail={cfg.e2e_app_m2}",
        "-Dmaven.compiler.proc=none",
        "-Dmaven.resources.skip=true",
        "test-compile",
    ]


def run_test_compile(cfg: Settings, root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="tp-m2-") as head_repo:
        res = proc.run(
            compile_argv(cfg, root, Path(head_repo)),
            cwd=root,
            env=_java_env(),
            timeout_s=cfg.mvn_timeout_s,
        )
    out = res.stdout + res.stderr
    diagnostics = parse_compile(out, root)
    result: dict[str, Any] = {
        "ok": res.ok,
        "exit_code": res.exit_code,
        "duration_ms": res.duration_ms,
        "diagnostics": diagnostics,
        "output": proc.truncate(out, 16 * 1024),
    }
    if res.timed_out:
        result["error"] = f"mvn test-compile süre sınırını aştı ({int(cfg.mvn_timeout_s)} sn)"
    elif not res.ok and not diagnostics:
        result["error"] = "mvn test-compile başarısız (ayrıntı: output)"
    return result


# -------------------------------------------------------------------------------- guard


def generated_files(root: Path) -> list[str]:
    """`uretilen/` altındaki .java dosyaları (köke göre, sıralı; sembolik bağlar da listelenir —
    koruyucu onları reddeder)."""
    gen = root / GENERATED_DIR
    if not gen.is_dir() or gen.is_symlink():
        return []
    return sorted(p.relative_to(root).as_posix() for p in gen.rglob("*.java"))


def _report(res: proc.ProcResult, what: str) -> dict[str, Any]:
    if res.timed_out:
        raise JavaAracError(f"java-araclar {what} süre sınırını aştı")
    try:
        report = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise JavaAracError(
            f"java-araclar {what} çıktısı okunamadı: {res.stderr.strip()[:500]}"
        ) from exc
    if res.exit_code == 2 or not isinstance(report, dict) or "violations" not in report:
        msg = report.get("error") if isinstance(report, dict) else None
        raise JavaAracError(f"java-araclar {what} çalışamadı: {msg or res.stderr.strip()[:500]}")
    if res.exit_code not in (0, 1) or bool(report.get("ok")) != (res.exit_code == 0):
        raise JavaAracError(f"java-araclar {what} beklenmeyen çıkış kodu {res.exit_code}")
    return report


def run_guard(cfg: Settings, root: Path, files: list[str] | None = None) -> dict[str, Any]:
    """Üretilen testler (varsayılan: `uretilen/` altındakilerin hepsi) + Kimlikler saflığı."""
    files = generated_files(root) if files is None else files
    res = proc.run(
        jar_argv(cfg, "guard", "--root", str(root), "--kimlikler", "--", *files),
        env=_java_env(),
        timeout_s=cfg.ast_guard_timeout_s,
        keep_full_stdout=True,
    )
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


def repair_guard(cfg: Settings, repo: Path, base: str, head: str) -> dict[str, Any]:
    """Onarım (repair) modu: base..head'de yalnızca Kimlikler.java kimlik literal'leri değişir."""
    raw = _git_bytes(
        cfg, repo, "diff", "--name-status", "--no-renames", "-z", "--end-of-options", base, head
    ).decode("utf-8", "replace")
    parts = [p for p in raw.split("\0") if p]
    prefix = cfg.e2e_app_root.strip("/") + "/"
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
                    "message": "onarımda yalnızca ekranlar/Kimlikler.java değişebilir",
                }
            )
            continue
        if st != "modified":
            fiil = "eklenemez" if st == "added" else "silinemez"
            violations.append(
                {
                    "code": f"locator_file_{st}",
                    "file": path,
                    "message": f"Kimlikler.java onarımda {fiil}",
                }
            )
            continue
        with tempfile.TemporaryDirectory(prefix="tp-kimlik-") as tmp:
            a, b = Path(tmp) / "base.java", Path(tmp) / "head.java"
            a.write_bytes(_git_bytes(cfg, repo, "show", f"{base}:{path}"))
            b.write_bytes(_git_bytes(cfg, repo, "show", f"{head}:{path}"))
            res = proc.run(
                jar_argv(
                    cfg, "locators", "diff", "--base", str(a), "--head", str(b), "--file", path
                ),
                env=_java_env(),
                timeout_s=cfg.ast_guard_timeout_s,
                keep_full_stdout=True,
            )
        rep = _report(res, "locators diff")
        violations += rep.get("violations") or []
        testid_changes += rep.get("testid_changes") or []
    ok = not violations
    return {
        "tool": "java-araclar",
        "schema_version": 1,
        "mode": "repair",
        "ok": ok,
        "noop": not changed,
        "base": base,
        "head": head,
        "root": cfg.e2e_app_root,
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
    cfg: Settings, repo: Path, base: str, head: str, mode: str, root: Path
) -> dict[str, Any]:
    """`/ast-guard` ve `/check` için tek rapor: üretilen testler + Kimlikler (+ repair farkı).

    Biçim TS ast-guard raporuyla aynıdır (`ok`, `violations[]`, `summary`, …); `generated` alt
    raporu ve (repair modunda) `repair` alt raporu ayrıca taşınır.
    """
    gen = run_guard(cfg, root)
    rep = repair_guard(cfg, repo, base, head) if mode == "repair" else None
    violations = list(gen.get("violations") or []) + list((rep or {}).get("violations") or [])
    ok = not violations
    return {
        "tool": "java-araclar",
        "schema_version": 1,
        "mode": mode,
        "ok": ok,
        "noop": False,
        "base": base,
        "head": head,
        "root": cfg.e2e_app_root,
        "files": gen.get("files", []),
        "changed_files": (rep or {}).get("changed_files", []),
        "testid_changes": (rep or {}).get("testid_changes", []),
        "added_entries": [],
        "removed_entries": [],
        "violations": violations,
        "summary": (
            f"Java AST koruması {'geçti' if ok else 'başarısız'} (mod: {mode}) · üretilen test: "
            f"{len(gen.get('files', []))} · ihlal: {len(violations)}"
        ),
        "generated": gen,
        "repair": rep,
    }
