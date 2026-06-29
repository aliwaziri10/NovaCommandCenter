import type { LucideIcon } from 'lucide-react'

interface StatCardProps {
  label: string
  value: string | number
  change?: string
  positive?: boolean
  icon: LucideIcon
  accent?: 'cyan' | 'emerald' | 'violet' | 'amber'
}

const accentClasses = {
  cyan: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
  emerald: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  violet: 'bg-violet-500/10 text-violet-400 border-violet-500/20',
  amber: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
}

export default function StatCard({ label, value, change, positive, icon: Icon, accent = 'cyan' }: StatCardProps) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-slate-400">{label}</p>
          <p className="mt-1 text-2xl font-bold text-white">{value}</p>
          {change && (
            <p className={`mt-1 text-xs ${positive ? 'text-emerald-400' : 'text-red-400'}`}>
              {change}
            </p>
          )}
        </div>
        <div className={`rounded-lg border p-2.5 ${accentClasses[accent]}`}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  )
}
