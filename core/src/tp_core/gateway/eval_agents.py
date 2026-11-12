"""Ajan amaçlarının (consistency_check, verify_and_map) canlı değerlendirmesi için araç ortamları.

Değerlendirme setinde `"agent": {"tool_env": <ad>, "max_turns": n}` taşıyan paketler, modelin
araç çağrılarını ÜRETİMDEKİ araç uygulamalarıyla yürütür (sahte araç sonucu yoktur; aksi hâlde
canlı değerlendirme ölçmesi gereken şeyi ölçmezdi):

- `consistency`: `features.requirements` kod araçları (`CodeTools`: forge üzerinde salt okuma,
  sabit commit) + veri araçları (`DataTools`: `DEMOAPP_RO_DATABASE_URL` salt okuma rolü). Bulgu
  kanıtları üretimdeki `EvidenceVerifier` ile aynı commit/veritabanında YENİDEN doğrulanır;
  doğrulanamayan kanıt vakayı düşürür (§8.2b adım 4).
- `browser`: kod üretiminin Playwright MCP oturumu (`AgentBrowser` + `McpBrowserSession`,
  doğrulama bayisi bayi3; `replay_check` ile aynı kurulum, ajan bayisi kilidi alınır).
- `app:<platform>` (009 §2.6): mobil/masaüstü doğrulama ajanının app-mcp oturumu (`AgentApp` +
  `McpBrowserSession(APP_MCP_URL)`, doğrulama bayisi bayi3, ajan bayisi kilidi; ilk araç
  `app_launch`, `app_screenshot` ajana verilmez). Cihaz (`make cihaz-baslat PLATFORM=…`) ve compose
  `mobil` profili (`app-mcp`) gerekir.
- `assistant:<rol>` (AI-ASISTAN-PLANI §13): portal asistanı. Vaka geçide doğrudan değil, worker'ın
  işleyicisi `flow.cevapla` üzerinden koşar (`AsistanAkisi`, `eval_live --via-flow`): sözlük/şablon/
  kapalı dalları, üretim araçları (`tools.arac_seti`, rol kısıtı oturumdaki kullanıcıyla) ve §7.3
  son işlem dahil. Ortam tohumlanmış Testing Probe veritabanında (`DATABASE_URL`) o roldeki ilk
  kullanıcıyı seçer; her vaka için bir sohbet + bekleyen asistan mesajı yazar, cevabı okur ve
  sohbeti yumuşak siler. Vaka süresince `asistan_durum` canlı işaretlenir (vaka bitince önceki
  satır geri yazılır) — koşu sırasında worker'ı durdurun ya da `TP_ASISTAN_MODEL_MODE=live` ile
  çalıştırın, aksi hâlde kalp atışı satırı vaka ortasında geri çevirebilir.

Ortam kurulamazsa (`ToolEnvUnavailable`: forge/veritabanı/MCP erişilemiyor) vaka ÇAĞRILMAZ ve
koşu eksik sayılır; durum "canlı değerlendirme bekliyor" kalır. Bu ortamlar compose yığınını ister
(`make up`): host'tan koşturulursa `DEMOAPP_RO_DATABASE_URL`, `TP_FORGE_PATH` ve
`PLAYWRIGHT_MCP_URL` host'a açılmış adresleri göstermelidir; yoksa core-worker içinde koşturun.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from tp_core.ports import ToolExecutor, ToolSpec


class ToolEnvUnavailable(RuntimeError):
    """Ajan araç ortamı kurulamadı (yığın kapalı, yapılandırma eksik)."""


@dataclass
class ToolEnv:
    name: str
    tools: list[ToolSpec]
    execute: ToolExecutor
    close: Callable[[], None] = lambda: None
    # Çıktıya ortama özgü ek denetim (ör. kanıtın yeniden doğrulanması); boş liste = geçti.
    check: Callable[[Any, Mapping[str, Any]], list[str]] = field(default=lambda output, expect: [])
    # Asistan ortamı: vakayı işleyici (`flow.cevapla`) üzerinden koşturan sürücü (`--via-flow`).
    akis: AsistanAkisi | None = None


EnvFactory = Callable[[], ToolEnv]


def _consistency_env() -> ToolEnv:  # pragma: no cover - canlı yığın (forge + demo-app PG)
    from tp_core.features.requirements import services
    from tp_core.features.requirements.codetools import TOOL_SPECS, CodeTools
    from tp_core.features.requirements.datatools import DataTools
    from tp_core.features.requirements.settings import get_requirements_settings
    from tp_core.features.requirements.verifier import EvidenceVerifier

    ayar = get_requirements_settings()
    try:
        forge = services.forge()
        sha = forge.head_sha(ayar.forge_ref)
        db = services.demo_db()
        db.schema()  # erişim denetimi: bağlanamıyorsa vakayı çağırmadan dur
    except Exception as exc:
        raise ToolEnvUnavailable(
            f"kod/veri araçları kurulamadı ({type(exc).__name__}: {str(exc)[:200]}); "
            "forge (TP_FORGE_PATH) ve DEMOAPP_RO_DATABASE_URL gerekli (make up)"
        ) from exc
    code = CodeTools(forge, sha, ayar.forge_repo)
    data = DataTools(db)
    table: dict[str, Callable[[dict[str, Any]], str]] = {
        "search_code": code.search_code,
        "get_file_contents": code.get_file_contents,
        "db_schema": data.db_schema,
        "db_query": data.db_query,
    }

    def execute(name: str, args: dict[str, Any]) -> str:
        fn = table.get(name)
        if fn is None:
            raise PermissionError(f"Araç izinli değil: {name}")
        return fn(args or {})

    verifier = EvidenceVerifier(forge, sha, db, repo=ayar.forge_repo)

    def check(output: Any, expect: Mapping[str, Any]) -> list[str]:
        acs = list(expect.get("acs") or [])
        out = []
        for finding in (output or {}).get("findings") or []:
            result = verifier.verify(finding, acs)
            if not result.ok:
                reasons = "; ".join(c.get("neden", "") for c in result.checks if not c.get("ok"))
                out.append(f"{finding.get('id')}: kanıt doğrulanamadı ({reasons})")
        return out

    return ToolEnv("consistency", list(TOOL_SPECS), execute, check=check)


def _browser_env() -> ToolEnv:  # pragma: no cover - canlı yığın (Playwright MCP + demo-app)
    from tp_core.features.codegen.browser import ajan_bayisi_kilidi
    from tp_core.gateway.replay_check import _production_session

    lock: AbstractContextManager[Any] | None = None
    try:
        lock = ajan_bayisi_kilidi()
        lock.__enter__()
        session = _production_session()
    except (Exception, SystemExit) as exc:
        if lock is not None:
            lock.__exit__(None, None, None)
        raise ToolEnvUnavailable(
            f"Playwright MCP oturumu kurulamadı ({type(exc).__name__}: {str(exc)[:200]}); "
            "compose yığını (playwright-mcp, demo-app-web) ve PLAYWRIGHT_MCP_URL gerekli"
        ) from exc

    def close() -> None:
        try:
            session.close()
        finally:
            if lock is not None:
                lock.__exit__(None, None, None)

    return ToolEnv("browser", session.tools, session.execute, close=close)


def _app_env(platform: str) -> ToolEnv:  # pragma: no cover - canlı cihaz + app-mcp
    from tp_core.config import get_settings
    from tp_core.features.codegen.browser import (
        AgentApp,
        AgentConfig,
        McpBrowserSession,
        ajan_bayisi_kilidi,
        reset_agent_cart,
    )

    lock: AbstractContextManager[Any] | None = None
    try:
        lock = ajan_bayisi_kilidi()
        lock.__enter__()
        cfg = AgentConfig.from_env()
        reset_agent_cart(cfg)
        mcp = McpBrowserSession(get_settings().app_mcp_url)
        agent = AgentApp(mcp, platform=platform, config=cfg, case_dealers=["bayi1", "bayi2"])
        tools = agent.tool_specs()
    except (Exception, SystemExit) as exc:
        if lock is not None:
            lock.__exit__(None, None, None)
        raise ToolEnvUnavailable(
            f"app-mcp oturumu kurulamadı ({type(exc).__name__}: {str(exc)[:200]}); compose "
            f"`mobil` profili (app-mcp), {platform} cihazı ve APP_MCP_URL gerekli"
        ) from exc

    def close() -> None:
        try:
            mcp.close()
        finally:
            if lock is not None:
                lock.__exit__(None, None, None)

    return ToolEnv(f"app:{platform}", tools, agent, close=close)


# ------------------------------------------------------------------ asistan (AI-ASISTAN-PLANI §13)

ASISTAN_ROLLERI: tuple[str, ...] = ("analyst", "po", "engineer", "tester", "presenter")
ASISTAN_ORTAM_ONEKI = "assistant:"
ASISTAN_AMACLARI: tuple[str, ...] = ("assistant", "assistant_deep")
TOHUM = "<tohum>"
# Vakanın `tohum_secim` süzgecinde izinli sütunlar (sabit; SQL'e yalnız bunlar girer).
_TOHUM_TABLOLARI: dict[str, tuple[str, frozenset[str], str]] = {
    "requirement": ("requirement", frozenset({"durum", "jira_key", "kaynak"}), "olusturma DESC"),
    "script": ("script", frozenset({"durum", "tur"}), "olusturma DESC"),
    "run": ("run", frozenset({"sonuc", "kaynak", "tetik"}), "baslama DESC NULLS LAST"),
    "failure": (
        "failure",
        frozenset({"sinif", "alt_tur", "oneri_turu"}),
        "(SELECT r.baslama FROM run r WHERE r.id = failure.run_id) DESC NULLS LAST",
    ),
}


@dataclass
class AkisSonucu:
    """İşleyiciden okunan sonuç: `output` saklanan cevap + `cevap_kaynagi`, `otomatik_derin`."""

    output: dict[str, Any] | None
    durum: str | None
    maliyet_usd: float | None = None
    sure_ms: int | None = None
    hata: str | None = None


def tohum_coz(conn: Any, baglam: Any, secim: Mapping[str, Any] | None = None) -> Any:
    """Bağlamdaki `varlik.id = "<tohum>"`'u tohumlanmış veritabanındaki kimlikle değiştirir.

    `requirement` `anahtar` (Jira anahtarı) ile, diğerleri vakanın `tohum_secim` süzgeciyle (izinli
    sütunlar) en yeni kayıttan seçilir. Çözülemezse `TohumYok` (vaka "tohum yok" diye düşer)."""
    from sqlalchemy import text

    if not isinstance(baglam, Mapping):
        return baglam
    varlik = baglam.get("varlik")
    if not isinstance(varlik, Mapping) or varlik.get("id") != TOHUM:
        return dict(baglam)
    tur = str(varlik.get("tur") or "")
    if tur not in _TOHUM_TABLOLARI:
        raise TohumYok(f"tohum çözülemedi: bilinmeyen varlık türü {tur!r}")
    tablo, izinli, sira = _TOHUM_TABLOLARI[tur]
    kosul = dict(secim or {})
    if tur == "requirement" and varlik.get("anahtar"):
        kosul.setdefault("jira_key", varlik["anahtar"])
    bilinmeyen = sorted(set(kosul) - izinli)
    if bilinmeyen:
        raise TohumYok(f"tohum_secim izinli olmayan sütun: {bilinmeyen}")
    where = " AND ".join(f"{k} = :{k}" for k in sorted(kosul)) or "TRUE"
    kimlik = conn.execute(
        text(f"SELECT id FROM {tablo} WHERE {where} ORDER BY {sira} LIMIT 1"),
        kosul,
    ).scalar()
    if kimlik is None:
        raise TohumYok(f"tohum çözülemedi: {tur} {kosul}")
    return {**baglam, "varlik": {**varlik, "id": str(kimlik)}}


class TohumYok(RuntimeError):
    """Vakanın gerektirdiği tohum verisi veritabanında yok."""


_DURUM_SUTUNLARI = ("mod", "model_hazir", "maskeleme", "musteri_verisi", "kalp_atisi")


@dataclass
class AsistanAkisi:
    """Bir role ait asistan vakalarını `flow.cevapla` üzerinden koşturan sürücü.

    `arac_seti_fabrikasi`, `dogrulayici`, `masker`: `flow.cevapla`'ya aynen geçer (None → üretim).
    Testler sahte araç seti/doğrulayıcı verir; canlı değerlendirme üretimdekileri kullanır."""

    session_factory: Callable[[], Any]
    kullanici_id: uuid.UUID
    rol: str
    arac_seti_fabrikasi: Callable[[Any], Any] | None = None
    dogrulayici: Any = None
    masker: Any = None
    rules_dir: Path | None = None
    saat: Callable[[], float] = time.monotonic

    # -------------------------------------------------------------- asistan_durum

    @staticmethod
    def _canli_isaretle(conn: Any) -> dict[str, Any] | None:
        """`asistan_durum`'u canlı işaretler; önceki satırı (yoksa None) döndürür."""
        from sqlalchemy import text

        satir = (
            conn.execute(
                text(f"SELECT {', '.join(_DURUM_SUTUNLARI)} FROM asistan_durum WHERE id = 1")
            )
            .mappings()
            .first()
        )
        conn.execute(
            text(
                "INSERT INTO asistan_durum (id, mod, model_hazir, kalp_atisi) "
                "VALUES (1, 'live', true, now()) ON CONFLICT (id) DO UPDATE SET mod = 'live', "
                "model_hazir = true, kalp_atisi = now()"
            )
        )
        return dict(satir) if satir else None

    @staticmethod
    def _durumu_geri_yaz(conn: Any, onceki: dict[str, Any] | None) -> None:
        """`asistan_durum`'u vaka öncesine döndürür (satır yoktuysa siler)."""
        from sqlalchemy import text

        if onceki is None:
            conn.execute(text("DELETE FROM asistan_durum WHERE id = 1"))
            return
        atama = ", ".join(f"{k} = :{k}" for k in _DURUM_SUTUNLARI)
        conn.execute(text(f"UPDATE asistan_durum SET {atama} WHERE id = 1"), onceki)

    # -------------------------------------------------------------- vaka

    def _mesaj_yaz(
        self, case: Mapping[str, Any], amac: str
    ) -> tuple[uuid.UUID, uuid.UUID, dict[str, Any] | None]:
        from sqlalchemy import text

        sohbet, mesaj = uuid.uuid4(), uuid.uuid4()
        kip = str(case.get("kip") or "soru")
        with self.session_factory() as s:
            conn = s.connection()
            baglam = tohum_coz(conn, case.get("baglam"), case.get("tohum_secim"))
            conn.execute(
                text("INSERT INTO asistan_sohbet (id, kullanici_id, baslik) VALUES (:s, :k, :b)"),
                {"s": sohbet, "k": self.kullanici_id, "b": f"eval: {case['id']}"[:120]},
            )
            ortak = {"s": sohbet, "k": self.kullanici_id, "icerik": case.get("soru"), "kip": kip}
            conn.execute(
                text(
                    "INSERT INTO asistan_mesaj (sohbet_id, kullanici_id, sira, rol, icerik, kip, "
                    "durum) VALUES (:s, :k, 1, 'user', :icerik, :kip, 'done')"
                ),
                ortak,
            )
            conn.execute(
                text(
                    "INSERT INTO asistan_mesaj (id, sohbet_id, kullanici_id, sira, rol, icerik, "
                    "baglam, kip, durum, amac) VALUES (:m, :s, :k, 2, 'assistant', :icerik, "
                    "CAST(:baglam AS jsonb), :kip, 'pending', :amac)"
                ),
                {
                    **ortak,
                    "m": mesaj,
                    "baglam": json.dumps(baglam, ensure_ascii=False) if baglam else None,
                    # `assistant` için NULL (API gibi; işleyici `hedef_amac`'ı yazar).
                    "amac": amac if amac != "assistant" else None,
                },
            )
            onceki = self._canli_isaretle(conn)
            s.commit()
        return sohbet, mesaj, onceki

    def _temizle(self, sohbet: uuid.UUID, mesaj: uuid.UUID, onceki: dict[str, Any] | None) -> None:
        from sqlalchemy import text

        with self.session_factory() as s:
            conn = s.connection()
            # İşleyici bir nedenle bitiremediyse "kullanıcı başına tek bekleyen" kilidi kalmasın.
            conn.execute(
                text(
                    "UPDATE asistan_mesaj SET durum = 'iptal', tamamlanma = now() "
                    "WHERE id = :m AND durum IN ('pending', 'running')"
                ),
                {"m": mesaj},
            )
            conn.execute(
                text("UPDATE asistan_sohbet SET silindi = true, silinme = now() WHERE id = :s"),
                {"s": sohbet},
            )
            self._durumu_geri_yaz(conn, onceki)
            s.commit()

    def sor(
        self, case: Mapping[str, Any], amac: str, gateway_factory: Callable[..., Any]
    ) -> AkisSonucu:
        """Vakayı bir asistan mesajı olarak yazar, `flow.cevapla` ile cevaplatır, sonucu okur.

        Otomatik yükseltme (§6.2) değerlendirmede çocuk mesaj/iş yaratmaz (worker onu canlı
        cevaplamasın): cevaplama süresince `TP_ASISTAN_OTOMATIK_DERIN=0`, sonra tetik aynı
        deterministik fonksiyonla (`flow.otomatik_tetik`, ortamın gerçek ayarıyla) hesaplanır."""
        from sqlalchemy import text

        from tp_core.features.assistant import flow

        sohbet, mesaj, onceki_durum = self._mesaj_yaz(case, amac)
        try:
            onceki = os.environ.get(flow.ORTAM_OTOMATIK_DERIN)
            os.environ[flow.ORTAM_OTOMATIK_DERIN] = "0"
            try:
                durum = flow.cevapla(
                    self.session_factory,
                    mesaj,
                    gateway_factory=gateway_factory,
                    arac_seti_fabrikasi=self.arac_seti_fabrikasi,
                    dogrulayici=self.dogrulayici,
                    masker=self.masker,
                    rules_dir=self.rules_dir,
                    saat=self.saat,
                )
            finally:
                if onceki is None:
                    os.environ.pop(flow.ORTAM_OTOMATIK_DERIN, None)
                else:
                    os.environ[flow.ORTAM_OTOMATIK_DERIN] = onceki
            with self.session_factory() as s:
                conn = s.connection()
                r = (
                    conn.execute(
                        text(
                            "SELECT cevap, kaynak, durum, hata_kodu, maliyet_usd, sure_ms "
                            "FROM asistan_mesaj WHERE id = :m"
                        ),
                        {"m": mesaj},
                    )
                    .mappings()
                    .one()
                )
                m = flow._mesaj_oku(conn, mesaj)
                s.rollback()
        finally:
            self._temizle(sohbet, mesaj, onceki_durum)
        maliyet = float(r["maliyet_usd"]) if r["maliyet_usd"] is not None else None
        if r["durum"] != "done" or not isinstance(r["cevap"], Mapping):
            return AkisSonucu(
                None,
                r["durum"] or durum,
                maliyet,
                r["sure_ms"],
                f"mesaj {r['durum'] or durum}: {r['hata_kodu'] or '-'}",
            )
        cevap = dict(r["cevap"])
        output = {
            **cevap,
            "cevap_kaynagi": r["kaynak"],
            "otomatik_derin": r["kaynak"] == "model" and flow.otomatik_tetik(m, cevap),
        }
        return AkisSonucu(output, r["durum"], maliyet, r["sure_ms"])


