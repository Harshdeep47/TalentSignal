import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, CheckCheck, FileText, RotateCcw, Sparkles, Trash2, UploadCloud } from "lucide-react";
import { api, uploadResumes } from "../services/api";
import { useAsync, useDebounced, usePoll } from "../hooks/useAsync";
import { ErrorBox, fmtBytes, fmtDate, Modal, Progress, Segmented, Spinner, useToast } from "../components/ui";
import type { ResumeBatch, ResumeDocStatus } from "../types/api";

const ACCEPT = ".pdf,.docx,.zip";
const PAGE = 50;

export const STATUS_LABEL: Record<ResumeDocStatus, string> = {
  queued: "Queued", processing: "Processing", needs_review: "Awaiting review", approved: "Approved",
  rejected: "Rejected", failed: "Failed", duplicate: "Duplicate",
};
const STATUS_TONE: Record<ResumeDocStatus, string> = {
  queued: "", processing: "data", needs_review: "warn", approved: "ok", rejected: "", failed: "risk", duplicate: "",
};

export function StatusChip({ status }: { status: ResumeDocStatus }) {
  return <span className={`chip ${STATUS_TONE[status]}`}>{STATUS_LABEL[status]}</span>;
}

const isBusy = (b: ResumeBatch | null | undefined) =>
  !!b && (b.counts.queued > 0 || b.counts.processing > 0 || b.job?.status === "running" || b.job?.status === "queued");

/** List of resume batches + create a new one. */
export default function ResumesPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const { data, error, loading, reload } = useAsync(() => api.resumeBatches(), []);
  const [name, setName] = useState("");
  usePoll(reload, 2000, !!data?.some(isBusy));

  const create = async () => {
    try {
      const b = await api.createResumeBatch(name.trim() || "Resumes");
      navigate(`/resumes/${b.id}`);
    } catch (e) {
      toast((e as Error).message, true);
    }
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow">Data</div>
          <h1>Resume intake</h1>
          <p>Upload PDF or DOCX resumes (or ZIP archives of them). Each resume is converted into a candidate profile in
            which every value is marked as stated in the document, inferred by a rule, or missing, with its source line.
            You review and correct the profiles, then publish the approved ones as a dataset for the normal ranking engine.</p>
        </div>
      </div>

      <section className="card card-pad">
        <h2>New batch</h2>
        <div className="row">
          <input className="input" style={{ flex: 1, maxWidth: 420 }} placeholder="Batch name, e.g. Backend hiring - November"
            value={name} onChange={(e) => setName(e.target.value)} aria-label="Batch name" maxLength={120}
            onKeyDown={(e) => e.key === "Enter" && create()} />
          <button className="btn btn-ink" onClick={create}><FileText size={15} /> Create batch</button>
        </div>
        <p className="cell-sub" style={{ marginBottom: 0 }}>Scanned (image-only) PDFs are not supported: there is no OCR, so they are
          reported as failed rather than guessed.</p>
      </section>

      <section className="card">
        <div className="card-head"><h2>Batches</h2></div>
        {loading && !data && <Spinner />}
        {error && <ErrorBox error={error} onRetry={reload} />}
        {data && data.length === 0 && <div className="muted" style={{ padding: "4px 20px 16px" }}>No resume batches yet.</div>}
        {data && data.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Batch</th><th>Uploaded</th><th>Awaiting review</th><th>Approved</th><th>Failed</th><th>Created</th></tr></thead>
              <tbody>
                {data.map((b) => (
                  <tr key={b.id}>
                    <td><Link to={`/resumes/${b.id}`} className="cell-title">{b.name}</Link>
                      {isBusy(b) && <div className="cell-sub">processing…</div>}</td>
                    <td className="mono">{b.counts.total.toLocaleString()}</td>
                    <td className="mono">{b.counts.needs_review.toLocaleString()}</td>
                    <td className="mono">{b.counts.approved.toLocaleString()}</td>
                    <td className="mono">{b.counts.failed.toLocaleString()}</td>
                    <td className="cell-sub">{fmtDate(b.created_at)}</td>
                  </tr>))}
              </tbody>
            </table>
          </div>)}
      </section>
    </div>
  );
}

type Filter = "all" | ResumeDocStatus;

