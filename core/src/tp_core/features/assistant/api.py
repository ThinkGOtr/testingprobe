"""Portal asistanı uçları (AI-ASISTAN-PLANI §9; specs/008-ai-asistan/contracts/api.md).

| Yöntem | Yol | Açıklama |
|---|---|---|
| GET | `/assistant/status` | `asistan_durum`'dan; kalp atışı > 2 dk → `worker_yok` |
| GET · POST | `/assistant/conversations` | kendi sohbetleri (son 50) · yeni sohbet (201) |
| DELETE | `/assistant/conversations/{id}` | yumuşak silme (204) |
| GET · POST | `/assistant/conversations/{id}/messages` | mesajlar · soru / "Daha ayrıntılı" (202) |
| GET | `/assistant/messages/{id}` | tek mesaj (yoklama) |
| POST | `/assistant/messages/{id}/cancel` · `/feedback` | iptal · 👍/👎 |

Öneri uçları (`/assistant/suggestions…`) Şerit R'nin `oneri_api.router`'ındadır; burada
dahil edilir.

- Tüm uçlar `CurrentUser` (yalnız çerez; bearer → 401). Rol kısıtı yok: herkes yalnız kendi
  kaynağını görür; başkasının ya da silinmiş sohbetin kaynağına her uç 404 (`ust_mesaj_id` dahil).
- core-api model anahtarını ve kipini **bilmez** (İlke II): durum worker'ın yazdığı `asistan_durum`
  satırından okunur. Model gerekip gerekmediğine (sözlük/şablon) worker karar verir.
- POST mesaj transaction sırası: dondurma (429 `donduruldu` + `kalan_s`; specs/013 §6.2) →
  doğrulama (422, sır → `sir_icerik` + güvenlik olayı, kart → `kisisel_veri`) → sahiplik (404) → hizmet
  durumu (503) → öneri geçerliliği (409 `oneri_gecersiz`) → saatlik hak (429 `hiz_siniri`) → bütçe
  (402) → `budget.global_kilit` → kullanıcı işi (409 `bekleyen_var`) ve global sayaç (429 `mesgul`)
  → mesaj INSERT (kısıt ihlali kısıt adına göre 409) → `assistant.answer` işi (aynı transaction).
  Kilit, otomatik yükseltme transaction'ıyla aynı anahtardır ve ilk yazımdan önce alınır.
- İş yükü daima `{mesaj_id, kullanici_id, tetik}`; idempotency anahtarı `assistant.answer:<id>`.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tp_core.api.errors import IC_HATA, SUNUCU_HATASI_METNI, KodluHata
from tp_core.auth.deps import CurrentUser, DbSession
from tp_core.events import publish_tx
from tp_core.features.assistant import budget, hiz, olay
from tp_core.features.assistant import oneri_api as _oneri_api
from tp_core.features.assistant.schemas import (
    ONERI_SORUSU,
    MesajGeriBildirim,
    SohbetOlustur,
    SoruGonder,
)
from tp_core.models.asistan import (
    MESAJ_BEKLEYEN_UQ,
    MESAJ_SIRA_UQ,
    MESAJ_UST_UQ,
    AsistanDurum,
    AsistanMesaj,
    AsistanSohbet,
)
from tp_core.workflow import jobs
from tp_core.workflow.service import Principal

log = logging.getLogger(__name__)
router = APIRouter(tags=["assistant"])

SOHBET_LISTE_AZAMI = 50
KALP_ATISI_AZAMI_S = 120
IS_ZAMAN_ASIMI_S = budget.IS_ZAMAN_ASIMI_S  # tek kaynak budget.py
EV_ANSWERED = "assistant.answered"

router.include_router(_oneri_api.router)  # öneri uçları (`/assistant/suggestions…`)


# ------------------------------------------------------------------ yardımcılar


def _bulunamadi(ne: str = "Sohbet") -> HTTPException:
    return HTTPException(404, f"{ne} bulunamadı")


def _iso(deger: datetime | None) -> str | None:
    return deger.isoformat() if deger is not None else None


def _sayi(deger: Decimal | None) -> float | None:
    return float(deger) if deger is not None else None


def sohbet_ozeti(s: AsistanSohbet) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "baslik": s.baslik,
        "oneri_kural_id": s.oneri_kural_id,
        "olusturma": _iso(s.olusturma),
        "guncelleme": _iso(s.guncelleme),
    }


def mesaj_ozeti(m: AsistanMesaj) -> dict[str, Any]:
    """Portalın `AsistanMesaji` biçimi. İç alanlar (`job_id`, `ai_call_id`, token) yazılmaz."""
    return {
        "id": str(m.id),
        "sohbet_id": str(m.sohbet_id),
        "sira": m.sira,
        "rol": m.rol,
        "ust_mesaj_id": str(m.ust_mesaj_id) if m.ust_mesaj_id else None,
        "icerik": m.icerik,
        "cevap": m.cevap,
        "durum": m.durum,
        "hata_kodu": m.hata_kodu,
        "kaynak": m.kaynak,
        "amac": m.amac,
        "kip": m.kip,
        "tetik": m.tetik,
        "maliyet_usd": _sayi(m.maliyet_usd),
        "sure_ms": m.sure_ms,
        "geri_bildirim": m.geri_bildirim,
        "olusturma": _iso(m.olusturma),
        "tamamlanma": _iso(m.tamamlanma),
    }


def _sohbet(
    session: Session, sohbet_id: uuid.UUID, user: Principal, *, kilitle: bool = False
) -> AsistanSohbet:
    # `kilitle`: sil ile gönder sohbet satırında sıralanır (READ COMMITTED'da en son sürümü
    # okur): silme commit edildikten sonra gelen gönderim 404 alır, silmeden önce kilidi alan
    # gönderimin cevabı silmenin açık mesaj taramasında görülüp iptal edilir. Kip FOR NO KEY
    # UPDATE: `asistan_mesaj.sohbet_id` FK'sinin INSERT'te aldığı KEY SHARE ile çakışmaz. FOR
    # UPDATE, worker'ın otomatik çocuk INSERT'iyle (global kilit → mesaj → sohbet KEY SHARE)
    # ters sırada bekleyip kilitlenmeye (deadlock) yol açardı.
    s = session.get(
        AsistanSohbet, sohbet_id, with_for_update={"key_share": True} if kilitle else None
    )
    if s is None or s.kullanici_id != user.id or s.silindi:
        raise _bulunamadi()
    return s


def _mesaj(
    session: Session, mesaj_id: uuid.UUID, user: Principal, *, kilitle: bool = False
) -> AsistanMesaj:
    m = session.get(AsistanMesaj, mesaj_id, with_for_update=kilitle or None)
    if m is None or m.kullanici_id != user.id:
        raise _bulunamadi("Mesaj")
    s = session.get(AsistanSohbet, m.sohbet_id)
    if s is None or s.silindi or s.kullanici_id != user.id:
        raise _bulunamadi("Mesaj")
    return m


# ------------------------------------------------------------------ hizmet durumu


def _kalp_atisi_taze(durum: AsistanDurum | None, simdi: datetime) -> bool:
    if durum is None or durum.kalp_atisi is None:
        return False
    return (simdi - durum.kalp_atisi).total_seconds() <= KALP_ATISI_AZAMI_S


def hizmet_nedeni(durum: AsistanDurum | None, simdi: datetime) -> str | None:
    """Asistan kapalıysa nedeni (`worker_yok` | `maskeleme_kapali`), açıksa None."""
    if not _kalp_atisi_taze(durum, simdi):
        return "worker_yok"
    assert durum is not None
    if durum.musteri_verisi and not durum.maskeleme:
        return "maskeleme_kapali"
    return None


KAPALI_METINLERI = {
    "worker_yok": "Asistan şu an kapalı: arka plan işleyicisi çalışmıyor.",
    "maskeleme_kapali": (
        "Asistan kapalı: müşteri verisi kurulumunda kişisel veri maskelemesi kapalı."
    ),
}


def _db_simdi(session: Session) -> datetime:
    return session.execute(text("SELECT now()")).scalar_one()


def _varsayilan_model(amac: str = "assistant") -> str | None:
    try:
        from tp_core.gateway.config import find_rules_dir, load_model_table

        return load_model_table(find_rules_dir()).purpose(amac).model
    except Exception:  # kural dosyası yoksa durum ucu yine yanıt verir
        return None


def _degerlendirme() -> dict[str, Any] | None:
    try:
        from tp_core.gateway.config import find_rules_dir
        from tp_core.gateway.evaluation import evaluation_summary

        ozet = evaluation_summary(find_rules_dir(), "assistant")
    except Exception:
        return None
    ozet.pop("hata", None)  # iç ayrıntı (dosya yolu) dışarı gitmez
    return ozet


@router.get("/assistant/status")
def durum(session: DbSession, user: CurrentUser) -> dict[str, Any]:
    satir = session.get(AsistanDurum, 1)
    simdi = _db_simdi(session)
    neden = hizmet_nedeni(satir, simdi)
    return {
        "etkin": neden is None,
        "neden": neden,
        "mod": satir.mod if satir is not None else "off",
        "model_hazir": bool(satir is not None and satir.model_hazir and neden is None),
        "varsayilan_model": _varsayilan_model(),
        # 013 §7: derin cevabın kip rozeti ("CANLI · Sonnet 5.5") bu modeli gösterir.
        "derin_model": _varsayilan_model("assistant_deep"),
        "degerlendirme": _degerlendirme(),
        "paket_commit": satir.paket_commit if satir is not None else None,
        "kalan_soru": budget.kalan_soru(session.connection(), user.id),
    }


# ------------------------------------------------------------------ sohbetler


@router.get("/assistant/conversations")
def sohbetler(session: DbSession, user: CurrentUser) -> list[dict[str, Any]]:
    satirlar = (
        session.query(AsistanSohbet)
        .filter(AsistanSohbet.kullanici_id == user.id, AsistanSohbet.silindi.is_(False))
        .order_by(AsistanSohbet.guncelleme.desc(), AsistanSohbet.olusturma.desc())
        .limit(SOHBET_LISTE_AZAMI)
        .all()
    )
    return [sohbet_ozeti(s) for s in satirlar]


@router.post("/assistant/conversations", status_code=201)
def sohbet_olustur(
    session: DbSession, user: CurrentUser, govde: SohbetOlustur | None = None
) -> dict[str, Any]:
    baslik = (govde.baslik if govde else None) or None
    if baslik:
        _sir_kontrol(baslik)
    # Sayaç ayrı, hemen commit edilen bağlantıda (öneri uçlarındaki gibi).
    with session.get_bind().begin() as conn:
        izinli = hiz.kova_kontrol(conn, hiz.KOVA_SOHBET_OLUSTUR, kullanici_id=user.id)
    if not izinli:
        raise KodluHata(429, "hiz_siniri", "Çok sık sohbet açıldı; biraz sonra yeniden deneyin.")
    s = AsistanSohbet(kullanici_id=user.id, baslik=baslik)
    session.add(s)
    session.flush()
    session.refresh(s)
    return sohbet_ozeti(s)


@router.delete("/assistant/conversations/{sohbet_id}", status_code=204)
def sohbet_sil(sohbet_id: uuid.UUID, session: DbSession, user: CurrentUser) -> Response:
    """Yumuşak silme. Sohbetin açık (`pending`/`running`) cevapları aynı transaction'da
    iptal edilir: silinen sohbetin mesajına iptal ucu 404 döndüğünden kullanıcı onları başka
    yoldan durduramaz (koşan iş geçitte `should_stop` ile sonraki turda durur)."""
    s = _sohbet(session, sohbet_id, user, kilitle=True)
    # Tarama boşalana dek tekrarlanır: sohbet kilidi (FOR NO KEY UPDATE) worker'ın otomatik
    # çocuk INSERT'ini (FK KEY SHARE) engellemez. Worker üst mesajı kilitliyken tarama o satırda
    # bekler; worker çocuğu ekleyip commit edince READ COMMITTED yalnız üst satırı yeniden
    # değerlendirir (artık `done`, atlanır) ve yeni çocuğu görmez. Sonraki ifade yeni anlık
    # görüntüyle çocuğu bulur ve iptal eder (yoksa ücretli `assistant_deep` koşardı). İlk
    # tarama bu yüzden boş dönse de en az bir kez yeniden taranır.
    ilk = True
    while True:
        acik = (
            session.query(AsistanMesaj)
            .filter(
                AsistanMesaj.sohbet_id == s.id,
                AsistanMesaj.rol == "assistant",
                AsistanMesaj.durum.in_(("pending", "running")),
            )
            .with_for_update()
            .all()
        )
        for m in acik:
            _iptal_et(session, m, user)
        if not acik and not ilk:
            break
        ilk = False
    s.silindi = True
    s.silinme = datetime.now(UTC)
    return Response(status_code=204)


@router.get("/assistant/conversations/{sohbet_id}/messages")
def mesajlar(sohbet_id: uuid.UUID, session: DbSession, user: CurrentUser) -> list[dict[str, Any]]:
    s = _sohbet(session, sohbet_id, user)
    satirlar = (
        session.query(AsistanMesaj)
        .filter(AsistanMesaj.sohbet_id == s.id)
        .order_by(AsistanMesaj.sira)
        .all()
    )
    return [mesaj_ozeti(m) for m in satirlar]


# ------------------------------------------------------------------ soru gönderme


KISMI_SIR = "known_value_partial"  # `gateway.masking.find_secret_patterns` bulgu adı


def _sir_kontrol(*metinler: str, olay_yaz: Callable[[str], None] | None = None) -> None:
    """Soru/bağlamda sır deseni ya da çalışma anı sır değeri → 422 `sir_icerik` (değer yazılmaz).

    Kullanıcı girdisinde yalnız biçim desenleri ve TAM değer aranır: kesme sınırı koruması
    (`known_value_partial`, öneki ≥ 8 karakter) kırpılmış araç çıktısı içindir; burada 422'yi
    karakter karakter tahminle sır çıkaran bir doğrulama aracına (oracle) çevirirdi.

    `olay_yaz(desen_adi)`: reddi güvenlik olayına yazar (dondurma sayacı; yalnız desen adı)."""
    from tp_core.gateway.factory import known_secret_values
    from tp_core.gateway.masking import find_secret_patterns

    degerler = known_secret_values()
    for metin in metinler:
        bulgular = [f for f in find_secret_patterns(metin, degerler) if f.name != KISMI_SIR]
        if metin and bulgular:
            if olay_yaz is not None:
                olay_yaz(bulgular[0].name)
            raise KodluHata(
                422,
                "sir_icerik",
                "Soru veya bağlam gizli bilgi (token, parola, anahtar) içeriyor; "
                "çıkarıp yeniden deneyin.",
            )


def _sir_olayi(session: Session, user: Principal) -> Callable[[str], None]:
    """422 isteği geri alır: olay ayrı, hemen commit edilen bağlantıda (§6.2)."""

    def yaz(desen: str) -> None:
        with session.get_bind().begin() as conn:
            olay.olay_yaz(conn, user.id, olay.TUR_SIR, ayrinti={"desen": desen})

    return yaz


def _dondurma_kontrol(session: Session, user: Principal) -> None:
    """Ardışık ciddi olay dondurması (specs/013 §6.2) → 429 `donduruldu` + `kalan_s`.

    Sır taramasından ÖNCE: donmuş kullanıcı sır denemesiyle sayacı büyütemez, deneme bilgisi de
    sızmaz. Dondurmanın ilk reddinde `donduruldu` olayı ve `asistan.supheli` denetimi ayrı, hemen
    commit edilen bağlantıda yazılır (429 isteği geri alır)."""
    conn = session.connection()
    kalan = olay.dondurma_kalan_s(conn, user.id, _db_simdi(session))
    if kalan is None:
        return
    with session.get_bind().begin() as ayri:
        olay.dondurma_baslat(ayri, user.id, user.kullanici_adi)
    dakika = max(1, -(-kalan // 60))
    raise KodluHata(
        429,
        "donduruldu",
        f"Asistan, art arda engellenen istekler nedeniyle ~{dakika} dk kullanılamıyor.",
        {"Retry-After": str(kalan)},
        ek={"kalan_s": kalan},
    )


def _kisisel_veri_kontrol(*metinler: str) -> None:
    """Soru/bağlamda Luhn'lu kart numarası → 422 `kisisel_veri` (değer yazılmaz; specs/013 §5.1).

    Dondurma sayacına girmez (K11). TCKN/IBAN reddedilmez, worker'da her zaman maskelenir."""
    from tp_core.features.assistant.guvenlik import kart_bul

    if any(kart_bul(m) for m in metinler if m):
        raise KodluHata(
            422,
            "kisisel_veri",
            "Soru kart numarası gibi kişisel veri içeriyor; çıkarıp yeniden deneyin.",
        )


