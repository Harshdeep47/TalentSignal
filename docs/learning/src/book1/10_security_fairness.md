# Security, Fairness and Responsible AI

Hiring software affects people's livelihoods and handles personal data. This part separates, clearly, the safeguards that **exist in the code** from **recommended improvements** that do not.

## Threats a candidate-ranking platform faces

| Threat | Example | Why it matters here |
|---|---|---|
| Malicious upload | a 2 GB file, a ZIP bomb, a file with a misleading extension | uploads are the main input |
| Path traversal | importing `../../secrets.txt` | the import-by-path feature reads server files |
| Cross-site scripting (XSS) | a candidate name `<script>…</script>` shown in the UI | candidate text is untrusted |
| Formula injection | a name `=HYPERLINK("http://evil")` exported to Excel | exports are opened in spreadsheets |
| SQL injection | an id `x' OR '1'='1` | the database stores runs and shortlists |
| Data exposure | one recruiter seeing another's shortlists | a hosted instance may have several users |
| Unfair ranking | penalising missing data, prestige or protected traits | the core ethical risk |

## Safeguards that exist

### Input validation and upload security

| Safeguard | Where | Detail |
|---|---|---|
| Extension allow-list | `DatasetService.save_upload` | `.jsonl .ndjson .txt .json .csv .xlsx .parquet` only; others → 415 |
| Size limit while streaming | `save_upload` | copies 4 MB chunks, aborts and deletes when over `TALENTSIGNAL_MAX_UPLOAD_MB` (default 2048) → 413 |
| Empty file rejected | `save_upload` | → 400 |
| Server-chosen file names | `save_upload` | stored as `<uuid>.<ext>`; the user's filename is only display text, cleaned by `safe_display_name` |
| Path imports restricted | `DatasetService.import_path` | path resolved with `resolve(strict=True)` and must lie inside an allow-listed directory (`is_relative_to`) → 403 otherwise |
| JD upload size | `upload_jd` route | 5 MB limit |
| DOCX zip-bomb guard | `engine/jd/documents.py` | declared uncompressed size of `word/document.xml` must be ≤ 20 MB |
| Record validation | `Normalizer` | types coerced, ranges clipped, control characters stripped, text length capped |
| Request validation | FastAPI + Pydantic | e.g. `page_size` 1-200, `order` must be asc/desc, `flags` from a fixed set, JD text 20-60,000 characters |
| Sort-column allow-list | `RunService.query` | sorting by an unknown column → 422 |

### Output safety

