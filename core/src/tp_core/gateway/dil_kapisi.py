"""Test dili kapısı (014 TASARIM §2.3) — `rules/diller.yaml`.

(platform, dil) çiftinin seçilebilir olup olmadığının TEK kaynağı. Değerlendirmeden geçmemiş çift
`yakinda`dır: TP üretmez (`POST /code/generate` 422), portal/Home "Yakında" gösterir. `acik` için
kanıt zorunludur:

- `kanit: devralindi` — yalnız 014 öncesi tam hat çiftleri (`DEVRALINABILIR`; kullanıcı kararı 3b);
- `kanit: {eval, tarih, kabul}` — `eval`: canlı değerlendirme raporu (`rules/`'a göre); rapor o
  çiftin ajan paketinin GÜNCEL prompt sürümüyle, setteki o çifte ait TÜM vakaları geçmiş olmalı
  (`kanit_sorunlari`); `kabul`: kabul koşusu (derleme + koşu + kırarak doğrulama; müşteri CI
  hattında GitHub run bağlantısı).

Bu desen `evaluations.yaml`'daki "ajanlar `waived` yazamaz" kuralıyla aynıdır: kanıtı yalnız
`eval_live --dil <d> --update-status` (`eval_kaniti_yaz`) ve kabul betiği (`--kabul`,
`kabul_yaz`) yazar; ikisi de geçerliyse durum `acik` olur.

Çalışma zamanı (`durumlar`, `kullanilabilir_mi`) yalnız yapısal doğrulama yapar (rapor dosyası
imajda olmayabilir); derin kanıt denetimi `--check` (CI/birleştirme kapısı) içindir.

    cd core && uv run python -m tp_core.gateway.dil_kapisi                 # durum tablosu
    cd core && uv run python -m tp_core.gateway.dil_kapisi --check         # kapı (çıkış 1)
    cd core && uv run python -m tp_core.gateway.dil_kapisi --check --dil python
    cd core && uv run python -m tp_core.gateway.dil_kapisi --json          # Home kopyası
    cd core && uv run python -m tp_core.gateway.dil_kapisi --kabul web/python --ref <run>
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tp_core.gateway.errors import GatewayConfigError

DILLER_FILE = "diller.yaml"
PLATFORMLAR = ("web", "android", "ios", "windows")
DILLER = ("ts", "java", "python", "csharp", "kotlin", "swift")
DIL_ADLARI = {
    "ts": "TypeScript",
    "java": "Java",
    "python": "Python",
    "csharp": "C#",
    "kotlin": "Kotlin",
    "swift": "Swift",
}
HATLAR = ("tam", "musteri_ci", "dogrulanmamis")
DURUMLAR = ("acik", "yakinda")
DEVRALINDI = "devralindi"
# Kullanıcı kararı 3b: 014 öncesi tam hat çiftleri değerlendirmesiz açık kalır. Liste kod sabitidir;
# yeni bir çifti `devralindi` ile açmak kapıyı geçmez.
DEVRALINABILIR = frozenset(
    {("web", "ts"), ("web", "java"), ("android", "java"), ("ios", "java"), ("windows", "java")}
)
YAKINDA_NEDENI = "Değerlendirme sürüyor"
_KANIT_ALANLARI = ("eval", "tarih", "kabul")

# Ş0 sözleşmesi (TASARIM §1.3/§2.1) gelene kadar stub matris: (platform, dil) → hat. Ş0'ın
# `codegen/platform.py` `CATILAR` tablosu varsa o kullanılır (`matris`).
_STUB_MATRIS: Mapping[tuple[str, str], str] = {
    ("web", "ts"): "tam",
    ("web", "java"): "tam",
    ("web", "python"): "tam",
    ("web", "csharp"): "tam",
    ("android", "java"): "tam",
    ("android", "python"): "tam",
    ("android", "kotlin"): "musteri_ci",
    ("ios", "java"): "tam",
    ("ios", "python"): "tam",
    ("ios", "swift"): "musteri_ci",
    ("windows", "java"): "tam",
    ("windows", "python"): "tam",
    ("windows", "csharp"): "tam",
}


def matris() -> tuple[dict[tuple[str, str], str], str]:
    """(platform, dil) → hat ve kaynağı (`platform.CATILAR` ya da `stub`)."""
    try:
        from tp_core.features.codegen.platform import CATILAR  # type: ignore[attr-defined]
    except (ImportError, AttributeError):
        return dict(_STUB_MATRIS), "stub"
    return {(str(p), str(d)): str(c.hat) for (p, d), c in CATILAR.items()}, "platform.CATILAR"


def ajan_paketi(platform: str) -> str:
    """Çiftin doğrulama ajanı paketi: web → `verify-and-map`, uygulama → `verify-and-map-app`."""
    return "verify-and-map" if platform == "web" else "verify-and-map-app"


def ajan_dil_girdisi(dil: str, tablo_dili: str) -> str:
    """Doğrulama ajanı girdisindeki dil satırı (verify-and-map v4 / verify-and-map-app v2).

    Ş0 sözleşmesi: `mapping_messages(..., dil=, tablo_dili=)` ve `app_mapping_messages(...)` bu
    satırı sembol tablosu bloğundan sonra ekler (değerlendirme seti aynı satırı kullanır)."""
    for d in (dil, tablo_dili):
        if d not in DIL_ADLARI:
            raise GatewayConfigError(f"bilinmeyen dil: {d!r}")
    return (
        f"Hedef test dili (language): {dil} ({DIL_ADLARI[dil]}). Sembol tablosunun dili: "
        f"{tablo_dili} ({DIL_ADLARI[tablo_dili]}). Eşlemede sınıf ve metot adlarını tabloda "
        "yazıldığı gibi döndür; hedef dilin ad dönüşümünü şablon yapar."
    )


@dataclass(frozen=True)
class DilDurumu:
    platform: str
    dil: str
    hat: str
    durum: str  # acik | yakinda
    kanit: str | Mapping[str, Any] | None = None

    @property
    def anahtar(self) -> str:
        return f"{self.platform}/{self.dil}"

    @property
    def kullanilabilir(self) -> bool:
        return self.durum == "acik"

    @property
    def neden(self) -> str | None:
        return None if self.kullanilabilir else YAKINDA_NEDENI

    @property
    def devralindi(self) -> bool:
        return self.kanit == DEVRALINDI


def _cift(anahtar: Any, where: str) -> tuple[str, str]:
    parca = str(anahtar).split("/")
    if len(parca) != 2 or parca[0] not in PLATFORMLAR or parca[1] not in DILLER:
        raise GatewayConfigError(
            f"{where}: anahtar '<platform>/<dil>' olmalı ({PLATFORMLAR} × {DILLER}), {anahtar!r}"
        )
    return parca[0], parca[1]


def _tarih_mi(value: Any) -> bool:
    if isinstance(value, dt.date):
        return True
    try:
        dt.date.fromisoformat(str(value))
    except ValueError:
        return False
    return True


def _dogrula(anahtar: Any, kayit: Any, path: Path) -> DilDurumu:
    where = f"{path}: {anahtar}"
    platform, dil = _cift(anahtar, str(path))
    if not isinstance(kayit, Mapping):
        raise GatewayConfigError(f"{where}: kayıt bir eşleme olmalı")
    bilinmeyen = sorted(set(kayit) - {"hat", "durum", "kanit", "not"})
    if bilinmeyen:
        raise GatewayConfigError(f"{where}: bilinmeyen alan(lar) {bilinmeyen}")
    hat, durum, kanit = kayit.get("hat"), kayit.get("durum"), kayit.get("kanit")
    if hat not in HATLAR:
        raise GatewayConfigError(f"{where}: 'hat' {HATLAR} içinden olmalı, {hat!r} geldi")
    if durum not in DURUMLAR:
        raise GatewayConfigError(f"{where}: 'durum' {DURUMLAR} içinden olmalı, {durum!r} geldi")
    if kanit == DEVRALINDI:
        if (platform, dil) not in DEVRALINABILIR:
            raise GatewayConfigError(
                f"{where}: 'devralindi' yalnız 014 öncesi tam hat çiftleri için geçerli "
                f"({', '.join(sorted(f'{p}/{d}' for p, d in DEVRALINABILIR))})"
            )
        if durum != "acik":
            raise GatewayConfigError(f"{where}: 'devralindi' kanıtı yalnız 'acik' durumda olur")
    elif kanit is not None:
        if not isinstance(kanit, Mapping):
            raise GatewayConfigError(f"{where}: 'kanit' 'devralindi' ya da eşleme olmalı")
        fazla = sorted(set(kanit) - set(_KANIT_ALANLARI))
        if fazla:
            raise GatewayConfigError(f"{where}: kanıtta bilinmeyen alan(lar) {fazla}")
        if not any(kanit.get(a) for a in _KANIT_ALANLARI):
            raise GatewayConfigError(f"{where}: kanıt boş")
        if kanit.get("eval") and not _tarih_mi(kanit.get("tarih")):
            raise GatewayConfigError(f"{where}: 'eval' kanıtı 'tarih' (YYYY-MM-DD) taşımalı")
    if durum == "acik" and kanit != DEVRALINDI:
        eksik = [a for a in _KANIT_ALANLARI if not (kanit or {}).get(a)]
        if eksik:
            raise GatewayConfigError(
                f"{where}: 'acik' durum kanıtsız olamaz (eksik: {', '.join(eksik)}); "
                "değerlendirilmemiş dil 'yakinda' kalır"
            )
    return DilDurumu(platform, dil, str(hat), str(durum), kanit)


def _oku(rules_dir: Path) -> tuple[Path, dict[str, Any]]:
    path = rules_dir / DILLER_FILE
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise GatewayConfigError(f"{path} bulunamadı (dil kapısı)") from None
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise GatewayConfigError(f"{path}: 'version: 1' zorunlu")
    if not isinstance(data.get("ciftler"), Mapping) or not data["ciftler"]:
        raise GatewayConfigError(f"{path}: 'ciftler' eşlemesi zorunlu")
    return path, dict(data)


def durumlar(rules_dir: Path) -> dict[tuple[str, str], DilDurumu]:
    """Yapısal olarak doğrulanmış çift durumları (dosya sırası korunur)."""
    path, data = _oku(rules_dir)
    out: dict[tuple[str, str], DilDurumu] = {}
    for anahtar, kayit in data["ciftler"].items():
        st = _dogrula(anahtar, kayit, path)
        out[(st.platform, st.dil)] = st
    return out


def durum(rules_dir: Path, platform: str, dil: str) -> DilDurumu | None:
    return durumlar(rules_dir).get((platform, dil))


def kullanilabilir_mi(rules_dir: Path, platform: str, dil: str) -> bool:
    """Çift seçilebilir mi? Kayıt yoksa ya da dosya okunamazsa HAYIR (kapı kapalı başlar)."""
    try:
        st = durum(rules_dir, platform, dil)
    except GatewayConfigError:
        return False
    return st is not None and st.kullanilabilir


def home_ozeti(rules_dir: Path) -> dict[str, Any]:
    """Home türetilmiş kopyası (`settings/product_info/tp_languages.json`, Ş6).

    `{"version": 1, "platformlar": {"web": {"ts": {"durum": "acik", "hat": "tam"}, …}, …}}`;
    Home `yakinda` → `availability: soon` gösterir. Kanıt ayrıntısı taşınmaz."""
    platformlar: dict[str, dict[str, dict[str, str]]] = {}
    for st in durumlar(rules_dir).values():
        platformlar.setdefault(st.platform, {})[st.dil] = {"durum": st.durum, "hat": st.hat}
    return {"version": 1, "kaynak": f"rules/{DILLER_FILE}", "platformlar": platformlar}


# ------------------------------------------------------------------ derin kanıt denetimi


def cift_vakalari(rules_dir: Path, platform: str, dil: str) -> list[str]:
    """Ajan paketinin değerlendirme setinde bu çifte ait vaka kimlikleri (`dil`, `platform`)."""
    from tp_core.gateway.eval_set import set_path

    path = set_path(rules_dir, ajan_paketi(platform))
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        str(c["id"])
        for c in data.get("cases") or []
        if c.get("dil") == dil and c.get("platform") == platform
    ]


def kanit_sorunlari(rules_dir: Path, st: DilDurumu) -> list[str]:
    """Çiftin değerlendirme kanıtının sorunları (boş liste = geçerli ya da kanıt beklenmiyor).

    Rapor: dosya var, `mode: live`, paket = çiftin ajan paketi, sürüm = GÜNCEL prompt sürümü
    (prompt yükselince kanıt bayatlar), set de aynı sürümde, setteki TÜM çift vakaları raporda
    `ok`; koşu tamamlanmış."""
    from tp_core.gateway.evaluation import prompt_versions

    if st.devralindi or not isinstance(st.kanit, Mapping):
        return []
    rel = str(st.kanit.get("eval"))
    path = rules_dir / rel
    if not path.is_file():
        return [f"{st.anahtar}: kanıt raporu yok: {rel}"]
    try:
        rapor = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{st.anahtar}: kanıt raporu okunamadı ({rel}): {exc}"]
    paket = ajan_paketi(st.platform)
    sorun: list[str] = []
    if rapor.get("bundle") != paket:
        sorun.append(f"{st.anahtar}: rapor paketi {rapor.get('bundle')!r}, beklenen {paket!r}")
    surum = prompt_versions(rules_dir).get(paket)
    if rapor.get("version") != surum:
        sorun.append(
            f"{st.anahtar}: kanıt bayat — rapor v{rapor.get('version')}, {paket} prompt v{surum}"
        )
    if rapor.get("mode") != "live":
        sorun.append(f"{st.anahtar}: rapor canlı değil (mode {rapor.get('mode')!r})")
    if rapor.get("tamamlandi") is False:
        sorun.append(f"{st.anahtar}: koşu tamamlanmamış")
    beklenen = cift_vakalari(rules_dir, st.platform, st.dil)
    if not beklenen:
        sorun.append(f"{st.anahtar}: {paket} setinde bu çiftin vakası yok")
    sonuc = {str(c.get("id")): bool(c.get("ok")) for c in rapor.get("cases") or []}
    eksik = [v for v in beklenen if v not in sonuc]
    kalan = [v for v in beklenen if v in sonuc and not sonuc[v]]
    if eksik:
        sorun.append(f"{st.anahtar}: raporda olmayan vaka(lar): {', '.join(eksik)}")
    if kalan:
        sorun.append(f"{st.anahtar}: geçmeyen vaka(lar): {', '.join(kalan)}")
    return sorun


def denetle(rules_dir: Path, dil: str | None = None) -> list[str]:
    """Kapı sorunları: şema, matris eşitliği (çift kümesi + hat), `acik` kanıtların derin
    denetimi. `dil` verilirse yalnız o dilin çiftleri (matris eşitliği yine tümüyle)."""
    try:
        sts = durumlar(rules_dir)
    except GatewayConfigError as exc:
        return [str(exc)]
    sorun: list[str] = []
    tablo, kaynak = matris()
    for cift in sorted(set(tablo) - set(sts)):
        sorun.append(f"{cift[0]}/{cift[1]}: {kaynak} çifti {DILLER_FILE}'da yok")
    for cift in sorted(set(sts) - set(tablo)):
        sorun.append(f"{cift[0]}/{cift[1]}: {DILLER_FILE} çifti {kaynak}'da yok")
    for cift, st in sts.items():
        if cift in tablo and tablo[cift] != st.hat:
            sorun.append(f"{st.anahtar}: hat {st.hat!r}, {kaynak} {tablo[cift]!r}")
        if dil is not None and st.dil != dil:
            continue
        if st.durum == "acik" or isinstance(st.kanit, Mapping):
            sorun += kanit_sorunlari(rules_dir, st)
    return sorun


# ------------------------------------------------------------------ yazım (kanıt)


def _yaz(rules_dir: Path, ciftler: Mapping[str, Mapping[str, Any]]) -> Path:
    """Başlık yorumlarını koruyarak `ciftler`'i yazar (çift başına tek satır akış eşlemesi)."""
    path = rules_dir / DILLER_FILE
    metin = path.read_text(encoding="utf-8")
    baslik: list[str] = []
    for satir in metin.splitlines():
        if satir.startswith("version:"):
            break
        baslik.append(satir)
    satirlar = [*baslik, "version: 1", "ciftler:"]
    for anahtar, kayit in ciftler.items():
        sade = {k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in kayit.items()}
        if isinstance(sade.get("kanit"), Mapping):
            sade["kanit"] = {
                k: (v.isoformat() if isinstance(v, dt.date) else v)
                for k, v in sade["kanit"].items()
            }
        akis = yaml.safe_dump(
            sade, default_flow_style=True, sort_keys=False, allow_unicode=True, width=10**6
        ).strip()
        satirlar.append(f"  {anahtar}: {akis}")
    path.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    durumlar(rules_dir)  # yazılanı yeniden doğrula
    return path


