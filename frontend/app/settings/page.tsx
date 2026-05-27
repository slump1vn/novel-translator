'use client'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type { ProviderConfig, ProviderConfigCreate } from '@/lib/types'
import NavBar from '@/components/NavBar'
import ProviderForm from '@/components/ProviderForm'
import { Plus, Trash2, CheckCircle2, AlertCircle, Wifi } from 'lucide-react'

export default function SettingsPage() {
  const [configs, setConfigs] = useState<ProviderConfig[]>([])
  const [showForm, setShowForm] = useState(false)
  const [testing, setTesting] = useState<Record<string, boolean>>({})
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; latency_ms: number | null }>>({})

  const load = async () => { try { setConfigs(await api.listProviderConfigs()) } catch {} }
  useEffect(() => { load() }, [])

  const handleCreate = async (body: ProviderConfigCreate) => {
    await api.createProviderConfig(body)
    setShowForm(false)
    load()
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Xóa config này?')) return
    await api.deleteProviderConfig(id)
    load()
  }

  const handleTest = async (cfg: ProviderConfig) => {
    setTesting(t => ({ ...t, [cfg.id]: true }))
    try {
      const res = await api.testProviderConnection({ provider: cfg.provider, base_url: cfg.base_url || undefined, model_name: cfg.model_name })
      setTestResults(r => ({ ...r, [cfg.id]: { ok: res.ok, latency_ms: res.latency_ms } }))
    } catch { setTestResults(r => ({ ...r, [cfg.id]: { ok: false, latency_ms: null } })) }
    finally { setTesting(t => ({ ...t, [cfg.id]: false })) }
  }

  return (
    <div style={{ background: 'var(--color-bg)' }} className="min-h-screen">
      <NavBar />
      <main className="max-w-3xl mx-auto px-4 py-10">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold" style={{ color: 'var(--color-text)' }}>Cấu hình Provider</h1>
            <p className="text-sm mt-1" style={{ color: 'var(--color-muted)' }}>Quản lý API key và model dùng để dịch</p>
          </div>
          <button onClick={() => setShowForm(s => !s)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors"
            style={{ background: 'var(--color-brand)' }}>
            <Plus size={14} /> Thêm provider
          </button>
        </div>

        {showForm && (
          <div className="mb-6 rounded-2xl border p-6" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
            <h2 className="font-semibold mb-4" style={{ color: 'var(--color-text)' }}>Provider mới</h2>
            <ProviderForm onSubmit={handleCreate} onCancel={() => setShowForm(false)} />
          </div>
        )}

        {configs.length === 0 ? (
          <div className="text-center py-16 rounded-2xl border border-dashed" style={{ borderColor: 'var(--color-border)', color: 'var(--color-muted)' }}>
            <p className="text-4xl mb-3">🔑</p>
            <p className="font-medium">Chưa có provider. Thêm OpenAI, DeepSeek hoặc Ollama để bắt đầu dịch.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {configs.map(cfg => {
              const res = testResults[cfg.id]
              return (
                <div key={cfg.id} className="rounded-xl border p-4 flex items-center gap-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm" style={{ color: 'var(--color-text)' }}>{cfg.config_name}</span>
                      {cfg.is_default && <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: '#01696f22', color: '#01696f' }}>Mặc định</span>}
                    </div>
                    <p className="text-xs mt-0.5" style={{ color: 'var(--color-muted)' }}>{cfg.provider} · {cfg.model_name} · parallelism: {cfg.parallelism}</p>
                    {res && (
                      <p className="text-xs mt-1 flex items-center gap-1" style={{ color: res.ok ? '#437a22' : '#a12c7b' }}>
                        {res.ok ? <CheckCircle2 size={11} /> : <AlertCircle size={11} />}
                        {res.ok ? `Kết nối OK${res.latency_ms ? ` · ${res.latency_ms}ms` : ''}` : 'Kết nối thất bại'}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <button onClick={() => handleTest(cfg)} disabled={testing[cfg.id]}
                      className="p-2 rounded-lg text-xs transition-opacity hover:opacity-70 disabled:opacity-40 flex items-center gap-1"
                      style={{ background: 'var(--color-bg)', color: 'var(--color-muted)' }}>
                      <Wifi size={13} /> {testing[cfg.id] ? 'Test…' : 'Test'}
                    </button>
                    <button onClick={() => handleDelete(cfg.id)}
                      className="p-2 rounded-lg transition-opacity hover:opacity-70"
                      style={{ background: '#a12c7b11', color: '#a12c7b' }}>
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
