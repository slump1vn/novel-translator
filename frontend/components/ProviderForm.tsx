'use client'

import { useState, type FormEvent } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import { api } from '@/lib/api'
import type { Provider, ProviderConfig, ProviderConfigCreate } from '@/lib/types'

interface Props {
  onSubmit: (body: ProviderConfigCreate) => Promise<void>
  onCancel: () => void
  initialConfig?: ProviderConfig
  submitLabel?: string
}

interface ProviderMeta {
  value: Provider
  label: string
  defaultModel: string
  defaultBaseUrl?: string
  needsKey: boolean
}

interface FormState {
  config_name: string
  api_key: string
  base_url: string
  model_name: string
  is_default: boolean
  stream: boolean
  options_temperature: number
  options_num_predict: number
  options_repeat_penalty: number
  options_timeout: number
  parallelism: number
  retry_limit: number
}

const PROVIDERS: ProviderMeta[] = [
  { value: 'openai', label: 'OpenAI', defaultModel: 'gpt-4.1-mini', needsKey: true },
  { value: 'deepseek', label: 'DeepSeek', defaultModel: 'deepseek-chat', needsKey: true },
  { value: 'ollama', label: 'Ollama (local)', defaultModel: 'qwen3:8b', defaultBaseUrl: 'http://localhost:11434/v1', needsKey: false },
]

