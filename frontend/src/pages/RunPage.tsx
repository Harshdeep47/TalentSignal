import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Columns3, Download, LayoutGrid, ListPlus, RotateCcw, Rows3, Search, XCircle } from "lucide-react";
import { api, download, type ResultQuery } from "../services/api";
import { useAsync, useDebounced, usePoll } from "../hooks/useAsync";
import { bus, Empty, ErrorBox, fmtDate, Menu, Modal, Progress, Segmented, Spinner, useToast } from "../components/ui";
import { FilterPanel, ResultCards, ResultsTable, type SortState } from "../components/Results";
import type { Facets, Page, ResultRow, Run } from "../types/api";

const COMPONENT_COLORS: Record<string, string> = {
  requirements: "#14213d", role_fit: "#2b6f8e", semantic: "#e4572e", lexical: "#9aa3b8",
  experience: "#6c8f3a", engagement: "#b7790a", logistics: "#7d5ba6",
};

function RunSummaryPanel({ run }: { run: Run }) {
  const s = run.summary!;
  const max = Math.max(...s.score_histogram.counts, 1);
  const shortlisted = run.n_results ?? 0;
  return (
    <div className="grid grid-3">
      <section className="card card-pad">
        <h2>Score distribution <span className="muted" style={{ fontWeight: 400 }}>· all eligible</span></h2>
        <div className="histo">{s.score_histogram.counts.map((c, i) => (
          <span key={i} title={`${(s.score_histogram.edges[i] * 100).toFixed(0)}-${(s.score_histogram.edges[i + 1] * 100).toFixed(0)}: ${c.toLocaleString()}`}
            style={{ height: `${(c / max) * 100}%`, opacity: c ? 0.85 : 0.15 }} />))}</div>
        <div className="spread faint mono" style={{ fontSize: 11 }}><span>0</span><span>50</span><span>100</span></div>
      </section>
      <section className="card card-pad">
        <h2>Requirements met in shortlist</h2>
        {s.requirements.slice(0, 7).map((r) => (
          <div key={r.id} className="spread" style={{ fontSize: 12.5, padding: "2px 0", gap: 12 }}>
            <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {r.importance === "mandatory" ? <strong>{r.label}</strong> : r.label}</span>
            <span className="row" style={{ flexWrap: "nowrap", width: 120 }}>
              <span className="bar ok"><span style={{ width: `${shortlisted ? (r.met_in_shortlist / shortlisted) * 100 : 0}%` }} /></span>
              <span className="mono faint" style={{ minWidth: 34, textAlign: "right" }}>{r.met_in_shortlist}</span></span>
          </div>
        ))}
      </section>
      <section className="card card-pad">
        <h2>How scores were composed</h2>
        <div className="stackbar" style={{ marginBottom: 8 }}>
          {Object.entries(s.context.weights_used).map(([k, w]) => <span key={k} title={`${k}: ${(w * 100).toFixed(0)}%`} style={{ width: `${w * 100}%`, background: COMPONENT_COLORS[k] }} />)}
        </div>
        <div className="legend">{Object.entries(s.context.weights_used).map(([k, w]) => (
          <span key={k}><i style={{ background: COMPONENT_COLORS[k] }} />{k.replace("_", " ")} {(w * 100).toFixed(0)}%</span>))}</div>
        <div className="divider" />
        <div className="cell-sub">Activity measured as of {s.context.as_of_date} · semantic model: {s.context.embedding_model ?? "off"}</div>
        {s.context.notes.map((n) => <div key={n} className="cell-sub" style={{ color: "var(--caution)" }}>{n}</div>)}
      </section>
    </div>
  );
}

