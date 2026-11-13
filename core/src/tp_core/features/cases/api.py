"""Case uçları (MIMARI-SOZLESME §5; TEKNIK-TASARIM §9; specs/012-rol-yetki/ANALIZ.md §4–§5).

| Yöntem | Yol | İzin |
|---|---|---|
| POST | `/requirements/{id}/generate-cases` (`UretimBaslatGirdisi`?) | `case.generate` — yalnızca PO onaylı gereksinim |
| GET  | `/cases?requirement_id=` | `case.read` (developer: yalnız approved/published, geçmiş yok) |
| GET  | `/cases/{id}` | `case.read` (developer: aynı süzgeç; görünmeyen case 404) |
| POST | `/cases/{id}/viewed` | `case.decide` veya `case.approve` — görünürlüğün başında (≥ 3 sn sonra `goruldu`, 013 K13') |
| POST | `/cases/{id}/decision` (aşağıda `CaseKararGirdisi`) | karar başına: `case.decide` (accept, edit, reject, reopen) / `case.approve` (approve, send_back); yanıtta `otomatik_kod` |
| POST | `/cases/bulk-decision` (`TopluKararGirdisi`) | karar başına: `case.decide` (accept: toplu kabul) / `case.approve` (approve: toplu son onay; üstte `otomatik_kod`); 011 K20 "Seçilenleri onayla" bu uçtadır |
| POST | `/cases/{id}/assumption-verified` (`VarsayimDogrulandiGirdisi`) | `case.decide` — 011 K20; Testçinin `edit`'i (draft → ready) |
| GET  | `/requirements/{id}/case-metrics` | `case.read` — kabul oranı ve süreler (§12); developer: yalnız durum sayıları |
| GET  | `/requirements/{id}/case-summary` | `case.analysis_read` — üretim özetleri + kapsam matrisi (011 §4.4) |
| POST | `/requirements/{id}/review-complete` | `case.approve` |
| GET  | `/requirements/{id}/cases.feature[?yalniz_yayinlanan=1]` | `case.read` — Gherkin (011 F8; yalnız onaylı/yayınlanmış case) |
| GET  | `/requirements/{id}/generation-options` | `case.analysis_read` — kayıtlı seçenekler + katalog (K5) |
| POST | `/requirements/{id}/deepen` (GET: son durum, `case.analysis_read`) | `case.generate` — derinleştirme (P5/P6) |

Açık sorular (`acik_sorular.router`), P8 review (`review.router`) ve P9 denetim
(`denetim_akisi.router`) uçlarının izinleri kendi modüllerindedir.
"""  # noqa: E501

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from tp_core.auth.deps import CurrentUser, DbSession
from tp_core.auth.yetki import izin, izinli, reddet
from tp_core.features.cases import acik_sorular, denetim_akisi, gherkin, review, service, toplu
from tp_core.features.cases import deepen as deepen_modulu
from tp_core.features.cases import secenekler as secenek_modulu
from tp_core.features.otomasyon.otokod import kuyruga_al
from tp_core.workflow.service import Principal
from tp_core.workflow.states import TEST_CASE_KARAR_IZNI

router = APIRouter(tags=["cases"])
# P8 review ve P9 denetim uçları (011 §4.4, D şeridi): `review.router`, `denetim_akisi.router`.
router.include_router(review.router)
router.include_router(denetim_akisi.router)
# 011 K16 (D6): açık soruların PO'ya gönderimi ve yanıtları (`acik_sorular.router`).
router.include_router(acik_sorular.router)

Uretici = Annotated[Principal, Depends(izin("case.generate"))]
Okuyucu = Annotated[Principal, Depends(izin("case.read"))]
SonOnay = Annotated[Principal, Depends(izin("case.approve"))]
Karar = Annotated[Principal, Depends(izin("case.decide"))]
# 011 çalışma ayrıntıları (özet, seçenekler, derinleştirme durumu): developer hariç.
Analiz = Annotated[Principal, Depends(izin("case.analysis_read"))]


