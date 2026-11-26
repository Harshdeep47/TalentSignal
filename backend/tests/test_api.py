"""End-to-end API tests against a real (small) dataset, using FastAPI's TestClient."""
from __future__ import annotations

import io
import json
import time
import uuid

import orjson
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.core.config import Settings
from app.main import create_app
from factories import candidate, standard_pool

JD_PATH = "engine/resources/jobs/sample_senior_ai_engineer.txt"


def _jsonl(records) -> bytes:
    return b"".join(orjson.dumps(r) + b"\n" for r in records)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("api")
    settings = Settings(data_dir=root / "data", artifacts_dir=root / "artifacts", import_dirs=[root / "imports"],
                        library_datasets=[], max_upload_mb=5, frontend_dist=root / "no_dist")
    (root / "imports").mkdir()
    app = create_app(settings, register_library=False)
    with TestClient(app) as c:
        c.root = root  # type: ignore[attr-defined]
        yield c


def H(session: str) -> dict:
    return {"X-Session-Id": session}


@pytest.fixture(scope="module")
def session():
    return str(uuid.uuid4())


def _wait(client, url, headers, done=("ready", "succeeded", "failed", "cancelled"), key="status", timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        body = client.get(url, headers=headers).json()
        if body.get(key) in done:
            return body
        time.sleep(0.3)
    raise AssertionError(f"timeout waiting for {url}: {body}")


@pytest.fixture(scope="module")
def dataset(client, session):
    recs = standard_pool(n_filler=110)
    recs[10]["profile"]["anonymized_name"] = "=HYPERLINK(\"http://evil\")"  # formula-injection probe
    r = client.post("/api/datasets/upload", headers=H(session),
                    files={"file": ("pool.jsonl", _jsonl(recs), "application/octet-stream")})
    assert r.status_code == 201, r.text
    ds = _wait(client, f"/api/datasets/{r.json()['id']}", H(session))
    assert ds["status"] == "ready", ds
    return ds


@pytest.fixture(scope="module")
def spec(client, session, dataset):
    text = open(JD_PATH, encoding="utf-8").read()
    r = client.post("/api/jd/parse", headers=H(session), json={"text": text, "dataset_id": dataset["id"]})
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def run(client, session, dataset, spec):
    r = client.post("/api/runs", headers=H(session), json={"dataset_id": dataset["id"], "spec": spec,
                                                           "shortlist_size": 25})
    assert r.status_code == 201, r.text
    body = _wait(client, f"/api/runs/{r.json()['id']}", H(session))
    assert body["status"] == "ready", body
    return body


def test_health_and_session_required(client):
    assert client.get("/api/health").json()["status"] == "ok"
    r = client.get("/api/datasets")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_session"
    assert client.get("/api/datasets", headers=H("not-a-uuid")).status_code == 400


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]


def test_dataset_quality(client, session, dataset):
    d = client.get(f"/api/datasets/{dataset['id']}", headers=H(session)).json()
    assert d["n_candidates"] == 116 and d["quality"]["valid_records"] == 116
    assert any(i["code"] == "expert_zero_duration" for i in d["quality"]["integrity"])


def test_upload_validation(client, session):
    r = client.post("/api/datasets/upload", headers=H(session), files={"file": ("x.exe", b"MZ", "application/x")})
    assert r.status_code == 415
    big = b"{}\n" * (3 * 1024 * 1024)  # ~9 MB > 5 MB limit
    r = client.post("/api/datasets/upload", headers=H(session), files={"file": ("big.jsonl", big, "x")})
    assert r.status_code == 413
    r = client.post("/api/datasets/upload", headers=H(session), files={"file": ("empty.jsonl", b"", "x")})
    assert r.status_code == 400