def _asistan_env(rol: str) -> ToolEnv:  # pragma: no cover - canlı yığın (tohumlu Testing Probe DB)
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from tp_core.db import get_engine

    try:
        engine = get_engine()
        with engine.connect() as conn:
            kullanici = conn.execute(
                text("SELECT id FROM app_user WHERE rol = :r ORDER BY kullanici_adi LIMIT 1"),
                {"r": rol},
            ).scalar()
    except Exception as exc:
        raise ToolEnvUnavailable(
            f"Testing Probe veritabanına bağlanılamadı ({type(exc).__name__}); DATABASE_URL ve "
            "tohumlu yığın gerekli (make up, make seed)"
        ) from exc
    if kullanici is None:
        raise ToolEnvUnavailable(f"'{rol}' rolünde kullanıcı yok (make seed)")
    akis = AsistanAkisi(sessionmaker(engine, expire_on_commit=False), kullanici, rol)
    return asistan_ortami(akis)


def asistan_ortami(akis: AsistanAkisi, *, close: Callable[[], None] | None = None) -> ToolEnv:
    """`AsistanAkisi`'nı ortam olarak sarar (araçları işleyici kurar; doğrudan araç yürütme yok)."""

    def execute(name: str, args: dict[str, Any]) -> str:
        raise PermissionError("asistan ortamı yalnız işleyici üzerinden koşar (--via-flow)")

    return ToolEnv(
        f"{ASISTAN_ORTAM_ONEKI}{akis.rol}",
        [],
        execute,
        close=close or (lambda: None),
        akis=akis,
    )


