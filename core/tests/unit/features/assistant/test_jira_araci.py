"""`jira_issue` aracı (AI-ASISTAN-PLANI §5.6, §13 "Jira/CI araçları" ve "Güvenlik").

Sahte Jira `httpx.MockTransport` ile; her istek yöntemiyle sayılır (yan etkisizlik: yalnız GET).
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tp_core.features.assistant.hiz import KOVA_JIRA_GLOBAL, VARSAYILAN_SINIRLAR
from tp_core.features.assistant.tools import jira as araci
from tp_core.features.assistant.tools.base import AracBaglami, AracHatasi, AracSarmalayici
from tp_core.gateway.masking import PiiMasker
from tp_core.integrations import jira as J
from tp_core.integrations.jira_adf import text_to_adf


class SahteJira:
    def __init__(self) -> None:
        self.istekler: list[httpx.Request] = []
        self.kod: int | None = None
        self.yorumlar = [
            {
                "id": "1",
                "author": {
                    "accountId": "acc-ayse",
                    "displayName": "Ayşe Yılmaz",
                    "emailAddress": "ayse.yilmaz@ornek.com",
                },
                "body": text_to_adf("Bana ayse.yilmaz@ornek.com adresinden ulaşın"),
                "created": "2026-11-01T10:00:00.000+0000",
                "jsdPublic": True,
            },
            {
                "id": "2",
                "author": {"accountId": "acc-x", "displayName": "X"},
                "body": text_to_adf("GIZLI rol notu"),
                "created": "2026-11-01T11:00:00.000+0000",
                "visibility": {"type": "role", "value": "Administrators"},
            },
        ]

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.istekler.append(req)
        if self.kod is not None:
            return httpx.Response(self.kod, json={"errorMessages": ["iç ayrıntı: sunucu-42"]})
        if req.url.path.endswith("/comment"):
            bas = int(req.url.params.get("startAt", 0))
            n = int(req.url.params.get("maxResults", 50))
            return httpx.Response(
                200,
                json={"total": len(self.yorumlar), "comments": self.yorumlar[bas : bas + n]},
            )
        anahtar = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            json={
                "key": anahtar,
                "fields": {
                    "summary": "Kampanya indirimi",
                    "description": text_to_adf("x" * 5000),
                    "labels": ["tp-ai"],
                    "status": {"name": "In Progress"},
                    "issuetype": {"name": "Story"},
                },
            },
        )

    def yontemler(self) -> set[str]:
        return {r.method for r in self.istekler}


@pytest.fixture
def sahte(monkeypatch: pytest.MonkeyPatch) -> SahteJira:
    s = SahteJira()
    ayar = J.JiraSettings(JIRA_BASE_URL="http://jira-sim:8090")

    def kur(
        timeout_s: float, toplam_sure_s: float, takma_adlar: dict[str, str], transport: Any
    ) -> Any:
        return J.get_jira_okuma(
            timeout_s,
            toplam_sure_s,
            settings=ayar,
            transport=transport,  # kova sayaçlı sarmalayıcı (içinde sahte transport)
            takma_adlar=takma_adlar,
        )

    monkeypatch.setattr(araci, "ag_transportu", lambda: httpx.MockTransport(s))
    monkeypatch.setattr(araci, "okuyucu_kur", kur)
    return s


@pytest.fixture
def bilinen(engine: Engine) -> list[str]:
    """TPD-3 gereksinim, TPD-9 bug, TPD-21 yayınlanmış case; TPD-22 yalnız `intent`."""
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO requirement (id, kaynak, jira_key, baslik, kaynak_hash) "
                "VALUES (:id, 'jira', 'TPD-3', 'Sepet', 'h')"
            ),
            {"id": uuid.uuid4()},
        )
        c.execute(
            text(
                "INSERT INTO bug_draft (id, icerik, icerik_hash, jira_key) "
                "VALUES (:id, '{}'::jsonb, 'h', 'TPD-9')"
            ),
            {"id": uuid.uuid4()},
        )
        for anahtar, durum in (("TPD-21", "created"), ("TPD-22", "intent")):
            c.execute(
                text(
                    "INSERT INTO external_ref (id, entity_turu, entity_id, sistem, "
                    "idempotency_key, external_key, durum) "
                    "VALUES (:id, 'test_case', :e, 'jira', :k, :a, :d)"
                ),
                {
                    "id": uuid.uuid4(),
                    "e": uuid.uuid4(),
                    "k": f"publish:{anahtar}",
                    "a": anahtar,
                    "d": durum,
                },
            )
    return ["TPD-3", "TPD-9", "TPD-21"]


def _baglam(engine: Engine, *, bitis: float | None = None, rol: str = "tester") -> AracBaglami:
    return AracBaglami(
        kullanici_id=uuid.uuid4(),
        rol=rol,
        oturum=PiiMasker(enabled=True).new_session(),
        db=lambda: Session(engine),
        bitis=bitis,
    )


def test_bilinen_anahtar_okunur_ve_yalniz_get(engine: Engine, sahte: SahteJira, bilinen) -> None:
    for anahtar in bilinen:
        sonuc = araci.jira_issue(_baglam(engine), anahtar=anahtar, yorum_limit=5)
        assert sonuc.kanit_turu == "jira" and sonuc.tur == "jira"
        assert f"Jira {anahtar}" in sonuc.metin
        assert "Kampanya indirimi" in sonuc.metin
        assert "Yorumlar: toplam 2" in sonuc.metin
        assert "1 kısıtlı yorum gösterilmedi" in sonuc.metin
        assert "GIZLI" not in sonuc.metin
        assert "http" not in sonuc.metin  # issue_url modele gitmez
    assert sahte.yontemler() == {"GET"}
    # anahtar başına: issue + 2 yorum isteği
    assert len(sahte.istekler) == 3 * len(bilinen)


def test_aciklama_3000_karakterde_kirpilir(engine: Engine, sahte: SahteJira, bilinen) -> None:
    metin = araci.jira_issue(_baglam(engine), anahtar="TPD-3").metin
    aciklama = metin.split("Açıklama:\n", 1)[1].split("\n", 1)[0]
    assert len(aciklama) <= 3000 + len(" …[kırpıldı]")


@pytest.mark.parametrize(
    "anahtar",
    [
        "TPD-22",  # yalnız intent: yayınlanmamış
        "TPD-404",
        "tpd-3",
        "TPD-3/../x",
        "TPD-3?expand=changelog",
        "TPD-٣",  # Arapça-Hint rakamı
        "TPD-３",  # tam genişlik rakam
        "ＴPD-3",
        "TPD-3\n",
        " TPD-3",
        "T-3",
        "",
        None,
        3,
    ],
)
def test_bilinmeyen_ya_da_atlatma_anahtarinda_istek_yok(
    engine: Engine, sahte: SahteJira, bilinen, anahtar: Any
) -> None:
    with pytest.raises(AracHatasi):
        araci.jira_issue(_baglam(engine), anahtar=anahtar)
    assert sahte.istekler == []


@pytest.mark.parametrize("rol", ["auditor", "viewer"])
def test_okuma_izni_olmayan_rol_jira_okuyamaz(
    engine: Engine, sahte: SahteJira, bilinen, rol: str
) -> None:
    # Gereksinim → requirement.read, bug → bug.read, case → case.read (yetki kataloğu).
    for anahtar in bilinen:
        with pytest.raises(AracHatasi, match="rolünüze açık değil"):
            araci.jira_issue(_baglam(engine, rol=rol), anahtar=anahtar)
    assert sahte.istekler == []


def test_tur_izni_katalogdan(engine: Engine, bilinen) -> None:
    b = _baglam(engine)
    assert araci.anahtar_turleri(b, "TPD-3") == {"requirement"}
    assert araci.anahtar_turleri(b, "TPD-9") == {"bug"}
    assert araci.anahtar_turleri(b, "TPD-21") == {"case"}
    assert araci.anahtar_turleri(b, "TPD-22") == frozenset()
    assert araci.rol_okuyabilir_mi("developer", frozenset({"bug"}))
    assert not araci.rol_okuyabilir_mi("viewer", frozenset({"requirement", "bug", "case"}))


def test_mesaj_basina_dorduncu_anahtar_reddedilir(
    engine: Engine, sahte: SahteJira, bilinen
) -> None:
    b = _baglam(engine)
    for anahtar in bilinen:
        araci.jira_issue(b, anahtar=anahtar)
    onceki = len(sahte.istekler)
    with pytest.raises(AracHatasi, match="en çok 3"):
        araci.jira_issue(b, anahtar="TPD-404")
    assert len(sahte.istekler) == onceki


def test_ayni_anahtar_mesajda_tek_istek(engine: Engine, sahte: SahteJira, bilinen) -> None:
    b = _baglam(engine)
    ilk = araci.jira_issue(b, anahtar="TPD-3").metin
    ikinci = araci.jira_issue(b, anahtar="TPD-3", yorum_limit=1).metin
    assert len(sahte.istekler) == 3
    assert "Kampanya indirimi" in ikinci and ilk


def test_onbellek_sonraki_cagrinin_yorum_limitini_karsilar(
    engine: Engine, sahte: SahteJira, bilinen
) -> None:
    """Önbellek anahtar başınadır ama limit çağrı başına: ilk çağrı 2 yorum isterken ikinci
    çağrının 10'u ilk okumanın 2 yorumuyla sınırlı kalmaz (yine tek okuma)."""
    sahte.yorumlar = [
        {
            "id": str(i),
            "author": {"accountId": f"acc-{i}", "displayName": f"Kişi {i}"},
            "body": text_to_adf(f"yorum-{i:02d}"),
            "created": "2026-11-01T10:00:00.000+0000",
        }
        for i in range(12)
    ]
    b = _baglam(engine)
    ilk = araci.jira_issue(b, anahtar="TPD-3", yorum_limit=2).metin
    istek = len(sahte.istekler)
    ikinci = araci.jira_issue(b, anahtar="TPD-3", yorum_limit=10).metin
    assert len(sahte.istekler) == istek  # ikinci çağrı ağa çıkmaz
    assert "son 2 gösteriliyor" in ilk and "yorum-11" in ilk and "yorum-09" not in ilk
    assert "son 10 gösteriliyor" in ikinci
    assert all(f"yorum-{i:02d}" in ikinci for i in range(2, 12))
    assert "yorum-01" not in ikinci


