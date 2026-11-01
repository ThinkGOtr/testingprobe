"""Prova raporu: `rehearsal/reports/<zaman>/rapor.md` + `rapor.json` (+ `komutlar.log`).

Rapor; adım tablosu (PASS/FAIL, süre / bütçe), toplam süre ve §1 bütçesi, model kipi (REPLAY
etiketi), başarısız kontroller ve adım kanıtlarını içerir. Bütün metinler sır maskelemesinden geçer.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tp_rehearsal.runner import ATLANDI, FAIL, PASS, UYARI, AdimSonucu

SIMGE = {PASS: "✅ PASS", FAIL: "❌ FAIL", ATLANDI: "⏭ ATLANDI", UYARI: "⚠️ UYARI"}


@dataclass
class ProvaOzeti:
    kip: str
    baslangic: str
    bitis: str
    toplam_s: float
    toplam_butce_s: float
    model_modu: str
    replay_strict: str
    adimlar: list[AdimSonucu]
    notlar: list[str] = field(default_factory=list)
    kosu_no: int | None = None

    @property
    def basarili(self) -> bool:
        return (
            bool(self.adimlar)
            and all(a.durum in (PASS, UYARI) for a in self.adimlar)
            and not self.toplam_butce_asildi
        )

    @property
    def toplam_butce_asildi(self) -> bool:
        return self.kip == "prova" and self.toplam_s > self.toplam_butce_s

    def sayilar(self) -> dict[str, int]:
        s = {PASS: 0, FAIL: 0, ATLANDI: 0, UYARI: 0}
        for a in self.adimlar:
            s[a.durum] = s.get(a.durum, 0) + 1
        return s

    def cikis_kodu(self) -> int:
        return 0 if self.basarili else 1


def _sure(s: float) -> str:
    s = max(0.0, float(s))
    if s < 60:
        return f"{s:.1f} sn"
    return f"{int(s // 60)} dk {int(s % 60):02d} sn"


def _hucre(metin: Any) -> str:
    return str(metin).replace("|", "\\|").replace("\n", " ")


def markdown(oz: ProvaOzeti, maskele=lambda x: x) -> str:
    s = oz.sayilar()
    durum = "BAŞARILI" if oz.basarili else "BAŞARISIZ"
    mod = oz.model_modu or "?"
    mod_etiketi = (
        "REPLAY (kayıtlı/hazırlanmış çıktı — canlı model değil)" if mod == "replay" else mod
    )
    satirlar = [
        f"# Demo provası — {durum}",
        "",
        f"- Kip: **{oz.kip}**"
        + (" (salt okuma: eylem yok, tamamlanmış durum doğrulandı)" if oz.kip == "denetim" else ""),
        f"- Başlangıç: {oz.baslangic} · Bitiş: {oz.bitis}"
        + (f" · Koşu {oz.kosu_no}" if oz.kosu_no is not None else ""),
        f"- Model kipi: **{mod_etiketi}** · TP_REPLAY_STRICT={oz.replay_strict or '?'}",
        f"- Toplam süre: **{_sure(oz.toplam_s)}** / bütçe {_sure(oz.toplam_butce_s)} "
        "(TEKNIK-TASARIM §1: 20–25 dk canlı akış)"
        + (" — **BÜTÇE AŞILDI**" if oz.toplam_butce_asildi else ""),
        f"- Adımlar: {s[PASS]} PASS · {s[FAIL]} FAIL · {s[UYARI]} UYARI · {s[ATLANDI]} ATLANDI",
        "",
        "| # | Adım | Rol | §2 | Sonuç | Süre | Bütçe | Not |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for a in oz.adimlar:
        uyarilar = [k for k in a.kontroller if k.sonuc == UYARI]
        not_ = a.hata or ("; ".join(f"{k.ad}: {k.ayrinti}" for k in uyarilar) if uyarilar else "")
        sure = "—" if a.durum == ATLANDI else _sure(a.sure_s)
        if a.durum != ATLANDI and a.sure_s > a.butce_s:
            sure += " ⏱"
        satirlar.append(
            f"| {a.no} | {_hucre(a.ad)} | {a.rol} | {a.demo_adimi} | "
            f"{SIMGE.get(a.durum, a.durum)} | "
            f"{sure} | {_sure(a.butce_s)} | {_hucre(not_)[:300]} |"
        )
    if oz.notlar:
        satirlar += ["", "## Notlar", ""] + [f"- {n}" for n in oz.notlar]
    basarisiz = [a for a in oz.adimlar if a.durum == FAIL]
    if basarisiz:
        satirlar += ["", "## Başarısız adımlar", ""]
        for a in basarisiz:
            satirlar += [f"### {a.no} {a.ad}", "", f"**Hata:** {a.hata}", ""]
            for k in a.kontroller:
                satirlar.append(
                    f"- {SIMGE.get(k.sonuc, k.sonuc)} {k.ad}"
                    + (f" — {k.ayrinti}" if k.ayrinti else "")
                )
            if a.ayrinti:
                satirlar += ["", "```", a.ayrinti.strip(), "```"]
            satirlar.append("")
    satirlar += ["", "## Adım ayrıntıları", ""]
    for a in oz.adimlar:
        if a.durum == ATLANDI:
            continue
        satirlar += [f"<details><summary>{a.no} {_hucre(a.ad)} — {a.durum}</summary>", ""]
        for k in a.kontroller:
            satirlar.append(
                f"- {SIMGE.get(k.sonuc, k.sonuc)} {k.ad}"
                + (f" — {_hucre(k.ayrinti)[:300]}" if k.ayrinti else "")
            )
        if a.kanit:
            satirlar += [
                "",
                "```json",
                json.dumps(a.kanit, ensure_ascii=False, indent=1, default=str)[:4000],
                "```",
            ]
        satirlar += ["", "</details>", ""]
    return maskele("\n".join(satirlar) + "\n")


def json_rapor(oz: ProvaOzeti) -> dict[str, Any]:
    return {
        "kip": oz.kip,
        "basarili": oz.basarili,
        "cikis_kodu": oz.cikis_kodu(),
        "baslangic": oz.baslangic,
        "bitis": oz.bitis,
        "toplam_s": round(oz.toplam_s, 1),
        "toplam_butce_s": oz.toplam_butce_s,
        "toplam_butce_asildi": oz.toplam_butce_asildi,
        "model_modu": oz.model_modu,
        "replay_strict": oz.replay_strict,
        "kosu_no": oz.kosu_no,
        "sayilar": oz.sayilar(),
        "notlar": oz.notlar,
        "adimlar": [{**asdict(a), "butce_asildi": a.butce_asildi} for a in oz.adimlar],
    }


def yaz(
    oz: ProvaOzeti, dizin: Path, maskele=lambda x: x, komut_logu: str = "", cagri_logu: str = ""
) -> Path:
    # Rapor dizini yalnızca sahibine açık (yedek video paketi paylaşılmadan önce gözden geçirilir).
    dizin.mkdir(parents=True, exist_ok=True, mode=0o700)
    (dizin / "rapor.md").write_text(markdown(oz, maskele), encoding="utf-8")
    (dizin / "rapor.json").write_text(
        maskele(json.dumps(json_rapor(oz), ensure_ascii=False, indent=2, default=str)) + "\n",
        encoding="utf-8",
    )
    if komut_logu:
        (dizin / "komutlar.log").write_text(maskele(komut_logu), encoding="utf-8")
    if cagri_logu:
        (dizin / "api-cagrilari.tsv").write_text(maskele(cagri_logu), encoding="utf-8")
    return dizin


def konsol_tablosu(oz: ProvaOzeti) -> str:
    gen = max((len(a.ad) for a in oz.adimlar), default=10)
    gen = min(gen, 62)
    satirlar = [f"{'#':<3} {'Adım':<{gen}} {'Sonuç':<8} {'Süre':>10} {'Bütçe':>10}"]
    for a in oz.adimlar:
        sure = "—" if a.durum == ATLANDI else _sure(a.sure_s)
        satirlar.append(
            f"{a.no:<3} {a.ad[:gen]:<{gen}} {a.durum:<8} {sure:>10} {_sure(a.butce_s):>10}"
        )
    s = oz.sayilar()
    satirlar.append(
        f"Toplam {_sure(oz.toplam_s)} / {_sure(oz.toplam_butce_s)} · {s[PASS]} PASS · "
        f"{s[FAIL]} FAIL · {s[UYARI]} UYARI · {s[ATLANDI]} ATLANDI → "
        f"{'BAŞARILI' if oz.basarili else 'BAŞARISIZ'}"
    )
    return "\n".join(satirlar)
