"""Bug şeridinin dış bağımlılık fabrikaları (Jira, model geçidi).

Üretimde `get_jira()` (core-worker: okuma + yazma kimliği) ve `build_gateway()` (TP_MODEL_MODE)
kullanılır; testler `override(...)` ile süreç içi jira-sim istemcisi ve FakeProvider'lı geçit
verir. Kod yolu aynıdır.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine

_overrides: dict[str, Callable[..., Any]] = {}
_jira_cache: list[Any] = []


def jira() -> Any:
    """`RestJira` (JiraPort + `link_type_names`/`issue_url`)."""
    f = _overrides.get("jira")
    if f is not None:
        return f()
    if not _jira_cache:
        from tp_core.integrations.jira import get_jira

        _jira_cache.append(get_jira())
    return _jira_cache[0]


def gateway(engine: Engine) -> Any:
    f = _overrides.get("gateway")
    if f is not None:
        return f(engine)
    from tp_core.audit import PgCallRecorder
    from tp_core.gateway import build_gateway

    return build_gateway(PgCallRecorder(engine), engine=engine)


def project() -> str:
    f = _overrides.get("project")
    if f is not None:
        return str(f())
    from tp_core.integrations.jira import get_jira_settings

    return get_jira_settings().jira_project


def testdata() -> str | None:
    """Case üretimindeki test verisi bloğu (bayi/ürün/limit; taslak adımlarının kaynağı)."""
    f = _overrides.get("testdata")
    if f is not None:
        return f()
    from tp_core.features.cases import testdata as td

    return td.block()


def public_base_url() -> str:
    """Jira'ya yazılan kanıt bağlantılarının mutlak kökü (portal; `/api/artifacts` oradan sunulur).

    `TP_PUBLIC_BASE_URL` (ör. `https://probe.example.com`) yoksa yerel portal
    (`http://127.0.0.1:${TP_PORTAL_PORT:-8080}`). Portal görünümünde bağlantılar göreli kalır;
    yalnızca Jira açıklaması/yorumu mutlak bağlantı alır (Jira göreli yolu kendi sunucusuna çözer).
    """
    f = _overrides.get("public_base_url")
    if f is not None:
        return str(f()).rstrip("/")
    acik = (os.environ.get("TP_PUBLIC_BASE_URL") or "").strip()
    if acik:
        return acik.rstrip("/")
    port = (os.environ.get("TP_PORTAL_PORT") or "8080").strip() or "8080"
    return f"http://127.0.0.1:{port}"


def code_url(path: str, line: Any, sha: str | None) -> str | None:
    """Kod kanıtının denetlenen commit'teki forge bağlantısı (yalnızca web arayüzü olan forge).

    `TP_FORGE=github` ve `GITHUB_REPO` → `https://github.com/<repo>/blob/<sha>/<path>#L<n>`
    (`TP_FORGE_WEB_URL` ile değiştirilebilir). LocalForge'un web arayüzü yoktur: None (çağıran
    commit'i metin olarak yazar).
    """
    f = _overrides.get("code_url")
    if f is not None:
        return f(path, line, sha)
    if not sha or (os.environ.get("TP_FORGE") or "local").strip() != "github":
        return None
    repo = (os.environ.get("GITHUB_REPO") or "").strip().strip("/")
    if not repo:
        return None
    web = (os.environ.get("TP_FORGE_WEB_URL") or "https://github.com").rstrip("/")
    satir = f"#L{line}" if str(line or "").isdigit() else ""
    return f"{web}/{repo}/blob/{sha}/{path.lstrip('/')}{satir}"


def add_adf_comment(
    jira_client: Any, key: str, body: dict[str, Any], *, mentions: Sequence[str] = ()
) -> str:
    """ADF gövdeli Jira yorumu (bağlantı işaretleri korunur); yorum id'si.

    `JiraPort.add_comment` düz metin alır (`text_to_adf`; bağlantılar tıklanamaz). İstemci ADF
    yorumu sunuyorsa (`add_comment_adf`) o; `RestJira` ise aynı uç (`POST /issue/{key}/comment`)
    ADF gövdeyle yazma kimliğiyle çağrılır; ikisi de yoksa düz metne düşülür. `mentions`
    (accountId) yorumun bot imi satırında @bahsedilir (yalnızca bildirim); boşsa istemciye hiç
    geçirilmez.
    """
    from tp_core.integrations.jira_adf import adf_to_text, with_bot_header

    fn = getattr(jira_client, "add_comment_adf", None)
    if callable(fn):
        return str(fn(key, body, mentions=list(mentions)) if mentions else fn(key, body))
    call = getattr(jira_client, "_call", None)
    if callable(call):
        from urllib.parse import quote

        created = call(
            "POST",
            f"/issue/{quote(key, safe='')}/comment",
            write=True,
            json={"body": with_bot_header(body, mentions)},
        )
        return str(created["id"])
    return str(jira_client.add_comment(key, adf_to_text(body)))


@contextmanager
def override(**factories: Callable[..., Any]) -> Iterator[None]:
    bilinmeyen = set(factories) - {
        "jira",
        "gateway",
        "project",
        "testdata",
        "public_base_url",
        "code_url",
    }
    if bilinmeyen:
        raise ValueError(f"bilinmeyen servis: {sorted(bilinmeyen)}")
    onceki = dict(_overrides)
    _overrides.update(factories)
    try:
        yield
    finally:
        _overrides.clear()
        _overrides.update(onceki)
