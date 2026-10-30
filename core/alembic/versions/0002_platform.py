# ruff: noqa: E501 — aşağıdaki CREATE TABLE ifadeleri modellerden üretilip dondurulmuştur.
"""Platform şeması: tüm alan tabloları, denetim zinciri (prev_hash/hash), iş kuyruğu genişletmesi

- TEKNIK-TASARIM §7 tabloları MIMARI-SOZLESME §4'e göre (Türkçe kolonlar, uuid PK, JSONB).
- audit_event: prev_hash/hash kolonları; mevcut satırlar zincire bağlanır (backfill), NOT NULL +
  UNIQUE(prev_hash) ile çatallanma engellenir.
- job: retry/backoff, idempotency anahtarı, run_after, son_hata, zaman aşımı.
- Yetkiler: tp_app ai_call, tool_call, audit_event üzerinde yalnızca INSERT/SELECT; diğerlerinde
  tam DML. Bu üç tabloya ek olarak sahip dahil herkes için UPDATE/DELETE/TRUNCATE tetikleyicisi.

CREATE TABLE ifadeleri yazıldığı andaki modellerden üretilip donduruldu; model ↔ şema eşitliği
tests/unit/platform/test_migrations.py'de doğrulanır.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from tp_core.audit.canonical import GENESIS_HASH, chain_hash, iso_utc

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY = ("ai_call", "tool_call", "audit_event")

NEW_TABLES: tuple[str, ...] = (
    "ai_call",
    "external_ref",
    "pull_request",
    "script",
    "tool_call",
    "workflow_instance",
    "api_token",
    "requirement",
    "review",
    "run",
    "consistency_finding",
    "requirement_review",
    "test_case",
    "script_test_case",
    "step_mapping",
    "test_result",
    "failure",
    "bug_draft",
)

CREATE_STATEMENTS: tuple[str, ...] = (
    """
CREATE TABLE ai_call (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    parent_call_id UUID,
    workflow_id UUID,
    amac TEXT NOT NULL,
    saglayici TEXT NOT NULL,
    model TEXT NOT NULL,
    surum TEXT,
    bundle_hash TEXT,
    maskeli_girdi JSONB,
    cikti JSONB,
    sema_gecerli BOOLEAN,
    deneme INTEGER DEFAULT '1' NOT NULL,
    girdi_token INTEGER DEFAULT '0' NOT NULL,
    cikti_token INTEGER DEFAULT '0' NOT NULL,
    maliyet NUMERIC(12, 6) DEFAULT '0' NOT NULL,
    sure_ms INTEGER,
    mod TEXT NOT NULL,
    replay_anahtari TEXT,
    hata TEXT,
    maskeleme_farki JSONB,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ai_call_mod_ck CHECK (mod IN ('live', 'replay', 'replay_miss'))
)
""",
    "CREATE INDEX ai_call_olusturma_ix ON ai_call (olusturma)",
    "CREATE INDEX ai_call_workflow_ix ON ai_call (workflow_id)",
    """
CREATE TABLE external_ref (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    entity_turu TEXT NOT NULL,
    entity_id UUID NOT NULL,
    sistem TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    external_key TEXT,
    url TEXT,
    durum TEXT DEFAULT 'intent' NOT NULL,
    hata TEXT,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT external_ref_sistem_ck CHECK (sistem IN ('github', 'jira', 'local_forge', 'xray')),
    CONSTRAINT external_ref_durum_ck CHECK (durum IN ('created', 'failed', 'intent')),
    UNIQUE (idempotency_key)
)
""",
    "CREATE INDEX external_ref_entity_ix ON external_ref (entity_id)",
    """
