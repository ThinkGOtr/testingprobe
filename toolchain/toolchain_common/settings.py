"""Ortam değişkenleri (her çağrıda okunur; testler ortamı değiştirebilir)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    forge_path: Path
    artifacts_path: Path
    e2e_root: str
    e2e_deps: Path
    toolchain_home: Path
    node: str
    test_runner_url: str
    base_url: str
    demo_api_url: str
    demoapp_test_token: str
    probe_base_url: str
    probe_app_sha: str
    probe_user: str
    probe_password: str
    run_dealers: tuple[str, ...]
    git_timeout_s: float
    tsc_timeout_s: float
    eslint_timeout_s: float
    ast_guard_timeout_s: float
    symbols_timeout_s: float
    probe_timeout_s: float
    run_timeout_s: float
    health_timeout_s: float
    run_queue_wait_s: float
    check_queue_wait_s: float
    runs_keep: int
    # `.keep` işaretli (kanıt) koşuların saklama sınırı: yaş (gün) ve sayı; 0 = o sınır kapalı.
    runs_keep_evidence_days: int
    runs_keep_evidence_max: int
    # Koşular arası süreçler-arası kilit (flock): test-runner /run ve `tp-run-lock` (e2e-smoke).
    run_lock_path: Path
    # toolchain-worker uçları için paylaşılan taşıyıcı belirteç (yalnızca core-api/core-worker'da;
    # test-runner'da ASLA). Boş + require=0 → uçlar açık (uyarı); require=1 → 503.
    toolchain_token: str
    toolchain_require_token: bool
    # GitHub modu: forge'da olmayan sha'lar salt okunur uzaktan depodan aynaya çekilir.
    forge_remote_url: str
    forge_remote_token: str
    forge_mirror_path: Path
    fetch_timeout_s: float
    # Çalışan demo-app-web'in derlendiği commit (dosya > DEMO_APP_BUILD_SHA) ve uygulama yolları.
    app_build_sha_file: Path
    app_paths: tuple[str, ...]
    check_require_app_sha: bool
    # checks/ (merge kapısı) ayrı volume olmalı mı (test-runner bağlamaz; MIMARI-SOZLESME §2).
    checks_require_mount: bool
    # Merge kapısı dizini (`<sha>.json`): ayrı volume (`tp_checks`), yalnızca toolchain-worker rw,
    # core ro, test-runner HİÇ bağlamaz. Boş = `TP_ARTIFACTS_PATH/checks` (eski düzen).
    checks_path: Path | None
    allure_cli: Path
    allure_config: Path
    allure_timeout_s: float

    @property
    def ast_guard_cli(self) -> Path:
        return self.toolchain_home / "ast-guard" / "dist" / "src" / "cli.js"

    @property
    def symbols_cli(self) -> Path:
        return self.toolchain_home / "symbols" / "dist" / "src" / "cli.js"

    @property
    def probe_script(self) -> Path:
        return self.toolchain_home / "probe" / "locator-probe.mjs"

    @property
    def e2e_node_modules(self) -> Path:
        return self.e2e_deps / "node_modules"

    @property
    def checks_dir(self) -> Path:
        return self.checks_path or self.artifacts_path / "checks"


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "evet")


def settings() -> Settings:
    env = os.environ.get
    return Settings(
        forge_path=Path(env("TP_FORGE_PATH", "/forge/demo-app.git")),
        artifacts_path=Path(env("TP_ARTIFACTS_PATH", "/artifacts")),
        e2e_root=env("TP_E2E_ROOT", "e2e"),
        e2e_deps=Path(env("TP_E2E_DEPS", "/opt/e2e")),
        toolchain_home=Path(env("TOOLCHAIN_HOME", "/opt/toolchain")),
        node=env("TP_NODE", "node"),
        test_runner_url=env("TEST_RUNNER_URL", "http://test-runner:8200").rstrip("/"),
        base_url=env("BASE_URL", "http://demo-app-web:8080").rstrip("/"),
        demo_api_url=env("DEMO_API_URL", "http://demo-app-api:8000").rstrip("/"),
        demoapp_test_token=env("DEMOAPP_TEST_TOKEN", ""),
        probe_base_url=env("DEMO_WEB_URL", "http://demo-app-web:8080").rstrip("/"),
        # Çalışan demo uygulamasının derlendiği commit (biliniyorsa). Boşsa /locator-probe
        # ölçümün istenen sha'ya ait olduğunu doğrulayamaz ve bunu yanıtında açıkça belirtir.
        probe_app_sha=env("DEMO_APP_BUILD_SHA", "").strip(),
        # DEMO-VERISI.md: bayi1 / Demo123! (sentetik demo kullanıcısı; yoklama salt okunur gezinir).
        probe_user=env("TP_PROBE_USER", "bayi1"),
        probe_password=env("TP_PROBE_PASSWORD", "Demo123!"),
        run_dealers=tuple(
            d.strip() for d in env("TP_RUN_DEALERS", "bayi1,bayi2").split(",") if d.strip()
        ),
        git_timeout_s=_float("TP_GIT_TIMEOUT_S", 60),
        tsc_timeout_s=_float("TP_TSC_TIMEOUT_S", 180),
        eslint_timeout_s=_float("TP_ESLINT_TIMEOUT_S", 240),
        ast_guard_timeout_s=_float("TP_AST_GUARD_TIMEOUT_S", 60),
        symbols_timeout_s=_float("TP_SYMBOLS_TIMEOUT_S", 60),
        probe_timeout_s=_float("TP_PROBE_TIMEOUT_S", 60),
        run_timeout_s=_float("TP_RUN_TIMEOUT_S", 900),
        health_timeout_s=_float("TP_HEALTH_TIMEOUT_S", 5),
        run_queue_wait_s=_float("TP_RUN_QUEUE_WAIT_S", 600),
        check_queue_wait_s=_float("TP_CHECK_QUEUE_WAIT_S", 900),
        # Saklanacak son koşu dizini sayısı (`runs/<id>/`); 0 = temizlik kapalı. `.keep` işaretli
        # koşular (kanıt: kırarak doğrulama, triage) sayılmaz ve silinmez.
        runs_keep=max(0, int(_float("TP_RUNS_KEEP", 50))),
        # Kanıt koşuları (`.keep`) da sınırsız büyümez: bu kadar günden eski olanlar ve en yeni
        # TP_RUNS_KEEP_EVIDENCE_MAX dışındakiler silinir (0 = o sınır kapalı). Core, sahibi script
        # kapandığında işareti `POST /runs/release` ile daha erken kaldırabilir.
        runs_keep_evidence_days=max(0, int(_float("TP_RUNS_KEEP_EVIDENCE_DAYS", 30))),
        runs_keep_evidence_max=max(0, int(_float("TP_RUNS_KEEP_EVIDENCE_MAX", 200))),
        run_lock_path=Path(env("TP_RUN_LOCK_PATH", "/tmp/testingprobe-run.lock")),
        toolchain_token=env("TP_TOOLCHAIN_TOKEN", "").strip(),
        toolchain_require_token=_flag("TP_TOOLCHAIN_REQUIRE_TOKEN"),
        # GitHub modu (TP_FORGE=github): sha yerel forge'da yoksa bu uzaktan depodan (salt okuma
        # belirteci; yalnızca toolchain-worker) TP_FORGE_MIRROR_PATH aynasına çekilir. Boş = kapalı.
        forge_remote_url=env("TP_FORGE_REMOTE_URL", "").strip(),
        forge_remote_token=env("TP_FORGE_REMOTE_TOKEN", "").strip(),
        forge_mirror_path=Path(env("TP_FORGE_MIRROR_PATH", "/forge-mirror/demo-app.git")),
        fetch_timeout_s=_float("TP_FETCH_TIMEOUT_S", 120),
        # Çalışan demo-app-web'in derlendiği forge commit'i: önce bu dosya (forge-init/sync-web/
        # break/reset yazar; konteyner yeniden oluşturmadan güncellenir), yoksa DEMO_APP_BUILD_SHA.
        app_build_sha_file=Path(env("TP_APP_BUILD_SHA_FILE", "/forge/demo-app-web.sha")),
        app_paths=tuple(p.strip() for p in env("TP_APP_PATHS", "web,api").split(",") if p.strip()),
        # 1 → çalışan uygulamanın commit'i bilinmiyorsa /check başarılı sayılmaz.
        check_require_app_sha=_flag("TP_CHECK_REQUIRE_APP_SHA"),
        checks_require_mount=_flag("TP_CHECKS_REQUIRE_MOUNT"),
        checks_path=Path(env("TP_CHECKS_PATH")) if env("TP_CHECKS_PATH", "").strip() else None,
        allure_cli=Path(env("TP_ALLURE_CLI", "/opt/allure/node_modules/allure/cli.js")),
        allure_config=Path(env("TP_ALLURE_CONFIG", "/opt/allure/allurerc.mjs")),
        allure_timeout_s=_float("TP_ALLURE_TIMEOUT_S", 120),
    )
