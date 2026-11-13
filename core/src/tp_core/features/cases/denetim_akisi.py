"""Case seti denetimi (P9; specs/011 F5, K2, K3) ve yayın kapısı.

Akış:

1. `request_audit` (`POST /requirements/{id}/case-audit`, analist, "Agent Probe'a gönder"):
   gereksinim `cases_ready|done` ve PO onayı güncel; setin v3 case'i var; aynı set için review
   sürmüyor; ve **güncel setin review'u tamamlanmış ya da setin en az bir onaylı v3 case'i
   var**. Gerekçe: P9, P8'i girdi olarak alır (tamamlanmış review en iyi girdi); review
   başarısız olduysa ya da hiç çalışmadıysa analist kalıcı olarak kilitlenmesin, ama denetime
   insan incelemesinden geçmemiş bir set gitmesin (en az bir onay = analist seti gördü). Aynı
   set için bekleyen denetim varsa o döner.
2. `run_audit` (core-worker, `cases.audit`): istek (`ports.CaseSetAuditRequest`) kurulur ve
   Agent Probe portuna gider (`get_agent_probe().audit_case_set`; bugün geçitte `case_audit`,
   Opus). Port hatası (erişilemiyor, REPLAY-MISS, model hatası) karar ÜRETMEZ: satır `hata` olur,
   yayın kapısı kapalı kalır (fail-closed).
3. Deterministik sertleştirme (Constitution XI; `deterministic_findings` + `harden`): kodda
   denetlenebilen ihlaller kararın ALT SINIRIDIR. Model KABUL dese bile karar en az bu sınırdır;
   model daha sert karar verdiyse o geçerlidir (kod yumuşatamaz). `model_karari` ve `karar`
   ayrı kolonlardır; kurallar `icerik.deterministik_bulgular`'dadır.
4. Yayın kapısı (K3; `gate_check`, `publish.set_gate_check` ile bağlanır): `TP_DENETIM_KAPISI`
   (`on` varsayılan | `off`). Açıkken v3 case, gereksinimin GÜNCEL `set_hash`'ine ait son
   tamamlanmış denetim KABUL değilse yayınlanmaz. Set değişince karar bayat olur.
"""

from __future__ import annotations

import fnmatch
import os
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.events.bus import publish_tx
from tp_core.features.cases import review as review_mod
from tp_core.models import CaseSetAudit, Requirement, TestCase, session_scope
from tp_core.ports import CaseSetAuditRequest, CaseSetAuditResult
from tp_core.workflow.jobs import JobContext, PermanentJobError, enqueue
from tp_core.workflow.service import Principal, WorkflowError

AUDIT_JOB = "cases.audit"
KABUL, DUZELTME, ENGELLE = "KABUL", "DÜZELTME_GEREKLİ", "ENGELLE"
SIDDET = {KABUL: 0, DUZELTME: 1, ENGELLE: 2}
KAPI_ORTAMI = "TP_DENETIM_KAPISI"
# Gereksinim başına 24 saatlik denetim sınırı (Opus çağrısı; maliyet, 011 D1 #8).
DENETIM_SINIRI_ORTAMI = "TP_DENETIM_GUNLUK_SINIR"
DENETIM_VARSAYILAN_SINIR = 10
# `session.info` anahtarı: yayın kapısı durumu gereksinim başına bir kez hesaplanır (önizleme,
# yayın işi; `features.publish`).
KAPI_ONBELLEGI = "denetim_kapisi_onbellegi"
KAYNAKLAR = frozenset({"tp-gecit", "agent-probe", "sim"})
POLITIKA_DOSYASI = Path("agent-probe") / "politikalar.md"


class AuditNotAllowed(WorkflowError):
    status_code = 409


# ---------------------------------------------------------------- kurum politikaları


def _rules_dir() -> Path:
    from tp_core.gateway import find_rules_dir

    return find_rules_dir()


def _bolum(metin: str, baslik: str) -> list[str]:
    """`## <baslik>` bölümündeki madde imli satırlar (sonraki `## `'e kadar)."""
    out: list[str] = []
    icinde = False
    for satir in metin.splitlines():
        if satir.startswith("## "):
            icinde = satir[3:].strip() == baslik
            continue
        if icinde and satir.lstrip().startswith("- "):
            out.append(satir.lstrip()[2:].strip())
    return out


@lru_cache(maxsize=4)
def _politika_metni(yol: str) -> str:
    p = Path(yol)
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def policies(rules_dir: Path | None = None) -> list[str]:
    """Kurum politikaları (denetim girdisi; `rules/agent-probe/politikalar.md`, varsayılan)."""
    yol = (rules_dir or _rules_dir()) / POLITIKA_DOSYASI
    return _bolum(_politika_metni(str(yol)), "Politikalar")


def allowed_hosts(rules_dir: Path | None = None) -> list[str]:
    """İzinli test ortamları (deterministik ortam kontrolü; fnmatch desenleri)."""
    yol = (rules_dir or _rules_dir()) / POLITIKA_DOSYASI
    return [h.lower() for h in _bolum(_politika_metni(str(yol)), "İzinli test ortamları")]


# ------------------------------------------------------- deterministik kurallar (XI)

