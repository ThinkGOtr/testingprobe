"""Kod üretimi uçları (MIMARI-SOZLESME §5; TEKNIK-TASARIM §8.4, §8.10).

| Yöntem | Yol | Rol |
|---|---|---|
| POST | `/code/generate` `{case_ids[], platform?, dil?}` | `code.generate` — CasesToCode (202) |
| GET  | `/code/languages?platform=` | `code.generate` — algılanan dil + seçenekler (K-T8) |
| POST | `/code/ci-setup` `{platform, dil, onizle?, parametreler}` | `code.ci_setup` (014) |
| GET  | `/scripts` · `/scripts/{id}` | `code.read` — üretilen test, PR, adımlar, yerel kontrol |
| GET  | `/scripts/{id}/screenshots/{n}` | `code.read` — ajan adımının ekran görüntüsü (PNG) |
| POST | `/scripts/{id}/break-verify` | `code.break_verify` — kırarak doğrula (202) |
| POST | `/prs/{number}/merge?depo=` `{icerik_hash, head_sha, onay_notu?}` | `code.merge` |
| POST | `/prs/{number}/update-branch?depo=` | `code.review` — dalı main ile güncelle (202) |
| POST | `/prs/{number}/review?depo=` `{karar, ret_nedeni, icerik_hash, head_sha, not?}` | review |

Platform depoları (0046): PR numarası yalnız depo içinde tekildir. `?depo=` PR'ın deposudur
(script/PR yanıtlarındaki `depo` alanı: `''` = projenin varsayılan deposu, ayrı platform
deposunda `sahip/ad`); eksik ya da boş → varsayılan depo (bugünkü davranış). Biçim dışı değer 422.

Merge, forge yazma kimliği yalnızca core-worker'da olduğu için işe (`codegen.merge`) gider; uç en
çok `MERGE_BEKLEME_S` bekler: bitti → 200 `PullRequest`, reddedildi → 409, sürüyor → 202. Aynı
head için ikinci istek aynı işi bekler (idempotent). Kırarak doğrulama `passed` değilse `onay_notu`
(açık insan kabulü) zorunludur; yoksa 409. `head_sha` yoksa 422; PR zaten merge edildiyse 409
"PR zaten merge edildi". Dal main'in gerisindeyse (başka PR merge edildi) merge onay kaydı
yazılmadan 409 döner; dal otomatik güncellenir (ya da `update-branch`).

Yetki (012): her uç `izin(...)` ile korunur (`tp_core/auth/yetki.py`). `GET /code/languages`
her çağrıda forge'u okur (GitHub hız sınırı, K-T8): yalnız üretimi başlatan role (`code.generate`)
açıktır; diğerlerinde portal 403'ü "seçici yok" sayar. GitHub App kipinde forge yalnız
core-worker'da kurulabildiği için algılama `codegen.dil_algila` işine gider; uç sonucu en çok
`service.DIL_ALGILA_BEKLEME_S` bekler (sonuç 2 dk'lık dilimde paylaşılır).

Kurulum PR'ı (`/code/ci-setup`, 014): Android Kotlin / iOS Swift müşteri CI hattının tek seferlik
kurulum PR'ı (iş akışı + iskelet) projenin forge'u (GitHub App kurulumu) üzerinden açılır. Forge
yazma kimliği worker'da olduğundan uç `codegen.kurulum_pr` işini kuyruğa alır ve en çok
`kurulum_pr.KURULUM_PR_BEKLEME_S` bekler: bitti → 200 (`durum`: acildi | mevcut | gereksiz |
onizleme), sürüyor → 202, iş düştü → 409 (`kod: kurulum_pr_basarisiz`), geçersiz parametre → 422
(`kod: kurulum_parametre`, `hatalar[]`). Kurulum dalında açık PR varsa yenisi açılmaz (`mevcut`).

Review (`karar` ∈ {degisiklik_iste, reddet}, `ret_nedeni` sabit taksonomiden) script'i kapatır ve
`insan_review_sonucu`'nu yazar (Constitution X); PR worker'da kapatılır.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from tp_core.api.errors import KodluHata
from tp_core.auth.deps import DbSession
from tp_core.auth.yetki import izin, izinlerden_biri
from tp_core.db import get_engine
from tp_core.features.codegen import depo as depolar
from tp_core.features.codegen import kurulum_pr, service, views
from tp_core.integrations.toolchain_blogu import ortam_gerekli
from tp_core.models import session_scope
from tp_core.workflow.service import Principal

router = APIRouter(tags=["codegen"])


def _depo_param(
    depo: Annotated[str, Query(max_length=201, description="PR'ın deposu ('' = varsayılan)")] = "",
) -> str:
    """`?depo=` → normal depo kimliği (`''` | `sahip/ad`); biçim dışıysa 422."""
    d = depolar.normalize(depo)
    if not depolar.gecerli_mi(d):
        raise HTTPException(422, "depo 'sahip/ad' biçiminde olmalı (boş = varsayılan depo)")
    return d


Depo = Annotated[str, Depends(_depo_param)]

Uretir = Annotated[Principal, Depends(izin("code.generate"))]
KiraraDogrular = Annotated[Principal, Depends(izin("code.break_verify"))]
Inceler = Annotated[Principal, Depends(izin("code.review"))]
MergeEder = Annotated[Principal, Depends(izin("code.merge"))]
KodOkur = Annotated[Principal, Depends(izin("code.read"))]
CiKurar = Annotated[Principal, Depends(izin("code.ci_setup"))]
# Ekran testi 2 TP-4: dil seçenekleri (kurulum özeti dahil) kurulum PR'ını açabilen role de açık;
# Sistem Yöneticisi `code.ci_setup`'a sahip ama `code.generate`'e değil. Yazma yok (salt okuma).
DilOkur = Annotated[Principal, Depends(izinlerden_biri("code.generate", "code.ci_setup"))]
MERGE_BEKLEME_S = 20.0  # portal nginx /api/ zaman aşımı 30 sn


class KodUretGirdisi(BaseModel):
    case_ids: list[uuid.UUID] = Field(min_length=1, max_length=service.MAX_CASE)
    # 009 §2.1: üretilecek testin platformu; yoksa web (geriye uyum). Bilinmeyen değer 422.
    platform: Literal["web", "android", "ios", "windows"] = "web"
    # 011 §2.3: üretim dili; yoksa hedef repodan algılanır. Geçersiz (platform, dil) çifti 422.
    dil: Literal["ts", "java", "csharp", "python", "kotlin", "swift"] | None = None


class KurulumParametreGirdisi(BaseModel):
    """Kurulum şablonu parametreleri (hepsi isteğe bağlı; boş → varsayılan). Biçim kontrolü
    `musteri_ci.parametre_hatalari`'dadır (YAML/kabuk enjeksiyonu yok)."""

    model_config = {"extra": "forbid"}

    varsayilan_dal: str | None = Field(default=None, max_length=100)
    uygulama_koku: str | None = Field(default=None, max_length=200)
    hazirlik_betigi: str | None = Field(default=None, max_length=200)
    node_surumu: str | None = Field(default=None, max_length=10)
    izlenen_kok: str | None = Field(default=None, max_length=200)
    # Android
    gradle_modulu: str | None = Field(default=None, max_length=64)
    test_paketi: str | None = Field(default=None, max_length=200)
    emulator_api: int | None = Field(default=None, ge=1, le=99)
    # iOS
    xcode_proje: str | None = Field(default=None, max_length=200)
    sema: str | None = Field(default=None, max_length=100)
    ui_test_hedefi: str | None = Field(default=None, max_length=100)
    runs_on: str | None = Field(default=None, max_length=64)
    simulator: str | None = Field(default=None, max_length=64)
    yapilandirma: str | None = Field(default=None, max_length=100)


