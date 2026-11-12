"""Review turu 2 (012 `review/tur2.md`) — oracle şeridi bulgularının regresyon testleri.

Her test bulgu kimliğini taşır (g2 = güvenlik + doğrulama bağımsızlığı, t2 = test + mimari,
u2 = ön yüz + analist/PO). Saf testler model ve DB kullanmaz; DB testleri gerçek Postgres ve sahte
`case_facts` modeliyle (`olgu_modeli`) ya da elle kontrol kaydıyla çalışır. Canlı model yok.
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError

from tp_core.audit import content_hash
from tp_core.features.karar_tablosu.hatalar import OracleKontrolSiniri
from tp_core.features.oracle import dogrulama as d
from tp_core.features.oracle import kapi, metrik, service
from tp_core.models import (
    AuditEvent,
    KararTablosu,
    MetamorfikIliski,
    MetamorfikTuretme,
    OracleIstisna,
    Review,
    TestCase,
    session_scope,
)
from tp_core.models.guard import allow_state_write

from ..cases.helpers import latest_cases, run_jobs
from . import tpd1
from .helpers import BASIT, basit_case, kayit_yaz, tablo_ekle, uyumsuz_ayrinti
from .test_oracle_db import UZUN_GEREKCE, _karar

T1, T2 = (
    d.Tablo(tpd1.tablo_id(n), f"T{n}", tpd1.TABLOLAR[n]["ad"], tpd1.TABLOLAR[n]) for n in (1, 2)
)
BASIT_T = d.Tablo("t", "T1", "Basit toplam", BASIT)


def _o(column: str, value: Any, field: str, quote: str) -> dict[str, Any]:
    return {"column": column, "value": value, "field": field, "quote": quote}


def _basit_olgular(case: dict[str, Any], *, toplam_alanlari: tuple[str, ...]) -> dict[str, Any]:
    """BASIT tablo için doğru olgular (adet S1 verisinden, toplam verilen alanlardan)."""
    adet = case["steps"][0]["data"].split()[-1]
    return {
        "groups": [
            {
                "table_ref": "T1",
                "inputs": [_o("adet", adet, "steps[0].data", f"adet {adet}")],
                "expected": [
                    _o("toplam", f"{int(adet) * 10}.00", a, f"{int(adet) * 10},00 TL")
                    for a in toplam_alanlari
                ],
            }
        ],
        "ignored": [],
    }


def _denetim(eylem: str) -> list[AuditEvent]:
    with session_scope() as s:
        rows = s.scalars(select(AuditEvent).where(AuditEvent.eylem == eylem)).all()
        s.expunge_all()
        return list(rows)


def _isler(engine: Engine, tur: str = service.CHECK_CASE_JOB) -> list[Any]:
    with engine.connect() as c:
        return c.execute(
            text(
                "SELECT id, durum, yuk, idempotency_key, sonuc, run_after, olusturma FROM job "
                "WHERE tur = :t ORDER BY olusturma, id"
            ),
            {"t": tur},
        ).all()


# ================================================================== g2 Y1 + Y14: tamlık denetimi


def test_g2_y1_birime_bitisik_yanlis_deger_uyumlu_cikmaz() -> None:
    """ "Toplam 45,00TL" (harfe bitişik) önceden sayılmıyordu: model yanlış değeri çıkarmazsa
    case `uyumlu` çıkıyordu. Artık sayılır → kapsanmayan sayı → `kismen`."""
    case = basit_case(toplam="30,00")
    case["steps"][1]["expected"] = "Toplam 30,00 TL; kampanyalı toplam 45,00TL"
    sonuc, ayr = d.degerlendir(
        case, [BASIT_T], _basit_olgular(case, toplam_alanlari=("expected_result",))
    )
    assert sonuc == d.KISMEN
    assert {"alan": "steps[1].expected", "alinti": "45,00", "tur": "sayi"} in ayr[
        "kapsanmayan_sayilar"
    ]
    assert "kapsanmayan_sayi" in ayr["kismen_nedeni"]


def test_g2_y1_kod_benzeri_belirtecler_sayilmaz() -> None:
    assert [m for m in d.sayi_gecisleri("P-001 S1 AC2 bayi1 Demo123!")] == []
    metin = "Toplam 45,00TL ve 330ml"
    assert [metin[a:b] for a, b in d.sayi_gecisleri(metin)] == ["45,00", "330"]


def test_g2_y1_yaziyla_sayi_karsilastirilmamis_sayilir() -> None:
    """ "kırk beş TL" sayı olarak okunamaz: uyumlu denmez, `yaziyla` olarak listelenir."""
    case = basit_case(toplam="30,00")
    case["expected_result"] = "Toplam 30,00 TL; indirimli toplam kırk beş TL"
    sonuc, ayr = d.degerlendir(
        case,
        [BASIT_T],
        _basit_olgular(case, toplam_alanlari=("steps[1].expected", "expected_result")),
    )
    assert sonuc == d.KISMEN
    assert {"alan": "expected_result", "alinti": "kırk beş", "tur": "yaziyla"} in ayr[
        "kapsanmayan_sayilar"
    ]
    metin = "bir uyarı görünür, bir adet bedava, yüzde on, altında"
    assert [metin[a:b] for a, b in d.yaziyla_sayilar(metin)] == ["bir", "on"]


def test_g2_y1_ignored_dolu_ise_en_iyi_kismen_ve_cikti_birimi_reddedilir() -> None:
    """`ignored` yanlış değeri saklayamaz: çıktı birimini (TL) ya da adını taşıyan alıntı
    gerekçesiyle reddedilir (sayısı kapsanmamış kalır); kabul edilen `ignored` kaydı da kontrolü en
    iyi `kismen` yapar."""
    case = basit_case(toplam="30,00")
    case["steps"][1]["expected"] = "Toplam 30,00 TL; kargo 45,00 TL; sayaç 3"
    olgu = _basit_olgular(case, toplam_alanlari=("steps[1].expected", "expected_result"))
    olgu["ignored"] = [
        {"field": "steps[1].expected", "quote": "kargo 45,00 TL", "reason": "kargo"},
        {"field": "steps[1].expected", "quote": "sayaç 3", "reason": "sayaç"},
    ]
    sonuc, ayr = d.degerlendir(case, [BASIT_T], olgu)
    assert sonuc == d.KISMEN
    assert ayr["reddedilen_yok_sayilan"] == [
        {
            "alan": "steps[1].expected",
            "alinti": "kargo 45,00 TL",
            "neden": "çıktı kolonunun birimini taşıyor (TL)",
        }
    ]
    assert [y["alinti"] for y in ayr["yok_sayilan"]] == ["sayaç 3"]
    assert ayr["kismen_nedeni"] == ["kapsanmayan_sayi", "yok_sayilan"]
    # Çıktı kolonunun adı da reddedilir.
    olgu["ignored"] = [{"field": "steps[1].expected", "quote": "toplam 30", "reason": "x"}]
    case["steps"][1]["expected"] = "Ara toplam 30 olur"
    _s, ayr = d.degerlendir(case, [BASIT_T], olgu)
    assert ayr["reddedilen_yok_sayilan"][0]["neden"] == "çıktı kolonunun adını taşıyor (toplam)"


def test_g2_y14_baslik_ve_veri_alanlari_cikarilan_girdiyle_celismez() -> None:
    """Başlık "4 adette" derken girdi "adet 3" çıkarılırsa başlıktaki sayı hiçbir doğrulanmış
    değerle eşleşmez → `celiski` → `kismen`. Aynı değeri yineleyen başlık sorun değildir."""
    case = basit_case(toplam="30,00")
    olgu = _basit_olgular(case, toplam_alanlari=("steps[1].expected", "expected_result"))
    assert d.degerlendir(case, [BASIT_T], olgu)[0] == d.UYUMLU  # başlık "3 adette … 30,00"
    case["title"] = "4 adette toplam 30,00 TL"
    sonuc, ayr = d.degerlendir(case, [BASIT_T], olgu)
    assert sonuc == d.KISMEN
    assert ayr["kapsanmayan_sayilar"] == [{"alan": "title", "alinti": "4", "tur": "celiski"}]
    case = basit_case(toplam="30,00") | {"test_data": [{"name": "adet", "value": "5"}]}
    sonuc, ayr = d.degerlendir(case, [BASIT_T], olgu)
    assert ayr["kapsanmayan_sayilar"] == [
        {"alan": "test_data[0].value", "alinti": "5", "tur": "celiski"}
    ]


# ================================================================== g2 Y4: kısmen nedeni, NFKC


def test_g2_y4_sifir_genislikli_karakter_alintiyi_dusurmez() -> None:
    """Alana gömülü sıfır genişlikli boşluk / NFKC farkı olguyu atamaz (önceden atılır → `kismen`
    → yüksek riskte bile onay açıktı)."""
    case = basit_case(toplam="30,00")
    case["expected_result"] = "Toplam 30,0​0 TL"
    case["steps"][1]["expected"] = "Toplam ３０,00 TL"  # tam genişlikli rakamlar (NFKC)
    sonuc, ayr = d.degerlendir(
        case,
        [BASIT_T],
        _basit_olgular(case, toplam_alanlari=("steps[1].expected", "expected_result")),
    )
    assert sonuc == d.UYUMLU and ayr["atilan_olgular"] == 0, ayr


def test_g2_y4_kismen_nedeni_listesi() -> None:
    olgu = tpd1.olgular(2)
    assert olgu is not None
    eksik = copy.deepcopy(olgu)
    eksik["groups"][0]["inputs"] = [
        o for o in eksik["groups"][0]["inputs"] if o["column"] == "adet"
    ]
    case = tpd1.ana_yol_cases()[1]
    _s, ayr = d.degerlendir(case, [T1], eksik)
    # Ara toplam olgusu yok: indirim/toplam hesaplanamaz (eksik girdi) ve 175,00 kapsanmaz.
    assert ayr["kismen_nedeni"] == ["eksik_girdi", "kapsanmayan_sayi"]
    assert d.gerekce_gerekir_mi(d.KISMEN, ayr)
    yalniz_eksik = {"gruplar": [{"karsilastirilamayan": [{"column": "indirim"}]}]}
    assert d.kismen_nedenleri(yalniz_eksik) == ["eksik_girdi"]
    assert not d.gerekce_gerekir_mi(d.KISMEN, yalniz_eksik)


def test_g2_y4_zorunlu_kapida_kismen_gerekce_ister(api: TestClient, kur) -> None:
    """Yüksek riskte nedeni yalnız `eksik_girdi` olmayan `kismen` gerekçesiz onaylanamaz (422
    `oracle_kontrolsuz`); gerekçe türü `kontrolsuz`. Yalnız eksik girdi → uyarıyla onay."""
    k = kur([basit_case(toplam="30,00")])
    c = latest_cases(api, k["rid"])[0]
    kayit_yaz(uuid.UUID(c["id"]), "kismen", {"gruplar": [], "yok_sayilan": [{"alinti": "x 1"}]})
    o = latest_cases(api, k["rid"])[0]["oracle"]
    assert (o["sonuc"], o["kismen_nedeni"]) == ("kismen", ["yok_sayilan"])
    r = _karar(api, c, karar="approve")
    assert r.status_code == 422 and r.json()["kod"] == "oracle_kontrolsuz", r.text
    r = _karar(
        api, c, karar="approve", oracle_istisna_gerekce=UZUN_GEREKCE, oracle_istisna_turu="uyumsuz"
    )
    assert r.status_code == 422 and r.json()["kod"] == "gecersiz_karar"
    r = _karar(
        api,
        c,
        karar="approve",
        oracle_istisna_gerekce=UZUN_GEREKCE,
        oracle_istisna_turu="kontrolsuz",
    )
    assert r.status_code == 200, r.text
    with session_scope() as s:
        [ist] = s.scalars(select(OracleIstisna)).all()
        assert ist.tur == "kontrolsuz"


def test_g2_y4_yalniz_eksik_girdi_kismen_uyariyla_onaylanir(api: TestClient, kur) -> None:
    k = kur([basit_case(toplam="30,00")])
    c = latest_cases(api, k["rid"])[0]
    ayr = {"gruplar": [{"karsilastirilamayan": [{"column": "toplam", "neden": "x"}]}]}
    kayit_yaz(uuid.UUID(c["id"]), "kismen", ayr)
    r = _karar(api, c, karar="approve")
    assert r.status_code == 200, r.text
    assert any("kısmen" in u for u in r.json()["uyarilar"])


# ================================================================== g2 Y2 + Y3: kalıcı taban


def test_ac_ref_iki_adimda_aklanamaz(api: TestClient, engine: Engine, kur) -> None:
    """g2 Y2: (1) AC1 → AC2 düzeltmesi doğru değerlerle onaylanır; (2) taslağa al; (3) yanlış
    değerli düzeltme. Önceden saklı ∪ gönderilen = {AC2} → kapsayan tablo yok → sessiz onay.
    Artık taban (AI özgün AC1 dahil) tabloyu kapsar: kontrol edilir ve 422."""
    k = kur([basit_case(toplam="30,00", risk="medium")], tablo_once=True, olgu_sayisi=20)
    c = latest_cases(api, k["rid"])[0]
    dogru = basit_case(toplam="30,00", risk="medium", acceptance_criteria_refs=["AC2"])
    r = _karar(api, c, karar="edit", icerik=dogru)
    assert r.status_code == 409, r.text  # düşürme → zorunlu → kayıt bekleniyor
    run_jobs(engine)
    r = _karar(api, c, karar="edit", icerik=dogru)
    assert r.status_code == 200, r.text
    c = latest_cases(api, k["rid"])[0]
    assert _karar(api, c, karar="reopen").status_code == 200
    c = latest_cases(api, k["rid"])[0]
    yanlis = basit_case(toplam="40,00", risk="medium", acceptance_criteria_refs=["AC2"])
    r = _karar(api, c, karar="edit", icerik=yanlis)
    assert r.status_code == 409, r.text
    [is_] = [j for j in _isler(engine) if j.durum == "queued"]
    assert is_.yuk["ac_refs"] == ["AC1", "AC2"]  # taban ∪ gönderilen
    run_jobs(engine)
    r = _karar(api, c, karar="edit", icerik=yanlis)
    assert r.status_code == 422 and r.json()["kod"] == "oracle_uyumsuz", r.text
    ev = _denetim("oracle.dusurme")[-1]
    assert ev.ozet["ac_refs"]["taban"] == ["AC1", "AC2"] and ev.ozet["engellendi"] is True
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(c["id"]))
        assert service.tabanlar(s, [tc])[tc.id].ac_refs == {"AC1", "AC2"}


def test_turetilen_case_riski_iki_adimda_dusmez(api: TestClient, engine: Engine, kur) -> None:
    """g2 Y3: türetilmiş (AI dışı) case'te kaynak case'in içeriği "özgün" sayılır. Kaynak yüksek
    riskli; türetilen orta riskli yazılmış: kapı yine zorunlu. (1) doğru değerle riski düşük
    yapıp onayla, (2) taslağa al, (3) yanlış değer → 422 (önceden uyarıyla onay)."""
    k = kur(
        [
            basit_case(toplam="30,00", risk="high"),
            basit_case(adet=6, toplam="60,00", risk="medium"),
        ],
        tablo_once=True,
        olgu_sayisi=30,
    )
    cases = latest_cases(api, k["rid"])
    kaynak, turev = cases[0], cases[1]
    with session_scope() as s:
        s.execute(
            text("UPDATE test_case SET ai_generated = false WHERE id = :i"), {"i": turev["id"]}
        )
        iliski = MetamorfikIliski(
            requirement_id=k["rid"], sira_no=1, icerik={}, icerik_hash=content_hash({})
        )
        s.add(iliski)
        s.flush()
        s.add(
            MetamorfikTuretme(
                iliski_id=iliski.id,
                kaynak_case_id=uuid.UUID(kaynak["id"]),
                turetilen_case_id=uuid.UUID(turev["id"]),
                sonuc="turetildi",
            )
        )
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(turev["id"]))
        taban = service.tabanlar(s, [tc])[tc.id]
        assert taban.yuksek and "high" in taban.riskler
    dusuk = basit_case(adet=6, toplam="60,00", risk="low")
    turev = latest_cases(api, k["rid"])[1]
    r = _karar(api, turev, karar="edit", icerik=dusuk)
    if r.status_code == 409:
        run_jobs(engine)
        r = _karar(api, turev, karar="edit", icerik=dusuk)
    assert r.status_code == 200, r.text
    assert _denetim("oracle.dusurme")[-1].ozet["risk"]["taban"] == ["high", "medium"]
    turev = latest_cases(api, k["rid"])[1]
    assert _karar(api, turev, karar="reopen").status_code == 200
    turev = latest_cases(api, k["rid"])[1]
    yanlis = basit_case(adet=6, toplam="70,00", risk="low")
    r = _karar(api, turev, karar="edit", icerik=yanlis)
    assert r.status_code == 409, r.text  # zorunlu: kayıt bekleniyor (önceden düşük → serbest)
    run_jobs(engine)
    r = _karar(api, turev, karar="edit", icerik=yanlis)
    assert r.status_code == 422 and r.json()["kod"] == "oracle_uyumsuz", r.text


# ================================================================== g2 Y5: geçici neden


def test_g2_y5_gecici_neden_onbellek_sayilmaz(api: TestClient, engine: Engine, kur) -> None:
    """`cagri_hatasi` / `replay_miss` kaydı gösterilir ama yeniden kontrolü engellemez: gereksinim
    işi ve kapı yeni kontrol açar (hız sınırıyla)."""
    k = kur([basit_case(toplam="30,00", risk="low")], tablo_once=True, olgu_sayisi=10)
    run_jobs(engine)
    c = latest_cases(api, k["rid"])[0]
    kayit_yaz(
        uuid.UUID(c["id"]),
        "kontrol_edilemedi",
        {"gruplar": [], "neden": service.NEDEN_CAGRI_HATASI},
    )
    c = latest_cases(api, k["rid"])[0]
    assert (c["oracle"]["sonuc"], c["oracle"]["neden"]) == ("kontrol_edilemedi", "cagri_hatasi")
    with session_scope() as s:
        service.gereksinim_kontrolu_kuyruga_al(s, k["rid"], "test")
    run_jobs(engine)
    c = latest_cases(api, k["rid"])[0]
    assert (c["oracle"]["sonuc"], c["oracle"]["neden"]) == ("uyumlu", None)


def test_g2_y5_kapi_gecici_kayitta_yeniden_kontrol_ister(
    api: TestClient, engine: Engine, kur
) -> None:
    k = kur([basit_case(toplam="30,00", risk="high")], tablo_once=True, olgu_sayisi=10)
    run_jobs(engine)
    c = latest_cases(api, k["rid"])[0]
    kayit_yaz(
        uuid.UUID(c["id"]), "kontrol_edilemedi", {"gruplar": [], "neden": service.NEDEN_REPLAY_MISS}
    )
    once = len(_isler(engine))
    r = _karar(api, c, karar="approve")
    assert r.status_code == 422 and r.json()["kod"] == "oracle_kontrolsuz"
    assert len(_isler(engine)) == once + 1  # ayrı işlemde kuyruğa alındı
    run_jobs(engine)
    r = _karar(api, latest_cases(api, k["rid"])[0], karar="approve")
    assert r.status_code == 200, r.text


# ================================================================== g2 Y6 + t2 N10: hız sınırı


def test_g2_y6_hiz_siniri_her_kaynakta(api: TestClient, engine: Engine, kur) -> None:
    """Sınır `kontrol_kuyruga_al`'dadır: kapı, istek ve sistem işleri aynı sayaca takılır; var
    olan anahtarın işi sınıra takılmaz; sistem yolu sessizce atlar."""
    k = kur([basit_case(toplam="30,00", risk="low")])
    c = latest_cases(api, k["rid"])[0]
    cid = uuid.UUID(c["id"])
    with session_scope() as s:
        for n in range(service.DAKIKA_SINIRI_CASE):
            service.kontrol_kuyruga_al(s, cid, f"h{n}", idempotency_key=f"t:{n}")
    with session_scope() as s:
        assert service.kontrol_kuyruga_al(s, cid, "h0", idempotency_key="t:0") is not None
        assert service.kontrol_kuyruga_al(s, cid, "hx", sinir_hatasi=False) is None
        with pytest.raises(OracleKontrolSiniri):
            service.kontrol_kuyruga_al(s, cid, "hy")
    r = api.post(f"/cases/{c['id']}/oracle-check", json={"icerik": basit_case(adet=9)})
    assert r.status_code == 429 and r.json()["kod"] == "oracle_kontrol_siniri"


def test_g2_y6_kapi_409_yolu_sinirli(api: TestClient, engine: Engine, kur) -> None:
    """Önceden kapının 409 yolu sınırsız iş (model çağrısı) açıyordu."""
    k = kur([basit_case(toplam="30,00", risk="high")])
    c = latest_cases(api, k["rid"])[0]
    cid = uuid.UUID(c["id"])
    with session_scope() as s:
        for n in range(service.DAKIKA_SINIRI_CASE):
            service.kontrol_kuyruga_al(s, cid, f"h{n}", idempotency_key=f"t:{n}")
    r = _karar(api, c, karar="approve")
    assert r.status_code == 429 and r.json()["kod"] == "oracle_kontrol_siniri", r.text


def test_g2_y6_kullanici_basina_sinir(api: TestClient, engine: Engine, kur) -> None:
    k = kur([basit_case(toplam=f"{n * 10},00", adet=n, risk="low") for n in range(1, 5)])
    cases = latest_cases(api, k["rid"])
    uid = k["analist"].id
    with session_scope() as s:
        for n in range(service.DAKIKA_SINIRI_KULLANICI):
            cid = uuid.UUID(cases[n % 4]["id"])
            with allow_state_write():
                s.execute(
                    text("INSERT INTO job (tur, yuk) VALUES (:t, CAST(:y AS jsonb))"),
                    {
                        "t": service.CHECK_CASE_JOB,
                        "y": f'{{"case_id": "{uuid.uuid4()}", "requirement_id": "{uuid.uuid4()}", '
                        f'"isteyen_id": "{uid}"}}',
                    },
                )
        with pytest.raises(OracleKontrolSiniri, match="Siz için"):
            service.kontrol_kuyruga_al(s, cid, "yeni", isteyen_id=uid)


def test_t2_n10_job_ifade_indeksleri_var(engine: Engine) -> None:
    with engine.connect() as c:
        adlar = set(
            c.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'job'")).scalars()
        )
    assert {"job_oracle_case_ix", "job_oracle_gereksinim_ix", "job_oracle_isteyen_ix"} <= adlar


# ================================================================== g2 Y9 + S1/Y11: damga, istisna


def test_g2_y9_gorulen_kayit_damgasi_degistiyse_409(api: TestClient, kur) -> None:
    k = kur([basit_case(toplam="40,00")])
    c = latest_cases(api, k["rid"])[0]
    cid = uuid.UUID(c["id"])
    kayit_yaz(cid, "uyumsuz", uyumsuz_ayrinti(str(k["tid"])))
    damga = latest_cases(api, k["rid"])[0]["oracle"]["damga"]
    assert damga != "yok"
    kayit_yaz(cid, "uyumsuz", uyumsuz_ayrinti(str(k["tid"]), "45.00"))  # yeniden hesaplandı
    govde = {
        "karar": "approve",
        "oracle_istisna_gerekce": UZUN_GEREKCE,
        "oracle_istisna_turu": "uyumsuz",
    }
    r = _karar(api, c, **govde, oracle_kayit_damgasi=damga)
    assert r.status_code == 409 and r.json()["kod"] == "oracle_kayit_degisti", r.text
    yeni = latest_cases(api, k["rid"])[0]["oracle"]["damga"]
    assert yeni != damga
    r = _karar(api, c, **govde, oracle_kayit_damgasi=yeni)
    assert r.status_code == 200, r.text


def test_g2_y9_gerekce_varsa_tur_zorunlu(api: TestClient, kur) -> None:
    k = kur([basit_case(toplam="40,00")])
    c = latest_cases(api, k["rid"])[0]
    kayit_yaz(uuid.UUID(c["id"]), "uyumsuz", uyumsuz_ayrinti(str(k["tid"])))
    r = _karar(api, c, karar="approve", oracle_istisna_gerekce=UZUN_GEREKCE)
    assert r.status_code == 422 and r.json()["kod"] == "gecersiz_karar"
    assert "oracle_istisna_turu" in r.json()["detail"]


def test_g2_y11_saklanan_istisnanin_yeniden_kullanimi_iz_birakir(api: TestClient, kur) -> None:
    """S1 (ürün sahibi): aynı tür + içerik + tablo kümesiyle verilmiş geçerli istisna yeniden
    gerekçe istemez; `oracle.exception_reused` denetimi ve review ölçülerinde `istisna_id`."""
    k = kur([basit_case(toplam="40,00")])
    c = latest_cases(api, k["rid"])[0]
    cid = uuid.UUID(c["id"])
    kayit_yaz(cid, "uyumsuz", uyumsuz_ayrinti(str(k["tid"])))
    r = _karar(
        api, c, karar="approve", oracle_istisna_gerekce=UZUN_GEREKCE, oracle_istisna_turu="uyumsuz"
    )
    assert r.status_code == 200, r.text
    c = latest_cases(api, k["rid"])[0]
    assert c["oracle"]["istisna"]["gecerli"] is True
    with session_scope() as s:
        [ist] = s.scalars(select(OracleIstisna)).all()
        ist_id = str(ist.id)
    assert c["oracle"]["istisna"]["id"] == ist_id
    assert _karar(api, c, karar="reopen").status_code == 200
    c = latest_cases(api, k["rid"])[0]
    r = _karar(api, c, karar="approve")
    assert r.status_code == 200, r.text
    [ev] = _denetim("oracle.exception_reused")
    assert ev.ozet["istisna_id"] == ist_id and ev.ozet["tur"] == "uyumsuz"
    with session_scope() as s:
        olculer = [
            rv.duzeltme_olculeri or {}
            for rv in s.scalars(
                select(Review).where(Review.nesne_id == cid, Review.karar == "approve")
            )
        ]
    assert [o.get("oracle_istisna_id") for o in olculer] == [ist_id, ist_id]
    assert [bool(o.get("oracle_istisna_yeniden")) for o in olculer] == [False, True]


def test_s1_istisna_gecerli_tur_ve_tablo_kumesine_bagli(api: TestClient, kur) -> None:
    """`istisna.gecerli` kaydın gerektirdiği türe de bakar: `kontrolsuz` istisnası `uyumsuz`
    kayıt için geçerli gösterilmez."""
    k = kur([basit_case(toplam="40,00")])
    c = latest_cases(api, k["rid"])[0]
    cid = uuid.UUID(c["id"])
    kayit_yaz(cid, "kontrol_edilemedi", {"gruplar": []})
    assert (
        _karar(
            api,
            c,
            karar="approve",
            oracle_istisna_gerekce=UZUN_GEREKCE,
            oracle_istisna_turu="kontrolsuz",
        ).status_code
        == 200
    )
    kayit_yaz(cid, "uyumsuz", uyumsuz_ayrinti(str(k["tid"])))
    ist = latest_cases(api, k["rid"])[0]["oracle"]["istisna"]
    assert (ist["tur"], ist["gecerli"]) == ("kontrolsuz", False)


# ================================================================ t2 N8 / g2 Y12: tek tablo kümesi


def test_t2_n8_ayni_hash_tek_tablo_kumesiyle_degerlendirilir(
    api: TestClient, engine: Engine, kur
) -> None:
    """Kapı ve `karar_sonrasi` aynı `(case, hash)`'i aynı tablo kümesiyle (taban ∪ içerik)
    değerlendirir: karşılıklı geçersizleştirme / ikinci model çağrısı yok."""
    k = kur([basit_case(toplam="30,00", risk="low")], tablo_once=True, olgu_sayisi=20)
    run_jobs(engine)
    c = latest_cases(api, k["rid"])[0]
    yeni = basit_case(adet=4, toplam="40,00", risk="low", acceptance_criteria_refs=["AC2"])
    r = api.post(f"/cases/{c['id']}/oracle-check", json={"icerik": yeni})
    assert r.status_code == 202
    run_jobs(engine)
    istek_sayisi = len(k["provider"].requests)
    assert _karar(api, c, karar="edit", icerik=yeni).status_code == 200
    run_jobs(engine)
    assert len(k["provider"].requests) == istek_sayisi  # karar_sonrasi önbellekten
    c = latest_cases(api, k["rid"])[0]
    assert c["oracle"]["sonuc"] == "uyumlu"
    o = api.get(f"/cases/{c['id']}/oracle").json()
    assert [t["id"] for t in o["kapsayan_tablolar"]] == [str(k["tid"])]


# ================================================================== g2 Y13 / t2 N6: birleştirici


def test_t2_n6_birlestirici_yalniz_queued_ise_ve_gecikmeli(
    api: TestClient, engine: Engine, kur, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_ORACLE_BIRLESTIRME_S", "5")
    k = kur([basit_case(toplam="30,00", risk="low")])
    run_jobs(engine)
    with session_scope() as s:
        a = service.gereksinim_kontrolu_kuyruga_al(s, k["rid"], "bir")
        b = service.gereksinim_kontrolu_kuyruga_al(s, k["rid"], "iki")
    assert a == b
    [is_] = [j for j in _isler(engine, service.CHECK_REQUIREMENT_JOB) if j.id == a]
    assert is_.run_after > datetime.now(UTC)  # 5 sn gecikme (run_after > 0 yolu)
    assert is_.yuk["nedenler"] == ["bir", "iki"]
    # Koşan işe birleşmez: yeni iş açılır, neden kaybolmaz.
    with session_scope() as s:
        s.execute(text("UPDATE job SET durum = 'running' WHERE id = :i"), {"i": a})
    with session_scope() as s:
        c_ = service.gereksinim_kontrolu_kuyruga_al(s, k["rid"], "uc")
    assert c_ != a
    # Yeniden denemedeki (retry) işe de birleşmez.
    with session_scope() as s:
        s.execute(text("UPDATE job SET durum = 'retry' WHERE id = :i"), {"i": c_})
    with session_scope() as s:
        d_ = service.gereksinim_kontrolu_kuyruga_al(s, k["rid"], "dort")
    assert d_ not in (a, c_)
    yuk = {j.id: j.yuk for j in _isler(engine, service.CHECK_REQUIREMENT_JOB)}
    assert yuk[d_] == {"requirement_id": str(k["rid"]), "neden": "dort"}


# ================================================================== t2 N1: kayıt yazmadan biten iş


def test_t2_n1_kayit_yazmadan_biten_is_anahtari_kilitlemez(
    api: TestClient, engine: Engine, kur
) -> None:
    """A → B → A: kapının işi koşarken tablo değişip iş `atlandi` ile `done` olursa (kayıt yok),
    tablo A'ya dönünce aynı anahtar yeni iş açar (önceden kapı sonsuz 409)."""
    k = kur([basit_case(toplam="30,00")], olgu_sayisi=10)
    c = latest_cases(api, k["rid"])[0]
    r = _karar(api, c, karar="approve")
    assert r.status_code == 409
    [is_] = [j for j in _isler(engine) if j.durum == "queued"]
    with session_scope() as s:
        s.execute(
            text(
                "UPDATE job SET durum = 'done', sonuc = CAST(:s AS jsonb), bitis = now() "
                "WHERE id = :i"
            ),
            {
                "s": '{"atlandi": true, "neden": "kontrol sürerken kapsayan tablolar değişti"}',
                "i": is_.id,
            },
        )
    r = _karar(api, c, karar="approve")
    assert r.status_code == 409
    yeni = [j for j in _isler(engine) if j.durum == "queued"]
    assert [j.idempotency_key for j in yeni] == [f"{is_.idempotency_key}:yeniden1"]
    run_jobs(engine)
    assert _karar(api, c, karar="approve").status_code == 200


