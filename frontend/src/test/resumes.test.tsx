import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ResumeBatchPage } from "../pages/ResumesPage";
import ResumeReviewPage from "../pages/ResumeReviewPage";
import { ToastProvider } from "../components/ui";
import type { CandidateRecord, Fact, ResumeBatch, ResumeDocument } from "../types/api";
import { mockFetch } from "./fixtures";

function at(path: string, routePath: string, el: JSX.Element) {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path={routePath} element={el} /><Route path="*" element={<div>navigated</div>} /></Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

const fact = <T,>(value: T | null, status: Fact["status"] = "stated", line = 1, page: number | null = 1): Fact<T> =>
  ({ value, status, source: status === "missing" ? null : { page, line, text: String(value) }, note: status === "inferred" ? "rule" : null });

const batch: ResumeBatch = {
  id: "b1", name: "Autumn hiring", last_dataset_id: null, created_at: 1, updated_at: 1, job: null, last_dataset: null,
  counts: { queued: 0, processing: 0, needs_review: 3, approved: 2, rejected: 1, failed: 4, duplicate: 1, total: 11, processed: 6 },
};

const record: CandidateRecord = {
  candidate_id: "RES_b1_d1",
  profile: { anonymized_name: "Asha Verma", headline: "ML Engineer", summary: "Builds ranking systems.", location: "Bengaluru",
    country: "India", years_of_experience: 7, current_title: "ML Engineer", current_company: "Nimbus", current_company_size: null,
    current_industry: "" },
  career_history: [{ company: "Nimbus", title: "ML Engineer", start_date: "2021-01-01", end_date: null, duration_months: 71,
    is_current: true, industry: "", description: "Built retrieval." }],
  education: [],
  skills: [{ name: "Python", proficiency: null, endorsements: null, duration_months: null }],
  certifications: [],
  redrob_signals: { skill_assessment_scores: {} },
};

const docBody = (): ResumeDocument => ({
  id: "d1", batch_id: "b1", filename: "asha.pdf", kind: "pdf", size_bytes: 3000, status: "needs_review", error_code: null,
  error: null, duplicate_of: null, possible_duplicate_of: null, candidate_id: "RES_b1_d1", display_name: "Asha Verma",
  title: "ML Engineer", n_pages: 2, n_warnings: 1, edited: 0, created_at: 1, updated_at: 1, has_original: true,
  text_pages: [["Asha Verma", "ML Engineer", "asha@example.com"], ["Skills", "Python"]],
  record: JSON.parse(JSON.stringify(record)), parsed_record: JSON.parse(JSON.stringify(record)), edited_fields: [], issues: [],
  extraction: {
    parser_version: 1, document: { kind: "pdf", pages: 2, redacted_lines: 1 },
    identity: { name: fact("Asha Verma"), headline: fact("ML Engineer", "stated", 2), location: fact("Bengaluru", "stated", 3),
      country: fact("India", "inferred", 3) },
    contact: { emails: [fact("asha@example.com", "stated", 3)], phones: [], links: [] },
    summary: fact("Builds ranking systems.", "stated", 4), years_of_experience: fact(7, "inferred", 5),
    current_title: fact("ML Engineer", "stated", 2), current_company: fact<string>(null, "missing"),
    experience: [{ title: fact("ML Engineer"), company: fact("Nimbus"), start_date: fact("2021-01-01"), end_date: fact<string>(null),
      is_current: fact(true), duration_months: fact(71, "inferred"), description: fact("Built retrieval.") }],
    education: [], skills: [{ name: fact("Python", "stated", 2, 2), proficiency: fact<string>(null, "missing") }], certifications: [],
    projects: [], achievements: [], sections_found: ["experience", "skills"],
    warnings: ["Stated experience differs from the listed roles."],
  },
});

describe("Resume batch dashboard", () => {
  it("shows uploaded / processed / awaiting-review / failed counters and the documents", async () => {
    const calls = mockFetch([
      ["/api/resume-batches/b1/documents", () => ({ total: 2, items: [
        { ...docBody(), text_pages: undefined, extraction: undefined },
        { ...docBody(), id: "d2", filename: "scan.pdf", status: "failed", error_code: "no_text_layer", candidate_id: null,
          display_name: null, error: "No extractable text was found. OCR is not supported." }] })],
      ["/api/resume-batches/b1/approve-clean", () => ({ approved: 2 })],
      ["/api/resume-batches/b1", () => batch],
    ]);
    at("/resumes/b1", "/resumes/:id", <ResumeBatchPage />);
    expect(await screen.findByRole("heading", { name: "Autumn hiring" })).toBeInTheDocument();
    const stats = screen.getByLabelText("Processing status");
    expect(stats).toHaveTextContent("Uploaded11");
    expect(stats).toHaveTextContent("Processed6");
    expect(stats).toHaveTextContent("Awaiting review3");
    expect(stats).toHaveTextContent("Failed4");
    expect(await screen.findByText(/OCR is not supported/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review" })).toHaveAttribute("href", "/resumes/b1/documents/d1");
    await userEvent.click(screen.getByRole("button", { name: /Approve all without warnings/ }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("approve-clean") && c.init?.method === "POST")).toBe(true));
    expect(screen.getByRole("button", { name: /Publish 2 approved/ })).toBeEnabled();
  });
});

describe("Resume review", () => {
  it("labels each value as stated / inferred / missing, links to the source line, and saves corrections", async () => {
    let patched: any = null;
    const calls = mockFetch([
      ["/api/resume-documents/d1/approve", () => ({ ...docBody(), status: "approved" })],
      ["/api/resume-documents/d1", (_u, init) => {
        if (init?.method === "PATCH") {
          patched = JSON.parse(String(init.body));
          return { ...docBody(), record: patched.record, edited: 1, edited_fields: ["profile.current_company"] };
        }
        return docBody();
      }],
    ]);
    at("/resumes/b1/documents/d1", "/resumes/:bid/documents/:did", <ResumeReviewPage />);
    expect(await screen.findByRole("heading", { name: "Asha Verma" })).toBeInTheDocument();
    expect(screen.getByText(/Stated experience differs/)).toBeInTheDocument();
    expect(screen.getByText(/not copied into the candidate profile/)).toBeInTheDocument();
    expect(screen.getByText("asha@example.com", { selector: ".mono" })).toBeInTheDocument();

    const company = screen.getByLabelText("Current company");
    expect(company.closest("label")).toHaveTextContent("missing");
    expect(screen.getByLabelText("Country").closest("label")).toHaveTextContent("inferred");
    expect(screen.getByLabelText("Name").closest("label")).toHaveTextContent("stated");

    // clicking a source chip highlights that page/line in the extracted text
    const src = screen.getAllByRole("button", { name: "p.2 · l.2" })[0];
    fireEvent.click(src);
    expect(document.querySelector('[data-loc="2-2"]')).toHaveStyle({ background: "var(--signal-soft)" });

    await userEvent.clear(company);
    await userEvent.type(company, "Nimbus Retail Labs");
    await userEvent.click(screen.getByRole("button", { name: /Save corrections/ }));
    await waitFor(() => expect(patched?.record.profile.current_company).toBe("Nimbus Retail Labs"));
    await waitFor(() => expect(screen.getByLabelText("Current company").closest("label")).toHaveTextContent("edited"));
    await userEvent.click(screen.getByRole("button", { name: /^Approve$/ }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/d1/approve"))).toBe(true));
  });

  it("shows the failure reason for a document that could not be read", async () => {
    mockFetch([["/api/resume-documents/d2", () => ({ ...docBody(), id: "d2", status: "failed", error_code: "no_text_layer",
      error: "The PDF appears to be scanned; OCR is not supported.", record: undefined, extraction: undefined, text_pages: [] })]]);
    at("/resumes/b1/documents/d2", "/resumes/:bid/documents/:did", <ResumeReviewPage />);
    expect(await screen.findByText(/OCR is not supported/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Original/ })).toBeInTheDocument();
  });
});
