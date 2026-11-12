"""Forge ortak parçaları: hata tipleri, girdi doğrulama, merge sonucu ve `get_forge` fabrikası.

`TP_FORGE=local` → `LocalForge` (tp_forge volume'ündeki bare git deposu, PR kaydı JSON dosyası).
`TP_FORGE=github` → `GitHubForge` (GitHub REST; App veya token kimliği).
Her iki adaptör de `tp_core.ports.ForgePort`'u uygular; iş akışları yalnızca porta bağımlıdır.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from tp_core.features.codegen import platform as platformlar
from tp_core.ports import CheckRun

if TYPE_CHECKING:
    from tp_core.ports import ForgePort

# Korunan dal: doğrudan commit yok, yalnızca merge_pr ile ilerler.
PROTECTED_BRANCHES: frozenset[str] = frozenset({"main"})
# Merge için zorunlu kontroller adaptöre özgüdür:
# - LocalForge: yerel CI runner'ının (test-runner) yazdığı tek check.
# - GitHubForge: `.github/workflows/ci.yml` iş adları = `scripts/github-ruleset.sh` CHECKS.
#   `TP_REQUIRED_CHECKS` (virgüllü) ile değiştirilebilir; ruleset ile aynı tutulmalıdır.
REQUIRED_CHECK = platformlar.YEREL_CHECK  # `local-ci`: LocalForge'un varsayılan zorunlu kontrolü
LOCAL_REQUIRED_CHECKS: tuple[str, ...] = (REQUIRED_CHECK,)
GITHUB_REQUIRED_CHECKS: tuple[str, ...] = ("test-local", "ast-guard", "semgrep")
REQUIRED_CHECKS_ENV = "TP_REQUIRED_CHECKS"
# Kural seti bypass'ı yalnızca bu insan hesabındadır (anayasa: bot merge edemez).
BYPASS_ACTOR = "demo-admin"
# Bot kimlikleri: PR açabilir, merge edemez.
BOT_ACTORS: frozenset[str] = frozenset({"tp-bot"})

# PR dal adları ve etiketleri — .github/workflows/ci.yml AST koruması modu bunlara bakar
# (scripts/github-ast-guard-mode.sh: tp/repair-* veya tp-repair etiketi → onarım modu).
CASE_BRANCH_PREFIX = "tp/case-"
REPAIR_BRANCH_PREFIX = "tp/repair-"
REPAIR_LABEL = "tp-repair"

BOT_NAME = "tp-bot"
BOT_EMAIL = "bot@testingprobe.local"

_MAX_REF_LEN = 200
_MAX_PATH_LEN = 1024
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_ACTOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CHECK_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/()-]{0,99}$")


class ForgeError(Exception):
    """Forge işlemi başarısız."""


class ForgeValidationError(ForgeError, ValueError):
    """Geçersiz girdi (dal adı, yol, sorgu ...). Komut çalıştırılmadan reddedilir."""


class ForgeNotFoundError(ForgeError, LookupError):
    """Ref, dosya veya PR bulunamadı."""


class ForgeConflictError(ForgeError):
    """Merge çakışması veya eşzamanlı değişiklik (ref beklenen yerde değil)."""


class ForgeProtectionError(ForgeError, PermissionError):
    """Dal koruması: korunan dala doğrudan commit, CI yeşil değilken merge, bot merge'ü."""


class ForgeStateError(ForgeError):
    """PR beklenen durumda değil (ör. zaten merge edilmiş)."""


class MergeResult(BaseModel):
    """merge_pr ayrıntısı. `ForgePort.merge_pr` yalnızca `sha` döndürür; ayrıntı denetim içindir."""

    number: int
    sha: str
    actor: str
    method: str  # fast-forward | merge-commit | already-merged
    bypass: bool = False
    bypass_reason: str | None = None
    checks: list[CheckRun] = Field(default_factory=list)


