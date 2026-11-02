"""GitHub kipi son yeşil aria kanıtı: `test-local-results` artefaktındaki `<sayfa>.aria.yml` →
`run_aria` (0016). Locator onarımı GitHub koşusunda koşu dizini olmadığı için bu kopyayı okur.

Fikstür (`fixtures/github_artifact_yesil/`) gerçek yeşil bir GitHub koşusunun artefakt düzenidir
(küçültülmüş: yalnızca katalog + sepet snapshot'ları; giriş sayfası test girdisi taşıdığı için
alınmadı): `artifacts/<locators testi>/<sayfa>.aria.yml`.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import FIXTURES, SHA
from tests.unit.features.ci.test_github import REPO, FakeGitHub
from tp_core.features.ci import __main__ as ci_cli
from tp_core.features.ci import enqueue_ci, service, services
from tp_core.features.ci.clients import GitHubCi, _zip_dosyalari
from tp_core.features.ci.parse import (
    MAX_ARIA_DOSYA_BAYT,
    MAX_ARIA_DOSYA_SAYI,
    aria_dosyalari,
    aria_dosyasi_mi,
)
from tp_core.integrations.forge_github import GitHubForge, TokenAuth
from tp_core.models import AuditEvent, Run
from tp_core.models.ci_feature import RunAria

YESIL = FIXTURES / "github_artifact_yesil"
HATA = FIXTURES / "github_artifact"
TEST_DIZINI = "artifacts/locators-locators-ts-rol-a-97cb9--sepet-ve-sipariş-sayfaları-chromium"


def _dosyalar(kok: Path, onek: str = "") -> dict[str, bytes]:
    return {
        onek + p.relative_to(kok).as_posix(): p.read_bytes()
        for p in sorted(kok.rglob("*"))
        if p.is_file()
    }


def _zip(dosyalar: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for ad, icerik in dosyalar.items():
            zf.writestr(ad, icerik)
    return buf.getvalue()


# ------------------------------------------------------------------------------- seçim


def test_aria_dosyasi_kaliplari() -> None:
    assert aria_dosyasi_mi("katalog.aria.yml") and aria_dosyasi_mi("x.aria")
    assert aria_dosyasi_mi("sayfa-aria.yaml")
    assert not aria_dosyasi_mi("error-context.md") and not aria_dosyasi_mi("results.json")


def test_artefakttan_aria_dosyalari_secilir() -> None:
    secilen = dict(aria_dosyalari({**_dosyalar(HATA), **_dosyalar(YESIL)}))
    assert sorted(secilen) == [f"{TEST_DIZINI}/katalog.aria.yml", f"{TEST_DIZINI}/sepet.aria.yml"]
    assert '- button "Sepete ekle"' in secilen[f"{TEST_DIZINI}/katalog.aria.yml"]


def test_aria_secimi_guvenilmeyen_girdiye_karsi_sinirli() -> None:
    iyi = b'- button "A"\n'
    secilen = dict(
        aria_dosyalari(
            {
                "/abs/a.aria.yml": iyi,
                "../kacis/b.aria.yml": iyi,
                "t/bos.aria.yml": b"",
                "t/buyuk.aria.yml": b"x" * (MAX_ARIA_DOSYA_BAYT + 1),
                "t/ikili.aria.yml": b"\xff\xfe\x00",
                "t/renkli.aria.yml": b'- button "B"\x1b[31m\x00\n',
                "t\\ters.aria.yml": iyi,
            }
        )
    )
    assert secilen == {"t/renkli.aria.yml": '- button "B"\n', "t/ters.aria.yml": iyi.decode()}
    cok = {f"t/{i:03d}.aria.yml": iyi for i in range(MAX_ARIA_DOSYA_SAYI + 5)}
    assert len(aria_dosyalari(cok)) == MAX_ARIA_DOSYA_SAYI


def test_zip_ek_kaliplari_aria_dosyalarini_okur() -> None:
    veri = _zip({**_dosyalar(HATA), **_dosyalar(YESIL)})
    out = _zip_dosyalari(veri, ("results.json",), service.EK_KALIPLARI)
    assert f"{TEST_DIZINI}/katalog.aria.yml" in out and f"{TEST_DIZINI}/sepet.aria.yml" in out
    assert sum(1 for k in out if k.endswith("error-context.md")) == 4
    # Yalnızca aria kalıbı: rapor ve hata bağlamı okunmaz.
    yalniz = _zip_dosyalari(veri, (), ("*aria*.yml",))
    assert sorted(yalniz) == [f"{TEST_DIZINI}/katalog.aria.yml", f"{TEST_DIZINI}/sepet.aria.yml"]


# ------------------------------------------------------------------- GitHub içe aktarımı


class YesilGitHub(FakeGitHub):
    """Sonuç artefaktı gerçek düzende: results.json + aria snapshot'ları (yeşil koşu)."""

    def handler(self, req: httpx.Request) -> httpx.Response:
        if req.url.host == "blob.example" and req.url.path.endswith("/sonuc.zip"):
            self.istekler.append(req)
            dosyalar = {
                "results.json": (FIXTURES / "results.json").read_bytes(),
                "junit.xml": (FIXTURES / "junit.xml").read_bytes(),
                "ci-meta.json": json.dumps({"tetik": "push", "sha": SHA}).encode(),
                **_dosyalar(YESIL),
            }
            return httpx.Response(200, content=_zip(dosyalar))
        return super().handler(req)


