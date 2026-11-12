"""FailureToFix sınıflandırması (TEKNIK-TASARIM §8.6; MIMARI-SOZLESME §5 `/failures`).

Akış (`triage.classify` işi, yalnızca core-worker; AI yalnızca kural eşleşmezse):

1. **Uygunluk.** Kırmızı (`failed`/`error`) koşu. Kod üretiminin yerel kontrolü (`local_check`)
   yalnızca kontrol sınıfı `defect_adayi` ise triage'a girer (locator/derleme/ortam sınıfları kod
   üretiminin kendi akışındadır); kırarak doğrulama koşuları (`break_verify`) girer —
   `BREAK_CAMPAIGN` kırmızısı "hata yakalama" senaryosunun (TEKNIK-TASARIM §2 adım 6, 12–14)
   girdisidir ve `kasitli_kirilma` sinyaliyle işaretlenir; varsayılan olarak taslak istenir
   (testçi kararına bırakılır, Jira'ya yalnızca insan onayıyla yazılır). `TP_TRIAGE_KIRMA_TASLAK=0`
   taslağı kapatır (`oneri_turu='none'`, `jira_yazilmaz`). Statik adımda
   (tsc/eslint/AST) kalan ve test sonucu üretmeyen koşu test hatası değildir (`skipped`).
2. **Kanıt.** test-runner'ın koşu dizinindeki `run.json` (`saglik`, `failures[].failure`:
   tür, mesaj, beklenen/gerçekleşen, locator, adım, konum, kanıt yolları, aria snapshot), gerekirse
   `error-context.md` ve `trace.zip` (güvenli, sınırlı okuma; `evidence`). JSON rapor yoksa (GitHub
   kipi) `test_result.hata_mesaji`'ndan kalıp eşlenir.
3. **Kurallar** (`rules.siniflandir`, sırayla). Kural 3 için sembol tablosu (`/symbols`, koşulan
   commit) + aria snapshot + `/locator-probe` (`scope_test_id` = `within` + ürün kodu; sha
   eşleşmesi `farkli` → öneri yok) kullanılır.
4. **LLM** (`gateway.call(purpose='triage')`) yalnızca hiçbir kural eşleşmezse; kanıt
   `<untrusted>` blokta. Deterministik `environment` kararı LLM'e hiç gitmez (XI). REPLAY'de
   eşleşen golden yoksa sınıf `unknown` kalır (uydurulmaz; `ai_call` `replay_miss` yazılır).
5. **Kayıt.** `failure` + `failure_ek` (idempotens anahtarı `<run>:<test>`), `triage_kosu`,
   SSE `failure.classified`, denetim `triage.classified`. Sayısal güven yok: eşleşen sinyaller.
6. **Öneriler.** `product_defect` (kasıtlı kırılma hariç) → bugs şeridinin
   `create_draft_from_failure(session, failure_id)` (insan onayı orada; yoksa sessizce
   atlanır). `test_maintenance/locator` → öneri `failure_ek.oneri`'de saklanır;
   onarımı `POST /failures/{id}/fix` (repair şeridi) başlatır.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import Engine, and_, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.events import publish_tx
from tp_core.features.codegen import platform as platformlar
from tp_core.features.triage import evidence as ev
from tp_core.features.triage import java as jv
from tp_core.features.triage import java_web as jw
from tp_core.features.triage import services
from tp_core.features.triage.rules import (
    Girdi,
    Karar,
    LocatorAnalizi,
    ag_sinyali_var,
    hata_imzasi,
    siniflandir,
)
from tp_core.features.triage.rules import sinyal as _sinyal
from tp_core.models import BugDraft, Failure, Requirement, Run, Script, TestCase, TestResult
from tp_core.models.ci_feature import TestResultEk
from tp_core.models.codegen_feature import ScriptCodegen, ScriptKontrol
from tp_core.models.triage_feature import FailureEk, TriageKosu
from tp_core.workflow import jobs as jobq

log = logging.getLogger(__name__)

JOB_CLASSIFY = "triage.classify"
JOB_SWEEP = "triage.sweep"
NS = uuid.UUID("0b7f6d1e-6a43-5c2e-9d0e-747269616765")
KIRMIZI = ("failed", "error")
# Kasıtlı kırılma kırmızısı: hata yakalama kanıtıdır, Jira'ya yazılacak bir hata değildir.
KIRMA_TASLAK_YOK = (
    "Kasıtlı kırılma (BREAK_CAMPAIGN): kırarak doğrulamanın beklenen sonucu — test hatayı "
    "yakaladı. Bug taslağı açılmaz, Jira'ya yazılmaz."
)
KIRMIZI_TEST = ("failed", "timedout", "flaky")
# TS (`deps → tsc → eslint → ast_guard`) + Java (009: `deps → guard → compile`). Adım bir
# koşuda yoksa `atlandi` olur ve sayılmaz. `app` (uygulama ≠ commit) statik değil, ortamdır.
STATIK_ADIMLAR = ("deps", "tsc", "eslint", "ast_guard", "guard", "compile")
MAX_TEST = 50
SUPURME_PENCERESI = timedelta(days=2)

# Sayfa object dosyasının dizini → uygulama yolu (demo-app `pages/support.ts` `paths`).
SAYFA_YOLU = {
    "catalog": "/katalog",
    "cart": "/sepet",
    "order": "/siparisler",
    "login": "/giris",
}
KANIT_ETIKETI = {
    "trace": "Playwright trace",
    "error_context": "Hata anı sayfa snapshot'ı (error-context)",
    "screenshot": "Ekran görüntüsü",
    "video": "Video",
    "page_source": "Hata anı sayfa kaynağı (Appium)",
    "dom": "Hata anı DOM'u (sayfa.html)",
}


class TriageBekle(RuntimeError):
    """Koşunun bağlı kaydı (ör. kod üretimi kontrol satırı) henüz yazılmadı; iş yeniden denenir."""


# ============================================================================= kuyruk


def enqueue_classify(conn: Connection, run_id: uuid.UUID) -> uuid.UUID:
    """`triage.classify` işini (idempotent, koşu başına tek) çağıranın işleminde kuyruğa ekler."""
    return jobq.enqueue(
        conn, JOB_CLASSIFY, {"run_id": str(run_id)}, idempotency_key=f"{JOB_CLASSIFY}:{run_id}"
    )


def on_run_finished(session: Session, run: Run) -> uuid.UUID | None:
    """Koşu bittiğinde çağrılacak tek satırlık kanca (ci / codegen şeritleri).

    Kırmızı koşu için `triage.classify` kuyruğa girer; yeşil koşu için hiçbir şey yapılmaz.
    Çağıranın işleminde koşar: koşu commit edilmezse iş de eklenmez.
    """
    if run.sonuc not in KIRMIZI:
        return None
    return enqueue_classify(session.connection(), run.id)


# ============================================================================= uygunluk


@dataclass
class Uygunluk:
    uygun: bool
    neden: str | None = None
    kaynak: str = "ci"
    kirma: bool = False
    kontrol: ScriptKontrol | None = None


def _kontrol_satiri(session: Session, run_id: uuid.UUID) -> ScriptKontrol | None:
    return session.scalars(
        select(ScriptKontrol)
        .where(ScriptKontrol.run_id == str(run_id))
        .order_by(ScriptKontrol.zaman.desc())
    ).first()


def uygunluk(session: Session, run: Run, *, son_deneme: bool = False) -> Uygunluk:
    if run.sonuc not in KIRMIZI:
        return Uygunluk(False, f"koşu kırmızı değil ({run.sonuc})")
    ortam = run.ortam or {}
    kirma = bool(ortam.get("break_campaign"))
    if run.tetik == "local_check" and ortam.get("onarim"):
        # Onarım şeridinin yerel kontrolü (repair.fix adım 7): sonucu onarım kaydına yazılır;
        # kırmızısı onarımı durdurur, CI hatası olarak sınıflandırılmaz.
        return Uygunluk(False, "locator onarımının yerel kontrolü (triage yapılmaz)", "onarim")
    if run.tetik == "local_check":
        kontrol = _kontrol_satiri(session, run.id)
        if kontrol is None:
            if son_deneme:
                return Uygunluk(False, "kod üretimi kontrol kaydı bulunamadı", "codegen")
            raise TriageBekle("kod üretimi kontrol kaydı henüz yazılmadı")
        if kontrol.sinif != "defect_adayi":
            return Uygunluk(
                False,
                f"kod üretimi yerel kontrolü (sınıf {kontrol.sinif}); triage yalnızca defect "
                "adayında yapılır — diğer sınıflar kod üretimi akışında insana düşer",
                "codegen",
                kontrol=kontrol,
            )
        return Uygunluk(True, None, "codegen", kirma, kontrol)
    if run.tetik == "break_verify":
        if kirma and not services.kirma_triage():
            return Uygunluk(
                False, "kasıtlı kırılma koşusu (TP_TRIAGE_KIRMA=0)", "kirma", kirma, None
            )
        return Uygunluk(True, None, "kirma" if kirma else "codegen", kirma, None)
    return Uygunluk(True, None, "ci", kirma, None)


# ============================================================================= kanıt → girdi


@dataclass
class TestKaniti:
    girdi: Girdi
    anahtar: str
    test_result_id: uuid.UUID | None
    kanit_linkleri: list[dict[str, Any]] = field(default_factory=list)
    trace_rel: str | None = None
    test_status: str | None = None
    son_yesil_run_id: str | None = None
    uyarilar: list[str] = field(default_factory=list)
    # LLM yedeğinin kanonik girdisi (`gateway.failure_block`): ham `failure`, tekrar/deneme
    # durum sayıları, tutarlılık, story ve case referansı.
    ham: dict[str, Any] = field(default_factory=dict)
    story_key: str | None = None
    case_ref: str | None = None


def _norm_dosya(d: Any) -> str:
    return PurePosixPath(str(d or "")).as_posix().lstrip("./")


def _ayni_dosya(a: Any, b: Any) -> bool:
    x, y = _norm_dosya(a), _norm_dosya(b)
    if not x or not y:
        return True
    return x == y or x.endswith("/" + y) or y.endswith("/" + x)


def _durum(status: Any) -> str:
    s = str(status or "")
    return {"expected": "passed", "unexpected": "failed"}.get(s, s)


def _konum(loc: Any) -> str | None:
    m = ev.mapping(loc)
    if not m.get("file"):
        return None
    satir = m.get("line")
    return f"{m.get('file')}:{satir}" if satir else str(m.get("file"))


def _satir(loc: Any) -> int | None:
    v = ev.mapping(loc).get("line")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _anahtar(run_id: uuid.UUID, dosya: Any, test_adi: str) -> str:
    h = hashlib.sha256(f"{_norm_dosya(dosya)}\x00{test_adi}".encode()).hexdigest()[:24]
    return f"{run_id}:{h}"


def failure_id_for(anahtar: str) -> uuid.UUID:
    return uuid.uuid5(NS, anahtar)


def _uygulama_farkli(run: Run) -> str | None:
    a = run.artefaktlar or {}
    if "app" in [str(x) for x in a.get("basarisiz_adimlar") or []]:
        adim = ev.mapping(ev.mapping(a.get("adimlar")).get("app"))
        return ev.temiz(adim.get("reason") or adim.get("error") or "app adımı başarısız", 300)
    return None


def _statik_kirmizi(run: Run) -> list[str]:
    a = run.artefaktlar or {}
    adimlar = ev.mapping(a.get("adimlar"))
    return [
        ad
        for ad in STATIK_ADIMLAR
        if ev.mapping(adimlar.get(ad)).get("ok") is False
        and not ev.mapping(adimlar.get(ad)).get("atlandi")
    ]


def _kanit_linkleri(
    failure: Mapping[str, Any], kosu_rel: str | None, ekler: Sequence[Any]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    gorulen: set[str] = set()
    kanitlar = ev.mapping(failure.get("evidence"))
    for ad, etiket in KANIT_ETIKETI.items():
        yol = ev.kanit_yolu(kosu_rel or "", ev.mapping(kanitlar.get(ad)).get("rel"))
        if yol and yol not in gorulen and kosu_rel:
            gorulen.add(yol)
            out.append({"etiket": etiket, "yol": yol, "tur": ad})
    for e in ekler or []:
        if not isinstance(e, Mapping):
            continue
        yol = e.get("yol")
        if (
            isinstance(yol, str)
            and yol not in gorulen
            and not PurePosixPath(yol).is_absolute()
            and ".." not in PurePosixPath(yol).parts
        ):
            ad = str(e.get("ad") or "ek")
            if ad.startswith("axe-"):
                continue
            gorulen.add(yol)
            out.append({"etiket": KANIT_ETIKETI.get(ad, ad)[:80], "yol": yol, "tur": ad[:40]})
    return out[:12]


def _deneme_durumlari(test: Mapping[str, Any], ek: TestResultEk | None) -> list[str]:
    out: list[str] = []
    for a in test.get("attempt_results") or test.get("attempts_detail") or []:
        if isinstance(a, Mapping):
            out.append(_durum(a.get("status")))
        elif isinstance(a, str):
            out.append(_durum(a))
    if not out and ek is not None:
        out = [_durum(d.get("sonuc")) for d in ek.denemeler or [] if isinstance(d, Mapping)]
    return out[:10]


def _son_yesil(session: Session, run: Run, test_adi: str, dosya: str | None) -> str | None:
    q = (
        select(TestResult.run_id)
        .join(Run, Run.id == TestResult.run_id)
        .where(
            TestResult.test_adi == test_adi,
            TestResult.sonuc == "passed",
            Run.id != run.id,
            Run.olusturma <= run.olusturma,
        )
        .order_by(Run.olusturma.desc())
        .limit(1)
    )
    if dosya:
        q = q.where(TestResult.dosya == dosya)
    rid = session.scalar(q)
    return str(rid) if rid else None


def _rapor_testleri(rapor: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not rapor:
        return []
    return [t for t in rapor.get("tests") or [] if isinstance(t, Mapping)]


def _rapor_hatalari(rapor: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not rapor:
        return []
    return [f for f in rapor.get("failures") or [] if isinstance(f, Mapping)]


def _girdi_olustur(
    *,
    run: Run,
    test_adi: str,
    dosya: str | None,
    sonuc: str,
    mesaj: str | None,
    rapor: Mapping[str, Any] | None,
    kosu: Path | None,
    kosu_rel: str | None,
    saglik: Mapping[str, Any] | None,
    uygunluk_: Uygunluk,
    ek: TestResultEk | None,
    platform: str | None = None,
    dil: str | None = None,
) -> tuple[Girdi, list[dict[str, Any]], str | None, str | None, list[str], dict[str, Any]]:
    """Bir testin girdisi + kanıt bağlantıları + trace yolu + test durumu + uyarılar + ham."""
    uyarilar: list[str] = []
    eslesen = [
        t
        for t in _rapor_testleri(rapor)
        if str(t.get("title") or "") == test_adi and _ayni_dosya(t.get("file"), dosya)
    ]
    hatalar = [
        f
        for f in _rapor_hatalari(rapor)
        if str(f.get("title") or "") == test_adi and _ayni_dosya(f.get("file"), dosya)
    ]
    kirmizi = [f for f in hatalar if f.get("status") == "unexpected"] or hatalar
    ana = kirmizi[0] if kirmizi else (eslesen[0] if eslesen else {})
    failure = ev.mapping(ana.get("failure"))
    if rapor is not None and not failure:
        uyarilar.append("JSON raporunda bu testin hata girdisi yok; hata metninden sınıflandırıldı")
    tekrarlar = eslesen if len(eslesen) > 1 else []
    tekrar_durumlari = [_durum(t.get("status")) for t in tekrarlar]
    tekrar_degerleri = [
        (
            _satir(ev.mapping(f.get("failure")).get("location")),
            ev.mapping(f.get("failure")).get("expected"),
            ev.mapping(f.get("failure")).get("received"),
        )
        for f in kirmizi
        if f.get("failure")
    ]
    aria = ev.temiz_or_none(failure.get("aria_snapshot"), ev.MAX_ARIA)
    kapsam = ev.temiz_or_none(failure.get("aria_snapshot_scope"), 40)
    kanitlar = ev.mapping(failure.get("evidence"))
    if aria is None and kosu is not None and kosu_rel:
        ctx_rel = ev.kanit_yolu(kosu_rel, ev.mapping(kanitlar.get("error_context")).get("rel"))
        aria, kapsam = ev.aria_oku(kosu, ctx_rel)
    if aria is None and ek is not None:
        # GitHub kipi: yerel koşu dizini yok; içe aktarımda artefakttaki error-context.md'den
        # okunan hata anı snapshot'ı (`test_result_ek.hata_baglami`, ci `github_ingest`).
        hb = ev.mapping(ek.hata_baglami)
        aria = ev.temiz_or_none(hb.get("aria_snapshot"), ev.MAX_ARIA)
        kapsam = ev.temiz_or_none(hb.get("aria_snapshot_scope"), 40) if aria else None
    trace_rel = None
    if kosu_rel:
        trace_rel = ev.kanit_yolu(
            kosu_rel, failure.get("trace_rel") or ev.mapping(kanitlar.get("trace")).get("rel")
        )
    adim = ev.mapping(failure.get("step")).get("title")
    loc = failure.get("test_location") or failure.get("location")
    g = Girdi(
        test_adi=test_adi,
        dosya=dosya,
        satir=_satir(loc),
        sonuc=sonuc,
        hata_turu=ev.temiz_or_none(failure.get("type"), 40),
        mesaj=ev.temiz_or_none(failure.get("message") or mesaj),
        beklenen=ev.temiz_or_none(failure.get("expected"), 300),
        gerceklesen=ev.temiz_or_none(failure.get("received"), 300),
        matcher=ev.temiz_or_none(failure.get("matcher"), 80),
        locator=ev.temiz_or_none(failure.get("locator"), 500),
        adim=ev.temiz_or_none(adim, 200),
        konum=_konum(failure.get("location")) or _konum(loc),
        page_location=ev.temiz_or_none(ev.mapping(failure.get("page_location")).get("file"), 200),
        aria=aria,
        aria_kapsami=kapsam,
        saglik=saglik,
        run_sonuc=run.sonuc,
        uygulama_farkli=_uygulama_farkli(run),
        tekrar_durumlari=tekrar_durumlari,
        tekrar_degerleri=tekrar_degerleri,
        deneme_durumlari=_deneme_durumlari(ana, ek),
        kirma=uygunluk_.kirma,
        platform=platform,
        dil=dil,
    )
    java_linkleri: list[dict[str, Any]] = []
    if g.web_java:
        # 011: web + Java (Playwright for Java) kanıtı web yöntemiyle okunur:
        # target/kanit/<Sınıf.metot>/{ekran.png, trace.zip, sayfa.html}.
        wk = jw.kanit_oku(kosu, kosu_rel, failure, dosya, test_adi)
        g.sayfa_html, g.sayfa_html_rel = wk.sayfa_html, wk.dom_rel
        if wk.uyari:
            uyarilar.append(wk.uyari)
        if trace_rel is None and wk.trace_rel:
            trace_rel = wk.trace_rel
        for tur, yol in (("screenshot", wk.ekran_rel), ("trace", wk.trace_rel),
                         ("dom", wk.dom_rel)):  # fmt: skip
            if yol:
                java_linkleri.append({"etiket": KANIT_ETIKETI[tur], "yol": yol, "tur": tur})
        if g.gerceklesen is None and g.beklenen is None:
            exp, rec = jw.beklenen_gorulen(g.mesaj)
            if exp is None and rec is None:
                from tp_core.features.codegen.classify import java_beklenen_gorulen

                exp, rec = java_beklenen_gorulen(g.mesaj)
            g.beklenen = None if exp is None else ev.temiz(exp, 300)
            g.gerceklesen = None if rec is None else ev.temiz(rec, 300)
    elif g.java:
        # 009: uygulama testi kanıtı (target/kanit/<Sınıf.metot>/{ekran.png,sayfa-kaynagi.xml}).
        jk = jv.sayfa_kaynagi_oku(kosu, kosu_rel, failure, dosya, test_adi)
        g.sayfa_kaynagi, g.sayfa_kaynagi_rel = jk.sayfa_kaynagi, jk.kaynak_rel
        if jk.uyari:
            uyarilar.append(jk.uyari)
        if jk.ekran_rel:
            java_linkleri.append(
                {"etiket": KANIT_ETIKETI["screenshot"], "yol": jk.ekran_rel, "tur": "screenshot"}
            )
        if jk.kaynak_rel:
            java_linkleri.append(
                {"etiket": KANIT_ETIKETI["page_source"], "yol": jk.kaynak_rel, "tur": "page_source"}
            )
        if g.gerceklesen is None and g.beklenen is None:
            from tp_core.features.codegen.classify import java_beklenen_gorulen

            exp, rec = java_beklenen_gorulen(g.mesaj)
            g.beklenen = None if exp is None else ev.temiz(exp, 300)
            g.gerceklesen = None if rec is None else ev.temiz(rec, 300)
    if g.gerceklesen is None and g.mesaj and not failure and not g.java:
        # GitHub kipi / JSON'suz: Playwright mesajındaki Expected/Received satırları.
        from tp_core.features.codegen.classify import _EXPECTED, _RECEIVED

        me, mr = _EXPECTED.search(g.mesaj), _RECEIVED.search(g.mesaj)
        g.beklenen = me.group("v").strip() if me else None
        g.gerceklesen = mr.group("v").strip() if mr else None
    linkler = _kanit_linkleri(failure, kosu_rel, ek.ekler if ek else [])
    gorulen_yollar = {lk["yol"] for lk in linkler}
    linkler = (linkler + [lk for lk in java_linkleri if lk["yol"] not in gorulen_yollar])[:12]
    ham = _ham_girdi(failure, g, eslesen, ana)
    return g, linkler, trace_rel, str(ana.get("status") or "") or None, uyarilar, ham


def _ham_girdi(
    failure: Mapping[str, Any],
    g: Girdi,
    tekrarlar: Sequence[Mapping[str, Any]],
    ana: Mapping[str, Any],
) -> dict[str, Any]:
    """`gateway.failure_block` girdisi: test-runner `failure` nesnesi (yoksa mesajdan kurulur),
    durum sayıları (tekrar varsa tekrarların, yoksa denemelerin ham Playwright durumları) ve
    tutarlılık (toolchain `failure_groups[].consistent` ile aynı tanım)."""
    durumlar: dict[str, int] = {}
    if len(tekrarlar) > 1:
        turler = set()
        for t in tekrarlar:
            st = str(t.get("status") or "")
            durumlar[st] = durumlar.get(st, 0) + 1
            f = ev.mapping(t.get("failure"))
            if f:
                turler.add(f.get("type"))
        tutarli: bool | None = set(durumlar) == {"unexpected"} and len(turler) == 1
    else:
        for a in ana.get("attempt_results") or []:
            st = str(ev.mapping(a).get("status") or "") if isinstance(a, Mapping) else str(a)
            if st:
                durumlar[st] = durumlar.get(st, 0) + 1
        tutarli = (len(durumlar) == 1) if durumlar else None
    if failure:
        ham_f = dict(failure)
    else:
        ilk = (g.mesaj or "").splitlines()[0] if g.mesaj else None
        ham_f = {
            "type": g.tur(),
            "first_line": ilk,
            "matcher": g.matcher,
            "locator": g.locator,
            "expected": g.beklenen,
            "received": g.gerceklesen,
            "aria_snapshot": g.aria,
            "aria_snapshot_scope": g.aria_kapsami,
        }
    if not ham_f.get("first_line") and g.mesaj:
        ham_f["first_line"] = g.mesaj.splitlines()[0]
    if not ham_f.get("aria_snapshot") and g.aria:
        ham_f["aria_snapshot"] = g.aria
        ham_f["aria_snapshot_scope"] = g.aria_kapsami
    return {"failure": ham_f, "statuses": durumlar, "consistent": tutarli}


def _story_ve_case(
    session: Session, run: Run, test_case_id: uuid.UUID | None, dosya: str | None
) -> tuple[str | None, str | None]:
    """Hatanın story'si ve (üretilen testse) case referansı (`TPD-1-C3`)."""
    # Üretilen test: web `tests/generated/`, Java (009) `…/bayi/uretilen/`.
    uretilen = any(k in (dosya or "") for k in ("tests/generated/", "/uretilen/"))
    if run.script_id is not None:
        cg = session.get(ScriptCodegen, run.script_id)
        if cg is not None and cg.story_key:
            return cg.story_key, f"{cg.story_key}-C{cg.sira_no}"
    if test_case_id is not None:
        tc = session.get(TestCase, test_case_id)
        req = session.get(Requirement, tc.requirement_id) if tc is not None else None
        if req is not None and req.jira_key:
            ref = f"{req.jira_key}-C{tc.sira_no}" if uretilen and tc is not None else None
            return req.jira_key, ref
    return None, None


