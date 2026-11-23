"""Demo tam sıfırlaması — AI Probe Home'daki "Sıfırla" düğmesi (yalnız Home servis kimliği).

Tek işlem, demo projesini (varsayılan proje: Bayi Portalı) canlı demo senaryosu v2'nin B0
başlangıcına döndürür. Adımlar (sıra güvenlik gereği; `ADIMLAR`):

1. `otomasyon` — Jira tetiği kapalı, durum `To Do`, aralık 30 sn, PO onayı sonrası otomatik
   case kapalı, onay sonrası otomatik kod kapalı. İlk yapılır: tetik açık kalsaydı silmeden
   sonra yeniden planlanan tur TPD-2/TPD-3'ü hemen geri çekerdi.
2. `tp_veri` — YALNIZ bu projenin iş verisi (`proje_verisini_sil`): gereksinim, case, karar
   tablosu, script/kod, koşu, hata, bug taslağı, hata koşusu, PR kaydı, iş kuyruğu… Diğer
   projelere, proje ayarlarına, test verisi kataloğuna, kullanıcılara ve append-only kayıtlara
   (denetim zinciri, model çağrıları, review) dokunulmaz. Kuyruk yarışı: projenin bekleyen
   işleri aynı işlemde iptal edilir; koşan iş varsa beklenir. Silmeden sonra özelliklerin
   açılış kancaları yalnız bu proje için yeniden koşar (kendini yeniden planlayan periyodik
   işler: Jira tetiği, PO sorgusu, CI senkronu…).
3. `jira` — `integrations.jira_demo_sifirla.sifirla` (TPD-1..7 sabit; TPD-8+ silinir ya da
   kapatılır; bağlantılar, etiketler, yorumlar, durumlar).
4. `github` — eski `demo-baseline` koruması (main'de olup etikette olmayan, üretilmiş test
   dışı dosya varsa durur) + mevcut "Demo'yu sıfırla" mantığı (baseline ağacı PR + insan
   kimliğiyle bypass merge, açık `tp/*`/`demo/*` PR'ları kapatılır — dallar silinmez —,
   çalışan demo-app-web yenileme isteği + baseline push CI, denetim `demo.reset`).
5. `dogrulama` — "Demoya hazır" kontrol listesi (salt okuma); çalışan demo-app-web'in main'e
   eşitlenmesi (host izleyicisi `demo-web-sync --watch`) en çok `WEB_BEKLE_ENV` sn beklenir.

İşlem durumu `demo_sifirlama` tablosunda (kurulum geneli; sıfırlanan verinin parçası değil).
İş `demo.tam_sifirla` kurulum işidir (NULL projeli → projenin işleri silinirken kendisi
silinmez) ve uzun şeritte koşar (aynı anda CI/kod üretimi koşmaz). Her adım idempotenttir:
hata sonrası yeniden denemek tüm adımları baştan, güvenle koşar.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, Engine, text

from tp_core.audit import PgAuditLog, append_audit
from tp_core.config import get_settings
from tp_core.proje import proje_icinde, varsayilan_pid
from tp_core.workflow.jobs import JobContext, enqueue, idempotency_lock

log = logging.getLogger(__name__)

TAM_JOB = "demo.tam_sifirla"
ADIMLAR: tuple[str, ...] = ("otomasyon", "tp_veri", "jira", "github", "dogrulama")
AKTOR = "demo-sifirlama"
AUDIT_ISTENDI = "demo.tam_sifirlama.istendi"
AUDIT_TAMAM = "demo.tam_sifirlama.tamam"
AUDIT_HATA = "demo.tam_sifirlama.hata"
BEKLE_ENV = "TP_DEMO_SIFIRLA_IS_BEKLE_S"  # koşan proje işinin bitmesi için (varsayılan 120)
WEB_BEKLE_ENV = "TP_DEMO_SIFIRLA_WEB_BEKLE_S"  # demo-app-web'in main'e eşitlenmesi (varsayılan 600)

# Otomasyon demo değerleri (CANLI-DEMO-SENARYOSU-v2 B0.4 #5, EK-A A.7).
OTOMASYON_HEDEF: dict[str, dict[str, Any]] = {
    "jira_tetik": {"acik": False, "durum": "To Do", "aralik_s": 30, "otomatik_case": False},
    "otomatik_kod_uretimi": {"acik": False},
}

# Proje kapsamlı silinen tablolar (sıra FK gereği). CASCADE'le gidenler de sonda doğrudan
# temizlenir (bağsız kalmış satır olmasın). Hepsinde `tp_app` DELETE yetkisi var (0051).
SILME_SIRASI: tuple[str, ...] = (
    "bug_draft",
    "run",
    "hata_kosusu",
    "script",
    "requirement",
    "test_case",
    "consistency_finding",
    "failure",
    "test_result",
    "triage_kosu",
    "run_aria",
    "step_mapping",
    "script_test_case",
    "script_codegen",
    "script_adim",
    "script_kontrol",
    "requirement_review",
    "requirement_kontrol",
    "requirement_akis",
    "consistency_finding_ek",
    "requirement_review_ek",
    "test_result_ek",
    "failure_ek",
    "bug_draft_ek",
    "ajan_urunu_baglantisi",
    "hata_kosusu_adim",
    "pull_request",
    "external_ref",
    "ci_tetik",
    "workflow_instance",
)
# Silme sonrası sıfır olması gereken tablolar (CASCADE'le gidenler dahil; yetkisiz olanlar da).
BOS_OLMALI: tuple[str, ...] = (
    *SILME_SIRASI,
    "karar_tablosu",
    "metamorfik_iliski",
    "metamorfik_turetme",
    "case_uretim",
    "tasarim_modeli",
    "case_set_review",
    "case_set_audit",
    "case_goruntuleme",
    "case_oracle_kontrol",
    "oracle_istisna",
    "requirement_baz_deger",
    "ajan_testi_talebi",
    "acik_soru",
)
# Önizleme / özet sayımları (kullanıcıya görünen adlar Home'da).
SAYIMLAR: dict[str, str] = {
    "gereksinim": "requirement",
    "test_case": "test_case",
    "script": "script",
    "kosu": "run",
    "hata": "failure",
    "bug_taslagi": "bug_draft",
    "hata_kosusu": "hata_kosusu",
    "pull_request": "pull_request",
}


class TamSifirlamaHatasi(Exception):
    """Adım hatası (kullanıcıya gösterilir; Türkçe)."""


class IstekReddi(Exception):
    def __init__(self, status: int, kod: str, mesaj: str, islem: dict[str, Any] | None = None):
        super().__init__(mesaj)
        self.status = status
        self.kod = kod
        self.mesaj = mesaj
        self.islem = islem


def _simdi() -> datetime:
    return datetime.now(UTC)


def _iso(d: Any) -> str | None:
    return d.isoformat() if isinstance(d, datetime) else (str(d) if d else None)


def _ortam_s(ad: str, varsayilan: float) -> float:
    try:
        return max(float((os.environ.get(ad) or "").strip() or varsayilan), 0.0)
    except ValueError:
        return varsayilan


_fabrikalar: dict[str, Callable[..., Any]] = {}


def set_factories(**kw: Callable[..., Any] | None) -> None:
    """Testler: `jira`, `forge`, `uyku`, `web_izleyici`, `calisan`, `kancalar` değiştirilebilir."""
    _fabrikalar.update({k: v for k, v in kw.items() if v is not None})


def reset_factories() -> None:
    _fabrikalar.clear()


def _uyku(s: float) -> None:
    f = _fabrikalar.get("uyku")
    (f or time.sleep)(s)


# ----------------------------------------------------------------------- işlem kaydı


def _bos_adimlar() -> list[dict[str, Any]]:
    return [
        {"kod": k, "durum": "bekliyor", "ozet": None, "hata": None, "baslangic": None,
         "bitis": None, "ayrinti": None}
        for k in ADIMLAR
    ]  # fmt: skip


def _satir(conn: Connection, islem_id: uuid.UUID) -> Any:
    return conn.execute(
        text(
            "SELECT d.*, j.durum AS job_durum FROM demo_sifirlama d "
            "LEFT JOIN job j ON j.id = d.job_id AND j.project_id IS NULL WHERE d.id = :id"
        ),
        {"id": islem_id},
    ).first()


def _yarim_kaldi_mi(row: Any) -> bool:
    """İşlem 'kuyrukta/çalışıyor' ama işi bitmiş/düşmüş (zaman aşımı, worker yeniden başladı)."""
    if row.durum not in ("kuyrukta", "calisiyor"):
        return False
    return row.job_id is None or row.job_durum in (None, "failed", "cancelled", "done")


YARIM_KALDI = (
    "Sıfırlama işi yarıda kaldı (zaman aşımı ya da sunucu yeniden başladı). Yeniden deneyin; "
    "adımlar güvenle tekrarlanır."
)


def gorunum(row: Any) -> dict[str, Any]:
    adimlar = [dict(a) for a in (row.adimlar or [])]
    durum = row.durum
    hata = row.hata
    if _yarim_kaldi_mi(row):
        durum = "hata"
        hata = hata or YARIM_KALDI
        for a in adimlar:
            if a.get("durum") == "calisiyor":
                a["durum"] = "hata"
                a["hata"] = a.get("hata") or YARIM_KALDI
    return {
        "id": str(row.id),
        "project_id": row.project_id,
        "durum": durum,
        "olusturma": _iso(row.olusturma),
        "bitis": _iso(row.bitis),
        "hata": hata,
        "hazir": bool(row.hazir) and durum == "tamam",
        "adimlar": [
            {k: a.get(k) for k in ("kod", "durum", "ozet", "hata", "baslangic", "bitis")}
            for a in adimlar
        ],
        "kontrol": list(row.kontrol or []),
        "aktor": dict(row.aktor or {}),
    }


def oku(engine: Engine, islem_id: uuid.UUID) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = _satir(conn, islem_id)
    return gorunum(row) if row is not None else None


def son(engine: Engine, project_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        sid = conn.execute(
            text(
                "SELECT id FROM demo_sifirlama WHERE project_id = :pid "
                "ORDER BY olusturma DESC LIMIT 1"
            ),
            {"pid": project_id},
        ).scalar()
        row = _satir(conn, sid) if sid else None
    return gorunum(row) if row is not None else None


def _guncelle(engine: Engine, islem_id: uuid.UUID, **alan: Any) -> None:
    sutunlar = []
    deger: dict[str, Any] = {"id": islem_id}
    for k, v in alan.items():
        if k in ("adimlar", "kontrol", "aktor"):
            sutunlar.append(f"{k} = CAST(:{k} AS jsonb)")
            deger[k] = json.dumps(v, ensure_ascii=False, default=str)
        else:
            sutunlar.append(f"{k} = :{k}")
            deger[k] = v
    sutunlar.append("guncelleme = now()")
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE demo_sifirlama SET {', '.join(sutunlar)} WHERE id = :id"), deger)


# ------------------------------------------------------------------------------ istek


def _proje_kayitli(conn: Connection, pid: str) -> bool:
    return bool(
        conn.execute(
            text("SELECT 1 FROM tp_proje WHERE pid = :pid AND aktif"), {"pid": pid}
        ).first()
    )


def demo_projesi_denetimi(pid: str) -> None:
    """Demo tohumu (TPD-1..7, demo deposu) yalnız varsayılan projeye özgüdür (`jira_seed` ile
    aynı kural); demo kipi kapalıysa demo yazmaları yapılmaz."""
    if not get_settings().demo_mode:
        raise IstekReddi(409, "demo_proje_degil", "Demo kipi kapalı (TP_DEMO_MODE=0)")
    if pid != varsayilan_pid():
        raise IstekReddi(
            409,
            "demo_proje_degil",
            "Bu proje demo verisi taşımıyor: demo sıfırlaması yalnız demo projesinde yapılır",
        )


def istek(engine: Engine, project_id: str, aktor: Mapping[str, Any]) -> dict[str, Any]:
    """İşlemi açar ve işi kuyruğa alır. Ret: `IstekReddi`."""
    from tp_core.features.demo import service

    with engine.begin() as conn:
        if not _proje_kayitli(conn, project_id):
            raise IstekReddi(404, "proje_yok", "Proje bu Testing Probe kurulumunda yok")
        demo_projesi_denetimi(project_id)
        # İstek-denetim yarışı: eşzamanlı istekler aynı kilitte sıralanır (işlem sonuna dek).
        idempotency_lock(conn, "demo:forge", project_id=project_id)  # = service._is_iste
        acik = conn.execute(
            text(
                "SELECT d.*, j.durum AS job_durum FROM demo_sifirlama d "
                "LEFT JOIN job j ON j.id = d.job_id AND j.project_id IS NULL "
                "WHERE d.durum IN ('kuyrukta', 'calisiyor') ORDER BY d.olusturma"
            )
        ).all()
        for row in acik:
            if _yarim_kaldi_mi(row):
                conn.execute(
                    text(
                        "UPDATE demo_sifirlama SET durum = 'hata', hata = COALESCE(hata, :h), "
                        "bitis = now(), guncelleme = now() WHERE id = :id"
                    ),
                    {"id": row.id, "h": YARIM_KALDI},
                )
                continue
            raise IstekReddi(409, "suruyor", "Bir demo sıfırlaması zaten sürüyor", gorunum(row))
        suren = conn.execute(
            text(
                "SELECT tur FROM job WHERE project_id = :pid AND tur IN (:a, :b) "
                "AND durum IN ('queued', 'retry', 'running') LIMIT 1"
            ),
            {"pid": project_id, "a": service.BREAK_JOB, "b": service.RESET_JOB},
        ).scalar()
        if suren:
            raise IstekReddi(
                409,
                "demo_isi_suruyor",
                "Demo kontrollerinden başlatılmış bir kırma/sıfırlama işi sürüyor; bitince "
                "yeniden deneyin",
            )
        temiz = {k: (str(aktor.get(k))[:200] if aktor.get(k) else None)
                 for k in ("uid", "email", "ad")}  # fmt: skip
        islem_id = conn.execute(
            text(
                "INSERT INTO demo_sifirlama (project_id, adimlar, aktor) "
                "VALUES (:pid, CAST(:a AS jsonb), CAST(:k AS jsonb)) RETURNING id"
            ),
            {"pid": project_id, "a": json.dumps(_bos_adimlar()), "k": json.dumps(temiz)},
        ).scalar_one()
        job_id = enqueue(
            conn,
            TAM_JOB,
            {"islem_id": str(islem_id), "project_id": project_id},
            project_id=None,
            max_deneme=1,
        )
        conn.execute(
            text("UPDATE demo_sifirlama SET job_id = :j WHERE id = :id"),
            {"j": job_id, "id": islem_id},
        )
        append_audit(
            conn,
            AKTOR,
            AUDIT_ISTENDI,
            f"proje:{project_id}",
            {"islem_id": str(islem_id), "job_id": str(job_id), "isteyen": temiz},
            project_id=project_id,
        )
        row = _satir(conn, islem_id)
    service.durum_onbellegini_temizle()
    return gorunum(row)


def onizleme(engine: Engine, project_id: str) -> dict[str, Any]:
    from tp_core.integrations.jira import JiraSettings

    with engine.connect() as conn:
        if not _proje_kayitli(conn, project_id):
            raise IstekReddi(404, "proje_yok", "Proje bu Testing Probe kurulumunda yok")
        tp = {ad: _say(conn, tablo, project_id) for ad, tablo in SAYIMLAR.items()}
        tp["is"] = _say(conn, "job", project_id)
        ad = conn.execute(
            text("SELECT ad FROM tp_proje WHERE pid = :pid"), {"pid": project_id}
        ).scalar()
    try:
        proje_kodu = JiraSettings.proje_icin(project_id).jira_project
    except Exception:
        proje_kodu = None
    from tp_core.integrations import jira_demo_sifirla as jds

    proje_kodu = proje_kodu or "TPD"
    return {
        "project_id": project_id,
        "proje_adi": ad,
        "tp": tp,
        "jira": {
            "proje": proje_kodu,
            "tohum": [f"{proje_kodu}-{n}" for n in jds.HEDEF_DURUMLAR],
            "durumlar": {f"{proje_kodu}-{n}": d for n, d in jds.HEDEF_DURUMLAR.items()},
        },
        "github": {"depo": _depo_adi(project_id)},
        "otomasyon": OTOMASYON_HEDEF,
    }


def _depo_adi(pid: str) -> str | None:
    try:
        from tp_core.proje.ayar import ayar

        return (ayar("GITHUB_REPO", pid=pid) or "").strip() or None
    except Exception:
        return None


def _say(conn: Connection, tablo: str, pid: str) -> int:
    return int(
        conn.execute(
            text(f"SELECT count(*) FROM {tablo} WHERE project_id = :pid"), {"pid": pid}
        ).scalar_one()
    )


# --------------------------------------------------------------------------- iş (worker)


def run(ctx: JobContext, engine: Engine) -> dict[str, Any]:
    yuk = dict(ctx.yuk or {})
    islem_id = uuid.UUID(str(yuk["islem_id"]))
    pid = str(yuk["project_id"])
    with engine.connect() as conn:
        row = _satir(conn, islem_id)
    if row is None or row.project_id != pid:
        return {"durum": "atlandi", "neden": "işlem kaydı yok"}
    adimlar = [dict(a) for a in row.adimlar or _bos_adimlar()]
    baslangic = _simdi()
    _guncelle(engine, islem_id, durum="calisiyor", adimlar=adimlar)
    baglam: dict[str, Any] = {"baslangic": baslangic, "pid": pid, "islem_id": islem_id}
    fonksiyonlar: dict[str, Callable[[Engine, dict[str, Any]], tuple[str, Any]]] = {
        "otomasyon": adim_otomasyon,
        "tp_veri": adim_tp_veri,
        "jira": adim_jira,
        "github": adim_github,
        "dogrulama": adim_dogrulama,
    }
    with proje_icinde(pid, kaynak="is"):
        try:
            demo_projesi_denetimi(pid)
        except IstekReddi as exc:
            return _bitir_hata(engine, islem_id, pid, adimlar, adimlar[0], exc.mesaj)
        for adim in adimlar:
            adim.update(durum="calisiyor", baslangic=_iso(_simdi()), hata=None, ozet=None)
            _guncelle(engine, islem_id, adimlar=adimlar)
            try:
                ozet, ayrinti = fonksiyonlar[adim["kod"]](engine, baglam)
            except Exception as exc:
                log.exception("demo tam sıfırlama: %s adımı başarısız", adim["kod"])
                metin = str(exc) if isinstance(exc, TamSifirlamaHatasi) else (
                    f"{type(exc).__name__}: {exc}")  # fmt: skip
                return _bitir_hata(engine, islem_id, pid, adimlar, adim, metin[:1000])
            adim.update(durum="tamam", ozet=ozet, ayrinti=ayrinti, bitis=_iso(_simdi()))
            _guncelle(engine, islem_id, adimlar=adimlar)
    kontrol = baglam.get("kontrol") or []
    hazir = not any(k["durum"] == "hata" for k in kontrol)
    _guncelle(
        engine, islem_id, durum="tamam", hazir=hazir, kontrol=kontrol, bitis=_simdi(),
        adimlar=adimlar,
    )  # fmt: skip
    with engine.begin() as conn:
        append_audit(
            conn, AKTOR, AUDIT_TAMAM, f"proje:{pid}",
            {"islem_id": str(islem_id), "hazir": hazir,
             "adimlar": {a["kod"]: a.get("ozet") for a in adimlar},
             "kontrol": {k["kod"]: k["durum"] for k in kontrol}},
            project_id=pid,
        )  # fmt: skip
    return {"durum": "tamam", "hazir": hazir}


def _bitir_hata(
    engine: Engine,
    islem_id: uuid.UUID,
    pid: str,
    adimlar: list[dict[str, Any]],
    adim: dict[str, Any],
    metin: str,
) -> dict[str, Any]:
    adim.update(durum="hata", hata=metin, bitis=_iso(_simdi()))
    _guncelle(engine, islem_id, durum="hata", hata=metin, adimlar=adimlar, bitis=_simdi())
    with engine.begin() as conn:
        append_audit(
            conn, AKTOR, AUDIT_HATA, f"proje:{pid}",
            {"islem_id": str(islem_id), "adim": adim["kod"], "hata": metin[:500]},
            project_id=pid,
        )  # fmt: skip
    return {"durum": "hata", "adim": adim["kod"], "hata": metin}


# ------------------------------------------------------------------------- 1. otomasyon


def otomasyon_yaz(engine: Engine) -> dict[str, str]:
    """Bağlamdaki projenin otomasyon ayarlarını demo değerlerine yazar (aynıysa yazmaz)."""
    from tp_core.features.otomasyon import ayarlar
    from tp_core.models import session_scope

    out: dict[str, str] = {}
    with session_scope() as s:
        for anahtar, hedef in OTOMASYON_HEDEF.items():
            mevcut = asdict(ayarlar.oku(s, anahtar))
            satir = ayarlar._satir(s, anahtar)
            if (
                satir is not None
                and {**mevcut, **hedef} == mevcut
                and all(k in (satir.deger or {}) for k in hedef)
            ):
                out[anahtar] = "zaten"
                continue
            ayarlar.yaz(s, anahtar, hedef, AKTOR)
            out[anahtar] = "yazildi"
    return out


def otomasyon_dogru_mu(engine: Engine) -> tuple[bool, str]:
    from tp_core.features.otomasyon import ayarlar
    from tp_core.models import session_scope

    with session_scope() as s:
        tetik = asdict(ayarlar.oku(s, "jira_tetik"))
        kod = asdict(ayarlar.oku(s, "otomatik_kod_uretimi"))
    farkli = [
        f"{k}={tetik.get(k)!r}"
        for k, v in OTOMASYON_HEDEF["jira_tetik"].items()
        if tetik.get(k) != v
    ]
    if kod.get("acik") is not False:
        farkli.append(f"otomatik_kod={kod.get('acik')!r}")
    metin = (
        f'Tetik {"açık" if tetik["acik"] else "kapalı"} · "{tetik["durum"]}" · '
        f"{tetik['aralik_s']} sn · otomatik case {'açık' if tetik['otomatik_case'] else 'kapalı'}"
        f" · otomatik kod {'açık' if kod['acik'] else 'kapalı'}"
    )
    return (not farkli, metin if not farkli else f"{metin} (farklı: {', '.join(farkli)})")


def adim_otomasyon(engine: Engine, baglam: dict[str, Any]) -> tuple[str, Any]:
    sonuc = otomasyon_yaz(engine)
    _, metin = otomasyon_dogru_mu(engine)
    return metin, sonuc


# --------------------------------------------------------------------------- 2. TP verisi


def proje_verisini_sil(engine: Engine, pid: str) -> dict[str, Any]:
    """YALNIZ `pid` projesinin iş verisini siler (tek işlem). Koşan proje işi varsa bekler; süre
    dolarsa `TamSifirlamaHatasi`. Dönen: silmeden önceki sayımlar."""
    bitis = time.monotonic() + _ortam_s(BEKLE_ENV, 120)
    while True:
        with engine.begin() as conn:
            # Bekleyen işler iptal: satır kilidi `claim`'in bunları almasını da önler.
            conn.execute(
                text(
                    "UPDATE job SET durum = 'cancelled', guncelleme = now(), bitis = now() "
                    "WHERE project_id = :pid AND durum IN ('queued', 'retry')"
                ),
                {"pid": pid},
            )
            kosan = list(
                conn.execute(
                    text("SELECT tur FROM job WHERE project_id = :pid AND durum = 'running'"),
                    {"pid": pid},
                ).scalars()
            )
            if not kosan:
                once = {ad: _say(conn, tablo, pid) for ad, tablo in SAYIMLAR.items()}
                once["is"] = _say(conn, "job", pid)
                conn.execute(
                    text(
                        "UPDATE script SET failure_id = NULL "
                        "WHERE project_id = :pid AND failure_id IS NOT NULL"
                    ),
                    {"pid": pid},
                )
                for tablo in SILME_SIRASI:
                    conn.execute(text(f"DELETE FROM {tablo} WHERE project_id = :pid"), {"pid": pid})
                conn.execute(
                    text("DELETE FROM otomasyon_ayari WHERE project_id = :pid AND anahtar = :a"),
                    {"pid": pid, "a": "jira_tetik.taban"},
                )
                conn.execute(
                    text("DELETE FROM job WHERE project_id = :pid AND durum <> 'running'"),
                    {"pid": pid},
                )
                kalan = {t: n for t in BOS_OLMALI if (n := _say(conn, t, pid))}
                if kalan:
                    raise TamSifirlamaHatasi(
                        "Proje verisi tam silinemedi (işlem geri alındı): "
                        + ", ".join(f"{t}={n}" for t, n in kalan.items())
                    )
                return once
        if time.monotonic() >= bitis:
            raise TamSifirlamaHatasi(
                "Projede süren iş var (" + ", ".join(sorted(set(kosan))) + "); bitince yeniden "
                "deneyin"
            )
        _uyku(3.0)


def proje_kancalarini_kos(pid: str) -> list[str]:
    """Özelliklerin açılış kancalarını yalnız `pid` için koşar (periyodik işler yeniden planlanır;
    kancalar idempotent). Başarısız kancaların modül adları döner."""
    f = _fabrikalar.get("kancalar")
    if f is not None:
        return list(f(pid))
    from tp_core import worker
    from tp_core.workflow.jobs import discover

    basarisiz: list[str] = []
    for ad in discover():
        kanca = worker._kanca(ad)
        if kanca is None or getattr(kanca, "kurulum", False):
            continue
        if not worker._kancayi_kos(ad, kanca, pid):
            basarisiz.append(ad)
    return basarisiz


def adim_tp_veri(engine: Engine, baglam: dict[str, Any]) -> tuple[str, Any]:
    pid = baglam["pid"]
    once = proje_verisini_sil(engine, pid)
    basarisiz = proje_kancalarini_kos(pid)
    toplam = sum(once.values())
    parca = ", ".join(f"{ad} {n}" for ad, n in once.items() if n)
    ozet = f"Silindi: {parca}" if toplam else "Proje verisi zaten boştu"
    if basarisiz:
        ozet += (
            f" (yeniden planlanamayan: {', '.join(basarisiz)} — worker yeniden başlayınca kurulur)"
        )
    return ozet, {"once": once, "kanca_hatalari": basarisiz}


# --------------------------------------------------------------------------------- 3. Jira


def _jira() -> Any:
    f = _fabrikalar.get("jira")
    if f is not None:
        return f()
    from tp_core.proje import istemciler

    return istemciler.jira()


def _jira_projesi(pid: str) -> str:
    from tp_core.integrations.jira import JiraSettings

    return JiraSettings.proje_icin(pid).jira_project


def adim_jira(engine: Engine, baglam: dict[str, Any]) -> tuple[str, Any]:
    from tp_core.integrations import jira_demo_sifirla as jds

    proje = _jira_projesi(baglam["pid"])
    sonuc = jds.sifirla(_jira(), proje)
    if sonuc.hatalar:
        raise TamSifirlamaHatasi(
            f"Jira ({proje}) kısmen sıfırlandı; hatalar: " + " | ".join(sonuc.hatalar[:8])
        )
    return sonuc.ozet(), sonuc.as_dict()


# ------------------------------------------------------------------------------- 4. GitHub


def _forge() -> Any:
    f = _fabrikalar.get("forge")
    if f is not None:
        return f()
    from tp_core.features.demo import service

    return service._forge()


def uretilen_dizinler() -> frozenset[str]:
    from tp_core.features.codegen import platform

    return frozenset({"tests/generated", *(c.uretilen_alt_yol for c in platform.CATILAR.values())})


def uretilen_mi(yol: str) -> bool:
    """Ürünün kod üretiminin yazdığı test dosyası mı (`<kök>/<üretilen dizin>/...`)?"""
    tam = f"/{yol}"
    return any(f"/{d.strip('/')}/" in tam for d in uretilen_dizinler())


def baseline_korumasi(forge: Any) -> dict[str, Any]:
    """`demo-baseline` etiketi eskiyse (main'de olup etikette olmayan, üretilmiş test dışı dosya
    varsa) sıfırlama main'den gerçek içeriği silerdi → durur (CANLI-DEMO-SENARYOSU-v2 EK-A A.0)."""
    from tp_core.integrations import forge_demo
    from tp_core.integrations.forge import ForgeError

    listele = getattr(forge, "list_files", None)
    if not callable(listele):
        return {"denetim": "atlandi", "neden": "forge dosya listesi sunmuyor"}
    try:
        etiket = set(listele("", forge_demo.BASELINE_TAG))
    except ForgeError as exc:
        raise TamSifirlamaHatasi(
            f"'{forge_demo.BASELINE_TAG}' etiketi okunamadı: {exc}"[:500]
        ) from exc
    main = set(listele("", "main"))
    silinecek = sorted(y for y in main - etiket if not uretilen_mi(y))
    uretilen = sorted(y for y in main - etiket if uretilen_mi(y))
    if silinecek:
        raise TamSifirlamaHatasi(
            f"'{forge_demo.BASELINE_TAG}' etiketi eski görünüyor: main'de olup etikette olmayan "
            f"{len(silinecek)} dosya sıfırlamada silinecekti (ör. {', '.join(silinecek[:5])}). "
            "GitHub sıfırlanmadı; etiketi güncel main'in temizlenmiş sürümüne taşıyın."
        )
    return {"denetim": "gecti", "silinecek_uretilen": len(uretilen)}


