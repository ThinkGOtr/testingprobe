"""Karar tablosu ve metamorfik ilişki uçları (012 ANALIZ §6). `registry` bu `router`'ı bağlar.

İzinler (auth/yetki.py): okuma `decision_table.read`, yazma ve geçişler `decision_table.edit`
(Analist), PO kararı `decision_table.approve` (PO).

| Yöntem | Yol | İzin | Gövde → yanıt |
|---|---|---|---|
| GET  | `/requirements/{id}/decision-tables?tumu=` | read | → `{tablolar, iliskiler,
son_taslak}` |
| POST | `/requirements/{id}/decision-tables/draft` | edit | → 202 `{job_id, workflow_id,
durum, mesaj, uretim_no}` |
| POST | `/requirements/{id}/decision-tables` | edit | `{icerik?}` → 201 öğe (boş tablo) |
| PUT  | `/decision-tables/{id}` | edit | `{icerik, icerik_hash}` → öğe |
| POST | `/decision-tables/{id}/submit` | edit | `{icerik_hash?}` → öğe |
| POST | `/decision-tables/{id}/withdraw` | edit | → öğe |
| POST | `/decision-tables/{id}/reopen` | edit | `{icerik_hash?, gerekce?, case_id?}` → öğe
("Tablo yanlış" yolu: `case_id` verilirse gerekçe zorunlu, 422 `gecersiz_karar`) |
| POST | `/decision-tables/{id}/approve` | approve | `{icerik_hash, gerekce?}` → öğe |
| POST | `/decision-tables/{id}/request-changes` | approve | `{icerik_hash, gerekce}` → öğe |
| POST | `/decision-tables/{id}/evaluate` | read | `{girdiler, icerik?}` → `{satir_id,
ciktilar, eksik_girdiler, hata}`; `girdiler` en çok 24 ad, ad ≤ 40, metin değer ≤ 300 karakter |
| GET  | `/decision-tables/{id}/ornekler` | read | → `{ornekler: [{girdiler, satir_id, ciktilar,
hata}], uyarilar: [{tur, mesaj, satirlar?, girdiler?}]}` (`ifade.sinir_ornekleri`) |
| POST | `/requirements/{id}/relations` | edit | `{icerik, karar_tablosu_id?}` → 201 öğe |
| PUT  | `/relations/{id}` | edit | `{icerik, icerik_hash, karar_tablosu_id?}` → öğe |
| POST | `/relations/{id}/submit` · `/withdraw` · `/reopen` | edit | tablo uçlarıyla aynı |
| POST | `/relations/{id}/approve` · `/request-changes` | approve | tablo uçlarıyla aynı |

Öğe: `{id, tur, requirement_id, sira_no, durum, icerik, icerik_hash, onaylanan_hash,
ai_generated, uretim_modu, bayat, olusturma, guncelleme, onaylayan, onay_zamani, son_karar,
son_duzenleyen, gecmis}`; ilişkide ek olarak `karar_tablosu_id` ve `tablo_engeli` (onaylı
ilişkinin bağlı tablosu onaylandığı sürümde değilse nedeni; o zaman `bayat: true`).
`son_taslak.hata` ham iş hatası değil, sınıflandırılmış metindir (`hata_kodu` ile).
`son_karar` = `{karar, gerekce, kullanici, zaman, case_id?} | null` (PO'nun son kararı;
"değişiklik iste" gerekçesi buradadır; ondan sonra gerekçeli yeniden açma varsa o).
`gecmis` = `[{karar: submit|withdraw|reopen|approve|request_changes|duzenle, gerekce,
kullanici, zaman, icerik_hash, case_id?}]` (eskiden yeniye, denetim kayıtlarından).

Hatalar `{detail, kod}`; içerik doğrulaması 422 `karar_tablosu_gecersiz` / `iliski_gecersiz` ve
ek olarak `hatalar: [metin]`. Görülen hash eskiyse 409 `onay_hash_uyusmuyor`; içerik taslakta
değilse ya da gereksinim PO onaylı değilse 409 `cakisma`; geçersiz geçiş 409 `gecersiz_gecis` /
`eszamanli_gecis`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from tp_core.auth.deps import DbSession
from tp_core.auth.yetki import izin
from tp_core.features.karar_tablosu import service
from tp_core.features.karar_tablosu.hatalar import IliskiGecersiz, KararTablosuGecersiz
from tp_core.workflow.service import Principal

router = APIRouter(tags=["karar_tablosu"])

# İzinler tek katalogdan (auth/yetki.py; 012-rol-yetki §4.3).
Analyst = Annotated[Principal, Depends(izin("decision_table.edit"))]
Po = Annotated[Principal, Depends(izin("decision_table.approve"))]
Okuyucu = Annotated[Principal, Depends(izin("decision_table.read"))]

HASH = Field(default=None, max_length=128)


class IsYaniti(BaseModel):
    job_id: uuid.UUID | None
    durum: str
    mesaj: str | None = None
    workflow_id: uuid.UUID | None = None
    uretim_no: int | None = None


class TabloOlustur(BaseModel):
    icerik: dict[str, Any] | None = None


class IcerikGuncelle(BaseModel):
    icerik: dict[str, Any]
    icerik_hash: str | None = HASH


class Gonder(BaseModel):
    icerik_hash: str | None = HASH


class YenidenAc(BaseModel):
    """Gövdesiz (analistin kendi kararı) ya da "Tablo yanlış" yolu: `{icerik_hash, gerekce,
    case_id}` (case_id verilirse gerekçe zorunlu)."""

    icerik_hash: str | None = HASH
    gerekce: str | None = Field(default=None, max_length=2000)
    case_id: uuid.UUID | None = None


class PoKarari(BaseModel):
    icerik_hash: str | None = HASH
    gerekce: str | None = Field(default=None, max_length=2000)


GIRDI_AZAMI = 24  # tablo en çok 12 girdi alır; fazlası yok sayılır ama gövde sınırlıdır
GIRDI_ADI_AZAMI = 40
GIRDI_DEGERI_AZAMI = 300

GirdiDegeri = str | int | float | bool | None


class Degerlendir(BaseModel):
    girdiler: dict[str, GirdiDegeri] = Field(default_factory=dict, max_length=GIRDI_AZAMI)
    # Düzenleyicideki kaydedilmemiş içerik ("örnekle dene"); verilmezse kayıtlı içerik.
    icerik: dict[str, Any] | None = None

    @field_validator("girdiler")
    @classmethod
    def _girdi_sinirlari(cls, girdiler: dict[str, GirdiDegeri]) -> dict[str, GirdiDegeri]:
        for ad, deger in girdiler.items():
            if len(ad) > GIRDI_ADI_AZAMI:
                raise ValueError(f"girdi adı en çok {GIRDI_ADI_AZAMI} karakter olabilir")
            if isinstance(deger, str) and len(deger) > GIRDI_DEGERI_AZAMI:
                raise ValueError(f"'{ad}' değeri en çok {GIRDI_DEGERI_AZAMI} karakter olabilir")
        return girdiler


class IliskiOlustur(BaseModel):
    icerik: dict[str, Any]
    karar_tablosu_id: uuid.UUID | None = None


class IliskiGuncelle(BaseModel):
    icerik: dict[str, Any]
    icerik_hash: str | None = HASH
    # Alan gönderilmezse bağ korunur; `null` bağı kaldırır.
    karar_tablosu_id: uuid.UUID | None = None


def _gecersiz(session: DbSession, exc: KararTablosuGecersiz | IliskiGecersiz) -> JSONResponse:
    """Doğrulama hataları liste olarak da döner (`hatalar`); işlem geri alınır."""
    session.rollback()
    return JSONResponse(
        {"detail": str(exc), "kod": exc.kod, "hatalar": exc.hatalar}, status_code=422
    )


def _oge(session: DbSession, nesne: Any) -> dict[str, Any]:
    session.flush()
    return service.serialize(session, [nesne])[0]


# ---------------------------------------------------------------------- liste ve AI taslağı


@router.get("/requirements/{requirement_id}/decision-tables")
def list_tables(
    requirement_id: uuid.UUID, session: DbSession, _u: Okuyucu, tumu: bool = False
) -> dict[str, Any]:
    return service.listele(session, requirement_id, tumu=tumu)


@router.post(
    "/requirements/{requirement_id}/decision-tables/draft",
    response_model=IsYaniti,
    status_code=202,
)
def draft_tables(requirement_id: uuid.UUID, session: DbSession, user: Analyst) -> IsYaniti:
    sonuc = service.taslak_baslat(session, requirement_id, user)
    return IsYaniti(
        job_id=sonuc["job_id"],
        workflow_id=sonuc["workflow_id"],
        durum="started",
        mesaj=(
            "Karar tablosu taslağı başlatıldı."
            if sonuc["yeni"]
            else "Bu gereksinim için süren bir taslak işi var."
        ),
    )


# ---------------------------------------------------------------------- karar tablosu


@router.post("/requirements/{requirement_id}/decision-tables", status_code=201, response_model=None)
def create_table(
    requirement_id: uuid.UUID,
    session: DbSession,
    user: Analyst,
    body: TabloOlustur | None = None,
) -> dict[str, Any] | JSONResponse:
    try:
        t = service.tablo_olustur(session, requirement_id, user, body.icerik if body else None)
    except KararTablosuGecersiz as exc:
        return _gecersiz(session, exc)
    return _oge(session, t)


@router.put("/decision-tables/{tablo_id}", response_model=None)
def update_table(
    tablo_id: uuid.UUID, body: IcerikGuncelle, session: DbSession, user: Analyst
) -> dict[str, Any] | JSONResponse:
    try:
        t = service.tablo_guncelle(session, tablo_id, user, body.icerik, body.icerik_hash)
    except KararTablosuGecersiz as exc:
        return _gecersiz(session, exc)
    return _oge(session, t)


@router.post("/decision-tables/{tablo_id}/evaluate")
def evaluate_table(
    tablo_id: uuid.UUID, body: Degerlendir, session: DbSession, _u: Okuyucu
) -> dict[str, Any]:
    return service.tablo_degerlendir(session, tablo_id, body.girdiler, body.icerik)


@router.get("/decision-tables/{tablo_id}/ornekler")
def table_examples(tablo_id: uuid.UUID, session: DbSession, _u: Okuyucu) -> dict[str, Any]:
    """Sınır örnekleri ve satır uyarıları (çakışan, hiç eşleşmeyen, gölgede kalan satırlar)."""
    return service.tablo_ornekleri(session, tablo_id)


# ---------------------------------------------------------------------- metamorfik ilişki


@router.post("/requirements/{requirement_id}/relations", status_code=201, response_model=None)
def create_relation(
    requirement_id: uuid.UUID, body: IliskiOlustur, session: DbSession, user: Analyst
) -> dict[str, Any] | JSONResponse:
    try:
        n = service.iliski_olustur(
            session, requirement_id, user, body.icerik, body.karar_tablosu_id
        )
    except IliskiGecersiz as exc:
        return _gecersiz(session, exc)
    return _oge(session, n)


@router.put("/relations/{iliski_id}", response_model=None)
def update_relation(
    iliski_id: uuid.UUID, body: IliskiGuncelle, session: DbSession, user: Analyst
) -> dict[str, Any] | JSONResponse:
    bag: Any = (
        body.karar_tablosu_id if "karar_tablosu_id" in body.model_fields_set else service.BAG_KORU
    )
    try:
        n = service.iliski_guncelle(session, iliski_id, user, body.icerik, body.icerik_hash, bag)
    except IliskiGecersiz as exc:
        return _gecersiz(session, exc)
    return _oge(session, n)


# ---------------------------------------------------------------------- durum geçişleri (iki tür)


def _gecis_uclari(onek: str, tur: str, ad: str) -> None:
    """`/<onek>/{id}/submit|withdraw|reopen|approve|request-changes` uçlarını kaydeder."""

    @router.post(f"/{onek}/{{nesne_id}}/submit", name=f"{ad}_submit", response_model=None)
    def submit(
        nesne_id: uuid.UUID, session: DbSession, user: Analyst, body: Gonder | None = None
    ) -> dict[str, Any] | JSONResponse:
        try:
            n = service.gonder(session, tur, nesne_id, user, body.icerik_hash if body else None)
        except (KararTablosuGecersiz, IliskiGecersiz) as exc:
            return _gecersiz(session, exc)
        return _oge(session, n)

    @router.post(f"/{onek}/{{nesne_id}}/withdraw", name=f"{ad}_withdraw")
    def withdraw(nesne_id: uuid.UUID, session: DbSession, user: Analyst) -> dict[str, Any]:
        return _oge(session, service.geri_cek(session, tur, nesne_id, user))

    @router.post(f"/{onek}/{{nesne_id}}/reopen", name=f"{ad}_reopen")
    def reopen(
        nesne_id: uuid.UUID, session: DbSession, user: Analyst, body: YenidenAc | None = None
    ) -> dict[str, Any]:
        b = body or YenidenAc()
        n = service.yeniden_ac(
            session, tur, nesne_id, user, b.icerik_hash, gerekce=b.gerekce, case_id=b.case_id
        )
        return _oge(session, n)

    @router.post(f"/{onek}/{{nesne_id}}/approve", name=f"{ad}_approve")
    def approve(
        nesne_id: uuid.UUID, body: PoKarari, session: DbSession, user: Po
    ) -> dict[str, Any]:
        return _oge(session, service.onayla(session, tur, nesne_id, user, body.icerik_hash))

    @router.post(f"/{onek}/{{nesne_id}}/request-changes", name=f"{ad}_request_changes")
    def request_changes(
        nesne_id: uuid.UUID, body: PoKarari, session: DbSession, user: Po
    ) -> dict[str, Any]:
        n = service.degisiklik_iste(session, tur, nesne_id, user, body.icerik_hash, body.gerekce)
        return _oge(session, n)


_gecis_uclari("decision-tables", service.TABLO, "decision_table")
_gecis_uclari("relations", service.ILISKI, "relation")
