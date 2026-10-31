"""Demo-B ön kontrolü: onaylı case'ler "defect adayı" anını üretecek mi? (REPLAY golden'larıyla)

Demo-B'nin doruk noktası (DEMO-VERISI, TEKNIK-TASARIM §8.4 adım 3): bugünkü kodda assertion'da
kırmızı olan bir case ("6 adet → bedava ürün verilmez") yerel kontrolde **defect adayı** olur ve
insana düşer. Demo'nun ANA yolu budur: Demo-A'da analist F2 (kampanya) ve F4 (kredi limiti)
bulgularında **"Kod hatalı"** (`code_defect`) seçer, F1/F3 dokümanda düzeltilir (REPLAY senaryosu
`f2-kod-hatasi`). Alternatif F2 `fix_doc` kararı (`golden/*.json`) C3'ü "6 adet → 1 bedava" yapar
ve o case bugünkü kodda yeşildir. Tek yanlış tık Demo-B kanıtını sessizce siler; bu kontrol
Demo-B'den önce bunu yakalar.

Kural (golden'lardan, elle liste yok): onaylı her case'in REPLAY'de döneceği verify_and_map golden'ı
`input_match` beyanıyla bulunur; golden yapılandırılmış `defect_adayi` beyanı taşıyorsa (kayıt
anında sayfada gözlenen değer case'in beklediğinden farklı → yerel kontrolde assertion kırmızı;
`{"step_id", "beklenen", "kayittaki_gozlem"}`) o case defect adayıdır. Karar serbest metinden
(evidence_ref) okunmaz. En az bir defect adayı yoksa kontrol başarısızdır.

    uv run python -m tp_core.gateway.demo_check --story TPD-1      # çıkış kodu 0 / 1
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tp_core.gateway.config import find_rules_dir
from tp_core.gateway.matching import input_mismatches
from tp_core.gateway.untrusted import wrap_untrusted

PURPOSE = "verify_and_map"
DEFECT_FIELD = "defect_adayi"
# Kod üretimine giren case durumları (features.codegen.service.CASE_KULLANILIR ile aynı).
USABLE_CASE_STATES = frozenset({"approved", "published"})
HINT = (
    "Demo-A'da TPD-1 F2 (kampanya: 'her 6 adette 1 bedava') bulgusunda 'Kod hatalı' (code_defect) "
    "seçin; F1 ve F3 'Dokümanı düzelt' kalır. Ardından 2. tur kontrol → case üretimi → onay. "
    "Bkz. docs/DEMO-VERISI.md (f2-kod-hatasi)."
)


@dataclass(frozen=True)
class CaseVerdict:
    sira_no: int
    title: str
    golden: str | None  # REPLAY'de dönecek golden (None = REPLAY-MISS)
    defect_candidate: bool


@dataclass
class Readiness:
    story: str
    cases: list[CaseVerdict] = field(default_factory=list)

    @property
    def defect_candidates(self) -> list[CaseVerdict]:
        return [c for c in self.cases if c.defect_candidate]

    @property
    def ok(self) -> bool:
        return bool(self.defect_candidates)

    def report(self) -> str:
        lines = [f"Demo-B ön kontrolü ({self.story}): {len(self.cases)} onaylı case"]
        for c in self.cases:
            tag = (
                "DEFECT ADAYI" if c.defect_candidate else ("REPLAY" if c.golden else "REPLAY-MISS")
            )
            lines.append(f"  C{c.sira_no:<3} {tag:<12} {c.title} [{c.golden or '-'}]")
        if self.ok:
            names = ", ".join(f"C{c.sira_no}" for c in self.defect_candidates)
            lines.append(f"TAMAM: defect adayı case var ({names}); Demo-B doruk noktası hazır.")
        else:
            lines.append("HATA: onaylı case'ler arasında defect adayı yok. " + HINT)
        return "\n".join(lines)


def _goldens(rules_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    root = rules_dir / "replay" / PURPOSE / "golden"
    out = []
    for path in sorted(root.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data.get("input_match"), dict):
            out.append((path.relative_to(root).with_suffix("").as_posix(), data))
    return out


def _is_defect_candidate(golden: Mapping[str, Any]) -> bool:
    """Golden'ın yapılandırılmış beyanı: eşlemedeki bir adımı gösteren `defect_adayi`."""
    beyan = golden.get(DEFECT_FIELD)
    if not isinstance(beyan, Mapping) or not beyan.get("beklenen"):
        return False
    steps = {m.get("step_id") for m in (golden.get("output") or {}).get("step_mapping") or []}
    return beyan.get("step_id") in steps


def case_message(story: str, sira_no: int, icerik: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Kod üretiminin case bloğuyla aynı biçim (`case:<KEY>-C<n>`, JSON gövde)."""
    block = wrap_untrusted(
        json.dumps(dict(icerik), ensure_ascii=False), source=f"case:{story}-C{sira_no}"
    )
    return [{"role": "user", "content": block}]


def evaluate(
    story: str, cases: Iterable[tuple[int, Mapping[str, Any]]], rules_dir: Path | None = None
) -> Readiness:
    """`cases`: (sira_no, onaylı case içeriği). Veritabanından bağımsız (birim testlenebilir)."""
    goldens = _goldens(find_rules_dir(rules_dir))
    result = Readiness(story)
    for sira_no, icerik in sorted(cases, key=lambda c: c[0]):
        msg = case_message(story, sira_no, icerik)
        hit = next(
            ((name, g) for name, g in goldens if not input_mismatches(g["input_match"], msg)),
            None,
        )
        result.cases.append(
            CaseVerdict(
                sira_no=sira_no,
                title=str(icerik.get("title") or ""),
                golden=hit[0] if hit else None,
                defect_candidate=bool(hit and _is_defect_candidate(hit[1])),
            )
        )
    return result


def approved_cases(story: str) -> list[tuple[int, dict[str, Any]]]:
    """Story'nin kod üretimine girecek case'leri (sıra başına en son üretim)."""
    from sqlalchemy import select

    from tp_core.models import session_scope
    from tp_core.models.requirements import Requirement, TestCase

    latest: dict[int, tuple[int, dict[str, Any]]] = {}
    with session_scope() as s:
        rows = s.execute(
            select(TestCase.sira_no, TestCase.uretim_no, TestCase.icerik)
            .join(Requirement, Requirement.id == TestCase.requirement_id)
            .where(Requirement.jira_key == story, TestCase.durum.in_(USABLE_CASE_STATES))
        ).all()
    for sira_no, uretim_no, icerik in rows:
        if sira_no not in latest or uretim_no > latest[sira_no][0]:
            latest[sira_no] = (uretim_no, dict(icerik))
    return [(n, icerik) for n, (_, icerik) in sorted(latest.items())]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--story", default="TPD-1")
    args = ap.parse_args(argv)
    readiness = evaluate(args.story, approved_cases(args.story))
    print(readiness.report())
    return 0 if readiness.ok else 1


if __name__ == "__main__":
    sys.exit(main())
