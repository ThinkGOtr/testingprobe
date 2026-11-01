"""Onarımın toolchain-worker istemcisi (MIMARI-SOZLESME §2): `/symbols`, `/locator-probe`,
`/ast-guard` (mode=repair) ve `/check` (tam paket, `ast_guard_mode=repair`).

Kimlik: `Authorization: Bearer $TP_TOOLCHAIN_TOKEN` (yalnızca core-api/core-worker'da). Testler
`transport=` (httpx MockTransport) verir; kod yolu aynıdır.
"""

from __future__ import annotations

from typing import Any

import httpx

SYMBOLS_TIMEOUT_S = 120.0
PROBE_TIMEOUT_S = 90.0
AST_TIMEOUT_S = 120.0


class ToolchainHatasi(RuntimeError):
    def __init__(self, status: int | None, detay: str) -> None:
        super().__init__(detay)
        self.status = status
        self.detay = detay


class RepairToolchain:
    def __init__(
        self,
        base_url: str,
        *,
        token: str = "",
        transport: httpx.BaseTransport | None = None,
        check_timeout_s: float | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"} if token else None
        self._http = httpx.Client(base_url=self.base_url, transport=transport, headers=headers)
        if check_timeout_s is None:
            from tp_core.features.ci.clients import check_timeout_s as _ct

            check_timeout_s = float(_ct())
        self.check_timeout_s = check_timeout_s

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> RepairToolchain:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _post(self, yol: str, govde: dict[str, Any], timeout: float) -> dict[str, Any]:
        try:
            resp = self._http.post(yol, json=govde, timeout=timeout)
        except httpx.HTTPError as exc:
            raise ToolchainHatasi(None, f"toolchain-worker'a ulaşılamadı: {exc}") from exc
        try:
            veri = resp.json()
        except ValueError:
            veri = None
        if not resp.is_success:
            detay = veri.get("detail") if isinstance(veri, dict) else None
            raise ToolchainHatasi(
                resp.status_code,
                f"toolchain-worker {yol} HTTP {resp.status_code}: {detay or resp.text[:300]}",
            )
        if not isinstance(veri, dict):
            raise ToolchainHatasi(resp.status_code, f"toolchain-worker {yol}: geçersiz yanıt")
        return veri

    def symbols(self, sha: str) -> dict[str, Any]:
        tablo = self._post("/symbols", {"sha": sha}, SYMBOLS_TIMEOUT_S)
        if "page_objects" not in tablo:
            raise ToolchainHatasi(200, "sembol tablosu page_objects içermiyor")
        return tablo

    def locator_probe(
        self, sha: str, role: str, name: str, url_path: str, scope_test_id: str | None
    ) -> dict[str, Any]:
        govde: dict[str, Any] = {"sha": sha, "role": role, "name": name, "url_path": url_path}
        if scope_test_id:
            govde["scope_test_id"] = scope_test_id
        return self._post("/locator-probe", govde, PROBE_TIMEOUT_S)

    def ast_guard(self, base_sha: str, head_sha: str) -> dict[str, Any]:
        return self._post(
            "/ast-guard",
            {"base_sha": base_sha, "head_sha": head_sha, "mode": "repair"},
            AST_TIMEOUT_S,
        )

    def check(self, sha: str, base_sha: str, run_id: str, *, retries: int = 1) -> dict[str, Any]:
        """Tam paket (test_files boş: etkilenen tüm testler dahil), onarım modunda AST koruması.

        `retries` CI ile aynıdır (1): yeniden denemede geçen test raporda `flaky` olur ve
        kontrolü kırmızıya çevirmez; tek bir ilgisiz flake onarımı düşürmez.

        `record_check` verilmez (None): tam kapsamlı, kırılmasız kontrol toolchain tarafından
        `local-ci` olarak kaydedilir; LocalForge merge kapısı bu head için onu okur.
        """
        return self._post(
            "/check",
            {
                "sha": sha,
                "test_files": [],
                "repeat_each": 1,
                "retries": retries,
                "env": {},
                "base_sha": base_sha,
                "ast_guard_mode": "repair",
                "run_id": run_id,
                "keep": True,
            },
            self.check_timeout_s,
        )