def oneri_gecerli_mi(
    session: Session, kullanici: Principal, kural_id: str, baglam: dict[str, Any] | None
) -> bool:
    """Şerit R'nin kural değerlendiricisi (testler bu adı değiştirebilir)."""
    from tp_core.features.assistant.oneri import oneri_gecerli_mi as _gecerli

    return bool(_gecerli(session, kullanici, kural_id, baglam))


def _oneri_acik() -> bool:
    """`TP_ASISTAN_ONERI` geri alma bayrağı; tek kaynak `oneri.oneri_etkin` (§9)."""
    from tp_core.features.assistant.oneri import oneri_etkin

    return oneri_etkin()


def _oneri_gecersiz() -> KodluHata:
    return KodluHata(409, "oneri_gecersiz", "Bu öneri artık geçerli değil.")


def _sonraki_sira(session: Session, sohbet_id: uuid.UUID) -> int:
    return (
        int(
            session.execute(
                text("SELECT COALESCE(MAX(sira), 0) FROM asistan_mesaj WHERE sohbet_id = :s"),
                {"s": sohbet_id},
            ).scalar_one()
        )
        + 1
    )


def _butce_kontrol(session: Session, user: Principal, kok_id: uuid.UUID | None) -> None:
    asilan = budget.butce_on_kontrol(session.connection(), user.id, kok_id=kok_id)
    if asilan is not None:
        raise KodluHata(402, "butce_asildi", budget.BUTCE_METINLERI[asilan])