# ================================================================== t2 N5: kilit sırası


def test_t2_n5_kapi_taslak_tabloyu_kilitlemez(
    api: TestClient, engine: Engine, kur, make_user
) -> None:
    """Kapı yalnız onaylı / PO bekleyen tabloları (id sırasıyla) paylaşımlı kilitler: AI taslak
    geçersiz kılma işinin FOR UPDATE tuttuğu taslak satır kapıyı bekletmez (deadlock yok)."""
    k = kur([basit_case(toplam="30,00", risk="low")])
    with session_scope() as s:
        taslak = KararTablosu(
            requirement_id=k["rid"], sira_no=9, icerik=BASIT, icerik_hash=content_hash(BASIT)
        )
        s.add(taslak)
        s.flush()
        tid = taslak.id
    c = latest_cases(api, k["rid"])[0]
    with engine.connect() as kilitleyen:
        tx = kilitleyen.begin()
        kilitleyen.execute(
            text("SELECT id FROM karar_tablosu WHERE id = :i FOR UPDATE"), {"i": tid}
        )
        with session_scope() as s:
            s.execute(text("SET LOCAL lock_timeout = '2s'"))
            tc = s.get(TestCase, uuid.UUID(c["id"]))
            kapi._tablolari_kilitle(s, tc)  # beklemeden döner
        tx.rollback()


