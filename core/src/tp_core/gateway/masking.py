"""Ters çevrilebilir PII maskeleme (TEKNIK-TASARIM §8.9, constitution VII).

Tanıyıcılar (Türkiye): TCKN (sağlama algoritmasıyla), TR IBAN (mod-97 ile), TR telefon,
e-posta. Değer → `<<PII_EMAIL_1>>` gibi yer tutucu; aynı değer aynı yer tutucuyu alır. Eşleme
oturumda (iş akışı kapsamında) saklanır, model çıktısında geri açılır.

Varsayılan kapalıdır (`TP_PII_MASKING=0`; yalnızca sentetik veriyle çalışan demo). Kapalıyken
de kanca her çağrıda çalışır ve `ai_call`'a "maskeleme kapalı" farkı yazılır; müşteri verisi
işlenen ortamda açılması zorunludur.

Kayıt (diff) yalnızca tür ve yer tutucuyu içerir; ham PII hiçbir zaman kayda yazılmaz.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

PLACEHOLDER_RE = re.compile(r"<<PII_([A-Z]+)_(\d+)>>")


def tckn_valid(value: str) -> bool:
    if len(value) != 11 or not value.isdigit() or value[0] == "0":
        return False
    d = [int(c) for c in value]
    d10 = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    d11 = sum(d[:10]) % 10
    return d[9] == d10 and d[10] == d11


def iban_valid(value: str) -> bool:
    compact = re.sub(r"\s", "", value).upper()
    if not re.fullmatch(r"TR\d{24}", compact):
        return False
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(numeric) % 97 == 1


@dataclass(frozen=True)
class Recognizer:
    kind: str
    pattern: re.Pattern[str]
    validate: Callable[[str], bool] | None = None


# Sıra önemli: IBAN rakam dizileri TCKN/telefona benzeyebilir, önce o alınır.
RECOGNIZERS: tuple[Recognizer, ...] = (
    Recognizer(
        "IBAN",
        re.compile(r"\bTR\d{2}(?:[ ]?\d){22}\b", re.IGNORECASE),
        iban_valid,
    ),
    Recognizer("TCKN", re.compile(r"(?<![\d.,])[1-9]\d{10}(?![\d.,]\d)"), tckn_valid),
    Recognizer(
        "PHONE",
        re.compile(
            # +90/0090/0 önekli sabit veya mobil; ya da öneksiz ama ayraçlı mobil (5xx xxx xx xx)
            r"(?<![\d+])(?:(?:\+90|0090|0)[\s-]?\(?[2-5]\d{2}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}"
            r"|\(?5\d{2}\)?[\s-]\d{3}[\s-]\d{2}[\s-]\d{2})(?!\d)"
        ),
    ),
    Recognizer(
        "EMAIL",
        re.compile(
            r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"
        ),
    ),
)


@dataclass
class MaskingSession:
    """Bir iş akışı kapsamındaki maskeleme eşlemesi."""

    enabled: bool
    allowlist: frozenset[str] = frozenset()
    _forward: dict[tuple[str, str], str] = field(default_factory=dict)
    _reverse: dict[str, str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    def _placeholder(self, kind: str, value: str) -> str:
        key = (kind, value)
        existing = self._forward.get(key)
        if existing:
            return existing
        n = self._counters.get(kind, 0) + 1
        self._counters[kind] = n
        placeholder = f"<<PII_{kind}_{n}>>"
        self._forward[key] = placeholder
        self._reverse[placeholder] = value
        return placeholder

    def mask_text(self, text: str) -> tuple[str, list[dict[str, str]]]:
        if not self.enabled or not text:
            return text, []
        found: list[dict[str, str]] = []
        # Girdide hazır yer tutucu (ör. güvenilmeyen Jira metninde) varsa etkisizleştir; aksi halde
        # model çıktısı geri açılırken oturumdaki başka bir değerin açığa çıkmasına yol açabilir.
        text = PLACEHOLDER_RE.sub(lambda m: m.group(0).replace("<<", "< <", 1), text)
        for rec in RECOGNIZERS:

            def repl(m: re.Match[str], rec: Recognizer = rec) -> str:
                value = m.group(0)
                if value in self.allowlist or value.lower() in self.allowlist:
                    return value
                if rec.validate is not None and not rec.validate(value):
                    return value
                placeholder = self._placeholder(rec.kind, value)
                found.append({"type": rec.kind, "placeholder": placeholder})
                return placeholder

            text = rec.pattern.sub(repl, text)
        return text, found

    def mask(self, obj: Any) -> tuple[Any, list[dict[str, str]]]:
        """Sözlük/liste içindeki tüm string değerleri maskeler (anahtarlar değişmez)."""
        found: list[dict[str, str]] = []

        def walk(node: Any) -> Any:
            if isinstance(node, str):
                masked, hits = self.mask_text(node)
                found.extend(hits)
                return masked
            if isinstance(node, dict):
                return {k: walk(v) for k, v in node.items()}
            if isinstance(node, list | tuple):
                return [walk(v) for v in node]
            return node

        return walk(obj), found

    def unmask(self, obj: Any) -> Any:
        if not self._reverse:
            return obj
        if isinstance(obj, str):
            return PLACEHOLDER_RE.sub(lambda m: self._reverse.get(m.group(0), m.group(0)), obj)
        if isinstance(obj, dict):
            return {k: self.unmask(v) for k, v in obj.items()}
        if isinstance(obj, list | tuple):
            return [self.unmask(v) for v in obj]
        return obj

    def diff(self, found: list[dict[str, str]]) -> dict[str, Any]:
        """`ai_call`'a yazılan maskeleme farkı (ham değer içermez)."""
        counts: dict[str, int] = {}
        placeholders: list[str] = []
        for hit in found:
            counts[hit["type"]] = counts.get(hit["type"], 0) + 1
            if hit["placeholder"] not in placeholders:
                placeholders.append(hit["placeholder"])
        return {"enabled": self.enabled, "counts": counts, "placeholders": placeholders}