def test_yazar_e_postasi_ve_adi_modele_gitmez(engine: Engine, sahte: SahteJira, bilinen) -> None:
    b = _baglam(engine)
    sar = AracSarmalayici(b, yeni=araci.ARACLAR)
    cikti = sar("jira_issue", {"anahtar": "TPD-3"})
    assert cikti.startswith("[kanit:k1]")
    assert '<untrusted kind="jira"' in cikti
    for sizinti in ("ayse.yilmaz@ornek.com", "Ayşe", "acc-ayse", "Yılmaz"):
        assert sizinti not in cikti
    assert "Kişi-1" in cikti and "<<PII_EMAIL_1>>" in cikti


@pytest.mark.parametrize("kod", [401, 403, 500, 503])
def test_erisim_hatasi_ayrintisi_modele_gitmez(
    engine: Engine, sahte: SahteJira, bilinen, kod: int
) -> None:
    sahte.kod = kod
    sar = AracSarmalayici(_baglam(engine), yeni=araci.ARACLAR)
    with pytest.raises(AracHatasi) as exc:
        sar("jira_issue", {"anahtar": "TPD-3"})
    mesaj = str(exc.value)
    assert "sunucu-42" not in mesaj and str(kod) not in mesaj
    assert mesaj in (araci.MESAJ_ERISIM, araci.MESAJ_YANIT_YOK)


