"""toolchain-worker HTTP API'si (:8100, core-net + runner-net) — MIMARI-SOZLESME §2.

**Kimlik doğrulaması:** `/health` dışındaki her uç `Authorization: Bearer TP_TOOLCHAIN_TOKEN`
ister (belirteç yalnızca core-api/core-worker'da; test-runner'da yok — toolchain_common/auth.py).
runner-net'teki test-runner commit kodunu koşturur; belirteç olmadan `/check`'i çağıramaz.

Uçlar eşzamanlıdır (senkron) ve sınırlıdır; her alt süreç kendi süre sınırıyla koşar
(`TP_*_TIMEOUT_S`). `/check` test-runner'ı bekler: istemci zaman aşımı en az
`TP_RUN_TIMEOUT_S + TP_RUN_QUEUE_WAIT_S` + statik adımlar (~25 dk) olmalıdır.
toolchain-worker test kodu çalıştırmaz; testler yalnızca test-runner'da koşar.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Annotated, Any, Literal

import uvicorn
from fastapi import Depends, HTTPException
from pydantic import (
    AfterValidator,
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from toolchain_common import (
    appsha,
    aria,
    check_artifacts,
    check_checks_volume,
    check_node,
    check_playwright,
    create_app,
    gitforge,
    proc,
    repos,
    trace,
)
from toolchain_common.api import install_error_handlers
from toolchain_common.artifacts import release_keep
from toolchain_common.auth import check_auth, require_token
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
from worker import affected
from worker import check as checks
from worker import java as javayol
from worker.astguard import AstGuardError, run_ast_guard

app = create_app(
    "toolchain-worker",
    {
        "node": check_node,
        "playwright": check_playwright,
        "artifacts": check_artifacts,
        "checks_volume": check_checks_volume,
        "auth": check_auth,
    },
)
install_error_handlers(app)

Ref = Annotated[str, AfterValidator(validate_ref)]
# `/health` dışındaki her uç (toolchain_common/auth.py).
AUTH = [Depends(require_token)]
# Dil boyutu (009 §2.1): `lang` (ts | java) ya da `platform` (web | android | ios | windows).
# İkisi de verilmezse `ts` — mevcut Playwright/TypeScript yolu, davranışı değişmez.
Lang = Literal["ts", "java"]
Platform = Literal["web", "android", "ios", "windows"]


class LangMixin(BaseModel):
    lang: Lang | None = None
    platform: Platform | None = None

    @model_validator(mode="after")
    def _lang_uyumu(self) -> LangMixin:
        javayol.resolve_lang(self.lang, self.platform)
        return self

    @property
    def dil(self) -> str:
        return javayol.resolve_lang(self.lang, self.platform)


def _resolve(cfg: Settings, ref: str, prefer: Path | None = None) -> repos.Located:
    """Yerel forge ya da (GitHub modunda) aynadan; eksik commit uzak depodan çekilir."""
    try:
        return repos.locate(cfg, ref, fetch=True, prefer=prefer)
    except gitforge.CommitNotFound as exc:
        raise HTTPException(404, f"Commit forge'da bulunamadı: {ref}") from exc
    except gitforge.ForgeError as exc:
        raise HTTPException(503, f"Forge okunamadı: {exc}") from exc


# ------------------------------------------------------------------------------- /symbols

_SYMBOL_CACHE: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()
_SYMBOL_CACHE_LOCK = threading.Lock()
_SYMBOL_CACHE_MAX = 32


class SymbolsBody(LangMixin):
    model_config = ConfigDict(extra="forbid")
    sha: Ref


def extract_symbols(
    cfg: Settings, full_sha: str, repo: Path | None = None, lang: str = "ts"
) -> dict[str, Any]:
    """Commit'in e2e/pages (ts) ya da e2e-app (java) ağacından sembol tablosu.

    Commit değişmez → (depo, sha, dil) anahtarıyla önbellekli. Java tablosu `java-araclar
    symbols` ile TS `tp-symbols` şemasındadır (009 §2.5).
    """
    repo = repo or cfg.forge_path
    key = (str(repo), full_sha, lang)
    with _SYMBOL_CACHE_LOCK:
        if key in _SYMBOL_CACHE:
            _SYMBOL_CACHE.move_to_end(key)
            return _SYMBOL_CACHE[key]
    if lang == "java":
        with gitforge.checkout(repo, full_sha, cfg.e2e_app_root, cfg.git_timeout_s) as root:
            res = javayol.run_symbols(cfg, root)
    else:
        with gitforge.checkout(repo, full_sha, cfg.e2e_root, cfg.git_timeout_s) as e2e:
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
    if lang != "ts":
        table["lang"] = lang
    with _SYMBOL_CACHE_LOCK:
        _SYMBOL_CACHE[key] = table
        while len(_SYMBOL_CACHE) > _SYMBOL_CACHE_MAX:
            _SYMBOL_CACHE.popitem(last=False)
    return table


@app.post("/symbols", dependencies=AUTH)
def symbols(body: SymbolsBody) -> dict[str, Any]:
    cfg = settings()
    loc = _resolve(cfg, body.sha)
    try:
        return {**extract_symbols(cfg, loc.sha, loc.repo, body.dil), "kaynak": loc.kaynak}
    except gitforge.ForgeError as exc:
        raise HTTPException(503, f"Forge okunamadı: {exc}") from exc


# ----------------------------------------------------------------------------- /ast-guard


class AstGuardBody(LangMixin):
    model_config = ConfigDict(extra="forbid")
    base_sha: Ref
    head_sha: Ref
    # Varsayılan en sıkı mod: locator onarımı (TEKNIK-TASARIM §8.7).
    mode: Literal["repair", "pr"] = "repair"


@app.post("/ast-guard", dependencies=AUTH)
def ast_guard(body: AstGuardBody) -> dict[str, Any]:
    cfg = settings()
    head_loc = _resolve(cfg, body.head_sha)
    base_loc = _resolve(cfg, body.base_sha, prefer=head_loc.repo)
    head, base = head_loc.sha, base_loc.sha
    if base_loc.repo != head_loc.repo:
        raise HTTPException(
            422, "base ve head aynı depoda değil (yerel forge / GitHub aynası); karşılaştırılamaz."
        )
    try:
        if body.dil == "java":
            with gitforge.checkout(
                head_loc.repo, head, cfg.e2e_app_root, cfg.git_timeout_s
            ) as root:
                report = javayol.guard_report(cfg, head_loc.repo, base, head, body.mode, root)
        else:
            report = run_ast_guard(cfg, base, head, body.mode, head_loc.repo)
    except (AstGuardError, javayol.JavaAracError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except gitforge.ForgeError as exc:
        raise HTTPException(503, f"Forge okunamadı: {exc}") from exc
    return {
        "ok": bool(report.get("ok")),
        "violations": report.get("violations", []),
        "base_sha": base,
        "head_sha": head,
        "mode": body.mode,
        "report": report,
    }


# --------------------------------------------------------------------------------- /check


class CheckBody(LangMixin):
    model_config = ConfigDict(extra="forbid")

    sha: Ref
    # `lang`/`platform` (LangMixin) alanları test_files'tan önce doğrulanır: Java'da test dosyası
    # e2e-app köküne göre `src/test/java/**/<Ad>Test.java`, TS'de `tests/**.spec.ts`.
    test_files: list[str] = Field(default_factory=list)
    repeat_each: int = Field(3, ge=1, le=10)
    retries: int = Field(0, ge=0, le=3)
    env: dict[str, str] = Field(default_factory=dict)
    break_campaign: bool = Field(False, validation_alias=AliasChoices("break_campaign", "break"))
    grep: Annotated[str | None, AfterValidator(validate_grep)] = None
    base_sha: Annotated[str | None, AfterValidator(lambda v: v and validate_ref(v))] = None
    ast_guard_mode: Literal["pr", "repair"] = "pr"
    run_id: Annotated[str | None, AfterValidator(lambda v: v and validate_run_id(v))] = None
    # `local-ci` kaydı (checks/<sha>.json): None = yalnızca tam kapsamlı kontrol (worker/check.py).
    # Kapsamlı (test_files/grep) ya da kırılmalı kontrol ASLA kayıt olamaz: true verilemez.
    record_check: bool | None = None
    # Koşu dizini temizlikte silinmez (kanıt).
    keep: bool = False
    # Etkilenen testler (Faz 4 onarımı): e2e köküne göre değişen kaynaklar (pages/…/locators.ts)
    # ya da "@diff" (base_sha..sha). Kapsamlıdır: asla local-ci kaydı olmaz.
    affected_by: Annotated[list[str], Field(max_length=50)] = Field(default_factory=list)

    @field_validator("test_files")
    @classmethod
    def _test_files(cls, v: list[str], info: ValidationInfo) -> list[str]:
        try:
            lang = javayol.resolve_lang(info.data.get("lang"), info.data.get("platform"))
        except ValueError:
            lang = "ts"  # uyumsuzluk model doğrulamasında ayrıca bildirilir
        if lang != "java":
            return validate_test_files(v)
        if len(v) > 200:
            raise ValueError("en fazla 200 test dosyası verilebilir")
        return list(dict.fromkeys(javayol.validate_java_test_file(x) for x in v))

    @field_validator("affected_by")
    @classmethod
    def _affected(cls, v: list[str]) -> list[str]:
        return list(
            dict.fromkeys(
                x if x == checks.DIFF_MARKER else affected.validate_source_path(x) for x in v
            )
        )

    @model_validator(mode="after")
    def _record(self) -> CheckBody:
        if self.dil == "java" and (self.grep or self.affected_by):
            raise ValueError(
                "Java yolunda grep ve affected_by henüz desteklenmiyor (test_files kullanın)"
            )
        if self.affected_by and (self.test_files or self.grep):
            raise ValueError("affected_by, test_files ve grep ile birlikte verilemez")
        if self.record_check and self.affected_by:
            raise ValueError(
                "etkilenen testlerle kapsamlı kontrol local-ci kaydı olamaz "
                "(record_check=true yalnızca tam kapsamlı kontrolde)"
            )
        if self.record_check and (self.break_campaign or self.env.get("BREAK_CAMPAIGN") == "1"):
            raise ValueError(
                "kırarak doğrulama local-ci kaydı olamaz (record_check=true verilemez)"
            )
        if self.record_check and (self.test_files or self.grep):
            # Merge kapısı tüm testlerin sonucunu ister; kapsamlı yeşil bir head'i geçirmemeli.
            raise ValueError(
                "kapsamlı kontrol (test_files/grep) local-ci kaydı olamaz "
                "(record_check=true yalnızca tam kapsamlı kontrolde)"
            )
        return self

    @field_validator("env")
    @classmethod
    def _env(cls, v: dict[str, str]) -> dict[str, str]:
        if set(v) - {"BREAK_CAMPAIGN"}:
            raise ValueError("yalnızca BREAK_CAMPAIGN ortam değişkeni verilebilir")
        if v.get("BREAK_CAMPAIGN", "") not in ("", "0", "1"):
            raise ValueError("BREAK_CAMPAIGN yalnızca '1', '0' veya boş olabilir")
        return v


@app.post("/check", dependencies=AUTH)
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
        record_check=body.record_check,
        keep=body.keep,
        affected_by=body.affected_by,
        lang=body.dil,
        platform=body.platform,
    )
    try:
        return checks.execute(cfg, req)
    except gitforge.CommitNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except checks.ChecksNotIsolated as exc:
        raise HTTPException(503, str(exc)) from exc
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
    # Onarım adayı (ör. "cart-add"): kapsamda tek elemana çözülmeli ve o eleman rol + adı taşımalı.
    candidate_test_id: Annotated[
        str | None, AfterValidator(lambda v: validate_test_id(v, "candidate_test_id"))
    ] = Field(None, validation_alias=AliasChoices("candidate_test_id", "test_id"))
    # Referans aria snapshot'ı (TP_ARTIFACTS_PATH'e göre, runs/ altında: error-context.md ya da
    # .yml): rol + ad orada da var mı (§8.7 doğrulaması; ör. son yeşil/ilk kırmızı koşunun kanıtı).
    aria_snapshot_rel: Annotated[str | None, AfterValidator(lambda v: v and _rel(v))] = None


def _rel(value: str) -> str:
    if len(value) > 500 or any(ord(c) < 32 for c in value):
        raise ValueError("geçersiz kanıt yolu")
    return value


LOGIN_PATH = "/giris"


def run_probe(cfg: Settings, body: LocatorProbeBody) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "base_url": cfg.probe_base_url,
        "url_path": body.url_path,
        "role": body.role,
        "name": body.name,
        "scope_test_id": body.scope_test_id,
        "candidate_test_id": body.candidate_test_id,
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


@app.post("/locator-probe", dependencies=AUTH)
def locator_probe(body: LocatorProbeBody) -> dict[str, Any]:
    """Demo uygulamasında getByRole(role, {name}) eşleşmelerini sayar, data-testid'yi okur.

    Yoklama compose'da ÇALIŞAN demo uygulamasına (DEMO_WEB_URL) yapılır, `sha`'nın ağacına değil.
    Yanıt bunu `olculen="calisan_uygulama"` ile, sha uyumunu `sha_eslesmesi` ile açıkça bildirir:
    çalışan uygulamanın commit'i (`TP_APP_BUILD_SHA_FILE` > `DEMO_APP_BUILD_SHA`) biliniyorsa
    uygulama ağaçları (`web`, `api`) istenen sha'nınkiyle karşılaştırılır; farklıysa öneri
    üretilmez (`oneri_uretilebilir=false`), bilinmiyorsa `dogrulanamadi` + `uyari` döner.
    Faz 4 onarım kaydı bu alanları olduğu gibi saklamalıdır.
    """
    cfg = settings()
    loc = _resolve(cfg, body.sha)
    full = loc.sha
    uyum = appsha.match(cfg, loc)
    app_sha, sha_eslesmesi, uyari = uyum.uygulama_sha, uyum.eslesme, uyum.uyari
    aria_ref = None
    if body.aria_snapshot_rel:
        # Yoklamadan önce: geçersiz yol tarayıcı açılmadan 422 olur.
        try:
            text = aria.load_snapshot(cfg.artifacts_path, body.aria_snapshot_rel)
        except aria.AriaSourceError as exc:
            raise HTTPException(422, f"Aria snapshot okunamadı: {exc}") from exc
        aria_ref = {
            "kaynak_rel": body.aria_snapshot_rel,
            **aria.match(text, body.role, body.name),
        }
    out = run_probe(cfg, body)
    matches = int(out.get("matches") or 0)
    raw = out.get("test_id")
    test_id = raw if isinstance(raw, str) and TESTID_RE.match(raw) and len(raw) <= 200 else None
    test_ids = [t if isinstance(t, str) else None for t in out.get("test_ids") or []]
    cand_raw = out.get("candidate") if isinstance(out.get("candidate"), dict) else None
    aday = None
    if body.candidate_test_id:
        c_matches = int((cand_raw or {}).get("matches") or 0)
        c_role = int((cand_raw or {}).get("role_name_matches") or 0)
        aday = {
            "test_id": body.candidate_test_id,
            "matches": c_matches,
            "rol_ad_eslesen": c_role,
            # Aday kapsamda tek elemana çözülüyor ve o eleman aynı rol + adı taşıyor.
            "gecerli": c_matches == 1 and c_role == 1,
            "yoklanan_ile_ayni": test_id is not None and test_id == body.candidate_test_id,
        }
    aria_text = out.get("aria_snapshot")
    # Öneriyi engelleyen deterministik nedenler (Türkçe; boş = engel yok).
    engeller: list[str] = []
    if matches == 0:
        engeller.append("rol + ad çalışan uygulamada bulunamadı")
    elif matches > 1:
        engeller.append(f"rol + ad {matches} elemana eşleşti (kapsam gerekli)")
    elif test_id is None:
        engeller.append("eşleşen elemanda geçerli data-testid yok")
    if sha_eslesmesi == "farkli":
        engeller.append("çalışan uygulama istenen commit'le eşleşmiyor")
    if aria_ref is not None and not aria_ref["var"]:
        engeller.append("rol + ad referans aria snapshot'ında yok")
    if aday is not None and not aday["gecerli"]:
        engeller.append("aday testId kapsamda tek ve aynı rol + adlı elemana çözülmüyor")
    return {
        "matches": matches,
        "test_id": test_id if matches == 1 else None,
        "test_ids": [t[:200] if t else None for t in test_ids],
        "test_id_raw": raw[:200] if isinstance(raw, str) and raw != test_id else None,
        "scope_test_id": body.scope_test_id,
        "scope_matches": out.get("scope_matches"),
        "page_matches": out.get("page_matches"),
        "aday": aday,
        "aria_dogrulama": aria_ref,
        # Çalışan uygulamadaki kapsayıcının (yoksa sayfanın) aria snapshot'ı: güvenilmeyen veri,
        # kanıt olarak saklanabilir (rol + ad; testId içermez).
        "aria_snapshot": aria_text[:8000] if isinstance(aria_text, str) else None,
        "aria_snapshot_scope": out.get("aria_snapshot_scope"),
        "sha": full,
        "app_url": cfg.probe_base_url,
        "url_path": body.url_path,
        "final_path": out.get("final_path"),
        "http_status": out.get("http_status"),
        # §8.7: yalnızca tek eşleşme ve geçerli testId öneri üretir; 0 / çoklu → insana.
        # Referans aria snapshot'ı ya da aday verildiyse onların doğrulaması da gerekir.
        "oneri_uretilebilir": not engeller,
        "engeller": engeller,
        # Ölçüm çalışan uygulamada yapılır; istenen sha ile ilişkisi aşağıda (MIMARI-SOZLESME §2).
        "olculen": "calisan_uygulama",
        "uygulama_sha": app_sha,
        "sha_eslesmesi": sha_eslesmesi,
        "uyari": uyari,
        "farkli_yollar": uyum.farkli_yollar,
    }


# ---------------------------------------------------------------------------- /aria-match


class AriaMatchBody(BaseModel):
    """Aria snapshot'ında rol + ad araması (§8.6 kural 3, §8.7 doğrulama). Model yok."""

    model_config = ConfigDict(extra="forbid")

    role: Annotated[str, AfterValidator(validate_role)]
    name: Annotated[str, AfterValidator(validate_name)]
    aria_snapshot_rel: Annotated[str | None, AfterValidator(lambda v: v and _rel(v))] = None
    aria_snapshot: Annotated[str | None, Field(max_length=200_000)] = None
    scope_role: Annotated[str | None, AfterValidator(lambda v: v and validate_role(v))] = None
    scope_name: Annotated[str | None, AfterValidator(lambda v: v and validate_name(v))] = None

    @model_validator(mode="after")
    def _one_source(self) -> AriaMatchBody:
        if (self.aria_snapshot_rel is None) == (self.aria_snapshot is None):
            raise ValueError("aria_snapshot_rel ya da aria_snapshot'tan yalnızca biri verilmeli")
        return self


