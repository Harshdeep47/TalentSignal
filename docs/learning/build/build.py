"""Build the three TalentSignal learning books (Markdown -> HTML -> PDF).

Pipeline per book
  1. Concatenate chapter sources  src/bookN/*.md  ->  docs/learning/0N_<name>.md
  2. Markdown -> HTML (python-markdown + pymdown-extensions: tables, fenced code
     with Pygments highlighting, Mermaid fences, math via KaTeX, admonitions).
  3. Number parts/sections, insert invisible page markers, build the TOC.
  4. Print with headless Microsoft Edge through the DevTools protocol
     (Mermaid and KaTeX render in the browser first). Pass 1 finds the page of
     every heading (markers extracted with pypdf); pass 2 prints the final TOC.
  5. Print a separate full-bleed cover, merge, add PDF bookmarks.
  6. Quality checks: Mermaid errors, Python code syntax, runnable examples,
     page count, preview PNGs for visual review.

Run with the isolated docs toolchain (does not touch application deps):
    .tools/docs-venv/Scripts/python docs/learning/build/build.py [--books 1 2 3] [--preview]
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import markdown
import websocket
from pypdf import PdfReader, PdfWriter
from pymdownx.superfences import fence_div_format

BUILD = Path(__file__).resolve().parent
LEARN = BUILD.parent
ROOT = LEARN.parents[1]
SRC = LEARN / "src"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9341
FONTS = ROOT / "frontend" / "node_modules" / "@fontsource"
NM = BUILD / "node_modules"

BOOKS = {
    1: {"file": "01_TalentSignal_Complete_Technical_Handbook", "src": "book1", "short": "Complete Technical Handbook",
        "title": "Complete Project &amp; Technical Handbook", "volume": "Book 1 of 3",
        "tagline": "From the recruiting problem to the ranking mathematics - the whole system, explained from first principles."},
    2: {"file": "02_TalentSignal_Developer_Code_Mastery_Guide", "src": "book2", "short": "Developer Code Mastery Guide",
        "title": "Developer's Implementation &amp; Code Mastery Guide", "volume": "Book 2 of 3",
        "tagline": "Every directory, module, endpoint and table - how the real code works and how to change it safely."},
    3: {"file": "03_TalentSignal_Interview_and_Technical_Defense_Bible", "src": "book3",
        "short": "Interview & Technical Defense Bible", "title": "Interview Preparation &amp; Technical Defense Bible",
        "volume": "Book 3 of 3",
        "tagline": "Explain it, defend it, calculate it, code it - with honest answers about what the project does not do."},
}


# --------------------------------------------------------------------------- code includes
INCLUDE_RE = re.compile(r"^(?P<indent>[ \t]*)#@include (?P<path>[^:\s]+)::(?P<name>[\w.]+)\s*$", re.M)


def _python_source(path: Path, qualname: str) -> str:
    """Exact source of a function/class/method (Class.method) taken from the real file."""
    import ast
    import textwrap
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    node: ast.AST = tree
    for part in qualname.split("."):
        node = next(n for n in ast.iter_child_nodes(node)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == part)
    lines = src.splitlines()
    start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    return textwrap.dedent("\n".join(lines[start - 1: node.end_lineno]))


def _ts_source(path: Path, name: str) -> str:
    """Source of a TS/TSX function or const by brace matching (export function X / function X / const X =)."""
    src = path.read_text(encoding="utf-8")
    m = re.search(rf"^(export\s+(default\s+)?)?(async\s+)?(function\s+{name}\b|const\s+{name}\b)", src, re.M)
    if not m:
        raise KeyError(f"{name} not found in {path}")
    i = src.index("{", src.index(")", m.end()) if "(" in src[m.end(): m.end() + 200] else m.end())
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                end = src.find("\n", j)
                return src[m.start(): end if end != -1 else len(src)].rstrip().rstrip(";") + (";" if src[j + 1: j + 2] == ";" else "")
    raise ValueError(f"unbalanced braces for {name} in {path}")


def expand_includes(text: str) -> tuple[str, list[str]]:
    used: list[str] = []

    def repl(m: re.Match) -> str:
        path = ROOT / m.group("path")
        name = m.group("name")
        used.append(f"{m.group('path')}::{name}")
        code = _python_source(path, name) if path.suffix == ".py" else _ts_source(path, name)
        lang = "python" if path.suffix == ".py" else "tsx"
        caption = (f'<p class="src-caption">Source: <code>{m.group("path")}</code> &middot; '
                   f'<code>{name}</code> (inserted from the repository at build time)</p>')
        return f"{caption}\n\n```{lang}\n{code}\n```"

    return INCLUDE_RE.sub(repl, text), used


# --------------------------------------------------------------------------- markdown
def md_to_html(text: str) -> str:
    md = markdown.Markdown(
        extensions=["tables", "attr_list", "md_in_html", "def_list", "admonition", "toc", "pymdownx.superfences",
                    "pymdownx.highlight", "pymdownx.arithmatex", "pymdownx.details", "pymdownx.tasklist", "sane_lists"],
        extension_configs={
            "pymdownx.superfences": {"custom_fences": [{"name": "mermaid", "class": "mermaid", "format": fence_div_format}]},
            "pymdownx.highlight": {"use_pygments": True, "css_class": "highlight", "guess_lang": False},
            "pymdownx.arithmatex": {"generic": True},
            "toc": {"permalink": False},
            "pymdownx.tasklist": {"custom_checkbox": True},
        })
    return md.convert(text)


def number_headings(body: str) -> tuple[str, list[dict]]:
    """Number parts (h1) and sections (h2); add page markers; collect TOC entries."""
    entries: list[dict] = []
    part = 0
    appendix = 0
    sec = 0
    counter = [0]

    def marker() -> str:
        counter[0] += 1
        return f"QQMK{counter[0]:04d}QQ"

    def h1(m: re.Match) -> str:
        nonlocal part, appendix, sec
        attrs, inner = m.group(1), m.group(2)
        sec = 0
        mk = marker()
        if "appendix" in attrs:
            appendix += 1
            label = f"Appendix {chr(64 + appendix)}"
        else:
            part += 1
            label = f"Part {part}"
        entries.append({"level": 1, "label": label, "title": re.sub("<[^>]+>", "", inner), "mk": mk})
        return (f'<h1{attrs}><span class="part-label">{label}</span><span class="part-title">{inner}</span>'
                f'<span class="mk">{mk}</span></h1>')

    def h2(m: re.Match) -> str:
        nonlocal sec
        attrs, inner = m.group(1), m.group(2)
        sec += 1
        mk = marker()
        last_h1 = next((e for e in reversed(entries) if e["level"] == 1), None)
        prefix = (last_h1["label"].split()[-1] if last_h1 and last_h1["label"].startswith("Appendix") else str(part))
        num = f"{prefix}.{sec}"
        entries.append({"level": 2, "label": num, "title": re.sub("<[^>]+>", "", inner), "mk": mk})
        return f'<h2{attrs}><span class="sec-num">{num}</span>{inner}<span class="mk">{mk}</span></h2>'

    out = []
    for chunk in re.split(r"(<h[12][^>]*>.*?</h[12]>)", body, flags=re.S):
        if chunk.startswith("<h1"):
            chunk = re.sub(r"<h1([^>]*)>(.*?)</h1>", h1, chunk, flags=re.S)
        elif chunk.startswith("<h2"):
            chunk = re.sub(r"<h2([^>]*)>(.*?)</h2>", h2, chunk, flags=re.S)
        out.append(chunk)
    return "".join(out), entries


def toc_html(entries: list[dict], pages: dict[str, int] | None) -> str:
    rows = []
    for e in entries:
        pg = str(pages.get(e["mk"], "")) if pages else "000"
        cls = "toc-part" if e["level"] == 1 else "toc-sec"
        rows.append(f'<div class="{cls}"><span class="toc-num">{html.escape(e["label"])}</span>'
                    f'<span class="toc-title">{html.escape(html.unescape(e["title"]))}</span>'
                    f'<span class="toc-dots"></span><span class="toc-pg">{pg}</span></div>')
    return '<section class="toc"><h1 class="toc-head">Contents</h1>' + "".join(rows) + "</section>"


def page_html(body: str, book: dict, toc: str) -> str:
    css = (BUILD / "book.css").read_text(encoding="utf-8")
    font = lambda pkg, f: (FONTS / pkg / "files" / f).as_uri()  # noqa: E731
    fonts = "\n".join([
        f"@font-face{{font-family:'Plex';font-weight:{w};font-style:{s};src:url('{font('ibm-plex-sans', f'ibm-plex-sans-latin-{w}-{s}.woff2')}')}}"
        for w, s in [(400, "normal"), (500, "normal"), (600, "normal"), (700, "normal"), (400, "italic")]] + [
        f"@font-face{{font-family:'PlexMono';font-weight:{w};src:url('{font('ibm-plex-mono', f'ibm-plex-mono-latin-{w}-normal.woff2')}')}}"
        for w in (400, 600)])
    pyg = (BUILD / "pygments.css").read_text(encoding="utf-8")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<link rel="stylesheet" href="{(NM / 'katex/dist/katex.min.css').as_uri()}">
<style>{fonts}
{pyg}
{css}</style>
<script src="{(NM / 'katex/dist/katex.min.js').as_uri()}"></script>
<script src="{(NM / 'katex/dist/contrib/auto-render.min.js').as_uri()}"></script>
<script src="{(NM / 'mermaid/dist/mermaid.min.js').as_uri()}"></script>
</head><body>{toc}<main>{body}</main>
<script>
window.__errors = [];
mermaid.initialize({{startOnLoad:false, securityLevel:'loose', theme:'base',
  flowchart:{{htmlLabels:true, curve:'basis', useMaxWidth:true, padding:12, wrappingWidth:330}},
  sequence:{{useMaxWidth:true, mirrorActors:false}}, er:{{useMaxWidth:true}},
  themeVariables:{{fontFamily:'Plex, sans-serif', fontSize:'15px', primaryColor:'#eef1f8', primaryBorderColor:'#2c3d66',
    primaryTextColor:'#14213d', lineColor:'#2c3d66', secondaryColor:'#fdf0eb', tertiaryColor:'#f6f4ef',
    clusterBkg:'#faf9f6', clusterBorder:'#cfc9bb', noteBkgColor:'#fff6e0', noteBorderColor:'#d9b24c',
    actorBkg:'#eef1f8', actorBorder:'#2c3d66', signalColor:'#14213d', signalTextColor:'#14213d'}}}});
(async () => {{
  await Promise.all(['400 14px Plex','600 14px Plex','700 14px Plex','400 13px PlexMono'].map(f => document.fonts.load(f)));
  await document.fonts.ready;
  try {{ await mermaid.run({{querySelector:'.mermaid', suppressErrors:false}}); }}
  catch (e) {{ window.__errors.push('mermaid: ' + (e && e.message ? e.message : e)); }}
  document.querySelectorAll('.mermaid').forEach((el, i) => {{
    if (!el.querySelector('svg')) window.__errors.push('mermaid block ' + i + ' did not render');
    if (el.textContent.includes('Syntax error')) window.__errors.push('mermaid block ' + i + ' syntax error');
  }});
  renderMathInElement(document.body, {{delimiters:[{{left:'\\\\[',right:'\\\\]',display:true}},{{left:'\\\\(',right:'\\\\)',display:false}}],
    throwOnError:false, errorCallback:(m) => window.__errors.push('katex: ' + m)}});
  document.querySelectorAll('.katex-error').forEach(e => window.__errors.push('katex error: ' + e.textContent.slice(0,80)));
  await document.fonts.ready;
  window.__done = true;
}})();
</script></body></html>"""