def _hiz_kontrol(session: Session, user: Principal, agirlik: int) -> None:
    if budget.saatlik_soru(session.connection(), user.id) + agirlik > budget.SAATLIK_SORU:
        raise KodluHata(
            429, "hiz_siniri", f"Saatte en çok {budget.SAATLIK_SORU} soru sorabilirsiniz."
        )


def _bekleyen_var(*, kapaniyor: bool = False) -> KodluHata:
    if kapaniyor:
        # Durdurulan (`iptal`) ama işi hâlâ kapanan cevap: iş tur başında durana dek sayılır (§9).
        return KodluHata(
            409, "bekleyen_var", "Durdurulan cevap kapanıyor; birkaç saniye sonra yeniden deneyin."
        )
    return KodluHata(409, "bekleyen_var", "Yanıt bekleyen bir sorunuz var; bitmesini bekleyin.")


def _sayac_kontrol(session: Session, user: Principal) -> None:
    conn = session.connection()
    budget.global_kilit(conn)
    bekleyen = budget.kullanici_bekleyen(conn, user.id)
    if bekleyen >= budget.KULLANICI_BEKLEYEN:
        raise _bekleyen_var(kapaniyor=budget.kullanici_kapanan(conn, user.id) >= bekleyen)
    if budget.global_bekleyen(conn) >= budget.global_sinir():
        raise KodluHata(429, "mesgul", "Asistan şu an meşgul; biraz sonra yeniden deneyin.")


