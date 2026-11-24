"""T1 (03-api-kimlik-taramasi): core-api'de senkron dış çağrı koruması.

Canlıda GitHub bağlantısı App, Jira bağlantısı OAuth kipindedir; bağlantı token'ları yalnız
`TP_BAGLANTI_TOKENI=1` taşıyan core-worker'da alınabilir (security-check 8). core-api'den forge /
Jira / Xray istemcisi kurmaya çalışan her yol canlıda kırılır (çoğu zaman sessizce: hata yutulur),
ama yerelde/token kipinde testler yeşil geçer. Bu test o sınıfı CI'da kırmızı yapar:

- süreç core-api gibi kurulur (`TP_BAGLANTI_TOKENI` yok, `baglanti_kipi`: github=app, jira=oauth;
  test fabrikası/sahte istemci yok),
- forge / Jira / Xray / GitHub Actions istemcisi kuran fabrikalar ve bağlantı token'ı alan
  fonksiyonlar tuzakla değiştirilir (canlıdaki gibi hata yükseltir ve çağrıyı kaydeder; hata
  uçta yutulsa bile kayıt kalır),
- uygulamanın BÜTÜN FastAPI uçları OpenAPI şemasından türetilen yol/sorgu/gövde değerleriyle
  dolaşılır (yol kimlikleri tohumlanan gerçek kayıtlardan; izin denetimi açık).

Beklenen: hiçbir uç tuzağa düşmez. Worker'a devredilen yollar (`demo.durum_oku`,
`codegen.dil_algila`, `codegen.musteri_ci_durum`, `jira.vekil`, iş kuyruğu) iş açar ve döner.
Yeni bir senkron dış çağrı eklenirse test hangi ucun hangi fabrikayı çağırdığını söyler.
"""

from __future__ import annotations

import sys
import traceback
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tp_core.models import PullRequest, Script, session_scope
from tp_core.models.codegen_feature import ScriptCodegen
from tp_core.models.guard import allow_state_write
from tp_core.workflow.service import Principal

from .conftest import login

# Dolaşılmayan uçlar (gerekçeli): SSE akışı kapanmaz; MCP ayrı protokol (kendi testleri var);
# oturum kapatma sonraki istekleri oturumsuz bırakır.
ATLANAN: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/events"),
        ("POST", "/auth/logout"),
        ("GET", "/mcp"),
        ("POST", "/mcp"),
    }
)

SHA = "b" * 40


@dataclass
class Dusus:
    tuzak: str
    uc: str
    yigin: str


class TuzakHatasi(RuntimeError):
    """Tuzak çağrıldı (canlıda bu noktada `ForgeValidationError`/`JiraConfigError` yükselir)."""


