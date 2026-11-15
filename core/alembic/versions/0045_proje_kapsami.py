"""Proje kapsamı (TP-COK-PROJE-PLANI §1.1–§1.5, Şerit 1): `project_id` sütunu, proje başına
tekillikler, `project_id` öncülü index'ler, `proje_sayac` tohumları, `asistan_durum` PK dönüşümü.

Veri (K4): mevcut tüm satırlar bugünkü projeye (`TP_HOME_PROJECT`) aittir. Sütun
`ADD COLUMN project_id varchar(64) NOT NULL DEFAULT '<pid>'` ile eklenir, sonra varsayılan
düşer. PG11+ "hızlı varsayılan" satırı yeniden yazmaz ve UPDATE tetiklemez: `ai_call`,
`tool_call`, `audit_event`, `review` append-only tetikleyicileri devre dışı bırakılmaz ve
`audit_event` hash'leri bozulmaz (hash formülü `project_id` içermez; zincir proje başına,
mevcut zincir varsayılan projenin zinciri olarak aynen geçerlidir).

`<pid>`: `TP_HOME_PROJECT`; boşsa `CONFIG_SOURCE=home` iken migrasyon **hata ile durur** (yanlış
pid'le kalıcı damgalamayı önler), değilse `'varsayilan'` (yerel/on-prem, 0044 ile aynı kural).

- Kapsamlı tablolar (`ProjeKapsamli`): `project_id NOT NULL`.
- `job.project_id` NULL'a izinli (NULL = kurulum geneli iş); mevcut işler `<pid>` alır (eski
  idempotency anahtarları aynı projede tekil kalır — örn. tamamlanmış gece koşusu yeniden açılmaz).
- `asistan_hiz.project_id NOT NULL DEFAULT '_kurulum'` (kullanıcı kovaları kurulum geneli).
- Tekillikler (§1.2): `requirement (project_id, jira_key)`, `test_verisi_anahtar_uq`,
  `otomasyon_ayari` PK, `ci_tetik`, `failure_ek`, `ajan_testi_talebi.talep_no`,
  `external_ref.idempotency_key`, `job_idempotency_uq` (NULLS NOT DISTINCT), `pull_request` PK
  `(project_id, number)` (dizi varsayılanı kalkar; numara forge'dan / `proje_sayac('pr')`),
  `asistan_durum` PK `project_id` (`id` düşer), `asistan_hiz_uq`, `audit_event.prev_hash`.
- `proje_sayac` tohumları: `pr` = `max(pull_request.number)`, `talep` =
  `ajan_testi_talebi_no_seq` son değeri (dizi silinmez; geçişte simülatör hâlâ kullanabilir).

Downgrade yalnız tek proje varken (her tabloda `count(DISTINCT project_id) <= 1`) çalışır; aksi
halde `RuntimeError` (`_kurulum` denetim zinciri satırı varken de: iki zincir birleştirilemez).

Revision ID: 0045
Revises: 0044
Create Date: 2026-11-15
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KURULUM = "_kurulum"

KAPSAMLI: tuple[str, ...] = (
    "acik_soru",
    "ai_call",
    "ajan_testi_talebi",
    "ajan_urunu_baglantisi",
    "api_token",
    "asistan_denetim",
    "asistan_durum",
    "asistan_guvenlik_olay",
    "asistan_mesaj",
    "asistan_oneri_geri_bildirim",
    "asistan_sohbet",
    "audit_event",
    "bug_draft",
    "bug_draft_ek",
    "case_goruntuleme",
    "case_oracle_kontrol",
    "case_set_audit",
    "case_set_review",
    "case_uretim",
    "ci_tetik",
    "consistency_finding",
    "consistency_finding_ek",
    "external_ref",
    "failure",
    "failure_ek",
    "hata_kosusu",
    "hata_kosusu_adim",
    "karar_tablosu",
    "metamorfik_iliski",
    "metamorfik_turetme",
    "oracle_istisna",
    "otomasyon_ayari",
    "pull_request",
    "requirement",
    "requirement_akis",
    "requirement_baz_deger",
    "requirement_kontrol",
    "requirement_review",
    "requirement_review_ek",
    "review",
    "run",
    "run_aria",
    "script",
    "script_adim",
    "script_codegen",
    "script_kontrol",
    "script_test_case",
    "step_mapping",
    "tasarim_modeli",
    "test_case",
    "test_result",
    "test_result_ek",
    "test_verisi",
    "test_verisi_surum",
    "tool_call",
    "triage_kosu",
    "workflow_instance",
)

# (tablo, eski kısıt, yeni kısıt, eski kolonlar, yeni kolonlar) — UNIQUE kısıtları.
TEKILLIKLER: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "requirement",
        "requirement_jira_key_key",
        "requirement_proje_jira_key_uq",
        "jira_key",
        "project_id, jira_key",
    ),
    (
        "test_verisi",
        "test_verisi_anahtar_uq",
        "test_verisi_anahtar_uq",
        "anahtar",
        "project_id, anahtar",
    ),
    (
        "ci_tetik",
        "ci_tetik_anahtar_key",
        "ci_tetik_proje_anahtar_uq",
        "anahtar",
        "project_id, anahtar",
    ),
    (
        "failure_ek",
        "failure_ek_anahtar_key",
        "failure_ek_proje_anahtar_uq",
        "anahtar",
        "project_id, anahtar",
    ),
    (
        "ajan_testi_talebi",
        "ajan_testi_talebi_talep_no_key",
        "ajan_testi_talebi_proje_talep_no_uq",
        "talep_no",
        "project_id, talep_no",
    ),
    (
        "external_ref",
        "external_ref_idempotency_key_key",
        "external_ref_proje_idempotency_uq",
        "idempotency_key",
        "project_id, idempotency_key",
    ),
    (
        "audit_event",
        "audit_event_prev_hash_key",
        "audit_event_proje_prev_hash_uq",
        "prev_hash",
        "project_id, prev_hash",
    ),
)

# (index, tablo, kolonlar) — sık listelenen tablolarda `project_id` öncülü index'ler (§1.2).
INDEXLER: tuple[tuple[str, str, str], ...] = (
    *(
        (f"{t}_proje_olusturma_ix", t, "project_id, olusturma")
        for t in (
            "requirement",
            "test_case",
            "script",
            "run",
            "test_result",
            "failure",
            "bug_draft",
            "job",
            "ai_call",
            "asistan_sohbet",
        )
    ),
    ("audit_event_proje_id_ix", "audit_event", "project_id, id"),
)


def _pid() -> str:
    pid = (os.environ.get("TP_HOME_PROJECT") or "").strip()
    if not pid:
        if (os.environ.get("CONFIG_SOURCE") or "env").strip().lower() == "home":
            raise RuntimeError(
                "0045: CONFIG_SOURCE=home ama TP_HOME_PROJECT boş — mevcut veri hangi projeye "
                "damgalanacağı bilinmeden taşınmaz (TP-COK-PROJE-PLANI §1.4, §8.3)"
            )
        pid = "varsayilan"
    if len(pid) > 64 or pid == KURULUM:
        raise RuntimeError(f"0045: geçersiz TP_HOME_PROJECT: {pid!r}")
    return pid


def _lit(deger: str) -> str:
    return "'" + deger.replace("'", "''") + "'"


def upgrade() -> None:
    pid = _pid()
    bind = op.get_bind()
    bind.execute(
        sa.text("INSERT INTO tp_proje (pid, kaynak) VALUES (:pid, 'env') ON CONFLICT DO NOTHING"),
        {"pid": pid},
    )

    # 1) Sütunlar — hızlı varsayılan (satır yeniden yazılmaz, tetikleyici çalışmaz).
    for t in KAPSAMLI:
        op.execute(
            f"ALTER TABLE {t} ADD COLUMN project_id varchar(64) NOT NULL DEFAULT {_lit(pid)}"
        )
        op.execute(f"ALTER TABLE {t} ALTER COLUMN project_id DROP DEFAULT")
    op.execute(f"ALTER TABLE job ADD COLUMN project_id varchar(64) DEFAULT {_lit(pid)}")
    op.execute("ALTER TABLE job ALTER COLUMN project_id DROP DEFAULT")
    op.execute(
        f"ALTER TABLE asistan_hiz ADD COLUMN project_id varchar(64) NOT NULL "
        f"DEFAULT {_lit(KURULUM)}"
    )

    # 2) Proje başına tekillikler.
    for tablo, eski, yeni, _eski_k, yeni_k in TEKILLIKLER:
        op.execute(f"ALTER TABLE {tablo} DROP CONSTRAINT {eski}")
        op.execute(f"ALTER TABLE {tablo} ADD CONSTRAINT {yeni} UNIQUE ({yeni_k})")
    op.execute("ALTER TABLE otomasyon_ayari DROP CONSTRAINT otomasyon_ayari_pkey")
    op.execute(
        "ALTER TABLE otomasyon_ayari ADD CONSTRAINT otomasyon_ayari_pkey "
        "PRIMARY KEY (project_id, anahtar)"
    )
    op.execute("DROP INDEX job_idempotency_uq")
    op.execute(
        "CREATE UNIQUE INDEX job_idempotency_uq ON job (project_id, idempotency_key) "
        "NULLS NOT DISTINCT WHERE idempotency_key IS NOT NULL"
    )
    op.execute("ALTER TABLE asistan_hiz DROP CONSTRAINT asistan_hiz_uq")
    op.execute(
        "ALTER TABLE asistan_hiz ADD CONSTRAINT asistan_hiz_uq UNIQUE NULLS NOT DISTINCT "
        "(project_id, kullanici_id, kova, pencere_baslangic)"
    )
    # pull_request: PK (project_id, number); global dizi varsayılanı kalkar.
    op.execute("ALTER TABLE pull_request DROP CONSTRAINT pull_request_pkey")
    op.execute(
        "ALTER TABLE pull_request ADD CONSTRAINT pull_request_pkey PRIMARY KEY (project_id, number)"
    )
    op.execute("ALTER TABLE pull_request ALTER COLUMN number DROP DEFAULT")
    op.execute("DROP SEQUENCE IF EXISTS pull_request_number_seq")
    # asistan_durum: tekil `id = 1` satırı → proje başına satır.
    op.execute("ALTER TABLE asistan_durum DROP CONSTRAINT asistan_durum_tekil_ck")
    op.execute("ALTER TABLE asistan_durum DROP CONSTRAINT asistan_durum_pkey")
    op.execute("ALTER TABLE asistan_durum DROP COLUMN id")
    op.execute(
        "ALTER TABLE asistan_durum ADD CONSTRAINT asistan_durum_pkey PRIMARY KEY (project_id)"
    )

    # 3) Liste index'leri.
    for ad, tablo, kolonlar in INDEXLER:
        op.execute(f"CREATE INDEX {ad} ON {tablo} ({kolonlar})")

    # 4) Proje sayacı tohumları (yeniden yükseltmede geriye gitmez).
    tohum = (
        "INSERT INTO proje_sayac (project_id, ad, deger) VALUES (:pid, :ad, :d) "
        "ON CONFLICT (project_id, ad) DO UPDATE SET "
        "deger = GREATEST(proje_sayac.deger, EXCLUDED.deger)"
    )
    pr = bind.execute(sa.text("SELECT max(number) FROM pull_request")).scalar()
    if pr:
        bind.execute(sa.text(tohum), {"pid": pid, "ad": "pr", "d": int(pr)})
    if bind.execute(sa.text("SELECT to_regclass('public.ajan_testi_talebi_no_seq')")).scalar():
        son, cagrildi = bind.execute(
            sa.text("SELECT last_value, is_called FROM ajan_testi_talebi_no_seq")
        ).one()
        if cagrildi:
            bind.execute(sa.text(tohum), {"pid": pid, "ad": "talep", "d": int(son)})


def _tek_proje_denetimi(bind: sa.Connection) -> None:
    for t in (*KAPSAMLI, "job"):
        n = bind.execute(sa.text(f"SELECT count(DISTINCT project_id) FROM {t}")).scalar_one()
        if n > 1:
            raise RuntimeError(
                f"0045 downgrade: {t} birden çok projenin verisini taşıyor; tek proje şemasına "
                "geri dönülemez (ileri-düzeltme gerekir, TP-COK-PROJE-PLANI §8.3 adım 7)"
            )
    farkli = bind.execute(
        sa.text(
            "SELECT count(*) FROM (SELECT project_id FROM audit_event UNION "
            "SELECT project_id FROM ai_call UNION SELECT project_id FROM job "
            "WHERE project_id IS NOT NULL) p"
        )
    ).scalar_one()
    if farkli > 1:
        raise RuntimeError("0045 downgrade: tablolar farklı projelere ait; geri dönülemez")
    n = bind.execute(
        sa.text(
            "SELECT count(*) FROM asistan_hiz GROUP BY kullanici_id, kova, pencere_baslangic "
            "HAVING count(*) > 1 LIMIT 1"
        )
    ).scalar()
    if n:
        raise RuntimeError("0045 downgrade: asistan_hiz kovaları projeler arasında çakışıyor")


def downgrade() -> None:
    bind = op.get_bind()
    _tek_proje_denetimi(bind)

    for ad, _tablo, _k in reversed(INDEXLER):
        op.execute(f"DROP INDEX IF EXISTS {ad}")

    op.execute("ALTER TABLE asistan_durum DROP CONSTRAINT asistan_durum_pkey")
    op.execute("ALTER TABLE asistan_durum ADD COLUMN id smallint NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE asistan_durum ADD CONSTRAINT asistan_durum_pkey PRIMARY KEY (id)")
    op.execute("ALTER TABLE asistan_durum ADD CONSTRAINT asistan_durum_tekil_ck CHECK (id = 1)")

    op.execute("CREATE SEQUENCE pull_request_number_seq OWNED BY pull_request.number")
    op.execute(
        "SELECT setval('pull_request_number_seq', GREATEST(COALESCE(max(number), 0), 1), "
        "max(number) IS NOT NULL) FROM pull_request"
    )
    op.execute(
        "ALTER TABLE pull_request ALTER COLUMN number "
        "SET DEFAULT nextval('pull_request_number_seq'::regclass)"
    )
    op.execute("ALTER TABLE pull_request DROP CONSTRAINT pull_request_pkey")
    op.execute("ALTER TABLE pull_request ADD CONSTRAINT pull_request_pkey PRIMARY KEY (number)")

    op.execute("ALTER TABLE asistan_hiz DROP CONSTRAINT asistan_hiz_uq")
    op.execute(
        "ALTER TABLE asistan_hiz ADD CONSTRAINT asistan_hiz_uq UNIQUE NULLS NOT DISTINCT "
        "(kullanici_id, kova, pencere_baslangic)"
    )
    op.execute("DROP INDEX job_idempotency_uq")
    op.execute(
        "CREATE UNIQUE INDEX job_idempotency_uq ON job (idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )
    op.execute("ALTER TABLE otomasyon_ayari DROP CONSTRAINT otomasyon_ayari_pkey")
    op.execute(
        "ALTER TABLE otomasyon_ayari ADD CONSTRAINT otomasyon_ayari_pkey PRIMARY KEY (anahtar)"
    )
    for tablo, eski, yeni, eski_k, _yeni_k in reversed(TEKILLIKLER):
        op.execute(f"ALTER TABLE {tablo} DROP CONSTRAINT {yeni}")
        op.execute(f"ALTER TABLE {tablo} ADD CONSTRAINT {eski} UNIQUE ({eski_k})")

    op.execute("ALTER TABLE asistan_hiz DROP COLUMN project_id")
    op.execute("ALTER TABLE job DROP COLUMN project_id")
    for t in reversed(KAPSAMLI):
        op.execute(f"ALTER TABLE {t} DROP COLUMN project_id")
    # Tohumlar 0044'ün tablosunda kalır (0044 downgrade tabloyu siler); yeniden yükseltme
    # GREATEST ile geriye gitmez.
