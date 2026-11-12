"""Rule-based resume parsing with provenance.

Input: an ``ExtractedDocument`` (lines with page and line numbers).
Output: an *extraction* - a dictionary of **facts**. Every fact has

    {"value": ..., "status": "stated" | "inferred" | "missing",
     "source": {"page": int | None, "line": int, "text": "..."} | None,
     "note": "how it was derived" | None}

* **stated**   - the value is text that appears in the document (the source
                  line is recorded);
* **inferred** - the value was derived by a documented rule from stated text
                  (e.g. role duration from its dates, country from a city);
* **missing**  - nothing usable was found. Missing values are never filled
                  with guesses: no proficiency levels, durations of skill use,
                  platform signals or qualifications are invented.

``to_candidate_record`` maps an extraction onto the existing candidate schema
so the unchanged ranking engine can score it. Contact details (email, phone,
profile links) are kept in the extraction for the recruiter but are **not**
copied into the candidate record, so they never reach the ranking index or
exports.

The parser is deterministic and offline. It handles common resume layouts;
unusual layouts produce missing facts and warnings, which is why every
profile is reviewed before it joins a ranking pool.
"""
from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from typing import Any

from engine.jd.parser import DEFAULT_CITIES
from engine.resumes.extract import REDACTED, ExtractedDocument
from engine.taxonomy import load_taxonomy

PARSER_VERSION = 1

SECTION_ALIASES: dict[str, str] = {}
for key, names in {
    "summary": ["summary", "profile", "professional summary", "about me", "about", "objective", "career objective",
                "profile summary", "career summary", "professional profile"],
    "experience": ["experience", "work experience", "professional experience", "employment history", "employment",
                   "work history", "career history", "relevant experience", "industry experience"],
    "education": ["education", "academic background", "academics", "qualifications", "educational qualifications",
                  "academic qualifications", "education and training"],
    "skills": ["skills", "technical skills", "key skills", "core competencies", "skills and tools", "skills & tools",
               "technologies", "tech stack", "tools and technologies", "technical expertise", "competencies"],
    "projects": ["projects", "key projects", "personal projects", "academic projects", "selected projects"],
    "certifications": ["certifications", "certificates", "licenses and certifications", "licenses & certifications",
                       "certifications and training", "courses"],
    "achievements": ["achievements", "awards", "honors", "honours", "accomplishments", "awards and achievements",
                     "awards & achievements", "publications"],
    "contact": ["contact", "contact information", "contact details", "personal details", "personal information"],
    "languages": ["languages", "spoken languages"],
    "interests": ["interests", "hobbies", "hobbies and interests"],
}.items():
    for n in names:
        SECTION_ALIASES[n] = key

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
MONTH_RE = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_RE = rf"(?:{MONTH_RE}\s*[,']?\s*(?:19|20)\d{{2}}|(?:0?[1-9]|1[0-2])\s*[/.\-]\s*(?:19|20)\d{{2}}|(?:19|20)\d{{2}})"
PRESENT_RE = r"(?:present|current|currently|now|till\s+date|to\s+date|ongoing|today)"
RANGE = re.compile(rf"(?P<start>{DATE_RE})\s*(?:-|–|—|to|till|until)\s*(?P<end>{DATE_RE}|{PRESENT_RE})", re.I)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?:\+?\d[\d\s().-]{8,}\d)")
LINKEDIN = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/[\w/\-%.]+", re.I)
GITHUB = re.compile(r"(?:https?://)?github\.com/[\w\-.]+", re.I)
STATED_YEARS = re.compile(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years|yrs)\b(?:\s+of)?(?:\s+\w+){0,3}?\s+experience", re.I)
BULLET = re.compile(r"^\s*(?:[-*•·▪●◦‣]|\d{1,2}[.)])\s+")
ROLE_WORDS = re.compile(
    r"\b(engineer|developer|scientist|analyst|manager|consultant|architect|lead|intern|designer|specialist|"
    r"administrator|executive|officer|director|head|researcher|programmer|associate|trainee|tester|sde|founder|"
    r"cto|ceo|vp|president|technician|coordinator|representative|writer|accountant|professor|lecturer|"
    r"fellow|staff|principal)\b", re.I)
