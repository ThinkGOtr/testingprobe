"""Kontrol Kulesi "Case kalitesi" bölümü (specs/011 K21, §4.3, §4.9). AI yok; her sayı DB'den.

`GET /control-tower/case-quality[?requirement_id=<uuid>]`: verilirse yalnız o gereksinim, yoksa
proje geneli (case'i ya da kalite kaydı olan tüm gereksinimler). Ölçülmeyen değer uydurulmaz
(`null`); boş DB'de tüm sayılar 0 / `null`.

- **kapsam:** gereksinim başına `cases.service._coverage_state` (case-summary ile aynı hesap) →
  `oranlar` (`gereksinim_kapsami`, `oge_kapsami`, `negatif_karar_kapsami`; her biri
  `{kapsanan, toplam, oran}`). Proje geneli pay/payda toplamıdır (gereksinim ortalaması değil);
  pay/payda yoksa gereksinim ortalaması alınır ve `kaynaklar.kapsam`'da yazılır. Yalnız v3 case'i
  olan gereksinimler girer. Hazır kapsam: `oranlar`'da adı `hazir` içeren anahtar varsa o, yoksa
  matris satırlarındaki `covered_by_ready`; ikisi de yoksa `null`.
- **review (P8):** gereksinim başına en güncel tamamlanmış `case_set_review`. Skor 0–12 (UYGUN
  madde sayısı); dağılım ve ortalama yüzde ölçeğindedir (skor / 12 × 100).
- **denetim (P9):** gereksinim başına BAĞLAYICI karar (`denetim_akisi.binding_decision`: güncel set
  hash'inin tamamlanmış denetimlerinden en serti; kapının okuduğu karar). Güncel set için karar
  yoksa en güncel tamamlanmış kayıt sayılır ve `bayat`'a girer. `kod` = `karar` (deterministik
  sertleştirme sonrası), `model` = aynı kaydın `model_karari`. `hata` / `bekliyor`: en güncel kaydı
  o durumda olan gereksinim sayısı.
- **tekrar:** sayılan review'lardaki `remove_or_merge` önerileri / değerlendirilen case sayısı
  (`icerik.case_haritasi`).
- **readiness / teknik:** güncel case'ler (superseded/rejected ve eski PO içeriğine ait olmayan).
- **icerik_kontrolu:** `asistan_denetim` karar dağılımı; asistan gereksinime bağlı değildir, filtre
  verilse de proje genelidir.
- **surumler:** `case_uretim.ai_call_id → ai_call.surum` (paket@sürüm) kırılımı; REPLAY dahil.
- **hedefler:** Prompt Seti v2 belgesindeki başlangıç hedefleri ekip hedefidir, standart değildir;
  eşik/kapı uygulanmaz. Belge repoda değil (`.docs/`), repoda sayısal hedef bulunmadığı için boş.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from tp_core.features.cases import denetim_akisi
from tp_core.features.cases import ozet as ozet_modulu
from tp_core.features.cases import review as review_mod
from tp_core.features.cases import service as cases_service
from tp_core.features.cases.schema import READINESS, is_legacy, readiness_of
from tp_core.models import (
    AiCall,
    CaseSetAudit,
    CaseSetReview,
    CaseUretim,
    Requirement,
    TestCase,
)

REVIEW_MADDE: Final = 12
DAGILIM: Final = (("0–49", 0, 50), ("50–69", 50, 70), ("70–84", 70, 85), ("85–100", 85, 101))
# Denetim kararlarının DB yazımı (models.case_kalite.DENETIM_KARARLARI) → yanıttaki ASCII anahtar.
KARAR_ANAHTARI: Final = {
    "KABUL": "KABUL",
    "DÜZELTME_GEREKLİ": "DUZELTME_GEREKLI",
    "ENGELLE": "ENGELLE",
}
ICERIK_KARARLARI: Final = ("gec", "uyar", "engelle")
# `oranlar` anahtarı → yanıt alanı.
KAPSAM_ANAHTARLARI: Final = {
    "gereksinim": "gereksinim_kapsami",
    "oge": "oge_kapsami",
    "negatif_karar": "negatif_karar_kapsami",
}
HEDEF_NOTU: Final = "ekip hedefi, standart değil"
# Prompt Seti v2 başlangıç hedefleri: belge repoya girmez (.docs/); repoda (specs/, docs/) sayısal
# hedef yok. Belgeden aynen alınırsa buraya eklenir: {"ad", "metrik", "hedef"}.
HEDEFLER: Final[tuple[Mapping[str, str], ...]] = ()
IDE_SURUM: Final = "ide-taslak"
BILINMEYEN_SURUM: Final = "bilinmiyor"

KAYNAKLAR: Final = {
    "kapsam": (
        "cases.service._coverage_state → oranlar {gereksinim_kapsami, oge_kapsami, "
        "negatif_karar_kapsami}: güncel case'ler (superseded/rejected ve eski PO içeriğine ait "
        "olmayan) × güncel üretim özetleri; yalnız v3 case'i olan gereksinimler; proje geneli = "
        "kapsanan/toplam toplamı (pay/payda yoksa gereksinim ortalaması, `kapsam_yontemi`)"
    ),
    "hazir_kapsam": (
        "oranlar içinde adı 'hazir' geçen anahtar; yoksa kapsam matrisi satırlarının "
        "covered_by_ready alanı (AC satırları → hazir_gereksinim, öğe satırları → hazir_oge); "
        "ikisi de yoksa null"
    ),
    "review": (
        "case_set_review durum='tamamlandi', gereksinim başına en güncel (olusturma) kayıt; skor "
        "0–12 (UYGUN madde), yüzde = skor/12×100; dağılım ve ortalama yüzde; ortalama_skor 0–12; "
        "bayat = kaydın set_hash'i güncel setinkinden farklı"
    ),
    "denetim": (
        "case_set_audit, gereksinim başına bağlayıcı karar (denetim_akisi.binding_decision: "
        "güncel set hash'inin tamamlanmış denetimlerinden en serti); güncel set için karar yoksa "
        "en güncel tamamlanmış kayıt (bayat): kod = karar (deterministik sertleştirme "
        "sonrası), model = aynı kaydın model_karari; 'DÜZELTME_GEREKLİ' → DUZELTME_GEREKLI; "
        "hata/bekliyor = en güncel kaydı o durumda olan gereksinim sayısı"
    ),
    "tekrar": (
        "sayılan review'ların icerik.remove_or_merge öneri sayısı / icerik.case_haritasi case "
        "sayısı; etkilenen_case = önerilerdeki ayrık case_refs"
    ),
    "readiness": (
        "güncel case'ler: icerik.readiness (ready/assumption_dependent/blocked); legacy = "
        "readiness anahtarı olmayan eski (v2) case (cases.schema.is_legacy)"
    ),
    "teknik": "güncel case'lerin icerik.technique listesi (bir case birden çok tekniğe sayılır)",
    "icerik_kontrolu": (
        "asistan_denetim.karar (gec/uyar/engelle), soru ve cevap puanları ayrı satır; oranlar "
        "satır sayısına göre; proje geneli (asistan gereksinime bağlı değil); saklama temizliği "
        "asistan_mesaj'ı silerse satırlar da gider (CASCADE)"
    ),
    "surumler": (
        "case_uretim.ai_call_id → ai_call.surum (paket@sürüm); model çağrısı olmayan IDE taslağı "
        f"'{IDE_SURUM}', bulunamayan '{BILINMEYEN_SURUM}'; REPLAY dahil; case = o üretimin "
        "(requirement_id, uretim_no) tüm case'leri; review = sayılan review'un uretim_no'su "
        "(yoksa gereksinimin son üretimi); denetim = bağlı review'un uretim_no'su (yoksa "
        "gereksinimin son üretimi) — yaklaşık bağlama: set birden çok üretimin case'ini "
        "içerebilir, sonuç tek üretime yazılır"
    ),
    "hedefler": (
        "Prompt Seti v2 başlangıç hedefleri (specs/011 §4.9): ekip hedefi, standart değil; eşik "
        "ya da kapı uygulanmaz"
    ),
}


# --------------------------------------------------------------------------- yardımcılar


def _oran(pay: float, payda: float, basamak: int = 4) -> float | None:
    return round(pay / payda, basamak) if payda else None


def _yuzde(skor: int | None) -> float | None:
    return None if skor is None else round(skor / REVIEW_MADDE * 100, 1)


def _ortalama(degerler: Sequence[float], basamak: int = 1) -> float | None:
    return round(sum(degerler) / len(degerler), basamak) if degerler else None


class _Toplayici:
    """Oranları toplar: pay/payda varsa toplam, yalnız oran varsa gereksinim ortalaması."""

    def __init__(self) -> None:
        self.kapsanan = 0
        self.toplam = 0
        self.oranlar: list[float] = []
        self.payda_yok = False
        self.veri = False

    def ekle(self, deger: Any) -> None:
        if isinstance(deger, Mapping):
            k, t = deger.get("kapsanan"), deger.get("toplam")
            if isinstance(k, int) and isinstance(t, int):
                self.veri = True
                self.kapsanan += k
                self.toplam += t
                return
            deger = deger.get("oran")
        if isinstance(deger, int | float) and not isinstance(deger, bool):
            self.veri = True
            self.payda_yok = True
            self.oranlar.append(float(deger))

    def sonuc(self) -> float | None:
        if not self.veri:
            return None
        if self.payda_yok:
            return _ortalama(self.oranlar, 4)
        return _oran(self.kapsanan, self.toplam)


def _hazir_oranlari(oranlar: Mapping[str, Any], matris: Sequence[Mapping[str, Any]]) -> dict:
    """`{"hazir_gereksinim": değer, "hazir_oge": değer}` (yoksa anahtar hiç yok)."""
    out: dict[str, Any] = {}
    for anahtar, deger in oranlar.items():
        ad = str(anahtar).lower()
        if "hazir" not in ad:
            continue
        if "oge" in ad:
            out.setdefault("hazir_oge", deger)
        elif "gereksinim" in ad or "ac" in ad.split("_"):
            out.setdefault("hazir_gereksinim", deger)
    if out:
        return out
    if not any("covered_by_ready" in s for s in matris):
        return {}
    for alan, tur in (("hazir_gereksinim", "ac"), ("hazir_oge", "oge")):
        satirlar = [s for s in matris if s.get("tur") == tur]
        out[alan] = {
            "kapsanan": sum(bool(s.get("covered_by_ready")) for s in satirlar),
            "toplam": len(satirlar),
        }
    return out


def _en_guncel(satirlar: Iterable[Any]) -> dict[uuid.UUID, Any]:
    """Gereksinim başına en güncel satır (olusturma, id azalan sıralı girdiden ilk)."""
    out: dict[uuid.UUID, Any] = {}
    for s in satirlar:
        out.setdefault(s.requirement_id, s)
    return out


def _surum_etiketi(surum: str | None, kanal: str | None) -> str:
    if surum:
        return surum
    return IDE_SURUM if kanal == "ide" else BILINMEYEN_SURUM


def _tekrar_sayilari(icerik: Mapping[str, Any] | None) -> tuple[int, int, int]:
    """(öneri, değerlendirilen case, etkilenen ayrık case) — review içeriğinden."""
    icerik = icerik or {}
    oneriler = [r for r in icerik.get("remove_or_merge") or [] if isinstance(r, Mapping)]
    etkilenen = {int(n) for r in oneriler for n in r.get("case_refs") or [] if str(n).isdigit()}
    harita = icerik.get("case_haritasi")
    return len(oneriler), len(harita) if isinstance(harita, Mapping) else 0, len(etkilenen)


# --------------------------------------------------------------------------- ana hesap


def case_kalitesi(session: Session, requirement_id: uuid.UUID | None = None) -> dict[str, Any]:
    uyarilar: list[str] = []
    if requirement_id is not None:
        reqs = [cases_service.get_requirement(session, requirement_id)]
    else:
        reqs = list(
            session.scalars(
                select(Requirement)
                .where(Requirement.id.in_(select(TestCase.requirement_id).distinct()))
                .order_by(Requirement.olusturma, Requirement.id)
            ).all()
        )

    def _filtre(q: Any, kolon: Any) -> Any:
        return q if requirement_id is None else q.where(kolon == requirement_id)

    # ---- kapsam / readiness / teknik (gereksinim başına _coverage_state)
    kapsam = {alan: _Toplayici() for alan in (*KAPSAM_ANAHTARLARI, "hazir_gereksinim", "hazir_oge")}
    n_gereksinim = 0
    readiness = {**dict.fromkeys(READINESS, 0), "legacy": 0}
    teknik: dict[str, int] = defaultdict(int)
    guncel_hash: dict[uuid.UUID, str | None] = {}
    hazir_veri = False
    for req in reqs:
        durum = cases_service._coverage_state(session, req)
        # Güncel küme D1'in tek tanımından (`ozet.current_cases`, eski case dahil).
        guncel = ozet_modulu.current_cases(session, req, include_legacy=True)
        for tc in guncel:
            if is_legacy(tc.icerik):
                readiness["legacy"] += 1
            else:
                r = readiness_of(tc.icerik)
                readiness[r] = readiness.get(r, 0) + 1
        for t, n in (durum.get("teknik_dagilimi") or {}).items():
            teknik[str(t)] += int(n)
        guncel_hash[req.id] = review_mod.set_hash(session, req)
        if not any(not is_legacy(tc.icerik) for tc in guncel):
            continue
        n_gereksinim += 1
        oranlar = durum.get("oranlar") or {}
        for alan, anahtar in KAPSAM_ANAHTARLARI.items():
            kapsam[alan].ekle(oranlar.get(anahtar))
        hazir = _hazir_oranlari(oranlar, durum.get("matris") or [])
        hazir_veri = hazir_veri or bool(hazir)
        for alan, deger in hazir.items():
            kapsam[alan].ekle(deger)
    kapsam_cikti: dict[str, Any] = {alan: t.sonuc() for alan, t in kapsam.items()}
    kapsam_cikti["n_gereksinim"] = n_gereksinim
    kapsam_cikti["kapsam_yontemi"] = (
        "gereksinim_ortalamasi" if any(t.payda_yok for t in kapsam.values()) else "toplam"
    )
    if n_gereksinim and not hazir_veri:
        uyarilar.append(
            "Hazır kapsam ölçülmüyor: kapsam matrisinde hazır case bilgisi (covered_by_ready) yok."
        )

    # ---- uretimler → sürüm
    uretim_satirlari = session.execute(
        _filtre(
            select(
                CaseUretim.requirement_id,
                CaseUretim.uretim_no,
                CaseUretim.kanal,
                AiCall.surum,
            )
            .outerjoin(AiCall, AiCall.id == CaseUretim.ai_call_id)
            .order_by(CaseUretim.requirement_id, CaseUretim.uretim_no),
            CaseUretim.requirement_id,
        )
    ).all()
    uretim_surumu: dict[tuple[uuid.UUID, int], str] = {}
    son_uretim: dict[uuid.UUID, int] = {}
    for rid, no, kanal, surum in uretim_satirlari:
        uretim_surumu[(rid, no)] = _surum_etiketi(surum, kanal)
        son_uretim[rid] = max(son_uretim.get(rid, no), no)
    case_sayisi: dict[tuple[uuid.UUID, int], int] = {
        (rid, no): int(n)
        for rid, no, n in session.execute(
            _filtre(
                select(TestCase.requirement_id, TestCase.uretim_no, func.count()).group_by(
                    TestCase.requirement_id, TestCase.uretim_no
                ),
                TestCase.requirement_id,
            )
        ).all()
    }

    def _surum_of(rid: uuid.UUID, uretim_no: int | None) -> str | None:
        if uretim_no is not None and (rid, uretim_no) in uretim_surumu:
            return uretim_surumu[(rid, uretim_no)]
        son = son_uretim.get(rid)
        return uretim_surumu.get((rid, son)) if son is not None else None

    surum_ozet: dict[str, dict[str, Any]] = {}

    def _surum(ad: str) -> dict[str, Any]:
        return surum_ozet.setdefault(
            ad,
            {
                "surum": ad,
                "uretim": 0,
                "case": 0,
                "_skorlar": [],
                "kabul": 0,
                "duzeltme": 0,
                "engel": 0,
                "_oneri": 0,
                "_case": 0,
            },
        )

    for (rid, no), ad in uretim_surumu.items():
        s = _surum(ad)
        s["uretim"] += 1
        s["case"] += case_sayisi.get((rid, no), 0)

    # ---- review (P8)
    reviewlar = _en_guncel(
        session.scalars(
            _filtre(
                select(CaseSetReview)
                .where(CaseSetReview.durum == "tamamlandi")
                .order_by(CaseSetReview.olusturma.desc(), CaseSetReview.id.desc()),
                CaseSetReview.requirement_id,
            )
        ).all()
    )
    yuzdeler: list[float] = []
    skorlar: list[float] = []
    dagilim = {etiket: 0 for etiket, _, _ in DAGILIM}
    bayat = 0
    tekrar = {"oneri": 0, "case": 0, "etkilenen_case": 0}
    for rid, satir in reviewlar.items():
        if satir.set_hash != guncel_hash.get(rid):
            bayat += 1
        oneri, deg_case, etkilenen = _tekrar_sayilari(satir.icerik)
        tekrar["oneri"] += oneri
        tekrar["case"] += deg_case
        tekrar["etkilenen_case"] += etkilenen
        yuzde = _yuzde(satir.skor)
        ad = _surum_of(rid, satir.uretim_no)
        if ad is not None:
            s = _surum(ad)
            s["_oneri"] += oneri
            s["_case"] += deg_case
            if yuzde is not None:
                s["_skorlar"].append(yuzde)
        if yuzde is None:
            continue
        yuzdeler.append(yuzde)
        skorlar.append(float(satir.skor))
        for etiket, alt, ust in DAGILIM:
            if alt <= yuzde < ust:
                dagilim[etiket] += 1
                break
    review_cikti = {
        "n": len(yuzdeler),
        "ortalama": _ortalama(yuzdeler),
        "ortalama_skor": _ortalama(skorlar, 2),
        "olcek": f"yüzde = skor / {REVIEW_MADDE} × 100",
        "bayat": bayat,
        "dagilim": [{"aralik": etiket, "n": dagilim[etiket]} for etiket, _, _ in DAGILIM],
    }
    tekrar_cikti = {**tekrar, "oran": _oran(tekrar["oneri"], tekrar["case"])}

    # ---- denetim (P9)
    denetimler = session.scalars(
        _filtre(
            select(CaseSetAudit).order_by(CaseSetAudit.olusturma.desc(), CaseSetAudit.id.desc()),
            CaseSetAudit.requirement_id,
        )
    ).all()
    en_son = _en_guncel(denetimler)
    tamamlanan = _en_guncel(d for d in denetimler if d.durum == "tamamlandi")
    review_uretim = dict(
        session.execute(
            select(CaseSetReview.id, CaseSetReview.uretim_no).where(
                CaseSetReview.id.in_(
                    {d.review_id for d in denetimler if d.durum == "tamamlandi" and d.review_id}
                )
            )
        ).all()
    )
    sifir = dict.fromkeys(KARAR_ANAHTARI.values(), 0)
    kod, model = dict(sifir), dict(sifir)
    denetim_bayat = 0
    for rid, son_tamam in tamamlanan.items():
        hash_ = guncel_hash.get(rid)
        baglayici = denetim_akisi.binding_decision(session, rid, hash_) if hash_ else None
        if baglayici is None:
            denetim_bayat += 1
        d = baglayici or son_tamam
        if d.karar in KARAR_ANAHTARI:
            kod[KARAR_ANAHTARI[d.karar]] += 1
        if d.model_karari in KARAR_ANAHTARI:
            model[KARAR_ANAHTARI[d.model_karari]] += 1
        ad = _surum_of(rid, review_uretim.get(d.review_id))
        if ad is not None and d.karar in KARAR_ANAHTARI:
            alan = {"KABUL": "kabul", "DUZELTME_GEREKLI": "duzeltme", "ENGELLE": "engel"}
            _surum(ad)[alan[KARAR_ANAHTARI[d.karar]]] += 1
    denetim_cikti = {
        "n": len(tamamlanan),
        "kod": kod,
        "model": model,
        "hata": sum(d.durum == "hata" for d in en_son.values()),
        "bekliyor": sum(d.durum == "bekliyor" for d in en_son.values()),
        "bayat": denetim_bayat,
    }

    # ---- içerik kontrolü (asistan denetimi; proje geneli)
    icerik = dict.fromkeys(ICERIK_KARARLARI, 0)
    yon: dict[str, int] = defaultdict(int)
    for karar, y, n in session.execute(
        text("SELECT karar, yon, count(*) FROM asistan_denetim GROUP BY karar, yon")
    ).all():
        if karar in icerik:
            icerik[karar] += int(n)
        yon[str(y)] += int(n)
    n_icerik = sum(yon.values())
    icerik_cikti = {
        "n": n_icerik,
        **icerik,
        "engel_orani": _oran(icerik["engelle"], n_icerik),
        "uyari_orani": _oran(icerik["uyar"], n_icerik),
        "yon": dict(sorted(yon.items())),
    }
    if requirement_id is not None:
        uyarilar.append(
            "İçerik kontrolü (asistan denetimi) gereksinime bağlı değildir; proje geneli "
            "gösterilir."
        )

    # ---- sürümler
    surumler = []
    for ad in sorted(surum_ozet):
        s = surum_ozet[ad]
        surumler.append(
            {
                "surum": ad,
                "uretim": s["uretim"],
                "case": s["case"],
                "review_ortalama": _ortalama(s["_skorlar"]),
                "review_n": len(s["_skorlar"]),
                "kabul": s["kabul"],
                "duzeltme": s["duzeltme"],
                "engel": s["engel"],
                "tekrar_orani": _oran(s["_oneri"], s["_case"]),
            }
        )

    # ---- hedefler
    hedefler = [{**h, "not": HEDEF_NOTU} for h in HEDEFLER]
    if not hedefler:
        uyarilar.append(
            "Prompt Seti v2 başlangıç hedefleri repoda bulunamadı (belge repoya girmez); hedef "
            "gösterilmiyor."
        )
    if readiness["legacy"]:
        uyarilar.append(
            f"{readiness['legacy']} eski (v2) case readiness taşımıyor (K9); review/denetim setine "
            "girmez."
        )

    return {
        "requirement_id": str(requirement_id) if requirement_id else None,
        "kapsam": kapsam_cikti,
        "review": review_cikti,
        "denetim": denetim_cikti,
        "tekrar": tekrar_cikti,
        "readiness": readiness,
        "teknik": dict(sorted(teknik.items())),
        "icerik_kontrolu": icerik_cikti,
        "surumler": surumler,
        "hedefler": hedefler,
        "kaynaklar": dict(KAYNAKLAR),
        "uyarilar": uyarilar,
    }