def adim_github(engine: Engine, baglam: dict[str, Any]) -> tuple[str, Any]:
    from tp_core.features.demo import service
    from tp_core.integrations import forge_demo
    from tp_core.integrations.forge import BYPASS_ACTOR, ForgeError

    service._canli_degil("demo sıfırlama")
    forge = _forge()
    koruma = baseline_korumasi(forge)
    try:
        sonuc = forge_demo.demo_baseline(
            forge, PgAuditLog(engine), actor=BYPASS_ACTOR, ci=lambda _s, _a: None
        )
    except ForgeError as exc:
        yonerge = "" if service._yerel_forge_mu(forge) else f" {service.GITHUB_INSAN_KIMLIGI_YOK}"
        raise TamSifirlamaHatasi(f"main demo-baseline'a döndürülemedi: {exc}.{yonerge}") from exc
    kapanan = service._prlari_kapat(engine, forge, AKTOR)
    ek = service._web_ve_ci(engine, forge, sonuc.main_after, "baseline", AKTOR)
    service.durum_onbellegini_temizle()
    ozet = {
        "isteyen": AKTOR,
        "bypass_aktoru": BYPASS_ACTOR,
        "kip": "local" if service._yerel_forge_mu(forge) else "github",
        "forge": {
            "pr": sonuc.pr_number,
            "degisti": sonuc.changed,
            "main_once": sonuc.main_before,
            "main_sonra": sonuc.main_after,
            "testid": sonuc.testid,
            "denetim_id": sonuc.audit_id,
        },
        "kapanan_prlar": kapanan,
        "baseline_korumasi": koruma,
        "kaynak": "home-sifirla",
        **ek,
    }
    with engine.begin() as conn:
        append_audit(conn, AKTOR, "demo.reset", "forge:main", ozet)
    baglam["main_sha"] = sonuc.main_after
    hatali = [k for k in kapanan if k.get("hata")]
    if hatali:
        raise TamSifirlamaHatasi(
            "Bazı PR'lar kapatılamadı: " + ", ".join(f"#{k['pr']} ({k['hata']})" for k in hatali)
        )
    metin = (
        f"main demo-baseline'a döndü (PR #{sonuc.pr_number})" if sonuc.changed
        else "main zaten demo-baseline ağacında"
    )  # fmt: skip
    kapali = [k for k in kapanan if not k.get("hata")]
    if kapali:
        metin += f"; {len(kapali)} açık PR kapatıldı (dallar silinmedi)"
    return metin + "; baseline push CI kuyrukta", ozet