export default function RunPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const runQ = useAsync(() => api.run(id), [id]);
  const run = runQ.data;
  const pending = !!run && (run.status === "queued" || run.status === "running");
  usePoll(runQ.reload, 1000, pending);
  useEffect(() => { if (run?.status === "ready") bus.emit("runs"); }, [run?.status]);

  const [layout, setLayout] = useState<"table" | "cards">("table");
  const [query, setQuery] = useState<ResultQuery>({ page: 1, page_size: 50, sort: "rank", order: "asc", view: "shortlist" });
  const [search, setSearch] = useState("");
  const q = useDebounced(search, 300);
  const [page, setPage] = useState<Page<ResultRow> | null>(null);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [shortlistModal, setShortlistModal] = useState(false);

  const effective = useMemo(() => ({ ...query, q }), [query, q]);
  useEffect(() => { setQuery((x) => ({ ...x, page: 1 })); }, [q]);
  useEffect(() => {
    if (run?.status !== "ready") return;
    let alive = true;
    api.results(id, effective).then((p) => alive && (setPage(p), setLoadErr(null))).catch((e) => alive && setLoadErr(e.message));
    return () => { alive = false; };
  }, [id, run?.status, effective]);
  useEffect(() => {
    if (run?.status !== "ready") return;
    api.facets(id, query.view === "all" ? "all" : "shortlist").then(setFacets).catch(() => setFacets(null));
  }, [id, run?.status, query.view]);

  const mandatoryIds = useMemo(() => (run?.spec?.requirements ?? []).filter((r) => r.importance === "mandatory").map((r) => r.id), [run?.spec]);
  const toggle = (cid: string) => setSelected((s) => { const n = new Set(s); n.has(cid) ? n.delete(cid) : n.add(cid); return n; });
  const doExport = async (format: string, withExpl = false) => {
    try {
      await download(`/runs/${id}/export`, { format, scope: query.view === "all" ? "all" : "shortlist", include_explanations: withExpl,
        candidate_ids: selected.size ? [...selected] : undefined });
    } catch (e) { toast((e as Error).message, true); }
  };

  if (runQ.loading && !run) return <Spinner label="Loading run" />;
  if (runQ.error) return <ErrorBox error={runQ.error} onRetry={runQ.reload} />;
  if (!run) return null;

  const sort: SortState = { sort: query.sort ?? "rank", order: query.order ?? "asc" };
  const totalPages = page ? Math.max(1, Math.ceil(page.total / page.page_size)) : 1;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow">Ranking run</div>
          <h1>{run.jd_title}</h1>
          <p>{run.dataset_name} · {fmtDate(run.created_at)} · {run.shortlist_size ? `Top ${run.shortlist_size.toLocaleString()}` : "All eligible candidates"}
            {run.n_candidates ? ` · ${run.n_candidates.toLocaleString()} scored, ${run.n_eligible?.toLocaleString()} eligible` : ""}</p>
        </div>
        {run.status === "ready" && (
          <div className="row">
            <button className="btn" onClick={() => api.rerun(run.id).then((r) => { bus.emit("runs"); nav(`/runs/${r.id}`); })}><RotateCcw size={15} /> Re-run</button>
            <Menu label={<><Download size={15} /> Export{selected.size ? ` (${selected.size})` : ""}</>}>
              {(close) => <>
                {["csv", "xlsx", "json", "jsonl", "parquet"].map((f) => <button key={f} onClick={() => { close(); doExport(f); }}>{f.toUpperCase()}</button>)}
                <button onClick={() => { close(); doExport("csv", true); }}>CSV with explanations (≤500 rows)</button>
                <button onClick={() => { close(); doExport("pdf"); }}>PDF shortlist report</button>
                <div className="menu-sep" />
                <button onClick={() => { close(); download(`/runs/${id}/export/competition`).catch((e) => toast(e.message, true)); }}>
                  Competition CSV (exactly 100, validated)</button>
              </>}
            </Menu>
          </div>
        )}
      </div>

      {pending && run.job && (
        <section className="card card-pad">
          <div className="spread"><strong>{run.job.message}</strong><span className="mono">{Math.round(run.job.progress * 100)}%</span></div>
          <div style={{ margin: "8px 0" }}><Progress value={run.job.progress} /></div>
          <button className="btn btn-sm" onClick={() => api.cancelJob(run.job!.id).then(runQ.reload)}><XCircle size={14} /> Cancel</button>
        </section>
      )}
      {(run.status === "failed" || run.status === "cancelled") && <ErrorBox error={run.error ?? `Run ${run.status}.`} />}

      {run.status === "ready" && run.summary && <RunSummaryPanel run={run} />}

      {run.status === "ready" && (
        <div className="results-layout">
          <FilterPanel facets={facets} q={query} setQ={setQuery} mandatoryTotal={mandatoryIds.length} />
          <section className="card" style={{ minWidth: 0 }}>
            <div className="toolbar">
              <div className="search"><Search size={15} />
                <input className="input" placeholder="Search name, title, company, skill or ID" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search results" /></div>
              <Segmented label="Which candidates" value={query.view ?? "shortlist"} onChange={(v) => setQuery({ ...query, view: v, page: 1 })}
                options={[{ value: "shortlist", label: "Shortlist" }, { value: "held", label: `Held for review (${facets?.held_for_review ?? 0})` }, { value: "all", label: "All" }]} />
              <Segmented label="Layout" value={layout} onChange={setLayout}
                options={[{ value: "table", label: <Rows3 size={15} aria-label="Table" /> }, { value: "cards", label: <LayoutGrid size={15} aria-label="Cards" /> }]} />
            </div>
            {selected.size > 0 && (
              <div className="toolbar" style={{ background: "#fdf3ef" }}>
                <strong>{selected.size} selected</strong>
                <button className="btn btn-sm btn-ink" disabled={selected.size < 2 || selected.size > 6}
                  onClick={() => nav(`/runs/${id}/compare?ids=${[...selected].join(",")}`)}><Columns3 size={14} /> Compare (2-6)</button>
                <button className="btn btn-sm" onClick={() => setShortlistModal(true)}><ListPlus size={14} /> Save to shortlist</button>
                <button className="btn btn-sm btn-ghost" onClick={() => setSelected(new Set())}>Clear</button>
              </div>
            )}
            {loadErr && <div style={{ padding: 14 }}><ErrorBox error={loadErr} /></div>}
            {!page && !loadErr && <Spinner label="Loading candidates" />}
            {page && page.items.length === 0 && <Empty title="No candidates match">Try removing a filter.</Empty>}
            {page && page.items.length > 0 && (layout === "table"
              ? <ResultsTable runId={id} rows={page.items} mandatoryIds={mandatoryIds} selected={selected} toggle={toggle} sort={sort}
                  onSort={(s) => setQuery({ ...query, ...s, page: 1 })} />
              : <ResultCards runId={id} rows={page.items} mandatoryIds={mandatoryIds} selected={selected} toggle={toggle} />)}
            {page && page.total > 0 && (
              <div className="pager">
                <span className="muted">{page.total.toLocaleString()} candidates · page {page.page} of {totalPages}</span>
                <div className="row">
                  <select className="select" style={{ width: 110 }} value={query.page_size} aria-label="Rows per page"
                    onChange={(e) => setQuery({ ...query, page_size: Number(e.target.value), page: 1 })}>
                    {[25, 50, 100, 200].map((n) => <option key={n} value={n}>{n} / page</option>)}
                  </select>
                  <button className="btn btn-sm" disabled={page.page <= 1} onClick={() => setQuery({ ...query, page: page.page - 1 })}>Previous</button>
                  <button className="btn btn-sm" disabled={page.page >= totalPages} onClick={() => setQuery({ ...query, page: page.page + 1 })}>Next</button>
                </div>
              </div>
            )}
          </section>
        </div>
      )}
      {shortlistModal && <SaveShortlistModal runId={id} ids={[...selected]} onClose={() => setShortlistModal(false)} />}
    </div>
  );
}

function SaveShortlistModal({ runId, ids, onClose }: { runId: string; ids: string[]; onClose: () => void }) {
  const toast = useToast();
  const lists = useAsync(() => api.shortlists(), []);
  const existing = (lists.data ?? []).filter((s) => s.run_id === runId);
  const [name, setName] = useState("");
  const [target, setTarget] = useState("new");
  const save = async () => {
    try {
      if (target === "new") await api.createShortlist(runId, name || "Shortlist", ids);
      else for (const cid of ids) await api.addToShortlist(target, cid);
      bus.emit("shortlists");
      toast(`Saved ${ids.length} candidate(s).`);
      onClose();
    } catch (e) { toast((e as Error).message, true); }
  };
  return (
    <Modal title={`Save ${ids.length} candidate(s) to a shortlist`} onClose={onClose}>
      <div className="stack" style={{ gap: 10 }}>
        <select className="select" value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Shortlist">
          <option value="new">New shortlist…</option>
          {existing.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.size})</option>)}
        </select>
        {target === "new" && <input className="input" placeholder="Shortlist name" value={name} onChange={(e) => setName(e.target.value)} autoFocus aria-label="Shortlist name" />}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={save}>Save</button>
        </div>
      </div>
    </Modal>
  );
}
