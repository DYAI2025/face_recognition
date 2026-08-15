from face2ai_app.adapters.json_identity_store import JsonIdentityStore
from face2ai_app.domain.models import IdentityRecord


def test_store_add_delete_and_clear(tmp_path):
    store = JsonIdentityStore(tmp_path / "identities.json")
    first = store.add(IdentityRecord.new("A", [0.1] * 128))
    second = store.add(IdentityRecord.new("B", [0.2] * 128))
    assert [item.display_name for item in store.list()] == ["A", "B"]
    assert store.delete(first.id) is True
    assert store.delete("missing") is False
    assert [item.id for item in store.list()] == [second.id]
    assert store.clear() == 1
    assert store.list() == []