def _rotalar(routes: Any, prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    for r in routes:
        if isinstance(r, APIRoute):
            yield prefix + r.path, r
            continue
        alt = getattr(r, "original_router", None)
        if alt is not None:
            ek = getattr(getattr(r, "include_context", None), "prefix", "") or ""
            yield from _rotalar(alt.routes, prefix + ek)


# ------------------------------------------------------------------ tuzaklar


def _tuzak_noktalari() -> list[tuple[Any, str, str]]:
    """(sahip nesne, öznitelik, ad). Fonksiyonlar tp_core modüllerindeki TÜM referanslarıyla
    değiştirilir (`from x import get_forge` kopyaları dahil); sınıf yöntemleri sınıfta."""
    from tp_core.features.ci import clients as ci_clients
    from tp_core.home_config import baglanti
    from tp_core.integrations import forge, forge_github, jira, proje_ortami, xray

    return [
        (forge, "get_forge", "forge.get_forge"),
        (forge_github.GitHubForge, "from_env", "GitHubForge.from_env"),
        (forge_github.GitHubForge, "__init__", "GitHubForge()"),
        (ci_clients.GitHubCi, "__init__", "GitHubCi()"),
        (jira, "get_jira", "jira.get_jira"),
        (jira.RestJira, "__init__", "RestJira()"),
        (xray, "get_xray_client", "xray.get_xray_client"),
        (baglanti, "istemci", "baglanti.istemci"),
        (baglanti, "token_al", "baglanti.token_al"),
        (proje_ortami, "token_al", "proje_ortami.token_al"),
    ]


def _yigin() -> str:
    satirlar = [
        f"{f.filename.split('/src/')[-1]}:{f.lineno} {f.name}"
        for f in traceback.extract_stack()[:-2]
        if "/src/tp_core/" in f.filename
    ]
    return " <- ".join(reversed(satirlar[-6:]))


@pytest.fixture
def tuzaklar(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[list[Dusus], list[str]]]:
    dususler: list[Dusus] = []
    su_an: list[str] = [""]

    def kur(ad: str) -> Callable[..., Any]:
        def tuzak(*_a: Any, **_k: Any) -> Any:
            dususler.append(Dusus(ad, su_an[0], _yigin()))
            raise TuzakHatasi(f"T1: core-api'de {ad} (App/OAuth kipinde yalnız core-worker)")

        return tuzak

    for sahip, oz, ad in _tuzak_noktalari():
        asil = sahip.__dict__.get(oz) if isinstance(sahip, type) else getattr(sahip, oz)
        yeni = kur(ad)
        if isinstance(sahip, type):
            monkeypatch.setattr(sahip, oz, classmethod(yeni) if isinstance(asil, classmethod)
                                else yeni)  # fmt: skip
            continue
        monkeypatch.setattr(sahip, oz, yeni)
        for mod in list(sys.modules.values()):
            if (getattr(mod, "__name__", "") or "").startswith("tp_core."):
                for k, v in list(vars(mod).items()):
                    if v is asil:
                        monkeypatch.setattr(mod, k, yeni)
    yield dususler, su_an


@pytest.fixture
def api_sureci(monkeypatch: pytest.MonkeyPatch) -> None:
    """core-api: bağlantı token'ı yok; GitHub App + Jira OAuth kipi; sahte istemci/fabrika yok."""
    from tp_core.auth import yetki
    from tp_core.features.codegen import service as cg
    from tp_core.features.publish import service as yayin
    from tp_core.features.requirements import services as req_services
    from tp_core.integrations import proje_ortami

    monkeypatch.delenv("TP_BAGLANTI_TOKENI", raising=False)
    monkeypatch.setenv("TP_FORGE", "github")
    monkeypatch.setenv("TP_DEMO_MODE", "1")  # demo v2 düğmeleri (kır/sıfırla/durum) de dolaşılır
    # Canlıdaki gibi gerçek (sim olmayan) Jira/Xray adresleri: sim'e özgü kısa yollar devre dışı.
    monkeypatch.setenv("JIRA_BASE_URL", "https://t1-ornek.atlassian.net")
    monkeypatch.setenv("XRAY_BASE_URL", "https://xray.t1-ornek.invalid")
    kipler = {"github": "app", "jira": "oauth"}
    monkeypatch.setattr(
        proje_ortami, "baglanti_kipi", lambda tur, pid=None: kipler.get(tur, "token")
    )
    cg.reset_factories()
    from tp_core.proje import istemciler

    istemciler.sifirla()  # önceki testlerin önbelleğe aldığı istemciler tuzağı örtmesin
    for ad in list(req_services._overrides):
        monkeypatch.delitem(req_services._overrides, ad)
    # Worker yok: kuyruğa alınan işi bekleyen uçlar beklemeden "iş sonucu yok" yoluna düşer.
    monkeypatch.setattr(yayin, "job_status", lambda _e, _j: ("cancelled", None, "T1: worker yok"))
    # İzin denetimi açık: her uç gövdesine kadar koşsun (yetki matrisi `test_yetki`'de).
    monkeypatch.setattr(yetki, "izinli", lambda _rol, _izin: True)
    monkeypatch.setattr(yetki, "projede", lambda _p: True)


# ------------------------------------------------------------------ değer üretimi


def _tohum(engine: Engine, hazir: dict[str, Any]) -> dict[str, list[str]]:
    """Yol kimlikleri için gerçek kayıtlar: gereksinim + case'ler (`hazir`), web ve müşteri CI
    (android/kotlin, PR + head) script'leri."""
    rid = hazir["requirement_id"]
    case_ids = list(hazir["cases"].values())
    sids: list[str] = []
    with allow_state_write(), session_scope() as s:
        for i, (platform, dil, pr_no) in enumerate([("android", "kotlin", 42), ("web", "ts", 41)]):
            sc = Script(
                tur="test",
                dosya_yolu=f"e2e/t1_{i}.spec",
                platform=platform,
                dil=dil,
                durum="pr_open",
                branch=f"tp/t1-{i}",
                head_sha=SHA,
                pr_no=pr_no,
            )
            s.add(sc)
            s.flush()
            s.add(
                ScriptCodegen(
                    script_id=sc.id,
                    test_case_id=case_ids[i],
                    requirement_id=rid,
                    case_hash="h",
                    sira_no=i + 1,
                )
            )
            sids.append(str(sc.id))
            s.add(
                PullRequest(
                    number=pr_no,
                    branch=sc.branch,
                    baslik=f"T1 {platform}",
                    head_sha=SHA,
                    acan="tp-bot",
                )
            )
    with engine.connect() as c:

        def ids(sql: str) -> list[str]:
            try:
                return [str(x) for x in c.execute(text(sql)).scalars().all()]
            except Exception:
                c.rollback()
                return []

        return {
            "requirement": [str(rid)],
            "case": [str(x) for x in case_ids],
            "script": sids,
            "run": ids("SELECT id FROM run LIMIT 3"),
            "failure": ids("SELECT id FROM failure LIMIT 3"),
            "bug": ids("SELECT id FROM bug LIMIT 3"),
        }


def _yol_degeri(ad: str, sema: dict[str, Any], havuz: dict[str, list[str]]) -> str:
    a = ad.lower()
    if a == "req_id":
        a = "requirement_id"
    for anahtar, liste in (
        ("requirement", havuz["requirement"]),
        ("case", havuz["case"]),
        ("script", havuz["script"]),
        ("run", havuz["run"]),
        ("failure", havuz["failure"]),
        ("bug", havuz["bug"]),
    ):
        if anahtar in a and liste:
            return liste[0]
    if a in ("n", "pr", "pr_no", "no", "numara", "number"):
        return "42"
    tur = sema.get("type")
    if tur == "integer":
        return "1"
    if sema.get("format") == "uuid" or a.endswith("_id") or a == "id":
        return str(uuid.uuid4())
    if "enum" in sema:
        return str(sema["enum"][0])
    return "x"


def _cozumle(sema: dict[str, Any], tum: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in sema:
        sema = tum["components"]["schemas"][sema["$ref"].rsplit("/", 1)[-1]]
    return sema


def _ornek(sema: dict[str, Any], tum: dict[str, Any], havuz: dict[str, list[str]],
           ad: str = "", derinlik: int = 0) -> Any:  # fmt: skip
    sema = _cozumle(sema, tum)
    if derinlik > 4:
        return None
    for birlesik in ("anyOf", "oneOf", "allOf"):
        if birlesik in sema:
            secenek = [s for s in sema[birlesik] if _cozumle(s, tum).get("type") != "null"]
            return _ornek(secenek[0] if secenek else {}, tum, havuz, ad, derinlik + 1)
    if "default" in sema:
        return sema["default"]
    if "enum" in sema:
        return sema["enum"][0]
    if "const" in sema:
        return sema["const"]
    tur = sema.get("type")
    if tur == "object" or "properties" in sema:
        zorunlu = set(sema.get("required", ()))
        return {
            k: _ornek(v, tum, havuz, k, derinlik + 1)
            for k, v in (sema.get("properties") or {}).items()
            if k in zorunlu
        }
    if tur == "array":
        a = ad.lower()
        if "case" in a and havuz["case"]:
            return havuz["case"][:1]
        return []
    if tur == "integer":
        return max(1, int(sema.get("minimum", 1)))
    if tur == "number":
        return 1
    if tur == "boolean":
        return False
    if sema.get("format") == "uuid":
        return _yol_degeri(ad, sema, havuz)
    a = ad.lower()
    if a.endswith("_id") or "sha" in a:
        return SHA if "sha" in a else _yol_degeri(ad, sema, havuz)
    en_az = int(sema.get("minLength", 1))
    return "x" * max(1, en_az)


# ------------------------------------------------------------------ test


# Uçlar bu rollerle sırayla dolaşılır: izin denetimi açık olsa da bazı uçlar gövdede role bakar
# (ör. yayın yalnız testçi, onay yalnız analist); her rol kendi dalına kadar koşar.
ROLLER = ("admin", "engineer", "tester", "analyst", "po")


def _dolas(c: TestClient, app: Any, sema: dict[str, Any], havuz: dict[str, list[str]],
           su_an: list[str], yeniden_giris: Callable[[], None]) -> int:  # fmt: skip
    dolasilan = 0
    for yol, r in sorted(_rotalar(app.router.routes), key=lambda x: x[0]):
        for yontem in sorted(r.methods or ()):
            if (yontem, yol) in ATLANAN or yontem == "HEAD":
                continue
            op = (sema["paths"].get(yol) or {}).get(yontem.lower()) or {}
            gercek, sorgu = yol, {}
            for p in op.get("parameters", ()):
                deger = _yol_degeri(p["name"], _cozumle(p.get("schema", {}), sema), havuz)
                if p["in"] == "path":
                    gercek = gercek.replace("{" + p["name"] + "}", deger)
                    gercek = gercek.replace("{" + p["name"] + ":path}", deger)
                elif p["in"] == "query" and p.get("required"):
                    sorgu[p["name"]] = deger
            govde = None
            icerik = (op.get("requestBody") or {}).get("content") or {}
            if "application/json" in icerik:
                govde = _ornek(icerik["application/json"].get("schema", {}), sema, havuz)
            su_an[0] = f"{yontem} {yol}"
            c.request(yontem, gercek, params=sorgu or None, json=govde)
            dolasilan += 1
            if yol.startswith("/auth/") or yol.startswith("/proje"):
                yeniden_giris()  # oturumu/rolü değiştiren uçlardan sonra
    return dolasilan


def test_core_api_ucu_senkron_dis_cagri_yapmaz(
    hazir: dict[str, Any],
    engine: Engine,
    make_user: Callable[..., Principal],
    api_sureci: None,
    tuzaklar: tuple[list[Dusus], list[str]],
) -> None:
    from tp_core.api.main import create_app

    dususler, su_an = tuzaklar
    havuz = _tohum(engine, hazir)
    app = create_app()
    sema = app.openapi()
    with TestClient(app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False) as c:
        for rol in ROLLER:
            u = make_user(rol)
            login(c, u)
            dolasilan = _dolas(c, app, sema, havuz, su_an, lambda u=u: login(c, u))
            assert dolasilan > 100, dolasilan
    ozet = sorted({f"{d.uc} -> {d.tuzak}\n    {d.yigin}" for d in dususler})
    assert ozet == [], (
        "core-api'de senkron dış çağrı (GitHub App/Jira OAuth kipinde canlıda kırılır; işi "
        "core-worker'a devredin — demo.durum_oku / codegen.dil_algila / jira.vekil deseni):\n"
        + "\n".join(ozet)
    )


def test_tuzak_kurulumu_dis_cagriyi_yakalar(
    api_sureci: None, tuzaklar: tuple[list[Dusus], list[str]]
) -> None:
    """Koruma kendisi çalışıyor mu: modül kopyaları dahil fabrika çağrısı kaydedilir."""
    from tp_core.features.codegen import service as cg
    from tp_core.features.requirements import services as req_services
    from tp_core.integrations import forge_demo

    dususler, su_an = tuzaklar
    su_an[0] = "dogrudan"
    with pytest.raises(TuzakHatasi):
        forge_demo.get_forge()  # `from tp_core.integrations.forge import get_forge` kopyası
    n = len(dususler)
    with pytest.raises(TuzakHatasi):
        cg._forge()  # işlev içi içe aktarma da (modül özniteliği değiştirildi)
    assert len(dususler) == n + 1 and dususler[-1].tuzak.startswith(("forge.", "GitHubForge"))
    with pytest.raises(TuzakHatasi):
        req_services.jira()
    assert dususler[0].tuzak == "forge.get_forge" and dususler[-1].tuzak == "jira.get_jira"
