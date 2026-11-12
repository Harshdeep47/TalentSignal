import { Route, Routes } from "react-router-dom";
import Shell from "./layouts/Shell";
import { ToastProvider } from "./components/ui";
import DashboardPage from "./pages/DashboardPage";
import DatasetsPage from "./pages/DatasetsPage";
import DatasetDetailPage from "./pages/DatasetDetailPage";
import NewRankingPage from "./pages/NewRankingPage";
import RunPage from "./pages/RunPage";
import CandidatePage from "./pages/CandidatePage";
import ComparePage from "./pages/ComparePage";
import HistoryPage from "./pages/HistoryPage";
import { ShortlistsPage, ShortlistDetailPage } from "./pages/ShortlistsPage";
import ResumesPage, { ResumeBatchPage } from "./pages/ResumesPage";
import ResumeReviewPage from "./pages/ResumeReviewPage";
import { Empty } from "./components/ui";

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<DashboardPage />} />
          <Route path="datasets" element={<DatasetsPage />} />
          <Route path="datasets/:id" element={<DatasetDetailPage />} />
          <Route path="rank/new" element={<NewRankingPage />} />
          <Route path="runs/:id" element={<RunPage />} />
          <Route path="runs/:id/candidates/:cid" element={<CandidatePage />} />
          <Route path="runs/:id/compare" element={<ComparePage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="shortlists" element={<ShortlistsPage />} />
          <Route path="shortlists/:id" element={<ShortlistDetailPage />} />
          <Route path="resumes" element={<ResumesPage />} />
          <Route path="resumes/:id" element={<ResumeBatchPage />} />
          <Route path="resumes/:bid/documents/:did" element={<ResumeReviewPage />} />
          <Route path="*" element={<Empty title="Page not found">The link may be out of date.</Empty>} />
        </Route>
      </Routes>
    </ToastProvider>
  );
}
