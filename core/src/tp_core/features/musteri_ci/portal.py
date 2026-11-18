"""Portal (Ş7) alan şekilleri: script yanıtındaki `musteri_ci`, `kurulum`, `hat` ve merge kabulü.

Ş7 portalı şu şekilleri bekler (aip-review/test-dilleri/s7.md); bu modül Ş5 iç modelini o
şekle çevirir (saf; DB/ağ yok). Serileştirmeyi yapan (script yanıtı, `/code/languages`) bu
fonksiyonları çağırır:

    script.hat         = hat_adi(platform, dil)                     # "musteri_ci" | None
    script.musteri_ci  = portal_musteri_ci(guncelleme, head_sha)    # HatGuncellemesi → portal
    script.kurulum     = portal_kurulum(plan, pr)                   # KurulumPlani / PR → portal
    merge yanıtı       merge_kabul_gerekli = merge_kabul_gerekli(p, d)  # müşteri CI'da []
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tp_core.features.musteri_ci.akis import HatGuncellemesi
from tp_core.features.musteri_ci.durum import ETIKETLER, HatDurumu
from tp_core.features.musteri_ci.kurulum import KurulumPlani
from tp_core.features.musteri_ci.sozlesme import HAT, musteri_ci_mi

D = HatDurumu
# İç durum → portal `durum` (bekliyor|kosuyor|gecti|kaldi|derleme_hatasi).
PORTAL_DURUMU: dict[HatDurumu, str] = {
    D.KURULUM_GEREKLI: "bekliyor",
    D.URETILDI: "bekliyor",
    D.PR_ACILDI: "bekliyor",
    D.CI_BEKLENIYOR: "bekliyor",
    D.CI_KOSUYOR: "kosuyor",
    D.YESIL: "gecti",
    D.KIRMIZI: "kaldi",
    D.DERLEME_HATASI: "derleme_hatasi",
    D.SONUC_YOK: "kaldi",  # yanlış-yeşil koruması: check yeşil ama kanıt yok → geçmedi
    D.IPTAL: "bekliyor",
}
# GitHub PR durumu → portal kurulum `durum`.
_PR_DURUMU = {"open": "acik", "merged": "birlesti", "closed": "kapali"}


def hat_adi(platform: Any, dil: Any) -> str | None:
    """Script yanıtının `hat` alanı için: müşteri CI çiftiyse "musteri_ci"; değilse None
    (tam/dogrulanmamis Ş0'ın `cati(...).hat`'ından gelir)."""
    return HAT if musteri_ci_mi(platform, dil) else None


def merge_kabul_gerekli(platform: Any, dil: Any) -> list[str] | None:
    """Müşteri CI hattında merge yanıtının `merge_kabul_gerekli` alanı `[]` (kırarak doğrulama
    yok; yeşil CI yeterli — karar 2). Müşteri CI değilse None (mevcut hesap geçerli)."""
    return [] if musteri_ci_mi(platform, dil) else None


def portal_musteri_ci(g: HatGuncellemesi, head_sha: str | None = None) -> dict[str, Any]:
    """`script.musteri_ci = {check_adi, durum, head_sha, run_url, tamamlanma,
    sonuc{toplam, gecen, kalan, atlanan}, artefakt: alindi|yok|bekliyor, neden}`."""
    c = g.check or {}
    s = g.sonuc
    sayac = s.sayac if s is not None else None
    tamam = c.get("status") == "completed"
    if s is not None and (s.ayristirma is not None or s.meta):
        artefakt = "alindi"
    elif tamam:
        artefakt = "yok"
    else:
        artefakt = "bekliyor"
    neden: str | None = None
    if g.durum in (D.KIRMIZI, D.DERLEME_HATASI, D.SONUC_YOK, D.IPTAL):
        neden = ETIKETLER[g.durum]
        if g.durum == D.DERLEME_HATASI and s is not None and s.derleme_kesiti:
            neden = f"{neden}: {s.derleme_kesiti}"
    return {
        "check_adi": c.get("ad") or (g.dogrulama or {}).get("check"),
        "durum": PORTAL_DURUMU[g.durum],
        "hat_durumu": str(g.durum),  # iç ayrıntı (portal yok sayabilir)
        "head_sha": head_sha or (s.meta.get("sha") if s is not None else None),
        "run_url": c.get("url"),
        "tamamlanma": c.get("completed_at"),
        "sonuc": (
            {
                "toplam": sayac["toplam"],
                "gecen": sayac["gecen"] + sayac["flaky"],
                "kalan": sayac["basarisiz"],
                "atlanan": sayac["atlanan"],
            }
            if sayac is not None
            else None
        ),
        "artefakt": artefakt,
        "neden": neden,
    }


def _pr_alan(pr: Any, ad: str) -> Any:
    return pr.get(ad) if isinstance(pr, Mapping) else getattr(pr, ad, None)


def portal_kurulum(plan: KurulumPlani | None, pr: Any = None) -> dict[str, Any] | None:
    """`kurulum = {durum: gerekli|acik|birlesti|kapali, number, url, baslik, eksikler[],
    elle_adimlar[]}`. `pr`: kurulum PR'ı (`PullRequest` ya da `kurulum_pr_ac` sonucu); yoksa
    plan gerekliyse `gerekli`, değilse None (kurulum tamam, gösterilmez)."""
    # TP3-3: elle adım ya da engel olarak ayrıca listelenen madde `eksikler`'de tekrar etmez.
    eksikler = list(plan.depo_eksikleri) if plan is not None else []
    elle = list(plan.elle_adimlar) if plan is not None else []
    if pr is not None:
        durum = _pr_alan(pr, "state")
        if durum is None and _pr_alan(pr, "durum") in ("acildi", "mevcut"):
            durum = "open"
        return {
            "durum": _PR_DURUMU.get(str(durum), "acik"),
            "number": _pr_alan(pr, "number") or _pr_alan(pr, "pr_no"),
            "url": _pr_alan(pr, "url"),
            "baslik": _pr_alan(pr, "title") or (plan.baslik if plan is not None else None),
            "eksikler": eksikler,
            "elle_adimlar": elle or list(_pr_alan(pr, "elle_adimlar") or []),
        }
    if plan is None or not plan.gerekli:
        return None
    return {
        "durum": "gerekli",
        "number": None,
        "url": None,
        "baslik": plan.baslik,
        "eksikler": eksikler,
        "elle_adimlar": elle,
    }
