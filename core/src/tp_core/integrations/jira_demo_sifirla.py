"""Home "Sıfırla" düğmesinin Jira adımı: demo Jira projesini (TPD) demo başlangıcına döndürür.

`jira_seed`'in yaptıklarına (TPD-1..4 içerik/etiket, TPD-5..7 içerik, TPD-1..7 yorumları) ek olarak:

1. **TPD-8 ve sonrası** (proje anahtarında numarası 7'den büyük HER kayıt; etiketinden bağımsız —
   bugün TPD-15, TPD-70..86 gibi etiketi önceden kaldırılmış koşu kalıntıları dahil) silinir. Yazma
   kimliğinin "Delete issues" izni yoksa (ya da tek kayıtta 401/403) kayıt "Done" kategorisine
   kapatılır ve `tp-*` / `AI-generated` etiketleri kaldırılır (kapalı Bug mükerrer aramasına
   girmez).
   TPD-1..TPD-7 asla silinmez ve kapatılmaz (anahtarlar sabit; demo onlara bağlı).
2. TPD-1..TPD-7'deki **tüm iş bağlantıları** (önceki provadan kalan TPD-5 ↔ TPD-1 "relates to")
   kaldırılır; bu kayıtlardaki `tp-*` (``tp-demo`` hariç) ve `AI-generated` etiketleri kalkar.
3. Durumlar canlı demo senaryosu v2 B0.1 tablosuna taşınır (`HEDEF_DURUMLAR`). Doğrudan geçiş yoksa
   en çok `MAX_ADIM` adımlık yol denenir.

Hepsi idempotenttir: yeniden çalıştırmak yalnız eksik kalanı yapar. Tek kayıt hatası diğerlerini
durdurmaz; hatalar listelenir ve adım hata sayılır. `dogrula` aynı hedefi salt okuma ile denetler
(Home "Demoya hazır" listesi).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tp_core.integrations import jira_seed
from tp_core.integrations.jira import (
    JiraAuthError,
    JiraError,
    JiraNotFound,
    JiraPermissionError,
    RestJira,
)

# docs/CANLI-DEMO-SENARYOSU-v2.md B0.1 "Olması gereken durum".
HEDEF_DURUMLAR: dict[int, str] = {
    1: "In Progress",
    2: "To Do",
    3: "To Do",
    4: "In Progress",
    5: "To Do",
    6: "In Progress",
    7: "Done",
}
TOHUM_SAYISI = jira_seed.SEED_ISSUE_COUNT
MAX_ADIM = 3
MAX_KAYIT = 2000


def _norm(deger: Any) -> str:
    return " ".join(str(deger or "").split()).casefold()


def yasak_etiket(etiket: str) -> bool:
    """Tohum kayıtlarında kalmaması gereken ürün etiketleri (``tp-demo`` hariç ``tp-*``,
    ``AI-generated``)."""
    return etiket != jira_seed.DEMO_LABEL and (
        etiket.startswith("tp-") or etiket == jira_seed.AI_LABEL
    )


def _numara(key: str, proje: str) -> int | None:
    onek = f"{proje}-"
    if not key.startswith(onek) or not key[len(onek) :].isdigit():
        return None
    return int(key[len(onek) :])


def fazla_kayitlar(jira: RestJira, proje: str, *, yalniz_acik: bool = False) -> list[str]:
    """Projede numarası `TOHUM_SAYISI`'ndan büyük kayıtlar (anahtar sırasıyla)."""
    kosul = " AND statusCategory != Done" if yalniz_acik else ""
    bulunan = jira.search(
        f'project = "{proje}"{kosul} ORDER BY key ASC',  # gitleaks:allow
        max_results=MAX_KAYIT,
    )
    out = []
    for i in bulunan:
        n = _numara(i.key, proje)
        if n is not None and n > TOHUM_SAYISI:
            out.append((n, i.key))
    return [k for _, k in sorted(out)]


