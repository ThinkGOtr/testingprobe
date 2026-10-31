"""test-runner kontrol API'si (:8200, yalnızca runner-net) — MIMARI-SOZLESME §2.

`POST /run` eşzamanlıdır (senkron) ve sınırlıdır: koşu `TP_RUN_TIMEOUT_S` (900 sn) içinde biter
ya da süreç grubu öldürülür; aynı anda tek koşu yürür, sıradaki istek en çok
`TP_RUN_QUEUE_WAIT_S` (600 sn) bekler, sonra 409 alır.
"""

from __future__ import annotations

from typing import Annotated, Any

import uvicorn
from fastapi import HTTPException
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

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
    validate_grep,
    validate_ref,
    validate_run_id,
    validate_test_files,
)

ALLOWED_ENV = {"BREAK_CAMPAIGN"}

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

    sha: Annotated[str, AfterValidator(validate_ref)]
    run_id: Annotated[str, AfterValidator(validate_run_id)]
    grep: Annotated[str | None, AfterValidator(validate_grep)] = None
    repeat_each: int = Field(1, ge=1, le=10)
    retries: int = Field(0, ge=0, le=3)
    # Sözleşme: env.BREAK_CAMPAIGN="1"; `break_campaign: true` eş anlamlıdır.
    env: dict[str, str] = Field(default_factory=dict)
    break_campaign: bool = False
    test_files: Annotated[list[str], AfterValidator(validate_test_files)] = Field(
        default_factory=list
    )
    workers: int | None = Field(None, ge=1, le=2)
    # Kanıt olarak saklanacak koşu (kırarak doğrulama, triage): temizlikte silinmez (`.keep`).
    keep: bool = False

    @field_validator("env")
    @classmethod
    def _env(cls, v: dict[str, str]) -> dict[str, str]:
        extra = set(v) - ALLOWED_ENV
        if extra:
            raise ValueError(
                f"izin verilmeyen ortam değişkeni: {sorted(extra)} (yalnızca BREAK_CAMPAIGN)"
            )
        if v.get("BREAK_CAMPAIGN", "") not in ("", "0", "1"):
            raise ValueError("BREAK_CAMPAIGN yalnızca '1', '0' veya boş olabilir")
        return v

    def to_request(self) -> runner.RunRequest:
        return runner.RunRequest(
            sha=self.sha,
            run_id=self.run_id,
            grep=self.grep,
            repeat_each=self.repeat_each,
            retries=self.retries,
            break_campaign=self.break_campaign or self.env.get("BREAK_CAMPAIGN") == "1",
            test_files=self.test_files,
            workers=self.workers,
            keep=self.keep,
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
