'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Loader2, LogIn } from 'lucide-react'
import { api, setAuthToken } from '@/lib/api'

export default function LoginPage() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      const result = await api.login(username, password)
      setAuthToken(result.access_token)
      router.push('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể đăng nhập')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4" style={{ background: 'var(--color-bg)' }}>
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-2xl border p-6" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
        <div>
          <h1 className="text-xl font-bold" style={{ color: 'var(--color-text)' }}>
            Đăng nhập ConvertVN
          </h1>
        </div>
        <label className="block text-sm" style={{ color: 'var(--color-muted)' }}>
          User
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            className="mt-1 w-full rounded-lg border px-3 py-2"
            style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
            autoComplete="username"
          />
        </label>
        <label className="block text-sm" style={{ color: 'var(--color-muted)' }}>
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-1 w-full rounded-lg border px-3 py-2"
            style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
            autoComplete="current-password"
          />
        </label>
        {error && (
          <div className="rounded-lg px-3 py-2 text-sm" style={{ background: '#a12c7b11', color: '#a12c7b' }}>
            {error}
          </div>
        )}
        <button
          type="submit"
          disabled={loading || !username.trim() || !password}
          className="flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition-opacity disabled:opacity-40"
          style={{ background: 'var(--color-brand)' }}
        >
          {loading ? <Loader2 size={15} className="animate-spin" /> : <LogIn size={15} />}
          Đăng nhập
        </button>
      </form>
    </div>
  )
}
