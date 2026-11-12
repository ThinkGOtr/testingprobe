"""GitHub kipi PR check kopyası (0014): worker senkronu yazar, core-api görünümü/kapısı okur.

- core-api GitHub'a erişmez; `sync_prs` açık PR'ların head check'lerini `pull_request.checks`'e
  LocalForge biçiminde ({name, status, conclusion, url}) yazar.
- `views.pr_checks`: GitHub kipinde DB kopyası, LocalForge kipinde `checks/<sha>.json`.
- Kopya yok ya da `checks_sha` güncel head değil → zorunlu check'ler `pending` (asla `passed`).
- Merge kapısı (`merge_engelleri`) iki kipte de aynı zorunlu check kuralını uygular.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, create_engine, text

from tests.unit.conftest import Db, run_alembic
from tp_core.config import get_settings
from tp_core.features.codegen import service, views
from tp_core.integrations.forge import ForgeError
from tp_core.models import Base, PullRequest, Script, session_scope
from tp_core.ports import CheckRun
from tp_core.ports import PullRequest as PortPR

YESIL = [
    {"name": ad, "status": "completed", "conclusion": "success", "url": f"https://gh/{ad}"}
    for ad in ("test-local", "ast-guard", "semgrep")
]


@pytest.fixture
def kip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Any]:
    def ayarla(forge: str) -> None:
        monkeypatch.setenv("TP_FORGE", forge)
        get_settings.cache_clear()

    monkeypatch.setenv("TP_ARTIFACTS_PATH", str(tmp_path))
    monkeypatch.delenv("TP_CHECKS_PATH", raising=False)
    monkeypatch.delenv("TP_REQUIRED_CHECKS", raising=False)
    yield ayarla
    get_settings.cache_clear()


class CheckForge:
    """Yalnızca `sync_prs`'in açık PR yolunun kullandığı ForgePort yüzeyi."""

    def __init__(self) -> None:
        self.prs: dict[int, PortPR] = {}
        self.by_sha: dict[str, list[CheckRun]] = {}
        self.okunan: list[str] = []
        self.patlat = False

    def get_pr(self, number: int) -> PortPR:
        return self.prs[number]

    def checks(self, sha: str) -> list[CheckRun]:
        self.okunan.append(sha)
        if self.patlat:
            raise ForgeError("GitHub 502")
        return list(self.by_sha.get(sha, []))


def _acik_pr(no: int, head: str) -> uuid.UUID:
    with session_scope() as s:
        sc = Script(tur="test", dosya_yolu=f"e2e/tests/generated/{no}.spec.ts", branch=f"tp/{no}")
        s.add(sc)
        s.flush()
        s.execute(
            text("UPDATE script SET durum = 'pr_open', pr_no = :n, head_sha = :h WHERE id = :i"),
            {"n": no, "h": head, "i": sc.id},
        )
        s.add(PullRequest(number=no, branch=f"tp/{no}", baslik="t", head_sha=head, acan="tp-bot"))
        return sc.id


def _sha() -> str:
    return uuid.uuid4().hex + "abcdef01"


def _kayit(no: int) -> PullRequest:
    with session_scope() as s:
        k = s.get(PullRequest, no)
        assert k is not None
        s.expunge(k)
        return k


# ---------------------------------------------------------------- worker senkronu


def test_sync_prs_acik_pr_checklerini_kaydeder(engine: Engine) -> None:
    head = _sha()
    _acik_pr(501, head)
    gh = CheckForge()
    gh.prs[501] = PortPR(number=501, branch="tp/501", title="t", body="", head_sha=head, url="u")
    gh.by_sha[head] = [CheckRun.model_validate(c) for c in YESIL]

    sonuc = service.sync_prs(engine, gh)

    assert sonuc["checks"] == 1 and sonuc["hata"] == 0
    k = _kayit(501)
    assert k.checks == YESIL and k.checks_sha == head and k.checks_zaman is not None
    ilk_zaman = k.checks_zaman
    # Değişmeyen check'ler yeniden yazılmaz.
    assert service.sync_prs(engine, gh)["checks"] == 0
    assert _kayit(501).checks_zaman == ilk_zaman

    # Dal güncellendi (yeni head) → yeni head'in check'leri yazılır.
    yeni = _sha()
    gh.prs[501] = gh.prs[501].model_copy(update={"head_sha": yeni})
    gh.by_sha[yeni] = [CheckRun(name="test-local", status="in_progress")]
    assert service.sync_prs(engine, gh)["checks"] == 1
    k = _kayit(501)
    assert k.checks_sha == yeni
    assert k.checks == [
        {"name": "test-local", "status": "in_progress", "conclusion": None, "url": None}
    ]


