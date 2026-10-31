"""Gereksinim içeriği: hash, kabul kriteri ayrıştırma, prompt belgesi ve düzeltme birleştirme.

İçerik hash'i (`requirement_hash`) platformun onay kapılarının kullandığı hash'le
(`workflow.service.content_hash_of(requirement)`) birebir aynıdır: kanonik JSON
``{"baslik", "aciklama", "kabul_kriterleri"}`` üzerinde sha256. `requirement.kaynak_hash` her
senkron/düzeltmede bu değere yazılır.

Doküman düzeltmesi birleştirme kuralları (§8.2b adım 6, deterministik; LLM yok)
---------------------------------------------------------------------------------

Onaylanan her `fix_doc` metni satırlara bölünür (baştaki/sondaki boşluk atılır, boş satırlar yok
sayılır) ve satırlar hedeflere dağıtılır:

1. ``ACn: …`` (ayraç `:` `.` `)` ya da `-`; büyük/küçük harf duyarsız) satırı **ACn**'i hedefler ve
   o kabul kriterinin metninin tamamını değiştirir. Saklanan biçim ``"ACn: <metin>"``dir.
2. Bir AC satırını izleyen, AC ile başlamayan satırlar o AC'nin devamıdır (tek boşlukla eklenir).
3. Metnin başında (ilk AC satırından önce) gelen satırlar **açıklamayı** hedefler ve açıklamanın
   tamamını değiştirir (satırlar ``\\n`` ile birleşir).
4. ``n`` mevcut AC sayısından büyükse yeni AC eklenir; eklenenler boşluksuz ardışık olmalıdır
   (AC sayısı 6 iken AC7 eklenebilir, AC9 eklenemez).
5. İki düzeltme aynı hedefe **farklı** metin yazıyorsa birleştirme reddedilir
   (`DocMergeConflict`, 409): analist kararlardan birini düzeltmelidir. Aynı metni yazıyorlarsa
   (ör. TPD-1 F1 ve F3 aynı AC3'ü önerir) tek değişiklik sayılır — sonuç düzeltmelerin
   sırasından bağımsızdır.
6. Sonuç: açıklama + AC'ler numara sırasıyla. Değişiklik listesi (hedef, önce, sonra, bulgular)
   Jira'ya değişiklik özeti yorumu olarak yazılır.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from tp_core.audit import content_hash

AC_LINE_RE = re.compile(r"^\s*AC\s*(\d+)\s*[:.)\-]\s*(.*)$", re.IGNORECASE)
AC_REF_RE = re.compile(r"\bAC\s*(\d+)\b", re.IGNORECASE)
DESC_REF_RE = re.compile(r"(açıklama|aciklama|description|özet|ozet)", re.IGNORECASE)
DESC = "DESC"

# Görüntüleme amaçlı (karar vermez) talimat benzeri metin işaretleri (§5). İçerik yine de modele
# yalnızca etiketli güvenilmeyen blokta gider; bu liste yalnızca portalda uyarı göstermek içindir.
_INJECTION_PATTERNS = (
    re.compile(r"talimat\w*\s+(?:\w+\s+){0,2}yok\s+say", re.IGNORECASE),
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions", re.IGNORECASE),
    re.compile(r"onaylanmış\s+olarak\s+işaretle", re.IGNORECASE),
    re.compile(r"system\s+prompt|sistem\s+(?:prompt|talimat)", re.IGNORECASE),
)
INJECTION_UYARISI = (
    "Açıklamada modele yönelik talimat benzeri metin var; güvenilmeyen içerik olarak işlenir ve "
    "uygulanmaz."
)
AC_MISSING_UYARISI = "Kabul kriteri yok: case üretimine gönderilmez; PO'ya sorulur."


def requirement_hash(baslik: str, aciklama: str, kabul_kriterleri: Sequence[str]) -> str:
    """`content_hash_of(requirement)` ile aynı hesap (CONTENT_FIELDS['requirement'])."""
    return content_hash(
        {"baslik": baslik, "aciklama": aciklama, "kabul_kriterleri": list(kabul_kriterleri)}
    )


def normalize_acs(items: Iterable[str]) -> list[str]:
    """Serbest metin AC'lerini ``"ACn: metin"`` biçimine getirir (konumdan numaralanır)."""
    out: list[str] = []
    for item in items:
        metin = " ".join(str(item).split())
        if not metin:
            continue
        m = AC_LINE_RE.match(metin)
        if m:
            metin = m.group(2).strip()
        if metin:
            out.append(f"AC{len(out) + 1}: {metin}")
    return out


def split_ac(ac: str) -> tuple[str, str]:
    """``"AC3: metin"`` → ``("AC3", "metin")``; önek yoksa ``("", ac)``."""
    m = AC_LINE_RE.match(ac)
    if not m:
        return "", ac.strip()
    return f"AC{int(m.group(1))}", m.group(2).strip()


def ac_items(acs: Sequence[str]) -> list[dict[str, str]]:
    out = []
    for i, ac in enumerate(acs, start=1):
        ref, metin = split_ac(str(ac))
        out.append({"ref": ref or f"AC{i}", "metin": metin})
    return out


