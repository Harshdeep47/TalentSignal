import { useEffect, useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { Database, FileText, History, LayoutDashboard, ListChecks, Sparkles } from "lucide-react";
import { api } from "../services/api";
import type { Run, Shortlist } from "../types/api";
import { bus, Logo } from "../components/ui";

/** App chrome: ink navigation rail with recent runs and saved shortlists. */
export default function Shell() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [lists, setLists] = useState<Shortlist[]>([]);

  const refresh = () => {
    api.runs(6).then(setRuns).catch(() => setRuns([]));
    api.shortlists().then((l) => setLists(l.slice(0, 6))).catch(() => setLists([]));
  };
  useEffect(() => {
    refresh();
    const off1 = bus.on("runs", refresh);
    const off2 = bus.on("shortlists", refresh);
    return () => { off1(); off2(); };
  }, []);

  return (
    <div className="shell">
      <aside className="rail" aria-label="Primary">
        <Link to="/" className="brand">
          <Logo />
          <div>
            <div className="brand-name">Talent<span>Signal</span></div>
            <div className="brand-tag">Candidate intelligence</div>
          </div>
        </Link>
        <nav className="nav">
          <NavLink to="/" end><LayoutDashboard size={17} /> Dashboard</NavLink>
          <NavLink to="/rank/new"><Sparkles size={17} /> New ranking</NavLink>
          <NavLink to="/datasets"><Database size={17} /> Datasets</NavLink>
          <NavLink to="/resumes"><FileText size={17} /> Resume intake</NavLink>
          <NavLink to="/history"><History size={17} /> Ranking history</NavLink>
          <NavLink to="/shortlists"><ListChecks size={17} /> Shortlists</NavLink>
        </nav>
        <div className="rail-section">
          <div className="rail-title">Recent runs</div>
          {runs.length === 0 && <div className="rail-empty">No runs yet</div>}
          {runs.map((r) => (
            <NavLink key={r.id} to={`/runs/${r.id}`} className="rail-link">
              <span style={{ minWidth: 0 }}>
                <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.jd_title}</span>
                <small>{r.status === "ready" ? `${r.n_results?.toLocaleString()} ranked` : r.status} · {r.dataset_name}</small>
              </span>
            </NavLink>
          ))}
        </div>
        <div className="rail-section">
          <div className="rail-title">Saved shortlists</div>
          {lists.length === 0 && <div className="rail-empty">None saved</div>}
          {lists.map((s) => (
            <NavLink key={s.id} to={`/shortlists/${s.id}`} className="rail-link">
              <span>{s.name}<small>{s.size} candidates</small></span>
            </NavLink>
          ))}
        </div>
        <div className="rail-foot">Decision support only. Scores summarise evidence; they are not hiring probabilities.</div>
      </aside>
      <main className="main"><Outlet /></main>
    </div>
  );
}
