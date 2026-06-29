
import axios from 'axios'
import type {
  CEODashboard,
  KPIDashboard,
  Topic,
  Script,
  Video,
  Short,
  Sponsor,
  Revenue,
  Task,
  PipelineItem,
  RevenueSummary,
  AgentTasks,
} from '../types'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  headers: { 'Content-Type': 'application/json' },
})

export const fetchCEODashboard = () => api.get<CEODashboard>('/dashboard/ceo').then(r => r.data)
export const fetchKPIDashboard = () => api.get<KPIDashboard>('/dashboard/kpi').then(r => r.data)
export const fetchTopics = () => api.get<Topic[]>('/topics').then(r => r.data)
export const createTopic = (data: Partial<Topic>) => api.post<Topic>('/topics', data).then(r => r.data)
export const fetchContentPipeline = () => api.get<{ items: PipelineItem[] }>('/content/pipeline').then(r => r.data)
export const fetchRevenue = () => api.get<Revenue[]>('/revenue').then(r => r.data)
export const fetchRevenueSummary = () => api.get<RevenueSummary>('/revenue/summary').then(r => r.data)
export const fetchSponsors = () => api.get<Sponsor[]>('/sponsors').then(r => r.data)
export const fetchAgentTasks = () => api.get<AgentTasks>('/tasks/agents').then(r => r.data)
export const runTask = (id: string) => api.post<Task>(`/tasks/${id}/run`).then(r => r.data)
export const fetchScripts = () => api.get<Script[]>('/scripts').then(r => r.data)
export const fetchVideos = () => api.get<Video[]>('/videos').then(r => r.data)
export const fetchShorts = () => api.get<Short[]>('/shorts').then(r => r.data)

export default api
