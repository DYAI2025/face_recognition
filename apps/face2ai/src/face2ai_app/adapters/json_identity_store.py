from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from pydantic import ValidationError

from face2ai_app.domain.errors import IdentityStoreCorrupted
from face2ai_app.domain.models import IdentityRecord


class JsonIdentityStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()

    def _read(self) -> list[IdentityRecord]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise IdentityStoreCorrupted(
                f"identity store contains invalid JSON: {self._path}"
            ) from exc
        if not isinstance(raw, list):
            raise IdentityStoreCorrupted(
                f"identity store root must be a JSON array: {self._path}"
            )
        try:
            return [IdentityRecord.model_validate(item) for item in raw]
        except ValidationError as exc:
            raise IdentityStoreCorrupted(
                f"identity store contains invalid identity records: {self._path}"
            ) from exc

    def _write(self, records: list[IdentityRecord]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [record.model_dump(mode="json") for record in records],
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        fd, temp_name = tempfile.mkstemp(
            prefix="identities-", suffix=".json", dir=self._path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self._path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def list(self) -> list[IdentityRecord]:
        with self._lock:
            return self._read()

    def add(self, identity: IdentityRecord) -> IdentityRecord:
        with self._lock:
            records = self._read()
            records.append(identity)
            self._write(records)
            return identity

    def delete(self, identity_id: str) -> bool:
        with self._lock:
            records = self._read()
            remaining = [record for record in records if record.id != identity_id]
            if len(remaining) == len(records):
                return False
            self._write(remaining)
            return True

    def clear(self) -> int:
        with self._lock:
            count = len(self._read())
            self._write([])
            return count
