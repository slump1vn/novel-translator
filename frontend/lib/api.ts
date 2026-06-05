import type {
  DownloadInfo,
  AuthUser,
  EpubAiSplitProgressResponse,
  EpubAiSplitTaskCreated,
  EpubChaptersResponse,
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
  LoginResponse,
  UserCreate,
  UserUpdate,
} from './types'

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '')
const API_PREFIX = `${API_BASE}/api/v1`
export const AUTH_TOKEN_KEY = 'convertvn_token'

export function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem(AUTH_TOKEN_KEY)
}

export function setAuthToken(token: string): void {
  if (typeof window !== 'undefined') window.localStorage.setItem(AUTH_TOKEN_KEY, token)
}

export function clearAuthToken(): void {
  if (typeof window !== 'undefined') window.localStorage.removeItem(AUTH_TOKEN_KEY)
}

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
  const token = getAuthToken()
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
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

function resolveDownloadFilename(response: Response, fallbackFilename: string): string {
  const contentDisposition = response.headers.get('Content-Disposition')
  if (!contentDisposition) return fallbackFilename

  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1])
    } catch {
      return utf8Match[1]
    }
  }

  const asciiMatch = contentDisposition.match(/filename="([^"]+)"/i)
  return asciiMatch?.[1] || fallbackFilename
}

async function download(path: string, fallbackFilename: string): Promise<void> {
  const token = getAuthToken()
  const response = await fetch(`${API_PREFIX}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })

  if (!response.ok) {
    throw new Error(await parseError(response))
  }

  const blob = await response.blob()
  const objectUrl = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = resolveDownloadFilename(response, fallbackFilename)
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(objectUrl)
}

export const api = {
  login: (username: string, password: string) =>
    request<LoginResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  me: () => request<AuthUser>('/auth/me'),
  listUsers: () => request<AuthUser[]>('/auth/users'),
  createUser: (body: UserCreate) =>
    request<AuthUser>('/auth/users', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateUser: (id: string, body: UserUpdate) =>
    request<AuthUser>(`/auth/users/${id}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  deleteUser: (id: string) =>
    request<void>(`/auth/users/${id}`, {
      method: 'DELETE',
    }),

  listJobs: () => request<JobListItem[]>('/jobs'),
  createJob: (body: FormData) =>
    request<{ job_id: string }>('/jobs', {
      method: 'POST',
      body,
    }),
  inspectEpubChapters: (body: FormData) =>
    request<EpubChaptersResponse>('/jobs/epub-chapters', {
      method: 'POST',
      body,
    }),
  startAiSplitEpubChapters: (body: FormData) =>
    request<EpubAiSplitTaskCreated>('/jobs/epub-chapters/ai-split', {
      method: 'POST',
      body,
    }),
  getAiSplitEpubChapters: (taskId: string) => request<EpubAiSplitProgressResponse>(`/jobs/epub-chapters/ai-split/${taskId}`),
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
  pauseJob: (id: string) =>
    request<JobDetail>(`/jobs/${id}/pause`, {
      method: 'POST',
    }),
  resumeJob: (id: string) =>
    request<JobDetail>(`/jobs/${id}/resume`, {
      method: 'POST',
    }),
  updateJobProvider: (id: string, providerConfigId: string) =>
    request<JobDetail>(`/jobs/${id}/provider`, {
      method: 'POST',
      body: JSON.stringify({ provider_config_id: providerConfigId }),
    }),
  getDownload: (id: string) => request<DownloadInfo>(`/jobs/${id}/download`),
  downloadJobFile: (id: string, filename: string) => download(`/jobs/${id}/download-file`, filename),

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
