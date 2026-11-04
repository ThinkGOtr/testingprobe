"""Asistan bütçe ve sayaç sorguları (AI-ASISTAN-PLANI §6.2, §6.4, §9; K3).

Harcama tek kaynaktan, `ai_call.maliyet`'ten okunur (append-only; REPLAY 0 yazar). Tavanlar v1'de
kod sabitidir (contracts/env.md): asistan günlük $10, kullanıcı günlük $1, kök soru başı $0.50
(otomatik/elle "Daha ayrıntılı" çocukları dahil). Genel günlük tavan `TP_DAILY_BUDGET_USD`.

- **Kök soru**: `ust_mesaj_id`'si boş asistan mesajı. `assistant_deep` hiç üst olmaz; ama sözlük/
  şablon cevabının "Daha ayrıntılı"sı (`assistant`) yeniden incelenebildiğinden zincir iki kademe
  olabilir: kök yukarı, harcama aşağı doğru özyinelemeli bulunur. Soru başı harcama = ağaçtaki
  mesajların `ai_call_id` kökleri + bu köklerin `parent_call_id` turları.
- **Kullanıcı günlük**: `ai_call.ek->>'kullanici_id'` (İlke VIII kişi bağı), UTC günü.
- **Asistan günlük**: `ai_call.amac IN ('assistant', 'assistant_deep')`, UTC günü.
- **Sayaçlar** `job` tablosundaki bitmemiş `assistant.answer` işlerinden (iptal edilmiş ama süren iş
  dahil): global sınır 2 × `TP_WORKER_ASISTAN_PARALEL`; kullanıcı başı yalnız `tetik='kullanici'`.
  Global sayım ve ekleme `global_kilit` altında yapılır; API POST ve otomatik yükseltme aynı kilidi
  transaction'ın İLK ifadesi olarak alır (tutarlı kilit sırası → deadlock yok).
- **Saatlik soru hakkı** mesaj tablosundan: kullanıcının `tetik='kullanici'` asistan mesajları, son
  60 dk, iptal/hata dahil; `assistant_deep` 2 sayılır, otomatik çocuklar sayılmaz.

`AsistanBudget` (geçide verilen bütçe; Şerit D2) aynı sorguları kullanır.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Final

from sqlalchemy import Connection, Engine, text

from tp_core.gateway.budget import Budget, InMemorySpendLedger
from tp_core.gateway.errors import BudgetExceeded
from tp_core.workflow.budget import daily_spend_usd

ASISTAN_GUNLUK_USD: Final = Decimal("10")
KULLANICI_GUNLUK_USD: Final = Decimal("1")
SORU_BASI_USD: Final = Decimal("0.50")
# Otomatik yükseltme ön koşulu: her kalan en az bu kadar (soğuk önekli Sonnet + yeniden isteme).
OTOMATIK_ASGARI_KALAN_USD: Final = Decimal("0.20")
# Kullanıcının günlük kalanı tavanın bu oranının altındaysa otomatik yerine düğme önerilir.
OTOMATIK_KULLANICI_ORAN: Final = Decimal("0.20")

SAATLIK_SORU: Final = 30
DERIN_AGIRLIK: Final = 2
KULLANICI_BEKLEYEN: Final = 1
VARSAYILAN_PARALEL: Final = 3

ASISTAN_IS_TURU: Final = "assistant.answer"
# `assistant.answer` işinin kuyruk zaman aşımı (yalnız emniyet; süre sınırı geçitte, 75 sn). Tek
# kaynak: API POST'u, otomatik yükseltme ve `@job_handler` kaydı buradan okur.
IS_ZAMAN_ASIMI_S: Final = 120
ASISTAN_AMACLARI: Final = ("assistant", "assistant_deep")
BITMEMIS_IS: Final = ("queued", "running", "retry")

# İki argümanlı advisory lock ad alanı (`workflow.jobs.IDEMPOTENCY_LOCK_NS` ile çakışmaz).
KILIT_NS: Final = 7_310_017
KILIT_ANAHTARI: Final = "asistan_global"


def _gun_araligi(gun: date | None = None) -> tuple[datetime, datetime]:
    gun = gun or datetime.now(UTC).date()
    bas = datetime.combine(gun, time.min, tzinfo=UTC)
    return bas, bas + timedelta(days=1)


def _dec(deger: object) -> Decimal:
    return Decimal(str(deger or 0))


# ------------------------------------------------------------------ harcama sorguları


def kok_mesaj_id(conn: Connection, mesaj_id: uuid.UUID) -> uuid.UUID | None:
    """Mesajın kök sorusu (`ust_mesaj_id` zincirinin başı); mesaj yoksa None."""
    return conn.execute(
        text(
            "WITH RECURSIVE yukari AS ("
            " SELECT id, ust_mesaj_id, 0 AS derinlik FROM asistan_mesaj WHERE id = :m"
            " UNION ALL"
            " SELECT a.id, a.ust_mesaj_id, y.derinlik + 1 FROM asistan_mesaj a"
            " JOIN yukari y ON a.id = y.ust_mesaj_id WHERE y.derinlik < 10) "
            "SELECT id FROM yukari ORDER BY derinlik DESC LIMIT 1"
        ),
        {"m": mesaj_id},
    ).scalar_one_or_none()


def soru_harcamasi_usd(conn: Connection, kok_id: uuid.UUID) -> Decimal:
    """Kök soru + alt mesajlarının (`ust_mesaj_id` ağacı) `ai_call` kökleri ve turları."""
    return _dec(
        conn.execute(
            text(
                "WITH RECURSIVE agac AS ("
                " SELECT id, ai_call_id, 0 AS derinlik FROM asistan_mesaj WHERE id = :k"
                " UNION ALL"
                " SELECT a.id, a.ai_call_id, g.derinlik + 1 FROM asistan_mesaj a"
                " JOIN agac g ON a.ust_mesaj_id = g.id WHERE g.derinlik < 10), "
                "kokler AS (SELECT ai_call_id FROM agac WHERE ai_call_id IS NOT NULL) "
                "SELECT COALESCE(SUM(maliyet), 0) FROM ai_call "
                "WHERE id IN (SELECT ai_call_id FROM kokler) "
                "   OR parent_call_id IN (SELECT ai_call_id FROM kokler)"
            ),
            {"k": kok_id},
        ).scalar_one()
    )


def kullanici_gunluk_usd(
    conn: Connection, kullanici_id: uuid.UUID, gun: date | None = None
) -> Decimal:
    bas, bit = _gun_araligi(gun)
    return _dec(
        conn.execute(
            text(
                "SELECT COALESCE(SUM(maliyet), 0) FROM ai_call "
                "WHERE olusturma >= :bas AND olusturma < :bit AND ek->>'kullanici_id' = :k"
            ),
            {"bas": bas, "bit": bit, "k": str(kullanici_id)},
        ).scalar_one()
    )


def asistan_gunluk_usd(conn: Connection, gun: date | None = None) -> Decimal:
    bas, bit = _gun_araligi(gun)
    return _dec(
        conn.execute(
            text(
                "SELECT COALESCE(SUM(maliyet), 0) FROM ai_call "
                "WHERE olusturma >= :bas AND olusturma < :bit "
                "AND amac IN ('assistant', 'assistant_deep')"
            ),
            {"bas": bas, "bit": bit},
        ).scalar_one()
    )


def genel_gunluk_sinir_usd() -> Decimal:
    from tp_core.config import get_settings

    return _dec(get_settings().daily_budget_usd)


@dataclass(frozen=True)
class Kalanlar:
    """Tavan − harcama (negatif olabilir). `soru` kök verilmediyse None."""

    kullanici: Decimal
    asistan: Decimal
    genel: Decimal
    soru: Decimal | None = None

    def asilan(self) -> str | None:
        """İlk tükenen kapsam (`kullanici` | `asistan` | `genel` | `soru`) ya da None."""
        for ad in ("soru", "kullanici", "asistan", "genel"):
            deger = getattr(self, ad)
            if deger is not None and deger <= 0:
                return ad
        return None


def kalanlar(
    conn: Connection, kullanici_id: uuid.UUID, *, kok_id: uuid.UUID | None = None
) -> Kalanlar:
    return Kalanlar(
        kullanici=KULLANICI_GUNLUK_USD - kullanici_gunluk_usd(conn, kullanici_id),
        asistan=ASISTAN_GUNLUK_USD - asistan_gunluk_usd(conn),
        genel=genel_gunluk_sinir_usd() - _dec(daily_spend_usd(conn)),
        soru=None if kok_id is None else SORU_BASI_USD - soru_harcamasi_usd(conn, kok_id),
    )


BUTCE_METINLERI: Final = {
    "soru": "Bu soru için ayrılan bütçe doldu.",
    "kullanici": "Bugünkü asistan kullanım bütçeniz doldu; yarın yeniden deneyin.",
    "asistan": "Asistanın bugünkü bütçesi doldu; yarın yeniden deneyin.",
    "genel": "Günlük AI bütçesi doldu; yarın yeniden deneyin.",
}


def butce_on_kontrol(
    conn: Connection, kullanici_id: uuid.UUID, *, kok_id: uuid.UUID | None = None
) -> str | None:
    """API POST ön kontrolü: tükenen kapsam (harcama ≥ tavan) ya da None."""
    return kalanlar(conn, kullanici_id, kok_id=kok_id).asilan()


# ------------------------------------------------------------------ sayaçlar ve kilit


def global_kilit(conn: Connection) -> None:
    """Asistan sayaçlarının transaction kilidi (API POST ve otomatik yükseltme; İLK ifade)."""
    conn.execute(
        text("SELECT pg_advisory_xact_lock(:ns, hashtext(:k))"),
        {"ns": KILIT_NS, "k": KILIT_ANAHTARI},
    )


def paralel() -> int:
    try:
        n = int(os.environ.get("TP_WORKER_ASISTAN_PARALEL", "") or VARSAYILAN_PARALEL)
    except ValueError:
        n = VARSAYILAN_PARALEL
    return max(1, n)


def global_sinir() -> int:
    return 2 * paralel()


def global_bekleyen(conn: Connection, *, haric_is: uuid.UUID | None = None) -> int:
    """Bitmemiş `assistant.answer` işleri (otomatik dahil); `haric_is` çağıranın kendi işi."""
    return int(
        conn.execute(
            text(
                "SELECT count(*) FROM job WHERE tur = :t AND durum IN ('queued','running','retry') "
                "AND (CAST(:h AS uuid) IS NULL OR id <> CAST(:h AS uuid))"
            ),
            {"t": ASISTAN_IS_TURU, "h": haric_is},
        ).scalar_one()
    )


def kullanici_bekleyen(conn: Connection, kullanici_id: uuid.UUID) -> int:
    """Kullanıcının bitmemiş, kendi tetiklediği (`tetik='kullanici'`) asistan işleri.

    Mesajı zaten son durumda (`done`/`error`) olan iş sayılmaz: cevap kendi transaction'ında
    yazılır, iş ise ayrı transaction'da `complete` olur; arada gelen yeni soru yanlışlıkla
    `bekleyen_var` almasın. `iptal` sayılır (iş tur başında durana dek kapanıyor; §9)."""
    return int(
        conn.execute(
            text(
                "SELECT count(*) FROM job j WHERE j.tur = :t "
                "AND j.durum IN ('queued','running','retry') "
                "AND j.yuk->>'kullanici_id' = :k AND j.yuk->>'tetik' = 'kullanici' "
                "AND NOT EXISTS (SELECT 1 FROM asistan_mesaj m "
                "WHERE m.id::text = j.yuk->>'mesaj_id' AND m.durum IN ('done','error'))"
            ),
            {"t": ASISTAN_IS_TURU, "k": str(kullanici_id)},
        ).scalar_one()
    )


def kullanici_kapanan(conn: Connection, kullanici_id: uuid.UUID) -> int:
    """`kullanici_bekleyen` içinde mesajı zaten `iptal` olan (durdurulmuş ama hâlâ kapanan) işler.

    Koşan cevap iptal edilince iş geçitte tur başında durur; o ana dek kullanıcı sayacında kalır
    (§9). API bu durumda 409 `bekleyen_var` metnini "kapanıyor" olarak açıklar."""
    return int(
        conn.execute(
            text(
                "SELECT count(*) FROM job j JOIN asistan_mesaj m "
                "ON m.id::text = j.yuk->>'mesaj_id' "
                "WHERE j.tur = :t AND j.durum IN ('queued','running','retry') "
                "AND j.yuk->>'kullanici_id' = :k AND j.yuk->>'tetik' = 'kullanici' "
                "AND m.durum = 'iptal'"
            ),
            {"t": ASISTAN_IS_TURU, "k": str(kullanici_id)},
        ).scalar_one()
    )


def saatlik_soru(conn: Connection, kullanici_id: uuid.UUID) -> int:
    """Son 60 dk'daki soru hakkı kullanımı (iptal/hata dahil; derin 2; otomatik hariç)."""
    return int(
        conn.execute(
            text(
                "SELECT COALESCE(SUM(CASE WHEN amac = 'assistant_deep' THEN :d ELSE 1 END), 0) "
                "FROM asistan_mesaj WHERE kullanici_id = :k AND rol = 'assistant' "
                "AND tetik = 'kullanici' AND olusturma > now() - interval '1 hour'"
            ),
            {"k": kullanici_id, "d": DERIN_AGIRLIK},
        ).scalar_one()
    )


