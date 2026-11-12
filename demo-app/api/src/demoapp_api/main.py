"""Bayi Sipariş Portalı API.

Uçlar: /health · /auth/{login,logout,me} · /products · /cart (+ /cart/lines) · /orders ·
/test/reset · /test/break · /test/faults (yalnızca DEMOAPP_TEST_MODE=1 ve DEMOAPP_TEST_TOKEN
tanımlıyken; istek `X-Demoapp-Test-Token` başlığında aynı değeri taşımalıdır). Web arayüzü `/api/`
önekiyle erişir (nginx ya da vite proxy öneki kaldırır; nginx /api/test/ yolunu dışarı açmaz).
"""

import hmac
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import Body, Cookie, Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from demoapp_api import __version__, db, faults, seed
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
from demoapp_api.money import tutar, tutar_str
from demoapp_api.pricing import SatirGirdi, SepetSonuc, sepet_hesapla
from demoapp_api.security import parola_dogru, parola_hash, token_hash, yeni_token

SERVICE_NAME = "demo-app-api"
COOKIE = "bayi_oturum"
OTURUM_SURESI = timedelta(hours=12)
MAX_ADET = 999
HATALI_GIRIS = "Kullanıcı adı veya parola hatalı"
VARSAYILAN_MIN_SIPARIS = Decimal("0.00")

