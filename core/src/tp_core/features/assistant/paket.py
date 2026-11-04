"""Ürün bilgi paketi üretici (AI-ASISTAN-PLANI §5.1).

Asistanın `product_search`/`product_read` araçlarının okuduğu, Testing Probe'un kendi kaynak ve
belgelerinden seçilmiş salt okunur kopya. İmaja kopyalanamaz (core derleme bağlamı `./core`), bu
yüzden core imajında, repo salt okunur bağlanarak üretilir (`scripts/asistan-bilgi-paketi.sh`):

    python -m tp_core.features.assistant.paket --kaynak /repo --cikti /out --commit <sha>

Çıktı düzeni (`--cikti`, core-worker'a `/opt/tp-bilgi` olarak salt okunur bağlanır):

    MANIFEST.json            {surum, commit, uretim, dizin, dosyalar: {yol: {sha256, boyut, satir}}}
    surumler/<kimlik>/<yol>  dosyaların kopyası (`dizin` geçerli sürümü gösterir)

Geçiş atomiktir: yeni sürüm ayrı dizine yazılır, MANIFEST.json yeniden adlandırmayla (rename)
değişir; okuyan worker yarım paket görmez. MANIFEST'in önceki işaret ettiği sürüm bir üretim daha
tutulur (o anda okuyan çağrı için), daha eskileri silinir.

Sır taraması üretimin parçasıdır: seçilen her dosya `find_secret_patterns` desenleriyle ve `.env`
değerleriyle (≥ 8 karakter; `true/false`, sayı ve bilinen demo parolası hariç) taranır; bulgu
varsa paket YAZILMAZ ve çıkış kodu 2'dir. Rapor yalnız `yol:satır: tür` yazar, değeri asla.

Çıkış kodları: 0 başarı, 1 kullanım/girdi hatası, 2 sır bulgusu.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from tp_core.gateway.factory import known_secret_values
from tp_core.gateway.masking import SECRET_VALUE_MIN_LEN, find_secret_patterns

MANIFEST_ADI = "MANIFEST.json"
SURUMLER_DIZINI = "surumler"
MANIFEST_SURUMU = 1
MAX_DOSYA_BAYT = 1_000_000  # daha büyük kaynak dosyası pakete alınmaz (uyarı)

IZIN_LISTESI: tuple[str, ...] = (
    "review-portal/src/**/*.{ts,tsx,css}",
    "core/src/tp_core/**/*.py",
    "docs/{ONBOARDING,DEMO-AKISI,CANLI-DEMO-SENARYOSU,CLAUDE-CODE-KANALI,MIMARI-SOZLESME,GERCEK-SISTEMLER}.md",
    "README.md",
    "rules/assistant/*.yaml",
)
HARIC_LISTESI: tuple[str, ...] = (
    "**/test/**",
    "**/tests/**",
    "**/*.test.*",
    "review-portal/src/api/mock/**",
    "**/fixtures/**",
    ".env*",
    "**/.env*",
    "docs/DAHILI-*",
    "docs/sunumlar/**",
    "**/*.docx",
    "**/node_modules/**",
    "**/dist/**",
    "deploy/**",
    "**/__pycache__/**",
)
# Yürünmeyen dizinler (izin listesi bunların altını zaten kapsamaz; hız ve symlink güvenliği).
_ATLANAN_DIZINLER = frozenset({".git", "node_modules", "dist", "__pycache__", ".venv", "var"})

# Pakette kalabilen bilinen demo parolası (compose varsayılanı, belgelerde açık); araç çıktısında
# yine temizlenir (`known_secret_values`).
DEMO_DEGERLERI = frozenset({"Demo123!"})
_ANLAMSIZ_DEGERLER = frozenset({"true", "false", "yes", "no", "on", "off", "none", "null"})
_SIR_ADI_RE = re.compile(r"PASSWORD|SECRET|TOKEN|KEY|PRIVATE|CREDENTIAL|PAROLA|SIFRE|AUTH", re.I)
# Adı sır gibi görünmeyen değişkenlerde yalnız rastgele görünümlü değerler aranır (URL, yol, model
# adı gibi belgelerde doğal olarak geçen değerler yanlış alarm üretmesin).
_RASTGELE_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[A-Za-z0-9+/=_.-]{16,}$")
# Belgelerdeki örnek değerler (`${TP_APP_PASSWORD}`, `<token>`, `tpt_…`) bulgu sayılmaz.
_YER_TUTUCU_RE = re.compile(
    r"\$\{|\$[A-Z_]|<[^>]*>|…|\.\.\.|\*\*\*|\bx{4,}\b|changeme|ornek|örnek|example", re.I
)


class PaketHatasi(RuntimeError):
    pass


# ------------------------------------------------------------------ desen eşleme


def _glob_regex(desen: str) -> re.Pattern[str]:
    """`**`, `*`, `?` ve `{a,b}` destekli glob → tam eşleşme regex'i (yol ayırıcı `/`)."""
    i, out = 0, []
    while i < len(desen):
        c = desen[i]
        if desen.startswith("**/", i):
            out.append(r"(?:[^/]+/)*")
            i += 3
            continue
        if desen.startswith("**", i):
            out.append(r".*")
            i += 2
            continue
        if c == "*":
            out.append(r"[^/]*")
        elif c == "?":
            out.append(r"[^/]")
        elif c == "{":
            son = desen.index("}", i)
            secenekler = desen[i + 1 : son].split(",")
            out.append("(?:" + "|".join(re.escape(s) for s in secenekler) + ")")
            i = son + 1
            continue
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + r"\Z")


