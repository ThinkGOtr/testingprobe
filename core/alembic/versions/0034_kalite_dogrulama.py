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

`tp_app` yeni tablolarda SELECT, INSERT, UPDATE yapar; DELETE verilmez (uygulama bu kayıtları
silmez; ama "asla silinmez" değildir: gereksinim / case silinince `ON DELETE CASCADE` ile giderler
ve `case_oracle_kontrol` yeniden kontrolde yerinde güncellenir — review 1 mimari 18).
`oracle_istisna` yalnız SELECT, INSERT (append-only).

Review turu 1 (2026-11-12): dal dev'e girmediği için yerinde güncellendi (§13.2): `kismen` sonucu,
`case_oracle_kontrol.guncelleme`, `oracle_istisna`, `metamorfik_turetme.sonuc`
`tutarsiz_kalan_deger`.

Review turu 2 (2026-11-12, yerinde): `karar_tablosu_onay_hash_ck` / `metamorfik_iliski_onay_hash_ck`
(onaylı satır `onaylanan_hash` ve `gereksinim_hash` taşır; mimari 17) ve `job` üzerinde oracle ifade
indeksleri (`job_oracle_case_ix`, `job_oracle_gereksinim_ix`, `job_oracle_isteyen_ix`; t2 N10).
Bitmiş `oracle.check_*` işleri için saklama (silme) süpürmesi ertelendi: `job`'da DELETE yetkisi
iş kuyruğu şeridinindir; hacim case başına dakikada en çok 10 yeni iştir (hız sınırı).

Numara (origin/dev birleşmesi, 2026-11-13): dal önce `0022` (`down_revision="0020"`) idi; dev'in
zinciri `0021`–`0023`, `0030`–`0033` olduğu için bu dosya `0034_kalite_dogrulama.py` oldu
(`revision="0034"`, `down_revision="0033"`). İçerik değişmedi. `review_nesne_turu_ck`'ye dev'de
`0002`'den sonra dokunan migrasyon yoktur: eski küme `0002`'ninkidir ve downgrade onu aynen geri
yükler. `feat/case-gen-v3` birleşirken v3 zinciri bu dosyanın üstüne yeniden numaralanır ve
v3'ün `design_model` eklemesi bu kümeye göre yazılır (ANALIZ §14.1–§14.2).

Model ↔ şema eşitliği tests/unit/platform/test_migrations.py'de doğrulanır.

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
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

# 0002 kümesi (dev'de başka migrasyon değiştirmez); downgrade bunu aynen geri yükler.
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
    CONSTRAINT karar_tablosu_onay_hash_ck CHECK (durum <> 'approved' OR (onaylanan_hash IS NOT NULL AND gereksinim_hash IS NOT NULL)),
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
    CONSTRAINT metamorfik_iliski_onay_hash_ck CHECK (durum <> 'approved' OR (onaylanan_hash IS NOT NULL AND gereksinim_hash IS NOT NULL)),
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

# Oracle hız sınırı ve gereksinim işi birleştirme sorguları için `job` ifade indeksleri (review 2
# t2 N10; `yuk->>'…'` taraması yerine). Geri almada düşer.
JOB_INDEXES: tuple[tuple[str, str], ...] = (
    (
        "job_oracle_case_ix",
        "CREATE INDEX job_oracle_case_ix ON job ((yuk ->> 'case_id'), olusturma) "
        "WHERE tur = 'oracle.check_case'",
    ),
    (
        "job_oracle_gereksinim_ix",
        "CREATE INDEX job_oracle_gereksinim_ix ON job ((yuk ->> 'requirement_id'), olusturma) "
        "WHERE tur IN ('oracle.check_case', 'oracle.check_requirement')",
    ),
    (
        "job_oracle_isteyen_ix",
        "CREATE INDEX job_oracle_isteyen_ix ON job ((yuk ->> 'isteyen_id'), olusturma) "
        "WHERE tur = 'oracle.check_case'",
    ),
)


def upgrade() -> None:
    for stmt in CREATE_STATEMENTS:
        op.execute(stmt)
    for _ad, stmt in JOB_INDEXES:
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
    for ad, _stmt in JOB_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {ad}")
    for tablo in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {tablo}")