def _guncelle(
    rules_dir: Path, platform: str, dil: str, kanit_ek: Mapping[str, Any], out: Any = print
) -> DilDurumu:
    _, data = _oku(rules_dir)
    ciftler = {str(k): dict(v) for k, v in data["ciftler"].items()}
    anahtar = f"{platform}/{dil}"
    if anahtar not in ciftler:
        raise GatewayConfigError(f"{DILLER_FILE}: bilinmeyen çift {anahtar}")
    kayit = ciftler[anahtar]
    if kayit.get("kanit") == DEVRALINDI:
        raise GatewayConfigError(f"{anahtar}: devralınmış çiftin kanıtı yazılmaz")
    kanit = dict(kayit.get("kanit") or {})
    kanit.update(kanit_ek)
    kayit["kanit"] = {a: kanit[a] for a in _KANIT_ALANLARI if kanit.get(a)}
    aday = DilDurumu(platform, dil, str(kayit["hat"]), "acik", kayit["kanit"])
    tam = all(kayit["kanit"].get(a) for a in _KANIT_ALANLARI)
    sorun = kanit_sorunlari(rules_dir, aday) if kayit["kanit"].get("eval") else ["eval yok"]
    kayit["durum"] = "acik" if tam and not sorun else "yakinda"
    ciftler[anahtar] = {"hat": kayit["hat"], "durum": kayit["durum"], "kanit": kayit["kanit"]}
    _yaz(rules_dir, ciftler)
    if kayit["durum"] != "acik":
        neden = "kabul bekliyor" if not kayit["kanit"].get("kabul") else "; ".join(sorun)
        out(f"  {anahtar}: kanıt yazıldı, durum yakinda ({neden})")
    else:
        out(f"  {anahtar}: kanıt tamam → acik")
    return durumlar(rules_dir)[(platform, dil)]


