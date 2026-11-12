import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, Download, Plus, Save, ShieldAlert, X } from "lucide-react";
import { api, downloadOriginal } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { ErrorBox, fmtBytes, Spinner, useToast } from "../components/ui";
import type { CandidateRecord, Fact, ResumeDocument, ResumeExtraction } from "../types/api";
import { StatusChip } from "./ResumesPage";

type Loc = { page: number | null; line: number } | null;
type Status = Fact["status"] | "edited";

const STATUS_TEXT: Record<Status, string> = {
  stated: "stated", inferred: "inferred", missing: "missing", edited: "edited",
};
const STATUS_TONE: Record<Status, string> = { stated: "ok", inferred: "data", missing: "warn", edited: "signal" };
const STATUS_HELP: Record<Status, string> = {
  stated: "Appears in the resume text",
  inferred: "Derived by a documented rule from stated text",
  missing: "Not found in the resume - left empty, never guessed",
  edited: "Changed by a reviewer",
};
const PROFICIENCY = ["", "beginner", "intermediate", "advanced", "expert"];

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const sameText = (a?: string | null, b?: string | null) => (a ?? "").trim().toLowerCase() === (b ?? "").trim().toLowerCase();

/** Fact badge with status and a clickable source location. */
function FactTag({ fact, edited, onLocate }: { fact?: Fact | null; edited?: boolean; onLocate: (l: Loc) => void }) {
  const status: Status = edited ? "edited" : fact?.status ?? "missing";
  const src = fact?.source;
  return (
    <span className="row" style={{ gap: 6, flexWrap: "wrap" }}>
      <span className={`chip ${STATUS_TONE[status]}`} title={STATUS_HELP[status]} style={{ fontSize: 11 }}>{STATUS_TEXT[status]}</span>
      {src && !edited && (
        <button type="button" className="chip mono" style={{ fontSize: 11, cursor: "pointer" }}
          title={`Source: "${src.text}"`} onClick={() => onLocate({ page: src.page, line: src.line })}>
          {src.page ? `p.${src.page} · ` : ""}l.{src.line}</button>)}
      {fact?.note && !edited && <span className="cell-sub" style={{ fontSize: 11 }}>{fact.note}</span>}
    </span>
  );
}

function Field({ label, children, tag }: { label: string; children: ReactNode; tag: ReactNode }) {
  return (
    <label className="field" style={{ gap: 4 }}>
      <span className="spread"><span className="label" style={{ marginBottom: 0 }}>{label}</span>{tag}</span>
      {children}
    </label>
  );
}