_IZIN_RE = tuple(_glob_regex(d) for d in IZIN_LISTESI)
_HARIC_RE = tuple(_glob_regex(d) for d in HARIC_LISTESI)


def secilir_mi(yol: str) -> bool:
    """Repo köküne göre `/` ayırıcılı yol izin listesinde ve hariç listesinde değilse True."""
    return any(r.match(yol) for r in _IZIN_RE) and not any(r.match(yol) for r in _HARIC_RE)


def dosyalari_sec(kaynak: Path) -> tuple[list[str], list[str]]:
    """(seçilen yollar, uyarılar). Symlink'ler izlenmez ve alınmaz; yalnız düzenli dosyalar."""
    secilen: list[str] = []
    uyarilar: list[str] = []
    for kok, dizinler, dosyalar in os.walk(kaynak, followlinks=False):
        dizinler[:] = sorted(
            d for d in dizinler if d not in _ATLANAN_DIZINLER and not os.path.islink(Path(kok) / d)
        )
        for ad in sorted(dosyalar):
            tam = Path(kok) / ad
            yol = tam.relative_to(kaynak).as_posix()
            if not secilir_mi(yol):
                continue
            if tam.is_symlink() or not tam.is_file():
                uyarilar.append(f"{yol}: symlink/düzenli olmayan dosya alınmadı")
                continue
            if tam.stat().st_size > MAX_DOSYA_BAYT:
                uyarilar.append(f"{yol}: {MAX_DOSYA_BAYT} bayttan büyük, alınmadı")
                continue
            secilen.append(yol)
    return sorted(secilen), uyarilar


# ------------------------------------------------------------------ sır taraması


def env_degerleri(env_dosyasi: Path) -> list[str]:
    """`.env` dosyasındaki taranacak değerler (dosya yoksa boş). Değerler asla yazdırılmaz."""
    if not env_dosyasi.is_file():
        return []
    out: list[str] = []
    for satir in env_dosyasi.read_text(encoding="utf-8", errors="replace").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#") or "=" not in satir:
            continue
        ad, _, deger = satir.removeprefix("export ").partition("=")
        ad, deger = ad.strip(), deger.strip()
        if len(deger) >= 2 and deger[0] == deger[-1] and deger[0] in "'\"":
            deger = deger[1:-1]
        if _taranacak_deger(ad, deger):
            out.append(deger)
    return out


