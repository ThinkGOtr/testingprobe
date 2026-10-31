"""toolchain-worker HTTP API'si (:8100, core-net + runner-net) — MIMARI-SOZLESME §2.

Uçlar eşzamanlıdır (senkron) ve sınırlıdır; her alt süreç kendi süre sınırıyla koşar
(`TP_*_TIMEOUT_S`). `/check` test-runner'ı bekler: istemci zaman aşımı en az
`TP_RUN_TIMEOUT_S + TP_RUN_QUEUE_WAIT_S` + statik adımlar (~25 dk) olmalıdır.
toolchain-worker test kodu çalıştırmaz; testler yalnızca test-runner'da koşar.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from typing import Annotated, Any, Literal

import uvicorn
from fastapi import HTTPException
from pydantic import AfterValidator, AliasChoices, BaseModel, ConfigDict, Field, field_validator

from toolchain_common import (
    check_artifacts,
    check_node,
    check_playwright,
    create_app,
    gitforge,
    proc,
)
from toolchain_common.api import install_error_handlers
from toolchain_common.settings import Settings, settings
from toolchain_common.validation import (
    TESTID_RE,
    validate_grep,
    validate_name,
    validate_ref,
    validate_role,
    validate_run_id,
    validate_test_files,
    validate_test_id,
    validate_url_path,
)
from worker import check as checks
from worker.astguard import AstGuardError, run_ast_guard

app = create_app(
    "toolchain-worker",
    {"node": check_node, "playwright": check_playwright, "artifacts": check_artifacts},
)
install_error_handlers(app)

Ref = Annotated[str, AfterValidator(validate_ref)]


def _resolve(cfg: Settings, ref: str) -> str:
    try:
        return gitforge.resolve_commit(cfg.forge_path, ref, cfg.git_timeout_s)
    except gitforge.CommitNotFound as exc:
        raise HTTPException(404, f"Commit forge'da bulunamadı: {ref}") from exc
    except gitforge.ForgeError as exc:
        raise HTTPException(503, f"Forge okunamadı: {exc}") from exc


# ------------------------------------------------------------------------------- /symbols

_SYMBOL_CACHE: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
_SYMBOL_CACHE_LOCK = threading.Lock()
_SYMBOL_CACHE_MAX = 32


class SymbolsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha: Ref


def extract_symbols(cfg: Settings, full_sha: str) -> dict[str, Any]:
    """Commit'in e2e/pages ağacından sembol tablosu (commit değişmez → önbellekli)."""
    key = (str(cfg.forge_path), full_sha)
    with _SYMBOL_CACHE_LOCK:
        if key in _SYMBOL_CACHE:
            _SYMBOL_CACHE.move_to_end(key)
            return _SYMBOL_CACHE[key]
    with gitforge.checkout(cfg.forge_path, full_sha, cfg.e2e_root, cfg.git_timeout_s) as e2e:
        res = proc.run(
            [cfg.node, str(cfg.symbols_cli), "--root", str(e2e)],
            timeout_s=cfg.symbols_timeout_s,
            keep_full_stdout=True,
        )
    if res.timed_out:
        raise HTTPException(504, "Sembol çıkarımı süre sınırını aştı.")
    try:
        table = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"Sembol çıkarıcı çıktısı okunamadı: {res.stderr[:300]}") from exc
    if res.exit_code != 0 or "page_objects" not in table:
        raise HTTPException(
            422, f"Sembol tablosu çıkarılamadı: {table.get('error', res.stderr[:300])}"
        )
    table = {"sha": full_sha, **table}
    with _SYMBOL_CACHE_LOCK:
        _SYMBOL_CACHE[key] = table
        while len(_SYMBOL_CACHE) > _SYMBOL_CACHE_MAX:
            _SYMBOL_CACHE.popitem(last=False)
    return table


@app.post("/symbols")
def symbols(body: SymbolsBody) -> dict[str, Any]:
    cfg = settings()
    full = _resolve(cfg, body.sha)
    try:
        return extract_symbols(cfg, full)
    except gitforge.ForgeError as exc:
        raise HTTPException(503, f"Forge okunamadı: {exc}") from exc


