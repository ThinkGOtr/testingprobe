"""Öneri motoru: "Öneri" düğmesinin kural tabanlı önerileri (AI-ASISTAN-PLANI §17; constitution
I, IX, XI).

Kullanıcı bir ekrandayken o ekranda, **kendi rolüyle şimdi yapması gereken** işleri görür. Liste
modelsizdir: `rules/assistant/oneriler.yaml` kuralları ekrandaki varlığın olgularıyla (`olgular`)
değerlendirilir; ücretsizdir, anında döner, model ve worker kapalıyken de çalışır ve `ai_call`
yazmaz. Hiçbir öneri kendiliğinden uygulanmaz; asistan Jira'ya yazmaz (taslağı kullanıcı açar).

- **Kural seti** (`kural_seti`): `oneriler.yaml` + `jira-taslaklari.yaml` + `rotalar.json`
  açılışta bir kez okunur ve doğrulanır. Bilinmeyen olgu/operatör/eylem/şablon/rota →
  `KuralHatasi` (sessizce atlanan kural yok). Sözleşmenin tamamı
  `tests/unit/gateway/test_rules_asistan.py`'de zorlanır.
- **Olgular** (`olgular`): kapalı liste (§17.2 olgu tablosu). Varlık türüne uymayan olgu dönmez;
  koşulda kullanılırsa kural eşleşmez. Varlık okuma kuralı `probe_get` ile aynıdır: detay uçlarının
  (`GET /requirements/{id}`, `/scripts/{id}`, `/runs/{id}`, `/failures/{id}`, `/bug-drafts/{id}`)
  hepsi tüm rollere açıktır; varlık yoksa `VarlikBulunamadi` (API 404).
- **Koşul** (`kosul_saglanir`): kapalı operatör kümesi (`_in`, `_esit`, `_gte`, `_lte`, `_var`,
  `_yok`), hepsi VE. İfade değerlendirme yoktur.
- **Metin** (`yer_doldur`): yalnız `yer_tutucu: true` olgular ve türevleri; tek geçişli güvenli
  değiştirme (`str.format` değil — değerdeki `{…}` yeniden açılmaz); çıktı düz metin.
- **Bağlantı** (`JiraBaglantisi`): "Jira'yı aç" adresini yalnız sunucu kurar; taslak metni URL'e
  konmaz. `jira_yorum`/`jira_kaydi` → kaydın gezinme adresi; `jira_taslak` → doğrulanmış
  `JIRA_CREATE_URL`, yoksa gerçek Jira'da `/secure/CreateIssue!default.jspa`, simülatörde yok.
- **Bastırma**: "Gizle" (`deger=-1`) yalnız o kullanıcıya, "Yaptım" (`deger=2`) tüm rollere; ikisi
  de varlık **aynı durumdayken** (`varlik_durumu`, sunucuda hesaplanır). "Yaptım" `tekrar_saat`
  dolunca yeniden gösterilir.
- **E1 sözleşmesi**: `oneri_gecerli_mi` / `oneri_baglami` mesaj ucunda `oneri_kural_id`'yi yeniden
  hesaplar (geçersizse 409 `oneri_gecersiz`); öneri bağlamı istemci metnine değil kurala dayanır.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote, urlsplit

import yaml
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from tp_core.workflow.service import Principal

log = logging.getLogger(__name__)

ROLLER: Final = ("analyst", "po", "engineer", "tester", "presenter")
OPERATORLER: Final = ("_in", "_esit", "_gte", "_lte", "_var", "_yok")
EYLEM_TURLERI: Final = ("rota", "jira_taslak", "jira_yorum", "jira_kaydi", "bilgi")
OLGU_TURLERI: Final = (
    "durum",
    "enum",
    "sayi",
    "oran",
    "bool",
    "anahtar",
    "kimlik",
    "metin_listesi",
)
# Serbest metin/kimlik taşıyan olgu hiçbir zaman yer tutucu olamaz (başlık, Jira özeti, adım adı).
SERBEST_METIN_TURLERI: Final = frozenset({"metin_listesi", "kimlik", "durum"})
VARLIK_TURLERI: Final = (
    "requirement",
    "consistency_finding",
    "test_case",
    "script",
    "run",
    "failure",
    "bug_draft",
)
GENEL: Final = "genel"
GERI_BILDIRIM_DEGERLERI: Final = frozenset({-1, 1, 2})
GIZLE, FAYDALI, YAPTIM = -1, 1, 2

# ASCII rakam: `\d` Unicode rakamlarını da kabul ederdi (§13 Jira anahtar atlatma).
JIRA_ANAHTARI: Final = re.compile(r"^[A-Z][A-Z0-9]+-[0-9]+$")
_YER_TUTUCU: Final = re.compile(r"\{([a-z_]+)\}")
_KEBAB: Final = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

FLAKY_PENCERE: Final = 10  # flaky_tekrar: aynı testin son N koşusu
# Son koşu yaşına sayılmayan iç tetikler (kırarak doğrulama ve yerel kontrol koşuları).
SON_KOSU_HARIC_TETIK: Final = ("break_verify", "local_check")

UYARI_NOTU: Final = "Bu bir öneridir; kaydı siz açarsınız."
SIM_BAGLANTI_YOK: Final = "Demo Jira'sında kayıt oluşturma sayfası yok"
JIRA_CREATE_YOLU: Final = "/secure/CreateIssue!default.jspa"

KURAL_DOSYASI: Final = "oneriler.yaml"
TASLAK_DOSYASI: Final = "jira-taslaklari.yaml"
ROTA_DOSYASI: Final = "rotalar.json"


class KuralHatasi(ValueError):
    """Kural dosyası sözleşmeye uymuyor (açılışta; sessizce atlanmaz)."""


class EkranBulunamadi(LookupError):
    """Rota `rotalar.json` kalıplarına inmiyor ya da ekran bu role kapalı (API 404)."""


class VarlikBulunamadi(LookupError):
    """Varlık yok, kimliği geçersiz ya da ekranın varlık türüyle uyuşmuyor (API 404)."""


class KuralBulunamadi(LookupError):
    """`kural_id` yüklü kurallarda yok (API 422)."""


class GecersizGeriBildirim(ValueError):
    """Geri bildirim gövdesi geçersiz (API 422); ileti sabit Türkçe metindir."""


def oneri_etkin() -> bool:
    """`TP_ASISTAN_ONERI` (varsayılan 1): 0 → öneri uçları ve düğme kapalı (§9 geri alma)."""
    deger = os.environ.get("TP_ASISTAN_ONERI", "1").strip().lower()
    return deger not in ("0", "false", "hayir", "hayır", "off", "no")


# ------------------------------------------------------------------ kural seti


@dataclass(frozen=True)
class Kosul:
    olgu: str
    op: str  # OPERATORLER
    deger: Any


@dataclass(frozen=True)
class Kural:
    id: str
    ekran: str
    varlik: str | None
    roller: frozenset[str]
    kosullar: tuple[Kosul, ...]
    oncelik: int
    baslik: str
    neden: str
    eylem: Mapping[str, Any]
    aciklama: str
    tekrar_saat: int | None
    yer_tutucular: frozenset[str]  # bu kuralın varlığında izinli adlar (olgu + türev)

    @property
    def eylem_turu(self) -> str:
        return str(self.eylem["tur"])


@dataclass(frozen=True)
class Taslak:
    id: str
    tur: str  # Task | Bug | Story | yorum
    ozet: str
    aciklama: str
    etiketler: tuple[str, ...]


@dataclass(frozen=True)
class Rota:
    kalip: str
    ekran: str
    varlik: str | None
    roller: frozenset[str] | None  # None = tüm roller
    desen: re.Pattern[str]

    def acabilir(self, rol: str) -> bool:
        return self.roller is None or rol in self.roller


@dataclass(frozen=True)
class KuralSeti:
    olgular: Mapping[str, Mapping[str, Any]]
    kurallar: tuple[Kural, ...]
    taslaklar: Mapping[str, Taslak]
    rotalar: tuple[Rota, ...]
    bos_ekranlar: frozenset[tuple[str, str]]
    _kimlik: Mapping[str, Kural] = field(default_factory=dict, repr=False)

    def kural(self, kural_id: str) -> Kural | None:
        return self._kimlik.get(kural_id)

    def rota(self, kalip: str) -> Rota | None:
        return next((r for r in self.rotalar if r.kalip == kalip), None)

    def ekran_kurallari(self, kalip: str, rol: str) -> list[Kural]:
        return [k for k in self.kurallar if k.ekran == kalip and rol in k.roller]


def anahtar_coz(anahtar: str) -> tuple[str, str] | None:
    """`po_bekleme_saat_gte` → (`po_bekleme_saat`, `_gte`); `durum_in` → (`durum`, `_in`)."""
    for op in OPERATORLER:
        if anahtar.endswith(op) and len(anahtar) > len(op):
            return anahtar[: -len(op)], op
    return None


def _kalip_deseni(kalip: str) -> re.Pattern[str]:
    if kalip == "/":
        return re.compile(r"^/$")
    parcalar = [
        "([^/]+)" if p.startswith(":") else re.escape(p) for p in kalip.strip("/").split("/")
    ]
    return re.compile("^/" + "/".join(parcalar) + "$")


def _yer_tutucu_adlari(
    olgular: Mapping[str, Mapping[str, Any]], varlik: str | None
) -> frozenset[str]:
    kapsam = varlik or GENEL
    out: set[str] = set()
    for ad, o in olgular.items():
        if kapsam in (o.get("varliklar") or ()) and o.get("yer_tutucu"):
            out.add(ad)
            out |= set(o.get("turevler") or {})
    return frozenset(out)


def _metin_denetle(etiket: str, metin: Any, izinli: frozenset[str]) -> str:
    if not isinstance(metin, str) or not metin.strip():
        raise KuralHatasi(f"{etiket}: boş metin")
    for ad in _YER_TUTUCU.findall(metin):
        if ad not in izinli:
            raise KuralHatasi(f"{etiket}: geçersiz yer tutucu {{{ad}}}")
    kalan = _YER_TUTUCU.sub("", metin)
    if "{" in kalan or "}" in kalan:
        raise KuralHatasi(f"{etiket}: biçimsiz süslü parantez")
    return metin


def _kosul_denetle(
    etiket: str,
    anahtar: str,
    deger: Any,
    olgular: Mapping[str, Mapping[str, Any]],
    kapsam: str,
) -> Kosul:
    cozulen = anahtar_coz(str(anahtar))
    if cozulen is None:
        raise KuralHatasi(f"{etiket}: bilinmeyen operatör {anahtar}")
    ad, op = cozulen
    olgu = olgular.get(ad)
    if olgu is None:
        raise KuralHatasi(f"{etiket}: bilinmeyen olgu {ad}")
    if kapsam not in (olgu.get("varliklar") or ()):
        raise KuralHatasi(f"{etiket}: {ad} olgusu {kapsam} için hesaplanmaz")
    tur = olgu["tur"]
    if op in ("_var", "_yok"):
        if deger is not True:
            raise KuralHatasi(f"{etiket}: {anahtar} yalnız true alır")
    elif op in ("_gte", "_lte"):
        if (
            tur not in ("sayi", "oran")
            or isinstance(deger, bool)
            or not isinstance(deger, int | float)
        ):
            raise KuralHatasi(f"{etiket}: {anahtar} sayısal olgu ve sayı ister")
    elif op == "_in":
        if tur not in ("durum", "enum") or not isinstance(deger, list) or not deger:
            raise KuralHatasi(f"{etiket}: {anahtar} dolu liste ve durum/enum olgusu ister")
        deger = tuple(deger)
    elif op == "_esit":
        if tur == "bool" and not isinstance(deger, bool):
            raise KuralHatasi(f"{etiket}: {anahtar} bool ister")
        if tur == "enum" and deger not in (olgu.get("degerler") or ()):
            raise KuralHatasi(f"{etiket}: {anahtar} geçersiz değer {deger!r}")
        if tur == "sayi" and (isinstance(deger, bool) or not isinstance(deger, int | float)):
            raise KuralHatasi(f"{etiket}: {anahtar} sayı ister")
        if tur in ("durum", "kimlik", "metin_listesi", "anahtar", "oran"):
            raise KuralHatasi(f"{etiket}: {anahtar} bu olguda eşitlik yok")
    return Kosul(ad, op, deger)


def _eylem_denetle(
    etiket: str,
    eylem: Any,
    kosullar: tuple[Kosul, ...],
    taslaklar: Mapping[str, Taslak],
    rotalar: Mapping[str, Rota],
    olgular: Mapping[str, Mapping[str, Any]],
    kapsam: str,
) -> Mapping[str, Any]:
    if not isinstance(eylem, Mapping) or eylem.get("tur") not in EYLEM_TURLERI:
        raise KuralHatasi(f"{etiket}: tek eylem ve bilinen tür ister")
    tur = eylem["tur"]
    if tur in ("jira_taslak", "jira_yorum"):
        sablon = taslaklar.get(str(eylem.get("sablon")))
        if sablon is None:
            raise KuralHatasi(f"{etiket}: bilinmeyen şablon {eylem.get('sablon')}")
        beklenen = ("yorum",) if tur == "jira_yorum" else ("Task", "Bug", "Story")
        if sablon.tur not in beklenen:
            raise KuralHatasi(f"{etiket}: şablon türü {sablon.tur} {tur} ile uyumsuz")
    if tur in ("jira_yorum", "jira_kaydi") and not any(
        k.olgu == "jira_key" and k.op == "_var" for k in kosullar
    ):
        raise KuralHatasi(f"{etiket}: {tur} bilinen anahtar ister (kosul jira_key_var: true)")
    if tur == "rota":
        hedef = rotalar.get(str(eylem.get("rota")))
        if hedef is None:
            raise KuralHatasi(f"{etiket}: eylem rotası {eylem.get('rota')} rotalar.json'da yok")
        if not isinstance(eylem.get("yetki"), Mapping) or not eylem["yetki"].get("uc"):
            raise KuralHatasi(f"{etiket}: rota eylemi yetki.uc ister")
        io = eylem.get("id_olgusu")
        if io is not None:
            o = olgular.get(str(io))
            if o is None or o.get("tur") != "kimlik" or kapsam not in (o.get("varliklar") or ()):
                raise KuralHatasi(f"{etiket}: id_olgusu {io} geçersiz")
        elif ":" in hedef.kalip and hedef.varlik != (None if kapsam == GENEL else kapsam):
            raise KuralHatasi(f"{etiket}: {hedef.kalip} kimliği {kapsam} varlığından gelmez")
    return dict(eylem)


def kural_seti_yukle(dizin: Path) -> KuralSeti:
    """`rules/assistant` dizinindeki üç dosyayı okur ve çalışma anı için doğrular."""
    belge = yaml.safe_load((dizin / KURAL_DOSYASI).read_text(encoding="utf-8")) or {}
    taslak_belge = yaml.safe_load((dizin / TASLAK_DOSYASI).read_text(encoding="utf-8")) or {}
    rota_belge = json.loads((dizin / ROTA_DOSYASI).read_text(encoding="utf-8"))

    rotalar = tuple(
        Rota(
            kalip=r["kalip"],
            ekran=r["ekran"],
            varlik=r.get("varlik"),
            roller=None if r.get("roller") is None else frozenset(r["roller"]),
            desen=_kalip_deseni(r["kalip"]),
        )
        for r in rota_belge["rotalar"]
    )
    rota_sozluk = {r.kalip: r for r in rotalar}

    olgular: dict[str, Mapping[str, Any]] = dict(belge.get("olgular") or {})
    for ad, o in olgular.items():
        if o.get("tur") not in OLGU_TURLERI:
            raise KuralHatasi(f"olgu {ad}: tür {o.get('tur')!r}")
        if o.get("yer_tutucu") and o["tur"] in SERBEST_METIN_TURLERI:
            raise KuralHatasi(f"olgu {ad}: serbest metin/kimlik olgusu yer tutucu olamaz")
        bilinmeyen_turev = set(o.get("turevler") or {}) - set(TUREVLER)
        if bilinmeyen_turev:
            raise KuralHatasi(f"olgu {ad}: hesaplanmayan türev {sorted(bilinmeyen_turev)}")
    bilinmeyen = set(olgular) - set(OLGU_HESAPLAYICILARI)
    if bilinmeyen:
        raise KuralHatasi(f"hesaplanmayan olgu tanımı: {sorted(bilinmeyen)}")

    taslaklar: dict[str, Taslak] = {}
    tum_yer_tutucular = frozenset().union(
        *(_yer_tutucu_adlari(olgular, v) for v in (*VARLIK_TURLERI, None))
    )
    for t in taslak_belge.get("taslaklar") or []:
        tid = str(t["id"])
        if tid in taslaklar:
            raise KuralHatasi(f"taslak {tid}: mükerrer")
        if t["tur"] not in ("Task", "Bug", "Story", "yorum"):
            raise KuralHatasi(f"taslak {tid}: tür {t['tur']!r}")
        if t.get("ozet"):
            _metin_denetle(f"taslak {tid}.ozet", t["ozet"], tum_yer_tutucular)
        _metin_denetle(f"taslak {tid}.aciklama", t["aciklama"], tum_yer_tutucular)
        taslaklar[tid] = Taslak(
            id=tid,
            tur=t["tur"],
            ozet=str(t.get("ozet") or ""),
            aciklama=t["aciklama"],
            etiketler=tuple(str(e) for e in t.get("etiketler") or ()),
        )

    kurallar: list[Kural] = []
    for k in belge.get("kurallar") or []:
        kid = str(k.get("id"))
        etiket = f"kural {kid}"
        if not _KEBAB.match(kid) or any(x.id == kid for x in kurallar):
            raise KuralHatasi(f"{etiket}: id tekil kebab-case değil")
        ekran, varlik = k.get("ekran"), k.get("varlik")
        rota = rota_sozluk.get(str(ekran))
        if rota is None:
            raise KuralHatasi(f"{etiket}: ekran {ekran} rotalar.json'da yok")
        if rota.varlik != varlik:
            raise KuralHatasi(f"{etiket}: varlık {varlik}, ekranınki {rota.varlik}")
        roller = k.get("roller") or []
        if not roller or not set(roller) <= set(ROLLER):
            raise KuralHatasi(f"{etiket}: roller {roller}")
        oncelik = k.get("oncelik")
        if not isinstance(oncelik, int) or isinstance(oncelik, bool) or not 0 <= oncelik <= 100:
            raise KuralHatasi(f"{etiket}: öncelik 0–100")
        tekrar = k.get("tekrar_saat")
        if tekrar is not None and (not isinstance(tekrar, int) or tekrar <= 0):
            raise KuralHatasi(f"{etiket}: tekrar_saat pozitif tam sayı")
        kosul = k.get("kosul")
        if not isinstance(kosul, Mapping) or not kosul:
            raise KuralHatasi(f"{etiket}: koşul boş")
        kapsam = varlik or GENEL
        kosullar = tuple(_kosul_denetle(etiket, a, d, olgular, kapsam) for a, d in kosul.items())
        izinli = _yer_tutucu_adlari(olgular, varlik)
        eylem = _eylem_denetle(
            etiket, k.get("eylem"), kosullar, taslaklar, rota_sozluk, olgular, kapsam
        )
        if eylem["tur"] in ("jira_taslak", "jira_yorum"):
            sablon = taslaklar[eylem["sablon"]]
            for alan in ("ozet", "aciklama"):
                if getattr(sablon, alan):
                    _metin_denetle(
                        f"{etiket}: şablon {sablon.id}.{alan}", getattr(sablon, alan), izinli
                    )
        kurallar.append(
            Kural(
                id=kid,
                ekran=str(ekran),
                varlik=varlik,
                roller=frozenset(roller),
                kosullar=kosullar,
                oncelik=oncelik,
                baslik=_metin_denetle(f"{etiket}.baslik", k.get("baslik"), izinli),
                neden=_metin_denetle(f"{etiket}.neden", k.get("neden"), izinli),
                eylem=eylem,
                aciklama=_metin_denetle(
                    f"{etiket}.aciklama", k.get("aciklama") or k.get("neden"), izinli
                ),
                tekrar_saat=tekrar,
                yer_tutucular=izinli,
            )
        )

    bos: set[tuple[str, str]] = set()
    for kayit in belge.get("bos_ekranlar") or []:
        for rol in kayit.get("roller") or []:
            bos.add((str(kayit["ekran"]), str(rol)))

    return KuralSeti(
        olgular=olgular,
        kurallar=tuple(kurallar),
        taslaklar=taslaklar,
        rotalar=rotalar,
        bos_ekranlar=frozenset(bos),
        _kimlik={k.id: k for k in kurallar},
    )


def kural_dizini() -> Path:
    from tp_core.gateway.config import find_rules_dir

    return find_rules_dir() / "assistant"


@lru_cache(maxsize=1)
def kural_seti() -> KuralSeti:
    """Süreç başına bir kez yüklenen kural seti (kural değişikliği yeniden başlatma ister)."""
    return kural_seti_yukle(kural_dizini())


def ekranda_kural_var(rota_kalibi: str, rol: str, *, kurallar: KuralSeti | None = None) -> bool:
    """(rota × rol) için en az bir kural var mı — statik; yoksa portal Öneri düğmesini gizler."""
    ks = kurallar or kural_seti()
    return any(k.ekran == rota_kalibi and rol in k.roller for k in ks.kurallar)


# ------------------------------------------------------------------ ekran ve varlık çözümü


@dataclass(frozen=True)
class Ekran:
    rota: Rota
    varlik_tur: str | None
    varlik_id: uuid.UUID | None


def _uuid(deger: Any) -> uuid.UUID | None:
    if deger is None or deger == "":
        return None
    if isinstance(deger, uuid.UUID):
        return deger
    try:
        return uuid.UUID(str(deger))
    except (ValueError, AttributeError, TypeError):
        raise VarlikBulunamadi("varlık kimliği geçersiz") from None


def rota_indirge(rota: str, *, kurallar: KuralSeti | None = None) -> tuple[Rota, str | None]:
    """İstemci rotası (`/gereksinimler/<id>?x#y` ya da kalıbın kendisi) → (`rotalar.json` kaydı,
    yoldaki id)."""
    ks = kurallar or kural_seti()
    yol = str(rota or "").split("?", 1)[0].split("#", 1)[0].strip()
    if len(yol) > 1:
        yol = yol.rstrip("/")
    if not yol.startswith("/"):
        raise EkranBulunamadi("rota tanınmıyor")
    dogrudan = ks.rota(yol)
    if dogrudan is not None:
        return dogrudan, None
    for r in ks.rotalar:
        m = r.desen.match(yol)
        if m is not None:
            return r, (m.group(1) if m.groups() else None)
    raise EkranBulunamadi("rota tanınmıyor")


def ekran_coz(
    kullanici: Principal,
    rota: str,
    varlik_tur: str | None,
    varlik_id: Any,
    *,
    kurallar: KuralSeti | None = None,
) -> Ekran:
    """Rota kalıba indirgenir, rolün açamadığı ekran reddedilir, varlık ekranın türüne bağlanır."""
    r, yol_id = rota_indirge(rota, kurallar=kurallar)
    if not r.acabilir(kullanici.rol):
        raise EkranBulunamadi("ekran bu role kapalı")
    if r.varlik is None:
        return Ekran(r, None, None)
    if varlik_tur not in (None, "", r.varlik):
        raise VarlikBulunamadi("varlık türü ekranla uyuşmuyor")
    vid = _uuid(varlik_id)
    yid = None if yol_id is None or yol_id.startswith(":") else _uuid(yol_id)
    if vid is not None and yid is not None and vid != yid:
        raise VarlikBulunamadi("varlık kimliği rotayla uyuşmuyor")
    kimlik = vid or yid
    if kimlik is None:
        raise VarlikBulunamadi("ekran varlık kimliği ister")
    return Ekran(r, r.varlik, kimlik)


# ------------------------------------------------------------------ olgular


def _saat(simdi: datetime, once: datetime | None) -> int | None:
    if once is None:
        return None
    if once.tzinfo is None:
        once = once.replace(tzinfo=UTC)
    return max(0, int((simdi - once).total_seconds() // 3600))


def _gecerli_anahtar(deger: Any) -> str | None:
    return deger if isinstance(deger, str) and JIRA_ANAHTARI.match(deger) else None


def _model(tur: str) -> Any:
    from tp_core import models as m

    return {
        "requirement": m.Requirement,
        "consistency_finding": m.ConsistencyFinding,
        "test_case": m.TestCase,
        "script": m.Script,
        "run": m.Run,
        "failure": m.Failure,
        "bug_draft": m.BugDraft,
    }[tur]


def _po_bekleme_baslangici(session: Session, req: Any) -> datetime | None:
    """`pending_po`'ya son giriş: denetim izindeki geçiş; yoksa son PO incelemesinin zamanı."""
    zaman = session.execute(
        text(
            "SELECT max(zaman) FROM audit_event WHERE eylem = 'requirement.transition' "
            "AND nesne = :nesne AND ozet->>'to' = 'pending_po'"
        ),
        {"nesne": f"requirement:{req.id}"},
    ).scalar_one_or_none()
    if zaman is not None:
        return zaman
    from tp_core.models import RequirementReview

    return session.scalar(
        select(func.max(RequirementReview.olusturma)).where(
            RequirementReview.requirement_id == req.id
        )
    )


