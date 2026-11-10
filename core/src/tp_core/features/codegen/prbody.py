"""PR açıklaması (TEKNIK-TASARIM §8.4 adım 6; Constitution VIII): case, Jira, doğrulama özeti,
yerel kontrol sonucu, "AI-generated" ve PR anındaki denetim zinciri başı.

Case metni ve ajan kanıtı güvenilmeyen girdidir; tablo hücrelerine tek satır ve kırpılmış girer.

- Düz metin hücreleri (`hucre`): `\\`, `|`, `` ` ``, `<>` yanında Markdown işaretleri `[ ] * _ ~ #`
  ters bölüyle kaçışlanır. `[`/`]` kaçışlı olduğundan bağlantı ve görsel (`[x](u)`, `![x](u)`)
  hiç oluşmaz; bu yüzden `(`, `)` ve `!` tek başına etkisizdir ve okunurluk için kaçışlanmaz.
  `@` sonrasına sıfır genişlikli boşluk eklenir: GitHub `@kişi` / `@org/takım` bahsetmesi ve
  bildirimi oluşmaz.
- Kod hücreleri (`kod`) satır içi kod aralığına girer (Markdown/HTML/bahsetme orada işlenmez);
  yalnızca `` ` `` ve `|` etkisizleştirilir.
- PR başlığı (`pr_title`) düz metindir (GitHub başlıkta Markdown işlemez): tek satıra indirgenir.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from tp_core.features.codegen.render import ts_literal

MAX_BODY = 60000
# Kontrol karakterleri, satır ayırıcıları, sıfır genişlik ve yön (bidi) denetimleri.
_KONTROL = re.compile(
    "[\\x00-\\x1f\\x7f\\u2028\\u2029\\u200b-\\u200f\\u202a-\\u202e\\u2066-\\u2069]"
)
_MD = re.compile(r"([\[\]*_~#])")
_SIFIR_GENISLIK = "\u200b"


def _tek_satir(value: Any, limit: int) -> str:
    metin = _KONTROL.sub(" ", str(value if value is not None else "")).strip()
    metin = re.sub(r"\s+", " ", metin)
    return metin if len(metin) <= limit else metin[: limit - 1] + "…"


def hucre(value: Any, limit: int = 160) -> str:
    """Düz metin tablo hücresi: bağlantı/görsel/HTML oluşmaz, bahsetme bildirimi gitmez."""
    metin = _tek_satir(value, limit)
    metin = metin.replace("\\", "\\\\").replace("|", "\\|").replace("`", "'")
    metin = metin.replace("<", "&lt;").replace(">", "&gt;")
    metin = _MD.sub(r"\\\1", metin)
    return metin.replace("@", "@" + _SIFIR_GENISLIK)


def kod(value: Any, limit: int = 160) -> str:
    """Satır içi kod aralığının içeriği (çağıran `` ` `` ile sarar)."""
    return _tek_satir(value, limit).replace("`", "'").replace("|", "\\|")


def cagri(item: Mapping[str, Any]) -> str:
    args = ", ".join(ts_literal(a) for a in item.get("args") or [])
    return f"{item.get('po')}.{item.get('method')}({args})"


def _dogrulandi(m: Mapping[str, Any], ajan_bayileri: Mapping[str, str]) -> str:
    if not m.get("verified"):
        return "✗"
    bayi = next((a for a in m.get("args") or [] if isinstance(a, str) and a in ajan_bayileri), None)
    if bayi is None:
        return "✓"
    return hucre(f"✓ (ajan bayisi {ajan_bayileri[bayi]} ile; test {bayi} ile koşar)", 120)


def _link(key: str | None, browse_url: str | None) -> str:
    if not key:
        return "-"
    if browse_url:
        return f"[{hucre(key, 40)}]({browse_url.rstrip('/')}/browse/{kod(key, 40)})"
    return hucre(key, 40)


def pr_title(case_ref: str, title: str, platform: str = "web") -> str:
    etiket = _tek_satir(case_ref, 40) + ("" if platform == "web" else f" · {platform}")
    metin = f"[{etiket}] {_tek_satir(title, 100)} (AI-generated)"
    return metin[:200]


def pr_body(
    *,
    case_id: str,
    case_ref: str,
    case: Mapping[str, Any],
    case_hash: str,
    onaylayan: str | None,
    story_key: str | None,
    test_key: str | None,
    browse_url: str | None,
    mode_label: str,
    bundle_hash: str | None,
    repo_path: str,
    mapping: Mapping[str, Any],
    kaynaklar: Sequence[str | None],
    kontrol: Mapping[str, Any] | None,
    duzeltme_turu: int,
    agent_dealer_note: str | None,
    audit_head: str,
    template_hash: str,
    mapping_hash: str,
    ajan_bayileri: Mapping[str, str] | None = None,
    platform: str = "web",
) -> str:
    """`ajan_bayileri`: doğrulama ajanının araç katmanında yerine geçirdiği bayiler
    (`{"bayi1": "bayi3"}`); bu bayiyi argüman alan eşleme satırları açıkça işaretlenir.
    `platform` (009 §2.1): `web` dışında Java/Appium testi (ekran nesnesi, app-mcp ajanı)."""
    adimlar = {str(s.get("id")): s for s in case.get("steps") or [] if isinstance(s, Mapping)}
    uygulama = platform != "web"
    giris = (
        "> Bu PR AI Testing Probe tarafından açıldı (**AI-generated**). Model Java yazmadı: "
        f"kod, uygulamada ({hucre(platform, 20)}, app-mcp) doğrulanmış adım → ekran nesnesi "
        "eşlemesinden şablonla üretildi. Merge yalnızca insan onayıyla ve zorunlu kontroller "
        "yeşilken yapılır."
        if uygulama
        else "> Bu PR AI Testing Probe tarafından açıldı (**AI-generated**). Model TypeScript "
        "yazmadı: kod, uygulamada doğrulanmış adım → page object eşlemesinden şablonla üretildi. "
        "Merge yalnızca insan onayıyla ve zorunlu kontroller yeşilken yapılır."
    )
    out: list[str] = [
        f"## AI-generated test: {hucre(case_ref, 40)} — {hucre(case.get('title'), 120)}",
        "",
        giris,
        "",
        "| Alan | Değer |",
        "|---|---|",
        f"| Case | `{kod(case_id, 40)}` ({hucre(case_ref, 40)}) |",
        *([f"| Platform | {hucre(platform, 20)} |"] if uygulama else []),
        f"| Onaylı case hash | `{kod(case_hash, 64)}` |",
        f"| Case onaylayan | {hucre(onaylayan or '-', 60)} |",
        f"| Story | {_link(story_key, browse_url)} |",
        f"| Jira Test | {_link(test_key, browse_url)} |",
        f"| Üretim modu | {hucre(mode_label, 120)} |",
        f"| Bundle hash | `{kod(bundle_hash or '-', 64)}` |",
        f"| Dosya | `{kod(repo_path, 120)}` |",
        f"| Eşleme / şablon hash | `{kod(mapping_hash[:16], 20)}` / "
        f"`{kod(template_hash[:16], 20)}` |",
        "",
        "### Doğrulama özeti (adım → ekran nesnesi)"
        if uygulama
        else "### Doğrulama özeti (adım → page object)",
        "",
        "| Adım | Eylem | Eşleme | Doğrulandı | Kanıt |",
        "|---|---|---|---|---|",
    ]
    for m in mapping.get("step_mapping") or []:
        sid = str(m.get("step_id"))
        out.append(
            f"| {hucre(sid, 8)} | {hucre((adimlar.get(sid) or {}).get('action'), 80)} | "
            f"`{kod(cagri(m), 100)}` | {_dogrulandi(m, ajan_bayileri or {})} | "
            f"{hucre(m.get('evidence_ref') or '-', 80)} |"
        )
    out += [
        "",
        "### Beklenen sonuç doğrulamaları (değer kaynağı: onaylı case metni)",
        "",
        "| Doğrulama | Kaynak metin |",
        "|---|---|",
    ]
    for i, e in enumerate(mapping.get("expects") or []):
        kaynak = kaynaklar[i] if i < len(kaynaklar) else None
        out.append(f"| `{kod(cagri(e), 100)}` | {hucre(kaynak or '-', 120)} |")
    out += ["", "### Yerel kontrol", ""]
    if not kontrol:
        out.append("- Yerel kontrol yapılmadı.")
    else:
        adim = kontrol.get("adimlar") or {}

        def isaret(v: Any) -> str:
            return "✓" if v is True else ("✗" if v is False else "—")

        if uygulama:
            out.append(
                f"- pom kilidi {isaret(adim.get('deps'))} · Java AST koruması "
                f"{isaret(adim.get('guard'))} · test-compile {isaret(adim.get('compile'))} · "
                f"Appium ({hucre(platform, 20)}) {kontrol.get('gecen', 0)}/"
                f"{kontrol.get('toplam', 0)} geçti (repeat-each=3, retries=0)"
            )
        else:
            out.append(
                f"- tsc {isaret(adim.get('tsc'))} · eslint {isaret(adim.get('eslint'))} · "
                f"AST koruması {isaret(adim.get('ast_guard'))} · Playwright "
                f"{kontrol.get('gecen', 0)}/{kontrol.get('toplam', 0)} geçti "
                "(repeat-each=3, retries=0)"
            )
        out.append(f"- Sonuç: **{hucre(kontrol.get('aciklama'), 200)}**")
        if kontrol.get("run_id"):
            out.append(f"- Koşu: `{kod(kontrol.get('run_id'), 100)}`")
    if duzeltme_turu:
        out.append(
            f"- Eşleme düzeltme turu: {duzeltme_turu} (yalnızca locator/eşleme; beklenen "
            "değerler değişmedi)."
        )
    if agent_dealer_note:
        out.append(f"- {hucre(agent_dealer_note, 300)}")
    out += [
        "",
        "### Denetim",
        "",
        f"- Denetim zinciri başı (PR anı): `{kod(audit_head, 64)}`",
        "- Etiketler: `AI-generated`. CI'da AI yok: bu test yalnızca deterministik olarak koşar.",
    ]
    govde = "\n".join(out) + "\n"
    return govde if len(govde) <= MAX_BODY else govde[: MAX_BODY - 20] + "\n…(kırpıldı)\n"
