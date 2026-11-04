"""AI Asistan (portal içi sohbet) tabloları ve `tool_call` kanal genişlemesi (AI-ASISTAN-PLANI §8).

- `asistan_sohbet`: kullanıcının sohbetleri (yumuşak silme; öneriden açılanlarda `oneri_kural_id`).
- `asistan_mesaj`: sıralı mesajlar. Atomiklik kısıtlarla: (sohbet_id, sira) UNIQUE;
  `ust_mesaj_id` dolu olanlarda UNIQUE (bir cevap bir kez derinleştirilir); kullanıcı başına tek
  bekleyen soru (`rol='assistant' AND tetik='kullanici' AND durum IN ('pending','running')`
  kısmi UNIQUE; otomatik yükseltme çocukları hariç); `tetik='otomatik'` yalnız derin çocuk.
  `job_id` / `ai_call_id` yabancı anahtar değildir (iş kuyruğu temizlenir; ai_call append-only).
- `asistan_durum`: worker'ın yazdığı tekil satır (`id = 1`).
- `asistan_oneri_geri_bildirim`: öneri gizle / faydalı / yaptım (-1 / 1 / 2) kayıtları.
- `asistan_hiz`: sabit pencere hız sayacı; `kullanici_id` boş olabilir (global kova), tekillik
  NULLS NOT DISTINCT (PostgreSQL 15+) — `ON CONFLICT … DO UPDATE` global kovada da çalışır.
- `tool_call_kanal_ck` → `kanal IN ('agent', 'asistan', 'ide')`; append-only tetikleyicisi ve
  yetkiler değişmez. Downgrade, `kanal='asistan'` satırı varken bilerek başarısız olur
  (tool_call append-only'dir, satır silinmez).
- `ai_call_parent_ix` (`ai_call.parent_call_id`): asistanın soru başı bütçe/harcama sorguları her
  ajan turunda kök çağrının turlarını bu kolonla arar. Yalnız indeks; kolon ve append-only
  tetikleyicisi değişmez.

Model ↔ şema eşitliği tests/unit/features/assistant/test_migration.py'de doğrulanır.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "asistan_sohbet",
    "asistan_mesaj",
    "asistan_durum",
    "asistan_oneri_geri_bildirim",
    "asistan_hiz",
)

CREATE_STATEMENTS = (
    """
CREATE TABLE asistan_sohbet (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    kullanici_id UUID NOT NULL,
    baslik TEXT,
    oneri_kural_id TEXT,
    silindi BOOLEAN DEFAULT false NOT NULL,
    silinme TIMESTAMP WITH TIME ZONE,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(kullanici_id) REFERENCES app_user (id) ON DELETE CASCADE
)
""",
    "CREATE INDEX asistan_sohbet_kullanici_ix ON asistan_sohbet (kullanici_id, guncelleme)",
    """
CREATE TABLE asistan_mesaj (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    sohbet_id UUID NOT NULL,
    kullanici_id UUID NOT NULL,
    sira INTEGER NOT NULL,
    rol TEXT NOT NULL,
    ust_mesaj_id UUID,
    icerik TEXT,
    baglam JSONB,
    cevap JSONB,
    durum TEXT DEFAULT 'pending' NOT NULL,
    hata_kodu TEXT,
    kaynak TEXT,
    amac TEXT,
    kip TEXT DEFAULT 'soru' NOT NULL,
    tetik TEXT DEFAULT 'kullanici' NOT NULL,
    job_id UUID,
    ai_call_id UUID,
    maliyet_usd NUMERIC(12, 6),
    token_girdi INTEGER,
    token_cikti INTEGER,
    sure_ms INTEGER,
    geri_bildirim SMALLINT,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    tamamlanma TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT asistan_mesaj_rol_ck CHECK (rol IN ('assistant', 'user')),
    CONSTRAINT asistan_mesaj_durum_ck
        CHECK (durum IN ('done', 'error', 'iptal', 'pending', 'running')),
    CONSTRAINT asistan_mesaj_kaynak_ck
        CHECK (kaynak IS NULL OR kaynak IN ('kapali', 'model', 'sablon', 'sozluk')),
    CONSTRAINT asistan_mesaj_amac_ck
        CHECK (amac IS NULL OR amac IN ('assistant', 'assistant_deep')),
    CONSTRAINT asistan_mesaj_kip_ck CHECK (kip IN ('oneri', 'soru')),
    CONSTRAINT asistan_mesaj_tetik_deger_ck CHECK (tetik IN ('kullanici', 'otomatik')),
    CONSTRAINT asistan_mesaj_geri_bildirim_ck
        CHECK (geri_bildirim IS NULL OR geri_bildirim IN (-1, 1)),
    CONSTRAINT asistan_mesaj_tetik_ck
        CHECK (tetik = 'kullanici' OR (ust_mesaj_id IS NOT NULL AND amac = 'assistant_deep')),
    CONSTRAINT asistan_mesaj_sira_uq UNIQUE (sohbet_id, sira),
    FOREIGN KEY(sohbet_id) REFERENCES asistan_sohbet (id) ON DELETE CASCADE,
    FOREIGN KEY(kullanici_id) REFERENCES app_user (id) ON DELETE CASCADE,
    FOREIGN KEY(ust_mesaj_id) REFERENCES asistan_mesaj (id) ON DELETE CASCADE
)
""",
    "CREATE INDEX asistan_mesaj_ai_call_ix ON asistan_mesaj (ai_call_id)",
    "CREATE INDEX asistan_mesaj_kullanici_ix ON asistan_mesaj (kullanici_id, olusturma)",
    "CREATE UNIQUE INDEX asistan_mesaj_ust_uq ON asistan_mesaj (ust_mesaj_id) "
    "WHERE ust_mesaj_id IS NOT NULL",
    "CREATE UNIQUE INDEX asistan_mesaj_bekleyen_uq ON asistan_mesaj (kullanici_id) "
    "WHERE rol = 'assistant' AND tetik = 'kullanici' AND durum IN ('pending', 'running')",
    """
