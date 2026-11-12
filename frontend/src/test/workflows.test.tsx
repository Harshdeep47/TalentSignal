import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { useState } from "react";
import SpecEditor from "../components/SpecEditor";
import RunPage from "../pages/RunPage";
import CandidatePage from "../pages/CandidatePage";
import NewRankingPage from "../pages/NewRankingPage";
import { ToastProvider } from "../components/ui";
import { ApiError, api, sessionId } from "../services/api";
import type { JobSpec } from "../types/api";
import { explanation, mockFetch, page, run, spec } from "./fixtures";

function at(path: string, routePath: string, el: JSX.Element) {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path={routePath} element={el} /><Route path="*" element={<div>navigated</div>} /></Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

describe("api client", () => {
  it("persists one session id and sends it on every request", async () => {
    const a = sessionId();
    expect(sessionId()).toBe(a);
    const calls = mockFetch([["/api/health", () => ({ status: "ok", version: "1", semantic_model: true })]]);
    await api.health();
    expect((calls[0].init?.headers as Record<string, string>)["X-Session-Id"]).toBe(a);
  });

  it("surfaces the server error message", async () => {
    mockFetch([["/api/runs/x", () => new Response(JSON.stringify({ error: { code: "run_not_found", message: "Run not found." } }), { status: 404 })]]);
    await expect(api.run("x")).rejects.toEqual(new ApiError(404, "run_not_found", "Run not found."));
  });
});

describe("SpecEditor (requirement review)", () => {
  function Harness({ onSpec }: { onSpec: (s: JobSpec) => void }) {
    const [s, setS] = useState(spec);
    return <SpecEditor spec={s} onChange={(n) => { setS(n); onSpec(n); }}
      concepts={[{ id: "nlp", label: "Natural language processing", category: "ml", skills: ["NLP"], phrases: ["nlp"], semantic: "x", signal: null }]} />;
  }

  it("lets the recruiter change importance, add and remove requirements, and see normalised weights", async () => {
    let latest = spec;
    render(<Harness onSpec={(s) => (latest = s)} />);
    expect(screen.getByText(/2 must-have, 1 nice-to-have/)).toBeInTheDocument();
    expect(screen.getByText(/from JD: "Strong Python\."/)).toBeInTheDocument();

    const selects = screen.getAllByLabelText("Importance");
    fireEvent.change(selects[2], { target: { value: "mandatory" } });
    expect(latest.requirements[2].importance).toBe("mandatory");
    expect(latest.requirements[2].weight).toBeGreaterThanOrEqual(0.8);

    fireEvent.change(screen.getByLabelText("Add capability"), { target: { value: "nlp" } });
    await userEvent.click(screen.getByRole("button", { name: /^Add$/ }));
    expect(latest.requirements.map((r) => r.id)).toContain("nlp");

    await userEvent.click(screen.getAllByLabelText("Remove requirement")[0]);
    expect(latest.requirements.map((r) => r.id)).not.toContain("embeddings_retrieval");

    fireEvent.change(screen.getByLabelText("Policy for Consulting-only career"), { target: { value: "exclude" } });
    expect(latest.constraints[0].policy).toBe("exclude");
    expect(screen.getByText("34%")).toBeInTheDocument();
  });
});

describe("Run results", () => {
  it("renders the shortlist, filters server-side and enables compare for 2+ selections", async () => {
    const calls = mockFetch([
      ["/api/runs/run1/results", () => page],
      ["/api/runs/run1/facets", () => ({ countries: [{ value: "India", count: 3 }], cities: [], branches: [], skills: [],
        flags: { none: 3, any: 0, critical: 0, warning: 0 }, years: { min: 5, max: 9 }, score: { min: 0.8, max: 0.9 }, held_for_review: 2 })],
      ["/api/runs/run1", () => run],
    ]);
    at("/runs/run1", "/runs/:id", <RunPage />);
    expect(await screen.findByText("Person 1")).toBeInTheDocument();
    expect(screen.getByText(/Held for review \(2\)/)).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText(/^India/));
    await waitFor(() => expect(calls.some((c) => c.url.includes("countries=India"))).toBe(true));

    await userEvent.click(screen.getByLabelText("Select CAND_0000001"));
    const compare = screen.getByRole("button", { name: /Compare/ });
    expect(compare).toBeDisabled();
    await userEvent.click(screen.getByLabelText("Select CAND_0000002"));
    expect(compare).toBeEnabled();
  });

  it("switches to card view and loads grounded summaries", async () => {
    mockFetch([
      ["/api/runs/run1/results", () => page],
      ["/api/runs/run1/facets", () => ({ countries: [], cities: [], branches: [], skills: [], flags: { none: 0, any: 0, critical: 0, warning: 0 },
        years: { min: null, max: null }, score: { min: null, max: null }, held_for_review: 0 })],
      ["/api/runs/run1/candidates/", () => explanation],
      ["/api/runs/run1", () => run],
    ]);
    at("/runs/run1", "/runs/:id", <RunPage />);
    await screen.findByText("Person 1");
    await userEvent.click(screen.getByLabelText("Cards"));
    expect((await screen.findAllByText(/meets 2 of 2 must-haves/)).length).toBeGreaterThan(0);
  });
});

