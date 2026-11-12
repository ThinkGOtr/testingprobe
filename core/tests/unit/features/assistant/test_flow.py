"""Asistan cevap akışı `flow.cevapla` (AI-ASISTAN-PLANI §10.2, §6.2, §10.1; §13 "Worker" tam
döngü, "Otomatik yükseltme", "Kilit/yarış (otomatik yükseltme)", "Yan etkisizlik").

Gerçek Postgres; mesajlar gerçek API ucuyla yaratılır, worker yerine `flow.cevapla` doğrudan
çağrılır. Model çağrısı yok: geçit `gateway_factory` ile sahte sağlayıcılı kurulur (gerçek
`build_gateway` + `PgCallRecorder`); kapalı kipte, sözlük ve şablon dallarında fabrika çağrılırsa
test düşer.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from tests.unit.conftest import Db
from tests.unit.features.assistant import test_asistan_api as _api
from tests.unit.features.assistant import test_probe_tools as _probe
from tests.unit.features.assistant.test_sonislem import SahteDogrulayici
from tp_core.audit import PgCallRecorder, verify_chain
from tp_core.features.assistant import budget, flow, sonislem
from tp_core.features.assistant.tools import AracSonucu, arac_seti
from tp_core.gateway import FINAL_TOOL, build_gateway
from tp_core.gateway.core import deterministic_call_id
from tp_core.gateway.errors import ProviderPermanentError
from tp_core.gateway.masking import PiiMasker
from tp_core.gateway.providers.base import ProviderRequest
from tp_core.gateway.testing import FakeProvider, tool_response
from tp_core.workflow.service import Principal

# Fikstürler (diğer asistan test modüllerinden; aynı kurulum).
client = _api.client
veri = _probe.veri
_giris_istemcisi = _api._giris_istemcisi
giris = _api.giris
kalp_atisi = _api.kalp_atisi
sohbet_ac = _api.sohbet_ac
sor = _api.sor
tek = _api.tek

KIRARAK = "Kırarak doğrula düğmesi neden gri?"
GRI_BAGLAM = {"rota": "/kod"}


@pytest.fixture(autouse=True)
def _otomatik_derin_varsayilan(monkeypatch: pytest.MonkeyPatch) -> None:
    # ANTHROPIC_API_KEY ortak conftest'te silinir.
    monkeypatch.delenv("TP_ASISTAN_OTOMATIK_DERIN", raising=False)


# ------------------------------------------------------------------ sahte araçlar ve geçit


class SahteUrun:
    def product_search(self, args: dict[str, Any]) -> str:
        return 'review-portal/src/pages/Script.tsx:12: <button title="Yalnızca mühendis rolü">'

    def product_read(self, args: dict[str, Any]) -> str:
        return (
            "review-portal/src/pages/Script.tsx (satır 12-12 / 40)\n"
            '12| <button title="Yalnızca mühendis rolü">'
        )


class SahteKod:
    def search_code(self, args: dict[str, Any]) -> str:
        return "<untrusted>src/kampanya.py:3: return tutar * 0.9</untrusted>"

    def get_file_contents(self, args: dict[str, Any]) -> str:
        return "<untrusted>def indirim(): ...</untrusted>"


class SahteVeri:
    def db_schema(self, args: dict[str, Any]) -> str:
        return "<untrusted>kampanya(kod text)</untrusted>"

    def db_query(self, args: dict[str, Any]) -> str:
        return "query: SELECT 1\nresult_digest: x\n<untrusted>1</untrusted>"


def sahte_jira(_b: Any, **arg: Any) -> AracSonucu:
    return AracSonucu(
        f"{arg.get('anahtar')} son yorum: PO kabul kriterini netleştirin dedi.",
        kanit_turu="jira",
        tur="jira",
        meta={"anahtar": arg.get("anahtar")},
    )


def sahte_ci(_b: Any, **arg: Any) -> AracSonucu:
    return AracSonucu("lint: E501", kanit_turu="ci_log", tur="ci_log")


def araclar(ab: Any) -> Any:
    return arac_seti(
        ab,
        urun=SahteUrun(),
        kod=SahteKod(),
        veri=SahteVeri(),
        yeni_araclar={"jira_issue": sahte_jira, "ci_log": sahte_ci},
    )


class Gecit:
    """`gateway_factory`: gerçek geçit, sahte sağlayıcı; çağrı sayısı ve bütçe tutulur."""

    def __init__(self, engine: Engine, script: list[Any]) -> None:
        self.engine = engine
        self.saglayici = FakeProvider(script)
        self.cagri = 0
        self.butce: Any = None

    def __call__(self, *, budget: Any) -> Any:
        self.cagri += 1
        self.butce = budget
        return build_gateway(
            PgCallRecorder(self.engine),
            provider=self.saglayici,
            engine=self.engine,
            mode_override="live",
            replay_fallback=False,
            budget=budget,
        )

    def ilk_istek(self) -> str:
        return json.dumps(self.saglayici.requests[0].messages, ensure_ascii=False)


def yasak_gecit(**_: Any) -> Any:
    pytest.fail("bu dalda geçit kurulmamalıydı")


def sonuc(**alan: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "cevap_bloklari": [{"tur": "paragraf", "metin": "Cevap metni.", "maddeler": []}],
        "guven": "yuksek",
        "kaynaklar": [],
        "yonlendirmeler": [],
        "jira_anahtarlari": [],
        "eylem_reddi": False,
        "oneriler": [],
    }
    out.update(alan)
    return out


def bitir(**alan: Any) -> Any:
    return tool_response((FINAL_TOOL, sonuc(**alan)))


def dogrulanmis_kaynak() -> list[Any]:
    """`product_read` çağırıp doğrulanabilir bir ürün kaynağı gösteren senaryo."""
    return [
        tool_response(("product_read", {"path": "review-portal/src/pages/Script.tsx"})),
        bitir(
            kaynaklar=[
                {
                    "tur": "urun_kodu",
                    "ref": "review-portal/src/pages/Script.tsx:12",
                    "alinti": '<button title="Yalnızca mühendis rolü">',
                }
            ]
        ),
    ]


DOGRULAYICI = SahteDogrulayici(
    urun={
        "review-portal/src/pages/Script.tsx": [""] * 11
        + ['<button title="Yalnızca mühendis rolü">']
    }
)


# ------------------------------------------------------------------ yardımcılar


def fabrika(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def soru_gonder(
    client: TestClient,
    engine: Engine,
    soru: str,
    *,
    baglam: dict[str, Any] | None = None,
    model_hazir: bool = True,
    sohbet: str | None = None,
    **govde: Any,
) -> tuple[str, str]:
    kalp_atisi(engine, mod="live" if model_hazir else "off", model_hazir=model_hazir)
    sohbet = sohbet or sohbet_ac(client)
    r = sor(client, sohbet, soru=soru, baglam=baglam, **govde)
    assert r.status_code == 202, r.text
    return sohbet, r.json()["mesaj_id"]


def cevapla(engine: Engine, mesaj_id: str, gecit: Any = yasak_gecit, **kw: Any) -> str | None:
    kw.setdefault("arac_seti_fabrikasi", araclar)
    kw.setdefault("dogrulayici", DOGRULAYICI)
    return flow.cevapla(fabrika(engine), uuid.UUID(mesaj_id), gateway_factory=gecit, **kw)


def mesaj(engine: Engine, mesaj_id: Any) -> dict[str, Any]:
    with engine.connect() as c:
        return dict(
            c.execute(text("SELECT * FROM asistan_mesaj WHERE id = :i"), {"i": mesaj_id})
            .mappings()
            .one()
        )


def cocuklar(engine: Engine, ust: Any) -> list[dict[str, Any]]:
    with engine.connect() as c:
        return [
            dict(r)
            for r in c.execute(
                text("SELECT * FROM asistan_mesaj WHERE ust_mesaj_id = :u"), {"u": ust}
            ).mappings()
        ]


def is_bitir(engine: Engine, mesaj_id: Any) -> None:
    """Worker'ın işi kapatmasını taklit eder (iş satırı)."""
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE job SET durum = 'done', bitis = now() WHERE id = "
                "(SELECT job_id FROM asistan_mesaj WHERE id = :m)"
            ),
            {"m": mesaj_id},
        )


def ai_call_ekle(
    engine: Engine,
    maliyet: str,
    *,
    kullanici_id: uuid.UUID | None = None,
    amac: str = "assistant",
    call_id: uuid.UUID | None = None,
    parent: uuid.UUID | None = None,
) -> None:
    ek = {"kanal": "asistan", "kullanici_id": str(kullanici_id)} if kullanici_id else None
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO ai_call (id, parent_call_id, amac, saglayici, model, mod, maliyet, "
                "ek) VALUES (:id, :p, :a, 'anthropic', 'm', 'live', :m, CAST(:ek AS jsonb))"
            ),
            {
                "id": call_id or uuid.uuid4(),
                "p": parent,
                "a": amac,
                "m": Decimal(maliyet),
                "ek": json.dumps(ek),
            },
        )


# ------------------------------------------------------------------ sözlük, şablon, kapalı


