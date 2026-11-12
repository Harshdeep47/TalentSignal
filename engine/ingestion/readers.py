"""Streaming readers for candidate files.

Every reader yields ``RawRow(row_number, record, error)`` one record at a
time, so a 465 MB JSONL file never has to be held in memory. Supported:

  .jsonl / .ndjson / .txt   one JSON object per line (streamed)
  .json                     a JSON array, or {"candidates": [...]} (loaded whole;
                            capped by ``max_json_bytes`` because a JSON array
                            cannot be streamed without a SAX parser)
  .csv / .xlsx              one candidate per row; nested fields either as
                            dotted columns (``profile.headline``) or as JSON
                            text in a column (``career_history``)
  .parquet                  nested columns or JSON-text columns, read in batches
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import orjson

SUPPORTED_EXTENSIONS = (".jsonl", ".ndjson", ".txt", ".json", ".csv", ".xlsx", ".parquet")
DEFAULT_MAX_JSON_BYTES = 512 * 1024 * 1024


@dataclass
class RawRow:
    row: int
    record: dict[str, Any] | None
    error: str | None = None


class UnsupportedFormat(ValueError):
    pass


def detect_format(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext in (".jsonl", ".ndjson", ".txt"):
        return "jsonl"
    if ext in (".json", ".csv", ".xlsx", ".parquet"):
        return ext[1:]
    raise UnsupportedFormat(
        f"Unsupported candidate file type '{ext or '(none)'}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
    )


def _iter_jsonl(path: Path) -> Iterator[RawRow]:
    with open(path, "rb") as f:
        for i, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                obj = orjson.loads(line)
            except orjson.JSONDecodeError as exc:
                yield RawRow(i, None, f"Invalid JSON: {exc}")
                continue
            if not isinstance(obj, dict):
                yield RawRow(i, None, "Each line must be a JSON object.")
                continue
            yield RawRow(i, obj)


def _iter_json(path: Path, max_bytes: int) -> Iterator[RawRow]:
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(
            f"JSON array files are loaded whole and are limited to {max_bytes // (1024 * 1024)} MB; "
            "convert large files to JSONL (one object per line) instead."
        )
    try:
        data = orjson.loads(path.read_bytes())
    except orjson.JSONDecodeError as exc:
        raise ValueError(f"The file is not valid JSON: {exc}") from exc
    if isinstance(data, dict):
        for key in ("candidates", "data", "records"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of candidate objects.")
    for i, obj in enumerate(data, start=1):
        if isinstance(obj, dict):
            yield RawRow(i, obj)
        else:
            yield RawRow(i, None, "Array element is not a JSON object.")


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        s = value.strip()
        if s[:1] in ("[", "{"):
            try:
                return orjson.loads(s)
            except orjson.JSONDecodeError:
                return value
        if s == "":
            return None
    return value


def unflatten(row: dict[str, Any]) -> dict[str, Any]:
    """Turn ``{"profile.headline": "x", "skills": "[...]"}`` into nested dicts."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        if key is None:
            continue
        value = _maybe_json(value)
        if value is None:
            continue
        parts = str(key).strip().split(".")
        cur = out
        for p in parts[:-1]:
            nxt = cur.get(p)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[p] = nxt
            cur = nxt
        cur[parts[-1]] = value
    return out


def _iter_csv(path: Path) -> Iterator[RawRow]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):
            yield RawRow(i, unflatten(row))


def _iter_xlsx(path: Path) -> Iterator[RawRow]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None)
        if not header:
            return
        names = [str(h).strip() if h is not None else None for h in header]
        for i, values in enumerate(rows, start=2):
            if values is None or all(v is None for v in values):
                continue
            yield RawRow(i, unflatten(dict(zip(names, values))))
    finally:
        wb.close()


def _iter_parquet(path: Path) -> Iterator[RawRow]:
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    i = 0
    for batch in pf.iter_batches(batch_size=2048):
        for row in batch.to_pylist():
            i += 1
            yield RawRow(i, unflatten(row))


def iter_records(path: str | Path, max_json_bytes: int = DEFAULT_MAX_JSON_BYTES) -> Iterator[RawRow]:
    p = Path(path)
    fmt = detect_format(p)
    if fmt == "jsonl":
        yield from _iter_jsonl(p)
    elif fmt == "json":
        yield from _iter_json(p, max_json_bytes)
    elif fmt == "csv":
        yield from _iter_csv(p)
    elif fmt == "xlsx":
        yield from _iter_xlsx(p)
    elif fmt == "parquet":
        yield from _iter_parquet(p)


def count_hint(path: str | Path) -> int | None:
    """Cheap record-count estimate for progress bars (line count for JSONL)."""
    p = Path(path)
    if detect_format(p) != "jsonl":
        return None
    n = 0
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            n += chunk.count(b"\n")
    return n or None


def records_to_csv_bytes(records: list[dict[str, Any]]) -> bytes:
    """Inverse of :func:`unflatten` for exports/tests: nested values as JSON text."""
    keys: list[str] = []
    flat_rows = []
    for rec in records:
        flat: dict[str, Any] = {}
        for k, v in rec.items():
            if isinstance(v, dict) and k in ("profile", "redrob_signals"):
                for kk, vv in v.items():
                    flat[f"{k}.{kk}"] = orjson.dumps(vv).decode() if isinstance(vv, (dict, list)) else vv
            elif isinstance(v, (dict, list)):
                flat[k] = orjson.dumps(v).decode()
            else:
                flat[k] = v
        for k in flat:
            if k not in keys:
                keys.append(k)
        flat_rows.append(flat)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys)
    w.writeheader()
    w.writerows(flat_rows)
    return buf.getvalue().encode("utf-8")
