// Thin API client. Every request carries the per-browser session id; errors
// are normalised to ApiError so pages can show the server's message.
import type {
  Comparison, Concept, Dashboard, Dataset, Explanation, Facets, JobSpec, Page, ResultRow, Run, Shortlist, Job,
} from "../types/api";

const SESSION_KEY = "talentsignal.session";

export function sessionId(): string {
  let id: string | null = null;
  try {
    id = localStorage.getItem(SESSION_KEY);
  } catch {
    /* storage unavailable (private mode): fall back to an in-memory id */
  }
  if (!id) {
    id = crypto.randomUUID();
    try {
      localStorage.setItem(SESSION_KEY, id);
    } catch {
      /* ignore */
    }
  }
  return id;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, raw = false): Promise<T> {
  const headers: Record<string, string> = { "X-Session-Id": sessionId() };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, { method, headers, body: payload });
  if (!res.ok) {
    let code = "http_error";
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      code = data?.error?.code ?? code;
      message = data?.error?.message ?? message;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, code, message);
  }
  if (raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export type ResultQuery = {
  page?: number; page_size?: number; sort?: string; order?: "asc" | "desc"; q?: string;
  view?: "shortlist" | "held" | "all"; min_score?: number; max_score?: number; min_years?: number;
  max_years?: number; countries?: string[]; cities?: string[]; branches?: string[]; skills?: string[];
  flags?: "none" | "any" | "critical" | "warning"; min_mandatory?: number;
};

function qs(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) {
      if (v.length) sp.set(k, v.join(","));
    } else sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  health: () => request<{ status: string; version: string; semantic_model: boolean }>("GET", "/health"),
  dashboard: () => request<Dashboard>("GET", "/dashboard"),
  concepts: () => request<Concept[]>("GET", "/taxonomy/concepts"),

  datasets: () => request<Dataset[]>("GET", "/datasets"),
  dataset: (id: string) => request<Dataset>("GET", `/datasets/${id}`),
  importDirs: () => request<string[]>("GET", "/datasets/import-dirs"),
  importPath: (path: string) => request<Dataset>("POST", "/datasets/import-path", { path }),
  reindex: (id: string) => request<Dataset>("POST", `/datasets/${id}/reindex`),
  deleteDataset: (id: string) => request<void>("DELETE", `/datasets/${id}`),

  job: (id: string) => request<Job>("GET", `/jobs/${id}`),
  cancelJob: (id: string) => request<{ cancelling: boolean }>("POST", `/jobs/${id}/cancel`),

  parseJD: (text: string, dataset_id?: string) => request<JobSpec>("POST", "/jd/parse", { text, dataset_id }),
  uploadJD: (file: File, dataset_id?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ text: string; spec: JobSpec }>("POST", `/jd/upload${qs({ dataset_id })}`, fd);
  },
  presets: () => request<{ id: string; title: string; text: string }[]>("GET", "/jd/presets"),

  runs: (limit = 50) => request<Run[]>("GET", `/runs?limit=${limit}`),
  run: (id: string) => request<Run>("GET", `/runs/${id}`),
  createRun: (dataset_id: string, spec: JobSpec, shortlist_size: number | null, name?: string) =>
    request<Run>("POST", "/runs", { dataset_id, spec, shortlist_size, name }),
  rerun: (id: string) => request<Run>("POST", `/runs/rerun/${id}`),
  deleteRun: (id: string) => request<void>("DELETE", `/runs/${id}`),
  results: (id: string, q: ResultQuery) => request<Page<ResultRow>>("GET", `/runs/${id}/results${qs(q)}`),
  facets: (id: string, view: "shortlist" | "all" = "shortlist") => request<Facets>("GET", `/runs/${id}/facets?view=${view}`),
  candidate: (runId: string, cid: string) => request<Explanation>("GET", `/runs/${runId}/candidates/${encodeURIComponent(cid)}`),
  compare: (runId: string, ids: string[]) => request<Comparison>("POST", `/runs/${runId}/compare`, { candidate_ids: ids }),

  shortlists: () => request<Shortlist[]>("GET", "/shortlists"),
  shortlist: (id: string) => request<Shortlist>("GET", `/shortlists/${id}`),
  createShortlist: (run_id: string, name: string, candidate_ids: string[]) =>
    request<Shortlist>("POST", "/shortlists", { run_id, name, candidate_ids }),
  addToShortlist: (id: string, candidate_id: string, note = "") =>
    request<Shortlist>("POST", `/shortlists/${id}/items`, { candidate_id, note }),
  removeFromShortlist: (id: string, cid: string) =>
    request<Shortlist>("DELETE", `/shortlists/${id}/items/${encodeURIComponent(cid)}`),
  deleteShortlist: (id: string) => request<void>("DELETE", `/shortlists/${id}`),
};

/** Upload a candidate file with real upload progress (fetch cannot report it). */
export function uploadDataset(file: File, onProgress: (fraction: number) => void): Promise<Dataset> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/datasets/upload");
    xhr.setRequestHeader("X-Session-Id", sessionId());
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let data: any = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as Dataset);
      else reject(new ApiError(xhr.status, data?.error?.code ?? "upload_failed", data?.error?.message ?? "Upload failed"));
    };
    xhr.onerror = () => reject(new ApiError(0, "network", "Network error during upload"));
    const fd = new FormData();
    fd.append("file", file);
    xhr.send(fd);
  });
}

/** POST an export request and trigger a browser download of the returned file. */
export async function download(path: string, body?: unknown, fallbackName = "export"): Promise<void> {
  const res = await request<Response>("POST", path, body, true);
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