def test_sozluk_dali_modelsiz_ve_amac_null_derin_kabul(
    client: TestClient, make_user, engine: Engine
) -> None:
    u = make_user("analyst")
    giris(client, u)
    baglam = {
        "rota": "/gereksinimler",
        "son_hata": {
            "uc": "POST /cases/:id/review",
            "status": 409,
            "kod": "onay_hash_uyusmuyor",
            "detail": "İçerik değişti, yeniden inceleyin.",
        },
    }
    sohbet, mid = soru_gonder(client, engine, "Az önceki hata ne demek?", baglam=baglam)
    assert cevapla(engine, mid) == "done"
    m = mesaj(engine, mid)
    assert (m["durum"], m["kaynak"], m["amac"], m["ai_call_id"]) == ("done", "sozluk", None, None)
    assert m["cevap"]["cevap_bloklari"][0]["metin"]
    assert m["cevap"]["guven_gosterimi"] == sonislem.DOGRULANDI
    assert m["sure_ms"] is not None and m["tamamlanma"] is not None
    assert tek(engine, "SELECT count(*) FROM ai_call") == 0
    # Sözlük cevabının (amac NULL) "Daha ayrıntılı"sı kabul edilir ve `assistant` ile cevaplanır.
    is_bitir(engine, mid)
    r = sor(client, sohbet, ust_mesaj_id=mid)
    assert r.status_code == 202, r.text
    gecit = Gecit(engine, dogrulanmis_kaynak())
    assert cevapla(engine, r.json()["mesaj_id"], gecit) == "done"
    d = mesaj(engine, r.json()["mesaj_id"])
    assert (d["amac"], d["kaynak"]) == ("assistant", "model")
    assert gecit.saglayici.requests[0].model == "claude-haiku-5-5"


def test_sablon_dali_durum_rol_kisiti_ve_tool_call(
    client: TestClient, make_user, engine: Engine, veri: dict[str, Any]
) -> None:
    for rol in ("analyst", "tester"):
        u = make_user(rol)
        giris(client, u)
        _, mid = soru_gonder(
            client, engine, "TPD-3 neden case üretimine geçmiyor?", model_hazir=False
        )
        assert cevapla(engine, mid) == "done"
        m = mesaj(engine, mid)
        assert (m["kaynak"], m["amac"]) == ("sablon", None)
        metin = json.dumps(m["cevap"], ensure_ascii=False)
        assert "PO onayı bekleniyor" in metin
        assert m["cevap"]["yonlendirmeler"] == [
            {"etiket": "Gereksinim ekranı", "rota": f"/gereksinimler/{veri['req']}"}
        ]
        assert m["cevap"]["jira_anahtarlari"] == ["TPD-3"]
        # Rol kısıtı aracın kendisinde: Testçi analiste özel yayın önizlemesini görmez.
        assert ("yayin_onizleme" in metin) is (rol == "analyst")
        with engine.connect() as c:
            tc = c.execute(
                text(
                    "SELECT kanal, cagiran_user_id, ai_call_id, arac, sonuc_ozeti FROM tool_call "
                    "WHERE cagiran_user_id = :u"
                ),
                {"u": u.id},
            ).one()
        assert (tc.kanal, tc.ai_call_id, tc.arac) == ("asistan", None, "probe_get")
        assert "po.kisi@ornek.com" not in tc.sonuc_ozeti  # kayıt maskeli


def test_sablon_kuyruk_dali(client: TestClient, make_user, engine: Engine, veri) -> None:
    giris(client, make_user("po"))
    _, mid = soru_gonder(client, engine, "Bugün ne yapmalıyım?", model_hazir=False)
    assert cevapla(engine, mid) == "done"
    m = mesaj(engine, mid)
    assert m["kaynak"] == "sablon"
    assert "TPD-3" in json.dumps(m["cevap"], ensure_ascii=False)
    assert m["cevap"]["yonlendirmeler"][0]["rota"] == f"/gereksinimler/{veri['req']}"


def test_bilinmeyen_anahtar_sablona_girmez_kapali_kipe_duser(
    client: TestClient, make_user, engine: Engine
) -> None:
    giris(client, make_user("analyst"))
    _, mid = soru_gonder(client, engine, "TPD-404 neden bekliyor?", model_hazir=False)
    assert cevapla(engine, mid) == "done"
    m = mesaj(engine, mid)
    assert m["kaynak"] == "kapali"
    assert m["cevap"]["cevap_bloklari"][0]["metin"] == flow.KAPALI_METNI


SON_HATA = {"uc": "POST /cases/:id/review", "status": 409, "kod": "onay_hash_uyusmuyor"}


def test_son_hata_varken_anahtarli_durum_sorusu_sozluge_gitmez(
    client: TestClient, make_user, engine: Engine, veri
) -> None:
    """S3: ekranda son hata varken "TPD-3 neden …?" gereksinim durumunu alır, hatanın sözlük
    açıklamasını değil ("neden" sözlük sınıfında da geçer)."""
    giris(client, make_user("analyst"))
    _, mid = soru_gonder(
        client,
        engine,
        "TPD-3 neden case üretimine geçmiyor?",
        baglam={"son_hata": SON_HATA},
        model_hazir=False,
    )
    assert cevapla(engine, mid) == "done"
    m = mesaj(engine, mid)
    assert m["kaynak"] == "sablon"
    assert "PO onayı bekleniyor" in json.dumps(m["cevap"], ensure_ascii=False)


@pytest.mark.parametrize(
    ("soru", "kaynak"),
    [
        ("Bu düğme neden gri?", "kapali"),  # "? Bu ne?" akışı: öğe hakkında
        ("Bu ne?", "kapali"),
        ("Bu hata ne demek?", "sozluk"),  # hatayı açıkça anar
    ],
)
def test_secili_oge_varken_sozluk_yalniz_hatayi_anan_soruda(
    client: TestClient, make_user, engine: Engine, soru: str, kaynak: str
) -> None:
    giris(client, make_user("tester"))
    baglam = {
        "rota": "/kod",
        "son_hata": {"kod": "kapi_kapali"},
        "secili_eleman": {"ad": "Kırarak doğrula", "rol": "button", "devre_disi": True},
    }
    _, mid = soru_gonder(client, engine, soru, baglam=baglam, model_hazir=False)
    assert cevapla(engine, mid) == "done"
    assert mesaj(engine, mid)["kaynak"] == kaynak


def test_sozluk_sorusu_siniflandirmasi() -> None:
    from tp_core.features.assistant import siniflandir

    secili = {"secili_eleman": {"ad": "Kaydet"}}
    assert siniflandir.sozluk_sorusu("Az önceki hata ne demek?")
    assert siniflandir.sozluk_sorusu("Neden oldu?", {"son_hata": {"kod": "x"}})
    assert not siniflandir.sozluk_sorusu("TPD-3 neden case üretimine geçmiyor?")
    assert not siniflandir.sozluk_sorusu("Bu Kırarak doğrula neden gri?", secili)
    assert siniflandir.sozluk_sorusu("Bu mesaj ne?", secili)
    assert not siniflandir.sozluk_sorusu("Merhaba", None)


def test_kapali_cipleri_ekrandaki_anahtari_kullanir() -> None:
    def cipler(baglam: Any) -> list[str]:
        return flow.kapali_cevabi("soru", baglam)["cevap_bloklari"][1]["maddeler"]

    assert cipler({"varlik": {"tur": "requirement", "anahtar": "ABC-12"}})[-1] == (
        "ABC-12 neden bekliyor?"
    )
    for baglam in (None, {}, {"varlik": {"tur": "run", "id": "x"}}, {"varlik": {"anahtar": "x"}}):
        son = cipler(baglam)[-1]
        assert son == flow.KAPALI_DURUM_GENEL and "TPD-3" not in son
    assert cipler(None)[:2] == list(flow.KAPALI_CIPLERI)


@pytest.mark.parametrize("musteri", [False, True])
def test_kapali_kip_gecit_kurulmaz(
    client: TestClient, make_user, engine: Engine, musteri: bool
) -> None:
    giris(client, make_user("engineer"))
    _, mid = soru_gonder(client, engine, KIRARAK, baglam=GRI_BAGLAM, model_hazir=False)
    if musteri:  # müşteri verisi + maskeleme kapalı → worker model_hazir=false yazar
        kalp_atisi(engine, mod="live", model_hazir=False, musteri_verisi=True, maskeleme=False)
    assert cevapla(engine, mid) == "done"
    m = mesaj(engine, mid)
    assert (m["kaynak"], m["amac"]) == ("kapali", None)
    assert m["cevap"]["cevap_bloklari"][0]["metin"] == flow.KAPALI_METNI
    assert tek(engine, "SELECT count(*) FROM ai_call") == 0


def test_oneri_kipi_kapali_sabit_cevap(client: TestClient, make_user, engine: Engine) -> None:
    giris(client, make_user("analyst"))
    _, mid = soru_gonder(
        client, engine, "", baglam={"rota": "/gereksinimler"}, kip="oneri", model_hazir=False
    )
    assert cevapla(engine, mid) == "done"
    m = mesaj(engine, mid)
    assert m["kaynak"] == "kapali"
    assert m["cevap"]["cevap_bloklari"][0]["metin"] == flow.ONERI_KAPALI_METNI


# ------------------------------------------------------------------ canlı dal


