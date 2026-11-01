"""Uygulama köküne göre forge görünümü (tutarlılık denetimi için salt okuma).

Bulgular, kanıtlar ve REPLAY altın örnekleri uygulama köküne göre göreli yollar kullanır
(`api/src/demoapp_api/campaign.py:23`). LocalForge deposu yalnızca demo-app olduğu için bu yollar
doğrudan çözülür; GitHub kipinde ise uygulama `demo-app/` altındadır (`codegen.service.app_root`).
Bu görünüm okumaları köke yönlendirir ve arama sonuçlarındaki kökü atar, böylece kanıt doğrulama
ve kod araçları iki kipte de aynı yolları görür.
"""

from __future__ import annotations

from typing import Any


class AppRootForge:
    def __init__(self, forge: Any, root: str) -> None:
        self._forge = forge
        self._root = root.strip().strip("/")
        self._prefix = f"{self._root}/"

    def _in(self, path: str) -> str:
        path = path.lstrip("/")
        return path if path.startswith(self._prefix) else f"{self._prefix}{path}"

    def _out(self, path: str) -> str:
        return path[len(self._prefix) :] if path.startswith(self._prefix) else path

    def read_file(self, path: str, ref: str = "main") -> str:
        return self._forge.read_file(self._in(path), ref)

    def list_files(self, prefix: str = "", ref: str = "main") -> list[str]:
        files = self._forge.list_files(self._in(prefix) if prefix else self._prefix, ref)
        return [self._out(p) for p in files if p.startswith(self._prefix)]

    def search_code(self, query: str, ref: str = "main") -> list[tuple[str, int, str]]:
        return [
            (self._out(p), no, line)
            for p, no, line in self._forge.search_code(query, ref)
            if p.startswith(self._prefix)
        ]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._forge, name)


def app_root_view(forge: Any) -> Any:
    """Kök tanımlıysa (GitHub kipi) görünüme sarar; LocalForge'da forge'u olduğu gibi döner."""
    from tp_core.features.codegen.service import app_root

    root = app_root()
    return AppRootForge(forge, root) if root else forge