# ----------------------------------------------------------------------------- 5. doğrulama


def _k(kod: str, durum: str, ayrinti: str) -> dict[str, str]:
    return {"kod": kod, "durum": durum, "ayrinti": ayrinti}


def _guvenli(kod: str, fn: Callable[[], list[dict[str, str]]]) -> list[dict[str, str]]:
    try:
        return fn()
    except Exception as exc:  # tek kontrolün hatası listeyi düşürmesin
        log.exception("demo tam sıfırlama: %s kontrolü okunamadı", kod)
        return [_k(kod, "hata", f"Okunamadı: {type(exc).__name__}: {exc}"[:300])]


def kontrol_tp_bos(engine: Engine, pid: str, baslangic: datetime) -> list[dict[str, str]]:
    with engine.connect() as conn:
        dolu = {
            ad: n for ad, tablo in SAYIMLAR.items()
            if ad not in ("kosu", "pull_request", "hata")
            and (n := _say(conn, tablo, pid))
        }  # fmt: skip
        eski_kosu = conn.execute(
            text("SELECT count(*) FROM run WHERE project_id = :pid AND olusturma < :t"),
            {"pid": pid, "t": baslangic},
        ).scalar_one()
        basarisiz_is = conn.execute(
            text("SELECT count(*) FROM job WHERE project_id = :pid AND durum = 'failed' "
                 "AND olusturma < :t"),
            {"pid": pid, "t": baslangic},
        ).scalar_one()  # fmt: skip
    if eski_kosu:
        dolu["eski koşu"] = int(eski_kosu)
    if basarisiz_is:
        dolu["başarısız iş"] = int(basarisiz_is)
    if dolu:
        return [_k("tp_bos", "hata", "Kalan: " + ", ".join(f"{k} {v}" for k, v in dolu.items()))]
    return [_k("tp_bos", "tamam", "Gereksinim, case, script, bug taslağı, hata koşusu yok; "
               "eski koşu ve başarısız iş yok")]  # fmt: skip