def kosu_platformu(
    session: Session, run: Run, rapor: Mapping[str, Any] | None = None
) -> str | None:
    """Koşunun platformu (009 §2.1): `run.ortam.platform` (test-runner/CI, Ş8) → koşu raporu
    (`run.json` `platform`) → koşunun script'i (`script.platform`). Bilinmiyorsa None (test
    bazında dosya adı / hata metninden çıkarılır: `triage.java.java_mi`)."""
    for aday in ((run.ortam or {}).get("platform"), (rapor or {}).get("platform")):
        if isinstance(aday, str) and aday in ("web", *jv.UYGULAMA_PLATFORMLARI):
            return aday
    if run.script_id is not None:
        sc = session.get(Script, run.script_id)
        if sc is not None and getattr(sc, "platform", None):
            return str(sc.platform)
    return None


def kosu_dili(session: Session, run: Run, rapor: Mapping[str, Any] | None = None) -> str | None:
    """Koşunun üretim dili (011 §2.8): `run.ortam.dil` → `run.ortam.lang` (CI / test-runner) →
    koşu raporu (`run.json` `lang`) → koşunun script'i (`script.dil`). Bilinmiyorsa None (test
    bazında dosya adından çıkarılır: `triage.java.java_mi`)."""
    o = run.ortam or {}
    for aday in (o.get("dil"), o.get("lang"), (rapor or {}).get("lang")):
        if aday in platformlar.TAM_HAT_DILLERI:
            return str(aday)
    if run.script_id is not None:
        sc = session.get(Script, run.script_id)
        if sc is not None and sc.dil in platformlar.TAM_HAT_DILLERI:
            return str(sc.dil)
    return None


