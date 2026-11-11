"""Faz 4 prompt paketlerinin değerlendirme setlerini (`rules/evaluation/<paket>.json`) üretir.

Girdiler golden testlerinin kullandığı kanonik kuruculardan (`defect_inputs`, yani
`tp_core.gateway.defects`) gelir; triage `Kural sinyalleri` satırları üretimdeki
`triage.service.kural_sinyalleri` ile kurulur. Setler bu modülden yeniden üretilir:

    cd core && uv run python -m tests.unit.gateway.build_eval_sets

`test_eval_sets` depodaki setin bu modülün çıktısıyla aynı olduğunu denetler (kurucu veya kaynak
değişince set bayatlar). Canlı koşu: `python -m tp_core.gateway.eval_set --bundle <paket>`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from tests.unit.gateway import defect_inputs as di
from tests.unit.gateway.demo_sources import RULES, load_golden
from tp_core.gateway import (
    defect_replay_key,
    failure_block,
    golden_name,
    requirement_block,
    triage_messages,
)
from tp_core.gateway.eval_set import EVAL_DIR
from tp_core.gateway.evaluation import prompt_versions
from tp_core.gateway.inputs import FREE_TEXT_KEY, numbered_acceptance_criteria
from tp_core.ports import ModelMessage

NO_MONEY = {"actual": ["TL"]}


def _msgs(messages: Sequence[ModelMessage]) -> list[dict[str, Any]]:
    return [m.model_dump() for m in messages]


def _rule_signals(failure: Mapping[str, Any], *, saglik: Any, attempts: list[str]) -> list[str]:
    from tp_core.features.triage.rules import Girdi
    from tp_core.features.triage.service import kural_sinyalleri

    girdi = Girdi(
        test_adi="eval",
        hata_turu=failure.get("type"),
        mesaj=failure.get("message"),
        beklenen=failure.get("expected"),
        gerceklesen=failure.get("received"),
        locator=failure.get("locator"),
        saglik=saglik,
        deneme_durumlari=attempts,
    )
    return kural_sinyalleri(girdi, [], None)


def _failure(**over: Any) -> dict[str, Any]:
    base = di.timeout_failure("00000000-0000-4000-8000-000000000000")
    base.update(
        {
            "matcher": None,
            "action": None,
            "locator": None,
            "expected": None,
            "received": None,
            "signals": [],
            "aria_snapshot": None,
        }
    )
    base.update(over)
    return base


def _triage(
    failure: dict[str, Any],
    *,
    title: str,
    saglik: Any,
    statuses: dict[str, int],
    consistent: bool,
    attempts: list[str],
) -> list[dict[str, Any]]:
    blk = failure_block(
        failure,
        test_title=title,
        test_file=failure["test_location"]["file"],
        story_key="TPD-1",
        saglik=saglik,
        statuses=statuses,
        consistent=consistent,
        rule_signals=_rule_signals(failure, saglik=saglik, attempts=attempts),
        include_aria=True,
    )
    return _msgs(triage_messages(blk))


def triage_cases() -> list[dict[str, Any]]:
    order = {"file": "tests/order.spec.ts", "line": 10, "column": 3}
    # Kural 1'in ağ hatası kalıbına (ECONNREFUSED, net::ERR_ …) uymayan ama servisin ayakta
    # olmadığını söyleyen mesaj: kalıba uyan hata modele hiç gitmez (kural → environment).
    unavailable = (
        "Error: apiRequestContext.post: 503 Service Unavailable — upstream demo-app-api "
        "bağlantıyı reddetti (connection refused)"
    )
    refused = _failure(
        type="other",
        first_line=unavailable,
        message=unavailable,
        status="failed",
        timeout_ms=None,
    )
    hidden_button = _failure(
        type="locator_timeout",
        first_line="Error: locator.click: Timeout 5000ms exceeded.",
        message="Error: locator.click: Timeout 5000ms exceeded.",
        action="click",
        locator="getByRole('button', { name: 'Siparişi onayla' })",
        timeout_ms=5000,
        signals=["eleman görünür olmadı"],
        status="failed",
        location=order,
        aria_snapshot='- heading "Sepet" [level=1]\n- status: "Sepet yükleniyor"',
    )
    # Kural 5'in fixture kalıbına uymayan veri önkoşulu: test, seed'de olmayan bayiyle girer.
    no_dealer = "Error: giriş başarısız: 'bayi9' adlı bayi kullanıcısı bulunamadı (401)"
    missing_dealer = _failure(
        type="other",
        first_line=no_dealer,
        message=no_dealer,
        status="failed",
        timeout_ms=None,
    )
    return [
        {
            "id": "zaman-asimi-kuralsiz",
            "description": "Golden: kuralların eşleşmediği test zaman aşımı → unknown (tahmin yok)",
            "messages": _msgs(di.timeout_messages("00000000-0000-4000-8000-000000000000")),
            "expect": {"class": "unknown", "sub_type": None},
        },
        {
            "id": "saglikli-agsiz-eleman-gorunmedi",
            "description": "Sağlık başarılı, ağ hatası yok: ortam denmez (triage.md sert kural)",
            "messages": _triage(
                hidden_button,
                title="Sipariş › sepet onayı",
                saglik=di.HEALTHY,
                statuses={"unexpected": 2},
                consistent=True,
                attempts=["failed", "failed"],
            ),
            "expect": {"class_not": ["environment", "product_defect"]},
        },
        {
            "id": "saglik-bilinmiyor-baglanti-reddedildi",
            "description": "Sağlık bilgisi yok + kural kalıbı dışı bağlantı reddi (503): ortam",
            "messages": _triage(
                refused,
                title="Katalog › ürünler listelenir",
                saglik=None,
                statuses={"unexpected": 2},
                consistent=True,
                attempts=["failed", "failed"],
            ),
            "expect": {"class": "environment", "sub_type": None},
        },
        {
            "id": "test-verisi-eksik-bayi",
            "description": "Seed'de olmayan bayi ile giriş: test verisi",
            "messages": _triage(
                missing_dealer,
                title="Giriş › bayi9 ile giriş yapılır",
                saglik=di.HEALTHY,
                statuses={"unexpected": 2},
                consistent=True,
                attempts=["failed", "failed"],
            ),
            "expect": {"class": "test_data", "sub_type": None},
        },
    ]


def bug_draft_cases() -> list[dict[str, Any]]:
    return [
        {
            "id": "c3-6-adet",
            "description": "Ana yol: C3 6 adet → bedava 1 (assertion: beklenen 0)",
            "messages": _msgs(di.bug_messages(di.c3_sources())),
            "expect": {
                "contains": {"summary": ["6 adet"], "actual": ["1"], "steps": ["bayi1", "6"]},
                "not_contains": NO_MONEY,
                "story_key": "TPD-1",
            },
        },
        {
            "id": "kirma-7-adet",
            "description": "BREAK_CAMPAIGN: 7 adet → bedava 0; ortam kasıtlı kırılmayı söyler",
            "messages": _msgs(di.bug_messages(di.break_sources(0))),
            "expect": {
                "contains": {"summary": ["7 adet"], "environment": ["BREAK_CAMPAIGN"]},
                "not_contains": NO_MONEY,
                "story_key": "TPD-1",
            },
        },
        {
            "id": "f2-kampanya-bulgusu",
            "description": "Demo-A F2: kod 6 adette 1 bedava (campaign.py:23)",
            "messages": _msgs(di.bug_messages(di.finding_sources("TPD-1", "F2"))),
            "expect": {"contains": {"steps": ["Portakal Gazozu"]}, "story_key": "TPD-1"},
        },
        {
            "id": "f4-kredi-limiti-bulgusu",
            "description": "Demo-A F4: kredi limiti kontrolü yok; adımlar bayi2 ile limiti aşar",
            "messages": _msgs(di.bug_messages(di.finding_sources("TPD-1", "F4"))),
            "expect": {
                "contains": {"steps": ["bayi2"], "expected": ["Kredi limiti aşıldı"]},
                "story_key": "TPD-1",
            },
        },
    ]


def _dup(
    case_id: str,
    description: str,
    sources: Callable[[], list[str]],
    keys: list[str],
    expect: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": case_id,
        "description": description,
        "messages": _msgs(di.dup_messages(sources(), keys)),
        "expect": {"candidate_keys": [di.candidate_key(k) for k in keys], **expect},
    }


def dup_rank_cases() -> list[dict[str, Any]]:
    link5 = {"top": "TPD-5", "recommendation": "link", "link_key": "TPD-5"}
    return [
        _dup("c3-seed", "C3 → TPD-5 aynı belirti", di.c3_sources, ["TPD-5", "TPD-6"], link5),
        _dup(
            "c3-f4-yayimlandi",
            "F4 yeni Bug olarak açıldıktan sonra C3: TPD-5 yine ilk",
            di.c3_sources,
            ["TPD-5", "@kredi-limiti"],
            link5,
        ),
        _dup(
            "f2-seed",
            "F2 bulgusu → TPD-5",
            lambda: di.finding_sources("TPD-1", "F2"),
            ["TPD-5", "TPD-6"],
            link5,
        ),
        _dup(
            "kirma-seed",
            "Kırma (7 adet → 0): TPD-5 ters belirti, yeni kayıt",
            di.break_sources,
            ["TPD-5", "TPD-6"],
            {"top": "TPD-5", "recommendation": "new", "link_key": None},
        ),
        _dup(
            "kirma-onceki-kirma-bug",
            "Önceki kırma koşusunun Bug'ı aramada: aynı belirti",
            di.break_sources,
            ["TPD-5", "@kirma"],
            {
                "top": di.candidate_key("@kirma"),
                "recommendation": "link",
                "link_key": di.candidate_key("@kirma"),
            },
        ),
        _dup(
            "f4-seed",
            "F4 kredi limiti: seed Bug'larının hiçbiri değil",
            lambda: di.finding_sources("TPD-1", "F4"),
            ["TPD-5", "TPD-6"],
            {"recommendation": "new", "link_key": None},
        ),
    ]


# ------------------------------------------------------------------ Demo-A / Demo-B prompt'ları

# Serbest metin gereksiniminin set içindeki sabit kimliği (üretimde gereksinim UUID'si; golden
# `input_match.sources` = `serbest:*`).
FREE_TEXT_ID = "00000000-0000-4000-8000-0000000000e1"
FREE_TEXT = {
    "summary": "Sepetten ürün çıkarma",
    "description": (
        "Bayi sepetteki bir ürün satırını kaldırabilmeli; toplamlar ve kampanya indirimi yeniden "
        "hesaplanmalıdır."
    ),
    "acs": [
        'Satırdaki "Kaldır" butonuna basıldığında ürün sepetten çıkar ve sepet sayacı azalır.',
        "Kaldırma sonrası kampanya indirimi her 7 adette 1 bedava kuralıyla yeniden hesaplanır.",
        "Sepet tutarı 500,00 TL altına düşerse minimum tutar uyarısı gösterilir.",
    ],
}
SYMBOLS_FIXTURE = Path(__file__).resolve().parents[1] / "features" / "codegen" / "symbols.json"
SYMBOLS_JAVA_FIXTURE = SYMBOLS_FIXTURE.with_name("symbols-java.json")


def _stories() -> dict[str, dict[str, Any]]:
    """Jira tohumu (`jira_seed.DEMO_STORIES`, DEMO-VERISI ile aynı) + serbest metin örneği."""
    from tp_core.integrations.jira_seed import DEMO_STORIES

    out = {
        f"TPD-{s.number}": {
            "summary": s.summary,
            "description": s.paragraph,
            "acs": list(s.acceptance_criteria),
        }
        for s in DEMO_STORIES
    }
    out["SERBEST"] = {**FREE_TEXT, "acs": numbered_acceptance_criteria(FREE_TEXT["acs"])}
    return out


def _block(key: str, summary: str, description: str, acs: list[str]) -> str:
    if key == "SERBEST":
        return requirement_block(
            summary=summary,
            description=description,
            acceptance_criteria=acs,
            requirement_id=FREE_TEXT_ID,
        )
    return requirement_block(
        summary=summary, description=description, acceptance_criteria=acs, jira_key=key
    )


def _key(key: str, **kw: Any) -> dict[str, str]:
    if key == "SERBEST":
        return {"name": golden_name(FREE_TEXT_KEY, **kw), "jira_key": FREE_TEXT_ID}
    return {"name": golden_name(key, **kw), "jira_key": key}


def _refs(acs: list[str]) -> list[str]:
    return [a.split(":", 1)[0].strip() for a in acs]


def requirement_review_cases() -> list[dict[str, Any]]:
    """Adım 2 ön inceleme: demo'nun 5 gereksinimi, Jira'daki ilk (düzeltilmemiş) halleriyle."""
    stories = _stories()
    expects: dict[str, dict[str, Any]] = {
        # AC3 ↔ AC6 çelişkisi ve 6/7 belirsizliği PO'ya sorulmalı.
        "TPD-1": {"verdict": "needs_po", "ac_refs_any": ["AC3", "AC6"]},
        # Kabul kriteri yok: PO teyidi (missing_ac); case üretimine geçilmez.
        "TPD-2": {"verdict": "needs_po", "question_types": ["missing_ac"]},
        # Açıklamadaki talimat veri olarak kalır; uydurma AC'ye soru yok.
        "TPD-3": {},
        # İki net AC: hazır.
        "TPD-4": {"verdict": "ready"},
        # "7 adette 1" ve 500 TL demo verisiyle çelişir: PO'ya sorulmalı.
        "SERBEST": {"verdict": "needs_po"},
    }
    out = []
    for key, exp in expects.items():
        st = stories[key]
        out.append(
            {
                "id": key.lower(),
                "description": f"{key}: {st['summary']}",
                "replay_key": _key(key),
                "messages": [
                    {
                        "role": "user",
                        "content": _block(key, st["summary"], st["description"], st["acs"]),
                    }
                ],
                "expect": {"ac_refs_within": _refs(st["acs"]), **exp},
            }
        )
    return out


def _golden_acs(purpose: str, name: str) -> list[str]:
    return list(load_golden(purpose, name)["input_match"]["acceptance_criteria"])


def _test_data_block() -> str:
    """Üretimin test verisi bloğu (`cases.testdata`), demo-app seed'inden (bellek içi SQLite)."""
    from tests.unit.gateway.demo_sources import demo_query
    from tp_core.features.cases import testdata
    from tp_core.gateway import wrap_untrusted

    text = testdata.build_text(lambda sql: [tuple(r) for r in demo_query(sql)])
    return wrap_untrusted(text, source=testdata.KAYNAK, kind="data")


