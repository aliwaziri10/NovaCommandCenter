import { Routes, Route, Navigate } from 'react-router-dom'
import DashboardLayout from './layouts/DashboardLayout'
import CEODashboard from './pages/CEODashboard'
import KPIDashboard from './pages/KPIDashboard'
import ContentFactory from './pages/ContentFactory'
import TopicIntelligence from './pages/TopicIntelligence'
import RevenueCenter from './pages/RevenueCenter'
import AgentControlCenter from './pages/AgentControlCenter'

export default function App() {
  return (
    <Routes>
      <Route element={<DashboardLayout />}>
        <Route index element={<CEODashboard />} />
        <Route path="kpi" element={<KPIDashboard />} />
        <Route path="content" element={<ContentFactory />} />
        <Route path="topics" element={<TopicIntelligence />} />
        <Route path="revenue" element={<RevenueCenter />} />
        <Route path="agents" element={<AgentControlCenter />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