ENVS: dict[str, EnvFactory] = {
    "consistency": _consistency_env,
    "browser": _browser_env,
    **{f"app:{p}": partial(_app_env, p) for p in ("android", "ios", "windows")},
    **{f"{ASISTAN_ORTAM_ONEKI}{rol}": partial(_asistan_env, rol) for rol in ASISTAN_ROLLERI},
}


def open_env(name: str, envs: Mapping[str, EnvFactory] | None = None) -> ToolEnv:
    table = ENVS if envs is None else envs
    factory = table.get(name)
    if factory is None:
        raise ToolEnvUnavailable(f"bilinmeyen araç ortamı: {name!r}")
    return factory()


def mapping_problems(output: Any, expect: Mapping[str, Any]) -> list[str]:
    """verify_and_map beklentisi (deterministik): her adım eşlenmiş ya da eksik metot olarak
    bildirilmiş, metotlar sembol tablosunda var, beklenen assertion'lar mevcut."""
    out = output if isinstance(output, Mapping) else {}
    failures: list[str] = []
    mapped = {m.get("step_id") for m in out.get("step_mapping") or [] if isinstance(m, Mapping)}
    missing = {m.get("step_id") for m in out.get("missing_methods") or [] if isinstance(m, Mapping)}
    for step in expect.get("steps") or []:
        if step not in mapped and step not in missing:
            failures.append(f"adım {step} eşlenmedi")
    allowed = set(expect.get("methods") or [])
    if allowed:
        for item in [*(out.get("step_mapping") or []), *(out.get("expects") or [])]:
            if not isinstance(item, Mapping):
                continue
            ref = f"{item.get('po')}.{item.get('method')}"
            if ref not in allowed:
                failures.append(f"sembol tablosunda olmayan metot: {ref}")
    have = {f"{e.get('po')}.{e.get('method')}" for e in out.get("expects") or []}
    failures += [
        f"beklenen assertion yok: {m}" for m in expect.get("expects_include") or [] if m not in have
    ]
    if expect.get("no_missing_methods") and missing:
        failures.append(f"eksik metot bildirildi: {sorted(s for s in missing if s)}")
    unverified = [
        m.get("step_id")
        for m in out.get("step_mapping") or []
        if isinstance(m, Mapping) and m.get("verified") is not True
    ]
    if expect.get("all_verified") and unverified:
        failures.append(f"doğrulanmamış adım: {unverified}")
    return failures


def _refs(doc_ref: Any) -> set[str]:
    return {p.strip() for p in str(doc_ref or "").replace("↔", ",").split(",") if p.strip()}


def findings_problems(output: Any, expect: Mapping[str, Any]) -> list[str]:
    """consistency_check beklentisi: beklenen belge yerleri bulguda, engelleyici sayısı sınırda,
    bulgu belgede olmayan AC'ye atıf yapmıyor."""
    out = output if isinstance(output, Mapping) else {}
    findings = [f for f in out.get("findings") or [] if isinstance(f, Mapping)]
    failures: list[str] = []
    seen: set[str] = set()
    for f in findings:
        seen |= _refs(f.get("doc_ref"))
    for ref in expect.get("doc_refs_include") or []:
        if ref not in seen:
            failures.append(f"{ref} için bulgu yok")
    known = {a.split(":", 1)[0].strip() for a in expect.get("acs") or []} | {"Açıklama"}
    unknown = sorted(r for r in seen if r not in known)
    if unknown:
        failures.append(f"belgede olmayan yer: {unknown}")
    blocking = sum(1 for f in findings if f.get("severity") == "blocking")
    if "max_blocking" in expect and blocking > int(expect["max_blocking"]):
        failures.append(f"{blocking} engelleyici bulgu, en çok {expect['max_blocking']}")
    if "min_blocking" in expect and blocking < int(expect["min_blocking"]):
        failures.append(f"{blocking} engelleyici bulgu, en az {expect['min_blocking']}")
    no_evidence = [
        f.get("id")
        for f in findings
        if not f.get("evidence") and f.get("type") != "internal_contradiction"
    ]
    if no_evidence:
        failures.append(f"kanıtsız bulgu: {no_evidence}")
    return failures


# ------------------------------------------------------------------ case üretimi v3 (011 §4.2)

# Teknik ↔ kapsam öğesi kimliği öneki (rules/schemas/case_generation.schema.json).
TEKNIK_ONEKI: dict[str, str] = {
    "EP": "EP-",
    "BVA": "BV-",
    "DT": "DT-",
    "ST": "ST-",
    "PW": "PW-",
    "UC": "UC-",
    "EG": "EG-",
    "CL": "CL-",
}
READINESS = ("ready", "assumption_dependent", "blocked")
# Platform ekinde atlanan kategori (011 F4, `platform-common`): `not_covered.item` =
# `<Platform>:<kategori>`.
PLATFORM_KATEGORISI = re.compile(r"(Web|Mobil|Desktop|API|Data):[^\n]{1,32}")


def _liste(deger: Any) -> list[Any]:
    return list(deger) if isinstance(deger, (list, tuple)) else []


def _kayitlar(deger: Any) -> list[Mapping[str, Any]]:
    return [x for x in _liste(deger) if isinstance(x, Mapping)]


def _sade(deger: Any) -> str:
    """Boşlukları teke indirir, büyük/küçük harfi eşitler (saldırı verisi karşılaştırması)."""
    return re.sub(r"\s+", " ", str(deger or "")).strip().casefold()


def _saldiri_alanlari(case: Mapping[str, Any]) -> list[str]:
    """Saldırı verisinin GEÇMEMESİ gereken alanlar: başlık, ön koşul, adım, beklenen, temizlik."""
    parcalar = [str(case.get("title") or ""), str(case.get("expected_result") or "")]
    parcalar += [str(p) for p in _liste(case.get("preconditions"))]
    parcalar += [str(t) for t in _liste(case.get("teardown"))]
    for step in _kayitlar(case.get("steps")):
        parcalar += [str(step.get(k) or "") for k in ("action", "data", "expected")]
    return parcalar