def _requirement_olgulari(session: Session, req: Any, simdi: datetime) -> dict[str, Any]:
    from tp_core.features.requirements.serialize import po_status
    from tp_core.models import ConsistencyFinding, TestCase

    o: dict[str, Any] = {
        "durum": req.durum,
        "po_kanal": po_status(req)["kanal"],
        "ac_eksik": bool(req.ac_missing),
    }
    anahtar = _gecerli_anahtar(req.jira_key)
    if anahtar:
        o["jira_key"] = anahtar
    if req.durum == "pending_po":
        saat = _saat(simdi, _po_bekleme_baslangici(session, req))
        if saat is not None:
            o["po_bekleme_saat"] = saat
    # Karar bekleyen (kanıtı doğrulanmış, açık) bulgular; önceki turların kararlıları sayılmaz.
    o["acik_bulgu_sayisi"] = int(
        session.scalar(
            select(func.count()).where(
                ConsistencyFinding.requirement_id == req.id,
                ConsistencyFinding.durum == "open",
                ConsistencyFinding.kanit_dogrulandi.is_(True),
            )
        )
        or 0
    )
    sayilar = dict(
        session.execute(
            select(TestCase.durum, func.count())
            .where(TestCase.requirement_id == req.id, TestCase.durum.in_(("draft", "approved")))
            .group_by(TestCase.durum)
        ).all()
    )
    o["inceleme_bekleyen_case"] = int(sayilar.get("draft", 0))
    o["onayli_case"] = int(sayilar.get("approved", 0))
    return o


