export interface Topic {
  id: string
  title: string
  category: string
  trend_score: number
  status: string
  notes?: string | null
  created_at: string
  updated_at: string
}

export interface Script {
  id: string
  title: string
  content: string
  status: string
  topic_id?: string | null
  created_at: string
  updated_at: string
}

export interface Video {
  id: string
  title: string
  status: string
  views: number
  topic_id?: string | null
  script_id?: string | null
  created_at: string
  updated_at: string
}

export interface Short {
  id: string
  title: string
  platform: string
  status: string
  views: number
  video_id?: string | null
  created_at: string
  updated_at: string
}

export interface Sponsor {
  id: string
  name: string
  contact_email: string
  tier: string
  status: string
  created_at: string
  updated_at: string
}

export interface Revenue {
  id: string
  amount: number
  type: string
  date: string
  sponsor_id?: string | null
  created_at: string
  updated_at: string
}

export interface Task {
  id: string
  title: string
  agent_name: string
  status: string
  priority: number
  payload?: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface AgentSummary {
  agent_name: string
  pending: number
  running: number
  completed: number
  failed: number
}

export interface CEODashboard {
  total_revenue: number
  active_topics: number
  pipeline: {
    scripts: number
    videos: number
    shorts: number
    published_videos: number
    published_shorts: number
  }
  agents: AgentSummary[]
  top_topics: Topic[]
  revenue_trend: { month: string; total: number }[]
}

export interface KPIDashboard {
  total_views: number
  total_revenue: number
  total_subscribers: number
  conversion_rate: number
  weekly_stats: { day: string; revenue: number; views: number }[]
  platform_breakdown: { platform: string; views: number }[]
}

export interface PipelineItem {
  script: Script | null
  video: Video | null
  shorts: Short[]
}

export interface RevenueSummary {
  monthly_totals: { month: string; total: number }[]
  by_sponsor: { sponsor: string; total: number }[]
  by_type: { type: string; total: number }[]
}

export interface AgentTasks {
  agents: AgentSummary[]
  tasks: Task[]
}
