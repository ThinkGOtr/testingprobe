"""Playwright MCP snapshot yardımcıları: snapshot tespiti, ref çözümü, dosya bağlantısı ayıklama.

**Neden:** Playwright MCP'nin snapshot ref'leri (`[ref=e21]`) oturuma özgüdür ve aynı yörüngede
bile koşudan koşuya kayabilir: `browser_navigate` SPA henüz çizilirken örtük bir snapshot alır ve
bazen fazladan bir ref harcar; sayfanın tamamı +1 kayar (`button "Giriş yap" [ref=e20]` ↔
`[ref=e21]`). Bu yüzden REPLAY kayıttaki ref'i olduğu gibi tekrar gönderemez: kayıttaki adım
elemanı **rol + erişilebilir ad (+ kapsam çapası)** ile yapılandırılmış olarak taşır (`hedef`) ve
replay, ref'i o anki CANLI son snapshot'tan çözer (`locate_ref`). Ajanın kendisi de böyle çalışır:
elemanı son snapshot'ta rol/adla bulur, ref'i oradan alır.

Golden adımının yapılandırılmış hedefi (`steps[i].hedef`, yalnızca ref alan adımlarda):

    {"rol": "button", "ad": "Sepete ekle", "kapsam": "paragraph: P-002"}

- `rol`: ARIA rolü (snapshot satırının ilk sözcüğü).
- `ad`: erişilebilir ad; tam eşleşir ya da `ad + " "` önekiyle (bağlantı adı sayacı içerir:
  `link "Sepet 6 ürün"` ↔ `ad: "Sepet"`). Boşsa adsız ilk `rol` elemanı.
- `kapsam` (isteğe bağlı): aynı rol/ad her ürün kartında tekrarlandığında kartı belirleyen satır
  (ref'siz temiz biçimiyle, ör. `paragraph: P-002`). Arama o satırdan sonra başlar ve satırın
  girinti düzeyinden çıkınca (kart bitince) durur.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

SNAPSHOT_TOOL = "browser_snapshot"
SNAPSHOT_REF = re.compile(r"^e\d+$")
# Ref alan argümanlar (Playwright MCP 1.64: `target`; eski sürümler: `ref`).
REF_ARGS = ("target", "ref")

_YAML_BLOCK = re.compile(r"```yaml\n(.*?)```", re.DOTALL)
# 1.64 biçimi: `### Snapshot` başlığı ve hemen ardından satır içi ```yaml bloğu.
_INLINE_SNAPSHOT = re.compile(r"^###\s*Snapshot\s*\n```yaml\n", re.MULTILINE)
_REF_ATTR = re.compile(r"\s*\[ref=e\d+\]")
_NOISE_ATTR = re.compile(r"\s*\[cursor=pointer\]|\s*\[active\]")
_LINE = re.compile(
    r'^(?P<indent>\s*)- (?P<role>[a-z][a-z0-9-]*)(?: "(?P<name>(?:[^"\\]|\\.)*)")?'
    r"(?P<attrs>(?: \[[^\]]*\])*)"
)
_REF_IN = re.compile(r"\[ref=(e\d+)\]")

# Eylem sonuçlarındaki MCP sunucu dosyası bağlantıları (model açamaz; gürültü + yol sızıntısı):
#   - [Snapshot](../../tmp/playwright-mcp/page-2026-10-31T13-38-47-139Z.yml)
#   - New console entries: ../../tmp/playwright-mcp/console-2026-10-31T13-38-47-078Z.log#L1
_FILE_LINK_LINE = re.compile(
    r"^\s*-\s*(?:\[[^\]]*\]\([^)\s]+\.(?:ya?ml|log|md|png|jpe?g)(?:#\S*)?\)"
    r"|New console entries:\s*\S+\.log(?:#\S*)?)\s*$"
)
_HEADER = re.compile(r"^###\s")


def is_inline_snapshot(text: str) -> bool:
    """Sonuç metni sayfa snapshot'ını satır içi taşıyor mu (YAML ağacı)?

    Playwright MCP 1.64: `browser_snapshot` → `### Snapshot` + ```yaml```; eylemler (navigate,
    click …) snapshot'ı yalnızca dosya bağlantısı olarak verir (`- [Snapshot](…yml)`) — bu
    snapshot sayılmaz. Bir MCP seçeneği eylem sonucuna YAML'ı satır içi koyarsa o da snapshot'tır
    (son snapshot dışındakiler bağlamdan çıkarılır, §8.4). Eski biçim (`- Page Snapshot`) de
    tanınır.
    """
    return bool(_INLINE_SNAPSHOT.search(text)) or "Page Snapshot" in text


def snapshot_lines(text: str) -> list[str] | None:
    """Sonuçtaki snapshot YAML ağacının satırları (snapshot yoksa None)."""
    m = _YAML_BLOCK.search(text or "")
    if m is None:
        return None
    return m.group(1).splitlines()


def clean_line(line: str) -> str:
    """Ref/gürültü özniteliksiz satır (`- paragraph [ref=e63]: P-002` → `paragraph: P-002`)."""
    return _NOISE_ATTR.sub("", _REF_ATTR.sub("", line)).strip().removeprefix("- ").rstrip(":")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


@dataclass(frozen=True)
class Hedef:
    """Ref alan bir adımın yapılandırılmış hedefi (golden `steps[i].hedef`)."""

    rol: str
    ad: str = ""
    kapsam: str | None = None

    @classmethod
    def from_raw(cls, raw: Any) -> Hedef | None:
        if not isinstance(raw, Mapping):
            return None
        rol = raw.get("rol")
        if not isinstance(rol, str) or not rol:
            return None
        ad = raw.get("ad") or ""
        kapsam = raw.get("kapsam") or None
        return cls(rol=rol, ad=str(ad), kapsam=str(kapsam) if kapsam else None)

    def as_dict(self) -> dict[str, str]:
        out = {"rol": self.rol, "ad": self.ad}
        if self.kapsam:
            out["kapsam"] = self.kapsam
        return out

    def describe(self) -> str:
        ad = f' "{self.ad}"' if self.ad else ""
        kapsam = f" ({self.kapsam} içinde)" if self.kapsam else ""
        return f"{self.rol}{ad}{kapsam}"


def _name_matches(want: str, got: str | None) -> bool:
    if not want:
        return got is None
    return got is not None and (got == want or got.startswith(want + " "))


def locate_line(lines: Sequence[str], hedef: Hedef) -> tuple[str, str] | None:
    """Son snapshot'ta hedefi rol/ad (+kapsam) ile bulur: (ref, ham satır) ya da None."""
    start, stop_indent = 0, -1
    if hedef.kapsam:
        anchor = next((i for i, x in enumerate(lines) if clean_line(x) == hedef.kapsam), None)
        if anchor is None:
            return None
        start, stop_indent = anchor + 1, _indent(lines[anchor])
    for line in lines[start:]:
        if stop_indent >= 0 and line.strip() and _indent(line) < stop_indent:
            break  # kapsamın (kartın) dışına çıkıldı
        m = _LINE.match(line)
        if m is None or m["role"] != hedef.rol or not _name_matches(hedef.ad, m["name"]):
            continue
        ref = _REF_IN.search(line)
        if ref:
            return ref.group(1), line
    return None


