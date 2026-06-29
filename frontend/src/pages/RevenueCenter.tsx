import { useEffect, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import DataTable from '../components/DataTable'
import StatusBadge from '../components/StatusBadge'
import ChartCard from '../components/ChartCard'
import StatCard from '../components/StatCard'
import { DollarSign, Building2, TrendingUp } from 'lucide-react'
import { fetchRevenue, fetchRevenueSummary, fetchSponsors } from '../api/client'
import type { Revenue, RevenueSummary, Sponsor } from '../types'

function formatCurrency(n: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n)
}

export default function RevenueCenter() {
  const [revenue, setRevenue] = useState<Revenue[]>([])
  const [summary, setSummary] = useState<RevenueSummary | null>(null)
  const [sponsors, setSponsors] = useState<Sponsor[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([fetchRevenue(), fetchRevenueSummary(), fetchSponsors()])
      .then(([rev, sum, sp]) => {
        setRevenue(rev)
        setSummary(sum)
        setSponsors(sp)
      })
      .catch(() => setError('Failed to load revenue data'))
  }, [])

  if (error) {
    return <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-4 text-red-400">{error}</div>
  }

  const totalRevenue = revenue.reduce((acc, r) => acc + Number(r.amount), 0)

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard label="Total Revenue" value={formatCurrency(totalRevenue)} change="All time" positive icon={DollarSign} accent="emerald" />
        <StatCard label="Active Sponsors" value={sponsors.filter(s => s.status === 'active').length} icon={Building2} accent="cyan" />
        <StatCard label="Revenue Streams" value={summary?.by_type.length ?? 0} icon={TrendingUp} accent="violet" />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        {sponsors.map(sponsor => (
          <div key={sponsor.id} className="rounded-xl border border-slate-800 bg-slate-900/80 p-5">
            <div className="flex items-start justify-between">
              <div>
                <p className="font-semibold text-white">{sponsor.name}</p>
                <p className="text-xs text-slate-400 mt-1">{sponsor.contact_email}</p>
              </div>
              <StatusBadge status={sponsor.tier} />
            </div>
            <div className="mt-3">
              <StatusBadge status={sponsor.status} />
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {summary && (
          <>
            <ChartCard title="Monthly Revenue">
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={summary.monthly_totals}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="month" stroke="#64748b" fontSize={11} />
                  <YAxis stroke="#64748b" fontSize={12} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                    formatter={(v: number) => [formatCurrency(v), 'Revenue']}
                  />
                  <Bar dataKey="total" fill="#10b981" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Revenue by Type">
              <div className="space-y-4">
                {summary.by_type.map(item => (
                  <div key={item.type}>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-slate-400 capitalize">{item.type}</span>
                      <span className="font-medium text-white">{formatCurrency(item.total)}</span>
                    </div>
                    <div className="h-2 rounded-full bg-slate-800">
                      <div
                        className="h-2 rounded-full bg-cyan-500"
                        style={{ width: `${(item.total / totalRevenue) * 100}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </ChartCard>
          </>
        )}
      </div>

      <ChartCard title="Revenue Entries">
        <DataTable
          data={revenue.slice(0, 20)}
          columns={[
            { key: 'date', label: 'Date' },
            { key: 'type', label: 'Type', render: (row) => <span className="capitalize">{String(row.type)}</span> },
            { key: 'amount', label: 'Amount', render: (row) => <span className="font-medium text-emerald-400">{formatCurrency(Number(row.amount))}</span> },
          ]}
        />
      </ChartCard>
    </div>
  )
}