DEGREE = re.compile(
    r"\b(ph\.?\s?d\.?|doctorate|m\.?\s?tech|b\.?\s?tech|m\.?\s?sc|b\.?\s?sc|msc|bsc|mca|bca|mba|bba|"
    r"m\.\s?s\.?|b\.\s?s\.?|m\.\s?e\.?|b\.\s?e\.?|m\.\s?a\.?|b\.\s?a\.?|bachelor(?:'s)?(?:\s+of\s+[a-z]+)?|"
    r"master(?:'s)?(?:\s+of\s+[a-z]+)?|diploma|associate degree)(?![a-z])", re.I)
INSTITUTION = re.compile(r"\b(university|institute|college|school|iit|nit|iiit|academy|polytechnic|universit)", re.I)
GRADE = re.compile(r"\b(?:cgpa|gpa|grade|percentage)\s*[:\-]?\s*([\d.]+\s*(?:/\s*[\d.]+|%)?)|\b(\d{2}(?:\.\d+)?\s*%)", re.I)
PROFICIENCY = ("beginner", "intermediate", "advanced", "expert")
ISSUERS = ["Amazon Web Services", "AWS", "Google Cloud", "Google", "Microsoft", "Coursera", "DeepLearning.AI",
           "Oracle", "IBM", "Meta", "Databricks", "NVIDIA", "Udemy", "edX", "Stanford", "Cisco", "Salesforce"]
COUNTRY_WORDS = {"india": "India", "usa": "USA", "united states": "USA", "uk": "UK", "united kingdom": "UK",
                 "germany": "Germany", "canada": "Canada", "singapore": "Singapore", "australia": "Australia",
                 "uae": "UAE", "united arab emirates": "UAE"}
CITY_COUNTRY = {"london": "UK", "berlin": "Germany", "singapore": "Singapore", "dubai": "UAE", "toronto": "Canada",
                "sydney": "Australia", "new york": "USA", "san francisco": "USA", "seattle": "USA"}


# --------------------------------------------------------------------------- helpers
def fact(value: Any, status: str, src: dict | None = None, note: str | None = None) -> dict:
    return {"value": value, "status": status, "source": src, "note": note}


def missing(note: str | None = None) -> dict:
    return fact(None, "missing", None, note)


def source(line: tuple[int | None, int, str]) -> dict:
    page, no, text = line
    return {"page": page, "line": no, "text": text[:240]}


def strip_bullet(text: str) -> str:
    return BULLET.sub("", text).strip()


def heading_key(text: str) -> str | None:
    if len(text) > 48:
        return None
    t = re.sub(r"[^a-z& ]", " ", text.lower())
    t = re.sub(r"\s+", " ", t).strip()
    return SECTION_ALIASES.get(t)


def parse_date(text: str, is_end: bool) -> tuple[int, int, bool]:
    """(year, month, month_was_stated) for one date token."""
    t = text.strip().lower()
    m = re.match(rf"({MONTH_RE})\s*[,']?\s*((?:19|20)\d{{2}})", t)
    if m:
        return int(m.group(2)), MONTHS[m.group(1)[:3]], True
    m = re.match(r"(0?[1-9]|1[0-2])\s*[/.\-]\s*((?:19|20)\d{2})", t)
    if m:
        return int(m.group(2)), int(m.group(1)), True
    y = int(YEAR.search(t).group(0))
    return y, (12 if is_end else 1), False


def months_between(start: tuple[int, int], end: tuple[int, int]) -> int:
    return max(0, (end[0] - start[0]) * 12 + (end[1] - start[1]) + 1)


@lru_cache(maxsize=1)
def _skill_vocab() -> dict[str, str]:
    tax = load_taxonomy()
    return {s.lower(): s for c in tax.concepts.values() for s in c.skills}