def test_canli_tam_dongu_assistant(client: TestClient, make_user, engine: Engine, veri) -> None:
    u = make_user("analyst")
    giris(client, u)
    _, mid = soru_gonder(client, engine, "TPD-3 için PO ne istemiş, açıklar mısın?")
    gecit = Gecit(
        engine,
        [
            tool_response(("probe_get", {"tur": "requirement", "id_or_key": "TPD-3"})),
            bitir(
                kaynaklar=[
                    {
                        "tur": "probe_verisi",
                        "ref": "k1",
                        "alinti": "bekleyen_kapi: PO onayı bekleniyor",
                    },
                    {"tur": "probe_verisi", "ref": "k1", "alinti": "iletişim po.kisi@ornek.com"},
                ],
                yonlendirmeler=[
                    {"etiket": "Gereksinim", "rota": f"/gereksinimler/{veri['req']}"},
                    {"etiket": "Dış", "rota": "https://evil.example"},
                ],
                jira_anahtarlari=["TPD-3", "XYZ-1"],
            ),
        ],
    )
    # Maskeleme açık (TP_PII_MASKING): mesajın tek oturumu geçide ve araçlara verilir.
    assert cevapla(engine, mid, gecit, masker=PiiMasker(enabled=True)) == "done"
    assert gecit.cagri == 1
    m = mesaj(engine, mid)
    assert (m["durum"], m["kaynak"], m["amac"], m["tetik"]) == (
        "done",
        "model",
        "assistant",
        "kullanici",
    )
    c = m["cevap"]
    assert [k["dogrulandi"] for k in c["kaynaklar"]] == [True, True]
    assert c["guven_gosterimi"] == sonislem.DOGRULANDI
    assert c["yonlendirmeler"] == [
        {"etiket": "Gereksinim", "rota": f"/gereksinimler/{veri['req']}"}
    ]
    assert c["jira_anahtarlari"] == ["TPD-3"]
    assert c["oneriler"] == []
    # Harcama ve denetim izi (İlke VIII).
    assert m["maliyet_usd"] > 0 and m["token_girdi"] == 200 and m["token_cikti"] == 100
    assert m["ai_call_id"] == deterministic_call_id(m["id"], "assistant")
    with engine.connect() as cn:
        ekler = cn.execute(text("SELECT amac, ek FROM ai_call")).all()
        tc = cn.execute(text("SELECT kanal, cagiran_user_id, arac FROM tool_call")).all()
    assert {a for a, _ in ekler} == {"assistant"}
    assert all(e["kullanici_id"] == str(u.id) and e["mesaj_id"] == mid for _, e in ekler)
    assert {(t.kanal, t.cagiran_user_id) for t in tc} == {("asistan", u.id)}
    # Sahte sağlayıcıya giden ilk mesajda PII maskeli; rol ve soru ilk mesajda.
    ilk = gecit.ilk_istek()
    assert "Kullanıcının rolü: Analist" in ilk and "kip=soru" in ilk
    sonraki = json.dumps(gecit.saglayici.requests[1].messages, ensure_ascii=False)
    assert "po.kisi@ornek.com" not in sonraki and "<<PII_EMAIL_" in sonraki
    # Doğrulanmış cevapta otomatik yükseltme yok.
    assert cocuklar(engine, mid) == []


def test_jira_ve_ci_kaynagi_tarih_kosu_ve_satir_tasir(
    client: TestClient, make_user, engine: Engine, veri
) -> None:
    """§11 kaynak etiketi: gerçek araç biçimiyle (`jira._bicimle`, `ci.log_isle`) sunucu, alıntının
    eşleştiği satırdan Jira'da yorum mu/tarih, CI'da koşu numarası ve log satır aralığı üretir
    (portal mock'u ile gerçek API aynı alanları taşır)."""
    from datetime import UTC, datetime

    from tp_core.features.assistant.tools import ci as ci_araci
    from tp_core.features.assistant.tools import jira as jira_araci
    from tp_core.integrations import jira as jira_mod

    tarih = datetime(2026, 11, 2, 9, 30, tzinfo=UTC)
    issue = jira_mod.OkunanIssue(
        key="TPD-3",
        issue_type="Story",
        summary="Kampanya indirimi",
        description="Kampanya kodu bayi başına bir kez uygulanır.",
        acceptance_criteria=[],
        labels=[],
        status="In Progress",
        updated=None,
    )
    sayfa = jira_mod.YorumSayfasi(
        toplam=1,
        yorumlar=[jira_mod.OkunanYorum("1", "PO", tarih, "Kabul kriterini netleştirin lütfen.")],
        kisitli=0,
    )
    log = "\n".join(f"adım {i}" for i in range(1, 30)) + "\nE501 satır çok uzun\nbitti\n"

    def jira_issue(_b: Any, **arg: Any) -> AracSonucu:
        metin, yorumlar = jira_araci._bicimle(issue, sayfa, 3)
        return AracSonucu(
            metin,
            kanit_turu="jira",
            tur="jira",
            meta={"anahtar": "TPD-3", "yorum_satirlari": yorumlar},
        )

    def ci_log(_b: Any, **arg: Any) -> AracSonucu:
        metin = ci_araci.log_isle(log.encode(), kirpildi=False, ara="E501", satir=120)
        return AracSonucu(
            metin,
            kanit_turu="ci_log",
            tur="ci_log",
            meta={"run_id": arg["run_id"], "kosu_no": "123456"},
        )

    def fabrika_(ab: Any) -> Any:
        return arac_seti(
            ab,
            urun=SahteUrun(),
            kod=SahteKod(),
            veri=SahteVeri(),
            yeni_araclar={"jira_issue": jira_issue, "ci_log": ci_log},
        )

    giris(client, make_user("tester"))
    _, mid = soru_gonder(client, engine, "TPD-3 koşusu neden kırmızı, PO ne yazmış?")
    run_id = str(uuid.uuid4())
    gecit = Gecit(
        engine,
        [
            tool_response(("jira_issue", {"anahtar": "TPD-3"})),
            tool_response(("ci_log", {"run_id": run_id, "ara": "E501"})),
            bitir(
                kaynaklar=[
                    {"tur": "jira", "ref": "k1", "alinti": "Kabul kriterini netleştirin"},
                    {"tur": "jira", "ref": "k1", "alinti": "bayi başına bir kez uygulanır"},
                    {"tur": "ci_log", "ref": "k2", "alinti": "E501 satır çok uzun"},
                ]
            ),
        ],
    )
    assert cevapla(engine, mid, gecit, arac_seti_fabrikasi=fabrika_) == "done"
    yorum, aciklama, ci_kaynagi = mesaj(engine, mid)["cevap"]["kaynaklar"]
    assert yorum["dogrulandi"] and aciklama["dogrulandi"] and ci_kaynagi["dogrulandi"]
    assert yorum["jira"]["anahtar"] == "TPD-3"
    assert yorum["jira"]["yorum"] is True and yorum["jira"]["tarih"] == tarih.isoformat()
    assert aciklama["jira"]["yorum"] is False and aciklama["jira"]["tarih"] is None
    assert ci_kaynagi["ci"] == {
        "run_id": run_id,
        "kosu_no": "123456",
        "satir_bas": 30,
        "satir_bit": 30,
    }


