"""Sprint otomasyonu: ayarlar, Jira durum tetiği, test verisi kataloğu (specs/013).

- `otomasyon_ayari`: portaldan açılıp kapanan otomasyon ayarları (anahtar → JSONB değer).
- `requirement.jira_durumu`, `requirement.qa_tetik_zamani`: Jira durum tetiğinin son gördüğü
  durum ve gereksinimin tetikle otomatik akışa alındığı an (NULL = elle akış).
- `test_verisi` + `test_verisi_surum`: merkezi test verisi kataloğu; case metni değeri değil
  `{veri:anahtar}` atfını taşır. Gizli kayıtta değer tutulmaz, yalnız ortam sırrının adı.
- `script_codegen.veri_izi`: üretimde çözülen anahtarların değer özetleri
  ({anahtar: sha256(değer)[:12]}); `script_codegen.tetik`: üretimi kim başlattı
  (`elle` | `otomatik`);
  `script_codegen_engel_ck`'ye `test_verisi` engel türü (sır tanımsız / katalogda olmayan atıf).
- Geçmiş değişmez: `test_verisi_surum` FK `ON DELETE RESTRICT`; tp_app `test_verisi`yi silemez
  (silme yumuşaktır, `silindi`).

Revision kimliği diğer açık dalların 0021/0022'siyle çakışmasın diye 0030'dur; dev'e birleşirken
`down_revision` zincirin son halkasına çekilir.

Revision ID: 0030
Revises: 0020
Create Date: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 0009'daki `script_codegen_engel_ck` listesi (bu migration `test_verisi` ekler).
ENGEL_TURLERI: tuple[str, ...] = (
    "agent_error",
    "case_changed",
    "check_unknown",
    "defect_candidate",
    "environment",
    "flaky",
    "human_rejected",
    "locator",
    "missing_method",
    "replay_miss",
    "static",
    "unknown_method",
    "unsourced_value",
    "unverified_step",
)


def _engel_ck(turler: Sequence[str]) -> str:
    liste = ", ".join(f"'{t}'" for t in sorted(turler))
    return (
        "ALTER TABLE script_codegen DROP CONSTRAINT script_codegen_engel_ck, "
        "ADD CONSTRAINT script_codegen_engel_ck "
        f"CHECK (engel_turu IS NULL OR engel_turu IN ({liste}))"
    )


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE otomasyon_ayari (
    anahtar TEXT PRIMARY KEY,
    deger JSONB NOT NULL,
    guncelleyen TEXT NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
)
"""
    )
    op.execute(
        """
CREATE TABLE test_verisi (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    anahtar TEXT NOT NULL,
    grup TEXT NOT NULL DEFAULT '',
    aciklama TEXT NOT NULL DEFAULT '',
    deger TEXT,
    gizli BOOLEAN NOT NULL DEFAULT false,
    sir_adi TEXT,
    surum INTEGER NOT NULL DEFAULT 1,
    silindi BOOLEAN NOT NULL DEFAULT false,
    guncelleyen TEXT NOT NULL,
    olusturma TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    guncelleme TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT test_verisi_anahtar_uq UNIQUE (anahtar),
    CONSTRAINT test_verisi_anahtar_ck CHECK (anahtar ~ '^[a-z0-9_]+(\\.[a-z0-9_]+){0,5}$'),
    CONSTRAINT test_verisi_gizli_ck CHECK (
        (gizli AND deger IS NULL AND sir_adi IS NOT NULL)
        OR (NOT gizli AND deger IS NOT NULL AND sir_adi IS NULL)
    )
)
"""
    )
    op.execute(
        """
CREATE TABLE test_verisi_surum (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_verisi_id UUID NOT NULL REFERENCES test_verisi(id) ON DELETE RESTRICT,
    surum INTEGER NOT NULL,
    islem TEXT NOT NULL,
    deger TEXT,
    gizli BOOLEAN NOT NULL,
    sir_adi TEXT,
    degistiren TEXT NOT NULL,
    zaman TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT test_verisi_surum_uq UNIQUE (test_verisi_id, surum),
    CONSTRAINT test_verisi_surum_islem_ck CHECK (islem IN ('guncelle', 'olustur', 'sil'))
)
"""
    )
    op.execute("ALTER TABLE requirement ADD COLUMN jira_durumu TEXT")
    op.execute("ALTER TABLE requirement ADD COLUMN qa_tetik_zamani TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE script_codegen ADD COLUMN veri_izi JSONB")
    op.execute("ALTER TABLE script_codegen ADD COLUMN tetik TEXT NOT NULL DEFAULT 'elle'")
    op.execute(
        "ALTER TABLE script_codegen ADD CONSTRAINT script_codegen_tetik_ck "
        "CHECK (tetik IN ('elle', 'otomatik'))"
    )
    op.execute(_engel_ck((*ENGEL_TURLERI, "test_verisi")))
    # Otomatik akış rozeti: gereksinimin son otomatik case işi (gereksinim listesi tek sorgu).
    op.execute(
        "CREATE INDEX job_otomatik_case_req_ix ON job ((yuk->>'requirement_id'), olusturma) "
        "WHERE tur = 'requirements.otomatik_case'"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON otomasyon_ayari TO tp_app")
    # Katalog silmesi yumuşaktır: tp_app satır silemez (sürüm geçmişi de RESTRICT ile korunur).
    op.execute("GRANT SELECT, INSERT, UPDATE ON test_verisi TO tp_app")
    # Sürüm geçmişi geriye dönük değiştirilemez (case_goruntuleme gibi).
    op.execute("GRANT SELECT, INSERT ON test_verisi_surum TO tp_app")


def downgrade() -> None:
    op.execute("DROP INDEX job_otomatik_case_req_ix")
    op.execute(
        "UPDATE script_codegen SET engel_turu = 'unsourced_value' WHERE engel_turu = 'test_verisi'"
    )
    op.execute(_engel_ck(ENGEL_TURLERI))
    op.execute("ALTER TABLE script_codegen DROP CONSTRAINT script_codegen_tetik_ck")
    op.execute("ALTER TABLE script_codegen DROP COLUMN tetik")
    op.execute("ALTER TABLE script_codegen DROP COLUMN veri_izi")
    op.execute("ALTER TABLE requirement DROP COLUMN qa_tetik_zamani")
    op.execute("ALTER TABLE requirement DROP COLUMN jira_durumu")
    op.execute("DROP TABLE test_verisi_surum")
    op.execute("DROP TABLE test_verisi")
    op.execute("DROP TABLE otomasyon_ayari")
