"""Capture UI screenshots from a running server with headless Microsoft Edge (Chrome DevTools Protocol).

Developer tool used to review the UI visually and to produce docs/screenshots.
It creates its own session, run and shortlist through the API, injects that
session id into the browser's localStorage, and screenshots each page.

    python scripts/screenshots.py [--base http://127.0.0.1:8000] [--edge PATH]
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import websocket

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9333


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, timeout=60, suppress_origin=True)
        self.i = 0

    def call(self, method: str, **params):
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.i:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    def js(self, expr: str):
        return self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True).get("result", {}).get("value")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--edge", default=EDGE)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    sid = str(uuid.uuid4())
    api = httpx.Client(base_url=args.base, headers={"X-Session-Id": sid}, timeout=300)
    ds = [d for d in api.get("/api/datasets").json() if d["shared"] and d["status"] == "ready"][0]
    spec = api.post("/api/jd/parse", json={"text": (ROOT / "engine/resources/jobs/redrob_senior_ai_engineer.txt").read_text(encoding="utf-8"),
                                           "dataset_id": ds["id"]}).json()
    run = api.post("/api/runs", json={"dataset_id": ds["id"], "spec": spec, "shortlist_size": 100}).json()
    while api.get(f"/api/runs/{run['id']}").json()["status"] != "ready":
        time.sleep(0.5)
    top = api.get(f"/api/runs/{run['id']}/results?page_size=4").json()["items"]
    ids = [t["candidate_id"] for t in top]
    sl = api.post("/api/shortlists", json={"run_id": run["id"], "name": "Search & ranking finalists", "candidate_ids": ids[:3]}).json()
    api.post(f"/api/shortlists/{sl['id']}/items", json={"candidate_id": ids[0], "note": "Strongest evaluation background; confirm notice period."})

    profile = tempfile.mkdtemp(prefix="ts-edge-")
    proc = subprocess.Popen([args.edge, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
                             "--window-size=1440,1000", "--hide-scrollbars", "--no-first-run", "about:blank"])
    try:
        for _ in range(50):
            try:
                tabs = httpx.get(f"http://127.0.0.1:{PORT}/json").json()
                page = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.2)
        cdp = CDP(page["webSocketDebuggerUrl"])
        cdp.call("Page.enable")
        cdp.call("Emulation.setDeviceMetricsOverride", width=1440, height=1000, deviceScaleFactor=1, mobile=False)
        cdp.call("Page.navigate", url=args.base + "/")
        time.sleep(1.5)
        cdp.js(f"localStorage.setItem('talentsignal.session', '{sid}')")

        def shot(name: str, path: str, wait: float = 2.5, setup: str | None = None, full: bool = True, width: int = 1440):
            cdp.call("Emulation.setDeviceMetricsOverride", width=width, height=1000, deviceScaleFactor=1, mobile=width < 800)
            cdp.call("Page.navigate", url=args.base + path)
            time.sleep(wait)
            if setup:
                cdp.js(setup)
                time.sleep(wait)
            h = cdp.js("document.documentElement.scrollHeight") or 1000
            h = min(int(h), 4200) if full else 1000
            cdp.call("Emulation.setDeviceMetricsOverride", width=width, height=h, deviceScaleFactor=1, mobile=width < 800)
            time.sleep(0.4)
            data = cdp.call("Page.captureScreenshot", format="png", captureBeyondViewport=False)["data"]
            (OUT / f"{name}.png").write_bytes(base64.b64decode(data))
            print("saved", name, h)

        rid = run["id"]
        shot("01_dashboard", "/")
        shot("02_dataset_quality", f"/datasets/{ds['id']}")
        click_preset = ("(async()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent.startsWith('Load:'));b&&b.click();"
                        "await new Promise(r=>setTimeout(r,400));const a=[...document.querySelectorAll('button')].find(x=>x.textContent.includes('Analyse'));a&&a.click();})()")
        shot("03_jd_workspace", "/rank/new", setup=click_preset)
        shot("04_results_table", f"/runs/{rid}")
        cards = "(()=>{const b=document.querySelector('[aria-label=\"Cards\"]');b&&b.closest('button').click();})()"
        shot("05_results_cards", f"/runs/{rid}", setup=cards, full=False)
        shot("06_candidate_detail", f"/runs/{rid}/candidates/{ids[0]}")
        shot("07_compare", f"/runs/{rid}/compare?ids={','.join(ids[:3])}")
        shot("08_history", "/history", full=False)
        shot("09_shortlist", f"/shortlists/{sl['id']}", full=False)
        shot("10_mobile_results", f"/runs/{rid}", full=False, width=390)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