| Safeguard | Where | Detail |
|---|---|---|
| HTML escaping | React (frontend) | all text rendered as text; **no** `dangerouslySetInnerHTML` anywhere |
| PDF report escaping | `services/exports.py` | `xml.sax.saxutils.escape` before reportlab paragraphs |
| Formula-injection protection | `csv_safe` in `core/security.py` | text cells starting with `= + - @ TAB CR` are prefixed with `'` in CSV/XLSX |
| Security headers | `backend/app/main.py` | `Content-Security-Policy: default-src 'self' …`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` |
| Uniform errors | `core/errors.py` | expected errors return `{error: {code, message}}`; unexpected ones are logged with a stack trace and return a generic 500 without internals |

The API tests check several of these directly: oversized and empty uploads, disallowed extensions, path imports outside the allowed folder, formula-injection neutralisation in CSV exports, and the presence of security headers.

### Database safety

All SQL uses parameter placeholders (`?`), never string formatting with user input. Foreign keys with `ON DELETE CASCADE` keep runs and shortlists consistent when a dataset is deleted.

### Network isolation of ranking

The embedding model is loaded only from a local folder with Hugging Face offline mode forced on. In competition mode, `scripts/competition_rank.py` additionally replaces `socket.connect` with a function that raises an error during the ranking step, so any accidental network call fails loudly.

## Authentication and authorization - what exists and what does not

TalentSignal has **no user accounts and no authentication**. What it has is *session separation*: the browser creates a random UUID once (`crypto.randomUUID()`), stores it in `localStorage`, and sends it as `X-Session-Id`. Every dataset upload, run and shortlist is stored with that owner and only returned to the same session (`test_session_isolation`).

This separates history between people using different browsers, which is useful on a shared machine or a demo server. It is **not** security: anyone who learns a session id can act as that session, and anyone who can reach the server can create a new session. The README states plainly that the app must be placed behind real authentication before exposure to untrusted users.

!!! warning "Recommended improvement (not implemented)"
    Add authentication (for example OpenID Connect through an identity provider), map sessions to authenticated users and organisations, add role-based permissions (who may upload, who may delete), audit logging of who viewed which candidate, and HTTPS termination at a reverse proxy.

## Data privacy

| Practice | Status |
|---|---|
| Candidate data stays on the server; no external API receives it | **Exists** - no hosted AI services are called; the embedding model is local |
| Names are display-only, never features | **Exists** |
| Datasets uploaded by a session are visible only to that session | **Exists** |
| Deleting a dataset deletes its uploaded file, its runs and (if unused) its index | **Exists** (`DatasetService.delete`) |
| Logs do not contain candidate text | **Exists by convention** - errors log types and messages, not records |
| Encryption at rest, retention policies, right-to-erasure workflow, consent tracking | **Not implemented** - recommended for production |

## Bias and fairness in candidate ranking

Bias in ranking usually enters through three doors: **features** that encode protected traits or their proxies, **defaults** that punish missing data, and **feedback loops** that reward past visibility. The table lists what the code does about each.

| Concern | What TalentSignal does (verified in code) |
|---|---|
| Protected attributes (gender, age, ethnicity, religion) | The schema contains none; nothing is inferred; names are display-only |
| Prestige proxies | `education.tier` (institution prestige) is **never used**; field of study is displayed and filterable but not scored |
| Location as a proxy for nationality | Location is used only as the JD states it. The work-authorization condition fires only for candidates abroad who **explicitly** will not relocate - penalising everyone abroad would amount to inferring citizenship |
| Missing optional data | Missing values are neutral by construction; measured: removing assessments, GitHub and offer history changed strong profiles' scores by −0.007 on average |
| Closed-source careers | The "no external validation" condition defaults to *show only*, not penalise |
| Popularity feedback loops | Profile views and search appearances are not scored; "saved by recruiters" has only 5% of the engagement component |
| Career gaps | Not explicitly penalised. *However*, a stated experience larger than the sum of listed roles by more than 3 years triggers a critical integrity finding (held for review) - which can affect people with long unlisted gaps. This is a known limitation (Part 8, false positives) |
| Over-qualification | Decays more slowly than under-qualification, and can be adjusted by the recruiter |
| Transparency | Every component, weight, policy and source sentence is visible and editable |

!!! caution "Honest limits"
    Fairness was designed into the features, not *measured* across demographic groups - the data contains no demographic attributes, so group-level outcome audits (for example, selection rates by gender) were not possible. Hand-set parameters (affinity table, calibration windows) embody judgements that could disadvantage people whose careers do not fit the taxonomy's role families. One small non-neutral default exists: a missing "willing to relocate" is treated as not willing in the location sub-score.

## Explainability and human oversight as safeguards

Explainability is itself a fairness tool: a recruiter who can see that a candidate was penalised for a 90-day notice period can decide that it does not matter for this role. TalentSignal supports oversight by design:

- held candidates are kept and shown with reasons ("Held for review" tab);
- every declared condition can be switched to *show only*;
- critical integrity findings can be switched from *hold* to *flag*;
- every score decomposes into weighted components;
- the footer of every page states that scores are not hiring probabilities.

## Responsible use of AI in hiring

Guidelines that follow from everything above, for anyone deploying a system like this:

1. **Use it to prioritise reading, not to reject.** A ranking says whom to look at first.
2. **Review held candidates.** Integrity findings can be false positives.
3. **Check the extracted requirements** before ranking; the parser can mislabel (Part 5's Elasticsearch example).
4. **Do not treat the score as a probability**, and do not compare scores across different job descriptions.
5. **Collect feedback and audit outcomes** before trusting the system more.
6. **Comply with local law** on automated decision-making and candidate data (for example, rights to explanation and to human review); TalentSignal provides the explanations but no legal compliance workflow.

!!! note "Summary of Part 10"
    Existing: upload limits and allow-lists, safe paths, escaping, formula-injection protection, CSP and security headers, parameterised SQL, offline ranking, session separation, fairness-aware features, editable policies and human-review flows. Not existing: authentication, encryption at rest, retention and consent workflows, demographic fairness audits.
