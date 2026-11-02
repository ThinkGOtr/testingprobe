"""Taslak içeriği: şema, Faz 2 şablonunun taşınması, deterministik düzeltmeler, Jira gövdesi."""

from __future__ import annotations

from tp_core.features.bugs import content
from tp_core.features.bugs.context import BugContext, literal
from tp_core.integrations import jira_adf

ICERIK = {
    "summary": "Sepet: 6 adette bedava ürün veriliyor",
    "steps": ["1. Giriş yap", "2. 6 adet ekle"],
    "expected": "bedava adet 0",
    "actual": "bedava adet 1",
    "environment": "Yerel demo ortamı",
    "evidence": [{"kind": "trace", "ref": "/api/artifacts/runs/r/trace.zip"}],
    "story_key": "TPD-1",
    "test_case_key": "TPD-12",
    "severity_suggestion": "critical",
    "labels": ["AI-generated"],
}


def _ctx(**kw: object) -> BugContext:
    ctx = BugContext(
        kaynak="failure",
        story_key="TPD-1",
        test_case_key="TPD-12",
        beklenen='"0"',
        gerceklesen='"1"',
        kanitlar=[{"kind": "trace", "ref": "/api/artifacts/runs/r/trace.zip"}],
    )
    for k, v in kw.items():
        setattr(ctx, k, v)
    return ctx


def test_sema() -> None:
    assert content.validation_errors(ICERIK) == []
    assert content.validation_errors({**ICERIK, "labels": []})
    assert content.validation_errors({**ICERIK, "story_key": "tpd 1"})
    assert content.validation_errors({**ICERIK, "fazla": 1})


def test_literal() -> None:
    assert literal('"0"') == "0" and literal("'x'") == "x" and literal(" 25,00 TL ") == "25,00 TL"
    assert literal(None) is None and literal('""') is None


def test_duzeltmeler() -> None:
    ctx = _ctx()
    sablon = content.template_draft(ctx)
    ai = {
        **ICERIK,
        "actual": "yanlış hesap",
        "story_key": "TPD-9",
        "evidence": [{"kind": "trace", "ref": "http://uydurma"}],
        "labels": ["x"],
    }
    out, duz = content.apply_guards(ai, ctx, sablon)
    alanlar = {d["alan"] for d in duz}
    assert {"actual", "story_key", "evidence", "labels"} <= alanlar
    assert out["actual"] == sablon["actual"] and "1" in out["actual"]
    assert out["story_key"] == "TPD-1" and out["evidence"] == ctx.kanitlar
    assert "AI-generated" in out["labels"]
    assert content.validation_errors(out) == []


def test_bozuk_model_ciktisi_sablona_duser() -> None:
    ctx = _ctx()
    sablon = content.template_draft(ctx)
    out, duz = content.apply_guards({"summary": 5, "steps": "x"}, ctx, sablon)
    assert out == sablon and duz[0]["alan"] == "*"


def test_faz2_taslagi_semaya_tasinir() -> None:
    eski = {
        "summary": "TPD-1 AC4: kredi limiti",
        "uretim": "sablon",
        "steps": ["Kodu açın"],
        "expected": "uyarı",
        "actual": "yok",
        "environment": "denetim",
        "evidence": [{"tur": "code", "url": None, "etiket": "demo-app · pricing.py:97"}],
        "story_key": "TPD-1",
        "test_case_key": None,
        "severity_suggestion": "major",
        "labels": ["AI-generated"],
        "kaynak": "consistency_finding",
        "finding_id": "x",
    }
    ctx = BugContext(kaynak="finding", story_key="TPD-1", mevcut_icerik=eski)
    out = content.template_draft(ctx)
    assert content.validation_errors(out) == []
    assert out["steps"] == ["1. Kodu açın"]
    assert out["evidence"] == [{"kind": "code", "ref": "demo-app · pricing.py:97"}]
    assert "uretim" not in out and "finding_id" not in out


