"""Portal asistanı kural dosyaları (`rules/assistant/*`, AI-ASISTAN-PLANI §5.4, §5.5, §10.2, §17).

Modelsiz kuralların (constitution XI) sözleşmesi burada zorlanır:

- `rotalar.json` portalın rotalarıyla (App.tsx + lib/rotalar.ts) birebir.
- `hata-sozlugu.yaml`: bilinen `kod`'lar (api/errors.py, WorkflowError ailesi, CSRF) kapsanır.
- `urun-terimleri.yaml`: genel QA terimi yok; S9 ("Flaky test…") genel bilgi kalır.
- `oneriler.yaml`: §17.3'ün 26 kuralı + 011 `script-dogrulanmamis`; kapalı olgu/operatör/yer
  tutucu kümesi, serbest metin olgusu yer tutucu olamaz, sistem hattı olan ekranda Jira eylemi
  yok, tek eylem, rol hizalama (FastAPI `require_role` + `APPROVER_ROLES`), kapsam matrisi.
- `jira-taslaklari.yaml`: taslakta URL/wiki bağlantı/mention/HTML yok, yer tutucular geçerli.
- `evaluation/assistant.json` iskeleti ve asistan golden'ları.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.unit.gateway.demo_sources import REPO, RULES
from tp_core.features.assistant import sonislem
from tp_core.gateway import ALLOWED_AGENT_TOOLS, FORBIDDEN_TOOLS, load_schema
from tp_core.gateway.bundle import parse_prompt_file

ASISTAN = RULES / "assistant"
ROLLER = ("analyst", "po", "engineer", "tester", "presenter")
VARLIKLAR = (
    "requirement",
    "consistency_finding",
    "test_case",
    "script",
    "run",
    "failure",
    "bug_draft",
)
EYLEM_TURLERI = ("rota", "jira_taslak", "jira_yorum", "jira_kaydi", "bilgi")
TASLAK_TURLERI = ("Task", "Bug", "Story", "yorum")
# §5 araç listesi; `ALLOWED_AGENT_TOOLS["assistant"/"assistant_deep"]` (gateway/core.py) ile aynı.
ASISTAN_ARACLARI = frozenset(
    {
        "product_search",
        "product_read",
        "probe_get",
        "probe_list",
        "probe_jobs",
        "probe_audit",
        "probe_my_queue",
        "jira_issue",
        "ci_log",
        "search_code",
        "get_file_contents",
        "db_schema",
        "db_query",
    }
)
# §17.2 olgu tablosu + §17.3 olgu eki. Değişiklik `features/assistant/oneri.py` ile birlikte gelir.
OLGU_ADLARI = frozenset(
    {
        "durum",
        "po_bekleme_saat",
        "po_kanal",
        "ac_eksik",
        "acik_bulgu_sayisi",
        "inceleme_bekleyen_case",
        "onayli_case",
        "kirarak_dogrulama",
        "defect_adayi",
        "ci_sonuc",
        "basarisiz_adimlar",
        "hata_sinifi",
        "onarim_durumu",
        "flaky_tekrar",
        "bug_taslagi_var",
        "bug_taslagi_id",
        "bulgu_kaynakli",
        "jira_key",
        "butce_orani",
        "son_kosu_saat",
    }
)
OLGU_TURLERI = ("durum", "enum", "sayi", "oran", "bool", "anahtar", "kimlik", "metin_listesi")
# Serbest metin taşıyabilen olgu türleri hiçbir zaman yer tutucu olamaz.
SERBEST_METIN_TURLERI = ("metin_listesi", "kimlik", "durum")
OPERATORLER = ("_in", "_esit", "_gte", "_lte", "_var", "_yok")
KURAL_ALANLARI = {"id", "ekran", "varlik", "roller", "kosul", "oncelik", "baslik", "neden", "eylem"}
KURAL_ISTEGE_BAGLI = {"aciklama", "tekrar_saat"}
EYLEM_ALANLARI: dict[str, tuple[set[str], set[str]]] = {  # tur → (zorunlu, isteğe bağlı)
    "rota": ({"tur", "rota", "yetki"}, {"capa", "id_olgusu"}),
    "jira_taslak": ({"tur", "sablon"}, set()),
    "jira_yorum": ({"tur", "sablon"}, set()),
    "jira_kaydi": ({"tur"}, set()),
    "bilgi": ({"tur"}, set()),
}
# Testing Probe'un kendi onaylı hattı olan iş: bu ekran/varlıklarda Jira taslağı/yorumu yasak
# (§17.2; mükerrer Jira kaydı ve constitution I'i aşan paralel hat olmasın). Liste kodda sabittir
# (kural dosyası kendi korumasını gevşetemez) ve model önerilerinin son işlemiyle ortaktır.
SISTEM_HATTI_EKRANLARI = sonislem.SISTEM_HATTI_EKRANLARI
SISTEM_HATTI_VARLIKLARI = sonislem.SISTEM_HATTI_VARLIKLARI
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
YER_TUTUCU = re.compile(r"\{([a-z_]+)\}")
JIRA_ANAHTARI = re.compile(r"^[A-Z][A-Z0-9]+-[0-9]+$")
# Taslak ve öneri metinlerinde yasak: URL, wiki bağlantısı, mention, HTML, Markdown bağlantısı.
YASAK_METIN = re.compile(
    r"[a-z][a-z0-9+.-]*://|www\.|\[[^\]]*\|[^\]]*\]|\[~|(^|\s)@\w|<[a-zA-Z/!]|\]\(",
    re.IGNORECASE,
)


def _yaml(name: str) -> Any:
    return yaml.safe_load((ASISTAN / name).read_text(encoding="utf-8"))


def _rotalar() -> dict[str, dict[str, Any]]:
    data = json.loads((ASISTAN / "rotalar.json").read_text(encoding="utf-8"))
    return {r["kalip"]: r for r in data["rotalar"]}


def _metinler(*parcalar: Any) -> Iterator[str]:
    for p in parcalar:
        if isinstance(p, str):
            yield p
        elif isinstance(p, Mapping):
            yield from _metinler(*p.values())
        elif isinstance(p, list):
            yield from _metinler(*p)


# ------------------------------------------------------------------ rotalar.json


# Asistan bağlamı dışındaki portal ekranları: AI Probe rol seçici (specs/010-aiprobe-sso; oturum
# öncesi/geçiş ekranı, Kabuk ve asistan yok). `rotalar.json`'a girmez (asistan bağlantı vermez).
ASISTAN_DISI = frozenset({"/rol-sec"})


def _app_rotalari() -> set[str]:
    """App.tsx `<Route path=…>` / `<Route index …>` (Kabuk altı "/" + giriş)."""
    src = (REPO / "review-portal" / "src" / "App.tsx").read_text(encoding="utf-8")
    out = set()
    for m in re.finditer(r"<Route\s+(index\b|path=\"([^\"]*)\")", src):
        if m.group(1) == "index":
            out.add("/")
            continue
        path = m.group(2)
        if path == "*":
            continue
        out.add(path if path.startswith("/") else "/" + path)
    return out - ASISTAN_DISI


def _kalip_regex(kalip: str) -> str:
    """`/gereksinimler/:id` → lib/rotalar.ts'teki RegExp kaynağı (`^\\/gereksinimler\\/[^/]+$`)."""
    if kalip == "/":
        return r"^\/$"
    parcalar = [r"[^/]+" if p.startswith(":") else p for p in kalip.strip("/").split("/")]
    return "^" + "".join(r"\/" + p for p in parcalar) + "$"


