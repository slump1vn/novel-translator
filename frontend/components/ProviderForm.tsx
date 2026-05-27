'use client'
import { useState } from 'react'
import type { ProviderConfigCreate, Provider } from '@/lib/types'
import { Loader2 } from 'lucide-react'

interface Props { onSubmit: (body: ProviderConfigCreate) => Promise<void>; onCancel: () => void }

const PROVIDERS: { value: Provider; label: string; defaultModel: string; needsKey: boolean }[] = [
  { value: 'openai', label: 'OpenAI', defaultModel: 'gpt-4.1-mini', needsKey: true },
  { value: 'deepseek', label: 'DeepSeek', defaultModel: 'deepseek-chat', needsKey: true },
  { value: 'ollama', label: 'Ollama (local)', defaultModel: 'qwen3:8b', needsKey: false },
]

const DEFAULT_SYSTEM_PROMPT = `Bạn là dịch giả chuyên nghiệp dịch truyện tiên hiệp/võ hiệp Trung Quốc sang tiếng Việt.
Hãy dịch chính xác, giữ nguyên tên nhân vật, địa danh, môn phái và thuật ngữ tu luyện ở dạng Hán-Việt.
Giữ nguyên cấu trúc đoạn văn, xuống dòng và tiêu đề chương. Chỉ trả về bản dịch, không giải thích thêm.`

export default function ProviderForm({ onSubmit, onCancel }: Props) {
  const [provider, setProvider] = useState<Provider>('openai')
  const [form, setForm] = useState({
    config_name: '', api_key: '', base_url: '',
    model_name: 'gpt-4.1-mini', is_default: false,
    temperature: 0.3, max_tokens: 4096, parallelism: 2, retry_limit: 3, timeout_seconds: 120,
    system_prompt: DEFAULT_SYSTEM_PROMPT,
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const provMeta = PROVIDERS.find(p => p.value === provider)!
  const set = (k: string, v: any) => setForm(f => ({ ...f, [k]: v }))

  const handleProviderChange = (p: Provider) => {
    setProvider(p)
    const meta = PROVIDERS.find(x => x.value === p)!
    set('model_name', meta.defaultModel)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault(); setLoading(true); setError('')
    try {
      await onSubmit({ ...form, provider, base_url: form.base_url || undefined, api_key: form.api_key || undefined })
    } catch (e: any) { setError(e.message) }
    finally { setLoading(false) }
  }

  const inp = "w-full rounded-lg border px-3 py-2 text-sm outline-none transition-all focus:ring-1"
  const inpStyle = { background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }
  const label = "text-xs font-medium block mb-1"

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className={label} style={{ color: 'var(--color-muted)' }}>Provider</label>
        <div className="flex gap-2 flex-wrap">
          {PROVIDERS.map(p => (
            <button key={p.value} type="button" onClick={() => handleProviderChange(p.value)}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
              style={provider === p.value
                ? { background: 'var(--color-brand)', color: '#fff' }
                : { background: 'var(--color-bg)', color: 'var(--color-muted)', border: '1px solid var(--color-border)' }
              }>{p.label}</button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={label} style={{ color: 'var(--color-muted)' }}>Tên config *</label>
          <input required className={inp} style={inpStyle} placeholder="VD: GPT-4.1-mini chính" value={form.config_name} onChange={e => set('config_name', e.target.value)} />
        </div>
        <div>
          <label className={label} style={{ color: 'var(--color-muted)' }}>Model *</label>
          <input required className={inp} style={inpStyle} placeholder={provMeta.defaultModel} value={form.model_name} onChange={e => set('model_name', e.target.value)} />
        </div>
      </div>

      {provMeta.needsKey && (
        <div>
          <label className={label} style={{ color: 'var(--color-muted)' }}>API Key</label>
          <input type="password" className={inp} style={inpStyle} placeholder="sk-..." value={form.api_key} onChange={e => set('api_key', e.target.value)} />
        </div>
      )}

      <div>
        <label className={label} style={{ color: 'var(--color-muted)' }}>Base URL {provider === 'ollama' ? '(bắt buộc)' : '(tuỳ chọn)'}</label>
        <input className={inp} style={inpStyle}
          placeholder={provider === 'ollama' ? 'http://localhost:11434/v1/' : 'Để trống dùng mặc định'}
          value={form.base_url} onChange={e => set('base_url', e.target.value)} />
      </div>

      <div className="grid grid-cols-3 gap-3">
        {[
          ['Temperature', 'temperature', 0.1, 0, 1],
          ['Parallelism', 'parallelism', 1, 1, 10],
          ['Max Tokens', 'max_tokens', 512, 256, 16384],
        ].map(([lbl, key, step, min, max]) => (
          <div key={key as string}>
            <label className={label} style={{ color: 'var(--color-muted)' }}>{lbl}</label>
            <input type="number" step={step} min={min} max={max} className={inp} style={inpStyle}
              value={(form as any)[key as string]} onChange={e => set(key as string, Number(e.target.value))} />
          </div>
        ))}
      </div>

      <div>
        <label className={label} style={{ color: 'var(--color-muted)' }}>System Prompt (dịch tiên hiệp)</label>
        <textarea rows={4} className={inp} style={inpStyle} value={form.system_prompt} onChange={e => set('system_prompt', e.target.value)} />
      </div>

      <div className="flex items-center gap-2">
        <input id="is_default" type="checkbox" checked={form.is_default} onChange={e => set('is_default', e.target.checked)} className="rounded" />
        <label htmlFor="is_default" className="text-sm" style={{ color: 'var(--color-text)' }}>Đặt làm provider mặc định</label>
      </div>

      {error && <p className="text-sm rounded-lg px-3 py-2" style={{ background: '#a12c7b11', color: '#a12c7b' }}>⚠️ {error}</p>}

      <div className="flex gap-3 pt-2">
        <button type="submit" disabled={loading}
          className="flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold text-white disabled:opacity-40 transition-colors"
          style={{ background: 'var(--color-brand)' }}>
          {loading ? <><Loader2 size={14} className="animate-spin" /> Đang lưu…</> : 'Lưu provider'}
        </button>
        <button type="button" onClick={onCancel} className="px-4 py-2 rounded-lg text-sm transition-opacity hover:opacity-70" style={{ color: 'var(--color-muted)', background: 'var(--color-bg)' }}>
          Hủy
        </button>
      </div>
    </form>
  )
}