# ================================================================== t2 N14: görülen hash önce


def test_t2_n14_bayat_hash_kapidan_once_reddedilir(api: TestClient, engine: Engine, kur) -> None:
    k = kur([basit_case(toplam="30,00", risk="high")])
    c = latest_cases(api, k["rid"])[0]
    once = len(_isler(engine))
    r = api.post(
        f"/cases/{c['id']}/decision", json={"karar": "approve", "icerik_hash": "sha256:bayat"}
    )
    assert r.status_code == 409 and r.json()["kod"] == "onay_hash_uyusmuyor", r.text
    assert len(_isler(engine)) == once  # kontrol işi açılmadı


# ================================================================== t2 N11: Kule önbelleği


def test_t2_n11_gecerli_tablolar_islem_basina_bir_kez(
    api: TestClient, engine: Engine, kur, monkeypatch: pytest.MonkeyPatch
) -> None:
    k = kur([basit_case(toplam="40,00")], tablo_once=True, olgu_sayisi=5)
    run_jobs(engine)
    c = latest_cases(api, k["rid"])[0]
    with session_scope() as s:
        s.execute(text("UPDATE test_case SET durum = 'approved' WHERE id = :i"), {"i": c["id"]})
    sayac = {"n": 0}
    asil = service.gecerli_tablolar

    def say(*a: Any, **kw: Any) -> Any:
        sayac["n"] += 1
        return asil(*a, **kw)

    monkeypatch.setattr(service, "gecerli_tablolar", say)
    with session_scope() as s:
        metrik.beklenti_dogrulugu(s)
        assert service.onayli_uyumsuz(s) != []
    assert sayac["n"] == 1


