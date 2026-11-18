"""Platform başına depo (platform-depo ANALIZ §3.2, Şerit T2): PR numarası depolar arasında
çakışır; her yerde (depo, numara).

- `PullRequest.anahtar(no, depo)` ve `script_for_pr(..., depo=)` başka deponun aynı numaralı
  PR'ını bulmaz.
- `sync_prs` açık PR'ları kayıtlı depolarına göre gruplar; her grup kendi forge'uyla okunur ve
  check kopyası doğru PR kaydına yazılır. Bir deponun forge'u kurulamazsa yalnız o deponun
  satırları `hata` sayılır (`codegen.pr_sync_failed`, `depo` alanıyla).
- Ayrı depoda merge kapısının kapalı tarafı `web-java` eklemez (merge kilidi yok).
- API: `?depo=` biçim dışıysa 422; boş/eksik = varsayılan depo.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, select, text

from tp_core.features.codegen import depo as depolar
from tp_core.features.codegen import service, views
from tp_core.models import AuditEvent, PullRequest, Script, session_scope
from tp_core.ports import CheckRun
from tp_core.ports import PullRequest as PortPR

MOBIL = "acme/mobil-android"


def _pr_script(no: int, depo: str, platform: str = "android") -> uuid.UUID:
    head = uuid.uuid4().hex + "00000000"
    dal = f"tp/case-{platform}-{uuid.uuid4()}"
    with session_scope() as s:
        sc = Script(
            tur="test",
            dosya_yolu=f"e2e-app/src/test/java/X{no}Test.java",
            branch=dal,
            platform=platform,
            dil="java",
            depo=depo,
        )
        s.add(sc)
        s.flush()
        s.execute(
            text("UPDATE script SET durum = 'pr_open', pr_no = :n, head_sha = :h WHERE id = :i"),
            {"n": no, "h": head, "i": sc.id},
        )
        s.add(
            PullRequest(
                number=no, depo=depo, branch=dal, baslik=f"PR {depo}", head_sha=head, acan="tp-bot"
            )
        )
        return sc.id


class _Forge:
    def __init__(self, ad: str, heads: dict[int, str]) -> None:
        self.ad = ad
        self.heads = heads

    def get_pr(self, number: int) -> PortPR:
        return PortPR(
            number=number,
            branch="b",
            title="t",
            head_sha=self.heads[number],
            state="open",
        )

    def checks(self, sha: str) -> list[CheckRun]:
        return [CheckRun(name=f"chk-{self.ad}", status="completed", conclusion="success")]


def test_anahtar_depoyu_tasir() -> None:
    _pid, depo, no = PullRequest.anahtar(5, MOBIL)
    assert (depo, no) == (MOBIL, 5)
    assert PullRequest.anahtar(5)[1:] == ("", 5)  # varsayılan depo (geriye uyum)


def test_ayni_numarali_pr_iki_depoda_karismaz(engine: Engine) -> None:
    varsayilan = _pr_script(41, "", platform="web")
    mobil = _pr_script(41, MOBIL)
    with session_scope() as s:
        assert service.script_for_pr(s, 41).id == varsayilan
        assert service.script_for_pr(s, 41, depo=MOBIL).id == mobil
        with pytest.raises(service.ScriptNotFound):
            service.script_for_pr(s, 41, depo="acme/baska")
        assert s.get(PullRequest, PullRequest.anahtar(41)).baslik == "PR "
        assert s.get(PullRequest, PullRequest.anahtar(41, MOBIL)).baslik == f"PR {MOBIL}"
        sc = s.get(Script, mobil)
        assert views.script_pr_kaydi(sc).depo == MOBIL


def test_sync_prs_her_depoyu_kendi_forgeuyla_okur(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    varsayilan = _pr_script(7, "", platform="web")
    mobil = _pr_script(7, MOBIL)
    with session_scope() as s:
        h_v = s.get(Script, varsayilan).head_sha
        h_m = s.get(Script, mobil).head_sha
    forgelar = {"": _Forge("web", {7: h_v}), MOBIL: _Forge("mobil", {7: h_m})}
    istenen: list[tuple[str, str | None]] = []

    def forge_depo(depo: str | None, platform: str | None = None) -> Any:
        istenen.append((depo or "", platform))
        return forgelar[depo or ""]

    monkeypatch.setattr(service, "_forge_depo", forge_depo)
    monkeypatch.setattr(service, "_depo_tanimsiz", lambda: False)
    sonuc = service.sync_prs(engine)
    assert sonuc["bakilan"] == 2 and sonuc["hata"] == 0 and sonuc["checks"] == 2
    # Depo başına tek forge (tur içinde önbellek); platform ipucu script'ten.
    assert sorted(istenen) == [("", "web"), (MOBIL, "android")]
    with session_scope() as s:
        assert [c["name"] for c in s.get(PullRequest, PullRequest.anahtar(7)).checks] == ["chk-web"]
        assert [c["name"] for c in s.get(PullRequest, PullRequest.anahtar(7, MOBIL)).checks] == [
            "chk-mobil"
        ]


def test_sync_prs_kurulamayan_depo_digerlerini_durdurmaz(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    varsayilan = _pr_script(8, "", platform="web")
    mobil = _pr_script(8, MOBIL)
    with session_scope() as s:
        h_v = s.get(Script, varsayilan).head_sha

    def forge_depo(depo: str | None, platform: str | None = None) -> Any:
        if depo:
            raise RuntimeError("token bu depoya erişemiyor")
        return _Forge("web", {8: h_v})

    monkeypatch.setattr(service, "_forge_depo", forge_depo)
    monkeypatch.setattr(service, "_depo_tanimsiz", lambda: False)
    sonuc = service.sync_prs(engine)
    assert sonuc["bakilan"] == 2 and sonuc["hata"] == 1 and sonuc["checks"] == 1
    with session_scope() as s:
        ozet = s.scalars(
            select(AuditEvent.ozet).where(
                AuditEvent.eylem == "codegen.pr_sync_failed",
                AuditEvent.nesne == f"script:{mobil}",
            )
        ).one()
    assert ozet["depo"] == MOBIL and ozet["pr"] == 8


def test_ayri_depoda_kapali_taraf_web_java_eklemez() -> None:
    kayit = PullRequest(number=1, depo=MOBIL, branch="b", baslik="t", head_sha="s", acan="x")
    assert "web-java" not in views.github_kapi_zorunlu(("mobil-android",), kayit)
    varsayilan = PullRequest(number=1, depo="", branch="b", baslik="t", head_sha="s", acan="x")
    assert "web-java" in views.github_kapi_zorunlu(("test-local",), varsayilan)


@pytest.mark.parametrize(
    ("girdi", "beklenen"),
    [("", ""), ("  Acme/Mobil-Android ", MOBIL), ("/acme/x/", "acme/x")],
)
def test_depo_normalize(girdi: str, beklenen: str) -> None:
    d = depolar.normalize(girdi)
    assert d == beklenen and depolar.gecerli_mi(d)


@pytest.mark.parametrize("girdi", ["acme", "acme/x/y", "../x", "acme/x y"])
def test_depo_gecersiz(girdi: str) -> None:
    assert not depolar.gecerli_mi(depolar.normalize(girdi))


def test_depo_alanlari_varsayilan_ve_ayri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(depolar, "depo_adi", lambda d: d or "acme/demo-app")
    assert views.depo_alanlari("") == {"depo": "", "depo_adi": "acme/demo-app"}
    assert views.depo_alanlari(MOBIL) == {"depo": MOBIL, "depo_adi": MOBIL}
