"""Swift / XCUITest worker eklentisi (014, Ş4): sembol tablosu, üretilen test koruması, Kimlikler
saflığı, çağrı doğrulaması, onarım farkı ve `run_static` akışı.

tree-sitter-swift yoksa atlanır (imajda `TP_DIL_STATIK`; yerelde
`uv run --with tree-sitter==0.26.1 --with tree-sitter-swift==0.7.4 pytest tests/test_dil_swift.py`).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("tree_sitter_swift")

from tests.conftest import git
from worker.diller import swift

TOOLCHAIN = Path(__file__).resolve().parents[1]
REPO = TOOLCHAIN.parent
UI = REPO / "demo-app" / "mobile" / "ios-test" / "BayiSiparisUITests"
GOLDEN = REPO / "core/tests/unit/features/codegen/golden/TPD1IosC2_3f9b1c2eTests.swift"
CORE_TABLO = REPO / "core/tests/unit/features/codegen/symbols-swift.json"
URETILEN = "TPUretilen/TPD1IosC2_3f9b1c2eTests.swift"


def koru(metin: str, yol: str = URETILEN) -> list[dict[str, Any]]:
    return swift.uretilen_koruma(yol, metin.encode("utf-8"))[0]


def golden() -> str:
    return GOLDEN.read_text(encoding="utf-8")


# ------------------------------------------------------------------------------ semboller


def test_sembol_tablosu_core_kopyasiyla_ayni() -> None:
    """Core golden testlerinin kullandığı tablo, demo kütüphanesinden üretilenle aynı."""
    tablo = swift.semboller(UI)
    assert tablo["errors"] == []
    assert tablo == json.loads(CORE_TABLO.read_text(encoding="utf-8"))


def test_sembol_tablosu_icerigi() -> None:
    t = swift.semboller(UI)
    assert t["lang"] == "swift"
    assert t["fixtures"] == [
        "girisEkrani",
        "katalogEkrani",
        "onayEkrani",
        "sepetEkrani",
        "siparisEkrani",
    ]
    po = {p["class"]: p for p in t["page_objects"]}
    giris = {m["name"]: m for m in po["GirisEkrani"]["methods"]}
    assert [(p["label"], p["type"], p["swift_type"]) for p in giris["girisYap"]["params"]] == [
        ("kullaniciAdi", "string", "String"),
        ("parola", "string", "String"),
    ]
    assert giris["dogrulaHataMesaji"]["kind"] == "expect"
    assert giris["ac"]["kind"] == "action"
    assert giris["girisYap"]["doc"] == "Bayi kullanıcı adı ve parolasıyla giriş yapar."
    # private yardımcılar ve dönüş türlü metotlar tabloya girmez
    katalog = {m["name"] for m in po["KatalogEkrani"]["methods"]}
    assert "sepetSayaci" not in katalog and "sayacHemen" not in katalog
    assert "siparisNumarasiniOku" not in {m["name"] for m in po["OnayEkrani"]["methods"]}
    # Taban sınıf ve test tabanı tabloda yok
    assert "Ekran" not in po and "TestTabani" not in po
    loc = po["GirisEkrani"]["locators"]["Giris.kullaniciAdi"]
    assert (loc["testId"], loc["prefix"], loc["intent"]) == (
        "login-username", False, "Giriş formunda kullanıcı adı alanı.",
    )  # fmt: skip
    assert po["KatalogEkrani"]["locators"]["Katalog.urunKartiOnek"]["prefix"] is True
    assert {
        "key": "Menu.katalog",
        "testId": "nav-catalog",
        "intent": "Üst menüde ürün kataloğuna giden bağlantı.",
        "prefix": False,
    } in t["ids"]
    assert t["locator_files"] == [
        {
            "file": "Ekranlar/Kimlikler.swift",
            "exports": ["Menu", "Giris", "Katalog", "Sepet", "Onay", "Siparis"],
        }
    ]


def test_parametre_etiketi_varsayilan_ve_tur(tmp_path: Path) -> None:
    (tmp_path / "Ekranlar").mkdir()
    (tmp_path / "Ekranlar/Kimlikler.swift").write_text("enum Kimlikler {}\n", encoding="utf-8")
    (tmp_path / "Ekranlar/X.swift").write_text(
        "final class XEkrani: Ekran {\n"
        "    func a(_ kod: String, adet n: Int = 2, oran: Double, acik: Bool, t: Date) {}\n"
        "    static func s() {}\n    override func o() {}\n    fileprivate func g() {}\n"
        "}\n",
        encoding="utf-8",
    )
    t = swift.semboller(tmp_path)
    m = t["page_objects"][0]["methods"]
    assert [x["name"] for x in m] == ["a"]
    assert [(p["name"], p["label"], p["type"], p["optional"]) for p in m[0]["params"]] == [
        ("kod", "_", "string", False),
        ("n", "adet", "long", True),
        ("oran", "oran", "double", False),
        ("acik", "acik", "boolean", False),
        ("t", "t", "Date", False),
    ]
    assert t["fixtures"] == ["xEkrani"]


# ------------------------------------------------------------------------------ üretilen koruma


def test_golden_korumadan_gecer_ve_cagrilar_dogru() -> None:
    ihlal, cagrilar = swift.uretilen_koruma(URETILEN, golden().encode("utf-8"))
    assert ihlal == []
    assert [(c.erisimci, c.metot) for c in cagrilar][:3] == [
        ("girisEkrani", "ac"), ("girisEkrani", "girisYap"), ("katalogEkrani", "sepeteEkle"),
    ]  # fmt: skip
    assert swift.cagrilari_dogrula(URETILEN, cagrilar, swift.semboller(UI)) == []


def test_demo_uretilen_ornegi_golden_ile_ayni() -> None:
    assert (UI / URETILEN).read_text(encoding="utf-8") == golden()


def _degistir(eski: str, yeni: str) -> str:
    g = golden()
    assert eski in g
    return g.replace(eski, yeni, 1)


@pytest.mark.parametrize(
    ("eski", "yeni", "kod"),
    [
        ("import XCTest", "import XCTest\nimport Foundation", "import"),
        ("import XCTest", "@testable import XCTest", "import"),
        ("final class", "class", "sinif"),
        (": TestTabani", ": XCTestCase", "miras"),
        ("TPD1IosC2_3f9b1c2eTests:", "Baska:", "sinif_adi"),
        ("func testSenaryo()", "func testSenaryo() throws", "test"),
        ("func testSenaryo()", "func testBaska()", "test"),
        ("func testSenaryo()", "private func testSenaryo()", "test"),
        ("        girisEkrani.ac()\n", "        let p = Process()\n", "deyim"),
        (
            "        girisEkrani.ac()\n",
            '        FileManager.default.removeItem(atPath: "/")\n',
            "deyim",
        ),
        ("        girisEkrani.ac()\n", "        girisEkrani.ac { }\n", "deyim"),
        ("        girisEkrani.ac()\n", "        if true { girisEkrani.ac() }\n", "deyim"),
        ("adet: 7)\n", "adet: 3 + 4)\n", "deyim"),
        ('"bayi1", parola', '"\\(ProcessInfo())", parola', "deyim"),
        ('parola: "Demo123!"', 'parola: ortam("HOME")', "deyim"),
        ('parola: "Demo123!"', "parola: x", "deyim"),
        ('{ "bayi1" }', "{ evil() }", "ozellik"),
        ("    func testSenaryo()", "    func ek() {}\n    func testSenaryo()", "test"),
        ("// Senaryo:", "/* blok */\n// Senaryo:", "yorum"),
        ("// S1", "// S1 ‮", "gorunmez_karakter"),
        ("}\n}\n", "}\n}\nfunc disarida() {}\n", "ust_duzey"),
        ("    func testSenaryo()", "    var x = 1\n    func testSenaryo()", "ozellik"),
        ("    func testSenaryo()", "    init() {}\n    func testSenaryo()", "uye"),
    ],
)
def test_koruma_ihlalleri(eski: str, yeni: str, kod: str) -> None:
    kodlar = {i["code"] for i in koru(_degistir(eski, yeni))}
    assert kod in kodlar or "sozdizimi" in kodlar, kodlar


def test_ortam_sirri_ve_kacisli_dize_gecer() -> None:
    m = _degistir('parola: "Demo123!"', 'parola: ortam("TP_TESTVERI_BAYI1_PAROLA")')
    m = m.replace('tutar: "175,00 TL"', 'tutar: "a\\"b\\\\c\\u{202E}"')
    assert koru(m) == []


def test_dosya_adi_sinifla_ayni_olmali() -> None:
    assert "sinif_adi" in {
        i["code"] for i in koru(golden(), "TPUretilen/TPD1IosC3_3f9b1c2eTests.swift")
    }


# ------------------------------------------------------------------------------ çağrı doğrulaması


@pytest.mark.parametrize(
    ("eski", "yeni", "kod"),
    [
        ("girisEkrani.ac()", "girisEkrani.yok()", "bilinmeyen_metot"),
        ("girisEkrani.ac()", "baskaEkrani.ac()", "bilinmeyen_erisimci"),
        ('kullaniciAdi: "bayi1"', 'kullanici: "bayi1"', "etiket"),
        ("adet: 7)", 'adet: "7")', "tur"),
        ("adet: 7)", "adet: 7.5)", "tur"),
        ('tutar: "175,00 TL"', "tutar: true", "tur"),
        ("girisEkrani.ac()", "girisEkrani.ac(x: 1)", "arguman_sayisi"),
    ],
)
def test_cagri_dogrulama(eski: str, yeni: str, kod: str) -> None:
    ihlal, cagrilar = swift.uretilen_koruma(URETILEN, _degistir(eski, yeni).encode("utf-8"))
    assert ihlal == []
    kodlar = {i["code"] for i in swift.cagrilari_dogrula(URETILEN, cagrilar, swift.semboller(UI))}
    assert kod in kodlar


# ------------------------------------------------------------------------------ Kimlikler


@pytest.mark.parametrize(
    "ek",
    [
        "    static func f() {}\n",
        '    static var x = "a"\n',
        "    static let x = 1\n",
        '    static let x = "a\\(b)"\n',
        '    enum Ic { static let y = "z" }\n',
    ],
)
def test_kimlikler_saf_veri(ek: str) -> None:
    temiz = (UI / swift.KIMLIKLER).read_text(encoding="utf-8")
    assert swift.kimlikler_korumasi(swift.KIMLIKLER, temiz.encode()) == []
    kirli = temiz.replace("    enum Menu {\n", "    enum Menu {\n    " + ek, 1)
    assert swift.kimlikler_korumasi(swift.KIMLIKLER, kirli.encode())


def test_kimlikler_ust_duzeyde_baska_kod_olamaz() -> None:
    temiz = (UI / swift.KIMLIKLER).read_text(encoding="utf-8")
    assert swift.kimlikler_korumasi(swift.KIMLIKLER, (temiz + "func f() {}\n").encode())


# ------------------------------------------------------------------------------ kök ve git akışı


def test_validate_test_file() -> None:
    assert swift.validate_test_file(URETILEN) == URETILEN
    for kotu in (
        "../x/TPD1IosC2_3f9b1c2eTests.swift",
        "TPUretilen/Kotu.swift",
        "Testler/GirisTesti.swift",
    ):
        with pytest.raises(ValueError):
            swift.validate_test_file(kotu)


@dataclass
class _Cfg:
    git_timeout_s: float = 30
    dil_kokleri: dict[str, str] = field(default_factory=dict)


def test_kok_cozumu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TP_IOS_SWIFT_ROOT", raising=False)
    monkeypatch.delenv("TP_IOS_SWIFT_ROOT_IOS", raising=False)
    assert swift.kok(_Cfg()) == "UITests"
    monkeypatch.setenv("TP_IOS_SWIFT_ROOT", "ios/AppUITests/")
    assert swift.kok(_Cfg()) == "ios/AppUITests"
    monkeypatch.setenv("TP_IOS_SWIFT_ROOT_IOS", "AyriDepo/UITests")
    assert swift.kok(_Cfg()) == "AyriDepo/UITests"
    assert swift.kok(_Cfg(dil_kokleri={"TP_IOS_SWIFT_ROOT": "blok/UITests"})) == "blok/UITests"


@pytest.fixture
def depo(tmp_path: Path) -> tuple[Path, str, str]:
    """UI test klasörü `UITests` olan geçici depo; main + golden testi ekleyen dal."""
    work = tmp_path / "work"
    shutil.copytree(UI, work / "UITests", ignore=shutil.ignore_patterns("TPUretilen"))
    git(work.parent, "init", "-q", "-b", "main", str(work))
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "taban")
    base = git(work, "rev-parse", "HEAD")
    (work / "UITests/TPUretilen").mkdir()
    (work / "UITests" / URETILEN).write_text(golden(), encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "üretilen")
    return work / ".git", base, git(work, "rev-parse", "HEAD")


@dataclass
class _Req:
    test_files: list[str]
    platform: str = "ios"
    ast_guard_mode: str = "pr"


@dataclass
class _Head:
    repo: Path
    sha: str


def test_run_static_yesil(depo: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_IOS_SWIFT_ROOT", "UITests")
    repo, base, head = depo
    steps = swift.EKLENTI.run_static(_Cfg(), _Req([URETILEN]), _Head(repo, head), base, None, {})
    assert steps["guard"]["ok"], steps["guard"]
    assert steps["guard"]["report"]["files"] == [URETILEN]
    assert steps["semboller"]["ok"], steps["semboller"]
    assert "run" not in steps
    assert swift.EKLENTI.steps == ("guard", "semboller") and swift.EKLENTI.hat == "musteri_ci"


def test_run_static_eksik_dosya(
    depo: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_IOS_SWIFT_ROOT", "UITests")
    repo, base, head = depo
    yok = "TPUretilen/TPD1IosC9_3f9b1c2eTests.swift"
    steps = swift.EKLENTI.run_static(_Cfg(), _Req([yok]), _Head(repo, head), base, None, {})
    assert not steps["guard"]["ok"] and steps["guard"]["missing_test_files"] == [yok]


def test_run_static_bilinmeyen_metot_kirmizi(
    depo: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_IOS_SWIFT_ROOT", "UITests")
    repo, base, _ = depo
    (repo.parent / "UITests" / URETILEN).write_text(
        golden().replace("girisEkrani.ac()", "girisEkrani.uc()"), encoding="utf-8"
    )
    git(repo.parent, "commit", "-qam", "bozuk")
    head = git(repo.parent, "rev-parse", "HEAD")
    steps = swift.EKLENTI.run_static(_Cfg(), _Req([URETILEN]), _Head(repo, head), base, None, {})
    assert steps["guard"]["ok"]
    assert not steps["semboller"]["ok"]
    assert steps["semboller"]["violations"][0]["code"] == "bilinmeyen_metot"


def test_symbols_ve_guard_ucu(depo: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_IOS_SWIFT_ROOT", "UITests")
    repo, base, head = depo
    t = swift.EKLENTI.symbols(_Cfg(), head, repo, "ios")
    assert t["root"] == "UITests" and len(t["page_objects"]) == 5
    rapor = swift.EKLENTI.guard(_Cfg(), repo, base, head, "pr", "ios")
    assert rapor["ok"] and rapor["tool"] == "tree-sitter-swift"


def test_onarim_yalniz_kimlik_degeri(
    depo: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_IOS_SWIFT_ROOT", "UITests")
    repo, _, base = depo
    work = repo.parent
    k = work / "UITests" / swift.KIMLIKLER
    k.write_text(
        k.read_text(encoding="utf-8").replace('"login-submit"', '"login-button"'), encoding="utf-8"
    )
    git(work, "commit", "-qam", "onarım")
    head = git(work, "rev-parse", "HEAD")
    rapor = swift.EKLENTI.guard(_Cfg(), repo, base, head, "repair", "ios")
    assert rapor["ok"], rapor["violations"]
    assert rapor["testid_changes"] == [
        {"key": "Giris.girisYap", "from": "login-submit", "to": "login-button"}
    ]

    # Anahtar ekleme ve başka dosya değişikliği reddedilir.
    k.write_text(
        k.read_text(encoding="utf-8").replace(
            '        static let hata = "login-error"\n',
            '        static let hata = "login-error"\n        static let yeni = "x"\n',
        ),
        encoding="utf-8",
    )
    ekran = work / "UITests/Ekranlar/GirisEkrani.swift"
    ekran.write_text(ekran.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    git(work, "commit", "-qam", "fazla")
    head2 = git(work, "rev-parse", "HEAD")
    kodlar = {
        v["code"]
        for v in swift.EKLENTI.guard(_Cfg(), repo, base, head2, "repair", "ios")["violations"]
    }
    assert {"locator_keys_changed", "non_locator_file_changed"} <= kodlar