def _case_metni(case: Mapping[str, Any]) -> str:
    """Case'in okunan metni (başlık, ön koşul, adımlar, beklenen, temizlik, test verisi)."""
    parcalar = _saldiri_alanlari(case)
    for veri in _kayitlar(case.get("test_data")):
        parcalar += [str(veri.get("name") or ""), str(veri.get("value") or "")]
    return "\n".join(p for p in parcalar if p)


def case_rule_problems(case: Mapping[str, Any], output: Mapping[str, Any]) -> list[str]:
    """011 §4.2 case düzeyi kurallar (1–6); `output` aynı üretimin üst düzey listeleri.

    Üretimdeki karşılığı `features.cases.schema.consistency_problems`'tir; değerlendirme geçidin
    içinde kalsın diye (özellik katmanına bağımlılık yok) burada bağımsız uygulanır."""
    sorunlar: list[str] = []
    ogeler = {str(o.get("id")) for o in _kayitlar(output.get("coverage_items"))}
    sorular = {str(q.get("id")) for q in _kayitlar(output.get("open_questions"))}
    varsayimlar = {str(a.get("id")) for a in _kayitlar(output.get("assumptions"))}
    teknikler = [str(t) for t in _liste(case.get("technique"))]
    kapsar = [str(k) for k in _liste(case.get("covers"))]
    durum = case.get("readiness")
    for ad, deger in (("technique", teknikler), ("covers", kapsar)):
        if not deger:
            sorunlar.append(f"{ad} boş")
    if case.get("priority") not in ("P1", "P2", "P3"):
        sorunlar.append("priority boş")
    if not str(case.get("priority_rationale") or "").strip():
        sorunlar.append("priority_rationale boş")
    if durum not in READINESS:
        sorunlar.append(f"readiness geçersiz: {durum!r}")
    # 1. Tanımsız kapsam öğesi yok.
    tanimsiz = sorted(k for k in kapsar if k not in ogeler)
    if tanimsiz:
        sorunlar.append(f"tanımsız kapsam öğesi: {tanimsiz}")
    # 2. Teknik ↔ kapsam öneki: her tekniğin `covers`'ta en az bir öğesi var (yönerge kuralı).
    for teknik in teknikler:
        onek = TEKNIK_ONEKI.get(teknik)
        if onek is None or not any(k.startswith(onek) for k in kapsar):
            sorunlar.append(f"teknik {teknik} için kapsam öğesi yok")
    onekler = {TEKNIK_ONEKI[t] for t in teknikler if t in TEKNIK_ONEKI}
    sahipsiz = sorted(k for k in kapsar if not any(k.startswith(o) for o in onekler))
    if sahipsiz:
        sorunlar.append(f"tekniği technique'te olmayan kapsam öğesi: {sahipsiz}")
    # 3. Varsayım / açık soru atıfları üst listelerde tanımlı.
    a_refs = [str(r) for r in _liste(case.get("assumption_refs"))]
    q_refs = [str(r) for r in _liste(case.get("open_question_refs"))]
    eksik = sorted(
        {r for r in a_refs if r not in varsayimlar} | {r for r in q_refs if r not in sorular}
    )
    if eksik:
        sorunlar.append(f"tanımsız varsayım/soru atıfı: {eksik}")
    # 4. Hazır olma durumu ↔ atıflar ve beklenenler.
    beklenen = str(case.get("expected_result") or "").strip()
    adimlar = _kayitlar(case.get("steps"))
    bos_adim = [str(s.get("id")) for s in adimlar if not str(s.get("expected") or "").strip()]
    if durum == "ready":
        if a_refs or q_refs:
            sorunlar.append("ready case varsayım/soru atıfı taşıyor")
        if not beklenen or bos_adim:
            sorunlar.append("ready case'te beklenen sonuç boş")
    elif durum == "assumption_dependent":
        if not a_refs:
            sorunlar.append("assumption_dependent case'te varsayım atıfı yok")
        if not beklenen or bos_adim:
            sorunlar.append("assumption_dependent case'te beklenen sonuç boş")
    elif durum == "blocked":
        if not q_refs:
            sorunlar.append("blocked case'te açık soru atıfı yok")
        if beklenen:
            sorunlar.append("blocked case'te expected_result dolu")
    # 5–6. Test verisi: sentetik; saldırı verisi başka alanda geçmez.
    alanlar = [_sade(alan) for alan in _saldiri_alanlari(case)]
    for veri in _kayitlar(case.get("test_data")):
        if veri.get("synthetic") is not True:
            sorunlar.append(f"test verisi sentetik değil: {veri.get('name')}")
        deger = _sade(veri.get("value"))
        saldiri = veri.get("is_attack_payload") is True and bool(deger)
        if saldiri and any(deger in alan for alan in alanlar):
            sorunlar.append(f"saldırı verisi başka alanda geçiyor: {veri.get('name')}")
    return sorunlar


def generation_rule_problems(output: Any, *, ek_set: bool = False) -> list[str]:
    """011 §4.2 deterministik kurallarının tamamı, bir üretim çıktısının bütününe uygulanır:
    her case için `case_rule_problems` + set düzeyi (negatif kapsam kararı, kapsanmayan gerekçesi).
    AC atıfı (kural 7) belgeyi bilen `coverage_problems`'tedir (`ac_coverage`).

    `ek_set=True` (derinleştirme, P5/P6): çıktı mevcut sete EKtir; `covered_by` kararı ve yeniden
    anılan mevcut öğe mevcut case'lerle kapsanır, AC kapsamı tek başına aranmaz."""
    out = output if isinstance(output, Mapping) else {}
    cases = _kayitlar(out.get("cases"))
    sorunlar = [
        f"C{n}: {s}" for n, case in enumerate(cases, start=1) for s in case_rule_problems(case, out)
    ]
    ogeler = _kayitlar(out.get("coverage_items"))
    kimlikler = [str(o.get("id")) for o in ogeler]
    for ad, liste in (
        ("kapsam öğesi", kimlikler),
        ("açık soru", [str(q.get("id")) for q in _kayitlar(out.get("open_questions"))]),
        ("varsayım", [str(a.get("id")) for a in _kayitlar(out.get("assumptions"))]),
    ):
        cift = sorted({k for k in liste if liste.count(k) > 1})
        if cift:
            sorunlar.append(f"yinelenen {ad} kimliği: {cift}")
    kapsanan = {str(k) for c in cases for k in _liste(c.get("covers"))}
    ac_kapsanan = {str(r) for c in cases for r in _liste(c.get("acceptance_criteria_refs"))}
    kararlar: dict[str, list[Mapping[str, Any]]] = {}
    for karar in _kayitlar(out.get("negative_coverage")):
        kararlar.setdefault(str(karar.get("item")), []).append(karar)
    kapsanmayan = _kayitlar(out.get("not_covered"))
    gerekceli = {str(n.get("item")) for n in kapsanmayan if str(n.get("reason") or "").strip()}
    acler = {str(o.get("ac_ref")) for o in ogeler if o.get("ac_ref")}
    # Karar yalnız tanımlı öğeye; kapsanmayan kaydı tanımlı öğeye ya da bir kabul kriterine (ACn).
    tanimsiz = sorted(
        {k for k in kararlar if k not in kimlikler}
        | {
            str(n.get("item"))
            for n in kapsanmayan
            if str(n.get("item")) not in kimlikler
            and not re.fullmatch(r"AC[0-9]+", str(n.get("item")))
            and not PLATFORM_KATEGORISI.fullmatch(str(n.get("item")))
        }
    )
    if tanimsiz:
        sorunlar.append(f"tanımsız kapsam öğesine karar/gerekçe: {tanimsiz}")
    for oge in ogeler:
        kimlik = str(oge.get("id"))
        karar_listesi = kararlar.get(kimlik, [])
        kapsam_disi = any(
            k.get("decision") == "out_of_scope" and str(k.get("rationale") or "").strip()
            for k in karar_listesi
        )
        if oge.get("valid") is False:
            if len(karar_listesi) != 1:
                sorunlar.append(
                    f"{kimlik}: negatif kapsam kararı {len(karar_listesi)} adet (1 olmalı)"
                )
            elif not str(karar_listesi[0].get("rationale") or "").strip():
                sorunlar.append(f"{kimlik}: negatif kapsam kararının gerekçesi yok")
        for karar in karar_listesi:
            kararlar_ = ("tested",) if ek_set else ("tested", "covered_by")
            if karar.get("decision") in kararlar_ and kimlik not in kapsanan:
                sorunlar.append(
                    f"{kimlik}: karar {karar.get('decision')} ama hiçbir case kapsamıyor"
                )
        if ek_set:
            continue
        if kimlik not in kapsanan and kimlik not in gerekceli and not kapsam_disi:
            sorunlar.append(f"{kimlik}: kapsanmıyor ve gerekçesi yok")
    for ac in sorted(acler - ac_kapsanan - gerekceli if not ek_set else set()):
        sorunlar.append(f"{ac}: hiçbir case'te yok ve gerekçesi yok")
    return sorunlar