log = logging.getLogger("demoapp_api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        db.ensure_initialized()
    except Exception as exc:
        log.warning("Şema kurulamadı, ilk istekte yeniden denenecek: %s", exc)
    yield


app = FastAPI(title="Bayi Sipariş Portalı API", version=__version__, lifespan=lifespan)

SessionDep = Annotated[Session, Depends(db.get_session, scope="function")]  # commit yanıttan önce


# --------------------------------------------------------------------------- yardımcılar
TEST_TOKEN_HEADER = "X-Demoapp-Test-Token"


def test_modu() -> bool:
    return os.environ.get("DEMOAPP_TEST_MODE") == "1"


def test_tokeni() -> str | None:
    """Test uçlarının paylaşılan sırrı; tanımsızsa test uçları kapalıdır."""
    return os.environ.get("DEMOAPP_TEST_TOKEN") or None


def test_ucu_yetkisi(x_demoapp_test_token: Annotated[str | None, Header()] = None) -> None:
    """/test/* uçları: test modu + paylaşılan token. Özel başlık tarayıcıda CORS ön isteği
    gerektirir; API CORS izni vermediği için başka bir sayfadan tetiklenemez."""
    beklenen = test_tokeni()
    if not test_modu() or beklenen is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    if not x_demoapp_test_token or not hmac.compare_digest(
        x_demoapp_test_token.encode(), beklenen.encode()
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Test token'ı geçersiz")


def min_siparis_tutari(s: Session) -> Decimal:
    row = s.get(Ayar, "min_siparis_tutari")
    if row is None:
        return VARSAYILAN_MIN_SIPARIS
    try:
        return tutar(row.deger)
    except ArithmeticError:
        log.error("ayar.min_siparis_tutari geçersiz: %r", row.deger)
        return VARSAYILAN_MIN_SIPARIS


def kampanyali_urun_idleri(s: Session) -> set[int]:
    return set(s.scalars(select(Kampanya.urun_id).where(Kampanya.aktif.is_(True))))


def _oturumdaki_bayi(s: Session, bayi_oturum: str | None) -> tuple[Bayi | None, str]:
    """Çerezdeki oturumun bayisini döndürür; yoksa (None, 401 gerekçesi)."""
    if not bayi_oturum:
        return None, "Oturum açmanız gerekiyor"
    oturum = s.get(Oturum, token_hash(bayi_oturum))
    if oturum is None or _utc(oturum.son_kullanma) < datetime.now(UTC):
        return None, "Oturumunuzun süresi doldu"
    bayi = s.get(Bayi, oturum.bayi_id)
    if bayi is None:
        return None, "Oturum açmanız gerekiyor"
    return bayi, ""


def mevcut_bayi(s: SessionDep, bayi_oturum: Annotated[str | None, Cookie()] = None) -> Bayi:
    bayi, gerekce = _oturumdaki_bayi(s, bayi_oturum)
    if bayi is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, gerekce)
    return bayi


BayiDep = Annotated[Bayi, Depends(mevcut_bayi)]


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def sepeti_kilitle(s: Session, bayi: Bayi) -> None:
    """Bu bayinin sepetini değiştiren istekleri sıraya sokar (Postgres: `SELECT … FOR UPDATE`).

    Kilit bayi satırına alınır: bayi her zaman vardır, sepet ise henüz oluşmamış olabilir; böylece
    sepet oluşturma, satır ekleme/güncelleme ve sipariş aynı kilidi paylaşır. Kilit işlem sonuna
    (commit/rollback) kadar sürer ve sepet okunmadan önce alınmalıdır; READ COMMITTED altında
    sonraki sorgular önceki işlemin yazdıklarını görür. SQLite'ta FOR UPDATE yoktur, orada
    BEGIN IMMEDIATE yazma işlemlerini zaten sıralar. Tüm sepet uçları önce bu kilidi aldığı için
    kilit sırası tek ve kilitlenme (deadlock) olmaz.
    """
    s.execute(select(Bayi.id).where(Bayi.id == bayi.id).with_for_update())


def sepet_al(s: Session, bayi: Bayi, olustur: bool = True) -> Sepet | None:
    sepet = s.scalar(select(Sepet).where(Sepet.bayi_id == bayi.id))
    if sepet is None and olustur:
        sepet = Sepet(bayi_id=bayi.id)
        s.add(sepet)
        s.flush()
    return sepet


def aktif_hata(s: Session, bayi: Bayi) -> str | None:
    """Bu bayi için ekilmiş hata kodu (`POST /test/break`, `faults.py`); yoksa None.
    Test modu dışında hep None: kırılma kaydı kalmış olsa bile hesap etkilenmez."""
    return faults.satir_hatasi(s.get(TestKirilma, bayi.id)) if test_modu() else None


def sepet_hesabi(s: Session, bayi: Bayi, sepet: Sepet | None) -> SepetSonuc:
    """Sepet tutarları, bayinin gördüğü değerlerle (ekilmiş veri hatası fiyatı/minimumu ezer)."""
    hata, kampanyali = bayi_gorunumu(s, bayi)
    satirlar = sorted(sepet.satirlar, key=lambda x: x.urun.sira) if sepet else []
    girdiler = [
        SatirGirdi(
            urun_kod=x.urun.kod,
            urun_ad=x.urun.ad,
            birim_fiyat=faults.fiyat(hata, x.urun.kod, x.urun.fiyat),
            adet=x.adet,
            kampanyali=x.urun_id in kampanyali,
        )
        for x in satirlar
    ]
    return sepet_hesapla(girdiler, faults.min_siparis(hata, min_siparis_tutari(s)), hata)


def sepet_json(h: SepetSonuc) -> dict:
    return {
        "satirlar": [
            {
                "urun_kod": x.urun_kod,
                "urun_ad": x.urun_ad,
                "birim_fiyat": tutar_str(x.birim_fiyat),
                "adet": x.adet,
                "kampanya": KAMPANYA_ADI if x.kampanyali else None,
                "bedava_adet": x.bedava_adet,
                "ucretli_adet": x.ucretli_adet,
                "ara_tutar": tutar_str(x.ara_tutar),
                "indirim": tutar_str(x.indirim),
                "satir_tutari": tutar_str(x.satir_tutari),
            }
            for x in h.satirlar
        ],
        "adet_toplam": h.adet_toplam,
        "ara_toplam": tutar_str(h.ara_toplam),
        "indirim": tutar_str(h.indirim),
        "toplam": tutar_str(h.toplam),
        "min_siparis_tutari": tutar_str(h.min_siparis_tutari),
        "min_siparis_saglandi": h.min_siparis_saglandi,
        "onaylanabilir": h.onaylanabilir,
        "uyarilar": [{"kod": u.kod, "mesaj": u.mesaj} for u in h.uyarilar],
    }


def urun_bul(s: Session, kod: str) -> Urun:
    urun = s.scalar(select(Urun).where(Urun.kod == kod, Urun.aktif.is_(True)))
    if urun is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ürün bulunamadı")
    return urun


def siparis_json(o: Siparis, detay: bool = False) -> dict:
    body = {
        "numara": o.numara,
        "olusturma": _utc(o.olusturma).isoformat(),
        "adet_toplam": o.adet_toplam,
        "ara_toplam": tutar_str(o.ara_toplam),
        "indirim": tutar_str(o.indirim),
        "toplam": tutar_str(o.toplam),
    }
    if detay:
        body["satirlar"] = [
            {
                "urun_kod": x.urun_kod,
                "urun_ad": x.urun_ad,
                "birim_fiyat": tutar_str(x.birim_fiyat),
                "adet": x.adet,
                "bedava_adet": x.bedava_adet,
                "satir_tutari": tutar_str(x.satir_tutari),
            }
            for x in o.satirlar
        ]
    return body


# --------------------------------------------------------------------------- modeller
class GirisIstegi(BaseModel):
    kullanici_adi: str = Field(min_length=1, max_length=64)
    parola: str = Field(min_length=1, max_length=256)


class SatirEkle(BaseModel):
    urun_kod: str = Field(min_length=1, max_length=16)
    adet: int = Field(ge=1, le=MAX_ADET)


class SatirGuncelle(BaseModel):
    adet: int = Field(ge=0, le=MAX_ADET)


class SifirlaIstegi(BaseModel):
    kullanici_adi: str | None = Field(default=None, max_length=64)


class KirIstegi(BaseModel):  # `kampanya: true` = `hata: "kampanya_bedava_yok"` (geriye uyumlu)
    kullanici_adi: str = Field(min_length=1, max_length=64)
    kampanya: bool | None = None
    hata: str | None = Field(default=None, max_length=faults.KOD_UZUNLUGU)


# --------------------------------------------------------------------------- uçlar
@app.get("/health")
def health() -> JSONResponse:
    checks = {"db": db.check_db()}
    healthy = all(v == "ok" for v in checks.values())
    body = {
        "service": SERVICE_NAME,
        "status": "ok" if healthy else "degraded",
        "version": __version__,
        "checks": checks,
    }
    return JSONResponse(body, status_code=200 if healthy else 503)


@app.post("/auth/login")
def login(istek: GirisIstegi, response: Response, s: SessionDep) -> dict:
    bayi = s.scalar(select(Bayi).where(Bayi.kullanici_adi == istek.kullanici_adi))
    if bayi is None:
        # Zamanlama farkıyla kullanıcı varlığını sızdırmamak için yine özet hesaplanır.
        parola_hash(istek.parola, "__yok__")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, HATALI_GIRIS)
    if not parola_dogru(istek.parola, bayi.parola_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, HATALI_GIRIS)
    token = yeni_token()
    s.add(
        Oturum(
            token_hash=token_hash(token),
            bayi_id=bayi.id,
            son_kullanma=datetime.now(UTC) + OTURUM_SURESI,
        )
    )
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(OTURUM_SURESI.total_seconds()),
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"kullanici_adi": bayi.kullanici_adi, "ad": bayi.ad}


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(s: SessionDep, bayi_oturum: Annotated[str | None, Cookie()] = None) -> Response:
    if bayi_oturum:
        s.execute(delete(Oturum).where(Oturum.token_hash == token_hash(bayi_oturum)))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(COOKIE, path="/")
    return response


