"""Durum makinesi servisi: `transition()` durum alanlarını değiştirmenin TEK yoludur.

Her geçiş aynı işlemde: satırı `FOR UPDATE` ile kilitler, `expected_from` ile iyimser eşzamanlılık
denetimi yapar, izinli geçiş tablosunu (workflow.states) ve koşulları uygular, insan kapılarında
Postgres'teki onay kaydının içerik hash'ini güncel içerikle karşılaştırır, denetim zincirine yazar
ve commit'te yayılan bir olay (`<varlık>.state`) bırakır.

Onaylar `record_approval()` ile `review` tablosuna yazılır (kullanıcı + nesne + içerik hash'i,
Constitution I). IDE (MCP token) ve sistem aktörleri onay veremez. Portal kararı, insanın ekranda
gördüğü içeriğin hash'ini (`beklenen_hash`) taşımak zorundadır; içerik arada değiştiyse karar
reddedilir (409). Kararla gelen düzenleme (`degisiklik`) görülen hash denetiminden SONRA uygulanır
ve onaylanan hash düzenlenmiş içeriğin hash'idir. Jira kanalında ürünün kendi bot kimlikleri PO
onaylayıcısı sayılmaz ve onay etiketin konduğu andaki içeriğe bağlanır (`onay_zamani`).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit, content_hash
from tp_core.config import get_settings
from tp_core.events.bus import publish_tx
from tp_core.models import Review
from tp_core.models.guard import allow_state_write
from tp_core.workflow.states import (
    APPROVER_ROLES,
    APPROVING,
    CONTENT_FIELDS,
    DECISION_EDIT_REQUIRED,
    DECISION_EDITS,
    DECISION_GEREKCE_REQUIRED,
    KARARLAR,
    MACHINES,
    RET_NEDENLERI,
    TEST_CASE_KARAR_IZNI,
    Machine,
)


@dataclass(frozen=True)
class Principal:
    """İşlemi yapan kimlik. `kanal`: portal (oturum), ide (MCP token), system (worker)."""

    id: uuid.UUID | None
    kullanici_adi: str
    rol: str
    kanal: str = "portal"
    kapsam: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id) if self.id else None,
            "kullanici_adi": self.kullanici_adi,
            "rol": self.rol,
        }


SYSTEM = Principal(None, "system", "system", "system")

Actor = Principal | str


class WorkflowError(Exception):
    """Durum makinesi/onay hatası; API 409 (veya alt sınıfın kodu) döner.

    `kod`: yanıta yazılan sabit, makinece okunur hata kodu (MIMARI-SOZLESME §5). Sınıf başına
    sabittir; mesaj metninden asla türetilmez. `None` ise API durum kodundan genel kodu üretir
    (409 → `cakisma`, 404 → `bulunamadi` …).
    """

    status_code = 409
    kod: str | None = None


class InvalidTransition(WorkflowError):
    kod = "gecersiz_gecis"


class ConcurrentTransition(WorkflowError):
    kod = "eszamanli_gecis"


class GateClosed(WorkflowError):
    kod = "kapi_kapali"


class OnayHashUyusmuyor(GateClosed):
    """Karar verilen içerik, kullanıcının gördüğü içerikten (icerik_hash) farklı."""

    kod = "onay_hash_uyusmuyor"


class GuardFailed(WorkflowError):
    status_code = 422
    kod = "kosul_saglanmadi"


class ApprovalNotAllowed(WorkflowError):
    status_code = 403
    kod = "onay_yetkisi_yok"


class InvalidDecision(WorkflowError):
    status_code = 422
    kod = "gecersiz_karar"


def actor_name(actor: Actor) -> str:
    return actor.kullanici_adi if isinstance(actor, Principal) else actor


def entity_kind(entity: Any) -> str:
    kind = getattr(type(entity), "__tablename__", None)
    if kind not in MACHINES:
        raise TypeError(f"durum makinesi olmayan nesne: {type(entity).__name__}")
    return kind


def machine_for(entity: Any) -> Machine:
    return MACHINES[entity_kind(entity)]


def content_hash_of(entity: Any) -> str:
    """Nesnenin onaya konu içerik hash'i (sha256, kanonik JSON).

    Tek alanlı varlıklarda (test_case, bug_draft: `icerik`) doğrudan o alanın hash'idir; böylece
    `icerik_hash` kolonu `content_hash(icerik)` ile aynı değeri taşır.
    """
    kind = entity_kind(entity)
    alanlar = CONTENT_FIELDS.get(kind)
    if alanlar is None:
        raise TypeError(f"{kind} için içerik hash'i tanımlı değil")
    if len(alanlar) == 1:
        return content_hash(getattr(entity, alanlar[0]))
    return content_hash({a: getattr(entity, a) for a in alanlar})


def latest_review(session: Session, kind: str, nesne_id: uuid.UUID) -> Review | None:
    return session.scalars(
        select(Review)
        .where(Review.nesne_turu == kind, Review.nesne_id == nesne_id)
        .order_by(Review.sira.desc())
        .limit(1)
    ).first()


def approved_hash_matches(
    session: Session, entity: Any, kararlar: frozenset[str] | None = None
) -> bool:
    """Son insan kararı onaylayan bir karar mı ve onaylanan hash güncel içerikle aynı mı?

    Yayın/PR/bug adımları bunu çağırır; onaydan sonra içerik değiştiyse False döner.
    Nesnenin `onaylanan_hash` alanı doluysa o da güncel hash'e eşit olmalıdır.
    """
    kind = entity_kind(entity)
    kararlar = kararlar if kararlar is not None else APPROVING.get(kind, frozenset())
    son = latest_review(session, kind, entity.id)
    if son is None:
        return False
    if son.karar not in kararlar and not (
        "approve" in kararlar and eski_analist_onayi(session, son)
    ):
        return False
    guncel = content_hash_of(entity)
    if son.onaylanan_hash != guncel:
        return False
    kayitli = getattr(entity, "onaylanan_hash", None)
    return kayitli is None or kayitli == guncel


def eski_analist_onayi(session: Session, review: Review) -> bool:
    """012 öncesi son onay: analist hesabının test_case `edit` kararı.

    0023 göçü, göç anında var olan analist `edit` kayıtlarını `review.eski_onay` ile işaretler;
    yayın / kod üretimi kapısında `approve` sayılır (hash eşleşmesi yine şarttır). Karar verenin
    güncel rolüne bakılmaz: hesabın rolü sonradan değişse de sonuç değişmez. Yeni kayıtlar
    (Testçi `edit`'i) işaretsizdir. `session` imza uyumu için kalır.
    """
    del session
    return review.nesne_turu == "test_case" and review.karar == "edit" and review.eski_onay


# Jira simülatörünün bot kimlikleri: yapılandırmadan bağımsız olarak her zaman ayrılmıştır.
SIM_BOT_KIMLIKLERI = frozenset({"writer@sim.local", "reader@sim.local"})


def _liste(deger: str | None) -> set[str]:
    return {p.strip().casefold() for p in (deger or "").split(",") if p.strip()}


def reserved_jira_identities() -> frozenset[str]:
    """Ürünün kendi Jira kimlikleri (küçük harf): okuma/yazma e-postaları ve bot accountId'leri."""
    ayar = get_settings()
    kimlikler = set(SIM_BOT_KIMLIKLERI)
    if ayar.test_tek_hesap:
        # TP_TEST_TEK_HESAP=1 (yalnız test): ürünün hesabı PO olarak da kabul edilir.
        return frozenset(kimlikler)
    kimlikler |= _liste(ayar.jira_write_email) | _liste(ayar.jira_read_email)
    kimlikler |= _liste(ayar.jira_bot_account_ids)
    return frozenset(kimlikler)


def check_jira_approver(harici_onaylayan: str | None) -> str:
    """Jira etiketinden gelen PO onaylayanını doğrular; temizlenmiş kimliği döndürür.

    Bot (ürünün yazma/okuma hesabı) etiketi koyduysa bu bir insan onayı değildir (Constitution I).
    `TP_PO_JIRA_USERS` tanımlıysa onaylayan o listede olmalıdır.
    """
    ad = (harici_onaylayan or "").strip()
    if not ad:
        raise ApprovalNotAllowed("Jira kanalı yalnızca PO teyidi için ve onaylayanla kullanılır")
    if ad.casefold() in reserved_jira_identities():
        raise ApprovalNotAllowed(f"Jira onayı ürünün kendi hesabından ({ad}); insan onayı değil")
    izinli = _liste(get_settings().po_jira_users)
    if izinli and ad.casefold() not in izinli:
        raise ApprovalNotAllowed(f"{ad} PO onaylayıcıları listesinde (TP_PO_JIRA_USERS) değil")
    return ad


def karar_rolleri(kind: str, karar: str) -> frozenset[str]:
    """Portal kanalında `kind` için `karar`'ı verebilecek roller (derinlemesine savunma).

    test_case'te karar başına izin kataloğa (auth/yetki.py) bağlıdır: Testçi kararları
    `case.decide`, son onay (`approve`/`send_back`) `case.approve`. Diğer türler
    `APPROVER_ROLES`'taki tür düzeyi kümeyi kullanır (requirement: PO; PO teyidi Jira'dadır).
    """
    izin_adi = TEST_CASE_KARAR_IZNI.get(karar) if kind == "test_case" else None
    if izin_adi is None:
        return APPROVER_ROLES.get(kind, frozenset())
    # Gecikmeli içe aktarma: yetki modülü bu modülün Principal'ını içe aktarır (döngü).
    from tp_core.auth.yetki import roller_icin

    return roller_icin(izin_adi)


def _rol_karar_verebilir(rol: str, kind: str, karar: str) -> bool:
    from tp_core.auth.yetki import normalize_rol

    return normalize_rol(rol) in karar_rolleri(kind, karar)


# Derinlemesine savunma mesajları (portal düğme adlarıyla).
NESNE_ETIKETLERI: dict[str, str] = {
    "test_case": "case",
    "requirement": "gereksinim",
    "bug_draft": "bug taslağı",
    "script": "script",
    "consistency_finding": "tutarlılık bulgusu",
}
KARAR_ETIKETLERI: dict[str, str] = {
    "accept": "Olduğu gibi kabul",
    "edit": "Düzelterek kabul",
    "reject": "Reddet",
    "reopen": "Taslağa al",
    "approve": "Onayla",
    "send_back": "Geri gönder",
    "po_approve": "PO onayı",
    "po_reject": "PO reddi",
    "new": "Yeni bug aç",
    "link": "Mevcut bug'a bağla",
    "dismiss": "Yoksay",
    "merge": "Merge",
    "request_changes": "Değişiklik iste",
    "fix_doc": "Dokümanı düzelt",
    "code_defect": "Kod hatası",
    "accept_difference": "Farkı kabul et",
}


def karar_red_mesaji(rol: str, kind: str, karar: str) -> str:
    """Ör. "Testçi rolü case için 'Onayla' kararı veremez"."""
    from tp_core.auth.yetki import ROL_ETIKETLERI, normalize_rol

    rol_etiketi = ROL_ETIKETLERI.get(normalize_rol(rol), rol)
    nesne = NESNE_ETIKETLERI.get(kind, kind)
    return f"{rol_etiketi} rolü {nesne} için '{KARAR_ETIKETLERI.get(karar, karar)}' kararı veremez"


def karar_izni(kind: str, karar: str) -> str:
    """Kararın katalog izni (denetim kaydı için); bilinmiyorsa `<tür>.decide`."""
    from tp_core.auth.yetki import KARAR_IZNI

    if kind == "test_case":
        return TEST_CASE_KARAR_IZNI.get(karar, "case.decide")
    if kind == "requirement":
        if karar == "po_reject":
            return "requirement.po_reject_free_text"
        return "requirement.po_approve_free_text"
    return KARAR_IZNI.get(kind, f"{kind}.decide")


def _uygula_degisiklik(
    entity: Any, kind: str, karar: str, degisiklik: Mapping[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Kararla gelen içerik değişikliğini uygular; (önce, sonra) değerlerini döndürür."""
    izinli = DECISION_EDITS.get(kind, {}).get(karar, frozenset())
    if not degisiklik:
        if karar in DECISION_EDIT_REQUIRED.get(kind, frozenset()):
            raise InvalidDecision(f"{kind} '{karar}' kararı düzenlenmiş içerikle verilir")
        return {}, {}
    fazla = sorted(set(degisiklik) - izinli)
    if fazla:
        raise InvalidDecision(f"{kind} '{karar}' kararı şu alanları değiştiremez: {fazla}")
    once = {a: getattr(entity, a) for a in degisiklik}
    for alan, deger in degisiklik.items():
        setattr(entity, alan, deger)
    if kind in ("test_case", "bug_draft") and "icerik" in degisiklik:
        entity.icerik_hash = content_hash(degisiklik["icerik"])
    return once, dict(degisiklik)


def _jira_onayini_bagla(
    entity: Any, onay_zamani: datetime | None, beklenen_hash: str | None, guncel: str
) -> None:
    """Jira etiketiyle gelen PO onayını etiketin konduğu andaki içeriğe bağlar.

    Etiket, gereksinimin içeriği en son değiştikten SONRA konmuş olmalıdır; aksi halde PO'nun
    gördüğü metin bugünkü metin değildir ve onay yeniden istenir (Constitution I).
    """
    if onay_zamani is None or onay_zamani.tzinfo is None:
        raise InvalidDecision("Jira PO onayı etiketin konma zamanını (saat dilimli) taşımalı")
    degisim = getattr(entity, "icerik_degisim", None)
    if degisim is not None and degisim > onay_zamani:
        raise GateClosed(
            "requirement: PO etiketi içerik son değiştirilmeden önce konmuş "
            f"(etiket {onay_zamani.isoformat()}, içerik {degisim.isoformat()}); "
            "PO'nun güncel metni yeniden onaylaması gerekir"
        )
    if beklenen_hash is not None and beklenen_hash != guncel:
        raise GateClosed("requirement: PO'nun onayladığı içerik güncel içerikle aynı değil")


def record_approval(
    session: Session,
    entity: Any,
    user: Principal | None,
    karar: str,
    *,
    ret_nedeni: str | None = None,
    gerekce: str | None = None,
    once: Mapping[str, Any] | None = None,
    sonra: Mapping[str, Any] | None = None,
    duzeltme_olculeri: Mapping[str, Any] | None = None,
    harici_onaylayan: str | None = None,
    kanal: str = "portal",
    beklenen_hash: str | None = None,
    degisiklik: Mapping[str, Any] | None = None,
    onay_zamani: datetime | None = None,
) -> Review:
    """İnsan kararını `review` tablosuna yazar (kullanıcı + nesne + onaylanan içerik hash'i).

    İki hash ayrıdır:

    - `beklenen_hash` (görülen): kararı veren insanın ekranda gördüğü, kararın değişikliği
      UYGULANMADAN önceki içeriğin hash'i (portal karar gövdesindeki `icerik_hash`). Portal
      kanalında zorunludur; güncel içerikle eşleşmezse `GateClosed` (409).
    - `review.onaylanan_hash`: kararla gelen değişiklik (`degisiklik`; ör. test_case 'edit' →
      `{"icerik": ...}`) uygulandıktan SONRAki içerik. Kapılar bunu güncel içerikle karşılaştırır.

    Router değişikliği kendisi UYGULAMAZ; düzenlenmiş alanları `degisiklik` ile verir. İzinli
    alanlar `states.DECISION_EDITS`'tedir. consistency_finding kararlarında `analist_karari`
    (= karar), `gerekce`, `karar_veren_id`, `karar_zamani` burada yazılır.

    `kanal='jira'` yalnızca PO teyidinin Jira etiketinden okunduğu yol içindir
    (`harici_onaylayan` = etiketi koyan Jira kullanıcısı; bot hesapları reddedilir).
    `onay_zamani` (etiketin konma anı, changelog'dan) zorunludur: gereksinimin içeriği o andan
    sonra değiştiyse (`requirement.icerik_degisim`) onay reddedilir. `beklenen_hash` verilirse
    (etiket anındaki içerik hash'i) güncel içerikle eşleşmelidir.
    """
    kind = entity_kind(entity)
    if karar not in KARARLAR.get(kind, frozenset()):
        raise InvalidDecision(f"{kind} için geçersiz karar: {karar}")
    if kanal == "jira":
        if kind != "requirement":
            raise ApprovalNotAllowed("Jira kanalı yalnızca PO teyidi için kullanılır")
        harici_onaylayan = check_jira_approver(harici_onaylayan)
        aktor = f"jira:{harici_onaylayan}"
        user_id = None
    elif kanal == "portal":
        if user is None or user.id is None or user.kanal != "portal":
            raise ApprovalNotAllowed("onay yalnızca portalda oturum açmış bir kullanıcıyla verilir")
        if not _rol_karar_verebilir(user.rol, kind, karar):
            # Rol nedeniyle red: HTTP izin katmanını aşan istek de `authz.denied` bırakır.
            from tp_core.auth.yetki import denetle_red

            denetle_red(
                session, user, karar_izni(kind, karar), "rol", f"{kind}:{entity.id}:{karar}"
            )
            raise ApprovalNotAllowed(karar_red_mesaji(user.rol, kind, karar))
        aktor = user.kullanici_adi
        user_id = user.id
    else:
        raise ApprovalNotAllowed(f"geçersiz onay kanalı: {kanal}")
    if karar == "reject" and ret_nedeni not in RET_NEDENLERI:
        raise InvalidDecision(f"ret nedeni taksonomiden olmalı: {sorted(RET_NEDENLERI)}")
    # Script review'da "değişiklik iste" de taksonomik ret nedeni taşır (TEKNIK-TASARIM §8.4,
    # Constitution X: ret nedenleri ölçülür).
    if ret_nedeni is not None and karar not in ("reject", "request_changes"):
        raise InvalidDecision("ret nedeni yalnızca 'reject' / 'request_changes' kararında verilir")
    if ret_nedeni is not None and ret_nedeni not in RET_NEDENLERI:
        raise InvalidDecision(f"ret nedeni taksonomiden olmalı: {sorted(RET_NEDENLERI)}")
    if karar in DECISION_GEREKCE_REQUIRED.get(kind, frozenset()) and not (gerekce or "").strip():
        raise InvalidDecision(f"'{karar}' kararı gerekçe ister")

    session.flush()
    gorulen = content_hash_of(entity)
    if kanal == "jira":
        _jira_onayini_bagla(entity, onay_zamani, beklenen_hash, gorulen)
    else:
        if beklenen_hash is None:
            raise InvalidDecision("karar, görüntülenen içeriğin hash'ini (icerik_hash) taşımalı")
        if beklenen_hash != gorulen:
            raise OnayHashUyusmuyor(
                f"{kind}: içerik siz görüntüledikten sonra değişmiş; yenileyip tekrar karar verin"
            )

    eski, yeni = _uygula_degisiklik(entity, kind, karar, degisiklik)
    if kind == "consistency_finding":
        entity.analist_karari = karar
        entity.gerekce = gerekce
        entity.karar_veren_id = user_id
        entity.karar_zamani = datetime.now(UTC)
    session.flush()
    h = content_hash_of(entity)

    review = Review(
        nesne_turu=kind,
        nesne_id=entity.id,
        user_id=user_id,
        harici_onaylayan=harici_onaylayan if kanal == "jira" else None,
        kanal=kanal,
        karar=karar,
        ret_nedeni=ret_nedeni,
        gerekce=gerekce,
        once=dict(once) if once is not None else (eski or None),
        sonra=dict(sonra) if sonra is not None else (yeni or None),
        duzeltme_olculeri=dict(duzeltme_olculeri) if duzeltme_olculeri is not None else None,
        onaylanan_hash=h,
    )
    session.add(review)
    session.flush()
    conn = session.connection()
    ozet: dict[str, Any] = {"karar": karar, "hash": h, "kanal": kanal, "review_id": review.id}
    if gorulen != h:
        ozet["gorulen_hash"] = gorulen
    if yeni:
        ozet["degisen_alanlar"] = sorted(yeni)
    if kanal == "jira" and onay_zamani is not None:
        ozet["onay_zamani"] = onay_zamani
    if ret_nedeni:
        ozet["ret_nedeni"] = ret_nedeni
    audit_on_commit(session, aktor, f"review.{karar}", f"{kind}:{entity.id}", ozet)
    publish_tx(
        conn,
        "review.recorded",
        {"id": review.id, "nesne_turu": kind, "nesne_id": entity.id, "karar": karar},
    )
    return review


def transition[E](
    session: Session,
    entity: E,
    to_state: str,
    actor: Actor,
    expected_from: str,
    *,
    sebep: str | None = None,
    ozet: Mapping[str, Any] | None = None,
) -> E:
    """`entity.durum`'u `expected_from` → `to_state` yapar; tek izinli yol.

    Hatalar: `ConcurrentTransition` (durum beklenen değil), `InvalidTransition` (tabloda yok),
    `GuardFailed` (deterministik koşul), `GateClosed` (onay yok/hash eşleşmiyor).
    Commit çağırana aittir; hata durumunda çağıran işlemi geri almalıdır.
    """
    obj: Any = entity
    kind = entity_kind(obj)
    machine = MACHINES[kind]
    session.flush()
    session.refresh(obj, with_for_update=True)
    mevcut = obj.durum
    if mevcut != expected_from:
        raise ConcurrentTransition(f"{kind} {obj.id}: durum '{mevcut}', beklenen '{expected_from}'")
    if not machine.allowed(mevcut, to_state):
        raise InvalidTransition(f"{kind}: '{mevcut}' → '{to_state}' izinli değil")
    guard = machine.guards.get((mevcut, to_state))
    if guard is not None and not guard.check(obj):
        raise GuardFailed(f"{kind}: {guard.aciklama}")

    h: str | None = None
    if kind in CONTENT_FIELDS:
        h = content_hash_of(obj)
    gate = machine.gates.get((mevcut, to_state))
    if gate is not None:
        if not approved_hash_matches(session, obj, gate.kararlar):
            raise GateClosed(
                f"{kind}: '{mevcut}' → '{to_state}' için güncel içerikle eşleşen insan onayı yok"
            )
        # Onayı tüketen kapılar (requirement: → generating; case/bug: → published) nesnede kayıtlı
        # onaylı hash'i de ister. `new`'e dönüş (PO etiketi geri çekildi) bu hash'i siler; böylece
        # eski bir `po_approve` kaydı failed → generating kapısını açamaz (MIMARI-SOZLESME §5/§6).
        if (
            mevcut in machine.approval_targets or to_state in machine.approval_consumers
        ) and getattr(obj, "onaylanan_hash", None) != h:
            if getattr(obj, "onaylanan_hash", None) is None:
                raise GateClosed(
                    f"{kind}: geçerli bir onay yok (onay geri çekilmiş); yeniden onay gerekir"
                )
            raise GateClosed(f"{kind}: onaydan sonra içerik değişmiş")

    with allow_state_write():
        obj.durum = to_state
        if hasattr(obj, "onaylanan_hash"):
            if to_state in machine.approval_targets:
                obj.onaylanan_hash = h
            elif to_state == machine.initial:
                obj.onaylanan_hash = None
        session.flush()

    conn = session.connection()
    nesne = f"{kind}:{obj.id}"
    kayit: dict[str, Any] = {"from": mevcut, "to": to_state}
    if h is not None:
        kayit["hash"] = h
    if sebep:
        kayit["sebep"] = sebep
    if ozet:
        kayit["ek"] = dict(ozet)
    audit_on_commit(session, actor_name(actor), f"{kind}.transition", nesne, kayit)
    olay = {"id": obj.id, "from": mevcut, "durum": to_state, "aktor": actor_name(actor)}
    publish_tx(conn, f"{kind}.state", olay)
    return entity