# Uydurma belirteçleri (011 §4.2 "beklenen sonuç kaynaktan gelir"): hiçbir demo story'sinde
# yanıt kodu, zaman aşımı, hız sınırı, yeniden deneme ya da idempotency kuralı yoktur. `ready`
# bir case bunlardan birini anıyorsa beklenen sonuç uydurulmuştur.
FABRICATION_COMMON = [
    "HTTP 2",
    "HTTP 4",
    "HTTP 5",
    "status code",
    "durum kodu",
    "401",
    "403",
    "404",
    "429",
    "timeout",
    "zaman aşımı",
    "rate limit",
    "hız sınırı",
    "retry",
    "yeniden dene",
    "idempot",
    "milisaniye",
    "saniye içinde",
]
# Sepet / sipariş story'leri: kaynakta stok, vergi, kargo, bildirim kuralı yok.
FABRICATION_ORDER = ["stok", "KDV", "kargo", "e-posta", "SMS"]
FABRICATION = {
    "TPD-1": [*FABRICATION_COMMON, *FABRICATION_ORDER],
    # Arama: en az karakter, öneri/otomatik tamamlama, sayfalama kuralı yok.
    "TPD-3": [
        *FABRICATION_COMMON,
        "en az 2 karakter",
        "en az 3 karakter",
        "karakter sınırı",
        "otomatik tamamla",
        "öneri listesi",
        "sayfalama",
    ],
    # Giriş: hesap kilidi, deneme hakkı, captcha, parola sıfırlama, zorunlu alan mesajı yok.
    "TPD-4": [
        *FABRICATION_COMMON,
        "kilitlen",
        "bloke",
        "captcha",
        "deneme hakkı",
        "3 hatalı",
        "5 hatalı",
        "şifremi unuttum",
        "parolamı unuttum",
        "zorunlu alan",
        "boş bırakılamaz",
        "e-posta",
        "SMS",
    ],
    # Sepetten çıkarma: onay penceresi, geri alma kuralı yok.
    "SERBEST": [
        *FABRICATION_COMMON,
        *FABRICATION_ORDER,
        "emin misiniz",
        "onay penceresi",
        "geri al",
    ],
}
# Kaynağın sessiz olduğu bilinen noktalar: bu konudaki case `ready` yazılamaz (varsayıma bağlı ya
# da engelli olur, ya da hiç yazılmaz). Golden'lar: TPD-3 C5 `blocked` (Q1), TPD-4 `out_of_scope`.
SILENT = {
    "TPD-3": [
        {
            "topic": "aramada büyük/küçük harf duyarlılığı",
            "keywords": ["küçük harf", "büyük harf", "büyük/küçük", "harf duyarl", "harfe duyarl"],
        }
    ],
    "TPD-4": [
        {
            "topic": "kayıtlı olmayan kullanıcı adıyla giriş",
            "keywords": [
                "kayıtlı olmayan",
                "kayıtsız kullanıcı",
                "bilinmeyen kullanıcı",
                "olmayan kullanıcı",
                "tanımsız kullanıcı",
                "geçersiz kullanıcı adı",
                "hatalı kullanıcı adı",
                "yanlış kullanıcı adı",
            ],
        }
    ],
}
MAX_CASES = 10  # case-generation.md: "at most 10 cases per story"
TEST_LEVEL = "SYSTEM"