def ac_refs(doc_ref: str) -> list[str]:
    return [f"AC{int(n)}" for n in AC_REF_RE.findall(doc_ref or "")]


def refers_to_description(doc_ref: str) -> bool:
    return bool(DESC_REF_RE.search(doc_ref or ""))


def doc_ref_valid(doc_ref: str, acs: Sequence[str]) -> bool:
    """Bulgunun belge referansı belgede var mı (deterministik; LLM'siz)."""
    mevcut = {split_ac(a)[0] for a in acs}
    refs = ac_refs(doc_ref)
    if refs:
        return all(r in mevcut for r in refs)
    return refers_to_description(doc_ref)


def current_doc_text(doc_ref: str, aciklama: str, acs: Sequence[str]) -> str | None:
    """Bulgunun işaret ettiği belge metni (AC satırları ya da açıklama)."""
    by_ref = {split_ac(a)[0]: a for a in acs}
    secilen = [by_ref[r] for r in dict.fromkeys(ac_refs(doc_ref)) if r in by_ref]
    if secilen:
        return "\n".join(secilen)
    if refers_to_description(doc_ref):
        return aciklama
    return None


def replaced_doc_text(
    fix_text: str | None, doc_ref: str, aciklama: str, acs: Sequence[str]
) -> str | None:
    """Düzeltme metninin gerçekten DEĞİŞTİRECEĞİ belge metni (portal farkının "önce" tarafı).

    Bulgu birden çok AC'ye atıf yapsa da (ör. ``AC3 ↔ AC6``) düzeltme yalnızca metnindeki
    ``ACn:`` satırlarını (ve baştaki açıklama satırlarını) değiştirir (`merge_fixes` kuralları).
    Fark yalnızca bu hedefler üzerinden gösterilir; değişmeyen AC "silindi" görünmez. Metin
    ayrıştırılamıyorsa ya da öneri yoksa `doc_ref`'in metnine düşülür.
    """
    try:
        hedefler = parse_fix_text(fix_text or "") if fix_text else {}
    except DocMergeError:
        hedefler = {}
    if not hedefler:
        return current_doc_text(doc_ref, aciklama, acs)
    by_ref = {split_ac(a)[0]: a for a in acs}
    parcalar: list[str] = []
    for hedef in sorted(hedefler, key=_hedef_sirasi):
        if hedef == DESC:
            if aciklama:
                parcalar.append(aciklama)
        elif hedef in by_ref:
            parcalar.append(by_ref[hedef])
    return "\n".join(parcalar)


def changed_targets(
    once_aciklama: str, once_acs: Sequence[str], sonra_aciklama: str, sonra_acs: Sequence[str]
) -> set[str]:
    """İki belge sürümü arasında metni değişen hedefler (``ACn`` ya da ``DESC``)."""
    once = {split_ac(a)[0] or f"AC{i}": a for i, a in enumerate(once_acs, start=1)}
    sonra = {split_ac(a)[0] or f"AC{i}": a for i, a in enumerate(sonra_acs, start=1)}
    out = {r for r in set(once) | set(sonra) if once.get(r) != sonra.get(r)}
    if (once_aciklama or "").strip() != (sonra_aciklama or "").strip():
        out.add(DESC)
    return out


def injection_warnings(*metinler: str) -> list[str]:
    birlesik = "\n".join(metinler)
    if any(p.search(birlesik) for p in _INJECTION_PATTERNS):
        return [INJECTION_UYARISI]
    return []


# ------------------------------------------------------------------ düzeltme birleştirme


class DocMergeError(ValueError):
    """Düzeltme metni kurallara uymuyor (422)."""


class DocMergeConflict(DocMergeError):
    """İki onaylı düzeltme aynı hedefe farklı metin yazıyor (409)."""


@dataclass(frozen=True)
class DocFix:
    finding_id: str
    doc_ref: str
    text: str