@lru_cache(maxsize=1)
def _skill_patterns() -> list[tuple[str, re.Pattern]]:
    """Patterns for skill mentions in free text. Names of 3 characters or fewer
    ("Go", "SQL") are matched case-sensitively so that ordinary words such as
    "go" are not mistaken for skills."""
    out = []
    for low, canon in sorted(_skill_vocab().items(), key=lambda kv: -len(kv[0])):
        if len(low) < 2:
            continue
        if len(low) <= 3:
            out.append((canon, re.compile(rf"(?<![A-Za-z0-9]){re.escape(canon)}(?![A-Za-z0-9])")))
        else:
            out.append((canon, re.compile(rf"(?<![a-z0-9]){re.escape(low)}(?![a-z0-9])", re.I)))
    return out


def _find_city(text: str) -> tuple[str, str | None] | None:
    low = text.lower()
    for city in sorted(DEFAULT_CITIES, key=len, reverse=True):
        m = re.search(rf"(?<![a-z]){re.escape(city)}(?![a-z])", low)
        if m:
            tail = re.match(r"\s*,\s*([A-Za-z][A-Za-z .]{1,30})", text[m.end():])
            label = text[m.start():m.end()].strip().title()
            region = tail.group(1).strip() if tail else None
            return city, (f"{label}, {region}" if region else label)
    return None


def _split_pieces(text: str) -> list[str]:
    parts = re.split(r"\s+(?:at|@)\s+|\s*[|•·]\s*|\s+[–—-]\s+|,\s+|\s{3,}", text)
    return [p.strip(" ,;:()-–—|") for p in parts if p and p.strip(" ,;:()-–—|")]


# --------------------------------------------------------------------------- sections
def split_sections(lines: list[tuple[int | None, int, str]]) -> dict[str, list[tuple[int | None, int, str]]]:
    sections: dict[str, list] = {"header": []}
    current = "header"
    for ln in lines:
        key = heading_key(ln[2])
        if key:
            current = key
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(ln)
    return sections


# --------------------------------------------------------------------------- field parsers
def parse_contact(lines) -> dict:
    out: dict[str, list] = {"emails": [], "phones": [], "links": []}
    seen = set()
    for ln in lines:
        text = ln[2]
        for m in EMAIL.findall(text):
            if m.lower() not in seen:
                seen.add(m.lower())
                out["emails"].append(fact(m, "stated", source(ln)))
        for m in LINKEDIN.findall(text) + GITHUB.findall(text):
            if m.lower() not in seen:
                seen.add(m.lower())
                out["links"].append(fact(m, "stated", source(ln)))
        if not EMAIL.search(text) or len(text) < 80:
            for m in PHONE.findall(text):
                digits = re.sub(r"\D", "", m)
                if 10 <= len(digits) <= 15 and not YEAR.fullmatch(digits[:4] + "") and digits not in seen:
                    if RANGE.search(m):
                        continue
                    seen.add(digits)
                    out["phones"].append(fact(m.strip(), "stated", source(ln)))
    return out


def _looks_like_name(text: str) -> bool:
    if any(ch.isdigit() for ch in text) or "@" in text or heading_key(text) or ROLE_WORDS.search(text):
        return False
    words = text.replace(",", " ").split()
    if not 2 <= len(words) <= 4:
        return False
    return all(re.fullmatch(r"[A-Z][A-Za-z'.-]*|[A-Z]{2,}", w) for w in words)