def validate_branch(name: str) -> str:
    """Dal adı: `git check-ref-format --branch` alt kümesi + seçenek enjeksiyonu koruması."""
    if not isinstance(name, str) or not name:
        raise ForgeValidationError("dal adı boş olamaz")
    if len(name) > _MAX_REF_LEN:
        raise ForgeValidationError("dal adı çok uzun")
    if not _REF_RE.match(name):
        raise ForgeValidationError(f"geçersiz dal adı: {name!r}")
    parts = name.split("/")
    for part in parts:
        if not part or part.startswith(".") or part.endswith(".lock"):
            raise ForgeValidationError(f"geçersiz dal adı: {name!r}")
    if ".." in name or name.endswith(".") or name.endswith("/") or name == "HEAD":
        raise ForgeValidationError(f"geçersiz dal adı: {name!r}")
    if name.startswith("refs/"):
        raise ForgeValidationError("dal adı kısa biçimde verilmeli (refs/ öneki olmadan)")
    return name


def is_sha(value: str) -> bool:
    return isinstance(value, str) and bool(_SHA_RE.match(value))


def validate_ref(ref: str) -> str:
    """Okuma işlemleri için ref: tam commit sha'sı, dal adı veya etiket adı."""
    if is_sha(ref):
        return ref
    return validate_branch(ref)


def validate_path(path: str) -> str:
    """Depo içi göreli POSIX yol; `..`, mutlak yol, `.git` bileşeni ve kontrol karakteri yok."""
    if not isinstance(path, str) or not path:
        raise ForgeValidationError("yol boş olamaz")
    if len(path) > _MAX_PATH_LEN:
        raise ForgeValidationError("yol çok uzun")
    if any(ord(c) < 0x20 or c == "\x7f" for c in path) or "\\" in path:
        raise ForgeValidationError(f"geçersiz yol: {path!r}")
    if path.startswith("/") or path.startswith("-"):
        raise ForgeValidationError(f"geçersiz yol: {path!r}")
    for part in path.split("/"):
        if part in ("", ".", "..") or part.lower() == ".git":
            raise ForgeValidationError(f"geçersiz yol: {path!r}")
    return path


def validate_prefix(prefix: str) -> str:
    """list_files öneki: boş, dizin (`e2e/`) veya yol başlangıcı (`e2e/pa`)."""
    if prefix == "":
        return prefix
    validate_path(prefix[:-1] if prefix.endswith("/") else prefix)
    return prefix


def validate_actor(actor: str) -> str:
    if not isinstance(actor, str) or not _ACTOR_RE.match(actor):
        raise ForgeValidationError(f"geçersiz aktör: {actor!r}")
    return actor


def validate_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ForgeValidationError("arama sorgusu boş olamaz")
    if len(query) > 256 or any(c in query for c in "\x00\n\r"):
        raise ForgeValidationError("geçersiz arama sorgusu")
    return query


def validate_files(files: Mapping[str, str]) -> dict[str, bytes]:
    if not files:
        raise ForgeValidationError("en az bir dosya gerekli")
    out: dict[str, bytes] = {}
    for path, content in files.items():
        validate_path(path)
        if not isinstance(content, str):
            raise ForgeValidationError(f"dosya içeriği metin olmalı: {path}")
        out[path] = content.encode("utf-8")
    return out


def validate_label(label: str) -> str:
    if not isinstance(label, str) or not label.strip() or len(label) > 50:
        raise ForgeValidationError(f"geçersiz etiket: {label!r}")
    if any(ord(c) < 0x20 for c in label):
        raise ForgeValidationError(f"geçersiz etiket: {label!r}")
    return label


def validate_message(message: str) -> str:
    if not isinstance(message, str) or not message.strip():
        raise ForgeValidationError("commit mesajı boş olamaz")
    if "\x00" in message:
        raise ForgeValidationError("commit mesajı NUL içeremez")
    return message


