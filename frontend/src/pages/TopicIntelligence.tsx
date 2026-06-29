import { useEffect, useState } from 'react'
import { Plus, X } from 'lucide-react'
import DataTable from '../components/DataTable'
import StatusBadge from '../components/StatusBadge'
import { fetchTopics, createTopic } from '../api/client'
import type { Topic } from '../types'

export default function TopicIntelligence() {
  const [topics, setTopics] = useState<Topic[]>([])
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('all')
  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState({ title: '', category: '', trend_score: 50, status: 'research', notes: '' })

  const loadTopics = () => {
    fetchTopics()
      .then(setTopics)
      .catch(() => setError('Failed to load topics'))
  }

  useEffect(() => { loadTopics() }, [])

  const filtered = topics.filter(t => filter === 'all' || t.status === filter)

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await createTopic(form)
      setShowModal(false)
      setForm({ title: '', category: '', trend_score: 50, status: 'research', notes: '' })
      loadTopics()
    } catch {
      setError('Failed to create topic')
    }
  }

  const categories = [...new Set(topics.map(t => t.category))]

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap gap-2">
          {['all', 'research', 'approved', 'archived'].map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-lg px-4 py-2 text-sm font-medium capitalize transition-colors ${
                filter === f
                  ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                  : 'bg-slate-800 text-slate-400 hover:text-white border border-slate-700'
              }`}
            >
              {f}
            </button>
          ))}
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 transition-colors"
        >
          <Plus className="h-4 w-4" />
          Add Topic
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-4 text-red-400">{error}</div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {categories.map(cat => (
          <div key={cat} className="rounded-xl border border-slate-800 bg-slate-900/80 p-4">
            <p className="text-xs text-slate-400">{cat}</p>
            <p className="text-2xl font-bold text-white">{topics.filter(t => t.category === cat).length}</p>
          </div>
        ))}
      </div>

      <DataTable
        data={filtered}
        columns={[
          { key: 'title', label: 'Title' },
          { key: 'category', label: 'Category' },
          {
            key: 'trend_score',
            label: 'Trend Score',
            render: (row) => (
              <span className={`font-bold ${row.trend_score >= 80 ? 'text-emerald-400' : row.trend_score >= 60 ? 'text-cyan-400' : 'text-slate-400'}`}>
                {Number(row.trend_score).toFixed(1)}
              </span>
            ),
          },
          { key: 'status', label: 'Status', render: (row) => <StatusBadge status={String(row.status)} /> },
          { key: 'notes', label: 'Notes', render: (row) => <span className="text-slate-400 truncate max-w-xs block">{String(row.notes || '—')}</span> },
        ]}
      />

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-900 p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-white">Add Topic</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white">
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleCreate} className="space-y-4">
              <input
                required
                placeholder="Title"
                value={form.title}
                onChange={e => setForm({ ...form, title: e.target.value })}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white placeholder-slate-500 outline-none focus:border-cyan-500"
              />
              <input
                required
                placeholder="Category"
                value={form.category}
                onChange={e => setForm({ ...form, category: e.target.value })}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white placeholder-slate-500 outline-none focus:border-cyan-500"
              />
              <input
                type="number"
                placeholder="Trend Score"
                value={form.trend_score}
                onChange={e => setForm({ ...form, trend_score: Number(e.target.value) })}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white placeholder-slate-500 outline-none focus:border-cyan-500"
              />
              <textarea
                placeholder="Notes"
                value={form.notes}
                onChange={e => setForm({ ...form, notes: e.target.value })}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white placeholder-slate-500 outline-none focus:border-cyan-500"
                rows={3}
              />
              <button type="submit" className="w-full rounded-lg bg-cyan-500 py-2 text-sm font-medium text-white hover:bg-cyan-600">
                Create Topic
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