CREATE TABLE pull_request (
    number SERIAL NOT NULL,
    branch TEXT NOT NULL,
    base TEXT DEFAULT 'main' NOT NULL,
    baslik TEXT NOT NULL,
    govde TEXT DEFAULT '' NOT NULL,
    durum TEXT DEFAULT 'open' NOT NULL,
    head_sha TEXT NOT NULL,
    merge_sha TEXT,
    etiketler JSONB DEFAULT '[]'::jsonb NOT NULL,
    yorumlar JSONB DEFAULT '[]'::jsonb NOT NULL,
    acan TEXT NOT NULL,
    merge_eden TEXT,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (number),
    CONSTRAINT pull_request_durum_ck CHECK (durum IN ('closed', 'merged', 'open'))
)
""",
    """
CREATE TABLE script (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    tur TEXT DEFAULT 'test' NOT NULL,
    dosya_yolu TEXT NOT NULL,
    icerik TEXT,
    icerik_hash TEXT,
    onaylanan_hash TEXT,
    branch TEXT,
    pr_no INTEGER,
    head_sha TEXT,
    durum TEXT DEFAULT 'pending' NOT NULL,
    pass_at_1 BOOLEAN,
    onarim_sonrasi_sonuc TEXT,
    insan_review_sonucu TEXT,
    zayif_test BOOLEAN DEFAULT false NOT NULL,
    kirma_dogrulama JSONB,
    failure_id UUID,
    uretim_modu TEXT,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT script_tur_ck CHECK (tur IN ('locator_fix', 'test')),
    CONSTRAINT script_durum_ck CHECK (durum IN ('blocked', 'checking', 'closed', 'failed', 'merged', 'pending', 'pr_open', 'verifying')),
    CONSTRAINT script_mod_ck CHECK (uretim_modu IS NULL OR uretim_modu IN ('live', 'replay', 'replay_miss'))
)
""",
    """
CREATE TABLE tool_call (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    ai_call_id UUID,
    kanal TEXT NOT NULL,
    cagiran_user_id UUID,
    arac TEXT NOT NULL,
    arguman_ozeti JSONB,
    sonuc_ozeti TEXT,
    izin_verildi BOOLEAN DEFAULT true NOT NULL,
    sure_ms INTEGER,
    zaman TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT tool_call_kanal_ck CHECK (kanal IN ('agent', 'ide'))
)
""",
    "CREATE INDEX tool_call_ai_call_ix ON tool_call (ai_call_id)",
    """
CREATE TABLE workflow_instance (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    tur TEXT NOT NULL,
    job_id UUID,
    durum TEXT DEFAULT 'running' NOT NULL,
    baslatan TEXT NOT NULL,
    nesne_turu TEXT,
    nesne_id UUID,
    baglam JSONB DEFAULT '{}'::jsonb NOT NULL,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT workflow_instance_durum_ck CHECK (durum IN ('cancelled', 'done', 'failed', 'paused', 'running', 'waiting_human'))
)
""",
    "CREATE INDEX workflow_instance_nesne_ix ON workflow_instance (nesne_turu, nesne_id)",
    """
CREATE TABLE api_token (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    user_id UUID NOT NULL,
    kapsam TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    son_kullanma TIMESTAMP WITH TIME ZONE NOT NULL,
    iptal BOOLEAN DEFAULT false NOT NULL,
    son_kullanim TIMESTAMP WITH TIME ZONE,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT api_token_kapsam_ck CHECK (kapsam IN ('publish', 'submit')),
    FOREIGN KEY(user_id) REFERENCES app_user (id) ON DELETE CASCADE,
    UNIQUE (token_hash)
)
""",
    "CREATE INDEX api_token_user_ix ON api_token (user_id)",
    """
