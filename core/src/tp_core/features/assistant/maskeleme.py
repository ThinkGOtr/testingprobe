"""Asistanın maskeleyicisi ve mesaj başına tek oturumu (AI-ASISTAN-PLANI §5.0).

İşleyici mesaj başına bir kez `oturum = mesaj_oturumu(maskeleyici())` açar ve aynı oturumu geçide
(`run_agent(..., masking_session=oturum)`), `DataTools(..., session=oturum)`'a ve yeni araçların
sarmalayıcısına (`tools.base.AracBaglami.oturum`) verir. Böylece yer tutucular
(`<<PII_EMAIL_1>>`) soru, geçmiş, bağlam ve tüm araç sonuçları boyunca tekildir; son çıktının
maskesi aynı oturumla açılır.

Yapılandırma geçidinkinin aynısıdır (`gateway/factory.py`): `TP_PII_MASKING` +
`rules/pii-allowlist.yaml`.
Geçit kurulmasa da (sözlük/şablon/kapalı kip) maskeleyici kurulur.

**TCKN ve IBAN her zaman maskelenir** (specs/013-asistan-guvenlik §5.1): `TP_PII_MASKING`
kapalıyken de mesaj oturumu (`AsistanMaskeOturumu`) bu iki türü yer tutucuya çevirir; telefon ve
e-posta bayrağa bağlı kalır. Ayrıntılar sınıf belgesinde.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tp_core.gateway.config import GatewaySettings, find_rules_dir
from tp_core.gateway.factory import load_pii_allowlist
from tp_core.gateway.masking import (
    PLACEHOLDER_RE,
    RECOGNIZERS,
    MaskingSession,
    PiiMasker,
    Recognizer,
    iban_valid,
    tckn_valid,
)

# Bayrak kapalıyken de maskelenen türler (tanıyıcı sırası `RECOGNIZERS`'daki gibi: önce IBAN).
ZORUNLU_TURLER: Final = frozenset({"IBAN", "TCKN"})


def _iban_genis_gecerli(deger: str) -> bool:
    return iban_valid(re.sub(r"[\s-]", "", deger))


def _tckn_genis_gecerli(deger: str) -> bool:
    return tckn_valid(re.sub(r"[\s.-]", "", deger))


# Asistan oturumunun IBAN/TCKN tanıyıcıları geçidinkilerin (`RECOGNIZERS`) üst kümesidir: boşluk
# ya da tire ayraçlı yazımı da alır (`TR33-0006-1005-…`, `TR33  0006  1005…` çift boşluk,
# `100 000 001 46`); TCKN ayrıca noktalı 3-3-3-2 gruplamayla (`100.000.001.46`). Noktalı yazım
# yalnız bu gruplamada tanınır: ondalık/sürüm sayıları (`1.234.567,89`, `4.111.1111.1111`)
# karışmasın; aynı gruplamadaki bir IPv4 adresi sağlamayı (~%1) tutarsa maskelenir (yalnız
# maske, kullanıcı cevapta kendi yazdığını görür). Global tanıyıcılar değişmez (iş hattının
# maskeleme davranışı aynı kalır); genişletme yalnız asistan mesajında. TCKN'de sol sınır ayraçlı
# bir sayı dizisinin ortasından başlamayı da engeller.
_IBAN_GENIS: Final = Recognizer(
    "IBAN",
    re.compile(r"\bTR\d{2}(?:[ \-]{0,2}\d){22}(?![ \-]{0,2}\d)", re.IGNORECASE),
    _iban_genis_gecerli,
)
_TCKN_GENIS: Final = Recognizer(
    "TCKN",
    re.compile(
        r"(?<![\d.,+])(?<!\d[ \-])"
        r"(?:[1-9](?:[ \-]?\d){10}|[1-9]\d{2}\.\d{3}\.\d{3}\.\d{2})"
        r"(?![ \-]?\d)(?![.,]\d)"
    ),
    _tckn_genis_gecerli,
)
_ZORUNLU_TANIYICILAR: Final[tuple[Recognizer, ...]] = (_IBAN_GENIS, _TCKN_GENIS)
# Bayrak açıkken: genişletilmiş IBAN/TCKN + geçidin geri kalan tanıyıcıları (telefon, e-posta).
_TUM_TANIYICILAR: Final[tuple[Recognizer, ...]] = _ZORUNLU_TANIYICILAR + tuple(
    r for r in RECOGNIZERS if r.kind not in ZORUNLU_TURLER
)


@dataclass
class AsistanMaskeOturumu(MaskingSession):
    """Asistan mesaj oturumu: bayrak açıkken `MaskingSession`'ın tüm türleri; kapalıyken yalnız
    TCKN (sağlama) ve IBAN (mod-97) maskelenir. Her iki durumda IBAN/TCKN boşluk/tire ayraçlı
    yazımda da tanınır (`_IBAN_GENIS`, `_TCKN_GENIS`).

    Seçimin gerekçesi (bayrak kapalı kurulum):

    - `enabled` bayrağın değeridir (False kalır). `DataTools` maskelemeyi buradan okur: demo
      veritabanı sonuçları (sentetik) ve `result_digest` hesabı eskisi gibi maskesiz kalır;
      geçidin `ai_call` maskeleme farkı da `enabled=false` yazar, sayımlarda yalnız TCKN/IBAN
      görünür.
    - Soru, bağlam ve geçmiş ilk kullanıcı mesajındadır; geçit onu bu oturumla maskeler, model
      yalnız `<<PII_TCKN_n>>` görür. Son çıktı aynı oturumla açılır: kullanıcı kendi yazdığı
      değeri görür, kullanıcıya yer tutucu sızmaz. Yeni araçların sonuçları da
      (`AracSarmalayici`, her zaman `mask_text`) aynı türlerde maskelenir; alıntı doğrulaması
      `unmask` ile çalıştığı için etkilenmez.
    - Saklanan cevap yalnız müşteri verisi kurulumunda yeniden maskelenir (`sonislem.isle`,
      sözlük dalı); geçit çıktıyı zaten açmış olduğundan bu ikinci maskeleme değildir ve aynı
      oturum kullanıldığından değer modelin gördüğü yer tutucunun aynısını alır.
    - Girdideki hazır `<<PII_…>>` dizgisi bayrak açıkken olduğu gibi etkisizleştirilir: model
      çıktısı açılırken oturumdaki gerçek değer başka bir yere taşınamaz.
    """

    def mask_text(self, text: str) -> tuple[str, list[dict[str, str]]]:
        if not text:
            return text, []
        found: list[dict[str, str]] = []
        text = PLACEHOLDER_RE.sub(lambda m: m.group(0).replace("<<", "< <", 1), text)
        for rec in _TUM_TANIYICILAR if self.enabled else _ZORUNLU_TANIYICILAR:

            def repl(m: re.Match[str], rec: Recognizer = rec) -> str:
                value = m.group(0)
                if value in self.allowlist or value.lower() in self.allowlist:
                    return value
                if rec.validate is not None and not rec.validate(value):
                    return value
                placeholder = self._placeholder(rec.kind, value)
                found.append({"type": rec.kind, "placeholder": placeholder})
                return placeholder

            text = rec.pattern.sub(repl, text)
        return text, found


def maskeleyici(*, enabled: bool | None = None, rules_dir: Path | None = None) -> PiiMasker:
    """`PiiMasker(enabled=TP_PII_MASKING, allowlist=load_pii_allowlist(rules_dir))`."""
    if enabled is None:
        enabled = bool(GatewaySettings().pii_masking)
    return PiiMasker(enabled=enabled, allowlist=load_pii_allowlist(find_rules_dir(rules_dir)))


def mesaj_oturumu(masker: PiiMasker | None = None) -> MaskingSession:
    """Mesaj başına tek maskeleme oturumu (TCKN/IBAN her zaman maskeli; sınıf belgesi)."""
    m = masker or maskeleyici()
    return AsistanMaskeOturumu(enabled=bool(m.enabled), allowlist=m.allowlist)
