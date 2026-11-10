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


def coverage_problems(output: Any, expect: Mapping[str, Any]) -> list[str]:
    """case_generation beklentisi: her AC en az bir case'te, bilinmeyen AC yok, case sayısı,
    metin içerir/içermez (tüm case'lerin birleşik metni)."""
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
    blob = _blob(cases)
    failures += [f"'{n}' geçmiyor" for n in expect.get("contains") or [] if n not in blob]
    failures += [f"'{n}' geçmemeli" for n in expect.get("not_contains") or [] if n in blob]
    return failures


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