def test_import_path_restricted(client, session, tmp_path):
    outside = tmp_path / "c.jsonl"
    outside.write_bytes(_jsonl([candidate("CAND_0000001")]))
    r = client.post("/api/datasets/import-path", headers=H(session), json={"path": str(outside)})
    assert r.status_code == 403
    inside = client.root / "imports" / "c.jsonl"  # type: ignore[attr-defined]
    inside.write_bytes(_jsonl([candidate("CAND_0000001"), candidate("CAND_0000002")]))
    r = client.post("/api/datasets/import-path", headers=H(session), json={"path": str(inside)})
    assert r.status_code == 201
    d = _wait(client, f"/api/datasets/{r.json()['id']}", H(session))
    assert d["status"] == "ready" and d["n_candidates"] == 2
    assert client.delete(f"/api/datasets/{d['id']}", headers=H(session)).status_code == 204


def test_failed_index_is_reported(client, session):
    r = client.post("/api/datasets/upload", headers=H(session),
                    files={"file": ("bad.jsonl", b"not json\n{also bad\n", "x")})
    d = _wait(client, f"/api/datasets/{r.json()['id']}", H(session))
    assert d["status"] == "failed" and "No valid candidate records" in d["error"]


def test_jd_parse_and_upload(client, session, spec):
    assert spec["title"].startswith("Senior AI Engineer")
    assert any(r["importance"] == "mandatory" for r in spec["requirements"])
    r = client.post("/api/jd/upload", headers=H(session),
                    files={"file": ("jd.txt", b"Backend Engineer\nRequirements:\n- 4+ years with Go and REST APIs\n", "t")})
    assert r.status_code == 200 and r.json()["spec"]["experience"]["min_years"] == 4
    r = client.post("/api/jd/upload", headers=H(session), files={"file": ("jd.pdf", b"%PDF-1.4", "x")})
    assert r.status_code == 415
    assert client.post("/api/jd/parse", headers=H(session), json={"text": "short"}).status_code == 422
    assert client.get("/api/jd/presets", headers=H(session)).json()[0]["id"] == "sample_senior_ai_engineer"


def test_run_results_paging_sort_filter(client, session, run):
    rid = run["id"]
    assert run["n_results"] == 25 and run["shortlist_size"] == 25
    page = client.get(f"/api/runs/{rid}/results?page=1&page_size=10", headers=H(session)).json()
    assert page["total"] == 25 and len(page["items"]) == 10
    assert [i["rank"] for i in page["items"]] == list(range(1, 11))
    by_score = client.get(f"/api/runs/{rid}/results?sort=overall&order=desc", headers=H(session)).json()["items"]
    scores = [i["overall"] for i in by_score]
    assert scores == sorted(scores, reverse=True)
    india = client.get(f"/api/runs/{rid}/results?countries=India", headers=H(session)).json()
    assert all(i["country"] == "India" for i in india["items"])
    ranked_skill = client.get(f"/api/runs/{rid}/results?skills=FAISS", headers=H(session)).json()
    assert all("FAISS" in i["skills"] for i in ranked_skill["items"])
    held = client.get(f"/api/runs/{rid}/results?view=held", headers=H(session)).json()
    assert any(i["candidate_id"] == "CAND_0000005" for i in held["items"])
    assert client.get(f"/api/runs/{rid}/results?sort=evil", headers=H(session)).status_code == 422
    facets = client.get(f"/api/runs/{rid}/facets", headers=H(session)).json()
    assert facets["held_for_review"] >= 1 and facets["countries"]


def test_all_eligible_mode(client, session, dataset, spec):
    r = client.post("/api/runs", headers=H(session), json={"dataset_id": dataset["id"], "spec": spec,
                                                           "shortlist_size": None})
    body = _wait(client, f"/api/runs/{r.json()['id']}", H(session))
    assert body["n_results"] == body["n_eligible"] == 115


def test_candidate_detail_and_compare(client, session, run):
    rid = run["id"]
    d = client.get(f"/api/runs/{rid}/candidates/CAND_0000001", headers=H(session)).json()
    assert d["candidate_id"] == "CAND_0000001" and d["requirements"] and d["summary"]
    assert d["record"]["profile"]["current_title"] == "Machine Learning Engineer"
    assert client.get(f"/api/runs/{rid}/candidates/CAND_9999999", headers=H(session)).status_code == 404
    c = client.post(f"/api/runs/{rid}/compare", headers=H(session),
                    json={"candidate_ids": ["CAND_0000001", "CAND_0000002", "CAND_0000003"]}).json()
    assert len(c["candidates"]) == 3 and len(c["requirements"][0]["values"]) == 3
    assert client.post(f"/api/runs/{rid}/compare", headers=H(session),
                       json={"candidate_ids": ["CAND_0000001"]}).status_code == 422


