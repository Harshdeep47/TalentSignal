import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { FileUp, Play, Wand2 } from "lucide-react";
import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { bus, ErrorBox, Segmented, Spinner, useToast } from "../components/ui";
import SpecEditor from "../components/SpecEditor";
import type { JobSpec } from "../types/api";

const SIZES = ["10", "25", "50", "100", "500", "1000", "custom", "all"] as const;
type SizeOpt = (typeof SIZES)[number];

export default function NewRankingPage() {
  const nav = useNavigate();
  const toast = useToast();
  const [params] = useSearchParams();
  const datasets = useAsync(() => api.datasets(), []);
  const presets = useAsync(() => api.presets(), []);
  const concepts = useAsync(() => api.concepts(), []);
  const [datasetId, setDatasetId] = useState(params.get("dataset") ?? "");
  const [text, setText] = useState("");
  const [spec, setSpec] = useState<JobSpec | null>(null);
  const [parsing, setParsing] = useState(false);
  const [size, setSize] = useState<SizeOpt>("100");
  const [custom, setCustom] = useState(200);
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const ready = (datasets.data ?? []).filter((d) => d.status === "ready");
  useEffect(() => {
    if (!datasetId && ready.length) setDatasetId(ready[0].id);
  }, [ready, datasetId]);

  const analyze = async () => {
    setParsing(true);
    try {
      setSpec(await api.parseJD(text, datasetId || undefined));
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setParsing(false);
    }
  };
  const uploadJD = async (f: File) => {
    setParsing(true);
    try {
      const r = await api.uploadJD(f, datasetId || undefined);
      setText(r.text);
      setSpec(r.spec);
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setParsing(false);
    }
  };
  const shortlistSize = size === "all" ? null : size === "custom" ? custom : Number(size);
  const run = async () => {
    if (!spec || !datasetId) return;
    if (!spec.requirements.length) return toast("Add at least one requirement.", true);
    setSubmitting(true);
    try {
      const r = await api.createRun(datasetId, spec, shortlistSize, name || undefined);
      bus.emit("runs");
      nav(`/runs/${r.id}`);
    } catch (e) {
      toast((e as Error).message, true);
      setSubmitting(false);
    }
  };

  if (datasets.loading && !datasets.data) return <Spinner />;
  if (datasets.error) return <ErrorBox error={datasets.error} onRetry={datasets.reload} />;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow">Job description workspace</div>
          <h1>New ranking</h1>
          <p>Paste or upload a job description. TalentSignal extracts must-haves, nice-to-haves, experience, location and
            declared conditions - each traced to the sentence it came from - for you to review before ranking.</p>
        </div>
      </div>

      <section className="card card-pad">
        <div className="row" style={{ marginBottom: 12 }}><span className="step-num">1</span><strong>Candidate pool</strong></div>
        {ready.length === 0 ? <div className="muted">No indexed dataset yet - add one on the Datasets page.</div> : (
          <select className="select" style={{ maxWidth: 520 }} value={datasetId} onChange={(e) => setDatasetId(e.target.value)} aria-label="Dataset">
            {ready.map((d) => <option key={d.id} value={d.id}>{d.name} - {d.n_candidates?.toLocaleString()} candidates{d.shared ? " (shared)" : ""}</option>)}
          </select>
        )}
      </section>

      <section className="card card-pad">
        <div className="spread" style={{ marginBottom: 12 }}>
          <div className="row"><span className="step-num">2</span><strong>Job description</strong></div>
          <div className="row">
            {(presets.data ?? []).map((p) => (
              <button key={p.id} className="btn btn-sm btn-ghost" onClick={() => { setText(p.text); setSpec(null); }}>Load: {p.title.slice(0, 40)}</button>
            ))}
            <button className="btn btn-sm" onClick={() => fileRef.current?.click()}><FileUp size={14} /> Upload .docx / .txt / .md</button>
            <input ref={fileRef} type="file" accept=".docx,.txt,.md" hidden onChange={(e) => e.target.files?.[0] && uploadJD(e.target.files[0])} />
          </div>
        </div>
        <textarea className="input" style={{ minHeight: 220 }} value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Paste the full job description here…" aria-label="Job description text" />
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn btn-ink" disabled={text.trim().length < 20 || parsing} onClick={analyze}>
            <Wand2 size={15} /> {parsing ? "Analysing…" : spec ? "Re-analyse" : "Analyse requirements"}</button>
          {spec && <span className="muted">Re-analysing replaces your edits below.</span>}
        </div>
      </section>

      {spec && concepts.data && (
        <>
          <div className="row"><span className="step-num">3</span><strong>Review and adjust what was extracted</strong></div>
          <SpecEditor spec={spec} onChange={setSpec} concepts={concepts.data} />

          <section className="card card-pad">
            <div className="row" style={{ marginBottom: 12 }}><span className="step-num">4</span><strong>Shortlist size</strong></div>
            <div className="row">
              <Segmented label="Shortlist size" value={size} onChange={setSize}
                options={SIZES.map((s) => ({ value: s, label: s === "all" ? "All eligible" : s === "custom" ? "Custom" : `Top ${Number(s).toLocaleString()}` }))} />
              {size === "custom" && <input className="input mono" type="number" min={1} style={{ width: 120 }} value={custom}
                onChange={(e) => setCustom(Math.max(1, Number(e.target.value)))} aria-label="Custom shortlist size" />}
            </div>
            <p className="muted" style={{ fontSize: 13 }}>Every candidate in the pool is scored; the shortlist size only decides how many
              eligible candidates are kept in the results. Candidates held for review are always kept and can be inspected.</p>
            <div className="row" style={{ marginTop: 6 }}>
              <input className="input" style={{ maxWidth: 420 }} placeholder={`Run name (default: ${spec.title})`} value={name}
                onChange={(e) => setName(e.target.value)} aria-label="Run name" />
              <button className="btn btn-primary" disabled={submitting || !datasetId} onClick={run}><Play size={15} /> {submitting ? "Starting…" : "Rank candidates"}</button>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
