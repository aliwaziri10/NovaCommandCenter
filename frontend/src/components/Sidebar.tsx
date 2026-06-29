import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  BarChart3,
  Factory,
  Lightbulb,
  DollarSign,
  Bot,
  X,
  Zap,
} from 'lucide-react'

const navItems = [
  { to: '/', label: 'CEO Dashboard', icon: LayoutDashboard },
  { to: '/kpi', label: 'KPI Dashboard', icon: BarChart3 },
  { to: '/content', label: 'Content Factory', icon: Factory },
  { to: '/topics', label: 'Topic Intelligence', icon: Lightbulb },
  { to: '/revenue', label: 'Revenue Center', icon: DollarSign },
  { to: '/agents', label: 'Agent Control', icon: Bot },
]

interface SidebarProps {
  open: boolean
  onClose: () => void
}

export default function Sidebar({ open, onClose }: SidebarProps) {
  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/60 md:hidden"
          onClick={onClose}
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-slate-800 bg-slate-900 transition-transform duration-200 md:static md:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex h-16 items-center justify-between border-b border-slate-800 px-4">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan-500/20">
              <Zap className="h-5 w-5 text-cyan-400" />
            </div>
            <div>
              <p className="text-sm font-bold text-white">Nova</p>
              <p className="text-xs text-slate-400">Command Center</p>
            </div>
          </div>
          <button onClick={onClose} className="md:hidden text-slate-400 hover:text-white">
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="flex-1 space-y-1 p-3">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={onClose}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                }`
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-slate-800 p-4">
          <div className="rounded-lg bg-slate-800/50 p-3">
            <p className="text-xs font-medium text-slate-300">System Status</p>
            <div className="mt-1 flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs text-emerald-400">All systems operational</span>
            </div>
          </div>
        </div>
      </aside>
    </>
  )
}
