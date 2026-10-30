"""`ports.CallRecorder` uygulaması: model geçidinin `ai_call` / `tool_call` yazımı.

Tablolar append-only'dir (uygulama rolü yalnızca INSERT/SELECT). Her yeni satır aynı işlemde
denetim zincirine de bağlanır (`ai_call.recorded` / `tool_call.recorded`, nesne `<tablo>:<id>`,
özette `satir_sha256` çapası, `capa_surumu=2`). Çapa, Postgres'in SAKLADIĞI değerlerden
(`INSERT … RETURNING`) hesaplanır: jsonb ayrıştırılmış değer olarak kanonik JSON'a, numeric metne
(`Decimal`, ölçeğiyle), uuid metne çevrilir — böylece aynı hash daha sonra tablodan yeniden
hesaplanabilir. `verify_call_anchors()` (ve `GET /audit?verify=true`) her çapayı satırın bugünkü
haliyle karşılaştırır: tablo sahibi bir satırı silse ya da değiştirse tutarsızlık görülür
(Constitution VIII). Satır anahtarları Türkçe kolon
adlarıdır; geçit şeridinin rahatı için İngilizce eşanlamlılar da kabul edilir (aşağıdaki tablolar).
Bilinmeyen anahtar hata verir (sessizce düşürülmez). `id` verilirse yazım idempotenttir: aynı
`id` ikinci kez yazılmaz (aktivite yeniden denemesi aynı çağrıyı iki kez faturalamaz, §8.8).

ai_call kolonları: id, parent_call_id, workflow_id, amac*, saglayici*, model*, surum, bundle_hash,
maskeli_girdi, cikti, sema_gecerli, deneme, girdi_token, cikti_token, maliyet (USD), sure_ms,
mod* (live|replay|replay_miss), replay_anahtari, hata, maskeleme_farki, ek   (* zorunlu)

`ek` (0005) sonradan eklenen isteğe bağlı kolondur: çapaya yalnızca NULL değilse girer, böylece
kolondan önce yazılmış satırların capa_surumu=2 çapaları geçerli kalır; NULL'dan bir değere ya da
değerden NULL'a değiştirmek yine çapayı bozar.

tool_call kolonları: id, ai_call_id, kanal* (agent|ide), cagiran_user_id, arac*, arguman_ozeti,
sonuc_ozeti, izin_verildi, sure_ms
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, Engine, text

from tp_core.audit.canonical import content_hash, normalize
from tp_core.audit.chain import append_audit

DENETIM_AKTORU = "system"

AI_CALL_COLUMNS: dict[str, str] = {
    "id": "uuid",
    "parent_call_id": "uuid",
    "workflow_id": "uuid",
    "amac": "text",
    "saglayici": "text",
    "model": "text",
    "surum": "text",
    "bundle_hash": "text",
    "maskeli_girdi": "jsonb",
    "cikti": "jsonb",
    "sema_gecerli": "bool",
    "deneme": "int",
    "girdi_token": "int",
    "cikti_token": "int",
    "maliyet": "numeric",
    "sure_ms": "int",
    "mod": "text",
    "replay_anahtari": "text",
    "hata": "text",
    "maskeleme_farki": "jsonb",
    "ek": "jsonb",
}
AI_CALL_REQUIRED = ("amac", "saglayici", "model", "mod")
AI_CALL_ALIASES: dict[str, str] = {
    "call_id": "id",
    "parent_id": "parent_call_id",
    "purpose": "amac",
    "provider": "saglayici",
    "model_version": "surum",
    "version": "surum",
    "input": "maskeli_girdi",
    "masked_input": "maskeli_girdi",
    "output": "cikti",
    "schema_valid": "sema_gecerli",
    "attempt": "deneme",
    "input_tokens": "girdi_token",
    "output_tokens": "cikti_token",
    "cost_usd": "maliyet",
    "duration_ms": "sure_ms",
    "mode": "mod",
    "replay": "mod",
    "replay_key": "replay_anahtari",
    "error": "hata",
    "masking_diff": "maskeleme_farki",
    "extras": "ek",
}

TOOL_CALL_COLUMNS: dict[str, str] = {
    "id": "uuid",
    "ai_call_id": "uuid",
    "kanal": "text",
    "cagiran_user_id": "uuid",
    "arac": "text",
    "arguman_ozeti": "jsonb",
    "sonuc_ozeti": "text",
    "izin_verildi": "bool",
    "sure_ms": "int",
}
TOOL_CALL_REQUIRED = ("kanal", "arac")
TOOL_CALL_ALIASES: dict[str, str] = {
    "call_id": "ai_call_id",
    "channel": "kanal",
    "caller_user_id": "cagiran_user_id",
    "tool": "arac",
    "args": "arguman_ozeti",
    "args_summary": "arguman_ozeti",
    "result_summary": "sonuc_ozeti",
    "allowed": "izin_verildi",
    "duration_ms": "sure_ms",
}


def _hazirla(
    row: Mapping[str, Any],
    columns: Mapping[str, str],
    aliases: Mapping[str, str],
    required: tuple[str, ...],
    tablo: str,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for anahtar, deger in row.items():
        kolon = anahtar if anahtar in columns else aliases.get(anahtar)
        if kolon is None:
            raise ValueError(f"{tablo}: bilinmeyen alan {anahtar!r}")
        if kolon in out:
            raise ValueError(f"{tablo}: {kolon!r} iki kez verildi")
        tur = columns[kolon]
        if deger is not None and tur == "jsonb":
            deger = json.dumps(normalize(deger), ensure_ascii=False, allow_nan=False)
        elif deger is not None and tur == "uuid":
            deger = deger if isinstance(deger, uuid.UUID) else uuid.UUID(str(deger))
        out[kolon] = deger
    eksik = [k for k in required if out.get(k) in (None, "")]
    if eksik:
        raise ValueError(f"{tablo}: zorunlu alan eksik: {', '.join(eksik)}")
    out.setdefault("id", uuid.uuid4())
    return out


CAPA_SURUMU = 2
TABLOLAR: dict[str, Mapping[str, str]] = {
    "ai_call": AI_CALL_COLUMNS,
    "tool_call": TOOL_CALL_COLUMNS,
}


def _insert(
    conn: Connection, tablo: str, values: dict[str, Any], columns: Mapping[str, str]
) -> Mapping[str, Any] | None:
    """Satırı ekler ve saklanan halini döndürür; aynı `id` zaten varsa (idempotent) None."""
    kolonlar = list(values)
    ifadeler = [f"CAST(:{k} AS jsonb)" if columns[k] == "jsonb" else f":{k}" for k in kolonlar]
    return (
        conn.execute(
            text(
                f"INSERT INTO {tablo} ({', '.join(kolonlar)}) VALUES ({', '.join(ifadeler)}) "
                f"ON CONFLICT (id) DO NOTHING RETURNING {', '.join(columns)}"
            ),
            values,
        )
        .mappings()
        .first()
    )


def _kanonik(tur: str, deger: Any) -> Any:
    if deger is None:
        return None
    if tur == "numeric":
        return str(deger if isinstance(deger, Decimal) else Decimal(str(deger)))
    if tur == "uuid":
        return str(deger)
    return deger  # jsonb: ayrıştırılmış değer; text/int/bool olduğu gibi


# Sonradan eklenen, NULL olabilen kolonlar: NULL iken çapaya girmez (eski çapalar geçerli kalır).
SONRADAN_KOLONLAR: dict[str, frozenset[str]] = {"ai_call": frozenset({"ek"})}


def row_anchor(tablo: str, row: Mapping[str, Any]) -> str:
    """Saklanan satırın çapası: tablonun tüm kolonları (NULL'lar dahil) üstünde kanonik sha256.

    İstisna: `SONRADAN_KOLONLAR` NULL ise atlanır.
    """
    columns = TABLOLAR[tablo]
    sonradan = SONRADAN_KOLONLAR.get(tablo, frozenset())
    return content_hash(
        {
            k: _kanonik(t, row.get(k))
            for k, t in columns.items()
            if not (k in sonradan and row.get(k) is None)
        }
    )


def record_ai_call(conn: Connection, row: Mapping[str, Any]) -> uuid.UUID:
    values = _hazirla(row, AI_CALL_COLUMNS, AI_CALL_ALIASES, AI_CALL_REQUIRED, "ai_call")
    saklanan = _insert(conn, "ai_call", values, AI_CALL_COLUMNS)
    if saklanan is not None:
        append_audit(
            conn,
            DENETIM_AKTORU,
            "ai_call.recorded",
            f"ai_call:{values['id']}",
            {
                "mod": values["mod"],
                "model": values["model"],
                "amac": values["amac"],
                "bundle_hash": values.get("bundle_hash"),
                "workflow_id": values.get("workflow_id"),
                "satir_sha256": row_anchor("ai_call", saklanan),
                "capa_surumu": CAPA_SURUMU,
            },
        )
    return values["id"]


def record_tool_call(conn: Connection, row: Mapping[str, Any]) -> uuid.UUID:
    values = _hazirla(row, TOOL_CALL_COLUMNS, TOOL_CALL_ALIASES, TOOL_CALL_REQUIRED, "tool_call")
    saklanan = _insert(conn, "tool_call", values, TOOL_CALL_COLUMNS)
    if saklanan is not None:
        append_audit(
            conn,
            DENETIM_AKTORU,
            "tool_call.recorded",
            f"tool_call:{values['id']}",
            {
                "kanal": values["kanal"],
                "arac": values["arac"],
                "ai_call_id": values.get("ai_call_id"),
                "izin_verildi": values.get("izin_verildi"),
                "satir_sha256": row_anchor("tool_call", saklanan),
                "capa_surumu": CAPA_SURUMU,
            },
        )
    return values["id"]


@dataclass
class AnchorVerification:
    """`verify_call_anchors` sonucu. `eski`: çapa sürümü olmayan (yeniden hesaplanamayan) kayıt;
    `sabitsiz`: denetim zincirinde çapası olmayan ai_call/tool_call satırı (kaydedici atlanmış)."""

    ok: bool = True
    checked: int = 0
    eski: int = 0
    sabitsiz: int = 0
    broken: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "eski": self.eski,
            "sabitsiz": self.sabitsiz,
            "broken": list(self.broken),
        }


MAX_BROKEN_RAPOR = 50


def verify_call_anchors(conn: Connection) -> AnchorVerification:
    """Zincirdeki her `ai_call`/`tool_call` çapasını satırın bugünkü haliyle karşılaştırır."""
    sonuc = AnchorVerification()

    def bozuk(nesne: str, neden: str) -> None:
        sonuc.ok = False
        if len(sonuc.broken) < MAX_BROKEN_RAPOR:
            sonuc.broken.append({"nesne": nesne, "reason": neden})

    for tablo, columns in TABLOLAR.items():
        capalar = conn.execute(
            text(
                "SELECT DISTINCT ON (nesne) nesne, ozet FROM audit_event "
                "WHERE eylem = :e ORDER BY nesne, id"
            ),
            {"e": f"{tablo}.recorded"},
        ).all()
        sabitli: set[str] = set()
        for capa in capalar:
            nesne = capa.nesne or ""
            kimlik = nesne.partition(":")[2]
            sabitli.add(kimlik)
            ozet = capa.ozet or {}
            if ozet.get("capa_surumu") != CAPA_SURUMU or not ozet.get("satir_sha256"):
                sonuc.eski += 1
                continue
            try:
                satir_id = uuid.UUID(kimlik)
            except ValueError:
                bozuk(nesne, "çapa nesnesi geçersiz")
                continue
            satir = (
                conn.execute(
                    text(f"SELECT {', '.join(columns)} FROM {tablo} WHERE id = :id"),
                    {"id": satir_id},
                )
                .mappings()
                .first()
            )
            sonuc.checked += 1
            if satir is None:
                bozuk(nesne, "satır silinmiş (zincirde çapası var)")
            elif row_anchor(tablo, satir) != ozet["satir_sha256"]:
                bozuk(nesne, "satır içeriği çapayla uyuşmuyor (değiştirilmiş)")
        idler = conn.execute(text(f"SELECT id FROM {tablo}")).scalars()
        for satir_id in idler:
            if str(satir_id) not in sabitli:
                sonuc.sabitsiz += 1
                bozuk(f"{tablo}:{satir_id}", "satırın denetim zincirinde çapası yok")
    return sonuc


class PgCallRecorder:
    """`ports.CallRecorder`: her kayıt kendi işleminde (model çağrısı başarısız olsa da kalır)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record_ai_call(self, row: Mapping[str, Any]) -> uuid.UUID:
        with self._engine.begin() as conn:
            return record_ai_call(conn, row)

    def record_tool_call(self, row: Mapping[str, Any]) -> uuid.UUID:
        with self._engine.begin() as conn:
            return record_tool_call(conn, row)