def parse_identity(header, all_lines) -> dict:
    pool = header[:8] if header else all_lines[:6]
    name = missing("No line in the resume header looked like a person's name.")
    name_i = -1
    for i, ln in enumerate(pool):
        if _looks_like_name(ln[2]):
            name = fact(ln[2].strip(), "stated", source(ln))
            name_i = i
            break
    headline = missing()
    for ln in pool[name_i + 1:]:
        t = ln[2]
        if EMAIL.search(t) or LINKEDIN.search(t) or GITHUB.search(t) or len(re.sub(r"\D", "", t)) >= 10:
            continue
        if _find_city(t) and len(t) < 40:
            continue
        if 3 <= len(t) <= 140 and re.search(r"[A-Za-z]{3}", t) and not heading_key(t):
            headline = fact(t, "stated", source(ln))
            break
    location, country = missing(), missing()
    for ln in pool:
        hit = _find_city(ln[2])
        if hit:
            city, label = hit
            location = fact(label, "stated", source(ln))
            low = ln[2].lower()
            stated_country = next((v for k, v in COUNTRY_WORDS.items() if re.search(rf"\b{k}\b", low)), None)
            if stated_country:
                country = fact(stated_country, "stated", source(ln))
            else:
                country = fact(CITY_COUNTRY.get(city, "India"), "inferred", source(ln),
                               f"Country inferred from the city '{city.title()}'.")
            break
    return {"name": name, "headline": headline, "location": location, "country": country}


def parse_experience(lines, today: date) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    date_idx = [i for i, ln in enumerate(lines) if RANGE.search(ln[2])]
    if lines and not date_idx:
        warnings.append("An experience section was found but no date ranges were recognised; roles need review.")
        return [], warnings
    headers: dict[int, list[int]] = {}
    for k, idx in enumerate(date_idx):
        prev = date_idx[k - 1] if k else -1
        take = []
        j = idx - 1
        while j > prev and len(take) < 2:
            t = lines[j][2]
            if BULLET.match(t) or len(t) > 100 or t.endswith("."):
                break
            take.insert(0, j)
            j -= 1
        headers[idx] = take
    roles = []
    for k, idx in enumerate(date_idx):
        ln = lines[idx]
        m = RANGE.search(ln[2])
        rest = (ln[2][:m.start()] + "  " + ln[2][m.end():]).strip(" |,()-–—")
        pieces, piece_src = [], []
        for h in headers[idx]:
            for p in _split_pieces(lines[h][2]):
                pieces.append(p)
                piece_src.append(lines[h])
        for p in _split_pieces(rest):
            pieces.append(p)
            piece_src.append(ln)
        pieces_nl = [(p, s) for p, s in zip(pieces, piece_src) if not (_find_city(p) and len(p) < 35)]
        title_i = next((i for i, (p, _) in enumerate(pieces_nl) if ROLE_WORDS.search(p)), None)
        note = None
        if title_i is None and pieces_nl:
            title_i = 0
            note = "No role word found; the first part of the role heading was taken as the title."
        title = fact(pieces_nl[title_i][0], "stated", source(pieces_nl[title_i][1]), note) if title_i is not None \
            else missing("No job title found for this role.")
        comp = next(((p, s) for i, (p, s) in enumerate(pieces_nl) if i != title_i), None)
        company = fact(comp[0], "stated", source(comp[1])) if comp else missing("No company name found for this role.")
        sy, sm, s_stated = parse_date(m.group("start"), is_end=False)
        end_txt = m.group("end")
        current = bool(re.fullmatch(PRESENT_RE, end_txt.strip(), re.I))
        if current:
            ey, em, e_stated = today.year, today.month, True
        else:
            ey, em, e_stated = parse_date(end_txt, is_end=True)
        dnote = None if (s_stated and e_stated) else "Month not stated; January (start) / December (end) assumed."
        next_start = (min(headers[date_idx[k + 1]] or [date_idx[k + 1]]) if k + 1 < len(date_idx) else len(lines))
        desc_lines = lines[idx + 1: next_start]
        desc = " ".join(strip_bullet(d[2]) for d in desc_lines if d[2] != REDACTED)
        roles.append({
            "title": title,
            "company": company,
            "start_date": fact(f"{sy:04d}-{sm:02d}-01", "stated" if s_stated else "inferred", source(ln), dnote),
            "end_date": fact(None if current else f"{ey:04d}-{em:02d}-01",
                             "stated" if (current or e_stated) else "inferred", source(ln), dnote),
            "is_current": fact(current, "stated", source(ln)),
            "duration_months": fact(months_between((sy, sm), (ey, em)), "inferred", source(ln),
                                    "Computed from the role's start and end dates (inclusive months)."),
            "description": fact(desc[:6000], "stated", source(desc_lines[0])) if desc else missing(),
        })
    return roles, warnings


