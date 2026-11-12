import { useState } from "react";
import { Info, Plus, Trash2 } from "lucide-react";
import type { ComponentWeights, Concept, JobSpec, Policy, Requirement } from "../types/api";

const WEIGHT_LABELS: Record<keyof ComponentWeights, string> = {
  requirements: "Requirement coverage", role_fit: "Role relevance", semantic: "Semantic match",
  lexical: "Keyword relevance (BM25)", experience: "Experience fit", engagement: "Engagement signals",
  logistics: "Location & availability",
};
const WEIGHT_HELP: Record<keyof ComponentWeights, string> = {
  requirements: "How well skills, assessments and career descriptions evidence each requirement.",
  role_fit: "How related the candidate's current and past job titles are to this role.",
  semantic: "Embedding similarity between the JD and the candidate's role descriptions.",
  lexical: "BM25 keyword relevance over the whole profile (a percentile).",
  experience: "Years against the band, relevant years, and seniority alignment.",
  engagement: "Recent activity, responsiveness, interview reliability (missing values are neutral).",
  logistics: "Location, notice period and work-mode fit.",
};

export function ChipEditor({ values, onChange, placeholder }: { values: string[]; onChange: (v: string[]) => void; placeholder: string }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const parts = draft.split(",").map((s) => s.trim()).filter(Boolean);
    if (parts.length) onChange([...values, ...parts.filter((p) => !values.includes(p))]);
    setDraft("");
  };
  return (
    <div>
      <div className="chips" style={{ marginBottom: 6 }}>
        {values.map((v) => (
          <span className="chip" key={v}>{v}
            <button className="chip-x" aria-label={`remove ${v}`} onClick={() => onChange(values.filter((x) => x !== v))}>×</button>
          </span>
        ))}
      </div>
      <input className="input" value={draft} placeholder={placeholder} onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} onBlur={add} />
    </div>
  );
}

