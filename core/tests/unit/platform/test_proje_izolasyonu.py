"""Çok proje — uç keşifli izolasyon testi (TP-COK-PROJE-PLANI §2.4).

İki proje (A varsayılan, B ikinci). Router kayıt defterindeki (`api/registry.py` → `create_app`)
her GET ucu B oturumuyla çağrılır:

1. **Faz 1:** yalnız B'nin tohum verisi var; A'nın nesne kimlikleri önceden seçilir ama henüz
   yazılmamıştır. Her uç (yol parametreleri A'nın kimlikleriyle doldurularak) çağrılır, durum kodu
   saklanır.
2. **Faz 2:** A'nın tohum verisi aynı kimliklerle yazılır; aynı çağrılar B oturumuyla tekrarlanır.

Beklenen: (a) hiçbir B yanıtı A'nın işaretlerini (kimlik, Jira anahtarı, başlık, dosya yolu, PR
numarası) içermez; (b) A'nın kimliğiyle yapılan ayrıntı çağrısı B'de faz 1'deki (nesne yokken)
durum kodunu döner — nesne "B'de yok" sayılır (404 ya da boş), sızıntı yüklemesi `ProjeIhlali`
(500) vermez. `sql_denetimi` fikstürü de her istekte `project_id`'siz kapsamlı SQL'i düşürür.

Kimlik doğrulama: `current_user` bağımlılığı B projesinde, istenen role sahip bir `Principal`
döndürecek biçimde değiştirilir (oturum/rol çözümü `test_proje_secimi.py`'de sınanır). Her uç için
izin reddi (403) almayan ilk rol kullanılır.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from tp_core.api import main
from tp_core.api.registry import route_table
from tp_core.auth.deps import current_user
from tp_core.models import (
    BugDraft,
    Failure,
    PullRequest,
    Requirement,
    Run,
    Script,
    TestCase,
    TestResult,
)
from tp_core.proje import proje_icinde
from tp_core.workflow.service import Principal

# İzin reddi almamak için sırayla denenen roller (en geniş okuma izinlileri önce).
ROLLER = ("admin", "auditor", "po", "engineer", "analyst", "tester", "developer", "viewer")
ROL_BASLIGI = "X-Test-Rol"
# Akış (SSE) uçları istemciyi bekletir; proje kapsamı `test_proje_secimi`/`events` testlerinde.
ATLANAN = re.compile(r"/events|/stream|/sse")


class Tohum:
    """Bir projenin tohum verisinin kimlikleri ve yanıtlarda aranacak işaretleri."""

    def __init__(self, etiket: str, pr_no: int) -> None:
        self.etiket = etiket
        self.req_id = uuid.uuid4()
        self.case_id = uuid.uuid4()
        self.run_id = uuid.uuid4()
        self.result_id = uuid.uuid4()
        self.failure_id = uuid.uuid4()
        self.script_id = uuid.uuid4()
        self.bug_id = uuid.uuid4()
        self.pr_no = pr_no
        ek = uuid.uuid4().hex[:8].upper()
        self.jira_key = f"IZO{etiket}-{pr_no}"
        self.baslik = f"Izolasyon-{etiket}-{ek}"
        self.dosya = f"e2e/tests/izolasyon-{etiket.lower()}-{ek.lower()}.spec.ts"

    def kimlikler(self) -> list[str]:
        return [
            str(k)
            for k in (
                self.req_id,
                self.case_id,
                self.run_id,
                self.result_id,
                self.failure_id,
                self.script_id,
                self.bug_id,
            )
        ]

    def isaretler(self) -> list[str]:
        return [*self.kimlikler(), self.jira_key, self.baslik, self.dosya]

    def yol_degerleri(self) -> list[str]:
        return [*self.kimlikler(), str(self.pr_no), self.jira_key]

    def yaz(self, engine: Engine, pid: str) -> None:
        h = hashlib.sha256(self.baslik.encode()).hexdigest()
        with Session(engine) as s, proje_icinde(pid, kaynak="test"):
            s.add(
                Requirement(
                    id=self.req_id,
                    kaynak="jira",
                    jira_key=self.jira_key,
                    baslik=self.baslik,
                    kaynak_hash=h,
                )
            )
            s.flush()
            s.add(
                TestCase(
                    id=self.case_id,
                    requirement_id=self.req_id,
                    sira_no=1,
                    icerik={"baslik": self.baslik, "adimlar": []},
                    icerik_hash=h,
                )
            )
            s.add(
                Script(
                    id=self.script_id, dosya_yolu=self.dosya, pr_no=self.pr_no, head_sha="a" * 40
                )
            )
            s.add(
                PullRequest(
                    number=self.pr_no,
                    branch=f"tp/case-{self.etiket.lower()}",
                    baslik=self.baslik,
                    head_sha="a" * 40,
                    acan="test",
                )
            )
            s.flush()
            s.add(
                Run(
                    id=self.run_id,
                    script_id=self.script_id,
                    kaynak="local",
                    tetik="manual",
                    sonuc="failed",
                )
            )
            s.flush()
            s.add(
                TestResult(
                    id=self.result_id,
                    run_id=self.run_id,
                    test_adi=self.baslik,
                    sonuc="failed",
                    tetik="manual",
                )
            )
            s.flush()
            s.add(
                Failure(
                    id=self.failure_id,
                    run_id=self.run_id,
                    test_result_id=self.result_id,
                    test_adi=self.baslik,
                    hata_imzasi=f"imza-{self.baslik}",
                    sinif="unknown",
                )
            )
            s.flush()
            s.add(
                BugDraft(
                    id=self.bug_id,
                    failure_id=self.failure_id,
                    icerik={"baslik": self.baslik},
                    icerik_hash=h,
                )
            )
            s.commit()


def _get_rotalari(app: FastAPI) -> list[str]:
    return sorted(
        {yol for yontem, yol, _ in route_table(app) if yontem == "GET" and not ATLANAN.search(yol)}
    )


def _doldur(yol: str, deger: str) -> str:
    return re.sub(r"\{[^}]+\}", deger, yol)


@pytest.fixture
def b_istemcisi(
    db: Any, engine: Engine, make_user: Any, iki_proje: tuple[str, str]
) -> Iterator[TestClient]:
    _, b = iki_proje
    kullanicilar = {rol: make_user(rol) for rol in ROLLER}

    def sahte(request: Request) -> Principal:
        rol = request.headers.get(ROL_BASLIGI, "viewer")
        u = kullanicilar[rol]
        p = Principal(u.id, u.kullanici_adi, rol, project_id=b, roller=frozenset({rol}))
        request.state.principal = p
        return p

    app = main.create_app()
    app.dependency_overrides[current_user] = sahte
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _cagir(c: TestClient, yol: str) -> tuple[int, str, str]:
    """İzin reddi almayan ilk rolle çağrı: (durum, gövde, rol)."""
    son: tuple[int, str, str] = (0, "", "")
    for rol in ROLLER:
        r = c.get(yol, headers={ROL_BASLIGI: rol})
        son = (r.status_code, r.text, rol)
        if r.status_code != 403:
            return son
    return son


def test_b_oturumu_a_verisini_gormez(
    b_istemcisi: TestClient, engine: Engine, iki_proje: tuple[str, str]
) -> None:
    a_pid, b_pid = iki_proje
    a = Tohum("A", 9101)
    b = Tohum("B", 9202)
    b.yaz(engine, b_pid)

    yollar = _get_rotalari(b_istemcisi.app)  # type: ignore[arg-type]
    assert len(yollar) > 50, "uç keşfi beklenenden az rota buldu"
    cagrilar: list[str] = []
    for yol in yollar:
        if "{" in yol:
            cagrilar.extend(_doldur(yol, d) for d in a.yol_degerleri())
        else:
            cagrilar.append(yol)

    faz1 = {y: _cagir(b_istemcisi, y) for y in cagrilar}

    a.yaz(engine, a_pid)
    faz2 = {y: _cagir(b_istemcisi, y) for y in cagrilar}

    sizinti: list[str] = []
    for y in cagrilar:
        d1, _, _ = faz1[y]
        d2, govde, rol = faz2[y]
        bulunan = [i for i in a.isaretler() if i in govde]
        if bulunan:
            sizinti.append(f"{y} [{rol}] {d2}: A işaretleri {bulunan[:3]}")
        elif d1 != d2:
            sizinti.append(f"{y} [{rol}]: A verisi yokken {d1}, varken {d2} — {govde[:160]}")
        elif d2 >= 500:
            # Bağlam/ProjeIhlali ya da proje kapsamlı sorgu hatası: izolasyon tablosu güvenilmez.
            sizinti.append(f"{y} [{rol}]: {d2} — {govde[:160]}")
    assert not sizinti, "B oturumunda A projesinin verisi:\n" + "\n".join(sizinti)

    # Kendi projesinde veri görünür (test boşa geçmesin): B'nin gereksinimi B listesinde.
    durum, govde, _ = _cagir(b_istemcisi, f"/requirements/{b.req_id}")
    assert durum == 200 and b.baslik in govde, (durum, govde[:300])
    assert json.loads(govde)