class PiiMasker:
    def __init__(self, *, enabled: bool = False, allowlist: Iterable[str] = ()) -> None:
        self.enabled = enabled
        self.allowlist = frozenset({v for v in allowlist} | {v.lower() for v in allowlist})

    def new_session(self) -> MaskingSession:
        return MaskingSession(enabled=self.enabled, allowlist=self.allowlist)


# ------------------------------------------------------------------ araç argümanı sırları
#
# PII maskelemesinden AYRI ve her zaman açık: ajanın parola alanına yazdığı metin (ör.
# `browser_type {element: "Parola", text: "Demo123!"}`) append-only `tool_call` tablosuna ham
# yazılmaz; sonradan silinemeyeceği için kayıttan ÖNCE gizlenir. Alan, hedefi tanımlayan
# argümanlardan (element / target / ref / selector / name) tanınır — kod üretimindeki
# `features.codegen.browser.mask_args` ile aynı kural. Aynı çalıştırmada gizlenen değerler
# araç sonuç özetinden de (`fill('Demo123!')`) silinir.

SECRET_FIELD_RE = re.compile(r"parola|password|passwd|şifre|sifre", re.IGNORECASE)
SECRET_MASK = "***"
_TARGET_KEYS = ("element", "target", "ref", "selector", "name", "label")
_VALUE_KEYS = ("text", "value")
_MIN_SECRET_LEN = 3  # daha kısa "sır" özetlerde rastgele eşleşir; gizlenmez


def _is_secret_target(args: dict[str, Any]) -> bool:
    target = " ".join(str(args.get(k) or "") for k in _TARGET_KEYS)
    return bool(SECRET_FIELD_RE.search(target)) or str(args.get("type") or "") == "password"


def secret_tool_values(args: Any) -> list[str]:
    """Araç argümanlarında parola alanına yazılan değerler (`browser_fill_form` alanları dahil)."""
    out: list[str] = []
    if isinstance(args, dict):
        if _is_secret_target(args):
            out += [str(args[k]) for k in _VALUE_KEYS if isinstance(args.get(k), str | int)]
        for v in args.values():
            if isinstance(v, dict | list):
                out += secret_tool_values(v)
    elif isinstance(args, list):
        for v in args:
            out += secret_tool_values(v)
    return [v for v in out if v and v != SECRET_MASK]


def mask_tool_args(args: Any) -> Any:
    """Kayıt için araç argümanları: parola alanına yazılan değer `***` olur (kopya döner).

    >>> mask_tool_args({"element": "Parola", "target": "[data-testid=\\"login-password\\"]",
    ...                 "text": "Demo123!"})["text"]
    '***'
    >>> mask_tool_args({"element": "Kullanıcı adı", "text": "bayi3"})["text"]
    'bayi3'
    """
    if isinstance(args, dict):
        secret = _is_secret_target(args)
        return {
            k: (
                SECRET_MASK
                if secret and k in _VALUE_KEYS and isinstance(v, str | int)
                else mask_tool_args(v)
            )
            for k, v in args.items()
        }
    if isinstance(args, list):
        return [mask_tool_args(v) for v in args]
    return args


