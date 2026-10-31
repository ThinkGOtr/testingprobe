"""Deterministik kanıt doğrulayıcı (TEKNIK-TASARIM §8.2b adım 4, Constitution XI) — LLM yok.

Bir bulgu yalnızca aşağıdakilerin hepsi sağlanırsa gösterilir (`kanit_dogrulandi = true`):

- `doc_ref` belgede var (atıf yapılan her ACn mevcut; AC yoksa açıklamaya atıf).
- Kod/veri iddiası taşıyan türler (`doc_vs_code`, `doc_vs_data`, `missing_in_code`,
  `missing_in_doc`) en az bir kanıt içerir. `internal_contradiction` ve `ambiguous` kanıtsız
  olabilir.
- **Kod kanıtı:** `repo` denetlenen depo; dosya denetimin sabitlendiği commit'te (`sha`) yeniden
  okunur; `line` dosya içinde; boşlukları normalize edilmiş `snippet` o satırın (boşlukları
  normalize edilmiş) metninde birebir geçer. Anlamsız kısa alıntılar (8 karakterden kısa ve
  satırın tamamı olmayan) kabul edilmez.
- **Veri kanıtı:** sorgu SQL korumasının kanıt kurallarından geçer (`validate_select(kanit=True)`:
  tek tablo — JOIN/virgüllü birleştirme/alt sorgu/LATERAL/VALUES yok, takma ad kolon listesi yok —
  ve her sütun tablodan okunur; `SELECT anahtar, '500.00' FROM ayar` gibi değer uyduran sabit
  projeksiyonlar ve `1 = 0` gibi sabit koşullar reddedilir), salt okuma veritabanında yeniden
  çalıştırılır ve `result_digest` sonucun özetiyle eşleşir (`gateway.digest_matches`; maskeli biçim
  `datatools.masked_digest`).

Doğrulanamayan bulgu saklanır (`kanit_dogrulandi = false`, durum `discarded`) ama gösterilmez;
nedeni `consistency_finding_ek.dogrulama`'da durur.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from tp_core.features.requirements.content import doc_ref_valid
from tp_core.features.requirements.datatools import DataToolError, DemoDb, digest_matches_any
from tp_core.features.requirements.sqlguard import QueryRejected, validate_select
from tp_core.ports import ForgePort

EVIDENCE_REQUIRED = frozenset({"doc_vs_code", "doc_vs_data", "missing_in_code", "missing_in_doc"})
MIN_SNIPPET = 8


def norm_ws(text: str) -> str:
    return " ".join(str(text).split())


@dataclass
class Verification:
    ok: bool
    checks: list[dict[str, Any]] = field(default_factory=list)


class EvidenceVerifier:
    def __init__(self, forge: ForgePort, sha: str, db: DemoDb, *, repo: str) -> None:
        self.forge = forge
        self.sha = sha
        self.db = db
        self.repo = repo
        self._files: dict[str, list[str] | None] = {}

    def _lines(self, path: str) -> list[str] | None:
        if path not in self._files:
            try:
                self._files[path] = self.forge.read_file(path, ref=self.sha).splitlines()
            except Exception:
                self._files[path] = None
        return self._files[path]

    def check_code(self, ev: dict[str, Any]) -> tuple[bool, str]:
        repo = str(ev.get("repo") or "").split("@", 1)[0].rsplit("/", 1)[-1]
        if repo not in (self.repo, ""):
            return False, f"farklı depo: {ev.get('repo')}"
        path = str(ev.get("path") or "")
        line = ev.get("line")
        snippet = norm_ws(ev.get("snippet") or "")
        if not path or not isinstance(line, int) or isinstance(line, bool) or not snippet:
            return False, "eksik kanıt alanı"
        satirlar = self._lines(path)
        if satirlar is None:
            return False, f"dosya bulunamadı: {path} @ {self.sha[:12]}"
        if not 1 <= line <= len(satirlar):
            return False, f"satır {line} dosyanın dışında ({len(satirlar)} satır)"
        hedef = norm_ws(satirlar[line - 1])
        if snippet not in hedef:
            return False, f"alıntı {path}:{line} satırında yok"
        if len(snippet) < MIN_SNIPPET and snippet != hedef:
            return False, "alıntı çok kısa"
        return True, f"{path}:{line} @ {self.sha[:12]}"

    def check_data(self, ev: dict[str, Any]) -> tuple[bool, str]:
        query = ev.get("query")
        digest = ev.get("result_digest")
        if not isinstance(query, str) or not isinstance(digest, str) or not digest.strip():
            return False, "eksik kanıt alanı"
        try:
            vq = validate_select(query, kanit=True)
            res = self.db.query(vq.sql)
        except QueryRejected as exc:
            return False, f"sorgu reddedildi: {exc}"
        except DataToolError as exc:
            return False, f"sorgu yeniden çalıştırılamadı: {exc}"
        if not digest_matches_any(digest, res.rows):
            return False, "sonuç özeti eşleşmiyor"
        if not res.rows:
            # Boş sonuç yalnızca "bu koşulla satır yok" kanıtıdır (koşuldaki bir yazım hatası da
            # boş döner); analist sorguyu görsün diye açıkça işaretlenir.
            neden = "0 satır (boş sonuç; yalnızca bu koşulla satır olmadığını kanıtlar)"
            return True, f"{neden}: {vq.sql}"
        return True, f"{len(res.rows)} satır, özet eşleşti: {vq.sql}"

    def verify(self, finding: dict[str, Any], acs: Sequence[str]) -> Verification:
        checks: list[dict[str, Any]] = []
        ok = True
        doc_ref = str(finding.get("doc_ref") or "")
        if not doc_ref_valid(doc_ref, acs):
            ok = False
            checks.append({"kind": "doc_ref", "ok": False, "neden": f"belgede yok: {doc_ref}"})
        kanitlar = finding.get("evidence") or []
        if finding.get("type") in EVIDENCE_REQUIRED and not kanitlar:
            ok = False
            checks.append({"kind": "evidence", "ok": False, "neden": "kanıt yok"})
        for i, ev in enumerate(kanitlar):
            kind = ev.get("kind") if isinstance(ev, dict) else None
            if kind == "code":
                gecti, neden = self.check_code(ev)
            elif kind == "data":
                gecti, neden = self.check_data(ev)
            else:
                gecti, neden = False, "bilinmeyen kanıt türü"
            ok = ok and gecti
            checks.append({"index": i, "kind": kind, "ok": gecti, "neden": neden})
        return Verification(ok, checks)
