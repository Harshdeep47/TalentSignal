"""Saved shortlists: named sets of candidates from one run, with recruiter notes."""
from __future__ import annotations

from app.core.errors import AppError
from app.database.db import Database, new_id, now
from app.services.runs import RunService


class ShortlistService:
    def __init__(self, db: Database, runs: RunService):
        self.db = db
        self.runs = runs

    def list(self, owner: str) -> list[dict]:
        return self.db.query(
            "SELECT s.id, s.name, s.run_id, s.created_at, r.jd_title, "
            "(SELECT COUNT(*) FROM shortlist_items i WHERE i.shortlist_id = s.id) AS size "
            "FROM shortlists s JOIN runs r ON r.id = s.run_id WHERE s.owner = ? ORDER BY s.created_at DESC", (owner,))

    def get(self, sid: str, owner: str) -> dict:
        row = self.db.one("SELECT * FROM shortlists WHERE id = ? AND owner = ?", (sid, owner))
        if not row:
            raise AppError(404, "shortlist_not_found", "Shortlist not found.")
        row["items"] = self.db.query("SELECT candidate_id, note, added_at FROM shortlist_items WHERE shortlist_id = ? "
                                     "ORDER BY added_at", (sid,))
        return row

    def _check_ids(self, run_id: str, owner: str, ids: list[str]) -> None:
        if not ids:
            return
        known = set(self.runs.table(run_id, owner)["candidate_id"])
        unknown = [c for c in ids if c not in known]
        if unknown:
            raise AppError(422, "unknown_candidates", f"Not in this run's results: {', '.join(unknown[:5])}")

    def create(self, owner: str, run_id: str, name: str, ids: list[str]) -> dict:
        self.runs.get(run_id, owner)
        self._check_ids(run_id, owner, ids)
        sid = new_id()
        self.db.insert("shortlists", {"id": sid, "owner": owner, "run_id": run_id, "name": name.strip(),
                                      "created_at": now()})
        for cid in dict.fromkeys(ids):
            self.db.insert("shortlist_items", {"shortlist_id": sid, "candidate_id": cid, "note": "", "added_at": now()})
        self.db.log_activity(owner, "shortlist", f"Shortlist '{name}' created with {len(ids)} candidates", sid)
        return self.get(sid, owner)

    def add(self, sid: str, owner: str, cid: str, note: str) -> dict:
        sl = self.get(sid, owner)
        self._check_ids(sl["run_id"], owner, [cid])
        self.db.execute("INSERT INTO shortlist_items(shortlist_id, candidate_id, note, added_at) VALUES (?,?,?,?) "
                        "ON CONFLICT(shortlist_id, candidate_id) DO UPDATE SET note = excluded.note",
                        (sid, cid, note, now()))
        return self.get(sid, owner)

    def remove(self, sid: str, owner: str, cid: str) -> dict:
        self.get(sid, owner)
        self.db.execute("DELETE FROM shortlist_items WHERE shortlist_id = ? AND candidate_id = ?", (sid, cid))
        return self.get(sid, owner)

    def delete(self, sid: str, owner: str) -> None:
        self.get(sid, owner)
        self.db.execute("DELETE FROM shortlists WHERE id = ?", (sid,))