export default function ResumeReviewPage() {
  const { bid = "", did = "" } = useParams();
  const toast = useToast();
  const doc = useAsync(() => api.resumeDocument(did), [did]);
  const [draft, setDraft] = useState<CandidateRecord | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loc, setLoc] = useState<Loc>(null);
  const textRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (doc.data?.record) { setDraft(clone(doc.data.record)); setDirty(false); }
  }, [doc.data]);

  useEffect(() => {
    if (!loc) return;
    const el = textRef.current?.querySelector(`[data-loc="${loc.page ?? 0}-${loc.line}"]`);
    if (el && typeof (el as HTMLElement).scrollIntoView === "function") el.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [loc]);

  const edited = useMemo(() => new Set(doc.data?.edited_fields ?? []), [doc.data]);

  if (doc.loading && !doc.data) return <Spinner />;
  if (doc.error) return <ErrorBox error={doc.error} onRetry={doc.reload} />;
  const d = doc.data as ResumeDocument;
  const ex = d.extraction as ResumeExtraction | undefined;

  const update = (fn: (r: CandidateRecord) => void) => {
    setDraft((prev) => { const n = clone(prev as CandidateRecord); fn(n); return n; });
    setDirty(true);
  };

  const save = async (): Promise<boolean> => {
    if (!draft) return false;
    setBusy(true);
    try {
      const next = await api.updateResumeRecord(did, draft);
      doc.setData(next);
      toast("Corrections saved.");
      return true;
    } catch (e) {
      toast((e as Error).message, true);
      return false;
    } finally {
      setBusy(false);
    }
  };
  const setStatus = async (approve: boolean) => {
    if (dirty && !(await save())) return;
    try {
      doc.setData(await (approve ? api.approveResume(did) : api.rejectResume(did)));
      toast(approve ? "Approved - it will be included in the next publish." : "Rejected - it will not be published.");
    } catch (e) {
      toast((e as Error).message, true);
    }
  };

  const header = (
    <>
      <Link to={`/resumes/${bid}`} className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start" }}><ArrowLeft size={14} /> Back to batch</Link>
      <section className="card card-pad">
        <div className="detail-head">
          <div>
            <div className="eyebrow">{d.kind?.toUpperCase()} · {fmtBytes(d.size_bytes)}{d.n_pages ? ` · ${d.n_pages} page(s)` : ""}
              {d.candidate_id && <> · <span className="mono">{d.candidate_id}</span></>}</div>
            <h1 style={{ margin: "4px 0 6px", fontSize: 22 }}>{d.display_name || d.filename}</h1>
            <div className="row" style={{ gap: 8 }}><StatusChip status={d.status} /><span className="cell-sub">{d.filename}</span></div>
          </div>
          <div className="row" style={{ flexWrap: "wrap" }}>
            {d.has_original && <button className="btn btn-ghost" onClick={() => downloadOriginal(did, d.filename).catch((e) => toast(e.message, true))}>
              <Download size={15} /> Original</button>}
            {draft && <>
              <button className="btn btn-ghost" disabled={!dirty || busy} onClick={save}><Save size={15} /> Save corrections</button>
              <button className="btn btn-ghost" disabled={busy || d.status === "rejected"} onClick={() => setStatus(false)}><X size={15} /> Reject</button>
              <button className="btn btn-primary" disabled={busy || (d.status === "approved" && !dirty)} onClick={() => setStatus(true)}>
                <Check size={15} /> {dirty ? "Save and approve" : "Approve"}</button>
            </>}
          </div>
        </div>
        {d.error && <div className="banner risk" style={{ marginTop: 12 }}><ShieldAlert size={16} /><div><strong>{d.error_code}</strong>: {d.error}</div></div>}
        {d.duplicate_of_doc && <div className="banner info" style={{ marginTop: 12 }}>Identical to{" "}
          <Link to={`/resumes/${d.duplicate_of_doc.batch_id}/documents/${d.duplicate_of_doc.id}`}>{d.duplicate_of_doc.filename}</Link>.</div>}
        {d.possible_duplicate_of_doc && <div className="banner warn" style={{ marginTop: 12 }}>Same e-mail or phone as{" "}
          <Link to={`/resumes/${d.possible_duplicate_of_doc.batch_id}/documents/${d.possible_duplicate_of_doc.id}`}>{d.possible_duplicate_of_doc.filename}</Link>
          {" "}- check whether this is the same candidate before approving both.</div>}
      </section>
    </>
  );

  return <div className="stack">{header}{renderEditor()}</div>;

  function renderEditor() {
  if (!ex || !draft) return null;
  const p = draft.profile;
  const parsed = d.parsed_record;
  const isEd = (path: string) => edited.has(path);
  const roleFact = (i: number) => {
    const base = parsed?.career_history[i];
    return base ? ex.experience.find((r) => sameText(r.title.value, base.title) && sameText(r.company.value, base.company)) : undefined;
  };
  const eduFact = (i: number) => {
    const base = parsed?.education[i];
    return base ? ex.education.find((e) => sameText(e.degree.value, base.degree) && sameText(e.institution.value, base.institution)) : undefined;
  };
  const skillFact = (name: string) => ex.skills.find((s) => sameText(s.name.value, name));
  const tag = (fact: Fact | undefined | null, path: string) => <FactTag fact={fact} edited={isEd(path)} onLocate={setLoc} />;
  const listTag = (fact: Fact | undefined | null, path: string) => <FactTag fact={fact} edited={isEd(path) && !fact} onLocate={setLoc} />;
  const text = (label: string, value: string, set: (v: string) => void, fact: Fact | undefined | null, path: string) => (
    <Field label={label} tag={tag(fact, path)}>
      <input className="input" value={value ?? ""} onChange={(e) => set(e.target.value)} aria-label={label} />
    </Field>);

  return (
    <>
      {ex.warnings.length > 0 && (
        <div className="banner warn"><ShieldAlert size={16} /><div><strong>Check before approving:</strong>
          <ul className="list-plain" style={{ margin: "4px 0 0" }}>{ex.warnings.map((w) => <li key={w}>{w}</li>)}</ul></div></div>)}

      <div className="grid grid-2" style={{ alignItems: "start" }}>
        <div className="stack">
          <section className="card card-pad stack" style={{ gap: 12 }}>
            <div className="spread"><h2 style={{ margin: 0 }}>Profile</h2>
              <span className="legend cell-sub">{(["stated", "inferred", "missing", "edited"] as Status[]).map((s) =>
                <span key={s} className={`chip ${STATUS_TONE[s]}`} title={STATUS_HELP[s]} style={{ fontSize: 11 }}>{s}</span>)}</span></div>
            {text("Name", p.anonymized_name, (v) => update((r) => { r.profile.anonymized_name = v; }), ex.identity.name, "profile.anonymized_name")}
            {text("Headline", p.headline, (v) => update((r) => { r.profile.headline = v; }), ex.identity.headline, "profile.headline")}
            <div className="grid grid-2">
              {text("Current title", p.current_title, (v) => update((r) => { r.profile.current_title = v; }), ex.current_title, "profile.current_title")}
              {text("Current company", p.current_company, (v) => update((r) => { r.profile.current_company = v; }), ex.current_company, "profile.current_company")}
              {text("Location", p.location, (v) => update((r) => { r.profile.location = v; }), ex.identity.location, "profile.location")}
              {text("Country", p.country, (v) => update((r) => { r.profile.country = v; }), ex.identity.country, "profile.country")}
            </div>
            <Field label="Years of experience" tag={tag(ex.years_of_experience, "profile.years_of_experience")}>
              <input className="input" type="number" min={0} max={60} step={0.5} style={{ maxWidth: 140 }} aria-label="Years of experience"
                value={p.years_of_experience ?? ""} onChange={(e) => update((r) => {
                  r.profile.years_of_experience = e.target.value === "" ? null : Number(e.target.value); })} />
            </Field>
            <Field label="Summary (used for semantic and keyword matching)" tag={tag(ex.summary, "profile.summary")}>
              <textarea className="input" value={p.summary} aria-label="Summary" onChange={(e) => update((r) => { r.profile.summary = e.target.value; })} />
            </Field>
            {ex.projects.length + ex.achievements.length > 0 && !isEd("profile.summary") &&
              <div className="cell-sub">The summary also includes the resume's Projects and Achievements sections so they count as evidence.</div>}
          </section>

          <section className="card card-pad stack" style={{ gap: 12 }}>
            <div className="spread"><h2 style={{ margin: 0 }}>Experience</h2>
              <button className="btn btn-ghost btn-sm" onClick={() => update((r) => r.career_history.push({ company: "", title: "", start_date: null,
                end_date: null, duration_months: null, is_current: false, industry: "", description: "" }))}><Plus size={14} /> Add role</button></div>
            {isEd("career_history") && <div className="cell-sub"><span className="chip signal" style={{ fontSize: 11 }}>edited</span> Roles were changed by a reviewer.</div>}
            {draft.career_history.length === 0 && <div className="muted">No roles were recognised.</div>}
            {draft.career_history.map((role, i) => {
              const f = roleFact(i);
              return (
                <div key={i} className="stack" style={{ gap: 8, borderTop: i ? "1px solid var(--line)" : undefined, paddingTop: i ? 12 : 0 }}>
                  <div className="grid grid-2">
                    <Field label="Title" tag={listTag(f?.title, "career_history")}><input className="input" aria-label={`Role ${i + 1} title`} value={role.title}
                      onChange={(e) => update((r) => { r.career_history[i].title = e.target.value; })} /></Field>
                    <Field label="Company" tag={listTag(f?.company, "career_history")}><input className="input" aria-label={`Role ${i + 1} company`} value={role.company}
                      onChange={(e) => update((r) => { r.career_history[i].company = e.target.value; })} /></Field>
                    <Field label="Start (YYYY-MM-DD)" tag={listTag(f?.start_date, "career_history")}><input className="input" aria-label={`Role ${i + 1} start`}
                      value={role.start_date ?? ""} onChange={(e) => update((r) => { r.career_history[i].start_date = e.target.value || null; r.career_history[i].duration_months = null; })} /></Field>
                    <Field label="End (empty = current)" tag={listTag(f?.end_date, "career_history")}><input className="input" aria-label={`Role ${i + 1} end`}
                      value={role.end_date ?? ""} onChange={(e) => update((r) => { r.career_history[i].end_date = e.target.value || null;
                        r.career_history[i].is_current = !e.target.value; r.career_history[i].duration_months = null; })} /></Field>
                  </div>
                  <Field label="Description" tag={listTag(f?.description, "career_history")}><textarea className="input" style={{ minHeight: 70 }}
                    aria-label={`Role ${i + 1} description`} value={role.description}
                    onChange={(e) => update((r) => { r.career_history[i].description = e.target.value; })} /></Field>
                  <div className="spread cell-sub"><span>{role.is_current ? "Current role" : ""}{role.duration_months != null ? ` · ${role.duration_months} months` : ""}
                    {f?.duration_months && role.duration_months === f.duration_months.value ? " (inferred from dates)" : ""}</span>
                    <button className="btn btn-ghost btn-sm" onClick={() => update((r) => { r.career_history.splice(i, 1); })}><X size={13} /> Remove</button></div>
                </div>);
            })}
          </section>

          <section className="card card-pad stack" style={{ gap: 12 }}>
            <div className="spread"><h2 style={{ margin: 0 }}>Skills</h2>
              <button className="btn btn-ghost btn-sm" onClick={() => update((r) => r.skills.push({ name: "", proficiency: null, endorsements: null,
                duration_months: null }))}><Plus size={14} /> Add skill</button></div>
            <p className="cell-sub" style={{ margin: 0 }}>Proficiency is only filled when the resume states it. Platform endorsements and skill-usage durations
              do not exist for resumes and stay empty (treated as unknown, not as zero).</p>
            {draft.skills.map((s, i) => {
              const f = skillFact(s.name);
              return (
                <div key={i} className="stack" style={{ gap: 4 }}>
                  <div className="row" style={{ flexWrap: "nowrap" }}>
                    <input className="input" style={{ flex: "1 1 auto", minWidth: 0 }} aria-label={`Skill ${i + 1}`} value={s.name}
                      onChange={(e) => update((r) => { r.skills[i].name = e.target.value; })} />
                    <select className="select" style={{ width: 130, flex: "none" }} aria-label={`Skill ${i + 1} proficiency`} value={s.proficiency ?? ""}
                      onChange={(e) => update((r) => { r.skills[i].proficiency = e.target.value || null; })}>
                      {PROFICIENCY.map((v) => <option key={v} value={v}>{v || "not stated"}</option>)}</select>
                    <button className="btn btn-ghost btn-sm" style={{ flex: "none" }} aria-label={`Remove skill ${s.name}`}
                      onClick={() => update((r) => { r.skills.splice(i, 1); })}><X size={13} /></button>
                  </div>
                  <FactTag fact={f?.name} edited={!f} onLocate={setLoc} />
                </div>);
            })}
          </section>

          <section className="card card-pad stack" style={{ gap: 12 }}>
            <h2 style={{ margin: 0 }}>Education and certifications</h2>
            {draft.education.length === 0 && <div className="muted">No education entries were recognised.</div>}
            {draft.education.map((e, i) => {
              const f = eduFact(i);
              return (
                <div key={i} className="grid grid-2">
                  <Field label="Degree" tag={listTag(f?.degree, "education")}><input className="input" aria-label={`Degree ${i + 1}`} value={e.degree}
                    onChange={(ev) => update((r) => { r.education[i].degree = ev.target.value; })} /></Field>
                  <Field label="Field of study" tag={listTag(f?.field_of_study, "education")}><input className="input" aria-label={`Field ${i + 1}`} value={e.field_of_study}
                    onChange={(ev) => update((r) => { r.education[i].field_of_study = ev.target.value; })} /></Field>
                  <Field label="Institution" tag={listTag(f?.institution, "education")}><input className="input" aria-label={`Institution ${i + 1}`} value={e.institution}
                    onChange={(ev) => update((r) => { r.education[i].institution = ev.target.value; })} /></Field>
                  <Field label="End year" tag={listTag(f?.end_year, "education")}><input className="input" type="number" aria-label={`End year ${i + 1}`}
                    value={e.end_year ?? ""} onChange={(ev) => update((r) => { r.education[i].end_year = ev.target.value ? Number(ev.target.value) : null; })} /></Field>
                </div>);
            })}
            {draft.certifications.length > 0 && <div className="divider" />}
            {draft.certifications.map((c, i) => (
              <div key={i} className="row" style={{ flexWrap: "wrap" }}>
                <input className="input" style={{ flex: 1, minWidth: 200 }} aria-label={`Certification ${i + 1}`} value={c.name}
                  onChange={(e) => update((r) => { r.certifications[i].name = e.target.value; })} />
                <span className="cell-sub">{[c.issuer, c.year].filter(Boolean).join(" · ")}</span>
                <FactTag fact={ex.certifications.find((x) => sameText(x.name.value, c.name))?.name} edited={isEd("certifications") &&
                  !ex.certifications.find((x) => sameText(x.name.value, c.name))} onLocate={setLoc} />
              </div>))}
          </section>
        </div>

        <div className="stack" style={{ position: "sticky", top: 16 }}>
          <section className="card card-pad">
            <h2>Contact details</h2>
            <p className="cell-sub" style={{ marginTop: -4 }}>Visible here for follow-up only. They are not copied into the candidate profile, the ranking
              index or exports.</p>
            {[...ex.contact.emails, ...ex.contact.phones, ...ex.contact.links].length === 0 ? <div className="muted">None found.</div> : (
              <div className="stack" style={{ gap: 6 }}>{[...ex.contact.emails, ...ex.contact.phones, ...ex.contact.links].map((c) => (
                <div key={c.value as string} className="spread"><span className="mono" style={{ fontSize: 12 }}>{c.value}</span><FactTag fact={c} onLocate={setLoc} /></div>))}
              </div>)}
            {ex.document.redacted_lines > 0 && <p className="cell-sub">{ex.document.redacted_lines} line(s) stating personal attributes (such as date
              of birth, gender or marital status) were redacted and not used.</p>}
          </section>
          <section className="card">
            <div className="card-head"><h2>Extracted text</h2><span className="cell-sub">sections: {ex.sections_found.join(", ") || "none recognised"}</span></div>
            <div ref={textRef} className="mono" style={{ fontSize: 12, maxHeight: 640, overflow: "auto", padding: "0 16px 16px", lineHeight: 1.6 }}>
              {d.text_pages.map((lines, pi) => (
                <div key={pi}>
                  {d.kind === "pdf" && <div className="eyebrow" style={{ margin: "10px 0 4px" }}>Page {pi + 1}</div>}
                  {lines.map((t, li) => {
                    const page = d.kind === "pdf" ? pi + 1 : null;
                    const on = loc && loc.page === page && loc.line === li + 1;
                    return (
                      <div key={li} data-loc={`${page ?? 0}-${li + 1}`} style={{ display: "flex", gap: 10,
                        background: on ? "var(--signal-soft)" : undefined, borderRadius: 4 }}>
                        <span className="faint" style={{ minWidth: 28, textAlign: "right", userSelect: "none" }}>{li + 1}</span>
                        <span style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{t}</span>
                      </div>);
                  })}
                </div>))}
            </div>
          </section>
        </div>
      </div>
    </>
  );
  }
}
