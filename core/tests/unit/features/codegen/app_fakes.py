"""Sahte app-mcp oturumu (009 §2.6; docs/CIHAZ-ALTYAPISI.md §6) — Bayi Sipariş uygulaması.

app-mcp'nin araç sözleşmesini (kapalı argümanlar, `### Sonuç` / `### Snapshot` + ```yaml```,
`[id=…]`, `[password]` işaretli alanın değeri `***`, `### Locator` + JSON, `### Hata` + isError)
cihazsız taklit eder: giriş → katalog → sepet ekranları, ajan bayisiyle (bayi3) giriş, P-001
"6 al 1 bedava" kampanyası. REPLAY golden'ı (`verify_and_map_app/golden/TPD-1-C2-android`) bu
oturumda yeniden yürütülür; kimlikler `demo-app/e2e-app` Kimlikler.java ile aynıdır.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from tp_core.features.codegen.browser import ToolOutput

PNG = b"\x89PNG\r\n\x1a\nfake-app-png"
APP_TOOLS = [
    "app_launch",
    "app_snapshot",
    "app_click",
    "app_type",
    "app_select_option",
    "app_wait_for",
    "app_generate_locator",
    "app_screenshot",
]
_SCHEMAS: dict[str, dict[str, Any]] = {
    "app_launch": {
        "type": "object",
        "properties": {
            "platform": {"type": "string", "enum": ["android", "ios", "windows"]},
            "reset": {"type": "boolean"},
        },
        "required": ["platform"],
        "additionalProperties": False,
    },
    "app_snapshot": {"type": "object", "properties": {}, "additionalProperties": False},
    "app_click": {
        "type": "object",
        "properties": {"ref": {"type": "string"}, "element": {"type": "string"}},
        "required": ["ref"],
        "additionalProperties": False,
    },
    "app_type": {
        "type": "object",
        "properties": {
            "ref": {"type": "string"},
            "text": {"type": "string"},
            "element": {"type": "string"},
        },
        "required": ["ref", "text"],
        "additionalProperties": False,
    },
    "app_select_option": {
        "type": "object",
        "properties": {
            "ref": {"type": "string"},
            "values": {"type": "array", "items": {"type": "string"}},
            "element": {"type": "string"},
        },
        "required": ["ref", "values"],
        "additionalProperties": False,
    },
    "app_wait_for": {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "textGone": {"type": "string"},
            "time": {"type": "number"},
        },
        "additionalProperties": False,
    },
    "app_generate_locator": {
        "type": "object",
        "properties": {"ref": {"type": "string"}, "element": {"type": "string"}},
        "required": ["ref"],
        "additionalProperties": False,
    },
    "app_screenshot": {"type": "object", "properties": {}, "additionalProperties": False},
}
STRATEJI = {"android": "id", "ios": "accessibilityId", "windows": "accessibilityId"}
AJAN_BAYISI, AJAN_PAROLASI = "bayi3", "Demo123!"


@dataclass
class Eleman:
    ref: str
    girinti: int
    rol: str
    ad: str = ""
    kimlik: str | None = None
    parola: bool = False
    deger: str | None = None
    ek: str = ""  # durum öznitelikleri (` [disabled]`, ` [selected]`)


class FakeAppSession:
    """Durumlu sahte app-mcp. `hata(araç)` True dönerse araç `isError` verir; `kimliksiz`
    kümesindeki kimlikler `app_generate_locator`'da `id: null` döner (eksik kimlik benzetimi)."""

    def __init__(
        self,
        platform: str = "android",
        hata: Callable[[str], bool] | None = None,
        kimliksiz: set[str] | None = None,
    ) -> None:
        self.platform = platform
        self.hata = hata
        self.kimliksiz = set(kimliksiz or ())
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False
        self.ekran: str | None = None
        self.alanlar: dict[str, str] = {}
        self.sepet: dict[str, int] = {}
        self.durum = ""
        self.giris_hatasi = False

    # ------------------------------------------------------------------ MCP yüzeyi

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {"name": n, "description": f"{n} aracı (app-mcp)", "input_schema": _SCHEMAS[n]}
            for n in APP_TOOLS
        ]

    def close(self) -> None:
        self.closed = True

    def call(self, name: str, args: Mapping[str, Any]) -> ToolOutput:
        self.calls.append((name, dict(args)))
        if name == "app_screenshot":
            return ToolOutput("", [("image/png", PNG)])
        if self.hata is not None and self.hata(name):
            return self._hata(f"{name} başarısız (sahte)")
        if name == "app_launch":
            if args.get("platform") != self.platform:
                return self._hata(f"platform {args.get('platform')} yapılandırılmamış")
            self.ekran, self.alanlar, self.sepet = "giris", {}, {}
            self.durum, self.giris_hatasi = "", False
            return self._sonuc(
                "Uygulama verisi sıfırlanarak başlatıldı: com.antreklabs.bayisiparis "
                f"({self.platform})",
                snapshot=True,
            )
        if self.ekran is None:
            return self._hata("Uygulama başlatılmadı: önce app_launch çağırın")
        if name == "app_snapshot":
            return self._sonuc(None, snapshot=True)
        if name == "app_wait_for":
            metin = str(args.get("text") or "")
            if metin and metin not in self._snapshot():
                return self._hata(f'"{metin}" görünmedi (10 sn)')
            return self._sonuc(f'Göründü: "{metin}"', snapshot=True)
        el = self._eleman(str(args.get("ref") or ""))
        if el is None:
            return self._hata(
                f"ref {args.get('ref')} son snapshot'ta yok; app_snapshot ile güncel ref alın"
            )
        if name == "app_generate_locator":
            kimlik = None if el.kimlik in self.kimliksiz else el.kimlik
            veri = {"platform": self.platform, "strategy": STRATEJI[self.platform], "id": kimlik}
            return ToolOutput("### Locator\n" + json.dumps(veri, ensure_ascii=False))
        if name == "app_type":
            metin = str(args.get("text") or "")
            self.alanlar[el.kimlik or el.ref] = metin
            gorunen = "***" if el.parola else metin
            yazilan = gorunen if el.parola else f'"{gorunen}"'
            return self._sonuc(f"Yazıldı: {yazilan} → {el.ad} [ref={el.ref}]", snapshot=True)
        if name == "app_click":
            self._tikla(el)
            return self._sonuc(f"Tıklandı: {el.ad or el.rol} [ref={el.ref}]", snapshot=True)
        if name == "app_select_option":
            return self._sonuc(f"Seçildi: {args.get('values')}", snapshot=True)
        return self._hata(f"bilinmeyen araç: {name}")

    # ------------------------------------------------------------------ uygulama

    def _tikla(self, el: Eleman) -> None:
        if el.kimlik == "login-submit":
            ok = (
                self.alanlar.get("login-username") == AJAN_BAYISI
                and self.alanlar.get("login-password") == AJAN_PAROLASI
            )
            self.giris_hatasi = not ok
            if ok:
                self.ekran = "katalog"
        elif el.kimlik == "add-to-cart":
            adet = int(self.alanlar.get("qty-input-P-001") or "1")
            self.sepet["P-001"] = self.sepet.get("P-001", 0) + adet
            self.durum = f"{adet} adet sepete eklendi."
        elif el.kimlik == "nav-cart":
            self.ekran, self.durum = "sepet", ""
        elif el.kimlik == "nav-catalog":
            self.ekran = "katalog"

    def _elemanlar(self) -> list[Eleman]:
        """Ekran ağaçları canlı Android dumanının (app-mcp + demo uygulama, 2026-11-08) biçimini
        izler: kök `android:id/content`, ürün adı `heading`, menü altta, sepet düğmesi
        "Sepet, N ürün"; ref'ler oturum içinde kararlı (giriş e1–e9, katalog e10–e48)."""
        if self.ekran == "giris":
            girildi = bool(
                self.alanlar.get("login-username") and self.alanlar.get("login-password")
            )
            out = [
                Eleman("e1", 0, "list", "", "android:id/content"),
                Eleman("e2", 2, "text", "Bayi Sipariş Portalı"),
                Eleman("e3", 2, "heading", "Bayi girişi"),
                Eleman("e5", 2, "text", "Kullanıcı adı"),
                Eleman("e6", 2, "textbox", "Kullanıcı adı", "login-username",
                       deger=self.alanlar.get("login-username")),
                Eleman("e7", 2, "text", "Parola"),
                Eleman("e8", 2, "textbox", "Parola", "login-password", parola=True,
                       deger="***" if self.alanlar.get("login-password") else None),
                Eleman("e9", 2, "button", "Giriş yap", "login-submit",
                       ek="" if girildi else " [disabled]"),
            ]  # fmt: skip
            if self.giris_hatasi:
                out.append(
                    Eleman("e50", 2, "text", "Kullanıcı adı veya parola hatalı", "login-error")
                )
            return out
        adet = sum(self.sepet.values())
        ust = [
            Eleman("e10", 0, "group", "", "android:id/content"),
            Eleman("e11", 2, "text", "Bayi Sipariş Portalı"),
            Eleman("e12", 2, "text", "Doğrulama Bayi", "current-dealer"),
            Eleman("e13", 2, "button", "Çıkış yap", "nav-logout"),
            Eleman("e14", 2, "list"),
        ]
        alt = [
            Eleman("e45", 2, "button", "Katalog", "nav-catalog",
                   ek=" [selected]" if self.ekran == "katalog" else ""),
            Eleman("e46", 2, "button", f"Sepet, {adet} ürün", "nav-cart",
                   ek=" [selected]" if self.ekran == "sepet" else ""),
            Eleman("e47", 2, "text", str(adet), "cart-count"),
            Eleman("e48", 2, "button", "Siparişlerim", "nav-orders"),
        ]  # fmt: skip
        if self.ekran == "katalog":
            return [
                *ust,
                Eleman("e15", 4, "heading", "Ürün kataloğu"),
                Eleman("e17", 4, "group", "", "product-list"),
                Eleman("e18", 6, "group", "", "product-card-P-001"),
                Eleman("e20", 8, "text", "P-001"),
                Eleman("e21", 8, "heading", "Portakal Gazozu 1L"),
                Eleman("e22", 8, "text", "Kampanya: 6 al 1 bedava"),
                Eleman("e23", 8, "text", "25,00 TL", "product-price-P-001"),
                Eleman("e24", 8, "text", "Adet"),
                Eleman("e25", 8, "textbox", "Adet", "qty-input-P-001",
                       deger=self.alanlar.get("qty-input-P-001", "1")),
                Eleman("e26", 8, "button", "Sepete ekle", "add-to-cart"),
                Eleman("e27", 8, "text", self.durum, "product-status-P-001"),
                Eleman("e28", 6, "group", "", "product-card-P-002"),
                Eleman("e30", 8, "text", "P-002"),
                Eleman("e31", 8, "heading", "Limonata 330ml"),
                Eleman("e32", 8, "text", "15,00 TL", "product-price-P-002"),
                Eleman("e34", 8, "textbox", "Adet", "qty-input-P-002", deger="1"),
                Eleman("e35", 8, "button", "Sepete ekle", "add-to-cart"),
                *alt,
            ]  # fmt: skip
        n = self.sepet.get("P-001", 0)
        bedava = n // 7
        ara, indirim = n * 25, bedava * 25
        return [
            *ust,
            Eleman("e60", 4, "heading", "Sepetim"),
            Eleman("e61", 4, "group", "", "cart-table"),
            Eleman("e62", 6, "group", "", "cart-line-P-001"),
            Eleman("e63", 8, "heading", "Portakal Gazozu 1L"),
            Eleman("e64", 8, "text", "P-001"),
            Eleman("e65", 8, "text", str(n), "cart-line-qty-P-001"),
            Eleman("e66", 8, "text", str(bedava), "cart-line-free-P-001"),
            Eleman("e67", 8, "text", _tl(ara - indirim), "cart-line-total-P-001"),
            Eleman("e68", 4, "text", _tl(ara), "cart-subtotal"),
            Eleman("e69", 4, "text", _tl(indirim), "cart-discount"),
            Eleman("e70", 4, "text", _tl(ara - indirim), "cart-total"),
            Eleman("e71", 4, "button", "Siparişi onayla", "checkout-submit"),
            *alt,
        ]

    def _eleman(self, ref: str) -> Eleman | None:
        return next((e for e in self._elemanlar() if e.ref == ref), None)

    def _snapshot(self) -> str:
        satirlar = []
        for e in self._elemanlar():
            parca = f"{' ' * e.girinti}- {e.rol}"
            if e.ad:
                parca += f' "{e.ad}"'
            if e.kimlik:
                parca += f" [id={e.kimlik}]"
            if e.parola:
                parca += " [password]"
            parca += f"{e.ek} [ref={e.ref}]"
            if e.deger:
                parca += f": {e.deger}"
            satirlar.append(parca)
        return "\n".join(satirlar)

    def _sonuc(self, mesaj: str | None, snapshot: bool) -> ToolOutput:
        parca = [f"### Sonuç\n{mesaj}"] if mesaj else []
        parca.append(
            f"### Uygulama\n- Platform: {self.platform}\n- Uygulama: com.antreklabs.bayisiparis"
        )
        if snapshot:
            parca.append(f"### Snapshot\n```yaml\n{self._snapshot()}\n```")
        return ToolOutput("\n".join(parca))

    @staticmethod
    def _hata(mesaj: str) -> ToolOutput:
        return ToolOutput(f"### Hata\n{mesaj}", is_error=True)


def _tl(kurus_lira: int) -> str:
    return f"{kurus_lira:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")
