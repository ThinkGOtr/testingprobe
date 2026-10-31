"""PR açıklaması: case metni ve model kanıtı güvenilmeyen girdidir (Markdown/HTML/bahsetme yok)."""

from __future__ import annotations

import re

from tp_core.features.codegen.prbody import hucre, kod, pr_body, pr_title

KOTU = "![x](https://tracker.example/p.png) [tık](http://evil) @org/team **kalın** <img src=x> #1"


def _kacissiz(metin: str, karakter: str) -> bool:
    return re.search(r"(?<!\\)" + re.escape(karakter), metin) is not None


def test_hucre_baglanti_gorsel_bahsetme_html_etkisiz() -> None:
    h = hucre(KOTU, 300)
    assert not _kacissiz(h, "[") and not _kacissiz(h, "]")  # bağlantı/görsel oluşmaz
    assert "![" not in h and not _kacissiz(h, "](")
    assert "@org" not in h and "@​org/team" in h  # bahsetme bildirimi gitmez
    assert "<" not in h and ">" not in h
    assert not _kacissiz(h, "*") and not _kacissiz(h, "#")
    assert "\n" not in hucre("a\nb|c`d") and "\\|" in hucre("a|b")


def test_kod_hucresi_satir_ici_kodu_kapatamaz() -> None:
    k = kod("x` @a | [b](c)")
    assert "`" not in k and "\\|" in k


def test_pr_govdesi_case_ve_kanit_enjeksiyonu() -> None:
    case = {
        "title": KOTU,
        "steps": [{"id": "S1", "action": KOTU, "expected": "x"}],
    }
    mapping = {
        "step_mapping": [
            {
                "step_id": "S1",
                "po": "LoginPage",
                "method": "login",
                "args": ["bayi1", "Demo123!"],
                "verified": True,
                "evidence_ref": "![b](https://beacon.example/x.png) @everyone",
            }
        ],
        "expects": [{"po": "CartPage", "method": "expectTotal", "args": ["125,00 TL"]}],
    }
    govde = pr_body(
        case_id="c",
        case_ref="TPD-1-C2",
        case=case,
        case_hash="h",
        onaylayan="@analist",
        story_key="TPD-1",
        test_key=None,
        browse_url="http://jira-sim:8080",
        mode_label="REPLAY",
        bundle_hash=None,
        repo_path="e2e/tests/generated/x.spec.ts",
        mapping=mapping,
        kaynaklar=["Toplam 125,00 TL ![z](http://q) @x"],
        kontrol=None,
        duzeltme_turu=0,
        agent_dealer_note=None,
        audit_head="a" * 64,
        template_hash="t" * 64,
        mapping_hash="m" * 64,
        ajan_bayileri={"bayi1": "bayi3"},
    )
    # Tek bilinçli bağlantı: Story → Jira (adres yapılandırmadan, anahtar kaçışlı).
    assert len(re.findall(r"(?<!\\)\]\(", govde)) == 1
    assert "](http://jira-sim:8080/browse/TPD-1)" in govde
    assert "![" not in govde and not _kacissiz(govde.replace("[TPD-1](", ""), "[")
    assert "@everyone" not in govde and "@analist" not in govde and "@x" not in govde
    assert "<img" not in govde
    # Ajan bayisi yerine geçmesi doğrulama satırında açık.
    assert "ajan bayisi bayi3 ile; test bayi1 ile koşar" in govde
    assert pr_title("TPD-1-C2", "a\nb") == "[TPD-1-C2] a b (AI-generated)"