def locate_ref(lines: Sequence[str], hedef: Hedef) -> str | None:
    found = locate_line(lines, hedef)
    return found[0] if found else None


def ref_arg(args: Mapping[str, Any]) -> str | None:
    """Adımın snapshot ref'i alan argümanının adı (yoksa None)."""
    for key in REF_ARGS:
        value = args.get(key)
        if isinstance(value, str) and SNAPSHOT_REF.match(value):
            return key
    return None


def strip_mcp_file_links(text: str) -> str:
    """MCP sunucusundaki dosyalara (snapshot .yml, konsol .log) giden bağlantı satırlarını çıkarır.

    Model bu dosyaları açamaz; yollar sunucu iç yapısını sızdırır ve bağlamı şişirir. Başlığı
    boş kalan bölüm (`### Snapshot`, `### Events`) de çıkarılır. Diğer satırlara dokunulmaz.
    """
    if "](" not in text and "New console entries" not in text:
        return text
    kept = [line for line in text.split("\n") if not _FILE_LINK_LINE.match(line)]
    out: list[str] = []
    for i, line in enumerate(kept):
        if _HEADER.match(line):
            nxt = next((x for x in kept[i + 1 :] if x.strip()), None)
            if nxt is None or _HEADER.match(nxt) or nxt.lstrip().startswith("</untrusted"):
                continue
        out.append(line)
    return "\n".join(out)