def test_yalniz_workerin_bildigi_sir_modele_gitmez(
    client: TestClient, make_user, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """core-api'nin bilmediği (yalnız worker ortamındaki) biçimsiz sır değeri soruya
    yapıştırılırsa 422'ye takılmaz; worker ilk mesajı kendi sır değerleriyle süzer."""
    deger = "jira" + "dc" + "Pat" + "Q7w8E9r0T1y2U3i4"  # biçimi tanınmayan Jira DC PAT
    monkeypatch.delenv("JIRA_READ_TOKEN", raising=False)
    giris(client, make_user("tester"))
    _, mid = soru_gonder(
        client, engine, f"Jira token'ım {deger} neden çalışmıyor?", baglam={"rota": "/kod"}
    )
    monkeypatch.setenv("JIRA_READ_TOKEN", deger)  # yalnız worker'da
    gecit = Gecit(engine, [bitir()])
    assert cevapla(engine, mid, gecit) == "done"
    assert deger not in gecit.ilk_istek()
    assert "neden çalışmıyor" in gecit.ilk_istek()


def test_assistant_deep_ayri_mesaj_ve_zincir_yok(
    client: TestClient, make_user, engine: Engine
) -> None:
    giris(client, make_user("engineer"))
    sohbet, mid = soru_gonder(client, engine, "Script ekranı ne yapar?", baglam=GRI_BAGLAM)
    assert cevapla(engine, mid, Gecit(engine, dogrulanmis_kaynak())) == "done"
    is_bitir(engine, mid)
    r = sor(client, sohbet, ust_mesaj_id=mid)
    assert r.status_code == 202, r.text
    derin = r.json()["mesaj_id"]
    gecit = Gecit(engine, [bitir(guven="dusuk")])  # "Emin değil" — yine de zincir yok
    assert cevapla(engine, derin, gecit) == "done"
    d = mesaj(engine, derin)
    assert (d["amac"], d["kaynak"], d["ust_mesaj_id"]) == (
        "assistant_deep",
        "model",
        uuid.UUID(mid),
    )
    assert d["cevap"]["guven_gosterimi"] == sonislem.EMIN_DEGIL
    assert gecit.saglayici.requests[0].model == "claude-sonnet-5-5"
    assert "ayrıntılı" in gecit.ilk_istek()
    assert cocuklar(engine, derin) == []


def test_gecmis_kirpilir_ve_untrusted(client: TestClient, make_user, engine: Engine) -> None:
    u = make_user("tester")
    giris(client, u)
    sohbet = sohbet_ac(client)
    with engine.begin() as c:
        for i in range(1, 9, 2):
            c.execute(
                text(
                    "INSERT INTO asistan_mesaj (sohbet_id, kullanici_id, sira, rol, icerik, "
                    "durum) VALUES (:s, :k, :n, 'user', :q, 'done')"
                ),
                {"s": sohbet, "k": u.id, "n": i, "q": f"eski soru {i}"},
            )
            c.execute(
                text(
                    "INSERT INTO asistan_mesaj (sohbet_id, kullanici_id, sira, rol, cevap, "
                    "durum, kaynak) VALUES (:s, :k, :n, 'assistant', CAST(:c AS jsonb), 'done', "
                    "'model')"
                ),
                {
                    "s": sohbet,
                    "k": u.id,
                    "n": i + 1,
                    "c": json.dumps(
                        {"cevap_bloklari": [{"tur": "paragraf", "metin": f"C{i} " + "u" * 900}]}
                    ),
                },
            )
    _, mid = soru_gonder(client, engine, "Peki şimdi ne olacak?", sohbet=sohbet)
    gecit = Gecit(engine, [bitir()])
    assert cevapla(engine, mid, gecit) == "done"
    ilk = gecit.ilk_istek()
    assert 'source=\\"sohbet_gecmisi\\"' in ilk
    assert "eski soru 1" not in ilk and "C1 " not in ilk  # yalnız son 6 mesaj
    assert "eski soru 3" in ilk and "C3 " in ilk and "C7 " in ilk
    assert "u" * 600 not in ilk and "…" in ilk
    assert ilk.count("Peki şimdi ne olacak?") == 1


def test_eski_cevabin_derini_gecmisi_kok_sorudan_oncesiyle_sinirli(
    make_user, engine: Engine
) -> None:
    """Q0, A0, Q1, A1, Q2, A2; A1'in "Daha ayrıntılı"sı sohbetin sonuna eklenir (sıra 7). Geçmiş
    Q0/A0 + üst kısa cevap A1'dir; kök soru Q1 yalnız `Soru:` satırında, Q2/A2 hiç gitmez."""
    u = make_user("tester")
    ids: dict[str, uuid.UUID] = {}
    with engine.begin() as c:
        sohbet = c.execute(
            text("INSERT INTO asistan_sohbet (kullanici_id) VALUES (:k) RETURNING id"),
            {"k": u.id},
        ).scalar_one()
        for i in range(3):
            ids[f"Q{i}"] = c.execute(
                text(
                    "INSERT INTO asistan_mesaj (sohbet_id, kullanici_id, sira, rol, icerik, "
                    "durum) VALUES (:s, :k, :n, 'user', :q, 'done') RETURNING id"
                ),
                {"s": sohbet, "k": u.id, "n": 2 * i + 1, "q": f"soru-{i}"},
            ).scalar_one()
            ids[f"A{i}"] = c.execute(
                text(
                    "INSERT INTO asistan_mesaj (sohbet_id, kullanici_id, sira, rol, icerik, "
                    "cevap, durum, kaynak) VALUES (:s, :k, :n, 'assistant', :q, "
                    "CAST(:c AS jsonb), 'done', 'model') RETURNING id"
                ),
                {
                    "s": sohbet,
                    "k": u.id,
                    "n": 2 * i + 2,
                    "q": f"soru-{i}",
                    "c": json.dumps(
                        {"cevap_bloklari": [{"tur": "paragraf", "metin": f"cevap-{i}"}]}
                    ),
                },
            ).scalar_one()
        derin = c.execute(
            text(
                "INSERT INTO asistan_mesaj (sohbet_id, kullanici_id, sira, rol, ust_mesaj_id, "
                "icerik, durum, amac) VALUES (:s, :k, 7, 'assistant', :u, 'soru-1', 'pending', "
                "'assistant_deep') RETURNING id"
            ),
            {"s": sohbet, "k": u.id, "u": ids["A1"]},
        ).scalar_one()
        m = flow._mesaj_oku(c, derin)
        gecmis = flow.sohbet_gecmisi(c, m) or ""
        # Derin olmayan son soru davranışı değişmez: kendi sorusu hariç önceki her şey.
        son = flow.sohbet_gecmisi(c, flow._mesaj_oku(c, ids["A2"])) or ""
    assert gecmis.splitlines() == [
        "Kullanıcı: soru-0",
        "Asistan: cevap-0",
        "Asistan: cevap-1",
    ]
    assert son.splitlines()[-1] == "Asistan: cevap-1" and "soru-2" not in son


def test_zincirli_derinin_gecmisi_zincir_kokunun_sorusuyla_sinirli(
    make_user, engine: Engine
) -> None:
    """Q0, A0, Q1, A1, Q2, A2; A1'in derini C1 (sıra 7), C1'in derini C2 (sıra 8). C2'nin kök
    sorusu Q1'dir (C1'in sırasından önceki son soru Q2 değil): geçmiş Q0/A0 + üst cevap C1."""
    u = make_user("tester")
    ids: dict[str, uuid.UUID] = {}
    with engine.begin() as c:
        sohbet = c.execute(
            text("INSERT INTO asistan_sohbet (kullanici_id) VALUES (:k) RETURNING id"),
            {"k": u.id},
        ).scalar_one()

        def ekle(ad: str, sira: int, rol: str, icerik: str, **ek: Any) -> None:
            ids[ad] = c.execute(
                text(
                    "INSERT INTO asistan_mesaj (sohbet_id, kullanici_id, sira, rol, icerik, "
                    "cevap, durum, ust_mesaj_id, amac) VALUES (:s, :k, :n, :r, :q, "
                    "CAST(:c AS jsonb), :d, :u, :a) RETURNING id"
                ),
                {
                    "s": sohbet,
                    "k": u.id,
                    "n": sira,
                    "r": rol,
                    "q": icerik,
                    "c": json.dumps({"cevap_bloklari": [{"tur": "paragraf", "metin": ek["metin"]}]})
                    if "metin" in ek
                    else None,
                    "d": ek.get("durum", "done"),
                    "u": ek.get("ust"),
                    "a": ek.get("amac"),
                },
            ).scalar_one()

        for i in range(3):
            ekle(f"Q{i}", 2 * i + 1, "user", f"soru-{i}")
            ekle(f"A{i}", 2 * i + 2, "assistant", f"soru-{i}", metin=f"cevap-{i}")
        ekle("C1", 7, "assistant", "soru-1", metin="derin-1", ust=ids["A1"], amac="assistant")
        ekle(
            "C2",
            8,
            "assistant",
            "soru-1",
            durum="pending",
            ust=ids["C1"],
            amac="assistant_deep",
        )
        gecmis = flow.sohbet_gecmisi(c, flow._mesaj_oku(c, ids["C2"])) or ""
    assert gecmis.splitlines() == [
        "Kullanıcı: soru-0",
        "Asistan: cevap-0",
        "Asistan: derin-1",
    ]


def test_oneri_bayragi_kapaliyken_worker_kural_onerisi_hesaplamaz(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bayrak kuyrukta bekleyen öneri kipi işinden sonra kapanırsa model kural önerisi görmez."""
    monkeypatch.setenv("TP_ASISTAN_ONERI", "off")

    def oturum_yok() -> Any:
        pytest.fail("bayrak kapalıyken öneri motoru çağrılmamalı")

    m = flow.Mesaj(
        id=uuid.uuid4(),
        sohbet_id=uuid.uuid4(),
        kullanici_id=uuid.uuid4(),
        kullanici_adi="t",
        rol="tester",
        sira=2,
        icerik="?",
        baglam={"rota_kalibi": "/gereksinimler/:id"},
        kip="oneri",
        tetik="kullanici",
        amac=None,
        ust_mesaj_id=None,
        job_id=None,
        oneri_kural_id=None,
    )
    assert flow._kural_onerileri(oturum_yok, m) == []


def test_oneri_kipi_kural_onerileri_untrusted_ve_son_islem(
    client: TestClient, make_user, engine: Engine, veri
) -> None:
    giris(client, make_user("analyst"))
    baglam = {
        "rota": f"/gereksinimler/{veri['req']}",
        "varlik": {"tur": "requirement", "id": str(veri["req"])},
    }
    _, mid = soru_gonder(client, engine, "", baglam=baglam, kip="oneri")
    taslak = {"tur": "Task", "ozet": "Takip https://evil.example", "aciklama": "@ali bak"}
    gecit = Gecit(
        engine,
        [
            bitir(
                guven="dusuk",
                oneriler=[
                    {
                        "baslik": f"Ek {i}",
                        "neden": "n",
                        "eylem": {
                            "tur": "jira_taslak",
                            "rota": None,
                            "anahtar": None,
                            "taslak": taslak,
                        },
                    }
                    for i in range(5)
                ],
            )
        ],
    )
    assert cevapla(engine, mid, gecit) == "done"
    assert 'kind=\\"oneriler\\"' in gecit.ilk_istek() and "kip=oneri" in gecit.ilk_istek()
    m = mesaj(engine, mid)
    oneriler = m["cevap"]["oneriler"]
    assert len(oneriler) == 3
    assert all("http" not in o["eylem"]["taslak"]["ozet"] for o in oneriler)
    assert all("@ali" not in o["eylem"]["taslak"]["aciklama"] for o in oneriler)
    # Öneri kipinde "Emin değil" olsa da otomatik yükseltme yok.
    assert m["cevap"]["guven_gosterimi"] == sonislem.EMIN_DEGIL
    assert cocuklar(engine, mid) == []


def test_neden_sor_oneri_baglami_sunucuda_yeniden_uretilir(
    client: TestClient, make_user, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.assistant import api as asistan_api
    from tp_core.features.assistant import oneri

    monkeypatch.setattr(asistan_api, "oneri_gecerli_mi", lambda *a, **k: True)
    monkeypatch.setattr(
        oneri,
        "oneri_baglami",
        lambda *a, **k: {
            "kural_id": "gereksinim-po-bekliyor",
            "baslik": "PO 3 gündür bekliyor",
            "neden": "Case üretimi bekler.",
            "aciklama": "uzun",
        },
    )
    giris(client, make_user("analyst"))
    _, mid = soru_gonder(
        client,
        engine,
        "Bu öneriyi neden yapmalıyım?",
        baglam={"rota": "/gereksinimler", "oneri": {"baslik": "istemci metni"}},
        oneri_kural_id="gereksinim-po-bekliyor",
    )
    gecit = Gecit(engine, [bitir()])
    assert cevapla(engine, mid, gecit) == "done"
    ilk = gecit.ilk_istek()
    assert "PO 3 gündür bekliyor" in ilk and "istemci metni" not in ilk


@pytest.mark.parametrize("bayrak", ["0", "1"])
def test_oneri_sohbeti_baglam_kurulamazsa_sozluk_dali_calisir(
    bayrak: str,
    client: TestClient,
    make_user,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Öneriden açılan sohbette bayrak sonradan kapanırsa (`0`) ya da öneri artık geçerli
    değilse (`1`, motor None döner) öneri bağlamı yoktur: hata sözlüğüyle cevaplanabilen soru
    sözlükten cevaplanır (model kapalıyken "kapalı" sabit cevabına düşmez)."""
    from tp_core.features.assistant import api as asistan_api
    from tp_core.features.assistant import oneri

    monkeypatch.setattr(asistan_api, "oneri_gecerli_mi", lambda *a, **k: True)
    giris(client, make_user("analyst"))
    baglam = {
        "rota": "/gereksinimler",
        "son_hata": {
            "uc": "POST /cases/:id/review",
            "status": 409,
            "kod": "onay_hash_uyusmuyor",
            "detail": "İçerik değişti, yeniden inceleyin.",
        },
    }
    _, mid = soru_gonder(
        client,
        engine,
        "Az önceki hata ne demek?",
        baglam=baglam,
        model_hazir=False,
        oneri_kural_id="gereksinim-po-bekliyor",
    )
    monkeypatch.setenv("TP_ASISTAN_ONERI", bayrak)
    if bayrak == "1":
        monkeypatch.setattr(oneri, "oneri_baglami", lambda *a, **k: None)
    assert cevapla(engine, mid) == "done"
    assert mesaj(engine, mid)["kaynak"] == "sozluk"


def test_oneri_sohbeti_baglam_varsa_sozluk_atlanir(
    client: TestClient, make_user, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.assistant import api as asistan_api
    from tp_core.features.assistant import oneri

    monkeypatch.setattr(asistan_api, "oneri_gecerli_mi", lambda *a, **k: True)
    monkeypatch.setattr(
        oneri,
        "oneri_baglami",
        lambda *a, **k: {"kural_id": "gereksinim-po-bekliyor", "baslik": "b", "neden": "n"},
    )
    giris(client, make_user("analyst"))
    baglam = {
        "rota": "/gereksinimler",
        "son_hata": {"uc": "POST /cases/:id/review", "status": 409, "kod": "onay_hash_uyusmuyor"},
    }
    _, mid = soru_gonder(
        client,
        engine,
        "Az önceki hata ne demek?",
        baglam=baglam,
        model_hazir=False,
        oneri_kural_id="gereksinim-po-bekliyor",
    )
    assert cevapla(engine, mid) == "done"
    assert mesaj(engine, mid)["kaynak"] == "kapali"


# ------------------------------------------------------------------ iptal, hata, yarış


def test_pending_iptal_edilmis_mesaj_baslatilmaz(
    client: TestClient, make_user, engine: Engine
) -> None:
    giris(client, make_user("analyst"))
    _, mid = soru_gonder(client, engine, KIRARAK, baglam=GRI_BAGLAM)
    assert client.post(f"/assistant/messages/{mid}/cancel").json()["durum"] == "iptal"
    assert cevapla(engine, mid) is None
    assert mesaj(engine, mid)["durum"] == "iptal"


def test_kosarken_iptal_harcama_yazilir_durum_iptal_kalir(
    client: TestClient, make_user, engine: Engine
) -> None:
    giris(client, make_user("analyst"))
    _, mid = soru_gonder(client, engine, KIRARAK, baglam=GRI_BAGLAM)

    def iptal_et(_req: ProviderRequest) -> Any:
        with engine.begin() as c:  # kullanıcı tur sürerken "Durdur"a bastı
            c.execute(text("UPDATE asistan_mesaj SET durum = 'iptal' WHERE id = :i"), {"i": mid})
        return tool_response(("product_search", {"query": "Kırarak"}))

    gecit = Gecit(engine, [iptal_et, bitir()])
    assert cevapla(engine, mid, gecit) == "iptal"
    m = mesaj(engine, mid)
    assert (m["durum"], m["hata_kodu"], m["cevap"]) == ("iptal", None, None)
    assert m["maliyet_usd"] > 0 and m["token_girdi"] == 100 and m["sure_ms"] is not None
    assert len(gecit.saglayici.requests) == 1  # ikinci (ücretli) tur açılmadı


def test_gec_biten_is_sonucu_ezmez(client: TestClient, make_user, engine: Engine) -> None:
    giris(client, make_user("analyst"))
    _, mid = soru_gonder(client, engine, KIRARAK, baglam=GRI_BAGLAM)

    def uzlastirildi(_req: ProviderRequest) -> Any:
        with engine.begin() as c:  # zaman aşımı uzlaştırması mesajı kapattı
            c.execute(
                text(
                    "UPDATE asistan_mesaj SET durum = 'error', hata_kodu = 'zaman_asimi' "
                    "WHERE id = :i"
                ),
                {"i": mid},
            )
        return bitir()

    assert cevapla(engine, mid, Gecit(engine, [uzlastirildi])) == "error"
    m = mesaj(engine, mid)
    assert (m["durum"], m["hata_kodu"], m["cevap"]) == ("error", "zaman_asimi", None)


@pytest.mark.parametrize(
    ("hazirlik", "beklenen"),
    [
        ("saglayici", "model_hatasi"),
        ("butce", "butce_asildi"),
        ("girdi", "girdi_tavani"),
        ("sure", "zaman_asimi"),
    ],
)
def test_istisna_siniflari_serit_yasar_kayitta_ayrinti_yok(
    client: TestClient,
    make_user,
    engine: Engine,
    caplog: pytest.LogCaptureFixture,
    hazirlik: str,
    beklenen: str,
) -> None:
    u = make_user("analyst")
    giris(client, u)
    _, mid = soru_gonder(client, engine, KIRARAK, baglam=GRI_BAGLAM)
    gizli = "gizli-ayrinti-" + "sk-" + "ant-" + "x" * 20
    kw: dict[str, Any] = {}
    script: list[Any] = [bitir()]
    if hazirlik == "saglayici":
        script = [ProviderPermanentError(f"400 {gizli}", status=400)]
    elif hazirlik == "butce":
        ai_call_ekle(engine, "1.00", kullanici_id=u.id)
    elif hazirlik == "girdi":
        script = [
            tool_response(("product_search", {"query": "x"}), input_tokens=50_000),
            bitir(),
        ]
    else:
        kw["saat"] = lambda: time.monotonic() - 200  # bitiş geçmişte
    caplog.set_level(logging.DEBUG)
    assert cevapla(engine, mid, Gecit(engine, script), **kw) == "error"
    m = mesaj(engine, mid)
    assert (m["durum"], m["hata_kodu"]) == ("error", beklenen)
    assert gizli not in caplog.text and "Kırarak" not in caplog.text
    # Şerit yaşar: sonraki soru (bütçe vakasında tavanı dolmamış başka kullanıcı) cevaplanır.
    is_bitir(engine, mid)
    giris(client, make_user("analyst"))
    _, yeni = soru_gonder(client, engine, "Script ekranı ne yapar?", baglam=GRI_BAGLAM)
    assert cevapla(engine, yeni, Gecit(engine, dogrulanmis_kaynak())) == "done"


# ------------------------------------------------------------------ otomatik yükseltme


def _yukseltilen(client: TestClient, engine: Engine, script: list[Any], **kw: Any) -> str:
    _, mid = soru_gonder(client, engine, KIRARAK, baglam=GRI_BAGLAM)
    assert cevapla(engine, mid, Gecit(engine, script), **kw) == "done"
    return mid


@pytest.mark.parametrize(
    "senaryo",
    ["emin_degil", "kismen_urune_ozgu", "toparlama"],
)
def test_otomatik_yukseltme_cocuk_ve_is_ayni_transactionda(
    client: TestClient, make_user, engine: Engine, senaryo: str
) -> None:
    u = make_user("tester")
    giris(client, u)
    if senaryo == "emin_degil":
        script = [bitir(guven="dusuk")]
    elif senaryo == "kismen_urune_ozgu":
        script = [bitir(kaynaklar=[{"tur": "genel_bilgi", "ref": "", "alinti": ""}])]
    else:  # 5 araç turu → toparlama nudge'ı → 6. turda doğrulanmış kaynakla bitse de "Emin değil"
        script = [
            tool_response(("product_read", {"path": "review-portal/src/pages/Script.tsx"}))
            for _ in range(5)
        ] + [dogrulanmis_kaynak()[1]]
    mid = _yukseltilen(client, engine, script)
    ust = mesaj(engine, mid)
    assert ust["durum"] == "done"
    if senaryo == "toparlama":
        assert ust["cevap"]["toparlama"] is True
    cocuk = cocuklar(engine, mid)
    assert len(cocuk) == 1
    c = cocuk[0]
    assert (c["durum"], c["amac"], c["tetik"], c["kip"]) == (
        "pending",
        "assistant_deep",
        "otomatik",
        "soru",
    )
    assert c["sira"] == ust["sira"] + 1 and c["icerik"] == ust["icerik"]
    assert c["baglam"] == ust["baglam"]
    with engine.connect() as cn:
        j = cn.execute(
            text("SELECT yuk, idempotency_key, max_deneme FROM job WHERE id = :j"),
            {"j": c["job_id"]},
        ).one()
    assert j.yuk == {"mesaj_id": str(c["id"]), "kullanici_id": str(u.id), "tetik": "otomatik"}
    assert j.idempotency_key == f"assistant.answer:{c['id']}" and j.max_deneme == 1


@pytest.mark.parametrize(
    "neden",
    [
        "dogrulandi",
        "eylem_reddi",
        "bayrak_kapali",
        "oneri_kipi",
        "derin_cocuk",
        "elle_derin",
        "model_hatasi",
        "genel_bilgi",
    ],
)
def test_otomatik_yukseltme_tetiklenmez(
    client: TestClient, make_user, engine: Engine, monkeypatch: pytest.MonkeyPatch, neden: str
) -> None:
    """§13: dışlamaların her biri ayrı; "Emin değil" cevabı bile çocuk üretmez."""
    giris(client, make_user("engineer"))
    script: list[Any] = [bitir(guven="dusuk")]
    if neden == "dogrulandi":
        script = dogrulanmis_kaynak()
    elif neden == "eylem_reddi":
        script = [bitir(guven="dusuk", eylem_reddi=True)]
    elif neden == "bayrak_kapali":
        monkeypatch.setenv("TP_ASISTAN_OTOMATIK_DERIN", "0")
    elif neden == "model_hatasi":
        script = [RuntimeError("sağlayıcı düştü")]
    if neden == "oneri_kipi":  # öneri kipi asla yükseltilmez
        _, mid = soru_gonder(client, engine, "", baglam={"rota": "/gereksinimler"}, kip="oneri")
        assert cevapla(engine, mid, Gecit(engine, script)) == "done"
        assert mesaj(engine, mid)["cevap"]["guven_gosterimi"] == sonislem.EMIN_DEGIL
    elif neden in ("derin_cocuk", "elle_derin"):  # assistant_deep asla yükseltilmez
        if neden == "derin_cocuk":  # otomatik çocuk "Emin değil" biter → torun yok
            ust = _yukseltilen(client, engine, [bitir(guven="dusuk")])
            mid = str(cocuklar(engine, ust)[0]["id"])
        else:  # elle "Daha ayrıntılı" (doğrulanmış model cevabının altı)
            sohbet, ust = soru_gonder(client, engine, KIRARAK, baglam=GRI_BAGLAM)
            assert cevapla(engine, ust, Gecit(engine, dogrulanmis_kaynak())) == "done"
            r = sor(client, sohbet, ust_mesaj_id=ust)
            assert r.status_code == 202, r.text
            mid = r.json()["mesaj_id"]
        is_bitir(engine, ust)
        assert mesaj(engine, mid)["amac"] == "assistant_deep"
        assert cevapla(engine, mid, Gecit(engine, script)) == "done"
        assert mesaj(engine, mid)["cevap"]["guven_gosterimi"] == sonislem.EMIN_DEGIL
    elif neden == "model_hatasi":
        _, mid = soru_gonder(client, engine, KIRARAK, baglam=GRI_BAGLAM)
        assert cevapla(engine, mid, Gecit(engine, script)) == "error"
    elif neden == "genel_bilgi":  # S9: ürüne özgü olmayan soru, araçsız genel bilgi cevabı
        _, mid = soru_gonder(client, engine, "Flaky test nasıl ayıklanır?")
        genel = [bitir(guven="orta", kaynaklar=[{"tur": "genel_bilgi", "ref": "", "alinti": ""}])]
        assert cevapla(engine, mid, Gecit(engine, genel)) == "done"
        cevap = mesaj(engine, mid)["cevap"]
        assert (cevap["urune_ozgu"], cevap["guven_gosterimi"]) == (False, sonislem.GENEL_BILGI)
    else:
        mid = _yukseltilen(client, engine, script)
    if neden == "eylem_reddi":  # S7: model bağlantı vermese de ret ekran bağlantısı taşır
        cevap = mesaj(engine, mid)["cevap"]
        assert [y["rota"] for y in cevap["yonlendirmeler"]] == ["/kod"]
    assert cocuklar(engine, mid) == []
    assert "derin_onerilir" not in (mesaj(engine, mid)["cevap"] or {})


@pytest.mark.parametrize("dal", ["sozluk", "sablon", "kapali"])
def test_modelsiz_dallar_otomatik_tetige_ulasmaz(
    client: TestClient,
    make_user,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    veri: dict[str, Any],
    dal: str,
) -> None:
    """Sözlük/şablon/kapalı cevaplar otomatik yükseltme kararına hiç girmez (§13)."""

    def cagrilmamali(*_: Any) -> bool:
        pytest.fail("modelsiz dalda otomatik tetik değerlendirilmemeli")

    monkeypatch.setattr(flow, "otomatik_tetik", cagrilmamali)
    giris(client, make_user("analyst"))
    if dal == "sozluk":
        _, mid = soru_gonder(
            client, engine, "Bu mesaj ne?", baglam={"son_hata": {"kod": "kapi_kapali"}}
        )
    elif dal == "sablon":
        _, mid = soru_gonder(client, engine, "TPD-3 neden bekliyor?")
    else:
        _, mid = soru_gonder(client, engine, KIRARAK, baglam=GRI_BAGLAM, model_hazir=False)
    assert cevapla(engine, mid) == "done"
    assert mesaj(engine, mid)["kaynak"] == dal
    assert cocuklar(engine, mid) == []


def _kosan(client: TestClient, engine: Engine) -> flow.Mesaj:
    _, mid = soru_gonder(client, engine, KIRARAK, baglam=GRI_BAGLAM)
    basla = flow._baslat(fabrika(engine), uuid.UUID(mid))
    assert basla is not None
    return basla[0]


EMIN_DEGIL_CEVAP = {
    **sonislem.bos_cevap(),
    "guven": "dusuk",
    "guven_gosterimi": sonislem.EMIN_DEGIL,
    "urune_ozgu": True,
}
HARCAMA = flow.Harcama(Decimal("0.004"), 10, 5)


@pytest.mark.parametrize(
    "kosul",
    ["kullanici", "asistan", "kok_soru", "genel", "global_dolu"],
)
def test_otomatik_yukseltme_her_on_kosul_ayri(
    client: TestClient,
    make_user,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    kosul: str,
) -> None:
    u = make_user("analyst")
    giris(client, u)
    m = _kosan(client, engine)
    if kosul == "kullanici":
        ai_call_ekle(engine, "0.81", kullanici_id=u.id)  # kalan 0.19 < 0.20
    elif kosul == "asistan":
        ai_call_ekle(engine, "9.81", kullanici_id=uuid.uuid4())
    elif kosul == "kok_soru":
        ai_call_ekle(engine, "0.31", call_id=flow._cagri_kimligi(m))  # soru başı kalan 0.19
    elif kosul == "genel":
        monkeypatch.setattr(budget, "genel_gunluk_sinir_usd", lambda: Decimal("0.10"))
    else:
        with engine.begin() as c:
            for _ in range(budget.global_sinir()):
                c.execute(
                    text(
                        "INSERT INTO job (tur, yuk, durum) VALUES ('assistant.answer', "
                        "CAST(:y AS jsonb), 'queued')"
                    ),
                    {"y": json.dumps({"kullanici_id": str(uuid.uuid4()), "tetik": "kullanici"})},
                )
    assert flow.model_cevabini_yaz(fabrika(engine), m, dict(EMIN_DEGIL_CEVAP), HARCAMA) == "done"
    assert cocuklar(engine, m.id) == []
    ust = mesaj(engine, m.id)
    assert ust["durum"] == "done" and ust["cevap"]["derin_onerilir"] is True


def test_on_kosullar_tutarsa_kendi_isi_global_sayimdan_duser(
    client: TestClient, make_user, engine: Engine
) -> None:
    giris(client, make_user("analyst"))
    m = _kosan(client, engine)
    with engine.begin() as c:  # kendi işi dahil sınırın tam altında: kendi işi sayılmaz
        for _ in range(budget.global_sinir() - 1):
            c.execute(
                text(
                    "INSERT INTO job (tur, yuk, durum) VALUES ('assistant.answer', "
                    "CAST(:y AS jsonb), 'queued')"
                ),
                {"y": json.dumps({"kullanici_id": str(uuid.uuid4()), "tetik": "kullanici"})},
            )
    assert flow.model_cevabini_yaz(fabrika(engine), m, dict(EMIN_DEGIL_CEVAP), HARCAMA) == "done"
    assert len(cocuklar(engine, m.id)) == 1


def test_otomatik_cocuk_kullaniciyi_kilitlemez_ve_saatlik_sayima_girmez(
    client: TestClient, make_user, engine: Engine
) -> None:
    u = make_user("tester")
    giris(client, u)
    sohbet, mid = soru_gonder(client, engine, KIRARAK, baglam=GRI_BAGLAM)
    with engine.connect() as c:
        once = budget.saatlik_soru(c, u.id)
    assert cevapla(engine, mid, Gecit(engine, [bitir(guven="dusuk")])) == "done"
    cocuk = cocuklar(engine, mid)[0]
    is_bitir(engine, mid)
    with engine.connect() as c:
        assert budget.saatlik_soru(c, u.id) == once
    # Otomatik çocuk koşarken (pending) yeni soru → 202.
    r = sor(client, sohbet, soru="Başka bir şey soracağım")
    assert r.status_code == 202, r.text
    # Elle "Daha ayrıntılı" → 409 zaten_derin (unique(ust_mesaj_id)).
    r = sor(client, sohbet, ust_mesaj_id=mid)
    assert r.status_code == 409 and r.json()["kod"] == "zaten_derin"
    # Çocuk iptali olağan kurallarla; iptal edilen çocuk başlatılmaz.
    assert client.post(f"/assistant/messages/{cocuk['id']}/cancel").json()["durum"] == "iptal"
    assert cevapla(engine, str(cocuk["id"])) is None


def test_otomatik_cocuk_cevaplanir_ve_kok_soru_harcamasi_cocugu_icerir(
    client: TestClient, make_user, engine: Engine
) -> None:
    giris(client, make_user("tester"))
    _, mid = soru_gonder(client, engine, KIRARAK, baglam=GRI_BAGLAM)
    assert cevapla(engine, mid, Gecit(engine, [bitir(guven="dusuk")])) == "done"
    cocuk = cocuklar(engine, mid)[0]
    is_bitir(engine, mid)
    gecit = Gecit(engine, dogrulanmis_kaynak())
    assert cevapla(engine, str(cocuk["id"]), gecit) == "done"
    assert gecit.butce.kok_id == uuid.UUID(mid)  # çocuğun bütçesi kök soruya bağlı
    c = mesaj(engine, cocuk["id"])
    assert (c["amac"], c["durum"]) == ("assistant_deep", "done")
    with engine.connect() as cn:
        toplam = budget.soru_harcamasi_usd(cn, uuid.UUID(mid))
    assert toplam == mesaj(engine, mid)["maliyet_usd"] + c["maliyet_usd"]


def test_tetik_kontrol_kisiti_ust_mesajsiz_otomatigi_reddeder(
    client: TestClient, make_user, engine: Engine
) -> None:
    from sqlalchemy.exc import IntegrityError

    u = make_user("analyst")
    giris(client, u)
    sohbet = sohbet_ac(client)
    with pytest.raises(IntegrityError), engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO asistan_mesaj (sohbet_id, kullanici_id, sira, rol, amac, tetik) "
                "VALUES (:s, :k, 1, 'assistant', 'assistant_deep', 'otomatik')"
            ),
            {"s": sohbet, "k": u.id},
        )


def kilitte_bekler(db: Db, adet: int, *, sure: float = 15.0) -> bool:
    """En az `adet` oturum kilitte (`wait_event_type = 'Lock'`) bekleyene dek yoklar.

    Sabit `sleep` yerine olumlu kanıt: yavaş makinede kilide henüz ulaşmamış iş parçacığı da
    `is_alive()` döner, yarış sınanmadan test yeşil geçerdi. Başka rollerin bekleme olayını
    yalnız süper kullanıcı görür (sahip/uygulama rolü için `wait_event` NULL döner)."""
    sahip = create_engine(db.srv.url("postgres", db.name))
    try:
        son = time.monotonic() + sure
        while time.monotonic() < son:
            with sahip.connect() as c:
                n = c.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                        "AND wait_event_type = 'Lock'"
                    )
                ).scalar_one()
            if n >= adet:
                return True
            time.sleep(0.02)
        return False
    finally:
        sahip.dispose()