describe("Candidate detail", () => {
  it("shows verified evidence, concerns, and missing information without treating it as negative", async () => {
    mockFetch([["/api/runs/run1/candidates/CAND_0000001", () => explanation]]);
    at("/runs/run1/candidates/CAND_0000001", "/runs/:id/candidates/:cid", <CandidatePage />);
    expect(await screen.findByRole("heading", { name: "Person 1" })).toBeInTheDocument();
    expect(screen.getByLabelText("verified")).toBeInTheDocument();
    expect(screen.getAllByText(/assessed 82\/100/).length).toBeGreaterThan(0);
    expect(screen.getByText("notice period 60 days (JD prefers <= 30)")).toBeInTheDocument();
    expect(screen.getByText(/Not held against the candidate/)).toBeInTheDocument();
    expect(screen.getByText("No GitHub account linked")).toBeInTheDocument();
  });

  it("explains why a candidate is held for review", async () => {
    mockFetch([["/api/runs/run1/candidates/CAND_0000001", () => ({ ...explanation, eligible: false, rank: 0, tone: "Held for review",
      ineligible_reason: "Critical profile inconsistency - needs human review" })]]);
    at("/runs/run1/candidates/CAND_0000001", "/runs/:id/candidates/:cid", <CandidatePage />);
    expect(await screen.findByText(/Held out of the shortlist/)).toBeInTheDocument();
  });
});

describe("New ranking workflow", () => {
  it("analyses a JD and starts a run for all eligible candidates", async () => {
    const calls = mockFetch([
      ["/api/datasets", () => [{ id: "ds1", name: "pool.jsonl", status: "ready", n_candidates: 1000, shared: true, job: null,
        source_kind: "library", size_bytes: 1, error: null, created_at: 0, updated_at: 0, fingerprint: null }]],
      ["/api/jd/presets", () => []],
      ["/api/taxonomy/concepts", () => []],
      ["/api/jd/parse", () => spec],
      ["/api/runs", () => ({ ...run, id: "newrun" })],
    ]);
    at("/rank/new", "/rank/new", <NewRankingPage />);
    const ta = await screen.findByLabelText("Job description text");
    fireEvent.change(ta, { target: { value: "Senior AI Engineer. Must have: Python, embeddings, ranking." } });
    await userEvent.click(screen.getByRole("button", { name: /Analyse requirements/ }));
    expect(await screen.findByText(/Review and adjust/)).toBeInTheDocument();
    const sizes = screen.getByRole("group", { name: "Shortlist size" });
    await userEvent.click(within(sizes).getByText("All eligible"));
    await userEvent.click(screen.getByRole("button", { name: /Rank candidates/ }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/api/runs") && c.init?.method === "POST")).toBe(true));
    const post = calls.find((c) => c.url.endsWith("/api/runs") && c.init?.method === "POST")!;
    expect(JSON.parse(String(post.init!.body)).shortlist_size).toBeNull();
    expect(await screen.findByText("navigated")).toBeInTheDocument();
  });
});
