import { useRef, useState } from "react";
import { FolderInput, UploadCloud } from "lucide-react";
import { api, uploadDataset } from "../services/api";
import { useAsync, usePoll } from "../hooks/useAsync";
import { ErrorBox, Progress, Spinner, useToast } from "../components/ui";
import { DatasetHealth } from "./DashboardPage";

const ACCEPT = ".jsonl,.ndjson,.json,.csv,.xlsx,.parquet,.txt";

export default function DatasetsPage() {
  const toast = useToast();
  const { data, error, loading, reload } = useAsync(() => api.datasets(), []);
  const dirs = useAsync(() => api.importDirs(), []);
  const [upload, setUpload] = useState<{ name: string; p: number } | null>(null);
  const [over, setOver] = useState(false);
  const [path, setPath] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const busy = !!data?.some((d) => d.status === "indexing" || d.status === "pending");
  usePoll(reload, 1500, busy);

  const send = async (file: File) => {
    setUpload({ name: file.name, p: 0 });
    try {
      await uploadDataset(file, (p) => setUpload({ name: file.name, p }));
      toast(`Uploaded ${file.name}; indexing started.`);
      reload();
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setUpload(null);
    }
  };

  const importPath = async () => {
    try {
      await api.importPath(path.trim());
      toast("Import started.");
      setPath("");
      reload();
    } catch (e) {
      toast((e as Error).message, true);
    }
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow">Data</div>
          <h1>Datasets</h1>
          <p>Candidate files are validated, normalised and indexed once. Identical files are recognised by a full-file
            fingerprint and reuse the existing index.</p>
        </div>
      </div>

      <div className="grid grid-2">
        <section className="card card-pad">
          <h2>Upload a candidate file</h2>
          <div
            className={`dropzone ${over ? "over" : ""}`}
            onClick={() => input.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) send(f); }}
            role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && input.current?.click()}
          >
            <UploadCloud size={26} />
            <div style={{ fontWeight: 600, marginTop: 6 }}>Drop a file or click to browse</div>
            <div className="muted" style={{ fontSize: 12 }}>JSONL, JSON, CSV, XLSX, Parquet - one candidate per record</div>
          </div>
          <input ref={input} type="file" accept={ACCEPT} hidden onChange={(e) => e.target.files?.[0] && send(e.target.files[0])} />
          {upload && (
            <div style={{ marginTop: 12 }}>
              <div className="spread cell-sub"><span>Uploading {upload.name}</span><span className="mono">{Math.round(upload.p * 100)}%</span></div>
              <Progress value={upload.p} />
            </div>
          )}
        </section>

        <section className="card card-pad">
          <h2>Import from the server</h2>
          <p className="muted" style={{ marginTop: 0 }}>For large files already on the server - avoids pushing hundreds of MB through the
            browser. Allowed directories:</p>
          <div className="chips" style={{ marginBottom: 10 }}>
            {(dirs.data ?? []).map((d) => <span key={d} className="chip mono" style={{ fontSize: 11 }}>{d}</span>)}
          </div>
          <div className="row">
            <input className="input" style={{ flex: 1 }} placeholder="Full path to a .jsonl / .csv / .parquet file"
              value={path} onChange={(e) => setPath(e.target.value)} aria-label="Server file path" />
            <button className="btn btn-ink" disabled={!path.trim()} onClick={importPath}><FolderInput size={15} /> Import</button>
          </div>
        </section>
      </div>

      <section className="card">
        <div className="card-head"><h2>All datasets</h2></div>
        <div style={{ padding: "4px 20px 12px" }}>
          {loading && !data && <Spinner />}
          {error && <ErrorBox error={error} onRetry={reload} />}
          {data && data.length === 0 && <div className="muted" style={{ padding: 10 }}>No datasets yet.</div>}
          {data?.map((d) => <DatasetHealth key={d.id} d={d} />)}
        </div>
      </section>
    </div>
  );
}
