"""Bug taslağı içeriği: şema doğrulaması, şablon taslak, deterministik düzeltmeler, Jira gövdesi.

İçerik `rules/schemas/bug_draft.schema.json` şemasındadır (§8.12): `summary, steps, expected,
actual, environment, evidence[{kind, ref}], story_key, test_case_key, severity_suggestion,
labels ⊇ ["AI-generated"]`. Testçinin düzenlemesi de aynı şemayla doğrulanır (Constitution III).

Model çıktısı üzerinde deterministik düzeltmeler (XI, VIII'e kayıtlı — `bug_draft_ek.duzeltmeler`):
- `actual` başarısızlığın **literal** gerçekleşen değerini içermek zorunda; içermiyorsa şablonun
  gerçekleşen metni kullanılır (model değeri yuvarlayamaz/uyduramaz).
- `evidence` yalnızca koşunun artefaktlarından gelir; modelin verdiği ve bağlamda olmayan her
  bağlantı atılır (URL uydurulamaz).
- `story_key` / `test_case_key` bağlamdan yazılır; `labels` her zaman `AI-generated` içerir.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator

from tp_core.features.bugs.context import BugContext
from tp_core.integrations import jira_adf as adf
from tp_core.integrations.testmgmt import AI_LABEL

SCHEMA_PURPOSE = "bug_draft"
SEVERITY_PRIORITY = {"critical": "Highest", "major": "High", "minor": "Low"}
ALANLAR = (
    "summary",
    "steps",
    "expected",
    "actual",
    "environment",
    "evidence",
    "story_key",
    "test_case_key",
    "severity_suggestion",
    "labels",
)


class ContentError(ValueError):
    """Taslak içeriği şemaya uymuyor (API 422)."""


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    from tp_core.gateway import find_rules_dir, load_schema

    return Draft202012Validator(load_schema(find_rules_dir(), SCHEMA_PURPOSE))


def schema() -> dict[str, Any]:
    return dict(_validator().schema)


def validation_errors(icerik: Any) -> list[str]:
    hatalar = []
    for e in sorted(_validator().iter_errors(icerik), key=lambda e: list(e.path))[:10]:
        yer = ".".join(str(p) for p in e.path)
        hatalar.append(f"{yer}: {e.message}" if yer else e.message)
    return hatalar


def validate(icerik: Any) -> dict[str, Any]:
    hatalar = validation_errors(icerik)
    if hatalar:
        raise ContentError("Bug taslağı şemaya uymuyor — " + "; ".join(hatalar))
    return dict(icerik)


# ------------------------------------------------------------------------ şablon


def literal_gecer(deger: str | None, metin: object) -> bool:
    """`deger` metinde **ayrı bir belirteç** olarak geçiyor mu?

    Düz alt-dizi denetimi tek haneli demo değerlerinde ("0"/"1") her zaman geçerdi: "P-001" ürün
    kodu ya da "TPD-1" anahtarı iki rakamı da içerir. Değerden önce harf/rakam ya da `-`/`.`/`,`
    (kod, anahtar, ondalık) gelemez; sonra harf/rakam ya da ondalık devamı (`,5`, `.5`) gelemez.
    Cümle sonu noktası, tırnak, iki nokta ve Türkçe ek kesme işareti (`1'den`) serbesttir.
    """
    if not deger:
        return True
    desen = rf"(?<![\w.,\-]){re.escape(deger)}(?!\w)(?![.,]\d)"
    return re.search(desen, str(metin or "")) is not None


def _numarala(adimlar: Sequence[str]) -> list[str]:
    out = []
    for i, a in enumerate(adimlar, start=1):
        metin = str(a).strip()
        out.append(metin if metin[:3].rstrip(".").isdigit() else f"{i}. {metin}")
    return out


def _severity(ctx: BugContext) -> str:
    metin = " ".join(
        p
        for p in (
            ctx.beklenen_deger,
            ctx.gerceklesen_deger,
            ctx.case_beklenen,
            ctx.iddia,
            ctx.gozlem,
        )
        if p
    ).lower()
    if any(k in metin for k in ("tl", "indirim", "bedava", "kredi", "limit", "tutar")):
        return "critical"
    if ctx.severity == "warning":
        return "minor"
    return "major"


def _environment(ctx: BugContext) -> str:
    if ctx.kaynak == "finding":
        return "Doküman tutarlılık denetimi (kod/veri, salt okuma) · yerel demo ortamı"
    parcalar = [f"Yerel demo ortamı ({ctx.run_kaynak or 'local'} koşusu, tetik {ctx.tetik})"]
    if ctx.commit:
        parcalar.append(f"commit {ctx.commit[:12]}")
    parcalar.append("Chromium (Playwright)")
    if ctx.kirma:
        parcalar.append("BREAK_CAMPAIGN açık (kırarak doğrula koşusu)")
    return " · ".join(parcalar)


def template_draft(ctx: BugContext) -> dict[str, Any]:
    """Deterministik taslak (model yokken / REPLAY-MISS'te / şemaya uymayan çıktıda)."""
    if ctx.kaynak == "finding" and ctx.mevcut_icerik:
        return normalize_legacy(ctx.mevcut_icerik, ctx)
    if ctx.kaynak == "finding":
        baslik = f"{ctx.story_key or 'Gereksinim'} {ctx.doc_ref or ''}: {ctx.iddia or ''}"
        adimlar = [f"Dokümandaki beklenen davranışı ({ctx.belge_metni or ctx.doc_ref}) deneyin"]
        if ctx.gozlem:
            adimlar.append(f"Gözlenen: {ctx.gozlem}")
        icerik = {
            "summary": baslik.strip()[:120] or "Doküman ile kod/veri uyumsuz",
            "steps": _numarala(adimlar),
            "expected": ctx.belge_metni or ctx.iddia or "Dokümandaki davranış",
            "actual": ctx.gozlem or "Kod/veri dokümandan farklı davranıyor",
            "environment": _environment(ctx),
            "evidence": list(ctx.kanitlar),
            "story_key": ctx.story_key,
            "test_case_key": None,
            "severity_suggestion": _severity(ctx),
            "labels": [AI_LABEL],
        }
        return validate(icerik)
    alan = ctx.sayfa or "Uygulama"
    konu = ctx.case_baslik or ctx.test_adi or "test"
    if ctx.case_adimlar:
        adimlar = []
        for a in ctx.case_adimlar:
            metin = str(a.get("action") or "").strip()
            if a.get("data"):
                metin += f" (veri: {a['data']})"
            if metin:
                adimlar.append(metin)
    else:
        adimlar = [f'`{ctx.test_dosya or "e2e"}` içindeki "{ctx.test_adi}" testini koşturun']
    if ctx.adim:
        adimlar.append(f"Başarısız adım: {ctx.adim}")
    beklenen = ctx.case_beklenen or "Onaylı test case'in beklenen sonucu"
    if ctx.beklenen_deger and not literal_gecer(ctx.beklenen_deger, beklenen):
        beklenen += f" (beklenen değer: {ctx.beklenen_deger})"
    if ctx.gerceklesen_deger:
        gerceklesen = f"Gerçekleşen değer: {ctx.gerceklesen_deger}"
        if ctx.hata_mesaji:
            gerceklesen += f" — {ctx.hata_mesaji}"
    else:
        gerceklesen = ctx.hata_mesaji or "Test beklenen sonucu vermedi"
    icerik = {
        "summary": f"{alan}: {konu} — beklenen sonuç alınamadı"[:120],
        "steps": _numarala(adimlar or ["Testi koşturun"]),
        "expected": beklenen,
        "actual": gerceklesen,
        "environment": _environment(ctx),
        "evidence": list(ctx.kanitlar),
        "story_key": ctx.story_key,
        "test_case_key": ctx.test_case_key,
        "severity_suggestion": _severity(ctx),
        "labels": [AI_LABEL],
    }
    return validate(icerik)


def normalize_legacy(eski: Mapping[str, Any], ctx: BugContext) -> dict[str, Any]:
    """Faz 2'nin şablon taslağını (requirements `ensure_bug_draft`) şemaya taşır."""
    kanitlar: list[dict[str, str]] = []
    for ev in eski.get("evidence") or []:
        if not isinstance(ev, Mapping):
            continue
        kind = ev.get("kind") or ev.get("tur")
        ref = ev.get("ref") or ev.get("url") or ev.get("etiket")
        if kind in ("code", "data", "log", "trace", "allure", "screenshot", "sauce_video") and ref:
            kanitlar.append({"kind": str(kind), "ref": str(ref)[:300]})
    sev = eski.get("severity_suggestion")
    icerik = {
        "summary": str(eski.get("summary") or "Doküman ile kod/veri uyumsuz")[:120],
        "steps": _numarala([str(a) for a in eski.get("steps") or []] or ["Bulguyu inceleyin"]),
        "expected": str(eski.get("expected") or ctx.belge_metni or ctx.iddia or "-"),
        "actual": str(eski.get("actual") or ctx.gozlem or "-"),
        "environment": str(eski.get("environment") or _environment(ctx)),
        "evidence": kanitlar or list(ctx.kanitlar),
        "story_key": ctx.story_key or eski.get("story_key"),
        "test_case_key": eski.get("test_case_key"),
        "severity_suggestion": sev if sev in SEVERITY_PRIORITY else _severity(ctx),
        "labels": [AI_LABEL],
    }
    return validate(icerik)


# ------------------------------------------------------------ deterministik düzeltme


def apply_guards(
    ai: Mapping[str, Any], ctx: BugContext, sablon: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Model taslağına deterministik kurallar; (son içerik, uygulanan düzeltmeler)."""
    out = {k: ai.get(k) for k in ALANLAR}
    duzeltmeler: list[dict[str, Any]] = []

    def duzelt(alan: str, neden: str, yeni: Any) -> None:
        if out.get(alan) != yeni:
            duzeltmeler.append({"alan": alan, "neden": neden, "once": out.get(alan), "sonra": yeni})
            out[alan] = yeni

    for deger in ctx.literal_values():
        if not literal_gecer(deger, out.get("actual")):
            duzelt(
                "actual",
                f"gerçekleşen değer ({deger}) başarısızlıktaki literal değerle aynı olmalı",
                sablon["actual"],
            )
            break
    if ctx.beklenen_deger and not literal_gecer(ctx.beklenen_deger, out.get("expected")):
        duzelt(
            "expected",
            f"beklenen değer ({ctx.beklenen_deger}) onaylı case / test beklentisiyle aynı olmalı",
            sablon["expected"],
        )
    izinli = {(k["kind"], k["ref"]) for k in ctx.kanitlar}
    kanit = [
        {"kind": e.get("kind"), "ref": e.get("ref")}
        for e in out.get("evidence") or []
        if isinstance(e, Mapping) and (e.get("kind"), e.get("ref")) in izinli
    ]
    for k in ctx.kanitlar:
        if (k["kind"], k["ref"]) not in {(e["kind"], e["ref"]) for e in kanit}:
            kanit.append(dict(k))
    duzelt("evidence", "kanıt yalnızca koşunun/bulgunun kendi kayıtlarından", kanit)
    duzelt("story_key", "story anahtarı bağlamdan", ctx.story_key)
    duzelt(
        "test_case_key",
        "Test issue anahtarı yayın kaydından",
        ctx.test_case_key if ctx.kaynak == "failure" else None,
    )
    etiketler = [str(x) for x in out.get("labels") or [] if isinstance(x, str)]
    if AI_LABEL not in etiketler:
        duzelt("labels", "AI-generated etiketi zorunlu", [AI_LABEL, *etiketler])
    if out.get("severity_suggestion") not in SEVERITY_PRIORITY:
        duzelt("severity_suggestion", "geçersiz önem önerisi", sablon["severity_suggestion"])
    if not isinstance(out.get("summary"), str) or not out["summary"].strip():
        duzelt("summary", "özet boş", sablon["summary"])
    else:
        out["summary"] = out["summary"][:120]
    if validation_errors(out):
        return dict(sablon), [{"alan": "*", "neden": "model taslağı şemaya uymadı; şablon"}]
    return out, duzeltmeler


# ------------------------------------------------------------ insan düzenlemesi


def _anahtar_mi(deger: object) -> bool:
    from tp_core.features.bugs.jql import is_issue_key

    return is_issue_key(deger)


def check_human_edit(yeni: Mapping[str, Any], mevcut: Mapping[str, Any], ctx: BugContext) -> None:
    """Testçinin düzenlemesine bağlam korumaları (`apply_guards`'ın insan karşılığı).

    İzlenebilirlik alanları (story / Test issue) ve kanıtın kökeni düzenlenemez: düzenleme bunları
    değiştirirse `ContentError` (API 422). Kanıt yalnızca koşunun/bulgunun kendi kayıtlarından
    (bağlam) ya da taslakta zaten olanlardan seçilebilir; kanıt çıkarmak serbesttir.
    """
    hatalar: list[str] = []
    if yeni.get("story_key") not in {ctx.story_key, mevcut.get("story_key")}:
        hatalar.append(
            f"story_key düzenlenemez (bağlamdan: {ctx.story_key or mevcut.get('story_key') or '-'})"
        )
    tc_baglam = ctx.test_case_key if ctx.kaynak == "failure" else None
    tc_izinli = {tc_baglam, mevcut.get("test_case_key")}
    tc = yeni.get("test_case_key")
    if tc is not None and not _anahtar_mi(tc):
        hatalar.append("test_case_key geçerli bir Jira anahtarı olmalı (ör. TPD-12)")
    elif tc not in tc_izinli:
        hatalar.append(f"test_case_key düzenlenemez (yayın kaydından: {tc_baglam or 'yok'})")
    izinli = {(k.get("kind"), k.get("ref")) for k in ctx.kanitlar}
    izinli |= {
        (e.get("kind"), e.get("ref"))
        for e in mevcut.get("evidence") or []
        if isinstance(e, Mapping)
    }
    yabanci = [
        str(e.get("ref"))
        for e in yeni.get("evidence") or []
        if isinstance(e, Mapping) and (e.get("kind"), e.get("ref")) not in izinli
    ]
    if yabanci:
        hatalar.append(
            "kanıt yalnızca koşunun/bulgunun kendi kayıtlarından seçilebilir; eklenemez: "
            + ", ".join(yabanci[:3])
        )
    if hatalar:
        raise ContentError("Bug taslağı düzenlemesi reddedildi — " + "; ".join(hatalar))


# ------------------------------------------------------------------- Jira kanıtı

_KOD_REF = re.compile(r"^(?P<path>[A-Za-z0-9_./-]+):(?P<line>\d+)$")

# (tür, görünen metin, bağlantı | None)
KanitSatiri = tuple[str, str, str | None]


def public_evidence(
    evidence: Sequence[Mapping[str, Any]] | None,
    *,
    base_url: str,
    kod_sha: str | None = None,
    kod_url: Callable[[str, Any, str | None], str | None] | None = None,
) -> list[KanitSatiri]:
    """Jira'ya yazılacak kanıt satırları: portal artefaktı mutlak URL, kod commit'e sabit.

    İçerikteki `ref` değişmez (portal göreli yolu kullanır, onaylanan hash aynı kalır); bu
    yalnızca Jira gövdesinin görünümüdür.
    """
    out: list[KanitSatiri] = []
    for e in evidence or []:
        if not isinstance(e, Mapping):
            continue
        kind, ref = str(e.get("kind") or ""), str(e.get("ref") or "")
        if not ref:
            continue
        if ref.startswith("/api/"):
            url = base_url.rstrip("/") + ref
            out.append((kind, url, url))
        elif ref.startswith(("https://", "http://")):
            out.append((kind, ref, ref))
        elif kind == "code" and (m := _KOD_REF.fullmatch(ref)):
            url = kod_url(m["path"], m["line"], kod_sha) if kod_url else None
            if url:
                out.append((kind, ref, url))
            elif kod_sha:
                out.append((kind, f"{ref} (demo-app @ commit {kod_sha[:12]})", None))
            else:
                out.append((kind, ref, None))
        else:
            out.append((kind, ref, None))
    return out


def _kanit_satirlari(
    icerik: Mapping[str, Any], kanit: Sequence[KanitSatiri] | None
) -> list[KanitSatiri]:
    if kanit is not None:
        return list(kanit)
    return [
        (str(e["kind"]), str(e["ref"]), None)
        for e in icerik.get("evidence") or []
        if isinstance(e, Mapping)
    ]


def _kanit_listesi(satirlar: Sequence[KanitSatiri]) -> dict[str, Any]:
    ogeler = []
    for kind, metin, url in satirlar:
        parca: list[dict[str, Any]] = [{"type": "text", "text": f"{kind}: "}]
        dugum: dict[str, Any] = {"type": "text", "text": metin}
        if url:
            dugum["marks"] = [{"type": "link", "attrs": {"href": url}}]
        parca.append(dugum)
        ogeler.append({"type": "listItem", "content": [{"type": "paragraph", "content": parca}]})
    return {"type": "bulletList", "content": ogeler}


# ------------------------------------------------------------------- Jira gövdesi


def description_adf(
    icerik: Mapping[str, Any],
    *,
    draft_label: str,
    onaylayan: str | None,
    mod_etiketi: str,
    icerik_hash: str,
    zincir_hash: str | None,
    kanit: Sequence[KanitSatiri] | None = None,
) -> dict[str, Any]:
    kokeni = (
        f"Bu kayıt Testing Probe tarafından taslaklandı (üretim: {mod_etiketi}) ve "
        f"testçi onayıyla açıldı; onaylayan: {onaylayan or '?'}."
    )
    content: list[dict[str, Any]] = [adf.paragraph(kokeni)]
    content += [adf.heading("Adımlar", 3), adf.bullet_list(list(icerik["steps"]), ordered=True)]
    content += [adf.heading("Beklenen", 3), adf.paragraph(str(icerik["expected"]))]
    content += [adf.heading("Gerçekleşen", 3), adf.paragraph(str(icerik["actual"]))]
    content += [adf.heading("Ortam", 3), adf.paragraph(str(icerik["environment"]))]
    satirlar = _kanit_satirlari(icerik, kanit)
    if satirlar:
        content += [adf.heading("Kanıt", 3), _kanit_listesi(satirlar)]
    iz = [f"Story: {icerik.get('story_key') or '-'}"]
    if icerik.get("test_case_key"):
        iz.append(f"Test: {icerik['test_case_key']}")
    iz.append(f"Önem önerisi: {icerik.get('severity_suggestion')}")
    iz.append(f"Kimlik: {draft_label}")
    iz.append(f"onaylanan içerik hash: {icerik_hash}")
    if zincir_hash:
        iz.append(f"denetim zinciri son hash: {zincir_hash}")
    content.append(adf.paragraph(" · ".join(iz)))
    return adf.doc(content)


def link_comment(
    icerik: Mapping[str, Any],
    *,
    draft_label: str,
    onaylayan: str | None,
    mod_etiketi: str,
    icerik_hash: str,
    zincir_hash: str | None,
    kanit: Sequence[KanitSatiri] | None = None,
) -> dict[str, Any]:
    """'Mevcut kayda bağla' yorumu (ADF): kanıtlar tıklanabilir bağlantı (`link` işareti) taşır."""
    content: list[dict[str, Any]] = [
        adf.paragraph(
            f"Testing Probe: Bu hata yeniden gözlendi ({draft_label}). "
            f"Testçi ({onaylayan or '?'}) taslağı bu kayda bağladı; yeni kayıt açılmadı."
        ),
        adf.paragraph(f"Üretim: {mod_etiketi} (AI-generated taslak, insan onaylı)."),
        adf.paragraph(f"Özet: {icerik.get('summary')}"),
        adf.paragraph(f"Beklenen: {icerik.get('expected')}"),
        adf.paragraph(f"Gerçekleşen: {icerik.get('actual')}"),
        adf.paragraph(f"Ortam: {icerik.get('environment')}"),
    ]
    satirlar = _kanit_satirlari(icerik, kanit)
    if satirlar:
        content.append(adf.paragraph("Kanıt:"))
        content.append(_kanit_listesi(satirlar))
        if any(url and "/api/artifacts/" in url for _, _, url in satirlar):
            content.append(
                adf.paragraph("Not: Kanıt bağlantıları Testing Probe portalında oturum ister.")
            )
    iz = f"Story: {icerik.get('story_key') or '-'}"
    if icerik.get("test_case_key"):
        iz += f" · Test: {icerik['test_case_key']}"
    content.append(adf.paragraph(iz))
    content.append(adf.paragraph(f"onaylanan içerik hash: {icerik_hash}"))
    if zincir_hash:
        content.append(adf.paragraph(f"denetim zinciri son hash: {zincir_hash}"))
    return adf.doc(content)


def link_comment_text(icerik: Mapping[str, Any], **ortak: Any) -> str:
    """ADF yorumu desteklemeyen istemci için düz metin karşılığı (bağlantılar URL olarak kalır)."""
    return adf.adf_to_text(link_comment(icerik, **ortak))