def _generation_messages(req: Any, data_block: str) -> list[ModelMessage]:
    """Üretimin `generation_messages` kurucusu, üretim seçenekleriyle (011 K5): girdi
    `Test seviyesi: SYSTEM` satırını taşır (golden'ların `test_level` alanı bununla tutarlıdır)."""
    from tp_core.features.cases.service import generation_messages

    return list(
        generation_messages(
            req, [], test_verisi=data_block, secenekler={"test_seviyesi": TEST_LEVEL}
        )
    )


def case_generation_cases() -> list[dict[str, Any]]:
    """Adım 4 (§12): 5 story × 3 koşu. PO onaylı (son hal) belgeler golden girdi beyanlarından;
    girdi üretimin `generation_messages` kurucusuyla (story bloğu + test verisi + test seviyesi).

    Beklentiler (şema v3, `eval_agents.coverage_problems`): AC kapsamı, her AC için hazır case,
    case sayısı sınırları, belgeden gelen metinler, uydurma belirteçleri ve kaynağın sessiz olduğu
    konular; 011 §4.2 deterministik kuralları her çıktıya ayrıca uygulanır."""
    from types import SimpleNamespace

    stories = _stories()
    data_block = _test_data_block()
    min_tl = "Minimum sipariş tutarı 750,00 TL"
    # 500,00 TL bayi2'nin kredi limitidir (geçerli); eski (düzeltilmemiş) minimum tutar olmamalı.
    old_min = "Minimum sipariş tutarı 500,00 TL"
    plan = [
        (
            "tpd-1-son-hal",
            "TPD-1",
            "TPD-1",
            {"contains": [min_tl, "Kredi limiti aşıldı"], "not_contains": [old_min]},
        ),
        (
            "tpd-1-f2-kod-hatasi",
            "TPD-1",
            "f2-kod-hatasi/TPD-1",
            {"contains": [min_tl], "not_contains": [old_min]},
        ),
        ("tpd-3-arama", "TPD-3", "TPD-3", {"contains": ["Ürün bulunamadı"]}),
        ("tpd-4-giris", "TPD-4", "TPD-4", {"contains": ["Kullanıcı adı veya parola hatalı"]}),
        (
            "serbest-son-hal",
            "SERBEST",
            "SERBEST",
            {"contains": ["750,00 TL"], "not_contains": [old_min]},
        ),
    ]
    out = []
    for case_id, key, golden, exp in plan:
        st = stories[key]
        acs = _golden_acs("case_generation", golden)
        req = SimpleNamespace(
            id=FREE_TEXT_ID,
            jira_key=None if key == "SERBEST" else key,
            baslik=st["summary"],
            aciklama=st["description"],
            kabul_kriterleri=acs,
            po_cevaplari=[],
        )
        expect: dict[str, Any] = {
            "ac_coverage": _refs(acs),
            "ready_ac_coverage": _refs(acs),
            "min_cases": len(acs),
            "max_cases": MAX_CASES,
            **exp,
            "not_contains_any": FABRICATION[key],
        }
        if key in SILENT:
            expect["must_not_be_ready_about"] = SILENT[key]
        out.append(
            {
                "id": case_id,
                "description": f"{key} ({golden}): son hal belgeden case üretimi",
                "replay_key": _key(key),
                "messages": _msgs(_generation_messages(req, data_block)),
                "expect": expect,
            }
        )
    return out


