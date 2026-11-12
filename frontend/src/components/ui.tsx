import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, Loader2, ShieldAlert, ShieldCheck } from "lucide-react";

export const pct = (x: number | null | undefined, digits = 0) =>
  x === null || x === undefined || Number.isNaN(x) ? "-" : `${(x * 100).toFixed(digits)}%`;
export const num = (x: number | null | undefined, digits = 1) =>
  x === null || x === undefined || Number.isNaN(x) ? "-" : x.toFixed(digits);
export const score100 = (x: number | null | undefined) =>
  x === null || x === undefined ? "-" : (x * 100).toFixed(1);
export const fmtDate = (epoch: number | null | undefined) =>
  epoch ? new Date(epoch * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "-";
export const fmtBytes = (b: number) =>
  b > 1e9 ? `${(b / 1e9).toFixed(2)} GB` : b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} KB`;

export function ScoreBar({ value, tone = "ink", showNum = true }: { value: number; tone?: "ink" | "signal" | "ok" | "data"; showNum?: boolean }) {
  const v = Math.max(0, Math.min(1, value || 0));
  return (
    <span className="score" aria-label={`score ${score100(v)} of 100`}>
      {showNum && <span className="score-num">{score100(v)}</span>}
      <span className={`bar ${tone === "ink" ? "" : tone}`}><span style={{ width: `${v * 100}%` }} /></span>
    </span>
  );
}

export function RankPill({ rank }: { rank: number }) {
  if (!rank) return <span className="rank-pill" title="Held for review">-</span>;
  return <span className={`rank-pill ${rank <= 10 ? "top" : ""}`}>{rank}</span>;
}

export function CoverageDots({ coverage, ids }: { coverage: Record<string, number>; ids: string[] }) {
  return (
    <span className="cov" aria-label="must-have coverage">
      {ids.map((id) => {
        const c = coverage[id] ?? 0;
        return <i key={id} className={c >= 0.65 ? "met" : c >= 0.3 ? "partial" : ""} title={`${id}: ${pct(c)}`} />;
      })}
    </span>
  );
}

export function FlagIcons({ codes, critical }: { codes: string[]; critical?: boolean }) {
  if (critical) return <span className="chip risk"><ShieldAlert size={13} /> review</span>;
  const meaningful = codes.filter((c) => !["salary_range_inverted", "activity_before_signup", "current_title_mismatch", "overlapping_roles"].includes(c));
  if (!meaningful.length) return <span className="chip ok" title="No integrity warnings"><ShieldCheck size={13} /></span>;
  return <span className="chip warn" title={meaningful.join(", ")}><AlertTriangle size={13} /> {meaningful.length}</span>;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <div className="empty"><Loader2 className="spin" size={20} /> <span className="sr-only">{label}</span><div>{label}...</div></div>;
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="error-box row" role="alert">
      <AlertTriangle size={16} /> <span style={{ flex: 1 }}>{error}</span>
      {onRetry && <button className="btn btn-sm" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return <div className="empty">{icon}<h3>{title}</h3>{children}</div>;
}

export function Progress({ value }: { value: number }) {
  return <div className="progress" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
    <span style={{ width: `${Math.max(2, value * 100)}%` }} />
  </div>;
}

export function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" className={o.value === value ? "on" : ""} aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

export function Menu({ label, children }: { label: ReactNode; children: (close: () => void) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  return (
    <div className="menu" ref={ref}>
      <button className="btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{label}</button>
      {open && <div className="menu-list" role="menu">{children(() => setOpen(false))}</div>}
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <h2 style={{ marginTop: 0, fontSize: 17 }}>{title}</h2>
        {children}
      </div>
    </div>
  );
}

type Toast = { text: string; error?: boolean } | null;
const ToastCtx = createContext<(text: string, error?: boolean) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast>(null);
  const timer = useRef<number>();
  const show = useCallback((text: string, error = false) => {
    setToast({ text, error });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setToast(null), 4200);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {toast && <div className={`toast ${toast.error ? "error" : ""}`} role="status">{toast.text}</div>}
    </ToastCtx.Provider>
  );
}

/** Simple event bus so the sidebar refreshes when runs / shortlists change. */
export const bus = {
  emit: (name: string) => window.dispatchEvent(new CustomEvent(`ts:${name}`)),
  on: (name: string, fn: () => void) => {
    const h = () => fn();
    window.addEventListener(`ts:${name}`, h);
    return () => window.removeEventListener(`ts:${name}`, h);
  },
};

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="#1f2e52" />
      <rect x="7" y="17" width="4" height="8" rx="1.5" fill="#8C93A8" />
      <rect x="14" y="12" width="4" height="13" rx="1.5" fill="#C9CCD6" />
      <rect x="21" y="6" width="4" height="19" rx="1.5" fill="#E4572E" />
    </svg>
  );
}