# ----------------------------------------------------------------------------- /ast-guard


class AstGuardBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_sha: Ref
    head_sha: Ref
    # Varsayılan en sıkı mod: locator onarımı (TEKNIK-TASARIM §8.7).
    mode: Literal["repair", "pr"] = "repair"


@app.post("/ast-guard")
def ast_guard(body: AstGuardBody) -> dict[str, Any]:
    cfg = settings()
    base = _resolve(cfg, body.base_sha)
    head = _resolve(cfg, body.head_sha)
    try:
        report = run_ast_guard(cfg, base, head, body.mode)
    except AstGuardError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "ok": bool(report.get("ok")),
        "violations": report.get("violations", []),
        "base_sha": base,
        "head_sha": head,
        "mode": body.mode,
        "report": report,
    }


# --------------------------------------------------------------------------------- /check


class CheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha: Ref
    test_files: Annotated[list[str], AfterValidator(validate_test_files)] = Field(
        default_factory=list
    )
    repeat_each: int = Field(3, ge=1, le=10)
    retries: int = Field(0, ge=0, le=3)
    env: dict[str, str] = Field(default_factory=dict)
    break_campaign: bool = Field(False, validation_alias=AliasChoices("break_campaign", "break"))
    grep: Annotated[str | None, AfterValidator(validate_grep)] = None
    base_sha: Annotated[str | None, AfterValidator(lambda v: v and validate_ref(v))] = None
    ast_guard_mode: Literal["pr", "repair"] = "pr"
    run_id: Annotated[str | None, AfterValidator(lambda v: v and validate_run_id(v))] = None

    @field_validator("env")
    @classmethod
    def _env(cls, v: dict[str, str]) -> dict[str, str]:
        if set(v) - {"BREAK_CAMPAIGN"}:
            raise ValueError("yalnızca BREAK_CAMPAIGN ortam değişkeni verilebilir")
        if v.get("BREAK_CAMPAIGN", "") not in ("", "0", "1"):
            raise ValueError("BREAK_CAMPAIGN yalnızca '1', '0' veya boş olabilir")
        return v


@app.post("/check")
def check(body: CheckBody) -> dict[str, Any]:
    cfg = settings()
    req = checks.CheckRequest(
        sha=body.sha,
        test_files=body.test_files,
        repeat_each=body.repeat_each,
        retries=body.retries,
        break_campaign=body.break_campaign or body.env.get("BREAK_CAMPAIGN") == "1",
        grep=body.grep,
        base_sha=body.base_sha,
        ast_guard_mode=body.ast_guard_mode,
        run_id=body.run_id,
    )
    try:
        return checks.execute(cfg, req)
    except gitforge.CommitNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except checks.CheckBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except gitforge.ForgeError as exc:
        raise HTTPException(503, f"Forge okunamadı: {exc}") from exc


# -------------------------------------------------------------------------- /locator-probe


class LocatorProbeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    sha: Ref
    role: Annotated[str, AfterValidator(validate_role)]
    name: Annotated[str, AfterValidator(validate_name)]
    url_path: Annotated[str, AfterValidator(validate_url_path)]
    scope_test_id: Annotated[
        str | None, AfterValidator(lambda v: validate_test_id(v, "scope_test_id"))
    ] = Field(None, validation_alias=AliasChoices("scope_test_id", "within_test_id"))


LOGIN_PATH = "/giris"