def test_jira_govdesi_ve_yorum() -> None:
    ortak = {
        "draft_label": "tp-abc",
        "onaylayan": "testci",
        "mod_etiketi": "REPLAY (hazırlanmış örnek çıktı; canlı model değil)",
        "icerik_hash": "h123",
        "zincir_hash": "z456",
    }
    govde = content.description_adf(ICERIK, **ortak)
    metin = jira_adf.adf_to_text(govde)
    for parca in ("Beklenen: bedava adet 0", "Gerçekleşen: bedava adet 1", "Kanıt", "REPLAY",
                  "testci", "onaylanan içerik hash: h123", "denetim zinciri son hash: z456",
                  "Story: TPD-1", "Test: TPD-12", "Kimlik: tp-abc", "Önem önerisi: critical",
                  "Ortam: Yerel demo ortamı"):  # fmt: skip
        assert parca in metin, parca
    # Görev şablonu: köken cümlesi, yedi bölüm şablon sırasıyla, en sonda kimlik/hash satırı.
    bloklar = govde["content"]
    basliklar = [jira_adf.inline_text(b) for b in bloklar if b["type"] == "heading"]
    assert basliklar == [baslik for _, baslik, _ in jira_adf.TEMPLATE_SECTIONS]
    assert jira_adf.inline_text(bloklar[0]).startswith("Bu kayıt Testing Probe")
    assert jira_adf.inline_text(bloklar[-1]) == (
        "Kimlik: tp-abc · onaylanan içerik hash: h123 · denetim zinciri son hash: z456"
    )

    def bolum(baslik: str) -> str:
        i = basliklar.index(baslik)
        bas = metin.index(baslik) + len(baslik)
        son = metin.index(basliklar[i + 1]) if i + 1 < len(basliklar) else len(metin)
        return metin[bas:son]

    akis = next(b for b in bloklar if b["type"] == "orderedList")
    assert [jira_adf.inline_text(li["content"][0]) for li in akis["content"]] == [
        "Giriş yap",
        "6 adet ekle",
    ]  # adımlar sıralı liste; içerikteki "1." önekleri tekrarlanmaz
    assert "Sepet: 6 adette bedava ürün veriliyor" in bolum("🎯 Objective (Amaç)")
    assert "Beklenen davranış sağlanır: bedava adet 0" in bolum(
        "🔑 Acceptance Criteria (Kabul Kriterleri)"
    )
    qa = bolum("🧪 QA Checklist")
    assert "TPD-12" in qa and "TPD-1 kabul kriterleri" in qa
    assert "Not applicable" not in metin
    # Bot imi açıklamanın ilk satırına `with_bot_header` ile eklenir (köken cümlesi ikinci).
    imli = jira_adf.with_bot_header(govde)
    assert jira_adf.has_bot_header(imli) and imli["content"][1] == bloklar[0]
    # Bağ yoksa Bağımlılıklar bölümü "Not applicable"; QA listesi test/story maddesi içermez.
    yalin = {**ICERIK, "story_key": None, "test_case_key": None, "evidence": []}
    yalin_metin = jira_adf.adf_to_text(content.description_adf(yalin, **ortak))
    assert "Bağımlılıklar ve Entegrasyon)\n\nNot applicable" in yalin_metin
    assert "Kanıt" not in yalin_metin and "yeşil geçer" not in yalin_metin
    # "Gerçekleşen değer: 1" gibi etiketli içerik etiketi tekrar etmez.
    etiketli = {**ICERIK, "actual": "Gerçekleşen değer: 1"}
    assert "Gerçekleşen: Gerçekleşen" not in jira_adf.adf_to_text(
        content.description_adf(etiketli, **ortak)
    )
    yorum = jira_adf.adf_to_text(content.link_comment(ICERIK, **ortak))
    assert "tp-abc" in yorum and "yeni kayıt açılmadı" in yorum and "h123" in yorum
    assert "Testçi (testci) taslağı bu kayda bağladı" in yorum
    assert "Testçi testci" not in yorum
    assert content.SEVERITY_PRIORITY["critical"] == "Highest"


# ------------------------------------------------------- insan düzenlemesi korumaları