/** Processing dashboard for one batch: counters, upload, documents, approve and publish. */
export function ResumeBatchPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const batch = useAsync(() => api.resumeBatch(id), [id]);
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [offset, setOffset] = useState(0);
  const docs = useAsync(() => api.resumeDocuments(id, { status: filter === "all" ? undefined : filter, q: dq || undefined,
    limit: PAGE, offset }), [id, filter, dq, offset]);
  const [upload, setUpload] = useState<{ label: string; p: number } | null>(null);
  const [over, setOver] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [pubName, setPubName] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const b = batch.data;
  const busy = isBusy(b);
  const refresh = () => { batch.reload(); docs.reload(); };
  usePoll(refresh, 1500, busy || b?.last_dataset?.status === "indexing" || b?.last_dataset?.status === "pending");

  const send = async (files: File[]) => {
    if (!files.length) return;
    const label = files.length === 1 ? files[0].name : `${files.length} files`;
    setUpload({ label, p: 0 });
    try {
      const r = await uploadResumes(id, files, (p) => setUpload({ label, p }));
      const s = r.summary;
      toast(`Received ${s.received.toLocaleString()} document(s): ${s.queued} queued, ${s.duplicate} duplicate, ${s.failed} rejected.`);
      refresh();
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setUpload(null);
    }
  };

  const act = async (fn: () => Promise<unknown>, ok: (r: any) => string) => {
    try {
      const r = await fn();
      toast(ok(r));
      refresh();
    } catch (e) {
      toast((e as Error).message, true);
    }
  };

  if (batch.loading && !b) return <Spinner />;
  if (batch.error) return <ErrorBox error={batch.error} onRetry={batch.reload} />;
  if (!b) return null;
  const c = b.counts;
  const job = b.job;
  const ds = b.last_dataset;

  return (
    <div className="stack">
      <Link to="/resumes" className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start" }}><ArrowLeft size={14} /> All batches</Link>
      <div className="page-head">
        <div>
          <div className="eyebrow">Resume batch</div>
          <h1>{b.name}</h1>
          <p>Created {fmtDate(b.created_at)}. Originals are kept unchanged; every extracted value links back to its page and line.</p>
        </div>
        <div className="row">
          <button className="btn btn-ghost btn-sm" onClick={async () => {
            if (!confirm("Delete this batch, its stored resumes and extractions? Published datasets are kept.")) return;
            try { await api.deleteResumeBatch(id); navigate("/resumes"); } catch (e) { toast((e as Error).message, true); }
          }}><Trash2 size={14} /> Delete batch</button>
        </div>
      </div>

      <div className="grid grid-4" aria-label="Processing status">
        <div className="card stat"><div className="stat-label">Uploaded</div><div className="stat-value">{c.total.toLocaleString()}</div></div>
        <div className="card stat"><div className="stat-label">Processed</div><div className="stat-value">{c.processed.toLocaleString()}
          {(c.queued + c.processing) > 0 && <span className="faint" style={{ fontSize: 14 }}> · {(c.queued + c.processing).toLocaleString()} queued</span>}</div></div>
        <div className="card stat"><div className="stat-label">Awaiting review</div><div className="stat-value">{c.needs_review.toLocaleString()}</div>
          <div className="cell-sub">{c.approved.toLocaleString()} approved · {c.rejected.toLocaleString()} rejected</div></div>
        <div className="card stat"><div className="stat-label">Failed</div><div className="stat-value">{c.failed.toLocaleString()}</div>
          <div className="cell-sub">{c.duplicate.toLocaleString()} duplicate(s) skipped</div></div>
      </div>

      {job && (job.status === "running" || job.status === "queued") && (
        <section className="card card-pad">
          <div className="spread cell-sub"><span>{job.message ?? "Processing"}</span><span className="mono">{Math.round(job.progress * 100)}%</span></div>
          <Progress value={job.progress} />
        </section>)}
      {job?.status === "failed" && <div className="banner risk">Processing stopped: {job.error}. Use “Process queue” to continue.</div>}

      <div className="grid grid-2">
        <section className="card card-pad">
          <h2>Add resumes</h2>
          <div className={`dropzone ${over ? "over" : ""}`} onClick={() => input.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); send(Array.from(e.dataTransfer.files)); }}
            role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && input.current?.click()}>
            <UploadCloud size={26} />
            <div style={{ fontWeight: 600, marginTop: 6 }}>Drop resumes or click to browse</div>
            <div className="muted" style={{ fontSize: 12 }}>PDF (with a text layer) or DOCX, up to 10 MB each - or ZIP archives of them</div>
          </div>
          <input ref={input} type="file" accept={ACCEPT} multiple hidden aria-label="Resume files"
            onChange={(e) => { send(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
          {upload && (
            <div style={{ marginTop: 12 }}>
              <div className="spread cell-sub"><span>Uploading {upload.label}</span><span className="mono">{Math.round(upload.p * 100)}%</span></div>
              <Progress value={upload.p} />
            </div>)}
        </section>

        <section className="card card-pad">
          <h2>Review and publish</h2>
          <p className="muted" style={{ marginTop: 0 }}>Only approved profiles join a ranking pool. Publishing creates a dataset that is
            indexed and ranked by the same engine as any uploaded candidate file.</p>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <button className="btn btn-ghost" disabled={!c.needs_review}
              onClick={() => act(() => api.approveCleanResumes(id), (r) => `Approved ${r.approved} profile(s) without warnings.`)}>
              <CheckCheck size={15} /> Approve all without warnings</button>
            <button className="btn btn-ghost" disabled={!c.failed && !c.queued}
              onClick={() => act(() => api.processResumes(id, true), () => "Processing restarted.")}>
              <RotateCcw size={15} /> Process queue / retry failed</button>
            <button className="btn btn-primary" disabled={!c.approved} onClick={() => setPublishing(true)}>
              <Sparkles size={15} /> Publish {c.approved.toLocaleString()} approved</button>
          </div>
          {ds && (
            <div className={`banner ${ds.status === "failed" ? "risk" : "info"}`} style={{ marginTop: 12 }}>
              <div>Last published as <Link to={`/datasets/${ds.id}`}>{ds.name}</Link>: {ds.status}
                {ds.n_candidates != null && ` · ${ds.n_candidates.toLocaleString()} candidates`}{ds.error && ` · ${ds.error}`}
                {ds.status === "ready" && <> · <Link to={`/rank/new?dataset=${ds.id}`}>rank these candidates</Link></>}</div>
            </div>)}
        </section>
      </div>

      <section className="card">
        <div className="card-head" style={{ flexWrap: "wrap", gap: 10 }}>
          <h2>Documents</h2>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <Segmented<Filter> label="Status" value={filter} onChange={(v) => { setFilter(v); setOffset(0); }} options={[
              { value: "all", label: "All" }, { value: "needs_review", label: "Awaiting review" },
              { value: "approved", label: "Approved" }, { value: "failed", label: "Failed" },
              { value: "duplicate", label: "Duplicates" }, { value: "rejected", label: "Rejected" }]} />
            <input className="input" placeholder="Search file, name or title" value={q} aria-label="Search documents"
              onChange={(e) => { setQ(e.target.value); setOffset(0); }} style={{ width: 220 }} />
          </div>
        </div>
        {docs.error && <ErrorBox error={docs.error} onRetry={docs.reload} />}
        {docs.data && docs.data.items.length === 0 && <div className="muted" style={{ padding: "4px 20px 16px" }}>No documents.</div>}
        {docs.data && docs.data.items.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>File</th><th>Candidate</th><th>Status</th><th>Notes</th><th /></tr></thead>
              <tbody>
                {docs.data.items.map((d) => (
                  <tr key={d.id}>
                    <td><div className="cell-title ellipsis" style={{ maxWidth: 260 }} title={d.filename}>{d.filename}</div>
                      <div className="cell-sub">{d.kind?.toUpperCase() ?? "?"} · {fmtBytes(d.size_bytes)}{d.n_pages ? ` · ${d.n_pages} p.` : ""}</div></td>
                    <td>{d.display_name ? <><div>{d.display_name}</div><div className="cell-sub">{d.title || "-"}</div></> : <span className="faint">-</span>}</td>
                    <td><StatusChip status={d.status} />{d.edited ? <span className="chip data" style={{ marginLeft: 4 }}>edited</span> : null}</td>
                    <td className="cell-sub" style={{ maxWidth: 340 }}>
                      {d.error ?? (d.possible_duplicate_of ? "Possible duplicate candidate (same contact details)" :
                        d.n_warnings ? `${d.n_warnings} warning(s)` : "")}</td>
                    <td>{d.status !== "duplicate" && <Link className="btn btn-ghost btn-sm" to={`/resumes/${id}/documents/${d.id}`}>
                      {d.status === "needs_review" ? "Review" : "Open"}</Link>}</td>
                  </tr>))}
              </tbody>
            </table>
          </div>)}
        {docs.data && docs.data.total > PAGE && (
          <div className="pager" style={{ padding: "10px 20px" }}>
            <button className="btn btn-ghost btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
            <span className="cell-sub">{offset + 1}-{Math.min(offset + PAGE, docs.data.total)} of {docs.data.total.toLocaleString()}</span>
            <button className="btn btn-ghost btn-sm" disabled={offset + PAGE >= docs.data.total} onClick={() => setOffset(offset + PAGE)}>Next</button>
          </div>)}
      </section>

      {publishing && (
        <Modal title="Publish approved profiles" onClose={() => setPublishing(false)}>
          <p>{c.approved.toLocaleString()} approved profile(s) will be written to a new dataset and indexed. Contact details are not
            included. Profiles awaiting review, rejected or failed are left out.</p>
          <label className="field"><span className="label">Dataset name</span>
            <input className="input" value={pubName} onChange={(e) => setPubName(e.target.value)} placeholder={`Resumes - ${b.name}`} maxLength={120} /></label>
          <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
            <button className="btn btn-ghost" onClick={() => setPublishing(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={async () => {
              setPublishing(false);
              await act(() => api.publishResumes(id, pubName.trim() || undefined),
                (r) => `Published ${r.published} profile(s); indexing started.`);
            }}>Publish</button>
          </div>
        </Modal>)}
    </div>
  );
}
