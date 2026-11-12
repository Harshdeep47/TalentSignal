import { Link, useParams } from "react-router-dom";
import { ArrowLeft, BadgeCheck, CircleDashed, CircleSlash, ShieldAlert, TrendingDown, TrendingUp } from "lucide-react";
import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { ErrorBox, num, pct, ScoreBar, score100, Spinner } from "../components/ui";
import type { EvidenceItem, Explanation, RequirementDetail } from "../types/api";

const COLORS: Record<string, string> = {
  requirements: "#14213d", role_fit: "#2b6f8e", semantic: "#e4572e", lexical: "#9aa3b8",
  experience: "#6c8f3a", engagement: "#b7790a", logistics: "#7d5ba6",
};
const SIGNAL_LABELS: Record<string, string> = {
  activity_recency: "Recent activity", response_rate: "Recruiter response rate", response_speed: "Response speed",
  open_to_work: "Open to work", interview_reliability: "Interview attendance", offer_follow_through: "Offer acceptance",
  recruiter_interest: "Saved by recruiters", location: "Location fit", notice: "Notice period fit", work_mode: "Work-mode fit",
  band: "Years vs band", relevant: "Relevant years", seniority: "Seniority alignment",
};

function Evidence({ e }: { e: EvidenceItem }) {
  if (e.kind === "skill") return (
    <div className="ev">{e.verified ? <BadgeCheck size={14} color="var(--verified)" aria-label="verified" /> : <CircleDashed size={14} color="var(--faint)" aria-label="self-reported" />}
      <span><strong>{e.skill}</strong> {e.proficiency && <span className="muted">{e.proficiency}</span>}
        {e.months !== null && e.months !== undefined && <span className="muted"> · {e.months} months used</span>}
        {e.assessed !== null && e.assessed !== undefined && <span className="chip ok" style={{ marginLeft: 6 }}>assessed {Math.round(e.assessed)}/100</span>}
        {!e.verified && <span className="faint"> · self-reported</span>}</span></div>
  );
  if (e.kind === "role_text") return (
    <div className="ev"><span className="status-dot" style={{ background: "var(--data)", marginTop: 6 }} />
      <span>{e.is_current ? "Current role" : "Past role"} <strong>{e.title}</strong> at {e.company}
        {e.phrases && e.phrases.length > 0 ? <> mentions {e.phrases.map((p) => <span key={p} className="chip" style={{ marginLeft: 4 }}>{p}</span>)}</>
          : <span className="muted"> - description is semantically close to this requirement</span>}</span></div>
  );
  if (e.kind === "summary_text") return (
    <div className="ev"><span className="status-dot" style={{ background: "var(--faint)", marginTop: 6 }} />
      <span>Profile summary {e.phrases?.length ? <>mentions {e.phrases.map((p) => <span key={p} className="chip" style={{ marginLeft: 4 }}>{p}</span>)}</> : "is related"}
        <span className="faint"> · self-description, counted at reduced weight</span></span></div>
  );
  return <div className="ev"><span className="status-dot" style={{ background: "var(--verified)", marginTop: 6 }} /><span>GitHub activity score {String(e.value)}</span></div>;
}

function ReqRow({ r }: { r: RequirementDetail }) {
  const icon = r.status === "met" ? <BadgeCheck size={16} color="var(--verified)" /> : r.status === "partial" ? <CircleDashed size={16} color="var(--caution)" /> : <CircleSlash size={16} color="var(--risk)" />;
  return (
    <div className="req-row">
      <div><div className="row" style={{ gap: 6 }}>{icon}<strong>{r.label}</strong></div>
        <div className="row" style={{ gap: 6, marginTop: 4 }}><span className={`badge ${r.importance}`}>{r.importance === "mandatory" ? "must-have" : "nice-to-have"}</span>
          {r.skill_matches > 1 && <span className="cell-sub">{r.skill_matches} matching skills (best one counts)</span>}</div></div>
      <div><ScoreBar value={r.coverage} tone={r.status === "met" ? "ok" : r.status === "partial" ? "data" : "ink"} /><div className="cell-sub">{r.status}</div></div>
      <div className="evidence">{r.evidence.length ? r.evidence.map((e, i) => <Evidence key={i} e={e} />) : <span className="muted">No evidence found in the profile.</span>}</div>
    </div>
  );
}