@pytest.fixture
def ygh(engine: Engine, artefakt_kok):
    fake = YesilGitHub()
    forge = GitHubForge(
        REPO,
        TokenAuth("gh-test-token"),
        api_url="https://api.github.test",
        transport=httpx.MockTransport(fake.handler),
    )
    with services.override(
        mode=lambda: "github",
        forge=lambda: forge,
        github=lambda: GitHubCi(forge),
        artifacts_root=lambda: artefakt_kok,
    ):
        yield fake


def _arialar(engine: Engine, rid: uuid.UUID) -> dict[str, RunAria]:
    with Session(engine) as s:
        rows = s.scalars(select(RunAria).where(RunAria.run_id == rid)).all()
        for r in rows:
            s.expunge(r)
        return {r.ad: r for r in rows}


def _ingest(engine: Engine, ygh: YesilGitHub, wid: int) -> uuid.UUID:
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "push", None)
    ygh.wr(wid, "push", conclusion="success")
    service.github_poll(engine, rid, 0)
    return rid


def test_github_ingest_aria_snapshotlarini_yazar(engine: Engine, ygh: YesilGitHub) -> None:
    rid = _ingest(engine, ygh, 400)
    a = _arialar(engine, rid)
    assert sorted(a) == ["katalog.aria.yml", "sepet.aria.yml"]
    k = a["katalog.aria.yml"]
    assert k.yol == f"{TEST_DIZINI}/katalog.aria.yml" and k.kaynak == "github_artefakt"
    assert k.boyut == len(k.icerik.encode()) and '- button "Sepete ekle"' in k.icerik
    with Session(engine) as s:
        run = s.get(Run, rid)
        assert run is not None and "dizin" not in run.artefaktlar
        assert run.artefaktlar["github"]["aria_dosya"] == 2


def test_aria_geri_doldurma_idempotent_ve_denetlenir(engine: Engine, ygh: YesilGitHub) -> None:
    """0016 öncesi içe aktarılan koşu: run_aria boş → artefakttan doldurulur; ikinci kez no-op."""
    rid = _ingest(engine, ygh, 401)
    with Session(engine) as s, s.begin():
        s.execute(RunAria.__table__.delete().where(RunAria.run_id == rid))
    with Session(engine) as s, s.begin():
        run = s.get(Run, rid)
        assert run is not None
        sonuc = service.github_aria_doldur(s, run, "operator")
    assert (sonuc["bulunan"], sonuc["eklenen"]) == (2, 2)
    a = _arialar(engine, rid)
    assert {r.kaynak for r in a.values()} == {"github_artefakt_geri_doldurma"}
    with Session(engine) as s, s.begin():
        run = s.get(Run, rid)
        assert service.github_aria_doldur(s, run)["eklenen"] == 0
    assert len(_arialar(engine, rid)) == 2
    with Session(engine) as s:
        kayit = s.scalars(
            select(AuditEvent).where(
                AuditEvent.eylem == "ci.aria_snapshots_backfilled",
                AuditEvent.nesne == f"run:{rid}",
            )
        ).all()
        assert len(kayit) == 2 and kayit[0].aktor == "operator"


def test_yerel_kosu_aria_geri_doldurulamaz(engine: Engine, ygh: YesilGitHub) -> None:
    with Session(engine) as s, s.begin():
        run = Run(kaynak="local", tetik="push", sonuc="passed", commit=SHA)
        s.add(run)
        s.flush()
        with pytest.raises(service.CiError):
            service.github_aria_doldur(s, run)


def test_cli_aria_doldur_onekle(
    engine: Engine, ygh: YesilGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    rid = _ingest(engine, ygh, 402)
    with Session(engine) as s, s.begin():
        s.execute(RunAria.__table__.delete().where(RunAria.run_id == rid))
    assert ci_cli.main(["aria-doldur", str(rid)[:13]]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["tamam"] and out["eklenen"] == 2 and out["run_id"] == str(rid)
    assert ci_cli.main(["aria-doldur", str(rid)]) == 0
    assert json.loads(capsys.readouterr().out)["eklenen"] == 0
    assert ci_cli.main(["aria-doldur", str(uuid.uuid4())]) == ci_cli.RED_KODU
    assert ci_cli.main(["aria-doldur", "x'; --"]) == ci_cli.RED_KODU