def _kisit_adi(exc: IntegrityError) -> str | None:
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    return getattr(diag, "constraint_name", None)


def _ekle(session: Session, *mesajlar: AsistanMesaj) -> None:
    try:
        with session.begin_nested():
            session.add_all(mesajlar)
            session.flush()
    except IntegrityError as exc:
        kisit = _kisit_adi(exc)
        if kisit == MESAJ_UST_UQ:
            raise KodluHata(409, "zaten_derin", "Bu cevap zaten ayrıntılı inceleniyor.") from None
        if kisit in (MESAJ_SIRA_UQ, MESAJ_BEKLEYEN_UQ):
            raise _bekleyen_var() from None
        # Bilinmeyen kısıt: istisna yeniden fırlatılmaz — SQL parametreleri (soru metni, ekran
        # bağlamı) Starlette'in hata günlüğüne düşerdi. Kayda yalnız sınıf ve kısıt adı (§9).
        log.warning("asistan: mesaj eklenemedi (%s, kısıt=%s)", type(exc).__name__, kisit)
        raise KodluHata(500, IC_HATA, SUNUCU_HATASI_METNI) from None


def _kuyruga_al(session: Session, m: AsistanMesaj, user: Principal) -> None:
    m.job_id = jobs.enqueue(
        session.connection(),
        budget.ASISTAN_IS_TURU,
        {"mesaj_id": str(m.id), "kullanici_id": str(user.id), "tetik": "kullanici"},
        idempotency_key=f"{budget.ASISTAN_IS_TURU}:{m.id}",
        max_deneme=1,
        zaman_asimi_s=IS_ZAMAN_ASIMI_S,
    )
    session.flush()


