// Types mirroring the backend JSON. Kept in one file so the API contract is
// easy to review; see backend/app/api/routes.py for the producers.

export type Importance = "mandatory" | "preferred";
export type Policy = "ignore" | "penalize" | "exclude";

export interface Requirement {
  id: string;
  label: string;
  concept_id: string | null;
  skills: string[];
  phrases: string[];
  semantic: string | null;
  signal: string | null;
  importance: Importance;
  weight: number;
  hard: boolean;
  min_coverage: number;
  source_text: string | null;
}

export interface ConstraintSpec {
  id: string;
  label: string;
  policy: Policy;
  factor: number;
  source_text: string | null;
}

export interface ComponentWeights {
  requirements: number;
  role_fit: number;
  semantic: number;
  lexical: number;
  experience: number;
  engagement: number;
  logistics: number;
}

export interface JobSpec {
  title: string;
  seniority_level: number;
  role_families: Record<string, number>;
  responsibilities: string[];
  requirements: Requirement[];
  experience: {
    min_years: number | null; max_years: number | null; ideal_min: number | null; ideal_max: number | null;
    relevant_min_years: number | null; hard_min: boolean; source_text: string | null;
  };
  location: {
    preferred: string[]; acceptable: string[]; countries: string[];
    work_mode: "onsite" | "hybrid" | "remote" | "flexible" | null;
    relocation_considered: boolean; visa_sponsorship: boolean | null; source_text: string | null;
  };
  notice: { ideal_max_days: number | null; acceptable_max_days: number | null; source_text: string | null };
  constraints: ConstraintSpec[];
  weights: ComponentWeights;
  integrity_policy: "exclude" | "flag";
  as_of_date: string | null;
  focus_text: string;
  raw_text: string;
  extraction_notes: string[];
}

export interface Job {
  id: string;
  kind: "index" | "rank";
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  message: string | null;
  error: string | null;
}

export interface Dataset {
  id: string;
  name: string;
  source_kind: "upload" | "path" | "library";
  size_bytes: number;
  status: "pending" | "indexing" | "ready" | "failed";
  n_candidates: number | null;
  error: string | null;
  created_at: number;
  updated_at: number;
  fingerprint: string | null;
  shared: boolean;
  job: Job | null;
  quality?: QualityReport;
  meta?: { as_of_date: string; embedding_model: string | null; timings: Record<string, number>; n_candidates: number };
}

export interface QualityReport {
  rows_read: number;
  valid_records: number;
  rejected_records: number;
  rejected_examples: { row: number; reason: string }[];
  warnings: { issue: string; count: number }[];
  missing_values: Record<string, { count: number; pct: number }>;
  integrity: { code: string; severity: string; count: number }[];
  duplicates: number;
  unique_text_segments: number;
  unique_descriptions: number;
  top_titles: [string, number][];
  countries: [string, number][];
  experience_histogram: [number, number][];
}

export interface RunSummary {
  context: {
    as_of_date: string; semantic_available: boolean; embedding_model: string | null;
    weights_used: Record<string, number>; notes: string[]; n_candidates: number; n_eligible: number;
    n_critical: number; requirement_ids: string[];
  };
  score_histogram: { counts: number[]; edges: number[] };
  shortlist_component_means: Record<string, number>;
  n_held_for_review: number;
  requirements: { id: string; label: string; importance: Importance; met_in_shortlist: number }[];
}

export interface Run {
  id: string;
  name: string;
  jd_title: string;
  dataset_id: string;
  dataset_name: string;
  status: "queued" | "running" | "ready" | "failed" | "cancelled";
  shortlist_size: number | null;
  n_candidates: number | null;
  n_eligible: number | null;
  n_results: number | null;
  created_at: number;
  finished_at: number | null;
  error?: string | null;
  spec?: JobSpec;
  summary?: RunSummary | null;
  job?: Job | null;
}