def parse_education(lines) -> list[dict]:
    entries: list[list] = []
    for ln in lines:
        if DEGREE.search(ln[2]) or not entries:
            entries.append([ln])
        elif len(entries[-1]) < 3:
            entries[-1].append(ln)
    out = []
    for group in entries:
        deg_ln = next((ln for ln in group if DEGREE.search(ln[2])), None)
        if deg_ln is None:
            continue
        dm = DEGREE.search(deg_ln[2])
        degree = fact(dm.group(0).strip(), "stated", source(deg_ln))
        after = deg_ln[2][dm.end():]
        fm = re.match(r"\s*(?:\(|in|of|,|-|–|:)?\s*(?:in\s+)?([A-Z][A-Za-z&/ .]+?)(?=\s*(?:[,|()\-–]|\bfrom\b|\bat\b|$|\d))",
                      after)
        field_v = None
        if fm and not INSTITUTION.search(fm.group(1)):
            field_v = fm.group(1).strip()
        field = fact(field_v, "stated", source(deg_ln)) if field_v else missing("Field of study not stated.")
        inst_ln = next((ln for ln in group if INSTITUTION.search(ln[2])), None)
        if inst_ln:
            piece = next((p for p in _split_pieces(inst_ln[2]) if INSTITUTION.search(p)), inst_ln[2])
            piece = YEAR.sub("", piece).strip(" ,-–()")
            institution = fact(piece, "stated", source(inst_ln))
        else:
            institution = missing("Institution not found.")
        years = sorted({int(y) for ln in group for y in YEAR.findall(ln[2])})
        year_src = next((ln for ln in group if YEAR.search(ln[2])), None)
        start = fact(years[0], "stated", source(year_src)) if len(years) >= 2 else missing()
        end = fact(years[-1], "stated", source(year_src)) if years else missing()
        gm = next(((GRADE.search(ln[2]), ln) for ln in group if GRADE.search(ln[2])), None)
        grade = fact((gm[0].group(1) or gm[0].group(2)).strip(), "stated", source(gm[1])) if gm else missing()
        out.append({"degree": degree, "field_of_study": field, "institution": institution,
                    "start_year": start, "end_year": end, "grade": grade})
    return out


def parse_skills(lines, full_lines) -> tuple[list[dict], list[str]]:
    vocab = _skill_vocab()
    warnings: list[str] = []
    skills: list[dict] = []
    seen: set[str] = set()
    for ln in lines:
        text = strip_bullet(ln[2])
        line_prof = None
        lm = re.match(r"^\s*(beginner|intermediate|advanced|expert)\s*[:\-]\s*", text, re.I)
        if lm:
            line_prof = lm.group(1).lower()
            text = text[lm.end():]
        elif ":" in text and len(text.split(":")[0]) < 40:
            text = text.split(":", 1)[1]
        for tok in re.split(r"[,;|•·]|\s{2,}", text):
            tok = tok.strip(" .-–")
            prof = line_prof
            pm = re.search(r"\((beginner|intermediate|advanced|expert)\)", tok, re.I)
            if pm:
                prof = pm.group(1).lower()
                tok = (tok[:pm.start()] + tok[pm.end():]).strip()
            tok = re.sub(r"\(.*?\)", "", tok).strip()
            if not (2 <= len(tok) <= 40) or not re.search(r"[A-Za-z]", tok) or len(tok.split()) > 5:
                continue
            canon = vocab.get(tok.lower(), tok)
            if canon.lower() in seen:
                continue
            seen.add(canon.lower())
            note = None if canon == tok else f"Normalised from '{tok}'."
            skills.append({"name": fact(canon, "stated", source(ln), note),
                           "proficiency": fact(prof, "stated", source(ln)) if prof else
                           missing("Proficiency not stated - not assumed.")})
    if not lines:
        body = [ln for ln in full_lines if ln[2] != REDACTED]
        text = "\n".join(ln[2] for ln in body)
        for canon, pat in _skill_patterns():
            m = pat.search(text)
            if m and canon.lower() not in seen:
                seen.add(canon.lower())
                src_ln = next((ln for ln in body if pat.search(ln[2])), None)
                skills.append({"name": fact(canon, "inferred", source(src_ln) if src_ln else None,
                                            "No skills section; skill name found in the resume text."),
                               "proficiency": missing("Proficiency not stated - not assumed.")})
        if skills:
            warnings.append("No skills section was found; skills were taken from mentions in the text.")
    if not skills:
        warnings.append("No skills were found.")
    return skills, warnings