def test_ust_iptali_yukseltmeyle_eszamanli_cocuk_yok_harcama_yazilir(
    client: TestClient, make_user, engine: Engine, db: Db
) -> None:
    giris(client, make_user("analyst"))
    m = _kosan(client, engine)
    kilitli = engine.connect()
    tx = kilitli.begin()
    kilitli.execute(text("SELECT 1 FROM asistan_mesaj WHERE id = :i FOR UPDATE"), {"i": m.id})
    sonuc: dict[str, Any] = {}

    def yaz() -> None:
        sonuc["durum"] = flow.model_cevabini_yaz(
            fabrika(engine), m, dict(EMIN_DEGIL_CEVAP), HARCAMA
        )

    t = threading.Thread(target=yaz)
    t.start()
    assert kilitte_bekler(db, 1)  # yükseltme transaction'ı satır kilidinde bekliyor
    assert t.is_alive()
    kilitli.execute(text("UPDATE asistan_mesaj SET durum = 'iptal' WHERE id = :i"), {"i": m.id})
    tx.commit()
    kilitli.close()
    t.join(15)
    assert sonuc["durum"] == "iptal"
    ust = mesaj(engine, m.id)
    assert (ust["durum"], ust["cevap"]) == ("iptal", None)
    assert ust["maliyet_usd"] == Decimal("0.004") and ust["token_girdi"] == 10
    assert cocuklar(engine, m.id) == []


