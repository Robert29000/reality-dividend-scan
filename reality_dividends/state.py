"""Automatic scan checkpoints and interval arithmetic."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .constants import CHAIN_ID, ORACLE_ADDRESS
from .decode import deduplicate_records

STATE_VERSION = 1


class StateError(ValueError):
    pass


def merge_ranges(ranges: Iterable[Iterable[int]]) -> list[list[int]]:
    ordered = sorted((int(item[0]), int(item[1])) for item in ranges)
    merged: list[list[int]] = []
    for start, end in ordered:
        if start > end:
            raise StateError(f"invalid completed range {start}..{end}")
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def subtract_ranges(
    start: int, end: int, completed: Iterable[Iterable[int]]
) -> list[tuple[int, int]]:
    if start > end:
        return []
    remaining: list[tuple[int, int]] = []
    cursor = start
    for done_start, done_end in merge_ranges(completed):
        if done_end < cursor:
            continue
        if done_start > end:
            break
        if done_start > cursor:
            remaining.append((cursor, min(end, done_start - 1)))
        cursor = max(cursor, done_end + 1)
        if cursor > end:
            break
    if cursor <= end:
        remaining.append((cursor, end))
    return remaining


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


class ScanState:
    def __init__(
        self,
        path: Path,
        provider: str,
        requested_from: int,
        requested_to: int,
    ) -> None:
        self.path = path
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise StateError(f"cannot read state file {path}: {exc}") from exc
            self._validate(provider, requested_from)
            self.data["requested_to"] = max(
                int(self.data.get("requested_to", requested_to)), requested_to
            )
        else:
            self.data = {
                "schema_version": STATE_VERSION,
                "provider": provider,
                "chain_id": CHAIN_ID,
                "oracle_address": ORACLE_ADDRESS,
                "requested_from": requested_from,
                "requested_to": requested_to,
                "completed_ranges": [],
                "records": [],
            }

    def _validate(self, provider: str, requested_from: int) -> None:
        expected = {
            "schema_version": STATE_VERSION,
            "provider": provider,
            "chain_id": CHAIN_ID,
            "oracle_address": ORACLE_ADDRESS,
            "requested_from": requested_from,
        }
        for key, value in expected.items():
            if self.data.get(key) != value:
                raise StateError(
                    f"state file {self.path} has {key}={self.data.get(key)!r}; "
                    f"expected {value!r}"
                )

    @property
    def records(self) -> list[dict[str, Any]]:
        return list(self.data.get("records", []))

    @property
    def completed_ranges(self) -> list[list[int]]:
        return merge_ranges(self.data.get("completed_ranges", []))

    def add_records(self, records: Iterable[dict[str, Any]]) -> None:
        self.data["records"] = deduplicate_records([*self.records, *records])

    def complete(self, start: int, end: int) -> None:
        self.data["completed_ranges"] = merge_ranges(
            [*self.completed_ranges, [start, end]]
        )

    def save(self) -> None:
        atomic_json(self.path, self.data)