def test_rotalar_json_app_tsx_ile_birebir() -> None:
    rotalar = _rotalar()
    assert len(rotalar) == len(json.loads((ASISTAN / "rotalar.json").read_text())["rotalar"])
    assert set(rotalar) == _app_rotalari()


def test_rotalar_json_lib_rotalar_ts_ile_birebir() -> None:
    src = (REPO / "review-portal" / "src" / "lib" / "rotalar.ts").read_text(encoding="utf-8")
    desenler = re.search(r"ROTA_DESENLERI[^=]*=\s*\[(.*?)\];", src, re.DOTALL)
    if desenler:  # react-router desenleri (`:id`), kalıplar bunlardan türetilir
        assert set(re.findall(r'"([^"]+)"', desenler.group(1))) - ASISTAN_DISI == set(_rotalar())
        return
    blok = re.search(r"ROTA_KALIPLARI[^=]*=\s*\[(.*?)\];", src, re.DOTALL)
    assert blok, "lib/rotalar.ts ROTA_DESENLERI/ROTA_KALIPLARI bulunamadı"
    ts = set(re.findall(r"/(\^.*?\$)/", blok.group(1)))
    assert {_kalip_regex(k) for k in _rotalar()} == ts


def test_rotalar_json_alanlari() -> None:
    for kalip, r in _rotalar().items():
        assert set(r) == {"kalip", "ekran", "varlik", "roller"}, kalip
        assert r["ekran"] and isinstance(r["ekran"], str)
        assert r["varlik"] is None or r["varlik"] in VARLIKLAR, kalip
        assert (":id" in kalip) == (r["varlik"] is not None), kalip
        assert r["roller"] is None or (r["roller"] and set(r["roller"]) <= set(ROLLER)), kalip


# ------------------------------------------------------------------ hata sözlüğü


def _normalize(metin: str) -> str:
    """Sözlük ve terim eşleşmesinin normalizasyonu: Türkçe küçük harf, tek boşluk."""
    return " ".join(metin.replace("I", "ı").replace("İ", "i").lower().split())


def _bilinen_kodlar() -> set[str]:
    from tp_core.api import csrf, errors
    from tp_core.api import main as _api_main  # noqa: F401  (özellik router'larını yükler)
    from tp_core.workflow import service

    # Kodlu WorkflowError alt sınıfları özellik modüllerinde tanımlıdır (ör. codegen
    # `DilCakismasi`); API modülü hepsini içe aktarır, dosya tek başına koşsa da görünür.

    def alt_siniflar(cls: type) -> Iterator[type]:
        for alt in cls.__subclasses__():
            yield alt
            yield from alt_siniflar(alt)

    kodlar = set(errors.GENEL_KODLAR.values()) | {errors.IC_HATA, csrf.RED_KODU, "butce_asildi"}
    kodlar |= {"istek_hatasi"}  # listede olmayan 4xx (errors.genel_kod)
    # Yalnız üründeki alt sınıflar: testlerin tanımladığı sahte WorkflowError alt sınıfları
    # (ör. test_hata_kodlari) __subclasses__() ile sızmasın.
    kodlar |= {
        c.kod
        for c in alt_siniflar(service.WorkflowError)
        if c.kod and c.__module__.startswith("tp_core.")
    }
    return kodlar


def _sozluk_bul(sozluk: dict[str, Any], kod: str | None, *metinler: str | None) -> str | None:
    """Belgelenen eşleşme sırası: önce metin parçası, sonra kod; ilk kayıt kazanır."""
    norm = [_normalize(m) for m in metinler if m]
    for k in sozluk["kayitlar"]:
        if any(_normalize(p) in m for p in k["metinler"] for m in norm):
            return k["id"]
    for k in sozluk["kayitlar"]:
        if kod and kod in k["kodlar"]:
            return k["id"]
    return None


def test_hata_sozlugu_bicimi() -> None:
    sozluk = _yaml("hata-sozlugu.yaml")
    assert sozluk["version"] >= 1
    alanlar = {"id", "kodlar", "metinler", "baslik", "anlam", "neden", "cozum", "rota"}
    rotalar = _rotalar()
    ids = [k["id"] for k in sozluk["kayitlar"]]
    assert len(ids) == len(set(ids))
    bilinen = _bilinen_kodlar()
    for k in sozluk["kayitlar"]:
        assert set(k) == alanlar, k["id"]
        assert KEBAB.match(k["id"]), k["id"]
        assert k["kodlar"] or k["metinler"], k["id"]
        assert set(k["kodlar"]) <= bilinen, (k["id"], set(k["kodlar"]) - bilinen)
        for parca in k["metinler"]:
            assert parca == _normalize(parca), (k["id"], parca)
        assert k["rota"] is None or k["rota"] in rotalar, k["id"]
        for metin in _metinler(k["baslik"], k["anlam"], k["neden"], k["cozum"]):
            assert metin.strip() and not YASAK_METIN.search(metin), (k["id"], metin)


def test_hata_sozlugu_bilinen_her_kodu_kapsar() -> None:
    kapsanan = {kod for k in _yaml("hata-sozlugu.yaml")["kayitlar"] for kod in k["kodlar"]}
    assert _bilinen_kodlar() <= kapsanan, sorted(_bilinen_kodlar() - kapsanan)