# Saldırı metni imzaları (prompt injection, XSS, SQLi). Yüksek kesinlikli, dar desenler: amaç
# işaretsiz ya da yanlış yere yazılmış saldırı verisini yakalamaktır, güvenlik taraması değil.
SALDIRI_DESENLERI = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"(önceki|onceki|yukarıdaki|tüm|bütün)\s+(tüm\s+|bütün\s+)?talimat\w*\s+(yok\s+say|unut|görmezden)",
        r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+instructions",
        r"<\s*script\b",
        r"javascript\s*:",
        r"\bon(error|load)\s*=",
        r"'\s*or\s+'?1'?\s*=\s*'?1",
        r"\bunion\s+(all\s+)?select\b",
        r"\bdrop\s+table\b",
    )
)
# Denetçiye / denetim kararına yönelik gömülü talimat (karar kuralı: ENGELLE). Yalnız emir /
# istek kipleri yakalanır ("onayla", "onaylasın", "KABUL ver", "approve"); iş akışını anlatan
# geniş zaman ("Denetçi siparişi onaylar") ve tırnak içi ya da düğme/menü adı olan UI etiketi
# ("Denetçi 'Onayla' butonuna basar") talimat sayılmaz (`_ui_etiketsiz`). Ürünün kendi "Denetçi"
# rolü olabilir: yalın "denetçi" öznesinde emrin hedefi set / çıktı / case / denetim / karar
# olmalıdır ("denetçi bu seti onayla"); yapay zekâ denetim katmanı öznesinde her emir sayılır.
_AI_DENETCI = (
    r"(?:agent\s*probe\w*|denetim\s+(?:model|katman|ajan|karar)\w*|auditor\w*"
    r"|audit\s+(?:model|layer)\w*|(?:ai|yapay\s+zek\w*)\s+denet\w*)"
)
_DENETCI = r"(?:denetçi\w*|denetci\w*|denetleyici\w*)"
_HEDEF = r"(?:set\w*|çıktı\w*|cikti\w*|case\w*|vaka\w*|denetim\w*|karar\w*|output|result)"
_EMIR = (
    r"(?:onayla(?:sın|sin|yın|yin|yınız|yiniz)?|onay\s+ver(?:sin|in)?"
    r"|kabul\s+(?:et(?:sin|in)?|edin|edilsin|ver(?:sin|in)?|döndür\w*|yaz(?:sın|ın)?)"
    r"|engellemesin|engellemeyin|approve)"
)
_UI_SONRASI = r"(?!\s*(?:butonu|buton|düğme|tuş|sekme|menü|bağlantı|link|seçene)\w*)"
_SOZ = r"(?:\w+\W+)"
DENETCIYE_TALIMAT = re.compile(
    rf"\b{_AI_DENETCI}\W+{_SOZ}{{0,6}}?{_EMIR}\b{_UI_SONRASI}"
    rf"|\b{_DENETCI}\W+{_SOZ}{{0,6}}?{_HEDEF}\W+{_SOZ}{{0,3}}?{_EMIR}\b{_UI_SONRASI}"
    # Öznesiz karar emri: büyük harfli karar belirteci + emir ("KABUL ver", "decision: KABUL").
    r"|(?-i:\bKABUL\b)\s+(?:ver|verin|versin|döndür\w*|yaz|yazın|yazsın|de|deyin)\b"
    r"|(?-i:\bENGELLE\b)\s+verme(?:sin|yin)?\b"
    r"|\bdecision\W{0,3}(?-i:KABUL)\b",
    re.IGNORECASE,
)
# Tırnak içi kısa metin (UI etiketi: 'Onayla', "Kabul et"); talimat aranmadan önce çıkarılır.
_TIRNAKLI = re.compile(r"[\"'‘’“”«»][^\"'‘’“”«»\n]{1,40}[\"'‘’“”«»]")
# Şemalı hedef: http(s), ws(s), ftp(s), sftp; kullanıcı bilgisi (`user:parola@`) atlanır.
URL_DESENI = re.compile(
    r"\b(?:https?|wss?|ftps?|sftp)://(?:[^/\s@\"'<>)]*@)?([^/\s:\"'<>)@]+)", re.IGNORECASE
)
# Şemasız ana makine (`evil.com/api`, `www.ornek.com`): en az iki etiket, harfli üst alan adı,
# ardından yol ya da `www.` öneki. E-posta alan adı (`@` sonrası) ve URL içindeki ad sayılmaz.
SEMASIZ_HOST = re.compile(
    r"(?<![@\w./:-])((?:www\.)?(?:[a-z0-9-]+\.)+[a-z]{2,})(?=(?::\d+)?/)"
    r"|(?<![@\w./:-])(www\.(?:[a-z0-9-]+\.)+[a-z]{2,})\b",
    re.IGNORECASE,
)
# Yolsuz ve `www`'siz ana makine (`prod.firma.com`, tur 2 güvenlik #15): en az üç etiket ve
# yaygın üst alan adı. Ters alan adı biçimi (`com.firma.app`, paket/bundle kimliği) ve ilk etiketi
# tümüyle rakam olan ad (`2.1.0.dev` sürümü) sayılmaz (tur 3 güvenlik #5).
SEMASIZ_ALT_ALAN = re.compile(
    r"(?<![@\w./:-])(?!(?:com|net|org|io|tr|de|uk|co|gov|edu)\.)(?!\d+\.)"
    r"((?:[a-z0-9-]+\.){2,}"
    r"(?:com|net|org|io|co|app|ai|dev|cloud|internal|corp|lan|local|gov|edu|tr))"
    r"(?![\w.-]*\w)",
    re.IGNORECASE,
)
# Kod/anahtar adlarıyla karışan üst alan adları (`Sepet.toplam.tr` i18n anahtarı, `rapor.v2.dev`):
# bu adlar yalnız ana makine bağlamı varsa sayılır: ikinci düzey kayıt adı (`firma.com.tr`), ortam
# öneki (`staging.…`, `api.…`) ya da yakında ana makine sözcüğü (sunucu, ortam, host, URL…).
_BELIRSIZ_UST_ALAN = frozenset({"dev", "tr", "local", "lan"})
_IKINCI_DUZEY = frozenset({"com", "net", "org", "gov", "edu", "co", "k12", "bel", "gen", "biz"})
_ORTAM_ONEKI = frozenset(
    {"www", "api", "staging", "stage", "prod", "preprod", "uat", "test", "qa", "dev", "admin"}
)
_HOST_BAGLAMI = re.compile(
    r"(?<!\w)(?:https?|url\w*|host\w*|sunucu\w*|server\w*|ortam\w*|environment\w*|env"
    r"|endpoint\w*|adres\w*|domain\w*|alan\s+ad\w*|bağlan\w*|baglan\w*|eriş\w*|eris\w*"
    r"|ping|dns)(?!\w)",
    re.IGNORECASE,
)
_BAGLAM_PENCERESI = 60