# ================================================================== mimari 17


def test_mimari_17_onayli_tablo_hashsiz_olamaz(engine: Engine, kur, api: TestClient) -> None:
    k = kur([basit_case(toplam="30,00", risk="low")])
    for tablo in ("karar_tablosu", "metamorfik_iliski"):
        with engine.connect() as c, pytest.raises(IntegrityError, match="onay_hash_ck"):
            c.execute(
                text(
                    f"INSERT INTO {tablo} (requirement_id, sira_no, icerik, icerik_hash, durum, "
                    "onaylanan_hash) VALUES (:r, 77, '{}'::jsonb, 'h', 'approved', 'h')"
                ),
                {"r": k["rid"]},
            )


# ================================================================== u2 N1 + N3


def test_u2_n1_yeniden_acilan_tablonun_uyumsuz_kaydi_sayilmaz(
    api: TestClient, engine: Engine, kur
) -> None:
    """Tablo yeniden açılınca (insanın yanlış tablosu) o tabloyla yapılmış `uyumsuz` kayıt geçersiz
    olur: beklenti doğruluğuna ve onaylı-uyumsuz listesine girmez."""
    k = kur([basit_case(toplam="40,00")], tablo_once=True, olgu_sayisi=5)
    run_jobs(engine)
    c = latest_cases(api, k["rid"])[0]
    with session_scope() as s:
        s.execute(text("UPDATE test_case SET durum = 'approved' WHERE id = :i"), {"i": c["id"]})
    m = api.get(f"/requirements/{k['rid']}/case-metrics").json()["beklenti_dogrulugu"]
    assert m["uyumsuz"] == 1
    assert [x["case_id"] for x in api.get("/control-tower").json()["onayli_uyumsuz"]] == [c["id"]]
    r = api.post(f"/decision-tables/{k['tid']}/reopen")
    assert r.status_code == 200, r.text
    m = api.get(f"/requirements/{k['rid']}/case-metrics").json()["beklenti_dogrulugu"]
    assert (m["uyumsuz"], m["oran"]) == (0, None)
    assert api.get("/control-tower").json()["onayli_uyumsuz"] == []