def test_retry_after_kalan_sureyi_asinca_yanit_vermiyor(
    engine: Engine, bilinen, monkeypatch: pytest.MonkeyPatch
) -> None:
    istekler: list[httpx.Request] = []

    def isleyici(req: httpx.Request) -> httpx.Response:
        istekler.append(req)
        return httpx.Response(429, headers={"Retry-After": "60"}, json={})

    uykular: list[float] = []

    def kur(
        timeout_s: float, toplam_sure_s: float, takma_adlar: dict[str, str], transport: Any
    ) -> Any:
        assert timeout_s <= 8 and toplam_sure_s <= 12
        return J.get_jira_okuma(
            timeout_s,
            toplam_sure_s,
            settings=J.JiraSettings(JIRA_BASE_URL="http://jira-sim:8090"),
            transport=transport,
            sleep=uykular.append,
        )

    monkeypatch.setattr(araci, "ag_transportu", lambda: httpx.MockTransport(isleyici))
    monkeypatch.setattr(araci, "okuyucu_kur", kur)
    with pytest.raises(AracHatasi, match="yanıt vermiyor"):
        araci.jira_issue(_baglam(engine, bitis=time.monotonic() + 30), anahtar="TPD-3")
    assert uykular == [] and len(istekler) == 1


def test_sure_bittiyse_istek_yok(engine: Engine, sahte: SahteJira, bilinen) -> None:
    with pytest.raises(AracHatasi, match="yanıt vermiyor"):
        araci.jira_issue(_baglam(engine, bitis=time.monotonic() + 0.2), anahtar="TPD-3")
    assert sahte.istekler == []