def kontrol_otomasyon(engine: Engine) -> list[dict[str, str]]:
    ok, metin = otomasyon_dogru_mu(engine)
    return [_k("otomasyon", "tamam" if ok else "hata", metin)]


def kontrol_jira(pid: str) -> list[dict[str, str]]:
    from tp_core.integrations import jira_demo_sifirla as jds

    return jds.dogrula(_jira(), _jira_projesi(pid))


def kontrol_jira_po(pid: str) -> list[dict[str, str]]:
    from tp_core.integrations import proje_ortami
    from tp_core.integrations.jira import JiraSettings, oauth_kipi, oauth_sahibi

    ayar = JiraSettings.proje_icin(pid)
    po = {a.strip().lower() for a in ayar.jira_po_account_ids.split(",") if a.strip()}
    if oauth_kipi(pid):
        yazan = {oauth_sahibi(pid).lower()} - {""}
        ad = str(proje_ortami.baglanti_public("jira", pid).get("account_name") or "").strip()
    else:
        yazan = {i.lower() for i in _jira().write_identities()}
        ad = ""
    kim = ad or ", ".join(sorted(yazan)) or "bilinmiyor"
    if not po:
        return [_k("jira_po", "hata", "PO onaycıları listesi boş: PO onayı sayılmaz (Home › proje "
                   "› Testing Probe ayarları › Jira › PO onaycıları)")]  # fmt: skip
    if "*" in po:
        return [_k("jira_po", "uyari", "PO onaycıları '*' (test kipi); demo için gerçek PO "
                   "hesabını yazın")]  # fmt: skip
    if not yazan:
        return [_k("jira_po", "uyari", "Jira bağlantısını yetkilendiren hesap bilinmiyor (Home › "
                   "Bağlantılar › Jira › Yeniden test et)")]  # fmt: skip
    if yazan & po:
        return [_k("jira_po", "hata", f"Jira bağlantısını yetkilendiren hesap ({kim}) PO "
                   "onaycıları listesinde: görev ayrılığı gereği PO onayı sayılmaz. Bağlantıyı "
                   "entegrasyon (bot) hesabıyla yeniden yetkilendirin")]  # fmt: skip
    return [_k("jira_po", "tamam", f"Yetkilendiren hesap ({kim}) PO onaycısı değil; "
               f"{len(po)} PO onaycısı tanımlı")]  # fmt: skip


