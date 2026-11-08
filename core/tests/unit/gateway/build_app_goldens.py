"""`verify_and_map_app` REPLAY golden'ları (009 §2.6) — üretici.

    cd core && uv run python -m tests.unit.gateway.build_app_goldens   # rules/replay/... yazar

Golden'ın model çıktısı (eşleme) ELLE hazırlanmıştır (canlı model çıktısı değil). Araç adımları
app-mcp sözleşmesine (docs/CIHAZ-ALTYAPISI.md §6) uyan sahte oturumda (`app_fakes.FakeAppSession`)
yürütülerek yazılır; gerçek cihazda kaydedilmemiştir. Ref alan her adım `hedef` (rol/ad/kapsam)
taşır: REPLAY ref'i bu oturumun canlı son snapshot'ından çözer (gateway.snapshot_refs).
`test_app_goldens.py` depodaki dosyanın bu üreticinin çıktısıyla aynı olduğunu denetler.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.unit.features.codegen.app_fakes import FakeAppSession
from tests.unit.gateway.demo_sources import RULES, load_golden
from tp_core.features.codegen.browser import AgentApp, AgentConfig

PURPOSE = "verify_and_map_app"
SUMMARY_MAX = 400

# (araç, argümanlar, hedef) — ajanın yörüngesi (prompt kuralları: önce app_launch, her kimliği ilk
# kullanımdan önce app_generate_locator ile doğrula, ref'leri son snapshot'tan al).
_TPD1_C2: list[tuple[str, dict[str, Any], dict[str, str] | None]] = [
    ("app_launch", {"platform": "android", "reset": True}, None),
    (
        "app_generate_locator",
        {"element": 'textbox "Kullanıcı adı" (Giris.KULLANICI_ADI)', "ref": "e6"},
        {"rol": "textbox", "ad": "Kullanıcı adı"},
    ),
    (
        "app_generate_locator",
        {"element": 'textbox "Parola" (Giris.PAROLA)', "ref": "e8"},
        {"rol": "textbox", "ad": "Parola"},
    ),
    (
        "app_generate_locator",
        {"element": 'button "Giriş yap" (Giris.GIRIS_YAP)', "ref": "e9"},
        {"rol": "button", "ad": "Giriş yap"},
    ),
    (
        "app_type",
        {"element": 'textbox "Kullanıcı adı"', "ref": "e6", "text": "bayi3"},
        {"rol": "textbox", "ad": "Kullanıcı adı"},
    ),
    (
        "app_type",
        {"element": 'textbox "Parola"', "ref": "e8", "text": "Demo123!"},
        {"rol": "textbox", "ad": "Parola"},
    ),
    (
        "app_click",
        {"element": 'button "Giriş yap"', "ref": "e9"},
        {"rol": "button", "ad": "Giriş yap"},
    ),
    (
        "app_generate_locator",
        {"element": 'P-001 kartında textbox "Adet" (Katalog.ADET_ONEK)', "ref": "e25"},
        {"rol": "textbox", "ad": "Adet", "kapsam": 'text "P-001"'},
    ),
    (
        "app_generate_locator",
        {"element": 'P-001 kartında button "Sepete ekle" (Katalog.SEPETE_EKLE)', "ref": "e26"},
        {"rol": "button", "ad": "Sepete ekle", "kapsam": 'text "P-001"'},
    ),
    (
        "app_type",
        {"element": 'P-001 kartında textbox "Adet"', "ref": "e25", "text": "7"},
        {"rol": "textbox", "ad": "Adet", "kapsam": 'text "P-001"'},
    ),
    (
        "app_click",
        {"element": 'P-001 kartında button "Sepete ekle"', "ref": "e26"},
        {"rol": "button", "ad": "Sepete ekle", "kapsam": 'text "P-001"'},
    ),
    ("app_wait_for", {"text": "7 adet sepete eklendi."}, None),
    (
        "app_generate_locator",
        {"element": 'button "Sepet" (Menu.SEPET; sayaç içinde)', "ref": "e46"},
        {"rol": "button", "ad": "Sepet,"},
    ),
    ("app_click", {"element": 'button "Sepet"', "ref": "e46"}, {"rol": "button", "ad": "Sepet,"}),
    ("app_snapshot", {}, None),
]

_TPD1_C2_OUTPUT: dict[str, Any] = {
    "platform": "android",
    "step_mapping": [
        {
            "step_id": "S1",
            "po": "GirisEkrani",
            "method": "ac",
            "args": [],
            "verified": True,
            "evidence_ref": "Giriş ekranı (login-username, login-password, login-submit) "
            "app_launch sonrası",
        },
        {
            "step_id": "S2",
            "po": "GirisEkrani",
            "method": "girisYap",
            "args": ["bayi1", "Demo123!"],
            "verified": True,
            "evidence_ref": 'login-submit → katalog (product-list); oturum "Doğrulama Bayi" '
            "(doğrulama bayisi bayi3; case'in bayisi bayi1 eşleme argümanıdır)",
        },
        {
            "step_id": "S3",
            "po": "KatalogEkrani",
            "method": "sepeteEkle",
            "args": ["P-001", 7],
            "verified": True,
            "evidence_ref": "product-card-P-001 içinde qty-input-P-001 = 7, add-to-cart → "
            '"7 adet sepete eklendi."; nav-cart "Sepet, 7 ürün"',
        },
        {
            "step_id": "S4",
            "po": "KatalogEkrani",
            "method": "sepetiAc",
            "args": [],
            "verified": True,
            "evidence_ref": "nav-cart → sepet (cart-table); gözlenen: cart-line-qty-P-001 7, "
            "cart-line-free-P-001 1; ara toplam 175,00 TL; indirim 25,00 TL; toplam 150,00 TL",
        },
    ],
    "expects": [
        {"po": "SepetEkrani", "method": "dogrulaSatirAdedi", "args": ["P-001", 7]},
        {"po": "SepetEkrani", "method": "dogrulaBedavaAdet", "args": ["P-001", 1]},
        {"po": "SepetEkrani", "method": "dogrulaAraToplam", "args": ["175,00 TL"]},
        {"po": "SepetEkrani", "method": "dogrulaIndirim", "args": ["25,00 TL"]},
        {"po": "SepetEkrani", "method": "dogrulaToplam", "args": ["150,00 TL"]},
    ],
    "missing_methods": [],
}

NOTE = (
    "Adlandırılmış golden kayıt (REPLAY-MISS yedeği; 009 mobil-masaüstü Ş6). Model çıktısı "
    "(platform/step_mapping/expects/missing_methods) elle hazırlandı (canlı model çıktısı değil; "
    "ai_call.model = golden-elle). Araç adımları gerçek cihazda KAYDEDİLMEDİ: app-mcp araç "
    "sözleşmesine (docs/CIHAZ-ALTYAPISI.md §6) uyan sahte oturumda yürütülerek yazıldı "
    "(core/tests/unit/gateway/build_app_goldens.py). Ajan uygulamada doğrulama bayisiyle (bayi3) "
    "girer; case'teki giriş verisi eşleme argümanıdır. Kimlik doğrulaması: eylemde kullanılan her "
    "kimlik ilk kullanımdan önce app_generate_locator ile doğrulanır (dönen id Kimlikler "
    "testId'si). Ref'ler oturuma özgüdür: adımın `hedef` alanı (rol/ad/kapsam) REPLAY'de ref'in "
    "canlı son snapshot'tan çözülmesi içindir. Canlı modelle ve gerçek cihazda yeniden "
    "kaydedilmeli (TP_MODEL_MODE=record, make cihaz-baslat PLATFORM=android). Girdi beyanı "
    "(input_match) eşleşirse mod REPLAY (köken golden_matched), eşleşmezse REPLAY-MISS."
)


def _ozet(tool: str, metin: str) -> str:
    """Kayıttaki sonuç özeti: locator çıktısı aynen (REPLAY sapma denetimi okur), diğerleri tek
    satıra indirgenmiş kısa özet."""
    if tool == "app_generate_locator":
        return metin.strip()
    satirlar = [s.strip() for s in metin.splitlines() if s.strip() and not s.startswith("```")]
    satirlar = [s for s in satirlar if not s.startswith("###")]
    ozet = " | ".join(satirlar)
    return ozet if len(ozet) <= SUMMARY_MAX else ozet[: SUMMARY_MAX - 1] + "…"


def build_tpd1_c2_android() -> dict[str, Any]:
    web = load_golden("verify_and_map", "TPD-1-C2")
    oturum = FakeAppSession("android")
    ajan = AgentApp(oturum, platform="android", config=AgentConfig(), case_dealers=["bayi1"])
    steps = []
    for tool, args, hedef in _TPD1_C2:
        metin = ajan(tool, dict(args))
        govde = (
            metin.split("\n", 1)[1].rsplit("\n", 1)[0] if metin.startswith("<untrusted") else metin
        )
        adim: dict[str, Any] = {
            "tool": tool,
            "args": args,
            "result_summary": _ozet(tool, govde),
            "allowed": True,
        }
        if hedef:
            adim["hedef"] = hedef
        steps.append(adim)
    return {
        "kind": "agent",
        "purpose": PURPOSE,
        "golden": "TPD-1-C2-android",
        "note": NOTE,
        "input_match": {
            "sources": web["input_match"]["sources"],
            "case_text": web["input_match"]["case_text"],
        },
        "case": {**web["case"], "platform": "android"},
        "steps": steps,
        "output": _TPD1_C2_OUTPUT,
    }


def build_all() -> dict[str, dict[str, Any]]:
    return {"TPD-1-C2-android": build_tpd1_c2_android()}


def dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def golden_path(name: str, rules: Path = RULES) -> Path:
    return rules / "replay" / PURPOSE / "golden" / f"{name}.json"


def main() -> None:
    for name, data in build_all().items():
        path = golden_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump(data), encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