def kalan_soru(conn: Connection, kullanici_id: uuid.UUID) -> int:
    return max(0, SAATLIK_SORU - saatlik_soru(conn, kullanici_id))


# ------------------------------------------------------------------ otomatik yükseltme


@dataclass(frozen=True)
class OtomatikKarar:
    """`yukselt` False ise `neden` (kayıt/ölçüm için sabit kod) ve düğme kartta kalır."""

    yukselt: bool
    neden: str | None = None


def otomatik_on_kosul(
    conn: Connection,
    kullanici_id: uuid.UUID,
    kok_id: uuid.UUID,
    *,
    mevcut_is: uuid.UUID | None = None,
    kalan: Kalanlar | None = None,
) -> OtomatikKarar:
    """§6.2 ön koşulları (hepsi). `global_kilit` alınmış transaction'da çağrılmalıdır.

    `mevcut_is`: üst mesajın hâlâ `running` görünen kendi işi global sayımdan düşülür.
    `kalan`: kilitten ÖNCE okunmuş bütçe kalanları (`kalanlar`; `ai_call` toplamları kilit
    altında koşmasın — global kilit her API POST'u bekletir). Verilmezse burada okunur.
    """
    k = kalan if kalan is not None else kalanlar(conn, kullanici_id, kok_id=kok_id)
    asgari = OTOMATIK_ASGARI_KALAN_USD
    if k.kullanici < asgari:
        return OtomatikKarar(False, "kullanici_kalani")
    if k.asistan < asgari:
        return OtomatikKarar(False, "asistan_kalani")
    if k.genel < asgari:
        return OtomatikKarar(False, "genel_kalani")
    if k.soru is not None and k.soru < asgari:
        return OtomatikKarar(False, "soru_kalani")
    if k.kullanici < KULLANICI_GUNLUK_USD * OTOMATIK_KULLANICI_ORAN:
        return OtomatikKarar(False, "kullanici_orani")
    if global_bekleyen(conn, haric_is=mevcut_is) >= global_sinir():
        return OtomatikKarar(False, "global_dolu")
    return OtomatikKarar(True)