def cover_html(book: dict, commit: str) -> str:
    css = (BUILD / "cover.css").read_text(encoding="utf-8")
    font = lambda pkg, f: (FONTS / pkg / "files" / f).as_uri()  # noqa: E731
    fonts = "\n".join(
        f"@font-face{{font-family:'Plex';font-weight:{w};src:url('{font('ibm-plex-sans', f'ibm-plex-sans-latin-{w}-normal.woff2')}')}}"
        for w in (400, 600, 700))
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{fonts}{css}</style></head><body>
<div class="cover">
  <div class="top"><svg width="64" height="64" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#1f2e52"/>
    <rect x="7" y="17" width="4" height="8" rx="1.5" fill="#8C93A8"/><rect x="14" y="12" width="4" height="13" rx="1.5" fill="#C9CCD6"/>
    <rect x="21" y="6" width="4" height="19" rx="1.5" fill="#E4572E"/></svg>
    <div class="brand">Talent<span>Signal</span></div></div>
  <div class="volume">{book['volume']}</div>
  <h1>{book['title']}</h1>
  <p class="tagline">{book['tagline']}</p>
  <div class="bars">{''.join(f'<i style="height:{h}%"></i>' for h in (18, 26, 22, 38, 31, 47, 42, 58, 52, 71, 64, 86))}</div>
  <div class="meta">
    <div><b>Subject</b>TalentSignal - explainable candidate intelligence and ranking platform</div>
    <div><b>Source of truth</b>the TalentSignal repository at commit {commit}</div>
    <div><b>Series</b>1 Technical Handbook · 2 Code Mastery Guide · 3 Interview &amp; Defense Bible</div>
  </div>
