import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowUp, Eye } from "lucide-react";
import { api } from "../services/api";
import type { Explanation, Facets, ResultRow } from "../types/api";
import { CoverageDots, FlagIcons, num, pct, RankPill, ScoreBar } from "./ui";
import type { ResultQuery } from "../services/api";

export type SortState = { sort: string; order: "asc" | "desc" };

function SortHead({ id, label, s, onSort }: { id: string; label: string; s: SortState; onSort: (s: SortState) => void }) {
  const active = s.sort === id;
  const next: SortState = { sort: id, order: active && s.order === (id === "rank" ? "asc" : "desc") ? (id === "rank" ? "desc" : "asc") : id === "rank" ? "asc" : "desc" };
  return (
    <th aria-sort={active ? (s.order === "asc" ? "ascending" : "descending") : "none"}>
      <button onClick={() => onSort(next)}>{label}{active && (s.order === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}</button>
    </th>
  );
}

export function ResultsTable({ runId, rows, mandatoryIds, selected, toggle, sort, onSort }: {
  runId: string; rows: ResultRow[]; mandatoryIds: string[]; selected: Set<string>; toggle: (id: string) => void;
  sort: SortState; onSort: (s: SortState) => void;
}) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th><span className="sr-only">Select</span></th>
            <SortHead id="rank" label="Rank" s={sort} onSort={onSort} />
            <SortHead id="name" label="Candidate" s={sort} onSort={onSort} />
            <SortHead id="overall" label="Score" s={sort} onSort={onSort} />
            <SortHead id="title" label="Current role" s={sort} onSort={onSort} />
            <th>Must-haves</th>
            <th>Relevant skills</th>
            <SortHead id="years_experience" label="Exp." s={sort} onSort={onSort} />
            <th>Branch</th>
            <th>Assessed</th>
            <th>Flags</th>
            <th><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.candidate_id} className={selected.has(r.candidate_id) ? "selected" : ""}>
              <td><input type="checkbox" aria-label={`Select ${r.candidate_id}`} checked={selected.has(r.candidate_id)} onChange={() => toggle(r.candidate_id)} /></td>
              <td><RankPill rank={r.rank} /></td>
              <td>
                <Link to={`/runs/${runId}/candidates/${r.candidate_id}`} className="cell-title" style={{ textDecoration: "none" }}>{r.name || r.candidate_id}</Link>
                <div className="cell-sub mono">{r.candidate_id}</div>
              </td>
              <td style={{ minWidth: 130 }}><ScoreBar value={r.overall} tone={r.rank && r.rank <= 10 ? "signal" : "ink"} />
                {r.constraint_factor < 1 && <div className="cell-sub" title={r.constraints_triggered.join(", ")}>× {r.constraint_factor.toFixed(2)} conditions</div>}</td>
              <td><div>{r.title}</div><div className="cell-sub">{r.company} · {r.city || r.location}</div></td>
              <td><CoverageDots coverage={r.requirement_coverage} ids={mandatoryIds} /><div className="cell-sub mono">{r.mandatory_met}/{r.mandatory_total}</div></td>
              <td style={{ maxWidth: 220 }}><div className="chips">{r.relevant_skills.slice(0, 4).map((s) => <span className="chip data" key={s}>{s}</span>)}
                {r.relevant_skills.length > 4 && <span className="chip">+{r.relevant_skills.length - 4}</span>}</div></td>
              <td className="num">{num(r.years_experience)}</td>
              <td style={{ maxWidth: 160 }} className="cell-sub">{r.fields_of_study || "-"}</td>
              <td className="num">{r.assessment_mean !== null ? `${Math.round(r.assessment_mean)}` : <span className="faint">-</span>}</td>
              <td><FlagIcons codes={r.flag_codes} critical={r.critical_flag} /></td>
              <td><Link to={`/runs/${runId}/candidates/${r.candidate_id}`} className="btn btn-sm btn-ghost" aria-label="Open profile"><Eye size={15} /></Link></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CandidateCard({ runId, r, mandatoryIds, selected, toggle }: {
  runId: string; r: ResultRow; mandatoryIds: string[]; selected: boolean; toggle: () => void;
}) {
  const [e, setE] = useState<Explanation | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let alive = true;
    api.candidate(runId, r.candidate_id).then((x) => alive && setE(x)).catch(() => alive && setErr(true));
    return () => { alive = false; };
  }, [runId, r.candidate_id]);
  return (
    <article className="cand-card" style={selected ? { borderColor: "var(--signal)" } : undefined}>
      <div className="spread">
        <div className="row"><RankPill rank={r.rank} /><input type="checkbox" aria-label={`Select ${r.candidate_id}`} checked={selected} onChange={toggle} /></div>
        <FlagIcons codes={r.flag_codes} critical={r.critical_flag} />
      </div>
      <div>
        <h3><Link to={`/runs/${runId}/candidates/${r.candidate_id}`} style={{ textDecoration: "none" }}>{r.name || r.candidate_id}</Link></h3>
        <div className="cell-sub">{r.title} · {r.company} · {num(r.years_experience)} yrs · {r.city || r.location}</div>
      </div>
      <ScoreBar value={r.overall} tone={r.rank && r.rank <= 10 ? "signal" : "ink"} />
      <div className="summary">{e ? e.summary : err ? <span className="faint">Explanation unavailable.</span> : <span className="faint">Loading evidence…</span>}</div>
      {e && e.concerns.length > 0 && <div className="chips">{e.concerns.slice(0, 2).map((c) => <span className="chip warn" key={c}>{c}</span>)}</div>}
      <div className="spread">
        <span className="row cell-sub"><CoverageDots coverage={r.requirement_coverage} ids={mandatoryIds} /> {r.mandatory_met}/{r.mandatory_total} must-haves</span>
        <span className="cell-sub">evidence {pct(r.evidence_completeness)}</span>
      </div>
      <div className="chips">{r.relevant_skills.slice(0, 5).map((s) => <span className="chip data" key={s}>{s}</span>)}</div>
    </article>
  );
}

