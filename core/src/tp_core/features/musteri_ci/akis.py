"""Müşteri CI hattının durum güncellemesi: PR head'inin GitHub check'i + tp-results → hat durumu.

Yalnız okuma (forge `check_runs`, Actions `workflow_run`/`artifacts`/`artifact_zip`); veritabanı
yazmaz. Çağıran (Ş3/Ş4 codegen/CI bağlantısı ya da entegrasyon) sonucu script/koşu kaydına
yazar ve `durum.gecis` ile geçişi doğrular.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from tp_core.features.ci.parse import temiz
from tp_core.features.musteri_ci.durum import (
    D,
    GecersizGecis,
    HatDurumu,
    check_durumu,
    gecis,
    merge_kapisi,
    sonuctan_durum,
)
from tp_core.features.musteri_ci.sonuc import (
    KimlikDonusturucu,
    MusteriCiSonucu,
    derleme_kesiti,
    tp_results_al,
)
from tp_core.features.musteri_ci.sozlesme import dogrulama_bilgisi, hedef


@dataclass
class HatGuncellemesi:
    durum: HatDurumu
    check: dict[str, Any] | None  # {ad, status, conclusion, url, workflow_run_id, job_id}
    sonuc: MusteriCiSonucu | None
    merge: tuple[bool, str]
    dogrulama: dict[str, Any] | None  # sozlesme.dogrulama_bilgisi (rozet)
    uyarilar: list[str] = field(default_factory=list)

    def ozet(self) -> dict[str, Any]:
        """JSON'a yazılabilir özet (script/koşu kaydı ve portal için)."""
        s = self.sonuc
        return {
            "durum": str(self.durum),
            "check": dict(self.check) if self.check else None,
            "merge": {"gecer": self.merge[0], "neden": self.merge[1]},
            "dogrulama": self.dogrulama,
            "sayac": s.sayac if s is not None else None,
            "meta": dict(s.meta) if s is not None else {},
            "derleme_kesiti": s.derleme_kesiti if s is not None else None,
            "yerel": (
                {k: v for k, v in s.yerel.items() if k != "indirilen"}
                if s is not None and s.yerel
                else None
            ),
            "uyarilar": [*self.uyarilar, *(s.uyarilar if s is not None else [])],
        }


def _alan(c: Any, ad: str) -> Any:
    return c.get(ad) if isinstance(c, Mapping) else getattr(c, ad, None)


def check_bul(check_runs: Sequence[Any], platform: str, dil: str) -> Any | None:
    """`forge.check_runs(sha)` listesinden hedefin check'i (ad = `is_adi`; birden çoksa en yeni:
    `started_at` en büyük, eşitse listede sonra gelen). Öğeler `GitHubCheckRun` ya da aynı alanlı
    eşleme olabilir."""
    ad = hedef(platform, dil).is_adi
    adaylar = [(i, c) for i, c in enumerate(check_runs or []) if _alan(c, "name") == ad]
    if not adaylar:
        return None
    return max(adaylar, key=lambda ic: (str(_alan(ic[1], "started_at") or ""), ic[0]))[1]


def _check_ozeti(c: Any) -> dict[str, Any]:
    return {
        "ad": _alan(c, "name"),
        "status": _alan(c, "status"),
        "conclusion": _alan(c, "conclusion"),
        "url": _alan(c, "html_url") or _alan(c, "details_url"),
        "workflow_run_id": _alan(c, "workflow_run_id"),
        "job_id": _alan(c, "job_id"),
        "completed_at": _alan(c, "completed_at"),
    }


def hat_durumu(
    forge: Any,
    gh: Any,
    sha: str,
    platform: str,
    dil: str,
    *,
    mevcut: HatDurumu | str | None = None,
    kimlik: KimlikDonusturucu | None = None,
    log_oku: Callable[[int], str | bytes | None] | None = None,
) -> HatGuncellemesi:
    """PR head `sha`'sı için hat durumunu hesaplar.

    Check yoksa `ci_bekleniyor`; tamamlanmamışsa `check_durumu`; tamamlanmışsa tp-results okunur
    (`sonuc.tp_results_al`) ve `durum.sonuctan_durum`. Derleme hatasında kesit önce artefaktın
    `derleme.log`'undan, yoksa `log_oku(job_id) -> str` (ör. `GitHubCiOkuyucu`) ile alınır.
    `mevcut` verilirse geçiş doğrulanır; geçersiz geçiş uyarıya yazılır, yeni durum yine döner
    (dış dünya otoritedir)."""
    hedef(platform, dil)
    uyarilar: list[str] = []
    if kimlik is None:
        # 014 entegrasyonu: dil şeridinin kimlik dönüşümü (Kotlin `kimlik_donusturucu(kök)`).
        try:
            from tp_core.features.musteri_ci.dil_kancalari import varsayilan_kimlik

            kimlik = varsayilan_kimlik(platform, dil)
        except Exception as exc:  # kök çözülemedi: ham kimlik, uyarı
            uyarilar.append(f"test kimliği dönüşümü kurulamadı: {temiz(exc, 200)}")
    sonuc: MusteriCiSonucu | None = None
    check_ozet: dict[str, Any] | None = None
    try:
        c = check_bul(forge.check_runs(sha), platform, dil)
    except Exception as exc:  # okuma hatası: bekleniyor say, uyar
        uyarilar.append(f"check'ler okunamadı: {temiz(exc, 200)}")
        c = None
    if c is None:
        yeni = D.CI_BEKLENIYOR
    else:
        check_ozet = _check_ozeti(c)
        status, conclusion = check_ozet["status"], check_ozet["conclusion"]
        yeni = check_durumu(status, conclusion)
        if status == "completed":
            run_id = check_ozet["workflow_run_id"]
            if run_id:
                sonuc = tp_results_al(
                    gh, {"id": run_id, "head_sha": sha}, platform, dil, kimlik=kimlik
                )
                yeni = sonuctan_durum(conclusion, sonuc.sayac)
            else:
                uyarilar.append("check'in GitHub Actions koşu kimliği yok; tp-results okunamadı.")
                yeni = sonuctan_durum(conclusion, None)
            if (
                yeni == D.DERLEME_HATASI
                and (sonuc is None or not sonuc.derleme_kesiti)
                and log_oku is not None
                and check_ozet["job_id"]
            ):
                try:
                    kesit = derleme_kesiti(log_oku(int(check_ozet["job_id"])), dil)
                except Exception as exc:
                    uyarilar.append(f"iş logu okunamadı: {temiz(exc, 200)}")
                    kesit = None
                if kesit:
                    if sonuc is None:
                        sonuc = MusteriCiSonucu(platform=platform, dil=dil, ayristirma=None)
                    sonuc.derleme_kesiti = kesit
    if mevcut is not None:
        try:
            gecis(mevcut, yeni)
        except GecersizGecis as exc:
            uyarilar.append(str(exc))
    return HatGuncellemesi(
        durum=yeni,
        check=check_ozet,
        sonuc=sonuc,
        merge=merge_kapisi(yeni),
        dogrulama=dogrulama_bilgisi(platform, dil),
        uyarilar=uyarilar,
    )


def ozet_sozlugu(g: HatGuncellemesi) -> Mapping[str, Any]:
    return g.ozet()