def _taranacak_deger(ad: str, deger: str) -> bool:
    if len(deger) < SECRET_VALUE_MIN_LEN or deger in DEMO_DEGERLERI:
        return False
    if deger.lower() in _ANLAMSIZ_DEGERLER or re.fullmatch(r"[\d.:,_ -]+", deger):
        return False
    if _SIR_ADI_RE.search(ad):
        return True
    return bool(_RASTGELE_RE.match(deger))


@dataclass(frozen=True)
class SirBulgusu:
    yol: str
    satir: int
    tur: str

    def __str__(self) -> str:
        return f"{self.yol}:{self.satir}: {self.tur}"


def metni_tara(yol: str, metin: str, degerler: Sequence[str]) -> list[SirBulgusu]:
    bulgular: list[SirBulgusu] = []
    for f in find_secret_patterns(metin, degerler):
        if f.name == "known_value_partial":
            continue  # dosya metni kesik değil; tam değer aranır
        # Yer tutucu bağlamı: eşleşen parça örnek/şablon ise (`${…}`, `<token>`) bulgu değil.
        parca = metin[f.start : f.end]
        if f.name != "known_value" and (_YER_TUTUCU_RE.search(parca) or parca in DEMO_DEGERLERI):
            continue
        if f.name in ("env_assignment", "authorization") and len(parca) < SECRET_VALUE_MIN_LEN:
            continue  # `JIRA_WRITE_TOKEN=sim` gibi simülatör/örnek değerleri
        bulgular.append(SirBulgusu(yol, metin.count("\n", 0, f.start) + 1, f.name))
    return bulgular


def tarama_degerleri(kaynak: Path, ortam: Iterable[str] | None = None) -> list[str]:
    """`.env` değerleri + süreç ortamındaki sır değerleri (demo parolası hariç)."""
    ortam_degerleri = known_secret_values() if ortam is None else list(ortam)
    birlesik = env_degerleri(kaynak / ".env") + [
        v for v in ortam_degerleri if len(v) >= SECRET_VALUE_MIN_LEN and v not in DEMO_DEGERLERI
    ]
    return list(dict.fromkeys(birlesik))


# ------------------------------------------------------------------ üretim


@dataclass
class UretimSonucu:
    dosya_sayisi: int = 0
    toplam_bayt: int = 0
    surum_dizini: str = ""
    uyarilar: list[str] = field(default_factory=list)
    bulgular: list[SirBulgusu] = field(default_factory=list)