def test_session_isolation(client, session, run, dataset):
    other = str(uuid.uuid4())
    assert client.get(f"/api/runs/{run['id']}", headers=H(other)).status_code == 404
    assert client.get("/api/runs", headers=H(other)).json() == []
    assert client.get(f"/api/datasets/{dataset['id']}", headers=H(other)).status_code == 404


def test_shortlists(client, session, run):
    r = client.post("/api/shortlists", headers=H(session),
                    json={"run_id": run["id"], "name": "Finalists", "candidate_ids": ["CAND_0000001"]})
    sid = r.json()["id"]
    r = client.post(f"/api/shortlists/{sid}/items", headers=H(session),
                    json={"candidate_id": "CAND_0000002", "note": "Strong on evaluation"})
    assert {i["candidate_id"] for i in r.json()["items"]} == {"CAND_0000001", "CAND_0000002"}
    bad = client.post(f"/api/shortlists/{sid}/items", headers=H(session), json={"candidate_id": "CAND_7777777"})
    assert bad.status_code == 422
    r = client.delete(f"/api/shortlists/{sid}/items/CAND_0000001", headers=H(session))
    assert [i["candidate_id"] for i in r.json()["items"]] == ["CAND_0000002"]
    assert client.get("/api/shortlists", headers=H(session)).json()[0]["size"] == 1


@pytest.mark.parametrize("fmt", ["csv", "xlsx", "json", "jsonl", "parquet", "pdf"])
def test_exports(client, session, run, fmt):
    r = client.post(f"/api/runs/{run['id']}/export", headers=H(session), json={"format": fmt, "scope": "all"})
    assert r.status_code == 200, r.text
    data = r.content
    if fmt == "csv":
        text = data.decode("utf-8-sig")
        assert "\n=HYPERLINK" not in text and ",=HYPERLINK" not in text  # formula injection neutralised
        assert text.splitlines()[0].startswith("rank,candidate_id")
    elif fmt == "xlsx":
        ws = load_workbook(io.BytesIO(data)).active
        assert ws.cell(1, 1).value == "rank"
    elif fmt == "json":
        body = json.loads(data)
        assert body["run"]["id"] == run["id"] and body["candidates"]
    elif fmt == "jsonl":
        assert json.loads(data.splitlines()[0])["candidate_id"]
    elif fmt == "parquet":
        assert data[:4] == b"PAR1"
    else:
        assert data[:4] == b"%PDF"


def test_export_with_explanations_and_errors(client, session, run):
    r = client.post(f"/api/runs/{run['id']}/export", headers=H(session),
                    json={"format": "csv", "include_explanations": True})
    assert "explanation" in r.content.decode("utf-8-sig").splitlines()[0]
    assert client.post(f"/api/runs/{run['id']}/export", headers=H(session), json={"format": "doc"}).status_code == 422


def test_competition_export(client, session, run):
    r = client.post(f"/api/runs/{run['id']}/export/competition", headers=H(session))
    assert r.status_code == 200, r.text
    lines = r.content.decode("utf-8").splitlines()
    assert lines[0] == "candidate_id,rank,score,reasoning" and len(lines) == 101


def test_dashboard_and_delete_run(client, session, run):
    d = client.get("/api/dashboard", headers=H(session)).json()
    assert d["totals"]["runs"] >= 1 and d["recent_runs"] and d["activity"]
    r = client.post(f"/api/runs/rerun/{run['id']}", headers=H(session))
    new = _wait(client, f"/api/runs/{r.json()['id']}", H(session))
    assert client.delete(f"/api/runs/{new['id']}", headers=H(session)).status_code == 204
    assert client.get(f"/api/runs/{new['id']}", headers=H(session)).status_code == 404
