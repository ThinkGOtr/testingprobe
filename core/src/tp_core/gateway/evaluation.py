"""Prompt paketlerinin canlı değerlendirme durumu (constitution X) — `rules/evaluations.yaml`.

Constitution X: "Prompt/kural değişikliği değerlendirme setini canlı modelle koşturmadan
birleştirilmez." Bu modül her prompt paketinin güncel sürümü için durum kaydını okur ve doğrular:

- `pending`   → "canlı değerlendirme bekliyor" (kullanıcıya görünür etiket),
- `evaluated` → tarihli canlı değerlendirme kaydı (`evaluation`: date, model, provider, results),
- `waived`    → sahibin onayladığı tarihli istisna
  (`waiver`: approved_by, approved_at, reason, until).

Kayıt sürümü prompt ön bilgisindeki `version`'dan farklıysa kayıt bayattır (`stale`); prompt
yükseltilip durum yazılmadan birleştirilemez. `--check` birleştirme kapısıdır: bekleyen veya bayat
kayıt varsa çıkış kodu 1. Bu modül istisna üretmez; istisna yalnızca sahip onayıyla elle yazılır.

**İçerik hash'i** (AI-ASISTAN-PLANI §4.2 X): bazı paketlerin davranışı prompt sürümünden fazlasına
bağlıdır (şema, `models.yaml` amaç ayarları, kural dosyaları). Bu paketler için `ICERIK_KAYNAKLARI`
sabit dosya listesinden bir hash hesaplanır (`icerik_hash`); `make eval-live A=--update-status` onu
`evaluation.icerik_hash`'e yazar. `evaluated` kayıtta hash yoksa ya da güncel içerikle uyuşmuyorsa
durum `icerik_degisti` olur ve kapı kapanır (prompt sürümü yükseltilmeden yapılan şema/ayar/kural
değişikliği de değerlendirilmemiş içerik sayılır). `waived` kayıtta hash denetlenmez.

    cd core && uv run python -m tp_core.gateway.evaluation            # durum tablosu
    cd core && uv run python -m tp_core.gateway.evaluation --check    # birleştirme kapısı
    cd core && uv run python -m tp_core.gateway.evaluation --hash     # güncel içerik hash'leri
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tp_core.gateway.bundle import parse_prompt_file
from tp_core.gateway.errors import GatewayConfigError

EVALUATIONS_FILE = "evaluations.yaml"
STATUSES = ("pending", "evaluated", "waived")
PENDING_LABEL = "canlı değerlendirme bekliyor"
_LABELS = {
    "pending": PENDING_LABEL,
    "evaluated": "canlı değerlendirildi",
    "waived": "onaylı istisna (canlı değerlendirme yok)",
    "stale": "değerlendirme kaydı bayat (prompt sürümü değişti)",
    "icerik_degisti": "değerlendirme sonrası içerik değişti (içerik hash'i uyuşmuyor)",
    "missing": "değerlendirme kaydı yok",
}
_EVALUATION_FIELDS = ("date", "model", "provider", "results")
_WAIVER_FIELDS = ("approved_by", "approved_at", "reason", "until")


ICERIK_HASH_ALANI = "icerik_hash"
_YOK = b"<yok>"


@dataclass(frozen=True)
class IcerikKaynagi:
    """Bir paketin değerlendirilen içeriği (yollar `rules/`'a göre, sabit liste).

    `dosyalar`: tek tek dosyalar; `globlar`: sabit dizin içindeki desenler (ör. `assistant/*.yaml`);
    `model_amaclari`: `models.yaml` `purposes` altındaki amaç blokları (yalnız bu bloklar; fiyat
    tablosu ve diğer amaçlar hash'e girmez)."""

    dosyalar: tuple[str, ...]
    globlar: tuple[str, ...] = ()
    model_amaclari: tuple[str, ...] = ()


# AI-ASISTAN-PLANI §4.2 X: prompt, iki şema, `models.yaml` asistan amaçları,
# `rules/assistant/*.yaml` ve `rules/assistant/rotalar.json` (model çıktısındaki rotanın bağlantıya
# dönüşmesini ve öneri kurallarının ekran/eylem doğrulamasını belirler; plandaki listeye eklendi).
# Değerlendirme seti (`evaluation/assistant.json`) ölçüttür, içerik değil; hash'e girmez.
# 011 F4 platform ekleri: ek kendi paketidir (kayıt + set) ama ev sahibi `case-generation` ile
# çağrılır; değerlendirilen içerik ek + ortak ek + ev sahibi prompt + şema + amaç ayarıdır. Ev
# sahibi prompt/şema değişirse ekin `evaluated` kaydı `icerik_degisti` olur (kapı kapanır).
_PLATFORM_EV_SAHIBI = (
    "prompts/platform-common.md",
    "prompts/case-generation.md",
    "schemas/case_generation.schema.json",
)
_PLATFORM_EKLERI = (
    "platform-common",
    "platform-web",
    "platform-mobile",
    "platform-desktop",
    "platform-api",
    "platform-data",
)
# 011 P5/P6 derinleştirme: prompt + kendi şeması (case_generation kopyası) + amaç ayarı.
_DERINLESTIRME = ("case-negative", "case-technique")

# 011 F7 asistan içerik kontrolü (`assistant-guard`) KENDİ içerik hash'iyle kapılanır (prompt,
# şema, `assistant_guard` amaç ayarı); asistan içeriğine dahil edilmez (D4 kararı). Gerekçe: kontrol
# asistanın cevabını üretmez, yalnız gösterip göstermemeye karar verir; o kararın doğruluğu (yanlış
# engelleme dahil: temiz soru/cevap vakaları) `assistant-guard` setiyle ölçülür. Asistan hash'ine
# girdiğinde her eşik/prompt ayarı asistanın tüm `--via-flow` koşusunu (en pahalı set) bayatlatır,
# kontrolün kendi şema/ayar değişikliği ise hiçbir kapıya takılmazdı (yalnız sürüm). Kontrol
# değiştiğinde `--bundle assistant --via-flow` koşusu önerilir (uçtan uca etki), kapı değildir.
ICERIK_KAYNAKLARI: Mapping[str, IcerikKaynagi] = {
    "assistant": IcerikKaynagi(
        dosyalar=(
            "prompts/assistant.md",
            "schemas/assistant.schema.json",
            "schemas/assistant_deep.schema.json",
        ),
        globlar=("assistant/*.yaml", "assistant/*.json"),
        model_amaclari=("assistant", "assistant_deep"),
    ),
    "assistant-guard": IcerikKaynagi(
        dosyalar=("prompts/assistant-guard.md", "schemas/assistant_guard.schema.json"),
        model_amaclari=("assistant_guard",),
    ),
    **{
        ek: IcerikKaynagi(
            dosyalar=tuple(sorted({f"prompts/{ek}.md", *_PLATFORM_EV_SAHIBI})),
            model_amaclari=("case_generation",),
        )
        for ek in _PLATFORM_EKLERI
    },
    **{
        paket: IcerikKaynagi(
            dosyalar=(f"prompts/{paket}.md", "schemas/case_deepening.schema.json"),
            model_amaclari=("case_deepening",),
        )
        for paket in _DERINLESTIRME
    },
}


def icerik_dosyalari(rules_dir: Path, bundle_id: str) -> list[str]:
    """Paketin hash'e giren dosyaları (`rules/`'a göre, sıralı); kaydı yoksa boş liste."""
    kaynak = ICERIK_KAYNAKLARI.get(bundle_id)
    if kaynak is None:
        return []
    yollar = set(kaynak.dosyalar)
    for desen in kaynak.globlar:
        yollar |= {str(p.relative_to(rules_dir)) for p in rules_dir.glob(desen) if p.is_file()}
    return sorted(yollar)


def icerik_hash(rules_dir: Path, bundle_id: str) -> str | None:
    """Paketin içerik hash'i (`sha256:<hex>`); `ICERIK_KAYNAKLARI`'nda olmayan paket → None.

    Satır sonları normalize edilir (CRLF ↔ LF farkı içerik değişikliği sayılmaz). Eksik dosya
    `<yok>` olarak hash'e girer (silinen dosya da değişikliktir). `models.yaml` amaç blokları
    ayrıştırılıp kanonik JSON olarak girer (yorum/biçim değişikliği hash'i değiştirmez)."""
    kaynak = ICERIK_KAYNAKLARI.get(bundle_id)
    if kaynak is None:
        return None
    h = hashlib.sha256()
    for rel in icerik_dosyalari(rules_dir, bundle_id):
        path = rules_dir / rel
        veri = path.read_bytes().replace(b"\r\n", b"\n") if path.is_file() else _YOK
        h.update(rel.encode() + b"\0" + hashlib.sha256(veri).hexdigest().encode() + b"\n")
    if kaynak.model_amaclari:
        models_path = rules_dir / "models.yaml"
        try:
            purposes = (yaml.safe_load(models_path.read_text(encoding="utf-8")) or {}).get(
                "purposes"
            ) or {}
        except FileNotFoundError:
            purposes = {}
        for amac in kaynak.model_amaclari:
            blok = json.dumps(purposes.get(amac), ensure_ascii=False, sort_keys=True, default=str)
            h.update(f"models.yaml#purposes.{amac}\0".encode() + blok.encode() + b"\n")
    return "sha256:" + h.hexdigest()


@dataclass(frozen=True)
class EvaluationStatus:
    bundle_id: str
    prompt_version: int
    recorded_version: int | None
    status: str  # pending | evaluated | waived | stale | icerik_degisti | missing
    detail: Mapping[str, Any] | None = None

    @property
    def label(self) -> str:
        return _LABELS[self.status]

    @property
    def mergeable(self) -> bool:
        """Constitution X kapısı: güncel sürüm için canlı değerlendirme veya onaylı istisna."""
        return self.status in ("evaluated", "waived")


def _is_date(value: Any) -> bool:
    if isinstance(value, dt.date):
        return True
    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _require(entry: Mapping[str, Any], key: str, fields: tuple[str, ...], where: str) -> dict:
    block = entry.get(key)
    if not isinstance(block, Mapping):
        raise GatewayConfigError(f"{where}: '{key}' bloğu zorunlu")
    for field in fields:
        value = block.get(field)
        if value in (None, "") or (isinstance(value, str) and not value.strip()):
            raise GatewayConfigError(f"{where}: '{key}.{field}' zorunlu")
    date_field = "date" if key == "evaluation" else "approved_at"
    if not _is_date(block[date_field]):
        raise GatewayConfigError(f"{where}: '{key}.{date_field}' YYYY-MM-DD olmalı")
    return dict(block)


def _validate_entry(name: str, entry: Any, path: Path) -> dict[str, Any]:
    where = f"{path}: {name}"
    if not isinstance(entry, Mapping):
        raise GatewayConfigError(f"{where}: kayıt bir eşleme olmalı")
    version = entry.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise GatewayConfigError(f"{where}: 'version' tamsayı olmalı")
    status = entry.get("status")
    if status not in STATUSES:
        raise GatewayConfigError(f"{where}: 'status' {STATUSES} içinden olmalı, {status!r} geldi")
    out = dict(entry)
    if status == "evaluated":
        out["evaluation"] = _require(entry, "evaluation", _EVALUATION_FIELDS, where)
    elif status == "waived":
        out["waiver"] = _require(entry, "waiver", _WAIVER_FIELDS, where)
    elif entry.get("evaluation") or entry.get("waiver"):
        raise GatewayConfigError(f"{where}: 'pending' kayıt evaluation/waiver taşıyamaz")
    return out


def load_evaluations(rules_dir: Path) -> dict[str, dict[str, Any]]:
    path = rules_dir / EVALUATIONS_FILE
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise GatewayConfigError(f"{path} bulunamadı (constitution X durum kaydı)") from None
    bundles = data.get("bundles")
    if not isinstance(bundles, Mapping):
        raise GatewayConfigError(f"{path}: 'bundles' eşlemesi zorunlu")
    return {str(name): _validate_entry(str(name), entry, path) for name, entry in bundles.items()}


def prompt_versions(rules_dir: Path) -> dict[str, int]:
    """rules/prompts/*.md → {ön bilgideki id: version} (`_guardrails` dahil)."""
    out: dict[str, int] = {}
    for path in sorted((rules_dir / "prompts").glob("*.md")):
        meta, _ = parse_prompt_file(path.read_text(encoding="utf-8"), path)
        out[str(meta["id"])] = int(meta["version"])
    if not out:
        raise GatewayConfigError(f"{rules_dir / 'prompts'}: prompt dosyası yok")
    return out


def evaluation_statuses(rules_dir: Path) -> dict[str, EvaluationStatus]:
    records = load_evaluations(rules_dir)
    out: dict[str, EvaluationStatus] = {}
    for bundle_id, version in prompt_versions(rules_dir).items():
        rec = records.get(bundle_id)
        if rec is None:
            out[bundle_id] = EvaluationStatus(bundle_id, version, None, "missing")
            continue
        status = rec["status"] if rec["version"] == version else "stale"
        detail = rec.get("evaluation") or rec.get("waiver")
        if status == "evaluated" and bundle_id in ICERIK_KAYNAKLARI:
            kayitli = (rec.get("evaluation") or {}).get(ICERIK_HASH_ALANI)
            if kayitli != icerik_hash(rules_dir, bundle_id):
                status = "icerik_degisti"
        out[bundle_id] = EvaluationStatus(bundle_id, version, rec["version"], status, detail)
    unknown = sorted(set(records) - set(out))
    if unknown:
        raise GatewayConfigError(
            f"{rules_dir / EVALUATIONS_FILE}: prompt dosyası olmayan kayıt(lar): {unknown}"
        )
    return out


def evaluation_status(rules_dir: Path, bundle_id: str) -> EvaluationStatus:
    statuses = evaluation_statuses(rules_dir)
    try:
        return statuses[bundle_id]
    except KeyError:
        raise GatewayConfigError(f"bilinmeyen prompt paketi: {bundle_id!r}") from None


def evaluation_summary(rules_dir: Path, bundle_id: str) -> dict[str, Any]:
    """Bir paketin kullanıcıya gösterilecek durum özeti (`ai_call.ek.degerlendirme`, portal).

    `{"paket", "surum", "durum", "etiket"}`; ortak `guardrails` paketi birleştirilebilir değilse
    `guardrails_durum` da eklenir. Kayıt okunamazsa çağrı düşmez: `durum = "missing"` ve `hata`.
    Etiket: `pending` → "canlı değerlendirme bekliyor" (portal bunu aynen gösterir).
    """
    try:
        statuses = evaluation_statuses(rules_dir)
    except GatewayConfigError as exc:
        return {
            "paket": bundle_id,
            "surum": None,
            "durum": "missing",
            "etiket": _LABELS["missing"],
            "hata": str(exc)[:300],
        }
    st = statuses.get(bundle_id)
    if st is None:
        return {"paket": bundle_id, "surum": None, "durum": "missing", "etiket": _LABELS["missing"]}
    out: dict[str, Any] = {
        "paket": bundle_id,
        "surum": st.prompt_version,
        "durum": st.status,
        "etiket": st.label,
    }
    guard = statuses.get("guardrails")
    if guard is not None and bundle_id != "guardrails" and not guard.mergeable:
        out["guardrails_durum"] = guard.status
    return out


def blocking(rules_dir: Path) -> list[EvaluationStatus]:
    """Constitution X kapısını kapatan paketler (bekleyen, bayat veya kaydı olmayan)."""
    return [s for s in evaluation_statuses(rules_dir).values() if not s.mergeable]


def main(argv: list[str] | None = None) -> int:
    from tp_core.gateway.config import find_rules_dir

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rules-dir", type=Path, default=None)
    parser.add_argument(
        "--check", action="store_true", help="birleştirme kapısı: bekleyen kayıt varsa çıkış 1"
    )
    parser.add_argument(
        "--hash", action="store_true", help="içerik hash'i tutulan paketlerin güncel hash'i"
    )
    args = parser.parse_args(argv)
    rules_dir = args.rules_dir or find_rules_dir()
    if args.hash:
        for bundle_id in ICERIK_KAYNAKLARI:
            print(f"{bundle_id}\t{icerik_hash(rules_dir, bundle_id)}")
            for rel in icerik_dosyalari(rules_dir, bundle_id):
                print(f"  {rel}")
        return 0
    try:
        statuses = evaluation_statuses(rules_dir)
    except GatewayConfigError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2
    for s in statuses.values():
        print(f"{s.bundle_id}@v{s.prompt_version}\t{s.status}\t{s.label}")
        if s.status == "icerik_degisti":
            kayitli = (s.detail or {}).get(ICERIK_HASH_ALANI) or "(kayıtta yok)"
            guncel = icerik_hash(rules_dir, s.bundle_id)
            print(f"  içerik hash'i: kayıtlı {kayitli}, güncel {guncel}")
    if args.check:
        blocked = [s for s in statuses.values() if not s.mergeable]
        if blocked:
            names = ", ".join(f"{s.bundle_id}@v{s.prompt_version} ({s.label})" for s in blocked)
            print(
                f"Constitution X: canlı değerlendirme veya onaylı istisna yok: {names}",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