def kontrol_github(engine: Engine) -> list[dict[str, str]]:
    from tp_core.features.demo import service
    from tp_core.integrations import forge_demo
    from tp_core.integrations.forge import ForgeError

    forge = _forge()
    out: list[dict[str, str]] = []
    try:
        main = forge.head_sha("main")
        baseline = forge.head_sha(forge_demo.BASELINE_TAG)
        ayni = forge_demo.main_is_baseline(forge, main, baseline)
        out.append(_k("github_main", "tamam" if ayni else "hata",
                      f"main {main[:12]} {'=' if ayni else '≠'} demo-baseline "
                      f"{(baseline or '')[:12]} (ağaç)"))  # fmt: skip
    except ForgeError as exc:
        out.append(_k("github_main", "hata", f"Okunamadı: {exc}"[:300]))
    try:
        acik = [
            p for p in forge.list_prs("open")
            if p.branch.startswith(service.KAPATILACAK_ONEKLER)
            and not p.branch.startswith(service.KORUNAN_ONEKLER)
        ]  # fmt: skip
        out.append(
            _k("github_pr", "hata", "Açık PR: " + ", ".join(f"#{p.number} {p.branch}"
                                                             for p in acik))
            if acik else _k("github_pr", "tamam", "Açık tp/* ya da demo/* PR yok")
        )  # fmt: skip
    except (ForgeError, AttributeError) as exc:
        out.append(_k("github_pr", "hata", f"Okunamadı: {exc}"[:300]))
    return out


