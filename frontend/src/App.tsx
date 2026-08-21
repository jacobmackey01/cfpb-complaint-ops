import { Navigate, Route, Routes } from 'react-router-dom';
import { AppChrome } from './components/Chrome';
import { CasePage } from './pages/CasePage';
import { DashboardPage } from './pages/DashboardPage';
import { ModelPage } from './pages/ModelPage';
import { QueuePage } from './pages/QueuePage';

const App = () => (
  <AppChrome>
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/queue" element={<QueuePage />} />
      <Route path="/cases/:caseId" element={<CasePage />} />
      <Route path="/model" element={<ModelPage />} />
      <Route path="*" element={<Navigate replace to="/" />} />
    </Routes>
  </AppChrome>
);

export default App;
