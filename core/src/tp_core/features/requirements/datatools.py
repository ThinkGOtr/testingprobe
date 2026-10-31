"""Veri araçları: `db_schema` ve `db_query` (TEKNIK-TASARIM §8.2b "Erişim").

- Bağlantı `DEMOAPP_RO_DATABASE_URL` (rol `demoapp_ro`: yalnızca izinli tablo/kolonlarda SELECT).
- Her sorgu `sqlguard.validate_select`'ten geçer; çalıştırılan metin ayrıştırılmış ağaçtan üretilir.
- İşlem salt okunurdur (`read_only`), `statement_timeout` 5 sn; en fazla 100 satır döner.
- Modele giden sonuç PII maskelemesinden geçer (Constitution VII) ve güvenilmeyen veri bloğuna
  sarılır (§5, `gateway.wrap_tool_result`).

Sonuç özeti — kanıt doğrulamasının karşılaştırdığı değer — model geçidinin tek tanımıdır
(`tp_core.gateway.result_digest`, ör. ``min_siparis_tutari=750.00``); golden'lar, araç ve
doğrulayıcı aynı fonksiyonu kullanır. Maskeleme açıkken okunur özet ham değeri modele sızdırmasın
diye araç bunun yerine `masked_digest` (``sha256:<64 hex>``, tüm hücrelerin kanonik özeti) verir;
doğrulayıcı iki biçimi de kabul eder (`digest_matches_any`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import psycopg

from tp_core.features.requirements.sqlguard import ALLOWED_COLUMNS, validate_select
from tp_core.gateway import PiiMasker, digest_matches, result_digest, wrap_tool_result
from tp_core.gateway.evidence import canonical_cell

MAX_ROWS = 100
STATEMENT_TIMEOUT_MS = 5000
MASKED_PREFIX = "sha256:"


class DataToolError(RuntimeError):
    """Veri aracı çalıştırılamadı (yapılandırma, bağlantı, zaman aşımı)."""


def masked_digest(rows: Sequence[Sequence[Any]]) -> str:
    """Maskeleme açıkken modele verilen özet: değer içermez (sıralı hücrelerin sha256'sı)."""
    hucreler = sorted([canonical_cell(v) for v in r] for r in rows)
    metin = json.dumps(hucreler, ensure_ascii=False, separators=(",", ":"))
    return MASKED_PREFIX + hashlib.sha256(metin.encode()).hexdigest()


def digest_matches_any(claimed: str, rows: Sequence[Sequence[Any]]) -> bool:
    if not isinstance(claimed, str):
        return False
    return digest_matches(claimed, rows) or claimed.strip() == masked_digest(rows)


@dataclass(frozen=True)
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool


def _conninfo(url: str) -> str:
    for onek in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgres://"):
        if url.startswith(onek):
            return "postgresql://" + url[len(onek) :]
    return url


class DemoDb:
    """Test edilen uygulamanın salt okuma veritabanı."""

    def __init__(self, url: str | None, *, connect_timeout_s: int = 3) -> None:
        self.url = url
        self.connect_timeout_s = connect_timeout_s

    def _connect(self) -> psycopg.Connection:
        if not self.url:
            raise DataToolError(
                "Veri erişimi yapılandırılmamış (DEMOAPP_RO_DATABASE_URL tanımlı değil)"
            )
        try:
            conn = psycopg.connect(
                _conninfo(self.url), connect_timeout=self.connect_timeout_s, autocommit=False
            )
        except psycopg.Error as exc:
            raise DataToolError(f"Veritabanına bağlanılamadı: {_ilk_satir(exc)}") from exc
        conn.read_only = True
        return conn

    def query(self, sql: str) -> QueryResult:
        vq = validate_select(sql)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL statement_timeout = {int(STATEMENT_TIMEOUT_MS)}")
                cur.execute(vq.sql)  # parametresiz: metin olduğu gibi gider (% işlenmez)
                kolonlar = [d.name for d in cur.description or []]
                satirlar = [tuple(r) for r in cur.fetchmany(MAX_ROWS + 1)]
        except psycopg.errors.QueryCanceled as exc:
            raise DataToolError("Sorgu zaman aşımına uğradı (5 sn)") from exc
        except psycopg.errors.InsufficientPrivilege as exc:
            raise DataToolError(f"Yetki yok: {_ilk_satir(exc)}") from exc
        except psycopg.Error as exc:
            raise DataToolError(f"Sorgu hatası: {_ilk_satir(exc)}") from exc
        finally:
            conn.rollback()
            conn.close()
        return QueryResult(vq.sql, kolonlar, satirlar[:MAX_ROWS], len(satirlar) > MAX_ROWS)

    def schema(self) -> dict[str, list[tuple[str, str]]]:
        """İzinli tablo/kolonlar ve türleri (izin listesine süzülmüş information_schema)."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name, column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = ANY(%s) "
                    "ORDER BY table_name, ordinal_position",
                    (sorted(ALLOWED_COLUMNS),),
                )
                rows = cur.fetchall()
        except psycopg.Error as exc:
            raise DataToolError(f"Şema okunamadı: {_ilk_satir(exc)}") from exc
        finally:
            conn.rollback()
            conn.close()
        out: dict[str, list[tuple[str, str]]] = {t: [] for t in sorted(ALLOWED_COLUMNS)}
        for tablo, kolon, tur in rows:
            if kolon in ALLOWED_COLUMNS.get(tablo, frozenset()):
                out[tablo].append((kolon, tur))
        return out


def _ilk_satir(exc: BaseException) -> str:
    metin = str(exc).strip()
    return metin.splitlines()[0][:200] if metin else type(exc).__name__


class DataTools:
    """Ajana verilen `db_schema` / `db_query` uygulaması (maskeli, güvenilmeyen blokta)."""

    def __init__(self, db: DemoDb, masker: PiiMasker | None = None) -> None:
        self.db = db
        self.masker = masker or PiiMasker(enabled=False)

    @property
    def masking(self) -> bool:
        return bool(getattr(self.masker, "enabled", False))

    def db_schema(self, _args: dict[str, Any]) -> str:
        sema = self.db.schema()
        satirlar = [
            f"{t}({', '.join(f'{k} {tur}' for k, tur in kolonlar)})" for t, kolonlar in sema.items()
        ]
        return wrap_tool_result("db_schema", "\n".join(satirlar))

    def db_query(self, args: dict[str, Any]) -> str:
        sql = args.get("sql") if isinstance(args, dict) else None
        if not isinstance(sql, str):
            raise DataToolError("'sql' argümanı gerekli")
        res = self.db.query(sql)
        ozet = masked_digest(res.rows) if self.masking else result_digest(res.rows)
        govde = [" | ".join(res.columns)]
        govde += [" | ".join(canonical_cell(v) for v in r) for r in res.rows]
        govde.append(
            f"satır: {len(res.rows)}" + (" (100 satırla kesildi)" if res.truncated else "")
        )
        metin = "\n".join(govde)
        if self.masking:
            maskeli, _ = self.masker.new_session().mask(metin)
            metin = str(maskeli)
        # Sorgu ve özet veri bloğunun dışında: model kanıta bunları birebir kopyalar.
        return f"query: {res.sql}\nresult_digest: {ozet}\n" + wrap_tool_result("db_query", metin)