@app.get("/auth/me")
def me(bayi: BayiDep) -> dict:
    return {"kullanici_adi": bayi.kullanici_adi, "ad": bayi.ad}


@app.get("/auth/session")
def session_probe(s: SessionDep, bayi_oturum: Annotated[str | None, Cookie()] = None) -> dict:
    """Sayfa açılışındaki oturum yoklaması: oturum yoksa da 200 döner.

    Oturumsuz durum bir hata değil, beklenen başlangıç hâlidir; 401 dönseydi tarayıcı her sayfa
    yüklemesinde konsola "Failed to load resource" yazardı (ajan çıktısında "Console: 1 errors").
    """
    bayi, _ = _oturumdaki_bayi(s, bayi_oturum)
    if bayi is None:
        return {"oturum": None}
    return {"oturum": {"kullanici_adi": bayi.kullanici_adi, "ad": bayi.ad}}


@app.get("/products")
def products(s: SessionDep, _bayi: BayiDep) -> list[dict]:
    hata, kampanyali = bayi_gorunumu(s, _bayi)
    urunler = s.scalars(select(Urun).where(Urun.aktif.is_(True)).order_by(Urun.sira, Urun.kod))
    return [
        {
            "kod": u.kod,
            "ad": u.ad,
            "fiyat": tutar_str(faults.fiyat(hata, u.kod, u.fiyat)),
            "kampanya": KAMPANYA_ADI if u.id in kampanyali else None,
        }
        for u in urunler
    ]