function Breakdown({ e }: { e: Explanation }) {
  const total = e.components.reduce((a, c) => a + c.contribution, 0) || 1;
  return (
    <section className="card card-pad">
      <h2>Why this score</h2>
      <div className="stackbar" style={{ height: 18 }}>
        {e.components.filter((c) => c.weight > 0).map((c) => <span key={c.id} title={`${c.label}: ${score100(c.contribution)}`} style={{ width: `${(c.contribution / total) * 100}%`, background: COLORS[c.id] }} />)}
      </div>
      <table className="data" style={{ marginTop: 12 }}>
        <thead><tr><th>Component</th><th>Value</th><th>Weight</th><th>Points</th></tr></thead>
        <tbody>
          {e.components.map((c) => (
            <tr key={c.id}><td><span className="status-dot" style={{ background: COLORS[c.id], marginRight: 8 }} />{c.label}</td>
              <td style={{ minWidth: 140 }}><ScoreBar value={c.value} /></td><td className="num">{pct(c.weight)}</td>
              <td className="num">{score100(c.contribution)}</td></tr>
          ))}
          <tr><td><strong>Weighted sum</strong></td><td /><td /><td className="num"><strong>{score100(total)}</strong></td></tr>
          {e.constraint_factor < 1 && <tr><td>× declared conditions</td><td className="cell-sub">{e.triggered_constraints.filter((c) => c.policy === "penalize").map((c) => c.label).join("; ")}</td><td /><td className="num">× {e.constraint_factor.toFixed(2)}</td></tr>}
          <tr><td><strong>Overall</strong></td><td /><td /><td className="num"><strong>{score100(e.overall)}</strong></td></tr>
        </tbody>
      </table>
      <p className="cell-sub" style={{ marginBottom: 0 }}>Scores summarise the available evidence on a 0-100 scale. They are not probabilities of hiring success.</p>
    </section>
  );
}