def scrub_secrets(text: str, secrets: Iterable[str]) -> str:
    """Metindeki bilinen sır değerlerini `***` ile değiştirir (uzundan kısaya)."""
    for value in sorted({s for s in secrets if len(s) >= _MIN_SECRET_LEN}, key=len, reverse=True):
        text = text.replace(value, SECRET_MASK)
    return text


def scrub_secrets_in(value: Any, secrets: Iterable[str]) -> Any:
    """`scrub_secrets`'in JSON değerlerine (dizgeler, iç içe dict/list) uygulanmış hâli."""
    known = list(secrets)
    if isinstance(value, str):
        return scrub_secrets(value, known)
    if isinstance(value, dict):
        return {k: scrub_secrets_in(v, known) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_secrets_in(v, known) for v in value]
    return value


# ------------------------------------------------------------------ biçimden sır temizliği
#
# Asistan araç çıktıları (ürün bilgisi, CI logu, Jira, probe verisi) ve bilgi paketi üretim
# taraması için (AI-ASISTAN-PLANI §5.1, §10.3 Şerit C1). PII maskelemesinden AYRI ve her zaman
# açık; geri açılmaz. Değeri bilinmeyen ama biçimi tanınan sırlar (token önekleri, JWT, özel
# anahtar, URL içi kimlik, Authorization başlığı, `AD=değer` ataması) ile çalışma anı sır
# değerleri (`gateway.factory.known_secret_values`) temizlenir.
#
# Kesme sınırı: araç çıktıları kırpılır (ör. log kuyruğu, 400 satır), bu yüzden metnin SONUNDA
# kalan yarım token (öneki tanınan, gövdesi kısa) ve bilinen sır değerinin metnin başında/sonunda
# kalan ≥ 8 karakterlik parçası da temizlenir.

SECRET_VALUE_MIN_LEN = 8  # çalışma anı sır değerleri: daha kısası rastgele eşleşir


def _onekli(onek: str, govde: str, en_az: int) -> str:
    """Önekli token: tam gövde ya da metin sonunda (kesme) kısa gövde."""
    return rf"{onek}(?:{govde}{{{en_az},}}|{govde}+\Z)"


@dataclass(frozen=True)
class SecretPattern:
    name: str
    pattern: re.Pattern[str]
    # Eşleşmenin korunan kısmı (ör. başlık adı); geri kalanı `***` olur.
    keep_group: str | None = None


SECRET_PATTERNS: tuple[SecretPattern, ...] = (
    # Özel anahtar bloğu (kesikse metin sonuna kadar); BEGIN'i kesilmiş blok aşağıda ayrıca.
    SecretPattern(
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?"
            r"(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)"
        ),
    ),
    SecretPattern(
        "private_key_tail",
        re.compile(r"\A[A-Za-z0-9+/=\s]*-----END [A-Z0-9 ]*PRIVATE KEY-----"),
    ),
    SecretPattern(
        "authorization",
        re.compile(
            r"(?P<keep>\bAuthorization\s*:\s*(?:Bearer|Basic|token)\s+)[^\s'\"`,;]+",
            re.IGNORECASE,
        ),
        keep_group="keep",
    ),
    SecretPattern(
        "env_assignment",
        re.compile(
            r"(?P<keep>\b(?:SEED_USER_PASSWORD|TP_SESSION_SECRET|JIRA_[A-Z_]*TOKEN"
            r"|[A-Z][A-Z0-9_]*(?:_PASSWORD|_SECRET|_API_KEY|_PRIVATE_KEY|_TOKEN))\s*=\s*)"
            r"(?![<${'\"`*])[^\s'\"`]+"
        ),
        keep_group="keep",
    ),
    SecretPattern(
        "url_credentials",
        re.compile(r"(?P<keep>\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^@\s]+(?=@)", re.IGNORECASE),
        keep_group="keep",
    ),
    SecretPattern("github_pat", re.compile(_onekli(r"\bgithub_pat_", r"[A-Za-z0-9_]", 20))),
    SecretPattern("github_token", re.compile(_onekli(r"\bgh[pousr]_", r"[A-Za-z0-9]", 20))),
    SecretPattern("anthropic_key", re.compile(_onekli(r"\bsk-ant-", r"[A-Za-z0-9_-]", 8))),
    SecretPattern("atlassian_token", re.compile(_onekli(r"\bATATT", r"[A-Za-z0-9_=+/-]", 16))),
    SecretPattern("google_api_key", re.compile(_onekli(r"\bAIza", r"[0-9A-Za-z_-]", 20))),
    SecretPattern("aws_access_key", re.compile(r"\bAKIA(?:[0-9A-Z]{16}|[0-9A-Z]+\Z)")),
    SecretPattern("slack_token", re.compile(_onekli(r"\bxox[abposr]-", r"[A-Za-z0-9-]", 8))),
    SecretPattern("npm_token", re.compile(_onekli(r"\bnpm_", r"[A-Za-z0-9]", 20))),
    SecretPattern(
        "jwt",
        re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+|\beyJ[\w-]{8,}(?:\.[\w-]*){0,2}\Z"),
    ),
    SecretPattern("tp_token", re.compile(_onekli(r"\btpt_", r"[A-Za-z0-9]", 8))),
    SecretPattern("tp_mcp_token", re.compile(_onekli(r"\btpk_", r"[A-Za-z0-9_]", 8))),
)