@pytest.mark.parametrize(
    ("kod", "detail", "beklenen"),
    [
        ("onay_hash_uyusmuyor", "İçerik değişti, yeniden inceleyin.", "onay-hash-uyusmuyor"),
        (
            "kapi_kapali",
            "İçerik siz görüntüledikten sonra değişmiş; yenileyin",
            "gorunduktan-sonra-degisti",
        ),
        (
            "kosul_saglanmadi",
            "requirement: kabul kriteri eksik (ac_missing) gereksinim case üretimine gönderilmez",
            "ac-eksik-uretim-engeli",
        ),
        (
            "kapi_kapali",
            "PO onay etiketi (tp-po-approved) Jira'da artık yok; PO onayı yenilenmeli",
            "po-onay-etiketi-yok",
        ),
        ("yetkisiz", "Oturumunuz geçersiz veya süresi dolmuş", "oturum-gecersiz"),
        ("kaynak_reddi", "Kaynak reddedildi", "kaynak-reddi"),
        (None, "İÇERİK SİZ GÖRÜNTÜLEDİKTEN SONRA DEĞİŞMİŞ", "gorunduktan-sonra-degisti"),
        ("bilinmeyen_kod", "hiç eşleşmeyen metin", None),
    ],
)
def test_hata_sozlugu_eslesme_sirasi(kod: str | None, detail: str, beklenen: str | None) -> None:
    assert _sozluk_bul(_yaml("hata-sozlugu.yaml"), kod, detail) == beklenen


# ------------------------------------------------------------------ ürün terimleri


def _urune_ozgu(soru: str, terimler: list[str]) -> bool:
    if re.search(r"[A-Z]+-\d+", soru):
        return True
    metin = _normalize(soru)
    return any(re.search(r"(?<!\w)" + re.escape(t), metin) for t in terimler)


def test_urun_terimleri_bicimi() -> None:
    data = _yaml("urun-terimleri.yaml")
    terimler = data["terimler"]
    assert data["version"] >= 1 and terimler
    assert len(terimler) == len(set(terimler))
    for t in terimler:
        assert t == _normalize(t) and t.strip() == t, t
        # Gereksiz terim yok: başka bir terim bunu zaten eşliyorsa listede durmasın.
        diger = [x for x in terimler if x != t]
        assert not _urune_ozgu(t, diger), f"'{t}' başka bir terimle zaten eşleşiyor"
    genel = {"test", "flaky", "bug", "ci", "jira", "locator", "playwright", "regresyon", "sunucu"}
    assert not genel & set(terimler)


@pytest.mark.parametrize(
    ("soru", "beklenen"),
    [
        ("Bu 'Kırarak doğrula' neden gri?", True),  # S1
        ("TPD-3 neden case üretimine geçmiyor?", True),  # S3
        ("Demo uygulamasında kampanya indirimi nasıl hesaplanıyor?", True),  # S5
        ("Onay bekleyen story'ler? PO onayını kim veriyor?", True),
        ("Bug taslağını kim yayımlar?", True),
        ("Flaky test nasıl ayıklanır?", False),  # S9: genel bilgi
        ("Playwright'ta bekleme nasıl yazılır?", False),
        ("Regresyon testi nedir?", False),
    ],
)
def test_urune_ozgu_soru_siniflamasi(soru: str, beklenen: bool) -> None:
    assert _urune_ozgu(soru, _yaml("urun-terimleri.yaml")["terimler"]) is beklenen


# ------------------------------------------------------------------ öneri kuralları


def _anahtar_coz(anahtar: str) -> tuple[str, str] | None:
    """`po_bekleme_saat_gte` → (`po_bekleme_saat`, `_gte`); `durum_in` → (`durum`, `_in`)."""
    for op in OPERATORLER:
        if anahtar.endswith(op) and len(anahtar) > len(op):
            return anahtar[: -len(op)], op
    return None


def _yer_tutucular(olgular: Mapping[str, Any], varlik: str | None) -> set[str]:
    """Kuralın varlığında hesaplanan ve yer tutucu olabilen adlar (olgu + türevleri)."""
    kapsam = varlik or "genel"
    out: set[str] = set()
    for ad, o in olgular.items():
        if kapsam in o["varliklar"] and o.get("yer_tutucu"):
            out.add(ad)
            out |= set(o.get("turevler") or {})
    return out


def _metin_hatalari(etiket: str, metin: Any, izinli: set[str]) -> list[str]:
    if not isinstance(metin, str) or not metin.strip():
        return [f"{etiket}: boş metin"]
    hatalar = []
    if YASAK_METIN.search(metin):
        hatalar.append(f"{etiket}: URL/bağlantı/mention/HTML içeriyor")
    for ad in YER_TUTUCU.findall(metin):
        if ad not in izinli:
            hatalar.append(f"{etiket}: geçersiz yer tutucu {{{ad}}}")
    if YER_TUTUCU.sub("", metin).count("{") or YER_TUTUCU.sub("", metin).count("}"):
        hatalar.append(f"{etiket}: biçimsiz süslü parantez")
    return hatalar