def test_api_post_ile_yukseltme_eszamanli_deadlock_yok(
    sunucu: str, make_user, engine: Engine, db: Db
) -> None:
    from tp_core.auth.login import THROTTLE

    THROTTLE._kayit.clear()
    kalp_atisi(engine, mod="live", model_hazir=True)
    sahip, diger = make_user("analyst"), make_user("tester")
    c1, c2 = _giris_istemcisi(sunucu, sahip), _giris_istemcisi(sunucu, diger)
    try:
        s1 = c1.post("/assistant/conversations", json={}).json()["id"]
        r = c1.post(
            f"/assistant/conversations/{s1}/messages", json={"soru": KIRARAK, "baglam": GRI_BAGLAM}
        )
        mid = uuid.UUID(r.json()["mesaj_id"])
        basla = flow._baslat(fabrika(engine), mid)
        assert basla is not None
        m = basla[0]
        s2 = c2.post("/assistant/conversations", json={}).json()["id"]
        # Global kilidi tutup iki transaction'ı aynı anda kilitte bekletiriz.
        kilit = engine.connect()
        tx = kilit.begin()
        budget.global_kilit(kilit)
        sonuc: dict[str, Any] = {}

        def yukselt() -> None:
            sonuc["yukselt"] = flow.model_cevabini_yaz(
                fabrika(engine), m, dict(EMIN_DEGIL_CEVAP), HARCAMA
            )

        def post() -> None:
            sonuc["post"] = c2.post(f"/assistant/conversations/{s2}/messages", json={"soru": "x"})

        isler = [threading.Thread(target=yukselt), threading.Thread(target=post)]
        for t in isler:
            t.start()
        assert kilitte_bekler(db, 2)  # ikisi de kilitte
        assert all(t.is_alive() for t in isler)
        tx.commit()
        kilit.close()
        for t in isler:
            t.join(20)
    finally:
        c1.close()
        c2.close()
    assert sonuc["yukselt"] == "done"
    assert isinstance(sonuc["post"], httpx.Response) and sonuc["post"].status_code == 202
    assert len(cocuklar(engine, mid)) == 1