CREATE TABLE requirement (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    kaynak TEXT NOT NULL,
    jira_key TEXT,
    baslik TEXT NOT NULL,
    aciklama TEXT DEFAULT '' NOT NULL,
    kabul_kriterleri JSONB DEFAULT '[]'::jsonb NOT NULL,
    kaynak_hash TEXT NOT NULL,
    ac_missing BOOLEAN DEFAULT false NOT NULL,
    durum TEXT DEFAULT 'new' NOT NULL,
    cekim_zamani TIMESTAMP WITH TIME ZONE,
    olusturan_id UUID,
    kontrol_turu INTEGER DEFAULT '0' NOT NULL,
    po_onaylayan TEXT,
    po_onay_zamani TIMESTAMP WITH TIME ZONE,
    po_onay_kaynagi TEXT,
    po_cevaplari JSONB DEFAULT '[]'::jsonb NOT NULL,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT requirement_kaynak_ck CHECK (kaynak IN ('free_text', 'jira')),
    CONSTRAINT requirement_durum_ck CHECK (durum IN ('cases_ready', 'doc_final', 'done', 'failed', 'findings_open', 'generating', 'in_review', 'new', 'pending_po', 'po_approved')),
    CONSTRAINT requirement_po_kaynak_ck CHECK (po_onay_kaynagi IS NULL OR po_onay_kaynagi IN ('jira_label', 'portal')),
    CONSTRAINT requirement_jira_key_ck CHECK (kaynak <> 'jira' OR jira_key IS NOT NULL),
    UNIQUE (jira_key),
    FOREIGN KEY(olusturan_id) REFERENCES app_user (id)
)
""",
    """
CREATE TABLE review (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    nesne_turu TEXT NOT NULL,
    nesne_id UUID NOT NULL,
    user_id UUID,
    harici_onaylayan TEXT,
    kanal TEXT DEFAULT 'portal' NOT NULL,
    karar TEXT NOT NULL,
    ret_nedeni TEXT,
    gerekce TEXT,
    once JSONB,
    sonra JSONB,
    duzeltme_olculeri JSONB,
    onaylanan_hash TEXT NOT NULL,
    sira BIGINT GENERATED ALWAYS AS IDENTITY,
    zaman TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT review_nesne_turu_ck CHECK (nesne_turu IN ('bug_draft', 'consistency_finding', 'requirement', 'script', 'test_case')),
    CONSTRAINT review_karar_ck CHECK (karar IN ('accept_difference', 'approve', 'code_defect', 'dismiss', 'edit', 'fix_doc', 'link', 'merge', 'new', 'po_approve', 'reject', 'request_changes')),
    CONSTRAINT review_kanal_ck CHECK (kanal IN ('jira', 'portal')),
    CONSTRAINT review_ret_nedeni_ck CHECK (ret_nedeni IS NULL OR ret_nedeni IN ('duplicate', 'hallucinated_step', 'missing_ac', 'out_of_scope', 'wrong_element', 'wrong_test_data')),
    CONSTRAINT review_onaylayan_ck CHECK (user_id IS NOT NULL OR harici_onaylayan IS NOT NULL),
    CONSTRAINT review_ret_ck CHECK (karar <> 'reject' OR ret_nedeni IS NOT NULL),
    FOREIGN KEY(user_id) REFERENCES app_user (id),
    UNIQUE (sira)
)
""",
    "CREATE INDEX review_nesne_ix ON review (nesne_turu, nesne_id, sira)",
    """
CREATE TABLE run (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    script_id UUID,
    pr_no INTEGER,
    commit TEXT,
    github_run_id TEXT,
    kaynak TEXT DEFAULT 'local' NOT NULL,
    tetik TEXT NOT NULL,
    sonuc TEXT DEFAULT 'queued' NOT NULL,
    ortam JSONB DEFAULT '{}'::jsonb NOT NULL,
    artefaktlar JSONB DEFAULT '{}'::jsonb NOT NULL,
    sure_ms INTEGER,
    baslama TIMESTAMP WITH TIME ZONE,
    bitis TIMESTAMP WITH TIME ZONE,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT run_kaynak_ck CHECK (kaynak IN ('github', 'local', 'sauce')),
    CONSTRAINT run_tetik_ck CHECK (tetik IN ('break_verify', 'deploy', 'local_check', 'nightly', 'pr', 'push')),
    CONSTRAINT run_sonuc_ck CHECK (sonuc IN ('error', 'failed', 'passed', 'queued', 'running')),
    FOREIGN KEY(script_id) REFERENCES script (id)
)
""",
    "CREATE INDEX run_olusturma_ix ON run (olusturma)",
    """