def run_probe(cfg: Settings, body: LocatorProbeBody) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "base_url": cfg.probe_base_url,
        "url_path": body.url_path,
        "role": body.role,
        "name": body.name,
        "scope_test_id": body.scope_test_id,
        "nav_timeout_ms": 15_000,
        "wait_ms": 5_000,
    }
    if not body.url_path.startswith(LOGIN_PATH):
        payload["login"] = {"kullanici_adi": cfg.probe_user, "parola": cfg.probe_password}
    res = proc.run(
        [cfg.node, str(cfg.probe_script), json.dumps(payload)],
        timeout_s=cfg.probe_timeout_s,
    )
    if res.timed_out:
        raise HTTPException(504, "Locator yoklaması süre sınırını aştı.")
    try:
        out = json.loads(res.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise HTTPException(
            500, f"Locator yoklaması çıktısı okunamadı: {res.stderr[:300]}"
        ) from exc
    if not out.get("ok"):
        raise HTTPException(502, f"Locator yoklaması başarısız: {out.get('error', 'bilinmiyor')}")
    return out


ShaMatch = Literal["eslesiyor", "farkli", "dogrulanamadi"]


def _app_sha_match(cfg: Settings, requested: str) -> tuple[str | None, ShaMatch, str | None]:
    """Çalışan uygulamanın derleme sha'sını (DEMO_APP_BUILD_SHA) istenen sha ile kıyaslar."""
    if not cfg.probe_app_sha:
        return (
            None,
            "dogrulanamadi",
            "Ölçüm çalışan demo uygulamasında yapıldı; uygulamanın derlendiği commit bilinmiyor, "
            "sonuç istenen sha'ya ait olmayabilir.",
        )
    try:
        app_full = gitforge.resolve_commit(cfg.forge_path, cfg.probe_app_sha, cfg.git_timeout_s)
    except (gitforge.ForgeError, gitforge.CommitNotFound, ValueError):
        return (
            cfg.probe_app_sha[:64],
            "dogrulanamadi",
            "Çalışan uygulamanın derleme sha'sı forge'da bulunamadı; sonuç istenen sha'ya ait "
            "olmayabilir.",
        )
    if app_full == requested:
        return app_full, "eslesiyor", None
    return (
        app_full,
        "farkli",
        f"Çalışan uygulama {app_full[:12]} commit'inden derlenmiş, istenen sha {requested[:12]}; "
        "öneri üretilmedi.",
    )


@app.post("/locator-probe")
def locator_probe(body: LocatorProbeBody) -> dict[str, Any]:
    """Demo uygulamasında getByRole(role, {name}) eşleşmelerini sayar, data-testid'yi okur.

    Yoklama compose'da ÇALIŞAN demo uygulamasına (DEMO_WEB_URL) yapılır, `sha`'nın ağacına değil.
    Yanıt bunu `olculen="calisan_uygulama"` ile, sha uyumunu `sha_eslesmesi` ile açıkça bildirir:
    `DEMO_APP_BUILD_SHA` verilmişse istenen sha ile karşılaştırılır; farklıysa öneri üretilmez
    (`oneri_uretilebilir=false`), bilinmiyorsa `dogrulanamadi` + `uyari` döner. Faz 4 onarım
    kaydı bu alanları olduğu gibi saklamalıdır.
    """
    cfg = settings()
    full = _resolve(cfg, body.sha)
    app_sha, sha_eslesmesi, uyari = _app_sha_match(cfg, full)
    out = run_probe(cfg, body)
    matches = int(out.get("matches") or 0)
    raw = out.get("test_id")
    test_id = raw if isinstance(raw, str) and TESTID_RE.match(raw) and len(raw) <= 200 else None
    test_ids = [t if isinstance(t, str) else None for t in out.get("test_ids") or []]
    return {
        "matches": matches,
        "test_id": test_id if matches == 1 else None,
        "test_ids": [t[:200] if t else None for t in test_ids],
        "test_id_raw": raw[:200] if isinstance(raw, str) and raw != test_id else None,
        "scope_test_id": body.scope_test_id,
        "scope_matches": out.get("scope_matches"),
        "sha": full,
        "app_url": cfg.probe_base_url,
        "url_path": body.url_path,
        "final_path": out.get("final_path"),
        "http_status": out.get("http_status"),
        # §8.7: yalnızca tek eşleşme ve geçerli testId öneri üretir; 0 / çoklu → insana.
        "oneri_uretilebilir": matches == 1 and test_id is not None and sha_eslesmesi != "farkli",
        # Ölçüm çalışan uygulamada yapılır; istenen sha ile ilişkisi aşağıda (MIMARI-SOZLESME §2).
        "olculen": "calisan_uygulama",
        "uygulama_sha": app_sha,
        "sha_eslesmesi": sha_eslesmesi,
        "uyari": uyari,
    }


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8100)
