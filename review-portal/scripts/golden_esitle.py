"""Portal örnek verisinin bağlayıcı kaynaklarını tek JSON olarak basar.

Kaynaklar (docs/DEMO-VERISI.md):
- sims/jira-sim/src/jira_sim/seed.py: TPD-1..TPD-4 başlık, açıklama paragrafı, kabul kriterleri
  (bağımlılık kurmadan `ast` ile okunur; seed.py çalıştırılmaz).
- rules/replay/requirement_review/golden/*.json → output (ön inceleme soruları, verdict).
- rules/replay/consistency_check/golden/*.json → output (tutarlılık bulguları).
- rules/replay/consistency_check/golden/SERBEST.json → input_match (serbest metin golden'ının girdisi).
- rules/replay/case_generation/golden/*.json → input_match AC'leri + output.cases + üst düzey
  listeler (`ozet`, şema v3).
- Senaryo golden'ları (`golden/<senaryo>/<ad>.json`, ör. ana demo yolu `f2-kod-hatasi/`): aynı
  sözlüklerde `<senaryo>/<ad>` anahtarıyla. Core gibi örnek veri de ana golden'ın girdi beyanı
  uymazsa senaryoları ada göre sıralı dener (`consistency_girdi` / `case_generation.girdi_ac`).

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


def _dosyalar(amac: str) -> list[tuple[str, Path]]:
    """Ana golden'lar (`<ad>`) ve senaryo golden'ları (`<senaryo>/<ad>`), ada göre sıralı."""
    kok = REPLAY / amac / "golden"
    ana = [(p.stem, p) for p in sorted(kok.glob("*.json"))]
    senaryo = [
        (f"{d.name}/{p.stem}", p)
        for d in sorted(x for x in kok.iterdir() if x.is_dir())
        for p in sorted(d.glob("*.json"))
    ]
    return ana + senaryo


def goldenlar(amac: str) -> dict[str, Any]:
    return {ad: json.loads(p.read_text(encoding="utf-8"))["output"] for ad, p in _dosyalar(amac)}


def girdi_aclari(amac: str) -> dict[str, list[str]]:
    """Golden'ların girdi beyanındaki AC satırları (beyan yoksa golden listede yok)."""
    out: dict[str, list[str]] = {}
    for ad, p in _dosyalar(amac):
        im = json.loads(p.read_text(encoding="utf-8")).get("input_match") or {}
        if "acceptance_criteria" in im:
            out[ad] = im["acceptance_criteria"]
    return out


def serbest_girdi() -> dict[str, Any]:
    """Serbest metin golden'ının girdi beyanı (input_match): örnek veri hangi serbest metnin
    golden'la eşleştiğini (REPLAY) ve hangisinin eşleşmediğini (REPLAY-MISS) buradan bilir."""
    p = REPLAY / "consistency_check" / "golden" / "SERBEST.json"
    if not p.exists():
        return {}
    im = json.loads(p.read_text(encoding="utf-8")).get("input_match") or {}
    return {k: im[k] for k in ("acceptance_criteria", "contains") if k in im}


def case_goldenlari() -> dict[str, Any]:
    """case_generation golden'ları: girdi beyanındaki AC satırları + çıktı case'leri + üretimin
    üst düzey listeleri (`ozet`; şema v3: açık soru, varsayım, kapsam öğeleri, negatif kapsam
    kararı, kapsanmayanlar — core `case_uretim.ozet` ile aynı içerik). Örnek veri case üretiminde
    yalnızca AC'ler birebir eşleşirse REPLAY der (core input_match ile aynı)."""
    out: dict[str, Any] = {}
    for ad, p in _dosyalar("case_generation"):
        d = json.loads(p.read_text(encoding="utf-8"))
        out[ad] = {
            "girdi_ac": (d.get("input_match") or {}).get("acceptance_criteria", []),
            "cases": d["output"]["cases"],
            "ozet": {k: v for k, v in d["output"].items() if k != "cases"},
        }
    return out


def main() -> None:
    cikti = {
        "jira_seed": jira_seed(),
        "requirement_review": goldenlar("requirement_review"),
        "consistency_check": goldenlar("consistency_check"),
        "consistency_girdi": girdi_aclari("consistency_check"),
        "serbest_girdi": serbest_girdi(),
        "case_generation": case_goldenlari(),
    }
    json.dump(cikti, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
