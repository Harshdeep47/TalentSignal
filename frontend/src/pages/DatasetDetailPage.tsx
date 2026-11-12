import { useNavigate, useParams } from "react-router-dom";
import { RefreshCw, Sparkles, Trash2, XCircle } from "lucide-react";
import { api } from "../services/api";
import { useAsync, usePoll } from "../hooks/useAsync";
import { ErrorBox, fmtBytes, fmtDate, Progress, Spinner, useToast } from "../components/ui";

const SEVERITY_TONE: Record<string, string> = { critical: "risk", warning: "warn", info: "data" };

export default function DatasetDetailPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { data: d, error, loading, reload } = useAsync(() => api.dataset(id), [id]);
  usePoll(reload, 1500, !!d && (d.status === "indexing" || d.status === "pending"));

  if (loading && !d) return <Spinner />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!d) return null;
  const q = d.quality;
  const maxHist = q ? Math.max(...q.experience_histogram.map(([, c]) => c), 1) : 1;

  const del = async () => {
    if (!confirm(`Delete dataset "${d.name}" and all its ranking runs? This cannot be undone.`)) return;
    try {
      await api.deleteDataset(d.id);
      toast("Dataset deleted.");
      nav("/datasets");
    } catch (e) {
      toast((e as Error).message, true);
    }
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow">Dataset</div>
          <h1>{d.name}</h1>
          <p>{fmtBytes(d.size_bytes)} · added {fmtDate(d.created_at)} · {d.shared ? "shared library dataset" : "private to this session"}
            {d.fingerprint && <> · <span className="mono" style={{ fontSize: 12 }}>{d.fingerprint.slice(0, 24)}…</span></>}</p>
        </div>
        <div className="row">
          {d.status === "ready" && <button className="btn btn-primary" onClick={() => nav(`/rank/new?dataset=${d.id}`)}><Sparkles size={15} /> Rank this pool</button>}
          {(d.status === "failed" || d.status === "ready") && <button className="btn" onClick={() => api.reindex(d.id).then(reload)}><RefreshCw size={15} /> Re-index</button>}
          {!d.shared && <button className="btn btn-danger" onClick={del}><Trash2 size={15} /> Delete</button>}
        </div>
      </div>

      {(d.status === "indexing" || d.status === "pending") && d.job && (
        <section className="card card-pad">
          <div className="spread"><strong>{d.job.message}</strong><span className="mono">{Math.round(d.job.progress * 100)}%</span></div>
          <div style={{ margin: "8px 0" }}><Progress value={d.job.progress} /></div>
          <button className="btn btn-sm" onClick={() => api.cancelJob(d.job!.id).then(reload)}><XCircle size={14} /> Cancel</button>
        </section>
      )}
      {d.status === "failed" && <ErrorBox error={d.error ?? "Indexing failed"} />}

      {q && d.meta && (
        <>
          <div className="grid grid-4">
            <div className="card stat"><div className="stat-label">Valid records</div><div className="stat-value">{q.valid_records.toLocaleString()}</div></div>
            <div className="card stat"><div className="stat-label">Rejected rows</div><div className="stat-value">{q.rejected_records.toLocaleString()}</div></div>
            <div className="card stat"><div className="stat-label">Unique text segments</div><div className="stat-value">{q.unique_text_segments.toLocaleString()}</div></div>
            <div className="card stat"><div className="stat-label">Activity reference date</div><div className="stat-value" style={{ fontSize: 20 }}>{d.meta.as_of_date}</div></div>
          </div>

          <div className="grid grid-2">
            <section className="card card-pad">
              <h2>Integrity findings</h2>
              <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>Critical findings hold a candidate for human review; they are not
                treated as proof of fraud. Info items are data-quality notes with no ranking effect.</p>
              <table className="data">
                <thead><tr><th>Check</th><th>Severity</th><th>Candidates</th></tr></thead>
                <tbody>
                  {q.integrity.length === 0 && <tr><td colSpan={3} className="muted">No findings.</td></tr>}
                  {q.integrity.map((r) => (
                    <tr key={r.code + r.severity}><td>{r.code.replace(/_/g, " ")}</td>
                      <td><span className={`chip ${SEVERITY_TONE[r.severity]}`}>{r.severity}</span></td>
                      <td className="num">{r.count.toLocaleString()}</td></tr>
                  ))}
                  {q.duplicates > 0 && <tr><td>duplicate profiles</td><td><span className="chip warn">warning</span></td><td className="num">{q.duplicates}</td></tr>}
                </tbody>
              </table>
            </section>
            <section className="card card-pad">
              <h2>Missing values</h2>
              <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>Missing optional fields are treated as unknown, never as negative evidence.</p>
              <table className="data">
                <thead><tr><th>Field</th><th>Missing</th></tr></thead>
                <tbody>
                  {Object.entries(q.missing_values).filter(([, v]) => v.count > 0).map(([k, v]) => (
                    <tr key={k}><td>{k.replace(/_/g, " ")}</td><td className="num">{v.pct}% <span className="faint">({v.count.toLocaleString()})</span></td></tr>
                  ))}
                </tbody>
              </table>
            </section>
          </div>

          <div className="grid grid-3">
            <section className="card card-pad">
              <h2>Years of experience</h2>
              <div className="histo" aria-label="experience histogram">
                {q.experience_histogram.map(([y, c]) => <span key={y} title={`${y} yrs: ${c}`} style={{ height: `${(c / maxHist) * 100}%` }} />)}
              </div>
              <div className="spread faint mono" style={{ fontSize: 11 }}><span>{q.experience_histogram[0]?.[0] ?? 0}y</span><span>{q.experience_histogram.at(-1)?.[0] ?? 0}y</span></div>
            </section>
            <section className="card card-pad">
              <h2>Most common titles</h2>
              {q.top_titles.slice(0, 8).map(([t, c]) => (
                <div key={t} className="spread" style={{ fontSize: 13, padding: "2px 0" }}><span>{t}</span><span className="num faint">{c.toLocaleString()}</span></div>
              ))}
            </section>
            <section className="card card-pad">
              <h2>Countries</h2>
              {q.countries.slice(0, 8).map(([t, c]) => (
                <div key={t} className="spread" style={{ fontSize: 13, padding: "2px 0" }}><span>{t}</span><span className="num faint">{c.toLocaleString()}</span></div>
              ))}
            </section>
          </div>

          {(q.warnings.length > 0 || q.rejected_examples.length > 0) && (
            <section className="card card-pad">
              <h2>Validation notes</h2>
              {q.rejected_examples.length > 0 && (
                <details open><summary><strong>Rejected rows</strong> (first {q.rejected_examples.length})</summary>
                  <ul className="list-plain">{q.rejected_examples.map((r) => <li key={r.row}>Row {r.row}: {r.reason}</li>)}</ul>
                </details>
              )}
              {q.warnings.length > 0 && (
                <details><summary><strong>Repairs applied</strong> ({q.warnings.length} kinds)</summary>
                  <ul className="list-plain">{q.warnings.map((w) => <li key={w.issue}>{w.issue} - {w.count.toLocaleString()}x</li>)}</ul>
                </details>
              )}
            </section>
          )}
          <div className="faint" style={{ fontSize: 12 }}>
            Embedding model: {d.meta.embedding_model ?? "not available (lexical evidence only)"} · index build{" "}
            {d.meta.timings?.total_s ? `${d.meta.timings.total_s}s` : "-"}
          </div>
        </>
      )}
    </div>
  );
}
