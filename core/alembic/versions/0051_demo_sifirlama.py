"""Home "Sıfırla" düğmesi (demo tam sıfırlaması): işlem tablosu `demo_sifirlama` ve proje kapsamlı
silme için eksik DELETE yetkisi.

- `demo_sifirlama`: bir sıfırlama işleminin adımları ve "Demoya hazır" kontrol listesi. Kurulum
  geneli kayıttır (sıfırlanan projenin verisiyle silinmez); `project_id` hedef projedir ve ORM proje
  süzgecine bağlı değildir (yalnız ham SQL; `features/demo/tam_sifirlama.py`).
- `hata_kosusu` / `hata_kosusu_adim`: `tp_app`'in DELETE yetkisi yoktu; proje kapsamlı silme bu
  ikisini de siler (diğer iş tabloları ya zaten yetkili ya da `requirement`/`test_case`/`run`
  üzerinden CASCADE ile gider). Append-only tablolara (denetim, model çağrıları, review) dokunulmaz.

Revision ID: 0051
Revises: 0050
Create Date: 2026-11-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE demo_sifirlama (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id VARCHAR(64) NOT NULL,
    durum TEXT NOT NULL DEFAULT 'kuyrukta',
    adimlar JSONB NOT NULL DEFAULT '[]'::jsonb,
    kontrol JSONB NOT NULL DEFAULT '[]'::jsonb,
    aktor JSONB NOT NULL DEFAULT '{}'::jsonb,
    hazir BOOLEAN NOT NULL DEFAULT false,
    hata TEXT,
    job_id UUID,
    olusturma TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    guncelleme TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    bitis TIMESTAMP WITH TIME ZONE,
    CONSTRAINT demo_sifirlama_durum_ck CHECK (durum IN ('calisiyor', 'hata', 'kuyrukta', 'tamam'))
)
"""
    )
    op.execute("CREATE INDEX demo_sifirlama_proje_ix ON demo_sifirlama (project_id, olusturma)")
    op.execute("GRANT SELECT, INSERT, UPDATE ON demo_sifirlama TO tp_app")
    op.execute("GRANT DELETE ON hata_kosusu, hata_kosusu_adim TO tp_app")


def downgrade() -> None:
    op.execute("REVOKE DELETE ON hata_kosusu, hata_kosusu_adim FROM tp_app")
    op.execute("DROP TABLE demo_sifirlama")