@app.post("/aria-match", dependencies=AUTH)
def aria_match(body: AriaMatchBody) -> dict[str, Any]:
    cfg = settings()
    if body.aria_snapshot_rel is not None:
        try:
            text = aria.load_snapshot(cfg.artifacts_path, body.aria_snapshot_rel)
        except aria.AriaSourceError as exc:
            raise HTTPException(422, f"Aria snapshot okunamadı: {exc}") from exc
    else:
        text = body.aria_snapshot or ""
    return {
        "kaynak_rel": body.aria_snapshot_rel,
        **aria.match(
            text, body.role, body.name, scope_role=body.scope_role, scope_name=body.scope_name
        ),
    }


# ------------------------------------------------------------------------- /trace-summary


class TraceSummaryBody(BaseModel):
    """`trace.zip` özeti (§8.7 alternatif kaynak: DOM snapshot'ından testId). Model yok."""

    model_config = ConfigDict(extra="forbid")

    trace_rel: Annotated[str, AfterValidator(_rel)]
    role: Annotated[str | None, AfterValidator(lambda v: v and validate_role(v))] = None
    name: Annotated[str | None, AfterValidator(lambda v: v if v is None else validate_name(v))] = (
        None
    )
    scope_test_id: Annotated[
        str | None, AfterValidator(lambda v: validate_test_id(v, "scope_test_id"))
    ] = None


