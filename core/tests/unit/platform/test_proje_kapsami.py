"""Proje kapsamı statik (AST) denetimi (TP-COK-PROJE-PLANI §2.4) — cırcır (ratchet).

Kurallar (`core/src/tp_core/**.py`):

- `sql`: SQL metninde (`"... FROM requirement ..."`, f-string dahil) kapsamlı tablo geçiyor ama
  `project_id` geçmiyor.
- `job`: `job` tablosu (`project_id` NULL olabilir: kurulum işi) `tur`/`yuk`/`idempotency_key` ile
  süzülüyor ama `project_id` geçmiyor (hız sınırı / tekil iş denetimi projeler arası sayardı).
  Yalnız id ile tek satır okuma serbesttir; `workflow/jobs.py` ve `worker/` (kuyruk) izinli.
- `tum_projeler`: `execution_options(tum_projeler=True)` / `TUM_PROJELER` izinli modül dışında.
- `thread`: `threading.Thread(` / `ThreadPoolExecutor(` çağıran fonksiyon `baglamla`,
  `proje_icinde` ya da `copy_context` kullanmıyor (iş parçacığı bağlamı miras almaz).
- `env`: `PROJE_ANAHTARLARI`'ndaki bir ad `os.environ`/`os.getenv` (ya da `_env`/`_ortam*`
  yardımcıları) ile okunuyor (`home_config/` ve `proje/ayar.py` izinli; `ayar()` kullanın).

Geçişte kalan ihlaller şerit başına taban dosyalarındadır: `proje_istisna/serit{1..5}.txt`, satır
biçimi `yol:kural:imza  # gerekçe`. Her şerit yalnız kendi dosyasını küçültür; giderilen ihlalin
satırı silinmezse test düşer, tabanda olmayan yeni ihlal de düşer. Dosyaya yeni satır eklemek
review'da reddedilir (yalnız gerekçeli kalıcı istisna).
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest

from tp_core.integrations.proje_ortami import EK_PROJE_ANAHTARLARI
from tp_core.proje.ayar import PROJE_ANAHTARLARI as _AYAR_ANAHTARLARI
from tp_core.proje.orm import kapsamli_tablolar

# §3.3 T/A/P adları + Şerit 3'ün proje ortamı adları (demo/e2e kökü, test kullanıcısı,
# TP_APP_*_<P>).
PROJE_ANAHTARLARI: frozenset[str] = _AYAR_ANAHTARLARI | EK_PROJE_ANAHTARLARI

SRC = Path(__file__).resolve().parents[3] / "src"
ISTISNA_DIZINI = Path(__file__).resolve().parent / "proje_istisna"
SERITLER = (1, 2, 3, 4, 5)

# §1.1 A — planlanan kapsamlı tablolar (mixin uygulanınca `kapsamli_tablolar()` ile birleşir).
PLAN_KAPSAMLI: frozenset[str] = frozenset(
    [
        "requirement",
        "requirement_review",
        "requirement_review_ek",
        "requirement_kontrol",
        "requirement_akis",
        "requirement_baz_deger",
        "consistency_finding",
        "consistency_finding_ek",
        "acik_soru",
        "test_case",
        "review",
        "case_goruntuleme",
        "case_uretim",
        "test_verisi_kaynagi",
        "tasarim_modeli",
        "case_set_review",
        "case_set_audit",
        "case_oracle_kontrol",
        "oracle_istisna",
        "karar_tablosu",
        "metamorfik_iliski",
        "metamorfik_turetme",
        "script",
        "script_test_case",
        "script_codegen",
        "script_adim",
        "script_kontrol",
        "step_mapping",
        "pull_request",
        "run",
        "run_aria",
        "test_result",
        "test_result_ek",
        "failure",
        "failure_ek",
        "triage_kosu",
        "bug_draft",
        "bug_draft_ek",
        "external_ref",
        "ci_tetik",
        "hata_kosusu",
        "hata_kosusu_adim",
        "otomasyon_ayari",
        "test_verisi",
        "test_verisi_surum",
        "ajan_urunu_baglantisi",
        "ajan_testi_talebi",
        "asistan_denetim",
        "asistan_sohbet",
        "asistan_mesaj",
        "asistan_oneri_geri_bildirim",
        "asistan_guvenlik_olay",
        "asistan_durum",
        "workflow_instance",
        "ai_call",
        "tool_call",
        "audit_event",
        "api_token",
    ]
)

TUM_PROJELER_IZINLI = (
    "tp_core/proje/",
    "tp_core/workflow/jobs.py",
    "tp_core/worker/",
)
# Fonksiyon düzeyi muafiyet: (yol, fonksiyon adı). Dosyanın geri kalanı denetlenir.
TUM_PROJELER_IZINLI_FONKSIYON: frozenset[tuple[str, str]] = frozenset(
    [
        # Kişi geneli token iptali: iptal kişiye özgüdür, projeye değil.
        ("tp_core/auth/aiprobe.py", "eski_oturumlari_iptal_et"),
    ]
)
JOB_IZINLI = ("tp_core/workflow/jobs.py", "tp_core/worker/")
_JOB_RE = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+job\b(?![.(])")
_JOB_SUZGEC = re.compile(r"\b(?:tur|yuk|idempotency_key)\b")
ENV_IZINLI = ("tp_core/home_config/", "tp_core/proje/ayar.py")
THREAD_BAGLAM = ("baglamla", "proje_icinde", "copy_context")
_ENV_CAGRI = re.compile(r"(environ|getenv|(^|[._])_*(env|ortam)[a-z_]*(\.get)?$)", re.IGNORECASE)
# `tp_core.proje.ayar` (ENV_IZINLI) proje kapsamlı çözücüdür:
# `ayar.ortamda_kaldirildi_mi(ad, pid=p)` gibi erişimcileri ham env okuması değildir (ad `ortam…` diye başlasa da).
_AYAR_MODULU = re.compile(r"^_*ayar\.")

# Şerit sahipliği (§7): yol öneki → şerit. En uzun önek kazanır.
SAHIPLIK: dict[str, int] = {
    "tp_core/models/": 1,
    "tp_core/audit/": 1,
    "tp_core/workflow/": 1,
    "tp_core/worker/": 1,
    "tp_core/events/": 1,
    "tp_core/db/": 1,
    "tp_core/home_config/": 2,
    "tp_core/config.py": 2,
    "tp_core/gateway/config.py": 2,
    "tp_core/auth/": 2,
    "tp_core/api/": 2,
    "tp_core/mcp_server/": 2,
    "tp_core/integrations/": 3,
    "tp_core/features/ci/clients.py": 3,
    "tp_core/gateway/": 4,
    "tp_core/seed.py": 4,
    **{
        f"tp_core/features/{d}/": 4
        for d in [
            "requirements",
            "cases",
            "tasarim_modeli",
            "karar_tablosu",
            "metamorfik",
            "oracle",
            "testveri",
            "otomasyon",
            "assistant",
            "publish",
        ]
    },
    **{
        f"tp_core/features/{d}/": 5
        for d in [
            "codegen",
            "ci",
            "triage",
            "repair",
            "bugs",
            "hata_kosusu",
            "control_tower",
            "demo",
            "agent_probe",
        ]
    },
}


def serit(yol: str) -> int | None:
    adaylar = [o for o in SAHIPLIK if yol == o or (o.endswith("/") and yol.startswith(o))]
    return SAHIPLIK[max(adaylar, key=len)] if adaylar else None


def _tablo_re(tablolar: frozenset[str]) -> re.Pattern[str]:
    adlar = "|".join(sorted(map(re.escape, tablolar), key=len, reverse=True))
    return re.compile(rf"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+\"?(?:{adlar})\b(?![.(])")


def _imza(metin: str, n: int = 70) -> str:
    return " ".join(metin.split())[:n].rstrip().replace("#", "_")


def _ad(dugum: ast.AST) -> str:
    if isinstance(dugum, ast.Name):
        return dugum.id
    if isinstance(dugum, ast.Attribute):
        return f"{_ad(dugum.value)}.{dugum.attr}"
    if isinstance(dugum, ast.Call):
        return _ad(dugum.func)
    return ""


def _docstring_mu(dugum: ast.AST, ebeveyn: dict[ast.AST, ast.AST]) -> bool:
    return isinstance(ebeveyn.get(dugum), ast.Expr)


def _metinler(agac: ast.AST, ebeveyn: dict[ast.AST, ast.AST]) -> Iterator[str]:
    """Kod içindeki dize ifadeleri (f-string parçaları `{}` ile); ifade-deyimi dizeleri atlanır."""
    for d in ast.walk(agac):
        if isinstance(d, ast.JoinedStr):
            if not _docstring_mu(d, ebeveyn):
                yield "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in d.values)
        elif isinstance(d, ast.Constant) and isinstance(d.value, str):
            if isinstance(ebeveyn.get(d), ast.JoinedStr) or _docstring_mu(d, ebeveyn):
                continue
            yield d.value


def _kapsayan_fonksiyon(
    d: ast.AST, ebeveyn: dict[ast.AST, ast.AST]
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    while d in ebeveyn:
        d = ebeveyn[d]
        if isinstance(d, ast.FunctionDef | ast.AsyncFunctionDef):
            return d
    return None


def _tum_projeler_izinli(yol: str, f: ast.FunctionDef | ast.AsyncFunctionDef | None) -> bool:
    if yol.startswith(TUM_PROJELER_IZINLI):
        return True
    return f is not None and (yol, f.name) in TUM_PROJELER_IZINLI_FONKSIYON


def ihlaller() -> list[str]:
    """Bugünkü tüm ihlal anahtarları (`yol:kural:imza`), kaynak sırasıyla."""
    tablo_re = _tablo_re(PLAN_KAPSAMLI | kapsamli_tablolar())
    sonuc: list[str] = []
    for dosya in sorted(SRC.rglob("*.py")):
        yol = dosya.relative_to(SRC).as_posix()
        kaynak = dosya.read_text(encoding="utf-8")
        agac = ast.parse(kaynak)
        ebeveyn = {c: p for p in ast.walk(agac) for c in ast.iter_child_nodes(p)}

        for metin in _metinler(agac, ebeveyn):
            if tablo_re.search(metin) and "project_id" not in metin:
                sonuc.append(f"{yol}:sql:{_imza(metin)}")
            if (
                not yol.startswith(JOB_IZINLI)
                and _JOB_RE.search(metin)
                and _JOB_SUZGEC.search(metin.partition("WHERE")[2])
                and "project_id" not in metin
            ):
                sonuc.append(f"{yol}:job:{_imza(metin)}")

        for d in ast.walk(agac):
            if isinstance(d, ast.Call):
                ad = _ad(d.func)
                # tum_projeler
                if any(k.arg == "tum_projeler" for k in d.keywords):
                    f = _kapsayan_fonksiyon(d, ebeveyn)
                    if not _tum_projeler_izinli(yol, f):
                        sonuc.append(f"{yol}:tum_projeler:{f.name if f else '<modul>'}")
                # thread
                if ad.split(".")[-1] in ("Thread", "ThreadPoolExecutor"):
                    f = _kapsayan_fonksiyon(d, ebeveyn)
                    govde = ast.get_source_segment(kaynak, f) if f else kaynak
                    if not any(t in (govde or "") for t in THREAD_BAGLAM):
                        sonuc.append(
                            f"{yol}:thread:{f.name if f else '<modul>'}:{ad.split('.')[-1]}"
                        )
                # env (çağrı)
                if (
                    not yol.startswith(ENV_IZINLI)
                    and d.args
                    and isinstance(d.args[0], ast.Constant)
                    and d.args[0].value in PROJE_ANAHTARLARI
                    and _ENV_CAGRI.search(ad)
                    and not _AYAR_MODULU.match(ad)
                ):
                    sonuc.append(f"{yol}:env:{d.args[0].value}:{ad}")
            elif isinstance(d, ast.Name | ast.Attribute):
                if (d.id if isinstance(d, ast.Name) else d.attr) == "TUM_PROJELER":
                    f = _kapsayan_fonksiyon(d, ebeveyn)
                    if not _tum_projeler_izinli(yol, f):
                        sonuc.append(f"{yol}:tum_projeler:{f.name if f else '<modul>'}")
            elif isinstance(d, ast.Subscript) and not yol.startswith(ENV_IZINLI):
                # os.environ["X"]
                if (
                    _ad(d.value).endswith("environ")
                    and isinstance(d.slice, ast.Constant)
                    and d.slice.value in PROJE_ANAHTARLARI
                    and not isinstance(ebeveyn.get(d), ast.Assign | ast.Delete)
                ):
                    sonuc.append(f"{yol}:env:{d.slice.value}:{_ad(d.value)}[]")
            elif isinstance(d, ast.Compare) and not yol.startswith(ENV_IZINLI):
                # "X" in os.environ
                if (
                    isinstance(d.left, ast.Constant)
                    and d.left.value in PROJE_ANAHTARLARI
                    and any(_ad(c).endswith("environ") for c in d.comparators)
                ):
                    sonuc.append(f"{yol}:env:{d.left.value}:in")
    return sonuc


def _taban(n: int) -> Counter[str]:
    dosya = ISTISNA_DIZINI / f"serit{n}.txt"
    sayac: Counter[str] = Counter()
    for satir in dosya.read_text(encoding="utf-8").splitlines():
        anahtar = satir.split("  # ", 1)[0].rstrip()
        if anahtar and not anahtar.startswith("#"):
            sayac[anahtar] += 1
    return sayac


@pytest.fixture(scope="module")
def guncel() -> Counter[str]:
    return Counter(ihlaller())


def test_sahipsiz_ihlal_yok(guncel: Counter[str]) -> None:
    sahipsiz = sorted(k for k in guncel if serit(k.split(":", 1)[0]) is None)
    assert sahipsiz == [], "şerit sahibi olmayan dosyada ihlal (SAHIPLIK'e bakın)"


@pytest.mark.parametrize("n", SERITLER)
def test_serit_tabani(n: int, guncel: Counter[str]) -> None:
    taban = _taban(n)
    yanlis_serit = sorted(k for k in taban if serit(k.split(":", 1)[0]) != n)
    assert yanlis_serit == [], f"serit{n}.txt başka şeridin dosyasını içeriyor"
    benim = Counter({k: v for k, v in guncel.items() if serit(k.split(":", 1)[0]) == n})
    yeni = sorted((benim - taban).elements())
    giderilen = sorted((taban - benim).elements())
    assert yeni == [], f"yeni proje kapsamı ihlali (serit{n}): düzeltin, tabana eklemeyin"
    assert giderilen == [], f"giderilmiş ihlal: proje_istisna/serit{n}.txt'den silin"


# ------------------------------------------------------------- denetleyicinin kendi testleri


def _tara(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, yol: str, kod: str) -> list[str]:
    dosya = tmp_path / yol
    dosya.parent.mkdir(parents=True, exist_ok=True)
    dosya.write_text(kod, encoding="utf-8")
    monkeypatch.setattr(f"{__name__}.SRC", tmp_path)
    return ihlaller()


def test_denetleyici_sql(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kod = (
        "from sqlalchemy import text\n"
        "def f(t):\n"
        '    """FROM requirement açıklaması (docstring sayılmaz)."""\n'
        '    a = text("SELECT id FROM requirement WHERE id = :id")\n'
        '    b = text("SELECT id FROM requirement WHERE project_id = :pid")\n'
        '    c = f"UPDATE run SET durum = :d WHERE id = {t}"\n'
        '    d = text("SELECT 1 FROM app_user")\n'
        '    e = "UPDATE requirement_review_ek SET x = 1"\n'
    )
    sonuc = _tara(tmp_path, monkeypatch, "tp_core/features/demo/x.py", kod)
    assert sorted(sonuc) == sorted(
        [
            "tp_core/features/demo/x.py:sql:SELECT id FROM requirement WHERE id = :id",
            "tp_core/features/demo/x.py:sql:UPDATE run SET durum = :d WHERE id = {}",
            "tp_core/features/demo/x.py:sql:UPDATE requirement_review_ek SET x = 1",
        ]
    )


def test_denetleyici_thread_env_tum_projeler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kod = (
        "import os, threading\n"
        "from tp_core.proje import baglamla\n"
        "def kotu():\n"
        "    threading.Thread(target=print).start()\n"
        "def iyi():\n"
        "    threading.Thread(target=baglamla(print)).start()\n"
        "def env():\n"
        '    os.environ.get("JIRA_PROJECT")\n'
        '    os.getenv("TP_DATABASE_URL")\n'
        '    os.environ["TP_FORGE"]\n'
        '    _ortam_float("TP_CI_GITHUB_TIMEOUT_S", 1.0)\n'
        '    "GITHUB_REPO" in os.environ\n'
        '    _ayar.ortamda_kaldirildi_mi("TP_FORGE", pid="p")\n'
        "def kacis(s):\n"
        "    s.execute(1, execution_options={}).execution_options(tum_projeler=True)\n"
    )
    yol = "tp_core/features/demo/y.py"
    assert sorted(_tara(tmp_path, monkeypatch, yol, kod)) == sorted(
        [
            f"{yol}:thread:kotu:Thread",
            f"{yol}:env:JIRA_PROJECT:os.environ.get",
            f"{yol}:env:TP_FORGE:os.environ[]",
            f"{yol}:env:TP_CI_GITHUB_TIMEOUT_S:_ortam_float",
            f"{yol}:env:GITHUB_REPO:in",
            f"{yol}:tum_projeler:kacis",
        ]
    )


def test_denetleyici_izinli_moduller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kod = (
        "import os\n"
        "def f(s):\n"
        '    os.environ.get("JIRA_PROJECT")\n'
        "    s.execution_options(tum_projeler=True)\n"
    )
    assert _tara(tmp_path, monkeypatch, "tp_core/proje/ayar.py", kod) == []


def test_denetleyici_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kod = (
        "from sqlalchemy import text\n"
        "def f():\n"
        '    a = text("SELECT durum FROM job WHERE id = :j")\n'
        "    b = text(\"SELECT count(*) FROM job WHERE tur = :t AND yuk->>'x' = :d\")\n"
        '    c = text("SELECT 1 FROM job WHERE tur = :t AND project_id = :pid")\n'
        '    d = text("SELECT 1 FROM job WHERE idempotency_key = :k")\n'
        '    e = text("UPDATE job SET yuk = :y WHERE id = :i")\n'
    )
    yol = "tp_core/features/demo/j.py"
    assert sorted(_tara(tmp_path, monkeypatch, yol, kod)) == sorted(
        [
            f"{yol}:job:SELECT count(*) FROM job WHERE tur = :t AND yuk->>'x' = :d",
            f"{yol}:job:SELECT 1 FROM job WHERE idempotency_key = :k",
        ]
    )
    (tmp_path / yol).unlink()
    assert _tara(tmp_path, monkeypatch, "tp_core/workflow/jobs.py", kod) == []


def test_denetleyici_fonksiyon_muafiyeti(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kod = (
        "def eski_oturumlari_iptal_et(s):\n"
        "    s.execution_options(tum_projeler=True)\n"
        "def baska(s):\n"
        "    s.execution_options(tum_projeler=True)\n"
    )
    yol = "tp_core/auth/aiprobe.py"
    assert _tara(tmp_path, monkeypatch, yol, kod) == [f"{yol}:tum_projeler:baska"]


def test_sahiplik() -> None:
    assert serit("tp_core/features/ci/clients.py") == 3
    assert serit("tp_core/features/ci/service.py") == 5
    assert serit("tp_core/gateway/config.py") == 2
    assert serit("tp_core/gateway/gateway.py") == 4
    assert serit("tp_core/models/delivery.py") == 1
    assert serit("tp_core/ports.py") is None
