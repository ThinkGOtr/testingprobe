"""test-runner kontrol API'si (:8200, yalnızca runner-net) — MIMARI-SOZLESME §2.

`POST /run` eşzamanlıdır (senkron) ve sınırlıdır: koşu `TP_RUN_TIMEOUT_S` (900 sn) içinde biter
ya da süreç grubu öldürülür; aynı anda tek koşu yürür, sıradaki istek en çok
`TP_RUN_QUEUE_WAIT_S` (600 sn) bekler, sonra 409 alır.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import uvicorn
from fastapi import HTTPException
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from runner import run as runner
from toolchain_common import (
    check_artifacts,
    check_checks_hidden,
    check_playwright,
    create_app,
    gitforge,
)
from toolchain_common.api import install_error_handlers
from toolchain_common.settings import settings
from toolchain_common.validation import (
    resolve_fault,
    validate_fault,
    validate_grep,
    validate_ref,
    validate_run_id,
    validate_test_files,
)
from worker.java import validate_java_test_file

ALLOWED_ENV = {"BREAK_CAMPAIGN", "TP_FAULT"}

app = create_app(
    "test-runner",
    {
        "playwright": check_playwright,
        "artifacts": check_artifacts,
        "checks_hidden": check_checks_hidden,
    },
)
install_error_handlers(app)


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Dil (009 §2.1): verilmezse "ts" (Playwright; eski gövde aynen geçer). "java" = e2e-app
    # (Appium + TestNG) ve `platform` zorunlu; test_files e2e-app köküne göre
    # `src/test/java/**/<Ad>Test.java`. Alanlar test_files'tan ÖNCE tanımlıdır (doğrulama sırası).
    lang: Literal["ts", "java"] = "ts"
    platform: Literal["android", "ios", "windows"] | None = None
    sha: Annotated[str, AfterValidator(validate_ref)]
    run_id: Annotated[str, AfterValidator(validate_run_id)]
    grep: Annotated[str | None, AfterValidator(validate_grep)] = None
    repeat_each: int = Field(1, ge=1, le=10)
    retries: int = Field(0, ge=0, le=3)
    # Sözleşme: env.BREAK_CAMPAIGN="1"; `break_campaign: true` eş anlamlıdır.
    env: dict[str, str] = Field(default_factory=dict)
    break_campaign: bool = False
    # Ekilmiş hata (012 §4.6): demo API kataloğundaki kod; env.TP_FAULT eş anlamlıdır. Test
    # sürecine TP_FAULT olarak geçer; BREAK_CAMPAIGN ile birlikteyse fixture TP_FAULT'u uygular.
    fault: Annotated[str | None, AfterValidator(validate_fault)] = None
    test_files: list[str] = Field(default_factory=list)
    workers: int | None = Field(None, ge=1, le=2)
    # Kanıt olarak saklanacak koşu (kırarak doğrulama, triage): temizlikte silinmez (`.keep`).
    keep: bool = False

    @field_validator("test_files")
    @classmethod
    def _test_files(cls, v: list[str], info: ValidationInfo) -> list[str]:
        if info.data.get("lang") != "java":
            return validate_test_files(v)
        if len(v) > 200:
            raise ValueError("en fazla 200 test dosyası verilebilir")
        return list(dict.fromkeys(validate_java_test_file(x) for x in v))

    @model_validator(mode="after")
    def _lang(self) -> RunBody:
        if self.lang == "java":
            if self.platform is None:
                raise ValueError("lang=java platform ister (android | ios | windows)")
            if self.grep:
                raise ValueError("Java koşusunda grep desteklenmiyor (test_files kullanın)")
            if self.workers is not None:
                raise ValueError("Java koşusu tek cihazda tek iş parçacığıdır (workers verilemez)")
        elif self.platform is not None:
            raise ValueError("platform yalnızca lang=java ile verilir (web: lang=ts)")
        self.fault = resolve_fault(self.fault, self.env)
        return self

    @field_validator("env")
    @classmethod
    def _env(cls, v: dict[str, str]) -> dict[str, str]:
        extra = set(v) - ALLOWED_ENV
        if extra:
            raise ValueError(
                f"izin verilmeyen ortam değişkeni: {sorted(extra)} "
                f"(yalnızca {', '.join(sorted(ALLOWED_ENV))})"
            )
        if v.get("BREAK_CAMPAIGN", "") not in ("", "0", "1"):
            raise ValueError("BREAK_CAMPAIGN yalnızca '1', '0' veya boş olabilir")
        validate_fault(v.get("TP_FAULT"))
        return v

    def to_request(self) -> runner.RunRequest:
        return runner.RunRequest(
            sha=self.sha,
            run_id=self.run_id,
            grep=self.grep,
            repeat_each=self.repeat_each,
            retries=self.retries,
            break_campaign=self.break_campaign or self.env.get("BREAK_CAMPAIGN") == "1",
            fault=self.fault,
            test_files=self.test_files,
            workers=self.workers,
            keep=self.keep,
            lang=self.lang,
            platform=self.platform,
        )


@app.post("/run")
def run_tests(body: RunBody) -> dict[str, Any]:
    try:
        return runner.execute(settings(), body.to_request())
    except gitforge.CommitNotFound as exc:
        raise HTTPException(404, f"Commit forge'da bulunamadı: {body.sha}") from exc
    except runner.RunConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except runner.RunnerBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except runner.RunRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    except gitforge.ForgeError as exc:
        raise HTTPException(503, f"Forge okunamadı: {exc}") from exc


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8200)