def parse_certifications(lines) -> list[dict]:
    out = []
    for ln in lines:
        text = strip_bullet(ln[2])
        if len(text) < 4:
            continue
        ym = YEAR.search(text)
        issuer = next((i for i in ISSUERS if re.search(rf"(?<![A-Za-z]){re.escape(i)}(?![A-Za-z])", text)), None)
        name = YEAR.sub("", text).strip(" ,-–()|")
        if issuer:
            name = re.sub(rf"\s*[,|(–-]\s*{re.escape(issuer)}\)?\s*$", "", name).strip(" ,-–()|") or name
        out.append({"name": fact(name, "stated", source(ln)),
                    "issuer": fact(issuer, "stated", source(ln)) if issuer else missing(),
                    "year": fact(int(ym.group(0)), "stated", source(ln)) if ym else missing()})
    return out


def parse_blocks(lines) -> list[dict]:
    """Projects: a non-bullet line starts a block, bullets/continuations describe it."""
    blocks: list[dict] = []
    for ln in lines:
        if ln[2] == REDACTED:
            continue
        if not BULLET.match(ln[2]) or not blocks:
            blocks.append({"title": fact(strip_bullet(ln[2]), "stated", source(ln)), "details": []})
        else:
            blocks[-1]["details"].append(fact(strip_bullet(ln[2]), "stated", source(ln)))
    return blocks


def _merged_months(roles: list[dict]) -> int:
    spans = []
    for r in roles:
        s = r["start_date"]["value"]
        e = r["end_date"]["value"]
        sy, sm = int(s[:4]), int(s[5:7])
        if e is None:
            d = date.today()
            ey, em = d.year, d.month
        else:
            ey, em = int(e[:4]), int(e[5:7])
        spans.append((sy * 12 + sm, ey * 12 + em))
    spans.sort()
    total, cur = 0, None
    for a, b in spans:
        if cur is None or a > cur[1]:
            if cur:
                total += cur[1] - cur[0] + 1
            cur = [a, b]
        else:
            cur[1] = max(cur[1], b)
    if cur:
        total += cur[1] - cur[0] + 1
    return total