CREATE TABLE consistency_finding (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    requirement_id UUID NOT NULL,
    kontrol_turu INTEGER DEFAULT '1' NOT NULL,
    tur TEXT NOT NULL,
    doc_ref TEXT NOT NULL,
    kanitlar JSONB DEFAULT '[]'::jsonb NOT NULL,
    kanit_dogrulandi BOOLEAN DEFAULT false NOT NULL,
    severity TEXT NOT NULL,
    onerilen_metin TEXT,
    analist_karari TEXT,
    gerekce TEXT,
    karar_veren_id UUID,
    karar_zamani TIMESTAMP WITH TIME ZONE,
    durum TEXT DEFAULT 'unverified' NOT NULL,
    ai_call_id UUID,
    uretim_modu TEXT,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT consistency_finding_tur_ck CHECK (tur IN ('ambiguous', 'doc_vs_code', 'doc_vs_data', 'internal_contradiction', 'missing_in_code', 'missing_in_doc')),
    CONSTRAINT consistency_finding_severity_ck CHECK (severity IN ('blocking', 'warning')),
    CONSTRAINT consistency_finding_karar_ck CHECK (analist_karari IS NULL OR analist_karari IN ('accept_difference', 'code_defect', 'fix_doc')),
    CONSTRAINT consistency_finding_durum_ck CHECK (durum IN ('decided', 'discarded', 'open', 'resolved', 'stale', 'unverified')),
    CONSTRAINT consistency_finding_mod_ck CHECK (uretim_modu IS NULL OR uretim_modu IN ('live', 'replay', 'replay_miss')),
    FOREIGN KEY(requirement_id) REFERENCES requirement (id) ON DELETE CASCADE,
    FOREIGN KEY(karar_veren_id) REFERENCES app_user (id)
)
""",
    "CREATE INDEX consistency_finding_req_ix ON consistency_finding (requirement_id, kontrol_turu)",
    """
CREATE TABLE requirement_review (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    requirement_id UUID NOT NULL,
    sorular JSONB DEFAULT '[]'::jsonb NOT NULL,
    verdict TEXT NOT NULL,
    jira_comment_id TEXT,
    po_onay_kullanicisi TEXT,
    po_onay_zamani TIMESTAMP WITH TIME ZONE,
    durum TEXT DEFAULT 'pending_po' NOT NULL,
    ai_call_id UUID,
    uretim_modu TEXT,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT requirement_review_verdict_ck CHECK (verdict IN ('needs_po', 'ready')),
    CONSTRAINT requirement_review_durum_ck CHECK (durum IN ('approved', 'pending_po', 'superseded')),
    CONSTRAINT requirement_review_mod_ck CHECK (uretim_modu IS NULL OR uretim_modu IN ('live', 'replay', 'replay_miss')),
    FOREIGN KEY(requirement_id) REFERENCES requirement (id) ON DELETE CASCADE
)
""",
    "CREATE INDEX requirement_review_req_ix ON requirement_review (requirement_id)",
    """
CREATE TABLE test_case (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    requirement_id UUID NOT NULL,
    sira_no INTEGER NOT NULL,
    uretim_no INTEGER DEFAULT '1' NOT NULL,
    kanal TEXT DEFAULT 'portal' NOT NULL,
    surum INTEGER DEFAULT '1' NOT NULL,
    icerik JSONB NOT NULL,
    icerik_hash TEXT NOT NULL,
    onaylanan_hash TEXT,
    durum TEXT DEFAULT 'draft' NOT NULL,
    ai_generated BOOLEAN DEFAULT true NOT NULL,
    ai_call_id UUID,
    uretim_modu TEXT,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT test_case_kanal_ck CHECK (kanal IN ('ide', 'portal')),
    CONSTRAINT test_case_durum_ck CHECK (durum IN ('approved', 'draft', 'published', 'rejected', 'superseded')),
    CONSTRAINT test_case_mod_ck CHECK (uretim_modu IS NULL OR uretim_modu IN ('live', 'replay', 'replay_miss')),
    FOREIGN KEY(requirement_id) REFERENCES requirement (id) ON DELETE CASCADE
)
""",
    "CREATE INDEX test_case_req_ix ON test_case (requirement_id)",
    """
