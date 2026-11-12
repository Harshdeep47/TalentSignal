import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Columns3, Download, Trash2 } from "lucide-react";
import { api, download } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { bus, Empty, ErrorBox, fmtDate, Menu, RankPill, ScoreBar, Spinner, useToast } from "../components/ui";
import type { ResultRow } from "../types/api";

export function ShortlistsPage() {
  const { data, error, loading, reload } = useAsync(() => api.shortlists(), []);
  if (loading && !data) return <Spinner />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  return (
    <div className="stack">
      <div className="page-head"><div><div className="eyebrow">Decisions</div><h1>Saved shortlists</h1>
        <p>Named sets of candidates from a ranking run, with your notes. Select candidates on a results page to add them.</p></div></div>
      <section className="card">
        {data && data.length === 0 ? <Empty title="No shortlists yet">Open a ranking run, select candidates and choose "Save to shortlist".</Empty> : (
          <table className="data"><thead><tr><th>Shortlist</th><th>Job</th><th>Candidates</th><th>Created</th></tr></thead>
            <tbody>{data?.map((s) => (
              <tr key={s.id}><td><Link className="cell-title" style={{ textDecoration: "none" }} to={`/shortlists/${s.id}`}>{s.name}</Link></td>
                <td>{s.jd_title}</td><td className="num">{s.size}</td><td className="cell-sub">{fmtDate(s.created_at)}</td></tr>))}</tbody></table>
        )}
      </section>
    </div>
  );
}

export function ShortlistDetailPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const sl = useAsync(() => api.shortlist(id), [id]);
  const [rows, setRows] = useState<Record<string, ResultRow>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});

  useEffect(() => {
    const s = sl.data;
    if (!s?.items?.length) return;
    setNotes(Object.fromEntries(s.items.map((i) => [i.candidate_id, i.note])));
    // The shortlist stores ids; candidate rows come from the run's result table.
    api.results(s.run_id, { view: "all", page_size: 200, q: "" }).then(async (first) => {
      const want = new Set(s.items!.map((i) => i.candidate_id));
      const found: Record<string, ResultRow> = {};
      first.items.forEach((r) => want.has(r.candidate_id) && (found[r.candidate_id] = r));
      for (const cid of want) {
        if (!found[cid]) {
          const p = await api.results(s.run_id, { view: "all", q: cid, page_size: 5 });
          const hit = p.items.find((r) => r.candidate_id === cid);
          if (hit) found[cid] = hit;
        }
      }
      setRows(found);
    }).catch((e) => toast(e.message, true));
  }, [sl.data, toast]);

  if (sl.loading && !sl.data) return <Spinner />;
  if (sl.error) return <ErrorBox error={sl.error} onRetry={sl.reload} />;
  const s = sl.data!;
  const items = s.items ?? [];
  const ids = items.map((i) => i.candidate_id);

  const saveNote = async (cid: string) => {
    try { await api.addToShortlist(id, cid, notes[cid] ?? ""); toast("Note saved."); } catch (e) { toast((e as Error).message, true); }
  };
  const remove = async (cid: string) => {
    try { await api.removeFromShortlist(id, cid); bus.emit("shortlists"); sl.reload(); } catch (e) { toast((e as Error).message, true); }
  };
  const del = async () => {
    if (!confirm(`Delete shortlist "${s.name}"?`)) return;
    await api.deleteShortlist(id);
    bus.emit("shortlists");
    nav("/shortlists");
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div><div className="eyebrow">Shortlist</div><h1>{s.name}</h1>
          <p>{items.length} candidates · from <Link to={`/runs/${s.run_id}`}>this ranking run</Link> · created {fmtDate(s.created_at)}</p></div>
        <div className="row">
          <button className="btn" disabled={ids.length < 2 || ids.length > 6} onClick={() => nav(`/runs/${s.run_id}/compare?ids=${ids.join(",")}`)}><Columns3 size={15} /> Compare</button>
          <Menu label={<><Download size={15} /> Export</>}>
            {(close) => ["csv", "xlsx", "json", "pdf"].map((f) => (
              <button key={f} onClick={() => { close(); download(`/runs/${s.run_id}/export`, { format: f, scope: "all", candidate_ids: ids, include_explanations: f === "csv" }).catch((e) => toast(e.message, true)); }}>
                {f.toUpperCase()}</button>))}
          </Menu>
          <button className="btn btn-danger" onClick={del}><Trash2 size={15} /> Delete</button>
        </div>
      </div>
      <section className="card">
        {items.length === 0 ? <Empty title="Empty shortlist" /> : (
          <table className="data"><thead><tr><th>Rank</th><th>Candidate</th><th>Score</th><th>Role</th><th>Note</th><th /></tr></thead>
            <tbody>{items.map((it) => {
              const r = rows[it.candidate_id];
              return (
                <tr key={it.candidate_id}>
                  <td>{r ? <RankPill rank={r.rank} /> : "-"}</td>
                  <td><Link className="cell-title" style={{ textDecoration: "none" }} to={`/runs/${s.run_id}/candidates/${it.candidate_id}`}>{r?.name ?? it.candidate_id}</Link>
                    <div className="cell-sub mono">{it.candidate_id}</div></td>
                  <td style={{ minWidth: 130 }}>{r ? <ScoreBar value={r.overall} /> : "-"}</td>
                  <td>{r ? <><div>{r.title}</div><div className="cell-sub">{r.company}</div></> : "-"}</td>
                  <td style={{ minWidth: 260 }}><textarea className="input" style={{ minHeight: 44 }} value={notes[it.candidate_id] ?? ""} aria-label="Note"
                    onChange={(e) => setNotes({ ...notes, [it.candidate_id]: e.target.value })} onBlur={() => saveNote(it.candidate_id)} /></td>
                  <td><button className="btn btn-sm btn-ghost btn-danger" aria-label="Remove" onClick={() => remove(it.candidate_id)}><Trash2 size={14} /></button></td>
                </tr>);
            })}</tbody></table>
        )}
      </section>
    </div>
  );
}