# --------------------------------------------------------------------------- main entry points
def parse_resume(doc: ExtractedDocument, today: date | None = None) -> dict:
    today = today or date.today()
    lines = doc.lines()
    sec = split_sections(lines)
    header = sec.get("header", [])
    warnings = list(doc.warnings)

    identity = parse_identity(header, lines)
    contact = parse_contact(header + sec.get("contact", []) + lines[:12])
    summary_lines = [ln for ln in sec.get("summary", []) if ln[2] != REDACTED]
    summary = fact(" ".join(ln[2] for ln in summary_lines)[:3000], "stated", source(summary_lines[0])) \
        if summary_lines else missing("No summary section.")
    roles, w = parse_experience(sec.get("experience", []), today)
    warnings += w
    education = parse_education(sec.get("education", []))
    skills, w = parse_skills(sec.get("skills", []), lines)
    warnings += w
    certifications = parse_certifications(sec.get("certifications", []))
    projects = parse_blocks(sec.get("projects", []))
    achievements = [fact(strip_bullet(ln[2]), "stated", source(ln))
                    for ln in sec.get("achievements", []) if ln[2] != REDACTED]

    computed = round(_merged_months(roles) / 12, 1) if roles else None
    stated_ln = next(((STATED_YEARS.search(ln[2]), ln) for ln in summary_lines + header if STATED_YEARS.search(ln[2])),
                     None)
    if stated_ln:
        years = fact(float(stated_ln[0].group(1)), "stated", source(stated_ln[1]))
        if computed is not None and abs(years["value"] - computed) > 3:
            warnings.append(f"Stated experience ({years['value']:g} years) differs from the listed roles "
                            f"({computed:g} years) by more than 3 years; ranking will flag this as an "
                            "integrity finding unless corrected.")
    elif computed is not None:
        years = fact(computed, "inferred", None, "Sum of listed role durations (overlaps counted once).")
    else:
        years = missing("No experience duration could be determined.")

    if identity["name"]["status"] == "missing":
        warnings.append("No candidate name was recognised.")
    if not roles and "experience" not in sec:
        warnings.append("No experience section was found.")
    current = next((r for r in roles if r["is_current"]["value"]), roles[0] if roles else None)
    return {
        "parser_version": PARSER_VERSION,
        "document": {"kind": doc.kind, "pages": doc.n_pages, "redacted_lines": doc.redacted_lines},
        "identity": identity,
        "contact": contact,
        "summary": summary,
        "years_of_experience": years,
        "current_title": current["title"] if current else missing(),
        "current_company": current["company"] if current else missing(),
        "experience": roles,
        "education": education,
        "skills": skills,
        "certifications": certifications,
        "projects": projects,
        "achievements": achievements,
        "sections_found": [k for k in sec if k != "header"],
        "warnings": warnings,
        "text_pages": doc.pages,
    }


def to_candidate_record(ex: dict, candidate_id: str, fallback_name: str) -> dict:
    """Map an extraction onto the candidate schema (values only; no contact details)."""
    v = lambda f: f["value"] if f else None  # noqa: E731
    parts = [v(ex["summary"]) or ""]
    if ex["projects"]:
        parts.append("Projects: " + " ".join(
            v(p["title"]) + (": " + " ".join(v(d) for d in p["details"]) if p["details"] else "") + "."
            for p in ex["projects"]))
    if ex["achievements"]:
        parts.append("Achievements: " + "; ".join(v(a) for a in ex["achievements"]) + ".")
    roles = [{
        "company": v(r["company"]) or "", "title": v(r["title"]) or "",
        "start_date": v(r["start_date"]), "end_date": v(r["end_date"]),
        "duration_months": v(r["duration_months"]), "is_current": bool(v(r["is_current"])),
        "industry": "", "company_size": None, "description": v(r["description"]) or "",
    } for r in ex["experience"]]
    title = v(ex["current_title"]) or ""
    return {
        "candidate_id": candidate_id,
        "profile": {
            "anonymized_name": v(ex["identity"]["name"]) or fallback_name,
            "headline": v(ex["identity"]["headline"]) or title,
            "summary": " ".join(p for p in parts if p).strip()[:6000],
            "location": v(ex["identity"]["location"]) or "",
            "country": v(ex["identity"]["country"]) or "",
            "years_of_experience": v(ex["years_of_experience"]),
            "current_title": title,
            "current_company": v(ex["current_company"]) or "",
            "current_company_size": None,
            "current_industry": "",
        },
        "career_history": roles,
        "education": [{
            "institution": v(e["institution"]) or "", "degree": v(e["degree"]) or "",
            "field_of_study": v(e["field_of_study"]) or "", "start_year": v(e["start_year"]),
            "end_year": v(e["end_year"]), "grade": v(e["grade"]), "tier": None,
        } for e in ex["education"]],
        "skills": [{"name": v(s["name"]), "proficiency": v(s["proficiency"]), "endorsements": None,
                    "duration_months": None} for s in ex["skills"]],
        "certifications": [{"name": v(c["name"]), "issuer": v(c["issuer"]) or "", "year": v(c["year"])}
                           for c in ex["certifications"]],
        "languages": [],
        "redrob_signals": {},
    }