# ------------------------------------------------------------------ yan etkisizlik


HARIC_TABLOLAR = frozenset(
    {"asistan_sohbet", "asistan_mesaj", "ai_call", "tool_call", "job", "audit_event"}
)


def _anlik(db: Db) -> dict[str, tuple[int, str]]:
    sahip = create_engine(db.owner_url)
    try:
        with sahip.connect() as c:
            tablolar = c.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars()
            out = {}
            for t in sorted(tablolar):
                if t in HARIC_TABLOLAR:
                    continue
                satir = c.execute(
                    text(
                        f"SELECT count(*), md5(COALESCE(string_agg(x::text, '|' "
                        f"ORDER BY x::text), '')) FROM \"{t}\" x"
                    )
                ).one()
                out[t] = (int(satir[0]), str(satir[1]))
            return out
    finally:
        sahip.dispose()


def test_yan_etkisizlik_soru_oneri_ve_otomatik_yukseltme(
    client: TestClient, make_user, engine: Engine, db: Db, veri
) -> None:
    u = make_user("analyst")
    giris(client, u)
    kalp_atisi(engine, mod="live", model_hazir=True)
    sohbet = sohbet_ac(client)
    once = _anlik(db)
    akislar: list[tuple[str, dict[str, Any], list[Any] | None]] = [
        ("Bu hata ne demek?", {"son_hata": {"kod": "kapi_kapali"}}, None),  # sözlük
        ("TPD-3 neden bekliyor?", {}, None),  # şablon
        (
            "TPD-3'te PO ne yazmış, ayrıntılı anlat",
            {},
            [
                tool_response(("probe_get", {"tur": "requirement", "id_or_key": "TPD-3"})),
                tool_response(("jira_issue", {"anahtar": "TPD-3"})),
                tool_response(("db_query", {"sql": "SELECT 1"})),
                bitir(),
            ],
        ),
        (KIRARAK, GRI_BAGLAM, [bitir(guven="dusuk")]),  # otomatik yükseltme
    ]
    for soru, baglam, script in akislar:
        r = sor(client, sohbet, soru=soru, baglam=baglam or None)
        assert r.status_code == 202, r.text
        mid = r.json()["mesaj_id"]
        assert cevapla(engine, mid, Gecit(engine, script) if script else yasak_gecit) == "done"
        is_bitir(engine, mid)
        # Otomatik yükseltme çocuğu gerçekten koşar (assistant_deep: araç çağrıları, son işlem);
        # yan etkileri de aşağıdaki anlık görüntüye girer.
        for cocuk in cocuklar(engine, mid):
            assert cocuk["amac"] == "assistant_deep"
            assert cevapla(engine, str(cocuk["id"]), Gecit(engine, dogrulanmis_kaynak())) == "done"
            is_bitir(engine, cocuk["id"])
    assert any(
        c["tetik"] == "otomatik" and c["durum"] == "done"
        for c in cocuklar(engine, mid)  # son akış otomatik yükseltmeydi
    )
    r = sor(
        client,
        sohbet,
        soru="",
        kip="oneri",
        baglam={
            "rota": f"/gereksinimler/{veri['req']}",
            "varlik": {"tur": "requirement", "id": str(veri["req"])},
        },
    )
    assert r.status_code == 202, r.text
    oneri_mid = r.json()["mesaj_id"]
    assert cevapla(engine, oneri_mid, Gecit(engine, [bitir()])) == "done"
    assert _anlik(db) == once
    # §13 "Migrasyon/denetim": soru, öneri, otomatik yükseltme ve geri bildirimlerden sonra
    # denetim zinciri bütün kalır.
    r = client.post(f"/assistant/messages/{oneri_mid}/feedback", json={"deger": 1})
    assert r.status_code == 200, r.text
    r = client.post(
        "/assistant/suggestions/gereksinim-bulgu-karari/feedback",
        json={"deger": 1, "varlik_id": str(veri["req"])},
    )
    assert r.status_code == 200, r.text
    with engine.connect() as c:
        assert verify_chain(c).ok
    # Aynı doğrulama uç üzerinden (yetki, serileştirme, çapalar dahil).
    r = client.get("/audit", params={"verify": "true"})
    assert r.status_code == 200, r.text
    dogrulama = r.json()["verify"]
    assert dogrulama["ok"] is True and dogrulama["broken_at"] is None
    assert dogrulama["anchors"] is None or dogrulama["anchors"]["broken"] == []


