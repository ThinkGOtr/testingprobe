"""Veri araçları: `db_schema` ve `db_query` (TEKNIK-TASARIM §8.2b "Erişim").

- Bağlantı `DEMOAPP_RO_DATABASE_URL` ya da `TP_RO_DB_*` (PostgreSQL, MySQL/MariaDB, SQL Server,
  Oracle; `tp_core.veri.ro_baglanti`). Rol yalnızca izinli tablo/kolonlarda SELECT yetkilidir.
- Her sorgu hedef lehçede `sqlguard.validate_select`'ten geçer; çalıştırılan metin ayrıştırılmış
  ağaçtan üretilir.
- İşlem salt okunurdur (türüne göre), sorgu zaman aşımı 5 sn; en fazla 100 satır döner.
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
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from tp_core.features.requirements.sqlguard import ALLOWED_COLUMNS, validate_select
from tp_core.gateway import PiiMasker, digest_matches, result_digest, wrap_tool_result
from tp_core.gateway.evidence import canonical_cell
from tp_core.gateway.masking import MaskingSession
from tp_core.veri import ro_baglanti
from tp_core.veri.ro_baglanti import BaglantiTanimi

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


class DemoDb:
    """Test edilen uygulamanın salt okuma veritabanı (PostgreSQL, MySQL/MariaDB, SQL Server,
    Oracle; bağlantı ve oturum güvencesi `tp_core.veri.ro_baglanti`).

    `url`: bağlantı dizesi (`DEMOAPP_RO_DATABASE_URL`; tür önekten) ya da çözülmüş
    `BaglantiTanimi` (ayrı alanlar `TP_RO_DB_*`). None → "yapılandırılmamış" hatası."""

    def __init__(self, url: str | BaglantiTanimi | None, *, connect_timeout_s: int = 3) -> None:
        self.url = url
        self.connect_timeout_s = connect_timeout_s
        self._tanim: BaglantiTanimi | None = None
        self._tanim_hatasi: str | None = None
        if isinstance(url, BaglantiTanimi):
            self._tanim = url
        elif url:
            try:
                self._tanim = ro_baglanti.url_coz(url)
            except ro_baglanti.BaglantiHatasi as exc:
                self._tanim_hatasi = str(exc)

    @classmethod
    def yapilandirma_hatasi(cls, mesaj: str) -> DemoDb:
        """Geçersiz yapılandırma: her çağrı bu (maskeli) metinle `DataToolError` verir."""
        db = cls(None)
        db._tanim_hatasi = mesaj
        return db

    @property
    def tanim(self) -> BaglantiTanimi | None:
        return self._tanim

    @property
    def tur(self) -> str:
        """Veritabanı türü (`postgresql`, `mysql`, `mssql`, `oracle`); yapılandırılmamışsa PG."""
        return self._tanim.tur if self._tanim is not None else "postgresql"

    @property
    def lehce(self) -> str:
        """sqlglot lehçesi (sorgu muhafızı ve prompt'taki hedef lehçe bilgisi)."""
        return ro_baglanti.SQLGLOT_LEHCE[self.tur]

    @contextmanager
    def _oturum(self) -> Iterator[ro_baglanti.RoOturum]:
        if self._tanim is None:
            raise DataToolError(self._tanim_hatasi or ro_baglanti.YAPILANDIRMA_YOK)
        try:
            with ro_baglanti.oturum(
                self._tanim,
                connect_timeout_s=self.connect_timeout_s,
                timeout_ms=int(STATEMENT_TIMEOUT_MS),
            ) as o:
                yield o
        except ro_baglanti.BaglantiHatasi as exc:
            raise DataToolError(str(exc)) from exc

    def query(self, sql: str, *, kaynak_lehce: str | None = None) -> QueryResult:
        """Muhafızdan geçen tek SELECT'i çalıştırır. `kaynak_lehce="postgres"`: TP'nin sabit
        (PostgreSQL ile yazılmış) sorgusu; önce hedef lehçeye çevrilir."""
        if kaynak_lehce == "postgres" and self._tanim is not None:
            sql = ro_baglanti.sabit_sql(sql, self.tur)
        vq = validate_select(sql, lehce=self.lehce)
        with self._oturum() as o:
            try:
                kolonlar, satirlar = o.calistir(vq.sql, en_fazla=MAX_ROWS + 1)
            except ro_baglanti.SorguHatasi as exc:
                if exc.tur == ro_baglanti.ZAMAN:
                    sure = int(STATEMENT_TIMEOUT_MS) / 1000
                    raise DataToolError(f"Sorgu zaman aşımına uğradı ({sure:g} sn)") from exc
                if exc.tur == ro_baglanti.YETKI:
                    raise DataToolError(f"Yetki yok: {exc}") from exc
                raise DataToolError(f"Sorgu hatası: {exc}") from exc
        return QueryResult(vq.sql, kolonlar, satirlar[:MAX_ROWS], len(satirlar) > MAX_ROWS)

    def schema(self) -> dict[str, list[tuple[str, str]]]:
        """İzinli tablo/kolonlar ve türleri (izin listesine süzülmüş information_schema; Oracle
        `ALL_TAB_COLUMNS`)."""
        tablolar = sorted(ALLOWED_COLUMNS)
        with self._oturum() as o:
            try:
                _, ham = o.calistir(ro_baglanti.sema_sorgusu(self.tur, tablolar))
            except ro_baglanti.SorguHatasi as exc:
                raise DataToolError(f"Şema okunamadı: {exc}") from exc
        out: dict[str, list[tuple[str, str]]] = {t: [] for t in tablolar}
        for tablo, kolon, tur in ro_baglanti.sema_satirlari(self.tur, ham):
            if kolon in ALLOWED_COLUMNS.get(tablo, frozenset()):
                out[tablo].append((kolon, tur))
        return out


def sql_lehcesi_satiri(db: Any) -> str:
    """`SQL lehçesi: MySQL / MariaDB (mysql)` — sahte/eski nesnelerde PostgreSQL."""
    tur = getattr(db, "tur", None)
    if tur not in ro_baglanti.SQLGLOT_LEHCE:
        tur = "postgresql"
    return f"SQL lehçesi: {ro_baglanti.ETIKETLER[tur]} ({ro_baglanti.SQLGLOT_LEHCE[tur]})"


class DataTools:
    """Ajana verilen `db_schema` / `db_query` uygulaması (maskeli, güvenilmeyen blokta)."""

    def __init__(
        self,
        db: DemoDb,
        masker: PiiMasker | None = None,
        *,
        session: MaskingSession | None = None,
    ) -> None:
        """`session` verilirse (asistan: mesaj başına tek oturum, geçitle paylaşılır) sorgu
        başına yeni oturum açılmaz; yer tutucular soru, araç sonuçları ve cevap boyunca tekildir.
        Maskelemenin açık olup olmadığı da o oturumdan okunur."""
        self.db = db
        self.masker = masker or PiiMasker(enabled=False)
        self.session = session

    @property
    def masking(self) -> bool:
        if self.session is not None:
            return bool(self.session.enabled)
        return bool(getattr(self.masker, "enabled", False))

    def db_schema(self, _args: dict[str, Any]) -> str:
        sema = self.db.schema()
        # İlk satır hedef SQL lehçesi (prompt: sorgular bu lehçede yazılır).
        satirlar = [sql_lehcesi_satiri(self.db)]
        satirlar += [
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
            oturum = self.session if self.session is not None else self.masker.new_session()
            maskeli, _ = oturum.mask(metin)
            metin = str(maskeli)
        # Sorgu ve özet veri bloğunun dışında: model kanıta bunları birebir kopyalar.
        return f"query: {res.sql}\nresult_digest: {ozet}\n" + wrap_tool_result("db_query", metin)