export default function CandidatePage() {
  const { id = "", cid = "" } = useParams();
  const { data: e, error, loading, reload } = useAsync(() => api.candidate(id, cid), [id, cid]);
  if (loading && !e) return <Spinner label="Loading candidate" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!e) return null;
  const p = e.record.profile;
  const sig = e.record.redrob_signals;
  const assessments = sig.skill_assessment_scores ?? {};
  const toneClass = e.tone.startsWith("Held") ? "held" : e.tone.startsWith("Top") ? "top" : e.tone.startsWith("Strong") ? "strong" : "";

  return (
    <div className="stack">
      <Link to={`/runs/${id}`} className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start" }}><ArrowLeft size={14} /> Back to results</Link>
      <section className="card card-pad">
        <div className="detail-head">
          <div>
            <div className="eyebrow">{e.rank ? `Rank ${e.rank}` : "Held for review"} · <span className="mono">{e.candidate_id}</span></div>
            <h1 style={{ margin: "4px 0 2px", fontSize: 24 }}>{p.anonymized_name}</h1>
            <div className="muted">{p.current_title} at {p.current_company} · {num(p.years_of_experience)} years · {p.location}, {p.country}</div>
            <p style={{ margin: "10px 0 0", maxWidth: 820 }}><span className={`tone ${toneClass}`}>{e.tone}.</span> {e.summary.replace(`${e.tone}: `, "")}</p>
          </div>
          <div className="big-score"><div className="v">{score100(e.overall)}</div><div className="cell-sub">overall · {e.mandatory_met}/{e.mandatory_total} must-haves</div>
            <div className="cell-sub">evidence completeness {pct(e.evidence_completeness)}</div></div>
        </div>
        {!e.eligible && <div className="banner risk" style={{ marginTop: 12 }}><ShieldAlert size={16} /><div><strong>Held out of the shortlist.</strong> {e.ineligible_reason}. The scores below are shown for review only.</div></div>}
      </section>

      <div className="grid grid-2">
        <Breakdown e={e} />
        <section className="card card-pad">
          <h2>What sets this candidate apart</h2>
          {e.differentiators.length === 0 ? <div className="muted">Very similar to neighbouring candidates on every component.</div> : (
            <ul className="list-plain" style={{ listStyle: "none", padding: 0 }}>
              {e.differentiators.map((d) => (
                <li key={d.component} className="row" style={{ padding: "4px 0" }}>
                  {d.delta > 0 ? <TrendingUp size={15} color="var(--verified)" /> : <TrendingDown size={15} color="var(--risk)" />}
                  <span>{d.label}: <span className="mono">{score100(d.value)}</span> vs <span className="mono">{score100(d.neighbour_mean)}</span> for nearby ranks</span>
                </li>))}
            </ul>)}
          <div className="divider" />
          <h2>Concerns</h2>
          {e.concerns.length === 0 ? <div className="muted">None found in the profile.</div> : <ul className="list-plain">{e.concerns.map((c) => <li key={c}>{c}</li>)}</ul>}
          <h2 style={{ marginTop: 14 }}>Missing information</h2>
          <p className="cell-sub" style={{ marginTop: -6 }}>Not held against the candidate - shown so you know what to ask.</p>
          {e.missing_information.length === 0 ? <div className="muted">Nothing notable.</div> : <div className="chips">{e.missing_information.map((m) => <span className="chip" key={m}>{m}</span>)}</div>}
        </section>
      </div>

      <section className="card">
        <div className="card-head"><h2>Requirement evidence</h2><span className="legend"><span><BadgeCheck size={13} color="var(--verified)" /> platform-verified</span><span><CircleDashed size={13} /> self-reported</span></span></div>
        <div style={{ padding: "0 20px 6px" }}>{e.requirements.map((r) => <ReqRow key={r.id} r={r} />)}</div>
      </section>

      {e.flags.length > 0 && (
        <section className="card card-pad">
          <h2>Integrity and consistency checks</h2>
          {e.flags.map((f) => (
            <div key={f.code} className={`banner ${f.severity === "critical" ? "risk" : f.severity === "warning" ? "warn" : "info"}`} style={{ marginBottom: 8 }}>
              <ShieldAlert size={16} /><div><strong>{f.title}</strong> <span className="chip" style={{ marginLeft: 4 }}>{f.severity}</span><div>{f.detail}</div>
                {Object.keys(f.evidence).length > 0 && <div className="mono cell-sub" style={{ marginTop: 3 }}>{JSON.stringify(f.evidence)}</div>}</div>
            </div>))}
          <p className="cell-sub" style={{ marginBottom: 0 }}>Findings indicate the record needs a closer look; they are not proof of misrepresentation.</p>
        </section>
      )}

      <div className="grid grid-3">
        {(["engagement", "logistics", "experience"] as const).map((g) => (
          <section className="card card-pad" key={g}>
            <h2 style={{ textTransform: "capitalize" }}>{g} signals</h2>
            {Object.entries(e.signals[g]).map(([k, v]) => (
              <div key={k} className="weight-row" style={{ gridTemplateColumns: "1fr 110px", marginBottom: 4 }}>
                <span style={{ fontSize: 13 }}>{SIGNAL_LABELS[k] ?? k}</span>
                {v === null ? <span className="faint cell-sub">not provided</span> : <ScoreBar value={v} tone="data" />}
              </div>))}
          </section>))}
      </div>

      <div className="grid grid-2">
        <section className="card card-pad">
          <h2>Career history</h2>
          <div className="timeline">
            {e.record.career_history.map((r, i) => (
              <div className="tl-item" key={i}>
                <span className={`tl-dot ${i === 0 ? "rel-high" : "rel-mid"}`} />
                <div><div><strong>{r.title}</strong> · {r.company} <span className="cell-sub">({r.industry})</span></div>
                  <div className="cell-sub mono">{r.start_date ?? "?"} → {r.is_current ? "present" : r.end_date ?? "?"} · {r.duration_months ?? "?"} months</div>
                  <div style={{ fontSize: 13, marginTop: 4, color: "#3b4253" }}>{r.description}</div></div>
              </div>))}
          </div>
        </section>
        <div className="stack">
          <section className="card card-pad">
            <h2>Skills</h2>
            <table className="data"><thead><tr><th>Skill</th><th>Proficiency</th><th>Used</th><th>Assessment</th></tr></thead>
              <tbody>{e.record.skills.map((s) => {
                const a = Object.entries(assessments).find(([k]) => k.toLowerCase() === s.name.toLowerCase())?.[1];
                return <tr key={s.name}><td>{s.name}</td><td>{s.proficiency ?? "-"}</td><td className="num">{s.duration_months ?? "-"} mo</td>
                  <td>{a !== undefined ? <span className="chip ok">{Math.round(a)}/100</span> : <span className="faint">-</span>}</td></tr>;
              })}</tbody></table>
          </section>
          <section className="card card-pad">
            <h2>Profile</h2>
            <dl className="kv">
              <dt>Headline</dt><dd>{p.headline}</dd>
              <dt>Summary</dt><dd>{p.summary}</dd>
              <dt>Education</dt><dd>{e.record.education.map((ed, i) => <div key={i}>{ed.degree}, {ed.field_of_study} - {ed.institution}</div>)}</dd>
              <dt>Notice period</dt><dd>{String(sig.notice_period_days ?? "not provided")} days</dd>
              <dt>Last active</dt><dd>{String(sig.last_active_date ?? "not provided")}</dd>
              <dt>Work mode</dt><dd>{String(sig.preferred_work_mode ?? "not provided")} · relocate: {String(sig.willing_to_relocate ?? "unknown")}</dd>
              <dt>Verification</dt><dd>email {sig.verified_email ? "✓" : "✗"} · phone {sig.verified_phone ? "✓" : "✗"} · LinkedIn {sig.linkedin_connected ? "✓" : "✗"}</dd>
            </dl>
          </section>
        </div>
      </div>
    </div>
  );
}