def consistency_check_cases() -> list[dict[str, Any]]:
    """Adım 2 tutarlılık (ajan): kod + veri araçları; kanıt yeniden doğrulanır (§8.2b adım 4)."""
    stories = _stories()
    plan = [
        # Dört gömülü tutarsızlık: AC2 (kod), AC3 (veri + AC6 çelişkisi), AC4 (kodda yok).
        ("tpd-1-tur-1", "TPD-1", {"doc_refs_include": ["AC2", "AC3", "AC4"], "min_blocking": 2}),
        ("serbest-tur-1", "SERBEST", {"doc_refs_include": ["AC2", "AC3"], "min_blocking": 1}),
        # Giriş story'si kodla tutarlı: engelleyici bulgu yok.
        ("tpd-4-tutarli", "TPD-4", {"max_blocking": 0}),
    ]
    out = []
    for case_id, key, exp in plan:
        st = stories[key]
        out.append(
            {
                "id": case_id,
                "description": f"{key}: 1. kontrol turu",
                "replay_key": _key(key, check_round=1),
                "messages": [
                    {
                        "role": "user",
                        "content": _block(key, st["summary"], st["description"], st["acs"]),
                    }
                ],
                "expect": {"acs": st["acs"], **exp},
            }
        )
    return out


def verify_and_map_cases() -> list[dict[str, Any]]:
    """Kod üretimi doğrulama ajanı (Playwright MCP): üretimin `mapping_messages` kurucusu, gerçek
    page object sembol tablosu (toolchain çıkarımı, codegen fikstürü)."""
    from tp_core.features.codegen.checks import SymbolTable
    from tp_core.features.codegen.service import case_ref, mapping_messages
    from tp_core.gateway.inputs import VERIFY_AGENT_DEALER, VERIFY_BASE_URL

    symbols = json.loads(SYMBOLS_FIXTURE.read_text(encoding="utf-8"))
    table = SymbolTable(symbols)
    methods = sorted(
        f"{po['class']}.{m['name']}" for po in symbols["page_objects"] for m in po["methods"]
    )
    out = []
    for key, n, title in (
        ("TPD-1", 3, "6 adette 1 bedava (ana senaryo F2 case'i)"),
        ("TPD-4", 1, "geçerli kullanıcıyla giriş"),
        ("TPD-4", 2, "hatalı parola"),
    ):
        case = load_golden("case_generation", key)["output"]["cases"][n - 1]
        golden = load_golden("verify_and_map", golden_name(key, case_no=n))["output"]
        out.append(
            {
                "id": f"{key.lower()}-c{n}",
                "description": f"{key}-C{n}: {title}",
                "replay_key": _key(key, case_no=n),
                "messages": _msgs(
                    mapping_messages(
                        case,
                        case_ref(key, n),
                        table,
                        agent_dealer=VERIFY_AGENT_DEALER,
                        demo_web_url=VERIFY_BASE_URL,
                    )
                ),
                "expect": {
                    "steps": [s["id"] for s in case["steps"]],
                    "methods": methods,
                    # Golden'daki case'e özgü assertion'lar (en azından son beklenen değer).
                    "expects_include": [f"{e['po']}.{e['method']}" for e in golden["expects"]],
                    "no_missing_methods": True,
                    "all_verified": True,
                },
            }
        )
    return out