def validate_required_checks(names: Sequence[str]) -> tuple[str, ...]:
    """Zorunlu kontrol adları: en az bir ad, tekrarsız, sıra korunur.

    Boş küme kabul edilmez: yanlış yapılandırma "her merge kurala uygun" sonucunu sessizce
    üretmemelidir (denetim doğruluğu, anayasa VIII).
    """
    clean: list[str] = []
    for raw in names:
        name = raw.strip() if isinstance(raw, str) else raw
        if not isinstance(name, str) or not _CHECK_NAME_RE.match(name):
            raise ForgeValidationError(f"geçersiz kontrol adı: {raw!r}")
        if name not in clean:
            clean.append(name)
    if not clean:
        raise ForgeValidationError("en az bir zorunlu kontrol gerekli")
    return tuple(clean)


def parse_required_checks(value: str | None, default: Sequence[str]) -> tuple[str, ...]:
    """`TP_REQUIRED_CHECKS="a,b,c"` → ("a", "b", "c"); boş/eksikse `default`."""
    if value is None or not value.strip():
        return validate_required_checks(default)
    return validate_required_checks([p for p in value.split(",") if p.strip()])


class RequiredChecksVerdict(BaseModel):
    """Zorunlu kontrollerin değerlendirmesi. `passed` yalnızca HER ad başarılıysa True."""

    passed: bool
    required: list[str]
    states: dict[str, str]  # ad → success | failure | in_progress | yok ...

    def reason(self) -> str:
        return "; ".join(
            f"'{n}' durumu: {self.states[n]}" for n in self.required if self.states[n] != "success"
        )


def evaluate_required_checks(
    checks: Sequence[CheckRun], required: Sequence[str]
) -> RequiredChecksVerdict:
    """Her zorunlu ad için listedeki SON (en güncel) koşu değerlendirilir; tamamlanmış ve
    `success` değilse kural sağlanmamıştır. Listede olmayan ad → "yok"."""
    latest: dict[str, CheckRun] = {}
    for run in checks:
        latest[run.name] = run  # sonraki girdi daha günceldir (adaptörler sıralar)
    states: dict[str, str] = {}
    for name in required:
        run = latest.get(name)
        if run is None:
            states[name] = "yok"
        elif run.status != "completed":
            states[name] = run.status
        else:
            states[name] = run.conclusion or "failure"
    passed = all(states[n] == "success" for n in required)
    return RequiredChecksVerdict(passed=passed, required=list(required), states=states)


# Kontrol adları `platform.check_adi`'dandır (011 K-T1): web + TS `local-ci`, web + Java
# `local-ci-web-java` (GitHub karşılığı `web-java`), uygulama (Java + Appium; 009 §2.7)
# `local-ci-<platform>`. toolchain-worker /check her birini ayrı girdi olarak yazar.
APP_PLATFORMS: tuple[str, ...] = platformlar.UYGULAMA_PLATFORMLARI
APP_PLATFORM_CHECKS: tuple[str, ...] = tuple(
    platformlar.check_adi(p, platformlar.JAVA) for p in APP_PLATFORMS
)
LOCAL_WEB_JAVA_CHECK = platformlar.check_adi(platformlar.WEB, platformlar.JAVA)
# LocalForge düzeninde Java e2e kökü (toolchain TP_E2E_APP_ROOT varsayılanı).
LOCAL_APP_E2E_ROOT = f"{platformlar.E2E_APP_DIZINI}/"
# LocalForge düzeninde web test kökleri: TS (`e2e/`, kontrolü `local-ci`) ve web + Java
# (`e2e-java/`, toolchain TP_E2E_JAVA_ROOT varsayılanı; kontrolü `local-ci-web-java`).
LOCAL_WEB_E2E_ROOT = "e2e/"
LOCAL_WEB_JAVA_E2E_ROOT = f"{platformlar.E2E_JAVA_DIZINI}/"
LOCAL_WEB_E2E_ROOTS: tuple[str, ...] = (LOCAL_WEB_E2E_ROOT, LOCAL_WEB_JAVA_E2E_ROOT)
# Web yerine geçebilen (kendi kontrolü olan) test kökleri: yalnız bunları değiştiren PR web
# `local-ci`'ı (kaydedilmemişse) istemez.
_KENDI_KONTROLLU_KOKLER: tuple[str, ...] = (LOCAL_APP_E2E_ROOT, LOCAL_WEB_JAVA_E2E_ROOT)