export function ResultCards(props: { runId: string; rows: ResultRow[]; mandatoryIds: string[]; selected: Set<string>; toggle: (id: string) => void }) {
  return (
    <div className="cards">
      {props.rows.map((r) => (
        <CandidateCard key={r.candidate_id} runId={props.runId} r={r} mandatoryIds={props.mandatoryIds}
          selected={props.selected.has(r.candidate_id)} toggle={() => props.toggle(r.candidate_id)} />
      ))}
    </div>
  );
}

function CheckList({ items, values, onChange, label }: { items: { value: string; count: number }[]; values: string[]; onChange: (v: string[]) => void; label: string }) {
  if (!items.length) return <div className="cell-sub">No values</div>;
  return (
    <div className="filter-list" role="group" aria-label={label}>
      {items.map((it) => (
        <label className="check" key={it.value}>
          <span className="row" style={{ gap: 6 }}>
            <input type="checkbox" checked={values.includes(it.value)}
              onChange={(e) => onChange(e.target.checked ? [...values, it.value] : values.filter((v) => v !== it.value))} />
            {it.value}
          </span>
          <span className="faint mono" style={{ fontSize: 11 }}>{it.count}</span>
        </label>
      ))}
    </div>
  );
}

export function FilterPanel({ facets, q, setQ, mandatoryTotal }: {
  facets: Facets | null; q: ResultQuery; setQ: (q: ResultQuery) => void; mandatoryTotal: number;
}) {
  const upd = (patch: Partial<ResultQuery>) => setQ({ ...q, ...patch, page: 1 });
  const active = ["min_score", "max_score", "min_years", "max_years", "countries", "cities", "branches", "skills", "flags", "min_mandatory"]
    .some((k) => { const v = (q as Record<string, unknown>)[k]; return Array.isArray(v) ? v.length > 0 : v !== undefined; });
  return (
    <aside className="card filters" aria-label="Filters">
      <div className="card-head"><h2>Filters</h2>
        {active && <button className="btn btn-sm btn-ghost" onClick={() => setQ({ page: 1, page_size: q.page_size, sort: q.sort, order: q.order, q: q.q, view: q.view })}>Clear</button>}</div>
      <div className="filter-group">
        <span className="label">Score (0-100)</span>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input className="input mono" type="number" min={0} max={100} placeholder="min" aria-label="Minimum score" value={q.min_score !== undefined ? Math.round(q.min_score * 100) : ""}
            onChange={(e) => upd({ min_score: e.target.value === "" ? undefined : Number(e.target.value) / 100 })} />
          <input className="input mono" type="number" min={0} max={100} placeholder="max" aria-label="Maximum score" value={q.max_score !== undefined ? Math.round(q.max_score * 100) : ""}
            onChange={(e) => upd({ max_score: e.target.value === "" ? undefined : Number(e.target.value) / 100 })} />
        </div>
      </div>
      <div className="filter-group">
        <span className="label">Years of experience</span>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input className="input mono" type="number" min={0} placeholder="min" aria-label="Minimum years" value={q.min_years ?? ""}
            onChange={(e) => upd({ min_years: e.target.value === "" ? undefined : Number(e.target.value) })} />
          <input className="input mono" type="number" min={0} placeholder="max" aria-label="Maximum years" value={q.max_years ?? ""}
            onChange={(e) => upd({ max_years: e.target.value === "" ? undefined : Number(e.target.value) })} />
        </div>
      </div>
      <div className="filter-group">
        <span className="label">Must-haves met (at least)</span>
        <select className="select" value={q.min_mandatory ?? ""} onChange={(e) => upd({ min_mandatory: e.target.value === "" ? undefined : Number(e.target.value) })}>
          <option value="">Any</option>
          {Array.from({ length: mandatoryTotal }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n} of {mandatoryTotal}</option>)}
        </select>
      </div>
      <div className="filter-group">
        <span className="label">Integrity</span>
        <select className="select" value={q.flags ?? ""} onChange={(e) => upd({ flags: (e.target.value || undefined) as ResultQuery["flags"] })}>
          <option value="">All candidates</option>
          <option value="none">No findings ({facets?.flags.none ?? 0})</option>
          <option value="warning">Has warnings ({facets?.flags.warning ?? 0})</option>
          <option value="critical">Critical ({facets?.flags.critical ?? 0})</option>
        </select>
      </div>
      <div className="filter-group"><span className="label">Relevant skills (all of)</span>
        <CheckList label="Skills" items={facets?.skills ?? []} values={q.skills ?? []} onChange={(skills) => upd({ skills })} /></div>
      <div className="filter-group"><span className="label">Academic branch</span>
        <CheckList label="Branches" items={facets?.branches ?? []} values={q.branches ?? []} onChange={(branches) => upd({ branches })} /></div>
      <div className="filter-group"><span className="label">Country</span>
        <CheckList label="Countries" items={facets?.countries ?? []} values={q.countries ?? []} onChange={(countries) => upd({ countries })} /></div>
      <div className="filter-group"><span className="label">City</span>
        <CheckList label="Cities" items={facets?.cities ?? []} values={q.cities ?? []} onChange={(cities) => upd({ cities })} /></div>
    </aside>
  );
}
