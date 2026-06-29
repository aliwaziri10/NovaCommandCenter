import { useEffect, useState } from 'react'
import { Eye, DollarSign, Users, Percent } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts'
import StatCard from '../components/StatCard'
import ChartCard from '../components/ChartCard'
import { fetchKPIDashboard } from '../api/client'
import type { KPIDashboard } from '../types'

const COLORS = ['#06b6d4', '#10b981', '#8b5cf6', '#f59e0b']

function formatCurrency(n: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n)
}

function formatNumber(n: number) {
  return new Intl.NumberFormat('en-US', { notation: 'compact' }).format(n)
}

export default function KPIDashboard() {
  const [data, setData] = useState<KPIDashboard | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    fetchKPIDashboard()
      .then(setData)
      .catch(() => setError('Failed to load KPI data'))
  }, [])

  if (error) {
    return <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-4 text-red-400">{error}</div>
  }

  if (!data) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-28 animate-pulse rounded-xl bg-slate-800/50" />
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total Views" value={formatNumber(data.total_views)} change="+8.2% this week" positive icon={Eye} accent="cyan" />
        <StatCard label="Total Revenue" value={formatCurrency(data.total_revenue)} change="+12.5% this month" positive icon={DollarSign} accent="emerald" />
        <StatCard label="Subscribers" value={formatNumber(data.total_subscribers)} change="+1,240 new" positive icon={Users} accent="violet" />
        <StatCard label="Conversion Rate" value={`${data.conversion_rate.toFixed(2)}%`} change="+0.3% vs avg" positive icon={Percent} accent="amber" />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard title="Weekly Performance" subtitle="Revenue and views">
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={data.weekly_stats}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="day" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }} />
              <Bar dataKey="revenue" fill="#06b6d4" radius={[4, 4, 0, 0]} name="Revenue" />
              <Bar dataKey="views" fill="#10b981" radius={[4, 4, 0, 0]} name="Views" />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Platform Breakdown" subtitle="Views by platform">
          <ResponsiveContainer width="100%" height={280}>
            <PieChart>
              <Pie
                data={data.platform_breakdown}
                dataKey="views"
                nameKey="platform"
                cx="50%"
                cy="50%"
                outerRadius={100}
                label={({ platform, percent }) => `${platform} ${(percent * 100).toFixed(0)}%`}
              >
                {data.platform_breakdown.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }} />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  )
}