# Test kökleri: bunların DIŞINDA bir değişiklik (uygulama kodu vb.) repodaki tüm tam hat
# dillerinin kontrolünü ister (K-T11).
_TEST_KOKLERI: tuple[str, ...] = (*LOCAL_WEB_E2E_ROOTS, LOCAL_APP_E2E_ROOT)


def yerel_repodaki_web_dilleri(
    list_files: Callable[[str, str], list[str]], ref: str
) -> tuple[str, ...]:
    """LocalForge düzeninde (`e2e/`, `e2e-java/` kökte) `ref`'te web testi olan tam hat dilleri
    (`platform.repodaki_web_dilleri`; CI ile aynı sayım). Okunamazsa `("ts",)`."""
    return platformlar.repodaki_web_dilleri(
        list_files, ref, e2e=LOCAL_WEB_E2E_ROOT, e2e_java=LOCAL_WEB_JAVA_E2E_ROOT
    )


def local_required_checks(
    configured: Sequence[str],
    checks: Sequence[CheckRun],
    changed_paths: Sequence[str],
    repodaki_web_dilleri: Sequence[str] = (platformlar.TS,),
) -> tuple[tuple[str, ...], str | None]:
    """LocalForge merge kapısı: platform/dil başına zorunlu kontroller + ek ihlal nedeni.

    - Yapılandırılmış liste (varsayılan `local-ci`) aynen zorunludur; web + TS PR'ı için davranış
      değişmez.
    - Bu head için KAYDEDİLMİŞ her `local-ci-<platform>` ve `local-ci-web-java` de zorunludur:
      kırmızı bir uygulama / Java kontrolü merge'i durdurur (yalnızca web + TS yeşili yetmez).
    - PR `e2e-java/` altını değiştiriyorsa `local-ci-web-java` zorunludur (011 K-T1: web + Java
      PR'ı Java derlenip koşmadan merge edilemez).
    - PR `e2e/` altını değiştiriyorsa `local-ci` zorunludur (yapılandırma düşürmüş olsa bile).
    - PR test köklerinin (`e2e/`, `e2e-java/`, `e2e-app/`) DIŞINDA bir yolu (uygulama kodu vb.)
      değiştiriyorsa `repodaki_web_dilleri`'nin her birinin kontrolü zorunludur (K-T11: `local-ci`
      + repoda Java web testi varsa `local-ci-web-java`); CI script'siz PR'da aynı dilleri koşar
      (`platform.degisen_web_dilleri`).
    - PR yalnızca kendi kontrolü olan kökleri (`e2e-app/`, `e2e-java/`) değiştiriyorsa web
      `local-ci` gerekmez (kaydedilmişse yine yeşil olmalı); yerine o köklerin kontrolü gelir.
    - Yarıda kalmış (`in_progress`) bir kayıt merge'i durdurur; kontrol yeniden koşturulur
      (aynı adın girdisi üzerine yazılır) ya da demo-admin bypass'ı kullanılır.
    - `e2e-app/` değişip hiç platform kontrolü yoksa ikinci değer ihlal nedenidir.
    """
    platform_names = set(APP_PLATFORM_CHECKS)
    kendi_kontrollu = platform_names | {LOCAL_WEB_JAVA_CHECK}
    recorded = [c.name for c in checks if c.name in kendi_kontrollu]
    touches_app = any(p.startswith(LOCAL_APP_E2E_ROOT) for p in changed_paths)
    touches_java = any(p.startswith(LOCAL_WEB_JAVA_E2E_ROOT) for p in changed_paths)
    touches_ts = any(p.startswith(LOCAL_WEB_E2E_ROOT) for p in changed_paths)
    own_only = bool(changed_paths) and all(
        p.startswith(_KENDI_KONTROLLU_KOKLER) for p in changed_paths
    )
    # Kayıtlı her kontrol yeşil olmalı (simetri): web local-ci yalnızca KAYDEDİLMEMİŞSE düşer.
    web_recorded = any(c.name == REQUIRED_CHECK for c in checks)
    yerine_gecen = bool(recorded) or touches_java
    required = [
        n
        for n in configured
        if not (own_only and yerine_gecen and n == REQUIRED_CHECK and not web_recorded)
    ]
    if touches_ts and REQUIRED_CHECK not in required:
        # Yapılandırma `local-ci`'ı düşürmüş olsa bile (ör. yalnızca platform kontrolü isteyen
        # `TP_REQUIRED_CHECKS`) web testini değiştiren PR web kontrolü olmadan merge edilemez.
        required.insert(0, REQUIRED_CHECK)
    if touches_java and LOCAL_WEB_JAVA_CHECK not in required:
        required.append(LOCAL_WEB_JAVA_CHECK)
    if any(not p.startswith(_TEST_KOKLERI) for p in changed_paths):
        # K-T11: uygulama kodu değişti → repodaki her tam hat dilinin kontrolü.
        if platformlar.TS in repodaki_web_dilleri and REQUIRED_CHECK not in required:
            required.insert(0, REQUIRED_CHECK)
        if platformlar.JAVA in repodaki_web_dilleri and LOCAL_WEB_JAVA_CHECK not in required:
            required.append(LOCAL_WEB_JAVA_CHECK)
    for name in recorded:
        if name not in required:
            required.append(name)
    reason = None
    if touches_app and not any(n in platform_names for n in required):
        reason = (
            f"{LOCAL_APP_E2E_ROOT} değişikliği için en az bir uygulama kontrolü gerekli "
            f"({' | '.join(APP_PLATFORM_CHECKS)})"
        )
    return validate_required_checks(required or list(configured)), reason


