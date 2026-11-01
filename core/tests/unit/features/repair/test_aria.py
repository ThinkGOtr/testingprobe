"""Son yeşil aria doğrulaması: 0 eşleşme, çoklu eşleşme, kapsamlı eşleşme (§8.7)."""

from __future__ import annotations

from tp_core.features.repair import aria

KATALOG = """- main:
  - heading "Katalog" [level=1]
  - generic:
    - article "Portakal Gazozu 1L":
      - heading "Portakal Gazozu 1L" [level=2]
      - spinbutton "Adet"
      - button "Sepete ekle" [ref=e12]
    - article "Kola 330 ml":
      - spinbutton "Adet"
      - button "Sepete ekle" [ref=e17]
"""


def test_kapsamli_her_kapsayicida_tek() -> None:
    s = aria.dogrula(KATALOG, "button", "Sepete ekle", kapsayici_rol="article", kapsamli=True)
    assert s.gecerli and s.eslesme == 2 and s.kapsayici_sayisi == 2


def test_kapsamsiz_coklu_eslesme_gecersiz() -> None:
    s = aria.dogrula(KATALOG, "button", "Sepete ekle")
    assert not s.gecerli and s.eslesme == 2 and "2 kez" in s.neden


def test_sifir_eslesme_gecersiz() -> None:
    s = aria.dogrula(KATALOG, "button", "Sepete koy", kapsayici_rol="article", kapsamli=True)
    assert not s.gecerli and s.eslesme == 0
    # rol farklıysa da eşleşme yok (yanlış elemana onarım önlenir)
    assert not aria.dogrula(KATALOG, "link", "Sepete ekle").gecerli


def test_kapsayicida_iki_eleman_gecersiz() -> None:
    metin = KATALOG.replace(
        '      - button "Sepete ekle" [ref=e17]',
        '      - button "Sepete ekle" [ref=e17]\n      - button "Sepete ekle" [ref=e18]',
    )
    s = aria.dogrula(metin, "button", "Sepete ekle", kapsayici_rol="article", kapsamli=True)
    assert not s.gecerli and "2 kez" in s.neden


def test_kapsayici_disinda_eleman_gecersiz() -> None:
    metin = KATALOG + '  - button "Sepete ekle"\n'
    s = aria.dogrula(metin, "button", "Sepete ekle", kapsayici_rol="article", kapsamli=True)
    assert not s.gecerli and "dışında" in s.neden


def test_tekil_eleman_ve_error_context_bicimi() -> None:
    md = (
        "# Test info\n\n- Name: x\n\n# Page snapshot\n\n```yaml\n"
        '- navigation:\n  - link "Sepet"\n  - link "Katalog"\n```\n'
    )
    s = aria.dogrula(md, "link", "Sepet")
    assert s.gecerli and s.eslesme == 1
    assert not aria.dogrula(md, "link", "").gecerli


def test_kapsayici_rolu_bilinmiyorsa_gecersiz() -> None:
    s = aria.dogrula(KATALOG, "button", "Sepete ekle", kapsamli=True)
    assert not s.gecerli
