import type {
  DownloadInfo,
  GlossaryEntry,
  GlossaryEntryInput,
  JobDetail,
  JobListItem,
  JobLog,
  JobStep,
  ProviderConfig,
  ProviderConfigCreate,
  ProviderConfigUpdate,
  ProviderConnectionResult,
  ProviderConnectionTest,
  ProviderModelsResult,
  TranslationPreviewRequest,
  TranslationPreviewResponse,
  TranslationSettings,
  TranslationSettingsUpdate,
} from './types'

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '')
const API_PREFIX = `${API_BASE}/api/v1`

async function parseError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      return body.detail.map((item: { msg?: string; type?: string }) => item.msg || item.type || 'Validation error').join(', ')
    }
  } catch {
    // Fall through to the HTTP status text below.
  }
  return response.statusText || `HTTP ${response.status}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  })

  if (!response.ok) {
    throw new Error(await parseError(response))
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export const api = {
  listJobs: () => request<JobListItem[]>('/jobs'),
  createJob: (body: FormData) =>
    request<{ job_id: string }>('/jobs', {
      method: 'POST',
      body,
    }),
  getJob: (id: string) => request<JobDetail>(`/jobs/${id}`),
  getJobSteps: (id: string) => request<{ steps: JobStep[] }>(`/jobs/${id}/steps`),
  getJobLogs: (id: string) => request<{ logs: JobLog[] }>(`/jobs/${id}/logs`),
  getJobGlossary: (id: string) => request<{ entries: GlossaryEntry[] }>(`/jobs/${id}/glossary`),
  updateJobGlossary: (id: string, entries: GlossaryEntryInput[]) =>
    request<{ entries: GlossaryEntry[] }>(`/jobs/${id}/glossary`, {
      method: 'PUT',
      body: JSON.stringify({ entries }),
    }),
  approveJobGlossary: (id: string, entries: GlossaryEntryInput[]) =>
    request<JobDetail>(`/jobs/${id}/glossary/approve`, {
      method: 'POST',
      body: JSON.stringify({ entries }),
    }),
  cancelJob: (id: string) =>
    request<JobDetail>(`/jobs/${id}/cancel`, {
      method: 'POST',
    }),
  getDownload: (id: string) => request<DownloadInfo>(`/jobs/${id}/download`),

  listProviderConfigs: () => request<ProviderConfig[]>('/provider-configs'),
  createProviderConfig: (body: ProviderConfigCreate) =>
    request<ProviderConfig>('/provider-configs', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateProviderConfig: (id: string, body: ProviderConfigUpdate) =>
    request<ProviderConfig>(`/provider-configs/${id}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  deleteProviderConfig: (id: string) =>
    request<void>(`/provider-configs/${id}`, {
      method: 'DELETE',
    }),
  setDefaultProviderConfig: (id: string) =>
    request<ProviderConfig>(`/provider-configs/${id}/default`, {
      method: 'POST',
    }),
  testProviderConnection: (body: ProviderConnectionTest) =>
    request<ProviderConnectionResult>('/provider-configs/test', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  listProviderModels: (id: string) => request<ProviderModelsResult>(`/provider-configs/${id}/models`),

  translatePreview: (body: TranslationPreviewRequest) =>
    request<TranslationPreviewResponse>('/translation-preview', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getTranslationSettings: () => request<TranslationSettings>('/settings/translation'),
  updateTranslationSettings: (body: TranslationSettingsUpdate) =>
    request<TranslationSettings>('/settings/translation', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
}