def eval_kaniti_yaz(
    rules_dir: Path,
    platform: str,
    dil: str,
    rapor: Path | str,
    *,
    tarih: dt.date | None = None,
    out: Any = print,
) -> DilDurumu:
    """`eval_live --dil <d> --update-status`: çiftin vakalarının hepsi geçtiyse çağrılır.

    Rapor derin denetimden geçmezse kanıt YAZILMAZ (hata). Kabul de varsa durum `acik` olur."""
    rel = str(Path(rapor).relative_to(rules_dir)) if Path(rapor).is_absolute() else str(rapor)
    aday = DilDurumu(platform, dil, "", "acik", {"eval": rel, "tarih": "2000-01-01"})
    sorun = kanit_sorunlari(rules_dir, aday)
    if sorun:
        raise GatewayConfigError("değerlendirme kanıtı geçersiz: " + "; ".join(sorun))
    gun = (tarih or dt.date.today()).isoformat()
    return _guncelle(rules_dir, platform, dil, {"eval": rel, "tarih": gun}, out)


def kabul_yaz(rules_dir: Path, platform: str, dil: str, ref: str, *, out: Any = print) -> DilDurumu:
    """Kabul betiği: derleme + koşu + kırarak doğrulama (müşteri CI: yeşil GitHub run) kimliği."""
    if not ref.strip():
        raise GatewayConfigError("kabul kimliği boş olamaz")
    return _guncelle(rules_dir, platform, dil, {"kabul": ref.strip()}, out)


