"""Jira Cloud REST v3 adaptörü (``JiraPort``).

Aynı istemci gerçek Jira Cloud'a da yerel ``jira-sim`` simülatörüne de konuşur; seçim yalnızca
``JIRA_BASE_URL`` ile yapılır. Okuma ve yazma ayrı kimliklerle yapılır (en az yetki): okuma
kullanıcısı yalnızca okur; yorum, etiket, açıklama, issue ve bağlantı yazımı yazma kullanıcısıyla.

İdempotent isteklerde (GET/PUT/DELETE) 429 ve 5xx yanıtları en fazla 3 kez üstel geri çekilmeyle
yeniden denenir; ``Retry-After`` başlığı varsa ona uyulur. POST (issue, yorum, bağlantı, Xray
içe aktarımı) yalnızca isteğin işlenmediği kesin olan yanıtlarda (429 ve ``Retry-After``'lı 503)
yeniden denenir: 500/502/504 sonrası Jira isteği işlemiş olabilir, tekrar göndermek mükerrer kayıt
açar. Karar çağıranın idempotency denetimine (etiket araması / ``external_ref``) bırakılır.

PO onay etiketi (``tp-po-approved``) yalnızca insan PO tarafından konur (TEKNİK-TASARIM §8.2b,
anayasa I): adaptör bu etiketi eklemeyi reddeder (kaldırmaya izin verir: içerik değişince bayat
onayı geri çekmek için); ``authorized_po_approvals`` changelog'daki yazarı PO izin listesiyle
karşılaştırır ve bot hesabının koyduğu etiketi saymaz. ``po_approvals`` ayrıca onaydan sonra
özet, açıklama ya da kabul kriterleri değiştiyse o onayı saymaz: PO'nun görmediği içerik onaylı
sayılamaz.
"""

from __future__ import annotations

import email.utils
import logging
import os
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tp_core.integrations.jira_adf import (
    adf_to_text,
    build_description,
    has_bot_header,
    parse_description,
    strip_bot_header,
    text_to_adf,
    valid_account_id,
    with_bot_header,
)
from tp_core.ports import JiraComment, JiraIssue, LabelChange

log = logging.getLogger(__name__)

SIM_BASE_URL = "http://jira-sim:8090"
SIM_XRAY_BASE_URL = "http://jira-sim:8090/xray"
SIM_SERVICE_NAME = "jira-sim"  # jira-sim `/health` yanıtındaki `service` (sims/jira-sim app.py)
SIM_READ = ("reader@sim.local", "sim")
SIM_WRITE = ("writer@sim.local", "sim")
SIM_PO_ACCOUNTS = ("po@sim.local",)

PO_APPROVED_LABEL = "tp-po-approved"
# Ürünün (bot) yazma kimliğiyle asla eklenemeyen etiketler: insan onayı. Bot bunları
# kaldırabilir (içerik değişince bayat onayı geri çekmek), ama asla ekleyemez.
RESERVED_LABELS = frozenset({PO_APPROVED_LABEL})

# Onaylanan içeriği oluşturan changelog alanları (``field``/``fieldId``, küçük harf). Gerçek Jira'da
# kabul kriterleri ayrı bir özel alandaysa (``customfield_NNNNN``) ``RestJira(content_fields=...)``
# ile eklenir; adında "acceptance" ya da "kabul kriter" geçen alanlar da içerik sayılır.
CONTENT_FIELDS = frozenset({"summary", "description"})
_AC_FIELD_HINTS = ("acceptance", "kabul kriter")

ISSUE_FIELDS = [
    "summary",
    "description",
    "labels",
    "status",
    "issuetype",
    "project",
    "reporter",
    "updated",
    "issuelinks",
]

Sleep = Callable[[float], None]


# ------------------------------------------------------------------------ ayarlar


