"""`db_query` için SQL koruması (TEKNIK-TASARIM §8.2b, Constitution: "Genel amaçlı SQL çalıştıran
araç kullanılmaz").

Sorgu `sqlglot` ile Postgres lehçesinde ayrıştırılır; çalıştırılan metin ayrıştırılmış ağaçtan
yeniden üretilir (yorumlar ve ikinci ifadeler gitmez). Kabul kuralları (izin listesi):

- Tam olarak **bir** ifade ve kökü `SELECT` (UNION/INTERSECT/EXCEPT, DML, DDL, komut yok).
- `WITH` (CTE) yok — DML içeren CTE dahil hiçbir CTE kabul edilmez.
- `SELECT … INTO` yok; kilitleme (`FOR UPDATE/SHARE …`) yok.
- Fonksiyonlar yalnızca `ALLOWED_FUNCTIONS` sınıflarından (toplama, metin, tür dönüşümü, CASE);
  `pg_sleep`, `pg_read_file`, `dblink`, `set_config`, `current_setting`, tablo fonksiyonları vb.
  bilinmeyen her fonksiyon (`Anonymous`) reddedilir.
- Tablolar yalnızca `ALLOWED_COLUMNS` anahtarları (`urun`, `kampanya`, `ayar`, `bayi`); şema
  yalnızca `public` (ya da hiç), katalog yok; FROM'da alt sorgu/tablo fonksiyonu yok.
- En az bir izinli tablo (FROM'suz `SELECT 'x'` yok).
- Kolonlar izinli kolonlardan; `bayi.parola_hash` hiçbir zaman. `*` yalnızca `count(*)` içinde.
  Projeksiyon takma adları (alias) yalnızca üst düzey `ORDER BY` öğesi olarak kullanılabilir
  (Postgres WHERE/GROUP BY/HAVING/JOIN'de adları tablo kolonlarına çözer: `SELECT id AS parola_hash
  FROM bayi WHERE parola_hash LIKE 'a%'` gizli kolonu okur); gizli kolon adını gölgeleyen takma ad
  reddedilir.

Kanıt sorguları (`kanit=True`, doğrulayıcı): sonuç verinin kendisinden gelmeli, sorgu metni değer
uyduramamalı. Her projeksiyon bir kolon, kolon/`*` üzerinde toplama ya da kolon üzerinde tekli
dönüşüm (`lower`, `upper`, `trim`, `length`, `abs`, `round`, `cast`) olmalı; sabit (literal, NULL,
TRUE/FALSE), CASE/COALESCE/CONCAT/aritmetik projeksiyonlar reddedilir (ör. `SELECT anahtar,
'500.00' FROM ayar` gerçek değeri 750.00 iken 500.00 "kanıtı" üretirdi). Koşullarda iki tarafı da
sabit karşılaştırma (`1 = 0`) ve çıplak TRUE/FALSE da reddedilir.

Veritabanı tarafında ayrıca: `demoapp_ro` rolü (yalnızca bu tablolara/kolonlara SELECT), salt
okuma işlemi, `statement_timeout` 5 sn; araç en fazla 100 satır döndürür (`datatools`).
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

MAX_SQL_LEN = 2000

ALLOWED_COLUMNS: dict[str, frozenset[str]] = {
    "urun": frozenset({"id", "kod", "ad", "fiyat", "sira", "aktif"}),
    "kampanya": frozenset({"id", "kod", "ad", "urun_id", "aktif"}),
    "ayar": frozenset({"anahtar", "deger", "aciklama"}),
    # parola_hash bilerek yok (kişisel/güvenlik verisi).
    "bayi": frozenset({"id", "kullanici_adi", "ad", "kredi_limiti", "olusturma"}),
}

# Hiçbir sorguda okunamayan kolonlar (ad olarak takma adla gölgelenemez de).
GIZLI_KOLONLAR: frozenset[str] = frozenset({"parola_hash"})

ALLOWED_FUNCTIONS: tuple[type[exp.Expression], ...] = (
    exp.Count,
    exp.Sum,
    exp.Avg,
    exp.Min,
    exp.Max,
    exp.Lower,
    exp.Upper,
    exp.Coalesce,
    exp.Cast,
    exp.Round,
    exp.Length,
    exp.Concat,
    exp.Abs,
    exp.Trim,
    exp.Substring,
    exp.Case,
    exp.If,
)

_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Copy,
    exp.Into,
    exp.Lock,
    exp.With,
    exp.CTE,
    exp.Placeholder,
    exp.Parameter,
)


# Kanıt sorgusunda izinli projeksiyon biçimleri (bkz. modül belgesi).
_TOPLAMA: tuple[type[exp.Expression], ...] = (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)
_TEKLI_DONUSUM: tuple[type[exp.Expression], ...] = (
    exp.Lower,
    exp.Upper,
    exp.Trim,
    exp.Length,
    exp.Abs,
    exp.Round,
    exp.Cast,
)


class QueryRejected(ValueError):
    """Sorgu izin listesine uymuyor; çalıştırılmaz."""


@dataclass(frozen=True)
class ValidatedQuery:
    sql: str  # ayrıştırılmış ağaçtan üretilen, çalıştırılacak metin
    tables: tuple[str, ...]


def validate_select(sql: str, *, kanit: bool = False) -> ValidatedQuery:
    """Sorguyu izin listesine göre doğrular. `kanit=True`: kanıt sorgusu kuralları da uygulanır."""
    if not isinstance(sql, str) or not sql.strip():
        raise QueryRejected("Sorgu boş")
    if len(sql) > MAX_SQL_LEN:
        raise QueryRejected(f"Sorgu çok uzun (en fazla {MAX_SQL_LEN} karakter)")
    try:
        ifadeler = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except (ParseError, sqlglot.errors.TokenError) as exc:
        raise QueryRejected(f"Sorgu ayrıştırılamadı: {str(exc).splitlines()[0][:200]}") from exc
    if len(ifadeler) != 1:
        raise QueryRejected("Tek bir SELECT ifadesi gönderin")
    kok = ifadeler[0]
    if not isinstance(kok, exp.Select):
        raise QueryRejected(f"Yalnızca SELECT çalıştırılır (gelen: {type(kok).__name__})")

    for node in kok.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise QueryRejected(f"İzin verilmeyen sorgu öğesi: {type(node).__name__}")
        if isinstance(node, exp.SetOperation):
            raise QueryRejected("UNION/INTERSECT/EXCEPT desteklenmez")
        if isinstance(node, exp.Select) and (node.args.get("into") or node.args.get("locks")):
            raise QueryRejected("SELECT INTO ve kilitleme yasak")
        # AND/OR (`exp.Connector`) sqlglot'ta `Func` alt sınıfıdır; bağlaçtır, fonksiyon değil.
        if (
            isinstance(node, exp.Func)
            and not isinstance(node, ALLOWED_FUNCTIONS)
            and not isinstance(node, exp.Connector)
        ):
            ad = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
            raise QueryRejected(f"İzin verilmeyen fonksiyon: {ad}")

    takma: dict[str, str] = {}
    tablolar: list[str] = []
    for tablo in kok.find_all(exp.Table):
        if not isinstance(tablo.this, exp.Identifier):
            raise QueryRejected("FROM'da tablo fonksiyonu kullanılamaz")
        ad = tablo.name.lower()
        if tablo.args.get("catalog") is not None:
            raise QueryRejected("Katalog belirtilemez")
        sema = tablo.args.get("db")
        if sema is not None and sema.name.lower() != "public":
            raise QueryRejected(f"İzin verilmeyen şema: {sema.name}")
        if ad not in ALLOWED_COLUMNS:
            raise QueryRejected(
                f"İzin verilmeyen tablo: {ad} (izinli: {', '.join(sorted(ALLOWED_COLUMNS))})"
            )
        tablolar.append(ad)
        takma[ad] = ad
        if tablo.alias:
            takma[tablo.alias.lower()] = ad
    for sub in kok.find_all(exp.Subquery):
        if isinstance(sub.parent, exp.From | exp.Join):
            raise QueryRejected("FROM'da alt sorgu desteklenmez")

    if not tablolar:
        raise QueryRejected("Sorgu en az bir izinli tabloyu okumalı (FROM gerekli)")

    for s in kok.find_all(exp.Select):
        for e in s.expressions:
            if e.alias and e.alias.lower() in GIZLI_KOLONLAR:
                raise QueryRejected(f"İzin verilmeyen takma ad: {e.alias}")
    # Takma adlar yalnızca üst düzey ORDER BY öğesinde (Postgres orada çıktı adını önce çözer).
    projeksiyon_adlari = {e.alias.lower() for e in kok.expressions if e.alias}
    kullanilan = set(tablolar)
    for star in kok.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise QueryRejected("'*' kullanılamaz; kolonları açıkça yazın")
    for kolon in kok.find_all(exp.Column):
        if isinstance(kolon.this, exp.Star):
            raise QueryRejected("'*' kullanılamaz; kolonları açıkça yazın")
        ad = kolon.name.lower()
        niteleyici = kolon.table.lower() if kolon.table else ""
        if niteleyici:
            hedef = takma.get(niteleyici)
            if hedef is None:
                raise QueryRejected(f"Bilinmeyen tablo niteleyicisi: {kolon.table}")
            if ad not in ALLOWED_COLUMNS[hedef]:
                raise QueryRejected(f"İzin verilmeyen kolon: {hedef}.{ad}")
            continue
        if ad in projeksiyon_adlari and _ust_duzey_siralama(kolon, kok):
            continue
        if not any(ad in ALLOWED_COLUMNS[t] for t in kullanilan):
            raise QueryRejected(f"İzin verilmeyen ya da bilinmeyen kolon: {ad}")

    if kanit:
        _kanit_kurallari(kok)

    return ValidatedQuery(
        kok.sql(dialect="postgres", comments=False), tuple(dict.fromkeys(tablolar))
    )


def _ust_duzey_siralama(kolon: exp.Column, kok: exp.Select) -> bool:
    """Kolon, üst düzey SELECT'in ORDER BY öğesinin kendisi mi (ifade içinde değil)?"""
    sirali = kolon.parent
    return (
        isinstance(sirali, exp.Ordered)
        and sirali.this is kolon
        and isinstance(sirali.parent, exp.Order)
        and sirali.parent.parent is kok
    )