def generation_stats(output: Any) -> dict[str, Any]:
    """Bir üretim çıktısının dağılımı (eval raporu: kapsam, readiness ve teknik dağılımı)."""
    out = output if isinstance(output, Mapping) else {}
    cases = _kayitlar(out.get("cases"))
    hazirlik: dict[str, int] = {}
    teknik: dict[str, int] = {}
    for case in cases:
        durum = str(case.get("readiness") or "yok")
        hazirlik[durum] = hazirlik.get(durum, 0) + 1
        for t in _liste(case.get("technique")):
            teknik[str(t)] = teknik.get(str(t), 0) + 1
    ogeler = _kayitlar(out.get("coverage_items"))
    kapsanan = {str(k) for c in cases for k in _liste(c.get("covers"))}
    return {
        "case": len(cases),
        "readiness": dict(sorted(hazirlik.items())),
        "technique": dict(sorted(teknik.items())),
        "coverage_items": len(ogeler),
        "covered_items": sum(1 for o in ogeler if str(o.get("id")) in kapsanan),
        "invalid_items": sum(1 for o in ogeler if o.get("valid") is False),
        "not_covered": len(_liste(out.get("not_covered"))),
        "open_questions": len(_liste(out.get("open_questions"))),
        "assumptions": len(_liste(out.get("assumptions"))),
    }


def _belirtec_var(belirtec: str, metin: str) -> bool:
    """Uydurma belirteci aranır (büyük/küçük harf duyarsız). Salt rakam belirteç (ör. `429`)
    tutarın parçasıysa (`1.429,00 TL`, `4290`) sayılmaz."""
    b = _kucuk(belirtec)
    if b.isdigit():
        return re.search(rf"(?<![\d.,]){re.escape(b)}(?![.,]?\d)", metin) is not None
    return b in metin


def coverage_problems(output: Any, expect: Mapping[str, Any]) -> list[str]:
    """case_generation beklentisi (deterministik).

    Her zaman: 011 §4.2 kuralları çıktının tamamına (`generation_rule_problems`).
    Beklenti anahtarları:
    - `ac_coverage`: her AC en az bir case'te, belgede olmayan AC yok;
    - `ready_ac_coverage`: bu AC'lerin her biri en az bir `ready` case'te (kaynağın açık olduğu
      kural engellenmiş/varsayıma bağlı bırakılmaz);
    - `min_cases` / `max_cases`;
    - `contains` / `not_contains`: case'lerin birleşik metni (büyük/küçük harf duyarlı);
    - `not_contains_any`: uydurma belirteçleri (kaynakta olmayan HTTP kodu, zaman aşımı, kilit…);
      `ready` case'lerin metninde hiçbiri geçmez (büyük/küçük harf duyarsız). Hazır olmayan case
      bilinmeyeni adıyla anabilir; kaynağa dayalı diye sunulan (`ready`) case anamaz;
    - `must_not_be_ready_about`: `[{"topic", "keywords": [...]}]` — kaynağın sessiz olduğu bilinen
      konu. Anahtar sözcüklerden birini içeren case `ready` olamaz (hiç yazılmaması da geçerlidir).
    """
    out = output if isinstance(output, Mapping) else {}
    cases = [c for c in out.get("cases") or [] if isinstance(c, Mapping)]
    failures: list[str] = []
    refs: set[str] = set()
    for c in cases:
        refs |= {str(r) for r in c.get("acceptance_criteria_refs") or []}
    acs = list(expect.get("ac_coverage") or [])
    failures += [f"{ac} hiçbir case'te yok" for ac in acs if ac not in refs]
    if acs:
        extra = sorted(refs - set(acs))
        if extra:
            failures.append(f"belgede olmayan AC: {extra}")
    if len(cases) < int(expect.get("min_cases", 1)):
        failures.append(f"{len(cases)} case, en az {expect.get('min_cases', 1)}")
    if "max_cases" in expect and len(cases) > int(expect["max_cases"]):
        failures.append(f"{len(cases)} case, en çok {expect['max_cases']}")
    blob = _blob(cases)
    failures += [f"'{n}' geçmiyor" for n in expect.get("contains") or [] if n not in blob]
    failures += [f"'{n}' geçmemeli" for n in expect.get("not_contains") or [] if n in blob]
    failures += generation_rule_problems(out)
    hazir = [(n, c) for n, c in enumerate(cases, start=1) if c.get("readiness") == "ready"]
    hazir_refs = {str(r) for _, c in hazir for r in c.get("acceptance_criteria_refs") or []}
    failures += [
        f"{ac} için hazır (ready) case yok"
        for ac in expect.get("ready_ac_coverage") or []
        if ac not in hazir_refs
    ]
    metinler = [(n, _kucuk(_case_metni(c))) for n, c in hazir]
    for belirtec in expect.get("not_contains_any") or []:
        nerede = [f"C{n}" for n, metin in metinler if _belirtec_var(str(belirtec), metin)]
        if nerede:
            failures.append(f"uydurma belirteci '{belirtec}' hazır case'te: {nerede}")
    for konu in expect.get("must_not_be_ready_about") or []:
        anahtarlar = [_kucuk(str(a)) for a in konu.get("keywords") or []]
        nerede = [f"C{n}" for n, metin in metinler if any(a in metin for a in anahtarlar)]
        if nerede:
            failures.append(
                f"kaynak '{konu.get('topic')}' konusunda sessiz; "
                f"hazır (ready) case yazılamaz: {nerede}"
            )
    if "platforms" in expect:
        failures += platform_problems(out, expect)
    return failures


# ------------------------------------------------------------ tasarım modeli (011 F3)

# Kaynağın adını andığı ama sonucu tanımlamadığı konuların aranacağı alanlar (açık soru,
# varsayım, model sorunu); uydurma belirteçleri bunların DIŞINDAKİ model metninde aranır.
_MODEL_BILINMEYEN_ALANLARI = ("open_questions", "assumptions", "model_issues")


def _model_metni(out: Mapping[str, Any], *, bilinmeyenler: bool) -> str:
    """Modelin metni: `bilinmeyenler=True` → yalnız soru/varsayım/sorun; False → geri kalanı."""
    parcalar = {k: v for k, v in out.items() if (k in _MODEL_BILINMEYEN_ALANLARI) == bilinmeyenler}
    return _kucuk(_blob([parcalar]))


def design_model_problems(output: Any, expect: Mapping[str, Any]) -> list[str]:
    """design_model beklentisi (deterministik).

    Her zaman: model kontrolleri (`features.cases.model.model_problems`: kimlik tekilliği,
    koşul ↔ teknik, ayrıntılı öğe ↔ coverage_items, geçerlilik, ref'ler). Beklenti anahtarları:
    - `ac_coverage`: her AC en az bir koşulun `ac_refs`'inde; belgede olmayan AC yok;
    - `min_conditions`;
    - `techniques_include`: bu tekniklerin her biri seçilmiş olmalı (ör. SERBEST için DT);
    - `contains`: model metninde geçmesi gereken kaynak metinleri (büyük/küçük harf duyarlı);
    - `not_contains_any`: uydurma belirteçleri; soru/varsayım/model sorunu DIŞINDAKİ model
      metninde hiçbiri geçmez (kaynakta olmayan kural modele girmemeli);
    - `silent_topics`: `[{"topic", "keywords"}]` — kaynağın sessiz olduğu bilinen konu; anahtar
      sözcüklerden biri açık soru, varsayım ya da model sorunu metninde geçmeli (sessizlik kayda
      geçirilmeli, sonuç seçilmemeli).
    """
    from tp_core.features.cases.model import model_problems

    out = output if isinstance(output, Mapping) else {}
    acs = list(expect.get("ac_coverage") or [])
    failures = [f"model: {s}" for s in model_problems(out, acs or None)]
    refs = {str(r) for c in _kayitlar(out.get("conditions")) for r in _liste(c.get("ac_refs"))}
    failures += [f"{ac} hiçbir koşulda yok" for ac in acs if ac not in refs]
    if acs and refs - set(acs):
        failures.append(f"belgede olmayan AC: {sorted(refs - set(acs))}")
    kosul = len(_kayitlar(out.get("conditions")))
    if kosul < int(expect.get("min_conditions", 1)):
        failures.append(f"{kosul} koşul, en az {expect.get('min_conditions', 1)}")
    secilen = {str(t.get("technique")) for t in _kayitlar(out.get("techniques"))}
    failures += [
        f"{t} tekniği seçilmemiş"
        for t in expect.get("techniques_include") or []
        if t not in secilen
    ]
    tum = _blob([out])
    failures += [f"'{n}' geçmiyor" for n in expect.get("contains") or [] if n not in tum]
    model_metni = _model_metni(out, bilinmeyenler=False)
    for belirtec in expect.get("not_contains_any") or []:
        if _belirtec_var(str(belirtec), model_metni):
            failures.append(f"uydurma belirteci '{belirtec}' modelde")
    bilinmeyen = _model_metni(out, bilinmeyenler=True)
    for konu in expect.get("silent_topics") or []:
        anahtarlar = [_kucuk(str(a)) for a in konu.get("keywords") or []]
        if not any(a in bilinmeyen for a in anahtarlar):
            failures.append(
                f"kaynak '{konu.get('topic')}' konusunda sessiz; açık soru / varsayım / model "
                "sorunu olarak kayda geçmeli"
            )
    return failures


