"""Girdi doğrulaması: her değer kabuk olmadan argv'ye ya da dosya yoluna gider.

Kurallar `-` ile başlayan (seçenek enjeksiyonu), `..` içeren (yol kaçışı), NUL/satır sonu
taşıyan değerleri reddeder. Hata mesajları Türkçe; FastAPI bunları 422 olarak döner.
"""

from __future__ import annotations

import re

# Hex commit kimliği (kısaltılmış da olabilir; çözümden sonra tam sha döner) veya güvenli ref adı.
SHA_RE = re.compile(r"^[0-9a-f]{7,64}\Z")
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}\Z")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
# Test dosyası: e2e köküne göre `tests/**.spec.ts` (üretilen testler de buraya yazılır).
TEST_FILE_RE = re.compile(
    r"^tests/(?:[A-Za-z0-9_][A-Za-z0-9_.-]*/)*[A-Za-z0-9_][A-Za-z0-9_.-]*\.spec\.ts\Z"
)
TESTID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*\Z")
ROLE_RE = re.compile(r"^[a-z]{1,40}\Z")
URL_PATH_RE = re.compile(r"^/[A-Za-z0-9_\-./~%?=&]*\Z")
# Ekilmiş hata kodu (012 §4.6): demo API kataloğundaki kod; test sürecine `TP_FAULT` olarak geçer.
FAULT_RE = re.compile(r"^[a-z0-9_]{1,40}\Z")

MAX_TEST_FILES = 200
MAX_GREP_LEN = 300
MAX_NAME_LEN = 200


def _no_control(value: str, what: str) -> None:
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{what} kontrol karakteri içeremez")


def validate_ref(value: str) -> str:
    """Commit sha'sı veya ref adı (`main`, `tp/case-…`); çözüm forge'da yapılır."""
    if not isinstance(value, str) or not value:
        raise ValueError("sha boş olamaz")
    if SHA_RE.match(value):
        return value
    if (
        not REF_RE.match(value)
        or ".." in value
        or "//" in value
        or value.endswith((".lock", "/", "."))
        or "@{" in value
    ):
        raise ValueError(f"geçersiz commit/ref: {value!r}")
    return value


def validate_run_id(value: str) -> str:
    if not isinstance(value, str) or not RUN_ID_RE.match(value) or ".." in value:
        raise ValueError(f"geçersiz run_id: {value!r} (harf, rakam, '_', '.', '-'; en çok 100)")
    return value


def validate_test_file(value: str) -> str:
    if not isinstance(value, str) or not TEST_FILE_RE.match(value) or ".." in value:
        raise ValueError(f"geçersiz test dosyası: {value!r} (beklenen: tests/**/<ad>.spec.ts)")
    return value


def validate_test_files(values: list[str]) -> list[str]:
    if len(values) > MAX_TEST_FILES:
        raise ValueError(f"en fazla {MAX_TEST_FILES} test dosyası verilebilir")
    out: list[str] = []
    for v in values:
        validate_test_file(v)
        if v not in out:
            out.append(v)
    return out


def validate_grep(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > MAX_GREP_LEN:
        raise ValueError(f"grep en çok {MAX_GREP_LEN} karakter olabilir")
    _no_control(value, "grep")
    return value


def validate_fault(value: str | None) -> str | None:
    """Ekilmiş hata kodu; boş/None = hata yok. Kodun katalogda olup olmadığına demo API karar
    verir (bilinmeyen kod → fixture'ın `/test/break` çağrısı 422, test `test_data` ile kalır)."""
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not FAULT_RE.match(value):
        raise ValueError(f"geçersiz fault: {value!r} (beklenen biçim: ^[a-z0-9_]{{1,40}}$)")
    return value


def resolve_fault(fault: str | None, env: dict[str, str]) -> str | None:
    """Gövdedeki `fault` ile `env.TP_FAULT` eş anlamlıdır; ikisi de verilmişse aynı olmalıdır."""
    env_fault = validate_fault(env.get("TP_FAULT"))
    if fault and env_fault and fault != env_fault:
        raise ValueError("fault ile env.TP_FAULT farklı; yalnızca birini verin")
    return fault or env_fault


def validate_test_id(value: str | None, what: str = "test_id") -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > MAX_NAME_LEN or not TESTID_RE.match(value):
        raise ValueError(f"geçersiz {what}: {value!r}")
    return value


def validate_role(value: str) -> str:
    if not isinstance(value, str) or not ROLE_RE.match(value):
        raise ValueError(f"geçersiz ARIA rolü: {value!r}")
    return value


def validate_name(value: str) -> str:
    if not isinstance(value, str) or len(value) > MAX_NAME_LEN:
        raise ValueError(f"ad en çok {MAX_NAME_LEN} karakter olabilir")
    _no_control(value, "ad")
    return value


def validate_url_path(value: str) -> str:
    """Yalnızca demo uygulaması içinde göreli yol: `/katalog`; şema, `//` ve `..` yok."""
    if (
        not isinstance(value, str)
        or len(value) > 300
        or not URL_PATH_RE.match(value)
        or value.startswith("//")
        or ".." in value
    ):
        raise ValueError(f"geçersiz url_path: {value!r} (ör. /katalog)")
    return value