def _script_olgulari(session: Session, sc: Any) -> dict[str, Any]:
    from tp_core.models.codegen_feature import ScriptCodegen

    o: dict[str, Any] = {"durum": sc.durum}
    kayit = session.execute(
        select(
            ScriptCodegen.break_durum, ScriptCodegen.engel_turu, ScriptCodegen.yerel_kontrol
        ).where(ScriptCodegen.script_id == sc.id)
    ).first()
    if kayit is not None:  # onarım script'inde üretim kaydı yok → olgu yok
        break_durum, engel_turu, yerel = kayit
        o["kirarak_dogrulama"] = break_durum
        # Kod.tsx "Yeniden üret" ayrımıyla aynı (codegen/views.serialize `engel`/`yerel_sinif`).
        yk = yerel or {}
        o["defect_adayi"] = engel_turu == "defect_candidate" or (
            not yk.get("atlandi") and yk.get("sinif") == "defect_adayi"
        )
    return o


def _run_olgulari(run: Any) -> dict[str, Any]:
    o: dict[str, Any] = {"ci_sonuc": run.sonuc}
    adimlar = (run.artefaktlar or {}).get("basarisiz_adimlar")
    if isinstance(adimlar, list):
        o["basarisiz_adimlar"] = [str(a) for a in adimlar]
    return o


