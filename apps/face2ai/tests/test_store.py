from __future__ import annotations

import pytest

from face2ai_app.adapters.json_identity_store import JsonIdentityStore
from face2ai_app.domain.errors import IdentityStoreCorrupted
from face2ai_app.domain.models import IdentityRecord


def test_store_add_delete_and_clear(tmp_path):
    store = JsonIdentityStore(tmp_path / "identities.json")
    a = store.add(IdentityRecord.new("A", [0.1] * 128))
    b = store.add(IdentityRecord.new("B", [0.2] * 128))
    assert [x.display_name for x in store.list()] == ["A", "B"]
    assert store.delete(a.id) is True
    assert store.delete("missing") is False
    assert [x.id for x in store.list()] == [b.id]
    assert store.clear() == 1
    assert store.list() == []


def test_store_rejects_corrupted_json_without_overwriting_it(tmp_path):
    path = tmp_path / "identities.json"
    original = "{broken"
    path.write_text(original, encoding="utf-8")
    store = JsonIdentityStore(path)

    with pytest.raises(IdentityStoreCorrupted, match="invalid JSON"):
        store.list()

    assert path.read_text(encoding="utf-8") == original


def test_store_rejects_wrong_json_root_shape(tmp_path):
    path = tmp_path / "identities.json"
    path.write_text('{"identity": "not-a-list"}', encoding="utf-8")
    store = JsonIdentityStore(path)

    with pytest.raises(IdentityStoreCorrupted, match="root must be a JSON array"):
        store.list()