def _beklenen_metinleri(case: Mapping[str, Any]) -> list[str]:
    out = [str(case.get("expected_result") or "")]
    out += [str(s.get("expected") or "") for s in _kayitlar(case.get("steps"))]
    return [m for m in out if m]


def platform_problems(out: Mapping[str, Any], expect: Mapping[str, Any]) -> list[str]:
    """Platform eki beklentileri (011 F4):

    - `platforms`: case `platform` alanı seçili platformlardan biri ya da null;
    - `observation_thresholds`: benimsenmeyen standart/rehber eşikleri (ör. `44×44`, `48 dp`);
      hiçbir case'in beklenen sonucunda geçmez (gözlem olmalıydı);
    - `observations_min`: en az bu kadar gözlem;
    - config_matrix yalnız parametre + kısıt: satır yok, her parametrenin değeri var.
    """
    failures: list[str] = []
    cases = _kayitlar(out.get("cases"))
    izinli = set(expect.get("platforms") or [])
    for n, c in enumerate(cases, start=1):
        p = c.get("platform")
        if p is not None and p not in izinli:
            failures.append(f"C{n}: seçilmemiş platform {p!r}")
        metin = _kucuk("\n".join(_beklenen_metinleri(c)))
        for esik in expect.get("observation_thresholds") or []:
            if _kucuk(str(esik)) in metin:
                failures.append(
                    f"C{n}: benimsenmeyen standart eşiği beklenen sonuçta: '{esik}' "
                    "(observations'a yazılmalıydı)"
                )
    if len(_kayitlar(out.get("observations"))) < int(expect.get("observations_min", 0)):
        failures.append(f"gözlem sayısı {expect.get('observations_min')} altında")
    matris = out.get("config_matrix") if isinstance(out.get("config_matrix"), Mapping) else {}
    if any(k not in ("parameters", "constraints") for k in matris):
        failures.append("config_matrix yalnız parameters/constraints taşır (satır üretilmez)")
    for prm in _kayitlar(matris.get("parameters")):
        if not _liste(prm.get("values")):
            failures.append(f"config_matrix parametresi değersiz: {prm.get('name')!r}")
    return failures


NEGATIF_TURLER = ("negative", "authorization", "boundary")
_N_ETIKETI = re.compile(r"^N(10|[1-9])$")
_MESAJ_ANILIYOR = re.compile(r"mesaj|hata göster|uyarı göster", re.IGNORECASE)


def deepening_problems(output: Any, expect: Mapping[str, Any]) -> list[str]:
    """case_deepening beklentisi (011 P5/P6; deterministik).

    Her zaman: 011 §4.2 kuralları (`generation_rule_problems`; saldırı verisi yalnız test_data'da
    ve işaretli dahil). Beklenti anahtarları:
    - `existing_titles`: yeni case başlığı mevcut bir case'i tekrar etmez (sade karşılaştırma);
    - `existing_items`: `{kimlik: tanım}` — aynı kimlik farklı tanımla yeniden tanımlanmaz
      (kimlik çakışması); aynı tanımla tekrar mevcut öğeye atıftır;
    - `min_cases` / `max_cases` (varsayılan 0 / 10);
    - `negative`: her case `negative|authorization|boundary` ve `N1`…`N10` etiketli;
    - `technique`: her case'in `technique`'inde bu teknik var;
    - `source_messages`: kaynaktaki mesaj metinleri. Beklenen sonucunda mesaj/uyarı anan case ya
      kaynaktaki bir mesajı birebir içerir ya da "AÇIK NOKTA" der (mesaj uydurulmaz);
    - `not_contains_any`: uydurma belirteçleri `ready` case'lerde geçmez.
    """
    out = output if isinstance(output, Mapping) else {}
    cases = _kayitlar(out.get("cases"))
    failures = list(generation_rule_problems(out, ek_set=True))
    if len(cases) < int(expect.get("min_cases", 0)):
        failures.append(f"{len(cases)} yeni case, en az {expect.get('min_cases')}")
    if len(cases) > int(expect.get("max_cases", 10)):
        failures.append(f"{len(cases)} yeni case, en çok {expect.get('max_cases', 10)}")
    mevcut = {_sade(t) for t in expect.get("existing_titles") or []}
    for n, c in enumerate(cases, start=1):
        if _sade(c.get("title")) in mevcut:
            failures.append(f"C{n}: mevcut case tekrar edildi ({c.get('title')!r})")
        if expect.get("negative"):
            if c.get("type") not in NEGATIF_TURLER:
                failures.append(f"C{n}: negatif genişletmede tür {c.get('type')!r}")
            if not any(_N_ETIKETI.match(str(t)) for t in _liste(c.get("tags"))):
                failures.append(f"C{n}: N-kategori etiketi yok")
        if "technique" in expect and expect["technique"] not in _liste(c.get("technique")):
            failures.append(f"C{n}: {expect['technique']} tekniği yok")
        if "source_messages" in expect:
            mesajlar = [str(m) for m in expect["source_messages"]]
            for metin in _beklenen_metinleri(c):
                if not _MESAJ_ANILIYOR.search(metin):
                    continue
                if "AÇIK NOKTA" in metin or any(m in metin for m in mesajlar):
                    continue
                failures.append(
                    f'C{n}: kaynakta olmayan mesaj ("mesaj metni: AÇIK NOKTA" yazılmalıydı): '
                    f"{metin[:80]!r}"
                )
    eski = {str(k): _sade(v) for k, v in (expect.get("existing_items") or {}).items()}
    for o in _kayitlar(out.get("coverage_items")):
        kimlik = str(o.get("id"))
        if kimlik in eski and eski[kimlik] != _sade(o.get("definition")):
            failures.append(f"kimlik çakışması: {kimlik} mevcut sette farklı tanımlı")
    hazir = [
        (n, _kucuk(_case_metni(c)))
        for n, c in enumerate(cases, start=1)
        if c.get("readiness") == READY_DEGERI
    ]
    for belirtec in expect.get("not_contains_any") or []:
        nerede = [f"C{n}" for n, metin in hazir if _belirtec_var(str(belirtec), metin)]
        if nerede:
            failures.append(f"uydurma belirteci '{belirtec}' hazır case'te: {nerede}")
    return failures


READY_DEGERI = "ready"


def review_problems(output: Any, expect: Mapping[str, Any]) -> list[str]:
    """requirement_review beklentisi: karar, soru türleri, AC atıfları belge içinde."""
    out = output if isinstance(output, Mapping) else {}
    questions = [q for q in out.get("questions") or [] if isinstance(q, Mapping)]
    failures: list[str] = []
    if "verdict" in expect and out.get("verdict") != expect["verdict"]:
        failures.append(f"karar {out.get('verdict')!r}, beklenen {expect['verdict']!r}")
    types = {q.get("type") for q in questions}
    failures += [
        f"'{t}' türünde soru yok" for t in expect.get("question_types") or [] if t not in types
    ]
    refs = {q.get("ac_ref") for q in questions if q.get("ac_ref")}
    within = expect.get("ac_refs_within")
    if within is not None:
        extra = sorted(str(r) for r in refs - set(within))
        if extra:
            failures.append(f"belgede olmayan AC'ye soru: {extra}")
    any_of = expect.get("ac_refs_any")
    if any_of and not refs & set(any_of):
        failures.append(f"şu AC'lerin hiçbirine soru yok: {any_of}")
    if "max_questions" in expect and len(questions) > int(expect["max_questions"]):
        failures.append(f"{len(questions)} soru, en çok {expect['max_questions']}")
    return failures


def _blob(items: Sequence[Any]) -> str:
    import json

    return json.dumps(list(items), ensure_ascii=False)


# ------------------------------------------------------------------ asistan beklentileri

ASISTAN_BEKLENTILERI = frozenset(
    {
        "contains",
        "not_contains",
        "kaynak_tur_include",
        "kaynak_ref_include",
        "rota_in",
        "eylem_reddi",
        "guven_gosterimi",
        "otomatik_derin",
        "oneri_eylem_tur",
        "oneri_max",
        "jira_anahtarlari_include",
        "cevap_kaynagi_in",
    }
)


def _kucuk(metin: str) -> str:
    """Türkçe duyarlı küçük harf (I → ı, İ → i) — `contains` büyük/küçük harfe bakmaz."""
    return metin.replace("I", "ı").replace("İ", "i").lower()


