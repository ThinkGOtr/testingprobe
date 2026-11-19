"""POST /auth/login · POST /auth/logout · GET /auth/me

`TP_AUTH_MODE=aiprobe` kipinde yerel giriş kapalıdır (`/auth/login` 404); giriş
`/auth/aiprobe/*` uçlarındandır (api/routers/aiprobe.py, TEKNIK-TASARIM §8.14). `both` kipinde
bir AI Probe kişisine bağlı (`kimlik_bagi`) hesap yerel parolayla açılmaz (403 `aiprobe_gerekli`).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.auth.client_ip import client_address
from tp_core.auth.deps import Codec, CurrentUser, DbSession, session_codec
from tp_core.auth.display import (
    ROL_ETIKETI,
    ayni_kisi_adlari,
    configured_names,
    display_name,
    kaynakli_ad,
    person_name,
)
from tp_core.auth.login import THROTTLE, OrtakKimlikGerekli, authenticate
from tp_core.auth.sessions import (
    DEVICE_COOKIE_NAME,
    DEVICE_MAX_AGE_S,
    SessionCodec,
    aiprobe_acik,
    cookie_name,
    cookie_secure,
    open_session,
    revoke_session,
)
from tp_core.auth.yetki import rol_izinleri
from tp_core.config import get_settings
from tp_core.models import AppUser, Oturum
from tp_core.models.identity import KimlikBagi
from tp_core.models.tp_proje import TpProje
from tp_core.workflow.service import Principal

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    kullanici_adi: str = Field(min_length=1, max_length=64)
    parola: str = Field(min_length=1, max_length=256)


class Me(BaseModel):
    id: uuid.UUID
    kullanici_adi: str
    rol: str
    # Rolün görünen adı (specs/012-rol-yetki §3, `yetki.ROL_ETIKETLERI`).
    rol_etiketi: str = ""
    # Rolün izin anahtarları (sıralı; `yetki.rol_izinleri`). Portal menü/sayfa/düğmeleri bununla
    # gösterir; kontrol yine çekirdektedir.
    izinler: list[str] = Field(default_factory=list)
    # Yalnızca gösterim (yetki rolle): "Cengizhan Gunaydin · Analist"; ad tanımsızsa rol etiketi.
    gorunen_ad: str
    ad_soyad: str | None = None
    # Adın kaynağı: "aiprobe" = AI Probe hesabından (JIT; TP doğrulamaz). Yerel/yapılandırılmış
    # adda boş. `gorunen_ad` ve `kisiler`de bu adlar "(AI Probe)" ile işaretlidir.
    ad_kaynak: str | None = None
    # Portalın denetim/onay görünümlerinde kullanıcı adlarını çevirmesi için tüm portal
    # kullanıcılarının görünen adları ({kullanici_adi: gorunen_ad}).
    kisiler: dict[str, str] = Field(default_factory=dict)


def me_of(session: Session, user_id: uuid.UUID, kullanici_adi: str, rol: str) -> Me:
    kimlikli = session.execute(
        select(AppUser.id, AppUser.kullanici_adi, AppUser.rol, AppUser.ad_soyad, AppUser.ad_kaynak)
    ).all()
    kullanicilar = [(k, r, a, ak) for _id, k, r, a, ak in kimlikli]
    # Yapılandırılmış adlar önce gelir; JIT (AI Probe) hesaplarında ad veritabanındadır ve
    # gösterimde "(AI Probe)" ile işaretlenir (kişinin kendi AI Probe hesabından, doğrulanmamış).
    names = configured_names()
    kisi_adi: dict[str, str] = {}
    kaynak: str | None = None
    for k, _r, ad_soyad, ad_kaynak in kullanicilar:
        anahtar = k.strip().lower()
        if ad_soyad and anahtar not in names:
            kisi_adi[anahtar] = ad_soyad
            names[anahtar] = kaynakli_ad(ad_soyad, ad_kaynak) or ad_soyad
            if k == kullanici_adi:
                kaynak = ad_kaynak
    # Aynı kişinin birden çok hesabı (ör. iki AI Probe girişi) tek adla görünür (TP UX YD-05):
    # "kimi bekliyoruz" listesi aynı kişiyi iki farklı adla iki kez yazmaz.
    bagli = dict(session.execute(select(KimlikBagi.app_user_id, KimlikBagi.external_uid)).all())
    kisi = ayni_kisi_adlari(
        ((k, r, a, ak, bagli.get(uid)) for uid, k, r, a, ak in kimlikli), configured_names()
    )
    for k, (_kok, tercih, temsilci) in kisi.items():
        if temsilci != k:
            names[k.strip().lower()] = tercih
    anahtar = kullanici_adi.strip().lower()
    return Me(
        id=user_id,
        kullanici_adi=kullanici_adi,
        rol=rol,
        rol_etiketi=ROL_ETIKETI.get(rol, rol),
        izinler=rol_izinleri(rol),
        gorunen_ad=display_name(kullanici_adi, rol, names),
        ad_soyad=kisi_adi.get(anahtar) or person_name(kullanici_adi, names),
        ad_kaynak=kaynak,
        kisiler={k: display_name(k, r, names) for k, r, _a, _k in kullanicilar},
    )


def set_session_cookie(yanit: Response, codec: SessionCodec, user: AppUser, sid: uuid.UUID) -> None:
    """Oturum çerezi: ad ve Secure kipe göre (`local` → `tp_session`, diğer → `__Host-`)."""
    yanit.set_cookie(
        cookie_name(),
        codec.dumps(user.id, user.parola_hash, sid, user.auth_epoch or 0),
        max_age=codec.max_age_s,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
        path="/",
    )


def throttle_key(request: Request, kullanici_adi: str, codec: SessionCodec) -> str:
    """Deneme sınırı anahtarı.

    - İstemci bu kullanıcı için daha önce başarıyla giriş yapmışsa (imzalı `tp_cihaz` çerezi) sayaç
      o cihaza özeldir: aynı IP'yi paylaşan başka biri (portal proxy'si, NAT, aynı makine) yanlış
      parolalarla bu kullanıcıyı kendi tarayıcısından kilitleyemez.
    - Değilse (kullanıcı adı, gerçek istemci adresi): adres güvenilen proxy'nin
      X-Forwarded-For'undan (`client_address`); doğrudan bağlantıda TCP eşi.
    """
    ad = kullanici_adi.strip().lower()
    raw = request.cookies.get(DEVICE_COOKIE_NAME)
    cihaz = codec.loads_device(raw) if raw else None
    if cihaz is not None and cihaz.kullanici == ad:
        return f"{ad}|cihaz:{cihaz.cihaz}"
    return f"{ad}|ip:{client_address(request)}"


@router.post("/login", response_model=Me)
def login(body: LoginIn, request: Request, session: DbSession, codec: Codec) -> JSONResponse:
    if get_settings().auth_mode == "aiprobe":
        raise HTTPException(404, "Yerel giriş kapalı; AI Probe hesabıyla giriş yapın")
    anahtar = throttle_key(request, body.kullanici_adi, codec)
    # Hak, (yavaş) argon2 doğrulamasından önce atomik olarak ayrılır: eşzamanlı yanlış parolalar
    # pencerede en çok MAX_DENEME kez doğrulanır.
    if not THROTTLE.try_acquire(anahtar):
        return JSONResponse(
            {
                "detail": "Çok fazla hatalı deneme. Birkaç dakika sonra tekrar deneyin.",
                "kod": "hiz_siniri",
            },
            status_code=429,
        )
    try:
        user = authenticate(session, body.kullanici_adi, body.parola, client_address(request))
    except OrtakKimlikGerekli:
        THROTTLE.success(anahtar)
        return JSONResponse(
            {
                "detail": "Bu hesap AI Probe hesabınıza bağlı; AI Probe ile giriş yapın",
                "kod": "aiprobe_gerekli",
            },
            status_code=403,
        )
    if user is None:
        # İstisna değil yanıt: başarısız deneme denetim kaydıyla birlikte commit edilir.
        return JSONResponse(
            {"detail": "Kullanıcı adı veya parola hatalı", "kod": "yetkisiz"}, status_code=401
        )
    THROTTLE.success(anahtar)
    sid = open_session(session, user.id, codec.max_age_s)
    yanit = JSONResponse(
        me_of(session, user.id, user.kullanici_adi, user.rol).model_dump(mode="json")
    )
    set_session_cookie(yanit, codec, user, sid)
    # Tanınan cihaz: mevcut geçerli çerez korunur (cihaz kimliği sabit kalır), yoksa yenisi.
    raw = request.cookies.get(DEVICE_COOKIE_NAME)
    mevcut = codec.loads_device(raw) if raw else None
    cihaz = mevcut.cihaz if mevcut is not None else None
    yanit.set_cookie(
        DEVICE_COOKIE_NAME,
        codec.dumps_device(user.kullanici_adi, cihaz),
        max_age=DEVICE_MAX_AGE_S,
        httponly=True,
        samesite="strict",
        secure=cookie_secure(),
        path="/",
    )
    return yanit


@router.post("/logout")
def logout(
    request: Request, session: DbSession, codec: Annotated[SessionCodec, Depends(session_codec)]
) -> Response:
    """Yerel oturumu kapatır. AI Probe oturumunda tüm ürünlerden çıkış sayfası
    `{home}/logout?product=<id>&auto=1` (yerel çıkış yapıldı → home onay istemez).

    Yanıt her zaman JSON `{"ok", "redirect"?}`: portal (fetch) yönlendirmeyi kendisi izler. Form
    POST'u ile 303 yönlendirme yoktur (CSP `form-action 'self'` home kaynağına izin vermez).
    """
    raw = request.cookies.get(cookie_name())
    veri = codec.loads(raw) if raw else None
    govde: dict[str, object] = {"ok": True}
    if veri is not None:
        user = session.get(AppUser, veri.user_id)
        harici = session.scalar(
            select(Oturum.external_uid).where(Oturum.id == veri.sid, Oturum.user_id == veri.user_id)
        )
        # Yalnızca etkin bir oturum iptal edildiyse denetime yazılır (çerez kopyasıyla tekrar
        # çıkış "logout" kaydı üretmez).
        if user is not None and revoke_session(session, veri):
            audit_on_commit(
                session, user.kullanici_adi, "auth.logout", f"app_user:{user.id}", {"sid": veri.sid}
            )
        # AI Probe oturumu: çıkış yalnız bu ürünün oturumunu kapatır, AI Probe ana sayfasına döner
        # (AI Probe oturumu açık kalır; tüm ürünlerden çıkış home'daki "Çıkış"tır).
        if harici is not None and aiprobe_acik():
            ayar = get_settings()
            govde["redirect"] = f"{ayar.aiprobe_id_origin.rstrip('/')}/"
    yanit = JSONResponse(govde)
    yanit.delete_cookie(
        cookie_name(), path="/", httponly=True, samesite="lax", secure=cookie_secure()
    )
    return yanit


class MeYaniti(Me):
    """`GET /auth/me`: AI Probe oturumunda ayrıca `product`, `roles` (değiştirici, "Rol değiştir").

    Alanlar yalnız AI Probe oturumunda yazılır (`response_model_exclude_unset`): yerel oturumun
    yanıtı bugünküyle aynıdır.
    """

    product: str | None = None
    # Kişiye bağlı rol hesaplarından AI Probe'un şu an verdiği (proje kipinde: seçili projedeki)
    # rollerdekiler (sıralı).
    roles: list[str] | None = None
    # Kişinin tüm AI Probe ürünlerindeki rolleri (`{"tp": [...], "ap": [...]}`; devir/kontrol
    # yanıtından, oturumda saklanır). Değiştirici diğer ürünlere erişimi buradan bilir.
    products: dict[str, list[str]] | None = None
    # Config R1 (yalnız Home etkin config'i yüklüyken; `CONFIG_SOURCE=env`de alan yok): projenin
    # özellikleri (portal kapalı ekranları gizler) ve başlıkta gösterilen organizasyon / proje.
    ozellikler: dict[str, bool] | None = None
    organizasyon: dict[str, str] | None = None
    # `{pid, kod, ad}` (+ geriye uyum için `id` = pid).
    proje: dict[str, str | None] | None = None
    # Çok proje (TP-COK-PROJE-PLANI §6.2; yalnız proje kipinde): seçili projedeki TP rolleri ve
    # kişinin erişebildiği proje sayısı. `izinler` seçili projede etkin rol yoksa boştur.
    roller: list[str] | None = None
    projeler_sayisi: int | None = None


def _proje_alani(pid: str, kod: Any, ad: Any) -> dict[str, str | None]:
    return {
        "pid": pid,
        "kod": str(kod) if kod else None,
        "ad": str(ad or "") or pid,
        "id": pid,
    }


def _proje_baglami(yanit: MeYaniti, durum: object, pid: str | None) -> None:
    """Home etkin config'i yüklüyse (varsayılan ya da seçili proje) özellikler + başlık."""
    from tp_core.home_config import durum as home_durum

    op = home_durum.org_proje(pid)
    ozellikler = home_durum.ozellikler(pid)
    if ozellikler is not None:
        yanit.ozellikler = ozellikler  # Home reddettiyse (N4) proje yok, özellikler kapalı
    if op is None or ozellikler is None:
        return
    org, proje = op
    oid = str(org.get("oid") or getattr(durum, "org_id", None) or "")
    if oid or org.get("name"):
        yanit.organizasyon = {"id": oid, "ad": str(org.get("name") or "")}
    yanit.proje = _proje_alani(str(proje.get("pid") or pid or ""), proje.get("code"),
                               proje.get("name"))  # fmt: skip


