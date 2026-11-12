import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { RotateCcw, Trash2 } from "lucide-react";
import { api } from "../services/api";
import { useAsync, usePoll } from "../hooks/useAsync";
import { bus, Empty, ErrorBox, fmtDate, Spinner, useToast } from "../components/ui";

export default function HistoryPage() {
  const nav = useNavigate();
  const toast = useToast();
  const { data, error, loading, reload } = useAsync(() => api.runs(500), []);
  const datasets = useAsync(() => api.datasets(), []);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [ds, setDs] = useState("");
  usePoll(reload, 2000, !!data?.some((r) => r.status === "queued" || r.status === "running"));

  const rows = useMemo(() => (data ?? []).filter((r) =>
    (!q || `${r.jd_title} ${r.name} ${r.dataset_name}`.toLowerCase().includes(q.toLowerCase())) &&
    (!status || r.status === status) && (!ds || r.dataset_id === ds)), [data, q, status, ds]);

  const del = async (id: string, title: string) => {
    if (!confirm(`Delete the run "${title}"? Its saved shortlists are deleted too.`)) return;
    try { await api.deleteRun(id); bus.emit("runs"); bus.emit("shortlists"); reload(); } catch (e) { toast((e as Error).message, true); }
  };

  return (
    <div className="stack">
      <div className="page-head"><div><div className="eyebrow">History</div><h1>Ranking history</h1>
        <p>Every run stores the exact job specification it used, so results can be reproduced or re-run after editing.</p></div></div>
      <section className="card">
        <div className="toolbar">
          <input className="input" style={{ maxWidth: 320 }} placeholder="Search runs" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search runs" />
          <select className="select" style={{ width: 160 }} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
            <option value="">Any status</option>{["ready", "running", "queued", "failed", "cancelled"].map((s) => <option key={s}>{s}</option>)}</select>
          <select className="select" style={{ width: 240 }} value={ds} onChange={(e) => setDs(e.target.value)} aria-label="Dataset">
            <option value="">All datasets</option>{(datasets.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
        </div>
        {loading && !data && <Spinner />}
        {error && <ErrorBox error={error} onRetry={reload} />}
        {data && rows.length === 0 && <Empty title="No runs found"><Link to="/rank/new" className="btn btn-sm">Start a ranking</Link></Empty>}
        {rows.length > 0 && (
          <div className="table-wrap"><table className="data">
            <thead><tr><th>Job</th><th>Dataset</th><th>Shortlist</th><th>Scored</th><th>Status</th><th>Created</th><th /></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.id}>
                <td><Link to={`/runs/${r.id}`} className="cell-title" style={{ textDecoration: "none" }}>{r.jd_title}</Link><div className="cell-sub">{r.name}</div></td>
                <td>{r.dataset_name}</td>
                <td className="num">{r.shortlist_size ? `top ${r.shortlist_size.toLocaleString()}` : "all eligible"}</td>
                <td className="num">{r.n_candidates?.toLocaleString() ?? "-"}</td>
                <td><span className={`chip ${r.status === "ready" ? "ok" : r.status === "failed" ? "risk" : "warn"}`}>{r.status}</span></td>
                <td className="cell-sub">{fmtDate(r.created_at)}</td>
                <td><div className="row" style={{ flexWrap: "nowrap" }}>
                  <button className="btn btn-sm btn-ghost" title="Re-run with the same specification" onClick={() => api.rerun(r.id).then((n) => { bus.emit("runs"); nav(`/runs/${n.id}`); }).catch((e) => toast(e.message, true))}><RotateCcw size={14} /></button>
                  <button className="btn btn-sm btn-ghost btn-danger" title="Delete" onClick={() => del(r.id, r.jd_title)}><Trash2 size={14} /></button></div></td>
              </tr>))}</tbody></table></div>
        )}
      </section>
    </div>
  );
}
