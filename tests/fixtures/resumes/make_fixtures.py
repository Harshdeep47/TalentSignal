"""Generate the sample resume fixtures used by the ingestion tests.

All people, companies and contact details below are fictional.

    python tests/fixtures/resumes/make_fixtures.py [out_dir]

Writes (default: this directory):
  asha_verma.pdf         two-page text PDF: full sections, current role, certifications
  rohan_mehta.docx       DOCX: no skills section (skills must be *inferred*), macro part present
  priya_nair_dup.pdf     byte-identical copy of asha_verma.pdf (duplicate detection)
  scanned.pdf            image-only PDF (no text layer -> OCR not supported)
  encrypted.pdf          password-protected PDF
  corrupted.pdf          truncated/garbled PDF bytes
  not_a_resume.txt       unsupported format
"""
from __future__ import annotations

import io
import shutil
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ASHA_PAGES = [
    [
        "Asha Verma",
        "Senior Machine Learning Engineer",
        "Bengaluru, Karnataka, India",
        "asha.verma@example.com | +91 98765 43210 | linkedin.com/in/asha-verma-example",
        "Date of Birth: 01/01/1990",
        "Summary",
        "Machine learning engineer with 7 years of experience building search and ranking systems.",
        "Shipped retrieval models to production serving 20 million queries per day.",
        "Experience",
        "Senior Machine Learning Engineer | Nimbus Retail Labs",
        "Jan 2021 - Present",
        "- Built a hybrid BM25 and embedding retrieval service in Python on Kubernetes.",
        "- Led A/B tests for ranking changes; improved NDCG by 6%.",
        "Machine Learning Engineer, Copperleaf Analytics",
        "Jul 2017 - Dec 2020",
        "- Trained gradient boosted ranking models with PyTorch and scikit-learn.",
        "- Owned the feature pipeline on Apache Spark and Airflow.",
    ],
    [
        "Education",
        "M.Tech in Computer Science",
        "Indian Institute of Technology Madras, 2015 - 2017",
        "CGPA: 8.9/10",
        "B.Tech in Information Technology",
        "National Institute of Technology Trichy, 2011 - 2015",
        "Skills",
        "Languages: Python, SQL, Java",
        "ML: PyTorch (Expert), scikit-learn, Learning to Rank, NLP",
        "Infrastructure: Kubernetes, Docker, Apache Spark, Airflow, AWS",
        "Certifications",
        "AWS Certified Machine Learning - Specialty, Amazon Web Services, 2022",
        "Projects",
        "Open-source query understanding toolkit",
        "- Tokenisation and spelling correction for product search.",
        "Achievements",
        "- Best Paper Award, Indian Retrieval Workshop 2019",
    ],
]

ROHAN_PARAS = [
    "Rohan Mehta",
    "Backend Developer",
    "Pune, India",
    "rohan.mehta@example.org",
    "Gender: Male",
    "Profile",
    "Backend developer who builds REST APIs and data services.",
    "Work Experience",
    "Software Engineer at Orbit Fintech",
    "03/2022 - 05/2024",
    "Developed payment APIs in Go and PostgreSQL; added Redis caching.",
    "Associate Software Engineer at Tealbyte Systems",
    "2020 - 2022",
    "Maintained Django services and wrote integration tests.",
    "Education",
    "B.E. Computer Engineering",
    "Savitribai Phule Pune University, 2016 - 2020",
]


def make_pdf(pages: list[list[str]], password: str | None = None) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1, encrypt=password)
    c.setTitle("Resume")
    for page in pages:
        y = 800
        for line in page:
            c.setFont("Helvetica-Bold" if line == page[0] else "Helvetica", 10)
            c.drawString(50, y, line)
            y -= 18
        c.showPage()
    c.save()
    return buf.getvalue()


def make_scanned_pdf() -> bytes:
    """A page that contains only a raster image (simulates a scan; no text layer)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    from PIL import Image, ImageDraw

    img = Image.new("L", (600, 300), 255)
    d = ImageDraw.Draw(img)
    for i, line in enumerate(ASHA_PAGES[0][:6]):
        d.text((20, 20 + 30 * i), line, fill=0)
    ib = io.BytesIO()
    img.save(ib, format="PNG")
    ib.seek(0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    c.drawImage(ImageReader(ib), 40, 450, width=500, height=250)
    c.showPage()
    c.save()
    return buf.getvalue()


def make_docx(paragraphs: list[str], with_macro: bool = False) -> bytes:
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{escape(p)}</w:t></w:r></w:p>' for p in paragraphs)
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f"<w:body>{body}</w:body></w:document>")
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/'
                     'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in (("[Content_Types].xml", content_types), ("_rels/.rels", rels),
                           ("word/document.xml", document)):
            info = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
            z.writestr(info, data, zipfile.ZIP_DEFLATED)
        if with_macro:
            info = zipfile.ZipInfo("word/vbaProject.bin", date_time=(2024, 1, 1, 0, 0, 0))
            z.writestr(info, b"\x00fake-macro-bytes-never-executed")
    return buf.getvalue()


def write_all(out: Path) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "asha_verma.pdf": make_pdf(ASHA_PAGES),
        "rohan_mehta.docx": make_docx(ROHAN_PARAS, with_macro=True),
        "scanned.pdf": make_scanned_pdf(),
        "encrypted.pdf": make_pdf(ASHA_PAGES, password="secret"),
        "not_a_resume.txt": b"This is a plain text file, not a resume document.\n",
    }
    good = files["asha_verma.pdf"]
    files["corrupted.pdf"] = good[:400] + b"\x00garbage" * 50
    paths = {}
    for name, data in files.items():
        p = out / name
        p.write_bytes(data)
        paths[name] = p
    shutil.copyfile(paths["asha_verma.pdf"], out / "priya_nair_dup.pdf")
    paths["priya_nair_dup.pdf"] = out / "priya_nair_dup.pdf"
    return paths


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    for n, p in write_all(target).items():
        print(f"{n:22s} {p.stat().st_size:>7,d} bytes")