def _izleyici() -> dict[str, Any]:
    f = _fabrikalar.get("web_izleyici")
    if f is not None:
        return dict(f())
    from tp_core.features.demo import web

    return web.izleyici_durumu()


def _calisan() -> Any:
    f = _fabrikalar.get("calisan")
    if f is not None:
        return f()
    from tp_core.features.demo import web

    return web.calisan_uygulama()


def kontrol_web(engine: Engine, main_sha: str | None) -> list[dict[str, str]]:
    """Host izleyicisi (`demo-web-sync --watch`) çalışıyor mu ve çalışan demo-app-web main'i
    yansıtıyor mu? İzleyici canlıysa eşitlenmesi en çok `WEB_BEKLE_ENV` sn beklenir."""
    from tp_core.features.demo import web

    out: list[dict[str, str]] = []
    iz = _izleyici()
    canli = bool(iz.get("calisiyor"))
    out.append(_k("web_izleyici", "tamam" if canli else "hata", str(iz.get("ayrinti") or "")))
    if not main_sha:
        out.append(_k("uygulama_main", "hata", "main sha bilinmiyor"))
        return out
    forge = _forge()
    bitis = time.monotonic() + (_ortam_s(WEB_BEKLE_ENV, 600) if canli else 0)
    while True:
        calisan = _calisan()
        eslesiyor, neden = web.uygulama_eslesiyor(forge, main_sha, calisan.sha)
        if eslesiyor or time.monotonic() >= bitis:
            break
        _uyku(5.0)
    sha = (calisan.sha or "?")[:12]
    if eslesiyor:
        out.append(_k("uygulama_main", "tamam", f"Çalışan demo uygulaması ({sha}) main "
                      f"{main_sha[:12]} ile eşleşiyor"))  # fmt: skip
    else:
        out.append(_k("uygulama_main", "hata", f"Çalışan demo uygulaması ({sha}) main "
                      f"{main_sha[:12]} ile eşleşmiyor: {neden}"))  # fmt: skip
    return out