@app.get("/cart")
def get_cart(s: SessionDep, bayi: BayiDep) -> dict:
    return sepet_json(sepet_hesabi(s, bayi, sepet_al(s, bayi, olustur=False)))


@app.post("/cart/lines")
def add_line(istek: SatirEkle, s: SessionDep, bayi: BayiDep) -> dict:
    urun = urun_bul(s, istek.urun_kod)
    sepeti_kilitle(s, bayi)
    sepet = sepet_al(s, bayi)
    assert sepet is not None
    satir = next((x for x in sepet.satirlar if x.urun_id == urun.id), None)
    if satir is None:
        sepet.satirlar.append(SepetSatiri(urun=urun, adet=istek.adet))
    else:
        if satir.adet + istek.adet > MAX_ADET:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"Bir üründen en fazla {MAX_ADET} adet"
            )
        satir.adet += istek.adet
    sepet.guncelleme = datetime.now(UTC)
    s.flush()
    return sepet_json(sepet_hesabi(s, bayi, sepet))


@app.put("/cart/lines/{urun_kod}")
def set_line(urun_kod: str, istek: SatirGuncelle, s: SessionDep, bayi: BayiDep) -> dict:
    urun = urun_bul(s, urun_kod)
    sepeti_kilitle(s, bayi)
    sepet = sepet_al(s, bayi)
    assert sepet is not None
    satir = next((x for x in sepet.satirlar if x.urun_id == urun.id), None)
    if istek.adet == 0:
        if satir is not None:
            sepet.satirlar.remove(satir)
    elif satir is None:
        sepet.satirlar.append(SepetSatiri(urun=urun, adet=istek.adet))
    else:
        satir.adet = istek.adet
    s.flush()
    return sepet_json(sepet_hesabi(s, bayi, sepet))


@app.delete("/cart/lines/{urun_kod}")
def delete_line(urun_kod: str, s: SessionDep, bayi: BayiDep) -> dict:
    sepeti_kilitle(s, bayi)
    sepet = sepet_al(s, bayi, olustur=False)
    satir = next((x for x in sepet.satirlar if x.urun.kod == urun_kod), None) if sepet else None
    if sepet is None or satir is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sepette bu ürün yok")
    sepet.satirlar.remove(satir)
    s.flush()
    return sepet_json(sepet_hesabi(s, bayi, sepet))


@app.delete("/cart")
def clear_cart(s: SessionDep, bayi: BayiDep) -> dict:
    sepeti_kilitle(s, bayi)
    sepet = sepet_al(s, bayi, olustur=False)
    if sepet is not None:
        sepet.satirlar.clear()
        s.flush()
    return sepet_json(sepet_hesabi(s, bayi, sepet))


@app.post("/orders", status_code=status.HTTP_201_CREATED)
def create_order(s: SessionDep, bayi: BayiDep) -> dict:
    sepeti_kilitle(s, bayi)
    sepet = sepet_al(s, bayi, olustur=False)
    h = sepet_hesabi(s, bayi, sepet)
    if sepet is None or not h.satirlar:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Sepetiniz boş")
    if not h.onaylanabilir:
        mesaj = h.uyarilar[0].mesaj if h.uyarilar else "Sipariş onaylanamaz"
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, mesaj)
    urun_id = {x.urun.kod: x.urun_id for x in sepet.satirlar}
    siparis = Siparis(
        numara="",
        bayi_id=bayi.id,
        adet_toplam=h.adet_toplam,
        ara_toplam=h.ara_toplam,
        indirim=h.indirim,
        toplam=h.toplam,
        satirlar=[
            SiparisSatiri(
                urun_id=urun_id[x.urun_kod],
                urun_kod=x.urun_kod,
                urun_ad=x.urun_ad,
                birim_fiyat=x.birim_fiyat,
                adet=x.adet,
                bedava_adet=x.bedava_adet,
                satir_tutari=x.satir_tutari,
            )
            for x in h.satirlar
        ],
    )
    s.add(siparis)
    s.flush()
    siparis.numara = f"SP-{siparis.id:06d}"
    sepet.satirlar.clear()
    s.flush()
    return siparis_json(siparis, detay=True)


