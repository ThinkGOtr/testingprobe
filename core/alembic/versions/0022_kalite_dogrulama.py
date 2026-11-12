"""Test kalite doğrulama (specs/012-test-kalite-dogrulama/ANALIZ.md §5).

- karar_tablosu: bir hesaplama kuralının PO onaylı girdi → çıktı tanımı (§4.1). `durum`
  `draft → pending_po → approved` (+ `superseded`); `onaylanan_hash` onayla yazılır;
  `gereksinim_hash` onay anındaki gereksinim içeriği (sonradan değişirse tablo bayat).
  `(requirement_id, sira_no)` tekildir.
- metamorfik_iliski: PO onaylı metamorfik ilişki (§4.5); aynı durum makinesi. `karar_tablosu_id`
  ilişkinin kolon adlarını aldığı tablo (olmayabilir).
- case_oracle_kontrol: case içeriğinin (hash'iyle) karar tablolarına göre kontrol sonucu (§4.3);
  `(test_case_id, icerik_hash)` tekildir. `guncelleme` son yeniden hesaplamadır (review 1).
- oracle_istisna: gerekçeli istisnaların append-only kaydı (review 1 V10, §13.2); `tp_app` yalnız
  SELECT, INSERT.
- metamorfik_turetme: `(iliski_id, kaynak_case_id)` başına tek türetme kaydı (§4.5).
- hata_kosusu, hata_kosusu_adim: ekilmiş hata koşusu ve platform × hata adımları (§4.6). Temel ve
  kapanış adımlarında `hata_kodu` boştur.
- review_nesne_turu_ck: `karar_tablosu` ve `metamorfik_iliski` eklenir (PO kararı `review`'a
  yazılır). Kararlar (`approve`, `request_changes`) zaten `review_karar_ck`'dedir.

`tp_app` yeni tablolarda SELECT, INSERT, UPDATE yapar; DELETE verilmez (kontrol, istisna ve koşu
kayıtları silinmez). `oracle_istisna` yalnız SELECT, INSERT (append-only).

Review turu 1 (2026-11-12): dal dev'e girmediği için yerinde güncellendi (§13.2): `kismen` sonucu,
`case_oracle_kontrol.guncelleme`, `oracle_istisna`, `metamorfik_turetme.sonuc`
`tutarsiz_kalan_deger`.

V7: `feat/case-gen-v3` `0021`'i kullanıyor; iki dal birleşirken `down_revision` `"0021"` yapılır.

Model ↔ şema eşitliği tests/unit/platform/test_migrations.py'de doğrulanır.

Revision ID: 0022
Revises: 0020
Create Date: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Oluşturma sırası (FK bağımlılığı); geri alma tersinden.
TABLES = (
    "karar_tablosu",
    "metamorfik_iliski",
    "case_oracle_kontrol",
    "oracle_istisna",
    "metamorfik_turetme",
    "hata_kosusu",
    "hata_kosusu_adim",
)

# Yalnız SELECT, INSERT (append-only; UPDATE de verilmez).
APPEND_ONLY = ("oracle_istisna",)

_NESNE_ESKI = "'bug_draft', 'consistency_finding', 'requirement', 'script', 'test_case'"
_NESNE_YENI = (
    "'bug_draft', 'consistency_finding', 'karar_tablosu', 'metamorfik_iliski', 'requirement', "
    "'script', 'test_case'"
)

CREATE_STATEMENTS: tuple[str, ...] = (
    """
CREATE TABLE karar_tablosu (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    requirement_id UUID NOT NULL,
    sira_no INTEGER NOT NULL,
    icerik JSONB NOT NULL,
    icerik_hash TEXT NOT NULL,
    onaylanan_hash TEXT,
    durum TEXT DEFAULT 'draft' NOT NULL,
    gereksinim_hash TEXT,
    ai_generated BOOLEAN DEFAULT false NOT NULL,
    ai_call_id UUID,
    uretim_modu TEXT,
    olusturan_id UUID,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT karar_tablosu_durum_ck CHECK (durum IN ('approved', 'draft', 'pending_po', 'superseded')),
    CONSTRAINT karar_tablosu_uretim_modu_ck CHECK (uretim_modu IS NULL OR uretim_modu IN ('live', 'replay', 'replay_miss')),
    CONSTRAINT karar_tablosu_sira_uq UNIQUE (requirement_id, sira_no),
    FOREIGN KEY(requirement_id) REFERENCES requirement (id) ON DELETE CASCADE,
    FOREIGN KEY(olusturan_id) REFERENCES app_user (id)
)
""",  # noqa: E501
    """
