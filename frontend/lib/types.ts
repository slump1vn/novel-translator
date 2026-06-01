export type Provider = 'openai' | 'deepseek' | 'ollama'

export type JobStatus = 'queued' | 'processing' | 'awaiting_glossary_review' | 'completed' | 'failed' | 'cancelled' | 'partial_success'

export interface JobListItem {
  id: string
  job_name: string
  status: JobStatus
  progress_percent: number
  output_format: string
  created_at: string
}

export interface EpubChapter {
  index: number
  title: string
  path: string
  character_count: number
}

export interface ProviderConfig {
  id: string
  config_name: string
  provider: Provider
  base_url: string | null
  model_name: string
  is_default: boolean
  stream: boolean
  options: ModelOptions
  parallelism: number
  retry_limit: number
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
  progress_percent: number
  started_at: string | null
  ended_at: string | null
  error_message: string | null
}

export interface JobLog {
  id: string
  step_name: string | null
  level: 'debug' | 'info' | 'warning' | 'error' | string
  message: string
  progress_percent: number | null
  created_at: string
}

export interface DownloadInfo {
  filename: string
  download_url: string
  content_type: string
}

export interface GlossaryEntry {
  id: string
  source_term: string
  translated_term: string
  category: string
  note: string | null
  occurrence_count: number
  position: number
}

export interface GlossaryEntryInput {
  id?: string | null
  source_term: string
  translated_term: string
  category: string
  note?: string | null
  occurrence_count: number
  position: number
}

export interface ProviderConfigCreate {
  config_name: string
  provider: Provider
  api_key?: string
  base_url?: string
  model_name: string
  is_default: boolean
  stream: boolean
  options: ModelOptions
  parallelism: number
  retry_limit: number
}

export interface ModelOptions {
  temperature: number
  num_predict: number
  repeat_penalty: number
  timeout: number
}

export type ProviderConfigUpdate = ProviderConfigCreate

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

export interface ProviderModelsResult {
  models: string[]
}

export interface TranslationPreviewRequest {
  text: string
  provider_config_id?: string
}

export interface TranslationPreviewResponse {
  translated_text: string
  provider_config_id: string
  provider: Provider
  model_name: string
  source_characters: number
  cleaned_characters: number
  chunk_count: number
  removed_noise_lines: number
  elapsed_ms: number
}

export interface TranslationSettings {
  system_prompt: string
  default_system_prompt: string
}

export interface TranslationSettingsUpdate {
  system_prompt: string
}
