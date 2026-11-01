"""Demo akışının adımları (TEKNIK-TASARIM §2, ana yol: REPLAY senaryosu `f2-kod-hatasi`).

Beklenen değerlerin kaynağı docs/DEMO-VERISI.md'dir; burada uydurma değer yoktur. Her adım ilgili
rolün oturumuyla çalışır (analist, po → jira-sim, muhendis, sunucu, testci). Kimlikler (gereksinim,
case, script, hata) her adımda API'den yeniden bulunur: `denetim` kipi aynı doğrulamaları
tamamlanmış bir demonun son durumuna karşı, hiçbir şey değiştirmeden koşturur.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tp_rehearsal.client import ApiHatasi, baglantilar
from tp_rehearsal.runner import Adim, Baglam, Basarisiz, dogrula

STORY = "TPD-1"
DUP_ADAYI = "TPD-5"
KARARLAR = {"F1": "fix_doc", "F2": "code_defect", "F3": "fix_doc", "F4": "code_defect"}
BULGU_TURLERI = {
    "F1": "internal_contradiction",
    "F2": "doc_vs_code",
    "F3": "doc_vs_data",
    "F4": "missing_in_code",
}
AC2_OZGUN = (
    '"6 al 1 bedava" kampanyasında kampanyalı üründen her 6 adet alımda 1 adet bedava verilir '
    "(7 adette 1 bedava)."
)
AC3_DUZELTME_ONEKI = "Kampanyasız siparişlerde minimum sipariş tutarı 750,00 TL"
CASE_SAYISI = 10
C3_BASLIK = "6 adet kampanyalı üründe bedava ürün verilmez"
KOD_CASELERI = (1, 2, 3, 5)  # C1 sepet sayacı, C2 7 adet, C3 6 adet, C5 750,00 TL
PR_CASELERI = (1, 2, 5)
MERGE_SIRASI = (2, 1, 5)  # önce kırarak doğrulaması geçen C2; C1/C5 zayıf test → açık kabul notu
C3_SINYALLERI = {"assertion_farki", "eleman_bulundu", "sayfa_yapisi_beklenen", "tutarli_tekrar"}
LOCATOR_KIRMIZI = (19, 22)  # Demo-B merge'leri yoksa 19, C1/C2/C5 merge edildiyse 22
AJAN_BUTCESI_S = 120.0  # §1/§13: kod üretiminde ajan adımı ≤120 sn
CI_BUTCESI_S = 120.0  # §13: CI 2 dakikayı aşarsa yedek yol
ONAY_NOTU = (
    "Zayıf test bilinçli kabul (prova): kampanya dışı davranış, BREAK_CAMPAIGN ile kırılmaz."
)
SURUYOR = {"pending", "queued", "generating", "verifying", "mapping", "checking", "running"}
KOSU_SURUYOR = {"queued", "running"}


# ---------------------------------------------------------------- bulma yardımcıları


def _simdi_iso() -> str:
    return datetime.now(UTC).isoformat()


def gereksinim(b: Baglam, zorunlu: bool = True) -> dict[str, Any] | None:
    for r in b.api.get("analist", "/requirements"):
        if r.get("jira_key") == STORY:
            return b.api.get("analist", f"/requirements/{r['id']}")
    if zorunlu:
        raise Basarisiz(f"{STORY} gereksinimi portalda yok (Jira'dan çekilmedi)")
    return None


def gereksinim_bekle(b: Baglam, aciklama: str, kosul, zaman_asimi_s: float) -> dict[str, Any]:
    """Gereksinim detayı `kosul(detay)` sağlanana kadar yoklanır; detay döner."""
    req_id = b.veri["req_id"]

    def oku():
        r = b.api.get("analist", f"/requirements/{req_id}")
        return r if kosul(r) else None

    return b.bekle(aciklama, oku, zaman_asimi_s)


def bulgular_tur1(b: Baglam, req_id: str) -> dict[str, dict[str, Any]]:
    tumu = b.api.get("analist", f"/requirements/{req_id}/findings?tumu=true")
    return {f["bulgu_no"]: f for f in tumu if f.get("kontrol_turu") == 1}


def caseler(b: Baglam, req_id: str) -> dict[int, dict[str, Any]]:
    """Güncel üretimin case'leri, sıra numarasına göre."""
    hepsi = b.api.get("analist", f"/cases?requirement_id={req_id}")
    if not hepsi:
        return {}
    son = max(c.get("uretim_no") or 0 for c in hepsi)
    return {c["sira_no"]: c for c in hepsi if (c.get("uretim_no") or 0) == son}


def script_bul(b: Baglam, sira: int) -> dict[str, Any] | None:
    ref = f"{STORY}-C{sira}"
    adaylar = [
        s
        for s in b.api.get("muhendis", "/scripts")
        if s.get("case_ref") == ref and s.get("durum") != "closed"
    ]
    if not adaylar:
        return None
    son = max(adaylar, key=lambda s: s.get("olusturma") or "")
    return b.api.get("muhendis", f"/scripts/{son['id']}")


def kosular(b: Baglam, sorgu: str = "") -> list[dict[str, Any]]:
    return b.api.get("sunucu", f"/runs?limit=200{'&' + sorgu if sorgu else ''}")


def kosu_bekle(b: Baglam, aciklama: str, sec, zaman_asimi_s: float) -> dict[str, Any]:
    """`sec(koşular)` bir koşu dönene ve koşu bitene kadar bekler."""

    def kosul():
        k = sec(kosular(b))
        return k if k and k.get("durum") not in KOSU_SURUYOR else None

    return b.bekle(aciklama, kosul, zaman_asimi_s, aralik_s=5)


def ci_bosta_bekle(b: Baglam, zaman_asimi_s: float = 600) -> None:
    """Kuyrukta/koşan CI yokken döner (sahne notu: kırma önceki koşu bittikten sonra)."""
    b.bekle(
        "kuyrukta ya da koşan CI koşusu kalmadı",
        lambda: not any(k.get("durum") in KOSU_SURUYOR for k in kosular(b, "limit=50")),
        zaman_asimi_s,
        aralik_s=5,
    )


def bug_taslaklari(b: Baglam) -> list[dict[str, Any]]:
    return b.api.get("testci", "/bug-drafts")


def mod_kontrol(b: Baglam, ad: str, mod: Any) -> None:
    izinli = b.veri.get("izinli_modlar", {"replay"})
    b.kontrol(
        f"{ad}: üretim modu dürüst etiketli",
        mod in izinli,
        f"mode={mod!r}, izinli={sorted(izinli)}",
    )


# ---------------------------------------------------------------- P0 ön kontrol

TEMEL_BEKLEME_S = 420.0  # demo-reset: demo-app-web derlemesi + baseline push CI
CI_TETIKLERI = {"pr", "push", "nightly", "deploy", "manual"}
DENETIM_SONRASI = {"doc_final", "pending_po", "po_approved", "generating", "cases_ready", "done"}
PO_SONRASI = {"po_approved", "generating", "cases_ready", "done"}
AKIS_ADIM_SAYISI = 14


def temel_kosu_bekle(b: Baglam) -> dict[str, Any]:
    """DEMO-AKISI §1.2: `make demo-reset`in kuyruğa aldığı main push CI'ı yeşil bitmiş olmalı.

    Sunucu açılıştan önce bunu bekler (locator kırılması yeşil temel koşu ister); prova da aynı
    başlangıç durumundan koşar. `onarim_on_kosulu.son_yesil_kosu` forge main'inde olmalıdır.
    """

    def oku():
        d = b.api.get("sunucu", "/demo/status")
        on = d.get("onarim_on_kosulu") or {}
        son = on.get("son_yesil_kosu") or {}
        main = (d.get("forge") or {}).get("main")
        return d if on.get("hazir") is True and (not main or son.get("commit") == main) else None

    try:
        durum = b.bekle("make demo-reset temel push CI'ı yeşil", oku, TEMEL_BEKLEME_S)
    except Basarisiz:
        durum = b.api.get("sunucu", "/demo/status")
    on = (durum or {}).get("onarim_on_kosulu") or {}
    son = on.get("son_yesil_kosu") or {}
    b.kanit["temel_kosu"] = {"hazir": on.get("hazir"), "tetik": son.get("tetik")}
    b.kontrol(
        "temel push CI yeşil (DEMO-AKISI §1.2: make reset → make demo-reset → yeşil)",
        on.get("hazir") is True and son.get("tetik") == "push",
        f"onarim_on_kosulu.hazir={on.get('hazir')!r}, son_yesil_kosu={son or None} — "
        "`make demo-reset` çalıştırıp main push koşusunun yeşil bitmesini bekleyin "
        "(scripts/demo-prova.sh bunu yapar)",
    )
    return durum


