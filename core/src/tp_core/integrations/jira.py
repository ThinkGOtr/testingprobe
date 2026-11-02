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
    parse_description,
    text_to_adf,
    valid_account_id,
    with_bot_header,
)
from tp_core.ports import JiraComment, JiraIssue, LabelChange

log = logging.getLogger(__name__)

SIM_BASE_URL = "http://jira-sim:8090"
SIM_XRAY_BASE_URL = "http://jira-sim:8090/xray"
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

    def role_account(self, rol: str) -> str:
        """``analist`` | ``po`` | ``muhendis`` | ``testci`` → accountId (geçersiz/boş → "")."""
        deger = str(getattr(self, f"jira_hesap_{rol}", "") or "").strip()
        return deger if valid_account_id(deger) else ""

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


def authorized_po_approvals(
    changes: Iterable[LabelChange],
    po_accounts: Iterable[str],
    bot_accounts: Iterable[str] = (),
) -> list[LabelChange]:
    """Onay etiketi değişikliklerinden yalnızca yetkili PO'nun koyduklarını döner.

    Yazar boşsa, PO izin listesinde değilse ya da ürünün kendi (bot/yazma) hesabıysa sayılmaz.
    Karşılaştırma büyük/küçük harf duyarsızdır (e-posta). İzin listesi boşsa hiçbir onay geçmez.
    """
    allowed = {a.strip().lower() for a in po_accounts if a and a.strip()}
    denied = {b.strip().lower() for b in bot_accounts if b and b.strip()}
    out = []
    for ch in changes:
        # Yazarın herhangi bir kimliği (e-posta ya da accountId) izinliyse ve hiçbiri bot değilse.
        who = {i.strip().lower() for i in (ch.author, *ch.author_ids) if i and i.strip()}
        if who & allowed and not who & denied:
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