class KurulumGirdisi(BaseModel):
    platform: Literal["android", "ios"]
    dil: Literal["kotlin", "swift"]
    # true: forge'a yazmadan plan (eklenecek dosyalar, eksikler) + açık kurulum PR'ı.
    onizle: bool = False
    parametreler: KurulumParametreGirdisi = Field(default_factory=KurulumParametreGirdisi)


class MergeGirdisi(BaseModel):
    icerik_hash: str | None = Field(default=None, max_length=128)
    head_sha: str | None = Field(default=None, max_length=64)
    # Kırarak doğrulama `passed` değilse (zayıf / tamamlanamadı / yapılmadı) zorunlu insan kabulü.
    onay_notu: str | None = Field(default=None, max_length=500)


class ReviewGirdisi(BaseModel):
    karar: str = Field(max_length=32)
    ret_nedeni: str = Field(max_length=64)
    icerik_hash: str | None = Field(default=None, max_length=128)
    head_sha: str | None = Field(default=None, max_length=64)
    not_: str | None = Field(default=None, max_length=500, alias="not")


@router.post("/code/generate", status_code=202)
def generate(body: KodUretGirdisi, session: DbSession, user: Uretir) -> dict[str, Any]:
    if body.platform == "web":  # web doğrulama ajanı projenin BASE_URL'ine karşı koşar
        ortam_gerekli()
    return service.start_generation(session, body.case_ids, user, body.platform, body.dil)


@router.get("/code/languages")
def languages(
    _user: DilOkur,
    platform: Literal["web", "android", "ios", "windows"] = "web",
) -> dict[str, Any]:
    """Algılanan dil, depodaki elle yazılmış test sayıları ve platformun dil seçenekleri."""
    return service.dil_secenekleri(platform)