def test_hata_kodu_eslemesi() -> None:
    from tp_core.gateway.errors import AgentDeadlineExceeded, AgentStopped, BudgetExceeded

    assert flow.hata_kodu(AgentStopped("x")) is None
    assert flow.hata_kodu(BudgetExceeded("ajan girdi token'ı", 1, 1)) == "girdi_tavani"
    assert flow.hata_kodu(BudgetExceeded("kullanıcı günlük", 1, 1)) == "butce_asildi"
    assert flow.hata_kodu(AgentDeadlineExceeded("x")) == "zaman_asimi"
    assert flow.hata_kodu(RuntimeError("x")) == "model_hatasi"


def test_principal_ve_rol_oturumdan(client: TestClient, make_user, engine: Engine) -> None:
    """Rol bağlamdan değil oturum kullanıcısından okunur (§5.5)."""
    u: Principal = make_user("presenter")
    giris(client, u)
    _, mid = soru_gonder(
        client, engine, "Script ekranı ne yapar?", baglam={**GRI_BAGLAM, "rol": "analyst"}
    )
    gecit = Gecit(engine, [bitir()])
    assert cevapla(engine, mid, gecit) == "done"
    assert "Kullanıcının rolü: Sunucu (sunum yapan)" in gecit.ilk_istek()


def _saf_mesaj(**ek: Any) -> flow.Mesaj:
    alanlar: dict[str, Any] = {
        "id": uuid.uuid4(),
        "sohbet_id": uuid.uuid4(),
        "kullanici_id": uuid.uuid4(),
        "kullanici_adi": "t",
        "rol": "tester",
        "sira": 1,
        "icerik": "Kontrol Kulesi'ndeki pass@1 bu hafta neden düştü?",
        "baglam": None,
        "kip": "soru",
        "tetik": "kullanici",
        "amac": None,
        "ust_mesaj_id": None,
        "job_id": None,
        "oneri_kural_id": None,
    }
    alanlar.update(ek)
    return flow.Mesaj(**alanlar)


def _dogrulanmis_cevap(metin: str, *, urune_ozgu: bool = True, **ek: Any) -> dict[str, Any]:
    return {
        **sonislem.bos_cevap(),
        "guven": "orta",
        "guven_gosterimi": sonislem.DOGRULANDI,
        "urune_ozgu": urune_ozgu,
        "cevap_bloklari": [{"tur": "paragraf", "metin": metin, "maddeler": []}],
        **ek,
    }


@pytest.mark.parametrize(
    "metin",
    [
        # Canlı eval s13 (Haiku, 2026-11-12): güven orta + rozet doğrulandı + metinde belirsizlik.
        "Hariç tutulanları kodda doğruladım. Düşüşün nedenini araçlarla doğrulayamadım; emin "
        "değilim.",
        "EMİN DEĞİLİM: haftalık veriyi göremedim.",
        "Bu ayrıntıyı teyit edemedim.",
        "Nedenini bilmiyorum.",
        # Tur 3 güvenlik #11: ASCII yazım.
        "Bundan emin degilim.",
        "Nedenini dogrulayamadim.",
        "EMIN DEGILIM.",
    ],
)
def test_otomatik_tetik_metindeki_belirsizlik(monkeypatch: pytest.MonkeyPatch, metin: str) -> None:
    monkeypatch.delenv(flow.ORTAM_OTOMATIK_DERIN, raising=False)
    assert flow.otomatik_tetik(_saf_mesaj(), _dogrulanmis_cevap(metin)) is True


def test_otomatik_tetik_madde_icindeki_belirsizlik(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(flow.ORTAM_OTOMATIK_DERIN, raising=False)
    cevap = _dogrulanmis_cevap("Adımlar:")
    cevap["cevap_bloklari"][0]["maddeler"] = ["Payda kuralı doğrulandı.", "Düşüşten emin değilim."]
    assert flow.otomatik_tetik(_saf_mesaj(), cevap) is True


@pytest.mark.parametrize(
    ("metin", "ek", "mesaj_ek"),
    [
        # Belirsizlik yok.
        ("Hariç tutulanlar kodda doğrulandı.", {}, {}),
        # Kullanıcıya yönelik kalıp birinci tekil belirsizlik değildir.
        ("Emin değilseniz Kontrol Kulesi'ne bakın.", {}, {}),
        ("Emin degilseniz Kontrol Kulesi'ne bakın.", {}, {}),
        # Genel (ürüne özgü olmayan) soru: metin tetiklemez.
        ("Emin değilim.", {"urune_ozgu": False}, {}),
        # Eylem reddi tetiklemez.
        ("Emin değilim.", {"eylem_reddi": True}, {}),
        # Derin (ayrıntılı) cevap ve öneri kipi tetiklemez.
        ("Emin değilim.", {}, {"amac": flow.DERIN_AMAC}),
        ("Emin değilim.", {}, {"kip": "oneri"}),
    ],
)
def test_otomatik_tetik_belirsizlik_disi(
    monkeypatch: pytest.MonkeyPatch, metin: str, ek: dict[str, Any], mesaj_ek: dict[str, Any]
) -> None:
    monkeypatch.delenv(flow.ORTAM_OTOMATIK_DERIN, raising=False)
    urune_ozgu = ek.pop("urune_ozgu", True)
    cevap = _dogrulanmis_cevap(metin, urune_ozgu=urune_ozgu, **ek)
    assert flow.otomatik_tetik(_saf_mesaj(**mesaj_ek), cevap) is False


def test_otomatik_tetik_son_islem_notu_sayilmaz(monkeypatch: pytest.MonkeyPatch) -> None:
    """Son işlemin eklediği not (`notlar`) modelin belirsizliği değildir; yalnız bloklar sayılır."""
    monkeypatch.delenv(flow.ORTAM_OTOMATIK_DERIN, raising=False)
    cevap = _dogrulanmis_cevap("Doğrulandı.", notlar=[sonislem.NOT_EMIN_DEGILIM])
    assert flow.otomatik_tetik(_saf_mesaj(), cevap) is False


def test_otomatik_tetik_ortamdan_kapali(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(flow.ORTAM_OTOMATIK_DERIN, "off")
    assert flow.otomatik_tetik(_saf_mesaj(), _dogrulanmis_cevap("Emin değilim.")) is False


def test_derin_mesaj_fonksiyon_tanimi_yonergesi() -> None:
    derin = _saf_mesaj(ust_mesaj_id=uuid.uuid4(), amac=flow.DERIN_AMAC)
    icerik = flow.ilk_mesaj(derin, ekran=None, kural_onerileri=None, gecmis=None)[0].content
    assert "çağrılan fonksiyonların tanımını açıp kaynak göster" in icerik
    kisa = flow.ilk_mesaj(_saf_mesaj(), ekran=None, kural_onerileri=None, gecmis=None)[0].content
    assert "tanımını açıp" not in kisa