function RequirementRow({ r, onChange, onRemove }: { r: Requirement; onChange: (r: Requirement) => void; onRemove: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ borderBottom: "1px solid #efece5" }}>
      <div className="req-edit" style={{ borderBottom: 0 }}>
        <div style={{ minWidth: 0 }}>
          <input className="input" value={r.label} aria-label="Requirement label" onChange={(e) => onChange({ ...r, label: e.target.value })} />
          {r.source_text && <div className="cell-sub" style={{ marginTop: 3 }} title={r.source_text}>
            <Info size={11} /> from JD: "{r.source_text.slice(0, 110)}{r.source_text.length > 110 ? "…" : ""}"</div>}
        </div>
        <select className="select" value={r.importance} aria-label="Importance"
          onChange={(e) => onChange({ ...r, importance: e.target.value as Requirement["importance"], weight: e.target.value === "mandatory" ? Math.max(r.weight, 0.8) : r.weight })}>
          <option value="mandatory">Must-have</option>
          <option value="preferred">Nice-to-have</option>
        </select>
        <div className="field">
          <input type="range" min={0.05} max={1} step={0.05} value={r.weight} aria-label="Weight"
            onChange={(e) => onChange({ ...r, weight: Number(e.target.value) })} />
          <span className="cell-sub mono">weight {r.weight.toFixed(2)}</span>
        </div>
        <label className="check" title="Hard gate: candidates below the minimum evidence are held out of the shortlist (still inspectable)">
          <input type="checkbox" checked={r.hard} onChange={(e) => onChange({ ...r, hard: e.target.checked })} /> Hard
        </label>
        <button className="btn btn-ghost btn-sm" aria-label="Remove requirement" onClick={onRemove}><Trash2 size={15} /></button>
      </div>
      <div style={{ paddingBottom: 8 }}>
        <button className="btn btn-ghost btn-sm" onClick={() => setOpen((o) => !o)}>
          {open ? "Hide" : "Edit"} evidence terms · {r.skills.length} skills · {r.phrases.length} phrases
        </button>
        {open && (
          <div className="grid grid-2" style={{ padding: "8px 0" }}>
            <div><span className="label">Skills (any one counts)</span>
              <ChipEditor values={r.skills} onChange={(skills) => onChange({ ...r, skills })} placeholder="Add skill, press Enter" /></div>
            <div><span className="label">Phrases searched in career text</span>
              <ChipEditor values={r.phrases} onChange={(phrases) => onChange({ ...r, phrases })} placeholder="Add phrase, press Enter" /></div>
            <div style={{ gridColumn: "1 / -1" }}><span className="label">Semantic description (used for embedding similarity)</span>
              <input className="input" value={r.semantic ?? ""} onChange={(e) => onChange({ ...r, semantic: e.target.value || null })} /></div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function SpecEditor({ spec, onChange, concepts }: { spec: JobSpec; onChange: (s: JobSpec) => void; concepts: Concept[] }) {
  const set = <K extends keyof JobSpec>(k: K, v: JobSpec[K]) => onChange({ ...spec, [k]: v });
  const [conceptPick, setConceptPick] = useState("");
  const used = new Set(spec.requirements.map((r) => r.id));
  const totalW = Object.values(spec.weights).reduce((a, b) => a + b, 0) || 1;

  const addConcept = () => {
    const c = concepts.find((x) => x.id === conceptPick);
    if (!c || used.has(c.id)) return;
    set("requirements", [...spec.requirements, {
      id: c.id, label: c.label, concept_id: c.id, skills: c.skills, phrases: c.phrases, semantic: c.semantic,
      signal: c.signal, importance: "preferred", weight: 0.5, hard: false, min_coverage: 0.35, source_text: null,
    }]);
    setConceptPick("");
  };
  const addCustom = () => {
    let i = 1;
    while (used.has(`custom_${i}`)) i++;
    set("requirements", [...spec.requirements, {
      id: `custom_${i}`, label: "New requirement", concept_id: null, skills: [], phrases: [], semantic: null, signal: null,
      importance: "preferred", weight: 0.5, hard: false, min_coverage: 0.35, source_text: null,
    }]);
  };
  const updateReq = (idx: number, r: Requirement) => set("requirements", spec.requirements.map((x, i) => (i === idx ? r : x)));
  const removeReq = (idx: number) => set("requirements", spec.requirements.filter((_, i) => i !== idx));
  const mand = spec.requirements.filter((r) => r.importance === "mandatory").length;

  return (
    <div className="stack">
      {spec.extraction_notes.length > 0 && (
        <div className="banner warn"><Info size={16} /><div>{spec.extraction_notes.map((n) => <div key={n}>{n}</div>)}</div></div>
      )}
      <section className="card card-pad">
        <div className="grid grid-2">
          <div className="field"><span className="label">Role title</span>
            <input className="input" value={spec.title} onChange={(e) => set("title", e.target.value)} /></div>
          <div className="field"><span className="label">Target role families (title relevance)</span>
            <div className="chips">{Object.keys(spec.role_families).length === 0
              ? <span className="muted">None detected - title relevance uses keyword overlap with the role title</span>
              : Object.keys(spec.role_families).map((f) => <span className="chip data" key={f}>{f.replace(/_/g, " ")}</span>)}</div></div>
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Requirements <span className="muted" style={{ fontWeight: 400 }}>· {mand} must-have, {spec.requirements.length - mand} nice-to-have</span></h2>
          <div className="row">
            <select className="select" style={{ width: 240 }} value={conceptPick} onChange={(e) => setConceptPick(e.target.value)} aria-label="Add capability">
              <option value="">Add a known capability…</option>
              {concepts.filter((c) => !used.has(c.id)).map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
            <button className="btn btn-sm" disabled={!conceptPick} onClick={addConcept}><Plus size={14} /> Add</button>
            <button className="btn btn-sm" onClick={addCustom}><Plus size={14} /> Custom</button>
          </div>
        </div>
        <div style={{ padding: "0 20px 8px" }}>
          {spec.requirements.length === 0 && <div className="muted" style={{ padding: 14 }}>No requirements - add at least one.</div>}
          {spec.requirements.map((r, i) => <RequirementRow key={r.id} r={r} onChange={(nr) => updateReq(i, nr)} onRemove={() => removeReq(i)} />)}
        </div>
      </section>

      <div className="grid grid-3">
        <section className="card card-pad">
          <h2>Experience</h2>
          <div className="grid grid-2">
            {(["min_years", "max_years", "ideal_min", "ideal_max"] as const).map((k) => (
              <label className="field" key={k}><span className="label">{k.replace("_", " ")}</span>
                <input className="input mono" type="number" min={0} max={50} step={0.5} value={spec.experience[k] ?? ""}
                  onChange={(e) => set("experience", { ...spec.experience, [k]: e.target.value === "" ? null : Number(e.target.value) })} /></label>
            ))}
          </div>
          <label className="check" style={{ marginTop: 10 }}>
            <input type="checkbox" checked={spec.experience.hard_min}
              onChange={(e) => set("experience", { ...spec.experience, hard_min: e.target.checked })} /> Minimum is a hard gate
          </label>
          {spec.experience.source_text && <div className="cell-sub" style={{ marginTop: 6 }}>From JD: "{spec.experience.source_text}"</div>}
        </section>

        <section className="card card-pad">
          <h2>Location & logistics</h2>
          <span className="label">Preferred cities</span>
          <ChipEditor values={spec.location.preferred} onChange={(v) => set("location", { ...spec.location, preferred: v })} placeholder="Add city" />
          <span className="label" style={{ marginTop: 8 }}>Also acceptable</span>
          <ChipEditor values={spec.location.acceptable} onChange={(v) => set("location", { ...spec.location, acceptable: v })} placeholder="Add city or region" />
          <span className="label" style={{ marginTop: 8 }}>Hiring countries</span>
          <ChipEditor values={spec.location.countries} onChange={(v) => set("location", { ...spec.location, countries: v })} placeholder="Add country" />
          <div className="grid grid-2" style={{ marginTop: 8 }}>
            <label className="field"><span className="label">Work mode</span>
              <select className="select" value={spec.location.work_mode ?? ""} onChange={(e) => set("location", { ...spec.location, work_mode: (e.target.value || null) as JobSpec["location"]["work_mode"] })}>
                <option value="">Not specified</option><option value="onsite">Onsite</option><option value="hybrid">Hybrid</option>
                <option value="remote">Remote</option><option value="flexible">Flexible</option></select></label>
            <label className="field"><span className="label">Notice: ideal max days</span>
              <input className="input mono" type="number" min={0} max={365} value={spec.notice.ideal_max_days ?? ""}
                onChange={(e) => set("notice", { ...spec.notice, ideal_max_days: e.target.value === "" ? null : Number(e.target.value) })} /></label>
          </div>
          <label className="check" style={{ marginTop: 8 }}>
            <input type="checkbox" checked={spec.location.visa_sponsorship === false}
              onChange={(e) => set("location", { ...spec.location, visa_sponsorship: e.target.checked ? false : null })} /> No visa sponsorship
          </label>
        </section>

        <section className="card card-pad">
          <h2>Declared conditions</h2>
          <p className="muted" style={{ marginTop: 0, fontSize: 12.5 }}>Conditions the JD states explicitly. Choose what happens to candidates who match them.</p>
          {spec.constraints.length === 0 && <div className="muted">None detected.</div>}
          {spec.constraints.map((c, i) => (
            <div key={c.id} style={{ padding: "6px 0", borderBottom: "1px solid #efece5" }}>
              <div style={{ fontSize: 13, fontWeight: 500 }} title={c.source_text ?? ""}>{c.label}</div>
              <div className="row" style={{ marginTop: 4 }}>
                <select className="select" style={{ width: 120 }} value={c.policy} aria-label={`Policy for ${c.label}`}
                  onChange={(e) => set("constraints", spec.constraints.map((x, j) => j === i ? { ...x, policy: e.target.value as Policy } : x))}>
                  <option value="ignore">Show only</option><option value="penalize">Penalise</option><option value="exclude">Exclude</option>
                </select>
                {c.policy === "penalize" && (
                  <label className="row cell-sub">× <input className="input mono" style={{ width: 70 }} type="number" min={0} max={1} step={0.05} value={c.factor}
                    onChange={(e) => set("constraints", spec.constraints.map((x, j) => j === i ? { ...x, factor: Number(e.target.value) } : x))} /></label>
                )}
              </div>
            </div>
          ))}
          <label className="field" style={{ marginTop: 10 }}><span className="label">Critical integrity findings</span>
            <select className="select" value={spec.integrity_policy} onChange={(e) => set("integrity_policy", e.target.value as JobSpec["integrity_policy"])}>
              <option value="exclude">Hold for human review (recommended)</option><option value="flag">Rank normally, show flag</option>
            </select></label>
        </section>
      </div>

      <section className="card card-pad">
        <h2>Score components</h2>
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>Relative influence of each component. Weights are normalised to 100%.</p>
        <div className="grid grid-2">
          {(Object.keys(WEIGHT_LABELS) as (keyof ComponentWeights)[]).map((k) => (
            <div className="weight-row" key={k} title={WEIGHT_HELP[k]}>
              <span style={{ fontSize: 13 }}>{WEIGHT_LABELS[k]}</span>
              <input type="range" min={0} max={0.6} step={0.01} value={spec.weights[k]} aria-label={WEIGHT_LABELS[k]}
                onChange={(e) => set("weights", { ...spec.weights, [k]: Number(e.target.value) })} />
              <span className="mono" style={{ textAlign: "right" }}>{Math.round((spec.weights[k] / totalW) * 100)}%</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
