export type Provider = 'openai' | 'deepseek' | 'ollama'

export type JobStatus = 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled' | 'partial_success'

export interface JobListItem {
  id: string
  job_name: string
  status: JobStatus
  progress_percent: number
  output_format: string
  created_at: string
}

export interface ProviderConfig {
  id: string
  config_name: string
  provider: Provider
  base_url: string | null
  model_name: string
  is_default: boolean
  temperature: number
  max_tokens: number
  parallelism: number
  retry_limit: number
  timeout_seconds: number
  system_prompt: string | null
  created_at: string
  updated_at: string
}

export interface JobDetail extends JobListItem {
  current_step: string
  source_file: {
    filename: string
    content_type: string
    size_bytes: number
    bucket: string
    key: string
  } | null
  output_file: {
    filename: string
    content_type: string
    size_bytes: number
    bucket: string
    key: string
  } | null
  total_chunks: number | null
  translated_chunks: number
  failed_chunks: number
  error_message: string | null
  completed_at: string | null
  provider: ProviderConfig | null
}

export interface JobStep {
  step_name: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  started_at: string | null
  ended_at: string | null
  error_message: string | null
}

export interface DownloadInfo {
  filename: string
  download_url: string
  content_type: string
}

export interface ProviderConfigCreate {
  config_name: string
  provider: Provider
  api_key?: string
  base_url?: string
  model_name: string
  is_default: boolean
  temperature: number
  max_tokens: number
  parallelism: number
  retry_limit: number
  timeout_seconds: number
  system_prompt?: string
}

export interface ProviderConnectionTest {
  config_id?: string
  provider?: Provider
  api_key?: string
  base_url?: string
  model_name?: string
}

export interface ProviderConnectionResult {
  ok: boolean
  latency_ms: number | null
  message?: string | null
}