def test_check_okuma_hatasi_senkronu_durdurmaz(engine: Engine) -> None:
    head = _sha()
    _acik_pr(502, head)
    gh = CheckForge()
    gh.prs[502] = PortPR(number=502, branch="tp/502", title="t", body="", head_sha=head, url="u")
    gh.patlat = True
    sonuc = service.sync_prs(engine, gh)
    assert sonuc["bakilan"] == 1 and sonuc["checks"] == 0 and sonuc["hata"] == 0
    assert _kayit(502).checks is None


# ---------------------------------------------------------------- core-api görünümü


def test_github_kipinde_db_kopyasi_okunur(engine: Engine, kip: Any) -> None:
    kip("github")
    head = _sha()
    k = PullRequest(number=1, branch="b", baslik="t", head_sha=head, acan="x",
                    checks=[*YESIL, {"name": "sauce", "status": "completed",
                                     "conclusion": "failure", "url": None}],
                    checks_sha=head)  # fmt: skip
    liste, ci, engeller = views.pr_checks(head, k)
    assert ci == "passed" and engeller == []
    durum = {c["ad"]: (c["durum"], c["zorunlu"]) for c in liste}
    assert durum["test-local"] == ("passed", True)
    assert durum["sauce"] == ("failed", False)  # Sauce zorunlu değil: kapıyı etkilemez

    k.checks = [{**YESIL[0], "conclusion": "failure"}, *YESIL[1:]]
    _, ci, engeller = views.pr_checks(head, k)
    assert ci == "failed" and engeller == ["Zorunlu kontrol 'test-local': failed"]


def test_github_kipinde_bayat_ya_da_eksik_kopya_pending(engine: Engine, kip: Any) -> None:
    kip("github")
    head, eski = _sha(), _sha()
    bayat = PullRequest(number=1, branch="b", baslik="t", head_sha=head, acan="x",
                        checks=YESIL, checks_sha=eski)  # fmt: skip
    for kayit in (bayat, PullRequest(number=2, branch="b", baslik="t", head_sha=head, acan="x"),
                  None):  # fmt: skip
        liste, ci, engeller = views.pr_checks(head, kayit)
        assert ci == "pending"
        assert {c["ad"]: c["durum"] for c in liste} == {
            "test-local": "pending", "ast-guard": "pending", "semgrep": "pending",
        }  # fmt: skip
        assert engeller == [
            "Zorunlu kontrol 'test-local': pending",
            "Zorunlu kontrol 'ast-guard': pending",
            "Zorunlu kontrol 'semgrep': pending",
        ]


def test_local_kipinde_dosya_okunur_db_kopyasi_yok_sayilir(
    engine: Engine, kip: Any, tmp_path: Path
) -> None:
    kip("local")
    head = _sha()
    (tmp_path / "checks").mkdir()
    (tmp_path / "checks" / f"{head}.json").write_text(
        json.dumps({"checks": [{"name": "local-ci", "status": "completed",
                                "conclusion": "success", "url": None}]}),
        encoding="utf-8",
    )  # fmt: skip
    k = PullRequest(number=1, branch="b", baslik="t", head_sha=head, acan="x",
                    checks=[{"name": "local-ci", "status": "completed", "conclusion": "failure"}],
                    checks_sha=head)  # fmt: skip
    liste, ci, engeller = views.pr_checks(head, k)
    assert ci == "passed" and engeller == [] and [c["ad"] for c in liste] == ["local-ci"]
    # Dosya yoksa (LocalForge davranışı değişmedi): ci yok, zorunlu check 'yok'.
    _, ci, engeller = views.pr_checks(_sha(), k)
    assert ci is None and engeller == ["Zorunlu kontrol 'local-ci': yok"]


def test_merge_kapisi_github_kipinde_db_kopyasini_kullanir(engine: Engine, kip: Any) -> None:
    kip("github")
    head = _sha()
    sid = _acik_pr(503, head)
    cg = SimpleNamespace(break_durum="passed", dal={})
    with session_scope() as s:
        sc = s.get(Script, sid)
        assert any("pending" in e for e in views.merge_engelleri(sc, cg))
        k = s.get(PullRequest, 503)
        k.checks, k.checks_sha = YESIL, head
        s.flush()
        assert views.merge_engelleri(sc, cg) == []
        k.checks_sha = _sha()  # dal güncellendi, senkron henüz koşmadı
        s.flush()
        assert views.merge_engelleri(sc, cg) == [
            "Zorunlu kontrol 'test-local': pending",
            "Zorunlu kontrol 'ast-guard': pending",
            "Zorunlu kontrol 'semgrep': pending",
        ]