CREATE TABLE asistan_durum (
    id SMALLINT DEFAULT 1 NOT NULL,
    mod TEXT DEFAULT 'off' NOT NULL,
    model_hazir BOOLEAN DEFAULT false NOT NULL,
    maskeleme BOOLEAN DEFAULT false NOT NULL,
    musteri_verisi BOOLEAN DEFAULT false NOT NULL,
    paket_commit TEXT,
    paket_uretim TIMESTAMP WITH TIME ZONE,
    kalp_atisi TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT asistan_durum_tekil_ck CHECK (id = 1),
    CONSTRAINT asistan_durum_mod_ck CHECK (mod IN ('live', 'off'))
)
""",
    """
CREATE TABLE asistan_oneri_geri_bildirim (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    kullanici_id UUID NOT NULL,
    kural_id TEXT NOT NULL,
    varlik_id UUID,
    varlik_durum TEXT,
    deger SMALLINT NOT NULL,
    jira_anahtari TEXT,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT asistan_oneri_geri_bildirim_deger_ck CHECK (deger IN (-1, 1, 2)),
    FOREIGN KEY(kullanici_id) REFERENCES app_user (id) ON DELETE CASCADE
)
""",
    "CREATE INDEX asistan_oneri_geri_bildirim_ix "
    "ON asistan_oneri_geri_bildirim (kullanici_id, kural_id, varlik_id)",
    # Öneri ucunun kullanıcılar arası "Gizle/Yaptım" bastırma sorgusu `kullanici_id` süzmez.
    "CREATE INDEX asistan_oneri_geri_bildirim_varlik_ix "
    "ON asistan_oneri_geri_bildirim (kural_id, varlik_id, varlik_durum)",
    """
CREATE TABLE asistan_hiz (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    kullanici_id UUID,
    kova TEXT NOT NULL,
    pencere_baslangic TIMESTAMP WITH TIME ZONE NOT NULL,
    sayi INTEGER DEFAULT 1 NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT asistan_hiz_uq UNIQUE NULLS NOT DISTINCT (kullanici_id, kova, pencere_baslangic),
    FOREIGN KEY(kullanici_id) REFERENCES app_user (id) ON DELETE CASCADE
)
""",
    "CREATE INDEX asistan_hiz_pencere_ix ON asistan_hiz (pencere_baslangic)",
    "CREATE INDEX ai_call_parent_ix ON ai_call (parent_call_id)",
)


def upgrade() -> None:
    for stmt in CREATE_STATEMENTS:
        op.execute(stmt)
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO tp_app")
    op.drop_constraint("tool_call_kanal_ck", "tool_call", type_="check")
    op.create_check_constraint(
        "tool_call_kanal_ck", "tool_call", "kanal IN ('agent', 'asistan', 'ide')"
    )


def downgrade() -> None:
    # tool_call append-only'dir (Anayasa VIII): 'asistan' satırı varken eski kısıt doğrulanamaz
    # ve geri alma bilerek başarısız olur (satırlar silinmez, NOT VALID ile gizlenmez).
    op.drop_constraint("tool_call_kanal_ck", "tool_call", type_="check")
    op.create_check_constraint("tool_call_kanal_ck", "tool_call", "kanal IN ('agent', 'ide')")
    op.execute("DROP INDEX IF EXISTS ai_call_parent_ix")
    for tablo in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {tablo}")
