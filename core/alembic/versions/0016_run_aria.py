"""GitHub kipi son yeşil aria kanıtı: `run_aria` (koşu başına `<sayfa>.aria.yml` kopyaları).

Yerel kipte locator onarımı (repair `aria_kaniti`) son yeşil koşunun aria dosyalarını koşu
dizininden (`run.artefaktlar.dizin`) okur; yeşil koşuda `locators.spec.ts` sayfa başına
`<sayfa>.aria.yml` yazar. GitHub kipinde yerel koşu dizini yoktur (dosyalar `test-local-results`
artefaktındadır); core-worker içe aktarımda (`github_ingest`) bu dosyaları okuyup buraya yazar,
onarım koşu dizini yokken bu kopyayı okur. core-api GitHub kimlik bilgisi gerektirmez.

- `yol`: artefakt zip'i içindeki göreli yol (NFC; mutlak / `..` içeren yollar alınmaz).
- `icerik`: dosya metni (UTF-8; denetim karakterleri temizlenmiş). Dosya başına boyut ve koşu
  başına dosya sayısı çekirdekte sınırlıdır (`ci.parse.MAX_ARIA_DOSYA_BAYT`,
  `MAX_ARIA_DOSYA_SAYI`); sınırı aşan dosya kesilmez, hiç alınmaz (yarım YAML yanlış kanıttır).
- (`run_id`, `yol`) UNIQUE: geri doldurma idempotenttir. Koşu silinirse satırlar da silinir.

Model ↔ şema eşitliği tests/unit/features/ci/test_migration.py'de doğrulanır.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE run_aria (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    run_id UUID NOT NULL,
    yol TEXT NOT NULL,
    ad TEXT NOT NULL,
    icerik TEXT NOT NULL,
    boyut INTEGER NOT NULL,
    kaynak TEXT NOT NULL,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT run_aria_run_yol_key UNIQUE (run_id, yol),
    FOREIGN KEY(run_id) REFERENCES run (id) ON DELETE CASCADE
)
"""
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON run_aria TO tp_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS run_aria")