def _cok_proje(yanit: MeYaniti, user: Principal, uid: str, session: Session) -> None:
    """Proje kipi: seçili proje, oradaki roller, proje sayısı, izinler (seçili projeye göre)."""
    from tp_core.auth import aiprobe

    pid = user.project_id or ""
    yanit.roller = sorted(user.roller)
    if user.rol not in user.roller:
        yanit.izinler = []
    try:
        projeler = aiprobe.kullanici_projeleri(uid)
    except aiprobe.HomeUlasilamaz:
        projeler = []
    yanit.projeler_sayisi = len(projeler)
    ozet = next((p for p in projeler if p.pid == pid), None)
    if yanit.proje is None:
        satir = session.get(TpProje, pid)
        kod = (ozet.kod if ozet else None) or (satir.kod if satir else None)
        ad = (ozet.ad if ozet else None) or (satir.ad if satir else None)
        yanit.proje = _proje_alani(pid, kod, ad)
    if yanit.organizasyon is None and ozet is not None and (ozet.oid or ozet.org_ad):
        yanit.organizasyon = {"id": ozet.oid or "", "ad": ozet.org_ad or ""}


def me_yaniti(session: Session, user: Principal, durum: object | None) -> MeYaniti:
    """`/auth/me` gövdesi (`PUT /proje` de yeni durumu bununla döner)."""
    assert user.id is not None
    yanit = MeYaniti(**me_of(session, user.id, user.kullanici_adi, user.rol).model_dump())
    uid = getattr(durum, "external_uid", None)
    if uid is not None:
        from tp_core.auth import aiprobe

        yanit.product = get_settings().aiprobe_product_id
        urunler = getattr(durum, "urunler", None) or {}
        yanit.products = urunler
        # Yalnız AI Probe'un şu an verdiği roller (bağlı hesap rolleriyle kesişim): oturumdaki ürün
        # haritası (devirde ve her kontrolde home'dan yenilenir); yoksa önbellekli kontrol; home'a
        # ulaşılamazsa yalnız etkin rol. Proje kipinde ayrıca seçili projenin rolleriyle kesişim.
        tp_haritasi = urunler.get(aiprobe.URUN_KODU)
        if isinstance(tp_haritasi, list):
            verilen: set[str] = {str(r) for r in tp_haritasi}
        else:
            try:
                verilen = set(aiprobe.kontrol_et(uid, aiprobe.OturumKimligi.of(durum)).roles)
            except aiprobe.ProjeRolleriYok:
                verilen = set()
            except aiprobe.HomeUlasilamaz:
                verilen = {user.rol}
        bagli = {h.rol for h in aiprobe.bagli_hesaplar(session, uid)}
        if aiprobe.proje_kipi():
            # Proje kipi: verilen roller = seçili projedeki (Home `/v1/projects`, `acr` süzgeçli);
            # ürün haritasındaki `tp` de seçili projenin rolleridir.
            verilen = set(user.roller)
            yanit.products = dict(urunler) | {aiprobe.URUN_KODU: sorted(user.roller)}
        yanit.roles = sorted(bagli & verilen)
    _proje_baglami(yanit, durum, user.project_id)
    if uid is not None:
        from tp_core.auth import aiprobe

        if aiprobe.proje_kipi():
            _cok_proje(yanit, user, uid, session)
    return yanit


@router.get("/me", response_model=MeYaniti, response_model_exclude_unset=True)
def me(user: CurrentUser, request: Request, session: DbSession) -> MeYaniti:
    return me_yaniti(session, user, getattr(request.state, "oturum_durumu", None))
