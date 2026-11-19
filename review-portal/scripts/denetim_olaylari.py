"""core denetim zincirine yazılan tüm olay kodlarını (`audit_event.eylem`) kaynaktan toplar, JSON basar.

Portal Denetim ekranının okunur etiket haritası (`src/lib/kullaniciMetni.ts` OLAY_ETIKETI) bu listeyle
karşılaştırılır (`src/lib/denetimOlaylari.test.ts`); core tarafında `tests/unit/test_cross_lane_contracts.py`
dosyanın güncel olduğunu denetler. Yeniden üretmek:

    npm run sozlesme:denetim

(`uv run --project ../core python scripts/denetim_olaylari.py > src/api/sozlesme/denetim-olaylari.json`)

Toplama kuralları (AST, çalıştırmadan):
- `audit_on_commit(…, eylem, …)` / `append_audit(…, eylem, …)` çağrısının eylem argümanı sabit metinse,
  modül düzeyi sabite (`OLAY = "…"`) ya da `a if … else b` ifadesine çözülüyorsa alınır.
- Herhangi bir çağrıdaki `eylem="…"` anahtar sözcüklü sabit alınır (sarmalayıcıya geçen kodlar).
- Kodu argümanla alan sarmalayıcıların (`SARMALAYICILAR`) çağrı yerlerindeki sabitler şablonla açılır.
- f-string kodlar `SABLONLAR` ile açılır (değer kümeleri core'dan okunur).
Çözülemeyen yeni bir dinamik çağrı hata verir: haritaya eklenmeden sessizce kaçmaz.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

KOD = re.compile(r"[a-z_]+(?:\.[a-z0-9_]+)+")
YAZICILAR = {"audit_on_commit": 2, "append_audit": 2}

# (dosya, fonksiyon) → (eylem argümanının sırası, şablonlar). Şablondaki {} çağrı yerindeki sabittir.
SARMALAYICILAR: dict[tuple[str, str], tuple[int, tuple[str, ...]]] = {
    ("home_config/durum.py", "_denetle"): (0, ("{}",)),
    ("features/cases/deepen.py", "_reddet"): (1, ("{}",)),
    ("features/testveri/kaynak.py", "_denetim"): (2, ("{}",)),
    ("features/testveri/service.py", "_denetim"): (2, ("{}",)),
    ("integrations/agent_probe/denetim.py", "_audit_kaydi"): (0, ("{}",)),
    ("features/karar_tablosu/service.py", "_denetim"): (
        3,
        ("karar_tablosu.{}", "metamorfik_iliski.{}"),
    ),
    ("features/demo/service.py", "_is_iste"): (3, ("demo.{}_requested",)),
}

# Yazıcıya değişkenle geçen ve yukarıdaki kurallarla karşılanan çağrılar: (dosya, ifade).
BILINEN_DINAMIK = {
    ("audit/chain.py", "eylem"),
    ("audit/session.py", "eylem"),
    ("home_config/durum.py", "eylem"),
    ("features/cases/review.py", "eylem"),
    ("features/cases/deepen.py", "eylem"),
    ("features/testveri/kaynak.py", "eylem"),
    ("features/testveri/service.py", "eylem"),
    ("integrations/agent_probe/denetim.py", "eylem"),
    ("api/routers/aiprobe.py", "eylem"),
    ("features/karar_tablosu/service.py", "f'{tur}.{fiil}'"),
    ("features/demo/service.py", "f'demo.{eylem}_requested'"),
    ("workflow/service.py", "f'review.{karar}'"),
    ("workflow/service.py", "f'{kind}.transition'"),
    ("features/codegen/kurulum_pr.py", "f\"musteri_ci.kurulum_pr_{sonuc['durum']}\""),
}


def _sablonlar() -> set[str]:
    from tp_core.workflow.states import KARARLAR, MACHINES

    out = {f"review.{k}" for v in KARARLAR.values() for k in v}
    out |= {f"{m}.transition" for m in MACHINES}
    out |= {"musteri_ci.kurulum_pr_acildi", "musteri_ci.kurulum_pr_mevcut"}
    return out


def _sabitler(agac: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in agac.body:
        hedef = (
            n.targets[0]
            if isinstance(n, ast.Assign) and len(n.targets) == 1
            else getattr(n, "target", None)
        )
        deger = getattr(n, "value", None)
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


def topla(kok: Path) -> tuple[list[str], list[str]]:
    """(olay kodları, çözülemeyen çağrılar)."""
    kodlar: set[str] = set(_sablonlar())
    cozulemeyen: list[str] = []
    for yol in sorted(kok.rglob("*.py")):
        goreli = yol.relative_to(kok).as_posix()
        agac = ast.parse(yol.read_text(encoding="utf-8"))
        sabit = _sabitler(agac)
        for n in ast.walk(agac):
            if not isinstance(n, ast.Call):
                continue
            ad = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
            for k in n.keywords:
                if k.arg == "eylem" and (c := _coz(k.value, sabit)) is not None:
                    kodlar.update(x for x in c if KOD.fullmatch(x))
            if ad in YAZICILAR:
                arg = next((k.value for k in n.keywords if k.arg == "eylem"), None)
                if arg is None and len(n.args) > YAZICILAR[ad]:
                    arg = n.args[YAZICILAR[ad]]
                c = _coz(arg, sabit)
                if c is not None:
                    kodlar.update(c)
                elif (goreli, ast.unparse(arg) if arg is not None else "") not in BILINEN_DINAMIK:
                    cozulemeyen.append(
                        f"{goreli}:{n.lineno} {ast.unparse(arg) if arg is not None else '?'}"
                    )
            sar = SARMALAYICILAR.get((goreli, ad or ""))
            if sar is not None and len(n.args) > sar[0]:
                c = _coz(n.args[sar[0]], sabit)
                if c is None:
                    cozulemeyen.append(f"{goreli}:{n.lineno} {ad}({ast.unparse(n.args[sar[0]])})")
                else:
                    kodlar.update(s.format(x) for x in c for s in sar[1])
    return sorted(kodlar), cozulemeyen


def main() -> None:
    import tp_core

    kodlar, cozulemeyen = topla(Path(tp_core.__file__).parent)
    if cozulemeyen:
        sys.exit(
            "çözülemeyen denetim olayı çağrıları (scripts/denetim_olaylari.py kurallarına ekleyin):\n"
            + "\n".join(cozulemeyen)
        )
    json.dump(kodlar, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
