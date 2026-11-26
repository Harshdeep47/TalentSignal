"""Resume ingestion through the HTTP API: upload (files and ZIP), background
processing, dashboard counts, review/correction, publishing into a dataset,
ranking with the existing engine, privacy and session isolation. Also covers
the v1 -> v2 database migration."""
from __future__ import annotations

import io
import json
import sqlite3
import time
import uuid
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.database.db import Database
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "resumes"
JD_PATH = ROOT / "engine" / "resources" / "jobs" / "sample_senior_ai_engineer.txt"


def H(session: str) -> dict:
    return {"X-Session-Id": session}


def _files(*names: str) -> list:
    return [("files", (n, (FIX / n).read_bytes(), "application/octet-stream")) for n in names]


def _wait(fn, ok, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        body = fn()
        if ok(body):
            return body
        time.sleep(0.25)
    raise AssertionError(f"timeout: {body}")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("resumes_api")
    settings = Settings(data_dir=root / "data", artifacts_dir=root / "artifacts", import_dirs=[root],
                        library_datasets=[], max_upload_mb=5, max_resume_zip_mb=12, frontend_dist=root / "no_dist")
    app = create_app(settings, register_library=False)
    with TestClient(app) as c:
        c.settings = settings  # type: ignore[attr-defined]
        yield c


@pytest.fixture(scope="module")
def session():
    return str(uuid.uuid4())


def _batch_done(client, session, bid):
    return _wait(lambda: client.get(f"/api/resume-batches/{bid}", headers=H(session)).json(),
                 lambda b: b["job"] and b["job"]["status"] in ("succeeded", "failed", "cancelled")
                 and b["counts"]["queued"] == 0 and b["counts"]["processing"] == 0)


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("../../escape/rohan_copy.docx", (FIX / "rohan_mehta.docx").read_bytes())  # duplicate + zip slip
        z.writestr("nested.zip", b"PK\x03\x04")
        z.writestr("photo.png", b"\x89PNG")
        z.writestr("fake.pdf", b"this is not really a pdf, only the name says so")
        z.writestr("__MACOSX/._asha.pdf", b"junk")
    return buf.getvalue()


@pytest.fixture(scope="module")
def batch(client, session):
    r = client.post("/api/resume-batches", headers=H(session), json={"name": "Autumn hiring"})
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    up = client.post(f"/api/resume-batches/{bid}/files", headers=H(session),
                     files=_files("asha_verma.pdf", "rohan_mehta.docx", "priya_nair_dup.pdf", "scanned.pdf",
                                  "encrypted.pdf", "corrupted.pdf", "not_a_resume.txt")
                     + [("files", ("archive.zip", _zip_bytes(), "application/zip"))])
    assert up.status_code == 201, up.text
    summary = up.json()["summary"]
    # 7 direct files + 4 archive members (the __MACOSX entry is ignored)
    assert summary["received"] == 11 and summary["archives"] == 1
    return _batch_done(client, session, bid)


def _docs(client, session, bid, **params):
    return client.get(f"/api/resume-batches/{bid}/documents", headers=H(session), params=params).json()


def _doc_by_name(client, session, bid, filename):
    items = _docs(client, session, bid, limit=500)["items"]
    return next(d for d in items if d["filename"] == filename)


def test_processing_dashboard_counts(client, session, batch):
    c = batch["counts"]
    assert batch["job"]["status"] == "succeeded" and batch["job"]["kind"] == "resume"
    assert c["total"] == 11
    assert c["needs_review"] == 2 and c["processed"] == 2
    assert c["duplicate"] == 2                  # priya_nair_dup.pdf + rohan_copy.docx (from the ZIP)
    assert c["failed"] == 7                     # scanned, encrypted, corrupted, txt, nested zip, png, fake pdf


def test_failure_reasons_are_specific(client, session, batch):
    failed = {d["filename"]: d["error_code"] for d in _docs(client, session, batch["id"], status="failed")["items"]}
    assert failed == {"scanned.pdf": "no_text_layer", "encrypted.pdf": "encrypted", "corrupted.pdf": "corrupted",
                      "not_a_resume.txt": "unsupported_format", "nested.zip": "nested_archive",
                      "photo.png": "unsupported_format", "fake.pdf": "unsupported_format"}
    scanned = _doc_by_name(client, session, batch["id"], "scanned.pdf")
    assert "OCR is not supported" in scanned["error"]


def test_duplicates_and_zip_slip_names(client, session, batch):
    dup = _doc_by_name(client, session, batch["id"], "rohan_copy.docx")   # directory parts were dropped
    orig = _doc_by_name(client, session, batch["id"], "rohan_mehta.docx")
    assert dup["status"] == "duplicate" and dup["duplicate_of"] == orig["id"]
    data_dir = client.settings.data_dir
    assert not list(data_dir.parent.glob("escape*")) and not list(data_dir.glob("**/escape*"))
    files = sorted(p.name for p in (client.settings.resumes_dir / batch["id"]).iterdir())
    # only server-named originals + extractions are stored; failed/duplicate uploads are not kept
    # 2 parsed documents (original + extraction JSON each) + 3 originals that failed extraction
    # (kept so they can be downloaded or retried); rejected uploads and duplicates are not stored.
    assert len(files) == 2 * 2 + 3
    assert all(not f.startswith(".") for f in files)


def test_document_detail_has_provenance_and_status(client, session, batch):
    did = _doc_by_name(client, session, batch["id"], "asha_verma.pdf")["id"]
    d = client.get(f"/api/resume-documents/{did}", headers=H(session)).json()
    ex = d["extraction"]
    assert d["status"] == "needs_review" and d["candidate_id"].startswith("RES_")
    assert ex["identity"]["name"] == {"value": "Asha Verma", "status": "stated", "note": None,
                                      "source": {"page": 1, "line": 1, "text": "Asha Verma"}}
    assert ex["education"][0]["degree"]["source"]["page"] == 2
    assert d["text_pages"][0][0] == "Asha Verma" and len(d["text_pages"]) == 2
    assert d["record"]["profile"]["anonymized_name"] == "Asha Verma"
    assert d["has_original"] is True and d["edited_fields"] == []
    assert "asha.verma@example.com" not in json.dumps(d["record"])


def test_original_download_is_attachment(client, session, batch):
    did = _doc_by_name(client, session, batch["id"], "asha_verma.pdf")["id"]
    r = client.get(f"/api/resume-documents/{did}/original", headers=H(session))
    assert r.status_code == 200 and r.content == (FIX / "asha_verma.pdf").read_bytes()
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["content-type"] == "application/pdf"


def test_review_edit_validation_and_status(client, session, batch):
    did = _doc_by_name(client, session, batch["id"], "rohan_mehta.docx")["id"]
    d = client.get(f"/api/resume-documents/{did}", headers=H(session)).json()
    rec = d["record"]
    rec["profile"]["current_title"] = "Senior Backend Engineer"
    rec["skills"].append({"name": "Kafka", "proficiency": "intermediate"})
    rec["candidate_id"] = "HIJACK_1"   # ignored: the id is fixed by the service
    r = client.patch(f"/api/resume-documents/{did}", headers=H(session), json={"record": rec})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["record"]["candidate_id"] == d["candidate_id"]
    assert "profile.current_title" in body["edited_fields"] and "skills" in body["edited_fields"]
    assert body["edited"] == 1 and body["title"] == "Senior Backend Engineer"
    bad = client.patch(f"/api/resume-documents/{did}", headers=H(session), json={"record": {"profile": "x"}})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_record"
    failed = _doc_by_name(client, session, batch["id"], "scanned.pdf")["id"]
    assert client.post(f"/api/resume-documents/{failed}/approve", headers=H(session)).status_code == 409
    assert client.post(f"/api/resume-documents/{did}/reject", headers=H(session)).json()["status"] == "rejected"
    assert client.post(f"/api/resume-documents/{did}/approve", headers=H(session)).json()["status"] == "approved"


def test_session_isolation(client, session, batch):
    other = H(str(uuid.uuid4()))
    did = _doc_by_name(client, session, batch["id"], "asha_verma.pdf")["id"]
    assert client.get(f"/api/resume-batches/{batch['id']}", headers=other).status_code == 404
    assert client.get(f"/api/resume-documents/{did}", headers=other).status_code == 404
    assert client.get(f"/api/resume-documents/{did}/original", headers=other).status_code == 404
    assert client.get("/api/resume-batches", headers=other).json() == []


def test_publish_and_rank_with_existing_engine(client, session, batch):
    bid = batch["id"]
    empty = client.post("/api/resume-batches", headers=H(session), json={"name": "empty"}).json()
    assert client.post(f"/api/resume-batches/{empty['id']}/publish", headers=H(session)).status_code == 409
    asha = _doc_by_name(client, session, bid, "asha_verma.pdf")
    # approve explicitly so the test does not depend on warning counts
    client.post(f"/api/resume-documents/{asha['id']}/approve", headers=H(session))
    r = client.post(f"/api/resume-batches/{bid}/publish", headers=H(session), json={"name": "Autumn pool"})
    assert r.status_code == 201, r.text
    assert r.json()["published"] == 2
    ds_id = r.json()["dataset"]["id"]
    ds = _wait(lambda: client.get(f"/api/datasets/{ds_id}", headers=H(session)).json(),
               lambda d: d["status"] in ("ready", "failed"))
    assert ds["status"] == "ready" and ds["n_candidates"] == 2, ds
    text = JD_PATH.read_text(encoding="utf-8")
    spec = client.post("/api/jd/parse", headers=H(session), json={"text": text, "dataset_id": ds_id}).json()
    run = client.post("/api/runs", headers=H(session),
                      json={"dataset_id": ds_id, "spec": spec, "shortlist_size": None}).json()
    run = _wait(lambda: client.get(f"/api/runs/{run['id']}", headers=H(session)).json(),
                lambda x: x["status"] in ("ready", "failed"))
    assert run["status"] == "ready", run
    items = client.get(f"/api/runs/{run['id']}/results", headers=H(session)).json()["items"]
    ids = [i["candidate_id"] for i in items]
    assert ids[0] == asha["candidate_id"] and all(i.startswith("RES_") for i in ids)
    detail = client.get(f"/api/runs/{run['id']}/candidates/{ids[0]}", headers=H(session)).json()
    assert detail["summary"] and detail["record"]["profile"]["anonymized_name"] == "Asha Verma"
    link = client.get(f"/api/resume-documents/by-candidate/{ids[0]}", headers=H(session)).json()
    assert link == {"id": asha["id"], "batch_id": bid}
    exp = client.post(f"/api/runs/{run['id']}/export", headers=H(session), json={"format": "csv", "scope": "all"})
    assert exp.status_code == 200
    for secret in (b"asha.verma@example.com", b"98765 43210", b"rohan.mehta@example.org"):
        assert secret not in exp.content
    assert client.get(f"/api/resume-batches/{bid}", headers=H(session)).json()["last_dataset_id"] == ds_id


def test_limits_and_retry(client, session):
    bid = client.post("/api/resume-batches", headers=H(session), json={}).json()["id"]
    big = b"%PDF-1.4\n" + b"0" * (11 * 1024 * 1024)
    r = client.post(f"/api/resume-batches/{bid}/files", headers=H(session),
                    files=[("files", ("big.pdf", big, "application/pdf")),
                           ("files", ("huge.zip", b"PK\x03\x04" + b"0" * (13 * 1024 * 1024), "application/zip"))])
    assert r.status_code == 201
    # big.pdf is stored (under the upload limit) but fails extraction's per-resume size cap
    _batch_done(client, session, bid)
    failed = {d["filename"]: d["error_code"] for d in _docs(client, session, bid, status="failed")["items"]}
    assert failed == {"big.pdf": "too_large", "huge.zip": "too_large"}
    again = client.post(f"/api/resume-batches/{bid}/process", headers=H(session), json={"retry_failed": True})
    assert again.status_code == 200
    _batch_done(client, session, bid)
    assert client.get(f"/api/resume-batches/{bid}", headers=H(session)).json()["counts"]["failed"] == 2
    assert client.post(f"/api/resume-batches/{bid}/files", headers=H(session), files=[]).status_code in (400, 422)


def _variant_pdf(headline: str) -> bytes:
    import sys
    sys.path.insert(0, str(FIX))
    from make_fixtures import ASHA_PAGES, make_pdf
    pages = [list(p) for p in ASHA_PAGES]
    pages[0][1] = headline
    return make_pdf(pages)


def test_approve_clean_and_delete_batch(client, session):
    s2 = H(str(uuid.uuid4()))   # fresh session: no earlier uploads to match against
    bid = client.post("/api/resume-batches", headers=s2, json={"name": "clean"}).json()["id"]
    # Two different files (different bytes) for the same person (same e-mail address).
    client.post(f"/api/resume-batches/{bid}/files", headers=s2,
                files=[("files", ("asha_2024.pdf", _variant_pdf("ML Engineer"), "application/pdf")),
                       ("files", ("asha_2025.pdf", _variant_pdf("Staff ML Engineer"), "application/pdf"))])
    b = _batch_done(client, session=s2["X-Session-Id"], bid=bid)
    assert b["counts"]["needs_review"] == 2 and b["counts"]["duplicate"] == 0
    docs = {d["filename"]: d for d in _docs(client, s2["X-Session-Id"], bid)["items"]}
    first, second = docs["asha_2024.pdf"], docs["asha_2025.pdf"]
    assert first["possible_duplicate_of"] is None and second["possible_duplicate_of"] == first["id"]
    detail = client.get(f"/api/resume-documents/{second['id']}", headers=s2).json()
    assert detail["possible_duplicate_of_doc"]["filename"] == "asha_2024.pdf"
    assert any("possible duplicate" in w for w in detail["extraction"]["warnings"])
    # The contact key is a hash - the raw e-mail never reaches the database.
    raw = sqlite3.connect(client.settings.db_path).execute(
        "SELECT contact_key FROM resume_documents WHERE id=?", (first["id"],)).fetchone()[0]
    assert raw and "@" not in raw and len(raw) == 64
    # Only the clean document is bulk-approved; the possible duplicate waits for a human.
    assert client.post(f"/api/resume-batches/{bid}/approve-clean", headers=s2).json() == {"approved": 1}
    assert client.delete(f"/api/resume-batches/{bid}", headers=s2).status_code == 204
    assert not (client.settings.resumes_dir / bid).exists()
    assert client.get(f"/api/resume-documents/{first['id']}", headers=s2).status_code == 404


def test_schema_migration_from_v1(tmp_path):
    db_path = tmp_path / "old.sqlite3"
    c = sqlite3.connect(db_path)
    c.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta VALUES ('schema_version', '1');
        CREATE TABLE jobs (id TEXT PRIMARY KEY, owner TEXT,
            kind TEXT NOT NULL CHECK (kind IN ('index', 'rank')), target_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
            progress REAL NOT NULL DEFAULT 0, message TEXT, error TEXT, created_at REAL NOT NULL,
            started_at REAL, finished_at REAL);
        INSERT INTO jobs (id, kind, target_id, status, created_at) VALUES ('j1', 'index', 'd1', 'succeeded', 1.0);
    """)
    c.commit()
    c.close()
    db = Database(db_path)
    assert db.schema_version() == 2
    assert db.one("SELECT * FROM jobs WHERE id='j1'")["kind"] == "index"
    db.insert("jobs", {"id": "j2", "kind": "resume", "target_id": "b1", "status": "queued", "created_at": 2.0})
    with pytest.raises(sqlite3.IntegrityError):
        db.insert("jobs", {"id": "j3", "kind": "bogus", "target_id": "b1", "status": "queued", "created_at": 2.0})
    assert db.one("SELECT name FROM sqlite_master WHERE name='resume_documents'")
    Database(db_path)  # re-opening is idempotent
    assert db.schema_version() == 2