@app.get("/orders")
def list_orders(s: SessionDep, bayi: BayiDep) -> list[dict]:
    rows = s.scalars(select(Siparis).where(Siparis.bayi_id == bayi.id).order_by(Siparis.id.desc()))
    return [siparis_json(o) for o in rows]


@app.get("/orders/{numara}")
def get_order(numara: str, s: SessionDep, bayi: BayiDep) -> dict:
    o = s.scalar(select(Siparis).where(Siparis.numara == numara, Siparis.bayi_id == bayi.id))
    if o is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sipariş bulunamadı")
    return siparis_json(o, detay=True)


@app.post("/test/reset", dependencies=[Depends(test_ucu_yetkisi)])
def test_reset(s: SessionDep, istek: Annotated[SifirlaIstegi | None, Body()] = None) -> dict:
    """Test verisini sıfırlar. `kullanici_adi` verilirse yalnızca o bayinin sepeti/siparişleri."""
    if istek is not None and istek.kullanici_adi:
        if not seed.reset_bayi(s, istek.kullanici_adi):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bayi bulunamadı")
        return {"status": "ok", "kapsam": istek.kullanici_adi}
    seed.reset_all(s)
    return {"status": "ok", "kapsam": "tumu"}


@app.post("/test/break", dependencies=[Depends(test_ucu_yetkisi)])
def test_break(istek: KirIstegi, s: SessionDep) -> dict:
    """Bayi kapsamlı ekilmiş hata ("kırarak doğrula", "ekilmiş hata koşusu").

    `hata`: `faults.KATALOG` kodu; bu bayinin sepet, katalog ve sipariş hesabı o hatayla çalışır,
    diğer bayiler etkilenmez. Bir bayide en çok bir hata etkindir (yenisi öncekinin yerini alır).
    `kampanya: true` geriye uyumludur ve `hata: "kampanya_bedava_yok"` ile eşanlamlıdır; ikisi
    birlikte verilirse `hata` geçerlidir. `hata: null` / `kampanya: false` hatayı kaldırır.
    `/test/reset` (bayi ya da tümü) hatayı da kaldırır."""
    if not istek.model_fields_set & {"kampanya", "hata"}:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "kampanya ya da hata alanı verilmelidir"
        )
    kod = istek.hata or (faults.KAMPANYA_BEDAVA_YOK if istek.kampanya else None)
    if kod is not None and not faults.gecerli(kod):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, faults.bilinmeyen_kod_mesaji(kod)
        )
    bayi = s.scalar(select(Bayi).where(Bayi.kullanici_adi == istek.kullanici_adi))
    if bayi is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bayi bulunamadı")
    row = s.get(TestKirilma, bayi.id)
    if kod is not None:
        if row is None:
            row = TestKirilma(bayi_id=bayi.id)
            s.add(row)
        row.hata = kod
        row.kampanya = kod == faults.KAMPANYA_BEDAVA_YOK
        row.guncelleme = datetime.now(UTC)
    elif row is not None:
        s.delete(row)
    s.flush()
    return {
        "kullanici_adi": bayi.kullanici_adi,
        "kampanya": kod == faults.KAMPANYA_BEDAVA_YOK,
        "hata": kod,
    }


@app.get("/test/faults", dependencies=[Depends(test_ucu_yetkisi)])
def test_faults() -> dict:
    """Ekilmiş hata kataloğu: `{"hatalar": [{kod, tur, ad, aciklama}]}` (`faults.KATALOG`)."""
    return {"hatalar": faults.katalog_json()}


# --------------------------------------------------------------------------- ekilmiş hata
# Sabitlenen satırları (core testleri: main.py:331, main.py:450) kaydırmamak için dosya sonunda.
def bayi_gorunumu(s: Session, bayi: Bayi) -> tuple[str | None, set[int]]:
    """Bu bayinin (etkin hata kodu, kampanyalı ürün id'leri) ikilisi.

    Kampanyalı ürün ekilmiş veri hatasıyla ezilmişse `kampanya` tablosu yerine o ürün döner;
    tabloya yazılmaz, bu yüzden diğer bayiler ve `/test/reset` etkilenmez."""
    hata = aktif_hata(s, bayi)
    urun_kod = faults.kampanya_urunu(hata)
    if urun_kod is None:
        return hata, kampanyali_urun_idleri(s)
    return hata, set(s.scalars(select(Urun.id).where(Urun.kod == urun_kod, Urun.aktif.is_(True))))