def _flaky_tekrar(session: Session, test_adi: str) -> int:
    """Aynı testin son `FLAKY_PENCERE` koşusunda kararsız (flaky) sonuç veren koşu sayısı.

    Kararsızlık iki yerden okunur: koşucunun `test_result.sonuc='flaky'` sonucu (yeniden denemede
    geçti) ya da triage'ın `failure.sinif='flaky'` sınıfı.
    """
    from tp_core.models import Failure, Run, TestResult

    kosular: dict[uuid.UUID, tuple[datetime, bool]] = {}
    sorgular = (
        select(TestResult.run_id, Run.olusturma, TestResult.sonuc == "flaky")
        .join(Run, Run.id == TestResult.run_id)
        .where(TestResult.test_adi == test_adi),
        select(Failure.run_id, Run.olusturma, Failure.sinif == "flaky")
        .join(Run, Run.id == Failure.run_id)
        .where(Failure.test_adi == test_adi),
    )
    for sorgu in sorgular:
        for run_id, zaman, flaky in session.execute(sorgu):
            onceki = kosular.get(run_id)
            kosular[run_id] = (zaman, bool(flaky) or bool(onceki and onceki[1]))
    son = sorted(kosular.values(), key=lambda z: z[0], reverse=True)[:FLAKY_PENCERE]
    return sum(1 for _, flaky in son if flaky)