CREATE TABLE script_test_case (
    script_id UUID NOT NULL,
    test_case_id UUID NOT NULL,
    PRIMARY KEY (script_id, test_case_id),
    FOREIGN KEY(script_id) REFERENCES script (id) ON DELETE CASCADE,
    FOREIGN KEY(test_case_id) REFERENCES test_case (id) ON DELETE CASCADE
)
""",
    """
CREATE TABLE step_mapping (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    test_case_id UUID NOT NULL,
    script_id UUID,
    adim_no INTEGER NOT NULL,
    adim_kimligi TEXT,
    po_sinifi TEXT NOT NULL,
    po_metodu TEXT NOT NULL,
    argumanlar JSONB DEFAULT '[]'::jsonb NOT NULL,
    beklenen BOOLEAN DEFAULT false NOT NULL,
    dogrulandi BOOLEAN DEFAULT false NOT NULL,
    ekran_goruntusu_ref TEXT,
    kanit_ref TEXT,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT step_mapping_adim_uq UNIQUE (test_case_id, script_id, adim_no),
    FOREIGN KEY(test_case_id) REFERENCES test_case (id) ON DELETE CASCADE,
    FOREIGN KEY(script_id) REFERENCES script (id) ON DELETE CASCADE
)
""",
    """
CREATE TABLE test_result (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    run_id UUID NOT NULL,
    test_case_id UUID,
    test_adi TEXT NOT NULL,
    dosya TEXT,
    sonuc TEXT NOT NULL,
    sure_ms INTEGER,
    retry INTEGER DEFAULT '0' NOT NULL,
    commit TEXT,
    tetik TEXT NOT NULL,
    kaynak TEXT DEFAULT 'local' NOT NULL,
    hata_mesaji TEXT,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT test_result_sonuc_ck CHECK (sonuc IN ('failed', 'flaky', 'passed', 'skipped', 'timedout')),
    CONSTRAINT test_result_kaynak_ck CHECK (kaynak IN ('github', 'local', 'sauce')),
    CONSTRAINT test_result_tetik_ck CHECK (tetik IN ('break_verify', 'deploy', 'local_check', 'nightly', 'pr', 'push')),
    FOREIGN KEY(run_id) REFERENCES run (id) ON DELETE CASCADE,
    FOREIGN KEY(test_case_id) REFERENCES test_case (id)
)
""",
    "CREATE INDEX test_result_ad_ix ON test_result (test_adi)",
    "CREATE INDEX test_result_run_ix ON test_result (run_id)",
    """
CREATE TABLE failure (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    run_id UUID NOT NULL,
    test_result_id UUID,
    test_adi TEXT NOT NULL,
    hata_imzasi TEXT NOT NULL,
    sinif TEXT NOT NULL,
    alt_tur TEXT,
    eslesen_sinyaller JSONB DEFAULT '[]'::jsonb NOT NULL,
    karar_kaynagi TEXT DEFAULT 'rule' NOT NULL,
    gerekce TEXT,
    oneri_turu TEXT DEFAULT 'none' NOT NULL,
    oneri_durumu TEXT DEFAULT 'none' NOT NULL,
    ai_call_id UUID,
    uretim_modu TEXT,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT failure_sinif_ck CHECK (sinif IN ('environment', 'flaky', 'product_defect', 'test_data', 'test_maintenance', 'unknown')),
    CONSTRAINT failure_karar_kaynagi_ck CHECK (karar_kaynagi IN ('llm', 'rule')),
    CONSTRAINT failure_oneri_turu_ck CHECK (oneri_turu IN ('bug_draft', 'locator_fix', 'none')),
    CONSTRAINT failure_oneri_durumu_ck CHECK (oneri_durumu IN ('merged', 'none', 'pr_open', 'proposed', 'rejected')),
    CONSTRAINT failure_mod_ck CHECK (uretim_modu IS NULL OR uretim_modu IN ('live', 'replay', 'replay_miss')),
    FOREIGN KEY(run_id) REFERENCES run (id) ON DELETE CASCADE,
    FOREIGN KEY(test_result_id) REFERENCES test_result (id)
)
""",
    "CREATE INDEX failure_run_ix ON failure (run_id)",
    """