@dataclass
class JiraSonucu:
    proje: str
    silinen: list[str] = field(default_factory=list)
    kapatilan: list[str] = field(default_factory=list)
    baglanti_kaldirilan: int = 0
    etiket_temizlenen: list[str] = field(default_factory=list)
    durum_tasinan: dict[str, str] = field(default_factory=dict)
    icerik_donen: list[str] = field(default_factory=list)
    yorum_silinen: int = 0
    silme_izni: bool | None = None
    eksik: list[str] = field(default_factory=list)
    hatalar: list[str] = field(default_factory=list)

    def ozet(self) -> str:
        parca = [
            f"{len(self.silinen)} kayıt silindi" if self.silinen else "silinecek TPD-8+ kaydı yok",
        ]
        if self.kapatilan:
            parca.append(f"{len(self.kapatilan)} kayıt kapatıldı (silme izni yok)")
        if self.baglanti_kaldirilan:
            parca.append(f"{self.baglanti_kaldirilan} bağlantı kaldırıldı")
        if self.durum_tasinan:
            parca.append(f"{len(self.durum_tasinan)} kaydın durumu düzeltildi")
        if self.icerik_donen:
            parca.append(f"{len(self.icerik_donen)} kaydın içeriği/etiketi döndü")
        if self.yorum_silinen:
            parca.append(f"{self.yorum_silinen} yorum silindi")
        return "; ".join(parca)

    def as_dict(self) -> dict[str, Any]:
        return {
            "proje": self.proje,
            "silinen": self.silinen,
            "kapatilan": self.kapatilan,
            "baglanti_kaldirilan": self.baglanti_kaldirilan,
            "etiket_temizlenen": self.etiket_temizlenen,
            "durum_tasinan": self.durum_tasinan,
            "icerik_donen": self.icerik_donen,
            "yorum_silinen": self.yorum_silinen,
            "silme_izni": self.silme_izni,
            "eksik": self.eksik,
            "hatalar": self.hatalar,
        }


def _kapat(jira: RestJira, key: str, sonuc: JiraSonucu) -> None:
    try:
        etiketler = [str(e) for e in jira.raw_fields(key, ("labels",)).get("labels") or []]
        tid = jira_seed._done_transition(jira, key)
        if tid is None and jira.search(f'key = "{key}" AND statusCategory != Done', max_results=1):
            sonuc.hatalar.append(f"{key}: silinemedi ve 'Done' kategorisinde geçiş yok")
            return
        if tid is not None:
            jira.transition(key, tid)
        kaldir = [e for e in etiketler if e.startswith("tp-") or e == jira_seed.AI_LABEL]
        if kaldir:
            jira.edit_issue(key, remove_labels=kaldir)
        sonuc.kapatilan.append(key)
    except JiraError as exc:
        sonuc.hatalar.append(f"{key}: kapatılamadı: {exc}"[:300])


def _fazlalari_temizle(jira: RestJira, proje: str, sonuc: JiraSonucu) -> None:
    sonuc.silme_izni = jira.has_permission(proje, "DELETE_ISSUES")
    for key in fazla_kayitlar(jira, proje):
        if sonuc.silme_izni is False:
            _kapat(jira, key, sonuc)
            continue
        try:
            jira.delete_issue(key)
            sonuc.silinen.append(key)
        except JiraNotFound:
            continue  # bu arada silinmiş
        except (JiraPermissionError, JiraAuthError):
            _kapat(jira, key, sonuc)
        except JiraError as exc:
            sonuc.hatalar.append(f"{key}: silinemedi: {exc}"[:300])


def _baglantilari_kaldir(jira: RestJira, proje: str, sonuc: JiraSonucu) -> None:
    for n in range(1, TOHUM_SAYISI + 1):
        key = f"{proje}-{n}"
        try:
            baglar = jira.issue_links(key)
        except JiraNotFound:
            continue
        except JiraError as exc:
            sonuc.hatalar.append(f"{key}: bağlantılar okunamadı: {exc}"[:300])
            continue
        for bag in baglar:
            bid = str(bag.get("id") or "")
            if not bid:
                continue
            try:
                jira.delete_issue_link(bid)
                sonuc.baglanti_kaldirilan += 1
            except JiraNotFound:
                continue  # karşı kayıttan zaten kaldırıldı
            except JiraError as exc:
                sonuc.hatalar.append(f"{key}: bağlantı {bid} kaldırılamadı: {exc}"[:300])