@dataclass(frozen=True)
class SecretFinding:
    """Bulunan sır: tür ve konum (değer TAŞINMAZ; rapora/kayda yalnız bunlar yazılır)."""

    name: str
    start: int
    end: int


def _sir_degerleri(values: Iterable[str]) -> list[str]:
    return sorted(
        {v for v in values if isinstance(v, str) and len(v) >= SECRET_VALUE_MIN_LEN},
        key=len,
        reverse=True,
    )


def find_secret_patterns(text: str, values: Iterable[str] = ()) -> list[SecretFinding]:
    """Metindeki biçimden tanınan sırlar ve bilinen sır değerleri (≥ 8 karakter), konumlarıyla."""
    if not text:
        return []
    found: list[SecretFinding] = []
    for sp in SECRET_PATTERNS:
        for m in sp.pattern.finditer(text):
            start = m.end(sp.keep_group) if sp.keep_group else m.start()
            if m.end() > start:
                found.append(SecretFinding(sp.name, start, m.end()))
    for value in _sir_degerleri(values):
        i = text.find(value)
        while i != -1:
            found.append(SecretFinding("known_value", i, i + len(value)))
            i = text.find(value, i + len(value))
        # Kesme sınırı: metnin sonunda değerin başı, başında değerin sonu kalmış olabilir.
        for n in range(len(value) - 1, SECRET_VALUE_MIN_LEN - 1, -1):
            if text.endswith(value[:n]):
                found.append(SecretFinding("known_value_partial", len(text) - n, len(text)))
                break
        for n in range(len(value) - 1, SECRET_VALUE_MIN_LEN - 1, -1):
            if text.startswith(value[-n:]):
                found.append(SecretFinding("known_value_partial", 0, n))
                break
    return sorted(found, key=lambda f: (f.start, -f.end))


def scrub_secret_patterns(text: str, values: Iterable[str] = ()) -> str:
    """Biçimden tanınan sırları ve bilinen sır değerlerini (≥ 8 karakter) `***` ile değiştirir.

    >>> scrub_secret_patterns("Authorization: Bearer ornek.token-123")
    'Authorization: Bearer ***'
    >>> scrub_secret_patterns("klon: https://ornek:parola@forge.local/x.git")
    'klon: https://***@forge.local/x.git'
    """
    if not text:
        return text
    findings = find_secret_patterns(text, values)
    if not findings:
        return text
    # Çakışan aralıkları birleştir, sonra tek geçişte değiştir (konumlar kaymaz).
    araliklar: list[list[int]] = []
    for f in findings:
        if araliklar and f.start <= araliklar[-1][1]:
            araliklar[-1][1] = max(araliklar[-1][1], f.end)
        else:
            araliklar.append([f.start, f.end])
    parcalar: list[str] = []
    konum = 0
    for bas, son in araliklar:
        parcalar.append(text[konum:bas])
        parcalar.append(SECRET_MASK)
        konum = son
    parcalar.append(text[konum:])
    return "".join(parcalar)