def verify_and_map_app_cases() -> list[dict[str, Any]]:
    """Mobil/masaüstü doğrulama ajanı (app-mcp; 009 §2.6): üretimin `app_mapping_messages`
    kurucusu, gerçek Java ekran nesnesi tablosu (`java-araclar symbols`, codegen fikstürü)."""
    from tp_core.features.codegen.checks import SymbolTable
    from tp_core.features.codegen.service import app_mapping_messages, case_ref
    from tp_core.gateway.inputs import VERIFY_AGENT_DEALER

    symbols = json.loads(SYMBOLS_JAVA_FIXTURE.read_text(encoding="utf-8"))
    table = SymbolTable(symbols)
    methods = sorted(
        f"{po['class']}.{m['name']}" for po in symbols["page_objects"] for m in po["methods"]
    )
    out = []
    for key, n, platform, title in (("TPD-1", 2, "android", "7 adette 1 bedava (Android)"),):
        case = load_golden("case_generation", key)["output"]["cases"][n - 1]
        ad = f"{golden_name(key, case_no=n)}-{platform}"
        golden = load_golden("verify_and_map_app", ad)["output"]
        out.append(
            {
                "id": f"{key.lower()}-c{n}-{platform}",
                "description": f"{key}-C{n} ({platform}): {title}",
                "replay_key": {"name": ad, "jira_key": key},
                "messages": _msgs(
                    app_mapping_messages(
                        case,
                        case_ref(key, n),
                        table,
                        platform=platform,
                        agent_dealer=VERIFY_AGENT_DEALER,
                    )
                ),
                "expect": {
                    "steps": [s["id"] for s in case["steps"]],
                    "methods": methods,
                    "expects_include": [f"{e['po']}.{e['method']}" for e in golden["expects"]],
                    "no_missing_methods": True,
                    "all_verified": True,
                },
            }
        )
    return out


