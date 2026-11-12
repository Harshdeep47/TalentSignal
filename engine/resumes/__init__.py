"""Resume (CV) ingestion: safe text extraction, rule-based parsing with provenance,
and mapping into the existing TalentSignal candidate schema.

    extract.py  PDF / DOCX -> ExtractedDocument (lines with page and line numbers)
    zipsafe.py  safe iteration over ZIP archives of resumes
    parse.py    ExtractedDocument -> extraction (facts: stated / inferred / missing,
                each with its source location) -> candidate record

The result is an ordinary candidate record, so ranking uses the existing
engine unchanged. Nothing here calls a network service or executes content
embedded in documents.
"""