# ------------------------------------------------- platform başına kapı (009, Ş6b)

APP_DOSYA = "e2e-app/src/test/java/com/antreklabs/bayi/uretilen/TPD1AndroidC2_0a1b2c3dTest.java"


def _checks_yaz(tmp_path: Path, head: str, checks: list[dict[str, Any]]) -> None:
    (tmp_path / "checks").mkdir(exist_ok=True)
    (tmp_path / "checks" / f"{head}.json").write_text(json.dumps({"checks": checks}))


def test_local_uygulama_pr_platform_kontrolu_ister_merge_pr_ile_ayni(
    engine: Engine, kip: Any, tmp_path: Path
) -> None:
    """Portal `forge.local_required_checks`'i kullanır: yalnız e2e-app/ değiştiren Android PR'ı
    web `local-ci` yerine `local-ci-android` ister; kayıt yokken de bekler ("yok")."""
    from tp_core.integrations.forge import local_required_checks

    kip("local")
    head = _sha()
    yollar = [APP_DOSYA]
    # Henüz hiç kontrol yok: platform kontrolü zorunlu ve 'yok'.
    _, ci, engeller = views.pr_checks(head, None, degisen=yollar, platform="android")
    assert "Zorunlu kontrol 'local-ci-android': yok" in engeller
    # Koşuyor (toolchain başta in_progress yazar).
    koşan = [{"name": "local-ci-android", "status": "in_progress", "conclusion": None}]
    _checks_yaz(tmp_path, head, koşan)
    _, ci, engeller = views.pr_checks(head, None, degisen=yollar, platform="android")
    assert ci == "pending" and engeller == ["Zorunlu kontrol 'local-ci-android': pending"]
    # Yeşil: web local-ci kaydı olmadan merge edilebilir (LocalForge kapısıyla aynı).
    yesil = [{"name": "local-ci-android", "status": "completed", "conclusion": "success"}]
    _checks_yaz(tmp_path, head, yesil)
    liste, ci, engeller = views.pr_checks(head, None, degisen=yollar, platform="android")
    assert ci == "passed" and engeller == []
    assert [(c["ad"], c["zorunlu"]) for c in liste] == [("local-ci-android", True)]
    zorunlu, neden = local_required_checks(
        ("local-ci",), [CheckRun(name="local-ci-android", status="completed",
                                 conclusion="success")], yollar
    )  # fmt: skip
    assert zorunlu == ("local-ci-android",) and neden is None
    # Kayıtlı kırmızı web local-ci de durdurur (simetri).
    _checks_yaz(tmp_path, head, [*yesil, {"name": "local-ci", "status": "completed",
                                          "conclusion": "failure"}])  # fmt: skip
    _, ci, engeller = views.pr_checks(head, None, degisen=yollar, platform="android")
    assert ci == "failed" and engeller == ["Zorunlu kontrol 'local-ci': failed"]


def test_local_web_pr_davranisi_degismez(engine: Engine, kip: Any, tmp_path: Path) -> None:
    kip("local")
    head = _sha()
    _checks_yaz(tmp_path, head, [{"name": "local-ci", "status": "completed",
                                  "conclusion": "success"}])  # fmt: skip
    yollar = ["e2e/tests/generated/TPD1C2_0a1b2c3d.spec.ts"]
    _, ci, engeller = views.pr_checks(head, None, degisen=yollar, platform="web")
    assert ci == "passed" and engeller == []


def test_merge_engelleri_uygulama_scripti(engine: Engine, kip: Any, tmp_path: Path) -> None:
    kip("local")
    head = _sha()
    with session_scope() as s:
        sc = Script(tur="test", dosya_yolu=APP_DOSYA, branch="tp/case-android-x",
                    platform="android")  # fmt: skip
        s.add(sc)
        s.flush()
        s.execute(
            text("UPDATE script SET durum = 'pr_open', pr_no = 611, head_sha = :h WHERE id = :i"),
            {"h": head, "i": sc.id},
        )
        s.refresh(sc)
        cg = SimpleNamespace(break_durum="passed", dal={})
        assert views.merge_engelleri(sc, cg) == ["Zorunlu kontrol 'local-ci-android': yok"]
        _checks_yaz(tmp_path, head, [{"name": "local-ci-android", "status": "completed",
                                      "conclusion": "success"}])  # fmt: skip
        assert views.merge_engelleri(sc, cg) == []


