'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { BookOpen, LogOut, Settings } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, clearAuthToken, getAuthToken } from '@/lib/api'
import type { AuthUser } from '@/lib/types'

export default function NavBar() {
  const path = usePathname()
  const router = useRouter()
  const [user, setUser] = useState<AuthUser | null>(null)
  const active = (href: string) =>
    path === href ? { color: 'var(--color-brand)', fontWeight: 600 } : { color: 'var(--color-muted)' }

  useEffect(() => {
    if (!getAuthToken()) {
      router.push('/login')
      return
    }
    api
      .me()
      .then(setUser)
      .catch(() => {
        clearAuthToken()
        router.push('/login')
      })
  }, [router])

  const logout = () => {
    clearAuthToken()
    router.push('/login')
  }

  return (
    <nav className="border-b sticky top-0 z-40 backdrop-blur-sm" style={{ background: 'var(--color-bg)', borderColor: 'var(--color-border)' }}>
      <div className="max-w-4xl mx-auto px-4 h-14 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 font-bold" style={{ color: 'var(--color-brand)' }}>
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none" aria-label="ConvertVN">
            <rect width="28" height="28" rx="7" fill="#01696f" />
            <path d="M7 14 C7 9.5 10.5 7 14 7 C16.5 7 18.5 8.2 19.5 10" stroke="white" strokeWidth="2.2" strokeLinecap="round" />
            <path d="M21 14 C21 18.5 17.5 21 14 21 C11.5 21 9.5 19.8 8.5 18" stroke="white" strokeWidth="2.2" strokeLinecap="round" />
            <path d="M17 10 L19.5 10 L19.5 7.5" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M11 18 L8.5 18 L8.5 20.5" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span>ConvertVN</span>
        </Link>
        <div className="flex items-center gap-4">
          <Link href="/" className="flex items-center gap-1.5 text-sm transition-colors" style={active('/')}>
            <BookOpen size={15} /> Thư viện
          </Link>
          <Link href="/settings" className="flex items-center gap-1.5 text-sm transition-colors" style={active('/settings')}>
            <Settings size={15} /> Cài đặt
          </Link>
          {user && (
            <button
              type="button"
              onClick={logout}
              className="flex items-center gap-1.5 text-sm transition-opacity hover:opacity-70"
              style={{ color: 'var(--color-muted)' }}
            >
              <LogOut size={15} /> {user.username}
            </button>
          )}
        </div>
      </div>
    </nav>
  )
}
