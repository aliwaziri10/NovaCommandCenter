import { useEffect, useState } from 'react'
import { Play, RefreshCw, Bot } from 'lucide-react'
import DataTable from '../components/DataTable'
import StatusBadge from '../components/StatusBadge'
import ChartCard from '../components/ChartCard'
import { fetchAgentTasks, runTask } from '../api/client'
import type { AgentTasks, Task } from '../types'

export default function AgentControlCenter() {
  const [data, setData] = useState<AgentTasks | null>(null)
  const [error, setError] = useState('')
  const [running, setRunning] = useState<string | null>(null)

  const load = () => {
    fetchAgentTasks()
      .then(setData)
      .catch(() => setError('Failed to load agent tasks'))
  }

  useEffect(() => { load() }, [])

  const handleRun = async (task: Task) => {
    setRunning(task.id)
    try {
      await runTask(task.id)
      load()
    } catch {
      setError('Failed to run task')
    } finally {
      setRunning(null)
    }
  }

  if (error) {
    return <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-4 text-red-400">{error}</div>
  }

  if (!data) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-32 animate-pulse rounded-xl bg-slate-800/50" />
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.agents.map(agent => (
          <div key={agent.agent_name} className="rounded-xl border border-slate-800 bg-slate-900/80 p-5">
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-500/10">
                <Bot className="h-5 w-5 text-cyan-400" />
              </div>
              <div>
                <p className="font-semibold text-white">{agent.agent_name}</p>
                <p className="text-xs text-slate-400">
                  {agent.pending + agent.running} active tasks
                </p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 text-center">
              <div className="rounded-lg bg-slate-800/50 p-2">
                <p className="text-lg font-bold text-slate-300">{agent.pending}</p>
                <p className="text-xs text-slate-500">Pending</p>
              </div>
              <div className="rounded-lg bg-slate-800/50 p-2">
                <p className="text-lg font-bold text-cyan-400">{agent.running}</p>
                <p className="text-xs text-slate-500">Running</p>
              </div>
              <div className="rounded-lg bg-slate-800/50 p-2">
                <p className="text-lg font-bold text-emerald-400">{agent.completed}</p>
                <p className="text-xs text-slate-500">Completed</p>
              </div>
              <div className="rounded-lg bg-slate-800/50 p-2">
                <p className="text-lg font-bold text-red-400">{agent.failed}</p>
                <p className="text-xs text-slate-500">Failed</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      <ChartCard title="Task Queue" subtitle={`${data.tasks.length} total tasks`}>
        <DataTable
          data={data.tasks}
          columns={[
            { key: 'title', label: 'Task' },
            { key: 'agent_name', label: 'Agent' },
            { key: 'priority', label: 'Priority', render: (row) => (
              <span className={`font-medium ${Number(row.priority) >= 3 ? 'text-amber-400' : 'text-slate-400'}`}>
                P{String(row.priority)}
              </span>
            )},
            { key: 'status', label: 'Status', render: (row) => <StatusBadge status={String(row.status)} /> },
            {
              key: 'actions',
              label: 'Actions',
              render: (row: Task) => (
                <div className="flex gap-2">
                  {(row.status === 'pending' || row.status === 'failed') && (
                    <button
                      onClick={() => handleRun(row)}
                      disabled={running === row.id}
                      className="flex items-center gap-1 rounded-lg bg-cyan-500/10 px-2 py-1 text-xs text-cyan-400 hover:bg-cyan-500/20 disabled:opacity-50"
                    >
                      <Play className="h-3 w-3" />
                      Run
                    </button>
                  )}
                  {row.status === 'failed' && (
                    <button
                      onClick={() => handleRun(row)}
                      className="flex items-center gap-1 rounded-lg bg-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-600"
                    >
                      <RefreshCw className="h-3 w-3" />
                      Retry
                    </button>
                  )}
                </div>
              ),
            },
          ]}
        />
      </ChartCard>
    </div>
  )
}