CREATE TABLE metamorfik_iliski (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    requirement_id UUID NOT NULL,
    karar_tablosu_id UUID,
    sira_no INTEGER NOT NULL,
    icerik JSONB NOT NULL,
    icerik_hash TEXT NOT NULL,
    onaylanan_hash TEXT,
    durum TEXT DEFAULT 'draft' NOT NULL,
    gereksinim_hash TEXT,
    ai_generated BOOLEAN DEFAULT false NOT NULL,
    ai_call_id UUID,
    uretim_modu TEXT,
    olusturan_id UUID,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT metamorfik_iliski_durum_ck CHECK (durum IN ('approved', 'draft', 'pending_po', 'superseded')),
    CONSTRAINT metamorfik_iliski_uretim_modu_ck CHECK (uretim_modu IS NULL OR uretim_modu IN ('live', 'replay', 'replay_miss')),
    CONSTRAINT metamorfik_iliski_sira_uq UNIQUE (requirement_id, sira_no),
    FOREIGN KEY(requirement_id) REFERENCES requirement (id) ON DELETE CASCADE,
    FOREIGN KEY(karar_tablosu_id) REFERENCES karar_tablosu (id) ON DELETE SET NULL,
    FOREIGN KEY(olusturan_id) REFERENCES app_user (id)
)
""",  # noqa: E501
    "CREATE INDEX metamorfik_iliski_tablo_ix ON metamorfik_iliski (karar_tablosu_id)",
    """
CREATE TABLE case_oracle_kontrol (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    test_case_id UUID NOT NULL,
    icerik_hash TEXT NOT NULL,
    sonuc TEXT NOT NULL,
    ayrintilar JSONB DEFAULT '{}'::jsonb NOT NULL,
    tablo_hashleri JSONB DEFAULT '{}'::jsonb NOT NULL,
    ai_icerik BOOLEAN DEFAULT false NOT NULL,
    ai_call_id UUID,
    uretim_modu TEXT,
    istisna_gerekce TEXT,
    istisna_veren_id UUID,
    istisna_zamani TIMESTAMP WITH TIME ZONE,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT case_oracle_kontrol_sonuc_ck CHECK (sonuc IN ('kapsam_disi', 'kismen', 'kontrol_edilemedi', 'uyumlu', 'uyumsuz')),
    CONSTRAINT case_oracle_kontrol_uretim_modu_ck CHECK (uretim_modu IS NULL OR uretim_modu IN ('live', 'replay', 'replay_miss')),
    CONSTRAINT case_oracle_kontrol_case_hash_uq UNIQUE (test_case_id, icerik_hash),
    FOREIGN KEY(test_case_id) REFERENCES test_case (id) ON DELETE CASCADE,
    FOREIGN KEY(istisna_veren_id) REFERENCES app_user (id)
)
""",  # noqa: E501
    """
CREATE TABLE oracle_istisna (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    test_case_id UUID NOT NULL,
    icerik_hash TEXT NOT NULL,
    tur TEXT NOT NULL,
    gerekce TEXT NOT NULL,
    veren_id UUID,
    tablo_hashleri JSONB DEFAULT '{}'::jsonb NOT NULL,
    zaman TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT oracle_istisna_tur_ck CHECK (tur IN ('kontrolsuz', 'uyumsuz')),
    FOREIGN KEY(test_case_id) REFERENCES test_case (id) ON DELETE CASCADE,
    FOREIGN KEY(veren_id) REFERENCES app_user (id)
)
""",
    "CREATE INDEX oracle_istisna_case_ix ON oracle_istisna (test_case_id, icerik_hash)",
    """
CREATE TABLE metamorfik_turetme (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    iliski_id UUID NOT NULL,
    kaynak_case_id UUID NOT NULL,
    turetilen_case_id UUID,
    sonuc TEXT NOT NULL,
    neden TEXT,
    olusturan_id UUID,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT metamorfik_turetme_sonuc_ck CHECK (sonuc IN ('belirsiz_alinti', 'iliski_gecersiz', 'olgu_yok', 'turetildi', 'tutarsiz_kalan_deger')),
    CONSTRAINT metamorfik_turetme_cift_uq UNIQUE (iliski_id, kaynak_case_id),
    FOREIGN KEY(iliski_id) REFERENCES metamorfik_iliski (id) ON DELETE CASCADE,
    FOREIGN KEY(kaynak_case_id) REFERENCES test_case (id) ON DELETE CASCADE,
    FOREIGN KEY(turetilen_case_id) REFERENCES test_case (id) ON DELETE SET NULL,
    FOREIGN KEY(olusturan_id) REFERENCES app_user (id)
)
""",  # noqa: E501
    "CREATE INDEX metamorfik_turetme_kaynak_ix ON metamorfik_turetme (kaynak_case_id)",
    "CREATE INDEX metamorfik_turetme_turetilen_ix ON metamorfik_turetme (turetilen_case_id)",
    """
