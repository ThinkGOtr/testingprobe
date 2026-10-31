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
  yalnızca `public` (ya da hiç), katalog yok. FROM/JOIN kaynakları yalnızca düz tablo: alt sorgu,
  `LATERAL`, `VALUES`, `UNNEST`, tablo fonksiyonu, `TABLESAMPLE` yok; pencere (`OVER`/`WINDOW`) yok.
- Tablo takma adında kolon listesi yok (`bayi AS b(id, kullanici_adi, ad, …)` kolonları konumla
  yeniden adlandırır: `b.ad` parola_hash'i okurdu); tablo takma adı bir kolon adını gölgeleyemez
  (Postgres kolon bulamazsa adı tüm satır referansına çözer).
- İç SELECT yalnızca WHERE/HAVING koşulunda (IN/EXISTS/ANY); projeksiyonda/FROM'da/ORDER BY'da yok.
- Nitelenmemiş kolon kendi SELECT'inin tablolarındaki izinli bir kolona çözülmeli (örtük dış kapsam
  bağıntısı yok); nitelikli kolon en içteki kapsamdan dışa doğru çözülür.
- En az bir izinli tablo (FROM'suz `SELECT 'x'` yok).
- Kolonlar izinli kolonlardan; `bayi.parola_hash` hiçbir zaman. `*` yalnızca `count(*)` içinde.
  Projeksiyon takma adları (alias) yalnızca üst düzey `ORDER BY` öğesi olarak kullanılabilir
  (Postgres WHERE/GROUP BY/HAVING/JOIN'de adları tablo kolonlarına çözer: `SELECT id AS parola_hash
  FROM bayi WHERE parola_hash LIKE 'a%'` gizli kolonu okur); gizli kolon adını gölgeleyen takma ad
  reddedilir.

Kanıt sorguları (`kanit=True`, doğrulayıcı): sonuç verinin kendisinden gelmeli, sorgu metni değer
uyduramamalı. Sorgu tek tablodan okur (JOIN, virgüllü birleştirme, alt sorgu yok: aksi halde gerçek
kolon değeri başka bir satırın anahtarıyla eşlenip "kanıt" olurdu). Her projeksiyon şunlardan biri:

- düz kolon;
- değeri koruyan dönüşüm: `lower`/`upper`, karakter argümansız `trim`, `CAST(x AS text)`,
  uzunluksuz `varchar`, ölçeksiz `numeric`/`decimal` (iç içe olabilir);
- toplama: `count(*)`, `count([DISTINCT] kolon)`, `min(kolon)`, `max(kolon)`.

Değeri değiştiren (kayıplı) dönüşümler reddedilir: `round` (`round(CAST(deger AS numeric), -3)`
750.00'ı 1000 yapar), `length`, `abs`, `sum`/`avg`, uzunluk/ölçek sınırlı ya da tamsayı/kayan
noktalı/tarih türüne `CAST` (`CAST(deger AS varchar(1))` → "7", `CAST(x AS int)` yuvarlar).
Toplama kullanılan projeksiyonda en fazla **bir** toplama ifadesi olur ve diğer her sütun
`GROUP BY`'da geçen düz kolonu okur (`SELECT min(kod), max(fiyat) FROM urun` farklı satırların
değerlerini "P-001=30.00" diye eşlerdi). Sabit (literal, NULL, TRUE/FALSE),
CASE/COALESCE/CONCAT/aritmetik projeksiyonlar reddedilir (ör. `SELECT anahtar, '500.00' FROM ayar`
gerçek değeri 750.00 iken 500.00 "kanıtı" üretirdi). Koşullarda iki tarafı da
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
_TOPLAMA: tuple[type[exp.Expression], ...] = (exp.Count, exp.Min, exp.Max)
_TUM_TOPLAMA: tuple[type[exp.Expression], ...] = (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)
# Değeri koruyan tekli dönüşümler (round/length/abs kayıplıdır, bilerek yok).
_TEKLI_DONUSUM: tuple[type[exp.Expression], ...] = (exp.Lower, exp.Upper, exp.Trim)
# CAST yalnızca değeri birebir koruyan, parametresiz hedeflere (varchar(1)/numeric(5,0)/int kesmez
# ya da yuvarlar; `char` Postgres'te char(1)'dir).
_KAYIPSIZ_CAST: frozenset[exp.DataType.Type] = frozenset(
    {exp.DataType.Type.TEXT, exp.DataType.Type.VARCHAR, exp.DataType.Type.DECIMAL}
)


# Hiçbir yerde kabul edilmeyen satır kaynakları / yan yollar: LATERAL ve VALUES sorgu metninden
# değer uydurur (`FROM urun, LATERAL (SELECT '500.00' AS deger) x`), TABLESAMPLE/pencere gereksiz.
_YASAK_KAYNAK: tuple[type[exp.Expression], ...] = (
    exp.Lateral,
    exp.Values,
    exp.Unnest,
    exp.TableFromRows,
    exp.TableSample,
    exp.Window,
    exp.Dot,
)

_TUM_KOLON_ADLARI: frozenset[str] = frozenset().union(*ALLOWED_COLUMNS.values()) | GIZLI_KOLONLAR


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

    for node in kok.walk():
        if isinstance(node, _YASAK_KAYNAK):
            raise QueryRejected(
                f"İzin verilmeyen sorgu öğesi: {type(node).__name__} (yalnızca tablo okunur)"
            )

    # Her SELECT'in kendi kapsamı: FROM/JOIN kaynakları yalnızca düz tablo (alt sorgu, LATERAL,
    # VALUES, tablo fonksiyonu yok); takma ad kolon listesi (`bayi AS b(id, …)`) kolonları konumla
    # yeniden adlandırdığı için yasak; tablo takma adı bir kolon adını gölgeleyemez (Postgres kolon
    # bulamazsa adı tüm satır referansına çözer: `SELECT CAST(deger AS TEXT) FROM bayi deger`).
    kapsamlar: dict[int, dict[str, str]] = {}
    tablolar: list[str] = []
    for s in kok.find_all(exp.Select):
        if s is not kok:
            _alt_sorgu_konumu(s)
        kapsam: dict[str, str] = {}
        kaynaklar = [s.args.get("from_") or s.args.get("from")]
        kaynaklar += list(s.args.get("joins") or [])
        for kaynak in kaynaklar:
            if kaynak is None:
                continue
            tablo = kaynak.this
            if not isinstance(tablo, exp.Table):
                raise QueryRejected("FROM/JOIN yalnızca izinli tabloları okuyabilir")
            ad = _tablo_adi(tablo)
            tablolar.append(ad)
            takma_ad = tablo.args.get("alias")
            if takma_ad is not None and takma_ad.args.get("columns"):
                raise QueryRejected("Tablo takma adında kolon listesi kullanılamaz")
            if tablo.alias:
                ta = tablo.alias.lower()
                if ta in _TUM_KOLON_ADLARI or (ta in ALLOWED_COLUMNS and ta != ad):
                    raise QueryRejected(f"Tablo takma adı bir kolon/tablo adını gölgeleyemez: {ta}")
                kapsam[ta] = ad
            else:
                kapsam[ad] = ad
        kapsamlar[id(s)] = kapsam
    for tablo in kok.find_all(exp.Table):
        # Kapsam dışında kalan tablo (ör. bir ifadenin içinde) olamaz; yine de adı denetlenir.
        _tablo_adi(tablo)

    if not tablolar:
        raise QueryRejected("Sorgu en az bir izinli tabloyu okumalı (FROM gerekli)")

    for s in kok.find_all(exp.Select):
        for e in s.expressions:
            if e.alias and e.alias.lower() in GIZLI_KOLONLAR:
                raise QueryRejected(f"İzin verilmeyen takma ad: {e.alias}")
    # Takma adlar yalnızca üst düzey ORDER BY öğesinde (Postgres orada çıktı adını önce çözer).
    projeksiyon_adlari = {e.alias.lower() for e in kok.expressions if e.alias}
    for star in kok.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise QueryRejected("'*' kullanılamaz; kolonları açıkça yazın")
    for kolon in kok.find_all(exp.Column):
        if isinstance(kolon.this, exp.Star):
            raise QueryRejected("'*' kullanılamaz; kolonları açıkça yazın")
        if kolon.args.get("db") is not None or kolon.args.get("catalog") is not None:
            raise QueryRejected("Kolon şema/katalog ile nitelenemez; tablo takma adı kullanın")
        ad = kolon.name.lower()
        zincir = _kapsam_zinciri(kolon, kapsamlar)
        niteleyici = kolon.table.lower() if kolon.table else ""
        if niteleyici:
            # Nitelikli ad: en içteki kapsamdan dışa doğru (Postgres'in çözüm sırası).
            hedef = next((k[niteleyici] for k in zincir if niteleyici in k), None)
            if hedef is None:
                raise QueryRejected(f"Bilinmeyen tablo niteleyicisi: {kolon.table}")
            if ad not in ALLOWED_COLUMNS[hedef]:
                raise QueryRejected(f"İzin verilmeyen kolon: {hedef}.{ad}")
            continue
        if ad in projeksiyon_adlari and _ust_duzey_siralama(kolon, kok):
            continue
        # Nitelenmemiş ad yalnızca KENDİ SELECT'inin tablolarına çözülmeli (örtük dış kapsam
        # bağıntısı yok: başka tablodaki aynı adlı kolon ya da tüm satır referansı okunamaz).
        kendi = zincir[0] if zincir else {}
        if not any(ad in ALLOWED_COLUMNS[t] for t in kendi.values()):
            raise QueryRejected(f"İzin verilmeyen ya da bilinmeyen kolon: {ad}")

    if kanit:
        _kanit_kurallari(kok)

    return ValidatedQuery(
        kok.sql(dialect="postgres", comments=False), tuple(dict.fromkeys(tablolar))
    )


def _tablo_adi(tablo: exp.Table) -> str:
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
    return ad


def _alt_sorgu_konumu(s: exp.Select) -> None:
    """İç SELECT yalnızca dış SELECT'in WHERE/HAVING koşulunda (IN/EXISTS/ANY/karşılaştırma)
    olabilir; projeksiyonda, FROM/JOIN'de, ORDER BY'da ya da LATERAL içinde olamaz."""
    ust = s.parent
    if not isinstance(ust, exp.Subquery | exp.Exists):
        raise QueryRejected("Alt sorgu yalnızca WHERE/HAVING koşulunda kullanılabilir")
    node = ust.parent
    while node is not None and not isinstance(node, exp.Select):
        if isinstance(node, exp.Where | exp.Having):
            return
        node = node.parent
    raise QueryRejected("Alt sorgu yalnızca WHERE/HAVING koşulunda kullanılabilir")


def _kapsam_zinciri(
    node: exp.Expression, kapsamlar: dict[int, dict[str, str]]
) -> list[dict[str, str]]:
    """Düğümün içinde bulunduğu SELECT'ten köke doğru kapsamlar (en içteki önce)."""
    out: list[dict[str, str]] = []
    p = node.parent
    while p is not None:
        if isinstance(p, exp.Select):
            out.append(kapsamlar.get(id(p), {}))
        p = p.parent
    return out


def _ust_duzey_siralama(kolon: exp.Column, kok: exp.Select) -> bool:
    """Kolon, üst düzey SELECT'in ORDER BY öğesinin kendisi mi (ifade içinde değil)?"""
    sirali = kolon.parent
    return (
        isinstance(sirali, exp.Ordered)
        and sirali.this is kolon
        and isinstance(sirali.parent, exp.Order)
        and sirali.parent.parent is kok
    )


def _duz_kolon(e: exp.Expression) -> bool:
    while isinstance(e, exp.Paren):
        e = e.this
    return isinstance(e, exp.Column) and not isinstance(e.this, exp.Star)


def _kolondan(e: exp.Expression) -> bool:
    """Projeksiyon değeri yalnızca okunan veriden, değiştirilmeden mi geliyor (sorgu metni değer
    uyduramaz, kayıplı dönüşümle değer kaydıramaz)?"""
    if isinstance(e, exp.Alias | exp.Paren):
        return _kolondan(e.this)
    if isinstance(e, exp.Column):
        return not isinstance(e.this, exp.Star)
    if isinstance(e, _TOPLAMA):
        arg = e.this
        if isinstance(e, exp.Count) and isinstance(arg, exp.Star):
            return True
        if isinstance(e, exp.Count) and isinstance(arg, exp.Distinct):
            return len(arg.expressions) == 1 and _duz_kolon(arg.expressions[0])
        return arg is not None and _duz_kolon(arg)
    if isinstance(e, exp.Cast):
        hedef = e.args.get("to")
        if (
            not isinstance(hedef, exp.DataType)
            or hedef.this not in _KAYIPSIZ_CAST
            or hedef.expressions
            or e.args.get("format") is not None
        ):
            return False
        return e.this is not None and not _toplama_var(e.this) and _kolondan(e.this)
    if isinstance(e, _TEKLI_DONUSUM):
        if e.this is None or _toplama_var(e.this) or not _kolondan(e.this):
            return False
        # Yalnızca birincil argüman: trim(x, '0') / trim(both '0' from x) değeri kırpar.
        return all(
            deger in (None, False, [], "") for anahtar, deger in e.args.items() if anahtar != "this"
        )
    return False


def _toplama_var(e: exp.Expression) -> bool:
    return isinstance(e, _TUM_TOPLAMA) or any(True for _ in e.find_all(*_TUM_TOPLAMA))


def _cekirdek(e: exp.Expression) -> exp.Expression:
    while isinstance(e, exp.Alias | exp.Paren):
        e = e.this
    return e


def _toplama_eslesmesi(kok: exp.Select) -> None:
    """Toplama kullanan projeksiyon: en fazla bir toplama; diğer sütunlar yalnızca GROUP BY'daki
    düz kolonları (ya da onların değer koruyan dönüşümlerini) okur.

    Aksi halde bağımsız toplamalar farklı satırların değerlerini tek satırda eşler
    (`SELECT min(kod), max(fiyat) FROM urun` → "P-001=30.00"; P-001 25.00).
    """
    projeksiyon = [_cekirdek(e) for e in kok.expressions]
    toplamali = [e for e in projeksiyon if _toplama_var(e)]
    if not toplamali:
        return
    if len(toplamali) > 1:
        raise QueryRejected(
            "Kanıt sorgusunda en fazla bir toplama ifadesi olabilir (bağımsız toplamalar farklı "
            "satırların değerlerini eşler)"
        )
    grup = kok.args.get("group")
    grup_kolonlari: set[str] = set()
    for g in grup.expressions if grup is not None else []:
        g = _cekirdek(g)
        if isinstance(g, exp.Literal) and not g.is_string:
            # GROUP BY 1: projeksiyon sırası.
            try:
                g = projeksiyon[int(g.this) - 1]
            except (ValueError, IndexError):
                continue
        if _duz_kolon(g):
            grup_kolonlari.add(_cekirdek(g).name.lower())
    for e in projeksiyon:
        if e is toplamali[0]:
            continue
        kolonlar = [c.name.lower() for c in e.find_all(exp.Column)]
        if not kolonlar or any(k not in grup_kolonlari for k in kolonlar):
            raise QueryRejected(
                "Toplamalı kanıt sorgusunda diğer sütunlar yalnızca GROUP BY'daki düz kolonları "
                f"okumalı: {e.sql(dialect='postgres')[:120]}"
            )


def _sabit(e: exp.Expression | None) -> bool:
    return e is not None and not any(True for _ in e.find_all(exp.Column))


def _kanit_kurallari(kok: exp.Select) -> None:
    # Tek tablo, tek kapsam: birleştirme (virgüllü dahil) ve alt sorgu yok. Aksi halde projeksiyon
    # "bir kolondan" gelse de değer başka satırla eşlenebilir (`SELECT a.anahtar, u.fiyat FROM
    # ayar a, urun u WHERE a.anahtar = 'min_siparis_tutari'` → "min_siparis_tutari=30.00").
    if any(s is not kok for s in kok.find_all(exp.Select)):
        raise QueryRejected("Kanıt sorgusunda alt sorgu kullanılamaz")
    if kok.args.get("joins") or any(True for _ in kok.find_all(exp.Join)):
        raise QueryRejected("Kanıt sorgusu tek tablodan okumalı (JOIN/virgüllü birleştirme yok)")
    if len(list(kok.find_all(exp.Table))) != 1:
        raise QueryRejected("Kanıt sorgusu tam olarak bir tablodan okumalı")
    for e in kok.expressions:
        if not _kolondan(e):
            raise QueryRejected(
                "Kanıt sorgusunda her sütun tablodan değiştirilmeden okunmalı (sabit/CASE/COALESCE/"
                "aritmetik ya da round/length/abs/sum/avg/kısıtlı CAST gibi kayıplı projeksiyon "
                f"kanıt olamaz): {e.sql(dialect='postgres')[:120]}"
            )
    _toplama_eslesmesi(kok)
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