SETS: dict[str, tuple[str, Callable[[], list[dict[str, Any]]]]] = {
    "triage": ("triage", triage_cases),
    "bug-draft": ("bug_draft", bug_draft_cases),
    "dup-rank": ("dup_rank", dup_rank_cases),
    "requirement-review": ("requirement_review", requirement_review_cases),
    "case-generation": ("case_generation", case_generation_cases),
    "consistency-check": ("consistency_check", consistency_check_cases),
    "verify-and-map": ("verify_and_map", verify_and_map_cases),
    "verify-and-map-app": ("verify_and_map_app", verify_and_map_app_cases),
}
# Set düzeyi ek alanlar: §12 koşu sayısı, ajan araç ortamı (`tp_core.gateway.eval_agents`).
EXTRA: dict[str, dict[str, Any]] = {
    "case-generation": {"runs": 3},
    "consistency-check": {"agent": {"tool_env": "consistency", "max_turns": 15}},
    "verify-and-map": {"agent": {"tool_env": "browser", "max_turns": 20}},
    "verify-and-map-app": {"agent": {"tool_env": "app:android", "max_turns": 20}},
}
DEFECT_SETS = ("triage", "bug-draft", "dup-rank")


def build_sets() -> dict[str, dict[str, Any]]:
    versions = prompt_versions(RULES)
    out = {}
    for bundle, (purpose, build) in SETS.items():
        data: dict[str, Any] = {
            "bundle": bundle,
            "purpose": purpose,
            "version": versions[bundle],
        }
        if bundle in DEFECT_SETS:
            # Geçidin golden kökü: REPLAY duman koşusu golden'ları kullanır, `record` kipi
            # demo girdileriyle aynı anahtarı yazar. Diğer setlerde vaka düzeyindedir.
            data["replay_key"] = defect_replay_key("TPD-1")
        data.update(EXTRA.get(bundle, {}))
        data["note"] = (
            "Üretildi: core/tests/unit/gateway/build_eval_sets.py (elle düzenlemeyin). "
            "Canlı koşu: make eval-live A='--bundle " + bundle + "'"
        )
        data["cases"] = build()
        out[bundle] = data
    return out


def dump(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def write_sets(rules_dir: Path = RULES) -> list[Path]:
    out = []
    for bundle, data in build_sets().items():
        path = rules_dir / EVAL_DIR / f"{bundle}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump(data), encoding="utf-8")
        out.append(path)
    return out


if __name__ == "__main__":  # pragma: no cover
    for p in write_sets():
        print(p)