@dataclass
class MergeResult:
    aciklama: str
    kabul_kriterleri: list[str]
    degisiklikler: list[dict[str, Any]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(d["once"] != d["sonra"] for d in self.degisiklikler)


def parse_fix_text(text: str) -> dict[str, str]:
    """Düzeltme metni → {hedef: yeni metin}; hedef ``ACn`` ya da ``DESC`` (kurallar 1–3)."""
    satirlar = [s.strip() for s in (text or "").splitlines() if s.strip()]
    if not satirlar:
        raise DocMergeError("Düzeltilmiş doküman metni boş olamaz")
    hedefler: dict[str, list[str]] = {}
    sira: list[str] = []
    aktif: str | None = None
    for satir in satirlar:
        m = AC_LINE_RE.match(satir)
        if m:
            hedef = f"AC{int(m.group(1))}"
            if int(m.group(1)) < 1:
                raise DocMergeError("AC numarası 1'den başlar")
            if hedef in hedefler:
                raise DocMergeError(f"{hedef} aynı düzeltme metninde iki kez geçiyor")
            hedefler[hedef] = [m.group(2).strip()]
            sira.append(hedef)
            aktif = hedef
        elif aktif is None:
            hedefler.setdefault(DESC, []).append(satir)
            if DESC not in sira:
                sira.append(DESC)
        else:
            hedefler[aktif].append(satir)
    out: dict[str, str] = {}
    for hedef in sira:
        parcalar = hedefler[hedef]
        if hedef == DESC:
            out[DESC] = "\n".join(parcalar)
        else:
            metin = " ".join(p for p in parcalar if p)
            if not metin:
                raise DocMergeError(f"{hedef} için metin boş")
            out[hedef] = f"{hedef}: {metin}"
    return out


def merge_fixes(aciklama: str, acs: Sequence[str], fixes: Sequence[DocFix]) -> MergeResult:
    """Onaylı düzeltmeleri belgeye uygular (kurallar modül belgesinde)."""
    hedef_metin: dict[str, str] = {}
    hedef_bulgu: dict[str, list[str]] = {}
    for fix in sorted(fixes, key=lambda f: f.finding_id):
        for hedef, metin in parse_fix_text(fix.text).items():
            onceki = hedef_metin.get(hedef)
            if onceki is not None and onceki != metin:
                raise DocMergeConflict(
                    f"{hedef_ad(hedef)} için onaylı düzeltmeler farklı metin öneriyor "
                    f"(bulgular: {', '.join([*hedef_bulgu[hedef], fix.finding_id])}); "
                    "düzeltmelerden birini diğeriyle aynı yapın"
                )
            hedef_metin[hedef] = metin
            hedef_bulgu.setdefault(hedef, []).append(fix.finding_id)

    mevcut = {split_ac(a)[0] or f"AC{i}": a for i, a in enumerate(acs, start=1)}
    sayi = len(acs)
    yeni_numaralar = sorted(
        int(h[2:]) for h in hedef_metin if h != DESC and f"AC{int(h[2:])}" not in mevcut
    )
    for beklenen, n in enumerate(yeni_numaralar, start=sayi + 1):
        if n != beklenen:
            raise DocMergeError(
                f"AC{n} eklenemez: yeni kabul kriterleri AC{sayi + 1}'den başlayarak ardışık olmalı"
            )

    sonuc = dict(mevcut)
    degisiklikler: list[dict[str, Any]] = []
    yeni_aciklama = aciklama
    for hedef in sorted(hedef_metin, key=_hedef_sirasi):
        metin = hedef_metin[hedef]
        if hedef == DESC:
            once, yeni_aciklama = aciklama, metin
        else:
            once = mevcut.get(hedef)
            sonuc[hedef] = metin
        degisiklikler.append(
            {
                "hedef": hedef_ad(hedef),
                "once": once,
                "sonra": metin,
                "bulgular": sorted(set(hedef_bulgu[hedef])),
            }
        )
    yeni_acs = [sonuc[k] for k in sorted(sonuc, key=lambda r: int(r[2:]))]
    return MergeResult(yeni_aciklama, yeni_acs, degisiklikler)


def validate_fix_text(text: str, aciklama: str, acs: Sequence[str]) -> MergeResult:
    """Tek düzeltmenin kurallara uyduğunu doğrular (karar anında, 422)."""
    return merge_fixes(aciklama, acs, [DocFix("karar", "", text)])


def hedef_ad(hedef: str) -> str:
    return "Açıklama" if hedef == DESC else hedef


def _hedef_sirasi(hedef: str) -> tuple[int, int]:
    return (0, 0) if hedef == DESC else (1, int(hedef[2:]))


def change_summary(
    degisiklikler: Sequence[dict[str, Any]], *, jira_key: str | None, audit_tip: str
) -> str:
    """Jira'ya yazılan değişiklik özeti yorumu (deterministik metin).

    Her değişiklik numaralı listenin TEK satırıdır (Jira ADF'de tek `orderedList`; ara satır
    listeyi bölmez). Bulgu etiketleri portaldakiyle aynıdır: ``F2 (tur 1)``.
    """
    satirlar = [
        "[AI-generated] Testing Probe — doküman düzeltmesi uygulandı"
        + (f" ({jira_key})" if jira_key else ""),
        "Analistin onayladığı düzeltmeler açıklama/kabul kriterlerine yazıldı. Önceki sürüm Jira "
        "geçmişinde durur. Yalnızca aşağıdaki maddeler değişti; diğerleri aynen korunur.",
        "",
    ]
    for i, d in enumerate(degisiklikler, start=1):
        once = _tek_satir(d["once"]) if d["once"] is not None else "(yok — yeni madde)"
        satirlar.append(
            f"{i}. {d['hedef']} — bulgu {', '.join(d['bulgular'])} · Önce: {once} → Sonra: "
            f"{_tek_satir(d['sonra'])}"
        )
    satirlar += [
        "",
        "PO teyidi yeniden gerekiyor (tp-po-pending).",
        f"Denetim zinciri: {audit_tip}",
    ]
    return "\n".join(satirlar)


def _tek_satir(metin: str) -> str:
    return " / ".join(p.strip() for p in str(metin).splitlines() if p.strip())
