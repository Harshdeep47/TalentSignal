"""Run the full evaluation suite and write docs/reports/EVALUATION_REPORT.md.

    python scripts/run_evaluation.py [--index DIR] [--quick]

All relevance metrics use PROXY labels (engine/evaluation/proxy_labels.py);
they are not ground truth. Every number in the report is produced by this
script on this machine; nothing is typed in by hand.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.evaluation.adversarial import build_adversarial_file  # noqa: E402
from engine.evaluation.metrics import evaluate_ranking, kendall_tau_topk, overlap  # noqa: E402
from engine.evaluation.proxy_labels import proxy_labels  # noqa: E402
from engine.explanations.explain import explain_candidate  # noqa: E402
from engine.explanations.validator import validate_text  # noqa: E402
from engine.ingestion.fingerprint import file_fingerprint  # noqa: E402
from engine.jd.documents import extract_text  # noqa: E402
from engine.jd.parser import parse_job_description  # noqa: E402
from engine.preprocessing.index import build_index  # noqa: E402
from engine.preprocessing.store import DatasetIndex  # noqa: E402
from engine.ranking.scorer import COMPONENTS, ScoringOptions, score_pool  # noqa: E402
from engine.taxonomy import load_taxonomy  # noqa: E402
from scripts._mem import PeakMemory  # noqa: E402

REF = ROOT.parent / "reference material"
# The evaluation measures the Redrob challenge task, so it uses the challenge JD from the local
# challenge materials (not redistributed in this repository).
JD_PATH = ROOT.parent / "reference material" / "job_description.docx"
REPORT_MD = ROOT / "docs" / "reports" / "EVALUATION_REPORT.md"
REPORT_JSON = ROOT / "docs" / "reports" / "evaluation_results.json"
PLAIN_PREFIXES = ("Built systems that understand", "Shipped the personalization", "Designed the ranking layer",
                  "Owned the search and discovery")



def _jd_text() -> str:
    from engine.jd.documents import extract_text
    if not JD_PATH.is_file():
        sys.exit(f"Challenge JD not found: {JD_PATH} (job_description.docx from the Redrob challenge materials).")
    return extract_text(JD_PATH.name, JD_PATH.read_bytes())

def _top_ids(pool, k=100) -> list[str]:
    return pool.shortlist(k)["candidate_id"].tolist()


def _diagnostics(ix, ids: list[str], labels: pd.Series) -> dict:
    cand = ix.candidates.set_index("candidate_id")
    tax = load_taxonomy()
    crit = set(ix.candidates.loc[ix.integrity.loc[ix.integrity.severity == "critical", "idx"], "candidate_id"])
    titles = cand.loc[ids, "title"]
    return {
        "critical_integrity_in_top100": int(sum(c in crit for c in ids)),
        "non_technical_titles_in_top100": int(sum(tax.family_of(t) == "non_technical" for t in titles)),
        "outside_india_in_top100": int((cand.loc[ids, "country"] != "India").sum()),
        "mean_proxy_label_top100": round(float(labels.reindex(ids).fillna(0).mean()), 3),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=Path, default=None)
    ap.add_argument("--quick", action="store_true", help="Skip the adversarial index build")
    args = ap.parse_args()
    candidates_file = REF / "candidates.jsonl"
    index_dir = args.index or ROOT / "artifacts" / "indexes" / file_fingerprint(candidates_file)
    ix = DatasetIndex(index_dir)
    spec = parse_job_description(_jd_text(),
                                 known_locations=ix.candidates["location"].unique().tolist())
    labels = proxy_labels(ix)
    lab = labels.to_dict()
    results: dict = {"index": ix.meta, "proxy_label_distribution": labels.value_counts().sort_index().to_dict()}

    # ---- systems --------------------------------------------------------------
    pool = score_pool(ix, spec)
    systems: dict[str, list[str]] = {"TalentSignal (full)": _top_ids(pool)}
    ref_csv = REF / "redrob-hackathon" / "submission.csv"
    if ref_csv.exists():
        systems["Reference implementation (committed top-100)"] = pd.read_csv(ref_csv)["candidate_id"].tolist()
    bm25_only = score_pool(ix, spec, ScoringOptions(disabled_components=frozenset(set(COMPONENTS) - {"lexical"}),
                                                    use_constraints=False, use_integrity=False))
    systems["BM25 only (lexical baseline)"] = _top_ids(bm25_only)
    # Naive keyword baseline: number of JD skills listed (the trap the JD warns about)
    jd_skills = {s.lower() for r in spec.requirements for s in r.skills}
    sk = ix.skills
    counts = sk[sk["skill"].str.lower().isin(jd_skills)].groupby("idx").size()
    order = ix.candidates.assign(k=counts.reindex(ix.candidates["idx"]).fillna(0).to_numpy()) \
        .sort_values(["k", "candidate_id"], ascending=[False, True])
    systems["Keyword count (JD skills listed)"] = order["candidate_id"].head(100).tolist()
    results["systems"] = {name: {**evaluate_ranking(ids, lab), **_diagnostics(ix, ids, labels)}
                          for name, ids in systems.items()}
    if "Reference implementation (committed top-100)" in systems:
        results["overlap_with_reference_top100"] = round(overlap(systems["TalentSignal (full)"],
                                                                 systems["Reference implementation (committed top-100)"]), 3)

    # plain-language profiles (JD "Tier 5") positions
    texts = ix.texts["text"]
    plain_tids = [i for i, t in texts.items() if t.startswith(PLAIN_PREFIXES)]
    roles = ix.roles
    plain_idx = roles.loc[roles["text_id"].isin(plain_tids) & (roles["order"] == 0), "idx"].unique()
    plain_ids = set(ix.candidates.loc[plain_idx, "candidate_id"])
    rank_of = dict(zip(pool.table["candidate_id"], pool.table["rank"]))
    results["plain_language_profiles"] = {
        "count": len(plain_ids),
        "ranks": sorted(int(rank_of[c]) for c in plain_ids),
    }

    # ---- ablations --------------------------------------------------------------
    ablations = {
        "full system": ScoringOptions(),
        "- requirements component": ScoringOptions(disabled_components=frozenset({"requirements"})),
        "- role fit component": ScoringOptions(disabled_components=frozenset({"role_fit"})),
        "- semantic component": ScoringOptions(disabled_components=frozenset({"semantic"})),
        "- lexical (BM25) component": ScoringOptions(disabled_components=frozenset({"lexical"})),
        "- experience component": ScoringOptions(disabled_components=frozenset({"experience"})),
        "- engagement (behavioural) component": ScoringOptions(disabled_components=frozenset({"engagement"})),
        "- logistics component": ScoringOptions(disabled_components=frozenset({"logistics"})),
        "- assessments in skill evidence": ScoringOptions(use_assessments=False),
        "- career-text evidence": ScoringOptions(use_text_evidence=False),
        "- skill-list evidence": ScoringOptions(use_skill_evidence=False),
        "- title trust / skill credibility": ScoringOptions(use_title_trust=False),
        "- constraint policies": ScoringOptions(use_constraints=False),
        "- integrity gate": ScoringOptions(use_integrity=False),
    }
    abl = {}
    for name, opt in ablations.items():
        p = score_pool(ix, spec, opt)
        ids = _top_ids(p)
        abl[name] = {**evaluate_ranking(ids, lab), **_diagnostics(ix, ids, labels),
                     "overlap_with_full": round(overlap(ids, systems["TalentSignal (full)"]), 3)}
    results["ablations"] = abl

    # ---- stability under weight perturbation -------------------------------------
    rnd = random.Random(11)
    base_ids = systems["TalentSignal (full)"]
    stab = []
    for _ in range(10):
        s2 = spec.model_copy(deep=True)
        for k in s2.weights.model_fields:
            setattr(s2.weights, k, getattr(s2.weights, k) * rnd.uniform(0.8, 1.2))
        ids = _top_ids(score_pool(ix, s2))
        stab.append((overlap(ids, base_ids), overlap(ids[:10], base_ids[:10]), kendall_tau_topk(base_ids[:50], ids)))
    stab = np.array(stab)
    results["stability_weight_perturbation_20pct"] = {
        "trials": len(stab), "mean_overlap_top100": round(float(stab[:, 0].mean()), 3),
        "min_overlap_top100": round(float(stab[:, 0].min()), 3),
        "mean_overlap_top10": round(float(stab[:, 1].mean()), 3),
        "mean_kendall_tau_top50": round(float(stab[:, 2].mean()), 3),
    }

    # ---- look-alike differentiation -----------------------------------------------
    cand = ix.candidates
    key = cand["headline"] + "|" + cand["summary_tid"].astype(str) + "|" + cand["title"] + "|" + \
        cand["years_experience"].round().astype(str)
    t = pool.table.merge(cand[["idx"]].assign(key=key), on="idx")
    groups = t.groupby("key")
    multi = groups.filter(lambda g: len(g) > 1)
    distinct = multi.groupby("key")["overall"].agg(lambda s: s.round(4).nunique() == len(s))
    top500 = t[(t["rank"] > 0) & (t["rank"] <= 500)]
    results["lookalikes"] = {
        "candidates_in_lookalike_groups": int(len(multi)),
        "groups": int(multi["key"].nunique()),
        "groups_with_all_distinct_scores": round(float(distinct.mean()), 4),
        "top500_candidates_in_lookalike_groups": int(top500["key"].isin(multi["key"]).sum()),
        "mean_within_group_score_std": round(float(multi.groupby("key")["overall"].std().mean()), 4),
    }

    # ---- evidence accuracy & reasoning variation --------------------------------
    t0 = time.perf_counter()
    sample = base_ids + random.Random(3).sample(pool.table["candidate_id"].tolist(), 100)
    unsupported, summaries, dropped = 0, [], 0
    for cid in sample:
        e = explain_candidate(ix, pool, spec, cid)
        rec = e["record"]
        unsupported += len(validate_text(e["summary_claims"], rec))  # remarks name missing JD items
        summaries.append(e["summary"])
    expl_ms = (time.perf_counter() - t0) * 1000 / len(sample)
    results["explanations"] = {
        "explained": len(sample),
        "unsupported_skill_mentions": unsupported,
        "distinct_summaries_top100": len(set(summaries[:100])),
        "mean_explain_ms": round(expl_ms, 1),
    }

    # ---- latency & memory ------------------------------------------------------
    times = []
    with PeakMemory() as mem:
        for _ in range(3):
            t1 = time.perf_counter()
            score_pool(ix, spec)
            times.append(time.perf_counter() - t1)
    results["latency"] = {"warm_score_100k_s": [round(x, 2) for x in times],
                          "warm_score_mean_s": round(float(np.mean(times)), 2),
                          "process_peak_rss_mb": mem.peak_mb}

    # ---- adversarial synthetic set ------------------------------------------------
    if not args.quick:
        strong = [c for c in base_ids[:40]]
        weak = pool.table.sample(400, random_state=5)["candidate_id"].tolist()
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "adversarial.jsonl"
            groups_ = build_adversarial_file(ix, strong, weak, spec, f)
            build_index(f, Path(td) / "ix")
            aix = DatasetIndex(Path(td) / "ix")
            ap_ = score_pool(aix, spec)
            tt = ap_.table.set_index("candidate_id")
            def ranks(ids): return [int(tt.loc[c, "rank"]) for c in ids]
            stuffer_ranks = ranks(groups_["stuffer"])
            base_strong_scores = tt.loc[strong[:30], "overall"].to_numpy()
            sparse_scores = tt.loc[groups_["sparse"], "overall"].to_numpy()
            twin_scores = tt.loc[groups_["twin"], "overall"].to_numpy()
            n_strong = len(strong)
            results["adversarial"] = {
                "pool_size": aix.n,
                "stuffers": len(stuffer_ranks),
                "best_stuffer_rank": min(r for r in stuffer_ranks if r > 0) if any(stuffer_ranks) else None,
                "stuffers_in_top_n_strong": int(sum(0 < r <= n_strong for r in stuffer_ranks)),
                "n_strong_real_profiles": n_strong,
                "impossible_profiles_eligible": int(tt.loc[groups_["impossible"], "eligible"].sum()),
                "sparse_vs_original_mean_score_delta": round(float((sparse_scores - base_strong_scores).mean()), 4),
                "sparse_vs_original_max_score_drop": round(float((base_strong_scores - sparse_scores).max()), 4),
                "twin_vs_original_mean_score_delta": round(float((twin_scores - base_strong_scores).mean()), 4),
                "twins_ranked_below_original": int(sum(tt.loc[groups_["twin"][k], "overall"] < tt.loc[strong[k], "overall"]
                                                       for k in range(30))),
            }

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    REPORT_MD.write_text(render_report(results), encoding="utf-8")
    print(f"Wrote {REPORT_MD} and {REPORT_JSON}")


def _table(rows: dict, cols: list[str]) -> str:
    head = "| System | " + " | ".join(cols) + " |\n|---|" + "---|" * len(cols) + "\n"
    body = ""
    for name, r in rows.items():
        body += f"| {name} | " + " | ".join(str(r.get(c, "")) for c in cols) + " |\n"
    return head + body


def render_report(r: dict) -> str:
    cols = ["composite", "ndcg@10", "ndcg@50", "map@100", "p@10", "critical_integrity_in_top100",
            "non_technical_titles_in_top100", "outside_india_in_top100", "mean_proxy_label_top100"]
    md = ["# TalentSignal - Evaluation Report", "",
          "> **All relevance metrics below use PROXY labels**, not ground truth. The hidden competition labels",
          "> were never available. Proxy labels are hand-assigned grades of the 44 role-description templates",
          "> (`engine/evaluation/resources/proxy_description_grades.yaml`) adjusted by conditions the JD states",
          "> explicitly (see `engine/evaluation/proxy_labels.py`). The scorer never reads these labels, but it does",
          "> read the same descriptions, so agreement is partly built in. Use these numbers to compare variants",
          "> and catch regressions, not as a claim of real-world accuracy.", "",
          f"Generated by `scripts/run_evaluation.py` on index `{r['index']['source_fingerprint']}` "
          f"({r['index']['n_candidates']:,} candidates, embedding model `{r['index'].get('embedding_model')}`).", "",
          "## Proxy label distribution", "",
          "| Label | Candidates |", "|---|---|"]
    md += [f"| {k} | {v:,} |" for k, v in r["proxy_label_distribution"].items()]
    md += ["", "## Systems compared (top-100 lists)", "", _table(r["systems"], cols)]
    if "overlap_with_reference_top100" in r:
        md.append(f"Overlap between TalentSignal's top 100 and the reference implementation's committed top 100: "
                  f"**{r['overlap_with_reference_top100']:.0%}**.\n")
    pl = r["plain_language_profiles"]
    md += ["## Plain-language profiles", "",
           f"{pl['count']} candidates whose current role describes search/ranking work without AI keywords "
           f"(the JD's 'Tier 5' example). Their ranks: {pl['ranks']}.", "",
           "## Ablations", "", "Each row removes one part of the system; everything else unchanged.", "",
           _table(r["ablations"], cols + ["overlap_with_full"]),
           "## Stability", "", "Ten trials, each component weight multiplied by a random factor in [0.8, 1.2]:", "",
           "```", json.dumps(r["stability_weight_perturbation_20pct"], indent=1), "```", "",
           "## Look-alike candidates", "",
           "Candidates sharing headline, summary, title and rounded years of experience:", "",
           "```", json.dumps(r["lookalikes"], indent=1), "```", "",
           "## Explanations", "",
           "```", json.dumps(r["explanations"], indent=1), "```", "",
           "## Latency and memory (scoring 100K candidates, warm)", "",
           "```", json.dumps(r["latency"], indent=1), "```", ""]
    if "adversarial" in r:
        md += ["## Adversarial synthetic set", "",
               "Real strong and random profiles plus synthetic attacks (see `engine/evaluation/adversarial.py`):",
               "", "```", json.dumps(r["adversarial"], indent=1), "```", ""]
    md += ["## Index build (cold precompute)", "", "```", json.dumps(r["index"].get("timings"), indent=1),
           json.dumps(r["index"].get("benchmark", {}), indent=1), "```", ""]
    return "\n".join(md)


if __name__ == "__main__":
    main()
