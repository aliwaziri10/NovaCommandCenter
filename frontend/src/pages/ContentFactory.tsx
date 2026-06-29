import { useEffect, useState } from 'react'
import { FileText, Video, Smartphone } from 'lucide-react'
import StatusBadge from '../components/StatusBadge'
import ChartCard from '../components/ChartCard'
import { fetchContentPipeline } from '../api/client'
import type { PipelineItem } from '../types'

export default function ContentFactory() {
  const [items, setItems] = useState<PipelineItem[]>([])
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('all')

  useEffect(() => {
    fetchContentPipeline()
      .then(d => setItems(d.items))
      .catch(() => setError('Failed to load content pipeline'))
  }, [])

  const filtered = items.filter(item => {
    if (filter === 'all') return true
    if (filter === 'scripts') return item.script !== null
    if (filter === 'videos') return item.video !== null
    if (filter === 'shorts') return item.shorts.length > 0
    return true
  })

  if (error) {
    return <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-4 text-red-400">{error}</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2">
        {['all', 'scripts', 'videos', 'shorts'].map(f => (
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

      <div className="grid gap-4 md:grid-cols-3">
        <ChartCard title="Scripts" subtitle={`${items.filter(i => i.script).length} total`}>
          <div className="flex items-center gap-3 mb-4">
            <FileText className="h-8 w-8 text-violet-400" />
            <div>
              <p className="text-2xl font-bold text-white">{items.filter(i => i.script?.status === 'approved').length}</p>
              <p className="text-xs text-slate-400">Approved</p>
            </div>
          </div>
        </ChartCard>
        <ChartCard title="Videos" subtitle={`${items.filter(i => i.video).length} total`}>
          <div className="flex items-center gap-3 mb-4">
            <Video className="h-8 w-8 text-cyan-400" />
            <div>
              <p className="text-2xl font-bold text-white">{items.filter(i => i.video?.status === 'published').length}</p>
              <p className="text-xs text-slate-400">Published</p>
            </div>
          </div>
        </ChartCard>
        <ChartCard title="Shorts" subtitle={`${items.reduce((acc, i) => acc + i.shorts.length, 0)} total`}>
          <div className="flex items-center gap-3 mb-4">
            <Smartphone className="h-8 w-8 text-emerald-400" />
            <div>
              <p className="text-2xl font-bold text-white">{items.reduce((acc, i) => acc + i.shorts.filter(s => s.status === 'published').length, 0)}</p>
              <p className="text-xs text-slate-400">Published</p>
            </div>
          </div>
        </ChartCard>
      </div>

      <div className="space-y-4">
        {filtered.length === 0 ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-8 text-center text-slate-500">
            No pipeline items found
          </div>
        ) : (
          filtered.map((item, idx) => (
            <div key={idx} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <div className="grid gap-4 md:grid-cols-3">
                <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <FileText className="h-4 w-4 text-violet-400" />
                    <span className="text-xs font-medium uppercase text-slate-400">Script</span>
                  </div>
                  {item.script ? (
                    <>
                      <p className="text-sm font-medium text-white">{item.script.title}</p>
                      <div className="mt-2"><StatusBadge status={item.script.status} /></div>
                    </>
                  ) : (
                    <p className="text-sm text-slate-500">No script</p>
                  )}
                </div>

                <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <Video className="h-4 w-4 text-cyan-400" />
                    <span className="text-xs font-medium uppercase text-slate-400">Video</span>
                  </div>
                  {item.video ? (
                    <>
                      <p className="text-sm font-medium text-white">{item.video.title}</p>
                      <div className="mt-2 flex items-center gap-2">
                        <StatusBadge status={item.video.status} />
                        <span className="text-xs text-slate-400">{item.video.views.toLocaleString()} views</span>
                      </div>
                    </>
                  ) : (
                    <p className="text-sm text-slate-500">No video</p>
                  )}
                </div>

                <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <Smartphone className="h-4 w-4 text-emerald-400" />
                    <span className="text-xs font-medium uppercase text-slate-400">Shorts</span>
                  </div>
                  {item.shorts.length > 0 ? (
                    <div className="space-y-2">
                      {item.shorts.map(short => (
                        <div key={short.id} className="flex items-center justify-between">
                          <p className="text-sm text-white truncate mr-2">{short.title}</p>
                          <StatusBadge status={short.status} />
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-slate-500">No shorts</p>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
