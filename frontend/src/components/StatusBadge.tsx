const statusColors: Record<string, string> = {
  research: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  approved: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  archived: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
  draft: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
  review: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  planned: 'bg-violet-500/10 text-violet-400 border-violet-500/20',
  filming: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  editing: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  published: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  pending: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
  running: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
  completed: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  failed: 'bg-red-500/10 text-red-400 border-red-500/20',
  active: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  bronze: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  silver: 'bg-slate-400/10 text-slate-300 border-slate-400/20',
  gold: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
}

interface StatusBadgeProps {
  status: string
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  const colors = statusColors[status.toLowerCase()] || 'bg-slate-500/10 text-slate-400 border-slate-500/20'
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize ${colors}`}>
      {status}
    </span>
  )
}
