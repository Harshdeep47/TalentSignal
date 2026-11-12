"""Offline index build (the "precompute" stage).

One streaming pass over the candidate file produces, in ``out_dir``:

  records.jsonl + offsets.npy  normalised records; O(1) random access by row
  candidates.parquet           one row per candidate (display + filter columns)
  roles.parquet                one row per career role
  skills.parquet               one row per (candidate, skill)
  texts.parquet                unique text segments (headline/summary/title/description)
  embeddings.npy               one vector per unique text segment (if model available)
  bm25_*                       sparse BM25 index
  integrity.parquet            record-level integrity flags
  quality.json                 data-quality report
  meta.json                    fingerprint, counts, as-of date, model, timings

Memory: the pass keeps only compact per-row tuples (not the parsed records),
so peak memory is dominated by the BM25 matrix, not by the raw file.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import numpy as np
import orjson
import pandas as pd
from scipy import sparse

from engine import __version__
from engine.ingestion.fingerprint import file_fingerprint
from engine.ingestion.readers import count_hint, iter_records
from engine.ingestion.validation import SIGNAL_SPEC, Normalizer
from engine.integrity.checks import check_record
from engine.retrieval.bm25 import BM25Index
from engine.retrieval.embeddings import get_embedder

INDEX_FORMAT_VERSION = 3
PROFICIENCY_LEVEL = {"beginner": 0.25, "intermediate": 0.5, "advanced": 0.75, "expert": 1.0}

ProgressFn = Callable[[float, str], None]


class Cancelled(Exception):
    pass


@dataclass
class _TextTable:
    ids: dict[str, int] = field(default_factory=dict)
    texts: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)

    def add(self, text: str, kind: str) -> int:
        if not text:
            return -1
        key = kind + "\x00" + text
        tid = self.ids.get(key)
        if tid is None:
            tid = len(self.texts)
            self.ids[key] = tid
            self.texts.append(text)
            self.kinds.append(kind)
        return tid


def _highest_degree(edu: list[dict]) -> str:
    order = ["ph.d", "phd", "m.", "mba", "ms", "b.", "bs", "diploma"]
    degrees = [e["degree"] for e in edu if e.get("degree")]
    for prefix in order:
        for d in degrees:
            if d.lower().startswith(prefix):
                return d
    return degrees[0] if degrees else ""


def build_index(source: str | Path, out_dir: str | Path, *, progress: ProgressFn | None = None,
                should_cancel: Callable[[], bool] | None = None, embed: bool = True,
                model_dir: Path | None = None) -> dict:
    """Build all artifacts for one candidate file. Returns the meta dict."""
    t_start = time.perf_counter()
    source, out = Path(source), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = progress or (lambda f, m: None)
    cancelled = should_cancel or (lambda: False)
    timings: dict[str, float] = {}

    report(0.0, "Fingerprinting file")
    fingerprint = file_fingerprint(source)
    expected = count_hint(source)
    timings["fingerprint_s"] = round(time.perf_counter() - t_start, 2)

    texts = _TextTable()
    norm = Normalizer()
    cand_rows: list[dict] = []
    role_rows: list[tuple] = []
    skill_rows: list[tuple] = []
    flag_rows: list[tuple] = []
    incidence_rows: list[int] = []
    incidence_cols: list[int] = []
    offsets: list[int] = []
    rejected: list[dict] = []
    n_rows = 0
    warn_counter: Counter = Counter()
    missing_counter: Counter = Counter()
    content_hashes: dict[str, int] = {}
    duplicates: list[tuple[int, int]] = []
    titles: Counter = Counter()
    countries: Counter = Counter()
    yoe_hist: Counter = Counter()
    last_active_max = ""
    today = date.today()

    t_pass = time.perf_counter()
    with open(out / "records.jsonl", "wb") as rec_out:
        pos = 0
        for raw in iter_records(source):
            n_rows += 1
            if n_rows % 2000 == 0:
                if cancelled():
                    raise Cancelled()
                frac = (n_rows / expected) if expected else 0.5
                report(0.02 + 0.55 * min(frac, 1.0), f"Reading candidates ({n_rows:,})")
            if raw.record is None:
                rejected.append({"row": raw.row, "reason": raw.error})
                continue
            rec, issues = norm.normalize(raw.record)
            if rec is None:
                rejected.append({"row": raw.row, "reason": issues[0].message if issues else "invalid"})
                continue
            for iss in issues:
                warn_counter[iss.field.split("[")[0].split(".")[-1] + ": " + iss.message.split(";")[0][:60]] += 1

            idx = len(cand_rows)
            line = orjson.dumps(rec) + b"\n"
            rec_out.write(line)
            offsets.append(pos)
            pos += len(line)

            p, sig, roles, skills = rec["profile"], rec["redrob_signals"], rec["career_history"], rec["skills"]
            for name in SIGNAL_SPEC:
                if sig.get(name) is None:
                    missing_counter[name] += 1
            if not sig.get("skill_assessment_scores"):
                missing_counter["skill_assessment_scores"] += 1

            seg_ids = []
            h_tid = texts.add(p["headline"], "headline")
            s_tid = texts.add(p["summary"], "summary")
            seg_ids += [h_tid, s_tid]
            for order, r in enumerate(roles):
                t_tid = texts.add(r["title"], "title")
                d_tid = texts.add(r["description"], "description")
                seg_ids += [t_tid, d_tid]
                role_rows.append((idx, order, r["title"], r["company"], r["industry"], r["company_size"] or "",
                                  r["start_date"] or "", r["end_date"] or "", r["duration_months"],
                                  r["is_current"], d_tid))
            cur_title_tid = texts.add(p["current_title"], "title")
            seg_ids.append(cur_title_tid)
            assessments = sig.get("skill_assessment_scores") or {}
            assess_lower = {k.lower(): v for k, v in assessments.items()}
            for s in skills:
                seg_ids.append(texts.add(s["name"], "skill"))
                skill_rows.append((idx, s["name"], s["proficiency"] or "",
                                   PROFICIENCY_LEVEL.get(s["proficiency"] or "", np.nan),
                                   s["duration_months"], s["endorsements"],
                                   assess_lower.get(s["name"].lower(), np.nan)))
            for tid in seg_ids:
                if tid >= 0:
                    incidence_rows.append(idx)
                    incidence_cols.append(tid)

            for fl in check_record(rec, today):
                flag_rows.append((idx, fl.code, fl.severity, fl.title, fl.detail, json.dumps(fl.evidence)))
            content = orjson.dumps({k: v for k, v in rec.items() if k != "candidate_id"} |
                                   {"profile": {k: v for k, v in p.items() if k != "anonymized_name"}},
                                   option=orjson.OPT_SORT_KEYS)
            digest = hashlib.blake2b(content, digest_size=12).hexdigest()
            if digest in content_hashes:
                duplicates.append((idx, content_hashes[digest]))
            else:
                content_hashes[digest] = idx

            edu = rec["education"]
            sal = sig.get("expected_salary_range_inr_lpa") or {}
            la = sig.get("last_active_date") or ""
            last_active_max = max(last_active_max, la)
            titles[p["current_title"]] += 1
            countries[p["country"]] += 1
            if p["years_of_experience"] is not None:
                yoe_hist[int(min(p["years_of_experience"], 30))] += 1
            cand_rows.append({
                "idx": idx,
                "candidate_id": rec["candidate_id"],
                "name": p["anonymized_name"],
                "headline": p["headline"],
                "headline_tid": h_tid,
                "summary_tid": s_tid,
                "title": p["current_title"],
                "company": p["current_company"],
                "industry": p["current_industry"],
                "company_size": p["current_company_size"] or "",
                "location": p["location"],
                "city": p["location"].split(",")[0].strip(),
                "country": p["country"],
                "years_experience": p["years_of_experience"],
                "n_roles": len(roles),
                "fields_of_study": "; ".join(sorted({e["field_of_study"] for e in edu if e["field_of_study"]})),
                "highest_degree": _highest_degree(edu),
                "skills": "|".join(s["name"] for s in skills),
                "n_skills": len(skills),
                "n_assessments": len(assessments),
                "certifications": "|".join(c.get("name") or "" for c in rec["certifications"]),
                "salary_min": sal.get("min"),
                "salary_max": sal.get("max"),
                **{f"sig_{k}": sig.get(k) for k in SIGNAL_SPEC},
            })
    timings["parse_s"] = round(time.perf_counter() - t_pass, 2)
    n = len(cand_rows)
    if n == 0:
        raise ValueError("No valid candidate records were found in the file.")

    report(0.6, "Writing tables")
    cand_df = pd.DataFrame(cand_rows)
    for col in ("sig_signup_date", "sig_last_active_date"):
        cand_df[col] = cand_df[col].astype("string")
    cand_df.to_parquet(out / "candidates.parquet", index=False)
    roles_df = pd.DataFrame(role_rows, columns=["idx", "order", "title", "company", "industry", "company_size",
                                                "start_date", "end_date", "months", "is_current", "text_id"])
    roles_df["months"] = roles_df["months"].astype("float32")
    roles_df.to_parquet(out / "roles.parquet", index=False)
    skills_df = pd.DataFrame(skill_rows, columns=["idx", "skill", "proficiency", "level", "months",
                                                  "endorsements", "assessed"])
    for c in ("level", "months", "endorsements", "assessed"):
        skills_df[c] = skills_df[c].astype("float32")
    skills_df.to_parquet(out / "skills.parquet", index=False)
    for dup_idx, orig_idx in duplicates:
        flag_rows.append((dup_idx, "duplicate_profile", "warning", "Possible duplicate profile",
                          f"Content is identical to {cand_rows[orig_idx]['candidate_id']} apart from id and name.",
                          json.dumps({"duplicate_of": cand_rows[orig_idx]["candidate_id"]})))
    flags_df = pd.DataFrame(flag_rows, columns=["idx", "code", "severity", "title", "detail", "evidence"])
    flags_df["idx"] = flags_df["idx"].astype("int64")  # keep integer dtype even when there are no flags
    flags_df.to_parquet(out / "integrity.parquet", index=False)
    pd.DataFrame({"text": texts.texts, "kind": texts.kinds}).to_parquet(out / "texts.parquet", index=False)
    np.save(out / "offsets.npy", np.asarray(offsets, dtype=np.int64))
    if cancelled():
        raise Cancelled()

    report(0.65, "Building BM25 index")
    t_bm = time.perf_counter()
    incidence = sparse.csr_matrix(
        (np.ones(len(incidence_rows), dtype=np.float32), (incidence_rows, incidence_cols)),
        shape=(n, len(texts.texts)))
    BM25Index.build(texts.texts, incidence).save(out)
    del incidence, incidence_rows, incidence_cols
    timings["bm25_s"] = round(time.perf_counter() - t_bm, 2)

    model_name = None
    if embed:
        embedder = get_embedder(model_dir)
        if embedder is not None:
            embed_ids = [i for i, k in enumerate(texts.kinds) if k != "skill"]
            report(0.7, f"Embedding {len(embed_ids):,} unique text segments")
            t_emb = time.perf_counter()

            def _p(done: int, total: int) -> None:
                report(0.7 + 0.28 * done / max(total, 1), f"Embedding text segments ({done:,}/{total:,})")

            try:
                vecs = embedder.encode([texts.texts[i] for i in embed_ids], progress=_p, should_cancel=cancelled)
            except InterruptedError as exc:
                raise Cancelled() from exc
            full = np.zeros((len(texts.texts), embedder.dim), dtype=np.float16)
            full[embed_ids] = vecs.astype(np.float16)
            np.save(out / "embeddings.npy", full)
            model_name = embedder.name
            timings["embed_s"] = round(time.perf_counter() - t_emb, 2)

    sev_counts = flags_df.groupby(["code", "severity"]).size().reset_index(name="n")
    quality = {
        "rows_read": n_rows,
        "valid_records": n,
        "rejected_records": len(rejected),
        "rejected_examples": rejected[:25],
        "warnings": [{"issue": k, "count": v} for k, v in warn_counter.most_common(40)],
        "missing_values": {k: {"count": v, "pct": round(100 * v / n, 1)} for k, v in sorted(missing_counter.items())},
        "integrity": [{"code": r.code, "severity": r.severity, "count": int(r.n)} for r in sev_counts.itertuples()],
        "duplicates": len(duplicates),
        "unique_text_segments": len(texts.texts),
        "unique_descriptions": sum(1 for k in texts.kinds if k == "description"),
        "top_titles": titles.most_common(25),
        "countries": countries.most_common(20),
        "experience_histogram": sorted(yoe_hist.items()),
    }
    (out / "quality.json").write_text(json.dumps(quality, indent=1), encoding="utf-8")
    meta = {
        "format_version": INDEX_FORMAT_VERSION,
        "engine_version": __version__,
        "source_name": source.name,
        "source_fingerprint": fingerprint,
        "n_candidates": n,
        "as_of_date": last_active_max or today.isoformat(),
        "embedding_model": model_name,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "timings": {**timings, "total_s": round(time.perf_counter() - t_start, 2)},
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    report(1.0, "Index ready")
    return meta