@router.post("/code/ci-setup")
async def ci_setup(body: KurulumGirdisi, user: CiKurar, response: Response) -> dict[str, Any]:
    """Müşteri CI kurulum PR'ı (014): önizleme ya da insan onaylı PR (onaylayan = istek sahibi)."""
    from tp_core.features.publish.service import await_job

    def kuyruga_al() -> uuid.UUID:
        with session_scope() as s:
            return kurulum_pr.istek(
                s,
                user,
                body.platform,
                body.dil,
                body.parametreler.model_dump(exclude_none=True),
                onizle=body.onizle,
            )

    try:
        job_id = await run_in_threadpool(kuyruga_al)
    except kurulum_pr.KurulumIstekHatasi as exc:
        raise KodluHata(422, "kurulum_parametre", str(exc), ek={"hatalar": exc.hatalar}) from exc
    durum, sonuc, hata = await await_job(get_engine(), job_id, kurulum_pr.KURULUM_PR_BEKLEME_S)
    if durum in ("failed", "cancelled"):
        raise KodluHata(409, "kurulum_pr_basarisiz", hata or "Kurulum PR'ı açılamadı")
    if durum != "done" or not isinstance(sonuc, dict):
        response.status_code = 202
        return {"durum": "suruyor", "job_id": str(job_id), "mesaj": kurulum_pr.SURUYOR}
    return sonuc


@router.get("/scripts")
def list_scripts(session: DbSession, _user: KodOkur, response: Response) -> list[dict[str, Any]]:
    """En yeni 200 script (düz dizi). `X-Daha-Fazla: 1` → daha eski kayıtlar var (liste kesildi),
    `0` → liste tam (MİM-D5)."""
    liste, daha_fazla = views.list_scripts_sinirli(session)
    response.headers[views.DAHA_FAZLA_BASLIGI] = "1" if daha_fazla else "0"
    return liste


@router.get("/scripts/{script_id}")
def get_script(script_id: uuid.UUID, session: DbSession, _user: KodOkur) -> dict[str, Any]:
    pair = views.get_pair(session, script_id)
    if pair is None:
        raise HTTPException(404, "Script bulunamadı")
    return views.detail(session, *pair)


@router.get("/scripts/{script_id}/screenshots/{sira}")
def screenshot(script_id: uuid.UUID, sira: int, session: DbSession, _user: KodOkur) -> FileResponse:
    if sira < 1 or sira > 10_000:
        raise HTTPException(404, "Ekran görüntüsü bulunamadı")
    yol = views.screenshot_path(session, script_id, sira)
    if yol is None:
        raise HTTPException(404, "Ekran görüntüsü bulunamadı")
    return FileResponse(
        yol,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/scripts/{script_id}/break-verify", status_code=202)
def break_verify(script_id: uuid.UUID, session: DbSession, user: KiraraDogrular) -> dict[str, Any]:
    return service.start_break_verify(session, script_id, user)


@router.post("/prs/{number}/update-branch", status_code=202)
def update_branch(number: int, session: DbSession, user: Inceler, depo: Depo) -> dict[str, Any]:
    return service.request_update_branch(session, number, user, depo=depo)


@router.post("/prs/{number}/review")
def review(
    number: int, body: ReviewGirdisi, session: DbSession, user: Inceler, depo: Depo
) -> dict[str, Any]:
    return service.review_pr(
        session,
        number,
        user,
        body.karar,
        body.ret_nedeni,
        body.icerik_hash,
        body.head_sha,
        body.not_,
        depo=depo,
    )


@router.post("/prs/{number}/merge")
async def merge(
    number: int, body: MergeGirdisi, user: MergeEder, response: Response, depo: Depo
) -> dict[str, Any]:
    from tp_core.features.publish.service import await_job
    from tp_core.features.repair import service as repair_service
    from tp_core.features.repair import views as repair_views

    def kuyruga_al() -> uuid.UUID:
        with session_scope() as s:
            # Faz 4: locator onarım PR'ları (`tp/repair-*`) repair şeridinin merge yoluna gider.
            if repair_service.repair_script_for_pr(s, number, depo=depo) is not None:
                return repair_service.request_merge(
                    s, number, user, body.icerik_hash, body.head_sha, depo=depo
                )
            return service.request_merge(
                s, number, user, body.icerik_hash, body.head_sha, body.onay_notu, depo=depo
            )

    job_id = await run_in_threadpool(kuyruga_al)
    durum, _sonuc, hata = await await_job(get_engine(), job_id, MERGE_BEKLEME_S)
    if durum in ("failed", "cancelled"):
        raise HTTPException(409, hata or "Merge reddedildi")

    def pr() -> dict[str, Any] | None:
        with session_scope() as s:
            onarim_pr = repair_views.pr_response(s, number, depo=depo)
            if onarim_pr is not None:
                return onarim_pr
            sc = service.script_for_pr(s, number, depo=depo)
            return views.pr_response(s, number, [sc])

    yanit = await run_in_threadpool(pr) or {"number": number, **views.depo_alanlari(depo)}
    if durum != "done":
        response.status_code = 202
        return {**yanit, "job_id": str(job_id), "is_durumu": durum}
    return {**yanit, "job_id": str(job_id)}