def _derin_ust(
    session: Session, s: AsistanSohbet, user: Principal, ust_id: uuid.UUID
) -> AsistanMesaj:
    ust = session.get(AsistanMesaj, ust_id)
    if ust is None or ust.kullanici_id != user.id or ust.sohbet_id != s.id:
        raise _bulunamadi("Mesaj")
    if ust.rol != "assistant" or ust.durum != "done" or ust.amac == "assistant_deep":
        raise KodluHata(422, "gecersiz_istek", "Bu cevap ayrıntılı incelenemez.")
    var = session.execute(
        text("SELECT 1 FROM asistan_mesaj WHERE ust_mesaj_id = :u"), {"u": ust.id}
    ).first()
    if var is not None:
        raise KodluHata(409, "zaten_derin", "Bu cevap zaten ayrıntılı inceleniyor.")
    return ust


def _hizmet_kontrol(session: Session) -> None:
    neden = hizmet_nedeni(session.get(AsistanDurum, 1), _db_simdi(session))
    if neden is not None:
        raise KodluHata(503, "asistan_kapali", KAPALI_METINLERI[neden], neden=neden)


@router.post("/assistant/conversations/{sohbet_id}/messages", status_code=202)
def soru_gonder(
    sohbet_id: uuid.UUID, govde: SoruGonder, session: DbSession, user: CurrentUser
) -> dict[str, str]:
    _dondurma_kontrol(session, user)
    derin = govde.ust_mesaj_id is not None
    soru = govde.soru
    if not derin:
        if govde.kip == "oneri" and not soru:
            soru = ONERI_SORUSU
        if not soru:
            raise KodluHata(422, "gecersiz_istek", "Soru boş olamaz.")
        _sir_kontrol(
            soru,
            json.dumps(govde.baglam, ensure_ascii=False) if govde.baglam else "",
            olay_yaz=_sir_olayi(session, user),
        )
        _kisisel_veri_kontrol(
            soru,
            json.dumps(govde.baglam, ensure_ascii=False) if govde.baglam else "",
        )

    s = _sohbet(session, sohbet_id, user, kilitle=True)
    ust = _derin_ust(session, s, user, govde.ust_mesaj_id) if govde.ust_mesaj_id else None
    _hizmet_kontrol(session)

    baglam = govde.baglam
    kural_id = None if derin else govde.oneri_kural_id
    # Geri alma bayrağı (`TP_ASISTAN_ONERI=0`) "Başka ne yapabilirim?" kipini de kapatır: öneri
    # kipindeki yeni soru ve onun "Daha ayrıntılı"sı kural önerilerini modele taşırdı.
    oneri_kipi = (ust.kip if ust is not None else govde.kip) == "oneri"
    if (oneri_kipi or kural_id is not None) and not _oneri_acik():
        raise _oneri_gecersiz()
    if kural_id is not None:
        # Kural hesabı (öneri motoru) GET /assistant/suggestions ile aynı kovadan düşer; sayaç
        # ayrı, hemen commit edilen bağlantıda: 409 `oneri_gecersiz` ile reddedilen istek de
        # sayılır (saatlik soru hakkı yalnız eklenen mesajları sayar).
        with session.get_bind().begin() as conn:
            izinli = hiz.kova_kontrol(conn, hiz.KOVA_ONERI_LISTE, kullanici_id=user.id)
        if not izinli:
            raise KodluHata(429, "hiz_siniri", "Çok sık istek; biraz sonra yeniden deneyin.")
        if not oneri_gecerli_mi(session, user, kural_id, baglam):
            raise _oneri_gecersiz()
        baglam = {**(baglam or {}), "oneri": {"kural_id": kural_id}}

    derin_amac = ust is not None and ust.amac == "assistant"
    _hiz_kontrol(session, user, budget.DERIN_AGIRLIK if derin_amac else 1)
    kok_id = budget.kok_mesaj_id(session.connection(), ust.id) if ust is not None else None
    _butce_kontrol(session, user, kok_id)
    _sayac_kontrol(session, user)

    sira = _sonraki_sira(session, s.id)
    if ust is not None:
        # Soru, bağlam, amaç ve kip sunucuda üst mesajdan türetilir; istemcinin `soru`'su yok
        # sayılır. Her asistan mesajı sorusunu `icerik`/`baglam`'da taşır (derin çocuk da
        # üstünden alır); böylece zincirli "Daha ayrıntılı" kök soruda kalır — çocuk sohbetin
        # sonuna eklendiğinden "önceki son kullanıcı mesajı" araya giren başka soru olabilirdi.
        cevap = AsistanMesaj(
            id=uuid.uuid4(),
            sohbet_id=s.id,
            kullanici_id=user.id,
            sira=sira,
            rol="assistant",
            ust_mesaj_id=ust.id,
            icerik=ust.icerik,
            baglam=ust.baglam,
            durum="pending",
            amac="assistant_deep" if derin_amac else "assistant",
            # Kip üstten devralınır: öneri kipindeki cevabın derini de kural önerilerini
            # modele verir ve `oneriler` sözleşmesini korur.
            kip=ust.kip,
            tetik="kullanici",
        )
        _ekle(session, cevap)
    else:
        kip = govde.kip
        soru_mesaji = AsistanMesaj(
            id=uuid.uuid4(),
            sohbet_id=s.id,
            kullanici_id=user.id,
            sira=sira,
            rol="user",
            icerik=soru,
            baglam=baglam,
            durum="done",
            kip=kip,
            tetik="kullanici",
            tamamlanma=datetime.now(UTC),
        )
        cevap = AsistanMesaj(
            id=uuid.uuid4(),
            sohbet_id=s.id,
            kullanici_id=user.id,
            sira=sira + 1,
            rol="assistant",
            icerik=soru,
            baglam=baglam,
            durum="pending",
            kip=kip,
            tetik="kullanici",
        )
        _ekle(session, soru_mesaji, cevap)
        if kural_id is not None and s.oneri_kural_id is None:
            s.oneri_kural_id = kural_id
        if not s.baslik and soru:
            s.baslik = soru[:60]
    s.guncelleme = datetime.now(UTC)
    _kuyruga_al(session, cevap, user)
    return {"mesaj_id": str(cevap.id)}


