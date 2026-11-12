"""Rule-based job-description understanding.

Turns free JD text into a :class:`JobSpec`. The approach is deliberately
transparent rather than clever:

1. Split the JD into sections and classify each heading (must-have,
   nice-to-have, exclusions, responsibilities, ideal profile, logistics,
   context). A requirement found under "Things you absolutely need" is
   mandatory; the same words under "Final note" are ignored.
2. Detect taxonomy concepts in each sentence via skill names and phrases.
3. Extract experience, location, notice and declared exclusions with
   targeted regular expressions.
4. Record, for every extracted item, the sentence that produced it, so the
   recruiter can verify the extraction in the review screen.

No network or LLM is required. The output is a starting point the recruiter
is expected to review and edit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from engine.jd.spec import (
    ConstraintSpec,
    ExperienceSpec,
    JobSpec,
    LocationSpec,
    NoticeSpec,
    Requirement,
)
from engine.taxonomy import Taxonomy, load_taxonomy

# Heading classification, checked in this order (first hit wins).
SECTION_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("exclusion", ("do not want", "don't want", "not want", "not a fit", "disqualif", "red flag", "deal breaker")),
    ("preferred", ("nice to have", "nice-to-have", "preferred", "bonus", "would like", "we'd like", "won't reject",
                   "good to have", "plus if")),
    ("mandatory", ("absolutely need", "must have", "must-have", "requirement", "required", "qualification",
                   "what we need", "you have", "minimum", "essential")),
    ("responsibilities", ("what you'd", "what you will", "what you'll", "responsibilit", "you will do",
                          "day to day", "day-to-day", "actually be doing", "the role")),
    ("ideal", ("ideal", "between the lines", "imagining", "who you are")),
    ("logistics", ("location", "logistics", "notice", "compensation", "comp,", "benefits")),
    ("context", ("note", "hackathon", "about us", "about the company", "culture", "vibe", "honest", "who we are",
                 "why join")),
]
HEADING_MAX_CHARS = 90

# Concepts that never become requirements by themselves (they describe
# non-target work and are handled by constraints when a JD excludes them).
NON_REQUIREMENT_CONCEPTS = {"business_functions"}

WEIGHT_MANDATORY = 1.0
WEIGHT_PREFERRED = 0.5
WEIGHT_MENTIONED = 0.35

DEFAULT_CITIES = (
    "pune", "noida", "hyderabad", "mumbai", "delhi", "new delhi", "gurgaon", "gurugram", "bangalore",
    "bengaluru", "chennai", "kolkata", "ahmedabad", "jaipur", "chandigarh", "indore", "kochi",
    "trivandrum", "coimbatore", "bhubaneswar", "vizag", "london", "berlin", "singapore", "dubai",
    "toronto", "sydney", "new york", "san francisco", "seattle",
)
COUNTRY_WORDS = {
    "india": "India", "indian": "India", "usa": "USA", "united states": "USA", "uk": "UK",
    "united kingdom": "UK", "germany": "Germany", "canada": "Canada", "singapore": "Singapore",
    "australia": "Australia", "uae": "UAE",
}

CONSTRAINT_RULES: list[tuple[str, str, str, float, re.Pattern]] = [
    ("consulting_only", "Career spent only at IT-services / consulting firms", "penalize", 0.5,
     re.compile(r"consulting firms?|it[- ]services firms?|only worked at (tcs|infosys|wipro|accenture)", re.I)),
    ("research_only", "Pure research career without production deployment", "penalize", 0.5,
     re.compile(r"pure research|research[- ]only|academic labs?", re.I)),
    ("non_coding_lead", "Senior lead/architect who no longer writes code", "penalize", 0.65,
     re.compile(r"(hasn't|has not|haven't|not) written production code|moved into .{0,20}(architecture|tech lead)", re.I)),
    ("title_chasing", "Frequent job switching while climbing titles", "penalize", 0.75,
     re.compile(r"title[- ]chas|switching companies every|job[- ]hopp", re.I)),
    ("cv_speech_only", "Computer vision / speech focus without NLP or IR", "penalize", 0.6,
     re.compile(r"computer vision, speech|vision, speech,? or robotics|cv,? speech", re.I)),
    ("llm_wrapper_only", "AI experience limited to recent LLM-API wrappers", "penalize", 0.75,
     re.compile(r"langchain to call openai|call(ing)? openai|llm wrappers?", re.I)),
    ("closed_source_only", "No external validation of work (open source, talks, papers)", "ignore", 0.9,
     re.compile(r"closed[- ]source|external validation", re.I)),
]
VISA_NO_SPONSOR = re.compile(r"(don't|do not|does not|doesn't|no|not able to|cannot|can't)\s+(\w+\s+)?sponsor\w*"
                             r"|no\s+visa\s+sponsorship", re.I)


@dataclass
class Section:
    kind: str
    heading: str
    lines: list[str]


def _clean_line(line: str) -> str:
    line = line.strip()
    # Strip bullets ("-", "*", "•") and list numbering ("1.", "2)") but not
    # numbers that are content, e.g. "6-8 years total experience".
    line = re.sub(r"^(?:[#>*•●▪\-]+\s*|\d{1,2}[.)]\s+)+", "", line)
    return line.strip()


def _classify_heading(text: str) -> str | None:
    t = text.lower()
    for kind, keys in SECTION_RULES:
        if any(k in t for k in keys):
            return kind
    return None


def _is_heading(raw: str, cleaned: str) -> bool:
    if not cleaned or len(cleaned) > HEADING_MAX_CHARS:
        return False
    if raw.lstrip().startswith("#"):
        return True
    if cleaned.endswith(":"):
        return True
    if re.match(r"^[A-Za-z][\w /&-]{1,30}:\s+\S", cleaned):
        return False  # "Key: value" metadata line, e.g. "Experience Required: 5-9 years"
    # Short line without sentence punctuation is treated as a heading.
    return not re.search(r"[.!?;,]$", cleaned) and len(cleaned.split()) <= 12 and cleaned[0].isupper()


def split_sections(text: str) -> list[Section]:
    sections: list[Section] = [Section("general", "", [])]
    for raw in text.splitlines():
        cleaned = _clean_line(raw)
        if not cleaned:
            continue
        if _is_heading(raw, cleaned):
            kind = _classify_heading(cleaned)
            if kind is not None:
                sections.append(Section(kind, cleaned.rstrip(":"), []))
                continue
        sections[-1].lines.append(cleaned)
    return [s for s in sections if s.lines or s.heading]


def _sentences(line: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", line)
    return [p.strip() for p in parts if p.strip()]


def _term_regex(term: str) -> re.Pattern:
    escaped = re.escape(term.lower())
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")


class _ConceptMatcher:
    def __init__(self, tax: Taxonomy):
        self.patterns: dict[str, list[re.Pattern]] = {}
        for c in tax.concepts.values():
            terms = {s.lower() for s in c.skills} | set(c.phrases)
            self.patterns[c.id] = [_term_regex(t) for t in sorted(terms) if len(t) >= 2]

    def find(self, sentence: str) -> list[str]:
        s = sentence.lower()
        return [cid for cid, pats in self.patterns.items() if any(p.search(s) for p in pats)]


def _extract_title(text: str, tax: Taxonomy) -> str:
    m = re.search(r"(?im)^\s*(?:job\s+description|job\s+title|title|role|position)\s*[:\-—]\s*(.+)$", text)
    if m:
        return m.group(1).strip()
    for raw in text.splitlines():
        cleaned = _clean_line(raw)
        if cleaned and len(cleaned) <= 100:
            return cleaned
    return "Untitled role"


def _extract_experience(sections: list[Section]) -> ExperienceSpec:
    spec = ExperienceSpec()
    range_re = re.compile(r"(\d{1,2}(?:\.\d)?)\s*(?:[–—\-]|to)\s*(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years|yrs)", re.I)
    plus_re = re.compile(r"(\d{1,2})\s*\+\s*(?:years|yrs)", re.I)
    of_which_re = re.compile(r"of which\s+(\d{1,2})(?:\s*[–\-]\s*(\d{1,2}))?", re.I)
    for sec in sections:
        for line in sec.lines + [sec.heading]:
            for sent in _sentences(line):
                m = range_re.search(sent)
                if m and spec.min_years is None and sec.kind != "ideal":
                    spec.min_years, spec.max_years = float(m.group(1)), float(m.group(2))
                    spec.source_text = sent[:240]
                    if re.search(r"\b(minimum|at least|strictly|must)\b", sent, re.I):
                        spec.hard_min = True
                elif m and sec.kind == "ideal" and spec.ideal_min is None:
                    spec.ideal_min, spec.ideal_max = float(m.group(1)), float(m.group(2))
                if spec.min_years is None:
                    p = plus_re.search(sent)
                    if p:
                        spec.min_years = float(p.group(1))
                        spec.source_text = sent[:240]
                w = of_which_re.search(sent)
                if w and spec.relevant_min_years is None:
                    spec.relevant_min_years = float(w.group(1))
    if spec.ideal_min is None and spec.min_years is not None:
        spec.ideal_min = spec.min_years
        spec.ideal_max = spec.max_years
    return spec


def _find_cities(sentence: str, cities: tuple[str, ...]) -> list[str]:
    s = sentence.lower()
    found = []
    for c in sorted(cities, key=len, reverse=True):
        if _term_regex(c).search(s) and not any(c in f for f in found):
            found.append(c)
    return found


def _extract_location(text: str, sections: list[Section], cities: tuple[str, ...]) -> LocationSpec:
    loc = LocationSpec()
    lines = [ln for s in sections for ln in s.lines + [s.heading]]
    loc_line = next((ln for ln in lines if re.match(r"(?i)location\s*:", ln)), None)
    if loc_line:
        loc.source_text = loc_line[:240]
        head = loc_line.split("|")[0]
        loc.preferred = _find_cities(head.split("(")[0], cities)
        lower = loc_line.lower()
        for mode in ("hybrid", "remote", "onsite", "on-site"):
            if mode in lower:
                loc.work_mode = "onsite" if mode == "on-site" else mode  # type: ignore[assignment]
                break
        loc.relocation_considered = "relocat" in lower or loc.relocation_considered
    for ln in lines:
        low = ln.lower()
        for sent in _sentences(ln):
            sl = sent.lower()
            if "welcome" in sl or "open to" in sl or "also consider" in sl:
                for c in _find_cities(sent, cities):
                    if c not in loc.preferred and c not in loc.acceptable:
                        loc.acceptable.append(c)
            if ("prefer" in sl) and not loc.preferred:
                loc.preferred = _find_cities(sent, cities)
        if VISA_NO_SPONSOR.search(ln) and "visa" in low:
            loc.visa_sponsorship = False
    for word, country in COUNTRY_WORDS.items():
        if loc_line and _term_regex(word).search(loc_line.lower()) and country not in loc.countries:
            loc.countries.append(country)
    if not loc.countries and re.search(r"\b(india|indian)\b", text, re.I) and (loc.preferred or loc.acceptable):
        loc.countries.append("India")
    return loc


def _extract_notice(text: str) -> NoticeSpec:
    spec = NoticeSpec()
    m = re.search(r"sub[- ](\d{1,3})[- ]day", text, re.I) or re.search(
        r"(?:notice(?: period)?\s*(?:of|under|below|<=?|within)?\s*)(\d{1,3})\s*days", text, re.I)
    if m:
        spec.ideal_max_days = int(m.group(1))
        spec.source_text = text[max(0, m.start() - 60): m.end() + 80].replace("\n", " ").strip()
        b = re.search(r"buy\s*out\s*(?:up to\s*)?(\d{1,3})\s*days", text, re.I)
        spec.acceptable_max_days = spec.ideal_max_days + int(b.group(1)) if b else spec.ideal_max_days * 2
    return spec


def _concept_requirement(cid: str, tax: Taxonomy, importance: str, weight: float, source: str) -> Requirement:
    c = tax.concepts[cid]
    return Requirement(
        id=cid, label=c.label, concept_id=cid, skills=list(c.skills), phrases=list(c.phrases),
        semantic=c.semantic, signal=c.signal, importance=importance,  # type: ignore[arg-type]
        weight=weight, source_text=source[:240],
    )


def parse_job_description(text: str, known_locations: list[str] | None = None,
                          taxonomy: Taxonomy | None = None) -> JobSpec:
    """Parse JD text into an editable :class:`JobSpec`.

    ``known_locations`` (e.g. distinct city names from the active dataset)
    extends the built-in city list so location requirements can be matched
    against real candidate locations.
    """
    tax = taxonomy or load_taxonomy()
    text = text.replace("\r\n", "\n")
    sections = split_sections(text)
    matcher = _ConceptMatcher(tax)
    notes: list[str] = []

    cities = set(DEFAULT_CITIES) | set(tax.location_groups.keys())
    for loc in known_locations or []:
        cities.add(loc.split(",")[0].strip().lower())

    title = _extract_title(text, tax)
    found: dict[str, tuple[str, float, str]] = {}  # cid -> (importance, weight, source)
    rank = {"mandatory": 3, "preferred": 2, "mentioned": 1}
    for sec in sections:
        if sec.kind in ("context", "exclusion", "logistics"):
            continue
        level = {"mandatory": "mandatory", "preferred": "preferred"}.get(sec.kind, "mentioned")
        for line in sec.lines:
            for sent in _sentences(line):
                for cid in matcher.find(sent):
                    if cid in NON_REQUIREMENT_CONCEPTS and level != "mandatory":
                        continue
                    prev = found.get(cid)
                    if prev is None or rank[level] > rank[prev[0]]:
                        found[cid] = (level, 0.0, sent)

    requirements: list[Requirement] = []
    for cid, (level, _, source) in found.items():
        if level == "mandatory":
            requirements.append(_concept_requirement(cid, tax, "mandatory", WEIGHT_MANDATORY, source))
        elif level == "preferred":
            requirements.append(_concept_requirement(cid, tax, "preferred", WEIGHT_PREFERRED, source))
        else:
            requirements.append(_concept_requirement(cid, tax, "preferred", WEIGHT_MENTIONED, source))
    requirements.sort(key=lambda r: (r.importance != "mandatory", -r.weight, r.label))
    if not requirements:
        notes.append("No known skills or capabilities were recognised; add requirements manually.")
    if not any(r.importance == "mandatory" for r in requirements) and requirements:
        notes.append("No explicit must-have section was found; all requirements were marked preferred.")

    constraints: list[ConstraintSpec] = []
    for cid, label, policy, factor, pattern in CONSTRAINT_RULES:
        m = pattern.search(text)
        if m:
            start = text.rfind("\n", 0, m.start()) + 1
            end = text.find("\n", m.end())
            src = text[start: end if end != -1 else len(text)].strip()
            constraints.append(ConstraintSpec(id=cid, label=label, policy=policy,  # type: ignore[arg-type]
                                              factor=factor, source_text=src[:240]))

    location = _extract_location(text, sections, tuple(sorted(cities)))
    if location.visa_sponsorship is False:
        constraints.append(ConstraintSpec(
            id="work_authorization", label="Outside the hiring country (no visa sponsorship)",
            policy="penalize", factor=0.5, source_text="JD states that work visas are not sponsored."))

    experience = _extract_experience(sections)
    notice = _extract_notice(text)

    family = tax.family_of(title)
    families: dict[str, float] = {family: 1.0} if family != "non_technical" else {}
    mandatory_ids = {r.id for r in requirements if r.importance == "mandatory"}
    if mandatory_ids & {"ranking_recsys", "information_retrieval", "embeddings_retrieval", "vector_search_infra"}:
        families["search_ranking"] = 1.0
    if not families:
        notes.append(f"Job title '{title}' did not match a technical role family; title relevance uses "
                     "keyword overlap only. Set target role families manually if needed.")

    responsibilities = [ln for s in sections if s.kind == "responsibilities" for ln in s.lines][:10]
    mandatory_text = " ".join(r.semantic or r.label for r in requirements if r.importance == "mandatory")
    focus = " ".join([title] + responsibilities[:6] + [mandatory_text]).strip()

    return JobSpec(
        title=title,
        seniority_level=tax.seniority_of(title),
        role_families=families,
        responsibilities=responsibilities,
        requirements=requirements,
        experience=experience,
        location=location,
        notice=notice,
        constraints=constraints,
        focus_text=focus[:4000],
        raw_text=text,
        extraction_notes=notes,
    )