def _tohum_etiketleri(jira: RestJira, proje: str, sonuc: JiraSonucu) -> None:
    """`jira_seed` yalnız ``tp-po-*``/``tp-<uuid>``/``AI-generated``'i kaldırır; burada kalan
    ürün etiketleri (ör. ``tp-mod-replay``) de kalkar (TPD-1..7; ``tp-demo`` korunur)."""
    for n in range(1, TOHUM_SAYISI + 1):
        key = f"{proje}-{n}"
        try:
            etiketler = [str(e) for e in jira.raw_fields(key, ("labels",)).get("labels") or []]
            kaldir = [e for e in etiketler if yasak_etiket(e)]
            if kaldir:
                jira.edit_issue(key, remove_labels=kaldir)
                sonuc.etiket_temizlenen.append(key)
        except JiraNotFound:
            continue
        except JiraError as exc:
            sonuc.hatalar.append(f"{key}: etiket temizlenemedi: {exc}"[:300])


def durum_tasi(jira: RestJira, key: str, hedef: str) -> str | None:
    """`key`'i `hedef` duruma taşır. Doğrudan geçiş yoksa ziyaret edilmemiş bir duruma geçip
    yeniden dener (en çok `MAX_ADIM`). Dönen: önceki durum (değiştiyse) ya da None (zaten hedefte).
    Ulaşılamazsa `JiraError`."""
    hedef_n = _norm(hedef)
    once = jira.get_issue(key).status
    if _norm(once) == hedef_n:
        return None
    goruldu = {_norm(once)}
    for _ in range(MAX_ADIM):
        gecisler = jira.transitions(key)

        def _ad(t: dict[str, Any]) -> str:
            return str((t.get("to") or {}).get("name") or "")

        direkt = next((t for t in gecisler if _norm(_ad(t)) == hedef_n), None)
        if direkt is not None:
            jira.transition(key, str(direkt["id"]))
            return once
        oncelik = [_norm(d) for d in ("To Do", "In Progress", "Done")]
        adaylar = [t for t in gecisler if _norm(_ad(t)) not in goruldu]
        adaylar.sort(key=lambda t: oncelik.index(_norm(_ad(t))) if _norm(_ad(t)) in oncelik else 9)
        if not adaylar:
            break
        ara = adaylar[0]
        jira.transition(key, str(ara["id"]))
        goruldu.add(_norm(_ad(ara)))
    simdi = jira.get_issue(key).status
    if _norm(simdi) == hedef_n:
        return once
    raise JiraError(f"{key}: '{hedef}' durumuna geçiş yolu bulunamadı (şu an '{simdi}')")


def _durumlari_tasi(jira: RestJira, proje: str, sonuc: JiraSonucu) -> None:
    for n, hedef in HEDEF_DURUMLAR.items():
        key = f"{proje}-{n}"
        try:
            once = durum_tasi(jira, key, hedef)
        except JiraNotFound:
            continue
        except JiraError as exc:
            sonuc.hatalar.append(str(exc)[:300])
            continue
        if once is not None:
            sonuc.durum_tasinan[key] = f"{once} → {hedef}"


def sifirla(jira: RestJira, proje: str) -> JiraSonucu:
    """Jira demo projesini başlangıca döndürür (yazar). Sıra: fazla kayıtlar → bağlantılar →
    içerik/etiket/yorum (`jira_seed`) → kalan ürün etiketleri → durumlar."""
    sonuc = JiraSonucu(proje=proje)
    _fazlalari_temizle(jira, proje, sonuc)
    _baglantilari_kaldir(jira, proje, sonuc)
    plan = jira_seed.plan(jira, proje)
    # Koşu kayıtları (TPD-8+) yukarıda etiketten bağımsız işlendi; tohum planında yalnız
    # TPD-1..7'nin içerik, etiket ve yorumları kalır.
    plan.run_issues = []
    plan.run_labels = {}
    sonuc.eksik = list(plan.missing)
    if not plan.empty:
        r = jira_seed.apply(jira, plan, delete=False)
        sonuc.icerik_donen = [*r.restored, *r.bugs_restored]
        sonuc.yorum_silinen = r.comments_deleted
        sonuc.hatalar.extend(r.failed)
    _tohum_etiketleri(jira, proje, sonuc)
    _durumlari_tasi(jira, proje, sonuc)
    for key in sonuc.eksik:
        sonuc.hatalar.append(f"{key}: Jira'da yok (elle oluşturulmalı)")
    return sonuc