# ------------------------------------------------------------------ geçit bütçesi


class AsistanBudget(Budget):
    """Geçide verilen bütçe (`build_gateway(budget=)`): her çağrıdan önce asistan tavanları.

    `check` kök soru, kullanıcı günlük, asistan günlük ve genel günlük tavanları `ai_call`'dan
    okur (koşan mesajın önceki turları dahil; `ai_call_id` iş başında yazılır). `charge` bir şey
    yazmaz: maliyet geçidin `ai_call` satırındadır. İş akışı tavanı asistanda kullanılmaz.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        kullanici_id: uuid.UUID,
        kok_id: uuid.UUID,
        genel_sinir_usd: Callable[[], Decimal] = genel_gunluk_sinir_usd,
    ) -> None:
        super().__init__(
            workflow_cap_usd=float(SORU_BASI_USD),
            daily_cap_usd=float(ASISTAN_GUNLUK_USD),
            ledger=InMemorySpendLedger(),
        )
        self._engine = engine
        self.kullanici_id = kullanici_id
        self.kok_id = kok_id
        self._genel_sinir = genel_sinir_usd

    def check(self, workflow_id: uuid.UUID | None, estimate_usd: float = 0.0) -> None:
        tahmin = _dec(estimate_usd)
        with self._engine.connect() as conn:
            olcumler = (
                ("soru başı", soru_harcamasi_usd(conn, self.kok_id), SORU_BASI_USD),
                (
                    "kullanıcı günlük",
                    kullanici_gunluk_usd(conn, self.kullanici_id),
                    KULLANICI_GUNLUK_USD,
                ),
                ("asistan günlük", asistan_gunluk_usd(conn), ASISTAN_GUNLUK_USD),
                ("günlük", _dec(daily_spend_usd(conn)), self._genel_sinir()),
            )
        for kapsam, harcanan, tavan in olcumler:
            if harcanan + tahmin >= tavan:
                raise BudgetExceeded(kapsam, float(harcanan), float(tavan))

    def charge(self, workflow_id: uuid.UUID | None, cost_usd: float) -> None:
        """Bilerek boş: maliyet `ai_call.maliyet`'e satırla birlikte yazılır."""