def uret(
    kaynak: Path,
    cikti: Path,
    *,
    commit: str = "",
    ortam_degerleri: Iterable[str] | None = None,
    simdi: datetime | None = None,
) -> UretimSonucu:
    """Paketi üretir. Sır bulgusu varsa hiçbir şey yazılmaz (`sonuc.bulgular` dolu döner)."""
    kaynak = kaynak.resolve()
    if not kaynak.is_dir():
        raise PaketHatasi(f"kaynak dizin yok: {kaynak}")
    cikti.mkdir(parents=True, exist_ok=True)
    sonuc = UretimSonucu()
    secilen, sonuc.uyarilar = dosyalari_sec(kaynak)
    if not secilen:
        raise PaketHatasi("izin listesine uyan dosya yok (kaynak repo kökü mü?)")
    degerler = tarama_degerleri(kaynak, ortam_degerleri)

    icerikler: dict[str, bytes] = {}
    for yol in secilen:
        veri = (kaynak / yol).read_bytes()
        try:
            metin = veri.decode("utf-8")
        except UnicodeDecodeError:
            sonuc.uyarilar.append(f"{yol}: UTF-8 değil, alınmadı")
            continue
        if "\x00" in metin:
            sonuc.uyarilar.append(f"{yol}: ikili içerik, alınmadı")
            continue
        sonuc.bulgular += metni_tara(yol, metin, degerler)
        icerikler[yol] = veri
    if sonuc.bulgular:
        return sonuc

    zaman = simdi or datetime.now(UTC)
    kimlik = f"{zaman.strftime('%Y%m%dT%H%M%SZ')}-{(commit or 'yerel')[:12]}-{uuid.uuid4().hex[:6]}"
    surum_rel = f"{SURUMLER_DIZINI}/{kimlik}"
    surum = cikti / surum_rel
    dosyalar: dict[str, dict[str, object]] = {}
    for yol, veri in icerikler.items():
        hedef = surum / yol
        hedef.parent.mkdir(parents=True, exist_ok=True)
        hedef.write_bytes(veri)
        os.chmod(hedef, 0o644)
        dosyalar[yol] = {
            "sha256": hashlib.sha256(veri).hexdigest(),
            "boyut": len(veri),
            "satir": len(veri.decode("utf-8").splitlines()),
        }
        sonuc.toplam_bayt += len(veri)
    manifest = {
        "surum": MANIFEST_SURUMU,
        "commit": commit,
        "uretim": zaman.isoformat(),
        "dizin": surum_rel,
        "dosyalar": dosyalar,
    }
    onceki = _gecerli_surum(cikti)
    gecici = cikti / f".{MANIFEST_ADI}.{uuid.uuid4().hex}"
    gecici.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    os.chmod(gecici, 0o644)
    os.replace(gecici, cikti / MANIFEST_ADI)
    _eski_surumleri_sil(cikti, {kimlik, onceki})
    sonuc.dosya_sayisi = len(dosyalar)
    sonuc.surum_dizini = surum_rel
    return sonuc


def _gecerli_surum(cikti: Path) -> str:
    """Şu anki MANIFEST'in işaret ettiği sürüm kimliği (yoksa boş)."""
    try:
        dizin = json.loads((cikti / MANIFEST_ADI).read_text("utf-8")).get("dizin", "")
    except (OSError, ValueError, AttributeError):
        return ""
    return dizin.rpartition("/")[2] if isinstance(dizin, str) else ""


def _eski_surumleri_sil(cikti: Path, tutulacak: set[str]) -> None:
    """Geçerli ve bir önceki sürüm (o anda okuyan çağrı için) dışındakileri siler."""
    for p in (cikti / SURUMLER_DIZINI).iterdir():
        if p.name not in tutulacak:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m tp_core.features.assistant.paket",
        description=(
            "Asistan ürün bilgi paketini üretir (izin/hariç listesi, sha256, MANIFEST, "
            "sır taraması)."
        ),
    )
    ap.add_argument("--kaynak", required=True, type=Path, help="repo kökü (salt okunur)")
    ap.add_argument("--cikti", required=True, type=Path, help="paket dizini (ör. var/tp-bilgi)")
    ap.add_argument("--commit", default="", help="kaynağın commit'i (MANIFEST'e yazılır)")
    args = ap.parse_args(argv)
    try:
        sonuc = uret(args.kaynak, args.cikti, commit=args.commit.strip())
    except (PaketHatasi, OSError) as exc:
        print(f"HATA: bilgi paketi üretilemedi: {exc}", file=sys.stderr)
        return 1
    for uyari in sonuc.uyarilar:
        print(f"uyarı: {uyari}", file=sys.stderr)
    if sonuc.bulgular:
        print(
            f"HATA: sır taraması {len(sonuc.bulgular)} bulgu verdi; paket YAZILMADI "
            "(değerler gösterilmez):",
            file=sys.stderr,
        )
        for b in sonuc.bulgular:
            print(f"  {b}", file=sys.stderr)
        return 2
    print(
        f"Bilgi paketi hazır: {sonuc.dosya_sayisi} dosya, {sonuc.toplam_bayt} bayt "
        f"({sonuc.surum_dizini}, commit {args.commit[:12] or '-'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