# GitHub forge kipi (009 §2.7, .github/CI.md "Uygulama iş akışları"): platform → iş akışı dosyası
# ve check (= job) adı. Platform `TP_PLATFORMS` ile etkinleştirilince job adı zorunlu kontrol
# listesine eklenir (GitHub ruleset'ine de `scripts/github-ruleset.sh --checks` ile eklenmelidir).
PLATFORMS_ENV = "TP_PLATFORMS"
GITHUB_PLATFORM_CHECKS: dict[str, str] = {
    "android": "mobil-android",
    "ios": "mobil-ios",
    "windows": "masaustu-windows",
}
GITHUB_PLATFORM_WORKFLOWS: dict[str, str] = {
    p: f"{ad}.yml" for p, ad in GITHUB_PLATFORM_CHECKS.items()
}


# Web + Java (Playwright for Java + TestNG; 011 §2.8): iş akışı `web-java.yml`, check (= job) adı
# `web-java`. Web + TS `ci.yml`'in `test-local`'ıdır (değişmez). K-T10: `web-java.yml` depoda
# olduğu sürece `web-java` HER ZAMAN zorunludur (iş akışı `changes` + no-op deseniyle ilgisiz PR'da
# hızla yeşil); `TP_WEB_DILLERI` yalnız Java üretimini ve kardeş koşuyu açar (java varsa iş akışı
# dosyası okunamasa da zorunlu). Ruleset: `scripts/github-ruleset.sh --checks`.
WEB_JAVA_CHECK = "web-java"
WEB_JAVA_WORKFLOW = f"{WEB_JAVA_CHECK}.yml"
WEB_JAVA_WORKFLOW_YOLU = f".github/workflows/{WEB_JAVA_WORKFLOW}"
WEB_DILLERI_ENV = "TP_WEB_DILLERI"
WEB_TAM_HAT_DILLERI: tuple[str, ...] = platformlar.TAM_HAT_DILLERI