def kanitlari_topla(session: Session, run: Run, u: Uygunluk) -> tuple[list[TestKaniti], str | None]:
    """Koşunun başarısız testleri → girdi listesi. Boş liste + neden: sınıflandırılacak hata yok."""
    a = run.artefaktlar or {}
    kosu_rel = a.get("dizin") if isinstance(a.get("dizin"), str) else None
    kosu = ev.kosu_dizini(services.artifacts_root(), kosu_rel)
    rapor: dict[str, Any] | None = None
    genel_uyari: list[str] = []
    if kosu is not None:
        try:
            rapor = ev.kosu_raporu(kosu)
        except ev.KanitHatasi as exc:
            genel_uyari.append(f"run.json okunamadı: {exc}")
        if rapor is None and not genel_uyari:
            genel_uyari.append("run.json yok (koşu dizini temizlenmiş olabilir)")
    saglik = ev.mapping((rapor or {}).get("saglik")) or ev.mapping((run.ortam or {}).get("saglik"))
    saglik_ = dict(saglik) if saglik else None
    platform = kosu_platformu(session, run, rapor)
    dil = kosu_dili(session, run, rapor)

    rows = session.execute(
        select(TestResult, TestResultEk)
        .outerjoin(TestResultEk, TestResultEk.test_result_id == TestResult.id)
        .where(TestResult.run_id == run.id, TestResult.sonuc.in_(KIRMIZI_TEST))
        .order_by(TestResult.dosya, TestResult.test_adi)
        .limit(MAX_TEST)
    ).all()
    out: list[TestKaniti] = []
    for tr, ek in rows:
        g, linkler, trace_rel, durum, uyarilar, ham = _girdi_olustur(
            run=run,
            test_adi=tr.test_adi,
            dosya=tr.dosya,
            sonuc=tr.sonuc,
            mesaj=tr.hata_mesaji,
            rapor=rapor,
            kosu=kosu,
            kosu_rel=kosu_rel,
            saglik=saglik_,
            uygunluk_=u,
            ek=ek,
            platform=platform,
            dil=dil,
        )
        out.append(
            TestKaniti(
                g,
                _anahtar(run.id, tr.dosya, tr.test_adi),
                tr.id,
                linkler,
                trace_rel,
                durum,
                _son_yesil(session, run, tr.test_adi, tr.dosya),
                genel_uyari + uyarilar,
                ham,
                *_story_ve_case(session, run, tr.test_case_id, tr.dosya),
            )
        )
    if out:
        return out, None
    # test_result satırı yok: JSON raporunun hata girdileri (ayrıştırma başarısız olduysa).
    gorulen: set[tuple[str, str]] = set()
    for f in _rapor_hatalari(rapor)[:MAX_TEST]:
        ad, dosya = str(f.get("title") or ""), _norm_dosya(f.get("file")) or None
        if not ad or (dosya or "", ad) in gorulen:
            continue
        gorulen.add((dosya or "", ad))
        g, linkler, trace_rel, durum, uyarilar, ham = _girdi_olustur(
            run=run,
            test_adi=ad,
            dosya=dosya,
            sonuc="flaky" if f.get("status") == "flaky" else "failed",
            mesaj=None,
            rapor=rapor,
            kosu=kosu,
            kosu_rel=kosu_rel,
            saglik=saglik_,
            uygunluk_=u,
            ek=None,
            platform=platform,
            dil=dil,
        )
        out.append(
            TestKaniti(
                g,
                _anahtar(run.id, dosya, ad),
                None,
                linkler,
                trace_rel,
                durum,
                None,
                [*genel_uyari, *uyarilar, "test_result satırı yok; JSON raporundan okundu"],
                ham,
                *_story_ve_case(session, run, None, dosya),
            )
        )
    if out:
        return out, None
    statik = _statik_kirmizi(run)
    saglik_kotu = isinstance(saglik_, Mapping) and saglik_.get("ok") is False
    if statik and not saglik_kotu and run.sonuc != "error":
        return [], f"statik adım başarısız ({', '.join(statik)}); test hatası yok"
    if run.sonuc == "error" or saglik_kotu or _uygulama_farkli(run):
        hata = a.get("runner_hata") or a.get("hata") or (rapor or {}).get("error")
        g = Girdi(
            test_adi="(koşu: test sonucu yok)",
            sonuc="kosu",
            mesaj=ev.temiz_or_none(hata),
            saglik=saglik_,
            run_sonuc=run.sonuc,
            uygulama_farkli=_uygulama_farkli(run),
            kirma=u.kirma,
            testsiz=True,
            runner_hata=ev.temiz_or_none(hata, 500),
        )
        linkler = []
        if kosu_rel and a.get("log"):
            linkler.append({"etiket": "Koşu günlüğü", "yol": str(a["log"]), "tur": "log"})
        return [TestKaniti(g, f"{run.id}:kosu", None, linkler, None, None, None, genel_uyari)], None
    return [], "kırmızı test sonucu bulunamadı"


# ============================================================================= kural 3


def _sayfa_yolu(dosya: str | None) -> str | None:
    if not dosya:
        return None
    parcalar = PurePosixPath(dosya).parts
    for i, p in enumerate(parcalar):
        if p == "pages" and i + 1 < len(parcalar):
            return SAYFA_YOLU.get(parcalar[i + 1])
    return None


@dataclass
class LocatorBaglami:
    sha: str | None
    trace_rel: str | None
    kosu: Path | None
    son_yesil_run_id: str | None
    # Koşu içinde paylaşılan önbellek: sembol tablosu ve (rol, ad, yol, kapsam) yoklamaları.
    # `make break` sonrası aynı kırık locator'ı kullanan her test için yoklama bir kez yapılır.
    ortak: dict[str, Any] = field(default_factory=dict)


def _sembol_adaylari(
    semboller: Mapping[str, Any], hedef: str
) -> list[tuple[str, Mapping[str, Any], list[str]]]:
    """testId → (anahtar, locator, kullanan page object dosyaları); önek locator'lar da."""
    bulunan: dict[tuple[str, str], tuple[str, Mapping[str, Any], list[str]]] = {}
    for po in semboller.get("page_objects") or []:
        if not isinstance(po, Mapping):
            continue
        for anahtar, loc in ev.mapping(po.get("locators")).items():
            if not isinstance(loc, Mapping):
                continue
            tid = str(loc.get("testId") or "")
            onek = bool(loc.get("prefix")) or tid.endswith("-")
            if tid == hedef or (onek and tid and hedef.startswith(tid) and len(hedef) > len(tid)):
                k = (str(loc.get("file") or ""), str(anahtar))
                if k not in bulunan:
                    bulunan[k] = (str(anahtar), loc, [])
                bulunan[k][2].append(str(po.get("file") or ""))
    return list(bulunan.values())