def test_github_platform_checkleri_tp_platforms(
    engine: Engine, kip: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    kip("github")
    assert views.required_checks() == ("test-local", "ast-guard", "semgrep")
    monkeypatch.setenv("TP_PLATFORMS", "android, windows,web")
    assert views.required_checks() == (
        "test-local", "ast-guard", "semgrep", "mobil-android", "masaustu-windows",
    )  # fmt: skip
    monkeypatch.setenv("TP_PLATFORMS", "symbian")
    assert views.required_checks() == ("test-local", "ast-guard", "semgrep")
    # Geçersiz yapılandırma portalda engel olarak görünür (GitHubForge de kurulamaz).
    _, _, engeller = views.pr_checks(_sha(), None)
    assert any(e.startswith("Yapılandırma hatası") for e in engeller)
    kip("local")
    monkeypatch.setenv("TP_PLATFORMS", "android")
    assert views.required_checks() == ("local-ci",)


def test_github_web_java_checki_tp_web_dilleri(
    engine: Engine, kip: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OPS-O1: portal zorunlu listesi GitHubForge ile aynı (`TP_WEB_DILLERI` java → `web-java`);
    geçersiz değer portalda engel olarak görünür."""
    kip("github")
    monkeypatch.delenv("TP_PLATFORMS", raising=False)
    monkeypatch.setenv("TP_WEB_DILLERI", "ts,java")
    assert views.required_checks() == ("test-local", "ast-guard", "semgrep", "web-java")
    monkeypatch.setenv("TP_WEB_DILLERI", "csharp")
    assert views.required_checks() == ("test-local", "ast-guard", "semgrep")
    _, _, engeller = views.pr_checks(_sha(), None)
    assert any(e.startswith("Yapılandırma hatası") for e in engeller)


# ---------------------------------------------------------------- migrasyon

KOLONLAR = ("checks", "checks_sha", "checks_zaman")


def _farklar(url: str) -> list[object]:
    eng = create_engine(url)
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        farklar = compare_metadata(ctx, Base.metadata)
    eng.dispose()
    return [f for f in farklar if "pull_request" in repr(f)]


def _kolonlar(url: str) -> set[str]:
    with psycopg.connect(url.replace("+psycopg", ""), autocommit=True) as c:
        rows = c.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'pull_request'"
        ).fetchall()
    return {r[0] for r in rows}


def test_0014_model_sema_ayni_ve_tp_app_yazabilir(db: Db) -> None:
    assert _farklar(db.owner_url) == []
    with psycopg.connect(db.app_url.replace("+psycopg", ""), autocommit=True) as c:
        c.execute(
            "INSERT INTO pull_request (branch, baslik, head_sha, acan) VALUES ('b','t','s','x')"
        )
        c.execute(
            "UPDATE pull_request SET checks = '[]'::jsonb, checks_sha = 's', checks_zaman = now()"
        )


def test_0014_downgrade_upgrade(db: Db) -> None:
    with psycopg.connect(db.owner_url.replace("+psycopg", ""), autocommit=True) as c:
        c.execute(
            "INSERT INTO pull_request (branch, baslik, head_sha, acan, checks, checks_sha) "
            "VALUES ('b','t','s','x','[]'::jsonb,'s')"
        )
    run_alembic(db.owner_url, "0013", "downgrade")
    assert not set(KOLONLAR) & _kolonlar(db.owner_url)
    run_alembic(db.owner_url, "head")
    assert set(KOLONLAR) <= _kolonlar(db.owner_url)
    assert _farklar(db.owner_url) == []


def test_github_kipinde_web_java_check_kostuysa_zorunlu(
    engine: Engine, kip: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """K-T10: `web-java` iş akışı depodaysa (check'i koştu) TP_WEB_DILLERI'nden bağımsız zorunlu
    (GitHubForge.zorunlu_checkler ile aynı); kırmızı `web-java` merge'i durdurur."""
    kip("github")
    monkeypatch.delenv("TP_WEB_DILLERI", raising=False)
    head = _sha()
    web_java = {"name": "web-java", "status": "completed", "conclusion": "failure", "url": None}
    k = PullRequest(number=1, branch="b", baslik="t", head_sha=head, acan="x",
                    checks=[*YESIL, web_java], checks_sha=head)  # fmt: skip
    liste, _, engeller = views.pr_checks(head, k)
    assert {c["ad"]: c["zorunlu"] for c in liste}["web-java"] is True
    assert engeller == ["Zorunlu kontrol 'web-java': failed"]
    k.checks = [*YESIL, {**web_java, "conclusion": "success"}]
    assert views.pr_checks(head, k)[2] == []
    # Check hiç koşmadıysa (iş akışı yok) zorunlu listeye eklenmez.
    k.checks = list(YESIL)
    assert views.pr_checks(head, k)[2] == []
