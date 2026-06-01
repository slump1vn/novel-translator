'use client'

import { useState, type FormEvent } from 'react'
import { Loader2 } from 'lucide-react'
import type { Provider, ProviderConfigCreate } from '@/lib/types'

interface Props {
  onSubmit: (body: ProviderConfigCreate) => Promise<void>
  onCancel: () => void
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
  temperature: number
  max_tokens: number
  parallelism: number
  retry_limit: number
  timeout_seconds: number
  system_prompt: string
}

const PROVIDERS: ProviderMeta[] = [
  { value: 'openai', label: 'OpenAI', defaultModel: 'gpt-4.1-mini', needsKey: true },
  { value: 'deepseek', label: 'DeepSeek', defaultModel: 'deepseek-chat', needsKey: true },
  { value: 'ollama', label: 'Ollama (local)', defaultModel: 'qwen3:8b', defaultBaseUrl: 'http://localhost:11434/v1', needsKey: false },
]

const DEFAULT_SYSTEM_PROMPT = `Bạn là dịch giả chuyên nghiệp dịch truyện tiên hiệp/võ hiệp Trung Quốc sang tiếng Việt.
Mục tiêu là tạo bản dịch tiếng Việt tự nhiên, dễ đọc, đúng văn phong tiểu thuyết, không dịch sát từng chữ.
Quy tắc bắt buộc:
- Dịch đầy đủ ý của đoạn nguồn, không tóm tắt, không thêm nội dung ngoài truyện.
- Giữ ổn định tên nhân vật, địa danh, môn phái, công pháp và cảnh giới theo cách Hán-Việt phổ biến.
- Chuyển câu Trung sang câu tiếng Việt mượt; tránh các cụm dịch máy như "một bộ ... bộ dáng", "thủ thời gian", "là dạng gì tử".
- Giữ cấu trúc đoạn văn và xuống dòng khi hợp lý.
- Bỏ qua dòng quảng cáo, watermark, link tải truyện, tên website nguồn.
- Không xuất suy luận, không ghi chú, không markdown, không thẻ <think>, không token /think.
- Chỉ trả về bản dịch tiếng Việt.`

export default function ProviderForm({ onSubmit, onCancel }: Props) {
  const [provider, setProvider] = useState<Provider>('openai')
  const [form, setForm] = useState<FormState>({
    config_name: '',
    api_key: '',
    base_url: '',
    model_name: 'gpt-4.1-mini',
    is_default: false,
    temperature: 0.2,
    max_tokens: 4096,
    parallelism: 2,
    retry_limit: 3,
    timeout_seconds: 120,
    system_prompt: DEFAULT_SYSTEM_PROMPT,
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const providerMeta = PROVIDERS.find((item) => item.value === provider)!
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
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      await onSubmit({
        ...form,
        provider,
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
        <div>
          <label className={labelClass} style={{ color: 'var(--color-muted)' }}>
            API Key *
          </label>
          <input required type="password" className={inputClass} style={inputStyle} placeholder="sk-..." value={form.api_key} onChange={(event) => setField('api_key', event.target.value)} />
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

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div>
          <label className={labelClass} style={{ color: 'var(--color-muted)' }}>
            Temperature
          </label>
          <input type="number" step={0.1} min={0} max={2} className={inputClass} style={inputStyle} value={form.temperature} onChange={(event) => setField('temperature', Number(event.target.value))} />
        </div>
        <div>
          <label className={labelClass} style={{ color: 'var(--color-muted)' }}>
            Parallelism
          </label>
          <input type="number" step={1} min={1} max={20} className={inputClass} style={inputStyle} value={form.parallelism} onChange={(event) => setField('parallelism', Number(event.target.value))} />
        </div>
        <div>
          <label className={labelClass} style={{ color: 'var(--color-muted)' }}>
            Max Tokens
          </label>
          <input type="number" step={512} min={256} max={200000} className={inputClass} style={inputStyle} value={form.max_tokens} onChange={(event) => setField('max_tokens', Number(event.target.value))} />
        </div>
      </div>

      <div>
        <label className={labelClass} style={{ color: 'var(--color-muted)' }}>
          System Prompt
        </label>
        <textarea rows={8} className={inputClass} style={inputStyle} value={form.system_prompt} onChange={(event) => setField('system_prompt', event.target.value)} />
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
            'Lưu provider'
          )}
        </button>
        <button type="button" onClick={onCancel} className="px-4 py-2 rounded-lg text-sm transition-opacity hover:opacity-70" style={{ color: 'var(--color-muted)', background: 'var(--color-bg)' }}>
          Hủy
        </button>
      </div>
    </form>
  )
}
