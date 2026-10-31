"""DB bağlantısında SCRAM zorunlu: `postgres` adı yanlış sunucuya çözülse de parola sızmaz."""

from __future__ import annotations

import socket
import struct
import threading

import psycopg
import pytest
from sqlalchemy.engine import make_url

from tp_core.config import Settings, libpq_auth_zorla
from tp_core.events.listener import libpq_dsn

URL = "postgresql+psycopg://tp_app:gizli-parola@postgres:5432/tp"


def test_varsayilan_url_scram_zorunlu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_DATABASE_URL", URL)
    monkeypatch.delenv("TP_DB_REQUIRE_AUTH", raising=False)
    ayar = Settings()  # type: ignore[call-arg]
    assert make_url(ayar.database_url).query["require_auth"] == "scram-sha-256"
    assert make_url(ayar.database_url).password == "gizli-parola"
    # LISTEN bağlantısı (olay yayını) da aynı parametreyi taşır.
    assert "require_auth=scram-sha-256" in libpq_dsn(ayar.database_url)


def test_url_kendi_degerini_tasirsa_dokunulmaz_bos_ayar_kapatir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert libpq_auth_zorla(URL + "?require_auth=md5", "scram-sha-256").endswith("=md5")
    assert libpq_auth_zorla(URL, "") == URL
    monkeypatch.setenv("TP_DATABASE_URL", URL)
    monkeypatch.setenv("TP_DB_REQUIRE_AUTH", "")
    assert Settings().database_url == URL  # type: ignore[call-arg]


def _sahte_sunucu(gelen: list[bytes]) -> tuple[socket.socket, threading.Thread]:
    """Düz metin parola isteyen sahte bir 'postgres' (LAN yönlendiricisi / kurumsal sunucu)."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(5)

    def calis() -> None:
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(3)
            try:
                uzunluk = struct.unpack("!I", conn.recv(4))[0]
                kalan = uzunluk - 4
                while kalan > 0:
                    parca = conn.recv(kalan)
                    if not parca:
                        return
                    kalan -= len(parca)
                # AuthenticationCleartextPassword
                conn.sendall(b"R" + struct.pack("!II", 8, 3))
                while True:
                    veri = conn.recv(4096)
                    if not veri:
                        return
                    gelen.append(veri)
            except OSError:
                return

    t = threading.Thread(target=calis, daemon=True)
    t.start()
    return srv, t


@pytest.mark.parametrize("zorla", [True, False])
def test_sahte_sunucu_duz_metin_parola_alamaz(zorla: bool) -> None:
    gelen: list[bytes] = []
    srv, t = _sahte_sunucu(gelen)
    port = srv.getsockname()[1]
    url = f"postgresql+psycopg://tp_app:gizli-parola@127.0.0.1:{port}/tp?sslmode=disable"
    url = libpq_auth_zorla(url, "scram-sha-256" if zorla else "")
    try:
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(libpq_dsn(url), connect_timeout=3)
    finally:
        t.join(timeout=5)
        srv.close()
    sizan = b"gizli-parola" in b"".join(gelen)
    # Zorlama yoksa libpq parolayı düz metin gönderir (bulgu); SCRAM zorunluyken hiç göndermez.
    assert sizan is (not zorla)