# ------------------------------------------------------------------ tek mesaj, iptal, geri bildirim


@router.get("/assistant/messages/{mesaj_id}")
def mesaj(mesaj_id: uuid.UUID, session: DbSession, user: CurrentUser) -> dict[str, Any]:
    return mesaj_ozeti(_mesaj(session, mesaj_id, user))


def _iptal_et(session: Session, m: AsistanMesaj, user: Principal) -> None:
    """Kilitli `pending`/`running` cevabı `iptal` yapar; `pending` işi kuyruktan düşer."""
    onceki = m.durum
    m.durum = "iptal"
    m.tamamlanma = datetime.now(UTC)
    if onceki == "pending" and m.job_id is not None:
        jobs.cancel(session.connection(), m.job_id)
    session.flush()
    publish_tx(
        session.connection(),
        EV_ANSWERED,
        {"mesaj_id": str(m.id), "kullanici_id": str(user.id), "durum": "iptal"},
    )


@router.post("/assistant/messages/{mesaj_id}/cancel")
def iptal(mesaj_id: uuid.UUID, session: DbSession, user: CurrentUser) -> dict[str, Any]:
    """`pending` → `iptal` (iş kuyruktan düşer, ücret yok); `running` → `iptal` (worker tur
    başında durur, harcanan yazılır; süren iş bitene kadar sayaçlarda kalır). İdempotent."""
    m = _mesaj(session, mesaj_id, user, kilitle=True)
    if m.rol != "assistant":
        raise KodluHata(422, "gecersiz_istek", "Yalnız asistan cevabı iptal edilebilir.")
    if m.durum == "iptal":
        return mesaj_ozeti(m)
    if m.durum not in ("pending", "running"):
        raise HTTPException(409, "Cevap zaten tamamlandı; iptal edilemez.")
    _iptal_et(session, m, user)
    return mesaj_ozeti(m)


@router.post("/assistant/messages/{mesaj_id}/feedback")
def geri_bildirim(
    mesaj_id: uuid.UUID, govde: MesajGeriBildirim, session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    m = _mesaj(session, mesaj_id, user)
    if m.rol != "assistant":
        raise KodluHata(422, "gecersiz_istek", "Yalnız asistan cevabına geri bildirim verilir.")
    m.geri_bildirim = govde.deger
    return {"id": str(m.id), "geri_bildirim": m.geri_bildirim}