export interface ResultRow {
  rank: number;
  candidate_id: string;
  idx: number;
  overall: number;
  requirements: number;
  role_fit: number;
  semantic: number;
  lexical: number;
  experience: number;
  engagement: number;
  logistics: number;
  constraint_factor: number;
  mandatory_coverage: number | null;
  evidence_completeness: number;
  critical_flag: boolean;
  warning_flags: number;
  eligible: boolean;
  ineligible_reason: string;
  name: string;
  title: string;
  company: string;
  location: string;
  city: string;
  country: string;
  years_experience: number | null;
  fields_of_study: string;
  highest_degree: string;
  skills: string[];
  relevant_skills: string[];
  n_assessments: number;
  assessment_mean: number | null;
  flag_codes: string[];
  mandatory_met: number;
  mandatory_total: number;
  requirement_coverage: Record<string, number>;
  constraints_triggered: string[];
  sig_notice_period_days: number | null;
  sig_recruiter_response_rate: number | null;
  sig_last_active_date: string | null;
}

export interface Page<T> {
  total: number;
  page: number;
  page_size: number;
  items: T[];
}

export interface Facets {
  countries: { value: string; count: number }[];
  cities: { value: string; count: number }[];
  branches: { value: string; count: number }[];
  skills: { value: string; count: number }[];
  flags: { none: number; any: number; critical: number; warning: number };
  years: { min: number | null; max: number | null };
  score: { min: number | null; max: number | null };
  held_for_review: number;
}

export interface EvidenceItem {
  kind: "skill" | "role_text" | "summary_text" | "signal";
  skill?: string;
  proficiency?: string | null;
  months?: number | null;
  assessed?: number | null;
  verified?: boolean;
  title?: string;
  company?: string;
  is_current?: boolean;
  phrases?: string[];
  signal?: string;
  value?: number | boolean | string | null;
  strength: number;
}

export interface RequirementDetail {
  id: string;
  label: string;
  importance: Importance;
  weight: number;
  coverage: number;
  status: "met" | "partial" | "missing";
  evidence: EvidenceItem[];
  skill_matches: number;
}

export interface Flag {
  code: string;
  severity: "critical" | "warning" | "info";
  title: string;
  detail: string;
  evidence: Record<string, unknown>;
}

export interface CandidateRecord {
  candidate_id: string;
  profile: {
    anonymized_name: string; headline: string; summary: string; location: string; country: string;
    years_of_experience: number | null; current_title: string; current_company: string;
    current_company_size: string | null; current_industry: string;
  };
  career_history: {
    company: string; title: string; start_date: string | null; end_date: string | null;
    duration_months: number | null; is_current: boolean; industry: string; description: string;
  }[];
  education: { institution: string; degree: string; field_of_study: string; start_year: number | null; end_year: number | null }[];
  skills: { name: string; proficiency: string | null; endorsements: number | null; duration_months: number | null }[];
  certifications: { name: string; issuer: string; year: number }[];
  redrob_signals: Record<string, unknown> & { skill_assessment_scores: Record<string, number> };
}

export interface Explanation {
  candidate_id: string;
  rank: number;
  eligible: boolean;
  ineligible_reason: string | null;
  overall: number;
  tone: string;
  summary: string;
  summary_claims: string;
  components: { id: string; label: string; value: number; weight: number; contribution: number }[];
  constraint_factor: number;
  triggered_constraints: { id: string; label: string; policy: Policy; factor: number; source_text: string | null }[];
  requirements: RequirementDetail[];
  mandatory_met: number;
  mandatory_total: number;
  strengths: string[];
  gaps: string[];
  concerns: string[];
  missing_information: string[];
  flags: Flag[];
  differentiators: { component: string; label: string; delta: number; value: number; neighbour_mean: number }[];
  evidence_completeness: number;
  signals: Record<"engagement" | "logistics" | "experience", Record<string, number | null>>;
  experience: { years: number | null; relevant_years: number; title_relevance: number; career_relevance: number };
  record: CandidateRecord;
}

export interface Comparison {
  candidates: Explanation[];
  requirements: { id: string; label: string; importance: Importance; values: number[] }[];
  components: { id: string; label: string; values: number[] }[];
}

export interface Shortlist {
  id: string;
  name: string;
  run_id: string;
  created_at: number;
  jd_title?: string;
  size?: number;
  items?: { candidate_id: string; note: string; added_at: number }[];
}

export interface Concept {
  id: string;
  label: string;
  category: string;
  skills: string[];
  phrases: string[];
  semantic: string;
  signal: string | null;
}

export interface Dashboard {
  datasets: Dataset[];
  recent_runs: Run[];
  activity: { kind: string; message: string; ref_id: string | null; created_at: number }[];
  totals: { datasets: number; ready_datasets: number; candidates: number; runs: number; shortlists: number };
}
