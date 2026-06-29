import { useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import Header from '../components/Header'

const pageTitles: Record<string, { title: string; subtitle: string }> = {
  '/': { title: 'CEO Dashboard', subtitle: 'Executive overview and key metrics' },
  '/kpi': { title: 'KPI Dashboard', subtitle: 'Performance metrics and analytics' },
  '/content': { title: 'Content Factory', subtitle: 'Scripts, videos, and shorts pipeline' },
  '/topics': { title: 'Topic Intelligence', subtitle: 'Trend research and topic management' },
  '/revenue': { title: 'Revenue Center', subtitle: 'Sponsors and revenue tracking' },
  '/agents': { title: 'Agent Control Center', subtitle: 'AI agent task queue and monitoring' },
}

export default function DashboardLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()
  const page = pageTitles[location.pathname] || { title: 'Nova Command Center', subtitle: '' }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-950">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header
          title={page.title}
          subtitle={page.subtitle}
          onMenuClick={() => setSidebarOpen(true)}
        />
        <main className="flex-1 overflow-y-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