def locator_analizi(g: Girdi, b: LocatorBaglami) -> LocatorAnalizi:
    """Kural 3'ün dış ölçümü. Öneri yalnızca tüm koşullar sağlanırsa üretilir (§8.6, §8.7)."""
    if g.web_java:
        return web_java_locator_analizi(g, b)
    if g.java:
        return java_locator_analizi(g, b)
    sinyaller: list[dict[str, Any]] = []
    tids = ev.locator_test_idleri(g.locator) or ev.locator_test_idleri(g.mesaj)
    if not tids:
        return LocatorAnalizi(None, sinyaller, "Locator metninde testId yok; aday üretilemez")
    hedef = tids[-1]
    kapsam_metni = tids[-2] if len(tids) > 1 else None
    if not b.sha:
        return LocatorAnalizi(None, sinyaller, "Koşunun commit'i bilinmiyor; sembol tablosu yok")
    tc = services.toolchain()
    if "semboller" not in b.ortak:
        try:
            b.ortak["semboller"] = tc.symbols(b.sha)
        except services.ToolchainHatasi as exc:
            b.ortak["semboller"] = None
            b.ortak["sembol_hatasi"] = str(exc)
    semboller = b.ortak["semboller"]
    if semboller is None:
        return LocatorAnalizi(
            None, sinyaller, f"Sembol tablosu alınamadı: {b.ortak.get('sembol_hatasi')}"
        )
    adaylar = _sembol_adaylari(semboller, hedef)
    if not adaylar:
        return LocatorAnalizi(
            None, sinyaller, f"testId '{hedef}' koşulan commit'in locators.ts'inde yok"
        )
    if len(adaylar) > 1:
        return LocatorAnalizi(
            None,
            sinyaller,
            f"testId '{hedef}' birden çok locator anahtarına uyuyor: "
            + ", ".join(a[0] for a in adaylar[:5]),
        )
    anahtar, loc, po_dosyalari = adaylar[0]
    role, name = str(loc.get("role") or ""), str(loc.get("name") or "")
    within = loc.get("within") if isinstance(loc.get("within"), str) else None
    tid = str(loc.get("testId") or "")
    sinyaller.append(
        _sinyal(
            "niyet_sembol_tablosu",
            f"Locator '{anahtar}' niyeti: rol {role or '-'}, ad \"{name}\"",
            f"toolchain /symbols @ {b.sha[:12]}",
            loc.get("intent"),
        )
    )
    if tid != hedef:
        return LocatorAnalizi(None, sinyaller, "Önek locator (ürün koduna göre değişen testId)")
    if not role or not name:
        return LocatorAnalizi(
            None, sinyaller, "Locator niyetinde rol + ad yok; kimlik karşılaştırması yapılamaz"
        )
    aria_satirlari = ev.aria_eslesmeleri(g.aria, role, name)
    if not g.aria:
        return LocatorAnalizi(None, sinyaller, "Hata anı aria snapshot'ı yok")
    if not aria_satirlari:
        return LocatorAnalizi(
            None, sinyaller, f'Rol + ad ({role} "{name}") hata anındaki sayfada yok'
        )
    sinyaller.append(
        _sinyal(
            "aria_rol_ad_var",
            f'Niyetteki eleman ({role} "{name}") hata anında aynı sayfada var '
            f"({len(aria_satirlari)} satır)",
            "error-context aria snapshot",
            aria_satirlari[0],
        )
    )
    scope: str | None = None
    if within:
        if kapsam_metni and kapsam_metni.startswith(within):
            scope = kapsam_metni
        else:
            kod = ev.urun_kodu(g.adim, g.locator, g.mesaj, g.test_adi)
            scope = f"{within}{kod}" if kod else None
        if scope is None:
            return LocatorAnalizi(
                None,
                sinyaller,
                f"Kapsamlı locator (within '{within}') için ürün kodu bulunamadı; çoklu eşleşme",
            )
    trace = ev.trace_oku(b.kosu, b.trace_rel) if b.kosu is not None else ev.TraceOzeti()
    url_path = (
        trace.son_url_yolu
        or _sayfa_yolu(g.page_location)
        or _sayfa_yolu(str(loc.get("file") or ""))
        or next((y for y in map(_sayfa_yolu, po_dosyalari) if y), None)
    )
    if not url_path:
        return LocatorAnalizi(None, sinyaller, "Hatanın sayfa yolu belirlenemedi")
    anahtar_p = f"probe:{role}\x00{name}\x00{url_path}\x00{scope}"
    if anahtar_p not in b.ortak:
        try:
            b.ortak[anahtar_p] = tc.locator_probe(b.sha, role, name, url_path, scope)
        except services.ToolchainHatasi as exc:
            b.ortak[anahtar_p] = exc
    probe = b.ortak[anahtar_p]
    if isinstance(probe, Exception):
        return LocatorAnalizi(None, sinyaller, f"Locator yoklaması yapılamadı: {probe}")
    p = {
        "rol": role,
        "ad": name,
        "url_path": url_path,
        "scope_test_id": scope,
        "matches": probe.get("matches"),
        "scope_matches": probe.get("scope_matches"),
        "test_id": probe.get("test_id"),
        "olculen": probe.get("olculen"),
        "uygulama_sha": probe.get("uygulama_sha"),
        "sha_eslesmesi": probe.get("sha_eslesmesi"),
        "uyari": probe.get("uyari"),
        "oneri_uretilebilir": probe.get("oneri_uretilebilir"),
    }
    sinyaller.append(
        _sinyal(
            "locator_probe",
            f'Çalışan uygulamada {role} "{name}" {p["matches"]} eleman'
            + (f" ({scope} içinde)" if scope else "")
            + (f", data-testid '{p['test_id']}'" if p["test_id"] else ""),
            f"toolchain /locator-probe ({p['olculen'] or 'calisan_uygulama'}, "
            f"sha {p['sha_eslesmesi'] or '?'})",
            p["uyari"],
        )
    )
    trace_dom = _trace_dom_degerlendir(trace, hedef, p["test_id"])
    if trace_dom["destekliyor"]:
        sinyaller.append(
            _sinyal("trace_dom", trace_dom["aciklama"], "trace.zip", trace_dom["kanit"])
        )
    if p["sha_eslesmesi"] == "farkli":
        return LocatorAnalizi(
            None,
            sinyaller,
            "Çalışan uygulama koşulan commit'ten farklı (sha_eslesmesi=farkli); öneri üretilmez",
        )
    if p["matches"] != 1 or not p["test_id"]:
        return LocatorAnalizi(
            None, sinyaller, f"Rol + ad {p['matches']} eleman buldu; tek eşleşme gerekli"
        )
    if p["test_id"] == hedef:
        return LocatorAnalizi(
            None, sinyaller, "Elemanın data-testid'si değişmemiş; locator kırılması değil"
        )
    if p["oneri_uretilebilir"] is False:
        return LocatorAnalizi(None, sinyaller, "Locator yoklaması öneri üretilemez dedi")
    sinyaller.append(
        _sinyal(
            "test_id_farkli",
            f"data-testid değişmiş: '{hedef}' → '{p['test_id']}'",
            "toolchain /locator-probe",
            None,
        )
    )
    oneri = {
        "locator_key": anahtar,
        "old_testid": hedef,
        "new_testid": p["test_id"],
        "dosya": str(loc.get("file") or ""),
        "satir": loc.get("line") if isinstance(loc.get("line"), int) else None,
        "page_objects": sorted({d for d in po_dosyalari if d}),
        "rol": role,
        "ad": name,
        "intent": loc.get("intent"),
        "within": within,
        "scope_test_id": scope,
        "url_path": url_path,
        "sha": b.sha,
        "probe": p,
        "aria_satirlari": aria_satirlari[:5],
        "son_yesil_run_id": b.son_yesil_run_id,
        # Değerlendirilen ama kararı desteklemeyen trace kanıtı eşleşen sinyal değildir; burada
        # (`destekliyor=false`) not olarak saklanır ki portal karşı/okunamayan kanıtı gösterebilsin.
        "trace_dom": trace_dom,
    }
    return LocatorAnalizi(oneri, sinyaller, None)


def java_locator_analizi(g: Girdi, b: LocatorBaglami) -> LocatorAnalizi:
    """Kural 3'ün uygulama (Java/Appium) karşılığı (009; `triage.java`).

    Web'deki rol + ad yoklamasının yerine hata anındaki sayfa kaynağı kullanılır (Java
    kimliklerinde rol/ad yoktur, §2.5; çalışan cihaz CI'da ajan aracı olmadan yoklanamaz):

    1. Hata metninden kırık kimlik (+ kapsayıcı): `kimlik 'kapsayıcı' içinde 'aranan'`.
    2. Koşulan commit'in Java sembol tablosunda (`/symbols` + `platform`) o kimliği taşıyan TEK
       sabit (`Grup.SABIT`, önek değil).
    3. Hata anı sayfa kaynağında eski kimlik YOK, (kapsayıcı içinde) sembol tablosunda tanımsız ve
       eski kimlikle ortak sözcüğü olan TEK kimlik var → öneri `{locator_key, old_testid,
       new_testid}`. Onarım bunu Kimlikler.java'da yalnızca değer değişikliğiyle uygular ve
       cihazda tam paketle yeniden doğrular.
    """
    sinyaller: list[dict[str, Any]] = []
    hedef, kapsam, belirsiz = jv.kimlik_zinciri(g.locator, g.mesaj)
    if belirsiz:
        return LocatorAnalizi(
            None, sinyaller, "Hata iki kimlikten birini bekliyordu ('ya da'); aday üretilmez"
        )
    if not hedef or not ev.TESTID_RE.match(hedef):
        return LocatorAnalizi(None, sinyaller, "Hata metninde kimlik yok; aday üretilemez")
    if not b.sha:
        return LocatorAnalizi(None, sinyaller, "Koşunun commit'i bilinmiyor; sembol tablosu yok")
    platform = g.platform if g.platform in jv.UYGULAMA_PLATFORMLARI else None
    if platform is None:
        return LocatorAnalizi(
            None,
            sinyaller,
            "Uygulama testinin platformu bilinmiyor (run.ortam.platform / script.platform yok); "
            "Java sembol tablosu istenemez",
        )
    tc = services.toolchain()
    anahtar_s = f"semboller:{platform}"
    if anahtar_s not in b.ortak:
        try:
            b.ortak[anahtar_s] = tc.symbols(b.sha, platform=platform)
        except services.ToolchainHatasi as exc:
            b.ortak[anahtar_s] = None
            b.ortak[f"{anahtar_s}:hata"] = str(exc)
    semboller = b.ortak[anahtar_s]
    if semboller is None:
        return LocatorAnalizi(
            None, sinyaller, f"Sembol tablosu alınamadı: {b.ortak.get(f'{anahtar_s}:hata')}"
        )
    adaylar = _sembol_adaylari(semboller, hedef)
    if not adaylar:
        return LocatorAnalizi(
            None, sinyaller, f"Kimlik '{hedef}' koşulan commit'in Kimlikler.java'sında yok"
        )
    if len(adaylar) > 1:
        return LocatorAnalizi(
            None,
            sinyaller,
            f"Kimlik '{hedef}' birden çok sabite uyuyor: " + ", ".join(a[0] for a in adaylar[:5]),
        )
    anahtar, loc, po_dosyalari = adaylar[0]
    tid = str(loc.get("testId") or "")
    sinyaller.append(
        _sinyal(
            "niyet_sembol_tablosu",
            f"Kimlik sabiti '{anahtar}' niyeti",
            f"toolchain /symbols (java, {platform}) @ {b.sha[:12]}",
            loc.get("intent"),
        )
    )
    if tid != hedef:
        return LocatorAnalizi(None, sinyaller, "Önek kimlik (_ONEK; ürün koduna göre değişen)")
    if not g.sayfa_kaynagi:
        return LocatorAnalizi(None, sinyaller, "Hata anı sayfa kaynağı (sayfa-kaynagi.xml) yok")
    try:
        dugumler = jv.kimlik_dugumleri(g.sayfa_kaynagi, platform)
    except jv.SayfaKaynagiHatasi as exc:
        return LocatorAnalizi(None, sinyaller, f"Sayfa kaynağı okunamadı: {exc}")
    sabit, onekler = jv.bilinen_kimlikler(semboller)
    aday = jv.aday_kimlik(dugumler, hedef, kapsam, sabit, onekler)
    if aday.eski_ekranda or aday.kapsam_bulundu is False:
        return LocatorAnalizi(None, sinyaller, aday.neden)
    sinyaller.append(
        _sinyal(
            "eski_kimlik_ekranda_yok",
            f"Kimlik '{hedef}' hata anındaki ekranda yok"
            + (f" ('{kapsam}' kapsayıcısı ekranda)" if kapsam else ""),
            "sayfa-kaynagi.xml",
            g.sayfa_kaynagi_rel,
        )
    )
    if aday.yeni is None:
        return LocatorAnalizi(None, sinyaller, aday.neden)
    yeni = aday.yeni
    sinyaller.append(
        _sinyal(
            "test_id_farkli",
            f"Kimlik değişmiş: '{hedef}' → '{yeni}' (ekranda tek aday, sembol tablosunda tanımsız)",
            "sayfa-kaynagi.xml",
            None,
        )
    )
    oneri = {
        "locator_key": anahtar,
        "old_testid": hedef,
        "new_testid": yeni,
        "dosya": str(loc.get("file") or ""),
        "satir": loc.get("line") if isinstance(loc.get("line"), int) else None,
        "page_objects": sorted({d for d in po_dosyalari if d}),
        "rol": "",
        "ad": "",
        "intent": loc.get("intent"),
        "within": None,
        "scope_test_id": kapsam,
        "url_path": None,
        "sha": b.sha,
        "platform": platform,
        "kaynak": "sayfa_kaynagi",
        "probe": {
            "olculen": "hata_ani_sayfa_kaynagi",
            "matches": 1,
            "test_id": yeni,
            "scope_test_id": kapsam,
            "sha_eslesmesi": None,
            "uyari": None,
        },
        "sayfa_kaynagi": {
            "rel": g.sayfa_kaynagi_rel,
            "eski_var": False,
            "tanimsiz_kimlikler": aday.tanimsiz,
            "aday_sayisi": 1,
        },
        "son_yesil_run_id": b.son_yesil_run_id,
    }
    return LocatorAnalizi(oneri, sinyaller, None)