def test_insan_duzenlemesi_baglam_alanlarini_degistiremez() -> None:
    ctx = _ctx()
    # Serbest metin düzenlemesi ve kanıt çıkarmak serbest.
    content.check_human_edit({**ICERIK, "summary": "yeni özet", "evidence": []}, ICERIK, ctx)
    kotu = [
        ({"story_key": "OTHER-9"}, "story_key"),
        ({"test_case_key": "not a key; anything"}, "test_case_key"),
        ({"test_case_key": "TPD-99"}, "test_case_key"),
        (
            {"evidence": [{"kind": "log", "ref": "https://evil.example/x"}]},
            "evil.example",
        ),
    ]
    for degisiklik, beklenen in kotu:
        yeni = {**ICERIK, **degisiklik}
        # Şema yalnızca biçimi denetler (anahtar deseni); bağlam korumasını check_human_edit sağlar.
        if degisiklik.get("test_case_key") == "not a key; anything":
            assert any("test_case_key" in h for h in content.validation_errors(yeni))
        else:
            assert content.validation_errors(yeni) == []
        try:
            content.check_human_edit(yeni, ICERIK, ctx)
        except content.ContentError as exc:
            assert beklenen in str(exc)
        else:  # pragma: no cover
            raise AssertionError(f"kabul edilmemeliydi: {degisiklik}")


def test_insan_duzenlemesi_mevcut_taslak_degerlerini_korur() -> None:
    """Faz 2 taslağında bağlamda olmayan ama taslakta zaten olan kanıt/anahtar korunabilir."""
    eski = {**ICERIK, "evidence": [{"kind": "code", "ref": "demo-app · api/x.py"}]}
    ctx = _ctx(kaynak="finding", test_case_key=None, kanitlar=[])
    content.check_human_edit({**eski, "summary": "düzenlendi"}, eski, ctx)


# ------------------------------------------------------------ Jira kanıt bağlantıları


def test_jira_kanitlari_mutlak_ve_commite_sabit() -> None:
    kanit = content.public_evidence(
        [
            {"kind": "trace", "ref": "/api/artifacts/runs/r/trace.zip"},
            {"kind": "sauce_video", "ref": "https://saucelabs.example/v.mp4"},
            {"kind": "code", "ref": "api/src/demoapp_api/campaign.py:23"},
            {"kind": "data", "ref": "SELECT 1"},
        ],
        base_url="http://portal.test/",
        kod_sha="0123456789abcdef0123",
    )
    assert kanit == [
        (
            "trace",
            "http://portal.test/api/artifacts/runs/r/trace.zip",
            "http://portal.test/api/artifacts/runs/r/trace.zip",
        ),
        ("sauce_video", "https://saucelabs.example/v.mp4", "https://saucelabs.example/v.mp4"),
        ("code", "api/src/demoapp_api/campaign.py:23 (demo-app @ commit 0123456789ab)", None),
        ("data", "SELECT 1", None),
    ]
    forge = content.public_evidence(
        [{"kind": "code", "ref": "api/src/demoapp_api/campaign.py:23"}],
        base_url="http://portal.test",
        kod_sha="abc",
        kod_url=lambda p, line, sha: f"https://git.example/blob/{sha}/{p}#L{line}",
    )
    url = "https://git.example/blob/abc/api/src/demoapp_api/campaign.py#L23"
    assert forge == [("code", "api/src/demoapp_api/campaign.py:23", url)]

    ortak = {
        "draft_label": "tp-x",
        "onaylayan": "testci",
        "mod_etiketi": "REPLAY",
        "icerik_hash": "h",
        "zincir_hash": None,
        "kanit": kanit[:1] + forge,
    }
    adf = content.description_adf(ICERIK, **ortak)
    hrefler = [
        m["attrs"]["href"]
        for n in _dugumler(adf)
        for m in n.get("marks") or []
        if m.get("type") == "link"
    ]
    assert hrefler == ["http://portal.test/api/artifacts/runs/r/trace.zip", url]
    assert "trace: http://portal.test/api/artifacts/runs/r/trace.zip" in jira_adf.adf_to_text(adf)
    # "Mevcut kayda bağla" yorumu da ADF: kanıtlar tıklanabilir bağlantı (düz metin değil).
    yorum = content.link_comment(ICERIK, **ortak)
    assert yorum["type"] == "doc"
    yorum_hrefleri = [
        m["attrs"]["href"]
        for n in _dugumler(yorum)
        for m in n.get("marks") or []
        if m.get("type") == "link"
    ]
    assert yorum_hrefleri == ["http://portal.test/api/artifacts/runs/r/trace.zip", url]
    metin = jira_adf.adf_to_text(yorum)
    assert "trace: http://portal.test/api/artifacts/runs/r/trace.zip" in metin
    assert "code: api/src/demoapp_api/campaign.py:23" in metin
    assert "portalında oturum ister" in metin


