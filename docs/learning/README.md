# TalentSignal learning books

Three books that take a reader from no knowledge of the project to defending it in a technical interview.

| # | Book | PDF | Pages | Read it to … |
|---|---|---|---|---|
| 1 | Complete Project & Technical Handbook | `01_TalentSignal_Complete_Technical_Handbook.pdf` | 66 | understand the problem, the architecture, the data, job understanding, the ranking mathematics, a full worked example, explanations, performance, security and fairness |
| 2 | Developer's Implementation & Code Mastery Guide | `02_TalentSignal_Developer_Code_Mastery_Guide.pdf` | 68 | read the real code: every directory, module, endpoint and table; important functions explained; testing, deployment, exercises with solutions |
| 3 | Interview Preparation & Technical Defense Bible | `03_TalentSignal_Interview_and_Technical_Defense_Bible.pdf` | 42 | explain and defend the project: talk tracks, architecture defence, ML/NLP questions, math and coding problems, hard questions, mock interviews, resume material, checklist |

## Recommended study order

1. **Book 1, Parts 1-3** (problem, architecture, programming foundations) - skip Part 3 if you already program.
2. **Book 1, Parts 4-8** - the core: data, job understanding, the ranking engine, the worked example, explanations. Re-derive the worked example's numbers yourself.
3. **Book 2, Parts 1-3** with the repository open; then run the tests (Part 9) and try Exercises 1.x and 2.x.
4. **Book 1, Parts 9-11** - performance, responsibility, the end-to-end walkthrough.
5. **Book 2, Parts 4-8** - frontend, database, API, important code, decisions.
6. **Book 3** in order; practise the talk tracks aloud and do the math and coding problems on paper first. Finish with the mock interviews and the checklist.

## How the books fit together

Book 1 explains *what and why* (concepts and formulas, with code references). Book 2 explains *where and how* (the actual source - its excerpts are inserted from the repository at build time, so they cannot drift from the code). Book 3 trains *explaining, calculating and defending*, and cross-references the other two instead of repeating them. Terminology is shared through Book 1's glossary (Appendix A).

## What "verified" means in these books

- Code excerpts in Book 2 are extracted from the source files by function or class name when the PDF is built; hand-quoted excerpts are checked to appear verbatim in the cited file.
- The worked ranking example (Book 1, Part 7) is produced by running the real engine (`build/worked_example.py`, `build/worked_whatif.py`; outputs in `build/*.json`).
- Every Python block marked `# runnable` is executed with its assertions during the build; all other Python blocks are compiled.
- Measured numbers come from `README.md`, `docs/reports/EVALUATION_REPORT.md`, index `meta.json` files and the scripts in `scripts/`.
- Features that do not exist are labelled as proposals (e.g. authentication, résumé ingestion at the time of writing, scaling beyond 100,000 candidates).

## Editing and rebuilding

The editable sources are the chapter files in `src/book1/`, `src/book2/`, `src/book3/`. The combined Markdown files next to the PDFs (`01_…md`, `02_…md`, `03_…md`) are generated from them, with code excerpts expanded.

The build uses an isolated toolchain that does not touch the application's dependencies:

```bash
# one-time
python -m venv .tools/docs-venv
.tools/docs-venv/Scripts/python -m pip install markdown==3.7 pymdown-extensions==10.12 pygments==2.18.0 \
    pypdf==5.1.0 pypdfium2==4.30.0 pillow websocket-client==1.9.0 numpy
cd docs/learning/build && npm install          # Mermaid 11.4.1 and KaTeX 0.16.11, rendered offline
# build (requires Microsoft Edge for headless printing; frontend/node_modules for the bundled fonts)
.tools/docs-venv/Scripts/python docs/learning/build/build.py [--books 1 2 3] [--preview]
```

The build prints a report per book (pages, sections, diagrams, code includes) and fails if a diagram or formula does not render, a code block does not compile, a runnable example fails, a table row has the wrong number of cells, a quoted excerpt is not verbatim, or a heading cannot be located for the table of contents. `--preview` renders every page to `build/preview/` for visual review.