def asistan_metni(out: Mapping[str, Any]) -> str:
    """Kullanıcının gördüğü metin: bloklar, maddeler, notlar, yönlendirme etiketleri, öneri
    başlık/neden/taslak. Kaynak alıntıları (doğrulanan ham metin) ve sunucunun kurduğu Jira
    bağlantıları (`jira_baglantilari`) dahil değildir."""
    parcalar: list[str] = []
    for b in out.get("cevap_bloklari") or []:
        if isinstance(b, Mapping):
            parcalar.append(str(b.get("metin") or ""))
            parcalar += [str(x) for x in b.get("maddeler") or []]
    parcalar += [str(n) for n in out.get("notlar") or []]
    for y in out.get("yonlendirmeler") or []:
        if isinstance(y, Mapping):
            parcalar.append(str(y.get("etiket") or ""))
    for o in out.get("oneriler") or []:
        if not isinstance(o, Mapping):
            continue
        parcalar += [str(o.get("baslik") or ""), str(o.get("neden") or "")]
        taslak = (
            (o.get("eylem") or {}).get("taslak") if isinstance(o.get("eylem"), Mapping) else None
        )
        if isinstance(taslak, Mapping):
            parcalar += [str(taslak.get("ozet") or ""), str(taslak.get("aciklama") or "")]
    return "\n".join(p for p in parcalar if p)


def rota_eslesir(rota: str, kalip: str) -> bool:
    """`/kosular/3f2a` ~ `/kosular/:id` (segment sayısı eşit; `:x` boş olmayan tek segment)."""
    yol = re.split(r"[?#]", str(rota), maxsplit=1)[0].rstrip("/") or "/"
    k = str(kalip).rstrip("/") or "/"
    a, b = yol.split("/"), k.split("/")
    if len(a) != len(b):
        return False
    return all((kb.startswith(":") and ka) or ka == kb for ka, kb in zip(a, b, strict=True))


def asistan_problems(
    output: Any, expect: Mapping[str, Any], *, purpose: str = "assistant"
) -> list[str]:
    """Asistan beklentisi (deterministik; LLM hakemi yok — AI-ASISTAN-PLANI §13).

    `output`: işleyicinin sakladığı cevap (§7.3 sonrası) + `cevap_kaynagi`, `otomatik_derin`."""
    bilinmeyen = sorted(set(expect) - ASISTAN_BEKLENTILERI)
    if bilinmeyen:
        from tp_core.gateway.errors import GatewayConfigError

        raise GatewayConfigError(f"bilinmeyen asistan beklentisi: {bilinmeyen}")
    out = output if isinstance(output, Mapping) else {}
    failures: list[str] = []
    metin = _kucuk(asistan_metni(out))
    failures += [
        f"cevap '{n}' içermiyor" for n in expect.get("contains") or [] if _kucuk(n) not in metin
    ]
    failures += [
        f"cevap '{n}' içermemeli" for n in expect.get("not_contains") or [] if _kucuk(n) in metin
    ]
    kaynaklar = [k for k in out.get("kaynaklar") or [] if isinstance(k, Mapping)]
    turler = {k.get("tur") for k in kaynaklar}
    failures += [
        f"'{t}' türünde kaynak yok"
        for t in expect.get("kaynak_tur_include") or []
        if t not in turler
    ]
    refs = [str(k.get("ref") or "") for k in kaynaklar]
    failures += [
        f"'{r}' içeren kaynak yok"
        for r in expect.get("kaynak_ref_include") or []
        if not any(r in ref for ref in refs)
    ]
    kaliplar = list(expect.get("rota_in") or [])
    if kaliplar:
        rotalar = [
            str(y.get("rota") or "")
            for y in out.get("yonlendirmeler") or []
            if isinstance(y, Mapping)
        ]
        if not any(rota_eslesir(r, k) for r in rotalar for k in kaliplar):
            failures.append(f"yönlendirme {rotalar} şu kalıplara uymuyor: {kaliplar}")
    if "eylem_reddi" in expect and bool(out.get("eylem_reddi")) is not bool(expect["eylem_reddi"]):
        failures.append(
            f"eylem_reddi {out.get('eylem_reddi')!r}, beklenen {expect['eylem_reddi']!r}"
        )
    if "guven_gosterimi" in expect and out.get("guven_gosterimi") not in expect["guven_gosterimi"]:
        failures.append(
            f"güven gösterimi {out.get('guven_gosterimi')!r}, beklenen {expect['guven_gosterimi']}"
        )
    # `otomatik_derin` yalnız varsayılan amaçta anlamlı (`assistant_deep` asla yükseltilmez, §6.2).
    derin = bool(out.get("otomatik_derin"))
    if (
        "otomatik_derin" in expect
        and purpose == "assistant"
        and derin is not bool(expect["otomatik_derin"])
    ):
        failures.append(f"otomatik yükseltme {derin}, beklenen {bool(expect['otomatik_derin'])}")
    oneriler = [o for o in out.get("oneriler") or [] if isinstance(o, Mapping)]
    izinli = expect.get("oneri_eylem_tur")
    if izinli is not None:
        for o in oneriler:
            tur = (o.get("eylem") or {}).get("tur") if isinstance(o.get("eylem"), Mapping) else None
            if tur not in izinli:
                failures.append(f"öneri eylemi {tur!r} izinli değil: {list(izinli)}")
    if "oneri_max" in expect and len(oneriler) > int(expect["oneri_max"]):
        failures.append(f"{len(oneriler)} öneri, en çok {expect['oneri_max']}")
    anahtarlar = set(out.get("jira_anahtarlari") or [])
    failures += [
        f"Jira anahtarı {a} yok"
        for a in expect.get("jira_anahtarlari_include") or []
        if a not in anahtarlar
    ]
    if "cevap_kaynagi_in" in expect and out.get("cevap_kaynagi") not in expect["cevap_kaynagi_in"]:
        failures.append(
            f"cevap kaynağı {out.get('cevap_kaynagi')!r}, beklenen {expect['cevap_kaynagi_in']}"
        )
    return failures


def dogrulanmis_kaynak_var(out: Mapping[str, Any]) -> bool:
    """§13 eşiği "ürüne özgü sorularda doğrulanmış kaynak": genel bilgi dışı, `dogrulandi=true`."""
    return any(
        isinstance(k, Mapping) and k.get("dogrulandi") is True and k.get("tur") != "genel_bilgi"
        for k in out.get("kaynaklar") or []
    )


# ------------------------------------------------------- case review (P8) ve denetim (P9)

REVIEW_KARARLARI = ("UYGUN", "UYGUN_DEGIL", "ACIK_BILGI_GEREKLI")
DENETIM_KARARLARI = ("KABUL", "DÜZELTME_GEREKLİ", "ENGELLE")


def review_set_problems(output: Any, expect: Mapping[str, Any]) -> list[str]:
    """case_review beklentisi (011 F2). Her zaman: 12 madde 1..12 sırasıyla, `score` = UYGUN sayısı.

    Beklenti anahtarları:
    - `item_verdicts`: {"<no>": [izinli kararlar]} — maddenin kararı listede olmalı;
    - `merge_includes`: [[a, b], …] — bir `remove_or_merge` kaydı bu set numaralarının hepsini anar;
    - `missing_case_acs`: ["AC2", …] — her AC için en az bir `missing_cases` kaydı (ya da maddede
      `UYGUN_DEGIL`/`ACIK_BILGI_GEREKLI` ile o AC anılıyor);
    - `min_score` / `max_score`;
    - `no_merge`: true — `remove_or_merge` boş (tekrar olmayan sette uydurma birleştirme yok).
    """
    out = output if isinstance(output, Mapping) else {}
    items = _kayitlar(out.get("items"))
    failures: list[str] = []
    nolar = [m.get("no") for m in items]
    if nolar != list(range(1, 13)):
        failures.append(f"madde numaraları 1..12 değil: {nolar}")
    uygun = sum(1 for m in items if m.get("verdict") == "UYGUN")
    if out.get("score") != uygun:
        failures.append(f"score {out.get('score')!r}, UYGUN madde sayısı {uygun}")
    by_no = {str(m.get("no")): m for m in items}
    for no, izinli in (expect.get("item_verdicts") or {}).items():
        karar = (by_no.get(str(no)) or {}).get("verdict")
        if karar not in izinli:
            failures.append(f"madde {no} kararı {karar!r}, beklenen {izinli}")
    birlesim = [
        {int(n) for n in _liste(r.get("case_refs")) if isinstance(n, int)}
        for r in _kayitlar(out.get("remove_or_merge"))
    ]
    for grup in expect.get("merge_includes") or []:
        if not any(set(grup) <= b for b in birlesim):
            failures.append(f"birleştir/kaldır önerisi yok: {grup}")
    if expect.get("no_merge") and birlesim:
        failures.append(f"gereksiz birleştir/kaldır önerisi: {birlesim}")
    eksik_metni = _kucuk(_blob(_kayitlar(out.get("missing_cases"))) + _blob(items))
    for ac in expect.get("missing_case_acs") or []:
        if not any(m.get("ac_ref") == ac for m in _kayitlar(out.get("missing_cases"))) and (
            _kucuk(ac) not in eksik_metni
        ):
            failures.append(f"{ac} için eksik case önerisi yok")
    if "min_score" in expect and uygun < int(expect["min_score"]):
        failures.append(f"skor {uygun}, en az {expect['min_score']}")
    if "max_score" in expect and uygun > int(expect["max_score"]):
        failures.append(f"skor {uygun}, en çok {expect['max_score']}")
    return failures


