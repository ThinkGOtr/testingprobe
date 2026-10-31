"""Portal örnek verisinin bağlayıcı kaynaklarını tek JSON olarak basar.

Kaynaklar (docs/DEMO-VERISI.md):
- sims/jira-sim/src/jira_sim/seed.py: TPD-1..TPD-4 başlık, açıklama paragrafı, kabul kriterleri
  (bağımlılık kurmadan `ast` ile okunur; seed.py çalıştırılmaz).
- rules/replay/requirement_review/golden/*.json → output (ön inceleme soruları, verdict).
- rules/replay/consistency_check/golden/*.json → output (tutarlılık bulguları).
- rules/replay/consistency_check/golden/SERBEST.json → input_match (serbest metin golden'ının girdisi).
- rules/replay/case_generation/golden/*.json → input_match AC'leri + output.cases.

Portal imajı yalnızca review-portal/ ile derlendiği için çıktı depoda tutulur
(src/api/mock/golden/kaynaklar.json); fixtures.test.ts güncelliğini denetler. Yeniden üretmek:

    npm run sozlesme:golden
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

KOK = Path(__file__).resolve().parents[2]
SEED = KOK / "sims/jira-sim/src/jira_sim/seed.py"
REPLAY = KOK / "rules/replay"
STORYLER = ("TPD-1", "TPD-2", "TPD-3", "TPD-4")
AC_RE = re.compile(r"^(AC\d+):\s*(.*)$", re.S)


def _ac(metin: str) -> dict[str, str]:
    m = AC_RE.match(metin)
    if not m:
        raise SystemExit(f"seed.py: kabul kriteri 'ACn: ...' biçiminde değil: {metin!r}")
    return {"ref": m.group(1), "metin": m.group(2)}


def jira_seed() -> dict[str, Any]:
    agac = ast.parse(SEED.read_text(encoding="utf-8"))
    sabitler: dict[str, Any] = {}
    for dugum in agac.body:
        hedef = None
        if isinstance(dugum, ast.Assign) and len(dugum.targets) == 1:
            hedef, deger = dugum.targets[0], dugum.value
        elif isinstance(dugum, ast.AnnAssign) and dugum.value is not None:
            hedef, deger = dugum.target, dugum.value
        if isinstance(hedef, ast.Name):
            sabitler[hedef.id] = deger

    cikti: dict[str, Any] = {}
    for kayit in sabitler["_ISSUES"].elts:
        alan = {k.value: v for k, v in zip(kayit.keys, kayit.values)}  # type: ignore[union-attr]
        anahtar = ast.literal_eval(alan["key"])
        if anahtar not in STORYLER:
            continue
        aciklama = alan["description"]
        assert isinstance(aciklama, ast.Call) and getattr(aciklama.func, "id", "") == "_desc", anahtar
        paragraf = ast.literal_eval(aciklama.args[0])
        ac_dugum = aciklama.args[1]
        acs: list[str] = []
        if isinstance(ac_dugum, ast.Name):
            acs = ast.literal_eval(sabitler[ac_dugum.id])
        cikti[anahtar] = {
            "summary": ast.literal_eval(alan["summary"]),
            "aciklama": paragraf,
            "ac": [_ac(a) for a in acs],
        }
    eksik = set(STORYLER) - set(cikti)
    if eksik:
        raise SystemExit(f"seed.py: story bulunamadı: {sorted(eksik)}")
    return cikti


def goldenlar(amac: str) -> dict[str, Any]:
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))["output"]
        for p in sorted((REPLAY / amac / "golden").glob("*.json"))
    }


def serbest_girdi() -> dict[str, Any]:
    """Serbest metin golden'ının girdi beyanı (input_match): örnek veri hangi serbest metnin
    golden'la eşleştiğini (REPLAY) ve hangisinin eşleşmediğini (REPLAY-MISS) buradan bilir."""
    p = REPLAY / "consistency_check" / "golden" / "SERBEST.json"
    if not p.exists():
        return {}
    im = json.loads(p.read_text(encoding="utf-8")).get("input_match") or {}
    return {k: im[k] for k in ("acceptance_criteria", "contains") if k in im}


def case_goldenlari() -> dict[str, Any]:
    """case_generation golden'ları: girdi beyanındaki AC satırları + çıktı case'leri. Örnek veri
    case üretiminde yalnızca AC'ler birebir eşleşirse REPLAY der (core input_match ile aynı)."""
    out: dict[str, Any] = {}
    for p in sorted((REPLAY / "case_generation" / "golden").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        out[p.stem] = {
            "girdi_ac": (d.get("input_match") or {}).get("acceptance_criteria", []),
            "cases": d["output"]["cases"],
        }
    return out


def main() -> None:
    cikti = {
        "jira_seed": jira_seed(),
        "requirement_review": goldenlar("requirement_review"),
        "consistency_check": goldenlar("consistency_check"),
        "serbest_girdi": serbest_girdi(),
        "case_generation": case_goldenlari(),
    }
    json.dump(cikti, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