class IsYaniti(BaseModel):
    job_id: uuid.UUID | None
    durum: str
    mesaj: str | None = None
    workflow_id: uuid.UUID | None = None
    uretim_no: int | None = None
    # 011 K1: üretim kipi ve aşama (iki turda önce "model", onaylı modelden sonra "case").
    kip: Literal["iki_tur", "tek_tur"] | None = None
    asama: Literal["model", "case"] | None = None


class TopluKararOgesi(BaseModel):
    case_id: uuid.UUID
    icerik_hash: str = Field(min_length=1, max_length=200)


class TopluKararGirdisi(BaseModel):
    # 012: Testçi toplu kabul (draft → ready) | Analist toplu son onay (ready → approved).
    karar: Literal["accept", "approve"]
    ogeler: list[TopluKararOgesi] = Field(min_length=1, max_length=service.TOPLU_KARAR_MAX)


class CaseKararGirdisi(BaseModel):
    # Testçi: accept | edit | reject | reopen · Analist (son onay): approve | send_back.
    karar: Literal["accept", "edit", "reject", "reopen", "approve", "send_back"]
    # Kullanıcının ekranda gördüğü içeriğin hash'i (edit'te düzeltme ÖNCESİ). Portalda zorunlu.
    icerik_hash: str | None = None
    icerik: dict[str, Any] | None = None
    ret_nedeni: (
        Literal[
            "hallucinated_step",
            "missing_ac",
            "wrong_test_data",
            "out_of_scope",
            "duplicate",
            "wrong_element",
        ]
        | None
    ) = None
    # `send_back`'te zorunlu; `reject`/`reopen`'da isteğe bağlı not.
    gerekce: str | None = Field(default=None, max_length=2000)
    # §12 "beklenen sonuç anlamca değişmedi" insan yargısı (verilmezse metin karşılaştırması).
    beklenen_anlam_degisti: bool | None = None


class UretimBaslatGirdisi(BaseModel):
    """`POST generate-cases` gövdesi (isteğe bağlı; gövdesiz çağrı geriye uyumlu).

    `kip` (011 F3, K20): `iki_tur` (önce test tasarım modeli, analist onayı, sonra yalnız onaylı
    modelden case) | `tek_tur` (hızlı; doğrudan case). Açıkça verilen kip gereksinimin üretim
    seçeneklerinde saklanır. Kip verilmezse kayıtlı kip; kayıt yoksa gövdeli çağrıda `iki_tur`,
    gövdesiz çağrıda `tek_tur` (geriye uyum: prova, IDE/MCP).

    Diğer alanlar üretim seçenekleridir (011 K5; anlamsal doğrulama `secenekler.dogrula`, 422).
    Seçenek alanlarından hiçbiri verilmezse gereksinimde kayıtlı son seçenekler kullanılır.
    """

    model_config = ConfigDict(extra="forbid")

    kip: Literal["iki_tur", "tek_tur"] | None = None

    platformlar: list[str] | None = None
    test_seviyesi: str | None = None
    benimsenen_standartlar: list[str] | None = None
    kapsam_disi: str | None = None
    roller: str | None = None
    ek_bilgi: dict[str, str | bool] | None = None

    def secenekler(self) -> dict[str, Any] | None:
        alanlar = {
            k: v
            for k in secenek_modulu.UretimSecenekleri.model_fields
            if k != "kip" and (v := getattr(self, k)) is not None
        }
        return alanlar or None