def _dugumler(n: object) -> list[dict]:
    if not isinstance(n, dict):
        return []
    out = [n]
    for c in n.get("content") or []:
        out += _dugumler(c)
    return out


def test_kanit_verilmezse_ham_ref_yazilir() -> None:
    ortak = {
        "draft_label": "tp-x",
        "onaylayan": None,
        "mod_etiketi": "şablon",
        "icerik_hash": "h",
        "zincir_hash": None,
    }
    assert "trace: /api/artifacts/runs/r/trace.zip" in content.link_comment_text(ICERIK, **ortak)


# ------------------------------------------------------ literal değer: ayrı belirteç


def test_literal_ayri_belirtec_olarak_aranir() -> None:
    gecer = content.literal_gecer
    assert gecer("1", "bedava adet 1") and gecer("1", 'Received: "1"')
    assert gecer("1", "bedava adet 1.") and gecer("0", "bedava adet: 0, beklenen")
    assert gecer("1", "1'den fazla") and gecer("25,00 TL", "tutar 25,00 TL oldu")
    assert not gecer("1", "P-001 satırında bedava adet 2")  # ürün kodu
    assert not gecer("1", "TPD-1 AC2: bedava adet 5")  # Jira anahtarı
    assert not gecer("0", "P-001 satırında bedava adet 5")
    assert not gecer("1", "bedava adet 10") and not gecer("1", "tutar 1,5 TL")
    assert not gecer("1", "AC1 gereği") and not gecer("1", "1.5 adet")


def test_urun_kodu_ve_anahtar_rakamlari_korumayi_gecemez() -> None:
    """C3: beklenen 0, gerçekleşen 1. Model 'P-001 ... bedava adet 2' / 'TPD-1 ... 5' yazarsa
    rakamlar ürün kodunda/anahtarda geçse de şablon değerleri yazılır."""
    ctx = _ctx(case_beklenen="6 adet ürün eklenince bedava adet 0 olmalı")
    sablon = content.template_draft(ctx)
    ai = {
        **ICERIK,
        "actual": "P-001 satırında bedava adet 2 görünüyor",
        "expected": "TPD-1 AC2 gereği P-001 için bedava adet 5",
    }
    out, duz = content.apply_guards(ai, ctx, sablon)
    alanlar = {d["alan"] for d in duz}
    assert {"actual", "expected"} <= alanlar
    assert out["actual"] == sablon["actual"] and content.literal_gecer("1", out["actual"])
    assert out["expected"] == sablon["expected"] and content.literal_gecer("0", out["expected"])
    # Doğru değeri ayrı belirteç olarak taşıyan model metni korunur.
    dogru = {
        **ICERIK,
        "actual": "P-001 satırında bedava adet 1 görünüyor",
        "expected": "P-001 için bedava adet 0",
    }
    out, duz = content.apply_guards(dogru, ctx, sablon)
    assert not {"actual", "expected"} & {d["alan"] for d in duz}
    assert out["actual"] == dogru["actual"]


def test_sablon_beklenen_degeri_urun_kodunda_saklanmaz() -> None:
    ctx = _ctx(case_beklenen="P-001 için kampanya uygulanır")
    sablon = content.template_draft(ctx)
    assert "(beklenen değer: 0)" in sablon["expected"]