CREATE TABLE bug_draft (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    failure_id UUID,
    finding_id UUID,
    icerik JSONB NOT NULL,
    icerik_hash TEXT NOT NULL,
    mukerrer_adaylari JSONB DEFAULT '[]'::jsonb NOT NULL,
    karar TEXT,
    link_key TEXT,
    onaylayan_id UUID,
    onaylanan_hash TEXT,
    jira_key TEXT,
    durum TEXT DEFAULT 'draft' NOT NULL,
    ai_call_id UUID,
    uretim_modu TEXT,
    olusturma TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    guncelleme TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT bug_draft_karar_ck CHECK (karar IS NULL OR karar IN ('link', 'new')),
    CONSTRAINT bug_draft_durum_ck CHECK (durum IN ('approved', 'dismissed', 'draft', 'published')),
    CONSTRAINT bug_draft_mod_ck CHECK (uretim_modu IS NULL OR uretim_modu IN ('live', 'replay', 'replay_miss')),
    FOREIGN KEY(failure_id) REFERENCES failure (id),
    FOREIGN KEY(finding_id) REFERENCES consistency_finding (id),
    FOREIGN KEY(onaylayan_id) REFERENCES app_user (id)
)
""",
)

ALTER_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE script ADD CONSTRAINT script_failure_id_fkey "
    "FOREIGN KEY(failure_id) REFERENCES failure (id)",
)


JOB_DURUM_YENI = "durum IN ('cancelled', 'done', 'failed', 'queued', 'retry', 'running')"
JOB_DURUM_ESKI = "durum IN ('queued', 'running', 'done', 'failed')"


def _audit_zinciri() -> None:
    op.add_column("audit_event", sa.Column("prev_hash", sa.Text))
    op.add_column("audit_event", sa.Column("hash", sa.Text))
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE audit_event SET zaman = now() WHERE zaman IS NULL"))
    rows = conn.execute(
        sa.text("SELECT id, zaman, aktor, eylem, nesne, ozet FROM audit_event ORDER BY id")
    ).all()
    prev = GENESIS_HASH
    for r in rows:
        satir = {
            "id": r.id,
            "zaman": iso_utc(r.zaman),
            "aktor": r.aktor,
            "eylem": r.eylem,
            "nesne": r.nesne,
            "ozet": r.ozet,
        }
        h = chain_hash(prev, satir)
        conn.execute(
            sa.text("UPDATE audit_event SET prev_hash = :p, hash = :h WHERE id = :id"),
            {"p": prev, "h": h, "id": r.id},
        )
        prev = h
    op.alter_column("audit_event", "zaman", nullable=False)
    op.alter_column("audit_event", "prev_hash", nullable=False)
    op.alter_column("audit_event", "hash", nullable=False)
    op.create_unique_constraint("audit_event_prev_hash_key", "audit_event", ["prev_hash"])
    op.create_unique_constraint("audit_event_hash_key", "audit_event", ["hash"])


def _job_kuyrugu() -> None:
    op.drop_constraint("job_durum_ck", "job", type_="check")
    op.create_check_constraint("job_durum_ck", "job", JOB_DURUM_YENI)
    tz = sa.DateTime(timezone=True)
    op.add_column("job", sa.Column("max_deneme", sa.Integer))
    op.add_column("job", sa.Column("son_hata", sa.Text))
    op.add_column(
        "job", sa.Column("run_after", tz, nullable=False, server_default=sa.text("now()"))
    )
    op.add_column("job", sa.Column("idempotency_key", sa.Text))
    op.add_column("job", sa.Column("workflow_id", UUID(as_uuid=True)))
    op.add_column("job", sa.Column("sonuc", JSONB))
    op.add_column("job", sa.Column("kilitleyen", sa.Text))
    op.add_column("job", sa.Column("baslama", tz))
    op.add_column("job", sa.Column("bitis", tz))
    op.add_column(
        "job", sa.Column("zaman_asimi_s", sa.Integer, nullable=False, server_default="900")
    )
    op.execute("UPDATE job SET olusturma = now() WHERE olusturma IS NULL")
    op.execute("UPDATE job SET guncelleme = now() WHERE guncelleme IS NULL")
    op.alter_column("job", "olusturma", nullable=False)
    op.alter_column("job", "guncelleme", nullable=False)
    op.drop_index("job_kuyruk_ix", table_name="job")
    op.execute(
        "CREATE INDEX job_kuyruk_ix ON job (run_after, olusturma) "
        "WHERE durum IN ('queued', 'retry')"
    )
    op.execute(
        "CREATE UNIQUE INDEX job_idempotency_uq ON job (idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )


def upgrade() -> None:
    _audit_zinciri()
    op.execute("UPDATE app_user SET olusturma = now() WHERE olusturma IS NULL")
    op.alter_column("app_user", "olusturma", nullable=False)
    _job_kuyrugu()

    for stmt in CREATE_STATEMENTS:
        op.execute(stmt)
    for stmt in ALTER_STATEMENTS:
        op.execute(stmt)

    dml = [t for t in NEW_TABLES if t not in APPEND_ONLY]
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(dml)} TO tp_app")
    op.execute("GRANT SELECT, INSERT ON ai_call, tool_call, audit_event TO tp_app")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON ai_call, tool_call, audit_event FROM tp_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tp_app")

    op.execute(
        """