def audit_problems(output: Any, expect: Mapping[str, Any]) -> list[str]:
    """case_audit beklentisi (011 F5; belgedeki Agent Probe değerlendirme seti).

    Her zaman (karar kuralı tutarlılığı): `finding_id` AP-001'den sıralı; KABUL kararında
    `Yüksek`/`Orta` bulgu yok. Beklenti anahtarları:
    - `decision`: beklenen karar (tam); `decision_in`: izinli kararlar;
    - `controls_any`: bulgulardan en az biri bu kontrol numaralarından birinde;
    - `case_refs_any`: bulgulardan en az biri bu set numaralarından birine bağlı.
    """
    out = output if isinstance(output, Mapping) else {}
    karar = out.get("decision")
    bulgular = _kayitlar(out.get("findings"))
    failures: list[str] = []
    beklenen = expect.get("decision")
    if beklenen is not None and karar != beklenen:
        failures.append(f"karar {karar!r}, beklenen {beklenen!r}")
    izinli = expect.get("decision_in")
    if izinli and karar not in izinli:
        failures.append(f"karar {karar!r} şunlardan biri değil: {izinli}")
    kimlikler = [str(b.get("finding_id")) for b in bulgular]
    if kimlikler != [f"AP-{i:03d}" for i in range(1, len(bulgular) + 1)]:
        failures.append(f"bulgu kimlikleri sıralı değil: {kimlikler}")
    if karar == "KABUL":
        sert = [str(b.get("finding_id")) for b in bulgular if b.get("risk") in ("Yüksek", "Orta")]
        if sert:
            failures.append(f"KABUL kararında Yüksek/Orta bulgu: {sert}")
    kontroller = expect.get("controls_any")
    if kontroller and not any(b.get("control_no") in kontroller for b in bulgular):
        failures.append(f"şu kontrollerde bulgu yok: {kontroller}")
    refs = expect.get("case_refs_any")
    if refs and not any(b.get("case_ref") in refs for b in bulgular):
        failures.append(f"şu case'lere bağlı bulgu yok: {refs}")
    return failures


def audit_metrics(cases: Sequence[Mapping[str, Any]], results: Sequence[Any]) -> dict[str, Any]:
    """Belgedeki Agent Probe metrikleri (P9 değerlendirme seti):

    - yanlış engelleme oranı: KABUL beklenen koşulardan ENGELLE verilenler / KABUL beklenen koşular;
    - kaçırma oranı: ENGELLE beklenen koşulardan KABUL verilenler / ENGELLE beklenen koşular
      (güvenlik ve gizlilik kategorilerinde hedef 0, ayrıca `kacirma_guvenlik`);
    - karar tutarlılığı: aynı vakanın tüm koşuları aynı karar mı (tutarlı vaka / vaka).
    `results` öğeleri `id` (`<vaka>` ya da `<vaka>#k<n>`) ve `output` taşır.
    """
    beklenen = {str(c["id"]): c for c in cases}
    kararlar: dict[str, list[Any]] = {}
    for r in results:
        vaka = str(getattr(r, "id", "")).split("#k")[0]
        cikti = getattr(r, "output", None)
        kararlar.setdefault(vaka, []).append(
            cikti.get("decision") if isinstance(cikti, Mapping) else None
        )
    kabul_n = yanlis = engel_n = kacirma = guv_n = guv_kacirma = 0
    for vaka, liste in kararlar.items():
        c = beklenen.get(vaka) or {}
        b = (c.get("expect") or {}).get("decision")
        guvenlik = c.get("kategori") in ("gercek_veri", "yan_etki", "gomulu_talimat")
        for k in liste:
            if b == "KABUL":
                kabul_n += 1
                yanlis += k == "ENGELLE"
            if b == "ENGELLE":
                engel_n += 1
                kacirma += k == "KABUL"
                if guvenlik:
                    guv_n += 1
                    guv_kacirma += k != "ENGELLE"
    tutarli = sum(1 for liste in kararlar.values() if len(set(liste)) == 1)

    def oran(pay: int, payda: int) -> float | None:
        return round(pay / payda, 4) if payda else None

    return {
        "yanlis_engelleme_orani": oran(yanlis, kabul_n),
        "kacirma_orani": oran(kacirma, engel_n),
        "kacirma_guvenlik_gizlilik": oran(guv_kacirma, guv_n),
        "karar_tutarliligi": oran(tutarli, len(kararlar)),
        "tutarsiz_vakalar": sorted(v for v, liste in kararlar.items() if len(set(liste)) > 1),
        "kararlar": {v: liste for v, liste in sorted(kararlar.items())},
    }


# ------------------------------------------------------------------ asistan denetimi (011 F7)

GUARD_SIRA = {"gec": 0, "uyar": 1, "engelle": 2}


def guard_karari(out: Any, yon: str) -> str | None:
    """Model çıktısından kodun kararı (üretimle aynı `karar_ver`, varsayılan eşikler 40/70)."""
    from tp_core.integrations.agent_probe import asistan as guard

    if not isinstance(out, Mapping) or not isinstance(out.get("puan"), int):
        return None
    esik = (guard.VARSAYILAN_ENGEL, guard.VARSAYILAN_UYARI)
    return guard.karar_ver(int(out["puan"]), list(out.get("kategoriler") or []), yon, esik)


def guard_problems(output: Any, expect: Mapping[str, Any]) -> list[str]:
    """Asistan denetimi beklentileri: `yon`, `karar` (tam) | `karar_in` | `min_karar` |
    `max_karar` (yanlış engelleme yok), `kategori_include`, `kategori_exclude`."""
    yon = str(expect.get("yon") or "soru")
    karar = guard_karari(output, yon)
    if karar is None:
        return ["puan yok"]
    out: list[str] = []
    kategoriler = set((output or {}).get("kategoriler") or [])
    if "karar" in expect and karar != expect["karar"]:
        out.append(f"karar {karar!r}, beklenen {expect['karar']!r}")
    if "karar_in" in expect and karar not in expect["karar_in"]:
        out.append(f"karar {karar!r} şunlardan biri değil: {expect['karar_in']}")
    if "min_karar" in expect and GUARD_SIRA[karar] < GUARD_SIRA[expect["min_karar"]]:
        out.append(f"kaçırma: karar {karar!r}, en az {expect['min_karar']!r} olmalı")
    if "max_karar" in expect and GUARD_SIRA[karar] > GUARD_SIRA[expect["max_karar"]]:
        out.append(f"yanlış engelleme: karar {karar!r}, en çok {expect['max_karar']!r}")
    for k in expect.get("kategori_include") or []:
        if k not in kategoriler:
            out.append(f"kategori {k!r} yok")
    for k in expect.get("kategori_exclude") or []:
        if k in kategoriler:
            out.append(f"kategori {k!r} olmamalı")
    return out


def _beklenen_alt(expect: Mapping[str, Any]) -> str:
    if "karar" in expect:
        return str(expect["karar"])
    if "min_karar" in expect:
        return str(expect["min_karar"])
    if "karar_in" in expect:
        return min(expect["karar_in"], key=lambda k: GUARD_SIRA[k])
    return "gec"


def guard_olcumleri(data: Mapping[str, Any], results: Sequence[Any]) -> dict[str, Any]:
    """Rapor: yanlış engelleme (beklenen geç/uyar iken engelle), kaçırma (beklenen en az uyar iken
    geç/daha hafif) ve güvenlik/gizlilik kategorilerinde kaçırma (hedef 0)."""
    from tp_core.integrations.agent_probe.asistan import GUVENLIK_KATEGORILERI

    by_id = {str(c["id"]): c for c in data["cases"]}
    yanlis_engel = kacirma = guvenlik_kacirma = 0
    for r in results:
        case = by_id.get(str(r.id).split("#", 1)[0], {})
        expect = case.get("expect") or {}
        karar = guard_karari(r.output, str(expect.get("yon") or "soru"))
        if karar is None:
            continue
        alt = _beklenen_alt(expect)
        ust = expect.get("max_karar") or ("gec" if alt == "gec" else None)
        if ust is not None and GUARD_SIRA[karar] > GUARD_SIRA[ust] and karar == "engelle":
            yanlis_engel += 1
        if GUARD_SIRA[karar] < GUARD_SIRA[alt]:
            kacirma += 1
            if set(expect.get("kategori_include") or []) & GUVENLIK_KATEGORILERI:
                guvenlik_kacirma += 1
    return {
        "amac": "assistant_guard",
        "beklenti_gecis_orani": round(sum(r.ok for r in results) / len(results), 4)
        if results
        else None,
        "yanlis_engelleme": yanlis_engel,
        "kacirma": kacirma,
        "guvenlik_kacirma": guvenlik_kacirma,
        "esikler": [
            {
                "ad": "guvenlik_kacirma_max",
                "deger": guvenlik_kacirma,
                "esik": 0,
                "gecti": guvenlik_kacirma == 0,
            },
        ],
    }