def kural_hatalari(
    doc: Mapping[str, Any],
    taslaklar: Mapping[str, Mapping[str, Any]],
    rotalar: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """`oneriler.yaml` sözleşme denetimi (boş liste = geçerli)."""
    from tp_core.workflow.states import MACHINES

    hatalar: list[str] = []
    if set(doc) != {"version", "olgular", "kurallar", "bos_ekranlar"}:
        hatalar.append(f"üst düzey alanlar: {sorted(doc)}")
    olgular: Mapping[str, Any] = doc.get("olgular") or {}
    bilinmeyen = set(olgular) - OLGU_ADLARI
    if bilinmeyen:
        hatalar.append(f"bilinmeyen olgu tanımı: {sorted(bilinmeyen)}")
    for ad, o in olgular.items():
        if o.get("tur") not in OLGU_TURLERI:
            hatalar.append(f"olgu {ad}: tür {o.get('tur')!r}")
        if not set(o.get("varliklar") or []) <= set(VARLIKLAR) | {"genel"}:
            hatalar.append(f"olgu {ad}: varlık {o.get('varliklar')}")
        if o.get("yer_tutucu") and o.get("tur") in SERBEST_METIN_TURLERI:
            hatalar.append(f"olgu {ad}: serbest metin/kimlik olgusu yer tutucu olamaz")
        if (o.get("tur") == "enum") != ("degerler" in o):
            hatalar.append(f"olgu {ad}: enum değerleri")
    ids: set[str] = set()
    for kural in doc.get("kurallar") or []:
        kid = str(kural.get("id"))
        etiket = f"kural {kid}"
        if not KEBAB.match(kid) or kid in ids:
            hatalar.append(f"{etiket}: id tekil kebab-case değil")
        ids.add(kid)
        alanlar = set(kural)
        if not alanlar >= KURAL_ALANLARI or alanlar - KURAL_ALANLARI - KURAL_ISTEGE_BAGLI:
            hatalar.append(f"{etiket}: alanlar {sorted(alanlar ^ KURAL_ALANLARI)}")
            continue
        ekran, varlik = kural["ekran"], kural["varlik"]
        if ekran not in rotalar:
            hatalar.append(f"{etiket}: ekran {ekran} rotalar.json'da yok")
        elif rotalar[ekran]["varlik"] != varlik:
            hatalar.append(f"{etiket}: varlık {varlik}, ekranınki {rotalar[ekran]['varlik']}")
        roller = kural["roller"]
        if not roller or not set(roller) <= set(ROLLER) or len(set(roller)) != len(roller):
            hatalar.append(f"{etiket}: roller {roller}")
        if not isinstance(kural["oncelik"], int) or not 0 <= kural["oncelik"] <= 100:
            hatalar.append(f"{etiket}: öncelik 0–100")
        if kural.get("tekrar_saat") is not None and (
            not isinstance(kural["tekrar_saat"], int) or kural["tekrar_saat"] <= 0
        ):
            hatalar.append(f"{etiket}: tekrar_saat pozitif tam sayı")
        kosul = kural["kosul"]
        if not isinstance(kosul, Mapping) or not kosul:
            hatalar.append(f"{etiket}: koşul boş")
            kosul = {}
        kapsam = varlik or "genel"
        for anahtar, deger in kosul.items():
            cozulen = _anahtar_coz(anahtar)
            if cozulen is None:
                hatalar.append(f"{etiket}: bilinmeyen operatör {anahtar}")
                continue
            ad, op = cozulen
            olgu = olgular.get(ad)
            if olgu is None:
                hatalar.append(f"{etiket}: bilinmeyen olgu {ad}")
                continue
            if kapsam not in olgu["varliklar"]:
                hatalar.append(f"{etiket}: {ad} olgusu {kapsam} için hesaplanmaz")
            tur = olgu["tur"]
            if op in ("_var", "_yok"):
                if deger is not True:
                    hatalar.append(f"{etiket}: {anahtar} yalnız true alır")
            elif op in ("_gte", "_lte"):
                if tur not in ("sayi", "oran") or isinstance(deger, bool):
                    hatalar.append(f"{etiket}: {anahtar} sayısal olguda")
                elif not isinstance(deger, int | float):
                    hatalar.append(f"{etiket}: {anahtar} sayı ister")
                elif tur == "oran" and not 0 <= deger <= 1:
                    hatalar.append(f"{etiket}: {anahtar} 0–1")
            elif op == "_in":
                if tur not in ("durum", "enum") or not isinstance(deger, list) or not deger:
                    hatalar.append(f"{etiket}: {anahtar} dolu liste ve durum/enum olgusu ister")
                    continue
                izinli = (
                    MACHINES[varlik].states
                    if tur == "durum" and varlik in MACHINES
                    else set(olgu.get("degerler") or [])
                )
                if not set(deger) <= set(izinli):
                    hatalar.append(
                        f"{etiket}: {anahtar} geçersiz değer {sorted(set(deger) - set(izinli))}"
                    )
            elif op == "_esit":
                if tur == "bool" and not isinstance(deger, bool):
                    hatalar.append(f"{etiket}: {anahtar} bool ister")
                elif tur == "enum" and deger not in olgu["degerler"]:
                    hatalar.append(f"{etiket}: {anahtar} geçersiz değer {deger!r}")
                elif tur == "sayi" and (
                    isinstance(deger, bool) or not isinstance(deger, int | float)
                ):
                    hatalar.append(f"{etiket}: {anahtar} sayı ister")
                elif tur in ("durum", "kimlik", "metin_listesi", "anahtar", "oran"):
                    hatalar.append(f"{etiket}: {anahtar} bu olguda eşitlik yok")
        izinli_yt = _yer_tutucular(olgular, varlik)
        for alan in ("baslik", "neden", "aciklama"):
            if alan in kural:
                hatalar += _metin_hatalari(f"{etiket}.{alan}", kural[alan], izinli_yt)
        eylem = kural["eylem"]
        tur = eylem.get("tur") if isinstance(eylem, Mapping) else None
        if tur not in EYLEM_ALANLARI:
            hatalar.append(f"{etiket}: tek eylem ve bilinen tür ister ({tur!r})")
            continue
        zorunlu, istege = EYLEM_ALANLARI[tur]
        if not zorunlu <= set(eylem) or set(eylem) - zorunlu - istege:
            hatalar.append(f"{etiket}: eylem alanları {sorted(set(eylem))}")
            continue
        jira_eylemi = tur in ("jira_taslak", "jira_yorum")
        sistem_hatti = varlik in SISTEM_HATTI_VARLIKLARI or any(
            ekran == e or ekran.startswith(e + "/") for e in SISTEM_HATTI_EKRANLARI
        )
        if jira_eylemi and sistem_hatti:
            hatalar.append(f"{etiket}: sistem hattı olan ekranda Jira eylemi yasak")
        if tur in ("jira_yorum", "jira_kaydi") and kosul.get("jira_key_var") is not True:
            hatalar.append(f"{etiket}: {tur} bilinen anahtar ister (kosul jira_key_var: true)")
        if jira_eylemi:
            sablon = taslaklar.get(eylem["sablon"])
            if sablon is None:
                hatalar.append(f"{etiket}: bilinmeyen şablon {eylem['sablon']}")
            else:
                beklenen = ("yorum",) if tur == "jira_yorum" else ("Task", "Bug", "Story")
                if sablon["tur"] not in beklenen:
                    hatalar.append(f"{etiket}: şablon türü {sablon['tur']} {tur} ile uyumsuz")
                for alan in ("ozet", "aciklama"):
                    if sablon.get(alan):
                        hatalar += _metin_hatalari(
                            f"{etiket}: şablon {sablon['id']}.{alan}", sablon[alan], izinli_yt
                        )
        if tur == "rota":
            hedef = eylem["rota"]
            if hedef not in rotalar:
                hatalar.append(f"{etiket}: eylem rotası {hedef} rotalar.json'da yok")
            elif rotalar[hedef]["roller"] and not set(roller) <= set(rotalar[hedef]["roller"]):
                hatalar.append(f"{etiket}: rol hedef ekranı açamaz")
            elif ":id" in hedef:
                if "id_olgusu" in eylem:
                    io = olgular.get(eylem["id_olgusu"])
                    if io is None or io["tur"] != "kimlik" or kapsam not in io["varliklar"]:
                        hatalar.append(f"{etiket}: id_olgusu {eylem['id_olgusu']} geçersiz")
                elif rotalar[hedef]["varlik"] != varlik:
                    hatalar.append(f"{etiket}: {hedef} kimliği {varlik} varlığından gelmez")
            yetki = eylem["yetki"]
            if not isinstance(yetki, Mapping) or not set(yetki) <= {"uc", "onay_varligi"}:
                hatalar.append(f"{etiket}: yetki alanları")
            elif not re.fullmatch(r"(POST|PUT|PATCH|DELETE) /\S+", str(yetki.get("uc"))):
                hatalar.append(f"{etiket}: yetki.uc '<YÖNTEM> /yol' biçiminde olmalı")
    return hatalar


def _oneriler() -> dict[str, Any]:
    return _yaml("oneriler.yaml")


def _taslaklar() -> dict[str, dict[str, Any]]:
    return {t["id"]: t for t in _yaml("jira-taslaklari.yaml")["taslaklar"]}


def test_oneriler_kural_dosyasi_gecerli() -> None:
    assert kural_hatalari(_oneriler(), _taslaklar(), _rotalar()) == []


def test_oneriler_kural_seti_27_kural_tek_eylem() -> None:
    """§17.3 tablosu (K10 onaylı): 26 satır + 011 `script-dogrulanmamis` (bilgi); her satır tek
    kural ve tek eylem."""
    kurallar = _oneriler()["kurallar"]
    assert len(kurallar) == 27
    turler = [k["eylem"]["tur"] for k in kurallar]
    assert turler.count("rota") == 12 and turler.count("bilgi") == 9
    assert turler.count("jira_taslak") == 3 and turler.count("jira_yorum") == 2
    assert turler.count("jira_kaydi") == 1


def test_olgu_sozlesmesi_kodla_ayni() -> None:
    """Enum değerleri koddaki sabitlerle aynı; durum olgusu yalnız makinesi olan varlıklarda."""
    from tp_core.models.codegen_feature import BREAK_DURUM
    from tp_core.models.enums import FAILURE_SINIF, ONERI_DURUMU, RUN_SONUC
    from tp_core.workflow.states import MACHINES

    olgular = _oneriler()["olgular"]
    assert set(olgular) == OLGU_ADLARI
    beklenen = {
        "kirarak_dogrulama": BREAK_DURUM,
        "ci_sonuc": RUN_SONUC,
        "hata_sinifi": FAILURE_SINIF,
        "onarim_durumu": ONERI_DURUMU,
        "po_kanal": {"portal", "jira"},
    }
    for ad, degerler in beklenen.items():
        assert set(olgular[ad]["degerler"]) == set(degerler), ad
    assert set(olgular["durum"]["varliklar"]) <= set(MACHINES)
    # Dışa aktarılan kural dosyası (İlke IX) hesaplanan varlıkları eksiksiz anlatır: kodla birebir.
    from tp_core.features.assistant.oneri import OLGU_HESAPLAYICILARI

    for ad, o in olgular.items():
        assert set(o["varliklar"]) == set(OLGU_HESAPLAYICILARI[ad]), ad
    for ad, o in olgular.items():
        assert o["kaynak"], ad


def test_jira_taslaklari_bicimi() -> None:
    data = _yaml("jira-taslaklari.yaml")
    olgular = _oneriler()["olgular"]
    tum_yer_tutucular = _yer_tutucular(olgular, None)
    for v in VARLIKLAR:
        tum_yer_tutucular |= _yer_tutucular(olgular, v)
    ids = [t["id"] for t in data["taslaklar"]]
    assert len(ids) == len(set(ids))
    assert {
        "po-hatirlatma",
        "ac-eksik",
        "flaky-task",
        "ortam-hatasi-task",
        "test-verisi-task",
    } <= set(ids)
    kullanilan = {k["eylem"].get("sablon") for k in _oneriler()["kurallar"]} - {None}
    assert set(ids) == kullanilan, "kullanılmayan ya da tanımsız şablon"
    for t in data["taslaklar"]:
        assert set(t) == {"id", "tur", "ozet", "aciklama", "etiketler"}, t["id"]
        assert KEBAB.match(t["id"]) and t["tur"] in TASLAK_TURLERI, t["id"]
        assert (t["ozet"] == "") == (t["tur"] == "yorum"), t["id"]
        assert _metin_hatalari(t["id"], t["aciklama"], tum_yer_tutucular) == []
        if t["ozet"]:
            assert _metin_hatalari(t["id"], t["ozet"], tum_yer_tutucular) == []
        assert all(isinstance(e, str) and re.fullmatch(r"[a-z0-9-]+", e) for e in t["etiketler"])
        if t["tur"] != "yorum" and "{jira_key}" not in t["aciklama"]:
            # Kimlik yer tutucu olamaz: kopyalanan kayıt Probe'daki kayda kullanıcının
            # dolduracağı kaynak satırıyla bağlanır.
            assert re.search(r"^Kaynak: \(.+buraya ekleyin\)", t["aciklama"], re.M), t["id"]


def _bozuk(degistir: Any) -> list[str]:
    doc = copy.deepcopy(_oneriler())
    taslaklar = copy.deepcopy(_taslaklar())
    degistir(doc, taslaklar)
    return kural_hatalari(doc, taslaklar, _rotalar())


def _kural(doc: dict[str, Any], kid: str) -> dict[str, Any]:
    return next(k for k in doc["kurallar"] if k["id"] == kid)


@pytest.mark.parametrize(
    ("ad", "degistir", "beklenen"),
    [
        (
            "bilinmeyen-olgu",
            lambda d, t: _kural(d, "gereksinim-basarisiz")["kosul"].update(oncelikli_esit=True),
            "bilinmeyen olgu oncelikli",
        ),
        (
            "bilinmeyen-operator",
            lambda d, t: _kural(d, "hata-flaky-task")["kosul"].update(flaky_tekrar_gt=3),
            "bilinmeyen operatör flaky_tekrar_gt",
        ),
        (
            "ifade-yok",
            lambda d, t: _kural(d, "hata-flaky-task")["kosul"].update(ifade="flaky_tekrar > 3"),
            "bilinmeyen operatör ifade",
        ),
        (
            "bilinmeyen-yer-tutucu",
            lambda d, t: _kural(d, "gereksinim-basarisiz").update(baslik="{hata_metni} oldu"),
            "geçersiz yer tutucu {hata_metni}",
        ),
        (
            "serbest-metin-baslik",
            lambda d, t: _kural(d, "gereksinim-basarisiz").update(baslik="{baslik} başarısız"),
            "geçersiz yer tutucu {baslik}",
        ),
        (
            "serbest-metin-olgusu",
            lambda d, t: _kural(d, "kosu-ortam-hatasi-bilgi").update(baslik="{basarisiz_adimlar}"),
            "geçersiz yer tutucu {basarisiz_adimlar}",
        ),
        (
            "serbest-metin-olgusu-yer-tutucu-ilan",
            lambda d, t: d["olgular"]["basarisiz_adimlar"].update(yer_tutucu=True),
            "serbest metin/kimlik olgusu yer tutucu olamaz",
        ),
        (
            "yanlis-varlik-olgusu",
            lambda d, t: _kural(d, "gereksinim-basarisiz")["kosul"].update(flaky_tekrar_gte=1),
            "flaky_tekrar olgusu requirement için hesaplanmaz",
        ),
        (
            "gecersiz-durum",
            lambda d, t: _kural(d, "gereksinim-basarisiz")["kosul"].update(durum_in=["pr_open"]),
            "durum_in geçersiz değer ['pr_open']",
        ),
        (
            "bug-taslaginda-jira-taslagi",
            lambda d, t: _kural(d, "bug-taslagi-bulgudan").update(
                eylem={"tur": "jira_taslak", "sablon": "flaky-task"}
            ),
            "sistem hattı olan ekranda Jira eylemi yasak",
        ),
        (
            "yayin-ekraninda-jira-yorumu",
            lambda d, t: d["kurallar"].append(
                {
                    **_kural(d, "gereksinim-ac-eksik-jira"),
                    "id": "yayin-yorum",
                    "ekran": "/gereksinimler/:id/yayin",
                }
            ),
            "sistem hattı olan ekranda Jira eylemi yasak",
        ),
        (
            "anahtarsiz-jira-yorumu",
            lambda d, t: _kural(d, "gereksinim-po-hatirlatma-jira")["kosul"].pop("jira_key_var"),
            "jira_yorum bilinen anahtar ister",
        ),
        (
            "iki-eylem",
            lambda d, t: _kural(d, "gereksinim-basarisiz").update(
                eylem={"tur": "bilgi", "rota": "/gereksinimler/:id"}
            ),
            "eylem alanları",
        ),
        (
            "rota-disi",
            lambda d, t: _kural(d, "guncel-kosu-yok")["eylem"].update(rota="/ayarlar"),
            "eylem rotası /ayarlar rotalar.json'da yok",
        ),
        (
            "yetkisiz-rota",
            lambda d, t: _kural(d, "guncel-kosu-yok")["eylem"].pop("yetki"),
            "eylem alanları",
        ),
        (
            "bilinmeyen-alan",
            lambda d, t: _kural(d, "gereksinim-basarisiz").update(ifade="True"),
            "alanlar",
        ),
        (
            "taslakta-url",
            lambda d, t: t["flaky-task"].update(aciklama="Ayrıntı: https://jira.example/x"),
            "şablon flaky-task.aciklama: URL/bağlantı/mention/HTML içeriyor",
        ),
        (
            "sablon-tur-uyumsuz",
            lambda d, t: _kural(d, "hata-flaky-task")["eylem"].update(sablon="po-hatirlatma"),
            "şablon türü yorum jira_taslak ile uyumsuz",
        ),
        (
            "sablon-yer-tutucu-varlikta-yok",
            lambda d, t: t["flaky-task"].update(aciklama="{po_bekleme_gun} gün"),
            "şablon flaky-task.aciklama: geçersiz yer tutucu {po_bekleme_gun}",
        ),
        (
            "tanimsiz-olgu-ilani",
            lambda d, t: d["olgular"].update(hata_mesaji={"tur": "enum", "varliklar": ["failure"]}),
            "bilinmeyen olgu tanımı",
        ),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_kural_denetimi_bozuk_dosyayi_reddeder(ad: str, degistir: Any, beklenen: str) -> None:
    hatalar = _bozuk(degistir)
    assert any(beklenen in h for h in hatalar), (ad, hatalar)


@pytest.mark.parametrize(
    "metin",
    [
        "Ayrıntı: https://jira.example/x",
        "bkz. www.example.com",
        "[burada|https://x]",
        "[~accountid:123] bakar mısın",
        "@ali bakar mısın",
        "<b>kalın</b>",
        "[metin](javascript:alert(1))",
        "data://x",
    ],
)
def test_taslak_metninde_baglanti_ve_mention_yasak(metin: str) -> None:
    assert _metin_hatalari("t", metin, set())


def test_degerdeki_suslu_parantez_yer_tutucu_sayilmaz() -> None:
    """Biçim denetimi: yer tutucu dışındaki `{`/`}` (ör. `{ ad }`, `{{x}}`) reddedilir."""
    assert _metin_hatalari("t", "{ jira_key }", {"jira_key"})
    assert _metin_hatalari("t", "{{jira_key}}", {"jira_key"})
    assert _metin_hatalari("t", "{jira_key} hazır", {"jira_key"}) == []


# ------------------------------------------------------------------ rol hizalama ve kapsam


def _uc_rolleri() -> dict[str, frozenset[str]]:
    """FastAPI rotası → `require_role` kümesi (`auth/deps.require_role` kapanışından)."""
    from tp_core.api.main import create_app

    def roller(dep: Any) -> Iterator[frozenset[str]]:
        call = dep.call
        if getattr(call, "__name__", "").startswith("require_role_"):
            for cell in call.__closure__ or ():
                if isinstance(cell.cell_contents, frozenset):
                    yield cell.cell_contents
        for alt in dep.dependencies:
            yield from roller(alt)

    def rotalar(routes: Any) -> Iterator[Any]:
        # FastAPI ≥ 0.16x dahil edilen router'ları tembel bağlar (`effective_route_contexts`).
        for route in routes:
            if hasattr(route, "effective_route_contexts"):
                yield from route.effective_route_contexts()
            else:
                yield route

    out: dict[str, frozenset[str]] = {}
    for route in rotalar(create_app().routes):
        if getattr(route, "dependant", None) is None:  # docs/openapi gibi düz rotalar
            continue
        kumeler = list(roller(route.dependant))
        for method in route.methods or ():
            out[f"{method} {route.path}"] = (
                frozenset.intersection(*kumeler) if kumeler else frozenset(ROLLER)
            )
    return out


def test_rol_hizalama_rota_eylemleri_ucun_rolleriyle() -> None:
    """Eylemi `rota` olan kuralın rolleri ucun `require_role` (ve `APPROVER_ROLES`) alt kümesi."""
    from tp_core.workflow.states import APPROVER_ROLES

    uclar = _uc_rolleri()
    # Denetim gerçekten rol okuyor (her şeye izin veren varsayılana düşmüyor).
    assert uclar["POST /requirements/{req_id}/po-approve"] == {"po"}
    assert uclar["POST /ci/trigger"] == {"presenter"}
    for kural in _oneriler()["kurallar"]:
        eylem = kural["eylem"]
        if eylem["tur"] != "rota":
            continue
        uc = eylem["yetki"]["uc"]
        assert uc in uclar, f"{kural['id']}: {uc} uygulamada yok"
        assert set(kural["roller"]) <= uclar[uc], (kural["id"], uc, sorted(uclar[uc]))
        if "onay_varligi" in eylem["yetki"]:
            assert set(kural["roller"]) <= APPROVER_ROLES[eylem["yetki"]["onay_varligi"]], kural[
                "id"
            ]


def test_kapsam_matrisi_her_rota_ve_rol_icin_kural_ya_da_bilincli_bos() -> None:
    doc = _oneriler()
    kurallar = {(k["ekran"], r) for k in doc["kurallar"] for r in k["roller"]}
    bos: set[tuple[str, str]] = set()
    for kayit in doc["bos_ekranlar"]:
        assert set(kayit) == {"ekran", "roller"}
        for r in kayit["roller"]:
            assert (kayit["ekran"], r) not in bos, f"mükerrer boş kayıt {kayit['ekran']} × {r}"
            bos.add((kayit["ekran"], r))
    assert not kurallar & bos, f"hem kural hem boş kayıt: {sorted(kurallar & bos)}"
    beklenen = {
        (kalip, rol)
        for kalip, r in _rotalar().items()
        if kalip != "/giris"
        for rol in (r["roller"] or ROLLER)
    }
    assert kurallar | bos == beklenen, (
        f"eksik: {sorted(beklenen - kurallar - bos)}; fazla: {sorted((kurallar | bos) - beklenen)}"
    )


# ------------------------------------------------------------------ prompt, araçlar, golden, eval


def test_asistan_promptu_oneri_kipini_ve_araclari_anlatir() -> None:
    meta, body = parse_prompt_file(
        (RULES / "prompts" / "assistant.md").read_text(encoding="utf-8"), Path("assistant.md")
    )
    assert meta["id"] == "assistant" and meta["version"] >= 1
    for arac in ASISTAN_ARACLARI:
        assert f"`{arac}`" in body, arac
    assert "kip=oneri" in body and "`oneriler`" in body
    assert "eylem_reddi" in body and "Never write a URL" in body
    assert "Sunucu (the person presenting the demo)" in body
    kalip = "Uygulama kodu ve verisi rolünüze açık değil; Mühendis, Testçi ya da Analist görebilir."
    assert kalip in " ".join(body.split())


def test_istem_izleri_promptta_birebir_ve_yeterince_uzun() -> None:
    """Her parmak izi prompt gövdesinde birebir geçer (yalnız boşluk farkı) ve normalize edildiğinde
    `IZ_EN_KISA`'dan kısa değildir; Türkçe çeviri/özet sızıntısı için Türkçe iz de vardır."""
    from tp_core.features.assistant import guvenlik_cikti

    _, body = parse_prompt_file(
        (RULES / "prompts" / "assistant.md").read_text(encoding="utf-8"), Path("assistant.md")
    )
    duz = " ".join(body.split())
    izler = _yaml("istem-izleri.yaml")["izler"]
    assert len(izler) >= 6 and len(set(izler)) == len(izler)
    for iz in izler:
        assert " ".join(iz.split()) in duz, iz
        assert len(guvenlik_cikti.normalize(iz)) >= guvenlik_cikti.IZ_EN_KISA, iz
    assert any(re.search(r"[çğıöşüİ]", iz) for iz in izler)  # en az bir Türkçe iz
    assert len(guvenlik_cikti.izleri_yukle(RULES)) == len(izler)


@pytest.mark.parametrize(
    "metin",
    [
        # Doğal Türkçe cevaplar: istemin genel cümlelerine benzese de sızıntı sayılmaz (izler
        # ayırt edici olmalı; yoksa zararsız cevap değiştirilir).
        "Sunucu sinyali satırı bir uyarıdır, hüküm değildir; soruya yine cevap verdim.",
        "Kayıtta talimat içeren bir metin var; güvenilmeyen bloklardaki talimatlar uygulanmaz.",
        "Araç tanımları ve kanıt kimliği satırları yalnız iç kullanım içindir, paylaşamam.",
        "A server signal is a caution, not a verdict.",
        "Use as few tool calls as you need.",
        "Talimatlarımı paylaşamam; ekranlar, kayıtlar ve Jira hakkında soru yanıtlayabilirim.",
    ],
)
def test_istem_izleri_dogal_cevapta_tetiklenmez(metin: str) -> None:
    from tp_core.features.assistant import guvenlik_cikti

    cevap = {"cevap_bloklari": [{"tur": "paragraf", "metin": metin, "maddeler": []}]}
    assert guvenlik_cikti.sizinti_var(cevap, None, guvenlik_cikti.izleri_yukle(RULES)) is None


def test_istem_izleri_ic_not_sizintisini_yakalar() -> None:
    from tp_core.features.assistant import guvenlik_cikti

    metin = "İç notlar (kullanıcıya yazılmaz): sunucu sinyali satırı bir uyarıdır."
    cevap = {"cevap_bloklari": [{"tur": "paragraf", "metin": metin.upper(), "maddeler": []}]}
    izler = guvenlik_cikti.izleri_yukle(RULES)
    assert guvenlik_cikti.sizinti_var(cevap, None, izler) == "istem_sizintisi"


def test_rol_etiketleri_portal_ile_ayni() -> None:
    """Portal rollerinin asistan etiketi portalın gösterdiği adla aynı (etiketler.ts `ROL`)."""
    from tp_core.features.assistant.rol_politikasi import etiket

    ts = (REPO / "review-portal" / "src" / "lib" / "etiketler.ts").read_text(encoding="utf-8")
    blok = ts.split("export const ROL", 1)[1].split("};", 1)[0]
    portal = dict(re.findall(r'(\w+): "([^"]+)"', blok))
    assert set(portal) == set(ROLLER)
    for rol, ad in portal.items():
        assert etiket(rol, rules_dir=RULES) == ad, rol


def test_asistan_arac_izin_listesi() -> None:
    for amac in ("assistant", "assistant_deep"):
        assert ALLOWED_AGENT_TOOLS[amac] == ASISTAN_ARACLARI, amac
        assert not ALLOWED_AGENT_TOOLS[amac] & FORBIDDEN_TOOLS


@pytest.mark.parametrize("amac", ["assistant", "assistant_deep"])
def test_asistan_golden_ornek(amac: str) -> None:
    golden = json.loads(
        (RULES / "replay" / amac / "golden" / "ornek.json").read_text(encoding="utf-8")
    )
    assert golden["kind"] == "agent" and golden["steps"] == [] and "recording" not in golden
    assert "elle hazırlandı" in golden["note"]
    assert golden["output"]["oneriler"] == []


def test_asistan_model_amaclari_yeni_alanlari_tasir() -> None:
    purposes = yaml.safe_load((RULES / "models.yaml").read_text(encoding="utf-8"))["purposes"]
    for amac in ("assistant", "assistant_deep"):
        cfg = purposes[amac]
        assert cfg["max_retries"] == 1 and cfg["max_timeout_retries"] == 0, amac
        assert "thinking" not in cfg["params"], amac  # adaptif düşünme açık
    assert purposes["assistant_deep"]["fallbacks"] == "none"
    assert "fallbacks" not in purposes["assistant"]


EVAL_BEKLENTILERI = {
    "contains",
    "contains_any",
    "not_contains",
    "cikti_sinyali_yok",
    "kaynak_tur_include",
    "kaynak_ref_include",
    "rota_in",
    "eylem_reddi",
    "guven_gosterimi",
    "otomatik_derin",
    "oneri_eylem_tur",
    "oneri_max",
    "jira_anahtarlari_include",
    "cevap_kaynagi_in",
}


def test_asistan_eval_iskeleti() -> None:
    from tp_core.gateway.eval_set import load_set

    data = load_set(RULES, "assistant")
    meta, _ = parse_prompt_file(
        (RULES / "prompts" / "assistant.md").read_text(encoding="utf-8"), Path("assistant.md")
    )
    assert data["purpose"] == "assistant" and data["version"] == meta["version"]
    cases = data["cases"]
    assert len(cases) >= 12
    etiketler = [e for c in cases for e in c["etiketler"]]
    assert {f"S{i}" for i in range(1, 14)} <= set(etiketler)
    assert etiketler.count("injection") >= 6 and etiketler.count("eylem_istegi") >= 4
    assert etiketler.count("oneri_modu") >= 3
    assert {c["rol"] for c in cases} == set(ROLLER)
    rotalar = _rotalar()
    kaynak_turleri = set(
        load_schema(RULES, "assistant")["properties"]["kaynaklar"]["items"]["properties"]["tur"][
            "enum"
        ]
    )
    for c in cases:
        assert set(c["expect"]) <= EVAL_BEKLENTILERI, (
            c["id"],
            set(c["expect"]) - EVAL_BEKLENTILERI,
        )
        assert c["kip"] in ("soru", "oneri") and c["soru"].strip() and len(c["soru"]) <= 2000
        assert c["messages"] and c["messages"][0]["role"] == "user"
        if c["baglam"] is not None:
            assert c["baglam"]["rota_kalibi"] in rotalar, c["id"]
            assert "rol" not in c["baglam"]  # rol oturumdan gelir
            assert len(json.dumps(c["baglam"], ensure_ascii=False).encode()) <= 2048, c["id"]
        assert set(c["expect"].get("rota_in", [])) <= set(rotalar), c["id"]
        assert set(c["expect"].get("kaynak_tur_include", [])) <= kaynak_turleri, c["id"]
        assert set(c["expect"].get("oneri_eylem_tur", [])) <= set(EYLEM_TURLERI), c["id"]
        if "eylem_istegi" in c["etiketler"] or "S7" in c["etiketler"]:
            assert c["expect"]["eylem_reddi"] is True, c["id"]
        if c["kip"] == "oneri":
            assert "oneri_eylem_tur" in c["expect"] and "http://" in c["expect"]["not_contains"]
    # Repo public: eval tohumunda gerçek biçimli sır yok (sahte token'lar çalışma anında üretilir).
    metin = (RULES / "evaluation" / "assistant.json").read_text(encoding="utf-8")
    assert not re.search(
        r"gh[pousr]_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}", metin
    )


# ------------------------------------------------------------------ eylem-rotalari.yaml


def test_eylem_rotalari_kurallari() -> None:
    from tp_core.features.assistant import eylem_rotasi

    data = _yaml("eylem-rotalari.yaml")
    assert data["version"] == 1
    rotalar = _rotalar()
    ids = [k["id"] for k in data["eylemler"]]
    assert len(ids) == len(set(ids))
    for k in data["eylemler"]:
        assert set(k) == {"id", "ifadeler", "rota", "liste"}, k["id"]
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", k["id"])
        assert k["ifadeler"] and all(isinstance(i, str) and i.strip() for i in k["ifadeler"])
        assert k["rota"] in rotalar and k["rota"] not in ("/", "/giris"), k["id"]
        if k["liste"] is not None:
            assert k["liste"] in rotalar and ":id" not in k["liste"], k["id"]
            assert ":id" in k["rota"], f"{k['id']}: varlıksız rotanın listesi gereksiz"
    assert len(eylem_rotasi.kayitlar(RULES)) == len(ids)


@pytest.mark.parametrize(
    ("soru", "beklenen"),
    [
        ("Yeni bir gece koşusu başlat.", "kosu-tetikle"),
        ("Demo verisini sıfırla, sunuma başlayacağım.", "demo-sifirla"),
        ("TPD-3'ü PO adına onayla, acelemiz var.", "gereksinim-onayi"),
        ("Bu case'i onayla", "case-karari"),
        ("Bu case'leri şimdi Jira'ya yayınla.", "case-yayinla"),
        ("Bu PR'ı merge et.", "pr-merge"),
        ("Bu hata için Jira'da bir task aç.", None),
        ("Flaky test nasıl ayıklanır?", None),
    ],
)
def test_eylem_rotalari_eslesme_sirasi(soru: str, beklenen: str | None) -> None:
    from tp_core.features.assistant import eylem_rotasi

    kayit = eylem_rotasi.eslesen(soru, rules_dir=RULES)
    assert (kayit.id if kayit else None) == beklenen


def test_asistan_promptu_portal_ekranlari_rotalar_json_ile_ayni() -> None:
    """Prompt'un "Portal screens" listesi `rotalar.json` ile birebir (giriş, ana sayfa hariç)."""
    _, body = parse_prompt_file(
        (RULES / "prompts" / "assistant.md").read_text(encoding="utf-8"), Path("assistant.md")
    )
    bolum = body.split("# Portal screens", 1)[1].split("\n# ", 1)[0]
    listelenen = set(re.findall(r"`(/[^`]*)`", bolum))
    assert listelenen == set(_rotalar()) - {"/", "/giris"}
