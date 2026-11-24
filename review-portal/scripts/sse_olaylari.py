"""core'un SSE olay yoluna (`publish_tx` → Postgres NOTIFY → `GET /events`) yayımladığı tüm olay
adlarını kaynaktan toplar, JSON basar.

Neden: portal olayları tarayıcının `EventSource`'u ile alır; adlı SSE olayı (`event: <ad>`) yalnızca
o ad için `addEventListener(ad)` kaydı varsa teslim edilir. `src/api/events.tsx` DINLENEN_OLAYLAR
listesinde olmayan bir ad core'dan çıksa da sayfaya hiç ulaşmaz (2026-11-24 canlı: `case.review` ve
`case.audit` — "Review çalışıyor…" / "Agent Probe'a gönder" yenilemeden bitmedi). Bu liste
portalda `src/api/events.test.ts` ile DINLENEN_OLAYLAR'a karşı, core'da
`tests/unit/test_cross_lane_contracts.py` ile kaynağa karşı denetlenir. Yeniden üretmek:

    npm run sozlesme:sse

(`uv run --project ../core python scripts/sse_olaylari.py > src/api/sozlesme/sse-olaylari.json`)

Toplama kuralları (AST, çalıştırmadan):
- `publish_tx(conn, ad, …)` çağrısının `ad` argümanı sabit metinse, modül sabitine (`OLAY = "…"`,
  `EV_STEP: Final = "…"`; başka modülden içe alınan sabit de) ya da `a if … else b` ifadesine
  çözülüyorsa alınır.
- Adı parametresiyle `publish_tx`'e geçen sarmalayıcılar (`def _olay(session, ad, veri)`)
  kendiliğinden bulunur; çağrı yerlerindeki sabitler toplanır (özel adlı sarmalayıcı yalnız kendi
  dosyasında).
- f-string adlar `SABLONLAR` ile açılır (değer kümeleri core'dan okunur).
Çözülemeyen yeni bir dinamik çağrı hata verir: portala bildirilmeden sessizce kaçmaz.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

AD = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
YAYINCI = "publish_tx"
YAYINCI_SIRASI = 1  # publish_tx(conn, event, data)

# Yayıncıya değişkenle geçen ve SABLONLAR / sarmalayıcı kuralıyla karşılanan çağrılar:
# (dosya, ifade).
BILINEN_DINAMIK = {
    ("events/bus.py", "event"),
    ("workflow/service.py", "f'{kind}.state'"),
}


def _sablonlar() -> set[str]:
    from tp_core.workflow.states import MACHINES

    return {f"{m}.state" for m in MACHINES}


def _sabitler(agac: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in agac.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1:
            hedef, deger = n.targets[0], n.value
        elif isinstance(n, ast.AnnAssign):
            hedef, deger = n.target, n.value
        else:
            continue
        if (
            isinstance(hedef, ast.Name)
            and isinstance(deger, ast.Constant)
            and isinstance(deger.value, str)
        ):
            out[hedef.id] = deger.value
    return out


def _coz(dugum: ast.expr | None, sabit: dict[str, str]) -> list[str] | None:
    if isinstance(dugum, ast.Constant) and isinstance(dugum.value, str):
        return [dugum.value]
    if isinstance(dugum, ast.Name) and dugum.id in sabit:
        return [sabit[dugum.id]]
    if isinstance(dugum, ast.IfExp):
        a, b = _coz(dugum.body, sabit), _coz(dugum.orelse, sabit)
        return a + b if a is not None and b is not None else None
    return None


def _cagri_adi(n: ast.Call) -> str | None:
    return n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)


def _arguman(n: ast.Call, sira: int, anahtar: str | None) -> ast.expr | None:
    if anahtar is not None:
        for k in n.keywords:
            if k.arg == anahtar:
                return k.value
    return n.args[sira] if 0 <= sira < len(n.args) else None


def _sarmalayicilar(goreli: str, agac: ast.Module) -> dict[tuple[str, str], tuple[int, str]]:
    """Adı parametresiyle yayıncıya geçen fonksiyonlar: (dosya|"*", ad) → (sıra, parametre)."""
    out: dict[tuple[str, str], tuple[int, str]] = {}
    for f in ast.walk(agac):
        if not isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        params = [a.arg for a in [*f.args.posonlyargs, *f.args.args]]
        yalniz_anahtar = [a.arg for a in f.args.kwonlyargs]
        for n in ast.walk(f):
            if not (isinstance(n, ast.Call) and _cagri_adi(n) == YAYINCI):
                continue
            arg = _arguman(n, YAYINCI_SIRASI, "event")
            if isinstance(arg, ast.Name) and arg.id in [*params, *yalniz_anahtar]:
                kapsam = goreli if f.name.startswith("_") else "*"
                sira = params.index(arg.id) if arg.id in params else -1
                out[(kapsam, f.name)] = (sira, arg.id)
    return out


def topla(kok: Path) -> tuple[list[str], list[str]]:
    """(olay adları, çözülemeyen çağrılar)."""
    dosyalar = {
        yol.relative_to(kok).as_posix(): ast.parse(yol.read_text(encoding="utf-8"))
        for yol in sorted(kok.rglob("*.py"))
    }
    yerel = {g: _sabitler(a) for g, a in dosyalar.items()}
    # Başka modülden içe alınan sabitler için: adı tek değere çözülen modül sabitleri.
    genel: dict[str, set[str]] = {}
    for s in yerel.values():
        for k, v in s.items():
            genel.setdefault(k, set()).add(v)
    genel_tek = {k: next(iter(v)) for k, v in genel.items() if len(v) == 1}
    sarmalayici: dict[tuple[str, str], tuple[int, str]] = {}
    for g, a in dosyalar.items():
        sarmalayici.update(_sarmalayicilar(g, a))

    adlar: set[str] = set(_sablonlar())
    cozulemeyen: list[str] = []
    for goreli, agac in dosyalar.items():
        sabit = {**genel_tek, **yerel[goreli]}
        for n in ast.walk(agac):
            if not isinstance(n, ast.Call):
                continue
            ad = _cagri_adi(n) or ""
            if ad == YAYINCI:
                kural: tuple[int, str | None] | None = (YAYINCI_SIRASI, "event")
            elif (s := sarmalayici.get((goreli, ad)) or sarmalayici.get(("*", ad))) is not None:
                kural = s
            else:
                continue
            arg = _arguman(n, kural[0], kural[1])
            if arg is None:
                continue
            c = _coz(arg, sabit)
            if c is not None:
                bozuk = [x for x in c if not AD.match(x)]
                if bozuk:
                    cozulemeyen.append(f"{goreli}:{n.lineno} geçersiz ad {bozuk}")
                adlar.update(x for x in c if AD.match(x))
                continue
            ifade = ast.unparse(arg)
            # Sarmalayıcının kendi gövdesindeki parametre geçişi: çağrı yerleri ayrıca toplanır.
            if isinstance(arg, ast.Name) and any(
                v[1] == arg.id and k[0] in (goreli, "*") for k, v in sarmalayici.items()
            ):
                continue
            if (goreli, ifade) not in BILINEN_DINAMIK:
                cozulemeyen.append(f"{goreli}:{n.lineno} {ad}({ifade})")
    return sorted(adlar), cozulemeyen


def main() -> None:
    import tp_core

    adlar, cozulemeyen = topla(Path(tp_core.__file__).parent)
    if cozulemeyen:
        sys.exit(
            "çözülemeyen SSE olayı yayınları (scripts/sse_olaylari.py kurallarına ekleyin):\n"
            + "\n".join(cozulemeyen)
        )
    json.dump(adlar, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
