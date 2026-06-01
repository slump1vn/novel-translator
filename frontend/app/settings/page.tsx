'use client'

import { useEffect, useState } from 'react'
import { AlertCircle, CheckCircle2, KeyRound, Loader2, Pencil, Plus, RotateCcw, Save, Star, Trash2, UserPlus, Wifi } from 'lucide-react'
import { api } from '@/lib/api'
import type { AuthUser, ProviderConfig, ProviderConfigCreate, ProviderConfigUpdate, UserRole } from '@/lib/types'
import NavBar from '@/components/NavBar'
import ProviderForm from '@/components/ProviderForm'

export default function SettingsPage() {
  const [configs, setConfigs] = useState<ProviderConfig[]>([])
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null)
  const [users, setUsers] = useState<AuthUser[]>([])
  const [showForm, setShowForm] = useState(false)
  const [editingConfig, setEditingConfig] = useState<ProviderConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [defaultSystemPrompt, setDefaultSystemPrompt] = useState('')
  const [savingPrompt, setSavingPrompt] = useState(false)
  const [promptSaved, setPromptSaved] = useState(false)
  const [settingDefault, setSettingDefault] = useState<Record<string, boolean>>({})
  const [testing, setTesting] = useState<Record<string, boolean>>({})
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; latency_ms: number | null }>>({})
  const [newUser, setNewUser] = useState({ username: '', password: '', role: 'user' as UserRole, is_active: true })
  const [userPasswords, setUserPasswords] = useState<Record<string, string>>({})

  const load = async () => {
    try {
      setError('')
      const [providerConfigs, translationSettings, me] = await Promise.all([api.listProviderConfigs(), api.getTranslationSettings(), api.me()])
      setConfigs(providerConfigs)
      setCurrentUser(me)
      setSystemPrompt(translationSettings.system_prompt)
      setDefaultSystemPrompt(translationSettings.default_system_prompt)
      if (me.role === 'super_admin') {
        setUsers(await api.listUsers())
      }
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
    setEditingConfig(null)
    await load()
  }

  const handleUpdate = async (body: ProviderConfigUpdate) => {
    if (!editingConfig) return
    await api.updateProviderConfig(editingConfig.id, body)
    setShowForm(false)
    setEditingConfig(null)
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

  const handleSetDefault = async (cfg: ProviderConfig) => {
    if (cfg.is_default) return
    setSettingDefault((state) => ({ ...state, [cfg.id]: true }))
    setError('')
    try {
      const updated = await api.setDefaultProviderConfig(cfg.id)
      setConfigs((items) => items.map((item) => ({ ...item, is_default: item.id === updated.id })))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể đổi model mặc định')
    } finally {
      setSettingDefault((state) => ({ ...state, [cfg.id]: false }))
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

  const handleCreateUser = async () => {
    if (!newUser.username.trim() || !newUser.password) return
    setError('')
    try {
      await api.createUser({ ...newUser, username: newUser.username.trim().toLowerCase() })
      setNewUser({ username: '', password: '', role: 'user', is_active: true })
      setUsers(await api.listUsers())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể tạo user')
    }
  }

  const handleUpdateUser = async (user: AuthUser, patch: { role?: UserRole; is_active?: boolean; password?: string }) => {
    setError('')
    try {
      await api.updateUser(user.id, patch)
      setUsers(await api.listUsers())
      if (patch.password) setUserPasswords((state) => ({ ...state, [user.id]: '' }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể cập nhật user')
    }
  }

  const handleDeleteUser = async (user: AuthUser) => {
    if (!confirm(`Xóa user ${user.username}?`)) return
    setError('')
    try {
      await api.deleteUser(user.id)
      setUsers(await api.listUsers())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể xóa user')
    }
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
            onClick={() => {
              setEditingConfig(null)
              setShowForm((value) => !value)
            }}
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
              Áp dụng cho mọi chức năng dịch và mọi model AI.
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

        {currentUser?.role === 'super_admin' && (
          <section className="mb-6 rounded-2xl border p-5 space-y-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
            <div>
              <h2 className="font-semibold" style={{ color: 'var(--color-text)' }}>
                Quản lý user
              </h2>
            </div>
            <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_160px_130px_120px]">
              <input
                value={newUser.username}
                onChange={(event) => setNewUser((state) => ({ ...state, username: event.target.value }))}
                placeholder="username"
                className="rounded-lg border px-3 py-2 text-sm"
                style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
              />
              <input
                type="password"
                value={newUser.password}
                onChange={(event) => setNewUser((state) => ({ ...state, password: event.target.value }))}
                placeholder="password"
                className="rounded-lg border px-3 py-2 text-sm"
                style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
              />
              <select
                value={newUser.role}
                onChange={(event) => setNewUser((state) => ({ ...state, role: event.target.value as UserRole }))}
                className="rounded-lg border px-3 py-2 text-sm"
                style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
              >
                <option value="user">user</option>
                <option value="admin">admin</option>
                <option value="super_admin">super_admin</option>
              </select>
              <button
                type="button"
                onClick={handleCreateUser}
                disabled={!newUser.username.trim() || !newUser.password}
                className="inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-white disabled:opacity-40"
                style={{ background: 'var(--color-brand)' }}
              >
                <UserPlus size={14} /> Thêm
              </button>
            </div>
            <div className="space-y-2">
              {users.map((user) => (
                <div key={user.id} className="grid gap-2 rounded-xl border p-3 md:grid-cols-[minmax(0,1fr)_140px_110px_minmax(0,180px)_auto]" style={{ borderColor: 'var(--color-border)' }}>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                      {user.username}
                    </p>
                    <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
                      {user.is_active ? 'active' : 'inactive'}
                    </p>
                  </div>
                  <select
                    value={user.role}
                    onChange={(event) => handleUpdateUser(user, { role: event.target.value as UserRole })}
                    className="rounded-lg border px-2 py-2 text-sm"
                    style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
                  >
                    <option value="user">user</option>
                    <option value="admin">admin</option>
                    <option value="super_admin">super_admin</option>
                  </select>
                  <button
                    type="button"
                    onClick={() => handleUpdateUser(user, { is_active: !user.is_active })}
                    className="rounded-lg px-3 py-2 text-sm transition-opacity hover:opacity-70"
                    style={{ background: user.is_active ? '#437a2211' : '#a12c7b11', color: user.is_active ? '#437a22' : '#a12c7b' }}
                  >
                    {user.is_active ? 'Khóa' : 'Mở khóa'}
                  </button>
                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={userPasswords[user.id] || ''}
                      onChange={(event) => setUserPasswords((state) => ({ ...state, [user.id]: event.target.value }))}
                      placeholder="mật khẩu mới"
                      className="min-w-0 flex-1 rounded-lg border px-2 py-2 text-sm"
                      style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
                    />
                    <button
                      type="button"
                      title="Đổi mật khẩu"
                      onClick={() => handleUpdateUser(user, { password: userPasswords[user.id] })}
                      disabled={!userPasswords[user.id]}
                      className="inline-flex h-10 w-10 items-center justify-center rounded-lg disabled:opacity-40"
                      style={{ background: 'var(--color-bg)', color: 'var(--color-muted)' }}
                    >
                      <KeyRound size={14} />
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDeleteUser(user)}
                    disabled={user.id === currentUser.id}
                    className="inline-flex h-10 w-10 items-center justify-center rounded-lg disabled:opacity-40"
                    style={{ background: '#a12c7b11', color: '#a12c7b' }}
                    title="Xóa user"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}

        {showForm && (
          <div className="mb-6 rounded-2xl border p-6" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
            <h2 className="font-semibold mb-4" style={{ color: 'var(--color-text)' }}>
              {editingConfig ? 'Chỉnh sửa provider' : 'Provider mới'}
            </h2>
            <ProviderForm
              key={editingConfig?.id || 'new'}
              initialConfig={editingConfig || undefined}
              submitLabel={editingConfig ? 'Lưu thay đổi' : 'Lưu provider'}
              onSubmit={editingConfig ? handleUpdate : handleCreate}
              onCancel={() => {
                setShowForm(false)
                setEditingConfig(null)
              }}
            />
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
                      {cfg.provider} · {cfg.model_name} · num_predict: {cfg.options.num_predict} · repeat_penalty: {cfg.options.repeat_penalty}
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
                      onClick={() => {
                        setEditingConfig(cfg)
                        setShowForm(true)
                      }}
                      className="p-2 rounded-lg text-xs transition-opacity hover:opacity-70 flex items-center gap-1"
                      style={{ background: 'var(--color-bg)', color: 'var(--color-muted)' }}
                    >
                      <Pencil size={13} /> Sửa
                    </button>
                    <button
                      onClick={() => handleSetDefault(cfg)}
                      disabled={cfg.is_default || settingDefault[cfg.id]}
                      className="p-2 rounded-lg text-xs transition-opacity hover:opacity-70 disabled:opacity-40 flex items-center gap-1"
                      style={{
                        background: cfg.is_default ? '#01696f22' : 'var(--color-bg)',
                        color: cfg.is_default ? 'var(--color-brand)' : 'var(--color-muted)',
                      }}
                    >
                      {settingDefault[cfg.id] ? <Loader2 size={13} className="animate-spin" /> : <Star size={13} />}
                      {cfg.is_default ? 'Đang mặc định' : 'Đặt mặc định'}
                    </button>
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