def kontrol_ci(engine: Engine, pid: str, baslangic: datetime) -> list[dict[str, str]]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT sonuc FROM run WHERE project_id = :pid AND tetik = 'push' "
                "AND olusturma >= :t ORDER BY olusturma DESC LIMIT 1"
            ),
            {"pid": pid, "t": baslangic},
        ).first()
    if row is None:
        return [_k("ci_baseline", "uyari", "Baseline push CI koşusu bulunamadı")]
    return [_k("ci_baseline", "bilgi", f"Baseline push CI: {row.sonuc}"
               + " — yeşil olunca 'kırma ön koşulu' sağlanır (≈16–20 dk)")]  # fmt: skip


STRICT_ACIK = "AÇIK (sahnede kapalı beklenir; tp-env TP_REPLAY_STRICT)"


def kontrol_replay() -> list[dict[str, str]]:
    from tp_core.features.demo import service

    m = service.model_durumu_hesapla()
    strict = bool(m.get("replay_strict"))
    return [_k("replay_strict", "uyari" if strict else "bilgi",
               f"Model kipi {str(m.get('mod') or '?').upper()}; REPLAY strict "
               f"{STRICT_ACIK if strict else 'kapalı'}")]  # fmt: skip


def adim_dogrulama(engine: Engine, baglam: dict[str, Any]) -> tuple[str, Any]:
    pid = baglam["pid"]
    bas = baglam["baslangic"]
    kontrol: list[dict[str, str]] = []
    kontrol += _guvenli("tp_bos", lambda: kontrol_tp_bos(engine, pid, bas))
    kontrol += _guvenli("otomasyon", lambda: kontrol_otomasyon(engine))
    kontrol += _guvenli("jira_durumlar", lambda: kontrol_jira(pid))
    kontrol += _guvenli("jira_po", lambda: kontrol_jira_po(pid))
    kontrol += _guvenli("github_main", lambda: kontrol_github(engine))
    kontrol += _guvenli("web_izleyici", lambda: kontrol_web(engine, baglam.get("main_sha")))
    kontrol += _guvenli("ci_baseline", lambda: kontrol_ci(engine, pid, bas))
    kontrol += _guvenli("replay_strict", kontrol_replay)
    baglam["kontrol"] = kontrol
    hata = [k["kod"] for k in kontrol if k["durum"] == "hata"]
    uyari = [k["kod"] for k in kontrol if k["durum"] == "uyari"]
    if hata:
        return f"Demoya hazır DEĞİL: {len(hata)} kontrol başarısız ({', '.join(hata)})", None
    return ("Demoya hazır" + (f" ({len(uyari)} uyarı)" if uyari else "")), None
