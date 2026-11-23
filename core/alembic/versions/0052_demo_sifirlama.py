"""Home "Sıfırla" düğmesi (demo tam sıfırlaması): işlem tablosu `demo_sifirlama` ve proje kapsamlı
hata koşusu silme işlevi.

- `demo_sifirlama`: bir sıfırlama işleminin adımları ve "Demoya hazır" kontrol listesi. Kurulum
  geneli kayıttır (sıfırlanan projenin verisiyle silinmez); `project_id` hedef projedir ve ORM proje
  süzgecine bağlı değildir (yalnız ham SQL; `features/demo/tam_sifirlama.py`).
- `tp_demo_hata_kosusu_sil(pid)`: `hata_kosusu`'nda `tp_app`'in DELETE yetkisi bilerek yok (0034;
  uygulama koşu kaydını silemez). Demo tam sıfırlaması yalnız bir projenin hata koşularını bu dar
  SECURITY DEFINER işleviyle siler (adımlar CASCADE); `tp_app`'e genel DELETE verilmez. Diğer iş
  tabloları ya zaten yetkili ya da `requirement`/`test_case`/`run` üzerinden CASCADE ile gider.
  Append-only tablolara (denetim, model çağrıları, review) dokunulmaz.

Revision ID: 0052
Revises: 0051
Create Date: 2026-11-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
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
    op.execute(
        """
CREATE FUNCTION tp_demo_hata_kosusu_sil(p_pid varchar) RETURNS integer
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    WITH silinen AS (DELETE FROM hata_kosusu WHERE project_id = p_pid RETURNING 1)
    SELECT count(*)::integer FROM silinen
$$
"""
    )
    op.execute("REVOKE ALL ON FUNCTION tp_demo_hata_kosusu_sil(varchar) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION tp_demo_hata_kosusu_sil(varchar) TO tp_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION tp_demo_hata_kosusu_sil(varchar)")
    op.execute("DROP TABLE demo_sifirlama")
