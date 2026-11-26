"""End-to-end smoke test against a RUNNING server (default http://127.0.0.1:8000).

Exercises the real workflow on the shared library dataset and prints API
response times. Usage:

    python scripts/smoke_test.py [--base http://127.0.0.1:8000] [--size 100]
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
import uuid

import httpx

JD = "engine/resources/jobs/sample_senior_ai_engineer.txt"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--size", type=int, default=100)
    args = ap.parse_args()
    h = {"X-Session-Id": str(uuid.uuid4())}
    c = httpx.Client(base_url=args.base, headers=h, timeout=300)
    timings: dict[str, list[float]] = {}

    def call(name: str, method: str, url: str, **kw):
        t = time.perf_counter()
        r = c.request(method, url, **kw)
        timings.setdefault(name, []).append((time.perf_counter() - t) * 1000)
        if r.status_code >= 400:
            sys.exit(f"{name} failed: {r.status_code} {r.text[:300]}")
        return r

    health = call("health", "GET", "/api/health").json()
    print("health:", health)
    t0 = time.time()
    while True:
        ds = [d for d in call("datasets", "GET", "/api/datasets").json() if d["shared"]]
        if ds and ds[0]["status"] == "ready":
            break
        if time.time() - t0 > 900:
            sys.exit("library dataset never became ready")
        time.sleep(2)
    d = ds[0]
    print(f"dataset: {d['name']} {d['n_candidates']:,} candidates")
    page = call("frontend", "GET", "/").text
    assert "<div id=\"root\">" in page, "frontend not served"
    spec = call("jd_parse", "POST", "/api/jd/parse", json={"text": open(JD, encoding="utf-8").read(),
                                                           "dataset_id": d["id"]}).json()
    t_run = time.perf_counter()
    run = call("run_create", "POST", "/api/runs", json={"dataset_id": d["id"], "spec": spec,
                                                        "shortlist_size": args.size}).json()
    while True:
        r = call("run_poll", "GET", f"/api/runs/{run['id']}").json()
        if r["status"] in ("ready", "failed", "cancelled"):
            break
        time.sleep(0.5)
    print(f"run: {r['status']} in {time.perf_counter() - t_run:.1f}s; eligible {r['n_eligible']:,}; results {r['n_results']}")
    assert r["status"] == "ready", r
    rid = run["id"]
    for _ in range(5):
        call("results_page", "GET", f"/api/runs/{rid}/results?page=1&page_size=50")
        call("results_filtered", "GET", f"/api/runs/{rid}/results?countries=India&min_years=5&sort=overall&order=desc")
    top = call("results_page", "GET", f"/api/runs/{rid}/results?page_size=5").json()["items"]
    call("facets", "GET", f"/api/runs/{rid}/facets")
    for item in top:
        call("candidate_detail", "GET", f"/api/runs/{rid}/candidates/{item['candidate_id']}")
    call("compare", "POST", f"/api/runs/{rid}/compare", json={"candidate_ids": [t["candidate_id"] for t in top[:3]]})
    for fmt in ("csv", "xlsx", "pdf"):
        call(f"export_{fmt}", "POST", f"/api/runs/{rid}/export", json={"format": fmt})
    comp = call("export_competition", "POST", f"/api/runs/{rid}/export/competition")
    lines = comp.text.splitlines()
    assert len(lines) == 101 and lines[0] == "candidate_id,rank,score,reasoning"
    call("dashboard", "GET", "/api/dashboard")
    print("\nAPI latency (ms): name  median  max  n")
    for k, v in timings.items():
        print(f"  {k:20s} {statistics.median(v):8.1f} {max(v):8.1f} {len(v):3d}")
    print("\nTop 5:", [(t["rank"], t["candidate_id"], t["title"], round(t["overall"], 3)) for t in top])
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