def web_java_locator_analizi(g: Girdi, b: LocatorBaglami) -> LocatorAnalizi:
    """Kural 3'ün web + Java (Playwright for Java; 011 §2.8) karşılığı.

    Kod tarafı Java'dır (kimlik ↔ sabit eşlemesi `ekranlar/Kimlikler.java`, sembol tablosu
    `/symbols` `lang=java, platform=web`); kanıt tarafı web'dir (hata anı DOM'u `sayfa.html` +
    Playwright trace'i). Java kimliklerinde rol/ad olmadığından çalışan uygulamada rol + ad
    yoklaması yapılamaz; aday Appium yolundaki kuralla hata anı DOM'undan seçilir:

    1. Hata metninden kırık testId (+ kapsayıcı): `Ekran.java` biçimi ya da çağrı günlüğündeki
       `getByTestId("x")` / `[data-testid="x"]`.
    2. Koşulan commit'in web + Java sembol tablosunda o testId'yi taşıyan TEK sabit (önek değil).
    3. Hata anı DOM'unda (yoksa trace DOM snapshot'ında; kapsayıcısız) eski testId YOK ve (kapsayıcı
       içinde) sembol tablosunda tanımsız, eski testId'yle ortak sözcüğü olan TEK testId var →
       öneri. trace DOM'u ek (destekleyen / karşı) kanıt olarak değerlendirilir.
    """
    sinyaller: list[dict[str, Any]] = []
    hedef, kapsam, belirsiz = jw.kirik_kimlik(g.locator, g.mesaj)
    if belirsiz:
        return LocatorAnalizi(
            None, sinyaller, "Hata iki kimlikten birini bekliyordu ('ya da'); aday üretilmez"
        )
    if not hedef or not ev.TESTID_RE.match(hedef):
        return LocatorAnalizi(None, sinyaller, "Hata metninde testId yok; aday üretilemez")
    if not b.sha:
        return LocatorAnalizi(None, sinyaller, "Koşunun commit'i bilinmiyor; sembol tablosu yok")
    tc = services.toolchain()
    anahtar_s = "semboller:web:java"
    if anahtar_s not in b.ortak:
        try:
            b.ortak[anahtar_s] = tc.symbols(b.sha, platform="web", lang="java")
        except services.ToolchainHatasi as exc:
            b.ortak[anahtar_s] = None
            b.ortak[f"{anahtar_s}:hata"] = str(exc)
    semboller = b.ortak[anahtar_s]
    if semboller is None:
        return LocatorAnalizi(
            None, sinyaller, f"Sembol tablosu alınamadı: {b.ortak.get(f'{anahtar_s}:hata')}"
        )
    adaylar = _sembol_adaylari(semboller, hedef)
    if not adaylar:
        return LocatorAnalizi(
            None, sinyaller, f"testId '{hedef}' koşulan commit'in Kimlikler.java'sında yok"
        )
    if len(adaylar) > 1:
        return LocatorAnalizi(
            None,
            sinyaller,
            f"testId '{hedef}' birden çok sabite uyuyor: " + ", ".join(a[0] for a in adaylar[:5]),
        )
    anahtar, loc, po_dosyalari = adaylar[0]
    tid = str(loc.get("testId") or "")
    sinyaller.append(
        _sinyal(
            "niyet_sembol_tablosu",
            f"Kimlik sabiti '{anahtar}' niyeti",
            f"toolchain /symbols (java, web) @ {b.sha[:12]}",
            loc.get("intent"),
        )
    )
    if tid != hedef:
        return LocatorAnalizi(None, sinyaller, "Önek kimlik (_ONEK; ürün koduna göre değişen)")
    trace = ev.trace_oku(b.kosu, b.trace_rel) if b.kosu is not None else ev.TraceOzeti()
    kaynak, kanit_rel = "sayfa.html", g.sayfa_html_rel
    if g.sayfa_html:
        try:
            dugumler = jw.dom_dugumleri(g.sayfa_html)
        except jw.DomHatasi as exc:
            return LocatorAnalizi(None, sinyaller, f"Hata anı DOM'u okunamadı: {exc}")
    elif trace.dom_kullanilabilir and not kapsam:
        # sayfa.html yoksa trace'in başarısız eylem snapshot'ı (kapsayıcı zinciri yok: yalnızca
        # kapsamsız kimlikte kullanılır).
        kaynak, kanit_rel = "trace.zip", b.trace_rel
        dugumler = [
            jv.KimlikDugumu(
                str(e["test_id"]), str(e.get("etiket") or ""), str(e.get("metin") or "")
            )
            for e in trace.elemanlar
        ]
    else:
        return LocatorAnalizi(
            None,
            sinyaller,
            "Hata anı DOM'u (sayfa.html) yok"
            + ("; kapsamlı kimlikte trace snapshot'ı yetmez" if kapsam else "; trace DOM'u da yok"),
        )
    sabit, onekler = jv.bilinen_kimlikler(semboller)
    aday = jv.aday_kimlik(dugumler, hedef, kapsam, sabit, onekler)
    if aday.eski_ekranda or aday.kapsam_bulundu is False:
        return LocatorAnalizi(None, sinyaller, aday.neden)
    sinyaller.append(
        _sinyal(
            "eski_kimlik_ekranda_yok",
            f"testId '{hedef}' hata anındaki sayfada yok"
            + (f" ('{kapsam}' kapsayıcısı sayfada)" if kapsam else ""),
            kaynak,
            kanit_rel,
        )
    )
    if aday.yeni is None:
        return LocatorAnalizi(None, sinyaller, aday.neden)
    yeni = aday.yeni
    trace_dom = _trace_dom_degerlendir(trace, hedef, yeni)
    if trace_dom["durum"] == "celisiyor":
        return LocatorAnalizi(None, sinyaller, trace_dom["aciklama"])
    if trace_dom["destekliyor"]:
        sinyaller.append(
            _sinyal("trace_dom", trace_dom["aciklama"], "trace.zip", trace_dom["kanit"])
        )
    sinyaller.append(
        _sinyal(
            "test_id_farkli",
            f"testId değişmiş: '{hedef}' → '{yeni}' (sayfada tek aday, sembol tablosunda tanımsız)",
            kaynak,
            None,
        )
    )
    oneri = {
        "locator_key": anahtar,
        "old_testid": hedef,
        "new_testid": yeni,
        "dosya": str(loc.get("file") or ""),
        "satir": loc.get("line") if isinstance(loc.get("line"), int) else None,
        "page_objects": sorted({d for d in po_dosyalari if d}),
        "rol": "",
        "ad": "",
        "intent": loc.get("intent"),
        "within": None,
        "scope_test_id": kapsam,
        "url_path": trace.dom_url_yolu or trace.son_url_yolu,
        "sha": b.sha,
        "platform": "web",
        "dil": "java",
        "kaynak": "hata_ani_dom",
        "probe": {
            "olculen": "hata_ani_dom",
            "matches": 1,
            "test_id": yeni,
            "scope_test_id": kapsam,
            "sha_eslesmesi": None,
            "uyari": None,
        },
        "dom": {
            "kaynak": kaynak,
            "rel": kanit_rel,
            "eski_var": False,
            "tanimsiz_kimlikler": aday.tanimsiz,
            "aday_sayisi": 1,
        },
        "son_yesil_run_id": b.son_yesil_run_id,
        "trace_dom": trace_dom,
    }
    return LocatorAnalizi(oneri, sinyaller, None)


def _trace_dom_degerlendir(trace: ev.TraceOzeti, eski: str, yeni: Any) -> dict[str, Any]:
    """trace DOM kanıtı: yalnızca eski testId yok VE yeni testId varsa kararı destekler.

    DOM'dan testId'li eleman çıkarılamadıysa "okunamadı" denir; "yok" asla bundan çıkarılmaz.
    """
    yeni_s = str(yeni) if yeni else None
    out: dict[str, Any] = {
        "durum": "okunamadi",
        "destekliyor": False,
        "eski_var": None,
        "yeni_var": None,
        "ozet": trace.ozet(),
        "aciklama": "",
        "kanit": trace.dom_url_yolu or trace.son_url_yolu,
    }
    if not trace.okundu:
        out["aciklama"] = f"trace okunamadı: {trace.hata or 'bilinmiyor'}"
        return out
    if not trace.dom_kullanilabilir:
        out["aciklama"] = (
            "trace DOM snapshot'ı okunamadı (testId'li eleman çıkarılamadı); "
            "testId var/yok yargısı yapılmadı"
        )
        return out
    eski_var = trace.test_id_var_mi(eski)
    yeni_var = bool(yeni_s and trace.test_id_var_mi(yeni_s))
    out.update(eski_var=eski_var, yeni_var=yeni_var)
    an = "başarısız eylem anındaki" if trace.dom_kaynagi == "basarisiz_eylem" else "son"
    if not eski_var and yeni_var:
        out.update(
            durum="destekliyor",
            destekliyor=True,
            aciklama=f"trace DOM ({an} snapshot): '{eski}' yok, '{yeni_s}' var",
        )
    elif eski_var:
        out.update(
            durum="celisiyor",
            aciklama=f"trace DOM ({an} snapshot): eski testId '{eski}' hâlâ var (karşı kanıt)",
        )
    else:
        out.update(
            durum="belirsiz",
            aciklama=f"trace DOM ({an} snapshot): '{eski}' yok"
            + (f"; '{yeni_s}' trace anında görülmedi" if yeni_s else ""),
        )
    return out


# ============================================================================= LLM


LLM_SINIFLAR = frozenset(
    {"product_defect", "test_maintenance", "test_data", "flaky", "environment", "unknown"}
)


def kural_sinyalleri(g: Girdi, ek_sinyaller: list[dict[str, Any]], neden: str | None) -> list[str]:
    """Her kuralın ne gördüğü (LLM girdisinin `Kural sinyalleri`; koşudan bağımsız, kararlı)."""
    saglik = ev.mapping(g.saglik)
    if saglik.get("ok") is True:
        k1 = "kural 1 (ortam): sağlık kontrolü başarılı, ağ hatası yok"
    else:
        k1 = "kural 1 (ortam): sağlık bilgisi yok, ağ hatası yok"
    if g.deneme_durumlari and len(set(g.deneme_durumlari)) == 1 and len(g.deneme_durumlari) > 1:
        k2 = f"kural 2 (flaky): {len(g.deneme_durumlari)} denemenin hepsi kırmızı"
    elif g.tekrar_durumlari:
        k2 = f"kural 2 (flaky): {len(g.tekrar_durumlari)} tekrarın hiçbiri geçmedi"
    else:
        k2 = "kural 2 (flaky): yeniden denemede geçen yok"
    if any(s.get("kod") == "locator_0_eleman" for s in ek_sinyaller):
        k3 = f"kural 3 (locator): 0 eleman; öneri yok — {neden or 'analiz yapılamadı'}"
    else:
        k3 = "kural 3 (locator): bulunamayan/çoklu eleman sinyali yok"
    if g.tur() == "assertion":
        k4 = (
            "kural 4 (assertion): beklenen/gerçekleşen farkı var ama sayfa yapısı / tekrar "
            "tutarlılığı doğrulanamadı"
        )
    else:
        k4 = "kural 4 (assertion): beklenen/gerçekleşen değer yok"
    k5 = "kural 5 (test verisi): fixture hatası yok"
    return [k1, k2, k3, k4, k5]


LLM_ALT_TURLER = frozenset({"locator", "wait", "flow"})


def _norm(metin: Any) -> str:
    return " ".join(str(metin or "").split()).casefold()