def _jira_penceresi() -> int:
    return VARSAYILAN_SINIRLAR[KOVA_JIRA_GLOBAL][1]


def _jira_kova_sayisi(engine: Engine) -> int:
    with engine.connect() as c:
        return int(
            c.execute(
                text(
                    "SELECT COALESCE(SUM(sayi), 0) FROM asistan_hiz WHERE kova = 'jira_global' "
                    "AND pencere_baslangic = "
                    "to_timestamp(floor(extract(epoch FROM now()) / :p) * :p)"
                ),
                {"p": _jira_penceresi()},
            ).scalar_one()
        )


def _jira_kova_ayarla(engine: Engine, sayi: int) -> None:
    with engine.begin() as c:
        c.execute(text("DELETE FROM asistan_hiz WHERE kova = 'jira_global'"))
        c.execute(
            text(
                "INSERT INTO asistan_hiz (id, kullanici_id, kova, pencere_baslangic, sayi) "
                "VALUES (:id, NULL, 'jira_global', "
                "to_timestamp(floor(extract(epoch FROM now()) / :p) * :p), :n)"
            ),
            {"id": uuid.uuid4(), "n": sayi, "p": _jira_penceresi()},
        )


def test_jira_kovasi_her_http_istegini_sayar(
    engine: Engine, sahte: SahteJira, bilinen, sabit_hiz_penceresi: int
) -> None:
    """Sınır dakikada 30 HTTP isteğidir: bir okuma (konu + yorum sayfaları) kaç istek yaptıysa
    kovadan o kadar düşer; kova dolunca istek ağa çıkmaz ("Jira meşgul")."""
    _jira_kova_ayarla(engine, 0)
    araci.jira_issue(_baglam(engine), anahtar="TPD-3")
    istek = len(sahte.istekler)
    assert istek >= 2 and _jira_kova_sayisi(engine) == istek

    _jira_kova_ayarla(engine, 30)
    with pytest.raises(AracHatasi, match="Jira meşgul"):
        araci.jira_issue(_baglam(engine), anahtar="TPD-9")  # 31. istek
    assert len(sahte.istekler) == istek

    # Okumanın ortasında dolan kova: ilk istek (30.) gider, ikincisi (31.) ağa çıkmaz.
    _jira_kova_ayarla(engine, 29)
    with pytest.raises(AracHatasi, match="Jira meşgul"):
        araci.jira_issue(_baglam(engine), anahtar="TPD-21")
    assert len(sahte.istekler) == istek + 1


def test_bilinmeyen_arguman_reddedilir(engine: Engine, sahte: SahteJira, bilinen) -> None:
    with pytest.raises(AracHatasi):
        araci.jira_issue(_baglam(engine), anahtar="TPD-3", jql="project = TPD")
    assert sahte.istekler == []


def test_arac_semasi_anahtar_kalibi() -> None:
    (spec,) = araci.TOOL_SPECS
    assert spec.name == "jira_issue"
    assert spec.input_schema["required"] == ["anahtar"]
    assert spec.input_schema["additionalProperties"] is False


def test_kirpma_sinirindaki_yarim_token_maskelenir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kırpma işaretinden ÖNCE temizlik: sınırda yarım kalan token (biçim deseni) ve bilinen sır
    değerinin öneki düz geçmez (işaret eklendikten sonra `\\Z` koruması çalışmazdı)."""
    from tp_core.features.assistant.tools.base import sir_temizle

    token = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    metin = "x" * (araci.MAX_YORUM - 14) + " " + token
    cikti = sir_temizle(araci._kirp(metin, araci.MAX_YORUM))
    assert cikti.endswith("…[kırpıldı]") and "***" in cikti
    assert token[:6] not in cikti
    deger = "bilinen-" + uuid.uuid4().hex
    monkeypatch.setenv("JIRA_READ_TOKEN", deger)
    metin = "y" * (araci.MAX_YORUM - 12) + " " + deger
    cikti = sir_temizle(araci._kirp(metin, araci.MAX_YORUM), [deger])
    assert deger[:11] not in cikti and "***" in cikti
