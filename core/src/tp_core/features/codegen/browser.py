"""Doğrulama ajanının tarayıcısı: Playwright MCP (streamable HTTP) vekili (TEKNIK-TASARIM §8.4).

- `McpBrowserSession`: resmi `mcp` SDK istemcisi (`mcp.Client`, streamable HTTP) üstünde eşzamanlı
  sarmalayıcı. SDK asenkrondur; model geçidinin araç yürütücüsü eşzamanlıdır. Oturum kendi iş
  parçacığındaki tek bir olay döngüsünde açılır ve kapanır (anyio iptal kapsamları aynı görevde
  kalır); çağrılar kuyrukla o göreve iletilir.
- `AgentBrowser`: ajana verilen araçlar = MCP `tools/list` ∩ `ALLOWED_AGENT_TOOLS['verify_and_map']`
  (`browser_take_screenshot`, `browser_evaluate`, `browser_run_code*`, dosya/ağ araçları hiçbir
  zaman verilmez; Constitution V). Her araç sonucu `<untrusted kind="snapshot">` bloğuna sarılır.
  `browser_navigate` yalnızca demo uygulaması origin'ine gider. Ajan başına en çok 25 araç çağrısı.
- **Ajan bayisi:** tarayıcı oturumu e2e işçilerinin bayileriyle (bayi1/bayi2) çakışmasın diye
  `browser_type` ile giriş alanına yazılan e2e bayi kullanıcı adı araç katmanında ajan bayisine
  (`TP_AGENT_DEALER`, varsayılan `bayi3`; demo-app seed'i) çevrilir. Model eşlemede case'teki
  bayiyi yazar; üretilen test o bayiye sabitlenir. Ajan bayisinin kullanıcı adı yazıldıktan sonra
  parola alanına bir bayinin GERÇEK parolası yazılırsa ajan bayisinin parolasıyla
  (`TP_AGENT_DEALER_PASSWORD`) değiştirilir; başka her değer (hatalı parola case'i) olduğu gibi
  yazılır, giriş ajan için de başarısız olur.
- **Ajan bayisi kilidi:** `ajan_bayisi_kilidi` — bayinin sepeti paylaşılan durumdur; doğrulama
  oturumu (ve `replay_check`) Postgres danışma kilidi altında koşar.
- **Gizli değerler:** ajan parolası ve parola alanlarına yazılan her metin araç sonucunda `***`
  olarak maskelenir (modele, denetime, `script_adim`'e ve SSE'ye düz parola gitmez).
- **Araç sonucu:** her çağrının yapılandırılmış sonucu (`AracSonucu`: başarılı mı, hata, sayfa
  adresi) tutulur; Playwright MCP `isError` döndürürse `McpToolError` fırlatılır, böylece model
  geçidi araç sonucunu `is_error=true` kaydeder (ön ek tahmini yok).
- **Canlı görünüm:** her eylemden sonra çekirdek, model döngüsünün DIŞINDA bir MCP çağrısıyla
  (`browser_take_screenshot`) ekran görüntüsü alır ve diske yazar; görüntü modele gitmez.
  Playwright MCP `--isolated` koştuğu için her MCP oturumunun ayrı bir tarayıcı bağlamı vardır;
  ajanın sayfasını görmenin tek yolu aynı oturumdur. Bu yüzden görüntü oturumu varsayılan olarak
  ajanın oturumudur (çağrı ve sonucu modele hiç girmez); ayrı bir oturum verilirse (paylaşılan
  bağlam, `--shared-browser-context`) o kullanılır.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import contextlib
import json
import logging
import os
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from tp_core.gateway import ALLOWED_AGENT_TOOLS, FORBIDDEN_TOOLS, wrap_tool_result
from tp_core.gateway.snapshot_refs import SNAPSHOT_REF, is_inline_snapshot, snapshot_lines
from tp_core.ports import ToolSpec

log = logging.getLogger(__name__)

PURPOSE = "verify_and_map"
MAX_TOOL_CALLS = 25
SCREENSHOT_TOOL = "browser_take_screenshot"
DEFAULT_DEMO_WEB_URL = "http://demo-app-web:8080"
DEFAULT_AGENT_DEALER = "bayi3"
DEFAULT_AGENT_PASSWORD = "Demo123!"
_GIZLI_ALAN = re.compile(r"parola|password|sifre|şifre", re.I)
MAX_IMAGE_BYTES = 8 * 1024 * 1024


class BrowserError(RuntimeError):
    pass


class ToolBudgetExceeded(BrowserError):
    pass


class McpToolError(BrowserError):
    """Playwright MCP aracı `isError` döndürdü (eleman yok, gezinme başarısız …)."""


@dataclass(frozen=True)
class AracSonucu:
    """Tek tarayıcı çağrısının yapılandırılmış sonucu (özet metninden tahmin edilmez)."""

    tool: str
    ok: bool
    hata: str | None = None
    url: str | None = None


_URL_RE = re.compile(r"(?:Page URL:\s*|\bURL\s+)(\S+)")


def sayfa_adresi(metin: str | None) -> str | None:
    """Araç çıktısındaki sayfa adresinin yolu (`Page URL: http://h/sepet` → `/sepet`)."""
    m = _URL_RE.search(metin or "")
    if m is None:
        return None
    url = m.group(1).rstrip(".,;)")
    if "://" in url:
        url = "/" + url.split("://", 1)[1].partition("/")[2]
    return url[:200] or "/"


@dataclass
class ToolOutput:
    text: str
    images: list[tuple[str, bytes]] = field(default_factory=list)
    is_error: bool = False


class BrowserSession(Protocol):
    def list_tools(self) -> list[dict[str, Any]]: ...
    def call(self, name: str, args: Mapping[str, Any]) -> ToolOutput: ...
    def close(self) -> None: ...


def _output_of(result: Any) -> ToolOutput:
    texts: list[str] = []
    images: list[tuple[str, bytes]] = []
    for block in getattr(result, "content", None) or []:
        tur = getattr(block, "type", None)
        if tur == "text":
            texts.append(str(block.text))
        elif tur == "image":
            try:
                veri = base64.b64decode(block.data, validate=False)
            except (ValueError, TypeError):
                continue
            images.append((str(getattr(block, "mime_type", "image/png")), veri))
    return ToolOutput("\n".join(texts), images, bool(getattr(result, "is_error", False)))


class McpBrowserSession:
    """`mcp.Client(url)` (streamable HTTP) — tek olay döngüsü, tek görev, eşzamanlı arayüz.

    `target` bir URL'dir (Playwright MCP, `PLAYWRIGHT_MCP_URL`); testlerde SDK'nın süreç içi
    sunucu nesnesi de verilebilir (aynı `mcp.Client` kod yolu).
    """

    def __init__(
        self, target: Any, *, timeout_s: float = 60.0, connect_timeout_s: float = 30.0
    ) -> None:
        self.url = target if isinstance(target, str) else type(target).__name__
        self._target = target
        self.timeout_s = timeout_s
        self._loop = asyncio.new_event_loop()
        self._queue: asyncio.Queue[Any] | None = None
        self._ready = concurrent.futures.Future[None]()
        self._done = concurrent.futures.Future[None]()
        self._thread = threading.Thread(target=self._run, name="mcp-browser", daemon=True)
        self._thread.start()
        try:
            self._ready.result(timeout=connect_timeout_s)
        except Exception as exc:
            self.close()
            raise BrowserError(f"Playwright MCP'ye bağlanılamadı ({self.url}): {exc}") from exc

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except BaseException as exc:  # pragma: no cover - bağlantı hatası _ready'ye taşınır
            if not self._ready.done():
                self._ready.set_exception(exc)
        finally:
            if not self._done.done():
                self._done.set_result(None)

    async def _main(self) -> None:
        from mcp import Client

        self._queue = asyncio.Queue()
        async with Client(self._target, read_timeout_seconds=self.timeout_s) as client:
            self._ready.set_result(None)
            while True:
                item = await self._queue.get()
                if item is None:
                    break
                fn, fut = item
                try:
                    fut.set_result(await fn(client))
                except BaseException as exc:
                    fut.set_exception(exc)

    def _submit(self, fn: Callable[[Any], Any]) -> Any:
        if self._queue is None or self._done.done():
            raise BrowserError("MCP oturumu kapalı")
        fut: concurrent.futures.Future[Any] = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (fn, fut))
        return fut.result(timeout=self.timeout_s + 5)

    def list_tools(self) -> list[dict[str, Any]]:
        async def fn(client: Any) -> list[dict[str, Any]]:
            res = await client.list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description or t.name,
                    "input_schema": dict(t.input_schema or {"type": "object"}),
                }
                for t in res.tools
            ]

        return self._submit(fn)

    def call(self, name: str, args: Mapping[str, Any]) -> ToolOutput:
        async def fn(client: Any) -> ToolOutput:
            return _output_of(await client.call_tool(name, dict(args)))

        return self._submit(fn)

    def close(self) -> None:
        if self._queue is not None and not self._done.done():
            with contextlib.suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
        self._thread.join(timeout=10)
        if not self._loop.is_running():
            with contextlib.suppress(Exception):
                self._loop.close()


# ----------------------------------------------------------------------- ajan vekili


@dataclass(frozen=True)
class AgentConfig:
    demo_web_url: str = DEFAULT_DEMO_WEB_URL
    agent_dealer: str = DEFAULT_AGENT_DEALER
    agent_password: str = DEFAULT_AGENT_PASSWORD
    max_tool_calls: int = MAX_TOOL_CALLS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AgentConfig:
        env = os.environ if env is None else env
        return cls(
            demo_web_url=(env.get("TP_DEMO_WEB_URL") or DEFAULT_DEMO_WEB_URL).rstrip("/"),
            agent_dealer=env.get("TP_AGENT_DEALER") or DEFAULT_AGENT_DEALER,
            agent_password=env.get("TP_AGENT_DEALER_PASSWORD") or DEFAULT_AGENT_PASSWORD,
        )


def ajan_kilit_anahtari(dealer: str) -> str:
    return f"agent-dealer:{dealer}"


@contextlib.contextmanager
def ajan_bayisi_kilidi(engine: Any = None, dealer: str | None = None) -> Any:
    """Ajan bayisinin (bayi3) sepeti sunucu tarafında paylaşılan durumdur: sepet sıfırlama +
    doğrulama oturumu boyunca başka bir süreç (kod üretimi, `replay_check`/`make demo-check`, …)
    aynı bayiyle tarayıcı sürmesin diye Postgres oturum düzeyi danışma kilidi
    (`pg_advisory_lock(hashtext('agent-dealer:<bayi>'))`) tutulur; tüm süreçler arasında geçerli.

    `engine` verilmezse `tp_core.db.get_engine()` kullanılır (core-worker içindeki araçlar için).
    """
    from sqlalchemy import text

    if engine is None:
        from tp_core.db import get_engine

        engine = get_engine()
    anahtar = ajan_kilit_anahtari(dealer or AgentConfig.from_env().agent_dealer)
    conn = engine.connect()
    try:
        conn.execute(text("SELECT pg_advisory_lock(hashtext(:k))"), {"k": anahtar})
        conn.commit()
        yield
    finally:
        try:
            conn.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": anahtar})
            conn.commit()
        except Exception:  # pragma: no cover - kilit bağlantıyla birlikte düşer
            conn.invalidate()
        conn.close()


def reset_agent_cart(cfg: AgentConfig, *, client: Any = None) -> bool:
    """Ajan bayisinin sepetini doğrulama öncesi boşaltır (demo uygulamasının HERKESE AÇIK API'si).

    REPLAY yörüngeleri ve canlı ajan boş sepet varsayar (sepete ekleme var olana ekler: 7+7=14).
    core-worker yalnızca `demo-app-web`e (core-net) ulaşır; `/api/test/*` kapalıdır. Bu yüzden
    ajan bayisiyle giriş yapılıp `DELETE /api/cart` çağrılır. Hata doğrulamayı durdurmaz (uyarı).
    """
    import httpx

    sahip = client is None
    http = client or httpx.Client(base_url=cfg.demo_web_url, timeout=10.0)
    try:
        r = http.post(
            "/api/auth/login",
            json={"kullanici_adi": cfg.agent_dealer, "parola": cfg.agent_password},
        )
        r.raise_for_status()
        r = http.delete("/api/cart")
        r.raise_for_status()
        http.post("/api/auth/logout")
        return True
    except Exception as exc:  # ağ/uygulama hatası: doğrulama yine de denenir
        log.warning("ajan bayisinin sepeti boşaltılamadı: %s", exc)
        return False
    finally:
        if sahip:
            http.close()


# (çağrı no, png) → TP_ARTIFACTS_PATH'e göreli yol
ScreenshotSink = Callable[[int, bytes], str | None]


def allowed_tools() -> frozenset[str]:
    return frozenset(ALLOWED_AGENT_TOOLS[PURPOSE]) - FORBIDDEN_TOOLS


def parola_alani(args: Mapping[str, Any]) -> bool:
    hedef = " ".join(str(args.get(k) or "") for k in ("element", "target", "ref", "selector"))
    return bool(_GIZLI_ALAN.search(hedef))


def mask_args(args: Mapping[str, Any]) -> dict[str, Any]:
    """Kayıt için araç argümanları: parola alanına yazılan metin gizlenir."""
    out = dict(args)
    if "text" in out and parola_alani(out):
        out["text"] = "***"
    return out


def gizle(metin: str, gizliler: Sequence[str] | set[str] | frozenset[str]) -> str:
    """Metindeki gizli değerleri `***` yapar (uzundan kısaya; 3 karakterden kısalar atlanır)."""
    for g in sorted({g for g in gizliler if isinstance(g, str) and len(g) >= 3}, key=len)[::-1]:
        metin = metin.replace(g, "***")
    return metin


GENERATE_LOCATOR = "browser_generate_locator"
_SNAP_SATIR = re.compile(
    r'^(?P<indent>\s*)- (?P<rol>[a-z][a-z0-9-]*)(?: "(?P<ad>(?:[^"\\]|\\.)*)")?'
)
_URUN_KODU = re.compile(r"\b([A-Z]{1,4}-\d{2,})\b")


@dataclass(frozen=True)
class LocatorHedefi:
    """`browser_generate_locator` hedefinin CANLI son snapshot'taki karşılığı (modelin yazdığı
    `element` metninden bağımsız; locator çapraz kontrolü bununla beklenen testId'yi bulur)."""

    target: str | None
    ref_gecerli: bool  # `target` snapshot ref'i mi (`e12`)? Seçici/CSS değil.
    rol: str | None = None
    ad: str | None = None
    kod: str | None = None  # elemanın kartındaki ürün kodu (`P-001`)


def _indent(satir: str) -> int:
    return len(satir) - len(satir.lstrip(" "))


def locator_hedefi(satirlar: Sequence[str] | None, target: Any) -> LocatorHedefi:
    """Ref'i son snapshot'ta bulur: rol, erişilebilir ad ve kart kapsamındaki ürün kodu."""
    ref = target if isinstance(target, str) else None
    if ref is None or not SNAPSHOT_REF.match(ref):
        return LocatorHedefi(ref, False)
    if not satirlar:
        return LocatorHedefi(ref, True)
    isaret = f"[ref={ref}]"
    idx = next((i for i, x in enumerate(satirlar) if isaret in x), None)
    if idx is None:
        return LocatorHedefi(ref, True)
    satir = satirlar[idx]
    m = _SNAP_SATIR.match(satir)
    rol = m["rol"] if m else None
    ad = m["ad"] if m and m["ad"] is not None else None
    kod_m = _URUN_KODU.search(ad or "")
    kod = kod_m.group(1) if kod_m else None
    if kod is None:
        # Kart kapsamı: en yakın üst eleman (daha az girintili) ve onun bloğundaki ürün kodu.
        girinti = _indent(satir)
        ust = next((i for i in range(idx - 1, -1, -1) if _indent(satirlar[i]) < girinti), None)
        if ust is not None:
            ust_g = _indent(satirlar[ust])
            kodlar: set[str] = set()
            for x in satirlar[ust + 1 :]:
                if x.strip() and _indent(x) <= ust_g:
                    break
                kodlar.update(_URUN_KODU.findall(x))
            # Kart: üst elemanın bloğunda tek ürün kodu. Birden çoksa (sayfa gövdesi) kapsam yok.
            if len(kodlar) == 1:
                kod = kodlar.pop()
    return LocatorHedefi(ref, True, rol, ad, kod)


class AgentBrowser:
    """Model geçidinin `ToolExecutor`'ı: izin listesi, güvenilmeyen sarma, ajan bayisi, görüntü."""

    def __init__(
        self,
        session: BrowserSession,
        *,
        config: AgentConfig | None = None,
        case_dealers: Sequence[str] = (),
        screenshot_session: BrowserSession | None = None,
        screenshot_sink: ScreenshotSink | None = None,
        step_offset: int = 0,
        secrets: Sequence[str] = (),
        case_passwords: Sequence[str] = (),
    ) -> None:
        self.session = session
        self.config = config or AgentConfig()
        self.case_dealers = frozenset(d for d in case_dealers if d != self.config.agent_dealer)
        self.screenshot_session = screenshot_session or session
        self.screenshot_sink = screenshot_sink
        self.step_offset = step_offset
        self.calls = 0
        self.last_screenshot: str | None = None
        self.substitutions = 0
        # e2e bayisi → ajan bayisi (portal/PR "ajan bayisiyle doğrulandı" notu için)
        self.yerine_gecenler: dict[str, str] = {}
        self.gizliler: set[str] = {self.config.agent_password, *secrets}
        # Bayilerin GERÇEK parolaları (e2e fikstürleri + demo tohum parolası + ajanınki). Ajan
        # bayisiyle girişte yalnızca bunlardan biri yazılırsa ajan parolasıyla değiştirilir;
        # başka her değer (ör. "hatalı parola" case'i) olduğu gibi yazılır → negatif case
        # ajan bayisiyle de yeniden üretilir.
        self.gercek_parolalar: frozenset[str] = frozenset(
            p
            for p in (self.config.agent_password, DEFAULT_AGENT_PASSWORD, *case_passwords)
            if isinstance(p, str) and p
        )
        self._ajan_girisi = False
        self._son_sonuc: AracSonucu | None = None
        self._son_snapshot: list[str] | None = None  # bu oturumun son canlı snapshot'ı
        self._son_locator_hedefi: LocatorHedefi | None = None
        self._specs: list[ToolSpec] | None = None

    def tool_specs(self) -> list[ToolSpec]:
        """MCP `tools/list` ∩ izin listesi (ajana verilen araçlar)."""
        if self._specs is None:
            izinli = allowed_tools()
            self._specs = [
                ToolSpec(
                    name=t["name"],
                    description=str(t.get("description") or t["name"])[:1000],
                    input_schema=dict(t.get("input_schema") or {"type": "object"}),
                )
                for t in sorted(self.session.list_tools(), key=lambda t: t["name"])
                if t.get("name") in izinli
            ]
        return self._specs

    def _hazirla(self, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
        if name not in allowed_tools():
            raise BrowserError(f"araç izinli değil: {name}")
        out = dict(args)
        if name == "browser_navigate":
            url = str(out.get("url") or "")
            kok = self.config.demo_web_url
            if not (url == kok or url.startswith(kok + "/")):
                raise BrowserError(f"yalnızca demo uygulamasına gidilebilir ({kok})")
        metin = out.get("text")
        if name == "browser_type" and isinstance(metin, str):
            if parola_alani(out):
                self.gizliler.add(metin)
                if self._ajan_girisi and metin in self.gercek_parolalar:
                    # Ajan bayisiyle giriş: case bayisinin gerçek parolası → ajan bayisininki.
                    # Hatalı parola (negatif case) değiştirilmez: giriş ajan için de başarısız olur.
                    out["text"] = self.config.agent_password
            else:
                if metin in self.case_dealers:
                    out["text"] = self.config.agent_dealer
                    self.substitutions += 1
                    self.yerine_gecenler[metin] = self.config.agent_dealer
                self._ajan_girisi = out["text"] == self.config.agent_dealer
        return out

    def redact(self, metin: str) -> str:
        return gizle(metin, self.gizliler)

    def __call__(self, name: str, args: dict[str, Any]) -> str:
        self._son_sonuc = None
        try:
            if self.calls >= self.config.max_tool_calls:
                raise ToolBudgetExceeded(
                    f"araç çağrısı bütçesi ({self.config.max_tool_calls}) doldu; sonucu şimdi ver"
                )
            gercek = self._hazirla(name, args)
            if name == GENERATE_LOCATOR:
                self._son_locator_hedefi = locator_hedefi(self._son_snapshot, gercek.get("target"))
            self.calls += 1
            self.last_screenshot = None
            out = self.session.call(name, gercek)
        except Exception as exc:
            self._son_sonuc = AracSonucu(name, False, self.redact(f"{type(exc).__name__}: {exc}"))
            raise
        self._screenshot()
        metin = self.redact(out.text or "(boş sonuç)")
        url = sayfa_adresi(metin)
        if out.is_error:
            satirlar = [s.strip() for s in metin.splitlines() if s.strip()]
            ilk = next(
                (s for s in satirlar if not s.startswith("#")), satirlar[0] if satirlar else ""
            )
            self._son_sonuc = AracSonucu(name, False, ilk[:300], url)
            # Gateway bunu is_error=true kaydeder; model hata metnini güvenilmeyen blokta görür.
            raise McpToolError(wrap_tool_result(name, "Araç hata döndürdü:\n" + metin))
        self._son_sonuc = AracSonucu(name, True, None, url)
        if is_inline_snapshot(metin):
            self._son_snapshot = snapshot_lines(metin) or self._son_snapshot
        return wrap_tool_result(name, metin)

    def pop_locator_hedefi(self) -> LocatorHedefi | None:
        """Son `browser_generate_locator` hedefinin canlı snapshot karşılığı (yoksa None)."""
        hedef, self._son_locator_hedefi = self._son_locator_hedefi, None
        return hedef

    def pop_sonuc(self) -> AracSonucu | None:
        """Son çağrının yapılandırılmış sonucu (çağrı yapılmadıysa None)."""
        sonuc, self._son_sonuc = self._son_sonuc, None
        return sonuc

    def _screenshot(self) -> None:
        """Model döngüsünün dışında: görüntü yalnızca diske/portala gider."""
        if self.screenshot_sink is None:
            return
        try:
            out = self.screenshot_session.call(SCREENSHOT_TOOL, {"type": "png"})
        except Exception as exc:  # görüntü alınamaması doğrulamayı durdurmaz
            log.warning("ekran görüntüsü alınamadı: %s", exc)
            return
        png = next((veri for mime, veri in out.images if mime.endswith("png")), None)
        if png is None and out.images:
            png = out.images[0][1]
        if png is None or len(png) > MAX_IMAGE_BYTES:
            return
        try:
            self.last_screenshot = self.screenshot_sink(self.step_offset + self.calls, png)
        except Exception as exc:  # ro artefakt bağlaması vb.
            log.warning("ekran görüntüsü yazılamadı: %s", exc)

    def pop_screenshot(self) -> str | None:
        ref, self.last_screenshot = self.last_screenshot, None
        return ref


def screenshot_writer(artifacts_root: Path, script_id: Any) -> ScreenshotSink:
    """TP_ARTIFACTS_PATH/codegen/<script_id>/step-<n>.png yazıcısı (atomik)."""
    kok = Path(artifacts_root)

    def yaz(n: int, png: bytes) -> str:
        rel = Path("codegen") / str(script_id) / f"step-{int(n)}.png"
        hedef = kok / rel
        hedef.parent.mkdir(parents=True, exist_ok=True)
        tmp = hedef.with_name(hedef.name + ".tmp")
        tmp.write_bytes(png)
        os.replace(tmp, hedef)
        return rel.as_posix()

    return yaz


def summarize_args(args: Mapping[str, Any]) -> str:
    return json.dumps(mask_args(args), ensure_ascii=False, sort_keys=True)[:300]