def test_u2_n3_ozet_turkce_bicim() -> None:
    assert d.tr_sayi("1234.56") == "1.234,56" and d.tr_sayi("-7") == "-7"
    assert d.deger_metni("1250000.5") == "1.250.000,5"
    ayr = {
        "gruplar": [
            {
                "karsilastirmalar": [
                    {
                        "column": "minimum_uyarisi",
                        "alinti": "uyarı görünür",
                        "case_degeri": True,
                        "tablo_degeri": False,
                        "uyumlu": False,
                    }
                ]
            }
        ],
        "kapsanmayan_sayilar": [{"alan": "steps[3].expected", "alinti": "45,00", "tur": "sayi"}],
        "degerler": {},
    }
    ozet = d.ozet(d.UYUMSUZ, ayr)
    assert "tablo yanlış" in ozet and "“uyarı görünür”" in ozet
    assert "“45,00”, S4 beklenen" in ozet
    assert "True" not in ozet and "'" not in ozet.replace("case'", "")


# ================================================================== güvenlik 13


def test_guvenlik_13_evaluate_icerik_boyut_siniri(api: TestClient, kur) -> None:
    k = kur([basit_case(toplam="30,00", risk="low")])
    buyuk = copy.deepcopy(BASIT)
    buyuk["satirlar"] = [
        {"id": f"R{n}", "kosul": "adet >= 1", "cikti": {"toplam": "adet * 10"}} for n in range(61)
    ]
    r = api.post(
        f"/decision-tables/{k['tid']}/evaluate", json={"girdiler": {"adet": 3}, "icerik": buyuk}
    )
    assert r.status_code == 422 and r.json()["kod"] == "karar_tablosu_gecersiz", r.text
    uzun = copy.deepcopy(BASIT)
    uzun["satirlar"][0]["kosul"] = "adet >= 1 ve " + " ve ".join(["adet >= 1"] * 40)
    r = api.post(
        f"/decision-tables/{k['tid']}/evaluate", json={"girdiler": {"adet": 3}, "icerik": uzun}
    )
    assert r.status_code == 422, r.text
    r = api.post(
        f"/decision-tables/{k['tid']}/evaluate", json={"girdiler": {"adet": 3}, "icerik": BASIT}
    )
    assert r.status_code == 200 and r.json()["ciktilar"] == {"toplam": "30"}


def test_tablo_ekle_yardimcisi_onay_hashlerini_yazar(api: TestClient, kur) -> None:
    k = kur([basit_case(toplam="30,00", risk="low")])
    tid = tablo_ekle(k["rid"], {**BASIT, "ad": "İkinci"}, k["analist"], k["po"])
    with session_scope() as s:
        t = s.get(KararTablosu, tid)
        assert t.durum == "approved" and t.onaylanan_hash and t.gereksinim_hash