def _zaman_s(z: Any) -> float | None:
    if not z:
        return None
    try:
        return datetime.fromisoformat(str(z).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _script_pr(s: dict[str, Any]) -> dict[str, Any]:
    pr = s.get("pr") or s.get("pull_request")
    if isinstance(pr, dict):
        return pr
    return {"number": s.get("pr_no")} if s.get("pr_no") is not None else {}


def story_kosusu_mu(k: dict[str, Any], story_scriptleri: list[dict[str, Any]]) -> bool:
    """review-portal/src/lib/yolHaritasi.ts `storyKosusuMu` aynası.

    Koşu story'ye aittir: story script'lerinden birinin PR'ının koşusuysa ya da story'nin ilk
    merge'ünden (bilinmiyorsa merge edilen script'in oluşturulmasından) sonra başladıysa.
    """
    prs = [_script_pr(s) for s in story_scriptleri]
    pr_no = k.get("pr_no")
    if pr_no is not None and any(
        (p.get("number") if p.get("number") is not None else p.get("pr_no")) == pr_no for p in prs
    ):
        return True
    mergeler = []
    for s, p in zip(story_scriptleri, prs, strict=True):
        if s.get("durum") == "merged" or str(p.get("durum") or p.get("state") or "") == "merged":
            z = _zaman_s(p.get("merge_zamani") or p.get("merged_at"))
            z = z if z is not None else _zaman_s(s.get("olusturma"))
            if z is not None:
                mergeler.append(z)
    if not mergeler:
        return False
    bas = _zaman_s(k.get("baslangic") or k.get("baslama") or k.get("olusturma"))
    return bas is not None and bas >= min(mergeler)


def acilis_tamam_adimlari(
    req: dict[str, Any] | None,
    kosu_listesi: list[dict[str, Any]],
    kule: dict[str, Any] | None,
    story_scriptleri: list[dict[str, Any]],
    story_buglari: list[dict[str, Any]],
) -> list[int]:
    """Yol haritasının (review-portal/src/lib/yolHaritasi.ts) "tamam" ya da "yedek" saydığı adımlar.

    Sayaç `tamam + yedek / 14`tür. Koşu tabanlı 8–11 kuralları birebir aynadır; story tabanlı
    adımlar (1–7, 12–14) temiz başlangıçta kanıt olmamasıyla yaklaşık izlenir.
    """
    tamam: list[int] = []
    durum = (req or {}).get("durum")
    if req:
        tamam.append(1)
    if durum in DENETIM_SONRASI:
        tamam.append(2)
    if durum in PO_SONRASI:
        tamam.append(3)
    if durum in ("cases_ready", "done"):
        tamam.append(4)
    if any(s.get("pr") for s in story_scriptleri):
        tamam.append(5)
    # Portal `storyKosusuMu`: yalnız story'nin koşuları (story PR'ının CI'ı / ilk merge'den sonra).
    ci = [
        k
        for k in kosu_listesi
        if k.get("tetik") in CI_TETIKLERI and story_kosusu_mu(k, story_scriptleri)
    ]
    tetikler = {k.get("tetik") for k in ci}
    if "push" in tetikler and tetikler & {"nightly", "deploy"}:
        tamam.append(8)
    if any(k.get("kaynak") == "sauce" for k in ci) or any(
        k.get("kaynak") != "sauce" and k.get("durum") in ("passed", "failed") for k in ci
    ):
        tamam.append(9)  # Sauce yoksa biten yerel koşu "yedek" — sayaçta tamam sayılır
    raporlu = any(k.get("junit_url") or k.get("allure_url") for k in ci)
    if raporlu:
        tamam.append(10)
    if raporlu and kule and (kule.get("son_kosular") or []):
        tamam.append(11)  # portal: adım 10 (story'nin raporlu koşusu) gelmeden 11 tamam değil
    if story_buglari:
        tamam.append(13)
    return sorted(tamam)


def acilis_sayaci_kontrol(b: Baglam, req: dict[str, Any] | None) -> None:
    """DEMO-AKISI Açılış: `make reset` (+ demo-reset) sonrası yol haritası **0/14 tamam** der.

    Portal mantığının aynasıdır; yetkili kontrol arayüz provasındadır (`--ui`, ekrandaki sayaç).
    Ayna portaldan sapabileceği için burada UYARI'dır (prova durmaz, rapora yazılır).
    """
    try:
        kule = b.api.get("sunucu", "/control-tower")
    except ApiHatasi:
        kule = None
    scriptler = [
        s for s in b.api.get("muhendis", "/scripts") if str(s.get("case_ref", "")).startswith(STORY)
    ]
    buglar = [d for d in bug_taslaklari(b) if ((d.get("icerik") or {}).get("story_key")) == STORY]
    tamam = acilis_tamam_adimlari(req, kosular(b), kule, scriptler, buglar)
    b.kanit["acilis_sayaci"] = f"{len(tamam)}/{AKIS_ADIM_SAYISI}"
    b.kontrol(
        f"açılış: yol haritası 0/{AKIS_ADIM_SAYISI} tamam (DEMO-AKISI Açılış sözü)",
        not tamam,
        f"{len(tamam)}/{AKIS_ADIM_SAYISI} tamam görünecek (adım {tamam}) — sunucu metni "
        "'0/14' der; ortam temiz değil ya da portal kuralı bu aynadan saptı",
        kritik=False,
    )


def on_kontrol(b: Baglam) -> None:
    b.veri["baslangic_iso"] = _simdi_iso()
    roller = {}
    for rol in ("analist", "po", "muhendis", "sunucu", "testci"):
        me = b.api.get(rol, "/auth/me")
        roller[rol] = me.get("rol")
    b.kanit["roller"] = roller
    b.kontrol("5 portal rolü giriş yaptı", len(roller) == 5, str(roller))

    w = b.yigin.worker_ortami()
    b.kanit["core_worker"] = w
    mod = w.get("TP_MODEL_MODE") or "?"
    b.veri["model_modu"] = mod
    canli_izinli = bool(b.veri.get("canli_izinli"))
    b.veri["izinli_modlar"] = (
        {"replay", "live"} if (mod != "replay" and (canli_izinli or not b.prova)) else {"replay"}
    )
    b.kontrol(
        "core-worker model kipi okundu", mod != "?", "docker compose exec core-worker printenv"
    )
    if b.prova:
        # §13 provası strict REPLAY'dir: auto/live kipte gerçek (değerlendirilmemiş, deterministik
        # olmayan) model çağrısı yapılır ve "REPLAY-MISS olmadan replay" doğrulanmış olmaz.
        b.kontrol(
            "TP_MODEL_MODE=replay (prova: canlı model çağrısı yok)",
            mod == "replay",
            f"core-worker TP_MODEL_MODE={mod!r} — .env'de TP_MODEL_MODE=replay yapıp `make up` "
            "(scripts/demo-prova.sh replay dışında koşmaz)",
            kritik=not canli_izinli,
        )
    b.kontrol(
        "TP_REPLAY_STRICT=1 (prova: golden'a düşmez, REPLAY-MISS verir)",
        w.get("TP_REPLAY_STRICT") == "1",
        f"TP_REPLAY_STRICT={w.get('TP_REPLAY_STRICT')!r} — scripts/demo-prova.sh ya da "
        "`TP_REPLAY_STRICT=1 docker compose up -d core-worker`",
        kritik=not b.veri.get("strict_gerekmez"),
    )
    b.kontrol(
        "TP_FORGE=local (locator demosu)",
        w.get("TP_FORGE") in ("local", ""),
        f"{w.get('TP_FORGE')!r}",
    )

    durum = b.api.get("sunucu", "/demo/status")
    b.kanit["demo_status"] = {
        "locator_durumu": durum.get("locator_durumu"),
        "main_baseline_mi": (durum.get("forge") or {}).get("main_baseline_mi"),
        "uygulama_main_ile_eslesiyor": (durum.get("uygulama") or {}).get("main_ile_eslesiyor"),
    }
    b.kontrol(
        "locator demosu destekleniyor",
        (durum.get("locator_demo") or {}).get("destekleniyor") is True,
    )

    baz = b.ortam.al("TP_MANUAL_BASELINE_S")
    b.veri["manuel_baz_s"] = baz
    b.kanit["manuel_baz"] = baz or "girilmedi (ölçülmedi; kazanç oranı gösterilmez)"

    req = gereksinim(b, zorunlu=False)
    if b.prova:
        b.kontrol(
            "temiz başlangıç: forge main = demo-baseline, locator baseline",
            durum.get("locator_durumu") in ("baseline", None)
            and (durum.get("forge") or {}).get("main_baseline_mi") is True,
            "make demo-reset ya da scripts/demo-prova.sh (tam sıfırlama)",
        )
        b.kontrol(
            "çalışan demo-app-web forge main'ini yansıtıyor",
            (durum.get("uygulama") or {}).get("main_ile_eslesiyor") is True,
            f"{durum.get('uygulama')} — scripts/forge-init.sh sync-web",
        )
        b.kontrol(
            f"temiz başlangıç: {STORY} henüz incelenmedi",
            req is None or (req.get("durum") == "new" and not req.get("son_kontrol")),
            f"{STORY} durumu {req and req.get('durum')!r}: Demo-A tekrar oynatılamaz; "
            "önce `make reset` (scripts/demo-prova.sh bunu yapar)",
        )
        acik = [s for s in b.api.get("muhendis", "/scripts") if s.get("durum") != "closed"]
        b.kontrol("temiz başlangıç: açık script yok", not acik, f"{len(acik)} açık script")
        ci_bosta_bekle(b, 300)
        temel_kosu_bekle(b)
        acilis_sayaci_kontrol(b, req)
    else:
        b.kontrol(f"denetim: {STORY} portalda", req is not None)
        # Denetimde ai_call süzgeci gereksinimin ilk çekiminden başlar.
        if req and req.get("cekim_zamani"):
            b.veri["baslangic_iso"] = req["cekim_zamani"]


# ---------------------------------------------------------------- Demo-A (adım 1–4)


def jira_cek(b: Baglam) -> None:
    if b.prova:
        y = b.api.post("analist", "/requirements/sync", beklenen=(200,))
        b.kanit["sync"] = y.get("sonuc")
        b.kontrol(
            f"{STORY} Jira'dan (jira-sim) çekildi",
            STORY in (y.get("sonuc") or {}),
            y.get("mesaj", ""),
        )
    req = gereksinim(b)
    b.veri["req_id"] = req["id"]
    acs = [a["ref"] for a in req.get("kabul_kriterleri") or []]
    b.kanit["ac"] = acs
    b.kontrol("6 kabul kriteri ayrıştırıldı", acs == [f"AC{i}" for i in range(1, 7)], str(acs))
    b.kontrol("AC eksik değil", req.get("ac_missing") is False)


def on_inceleme(b: Baglam) -> None:
    req_id = b.veri["req_id"]
    if b.prova:
        b.api.post("analist", f"/requirements/{req_id}/review", beklenen=(202,))
        req = gereksinim_bekle(
            b,
            "ön inceleme + tutarlılık denetimi bitti (findings_open)",
            lambda r: r.get("durum") in ("findings_open", "failed", "pending_po"),
            60,
        )
        b.kontrol("durum findings_open", req["durum"] == "findings_open", req["durum"])
    f = bulgular_tur1(b, req_id)
    b.kanit["bulgular"] = {
        k: {"tur": v["type"], "doc_ref": v["doc_ref"], "mode": v.get("mode")} for k, v in f.items()
    }
    b.kontrol("4 doğrulanmış bulgu (F1–F4)", sorted(f) == ["F1", "F2", "F3", "F4"], str(sorted(f)))
    for no, tur in BULGU_TURLERI.items():
        b.kontrol(f"{no} türü {tur}", f[no]["type"] == tur, f[no]["type"])
        b.kontrol(f"{no} kanıtı deterministik doğrulandı", f[no].get("kanit_dogrulandi") is True)
        mod_kontrol(b, no, f[no].get("mode"))
    b.kontrol(
        "F2 kanıtı campaign.py:23 (`return adet // 6`)",
        any(
            e.get("path", "").endswith("campaign.py") and e.get("line") == 23
            for e in f["F2"]["evidence"]
        ),
    )


def bulgu_kararlari(b: Baglam) -> None:
    req_id = b.veri["req_id"]
    if b.prova:
        for no, f in bulgular_tur1(b, req_id).items():
            if f.get("karar") is None:
                b.api.post(
                    "analist",
                    f"/findings/{f['id']}/decision",
                    {"karar": KARARLAR[no], "icerik_hash": f["icerik_hash"]},
                    beklenen=(200,),
                )
    f = bulgular_tur1(b, req_id)
    b.kanit["kararlar"] = {k: v.get("karar") for k, v in f.items()}
    for no, karar in KARARLAR.items():
        b.kontrol(
            f"{no} kararı {karar} (f2-kod-hatasi)",
            f[no].get("karar") == karar,
            str(f[no].get("karar")),
        )
        b.kontrol(
            f"{no} kararı analist oturumuyla",
            f[no].get("karar_veren") == "analist",
            str(f[no].get("karar_veren")),
        )
    for no in ("F2", "F4"):
        b.kontrol(f"{no} code_defect → bug taslağı açıldı", bool(f[no].get("bug_draft_id")))
        b.veri[f"taslak_{no}"] = f[no].get("bug_draft_id")


def dokuman_duzelt(b: Baglam) -> None:
    req_id = b.veri["req_id"]
    if b.prova:
        b.api.post("analist", f"/requirements/{req_id}/apply-doc-fixes", {}, beklenen=(200, 202))
        req = gereksinim_bekle(
            b,
            "düzeltmeler Jira'ya yazıldı, 2. tur temiz, PO teyidi bekleniyor",
            lambda r: (
                r.get("durum") in ("pending_po", "po_approved", "failed")
                or (r.get("durum") == "findings_open" and (r.get("kontrol_turu") or 1) > 1)
            ),
            90,
        )
        b.kontrol("durum pending_po", req["durum"] == "pending_po", req["durum"])
        jira_tpd1 = b.jira.issue(STORY, "labels")
        etiketler = jira_tpd1["fields"]["labels"]
        b.kanit["jira_etiketleri"] = etiketler
        b.kontrol("jira-sim: tp-po-pending etiketi", "tp-po-pending" in etiketler, str(etiketler))
        # po_istegi yalnızca PO beklenirken dolu (onaydan sonra None): denetim kipinde bakılmaz.
        b.kontrol(
            "PO soru yorumu Jira'ya yazıldı",
            (req.get("po_istegi") or {}).get("durum") == "yazildi",
            str(req.get("po_istegi")),
        )
    req = b.api.get("analist", f"/requirements/{req_id}")
    ac = {a["ref"]: a["metin"] for a in req["kabul_kriterleri"]}
    b.kanit["tur"] = req.get("kontrol_turu")
    b.kontrol(
        "ikinci kontrol turu koştu (TPD-1-r2)",
        (req.get("kontrol_turu") or 0) >= 2,
        str(req.get("kontrol_turu")),
    )
    b.kontrol("AC2 özgün kaldı (7 adette 1 bedava)", ac.get("AC2") == AC2_OZGUN, ac.get("AC2", ""))
    b.kontrol(
        "AC3 F1/F3 düzeltmesiyle güncellendi",
        ac.get("AC3", "").startswith(AC3_DUZELTME_ONEKI),
        ac.get("AC3", ""),
    )


def po_teyidi(b: Baglam) -> None:
    if b.prova:
        b.jira.po_onayla(STORY)  # PO insan kapısı: jira-sim'de po@sim.local kimliğiyle etiket
    req = gereksinim_bekle(
        b,
        "PO onayı çekirdeğe işlendi (TP_PO_POLL_S)",
        lambda r: (r.get("po") or {}).get("durum") == "approved",
        60,
    )
    b.kanit["po"] = req["po"]
    b.kontrol(
        "PO onayı po@sim.local (Jira kanalı)",
        req["po"].get("onaylayan") == "po@sim.local",
        str(req["po"]),
    )
    b.kontrol("onay içerik hash'ine bağlı", bool(req["po"].get("onaylanan_hash")))


def case_uret(b: Baglam) -> None:
    req_id = b.veri["req_id"]
    if b.prova:
        b.api.post("analist", f"/requirements/{req_id}/generate-cases", beklenen=(202,))
        gereksinim_bekle(
            b,
            f"{CASE_SAYISI} case üretildi",
            lambda r: r.get("durum") in ("cases_ready", "failed"),
            60,
        )
    cs = caseler(b, req_id)
    b.kanit["caseler"] = {n: c["icerik"].get("title") for n, c in sorted(cs.items())}
    b.kontrol(f"{CASE_SAYISI} case", len(cs) == CASE_SAYISI, str(len(cs)))
    b.kontrol(
        "C3 = 6 adet sınır case'i", (cs.get(3) or {}).get("icerik", {}).get("title") == C3_BASLIK
    )
    for n, c in cs.items():
        mod_kontrol(b, f"C{n}", c.get("mode"))


def qa_kararlari(b: Baglam) -> None:
    req_id = b.veri["req_id"]
    if b.prova:
        for _n, c in sorted(caseler(b, req_id).items()):
            if c["durum"] != "draft":
                continue
            b.api.post("analist", f"/cases/{c['id']}/viewed", beklenen=(200, 201, 204))
            b.api.post(
                "analist",
                f"/cases/{c['id']}/decision",
                {"karar": "approve", "icerik_hash": c["icerik_hash"]},
                beklenen=(200,),
            )
    cs = caseler(b, req_id)
    onayli = [n for n, c in cs.items() if c["durum"] in ("approved", "published")]
    b.kontrol("10 case QA onaylı (analist)", len(onayli) == CASE_SAYISI, f"{len(onayli)}/{len(cs)}")
    m = b.api.get("analist", f"/requirements/{req_id}/case-metrics")
    b.kanit["kabul_orani"] = m.get("kabul_orani")
    b.kontrol(
        "kabul oranı ≥ hedef (0,70)",
        (m.get("kabul_orani") or 0) >= (m.get("kabul_hedefi") or 0.7),
        str(m.get("kabul_orani")),
    )


def yayin(b: Baglam) -> None:
    req_id = b.veri["req_id"]
    if b.prova:
        on = b.api.get("analist", f"/publish/preview?requirement_id={req_id}")
        islemler = {k["islem"] for k in on["kalemler"]}
        b.kontrol("yayın önizlemesi: tüm kalemler create", islemler == {"create"}, str(islemler))
        ids = [k["case_id"] for k in on["kalemler"] if k["islem"] == "create"]
        y = b.api.post("analist", "/publish", {"case_ids": ids}, beklenen=(200,))
        durumlar = {s["durum"] for s in y["sonuclar"]}
        b.kontrol("yayın: hepsi created", durumlar == {"created"}, str(durumlar))
    cs = caseler(b, req_id)
    anahtarlar = {n: c.get("jira_test_key") for n, c in sorted(cs.items())}
    b.kanit["test_issuelari"] = anahtarlar
    b.kontrol(
        "10 case Jira'da Test issue",
        all(anahtarlar.values()) and len(anahtarlar) == CASE_SAYISI,
        str(anahtarlar),
    )
    b.veri["test_anahtarlari"] = anahtarlar
    c3 = b.jira.issue(anahtarlar[3], "issuetype,labels")
    b.kontrol("jira-sim: C3 Test issue türü Test", c3["fields"]["issuetype"]["name"] == "Test")
    b.kontrol(
        "jira-sim: AI-generated etiketi",
        "AI-generated" in c3["fields"]["labels"],
        str(c3["fields"]["labels"]),
    )


# ---------------------------------------------------------------- Demo-B (adım 5–11)


def kod_uret(b: Baglam) -> None:
    cs = caseler(b, b.veri["req_id"])
    if b.prova:
        t0 = b.saat()
        y = b.api.post(
            "muhendis",
            "/code/generate",
            {"case_ids": [cs[n]["id"] for n in KOD_CASELERI]},
            beklenen=(202,),
        )
        ids = y.get("script_ids") or []
        b.kontrol("4 script üretimi başladı", len(ids) == len(KOD_CASELERI), str(len(ids)))
        bitis: dict[str, float] = {}

        def hepsi_bitti():
            for sid in ids:
                if sid in bitis:
                    continue
                d = b.api.get("muhendis", f"/scripts/{sid}")
                if d.get("durum") not in SURUYOR:
                    bitis[sid] = b.saat() - t0
            return len(bitis) == len(ids)

        b.bekle(
            "4 script için kod üretimi bitti",
            hepsi_bitti,
            AJAN_BUTCESI_S * len(ids) + 60,
            aralik_s=2,
        )
        # Üretim sıralı (ajan bayisi kilidi): script süresi = kendi bitişi − öncekinin bitişi.
        onceki, sureler = 0.0, {}
        for sid, t in sorted(bitis.items(), key=lambda kv: kv[1]):
            sureler[sid] = round(t - onceki, 1)
            onceki = t
        b.veri["ajan_sureleri"] = sureler
    scr = {n: script_bul(b, n) for n in KOD_CASELERI}
    for n, s in scr.items():
        dogrula(s is not None, f"C{n} için script yok")
    b.veri["scriptler"] = {n: s["id"] for n, s in scr.items()}
    sureler = b.veri.get("ajan_sureleri", {})
    b.kanit["scriptler"] = {
        f"C{n}": {
            "durum": s["durum"],
            "yerel_sinif": s.get("yerel_sinif"),
            "pr": (s.get("pr") or {}).get("number"),
            "mode": s.get("mode"),
            "sure_s": sureler.get(s["id"]),
        }
        for n, s in scr.items()
    }
    for n in PR_CASELERI:
        s = scr[n]
        b.kontrol(
            f"C{n}: yerel kontrol geçti (tsc/eslint/AST + 3/3)",
            (s.get("yerel_kontrol") or {}).get("sinif") == "gecti",
            str((s.get("yerel_kontrol") or {}).get("aciklama")),
        )
        b.kontrol(
            f"C{n}: PR açıldı (LocalForge)", bool((s.get("pr") or {}).get("number")), s["durum"]
        )
    c3 = scr[3]
    b.kontrol(
        "C3: defect adayı (PR açılmaz, onarım yok)",
        c3["durum"] == "blocked"
        and (c3.get("engel") or {}).get("tur") == "defect_candidate"
        and c3.get("yerel_sinif") == "defect_adayi"
        and not (c3.get("pr") or {}).get("number"),
        f"{c3['durum']} / {(c3.get('engel') or {}).get('tur')}",
    )
    basarisiz = (c3.get("yerel_kontrol") or {}).get("basarisiz") or []
    b.kontrol(
        'C3: beklenen "0", gerçekleşen "1" (3/3 tekrar)',
        any(
            x.get("beklenen") == '"0"' and x.get("gerceklesen") == '"1"' and x.get("tekrar") == 3
            for x in basarisiz
        ),
        str(basarisiz)[:300],
    )
    for n, s in scr.items():
        mod_kontrol(b, f"C{n} eşleme", s.get("mode"))
        sapma = [
            a
            for a in s.get("adimlar") or []
            if "REPLAY sapması" in (a.get("ozet") or "") + (a.get("aciklama") or "")
        ]
        b.kontrol(f"C{n}: REPLAY sapması yok", not sapma, f"{len(sapma)} adım")
        gecikme = [u for u in s.get("uyarilar") or [] if "REPLAY'e geçmeyi" in u]
        b.kontrol(
            f"C{n}: adım 5 gecikme bütçesi aşılmadı (çekirdek ölçümü)",
            not gecikme,
            "; ".join(gecikme),
        )
        if s["id"] in sureler:
            b.kontrol(
                f"C{n}: ajan süresi ≤ {AJAN_BUTCESI_S:.0f} sn",
                sureler[s["id"]] <= AJAN_BUTCESI_S,
                f"{sureler[s['id']]} sn",
            )


def _kirma_kosulari(b: Baglam, sid: str) -> list[dict[str, Any]]:
    ks = [
        k
        for k in kosular(b, f"tetik=break_verify&script_id={sid}")
        if k.get("tetik") == "break_verify"
    ]
    return sorted(ks, key=lambda k: k.get("olusturma") or "")[-3:]


def kirarak_dogrula(b: Baglam) -> None:
    ids = b.veri["scriptler"]
    if b.prova:
        for n in (2, 1, 5):
            b.api.post("muhendis", f"/scripts/{ids[n]}/break-verify", beklenen=(202,))
        b.bekle(
            "üç kırarak doğrulama bitti",
            lambda: all(
                b.api.get("muhendis", f"/scripts/{ids[n]}")["break_verify"]["durum"]
                not in ("not_started", "running", "queued")
                for n in (2, 1, 5)
            ),
            300,
            aralik_s=5,
        )
        for n, beklenen in ((2, "passed"), (1, "weak"), (5, "weak")):
            d = b.api.get("muhendis", f"/scripts/{ids[n]}")["break_verify"]
            b.kontrol(
                f"C{n}: kırarak doğrulama {beklenen}",
                d["durum"] == beklenen,
                f"{d['durum']}: {d.get('neden')}",
            )
    # Koşu kayıtlarından (denetim kipinde de geçerli; dal güncellemesi script alanını sıfırlar)
    sonuc = {}
    for n in (2, 1, 5):
        ks = _kirma_kosulari(b, ids[n])
        sonuc[f"C{n}"] = [k.get("durum") for k in ks]
    b.kanit["kirma_kosulari"] = sonuc
    b.kontrol(
        "C2: yeşil → kırmızı → yeşil (test hata yakalıyor ✓)",
        sonuc["C2"] == ["passed", "failed", "passed"],
        str(sonuc["C2"]),
    )
    for n in (1, 5):
        b.kontrol(
            f"C{n}: zayıf test (kırılmada yeşil kaldı)",
            sonuc[f"C{n}"] == ["passed"] * 3,
            str(sonuc[f"C{n}"]),
        )


def _pr_hazir(b: Baglam, sid: str, eski_head: str | None) -> dict[str, Any] | None:
    s = b.api.get("muhendis", f"/scripts/{sid}")
    pr = s.get("pr") or {}
    if pr.get("durum") != "open":
        return s if pr.get("durum") == "merged" else None
    if eski_head and pr.get("head_sha") == eski_head:
        return None  # dal main'e taşınmadı (codegen.update_branch bekleniyor)
    dal = pr.get("dal") or {}
    checks = [c.get("durum") for c in pr.get("checks") or []]
    if dal.get("geride") or dal.get("yabanci") or checks != ["passed"] or s.get("merge_engelleri"):
        return None
    return s


def _head(b: Baglam, sid: str) -> str | None:
    return (b.api.get("muhendis", f"/scripts/{sid}").get("pr") or {}).get("head_sha")


def merge(b: Baglam) -> None:
    ids = b.veri["scriptler"]
    if b.prova:
        # Merge main'i ilerletir; kalan bot PR'ları codegen.update_branch ile yeni head'e taşınır
        # (kırma not_started, PR CI yeniden). Head'i merge'den ÖNCE kaydedip değişmesini bekleriz.
        eski: dict[int, str | None] = {n: None for n in MERGE_SIRASI}
        for i, n in enumerate(MERGE_SIRASI):
            s = b.bekle(
                f"C{n} PR'ı merge'e hazır (local-ci yeşil, dal güncel)",
                lambda n=n: _pr_hazir(b, ids[n], eski[n]),
                240,
                aralik_s=4,
            )
            pr = s["pr"]
            kalanlar = MERGE_SIRASI[i + 1 :]
            if pr.get("durum") != "merged":
                for m in kalanlar:
                    eski[m] = _head(b, ids[m])
                govde = {"icerik_hash": pr["icerik_hash"], "head_sha": pr["head_sha"]}
                if s.get("merge_kabul_gerekli"):
                    # zayıf test / kırma kanıtı yok: açık insan kabulü (review.gerekce)
                    govde["onay_notu"] = ONAY_NOTU
                r = b.api.post("muhendis", f"/prs/{pr['number']}/merge", govde, beklenen=(200, 202))
                b.kanit[f"merge_C{n}"] = {
                    "pr": pr["number"],
                    "durum": r.get("durum"),
                    "onay_notu": "onay_notu" in govde,
                }
            b.bekle(
                f"C{n} merged",
                lambda n=n: (
                    (b.api.get("muhendis", f"/scripts/{ids[n]}").get("pr") or {}).get("durum")
                    == "merged"
                ),
                60,
            )
    for n in PR_CASELERI:
        pr = b.api.get("muhendis", f"/scripts/{ids[n]}").get("pr") or {}
        b.kontrol(
            f"C{n} PR merge edildi (insan: muhendis)",
            pr.get("durum") == "merged" and pr.get("merge_eden") in ("muhendis", None),
            f"{pr.get('durum')} / {pr.get('merge_eden')}",
        )
        b.veri[f"merge_sha_C{n}"] = pr.get("merge_sha")
    b.veri["son_merge_sha"] = b.veri.get(f"merge_sha_C{MERGE_SIRASI[-1]}")


def ci_tetikleri(b: Baglam) -> None:
    sha = b.veri.get("son_merge_sha")
    dogrula(sha, "son merge sha'sı yok")
    push = kosu_bekle(
        b,
        "son merge'ün push CI'ı bitti",
        lambda ks: next(
            (k for k in ks if k.get("tetik") == "push" and k.get("commit") == sha), None
        ),
        300,
    )
    b.kontrol(
        "push CI (main) yeşil",
        push.get("durum") == "passed" and push.get("toplam") == push.get("gecen"),
        f"{push.get('durum')} {push.get('gecen')}/{push.get('toplam')}",
    )
    tetikler: dict[str, str] = {}
    if b.prova:
        for t in ("deploy", "nightly"):
            y = b.api.post("sunucu", "/ci/trigger", {"tetik": t}, beklenen=(202,))
            tetikler[t] = y.get("run_id")
    sonuc = {"push": push}
    for t in ("deploy", "nightly"):
        rid = tetikler.get(t)
        sonuc[t] = kosu_bekle(
            b,
            f"{t} koşusu bitti",
            lambda ks, t=t, rid=rid: next(
                (
                    k
                    for k in ks
                    if (
                        k.get("id") == rid
                        if rid
                        else (k.get("tetik") == t and k.get("commit") == sha)
                    )
                ),
                None,
            ),
            300,
        )
    b.kanit["kosular"] = {
        t: {
            "durum": k.get("durum"),
            "gecen": k.get("gecen"),
            "toplam": k.get("toplam"),
            "sure_ms": k.get("sure_ms"),
        }
        for t, k in sonuc.items()
    }
    for t in ("deploy", "nightly"):
        k = sonuc[t]
        b.kontrol(
            f"{t} CI yeşil (sunucu tetikledi)",
            k.get("durum") == "passed"
            and k.get("toplam") == k.get("gecen")
            and (k.get("toplam") or 0) > 0,
            f"{k.get('durum')} {k.get('gecen')}/{k.get('toplam')}",
        )
    rapor_baglantilari(b, sonuc["deploy"])
    for t, k in sonuc.items():
        b.kontrol(
            f"{t} CI ≤ {CI_BUTCESI_S:.0f} sn (§13)",
            (k.get("sure_ms") or 0) <= CI_BUTCESI_S * 1000,
            f"{(k.get('sure_ms') or 0) / 1000:.0f} sn",
            kritik=False,
        )


RAPOR_ALANLARI = (
    ("rapor_url", "Playwright HTML raporu"),
    ("junit_url", "JUnit XML"),
    ("allure_url", "Allure raporu"),
)


def api_yolu(url: str) -> str | None:
    """Portal göreli artefakt adresi (`/api/...`) → istemci yolu; dış adres → None."""
    return url[len("/api") :] if url.startswith("/api/") else None


def rapor_baglantilari(b: Baglam, kosu: dict[str, Any]) -> None:
    """§2 adım 9–10: koşu detayındaki rapor bağlantıları açılıyor mu (sahnede kırık link yok)."""
    durumlar: dict[str, Any] = {}
    for alan, ad in RAPOR_ALANLARI:
        url = kosu.get(alan)
        yol = api_yolu(url) if isinstance(url, str) else None
        if yol is None:
            durumlar[alan] = url and "dış adres"
            b.kontrol(f"{ad} bağlantısı var", bool(url), str(url))
            continue
        y = b.api.istek("sunucu", "GET", yol)
        durumlar[alan] = y.durum
        b.kontrol(f"{ad} açılıyor (HTTP 200)", y.durum == 200, f"HTTP {y.durum}")
    b.kanit["rapor_baglantilari"] = durumlar
    # Dürüstlük (adım 9): Sauce kimliği yokken koşu yerel Chromium'dur; sahte Sauce bağlantısı yok.
    b.kontrol(
        "koşu kaynağı dürüst (Sauce kimliği yoksa yerel, Sauce bağlantısı yok)",
        kosu.get("kaynak") == "sauce" or not kosu.get("sauce_url"),
        f"kaynak={kosu.get('kaynak')!r} sauce_url={'var' if kosu.get('sauce_url') else 'yok'}",
    )


def kontrol_kulesi(b: Baglam) -> None:
    ct = b.api.get("sunucu", "/control-tower")
    go = ct.get("gecme_orani") or {}
    ai = ct.get("ai_katkisi") or {}
    b.kanit["kontrol_kulesi"] = {
        "gecme_orani": go.get("oran"),
        "kosu": go.get("toplam"),
        "kabul_orani": ai.get("kabul_orani"),
        "script_ilk_review": ai.get("script_ilk_review"),
        "pass_at_1": ai.get("pass_at_1"),
        "defect_adayi": ai.get("script_defect_adayi"),
        "manuel_baz_ms": ai.get("manuel_baz_ms"),
        "a11y_ihlal": (ct.get("a11y") or {}).get("ihlal"),
    }
    b.kontrol(
        "geçme oranı + kaynağı",
        go.get("oran") is not None and "gecme_orani" in (ct.get("kaynaklar") or {}),
    )
    tetikler = {k.get("tetik") for k in ct.get("son_kosular") or []}
    b.kontrol(
        "son koşularda push/deploy/nightly",
        {"push", "deploy", "nightly"} <= tetikler,
        str(sorted(t for t in tetikler if t)),
    )
    b.kontrol(
        "kırma/yerel kontrol koşuları KPI'a girmez",
        not (tetikler & {"break_verify", "local_check"}),
        str(sorted(t for t in tetikler if t)),
    )
    b.kontrol(
        "açık defect adayı görünüyor (C3)",
        (ai.get("script_defect_adayi") or 0) >= 1,
        str(ai.get("script_defect_adayi")),
    )
    b.kontrol("kabul oranı görünüyor", ai.get("kabul_orani") is not None)
    baz = b.veri.get("manuel_baz_s") or ""
    hazirlik = ct.get("hazirlik") or []
    kaynaklar = sorted({str(h.get("manuel_baz_kaynagi")) for h in hazirlik})
    # Ölçüm yalnızca gözden geçirilmiş rules/baz-degerler.yaml'dan (sync'te uygulanır) gelebilir;
    # prova değer girmez (uydurulmaz). Ölçülmeyen story kazanca girmez; REPLAY'de yalnız-review
    # satırları başlık kazancına girmez (kazanc_replay_haric).
    try:
        dosya = b.api.get("sunucu", "/baseline-file")
    except Exception:  # eski çekirdek: dosya yok sayılır
        dosya = {}
    dosya_storyleri = {
        str(g.get("story"))
        for g in dosya.get("girdiler") or []
        if isinstance(g, dict) and g.get("story")
    }
    olcumlu = [h for h in hazirlik if h.get("manuel_baz_kaynagi") == "olcum"]
    olcum_dosyadan = all(h.get("story_key") in dosya_storyleri for h in olcumlu)
    b.kontrol(
        "ölçülmeyen story'de kazanç yok; ölçüm yalnız baz-degerler.yaml'dan",
        all(
            h.get("kazanc_orani") is None
            for h in hazirlik
            if h.get("manuel_baz_kaynagi") != "olcum"
        )
        and (not olcumlu or olcum_dosyadan)
        and (ai.get("kazanc_orani") is None or any(h.get("kazanca_girer") for h in hazirlik)),
        f"kaynaklar={kaynaklar} kazanc={ai.get('kazanc_orani')} "
        f"replay_haric={ai.get('kazanc_replay_haric')}",
    )
    if not olcumlu:
        b.kontrol(
            "ölçüm yok → başlıkta manuel baz/kazanç gösterilmez",
            ai.get("manuel_baz_ms") is None
            and ai.get("baz_deger_olculmedi") is True
            and ai.get("kazanc_orani") is None,
            f"manuel_baz_ms={ai.get('manuel_baz_ms')}",
        )
    if baz:
        b.kontrol(
            "varsayılan baz yalnızca ikincil alanda (TP_MANUAL_BASELINE_S; ölçüm sayılmaz)",
            ai.get("manuel_baz_varsayilan_ms") == int(float(baz) * 1000)
            and all(
                h.get("manuel_baz_ms") is None
                for h in hazirlik
                if h.get("manuel_baz_kaynagi") != "olcum"
            ),
            f"varsayilan_ms={ai.get('manuel_baz_varsayilan_ms')} ← TP_MANUAL_BASELINE_S={baz}",
        )
    m = b.api.get("analist", f"/requirements/{b.veri['req_id']}/case-metrics")
    if b.veri.get("model_modu") == "replay":
        b.kontrol(
            "REPLAY'de AI süresi ölçülmez uyarısı",
            any("REPLAY" in u for u in m.get("uyarilar") or []),
            str(m.get("uyarilar")),
        )


# ---------------------------------------------------------------- Faz 4: triage → bug (adım 12–14)


def _taslak(b: Baglam, taslak_id: str, hazir_bekle: bool = True) -> dict[str, Any]:
    def oku():
        d = b.api.get("testci", f"/bug-drafts/{taslak_id}")
        if not hazir_bekle:
            return d
        return (
            d
            if (d.get("hazirlik") or {}).get("durum") in ("hazir", "basarisiz")
            or d.get("durum") == "published"
            else None
        )

    return b.bekle("bug taslağı hazır (mükerrer araması + AI taslağı)", oku, 90)


def c3_triage(b: Baglam) -> None:
    c3 = b.api.get("muhendis", f"/scripts/{b.veri['scriptler'][3]}")
    fid = b.bekle(
        "C3 triage sonucu",
        lambda: b.api.get("muhendis", f"/scripts/{c3['id']}").get("failure_id"),
        60,
    )
    f = b.api.get("testci", f"/failures/{fid}")
    sinyaller = {s.get("kod") for s in f.get("eslesen_sinyaller") or []}
    b.kanit["triage"] = {
        "sinif": f.get("sinif"),
        "karar_kaynagi": f.get("karar_kaynagi"),
        "sinyaller": sorted(sinyaller),
    }
    b.kontrol("C3 → product_defect", f.get("sinif") == "product_defect", str(f.get("sinif")))
    b.kontrol(
        "karar kaynağı kural (AI çağrısı yok)",
        f.get("karar_kaynagi") == "rule",
        str(f.get("karar_kaynagi")),
    )
    b.kontrol(
        "4 sinyal (assertion_farki, eleman_bulundu, sayfa_yapisi_beklenen, tutarli_tekrar)",
        sinyaller >= C3_SINYALLERI,
        str(sorted(sinyaller)),
    )
    tid = (f.get("oneri") or {}).get("bug_draft_id") or f.get("bug_draft_id")
    dogrula(tid, "C3 için bug taslağı yok")
    d = _taslak(b, tid)
    b.veri["taslak_C3"] = tid
    adaylar = d.get("mukerrer_adaylari") or []
    b.kanit["taslak"] = {
        "aday": [(a.get("key"), a.get("likelihood")) for a in adaylar],
        "oneri": d.get("oneri"),
        "jql": d.get("jql"),
    }
    b.kontrol(
        "JQL yalnızca TPD-5'i buldu",
        [a.get("key") for a in adaylar] == [DUP_ADAYI],
        str([a.get("key") for a in adaylar]),
    )
    b.kontrol(
        "dup_rank TPD-5 = high",
        adaylar and adaylar[0].get("likelihood") == "high",
        str(adaylar[:1]),
    )
    b.kontrol(
        "öneri: TPD-5'e bağla",
        (d.get("oneri") or {}).get("recommendation") == "link"
        and (d.get("oneri") or {}).get("link_key") == DUP_ADAYI,
        str(d.get("oneri")),
    )
    mod_kontrol(b, "bug taslağı", d.get("mode"))


def _jira_yorum_sayisi(b: Baglam, anahtar: str) -> int:
    return int(
        ((b.jira.issue(anahtar, "comment")["fields"].get("comment")) or {}).get("total") or 0
    )


def _karar(b: Baglam, tid: str, karar: str, link_key: str | None = None) -> dict[str, Any]:
    d = b.api.get("testci", f"/bug-drafts/{tid}")
    if d.get("durum") == "published":
        return d
    govde: dict[str, Any] = {"karar": karar, "icerik_hash": d["icerik_hash"]}
    if link_key:
        govde["link_key"] = link_key
    b.api.post("testci", f"/bug-drafts/{tid}/decision", govde, beklenen=(200, 202))
    return b.bekle(
        "publish_bug bitti",
        lambda: (x := b.api.get("testci", f"/bug-drafts/{tid}")).get("durum") == "published" and x,
        60,
    )


def c3_bagla(b: Baglam) -> None:
    tid = b.veri["taslak_C3"]
    once = _jira_yorum_sayisi(b, DUP_ADAYI) if b.prova else None
    d = _karar(b, tid, "link", DUP_ADAYI) if b.prova else b.api.get("testci", f"/bug-drafts/{tid}")
    b.kanit["sonuc"] = {
        "durum": d.get("durum"),
        "karar": d.get("karar"),
        "jira_key": d.get("jira_key"),
        "sonuc_metni": d.get("sonuc_metni"),
    }
    b.kontrol(
        "testçi: TPD-5 kaydına bağlandı (yeni Bug yok)",
        d.get("durum") == "published"
        and d.get("karar") == "link"
        and d.get("jira_key") == DUP_ADAYI,
        str(b.kanit["sonuc"]),
    )
    b.kontrol("onaylayan testci", d.get("onaylayan") == "testci", str(d.get("onaylayan")))
    issue = b.jira.issue(DUP_ADAYI)
    lk = baglantilar(issue)
    c3_test = (b.veri.get("test_anahtarlari") or {}).get(3) or (
        caseler(b, b.veri["req_id"]).get(3) or {}
    ).get("jira_test_key")
    b.kanit["tpd5_baglantilari"] = lk
    b.kontrol("TPD-5 ↔ TPD-1 Relates", ("Relates", STORY) in lk, str(lk))
    b.kontrol(f"TPD-5 ↔ {c3_test} Test (C3'ün Test issue'su)", ("Test", c3_test) in lk, str(lk))
    if once is not None:
        b.kontrol(
            "TPD-5'e tek kanıt yorumu", _jira_yorum_sayisi(b, DUP_ADAYI) == once + 1, f"önce {once}"
        )
    y = b.api.istek(
        "testci",
        "POST",
        f"/bug-drafts/{tid}/decision",
        {"karar": "link", "icerik_hash": d.get("icerik_hash"), "link_key": DUP_ADAYI},
    )
    b.kontrol("ikinci karar 409 (idempotent)", y.durum == 409, f"HTTP {y.durum}")


def f2_bagla(b: Baglam) -> None:
    tid = b.veri.get("taslak_F2")
    dogrula(tid, "F2 bug taslağı yok")
    d = _taslak(b, tid)
    oneri = d.get("oneri") or {}
    if d.get("durum") != "published":
        b.kontrol(
            "F2 taslağı: TPD-5 high + bağla",
            oneri.get("recommendation") == "link" and oneri.get("link_key") == DUP_ADAYI,
            str(oneri),
        )
    if b.prova:
        d = _karar(b, tid, "link", DUP_ADAYI)
    b.kanit["sonuc"] = {
        "durum": d.get("durum"),
        "jira_key": d.get("jira_key"),
        "sonuc_metni": d.get("sonuc_metni"),
    }
    b.kontrol(
        "F2 → TPD-5'e bağlandı",
        d.get("durum") == "published" and d.get("jira_key") == DUP_ADAYI,
        str(b.kanit["sonuc"]),
    )
    lk = baglantilar(b.jira.issue(DUP_ADAYI))
    b.kontrol("bağlantılar tekrarlanmadı", lk.count(("Relates", STORY)) == 1, str(lk))


def f4_yeni(b: Baglam) -> None:
    tid = b.veri.get("taslak_F4")
    dogrula(tid, "F4 bug taslağı yok")
    d = _taslak(b, tid)
    if d.get("durum") != "published":
        b.kontrol(
            "F4: mükerrer adayı yok",
            not d.get("mukerrer_adaylari"),
            str(d.get("mukerrer_adaylari")),
        )
        b.kontrol(
            "F4: öneri yeni kayıt",
            (d.get("oneri") or {}).get("recommendation") == "new",
            str(d.get("oneri")),
        )
    if b.prova:
        d = _karar(b, tid, "new")
    anahtar = d.get("jira_key")
    b.kanit["sonuc"] = {
        "durum": d.get("durum"),
        "jira_key": anahtar,
        "sonuc_metni": d.get("sonuc_metni"),
    }
    b.kontrol(
        "F4 → yeni Bug açıldı",
        d.get("durum") == "published"
        and d.get("karar") == "new"
        and anahtar
        and anahtar != DUP_ADAYI,
        str(b.kanit["sonuc"]),
    )
    if anahtar and not d.get("jira_silindi"):
        i = b.jira.issue(anahtar)
        f = i["fields"]
        b.kontrol("jira-sim: tür Bug", f["issuetype"]["name"] == "Bug", f["issuetype"]["name"])
        b.kontrol(
            "jira-sim: AI-generated + tp-<uuid> etiketi",
            "AI-generated" in f["labels"] and f"tp-{tid}" in f["labels"],
            str(f["labels"]),
        )
        if b.veri.get("model_modu") == "replay":
            b.kontrol(
                "jira-sim: REPLAY etiketi (tp-mod-replay)",
                "tp-mod-replay" in f["labels"],
                str(f["labels"]),
            )
        b.kontrol(
            "jira-sim: Relates TPD-1", ("Relates", STORY) in baglantilar(i), str(baglantilar(i))
        )


def kirma_taslagi(b: Baglam) -> None:
    """C2 kırmızı aşaması → product_defect (kaynak=kirma) → taslak. Karar sunucuya kalır."""
    fs = b.api.get("testci", f"/failures?kaynak=kirma&script_id={b.veri['scriptler'][2]}&limit=50")
    b.kontrol("kırma koşusu triage edildi (kaynak=kirma)", bool(fs), f"{len(fs)} hata")
    f = fs[0]
    b.kontrol("kırma → product_defect", f.get("sinif") == "product_defect", str(f.get("sinif")))
    tid = (f.get("oneri") or {}).get("bug_draft_id") or f.get("bug_draft_id")
    dogrula(tid, "kırma taslağı yok")
    b.veri["taslak_kirma"] = tid
    d = _taslak(b, tid)
    adaylar = d.get("mukerrer_adaylari") or []
    b.kanit["kirma"] = {
        "aday": [(a.get("key"), a.get("likelihood")) for a in adaylar],
        "oneri": d.get("oneri"),
        "durum": d.get("durum"),
    }
    b.kontrol(
        "TPD-5 ters belirti → medium",
        any(a.get("key") == DUP_ADAYI and a.get("likelihood") == "medium" for a in adaylar),
        str(b.kanit["kirma"]["aday"]),
    )
    b.kontrol(
        "öneri yeni kayıt (karar sunucuya bırakıldı)",
        (d.get("oneri") or {}).get("recommendation") == "new",
        str(d.get("oneri")),
    )


def kirma_yeni_bug(b: Baglam) -> None:
    """İsteğe bağlı (--kirma-yayinla): CI hatası → yeni Bug, story + Test issue bağlı (§2 adım 14).

    Sahnede kırma taslağı bilerek karara bırakılır; bu adım yeni Bug yolunu uçtan uca prova eder.
    """
    tid = b.veri.get("taslak_kirma")
    dogrula(tid, "kırma taslağı yok (C5)")
    d = _taslak(b, tid)
    c2_test = (b.veri.get("test_anahtarlari") or {}).get(2)
    test_key = (d.get("icerik") or {}).get("test_case_key") or c2_test
    if c2_test:
        b.kontrol(
            "taslak C2'nin Test issue'suna bağlı", test_key == c2_test, f"{test_key} ≠ {c2_test}"
        )
    if b.prova:
        d = _karar(b, tid, "new")
    anahtar = d.get("jira_key")
    b.kanit["sonuc"] = {"durum": d.get("durum"), "jira_key": anahtar, "test": test_key}
    b.kontrol(
        "kırma taslağı → yeni Bug yayınlandı",
        d.get("durum") == "published"
        and d.get("karar") == "new"
        and bool(anahtar)
        and anahtar != DUP_ADAYI,
        str(b.kanit["sonuc"]),
    )
    dogrula(test_key, "C2'nin Test issue anahtarı bulunamadı")
    if anahtar and not d.get("jira_silindi"):
        i = b.jira.issue(anahtar)
        lk = baglantilar(i)
        b.kanit["baglantilar"] = lk
        b.kontrol("jira-sim: tür Bug", i["fields"]["issuetype"]["name"] == "Bug")
        b.kontrol(f"jira-sim: Relates {STORY}", ("Relates", STORY) in lk, str(lk))
        b.kontrol(
            f"jira-sim: Test {test_key} (C2'nin Test issue'su)", ("Test", test_key) in lk, str(lk)
        )


# ---------------------------------------------------------------- P1 güvenlik


def guvenlik(b: Baglam) -> None:
    """§13 kontrol listesi: `make security-check` 10/10, bot kimliğiyle main'e push reddi."""
    r = b.yigin.make("security-check", 300)
    ozet = next((x for x in reversed(r.cikti.splitlines()) if x.startswith("Özet:")), "")
    b.kanit["security_check"] = {"kod": r.kod, "ozet": ozet, "sure_s": r.sure_s}
    b.kontrol("make security-check çıkış 0 (10/10)", r.kod == 0, ozet or f"çıkış {r.kod}")
    if not b.prova:
        return  # denetim kipi yığını değiştirmez; push denemesi yalnızca provada
    p = b.yigin.bot_main_push_dene()
    b.kanit["bot_main_push"] = p
    b.kontrol("bot main'e push denemesi koştu", p is not None, "core-worker'a erişilemedi")
    b.kontrol(
        "bot kimliğiyle main'e doğrudan commit reddedildi (ForgeProtectionError)",
        p.get("reddedildi") is True,
        str(p),
    )
    b.kontrol("forge main değişmedi", p.get("main_degismedi") is True, str(p))


# ---------------------------------------------------------------- Faz 4: locator kırma → onarım


def locator_kir(b: Baglam) -> None:
    if b.prova:
        ci_bosta_bekle(b, 300)  # sahne notu: önceki push/baseline koşusu bitmeden kırma
        r = b.yigin.make("demo-break", 600)
        b.kanit["make_demo_break"] = {
            "kod": r.kod,
            "sure_s": r.sure_s,
            "cikti_son": r.cikti.strip().splitlines()[-4:],
        }
        b.kontrol(
            "make demo-break çıkış 0",
            r.kod == 0,
            r.cikti.strip().splitlines()[-1] if r.cikti.strip() else "",
        )
        durum = b.api.get("sunucu", "/demo/status")
        b.kontrol(
            "locator_durumu kirik",
            durum.get("locator_durumu") == "kirik",
            str(durum.get("locator_durumu")),
        )
        b.kontrol(
            "forge testId cart-add",
            (durum.get("forge") or {}).get("testid") == "cart-add",
            str(durum.get("forge")),
        )
        b.kontrol(
            "çalışan uygulama main'i yansıtıyor",
            (durum.get("uygulama") or {}).get("main_ile_eslesiyor") is True,
            str(durum.get("uygulama")),
        )
        b.veri["kirik_main"] = (durum.get("forge") or {}).get("main")
    else:
        durum = b.api.get("sunucu", "/demo/status")
        b.kontrol(
            "denetim: kırma yapılmış",
            durum.get("locator_durumu") in ("kirik", "onarildi"),
            str(durum.get("locator_durumu")),
        )


def _kirmizi_push(ks: list[dict[str, Any]], sha: str | None) -> dict[str, Any] | None:
    for k in ks:
        if k.get("tetik") != "push":
            continue
        if sha and k.get("commit") == sha:
            return k
        if not sha and k.get("durum") == "failed" and k.get("basarisiz") in LOCATOR_KIRMIZI:
            return k
    return None


def locator_triage(b: Baglam) -> None:
    sha = b.veri.get("kirik_main")
    k = kosu_bekle(b, "kırık main'in push CI'ı bitti", lambda ks: _kirmizi_push(ks, sha), 360)
    b.veri["kirik_kosu"] = k["id"]
    b.kontrol(
        f"push CI kırmızı, {LOCATOR_KIRMIZI[0]} ya da {LOCATOR_KIRMIZI[1]} hata",
        k.get("durum") == "failed" and k.get("basarisiz") in LOCATOR_KIRMIZI,
        f"{k.get('durum')} {k.get('basarisiz')}/{k.get('toplam')}",
    )
    b.kontrol(
        "sağlık kontrolü geçti (ortam hatası değil)",
        not k.get("saglik_hatasi"),
        str(k.get("saglik_hatasi")),
    )
    hatalar = b.bekle(
        "tüm kırmızılar triage edildi",
        lambda: (
            (fs := b.api.get("muhendis", f"/failures?run_id={k['id']}&limit=200"))
            and len(fs) >= (k.get("basarisiz") or 1)
            and fs
        ),
        120,
    )
    siniflar = {(f.get("sinif"), f.get("alt_tur")) for f in hatalar}
    b.kanit["triage"] = {"hata": len(hatalar), "siniflar": sorted(map(str, siniflar))}
    b.kontrol(
        "hepsi test_maintenance/locator",
        siniflar == {("test_maintenance", "locator")},
        str(siniflar),
    )
    b.kontrol(
        "onarım önerisi (locator_fix) var",
        all(f.get("oneri_turu") == "locator_fix" for f in hatalar),
    )
    b.veri["onarim_hatasi"] = hatalar[0]["id"]
    kanit = " ".join(str(s.get("kanit")) for s in hatalar[0].get("eslesen_sinyaller") or [])
    b.kontrol(
        "kanıtta add-to-cart, kapsam product-card-P-00x",
        "add-to-cart" in kanit and "product-card-P-00" in kanit,
        kanit[:200],
        kritik=False,
    )


def _yama_satirlari(yama: str) -> tuple[list[str], list[str]]:
    eksi = [s for s in yama.splitlines() if s.startswith("-") and not s.startswith("---")]
    arti = [s for s in yama.splitlines() if s.startswith("+") and not s.startswith("+++")]
    return eksi, arti


def onarim_pr(b: Baglam) -> None:
    fid = b.veri["onarim_hatasi"]
    if b.prova:
        b.api.post("muhendis", f"/failures/{fid}/fix", beklenen=(202,))
    o = b.bekle(
        "onarım PR'ı açıldı (AST + tam paket yerel kontrol)",
        lambda: (
            (x := b.api.get("muhendis", f"/failures/{fid}/fix")).get("durum")
            in ("pr_open", "merged", "blocked", "failed")
            and x
        ),
        180,
    )
    eksi, arti = _yama_satirlari(o.get("yama") or "")
    yk = o.get("yerel_kontrol") or {}
    b.kanit["onarim"] = {
        "durum": o.get("durum"),
        "pr": (o.get("pr") or {}).get("number"),
        "dosya": o.get("dosya"),
        "eski": o.get("eski_test_id"),
        "yeni": o.get("yeni_test_id"),
        "test_sayilari": yk.get("test_sayilari"),
    }
    b.kontrol(
        "onarım PR'ı açık",
        o.get("durum") in ("pr_open", "merged") and not o.get("engellendi"),
        f"{o.get('durum')} {o.get('engel')}",
    )
    b.kontrol(
        "yalnızca e2e/pages/catalog/locators.ts",
        o.get("dosya") == "e2e/pages/catalog/locators.ts",
        str(o.get("dosya")),
    )
    b.kontrol(
        "testId add-to-cart → cart-add",
        (o.get("eski_test_id"), o.get("yeni_test_id")) == ("add-to-cart", "cart-add"),
    )
    b.kontrol(
        "yama tek satır",
        len(eksi) == 1 and len(arti) == 1 and "add-to-cart" in eksi[0] and "cart-add" in arti[0],
        f"-{len(eksi)} +{len(arti)}",
    )
    b.kontrol(
        "AST koruması (repair) geçti",
        (o.get("ast_guard") or {}).get("ok") is True,
        str(o.get("ast_guard")),
    )
    sayi = yk.get("test_sayilari") or {}
    b.kontrol(
        "tam paket yerel kontrol yeşil",
        yk.get("sonuc") == "success"
        and yk.get("kapsam") == "tam_paket"
        and sayi.get("unexpected") == 0,
        f"{yk.get('sonuc')} {yk.get('kapsam')} {sayi}",
    )
    b.kontrol(
        "AI üretimi değil (deterministik onarım)",
        o.get("ai_uretimi") is False,
        str(o.get("ai_uretimi")),
    )
    b.kontrol(
        "çalışan uygulama sha eşleşmesi",
        (o.get("probe") or {}).get("sha_eslesmesi") == "eslesiyor",
        str((o.get("probe") or {}).get("sha_eslesmesi")),
    )


def onarim_merge(b: Baglam) -> None:
    fid = b.veri["onarim_hatasi"]
    o = b.api.get("muhendis", f"/failures/{fid}/fix")
    pr = o.get("pr") or {}
    if b.prova and pr.get("durum") == "open":
        govde = {"icerik_hash": pr["icerik_hash"], "head_sha": pr["head_sha"]}

        def dene():
            y = b.api.istek("muhendis", "POST", f"/prs/{pr['number']}/merge", govde)
            if y.durum in (200, 202):
                return y
            if y.durum == 409 and "local-ci" in str(y.govde):
                return None  # merge kapısı: local-ci henüz yazılmadı / bekliyor
            raise ApiHatasi("POST", f"/prs/{pr['number']}/merge", y.durum, y.govde)

        b.bekle("onarım PR'ı merge edildi (hash + head bağlı insan onayı)", dene, 180, aralik_s=5)
    o = b.bekle(
        "onarım merged",
        lambda: (x := b.api.get("muhendis", f"/failures/{fid}/fix")).get("durum") == "merged" and x,
        90,
    )
    b.veri["onarim_merge_sha"] = (o.get("pr") or {}).get("merge_sha")
    b.kontrol(
        "onarım PR'ı merge edildi", (o.get("pr") or {}).get("durum") == "merged", str(o.get("pr"))
    )
    kardes = b.bekle(
        "kardeş hatalar aynı PR'la merged",
        lambda: (
            (fs := b.api.get("muhendis", f"/failures?run_id={b.veri['kirik_kosu']}&limit=200"))
            and all(f.get("oneri_durumu") == "merged" for f in fs)
            and fs
        ),
        90,
    )
    b.kanit["kardes"] = len(kardes)
    b.kontrol(
        "kardeş hatalar tek onarımı paylaştı", len(kardes) in LOCATOR_KIRMIZI, str(len(kardes))
    )


def ci_yesil(b: Baglam) -> None:
    sha = b.veri.get("onarim_merge_sha")
    dogrula(sha, "onarım merge sha'sı yok")
    k = kosu_bekle(
        b,
        "onarım merge'ünün push CI'ı bitti",
        lambda ks: next(
            (x for x in ks if x.get("tetik") == "push" and x.get("commit") == sha), None
        ),
        300,
    )
    b.kanit["push"] = {
        "durum": k.get("durum"),
        "gecen": k.get("gecen"),
        "toplam": k.get("toplam"),
        "sure_ms": k.get("sure_ms"),
    }
    b.kontrol(
        "push CI yeşile döndü",
        k.get("durum") == "passed"
        and k.get("gecen") == k.get("toplam")
        and (k.get("toplam") or 0) > 0,
        f"{k.get('gecen')}/{k.get('toplam')}",
    )
    durum = b.api.get("sunucu", "/demo/status")
    b.kontrol(
        "locator_durumu onarildi",
        durum.get("locator_durumu") == "onarildi",
        str(durum.get("locator_durumu")),
    )


# ---------------------------------------------------------------- son denetim


def son_denetim(b: Baglam) -> None:
    kipler = b.yigin.ai_call_kipleri(b.veri["baslangic_iso"])
    b.kanit["ai_call"] = kipler
    # API'den bağımsız çapraz kontrol: Kontrol Kulesi tüm model çağrılarını kipe göre sayar.
    ai = (b.api.get("sunucu", "/control-tower").get("ai_katkisi")) or {}
    b.kanit["kontrol_kulesi_cagri"] = {
        "cagri_sayisi": ai.get("cagri_sayisi"),
        "replay_cagri": ai.get("replay_cagri"),
        "script_replay_miss": ai.get("script_replay_miss"),
    }
    if b.veri.get("model_modu") == "replay":
        b.kontrol(
            "Kontrol Kulesi: tüm model çağrıları REPLAY (sahte 'live' yok)",
            ai.get("cagri_sayisi") is not None and ai.get("cagri_sayisi") == ai.get("replay_cagri"),
            str(b.kanit["kontrol_kulesi_cagri"]),
            kritik=b.prova,
        )
    b.kontrol(
        "Kontrol Kulesi: script REPLAY-MISS yok",
        not ai.get("script_replay_miss"),
        str(ai.get("script_replay_miss")),
    )
    # ai_call okunamazsa REPLAY-MISS / sahte live doğrulanamaz: prova geçmez (sessiz atlama yok).
    b.kontrol(
        "ai_call kipleri okundu",
        kipler is not None,
        ""
        if kipler is not None
        else "postgres'e erişilemedi (docker exec): REPLAY-MISS / sahte 'live' denetlenemedi",
    )
    if kipler is not None:
        miss = [k for k in kipler if k["mod"] == "replay_miss"]
        b.kontrol("REPLAY-MISS yok", not miss, str(miss))
        izinli = b.veri.get("izinli_modlar", {"replay"})
        yabanci = [k for k in kipler if k["mod"] not in izinli and k["mod"] != "replay_miss"]
        b.kontrol("sahte 'live' yok (tüm çağrılar dürüst etiketli)", not yabanci, str(yabanci))
        b.kontrol("model çağrısı kaydı var", sum(k["sayi"] for k in kipler) > 0, str(kipler))
    a = b.api.get("sunucu", "/audit?verify=true&limit=1")
    v = a.get("verify") or {}
    b.kanit["denetim_zinciri"] = {
        "ok": v.get("ok"),
        "kayit": v.get("count"),
        "capa": (v.get("anchors") or {}).get("checked"),
    }
    b.kontrol(
        "denetim zinciri + çapalar doğrulandı",
        v.get("ok") is True and (v.get("anchors") or {}).get("ok") is True,
        str(b.kanit["denetim_zinciri"]),
    )
    if b.veri.get("model_modu") == "replay":
        etiketsiz = [
            d["id"]
            for d in bug_taslaklari(b)
            if d.get("mode") == "replay" and "REPLAY" not in (d.get("mode_label") or "")
        ]
        b.kontrol("bug taslakları REPLAY etiketli", not etiketsiz, str(etiketsiz))


def adimlar(kirma_yayinla: bool = False) -> list[Adim]:
    """Prova adımları. `kirma_yayinla`: isteğe bağlı C6 (kırma taslağı → yeni Bug + Test bağı)."""
    liste = [
        Adim(
            "P0",
            "Ön kontrol: roller, REPLAY sıkı kip, temiz başlangıç",
            "sunucu",
            "—",
            330,
            on_kontrol,
        ),
        Adim(
            "P1",
            "Güvenlik: security-check 10/10, bot main'e push reddi",
            "sunucu",
            "—",
            300,
            guvenlik,
        ),
        Adim("A1", "Jira'dan story çek (TPD-1, 6 AC)", "analist", "1", 30, jira_cek),
        Adim(
            "A2",
            "Ön inceleme + kod/veri tutarlılık denetimi",
            "analist",
            "2",
            60,
            on_inceleme,
            ai_adimi=True,
        ),
        Adim(
            "A3",
            "Bulgu kararları: F1/F3 dokümanı düzelt, F2/F4 kod hatalı",
            "analist",
            "2",
            30,
            bulgu_kararlari,
        ),
        Adim(
            "A4",
            "Düzeltmeleri Jira'ya yaz → 2. tur → son hal",
            "analist",
            "2",
            90,
            dokuman_duzelt,
            ai_adimi=True,
        ),
        Adim("A5", "PO teyidi (jira-sim, tp-po-approved)", "po", "3", 60, po_teyidi),
        Adim("A6", "Case üretimi (10 case)", "analist", "4", 60, case_uret, ai_adimi=True),
        Adim("A7", "QA kararları (10 onay)", "analist", "4", 60, qa_kararlari),
        Adim("A8", "Yayın: önizleme → Jira Test issue'ları", "analist", "4", 60, yayin),
        Adim(
            "B1",
            "Kod üretimi C1/C2/C3/C5 (Playwright MCP ajanı + şablon)",
            "muhendis",
            "5",
            AJAN_BUTCESI_S * 4 + 60,
            kod_uret,
            ai_adimi=True,
        ),
        Adim(
            "B2",
            "Kırarak doğrula: C2 yeşil→kırmızı→yeşil, C1/C5 zayıf",
            "muhendis",
            "6",
            300,
            kirarak_dogrula,
        ),
        Adim(
            "B3",
            "Merge: C2, C1, C5 (local-ci yeşil, zayıf test açık kabul)",
            "muhendis",
            "6–7",
            420,
            merge,
        ),
        Adim("B4", "Yerel CI: push (main) + deploy + nightly", "sunucu", "8–10", 420, ci_tetikleri),
        Adim("B5", "Kontrol Kulesi", "sunucu", "11", 30, kontrol_kulesi),
        Adim(
            "C1",
            "C3 triage: product_defect (kural) → bug taslağı, TPD-5 high",
            "testci",
            "12",
            120,
            c3_triage,
        ),
        Adim("C2", "Testçi: C3 → TPD-5 kaydına bağla", "testci", "13–14", 90, c3_bagla),
        Adim("C3", "Testçi: F2 taslağı → TPD-5 kaydına bağla", "testci", "13–14", 120, f2_bagla),
        Adim("C4", "Testçi: F4 → yeni Bug (aday yok)", "testci", "13–14", 120, f4_yeni),
        Adim(
            "C5",
            "Kırma koşusu taslağı (C2, TPD-5 medium, yeni kayıt önerisi)",
            "testci",
            "12",
            120,
            kirma_taslagi,
        ),
        Adim("D1", "make demo-break (add-to-cart → cart-add)", "sunucu", "12", 420, locator_kir),
        Adim(
            "D2",
            "Push CI kırmızı → triage test_maintenance/locator",
            "muhendis",
            "8, 12",
            420,
            locator_triage,
        ),
        Adim("D3", "Onarım PR'ı (yalnızca locator testId)", "muhendis", "12", 180, onarim_pr),
        Adim("D4", "Onarım merge (insan onayı)", "muhendis", "6–7", 240, onarim_merge),
        Adim("D5", "Push CI yeşil", "sunucu", "8", 300, ci_yesil),
        Adim("Z1", "Son denetim: REPLAY-MISS yok, zincir sağlam", "sunucu", "—", 60, son_denetim),
    ]
    if kirma_yayinla:
        i = next(n for n, a in enumerate(liste) if a.no == "C5") + 1
        liste.insert(
            i,
            Adim(
                "C6",
                "İsteğe bağlı: kırma taslağı → yeni Bug (Relates + Test)",
                "testci",
                "14",
                120,
                kirma_yeni_bug,
            ),
        )
    return liste


TOPLAM_BUTCE_S = 25 * 60  # §1: 20–25 dk canlı akış
