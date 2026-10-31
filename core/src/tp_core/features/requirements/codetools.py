"""Kod araçları: forge (`ForgePort`) üzerinde salt okuma, tek ve sabit commit'te.

Ajana verilen adlar model geçidinin izin listesindekilerdir (`ALLOWED_AGENT_TOOLS
['consistency_check']`, GitHub MCP'nin salt okuma araç adları):

- `search_code {query}` — sabit metin araması (`yol:satır: metin`, en çok 50 sonuç).
- `get_file_contents {path, start_line?, end_line?}` — dosyayı satır numaralı döndürür (en çok
  400 satır/çağrı). `path` boş, `/` ile biten ya da bir dizinse dosya listesini verir (GitHub
  MCP'deki gibi; `list_files` bu yolla karşılanır).

Tüm çağrılar denetimin başında sabitlenen `sha`'ya karşı yapılır: aynı turdaki kanıtlar aynı
commit'ten gelir ve doğrulayıcı (verifier) kanıtı aynı commit'te yeniden okur. Sonuçlar
güvenilmeyen kod bloğuna sarılır (§5).
"""

from __future__ import annotations

from typing import Any

from tp_core.gateway import wrap_tool_result
from tp_core.ports import ForgePort, ToolSpec

MAX_SEARCH_RESULTS = 50
MAX_LINES = 400
MAX_LIST = 300


class CodeToolError(RuntimeError):
    pass


def _int_arg(args: dict[str, Any], key: str) -> int | None:
    deger = args.get(key)
    if deger is None:
        return None
    if isinstance(deger, bool) or not isinstance(deger, int | str):
        raise CodeToolError(f"'{key}' tam sayı olmalı")
    try:
        sayi = int(deger)
    except ValueError as exc:
        raise CodeToolError(f"'{key}' tam sayı olmalı") from exc
    if sayi < 1:
        raise CodeToolError(f"'{key}' 1'den başlar")
    return sayi


class CodeTools:
    def __init__(self, forge: ForgePort, sha: str, repo: str = "demo-app") -> None:
        self.forge = forge
        self.sha = sha
        self.repo = repo

    def _wrap(self, text: str, tool: str, ref: str) -> str:
        return wrap_tool_result(tool, text, ref=f"{self.repo}@{self.sha[:12]}:{ref}")

    def search_code(self, args: dict[str, Any]) -> str:
        query = args.get("query") if isinstance(args, dict) else None
        if not isinstance(query, str) or not query.strip():
            raise CodeToolError("'query' gerekli")
        sonuclar = self.forge.search_code(query, ref=self.sha)
        if not sonuclar:
            return self._wrap("eşleşme yok", "search_code", query[:60])
        satirlar = [f"{yol}:{no}: {metin}" for yol, no, metin in sonuclar[:MAX_SEARCH_RESULTS]]
        if len(sonuclar) > MAX_SEARCH_RESULTS:
            satirlar.append(f"… {len(sonuclar) - MAX_SEARCH_RESULTS} sonuç daha (sorguyu daraltın)")
        return self._wrap("\n".join(satirlar), "search_code", query[:60])

    def _listele(self, prefix: str) -> list[str]:
        prefix = prefix.lstrip("/")
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        return self.forge.list_files(prefix, ref=self.sha)

    def get_file_contents(self, args: dict[str, Any]) -> str:
        path = args.get("path", "") if isinstance(args, dict) else ""
        if not isinstance(path, str):
            raise CodeToolError("'path' metin olmalı")
        path = path.strip()
        bas = _int_arg(args, "start_line")
        son = _int_arg(args, "end_line")
        if not path or path.endswith("/"):
            return self._liste_metni(path)
        try:
            icerik = self.forge.read_file(path, ref=self.sha)
        except Exception as exc:
            dosyalar = self._listele(path)
            if dosyalar:
                return self._liste_metni(path, dosyalar)
            raise CodeToolError(f"Dosya okunamadı: {path} ({exc})") from exc
        satirlar = icerik.splitlines()
        bas = bas or 1
        son = min(son or len(satirlar), len(satirlar), bas + MAX_LINES - 1)
        if satirlar and bas > len(satirlar):
            raise CodeToolError(f"{path} {len(satirlar)} satır; start_line={bas} dışında")
        govde = [f"{i}| {satirlar[i - 1]}" for i in range(bas, son + 1)]
        ust = f"{path} (satır {bas}-{son} / {len(satirlar)})"
        return self._wrap("\n".join([ust, *govde]), "get_file_contents", path)

    def _liste_metni(self, prefix: str, dosyalar: list[str] | None = None) -> str:
        dosyalar = dosyalar if dosyalar is not None else self._listele(prefix)
        metin = "\n".join(dosyalar[:MAX_LIST]) or "dosya yok"
        if len(dosyalar) > MAX_LIST:
            metin += f"\n… {len(dosyalar) - MAX_LIST} dosya daha"
        return self._wrap(metin, "get_file_contents", prefix or "/")


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="search_code",
        description=(
            "Test edilen uygulamanın deposunda sabit metin araması (salt okuma). "
            "Sonuç: 'yol:satır: metin' satırları."
        ),
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 200}},
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_file_contents",
        description=(
            "Depodan dosya okur (satır numaralı, en çok 400 satır). path boş/dizin ise dosya "
            "listesini verir. Kanıtta satır numarasını ve satırı birebir kullanın."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="db_schema",
        description="İzinli tabloların (urun, kampanya, ayar, bayi) kolonları ve türleri.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolSpec(
        name="db_query",
        description=(
            "Tek bir SELECT çalıştırır (yalnızca izinli tablo/kolonlar, salt okuma, 5 sn, en çok "
            "100 satır). Yanıttaki query ve result_digest değerlerini kanıta birebir yazın."
        ),
        input_schema={
            "type": "object",
            "properties": {"sql": {"type": "string", "minLength": 1, "maxLength": 2000}},
            "required": ["sql"],
            "additionalProperties": False,
        },
    ),
)