def _alt_alan_host_mu(metin: str, m: re.Match[str]) -> bool:
    etiketler = m.group(1).lower().split(".")
    if etiketler[-1] not in _BELIRSIZ_UST_ALAN:
        return True
    if etiketler[-2] in _IKINCI_DUZEY or etiketler[0] in _ORTAM_ONEKI:
        return True
    pencere = metin[max(0, m.start() - _BAGLAM_PENCERESI) : m.end() + _BAGLAM_PENCERESI]
    return _HOST_BAGLAMI.search(pencere) is not None


# Şemasız IP (`10.0.0.5/admin`, `10.0.0.5:8080`): ardından yol ya da port gelmeli (tutar ya da
# sürüm numarası yanlış pozitif vermesin); oktetler `hosts_in`'de doğrulanır.
SEMASIZ_IP = re.compile(r"(?<![\w.@/:-])(\d{1,3}(?:\.\d{1,3}){3})(?=:\d+|/)")


def _ip_gecerli(ip: str) -> bool:
    oktetler = ip.split(".")
    return all(o == "0" or (not o.startswith("0") and int(o) <= 255) for o in oktetler)


# Gizlilik (KVKK): geçerli sağlama toplamlı kimlik/ödeme numaraları ve genel e-posta sağlayıcısı.
KART_DESENI = re.compile(r"(?<![\d.,])\d(?:[ -]?\d){12,18}(?![\d]|[.,]\d)")
GENEL_EPOSTA = re.compile(
    r"[a-z0-9._%+-]+@(?:gmail|googlemail|hotmail|outlook|live|msn|windowslive|yahoo|ymail|"
    r"yandex|icloud|me|mac|aol|protonmail|proton|gmx|mynet|mail|superonline|ttmail)"
    r"\.(?:com|net|org|me|ru|de|fr|co\.uk|com\.tr|ch)\b",
    re.IGNORECASE,
)


