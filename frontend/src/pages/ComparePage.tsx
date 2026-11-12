import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { ErrorBox, num, pct, ScoreBar, score100, Spinner } from "../components/ui";

function heat(v: number) {
  const bg = v >= 0.65 ? "var(--verified-soft)" : v >= 0.3 ? "var(--caution-soft)" : "#f0ede6";
  const fg = v >= 0.65 ? "#1f6a51" : v >= 0.3 ? "#8a5b06" : "var(--faint)";
  return { background: bg, color: fg };
}

export default function ComparePage() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const ids = (params.get("ids") ?? "").split(",").filter(Boolean);
  const { data, error, loading, reload } = useAsync(() => api.compare(id, ids), [id, ids.join(",")]);
  if (loading && !data) return <Spinner label="Comparing" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;
  const cs = data.candidates;
  const cols = `200px repeat(${cs.length}, minmax(180px, 1fr))`;
  const allSkills = new Map<string, number>();
  cs.forEach((c) => c.record.skills.forEach((s) => allSkills.set(s.name, (allSkills.get(s.name) ?? 0) + 1)));
  const best = (vals: number[]) => Math.max(...vals);

  return (
    <div className="stack">
      <Link to={`/runs/${id}`} className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start" }}><ArrowLeft size={14} /> Back to results</Link>
      <div className="page-head"><div><div className="eyebrow">Side-by-side</div><h1>Compare {cs.length} candidates</h1>
        <p>Green cells meet a requirement (coverage ≥ 65%), amber is partial. The best value in each component row is bold.</p></div></div>
      <section className="card" style={{ overflowX: "auto" }}>
        <div className="compare-grid" style={{ gridTemplateColumns: cols }}>
          <div className="cg-cell cg-label cg-head">Candidate</div>
          {cs.map((c) => (
            <div key={c.candidate_id} className="cg-cell cg-head">
              <Link to={`/runs/${id}/candidates/${c.candidate_id}`} style={{ textDecoration: "none" }}>{c.record.profile.anonymized_name}</Link>
              <div className="cell-sub">{c.record.profile.current_title} · {c.record.profile.current_company}</div>
              <div className="cell-sub mono">{c.rank ? `rank ${c.rank}` : "held for review"}</div>
            </div>))}
          <div className="cg-cell cg-label">Overall score</div>
          {cs.map((c) => <div key={c.candidate_id} className="cg-cell"><ScoreBar value={c.overall} tone="signal" /></div>)}
          <div className="cg-cell cg-label">Summary</div>
          {cs.map((c) => <div key={c.candidate_id} className="cg-cell" style={{ fontSize: 12.5 }}>{c.summary}</div>)}

          {data.components.map((row) => (
            <div className="cg-row" key={row.id}>
              <div className="cg-cell cg-label">{row.label}</div>
              {row.values.map((v, i) => <div key={i} className="cg-cell" style={{ fontWeight: v === best(row.values) ? 700 : 400 }}><ScoreBar value={v} /></div>)}
            </div>))}

          <div className="cg-cell cg-label cg-head">Requirements</div>
          {cs.map((c) => <div key={c.candidate_id} className="cg-cell cg-head mono">{c.mandatory_met}/{c.mandatory_total} must-haves</div>)}
          {data.requirements.map((r) => (
            <div className="cg-row" key={r.id}>
              <div className="cg-cell cg-label">{r.importance === "mandatory" ? <strong>{r.label}</strong> : r.label}</div>
              {r.values.map((v, i) => <div key={i} className="cg-cell"><span className="heat" style={heat(v)}>{score100(v)}</span></div>)}
            </div>))}

          <div className="cg-cell cg-label cg-head">Profile</div>
          {cs.map((c) => <div key={c.candidate_id} className="cg-cell cg-head" />)}
          <div className="cg-cell cg-label">Experience</div>
          {cs.map((c) => <div key={c.candidate_id} className="cg-cell mono">{num(c.experience.years)} yrs · {num(c.experience.relevant_years)} relevant</div>)}
          <div className="cg-cell cg-label">Assessments</div>
          {cs.map((c) => {
            const a = Object.entries(c.record.redrob_signals.skill_assessment_scores ?? {});
            return <div key={c.candidate_id} className="cg-cell">{a.length ? a.map(([k, v]) => <div key={k} className="cell-sub">{k}: <span className="mono">{Math.round(v)}</span></div>) : <span className="faint">none</span>}</div>;
          })}
          <div className="cg-cell cg-label">Evidence completeness</div>
          {cs.map((c) => <div key={c.candidate_id} className="cg-cell mono">{pct(c.evidence_completeness)}</div>)}
          <div className="cg-cell cg-label">Skills</div>
          {cs.map((c) => (
            <div key={c.candidate_id} className="cg-cell"><div className="chips">{c.record.skills.map((s) => (
              <span key={s.name} className={`chip ${allSkills.get(s.name) === cs.length ? "data" : allSkills.get(s.name) === 1 ? "signal" : ""}`}
                title={allSkills.get(s.name) === 1 ? "Only this candidate" : allSkills.get(s.name) === cs.length ? "Shared by all" : ""}>{s.name}</span>))}</div></div>))}
          <div className="cg-cell cg-label">Concerns</div>
          {cs.map((c) => <div key={c.candidate_id} className="cg-cell cell-sub">{c.concerns.length ? c.concerns.join("; ") : "none"}</div>)}
          <div className="cg-cell cg-label">Integrity</div>
          {cs.map((c) => <div key={c.candidate_id} className="cg-cell cell-sub">{c.flags.filter((f) => f.severity !== "info").map((f) => f.title).join("; ") || "no findings"}</div>)}
        </div>
      </section>
      <div className="legend"><span><i style={{ background: "var(--data-soft)" }} />skill shared by all</span><span><i style={{ background: "var(--signal-soft)" }} />skill unique to one candidate</span>
        <span>score values shown as {score100(1)}-point scale</span></div>
    </div>
  );
}
