"""İç kod → kullanıcı etiketi (B6.1 F-B6-01): araç çıktısı, cevap metni ve denetim kaynakları."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from tp_core.features.assistant import denetim, ic_terimler, sonislem


def test_failure_alanlari_etiketlenir_merged_ture_gore() -> None:
    bug = ic_terimler.etiketle(
        "failure",
        {
            "sinif": "product_defect",
            "karar_kaynagi": "rule",
            "kural": "karar_tablosu",
            "oneri_turu": "bug_draft",
            "oneri_durumu": "merged",
        },
    )
    assert bug == {
        "sinif": "Ürün hatası",
        "karar_kaynagi": "otomatik kural",
        "kural": "onaylı karar tablosu kuralı",
        "oneri_turu": "bug taslağı",
        "oneri_durumu": (
            "karar verildi; bug Jira'ya yazıldı (yeni kayıt ya da mevcut kayda bağlandı)"
        ),
    }
    onarim = ic_terimler.etiketle(
        "failure",
        {
            "sinif": "test_maintenance",
            "kural": "test_maintenance/locator",
            "oneri_turu": "locator_fix",
            "oneri_durumu": "merged",
        },
    )
    assert onarim["oneri_durumu"] == "onarım PR'ı birleştirildi"
    assert onarim["kural"] == "Test bakımı kuralı · locator değişikliği"
    # Bilinmeyen kod ve boş değer olduğu gibi kalır; girdi değişmez.
    giris = {"sinif": "yeni_sinif", "oneri_durumu": None}
    assert ic_terimler.etiketle("failure", giris) == giris
    assert ic_terimler.etiketle("bug_draft", {"durum": "published", "karar": "link"}) == {
        "durum": "Jira'da",
        "karar": "mevcut Jira kaydına bağla",
    }


def test_cevap_metninde_ic_kod_etikete_cevrilir() -> None:
    km = ic_terimler.kullanici_metni
    assert km("Bu hatanın sınıfı product_defect (ürün hatası adayı).") == (
        "Bu hatanın sınıfı ürün hatası adayı."
    )
    assert km('Sınıf "product_defect" (Ürün hatası).') == "Sınıf Ürün hatası."
    assert km("deterministik kural (karar_tablosu) ile") == (
        "deterministik kural (onaylı karar tablosu kuralı) ile"
    )
    assert km("oneri_turu bug_draft ve oneri_durumu") == "öneri türü bug taslağı ve öneri durumu"
    # Yol, dosya adı ve daha uzun tanımlayıcı değişmez.
    for metin in (
        "core/src/tp_core/features/triage/product_defect.py",
        "product_defect_orani yüksek",
        "Kural adı yok.",
    ):
        assert km(metin) == metin


def _baglam() -> Any:
    return sonislem.SonIslemBaglami()


def test_son_islem_bloklari_cevirir_kod_blogu_ve_alintiyi_degil() -> None:
    cevap = sonislem.isle(
        {
            "cevap_bloklari": [
                {"tur": "paragraf", "metin": "Sınıf product_defect.", "maddeler": []},
                {"tur": "liste", "metin": "", "maddeler": ["oneri_durumu: karar verildi"]},
                {"tur": "kod", "metin": "sinif == 'product_defect'", "maddeler": []},
            ],
            "guven": "orta",
            "kaynaklar": [{"tur": "genel_bilgi", "ref": "", "alinti": "product_defect"}],
        },
        _baglam(),
    )
    bloklar = cevap["cevap_bloklari"]
    assert bloklar[0]["metin"] == "Sınıf Ürün hatası."
    assert bloklar[1]["maddeler"] == ["öneri durumu: karar verildi"]
    assert bloklar[2]["metin"] == "sinif == 'product_defect'"
    assert cevap["kaynaklar"][0]["alinti"] == "product_defect"


def _kanit(kimlik: str, govde: str) -> Any:
    return SimpleNamespace(
        kimlik=kimlik,
        metin=f'[kanit:{kimlik}]\n<untrusted kind="data" source="x:{kimlik}" id="ab">\n'
        f'{govde}\n</untrusted id="ab">',
    )


def test_denetim_dogrulanmis_kanitin_tam_ciktisini_alir() -> None:
    """Denetim, kaynak gösterilen ve doğrulanan kanıtın tamamını görür; doğrulanmamış ya da
    kaynak gösterilmeyen kanıt verilmez (kontrol gevşemez)."""
    havuz = [
        _kanit("k1", "sinif: Ürün hatası\nkanit.beklenen: 0\nkanit.gerceklesen: 1"),
        _kanit("k2", "gizli: kaynak gösterilmedi"),
        _kanit("k3", "durum: Jira'da"),
    ]
    cevap = {
        "kaynaklar": [
            {
                "tur": "probe_verisi",
                "ref": "k1",
                "alinti": "sinif: Ürün hatası",
                "dogrulandi": True,
            },
            {"tur": "probe_verisi", "ref": "k1", "alinti": "kanit.beklenen: 0", "dogrulandi": True},
            {"tur": "probe_verisi", "ref": "k3", "alinti": "uydurma", "dogrulandi": False},
            {"tur": "urun_kodu", "ref": "a.py:1", "alinti": "x = 1", "dogrulandi": True},
        ]
    }
    kanitlar = denetim.kanit_metinleri(cevap, havuz)
    assert kanitlar == {"k1": "sinif: Ürün hatası\nkanit.beklenen: 0\nkanit.gerceklesen: 1"}
    ozet = denetim.kaynak_ozetleri(cevap, kanitlar)
    assert len(ozet) == 4
    assert "kanıt k1 (aracın tam çıktısı)" in ozet[0] and "kanit.gerceklesen: 1" in ozet[0]
    assert "aracın tam çıktısı" not in "".join(ozet[1:])  # kimlik başına bir kez
    assert "Jira'da" not in "".join(ozet) and "gizli" not in "".join(ozet)
    assert denetim.kaynak_ozetleri(cevap) == [o.split("\n")[0] for o in ozet]
    assert denetim.kanit_metinleri(cevap, None) == {}