def llm_ciktisi_dogrula(
    g: Girdi, sinif: str, alt_tur: str | None
) -> tuple[str, str | None, list[dict[str, Any]]]:
    """LLM çıktısının prompt'taki sert kısıtlara deterministik son doğrulaması.

    - Bilinmeyen sınıf → `unknown`.
    - `environment`: sağlık kontrolü başarılı (`saglik.ok=true`) ve ağ hatası sinyali yokken
      reddedilir → `unknown` (ortam kararı yalnızca kanıtla verilir; triage.md).
    - `test_maintenance` alt türü yalnızca locator | wait | flow; aksi → `unknown`.
    Dönüş: (sınıf, alt tür, düzeltme sinyalleri). Düzeltmeler sinyal olarak kaydedilir ve
    `triage.classified` denetim kaydında sinyal kodlarıyla görünür.
    """
    duz: list[dict[str, Any]] = []
    if sinif not in LLM_SINIFLAR:
        duz.append(
            _sinyal(
                "llm_sinif_gecersiz",
                f"Model geçersiz sınıf önerdi ('{ev.temiz(sinif, 40)}'); unknown'a indirildi",
                "deterministik doğrulama",
                None,
            )
        )
        return "unknown", None, duz
    if sinif == "environment" and ev.mapping(g.saglik).get("ok") is True and not ag_sinyali_var(g):
        duz.append(
            _sinyal(
                "llm_ortam_reddedildi",
                "Model 'environment' önerdi ama sağlık kontrolü başarılı ve ağ hatası sinyali "
                "yok; ortam kararı reddedildi → unknown (insan incelemesi)",
                "deterministik doğrulama (Constitution XI)",
                None,
            )
        )
        return "unknown", None, duz
    if sinif == "test_maintenance" and alt_tur not in LLM_ALT_TURLER:
        duz.append(
            _sinyal(
                "llm_alt_tur_gecersiz",
                f"Model test_maintenance için geçersiz alt tür önerdi ('{alt_tur or '-'}'; "
                "yalnızca locator | wait | flow); unknown'a indirildi",
                "deterministik doğrulama",
                None,
            )
        )
        return "unknown", None, duz
    return sinif, (alt_tur if sinif == "test_maintenance" else None), duz


def llm_siniflandir(
    engine: Engine,
    tk: TestKaniti,
    ek_sinyaller: list[dict[str, Any]],
    neden: str | None,
) -> tuple[Karar, dict[str, Any] | None, uuid.UUID | None, str | None]:
    """Yalnızca kural eşleşmediğinde (XI). Girdi `gateway.defects` kurucularıyla kurulur (golden
    beyanı ve birebir replay anahtarı için tek biçim); kanıt `<untrusted>` blokta.

    Dönüş: (karar, llm kaydı, ai_call_id, mod). REPLAY'de uyan golden yoksa geçidin nötr yedeği
    (`unknown`, mod `replay_miss`) döner: bu bir model kararı değildir → `karar_kaynagi='rule'`.
    """
    from tp_core.gateway import (
        GatewayError,
        ReplayMiss,
        ReplayNoOutput,
        ReplayNotFound,
        defect_replay_key,
        deterministic_call_id,
        failure_block,
        load_schema,
        triage_messages,
    )

    g = tk.girdi
    call_id = deterministic_call_id(f"triage:{tk.anahtar}", "triage")
    blok = failure_block(
        tk.ham.get("failure") or {},
        test_title=g.test_adi,
        test_file=g.dosya,
        story_key=tk.story_key,
        case_ref=tk.case_ref,
        saglik=g.saglik,
        statuses=tk.ham.get("statuses") or None,
        consistent=tk.ham.get("consistent"),
        break_campaign=g.kirma,
        rule_signals=kural_sinyalleri(g, ek_sinyaller, neden),
        include_aria=True,
    )
    try:
        gw = services.gateway(engine)
        schema = load_schema(gw.rules_dir, "triage")
        sonuc = gw.call(
            "triage",
            "triage",
            triage_messages(blok),
            schema,
            replay_key=defect_replay_key(tk.story_key),
            max_tokens=2048,
            call_id=call_id,
        )
    except (ReplayMiss, ReplayNoOutput, ReplayNotFound) as exc:
        return (
            Karar(
                "unknown",
                None,
                None,
                [
                    *ek_sinyaller,
                    _sinyal(
                        "llm_replay_miss",
                        "Kural eşleşmedi; REPLAY-MISS: bu hata için kayıtlı model çıktısı yok "
                        "(canlı model gerekir) — insan incelemesi",
                        "model geçidi",
                        type(exc).__name__,
                    ),
                ],
            ),
            None,
            call_id,
            "replay_miss",
        )
    except GatewayError as exc:
        return (
            Karar(
                "unknown",
                None,
                None,
                [
                    *ek_sinyaller,
                    _sinyal(
                        "llm_hatasi",
                        "Kural eşleşmedi; model çağrısı başarısız — insan incelemesi",
                        "model geçidi",
                        f"{type(exc).__name__}: {exc}",
                    ),
                ],
            ),
            None,
            None,
            None,
        )
    cikti = sonuc.output if isinstance(sonuc.output, Mapping) else {}
    ham_sinif = str(cikti.get("class") or "unknown")
    alt = cikti.get("sub_type")
    alt_tur = ev.temiz(alt, 40) if isinstance(alt, str) and alt.strip() else None
    gerekce = ev.temiz(cikti.get("rationale"), 800) if cikti.get("rationale") else None
    ham_sinyaller = cikti.get("signals") if isinstance(cikti.get("signals"), list) else []
    llm_sinyal_metinleri = [ev.temiz(s, 280) for s in ham_sinyaller[:10] if s]
    sinif, alt_tur, duzeltmeler = llm_ciktisi_dogrula(g, ham_sinif, alt_tur)
    kayit = {
        "class": sinif,
        "sub_type": alt_tur,
        "rationale": gerekce,
        "signals": llm_sinyal_metinleri,
        "mod": sonuc.mode,
        # Deterministik son doğrulama (Constitution XI): modelin ham önerisi ve düzeltmeler.
        "ham_class": ev.temiz(ham_sinif, 40),
        "ham_sub_type": ev.temiz(alt, 40) if isinstance(alt, str) else None,
        "dogrulama": [d["kod"] for d in duzeltmeler],
    }
    if sonuc.mode == "replay_miss":
        # Geçidin nötr REPLAY-MISS yedeği (rules/replay/triage/on_miss.json): model kararı yok.
        karar = Karar(
            "unknown",
            None,
            None,
            [
                *ek_sinyaller,
                _sinyal(
                    "llm_replay_miss",
                    "Kural eşleşmedi; REPLAY-MISS: bu hata için kayıtlı model çıktısı yok "
                    "(canlı model gerekir) — insan incelemesi",
                    "model geçidi (nötr yedek)",
                    None,
                ),
            ],
            gerekce=gerekce,
        )
        return karar, kayit, sonuc.call_id, sonuc.mode
    girdi_metni = _norm(blok)
    llm_sinyaller = [
        _sinyal(
            "llm" if _norm(x) and _norm(x) in girdi_metni else "llm_dogrulanamadi",
            x,
            "LLM (yalnızca kural eşleşmediğinde)"
            if _norm(x) and _norm(x) in girdi_metni
            else "LLM — girdide birebir bulunamadı (yorum; kanıt değil)",
            None,
        )
        for x in kayit["signals"]
    ]
    karar = Karar(
        sinif,
        alt_tur if sinif == "test_maintenance" else None,
        None,
        [*ek_sinyaller, *llm_sinyaller, *duzeltmeler],
        karar_kaynagi="llm",
        gerekce=gerekce,
    )
    return karar, kayit, sonuc.call_id, sonuc.mode


# ============================================================================= ana iş


@dataclass
class Sonuc:
    tk: TestKaniti
    karar: Karar
    imza: str
    llm: dict[str, Any] | None = None
    ai_call_id: uuid.UUID | None = None
    mod: str | None = None


def _kanit_ozeti(tk: TestKaniti, karar: Karar) -> dict[str, Any]:
    g = tk.girdi
    probe = None
    if karar.oneri is not None:
        probe = karar.oneri.get("probe")
    else:
        probe_s = next((s for s in karar.sinyaller if s.get("kod") == "locator_probe"), None)
        probe = {"ozet": probe_s["aciklama"]} if probe_s else None
    anahtarlar = [g.beklenen or "", g.gerceklesen or ""]
    if karar.oneri:
        anahtarlar.append(str(karar.oneri.get("ad") or ""))
    return {
        "hata_mesaji": g.mesaj,
        "hata_turu": g.tur(),
        "beklenen": g.beklenen,
        "gerceklesen": g.gerceklesen,
        "konum": g.konum,
        "adim": g.adim,
        "locator": g.locator,
        "matcher": g.matcher,
        "aria_snippet": ev.aria_parcasi(g.aria, [a for a in anahtarlar if a]),
        "aria_kapsami": g.aria_kapsami,
        "locator_probe": probe,
        "trace_dom": karar.oneri.get("trace_dom") if karar.oneri else None,
        "saglik": dict(g.saglik) if isinstance(g.saglik, Mapping) else None,
        "tekrar_durumlari": g.tekrar_durumlari,
        "deneme_durumlari": g.deneme_durumlari,
        "test_durumu": tk.test_status,
        "son_yesil_run_id": tk.son_yesil_run_id,
        "uyarilar": tk.uyarilar[:10],
        # Toolchain'in ham hata kaydı ({failure, statuses, consistent}): bugs şeridi
        # `gateway.failure_block`'u bundan kurar (replay anahtarı triage'ınkiyle aynı kalır).
        "ham": dict(tk.ham) if tk.ham else None,
    }


def _kasitli_taslaksiz(u: Uygunluk, k: Karar) -> bool:
    """Kasıtlı kırılmanın gerçek defect kararı taslağa gitmez (varsayılan; `kirma_taslak`)."""
    return u.kirma and k.sinif == "product_defect" and not services.kirma_taslak()


def _kaydet(session: Session, run: Run, u: Uygunluk, sonuclar: list[Sonuc]) -> list[Failure]:
    yeni: list[Failure] = []
    for s in sonuclar:
        fid = failure_id_for(s.tk.anahtar)
        if session.get(Failure, fid) is not None:
            continue
        k = s.karar
        kasitli = _kasitli_taslaksiz(u, k)
        oneri_turu = "none" if kasitli else k.oneri_turu
        if kasitli:
            onceki = k.oneri_yok_nedeni
            k.oneri_yok_nedeni = f"{KIRMA_TASLAK_YOK} {onceki}" if onceki else KIRMA_TASLAK_YOK
        f = Failure(
            id=fid,
            run_id=run.id,
            test_result_id=s.tk.test_result_id,
            test_adi=ev.temiz(s.tk.girdi.test_adi, 500),
            hata_imzasi=s.imza,
            sinif=k.sinif,
            alt_tur=k.alt_tur,
            eslesen_sinyaller=k.sinyaller,
            karar_kaynagi=k.karar_kaynagi,
            gerekce=(f"{k.gerekce} {KIRMA_TASLAK_YOK}" if kasitli and k.gerekce else None)
            or k.gerekce
            or k.oneri_yok_nedeni,
            oneri_turu=oneri_turu,
            oneri_durumu="proposed" if oneri_turu != "none" else "none",
            ai_call_id=s.ai_call_id,
            uretim_modu=s.mod,
        )
        session.add(f)
        session.flush()
        session.add(
            FailureEk(
                failure_id=fid,
                anahtar=s.tk.anahtar,
                kaynak=u.kaynak,
                kirma=u.kirma,
                script_id=run.script_id,
                script_kontrol_id=u.kontrol.id if u.kontrol is not None else None,
                kural=k.kural,
                kanit=_kanit_ozeti(s.tk, k),
                kanit_linkleri=s.tk.kanit_linkleri,
                oneri=k.oneri,
                oneri_yok_nedeni=k.oneri_yok_nedeni,
                llm=s.llm,
            )
        )
        yeni.append(f)
        publish_tx(
            session.connection(),
            "failure.classified",
            {
                "id": str(fid),
                "failure_id": str(fid),
                "run_id": str(run.id),
                "script_id": str(run.script_id) if run.script_id else None,
                "test_adi": f.test_adi,
                "sinif": f.sinif,
                "alt_tur": f.alt_tur,
                "kural": k.kural,
                "karar_kaynagi": f.karar_kaynagi,
                "oneri_turu": f.oneri_turu,
                "mode": s.mod,
            },
        )
        audit_on_commit(
            session,
            "system",
            "triage.classified",
            f"failure:{fid}",
            {
                "run_id": str(run.id),
                "test_adi": f.test_adi,
                "sinif": f.sinif,
                "alt_tur": f.alt_tur,
                "kural": k.kural,
                "karar_kaynagi": f.karar_kaynagi,
                "sinyaller": [x.get("kod") for x in k.sinyaller],
                "oneri_turu": f.oneri_turu,
                "oneri": (
                    {kk: k.oneri.get(kk) for kk in ("locator_key", "old_testid", "new_testid")}
                    if k.oneri
                    else None
                ),
                "oneri_yok_nedeni": k.oneri_yok_nedeni,
                "ai_call_id": str(s.ai_call_id) if s.ai_call_id else None,
                "llm_dogrulama": (s.llm or {}).get("dogrulama") or None,
                "mode": s.mod,
                "kaynak": u.kaynak,
                "kirma": u.kirma,
                "bug_taslagi": "kasitli_kirilma_yazilmaz" if kasitli else None,
            },
        )
    return yeni