CREATE TABLE hata_kosusu (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    durum TEXT DEFAULT 'queued' NOT NULL,
    platformlar JSONB DEFAULT '[]'::jsonb NOT NULL,
    hatalar JSONB DEFAULT '[]'::jsonb NOT NULL,
    commit TEXT,
    baslatan_id UUID,
    ozet JSONB DEFAULT '{}'::jsonb NOT NULL,
    uyarilar JSONB DEFAULT '[]'::jsonb NOT NULL,
    baslama TIMESTAMP WITH TIME ZONE,
    bitis TIMESTAMP WITH TIME ZONE,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT hata_kosusu_durum_ck CHECK (durum IN ('cancelled', 'done', 'failed', 'queued', 'running')),
    FOREIGN KEY(baslatan_id) REFERENCES app_user (id)
)
""",  # noqa: E501
    "CREATE INDEX hata_kosusu_durum_ix ON hata_kosusu (durum)",
    "CREATE INDEX hata_kosusu_olusturma_ix ON hata_kosusu (olusturma)",
    """
CREATE TABLE hata_kosusu_adim (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    kosu_id UUID NOT NULL,
    platform TEXT NOT NULL,
    hata_kodu TEXT,
    asama TEXT NOT NULL,
    run_id UUID,
    sonuc TEXT DEFAULT 'bekliyor' NOT NULL,
    kiran_testler JSONB DEFAULT '[]'::jsonb NOT NULL,
    neden TEXT,
    sure_ms INTEGER,
    sira INTEGER NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT hata_kosusu_adim_platform_ck CHECK (platform IN ('android', 'ios', 'web', 'windows')),
    CONSTRAINT hata_kosusu_adim_asama_ck CHECK (asama IN ('hata', 'kapanis', 'temel')),
    CONSTRAINT hata_kosusu_adim_sonuc_ck CHECK (sonuc IN ('bekliyor', 'gecersiz', 'kacti', 'kirmizi', 'yakalandi', 'yesil')),
    CONSTRAINT hata_kosusu_adim_hata_kodu_ck CHECK ((asama = 'hata') = (hata_kodu IS NOT NULL)),
    CONSTRAINT hata_kosusu_adim_sira_uq UNIQUE (kosu_id, sira),
    FOREIGN KEY(kosu_id) REFERENCES hata_kosusu (id) ON DELETE CASCADE,
    FOREIGN KEY(run_id) REFERENCES run (id) ON DELETE SET NULL
)
""",  # noqa: E501
    "CREATE INDEX hata_kosusu_adim_run_ix ON hata_kosusu_adim (run_id)",
)


def upgrade() -> None:
    for stmt in CREATE_STATEMENTS:
        op.execute(stmt)
    guncellenen = [t for t in TABLES if t not in APPEND_ONLY]
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {', '.join(guncellenen)} TO tp_app")
    op.execute(f"GRANT SELECT, INSERT ON {', '.join(APPEND_ONLY)} TO tp_app")
    op.drop_constraint("review_nesne_turu_ck", "review", type_="check")
    op.create_check_constraint("review_nesne_turu_ck", "review", f"nesne_turu IN ({_NESNE_YENI})")


def downgrade() -> None:
    # `review` append-only'dir (0003 tetikleyicisi) ve insan kararları silinmez (Anayasa VIII):
    # var olan karar tablosu / ilişki kararları korunur; eski alan yalnızca yeni satırlara uygulanır
    # (NOT VALID; 0008 ile aynı yol).
    op.drop_constraint("review_nesne_turu_ck", "review", type_="check")
    op.execute(
        "ALTER TABLE review ADD CONSTRAINT review_nesne_turu_ck "
        f"CHECK (nesne_turu IN ({_NESNE_ESKI})) NOT VALID"
    )
    for tablo in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {tablo}")
