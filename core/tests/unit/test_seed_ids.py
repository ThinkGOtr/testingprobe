import uuid

from tp_core.seed import KULLANICILAR, NAMESPACE_TP, tp_uuid


def test_uuid_deterministik() -> None:
    assert tp_uuid("user", "analist") == tp_uuid("user", "analist")
    assert tp_uuid("user", "analist") == uuid.uuid5(NAMESPACE_TP, "user:analist")
    assert tp_uuid("user", "analist").version == 5


def test_namespace_sabit() -> None:
    # Değişirse tüm seed kimlikleri değişir; bilinçli olmadıkça dokunmayın.
    assert str(NAMESPACE_TP) == "6f1d2c3a-8b4e-5f60-9a7b-1c2d3e4f5a6b"


def test_seed_kullanicilari() -> None:
    assert dict(KULLANICILAR) == {
        "analist": "analyst",
        "muhendis": "engineer",
        "sunucu": "presenter",
        "po": "po",
        "testci": "tester",
    }
    assert len({tp_uuid("user", ad) for ad, _ in KULLANICILAR}) == 5
