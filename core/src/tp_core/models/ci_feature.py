"""CI şeridinin (Faz 3: yerel CI, sonuçlar, Kontrol Kulesi) ek tabloları — migrasyon 0010.

Platform tablolarına (`run`, `test_result`) kolon eklemeden, şeridin ihtiyaç duyduğu kayıtlar
ayrı tablolardadır:

- `ci_tetik`: her CI tetiği (PR, push, gece, deploy) için tek satır. `anahtar` UNIQUE'tir: gece
  zamanlayıcısı aynı gün için ikinci kez tetiklese (iş yeniden denemesi, iki worker) yeni koşu
  açılmaz (`nightly:2026-11-01`). GitHub kipinde `repository_dispatch` / `workflow_dispatch`
  isteğinin kaydı (`dis_istek`) burada tutulur; koşu satırı GitHub'dan sonuç alınınca dolar.
- `test_result_ek`: JSON raporundan (Playwright) test başına ek bilgi: erişilebilirlik (axe)
  ihlal sayıları ve sayfa dökümü, koşu dizinine göre göreli ek dosya yolları (trace, ekran
  görüntüsü), deneme sonuçları. Kontrol Kulesi'nin a11y sayıları yalnızca bu satırlardan türetilir.
- `run_aria` (0016): GitHub kipinde koşunun `test-local-results` artefaktındaki `<sayfa>.aria.yml`
  kopyaları (yerel koşu dizini yok); locator onarımının son yeşil aria kanıtı.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models.base import Base, in_check, olusturma_col, uuid_pk
from tp_core.models.delivery import TestResult
from tp_core.models.requirements import EMPTY_LIST, EMPTY_OBJ

CI_TETIK = frozenset({"pr", "push", "nightly", "deploy"})
CI_KAYNAK = frozenset({"local", "github"})


class CiTetik(Base):
    """Bir CI tetiği (çift tetiklemeye karşı benzersiz anahtar)."""

    __tablename__ = "ci_tetik"
    __table_args__ = (
        in_check("tetik", CI_TETIK, "ci_tetik_tetik_ck"),
        in_check("kaynak", CI_KAYNAK, "ci_tetik_kaynak_ck"),
        Index("ci_tetik_run_ix", "run_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    anahtar: Mapped[str] = mapped_column(unique=True)
    tetik: Mapped[str]
    kaynak: Mapped[str]
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("run.id", ondelete="SET NULL"))
    ref: Mapped[str | None]
    commit: Mapped[str | None]
    pr_no: Mapped[int | None] = mapped_column(Integer)
    isteyen: Mapped[str]
    dis_istek: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJ, default=dict)
    olusturma: Mapped[datetime] = olusturma_col()


class TestResultEk(Base):
    """Test sonucunun JSON raporundan gelen ekleri (a11y, ek dosyalar, denemeler)."""

    __tablename__ = "test_result_ek"
    __test__ = False

    test_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_result.id", ondelete="CASCADE"), primary_key=True
    )
    a11y_ihlal: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    a11y_kritik: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    # [{sayfa, url, ihlal, dugum, etki: {critical: n, serious: n, ...}, kurallar: [...]}]
    a11y: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    # [{ad, yol (koşu dizinine göre), tur, deneme}]
    ekler: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    # [{deneme, sonuc, sure_ms}]
    denemeler: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    proje: Mapped[str | None]
    satir: Mapped[int | None] = mapped_column(Integer)
    # GitHub kipi (0015): artefakttaki error-context.md'den hata anı bağlamı (yerel koşu dizini
    # yok). {aria_snapshot, aria_snapshot_scope, deneme, kaynak}; yerel kipte boş.
    # none_as_null: Python None → SQL NULL (JSON `null` değil); geri doldurma `IS NULL` arar.
    hata_baglami: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    olusturma: Mapped[datetime] = olusturma_col()


# Kontrol Kulesi "aynı commit'te değişen sonuç" sorgusu için (platform tablosuna yalnızca indeks).
TEST_RESULT_COMMIT_IX = Index("test_result_commit_ix_ci", TestResult.commit, TestResult.test_adi)


class RunAria(Base):
    """GitHub koşusunun artefaktındaki aria snapshot dosyasının kopyası (0016).

    Yeşil koşuda `locators.spec.ts` sayfa başına `<sayfa>.aria.yml` yazar; GitHub kipinde bu
    dosyalar yalnızca artefakttadır. core-worker içe aktarımda (ve geri doldurmada) buraya yazar;
    locator onarımı (`repair.service.aria_kaniti`) koşu dizini yokken bu kopyayı okur.
    """

    __tablename__ = "run_aria"
    __table_args__ = (UniqueConstraint("run_id", "yol", name="run_aria_run_yol_key"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"))
    # Artefakt zip'i içindeki göreli yol (NFC) ve dosya adı.
    yol: Mapped[str]
    ad: Mapped[str]
    icerik: Mapped[str]
    boyut: Mapped[int] = mapped_column(Integer)
    # "github_artefakt" (içe aktarım) | "github_artefakt_geri_doldurma"
    kaynak: Mapped[str]
    olusturma: Mapped[datetime] = olusturma_col()
