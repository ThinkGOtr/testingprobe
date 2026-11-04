"""Deterministik son işlem, soru sınıflandırması ve hata sözlüğü (AI-ASISTAN-PLANI §7.3, §5.4,
§10.2, §17.5; §13 "Birim"). DB'siz: kanıt havuzu gerçek sarmalayıcıyla, dış okumalar sahte
doğrulayıcıyla."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Sequence
from typing import Any

import pytest

from tp_core.features.assistant import siniflandir, sonislem, sozluk
from tp_core.features.assistant.sonislem import SonIslemBaglami, isle
from tp_core.features.assistant.tools.base import (
    AracBaglami,
    AracSarmalayici,
    AracSonucu,
    KanitHavuzu,
)
from tp_core.features.requirements.datatools import masked_digest
from tp_core.gateway.masking import MaskingSession, PiiMasker

REQ = "0f3c8a1e-2b4d-4c6e-8f00-112233445566"
UUID_RE_ROTA = f"/gereksinimler/{REQ}/caseler"


# ------------------------------------------------------------------ yardımcılar


def _oturum(maske: bool = True) -> MaskingSession:
    return PiiMasker(enabled=maske).new_session()


def _baglam(oturum: MaskingSession) -> AracBaglami:
    return AracBaglami(kullanici_id=uuid.uuid4(), rol="analyst", oturum=oturum, db=lambda: None)


def _havuz_ile(
    oturum: MaskingSession, *sonuclar: tuple[str, AracSonucu], mevcut: dict[str, str] | None = None
) -> tuple[KanitHavuzu, list[str]]:
    """Gerçek sarmalayıcıdan geçirerek havuza kanıt ekler; modele giden metinleri döndürür."""
    havuz = KanitHavuzu()
    yeni = {ad: (lambda _b, _s=s, **_a: _s) for ad, s in sonuclar}
    mevcut_araclar = {ad: (lambda _a, _m=m: _m) for ad, m in (mevcut or {}).items()}
    sar = AracSarmalayici(
        _baglam(oturum),
        yeni=yeni,
        mevcut=mevcut_araclar,
        mevcut_turleri={"db_query": "uygulama_verisi"},
        havuz=havuz,
    )
    giden = [sar(ad, {}) for ad, _ in sonuclar] + [sar(ad, {}) for ad in mevcut or {}]
    return havuz, giden


class SahteDogrulayici:
    def __init__(
        self,
        urun: dict[str, list[str]] | None = None,
        uygulama: dict[str, list[str]] | None = None,
        satirlar: Sequence[Sequence[Any]] = (),
        bekle_s: float = 0.0,
    ) -> None:
        self.urun = urun or {}
        self.uygulama = uygulama or {}
        self.satirlar = satirlar
        self.bekle_s = bekle_s
        self.sorgular: list[str] = []

    def urun_satirlari(self, yol: str, bas: int, son: int) -> list[str] | None:
        dosya = self.urun.get(yol)
        if dosya is None or son > len(dosya):
            return None
        return dosya[bas - 1 : son]

    def uygulama_satirlari(self, yol: str) -> list[str] | None:
        return self.uygulama.get(yol)

    def veri_sorgula(self, sql: str) -> Sequence[Sequence[Any]]:
        self.sorgular.append(sql)
        if self.bekle_s:
            time.sleep(self.bekle_s)
        return self.satirlar


def _cikti(**alan: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "cevap_bloklari": [{"tur": "paragraf", "metin": "Cevap.", "maddeler": []}],
        "guven": "yuksek",
        "kaynaklar": [],
        "yonlendirmeler": [],
        "jira_anahtarlari": [],
        "eylem_reddi": False,
        "oneriler": [],
    }
    out.update(alan)
    return out


def _kaynak(tur: str, ref: str, alinti: str) -> dict[str, str]:
    return {"tur": tur, "ref": ref, "alinti": alinti}


# ------------------------------------------------------------------ metin


@pytest.mark.parametrize(
    ("girdi", "beklenen", "olmayan"),
    [
        ("Bkz. https://evil.example/x?d=1 lütfen", "Bkz. [bağlantı kaldırıldı] lütfen", "evil"),
        ("[tıkla](https://evil.example)", "tıkla", "evil"),
        ("![resim](https://evil.example/p.png?q=gizli)", "resim", "gizli"),
        ("javascript:alert(1) çalıştır", "[bağlantı kaldırıldı] çalıştır", "alert"),
        ("data:text/html;base64,PHNjcmlwdD4= aç", "[bağlantı kaldırıldı] aç", "base64"),
        ("www.evil.example adresine git", "[bağlantı kaldırıldı] adresine git", "evil"),
        ("ftp://kullanici:parola@host/dosya", "[bağlantı kaldırıldı]", "parola"),
        # Şemasız alan adı + yol (enjeksiyonla "şu adrese gidip giriş yapın" metni).
        (
            "Önce evil.example.com/login adresinde oturum açın.",
            "Önce [bağlantı kaldırıldı] adresinde oturum açın.",
            "evil",
        ),
        ("Bkz. destek.ornek.com.tr:8443/giris", "Bkz. [bağlantı kaldırıldı]", "destek"),
        # IDN/homograf (Kiril "е"), listede olmayan TLD + yol, çıplak IPv4 + port/yol.
        ("Bkz. \u0435vil.com/login", "Bkz. [bağlantı kaldırıldı]", "vil"),
        ("Bkz. göz.com/x", "Bkz. [bağlantı kaldırıldı]", "göz"),
        ("Bkz. evil.zip/login", "Bkz. [bağlantı kaldırıldı]", "evil"),
        ("Bkz. evil.example.page/reset", "Bkz. [bağlantı kaldırıldı]", "evil"),
        ("Bkz. 10.1.2.3:8080/login giriş", "Bkz. [bağlantı kaldırıldı] giriş", "10.1"),
        ("Bkz. 10.1.2.3/panel", "Bkz. [bağlantı kaldırıldı]", "10.1"),
        ("Bkz. paypal.com.evil.io/a", "Bkz. [bağlantı kaldırıldı]", "evil"),
        # Gizlenmiş nokta (ideografik/tam genişlik, parantezli) ve protokolsüz "//" adres.
        (
            "Şifrenizi yenileyin: evil\u3002com/reset",
            "Şifrenizi yenileyin: [bağlantı kaldırıldı]",
            "evil",
        ),
        (
            "Bkz. evil\uff0ecom ve evil\uff61net",
            "Bkz. [bağlantı kaldırıldı] ve [bağlantı kaldırıldı]",
            "evil",
        ),
        ("giriş: evil[.]com/login", "giriş: [bağlantı kaldırıldı]", "evil"),
        ("Bkz. evil(.)example{.}page/x", "Bkz. [bağlantı kaldırıldı]", "evil"),
        ("Bkz. //evil.com/x hemen", "Bkz. [bağlantı kaldırıldı] hemen", "evil"),
        ("Bkz. //evil.zip", "Bkz. [bağlantı kaldırıldı]", "evil"),
    ],
)
def test_metin_url_ve_markdown_duzlesir(girdi: str, beklenen: str, olmayan: str) -> None:
    cevap = isle(
        _cikti(cevap_bloklari=[{"tur": "liste", "metin": girdi, "maddeler": [girdi]}]),
        SonIslemBaglami(),
    )
    blok = cevap["cevap_bloklari"][0]
    assert blok["metin"] == beklenen and blok["maddeler"] == [beklenen]
    assert olmayan not in str(cevap)


@pytest.mark.parametrize(
    "metin",
    [
        "review-portal/src/pages/Script.tsx:12",
        "next.config.app.ts ve README.md, app.py",
        "tp_core.features.assistant.flow modülü",
        "kampanya.py:3 satırı, sürüm v1.2.3",
        "po.kisi@ornek.com adresine yazın",
        "src/app.io dosyası",
        "flow.cevapla ve self.b.rol çağrısı",
        "sürüm 1.2.3.4 ve docs/AI-PLAN.md",
        "Node.js/React ve config.yaml/anahtar",
        "// yorum: config.ts ve //app.ts satırı",
        "dizi[.] ve f(.) gösterimi, src//app.io",
    ],
)
def test_semasiz_alan_deseni_dosya_ve_kod_adlarina_dokunmaz(metin: str) -> None:
    assert sonislem.duz_metin(metin) == metin


def test_metin_toplam_6000_karakterde_kirpilir_ve_blok_turu_korunur() -> None:
    bloklar = [{"tur": "paragraf", "metin": "a" * 4000, "maddeler": []} for _ in range(3)]
    bloklar.append({"tur": "bilinmeyen", "metin": "b", "maddeler": ["x"]})
    cevap = isle(_cikti(cevap_bloklari=bloklar), SonIslemBaglami())
    toplam = sum(len(b["metin"]) + sum(map(len, b["maddeler"])) for b in cevap["cevap_bloklari"])
    assert toplam <= sonislem.METIN_AZAMI
    assert len(cevap["cevap_bloklari"]) == 2
    assert cevap["cevap_bloklari"][1]["metin"].endswith("…")
    # Liste dışı blokta madde tutulmaz; bilinmeyen tür paragraf olur.
    tek = isle(_cikti(cevap_bloklari=[bloklar[-1]]), SonIslemBaglami())
    assert tek["cevap_bloklari"] == [{"tur": "paragraf", "metin": "b", "maddeler": []}]


# ------------------------------------------------------------------ linkler


def test_yalniz_rota_kalibina_uyan_ic_rota_baglanti_olur() -> None:
    cevap = isle(
        _cikti(
            yonlendirmeler=[
                {"etiket": "Caseler", "rota": UUID_RE_ROTA},
                {"etiket": "Dış", "rota": "https://evil.example/gereksinimler"},
                {"etiket": "Protokolsüz", "rota": "//evil.example/x"},
                {"etiket": "Bilinmeyen", "rota": "/yonetim/kullanicilar"},
                {"etiket": "Gezinme", "rota": "/gereksinimler/../denetim"},
                {"etiket": "Sorgulu", "rota": "/kosular?x=1"},
                {"etiket": "JS", "rota": "javascript:alert(1)"},
                {"etiket": "Tekrar", "rota": UUID_RE_ROTA},
                {"etiket": "[Denetim](https://evil.example)", "rota": "/denetim"},
            ]
        ),
        SonIslemBaglami(),
    )
    assert cevap["yonlendirmeler"] == [
        {"etiket": "Caseler", "rota": UUID_RE_ROTA},
        {"etiket": "Denetim", "rota": "/denetim"},
    ]


@pytest.mark.parametrize(
    ("rol", "beklenen"),
    [
        ("tester", ["/kosular"]),  # /demo yalnız presenter, /claude-code yalnız analyst
        ("presenter", ["/demo", "/kosular"]),
        ("analyst", ["/claude-code", "/kosular"]),
        (None, ["/demo", "/claude-code", "/kosular"]),  # rol bilinmiyor → süzgeç yok
    ],
)
def test_yonlendirme_rolun_acamadigi_ekrana_dusmez(rol: str | None, beklenen: list[str]) -> None:
    """`oneri_eylemi` rota süzgeciyle aynı: rolün açamadığı ekrana "Git:" düğmesi çıkmaz."""
    cevap = isle(
        _cikti(
            yonlendirmeler=[
                {"etiket": "Demo", "rota": "/demo"},
                {"etiket": "Claude Code", "rota": "/claude-code"},
                {"etiket": "Koşular", "rota": "/kosular"},
            ]
        ),
        SonIslemBaglami(rol=rol),
    )
    assert [y["rota"] for y in cevap["yonlendirmeler"]] == beklenen


def test_bilinmeyen_jira_anahtari_baglanti_almaz() -> None:
    sorulan: list[str] = []

    def bilinir(a: str) -> bool:
        sorulan.append(a)
        return a == "TPD-3"

    b = SonIslemBaglami(
        bilinen_anahtar=bilinir, kayit_adresi=lambda a: f"https://jira.ornek/browse/{a}"
    )
    cevap = isle(
        _cikti(jira_anahtarlari=["TPD-3", "TPD-404", "tpd-3", "TPD-3/../x", "TPD-３", "TPD-3"]),
        b,
    )
    assert cevap["jira_anahtarlari"] == ["TPD-3"]
    assert cevap["jira_baglantilari"] == [
        {"anahtar": "TPD-3", "url": "https://jira.ornek/browse/TPD-3"}
    ]
    # Biçimi bozuk anahtar için kayıt sorgusu bile yapılmaz; aynı anahtar bir kez sorulur.
    assert sorulan == ["TPD-3", "TPD-404"]


# ------------------------------------------------------------------ kaynak doğrulama


def test_urun_kodu_ve_dokuman_ref_bicimleri() -> None:
    dosya = ["def f():", "    return 'Yalnızca mühendis rolü'", "", "# son"]
    d = SahteDogrulayici(urun={"review-portal/src/x.tsx": dosya, "docs/ONBOARDING.md": dosya})
    cevap = isle(
        _cikti(
            kaynaklar=[
                _kaynak(
                    "urun_kodu", "review-portal/src/x.tsx:2", "return 'Yalnızca  mühendis rolü'"
                ),
                _kaynak("dokuman", "docs/ONBOARDING.md:1-2", "def f(): return"),
                _kaynak("urun_kodu", "review-portal/src/x.tsx:9", "son"),  # satır dışı
                _kaynak("urun_kodu", "review-portal/src/x.tsx:2", "uydurma alıntı metni"),
                _kaynak("urun_kodu", "yok.py:1", "def f():"),
                _kaynak("urun_kodu", "review-portal/src/x.tsx", "def f():"),  # satırsız ref
                _kaynak("urun_kodu", "review-portal/src/x.tsx:2", "2| return"),  # satır öneki
            ]
        ),
        SonIslemBaglami(dogrulayici=d),
    )
    assert [k["dogrulandi"] for k in cevap["kaynaklar"]] == [
        True,
        True,
        False,
        False,
        False,
        False,
        False,
    ]
    # Doğrulanmayan kaynak silinmez; nedeni ve sha256 `dogrulama`'da.
    assert len(cevap["kaynaklar"]) == 7
    assert cevap["dogrulama"]["review-portal/src/x.tsx:2"]["dogrulandi"] is True
    assert len(cevap["dogrulama"]["docs/ONBOARDING.md:1-2"]["sha256"]) == 64


def test_kod_okumasi_kalan_sureyle_sinirli() -> None:
    """§7.3 ürün/uygulama kodu doğrulaması `bitis`e bağlıdır: süre bittiyse forge hiç okunmaz,
    yavaş forge kalan süreyi aşarsa "zaman aşımı" (cevap 120 sn emniyetine takılıp kaybolmaz)."""

    class Yavas(SahteDogrulayici):
        def __init__(self, bekle_s: float, **kw: Any) -> None:
            super().__init__(**kw)
            self.okunan: list[str] = []
            self.bekle = bekle_s

        def uygulama_satirlari(self, yol: str) -> list[str] | None:
            self.okunan.append(yol)
            time.sleep(self.bekle)
            return super().uygulama_satirlari(yol)

        def urun_satirlari(self, yol: str, bas: int, son: int) -> list[str] | None:
            self.okunan.append(yol)
            time.sleep(self.bekle)
            return super().urun_satirlari(yol, bas, son)

    kaynaklar = [
        _kaynak("uygulama_kodu", "src/k.py:1", "x = 1"),
        _kaynak("urun_kodu", "docs/a.md:1", "x = 1"),
    ]
    dosya = {"src/k.py": ["x = 1"]}
    bitmis = Yavas(0.0, uygulama=dosya, urun={"docs/a.md": ["x = 1"]})
    cevap = isle(
        _cikti(kaynaklar=kaynaklar),
        SonIslemBaglami(dogrulayici=bitmis, bitis=time.monotonic() - 1),
    )
    assert [k["neden"] for k in cevap["kaynaklar"]] == ["zaman aşımı"] * 2
    assert bitmis.okunan == []
    yavas = Yavas(2.0, uygulama=dosya)
    t0 = time.monotonic()
    cevap = isle(
        _cikti(kaynaklar=kaynaklar[:1]), SonIslemBaglami(dogrulayici=yavas, bitis=t0 + 0.8)
    )
    assert cevap["kaynaklar"][0]["neden"] == "zaman aşımı"
    assert time.monotonic() - t0 < 1.8
    # Süre yeterliyse doğrulama aynen çalışır.
    hizli = Yavas(0.0, uygulama=dosya)
    cevap = isle(
        _cikti(kaynaklar=kaynaklar[:1]),
        SonIslemBaglami(dogrulayici=hizli, bitis=time.monotonic() + 30),
    )
    assert cevap["kaynaklar"][0]["dogrulandi"] is True


def test_kisa_alinti_yalniz_tam_satirsa_gecer() -> None:
    d = SahteDogrulayici(uygulama={"src/k.py": ["x = 1", "return indirim * 0.9"]})
    cevap = isle(
        _cikti(
            kaynaklar=[
                _kaynak("uygulama_kodu", "src/k.py:1", "x = 1"),
                _kaynak("uygulama_kodu", "src/k.py:2", "0.9"),
                _kaynak("uygulama_kodu", "src/k.py:2", "indirim * 0.9"),
                _kaynak("uygulama_kodu", "src/k.py:3", "x"),
            ]
        ),
        SonIslemBaglami(dogrulayici=d),
    )
    assert [k["dogrulandi"] for k in cevap["kaynaklar"]] == [True, False, True, False]


def test_havuz_kaynagi_turu_uyusmali_ve_500_karakter_sonrasi_alinti_dogrulanir() -> None:
    oturum = _oturum()
    uzun = "x" * 700 + "\nsatır: KAPI-BEKLIYOR PO onayı\n"
    havuz, _ = _havuz_ile(
        oturum,
        ("probe_get", AracSonucu(uzun, kanit_turu="probe_verisi")),
        ("ci_log", AracSonucu("lint: E501 satır çok uzun", kanit_turu="ci_log", tur="ci_log")),
    )
    cevap = isle(
        _cikti(
            kaynaklar=[
                _kaynak("probe_verisi", "k1", "KAPI-BEKLIYOR PO onayı"),
                _kaynak("ci_log", "k2", "E501 satır çok uzun"),
                _kaynak("jira", "k1", "KAPI-BEKLIYOR PO onayı"),  # tür uyuşmaz
                _kaynak("probe_verisi", "k9", "KAPI-BEKLIYOR"),  # kimlik yok
                _kaynak("probe_verisi", "k1", "uydurma ifade burada"),
            ]
        ),
        SonIslemBaglami(havuz=havuz, oturum=oturum),
    )
    assert [k["dogrulandi"] for k in cevap["kaynaklar"]] == [True, True, False, False, False]
    assert cevap["dogrulama"]["k1"]["sha256"] == havuz.al("k1").sha256


def test_son_islem_pii_iceren_probe_alintisini_maskeleme_acikken_dogrular() -> None:
    """Son işlem katmanı: maskeli havuzdaki kanıta ham değerli alıntı `isle` ile doğrulanır
    (sarmalayıcı katmanı `test_arac_sarmalayici`'da)."""
    oturum = _oturum(maske=True)
    havuz, giden = _havuz_ile(
        oturum,
        ("probe_get", AracSonucu("po_cevaplari: iletişim po.kisi@ornek.com")),
    )
    assert "po.kisi@ornek.com" not in giden[0]  # modele maskeli gitti
    # Geçit son çıktının maskesini açar: alıntı ham değer taşır.
    cevap = isle(
        _cikti(kaynaklar=[_kaynak("probe_verisi", "k1", "iletişim po.kisi@ornek.com")]),
        SonIslemBaglami(havuz=havuz, oturum=oturum),
    )
    assert cevap["kaynaklar"][0]["dogrulandi"] is True


def test_son_islem_havuzu_tek_oturumda_yer_tutuculari_tutarli_acar() -> None:
    """Son işlem havuz yardımcısı (`_havuz_ile`) üzerinden: soru ve araç çıktıları tek oturumda
    tutarlı yer tutucu alır (sarmalayıcının kendisi `test_arac_sarmalayici`'da)."""
    oturum = _oturum(maske=True)
    soru, _ = oturum.mask_text("Soru: ali@ornek.com nerede?")
    _, giden = _havuz_ile(
        oturum,
        ("probe_get", AracSonucu("sahip: veli@ornek.com")),
        ("probe_list", AracSonucu("ilgili: ayse@ornek.com, ali@ornek.com")),
    )
    yer = {soru.split()[1], giden[0].split("sahip: ")[1].split()[0]}
    assert len(yer) == 2 and all(y.startswith("<<PII_EMAIL_") for y in yer)
    assert "<<PII_EMAIL_1>>" in giden[1]  # aynı e-posta aynı yer tutucu
    assert oturum.unmask(giden[1]).count("ali@ornek.com") == 1


def test_mevcut_db_query_sql_yeniden_calistirilir_5_siniri_ve_zaman_asimi() -> None:
    oturum = _oturum(maske=True)
    satirlar = [("ABC", 10)]
    ozet = masked_digest(satirlar)
    db_cikti = f"query: SELECT kod, oran FROM kampanya\nresult_digest: {ozet}\n<untrusted>…"
    havuz = KanitHavuzu()
    sar = AracSarmalayici(
        _baglam(oturum),
        mevcut={"db_query": lambda _a: db_cikti},
        mevcut_turleri={"db_query": "uygulama_verisi"},
        havuz=havuz,
    )
    for _ in range(7):
        sar("db_query", {})
    d = SahteDogrulayici(satirlar=satirlar)
    cevap = isle(
        _cikti(kaynaklar=[_kaynak("uygulama_verisi", f"k{i}", "") for i in range(1, 8)]),
        SonIslemBaglami(havuz=havuz, oturum=oturum, dogrulayici=d),
    )
    assert [k["dogrulandi"] for k in cevap["kaynaklar"]] == [True] * 5 + [False] * 2
    assert cevap["kaynaklar"][5]["neden"] == "doğrulama sınırı (5 sorgu)"
    assert d.sorgular == ["SELECT kod, oran FROM kampanya"] * 5
    # Sonuç değişmişse özet tutmaz.
    farkli = isle(
        _cikti(kaynaklar=[_kaynak("uygulama_verisi", "k1", "")]),
        SonIslemBaglami(
            havuz=havuz, oturum=oturum, dogrulayici=SahteDogrulayici(satirlar=[("XYZ", 5)])
        ),
    )
    assert farkli["kaynaklar"][0]["dogrulandi"] is False
    # `bitis` geçmişse sorgu hiç çalışmaz; yavaş sorgu kalan süreyi aşarsa "zaman aşımı".
    simdi = time.monotonic()
    bitmis = SahteDogrulayici(satirlar=satirlar)
    zaman = isle(
        _cikti(kaynaklar=[_kaynak("uygulama_verisi", "k1", "")]),
        SonIslemBaglami(havuz=havuz, oturum=oturum, dogrulayici=bitmis, bitis=simdi - 1),
    )
    assert zaman["kaynaklar"][0]["neden"] == "zaman aşımı" and bitmis.sorgular == []
    yavas = SahteDogrulayici(satirlar=satirlar, bekle_s=2.0)
    t0 = time.monotonic()
    zaman2 = isle(
        _cikti(kaynaklar=[_kaynak("uygulama_verisi", "k1", "")]),
        SonIslemBaglami(havuz=havuz, oturum=oturum, dogrulayici=yavas, bitis=t0 + 0.8),
    )
    assert zaman2["kaynaklar"][0]["neden"] == "zaman aşımı"
    assert time.monotonic() - t0 < 1.8


def test_dogrulama_hatasi_cevabi_dusurmez() -> None:
    class Patlayan(SahteDogrulayici):
        def urun_satirlari(self, yol: str, bas: int, son: int) -> list[str] | None:
            raise RuntimeError("gizli /opt/tp-bilgi yolu")

    cevap = isle(
        _cikti(kaynaklar=[_kaynak("urun_kodu", "a.py:1", "x = 1")]),
        SonIslemBaglami(dogrulayici=Patlayan()),
    )
    assert cevap["kaynaklar"][0]["dogrulandi"] is False
    assert cevap["kaynaklar"][0].get("neden") in (None, "doğrulanamadı")
    assert "gizli" not in str(cevap)
    assert "RuntimeError" not in str(cevap)  # istisna adı yalnız kayda


# ------------------------------------------------------------------ güven tablosu


@pytest.mark.parametrize(
    ("guven", "kaynaklar", "urune_ozgu", "toparlama", "beklenen"),
    [
        ("yuksek", [("probe_verisi", True)], True, False, sonislem.DOGRULANDI),
        ("orta", [("probe_verisi", True)], False, False, sonislem.DOGRULANDI),
        ("dusuk", [("probe_verisi", True)], True, False, sonislem.KISMEN),
        ("yuksek", [("genel_bilgi", False)], True, False, sonislem.KISMEN),
        ("yuksek", [("probe_verisi", False)], True, False, sonislem.EMIN_DEGIL),
        ("yuksek", [], True, False, sonislem.EMIN_DEGIL),
        ("yuksek", [("probe_verisi", True)], True, True, sonislem.EMIN_DEGIL),
        ("yuksek", [("genel_bilgi", False)], False, False, sonislem.GENEL_BILGI),
        ("yuksek", [], False, False, sonislem.GENEL_BILGI),
        ("yuksek", [("urun_kodu", False)], False, False, sonislem.EMIN_DEGIL),
    ],
)
def test_guven_gosterimi_tablosu(
    guven: str,
    kaynaklar: list[tuple[str, bool]],
    urune_ozgu: bool,
    toparlama: bool,
    beklenen: str,
) -> None:
    ks = [{"tur": t, "dogrulandi": d} for t, d in kaynaklar]
    assert (
        sonislem.guven_gosterimi(guven, ks, urune_ozgu=urune_ozgu, toparlama=toparlama) == beklenen
    )


def test_urune_ozgu_soruda_yalniz_genel_bilgi_kismen_ve_not() -> None:
    cevap = isle(
        _cikti(kaynaklar=[_kaynak("genel_bilgi", "", "Genel QA bilgisi")]),
        SonIslemBaglami(urune_ozgu=True),
    )
    assert cevap["guven_gosterimi"] == sonislem.KISMEN
    assert sonislem.NOT_URUN_KAYNAGI_YOK in cevap["notlar"]
    assert cevap["urune_ozgu"] is True
    toparlandi = isle(_cikti(), SonIslemBaglami(toparlama=True))
    assert toparlandi["guven_gosterimi"] == sonislem.EMIN_DEGIL and toparlandi["toparlama"]


# ------------------------------------------------------------------ öneriler


def _oneri(baslik: str, eylem: dict[str, Any], neden: str = "Çünkü") -> dict[str, Any]:
    tam = {"tur": "bilgi", "rota": None, "anahtar": None, "taslak": None}
    tam.update(eylem)
    return {"baslik": baslik, "neden": neden, "eylem": tam}


def _oneri_baglami(**kw: Any) -> SonIslemBaglami:
    kw.setdefault("kip", "oneri")
    kw.setdefault("bilinen_anahtar", lambda a: a == "TPD-3")
    kw.setdefault("kayit_adresi", lambda a: f"https://jira.ornek/browse/{a}")
    kw.setdefault("yeni_kayit_adresi", "https://jira.ornek/secure/CreateIssue!default.jspa")
    kw.setdefault("proje", "TPD")
    return SonIslemBaglami(**kw)


def test_soru_kipinde_oneriler_bosaltilir() -> None:
    cevap = isle(_cikti(oneriler=[_oneri("X", {"tur": "bilgi"})]), SonIslemBaglami(kip="soru"))
    assert cevap["oneriler"] == []


def test_oneri_eylemleri_son_islemi() -> None:
    taslak = {
        "tur": "Task",
        "ozet": "Flaky test https://evil.example/x için takip",
        "aciklama": "Bkz [buraya|https://evil.example] ve [~accountid:5b10a2844c20165700ede21g] "
        "@ahmet.yilmaz lütfen; ![x](http://evil.example/p.png)",
    }
    cevap = isle(
        _cikti(
            oneriler=[
                _oneri("Caseleri inceleyin", {"tur": "rota", "rota": UUID_RE_ROTA}),
                _oneri("Dışarı git", {"tur": "rota", "rota": "https://evil.example"}),
                _oneri("PO onayı 2 gündür bekliyor", {"tur": "bilgi"}),  # kural başlığı
                _oneri(
                    "Takip kaydı açın",
                    {"tur": "jira_taslak", "anahtar": "TPD-404", "taslak": taslak},
                ),
                _oneri("Fazla öneri", {"tur": "bilgi"}),
            ]
        ),
        _oneri_baglami(kural_basliklari=["PO onayı 2 gündür bekliyor."]),
    )
    oneriler = cevap["oneriler"]
    assert [o["baslik"] for o in oneriler] == [
        "Caseleri inceleyin",
        "Dışarı git",
        "Takip kaydı açın",
    ]
    assert oneriler[0]["eylem"] == {
        "tur": "rota",
        "rota": UUID_RE_ROTA,
        "anahtar": None,
        "taslak": None,
    }
    assert oneriler[1]["eylem"]["tur"] == "bilgi"
    jira = oneriler[2]["eylem"]
    assert jira["tur"] == "jira_taslak" and jira["anahtar"] is None
    assert jira["taslak"]["proje"] == "TPD" and jira["taslak"]["tur"] == "Task"
    assert jira["baglanti"] == "https://jira.ornek/secure/CreateIssue!default.jspa"
    metin = jira["taslak"]["ozet"] + jira["taslak"]["aciklama"]
    for yasak in ("http", "evil", "accountid", "@ahmet", "[~", "|"):
        assert yasak not in metin
    assert "[bağlantı kaldırıldı]" in jira["taslak"]["ozet"] and "buraya" in metin


@pytest.mark.parametrize(
    ("eylem", "beklenen_tur", "baglanti"),
    [
        (
            {
                "tur": "jira_yorum",
                "anahtar": "TPD-3",
                "taslak": {"tur": "yorum", "ozet": "a", "aciklama": "b"},
            },
            "jira_yorum",
            "https://jira.ornek/browse/TPD-3",
        ),
        (
            {
                "tur": "jira_yorum",
                "anahtar": "TPD-404",
                "taslak": {"tur": "yorum", "ozet": "a", "aciklama": "b"},
            },
            "bilgi",
            None,
        ),
        (
            {"tur": "jira_kaydi", "anahtar": "TPD-3"},
            "jira_kaydi",
            "https://jira.ornek/browse/TPD-3",
        ),
        ({"tur": "jira_kaydi", "anahtar": None}, "bilgi", None),
        (
            {"tur": "jira_taslak", "taslak": {"tur": "Epic", "ozet": "a", "aciklama": "b"}},
            "bilgi",
            None,
        ),
        ({"tur": "sil_her_seyi"}, "bilgi", None),
    ],
)
def test_oneri_eylemi_bilinen_anahtar_ve_tur_kurallari(
    eylem: dict[str, Any], beklenen_tur: str, baglanti: str | None
) -> None:
    out = sonislem.oneri_eylemi(eylem, _oneri_baglami())
    assert out["tur"] == beklenen_tur
    assert out.get("baglanti") == baglanti
    if beklenen_tur == "jira_yorum":
        assert out["taslak"]["tur"] == "yorum" and out["taslak"]["proje"] == "TPD"


_BUG_TASLAGI = {
    "tur": "jira_taslak",
    "taslak": {"tur": "Bug", "ozet": "Giriş hatası", "aciklama": "Adımlar"},
}
_TASK_TASLAGI = {
    "tur": "jira_taslak",
    "taslak": {"tur": "Task", "ozet": "Test verisini yenile", "aciklama": "Adımlar"},
}
_YORUM = {
    "tur": "jira_yorum",
    "anahtar": "TPD-3",
    "taslak": {"tur": "yorum", "ozet": "a", "aciklama": "b"},
}


@pytest.mark.parametrize(
    ("rota_kalibi", "varlik_turu", "sistem_hatti"),
    [
        ("/bug-taslaklari/:id", "bug_draft", True),
        ("/bug-taslaklari", None, True),
        ("/gereksinimler/:id/yayin", "requirement", True),
        ("/gereksinimler/:id", "consistency_finding", True),
        ("/gereksinimler/:id", "requirement", False),
        ("/kosular/:id", "run", False),
        ("/bug-taslaklari-eski", None, False),  # önek değil, tam bölüt
        (None, None, False),
    ],
)
def test_sistem_hattinda_jira_onerisi_bilgiye_duser(
    rota_kalibi: str | None, varlik_turu: str | None, sistem_hatti: bool
) -> None:
    """§17.2: sistem hattındaki işte modelin Jira taslağı/yorumu önerisi deterministik düşer."""
    b = _oneri_baglami(rota_kalibi=rota_kalibi, varlik_turu=varlik_turu)
    assert sonislem.sistem_hatti_mi(rota_kalibi, varlik_turu) is sistem_hatti
    for eylem, tur in ((_TASK_TASLAGI, "jira_taslak"), (_YORUM, "jira_yorum")):
        out = sonislem.oneri_eylemi(eylem, b)
        assert out["tur"] == ("bilgi" if sistem_hatti else tur)
        assert ("baglanti" in out) is not sistem_hatti
    # Kaydı açmak (yeni kayıt değil) ve rota sistem hattında da serbesttir.
    assert sonislem.oneri_eylemi({"tur": "jira_kaydi", "anahtar": "TPD-3"}, b)["tur"] == (
        "jira_kaydi"
    )
    assert sonislem.oneri_eylemi({"tur": "rota", "rota": "/kosular"}, b)["tur"] == "rota"


def test_hata_detayinda_bug_taslagi_bilgiye_duser_task_serbest() -> None:
    """Hata detayı sistem hattı değildir (§17.3) ama ürün hatasının Bug'ı bug taslağı hattındadır:
    modelin Bug taslağı `bilgi`ye düşer; Task taslağı ve yorum serbest kalır."""
    b = _oneri_baglami(rota_kalibi="/hatalar/:id", varlik_turu="failure")
    assert sonislem.sistem_hatti_mi("/hatalar/:id", "failure") is False
    assert sonislem.oneri_eylemi(_BUG_TASLAGI, b)["tur"] == "bilgi"
    task = {**_BUG_TASLAGI, "taslak": {**_BUG_TASLAGI["taslak"], "tur": "Task"}}
    assert sonislem.oneri_eylemi(task, b)["tur"] == "jira_taslak"
    assert sonislem.oneri_eylemi(_YORUM, b)["tur"] == "jira_yorum"


@pytest.mark.parametrize(
    ("rota_kalibi", "varlik_turu"),
    [
        ("/kosular/:id", "run"),
        ("/gereksinimler/:id", "requirement"),
        ("/scriptler/:id", "script"),
        ("/", None),
        (None, None),
    ],
)
def test_modelin_bug_taslagi_her_ekranda_bilgiye_duser(
    rota_kalibi: str | None, varlik_turu: str | None
) -> None:
    """Ürün hatasının Bug'ı her ekranda Probe'un bug taslağı hattındadır (koşudaki ürün hataları,
    gereksinimdeki code_defect bulguları; §17.2): ikinci bir Bug açma yolu olmaz; Task serbest."""
    b = _oneri_baglami(rota_kalibi=rota_kalibi, varlik_turu=varlik_turu)
    assert sonislem.oneri_eylemi(_BUG_TASLAGI, b)["tur"] == "bilgi"
    task = {**_BUG_TASLAGI, "taslak": {**_BUG_TASLAGI["taslak"], "tur": "Task"}}
    assert sonislem.oneri_eylemi(task, b)["tur"] == "jira_taslak"


@pytest.mark.parametrize(
    ("rol", "rota", "beklenen"),
    [
        ("tester", "/demo", "bilgi"),  # yalnız presenter
        ("presenter", "/demo", "rota"),
        ("tester", "/claude-code", "bilgi"),  # yalnız analyst
        ("analyst", "/claude-code", "rota"),
        ("tester", "/kod/0f3c-1", "rota"),  # roller null → herkes
        (None, "/demo", "rota"),  # rol bilinmiyor → süzgeç yok
    ],
)
def test_rota_eylemi_rolle_hizalanir(rol: str | None, rota: str, beklenen: str) -> None:
    out = sonislem.oneri_eylemi({"tur": "rota", "rota": rota}, _oneri_baglami(rol=rol))
    assert out["tur"] == beklenen
    assert out["rota"] == (rota if beklenen == "rota" else None)


def test_oneri_metinleri_kirpilir() -> None:
    cevap = isle(
        _cikti(oneriler=[_oneri("B" * 200, {"tur": "bilgi"}, neden="N" * 900)]),
        _oneri_baglami(),
    )
    o = cevap["oneriler"][0]
    assert len(o["baslik"]) == sonislem.ONERI_BASLIK_AZAMI
    assert len(o["neden"]) == sonislem.ONERI_NEDEN_AZAMI


# ------------------------------------------------------------------ müşteri verisi, sırlar


def test_musteri_verisinde_cevap_ayni_oturumla_yeniden_maskelenir() -> None:
    oturum = _oturum(maske=True)
    oturum.mask_text("sahibi zeynep@ornek.com")
    cikti = _cikti(
        cevap_bloklari=[{"tur": "paragraf", "metin": "zeynep@ornek.com", "maddeler": []}]
    )
    acik = isle(cikti, SonIslemBaglami(oturum=oturum))
    maskeli = isle(cikti, SonIslemBaglami(oturum=oturum, musteri_verisi=True))
    assert acik["cevap_bloklari"][0]["metin"] == "zeynep@ornek.com"
    assert maskeli["cevap_bloklari"][0]["metin"] == "<<PII_EMAIL_1>>"


def test_cevaptaki_sir_temizlenir() -> None:
    token = "gh" + "p_" + "Q1w2E3r4T5y6U7i8O9p0A1s2D3f4"
    calisma = "calisma-ani-" + "deger-123456"
    cevap = isle(
        _cikti(
            cevap_bloklari=[{"tur": "kod", "metin": f"TOKEN={token} ve {calisma}", "maddeler": []}]
        ),
        SonIslemBaglami(sir_degerleri=(calisma,)),
    )
    assert token not in str(cevap) and calisma not in str(cevap)


def test_semaya_uymayan_cikti_cokertmez() -> None:
    cevap = isle({"guven": "kesin", "kaynaklar": "x", "oneriler": None}, SonIslemBaglami())
    assert cevap["guven"] == "dusuk" and cevap["kaynaklar"] == []
    assert isle(None, SonIslemBaglami())["cevap_bloklari"] == []


# ------------------------------------------------------------------ sınıflandırma


TERIMLER = ("gereksinim", "kırarak doğrula", "kampanya", "bug taslağ", "po onay")


@pytest.mark.parametrize(
    ("soru", "baglam", "araclar", "beklenen"),
    [
        ("Bu 'Kırarak doğrula' neden gri?", None, (), True),
        ("TPD-3 neden case üretimine geçmiyor?", None, (), True),
        ("Flaky test nasıl ayıklanır?", None, (), False),
        ("Flaky test nasıl ayıklanır?", {"rota_kalibi": "/kosular/:id"}, (), True),
        ("Flaky test nasıl ayıklanır?", {"rota_kalibi": "/"}, (), False),
        ("Flaky test nasıl ayıklanır?", {"varlik": {"tur": "run", "id": REQ}}, (), True),
        ("Regresyon testi nedir?", None, ("probe_get",), True),
        ("Regresyon testi nedir?", None, ("submit_result",), False),
        ("GEREKSİNİMLER ekranı ne işe yarar?", None, (), True),
        ("tpd-3 ne durumda?", None, (), False),
    ],
)
def test_urune_ozgu_soru_siniflamasi(
    soru: str, baglam: dict[str, Any] | None, araclar: tuple[str, ...], beklenen: bool
) -> None:
    assert siniflandir.urune_ozgu(soru, baglam, terimler=TERIMLER, araclar=araclar) is beklenen


def test_urun_terimleri_dosyadan_okunur() -> None:
    assert siniflandir.urune_ozgu("Gereksinim detayında ne var?", None) is True
    assert siniflandir.urune_ozgu("Flaky test nasıl ayıklanır?", None) is False


@pytest.mark.parametrize(
    ("soru", "durum", "kuyruk", "ne_demek"),
    [
        ("TPD-3 neden case üretimine geçmiyor?", "TPD-3", False, True),
        ("TPD-3'ün durumu ne?", "TPD-3", False, False),
        ("TPD-3 ile TPD-4 farkı neden?", None, False, True),
        ("TPD-３ neden bekliyor?", None, False, True),
        # Jira yorumu/içeriği sorusu şablona gitmez (canlı `jira_issue` için modele kalır).
        ("TPD-3'te PO yorumunda neden itiraz etmiş?", None, False, True),
        ("TPD-3 Jira'da neden bekliyor?", None, False, True),
        ("TPD-3'te PO ne istemiş, durum ne?", None, False, False),
        ("Bugün ne yapmalıyım?", None, True, False),
        ("BUGÜN NE YAPMALIYIM", None, True, False),
        ("Bu hata ne demek?", None, False, True),
        ("Bu mesaj ne?", None, False, True),
        ("BU UYARI NE", None, False, True),
        ("Bu bildirim ne anlatıyor", None, False, True),
        ("Mesajı tekrar gönder", None, False, False),
        ("Bu case'i onayla", None, False, False),
    ],
)
def test_dal_siniflari(soru: str, durum: str | None, kuyruk: bool, ne_demek: bool) -> None:
    assert siniflandir.durum_sorusu(soru) == durum
    assert siniflandir.kuyruk_sorusu(soru) is kuyruk
    assert siniflandir.ne_demek_sorusu(soru) is ne_demek


# ------------------------------------------------------------------ sözlük


@pytest.mark.parametrize(
    ("son_hata", "beklenen"),
    [
        ({"kod": "onay_hash_uyusmuyor", "detail": "İçerik değişti"}, "onay-hash-uyusmuyor"),
        (
            {"kod": "kapi_kapali", "gorunen_metin": "İÇERİK SİZ GÖRÜNTÜLEDİKTEN SONRA DEĞİŞMİŞ"},
            "gorunduktan-sonra-degisti",
        ),
        ({"kod": "bilinmeyen_kod", "detail": "hiç eşleşmeyen"}, None),
        (None, None),
    ],
)
def test_sozluk_eslesme_sirasi(son_hata: dict[str, Any] | None, beklenen: str | None) -> None:
    kayit = sozluk.bul(son_hata)
    assert (kayit.id if kayit else None) == beklenen


def test_sozluk_cevabi_rota_yalniz_uygun_varlikla_dolar() -> None:
    kayit = next(k for k in sozluk.kayitlar() if k.rota == "/gereksinimler/:id")
    uygun = sozluk.cevap(kayit, {"varlik": {"tur": "requirement", "id": REQ}})
    assert uygun["yonlendirmeler"] == [{"etiket": "İlgili ekran", "rota": f"/gereksinimler/{REQ}"}]
    assert uygun["guven_gosterimi"] == sonislem.DOGRULANDI
    assert uygun["kaynaklar"][0]["ref"].startswith("rules/assistant/hata-sozlugu.yaml#")
    for baglam in (
        None,
        {"varlik": {"tur": "run", "id": REQ}},
        {"varlik": {"tur": "requirement", "id": "../denetim"}},
    ):
        assert sozluk.cevap(kayit, baglam)["yonlendirmeler"] == []


def test_veri_dogrulamasi_is_parcacigi_birakmaz_ve_es_zamanli_calisir() -> None:
    oturum = _oturum()
    havuz = KanitHavuzu()
    satirlar = [("A",)]
    sar = AracSarmalayici(
        _baglam(oturum),
        mevcut={
            "db_query": lambda _a: (
                f"query: SELECT a FROM t\nresult_digest: {masked_digest(satirlar)}\n…"
            )
        },
        mevcut_turleri={"db_query": "uygulama_verisi"},
        havuz=havuz,
    )
    sar("db_query", {})

    def dogrulama_isleri() -> set[threading.Thread]:
        # Yalnız doğrulayıcının iş parçacıkları (`thread_name_prefix="asistan-dogrula"`); başka
        # fikstürlerin/arka plan iş parçacıkları sayıyı oynatmaz.
        return {
            t
            for t in threading.enumerate()
            if t.name.startswith("asistan-dogrula") and t.is_alive()
        }

    once = dogrulama_isleri()
    for _ in range(3):
        isle(
            _cikti(kaynaklar=[_kaynak("uygulama_verisi", "k1", "")]),
            SonIslemBaglami(havuz=havuz, dogrulayici=SahteDogrulayici(satirlar=satirlar)),
        )
    son = time.monotonic() + 5.0
    while dogrulama_isleri() - once and time.monotonic() < son:
        time.sleep(0.02)
    assert dogrulama_isleri() - once == set()


def test_varsayilan_arac_seti_ve_dogrulayici_ayni_sha_ve_tek_kurulum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7.3 "aynı sha'da": araç ve doğrulama aynı `CodeTools`'u paylaşır, bir kez kurulur."""
    from tp_core.features.assistant import flow, tools

    kurulum: list[str] = []

    class Forge:
        def read_file(self, yol: str, ref: str) -> str:
            return f"{yol}@{ref}\nreturn indirim"

    class Kod:
        sha = "abc123"
        forge = Forge()

        def search_code(self, _a: dict[str, Any]) -> str:
            return "<untrusted>src/k.py:2: return indirim</untrusted>"

        def get_file_contents(self, _a: dict[str, Any]) -> str:
            return ""

    def kur() -> Kod:
        kurulum.append("kod")
        return Kod()

    monkeypatch.setattr(tools, "kod_araclari", kur)
    araclar, dogrulayici = flow.varsayilan_araclar(_baglam(_oturum()))
    assert kurulum == []  # tembel: ağ çağrısı yalnız gerekirse
    araclar.execute("search_code", {"query": "indirim"})
    assert dogrulayici.uygulama_satirlari("src/k.py") == ["src/k.py@abc123", "return indirim"]
    assert kurulum == ["kod"]
