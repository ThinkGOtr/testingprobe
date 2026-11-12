"""Onarım PR'ının başlığı ve açıklaması (Türkçe; deterministik şablon, model yok).

Açıklama: hata, eşleşen sinyaller, eski → yeni testId, yoklama (dört sha alanı), son yeşil aria
kanıtı, AST koruması sonucu, yerel kontrol, "AI üretimi: hayır" ve denetim zinciri başı
(Constitution VIII: zincirin son hash'i PR açıklamasına sabitlenir).

Güvenilmeyen metinler (test adı, hata imzası, yoklamanın okuduğu değerler) satır içi kod olarak ve
kırpılarak basılır; Markdown/HTML enjeksiyonu için ters tırnak ve satır sonları temizlenir.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MAX_GOVDE = 60_000


def _kod(deger: Any, n: int = 200) -> str:
    metin = " ".join(str(deger if deger is not None else "—").split())[:n]
    return "`" + metin.replace("`", "'") + "`"


def pr_basligi(k: Mapping[str, Any]) -> str:
    loc = k.get("locator") or {}
    ad = loc.get("tam_ad") or loc.get("anahtar") or "locator"
    return f"fix(locators): {ad} testId {k.get('eski_test_id')} → {k.get('yeni_test_id')}"[:200]


def _sinyaller(k: Mapping[str, Any]) -> list[str]:
    out = []
    for s in k.get("sinyaller") or []:
        if isinstance(s, Mapping):
            out.append(f"- {_kod(s.get('kod'), 60)} {_kod(s.get('aciklama'), 200)}")
        else:
            out.append(f"- {_kod(s)}")
    return out or ["- (triage sinyali kaydedilmemiş)"]


def pr_govdesi(k: Mapping[str, Any]) -> str:
    loc = k.get("locator") or {}
    probe = k.get("probe") or {}
    aria = k.get("aria") or {}
    ast = k.get("ast_guard") or {}
    yk = k.get("yerel_kontrol") or {}
    platform = str(k.get("platform") or "web")
    web_java = platform == "web" and k.get("dil") == "java"
    java = platform != "web" or web_java
    kanit = "hata anı DOM'u" if web_java else "hata anı sayfa kaynağı"
    giris = (
        "Web + Java (Playwright for Java): yalnızca `ekranlar/Kimlikler.java` içindeki ilgili "
        "sabitin testId değeri değişir; sabit adları, niyet ve ekran nesneleri değişmez (011 "
        "§2.8). Test dosyaları ve assertion'lara dokunulmadı (Constitution VI). Merge yalnızca "
        "insan onayıyla yapılır."
        if web_java
        else f"Uygulama ({platform}): yalnızca `ekranlar/Kimlikler.java` içindeki ilgili sabitin "
        "kimlik değeri değişir; sabit adları, niyet ve ekran nesneleri değişmez (009 §2.2). "
        "Test dosyaları ve assertion'lara dokunulmadı (Constitution VI). Merge yalnızca insan "
        "onayıyla yapılır."
        if java
        else "Yalnızca `pages/**/locators.ts` içindeki ilgili `testId` değeri değişir; anahtar "
        "kümesi, rol, ad, niyet ve `within` değişmez. Test dosyaları ve assertion'lara "
        "dokunulmadı (Constitution VI). Merge yalnızca insan onayıyla yapılır."
    )
    satirlar = [
        "## Locator onarımı (bakım yolu, TEKNIK-TASARIM §8.7)",
        "",
        giris,
        "",
        "### Hata",
        f"- Hata analizi: {_kod(k.get('failure_id'))} · koşu {_kod(k.get('run_id'))}",
        f"- Test: {_kod(k.get('test'))}",
        f"- Hata imzası: {_kod(k.get('hata_imzasi'))}",
        "- Sınıf: `test_maintenance/locator` (kural)",
        "",
        "### Eşleşen sinyaller",
        *_sinyaller(k),
        "",
        "### Değişiklik",
        f"- Dosya: {_kod(k.get('dosya'))} · anahtar {_kod(loc.get('tam_ad'))} "
        f"({_kod(loc.get('sinif'))})",
        f"- Rol + ad: {_kod(loc.get('rol'))} {_kod(loc.get('ad'))}"
        + (f" · kapsam {_kod(loc.get('within'))}" if loc.get("within") else ""),
        f"- testId: {_kod(k.get('eski_test_id'))} → {_kod(k.get('yeni_test_id'))}",
        "",
        "```diff",
        str(k.get("fark") or "").replace("```", "'''")[:4000].rstrip(),
        "```",
        "",
        f"### Aday ({kanit})" if java else "### Aday (çalışan uygulamada yoklama)",
        f"- Sayfa: {_kod(probe.get('url_path'))} · kapsayıcı {_kod(k.get('scope_test_id'))}",
        f"- Eşleşme: {_kod(probe.get('matches'))} · okunan testId {_kod(probe.get('test_id'))}",
        f"- Ölçülen: {_kod(probe.get('olculen'))} · uygulama sha {_kod(probe.get('uygulama_sha'))}"
        f" · sha eşleşmesi {_kod(probe.get('sha_eslesmesi'))}",
    ]
    if probe.get("uyari"):
        satirlar.append(f"- Uyarı: {_kod(probe.get('uyari'), 300)}")
    satirlar += [
        "",
        f"### Kanıt doğrulaması ({kanit})" if java else "### Son yeşil doğrulaması (aria)",
        f"- Kaynak: {_kod(aria.get('kaynak'))}"
        + (f" · koşu {_kod(aria.get('run_id'))}" if aria.get("run_id") else "")
        + (f" · {_kod(aria.get('ref'))}" if aria.get("ref") else ""),
        f"- Sonuç: {_kod(aria.get('neden'), 400)}",
        "",
        "### AST koruması (repair, base = main)",
        f"- Sonuç: {'geçti' if ast.get('ok') else 'ihlal'} · ihlal sayısı "
        f"{len(ast.get('violations') or [])}",
        "",
        "### Yerel kontrol (tam paket — etkilenen tüm testler)",
        f"- Sonuç: {_kod(yk.get('sonuc'))} · {_kod(yk.get('ozet'), 300)}",
        f"- Koşu: {_kod(yk.get('run_id'))} · test sayıları {_kod(yk.get('test_sayilari'), 300)}",
        "- Etkilenen testler: "
        + (", ".join(_kod(t, 120) for t in (k.get("etkilenen_testler") or [])[:30]) or "—"),
        "",
        "### İzlenebilirlik",
        "- AI üretimi: **hayır** — aday yoklamayla, yama metin düzeyinde deterministik üretildi "
        "(model çağrısı yok).",
        f"- Dal: {_kod(k.get('dal'))} · head {_kod(k.get('head_sha'))} · "
        f"main {_kod(k.get('main_sha'))}",
        f"- Denetim zinciri başı: {_kod(k.get('denetim_zinciri'))}",
    ]
    return "\n".join(satirlar)[:MAX_GOVDE]