export default function ProviderForm({ onSubmit, onCancel, initialConfig, submitLabel = 'Lưu provider' }: Props) {
  const isEditing = Boolean(initialConfig)
  const [provider, setProvider] = useState<Provider>(initialConfig?.provider || 'openai')
  const [form, setForm] = useState<FormState>({
    config_name: initialConfig?.config_name || '',
    api_key: '',
    base_url: initialConfig?.base_url || '',
    model_name: initialConfig?.model_name || 'gpt-4.1-mini',
    is_default: initialConfig?.is_default || false,
    stream: initialConfig?.stream ?? false,
    options_temperature: initialConfig?.options?.temperature ?? 0.2,
    options_num_predict: initialConfig?.options?.num_predict ?? 2048,
    options_repeat_penalty: initialConfig?.options?.repeat_penalty ?? 1.2,
    options_timeout: initialConfig?.options?.timeout ?? 28800000,
    parallelism: initialConfig?.parallelism ?? 2,
    retry_limit: initialConfig?.retry_limit ?? 3,
  })
  const [loading, setLoading] = useState(false)
  const [loadingModels, setLoadingModels] = useState(false)
  const [models, setModels] = useState<string[]>([])
  const [modelError, setModelError] = useState('')
  const [error, setError] = useState('')

  const providerMeta = PROVIDERS.find((item) => item.value === provider)!
  const canListModels = Boolean(initialConfig?.id && providerMeta.needsKey && initialConfig.provider === provider)
  const setField = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((state) => ({ ...state, [key]: value }))

  const handleProviderChange = (nextProvider: Provider) => {
    const meta = PROVIDERS.find((item) => item.value === nextProvider)!
    setProvider(nextProvider)
    setForm((state) => ({
      ...state,
      model_name: meta.defaultModel,
      base_url: meta.defaultBaseUrl || '',
      api_key: meta.needsKey ? state.api_key : '',
    }))
    setModels([])
    setModelError('')
  }

  const loadModels = async () => {
    if (!initialConfig?.id) return
    setLoadingModels(true)
    setModelError('')
    try {
      const result = await api.listProviderModels(initialConfig.id)
      setModels(result.models)
      if (!result.models.length) {
        setModelError('Provider không trả về model nào')
      }
    } catch (err) {
      setModelError(err instanceof Error ? err.message : 'Không thể tải danh sách model')
    } finally {
      setLoadingModels(false)
    }
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      await onSubmit({
        config_name: form.config_name,
        provider,
        model_name: form.model_name,
        is_default: form.is_default,
        stream: form.stream,
        options: {
          temperature: form.options_temperature,
          num_predict: form.options_num_predict,
          repeat_penalty: form.options_repeat_penalty,
          timeout: form.options_timeout,
        },
        parallelism: form.parallelism,
        retry_limit: form.retry_limit,
        base_url: form.base_url || undefined,
        api_key: form.api_key || undefined,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể lưu provider')
    } finally {
      setLoading(false)
    }
  }

  const inputClass = 'w-full rounded-lg border px-3 py-2 text-sm outline-none transition-all focus:ring-1'
  const inputStyle = { background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }
  const labelClass = 'text-xs font-medium block mb-1'

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className={labelClass} style={{ color: 'var(--color-muted)' }}>
          Provider
        </label>
        <div className="flex gap-2 flex-wrap">
          {PROVIDERS.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => handleProviderChange(item.value)}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
              style={
                provider === item.value
                  ? { background: 'var(--color-brand)', color: '#fff' }
                  : { background: 'var(--color-bg)', color: 'var(--color-muted)', border: '1px solid var(--color-border)' }
              }
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className={labelClass} style={{ color: 'var(--color-muted)' }}>
            Tên config *
          </label>
          <input required className={inputClass} style={inputStyle} placeholder="VD: GPT-4.1-mini chính" value={form.config_name} onChange={(event) => setField('config_name', event.target.value)} />
        </div>
        <div>
          <label className={labelClass} style={{ color: 'var(--color-muted)' }}>
            Model *
          </label>
          <input required className={inputClass} style={inputStyle} placeholder={providerMeta.defaultModel} value={form.model_name} onChange={(event) => setField('model_name', event.target.value)} />
        </div>
      </div>

      {providerMeta.needsKey && (
        <div className="space-y-2">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <button
              type="button"
              onClick={loadModels}
              disabled={!canListModels || loadingModels}
              className="flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-opacity hover:opacity-70 disabled:opacity-40"
              style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
            >
              {loadingModels ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              Tải danh sách model
            </button>
            {!canListModels && (
              <span className="text-xs" style={{ color: 'var(--color-muted)' }}>
                Lưu provider/token trước rồi mở sửa để tải model.
              </span>
            )}
          </div>
          {models.length > 0 && (
            <select
              value={form.model_name}
              onChange={(event) => setField('model_name', event.target.value)}
              className={inputClass}
              style={inputStyle}
              aria-label="Chọn model từ provider"
            >
              {!models.includes(form.model_name) && <option value={form.model_name}>{form.model_name}</option>}
              {models.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          )}
          {modelError && (
            <p className="text-xs rounded-lg px-3 py-2" style={{ background: '#a12c7b11', color: '#a12c7b' }}>
              {modelError}
            </p>
          )}
        </div>
      )}

      {providerMeta.needsKey && (
        <div>
          <label className={labelClass} style={{ color: 'var(--color-muted)' }}>
            API Key {isEditing ? '(để trống để giữ key hiện tại)' : '*'}
          </label>
          <input
            required={!isEditing}
            type="password"
            className={inputClass}
            style={inputStyle}
            placeholder={isEditing ? 'Giữ nguyên API key hiện tại' : 'sk-...'}
            value={form.api_key}
            onChange={(event) => setField('api_key', event.target.value)}
          />
        </div>
      )}

      <div>
        <label className={labelClass} style={{ color: 'var(--color-muted)' }}>
          Base URL {provider === 'ollama' ? '(bắt buộc nếu chạy ngoài container)' : '(tuỳ chọn)'}
        </label>
        <input
          className={inputClass}
          style={inputStyle}
          placeholder={providerMeta.defaultBaseUrl || 'Để trống dùng mặc định'}
          value={form.base_url}
          onChange={(event) => setField('base_url', event.target.value)}
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <div>
          <label className={labelClass} style={{ color: 'var(--color-muted)' }}>
            Temperature
          </label>
          <input type="number" step={0.1} min={0} max={2} className={inputClass} style={inputStyle} value={form.options_temperature} onChange={(event) => setField('options_temperature', Number(event.target.value))} />
        </div>
        <div>
          <label className={labelClass} style={{ color: 'var(--color-muted)' }}>
            Num Predict
          </label>
          <input type="number" step={1} min={1} max={200000} className={inputClass} style={inputStyle} value={form.options_num_predict} onChange={(event) => setField('options_num_predict', Number(event.target.value))} />
        </div>
        <div>
          <label className={labelClass} style={{ color: 'var(--color-muted)' }}>
            Repeat Penalty
          </label>
          <input type="number" step={0.1} min={0.1} max={10} className={inputClass} style={inputStyle} value={form.options_repeat_penalty} onChange={(event) => setField('options_repeat_penalty', Number(event.target.value))} />
        </div>
        <div>
          <label className={labelClass} style={{ color: 'var(--color-muted)' }}>
            Timeout (ms)
          </label>
          <input type="number" step={1000} min={1000} className={inputClass} style={inputStyle} value={form.options_timeout} onChange={(event) => setField('options_timeout', Number(event.target.value))} />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="flex items-center gap-2 rounded-lg border px-3 py-2" style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)' }}>
          <input id="stream" type="checkbox" checked={form.stream} onChange={(event) => setField('stream', event.target.checked)} className="rounded" />
          <label htmlFor="stream" className="text-sm" style={{ color: 'var(--color-text)' }}>
            Stream
          </label>
        </div>
        <div>
          <label className={labelClass} style={{ color: 'var(--color-muted)' }}>
            Parallelism
          </label>
          <input type="number" step={1} min={1} max={20} className={inputClass} style={inputStyle} value={form.parallelism} onChange={(event) => setField('parallelism', Number(event.target.value))} />
        </div>
      </div>

      <div className="flex items-center gap-2">
        <input id="is_default" type="checkbox" checked={form.is_default} onChange={(event) => setField('is_default', event.target.checked)} className="rounded" />
        <label htmlFor="is_default" className="text-sm" style={{ color: 'var(--color-text)' }}>
          Đặt làm provider mặc định
        </label>
      </div>

      {error && (
        <p className="text-sm rounded-lg px-3 py-2" style={{ background: '#a12c7b11', color: '#a12c7b' }}>
          {error}
        </p>
      )}

      <div className="flex gap-3 pt-2">
        <button
          type="submit"
          disabled={loading}
          className="flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold text-white disabled:opacity-40 transition-colors"
          style={{ background: 'var(--color-brand)' }}
        >
          {loading ? (
            <>
              <Loader2 size={14} className="animate-spin" /> Đang lưu...
            </>
          ) : (
            submitLabel
          )}
        </button>
        <button type="button" onClick={onCancel} className="px-4 py-2 rounded-lg text-sm transition-opacity hover:opacity-70" style={{ color: 'var(--color-muted)', background: 'var(--color-bg)' }}>
          Hủy
        </button>
      </div>
    </form>
  )
}
