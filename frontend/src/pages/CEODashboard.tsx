import { useEffect, useState } from 'react'
import { DollarSign, Lightbulb, Film, Bot, TrendingUp } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import StatCard from '../components/StatCard'
import ChartCard from '../components/ChartCard'
import StatusBadge from '../components/StatusBadge'
import { fetchCEODashboard } from '../api/client'
import type { CEODashboard } from '../types'

function formatCurrency(n: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n)
}

export default function CEODashboard() {
  const [data, setData] = useState<CEODashboard | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    fetchCEODashboard()
      .then(setData)
      .catch(() => setError('Failed to load dashboard data'))
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
        <StatCard label="Total Revenue" value={formatCurrency(data.total_revenue)} change="+12.5% vs last month" positive icon={DollarSign} accent="emerald" />
        <StatCard label="Active Topics" value={data.active_topics} change="3 new this week" positive icon={Lightbulb} accent="cyan" />
        <StatCard label="Published Content" value={data.pipeline.published_videos + data.pipeline.published_shorts} change={`${data.pipeline.published_videos} videos, ${data.pipeline.published_shorts} shorts`} positive icon={Film} accent="violet" />
        <StatCard label="Active Agents" value={data.agents.filter(a => a.running > 0).length} change={`${data.agents.length} agents total`} icon={Bot} accent="amber" />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ChartCard title="Revenue Trend" subtitle="Last 6 months">
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={data.revenue_trend}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="month" stroke="#64748b" fontSize={12} />
                <YAxis stroke="#64748b" fontSize={12} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                  labelStyle={{ color: '#94a3b8' }}
                  formatter={(v: number) => [formatCurrency(v), 'Revenue']}
                />
                <Line type="monotone" dataKey="total" stroke="#06b6d4" strokeWidth={2} dot={{ fill: '#06b6d4', r: 4 }} />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
        </div>

        <ChartCard title="Content Pipeline">
          <div className="space-y-4">
            {[
              { label: 'Scripts', count: data.pipeline.scripts, color: 'bg-violet-500' },
              { label: 'Videos', count: data.pipeline.videos, color: 'bg-cyan-500' },
              { label: 'Shorts', count: data.pipeline.shorts, color: 'bg-emerald-500' },
            ].map(item => (
              <div key={item.label}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-slate-400">{item.label}</span>
                  <span className="font-medium text-white">{item.count}</span>
                </div>
                <div className="h-2 rounded-full bg-slate-800">
                  <div
                    className={`h-2 rounded-full ${item.color}`}
                    style={{ width: `${Math.min((item.count / Math.max(data.pipeline.scripts, 1)) * 100, 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </ChartCard>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard title="Top Topics" subtitle="By trend score">
          <div className="space-y-3">
            {data.top_topics.map(topic => (
              <div key={topic.id} className="flex items-center justify-between rounded-lg bg-slate-800/50 px-4 py-3">
                <div className="flex items-center gap-3">
                  <TrendingUp className="h-4 w-4 text-cyan-400" />
                  <div>
                    <p className="text-sm font-medium text-white">{topic.title}</p>
                    <p className="text-xs text-slate-400">{topic.category}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-sm font-bold text-cyan-400">{topic.trend_score.toFixed(1)}</span>
                  <StatusBadge status={topic.status} />
                </div>
              </div>
            ))}
          </div>
        </ChartCard>

        <ChartCard title="Agent Status">
          <div className="space-y-3">
            {data.agents.map(agent => (
              <div key={agent.agent_name} className="rounded-lg bg-slate-800/50 px-4 py-3">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-sm font-medium text-white">{agent.agent_name}</p>
                  {agent.running > 0 && <StatusBadge status="running" />}
                </div>
                <div className="grid grid-cols-4 gap-2 text-center text-xs">
                  <div><p className="text-slate-500">Pending</p><p className="font-medium text-slate-300">{agent.pending}</p></div>
                  <div><p className="text-slate-500">Running</p><p className="font-medium text-cyan-400">{agent.running}</p></div>
                  <div><p className="text-slate-500">Done</p><p className="font-medium text-emerald-400">{agent.completed}</p></div>
                  <div><p className="text-slate-500">Failed</p><p className="font-medium text-red-400">{agent.failed}</p></div>
                </div>
              </div>
            ))}
          </div>
        </ChartCard>
      </div>
    </div>
  )
}
