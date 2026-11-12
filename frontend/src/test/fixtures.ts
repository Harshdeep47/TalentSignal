import type { Explanation, JobSpec, Page, ResultRow, Run } from "../types/api";

export const spec: JobSpec = {
  title: "Senior AI Engineer",
  seniority_level: 3,
  role_families: { ml_engineering: 1 },
  responsibilities: [],
  requirements: [
    { id: "embeddings_retrieval", label: "Embeddings-based retrieval", concept_id: "embeddings_retrieval", skills: ["Embeddings"],
      phrases: ["embedding"], semantic: "x", signal: null, importance: "mandatory", weight: 1, hard: false, min_coverage: 0.35,
      source_text: "Production experience with embeddings" },
    { id: "python", label: "Python", concept_id: "python", skills: ["Python"], phrases: ["python"], semantic: "x", signal: null,
      importance: "mandatory", weight: 1, hard: false, min_coverage: 0.35, source_text: "Strong Python." },
    { id: "llm_finetuning", label: "LLM fine-tuning", concept_id: "llm_finetuning", skills: ["LoRA"], phrases: [], semantic: "x",
      signal: null, importance: "preferred", weight: 0.5, hard: false, min_coverage: 0.35, source_text: null },
  ],
  experience: { min_years: 5, max_years: 9, ideal_min: 6, ideal_max: 8, relevant_min_years: 4, hard_min: false, source_text: null },
  location: { preferred: ["pune"], acceptable: [], countries: ["India"], work_mode: "hybrid", relocation_considered: true,
    visa_sponsorship: false, source_text: null },
  notice: { ideal_max_days: 30, acceptable_max_days: 60, source_text: null },
  constraints: [{ id: "consulting_only", label: "Consulting-only career", policy: "penalize", factor: 0.5, source_text: null }],
  weights: { requirements: 0.34, role_fit: 0.2, semantic: 0.12, lexical: 0.05, experience: 0.1, engagement: 0.11, logistics: 0.08 },
  integrity_policy: "exclude",
  as_of_date: null,
  focus_text: "",
  raw_text: "",
  extraction_notes: [],
};

export const row = (i: number, extra: Partial<ResultRow> = {}): ResultRow => ({
  rank: i, candidate_id: `CAND_${String(i).padStart(7, "0")}`, idx: i, overall: 0.9 - i * 0.01, requirements: 0.8,
  role_fit: 1, semantic: 0.6, lexical: 0.9, experience: 1, engagement: 0.8, logistics: 0.9, constraint_factor: 1,
  mandatory_coverage: 0.9, evidence_completeness: 0.7, critical_flag: false, warning_flags: 0, eligible: true,
  ineligible_reason: "", name: `Person ${i}`, title: "ML Engineer", company: "Acme", location: "Pune, Maharashtra",
  city: "Pune", country: "India", years_experience: 7, fields_of_study: "Computer Science", highest_degree: "B.Tech",
  skills: ["Python", "Embeddings"], relevant_skills: ["Python", "Embeddings"], n_assessments: 1, assessment_mean: 80,
  flag_codes: [], mandatory_met: 2, mandatory_total: 2, requirement_coverage: { embeddings_retrieval: 0.9, python: 0.8 },
  constraints_triggered: [], sig_notice_period_days: 30, sig_recruiter_response_rate: 0.7, sig_last_active_date: "2026-05-01",
  ...extra,
});

export const page: Page<ResultRow> = { total: 3, page: 1, page_size: 50, items: [row(1), row(2), row(3)] };

export const run: Run = {
  id: "run1", name: "Run", jd_title: "Senior AI Engineer", dataset_id: "ds1", dataset_name: "candidates.jsonl",
  status: "ready", shortlist_size: 100, n_candidates: 1000, n_eligible: 990, n_results: 3, created_at: 1760000000,
  finished_at: 1760000010, spec,
  summary: {
    context: { as_of_date: "2026-05-27", semantic_available: true, embedding_model: "bge-small-en-v1.5",
      weights_used: spec.weights as unknown as Record<string, number>, notes: [], n_candidates: 1000, n_eligible: 990,
      n_critical: 2, requirement_ids: ["embeddings_retrieval", "python", "llm_finetuning"] },
    score_histogram: { counts: Array(20).fill(5), edges: Array.from({ length: 21 }, (_, i) => i / 20) },
    shortlist_component_means: {}, n_held_for_review: 2,
    requirements: [{ id: "python", label: "Python", importance: "mandatory", met_in_shortlist: 3 }],
  },
  job: null,
};

export const explanation: Explanation = {
  candidate_id: "CAND_0000001", rank: 1, eligible: true, ineligible_reason: null, overall: 0.89, tone: "Top match",
  summary: "Top match: ML Engineer at Acme (7.0 yrs) meets 2 of 2 must-haves, with Embeddings (expert, assessed 82/100).",
  summary_claims: "Top match: ML Engineer at Acme (7.0 yrs) meets 2 of 2 must-haves.",
  components: [{ id: "requirements", label: "Requirement coverage", value: 0.8, weight: 0.34, contribution: 0.272 }],
  constraint_factor: 1, triggered_constraints: [],
  requirements: [{ id: "embeddings_retrieval", label: "Embeddings-based retrieval", importance: "mandatory", weight: 1, coverage: 0.9,
    status: "met", skill_matches: 1,
    evidence: [{ kind: "skill", skill: "Embeddings", proficiency: "expert", months: 30, assessed: 82, verified: true, strength: 0.9 }] }],
  mandatory_met: 2, mandatory_total: 2, strengths: [], gaps: [], concerns: ["notice period 60 days (JD prefers <= 30)"],
  missing_information: ["No GitHub account linked"], flags: [], differentiators: [], evidence_completeness: 0.7,
  signals: { engagement: { response_rate: 0.7, offer_follow_through: null }, logistics: { location: 1 }, experience: { band: 1 } },
  experience: { years: 7, relevant_years: 6.5, title_relevance: 1, career_relevance: 0.95 },
  record: {
    candidate_id: "CAND_0000001",
    profile: { anonymized_name: "Person 1", headline: "ML", summary: "Builds search.", location: "Pune, Maharashtra", country: "India",
      years_of_experience: 7, current_title: "ML Engineer", current_company: "Acme", current_company_size: null, current_industry: "AI" },
    career_history: [{ company: "Acme", title: "ML Engineer", start_date: "2019-01-01", end_date: null, duration_months: 84,
      is_current: true, industry: "AI", description: "Built ranking." }],
    education: [], skills: [{ name: "Embeddings", proficiency: "expert", endorsements: 3, duration_months: 30 }], certifications: [],
    redrob_signals: { skill_assessment_scores: { Embeddings: 82 }, notice_period_days: 60 },
  },
};

type Handler = (url: string, init?: RequestInit) => unknown;

/** Install a fetch mock that routes by URL substring. Returns the call log. */
export function mockFetch(routes: [string, Handler][]) {
  const calls: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    const hit = routes.find(([k]) => url.includes(k));
    if (!hit) return new Response(JSON.stringify({ error: { code: "nf", message: `no mock for ${url}` } }), { status: 404 });
    const body = hit[1](url, init);
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  return calls;
}