def _kosu_isaretle(
    session: Session, run_id: uuid.UUID, durum: str, neden: str | None, sayilar: dict[str, Any]
) -> None:
    if session.get(TriageKosu, run_id) is None:
        session.add(TriageKosu(run_id=run_id, durum=durum, neden=neden, sayilar=sayilar))
        audit_on_commit(
            session,
            "system",
            "triage.run_done" if durum == "done" else "triage.run_skipped",
            f"run:{run_id}",
            {"neden": neden, **sayilar},
        )


def classify_run(engine: Engine, run_id: uuid.UUID, *, son_deneme: bool = True) -> dict[str, Any]:
    """Koşunun başarısız testlerini sınıflandırır (idempotent). `triage.classify` işinin gövdesi."""
    with Session(engine, expire_on_commit=False) as session, session.begin():
        jobq.idempotency_lock(session.connection(), f"triage:{run_id}")
        run = session.get(Run, run_id)
        if run is None:
            return {"durum": "yok", "run_id": str(run_id)}
        if session.get(TriageKosu, run_id) is not None:
            onceki = True
        else:
            onceki = False
            u = uygunluk(session, run, son_deneme=son_deneme)
            if not u.uygun:
                _kosu_isaretle(session, run.id, "skipped", u.neden, {})
                return {"durum": "atlandi", "neden": u.neden, "run_id": str(run_id)}
            kanitlar, neden = kanitlari_topla(session, run, u)
            if not kanitlar:
                _kosu_isaretle(session, run.id, "skipped", neden, {})
                return {"durum": "atlandi", "neden": neden, "run_id": str(run_id)}
            mevcut = set(
                session.scalars(
                    select(FailureEk.anahtar).where(
                        FailureEk.anahtar.in_([k.anahtar for k in kanitlar])
                    )
                )
            )
            kanitlar = [k for k in kanitlar if k.anahtar not in mevcut]
            a = run.artefaktlar or {}
            kosu = ev.kosu_dizini(services.artifacts_root(), a.get("dizin"))
            run_kopya = run
    if onceki:
        return {"durum": "zaten_yapildi", "run_id": str(run_id), **_bug_taslaklari(run_id)}

    # Kurallar ve (gerekirse) LLM: işlem dışında (dış çağrılar uzun sürebilir).
    sonuclar: list[Sonuc] = []
    ortak: dict[str, Any] = {}
    for tk in kanitlar:
        b = LocatorBaglami(run_kopya.commit, tk.trace_rel, kosu, tk.son_yesil_run_id, ortak)
        karar, ek_sinyaller, neden = siniflandir(tk.girdi, lambda g, b=b: locator_analizi(g, b))
        imza = hata_imzasi(tk.girdi)
        if karar is None:
            karar, llm, ai_call_id, mod = llm_siniflandir(engine, tk, ek_sinyaller, neden)
            karar.oneri_yok_nedeni = neden
            sonuclar.append(Sonuc(tk, karar, imza, llm, ai_call_id, mod))
        else:
            if karar.oneri is None and (neden or ek_sinyaller):
                # Kural 3 değerlendirildi ama öneri çıkmadı; karar sonraki kuraldan geldi.
                karar.oneri_yok_nedeni = neden
                karar.sinyaller = [*ek_sinyaller, *karar.sinyaller]
            sonuclar.append(Sonuc(tk, karar, imza))

    sayilar: dict[str, int] = {}
    for s in sonuclar:
        sayilar[s.karar.sinif] = sayilar.get(s.karar.sinif, 0) + 1
    with Session(engine, expire_on_commit=False) as session, session.begin():
        jobq.idempotency_lock(session.connection(), f"triage:{run_id}")
        run = session.get(Run, run_id)
        if run is None:
            return {"durum": "yok", "run_id": str(run_id)}
        if session.get(TriageKosu, run_id) is None:
            u = uygunluk(session, run, son_deneme=True)
            _kaydet(session, run, u, sonuclar)
            _kosu_isaretle(session, run.id, "done", None, dict(sayilar))
    return {"durum": "done", "run_id": str(run_id), "siniflar": sayilar, **_bug_taslaklari(run_id)}


# ============================================================================= bug taslağı


def _bug_taslaklari(run_id: uuid.UUID) -> dict[str, Any]:
    """`product_defect` failure'lar için bugs şeridinden taslak ister (taslağı olmayanlar).

    Taslak oluşturma (mükerrer araması, şemalı içerik, insan onayı) bugs şeridindedir; şerit yoksa
    (`ImportError`) atlanır. Hata iş sonucunu bozmaz: denetime yazılır, sonraki çağrı yeniden dener.
    """
    from tp_core.models import session_scope

    kirma_taslak = services.kirma_taslak()
    with session_scope() as s:
        satirlar = s.execute(
            select(Failure.id, FailureEk.kirma)
            .outerjoin(FailureEk, FailureEk.failure_id == Failure.id)
            .where(Failure.run_id == run_id, Failure.sinif == "product_defect")
        ).all()
        # Kasıtlı kırılmanın kırmızısı beklenen sonuçtur: Jira'ya yazılacak taslak istenmez.
        kasitli = sum(1 for _, kirma in satirlar if kirma and not kirma_taslak)
        adaylar = [
            fid
            for fid, kirma in satirlar
            if not (kirma and not kirma_taslak) and bug_taslagi_id(s, fid) is None
        ]
    ek_bilgi: dict[str, Any] = {"bug_taslagi_atlanan_kasitli": kasitli} if kasitli else {}
    if not adaylar:
        return {"bug_taslagi_istenen": 0, **ek_bilgi}
    try:
        from tp_core.features.bugs import create_draft_from_failure  # type: ignore[attr-defined]
    except ImportError:
        return {"bug_taslagi_istenen": 0, "bug_taslagi": "bugs şeridi yok", **ek_bilgi}
    istenen = 0
    for fid in adaylar:
        try:
            with session_scope() as s:
                create_draft_from_failure(s, fid)
            istenen += 1
        except Exception as exc:
            log.warning("bug taslağı istenemedi (failure %s): %s", fid, exc)
            try:
                with session_scope() as s:
                    audit_on_commit(
                        s,
                        "system",
                        "triage.bug_draft_request_failed",
                        f"failure:{fid}",
                        {"hata": ev.temiz(exc, 300)},
                    )
            except Exception:  # pragma: no cover - denetim de yazılamazsa yalnızca log
                log.exception("denetim yazılamadı")
    return {"bug_taslagi_istenen": istenen, **ek_bilgi}


# ============================================================================= süpürme


def sweep(engine: Engine, simdi: datetime | None = None) -> dict[str, Any]:
    """Triage'ı yapılmamış son kırmızı koşular için `triage.classify` kuyruğa ekler.

    Kanca (`on_run_finished`) bağlanmamış olsa da kırmızı koşular kaçmaz; idempotens anahtarı
    aynı koşu için ikinci işi engeller.
    """
    simdi = simdi or datetime.now(UTC)
    with Session(engine) as session, session.begin():
        ids = list(
            session.scalars(
                select(Run.id)
                .outerjoin(TriageKosu, TriageKosu.run_id == Run.id)
                .where(
                    Run.sonuc.in_(KIRMIZI),
                    TriageKosu.run_id.is_(None),
                    Run.olusturma >= simdi - SUPURME_PENCERESI,
                )
                .order_by(Run.olusturma)
                .limit(50)
            )
        )
        for rid in ids:
            enqueue_classify(session.connection(), rid)
    return {"kuyruga": len(ids)}


def ensure_sweep(conn: Connection, *, gecikme_s: float = 0.0) -> uuid.UUID | None:
    """Süpürme işi kuyrukta yoksa ekler (tek bekleyen iş)."""
    if services.sweep_s() <= 0:
        return None
    jobq.idempotency_lock(conn, JOB_SWEEP)
    bekleyen = conn.execute(
        text("SELECT id FROM job WHERE tur = :t AND durum IN ('queued', 'retry') LIMIT 1"),
        {"t": JOB_SWEEP},
    ).scalar_one_or_none()
    if bekleyen is not None:
        return None
    zaman = datetime.now(UTC) + timedelta(seconds=gecikme_s) if gecikme_s > 0 else None
    return jobq.enqueue(conn, JOB_SWEEP, {}, run_after=zaman)


def purge_sweep_jobs(engine: Engine, saklama: timedelta = timedelta(hours=1)) -> int:
    with engine.begin() as conn:
        return (
            conn.execute(
                text(
                    "DELETE FROM job WHERE tur = :t AND durum IN ('done', 'failed', 'cancelled') "
                    "AND COALESCE(bitis, guncelleme) < now() - make_interval(secs => :sn)"
                ),
                {"t": JOB_SWEEP, "sn": saklama.total_seconds()},
            ).rowcount
            or 0
        )


# ============================================================================= görünüm


def _url(run_id: uuid.UUID, yol: str | None) -> str | None:
    if not yol:
        return None
    return f"/api/artifacts/runs/{run_id}/{yol}"


ONARIM_DURUMU = {"proposed": "proposed", "pr_open": "pr_open", "merged": "merged"}


def bug_taslagi_id(session: Session, failure_id: uuid.UUID) -> uuid.UUID | None:
    """Başarısızlığın bug taslağı: kendi taslağı ya da aynı hata imzasıyla açılmış taslağa
    bağlandıysa (bugs şeridi `bug_draft_ek.ilgili_failure_ids`) o taslak."""
    bid = session.scalar(
        select(BugDraft.id).where(BugDraft.failure_id == failure_id).order_by(BugDraft.olusturma)
    )
    if bid is not None:
        return bid
    if not session.execute(text("SELECT to_regclass('bug_draft_ek') IS NOT NULL")).scalar():
        return None
    return session.execute(
        text(
            "SELECT bug_draft_id FROM bug_draft_ek WHERE ilgili_failure_ids @> "
            "CAST(:j AS jsonb) ORDER BY olusturma LIMIT 1"
        ),
        {"j": f'["{failure_id}"]'},
    ).scalar()


def _bug_taslagi_ozeti(session: Session, bug_id: uuid.UUID) -> dict[str, Any]:
    """Taslağın durumu / Jira anahtarı / Türkçe sonuç metni (portal ek çağrı yapmasın)."""
    try:
        from tp_core.features.bugs import serialize as bug_serialize
        from tp_core.models.bugs_feature import BugDraftEk
    except ImportError:
        return {}
    b = session.get(BugDraft, bug_id)
    if b is None:
        return {}
    try:
        metin = bug_serialize.sonuc_metni(b, session.get(BugDraftEk, b.id))
    except Exception as exc:  # özet triage sonucunu gizlemesin
        log.warning("bug taslağı özeti alınamadı (%s): %s", bug_id, exc)
        metin = None
    return {
        "taslak_durumu": b.durum,
        "jira_key": b.jira_key,
        "karar": b.karar,
        "sonuc_metni": metin,
    }