def _failure_olgulari(session: Session, f: Any) -> dict[str, Any]:
    from tp_core.models import BugDraft
    from tp_core.models.bugs_feature import BugDraftEk

    o: dict[str, Any] = {
        "hata_sinifi": f.sinif,
        "onarim_durumu": f.oneri_durumu,
        "flaky_tekrar": _flaky_tekrar(session, f.test_adi),
    }
    # Karar bekleyen (`draft`) ilişkili taslak: doğrudan bağ ya da kardeş hata listesi.
    taslak_id = session.scalar(
        select(BugDraft.id)
        .outerjoin(BugDraftEk, BugDraftEk.bug_draft_id == BugDraft.id)
        .where(
            BugDraft.durum == "draft",
            or_(
                BugDraft.failure_id == f.id,
                BugDraftEk.ilgili_failure_ids.contains([str(f.id)]),
            ),
        )
        .order_by(BugDraft.olusturma.desc())
        .limit(1)
    )
    o["bug_taslagi_var"] = taslak_id is not None
    if taslak_id is not None:
        o["bug_taslagi_id"] = str(taslak_id)
    return o


def _bug_draft_olgulari(b: Any) -> dict[str, Any]:
    o: dict[str, Any] = {"durum": b.durum, "bulgu_kaynakli": b.finding_id is not None}
    anahtar = _gecerli_anahtar(b.jira_key)
    if anahtar:
        o["jira_key"] = anahtar
    return o


def _genel_olgular(session: Session, simdi: datetime) -> dict[str, Any]:
    from tp_core.config import get_settings
    from tp_core.models import Run
    from tp_core.workflow.budget import daily_spend_usd

    o: dict[str, Any] = {}
    tavan = float(get_settings().daily_budget_usd or 0)
    if tavan > 0:
        harcanan = float(daily_spend_usd(session.connection(), simdi.astimezone(UTC).date()))
        o["butce_orani"] = round(max(0.0, harcanan / tavan), 4)
    son_bitis = session.scalar(
        select(func.max(Run.bitis)).where(
            Run.bitis.is_not(None), Run.tetik.not_in(SON_KOSU_HARIC_TETIK)
        )
    )
    saat = _saat(simdi, son_bitis)
    if saat is not None:
        o["son_kosu_saat"] = saat
    return o


# Olgu → hesaplandığı varlıklar (oneriler.yaml `olgular` bu kümeyle aynı olmalı; test denetler).
OLGU_HESAPLAYICILARI: Final[Mapping[str, frozenset[str]]] = {
    "durum": frozenset({"requirement", "consistency_finding", "test_case", "script", "bug_draft"}),
    "po_bekleme_saat": frozenset({"requirement"}),
    "po_kanal": frozenset({"requirement"}),
    "ac_eksik": frozenset({"requirement"}),
    "acik_bulgu_sayisi": frozenset({"requirement"}),
    "inceleme_bekleyen_case": frozenset({"requirement"}),
    "onayli_case": frozenset({"requirement"}),
    "kirarak_dogrulama": frozenset({"script"}),
    "defect_adayi": frozenset({"script"}),
    "ci_sonuc": frozenset({"run"}),
    "basarisiz_adimlar": frozenset({"run"}),
    "hata_sinifi": frozenset({"failure"}),
    "onarim_durumu": frozenset({"failure"}),
    "flaky_tekrar": frozenset({"failure"}),
    "bug_taslagi_var": frozenset({"failure"}),
    "bug_taslagi_id": frozenset({"failure"}),
    "bulgu_kaynakli": frozenset({"bug_draft"}),
    "jira_key": frozenset({"requirement", "bug_draft"}),
    "butce_orani": frozenset({GENEL}),
    "son_kosu_saat": frozenset({GENEL}),
}


def olgular(
    session: Session,
    kullanici: Principal,
    varlik_tur: str | None,
    varlik_id: uuid.UUID | None,
    *,
    simdi: datetime | None = None,
) -> dict[str, Any]:
    """Ekrandaki varlığın (ya da varlıksız ekranın) olguları; kapalı liste, salt okuma.

    Varlık okuma kuralı `probe_get` ile aynıdır (detay uçları tüm rollere açık); rol oturumdan
    gelir ve bilinmeyen rol hiçbir şey okuyamaz. Varlık yoksa `VarlikBulunamadi`.
    """
    if kullanici.rol not in ROLLER:
        raise VarlikBulunamadi("rol tanınmıyor")
    simdi = simdi or datetime.now(UTC)
    if varlik_tur is None:
        return _genel_olgular(session, simdi)
    if varlik_tur not in VARLIK_TURLERI or varlik_id is None:
        raise VarlikBulunamadi("varlık türü veya kimliği geçersiz")
    obj = session.get(_model(varlik_tur), varlik_id)
    if obj is None:
        raise VarlikBulunamadi("varlık bulunamadı")
    if varlik_tur == "requirement":
        return _requirement_olgulari(session, obj, simdi)
    if varlik_tur == "script":
        return _script_olgulari(session, obj)
    if varlik_tur == "run":
        return _run_olgulari(obj)
    if varlik_tur == "failure":
        return _failure_olgulari(session, obj)
    if varlik_tur == "bug_draft":
        return _bug_draft_olgulari(obj)
    return {"durum": obj.durum}  # consistency_finding, test_case


def varlik_durumu(varlik_tur: str | None, olgu: Mapping[str, Any], simdi: datetime) -> str:
    """Bastırmanın bağlandığı "aynı durum" (sunucuda hesaplanır; istemci değeri yok sayılır).

    Durum makinesi olan varlıkta `durum`; koşuda sonuç; hatada sınıf + onarım durumu. Varlıksız
    (ekran düzeyi) öneride UTC gün: "Yaptım" ertesi gün kendiliğinden düşer.
    """
    if varlik_tur is None:
        return f"gun:{simdi.astimezone(UTC).date().isoformat()}"
    if varlik_tur == "run":
        return f"sonuc:{olgu.get('ci_sonuc')}"
    if varlik_tur == "failure":
        return f"sinif:{olgu.get('hata_sinifi')}:{olgu.get('onarim_durumu')}"
    return str(olgu.get("durum"))


# ------------------------------------------------------------------ koşul ve metin


def _var(deger: Any) -> bool:
    if deger is None or deger is False:
        return False
    if isinstance(deger, str | list | tuple | dict | set):
        return len(deger) > 0
    return True


def _sayi(deger: Any) -> bool:
    return isinstance(deger, int | float) and not isinstance(deger, bool)


def kosul_saglanir(kosullar: Iterable[Kosul], olgu: Mapping[str, Any]) -> bool:
    """Kapalı operatör kümesi, hepsi VE. Olgu yoksa yalnız `_yok` sağlanır."""
    for k in kosullar:
        deger = olgu.get(k.olgu)
        if k.op == "_var":
            ok = _var(deger)
        elif k.op == "_yok":
            ok = not _var(deger)
        elif deger is None:
            ok = False
        elif k.op == "_in":
            ok = isinstance(deger, str) and deger in k.deger
        elif k.op == "_esit":
            ok = (type(deger) is bool) == (type(k.deger) is bool) and deger == k.deger
        elif k.op == "_gte":
            ok = _sayi(deger) and deger >= k.deger
        elif k.op == "_lte":
            ok = _sayi(deger) and deger <= k.deger
        else:  # pragma: no cover — yüklemede reddedilir
            ok = False
        if not ok:
            return False
    return True