# Zorunlu check yapılabilen platform iş akışları (`changes` + no-op deseni; .github/CI.md).
ZORUNLU_YAPILABILIR_PLATFORMLAR: tuple[str, ...] = ("android", "windows")


def etkin_platformlar(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """`TP_PLATFORMS="android,windows"` → ("android", "windows"); boş → (). `web` yok sayılır
    (her zaman etkin); bilinmeyen ad yanlış yapılandırmadır (`ForgeValidationError`)."""
    env = os.environ if env is None else env
    out: list[str] = []
    for parca in (env.get(PLATFORMS_ENV) or "").split(","):
        ad = parca.strip().lower()
        if not ad or ad == "web":
            continue
        if ad not in APP_PLATFORMS:
            raise ForgeValidationError(
                f"{PLATFORMS_ENV} yalnızca {', '.join(APP_PLATFORMS)} içerebilir: {parca!r}"
            )
        if ad not in ZORUNLU_YAPILABILIR_PLATFORMLAR:
            # mobil-ios.yml workflow düzeyinde `paths` süzgeçlidir ve push tetiği yoktur: ilgisiz
            # PR'da check hiç oluşmaz → zorunlu yapılırsa her PR süresiz bekler (.github/CI.md).
            raise ForgeValidationError(
                f"{PLATFORMS_ENV}={ad}: bu platformun iş akışı zorunlu check olamaz (no-op deseni "
                "yok); önce iş akışını `changes` + no-op desenine çevirin"
            )
        if ad not in out:
            out.append(ad)
    return tuple(out)


def etkin_web_dilleri(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """`TP_WEB_DILLERI="ts,java"` → ("ts", "java"); boş → ("ts",) (bugünkü davranış). `ts` her
    zaman etkindir. Yalnızca tam hat dilleri (`ts` | `java`) yazılabilir: doğrulanmamış diller
    (csharp | python) PR'a ve CI'a girmez (011 K3) → `ForgeValidationError`."""
    env = os.environ if env is None else env
    out = ["ts"]
    for parca in (env.get(WEB_DILLERI_ENV) or "").split(","):
        ad = parca.strip().lower()
        if not ad:
            continue
        if ad not in WEB_TAM_HAT_DILLERI:
            raise ForgeValidationError(
                f"{WEB_DILLERI_ENV} yalnızca {', '.join(WEB_TAM_HAT_DILLERI)} içerebilir: {parca!r}"
            )
        if ad not in out:
            out.append(ad)
    return tuple(out)


def github_required_checks(
    configured: Sequence[str],
    platforms: Sequence[str],
    web_dilleri: Sequence[str] = (),
    *,
    web_java_is_akisi: bool = False,
) -> tuple[str, ...]:
    """GitHub zorunlu kontrolleri: yapılandırılmış liste + etkin platformların job adları +
    `web-java` (K-T10: `web-java.yml` depodaysa — `web_java_is_akisi` — ya da web dillerinde
    `java` etkinse)."""
    web_java = web_java_is_akisi or platformlar.JAVA in web_dilleri
    return validate_required_checks(
        [
            *configured,
            *(GITHUB_PLATFORM_CHECKS[p] for p in platforms),
            *((WEB_JAVA_CHECK,) if web_java else ()),
        ]
    )


def get_forge(env: Mapping[str, str] | None = None) -> ForgePort:
    """`TP_FORGE`'a göre adaptör kurar (varsayılan: local)."""
    env = os.environ if env is None else env
    kind = (env.get("TP_FORGE") or "local").strip().lower()
    if kind == "local":
        from tp_core.integrations.forge_local import LocalForge

        return LocalForge.from_env(env)
    if kind == "github":
        from tp_core.integrations.forge_github import GitHubForge

        return GitHubForge.from_env(env)
    raise ForgeValidationError(f"bilinmeyen TP_FORGE: {kind!r} (local | github)")
