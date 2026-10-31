"""Deterministik demo verisi: bayiler, ürünler, kampanya ve ayarlar. Tekrar çalıştırılabilir."""

from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from demoapp_api.campaign import KAMPANYA_ADI
from demoapp_api.models import (
    Ayar,
    Bayi,
    Kampanya,
    Oturum,
    Sepet,
    SepetSatiri,
    Siparis,
    SiparisSatiri,
    TestKirilma,
    Urun,
)
from demoapp_api.security import parola_hash

DEMO_PAROLA = "Demo123!"

# bayi1, bayi2: e2e işçileri (paralel işçi başına bir bayi).
# bayi3: kod üretimindeki doğrulama ajanının (playwright-mcp) bayisi; e2e koşuları kullanmaz,
# böylece ajanın sepeti ile eşzamanlı test koşuları birbirini bozmaz.
BAYILER = [
    {"kullanici_adi": "bayi1", "ad": "Merkez Bayi", "kredi_limiti": Decimal("2000.00")},
    {"kullanici_adi": "bayi2", "ad": "Sahil Bayi", "kredi_limiti": Decimal("500.00")},
    {"kullanici_adi": "bayi3", "ad": "Doğrulama Bayi", "kredi_limiti": Decimal("2000.00")},
]

URUNLER = [
    {"kod": "P-001", "ad": "Portakal Gazozu 1L", "fiyat": Decimal("25.00")},
    {"kod": "P-002", "ad": "Limonata 330ml", "fiyat": Decimal("15.00")},
    {"kod": "P-003", "ad": "Maden Suyu 200ml", "fiyat": Decimal("8.00")},
    {"kod": "P-004", "ad": "Şeftalili Soğuk Çay 1L", "fiyat": Decimal("30.00")},
]

KAMPANYALAR = [{"kod": "6AL1BEDAVA", "ad": KAMPANYA_ADI, "urun_kod": "P-001"}]

# Uygulama minimum sipariş tutarını `ayar` tablosundan okur.
AYARLAR = [
    {
        "anahtar": "min_siparis_tutari",
        "deger": "750.00",
        "aciklama": "Minimum sipariş tutarı (TL, indirim sonrası toplam)",
    },
]


def seed(s: Session) -> None:
    for b in BAYILER:
        row = s.scalar(select(Bayi).where(Bayi.kullanici_adi == b["kullanici_adi"]))
        if row is None:
            row = Bayi(kullanici_adi=b["kullanici_adi"])
            s.add(row)
        row.ad = b["ad"]
        row.kredi_limiti = b["kredi_limiti"]
        beklenen = parola_hash(DEMO_PAROLA, b["kullanici_adi"])
        if row.parola_hash != beklenen:
            row.parola_hash = beklenen
    s.flush()

    urunler: dict[str, Urun] = {}
    for i, u in enumerate(URUNLER, start=1):
        row = s.scalar(select(Urun).where(Urun.kod == u["kod"]))
        if row is None:
            row = Urun(kod=u["kod"])
            s.add(row)
        row.ad = u["ad"]
        row.fiyat = u["fiyat"]
        row.sira = i
        row.aktif = True
        urunler[u["kod"]] = row
    s.flush()

    for k in KAMPANYALAR:
        row = s.scalar(select(Kampanya).where(Kampanya.kod == k["kod"]))
        if row is None:
            row = Kampanya(kod=k["kod"])
            s.add(row)
        row.ad = k["ad"]
        row.urun_id = urunler[k["urun_kod"]].id
        row.aktif = True

    for a in AYARLAR:
        row = s.get(Ayar, a["anahtar"])
        if row is None:
            row = Ayar(anahtar=a["anahtar"])
            s.add(row)
        row.deger = a["deger"]
        row.aciklama = a["aciklama"]
    s.flush()


def _bayi_verisini_sil(s: Session, bayi_ids: list[int] | None) -> None:
    def where(model):
        return model.bayi_id.in_(bayi_ids) if bayi_ids is not None else True

    siparis_ids = select(Siparis.id).where(where(Siparis))
    sepet_ids = select(Sepet.id).where(where(Sepet))
    s.execute(delete(SiparisSatiri).where(SiparisSatiri.siparis_id.in_(siparis_ids)))
    s.execute(delete(Siparis).where(where(Siparis)))
    s.execute(delete(SepetSatiri).where(SepetSatiri.sepet_id.in_(sepet_ids)))
    s.execute(delete(Sepet).where(where(Sepet)))
    # Yarıda kalan bir "kırarak doğrula" koşusu bayiyi bozuk bırakmasın.
    s.execute(delete(TestKirilma).where(where(TestKirilma)))


def reset_all(s: Session) -> None:
    """Tüm sepet, sipariş ve oturumları siler; tohum verisini yeniden yazar."""
    _bayi_verisini_sil(s, None)
    s.execute(delete(Oturum))
    s.execute(delete(Kampanya).where(Kampanya.kod.not_in([k["kod"] for k in KAMPANYALAR])))
    s.execute(delete(Ayar).where(Ayar.anahtar.not_in([a["anahtar"] for a in AYARLAR])))
    s.flush()
    seed(s)


def reset_bayi(s: Session, kullanici_adi: str) -> bool:
    """Yalnızca bir bayinin sepetini, siparişlerini ve demo kırılmasını siler (paralel test
    işçileri için). Oturumlar korunur. Bayi yoksa False."""
    bayi = s.scalar(select(Bayi).where(Bayi.kullanici_adi == kullanici_adi))
    if bayi is None:
        return False
    _bayi_verisini_sil(s, [bayi.id])
    seed(s)
    return True
