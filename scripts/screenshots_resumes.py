"""Capture screenshots of the resume-intake pages (headless Edge, CDP).

Starts nothing itself: point it at a running server. It creates its own
session and batch, uploads the sample fixtures (fictional people) plus a ZIP
with problem files, approves and publishes one profile, then screenshots the
batch dashboard and the review page.

    python scripts/screenshots_resumes.py [--base http://127.0.0.1:8000]
"""
from __future__ import annotations

import argparse
import base64
import io
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.screenshots import CDP, EDGE  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
FIX = ROOT / "tests" / "fixtures" / "resumes"
PORT = 9334


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--edge", default=EDGE)
    args = ap.parse_args()
    sid = str(uuid.uuid4())
    api = httpx.Client(base_url=args.base, headers={"X-Session-Id": sid}, timeout=300)
    bid = api.post("/api/resume-batches", json={"name": "Search team - November"}).json()["id"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("more/rohan_copy.docx", (FIX / "rohan_mehta.docx").read_bytes())
        z.writestr("more/old_cv.doc", b"\xd0\xcf\x11\xe0legacy")
    files = [("files", (n, (FIX / n).read_bytes())) for n in
             ("asha_verma.pdf", "rohan_mehta.docx", "scanned.pdf", "encrypted.pdf", "corrupted.pdf")]
    files.append(("files", ("more_resumes.zip", buf.getvalue())))
    api.post(f"/api/resume-batches/{bid}/files", files=files).raise_for_status()
    while api.get(f"/api/resume-batches/{bid}").json()["counts"]["queued"]:
        time.sleep(0.5)
    time.sleep(1)
    docs = {d["filename"]: d for d in api.get(f"/api/resume-batches/{bid}/documents").json()["items"]}
    api.post(f"/api/resume-documents/{docs['rohan_mehta.docx']['id']}/approve")
    pub = api.post(f"/api/resume-batches/{bid}/publish", json={"name": "Search team resumes"}).json()
    while api.get(f"/api/datasets/{pub['dataset']['id']}").json()["status"] not in ("ready", "failed"):
        time.sleep(0.5)

    profile = tempfile.mkdtemp(prefix="ts-edge-")
    proc = subprocess.Popen([args.edge, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
                             "--window-size=1440,1000", "--hide-scrollbars", "--no-first-run", "about:blank"])
    try:
        for _ in range(50):
            try:
                page = next(t for t in httpx.get(f"http://127.0.0.1:{PORT}/json").json() if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.2)
        cdp = CDP(page["webSocketDebuggerUrl"])
        cdp.call("Page.enable")
        cdp.call("Page.navigate", url=args.base + "/")
        time.sleep(1.5)
        cdp.js(f"localStorage.setItem('talentsignal.session', '{sid}')")

        def shot(name: str, path: str, width: int = 1440, setup: str | None = None, full: bool = True):
            cdp.call("Emulation.setDeviceMetricsOverride", width=width, height=1000, deviceScaleFactor=1, mobile=width < 800)
            cdp.call("Page.navigate", url=args.base + path)
            time.sleep(2.5)
            if setup:
                cdp.js(setup)
                time.sleep(1)
            h = min(int(cdp.js("document.documentElement.scrollHeight") or 1000), 4200) if full else 1000
            cdp.call("Emulation.setDeviceMetricsOverride", width=width, height=h, deviceScaleFactor=1, mobile=width < 800)
            time.sleep(0.4)
            overflow = cdp.js("document.documentElement.scrollWidth > window.innerWidth")
            data = cdp.call("Page.captureScreenshot", format="png")["data"]
            (OUT / f"{name}.png").write_bytes(base64.b64decode(data))
            print("saved", name, h, "horizontal overflow" if overflow else "")

        asha = docs["asha_verma.pdf"]["id"]
        locate = "(()=>{const b=[...document.querySelectorAll('button.chip')].find(x=>x.textContent.startsWith('p.2'));b&&b.click();})()"
        shot("11_resume_batch", f"/resumes/{bid}")
        shot("12_resume_review", f"/resumes/{bid}/documents/{asha}", setup=locate)
        shot("13_resume_review_mobile", f"/resumes/{bid}/documents/{asha}", width=390, full=False)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