@app.post("/trace-summary", dependencies=AUTH)
def trace_summary(body: TraceSummaryBody) -> dict[str, Any]:
    cfg = settings()
    try:
        return trace.load_and_summarize(
            cfg.artifacts_path,
            body.trace_rel,
            role=body.role,
            name=body.name,
            scope_test_id=body.scope_test_id,
        )
    except trace.TraceError as exc:
        raise HTTPException(422, f"Trace okunamadı: {exc}") from exc


# ------------------------------------------------------------------------ /affected-tests


class AffectedBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha: Ref
    changed: Annotated[list[str], Field(max_length=50)] = Field(default_factory=list)
    base_sha: Annotated[str | None, AfterValidator(lambda v: v and validate_ref(v))] = None

    @field_validator("changed")
    @classmethod
    def _changed(cls, v: list[str]) -> list[str]:
        return [affected.validate_source_path(x) for x in v]

    @model_validator(mode="after")
    def _source(self) -> AffectedBody:
        if not self.changed and not self.base_sha:
            raise ValueError("changed ya da base_sha verilmeli")
        return self


@app.post("/affected-tests", dependencies=AUTH)
def affected_tests(body: AffectedBody) -> dict[str, Any]:
    """Değişen e2e kaynaklarından etkilenen spec dosyaları (yalnızca önizleme; koşu yok).

    `/check {affected_by}` aynı hesabı koşudan hemen önce, aynı commit'te yeniden yapar.
    """
    cfg = settings()
    head = _resolve(cfg, body.sha)
    changed = list(body.changed)
    try:
        if body.base_sha:
            base = _resolve(cfg, body.base_sha, prefer=head.repo)
            if base.repo != head.repo:
                raise HTTPException(422, "base ve head aynı depoda değil; karşılaştırılamaz.")
            changed += affected.changed_files(
                head.repo, base.sha, head.sha, cfg.e2e_root, cfg.git_timeout_s
            )
        changed = list(dict.fromkeys(changed))
        with gitforge.checkout(head.repo, head.sha, cfg.e2e_root, cfg.git_timeout_s) as e2e:
            result = (
                affected.affected_tests(e2e, changed)
                if changed
                else {
                    "yontem": "import_grafi",
                    "kaynak": [],
                    "test_files": [],
                    "tam_kapsam": True,
                    "tam_kapsam_nedeni": "değişen e2e dosyası yok",
                    "dosya_sayisi": 0,
                }
            )
    except gitforge.ForgeError as exc:
        raise HTTPException(503, f"Forge okunamadı: {exc}") from exc
    return {"sha": head.sha, **result}


# ------------------------------------------------------------------------------ /runs/release


class ReleaseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_ids: Annotated[list[str], Field(min_length=1, max_length=100)]

    @field_validator("run_ids")
    @classmethod
    def _ids(cls, v: list[str]) -> list[str]:
        return [validate_run_id(r) for r in v]


@app.post("/runs/release", dependencies=AUTH)
def release_runs(body: ReleaseBody) -> dict[str, Any]:
    """Kanıt koşularının `.keep` işaretini kaldırır (sahibi script kapandı/başarısız oldu).

    Koşu dizini silinmez; test-runner'ın sıradaki temizliği onu `TP_RUNS_KEEP` sırasına göre
    eler. Bilinmeyen / zaten işaretsiz koşular hata değildir (idempotent).
    """
    cfg = settings()
    return {"released": [r for r in body.run_ids if release_keep(cfg.artifacts_path, r)]}


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8100)
