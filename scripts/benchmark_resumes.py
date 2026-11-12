"""Benchmark resume ingestion end to end through the real API.

    python scripts/benchmark_resumes.py [--n 10000] [--no-index] [--out FILE]

1. Generates N synthetic, fictional resumes (about 70% PDF, 30% DOCX, plus
   ~1% scanned and ~0.5% corrupted files) into one ZIP archive.
2. Starts the app in-process (temporary data directory) and, through HTTP:
   creates a batch, uploads the ZIP, waits for background processing,
   bulk-approves clean documents, publishes them and (unless --no-index)
   waits for the existing index build.
3. Reports wall time per stage, documents per second and peak process memory.

The generated resumes are template-based, so they are far more regular than
real resumes: the timings measure throughput and memory, NOT parsing accuracy.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend"), str(ROOT / "tests" / "fixtures" / "resumes")]

from make_fixtures import make_docx, make_pdf, make_scanned_pdf  # noqa: E402
from scripts._mem import PeakMemory  # noqa: E402

FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Sara", "Vikram", "Anika", "Dev", "Isha", "Arjun", "Nisha"]
LAST = ["Sharma", "Iyer", "Khan", "Patel", "Reddy", "Das", "Menon", "Gupta", "Joshi", "Bose", "Rao", "Kulkarni"]
TITLES = ["Machine Learning Engineer", "Data Scientist", "Backend Engineer", "Software Engineer",
          "Data Engineer", "Frontend Developer", "DevOps Engineer", "Product Analyst"]
COMPANIES = ["Northwind Labs", "Bluefin Systems", "Quanta Retail", "Helix Health", "Orbit Fintech", "Lumen AI"]
SKILLS = ["Python", "SQL", "Java", "Go", "PyTorch", "TensorFlow", "scikit-learn", "Docker", "Kubernetes", "AWS",
          "React", "TypeScript", "PostgreSQL", "Redis", "Apache Spark", "Airflow", "NLP", "FastAPI"]
CITIES = ["Bengaluru", "Pune", "Hyderabad", "Chennai", "Mumbai", "Noida", "Gurgaon", "Kochi"]


def resume_lines(rng: random.Random, i: int) -> list[str]:
    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    title = rng.choice(TITLES)
    y0 = rng.randint(2008, 2020)
    y1 = rng.randint(y0 + 1, 2024)
    skills = rng.sample(SKILLS, rng.randint(4, 9))
    return [
        name, title, f"{rng.choice(CITIES)}, India",
        f"candidate{i}@example.com | +91 9{rng.randint(100000000, 999999999)}",
        "Summary", f"{title} with {2025 - y0} years of experience building production software and data systems.",
        "Experience",
        f"{title} | {rng.choice(COMPANIES)}", f"Jan {y1} - Present",
        f"- Built services in {skills[0]} and {skills[1]}; improved latency by {rng.randint(5, 60)}%.",
        f"Software Engineer, {rng.choice(COMPANIES)}", f"Jun {y0} - Dec {y1 - 1}",
        f"- Delivered features using {skills[2]} and {skills[3]}.",
        "Education", "B.Tech in Computer Science", f"National Institute of Technology, {y0 - 4} - {y0}",
        "Skills", ", ".join(skills),
    ]


def build_zip(path: Path, n: int, seed: int = 7) -> dict:
    rng = random.Random(seed)
    scanned = make_scanned_pdf()
    counts = {"pdf": 0, "docx": 0, "scanned": 0, "corrupted": 0}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(n):
            r = rng.random()
            if r < 0.01:
                z.writestr(f"resumes/scan_{i:05d}.pdf", scanned + str(i).encode())
                counts["scanned"] += 1
            elif r < 0.015:
                z.writestr(f"resumes/broken_{i:05d}.pdf", b"%PDF-1.4\n" + rng.randbytes(600))
                counts["corrupted"] += 1
            elif r < 0.715:
                z.writestr(f"resumes/cv_{i:05d}.pdf", make_pdf([resume_lines(rng, i)]))
                counts["pdf"] += 1
            else:
                z.writestr(f"resumes/cv_{i:05d}.docx", make_docx(resume_lines(rng, i)))
                counts["docx"] += 1
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10_000)
    ap.add_argument("--no-index", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    from fastapi.testclient import TestClient
    from app.core.config import Settings
    from app.main import create_app

    tmp = Path(tempfile.mkdtemp(prefix="ts-resume-bench-"))
    zpath = tmp / "resumes.zip"
    t0 = time.perf_counter()
    gen = build_zip(zpath, args.n)
    t_gen = time.perf_counter() - t0
    print(f"generated {args.n:,} files ({gen}) -> {zpath.stat().st_size / 1e6:.1f} MB in {t_gen:.1f}s")

    settings = Settings(data_dir=tmp / "data", artifacts_dir=tmp / "artifacts", import_dirs=[tmp],
                        library_datasets=[], frontend_dist=tmp / "no_dist", log_level="WARNING")
    H = {"X-Session-Id": str(uuid.uuid4())}
    stages: dict[str, float] = {}
    with PeakMemory() as mem, TestClient(create_app(settings, register_library=False)) as c:
        bid = c.post("/api/resume-batches", headers=H, json={"name": "benchmark"}).json()["id"]
        t = time.perf_counter()
        with open(zpath, "rb") as f:
            r = c.post(f"/api/resume-batches/{bid}/files", headers=H,
                       files=[("files", ("resumes.zip", f, "application/zip"))])
        r.raise_for_status()
        stages["upload_and_unpack_s"] = time.perf_counter() - t
        t = time.perf_counter()
        while True:
            b = c.get(f"/api/resume-batches/{bid}", headers=H).json()
            if b["counts"]["queued"] == 0 and b["counts"]["processing"] == 0 and b["job"] \
                    and b["job"]["status"] != "running":
                break
            time.sleep(1)
        stages["process_s"] = time.perf_counter() - t
        counts = b["counts"]
        t = time.perf_counter()
        approved = c.post(f"/api/resume-batches/{bid}/approve-clean", headers=H).json()["approved"]
        stages["approve_clean_s"] = time.perf_counter() - t
        t = time.perf_counter()
        pub = c.post(f"/api/resume-batches/{bid}/publish", headers=H, json={"name": "benchmark"}).json()
        stages["publish_s"] = time.perf_counter() - t
        if args.no_index:  # do not leave the index job running while the interpreter exits
            job = (pub["dataset"].get("job") or {}).get("id")
            if job:
                c.post(f"/api/jobs/{job}/cancel", headers=H)
                while c.get(f"/api/jobs/{job}", headers=H).json()["status"] in ("queued", "running"):
                    time.sleep(0.5)
        else:
            t = time.perf_counter()
            while True:
                d = c.get(f"/api/datasets/{pub['dataset']['id']}", headers=H).json()
                if d["status"] in ("ready", "failed"):
                    break
                time.sleep(1)
            stages["index_s"] = time.perf_counter() - t
            stages["index_status"] = d["status"]  # type: ignore[assignment]
            stages["indexed_candidates"] = d["n_candidates"]  # type: ignore[assignment]
    result = {
        "n_files": args.n, "generated": gen, "zip_mb": round(zpath.stat().st_size / 1e6, 1),
        "counts": counts, "approved_clean": approved, "published": pub["published"],
        "stages": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in stages.items()},
        "docs_per_second_processing": round(args.n / stages["process_s"], 1),
        "peak_process_memory_mb": mem.peak_mb,
        "machine_note": "single process; one processing worker thread; see docs/RESUME_INGESTION.md",
    }
    print(json.dumps(result, indent=2))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