def _kolondan(e: exp.Expression) -> bool:
    """Projeksiyon değeri yalnızca okunan veriden mi geliyor (sorgu metni değer uyduramaz)?"""
    if isinstance(e, exp.Alias | exp.Paren):
        return _kolondan(e.this)
    if isinstance(e, exp.Column):
        return not isinstance(e.this, exp.Star)
    if isinstance(e, exp.Distinct):
        return bool(e.expressions) and all(_kolondan(x) for x in e.expressions)
    if isinstance(e, _TOPLAMA):
        arg = e.this
        if isinstance(e, exp.Count) and isinstance(arg, exp.Star):
            return True
        return arg is not None and _kolondan(arg)
    if isinstance(e, _TEKLI_DONUSUM):
        if e.this is None or not _kolondan(e.this):
            return False
        # Yalnızca birincil argüman veri taşıyabilir: round(x, 2) basamak, cast(x AS t) tür.
        for anahtar, deger in e.args.items():
            if anahtar in ("this", "to", "decimals", "safe", "format", "action", "default"):
                continue
            if deger not in (None, False, [], ""):
                return False
        return True
    return False


def _sabit(e: exp.Expression | None) -> bool:
    return e is not None and not any(True for _ in e.find_all(exp.Column))


def _kanit_kurallari(kok: exp.Select) -> None:
    for e in kok.expressions:
        if not _kolondan(e):
            raise QueryRejected(
                "Kanıt sorgusunda her sütun tablodan okunmalı (sabit/CASE/COALESCE/aritmetik "
                f"projeksiyon kanıt olamaz): {e.sql(dialect='postgres')[:120]}"
            )
    for node in kok.walk():
        if isinstance(node, exp.Boolean):
            raise QueryRejected("Kanıt sorgusunda TRUE/FALSE sabiti kullanılamaz")
        if (
            isinstance(node, exp.Predicate)
            and isinstance(node, exp.Binary)
            and not isinstance(node, exp.Connector)
            and _sabit(node.left)
            and _sabit(node.right)
        ):
            raise QueryRejected(
                f"Kanıt sorgusunda sabit koşul kullanılamaz: {node.sql(dialect='postgres')}"
            )
