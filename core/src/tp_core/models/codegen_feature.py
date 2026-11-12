"""Kod üretimi (CasesToCode, TEKNIK-TASARIM §8.4) şeridinin ek tabloları — migrasyon 0009.

Platform tabloları (`script`, `script_test_case`, `step_mapping`, `pull_request`) olduğu gibi
kullanılır; özelliğin ihtiyaç duyduğu ek kayıtlar ayrı tablolardadır:

- `script_codegen` (script ile 1:1): hangi onaylı case'in hangi onaylı hash'inden üretildiği,
  sembol tablosunun alındığı `main` commit'i, ajan çağrılarının modu/bundle hash'i, ham eşleme
  çıktısı (ilk tur ayrıca saklanır: düzeltme turu `expects`'i değiştiremez), deterministik
  kontrol sonuçları, insana düşme nedeni (`engel_turu`), son yerel kontrol özeti, PR adresi ve
  PR'a sabitlenen denetim zinciri başı.
- `script_adim`: ajanın her tarayıcı eylemi (araç, insan için tek satırlık özet, temizlenmiş ham
  çıktı, izinli mi, araç hata döndürdü mü) ve model döngüsü dışında alınan ekran görüntüsünün
  artefakt yolu. Portal canlı görünümü buradan okur.
- `script_kontrol`: yerel kontrol ve "kırarak doğrula" koşularının zaman çizelgesi (commit,
  kırılma bayrağı, deterministik sınıf, başarısız testlerin kısa özeti). `run_id` koşunun
  `run` tablosundaki UUID'sidir (toolchain koşu kimliği `ozet.toolchain_run_id`'de).

`script.durum` platform durum makinesindedir (`blocked` = insana düştü). "Defect adayı" ayrı bir
durum değildir: `script.durum = 'blocked'` + `script_codegen.engel_turu = 'defect_candidate'`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, UniqueConstraint, false, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models.base import Base, guncelleme_col, in_check, olusturma_col, uuid_pk
from tp_core.models.requirements import EMPTY_LIST, EMPTY_OBJ

# İnsana düşme nedenleri (script `blocked` / `failed` iken).
ENGEL_TURU = frozenset(
    {
        "missing_method",  # page object'te eksik metot (model `missing_methods` bildirdi)
        "unknown_method",  # eşlemedeki metot sembol tablosunda yok / imza uymuyor
        "unsourced_value",  # beklenen/girdi değeri onaylı case metninde yok
        "unverified_step",  # adım uygulamada doğrulanmadı (verified=false) ya da eşlenmedi
        "replay_miss",  # REPLAY-MISS: bu case için kayıtlı doğrulama yok
        "agent_error",  # ajan/model geçidi hatası, bütçe
        "defect_candidate",  # yerel kontrolde assertion hatası (onarım yok, insana)
        "locator",  # düzeltme turundan sonra da locator/eşleme hatası
        "static",  # tsc / eslint / AST koruması
        "environment",  # sağlık kontrolü / ağ / runner hatası
        "check_unknown",  # sınıflandırılamayan kırmızı
        "flaky",  # tekrarların bir kısmı geçti, bir kısmı kırmızı (defect adayı değil)
        "human_rejected",  # mühendis PR'ı reddetti / değişiklik istedi (POST /prs/{n}/review)
        "test_verisi",  # 013 K19: test verisi atfı çözülemedi (sır tanımsız / katalogda yok)
        "case_changed",  # case onaydan sonra değişti
    }
)
BREAK_DURUM = frozenset({"not_started", "running", "passed", "weak", "failed"})
# 013: üretimi başlatan (portal/MCP düğmesi = elle, case onayı = otomatik)
TETIK = frozenset({"elle", "otomatik"})
KONTROL_TUR = frozenset(
    {"local_check", "remap_check", "break_baseline", "break_red", "break_green"}
)
KONTROL_SONUC = frozenset({"success", "failure", "error", "skipped"})
# `kirma_beklenen_kirmizi`: BREAK_CAMPAIGN koşusunda assertion kırmızısı — beklenen kanıt, defect
# adayı değil (Faz 4 triage bunu hata olarak okumamalı).
KONTROL_SINIF = frozenset(
    {
        "gecti",
        "defect_adayi",
        "locator",
        "derleme",
        "ortam",
        "bilinmiyor",
        "kararsiz",
        "kirma_beklenen_kirmizi",
    }
)


class ScriptCodegen(Base):
    """Üretilen testin kaynağı ve doğrulama/kontrol özeti (script ile 1:1)."""

    __tablename__ = "script_codegen"
    __table_args__ = (
        in_check("engel_turu", ENGEL_TURU, "script_codegen_engel_ck", True),
        in_check("break_durum", BREAK_DURUM, "script_codegen_break_ck"),
        in_check("tetik", TETIK, "script_codegen_tetik_ck"),
        Index("script_codegen_case_ix", "test_case_id"),
    )

    script_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("script.id", ondelete="CASCADE"), primary_key=True
    )
    test_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_case.id", ondelete="CASCADE"))
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE")
    )
    # Üretimin dayandığı onaylı case içerik hash'i (case.onaylanan_hash o andaki değer).
    case_hash: Mapped[str]
    story_key: Mapped[str | None]
    test_key: Mapped[str | None]  # yayınlanmış Jira Test issue anahtarı (varsa)
    sira_no: Mapped[int] = mapped_column(Integer)
    baslik: Mapped[str] = mapped_column(server_default="", default="")
    workflow_id: Mapped[uuid.UUID | None]
    job_id: Mapped[uuid.UUID | None]
    symbols_sha: Mapped[str | None]  # sembol tablosunun alındığı main commit'i
    uretim_modu: Mapped[str | None]
    ai_call_ids: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    bundle_hash: Mapped[str | None]
    sablon_hash: Mapped[str | None]
    # 011 §2.2: yalnız doğrulanmamış dillerde (csharp | python) render edilen kaynak. Forge'a
    # commit edilmez; portal buradan gösterir/indirir.
    kaynak_kod: Mapped[str | None]
    ilk_eslesme: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    eslesme: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    dogrulama: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    engel_turu: Mapped[str | None]
    engel_nedeni: Mapped[str | None]
    yerel_kontrol: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    duzeltme_turu: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    pr_url: Mapped[str | None]
    denetim_hash: Mapped[str | None]
    # PR dalının main'e göre durumu: {"geride": bool, "main": sha, "neden": str,
    # "guncelleme": "queued|done|failed", "job_id": …, "onceki_head": …}. Başka bir PR merge
    # edildiğinde (ya da forge merge'i "dal güncel değil" diye reddettiğinde) `geride=true` olur;
    # `codegen.update_branch` işi dalı günceller (yeni head → PR CI, yeni onay, yeni kırma kanıtı).
    dal: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    break_durum: Mapped[str] = mapped_column(server_default="not_started", default="not_started")
    # 013 §9/§10: üretimde çözülen test verisi anahtarlarının tuzlu değer özetleri
    # ({anahtar: "h1:<HMAC-SHA256[:16]>"}; sürüm DEĞİL). Yalnız DEĞER değişince (açıklama/grup/
    # sürüm değil) portal "veri değişti" uyarısı gösterir (testveri.service.degisen_anahtarlar).
    veri_izi: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    tetik: Mapped[str] = mapped_column(server_default="elle", default="elle")
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class ScriptAdim(Base):
    """Ajanın tek tarayıcı eylemi + model dışı ekran görüntüsü (canlı görünüm)."""

    __tablename__ = "script_adim"
    __table_args__ = (UniqueConstraint("script_id", "sira", name="script_adim_sira_uq"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    script_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("script.id", ondelete="CASCADE"))
    sira: Mapped[int] = mapped_column(Integer)
    tur: Mapped[int] = mapped_column(Integer, server_default="1", default=1)  # eşleme turu
    arac: Mapped[str]
    arguman: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJ, default=dict)
    ozet: Mapped[str] = mapped_column(server_default="", default="")  # insan için tek satır
    ham: Mapped[str] = mapped_column(server_default="", default="")  # temizlenmiş araç çıktısı
    izinli: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    hata: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    ekran_goruntusu: Mapped[str | None]  # TP_ARTIFACTS_PATH'e göreli yol
    zaman: Mapped[datetime] = olusturma_col()


class ScriptKontrol(Base):
    """Yerel kontrol / kırarak doğrula koşusu (zaman çizelgesi)."""

    __tablename__ = "script_kontrol"
    __table_args__ = (
        in_check("tur", KONTROL_TUR, "script_kontrol_tur_ck"),
        in_check("sonuc", KONTROL_SONUC, "script_kontrol_sonuc_ck"),
        in_check("sinif", KONTROL_SINIF, "script_kontrol_sinif_ck", True),
        Index("script_kontrol_script_ix", "script_id", "zaman"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    script_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("script.id", ondelete="CASCADE"))
    tur: Mapped[str]
    sha: Mapped[str]
    kirma: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    run_id: Mapped[str | None]
    sonuc: Mapped[str]
    sinif: Mapped[str | None]
    ozet: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJ, default=dict)
    sure_ms: Mapped[int | None] = mapped_column(Integer)
    zaman: Mapped[datetime] = olusturma_col()
