"""Eşlemenin deterministik kontrolleri (TEKNIK-TASARIM §8.4 adım 3; Constitution IV, V, XI).

Ajanın `step_mapping` / `expects` çıktısı koda dönüşmeden önce:

1. Model `missing_methods` bildirdiyse durulur ("page object'te eksik metot" → mühendis).
2. Case'in her adımı eşlenmiş (ya da eksik metot olarak bildirilmiş) ve uygulamada doğrulanmış
   (`verified=true`) olmalı; case'te olmayan adım kimliği reddedilir. Eşleme case'in adım
   sırasını izlemeli (art arda tekrarlar tek adım sayılır): sırası bozuk, bir adımı başka adımdan
   sonra yeniden açan ya da aynı çağrıyı art arda yineleyen eşleme reddedilir; adım başına en çok
   `MAX_ADIM_CAGRI` çağrı.
3. Her `po.method` sembol tablosunda olmalı; adım eşlemeleri `kind=action`, doğrulamalar
   `kind=expect` metot kullanır (assertion adım eşlemesinin içine gizlenemez); argüman sayısı ve
   türleri imzaya uymalı (`string` ↔ metin, `number` ↔ sayı, `boolean` ↔ mantıksal).
4. En az bir doğrulama olmalı (doğrulamasız test hiçbir şey yakalamaz).
5. Her doğrulama argümanı onaylı case'in beklenen metninde (`steps[].expected`,
   `expected_result`) **literal** geçmeli (normalize edilerek: `1.250,00 TL` ≡ `1250`); adım
   argümanları case metninin herhangi bir yerinde (başlık, ön koşul, eylem, veri, beklenen)
   geçmeli. Kaynaksız değer → insan ("kaynağı olmayan beklenen değer"). Doğrulamanın metin
   (string) değeri ayrıca case'teki yazımla **aynen** geçmeli (`150 TL` ≠ `150,00 TL`): doğrulama
   metotları birebir metin karşılaştırır; biçim farkı aksi halde sahte "defect adayı" üretir.

Biri tutmazsa kod üretilmez; neden Türkçe ve adım kimliğiyle insana gösterilir.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from tp_core.features.codegen.normalize import find_exact_source, find_source

IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
# Engel türleri: öncelik sırasıyla (ilk görülen tür script'in engel_turu olur).
ONCELIK = ("missing_method", "unknown_method", "unverified_step", "unsourced_value")
MAX_ADIM_CAGRI = 6  # tek case adımına eşlenebilecek en çok page object çağrısı


@dataclass(frozen=True)
class Bulgu:
    tur: str
    mesaj: str
    step_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"tur": self.tur, "mesaj": self.mesaj, "step_id": self.step_id}


@dataclass
class Sonuc:
    bulgular: list[Bulgu] = field(default_factory=list)
    # expects sırasıyla: her doğrulamanın değerlerinin kaynak metni (portal "kaynak_metin").
    kaynaklar: list[str | None] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.bulgular

    @property
    def engel_turu(self) -> str | None:
        turler = {b.tur for b in self.bulgular}
        return next((t for t in ONCELIK if t in turler), None)

    def ozet(self) -> str:
        return "; ".join(b.mesaj for b in self.bulgular[:10]) + (
            f" (+{len(self.bulgular) - 10})" if len(self.bulgular) > 10 else ""
        )


class SymbolTable:
    """toolchain-worker `/symbols` çıktısı üstünde arama."""

    def __init__(self, table: Mapping[str, Any]) -> None:
        self.raw = dict(table)
        self.sha: str | None = table.get("sha")
        self._methods: dict[tuple[str, str], Mapping[str, Any]] = {}
        self.classes: dict[str, Mapping[str, Any]] = {}
        for po in table.get("page_objects") or []:
            cls = po.get("class")
            if not isinstance(cls, str):
                continue
            self.classes[cls] = po
            for m in po.get("methods") or []:
                if isinstance(m.get("name"), str):
                    self._methods[(cls, m["name"])] = m

    def method(self, po: str, name: str) -> Mapping[str, Any] | None:
        return self._methods.get((po, name))

    def locators(self) -> dict[str, Mapping[str, Any]]:
        """Tüm sınıfların locator anahtarları (`login.submit` → {testId, prefix, within, …})."""
        out: dict[str, Mapping[str, Any]] = {}
        for po in self.classes.values():
            for k, v in (po.get("locators") or {}).items():
                if isinstance(k, str) and isinstance(v, Mapping):
                    out.setdefault(k, v)
        return out

    def for_prompt(self) -> list[dict[str, Any]]:
        """Modele giden sade tablo: sınıf, metot imzaları, locator niyetleri (yol/satır yok)."""
        out = []
        for cls, po in sorted(self.classes.items()):
            out.append(
                {
                    "class": cls,
                    "doc": po.get("doc"),
                    "methods": [
                        {
                            "name": m.get("name"),
                            "kind": m.get("kind"),
                            "params": [
                                {"name": p.get("name"), "type": p.get("type")}
                                for p in m.get("params") or []
                            ],
                            "returns": m.get("returns"),
                            "doc": m.get("doc"),
                        }
                        for m in po.get("methods") or []
                    ],
                    "locators": {
                        k: {
                            kk: v.get(kk)
                            for kk in ("testId", "role", "name", "intent", "within")
                            if v.get(kk) is not None
                        }
                        for k, v in sorted((po.get("locators") or {}).items())
                    },
                }
            )
        return out


def fixture_name(po_class: str) -> str:
    """Page object sınıfının e2e fikstür adı (`CartPage` → `cartPage`)."""
    return po_class[:1].lower() + po_class[1:]


INT_MIN, INT_MAX = -(2**31), 2**31 - 1
LONG_MIN, LONG_MAX = -(2**63), 2**63 - 1


def _tamsayi(deger: Any) -> bool:
    return isinstance(deger, int) and not isinstance(deger, bool)


def _tur_uyar(tip: str, deger: Any) -> bool | None:
    """True/False: tür uyumu; None: desteklenmeyen parametre türü.

    TypeScript (`string`/`number`/`boolean`) ve Java (009 §2.8: `String`/`int`/`long`/`double`/
    `boolean`) türleri. Java literal uyumu `java-araclar guard` ile aynıdır: `int` yalnız 32 bit
    tamsayı, `long` 64 bit tamsayı, `double` sonlu sayı (tamsayı genişletilir); kesirli değer `int`/
    `long`'a, sayı `String`'e geçmez.
    """
    t = (tip or "").strip()
    if t in ("string", "String"):
        return isinstance(deger, str)
    if t == "number":
        return isinstance(deger, int | float) and not isinstance(deger, bool)
    if t == "boolean":
        return isinstance(deger, bool)
    if t == "int":
        return _tamsayi(deger) and INT_MIN <= deger <= INT_MAX
    if t == "long":
        return _tamsayi(deger) and LONG_MIN <= deger <= LONG_MAX
    if t == "double":
        if _tamsayi(deger):
            return LONG_MIN <= deger <= LONG_MAX
        return isinstance(deger, float) and math.isfinite(deger)
    return None


def _imza(
    table: SymbolTable,
    po: str,
    method: str,
    args: Sequence[Any],
    kind: str,
    yer: str,
    sid: str | None,
) -> list[Bulgu]:
    if not (IDENT_RE.match(po or "") and IDENT_RE.match(method or "")):
        return [Bulgu("unknown_method", f"{yer}: geçersiz ad {po}.{method}", sid)]
    m = table.method(po, method)
    if m is None:
        return [
            Bulgu(
                "unknown_method",
                f"{yer}: {po}.{method} page object kütüphanesinde yok (eksik metot)",
                sid,
            )
        ]
    out: list[Bulgu] = []
    if m.get("kind") != kind:
        beklenen = "eylem (action)" if kind == "action" else "doğrulama (expect*)"
        out.append(
            Bulgu("unknown_method", f"{yer}: {po}.{method} bir {beklenen} metodu değil", sid)
        )
    params = list(m.get("params") or [])
    zorunlu = sum(1 for p in params if not p.get("optional") and "default" not in p)
    if not (zorunlu <= len(args) <= len(params)):
        out.append(
            Bulgu(
                "unknown_method",
                f"{yer}: {po}.{method} {zorunlu}"
                + (f"–{len(params)}" if len(params) != zorunlu else "")
                + f" argüman bekler, {len(args)} verildi",
                sid,
            )
        )
        return out
    for p, a in zip(params, args, strict=False):
        uyum = _tur_uyar(str(p.get("type")), a)
        if uyum is None:
            out.append(
                Bulgu(
                    "unknown_method",
                    f"{yer}: {po}.{method}({p.get('name')}) parametre türü desteklenmiyor: "
                    f"{p.get('type')}",
                    sid,
                )
            )
        elif not uyum:
            out.append(
                Bulgu(
                    "unknown_method",
                    f"{yer}: {po}.{method}({p.get('name')}: {p.get('type')}) için tür uyumsuz "
                    f"değer: {a!r}",
                    sid,
                )
            )
    return out


def case_texts(case: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """(beklenen metinleri, tüm case metinleri)."""
    steps = [s for s in case.get("steps") or [] if isinstance(s, Mapping)]
    beklenen = [str(s.get("expected") or "") for s in steps]
    beklenen.append(str(case.get("expected_result") or ""))
    tum = [str(case.get("title") or ""), *(str(p) for p in case.get("preconditions") or [])]
    for s in steps:
        tum += [str(s.get("action") or ""), str(s.get("data") or ""), str(s.get("expected") or "")]
    tum.append(str(case.get("expected_result") or ""))
    return [t for t in beklenen if t], [t for t in tum if t]


def _sira_bulgulari(eslemeler: Sequence[Mapping[str, Any]], adimlar: Sequence[str]) -> list[Bulgu]:
    """Eşleme onaylı case'in adım sırasını izlemeli; adım tekrar açılamaz, çağrı tekrarlanamaz.

    Şablon çağrıları eşleme sırasıyla basar ve adım kimliği değiştikçe yeni adım grubu açar:
    sırası bozuk, araya başka adım giren ya da aynı çağrıyı iki kez yapan eşleme onaylı case'ten
    farklı bir test üretir. Böyle bir testin assertion hatası "defect adayı" değil modelin eşleme
    hatasıdır; bu yüzden kod üretilmeden insana gider.
    """
    out: list[Bulgu] = []
    sira = {sid: i for i, sid in enumerate(adimlar)}
    gruplar: list[str] = []
    onceki: tuple[Any, ...] | None = None
    adim_cagri: dict[str, int] = {}
    for m in eslemeler:
        sid = str(m.get("step_id"))
        cagri = (sid, str(m.get("po")), str(m.get("method")), repr(list(m.get("args") or [])))
        if cagri == onceki:
            out.append(
                Bulgu(
                    "unverified_step",
                    f"{sid}: {cagri[1]}.{cagri[2]} aynı argümanlarla art arda iki kez eşlenmiş "
                    "(onaylı case'te tek eylem)",
                    sid,
                )
            )
        onceki = cagri
        adim_cagri[sid] = adim_cagri.get(sid, 0) + 1
        if not gruplar or gruplar[-1] != sid:
            gruplar.append(sid)
    for sid, n in adim_cagri.items():
        if n > MAX_ADIM_CAGRI:
            out.append(
                Bulgu(
                    "unverified_step",
                    f"{sid}: tek adıma {n} çağrı eşlenmiş (en çok {MAX_ADIM_CAGRI})",
                    sid,
                )
            )
    gorulen: set[str] = set()
    for sid in gruplar:
        if sid in gorulen:
            out.append(
                Bulgu(
                    "unverified_step",
                    f"{sid}: adım başka bir adımdan sonra yeniden eşlenmiş (araya giren adım)",
                    sid,
                )
            )
        gorulen.add(sid)
    bilinen = [sid for sid in dict.fromkeys(gruplar) if sid in sira]
    if bilinen != sorted(bilinen, key=sira.__getitem__):
        out.append(
            Bulgu(
                "unverified_step",
                "eşleme sırası onaylı case'in adım sırasına uymuyor ("
                + " → ".join(bilinen)
                + "; beklenen "
                + " → ".join(sorted(bilinen, key=sira.__getitem__))
                + ")",
            )
        )
    return out


def check_mapping(
    output: Mapping[str, Any],
    case: Mapping[str, Any],
    table: SymbolTable,
    *,
    fixtures: set[str] | None = None,
    fixture_kaynagi: str = "tests/fixtures.ts",
) -> Sonuc:
    sonuc = Sonuc()
    b = sonuc.bulgular
    adimlar = [str(s.get("id")) for s in case.get("steps") or [] if isinstance(s, Mapping)]
    eslemeler = [m for m in output.get("step_mapping") or [] if isinstance(m, Mapping)]
    expects = [e for e in output.get("expects") or [] if isinstance(e, Mapping)]
    eksikler = [e for e in output.get("missing_methods") or [] if isinstance(e, Mapping)]

    for e in eksikler:
        b.append(
            Bulgu(
                "missing_method",
                f"{e.get('step_id')}: page object'te eksik metot — {e.get('reason')}",
                str(e.get("step_id")),
            )
        )
    eksik_adim = {str(e.get("step_id")) for e in eksikler}
    eslenen = {str(m.get("step_id")) for m in eslemeler}
    for sid in adimlar:
        if sid not in eslenen and sid not in eksik_adim:
            b.append(Bulgu("unverified_step", f"{sid}: adım eşlenmedi", sid))
    for sid in sorted((eslenen | eksik_adim) - set(adimlar)):
        b.append(Bulgu("unverified_step", f"{sid}: case'te böyle bir adım yok", sid))
    b.extend(_sira_bulgulari(eslemeler, adimlar))

    _beklenen_metin, tum_metin = case_texts(case)
    kullanilan: set[str] = set()
    for m in eslemeler:
        sid = str(m.get("step_id"))
        po, method, args = str(m.get("po")), str(m.get("method")), list(m.get("args") or [])
        if sid in eksik_adim:
            continue  # zaten "eksik metot" olarak insana gidiyor
        if not m.get("verified"):
            b.append(
                Bulgu(
                    "unverified_step",
                    f"{sid}: adım uygulamada doğrulanmadı (verified=false); eşleme kabul edilmez",
                    sid,
                )
            )
        b.extend(_imza(table, po, method, args, "action", sid, sid))
        kullanilan.add(po)
        for a in args:
            if find_source(a, tum_metin) is None:
                b.append(
                    Bulgu(
                        "unsourced_value",
                        f"{sid}: {po}.{method} girdisi {a!r} onaylı case metninde yok",
                        sid,
                    )
                )

    if not expects and not eksikler:
        b.append(Bulgu("unsourced_value", "doğrulama (expect) yok: test hiçbir sonucu denetlemez"))
    for i, e in enumerate(expects, start=1):
        po, method, args = str(e.get("po")), str(e.get("method")), list(e.get("args") or [])
        yer = f"Doğrulama {i}"
        b.extend(_imza(table, po, method, args, "expect", yer, None))
        kullanilan.add(po)
        kaynak: str | None = None
        for a in args:
            k = find_source(a, _beklenen_metin)
            if k is None:
                b.append(
                    Bulgu(
                        "unsourced_value",
                        f"{yer}: {po}.{method} beklenen değeri {a!r} onaylı case'in beklenen "
                        "sonuç metninde yok (kaynağı olmayan beklenen değer)",
                    )
                )
            elif find_exact_source(a, _beklenen_metin) is None:
                b.append(
                    Bulgu(
                        "unsourced_value",
                        f"{yer}: {po}.{method} beklenen değeri {a!r} case'teki yazımla aynı "
                        f"değil (case: {k[:120]!r}); doğrulama birebir metin karşılaştırır, "
                        "değer case'teki biçimiyle yazılmalı",
                    )
                )
            kaynak = kaynak or k
        sonuc.kaynaklar.append(kaynak)

    if fixtures is not None:
        for po in sorted(kullanilan):
            if table.classes.get(po) is not None and fixture_name(po) not in fixtures:
                b.append(
                    Bulgu(
                        "unknown_method",
                        f"{po} için e2e fikstürü ({fixture_name(po)}) {fixture_kaynagi} içinde yok",
                    )
                )
    return sonuc


_FIXTURE_RE = re.compile(r"^\s{2}([A-Za-z_$][A-Za-z0-9_$]*)\s*:", re.MULTILINE)


def fixtures_in(source: str) -> set[str]:
    """`tests/fixtures.ts` `interface Fixtures { … }` alan adları (sözdizimsel; çalıştırılmaz)."""
    m = re.search(r"interface\s+Fixtures\s*\{(?P<govde>[^}]*)\}", source)
    if m is None:
        return set()
    return set(_FIXTURE_RE.findall(m.group("govde")))