</div></body></html>"""


# --------------------------------------------------------------------------- browser
class Browser:
    def __init__(self) -> None:
        self.profile = tempfile.mkdtemp(prefix="ts-book-")
        self.proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}",
                                      f"--user-data-dir={self.profile}", "--allow-file-access-from-files",
                                      "--no-first-run", "about:blank"])
        for _ in range(100):
            try:
                tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json").read())
                page = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.2)
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=600, suppress_origin=True,
                                              max_size=None)
        self.i = 0
        self.call("Page.enable")

    def call(self, method: str, **params):
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.i:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr: str):
        return self.call("Runtime.evaluate", expression=expr, returnByValue=True).get("result", {}).get("value")

    def pdf(self, html_path: Path, *, header: str | None, wait_ready: bool, margins: tuple[float, float, float, float]) -> tuple[bytes, list]:
        self.call("Page.navigate", url=html_path.as_uri())
        t0 = time.time()
        while True:
            time.sleep(0.4)
            ready = self.js("document.readyState === 'complete' && (window.__done === true || !document.querySelector('main'))")
            if ready:
                break
            if time.time() - t0 > 240:
                raise TimeoutError(f"page not ready: {html_path}")
        errors = self.js("window.__errors || []") or []
        top, right, bottom, left = margins
        params = dict(printBackground=True, paperWidth=8.27, paperHeight=11.69, marginTop=top, marginBottom=bottom,
                      marginLeft=left, marginRight=right, preferCSSPageSize=False)
        if header:
            params.update(displayHeaderFooter=True, headerTemplate=header[0], footerTemplate=header[1])
        data = self.call("Page.printToPDF", **params)["data"]
        return base64.b64decode(data), errors

    def close(self) -> None:
        try:
            self.ws.close()
        finally:
            self.proc.terminate()


def header_footer(book: dict) -> tuple[str, str]:
    style = "font-family:Segoe UI,Arial,sans-serif;font-size:7.5px;color:#7b8191;width:100%;padding:0 14mm;"
    head = (f'<div style="{style}display:flex;justify-content:space-between;border-bottom:0.5px solid #e4e0d6;'
            f'padding-bottom:3px;margin-top:6mm"><span style="color:#14213d;font-weight:600">TalentSignal</span>'
            f'<span>{book["short"]}</span></div>')
    foot = (f'<div style="{style}display:flex;justify-content:space-between;margin-bottom:6mm">'
            f'<span>{book["volume"]}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')
    return head, foot


# --------------------------------------------------------------------------- checks
def check_code_blocks(text: str, label: str) -> list[str]:
    problems = []
    for m in re.finditer(r"```python[^\n]*\n(.*?)```", text, flags=re.S):
        code = m.group(1)
        if "# excerpt" in code.splitlines()[0] if code.strip() else False:
            continue
        try:
            compile(code, f"<{label}>", "exec")
        except SyntaxError as exc:
            problems.append(f"{label}: python syntax error line {exc.lineno}: {exc.msg} :: {code.splitlines()[0][:60]}")
            continue
        if code.lstrip().startswith("# runnable"):
            try:
                exec(compile(code, f"<{label}>", "exec"), {"__name__": "__book__"})
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{label}: runnable example failed: {type(exc).__name__}: {exc}")
    return problems


def check_excerpts(text: str, label: str) -> list[str]:
    """Blocks labelled '# excerpt from <fn> (<path>)' must appear verbatim (whitespace-normalised) in <path>."""
    problems = []
    norm = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731
    for fn, path, code in re.findall(r"```\w+\n# excerpt from (\w+) \(([^)]+)\)\n(.*?)```", text, re.S):
        p = ROOT / path
        if not p.exists() or norm(code) not in norm(p.read_text(encoding="utf-8")):
            problems.append(f"{label}: excerpt from {fn} ({path}) is not verbatim in the source")
    return problems


def check_tables(text: str, label: str) -> list[str]:
    """Every Markdown table row must have the same number of cells as its header row."""
    problems = []
    in_code = False
    header_cells = None
    for i, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if line.startswith("|"):
            cells = len(re.split(r"(?<!\\)\|", line.strip().strip("|")))
            if header_cells is None:
                header_cells = cells
            elif not re.match(r"^\|[\s:|-]+\|?$", line) and cells != header_cells:
                problems.append(f"{label}: table row has {cells} cells, header has {header_cells}: {line[:70]}")
        else:
            header_cells = None
    return problems


def find_pages(pdf: bytes) -> dict[str, int]:
    reader = PdfReader(io.BytesIO(pdf))
    pages = {}
    for i, page in enumerate(reader.pages, start=1):
        for mk in re.findall(r"QQMK\d{4}QQ", (page.extract_text() or "").replace(" ", "")):
            pages.setdefault(mk, i)
    return pages


def build_book(n: int, browser: Browser, commit: str, preview: bool) -> dict:
    book = BOOKS[n]
    files = sorted((SRC / book["src"]).glob("*.md"))
    text = "\n\n".join(f.read_text(encoding="utf-8") for f in files)
    text, includes = expand_includes(text)
    (LEARN / f"{book['file']}.md").write_text(
        f"<!-- Generated by docs/learning/build/build.py from docs/learning/src/{book['src']}/ - edit the chapter files there. -->\n\n"
        + text, encoding="utf-8")
    problems = check_code_blocks(text, book["file"]) + check_tables(text, book["file"]) + check_excerpts(text, book["file"])
    body, entries = number_headings(md_to_html(text))
    tmp = BUILD / "out"
    tmp.mkdir(exist_ok=True)
    hp = tmp / f"{book['file']}.html"
    hf = header_footer(book)
    margins = (0.85, 0.72, 0.8, 0.72)
    hp.write_text(page_html(body, book, toc_html(entries, None)), encoding="utf-8")
    pdf1, errors = browser.pdf(hp, header=hf, wait_ready=True, margins=margins)
    pages = find_pages(pdf1)
    hp.write_text(page_html(body, book, toc_html(entries, pages)), encoding="utf-8")
    pdf2, errors2 = browser.pdf(hp, header=hf, wait_ready=True, margins=margins)
    pages2 = find_pages(pdf2)
    if pages2 != pages:
        problems.append("TOC page numbers shifted between passes")
    missing = [e["title"] for e in entries if e["mk"] not in pages2]
    if missing:
        problems.append(f"headings not located in PDF: {missing[:5]}")
    cp = tmp / f"{book['file']}_cover.html"
    cp.write_text(cover_html(book, commit), encoding="utf-8")
    cover, _ = browser.pdf(cp, header=None, wait_ready=False, margins=(0, 0, 0, 0))

    writer = PdfWriter()
    for src in (cover, pdf2):
        for p in PdfReader(io.BytesIO(src)).pages:
            writer.add_page(p)
    writer.add_metadata({"/Title": f"TalentSignal - {html.unescape(book['title'])}", "/Author": "TalentSignal project",
                         "/Subject": html.unescape(book["tagline"])})
    parent = None
    for e in entries:
        pg = pages2.get(e["mk"])
        if pg is None:
            continue
        title = f"{e['label']}  {html.unescape(e['title'])}"
        if e["level"] == 1:
            parent = writer.add_outline_item(title, pg)  # +1 cover, -1 zero-based
        else:
            writer.add_outline_item(title, pg, parent=parent)
    out_pdf = LEARN / f"{book['file']}.pdf"
    with open(out_pdf, "wb") as f:
        writer.write(f)
    n_pages = len(writer.pages)
    words = len(re.findall(r"\w+", re.sub(r"```.*?```", "", text, flags=re.S)))
    if preview:
        render_preview(out_pdf, n)
    return {"book": book["file"], "pages": n_pages, "words_prose": words, "parts": sum(e["level"] == 1 for e in entries),
            "sections": sum(e["level"] == 2 for e in entries), "diagrams": text.count("```mermaid"), "code_includes": len(includes),
            "render_errors": errors + errors2, "problems": problems}


def render_preview(pdf_path: Path, n: int) -> None:
    import pypdfium2 as pdfium
    out = BUILD / "preview" / f"book{n}"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    doc = pdfium.PdfDocument(str(pdf_path))
    for i in range(len(doc)):
        doc[i].render(scale=0.9).to_pil().save(out / f"p{i + 1:03d}.png")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", nargs="*", type=int, default=[1, 2, 3])
    ap.add_argument("--preview", action="store_true")
    args = ap.parse_args()
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True).stdout.strip() or "unknown"
    browser = Browser()
    report = []
    try:
        for n in args.books:
            report.append(build_book(n, browser, commit, args.preview))
    finally:
        browser.close()
    print(json.dumps(report, indent=1))
    (BUILD / "build_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    if any(r["render_errors"] or r["problems"] for r in report):
        sys.exit(1)


if __name__ == "__main__":
    main()
