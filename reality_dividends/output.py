"""Normalized CSV and Markdown output."""

from __future__ import annotations

import csv
import io
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .decode import CSV_FIELDS, deduplicate_records


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def write_csv(path: Path, records: Iterable[dict[str, Any]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for record in deduplicate_records(records):
        writer.writerow(record)
    atomic_text(path, buffer.getvalue())


def _markdown_cell(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def write_markdown(path: Path, records: Iterable[dict[str, Any]]) -> None:
    labels = {
        "event_type": "Event Type",
        "corporate_action_id": "Corporate Action ID",
        "block_number": "Block Number",
        "transaction_hash": "Transaction Hash",
        "log_index": "Log Index",
        "rtoken_address": "rToken Address",
        "status": "Status",
        "payload_rtoken": "Payload rToken",
        "payout_token": "Payout Token",
        "dividend_per_share_raw": "Dividend/Share Raw",
        "dividend_per_share_scaled": "Dividend/Share (1e18)",
        "source_provider": "Source Provider",
    }
    rows = deduplicate_records(records)
    lines = [
        "# Reality Finance Dividend Events",
        "",
        "| " + " | ".join(labels[field] for field in CSV_FIELDS) + " |",
        "| " + " | ".join("---" for _ in CSV_FIELDS) + " |",
    ]
    for record in rows:
        lines.append(
            "| "
            + " | ".join(_markdown_cell(record.get(field, "")) for field in CSV_FIELDS)
            + " |"
        )
    lines.append("")
    atomic_text(path, "\n".join(lines))