# --------------------------------------------------------------------------- doğrulama


def _kontrol(kod: str, durum: str, ayrinti: str) -> dict[str, str]:
    return {"kod": kod, "durum": durum, "ayrinti": ayrinti}


def dogrula(jira: RestJira, proje: str) -> list[dict[str, str]]:
    """Salt okuma: `jira_durumlar`, `jira_icerik`, `jira_fazla` kontrolleri."""
    out: list[dict[str, str]] = []
    durum_hata: list[str] = []
    icerik_hata: list[str] = []
    tohumlar = {s.number: s for s in (*jira_seed.DEMO_STORIES, *jira_seed.SEED_BUGS)}
    for n, hedef in HEDEF_DURUMLAR.items():
        key = f"{proje}-{n}"
        try:
            f = jira.raw_fields(
                key, ("summary", "description", "labels", "status", "issuelinks", "comment")
            )
        except JiraNotFound:
            durum_hata.append(f"{key} yok")
            continue
        durum = str((f.get("status") or {}).get("name") or "")
        if _norm(durum) != _norm(hedef):
            durum_hata.append(f"{key} '{durum}' (beklenen '{hedef}')")
        sorun = []
        tohum = tohumlar.get(n)
        if tohum is not None and not jira_seed._same_content(f, tohum):
            sorun.append("içerik farklı")
        etiketler = [str(e) for e in f.get("labels") or []]
        yasak = [e for e in etiketler if yasak_etiket(e)]
        if yasak:
            sorun.append("etiket: " + ", ".join(yasak))
        if n <= len(jira_seed.DEMO_STORIES) and jira_seed.DEMO_LABEL not in etiketler:
            sorun.append(f"'{jira_seed.DEMO_LABEL}' etiketi yok")
        if f.get("issuelinks"):
            sorun.append(f"{len(f['issuelinks'])} bağlantı")
        yorum = (f.get("comment") or {}).get("total")
        if yorum is None:
            yorum = len(jira.get_comments(key))
        if yorum:
            sorun.append(f"{yorum} yorum")
        if sorun:
            icerik_hata.append(f"{key}: " + ", ".join(sorun))
    out.append(
        _kontrol("jira_durumlar", "hata", "; ".join(durum_hata))
        if durum_hata
        else _kontrol(
            "jira_durumlar",
            "tamam",
            ", ".join(f"{proje}-{n} {d}" for n, d in HEDEF_DURUMLAR.items()),
        )
    )
    out.append(
        _kontrol("jira_icerik", "hata", "; ".join(icerik_hata))
        if icerik_hata
        else _kontrol(
            "jira_icerik",
            "tamam",
            f"{proje}-1..{TOHUM_SAYISI}: tohum içeriği, yalnız '{jira_seed.DEMO_LABEL}' etiketi, "
            "yorum ve bağlantı yok",
        )
    )
    tum = fazla_kayitlar(jira, proje)
    acik = fazla_kayitlar(jira, proje, yalniz_acik=True) if tum else []
    if not tum:
        out.append(_kontrol("jira_fazla", "tamam", f"{proje}-{TOHUM_SAYISI + 1} ve sonrası yok"))
    elif acik:
        out.append(_kontrol("jira_fazla", "hata", "Açık kalan kayıtlar: " + ", ".join(acik[:20])))
    else:
        out.append(
            _kontrol(
                "jira_fazla",
                "uyari",
                f"{len(tum)} kayıt silinemedi ama kapalı (silme izni yok): " + ", ".join(tum[:20]),
            )
        )
    return out