def luhn_valid(rakamlar: str) -> bool:
    """Luhn sağlaması (kart numarası; 13–19 hane)."""
    if not rakamlar.isdigit() or not 13 <= len(rakamlar) <= 19:
        return False
    toplam = 0
    for i, ch in enumerate(reversed(rakamlar)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        toplam += d
    return toplam % 10 == 0


def privacy_hits(metin: str) -> list[str]:
    """Metindeki gerçek görünümlü kişisel / ödeme verisi türleri (deterministik; Türkçe ad).

    TCKN ve TR IBAN sağlama algoritmasıyla (`gateway.masking`), kart Luhn ile doğrulanır; genel
    e-posta sağlayıcısındaki adres gerçek kişisel e-posta sayılır (politika: ayrılmış/test alan
    adları kullanılır)."""
    from tp_core.gateway.masking import RECOGNIZERS, iban_valid, tckn_valid

    tanir = {r.kind: r.pattern for r in RECOGNIZERS}
    out: list[str] = []
    if any(iban_valid(m.group(0)) for m in tanir["IBAN"].finditer(metin)):
        out.append("geçerli IBAN")
    if any(tckn_valid(m.group(0)) for m in tanir["TCKN"].finditer(metin)):
        out.append("geçerli TCKN")
    if any(luhn_valid(re.sub(r"[ -]", "", m.group(0))) for m in KART_DESENI.finditer(metin)):
        out.append("Luhn geçerli kart numarası")
    if GENEL_EPOSTA.search(metin):
        out.append("genel sağlayıcıda e-posta")
    return out


def _ui_etiketsiz(metin: str) -> str:
    return _TIRNAKLI.sub(" ‹etiket› ", metin)


def instruction_to_auditor(metin: str) -> bool:
    """Metinde denetçiye / denetim kararına yönelik emir var mı (UI etiketleri hariç)?"""
    return DENETCIYE_TALIMAT.search(_ui_etiketsiz(metin or "")) is not None


def hosts_in(metin: str) -> set[str]:
    """Metindeki hedef ana makineler: şemalı URL'ler (http, ws, ftp…), şemasız `ad.uzanti/yol`,
    `www.` önekli ad, en az üç etiketli yolsuz ad (`prod.firma.com`) ve yol/port ile yazılmış
    IP adresi (`10.0.0.5/admin`)."""
    out = {h for h in URL_DESENI.findall(metin)}
    for a, b in SEMASIZ_HOST.findall(metin):
        out.add(a or b)
    out.update(m.group(1) for m in SEMASIZ_ALT_ALAN.finditer(metin) if _alt_alan_host_mu(metin, m))
    out.update(ip for ip in SEMASIZ_IP.findall(metin) if _ip_gecerli(ip))
    return {h.lower().rstrip(".") for h in out if h}


def _saldiri_var(metin: str) -> bool:
    return any(d.search(metin) for d in SALDIRI_DESENLERI)


def _sade(deger: Any) -> str:
    return re.sub(r"\s+", " ", str(deger or "")).strip().casefold()


def _metin_alanlari(case: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Talimat/saldırı metninin yazılmaması gereken alanlar (test verisi hariç)."""
    out = [
        ("başlık", str(case.get("title") or "")),
        ("beklenen", str(case.get("expected_result") or "")),
    ]
    out += [("ön koşul", str(p)) for p in case.get("preconditions") or []]
    out += [("temizlik", str(t)) for t in case.get("teardown") or []]
    for adim in case.get("steps") or []:
        if isinstance(adim, Mapping):
            for k, ad in (
                ("action", "adım"),
                ("data", "adım verisi"),
                ("expected", "adım beklenen"),
            ):
                out.append((f"{ad} {adim.get('id') or ''}".strip(), str(adim.get(k) or "")))
    return out


def _host_izinli(host: str, izinli: Sequence[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(fnmatch.fnmatchcase(host, d) for d in izinli)


def _bulgu(kural: str, no: int | None, alt_sinir: str, aciklama: str) -> dict[str, Any]:
    return {"kural": kural, "case_ref": no, "alt_sinir": alt_sinir, "aciklama": aciklama}


def deterministic_findings(
    cases: Sequence[Mapping[str, Any]],
    requirement_text: str = "",
    izinli: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Kodda denetlenebilen ihlaller → karar alt sınırı (`alt_sinir`). Case'ler set sırasıyla
    (1 tabanlı `case_ref`). Kurallar (alt sınır `case-audit.md` karar kuralıyla tutarlı):

    - `isaretsiz_payload_metinde`: saldırı imzası başlık/ön koşul/adım/beklenen/temizlik → DÜZELTME
    - `isaretsiz_payload_veride`: veride saldırı imzası, `is_attack_payload` true değil → DÜZELTME
    - `payload_baska_alanda`: işaretli saldırı verisinin metni başka alanda geçiyor → DÜZELTME
      (kısa veri, ör. `'`, yalnız tek başına geçtiğinde)
    - `sentetik_degil`: `synthetic` true değil → DÜZELTME
    - `ready_atifli`: `ready` case varsayım/açık soru atfı taşıyor → DÜZELTME
    - `gizlilik`: test verisinde ya da case metninde geçerli TCKN, TR IBAN (mod-97), Luhn geçerli
      kart numarası ya da genel sağlayıcıda (gmail, hotmail, outlook, yahoo, yandex …) e-posta
      → ENGELLE (kontrol 2: gerçek kişisel veri / geçerli kimlik)
    - `izinsiz_ortam`: case metnindeki ya da verisindeki hedefin (şemalı URL ya da şemasız
      `ad.uzantı/yol`) ana makinesi izinli ortamlarda değil → ENGELLE (kontrol 4: üretim ya da
      üçüncü taraf hedef)
    - `denetciye_talimat`: case metninde ya da işaretsiz verisinde denetçiye/denetim kararına
      yönelik emir → ENGELLE; gereksinim metninde → DÜZELTME (ürünün kendi "Denetçi" rolü
      olabilir; story sahibince temizlenmeli, model kararı daha sert olabilir); işaretli saldırı
      verisinde → DÜZELTME (`denetciye_talimat_veride`: meşru güvenlik testi verisi denetimi
      hedef alamaz)
    """
    from tp_core.features.cases.schema import veri_geciyor

    izinli = list(allowed_hosts() if izinli is None else izinli)
    out: list[dict[str, Any]] = []
    if instruction_to_auditor(requirement_text or ""):
        out.append(
            _bulgu(
                "denetciye_talimat",
                None,
                DUZELTME,
                "Gereksinim metninde denetçiye / denetim kararına yönelik talimat var; story "
                "sahibince temizlenmeli.",
            )
        )
    for no, case in enumerate(cases, start=1):
        alanlar = _metin_alanlari(case)
        veriler = [v for v in case.get("test_data") or [] if isinstance(v, Mapping)]
        isaretli = [_sade(v.get("value")) for v in veriler if v.get("is_attack_payload") is True]
        for ad, metin in alanlar:
            if _saldiri_var(metin):
                out.append(
                    _bulgu(
                        "isaretsiz_payload_metinde",
                        no,
                        DUZELTME,
                        f"Saldırı metni {ad} alanında (test_data dışında); test verisine "
                        "taşınıp is_attack_payload ile işaretlenmeli.",
                    )
                )
                break
        for ad, metin in alanlar:
            sade = _sade(metin)
            if any(veri_geciyor(p, sade) for p in isaretli):
                out.append(
                    _bulgu(
                        "payload_baska_alanda",
                        no,
                        DUZELTME,
                        f"İşaretli saldırı verisinin metni {ad} alanında da geçiyor.",
                    )
                )
                break
        for v in veriler:
            deger = str(v.get("value") or "")
            if v.get("is_attack_payload") is not True and _saldiri_var(deger):
                out.append(
                    _bulgu(
                        "isaretsiz_payload_veride",
                        no,
                        DUZELTME,
                        f"Test verisi '{v.get('name')}' saldırı metni içeriyor ama "
                        "is_attack_payload işaretli değil.",
                    )
                )
            if v.get("synthetic") is not True:
                out.append(
                    _bulgu(
                        "sentetik_degil",
                        no,
                        DUZELTME,
                        f"Test verisi '{v.get('name')}' sentetik olarak işaretli değil.",
                    )
                )
        if case.get("readiness") == "ready" and (
            case.get("assumption_refs") or case.get("open_question_refs")
        ):
            out.append(
                _bulgu(
                    "ready_atifli",
                    no,
                    DUZELTME,
                    "Hazır (ready) case varsayıma / açık soruya atıf yapıyor.",
                )
            )
        metinler = [m for _, m in alanlar] + [
            str(v.get("value") or "") for v in veriler if v.get("is_attack_payload") is not True
        ]
        tum_metin = [*metinler, *(str(v.get("value") or "") for v in veriler)]
        gizli = sorted({t for m in tum_metin for t in privacy_hits(m)})
        if gizli:
            out.append(
                _bulgu(
                    "gizlilik",
                    no,
                    ENGELLE,
                    "Gerçek görünümlü kişisel / ödeme verisi: " + ", ".join(gizli) + " (KVKK; "
                    "sentetik, ayrılmış alan adlı ve sağlaması geçersiz değer kullanılmalı).",
                )
            )
        if any(instruction_to_auditor(m) for m in metinler):
            out.append(
                _bulgu(
                    "denetciye_talimat",
                    no,
                    ENGELLE,
                    "Case metninde denetçiye / denetim kararına yönelik talimat var.",
                )
            )
        elif any(
            instruction_to_auditor(str(v.get("value") or ""))
            for v in veriler
            if v.get("is_attack_payload") is True
        ):
            out.append(
                _bulgu(
                    "denetciye_talimat_veride",
                    no,
                    DUZELTME,
                    "İşaretli saldırı verisi denetçiye / denetim kararına yönelik talimat "
                    "içeriyor; güvenlik testi verisi denetim kararını hedef alamaz.",
                )
            )
        yasak = sorted({h for m in tum_metin for h in hosts_in(m) if not _host_izinli(h, izinli)})
        if yasak:
            out.append(
                _bulgu(
                    "izinsiz_ortam",
                    no,
                    ENGELLE,
                    "İzinli test ortamı dışında hedef (üretim ya da üçüncü taraf): "
                    + ", ".join(yasak),
                )
            )
    return out


SERT_RISK = ("Yüksek", "Orta")


def harden(
    model_karari: str,
    bulgular: Iterable[Mapping[str, Any]],
    model_bulgulari: Iterable[Mapping[str, Any]] = (),
) -> str:
    """Kararın deterministik alt sınırla sertleştirilmesi (yumuşatma yok).

    Alt sınırlar: deterministik bulguların `alt_sinir`'ı ve modelin kendi bulguları — karar
    kuralı "Yüksek ya da Orta riskli bulgu varsa karar KABUL olamaz" der; model KABUL deyip
    Yüksek/Orta bulgu yazdıysa karar en az DÜZELTME_GEREKLİ olur."""
    karar = model_karari if model_karari in SIDDET else ENGELLE
    if karar == KABUL and any(
        isinstance(b, Mapping) and b.get("risk") in SERT_RISK for b in model_bulgulari
    ):
        karar = DUZELTME
    for b in bulgular:
        sinir = str(b.get("alt_sinir"))
        if SIDDET.get(sinir, 0) > SIDDET[karar]:
            karar = sinir
    return karar


# ------------------------------------------------------------------------- istek


def _bekleyen(session: Session, requirement_id: uuid.UUID, hash_: str) -> CaseSetAudit | None:
    return review_mod.bekleyen_satir(session, CaseSetAudit, requirement_id, hash_)


def _denetim_hatasi(session: Session, satir: CaseSetAudit, neden: str) -> None:
    review_mod.mark_failed(
        session,
        satir,
        neden,
        eylem="cases.audit_failed",
        olay="case.audit",
        anahtar="audit_id",
    )


def close_stuck_audits(session: Session, requirement_id: uuid.UUID | None = None) -> int:
    """Etkin işi olmayan `bekliyor` denetim satırlarını `hata` yapar (iş yarıda kaldı)."""
    return review_mod.close_stuck(session, CaseSetAudit, _denetim_hatasi, requirement_id)


def _tamamlananlar(
    session: Session, requirement_id: uuid.UUID, hash_: str | None
) -> list[CaseSetAudit]:
    if hash_ is None:
        return []
    return list(
        session.scalars(
            select(CaseSetAudit)
            .where(
                CaseSetAudit.requirement_id == requirement_id,
                CaseSetAudit.set_hash == hash_,
                CaseSetAudit.durum == "tamamlandi",
            )
            .order_by(CaseSetAudit.olusturma.desc(), CaseSetAudit.id.desc())
        )
    )


def binding_decision(
    session: Session, requirement_id: uuid.UUID, hash_: str | None
) -> CaseSetAudit | None:
    """Kapının okuduğu karar: bu set hash'inin tamamlanmış denetimlerinden EN SERTİ (eşitlikte
    en yenisi). Aynı set yeniden denetlenip daha yumuşak karar alınsa bile önceki sert karar
    geçerli kalır (P9 kararı set değişmeden değiştirilemez)."""
    satirlar = _tamamlananlar(session, requirement_id, hash_)
    if not satirlar:
        return None
    return max(satirlar, key=lambda a: SIDDET.get(str(a.karar), SIDDET[ENGELLE]))


def limit_block(session: Session, requirement_id: uuid.UUID) -> str | None:
    return review_mod.limit_reason(
        session,
        CaseSetAudit,
        requirement_id,
        DENETIM_SINIRI_ORTAMI,
        DENETIM_VARSAYILAN_SINIR,
        "denetim",
    )


def submit_block(
    session: Session,
    req: Requirement,
    hash_: str | None,
    cases: Sequence[TestCase] | None = None,
) -> str | None:
    """ "Agent Probe'a gönder" neden kapalı (None = gönderilebilir).

    Portal düğme açıklaması da budur.

    `cases`: güncel set (verilmezse hesaplanır; görünüm tek kez hesaplayıp verir)."""
    from tp_core.features.cases.service import requirement_change_reason

    if req.durum not in review_mod.SET_KULLANILIR:
        return (
            "Agent Probe denetimi yalnızca case'leri hazır gereksinimde istenir "
            f"(durum: {req.durum})"
        )
    engel = requirement_change_reason(req)
    if engel is not None:
        return engel
    if hash_ is None:
        return "Gereksinimin güncel v3 case'i yok; denetlenecek set boş"
    karar = binding_decision(session, req.id, hash_)
    if karar is not None:
        if karar.karar == KABUL:
            # UX4 Bulgu 9: KABUL sonrası "düzeltip yeniden gönderin" denmez; yapılacak bir şey yok.
            return (
                f"Bu set zaten denetlendi (karar: {karar.karar}); yeniden denetim gerekmez. "
                "Set değişirse (case düzeltilir, eklenir ya da reddedilir) yeniden gönderilebilir"
            )
        return (
            f"Bu set zaten denetlendi (karar: {karar.karar}); set değişmeden yeniden denetim "
            "yapılmaz. Case'leri düzeltip yeniden gönderin"
        )
    if review_mod._bekleyen(session, req.id, hash_) is not None:
        return "Bu set için review sürüyor; review bitince 'Agent Probe'a gönder'i kullanın"
    sinir = limit_block(session, req.id)
    if sinir is not None:
        return sinir
    if review_mod.latest_completed(session, req.id, hash_) is not None:
        return None
    if cases is None:
        cases = review_mod.current_cases(session, req)
    if not any(tc.durum in ("approved", "published") for tc in cases):
        return (
            "Bu setin review'u tamamlanmadı ve onaylı case yok: review'u yeniden çalıştırın ya da "
            "en az bir case'i inceleyip onaylayın"
        )
    return None


def request_audit(session: Session, requirement_id: uuid.UUID, user: Principal) -> dict[str, Any]:
    """`POST /requirements/{id}/case-audit` ("Agent Probe'a gönder").

    409: set boş / gereksinim uygun değil / review sürüyor / bu set ZATEN denetlendi (aynı
    `set_hash` için tamamlanmış karar varken yeniden denetim yok). 429: gereksinim başına
    24 saatlik denetim sınırı (`TP_DENETIM_GUNLUK_SINIR`)."""
    from tp_core.features.cases.service import get_requirement

    req = get_requirement(session, requirement_id, lock=True)
    close_stuck_audits(session, req.id)
    review_mod.close_stuck_reviews(session, req.id)
    cases = review_mod.current_cases(session, req)
    hash_ = review_mod.hash_of([tc.icerik_hash for tc in cases])
    mevcut = _bekleyen(session, req.id, hash_) if hash_ else None
    if mevcut is None:
        engel = submit_block(session, req, hash_, cases)
        if engel is not None:
            if engel == limit_block(session, req.id):
                raise review_mod.KaliteSiniri(engel)
            raise AuditNotAllowed(engel)
        assert hash_ is not None
        son_review = review_mod.latest_completed(session, req.id, hash_)
        satir = CaseSetAudit(
            requirement_id=req.id,
            set_hash=hash_,
            isteyen=user.kullanici_adi,
            review_id=son_review.id if son_review else None,
        )
        session.add(satir)
        session.flush()
        satir.job_id = enqueue(
            session.connection(),
            AUDIT_JOB,
            {"audit_id": str(satir.id)},
            idempotency_key=f"{AUDIT_JOB}:{satir.id}",
        )
        audit_on_commit(
            session,
            user.kullanici_adi,
            "cases.audit_requested",
            f"requirement:{req.id}",
            {"audit_id": satir.id, "set_hash": hash_, "review_id": satir.review_id},
        )
        session.flush()
    return view(session, req.id)


def build_request(
    session: Session, req: Requirement, girdi: review_mod.SetGirdisi
) -> CaseSetAuditRequest:
    blok, kok = review_mod.requirement_block_for(req)
    son_review = review_mod.latest_completed(session, req.id, girdi.set_hash)
    review_sonucu = None
    if son_review is not None:
        review_sonucu = {
            k: v
            for k, v in (son_review.icerik or {}).items()
            if k in ("items", "score", "missing_cases", "remove_or_merge", "summary")
        }
    return CaseSetAuditRequest(
        requirement_id=req.id,
        requirement_key=kok,
        set_hash=girdi.set_hash or "",
        requirement_block=blok,
        generated_set=review_mod.set_payload([tc.icerik for tc in girdi.cases], girdi.ozet),
        review_result=review_sonucu,
        policies=policies(),
        test_data_block=_test_verisi_blogu(),
        allowed_hosts=allowed_hosts(),
    )


def _test_verisi_blogu() -> str | None:
    """Üretime verilen test verisi bloğu (denetçi aynı kaynağı görsün; yoksa None)."""
    from tp_core.features.cases import testdata

    try:
        return testdata.block()
    except Exception:  # veri kaynağı yoksa denetim yine çalışır
        return None


def _requirement_text(req: Any) -> str:
    return "\n".join(
        [str(req.baslik or ""), str(req.aciklama or "")]
        + [str(a) for a in req.kabul_kriterleri or []]
    )


def _hata_yaz(audit_id: uuid.UUID, neden: str) -> None:
    with session_scope() as s:
        satir = s.get(CaseSetAudit, audit_id, with_for_update=True)
        if satir is not None:
            _denetim_hatasi(s, satir, neden)


def run_audit(ctx: JobContext, engine: Engine) -> dict[str, Any]:
    """`cases.audit` işi: Agent Probe portu → deterministik sertleştirme → `case_set_audit`."""
    from tp_core.gateway import deterministic_call_id
    from tp_core.gateway.errors import GatewayError, ReplayNotFound
    from tp_core.integrations.agent_probe import AgentProbeUnavailable, denetim, get_agent_probe

    aid = uuid.UUID(str((ctx.yuk or {})["audit_id"]))
    try:
        with session_scope() as s:
            satir = s.get(CaseSetAudit, aid, with_for_update=True)
            if satir is None:
                raise PermanentJobError("denetim kaydı yok")
            if satir.durum != "bekliyor":
                return {"atlandi": True, "durum": satir.durum}
            req = s.get(Requirement, satir.requirement_id)
            if req is None:
                raise PermanentJobError("gereksinim silinmiş")
            girdi = review_mod.snapshot(s, req)
            if girdi.set_hash is None:
                _denetim_hatasi(s, satir, "sette v3 case kalmadı")
                return {"atlandi": True, "neden": "boş set"}
            if girdi.set_hash != satir.set_hash:
                # İstekten sonra set değişti: analistin göndermediği set denetlenmez (model
                # çağrılmaz); analist güncel seti yeniden gönderir.
                _denetim_hatasi(s, satir, review_mod.SET_DEGISTI_HATA)
                return {"atlandi": True, "neden": "set değişti"}
            istek = build_request(s, req, girdi)
            harita = girdi.harita()
            cases = [dict(tc.icerik) for tc in girdi.cases]
            gereksinim_metni = _requirement_text(req)
    except PermanentJobError:
        raise
    except Exception as exc:  # girdi kurulamadı: karar yok (fail-closed), satır kilitte kalmaz
        _hata_yaz(aid, f"denetim girdisi kurulamadı: {type(exc).__name__}: {str(exc)[:300]}")
        return {"hata": type(exc).__name__}
    try:
        port = get_agent_probe()
        with denetim.cagri_baglami(call_id=deterministic_call_id(ctx.job_id, "case_audit")):
            sonuc: CaseSetAuditResult = port.audit_case_set(istek)
    except ReplayNotFound as exc:
        _hata_yaz(
            aid, f"REPLAY-MISS: bu set için kayıtlı denetim çıktısı yok ({type(exc).__name__})"
        )
        return {"hata": "replay_miss"}
    except (GatewayError, AgentProbeUnavailable) as exc:
        if not ctx.son_deneme and not isinstance(exc, AgentProbeUnavailable):
            raise
        _hata_yaz(aid, f"Agent Probe: {exc}")
        return {"hata": type(exc).__name__}
    except Exception as exc:
        _hata_yaz(aid, f"{type(exc).__name__}: {str(exc)[:300]}")
        return {"hata": type(exc).__name__}
    if sonuc.decision not in SIDDET or sonuc.kaynak not in KAYNAKLAR:
        _hata_yaz(
            aid,
            f"Agent Probe geçersiz yanıt döndü (karar: {str(sonuc.decision)[:40]!r}, kaynak: "
            f"{str(sonuc.kaynak)[:40]!r}); karar yazılmadı",
        )
        return {"hata": "gecersiz_karar"}
    try:
        return _denetim_yaz(aid, sonuc, istek, harita, cases, gereksinim_metni)
    except Exception as exc:  # sonuç yazılamadı: karar yok (fail-closed)
        _hata_yaz(aid, f"denetim sonucu yazılamadı: {type(exc).__name__}: {str(exc)[:300]}")
        return {"hata": type(exc).__name__}


def _denetim_yaz(
    aid: uuid.UUID,
    sonuc: CaseSetAuditResult,
    istek: CaseSetAuditRequest,
    harita: dict[str, Any],
    cases: list[dict[str, Any]],
    gereksinim_metni: str,
) -> dict[str, Any]:
    bulgular = deterministic_findings(cases, gereksinim_metni)
    karar = harden(sonuc.decision, bulgular, sonuc.findings or ())
    with session_scope() as s:
        satir = s.get(CaseSetAudit, aid, with_for_update=True)
        if satir is None or satir.durum != "bekliyor":
            return {"atlandi": True}
        mod = review_mod._mod(s, sonuc.ai_call_id)
        satir.durum = "tamamlandi"
        satir.model_karari = sonuc.decision
        satir.karar = karar
        satir.kaynak = sonuc.kaynak
        satir.talep_no = sonuc.talep_no
        satir.ai_call_id = sonuc.ai_call_id
        satir.icerik = {
            "decision": sonuc.decision,
            "decision_rationale": sonuc.decision_rationale,
            "findings": sonuc.findings,
            "missing_scenarios": sonuc.missing_scenarios,
            "deterministik_bulgular": bulgular,
            "sertlestirildi": karar != sonuc.decision,
            "case_haritasi": harita,
            "review_kullanildi": istek.review_result is not None,
            "mode": mod,
        }
        audit_on_commit(
            s,
            "system",
            "cases.audited",
            f"requirement:{satir.requirement_id}",
            {
                "audit_id": aid,
                "set_hash": satir.set_hash,
                "karar": karar,
                "model_karari": sonuc.decision,
                "kaynak": sonuc.kaynak,
                "talep_no": sonuc.talep_no,
                "ai_call_id": sonuc.ai_call_id,
                "deterministik": [b["kural"] for b in bulgular],
            },
        )
        publish_tx(
            s.connection(),
            "case.audit",
            {"requirement_id": satir.requirement_id, "durum": "tamamlandi", "karar": karar},
        )
    return {"audit_id": str(aid), "karar": karar, "model_karari": sonuc.decision}


# ------------------------------------------------------------------- yayın kapısı (K3)


def gate_enabled() -> bool:
    return (os.environ.get(KAPI_ORTAMI) or "on").strip().lower() not in (
        "off",
        "0",
        "false",
        "kapali",
    )


def latest_completed(
    session: Session, requirement_id: uuid.UUID, hash_: str | None
) -> CaseSetAudit | None:
    if hash_ is None:
        return None
    return session.scalars(
        select(CaseSetAudit)
        .where(
            CaseSetAudit.requirement_id == requirement_id,
            CaseSetAudit.set_hash == hash_,
            CaseSetAudit.durum == "tamamlandi",
        )
        .order_by(CaseSetAudit.olusturma.desc(), CaseSetAudit.id.desc())
        .limit(1)
    ).first()


def latest(session: Session, requirement_id: uuid.UUID) -> CaseSetAudit | None:
    return session.scalars(
        select(CaseSetAudit)
        .where(CaseSetAudit.requirement_id == requirement_id)
        .order_by(CaseSetAudit.olusturma.desc(), CaseSetAudit.id.desc())
        .limit(1)
    ).first()


def _kisa(metin: str | None, n: int = 240) -> str:
    metin = " ".join(str(metin or "").split())
    return metin if len(metin) <= n else metin[: n - 1] + "…"


def _hash_reason(session: Session, req: Requirement, hash_: str | None) -> str | None:
    """Verilen (güncel) set hash'i için yayın engeli (kapı açıkken)."""
    karar = binding_decision(session, req.id, hash_)
    if karar is None:
        son = latest(session, req.id)
        if son is None:
            return (
                "Denetim kararı yok: set Agent Probe denetiminden geçmedi ('Agent Probe'a gönder')"
            )
        if son.set_hash == hash_ and review_mod.is_running(session, son):
            return "Denetim bekliyor: bu set için Agent Probe kararı henüz gelmedi"
        if son.set_hash == hash_ and son.durum in ("hata", "bekliyor"):
            neden = son.hata or review_mod.YARIDA_KALDI
            return (
                f"Denetim yapılamadı: {_kisa(neden, 160)}; "
                "'Agent Probe'a gönder' ile yeniden gönderin"
            )
        return (
            "Denetim kararı bayat: set son denetimden sonra değişti (case eklendi, düzeltildi ya "
            "da reddedildi); 'Agent Probe'a gönder' ile yeniden gönderin"
        )
    if karar.karar == KABUL:
        return None
    gerekce = _kisa((karar.icerik or {}).get("decision_rationale"))
    return f"{karar.karar}: {gerekce}" if gerekce else str(karar.karar)


def gate_reason(session: Session, req: Requirement, hash_: Any = ...) -> str | None:
    """Gereksinimin güncel seti için yayın engeli (None = KABUL var ya da kapı kapalı)."""
    if not gate_enabled():
        return None
    if hash_ is ...:
        hash_ = review_mod.set_hash(session, req)
    return _hash_reason(session, req, hash_)


@dataclass(frozen=True)
class KapiDurumu:
    """Gereksinimin yayın kapısı durumu: güncel (denetlenen) setin case'leri + engel."""

    set_ids: frozenset[uuid.UUID]
    neden: str | None


def gate_state(session: Session, req: Requirement) -> KapiDurumu:
    cases = review_mod.current_cases(session, req)
    hash_ = review_mod.hash_of([tc.icerik_hash for tc in cases])
    return KapiDurumu(frozenset(tc.id for tc in cases), _hash_reason(session, req, hash_))


SET_DISI = "Case denetlenen güncel sette değil (eski içerik ya da set dışı case); yayınlanamaz"


def gate_check(session: Session, tc: TestCase) -> str | None:
    """`publish.set_gate_check` kancası (yalnız v3 case için çağrılır).

    Kapı açıkken: case gereksinimin GÜNCEL setinde olmalı (denetlenen set) ve setin bağlayıcı
    kararı KABUL olmalı. Durum `session.info[KAPI_ONBELLEGI]` varsa gereksinim başına bir kez
    hesaplanır (önizleme / yayın işi)."""
    if not gate_enabled():
        return None
    onbellek = session.info.get(KAPI_ONBELLEGI)
    durum = onbellek.get(tc.requirement_id) if isinstance(onbellek, dict) else None
    if durum is None:
        req = session.get(Requirement, tc.requirement_id)
        if req is None:
            return "Gereksinim bulunamadı"
        durum = gate_state(session, req)
        if isinstance(onbellek, dict):
            onbellek[tc.requirement_id] = durum
    if tc.id not in durum.set_ids:
        return SET_DISI
    return durum.neden


def bind_gate() -> None:
    """Yayın kapısını bağlar (publish paketinin açılışında; core-api, core-worker, testler)."""
    from tp_core.features.publish import service as publish

    publish.set_gate_check(gate_check)


# ------------------------------------------------------------------------ görünüm


def serialize(session: Session, satir: CaseSetAudit | None, guncel: str | None) -> dict | None:
    if satir is None:
        return None
    return {
        "id": str(satir.id),
        "durum": satir.durum,
        "set_hash": satir.set_hash,
        "karar": satir.karar,
        "model_karari": satir.model_karari,
        "icerik": satir.icerik or {},
        "kaynak": satir.kaynak,
        "talep_no": satir.talep_no,
        "hata": satir.hata,
        "isteyen": satir.isteyen,
        "review_id": str(satir.review_id) if satir.review_id else None,
        "ai_call_id": str(satir.ai_call_id) if satir.ai_call_id else None,
        "olusturma": satir.olusturma,
        "guncelleme": satir.guncelleme,
        "guncel": satir.set_hash == guncel,
    }


def view(session: Session, requirement_id: uuid.UUID) -> dict[str, Any]:
    """`GET /requirements/{id}/case-audit`: son karar, güncel set hash'i, güncel mi, kapı durumu."""
    from tp_core.features.cases.service import get_requirement

    req = get_requirement(session, requirement_id)
    cases = review_mod.current_cases(session, req)  # set bir kez hesaplanır
    hash_ = review_mod.hash_of([tc.icerik_hash for tc in cases])
    son = latest(session, req.id)
    bekleyen = _bekleyen(session, req.id, hash_) if hash_ else None
    return {
        "requirement_id": str(req.id),
        "set_hash": hash_,
        "denetim": serialize(session, son, hash_),
        "guncel_karar": serialize(session, binding_decision(session, req.id, hash_), hash_),
        "calisiyor": bekleyen is not None,
        "gonder_engeli": None if bekleyen is not None else submit_block(session, req, hash_, cases),
        "kapi_acik": gate_enabled(),
        "yayin_engeli": gate_reason(session, req, hash_) if hash_ else None,
    }


router = APIRouter(tags=["cases"])
Analyst = Annotated[Principal, Depends(require_role("analyst"))]


@router.get("/requirements/{requirement_id}/case-audit")
def get_case_audit(
    requirement_id: uuid.UUID, session: DbSession, _user: CurrentUser
) -> dict[str, Any]:
    return view(session, requirement_id)


@router.post("/requirements/{requirement_id}/case-audit", status_code=202)
def post_case_audit(requirement_id: uuid.UUID, session: DbSession, user: Analyst) -> dict[str, Any]:
    return request_audit(session, requirement_id, user)
