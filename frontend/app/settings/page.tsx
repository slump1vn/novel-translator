'use client'

import { useEffect, useState } from 'react'
import { AlertCircle, CheckCircle2, Loader2, Plus, RotateCcw, Save, Trash2, Wifi } from 'lucide-react'
import { api } from '@/lib/api'
import type { ProviderConfig, ProviderConfigCreate } from '@/lib/types'
import NavBar from '@/components/NavBar'
import ProviderForm from '@/components/ProviderForm'

export default function SettingsPage() {
  const [configs, setConfigs] = useState<ProviderConfig[]>([])
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [defaultSystemPrompt, setDefaultSystemPrompt] = useState('')
  const [savingPrompt, setSavingPrompt] = useState(false)
  const [promptSaved, setPromptSaved] = useState(false)
  const [testing, setTesting] = useState<Record<string, boolean>>({})
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; latency_ms: number | null }>>({})

  const load = async () => {
    try {
      setError('')
      const [providerConfigs, translationSettings] = await Promise.all([api.listProviderConfigs(), api.getTranslationSettings()])
      setConfigs(providerConfigs)
      setSystemPrompt(translationSettings.system_prompt)
      setDefaultSystemPrompt(translationSettings.default_system_prompt)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể tải cài đặt')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const handleCreate = async (body: ProviderConfigCreate) => {
    await api.createProviderConfig(body)
    setShowForm(false)
    await load()
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Xóa config này?')) return
    setError('')
    try {
      await api.deleteProviderConfig(id)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể xóa provider')
    }
  }

  const handleTest = async (cfg: ProviderConfig) => {
    setTesting((state) => ({ ...state, [cfg.id]: true }))
    try {
      const result = await api.testProviderConnection({ config_id: cfg.id })
      setTestResults((state) => ({ ...state, [cfg.id]: { ok: result.ok, latency_ms: result.latency_ms } }))
    } catch {
      setTestResults((state) => ({ ...state, [cfg.id]: { ok: false, latency_ms: null } }))
    } finally {
      setTesting((state) => ({ ...state, [cfg.id]: false }))
    }
  }

  const handleSavePrompt = async () => {
    const prompt = systemPrompt.trim()
    if (!prompt) {
      setError('System prompt không được để trống')
      return
    }
    setSavingPrompt(true)
    setPromptSaved(false)
    setError('')
    try {
      const settings = await api.updateTranslationSettings({ system_prompt: prompt })
      setSystemPrompt(settings.system_prompt)
      setDefaultSystemPrompt(settings.default_system_prompt)
      setPromptSaved(true)
      window.setTimeout(() => setPromptSaved(false), 1800)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể lưu system prompt')
    } finally {
      setSavingPrompt(false)
    }
  }

  const handleResetPrompt = () => {
    setSystemPrompt(defaultSystemPrompt)
    setPromptSaved(false)
  }

  return (
    <div style={{ background: 'var(--color-bg)' }} className="min-h-screen">
      <NavBar />
      <main className="max-w-4xl mx-auto px-4 py-10">
        <div className="flex items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold" style={{ color: 'var(--color-text)' }}>
              Cài đặt dịch thuật
            </h1>
            <p className="text-sm mt-1" style={{ color: 'var(--color-muted)' }}>
              Quản lý system prompt, API key và model dùng để dịch
            </p>
          </div>
          <button
            onClick={() => setShowForm((value) => !value)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors"
            style={{ background: 'var(--color-brand)' }}
          >
            <Plus size={14} /> Thêm provider
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-lg px-3 py-2 text-sm" style={{ background: '#a12c7b11', color: '#a12c7b' }}>
            {error}
          </div>
        )}

        <section className="mb-6 rounded-2xl border p-5 space-y-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
          <div>
            <h2 className="font-semibold" style={{ color: 'var(--color-text)' }}>
              System prompt
            </h2>
            <p className="text-xs mt-1" style={{ color: 'var(--color-muted)' }}>
              Áp dụng cho mọi chức năng dịch và mọi provider/model AI.
            </p>
          </div>
          <textarea
            rows={10}
            value={systemPrompt}
            disabled={loading || savingPrompt}
            onChange={(event) => {
              setSystemPrompt(event.target.value)
              setPromptSaved(false)
            }}
            className="w-full resize-y rounded-xl border p-3 text-sm leading-6 outline-none transition-all focus:ring-1 disabled:opacity-60"
            style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
          />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-xs" style={{ color: promptSaved ? '#437a22' : 'var(--color-muted)' }}>
              {promptSaved ? 'Đã lưu system prompt' : 'Prompt này được dùng khi upload file và khi dịch thử.'}
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleResetPrompt}
                disabled={loading || savingPrompt || !defaultSystemPrompt}
                className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-opacity hover:opacity-70 disabled:opacity-40"
                style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
              >
                <RotateCcw size={14} /> Khôi phục mặc định
              </button>
              <button
                type="button"
                onClick={handleSavePrompt}
                disabled={loading || savingPrompt}
                className="flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold text-white transition-opacity disabled:opacity-40"
                style={{ background: 'var(--color-brand)' }}
              >
                {savingPrompt ? (
                  <>
                    <Loader2 size={14} className="animate-spin" /> Đang lưu...
                  </>
                ) : (
                  <>
                    <Save size={14} /> Lưu prompt
                  </>
                )}
              </button>
            </div>
          </div>
        </section>

        {showForm && (
          <div className="mb-6 rounded-2xl border p-6" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
            <h2 className="font-semibold mb-4" style={{ color: 'var(--color-text)' }}>
              Provider mới
            </h2>
            <ProviderForm onSubmit={handleCreate} onCancel={() => setShowForm(false)} />
          </div>
        )}

        {loading ? (
          <div className="space-y-3">
            {[1, 2].map((item) => (
              <div key={item} className="h-20 rounded-xl animate-pulse" style={{ background: 'var(--color-surface)' }} />
            ))}
          </div>
        ) : configs.length === 0 && !error ? (
          <div
            className="text-center py-16 rounded-2xl border border-dashed"
            style={{ borderColor: 'var(--color-border)', color: 'var(--color-muted)' }}
          >
            <p className="font-medium">Chưa có provider. Thêm OpenAI, DeepSeek hoặc Ollama để bắt đầu dịch.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {configs.map((cfg) => {
              const result = testResults[cfg.id]
              return (
                <div
                  key={cfg.id}
                  className="rounded-xl border p-4 flex items-center gap-4"
                  style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm" style={{ color: 'var(--color-text)' }}>
                        {cfg.config_name}
                      </span>
                      {cfg.is_default && (
                        <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: '#01696f22', color: '#01696f' }}>
                          Mặc định
                        </span>
                      )}
                    </div>
                    <p className="text-xs mt-0.5" style={{ color: 'var(--color-muted)' }}>
                      {cfg.provider} · {cfg.model_name} · parallelism: {cfg.parallelism}
                    </p>
                    {result && (
                      <p className="text-xs mt-1 flex items-center gap-1" style={{ color: result.ok ? '#437a22' : '#a12c7b' }}>
                        {result.ok ? <CheckCircle2 size={11} /> : <AlertCircle size={11} />}
                        {result.ok ? `Kết nối OK${result.latency_ms ? ` · ${result.latency_ms}ms` : ''}` : 'Kết nối thất bại'}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleTest(cfg)}
                      disabled={testing[cfg.id]}
                      className="p-2 rounded-lg text-xs transition-opacity hover:opacity-70 disabled:opacity-40 flex items-center gap-1"
                      style={{ background: 'var(--color-bg)', color: 'var(--color-muted)' }}
                    >
                      <Wifi size={13} /> {testing[cfg.id] ? 'Test...' : 'Test'}
                    </button>
                    <button
                      onClick={() => handleDelete(cfg.id)}
                      className="p-2 rounded-lg transition-opacity hover:opacity-70"
                      style={{ background: '#a12c7b11', color: '#a12c7b' }}
                      aria-label={`Xóa ${cfg.config_name}`}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </main>
    </div>
  )
}
