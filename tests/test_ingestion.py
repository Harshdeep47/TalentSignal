import json

import orjson
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from openpyxl import Workbook

from engine.ingestion.fingerprint import file_fingerprint
from engine.ingestion.readers import UnsupportedFormat, iter_records, records_to_csv_bytes
from engine.ingestion.validation import Normalizer
from factories import candidate, write_jsonl


def test_jsonl_streaming_reports_bad_lines(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_bytes(orjson.dumps(candidate("CAND_0000001")) + b"\n{not json}\n[1,2]\n\n")
    rows = list(iter_records(p))
    assert rows[0].record["candidate_id"] == "CAND_0000001"
    assert rows[1].record is None and "Invalid JSON" in rows[1].error
    assert rows[2].record is None and "object" in rows[2].error
    assert len(rows) == 3


def test_json_array_and_wrapped_object(tmp_path):
    a = tmp_path / "a.json"
    a.write_text(json.dumps([candidate("CAND_0000001"), candidate("CAND_0000002")]))
    b = tmp_path / "b.json"
    b.write_text(json.dumps({"candidates": [candidate("CAND_0000003")]}))
    assert [r.record["candidate_id"] for r in iter_records(a)] == ["CAND_0000001", "CAND_0000002"]
    assert [r.record["candidate_id"] for r in iter_records(b)] == ["CAND_0000003"]


def test_csv_round_trip_with_nested_json_columns(tmp_path):
    recs = [candidate("CAND_0000001"), candidate("CAND_0000002", title="Data Engineer")]
    p = tmp_path / "c.csv"
    p.write_bytes(records_to_csv_bytes(recs))
    out = [r.record for r in iter_records(p)]
    norm = Normalizer()
    a, _ = norm.normalize(out[1])
    assert a["profile"]["current_title"] == "Data Engineer"
    assert a["skills"][0]["name"] == "Python"
    assert a["redrob_signals"]["recruiter_response_rate"] == pytest.approx(0.7)


def test_xlsx_and_parquet(tmp_path):
    rec = candidate("CAND_0000009")
    wb = Workbook()
    ws = wb.active
    ws.append(["candidate_id", "profile.current_title", "profile.years_of_experience", "skills"])
    ws.append([rec["candidate_id"], "AI Engineer", 6, json.dumps(rec["skills"])])
    wb.save(tmp_path / "c.xlsx")
    row = next(iter_records(tmp_path / "c.xlsx")).record
    assert row["profile"]["current_title"] == "AI Engineer" and isinstance(row["skills"], list)

    table = pa.table({"candidate_id": [rec["candidate_id"]], "profile": [json.dumps(rec["profile"])]})
    pq.write_table(table, tmp_path / "c.parquet")
    row = next(iter_records(tmp_path / "c.parquet")).record
    assert row["profile"]["current_title"] == rec["profile"]["current_title"]


def test_unsupported_extension(tmp_path):
    with pytest.raises(UnsupportedFormat):
        list(iter_records(tmp_path / "x.pdf"))


def test_normalizer_missing_and_sentinels_become_none():
    rec = candidate("CAND_0000001", signals={"github_activity_score": -1, "offer_acceptance_rate": -1})
    del rec["redrob_signals"]["notice_period_days"]
    out, issues = Normalizer().normalize(rec)
    sig = out["redrob_signals"]
    assert sig["github_activity_score"] is None
    assert sig["offer_acceptance_rate"] is None
    assert sig["notice_period_days"] is None
    assert not [i for i in issues if i.level == "error"]


def test_normalizer_clips_and_coerces():
    rec = candidate("CAND_0000001", signals={"recruiter_response_rate": "1.7", "open_to_work_flag": "yes"})
    out, issues = Normalizer().normalize(rec)
    assert out["redrob_signals"]["recruiter_response_rate"] == 1.0
    assert out["redrob_signals"]["open_to_work_flag"] is True
    assert any("clipped" in i.message for i in issues)


def test_normalizer_rejects_unusable_and_duplicates():
    n = Normalizer()
    assert n.normalize({"profile": {}})[0] is None
    assert n.normalize({"candidate_id": "bad id!", "profile": {}})[0] is None
    assert n.normalize(candidate("CAND_0000001"))[0] is not None
    dup, issues = n.normalize(candidate("CAND_0000001"))
    assert dup is None and "Duplicate" in issues[0].message


def test_normalizer_strips_control_characters_and_orders_roles():
    rec = candidate("CAND_0000001")
    rec["profile"]["summary"] = "Hello\x00\x07 world"
    rec["career_history"].append({**rec["career_history"][0], "is_current": False, "start_date": "2015-01-01",
                                  "end_date": "2019-01-01", "title": "Old Role"})
    rec["career_history"].reverse()
    out, _ = Normalizer().normalize(rec)
    assert "\x00" not in out["profile"]["summary"]
    assert out["career_history"][0]["is_current"] is True


def test_fingerprint_detects_middle_edit(tmp_path):
    recs = [candidate(f"CAND_{i:07d}") for i in range(3000)]
    p = write_jsonl(recs, tmp_path / "big.jsonl")
    fp1 = file_fingerprint(p)
    data = bytearray(p.read_bytes())
    mid = len(data) // 2
    data[mid] = ord("x") if data[mid] != ord("x") else ord("y")
    p.write_bytes(bytes(data))
    assert file_fingerprint(p) != fp1  # the reference implementation's head/tail hash would miss this


def test_index_build_outputs(pool_index):
    assert pool_index.n == 116
    q = pool_index.quality
    assert q["valid_records"] == 116 and q["rejected_records"] == 0
    rec = pool_index.record_by_id("CAND_0000003")
    assert rec["profile"]["current_title"] == "HR Manager"
    codes = set(pool_index.integrity["code"])
    assert "expert_zero_duration" in codes
    assert isinstance(pd.read_parquet(pool_index.dir / "candidates.parquet"), pd.DataFrame)