@router.post(
    "/requirements/{requirement_id}/generate-cases", response_model=IsYaniti, status_code=202
)
def generate_cases(
    requirement_id: uuid.UUID,
    session: DbSession,
    user: Uretici,
    body: UretimBaslatGirdisi | None = None,
) -> IsYaniti:
    sonuc = service.start_generation(
        session,
        requirement_id,
        user,
        kip=body.kip if body is not None else None,
        secenekler=body.secenekler() if body else None,
        varsayilan_kip="iki_tur" if body is not None else "tek_tur",
    )
    kip = sonuc["kip"]
    model_asamasi = sonuc.get("asama") == "model"
    return IsYaniti(
        job_id=sonuc["job_id"],
        workflow_id=sonuc["workflow_id"],
        uretim_no=sonuc["uretim_no"],
        durum="started",
        mesaj=(
            "Test tasarım modeli üretimi başlatıldı (iki tur)."
            if model_asamasi
            else "Onaylı tasarım modelinden case üretimi başlatıldı."
            if kip == "iki_tur"
            else "Case üretimi başlatıldı."
        ),
        kip=kip,
        asama=sonuc.get("asama", "case"),
    )


@router.get("/cases")
def list_cases(
    session: DbSession, user: Okuyucu, requirement_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    return service.list_cases(session, requirement_id, user)


@router.get("/cases/{case_id}")
def get_case(case_id: uuid.UUID, session: DbSession, user: Okuyucu) -> dict[str, Any]:
    return service.get_case_view(session, case_id, user)


@router.post("/cases/bulk-decision")
def bulk_decision(
    body: TopluKararGirdisi, request: Request, session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    # 012: toplu kabul (Testçi, `case.decide`) ya da toplu son onay (Analist, `case.approve`);
    # izin tekli kararla aynı tablodan. Her öğe tekli `decide`'ın tüm kapılarından geçer.
    izin_adi = TEST_CASE_KARAR_IZNI[body.karar]
    if not izinli(user.rol, izin_adi):
        raise reddet(session, user, izin_adi, "rol", request.url.path, karar=body.karar)
    return service.bulk_decide(
        session, [(o.case_id, o.icerik_hash) for o in body.ogeler], user, karar=body.karar
    )


@router.post("/cases/{case_id}/viewed")
def mark_viewed(
    case_id: uuid.UUID, request: Request, session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    # Testçi kararı ya da Analist son onayı için review süresinin başlangıcı.
    if not (izinli(user.rol, "case.decide") or izinli(user.rol, "case.approve")):
        raise reddet(session, user, "case.decide", "rol", request.url.path)
    return service.mark_viewed(session, case_id, user)


@router.post("/cases/{case_id}/decision")
def decide(
    case_id: uuid.UUID,
    body: CaseKararGirdisi,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    # İzin karara göre: Testçi kararları `case.decide`, son onay `case.approve` (ANALIZ §4.1).
    izin_adi = TEST_CASE_KARAR_IZNI[body.karar]
    if not izinli(user.rol, izin_adi):
        raise reddet(session, user, izin_adi, "rol", request.url.path, karar=body.karar)
    tc = service.decide(
        session,
        case_id,
        user,
        karar=body.karar,
        icerik_hash=body.icerik_hash,
        icerik=body.icerik,
        ret_nedeni=body.ret_nedeni,
        gerekce=body.gerekce,
        beklenen_anlam_degisti=body.beklenen_anlam_degisti,
    )
    session.flush()
    # 013 §3.2 (K4): son onay (Analist `approve`; case approved olur) otomatik kod üretimini
    # kuyruğa alır; üretimin reddi/hatası onayı geri almaz. Testçi kabulü kod üretmez (012).
    otomatik_kod = kuyruga_al(session, tc, user) if body.karar == "approve" else None
    return {**service.serialize_cases(session, [tc], user)[0], "otomatik_kod": otomatik_kod}


class VarsayimDogrulandiGirdisi(BaseModel):
    """`POST /cases/{id}/assumption-verified` ("Varsayım doğrulandı", 011 K20)."""

    model_config = ConfigDict(extra="forbid")

    icerik_hash: str = Field(min_length=1)
    varsayim_id: str | list[str]
    gerekce: str | None = Field(default=None, max_length=2000)


@router.post("/cases/{case_id}/assumption-verified")
def assumption_verified(
    case_id: uuid.UUID, body: VarsayimDogrulandiGirdisi, session: DbSession, user: Karar
) -> dict[str, Any]:
    # 012: varsayım doğrulaması Testçinin `edit` kararıdır (draft → ready; son onay Analistte).
    tc = toplu.assumption_verified(
        session,
        case_id,
        user,
        icerik_hash=body.icerik_hash,
        varsayim_id=body.varsayim_id,
        gerekce=body.gerekce,
    )
    session.flush()
    return service.serialize_cases(session, [tc], user)[0]


@router.get("/requirements/{requirement_id}/case-metrics")
def case_metrics(requirement_id: uuid.UUID, session: DbSession, user: Okuyucu) -> dict[str, Any]:
    if service.kisitli_gorunum(user):
        return service.requirement_metrics_kisitli(session, requirement_id)
    return service.requirement_metrics(session, requirement_id)


@router.get("/requirements/{requirement_id}/case-summary")
def case_summary(requirement_id: uuid.UUID, session: DbSession, _user: Analiz) -> dict[str, Any]:
    return service.case_summary(session, requirement_id)


@router.post("/requirements/{requirement_id}/review-complete")
def review_complete(requirement_id: uuid.UUID, session: DbSession, user: SonOnay) -> dict[str, Any]:
    return service.review_complete(session, requirement_id, user)


@router.get("/requirements/{requirement_id}/cases.feature", response_class=PlainTextResponse)
def cases_feature(
    requirement_id: uuid.UUID,
    session: DbSession,
    _user: Okuyucu,
    yalniz_yayinlanan: bool = False,
) -> PlainTextResponse:
    """Onaylı ve hazır güncel case'lerin Türkçe Gherkin'i (deterministik; `gherkin.py`).

    Uygun case yoksa 404 (boş dosya indirilmez); gereksinim PO onayı dışındaysa 409.
    """
    cikti = gherkin.requirement_feature(
        session, requirement_id, yalniz_yayinlanan=yalniz_yayinlanan
    )
    return PlainTextResponse(
        cikti.metin,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{cikti.dosya_adi}"',
            "X-TP-Case-Sayisi": str(cikti.case_sayisi),
            "X-TP-Senaryo-Sayisi": str(cikti.senaryo_sayisi),
            "X-TP-Taslak-Sayisi": str(cikti.taslak_sayisi),
        },
    )


@router.get("/requirements/{requirement_id}/generation-options")
def generation_options(
    requirement_id: uuid.UUID, session: DbSession, _user: Analiz
) -> dict[str, Any]:
    """Üretim formu: kayıtlı son seçenekler (yoksa null), varsayılan ve katalog (011 K5)."""
    req = service.get_requirement(session, requirement_id)
    return {
        "secenekler": secenek_modulu.kayitli(req.uretim_secenekleri),
        "varsayilan": secenek_modulu.varsayilan(),
        **secenek_modulu.katalog(),
    }


class DerinlestirmeGirdisi(BaseModel):
    """`POST /requirements/{id}/deepen` (011 P5/P6, K7)."""

    model_config = ConfigDict(extra="forbid")

    tur: Literal["negatif", "teknik"]
    teknik: Literal["EP", "BVA", "DT", "ST", "PW", "UC", "EG"] | None = None


@router.post("/requirements/{requirement_id}/deepen", response_model=IsYaniti, status_code=202)
def deepen(
    requirement_id: uuid.UUID, body: DerinlestirmeGirdisi, session: DbSession, user: Uretici
) -> IsYaniti:
    sonuc = deepen_modulu.start_deepening(
        session, requirement_id, user, tur=body.tur, teknik=body.teknik
    )
    return IsYaniti(
        job_id=sonuc["job_id"],
        workflow_id=sonuc["workflow_id"],
        uretim_no=sonuc["uretim_no"],
        durum="started",
        mesaj="Derinleştirme başlatıldı; yeni taslaklar mevcut sete eklenecek.",
    )


@router.get("/requirements/{requirement_id}/deepen")
def deepen_status(requirement_id: uuid.UUID, session: DbSession, _user: Analiz) -> dict[str, Any]:
    return deepen_modulu.deepening_status(session, requirement_id)
