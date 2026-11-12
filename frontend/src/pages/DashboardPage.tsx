import { Link } from "react-router-dom";
import { ArrowRight, Database, Sparkles } from "lucide-react";
import { api } from "../services/api";
import { useAsync, usePoll } from "../hooks/useAsync";
import { Empty, ErrorBox, fmtDate, Progress, Spinner } from "../components/ui";
import type { Dataset } from "../types/api";

export function DatasetHealth({ d }: { d: Dataset }) {
  const tone = d.status === "ready" ? "ok" : d.status === "failed" ? "risk" : "warn";
  return (
    <div className="spread" style={{ padding: "10px 0", borderBottom: "1px solid #efece5" }}>
      <div style={{ minWidth: 0 }}>
        <Link to={`/datasets/${d.id}`} className="cell-title" style={{ textDecoration: "none" }}>{d.name}</Link>
        <div className="cell-sub">
          {d.shared ? "Shared library" : d.source_kind === "upload" ? "Uploaded" : "Imported"} ·{" "}
          {d.n_candidates ? `${d.n_candidates.toLocaleString()} candidates` : "not indexed yet"}
        </div>
        {(d.status === "indexing" || d.status === "pending") && d.job && (
          <div style={{ marginTop: 6, width: 260 }}><Progress value={d.job.progress} /><div className="cell-sub">{d.job.message}</div></div>
        )}
        {d.status === "failed" && <div className="cell-sub" style={{ color: "var(--risk)" }}>{d.error}</div>}
      </div>
      <span className={`chip ${tone}`}>{d.status}</span>
    </div>
  );
}

export default function DashboardPage() {
  const { data, error, loading, reload } = useAsync(() => api.dashboard(), []);
  const busy = !!data?.datasets.some((d) => d.status === "indexing" || d.status === "pending");
  usePoll(reload, 2000, busy);

  if (loading && !data) return <Spinner label="Loading dashboard" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;
  const t = data.totals;
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow">Overview</div>
          <h1>Candidate intelligence workspace</h1>
          <p>Rank candidate pools against a job description using evidence from skills, assessments, career history
            and platform signals - with every score explained.</p>
        </div>
        <Link to="/rank/new" className="btn btn-primary"><Sparkles size={16} /> New ranking</Link>
      </div>

      <div className="grid grid-4">
        <div className="card stat"><div className="stat-label">Candidates indexed</div><div className="stat-value">{t.candidates.toLocaleString()}</div></div>
        <div className="card stat"><div className="stat-label">Datasets ready</div><div className="stat-value">{t.ready_datasets}<span className="faint" style={{ fontSize: 16 }}> / {t.datasets}</span></div></div>
        <div className="card stat"><div className="stat-label">Ranking runs</div><div className="stat-value">{t.runs}</div></div>
        <div className="card stat"><div className="stat-label">Saved shortlists</div><div className="stat-value">{t.shortlists}</div></div>
      </div>

      <div className="grid grid-2">
        <section className="card">
          <div className="card-head"><h2>Datasets</h2><Link to="/datasets" className="btn btn-sm btn-ghost">Manage <ArrowRight size={14} /></Link></div>
          <div style={{ padding: "4px 20px 12px" }}>
            {data.datasets.length === 0 ? (
              <Empty title="No datasets yet" icon={<Database />}>
                <Link to="/datasets" className="btn btn-sm">Upload or import candidates</Link>
              </Empty>
            ) : data.datasets.map((d) => <DatasetHealth key={d.id} d={d} />)}
          </div>
        </section>

        <section className="card">
          <div className="card-head"><h2>Recent ranking runs</h2><Link to="/history" className="btn btn-sm btn-ghost">History <ArrowRight size={14} /></Link></div>
          <div style={{ padding: "4px 20px 12px" }}>
            {data.recent_runs.length === 0 ? (
              <Empty title="No rankings yet">Start with a job description - the system extracts requirements you can review.</Empty>
            ) : data.recent_runs.map((r) => (
              <div key={r.id} className="spread" style={{ padding: "10px 0", borderBottom: "1px solid #efece5" }}>
                <div style={{ minWidth: 0 }}>
                  <Link to={`/runs/${r.id}`} className="cell-title" style={{ textDecoration: "none" }}>{r.jd_title}</Link>
                  <div className="cell-sub">{r.dataset_name} · {fmtDate(r.created_at)}</div>
                </div>
                <span className={`chip ${r.status === "ready" ? "ok" : r.status === "failed" ? "risk" : "warn"}`}>
                  {r.status === "ready" ? `${r.n_results?.toLocaleString()} ranked` : r.status}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="card">
        <div className="card-head"><h2>Recent activity</h2></div>
        <div style={{ padding: "6px 20px 14px" }}>
          {data.activity.length === 0 ? <div className="muted">Nothing yet.</div> : (
            <ul className="list-plain" style={{ listStyle: "none", padding: 0 }}>
              {data.activity.map((a, i) => (
                <li key={i} className="spread" style={{ padding: "5px 0" }}>
                  <span>{a.message}</span><span className="faint mono" style={{ fontSize: 12 }}>{fmtDate(a.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}