def _onarim_gorunumu(session: Session, f: Failure) -> dict[str, Any] | None:
    """Repair şeridinin onarım kaydı (`repair.views.oneri_blogu`) varsa öneriyle birleştirilir:
    durum, PR, AST koruması, yerel kontrol, etkilenen testler (yoksa None)."""
    try:
        from tp_core.features.repair import views as repair_views
    except ImportError:
        return None
    try:
        sonuc = repair_views.oneri_blogu(session, f.id)
    except Exception as exc:  # görünüm triage sonucunu gizlemesin
        log.warning("onarım görünümü alınamadı (%s): %s", f.id, exc)
        return None
    return dict(sonuc) if isinstance(sonuc, Mapping) else None


def serialize(
    session: Session,
    f: Failure,
    ek: FailureEk | None,
    run: Run | None,
    *,
    yalniz_yayinlanmis_bug: bool = False,
) -> dict:
    """Triage kaydı. `yalniz_yayinlanmis_bug=True` (developer, specs/012 §4.2 `bug.read`):
    yayınlanmamış bug taslağı yanıtta görünmez (kimlik ve özet dahil)."""
    k = (ek.kanit if ek else None) or {}
    oneri: dict[str, Any] | None = None
    bug_id = bug_taslagi_id(session, f.id)
    if bug_id is not None and yalniz_yayinlanmis_bug:
        taslak = session.get(BugDraft, bug_id)
        if taslak is None or taslak.durum != "published":
            bug_id = None
    if ek is not None and ek.oneri:
        o = ek.oneri
        oneri = {
            "tur": "locator_fix",
            "dosya": o.get("dosya"),
            "anahtar": o.get("locator_key"),
            "eski_test_id": o.get("old_testid"),
            "yeni_test_id": o.get("new_testid"),
            "rol": o.get("rol"),
            "ad": o.get("ad"),
            "within": o.get("within"),
            "scope_test_id": o.get("scope_test_id"),
            "dogrulama": [
                s.get("aciklama")
                for s in f.eslesen_sinyaller or []
                if isinstance(s, Mapping) and s.get("kod") != "locator_0_eleman"
            ],
            "durum": ONARIM_DURUMU.get(f.oneri_durumu, "rejected")
            if f.oneri_durumu != "none"
            else "proposed",
            "pr": None,
            "locator_key": o.get("locator_key"),
            "old_testid": o.get("old_testid"),
            "new_testid": o.get("new_testid"),
            "url_path": o.get("url_path"),
            "sha": o.get("sha"),
            "son_yesil_run_id": o.get("son_yesil_run_id"),
            "probe": o.get("probe"),
            # 009: uygulama önerisinin kaynağı (`sayfa_kaynagi`), platformu ve hata anı sayfa
            # kaynağı özeti (portal Ş7 gösterir).
            "kaynak": o.get("kaynak"),
            "platform": o.get("platform"),
            "sayfa_kaynagi": o.get("sayfa_kaynagi"),
            # 011: web + Java önerisinin dili ve hata anı DOM'u özeti.
            "dil": o.get("dil"),
            "dom": o.get("dom"),
        }
        ek_gorunum = _onarim_gorunumu(session, f)
        if ek_gorunum:
            oneri.update(ek_gorunum)
    elif bug_id is not None:
        oneri = {
            "tur": "bug_draft",
            "bug_draft_id": str(bug_id),
            **_bug_taslagi_ozeti(session, bug_id),
        }
    probe = k.get("locator_probe") if isinstance(k.get("locator_probe"), Mapping) else None
    kanit = {
        "hata_mesaji": k.get("hata_mesaji"),
        "beklenen": k.get("beklenen"),
        "gerceklesen": k.get("gerceklesen"),
        "konum": k.get("konum"),
        "aria_snippet": k.get("aria_snippet"),
        "locator_probe": (
            {
                "rol": probe.get("rol"),
                "ad": probe.get("ad"),
                "scope_test_id": probe.get("scope_test_id"),
                "matches": probe.get("matches"),
                "test_id": probe.get("test_id"),
                "olculen": probe.get("olculen"),
                "uygulama_sha": probe.get("uygulama_sha"),
                "sha_eslesmesi": probe.get("sha_eslesmesi"),
                "uyari": probe.get("uyari"),
                "oneri_uretilebilir": probe.get("oneri_uretilebilir"),
            }
            if probe and "matches" in probe
            else None
        ),
        "saglik": k.get("saglik"),
        "hata_turu": k.get("hata_turu"),
        "adim": k.get("adim"),
        "locator": k.get("locator"),
        "tekrar_durumlari": k.get("tekrar_durumlari") or [],
        "deneme_durumlari": k.get("deneme_durumlari") or [],
        "uyarilar": k.get("uyarilar") or [],
        # trace DOM değerlendirmesi (destekliyor=false → karşı/okunamayan kanıt; eşleşen değil)
        "trace_dom": k.get("trace_dom"),
    }
    linkler = [
        {"etiket": x.get("etiket"), "url": _url(f.run_id, x.get("yol")), "tur": x.get("tur")}
        for x in (ek.kanit_linkleri if ek else []) or []
        if isinstance(x, Mapping)
    ]
    return {
        "id": str(f.id),
        "run_id": str(f.run_id),
        "test_result_id": str(f.test_result_id) if f.test_result_id else None,
        "test_adi": f.test_adi,
        "hata_imzasi": f.hata_imzasi,
        "hata_mesaji": k.get("hata_mesaji") or "",
        "sinif": f.sinif,
        "alt_tur": f.alt_tur,
        "eslesen_sinyaller": f.eslesen_sinyaller or [],
        "karar_kaynagi": f.karar_kaynagi,
        "kural": ek.kural if ek else None,
        "gerekce": f.gerekce,
        "llm_yorumu": (ek.llm or {}).get("rationale") if ek and ek.llm else None,
        "oneri": oneri,
        "oneri_turu": f.oneri_turu,
        "oneri_durumu": f.oneri_durumu,
        "oneri_yok_nedeni": ek.oneri_yok_nedeni if ek else None,
        "bug_draft_id": str(bug_id) if bug_id else None,
        "kanit": kanit,
        "kanit_linkleri": linkler,
        # null: model çağrısı yok (kural kararı); "live" uydurulmaz.
        "mode": f.uretim_modu,
        "ai_call_id": str(f.ai_call_id) if f.ai_call_id else None,
        "zaman": f.olusturma.isoformat() if f.olusturma else None,
        "script_id": str(ek.script_id)
        if ek and ek.script_id
        else (str(run.script_id) if run and run.script_id else None),
        "kaynak": ek.kaynak if ek else None,
        "kirma": bool(ek.kirma) if ek else False,
        # Kasıtlı kırılma kırmızısı Jira'ya yazılmaz (beklenen kırarak doğrulama sonucu).
        "jira_yazilmaz": bool(
            ek and ek.kirma and f.sinif == "product_defect" and f.oneri_turu == "none"
        ),
        "commit": run.commit if run else None,
        "tetik": run.tetik if run else None,
        "pr_no": run.pr_no if run else None,
        # 009: hatanın platformu (run.ortam.platform → run.json → script.platform; web/None).
        "platform": kosu_platformu(session, run) if run is not None else None,
        # 011: hatanın üretim dili (run.ortam.dil → run.json → script.dil; ts | java | None).
        "dil": kosu_dili(session, run) if run is not None else None,
    }


def get_failure(
    session: Session, failure_id: uuid.UUID, *, yalniz_yayinlanmis_bug: bool = False
) -> dict[str, Any] | None:
    f = session.get(Failure, failure_id)
    if f is None:
        return None
    return serialize(
        session,
        f,
        session.get(FailureEk, f.id),
        session.get(Run, f.run_id),
        yalniz_yayinlanmis_bug=yalniz_yayinlanmis_bug,
    )


def list_failures(
    session: Session,
    *,
    run_id: uuid.UUID | None = None,
    sinif: str | None = None,
    karar_kaynagi: str | None = None,
    oneri_turu: str | None = None,
    oneri_durumu: str | None = None,
    script_id: uuid.UUID | None = None,
    kaynak: str | None = None,
    limit: int = 50,
    yalniz_yayinlanmis_bug: bool = False,
) -> list[dict[str, Any]]:
    q = (
        select(Failure, FailureEk, Run)
        .outerjoin(FailureEk, FailureEk.failure_id == Failure.id)
        .join(Run, Run.id == Failure.run_id)
    )
    kosullar = []
    if run_id is not None:
        kosullar.append(Failure.run_id == run_id)
    if sinif is not None:
        kosullar.append(Failure.sinif == sinif)
    if karar_kaynagi is not None:
        kosullar.append(Failure.karar_kaynagi == karar_kaynagi)
    if oneri_turu is not None:
        kosullar.append(Failure.oneri_turu == oneri_turu)
    if oneri_durumu is not None:
        kosullar.append(Failure.oneri_durumu == oneri_durumu)
    if script_id is not None:
        kosullar.append(Run.script_id == script_id)
    if kaynak is not None:
        kosullar.append(FailureEk.kaynak == kaynak)
    if kosullar:
        q = q.where(and_(*kosullar))
    q = q.order_by(Failure.olusturma.desc(), Failure.test_adi).limit(limit)
    return [
        serialize(session, f, ek, run, yalniz_yayinlanmis_bug=yalniz_yayinlanmis_bug)
        for f, ek, run in session.execute(q).all()
    ]


# ============================================================================= yeniden triage


class YenidenTriageReddi(ValueError):
    """Koşunun triage sonuçları başka kayıtlara bağlı; silinip yeniden sınıflandırılamaz."""


def triage_sifirla(session: Session, run_id: uuid.UUID, isteyen: str) -> dict[str, Any]:
    """Koşunun triage çıktılarını (failure + failure_ek + triage_kosu) siler; operatör aracı.

    Kanıt sonradan düzeldiğinde (ör. GitHub koşusunun hata bağlamı 0015 ile geri dolduruldu)
    `classify_run` yeniden çalışabilsin diye. Bir failure bug taslağına, onarım script'ine ya da
    başka bir taslağın `ilgili_failure_ids`'ine bağlıysa hiçbir şey silinmez (reddedilir). Denetim
    kaydı (`triage.reset`) yazılır; önceki `triage.classified` kayıtları append-only olarak kalır.
    """
    from tp_core.models import Script

    ids = list(session.scalars(select(Failure.id).where(Failure.run_id == run_id)))
    if ids:
        bagli = session.scalar(
            select(BugDraft.id).where(BugDraft.failure_id.in_(ids)).limit(1)
        ) or session.scalar(select(Script.id).where(Script.failure_id.in_(ids)).limit(1))
        if bagli is None:
            bagli = session.execute(
                text(
                    "SELECT 1 FROM bug_draft_ek WHERE ilgili_failure_ids ?| CAST(:ids AS text[]) "
                    "LIMIT 1"
                ),
                {"ids": [str(i) for i in ids]},
            ).scalar()
        if bagli is not None:
            raise YenidenTriageReddi(
                "koşunun failure kayıtları bug taslağına / onarım script'ine bağlı; sıfırlanmadı"
            )
        session.execute(Failure.__table__.delete().where(Failure.run_id == run_id))
    session.execute(TriageKosu.__table__.delete().where(TriageKosu.run_id == run_id))
    audit_on_commit(
        session, isteyen, "triage.reset", f"run:{run_id}", {"silinen_failure": len(ids)}
    )
    return {"run_id": str(run_id), "silinen_failure": len(ids)}