CREATE FUNCTION tp_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% append-only: % yasak', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END
$$"""
    )
    for t in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t} "
            "FOR EACH ROW EXECUTE FUNCTION tp_append_only()"
        )
        op.execute(
            f"CREATE TRIGGER {t}_no_truncate BEFORE TRUNCATE ON {t} "
            "FOR EACH STATEMENT EXECUTE FUNCTION tp_append_only()"
        )


def downgrade() -> None:
    for t in APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS {t}_no_truncate ON {t}")
        op.execute(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t}")
    op.execute("DROP FUNCTION IF EXISTS tp_append_only()")

    op.execute("ALTER TABLE script DROP CONSTRAINT IF EXISTS script_failure_id_fkey")
    for t in reversed(NEW_TABLES):
        op.drop_table(t)

    op.drop_index("job_idempotency_uq", table_name="job")
    op.drop_index("job_kuyruk_ix", table_name="job")
    for kolon in (
        "zaman_asimi_s",
        "bitis",
        "baslama",
        "kilitleyen",
        "sonuc",
        "workflow_id",
        "idempotency_key",
        "run_after",
        "son_hata",
        "max_deneme",
    ):
        op.drop_column("job", kolon)
    op.alter_column("job", "olusturma", nullable=True)
    op.alter_column("job", "guncelleme", nullable=True)
    op.drop_constraint("job_durum_ck", "job", type_="check")
    op.execute("UPDATE job SET durum = 'failed' WHERE durum IN ('retry', 'cancelled')")
    op.create_check_constraint("job_durum_ck", "job", JOB_DURUM_ESKI)
    op.create_index(
        "job_kuyruk_ix", "job", ["olusturma"], postgresql_where=sa.text("durum = 'queued'")
    )

    op.alter_column("app_user", "olusturma", nullable=True)
    op.drop_constraint("audit_event_hash_key", "audit_event", type_="unique")
    op.drop_constraint("audit_event_prev_hash_key", "audit_event", type_="unique")
    op.drop_column("audit_event", "hash")
    op.drop_column("audit_event", "prev_hash")
    op.alter_column("audit_event", "zaman", nullable=True)