def dil_ciftleri(rules_dir: Path, dil: str) -> list[DilDurumu]:
    return [st for st in durumlar(rules_dir).values() if st.dil == dil]


def paketler(sts: Iterable[DilDurumu]) -> list[str]:
    return sorted({ajan_paketi(st.platform) for st in sts})


def main(argv: list[str] | None = None) -> int:
    from tp_core.gateway.config import find_rules_dir

    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--rules-dir", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="kapı: sorun varsa çıkış 1")
    parser.add_argument("--dil", choices=DILLER, default=None, help="yalnız bu dilin çiftleri")
    parser.add_argument("--json", action="store_true", help="Home kopyası (tp_languages.json)")
    parser.add_argument("--kabul", default=None, metavar="P/D", help="kabul kanıtı yaz: web/python")
    parser.add_argument("--ref", default=None, help="--kabul ile: koşu kimliği / run bağlantısı")
    args = parser.parse_args(argv)
    rules_dir = args.rules_dir or find_rules_dir()
    try:
        if args.kabul:
            if not args.ref:
                parser.error("--kabul için --ref zorunlu")
            platform, dil = _cift(args.kabul, "--kabul")
            kabul_yaz(rules_dir, platform, dil, args.ref)
            return 0
        if args.json:
            print(json.dumps(home_ozeti(rules_dir), ensure_ascii=False, indent=2))
            return 0
        sts = durumlar(rules_dir)
    except GatewayConfigError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2
    _, kaynak = matris()
    for st in sts.values():
        if args.dil and st.dil != args.dil:
            continue
        kanit = st.kanit if not isinstance(st.kanit, Mapping) else json.dumps(st.kanit, default=str)
        print(f"{st.anahtar}\t{st.hat}\t{st.durum}\t{kanit or '-'}")
    if args.check:
        sorun = denetle(rules_dir, args.dil)
        if sorun:
            print(f"Dil kapısı ({kaynak}):", file=sys.stderr)
            for s in sorun:
                print(f"  {s}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