TUREVLER: Final[Mapping[str, Callable[[Mapping[str, Any]], Any]]] = {
    "po_bekleme_gun": lambda o: (
        max(1, int(o["po_bekleme_saat"]) // 24) if _sayi(o.get("po_bekleme_saat")) else None
    ),
    "butce_yuzde": lambda o: (
        round(float(o["butce_orani"]) * 100) if _sayi(o.get("butce_orani")) else None
    ),
    "son_kosu_gun": lambda o: (
        int(o["son_kosu_saat"]) // 24 if _sayi(o.get("son_kosu_saat")) else None
    ),
}


def _metin_degeri(deger: Any) -> str:
    if deger is None or isinstance(deger, bool):
        return ""
    if isinstance(deger, float):
        return str(int(deger)) if deger.is_integer() else f"{deger:.2f}"
    if isinstance(deger, int):
        return str(deger)
    if isinstance(deger, str) and JIRA_ANAHTARI.match(deger):
        return deger
    return ""  # yer tutucu yalnız sayı/oran/anahtar taşır; başka değer metne girmez


def yer_degerleri(olgu: Mapping[str, Any], izinli: Iterable[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for ad in izinli:
        deger = TUREVLER[ad](olgu) if ad in TUREVLER else olgu.get(ad)
        out[ad] = _metin_degeri(deger)
    return out


def yer_doldur(metin: str, degerler: Mapping[str, str]) -> str:
    """Tek geçişli güvenli yerleştirme: `{ad}` → değer; bilinmeyen/eksik ad → boş metin.

    `re.sub` değiştirilen metni yeniden taramaz: değerdeki `{…}` yer tutucu olarak açılmaz.
    `str.format` kullanılmaz (öznitelik/indeks erişimi ve biçim dili yok).
    """
    return _YER_TUTUCU.sub(lambda m: str(degerler.get(m.group(1), "")), metin)


# ------------------------------------------------------------------ Jira bağlantısı


def _koken(url: str) -> tuple[str, str, int | None] | None:
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        return None
    return p.scheme, p.hostname.lower(), port or (443 if p.scheme == "https" else 80)


@dataclass(frozen=True)
class JiraBaglantisi:
    """Jira'yı aç bağlantısının adresleri; yalnız sunucu kurar (§17.4)."""

    proje: str
    gezinme_koku: str | None  # JIRA_BROWSE_URL (gerçek Jira'da yoksa JIRA_BASE_URL)
    olusturma_adresi: str | None  # doğrulanmış JIRA_CREATE_URL
    simulator: bool

    def kayit_adresi(self, anahtar: str | None) -> str | None:
        if not self.gezinme_koku or not _gecerli_anahtar(anahtar):
            return None
        return f"{self.gezinme_koku}/browse/{quote(str(anahtar), safe='')}"

    def yeni_kayit_adresi(self) -> str | None:
        if self.olusturma_adresi:
            return self.olusturma_adresi
        if self.simulator or not self.gezinme_koku:
            return None
        return self.gezinme_koku + JIRA_CREATE_YOLU


def create_url_dogrula(deger: str | None, gezinme_koku: str | None, simulator: bool) -> str | None:
    """`JIRA_CREATE_URL`: `https` (simülatörde `http://127.0.0.1`/`localhost` de) ve kökeni gezinme
    adresiyle aynı; değilse yok sayılır + uyarı (değer kayda yazılmaz)."""
    deger = (deger or "").strip()
    if not deger:
        return None
    koken = _koken(deger)
    gezinme = _koken(gezinme_koku) if gezinme_koku else None
    yerel = koken is not None and koken[1] in ("127.0.0.1", "localhost")
    sema_uygun = koken is not None and (
        koken[0] == "https" or (simulator and koken[0] == "http" and yerel)
    )
    if not sema_uygun or gezinme is None or koken != gezinme:
        log.warning(
            "JIRA_CREATE_URL yok sayıldı: https (simülatörde http://127.0.0.1) olmalı ve kökeni "
            "JIRA_BROWSE_URL ile aynı olmalı"
        )
        return None
    return deger


@lru_cache(maxsize=1)
def jira_baglantisi() -> JiraBaglantisi:
    """Açılışta bir kez kurulur (ayar değişikliği yeniden başlatma ister)."""
    from tp_core.integrations.jira import get_jira_settings

    s = get_jira_settings()
    gezinme = (s.jira_browse_url or "").strip() or None
    # Simülatörün iç adresi (http://jira-sim:8090) tarayıcıdan açılmaz: bağlantı yalnız
    # JIRA_BROWSE_URL tanımlıyken kurulur. Gerçek Jira'da taban adres gezinme adresidir.
    if gezinme is None and not s.is_simulator:
        gezinme = s.jira_base_url
    if gezinme is not None and _koken(gezinme) is None:
        gezinme = None
    if gezinme is not None:
        gezinme = gezinme.rstrip("/")
    return JiraBaglantisi(
        proje=s.jira_project,
        gezinme_koku=gezinme,
        olusturma_adresi=create_url_dogrula(
            os.environ.get("JIRA_CREATE_URL"), gezinme, s.is_simulator
        ),
        simulator=s.is_simulator,
    )


# ------------------------------------------------------------------ kart üretimi


def _taslak(sablon: Taslak, degerler: Mapping[str, str], proje: str) -> dict[str, Any]:
    return {
        "proje": proje,
        "tur": sablon.tur,
        "ozet": yer_doldur(sablon.ozet, degerler),
        "aciklama": yer_doldur(sablon.aciklama, degerler),
        "etiketler": list(sablon.etiketler),
    }


def eylem_kur(
    kural: Kural,
    ekran: Ekran,
    olgu: Mapping[str, Any],
    degerler: Mapping[str, str],
    *,
    kurallar: KuralSeti,
    jira: JiraBaglantisi,
) -> dict[str, Any] | None:
    """Kartın eylemi; bağlantıyı yalnız sunucu kurar. Kurulamıyorsa (ör. hedef kimlik yok) None."""
    e = kural.eylem
    tur = kural.eylem_turu
    if tur == "bilgi":
        return {"tur": "bilgi"}
    if tur == "rota":
        hedef = str(e["rota"])
        if ":id" in hedef:
            kimlik = olgu.get(e["id_olgusu"]) if e.get("id_olgusu") else ekran.varlik_id
            if kimlik is None:
                return None
            hedef = hedef.replace(":id", quote(str(kimlik), safe=""))
        out: dict[str, Any] = {"tur": "rota", "rota": hedef}
        if e.get("capa"):
            out["capa"] = str(e["capa"])
        return out
    anahtar = _gecerli_anahtar(olgu.get("jira_key"))
    if tur == "jira_kaydi":
        if anahtar is None:
            return None
        out = {"tur": tur, "anahtar": anahtar, "not": UYARI_NOTU}
        baglanti = jira.kayit_adresi(anahtar)
        if baglanti:
            out["baglanti"] = baglanti
        return out
    sablon = kurallar.taslaklar[str(e["sablon"])]
    taslak = _taslak(sablon, degerler, jira.proje)
    if tur == "jira_yorum":
        if anahtar is None:
            return None
        out = {
            "tur": tur,
            "anahtar": anahtar,
            "taslak": taslak,
            "adim_notu": f"{anahtar} kaydını açın; metni yorum olarak yapıştırın.",
            "not": UYARI_NOTU,
        }
        baglanti = jira.kayit_adresi(anahtar)
    else:  # jira_taslak
        out = {
            "tur": tur,
            "taslak": taslak,
            "adim_notu": f"Proje: {jira.proje}, Tür: {sablon.tur} seçin; metni yapıştırın.",
            "not": UYARI_NOTU,
        }
        baglanti = jira.yeni_kayit_adresi()
        if baglanti is None and jira.simulator:
            out["baglanti_yok_nedeni"] = SIM_BAGLANTI_YOK
    if baglanti:
        out["baglanti"] = baglanti
    return out


def kart_kur(
    kural: Kural,
    ekran: Ekran,
    olgu: Mapping[str, Any],
    *,
    kurallar: KuralSeti,
    jira: JiraBaglantisi | None = None,
) -> dict[str, Any] | None:
    degerler = yer_degerleri(olgu, kural.yer_tutucular)
    eylem = eylem_kur(
        kural, ekran, olgu, degerler, kurallar=kurallar, jira=jira or jira_baglantisi()
    )
    if eylem is None:
        return None
    return {
        "kural_id": kural.id,
        "baslik": yer_doldur(kural.baslik, degerler),
        "neden": yer_doldur(kural.neden, degerler),
        "aciklama": yer_doldur(kural.aciklama, degerler),
        "oncelik": kural.oncelik,
        "eylem": eylem,
    }


# ------------------------------------------------------------------ bastırma


def _bastirmalar(
    session: Session,
    kullanici: Principal,
    adaylar: list[Kural],
    ekran: Ekran,
    durum: str,
    simdi: datetime,
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    """(gizlenen kural kimlikleri, "Yaptım" ile bastırılanlar → gösterim bilgisi)."""
    from tp_core.models import AppUser
    from tp_core.models.asistan import AsistanOneriGeriBildirim as G

    if not adaylar:
        return set(), {}
    tekrar = {k.id: k.tekrar_saat for k in adaylar}
    varlik_kosulu = (
        G.varlik_id.is_(None) if ekran.varlik_id is None else G.varlik_id == ekran.varlik_id
    )
    satirlar = session.execute(
        select(
            G.kural_id, G.kullanici_id, G.deger, G.jira_anahtari, G.olusturma, AppUser.kullanici_adi
        )
        .join(AppUser, AppUser.id == G.kullanici_id)
        .where(
            G.kural_id.in_(list(tekrar)),
            varlik_kosulu,
            G.varlik_durum == durum,
            G.deger.in_((GIZLE, YAPTIM)),
        )
        .order_by(G.olusturma.desc())
    ).all()
    gizli: set[str] = set()
    yapildi: dict[str, dict[str, Any]] = {}
    for kural_id, kullanici_id, deger, jira_anahtari, olusturma, kisi in satirlar:
        if deger == GIZLE:
            if kullanici_id == kullanici.id:
                gizli.add(kural_id)
            continue
        if kural_id in yapildi:
            continue  # en yenisi yeter (satırlar azalan sırada)
        saat = tekrar[kural_id]
        zaman = olusturma if olusturma.tzinfo else olusturma.replace(tzinfo=UTC)
        if saat is not None and simdi - zaman >= timedelta(hours=saat):
            continue  # hatırlatma kuralı: süre doldu, yeniden gösterilir
        yapildi[kural_id] = {
            "kisi": kisi,
            "jira_anahtari": _gecerli_anahtar(jira_anahtari),
            "zaman": zaman.isoformat(),
        }
    return gizli, yapildi


# ------------------------------------------------------------------ öneriler


# Öneri varlık türü → `probe_my_queue` kuyruk türü (yalnız adı farklı olan).
_KUYRUK_TURU: Final = {"test_case": "case"}


def diger_ekranlar(session: Session, kullanici: Principal, ekran: Ekran) -> dict[str, Any]:
    """§17.3 `*` özet: "Diğer ekranlarda sizi bekleyen N iş → Git" (`probe_my_queue` sayımı).

    Açık ekrandaki varlık kuyruktaysa sayıdan düşer; `rota` ilk başka işin ekranıdır. Rozete
    sayılmaz (portal). Yalnız SELECT; rolün kapısındaki varlıklar (`bekleyen_isler`).
    """
    from tp_core.features.assistant.tools.probe import bekleyen_isler, kuyrukta_mi

    toplam, isler = bekleyen_isler(session, kullanici.rol)
    kendi_tur = _KUYRUK_TURU.get(ekran.varlik_tur or "", ekran.varlik_tur)

    def buradaki(tur: str, kimlik: uuid.UUID) -> bool:
        return ekran.varlik_id is not None and tur == kendi_tur and kimlik == ekran.varlik_id

    if (
        ekran.varlik_id is not None
        and kendi_tur is not None
        and kuyrukta_mi(session, kullanici.rol, kendi_tur, ekran.varlik_id)
    ):
        toplam -= 1
    sayi = max(toplam, 0)
    rota = next((i.rota for i in isler if not buradaki(i.tur, i.id)), None)
    return {"sayi": sayi, "rota": rota if sayi else None}


def oneriler_ekran(
    session: Session,
    kullanici: Principal,
    ekran: Ekran,
    *,
    simdi: datetime | None = None,
    kurallar: KuralSeti | None = None,
    jira: JiraBaglantisi | None = None,
) -> dict[str, Any]:
    """Çözülmüş ekran için öneri sonucu (salt okuma; yalnız SELECT)."""
    ks = kurallar or kural_seti()
    simdi = simdi or datetime.now(UTC)
    olgu = olgular(session, kullanici, ekran.varlik_tur, ekran.varlik_id, simdi=simdi)
    adaylar = ks.ekran_kurallari(ekran.rota.kalip, kullanici.rol)
    sonuc: dict[str, Any] = {
        "rota_kalibi": ekran.rota.kalip,
        "ekranda_kural_var": bool(adaylar),
        "oneriler": [],
        "bastirilan": [],
        "diger_ekranlar": diger_ekranlar(session, kullanici, ekran),
        "hesaplandi": simdi.isoformat(),
    }
    eslesen = [k for k in adaylar if kosul_saglanir(k.kosullar, olgu)]
    durum = varlik_durumu(ekran.varlik_tur, olgu, simdi)
    gizli, yapildi = _bastirmalar(session, kullanici, eslesen, ekran, durum, simdi)
    kartlar: list[dict[str, Any]] = []
    for k in eslesen:
        if k.id in gizli:
            continue
        kart = kart_kur(k, ekran, olgu, kurallar=ks, jira=jira)
        if kart is None:
            continue
        if k.id in yapildi:
            sonuc["bastirilan"].append(
                {"kural_id": k.id, "baslik": kart["baslik"], **yapildi[k.id]}
            )
            continue
        kartlar.append(kart)
    kartlar.sort(key=lambda c: (-int(c["oncelik"]), str(c["kural_id"])))
    sonuc["oneriler"] = kartlar
    return sonuc


def oneriler(
    session: Session,
    kullanici: Principal,
    rota: str,
    varlik_tur: str | None,
    varlik_id: uuid.UUID | str | None,
    *,
    simdi: datetime | None = None,
    kurallar: KuralSeti | None = None,
    jira: JiraBaglantisi | None = None,
) -> dict[str, Any]:
    """`GET /assistant/suggestions` gövdesi: `{oneriler, ekranda_kural_var, bastirilan,
    diger_ekranlar, hesaplandi, rota_kalibi}`. Ekran tanınmıyorsa/role kapalıysa
    `EkranBulunamadi`, varlık yoksa `VarlikBulunamadi` (ikisi de API 404)."""
    ks = kurallar or kural_seti()
    ekran = ekran_coz(kullanici, rota, varlik_tur, varlik_id, kurallar=ks)
    return oneriler_ekran(session, kullanici, ekran, simdi=simdi, kurallar=ks, jira=jira)


def _baglam_ekrani(
    kullanici: Principal, baglam: Mapping[str, Any] | None, kurallar: KuralSeti
) -> Ekran:
    baglam = baglam or {}
    rota = baglam.get("rota_kalibi") or baglam.get("rota") or ""
    varlik = baglam.get("varlik") if isinstance(baglam.get("varlik"), Mapping) else {}
    return ekran_coz(kullanici, str(rota), varlik.get("tur"), varlik.get("id"), kurallar=kurallar)


def oneri_baglami(
    session: Session,
    kullanici: Principal,
    kural_id: str,
    baglam: Mapping[str, Any] | None,
    *,
    simdi: datetime | None = None,
    kurallar: KuralSeti | None = None,
) -> dict[str, Any] | None:
    """Öneriden açılan sohbetin bağlamı `{kural_id, baslik, neden, aciklama}`; öneri artık geçerli
    değilse (kural yok, rol dışı, ekran farklı, varlık yok, koşul sağlanmıyor) None.

    Metin kuraldan ve sunucudaki olgulardan yeniden üretilir; istemcinin metnine güvenilmez.
    "Gizle"/"Yaptım" bastırması geçerliliği etkilemez ("Neden? Sor" yine sorulabilir).
    """
    if not oneri_etkin():
        return None
    ks = kurallar or kural_seti()
    kural = ks.kural(str(kural_id))
    if kural is None or kullanici.rol not in kural.roller:
        return None
    try:
        ekran = _baglam_ekrani(kullanici, baglam, ks)
        if ekran.rota.kalip != kural.ekran:
            return None
        olgu = olgular(session, kullanici, ekran.varlik_tur, ekran.varlik_id, simdi=simdi)
    except (EkranBulunamadi, VarlikBulunamadi):
        return None
    if not kosul_saglanir(kural.kosullar, olgu):
        return None
    degerler = yer_degerleri(olgu, kural.yer_tutucular)
    return {
        "kural_id": kural.id,
        "baslik": yer_doldur(kural.baslik, degerler),
        "neden": yer_doldur(kural.neden, degerler),
        "aciklama": yer_doldur(kural.aciklama, degerler),
    }


def oneri_gecerli_mi(
    session: Session, kullanici: Principal, kural_id: str, baglam: Mapping[str, Any] | None
) -> bool:
    """`kural_id` önerisi bu kullanıcı ve ekran bağlamı için şu an geçerli mi.

    Mesaj ucu (Şerit E1) `oneri_kural_id` geldiğinde çağırır; False → 409 `oneri_gecersiz`.
    `baglam` §5.5 ekran bağlamıdır: `{rota_kalibi | rota, varlik: {tur, id}}`.
    """
    return oneri_baglami(session, kullanici, kural_id, baglam) is not None


# ------------------------------------------------------------------ geri bildirim


def geri_bildirim_yaz(
    session: Session,
    kullanici: Principal,
    kural_id: str,
    deger: int,
    varlik_id: uuid.UUID | None = None,
    jira_anahtari: str | None = None,
    *,
    simdi: datetime | None = None,
    kurallar: KuralSeti | None = None,
) -> dict[str, Any]:
    """Gizle / Faydalı / Yaptım kaydı. `varlik_durum` burada, sunucuda hesaplanır.

    Bilinmeyen kural → `KuralBulunamadi` (422); kuralın rolü dışında ya da erişilemeyen varlık →
    `VarlikBulunamadi` (404); geçersiz değer/anahtar → `GecersizGeriBildirim` (422).
    """
    from tp_core.models.asistan import AsistanOneriGeriBildirim

    ks = kurallar or kural_seti()
    kural = ks.kural(str(kural_id))
    if kural is None:
        raise KuralBulunamadi("bilinmeyen öneri kuralı")
    if deger not in GERI_BILDIRIM_DEGERLERI:
        raise GecersizGeriBildirim("deger -1, 1 ya da 2 olmalı")
    if kullanici.rol not in kural.roller:
        raise VarlikBulunamadi("öneri bu role ait değil")
    anahtar: str | None = None
    if jira_anahtari not in (None, ""):
        if deger != YAPTIM:
            raise GecersizGeriBildirim("Jira anahtarı yalnız 'Yaptım' ile verilir")
        anahtar = _gecerli_anahtar(jira_anahtari)
        if anahtar is None:
            raise GecersizGeriBildirim("Jira anahtarı biçimi geçersiz (ör. TPD-12)")
    simdi = simdi or datetime.now(UTC)
    if kural.varlik is None:
        varlik_id = None
    elif varlik_id is None:
        raise GecersizGeriBildirim("Bu öneri varlık kimliği ister")
    olgu = olgular(session, kullanici, kural.varlik, varlik_id, simdi=simdi)
    durum = varlik_durumu(kural.varlik, olgu, simdi)
    kayit = AsistanOneriGeriBildirim(
        kullanici_id=kullanici.id,
        kural_id=kural.id,
        varlik_id=varlik_id,
        varlik_durum=durum,
        deger=int(deger),
        jira_anahtari=anahtar,
    )
    session.add(kayit)
    session.flush()
    return {
        "id": str(kayit.id),
        "kural_id": kural.id,
        "deger": int(deger),
        "varlik_id": None if varlik_id is None else str(varlik_id),
        "varlik_durum": durum,
        "jira_anahtari": anahtar,
    }


# ------------------------------------------------------------------ sunucu önbelleği


# Önbellek ömrü portalın SSE sonrası tek yenilemesinden (`oneriAyar.olayGecikmeMs` = 5 sn) kısa
# olmalı: olaydan önce hesaplanmış sonuç, olaydan 5 sn sonraki `zorla` yenilemesinde artık
# önbellekte değildir (plan §17.6'daki 10 sn bu yenilemeyi eski rozetle bırakıyordu).
ONBELLEK_SURE_S: Final = 4.0


class Onbellek:
    """`(kullanici, rota, varlik)` için kısa ömürlü sonuç önbelleği (süreç içi, thread-safe)."""

    def __init__(
        self, sure_s: float = ONBELLEK_SURE_S, saat: Callable[[], float] = time.monotonic
    ) -> None:
        self.sure_s = sure_s
        self._saat = saat
        self._kayit: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
        self._kilit = threading.Lock()

    def al(self, anahtar: tuple[Any, ...]) -> dict[str, Any] | None:
        with self._kilit:
            kayit = self._kayit.get(anahtar)
            if kayit is None:
                return None
            if self._saat() - kayit[0] >= self.sure_s:
                del self._kayit[anahtar]
                return None
            return kayit[1]

    def koy(self, anahtar: tuple[Any, ...], deger: dict[str, Any]) -> None:
        with self._kilit:
            if len(self._kayit) > 2048:  # sınırsız büyümesin: süresi dolanları at
                simdi = self._saat()
                self._kayit = {a: k for a, k in self._kayit.items() if simdi - k[0] < self.sure_s}
            self._kayit[anahtar] = (self._saat(), deger)

    def temizle(self) -> None:
        with self._kilit:
            self._kayit.clear()


ONBELLEK: Final = Onbellek()