class JiraSettings(BaseSettings):
    """MİMARİ-SÖZLEŞME §6 ortam değişkenleri (Jira ve test yönetimi)."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    jira_base_url: str = Field(default=SIM_BASE_URL, validation_alias="JIRA_BASE_URL")
    jira_browse_url: str | None = Field(default=None, validation_alias="JIRA_BROWSE_URL")
    jira_project: str = Field(default="TPD", validation_alias="JIRA_PROJECT")
    jira_read_email: str | None = Field(default=None, validation_alias="JIRA_READ_EMAIL")
    jira_read_token: SecretStr | None = Field(default=None, validation_alias="JIRA_READ_TOKEN")
    jira_write_email: str | None = Field(default=None, validation_alias="JIRA_WRITE_EMAIL")
    jira_write_token: SecretStr | None = Field(default=None, validation_alias="JIRA_WRITE_TOKEN")
    jira_timeout_s: float = Field(default=10.0, validation_alias="JIRA_TIMEOUT_S")
    test_mgmt: str = Field(default="jira", validation_alias="TP_TEST_MGMT")
    xray_base_url: str = Field(default=SIM_XRAY_BASE_URL, validation_alias="XRAY_BASE_URL")
    xray_client_id: SecretStr | None = Field(default=None, validation_alias="XRAY_CLIENT_ID")
    xray_client_secret: SecretStr | None = Field(
        default=None, validation_alias="XRAY_CLIENT_SECRET"
    )
    # PO onayını verebilecek Jira hesapları (virgülle; Jira Cloud'da accountId). Boşsa
    # simülatörde ``po@sim.local``, gerçek Jira'da hiç kimse (onay etiketi kabul edilmez).
    jira_po_account_ids: str = Field(default="", validation_alias="JIRA_PO_ACCOUNT_IDS")
    # Rol → Jira accountId: ürün yorumlarında ilgili kişiyi @bahseder (yalnızca bildirim; yetki
    # vermez, onay sayılmaz). Boş = o rol için bahsetme yok.
    jira_hesap_analist: str = Field(default="", validation_alias="JIRA_HESAP_ANALIST")
    jira_hesap_po: str = Field(default="", validation_alias="JIRA_HESAP_PO")
    jira_hesap_muhendis: str = Field(default="", validation_alias="JIRA_HESAP_MUHENDIS")
    jira_hesap_testci: str = Field(default="", validation_alias="JIRA_HESAP_TESTCI")
    # Ürünün bot accountId'leri (virgülle). Gerçek Jira yorum yazarının e-postasını çoğunlukla
    # gizler; asistan okuyucusu bot yorumunu bu kimliklerle tanır.
    jira_bot_account_ids: str = Field(default="", validation_alias="TP_JIRA_BOT_ACCOUNT_IDS")

    def role_account(self, rol: str) -> str:
        """``analist`` | ``po`` | ``muhendis`` | ``testci`` → accountId (geçersiz/boş → "")."""
        deger = str(getattr(self, f"jira_hesap_{rol}", "") or "").strip()
        return deger if valid_account_id(deger) else ""

    @property
    def bot_kimlikleri(self) -> frozenset[str]:
        """Yorum yazan bot hesabının kimlikleri (küçük harf): ``JIRA_WRITE_EMAIL``,
        ``TP_JIRA_BOT_ACCOUNT_IDS``; simülatörde sim yazma kullanıcısı da."""
        ids = {a.strip().lower() for a in self.jira_bot_account_ids.split(",") if a.strip()}
        if self.jira_write_email and self.jira_write_email.strip():
            ids.add(self.jira_write_email.strip().lower())
        if self.is_simulator:
            ids.add(SIM_WRITE[0])
        return frozenset(ids)

    @property
    def po_accounts(self) -> frozenset[str]:
        ids = {a.strip() for a in self.jira_po_account_ids.split(",") if a.strip()}
        if not ids and self.is_simulator:
            ids = set(SIM_PO_ACCOUNTS)
        return frozenset(ids)

    @field_validator("jira_base_url", mode="before")
    @classmethod
    def _base_default(cls, v: Any) -> Any:
        return v or SIM_BASE_URL  # .env'de boş bırakılmış değişken → simülatör

    @field_validator("xray_base_url", mode="before")
    @classmethod
    def _xray_default(cls, v: Any) -> Any:
        return v or SIM_XRAY_BASE_URL

    @field_validator("jira_project", mode="before")
    @classmethod
    def _project_default(cls, v: Any) -> Any:
        return v or "TPD"

    @field_validator("test_mgmt", mode="before")
    @classmethod
    def _mgmt(cls, v: Any) -> str:
        v = str(v or "jira").strip().lower()
        if v not in ("jira", "xray"):
            raise ValueError("TP_TEST_MGMT 'jira' ya da 'xray' olmalı")
        return v

    @property
    def is_simulator(self) -> bool:
        host = urlparse(self.jira_base_url).hostname or ""
        return host in ("jira-sim", "localhost", "127.0.0.1")


@lru_cache
def get_jira_settings() -> JiraSettings:
    return JiraSettings()


# ------------------------------------------------------------------------- hatalar


class JiraError(Exception):
    """Jira isteği başarısız. ``status`` HTTP kodu (bağlantı hatasında ``None``)."""

    def __init__(
        self,
        message: str,
        status: int | None = None,
        errors: Mapping[str, str] | None = None,
        messages: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.status = status
        self.errors = dict(errors or {})
        self.messages = list(messages)


class JiraBadRequest(JiraError): ...


class JiraAuthError(JiraError): ...


class JiraPermissionError(JiraError): ...


class JiraNotFound(JiraError): ...


class JiraUnavailable(JiraError): ...


class JiraConfigError(JiraError): ...


class ReservedLabelError(JiraError, ValueError):
    """Bot kimliğiyle ayrılmış (insan onayı) etiket yazılmaya çalışıldı; istek gönderilmez."""


_STATUS_ERRORS: dict[int, type[JiraError]] = {
    400: JiraBadRequest,
    401: JiraAuthError,
    403: JiraPermissionError,
    404: JiraNotFound,
}


def _error_from(resp: httpx.Response, what: str) -> JiraError:
    messages: list[str] = []
    errors: dict[str, str] = {}
    try:
        body = resp.json()
        if isinstance(body, dict):
            messages = [str(m) for m in body.get("errorMessages") or []]
            errors = {str(k): str(v) for k, v in (body.get("errors") or {}).items()}
            if not messages and body.get("error"):
                messages = [str(body["error"])]
    except ValueError:
        if resp.text:
            messages = [resp.text[:300]]
    detail = "; ".join([*messages, *(f"{k}: {v}" for k, v in errors.items())])
    cls = _STATUS_ERRORS.get(resp.status_code)
    if cls is None:
        cls = JiraUnavailable if resp.status_code == 429 or resp.status_code >= 500 else JiraError
    return cls(
        f"{what} → HTTP {resp.status_code}" + (f": {detail}" if detail else ""),
        status=resp.status_code,
        errors=errors,
        messages=messages,
    )


# ----------------------------------------------------------------- yeniden deneme

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_DELAY_S = 30.0


def retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


IDEMPOTENT_METHODS = frozenset({"GET", "PUT", "DELETE", "HEAD", "OPTIONS"})


def _not_processed(resp: httpx.Response) -> bool:
    """Yanıt, isteğin sunucuda işlenmediğini kesin olarak söylüyor mu?

    429 (hız sınırı) istek kabul edilmeden döner. 503 yalnızca ``Retry-After`` ile gelirse
    (sunucunun kendisi "şimdi işlemedim, sonra gel" diyorsa) işlenmemiş sayılır; ağ geçidinden
    gelen 500/502/504 ise istek arka uca ulaşmış ve işlenmiş olabilir.
    """
    if resp.status_code == 429:
        return True
    return resp.status_code == 503 and resp.headers.get("Retry-After") is not None


def send_with_retry(
    http: httpx.Client,
    method: str,
    url: str,
    *,
    what: str,
    max_retries: int = 3,
    backoff_s: float = 0.5,
    sleep: Sleep = time.sleep,
    timeout: float | httpx.Timeout | None = None,
    idempotent: bool | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """İsteği gönderir; güvenli olduğu durumlarda en fazla ``max_retries`` kez tekrarlar.

    - Bağlantı kurulamadıysa (istek sunucuya ulaşmadı) her yöntem tekrarlanır.
    - Okuma zaman aşımı gibi belirsiz hatalarda ve 500/502/503/504 yanıtlarında yalnızca
      idempotent yöntemler (GET/PUT/DELETE) tekrarlanır.
    - İdempotent olmayan yöntem (POST) yalnızca 429 ve ``Retry-After``'lı 503'te tekrarlanır;
      aksi halde yanıt döner ve çağıran ``JiraUnavailable`` yükseltir.

    ``idempotent`` verilirse yöntemden çıkarılan değerin yerine geçer (ör. Xray kimlik
    doğrulaması POST'tur ama yan etkisizdir).
    """
    if idempotent is None:
        idempotent = method.upper() in IDEMPOTENT_METHODS
    attempt = 0
    while True:
        try:
            resp = http.request(method, url, timeout=timeout, **kwargs)
        except httpx.TransportError as exc:
            safe = idempotent or isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout)
            if not safe or attempt >= max_retries:
                raise JiraUnavailable(f"{what}: {type(exc).__name__}: {exc}") from exc
            sleep(min(backoff_s * 2**attempt, MAX_RETRY_DELAY_S))
            attempt += 1
            continue
        retryable = resp.status_code in RETRYABLE_STATUS and (idempotent or _not_processed(resp))
        if retryable and attempt < max_retries:
            delay = retry_after_seconds(resp.headers.get("Retry-After"))
            if delay is None:
                delay = backoff_s * 2**attempt
            sleep(min(delay, MAX_RETRY_DELAY_S))
            attempt += 1
            continue
        return resp


# ------------------------------------------------------------------ yardımcılar


def parse_jira_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def person(user: Any) -> str:
    """Gösterim için kişi: e-posta (görünürse), yoksa görünen ad, yoksa accountId."""
    if not isinstance(user, dict):
        return ""
    return str(user.get("emailAddress") or user.get("displayName") or user.get("accountId") or "")


def display_name(user: Any) -> str | None:
    """Yalnız gösterim için Jira görünen adı (displayName); yoksa None. Yetki için kullanılmaz."""
    if not isinstance(user, dict):
        return None
    return str(user.get("displayName") or "").strip() or None


def person_id(user: Any) -> str:
    """Yetki kararı için kişi kimliği: e-posta (görünürse), yoksa accountId.

    Görünen ad (``displayName``) hiçbir zaman kullanılmaz: herkes kendi görünen adını PO'nunkiyle
    aynı yapabilir. Jira Cloud e-postayı çoğunlukla gizler; o zaman değişmez ``accountId`` döner.
    """
    if not isinstance(user, dict):
        return ""
    return str(user.get("emailAddress") or user.get("accountId") or "")


def person_ids(user: Any) -> list[str]:
    """Yetki eşlemesi için kişinin tüm kimlikleri: görünürse e-posta, ve accountId.

    PO izin listesi accountId ile (önerilen) ya da e-postayla yapılandırılabilir; Jira e-postayı
    gösterse de gizlese de ikisinden biri eşleşmelidir. Görünen ad hiçbir zaman dahil edilmez.
    """
    if not isinstance(user, dict):
        return []
    ids = (str(user.get("emailAddress") or ""), str(user.get("accountId") or ""))
    return [i for i in ids if i]


_tek_hesap_uyarildi = False


def test_single_account() -> bool:
    """``TP_TEST_TEK_HESAP=1``: yalnız test için bot dışlaması kapalı (tek hesapla PO onayı)."""
    global _tek_hesap_uyarildi
    on = os.environ.get("TP_TEST_TEK_HESAP", "").strip().lower() in {"1", "true", "yes"}
    if on and not _tek_hesap_uyarildi:
        _tek_hesap_uyarildi = True  # süreç başına bir kez; `make status` her seferinde uyarır
        log.warning("TP_TEST_TEK_HESAP açık: bot hesabının PO etiketi onay sayılıyor (YALNIZ TEST)")
    return on


# JIRA_PO_ACCOUNT_IDS'te bu değer: Jira'da etiketi koyabilen/yorum yazabilen herkes PO sayılır.
PO_HERKES = "*"


def authorized_po_approvals(
    changes: Iterable[LabelChange],
    po_accounts: Iterable[str],
    bot_accounts: Iterable[str] = (),
) -> list[LabelChange]:
    """Onay etiketi değişikliklerinden yalnızca yetkili PO'nun koyduklarını döner.

    Yazar boşsa, PO izin listesinde değilse ya da ürünün kendi (bot/yazma) hesabıysa sayılmaz.
    Karşılaştırma büyük/küçük harf duyarsızdır (e-posta). İzin listesi boşsa hiçbir onay geçmez.
    Listede `*` varsa (JIRA_PO_ACCOUNT_IDS=*) Jira'da etiketi koyabilen herkes PO sayılır
    (bot hesabı yine hariç).
    """
    allowed = {a.strip().lower() for a in po_accounts if a and a.strip()}
    herkes = PO_HERKES in allowed
    denied = {b.strip().lower() for b in bot_accounts if b and b.strip()}
    out = []
    for ch in changes:
        # Yazarın herhangi bir kimliği (e-posta ya da accountId) izinliyse ve hiçbiri bot değilse.
        who = {i.strip().lower() for i in (ch.author, *ch.author_ids) if i and i.strip()}
        if who and (herkes or who & allowed) and not who & denied:
            out.append(ch)
    return out


def issue_from_json(raw: Mapping[str, Any]) -> JiraIssue:
    f = raw.get("fields") or {}
    description, acs = parse_description(f.get("description"))
    return JiraIssue(
        key=str(raw["key"]),
        issue_type=str((f.get("issuetype") or {}).get("name") or ""),
        summary=str(f.get("summary") or ""),
        description=description,
        acceptance_criteria=acs,
        labels=[str(lb) for lb in f.get("labels") or []],
        status=str((f.get("status") or {}).get("name") or ""),
        updated=parse_jira_datetime(f.get("updated")),
        reporter=person(f.get("reporter")) or None,
    )


# ---------------------------------------------------------------------- adaptör


class RestJira:
    """``JiraPort`` uygulaması: Jira Cloud REST v3 (veya aynı API'yi sunan jira-sim)."""

    def __init__(
        self,
        base_url: str,
        read_auth: tuple[str, str],
        write_auth: tuple[str, str] | None = None,
        *,
        http: httpx.Client | None = None,
        timeout_s: float = 10.0,
        max_retries: int = 3,
        backoff_s: float = 0.5,
        sleep: Sleep = time.sleep,
        browse_url: str | None = None,
        content_fields: Iterable[str] = (),
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._content_fields = CONTENT_FIELDS | {f.strip().lower() for f in content_fields if f}
        self.browse_url = (browse_url or base_url).rstrip("/")
        self._read_auth = httpx.BasicAuth(*read_auth)
        self._write_auth = httpx.BasicAuth(*write_auth) if write_auth else None
        self._http = http or httpx.Client(headers={"Accept": "application/json"})
        self._timeout = httpx.Timeout(timeout_s, connect=min(timeout_s, 5.0))
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._sleep = sleep

    # ----------------------------------------------------------------- HTTP
    def _call(
        self,
        method: str,
        path: str,
        *,
        write: bool = False,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        if write and self._write_auth is None:
            raise JiraConfigError("Jira yazma kimliği tanımlı değil (JIRA_WRITE_EMAIL/TOKEN)")
        auth = self._write_auth if write else self._read_auth
        what = f"Jira {method} {path}"
        resp = send_with_retry(
            self._http,
            method,
            f"{self.base_url}/rest/api/3{path}",
            what=what,
            max_retries=self._max_retries,
            backoff_s=self._backoff_s,
            sleep=self._sleep,
            timeout=self._timeout,
            auth=auth,
            params=params,
            json=json,
            headers={"Accept": "application/json"},
        )
        if resp.status_code >= 400:
            raise _error_from(resp, what)
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError as exc:
            raise JiraError(f"{what}: JSON olmayan yanıt", status=resp.status_code) from exc

    @staticmethod
    def _key(key: str) -> str:
        return quote(key, safe="")

    def issue_url(self, key: str) -> str:
        return f"{self.browse_url}/browse/{key}"

    def simulator_mu(self) -> bool:
        """Bağlı uç gerçekten jira-sim mi: sim'e özgü `/health` yanıtı (`service == "jira-sim"`).

        Host adına güvenilmez (localhost tüneli gerçek Jira'ya çıkabilir): yalnız simülatörün
        kendi sağlık ucu bu kimliği döndürür. Kimlik bilgisi gönderilmez; hata → False.
        """
        try:
            resp = self._http.get(f"{self.base_url}/health", timeout=self._timeout)
            govde = resp.json() if resp.status_code == 200 else None
        except Exception:
            return False
        return isinstance(govde, dict) and govde.get("service") == SIM_SERVICE_NAME

    # ----------------------------------------------------------------- okuma
    def myself(self, write: bool = False) -> dict[str, Any]:
        return self._call("GET", "/myself", write=write)

    def search(self, jql: str, max_results: int = 50) -> list[JiraIssue]:
        out: list[JiraIssue] = []
        token: str | None = None
        while len(out) < max_results:
            body: dict[str, Any] = {
                "jql": jql,
                "fields": ISSUE_FIELDS,
                "maxResults": min(100, max_results - len(out)),
            }
            if token:
                body["nextPageToken"] = token
            page = self._call("POST", "/search/jql", json=body)
            out.extend(issue_from_json(raw) for raw in page.get("issues") or [])
            token = page.get("nextPageToken")
            if page.get("isLast", True) or not token or not page.get("issues"):
                break
        return out[:max_results]

    def get_issue(self, key: str) -> JiraIssue:
        raw = self._call(
            "GET", f"/issue/{self._key(key)}", params={"fields": ",".join(ISSUE_FIELDS)}
        )
        return issue_from_json(raw)

    def get_comments(self, key: str) -> list[JiraComment]:
        out: list[JiraComment] = []
        start = 0
        while True:
            page = self._call(
                "GET",
                f"/issue/{self._key(key)}/comment",
                params={"startAt": start, "maxResults": 100, "orderBy": "created"},
            )
            comments = page.get("comments") or []
            out.extend(
                JiraComment(
                    id=str(c["id"]),
                    author=person(c.get("author")),
                    author_ids=person_ids(c.get("author")),
                    author_name=display_name(c.get("author")),
                    body=adf_to_text(c.get("body")),
                    created=parse_jira_datetime(c.get("created")),
                )
                for c in comments
            )
            start += len(comments)
            if not comments or start >= int(page.get("total") or 0):
                return out

    def _changelog(self, key: str) -> list[dict[str, Any]]:
        histories: list[dict[str, Any]] = []
        start = 0
        while True:
            page = self._call(
                "GET",
                f"/issue/{self._key(key)}/changelog",
                params={"startAt": start, "maxResults": 100},
            )
            values = page.get("values") or []
            histories.extend(values)
            start += len(values)
            if not values or page.get("isLast", start >= int(page.get("total") or 0)):
                return histories

    @staticmethod
    def _ordered(histories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Changelog eskiden yeniye; aynı zaman damgalı kayıtlar API sırasını korur."""
        floor = datetime.min.replace(tzinfo=UTC)
        return sorted(histories, key=lambda h: parse_jira_datetime(h.get("created")) or floor)

    @staticmethod
    def _label_added(item: Mapping[str, Any], label: str) -> bool:
        if item.get("field") != "labels":
            return False
        before = set((item.get("fromString") or "").split())
        after = set((item.get("toString") or "").split())
        return label in after and label not in before

    def _is_content_item(self, item: Mapping[str, Any]) -> bool:
        names = {str(item.get("field") or "").lower(), str(item.get("fieldId") or "").lower()}
        names.discard("")
        if names & self._content_fields:
            return True
        return any(hint in n for n in names for hint in _AC_FIELD_HINTS)

    @staticmethod
    def _label_removed(item: Mapping[str, Any], label: str) -> bool:
        if item.get("field") != "labels":
            return False
        before = set((item.get("fromString") or "").split())
        after = set((item.get("toString") or "").split())
        return label in before and label not in after

    def _label_events_full(self, key: str, label: str) -> list[tuple[LabelChange, bool, bool]]:
        """Etiketin her eklenişi: ``(değişiklik, içerik_sonra_değişti, etiket_sonra_kaldırıldı)``.

        Sıra zaman damgasıyla değil changelog sırasıyla belirlenir (aynı milisaniyedeki iki
        değişiklik de doğru sıralanır). Etiketin eklendiği düzenlemenin kendisindeki içerik
        değişikliği onaydan önce sayılır (PO o içeriği kendisi yazıp onaylamıştır). Eklemeden
        sonraki herhangi bir kayıtta etiket kaldırıldıysa o ekleme geri çekilmiştir.
        """
        histories = self._ordered(self._changelog(key))
        last_content = -1
        last_removal = -1
        for i, h in enumerate(histories):
            items = h.get("items") or []
            if any(self._is_content_item(it) for it in items):
                last_content = i
            if any(self._label_removed(it, label) for it in items):
                last_removal = i
        events: list[tuple[LabelChange, bool, bool]] = []
        for i, h in enumerate(histories):
            if any(self._label_added(it, label) for it in h.get("items") or []):
                change = LabelChange(
                    label=label,
                    # Yetki için: e-posta ya da accountId; görünen ad asla.
                    author=person_id(h.get("author")),
                    author_ids=person_ids(h.get("author")),
                    at=parse_jira_datetime(h.get("created")),
                )
                events.append((change, last_content > i, last_removal > i))
        return events

    def _label_events(self, key: str, label: str) -> list[tuple[LabelChange, bool]]:
        """Etiketin her eklenişi ve o andan *sonra* içeriğin değişip değişmediği."""
        return [(change, changed) for change, changed, _ in self._label_events_full(key, label)]

    def label_history(self, key: str, label: str) -> list[LabelChange]:
        """Etiketin eklendiği her an (kim, ne zaman), eskiden yeniye.

        ``author`` yetki kararına uygun kimliktir (``person_id``: e-posta ya da accountId).
        """
        return [change for change, _ in self._label_events(key, label)]

    def label_events(self, key: str, label: str) -> list[tuple[LabelChange, bool]]:
        """``label_history`` + her ekleme için ``content_changed_after`` bayrağı."""
        return self._label_events(key, label)

    def issue_types(self, project: str) -> list[str]:
        page = self._call("GET", f"/issue/createmeta/{self._key(project)}/issuetypes")
        return [str(t["name"]) for t in page.get("issueTypes") or page.get("values") or []]

    def link_type_names(self) -> list[str]:
        page = self._call("GET", "/issueLinkType")
        return [str(t["name"]) for t in page.get("issueLinkTypes") or []]

    # ----------------------------------------------------------------- yazma
    def add_comment(self, key: str, body: str, *, mentions: Sequence[str] = ()) -> str:
        """Düz metin yorum. Her yorum bot imiyle (``🤖 AI Testing Probe:``) başlar; ``mentions``
        (accountId) aynı satırda @bahsedilir (yalnızca bildirim)."""
        return self.add_comment_adf(key, text_to_adf(body), mentions=mentions)

    def add_comment_adf(
        self, key: str, adf: Mapping[str, Any], *, mentions: Sequence[str] = ()
    ) -> str:
        """Hazır ADF gövdesiyle yorum (bağlantı işaretli kanıt listeleri için); bot imi eklenir."""
        created = self._call(
            "POST",
            f"/issue/{self._key(key)}/comment",
            write=True,
            json={"body": with_bot_header(dict(adf), mentions)},
        )
        return str(created["id"])

    def _labels(self, key: str, op: str, labels: Sequence[str]) -> None:
        # Ayrılmış etiket bot tarafından eklenemez; kaldırılabilir (bayat onayı geri çekmek).
        reserved = sorted(RESERVED_LABELS.intersection(labels)) if op == "add" else []
        if reserved:
            raise ReservedLabelError(
                f"Ayrılmış etiket yalnızca PO tarafından yazılır: {', '.join(reserved)}"
            )
        ops = [{op: lb} for lb in dict.fromkeys(labels) if lb]
        if not ops:
            return
        self._call("PUT", f"/issue/{self._key(key)}", write=True, json={"update": {"labels": ops}})

    def add_labels(self, key: str, labels: Sequence[str]) -> None:
        self._labels(key, "add", labels)

    def remove_labels(self, key: str, labels: Sequence[str]) -> None:
        self._labels(key, "remove", labels)

    def update_description(
        self, key: str, description: str, acceptance_criteria: Sequence[str]
    ) -> None:
        self._call(
            "PUT",
            f"/issue/{self._key(key)}",
            write=True,
            json={"fields": {"description": build_description(description, acceptance_criteria)}},
        )

    def create_issue(
        self,
        project: str,
        issue_type: str,
        summary: str,
        description: str,
        labels: Sequence[str] = (),
        fields: Mapping[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "project": {"key": project},
            "issuetype": {"name": issue_type},
            "summary": summary[:255],
        }
        if description.strip():
            payload["description"] = text_to_adf(description)
        if labels:
            payload["labels"] = list(dict.fromkeys(labels))
        payload.update(fields or {})
        reserved = sorted(RESERVED_LABELS.intersection(payload.get("labels") or []))
        if reserved:
            raise ReservedLabelError(
                f"Ayrılmış etiket yalnızca PO tarafından yazılır: {', '.join(reserved)}"
            )
        created = self._call("POST", "/issue", write=True, json={"fields": payload})
        return str(created["key"])

    def link_issues(self, inward_key: str, outward_key: str, link_type: str) -> None:
        """Jira semantiği: ``inwardIssue`` <outward ifadesi> ``outwardIssue``.

        Ör. ``Test`` türünde (inward "is tested by", outward "tests"):
        ``link_issues(test_key, story_key, "Test")`` → story "is tested by" test.
        """
        self._call(
            "POST",
            "/issueLink",
            write=True,
            json={
                "type": {"name": link_type},
                "inwardIssue": {"key": inward_key},
                "outwardIssue": {"key": outward_key},
            },
        )

    def bot_identities(self) -> frozenset[str]:
        """Ürünün yazma (bot) hesabının kimlikleri: e-posta ve accountId.

        ``authorized_po_approvals`` için: bot'un koyduğu onay etiketi PO onayı sayılmaz.
        """
        if self._write_auth is None or test_single_account():
            return frozenset()
        me = self.myself(write=True)
        ids = {str(me.get("emailAddress") or ""), str(me.get("accountId") or "")}
        return frozenset(i for i in ids if i)

    def write_identities(self) -> frozenset[str]:
        """Ürünün yazma hesabının kimlikleri (test modundan bağımsız): ürünün kendi yorumları
        PO cevabı sayılmasın (JIRA_PO_ACCOUNT_IDS=* iken)."""
        if self._write_auth is None:
            return frozenset()
        me = self.myself(write=True)
        ids = {str(me.get("emailAddress") or ""), str(me.get("accountId") or "")}
        return frozenset(i for i in ids if i)

    def po_approvals(
        self, key: str, po_accounts: Iterable[str], label: str = PO_APPROVED_LABEL
    ) -> list[LabelChange]:
        """Geçerli PO onayları: ``label``'ı yetkili PO'nun eklediği ve sonrasında özet, açıklama
        ya da kabul kriterleri değişmemiş anlar.

        Bot ve izin listesi dışı yazarlar elenir. Onaydan sonra içerik değiştiyse (ör.
        ``apply-doc-fixes`` açıklamayı yeniden yazdı) o onay sayılmaz: PO yeni içeriği görmedi
        (anayasa I). Onaydan sonra etiket kaldırıldıysa (PO onayı geri çekti ya da bayat etiket
        temizlendi) o onay da sayılmaz; yalnızca son kaldırmadan sonraki eklemeler geçerlidir.
        Geçerli onay için PO etiketi yeniden eklemelidir.
        """
        fresh = [
            change
            for change, changed, removed in self._label_events_full(key, label)
            if not changed and not removed
        ]
        return authorized_po_approvals(fresh, po_accounts, self.bot_identities())

    def raw_fields(self, key: str, fields: Sequence[str]) -> dict[str, Any]:
        """Kaydın ham (ADF dahil) alanları; ``JiraIssue``'ya dönüştürülmeden."""
        raw = self._call("GET", f"/issue/{self._key(key)}", params={"fields": ",".join(fields)})
        return dict(raw.get("fields") or {})

    def edit_issue(
        self,
        key: str,
        *,
        fields: Mapping[str, Any] | None = None,
        add_labels: Sequence[str] = (),
        remove_labels: Sequence[str] = (),
    ) -> None:
        """Alanları ve etiketleri tek düzenlemede yazar (tek changelog kaydı).

        Ayrılmış etiket (``tp-po-approved``) eklenemez, kaldırılabilir.
        """
        reserved = sorted(RESERVED_LABELS.intersection(add_labels))
        if reserved:
            raise ReservedLabelError(
                f"Ayrılmış etiket yalnızca PO tarafından yazılır: {', '.join(reserved)}"
            )
        ops = [{"remove": lb} for lb in dict.fromkeys(remove_labels) if lb]
        ops += [{"add": lb} for lb in dict.fromkeys(add_labels) if lb]
        body: dict[str, Any] = {}
        if fields:
            body["fields"] = dict(fields)
        if ops:
            body["update"] = {"labels": ops}
        if body:
            self._call("PUT", f"/issue/{self._key(key)}", write=True, json=body)

    def transitions(self, key: str) -> list[dict[str, Any]]:
        """Kaydın şu an yapılabilecek durum geçişleri (``id``, ``name``, ``to``)."""
        page = self._call("GET", f"/issue/{self._key(key)}/transitions")
        return list(page.get("transitions") or [])

    def transition(self, key: str, transition_id: str) -> None:
        self._call(
            "POST",
            f"/issue/{self._key(key)}/transitions",
            write=True,
            json={"transition": {"id": str(transition_id)}},
        )

    def delete_comment(self, key: str, comment_id: str) -> None:
        self._call(
            "DELETE", f"/issue/{self._key(key)}/comment/{quote(comment_id, safe='')}", write=True
        )

    def delete_issue(self, key: str) -> None:
        self._call("DELETE", f"/issue/{self._key(key)}", write=True)

    def close(self) -> None:
        self._http.close()


# ---------------------------------------------------------------------- fabrika


def _creds(
    email_: str | None, token: SecretStr | None, sim_default: tuple[str, str], sim: bool, role: str
) -> tuple[str, str] | None:
    if email_ and token and token.get_secret_value():
        return (email_, token.get_secret_value())
    if sim:
        return sim_default
    if role == "read":
        raise JiraConfigError("JIRA_READ_EMAIL/JIRA_READ_TOKEN tanımlı değil")
    return None


def get_jira(settings: JiraSettings | None = None, *, http: httpx.Client | None = None) -> RestJira:
    """Ayarlardan ``RestJira`` kurar. Simülatör adresinde kimlik verilmemişse sim kullanıcıları."""
    s = settings or get_jira_settings()
    read = _creds(s.jira_read_email, s.jira_read_token, SIM_READ, s.is_simulator, "read")
    write = _creds(s.jira_write_email, s.jira_write_token, SIM_WRITE, s.is_simulator, "write")
    assert read is not None
    return RestJira(
        s.jira_base_url,
        read,
        write,
        http=http,
        timeout_s=s.jira_timeout_s,
        browse_url=s.jira_browse_url,
    )


# ------------------------------------------------------------ asistan: dar okuyucu
#
# AI-ASISTAN-PLANI §5.6. Asistanın `jira_issue` aracı `RestJira`'yı hiç görmez; yalnızca bu
# okuyucuyu alır: üç okuma yöntemi (`get_issue`, `son_yorumlar`, `issue_url`), yazma yöntemi yok.
# En az yetki üç katmanlıdır: (1) sınıfta yazma yöntemi yok, (2) httpx istemcisinin transport'u
# GET dışındaki her isteği gönderilmeden reddeder, (3) kimlik `JIRA_READ_*` okuma hesabıdır
# (`security-check` gerçek Jira'da bu hesabın yorum/issue yazma izni taşımadığını denetler).
#
# Kişi verisi modele gitmez: yorumlar ham ADF üzerinde tek geçişte işlenir — kısıtlı yorumlar
# (`visibility` dolu ya da `jsdPublic=false`) elenir, bot yorumu `has_bot_header` VE yazarın bot
# hesabı olmasıyla (`JiraSettings.bot_kimlikleri`) tanınır (imi taklit eden kişi bot sayılmaz),
# yazar ve ADF mention'ları rol etiketine ("PO", "analyst" …) ya da mesaj içi takma ada
# ("Kişi-1") çevrilir; ad/e-posta/accountId metne hiç girmez.

BOT_ETIKETI = "Testing Probe botu"
PO_ETIKETI = "PO"
TAKMA_AD_ONEKI = "Kişi"
# `JIRA_HESAP_*` (ürün yorumlarında @bahsedilen rol hesapları) → portal rol kodu.
HESAP_ROLLERI: tuple[tuple[str, str], ...] = (
    ("analist", "analyst"),
    ("po", "po"),
    ("muhendis", "engineer"),
    ("testci", "tester"),
)
OKUMA_MAX_YENIDEN_DENEME = 1


class JiraYalnizOkuma(JiraError):
    """Okuyucunun HTTP katmanı GET dışında bir istek göndermeye çalıştı (gönderilmedi)."""


class JiraSureAsimi(JiraUnavailable):
    """Araç süresi doldu ya da ``Retry-After`` kalan süreden uzun (beklenmedi)."""


class YalnizGetTransport(httpx.BaseTransport):
    """GET dışındaki her isteği ağa çıkmadan reddeden transport sarmalayıcısı."""

    def __init__(self, ic: httpx.BaseTransport) -> None:
        self._ic = ic

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method.upper() != "GET":
            raise JiraYalnizOkuma(f"Jira okuyucusu yalnızca GET gönderir ({request.method})")
        return self._ic.handle_request(request)

    def close(self) -> None:
        self._ic.close()


@dataclass(frozen=True)
class OkunanYorum:
    """Modele gidebilecek yorum: yazar yalnız etiket (rol/bot/takma ad), metin düz."""

    id: str
    yazar: str
    tarih: datetime | None
    metin: str


@dataclass(frozen=True)
class YorumSayfasi:
    toplam: int  # kayıttaki tüm yorumlar (kısıtlılar dahil)
    yorumlar: list[OkunanYorum]  # en eskiden en yeniye, kısıtlılar elenmiş
    kisitli: int  # okunan aralıkta elenen kısıtlı yorum sayısı


@dataclass(frozen=True)
class OkunanIssue:
    """``JiraIssue``'nun kişi verisi ayıklanmış hâli (raporlayan/ad yok)."""

    key: str
    issue_type: str
    summary: str
    description: str
    acceptance_criteria: list[str]
    labels: list[str]
    status: str
    updated: datetime | None


def kisitli_yorum_mu(c: Mapping[str, Any]) -> bool:
    """Rol/grup kısıtlı (``visibility``) ya da iç not (``jsdPublic=false``) yorum."""
    return bool(c.get("visibility")) or c.get("jsdPublic") is False


class KisiEtiketleyici:
    """Jira kimliklerini modele gidebilecek etiketlere çevirir (mesaj içi tutarlı).

    Sıra: PO izin listesi (``JiraSettings.po_accounts``) → "PO"; ``JIRA_HESAP_*`` eşlemesi →
    portal rol kodu; diğerleri → "Kişi-N" (aynı kişi aynı mesajda hep aynı takma adı alır;
    ``takma_adlar`` sözlüğü çağıran tarafından mesaj boyunca paylaşılabilir).
    """

    def __init__(
        self,
        po_hesaplari: Iterable[str] = (),
        rol_hesaplari: Mapping[str, str] | None = None,
        takma_adlar: dict[str, str] | None = None,
    ) -> None:
        self._po = {a.strip().lower() for a in po_hesaplari if a and a.strip()}
        self._roller = {
            k.strip().lower(): v for k, v in (rol_hesaplari or {}).items() if k and k.strip()
        }
        self.takma_adlar = takma_adlar if takma_adlar is not None else {}

    @classmethod
    def ayarlardan(
        cls, s: JiraSettings, takma_adlar: dict[str, str] | None = None
    ) -> KisiEtiketleyici:
        roller: dict[str, str] = {}
        for jira_rol, portal_rol in HESAP_ROLLERI:
            hesap = s.role_account(jira_rol)
            if hesap:
                roller.setdefault(hesap, portal_rol)
        return cls(s.po_accounts, roller, takma_adlar)

    def etiket(self, kimlikler: Iterable[str]) -> str:
        ids = [i.strip().lower() for i in kimlikler if i and i.strip()]
        if not ids:
            return f"{TAKMA_AD_ONEKI}-?"
        if any(i in self._po for i in ids):
            return PO_ETIKETI
        for i in ids:
            if i in self._roller:
                return self._roller[i]
        anahtar = min(ids)  # e-posta/accountId hangisi görünürse görünsün aynı kişi
        for i in ids:
            if i in self.takma_adlar:
                return self.takma_adlar[i]
        ad = f"{TAKMA_AD_ONEKI}-{len(set(self.takma_adlar.values())) + 1}"
        for i in {anahtar, *ids}:
            self.takma_adlar[i] = ad
        return ad

    def mentionlari_degistir(self, adf: Any) -> Any:
        """ADF ağacının kopyası: her ``mention`` düğümü ``@<etiket>`` metnine çevrilir.

        Jira okumada mention'ın ``attrs.text`` alanı görünen adı taşır; o alan hiç okunmaz.
        """
        if isinstance(adf, list):
            return [self.mentionlari_degistir(x) for x in adf]
        if not isinstance(adf, dict):
            return adf
        if adf.get("type") == "mention":
            attrs = adf.get("attrs") if isinstance(adf.get("attrs"), dict) else {}
            return {"type": "text", "text": "@" + self.etiket([str(attrs.get("id") or "")])}
        out = {k: v for k, v in adf.items() if k != "content"}
        if "content" in adf:
            out["content"] = self.mentionlari_degistir(adf["content"])
        return out


class JiraOkuyucu:
    """Asistanın Jira'ya tek kapısı: yalnız okuma, süre sınırlı, kişi verisi ayıklanmış.

    ``toplam_sure_s`` okuyucunun ömrü boyunca tüm isteklerin (yeniden denemeler ve beklemeler
    dahil) sığması gereken süredir; istek başı zaman aşımı ``min(timeout_s, kalan)``. Yeniden
    deneme beklemesi kalan süreyi aşacaksa beklenmez, ``JiraSureAsimi`` fırlar.
    """

    def __init__(
        self,
        base_url: str,
        read_auth: tuple[str, str],
        *,
        timeout_s: float,
        toplam_sure_s: float,
        transport: httpx.BaseTransport | None = None,
        browse_url: str | None = None,
        etiketleyici: KisiEtiketleyici | None = None,
        bot_kimlikleri: Iterable[str] = (),
        max_retries: int = OKUMA_MAX_YENIDEN_DENEME,
        backoff_s: float = 0.5,
        sleep: Sleep = time.sleep,
        saat: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._browse_url = (browse_url or base_url).rstrip("/")
        self._timeout_s = max(0.1, float(timeout_s))
        self._saat = saat
        self._bitis = saat() + max(0.0, float(toplam_sure_s))
        self._uyku_ic = sleep
        self._max_retries = max(0, int(max_retries))
        self._backoff_s = backoff_s
        self._etiketleyici = etiketleyici or KisiEtiketleyici()
        self._bot = {b.strip().lower() for b in bot_kimlikleri if b and b.strip()}
        self._http = httpx.Client(
            transport=YalnizGetTransport(transport or httpx.HTTPTransport()),
            auth=httpx.BasicAuth(*read_auth),
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )

    # ----------------------------------------------------------------- HTTP
    def kalan_s(self) -> float:
        return max(0.0, self._bitis - self._saat())

    def _uyku(self, sure: float) -> None:
        if sure >= self.kalan_s():
            raise JiraSureAsimi("Jira yeniden deneme beklemesi kalan süreyi aşıyor")
        self._uyku_ic(sure)

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        kalan = self.kalan_s()
        if kalan <= 0.05:
            raise JiraSureAsimi("Jira araç süresi doldu")
        sure = min(self._timeout_s, kalan)
        what = f"Jira GET {path}"
        resp = send_with_retry(
            self._http,
            "GET",
            f"{self._base_url}/rest/api/3{path}",
            what=what,
            max_retries=self._max_retries,
            backoff_s=self._backoff_s,
            sleep=self._uyku,
            timeout=httpx.Timeout(sure, connect=min(sure, 5.0)),
            params=params,
        )
        if resp.status_code >= 400:
            raise _error_from(resp, what)
        try:
            return resp.json()
        except ValueError as exc:
            raise JiraError(f"{what}: JSON olmayan yanıt", status=resp.status_code) from exc

    # ----------------------------------------------------------------- okuma
    def issue_url(self, key: str) -> str:
        """Yalnız sunucunun bağlantı kurması içindir; modele verilmez (§7.3)."""
        return f"{self._browse_url}/browse/{key}"

    def get_issue(self, key: str) -> OkunanIssue:
        raw = self._get(f"/issue/{quote(key, safe='')}", {"fields": ",".join(ISSUE_FIELDS)})
        f = raw.get("fields") if isinstance(raw, dict) else None
        f = f if isinstance(f, dict) else {}
        aciklama, acs = parse_description(
            self._etiketleyici.mentionlari_degistir(f.get("description"))
        )
        return OkunanIssue(
            key=str(raw.get("key") or key),
            issue_type=str((f.get("issuetype") or {}).get("name") or ""),
            summary=str(f.get("summary") or ""),
            description=aciklama,
            acceptance_criteria=acs,
            labels=[str(lb) for lb in f.get("labels") or []],
            status=str((f.get("status") or {}).get("name") or ""),
            updated=parse_jira_datetime(f.get("updated")),
        )

    def _yorum(self, c: Mapping[str, Any]) -> OkunanYorum:
        govde = c.get("body")
        kimlikler = person_ids(c.get("author"))
        # Bot etiketi yalnız bot hesabının imli yorumuna: imi taklit eden kişi kendi etiketini
        # alır ve im metinde kalır (güven yükseltmesi yok).
        if has_bot_header(govde) and any(i.strip().lower() in self._bot for i in kimlikler):
            yazar = BOT_ETIKETI
        else:
            yazar = self._etiketleyici.etiket(kimlikler)
        metin = adf_to_text(self._etiketleyici.mentionlari_degistir(govde))
        if yazar == BOT_ETIKETI:
            metin = strip_bot_header(metin)
        return OkunanYorum(
            id=str(c.get("id") or ""),
            yazar=yazar,
            tarih=parse_jira_datetime(c.get("created")),
            metin=metin,
        )

    def son_yorumlar(self, key: str, n: int) -> YorumSayfasi:
        """Son ``n`` yorum, en çok 2 istekle: önce ``maxResults=1`` ile ``total``, sonra
        ``startAt=max(0, total-n)``. (``get_comments`` tüm sayfaları gezer; kullanılmaz.)"""
        n = max(1, int(n))
        yol = f"/issue/{quote(key, safe='')}/comment"
        ilk = self._get(yol, {"startAt": 0, "maxResults": 1})
        toplam = int((ilk or {}).get("total") or 0)
        if toplam <= 0:
            return YorumSayfasi(0, [], 0)
        if toplam == 1:
            ham = (ilk or {}).get("comments") or []
        else:
            bas = max(0, toplam - n)
            sayfa = self._get(yol, {"startAt": bas, "maxResults": n})
            ham = (sayfa or {}).get("comments") or []
        ham = [c for c in ham if isinstance(c, dict)][-n:]
        kisitli = sum(1 for c in ham if kisitli_yorum_mu(c))
        yorumlar = [self._yorum(c) for c in ham if not kisitli_yorum_mu(c)]
        return YorumSayfasi(toplam, yorumlar, kisitli)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> JiraOkuyucu:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def get_jira_okuma(
    timeout_s: float,
    toplam_sure_s: float,
    *,
    settings: JiraSettings | None = None,
    transport: httpx.BaseTransport | None = None,
    takma_adlar: dict[str, str] | None = None,
    sleep: Sleep = time.sleep,
    saat: Callable[[], float] = time.monotonic,
) -> JiraOkuyucu:
    """Okuma kimliğiyle (``JIRA_READ_*``; simülatörde sim okuma kullanıcısı) ``JiraOkuyucu``.

    Araç çağrısı başına kurulur; ``max_retries=1``. Yazma kimliği hiç okunmaz.
    """
    s = settings or get_jira_settings()
    read = _creds(s.jira_read_email, s.jira_read_token, SIM_READ, s.is_simulator, "read")
    assert read is not None
    return JiraOkuyucu(
        s.jira_base_url,
        read,
        timeout_s=timeout_s,
        toplam_sure_s=toplam_sure_s,
        transport=transport,
        browse_url=s.jira_browse_url,
        etiketleyici=KisiEtiketleyici.ayarlardan(s, takma_adlar),
        bot_kimlikleri=s.bot_kimlikleri,
        sleep=sleep,
        saat=saat,
    )
